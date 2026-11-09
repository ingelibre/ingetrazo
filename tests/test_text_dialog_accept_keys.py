"""The leader-text dialog accepts with Ctrl+Enter; Enter still adds a line (#696)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QPlainTextEdit

from views.prompts import build_multiline_dialog


def _run(dlg, keys):
    """Exec the dialog, press ``keys`` once it is up, return its result."""
    def press():
        edit = dlg.findChild(QPlainTextEdit)
        edit.setFocus()
        edit.moveCursor(edit.textCursor().MoveOperation.End)
        for key, modifiers in keys:
            QTest.keyClick(edit, key, modifiers)
        if dlg.isVisible():          # nothing accepted: close it ourselves
            dlg.reject()
    QTimer.singleShot(0, press)
    return dlg.exec()


@pytest.mark.parametrize("key, modifiers", [
    (Qt.Key_Return, Qt.ControlModifier),
    (Qt.Key_Enter, Qt.ControlModifier | Qt.KeypadModifier),
])
def test_ctrl_enter_accepts_and_keeps_the_text(key, modifiers):
    dlg = build_multiline_dialog(None, "Text", "Label text:", "Muro eje A")
    assert _run(dlg, [(key, modifiers)]) == QInputDialog.Accepted
    assert dlg.textValue() == "Muro eje A"


def test_enter_alone_adds_a_line_and_does_not_accept():
    dlg = build_multiline_dialog(None, "Text", "Label text:", "Muro")
    result = _run(dlg, [(Qt.Key_Return, Qt.NoModifier),
                        (Qt.Key_B, Qt.NoModifier)])
    assert result == QInputDialog.Rejected
    assert dlg.textValue() == "Muro\nb"


def test_the_dialog_says_how_to_accept():
    dlg = build_multiline_dialog(None, "Text", "Label text:", "")
    assert "Ctrl+Enter" in dlg.labelText()
    assert dlg.labelText().startswith("Label text:")
