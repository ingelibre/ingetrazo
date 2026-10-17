# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A text prompt wide enough to read.

``QInputDialog.getText`` sizes itself to its contents, so a short label
gave a dialog a few centimetres wide whose title the window manager cut to
«Crear…» (Rafael, revision 4, 02:16 and 06:24). Same call, same answer,
with a sensible floor on the width.
"""
from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QInputDialog, QLineEdit
from core.i18n import tr

#: Wide enough for a title like «Crear componente» and a name to edit.
MIN_WIDTH = 380

#: Qt's own static prompt, as imported. A test (or a plugin) that replaces
#: ``QInputDialog.getText`` to answer for the user is still obeyed.
_QT_GET_TEXT = QInputDialog.getText

#: Same override convention for the multi-line prompt below.
_QT_GET_MULTI_LINE_TEXT = QInputDialog.getMultiLineText


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


def _multiline_dialog(parent, title: str, label: str,
                      text: str = "") -> QInputDialog:
    """Build the multi-line text prompt (issue #696).

    Enter keeps inserting new lines — labels are multi-line — so the
    dialog also accepts Ctrl+Enter (and Ctrl+Return, for keyboards whose
    main key reports ``Return``), with the hint shown under the label.
    """
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label + "\n" + tr("Ctrl+Enter: accept"))
    dlg.setTextValue(text)
    dlg.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput,
                  True)
    dlg.setMinimumWidth(MIN_WIDTH)
    dlg.resize(max(dlg.sizeHint().width(), MIN_WIDTH), dlg.sizeHint().height())
    for seq in ("Ctrl+Return", "Ctrl+Enter"):
        QShortcut(QKeySequence(seq), dlg, activated=dlg.accept)
    return dlg


def get_multiline_text(parent, title: str, label: str, text: str = "",
                       **_ignored) -> tuple[str, bool]:
    """Drop-in for ``QInputDialog.getMultiLineText`` returning ``(text, ok)``.

    A test (or a plugin) that replaces ``QInputDialog.getMultiLineText``
    to answer for the user is still obeyed, like :func:`get_text`.
    """
    if QInputDialog.getMultiLineText is not _QT_GET_MULTI_LINE_TEXT:
        return QInputDialog.getMultiLineText(parent, title, label, text)
    dlg = _multiline_dialog(parent, title, label, text)
    ok = dlg.exec() == QInputDialog.Accepted
    return dlg.textValue(), ok
