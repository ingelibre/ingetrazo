# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The composer's «Sheets» side panel: every sheet as a page, the way a PDF
reader lists its pages (Marco, 19-11: «me gustaria que haya como en la barra
lateral derecha como un gestor de laminas … donde pueda seleccionar la
lamina, cambiar el orden, cambiar nombre eliminar, y que se muestren en
miniatura, como si fuera cada pagina como tienen algunos programas de
pdf»).

A click opens the sheet, a drag reorders the set (the same undo step as a
tab dragged along the strip), a double-click or F2 renames it, Delete
removes it (asking first), and the right-click menu is the strip's own.
Everything goes through the composer's sheet functions — this panel only
lists and forwards.

The pictures are the sheet painted from what the composer already holds —
each frame's cached render or hidden-line drawing, exactly what the export
prints — and never a new render: on a big model one frame costs seconds,
and a panel of fifteen pages would freeze the window to show stamps. A
frame never rendered this session shows the canvas's own «Update the view»
placeholder. Each picture is cached per sheet and painted again only when
that sheet changed, 300 ms after the last change (an edit, a render that
landed, a reorder that renumbered it), one per pass of the event loop, and
only while the panel is on screen.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QListWidget,
                               QListWidgetItem, QStyle, QStyledItemDelegate,
                               QVBoxLayout, QWidget)

from core.composition import ComposerCommand
from core.i18n import tr


class SheetOrderCommand(ComposerCommand):
    """A sheet to another place in the set, as one step of the composer's
    undo. The model's own ``MoveSheetCommand`` does the move (the Views and
    sheets panel's Alt+↑/↓); ``after(old, new)`` lets the composer catch up
    — strips, panel, sheet numbers — after both do and undo."""

    def __init__(self, scene, sheet, index: int, after=None) -> None:
        from core.history import MoveSheetCommand
        self.scene = scene
        self.sheet = sheet
        self._move = MoveSheetCommand(sheet, index)
        self._after = after
        self._from = scene.compositions.index(sheet)
        self._to = max(0, min(int(index), len(scene.compositions) - 1))

    def do(self) -> None:
        self._move.do(self.scene)
        if self._after is not None:
            self._after(self._from, self._to)

    def undo(self) -> None:
        self._move.undo(self.scene)
        if self._after is not None:
            self._after(self._to, self._from)


#: The box a page's picture fits in, in logical pixels: a landscape sheet is
#: this wide, a portrait one this tall.
THUMB_PX = 150
#: Around each page, and between the picture and its name.
PAD = 8
GAP = 4

_SHEET_ROLE = Qt.UserRole          # id() of the sheet the row shows
_BOX_ROLE = Qt.UserRole + 1        # QSize of the picture's box


def thumb_box(comp) -> QSize:
    """The picture's size for ``comp``, in proportion to its paper."""
    pw, ph = comp.page_size_mm()
    if pw <= 0 or ph <= 0:
        return QSize(THUMB_PX, THUMB_PX)
    if pw >= ph:
        return QSize(THUMB_PX, max(1, round(THUMB_PX * ph / pw)))
    return QSize(max(1, round(THUMB_PX * pw / ph)), THUMB_PX)


class _PageDelegate(QStyledItemDelegate):
    """A page: its picture in the middle with a paper edge and a shadow,
    the name under it; the open sheet in the selection colour."""

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self._panel = panel

    def _text_h(self, option) -> int:
        return option.fontMetrics.height() + 2

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        box = index.data(_BOX_ROLE) or QSize(THUMB_PX, THUMB_PX)
        width = max(self._panel.list.viewport().width(), box.width() + 2 * PAD)
        return QSize(width, PAD + box.height() + GAP + self._text_h(option)
                     + PAD)

    def _rects(self, option, index):
        box = index.data(_BOX_ROLE) or QSize(THUMB_PX, THUMB_PX)
        r = option.rect
        pic = QRect(r.left() + (r.width() - box.width()) // 2,
                    r.top() + PAD, box.width(), box.height())
        text = QRect(r.left() + 4, pic.bottom() + 1 + GAP, r.width() - 8,
                     self._text_h(option))
        return pic, text

    def paint(self, painter, option, index) -> None:
        painter.save()
        selected = bool(option.state & QStyle.State_Selected)
        pal = option.palette
        if selected:
            hl = QColor(pal.highlight().color())
            hl.setAlpha(70)
            painter.setPen(Qt.NoPen)
            painter.setBrush(hl)
            painter.drawRoundedRect(option.rect.adjusted(2, 1, -2, -1), 5, 5)
        pic, text = self._rects(option, index)
        painter.fillRect(pic.translated(2, 2), QColor(0, 0, 0, 60))
        pixmap = self._panel.pixmap_for(index.data(_SHEET_ROLE))
        if pixmap is not None:
            painter.drawPixmap(pic, pixmap)
        else:                           # not painted yet: blank paper
            painter.fillRect(pic, QColor(255, 255, 255))
        pen = QPen(pal.highlight().color() if selected
                   else QColor(150, 150, 150))
        pen.setWidth(2 if selected else 1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(pic.adjusted(0, 0, -1, -1))
        name = str(index.data(Qt.DisplayRole) or "")
        font = option.font
        font.setBold(selected)
        painter.setFont(font)
        painter.setPen(pal.text().color())
        painter.drawText(text, Qt.AlignHCenter | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(
                             name, Qt.ElideRight, text.width()))
        painter.restore()

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        # Renamed in place, where the name is — not over the picture.
        _pic, text = self._rects(option, index)
        editor.setGeometry(text.adjusted(0, -2, 0, 2))


class _PagesList(QListWidget):
    """The pages; a page dropped among the others moves that sheet —
    through the composer, never by Qt shuffling the rows itself (the rows
    are a picture of ``scene.compositions``, which the composer reorders
    and the panel then lists again)."""

    def __init__(self, panel) -> None:
        super().__init__(panel)
        self._panel = panel
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragDropOverwriteMode(False)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setResizeMode(QListWidget.Adjust)
        self.setUniformItemSizes(False)
        self.setEditTriggers(QAbstractItemView.DoubleClicked
                             | QAbstractItemView.EditKeyPressed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)

    def drop_row(self, pos) -> int:
        """Where a drop at ``pos`` (viewport coordinates) puts the page, as
        a row of the list before the dragged page leaves it."""
        item = self.itemAt(pos)
        if item is None:
            return self.count()
        r = self.visualItemRect(item)
        row = self.row(item)
        return row if pos.y() < r.center().y() else row + 1

    def dropEvent(self, event) -> None:  # noqa: N802 — Qt override
        src = self.currentRow()
        row = self.drop_row(event.position().toPoint())
        # Nothing for Qt to move: the composer moves the sheet and the rows
        # follow. IgnoreAction, or the drag's source would drop the row.
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
        self.setState(QAbstractItemView.NoState)
        self.viewport().update()
        if src < 0:
            return
        dst = row - 1 if row > src else row
        if dst != src:
            QTimer.singleShot(0, lambda: self._panel.move(src, dst))

    def event(self, event) -> bool:  # noqa: N802 — Qt override
        # Delete is also the composer's «delete the selected item»
        # shortcut: here, with the focus on the pages, it means the page.
        from PySide6.QtCore import QEvent
        if (event.type() == QEvent.ShortcutOverride
                and event.key() == Qt.Key_Delete
                and self.state() != QAbstractItemView.EditingState):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt override
        if (event.key() == Qt.Key_Delete
                and self.state() != QAbstractItemView.EditingState
                and self.currentRow() >= 0):
            row = self.currentRow()
            QTimer.singleShot(0, lambda: self._panel.delete(row))
            event.accept()
            return
        super().keyPressEvent(event)


class SheetPagesPanel(QWidget):
    """The «Sheets» page of the composer's side panel (see the module)."""

    #: The wait after the last change of a sheet before its picture is
    #: painted again: a drag or a run of keystrokes paints it once.
    DELAY_MS = 300

    def __init__(self, composer) -> None:
        super().__init__()
        self._composer = composer
        self._pixmaps: dict = {}        # id(sheet) → (QPixmap, its box)
        self._dirty: set = set()        # id(sheet) whose picture is old
        self._shape = None
        self._updating = False
        #: How many pictures this panel painted (the tests count them).
        self.painted = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.list = _PagesList(self)
        self.list.setItemDelegate(_PageDelegate(self))
        self.list.setToolTip(tr(
            "Every sheet as a page. Click: open it. Drag: change the order. "
            "Double-click or F2: rename. Delete: remove it. Right-click: "
            "more."))
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemChanged.connect(self._on_renamed)
        self.list.customContextMenuRequested.connect(self._on_menu)
        lay.addWidget(self.list, 1)
        #: The pictures still to paint come out one per pass of this one;
        #: a sheet that changed waits in ``_later`` for the other, which the
        #: next change starts over — the queue never waits on the canvas.
        self._later: set = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._paint_next)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(self.DELAY_MS)
        self._delay.timeout.connect(self._settled)
        self.sync()

    # ---- the list follows the document -----------------------------------------
    def _sheets(self) -> list:
        return list(self._composer._scene().compositions)

    def sync(self) -> None:
        """List the sheets again if their order or names changed, and mark
        the one open in the composer. Cheap when nothing did."""
        from shiboken6 import isValid
        if not isValid(self):
            return
        if self.list.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        sheets = self._sheets()
        shape = tuple((id(c), c.name, c.page_size_mm()) for c in sheets)
        self._updating = True
        try:
            if shape != self._shape:
                self._shape = shape
                live = {id(c) for c in sheets}
                for key in [k for k in self._pixmaps if k not in live]:
                    del self._pixmaps[key]
                self._dirty &= live
                self._later &= live
                self.list.clear()
                for c in sheets:
                    item = QListWidgetItem(c.name)
                    item.setFlags(item.flags() | Qt.ItemIsEditable
                                  | Qt.ItemIsDragEnabled)
                    item.setData(_SHEET_ROLE, id(c))
                    item.setData(_BOX_ROLE, thumb_box(c))
                    self.list.addItem(item)
                    held = self._pixmaps.get(id(c))
                    if held is None or held[1] != thumb_box(c):
                        self._dirty.add(id(c))   # new, or its paper changed
                if self._dirty:
                    self._schedule(0)
            cur = self._composer.comp
            row = next((i for i, c in enumerate(sheets) if c is cur), -1)
            if self.list.currentRow() != row:
                self.list.setCurrentRow(row)
        finally:
            self._updating = False

    def touch(self, sheet=None) -> None:
        """``sheet`` (all of them when ``None``) changed: its picture is
        painted again ``DELAY_MS`` after the last call."""
        if sheet is None:
            self._later.update(id(c) for c in self._sheets())
        else:
            self._later.add(id(sheet))
        self._delay.start()

    def _settled(self) -> None:
        self._dirty |= self._later
        self._later.clear()
        self._schedule(0)

    def _schedule(self, _ms: int = 0) -> None:
        if not self.isVisible():
            return                      # painted when the panel shows
        self._timer.start()

    def showEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().showEvent(ev)
        self.sync()
        if self._dirty:
            self._timer.start()

    # ---- pictures ---------------------------------------------------------------
    def pixmap_for(self, key):
        held = self._pixmaps.get(key)
        return held[0] if held is not None else None

    def _paint_next(self) -> None:
        """One picture per pass, the open sheet first; the next in the
        following pass, so the window never waits on the whole set."""
        from shiboken6 import isValid
        if not isValid(self) or not self._dirty or not self.isVisible():
            return
        sheets = self._sheets()
        by_id = {id(c): c for c in sheets}
        self._dirty &= set(by_id)
        if not self._dirty:
            return
        cur = self._composer.comp
        key = id(cur) if id(cur) in self._dirty else next(
            id(c) for c in sheets if id(c) in self._dirty)
        self._dirty.discard(key)
        comp = by_id[key]
        box = thumb_box(comp)
        dpr = self.devicePixelRatioF() or 1.0
        image = self._composer.sheet_thumbnail(
            comp, round(box.width() * dpr), round(box.height() * dpr))
        if image is not None:
            pm = QPixmap.fromImage(image)
            pm.setDevicePixelRatio(dpr)
            self._pixmaps[key] = (pm, box)
            self.painted += 1
            for i in range(self.list.count()):
                item = self.list.item(i)
                if item.data(_SHEET_ROLE) == key:
                    if item.data(_BOX_ROLE) != box:      # its paper changed
                        self._updating = True
                        try:
                            item.setData(_BOX_ROLE, box)
                        finally:
                            self._updating = False
                        self.list.doItemsLayout()
                    self.list.update(self.list.indexFromItem(item))
                    break
        if self._dirty:
            self._timer.start()

    # ---- what the user does here, forwarded to the composer --------------------
    def _on_row(self, row: int) -> None:
        if self._updating or row < 0:
            return
        # After the press: the composer rebuilds this list on a new sheet.
        QTimer.singleShot(0, lambda: self._composer.show_sheet(row))

    def _on_renamed(self, item) -> None:
        if self._updating:
            return
        row = self.list.row(item)
        name = item.text().strip()
        sheets = self._sheets()
        if 0 <= row < len(sheets) and name and name != sheets[row].name:
            # Not under the editor's own signal: the rename lists again.
            QTimer.singleShot(0, lambda: self._composer.rename_sheet(row,
                                                                     name))
        else:
            self._shape = None          # back to the name it had
            QTimer.singleShot(0, self.sync)

    def _on_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        self._composer.sheet_tab_menu(self.list.row(item),
                                      self.list.viewport().mapToGlobal(pos),
                                      self)

    def move(self, src: int, dst: int) -> None:
        """Sheet ``src`` to place ``dst`` — what a drop here does."""
        self._composer.move_sheet(src, dst)

    def rename(self, row: int, name: str) -> None:
        """What finishing an in-place rename does (the tests call it)."""
        item = self.list.item(row)
        if item is not None:
            item.setText(name)          # → _on_renamed

    def delete(self, row: int) -> None:
        """The Delete key: the composer asks first and keeps one sheet."""
        self._composer.delete_sheet(row, self)


def paint_thumbnail(paint_sheet, comp, w_px: int, h_px: int) -> QImage:
    """``comp`` drawn by ``paint_sheet(painter, comp)`` (mm space) on a
    white ``w_px``×``h_px`` picture."""
    image = QImage(max(1, int(w_px)), max(1, int(h_px)),
                   QImage.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255))
    pw, ph = comp.page_size_mm()
    painter = QPainter(image)
    try:
        painter.setRenderHints(QPainter.Antialiasing
                               | QPainter.SmoothPixmapTransform
                               | QPainter.TextAntialiasing)
        painter.scale(image.width() / max(pw, 1e-6),
                      image.height() / max(ph, 1e-6))
        paint_sheet(painter, comp)
    finally:
        painter.end()
    return image
