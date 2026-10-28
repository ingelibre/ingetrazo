# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The **Layers** tab of the side tray: the document's layers as a tree,
beside the Browser.

One row per layer, filed under folders when it has one: the pencil marks
the ACTIVE layer (new objects go there, core.layers.tag_new_objects), the
eye and the padlock show and lock, the swatch is the layer's colour (what
«Colour by layer» paints the model with), and the last column counts what
carries the layer. Clicking the eye or the padlock of one of several
selected rows acts on all of them; clicking a column header sorts, with the
default layer always first. Visibility, lock, colour and folders are
display state and stay off the undo stack, like before; deleting a layer
is one undo step (core.history.DeleteLayerCommand).
"""
from __future__ import annotations

from PySide6.QtCore import (QItemSelectionModel, QPoint, QPointF, QRectF, Qt,
                            QTimer)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDockWidget,
                               QHBoxLayout, QHeaderView, QLineEdit, QMenu,
                               QMessageBox, QStyledItemDelegate,
                               QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from core import layers as L
from core.i18n import tr
from views.outliner import _HeaderButton, _StripFiller, node_icon

(COL_NAME, COL_ACTIVE, COL_EYE, COL_LOCK, COL_COLOR, COL_COUNT,
 COL_ISOLATE, COL_LINETYPE, COL_WEIGHT, COL_OPACITY, COL_PRINT) = range(11)

#: The row kinds kept in ``Qt.UserRole`` of the name column.
KIND_LAYER, KIND_FOLDER = "layer", "folder"
#: Name-column role: the row holds what is selected in the model (its
#: layer, or a folded folder with that layer inside).
ROLE_HOLDS = Qt.UserRole + 2
#: Line-type column role: the layer's line type key, drawn by
#: :class:`_LineDelegate`.
ROLE_LINETYPE = Qt.UserRole + 3
#: Name-column role: where the row stands in the document's own order (the
#: order the layers and folders were made in).
ROLE_ORDER = Qt.UserRole + 4



def _submenu(menu, title):
    """A submenu parented to ``menu``. ``menu.addMenu(title)`` makes one
    Python holds no reference to, and inside a helper it can be deleted
    with the helper's locals before it ever opens."""
    from PySide6.QtWidgets import QMenu
    sub = QMenu(title, menu)
    menu.addMenu(sub)
    return sub

def natural_key(text: str) -> tuple:
    """Sort key that reads the numbers in a name as numbers: «Capa 2»
    before «Capa 10», «Planta 9» before «Planta 12»."""
    import re
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part)
                 for part in re.split(r"(\d+)", text.casefold()) if part)


def _pencil_icon(on: bool) -> QIcon:
    """The active layer's mark: the toolbar's «Make active» pencil, drawn
    in the chosen accent on the active row and as a faint outline on the
    others (where clicking makes it active)."""
    from PySide6.QtWidgets import QApplication
    from views.icons import pencil_glyph
    from views.theme import accent_color
    ink = QApplication.palette().text().color()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # The glyph's 16.5-unit box in the 48 canvas onto the 18 px cell.
    k = 15.0 / 16.5
    p.translate(1.5, 1.5)
    p.scale(k, k)
    p.translate(-27, -25.5)
    if on:
        pen = QPen(ink, 1.6 / k)
        p.setBrush(accent_color())
    else:
        faint = QColor(ink)
        faint.setAlpha(80)
        pen = QPen(faint, 1.2 / k)
        p.setBrush(Qt.NoBrush)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    pencil_glyph(p)
    p.end()
    return QIcon(pm)


def add_icon(kind: str) -> QIcon:
    """The icon of the add buttons beside the filter: the layer sheets or a
    folder, each with a «+», drawn like every other icon of the bar."""
    from views.icons import tool_icon
    return tool_icon("folder_add" if kind == KIND_FOLDER else "layer_add")


def printer_icon(on: bool) -> QIcon:
    """The print mark of a row: a printer in ink when the layer goes onto
    the sheets; faint and struck through when it stays off them."""
    from PySide6.QtWidgets import QApplication
    ink = QColor(QApplication.palette().text().color())
    if not on:
        ink.setAlpha(110)
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(ink, 1.2)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(5.5, 2.5, 7, 4))              # the paper going in
    p.drawRoundedRect(QRectF(2.5, 6.5, 13, 6), 1.5, 1.5)   # the body
    p.drawRect(QRectF(5.5, 10.5, 7, 5))             # the sheet coming out
    if not on:
        strike = QPen(ink, 1.6)
        strike.setCapStyle(Qt.RoundCap)
        p.setPen(strike)
        p.drawLine(QPointF(2.5, 15.5), QPointF(15.5, 2.5))
    p.end()
    return QIcon(pm)


def swatch_icon(rgb) -> QIcon:
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtWidgets import QApplication
    p.setPen(QPen(QApplication.palette().text().color(), 1.0))
    p.setBrush(QColor.fromRgbF(*rgb[:3]))
    p.drawRoundedRect(QRectF(2.5, 3.5, 13, 11), 2, 2)
    p.end()
    return QIcon(pm)


#: The «no colour» slash of the default layer's swatch.
NO_COLOUR_SLASH = QColor(214, 48, 49)


def layers_signature(scene) -> tuple:
    """Everything the Layers rows are drawn from — each layer's own state,
    the folders, the active layer and «colour by layer». The same value
    twice means the rows would come out the same: an edit of the model
    (a push, a move) leaves it as it was and does not rebuild the list."""
    style = getattr(scene, "display_style", None)
    folders = tuple(L.folders_of(scene))
    return (tuple(repr(sorted(vars(ly).items())) for ly in scene.layers),
            folders, tuple(L.folder_parent(scene, f) for f in folders),
            L.active_layer(scene),
            bool(getattr(style, "color_by_layer", False)))


def layer_swatch(ly) -> QIcon:
    """A layer's swatch. The default layer with no colour picked has none
    of its own, and must not pass for one: an empty (base-coloured) swatch
    crossed by a red slash from the top-left corner to the bottom-right —
    the usual «none» mark."""
    if ly is None or ly.color is not None or ly.name != L.DEFAULT_LAYER:
        return swatch_icon(L.layer_color(ly))
    from PySide6.QtGui import QPainterPath
    from PySide6.QtWidgets import QApplication
    pal = QApplication.palette()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    box = QRectF(2.5, 3.5, 13, 11)
    path = QPainterPath()
    path.addRoundedRect(box, 2, 2)
    p.setPen(Qt.NoPen)
    p.setBrush(pal.base().color())
    p.drawPath(path)
    p.setClipPath(path)
    slash = QPen(NO_COLOUR_SLASH, 1.8)
    slash.setCapStyle(Qt.FlatCap)
    p.setPen(slash)
    p.drawLine(box.topLeft(), box.bottomRight())
    p.setClipping(False)
    p.setPen(QPen(pal.text().color(), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(box, 2, 2)
    p.end()
    return QIcon(pm)


class _Row(QTreeWidgetItem):
    """A row that sorts the way the panel reads: the default layer first,
    then the folders, then the layers — whichever way the column runs."""

    def __lt__(self, other) -> bool:
        tree = self.treeWidget()
        col = tree.sortColumn() if tree is not None else COL_NAME
        asc = (tree is None
               or tree.header().sortIndicatorOrder() == Qt.AscendingOrder)
        a, b = self._rank(), other._rank()
        if a != b:
            # Ranks hold in both directions: undo the reversal Qt applies.
            return (a < b) if asc else (a > b)
        panel = getattr(tree, "_panel", None)
        if col == COL_NAME and getattr(panel, "sort_by", "name") == "created":
            oa, ob = self.data(COL_NAME, ROLE_ORDER), other.data(COL_NAME,
                                                                 ROLE_ORDER)
            if oa is not None and ob is not None and oa != ob:
                return oa < ob
        ka, kb = self.data(col, Qt.UserRole + 1), other.data(col, Qt.UserRole + 1)
        if ka is None or kb is None or ka == kb:
            return (natural_key(self.text(COL_NAME))
                    < natural_key(other.text(COL_NAME)))
        return ka < kb

    def _rank(self) -> int:
        kind, name = self.data(COL_NAME, Qt.UserRole) or (KIND_LAYER, "")
        if kind == KIND_LAYER and name == L.DEFAULT_LAYER:
            return 0
        return 1 if kind == KIND_FOLDER else 2


class _HoldsDelegate(QStyledItemDelegate):
    """The name column with the selection's mark: a bar of the accent at
    the row's left edge (the row's tint does the rest)."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.data(ROLE_HOLDS):
            from PySide6.QtWidgets import QApplication
            r = option.rect
            painter.fillRect(r.left(), r.top() + 2, 3, r.height() - 4,
                             QApplication.palette().highlight())


#: Room kept between a dropped list and the panel's sides, in pixels.
MENU_MARGIN = 6


def place_menu(menu, anchor, inside):
    """Where ``menu`` drops under ``anchor`` (a global QRect): always the
    same way — its right edge on the anchor's, so every list of the panel
    opens alike — and kept inside ``inside`` (the panel, global) with a
    small margin, never out to the screen's edge; above the anchor when the
    screen has no room below."""
    size = menu.sizeHint()
    x = anchor.right() + 1 - size.width()
    x = min(x, inside.right() + 1 - MENU_MARGIN - size.width())
    x = max(x, inside.left() + MENU_MARGIN)
    y = anchor.bottom() + 1
    screen = (QApplication.screenAt(anchor.center())
              or QApplication.primaryScreen())
    avail = screen.availableGeometry()
    if y + size.height() > avail.bottom():
        y = max(avail.top(), anchor.top() - size.height())
    return QPoint(x, y)


def global_rect(widget, rect=None):
    """``rect`` (``widget``'s whole rect by default) in screen coordinates."""
    from PySide6.QtCore import QRect
    r = widget.rect() if rect is None else rect
    return QRect(widget.mapToGlobal(r.topLeft()), r.size())


class _StayOpenMenu(QMenu):
    """A menu of switches that stays open while they are flipped — several
    columns on or off in one go — and closes on a click outside or Esc.
    An entry with the ``keep_open`` property set stays open too."""

    @staticmethod
    def _stays(action) -> bool:
        return (action is not None and action.isEnabled()
                and (action.isCheckable() or bool(action.property("keep_open"))))

    def mouseReleaseEvent(self, event) -> None:
        action = self.actionAt(event.position().toPoint())
        if self._stays(action):
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        action = self.activeAction()
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space)
                and self._stays(action)):
            action.trigger()
            event.accept()
            return
        super().keyPressEvent(event)


def line_pen(key: str, ink, width: float, px_per_mm: float) -> QPen:
    """A pen in the dash pattern of line type ``key`` (millimetres on paper
    shown at ``px_per_mm`` screen pixels each)."""
    pen = QPen(ink, width)
    pen.setCapStyle(Qt.FlatCap)
    pattern = L.LINETYPES.get(key, ())
    if pattern:
        pen.setDashPattern([max(0.3, mm * px_per_mm / width)
                            for mm in pattern])
    return pen


class _LineSample(QWidget):
    """One entry of the line type or line weight list: the line itself,
    drawn — its type, or its weight with the value beside it — and a tick
    on the current one. The line type's name stays as the tooltip. A click
    picks it. Both lists are made of these, so they look alike."""

    #: Where the drawn line ends when a value follows it.
    LINE_END = 86

    def __init__(self, key, action, menu, checked: bool,
                 width: float = 2.0, text: str = "", swatch=None) -> None:
        super().__init__()
        self.key = key                     # None: no line, only the text
        #: ``(rgb, opacity)``: a swatch of the colour at that opacity over a
        #: checkerboard, in the line's place (the transparency list).
        self.swatch = swatch
        self._action = action
        self._menu = menu
        self._checked = checked
        self._width = width
        self._text = text
        self._hover = False
        self.setMouseTracking(True)
        self.setToolTip(action.text())
        w = 170                       # room for two repeats of a long dash
        if text:
            w = (self.LINE_END if (key is not None or swatch is not None)
                 else 18) + 14 \
                + self.fontMetrics().horizontalAdvance(text) + 14
        self.setMinimumSize(max(120, w), 26)

    def enterEvent(self, _e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._menu.close()
            self._action.trigger()

    def paintEvent(self, _e) -> None:
        from PySide6.QtWidgets import QApplication
        pal = QApplication.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        ink = pal.text().color()
        if self._hover:
            p.fillRect(r, pal.highlight())
            ink = pal.highlightedText().color()
        if self._checked:                    # the current one: a tick
            tick = QPen(ink, 1.8)
            tick.setCapStyle(Qt.RoundCap)
            p.setPen(tick)
            cy = r.center().y()
            p.drawPolyline([QPointF(8, cy), QPointF(11, cy + 3),
                            QPointF(17, cy - 4)])
        y = r.center().y() + 0.5
        end = self.LINE_END if self._text else r.right() - 12
        if self.key is not None:
            p.setPen(line_pen(self.key, ink, self._width, 3.0))
            p.drawLine(QPointF(26, y), QPointF(end, y))
        if self.swatch is not None:
            see_through_swatch(p, QRectF(26, y - 7, end - 26, 14),
                               *self.swatch, ink)
        if self._text:
            p.setPen(ink)
            left = end + 14 if (self.key is not None
                                or self.swatch is not None) else 26
            p.drawText(r.adjusted(left, 0, 0, 0),
                       Qt.AlignVCenter | Qt.AlignLeft, self._text)
        p.end()


def see_through_swatch(p, rect, rgb, opacity: float, ink) -> None:
    """``rgb`` at ``opacity`` over a grey checkerboard, outlined: how see-
    through a layer's faces are."""
    p.save()
    p.setPen(Qt.NoPen)
    p.fillRect(rect, QColor(255, 255, 255))
    cell = 4.0
    dark = QColor(190, 190, 190)
    y = rect.top()
    row = 0
    while y < rect.bottom():
        x = rect.left() + (cell if row % 2 else 0.0)
        while x < rect.right():
            p.fillRect(QRectF(x, y, min(cell, rect.right() - x),
                              min(cell, rect.bottom() - y)), dark)
            x += 2 * cell
        y += cell
        row += 1
    colour = QColor.fromRgbF(*rgb[:3])
    colour.setAlphaF(max(0.0, min(1.0, opacity)))
    p.fillRect(rect, colour)
    p.setPen(QPen(ink, 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRect(rect)
    p.restore()


class _LineDelegate(QStyledItemDelegate):
    """The line-type column: a stroke across the cell in the layer's dash
    pattern, as the sheets draw its lines."""

    #: Screen pixels per paper millimetre of the dash pattern.
    PX_PER_MM = 2.0

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        key = index.data(ROLE_LINETYPE)
        if key is None:
            return
        from PySide6.QtWidgets import QApplication, QStyle
        pal = QApplication.palette()
        ink = (pal.highlightedText() if option.state & QStyle.State_Selected
               else pal.text()).color()
        r = option.rect
        # One whole repeat at least, however narrow the cell: a long-dash
        # pattern drawn at full scale would show a single dash and read as
        # any other.
        period = sum(L.LINETYPES.get(key, ()))
        room = max(1.0, r.width() - 10.0)
        ppm = (min(self.PX_PER_MM, room / (1.5 * period)) if period
               else self.PX_PER_MM)
        pen = line_pen(key, ink, 1.6, ppm)
        y = r.center().y() + 0.5
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(pen)
        painter.drawLine(QPointF(r.left() + 5, y), QPointF(r.right() - 5, y))
        painter.restore()


class _LayerTree(QTreeWidget):
    """The layer tree, taking drops of its own rows: what is dragged goes
    into the folder dropped on — the folder of the layer dropped on, or out
    of any folder on the empty space. Qt never moves a row by itself here:
    the document changes and the tree is rebuilt from it."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        #: Width of the strip kept free at the right for the columns button.
        self.button_strip = 0
        self._filler = _StripFiller(self)
        self._filler.hide()
        self.viewport().installEventFilter(self)    # the strip repaints too
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        # Qt's line between rows says «between these two», which a drop
        # here never means: the folder it files into is outlined instead.
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        # Hovering a folded folder while dragging unfolds it.
        self.setAutoExpandDelay(600)
        #: While a drag is over the tree: ``(folder,)`` — the folder a drop
        #: would file into (``None``: out of any folder); else ``None``.
        self.drop_hint: tuple | None = None

    #: The cells a press acts on directly, as in the Browser: the row's
    #: selection is left as it is, so a click on the eye of one of several
    #: selected rows acts on all of them.
    _CELLS = (COL_ACTIVE, COL_EYE, COL_LOCK, COL_ISOLATE, COL_COLOR,
              COL_LINETYPE, COL_WEIGHT, COL_OPACITY, COL_PRINT)

    #: A press on one of the cells is the panel's until the button is let
    #: go: Qt never saw it, so a move with the button held would draw a
    #: selection box from wherever Qt's last press was — a few pixels of
    #: wobble while clicking an eye selected a run of layers.
    _cell_press = False

    def _cell_click(self, event) -> bool:
        """Act on a plain left click on one of :attr:`_CELLS`; whether it
        was one (and so taken)."""
        if (event.button() != Qt.LeftButton
                or event.modifiers() & (Qt.ControlModifier
                                        | Qt.ShiftModifier)):
            return False
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        col = self.columnAt(pos.x())
        if item is None or col not in self._CELLS:
            return False
        key = self._panel._key(item)
        targets = self._panel._targets(item)
        event.accept()
        self._cell_press = True
        QTimer.singleShot(0, lambda: self._panel.click_cell(
            key, col, targets))
        return True

    def mousePressEvent(self, event) -> None:
        if not self._cell_click(event):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — Qt override
        # Two quick clicks on an eye are two clicks (off and on again), not
        # a double click for the list to select or rename the row with.
        if not self._cell_click(event):
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:         # noqa: N802 — Qt override
        if self._cell_press:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:      # noqa: N802 — Qt override
        if self._cell_press:
            self._cell_press = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def updateGeometries(self) -> None:
        """Qt lays the header over the whole viewport; a strip is then kept
        at the right for the columns button, header and rows one strip
        narrower — the Browser's layout."""
        super().updateGeometries()
        m = self.viewportMargins()
        if m.right() != self.button_strip:
            self.setViewportMargins(m.left(), m.top(), self.button_strip,
                                    m.bottom())
        vg = self.viewport().geometry()
        head = self.header()
        if not head.isHidden():
            head.setGeometry(vg.left(), vg.top() - m.top(), vg.width(),
                             m.top())
        b = getattr(self._panel, "columns_button", None)
        if b is not None:
            g = head.geometry()
            b.setGeometry(g.right() + 1, g.top(), b.width(), g.height())
        self._filler.setGeometry(vg.right() + 1, vg.top(), self.button_strip,
                                 vg.height())
        self._filler.setVisible(self.button_strip > 0)

    def row_parity(self, index) -> bool:
        """Whether the row of ``index`` is painted in the alternate tone."""
        n = 0
        above = self.indexAbove(index)
        while above.isValid():
            n += 1
            above = self.indexAbove(above)
        return bool(n % 2)

    def eventFilter(self, obj, ev) -> bool:
        from PySide6.QtCore import QEvent
        if obj is self.viewport() and ev.type() == QEvent.Paint:
            self._filler.update()
        return super().eventFilter(obj, ev)

    def _is_delete(self, event) -> bool:
        return (event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
                and self.state() != QAbstractItemView.EditingState)

    def event(self, event) -> bool:
        # Delete belongs to the list while it has the focus, not to a
        # window shortcut.
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.ShortcutOverride and self._is_delete(event):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if self._is_delete(event):
            event.accept()
            self._panel._on_delete()
            return
        super().keyPressEvent(event)

    def target_folder(self, pos) -> str | None:
        """The folder a drop at ``pos`` (viewport coordinates) files into."""
        item = self.itemAt(pos)
        if item is None:
            return None
        kind, name = self._panel._key(item)
        if kind == KIND_FOLDER:
            return name
        parent = item.parent()
        return self._panel._key(parent)[1] if parent is not None else None

    #: How see-through the dragged rows are, and how many are drawn before
    #: the rest is only counted.
    DRAG_OPACITY = 0.55
    DRAG_ROWS = 6

    def drag_pixmap(self):
        """The rows being dragged, as they look in the list, stacked with
        no gaps between them (however far apart they sit) and see-through,
        so the folders under the pointer still show. ``(pixmap, rows)``."""
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QApplication
        vp = self.viewport()
        rows = [it for it in self.selectedItems()
                if self.visualItemRect(it).isValid()]
        rows.sort(key=lambda it: self.visualItemRect(it).top())
        shown = rows[:self.DRAG_ROWS]
        if not shown:
            return QPixmap(), []
        width = vp.width()
        heights = [self.visualItemRect(it).height() for it in shown]
        extra = len(rows) - len(shown)
        foot = heights[0] if extra else 0
        dpr = vp.devicePixelRatioF()
        pm = QPixmap(round(width * dpr), round((sum(heights) + foot) * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setOpacity(self.DRAG_OPACITY)
        y = 0
        for it, h in zip(shown, heights):
            r = self.visualItemRect(it)
            p.drawPixmap(0, y, vp.grab(QRect(0, r.top(), width, h)))
            y += h
        p.setOpacity(1.0)
        accent = QColor(QApplication.palette().highlight().color())
        if extra:
            p.setPen(QApplication.palette().text().color())
            p.drawText(QRectF(0, y, width, foot), Qt.AlignCenter,
                       tr("+{n} more", n=extra))
        p.setPen(QPen(accent, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.75, 0.75, width - 1.5, y + foot - 1.5),
                          3, 3)
        p.end()
        return pm, rows

    def startDrag(self, actions) -> None:
        from PySide6.QtGui import QCursor, QDrag
        pm, rows = self.drag_pixmap()
        if not rows:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(rows))
        drag.setPixmap(pm)
        # Held where it was picked up: the pointer stays on the row it
        # pressed, within the first row's height.
        at = self.viewport().mapFromGlobal(QCursor.pos())
        first = self.visualItemRect(rows[0])
        drag.setHotSpot(QPoint(max(0, min(at.x(), first.width() - 1)),
                               max(0, min(at.y() - first.top(),
                                          first.height() - 1))))
        drag.exec(Qt.MoveAction)
        self._clear_hint()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self:
            super().dragMoveEvent(event)             # auto-scroll, unfold
            event.setDropAction(Qt.MoveAction)
            event.accept()
            hint = (self.target_folder(event.position().toPoint()),)
            if hint != self.drop_hint:
                self.drop_hint = hint
                self.viewport().update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)
        self._clear_hint()

    def _clear_hint(self) -> None:
        if self.drop_hint is not None:
            self.drop_hint = None
            self.viewport().update()

    def folder_item(self, name: str):
        """The row of folder ``name``, or None."""
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        it = QTreeWidgetItemIterator(self)
        while it.value() is not None:
            item = it.value()
            if self._panel._key(item) == (KIND_FOLDER, name):
                return item
            it += 1
        return None

    def drop_rect(self, folder: str | None):
        """Where the drop lands, in viewport coordinates: the folder's row
        and every row shown inside it, full width; the whole list for «out
        of any folder»."""
        from PySide6.QtCore import QRect
        vp = self.viewport().rect()
        if folder is None:
            return vp
        item = self.folder_item(folder)
        if item is None:
            return QRect()
        rect = self.visualItemRect(item)
        stack = [item]
        while stack:
            node = stack.pop()
            if not node.isExpanded():
                continue
            for i in range(node.childCount()):
                child = node.child(i)
                if child.isHidden():
                    continue
                r = self.visualItemRect(child)
                if r.isValid():
                    rect = rect.united(r)
                stack.append(child)
        return QRect(vp.left(), rect.top(), vp.width(), rect.height())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.drop_hint is None:
            return
        from PySide6.QtWidgets import QApplication
        folder = self.drop_hint[0]
        accent = QColor(QApplication.palette().highlight().color())
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.drop_rect(folder)
        if rect.isValid():
            tint = QColor(accent)
            tint.setAlpha(45)
            p.setBrush(tint)
            p.setPen(QPen(accent, 2.0))
            p.drawRoundedRect(QRectF(rect).adjusted(1.5, 1.5, -1.5, -1.5),
                              4, 4)
        # Said in words too, at the foot of the list: with folders inside
        # folders the outline alone can leave a doubt.
        text = (tr("Into «{folder}»", folder=folder) if folder is not None
                else tr("Out of any folder"))
        fm = p.fontMetrics()
        vp = self.viewport().rect()
        w = fm.horizontalAdvance(text) + 16
        h = fm.height() + 6
        pill = QRectF(vp.right() - w - 6, vp.bottom() - h - 6, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        p.drawRoundedRect(pill, h / 2, h / 2)
        p.setPen(QApplication.palette().highlightedText().color())
        p.drawText(pill, Qt.AlignCenter, text)
        p.end()

    def dropEvent(self, event) -> None:
        self._clear_hint()
        if event.source() is not self:
            event.ignore()
            return
        folder = self.target_folder(event.position().toPoint())
        rows = [self._panel._key(it) for it in self.selectedItems()]
        # Accepted, but as nothing for Qt to do: the panel files the rows
        # in the document and rebuilds the tree from it.
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
        QTimer.singleShot(0, lambda: self._panel.drop_rows(rows, folder))


class LayersPanel(QWidget):
    """The layer tree, its filter and its buttons. See the module doc."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        self._collapsed: set[str] = set()
        self._counts: dict[str, int] = {}
        self._counted_version = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        # The add buttons, then the filter — the Browser's bar: flat tool
        # buttons that raise on hover.
        bar = QHBoxLayout()
        self.add_layer_btn = self._tool_button(
            add_icon(KIND_LAYER), tr("Add layer"), lambda: self.add_layer())
        self.add_folder_btn = self._tool_button(
            add_icon(KIND_FOLDER), tr("Add folder"), lambda: self.add_folder())
        bar.addWidget(self.add_layer_btn)
        bar.addWidget(self.add_folder_btn)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter layers… (* and ? work)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        bar.addWidget(self.search, 1)
        # Quick filters by state, one click each — nothing to build or name
        # (a fixed group of layers is what folders are for).
        self.state_filter = "all"
        self.invert_filter = False
        self.filter_btn = QToolButton()
        self.filter_btn.setAutoRaise(True)
        self.filter_menu = QMenu(self.filter_btn)
        self.filter_btn.clicked.connect(self._open_filter_menu)
        bar.addWidget(self.filter_btn)
        self._show_filter_state()
        # Expand / collapse every folder, as the Browser's. Isolating is per
        # row (the target beside the padlock), as in the Layers drop-down.
        #: What Isolate hid, to show back exactly that on the way out.
        self._isolated: list[str] = []
        # Drawn icons, not text glyphs: the same size and ink as the rest
        # of the bar.
        self.expand_btn = self._tool_button(
            QIcon(), tr("Expand all"), self._expand_or_collapse)
        bar.addWidget(self.expand_btn)
        # Colour by layer, at the top right: the model painted in its
        # layers' colours, on and off in one click.
        from views.icons import tool_icon
        self.color_by_layer = QToolButton()
        self.color_by_layer.setAutoRaise(True)
        self.color_by_layer.setCheckable(True)
        self.color_by_layer.setIcon(tool_icon("layers_colour"))
        self.color_by_layer.setToolTip(tr(
            "Colour by layer: paint the model in its layers' colours "
            "(shaded, textured and X-ray styles). Scenes remember it with "
            "the style."))
        self.color_by_layer.toggled.connect(self.set_color_by_layer)
        bar.addWidget(self.color_by_layer)
        # Templates and options, last: used now and then.
        self.more_btn = QToolButton()
        self.more_btn.setAutoRaise(True)
        self.more_btn.setIcon(tool_icon("layers_templates"))
        self.more_btn.setToolTip(tr("Layer templates and options"))
        self.more_menu = QMenu(self.more_btn)
        self.more_btn.clicked.connect(self._open_more_menu)
        bar.addWidget(self.more_btn)
        lay.addLayout(bar)

        self.tree = _LayerTree(self)
        self.tree.setColumnCount(11)
        self.tree.setHeaderLabels([tr("Name"), "", "", "", "", "#", "",
                                   tr("Line"), "mm", "%", ""])
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col, width in ((COL_ACTIVE, 26), (COL_EYE, 26), (COL_LOCK, 26),
                           (COL_ISOLATE, 26), (COL_COLOR, 26),
                           (COL_LINETYPE, 40), (COL_WEIGHT, 40),
                           (COL_OPACITY, 40), (COL_PRINT, 26),
                           (COL_COUNT, 44)):
            head.setSectionResizeMode(col, QHeaderView.Fixed)
            head.resizeSection(col, width)
        hi = self.tree.headerItem()
        hi.setIcon(COL_ACTIVE, _pencil_icon(True))
        hi.setToolTip(COL_ACTIVE, tr(
            "Active layer: new groups, components, dimensions, texts and "
            "guides go to it"))
        hi.setIcon(COL_EYE, node_icon("eye"))
        hi.setToolTip(COL_EYE, tr("Visible"))
        hi.setIcon(COL_LOCK, node_icon("lock"))
        hi.setToolTip(COL_LOCK, tr("Locked: drawn, but it cannot be picked"))
        from views.layers_toolbar import isolate_icon
        hi.setIcon(COL_ISOLATE, isolate_icon(False))
        hi.setToolTip(COL_ISOLATE, tr(
            "Isolate — a row's target shows only that layer, a second click "
            "shows back what it hid; click here to end the isolation"))
        hi.setToolTip(COL_COLOR, tr("Colour"))
        hi.setToolTip(COL_LINETYPE, tr(
            "Line type the layer's lines take on the sheets and in DXF — "
            "click a row's line to change it"))
        hi.setToolTip(COL_WEIGHT, tr(
            "Line weight in mm (—: default, from the sheet) — click a "
            "row's to change it"))
        hi.setTextAlignment(COL_WEIGHT, Qt.AlignCenter)
        hi.setIcon(COL_PRINT, printer_icon(True))
        hi.setToolTip(COL_PRINT, tr(
            "Print — a layer switched off here is seen in the model but left "
            "out of the sheets, their PDF and DXF; click here for every "
            "layer"))
        hi.setToolTip(COL_OPACITY, tr(
            "Transparency of the layer's faces in the model (—: opaque) — "
            "click a row's to change it"))
        hi.setTextAlignment(COL_OPACITY, Qt.AlignCenter)
        hi.setToolTip(COL_COUNT, tr(
            "Entities on the layer: faces, edges, objects, dimensions, texts, "
            "guides and images"))
        # As in the Browser: eye and padlock first (then the isolate
        # target, as in the drop-down), the name next (the tree lines and
        # folds hang from it), then the rest.
        for visual, logical in enumerate(self.COLUMN_ORDER):
            head.moveSection(head.visualIndex(logical), visual)
        self.tree.setTreePosition(COL_NAME)
        self.tree.setIndentation(self.INDENT)
        hi.setToolTip(COL_EYE, tr("Visible — click here to show or hide "
                                  "every layer"))
        hi.setToolTip(COL_LOCK, tr("Locked — click here to lock or unlock "
                                   "every layer"))
        head.setSectionsClickable(True)
        head.setSortIndicatorShown(True)
        head.sectionClicked.connect(self._on_header_clicked)
        # Which columns show — the Browser's way: right-click on the header,
        # or the button at its right end (which says how many are off).
        head.setContextMenuPolicy(Qt.CustomContextMenu)
        head.customContextMenuRequested.connect(
            lambda _pos: self._open_columns_menu())
        self.columns_button = _HeaderButton(self.tree)
        self.columns_button.setToolTip(tr(
            "Columns: show or hide the active layer, isolate, colour, line "
            "type, line weight and count"))
        self.columns_button.clicked.connect(self._open_columns_menu)
        self._sort = (COL_NAME, Qt.AscendingOrder)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked
                                  | QAbstractItemView.EditKeyPressed)
        # Sorted by hand: a click on the eye or padlock header acts on every
        # layer (the Browser's rule), the other headers sort.
        self.tree.setSortingEnabled(False)
        # Qt makes the header unclickable when sorting is switched off:
        # clickable again, or the eye and padlock headers do nothing.
        head.setSectionsClickable(True)
        self.tree.sortItems(COL_NAME, Qt.AscendingOrder)
        self.tree.itemChanged.connect(self._on_item_changed)
        names = _HoldsDelegate(self.tree)
        self.tree.setItemDelegateForColumn(COL_NAME, names)
        self.tree.setItemDelegateForColumn(COL_LINETYPE,
                                           _LineDelegate(self.tree))
        #: The row just made, ``(kind, name)``, until its name is typed.
        self._just_made = None
        names.closeEditor.connect(
            lambda *_a: QTimer.singleShot(0, self._select_just_made))
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemCollapsed.connect(self._on_collapsed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        lay.addWidget(self.tree, 1)

        # No row of buttons under the list (the Browser has none): delete
        # is the Delete key and the right-click menu, assigning is the
        # Layers toolbar's drop-down and the right-click menu.

        self._count_timer = QTimer(self)
        self._count_timer.setSingleShot(True)
        self._count_timer.timeout.connect(self.update_counts)
        # Back in the drawing, the rows picked here let go: a highlighted
        # row left behind reads as a layer still being worked on.
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        self._apply_column_choice()
        self.refresh()

    def _in_model(self, widget) -> bool:
        """Whether ``widget`` is the drawing (or inside it)."""
        vp = getattr(self._window, "viewport", None)
        if vp is None or widget is None:
            return False
        return widget is vp or vp.isAncestorOf(widget)

    def _on_focus_changed(self, _old, new) -> None:
        try:
            if self._in_model(new):
                self.tree.clearSelection()
        except RuntimeError:                 # the panel is being torn down
            pass

    @staticmethod
    def _tool_button(icon, tip: str, slot) -> QToolButton:
        btn = QToolButton()
        btn.setIcon(icon)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        btn.clicked.connect(slot)
        return btn

    # ---- Model → view --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    @staticmethod
    def _key(item):
        return item.data(COL_NAME, Qt.UserRole) or (KIND_LAYER, "")

    def refresh(self) -> None:
        """Rebuild the tree from the document, keeping the selection, the
        folded folders and the filter; the counts follow a moment later
        (one walk of the model, not one per edit)."""
        scene = self._scene()
        selected = {self._key(it) for it in self.tree.selectedItems()}
        current = self.tree.currentItem()
        current_key = self._key(current) if current is not None else None
        self._updating = True
        self.tree.clear()
        folders = {}
        for order, name in enumerate(L.folders_of(scene)):
            item = _Row([name])
            item.setData(COL_NAME, Qt.UserRole, (KIND_FOLDER, name))
            item.setData(COL_NAME, ROLE_ORDER, order)
            item.setIcon(COL_NAME, node_icon("folder"))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            folders[name] = item
        for name, item in folders.items():
            parent = folders.get(L.folder_parent(scene, name))
            if parent is not None:
                parent.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
        active = L.active_layer(scene)
        self._alone = self.isolated_layers()         # whose target is filled
        for order, ly in enumerate(scene.layers):
            item = _Row([ly.name])
            item.setData(COL_NAME, Qt.UserRole, (KIND_LAYER, ly.name))
            item.setData(COL_NAME, ROLE_ORDER, order)
            if ly.name != L.DEFAULT_LAYER:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            self._paint_layer_row(item, ly, ly.name == active)
            parent = folders.get(ly.folder)
            if parent is not None:
                parent.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
        for name, item in folders.items():
            self._paint_folder_row(item)
            item.setExpanded(name not in self._collapsed)
        self._mark_selection()
        for it in self._all_items():
            key = self._key(it)
            if key in selected:
                it.setSelected(True)
            if key == current_key:
                self.tree.setCurrentItem(it, 0, QItemSelectionModel.NoUpdate)
        col, order = getattr(self, "_sort", (COL_NAME, Qt.AscendingOrder))
        self.tree.sortItems(col, order)
        self._apply_filter()
        self._update_expand_button()
        style = getattr(scene, "display_style", None)
        self.color_by_layer.blockSignals(True)
        self.color_by_layer.setChecked(bool(getattr(style, "color_by_layer",
                                                    False)))
        self.color_by_layer.blockSignals(False)
        self._updating = False
        self._drawn_signature = self._signature()
        self._count_timer.start(300)

    def refresh_pencil_icons(self) -> None:
        """Repaint the active marks after the theme or accent changes."""
        self.tree.headerItem().setIcon(COL_ACTIVE, _pencil_icon(True))
        active = L.active_layer(self._scene())
        for item in self._all_items():
            kind, name = self._key(item)
            if kind == KIND_LAYER:
                item.setIcon(COL_ACTIVE, _pencil_icon(name == active))

    #: Column order on screen (logical columns), and the indent per level —
    #: the Browser's.
    COLUMN_ORDER = (COL_EYE, COL_LOCK, COL_ISOLATE, COL_NAME, COL_ACTIVE,
                    COL_COLOR, COL_LINETYPE, COL_WEIGHT, COL_OPACITY,
                    COL_PRINT, COL_COUNT)
    INDENT = 12

    def _on_header_clicked(self, col: int) -> None:
        """Eye or padlock header: every layer shown or hidden, locked or
        unlocked (all of them hidden or locked → all back). Any other
        header: sort by it, twice to turn the order."""
        scene = self._scene()
        names = [ly.name for ly in scene.layers]
        if col == COL_EYE:
            self.set_visible(names, not all(ly.visible for ly in scene.layers))
            return
        if col == COL_LOCK:
            self.set_locked(names, not all(ly.locked for ly in scene.layers))
            return
        if col == COL_ISOLATE:
            self.exit_isolation()
            return
        if col == COL_PRINT:
            self.set_printable(names, not all(
                getattr(ly, "printable", True) for ly in scene.layers))
            return
        old_col, old_order = self._sort
        order = (Qt.DescendingOrder if (old_col == col
                                        and old_order == Qt.AscendingOrder)
                 else Qt.AscendingOrder)
        self._sort = (col, order)
        self.tree.sortItems(col, order)

    # ---- Isolate (the target column) -------------------------------------------
    def _isolated_now(self) -> list[str]:
        """What Isolate hid and is still hidden."""
        scene = self._scene()
        return [n for n in self._isolated
                if scene.layer(n) is not None and not scene.layer(n).visible]

    def isolated_layers(self) -> set[str]:
        """The layers shown alone just now — by Isolate here or on the
        toolbar, or one layer left on its own however it came to be."""
        scene = self._scene()
        if self._isolated_now():
            return {ly.name for ly in scene.layers
                    if ly.visible and ly.name != L.DEFAULT_LAYER}
        return {ly.name for ly in scene.layers
                if L.is_isolated(scene, ly.name)}

    def toggle_isolate(self, names) -> None:
        """A click on a target: show only ``names``; on the ones already
        shown alone, end the isolation instead."""
        names = [n for n in names if n != L.DEFAULT_LAYER
                 and self._scene().layer(n) is not None]
        if not names:
            return
        if set(names) <= self.isolated_layers():
            self.exit_isolation()
        else:
            self.isolate(names)

    def exit_isolation(self) -> None:
        """Show again exactly what Isolate hid; a layer hidden by hand
        before isolating stays hidden. Isolated some other way (nothing
        remembered): every layer back."""
        back = self._isolated_now()
        self._isolated = []
        if back:
            self.set_visible(back, True)
        elif self.isolated_layers():
            self.show_all()
        else:
            self.refresh()

    # ---- ⊞ expand / ⊟ collapse ----------------------------------------------------
    def _folders_all_open(self) -> bool:
        return all(it.isExpanded() for it in self._all_items()
                   if self._key(it)[0] == KIND_FOLDER)

    def _update_expand_button(self) -> None:
        b = getattr(self, "expand_btn", None)
        if b is None:
            return
        has = any(self._key(it)[0] == KIND_FOLDER for it in self._all_items())
        b.setEnabled(has)
        opened = has and self._folders_all_open()
        from views.icons import tool_icon
        b.setIcon(tool_icon("layers_collapse" if opened
                            else "layers_expand"))
        b.setProperty("opened", opened)
        b.setToolTip(tr("Collapse all") if opened else tr("Expand all"))

    def _expand_or_collapse(self) -> None:
        open_ = not self._folders_all_open()
        for it in self._all_items():
            if self._key(it)[0] == KIND_FOLDER:
                it.setExpanded(open_)
        self._update_expand_button()

    def _on_expanded(self, item) -> None:
        self._collapsed.discard(self._key(item)[1])
        if not self._updating:
            self._mark_selection()
            self._update_expand_button()

    def _on_collapsed(self, item) -> None:
        self._collapsed.add(self._key(item)[1])
        if not self._updating:
            self._mark_selection()
            self._update_expand_button()

    def _mark_selection(self) -> None:
        """Tint the rows of the layers what is selected sits on — every one
        of them when it spans several — and a folded folder holding one, so
        the mark is always in view. Nothing selected: no mark. It never
        changes the active layer: what you draw next stays where it was."""
        from PySide6.QtWidgets import QApplication
        names = L.selection_layers(self._scene())
        tint = QColor(QApplication.palette().highlight().color())
        tint.setAlpha(55)
        was = self._updating
        self._updating = True
        marked = set()
        for it in self._all_items():
            kind, name = self._key(it)
            if kind == KIND_LAYER and name in names:
                marked.add(id(it))
                parent = it.parent()
                while parent is not None:
                    if not parent.isExpanded():
                        marked.add(id(parent))
                    parent = parent.parent()
        for it in self._all_items():
            on = id(it) in marked
            it.setData(COL_NAME, ROLE_HOLDS, on)
            for col in range(self.tree.columnCount()):
                it.setBackground(col, QBrush(tint) if on else QBrush())
        self._updating = was

    def _paint_layer_row(self, item, ly, active: bool) -> None:
        item.setIcon(COL_ACTIVE, _pencil_icon(active))
        item.setToolTip(COL_ACTIVE, tr("Active layer") if active
                        else tr("Make this the active layer"))
        item.setIcon(COL_EYE, node_icon("eye" if ly.visible else "eye_off"))
        item.setData(COL_EYE, Qt.UserRole + 1, int(ly.visible))
        item.setIcon(COL_LOCK, node_icon("lock" if ly.locked else "lock_open"))
        item.setData(COL_LOCK, Qt.UserRole + 1, int(ly.locked))
        item.setIcon(COL_COLOR, layer_swatch(ly))
        item.setToolTip(COL_COLOR, tr("Click to pick the layer's colour"))
        keys = [k for k, _l in self.LINETYPE_LABELS]
        label = dict(self.LINETYPE_LABELS).get(ly.linetype, "Continuous")
        item.setData(COL_LINETYPE, ROLE_LINETYPE, ly.linetype)
        item.setData(COL_LINETYPE, Qt.UserRole + 1,
                     keys.index(ly.linetype) if ly.linetype in keys else 0)
        item.setToolTip(COL_LINETYPE, tr(label))
        weight = ly.lineweight
        item.setText(COL_WEIGHT, "—" if weight is None else f"{weight:.2f}")
        item.setTextAlignment(COL_WEIGHT, Qt.AlignCenter)
        item.setData(COL_WEIGHT, Qt.UserRole + 1,
                     -1.0 if weight is None else float(weight))
        item.setToolTip(COL_WEIGHT, tr("Default (from the sheet)") if weight is None
                        else f"{weight:.2f} mm")
        printed = getattr(ly, "printable", True)
        item.setIcon(COL_PRINT, printer_icon(printed))
        item.setData(COL_PRINT, Qt.UserRole + 1, int(printed))
        item.setToolTip(COL_PRINT, tr("On the sheets — click to leave it "
                                      "out of them") if printed else
                        tr("Not printed: seen in the model, left out of the "
                           "sheets — click to print it"))
        clear = round((1.0 - ly.opacity) * 100)
        item.setText(COL_OPACITY, f"{clear} %" if clear else "—")
        item.setTextAlignment(COL_OPACITY, Qt.AlignCenter)
        item.setData(COL_OPACITY, Qt.UserRole + 1, clear)
        item.setToolTip(COL_OPACITY, tr("Opaque") if not clear else
                        f"{tr('Transparency')} {clear} %")
        if ly.name != L.DEFAULT_LAYER:              # always on: no target
            from views.layers_toolbar import isolate_icon
            alone = ly.name in self._alone
            item.setIcon(COL_ISOLATE, isolate_icon(alone))
            item.setToolTip(COL_ISOLATE, tr(
                "Shown alone — click to show back what Isolate hid")
                if alone else tr("Isolate: show only this layer"))
        # What no column shows, on the name: the folder — and the
        # transparency while its column is off.
        look = []
        if ly.opacity < 1.0 and self.tree.isColumnHidden(COL_OPACITY):
            look.append(f"{tr('Transparency')} {round((1 - ly.opacity) * 100)} %")
        if ly.folder:
            look.append(ly.folder)
        item.setToolTip(COL_NAME, "\n".join([ly.name, " · ".join(look)])
                        if look else ly.name)
        if ly.name in self._counts:
            self._set_count(item, self._counts[ly.name])

    def _paint_folder_row(self, item) -> None:
        scene = self._scene()
        layers = [scene.layer(n)
                  for n in L.layers_in_folder(scene, self._key(item)[1])]
        layers = [ly for ly in layers if ly is not None]
        shown = any(ly.visible for ly in layers) or not layers
        locked = bool(layers) and all(ly.locked for ly in layers)
        item.setIcon(COL_EYE, node_icon("eye" if shown else "eye_off"))
        item.setIcon(COL_LOCK, node_icon("lock" if locked else "lock_open"))
        item.setToolTip(COL_EYE, tr("Show or hide every layer in the folder"))
        printed = (not layers
                   or any(getattr(ly, "printable", True) for ly in layers))
        item.setIcon(COL_PRINT, printer_icon(printed))
        from views.layers_toolbar import isolate_icon
        names = {ly.name for ly in layers} - {L.DEFAULT_LAYER}
        alone = bool(names) and names == self._alone
        item.setIcon(COL_ISOLATE, isolate_icon(alone))
        item.setToolTip(COL_ISOLATE, tr(
            "Shown alone — click to show back what Isolate hid")
            if alone else tr("Isolate: show only the layers in this folder"))

    @staticmethod
    def _set_count(item, n: int) -> None:
        item.setText(COL_COUNT, str(n))
        item.setData(COL_COUNT, Qt.UserRole + 1, n)
        item.setTextAlignment(COL_COUNT, Qt.AlignRight | Qt.AlignVCenter)

    def update_counts(self) -> None:
        """How many entities carry each layer — faces, edges, objects and
        annotations, inside groups too."""
        from core.purge import layer_counts
        scene = self._scene()
        self._counted_version = scene.content_version
        counts = layer_counts(scene)
        self._counts = counts
        self._updating = True
        for it in self._all_items():
            kind, name = self._key(it)
            if kind == KIND_LAYER:
                self._set_count(it, counts.get(name, 0))
        self._updating = False

    def _all_items(self):
        """Every row, folders inside folders included, depth first."""
        out = []

        def walk(item):
            out.append(item)
            for c in self._children(item):
                walk(c)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    @staticmethod
    def _children(item):
        return [item.child(i) for i in range(item.childCount())]

    def item_for(self, name: str, kind: str = KIND_LAYER):
        return next((it for it in self._all_items()
                     if self._key(it) == (kind, name)), None)

    #: The quick filters of the funnel, in menu order: (key, label, tip).
    STATE_FILTERS = (
        ("all", "All layers", ""),
        ("visible", "Visible layers", ""),
        ("hidden", "Hidden layers", ""),
        ("locked", "Locked layers", ""),
        ("unprinted", "Layers not printed",
         "Seen in the model, left out of the sheets."),
        ("used", "Layers in use", "Layers something in the model carries."),
        ("unused", "Unused layers", "What Purge would delete."),
        ("selection", "Layers of the selection",
         "The layers of what is selected in the model."),
    )

    def _fill_filter_menu(self) -> None:
        from PySide6.QtGui import QActionGroup
        menu = self.filter_menu
        menu.clear()
        group = QActionGroup(menu)
        group.setExclusive(True)
        for key, label, tip in self.STATE_FILTERS:
            act = menu.addAction(tr(label))
            act.setCheckable(True)
            act.setChecked(self.state_filter == key)
            if tip:
                act.setStatusTip(tr(tip))
                act.setToolTip(tr(tip))
            group.addAction(act)
            act.triggered.connect(lambda _c=False, k=key:
                                  self.set_state_filter(k))
        menu.addSeparator()
        inv = menu.addAction(tr("Invert filter"))
        inv.setCheckable(True)
        inv.setChecked(self.invert_filter)
        inv.setStatusTip(tr("Show the layers the filter leaves out."))
        inv.toggled.connect(self.set_invert_filter)

    def set_state_filter(self, key: str) -> None:
        self.state_filter = key if key in dict(
            (k, k) for k, _l, _t in self.STATE_FILTERS) else "all"
        self._show_filter_state()
        self._apply_filter()

    def set_invert_filter(self, on: bool) -> None:
        self.invert_filter = bool(on)
        self._show_filter_state()
        self._apply_filter()

    def _show_filter_state(self) -> None:
        """The funnel fills when a filter is narrowing the list, and its
        tooltip says which."""
        from views.icons import tool_icon
        on = self.state_filter != "all" or self.invert_filter
        self.filter_btn.setIcon(tool_icon("layers_filter_on" if on
                                          else "layers_filter"))
        label = dict((k, l) for k, l, _t in self.STATE_FILTERS)[
            self.state_filter]
        tip = tr("Filter: {name}", name=tr(label))
        if self.invert_filter:
            tip += " · " + tr("inverted")
        self.filter_btn.setToolTip(tip)

    @staticmethod
    def _name_matches(name: str, text: str) -> bool:
        """The search: a plain text is looked for anywhere in the name; with
        ``*`` or ``?`` it is a pattern for the whole name (``A-*``,
        ``*MUR*``) — the names an imported drawing brings by the hundred."""
        if not text:
            return True
        name = name.casefold()
        if "*" in text or "?" in text:
            import fnmatch
            return fnmatch.fnmatchcase(name, text)
        return text in name

    def _state_test(self):
        """``name -> bool`` for the funnel's filter (``None``: no filter)."""
        scene = self._scene()
        key = self.state_filter
        if key == "all":
            return None
        if key in ("visible", "hidden", "locked", "unprinted"):
            def test(name):
                ly = scene.layer(name)
                if ly is None:
                    return False
                return (ly.visible if key == "visible" else
                        not ly.visible if key == "hidden" else
                        not getattr(ly, "printable", True)
                        if key == "unprinted" else ly.locked)
            return test
        if key == "selection":
            names = L.selection_layers(scene)
        elif key == "used":
            from core.purge import used_layers
            names = used_layers(scene)
        else:
            from core.purge import unused_layers
            names = {ly.name for ly in unused_layers(scene)}
        return lambda name: name in names

    def _apply_filter(self) -> None:
        """Layer rows that pass the search text and the funnel's filter stay
        — or, inverted, the ones that do not — with the folders on the way
        to them. A folder whose name matches the search shows all it holds
        (with no state filter and not inverted: then it is the folder you
        were looking for)."""
        text = self.search.text().strip().casefold()
        state = self._state_test()
        invert = self.invert_filter

        def layer_ok(name: str) -> bool:
            ok = self._name_matches(name, text) and (state is None
                                                      or state(name))
            return ok != invert

        whole = bool(text) and state is None and not invert
        # No filter at all: every row shows — an empty folder too, which
        # has no layer to be shown through (a new folder was invisible).
        nothing = not text and state is None and not invert

        def show(item, inherited: bool) -> bool:
            kind, name = self._key(item)
            if kind == KIND_LAYER:
                visible = nothing or inherited or layer_ok(name)
            else:
                opens = whole and self._name_matches(name, text)
                kids = [show(c, inherited or opens)
                        for c in self._children(item)]
                visible = nothing or inherited or opens or any(kids)
            item.setHidden(not visible)
            return visible

        for i in range(self.tree.topLevelItemCount()):
            show(self.tree.topLevelItem(i), False)

    # ---- Selection helpers ---------------------------------------------------
    def _layers_under(self, items) -> list[str]:
        """Layer names of the rows ``items`` — a folder row stands for every
        layer in it — in order, each once."""
        out: list[str] = []
        for it in items:
            kind, name = self._key(it)
            names = (L.layers_in_folder(self._scene(), name)
                     if kind == KIND_FOLDER else [name])
            for n in names:
                if n not in out:
                    out.append(n)
        return out

    def _targets(self, item) -> list[str]:
        """The rows a click on ``item`` acts on: every selected row when
        it is one of them, else just it."""
        selected = self.tree.selectedItems()
        return self._layers_under(selected if item in selected else [item])

    def selected_layers(self) -> list[str]:
        return [n for n in self._layers_under(self.tree.selectedItems())]

    # ---- View → model --------------------------------------------------------
    def _touch(self, rebuild: bool = True) -> None:
        scene = self._scene()
        scene.version += 1
        if rebuild:
            self.refresh()
        self._window.viewport.notify_scene_changed()

    def _released(self, released: bool) -> None:
        if released:
            self._window.statusBar().showMessage(tr(
                "The active layer is hidden or locked: new objects go to "
                "'{default}' again.", default=L.DEFAULT_LAYER), 4000)

    def _on_item_clicked(self, item, column) -> None:
        """A click on one of the cells, for code and tests: the tree itself
        acts on the press (:meth:`_LayerTree.mousePressEvent`). The action
        runs once Qt is done: it rebuilds the tree."""
        if self._updating or column == COL_NAME or column == COL_COUNT:
            return
        key, targets = self._key(item), self._targets(item)
        QTimer.singleShot(0, lambda: self.click_cell(key, column, targets))

    def click_cell(self, key, column, targets=None) -> None:
        """What a click on ``column`` of the row ``key`` (kind, name) does:
        make active, show or hide, lock or unlock (``targets``: every
        selected row when the clicked one is among them), pick the colour."""
        kind, name = key
        if targets is None:
            item = self.item_for(name, kind)
            targets = self._targets(item) if item is not None else [name]
        scene = self._scene()
        if column == COL_ACTIVE and kind == KIND_LAYER:
            self.set_active(name)
        elif column in (COL_EYE, COL_LOCK):
            names = targets
            layers =[scene.layer(n) for n in names if scene.layer(n)]
            if not layers:
                return
            # The row clicked decides: its state flips, and every target
            # follows it (a folder reads as shown while any layer in it is).
            clicked = scene.layer(name) if kind == KIND_LAYER else None
            if column == COL_EYE:
                now = (clicked.visible if clicked is not None
                       else any(ly.visible for ly in layers))
                self.set_visible(names, not now)
            else:
                now = (clicked.locked if clicked is not None
                       else all(ly.locked for ly in layers))
                self.set_locked(names, not now)
        elif column == COL_ISOLATE:
            self.toggle_isolate(targets)
        elif column == COL_PRINT:
            layers = [scene.layer(n) for n in targets if scene.layer(n)]
            if layers:
                clicked = scene.layer(name) if kind == KIND_LAYER else None
                now = (getattr(clicked, "printable", True) if clicked
                       else any(getattr(ly, "printable", True)
                                for ly in layers))
                self.set_printable(targets, not now)
        elif column == COL_COLOR and kind == KIND_LAYER:
            self.pick_color(targets)
        elif (column in (COL_LINETYPE, COL_WEIGHT, COL_OPACITY)
              and kind == KIND_LAYER):
            self._cell_menu(name, column, targets)

    def _cell_menu(self, name: str, column: int, targets) -> None:
        """The line type, line weight or transparency list, dropped under
        the clicked cell; the pick goes to every target row."""
        item = self.item_for(name)
        ly = self._scene().layer(name)
        if item is None or ly is None:
            return
        menu = QMenu(self)
        if column == COL_LINETYPE:
            self._fill_linetypes(menu, targets, ly)
        elif column == COL_WEIGHT:
            self._fill_weights(menu, targets, ly)
        else:
            self._fill_opacities(menu, targets, ly)
        from PySide6.QtCore import QRect
        row = self.tree.visualItemRect(item)
        cell = QRect(self.tree.columnViewportPosition(column), row.top(),
                     self.tree.columnWidth(column), row.height())
        self._drop(menu, global_rect(self.tree.viewport(), cell))

    @staticmethod
    def _popup(menu, at) -> None:
        """Run ``menu`` at ``at`` (global) — one place, so a test can stand
        in for the modal loop."""
        menu.exec(at)

    # ---- Menus dropped from the panel --------------------------------------
    def _drop(self, menu, anchor) -> None:
        """Open ``menu`` under ``anchor`` (a global QRect), kept inside the
        panel."""
        self._popup(menu, place_menu(menu, anchor, global_rect(self)))

    def _open_filter_menu(self) -> None:
        self._fill_filter_menu()
        self._drop(self.filter_menu, global_rect(self.filter_btn))

    def _open_more_menu(self) -> None:
        self._fill_more_menu()
        self._drop(self.more_menu, global_rect(self.more_btn))

    # ---- Which columns show ------------------------------------------------
    #: The columns that can be switched off (eye, padlock and name stay).
    OPTIONAL_COLUMNS = ((COL_ACTIVE, "Active layer"), (COL_ISOLATE, "Isolate"),
                        (COL_COLOR, "Colour"), (COL_LINETYPE, "Line type"),
                        (COL_WEIGHT, "Line weight"),
                        (COL_OPACITY, "Transparency"),
                        (COL_PRINT, "Print"),
                        (COL_COUNT, "Entities on the layer"))
    #: QSettings key of the columns switched off.
    HIDDEN_COLUMNS_KEY = "layers/hidden_columns"

    #: Off until asked for — what is set now and then, not looked at every
    #: day: the line weight (set once per layer, and only seen on sheets),
    #: the print mark (a few reference layers, once per project),
    #: transparency (a viewing aid) and the count (it adds faces, edges and
    #: objects up, a number that mostly says «empty or not» — which the
    #: filter and Purge say already). The name keeps room to be read.
    DEFAULT_HIDDEN = (COL_WEIGHT, COL_PRINT, COL_OPACITY, COL_COUNT)

    def hidden_columns(self) -> set[int]:
        from PySide6.QtCore import QSettings
        settings = QSettings()
        if not settings.contains(self.HIDDEN_COLUMNS_KEY):
            return set(self.DEFAULT_HIDDEN)
        raw = settings.value(self.HIDDEN_COLUMNS_KEY, "") or ""
        if isinstance(raw, (list, tuple)):
            raw = ",".join(str(v) for v in raw)
        optional = {c for c, _l in self.OPTIONAL_COLUMNS}
        return {int(v) for v in str(raw).split(",")
                if v.strip().isdigit() and int(v) in optional}

    def set_column_shown(self, col: int, on: bool) -> None:
        from PySide6.QtCore import QSettings
        hidden = self.hidden_columns()
        if on:
            hidden.discard(col)
        else:
            hidden.add(col)
        QSettings().setValue(self.HIDDEN_COLUMNS_KEY,
                             ",".join(str(c) for c in sorted(hidden)))
        self._apply_column_choice()
        self.refresh()                  # the name's tooltip follows the choice

    def _apply_column_choice(self) -> None:
        hidden = self.hidden_columns()
        for col, _label in self.OPTIONAL_COLUMNS:
            self.tree.setColumnHidden(col, col in hidden)
        self._place_columns_button()

    #: QSettings key of the rows' order: by name or as they were made.
    SORT_KEY = "layers/sort_by"

    @property
    def sort_by(self) -> str:
        from PySide6.QtCore import QSettings
        v = str(QSettings().value(self.SORT_KEY, "name") or "name")
        return v if v in ("name", "created") else "name"

    def set_sort_by(self, how: str) -> None:
        """Order the rows by name (numbers read as numbers) or in the order
        they were made — Layer 0 first and folders before layers either
        way; remembered."""
        from PySide6.QtCore import QSettings
        QSettings().setValue(self.SORT_KEY,
                             how if how in ("name", "created") else "name")
        self._sort = (COL_NAME, Qt.AscendingOrder)
        self.refresh()

    def _columns_menu(self):
        """Which columns show. It stays open while columns are switched —
        several in one go; «Show all columns» turns every one on and
        «Default columns» puts the daily set back."""
        menu = _StayOpenMenu(self)
        hidden = self.hidden_columns()
        show_all = menu.addAction(tr("Show all columns"))
        show_all.setProperty("keep_open", True)
        menu.addSeparator()
        switches = []
        for col, label in self.OPTIONAL_COLUMNS:
            act = menu.addAction(tr(label))
            act.setCheckable(True)
            act.setChecked(col not in hidden)
            act.toggled.connect(lambda on, c=col: self.set_column_shown(c, on))
            switches.append(act)
        # Back to the starting point: last, apart, as a «reset» goes.
        menu.addSeparator()
        defaults = menu.addAction(tr("Default columns"))
        defaults.setProperty("keep_open", True)

        def all_on() -> None:
            for act in switches:
                act.setChecked(True)             # each switch applies itself
        show_all.triggered.connect(all_on)

        def back_to_defaults() -> None:
            for (col, _label), act in zip(self.OPTIONAL_COLUMNS, switches):
                act.setChecked(col not in self.DEFAULT_HIDDEN)
        defaults.triggered.connect(back_to_defaults)
        return menu

    def _open_columns_menu(self) -> None:
        self._drop(self._columns_menu(), global_rect(self.columns_button))

    def _place_columns_button(self) -> None:
        """At the header's right end, as tall as it; «+N» while N columns
        are off, «⋮» when none — as in the Browser."""
        b = getattr(self, "columns_button", None)
        if b is None:
            return
        head = self.tree.header()
        n = len(self.hidden_columns())
        b.setText(f"+{n}" if n else "⋮")
        font = b.font()
        font.setBold(bool(n))
        b.setFont(font)
        side = max(head.sizeHint().height(), 18)
        width = max(side, b.sizeHint().width())
        b.resize(width, side)
        if self.tree.button_strip != width:
            self.tree.button_strip = width
        self.tree.updateGeometries()
        b.raise_()

    #: How many layer states «Previous layer state» can go back through.
    PREVIOUS_DEPTH = 20

    def _remember(self) -> None:
        """Keep the layers' state before a change to it (visibility, lock,
        active layer), for «Previous layer state»."""
        stack = self.__dict__.setdefault("_previous", [])
        stack.append(L.layer_state(self._scene()))
        del stack[:-self.PREVIOUS_DEPTH]

    def previous_state(self) -> bool:
        """Back to the layers' state before the last change made here or
        from the Layers toolbar — visibility, lock and active layer, not
        the geometry (that is Ctrl+Z's). False when there is none."""
        stack = self.__dict__.get("_previous") or []
        if not stack:
            self._window.statusBar().showMessage(
                tr("No earlier layer state."), 2500)
            return False
        L.apply_layer_state(self._scene(), stack.pop())
        self._touch()
        self._window.statusBar().showMessage(
            tr("Previous layer state restored."), 2500)
        return True

    def set_active(self, name: str | None) -> None:
        self._remember()
        L.set_active(self._scene(), name)
        self._touch()
        self._window.statusBar().showMessage(tr(
            "Active layer: '{layer}'", layer=L.active_layer(self._scene())),
            2500)

    def set_visible(self, names, on: bool) -> None:
        self._remember()
        scene = self._scene()
        released = L.set_visible(scene, names, on)
        if not on:
            self._prune_selection(names)
        self._released(released)
        self._touch()

    def set_locked(self, names, on: bool) -> None:
        self._remember()
        scene = self._scene()
        released = L.set_locked(scene, names, on)
        if on:
            self._prune_selection(names)
        self._released(released)
        self._touch()

    def isolate(self, names) -> None:
        """Show only ``names`` (and the default layer); what this hid is
        remembered, so ◉ shows back exactly that."""
        self._remember()
        scene = self._scene()
        keep = set(names) | {L.DEFAULT_LAYER}
        # Isolating another layer while isolated: the way out still shows
        # back everything the first Isolate hid, not only the last one.
        self._isolated = list(dict.fromkeys(
            self._isolated_now() + [ly.name for ly in scene.layers
                                    if ly.visible and ly.name not in keep]))
        released = L.isolate(scene, names)
        self._prune_selection([ly.name for ly in scene.layers
                               if not ly.visible])
        self._released(released)
        self._touch()

    def show_all(self) -> None:
        self.set_visible([ly.name for ly in self._scene().layers], True)

    def pick_color(self, names) -> None:
        """Pick one colour for the layers ``names`` (one name or several —
        every selected row takes it)."""
        from views.color_dialog import get_color
        names = [names] if isinstance(names, str) else list(names)
        scene = self._scene()
        layers = [scene.layer(n) for n in names if scene.layer(n)]
        if not layers:
            return
        color = get_color(QColor.fromRgbF(*L.layer_color(layers[0])), self,
                          tr("Layer colour"))
        if not color.isValid():
            return
        self.set_color(names, (color.redF(), color.greenF(), color.blueF()))

    def set_color(self, names, rgb) -> None:
        """The colour of the layers ``names`` (``None``: automatic)."""
        names = [names] if isinstance(names, str) else list(names)
        scene = self._scene()
        for name in names:
            ly = scene.layer(name)
            if ly is not None:
                ly.color = (tuple(float(c) for c in rgb[:3]) if rgb
                            else None)
        self._dirty_paint()
        self._touch()

    def set_color_by_layer(self, on: bool) -> None:
        """Paint the model by layer, or by material again. A setting of the
        STYLE, so the scenes saved with it remember it."""
        style = getattr(self._scene(), "display_style", None)
        if style is None or bool(style.color_by_layer) == bool(on):
            return
        style.color_by_layer = bool(on)
        self._dirty_paint()
        self._touch(rebuild=False)
        if on and style.face_mode not in ("textures", "shaded", "xray"):
            self._window.statusBar().showMessage(tr(
                "Colour by layer shows in the shaded, textured and X-ray "
                "styles."), 4000)

    def _dirty_paint(self) -> None:
        from core.history import _dirty_group_chunks
        _dirty_group_chunks(self._scene())

    def _prune_selection(self, names) -> None:
        names = set(names)
        scene = self._scene()
        for s in [s for s in scene.selection if L.layer_of(s) in names]:
            scene.selection.discard(s)

    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != COL_NAME:
            return
        kind, old = self._key(item)
        new = item.text(COL_NAME).strip()
        scene = self._scene()
        if new and new != old and self._just_made == (kind, old):
            self._just_made = (kind, new)
        if new and new != old:
            if kind == KIND_FOLDER:
                if old in self._collapsed:
                    self._collapsed.discard(old)
                    self._collapsed.add(new)
                L.rename_folder(scene, old, new)
            else:
                L.rename_layer(scene, old, new)
        QTimer.singleShot(0, self._touch)       # not while the editor closes

    #: QSettings key of «New layers start hidden in the existing scenes».
    NEW_HIDDEN_KEY = "layers/new_hidden_in_scenes"

    @classmethod
    def new_layers_hidden_in_scenes(cls) -> bool:
        from PySide6.QtCore import QSettings
        return str(QSettings().value(cls.NEW_HIDDEN_KEY, "false")).lower() \
            in ("true", "1")

    @classmethod
    def set_new_layers_hidden_in_scenes(cls, on: bool) -> None:
        from PySide6.QtCore import QSettings
        QSettings().setValue(cls.NEW_HIDDEN_KEY, bool(on))

    def _selected_folder(self) -> str | None:
        """The folder new things go into: the highlighted row when it is a
        selected folder, the folder of a selected layer, else none (the
        top) — working in «Arquitectura», a new layer lands there too."""
        item = self.tree.currentItem()
        if item is None or not item.isSelected():
            return None
        kind, name = self._key(item)
        if kind == KIND_FOLDER:
            return name
        ly = self._scene().layer(name)
        return ly.folder if ly is not None and ly.folder else None

    def add_layer(self, folder: str | None = None, edit: bool = True) -> str:
        """A new layer — inside the selected folder, or ``folder`` — with
        its name open for typing. Returns its name."""
        scene = self._scene()
        folder = folder or self._selected_folder()
        name = L.unique_name([ly.name for ly in scene.layers], tr("Layer"))
        scene.layers.append(L.Layer(name, folder=folder or None))
        # A layer made after the plans were set up stays out of them.
        if self.new_layers_hidden_in_scenes():
            L.hide_in_scenes(scene, [name], True)
        self._touch()
        self._edit_new(KIND_LAYER, name, edit)
        return name

    def add_folder(self, parent: str | None = None, edit: bool = True) -> str:
        """A new folder — inside the selected folder, or ``parent`` — with
        its name open for typing. Returns its name."""
        scene = self._scene()
        parent = parent or self._selected_folder()
        name = L.add_folder(scene, tr("Folder"), parent)
        self._touch()
        self._edit_new(KIND_FOLDER, name, edit)
        return name

    def _edit_new(self, kind: str, name: str, edit: bool) -> None:
        item = self.item_for(name, kind)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:                   # in view, unfolded
            parent.setExpanded(True)
            parent = parent.parent()
        # Current but NOT selected: with the name being typed, a selected
        # row showed the highlight broken around the editor — half the
        # row lit, the cells under the editor not.
        self.tree.clearSelection()
        self.tree.setCurrentItem(item, COL_NAME, QItemSelectionModel.NoUpdate)
        self.tree.scrollToItem(item)
        if edit:
            self._just_made = (kind, name)
            self.tree.editItem(item, COL_NAME)

    def _select_just_made(self) -> None:
        """Its name typed, the new row is selected — whole, the editor gone
        — so a layer added next goes into a folder just made."""
        made, self._just_made = self._just_made, None
        if made is None or self._in_model(QApplication.focusWidget()):
            return             # the name was left by clicking the model
        item = self.item_for(made[1], made[0])
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)     # resorted by its name: still seen

    # The names the old buttons and menus call.
    def _on_add(self, folder: str | None = None) -> None:
        self.add_layer(folder or None)

    def _on_add_folder(self) -> None:
        self.add_folder()

    def move_to_folder(self, names, folder: str | None) -> None:
        L.move_to_folder(self._scene(), names, folder)
        self._touch()

    def drop_rows(self, rows, folder: str | None) -> None:
        """File the dragged rows — ``(kind, name)`` pairs — into ``folder``
        (``None``: out of any folder). A layer inside a dragged folder
        travels with its folder; the default layer never goes in one; a
        folder will not go into itself or into a folder inside it."""
        scene = self._scene()
        folders = [n for k, n in rows if k == KIND_FOLDER]
        inside = set(folders)
        for f in folders:
            inside.update(L.subfolders(scene, f, deep=True))
        layers = [n for k, n in rows if k == KIND_LAYER
                  and n != L.DEFAULT_LAYER
                  and scene.layer(n) is not None
                  and scene.layer(n).folder not in inside]
        moved = 0
        for f in folders:
            if f != folder and L.move_folder(scene, f, folder):
                moved += 1
        if layers:
            L.move_to_folder(scene, layers, folder)
            moved += len(layers)
        if folder:
            self._collapsed.discard(folder)          # show where they went
        self._touch()
        if moved:
            self._window.statusBar().showMessage(
                tr("{n} moved to '{folder}'", n=moved, folder=folder)
                if folder else tr("{n} moved out of any folder", n=moved),
                2500)

    def move_folder(self, name: str, parent: str | None) -> None:
        L.move_folder(self._scene(), name, parent)
        self._touch()

    def _ask_folder(self, names) -> None:
        from views import prompts
        name, ok = prompts.get_text(self, tr("New folder"),
                                    tr("Folder name:"))
        if ok and name.strip():
            self.move_to_folder(names, name.strip())

    def _on_delete(self) -> None:
        """Delete the highlighted layer — one undo step, so Ctrl+Z brings
        it back with everything it carried. A layer with content asks
        first, saying how much goes to the default layer. A folder goes
        on its own; its layers stay."""
        from core.history import DeleteLayerCommand
        from core.purge import layer_counts
        scene = self._scene()
        item = self.tree.currentItem()
        if item is None:
            return
        kind, name = self._key(item)
        if kind == KIND_FOLDER:
            L.remove_folder(scene, name)
            self._touch()
            return
        if name == L.DEFAULT_LAYER or scene.layer(name) is None:
            return                                  # the default is permanent
        n = layer_counts(scene).get(name, 0)
        if n and QMessageBox.question(
                self, tr("Layers"),
                tr("Delete the layer '{layer}'? Its {n} entities go to "
                   "'{default}'.", layer=name, n=n, default=L.DEFAULT_LAYER)
                ) != QMessageBox.Yes:
            return
        viewport = self._window.viewport
        viewport.history.execute(DeleteLayerCommand(name))
        self.refresh()
        viewport.notify_scene_changed()

    # ---- Templates and options -------------------------------------------------
    def _fill_more_menu(self) -> None:
        """The panel's options: how the rows are ordered, new layers in the
        scenes, and the layer templates."""
        from PySide6.QtGui import QActionGroup
        menu = self.more_menu
        menu.clear()
        group = QActionGroup(menu)
        for key, label in (("name", "Sort by name"),
                           ("created", "Sort by order created")):
            act = menu.addAction(tr(label))
            act.setCheckable(True)
            act.setChecked(self.sort_by == key)
            group.addAction(act)
            act.triggered.connect(lambda _c=False, k=key: self.set_sort_by(k))
        menu.addSeparator()
        act = menu.addAction(tr("New layers start hidden in existing scenes"))
        act.setCheckable(True)
        act.setChecked(self.new_layers_hidden_in_scenes())
        act.setStatusTip(tr(
            "A layer made after the scenes were saved does not turn up in "
            "them."))
        act.toggled.connect(self.set_new_layers_hidden_in_scenes)
        menu.addSeparator()
        menu.addAction(tr("Export layer template…"), self.export_template)
        menu.addAction(tr("Import layer template…"), self.import_template)

    def export_template(self, path: str | None = None) -> bool:
        """Save the layer list (names, colours, lines, folders) as a JSON
        template to load into other documents."""
        import json
        if path is None:
            from views.filedialogs import file_dialogs
            path, _ = file_dialogs.getSaveFileName(
                self, tr("Export layer template"), "layers.json",
                tr("Layer template (*.json)"))
            if not path:
                return False
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(L.template_of(self._scene()), fh,
                          ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, tr("Layers"), str(exc))
            return False
        self._window.statusBar().showMessage(
            tr("Layer template saved"), 2500)
        return True

    def import_template(self, path: str | None = None) -> bool:
        """Bring a template's layers in: new ones added, the ones already
        here take the template's look; nothing is removed."""
        import json
        if path is None:
            from views.filedialogs import file_dialogs
            path, _ = file_dialogs.getOpenFileName(
                self, tr("Import layer template"), "",
                tr("Layer template (*.json)"))
            if not path:
                return False
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            added, updated = L.apply_template(self._scene(), data)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("Layers"), tr(
                "This file is not a layer template.") + f"\n\n{exc}")
            return False
        self._dirty_paint()
        self._touch()
        self._window.statusBar().showMessage(tr(
            "{added} layers added, {updated} updated", added=added,
            updated=updated), 3000)
        return True

    def set_style(self, names, **look) -> None:
        """Line type, line weight or opacity of the layers ``names``."""
        scene = self._scene()
        for name in names:
            ly = scene.layer(name)
            if ly is None:
                continue
            if "linetype" in look:
                ly.linetype = look["linetype"]
            if "lineweight" in look:
                ly.lineweight = look["lineweight"]
            if "opacity" in look:
                ly.opacity = min(1.0, max(0.1, float(look["opacity"])))
        self._dirty_paint()
        self._touch()

    def set_printable(self, names, on: bool) -> None:
        """Put the layers ``names`` on the sheets, or leave them out (still
        seen in the model). The sheets redraw on their next refresh."""
        scene = self._scene()
        for name in names:
            ly = scene.layer(name)
            if ly is not None:
                ly.printable = bool(on)
        self._touch()

    def hide_in_scenes(self, names, hidden: bool) -> None:
        n = L.hide_in_scenes(self._scene(), names, hidden)
        self._touch()
        self._window.statusBar().showMessage(
            tr("{n} scenes updated", n=n), 2500)

    def merge(self, name: str, into: str) -> None:
        """Everything on ``name`` goes onto ``into`` and ``name`` goes away
        — one undo step."""
        from core.history import DeleteLayerCommand
        viewport = self._window.viewport
        viewport.history.execute(DeleteLayerCommand(name, into=into))
        self.refresh()
        viewport.notify_scene_changed()
        if self._scene().layer(name) is None:
            self._window.statusBar().showMessage(
                tr("'{layer}' merged into '{into}'", layer=name, into=into),
                2500)

    def _on_purge(self) -> None:
        """The classic "Purge Unused" for tags: sweep the layers nothing
        carries. One undoable step, and it says what it did — a silent
        sweep of a panel the user did not look at is how a deliberate
        empty layer disappears without anyone noticing."""
        from core.history import PurgeUnusedCommand
        scene = self._scene()
        cmd = PurgeUnusedCommand(layers=True, materials=False)
        n_layers, _ = cmd.counts(scene)
        if not n_layers:
            QMessageBox.information(
                self, tr("Purge"), tr("Every layer is in use."))
            return
        names = [ly.name for _i, ly in (cmd._layers or [])]
        preview = ", ".join(names[:12]) + ("…" if len(names) > 12 else "")
        if QMessageBox.question(
                self, tr("Purge"),
                tr("Delete {n} layers no entity carries?", n=n_layers)
                + f"\n\n{preview}") != QMessageBox.Yes:
            return
        self._window.viewport.history.execute(cmd)
        self.refresh()
        self._window.viewport.update()
        self._window.statusBar().showMessage(
            tr("{n} unused layers purged", n=n_layers), 3000)

    def _on_assign(self) -> None:
        """Move the selection onto the HIGHLIGHTED layer — and say so when
        there is nothing to move or no layer picked: the button used to do
        nothing in silence, which is how it read as broken («Asignar
        selección funcionó a la segunda», Rafael, 2026-09-16)."""
        from core.history import AssignLayerCommand
        scene = self._scene()
        item = self.tree.currentItem()
        if item is None or self._key(item)[0] != KIND_LAYER:
            self._window.statusBar().showMessage(
                tr("Click a layer in the list first, then Assign."), 3000)
            return
        name = self._key(item)[1]
        # Annotations are tagged too: a "Anotaciones" layer a
        # scene hides gives a clean plan without duplicating the model.
        targets = L.taggable(scene.selection)
        if not targets:
            self._window.statusBar().showMessage(
                tr("Select something in the model first, then Assign."), 3000)
            return
        self._window.viewport.history.execute(AssignLayerCommand(targets, name))
        self._window.viewport.update()
        self._window.statusBar().showMessage(
            tr("{n} entities moved to '{layer}'", n=len(targets), layer=name),
            2500)

    def select_content(self, names) -> None:
        from core.select_ops import on_layers
        scene = self._scene()
        picks = on_layers(scene, names)
        scene.select(picks)
        self._window.viewport.notify_scene_changed()
        self._window.statusBar().showMessage(
            tr("{n} entities selected", n=len(picks)), 2500)

    # ---- Context menu ----------------------------------------------------------
    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        self.fill_menu(menu, item)
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def fill_menu(self, menu, item) -> None:
        """The right-click menu of ``item`` (``None``: the empty list)."""
        scene = self._scene()
        if item is None:
            menu.addAction(tr("Add layer"), lambda: self.add_layer())
            menu.addAction(tr("Add folder"), lambda: self.add_folder())
            menu.addAction(tr("Show all layers"), self.show_all)
            menu.addSeparator()
            menu.addAction(tr("Purge unused layers…"), self._on_purge)
            return
        kind, name = self._key(item)
        names = self._targets(item)
        if kind == KIND_LAYER:
            act = menu.addAction(tr("Make active"),
                                 lambda: self.set_active(name))
            act.setEnabled(L.active_layer(scene) != name)
            act = menu.addAction(tr("Move the selection here"),
                                 self._assign_to(item))
            act.setEnabled(bool(L.taggable(scene.selection)))
        # Isolating is the row's target; no entry for it here.
        menu.addAction(tr("Show all layers"), self.show_all)
        menu.addAction(tr("Select content"),
                       lambda: self.select_content(names))
        menu.addSeparator()
        if kind == KIND_LAYER:
            menu.addAction(tr("Colour…"), lambda: self.pick_color(names))
            reset = menu.addAction(tr("Automatic colour"),
                                   lambda: self.set_color(names, None))
            ly = scene.layer(name)
            reset.setEnabled(any(scene.layer(n) is not None
                                 and scene.layer(n).color is not None
                                 for n in names))
            self._add_look_menus(menu, names, ly)
            movable = [n for n in names if n != L.DEFAULT_LAYER]
            if movable:
                sub = _submenu(menu, tr("Move to folder"))
                for folder in L.folders_of(scene):
                    sub.addAction(folder, lambda f=folder:
                                  self.move_to_folder(movable, f))
                sub.addSeparator()
                sub.addAction(tr("New folder…"), lambda: QTimer.singleShot(
                    0, lambda: self._ask_folder(movable)))
                out = sub.addAction(tr("Out of any folder"), lambda:
                                    self.move_to_folder(movable, None))
                out.setEnabled(any(scene.layer(n) and scene.layer(n).folder
                                   for n in movable))
            if name != L.DEFAULT_LAYER:
                merge = _submenu(menu, tr("Merge into"))
                for other in scene.layers:
                    if other.name != name:
                        merge.addAction(other.name, lambda o=other.name:
                                        self.merge(name, o))
        else:
            menu.addAction(tr("New layer in this folder"),
                           lambda: self.add_layer(name))
            menu.addAction(tr("New folder in this folder"),
                           lambda: self.add_folder(name))
            inside = set(L.subfolders(scene, name, deep=True)) | {name}
            sub = _submenu(menu, tr("Move to folder"))
            for folder in L.folders_of(scene):
                if folder not in inside:
                    sub.addAction(folder, lambda f=folder:
                                  self.move_folder(name, f))
            sub.addSeparator()
            top = sub.addAction(tr("Out of any folder"),
                                lambda: self.move_folder(name, None))
            top.setEnabled(L.folder_parent(scene, name) is not None)
        menu.addSeparator()
        if kind == KIND_FOLDER or name != L.DEFAULT_LAYER:
            menu.addAction(tr("Rename"), lambda: self.tree.editItem(item,
                                                                    COL_NAME))
            menu.addAction(tr("Delete folder") if kind == KIND_FOLDER
                           else tr("Delete"), self._delete_item(item))
        menu.addSeparator()
        menu.addAction(tr("Purge unused layers…"), self._on_purge)

    #: Line type labels, in menu order.
    LINETYPE_LABELS = (("continuous", "Continuous"), ("dashed", "Dashed"),
                       ("dashed_short", "Short dashes (hidden)"),
                       ("dashed_long", "Long dashes"),
                       ("dotted", "Dotted"), ("dashdot", "Dash-dot"),
                       ("dashdotdot", "Dash-dot-dot"),
                       ("center", "Centre line (long dash, dot)"),
                       ("phantom", "Phantom (long dash, two dots)"),
                       ("border", "Border (two dashes, dot)"))
    #: Pen widths offered, in millimetres (the usual ISO series).
    LINEWEIGHTS = (0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.00)
    OPACITIES = (1.0, 0.75, 0.5, 0.25)

    def _add_look_menus(self, menu, names, ly) -> None:
        """Line type, line weight and opacity of the layers ``names``, the
        current one ticked; and their visibility in every saved scene."""
        self._fill_linetypes(_submenu(menu, tr("Line type")), names, ly)
        self._fill_weights(_submenu(menu, tr("Line weight")), names, ly)
        self._fill_opacities(_submenu(menu, tr("Transparency")), names, ly)
        if getattr(self._scene(), "saved_views", None):
            menu.addAction(tr("Hide in every scene"),
                           lambda: self.hide_in_scenes(names, True))
            menu.addAction(tr("Show in every scene"),
                           lambda: self.hide_in_scenes(names, False))

    def _fill_linetypes(self, menu, names, ly) -> None:
        """The line types as the lines they draw, the current one ticked
        (the name is the entry's tooltip and its text for the keyboard)."""
        from PySide6.QtWidgets import QWidgetAction
        for key, label in self.LINETYPE_LABELS:
            a = QWidgetAction(menu)
            a.setText(tr(label))
            a.setCheckable(True)
            on = ly is not None and ly.linetype == key
            a.setChecked(on)
            a.triggered.connect(lambda _c=False, k=key:
                                self.set_style(names, linetype=k))
            a.setDefaultWidget(_LineSample(key, a, menu, on))
            menu.addAction(a)

    #: Screen pixels per millimetre of pen width in the weight list (the
    #: thinnest still a pixel, the thickest not a bar).
    WEIGHT_PX_PER_MM = 6.0

    def _fill_weights(self, menu, names, ly) -> None:
        """The weights as lines of that weight with the value beside them,
        like the line types; first the default (the sheet's pens)."""
        from PySide6.QtWidgets import QWidgetAction
        rows = [(None, tr("Default (from the sheet)"))] + [
            (w, f"{w:.2f} mm") for w in self.LINEWEIGHTS]
        for w, text in rows:
            a = QWidgetAction(menu)
            a.setText(text)
            a.setCheckable(True)
            if w is None:
                on = ly is not None and ly.lineweight is None
            else:
                on = (ly is not None and ly.lineweight is not None
                      and abs(ly.lineweight - w) < 1e-6)
            a.setChecked(on)
            a.triggered.connect(lambda _c=False, w=w:
                                self.set_style(names, lineweight=w))
            px = (max(1.0, min(6.0, w * self.WEIGHT_PX_PER_MM))
                  if w is not None else 2.0)
            a.setDefaultWidget(_LineSample(
                "continuous" if w is not None else None, a, menu, on,
                width=px, text=text))
            menu.addAction(a)

    def _fill_opacities(self, menu, names, ly) -> None:
        """The transparencies as the layer's colour at that opacity over a
        checkerboard, with the percentage — like the line lists."""
        from PySide6.QtWidgets import QWidgetAction
        rgb = L.layer_color(ly)
        for o in self.OPACITIES:
            clear = round((1.0 - o) * 100)
            a = QWidgetAction(menu)
            a.setText(f"{clear} %")
            a.setCheckable(True)
            on = ly is not None and abs(ly.opacity - o) < 1e-6
            a.setChecked(on)
            a.triggered.connect(lambda _c=False, o=o:
                                self.set_style(names, opacity=o))
            a.setDefaultWidget(_LineSample(None, a, menu, on, text=f"{clear} %",
                                           swatch=(rgb, o)))
            menu.addAction(a)

    def _assign_to(self, item):
        def run():
            self.tree.setCurrentItem(item)
            self._on_assign()
        return run

    def _delete_item(self, item):
        def run():
            self.tree.setCurrentItem(item)
            self._on_delete()
        return run

    # ---- The window's scene-changed signal -------------------------------------
    def on_scene_changed(self) -> None:
        """Refreshed now when on screen, on showing otherwise — like the
        Browser and the components tray. Behind another tab, rebuilding the
        rows was 7 ms of every edit on plaza, and the counts that follow
        walk the whole model: 0.15 s of every edit on the plant of #158
        (release_check 0.5.11). A window not shown yet (scripts, tests)
        refreshes at once, as before."""
        if self.tree.state() == QAbstractItemView.EditingState:
            return                          # never under an open name editor
        if self._window.isVisible() and not self.isVisible():
            self._stale = True
            return
        if (self._signature() == getattr(self, "_drawn_signature", None)
                and self.tree.topLevelItemCount()):
            # The rows are what they were: only the selection's mark and,
            # after a change of the model, the counts follow. The filter
            # too: «Selection» shows the layers of what is picked.
            self._mark_selection()
            self._apply_filter()
            if self._scene().content_version != self._counted_version:
                self._count_timer.start(300)
            return
        self.refresh()

    def _signature(self) -> tuple:
        return (layers_signature(self._scene()), tuple(self._isolated))

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if getattr(self, "_stale", False):
            self._stale = False
            self.refresh()


class LayersDock(QDockWidget):
    """Sidebar tab **Layers**, next to the Browser."""

    def __init__(self, window) -> None:
        super().__init__(tr("Layers"), window)
        self.setObjectName("tray_layers")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetClosable)
        self.panel = LayersPanel(window)
        self.setWidget(self.panel)
        self.setMinimumWidth(240)

    def on_scene_changed(self) -> None:
        self.panel.on_scene_changed()
