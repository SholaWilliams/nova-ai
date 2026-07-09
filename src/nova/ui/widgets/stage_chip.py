"""StageChip: one row in the pipeline stage rail (docs/05 §7.2, §6.2).

`apply_event()` is the entire write path — a chip only reacts to PipelineEvents for its own
`stage`. Click anywhere on a non-pending chip to expand/collapse its full `PipelineEvent.detail`.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QPropertyAnimation, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from nova.core.events import EventStatus, PipelineEvent, PipelineStage
from nova.ui import theme
from nova.ui.animations import make_property_animation
from nova.ui.theme import Color, Motion, Spacing

# Child-facing labels, verbatim from docs/03 §7.1 (the single source for this copy).
CHILD_LABELS: dict[PipelineStage, str] = {
    PipelineStage.IDLE: "",
    PipelineStage.LISTENING: "Listening…",
    PipelineStage.TRANSCRIBING: "Understanding your words",
    PipelineStage.THINKING: "Thinking…",
    PipelineStage.SELECTING_TOOL: "Choosing a tool",
    PipelineStage.AWAITING_CONFIRMATION: "Asking your permission",
    PipelineStage.EXECUTING: "Doing it on your PC",
    PipelineStage.OBSERVING: "Checking the result",
    PipelineStage.REMEMBERING: "Remembering",
    PipelineStage.RESPONDING: "Getting my answer ready",
    PipelineStage.SPEAKING: "Speaking",
    PipelineStage.ERROR: "Oops — something went wrong",
}

# docs/05 §5 — only these stages have a fixed icon; others (TRANSCRIBING, OBSERVING,
# RESPONDING) show none, and SELECTING_TOOL's icon is dynamic (payload["icon"], set once
# tools exist in M3) rather than fixed here.
_STAGE_ICONS: dict[PipelineStage, str] = {
    PipelineStage.LISTENING: "mic",
    PipelineStage.THINKING: "sparkles",
    PipelineStage.EXECUTING: "zap",
    PipelineStage.REMEMBERING: "bookmark",
    PipelineStage.SPEAKING: "volume-2",
}

_ROW_HEIGHT = 40
_ICON_SIZE = 20


class ChipState(Enum):
    """Visual state of a chip (docs/05 §7.2)."""

    PENDING = auto()
    ACTIVE = auto()
    DONE = auto()
    SKIPPED = auto()
    FAILED = auto()


def _format_duration(duration_ms: int) -> str:
    return f"{duration_ms / 1000:.1f}s"


class StageChip(QWidget):
    """One pipeline stage row: label + status + (once done) duration; click expands detail."""

    def __init__(self, stage: PipelineStage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stage = stage
        self._chip_state = ChipState.PENDING
        self._detail = ""
        self._duration_ms: int | None = None
        self._tool_title: str | None = None
        self._expanded = False
        # keeps a live Python ref while running (avoids GC before Qt finishes the animation)
        self._crossfade_animation: QPropertyAnimation | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._row = QWidget(self)
        self._row.setFixedHeight(_ROW_HEIGHT)
        self._row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row_layout = QHBoxLayout(self._row)
        row_layout.setContentsMargins(Spacing.SM, 0, Spacing.SM, 0)
        row_layout.setSpacing(Spacing.SM)

        self._icon_label = QLabel(self._row)
        self._icon_label.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self._icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row_layout.addWidget(self._icon_label)

        self._text_label = QLabel(CHILD_LABELS.get(stage, stage.value), self._row)
        self._text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row_layout.addWidget(self._text_label, 1)

        self._status_label = QLabel(self._row)
        self._status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row_layout.addWidget(self._status_label)

        outer.addWidget(self._row)

        self._detail_label = QLabel(self)
        self._detail_label.setWordWrap(True)
        self._detail_label.setFont(theme.font(theme.FontRole.CAPTION))
        left_indent = Spacing.SM + _ICON_SIZE + Spacing.SM
        self._detail_label.setContentsMargins(left_indent, 0, Spacing.SM, Spacing.SM)
        self._detail_label.setStyleSheet(f"color: {Color.TEXT_SECONDARY};")
        self._detail_label.setVisible(False)
        outer.addWidget(self._detail_label)

        self._opacity_effect = QGraphicsOpacityEffect(self._row)
        self._row.setGraphicsEffect(self._opacity_effect)

        self._apply_visual_state()

    # ── public API ────────────────────────────────────────────────────

    def apply_event(self, event: PipelineEvent) -> None:
        """Update from a PipelineEvent. No-ops for events belonging to a different stage."""
        if event.stage != self.stage:
            return
        self._detail = event.detail
        payload = event.payload or {}
        self._tool_title = payload.get("tool_title")

        if event.status == EventStatus.STARTED:
            self._chip_state = ChipState.ACTIVE
        elif event.status == EventStatus.COMPLETED:
            self._chip_state = ChipState.DONE
            self._duration_ms = payload.get("duration_ms")
        elif event.status == EventStatus.SKIPPED:
            self._chip_state = ChipState.SKIPPED
        elif event.status == EventStatus.FAILED:
            self._chip_state = ChipState.FAILED

        self._apply_visual_state(animate=True)

    def reset(self) -> None:
        """Back to pending — call when a new request starts.

        FR-40: the rail otherwise stays populated (doesn't auto-clear) after a request ends.
        """
        self._chip_state = ChipState.PENDING
        self._detail = ""
        self._duration_ms = None
        self._tool_title = None
        self._expanded = False
        self._detail_label.setVisible(False)
        self._apply_visual_state()

    # ── interaction ──────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._detail and self._chip_state != ChipState.PENDING:
            self._expanded = not self._expanded
            self._detail_label.setText(self._detail)
            self._detail_label.setVisible(self._expanded)
        super().mousePressEvent(event)

    # ── visuals ──────────────────────────────────────────────────────

    def _apply_visual_state(self, animate: bool = False) -> None:
        label_font = theme.font(theme.FontRole.LABEL)
        label_font.setBold(self._chip_state == ChipState.ACTIVE)
        label_font.setStrikeOut(self._chip_state == ChipState.SKIPPED)
        self._text_label.setFont(label_font)
        self._status_label.setFont(theme.font(theme.FontRole.CAPTION))

        icon_name = _STAGE_ICONS.get(self.stage)
        status_text = ""
        if self._chip_state == ChipState.PENDING:
            text_color = Color.TEXT_SECONDARY
            border_color = status_color = Color.STROKE_SUBTLE
        elif self._chip_state == ChipState.ACTIVE:
            text_color = Color.TEXT_PRIMARY
            border_color = status_color = theme.accent_hex("cyan")
            status_text = self._tool_title or "now"
        elif self._chip_state == ChipState.DONE:
            text_color = Color.TEXT_PRIMARY
            border_color = Color.STROKE_SUBTLE
            status_color = Color.STATE_SUCCESS
            status_text = (
                f"✓ {_format_duration(self._duration_ms)}" if self._duration_ms is not None else "✓"
            )
        elif self._chip_state == ChipState.SKIPPED:
            text_color = Color.TEXT_SECONDARY
            border_color = Color.STROKE_SUBTLE
            status_color = Color.TEXT_SECONDARY
            status_text = "— skipped"
        else:  # FAILED
            text_color = border_color = status_color = Color.STATE_ERROR
            status_text = "failed"
            icon_name = "alert-triangle"

        if icon_name:
            self._icon_label.setPixmap(
                theme.load_icon(icon_name, text_color).pixmap(_ICON_SIZE, _ICON_SIZE)
            )
        else:
            self._icon_label.clear()
        self._text_label.setStyleSheet(f"color: {text_color}; background: transparent;")
        self._status_label.setStyleSheet(f"color: {status_color}; background: transparent;")
        self._status_label.setText(status_text)
        self._row.setStyleSheet(f"QWidget {{ border-left: 2px solid {border_color}; }}")

        if animate:
            self._crossfade_animation = make_property_animation(
                self._opacity_effect, "opacity", *Motion.BASE, start_value=0.4, end_value=1.0
            )
            self._crossfade_animation.start()
