# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The work area with every project closed: a quiet hatching and nothing
else — no tabs, no views button, no panels; only **+** above it to start
a new project (``MainWindow._show_empty_area``). A file dragged onto it
opens, as File ▸ Open would.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget


class EmptyArea(QWidget):
    """Hatched, in the palette's colours, light or dark."""

    #: Files dropped on it that it can open ([Path]).
    filesDropped = Signal(list)

    #: Distance (px) between the hatching's lines.
    STEP = 7

    def __init__(self, suffixes=(".igz",), parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("empty_area")
        self.setAcceptDrops(True)
        #: What a drop may open: a tuple, or a callable giving one (the
        #: window's, so an extension's file types count too).
        self.suffixes = suffixes

    # ---- drawing -------------------------------------------------------------
    def paintEvent(self, _ev) -> None:  # noqa: N802 — Qt override
        p = QPainter(self)
        pal = self.palette()
        base = pal.color(pal.ColorRole.Window)
        dark = base.lightness() < 128
        grad = QLinearGradient(QPointF(0, 0), QPointF(0, self.height()))
        grad.setColorAt(0.0, base.lighter(118) if dark else base.darker(104))
        grad.setColorAt(1.0, base.darker(112))
        p.fillRect(self.rect(), grad)
        ink = QColor(pal.color(pal.ColorRole.WindowText))
        ink.setAlpha(22 if dark else 16)
        p.setPen(QPen(ink, 1))
        w, h = self.width(), self.height()
        for x in range(-h, w, self.STEP):
            p.drawLine(QPointF(x, h), QPointF(x + h, 0))
        p.end()

    # ---- drag and drop -------------------------------------------------------
    def _dropped(self, ev) -> list:
        mime = ev.mimeData()
        if not mime.hasUrls():
            return []
        ok = self.suffixes() if callable(self.suffixes) else self.suffixes
        return [Path(u.toLocalFile()) for u in mime.urls()
                if u.isLocalFile()
                and Path(u.toLocalFile()).suffix.lower() in ok]

    def dragEnterEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if self._dropped(ev):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self.dragEnterEvent(ev)

    def dropEvent(self, ev) -> None:  # noqa: N802 — Qt override
        files = self._dropped(ev)
        if not files:
            ev.ignore()
            return
        ev.acceptProposedAction()
        self.filesDropped.emit(files)
