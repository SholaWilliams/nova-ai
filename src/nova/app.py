"""Composition root (docs/03 §4): the only module allowed to import from every layer.

Builds and wires everything, owns startup ordering. Business logic, rendering, and
reasoning all live elsewhere — this module is wiring only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication

from nova.agent.agent import Agent
from nova.agent.executor import Executor
from nova.agent.planner import Planner, load_system_prompt
from nova.agent.router import Router
from nova.agent.stage_recorder import StageRecorder
from nova.agent.state import ConversationState
from nova.agent.worker import AgentWorker
from nova.core.config import (
    Secrets,
    Settings,
    get_data_dir,
    load_settings,
    save_settings,
    write_secret_to_env,
)
from nova.core.errors import SpeechError, install_excepthook
from nova.core.events import EventBus
from nova.core.logging import EventLogBridge, register_secrets, setup_logging
from nova.core.models import AssistantReply, ProviderStatus, Transcript
from nova.memory.service import MemoryService
from nova.providers.base import LLMProvider
from nova.providers.gemini import GeminiProvider
from nova.providers.groq import GroqProvider
from nova.providers.manager import ProviderManager
from nova.providers.openrouter import OpenRouterProvider
from nova.speech.audio import AudioCapture, list_input_devices, list_output_devices
from nova.speech.service import SpeechService
from nova.speech.stt.base import STTEngine
from nova.speech.stt.groq_whisper import GroqSTTEngine
from nova.speech.tts.pyttsx3_engine import Pyttsx3Engine
from nova.speech.tts.remote_tts import RemoteTTSEngine
from nova.speech.worker import SpeechInWorker, SpeechOutWorker
from nova.tools.app_launcher import AppLauncherTool
from nova.tools.base import ToolContext
from nova.tools.browser import BrowserTool
from nova.tools.calculator import CalculatorTool
from nova.tools.desktop_organizer import DesktopOrganizerTool
from nova.tools.file_opener import FileOpenerTool
from nova.tools.file_search import FileSearchTool
from nova.tools.memory_tool import MemoryTool
from nova.tools.registry import ToolRegistry
from nova.tools.weather import WeatherTool
from nova.ui.animations import set_reduced_motion
from nova.ui.main_window import MainWindow
from nova.ui.theme import build_stylesheet

_ENV_KEY_NAMES = {
    "gemini": "NOVA_GEMINI_API_KEY",
    "groq": "NOVA_GROQ_API_KEY",
    "openrouter": "NOVA_OPENROUTER_API_KEY",
}
_PROVIDER_LABELS = {"gemini": "Gemini", "groq": "Groq", "openrouter": "OpenRouter"}
_NO_STT_KEY_MESSAGE = "I can't hear right now — you can type to me!"


class _NoKeySTTEngine(STTEngine):
    """Placeholder when no Groq key is configured (TD-5: STT reuses the Groq key).

    `window.set_mic_available(False)` keeps the mic button disabled whenever this is in use,
    so `transcribe()` should never actually be reached — it exists purely so `SpeechService`
    always has a real `STTEngine` to construct with, mirroring `ProviderManager` always being
    buildable even with zero configured providers.
    """

    def transcribe(self, request_id: str, pcm: bytes, sample_rate: int) -> Transcript:
        del request_id, pcm, sample_rate
        raise SpeechError(
            "no Groq API key configured for STT", friendly_message=_NO_STT_KEY_MESSAGE
        )


def _build_provider(name: str, secrets: Secrets, settings: Settings) -> LLMProvider | None:
    """Construct the adapter for `name` iff a key is configured — never a FakeProvider."""
    if name == "gemini" and secrets.gemini_api_key:
        return GeminiProvider(api_key=secrets.gemini_api_key, model=settings.provider.gemini_model)
    if name == "groq" and secrets.groq_api_key:
        return GroqProvider(api_key=secrets.groq_api_key, model=settings.provider.groq_model)
    if name == "openrouter" and secrets.openrouter_api_key:
        return OpenRouterProvider(
            api_key=secrets.openrouter_api_key, model=settings.provider.openrouter_model
        )
    return None


def _build_providers(secrets: Secrets, settings: Settings) -> dict[str, LLMProvider]:
    providers: dict[str, LLMProvider] = {}
    for name in ("gemini", "groq", "openrouter"):
        provider = _build_provider(name, secrets, settings)
        if provider is not None:
            providers[name] = provider
    return providers


def _build_registry(secrets: Secrets, settings: Settings, data_dir: Path) -> ToolRegistry:
    """Register all eight v1.0 tools (docs/07). Order = SELECTING_TOOL display order."""
    desktop = (
        Path(secrets.desktop_override) if secrets.desktop_override else (Path.home() / "Desktop")
    )
    raw_extra = settings.model_extra or {}
    blocked = (raw_extra.get("browser") or {}).get("blocked_domains") or []

    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(WeatherTool())
    registry.register(BrowserTool(blocked_domains=blocked))
    registry.register(AppLauncherTool())
    registry.register(FileSearchTool())
    registry.register(FileOpenerTool())
    registry.register(DesktopOrganizerTool(desktop=desktop, manifest_dir=data_dir))
    registry.register(MemoryTool())
    return registry


def _build_speech_service(secrets: Secrets, settings: Settings, bus: EventBus) -> SpeechService:
    """docs/08 §1: engines behind ABCs, real pipeline events on the same bus as the agent."""
    stt_engine: STTEngine = (
        GroqSTTEngine(api_key=secrets.groq_api_key) if secrets.groq_api_key else _NoKeySTTEngine()
    )
    return SpeechService(
        stt_engine=stt_engine,
        primary_tts=RemoteTTSEngine(settings.voice.tts_base_url, settings.voice.tts_tenant_id),
        fallback_tts=Pyttsx3Engine(),
        audio_capture_factory=AudioCapture,
        bus=bus,
        vad_settings=settings.advanced.vad,
        voice_settings=settings.voice,
    )


def _show_first_run_if_needed(window: MainWindow, secrets: Secrets) -> None:
    """M6 T-603: if no API keys configured, show Settings on first run (docs/14 §2, FR-47).

    The user can still use the app (typed mode only) without keys; Settings guides key entry.
    """
    # ponytail: simple check, not exhaustive. Keys may be set via env vars directly without
    # the settings UI knowing — but the common first-run path is empty → Settings → key entry.
    if not secrets.gemini_api_key and not secrets.groq_api_key and not secrets.openrouter_api_key:
        window.settings_view.welcome_banner_visible = True
        window._stack.setCurrentIndex(1)  # _SETTINGS_PAGE (docs/05 §6.3, T-209)


def main() -> int:
    """Build and run the app. Returns the process exit code."""
    install_excepthook()  # active before anything else can go wrong

    data_dir = get_data_dir()
    secrets = Secrets.load(data_dir=data_dir)
    setup_logging(data_dir, level=secrets.log_level)
    register_secrets(secrets.gemini_api_key, secrets.groq_api_key, secrets.openrouter_api_key)

    settings = load_settings(data_dir / "settings.json")

    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(settings.ui.accent))
    set_reduced_motion(settings.ui.reduced_motion)

    bus = EventBus()
    EventLogBridge(bus)

    window = MainWindow(bus, settings)
    # M6 T-603: first-run welcome — auto-show Settings if no keys configured yet.
    _show_first_run_if_needed(window, secrets)

    provider_manager = ProviderManager(
        _build_providers(secrets, settings), settings.provider.active
    )
    registry = _build_registry(secrets, settings, data_dir)
    memory_service = MemoryService(data_dir)  # M5: replaces the M3 InMemoryFacade stub
    tool_ctx = ToolContext(settings=settings, memory=memory_service)
    executor = Executor(registry, bus, tool_ctx, tool_timeout_s=settings.advanced.tool_timeout_s)
    stage_recorder = StageRecorder(bus)
    agent = Agent(
        provider_manager,
        Planner(load_system_prompt()),
        Router(known_tool_names=registry.names),
        ConversationState(max_iterations=settings.advanced.max_iterations),
        bus,
        registry=registry,
        executor=executor,
        memory=memory_service,
        stage_recorder=stage_recorder,
    )
    worker = AgentWorker(agent)
    agent_thread = QThread()
    worker.moveToThread(agent_thread)
    agent_thread.start()

    window.submit_requested.connect(worker.handle_request)
    worker.reply_ready.connect(window.on_reply_ready)
    worker.request_rejected.connect(window.on_request_rejected)
    worker.request_cancelled.connect(window.on_request_cancelled)
    worker.failed.connect(window.on_request_failed)
    # Direct, not queued: `cancel_current()` must reach the worker's running `handle()` call
    # *while it's blocked* — a queued connection would sit undelivered in the worker thread's
    # own event queue until that blocking call returns, defeating cancellation (see
    # AgentWorker.cancel_current's docstring).
    window.cancel_requested.connect(worker.cancel_current, Qt.ConnectionType.DirectConnection)
    # Same reasoning as cancel: the worker thread is *blocked* inside the Executor's
    # confirmation gate — the answer must arrive as a direct call, not a queued slot.
    window.confirmation_answered.connect(worker.confirm, Qt.ConnectionType.DirectConnection)

    # M5: Memory View + History drawer (docs/05 §6.4/§6.5, FR-32/33/5/6)
    def _refresh_memory_view() -> None:
        window.set_memory_facts(memory_service.list_facts())

    def _refresh_sessions() -> None:
        window.set_sessions(memory_service.list_sessions())

    def _on_reply_landed(reply: AssistantReply) -> None:
        del reply
        _refresh_memory_view()
        _refresh_sessions()

    def _on_delete_fact_requested(fact_id: str) -> None:
        memory_service.delete_fact(fact_id)
        _refresh_memory_view()

    def _on_clear_facts_requested() -> None:
        memory_service.clear_facts()
        _refresh_memory_view()

    def _on_session_selected(session_id: str) -> None:
        window.show_session_replay(memory_service.load_session(session_id))

    def _on_new_conversation_requested() -> None:
        memory_service.start_new_session()
        _refresh_sessions()

    worker.reply_ready.connect(_on_reply_landed)
    window.delete_fact_requested.connect(_on_delete_fact_requested)
    window.clear_facts_requested.connect(_on_clear_facts_requested)
    window.session_selected.connect(_on_session_selected)
    # Queued (default), not direct — see Agent.new_conversation()'s docstring: nothing to
    # preempt mid-flight, so this doesn't need the cancel/confirm treatment.
    window.new_conversation_requested.connect(worker.new_conversation)
    window.new_conversation_requested.connect(_on_new_conversation_requested)

    _refresh_memory_view()
    _refresh_sessions()

    # M4: two more dedicated worker threads (docs/03 §5), the exact AgentWorker cross-thread
    # idiom applied twice more rather than a new one (TD-3).
    speech_service = _build_speech_service(secrets, settings, bus)
    speech_in_worker = SpeechInWorker(speech_service)
    speech_in_thread = QThread()
    speech_in_worker.moveToThread(speech_in_thread)
    speech_in_thread.start()

    speech_out_worker = SpeechOutWorker(speech_service)
    speech_out_thread = QThread()
    speech_out_worker.moveToThread(speech_out_thread)
    # Runs once, as soon as this worker's thread starts its event loop — well ahead of the
    # first real request (see SpeechService.warm_up_tts's docstring for why this matters).
    speech_out_thread.started.connect(speech_out_worker.warm_up)
    speech_out_thread.start()

    speech_service.set_listening_level_callback(speech_in_worker.listening_level.emit)
    speech_service.set_tts_mode_callback(speech_out_worker.tts_mode_changed.emit)

    window.mic_pressed.connect(speech_in_worker.listen_request)
    speech_in_worker.transcript_ready.connect(window.on_transcript_ready)
    speech_in_worker.failed.connect(window.on_listen_failed)
    # Direct, not queued — same reasoning as cancel_current/confirm above: the SpeechIn
    # thread is blocked inside `listen()`'s loop when these need to land.
    window.mic_repressed.connect(speech_in_worker.end_listening, Qt.ConnectionType.DirectConnection)
    window.listening_cancelled.connect(
        speech_in_worker.cancel_listening, Qt.ConnectionType.DirectConnection
    )

    worker.reply_ready.connect(speech_out_worker.speak_request)
    speech_out_worker.tts_mode_changed.connect(window.set_voice_mode)
    # Direct, not queued — the SpeechOut thread is blocked inside `speak()` when this lands.
    window.stop_speaking_requested.connect(
        speech_out_worker.stop_speaking, Qt.ConnectionType.DirectConnection
    )

    speech_in_worker.listening_level.connect(window.pipeline_view.set_audio_level)

    window.set_mic_available(bool(secrets.groq_api_key) and bool(list_input_devices()))

    provider_manager.status_changed.connect(window.set_provider_status)

    def _refresh_provider_status(name: str) -> None:
        available, detail = provider_manager.check_health(name)
        label = _PROVIDER_LABELS.get(name, name)
        if available:
            window.set_provider_status(ProviderStatus(active=name, mode="normal", detail=label))
        else:
            window.set_provider_status(
                ProviderStatus(active=name, mode="down", detail=f"{label}: {detail}")
            )

    def _on_provider_selected(name: str) -> None:
        settings.provider.active = name
        save_settings(settings, data_dir / "settings.json")
        provider_manager.set_active(name)
        _refresh_provider_status(name)

    def _on_key_changed(name: str, value: str) -> None:
        nonlocal secrets
        write_secret_to_env(data_dir, _ENV_KEY_NAMES[name], value)
        secrets = Secrets.load(data_dir=data_dir)
        register_secrets(secrets.gemini_api_key, secrets.groq_api_key, secrets.openrouter_api_key)

        provider = _build_provider(name, secrets, settings)
        window.settings_view.set_key_configured(name, provider is not None)
        if provider is not None:
            provider_manager.set_provider(name, provider)
            if name == provider_manager.active_name:
                _refresh_provider_status(name)

    def _on_test_requested(name: str) -> None:
        window.settings_view.set_testing(name, True)
        available, detail = provider_manager.check_health(name)
        window.settings_view.set_key_test_result(name, available, detail)
        window.settings_view.set_testing(name, False)

    def _on_openrouter_model_changed(model: str) -> None:
        settings.provider.openrouter_model = model
        save_settings(settings, data_dir / "settings.json")
        provider = _build_provider("openrouter", secrets, settings)
        if provider is not None:
            provider_manager.set_provider("openrouter", provider)

    window.settings_view.provider_selected.connect(_on_provider_selected)
    window.settings_view.key_changed.connect(_on_key_changed)
    window.settings_view.test_requested.connect(_on_test_requested)
    window.settings_view.openrouter_model_changed.connect(_on_openrouter_model_changed)

    # `settings.voice` is the exact object `speech_service` was built with (same reference,
    # not a copy) — mutating it in place here is all `SpeechService` needs to pick the
    # change up on its next `listen()`/`speak()` call; no separate push required.
    def _on_tts_enabled_changed(enabled: bool) -> None:
        settings.voice.tts_enabled = enabled
        save_settings(settings, data_dir / "settings.json")

    def _on_voice_changed(voice: str) -> None:
        settings.voice.voice = voice
        save_settings(settings, data_dir / "settings.json")

    def _on_input_device_changed(device: int | None) -> None:
        settings.voice.input_device = device
        save_settings(settings, data_dir / "settings.json")

    def _on_output_device_changed(device: int | None) -> None:
        settings.voice.output_device = device
        save_settings(settings, data_dir / "settings.json")

    window.settings_view.tts_enabled_changed.connect(_on_tts_enabled_changed)
    window.settings_view.voice_changed.connect(_on_voice_changed)
    window.settings_view.input_device_changed.connect(_on_input_device_changed)
    window.settings_view.output_device_changed.connect(_on_output_device_changed)
    window.settings_view.set_input_devices(list_input_devices())
    window.settings_view.set_output_devices(list_output_devices())

    def _on_default_city_changed(city: str) -> None:
        settings.weather.default_city = city
        save_settings(settings, data_dir / "settings.json")

    def _on_accent_changed(accent: str) -> None:
        settings.ui.accent = accent  # type: ignore[assignment]
        save_settings(settings, data_dir / "settings.json")
        app.setStyleSheet(build_stylesheet(accent))
        window.pipeline_view.set_accent(accent)

    def _on_reduced_motion_changed(enabled: bool) -> None:
        settings.ui.reduced_motion = enabled
        save_settings(settings, data_dir / "settings.json")
        set_reduced_motion(enabled)

    window.settings_view.default_city_changed.connect(_on_default_city_changed)
    window.settings_view.accent_changed.connect(_on_accent_changed)
    window.settings_view.reduced_motion_changed.connect(_on_reduced_motion_changed)

    for name in ("gemini", "groq", "openrouter"):
        window.settings_view.set_key_configured(name, name in provider_manager.configured_names)

    if provider_manager.configured_names:
        _refresh_provider_status(settings.provider.active)
    else:
        window.settings_view.show_missing_key_banner(
            "No API key configured yet — add one below to start chatting."
        )

    def _shutdown_worker_threads() -> None:
        for thread in (agent_thread, speech_in_thread, speech_out_thread):
            thread.quit()
            thread.wait()

    app.aboutToQuit.connect(_shutdown_worker_threads)

    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
