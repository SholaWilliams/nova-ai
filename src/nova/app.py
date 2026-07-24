"""Composition root (docs/03 §4): the only module allowed to import from every layer.

Builds and wires everything, owns startup ordering. Business logic, rendering, and
reasoning all live elsewhere — this module is wiring only.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSharedMemory, Qt, QThread
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
    set_autostart,
    write_secret_to_env,
)
from nova.core.errors import SpeechError, install_excepthook
from nova.core.events import EventBus
from nova.core.logging import EventLogBridge, register_secrets, setup_logging
from nova.core.models import AssistantReply, ProviderStatus, Transcript
from nova.memory.service import MemoryService
from nova.providers.base import LLMProvider
from nova.providers.manager import ProviderManager
from nova.providers.omniroute import OmniRouteProvider
from nova.speech.audio import AudioCapture, list_input_devices, list_output_devices
from nova.speech.service import SpeechService
from nova.speech.stt.base import STTEngine
from nova.speech.stt.groq_whisper import GroqSTTEngine
from nova.speech.tts.pyttsx3_engine import Pyttsx3Engine
from nova.speech.tts.remote_tts import RemoteTTSEngine
from nova.speech.worker import SpeechInWorker, SpeechOutWorker, WakeWorker
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

logger = logging.getLogger(__name__)

_OMNIROUTE_ENV_KEY_NAME = "NOVA_OMNIROUTE_API_KEY"
_NO_STT_KEY_MESSAGE = "I can't hear right now — you can type to me!"
# M10: arbitrary-but-fixed key for the single-instance guard (docs/08 §7a) -- namespaced so
# it can't collide with an unrelated app's shared-memory segment of the same generic name.
_SINGLE_INSTANCE_KEY = "NOVA-9f3c2b71-4a5d-4e8a-b6f1-single-instance-guard"


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


def _build_provider(secrets: Secrets, settings: Settings) -> LLMProvider | None:
    """Construct the OmniRoute adapter iff a key is configured — never a FakeProvider."""
    if not secrets.omniroute_api_key:
        return None
    return OmniRouteProvider(
        base_url=settings.provider.omniroute_base_url,
        api_key=secrets.omniroute_api_key,
        model=settings.provider.omniroute_model,
    )


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


def _acquire_single_instance_lock() -> QSharedMemory | None:
    """`None` means another NOVA process already holds the lock -- caller should exit without
    building the rest of the app. Windows frees a `QSharedMemory` segment automatically when
    its owning process exits, even on a crash (unlike the classic Unix stale-lockfile
    problem), so there's no cleanup path to write here (docs/08 §7a residency)."""
    lock = QSharedMemory(_SINGLE_INSTANCE_KEY)
    if not lock.create(1):
        return None
    return lock


def _show_first_run_if_needed(window: MainWindow, secrets: Secrets) -> None:
    """M6 T-603: if no API keys configured, show Settings on first run (docs/14 §2, FR-47).

    The user can still use the app (typed mode only) without keys; Settings guides key entry.
    """
    # ponytail: simple check, not exhaustive. Keys may be set via env vars directly without
    # the settings UI knowing — but the common first-run path is empty → Settings → key entry.
    if not secrets.omniroute_api_key:
        window.settings_view.welcome_banner_visible = True
        window._stack.setCurrentIndex(1)  # _SETTINGS_PAGE (docs/05 §6.3, T-209)


def main() -> int:
    """Build and run the app. Returns the process exit code."""
    install_excepthook()  # active before anything else can go wrong

    data_dir = get_data_dir()
    secrets = Secrets.load(data_dir=data_dir)
    setup_logging(data_dir, level=secrets.log_level)
    register_secrets(secrets.omniroute_api_key, secrets.groq_api_key)

    settings = load_settings(data_dir / "settings.json")

    app = QApplication(sys.argv)

    # M10: tray residency means a second launch is a real scenario now (clap-to-wake, an
    # autostart shortcut), not just an accidental double-click -- refuse silently rather than
    # opening a second window competing for the same microphone (docs/08 §7a).
    instance_lock = _acquire_single_instance_lock()
    if instance_lock is None:
        logger.info("NOVA is already running — exiting")
        return 0

    app.setStyleSheet(build_stylesheet(settings.ui.accent))
    set_reduced_motion(settings.ui.reduced_motion)

    bus = EventBus()
    EventLogBridge(bus)

    window = MainWindow(bus, settings)
    # M6 T-603: first-run welcome — auto-show Settings if no keys configured yet.
    _show_first_run_if_needed(window, secrets)

    provider_manager = ProviderManager(_build_provider(secrets, settings))
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
    speech_service.set_speech_started_callback(speech_out_worker.speech_started.emit)

    # M10: clap-to-wake (docs/08 §7a). WakeWorker is itself a QThread subclass (see its
    # docstring for why) -- its own AudioCapture so it never competes with SpeechInWorker's.
    wake_worker = WakeWorker(
        sensitivity=settings.wake.sensitivity, device=settings.voice.input_device
    )
    wake_worker.set_enabled(settings.wake.enabled)
    wake_worker.start()

    wake_worker.wake_detected.connect(window.on_wake_detected)
    # Direct, not queued -- these just flip a bool the wake loop polls; no thread is blocked
    # waiting for them to land, unlike cancel_listening/end_listening above.
    window.mic_pressed.connect(
        wake_worker.pause_for_active_listen, Qt.ConnectionType.DirectConnection
    )
    speech_in_worker.transcript_ready.connect(
        wake_worker.resume_after_active_listen, Qt.ConnectionType.DirectConnection
    )
    speech_in_worker.failed.connect(
        wake_worker.resume_after_active_listen, Qt.ConnectionType.DirectConnection
    )

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
    speech_out_worker.speech_started.connect(window.on_speech_started)
    # Direct, not queued — the SpeechOut thread is blocked inside `speak()` when this lands.
    window.stop_speaking_requested.connect(
        speech_out_worker.stop_speaking, Qt.ConnectionType.DirectConnection
    )

    speech_in_worker.listening_level.connect(window.pipeline_view.set_audio_level)

    window.set_mic_available(bool(secrets.groq_api_key) and bool(list_input_devices()))

    provider_manager.status_changed.connect(window.set_provider_status)

    def _refresh_provider_status() -> None:
        available, detail = provider_manager.check_health()
        if available:
            window.set_provider_status(
                ProviderStatus(active="omniroute", mode="normal", detail="OmniRoute")
            )
        else:
            window.set_provider_status(
                ProviderStatus(active="omniroute", mode="down", detail=f"OmniRoute: {detail}")
            )

    def _on_key_changed(name: str, value: str) -> None:
        del name  # single provider now — the row is always "omniroute"
        nonlocal secrets
        write_secret_to_env(data_dir, _OMNIROUTE_ENV_KEY_NAME, value)
        secrets = Secrets.load(data_dir=data_dir)
        register_secrets(secrets.omniroute_api_key, secrets.groq_api_key)

        provider = _build_provider(secrets, settings)
        window.settings_view.set_key_configured("omniroute", provider is not None)
        if provider is not None:
            provider_manager.set_provider(provider)
            _refresh_provider_status()

    def _on_test_requested(name: str) -> None:
        del name
        window.settings_view.set_testing("omniroute", True)
        available, detail = provider_manager.check_health()
        window.settings_view.set_key_test_result("omniroute", available, detail)
        window.settings_view.set_testing("omniroute", False)

    def _on_omniroute_model_changed(model: str) -> None:
        settings.provider.omniroute_model = model
        save_settings(settings, data_dir / "settings.json")
        provider = _build_provider(secrets, settings)
        if provider is not None:
            provider_manager.set_provider(provider)

    window.settings_view.key_changed.connect(_on_key_changed)
    window.settings_view.test_requested.connect(_on_test_requested)
    window.settings_view.omniroute_model_changed.connect(_on_omniroute_model_changed)

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
        wake_worker.set_device(device)

    def _on_output_device_changed(device: int | None) -> None:
        settings.voice.output_device = device
        save_settings(settings, data_dir / "settings.json")

    def _on_wake_enabled_changed(enabled: bool) -> None:
        settings.wake.enabled = enabled
        save_settings(settings, data_dir / "settings.json")
        wake_worker.set_enabled(enabled)
        window.set_wake_indicator(enabled)

    def _on_autostart_changed(enabled: bool) -> None:
        settings.wake.autostart = enabled
        save_settings(settings, data_dir / "settings.json")
        set_autostart(enabled)

    window.settings_view.tts_enabled_changed.connect(_on_tts_enabled_changed)
    window.settings_view.voice_changed.connect(_on_voice_changed)
    window.settings_view.input_device_changed.connect(_on_input_device_changed)
    window.settings_view.output_device_changed.connect(_on_output_device_changed)
    window.settings_view.wake_enabled_changed.connect(_on_wake_enabled_changed)
    window.settings_view.autostart_changed.connect(_on_autostart_changed)
    window.tray_wake_toggled.connect(_on_wake_enabled_changed)
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

    window.settings_view.set_key_configured("omniroute", provider_manager.configured)

    if provider_manager.configured:
        _refresh_provider_status()
    else:
        window.settings_view.show_missing_key_banner(
            "No API key configured yet — add one below to start chatting."
        )

    def _shutdown_worker_threads() -> None:
        # WakeWorker overrides run() instead of using the exec()-event-loop model the other
        # three threads use (see its class docstring) -- quit() is meaningless here, only
        # stop_loop() + wait() actually joins it.
        wake_worker.stop_loop()
        wake_worker.wait()
        for thread in (agent_thread, speech_in_thread, speech_out_thread):
            thread.quit()
            thread.wait()

    app.aboutToQuit.connect(_shutdown_worker_threads)

    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
