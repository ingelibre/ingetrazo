# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheets' page pictures, and sheets added, copied, deleted, renamed or
moved to another place in the set.

Marco, 19-11: «que se muestren en miniatura, como si fuera cada pagina como
tienen algunos programas de pdf»; 20-11: «láminas deberían ser parecido a
las vistas de miniatura de ciertos programas conocidos de pdf, de allí
podría mover el orden, copiar, pegar, eliminar». The pictures are the
Pages view of the composer's Sheets tab
(:class:`views.sheet_browser.SheetExplorer`): a column of pages, nothing
else — the folders and the Print switch live in its List view.

The pictures are the sheet painted from what the composer already holds —
each frame's cached render or hidden-line drawing, exactly what the export
prints. A frame never rendered this session is not waited for: the page
shows at once with what there is, and a SMALL render of that frame, made
for the picture alone (:meth:`ComposerWindow.thumbnail_render`), fills it
in afterwards — one frame at a time, the pages on screen first, never
while a mouse button is down. (Before 20-11 such a frame stayed «Update
the view» until its sheet was opened: on the final plaza 40 of 41 frames,
so fourteen of fifteen pages looked unfinished.) Each picture is cached
per sheet and painted again only when that sheet changed, 300 ms after
the last change (an edit, a render that landed, a reorder that renumbered
it), one per pass of the event loop, and only while the pages are on
screen.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QSize, Qt, QTimer
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


class SheetSetCommand(ComposerCommand):
    """Sheets added, copied, deleted, renamed or moved — from the Sheets
    tab — as ONE step of the composer's undo, however many sheets it
    touches.

    ``change()`` makes the change the first time; after that the command
    swaps whole snapshots of the set: which sheets, in which order, their
    names, the folder tree (``sheet_folders.capture``), and which sheet the
    composer had open. ``after(cmd, opened)`` lets the composer catch up;
    ``opened`` is the sheet to show now (``None``: keep the one shown) —
    the one open before or after the step, but only when the user has not
    opened another one meanwhile."""

    def __init__(self, scene, change, composer=None, after=None) -> None:
        self.scene = scene
        self._change = change
        self._composer = composer
        self._after = after
        self._before = None
        self._done = None

    def _open(self):
        return getattr(self._composer, "comp", None)

    def _snap(self) -> tuple:
        from core import sheet_folders as sf
        comps = list(self.scene.compositions)
        return (comps, [c.name for c in comps], sf.capture(self.scene),
                self._open())

    def _put(self, snap) -> None:
        from core import sheet_folders as sf
        comps, names, tree, _open = snap
        self.scene.compositions[:] = comps
        for c, name in zip(comps, names):
            c.name = name
        sf.restore(self.scene, tree)

    def _opened(self, was, now):
        """What to show after going from snapshot ``was`` to ``now``."""
        shown = self._open()
        if shown is was[3] or shown not in self.scene.compositions:
            return now[3] if now[3] in self.scene.compositions else None
        return None

    def do(self) -> None:
        if self._done is None:
            self._before = self._snap()
            self._change()
            self._done = self._snap()
            opened = None
        else:
            self._put(self._done)
            opened = self._opened(self._before, self._done)
        if self._after is not None:
            self._after(self, opened)

    def undo(self) -> None:
        self._put(self._before)
        if self._after is not None:
            self._after(self, self._opened(self._done, self._before))

    @property
    def changed(self) -> bool:
        """Whether the step changed anything (a paste of nothing, a move
        to where the sheets already were: not worth an undo step)."""
        if self._before is None or self._done is None:
            return True
        b, d = self._before, self._done
        return ([id(c) for c in b[0]] != [id(c) for c in d[0]]
                or b[1] != d[1]
                or b[2]["sheet_state"] != d[2]["sheet_state"])


def place_block(scene, order: list, block: list) -> None:
    """Make ``order`` (every sheet, ``block`` among them side by side) the
    sheet order. In a document with folders the block joins the folder of
    the sheet before it (or after it, at the very top), as a tab dropped
    on the strip does (:class:`SheetOrderCommand`): the order follows the
    folder tree, and a plain reorder would be sorted back at once."""
    from core import sheet_folders as sf
    if not sf.folders_of(scene) or not block:
        scene.compositions[:] = order
        return
    moving = {id(c) for c in block}
    at = next(k for k, c in enumerate(order) if id(c) in moving)
    rest = [c for c in order if id(c) not in moving]
    prev = rest[at - 1] if at > 0 else None
    nxt = rest[at] if at < len(rest) else None
    folder = (prev.folder_id if prev is not None
              else nxt.folder_id if nxt is not None else None)
    before = nxt if (nxt is not None and nxt.folder_id == folder) else None
    # New sheets must be in the list before the tree can place them.
    for c in block:
        if c not in scene.compositions:
            scene.compositions.append(c)
    sf.move_items(scene, block, [], folder, before)
    sf.sync_order(scene)


def moved_order(comps: list, sheets: list, gap: int) -> list:
    """``comps`` with ``sheets`` taken out and put back, in their order,
    at ``gap`` — a place between two sheets of ``comps`` (0: before the
    first, ``len(comps)``: after the last)."""
    moving = {id(c) for c in sheets}
    block = [c for c in comps if id(c) in moving]
    before = next((c for c in comps[max(0, gap):] if id(c) not in moving),
                  None)
    rest = [c for c in comps if id(c) not in moving]
    at = rest.index(before) if before is not None else len(rest)
    return rest[:at] + block + rest[at:]


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

    #: The wait between two small renders of frames a page still lacks
    #: (:meth:`_fill_next`): the window answers in between — a short one
    #: for the pages on screen, a longer one for the rest, so the window
    #: stays at ease while those fill in behind (a small render of a frame
    #: of the final plaza costs 0.05–0.27 s).
    FILL_MS = 40
    FILL_OFF_SCREEN_MS = 250

    def __init__(self, composer, on_painted, visible, parent=None,
                 box=None, first=None) -> None:
        super().__init__(parent)
        self._composer = composer
        self._on_painted = on_painted
        self._visible = visible
        self._box = box or thumb_box
        #: ``first()``: the sheets on screen now, painted before the rest.
        self._first = first or (lambda: [])
        self._pixmaps: dict = {}        # id(sheet) → (QPixmap, its box)
        self._dirty: set = set()        # id(sheet) whose picture is old
        self._later: set = set()        # changed, waiting for DELAY_MS
        self._wanted: list = []
        #: How many pictures were painted, and of which sheets in turn (the
        #: tests count them).
        self.painted = 0
        self.painted_keys: list = []
        #: How many small renders filled frames in.
        self.filled = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._paint_next)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(self.DELAY_MS)
        self._delay.timeout.connect(self._settled)
        self._fill = QTimer(self)
        self._fill.setSingleShot(True)
        self._fill.setInterval(self.FILL_MS)
        self._fill.timeout.connect(self._fill_next)

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
        if not self._visible():
            return
        if self._dirty:
            self._timer.start()
        elif not self._fill.isActive():
            self._fill.start(self.FILL_MS)

    #: After a model change, the wait before the pages' small renders are
    #: made again: a run of edits renders them once.
    SETTLE_MS = 1500

    def kick_later(self) -> None:
        """The model changed: the small renders are made again once it has
        been still for :data:`SETTLE_MS`."""
        self._fill.start(self.SETTLE_MS)

    def busy(self) -> bool:
        """Whether a picture is still to be painted or a frame filled in."""
        return bool(self._dirty or self._later) or self._next_missing() \
            is not None

    def _ordered(self) -> list:
        """The sheets on show, those on screen first (the open one first
        of all, when it is on screen)."""
        on_screen = [c for c in self._first() if c in self._wanted]
        cur = getattr(self._composer, "comp", None)
        if cur in on_screen:
            on_screen.remove(cur)
            on_screen.insert(0, cur)
        seen = {id(c) for c in on_screen}
        return on_screen + [c for c in self._wanted if id(c) not in seen]

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
        key = next(id(c) for c in self._ordered() if id(c) in self._dirty)
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
            self.painted_keys.append(key)
            self._on_painted(key)
        if self._dirty:
            self._timer.start()
        elif not self._fill.isActive():
            self._fill.start(self._fill_wait())

    def _fill_wait(self) -> int:
        nxt = self._next_missing()
        on_screen = {id(c) for c in self._first()}
        return (self.FILL_MS if nxt is not None and id(nxt[0]) in on_screen
                else self.FILL_OFF_SCREEN_MS)

    # ---- frames a page still lacks -------------------------------------------
    def _next_missing(self):
        """``(sheet, frame)``: the next frame with nothing to show yet, on
        the pages on screen first; ``None`` when every page is whole."""
        missing = getattr(self._composer, "thumbnail_missing", None)
        if missing is None:
            return None
        for c in self._ordered():
            frame = missing(c)
            if frame is not None:
                return c, frame
        return None

    def _fill_next(self) -> None:
        """One small render of a frame a page lacks, then its page painted
        again; the next one a moment later. Never while a mouse button is
        down (a drag, a click on its way), a dialog or a menu open: the
        render would stall it."""
        from shiboken6 import isValid
        from PySide6.QtWidgets import QApplication
        if not isValid(self) or not self._visible() or self._dirty:
            return
        if (QApplication.mouseButtons() != Qt.NoButton
                or QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None):
            self._fill.start(250)
            return
        nxt = self._next_missing()
        if nxt is None:
            return
        comp, frame = nxt
        self._composer.thumbnail_render(frame)
        self.filled += 1
        self._dirty.add(id(comp))
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
