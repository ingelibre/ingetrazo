# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Drag a component from a list and drop it in the view.

A double click starts the Place component tool and a second click drops
the piece. Dragging does both in one gesture: the moment the pointer
enters the view the same tool starts, the piece follows the pointer with
its snaps, and letting go places it — one undo step, like the click.
Let go anywhere else, or press Esc, and nothing is placed.

Any list can offer it, a plugin's too: it adds a *starter* — the callable
its double click already runs, which hands a group to
``MainWindow._start_place`` — to the drag's data with :func:`offer`, and
calls :func:`finished` once the drag is over. The view
(``views/viewport/interaction.py``) accepts any drag that carries one.

The starter is a Python callable, so it never leaves the program: the
drag's data carries a token and the callable waits here, one drag at a
time (a drag is modal: there is never a second one under way).
"""
from __future__ import annotations

from itertools import count
from typing import Callable, Optional

from PySide6.QtCore import QByteArray, QMimeData, Qt

#: The format a drag that can place a component carries.
MIME = "application/x-ingetrazo-place"

_tokens = count(1)
#: ``(token, starter)`` of the drag under way, ``None`` between drags.
_pending: Optional[tuple] = None


def offer(mime: QMimeData, starter: Callable[[], None]) -> QMimeData:
    """Add ``starter`` to ``mime``: dropped in the view, the drag places
    what ``starter`` puts on the pointer. Returns ``mime``."""
    global _pending
    token = str(next(_tokens))
    _pending = (token, starter)
    mime.setData(MIME, QByteArray(token.encode("ascii")))
    return mime


def starter_of(mime) -> Optional[Callable[[], None]]:
    """The starter a drag's ``mime`` carries, ``None`` when it carries
    none (or one from a drag that is over)."""
    if mime is None or not mime.hasFormat(MIME) or _pending is None:
        return None
    token = bytes(mime.data(MIME)).decode("ascii", "replace")
    return _pending[1] if token == _pending[0] else None


def finished(action) -> None:
    """The drag is over (``QDrag.exec`` returned ``action``). Not dropped
    in the view — let go elsewhere, or Esc — the piece the view put on the
    pointer goes away: the drag offered a placement, not a pending tool."""
    global _pending
    _pending = None
    from PySide6.QtWidgets import QApplication
    for widget in QApplication.topLevelWidgets():
        vp = getattr(widget, "viewport", None)
        end = getattr(vp, "end_place_drag", None)
        if callable(end):
            end(placed=action == Qt.CopyAction)


#: The actions a drag that offers a placement allows: Move for its own
#: list (categories, folders), Copy for the view — a copy is what it is.
ACTIONS = Qt.MoveAction | Qt.CopyAction


def run(drag, default=Qt.MoveAction):
    """``drag.exec`` for a drag that may carry a starter, followed by
    :func:`finished` — the one call a list makes. Returns the action."""
    action = drag.exec(ACTIONS, default)
    finished(action)
    return action
