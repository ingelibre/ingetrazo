# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tooltips that wrap.

Qt shows a plain-text tooltip on ONE line, however long, and only folds
it when it would not fit the screen; a rich-text one wraps into a box of
a comfortable width. So a long hint read as a strip across the window
while a longer one next to it came out as a neat block (Marco, 2026-09-20:
«en algunos sale en una línea que no me gusta como el texto es extenso,
pero en otras sale en tipo cuadro delimitado que sale bien»).

The filter turns every plain-text tooltip into rich text on its way to
the screen — escaped, so a ``<>`` or an ``&`` in a hint still reads as
written — and leaves tooltips that already are rich text, and widgets
that make theirs up on the spot (no ``toolTip()``), to Qt.

A toolbar button's tooltip is its name and keys over what it does
(«Line  (L)», then a sentence): the name goes in bold, so it reads apart
from the sentence under it. Only on screen — the stored tooltip stays
plain text, which the command search and the shortcuts read.

Not every button writes its tooltip that way — an extension's often
says it all on one line («Extruder — extrudes each face…»), or only its
name, with the sentence in the status tip, or only the sentence — so the
layout is worked out from the button's action when it is shown: any
button on any toolbar, the ones added later included, reads the same
(Marco, 2026-10-16: «que revea automáticamente para futuras
actualizaciones nuevos botones o botones de plugins»).
"""
from __future__ import annotations

import html
import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QKeySequence, Qt
from PySide6.QtWidgets import QToolBar, QToolButton, QToolTip, QWidget

# What may stand between a name and its sentence on one line: «Orbit (O) —
# left-drag…», «Zoom: drag up…», «Extruder - extrudes…».
_KEYS = re.compile(r"[ \t]*\(([^()\n]*)\)")
_SEP = re.compile(r"[ \t]*[—–:][ \t]*|[ \t]+-[ \t]+")


def wrapped(text: str, titled: bool = False) -> str:
    """*text* as rich text that wraps, or itself when it already is.

    *titled*: the first line names what the rest describes — the name, not
    the keys after it, goes in bold. A tooltip of one line stays as is."""
    if not text or Qt.mightBeRichText(text):
        return text
    if titled and "\n" in text:
        first, rest = text.split("\n", 1)
        name, sep, keys = first.partition("  (")
        body = "<b>" + html.escape(name) + "</b>" + \
            html.escape(sep + keys) + "\n" + html.escape(rest)
    else:
        body = html.escape(text)
    return "<p style='white-space:normal'>" + \
        body.replace("\n", "<br>") + "</p>"


def _bare(text: str) -> str:
    """An action's text as it reads: no ``&`` mnemonic, no trailing «…»."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&") \
        .rstrip("…").rstrip(".").strip()


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


def titled_text(text: str, name: str, keys: str = "",
                status: str = "") -> str:
    """*text*, a toolbar button's tooltip, as «name  (keys)» over what the
    button does — the shape :func:`wrapped` sets in bold — whatever shape
    it came in. *name*, *keys* and *status* are its action's text,
    shortcut and status tip. Unchanged when there is no name to set apart
    or nothing to say under it."""
    if not text or "\n" in text or Qt.mightBeRichText(text):
        return text
    name = _bare(name)
    if not name:
        return text
    desc = None
    if text.casefold().startswith(name.casefold()):
        pos = len(name)
        m = _KEYS.match(text, pos)
        if m is not None:
            keys, pos = m.group(1).strip() or keys, m.end()
        tail = text[pos:]
        if not tail.strip():
            desc = ""                       # the name alone
        else:
            m = _SEP.match(tail)
            if m is not None:               # name, then its sentence
                name, desc = text[:len(name)], tail[m.end():]
    if desc is None:                        # a sentence of its own
        desc = text
    if not desc.strip() and status.strip() and \
            _bare(status).casefold() != name.casefold():
        desc = status
    desc = desc.strip()
    if not desc:
        return text
    head = f"{name}  ({keys})" if keys else name
    return head + "\n" + _sentence(desc)


def _titled(widget: QWidget) -> bool:
    """A toolbar button, whose tooltip is a name over a description."""
    return isinstance(widget, QToolButton) and \
        isinstance(widget.parentWidget(), QToolBar)


def _toolbar_tip(button: QToolButton) -> str:
    text = button.toolTip()
    act = button.defaultAction()
    if act is None:
        return text
    keys = act.shortcut().toString(QKeySequence.NativeText)
    return titled_text(text, act.text(), keys, act.statusTip())


class WrappingToolTips(QObject):
    """Application-wide event filter: ``app.installEventFilter(...)``."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt override
        if event.type() == QEvent.ToolTip and isinstance(obj, QWidget):
            text = obj.toolTip()
            if text and not Qt.mightBeRichText(text):
                titled = _titled(obj)
                if titled:
                    text = _toolbar_tip(obj)
                QToolTip.showText(event.globalPos(),
                                  wrapped(text, titled), obj)
                event.accept()
                return True
        return False
