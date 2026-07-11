"""PipelineView: the Pipeline Panel (docs/05 §6.2) — the pipeline's hero, and the UI's only
subscriber that needs the full PipelineEvent stream (everything else can watch a view model).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from nova.core.events import EventBus, PipelineEvent, PipelineStage
from nova.ui import theme
from nova.ui.theme import Spacing
from nova.ui.widgets.pulse_ring import PulseRing, PulseState
from nova.ui.widgets.stage_chip import CHILD_LABELS, StageChip

# Fixed rail order (docs/03 §7.1 table order). Excludes IDLE (child label is "—": not a
# stage-in-progress) and AWAITING_CONFIRMATION (docs/05 §6.6 gives it a modal dialog, not a
# rail row — the Executing chip stays active/"held" per docs/05 §11 while it's open).
RAIL_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.LISTENING,
    PipelineStage.TRANSCRIBING,
    PipelineStage.THINKING,
    PipelineStage.SELECTING_TOOL,
    PipelineStage.EXECUTING,
    PipelineStage.OBSERVING,
    PipelineStage.REMEMBERING,
    PipelineStage.RESPONDING,
    PipelineStage.SPEAKING,
)

# docs/05 §11 (State Transition Map) + docs/03 §7.1: collapsing the 11 PipelineStages down
# to PulseRing's simplified 6-state vocabulary. AWAITING_CONFIRMATION maps to Executing —
# the map's own words are "Executing (held)".
_PULSE_STATE_FOR_STAGE: dict[PipelineStage, PulseState] = {
    PipelineStage.IDLE: PulseState.IDLE,
    PipelineStage.LISTENING: PulseState.LISTENING,
    PipelineStage.TRANSCRIBING: PulseState.LISTENING,
    PipelineStage.THINKING: PulseState.THINKING,
    PipelineStage.SELECTING_TOOL: PulseState.THINKING,
    PipelineStage.AWAITING_CONFIRMATION: PulseState.EXECUTING,
    PipelineStage.EXECUTING: PulseState.EXECUTING,
    PipelineStage.OBSERVING: PulseState.THINKING,
    PipelineStage.REMEMBERING: PulseState.THINKING,
    PipelineStage.RESPONDING: PulseState.THINKING,
    PipelineStage.SPEAKING: PulseState.SPEAKING,
    PipelineStage.ERROR: PulseState.ERROR,
}


def pulse_state_for(stage: PipelineStage) -> PulseState:
    """Map a PipelineStage to the PulseRing's simplified 6-state vocabulary."""
    return _PULSE_STATE_FOR_STAGE.get(stage, PulseState.IDLE)


class PipelineView(QWidget):
    """PulseRing + stage word on top, the fixed-order stage rail below. Subscribes to `bus`.

    Mic/playback `level` is intentionally not driven from PipelineEvents here: per docs/11
    §4, that's `SpeechService.listening_level`, a separate high-frequency Qt signal — wiring
    it to `PulseRing.set_level()` directly is M4's job (T-401+), once SpeechService exists.
    """

    def __init__(self, bus: EventBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bus = bus
        self._current_request_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.MD)

        self._pulse_ring = PulseRing(self)
        layout.addWidget(self._pulse_ring, 0, Qt.AlignmentFlag.AlignHCenter)

        self._stage_word = QLabel(self)
        self._stage_word.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._stage_word.setFont(theme.font(theme.FontRole.DISPLAY))
        self._stage_word.setWordWrap(True)
        layout.addWidget(self._stage_word)

        self._chips: dict[PipelineStage, StageChip] = {}
        rail_container = QWidget()
        rail_layout = QVBoxLayout(rail_container)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(0)
        for stage in RAIL_STAGES:
            chip = StageChip(stage, rail_container)
            self._chips[stage] = chip
            rail_layout.addWidget(chip)
        rail_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(rail_container)
        layout.addWidget(scroll, 1)

        self._bus.event_published.connect(self._on_event)

    def set_audio_level(self, level: float) -> None:
        """Drive the ring's amplitude directly from live mic/playback level (docs/11 §4:
        `listening_level` is a separate high-frequency Qt signal, not a PipelineEvent) — M4's
        job, per the comment this replaces. Wired directly to `SpeechInWorker.listening_level`
        in `app.py`; a `PipelineEvent` still owns which *state* the ring is in."""
        self._pulse_ring.set_level(level)

    def set_accent(self, accent: str) -> None:
        """FR-44 (M5): live accent swap from Settings' Look section."""
        self._pulse_ring.set_accent(accent)

    def _on_event(self, event: PipelineEvent) -> None:
        if event.request_id != self._current_request_id:
            self._start_new_request(event.request_id)

        chip = self._chips.get(event.stage)
        if chip is not None:
            chip.apply_event(event)

        self._pulse_ring.set_state(pulse_state_for(event.stage))
        self._stage_word.setText(event.detail or CHILD_LABELS.get(event.stage, ""))

    def _start_new_request(self, request_id: str) -> None:
        """Reset the rail for a new request. FR-40: it otherwise stays populated as-is."""
        self._current_request_id = request_id
        for chip in self._chips.values():
            chip.reset()
