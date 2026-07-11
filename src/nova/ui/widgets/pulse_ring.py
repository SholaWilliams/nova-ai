"""PulseRing: NOVA's living avatar and the pipeline's hero widget (docs/05 §7.1).

One QVariantAnimation drives a repeating phase float (0..1); `paintEvent` derives all
geometry from (state, phase, level) — no heavy per-frame work (FR-45). Colors are
precomputed on state/accent change, not re-parsed from hex strings every frame.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from nova.ui.animations import easing_curve, is_reduced_motion, make_variant_animation
from nova.ui.theme import Color, Motion, accent_hex, with_alpha

_DIAMETER = 160
_CORE_RADIUS = 28.0
_RING_INSET = 4.0


class PulseState(Enum):
    """The 6 visual states from docs/05 §7.1 — a simplified view of the 11 PipelineStages.

    Mapping from the full PipelineStage vocabulary to these is `pipeline_view.py`'s job
    (docs/05 §11); this widget only knows its own 6 states, kept narrow and reusable.
    """

    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    EXECUTING = auto()
    SPEAKING = auto()
    ERROR = auto()


# (duration_ms, easing, loop_count) per docs/05 §7.1's params column. loop_count=-1 loops
# forever (Idle/Listening/Thinking/Speaking are continuous); Executing/Error run once and
# hold/dim at their end value ("fast double-pulse then hold", "two quick flashes then dim").
_ANIMATION_PARAMS: dict[PulseState, tuple[int, str, int]] = {
    PulseState.IDLE: (*Motion.BREATHE, -1),
    PulseState.LISTENING: (1200, "OutCubic", -1),
    PulseState.THINKING: (1600, "Linear", -1),
    PulseState.EXECUTING: (1000, "OutCubic", 1),
    PulseState.SPEAKING: (600, "InOutSine", -1),
    PulseState.ERROR: (300, "OutCubic", 1),
}

# States whose `set_state` call should always replay the animation from the start, even if
# the widget was already in that state — they represent a fresh, discrete occurrence (a new
# tool call, a new error), unlike Listening/Speaking which get repeated calls just to update
# `level` and must NOT restart their loop each time.
_REPLAY_ON_EVERY_CALL = {PulseState.EXECUTING, PulseState.ERROR}


class PulseRing(QWidget):
    """160px custom-painted avatar. `set_state()` is the entire public API surface."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(_DIAMETER, _DIAMETER)

        self._state = PulseState.IDLE
        self._level = 0.0
        self._phase = 0.0
        self._restart_count = 0  # test hook: counts animation (re)starts
        self._paint_count = 0  # test hook: counts paintEvent calls

        self._primary_color = QColor(accent_hex("cyan"))
        self._secondary_color = QColor(Color.ACCENT_SECONDARY)
        self._error_color = QColor(Color.STATE_ERROR)

        self._animation = make_variant_animation(*Motion.BREATHE, start_value=0.0, end_value=1.0)
        self._animation.valueChanged.connect(self._on_phase_changed)
        self._apply_state_animation_params()

    # ── public API ────────────────────────────────────────────────────

    def set_accent(self, accent: str) -> None:
        """Update the user-adjustable accent (FR-44) used by non-fixed-color states."""
        self._primary_color = QColor(accent_hex(accent))
        self.update()

    def set_state(self, state: PulseState, level: float = 0.0) -> None:
        """Switch the visual state. `level` (0..1) drives Listening/Speaking intensity."""
        self._level = max(0.0, min(1.0, level))
        if state != self._state or state in _REPLAY_ON_EVERY_CALL:
            self._state = state
            self._apply_state_animation_params()
        self.update()

    def set_level(self, level: float) -> None:
        """Update the mic/playback level (0..1) without changing state or restarting."""
        self._level = max(0.0, min(1.0, level))
        self.update()

    # ── animation plumbing ───────────────────────────────────────────

    def _apply_state_animation_params(self) -> None:
        duration_ms, easing_name, loop_count = _ANIMATION_PARAMS[self._state]
        if is_reduced_motion() and loop_count == -1:
            # docs/05 §10: "reduced motion disables loops/ripples" — plays once, settles at
            # the end value, instead of looping forever (WCAG-style: the concern is
            # *repeating* motion, not the single transition itself).
            loop_count = 1
        self._animation.stop()
        self._animation.setDuration(duration_ms)
        self._animation.setEasingCurve(easing_curve(easing_name))
        self._animation.setLoopCount(loop_count)
        self._phase = 0.0
        self._restart_count += 1
        self._animation.start()

    def _on_phase_changed(self, value: object) -> None:
        self._phase = float(value)  # type: ignore[arg-type]
        self.update()

    # ── painting ─────────────────────────────────────────────────────

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        self._paint_count += 1
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, _DIAMETER, _DIAMETER).adjusted(
            _RING_INSET, _RING_INSET, -_RING_INSET, -_RING_INSET
        )
        center = rect.center()

        paint_by_state = {
            PulseState.IDLE: self._paint_idle,
            PulseState.LISTENING: self._paint_listening,
            PulseState.THINKING: self._paint_thinking,
            PulseState.EXECUTING: self._paint_executing,
            PulseState.SPEAKING: self._paint_speaking,
            PulseState.ERROR: self._paint_error,
        }
        paint_by_state[self._state](painter, rect, center)
        painter.end()

    def _paint_idle(self, painter: QPainter, rect: QRectF, center: QPointF) -> None:
        # breathe: scale 0.96 -> 1.0, accent @ 60%, folded into a triangle wave so the
        # sawtooth phase reads as smooth in-and-out breathing rather than a snap-back.
        breathe = 1.0 - abs(1.0 - 2.0 * self._phase)
        scale = 0.96 + 0.04 * breathe
        color = with_alpha(self._primary_color.name(), 0.6)
        self._draw_glow_core(painter, center, _CORE_RADIUS * scale, color)

    def _paint_listening(self, painter: QPainter, rect: QRectF, center: QPointF) -> None:
        # two ripples, staggered half a cycle apart, expanding outward and fading (FR-42).
        max_radius = min(rect.width(), rect.height()) / 2.0
        for offset in (0.0, 0.5):
            ripple_phase = (self._phase + offset) % 1.0
            radius = _CORE_RADIUS + ripple_phase * (max_radius - _CORE_RADIUS)
            alpha = 1.0 - ripple_phase
            self._draw_ring(painter, center, radius, with_alpha(self._primary_color.name(), alpha))
        core_radius = _CORE_RADIUS + 8.0 * self._level
        self._draw_glow_core(painter, center, core_radius, self._primary_color)

    def _paint_thinking(self, painter: QPainter, rect: QRectF, center: QPointF) -> None:
        # rotating 270 degree arc, one revolution per Motion token duration.
        self._draw_glow_core(
            painter, center, _CORE_RADIUS, with_alpha(self._secondary_color.name(), 0.5)
        )
        pen = QPen(self._secondary_color, 4.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        arc_rect = QRectF(
            center.x() - _CORE_RADIUS, center.y() - _CORE_RADIUS, _CORE_RADIUS * 2, _CORE_RADIUS * 2
        )
        start_angle = int(-self._phase * 360 * 16)
        painter.drawArc(arc_rect, start_angle, 270 * 16)

    def _paint_executing(self, painter: QPainter, rect: QRectF, center: QPointF) -> None:
        # two fast pulses (phase 0->0.5 and 0.5->1.0), then hold at rest once phase reaches 1.
        if self._phase >= 1.0:
            self._draw_glow_core(painter, center, _CORE_RADIUS, self._primary_color)
            return
        local = (self._phase * 2.0) % 1.0
        bump = 1.0 - abs(1.0 - 2.0 * local)
        scale = 1.0 + 0.25 * bump
        self._draw_glow_core(painter, center, _CORE_RADIUS * scale, self._primary_color)

    def _paint_speaking(self, painter: QPainter, rect: QRectF, center: QPointF) -> None:
        # amplitude pulsation: a live baseline loop, boosted by real playback `level` (M4).
        baseline = 1.0 - abs(1.0 - 2.0 * self._phase)
        intensity = max(baseline * 0.5, self._level)
        scale = 1.0 + 0.3 * intensity
        self._draw_glow_core(painter, center, _CORE_RADIUS * scale, self._primary_color)

    def _paint_error(self, painter: QPainter, rect: QRectF, center: QPointF) -> None:
        # two quick flashes (phase 0->1 over 300ms), then dim once at rest.
        if self._phase >= 1.0:
            self._draw_glow_core(
                painter, center, _CORE_RADIUS, with_alpha(self._error_color.name(), 0.35)
            )
            return
        local = (self._phase * 2.0) % 1.0
        flash = 1.0 - abs(1.0 - 2.0 * local)
        self._draw_glow_core(
            painter, center, _CORE_RADIUS, with_alpha(self._error_color.name(), flash)
        )

    @staticmethod
    def _draw_glow_core(painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
        radius = max(radius, 1.0)
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, color)
        faded = QColor(color)
        faded.setAlpha(0)
        gradient.setColorAt(1.0, faded)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(center, radius, radius)

    @staticmethod
    def _draw_ring(painter: QPainter, center: QPointF, radius: float, color: QColor) -> None:
        painter.setPen(QPen(color, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(center, radius, radius)
