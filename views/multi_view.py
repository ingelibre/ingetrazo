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
small title that opens a menu: first the entry that fills the work area with
that view and, then, brings the others back (Ctrl+Space does the same), and
after it the standard views.

A line between the views drags alone (with four views the two halves of the
cross part ways); near a crossing a square with arrows drags the lines meeting
there as one block. A guide shows where they will land, they stick to the middle
of the views (a line also to its other half), and Esc leaves them as they were.
"""
from __future__ import annotations

from PySide6.QtCore import (QEvent, QLine, QObject, QPoint, QPointF, QRectF,
                            QSettings, QSize, Qt, Signal)
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QMenu,
                               QSizePolicy, QSplitter, QSplitterHandle,
                               QToolButton, QVBoxLayout, QWidget)

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
    if hasattr(cam, "lens_dict"):
        out["lens"] = cam.lens_dict()
    return out


def _apply_camera_state(cam, state: dict) -> None:
    from PySide6.QtGui import QVector3D
    cam.target = QVector3D(*state["target"])
    for k in _CAMERA_FIELDS:
        if k in state:
            setattr(cam, k, state[k])
    if hasattr(cam, "apply_lens") and "lens" in state:
        cam.apply_lens(state["lens"])


#: The view's name as a small label over its top-left corner (not a strip
#: above it), covering as little of the view as it can: small, no arrow, dark
#: and faint until hovered, in the accent colour for the view being worked in.
_CHIP = """
QToolButton#viewChip {{
    background: rgba(32, 36, 42, 0.45); color: white;
    border: 0px; border-radius: 2px; padding: 0px 4px;
    font-size: 8pt;
}}
QToolButton#viewChip::menu-indicator {{ image: none; width: 0px; }}
QToolButton#viewChip:hover {{ background: rgba(32, 36, 42, 0.82); }}
QToolButton#viewChip[active="true"] {{ background: rgb({accent_rgb}); }}
"""


class _CellHeader(QToolButton):
    """The cell's title, a small label over the view's corner: a click opens
    its menu, to fill the work area with the cell (and back) or change its
    view."""

    #: Distance (px) from the view's top-left corner.
    MARGIN = 2

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
        self.setToolTip(tr("Maximize this view or change it"))
        # Filled as it opens: the window's own view actions (Camera menu,
        # Views bar) stay the only ones with those names, for the shortcut
        # editor and the command search.
        menu = QMenu(self)
        menu.aboutToShow.connect(self._fill)
        self.setMenu(menu)

    def sizeHint(self):  # noqa: N802 — Qt override
        """As wide as its name: Qt keeps room for the arrow it no longer has."""
        self.ensurePolished()
        hint = super().sizeHint()
        hint.setWidth(self.fontMetrics().horizontalAdvance(self.text()) + 10)
        return hint

    def _fill(self) -> None:
        menu = self.menu()
        if not menu.actions():
            self._maximize_action = menu.addAction("")
            self._maximize_action.triggered.connect(
                lambda _c=False: self._cell.grid.toggle_maximized(self._cell))
            menu.addSeparator()
            for key, label in VIEWS:
                act = menu.addAction(tr(label))
                act.triggered.connect(
                    lambda _c=False, k=key: self._cell.pick_view(k))
        # The key only shown, after a tab, so that people learn it: the
        # window's action is the one that holds it.
        text = self._cell.maximize_label()
        act = getattr(self.window(), "_act_maximize_view", None)
        if act is not None and not act.shortcut().isEmpty():
            text += "\t" + act.shortcut().toString(QKeySequence.NativeText)
        self._maximize_action.setText(text)

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

    def maximize_label(self) -> str:
        return (tr("Restore") if self.grid.maximized_index() == self.index
                else tr("Maximize"))

    def resizeEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(ev)
        self._place_header()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802 — Qt override
        if obj is not self.viewport:
            return False
        kind = ev.type()
        if kind in (QEvent.Enter, QEvent.MouseMove, QEvent.MouseButtonPress):
            self.grid.set_tool_view(obj)
        # The view clicked or given the keyboard is the one worked in.
        if kind in (QEvent.MouseButtonPress, QEvent.FocusIn):
            self.grid.set_active_cell(self)
        elif kind == QEvent.MouseMove and ev.buttons() == Qt.NoButton:
            self.grid.pointer_moved(ev.globalPosition().toPoint())
        elif kind == QEvent.Leave:
            self.grid.pointer_moved(QCursor.pos())
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
            changed = False
            if obj.active_tool is not main.active_tool:
                obj.active_tool = main.active_tool
                changed = True
            if obj.nav_mode != main.nav_mode:
                obj.nav_mode = main.nav_mode
                changed = True
            # The pointer comes along too: the magnifier, the orbit or pan
            # hand, or the tool's icon — not the one the view had before.
            if changed:
                if obj.nav_mode is not None:
                    obj._apply_nav_cursor()
                else:
                    obj.unsetCursor()
                    obj._apply_tool_cursor()
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


#: How near (px) a dragged line sticks to the middle of the views or to its
#: other half.
DIVIDER_SNAP_PX = 16


def _divider_snap_px() -> int:
    """``views/divider_snap_px`` in the settings, or :data:`DIVIDER_SNAP_PX`."""
    try:
        return max(0, int(QSettings().value("views/divider_snap_px",
                                            DIVIDER_SNAP_PX)))
    except (TypeError, ValueError):
        return DIVIDER_SNAP_PX


def _stick(wanted: int, low: int, high: int, targets) -> tuple:
    """(where a line lands, whether it stuck) for a wished place, kept inside
    ``low``..``high``; the nearest of ``targets`` within the tolerance wins."""
    wanted = min(max(wanted, low), max(low, high))
    near = [t for t in targets if low <= t <= high
            and abs(wanted - t) <= _divider_snap_px()]
    if near:
        return min(near, key=lambda t: abs(wanted - t)), True
    return wanted, False


class _EscCancelsDrag(QObject):
    """On the application during a drag: Esc is the drag's, ahead of the
    window's filters and shortcuts."""

    def __init__(self, grid) -> None:
        super().__init__(grid)
        self._grid = grid

    def eventFilter(self, _obj, ev) -> bool:  # noqa: N802 — Qt override
        kind = ev.type()
        if (kind not in (QEvent.KeyPress, QEvent.KeyRelease,
                         QEvent.ShortcutOverride)
                or ev.key() != Qt.Key_Escape):
            return False
        if kind == QEvent.ShortcutOverride:
            ev.accept()
        elif kind == QEvent.KeyPress:
            self._grid.cancel_drag()
        return True


class _DividerGuide(QWidget):
    """Over the grid during a drag: where the lines will land, dashed while
    one is sticking."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()
        self.lines = []

    def show_lines(self, lines) -> None:
        """``lines``: (QLine in the grid's coordinates, sticking)."""
        self.lines = lines
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802 — Qt override
        from views.theme import accent_color
        p = QPainter(self)
        for line, snapped in self.lines:
            p.setPen(QPen(QColor(32, 36, 42, 150), 4))
            p.drawLine(line)
            pen = QPen(accent_color(), 2)
            if snapped:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawLine(line)
        p.end()


class _ViewSplitterHandle(QSplitterHandle):
    """A line between views: it drags alone. A guide shows where it will land,
    it sticks to the middle of the views and to its other half, Esc leaves it
    where it was, and only releasing the mouse moves it."""

    def __init__(self, orientation, splitter) -> None:
        super().__init__(orientation, splitter)
        self.setCursor(Qt.SizeHorCursor if orientation == Qt.Horizontal
                       else Qt.SizeVerCursor)
        self.setMouseTracking(True)         # the crossing's square, nearby
        self._drag_offset = None
        self._landing = None

    def _grid(self):
        return self.splitter().view_grid

    def along(self, point: QPoint) -> int:
        return (point.x() if self.orientation() == Qt.Horizontal
                else point.y())

    def thickness(self) -> int:
        return (self.width() if self.orientation() == Qt.Horizontal
                else self.height())

    def limits(self) -> tuple:
        """How far the line may go, keeping the two views beside it their
        least room."""
        s = self.splitter()
        i = s.indexOf(self)
        before, after = s.widget(i - 1), s.widget(i)
        horizontal = self.orientation() == Qt.Horizontal
        least = ((lambda w: max(w.minimumWidth(), w.minimumSizeHint().width()))
                 if horizontal else
                 (lambda w: max(w.minimumHeight(),
                                w.minimumSizeHint().height())))
        end = self.along(after.pos()) + (after.width() if horizontal
                                         else after.height())
        return (self.along(before.pos()) + least(before),
                end - least(after) - self.thickness())

    def middle(self) -> int:
        s = self.splitter()
        extent = (s.width() if self.orientation() == Qt.Horizontal
                  else s.height())
        return (extent - self.thickness()) // 2

    def other_half(self):
        """The line that continues this one in the column beside, if both
        columns show two views."""
        grid = self._grid()
        s = self.splitter()
        if s not in (grid.col_a, grid.col_b):
            return None
        other = grid.col_b if s is grid.col_a else grid.col_a
        return other.handle(1) if grid.shows_two(other) else None

    def line_at(self, at: int) -> QLine:
        """The line landed at ``at``, in the grid's coordinates."""
        s = self.splitter()
        o = s.mapTo(self._grid(), QPoint(0, 0))
        c = at + self.thickness() // 2
        if self.orientation() == Qt.Horizontal:
            return QLine(o.x() + c, o.y(), o.x() + c, o.y() + s.height())
        return QLine(o.x(), o.y() + c, o.x() + s.width(), o.y() + c)

    def move_to(self, at: int) -> None:
        s = self.splitter()
        i = s.indexOf(self)
        sizes = s.sizes()
        total = sizes[i - 1] + sizes[i]
        first = at - self.along(s.widget(i - 1).pos())
        sizes[i - 1], sizes[i] = first, total - first
        s.setSizes(sizes)

    def _show_landing(self, global_pos: QPoint) -> None:
        s = self.splitter()
        low, high = self.limits()
        targets = [self.middle()]
        other = self.other_half()
        if other is not None:
            targets.append(other.y())
        self._landing, snapped = _stick(
            self.along(s.mapFromGlobal(global_pos)) - self._drag_offset,
            low, high, targets)
        self._grid().divider_guide.show_lines(
            [(self.line_at(self._landing), snapped)])

    def cancel(self) -> None:
        self._drag_offset = None
        self._landing = None

    def mousePressEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if ev.button() != Qt.LeftButton:
            ev.ignore()
            return
        self._drag_offset = self.along(ev.position().toPoint())
        self._grid().begin_drag(self)
        self._show_landing(ev.globalPosition().toPoint())
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if self._drag_offset is not None:
            self._show_landing(ev.globalPosition().toPoint())
        elif ev.buttons() == Qt.NoButton:
            self._grid().pointer_moved(ev.globalPosition().toPoint())
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if self._drag_offset is not None:
            at = self._landing
            self.cancel()
            self._grid().end_drag()
            self.move_to(at)
        ev.accept()

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802 — Qt override
        ev.accept()


class _CrossHandle(QWidget):
    """The square with four arrows on a crossing of the lines, there while the
    pointer is near it: it drags the lines that meet there as one block."""

    #: Its side, and how near (px) the pointer brings it.
    SIDE = 22
    NEAR = 18

    def __init__(self, grid) -> None:
        super().__init__(grid)
        self._grid = grid
        self.setFixedSize(self.SIDE, self.SIDE)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip(tr("Drag: move these views' lines together"))
        self.hide()
        self._drag_offset = None
        self._landing = None

    def centre(self) -> QPoint:
        return self.pos() + QPoint(self.SIDE // 2, self.SIDE // 2)

    def place(self, centre: QPoint) -> None:
        self.move(centre - QPoint(self.SIDE // 2, self.SIDE // 2))
        self.show()
        self.raise_()

    def paintEvent(self, _ev) -> None:  # noqa: N802 — Qt override
        from views.theme import accent_color
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(accent_color() if self._drag_offset is not None
                   else QColor(32, 36, 42, 215))
        p.drawRoundedRect(self.rect(), 3, 3)
        p.translate(self.width() / 2, self.height() / 2)
        p.setBrush(QColor("white"))
        for _ in range(4):
            p.drawRect(QRectF(-1, -6, 2, 6))
            p.drawPolygon([QPointF(0, -9), QPointF(-3.5, -5), QPointF(3.5, -5)])
            p.rotate(90)
        p.end()

    def _show_landing(self, global_pos: QPoint) -> None:
        grid = self._grid
        at = grid.mapFromGlobal(global_pos) - self._drag_offset
        column = grid.columns.handle(1)
        low, high = column.limits()
        x = column.along(grid.columns.mapFrom(grid, at)) - column.thickness() // 2
        x, x_stuck = _stick(x, low, high, [column.middle()])
        rows = grid.row_lines()
        low = max(r.limits()[0] for r in rows)
        high = min(r.limits()[1] for r in rows)
        first = rows[0]
        y = first.along(first.splitter().mapFrom(grid, at)) - first.thickness() // 2
        y, y_stuck = _stick(y, low, high, [first.middle()])
        self._landing = (x, y)
        grid.divider_guide.show_lines(
            [(column.line_at(x), x_stuck)]
            + [(self._row_guide(r, x, y), y_stuck) for r in rows])
        self.place(QPoint(column.line_at(x).x1(), first.line_at(y).y1()))

    def _row_guide(self, row, x: int, y: int) -> QLine:
        """``row``'s guide at ``y``, reaching the column line at ``x`` (where
        it will be, not where it is): the guide draws the views as they will
        be, with no stub left over from the old crossing."""
        grid = self._grid
        line = row.line_at(y)
        left = grid.columns.mapTo(grid, QPoint(x, 0)).x()
        right = left + grid.columns.handle(1).thickness()
        if row.splitter() is grid.columns.widget(0):
            line.setP2(QPoint(left, line.y2()))
        else:
            line.setP1(QPoint(right, line.y1()))
        return line

    def cancel(self) -> None:
        self._drag_offset = None
        self._landing = None
        self.update()

    def mousePressEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if ev.button() != Qt.LeftButton:
            ev.ignore()
            return
        self._drag_offset = (self._grid.mapFromGlobal(
            ev.globalPosition().toPoint()) - self.centre())
        self._grid.begin_drag(self)
        self._show_landing(ev.globalPosition().toPoint())
        ev.accept()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if self._drag_offset is not None:
            self._show_landing(ev.globalPosition().toPoint())
        ev.accept()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if self._drag_offset is None:
            ev.accept()
            return
        x, y = self._landing
        self.cancel()
        self._grid.end_drag()
        self._grid.columns.handle(1).move_to(x)
        for row in self._grid.row_lines():
            row.move_to(y)
        ev.accept()

    def leaveEvent(self, ev) -> None:  # noqa: N802 — Qt override
        if self._drag_offset is None:
            self._grid.pointer_moved(QCursor.pos())
        super().leaveEvent(ev)


class _ViewSplitter(QSplitter):
    """A splitter of the views' grid, with lines of its own."""

    def __init__(self, orientation, grid) -> None:
        super().__init__(orientation)
        self.view_grid = grid

    def createHandle(self):  # noqa: N802 — Qt override
        return _ViewSplitterHandle(self.orientation(), self)


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
        self._kept_sizes = None
        self._tool_view = None
        self._follow = _FollowWindow(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.columns = _ViewSplitter(Qt.Horizontal, self)
        self.columns.setChildrenCollapsible(False)
        lay.addWidget(self.columns)
        self.cells = [ViewCell(self, i, main_viewport if i == 1 else None)
                      for i in range(4)]
        # Column A holds cells 0 and 2, column B cells 1 and 3.
        self.col_a = _ViewSplitter(Qt.Vertical, self)
        self.col_b = _ViewSplitter(Qt.Vertical, self)
        for col, cells in ((self.col_a, (0, 2)), (self.col_b, (1, 3))):
            col.setChildrenCollapsible(False)
            for i in cells:
                col.addWidget(self.cells[i])
            self.columns.addWidget(col)
        self.divider_guide = _DividerGuide(self)
        self.cross = _CrossHandle(self)
        self._dragging = None
        self._esc_filter = _EscCancelsDrag(self)
        main_viewport.sceneVersionChanged.connect(self._repaint_extras)
        self._apply()

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
        self._kept_sizes = None
        if key != "single" and not self.extras():
            self._make_extras()
        # Their caches stand: only another document makes them again (a
        # second or more of every layout change on a model of some size).
        if any(vp.scene is not self.main.scene for vp in self.extras()):
            self.follow_document()
        self._apply()
        sync = getattr(self.window(), "on_active_view_changed", None)
        if sync is not None:      # one view: the Styles are the window's
            sync()

    def set_enabled(self, on: bool) -> None:
        """Four views, or the one."""
        self.set_layout("four" if on else "single")

    def set_active_cell(self, cell) -> None:
        """The view being worked in: its label in the accent colour. The
        Styles (menu, panel) and the projection buttons show its own."""
        if cell is self.active_cell():
            return
        for c in self.cells:
            c.header.set_active(c is cell)
        sync = getattr(self.window(), "on_active_view_changed", None)
        if sync is not None:
            sync()

    def active_cell(self):
        return next((c for c in self.cells
                     if c.header.property("active")), None)

    def toggle_maximized(self, cell) -> None:
        if not self.is_enabled():
            return
        self._keep_sizes(None if self._maximized is cell else cell)
        self._maximized = None if self._maximized is cell else cell
        self.set_active_cell(cell)
        self._apply()

    def _keep_sizes(self, maximizing) -> None:
        """A view is about to fill the area: where the lines are now, for
        Restore to find them."""
        if maximizing is not None and self._maximized is None:
            self._kept_sizes = (self.columns.sizes(), self.col_a.sizes(),
                                self.col_b.sizes())

    def set_tool_view(self, viewport) -> None:
        """The pointer is in ``viewport``: the tool's preview shows there."""
        if viewport is not self._tool_view:
            self._tool_view = viewport
            self._sync_tool_preview()

    def _sync_tool_preview(self) -> None:
        """A tool's preview in one view only, not one of its own in each. A
        view gone from sight hands over to the one filling the area, or the
        window's."""
        views = [c for c in self.cells if c.viewport is not None]
        if not any(c.viewport is self._tool_view and not c.isHidden()
                   for c in views):
            self._tool_view = (self._maximized.viewport
                               if self._maximized is not None else self.main)
        on_all = not self.is_enabled()
        for cell in views:
            want = on_all or cell.viewport is self._tool_view
            if cell.viewport.tool_preview != want:
                cell.viewport.tool_preview = want
                cell.viewport.update()

    def toggle_maximized_here(self) -> None:
        """Ctrl+Space: back to the others if a view fills the area; else the view
        under the pointer fills it, or the one being worked in, or the
        window's own."""
        if not self.is_enabled():
            return
        cell = self._maximized
        if cell is None:
            shown = [c for c in self.cells if not c.isHidden()]
            at = QCursor.pos()
            cell = next((c for c in shown
                         if c.rect().contains(c.mapFromGlobal(at))), None)
        if cell is None:
            active = self.active_cell()
            cell = (active if active is not None and not active.isHidden()
                    else self.cells[1])
        self.toggle_maximized(cell)

    # ---- dragging the lines ---------------------------------------------------
    def shows_two(self, column) -> bool:
        """``column`` is on show with its two views, so with a line."""
        return (not column.isHidden()
                and sum(not column.widget(i).isHidden()
                        for i in range(column.count())) == 2)

    def row_lines(self) -> list:
        """The lines across the columns, in the columns showing two views."""
        return [c.handle(1) for c in (self.col_a, self.col_b)
                if self.shows_two(c)]

    def crossings(self) -> list:
        """Where the line between the columns meets those across them, in
        this widget's coordinates: one with the two halves lined up, two when
        they are apart."""
        if not self.is_enabled() or self._maximized is not None:
            return []
        column = self.columns.handle(1)
        if column.isHidden():
            return []
        x = column.line_at(column.along(column.pos())).x1()
        ys = {r.line_at(r.along(r.pos())).y1() for r in self.row_lines()}
        return [QPoint(x, y) for y in sorted(ys)]

    def pointer_moved(self, global_pos: QPoint) -> None:
        """The square with arrows comes while the pointer is near a crossing."""
        if self._dragging is not None:
            return
        # Only with Select in hand: a drawing tool's click there is the tool's.
        if getattr(self.main.active_tool, "name", "Select") != "Select":
            self.cross.hide()
            return
        at = self.mapFromGlobal(global_pos)
        near = [c for c in self.crossings()
                if (c - at).manhattanLength() <= 2 * self.cross.NEAR
                and abs(c.x() - at.x()) <= self.cross.NEAR
                and abs(c.y() - at.y()) <= self.cross.NEAR]
        if near:
            self.cross.place(min(
                near, key=lambda c: (c - at).manhattanLength()))
        else:
            self.cross.hide()

    def lines_state(self) -> dict:
        """Where the lines are, as shares of the room they split, for the
        file: with a view maximized, where Restore would put them."""
        columns, col_a, col_b = self._kept_sizes or (
            self.columns.sizes(), self.col_a.sizes(), self.col_b.sizes())

        def share(sizes):
            total = sum(sizes)
            return sizes[0] / total if len(sizes) == 2 and total > 0 else 0.5
        return {"columns": share(columns), "rows": [share(col_a), share(col_b)]}

    def apply_lines_state(self, state) -> None:
        """Put back :meth:`lines_state`; anything odd in it is left alone."""
        def put(splitter, share):
            if (isinstance(share, (int, float))
                    and not isinstance(share, bool) and 0 < share < 1):
                # Shares, not pixels: setSizes scales them to the room.
                splitter.setSizes([round(share * 10000),
                                   round((1 - share) * 10000)])
        if not isinstance(state, dict):
            return
        put(self.columns, state.get("columns"))
        rows = state.get("rows")
        if isinstance(rows, (list, tuple)) and len(rows) == 2:
            put(self.col_a, rows[0])
            put(self.col_b, rows[1])

    def begin_drag(self, dragging) -> None:
        self._dragging = dragging
        if dragging is not self.cross:
            self.cross.hide()
        # Last in, first asked: ahead of every filter already there.
        QApplication.instance().installEventFilter(self._esc_filter)

    def end_drag(self) -> None:
        self._dragging = None
        QApplication.instance().removeEventFilter(self._esc_filter)
        self.divider_guide.hide()
        self.cross.hide()

    def cancel_drag(self) -> None:
        """Esc: everything stays as it was."""
        if self._dragging is not None:
            self._dragging.cancel()
            self.end_drag()

    def _apply(self) -> None:
        on = self.is_enabled()
        self.cross.hide()
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
        if on and self._maximized is None and self._kept_sizes is not None:
            for splitter, sizes in zip((self.columns, self.col_a, self.col_b),
                                       self._kept_sizes):
                splitter.setSizes(sizes)
            self._kept_sizes = None
        elif on and self._maximized is None:
            total = max(1, self.width())
            parts = [total * w // sum(widths) for w in widths]
            if len(parts) == 2:
                self.columns.setSizes(parts)
            half = max(1, self.height() // 2)
            for col in (self.col_a, self.col_b):
                col.setSizes([half, half])
        self._sync_tool_preview()
        sync = getattr(self.window(), "_sync_maximize_action", None)
        if sync is not None:
            sync()
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
            # What extensions registered: one list per window, as in
            # MainWindow._make_viewport.
            for name in ("_ext_overlays", "_ext_snap_providers",
                         "_ext_pickables"):
                if hasattr(main, name):
                    setattr(vp, name, getattr(main, name))
            # set_document hands this view's own to the incoming scene.
            vp.scene.hide_similar_components = bool(
                getattr(main.scene, "hide_similar_components", False))
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
                vp.view_style = None    # another document: its own style
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
            self._keep_sizes(cell)
            self._maximized = cell
            self._apply()

    def state(self):
        """What each extra view shows — its view key and camera — for the
        project going to the back (None before the views exist)."""
        if not self.extras():
            return None
        return [(c.view, _camera_state(c.viewport.camera),
                 c.viewport.view_style)
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
                cell.viewport.view_style = None
                cell.show_view(cell.view)
            return
        for cell, (view, cam, *rest) in zip(cells, state):
            # Each view's own style (None: the window's); older states
            # carried only the view and the camera.
            cell.viewport.view_style = rest[0] if rest else None
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
