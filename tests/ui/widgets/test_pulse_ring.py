"""Unit tests for nova.ui.widgets.pulse_ring — state transitions and paint safety (docs/13 §4)."""

import pytest

from nova.ui.widgets.pulse_ring import PulseRing, PulseState


@pytest.fixture
def ring(qtbot: object) -> PulseRing:
    widget = PulseRing()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    return widget


def test_starts_idle(ring: PulseRing) -> None:
    assert ring._state == PulseState.IDLE


@pytest.mark.parametrize("state", list(PulseState))
def test_set_state_updates_internal_state(ring: PulseRing, state: PulseState) -> None:
    ring.set_state(state)
    assert ring._state == state


def test_set_state_clamps_level_to_0_1(ring: PulseRing) -> None:
    ring.set_state(PulseState.LISTENING, level=5.0)
    assert ring._level == 1.0
    ring.set_state(PulseState.LISTENING, level=-5.0)
    assert ring._level == 0.0


@pytest.mark.parametrize(
    "state", [PulseState.IDLE, PulseState.LISTENING, PulseState.THINKING, PulseState.SPEAKING]
)
def test_continuous_states_do_not_restart_on_repeated_same_state_calls(
    ring: PulseRing, state: PulseState
) -> None:
    ring.set_state(state, level=0.2)
    restart_count_after_first = ring._restart_count

    ring.set_state(state, level=0.7)  # only the level changed

    assert ring._restart_count == restart_count_after_first


@pytest.mark.parametrize("state", [PulseState.EXECUTING, PulseState.ERROR])
def test_one_shot_states_restart_on_every_call(ring: PulseRing, state: PulseState) -> None:
    ring.set_state(state)
    restart_count_after_first = ring._restart_count

    ring.set_state(state)  # a second, distinct occurrence (e.g. a second tool call)

    assert ring._restart_count == restart_count_after_first + 1


def test_set_level_does_not_restart_animation(ring: PulseRing) -> None:
    ring.set_state(PulseState.LISTENING)
    restart_count = ring._restart_count

    ring.set_level(0.9)

    assert ring._restart_count == restart_count
    assert ring._level == pytest.approx(0.9)


def test_set_accent_changes_primary_color(ring: PulseRing) -> None:
    before = ring._primary_color.name()
    ring.set_accent("violet")
    assert ring._primary_color.name() != before


@pytest.mark.parametrize("state", list(PulseState))
def test_paints_without_error_in_every_state(ring: PulseRing, state: PulseState) -> None:
    ring.set_state(state, level=0.5)
    pixmap = ring.grab()
    assert not pixmap.isNull()
    assert pixmap.width() == 160
    assert pixmap.height() == 160


def test_paint_count_is_bounded_for_a_handful_of_updates(
    ring: PulseRing, qtbot: object, qapp: object
) -> None:
    ring.set_state(PulseState.IDLE)
    ring.show()
    qapp.processEvents()  # type: ignore[attr-defined]

    before = ring._paint_count
    for _ in range(5):
        ring.repaint()  # synchronous — unlike update(), each call must paint immediately
        qapp.processEvents()  # type: ignore[attr-defined]
    after = ring._paint_count

    # exactly 5, not e.g. 2x from a bug that double-triggers per repaint() call
    assert after - before == 5
