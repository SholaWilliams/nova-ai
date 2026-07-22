"""Unit tests for nova.ui.views.memory_view — card list, delete/clear confirm flows (T-504)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nova.core.models import MemoryItem
from nova.ui.views.memory_view import MemoryView
from nova.ui.widgets.confirm_dialog import ConfirmDialog


def _item(content: str = "Has a dog", kind: str = "fact", fact_id: str = "f_1") -> MemoryItem:
    return MemoryItem(
        id=fact_id,
        kind=kind,  # type: ignore[arg-type]
        content=content,
        keywords=(),
        created_at=datetime.now(UTC),
        source_request="req_1",
    )


@pytest.fixture
def view(qtbot: object) -> MemoryView:
    widget = MemoryView()
    qtbot.addWidget(widget)  # type: ignore[attr-defined]
    return widget


def test_empty_state_shown_when_no_facts(view: MemoryView) -> None:
    assert not view._empty_label.isHidden()
    assert view.card_count() == 0


def test_set_facts_populates_cards_and_hides_empty_state(view: MemoryView) -> None:
    view.set_facts([_item("Has a dog"), _item("Likes pizza", fact_id="f_2")])

    assert view.card_count() == 2
    assert view._empty_label.isHidden()


def test_set_facts_replaces_previous_cards(view: MemoryView) -> None:
    view.set_facts([_item("Has a dog")])
    view.set_facts([_item("Likes pizza", fact_id="f_2")])

    assert view.card_count() == 1


def test_clear_all_button_disabled_when_empty(view: MemoryView) -> None:
    assert not view._clear_all_button.isEnabled()


def test_clear_all_button_enabled_with_facts(view: MemoryView) -> None:
    view.set_facts([_item()])
    assert view._clear_all_button.isEnabled()


def test_clear_all_confirmed_emits_clear_all_requested(
    view: MemoryView, qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    view.set_facts([_item()])
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: ConfirmDialog.DialogCode.Accepted)

    with qtbot.waitSignal(view.clear_all_requested, timeout=1000):  # type: ignore[attr-defined]
        view._clear_all_button.click()


def test_clear_all_declined_emits_nothing(
    view: MemoryView, monkeypatch: pytest.MonkeyPatch
) -> None:
    view.set_facts([_item()])
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: ConfirmDialog.DialogCode.Rejected)
    received: list[bool] = []
    view.clear_all_requested.connect(lambda: received.append(True))

    view._clear_all_button.click()

    assert received == []


def test_card_delete_confirmed_emits_delete_requested_with_id(
    view: MemoryView, qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    view.set_facts([_item(fact_id="f_42")])
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: ConfirmDialog.DialogCode.Accepted)
    card = view._column_layout.itemAt(0).widget()

    with qtbot.waitSignal(view.delete_requested, timeout=1000) as blocker:  # type: ignore[attr-defined]
        card._delete_button.click()

    assert blocker.args == ["f_42"]


def test_card_delete_declined_emits_nothing(
    view: MemoryView, monkeypatch: pytest.MonkeyPatch
) -> None:
    view.set_facts([_item(fact_id="f_42")])
    monkeypatch.setattr(ConfirmDialog, "exec", lambda self: ConfirmDialog.DialogCode.Rejected)
    card = view._column_layout.itemAt(0).widget()
    received: list[str] = []
    view.delete_requested.connect(received.append)

    card._delete_button.click()

    assert received == []
