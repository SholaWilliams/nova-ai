"""Unit tests for nova.ui.views.chat_view — bubble insertion, ordering, and auto-scroll."""

import pytest
from PySide6.QtCore import QTimer

from nova.ui.views.chat_view import ChatView
from nova.ui.widgets.message_bubble import MessageBubble


@pytest.fixture(autouse=True)
def _run_timers_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the deferred (QTimer.singleShot) scroll-to-bottom so it runs within the test."""
    monkeypatch.setattr(QTimer, "singleShot", lambda _ms, callback: callback())


@pytest.fixture
def view(qtbot: object) -> ChatView:
    widget = ChatView()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    return widget


def test_starts_with_no_bubbles(view: ChatView) -> None:
    assert view.bubble_count() == 0


def test_add_user_message_creates_a_user_role_bubble_with_text(view: ChatView) -> None:
    view.add_user_message("hello")

    bubble = view._column_layout.itemAt(0).widget()
    assert view.bubble_count() == 1
    assert isinstance(bubble, MessageBubble)
    assert bubble._role == "user"
    assert bubble._label.text() == "hello"


def test_add_nova_message_creates_a_nova_role_bubble_with_text(view: ChatView) -> None:
    view.add_nova_message("hi there")

    bubble = view._column_layout.itemAt(0).widget()
    assert view.bubble_count() == 1
    assert isinstance(bubble, MessageBubble)
    assert bubble._role == "nova"
    assert bubble._label.text() == "hi there"


def test_bubbles_are_appended_in_insertion_order(view: ChatView) -> None:
    view.add_user_message("first")
    view.add_nova_message("second")
    view.add_user_message("third")

    texts = [view._column_layout.itemAt(i).widget()._label.text() for i in range(3)]
    assert texts == ["first", "second", "third"]
    assert view.bubble_count() == 3


def test_new_bubble_width_is_constrained_to_chat_view_width(view: ChatView) -> None:
    view.resize(400, 150)
    view.add_user_message("hi")

    bubble = view._column_layout.itemAt(0).widget()
    assert bubble._label.maximumWidth() == int(400 * 0.72)


def test_is_scrolled_to_bottom_true_within_epsilon_of_max(view: ChatView) -> None:
    bar = view._scroll_area.verticalScrollBar()
    bar.setRange(0, 100)
    bar.setValue(90)  # within the 24px epsilon
    assert view._is_scrolled_to_bottom() is True


def test_is_scrolled_to_bottom_false_when_scrolled_away_from_max(view: ChatView) -> None:
    bar = view._scroll_area.verticalScrollBar()
    bar.setRange(0, 100)
    bar.setValue(50)
    assert view._is_scrolled_to_bottom() is False


def test_adding_a_message_autoscrolls_when_already_at_bottom(view: ChatView) -> None:
    bar = view._scroll_area.verticalScrollBar()
    bar.setRange(0, 100)
    bar.setValue(100)

    view.add_user_message("hi")

    assert bar.value() == bar.maximum()


def test_adding_a_message_does_not_autoscroll_when_scrolled_up(view: ChatView) -> None:
    bar = view._scroll_area.verticalScrollBar()
    bar.setRange(0, 100)
    bar.setValue(0)

    view.add_user_message("hi")

    assert bar.value() == 0
