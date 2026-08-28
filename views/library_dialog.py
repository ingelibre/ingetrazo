# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The online component library, browsable: a grid of thumbnails you filter
and search, and a click that downloads the model and hands it to the
placement tool.

Only the thumbnails of the rows you can actually SEE are fetched. The full
catalogue is ~1500 models and its previews are ~19 MB; pulling them all to
open a dialog would be a download every time for pictures nobody scrolled
to. They arrive as you scroll and stay in the cache.

The licence travels with the model and is shown, because these collections
mix public domain with attribution and copyleft — the user has to be able to
see whose work it is and what using it asks of them.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from core import library
from core.i18n import tr

ICON = 96


class LibraryDialog(QDialog):
    """Browse the published library and insert one of its models."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setWindowTitle(tr("Component library"))
        self.resize(760, 560)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("Search…"))
        self._search.textChanged.connect(self._refill)
        top.addWidget(self._search, 1)
        self._cat = QComboBox()
        self._cat.currentIndexChanged.connect(self._refill)
        top.addWidget(self._cat)
        lay.addLayout(top)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setIconSize(QSize(ICON, ICON))
        self._list.setGridSize(QSize(ICON + 34, ICON + 46))
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setWordWrap(True)
        self._list.itemDoubleClicked.connect(lambda _i: self._insert())
        self._list.currentItemChanged.connect(self._show_credit)
        lay.addWidget(self._list, 1)

        self._credit = QLabel("")
        self._credit.setWordWrap(True)
        lay.addWidget(self._credit)

        row = QHBoxLayout()
        self._status = QLabel("")
        row.addWidget(self._status, 1)
        self._insert_btn = QPushButton(tr("Insert"))
        self._insert_btn.setDefault(True)
        self._insert_btn.clicked.connect(self._insert)
        row.addWidget(self._insert_btn)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

        self._entries = library.index()
        cats = sorted({e.get("categoria", "") for e in self._entries})
        self._cat.addItem(tr("All categories"), "")
        for c in cats:
            self._cat.addItem(c, c)
        self._refill()

        # Thumbnails arrive for what is on screen, a few per tick, so
        # scrolling never blocks on the network.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fill_visible_thumbs)
        self._timer.start(120)

    # ---- listing -------------------------------------------------------
    def _refill(self) -> None:
        text = self._search.text().strip().lower()
        cat = self._cat.currentData() or ""
        self._list.clear()
        shown = 0
        for e in self._entries:
            if cat and e.get("categoria") != cat:
                continue
            if text and text not in e.get("nombre", "").lower():
                continue
            it = QListWidgetItem(e.get("nombre", e.get("id", "?")))
            it.setData(Qt.UserRole, e)
            it.setToolTip("%s · %s" % (e.get("categoria", ""),
                                       self._size_text(e)))
            self._list.addItem(it)
            shown += 1
        if not self._entries:
            self._status.setText(tr(
                "The library could not be reached, and nothing is cached yet."))
        else:
            self._status.setText(tr("{n} of {total} models",
                                    n=shown, total=len(self._entries)))

    @staticmethod
    def _size_text(entry) -> str:
        cm = [c for c in (entry.get("cm") or []) if c]
        return " × ".join("%s cm" % c for c in cm) if cm else ""

    #: Rows past the bottom of the view whose preview is fetched anyway, so
    #: scrolling lands on pictures instead of on empty squares.
    _LOOKAHEAD = 40

    def _fill_visible_thumbs(self) -> None:
        """Paint the previews that have arrived and ask for the ones that
        have not — the asking happens in the background (see
        :func:`core.library.prefetch_thumbnails`), so this never waits on
        the network and the dialog never freezes while it fills."""
        rect = self._list.viewport().rect()
        wanted, first, last = [], None, None
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it is None:
                continue
            if not rect.intersects(self._list.visualItemRect(it)):
                continue
            first = i if first is None else first
            last = i
            if not it.icon().isNull():
                continue
            entry = it.data(Qt.UserRole) or {}
            ident = entry.get("id", "")
            p = library.cached_thumbnail(ident)
            if p is None:
                wanted.append(ident)
                continue
            pix = QPixmap(str(p))
            if not pix.isNull():
                it.setIcon(QIcon(pix))
        if last is not None:
            for i in range(last + 1, min(last + 1 + self._LOOKAHEAD,
                                         self._list.count())):
                it = self._list.item(i)
                if it is not None and it.icon().isNull():
                    wanted.append((it.data(Qt.UserRole) or {}).get("id", ""))
        if wanted:
            library.prefetch_thumbnails(wanted)

    def _show_credit(self, current, _prev=None) -> None:
        e = current.data(Qt.UserRole) if current is not None else None
        if not e:
            self._credit.setText("")
            return
        author = e.get("autor") or tr("unknown author")
        self._credit.setText(tr(
            "{name} — {size} · {licence} · by {author}",
            name=e.get("nombre", ""), size=self._size_text(e),
            licence=e.get("licencia_nombre") or e.get("licencia", ""),
            author=author))

    # ---- inserting -----------------------------------------------------
    def _insert(self) -> None:
        it = self._list.currentItem()
        if it is None:
            return
        entry = it.data(Qt.UserRole) or {}
        self._window.insert_library_component(entry)
        self.accept()
