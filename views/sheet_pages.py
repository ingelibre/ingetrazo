# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheets' page pictures, and a sheet moved to another place in the set.

Marco, 19-11: «que se muestren en miniatura, como si fuera cada pagina como
tienen algunos programas de pdf». The pictures show in the sheet explorer
of the composer's Sheets page (:class:`views.sheet_browser.SheetExplorer`,
PR #932), in its Thumbnails mode: one panel lists, orders, files, prints,
renames and deletes the sheets, and shows them as pages — not two panels
for one job (merged 19-11; this module held its own «Sheets» panel until
then).

The pictures are the sheet painted from what the composer already holds —
each frame's cached render or hidden-line drawing, exactly what the export
prints — and never a new render: on a big model one frame costs seconds,
and fifteen pages would freeze the window to show stamps. A frame never
rendered this session shows the canvas's own «Update the view»
placeholder. Each picture is cached per sheet and painted again only when
that sheet changed, 300 ms after the last change (an edit, a render that
landed, a reorder that renumbered it), one per pass of the event loop, and
only while the explorer is on screen.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from core.composition import ComposerCommand


class SheetOrderCommand(ComposerCommand):
    """A sheet to another place in the set — a tab dragged along the strip
    — as one step of the composer's undo. ``after(old, new)`` lets the
    composer catch up (strips, explorer, sheet numbers) after do and undo.

    The sheet order follows the sheet explorer's tree (PR #932): in a
    document with folders the sheet joins the folder of the sheet it is
    dropped next to, so the strip and the tree never disagree (a plain
    reorder would be sorted back to the tree at once). Undone by putting
    the whole tree back (``sheet_folders.capture`` / ``restore``)."""

    def __init__(self, scene, sheet, index: int, after=None) -> None:
        self.scene = scene
        self.sheet = sheet
        self._after = after
        self._from = scene.compositions.index(sheet)
        self._to = max(0, min(int(index), len(scene.compositions) - 1))
        self._before = None
        self._done = None

    def _move(self) -> None:
        from core import sheet_folders as sf
        comps = self.scene.compositions
        if not sf.folders_of(self.scene):
            comps.remove(self.sheet)
            comps.insert(self._to, self.sheet)
            return
        order = [c for c in comps if c is not self.sheet]
        order.insert(self._to, self.sheet)
        at = order.index(self.sheet)
        prev = order[at - 1] if at > 0 else None
        nxt = order[at + 1] if at + 1 < len(order) else None
        folder = (prev.folder_id if prev is not None
                  else nxt.folder_id if nxt is not None else None)
        before = nxt if (nxt is not None
                         and nxt.folder_id == folder) else None
        sf.move_items(self.scene, [self.sheet], [], folder, before)
        sf.sync_order(self.scene)

    def do(self) -> None:
        from core import sheet_folders as sf
        if self._done is not None:
            sf.restore(self.scene, self._done)
        else:
            self._before = sf.capture(self.scene)
            self._move()
            self._done = sf.capture(self.scene)
        self.scene.version += 1
        if self._after is not None:
            self._after(self._from, self.scene.compositions.index(self.sheet))

    def undo(self) -> None:
        from core import sheet_folders as sf
        now = self.scene.compositions.index(self.sheet)
        sf.restore(self.scene, self._before)
        self.scene.version += 1
        if self._after is not None:
            self._after(now, self.scene.compositions.index(self.sheet))


#: The box a page's picture fits in, in logical pixels: a landscape sheet is
#: this wide, a portrait one this tall. A row of the sheet explorer, its
#: name beside it: smaller than the 150 of the old page list.
THUMB_PX = 110


def thumb_box(comp) -> QSize:
    """The picture's size for ``comp``, in proportion to its paper."""
    pw, ph = comp.page_size_mm()
    if pw <= 0 or ph <= 0:
        return QSize(THUMB_PX, THUMB_PX)
    if pw >= ph:
        return QSize(THUMB_PX, max(1, round(THUMB_PX * ph / pw)))
    return QSize(max(1, round(THUMB_PX * pw / ph)), THUMB_PX)


class SheetPictures(QObject):
    """The page pictures of a composer's sheets, painted on demand and
    kept: ``touch(sheet)`` marks one old, ``wanted(sheets)`` names the ones
    on show; ``on_painted(sheet_id)`` is called as each one lands. Painting
    waits while ``visible()`` is false."""

    #: The wait after the last change of a sheet before its picture is
    #: painted again: a drag or a run of keystrokes paints it once.
    DELAY_MS = 300

    def __init__(self, composer, on_painted, visible, parent=None,
                 box=None) -> None:
        super().__init__(parent)
        self._composer = composer
        self._on_painted = on_painted
        self._visible = visible
        self._box = box or thumb_box
        self._pixmaps: dict = {}        # id(sheet) → (QPixmap, its box)
        self._dirty: set = set()        # id(sheet) whose picture is old
        self._later: set = set()        # changed, waiting for DELAY_MS
        self._wanted: list = []
        #: How many pictures were painted (the tests count them).
        self.painted = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._paint_next)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(self.DELAY_MS)
        self._delay.timeout.connect(self._settled)

    def wanted(self, sheets) -> None:
        """The sheets on show, in order: those without a picture (or whose
        paper changed) are painted, the open one first."""
        self._wanted = list(sheets)
        live = {id(c) for c in self._wanted}
        for key in [k for k in self._pixmaps if k not in live]:
            del self._pixmaps[key]
        self._dirty &= live
        self._later &= live
        for c in self._wanted:
            held = self._pixmaps.get(id(c))
            if held is None or held[1] != self._box(c):
                self._dirty.add(id(c))
        self.kick()

    def pixmap_for(self, key):
        held = self._pixmaps.get(key)
        return held[0] if held is not None else None

    def touch(self, sheet=None) -> None:
        """``sheet`` (all of them when ``None``) changed: its picture is
        painted again ``DELAY_MS`` after the last call."""
        if sheet is None:
            self._later.update(id(c) for c in self._wanted)
        else:
            self._later.add(id(sheet))
        self._delay.start()

    def _settled(self) -> None:
        self._dirty |= self._later & {id(c) for c in self._wanted}
        self._later.clear()
        self.kick()

    def kick(self) -> None:
        if self._dirty and self._visible():
            self._timer.start()

    def _paint_next(self) -> None:
        """One picture per pass, the open sheet first; the next in the
        following pass, so the window never waits on the whole set."""
        from shiboken6 import isValid
        if not isValid(self) or not self._dirty or not self._visible():
            return
        by_id = {id(c): c for c in self._wanted}
        self._dirty &= set(by_id)
        if not self._dirty:
            return
        cur = getattr(self._composer, "comp", None)
        key = id(cur) if id(cur) in self._dirty else next(
            id(c) for c in self._wanted if id(c) in self._dirty)
        self._dirty.discard(key)
        comp = by_id[key]
        box = self._box(comp)
        from PySide6.QtWidgets import QApplication
        dpr = QApplication.instance().devicePixelRatio() or 1.0
        image = self._composer.sheet_thumbnail(
            comp, round(box.width() * dpr), round(box.height() * dpr))
        if image is not None:
            pm = QPixmap.fromImage(image)
            pm.setDevicePixelRatio(dpr)
            self._pixmaps[key] = (pm, box)
            self.painted += 1
            self._on_painted(key)
        if self._dirty:
            self._timer.start()


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
