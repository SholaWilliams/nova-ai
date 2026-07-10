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
from nova.core.errors import install_excepthook
from nova.core.events import EventBus
from nova.core.logging import EventLogBridge, register_secrets, setup_logging
from nova.core.models import ProviderStatus
from nova.providers.base import LLMProvider
from nova.providers.gemini import GeminiProvider
from nova.providers.groq import GroqProvider
from nova.providers.manager import ProviderManager
from nova.tools.app_launcher import AppLauncherTool
from nova.tools.base import ToolContext
from nova.tools.browser import BrowserTool
from nova.tools.calculator import CalculatorTool
from nova.tools.desktop_organizer import DesktopOrganizerTool
from nova.tools.file_search import FileSearchTool
from nova.tools.memory_tool import InMemoryFacade, MemoryTool
from nova.tools.registry import ToolRegistry
from nova.tools.weather import WeatherTool
from nova.ui.main_window import MainWindow
from nova.ui.theme import build_stylesheet

_ENV_KEY_NAMES = {"gemini": "NOVA_GEMINI_API_KEY", "groq": "NOVA_GROQ_API_KEY"}
_PROVIDER_LABELS = {"gemini": "Gemini", "groq": "Groq"}


def _build_provider(name: str, secrets: Secrets, settings: Settings) -> LLMProvider | None:
    """Construct the adapter for `name` iff a key is configured — never a FakeProvider."""
    if name == "gemini" and secrets.gemini_api_key:
        return GeminiProvider(api_key=secrets.gemini_api_key, model=settings.provider.gemini_model)
    if name == "groq" and secrets.groq_api_key:
        return GroqProvider(api_key=secrets.groq_api_key, model=settings.provider.groq_model)
    return None


def _build_providers(secrets: Secrets, settings: Settings) -> dict[str, LLMProvider]:
    providers: dict[str, LLMProvider] = {}
    for name in ("gemini", "groq"):
        provider = _build_provider(name, secrets, settings)
        if provider is not None:
            providers[name] = provider
    return providers


def _build_registry(secrets: Secrets, settings: Settings, data_dir: Path) -> ToolRegistry:
    """Register all seven v1.0 tools (docs/07). Order = SELECTING_TOOL display order."""
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
    registry.register(DesktopOrganizerTool(desktop=desktop, manifest_dir=data_dir))
    registry.register(MemoryTool())
    return registry


def main() -> int:
    """Build and run the app. Returns the process exit code."""
    install_excepthook()  # active before anything else can go wrong

    data_dir = get_data_dir()
    secrets = Secrets.load(data_dir=data_dir)
    setup_logging(data_dir, level=secrets.log_level)
    register_secrets(secrets.gemini_api_key, secrets.groq_api_key)

    settings = load_settings(data_dir / "settings.json")

    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(settings.ui.accent))

    bus = EventBus()
    EventLogBridge(bus)

    window = MainWindow(bus, settings)

    provider_manager = ProviderManager(
        _build_providers(secrets, settings), settings.provider.active
    )
    registry = _build_registry(secrets, settings, data_dir)
    # ponytail: InMemoryFacade is the M3 stub — M5's MemoryService replaces it (same protocol)
    tool_ctx = ToolContext(settings=settings, memory=InMemoryFacade())
    executor = Executor(registry, bus, tool_ctx, tool_timeout_s=settings.advanced.tool_timeout_s)
    agent = Agent(
        provider_manager,
        Planner(load_system_prompt()),
        Router(known_tool_names=registry.names),
        ConversationState(max_iterations=settings.advanced.max_iterations),
        bus,
        registry=registry,
        executor=executor,
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
        register_secrets(secrets.gemini_api_key, secrets.groq_api_key)

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

    window.settings_view.provider_selected.connect(_on_provider_selected)
    window.settings_view.key_changed.connect(_on_key_changed)
    window.settings_view.test_requested.connect(_on_test_requested)

    for name in ("gemini", "groq"):
        window.settings_view.set_key_configured(name, name in provider_manager.configured_names)

    if provider_manager.configured_names:
        _refresh_provider_status(settings.provider.active)
    else:
        window.settings_view.show_missing_key_banner(
            "No API key configured yet — add one below to start chatting."
        )

    def _shutdown_agent_thread() -> None:
        agent_thread.quit()
        agent_thread.wait()

    app.aboutToQuit.connect(_shutdown_agent_thread)

    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
