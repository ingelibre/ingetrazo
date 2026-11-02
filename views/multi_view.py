# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Several views of the model at once: one, two (side by side, or one
wider), three, or four — Top, Perspective, Front and Right.

The views button offers the layouts as small drawings of their panes
(:class:`LayoutPicker`), as a desktop offers to tile its windows.

Each project tab has its own grid (``MainWindow._view_grid_of``), made
the first time that project asks for more than one view: the project's
viewport moves into it once — into the slot of the tab, the way an
extension puts its own widget there (``Document.stand_in``) — and stays;
going back to one view only hides the other cells. The window's viewport
is the Perspective view; the three others are made with the grid and
only hidden afterwards. A project opens in its one 3D view, and each tab
keeps its layout, the view filling the area and the extra views' cameras.

The extra views draw the same document with the same undo history: what
is drawn, selected or undone in one shows in the four. Each picks up the
window's tool when the mouse comes in, and its readouts (typed value,
measurement, coordinates) and document changes reach the window through
the main viewport's signals, as if it had happened there. Each cell has a
small title that opens a menu of the standard views; a double-click on it
fills the work area with that view and another brings the four back.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QMenu, QSizePolicy,
                               QSplitter, QToolButton, QVBoxLayout, QWidget)

from core.i18n import tr

#: (key, label) of the standard views a cell can show.
VIEWS = (
    ("top", "Top"), ("front", "Front"), ("right", "Right"),
    ("back", "Back"), ("left", "Left"), ("bottom", "Bottom"),
    ("iso", "Isometric"), ("perspective", "Perspective"),
)

#: The view each cell starts in, by cell (row-major).
DEFAULTS = ("top", "perspective", "front", "right")


_CAMERA_FIELDS = ("distance", "yaw", "pitch", "fov_deg", "perspective",
                  "two_point")


def _camera_state(cam) -> dict:
    t = cam.target
    out = {"target": (t.x(), t.y(), t.z())}
    for k in _CAMERA_FIELDS:
        out[k] = getattr(cam, k)
    return out


def _apply_camera_state(cam, state: dict) -> None:
    from PySide6.QtGui import QVector3D
    cam.target = QVector3D(*state["target"])
    for k in _CAMERA_FIELDS:
        if k in state:
            setattr(cam, k, state[k])


#: The view's name as a small label over its top-left corner (not a strip
#: above it): dark and translucent, in the accent colour for the view
#: being worked in.
_CHIP = """
QToolButton#viewChip {{
    background: rgba(32, 36, 42, 0.62); color: white;
    border: 0px; border-radius: 3px; padding: 1px 16px 1px 6px;
    font-weight: 600;
}}
QToolButton#viewChip::menu-indicator {{
    subcontrol-origin: padding; subcontrol-position: right center;
    right: 4px;
}}
QToolButton#viewChip:hover {{ background: rgba(32, 36, 42, 0.82); }}
QToolButton#viewChip[active="true"] {{ background: rgb({accent_rgb}); }}
"""


class _CellHeader(QToolButton):
    """The cell's title, a small label over the view's corner: a click
    opens the views, a double-click fills the work area with the cell (and
    back)."""

    #: Distance (px) from the view's top-left corner.
    MARGIN = 4

    def __init__(self, cell) -> None:
        super().__init__(cell)
        self._cell = cell
        self.setObjectName("viewChip")
        self.setProperty("active", False)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setCursor(Qt.PointingHandCursor)
        from views.theme import style
        style(self, _CHIP)
        self.setToolTip(tr("Click: change the view · Double-click: "
                           "this view alone, or the four again"))
        # Filled as it opens: the window's own view actions (Camera menu,
        # Views bar) stay the only ones with those names, for the shortcut
        # editor and the command search.
        menu = QMenu(self)
        menu.aboutToShow.connect(self._fill)
        self.setMenu(menu)

    def _fill(self) -> None:
        menu = self.menu()
        if menu.actions():
            return
        for key, label in VIEWS:
            act = menu.addAction(tr(label))
            act.triggered.connect(
                lambda _c=False, k=key: self._cell.pick_view(k))

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802 — Qt override
        self._cell.grid.toggle_maximized(self._cell)
        ev.accept()

    def set_active(self, on: bool) -> None:
        if bool(self.property("active")) == bool(on):
            return
        self.setProperty("active", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)


class ViewCell(QWidget):
    """A view of the four: the viewport filling it and its name as a small
    label over the corner."""

    def __init__(self, grid, index: int, viewport=None) -> None:
        super().__init__()
        self.grid = grid
        self.index = index
        self.view = DEFAULTS[index]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # Not in the layout: it floats over the viewport's corner.
        self.header = _CellHeader(self)
        self.header.setVisible(False)
        self.viewport = None
        if viewport is not None:
            self.set_viewport(viewport)

    def set_viewport(self, vp) -> None:
        self.viewport = vp
        vp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.layout().addWidget(vp, 1)
        # Taken out of the window's stack of projects it comes in hidden
        # (the stack hides what it lets go): shown with its cell.
        vp.show()
        vp.installEventFilter(self)
        self._label()
        self.header.raise_()

    def _label(self) -> None:
        self.header.setText(tr(dict(VIEWS).get(self.view, self.view)))
        self._place_header()

    def _place_header(self) -> None:
        h = self.header
        h.adjustSize()
        h.move(h.MARGIN, h.MARGIN)
        h.raise_()

    def resizeEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(ev)
        self._place_header()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 — Qt override
        # The view clicked or given the keyboard is the one worked in.
        if obj is self.viewport and ev.type() in (QEvent.MouseButtonPress,
                                                  QEvent.FocusIn):
            self.grid.set_active_cell(self)
        return False

    def pick_view(self, key: str) -> None:
        """The user's own pick for this cell: layouts leave it alone."""
        self.picked = True
        self.show_view(key)

    def show_view(self, key: str) -> None:
        self.view = key
        self._label()
        vp = self.viewport
        if vp is None:
            return
        cam = vp.camera
        if key == "perspective":
            cam.perspective = True
            cam.set_view("iso")
        else:
            cam.perspective = key == "iso"
            cam.set_view(key)
        vp.update()


class _FollowWindow(QObject):
    """On an extra view: the window's tool and navigation mode come along
    as the mouse or a key arrives."""

    def __init__(self, grid) -> None:
        super().__init__(grid)
        self._grid = grid

    _EVENTS = frozenset((QEvent.Enter, QEvent.MouseButtonPress,
                         QEvent.MouseMove, QEvent.KeyPress, QEvent.Wheel))

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 — Qt override
        if ev.type() in self._EVENTS:
            main = self._grid.main
            if obj.active_tool is not main.active_tool:
                obj.active_tool = main.active_tool
            if obj.nav_mode != main.nav_mode:
                obj.nav_mode = main.nav_mode
        return False


#: The layouts the views button offers: key, label, and the cells shown,
#: column by column (cell 1 is the window's own viewport, Perspective).
#: The columns' widths are relative.
#: In the picker's order: one view always first, then the rest from the
#: most used to the least.
LAYOUTS = (
    ("single", "One view", ((1,),), (1,)),
    ("four", "Four views", ((0, 2), (1, 3)), (1, 1)),
    ("two", "Two views", ((0,), (1,)), (1, 1)),
    ("three", "Three views", ((1,), (0, 2)), (1, 1)),
    ("two_stacked", "Two views, one above the other", ((1, 3),), (1,)),
    ("three_mirror", "Three views, the large one on the right",
     ((0, 2), (1,)), (1, 1)),
    ("two_wide", "Two views, one wider", ((1,), (0,)), (2, 1)),
)

#: The view a cell takes in a layout, while the user has not picked one
#: for it: one above the other, the plan goes under the 3D view.
LAYOUT_VIEWS = {"two_stacked": {3: "top"}}
LAYOUT_KEYS = tuple(k for k, *_ in LAYOUTS)


class _LayoutButton(QToolButton):
    """One layout in the picker: its views drawn as panes."""

    #: Where each layout's panes sit, in a 0–1 square (x, y, w, h).
    PANES = {
        "single": ((0, 0, 1, 1),),
        "two": ((0, 0, .5, 1), (.5, 0, .5, 1)),
        "two_wide": ((0, 0, .64, 1), (.64, 0, .36, 1)),
        "two_stacked": ((0, 0, 1, .5), (0, .5, 1, .5)),
        "three": ((0, 0, .5, 1), (.5, 0, .5, .5), (.5, .5, .5, .5)),
        "three_mirror": ((0, 0, .5, .5), (0, .5, .5, .5), (.5, 0, .5, 1)),
        "four": ((0, 0, .5, .5), (.5, 0, .5, .5), (0, .5, .5, .5),
                 (.5, .5, .5, .5)),
    }

    def __init__(self, key: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setToolTip(tr(label))
        self.setAccessibleName(tr(label))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(QSize(76, 56))

    def paintEvent(self, _ev) -> None:  # noqa: N802 — Qt override
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPen
        from views.theme import accent_color
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        ink = QColor(pal.color(pal.ColorRole.WindowText))
        accent = accent_color()
        hot = self.underMouse() or self.hasFocus()
        if self.isChecked() or hot:
            back = QColor(accent)
            back.setAlpha(60 if self.isChecked() else 30)
            p.setPen(Qt.NoPen)
            p.setBrush(back)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        box = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        gap = 3.0
        fill = QColor(ink)
        fill.setAlpha(40)
        edge = QColor(accent if self.isChecked() else ink)
        edge.setAlpha(255 if self.isChecked() else 140)
        p.setPen(QPen(edge, 1.2))
        p.setBrush(fill)
        for x, y, w, h in self.PANES[self.key]:
            r = QRectF(box.x() + x * box.width(), box.y() + y * box.height(),
                       w * box.width(), h * box.height())
            p.drawRoundedRect(r.adjusted(gap / 2, gap / 2, -gap / 2, -gap / 2),
                              3, 3)
        p.end()


class LayoutPicker(QFrame):
    """The views button's popup: one, two, three or four views, drawn as
    panes; a click picks one for the active document."""

    chosen = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.Popup)
        self.setObjectName("layoutPicker")
        self.setFrameShape(QFrame.StyledPanel)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.buttons = {}
        for key, label, _cols, _w in LAYOUTS:
            b = _LayoutButton(key, label, self)
            b.clicked.connect(lambda _c=False, k=key: self._pick(k))
            lay.addWidget(b)
            self.buttons[key] = b

    def show_for(self, current: str, anchor) -> None:
        """Pop up under ``anchor`` with ``current`` marked."""
        for key, b in self.buttons.items():
            b.setChecked(key == current)
        self.adjustSize()
        from PySide6.QtCore import QPoint
        self.move(anchor.mapToGlobal(QPoint(0, anchor.height() + 2)))
        self.show()
        self.buttons[current].setFocus()

    def _pick(self, key: str) -> None:
        self.hide()
        self.chosen.emit(key)


class ViewGrid(QWidget):
    """The work area's views: the window's viewport alone, or two, three or
    four views side by side (:data:`LAYOUTS`).

    Built as two columns — cells 0 and 2 in one, 1 and 3 in the other —
    that only change order and visibility: no cell changes parent after
    the grid is made, so no viewport loses its OpenGL context again."""

    def __init__(self, main_viewport, parent=None) -> None:
        super().__init__(parent)
        self.main = main_viewport
        self._main_min = main_viewport.minimumSize()
        self._layout = "single"
        self._maximized = None
        self._follow = _FollowWindow(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.columns = QSplitter(Qt.Horizontal)
        self.columns.setChildrenCollapsible(False)
        lay.addWidget(self.columns)
        self.cells = [ViewCell(self, i, main_viewport if i == 1 else None)
                      for i in range(4)]
        # Column A holds cells 0 and 2, column B cells 1 and 3.
        self.col_a = QSplitter(Qt.Vertical)
        self.col_b = QSplitter(Qt.Vertical)
        for col, cells in ((self.col_a, (0, 2)), (self.col_b, (1, 3))):
            col.setChildrenCollapsible(False)
            for i in cells:
                col.addWidget(self.cells[i])
            self.columns.addWidget(col)
        # With four views the two columns share their row line, as one
        # cross.
        self.col_a.splitterMoved.connect(
            lambda *_: self._sync_rows(self.col_a, self.col_b))
        self.col_b.splitterMoved.connect(
            lambda *_: self._sync_rows(self.col_b, self.col_a))
        main_viewport.sceneVersionChanged.connect(self._repaint_extras)
        self._apply()

    def _sync_rows(self, src, dst) -> None:
        if self._layout == "four":
            dst.setSizes(src.sizes())

    # ---- state ---------------------------------------------------------------
    def layout_key(self) -> str:
        return self._layout

    def is_enabled(self) -> bool:
        """More than the one view."""
        return self._layout != "single"

    def extras(self) -> list:
        """The three extra viewports made so far (none before the first
        time more than one view is shown)."""
        return [c.viewport for c in self.cells
                if c.viewport is not None and c.viewport is not self.main]

    def visible_extras(self) -> list:
        return [c.viewport for c in self.cells
                if c.viewport is not None and c.viewport is not self.main
                and not c.isHidden()]

    def set_layout(self, key: str) -> None:
        """Show the views as :data:`LAYOUTS` ``key`` says."""
        if key not in LAYOUT_KEYS:
            key = "single"
        if key == self._layout:
            return
        self._layout = key
        self._maximized = None
        if key != "single" and not self.extras():
            self._make_extras()
        if key != "single":
            self.follow_document()
        self._apply()

    def set_enabled(self, on: bool) -> None:
        """Four views, or the one."""
        self.set_layout("four" if on else "single")

    def set_active_cell(self, cell) -> None:
        """The view being worked in: its label in the accent colour."""
        for c in self.cells:
            c.header.set_active(c is cell)

    def active_cell(self):
        return next((c for c in self.cells
                     if c.header.property("active")), None)

    def toggle_maximized(self, cell) -> None:
        if not self.is_enabled():
            return
        self._maximized = None if self._maximized is cell else cell
        self._apply()

    def _apply(self) -> None:
        on = self.is_enabled()
        if on:
            self.main.setMinimumSize(80, 60)
        else:
            self.main.setMinimumSize(self._main_min)
        spec = next(l for l in LAYOUTS if l[0] == self._layout)
        columns, widths = spec[2], spec[3]
        # The views a layout suggests, in the cells the user left alone.
        suggested = LAYOUT_VIEWS.get(self._layout, {})
        for cell in self.cells:
            if getattr(cell, "picked", False) or cell.viewport is None:
                continue
            want = suggested.get(cell.index, DEFAULTS[cell.index])
            if cell.view != want:
                cell.show_view(want)
        shown = {i for col in columns for i in col}
        if self._maximized is not None:
            shown = {self._maximized.index}
        for cell in self.cells:
            cell.header.setVisible(on)
            cell.setVisible(cell.index in shown)
        # Column order: the one holding the layout's first column first.
        first = self.col_b if 1 in columns[0] else self.col_a
        if self.columns.indexOf(first) != 0:
            self.columns.insertWidget(0, first)
        self.col_a.setVisible(bool(shown & {0, 2}))
        self.col_b.setVisible(bool(shown & {1, 3}))
        if on and self._maximized is None:
            total = max(1, self.width())
            parts = [total * w // sum(widths) for w in widths]
            if len(parts) == 2:
                self.columns.setSizes(parts)
            half = max(1, self.height() // 2)
            for col in (self.col_a, self.col_b):
                col.setSizes([half, half])
        # The sidebar's handle sits on the views' edge: placed again once
        # the cells are laid out.
        place = getattr(self.window(), "_place_sidebar_handle", None)
        if place is not None:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self, place)

    # ---- the extra viewports -------------------------------------------------
    def _make_extras(self) -> None:
        from views.viewport import Viewport
        main = self.main
        for cell in self.cells:
            if cell.viewport is not None:
                continue
            vp = Viewport(cell)
            vp.setMinimumSize(80, 60)
            vp.set_document(main.scene, main.history)
            cam = vp.camera
            cam.target = type(main.camera.target)(main.camera.target)
            cam.distance = max(main.camera.distance, 15.0)
            cell.set_viewport(vp)
            cell.show_view(cell.view)
            vp.installEventFilter(self._follow)
            # Whatever happens in an extra view reaches the window as if
            # it had happened in the main one.
            vp.sceneVersionChanged.connect(main.sceneVersionChanged.emit)
            vp.sceneVersionChanged.connect(
                lambda _v, src=vp: self._repaint_others(src))
            vp.valueBufferChanged.connect(main.valueBufferChanged.emit)
            vp.measurementChanged.connect(main.measurementChanged.emit)
            vp.coordinateChanged.connect(main.coordinateChanged.emit)
        # Making a viewport binds the units to its own empty document.
        from core import units
        units.bind_scene(main.scene)

    def follow_document(self) -> None:
        """The window's viewport has another document (a tab, New, Open):
        the extra views show it too."""
        main = self.main
        for vp in self.extras():
            if vp.scene is not main.scene or vp.history is not main.history:
                vp.set_document(main.scene, main.history)
            else:
                vp.reset_document_caches()
                vp._edges_version = -1
                vp.last_snap = None
            vp.update()
        from core import units
        units.bind_scene(main.scene)

    # ---- per project -------------------------------------------------------
    def layout_of_project(self) -> dict:
        """The active project's views, kept with it while it waits in its
        tab: one view or four, the one filling the area, each extra view's
        view and camera."""
        return {"layout": self._layout, "multi": self.is_enabled(),
                "maximized": self.maximized_index(), "views": self.state()}

    def maximized_index(self):
        return None if self._maximized is None else self._maximized.index

    def set_maximized_index(self, index) -> None:
        cell = (self.cells[index]
                if index is not None and self.is_enabled() else None)
        if cell is not self._maximized:
            self._maximized = cell
            self._apply()

    def state(self):
        """What each extra view shows — its view key and camera — for the
        project going to the back (None before the views exist)."""
        if not self.extras():
            return None
        return [(c.view, _camera_state(c.viewport.camera))
                for c in self.cells if c.viewport is not self.main]

    def restore(self, state) -> None:
        """Put back :meth:`state`; None: each view starts over from its
        default, looking where the main view looks."""
        cells = [c for c in self.cells if c.viewport is not self.main]
        if not self.extras():
            return
        if not state:
            main = self.main.camera
            for cell in cells:
                cell.view = DEFAULTS[cell.index]
                cam = cell.viewport.camera
                cam.target = type(main.target)(main.target)
                cam.distance = max(main.distance, 15.0)
                cell.show_view(cell.view)
            return
        for cell, (view, cam) in zip(cells, state):
            cell.view = view
            cell._label()
            _apply_camera_state(cell.viewport.camera, cam)
            cell.viewport.update()

    def fit_box(self, lo, hi) -> None:
        """Zoom Extents: every extra view shown frames the same box."""
        for vp in self.visible_extras():
            vp.camera.fit_box(lo, hi)
            vp.update()

    def _repaint_extras(self, *_a) -> None:
        for vp in self.visible_extras():
            vp.update()

    def _repaint_others(self, source) -> None:
        if self.main is not source:
            self.main.update()
        for vp in self.visible_extras():
            if vp is not source:
                vp.update()
