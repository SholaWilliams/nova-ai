"""Composition root (docs/03 §4): the only module allowed to import from every layer.

Builds and wires everything, owns startup ordering. Business logic, rendering, and
reasoning all live elsewhere — this module is wiring only.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from nova.core.config import Secrets, get_data_dir, load_settings
from nova.core.errors import install_excepthook
from nova.core.events import EventBus
from nova.core.logging import EventLogBridge, register_secrets, setup_logging
from nova.ui.main_window import MainWindow
from nova.ui.theme import build_stylesheet


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
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
