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

import json

from PySide6.QtCore import (QItemSelectionModel, QPoint, QPointF, QRectF, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtGui import QAction, QBrush
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                               QFrame,
                               QDockWidget,
                               QHBoxLayout, QHeaderView, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QSizePolicy,
                               QStyledItemDelegate,
                               QToolButton, QTreeWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout, QWidget)

from core import layers as L
from core.i18n import tr
from core.outliner import natural_key  # noqa: F401 — the Browser's too
from views.outliner import node_icon
from views.side_tree import SideTree, StayOpenMenu, _HeaderButton

(COL_NAME, COL_ACTIVE, COL_EYE, COL_LOCK, COL_COLOR, COL_COUNT,
 COL_ISOLATE, COL_LINETYPE, COL_WEIGHT, COL_OPACITY, COL_PRINT,
 COL_CUT, COL_HATCH) = range(13)

#: The row kinds kept in ``Qt.UserRole`` of the name column.
KIND_LAYER, KIND_FOLDER = "layer", "folder"
#: Name-column role: the row holds what is selected in the model (its
#: layer, or a folded folder with that layer inside).
ROLE_HOLDS = Qt.UserRole + 2
#: Line-type column role: the layer's line type key, drawn by
#: :class:`_LineDelegate`.
ROLE_LINETYPE = Qt.UserRole + 3
#: Line-type column role: the dash pattern itself, in paper mm — the
#: document's own line types too.
ROLE_LINEPATTERN = Qt.UserRole + 5
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
    return none_swatch()


def none_swatch() -> QIcon:
    """The «none» swatch: empty (base-coloured), crossed by a red slash —
    a layer with no colour of its own, a layer with no hatch."""
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
    the row's left edge (the row's tint and its name in bold do the
    rest)."""

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.data(ROLE_HOLDS):
            from PySide6.QtWidgets import QApplication
            r = option.rect
            painter.fillRect(r.left(), r.top() + 1, 4, r.height() - 2,
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


def line_pen(key: str, ink, width: float, px_per_mm: float,
             pattern=None) -> QPen:
    """A pen in the dash pattern of line type ``key`` — or ``pattern``,
    given (a custom one) — in millimetres on paper shown at ``px_per_mm``
    screen pixels each."""
    pen = QPen(ink, width)
    pen.setCapStyle(Qt.FlatCap)
    if pattern is None:
        pattern = L.LINETYPES.get(key, ())
    # A dot is a dash as long as the pen is wide; Qt wants every piece > 0.
    pattern = [abs(mm) if mm else width / px_per_mm for mm in pattern]
    if pattern:
        pen.setDashPattern([max(0.3, mm * px_per_mm / width)
                            for mm in pattern])
    return pen


#: The swatch box shared by the colour and the hatch columns, in px of an
#: 18 px icon: the same rounded rectangle, so both columns read alike.
SWATCH_BOX = QRectF(2.5, 3.5, 13, 11)


def hatch_icon(key, ground=None, ink=None, angle: float = 0.0,
               families=None) -> QIcon:
    """A row's hatch swatch (the Layers panel's Hatch column) — the very
    shape of the colour swatch beside it: the pattern inside the rounded
    box, on the layer's ground colour and in its ink (RGB 0–1) when it has
    them, turned as the layer turns it; ``families``: an imported pattern's.
    No pattern: the «none» swatch."""
    if not key:
        return none_swatch()
    from PySide6.QtGui import QPainterPath
    from views.hatch_paint import paint_hatch
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app is not None else 1.0
    pal = QApplication.palette()
    pm = QPixmap(int(18 * dpr), int(18 * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    box = QPainterPath()
    box.addRoundedRect(SWATCH_BOX, 2, 2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor.fromRgbF(*ground[:3]) if ground is not None
               else QColor(255, 255, 255))
    p.drawPath(box)
    # The pattern at 2 px per paper mm: a few repeats in the little box.
    k = 2.0
    p.save()
    p.scale(k, k)
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(SWATCH_BOX.x() / k, SWATCH_BOX.y() / k,
                                SWATCH_BOX.width() / k,
                                SWATCH_BOX.height() / k), 1, 1)
    paint_hatch(p, inner, key,
                QColor.fromRgbF(*ink[:3]) if ink is not None
                else QColor(30, 36, 44), 0.9 / k, 1.0, None, angle, families)
    p.restore()
    p.setPen(QPen(pal.text().color(), 1.0))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(SWATCH_BOX, 2, 2)
    p.end()
    return QIcon(pm)


class _ColourWindow(QFrame):
    """The «Other colour…» window of the hatch picker: a popup over it —
    so the picker, a popup too, stays open behind — that says when it
    closes (a click outside it, Esc)."""

    closed = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent, Qt.Popup)
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.closed.emit()


class _ColourPopup(_ColourWindow):
    """«Other colour…» over a popup panel — the panel, a popup too, stays
    open behind it: a colour chooser, «Back» and «Use this colour»;
    ``callback`` gets the colour picked, as ``(r, g, b)``."""

    def __init__(self, parent, title: str, start, callback) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QColorDialog, QLabel
        self._callback = callback
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 12)
        box.setSpacing(8)
        label = QLabel(title, self)
        label.setStyleSheet("font-weight: bold;")
        box.addWidget(label)
        dlg = self.dialog = QColorDialog(self)
        dlg.setWindowFlags(Qt.Widget)
        dlg.setOptions(QColorDialog.DontUseNativeDialog
                       | QColorDialog.NoButtons)
        dlg.setCurrentColor(start)
        dlg.accepted.connect(self._take)
        dlg.rejected.connect(self.close)
        box.addWidget(dlg)
        row = QHBoxLayout()
        row.addStretch(1)
        back = self.back_button = QPushButton(tr("Cancel"), self)
        back.clicked.connect(self.close)
        row.addWidget(back)
        use = self.use_button = QPushButton(tr("Use this colour"), self)
        use.setDefault(True)
        use.clicked.connect(self._take)
        row.addWidget(use)
        box.addLayout(row)

    def _take(self) -> None:
        rgb = tuple(round(c, 4) for c in
                    self.dialog.currentColor().getRgbF()[:3])
        self.close()
        self._callback(rgb)

    def ask(self) -> None:
        """Shown over the middle of its parent."""
        self.dialog.show()
        self.adjustSize()
        owner = self.parentWidget()
        centre = owner.mapToGlobal(owner.rect().center())
        self.move(centre.x() - self.width() // 2,
                  centre.y() - self.height() // 2)
        self.show()
        self.raise_()
        self.use_button.setFocus()


class _LineColourRow(QWidget):
    """The line type panel's «COLOUR OF THE LINE»: compact chips — by
    layer, the usual colours, any other — for the line type the layers
    have now, its name beside the title; a click applies at once."""

    CHIP = (18, 14)

    def __init__(self, panel, names, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QButtonGroup, QLabel
        self._panel = panel
        self._names = list(names)
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 6, 12, 4)
        box.setSpacing(4)
        # A section title as the panel's others: small capitals over a
        # rule, the colour's name beside it.
        self.title = QLabel(self)
        self.title.setStyleSheet(
            "font-size: 7.5pt; letter-spacing: 1px; padding: 2px 0;"
            " border-bottom: 1px solid palette(mid);")
        box.addWidget(self.title)
        row = QHBoxLayout()
        row.setSpacing(2)
        box.addLayout(row)
        group = QButtonGroup(self)
        self.buttons = {}
        for value, label in LineTypeDialog.COLOURS:
            b = QToolButton(self)
            b.setCheckable(True)
            b.setToolTip(tr(label))
            b.setStyleSheet(HatchGrid._TILE_CSS)
            b.setIconSize(QSize(*self.CHIP))
            b.clicked.connect(lambda _c=False, v=value: self._pick(v))
            group.addButton(b)
            row.addWidget(b)
            self.buttons[value] = b
        row.addStretch(1)
        self.refresh()

    def key(self):
        ly = self._panel._scene().layer(self._names[0]) if self._names \
            else None
        return ly.linetype if ly is not None else "continuous"

    def refresh(self) -> None:
        from views.hatch_paint import any_colour_chip, colour_chip
        key = self.key()
        mine = L.linetype_color(key, self._panel._scene())
        fixed = [v for v, _t in LineTypeDialog.COLOURS
                 if isinstance(v, tuple)]
        dpr = self.devicePixelRatioF()
        for value, b in self.buttons.items():
            if value is None:
                icon = colour_chip(*self.CHIP,
                                   QColor.fromRgbF(0.55, 0.35, 0.25),
                                   dpr=dpr, strokes=True)
                on = mine is None
            elif value == "other":
                on = mine is not None and mine not in fixed
                icon = any_colour_chip(*self.CHIP,
                                       QColor.fromRgbF(*mine) if on
                                       else None, dpr=dpr)
            else:
                icon = colour_chip(*self.CHIP, QColor.fromRgbF(*value),
                                   dpr=dpr, strokes=True)
                on = mine == value
            b.setIcon(QIcon(icon))
            b.setChecked(on)
        name = next((t for v, t in LineTypeDialog.COLOURS if v == mine),
                    "Other colour…" if mine is not None else "By layer")
        self.title.setText(
            "<b>" + tr("Colour of the line").upper() + "</b> · "
            + tr(name).rstrip("…"))

    def _pick(self, value) -> None:
        key = self.key()
        if value == "other":
            mine = L.linetype_color(key, self._panel._scene())
            self.chooser = _ColourPopup(
                self.window(), tr("Colour of the line"),
                QColor.fromRgbF(*mine) if mine else QColor(220, 120, 0),
                lambda rgb: self._set(key, rgb))
            self.chooser.closed.connect(self.refresh)
            self.chooser.ask()
            return
        self._set(key, value)

    def _set(self, key, rgb) -> None:
        self._panel.set_linetype_colour(key, rgb)
        self.refresh()
        menu = self.parentWidget()
        for sample in (menu.findChildren(_LineSample)
                       if menu is not None else ()):
            if sample.key == key:
                sample.colour = rgb
                sample.update()


class HatchGrid(QWidget):
    """The picker of a layer's cut hatch — a popover in four bands, top to
    bottom:

    1. a search field and a chip per material group (core.hatches.
       HATCH_GROUPS, and the document's imported patterns) that scrolls the
       grid to it;
    2. the patterns as a grid of drawn tiles — the recently used first,
       then a title per group, the imported ones last — the current one
       framed in the accent colour; :data:`ROWS` rows in sight, the rest
       scroll, opened at the top (the recently used first);
    3. the preview: the pattern as it will print — on its ground, in its
       ink, turned and sized — big, with its name; a tile under the pointer
       previews itself; beside it, the grounds and the inks as rows of
       chips, the chosen one named, and the angle, the scale and whether
       the pattern grows with the drawing's scale;
    4. «No hatch (the frame's fill)», «Import .pat…» and «Done».

    Every click applies at once and the popover stays open, so pattern,
    ground and ink are chosen in one go; only «Done» keeps them —
    «Cancel», Esc or a click outside put the layer back. Signals: ``picked`` (the pattern, ``None`` for the frame's
    fill), ``ground_picked`` (what ``Layer.hatch_ground`` takes),
    ``ink_picked`` (what ``Layer.hatch_color`` takes), ``form_picked``
    (``{"hatch_angle", "hatch_scale", "hatch_offset", "hatch_on_paper"}``),
    ``brick_picked`` (what ``Layer.brick`` takes: the brick a brickwork
    pattern is drawn with, ``None`` for the usual one),
    ``import_requested``, ``done``."""

    picked = Signal(object)
    ground_picked = Signal(object)
    ink_picked = Signal(object)
    form_picked = Signal(object)
    brick_picked = Signal(object)
    #: The brick shown, made the document's: every layer takes it.
    brick_for_document = Signal(object)
    import_requested = Signal()
    export_requested = Signal()
    done = Signal()
    cancelled = Signal()
    #: QSettings key of the patterns used last, newest first, and how many.
    RECENT_KEY = "layers/recent_hatches"
    RECENT_MAX = 7
    #: QSettings key of the patterns pinned as favourites, in pin order.
    FAVOURITES_KEY = "layers/favourite_hatches"
    FAVOURITES_MAX = 21
    #: The groups of shortcut tiles: patterns shown again from below.
    SHORTCUTS = ("Favourites", "Recent")
    #: Tiles per row, a tile's swatch in px, and the rows in sight at once.
    #: A tile is the pattern alone: its name is the tooltip and the
    #: preview's caption while the pointer is on it.
    COLUMNS = 6
    TILE = (52, 34)
    ROWS = 4
    #: A ground's or an ink's chip, in px.
    CHIP = (26, 20)
    #: The preview card: the face, and under it how the pattern looks cut
    #: — a plan and a section of one wall, side by side, as tall as each
    #: other — all in px.
    PREVIEW = (144, 68)
    #: The piece in isometric under the card, in px.
    PIECE_VIEW = (162, 98)
    PLAN_TILE = (94, 44)
    SECTION_TILE = (44, 44)
    #: The grounds offered: ``(value, label)``; ``"other"`` asks for one.
    GROUNDS = ((None, "No ground (the paper)"), ((1.0, 1.0, 1.0), "White"),
               ((0.88, 0.88, 0.88), "Light grey"), ((0.70, 0.70, 0.70), "Grey"),
               (L.GROUND_LAYER, "The layer's colour, light"),
               ("other", "Other colour…"))
    #: How masonry joints are drawn: ``(Layer.joints, label)``.
    JOINTS = ((None, "Automatic (by scale)"), ("single", "Single line"),
              ("double", "Double (real thickness)"),
              ("none", "None (outline only)"))
    #: The inks offered: the two that follow the drawing (the frame's,
    #: the layer's), the two fixed ones of a technical section — black, and
    #: a dark grey that lets the outlines lead — and any other (white for a
    #: dark ground, a colour of its own). «Automatic» carries an «A», or it
    #: would read as one more grey.
    INKS = ((None, "Automatic (as the frame says)"),
            (L.GROUND_LAYER, "The layer's colour"),
            ((0.0, 0.0, 0.0), "Black"), ((0.40, 0.40, 0.40), "Dark grey"),
            ("other", "Other colour…"))

    _TILE_CSS = ("QToolButton { font-size: 8pt; border: 1px solid transparent;"
                 " border-radius: 4px; padding: 2px; }"
                 "QToolButton:hover { background: palette(midlight);"
                 " border-color: palette(mid); }"
                 "QToolButton:checked { border: 2px solid palette(highlight);"
                 " background: palette(alternate-base); }")

    def __init__(self, current, parent=None, ground=None, layer=None,
                 ink=None, patterns=None, form=None, recent=None) -> None:
        super().__init__(parent)
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout,
                                       QLabel, QScrollArea, QVBoxLayout)
        from core.hatches import HATCH_GROUPS, IMPORTED, known
        from views.hatch_paint import hatch_swatch
        self._layer = layer
        #: The document's imported patterns: name → {"label", "families"}.
        self._imported = dict(patterns or {})
        form = dict(form or {})
        from core.layers import clean_offset
        self._form = {"hatch_angle": float(form.get("hatch_angle", 0.0)),
                      "hatch_scale": float(form.get("hatch_scale", 1.0)),
                      "hatch_offset": clean_offset(form.get("hatch_offset")),
                      "hatch_on_paper": bool(form.get("hatch_on_paper",
                                                      True)),
                      "hatch_cross": bool(form.get("hatch_cross", False))}
        #: The checkbox shows what the layer does now; only a click on it
        #: fixes the choice for the layer.
        self._paper_fixed = bool(form.get("paper_fixed", False))
        from core.hatches import clean_brick
        #: The layer's own brick, ``None`` for the usual one.
        self._brick = clean_brick(form.get("brick")) \
            if form.get("brick") is not None else None
        #: The document's pieces by kind (core.hatches.piece_kind) — what a
        #: layer without its own is drawn with; a kind not there: its usual.
        self._doc_bricks = {k: clean_brick(v) for k, v in
                            (form.get("doc_bricks") or {}).items()
                            if clean_brick(v) is not None}
        from core.hatches import piece_kind
        #: The kind of piece the fields size: the current pattern's.
        self._kind = piece_kind(current) or "brick"
        #: How its masonry joints are drawn (``None``: by the scale), and
        #: whether the double ones show their mortar.
        self._joints = form.get("joints")
        self._mortar = bool(form.get("mortar", False))
        recent = self.recent() if recent is None else list(recent)
        self._recent = [k for k in recent if self._usable(k)][
            :self.RECENT_MAX]
        groups = self._groups()
        self._dpr = dpr = self.devicePixelRatioF()
        self._current, self._hover = current, None
        self._ground = (tuple(round(c, 4) for c in ground)
                        if isinstance(ground, (list, tuple)) else ground)
        self._ink = (tuple(round(c, 4) for c in ink)
                     if isinstance(ink, (list, tuple)) else ink)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        # Side by side, in the order of the task: the catalogue on the left
        # — search, groups, tiles: choosing comes first — and on the right
        # the preview and the settings of the one chosen. Screens are wider
        # than tall: the picker fits a laptop and shows more patterns.
        body = QHBoxLayout()
        body.setSpacing(12)
        catalog = QVBoxLayout()
        catalog.setSpacing(8)

        # 1. Search and jump.
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(tr("Search hatches…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        # Beside the search, a funnel — as the Layers panel's — for one
        # group at a time: the tiles get the room the group buttons took.
        self._group = None
        self.filter_btn = QToolButton(self)
        self.filter_btn.setObjectName("hatch_filter")
        self.filter_btn.setAutoRaise(True)
        self.filter_btn.setPopupMode(QToolButton.InstantPopup)
        self.filter_btn.setStyleSheet(
            "QToolButton::menu-indicator { image: none; width: 0; }")
        self.filter_menu = QMenu(self.filter_btn)
        self.filter_menu.aboutToShow.connect(self._fill_filter_menu)
        self.filter_btn.setMenu(self.filter_menu)
        self.group_actions: dict = {}
        self._fill_filter_menu()
        self._show_filter_state()
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(4)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.filter_btn)
        search_bar = QWidget(self)
        search_bar.setLayout(search_row)
        catalog.addWidget(search_bar)

        # 2. The grid of patterns, scrolling.
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.StyledPanel)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = self._build_tiles(groups, current)
        tile_h = next(iter(self.buttons.values())).sizeHint().height()
        head_h = QLabel("X").sizeHint().height() + 6
        # At least this many rows; more when the settings below are fewer.
        self.scroll.setMinimumHeight(min(inner.sizeHint().height() + 4,
                                         self.ROWS * (tile_h + 2) + head_h
                                         + 8))
        width = (inner.sizeHint().width()
                 + self.scroll.verticalScrollBar().sizeHint().width() + 6)
        self.scroll.setFixedWidth(width)
        catalog.addWidget(self.scroll, 1)
        search_bar.setFixedWidth(width)
        # Opened at the top — the recently used and the general ones in
        # sight; the current pattern is named in the preview below.
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar()
                          .setValue(0))

        # 3. Preview and settings, on a grid of two rows so that what goes
        # together lines up: the preview beside the colour and the size
        # (both from the top), the piece's drawing beside the piece's
        # fields (both from the «Piece» title).
        band = QGridLayout()
        band.setHorizontalSpacing(12)
        band.setVerticalSpacing(10)
        band.addWidget(self._preview_card(), 0, 0, Qt.AlignTop)
        # The piece the size fields set, drawn in isometric with its
        # measures — beside the fields, under the preview.
        self.piece_view = QLabel(self)
        self.piece_view.setObjectName("hatchPieceView")
        self.piece_view.setFixedSize(*self.PIECE_VIEW)
        self.piece_view.setAlignment(Qt.AlignCenter)
        self.piece_view.setStyleSheet(
            "QLabel#hatchPieceView { border: 1px solid palette(mid);"
            " border-radius: 6px; background: palette(base); }")
        self.piece_view.setToolTip(tr(
            "The piece, as its measures set it: length, width, height"))
        band.addWidget(self.piece_view, 1, 0, Qt.AlignTop)
        self.settings = QWidget(self)
        right = QVBoxLayout(self.settings)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(2)
        # Colour: under it and of it.
        right.addWidget(self._section(tr("Colour")))
        self.ground_name = QLabel(self)
        self.ink_name = QLabel(self)
        self.ground_buttons = self._choices(
            right, tr("Ground under the hatch"), self.ground_name,
            self.GROUNDS, self._ground, "ground")
        right.addSpacing(4)
        self.ink_buttons = self._choices(
            right, tr("Colour of the hatch"), self.ink_name, self.INKS,
            self._ink, "ink")
        # Size and turn.
        right.addSpacing(8)
        right.addWidget(self._section(tr("Placement")))
        right.addLayout(self._form_row())
        right.addWidget(self.drawing_check)
        right.addStretch(1)
        band.addWidget(self.settings, 0, 1)
        # The second row: what only some patterns use.
        lower = QWidget(self)
        below = QVBoxLayout(lower)
        below.setContentsMargins(0, 0, 0, 0)
        below.setSpacing(0)
        # Wood: its cross — only for wood.
        self.wood_section = QWidget(lower)
        wood = QVBoxLayout(self.wood_section)
        wood.setContentsMargins(0, 0, 0, 0)
        wood.setSpacing(2)
        wood.addWidget(self._section(tr("Wood")))
        wood.addWidget(self.cross_check)
        below.addWidget(self.wood_section)
        # The piece — only for masonry.
        self.piece_section = QWidget(lower)
        piece = QVBoxLayout(self.piece_section)
        piece.setContentsMargins(0, 0, 0, 0)
        piece.setSpacing(2)
        piece.addWidget(self._section(tr("Piece")))
        piece.addWidget(self._brick_row())
        below.addWidget(self.piece_section)
        below.addStretch(1)
        band.addWidget(lower, 1, 1)
        band.setColumnStretch(1, 1)
        band.setRowStretch(2, 1)
        body.addLayout(catalog)
        rule = QFrame(self)
        rule.setFrameShape(QFrame.VLine)
        rule.setFrameShadow(QFrame.Sunken)
        body.addWidget(rule)
        body.addLayout(band, 1)
        outer.addLayout(body, 1)

        # 4. Footer.
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        outer.addWidget(line)
        foot = QHBoxLayout()
        # The pattern files on the left, apart from the answers on the
        # right: two plain buttons, each saying what it does — one click,
        # and nothing hidden behind a menu.
        load = QAction(tr("Import .pat…"), self)
        load.setToolTip(tr(
            "Bring in the patterns of a pattern file (.pat, the plain text "
            "format of technical drawing): they are kept in this document"))
        load.triggered.connect(self.import_requested.emit)
        save = QAction(tr("Export .pat…"), self)
        save.setToolTip(tr(
            "Write the patterns drawn with lines — the built-in ones and "
            "this document's — to a pattern file (.pat, millimetres) other "
            "drawing programs open; stipples, stones and waves have no .pat "
            "form and stay out"))
        save.triggered.connect(self.export_requested.emit)
        self.file_buttons = []
        from PySide6.QtCore import QSize
        from views.icons import tool_icon
        for action, name, icon in ((load, "hatch_import", "file_import"),
                                   (save, "hatch_export", "file_export")):
            # A button takes the icon text, which drops the «…» that
            # says a file dialog follows.
            action.setIconText(action.text())
            action.setIcon(tool_icon(icon))
            b = QToolButton(self)
            b.setObjectName(name)
            b.setDefaultAction(action)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setIconSize(QSize(16, 16))
            # A button, plainly — but lighter than the answers on the
            # right: a thin frame, no fill until the pointer is on it.
            b.setStyleSheet(
                "QToolButton { border: 1px solid palette(mid);"
                " border-radius: 4px; padding: 3px 8px 3px 6px; }"
                " QToolButton:hover { background: palette(midlight); }"
                " QToolButton:pressed { background: palette(mid); }")
            foot.addWidget(b)
            self.file_buttons.append(b)
        self.import_button, self.export_button = load, save
        foot.addStretch(1)
        # Every pick applies at once; «Cancel» puts the layer back as it
        # was when the picker opened, «Done» keeps it.
        back = QPushButton(tr("Cancel"), self)
        back.clicked.connect(self.cancelled.emit)
        foot.addWidget(back)
        self.cancel_button = back
        ok = QPushButton(tr("Done"), self)
        ok.setDefault(True)
        ok.clicked.connect(self.done.emit)
        # Where the arrows stopped joins the recently used.
        self.done.connect(lambda: self.remember(self._current))
        foot.addWidget(ok)
        self.done_button = ok
        outer.addLayout(foot)
        # As tall as with the tallest settings (a masonry pattern's): the
        # picker keeps its size, the grid of patterns all of its height.
        self.wood_section.hide()
        self.piece_section.show()
        self.cut_same.hide()           # one of the two, not both
        self.cut_preview.show()
        for w in self.offset_widgets:
            w.show()
        for b in self.more_boxes.values():
            b.show()
        # Every layout measured afresh with the folds open, inner first.
        from PySide6.QtCore import QEvent
        for w in self.findChildren(QWidget):
            w.updateGeometry()
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        self.layout().invalidate()
        self.layout().activate()
        self.setFixedSize(self.sizeHint().width(),
                          self.minimumSizeHint().height())
        for n, b in self.more_boxes.items():
            b.setVisible(self.more_buttons[n].isChecked())
        self._refresh_preview()
        QTimer.singleShot(0, self.search.setFocus)

    def _preview_card(self):
        """The preview as one card: the pattern's name on top, its face,
        and under it how it looks cut — a plan and a section of the same
        wall at the same scale, with a caption each in one quiet style.
        Where every cut looks alike, a line says so in their place: the
        card keeps its size and nothing jumps while browsing."""
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import (QFrame, QGridLayout, QLabel,
                                       QVBoxLayout)
        card = QFrame(self)
        card.setObjectName("hatchPreviewCard")
        card.setStyleSheet(
            "QFrame#hatchPreviewCard { border: 1px solid palette(mid);"
            " border-radius: 6px; background: palette(base); }")
        col = QVBoxLayout(card)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(3)

        def caption(text):
            label = QLabel(text, card)
            label.setStyleSheet("font-size: 7.5pt;")
            label.setForegroundRole(QPalette.PlaceholderText)
            label.setAlignment(Qt.AlignHCenter)
            return label
        self.preview_name = QLabel(card)
        self.preview_name.setStyleSheet("font-weight: bold;")
        self.preview_name.setWordWrap(True)
        self.preview_name.setFixedWidth(self.PREVIEW[0] - 24)
        # Two lines at most: the card stays put from one name to the next.
        self.preview_name.setFixedHeight(
            2 * self.preview_name.fontMetrics().lineSpacing())
        self.preview_name.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # The star: pin the chosen pattern among the favourites.
        self.star = QToolButton(card)
        self.star.setObjectName("hatch_star")
        self.star.setAutoRaise(True)
        self.star.setCheckable(True)
        self.star.setFixedSize(22, 22)
        self.star.setStyleSheet(
            "QToolButton { border: none; font-size: 13pt; padding: 0; }"
            "QToolButton:checked { color: #e8a317; }")
        self.star.clicked.connect(
            lambda on: self.set_favourite(self._current, on))
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(2)
        head.addWidget(self.preview_name, 1)
        head.addWidget(self.star, 0, Qt.AlignTop)
        col.addLayout(head)
        self.preview = QLabel(card)
        self.preview.setFixedSize(*self.PREVIEW)
        col.addWidget(self.preview)
        col.addWidget(caption(tr("Elevation")))
        col.addSpacing(3)
        # How it looks cut: the plan and the section of one wall.
        self.cut_preview = QWidget(card)
        self.cut_preview.setToolTip(tr(
            "How it looks cut: a wall seen from above in a plan, and the "
            "same wall in a vertical section"))
        cuts = QGridLayout(self.cut_preview)
        cuts.setContentsMargins(0, 0, 0, 0)
        cuts.setHorizontalSpacing(self.PREVIEW[0] - self.PLAN_TILE[0]
                                  - self.SECTION_TILE[0])
        cuts.setVerticalSpacing(3)
        self.plan_tile = QLabel(self.cut_preview)
        self.plan_tile.setFixedSize(*self.PLAN_TILE)
        self.section_tile = QLabel(self.cut_preview)
        self.section_tile.setFixedSize(*self.SECTION_TILE)
        cuts.addWidget(self.plan_tile, 0, 0)
        cuts.addWidget(self.section_tile, 0, 1)
        cuts.addWidget(caption(tr("Plan")), 1, 0)
        cuts.addWidget(caption(tr("Section")), 1, 1)
        self.cut_same = caption(tr("Looks the same in plan and in section"))
        self.cut_same.setWordWrap(True)
        self.cut_same.setAlignment(Qt.AlignCenter)
        self.cut_same.setFixedSize(self.PREVIEW[0],
                                   self.cut_preview.sizeHint().height())
        col.addWidget(self.cut_preview)
        col.addWidget(self.cut_same)
        return card

    def _usable(self, key) -> bool:
        from core.hatches import IMPORTED, known
        return bool(key) and known(key) and (
            not key.startswith(IMPORTED)
            or key[len(IMPORTED):] in self._imported)

    def _groups(self) -> list:
        """The sections of the grid: the pinned patterns, the recently
        used, every group of the catalogue, the imported ones."""
        from core.hatches import HATCH_GROUPS, IMPORTED
        favs = [k for k in self.favourites() if self._usable(k)]
        # «No hatch» (the frame's fill) is a pattern like the others: the
        # first tile of General.
        catalogue = [(t, ((None,) + keys) if t == "General" else keys)
                     for t, keys in HATCH_GROUPS]
        groups = (([("Favourites", tuple(favs))] if favs else [])
                  + ([("Recent", tuple(self._recent))] if self._recent
                     else [])
                  + catalogue)
        if self._imported:
            groups.append(("Imported", tuple(
                IMPORTED + n for n in sorted(self._imported, key=str.lower))))
        return groups

    def _build_tiles(self, groups, current):
        """The grid of tiles under their group titles, in the scroll area
        (replacing what it held)."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QButtonGroup, QGridLayout, QLabel
        from views.hatch_paint import hatch_swatch
        dpr = self._dpr
        inner = QWidget(self.scroll)
        grid = QGridLayout(inner)
        grid.setContentsMargins(6, 4, 6, 6)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self._patterns = QButtonGroup(self)
        self.buttons: dict = {}
        #: The recently used tiles — shortcuts to a pattern shown below too.
        self.recent_buttons: dict = {}
        #: The pinned tiles — shortcuts too, first of all.
        self.favourite_buttons: dict = {}
        self._heads: dict = {}
        self._sections: list = []           # (title, head, [(key, button)])
        row = 0
        for title, group in groups:
            head = QLabel(tr(title), inner)
            # The default text colour: a «dark» palette role vanishes on a
            # dark theme.
            head.setStyleSheet("font-size: 8pt; font-weight: bold;"
                               " padding-top: 6px;")
            grid.addWidget(head, row, 0, 1, self.COLUMNS)
            self._heads[title] = head
            row += 1
            shortcut = title in self.SHORTCUTS
            tiles = []
            for i, key in enumerate(group):
                label = self._label(key)
                b = QToolButton(inner)
                b.setObjectName(("recent_" if title == "Recent"
                                 else "favourite_" if shortcut
                                 else "hatch_")
                                + ("frame" if key is None else key))
                b.setToolButtonStyle(Qt.ToolButtonIconOnly)
                b.setIcon(QIcon(hatch_swatch(key, *self.TILE, dpr=dpr,
                                             families=self._families(key))))
                b.setIconSize(QSize(*self.TILE))
                b.setFixedSize(self.TILE[0] + 10, self.TILE[1] + 10)
                b.setToolTip(label)
                b.setAccessibleName(label)
                b.setStyleSheet(self._TILE_CSS)
                b.setProperty("hatch", key)
                b.installEventFilter(self)
                b.clicked.connect(lambda _c=False, k=key: self._pick(k))
                if shortcut:
                    (self.recent_buttons if title == "Recent"
                     else self.favourite_buttons)[key] = b
                else:
                    b.setCheckable(True)
                    b.setChecked(key == current)
                    self._patterns.addButton(b)
                    self.buttons[key] = b
                grid.addWidget(b, row + i // self.COLUMNS, i % self.COLUMNS)
                tiles.append((key, b))
            self._sections.append((title, head, tiles))
            row += (len(group) + self.COLUMNS - 1) // self.COLUMNS
        self._grid_layout = grid
        self.nothing = QLabel(inner)
        self.nothing.setAlignment(Qt.AlignCenter)
        self.nothing.setStyleSheet("padding: 16px;")
        self.nothing.hide()
        grid.addWidget(self.nothing, row, 0, 1, self.COLUMNS)
        grid.setRowStretch(row + 1, 1)
        grid.setColumnStretch(self.COLUMNS, 1)    # tiles packed to the left
        self.scroll.setWidget(inner)
        return inner

    @classmethod
    def favourites(cls) -> list:
        """The pinned patterns, in the order they were pinned."""
        from PySide6.QtCore import QSettings
        raw = QSettings().value(cls.FAVOURITES_KEY, []) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(k) for k in raw if k][:cls.FAVOURITES_MAX]

    def set_favourite(self, key, on: bool) -> None:
        """Pin ``key`` among the favourites, or unpin it — the grid shows
        it at once, first of all, and keeps it for next time."""
        from PySide6.QtCore import QSettings
        if not key:
            return
        keys = [k for k in self.favourites() if k != key]
        if on:
            keys.append(key)
        QSettings().setValue(self.FAVOURITES_KEY, keys[:self.FAVOURITES_MAX])
        bar = self.scroll.verticalScrollBar()
        at = bar.value()
        self._build_tiles(self._groups(), self._current)
        self._filter(self.search.text())
        QTimer.singleShot(0, lambda: bar.setValue(at))
        self._refresh_preview()

    def _pin_menu(self, key, at) -> None:
        """A tile's right-click: pin it, or unpin it."""
        menu = QMenu(self)
        pinned = key in self.favourites()
        menu.addAction(tr("Remove from favourites") if pinned
                       else tr("Pin to favourites"),
                       lambda: self.set_favourite(key, not pinned))
        menu.exec(at)

    # ---- names, families and the recently used ---------------------------
    def _label(self, key) -> str:
        from core.hatches import HATCH_LABELS, IMPORTED
        if key in HATCH_LABELS:
            return tr(HATCH_LABELS[key])
        if isinstance(key, str) and key.startswith(IMPORTED):
            name = key[len(IMPORTED):]
            label = (self._imported.get(name) or {}).get("label") or name
            return name if label == name else f"{name} — {label}"
        return tr("No hatch (the frame's fill)")

    def _families(self, key):
        from core.hatches import BRICKS, IMPORTED, brick_families
        if isinstance(key, str) and key.startswith(IMPORTED):
            return (self._imported.get(key[len(IMPORTED):]) or {}).get(
                "families")
        brick = self._brick_now()
        if key in BRICKS and brick is not None:
            return brick_families(key, brick)
        return None

    @classmethod
    def recent(cls) -> list:
        """The patterns used last, newest first."""
        from PySide6.QtCore import QSettings
        raw = QSettings().value(cls.RECENT_KEY, []) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(k) for k in raw if k][:cls.RECENT_MAX]

    @classmethod
    def remember(cls, key) -> None:
        """Put ``key`` first among the recently used."""
        if not key:
            return
        from PySide6.QtCore import QSettings
        keys = [key] + [k for k in cls.recent() if k != key]
        QSettings().setValue(cls.RECENT_KEY, keys[:cls.RECENT_MAX])

    #: QSettings key of the «More settings» opened, per section.
    MORE_KEY = "layers/hatch_more_settings"

    def _more(self, name: str, widgets):
        """«More settings ▸»: the seldom used settings of a section folded
        under a small switch — the section shows what is set nearly always,
        the rest one click away, remembered for next time."""
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QVBoxLayout
        holder = QWidget(self)
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 2, 0, 0)
        col.setSpacing(2)
        switch = QToolButton(holder)
        switch.setObjectName(f"more_{name}")
        switch.setCheckable(True)
        switch.setAutoRaise(True)
        switch.setStyleSheet("QToolButton { font-size: 8pt; border: none;"
                             " padding: 1px 0; }")
        col.addWidget(switch, 0, Qt.AlignLeft)
        box = QWidget(holder)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(2)
        for w in widgets:
            inner.addWidget(w)
        col.addWidget(box)
        if not hasattr(self, "more_buttons"):
            self.more_buttons, self.more_boxes = {}, {}
        self.more_buttons[name], self.more_boxes[name] = switch, box
        opened = name in (QSettings().value(self.MORE_KEY, []) or [])

        def show(on: bool) -> None:
            box.setVisible(on)
            switch.setText(("▾ " + tr("Fewer settings")) if on
                           else ("▸ " + tr("More settings")))
            keys = [k for k in (QSettings().value(self.MORE_KEY, []) or [])
                    if k != name]
            QSettings().setValue(self.MORE_KEY, keys + ([name] if on else []))
        switch.toggled.connect(show)
        switch.setChecked(opened)
        show(opened)
        return holder

    def _section(self, title: str):
        """A section's title: small capitals in the quiet colour, a rule
        under it — what groups the settings at a glance."""
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QLabel
        label = QLabel(title.upper(), self)
        label.setStyleSheet(
            "font-size: 7.5pt; font-weight: bold; letter-spacing: 1px;"
            " padding: 0 0 2px 0; margin: 0;"
            " border-bottom: 1px solid palette(mid);")
        # Flush left with the fields under it: a framed label indents its
        # text otherwise.
        label.setIndent(0)
        label.setContentsMargins(0, 0, 0, 0)
        label.setForegroundRole(QPalette.PlaceholderText)
        return label

    def _form_row(self):
        """Angle and scale of the pattern, and whether it keeps its size on
        paper or grows with the drawing's scale."""
        from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QGridLayout,
                                       QLabel)
        row = QGridLayout()
        row.setHorizontalSpacing(6)
        row.setVerticalSpacing(2)
        caption = QLabel(tr("Angle"), self)
        caption.setStyleSheet("font-size: 8pt; font-weight: bold;")
        row.addWidget(caption, 0, 0)
        self.angle_spin = QDoubleSpinBox(self)
        self.angle_spin.setRange(0.0, 359.0)
        self.angle_spin.setSingleStep(15.0)
        self.angle_spin.setDecimals(0)
        self.angle_spin.setWrapping(True)
        self.angle_spin.setSuffix(" °")
        self.angle_spin.setValue(self._form["hatch_angle"])
        self.angle_spin.setToolTip(tr("Turn the pattern (steps of 15°)"))
        row.addWidget(self.angle_spin, 0, 1)
        caption = QLabel(tr("Scale"), self)
        caption.setStyleSheet("font-size: 8pt; font-weight: bold;")
        row.addWidget(caption, 0, 2)
        self.scale_spin = QDoubleSpinBox(self)
        self.scale_spin.setRange(0.1, 10.0)
        self.scale_spin.setSingleStep(0.25)
        self.scale_spin.setDecimals(2)
        self.scale_spin.setPrefix("× ")
        self.scale_spin.setValue(self._form["hatch_scale"])
        self.scale_spin.setToolTip(tr(
            "The pattern this many times its size (× 1: its own size)"))
        row.addWidget(self.scale_spin, 0, 3)
        self.drawing_check = QCheckBox(tr("Grows with the drawing scale"),
                                       self)
        self.drawing_check.setStyleSheet("font-size: 8pt;")
        self.drawing_check.setToolTip(tr(
            "Off: the pattern measures the same on paper at any scale. On: "
            "it grows and shrinks with the frame's scale, like the real "
            "bricks or tiles — its own size is the one at 1:100"))
        self.drawing_check.setStatusTip(tr(
            "Materials with a real size — brick, block, tiles, boards, "
            "pavers — grow with the drawing by themselves; stipples and "
            "generic hatches keep their size on paper"))
        self.drawing_check.setChecked(not self._form["hatch_on_paper"])
        # Placed under the angle and scale by the caller.
        self.cross_check = QCheckBox(tr("Cross where cut across the grain"),
                                     self)
        self.cross_check.setStyleSheet("font-size: 8pt;")
        self.cross_check.setToolTip(tr(
            "For wood: pieces cut across the grain — studs, joists, beams "
            "in section — get a cross from corner to corner; boards and "
            "beams cut along keep this pattern. The grain runs the way each "
            "piece is longest: a piece that goes on further through the cut "
            "than within it is cut across"))
        self.cross_check.setChecked(self._form["hatch_cross"])
        # Shown in a section of its own (Wood), only for wood.
        row.setColumnStretch(4, 1)
        # Where the pieces start — only for the patterns of pieces
        # (core.hatches.PLACED): a second row of the same grid, «Start X»
        # under «Angle» and «Y» under «Scale», the fields edge to edge.
        where = tr(
            "Where the pieces start. Brickwork begins as it is laid: a whole "
            "brick at the end of each wall, the first course at its foot. "
            "Move it from there, in real millimetres")
        self.offset_spins = []
        self.offset_widgets = []
        shift = self._form["hatch_offset"] or (0.0, 0.0)
        for col, (axis, value, tip) in enumerate((
                (tr("Start X"), shift[0],
                 tr("Move the pattern sideways — brickwork: the first joint "
                    "along the wall, in a plan")),
                ("Y", shift[1],
                 tr("Move the pattern up — brickwork: the first course up "
                    "the wall, in a section")))):
            caption = QLabel(axis, self)
            caption.setStyleSheet("font-size: 8pt; font-weight: bold;")
            caption.setToolTip(where)
            row.addWidget(caption, 1, 2 * col)
            spin = QDoubleSpinBox(self)
            spin.setRange(-5000.0, 5000.0)
            spin.setSingleStep(10.0)
            spin.setDecimals(0)
            spin.setSuffix(" mm")
            spin.setValue(float(value))
            spin.setToolTip(tip)
            spin.valueChanged.connect(self._form_changed)
            row.addWidget(spin, 1, 2 * col + 1)
            self.offset_spins.append(spin)
            self.offset_widgets += [caption, spin]
        self.angle_spin.valueChanged.connect(self._form_changed)
        self.scale_spin.valueChanged.connect(self._form_changed)
        self.drawing_check.toggled.connect(self._paper_chosen)
        self.cross_check.toggled.connect(self._form_changed)
        return row

    def _brick_row(self):
        """The brick a brickwork pattern is drawn with: one of the usual
        sizes, or the layer's own — length, width, height and joint. Only
        for the brickwork patterns: greyed out for any other."""
        from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                                       QGridLayout, QLabel, QPushButton)
        from core.hatches import _BRICK_LIMITS, BRICK_SIZES

        def mm(v):
            return f"{v:g}"
        box = QWidget(self)
        row = QGridLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(4)
        row.setVerticalSpacing(2)
        caption = QLabel(tr("Piece size"), box)
        caption.setStyleSheet("font-size: 8pt; font-weight: bold;")
        row.addWidget(caption, 0, 0, 1, 4)
        caption.hide()                 # the section's title says it
        self.brick_combo = QComboBox(box)
        self.brick_combo.setToolTip(tr(
            "The brick the bond is drawn with: its courses, its joints and "
            "how many bricks fit across each wall"))
        self._fill_sizes()
        row.addWidget(self.brick_combo, 1, 0, 1, 4)
        # Its measures in a line — the fields are under «More settings».
        self.piece_summary = QLabel(box)
        self.piece_summary.setStyleSheet("font-size: 8pt;")
        row.addWidget(self.piece_summary, 2, 0, 1, 4)
        more = QGridLayout()
        more.setContentsMargins(0, 0, 0, 0)
        more.setHorizontalSpacing(4)
        more.setVerticalSpacing(2)
        self.brick_spins = []
        # Length, width, height; the bed joint (horizontal, under each
        # course) and the head joint (vertical, between two bricks) with a
        # padlock between: closed, they are one, typed in the bed joint;
        # open, each its own.
        fields = ((tr("Length"), tr("The brick's length (the stretcher)"),
                   2, 0),
                  (tr("Width"), tr("The brick's width (the header)"), 2, 1),
                  (tr("Height"), tr("The brick's height"), 2, 2),
                  (tr("Bed joint"), tr(
                      "The horizontal joint, under each course"), 4, 0),
                  (tr("Head joint"), tr(
                      "The vertical joint, between two bricks of a course "
                      "and between the wythes of a wall"), 4, 2))
        for i, (label, tip, r, c) in enumerate(fields):
            head = QLabel(label, box)
            head.setStyleSheet("font-size: 8pt;")
            more.addWidget(head, r, c)
            spin = QDoubleSpinBox(box)
            spin.setRange(*_BRICK_LIMITS[min(i, 3)])
            spin.setDecimals(1)
            spin.setSingleStep(5.0 if i < 3 else 1.0)
            spin.setButtonSymbols(QDoubleSpinBox.NoButtons)
            spin.setSuffix(" mm")
            spin.setToolTip(tip)
            spin.setAccessibleName(label)
            more.addWidget(spin, r + 1, c)
            self.brick_spins.append(spin)
        self.joint_lock = QToolButton(box)
        self.joint_lock.setObjectName("joint_lock")
        self.joint_lock.setCheckable(True)
        self.joint_lock.setChecked(True)
        self.joint_lock.setAutoRaise(True)
        self.joint_lock.setFixedSize(26, 24)
        self.joint_lock.setStyleSheet(
            "QToolButton { font-size: 11pt; border: 1px solid transparent;"
            " border-radius: 4px; }"
            "QToolButton:hover { border-color: palette(mid); }")
        self.joint_lock.toggled.connect(self._joint_lock_toggled)
        more.addWidget(self.joint_lock, 5, 1, Qt.AlignCenter)
        # Make it the document's: every layer's brick, in one go.
        self.brick_document = QPushButton(tr("Use in the whole document"),
                                          box)
        self.brick_document.setStyleSheet(
            "QPushButton { font-size: 8pt; padding: 2px 10px;"
            " border: 1px solid palette(mid); border-radius: 10px; }"
            "QPushButton:hover { background: palette(midlight); }")
        self.brick_document.setToolTip(tr(
            "Every layer of this kind of piece takes it — chosen once for "
            "the whole document; a layer can still set its own afterwards"))
        self.brick_document.clicked.connect(self._brick_to_document)
        # Keep a size of one's own in the list, for every document.
        self.brick_save = QPushButton(tr("Save this size"), box)
        self.brick_save.setStyleSheet(self.brick_document.styleSheet())
        self.brick_save.setToolTip(tr(
            "Keep these measures in the list of this kind of piece (marked "
            "★), in every document"))
        self.brick_save.clicked.connect(self._save_or_remove_size)
        # Under the brick's fields, which they are about.
        buttons = QHBoxLayout()
        buttons.setSpacing(4)
        buttons.addWidget(self.brick_document)
        buttons.addWidget(self.brick_save)
        buttons.addStretch(1)
        more.addLayout(buttons, 6, 0, 1, 4)
        self.brick_problem = QLabel(box)
        self.brick_problem.setStyleSheet("font-size: 8pt; color: #c0392b;")
        self.brick_problem.hide()
        more.addWidget(self.brick_problem, 9, 0, 1, 4)
        # The joints: by the scale, or as the layer says — and the mortar.
        head = QLabel(tr("Joints"), box)
        head.setStyleSheet("font-size: 8pt; font-weight: bold;")
        more.addWidget(head, 7, 0)
        self.joints_combo = QComboBox(box)
        self.joints_combo.setToolTip(tr(
            "Automatic: a 45° hatch at 1:75 and smaller, the joints as single "
            "lines from 1:50 to 1:20, the joints at their real thickness at "
            "1:15 and larger"))
        for value, label in self.JOINTS:
            self.joints_combo.addItem(tr(label), value)
        self.joints_combo.setCurrentIndex(
            [v for v, _l in self.JOINTS].index(self._joints)
            if self._joints in [v for v, _l in self.JOINTS] else 0)
        more.addWidget(self.joints_combo, 7, 1, 1, 3)
        self.mortar_check = QCheckBox(tr("Mortar in the joints"), box)
        self.mortar_check.setStyleSheet("font-size: 8pt;")
        self.mortar_check.setToolTip(tr(
            "The joints of real thickness filled in light grey, the bricks "
            "on the ground colour"))
        self.mortar_check.setChecked(self._mortar)
        more.addWidget(self.mortar_check, 8, 0, 1, 4)
        self.joints_combo.activated.connect(self._joints_chosen)
        self.mortar_check.toggled.connect(self._joints_chosen)
        fields = QWidget(box)
        fields.setLayout(more)
        row.addWidget(self._more("piece", [fields]), 3, 0, 1, 4)
        self._show_brick(self._brick_now())
        self.brick_combo.activated.connect(self._brick_size_chosen)
        for spin in self.brick_spins:
            spin.valueChanged.connect(self._brick_typed)
        self.brick_box = box
        return box

    def _joints_chosen(self, *_a) -> None:
        self._joints = self.joints_combo.currentData()
        self._mortar = self.mortar_check.isChecked()
        self._refresh_preview()
        self.form_picked.emit({"joints": self._joints,
                               "mortar": self._mortar})

    #: QSettings key of the piece sizes saved by the user, by kind: their
    #: own bricks and blocks, offered in every document.
    OWN_PIECES_KEY = "layers/own_pieces"

    @classmethod
    def own_pieces(cls) -> dict:
        """``{kind: [size, …]}`` the user saved (core.hatches.clean_brick
        sizes)."""
        from PySide6.QtCore import QSettings
        from core.hatches import clean_brick
        try:
            raw = json.loads(str(QSettings().value(cls.OWN_PIECES_KEY, "{}")))
        except (TypeError, ValueError):
            return {}
        out = {}
        for kind, sizes in (raw.items() if isinstance(raw, dict) else ()):
            kept = [clean_brick(v) for v in sizes or ()
                    if isinstance(v, (list, tuple))]
            kept = [v for v in kept if v is not None]
            if kept:
                out[str(kind)] = kept
        return out

    @classmethod
    def _save_own_pieces(cls, pieces: dict) -> None:
        from PySide6.QtCore import QSettings
        QSettings().setValue(cls.OWN_PIECES_KEY, json.dumps(
            {k: [list(v) for v in sizes] for k, sizes in pieces.items()
             if sizes}))

    def _sizes(self) -> list:
        """The sizes offered for the kind of piece: the usual ones, then the
        ones the user saved — ``[(size, own)]``."""
        from core.hatches import PIECE_SIZES
        return ([(size, False) for _n, size in PIECE_SIZES[self._kind]]
                + [(size, True)
                   for size in self.own_pieces().get(self._kind, ())])

    def _fill_sizes(self) -> None:
        """The sizes of the kind of piece the fields set — by their
        measures alone, the usual ones then the user's own (★) — and
        «Custom»."""
        def mm(v):
            return f"{v:g}"
        self.brick_combo.blockSignals(True)
        self.brick_combo.clear()
        for size, own in self._sizes():
            self.brick_combo.addItem(
                ("★ " if own else "")
                + f"{mm(size[0])} × {mm(size[1])} × {mm(size[2])}")
        self.brick_combo.addItem(tr("Custom"))
        self.brick_combo.blockSignals(False)

    def _preset_index(self, size) -> int:
        from core.hatches import brick_dims
        size = brick_dims(size, self._kind)
        for i, (preset, _own) in enumerate(self._sizes()):
            if all(abs(a - b) < 1e-6
                   for a, b in zip(brick_dims(preset, self._kind), size)):
                return i
        return -1

    def _show_saved_state(self) -> None:
        """«Save this size» while the fields hold one not in the list,
        «Remove from the list» on one the user saved."""
        b = getattr(self, "brick_save", None)
        if b is None:
            return
        size = self._brick_fields()
        i = self._preset_index(size) if size is not None else -1
        sizes = self._sizes()
        own = 0 <= i < len(sizes) and sizes[i][1]
        b.setText(tr("Remove from the list") if own
                  else tr("Save this size"))
        b.setEnabled(size is not None and (own or i < 0))

    def _save_or_remove_size(self) -> None:
        """Keep the size in the fields in the list of this kind, for every
        document — or take a saved one out of it."""
        from core.hatches import brick_dims
        size = self._brick_fields()
        if size is None:
            return
        pieces = self.own_pieces()
        mine = pieces.setdefault(self._kind, [])
        dims = brick_dims(size, self._kind)
        same = [v for v in mine
                if all(abs(a - b) < 1e-6
                       for a, b in zip(brick_dims(v, self._kind), dims))]
        if same:
            for v in same:
                mine.remove(v)
        elif self._preset_index(size) < 0:
            mine.append(size)
        self._save_own_pieces(pieces)
        self._fill_sizes()
        i = self._preset_index(size)
        self.brick_combo.setCurrentIndex(
            i if i >= 0 else self.brick_combo.count() - 1)
        self._show_saved_state()

    def _brick_now(self):
        """The piece the layer is drawn with: its own, else the
        document's of its kind (``None``: the usual one)."""
        return (self._brick if self._brick is not None
                else self._doc_bricks.get(self._kind))

    def _brick_to_document(self) -> None:
        """«Use in the whole document»: the piece shown becomes the
        document's of its kind, and the layer follows it (no piece of its
        own). Emits ``(kind, size)`` — ``None`` for the usual one."""
        from core.hatches import PIECE_DEFAULT
        size = self._brick_fields()
        if size is None:
            return
        size = None if size == PIECE_DEFAULT[self._kind] else size
        if size is None:
            self._doc_bricks.pop(self._kind, None)
        else:
            self._doc_bricks[self._kind] = size
        self._brick = None
        self._refresh_preview()
        self.brick_for_document.emit((self._kind, size))

    def _kind_changed(self) -> None:
        """Another kind of piece picked (a block after a brick): its own
        list, and its size — the document's, or its usual one."""
        from core.hatches import piece_kind
        kind = piece_kind(self._current)
        if kind is None or kind == self._kind:
            return
        self._kind = kind
        self._brick = None
        self._fill_sizes()
        self._show_brick(self._brick_now())

    def _joint_lock_toggled(self, locked: bool) -> None:
        """The padlock: closed, one joint (the head joint follows the bed
        joint, greyed out); open, each typed on its own."""
        self.joint_lock.setText("🔒" if locked else "🔓")
        self.joint_lock.setToolTip(
            tr("Joints locked: one measure, typed in the bed joint")
            if locked else tr("Joints unlocked: the bed and the head joint "
                              "each their own measure"))
        head = self.brick_spins[4]
        head.setEnabled(not locked)
        if locked and abs(head.value() - self.brick_spins[3].value()) > 1e-9:
            head.setValue(self.brick_spins[3].value())   # → _brick_typed

    def _brick_fields(self):
        """The brick as the fields hold it: one joint while the padlock is
        closed."""
        from core.hatches import clean_brick
        values = [spin.value() for spin in self.brick_spins]
        if self.joint_lock.isChecked():
            values[4] = values[3]
        return clean_brick(values)

    def _piece_line(self, dims) -> None:
        """The piece's measures in one line: length × width × height and
        its joint (or its two)."""
        bed, head = dims[3], dims[4]
        joint = (f"{bed:g}" if abs(bed - head) < 1e-9
                 else f"{bed:g} / {head:g}")
        self.piece_summary.setText(
            f"{dims[0]:g} × {dims[1]:g} × {dims[2]:g} mm  ·  "
            f"{tr('joint')} {joint} mm")

    def _show_brick(self, size) -> None:
        from core.hatches import brick_dims
        dims = brick_dims(size, self._kind)
        self._piece_line(dims)
        for spin, v in zip(self.brick_spins, dims):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
        self.joint_lock.blockSignals(True)
        self.joint_lock.setChecked(abs(dims[3] - dims[4]) < 1e-9)
        self.joint_lock.blockSignals(False)
        self._joint_lock_toggled(self.joint_lock.isChecked())
        size = dims
        i = self._preset_index(size)
        self.brick_combo.setCurrentIndex(
            i if i >= 0 else self.brick_combo.count() - 1)
        self._show_saved_state()

    def _brick_size_chosen(self, index: int) -> None:
        sizes = self._sizes()
        size = sizes[index][0] if index < len(sizes) else None
        if size is None:               # «Custom»: the fields are the brick
            self.more_buttons["piece"].setChecked(True)
            self.brick_spins[0].setFocus()
            return
        self._show_brick(size)
        self._brick_typed()

    def _brick_typed(self, *_a) -> None:
        from core.hatches import PIECE_DEFAULT
        if self.joint_lock.isChecked():
            # One joint: the head joint shows what the bed joint holds.
            head = self.brick_spins[4]
            head.blockSignals(True)
            head.setValue(self.brick_spins[3].value())
            head.blockSignals(False)
        size = self._brick_fields()
        self.brick_problem.setVisible(size is None)
        if size is None:
            self.brick_problem.setText(tr(
                "A brick is no wider than it is long"))
            return
        i = self._preset_index(size)
        self.brick_combo.setCurrentIndex(
            i if i >= 0 else self.brick_combo.count() - 1)
        self._show_saved_state()
        from core.hatches import brick_dims
        self._piece_line(brick_dims(size, self._kind))
        # The document's piece (or the usual one) is no piece of its own:
        # the layer goes on following the document.
        self._brick = (None if size == (self._doc_bricks.get(self._kind)
                                        or PIECE_DEFAULT[self._kind])
                       else size)
        self._refresh_preview()
        self.brick_picked.emit(self._brick)

    def _paper_chosen(self, *_a) -> None:
        self._paper_fixed = True
        self._form_changed()

    def _form_changed(self, *_a) -> None:
        from core.layers import clean_offset
        self._form = {"hatch_angle": float(self.angle_spin.value()) % 360.0,
                      "hatch_scale": float(self.scale_spin.value()),
                      "hatch_offset": clean_offset(
                          [s.value() for s in self.offset_spins]),
                      "hatch_on_paper": not self.drawing_check.isChecked(),
                      "hatch_cross": self.cross_check.isChecked()}
        self._refresh_preview()
        form = dict(self._form)
        if not self._paper_fixed:
            # Angle or scale changed: the size rule stays the pattern's.
            form.pop("hatch_on_paper", None)
        self.form_picked.emit(form)

    # ---- the bands' parts ------------------------------------------------
    def _choices(self, column, title, name_label, options, mine,
                 kind) -> dict:
        """A titled row of chips, one per ``(value, label)`` of ``options``,
        ``mine`` checked and named beside the title."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QButtonGroup, QLabel
        from views.hatch_paint import colour_chip
        head = QHBoxLayout()
        caption = QLabel(title, self)
        caption.setStyleSheet("font-size: 8pt; font-weight: bold;")
        name_label.setStyleSheet("font-size: 8pt;")
        head.addWidget(caption)
        head.addWidget(name_label)
        head.addStretch(1)
        column.addLayout(head)
        strip = QHBoxLayout()
        strip.setSpacing(3)
        column.addLayout(strip)
        group = QButtonGroup(self)
        fixed = [v for v, _t in options if isinstance(v, tuple)]
        buttons: dict = {}
        for value, text in options:
            b = QToolButton(self)
            b.setObjectName(f"{kind}_" + (
                "frame" if value is None else value if isinstance(value, str)
                else "%.2f" % value[0]))
            b.setToolTip(tr(text))
            b.setCheckable(True)
            b.setStyleSheet(self._TILE_CSS)
            if value == "other":
                # A chip like the others — same size, same frame — the
                # name beside it, so it still reads as «any other».
                on = isinstance(mine, tuple) and mine not in fixed
                self._other_icon(b, mine if on else None, kind)
                b.setIconSize(QSize(*self.CHIP))
                b.setText(tr(text))
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            else:
                on = mine == value
                rgb = self._resolve(value, kind)
                b.setIcon(QIcon(colour_chip(
                    *self.CHIP, QColor.fromRgbF(*rgb) if rgb else None,
                    dpr=self._dpr, strokes=kind == "ink",
                    paper=kind == "ground" and value is None,
                    badge="A" if kind == "ink" and value is None
                    else None)))
                b.setIconSize(QSize(*self.CHIP))
                b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            b.setChecked(on)
            b.clicked.connect(lambda _c=False, v=value, k=kind:
                              self._choose(v, k))
            group.addButton(b)
            strip.addWidget(b)
            buttons[value] = b
        strip.addStretch(1)
        self._name_choice(kind)
        return buttons

    def _other_icon(self, button, rgb, kind) -> None:
        """«Other colour…»'s chip: every hue, or the colour picked."""
        from views.hatch_paint import any_colour_chip
        # The same chip in both rows: the colour itself, whether it goes
        # under the hatch or into its lines.
        button.setIcon(QIcon(any_colour_chip(
            *self.CHIP, QColor.fromRgbF(*rgb) if rgb else None,
            dpr=self._dpr)))

    def _resolve(self, value, kind):
        """The RGB a ground or an ink shows; ``None`` for the paper / the
        frame's own."""
        if value == L.GROUND_LAYER and self._layer is not None:
            return (L.light_layer_color(self._layer) if kind == "ground"
                    else tuple(c * 0.7 for c in L.layer_color(self._layer)))
        if value == L.GROUND_LAYER:
            return (0.85, 0.80, 0.70) if kind == "ground" else (0.55, 0.35,
                                                                  0.25)
        return value if isinstance(value, tuple) else None

    def _name_choice(self, kind) -> None:
        options, mine, label = ((self.GROUNDS, self._ground,
                                 getattr(self, "ground_name", None))
                                if kind == "ground" else
                                (self.INKS, self._ink,
                                 getattr(self, "ink_name", None)))
        if label is None:
            return
        name = next((t for v, t in options if v == mine), None)
        label.setText("· " + tr(name if name else "Other colour…"))

    def _refresh_preview(self) -> None:
        from views.hatch_paint import hatch_swatch
        key = self._hover if self._hover is not None else self._current
        ground = self._resolve(self._ground, "ground")
        ink = self._resolve(self._ink, "ink")
        form = getattr(self, "_form", {})
        for w in getattr(self, "offset_widgets", ()):
            from core.hatches import PLACED
            w.setVisible(self._current in PLACED)
        box = getattr(self, "brick_box", None)
        if box is not None:
            from core.hatches import COURSED, WOOD, brick_dims, piece_kind
            sized = piece_kind(self._current) is not None
            box.setEnabled(self._current in COURSED)
            self.piece_section.setVisible(self._current in COURSED)
            self.wood_section.setVisible(self._current in WOOD)
            for w in [self.brick_combo, self.joint_lock] + \
                    self.brick_spins[:4]:
                w.setEnabled(sized)
            self.brick_spins[4].setEnabled(
                sized and not self.joint_lock.isChecked())
            from views.hatch_paint import piece_axo
            self.piece_view.setVisible(sized)
            if sized:
                self.piece_view.setPixmap(piece_axo(
                    self._kind, brick_dims(self._brick_now(), self._kind),
                    *self.PIECE_VIEW, ink=self.palette().text().color(),
                    dpr=self._dpr))
            self.cross_check.setEnabled(self._current in WOOD)
        self.preview.setPixmap(hatch_swatch(
            key, *self.PREVIEW, dpr=self._dpr,
            ground=QColor.fromRgbF(*ground) if ground and key else None,
            ink=QColor.fromRgbF(*ink) if ink else None,
            angle=form.get("hatch_angle", 0.0),
            scale=form.get("hatch_scale", 1.0),
            families=self._families(key)))
        self.preview_name.setText(self._label(key))
        star = getattr(self, "star", None)
        if star is not None:
            pinned = self._current in self.favourites()
            star.setEnabled(self._current is not None)
            star.setChecked(pinned)
            star.setText("★" if pinned else "☆")
            star.setToolTip(tr("Remove from favourites") if pinned
                            else tr("Pin to favourites"))
        from views.hatch_paint import cut_tile, has_cut_preview
        cut = getattr(self, "cut_preview", None)
        if cut is not None:
            crossed = bool(form.get("hatch_cross")) and key == self._current
            shown = has_cut_preview(key, crossed)
            cut.setVisible(shown)
            self.cut_same.setVisible(not shown and key is not None)
            if shown:
                look = dict(ink=QColor.fromRgbF(*ink) if ink else None,
                            dpr=self._dpr,
                            ground=(QColor.fromRgbF(*ground) if ground
                                    else None),
                            brick=self._brick_now(),
                            cross=crossed,
                            joints=getattr(self, "_joints", None),
                            mortar=getattr(self, "_mortar", False))
                self.plan_tile.setPixmap(cut_tile(key, "plan",
                                                  *self.PLAN_TILE, **look))
                self.section_tile.setPixmap(cut_tile(
                    key, "vertical", *self.SECTION_TILE, **look))

    # ---- what a click does -------------------------------------------------
    def _pick(self, key, remember: bool = True) -> None:
        self._current = key
        if getattr(self, "brick_combo", None) is not None:
            self._kind_changed()
        if not self._paper_fixed:
            # The layer has not chosen: the checkbox follows the pattern.
            from core.hatches import REAL_SIZE
            self.drawing_check.blockSignals(True)
            self.drawing_check.setChecked(key in REAL_SIZE)
            self.drawing_check.blockSignals(False)
            self._form["hatch_on_paper"] = key not in REAL_SIZE
        b = self.buttons.get(key)
        if b is not None:
            b.setChecked(True)
            # The grid may shrink as the settings for this pattern show:
            # the tile stays in sight.
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(
                b, 0, 24))
        if remember:
            self.remember(key)
        self._refresh_preview()
        self.picked.emit(key)

    #: The arrow keys and the way each moves through the grid.
    _ARROWS = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
               Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}

    def _step(self, key) -> bool:
        """Move the chosen pattern one tile with arrow ``key`` — left and
        right through the list, up and down to the row above or below (the
        tile nearest in its column), across the groups — among the tiles
        the search leaves, and bring it into sight. From no pattern, any
        arrow starts at the first. Whether it moved."""
        dx, dy = self._ARROWS[key]
        grid = self._grid_layout
        tiles = []
        for title, _head, group in self._sections:
            if title in self.SHORTCUTS:
                continue
            for k, b in group:
                if b.isHidden():
                    continue
                row, col, _rs, _cs = grid.getItemPosition(grid.indexOf(b))
                tiles.append((row, col, k, b))
        if not tiles:
            return False
        tiles.sort(key=lambda t: (t[0], t[1]))
        here = next((t for t in tiles if t[2] == self._current), None)
        if here is None:
            target = tiles[0]
        elif dx:
            i = tiles.index(here) + dx
            if not 0 <= i < len(tiles):
                return False
            target = tiles[i]
        else:
            rows = sorted({t[0] for t in tiles
                           if (t[0] > here[0] if dy > 0 else t[0] < here[0])})
            if not rows:
                return False
            row = rows[0] if dy > 0 else rows[-1]
            target = min((t for t in tiles if t[0] == row),
                         key=lambda t: abs(t[1] - here[1]))
        # Every step applies, as a click would; the list of the recently
        # used takes only where the keys stop («Done»).
        self._pick(target[2], remember=False)
        self.scroll.ensureWidgetVisible(target[3], 0, 24)
        return True

    def _choose(self, value, kind) -> None:
        if value == "other":
            # Chosen inside the picker: a window of its own would close it
            # (it is a popup), and the colour would land with no «Done».
            self.ask_colour(kind)
            return
        if kind == "ground":
            self._ground = value
            self.ground_picked.emit(value)
        else:
            self._ink = value
            self.ink_picked.emit(value)
        self._name_choice(kind)
        self._refresh_preview()

    def ask_colour(self, kind) -> None:
        """«Other colour…»: a colour chooser in a window of its own over the
        picker, the picker left open behind it — «Use this colour» brings
        it back with that colour, «Back» (Esc, or a click outside) with
        what was there; «Done» still keeps the lot. A popup opened from the
        picker's own popup, as a submenu is: any other window would close
        the picker."""
        from PySide6.QtWidgets import (QColorDialog, QFrame, QLabel,
                                       QPushButton, QVBoxLayout)
        page = getattr(self, "colour_page", None)
        if page is None:
            page = self.colour_page = _ColourWindow(self)
            page.setObjectName("hatch_colour_page")
            page.closed.connect(self._colour_dropped)
            box = QVBoxLayout(page)
            box.setContentsMargins(16, 12, 16, 12)
            box.setSpacing(8)
            self.colour_title = QLabel(page)
            self.colour_title.setStyleSheet("font-weight: bold;")
            box.addWidget(self.colour_title)
            dlg = self.colour_dialog = QColorDialog(page)
            dlg.setWindowFlags(Qt.Widget)
            dlg.setOptions(QColorDialog.DontUseNativeDialog
                           | QColorDialog.NoButtons)
            # Enter and Esc inside the chooser: use the colour, go back.
            dlg.accepted.connect(self._colour_taken)
            dlg.rejected.connect(self._colour_dropped)
            box.addWidget(dlg)
            row = QHBoxLayout()
            row.addStretch(1)
            back = self.colour_back = QPushButton(tr("Back to the hatch"), page)
            back.clicked.connect(self._colour_dropped)
            row.addWidget(back)
            use = self.colour_use = QPushButton(tr("Use this colour"), page)
            use.setDefault(True)
            use.clicked.connect(self._colour_taken)
            row.addWidget(use)
            box.addLayout(row)
        self._asking = kind
        mine = self._ground if kind == "ground" else self._ink
        start = (QColor.fromRgbF(*mine) if isinstance(mine, tuple)
                 else QColor(220, 220, 220))
        self.colour_dialog.setCurrentColor(start)
        self.colour_title.setText(tr("Ground under the hatch")
                                  if kind == "ground"
                                  else tr("Colour of the hatch"))
        self.colour_dialog.show()
        page.adjustSize()
        # Over the middle of the picker, which stays where it is.
        centre = self.mapToGlobal(self.rect().center())
        page.move(centre.x() - page.width() // 2,
                  centre.y() - page.height() // 2)
        page.show()
        page.raise_()
        self.colour_use.setFocus()

    def _colour_page_closed(self) -> str | None:
        kind = getattr(self, "_asking", None)
        self._asking = None
        self.colour_page.hide()
        return kind

    def _colour_taken(self) -> None:
        kind = self._colour_page_closed()
        if kind is None:
            return
        value = tuple(round(c, 4) for c in
                      self.colour_dialog.currentColor().getRgbF()[:3])
        buttons = self.ground_buttons if kind == "ground" else self.ink_buttons
        self._other_icon(buttons["other"], value, kind)
        buttons["other"].setChecked(True)
        self._choose(value, kind)

    def _colour_dropped(self) -> None:
        kind = self._colour_page_closed()
        if kind is None:
            return
        # Back to what was ticked before.
        buttons = self.ground_buttons if kind == "ground" else self.ink_buttons
        mine = self._ground if kind == "ground" else self._ink
        fixed = [v for v in buttons if isinstance(v, tuple)]
        for v, b in buttons.items():
            b.setChecked(v == mine or (v == "other" and isinstance(mine, tuple)
                                       and mine not in fixed))

    def _fill_filter_menu(self) -> None:
        """The funnel's list: every pattern, or one group of them — the
        groups of the catalogue and the imported ones, the shown one
        ticked."""
        from PySide6.QtGui import QActionGroup
        menu = self.filter_menu
        menu.clear()
        group = QActionGroup(menu)
        group.setExclusive(True)
        every = menu.addAction(tr("All hatches"))
        every.setCheckable(True)
        every.setChecked(self._group is None)
        every.triggered.connect(lambda: self.filter_to(None))
        group.addAction(every)
        menu.addSeparator()
        self.group_actions = {}
        for title, _keys in self._groups():
            if title in self.SHORTCUTS:
                continue
            a = menu.addAction(tr(title))
            a.setCheckable(True)
            a.setChecked(self._group == title)
            a.triggered.connect(lambda _c=False, t=title: self.filter_to(t))
            group.addAction(a)
            self.group_actions[title] = a

    def _show_filter_state(self) -> None:
        """The funnel fills while a group narrows the grid, and says
        which."""
        from views.icons import tool_icon
        on = self._group is not None
        self.filter_btn.setIcon(tool_icon("layers_filter_on" if on
                                          else "layers_filter"))
        self.filter_btn.setToolTip(tr("Filter: {name}", name=tr(
            self._group) if on else tr("All hatches")))

    def filter_to(self, title) -> None:
        """Show one group of patterns (``title``), or all (``None``); the
        search narrows within it."""
        self._group = title
        self._show_filter_state()
        self._filter(self.search.text())
        self.scroll.verticalScrollBar().setValue(0)

    def _filter(self, text: str) -> None:
        """Only the patterns whose name holds ``text`` (any case), in the
        group the funnel shows (every group when none); a group with none
        of them hides its title too."""
        from core.layers import hatch_label
        needle = text.strip().casefold()
        group = getattr(self, "_group", None)
        shown = 0
        for title, head, tiles in self._sections:
            hits = 0
            for key, b in tiles:
                hit = ((group is None or title == group)
                       and (not needle
                            or needle in self._label(key).casefold()
                            or needle in hatch_label(None, key).casefold()))
                b.setVisible(hit)
                hits += hit
            head.setVisible(bool(hits))
            shown += hits
        self.nothing.setText(tr("No hatch is called «{text}»", text=text))
        self.nothing.setVisible(shown == 0)

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.ContextMenu and obj is not None \
                and obj.property("hatch"):
            self._pin_menu(obj.property("hatch"), event.globalPos())
            return True
        if (event.type() == QEvent.KeyPress and event.key() in self._ARROWS
                and not event.modifiers() & ~Qt.KeypadModifier):
            # A tile with the focus: the arrows walk the grid, not the
            # buttons' focus chain.
            self._step(event.key())
            return True
        if event.type() in (QEvent.Enter, QEvent.Leave):
            key = obj.property("hatch") if obj is not None else None
            self._hover = key if event.type() == QEvent.Enter else None
            self._refresh_preview()
        return False

    # A click on an empty spot of the picker (between tiles, on a caption,
    # on the preview) is kept here: passed on, the menu holding the picker
    # would take it for a pick and close.
    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()

    def keyPressEvent(self, event) -> None:
        # The arrows nothing else took (the search field keeps left and
        # right for its text; the angle, scale and size fields keep theirs)
        # walk the patterns.
        if (event.key() in self._ARROWS
                and not event.modifiers() & ~Qt.KeypadModifier):
            self._step(event.key())
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.done.emit()
            return
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class LineTypeDialog(QDialog):
    """Make or edit a line type, the way the hatch picker is laid out: the
    line itself on a card at the top, drawn as it is being made — words
    and all — then its name, its pieces in paper mm (a dash > 0, a gap
    < 0, a dot 0) typed or added with a button, and words to write along
    it (GAS, AGUA…) with their height."""

    #: The preview card, in px, and how many px a paper mm takes in it.
    PREVIEW = (420, 64)
    PX_PER_MM = 4.0

    #: The colours offered for a line type: by layer, then the usual ones of
    #: services drawings — gas yellow, water blue, power red, telecoms
    #: green — black, and any other.
    COLOURS = ((None, "By layer"), ((0.0, 0.0, 0.0), "Black"),
               ((0.85, 0.65, 0.0), "Yellow"), ((0.0, 0.40, 0.85), "Blue"),
               ((0.85, 0.10, 0.10), "Red"), ((0.0, 0.55, 0.25), "Green"),
               ("other", "Other colour…"))
    CHIP = (26, 20)

    def __init__(self, parent=None, name: str = "", pattern=None,
                 text: str = "", text_size: float = 2.5,
                 editing: bool = False, color=None) -> None:
        super().__init__(parent)
        self._colour = L.clean_line_colour(color)
        from PySide6.QtWidgets import (QDialogButtonBox, QDoubleSpinBox,
                                       QFrame, QGridLayout, QLabel,
                                       QPushButton, QVBoxLayout)
        self.setWindowTitle(tr("Edit line type") if editing
                            else tr("New line type"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)
        # 1. The line, on a card like the hatch preview.
        card = QFrame(self)
        card.setObjectName("lineTypeCard")
        card.setStyleSheet(
            "QFrame#lineTypeCard { border: 1px solid palette(mid);"
            " border-radius: 6px; background: palette(base); }")
        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 6)
        box.setSpacing(3)
        self.preview = QLabel(card)
        self.preview.setFixedSize(*self.PREVIEW)
        box.addWidget(self.preview)
        self.problem = QLabel(card)
        self.problem.setStyleSheet("font-size: 8pt; color: #c0392b;")
        self.problem.setWordWrap(True)
        box.addWidget(self.problem)
        outer.addWidget(card)

        def caption(text):
            label = QLabel(text, self)
            label.setStyleSheet("font-size: 8pt; font-weight: bold;")
            return label
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        # 2. Name.
        grid.addWidget(caption(tr("Name")), 0, 0)
        self.name_edit = QLineEdit(name or tr("My line"), self)
        grid.addWidget(self.name_edit, 0, 1, 1, 2)
        # 3. Pieces, typed or added.
        grid.addWidget(caption(tr("Pieces (mm)")), 1, 0)
        self.pattern_edit = QLineEdit(
            ", ".join(f"{v:g}" for v in (pattern or (6.0, -1.5, 0.0, -1.5))),
            self)
        self.pattern_edit.setToolTip(tr(
            "Millimetres on paper, separated by commas: a dash (6), a gap "
            "(-1.5), a dot (0)"))
        grid.addWidget(self.pattern_edit, 1, 1, 1, 2)
        quick = QHBoxLayout()
        quick.setSpacing(4)
        css = ("QPushButton { font-size: 8pt; padding: 2px 8px;"
               " border: 1px solid palette(mid); border-radius: 10px; }"
               "QPushButton:hover { background: palette(midlight); }")
        for text_, value in ((tr("+ Dash"), "3"), (tr("+ Gap"), "-1.5"),
                             (tr("+ Dot"), "0")):
            b = QPushButton(text_, self)
            b.setStyleSheet(css)
            b.clicked.connect(lambda _c=False, v=value: self._append(v))
            quick.addWidget(b)
        clear = QPushButton(tr("Clear"), self)
        clear.setStyleSheet(css)
        clear.clicked.connect(lambda: self.pattern_edit.setText(""))
        quick.addWidget(clear)
        quick.addStretch(1)
        grid.addLayout(quick, 2, 1, 1, 2)
        # 4. Words along it.
        grid.addWidget(caption(tr("Text in the line")), 3, 0)
        self.text_edit = QLineEdit(text or "", self)
        self.text_edit.setPlaceholderText(tr("GAS, AGUA, ELEC…"))
        self.text_edit.setToolTip(tr(
            "Words written along the line, in a gap of their own after the "
            "pieces — the line of a gas pipe, a water main, a cable"))
        self.text_edit.setMaxLength(24)
        grid.addWidget(self.text_edit, 3, 1)
        self.size_spin = QDoubleSpinBox(self)
        self.size_spin.setRange(0.5, 20.0)
        self.size_spin.setDecimals(1)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setSuffix(" mm")
        self.size_spin.setValue(float(text_size or 2.5))
        self.size_spin.setToolTip(tr("The height of the text on paper"))
        grid.addWidget(self.size_spin, 3, 2)
        # 5. Its colour: the layer's, or one of its own.
        grid.addWidget(caption(tr("Colour")), 4, 0)
        grid.addLayout(self._colour_row(), 4, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        #: «Delete line type» pressed (editing only): the caller deletes it.
        self.deleted = False
        if editing:
            gone = self.buttons.addButton(tr("Delete line type"),
                                          QDialogButtonBox.DestructiveRole)
            gone.clicked.connect(self._delete)
        outer.addWidget(self.buttons)
        for edit in (self.pattern_edit, self.name_edit, self.text_edit):
            edit.textChanged.connect(self._refresh)
        self.size_spin.valueChanged.connect(self._refresh)
        self._refresh()

    def _delete(self) -> None:
        self.deleted = True
        self.accept()

    def _colour_row(self):
        """Chips like the hatch picker's: by layer, a few usual colours,
        any other — the one the line type has ticked."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QButtonGroup
        from views.hatch_paint import any_colour_chip, colour_chip
        row = QHBoxLayout()
        row.setSpacing(3)
        group = QButtonGroup(self)
        fixed = [v for v, _t in self.COLOURS if isinstance(v, tuple)]
        self.colour_buttons = {}
        css = HatchGrid._TILE_CSS
        for value, label in self.COLOURS:
            b = QToolButton(self)
            b.setCheckable(True)
            b.setToolTip(tr(label))
            b.setStyleSheet(css)
            b.setIconSize(QSize(*self.CHIP))
            if value is None:
                # As the hatch picker's «The layer's colour».
                b.setIcon(QIcon(colour_chip(
                    *self.CHIP, QColor.fromRgbF(0.55, 0.35, 0.25),
                    dpr=self.devicePixelRatioF(), strokes=True)))
                on = self._colour is None
            elif value == "other":
                on = self._colour is not None and self._colour not in fixed
                b.setIcon(QIcon(any_colour_chip(
                    *self.CHIP, QColor.fromRgbF(*self._colour) if on
                    else None, dpr=self.devicePixelRatioF())))
                b.setText(tr(label))
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            else:
                b.setIcon(QIcon(colour_chip(*self.CHIP,
                                            QColor.fromRgbF(*value),
                                            dpr=self.devicePixelRatioF(),
                                            strokes=True)))
                on = self._colour == value
            b.setChecked(on)
            b.clicked.connect(lambda _c=False, v=value: self._pick_colour(v))
            group.addButton(b)
            row.addWidget(b)
            self.colour_buttons[value] = b
        row.addStretch(1)
        return row

    def _pick_colour(self, value) -> None:
        if value == "other":
            from views.color_dialog import get_color
            start = (QColor.fromRgbF(*self._colour) if self._colour
                     else QColor(220, 120, 0))
            picked = get_color(start, self, tr("Other colour…"))
            if not picked.isValid():
                for v, b in self.colour_buttons.items():
                    b.setChecked(v == self._colour or (
                        v == "other" and self._colour is not None
                        and self._colour not in self.colour_buttons))
                return
            value = tuple(round(c, 4) for c in picked.getRgbF()[:3])
            from views.hatch_paint import any_colour_chip
            self.colour_buttons["other"].setIcon(QIcon(any_colour_chip(
                *self.CHIP, QColor.fromRgbF(*value),
                dpr=self.devicePixelRatioF())))
            self.colour_buttons["other"].setChecked(True)
        self._colour = value
        self._refresh()

    def result_color(self):
        """The line type's own colour, ``(r, g, b)``, or ``None`` (by
        layer)."""
        return self._colour

    def _append(self, value: str) -> None:
        text = self.pattern_edit.text().strip()
        self.pattern_edit.setText(f"{text}, {value}" if text else value)

    def name(self) -> str:
        return self.name_edit.text().strip()

    def result_pattern(self):
        """The pieces as typed, in mm, or ``None`` if they cannot be a
        line type."""
        try:
            nums = [float(v) for v in self.pattern_edit.text().replace(
                ";", ",").split(",") if v.strip()]
        except ValueError:
            return None
        return L.clean_pattern(nums)

    def result_text(self) -> tuple:
        """The words to write along the line and their height (mm); an
        empty text for none."""
        return self.text_edit.text().strip(), float(self.size_spin.value())

    def _refresh(self) -> None:
        from PySide6.QtWidgets import QApplication, QDialogButtonBox
        pattern = self.result_pattern()
        ok = pattern is not None and bool(self.name())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        self.problem.setText("" if pattern is not None else tr(
            "Use dashes and gaps: at least one piece drawn (≥ 0) and one gap "
            "(< 0)"))
        self.problem.setVisible(pattern is None)
        w, h = self.PREVIEW
        dpr = self.devicePixelRatioF()
        px = QPixmap(int(w * dpr), int(h * dpr))
        px.setDevicePixelRatio(dpr)
        px.fill(QColor(255, 255, 255))
        if pattern is not None:
            words, size = self.result_text()
            drawn, spec = L.with_text(pattern, words, size)
            p = QPainter(px)
            p.setRenderHint(QPainter.Antialiasing)
            colour = getattr(self, "_colour", None)
            ink = (QColor.fromRgbF(*colour) if colour
                   else QColor(30, 36, 44))
            k = self.PX_PER_MM
            p.setPen(line_pen("", ink, 1.6, k, L.drawn_dashes(drawn)))
            p.drawLine(QPointF(10, h / 2), QPointF(w - 10, h / 2))
            if spec is not None:
                from views.hatch_paint import paint_line_text
                paint_line_text(p, [(10.0, h / 2, w - 10.0, h / 2)],
                                (spec["text"], spec["text_size"],
                                 L.text_offset(drawn, spec["text_at"]),
                                 sum(L.drawn_dashes(drawn))), ink, k)
            p.end()
        self.preview.setPixmap(px)
        _ = QApplication


class _LineSample(QWidget):
    """One entry of the line type or line weight list: the line itself,
    drawn — its type, or its weight with the value beside it — and a tick
    on the current one. The line type's name stays as the tooltip. A click
    picks it. Both lists are made of these, so they look alike."""

    #: Where the drawn line ends when a value follows it.
    LINE_END = 86

    def __init__(self, key, action, menu, checked: bool,
                 width: float = 2.0, text: str = "", swatch=None,
                 pattern=None, words=None, actions=(),
                 colour=None, keep_open: bool = False, edit=None,
                 pick=None) -> None:
        super().__init__()
        #: The line type panel stays open on a pick (its «Done» closes it):
        #: a click runs ``pick`` — triggering the action would close it.
        self.keep_open = keep_open and pick is not None
        self.pick = pick
        #: An own line type's «Edit…»: a pencil at the right end, in sight.
        self.edit = edit
        self.key = key                     # None: no line, only the text
        #: A line type's own colour: its line drawn in it.
        self.colour = colour
        #: The dash pattern of a custom line type (else the key's own).
        self.pattern = pattern
        #: Its words (core.layers.linetype_text), drawn along the sample.
        self.words = words
        #: ``(label, callback)`` offered on a right-click (edit, delete).
        self.actions = tuple(actions)
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
        # A drawing: left to right in a mirrored interface too, or a line
        # type's words (GAS) read backwards.
        from views.rtl import keep_ltr
        keep_ltr(self)
        w = 170                       # room for two repeats of a long dash
        if text:
            w = (self.LINE_END if (key is not None or swatch is not None)
                 else 18) + 14 \
                + self.fontMetrics().horizontalAdvance(text) + 14
        if edit is not None:
            w += self.PENCIL
        self.setMinimumSize(max(120, w), 26)

    #: The room the pencil of an own line type takes at the right end.
    PENCIL = 26

    def _on_pencil(self, x: float) -> bool:
        return self.edit is not None and x >= self.width() - self.PENCIL

    def enterEvent(self, _e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._on_pencil(event.position().x()):
            self.edit()
            return
        if self.keep_open:
            self.pick()
            return
        self._menu.close()
        self._action.trigger()

    def set_checked(self, on: bool) -> None:
        self._checked = bool(on)
        self.update()

    def contextMenuEvent(self, event) -> None:
        if not self.actions:
            return
        menu = QMenu(self)
        for label, callback in self.actions:
            menu.addAction(label, lambda cb=callback: (self._menu.close(),
                                                       QTimer.singleShot(
                                                           0, cb)))
        menu.exec(event.globalPos())

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
        # Right to left (#1067) the row reads from the right: the tick, the
        # sample and the words mirror their places (not their shapes).
        rtl = self.isRightToLeft()
        if self._checked:                    # the current one: a tick
            tick = QPen(ink, 1.8)
            tick.setCapStyle(Qt.RoundCap)
            p.setPen(tick)
            cy = r.center().y()
            dx = r.width() - 25 if rtl else 0
            p.drawPolyline([QPointF(8 + dx, cy), QPointF(11 + dx, cy + 3),
                            QPointF(17 + dx, cy - 4)])
        y = r.center().y() + 0.5
        if self.edit is not None:
            # The pencil: an own line type is edited from the list.
            p.setPen(ink)
            p.drawText(QRectF(r.right() - self.PENCIL, r.top(), self.PENCIL,
                              r.height()), Qt.AlignCenter, "✎")
            r = r.adjusted(0, 0, -self.PENCIL, 0)
        end = self.LINE_END if self._text else r.right() - 12
        if rtl:
            p.save()
            p.translate(r.width(), 0)
            p.scale(-1, 1)
        if self.key is not None:
            line_ink = (QColor.fromRgbF(*self.colour) if self.colour
                        else ink)
            p.setPen(line_pen(self.key, line_ink, self._width, 3.0,
                              self.pattern))
            p.drawLine(QPointF(26, y), QPointF(end, y))
            if self.words is not None:
                from views.hatch_paint import paint_line_text
                paint_line_text(p, [(26.0, y, float(end), y)], self.words,
                                line_ink, 3.0)
        if self.swatch is not None:
            see_through_swatch(p, QRectF(26, y - 7, end - 26, 14),
                               *self.swatch, ink)
        if rtl:
            p.restore()
        if self._text:
            p.setPen(ink)
            left = end + 14 if (self.key is not None
                                or self.swatch is not None) else 26
            p.drawText(r.adjusted(0, 0, -left, 0) if rtl
                       else r.adjusted(left, 0, 0, 0),
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
        own = index.data(ROLE_LINEPATTERN)
        pattern = list(own) if own else list(L.LINETYPES.get(key, ()))
        from PySide6.QtWidgets import QApplication, QStyle
        pal = QApplication.palette()
        ink = (pal.highlightedText() if option.state & QStyle.State_Selected
               else pal.text()).color()
        r = option.rect
        # One whole repeat at least, however narrow the cell: a long-dash
        # pattern drawn at full scale would show a single dash and read as
        # any other.
        period = sum(abs(v) for v in pattern)
        room = max(1.0, r.width() - 10.0)
        ppm = (min(self.PX_PER_MM, room / (1.5 * period)) if period
               else self.PX_PER_MM)
        pen = line_pen(key, ink, 1.6, ppm, pattern)
        y = r.center().y() + 0.5
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(pen)
        painter.drawLine(QPointF(r.left() + 5, y), QPointF(r.right() - 5, y))
        painter.restore()


class _LayerTree(SideTree):
    """The layer tree, taking drops of its own rows: what is dragged goes
    into the folder dropped on — the folder of the layer dropped on, or out
    of any folder on the empty space. Qt never moves a row by itself here:
    the document changes and the tree is rebuilt from it."""

    #: The cells a press acts on directly, as in the Browser: the row's
    #: selection is left as it is, so a click on the eye of one of several
    #: selected rows acts on all of them.
    CELLS = (COL_ACTIVE, COL_EYE, COL_LOCK, COL_ISOLATE, COL_COLOR,
             COL_LINETYPE, COL_WEIGHT, COL_OPACITY, COL_PRINT, COL_CUT,
             COL_HATCH)

    #: Delete belongs to the list while it has the focus, not to a window
    #: shortcut.
    DELETE_KEY = True

    def target_folder(self, pos) -> str | None:
        """The folder a drop at `pos` (viewport coordinates) files into."""
        item = self.itemAt(pos)
        if item is None:
            return None
        kind, name = self._panel._key(item)
        if kind == KIND_FOLDER:
            return name
        parent = item.parent()
        return self._panel._key(parent)[1] if parent is not None else None

    # ---- Where a drop lands ----------------------------------------------
    def drop_target(self, pos):
        return self.target_folder(pos)

    def folder_item(self, name: str):
        """The row of folder `name`, or None."""
        it = QTreeWidgetItemIterator(self)
        while it.value() is not None:
            item = it.value()
            if self._panel._key(item) == (KIND_FOLDER, name):
                return item
            it += 1
        return None

    def drop_items(self, folder):
        """The folder's row and every row shown inside it; none for the
        empty space (the whole list, out of any folder)."""
        item = self.folder_item(folder)
        if item is None:
            return []
        items = [item]
        stack = [item]
        while stack:
            node = stack.pop()
            if not node.isExpanded():
                continue
            for i in range(node.childCount()):
                child = node.child(i)
                if child.isHidden():
                    continue
                items.append(child)
                stack.append(child)
        return items

    def drop_text(self, folder) -> str:
        return (tr("Into «{folder}»", folder=folder) if folder is not None
                else tr("Out of any folder"))

    def apply_drop(self, folder, rows) -> None:
        self._panel.drop_rows([self._panel._key(it) for it in rows], folder)


class LayersPanel(QWidget):
    """The layer tree, its filter and its buttons. See the module doc."""

    #: The rows now list the layers and folders in another order (a sort,
    #: a layer made, filed or renamed): the Browser ordering by layer
    #: follows it.
    orderChanged = Signal()

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        self._told_outline = None
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
                                   tr("Line"), "mm", "%", "", tr("Cut pen"),
                                   ""])
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col, width in ((COL_ACTIVE, 26), (COL_EYE, 26), (COL_LOCK, 26),
                           (COL_ISOLATE, 26), (COL_COLOR, 26),
                           (COL_LINETYPE, 40), (COL_WEIGHT, 40),
                           (COL_CUT, 44), (COL_HATCH, 26),
                           (COL_OPACITY, 40), (COL_PRINT, 26),
                           (COL_COUNT, 44)):
            head.setSectionResizeMode(col, QHeaderView.Fixed)
            if col == COL_CUT:
                # Its title whole, in any language («Cut pen», «Corte»).
                width = max(width, head.fontMetrics().horizontalAdvance(
                    tr("Cut pen")) + 18)
            head.resizeSection(col, width)
        hi = self.tree.headerItem()
        self._header_icons()
        hi.setToolTip(COL_ACTIVE, tr(
            "Active layer: new groups, components, dimensions, texts and "
            "guides go to it"))
        hi.setToolTip(COL_EYE, tr("Visible"))
        hi.setToolTip(COL_LOCK, tr("Locked: drawn, but it cannot be picked"))
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
        hi.setToolTip(COL_CUT, tr(
            "Cut weight in mm: the pen of the layer's section cut on the "
            "sheets (—: the sheet's cut pen) — click a row's to change it"))
        hi.setTextAlignment(COL_CUT, Qt.AlignCenter)
        # Like the colour column: no word, a swatch — here, a hatched one.
        hi.setIcon(COL_HATCH, hatch_icon("diagonal"))
        hi.setToolTip(COL_HATCH, tr(
            "Hatch of the layer's section cut on the sheets — brick, "
            "concrete, insulation… (a red slash: the frame's fill) — click a "
            "row's to pick one"))
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

    def _header_icons(self) -> None:
        """The header's pencil, eye, padlock and target, in the palette's
        ink."""
        from views.layers_toolbar import isolate_icon
        hi = self.tree.headerItem()
        self._drawn_ink = QApplication.palette().text().color().rgba()
        hi.setIcon(COL_ACTIVE, _pencil_icon(True))
        hi.setIcon(COL_EYE, node_icon("eye"))
        hi.setIcon(COL_LOCK, node_icon("lock"))
        hi.setIcon(COL_ISOLATE, isolate_icon(False))

    def changeEvent(self, event) -> None:
        """The theme changed while the app runs (Preferences ▸ theme): the
        icons are drawn in the palette's ink, so the rows, the header and
        the bar are drawn again at once — not black on the dark theme until
        the list happens to rebuild."""
        super().changeEvent(event)
        from PySide6.QtCore import QEvent
        if event.type() not in (QEvent.PaletteChange,
                                QEvent.ApplicationPaletteChange):
            return
        ink = QApplication.palette().text().color().rgba()
        if ink == getattr(self, "_drawn_ink", ink)                 or getattr(self, "_retheming", False):
            return
        self._retheming = True
        try:
            self.retheme()
        finally:
            self._retheming = False

    def retheme(self) -> None:
        from views.icons import tool_icon
        self._header_icons()
        self.add_layer_btn.setIcon(add_icon(KIND_LAYER))
        self.add_folder_btn.setIcon(add_icon(KIND_FOLDER))
        self.color_by_layer.setIcon(tool_icon("layers_colour"))
        self.more_btn.setIcon(tool_icon("layers_templates"))
        self._show_filter_state()
        self._update_expand_button()
        self.refresh()

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
        # This rebuild covers whatever the deferred one was waiting for.
        timer = getattr(self, "_refresh_timer", None)
        if timer is not None and timer.isActive():
            timer.stop()
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
        self._tell_order()

    def display_outline(self) -> list:
        """``(kind, name, depth)`` of every row — ``kind`` ``"folder"`` or
        ``"layer"`` — in the order the tab lists them now, a folder before
        what it holds, folded or filtered out alike."""
        out = []

        def walk(item, depth) -> None:
            kind, name = self._key(item)
            out.append((kind, name, depth))
            for c in self._children(item):
                walk(c, depth + 1)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), 0)
        return out

    def _tell_order(self) -> None:
        """Announce a new order of the rows — once, not on every rebuild."""
        outline = tuple(self.display_outline())
        if outline != self._told_outline:
            self._told_outline = outline
            self.orderChanged.emit()

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
                    COL_COLOR, COL_LINETYPE, COL_HATCH, COL_WEIGHT,
                    COL_CUT, COL_OPACITY, COL_PRINT, COL_COUNT)
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
        self._tell_order()

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
        # Strong enough to find at a glance — next to a row picked in the
        # list, a faint tint went unseen — yet lighter than that pick.
        tint = QColor(QApplication.palette().highlight().color())
        tint.setAlpha(105)
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
        first = None
        for it in self._all_items():
            on = id(it) in marked
            it.setData(COL_NAME, ROLE_HOLDS, on)
            for col in range(self.tree.columnCount()):
                it.setBackground(col, QBrush(tint) if on else QBrush())
            font = it.font(COL_NAME)
            if font.bold() != on:
                font.setBold(on)
                it.setFont(COL_NAME, font)
            if on and first is None:
                first = it
        # In view: the layer of what was just picked in the model.
        if first is not None and names != getattr(self, "_marked_names",
                                                  None):
            self.tree.scrollToItem(first)
        self._marked_names = names
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
        own = ly.linetype.startswith(L.CUSTOM_LINETYPE)
        label = (ly.linetype[len(L.CUSTOM_LINETYPE):] if own
                 else tr(dict(self.LINETYPE_LABELS).get(ly.linetype,
                                                        "Continuous")))
        item.setData(COL_LINETYPE, ROLE_LINETYPE, ly.linetype)
        item.setData(COL_LINETYPE, ROLE_LINEPATTERN,
                     list(L.linetype_pattern(ly.linetype, self._scene()))
                     if own else None)
        item.setData(COL_LINETYPE, Qt.UserRole + 1,
                     keys.index(ly.linetype) if ly.linetype in keys
                     else len(keys))
        item.setToolTip(COL_LINETYPE, label)
        weight = ly.lineweight
        item.setText(COL_WEIGHT, "—" if weight is None else f"{weight:.2f}")
        item.setTextAlignment(COL_WEIGHT, Qt.AlignCenter)
        item.setData(COL_WEIGHT, Qt.UserRole + 1,
                     -1.0 if weight is None else float(weight))
        item.setToolTip(COL_WEIGHT, tr("Default (from the sheet)") if weight is None
                        else f"{weight:.2f} mm")
        cut = getattr(ly, "cut_weight", None)
        item.setText(COL_CUT, "—" if cut is None else f"{cut:.2f}")
        item.setTextAlignment(COL_CUT, Qt.AlignCenter)
        item.setData(COL_CUT, Qt.UserRole + 1,
                     -1.0 if cut is None else float(cut))
        item.setToolTip(COL_CUT, tr("The sheet's cut pen") if cut is None
                        else f"{tr('Cut pen')} {cut:.2f} mm")
        hatch = getattr(ly, "hatch", None)
        from core.hatches import HATCH_LABELS, HATCH_ORDER
        scene = self._scene()
        item.setIcon(COL_HATCH, hatch_icon(
            hatch, L.hatch_ground_rgb(ly), L.hatch_ink_rgb(ly),
            getattr(ly, "hatch_angle", 0.0), L.layer_hatch_families(scene, ly)))
        item.setData(COL_HATCH, Qt.UserRole + 1,
                     -1 if hatch is None else HATCH_ORDER.index(hatch)
                     if hatch in HATCH_ORDER else len(HATCH_ORDER))
        item.setToolTip(COL_HATCH, tr("The frame's fill") if hatch is None
                        else tr(HATCH_LABELS[hatch]) if hatch in HATCH_LABELS
                        else L.hatch_label(scene, hatch))
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
        # Announce first: the listeners' rebuild is deferred, and the one
        # below covers it (``refresh`` drops a pending one) — the row whose
        # name is about to be typed must not be rebuilt under the editor.
        self._window.viewport.notify_scene_changed()
        if rebuild:
            self.refresh()

    def _released(self, released: bool) -> None:
        if released:
            self._window.statusBar().showMessage(tr(
                "The active layer is hidden or locked: new objects go to "
                "'{default}' again.", default=L.DEFAULT_LAYER), 4000)

    def _on_item_clicked(self, item, column) -> None:
        """A click on one of the cells, for code and tests: the tree itself
        acts on the press (:class:`views.side_tree.SideTree`). The action
        runs once Qt is done: it rebuilds the tree."""
        self.cell_clicked(item, column)

    def cell_clicked(self, item, column) -> None:
        """A press on one of the tree's cells — the eye, the padlock or the
        target: the panel answers it, and the selection is left as it was,
        so it acts on every selected row. The row and its targets are read
        now: the action rebuilds the tree, and the item would be gone."""
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
            self._select_edited(name, targets)
            self.pick_color(targets)
        elif (column in (COL_LINETYPE, COL_WEIGHT, COL_OPACITY, COL_CUT,
                         COL_HATCH)
              and kind == KIND_LAYER):
            self._select_edited(name, targets)
            self._cell_menu(name, column, targets)

    def _select_edited(self, name: str, targets) -> None:
        """Select the row whose colour, line or hatch is being edited, so
        the list shows which layer the picker works on: the clicked row
        alone, unless it is one of several selected — then they all stay
        selected, as they all take the pick."""
        item = self.item_for(name)
        if item is None or item.isSelected():
            return
        self.tree.clearSelection()
        self.tree.setCurrentItem(item)
        item.setSelected(True)

    def _cell_menu(self, name: str, column: int, targets) -> None:
        """The line type, line weight, cut weight or transparency list,
        dropped under the clicked cell; the pick goes to every target row."""
        item = self.item_for(name)
        ly = self._scene().layer(name)
        if item is None or ly is None:
            return
        if column == COL_HATCH:
            self.open_hatch_picker(targets, ly)
            return
        menu = QMenu(self)
        if column == COL_LINETYPE:
            # A panel of its own, as the hatch picker: centred, the same
            # place every time.
            self._fill_linetypes(menu, targets, ly, picker=True)
            self._popup_centred(menu)
            return
        elif column == COL_WEIGHT:
            self._fill_weights(menu, targets, ly)
        elif column == COL_CUT:
            self._fill_weights(menu, targets, ly, cut=True)
        else:
            self._fill_opacities(menu, targets, ly)
        from PySide6.QtCore import QRect
        row = self.tree.visualItemRect(item)
        cell = QRect(self.tree.columnViewportPosition(column), row.top(),
                     self.tree.columnWidth(column), row.height())
        self._drop(menu, global_rect(self.tree.viewport(), cell))

    #: The largest pattern file read, in bytes.
    PAT_MAX_BYTES = 4 * 1024 * 1024

    def import_pat_file(self, path) -> int:
        """Bring the patterns of the pattern file ``path`` into the document
        (``Scene.hatch_patterns``; one of the same name is replaced).
        Returns how many came in — 0 when the file holds none it can read."""
        from pathlib import Path
        from core.hatches import parse_pat
        try:
            data = Path(path).read_bytes()[:self.PAT_MAX_BYTES]
        except OSError:
            return 0
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        found = parse_pat(text)
        if not found:
            return 0
        scene = self._scene()
        patterns = dict(getattr(scene, "hatch_patterns", None) or {})
        patterns.update(found)
        scene.hatch_patterns = patterns
        self._touch()
        return len(found)

    def export_pat_file(self, path) -> int:
        """Write every pattern drawn only with lines — the built-in ones
        (as ``IT-<alias>``) and the document's imported ones — to the
        pattern file ``path``. Returns how many went in."""
        from pathlib import Path
        from core.hatches import (HATCH_INFO, HATCH_LABELS, HATCH_ORDER,
                                  line_families, to_pat)
        entries = []
        for key in HATCH_ORDER:
            families = line_families(key)
            if families:
                entries.append(("IT-" + HATCH_INFO[key][0],
                                HATCH_LABELS[key], families))
        for name, raw in sorted((getattr(self._scene(), "hatch_patterns",
                                         None) or {}).items()):
            entries.append((name, raw.get("label", name),
                            raw.get("families", [])))
        Path(path).write_text(to_pat(entries), encoding="utf-8")
        return sum(1 for e in entries if e[2])

    def _export_hatches(self) -> None:
        """«Export .pat…»: pick where, write the file, say how many."""
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getSaveFileName(
            self, tr("Export .pat…"), "ingetrazo.pat",
            tr("Pattern files (*.pat)"))
        if not path:
            return
        try:
            n = self.export_pat_file(path)
        except OSError as exc:
            QMessageBox.warning(self, tr("Export .pat…"), str(exc))
            return
        self._window.statusBar().showMessage(tr(
            "{n} hatch patterns written to {name}", n=n,
            name=Path(path).name), 5000)

    # ---- The document's own line types -------------------------------------
    def add_line_type(self, name: str, pattern, names=(), text: str = "",
                      text_size: float = 2.5, replaces: str = "",
                      color=None) -> str | None:
        """Keep line type ``name`` (``pattern`` in paper mm, and ``text``
        written along it, ``text_size`` mm high, in a gap of its own) in the
        document — one of the same name is replaced; ``replaces``: the one
        being edited, renamed, its layers following — and give it to the
        layers ``names``. Returns its key, or ``None`` for a pattern that
        cannot be drawn."""
        pattern = L.clean_pattern(pattern)
        name = (name or "").strip()[:64]
        if pattern is None or not name:
            return None
        scene = self._scene()
        own = dict(getattr(scene, "line_types", None) or {})
        drawn, spec = L.with_text(pattern, text, text_size)
        drawn = L.clean_pattern(drawn)
        if drawn is None:
            return None
        if replaces and replaces != name:
            own.pop(replaces, None)
            for ly in scene.layers:
                if ly.linetype == L.CUSTOM_LINETYPE + replaces:
                    ly.linetype = L.CUSTOM_LINETYPE + name
        # ``pieces``: as they were typed, for the editor to show again.
        own[name] = dict({"label": name, "pattern": drawn,
                          "pieces": pattern}, **(spec or {}))
        colour = L.clean_line_colour(color)
        if colour is not None:
            own[name]["color"] = colour
        scene.line_types = own
        key = L.CUSTOM_LINETYPE + name
        if names:
            self.set_style(names, linetype=key)
        else:
            self._touch()
        return key

    def new_line_type(self, names) -> None:
        """«New line type…»: the editor; on OK, the new type for ``names``."""
        dlg = LineTypeDialog(self)
        if dlg.exec() and dlg.result_pattern() is not None:
            words, size = dlg.result_text()
            self.add_line_type(dlg.name(), dlg.result_pattern(), names,
                               words, size, color=dlg.result_color())

    def edit_line_type(self, name: str) -> None:
        """«Edit…» on one of the document's line types: the editor with it
        filled in; on OK, it changes (and its layers with it)."""
        entry = (getattr(self._scene(), "line_types", None) or {}).get(name)
        if not isinstance(entry, dict):
            return
        dlg = LineTypeDialog(self, name=name,
                             pattern=entry.get("pieces") or entry["pattern"],
                             text=entry.get("text", ""),
                             text_size=entry.get("text_size", 2.5),
                             editing=True, color=entry.get("color"))
        if dlg.exec() and dlg.deleted:
            self.delete_line_type(name)
            return
        if dlg.result() and dlg.result_pattern() is not None:
            words, size = dlg.result_text()
            self.add_line_type(dlg.name(), dlg.result_pattern(), (), words,
                               size, replaces=name,
                               color=dlg.result_color())

    def set_linetype_colour(self, key, rgb) -> None:
        """Line type ``key`` in colour ``rgb`` (``None``: by layer) — on the
        sheets, in the DXF and, with the style's option, in the model."""
        if L.set_linetype_color(self._scene(), key, rgb):
            self._touch(rebuild=False)
            vp = getattr(self._window, "viewport", None)
            if vp is not None:
                vp.update()

    def ask_linetype_colour(self, key) -> None:
        """A right-click's «Colour…» on a line type, built-in or own: the
        line type editor's colours, the current one ticked."""
        from views.hatch_paint import any_colour_chip, colour_chip
        scene = self._scene()
        mine = L.linetype_color(key, scene)
        menu = QMenu(self)
        fixed = [v for v, _t in LineTypeDialog.COLOURS
                 if isinstance(v, tuple)]
        dpr = self.devicePixelRatioF()
        for value, label in LineTypeDialog.COLOURS:
            if value is None:
                icon = colour_chip(*LineTypeDialog.CHIP,
                                   QColor.fromRgbF(0.55, 0.35, 0.25),
                                   dpr=dpr, strokes=True)
                on = mine is None
            elif value == "other":
                on = mine is not None and mine not in fixed
                icon = any_colour_chip(*LineTypeDialog.CHIP,
                                       QColor.fromRgbF(*mine) if on
                                       else None, dpr=dpr)
            else:
                icon = colour_chip(*LineTypeDialog.CHIP,
                                   QColor.fromRgbF(*value), dpr=dpr,
                                   strokes=True)
                on = mine == value
            act = menu.addAction(QIcon(icon), tr(label))
            act.setCheckable(True)
            act.setChecked(on)
            act.triggered.connect(
                lambda _c=False, v=value: self._linetype_colour_chosen(
                    key, v))
        from PySide6.QtGui import QCursor
        self._popup(menu, QCursor.pos())

    def _line_colour_row(self, menu, key) -> None:
        """«Colour of the line: ▬ Yellow ▸» under the list, for the line
        type ``key`` (the layer's own): one row, so the list keeps its
        width, the colours in a submenu with their names. A colour is set
        once a project, a line type picked all day long."""
        from views.hatch_paint import any_colour_chip, colour_chip
        scene = self._scene()
        mine = L.linetype_color(key, scene)
        fixed = [v for v, _t in LineTypeDialog.COLOURS
                 if isinstance(v, tuple)]
        dpr = self.devicePixelRatioF()

        def chip(value, on_other=None):
            if value is None:
                return QIcon(colour_chip(
                    *LineTypeDialog.CHIP, QColor.fromRgbF(0.55, 0.35, 0.25),
                    dpr=dpr, strokes=True))
            if value == "other":
                return QIcon(any_colour_chip(
                    *LineTypeDialog.CHIP,
                    QColor.fromRgbF(*on_other) if on_other else None,
                    dpr=dpr))
            return QIcon(colour_chip(*LineTypeDialog.CHIP,
                                     QColor.fromRgbF(*value), dpr=dpr,
                                     strokes=True))
        current = next((t for v, t in LineTypeDialog.COLOURS if v == mine),
                       "Other colour…" if mine is not None else "By layer")
        sub = QMenu(tr("Colour of the line: {colour}",
                       colour=tr(current).rstrip("…")), menu)
        sub.setIcon(chip(mine if mine in fixed or mine is None else "other",
                         mine))
        for value, label in LineTypeDialog.COLOURS:
            other_on = (value == "other" and mine is not None
                        and mine not in fixed)
            act = sub.addAction(chip(value, mine if other_on else None),
                                tr(label))
            act.setCheckable(True)
            act.setChecked(other_on or (value != "other" and mine == value))
            act.triggered.connect(lambda _c=False, v=value: QTimer.singleShot(
                0, lambda: self._linetype_colour_chosen(key, v)))
        # menuAction(), not QAction.menu(): see the panel's other submenus.
        menu.addAction(sub.menuAction())
        self.line_colour_menu = sub

    def _linetype_colour_chosen(self, key, value) -> None:
        if value == "other":
            from views.color_dialog import get_color
            mine = L.linetype_color(key, self._scene())
            picked = get_color(QColor.fromRgbF(*mine) if mine
                               else QColor(220, 120, 0), self,
                               tr("Other colour…"))
            if not picked.isValid():
                return
            value = tuple(round(c, 4) for c in picked.getRgbF()[:3])
        self.set_linetype_colour(key, value)

    def delete_line_type(self, name: str) -> None:
        """«Delete»: the line type goes; the layers that used it are inked
        continuous again."""
        scene = self._scene()
        own = dict(getattr(scene, "line_types", None) or {})
        if own.pop(name, None) is None:
            return
        scene.line_types = own
        for ly in scene.layers:
            if ly.linetype == L.CUSTOM_LINETYPE + name:
                ly.linetype = "continuous"
        self._dirty_paint()
        self._touch()

    def import_lin_file(self, path) -> tuple[int, list]:
        """Bring the simple line types of the line type file ``path`` into
        the document. Returns ``(how many, names left out)`` — those with
        text or shapes inside."""
        from pathlib import Path
        try:
            data = Path(path).read_bytes()[:self.PAT_MAX_BYTES]
        except OSError:
            return 0, []
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        found, skipped = L.parse_lin(text)
        n = L.load_line_types(self._scene(), found)
        if n:
            self._touch()
        return n, skipped

    def export_lin_file(self, path) -> int:
        """Write the document's own line types to the line type file
        ``path``. Returns how many."""
        from pathlib import Path
        own = getattr(self._scene(), "line_types", None) or {}
        entries = [(n, e.get("label", n), e["pattern"],
                    L.clean_line_text(e, e["pattern"]))
                   for n, e in sorted(own.items())]
        Path(path).write_text(L.to_lin(entries), encoding="utf-8")
        return len(entries)

    def _import_line_types(self) -> None:
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getOpenFileName(
            self, tr("Import .lin…"), "",
            tr("Line type files (*.lin)") + ";;" + tr("All files (*)"))
        if not path:
            return
        n, skipped = self.import_lin_file(path)
        msg = tr("{n} line types imported from {name}", n=n,
                 name=Path(path).name)
        if skipped:
            msg += "\n\n" + tr(
                "Left out, with text or shapes inside: {names}",
                names=", ".join(skipped[:12])
                + ("…" if len(skipped) > 12 else ""))
        if n or skipped:
            QMessageBox.information(self, tr("Import .lin…"), msg)
        else:
            QMessageBox.information(self, tr("Import .lin…"), tr(
                "No line type could be read from {name}.",
                name=Path(path).name))

    def _export_line_types(self) -> None:
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getSaveFileName(
            self, tr("Export .lin…"), "ingetrazo.lin",
            tr("Line type files (*.lin)"))
        if not path:
            return
        try:
            n = self.export_lin_file(path)
        except OSError as exc:
            QMessageBox.warning(self, tr("Export .lin…"), str(exc))
            return
        self._window.statusBar().showMessage(tr(
            "{n} line types written to {name}", n=n, name=Path(path).name),
            5000)

    def _import_hatches(self, names, ly) -> None:
        """«Import .pat…»: pick a pattern file, bring its patterns in and
        open the picker again on them."""
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        path, _f = QFileDialog.getOpenFileName(
            self, tr("Import .pat…"), "",
            tr("Pattern files (*.pat)") + ";;" + tr("All files (*)"))
        if path:
            n = self.import_pat_file(path)
            bar = self._window.statusBar()
            if n:
                bar.showMessage(tr("{n} hatch patterns imported from {name}",
                                   n=n, name=Path(path).name), 5000)
            else:
                QMessageBox.information(self, tr("Import .pat…"), tr(
                    "No hatch pattern could be read from {name}.",
                    name=Path(path).name))
        self.open_hatch_picker(names, ly)

    def open_hatch_picker(self, names, ly) -> None:
        """The hatch picker for the layers ``names``, centred on the screen
        the panel is on — it is a whole editor, not a list dropped from a
        cell, and it stays open while pattern, ground and ink are chosen."""
        from PySide6.QtCore import QPoint
        menu = QMenu(self)
        self._fill_hatches(menu, names, ly)
        self._popup_centred(menu)

    def _popup_centred(self, menu) -> None:
        """Show a picker (hatches, line types) in the middle of the screen
        the panel is on — always the same place, a panel of its own rather
        than a list dropped from a cell."""
        from PySide6.QtCore import QPoint
        # Laid out before it shows, so its first frame is the whole picker.
        menu.ensurePolished()
        menu.adjustSize()
        size = menu.sizeHint()
        screen = (self.screen() or QApplication.primaryScreen())
        area = screen.availableGeometry()
        # Shown at once: a menu fading or sliding in (the system's menu
        # effect) leaves its shadow on screen first, alone, for a moment —
        # a flash before so large a panel. The effects come back as soon as
        # it is up, for every other menu.
        effects = (Qt.UI_AnimateMenu, Qt.UI_FadeMenu)
        was = [(e, QApplication.isEffectEnabled(e)) for e in effects]
        for e in effects:
            QApplication.setEffectEnabled(e, False)
        QTimer.singleShot(0, lambda: [QApplication.setEffectEnabled(e, on)
                                      for e, on in was])
        self._popup(menu, QPoint(area.center().x() - size.width() // 2,
                                 area.center().y() - size.height() // 2))

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
                        (COL_HATCH, "Cut hatch"),
                        (COL_CUT, "Cut weight"),
                        (COL_OPACITY, "Transparency"),
                        (COL_PRINT, "Print"),
                        (COL_COUNT, "Entities on the layer"))
    #: QSettings key of the columns switched off.
    HIDDEN_COLUMNS_KEY = "layers/hidden_columns"
    #: QSettings key of the optional columns that choice was made among: a
    #: column added since starts as :data:`DEFAULT_HIDDEN` says, not shown
    #: because the saved list never named it.
    KNOWN_COLUMNS_KEY = "layers/known_columns"
    #: The optional columns before the key above existed.
    FIRST_COLUMNS = (COL_ACTIVE, COL_ISOLATE, COL_COLOR, COL_LINETYPE,
                     COL_WEIGHT, COL_OPACITY, COL_PRINT, COL_COUNT)

    #: Off until asked for — what is set now and then, not looked at every
    #: day: the line weight (set once per layer, and only seen on sheets),
    #: the print mark (a few reference layers, once per project),
    #: transparency (a viewing aid), the count (it adds faces, edges and
    #: objects up, a number that mostly says «empty or not» — which the
    #: filter and Purge say already) and the cut weight (set once per layer,
    #: and only seen on a cut sheet). The name keeps room to be read.
    DEFAULT_HIDDEN = (COL_WEIGHT, COL_PRINT, COL_OPACITY, COL_COUNT, COL_CUT)

    @staticmethod
    def _columns_value(raw) -> set[int]:
        if isinstance(raw, (list, tuple)):
            raw = ",".join(str(v) for v in raw)
        return {int(v) for v in str(raw or "").split(",")
                if v.strip().isdigit()}

    def hidden_columns(self) -> set[int]:
        from PySide6.QtCore import QSettings
        settings = QSettings()
        if not settings.contains(self.HIDDEN_COLUMNS_KEY):
            return set(self.DEFAULT_HIDDEN)
        optional = {c for c, _l in self.OPTIONAL_COLUMNS}
        hidden = self._columns_value(
            settings.value(self.HIDDEN_COLUMNS_KEY, "")) & optional
        known = (self._columns_value(settings.value(self.KNOWN_COLUMNS_KEY))
                 if settings.contains(self.KNOWN_COLUMNS_KEY)
                 else set(self.FIRST_COLUMNS))
        return hidden | ((optional - known) & set(self.DEFAULT_HIDDEN))

    def set_column_shown(self, col: int, on: bool) -> None:
        from PySide6.QtCore import QSettings
        hidden = self.hidden_columns()
        if on:
            hidden.discard(col)
        else:
            hidden.add(col)
        QSettings().setValue(self.HIDDEN_COLUMNS_KEY,
                             ",".join(str(c) for c in sorted(hidden)))
        QSettings().setValue(self.KNOWN_COLUMNS_KEY, ",".join(
            str(c) for c, _l in self.OPTIONAL_COLUMNS))
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
        menu = StayOpenMenu(self)
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

    def set_model_linetypes(self, on: bool) -> None:
        """Draw the layers' line types — dashes and colours — on the model's
        edges, or not — a setting of the STYLE, like «Colour by layer»."""
        style = getattr(self._scene(), "display_style", None)
        if style is None or bool(style.model_linetypes) == bool(on):
            return
        style.model_linetypes = bool(on)
        self._touch(rebuild=False)
        vp = getattr(self._window, "viewport", None)
        if vp is not None:
            vp.update()

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

    def delete_row(self) -> None:
        """Delete the current row: what the list's Delete key does (see
        :meth:`_on_delete`)."""
        self._on_delete()

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
        style = getattr(self._scene(), "display_style", None)
        act = menu.addAction(tr("Line types in the model"))
        act.setCheckable(True)
        act.setChecked(bool(getattr(style, "model_linetypes", True)))
        act.setStatusTip(tr(
            "The layers' line types on their edges in the 3D view too: "
            "dashed as a sheet at 1:50 draws them, in the line type's own "
            "colour (a gas line yellow); scenes remember it with the style."))
        act.toggled.connect(self.set_model_linetypes)
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
        """Line type, line weight, cut weight, cut hatch or opacity of the
        layers ``names``."""
        scene = self._scene()
        for name in names:
            ly = scene.layer(name)
            if ly is None:
                continue
            if "linetype" in look:
                ly.linetype = look["linetype"]
            if "lineweight" in look:
                ly.lineweight = look["lineweight"]
            if "cut_weight" in look:
                ly.cut_weight = look["cut_weight"]
            if "hatch" in look:
                from core.hatches import piece_kind
                if piece_kind(look["hatch"]) != piece_kind(ly.hatch):
                    ly.brick = None    # a brick's size is no block's
                ly.hatch = look["hatch"]
            if "hatch_ground" in look:
                ly.hatch_ground = L._ground(look["hatch_ground"])
            if "hatch_color" in look:
                ly.hatch_color = L._ground(look["hatch_color"])
            if "hatch_angle" in look:
                ly.hatch_angle = float(look["hatch_angle"]) % 360.0
            if "hatch_scale" in look:
                ly.hatch_scale = min(20.0, max(0.05,
                                               float(look["hatch_scale"])))
            if "hatch_offset" in look:
                ly.hatch_offset = L.clean_offset(look["hatch_offset"])
            if "hatch_on_paper" in look:
                ly.hatch_on_paper = bool(look["hatch_on_paper"])
            if "hatch_cross" in look:
                ly.hatch_cross = bool(look["hatch_cross"])
            if "joints" in look:
                from core.hatches import JOINTS
                ly.joints = (look["joints"] if look["joints"] in JOINTS
                             else None)
            if "mortar" in look:
                ly.mortar = bool(look["mortar"])
            if "brick" in look:
                from core.hatches import clean_brick
                ly.brick = (clean_brick(look["brick"])
                            if look["brick"] is not None else None)
            if "opacity" in look:
                ly.opacity = min(1.0, max(0.1, float(look["opacity"])))
        self._dirty_paint()
        self._touch()

    def set_document_brick(self, kind_size) -> None:
        """The document's piece of a kind — ``(kind, size)``, ``None`` for
        the usual one: every layer of that kind is drawn with it, their own
        sizes giving way, chosen once for the whole document."""
        from core.hatches import clean_brick, piece_kind
        kind, size = kind_size
        scene = self._scene()
        bricks = dict(getattr(scene, "bricks", None) or {})
        size = clean_brick(size) if size is not None else None
        if size is None:
            bricks.pop(kind, None)
        else:
            bricks[kind] = size
        scene.bricks = bricks
        for ly in scene.layers:
            if piece_kind(ly.hatch) == kind:
                ly.brick = None
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
        """Line type, line weight, cut weight and opacity of the layers
        ``names``, the current one ticked; and their visibility in every
        saved scene."""
        self._fill_linetypes(_submenu(menu, tr("Line type")), names, ly)
        self._fill_weights(_submenu(menu, tr("Line weight")), names, ly)
        self._fill_weights(_submenu(menu, tr("Cut weight")), names, ly,
                           cut=True)
        # A whole editor, centred on the screen once this menu has closed.
        menu.addAction(tr("Cut hatch") + "…", lambda: QTimer.singleShot(
            0, lambda: self.open_hatch_picker(names, ly)))
        self._fill_opacities(_submenu(menu, tr("Transparency")), names, ly)
        if getattr(self._scene(), "saved_views", None):
            menu.addAction(tr("Hide in every scene"),
                           lambda: self.hide_in_scenes(names, True))
            menu.addAction(tr("Show in every scene"),
                           lambda: self.hide_in_scenes(names, False))

    def _fill_linetypes(self, menu, names, ly, picker: bool = False) -> None:
        """The line types as the lines they draw, the current one ticked
        (the name is the entry's tooltip and its text for the keyboard):
        the built-in ones, then the document's own under «Custom», then
        making one, importing and exporting line type files.

        ``picker`` (the Line type cell): the line type panel, laid out as
        the hatch picker — it stays open on a pick, the colour of the line
        in sight under the list, the tools and «Done» at its foot; only
        «Done» keeps the changes, Esc or a click outside put them back."""
        from PySide6.QtWidgets import QLabel, QWidgetAction

        def head(title):
            # A group title as the hatch picker has them: in the panel, its
            # sections' — small capitals over a rule.
            act = QWidgetAction(menu)
            act.setText(title)
            label = QLabel(title.upper() if picker else title, menu)
            label.setStyleSheet(
                "font-size: 7.5pt; font-weight: bold; letter-spacing: 1px;"
                " padding: 8px 0 2px 0; margin: 0 12px;"
                " border-bottom: 1px solid palette(mid);" if picker else
                "font-size: 8pt; font-weight: bold; padding: 6px 10px 2px;")
            act.setDefaultWidget(label)
            act.setEnabled(False)
            menu.addAction(act)
        if picker:
            # Which layer the panel works on, on top — as the hatch
            # picker's card names its pattern.
            act = QWidgetAction(menu)
            shown = ", ".join(names[:3]) + ("…" if len(names) > 3 else "")
            act.setText(tr("Line type") + " · " + shown)
            label = QLabel("<b>" + tr("Line type") + "</b> · " + shown, menu)
            label.setStyleSheet("padding: 10px 12px 2px;")
            act.setDefaultWidget(label)
            act.setEnabled(False)
            menu.addAction(act)
        # The line type panel: only «Done» — or a pick made with Enter, as
        # in any menu — keeps what was chosen (the menu hides itself after
        # a triggered action: «kept» must be set before that, by a slot
        # connected before the menu's own).
        kept = [not picker]

        def keep_on_trigger(a) -> None:
            if picker:
                a.triggered.connect(lambda _c=False: kept.__setitem__(
                    0, True))
        head(tr("Standard line types"))
        for key, label in self.LINETYPE_LABELS:
            a = QWidgetAction(menu)
            a.setText(tr(label))
            a.setCheckable(True)
            on = ly is not None and ly.linetype == key
            a.setChecked(on)
            a.triggered.connect(lambda _c=False, k=key:
                                self.set_style(names, linetype=k))
            keep_on_trigger(a)
            # The line alone, its name on hover — as the hatch tiles — in
            # the colour the document gave it; a right-click changes that.
            a.setDefaultWidget(_LineSample(
                key, a, menu, on, keep_open=picker,
                pick=lambda k=key: self._line_picked(menu, names, k),
                colour=L.linetype_color(key, self._scene()),
                actions=((tr("Colour…"),
                          lambda k=key: self.ask_linetype_colour(k)),)))
            menu.addAction(a)
        scene = self._scene()

        def closing(f):
            # A tool that opens a dialog closes the panel, keeping its picks.
            def run():
                kept[0] = True
                menu.close()
                QTimer.singleShot(0, f)
            return run
        own = getattr(scene, "line_types", None) or {}
        if own:
            menu.addSeparator()
            head(tr("Custom line types"))
            for name in sorted(own, key=str.lower):
                key = L.CUSTOM_LINETYPE + name
                a = QWidgetAction(menu)
                a.setText(name)
                a.setCheckable(True)
                on = ly is not None and ly.linetype == key
                a.setChecked(on)
                a.triggered.connect(lambda _c=False, k=key:
                                    self.set_style(names, linetype=k))
                keep_on_trigger(a)
                a.setDefaultWidget(_LineSample(
                    key, a, menu, on, text=name, keep_open=picker,
                    pick=lambda k=key: self._line_picked(menu, names, k),
                    edit=(closing(lambda n=name: self.edit_line_type(n))
                          if picker else None),
                    pattern=L.linetype_pattern(key, scene),
                    words=L.linetype_text(key, scene),
                    colour=L.linetype_color(key, scene),
                    actions=((tr("Edit…"),
                              lambda n=name: self.edit_line_type(n)),
                             (tr("Colour…"),
                              lambda k=key: self.ask_linetype_colour(k)),
                             (tr("Delete"),
                              lambda n=name: self.delete_line_type(n)))))
                a.setToolTip(tr("Right-click to edit, colour or delete it"))
                menu.addAction(a)
        if picker:
            self._line_panel_parts(menu, names, own, kept, closing)
            return
        if ly is not None:
            # The colour of the line type ticked, under the list.
            menu.addSeparator()
            self._line_colour_row(menu, ly.linetype)
        menu.addSeparator()
        later = (lambda f: lambda: QTimer.singleShot(0, f))
        menu.addAction(tr("New line type…"),
                       later(lambda: self.new_line_type(names)))
        menu.addAction(tr("Import .lin…"),
                       later(lambda: self._import_line_types()))
        out = menu.addAction(tr("Export .lin…"),
                             later(lambda: self._export_line_types()))
        out.setEnabled(bool(own))

    def _line_picked(self, menu, names, key) -> None:
        """A click on a line in the line type panel: the layers take it, its
        tick moves there and the colour row shows its colour — the panel
        stays open."""
        self.set_style(names, linetype=key)
        for sample in menu.findChildren(_LineSample):
            sample.set_checked(sample.key == key)
        row = getattr(self, "line_colour_row", None)
        if row is not None:
            row.refresh()

    def _line_panel_parts(self, menu, names, own, kept, closing) -> None:
        """The line type panel's colour of the line and its foot — «New»,
        import and export .lin, «Done» — and what «Done» keeps: a pick
        ticks its line at once and shows its colour; closing any other way
        puts the layers' line types and the colours back."""
        from PySide6.QtCore import QSize
        from PySide6.QtWidgets import QWidgetAction
        from views.icons import tool_icon
        scene = self._scene()
        before = {n: scene.layer(n).linetype for n in names
                  if scene.layer(n) is not None}
        colours_before = (dict(getattr(scene, "linetype_colors", None) or {}),
                          {n: (e.get("color") if isinstance(e, dict)
                               else None)
                           for n, e in (getattr(scene, "line_types", None)
                                        or {}).items()})
        menu.addSeparator()
        colour = _LineColourRow(self, names, menu)
        a = QWidgetAction(menu)
        a.setText(tr("Colour of the line"))
        a.setDefaultWidget(colour)
        menu.addAction(a)
        self.line_colour_row = colour

        menu.addSeparator()
        foot = QWidget(menu)
        line = QHBoxLayout(foot)
        line.setContentsMargins(10, 2, 10, 6)
        line.setSpacing(4)
        css = ("QToolButton { border: 1px solid palette(mid);"
               " border-radius: 4px; padding: 2px 6px; }"
               " QToolButton:hover { background: palette(midlight); }")
        self.line_tool_buttons = []
        for text, tip, icon, run, enabled in (
                ("+ " + tr("New"), tr("New line type…"), None,
                 closing(lambda: self.new_line_type(names)), True),
                ("", tr("Import .lin…"), "file_import",
                 closing(self._import_line_types), True),
                ("", tr("Export .lin…"), "file_export",
                 closing(self._export_line_types), bool(own))):
            b = QToolButton(foot)
            b.setStyleSheet(css)
            b.setToolTip(tip)
            if icon:
                b.setIcon(tool_icon(icon))
                b.setIconSize(QSize(16, 16))
            else:
                b.setText(text)
            b.setEnabled(enabled)
            b.clicked.connect(run)
            line.addWidget(b)
            self.line_tool_buttons.append(b)
        line.addStretch(1)
        # «Cancel» puts the layers back and closes; «Done» keeps — as the
        # hatch picker's foot.
        back = self.line_cancel_button = QPushButton(tr("Cancel"), foot)
        back.clicked.connect(menu.close)
        line.addWidget(back)
        done = self.line_done_button = QPushButton(tr("Done"), foot)
        done.setDefault(True)

        def keep() -> None:
            kept[0] = True
            menu.close()
        done.clicked.connect(keep)
        line.addWidget(done)
        a = QWidgetAction(menu)
        a.setText(tr("Done"))
        a.setDefaultWidget(foot)
        menu.addAction(a)

        def put_back() -> None:
            if kept[0]:
                return
            kept[0] = True
            changed = False
            for n, key in before.items():
                ly = scene.layer(n)
                if ly is not None and ly.linetype != key:
                    ly.linetype = key
                    changed = True
            if (getattr(scene, "linetype_colors", None) or {}) \
                    != colours_before[0]:
                scene.linetype_colors = dict(colours_before[0])
                changed = True
            for n, rgb in colours_before[1].items():
                if L.set_linetype_color(scene, L.CUSTOM_LINETYPE + n, rgb):
                    changed = True
            if changed:
                self._dirty_paint()
                self._touch()
                vp = getattr(self._window, "viewport", None)
                if vp is not None:
                    vp.update()
        menu.aboutToHide.connect(put_back)

    #: Screen pixels per millimetre of pen width in the weight list (the
    #: thinnest still a pixel, the thickest not a bar).
    WEIGHT_PX_PER_MM = 6.0

    def _fill_weights(self, menu, names, ly, cut: bool = False) -> None:
        """The weights as lines of that weight with the value beside them,
        like the line types; first the default (the sheet's pens). ``cut``:
        the layer's cut weight instead of its line weight."""
        from PySide6.QtWidgets import QWidgetAction
        key = "cut_weight" if cut else "lineweight"
        now = getattr(ly, key, None) if ly is not None else None
        rows = [(None, tr("The sheet's cut pen") if cut
                 else tr("Default (from the sheet)"))] + [
            (w, f"{w:.2f} mm") for w in self.LINEWEIGHTS]
        for w, text in rows:
            a = QWidgetAction(menu)
            a.setText(text)
            a.setCheckable(True)
            if w is None:
                on = ly is not None and now is None
            else:
                on = now is not None and abs(now - w) < 1e-6
            a.setChecked(on)
            a.triggered.connect(lambda _c=False, w=w:
                                self.set_style(names, **{key: w}))
            px = (max(1.0, min(6.0, w * self.WEIGHT_PX_PER_MM))
                  if w is not None else 2.0)
            a.setDefaultWidget(_LineSample(
                "continuous" if w is not None else None, a, menu, on,
                width=px, text=text))
            menu.addAction(a)

    def _fill_hatches(self, menu, names, ly) -> None:
        """The hatch picker (:class:`HatchGrid`) for the layers ``names``,
        the current pattern, ground and ink marked."""
        from PySide6.QtWidgets import QWidgetAction
        a = QWidgetAction(menu)
        a.setText(tr("Cut hatch"))
        grows = L.hatch_grows(ly) if ly is not None else False
        grid = HatchGrid(getattr(ly, "hatch", None) if ly is not None
                         else None, menu,
                         ground=getattr(ly, "hatch_ground", None), layer=ly,
                         ink=getattr(ly, "hatch_color", None),
                         patterns=getattr(self._scene(), "hatch_patterns",
                                          None),
                         form={"hatch_angle": getattr(ly, "hatch_angle", 0.0),
                               "hatch_scale": getattr(ly, "hatch_scale", 1.0),
                               "hatch_offset": getattr(ly, "hatch_offset",
                                                       None),
                               "hatch_on_paper": not grows,
                               "paper_fixed": getattr(
                                   ly, "hatch_on_paper", None) is not None,
                               "brick": getattr(ly, "brick", None),
                               "hatch_cross": getattr(ly, "hatch_cross",
                                                      False),
                               "joints": getattr(ly, "joints", None),
                               "mortar": getattr(ly, "mortar", False),
                               "doc_bricks": dict(getattr(
                                   self._scene(), "bricks", None) or {})})
        # Every pick applies at once and the picker stays open: pattern,
        # ground and ink in one go, seen at once in the model and on the
        # sheets. Only «Done» keeps them: «Cancel», Esc or a click outside
        # put the layers back as they were.
        kept = [False]

        def keep() -> None:
            kept[0] = True
        grid.picked.connect(lambda key: self.set_style(names, hatch=key))
        grid.ground_picked.connect(
            lambda value: self.set_style(names, hatch_ground=value))
        grid.ink_picked.connect(
            lambda value: self.set_style(names, hatch_color=value))
        grid.form_picked.connect(lambda form: self.set_style(names, **form))
        grid.brick_picked.connect(
            lambda size: self.set_style(names, brick=size))
        grid.brick_for_document.connect(self.set_document_brick)
        # A .pat file is chosen in a dialog of its own: the picker closes
        # for it, keeping what was picked.
        grid.import_requested.connect(
            lambda: (keep(), menu.close(), QTimer.singleShot(
                0, lambda: self._import_hatches(names, ly))))
        grid.export_requested.connect(
            lambda: (keep(), menu.close(),
                     QTimer.singleShot(0, self._export_hatches)))
        grid.done.connect(keep)
        grid.done.connect(menu.close)
        # What «Cancel» puts back: each layer's hatch as it is now.
        fields = ("hatch", "hatch_ground", "hatch_color", "hatch_angle",
                  "hatch_scale", "hatch_offset", "hatch_on_paper", "brick",
                  "hatch_cross",
                  "joints", "mortar")
        scene = self._scene()
        before = {n: {f: getattr(scene.layer(n), f, None) for f in fields}
                  for n in names if scene.layer(n) is not None}
        # «Use in the whole document» touches every layer: all of them,
        # and the document's brick, come back too.
        doc_before = (dict(getattr(scene, "bricks", None) or {}),
                      {ly.name: ly.brick for ly in scene.layers})

        def put_back() -> None:
            kept[0] = True             # once
            changed = False
            if (getattr(scene, "bricks", None) or {}) != doc_before[0]:
                scene.bricks = dict(doc_before[0])
                for ly in scene.layers:
                    if ly.name in doc_before[1]:
                        ly.brick = doc_before[1][ly.name]
                changed = True
            for n, old in before.items():
                ly = scene.layer(n)
                if ly is None:
                    continue
                for f, v in old.items():
                    if getattr(ly, f, None) != v:
                        setattr(ly, f, v)
                        changed = True
            if changed:
                self._dirty_paint()
                self._touch()

        def cancel() -> None:
            put_back()
            menu.close()
        grid.cancelled.connect(cancel)
        # Esc or a click outside: as «Cancel».
        menu.aboutToHide.connect(lambda: None if kept[0] else put_back())
        a.setDefaultWidget(grid)
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
        """The window's per-change call: rebuild once the event loop is
        back — never from inside a paint nor from a drop-down's own signal.

        ``sceneVersionChanged`` reaches here from ``_sync_edges``, that is,
        in the middle of ``paintGL``, and from the Layers toolbar's list
        while Qt is still closing it (handing a layer to the groups).
        Clearing and sorting the tree there was an access violation: the
        rows are rebuilt on the next turn instead, a burst of changes
        paying one rebuild. A window not shown yet (scripts, tests)
        refreshes at once, as before."""
        if self.tree.state() == QAbstractItemView.EditingState:
            return                          # never under an open name editor
        if self._window.isVisible() and not self.isVisible():
            self._stale = True
            return
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._refresh_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._refresh_after_change)
        timer.start(0)

    def _refresh_after_change(self) -> None:
        """What the next turn does: only the selection's mark and, after a
        change of the model, the counts — the filter too: «Selection» shows
        the layers of what is picked — when the rows are what they were;
        otherwise the tree is rebuilt."""
        if (self._signature() == getattr(self, "_drawn_signature", None)
                and self.tree.topLevelItemCount()):
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
