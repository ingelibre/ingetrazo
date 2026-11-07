# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A text prompt wide enough to read.

``QInputDialog.getText`` sizes itself to its contents, so a short label
gave a dialog a few centimetres wide whose title the window manager cut to
«Crear…» (Rafael, revision 4, 02:16 and 06:24). Same call, same answer,
with a sensible floor on the width. ``get_multiline_text`` does the same
for ``getMultiLineText`` and adds Ctrl+Enter to accept.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QInputDialog, QLineEdit, QPlainTextEdit

#: Wide enough for a title like «Crear componente» and a name to edit.
MIN_WIDTH = 380

#: Qt's own static prompt, as imported. A test (or a plugin) that replaces
#: ``QInputDialog.getText`` to answer for the user is still obeyed.
_QT_GET_TEXT = QInputDialog.getText


def get_text(parent, title: str, label: str, echo=QLineEdit.Normal,
             text: str = "", **_ignored) -> tuple[str, bool]:
    """Drop-in for ``QInputDialog.getText`` returning ``(text, ok)``."""
    if QInputDialog.getText is not _QT_GET_TEXT:
        if echo == QLineEdit.Normal:
            return QInputDialog.getText(parent, title, label, text=text)
        return QInputDialog.getText(parent, title, label, echo, text=text)
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextEchoMode(echo)
    dlg.setTextValue(text)
    dlg.setMinimumWidth(MIN_WIDTH)
    dlg.resize(max(dlg.sizeHint().width(), MIN_WIDTH), dlg.sizeHint().height())
    ok = dlg.exec() == QInputDialog.Accepted
    return dlg.textValue(), ok


#: Qt's own static multi-line prompt, as imported; replacing it still answers.
_QT_GET_MULTILINE_TEXT = QInputDialog.getMultiLineText

class _CtrlEnterAccepts(QObject):
    """Accept ``dialog`` on Ctrl+Enter (main or keypad) typed in its editor.

    An event filter on the editor rather than a ``QShortcut``: a window
    shortcut only fires once the dialog window is active, and the plain-text
    editor would otherwise take Ctrl+Enter as one more new line.
    """

    def __init__(self, dialog: QInputDialog) -> None:
        super().__init__(dialog)
        self._dialog = dialog

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt API)
        if (event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and event.modifiers() & Qt.ControlModifier):
            self._dialog.accept()
            return True
        return False


def build_multiline_dialog(parent, title: str, label: str,
                           text: str = "") -> QInputDialog:
    """The dialog behind :func:`get_multiline_text`, not yet shown.

    Enter keeps inserting a new line, since a label can span several, so
    Ctrl+Enter accepts it without reaching for the mouse (#696). The label
    says so.
    """
    from core.i18n import tr

    dlg = QInputDialog(parent)
    dlg.setOption(QInputDialog.UsePlainTextEditForTextInput, True)
    dlg.setWindowTitle(title)
    dlg.setLabelText(f"{label}\n{tr('Ctrl+Enter to accept')}")
    dlg.setTextValue(text)
    dlg.setMinimumWidth(MIN_WIDTH)
    dlg.findChild(QPlainTextEdit).installEventFilter(_CtrlEnterAccepts(dlg))
    return dlg


def get_multiline_text(parent, title: str, label: str,
                       text: str = "") -> tuple[str, bool]:
    """Drop-in for ``QInputDialog.getMultiLineText`` returning ``(text, ok)``."""
    if QInputDialog.getMultiLineText is not _QT_GET_MULTILINE_TEXT:
        return QInputDialog.getMultiLineText(parent, title, label, text)
    dlg = build_multiline_dialog(parent, title, label, text)
    ok = dlg.exec() == QInputDialog.Accepted
    return dlg.textValue(), ok
