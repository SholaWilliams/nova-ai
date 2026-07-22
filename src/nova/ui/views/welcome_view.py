"""WelcomeView: first-run setup guidance (docs/05 §6.3, M6 T-603).

Shown on launch if no API keys are configured. Provides plain-language links to key setup pages
and a quick "Test" affordance for each provider (docs/14 §2, FR-47).

Similar structure to SettingsView but read-only (no editable fields) — the real key entry lives
in Settings once the user navigates there.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from nova.ui import theme
from nova.ui.theme import Color, Spacing

_SETUP_LINKS = {
    "gemini": "https://aistudio.google.com/apikey",
    "groq": "https://console.groq.com/keys",
}

_SETUP_TEXT = {
    "gemini": "Get a Gemini API key from Google AI Studio (free tier available)",
    "groq": "Get a Groq API key from the Groq console (limited free tier)",
}


class WelcomeView(QWidget):
    """First-run welcome pane: setup instructions + key test buttons."""

    test_requested = Signal(str)  # provider_name
    goto_settings = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*([Spacing.MD] * 4))
        layout.setSpacing(Spacing.LG)

        # Title
        title = QLabel("Welcome to NOVA", self)
        title.setFont(theme.font(theme.FontRole.TITLE))
        layout.addWidget(title)

        # Intro text
        intro = QLabel(
            "To start using NOVA, you'll need API keys for the LLM providers. "
            "Here's how to get them:",
            self,
        )
        intro.setWordWrap(True)
        intro.setFont(theme.font(theme.FontRole.BODY))
        layout.addWidget(intro)

        # Provider setup instructions
        for provider in ("gemini", "groq"):
            self._add_provider_section(layout, provider)

        # Spacer
        layout.addSpacing(Spacing.LG)

        # Instructions for entering keys
        instructions = QLabel(
            "Once you've created an account and copied your API key, "
            'go to Settings → Brain → enter your key and click "Test" to verify it works.',
            self,
        )
        instructions.setWordWrap(True)
        instructions.setFont(theme.font(theme.FontRole.BODY))
        layout.addWidget(instructions)

        # Settings button
        layout.addSpacing(Spacing.SM)
        settings_btn = QPushButton("Open Settings", self)
        settings_btn.setStyleSheet(theme.button_style(theme.ButtonRole.PRIMARY))
        settings_btn.clicked.connect(self.goto_settings)
        layout.addWidget(settings_btn)

        # Stretch at the end
        layout.addStretch()

    def _add_provider_section(self, parent_layout: QVBoxLayout, provider: str) -> None:
        """Add a provider's setup section with link + description."""
        section = QVBoxLayout()
        section.setSpacing(Spacing.XS)

        # Provider name
        name_label = QLabel(provider.capitalize(), self)
        name_label.setFont(theme.font(theme.FontRole.LABEL))
        section.addWidget(name_label)

        # Description + clickable link
        desc = QLabel(f'<a href="{_SETUP_LINKS[provider]}">{_SETUP_TEXT[provider]}</a>', self)
        desc.setWordWrap(True)
        desc.setFont(theme.font(theme.FontRole.BODY))
        desc.setOpenExternalLinks(True)
        desc.setLinkColor(theme.color(Color.ACCENT_PRIMARY))
        section.addWidget(desc)

        parent_layout.addLayout(section)
