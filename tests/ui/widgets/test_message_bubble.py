"""Unit tests for nova.ui.widgets.message_bubble — role-based layout, sizing, entry fade."""

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect

from nova.ui.theme import Color
from nova.ui.widgets.message_bubble import MessageBubble


@pytest.fixture(autouse=True)
def _do_not_auto_start_fade(monkeypatch: pytest.MonkeyPatch) -> None:
    """The entry-fade animation itself is covered generically by test_animations.py; block it
    here so opacity stays at its constructed initial value for the sizing/layout assertions."""
    monkeypatch.setattr(QTimer, "singleShot", lambda _ms, _callback: None)


def test_displays_the_given_text_immediately(qtbot: object) -> None:
    bubble = MessageBubble("Hello there", role="user")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    assert bubble._label.text() == "Hello there"


def test_user_bubble_uses_user_background_color(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="user")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    assert Color.BUBBLE_USER in bubble._label.styleSheet()


def test_nova_bubble_uses_nova_background_color(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="nova")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    assert Color.BUBBLE_NOVA in bubble._label.styleSheet()


def test_user_bubble_is_right_aligned(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="user")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    layout = bubble.layout()
    assert layout.itemAt(0).widget() is None  # leading stretch pushes the bubble right
    assert layout.itemAt(1).widget() is bubble._label


def test_nova_bubble_is_left_aligned(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="nova")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    layout = bubble.layout()
    # wrapped in a `content` widget (alongside the speaker glyph row) rather than the bare
    # label directly — see test_nova_bubble_has_a_speaker_glyph_that_stops_speech below.
    content = layout.itemAt(0).widget()
    assert content is not None
    assert content.layout().itemAt(0).widget() is bubble._label
    assert layout.itemAt(1).widget() is None  # trailing stretch keeps it left


def test_user_bubble_has_no_speaker_glyph(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="user")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]

    assert not hasattr(bubble, "_speaker_button")


def test_nova_bubble_has_a_speaker_glyph_that_stops_speech(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="nova")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]

    with qtbot.waitSignal(bubble.stop_speech_requested, timeout=1000):  # type: ignore[attr-defined]
        bubble._speaker_button.click()


def test_set_max_bubble_width_constrains_to_72_percent(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="user")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    bubble.set_max_bubble_width(1000)
    assert bubble._label.maximumWidth() == 720


def test_set_max_bubble_width_never_goes_to_zero_or_below(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="user")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    bubble.set_max_bubble_width(0)
    assert bubble._label.maximumWidth() >= 1


def test_starts_fully_transparent_before_the_entry_fade_runs(qtbot: object) -> None:
    bubble = MessageBubble("hi", role="user")
    qtbot.addWidget(bubble)  # type: ignore[attr-defined]
    effect = bubble.graphicsEffect()
    assert isinstance(effect, QGraphicsOpacityEffect)
    assert effect.opacity() == pytest.approx(0.0)
