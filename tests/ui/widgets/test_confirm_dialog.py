"""ConfirmDialog: docs/05 §6.6 — May I? modal with preview list, Yes/No, Esc = No."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QPushButton

from nova.ui.widgets.confirm_dialog import ConfirmDialog


def _buttons(dialog: ConfirmDialog) -> dict[str, QPushButton]:
    return {b.text(): b for b in dialog.findChildren(QPushButton)}


def test_shows_detail_and_preview(qtbot) -> None:
    dialog = ConfirmDialog("Tidying up your Desktop", ["Move a.png into Pictures"])
    qtbot.addWidget(dialog)

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "Tidying up your Desktop" in labels
    preview = dialog.findChild(QListWidget)
    assert preview is not None
    assert preview.count() == 1
    assert preview.item(0).text() == "Move a.png into Pictures"


def test_no_preview_list_when_empty(qtbot) -> None:
    dialog = ConfirmDialog("May I?", [])
    qtbot.addWidget(dialog)
    assert dialog.findChild(QListWidget) is None


def test_yes_accepts(qtbot) -> None:
    dialog = ConfirmDialog("detail", [])
    qtbot.addWidget(dialog)
    _buttons(dialog)["Yes, do it"].click()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_no_rejects(qtbot) -> None:
    dialog = ConfirmDialog("detail", [])
    qtbot.addWidget(dialog)
    _buttons(dialog)["No, stop"].click()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_escape_rejects(qtbot) -> None:
    dialog = ConfirmDialog("detail", [])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.result() == QDialog.DialogCode.Rejected
