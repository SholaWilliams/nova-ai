"""MessageBubble: one chat turn (docs/05 §7.3).

Entry animation is fade-only (opacity 0->1, 250ms OutCubic) rather than the full "12px rise +
fade" docs/05 §7.3 describes — animating a layout-managed widget's own geometry fights Qt's
layout system (it reasserts the widget's position on the next layout pass), and there's no
robust, simple way around that without a custom animatable property. StageChip (the only
existing entry-animation precedent in this codebase) already made the same call: fade only,
via QGraphicsOpacityEffect. Full motion parity is explicitly M5's job (T-506, "Motion pass:
all Phase 5 §8 tokens") — noted as a scope trim, not an oversight.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nova.ui import theme
from nova.ui.animations import make_property_animation
from nova.ui.theme import Color, Motion, Radius, Spacing

_MAX_WIDTH_FRACTION = 0.72
_SPEAKER_BUTTON_SIZE = 24


class MessageBubble(QWidget):
    """One chat message: right-aligned for the user, left-aligned + accent hairline for NOVA.

    Text renders in full immediately — no typewriter effect (NG-9 spirit: the visualization
    never simulates work that isn't happening).
    """

    stop_speech_requested = Signal()

    def __init__(
        self, text: str, *, role: Literal["user", "nova"], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._role = role

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(text, self)
        self._label.setWordWrap(True)
        self._label.setFont(theme.font(theme.FontRole.BODY))
        self._label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self._label.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)

        if role == "user":
            style = (
                f"background-color: {Color.BUBBLE_USER}; border-radius: {Radius.CARD}px; "
                f"color: {Color.TEXT_PRIMARY};"
            )
            layout.addStretch(1)
            layout.addWidget(self._label, 0)
        else:
            style = (
                f"background-color: {Color.BUBBLE_NOVA}; border-radius: {Radius.CARD}px; "
                f"border-left: 2px solid {theme.accent_hex('cyan')}; color: {Color.TEXT_PRIMARY};"
            )
            content = QWidget(self)
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            content_layout.addWidget(self._label)

            # docs/05 §7.3: "a small volume-2 glyph pulses in the bubble corner; clicking it
            # stops speech" (FR-13, one of three interrupt triggers). ponytail: shown on every
            # NOVA bubble rather than only the currently-speaking one — syncing visibility/
            # pulsing to the live SPEAKING stage is cosmetic polish beyond FR-13's functional
            # ask (click stops speech); MainWindow already ignores clicks once nothing is
            # playing (SpeechService.stop_speaking() is a no-op with nothing active).
            self._speaker_button = QPushButton(content)
            self._speaker_button.setIcon(theme.load_icon("volume-2", Color.TEXT_SECONDARY, size=16))
            self._speaker_button.setFixedSize(_SPEAKER_BUTTON_SIZE, _SPEAKER_BUTTON_SIZE)
            self._speaker_button.setFlat(True)
            self._speaker_button.setToolTip("Stop speaking")
            self._speaker_button.clicked.connect(self.stop_speech_requested)
            speaker_row = QHBoxLayout()
            speaker_row.setContentsMargins(0, 0, Spacing.XS, Spacing.XS)
            speaker_row.addStretch(1)
            speaker_row.addWidget(self._speaker_button)
            content_layout.addLayout(speaker_row)

            layout.addWidget(content, 0)
            layout.addStretch(1)

        self._label.setStyleSheet(style)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)
        # keeps a live Python ref while running (avoids GC before Qt finishes the animation)
        self._fade_animation = make_property_animation(
            self._opacity_effect, "opacity", *Motion.BASE, start_value=0.0, end_value=1.0
        )
        # Drop the effect once the fade lands. A QGraphicsOpacityEffect on a widget freshly
        # inserted into a resizable QScrollArea can stay stuck at its cached opacity-0 pixmap
        # until the *next* relayout repaints it — the reported "reply doesn't show up until I
        # send another message". Removing the effect at the end forces a normal repaint, so a
        # completed (or janky) fade can never leave the bubble invisible.
        self._fade_animation.finished.connect(lambda: self.setGraphicsEffect(None))
        QTimer.singleShot(0, self._fade_animation.start)

    def set_max_bubble_width(self, chat_pane_width: int) -> None:
        """Constrain to 72% of the chat pane's current width (docs/05 §7.3)."""
        self._label.setMaximumWidth(max(1, int(chat_pane_width * _MAX_WIDTH_FRACTION)))
