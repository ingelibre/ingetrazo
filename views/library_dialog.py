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
        # Sorted by what is SHOWN, so the list reads alphabetically in the
        # language it is being read in; the raw category stays as the item's
        # data, because that is what the entries carry and what filters.
        cats = sorted({e.get("categoria", "") for e in self._entries},
                      key=self._cat_label)
        self._cat.addItem(tr("All categories"), "")
        for c in cats:
            self._cat.addItem(self._cat_label(c), c)
        self._refill()

        # Thumbnails arrive for what is on screen, a few per tick, so
        # scrolling never blocks on the network.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._fill_visible_thumbs)
        self._timer.start(120)

    # ---- listing -------------------------------------------------------
    #: The catalogue's categories, which arrive in Spanish, said in the
    #: language the program is running in. They are translated HERE and not
    #: taken from the catalogue's own English list, because the two
    #: disagree: the same model is "Dormitorio" in one and "Office" in the
    #: other, so reading both would scatter a category across two filters.
    CATEGORY_EN = {
        "Cocina": "Kitchen",
        "Cuarto de Baño": "Bathroom",
        "Dormitorio": "Bedroom",
        "Escaleras": "Staircases",
        "Exterior": "Exterior",
        "Iluminación": "Lights",
        "Oficina": "Office",
        "Personajes": "People",
        "Puertas y Ventanas": "Doors and windows",
        "Salón": "Living room",
        "Varios": "Miscellaneous",
        "Vehículos": "Vehicles",
    }

    @classmethod
    def _cat_label(cls, cat: str) -> str:
        return tr(cls.CATEGORY_EN.get(cat, cat))

    @staticmethod
    def _name_of(entry: dict) -> str:
        """The model's name in the language being read. The catalogue names
        each one in both and they agree one-to-one, so this is its own word
        either way — not a translation of ours."""
        from core.i18n import current_language
        if not current_language().startswith("es") and entry.get("nombre_en"):
            return entry["nombre_en"]
        return entry.get("nombre", entry.get("id", "?"))

    def _refill(self) -> None:
        text = self._search.text().strip().lower()
        cat = self._cat.currentData() or ""
        self._list.clear()
        shown = 0
        for e in self._entries:
            if cat and e.get("categoria") != cat:
                continue
            # Search both names: someone typing "chair" and someone
            # typing "silla" are both looking for the same model.
            if text and text not in e.get("nombre", "").lower() \
                    and text not in e.get("nombre_en", "").lower():
                continue
            it = QListWidgetItem(self._name_of(e))
            it.setData(Qt.UserRole, e)
            it.setToolTip(self._cat_label(e.get("categoria", "")))
            self._list.addItem(it)
            shown += 1
        if not self._entries:
            self._status.setText(tr(
                "The library could not be reached, and nothing is cached yet."))
        else:
            self._status.setText(tr("{n} of {total} models",
                                    n=shown, total=len(self._entries)))

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
        # No size here. Every model arrives at the size the catalogue
        # declares (core.library.model_matrix), so printing the centimetres
        # says nothing you cannot measure in the drawing — and it read as a
        # specification the component did not have.
        self._credit.setText(tr(
            "{name} · {licence} · by {author}",
            name=self._name_of(e),
            licence=tr(e.get("licencia_nombre") or e.get("licencia", "")),
            author=author))

    # ---- inserting -----------------------------------------------------
    def _insert(self) -> None:
        it = self._list.currentItem()
        if it is None:
            return
        entry = it.data(Qt.UserRole) or {}
        self._window.insert_library_component(entry)
        self.accept()
