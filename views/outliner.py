# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Browser: the model's tree, and the composer's views and sheets.

**The Browser** (a sidebar tab of the model window) is the Outliner
(#219): every group and component at every depth, under the document's
name. An icon says what each row is (group, component, image, 3D text, a
BIM-tagged element, or what an extension says it is); the eye shows or
hides it, the padlock locks it; the filter keeps the rows whose name, type,
BIM class or layer match, with the containers on the way to them. A click
selects in the view — opening the groups around it, as double-clicking down
to it would — and a double-click (or Enter) opens it for editing. A
selection made in the view is found in the tree, its branch unfolded, and
the groups open for editing read in bold, so the tree always says where you
are. Below the groups, the section planes, each with its cut, frame and
fill.

**Views and sheets** (:class:`SheetsPanel`, docked in the sheet composer,
beside the page) lists the saved scenes and the sheets with their view
frames. A scene dragged onto the page lands as a view where it is dropped;
each scene says which sheets place it, a frame whose scene was deleted is
flagged instead of breaking, and the sheets are opened, ordered, copied,
deleted and printed from there.

The Outliner is built on the Project Structure plugin Carlos Martins
(@fafecm) shared in #87 — the tree mirrored with the view both ways, the
eye per node, entering a nested group through its path — and on the scope
Roy Méndez Castro (@roymendezcastro) wrote down in #219. Its drag and
drop and its padlock are here too: re-nesting keeps every group where it
stands in the world, whatever frame the new parent has, and the lock is
saved in the document.

The model stays the only source of truth: rows hold their group (or scene,
sheet, frame) and renames and hides are the usual undoable commands.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QPainter, QPalette, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                               QDockWidget,
                               QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QStyle,
                               QStyledItemDelegate,
                               QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget,
                               QFrame)

from core import outliner
from core.group import Group
from core.i18n import tr
from core.section import SectionPlane

# Model tab columns.
(COL_NAME, COL_EYE, COL_LOCK, COL_TYPE, COL_LAYER, COL_MATERIAL, COL_COPIES,
 COL_IFC) = range(8)
#: Columns the header's right-click shows or hides, and which start shown.
OPTIONAL_COLUMNS = ((COL_TYPE, "Type", True), (COL_LAYER, "Layer", True),
                    (COL_MATERIAL, "Material", False),
                    (COL_COPIES, "Copies", False),
                    (COL_IFC, "IFC class", False))


def _paint_icon(paint: dict, size: int = 16) -> QIcon:
    """A small swatch of a paint for a menu: the texture's image when it
    can be read, its colour otherwise."""
    raw_opacity = paint.get("opacity")
    opacity = (1.0 if raw_opacity is None else
               min(1.0, max(0.0, float(raw_opacity))))
    tex = paint.get("texture") or {}
    path = tex.get("path")
    if path:
        # Share the Materials panel's diagonal opacity preview and large-file
        # reader, so the same material looks the same in every menu.
        from views.tray import _texture_pixmap
        texture = _texture_pixmap(path, size, opacity)
        if texture is not None:
            return QIcon(texture)
    col = paint.get("color") or tex.get("tint") or (0.6, 0.6, 0.6)
    rgb = [max(0.0, min(1.0, float(c))) for c in list(col)[:3]]
    from views.tray import _color_pixmap
    return QIcon(_color_pixmap(rgb, size, opacity))


def open_to(viewport, path) -> bool:
    """Leave the view with exactly ``path`` open — stepping out of the
    levels that differ, then into the rest, one level at a time, as the
    view's own double-click and Esc do. False when a group on the way is
    hidden or locked (it cannot be entered). The tray's «In model» list
    opens to a nested copy the same way."""
    if any(g.hidden or getattr(g, "locked", False) for g in path):
        return False
    scene = viewport.scene
    current = outliner.open_path(scene)
    same = 0
    while (same < min(len(current), len(path))
           and current[same] is path[same]):
        same += 1
    for _ in range(len(current) - same):
        viewport.end_one_group_edit()
    for g in path[same:]:
        viewport.begin_group_edit(g)
    return outliner.open_path(scene) == list(path)

# Keys the tree answers itself while it has the focus, instead of the
# window's single-key shortcuts (Space is Select, Esc cancels a tool…).
_TREE_KEYS = {Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape,
              Qt.Key_F2, Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
              Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown}


# ---- Icons ---------------------------------------------------------------------
# Drawn, like the tool icons (views/icons.py), in the palette's own ink so
# they read in the light and the dark theme alike.

_ICONS: dict = {}


def _ink() -> QColor:
    from PySide6.QtWidgets import QApplication
    return QApplication.palette().text().color()


def _accent() -> QColor:
    from PySide6.QtWidgets import QApplication
    return QApplication.palette().highlight().color()


def _cube(p, ink, fill=None) -> None:
    """A small box in cavalier view: the group's mark."""
    front = QRectF(2.5, 6.5, 9, 8)
    if fill is not None:
        p.setBrush(fill)
    p.drawPolygon([QPointF(2.5, 6.5), QPointF(6.5, 2.5), QPointF(15.5, 2.5),
                   QPointF(15.5, 10.5), QPointF(11.5, 14.5),
                   QPointF(2.5, 14.5)])
    p.setBrush(Qt.NoBrush)
    p.drawRect(front)
    p.drawLine(QPointF(11.5, 6.5), QPointF(15.5, 2.5))


def _draw(key: str):
    ink = _ink()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(ink, 1.2))
    if key == "group":
        _cube(p, ink)
    elif key == "component":
        # A component is a box FILLED: the definition its copies share.
        fill = QColor(_accent())
        fill.setAlpha(110)
        _cube(p, ink, fill)
    elif key == "ifc":
        _cube(p, ink)
        p.setPen(Qt.NoPen)
        p.setBrush(_accent())
        p.drawEllipse(QRectF(10, 10, 7.5, 7.5))
    elif key == "rename":
        # A pencil, point down-left, over the line it writes.
        p.drawPolygon([QPointF(4.7, 11.0), QPointF(12.9, 2.9),
                       QPointF(15.1, 5.1), QPointF(7.0, 13.3)])
        p.drawPolygon([QPointF(4.7, 11.0), QPointF(7.0, 13.3),
                       QPointF(2.6, 15.4)])
        p.drawLine(QPointF(11.1, 4.6), QPointF(13.4, 6.9))
        p.drawLine(QPointF(9.5, 16.2), QPointF(16.2, 16.2))
    elif key in ("isolate", "isolate_on"):
        # Drawn, not the ◎ / ◉ characters: few interface fonts have them,
        # and looking for one that does is where the 0.5.8 Flatpak died at
        # start-up on a machine with a broken user font (#658).
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(2.5, 2.5, 13, 13))
        if key == "isolate_on":
            p.setPen(Qt.NoPen)
            p.setBrush(_accent())
            p.drawEllipse(QRectF(5.5, 5.5, 7, 7))
        else:
            p.drawEllipse(QRectF(6, 6, 6, 6))
    elif key in ("expand_all", "collapse_all"):
        # ⊞ / ⊟, drawn for the same reason as Isolate's (#658).
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(2.5, 2.5, 13, 13))
        p.drawLine(QPointF(5.5, 9), QPointF(12.5, 9))
        if key == "expand_all":
            p.drawLine(QPointF(9, 5.5), QPointF(9, 12.5))
    elif key == "document":
        p.drawPolygon([QPointF(2, 9), QPointF(9, 3), QPointF(16, 9)])
        p.drawRect(QRectF(4, 9, 10, 7))
    elif key == "sheet":
        p.drawPolygon([QPointF(3.5, 1.5), QPointF(11.5, 1.5),
                       QPointF(14.5, 4.5), QPointF(14.5, 16.5),
                       QPointF(3.5, 16.5)])
        p.drawLine(QPointF(11.5, 1.5), QPointF(11.5, 4.5))
        p.drawLine(QPointF(11.5, 4.5), QPointF(14.5, 4.5))
        p.drawLine(QPointF(6, 12), QPointF(12, 12))
        p.drawLine(QPointF(6, 14), QPointF(10, 14))
    elif key == "frame":
        p.drawRect(QRectF(2.5, 4.5, 13, 10))
        p.drawPolyline([QPointF(4, 13), QPointF(8, 8), QPointF(11, 11),
                        QPointF(14, 7)])
    elif key == "scene":
        # A camera: what a saved scene remembers.
        p.drawRect(QRectF(2.5, 6.5, 9, 7))
        p.drawPolygon([QPointF(11.5, 9), QPointF(15.5, 6.5),
                       QPointF(15.5, 13.5)])
    elif key in ("cut", "cut_off"):
        # A box sliced: the cut half filled when the plane cuts.
        if key == "cut":
            fill = QColor(_accent())
            fill.setAlpha(160)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPolygon([QPointF(3, 3), QPointF(15, 3), QPointF(3, 15)])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ink, 1.2))
        else:
            faint = QColor(ink)
            faint.setAlpha(110)
            p.setPen(QPen(faint, 1.2))
        p.drawRect(QRectF(3, 3, 12, 12))
        p.drawLine(QPointF(1.5, 16.5), QPointF(16.5, 1.5))
    elif key in ("lock", "lock_open"):
        # The shackle closed over the body, or swung up and open.
        p.drawRoundedRect(QRectF(4, 8.5, 10, 7.5), 1.5, 1.5)
        if key == "lock":
            p.drawArc(QRectF(5.5, 2.5, 7, 10), 0, 180 * 16)
            p.drawLine(QPointF(5.5, 7.5), QPointF(5.5, 8.5))
            p.drawLine(QPointF(12.5, 7.5), QPointF(12.5, 8.5))
        else:
            faint = QColor(ink)
            faint.setAlpha(110)
            p.setPen(QPen(faint, 1.2))
            p.drawRoundedRect(QRectF(4, 8.5, 10, 7.5), 1.5, 1.5)
            p.drawArc(QRectF(8.5, 1.5, 7, 9), 0, 180 * 16)
            p.drawLine(QPointF(8.5, 6), QPointF(8.5, 8.5))
    elif key in ("eye", "eye_off"):
        if key == "eye_off":
            p.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 110),
                          1.2))
        p.drawEllipse(QRectF(2, 5.5, 14, 7))
        p.setBrush(p.pen().color())
        p.drawEllipse(QRectF(7, 7, 4, 4))
        if key == "eye_off":
            p.setPen(QPen(ink, 1.4))
            p.drawLine(QPointF(3, 15), QPointF(15, 3))
    p.end()
    return QIcon(pm)


def _faded(icon: QIcon, size: int = 16) -> QIcon:
    """``icon`` at 40 %: the eye or padlock a row inherits from a group
    around it — closed, but not its own."""
    src = icon.pixmap(size, size)
    pm = QPixmap(src.size())
    pm.setDevicePixelRatio(src.devicePixelRatio())
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setOpacity(0.4)
    p.drawPixmap(0, 0, src)
    p.end()
    return QIcon(pm)


def inherited_states(groups) -> dict:
    """``{id(group): (hidden_by, locked_by)}`` — the nearest group around
    each one that is hidden, and that is locked (``None`` when none). What
    a closed group does to what it holds, which the rows show faded."""
    out: dict = {}

    def walk(items, hid, lock):
        for g in items or ():
            out[id(g)] = (hid, lock)
            walk(getattr(g, "children", None),
                 g if g.hidden else hid,
                 g if getattr(g, "locked", False) else lock)
    walk(groups, None, None)
    return out


def node_icon(key: str) -> QIcon:
    """The icon for a row kind — ``group``, ``component``, ``ifc``,
    ``image``, ``text``, ``document``, ``scene``, ``sheet``, ``frame``,
    ``eye``, ``eye_off``, ``warning``."""
    if key not in _ICONS:
        if key in ("image", "text", "sections"):
            from views.icons import tool_icon
            _ICONS[key] = tool_icon({"image": "image", "text": "text3d",
                                     "sections": "section_planes"}[key])
        elif key == "warning":
            from PySide6.QtWidgets import QApplication
            _ICONS[key] = QApplication.style().standardIcon(
                QStyle.SP_MessageBoxWarning)
        elif key == "folder":
            from PySide6.QtWidgets import QApplication
            _ICONS[key] = QApplication.style().standardIcon(QStyle.SP_DirIcon)
        else:
            _ICONS[key] = _draw(key)
    return _ICONS[key]


def fill_icon(color, on: bool) -> QIcon:
    """The section fill as a swatch: the style's fill colour, hatched, or
    an empty faint square when the fill is off."""
    ink = _ink()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if on:
        r, g, b = (max(0, min(255, round(c * 255))) for c in color[:3])
        p.setBrush(QColor(r, g, b))
        p.setPen(QPen(ink, 1.2))
        p.drawRect(QRectF(3, 3, 12, 12))
        p.setPen(QPen(QColor(255, 255, 255, 140), 1.0))
        for k in (6, 10, 14):
            p.drawLine(QPointF(3, 3 + k), QPointF(3 + k, 3))
    else:
        faint = QColor(ink)
        faint.setAlpha(110)
        p.setPen(QPen(faint, 1.2, Qt.DashLine))
        p.drawRect(QRectF(3, 3, 12, 12))
    p.end()
    return QIcon(pm)


def _remember_widths(header, key: str, columns, quiet=None) -> None:
    """Give ``columns`` the widths the user left them at, and keep them
    as they are dragged (per user, not per document). ``quiet()`` true:
    a resize the program made, not the user — not kept."""
    from PySide6.QtCore import QSettings
    saved = QSettings().value(key)
    if isinstance(saved, str):
        saved = saved.split(",")
    if isinstance(saved, (list, tuple)) and len(saved) == len(columns):
        for col, width in zip(columns, saved):
            try:
                if int(width) >= 40:
                    header.resizeSection(col, int(width))
            except (TypeError, ValueError):
                pass

    def save(*_args) -> None:
        if quiet is not None and quiet():
            return
        QSettings().setValue(key, ",".join(
            str(header.sectionSize(c)) for c in columns))

    header.sectionResized.connect(save)


def _tool_button(text: str, tip: str, slot) -> QToolButton:
    btn = QToolButton()
    btn.setText(text)
    btn.setToolTip(tip)
    btn.setAutoRaise(True)
    btn.clicked.connect(slot)
    return btn


# ---- Model 3D ------------------------------------------------------------------

class _HeaderButton(QToolButton):
    """The columns button, in a strip of its own at the tree's right edge,
    level with the header: the columns scroll, stretch and move under the
    header beside it, and it stays put. Drawn as a header section — the
    same face as the columns, after the header's own last line — so it
    reads as part of the header, not as a stray number on the first row."""

    def paintEvent(self, _ev) -> None:          # noqa: N802 — Qt override
        from PySide6.QtWidgets import QStyleOptionHeader
        opt = QStyleOptionHeader()
        opt.initFrom(self)
        opt.rect = self.rect()
        opt.orientation = Qt.Horizontal
        opt.position = QStyleOptionHeader.End
        opt.text = self.text()
        opt.textAlignment = Qt.AlignCenter
        if self.isDown():
            opt.state |= QStyle.State_Sunken
        else:
            opt.state |= QStyle.State_Raised
        if self.underMouse():
            opt.state |= QStyle.State_MouseOver
        p = QPainter(self)
        p.setFont(self.font())
        self.style().drawControl(QStyle.CE_Header, opt, p, self)
        # The line before it. The header's last column draws none on its
        # right (the style leaves the end of a header open), so the style
        # draws it here: a section beside this one, its right edge — the
        # separator every other column has — 1 px inside this button, the
        # rest clipped away. 2 px of clip: at 125 % display scaling one
        # logical pixel falls between device pixels and the line vanished.
        r = self.rect()
        edge = QStyleOptionHeader()
        edge.initFrom(self)
        edge.orientation = Qt.Horizontal
        edge.position = QStyleOptionHeader.Middle
        edge.state |= QStyle.State_Raised
        edge.rect = r.translated(-r.width() + 2, 0)
        p.setClipRect(0, 0, 2, r.height())
        self.style().drawControl(QStyle.CE_HeaderSection, edge, p, self)
        p.end()


class _StripFiller(QWidget):
    """The strip kept at the tree's right for the columns button, below the
    button: painted as the rows beside it — their tone, alternate or not,
    and the selection's — so it reads as their end, not as a lighter band
    (the frame behind it shows the window's colour)."""

    def __init__(self, tree) -> None:
        super().__init__(tree)
        self._tree = tree

    def paintEvent(self, _ev) -> None:          # noqa: N802 — Qt override
        from PySide6.QtCore import QPoint
        tree = self._tree
        pal = tree.palette()
        p = QPainter(self)
        p.fillRect(self.rect(), pal.color(QPalette.Base))
        vp = tree.viewport()
        y = 0
        odd = None
        while y < vp.height():
            index = tree.indexAt(QPoint(1, y))
            if not index.isValid():
                break
            rect = tree.visualRect(index)
            if rect.height() <= 0:
                break
            # The first row's parity once, then every row flips it.
            odd = tree.row_parity(index) if odd is None else not odd
            item = tree.itemFromIndex(index)
            if item is not None and item.isSelected():
                colour = pal.color(QPalette.Highlight)
            elif tree.alternatingRowColors() and odd:
                colour = pal.color(QPalette.AlternateBase)
            else:
                colour = None
            if colour is not None:
                p.fillRect(0, rect.top(), self.width(), rect.height(), colour)
            y = rect.bottom() + 1
        p.end()


def library_catalog() -> list:
    """The material library the Materials tab offers, as ``[(category,
    [(label, paint, swatch)])]``: the RAL colours (named, as the tab paints
    them: «RAL 7035 Light grey»), each texture category of the bundled
    manifest, and the loose images in resources/textures. ``paint`` is a
    container material; ``swatch()`` reads the image only when asked — the
    library holds hundreds of them."""
    import json as _json
    from views import tray as _tray
    out: list = []
    colours = []
    if _tray._RAL_FILE.exists():
        data = _json.loads(_tray._RAL_FILE.read_text(encoding="utf-8"))
        for fam in data.get("families", []):
            for c in fam.get("colors", []):
                name = "%s %s" % (c["code"], _tray._ral_name(c))
                colours.append((
                    "%s · %s" % (c["code"], _tray._ral_name(c)),
                    {"color": list(c["rgb"]), "mat": name},
                    lambda rgb=c["rgb"]: _tray._color_pixmap(rgb)))
    if colours:
        out.append((tr("Colors"), colours))
    manifest = _tray._TEX_DIR / "library.json"
    if manifest.exists():
        data = _json.loads(manifest.read_text(encoding="utf-8"))
        names = _tray.MaterialsPanel.CATEGORY_NAMES
        for cat in data.get("categories", []):
            entries = []
            for item in cat.get("items", []):
                path = _tray._TEX_DIR / "library" / item["file"]
                label = tr(item["name"])
                paint = {"texture": {"path": str(path),
                                     "sw": float(item.get("sw") or 1.0),
                                     "sh": float(item.get("sh") or 1.0),
                                     "rot": 0.0},
                         "mat": label}
                if item.get("opacity") is not None:
                    paint["opacity"] = float(item["opacity"])
                entries.append((
                    label, paint,
                    lambda pa=path, op=item.get("opacity"):
                    _tray._texture_pixmap(pa, opacity=op)))
            if entries:
                out.append((tr(names.get(cat["id"], cat["id"])), entries))
    loose = sorted(_tray._TEX_DIR.glob("*.png"))
    if loose:
        out.append((tr("Other"), [
            (pa.stem, {"texture": {"path": str(pa), "sw": 1.0, "sh": 1.0,
                                   "rot": 0.0}, "mat": pa.stem},
             lambda q=pa: _tray._texture_pixmap(q)) for pa in loose]))
    return out


class BatchRenameDialog(QDialog):
    """Rename several rows at once (#565, @fafecm; #87): a name and a
    number (W01, W02…), find and replace, or a prefix and a suffix — with
    the names before and after side by side before anything changes. The
    rows come in the tree's order, top to bottom, so the numbers follow
    it. ``names()`` gives the new names, one per row."""

    NUMBER, REPLACE, AFFIX = range(3)

    def __init__(self, old_names, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import (QCheckBox, QDialogButtonBox,
                                       QFormLayout, QSpinBox, QTabWidget,
                                       QTableWidget, QTableWidgetItem)
        self._Item = QTableWidgetItem
        # As Preferences: «— IngeTrazo» in the title, one tab per way of
        # renaming, forms with their labels, OK and Cancel at the bottom.
        self.setWindowTitle(tr("Rename selected") + " — IngeTrazo")
        self.setMinimumWidth(440)
        self.resize(480, 440)
        self.old = list(old_names)
        lay = QVBoxLayout(self)
        self.mode = self.pages = QTabWidget()
        # Name and number
        page = QWidget()
        form = QFormLayout(page)
        self.base = QLineEdit(outliner_common_prefix(self.old) or "W")
        self.start = QSpinBox()
        self.start.setRange(0, 99999)
        self.start.setValue(1)
        self.digits = QSpinBox()
        self.digits.setRange(1, 6)
        self.digits.setValue(2)
        form.addRow(tr("Name:"), self.base)
        form.addRow(tr("Start at:"), self.start)
        form.addRow(tr("Digits:"), self.digits)
        self.pages.addTab(page, tr("Name and number"))
        # Find and replace
        page = QWidget()
        form = QFormLayout(page)
        self.find = QLineEdit()
        self.replace = QLineEdit()
        self.match_case = QCheckBox(tr("Match case"))
        form.addRow(tr("Find:"), self.find)
        form.addRow(tr("Replace with:"), self.replace)
        form.addRow("", self.match_case)
        self.pages.addTab(page, tr("Find and replace"))
        # Prefix and suffix
        page = QWidget()
        form = QFormLayout(page)
        self.prefix = QLineEdit()
        self.suffix = QLineEdit()
        form.addRow(tr("Prefix:"), self.prefix)
        form.addRow(tr("Suffix:"), self.suffix)
        self.pages.addTab(page, tr("Prefix and suffix"))
        lay.addWidget(self.pages)
        self.preview = QTableWidget(len(self.old), 2)
        self.preview.setHorizontalHeaderLabels([tr("Before"), tr("After")])
        self.preview.verticalHeader().setVisible(False)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setColumnWidth(0, 200)
        lay.addWidget(self.preview, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        self.ok = buttons.button(QDialogButtonBox.Ok)
        self.ok.setText(tr("Rename"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        for w in (self.base, self.find, self.replace, self.prefix,
                  self.suffix):
            w.textChanged.connect(self._update)
        for w in (self.start, self.digits):
            w.valueChanged.connect(self._update)
        self.match_case.toggled.connect(self._update)
        self.mode.currentChanged.connect(self._update)
        self._update()

    def names(self) -> list:
        mode = self.mode.currentIndex()
        if mode == self.NUMBER:
            return outliner.numbered_names(len(self.old), self.base.text(),
                                           self.start.value(),
                                           self.digits.value())
        if mode == self.REPLACE:
            return outliner.replaced_names(self.old, self.find.text(),
                                           self.replace.text(),
                                           self.match_case.isChecked())
        return outliner.affixed_names(self.old, self.prefix.text(),
                                      self.suffix.text())

    def _update(self, *_a) -> None:
        new = self.names()
        bold = QFont(self.font())
        bold.setBold(True)
        for row, (before, after) in enumerate(zip(self.old, new)):
            self.preview.setItem(row, 0, self._Item(before))
            cell = self._Item(after)
            if after != before:
                cell.setFont(bold)          # what will change
            self.preview.setItem(row, 1, cell)
        changed = any(a != b for a, b in zip(self.old, new))
        self.ok.setEnabled(changed and all(n.strip() for n in new))


def outliner_common_prefix(names) -> str:
    """What the names start with in common, trailing digits, spaces and
    separators dropped — «Muro 01», «Muro 02» → «Muro »… → «Muro»; a fair
    first guess for the base of a numbering."""
    import os
    common = os.path.commonprefix(list(names)) if names else ""
    return common.rstrip("0123456789 _-#.").strip()


class MaterialLibraryDialog(QDialog):
    """«More materials…»: the whole library in a window of its own, as
    «New color…» opens the colour dialog — categories on the left, their
    swatches on the right (read the first time a category is shown), and a
    search across all of them. A click on a swatch closes it with that
    paint in ``chosen``."""

    #: How many matches a search shows at most (each reads an image).
    SEARCH_LIMIT = 120

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QListWidget, QScrollArea
        from PySide6.QtWidgets import QDialogButtonBox
        from views.theme import style as theme_style
        self.setWindowTitle(tr("Materials") + " — IngeTrazo")
        self.resize(660, 480)
        self.chosen = None
        self._catalog = library_catalog()
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._show_search)
        lay.addWidget(self.search)
        note = QLabel(tr("Click a swatch to apply it"))
        theme_style(note, "color:{muted}; font-size:11px;")
        lay.addWidget(note)
        row = QHBoxLayout()
        self.categories = QListWidget()
        self.categories.setMaximumWidth(190)
        for title, entries in self._catalog:
            self.categories.addItem("%s  (%d)" % (title, len(entries)))
        self.categories.currentRowChanged.connect(self._show_category)
        row.addWidget(self.categories)
        self._area = QScrollArea()
        self._area.setWidgetResizable(True)
        row.addWidget(self._area, 1)
        lay.addLayout(row, 1)
        # As every dialog of the program: its buttons at the bottom right.
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.buttons: list = []         # (label, button) of what is shown
        if self._catalog:
            self.categories.setCurrentRow(0)

    def _fill(self, entries) -> None:
        from views.tray import FlowLayout, _SWATCH
        body = QWidget()
        flow = FlowLayout(body, spacing=2)
        self.buttons = []
        for label, paint, swatch in entries:
            pm = swatch()
            if pm is None:
                continue
            b = QToolButton()
            b.setIcon(QIcon(pm))
            b.setIconSize(QSize(_SWATCH, _SWATCH))
            b.setToolTip(label)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _c=False, pt=paint: self._choose(pt))
            flow.addWidget(b)
            self.buttons.append((label, b))
        if not self.buttons:
            flow.addWidget(QLabel(tr("No materials yet")))
        self._area.setWidget(body)

    def _show_category(self, row: int) -> None:
        if 0 <= row < len(self._catalog) and not self.search.text().strip():
            self._fill(self._catalog[row][1])

    def _show_search(self, text: str) -> None:
        needle = text.strip().casefold()
        if not needle:
            self._show_category(self.categories.currentRow())
            return
        found = [e for _t, entries in self._catalog for e in entries
                 if needle in e[0].casefold()]
        self._fill(found[:self.SEARCH_LIMIT])

    def _choose(self, paint) -> None:
        self.chosen = paint
        self.accept()

    def showEvent(self, ev) -> None:            # noqa: N802 — Qt override
        super().showEvent(ev)
        self.place()

    def place(self) -> None:
        """In the middle of the screen the program is on, wholly on it,
        title bar included. Placed once shown, when the frame's size is
        known: placed before, a window not maximised (or one wider than
        the screen) sent it to the bottom, half hidden."""
        win = self.parentWidget().window() if self.parentWidget() else None
        screen = (win.screen() if isinstance(win, QWidget) else None)             or QApplication.primaryScreen()
        room = screen.availableGeometry()
        frame = self.frameGeometry()
        x = room.center().x() - frame.width() // 2
        y = room.center().y() - frame.height() // 2
        x = max(room.left(), min(x, room.right() + 1 - frame.width()))
        y = max(room.top(), min(y, room.bottom() + 1 - frame.height()))
        self.move(x, y)             # a window's move() places its frame

    @classmethod
    def choose(cls, parent=None):
        """Open it and wait: the paint picked, or ``None``. It opens in the
        middle of the screen, not where the panel was."""
        dlg = cls(parent)
        dlg.exec()
        return dlg.chosen


class MaterialPopup(QFrame):
    """A floating, short-lived panel to give rows a material: opened by a
    click on a row's Material cell, gone on a choice or a click outside.
    The document's materials and the recent paints as swatches (a search
    field narrows them), «No material», «New color…» (an optional name
    makes it a material of the document) and «More materials…» (the whole
    library, in a window of its own). ``apply(paint)`` is
    called with the chosen container material, or ``None`` for none."""

    COLS = 6
    SWATCH = 26

    def __init__(self, parent, scene, recent, current, apply) -> None:
        super().__init__(parent, Qt.Popup)
        from PySide6.QtWidgets import QGridLayout, QPushButton
        from views.theme import style as theme_style
        self.setAttribute(Qt.WA_DeleteOnClose)
        # Framed and compact, as the Fillet 3D panel floating in the view.
        self.setFrameShape(QFrame.StyledPanel)
        self._apply = apply
        from tools.paint import recent_key
        # The paint the row wears, by identity (its material's name, or its
        # colour or image): the swatch for it shows framed.
        self._current = recent_key(current) if current else None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self._swatches: list = []
        choices = outliner.material_choices(scene, recent)
        names = set(getattr(scene, "materials", None) or {})
        doc = [(l, pt) for l, pt in choices if pt.get("mat") in names]
        rest = [(l, pt) for l, pt in choices if pt.get("mat") not in names]
        for title, group in ((tr("In model"), doc), (tr("Recent"), rest)):
            if not group:
                continue
            # A section's title as Preferences writes its notes: small, grey.
            head = QLabel(title)
            theme_style(head, "color:{muted}; font-size:11px;")
            lay.addWidget(head)
            grid = QGridLayout()
            grid.setSpacing(3)
            for i, (label, paint) in enumerate(group):
                b = QToolButton()
                b.setAutoRaise(True)
                b.setCheckable(True)
                b.setChecked(recent_key(paint) == self._current)
                b.setStyleSheet("QToolButton:checked { border: 2px solid "
                                "palette(highlight); border-radius: 3px; }")
                b.setIcon(_paint_icon(paint, self.SWATCH))
                b.setIconSize(QSize(self.SWATCH, self.SWATCH))
                b.setToolTip(label)
                b.clicked.connect(lambda _c=False, pt=paint: self._choose(pt))
                grid.addWidget(b, i // self.COLS, i % self.COLS)
                self._swatches.append((label.casefold(), b))
            # Left-aligned in every section, however few swatches it has.
            grid.setColumnStretch(self.COLS, 1)
            lay.addLayout(grid)
        if not self._swatches:
            lay.addWidget(QLabel(tr("No materials yet")))
        none = QPushButton(tr("No material"))
        none.clicked.connect(lambda: self._choose(None))
        lay.addWidget(none)
        new = QPushButton(tr("New color…"))
        new.clicked.connect(self._new_colour)
        lay.addWidget(new)
        more_btn = QPushButton(tr("More materials…"))
        more_btn.setToolTip(tr(
            "The whole library: RAL colours and textures by category"))
        more_btn.clicked.connect(self._open_more)
        lay.addWidget(more_btn)
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for label, b in self._swatches:
            b.setVisible(not needle or needle in label)

    def _choose(self, paint) -> None:
        self.close()
        self._apply(paint)

    def _new_colour(self) -> None:
        """Pick a colour; a name, if given, makes it a material of the
        document (listed in the Materials tab), otherwise a plain colour."""
        from views import prompts
        from views.color_dialog import get_color
        from PySide6.QtWidgets import QColorDialog
        self.hide()                     # the dialogs take the stage
        colour = get_color(
            QColor(200, 200, 200), self.parentWidget(), tr("New color…"),
            options=QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not colour.isValid():
            self.close()
            return
        name, ok = prompts.get_text(self.parentWidget(), tr("New material"),
                                    tr("Material name (optional):"))
        self.close()
        if not ok:
            return
        paint = {"color": [colour.redF(), colour.greenF(), colour.blueF()]}
        if colour.alphaF() < 0.99995:
            paint["opacity"] = colour.alphaF()
        if name.strip():
            paint["mat"] = name.strip()
        self._apply(paint)

    def _open_more(self) -> None:
        """The library in its own window, as «New color…» opens the colour
        dialog; what is picked there paints the rows."""
        self.hide()                     # the dialog takes the stage
        paint = MaterialLibraryDialog.choose(self.parentWidget())
        self.close()
        if paint is not None:
            self._apply(paint)

    def popup_at(self, global_pos) -> None:
        """Shown with its top-left at ``global_pos``, kept on the screen."""
        self.adjustSize()
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(global_pos.x(), area.right() - self.width())
        y = global_pos.y()
        if y + self.height() > area.bottom():
            y = max(area.top(), y - self.height())
        self.move(max(area.left(), x), y)
        self.show()


class _MaterialCellDelegate(QStyledItemDelegate):
    """The Material cell with a small ▾ at its right end: the handle that
    opens the material panel. Pressing it does not select the row — the
    rest of the cell selects, as anywhere in the row — so choosing a
    material and selecting are never mixed up."""

    #: Width of the ▾ handle at the cell's right end.
    ARROW = 16

    def paint(self, painter, option, index) -> None:
        if not index.data(_GROUP_ROLE_FLAG):
            super().paint(painter, option, index)
            return
        from PySide6.QtWidgets import QStyleOption, QStyleOptionViewItem
        style = option.widget.style() if option.widget else QApplication.style()
        # The row's background and selection over the whole cell; the
        # swatch and the name stop short of the ▾.
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter,
                            option.widget)
        opt.rect = option.rect.adjusted(0, 0, -self.ARROW, 0)
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, option.widget)
        arrow = QStyleOption()
        arrow.initFrom(option.widget)
        r = self.arrow_rect(option.rect)
        arrow.rect = r.adjusted(3, r.height() // 2 - 4, -3,
                                -(r.height() // 2 - 4))
        arrow.palette = option.palette
        if option.state & QStyle.State_Selected:
            arrow.palette.setColor(QPalette.ButtonText, option.palette.color(
                QPalette.HighlightedText))
        style.drawPrimitive(QStyle.PE_IndicatorArrowDown, arrow, painter,
                            option.widget)

    @classmethod
    def arrow_rect(cls, cell):
        """Where the ▾ sits in a cell's rectangle."""
        return cell.adjusted(max(0, cell.width() - cls.ARROW), 0, 0, 0)


#: Set on a row's Material cell when the row is a group (it gets a ▾).
_GROUP_ROLE_FLAG = Qt.UserRole + 7


class _Tree(QTreeWidget):
    """The tree, with the keyboard of an outliner: Space shows or hides the
    selected rows, Enter opens the current one, Esc steps out one level,
    Tab puts the selection into the group above it and Shift+Tab takes it
    out one level. Rows dragged onto a group go into it; dropped between
    rows, they go beside them."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        #: Width of the strip kept free at the right for the columns button.
        self.button_strip = 0
        self._filler = _StripFiller(self)
        self._filler.hide()
        # It repaints with the rows: scrolled, expanded, selected.
        self.viewport().installEventFilter(self)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def updateGeometries(self) -> None:          # noqa: N802 — Qt override
        """Qt lays the header over the whole viewport and sets the margins
        for it; a strip is then kept at the right for the columns button,
        with the header (and the rows) one strip narrower."""
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
        b = getattr(self._panel, "_columns_button", None)
        if b is not None:
            g = head.geometry()
            b.setGeometry(g.right() + 1, g.top(), b.width(), g.height())
        self._filler.setGeometry(vg.right() + 1, vg.top(), self.button_strip,
                                 vg.height())
        self._filler.setVisible(self.button_strip > 0)

    def row_parity(self, index) -> bool:
        """Whether the row of ``index`` is one the tree paints in the
        alternate tone: every other row shown, counted from the top. For
        the first row on screen, scrolling by rows already counts them."""
        if (self.verticalScrollMode() == QAbstractItemView.ScrollPerItem
                and index == self.indexAt(self.viewport().rect().topLeft())):
            return bool(self.verticalScrollBar().value() % 2)
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

    def mousePressEvent(self, ev) -> None:      # noqa: N802 — Qt override
        """A press on the eye, the padlock or a Material cell's ▾ acts at
        once and is kept from the selection: the rows stay as selected as
        they were, so the eye of one of several selected rows hides them
        all (as the material panel paints them all). Before, the press
        selected that one row first, and only it was hidden."""
        if ev.button() == Qt.LeftButton:
            index = self.indexAt(ev.position().toPoint())
            if index.isValid() and index.column() in (COL_EYE, COL_LOCK):
                self._panel._on_item_clicked(self.itemFromIndex(index),
                                             index.column())
                ev.accept()
                return
            if (index.isValid() and index.column() == COL_MATERIAL
                    and index.data(_GROUP_ROLE_FLAG)):
                cell = self.visualRect(index)
                if _MaterialCellDelegate.arrow_rect(cell).contains(
                        ev.position().toPoint()):
                    self._panel.material_popup(self.itemFromIndex(index))
                    ev.accept()
                    return
        super().mousePressEvent(ev)

    def event(self, ev) -> bool:
        from PySide6.QtCore import QEvent
        editing = self.state() == QAbstractItemView.EditingState
        if (ev.type() == QEvent.ShortcutOverride and not editing
                and (ev.key() in _TREE_KEYS
                     or ev.key() in (Qt.Key_Tab, Qt.Key_Backtab))
                and not (ev.modifiers() & (Qt.ControlModifier
                                           | Qt.AltModifier))):
            ev.accept()
            return True
        # Tab moves the focus before keyPressEvent ever sees it.
        if (ev.type() == QEvent.KeyPress and not editing
                and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab)):
            if ev.key() == Qt.Key_Backtab or \
                    ev.modifiers() & Qt.ShiftModifier:
                self._panel.outdent()
            else:
                self._panel.indent()
            return True
        return super().event(ev)

    def dropEvent(self, ev) -> None:
        """Re-nest through the panel — one undoable command — and never let
        Qt move the rows itself: the tree follows the model, not the other
        way round."""
        item = self.itemAt(ev.position().toPoint())
        if item is not None and \
                self.dropIndicatorPosition() != QAbstractItemView.OnItem:
            item = item.parent()            # between rows: beside them
        ev.setDropAction(Qt.IgnoreAction)
        ev.accept()
        sections = self._panel._sec_root
        if item is not None and sections is not None and (
                item is sections or item.parent() is sections):
            return                          # planes are not containers
        self._panel.reparent(self._panel._selected_groups(),
                             self._panel._group_of(item))

    def keyPressEvent(self, ev) -> None:
        if self.state() != QAbstractItemView.EditingState:
            key = ev.key()
            if key == Qt.Key_F2:
                plane = self._panel._plane_of(self.currentItem())
                if plane is not None:
                    self._panel.rename_plane(plane)
                    return
                picked = self._panel._selected_groups()
                if len(picked) > 1:         # several rows: all at once
                    self._panel.ask_batch_rename(picked)
                    return
            if key == Qt.Key_Space:
                self._panel.toggle_hidden()
                return
            if key in (Qt.Key_Return, Qt.Key_Enter):
                item = self.currentItem()
                if item is not None:
                    self._panel.open_item(item)
                return
            if key == Qt.Key_Escape:
                self._panel.step_out()
                return
        super().keyPressEvent(ev)


class OutlinerPanel(QWidget):
    """The model's tree of groups and components (the Model 3D tab)."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        self._stale = False
        self._shape: tuple | None = None
        self._items: dict = {}              # id(group) -> its row
        self._groups: dict = {}             # id(group) -> the group
        self._state: dict = {}              # id(group) -> what its row shows
        self._shown_selection: tuple = ()
        #: Rows picked in the tree that the view cannot select — hidden or
        #: locked — kept highlighted here: clicked, they used to be
        #: deselected at once, the view having nothing to select. Dropped
        #: when the selection changes anywhere else.
        self._tree_only: set = set()
        self._shown_path: tuple = ()
        self._query = ""
        self._kind_providers: tuple = ()
        self._root = None
        self._sec_root = None               # the «Section planes» folder
        self._sec_items: dict = {}          # id(plane) -> its row
        self._sec_state: dict = {}
        self._sec_shape = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter by name, type or layer…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_filter)
        bar.addWidget(self.search, 1)
        # Isolate and Show all in one button, as they undo each other:
        # with nothing hidden it isolates the selection; with anything
        # hidden (isolated, or hidden by hand) it shows it all, pressed.
        # Rename: one row in place, several rows at once (Rename selected).
        self._rename_btn = _tool_button("", tr(
            "Rename (F2): several selected rows at once — a name and a "
            "number, find and replace, a prefix or a suffix; one row in "
            "place; nothing selected: every row the filter shows"),
            self._rename_picked)
        self._rename_btn.setIcon(node_icon("rename"))
        bar.addWidget(self._rename_btn)
        self._isolate_btn = _tool_button("", "", self._isolate_or_show)
        self._isolate_btn.setCheckable(True)
        bar.addWidget(self._isolate_btn)
        self._update_isolate_button()
        # Expand all and Collapse all in one button too: ⊞ while a branch
        # is folded, ⊟ once everything is open.
        self._expand_btn = _tool_button("", tr("Expand all"),
                                        self._expand_or_collapse)
        self._expand_btn.setIcon(node_icon("expand_all"))
        bar.addWidget(self._expand_btn)
        lay.addLayout(bar)
        self.tree = _Tree(self)
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels([tr("Name"), "", "", tr("Type"),
                                   tr("Layer"), tr("Material"), tr("Copies"),
                                   tr("IFC class")])
        head = self.tree.header()
        # The Name column is the user's to size — drag its edge in the
        # header; the width is remembered. The last column takes the rest.
        head.setStretchLastSection(True)
        # A title that does not fit ends in «…»: cut short at the column's
        # edge, the last one looked hidden under the columns button.
        head.setTextElideMode(Qt.ElideRight)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        head.resizeSection(COL_NAME, 200)
        head.setSectionResizeMode(COL_EYE, QHeaderView.Fixed)
        head.resizeSection(COL_EYE, 26)
        head.setSectionResizeMode(COL_LOCK, QHeaderView.Fixed)
        head.resizeSection(COL_LOCK, 26)
        head.setSectionResizeMode(COL_TYPE, QHeaderView.Interactive)
        head.resizeSection(COL_TYPE, 110)
        head.setSectionResizeMode(COL_LAYER, QHeaderView.Interactive)
        head.resizeSection(COL_LAYER, 80)
        # Until the user drags a column edge, Name, Type and Layer share the
        # panel's width as it changes (see _fit_columns).
        self._fitting = False
        from PySide6.QtCore import QSettings
        self._auto_fit = not QSettings().contains("browser/model_columns")
        # Kept only once the user has sized them: while they follow the
        # panel, what Qt or the fitting does to them is nobody's choice.
        _remember_widths(head, "browser/model_columns",
                         (COL_NAME, COL_TYPE),
                         quiet=lambda: self._fitting or self._auto_fit)
        for col, width in ((COL_MATERIAL, 100), (COL_COPIES, 60),
                           (COL_IFC, 110)):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            head.resizeSection(col, width)
        # Right-click on the header: which columns show (remembered).
        head.setContextMenuPolicy(Qt.CustomContextMenu)
        head.customContextMenuRequested.connect(self._on_header_menu)
        # A button at the header's right end opens the same menu, so the
        # columns that are off show they are there to turn on.
        self._columns_button = _HeaderButton(self.tree)
        self._columns_button.setToolTip(tr(
            "Columns: show or hide Type, Layer, Material, Copies and IFC "
            "class"))
        self._columns_button.clicked.connect(self._on_columns_button)
        head.installEventFilter(self)
        self.tree.horizontalScrollBar().valueChanged.connect(
            lambda _v: self._place_columns_button())
        self._apply_column_choice()
        # The eye and the padlock come first, before the name; the tree's
        # branches stay on the Name column wherever it sits. The columns
        # can be dragged to another order, which is remembered; Window ▸
        # Panels ▸ Restore default panels puts them back.
        self.tree.setTreePosition(COL_NAME)
        self._material_delegate = _MaterialCellDelegate(self.tree)
        self.tree.setItemDelegateForColumn(COL_MATERIAL,
                                           self._material_delegate)
        head.setSectionsMovable(True)
        head.setFirstSectionMovable(True)
        self._apply_column_order()
        head.sectionMoved.connect(self._save_column_order)
        head.sectionResized.connect(self._on_section_resized)
        # A user's resize is a drag on the header: Qt resizes sections on
        # its own too (the old last column stops stretching when a new one
        # is shown), and those must not end the fitting.
        self._header_pressed = False
        head.viewport().installEventFilter(self)
        self.tree.headerItem().setIcon(COL_EYE, node_icon("eye"))
        self.tree.headerItem().setToolTip(COL_EYE, tr(
            "Visible — click to hide everything, or to show it all again"))
        self.tree.headerItem().setIcon(COL_LOCK, node_icon("lock"))
        self.tree.headerItem().setToolTip(COL_LOCK, tr(
            "Locked: drawn, but it cannot be picked, selected or opened — "
            "click to lock everything, or to unlock it all again"))
        # The eye's and the padlock's own headers act on the whole model.
        head.setSectionsClickable(True)
        head.sectionClicked.connect(self._on_header_clicked)
        self.tree.setUniformRowHeights(True)
        # A short step per level of nesting: the branch arrow still fits,
        # and a deep tree keeps its names in a sidebar-wide panel (20 px a
        # level was Qt's default).
        self.tree.setIndentation(self.INDENT)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Double-click OPENS a group, as in the view: renaming is F2 or the
        # context menu.
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.tree.setToolTip(tr(
            "Click to select in the model; double-click or Enter opens the "
            "group. The eye (or Space) shows or hides, the padlock locks; "
            "F2 renames; Esc steps out one level. Drag rows onto a group, "
            "or press Tab / Shift+Tab, to move them in or out of it."))
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemSelectionChanged.connect(self._update_rename_button)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemExpanded.connect(
            lambda _i: self._update_expand_button())
        self.tree.itemCollapsed.connect(
            lambda _i: self._update_expand_button())
        self._root = None
        lay.addWidget(self.tree, 1)
        self._empty = QLabel(tr(
            "No groups or components in the model yet."))
        self._empty.setWordWrap(True)
        self._empty.setEnabled(False)
        lay.addWidget(self._empty)
        self.summary = QLabel()
        self.summary.setEnabled(False)
        lay.addWidget(self.summary)
        self._matches = 0
        self.refresh()

    # ---- Model → view --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def on_scene_changed(self) -> None:
        """The dock's per-change call: refreshed when on screen, on
        showing otherwise — a hidden tab costs nothing per edit. On screen,
        one refresh 300 ms after the last edit: every row's state is read
        again (17 ms per edit on the Plaza, release_check 09-10), and a
        burst of edits pays it once."""
        if not self.isVisible():
            if not self._stale and self._holds_departed_groups():
                self._forget_rows()     # New / Open: let the old one go
            self._stale = True
            return
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._refresh_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(
                lambda: self.refresh(rows_if_changed=True))
        timer.start(300)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._stale:
            self.refresh()
        if not getattr(self, "_room_made", False):
            # Columns turned on in an earlier session: the first time the
            # panel has a width, make room for them as when turned on.
            self._room_made = True
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._make_room_for_shown)

    def _make_room_for_shown(self) -> None:
        if self._auto_fit:
            self._fit_columns()
            self._scroll_to_column(COL_NAME)
            return
        head = self.tree.header()
        for col in (COL_MATERIAL, COL_COPIES, COL_IFC):
            if not head.isSectionHidden(col):
                self._make_room_for(col)
        self._scroll_to_column(COL_NAME)               # the names first

    def _document_name(self) -> str:
        w = self._window
        path = getattr(w, "_current_path", None)
        if path is not None:
            return path.name
        return getattr(w, "_import_name", None) or tr("Untitled")

    def refresh(self, rows_if_changed: bool = False) -> None:
        """Bring the tree up to date: rows rebuilt only when groups came or
        went, otherwise updated in place — a refresh follows every edit and
        every click, and a rebuild would lose the scroll and the branches
        the user unfolded. ``rows_if_changed`` (the model's own change
        notice): the rows are read again only if the content or the open
        path changed since they last were."""
        if self.tree.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        self._stale = False
        self._update_isolate_button()
        self._kind_providers = tuple(
            getattr(self._window, "_outliner_kinds", None) or ())
        scene = self._scene()
        shape = outliner.structure(scene.groups)
        # A click changes the view, not the rows: with the content and the
        # open path as they were, every row reads as it did (21 406 rows
        # read again after each click on the plant of #158, ~0.15 s).
        rows_key = (getattr(scene, "content_version", None), id(scene),
                    shape, tuple(id(g) for g in outliner.open_path(scene)),
                    self._kind_providers, self._document_name())
        old_key = getattr(self, "_rows_key", None)
        hist = getattr(self._window.viewport, "history", None)
        # Only groups put in or taken out since the rows were last read
        # (a Delete, a Paste, their undo — History.groups_cv): their rows
        # come and go, the others stay as they are — but for the copies
        # count of a component that gained or lost one.
        groups_only = (rows_if_changed and old_key is not None
                       and rows_key[0] is not None
                       and not self._kind_providers
                       and old_key[1] == rows_key[1]
                       and old_key[3:] == rows_key[3:]
                       and hist is not None
                       and getattr(hist, "groups_cv", {}).get("rows")
                       == rows_key[0])
        # Only a group opened or closed since (History.context_changed):
        # what a row shows changes for the groups on the open path, old and
        # new, and for the copies of a component whose count moved (its
        # instance edits a world copy) — the other 21 406 rows of the plant
        # of #158 read as they did (~0.15 s each way).
        ctx_only = (rows_if_changed and old_key is not None
                    and rows_key[0] is not None
                    and not self._kind_providers
                    and shape == self._shape
                    and old_key[1:3] == rows_key[1:3]
                    and old_key[4:] == rows_key[4:]
                    and hist is not None
                    and getattr(hist, "groups_cv", {}).get("rows")
                    == rows_key[0])
        patched = False
        if shape != self._shape:
            patched = groups_only and self._patch_rows(scene, shape)
            if not patched:
                self._rebuild(scene)
            self._shape = shape
        # Nor does a Move (History.rows_cv) — unless an extension's kind
        # adds properties to the rows, which may well be sizes.
        moved_only = (old_key is not None and not self._kind_providers
                      and old_key[1:] == rows_key[1:]
                      and getattr(hist, "rows_cv", None) == rows_key[0])
        if (not rows_if_changed or rows_key[0] is None
                or (rows_key != old_key and not moved_only)):
            if ctx_only:
                self._update_some_rows(scene, set(old_key[3])
                                       | set(rows_key[3]))
            elif not patched:
                self._update_rows(scene)
            if hist is not None:
                hist.rows_cv = rows_key[0]
                hist.groups_cv["rows"] = rows_key[0]
        self._rows_key = rows_key
        self._sync_sections(scene)
        if self._query:
            self._apply_filter()
        self._sync_selection(scene)
        self._empty.setVisible(not self._items)
        self._update_summary()
        self._update_expand_button()
        self._update_rename_button()

    def _holds_departed_groups(self) -> bool:
        """Whether a row still holds a group the model no longer has —
        after New or Open (both load into the same scene), or a delete."""
        if not self._groups:
            return False
        live = {id(g) for g, _p, _d in outliner.walk(self._scene().groups)}
        return any(key not in live for key in self._groups)

    def _forget_rows(self) -> None:
        """Drop the rows of a document that is no longer open. Each row
        holds its group, so a hidden Browser waiting to be shown kept the
        whole previous document in memory after Open (release_check
        10-10); the next refresh builds the rows of the new one."""
        self._kept_expanded = {self._groups[key].uid
                               for key, item in self._items.items()
                               if item.isExpanded()}
        self.tree.clear()
        self._items = {}
        self._groups = {}
        self._state = {}
        self._rows_key = None
        self._root = None
        self._shape = None

    def _update_summary(self) -> None:
        """The footer: what the model holds, or what the filter found."""
        total = len(self._state)
        if self._query:
            text = tr("{shown} of {total} match", shown=self._matches,
                      total=total)
        else:
            comps = sum(1 for st in self._state.values()
                        if st[3] == "component")
            hidden = sum(1 for st in self._state.values() if st[4])
            text = tr("{groups} groups · {components} components · "
                      "{hidden} hidden", groups=total - comps,
                      components=comps, hidden=hidden)
        if self.summary.text() != text:
            self.summary.setText(text)

    def _rebuild(self, scene) -> None:
        """Rows for every group, each born with its texts and icons: one
        constructor call does what a setText per column would, and the
        cache it fills tells ``_update_rows`` there is nothing left to do."""
        expanded = {self._groups[key].uid
                    for key, item in self._items.items() if item.isExpanded()}
        expanded |= self.__dict__.pop("_kept_expanded", set())
        scroll = self.tree.verticalScrollBar().value()
        counts = self._counts = outliner.instance_counts(scene.groups)
        opened = {id(g) for g in outliner.open_path(scene)}
        self._updating = True
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self._items = {}
            self._groups = {}
            self._state = {}
            root = self._root = QTreeWidgetItem(["", "", "", "", ""])
            root.setIcon(COL_NAME, node_icon("document"))
            root.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
            font = QFont(root.font(COL_NAME))
            font.setBold(True)
            root.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(root)
            editable = Qt.ItemIsEditable
            around = inherited_states(scene.groups)
            for g, parent, _depth in outliner.walk(scene.groups):
                key = id(g)
                state = self._row_state(g, counts, opened,
                                        around.get(key, (None, None)))
                item = QTreeWidgetItem([state[0], "", "", state[1],
                                        state[2], state[7], state[8],
                                        state[9]])
                item.setData(COL_NAME, Qt.UserRole, g)
                item.setFlags(item.flags() | editable)
                self._paint(item, None, state)
                (root if parent is None
                 else self._items[id(parent)]).addChild(item)
                self._items[key] = item
                self._groups[key] = g
                self._state[key] = state
            root.setExpanded(True)
            sec = self._sec_root = QTreeWidgetItem(["", "", "", "", ""])
            sec.setIcon(COL_NAME, node_icon("sections"))
            sec.setFlags(Qt.ItemIsEnabled)
            sec.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(sec)
            self._sec_items = {}
            self._sec_shape = None
            self._sec_state = {}
            self._sec_folder = None         # a new row: its texts to write
            for key, item in self._items.items():
                if self._groups[key].uid in expanded:
                    item.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
            self._updating = False
        self._shown_selection = ()
        self._shown_path = ()
        self.tree.verticalScrollBar().setValue(scroll)

    #: Past this many rows coming or going, all of them are made again.
    _PATCH_MAX = 2000

    def _patch_rows(self, scene, shape) -> bool:
        """Take out the rows of the groups that left and put in rows for
        the ones that came, in their places — when every other group kept
        its parent and its order (``False`` otherwise, nothing touched).
        Making all 21 406 rows again after a Delete or a Paste on the plant
        of #158 took ~0.8 s; this, the rows that changed."""
        old = self._shape
        if old is None or self._root is None:
            return False
        was = {k for k, _p in old}
        now = {k for k, _p in shape}
        gone = was - now
        came = now - was
        if len(gone) + len(came) > self._PATCH_MAX:
            return False
        if ([x for x in old if x[0] not in gone]
                != [x for x in shape if x[0] not in came]):
            return False                 # something else moved in the tree
        counts = outliner.instance_counts(scene.groups)
        opened = {id(g) for g in outliner.open_path(scene)}
        scroll = self.tree.verticalScrollBar().value()
        self._updating = True
        self.tree.blockSignals(True)
        try:
            up = dict(old)
            for key in gone:
                item = self._items.pop(key)
                self._groups.pop(key, None)
                self._state.pop(key, None)
                if up.get(key) in gone:
                    continue        # goes with its parent's row
                parent = item.parent()
                if parent is not None:
                    parent.removeChild(item)   # its own rows go with it
            if came:
                around = inherited_states(scene.groups)
                editable = Qt.ItemIsEditable
                place: dict = {}             # parent id → children so far
                for g, parent, _depth in outliner.walk(scene.groups):
                    pk = id(parent) if parent is not None else 0
                    at = place.get(pk, 0)
                    place[pk] = at + 1
                    key = id(g)
                    if key not in came:
                        continue
                    state = self._row_state(g, counts, opened,
                                            around.get(key, (None, None)))
                    item = QTreeWidgetItem([state[0], "", "", state[1],
                                            state[2], state[7], state[8],
                                            state[9]])
                    item.setData(COL_NAME, Qt.UserRole, g)
                    item.setFlags(item.flags() | editable)
                    self._paint(item, None, state)
                    (self._root if parent is None
                     else self._items[id(parent)]).insertChild(at, item)
                    self._items[key] = item
                    self._groups[key] = g
                    self._state[key] = state
            # A component that gained or lost a copy: its rows' count.
            before = getattr(self, "_counts", None) or {}
            changed = {m for m in set(before) | set(counts)
                       if before.get(m) != counts.get(m)}
            if changed:
                around = None
                for key, g in self._groups.items():
                    if key in came or id(g.mesh) not in changed:
                        continue
                    if around is None:
                        around = inherited_states(scene.groups)
                    state = self._row_state(g, counts, opened,
                                            around.get(key, (None, None)))
                    if state != self._state[key]:
                        self._paint(self._items[key], self._state[key], state)
                        self._state[key] = state
            self._counts = counts
        finally:
            self.tree.blockSignals(False)
            self._updating = False
        self.tree.verticalScrollBar().setValue(scroll)
        return True

    def _kind(self, group) -> str:
        return "ifc" if outliner.ifc_class(group) else outliner.kind(group)

    def _providers(self):
        # Read once per refresh (see refresh): asked per row, the lookup of
        # a missing attribute on the Qt window cost ~1 s on 10 000 rows.
        return self._kind_providers

    def _type_text(self, group, counts) -> str:
        custom = outliner.custom_kind(group, self._providers())
        if custom is not None:
            return custom["type"]
        cls = outliner.ifc_class(group)
        if cls:
            return cls
        kind = outliner.kind(group)
        if kind == "component":
            n = counts.get(id(group.mesh), 1)
            return (tr("Component") if n < 2
                    else tr("Component ({n} copies)", n=n))
        return {"group": tr("Group"), "image": tr("Image"),
                "text": tr("3D Text")}[kind]

    def _row_state(self, g, counts, opened, inherited=(None, None)) -> tuple:
        """Everything a row shows: ``(name, type, layer, kind, hidden,
        open, locked, material, copies, IFC class, properties, hidden by,
        locked by)`` — compared as one tuple, so an unchanged row costs no
        Qt call at all. The last two name the group around it that hides
        or locks it (``""`` when none)."""
        custom = outliner.custom_kind(g, self._providers())
        props = "\n".join(f"{k}: {v}" for k, v in custom["props"]) \
            if custom else ""
        copies = (str(counts.get(id(g.mesh), 1)) if g.is_component()
                  else "")
        return (g.name or tr("Unnamed group"),
                custom["type"] if custom else self._type_text(g, counts),
                outliner.layer_name(g), self._kind(g), bool(g.hidden),
                id(g) in opened, bool(getattr(g, "locked", False)),
                outliner.material_name(g), copies, outliner.ifc_class(g),
                props,
                (inherited[0].name or tr("Unnamed group"))
                if inherited[0] is not None else "",
                (inherited[1].name or tr("Unnamed group"))
                if inherited[1] is not None else "")

    def _paint(self, item, old, new) -> None:
        """Bring ``item`` from the ``old`` state (``None``: just made, texts
        already in) to ``new``, touching only what differs."""
        if old is not None:
            for col, i in ((COL_NAME, 0), (COL_TYPE, 1), (COL_LAYER, 2),
                           (COL_MATERIAL, 7), (COL_COPIES, 8),
                           (COL_IFC, 9)):
                if old[i] != new[i]:
                    item.setText(col, new[i])
        if old is None or old[10] != new[10]:
            item.setToolTip(COL_TYPE, new[10])
        if old is None or old[7] != new[7]:
            group = item.data(COL_NAME, Qt.UserRole)
            paint = getattr(group, "material", None)
            item.setIcon(COL_MATERIAL, _paint_icon(paint) if paint
                         else QIcon())
            item.setToolTip(COL_MATERIAL,
                            tr("Click the ▾ to choose a material"))
            item.setData(COL_MATERIAL, _GROUP_ROLE_FLAG, True)
        kind, hidden, bold = new[3], new[4], new[5]
        if old is None or old[3] != kind:
            item.setData(COL_TYPE, Qt.UserRole, kind)
            item.setIcon(COL_NAME, node_icon(kind))
        hidden_by = new[11]
        if old is None or old[4] != hidden or old[11] != hidden_by:
            item.setData(COL_EYE, Qt.UserRole, hidden)
            if hidden:
                item.setIcon(COL_EYE, node_icon("eye_off"))
                item.setToolTip(COL_EYE, "")
            elif hidden_by:
                # Hidden by the group around it: closed, faded, not its own.
                item.setIcon(COL_EYE, _faded(node_icon("eye_off")))
                item.setToolTip(COL_EYE, tr("Hidden by «{name}»",
                                            name=hidden_by))
            else:
                item.setIcon(COL_EYE, node_icon("eye"))
                item.setToolTip(COL_EYE, "")
            grey = hidden or bool(hidden_by)
            if grey or old is not None:
                item.setForeground(COL_NAME, self.tree.palette().brush(
                    QPalette.PlaceholderText if grey else QPalette.Text))
        if (old is None and bold) or (old is not None and old[5] != bold):
            font = QFont(item.font(COL_NAME))
            font.setBold(bold)
            item.setFont(COL_NAME, font)
            item.setToolTip(COL_NAME, tr("Open for editing") if bold else "")
        locked, locked_by = new[6], new[12]
        if old is None or old[6] != locked or old[12] != locked_by:
            item.setData(COL_LOCK, Qt.UserRole, locked)
            if locked:
                item.setIcon(COL_LOCK, node_icon("lock"))
                item.setToolTip(COL_LOCK, "")
            elif locked_by:
                item.setIcon(COL_LOCK, _faded(node_icon("lock")))
                item.setToolTip(COL_LOCK, tr("Locked by «{name}»",
                                             name=locked_by))
            else:
                item.setIcon(COL_LOCK, node_icon("lock_open"))
                item.setToolTip(COL_LOCK, "")

    def _update_rows(self, scene) -> None:
        counts = self._counts = outliner.instance_counts(scene.groups)
        opened = {id(g) for g in outliner.open_path(scene)}
        self._updating = True
        try:
            name = self._document_name()
            if self._root.text(COL_NAME) != name:
                self._root.setText(COL_NAME, name)
            state_of = self._state
            around = inherited_states(scene.groups)
            for key, g in self._groups.items():
                state = self._row_state(g, counts, opened,
                                        around.get(key, (None, None)))
                old = state_of[key]
                if state != old:
                    self._paint(self._items[key], old, state)
                    state_of[key] = state
        finally:
            self._updating = False

    def _update_some_rows(self, scene, keys) -> None:
        """``_update_rows`` for the rows of ``keys`` and of every copy of
        a component whose count changed."""
        counts = outliner.instance_counts(scene.groups)
        old_counts = getattr(self, "_counts", None) or {}
        moved = {m for m in set(counts) | set(old_counts)
                 if counts.get(m) != old_counts.get(m)}
        self._counts = counts
        if moved:
            keys = set(keys) | {k for k, g in self._groups.items()
                                if id(g.mesh) in moved}
        opened = {id(g) for g in outliner.open_path(scene)}
        self._updating = True
        try:
            state_of = self._state
            around = inherited_states(scene.groups)
            for key in keys:
                g = self._groups.get(key)
                if g is None:
                    continue
                state = self._row_state(g, counts, opened,
                                        around.get(key, (None, None)))
                old = state_of[key]
                if state != old:
                    self._paint(self._items[key], old, state)
                    state_of[key] = state
        finally:
            self._updating = False

    def _reveal(self, item) -> None:
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    def _sync_selection(self, scene) -> None:
        """Highlight what is selected in the view and, when that changed,
        unfold its branch and scroll it into sight; unfold the groups open
        for editing too, so the context is on screen."""
        path = tuple(id(g) for g in outliner.open_path(scene))
        if path != self._shown_path:
            for key in path:
                item = self._items.get(key)
                if item is not None:
                    self._reveal(item)
                    item.setExpanded(True)
            self._shown_path = path
        chosen = tuple(id(g) for g in scene.selection
                       if id(g) in self._items)
        if set(chosen) != set(self._shown_selection):
            self._tree_only = set()         # selected elsewhere since
        self.tree.blockSignals(True)
        try:
            wanted = set(chosen) | {k for k in self._tree_only
                                    if k in self._items}
            for key, item in self._items.items():
                if item.isSelected() != (key in wanted):
                    item.setSelected(key in wanted)
            if chosen and set(chosen) != set(self._shown_selection):
                first = self._items[chosen[0]]
                self._reveal(first)
                self.tree.setCurrentItem(first, COL_NAME,
                                         QItemSelectionModel.NoUpdate)
                self.tree.scrollToItem(first)
        finally:
            self.tree.blockSignals(False)
        self._shown_selection = chosen

    # ---- Filter --------------------------------------------------------------
    def _on_filter(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._apply_filter()
        self._update_summary()

    def _apply_filter(self) -> None:
        """Hide the rows the filter leaves out — no rebuild: a filter typed
        letter by letter over thousands of rows only flips their flag."""
        self._filter_sections()
        if not self._query:
            self._matches = len(self._items)
            for item in self._items.values():
                if item.isHidden():
                    item.setHidden(False)
            return
        scene = self._scene()
        counts = outliner.instance_counts(scene.groups)
        keep, hit = outliner.filter_keep(
            scene.groups, self._query,
            lambda g: self._type_text(g, counts))
        self._matches = len(hit)
        for key, item in self._items.items():
            item.setHidden(key not in keep)
            if key in keep and key not in hit:
                item.setExpanded(True)

    def _all_expanded(self) -> bool:
        """Whether every row that holds others is unfolded."""
        return all(item.isExpanded()
                   for item in (getattr(self, "_items", None) or {}).values()
                   if item.childCount())

    def _update_expand_button(self) -> None:
        b = getattr(self, "_expand_btn", None)
        if b is None or getattr(self, "tree", None) is None:
            return
        open_ = self._all_expanded()
        b.setIcon(node_icon("collapse_all" if open_ else "expand_all"))
        b.setToolTip(tr("Collapse all") if open_ else tr("Expand all"))

    def _expand_or_collapse(self) -> None:
        if self._all_expanded():
            self._collapse_all()
        else:
            self._expand_all()
        self._update_expand_button()

    def _expand_all(self) -> None:
        self.tree.expandAll()

    def _collapse_all(self) -> None:
        self.tree.collapseAll()
        if self._root is not None:
            self._root.setExpanded(True)

    # ---- View → model --------------------------------------------------------
    def _open_to(self, path) -> bool:
        return open_to(self._window.viewport, path)

    def _group_of(self, item):
        data = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return data if isinstance(data, Group) else None

    def _plane_of(self, item):
        data = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return data if isinstance(data, SectionPlane) else None

    # ---- Section planes ------------------------------------------------------
    _SECTION_MODE_TEXT = {
        "both": "Cut and frame", "cut": "Cut only (no frame)",
        "frame": "Frame only (no cut)", "off": "Off"}

    def _sync_sections(self, scene) -> None:
        """The «Section planes» folder: one row per plane, its mode in
        words, the eye for its frame and the slice for its cut; the folder
        row carries the two global switches (View ▸ Section Planes and
        Section Cuts)."""
        sec = self._sec_root
        if sec is None:
            return
        planes = list(getattr(scene, "section_planes", None) or ())
        shape = tuple(id(sp) for sp in planes)
        self._updating = True
        try:
            if shape != self._sec_shape:
                expanded = sec.isExpanded() or self._sec_shape is None
                sec.takeChildren()
                self._sec_items = {}
                self._sec_state = {}
                for sp in planes:
                    item = QTreeWidgetItem(["", "", "", "", ""])
                    item.setData(COL_NAME, Qt.UserRole, sp)
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    item.setIcon(COL_NAME, node_icon("sections"))
                    item.setToolTip(COL_LOCK, tr(
                        "Click: this plane cuts the model (or stops)"))
                    sec.addChild(item)
                    self._sec_items[id(sp)] = item
                self._sec_shape = shape
                sec.setExpanded(expanded)
            fill = self._fill_state(scene)
            for sp in planes:
                item = self._sec_items[id(sp)]
                mode = outliner.section_mode(sp)
                own = dict(getattr(sp, "fill", None) or {})
                state = (outliner.section_label(sp), mode, fill,
                         tuple(sorted((k, tuple(v) if k == "color" else v)
                                      for k, v in own.items())))
                if self._sec_state.get(id(sp)) == state:
                    continue
                self._sec_state[id(sp)] = state
                item.setText(COL_NAME, state[0])
                item.setText(COL_TYPE, tr(self._SECTION_MODE_TEXT[mode]))
                cut, frame = outliner.SECTION_MODES[mode]
                item.setData(COL_EYE, Qt.UserRole, not frame)
                item.setIcon(COL_EYE, node_icon("eye" if frame else "eye_off"))
                item.setToolTip(COL_EYE, tr("Hide the frame, keep the cut")
                                if frame else tr("Show the frame"))
                item.setData(COL_LOCK, Qt.UserRole, cut)
                item.setIcon(COL_LOCK, node_icon("cut" if cut else "cut_off"))
                self._paint_fill(item, cut, fill, sp)
                item.setForeground(COL_NAME, self.tree.palette().brush(
                    QPalette.PlaceholderText if mode == "off"
                    else QPalette.Text))
            # The folder: the global switches, and the count.
            shown = bool(getattr(scene, "show_section_planes", True))
            cuts = bool(getattr(scene, "show_section_cuts", True))
            folder = (tr("Section planes"), shown, cuts, len(planes), fill)
            if getattr(self, "_sec_folder", None) != folder:
                self._sec_folder = folder
                sec.setText(COL_NAME, folder[0])
                sec.setText(COL_TYPE, tr("{n} planes", n=len(planes)))
                sec.setIcon(COL_EYE, node_icon("eye" if shown else "eye_off"))
                sec.setToolTip(COL_EYE, tr(
                    "Every section plane's frame (View ▸ Section Planes)"))
                sec.setIcon(COL_LOCK, node_icon("cut" if cuts else "cut_off"))
                sec.setToolTip(COL_LOCK, tr(
                    "Section cuts in the model (View ▸ Section Cuts)"))
                self._paint_fill(sec, True, fill)
            sec.setHidden(not planes)
        finally:
            self._updating = False

    def _filter_sections(self) -> None:
        sec = self._sec_root
        if sec is None:
            return
        any_shown = False
        for i in range(sec.childCount()):
            item = sec.child(i)
            show = not self._query or self._query in item.text(
                COL_NAME).casefold()
            item.setHidden(not show)
            any_shown = any_shown or show
        sec.setHidden(sec.childCount() == 0 or not any_shown)

    _PATTERN_TEXT = {"solid": "Solid", "hatch": "Hatched 45°",
                     "cross": "Cross-hatched", "none": "No fill"}

    def set_plane_fill(self, plane, **changes) -> None:
        """Change this cut's own fill — ``pattern``, ``color``, ``spacing``;
        a value of ``None`` drops that key back to the style's. One undo
        step."""
        from core.history import SetSectionFillCommand
        fill = dict(getattr(plane, "fill", None) or {})
        for key, value in changes.items():
            if value is None:
                fill.pop(key, None)
            else:
                fill[key] = value
        if fill == (getattr(plane, "fill", None) or {}):
            return
        self._window.viewport.history.execute(
            SetSectionFillCommand(plane, fill or None))
        self._window.viewport.update()
        self.refresh()

    def pick_plane_fill_color(self, plane) -> None:
        from views.color_dialog import get_color
        from core.section import effective_fill
        _p, color, _s = effective_fill(
            plane, getattr(self._scene(), "display_style", None))
        chosen = get_color(QColor.fromRgbF(*(float(c) for c in color[:3])),
                           self, tr("Fill color of this cut"))
        if chosen.isValid():
            self.set_plane_fill(plane, color=(chosen.redF(), chosen.greenF(),
                                              chosen.blueF()))

    def ask_plane_hatch_spacing(self, plane) -> None:
        """The hatch spacing, typed as any length (5cm, 50mm, 2") — a bare
        number in the document's unit."""
        from core.section import effective_fill
        from core.units import fmt_len
        from views import prompts
        from views.viewport import _parse_length_field
        _p, _c, spacing = effective_fill(
            plane, getattr(self._scene(), "display_style", None))
        text, ok = prompts.get_text(self, tr("Hatch spacing"),
                                    tr("Distance between hatch lines:"),
                                    text=fmt_len(spacing))
        if not ok:
            return
        value = _parse_length_field(text or "")
        if value is None or value <= 0:
            self._window.viewport.flash_status(
                tr("Not a length: {text}", text=text), 3000)
            return
        self.set_plane_fill(plane, spacing=float(value))

    def _plane_fill_menu(self, menu, plane) -> None:
        """The cut's own fill: pattern, colour, spacing, or the style's."""
        from PySide6.QtCore import QTimer
        sub = menu.addMenu(tr("Fill of this cut"))
        own = getattr(plane, "fill", None) or {}
        current = own.get("pattern")
        act = sub.addAction(tr("As the style"), lambda: self.set_plane_fill(
            plane, pattern=None))
        act.setCheckable(True)
        act.setChecked(current is None)
        for pattern in ("solid", "hatch", "cross", "none"):
            act = sub.addAction(tr(self._PATTERN_TEXT[pattern]),
                                lambda p=pattern: self.set_plane_fill(
                                    plane, pattern=p))
            act.setCheckable(True)
            act.setChecked(current == pattern)
        sub.addSeparator()
        # Dialogs open once the menu has closed (see _fill_actions).
        sub.addAction(tr("Fill color of this cut…"), lambda: QTimer.singleShot(
            0, lambda: self.pick_plane_fill_color(plane)))
        if own.get("color") is not None:
            sub.addAction(tr("Use the style's fill color"),
                          lambda: self.set_plane_fill(plane, color=None))
        sub.addAction(tr("Hatch spacing…"), lambda: QTimer.singleShot(
            0, lambda: self.ask_plane_hatch_spacing(plane)))

    def rename_plane(self, plane) -> bool:
        """Name and symbol of a section plane — the dialog the Section tool
        opens on placing one, here undoable."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                                       QFormLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Name Section Plane"))
        form = QFormLayout(dlg)
        name_edit = QLineEdit(plane.name)
        sym_edit = QLineEdit(plane.symbol)
        sym_edit.setMaxLength(3)
        form.addRow(tr("Name"), name_edit)
        form.addRow(tr("Symbol"), sym_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        self._rename_dialog = dlg           # reachable from the tests
        if dlg.exec() != QDialog.Accepted:
            return False
        return self.set_plane_name(plane, name_edit.text(), sym_edit.text())

    def set_plane_name(self, plane, name: str, symbol: str) -> bool:
        from core.history import RenameSectionPlaneCommand
        name = (name or "").strip() or plane.name
        symbol = (symbol or "").strip()[:3] or plane.symbol
        if (name, symbol) == (plane.name, plane.symbol):
            return False
        self._window.viewport.history.execute(
            RenameSectionPlaneCommand(plane, name, symbol))
        self._window.viewport.update()
        self.refresh()
        return True

    @staticmethod
    def _fill_state(scene) -> tuple:
        """``(on, colour)`` of the section fill — the display style's."""
        style = getattr(scene, "display_style", None)
        return (bool(getattr(style, "section_fill", True)),
                tuple(getattr(style, "section_fill_color",
                              (0.35, 0.37, 0.41))))

    def _paint_fill(self, item, show: bool, fill, plane=None) -> None:
        """The Fill cell (Layer column): on the folder row and on the plane
        that cuts — where a fill can show — empty on the others. A plane
        shows ITS fill: its own pattern and colour over the style's."""
        on, color = fill
        item.setData(COL_LAYER, Qt.UserRole, on if show else None)
        if not show:
            item.setIcon(COL_LAYER, QIcon())
            item.setText(COL_LAYER, "")
            item.setToolTip(COL_LAYER, "")
            return
        text = tr("Fill") if on else tr("No fill")
        if plane is not None:
            from core.section import effective_fill
            pattern, color, _s = effective_fill(
                plane, getattr(self._scene(), "display_style", None))
            on = pattern != "none"
            text = tr(self._PATTERN_TEXT[pattern])
        item.setIcon(COL_LAYER, fill_icon(color, on))
        item.setText(COL_LAYER, text)
        item.setToolTip(COL_LAYER, tr(
            "Section Fill: paint the cut faces solid (click to switch; its "
            "colour from the context menu or the Styles panel)"))

    def set_section_fill(self, on: bool) -> None:
        """View ▸ Section Fill, from the browser — the menu, the toolbar
        and the Styles panel follow."""
        w = self._window
        w._set_style_field("section_fill", bool(on))
        sync = getattr(w, "_sync_style_menu", None)
        if sync is not None:
            sync()
        self.refresh()

    def pick_section_fill_color(self) -> None:
        """The Styles panel's own colour picker for the fill — same dialog,
        same hint when the fill is off."""
        panel = getattr(self._window, "styles_panel", None)
        if panel is not None:
            panel._pick_color(tr("Section fill color"), "section_fill_color")
        self.refresh()

    def _fill_actions(self, menu) -> None:
        from PySide6.QtCore import QTimer
        on = self._fill_state(self._scene())[0]
        act = menu.addAction(tr("Section Fill"),
                             lambda: self.set_section_fill(not on))
        act.setCheckable(True)
        act.setChecked(on)
        # The dialog opens once the menu has closed: a modal opened inside
        # the menu's own event loop came back without a colour.
        menu.addAction(tr("Section fill color…"), lambda: QTimer.singleShot(
            0, self.pick_section_fill_color))

    def set_section_mode(self, plane, mode: str) -> None:
        """One plane: ``"both"``, ``"cut"``, ``"frame"`` or ``"off"`` —
        one undoable step."""
        from core.history import SetSectionModeCommand
        if outliner.section_mode(plane) == mode:
            return
        cut, frame = outliner.SECTION_MODES[mode]
        self._window.viewport.history.execute(
            SetSectionModeCommand(plane, cut, frame))
        self._window.viewport.update()
        self.refresh()

    def _toggle_section(self, plane, column) -> None:
        cut, frame = outliner.SECTION_MODES[outliner.section_mode(plane)]
        if column == COL_EYE:
            frame = not frame
        else:
            cut = not cut
        mode = {v: k for k, v in outliner.SECTION_MODES.items()}[(cut, frame)]
        self.set_section_mode(plane, mode)

    def set_section_globals(self, planes=None, cuts=None) -> None:
        """The View menu's two switches, from the folder row — they stay in
        step with the menu and the toolbar."""
        w = self._window
        if planes is not None:
            w._set_section_visibility("show_section_planes", planes)
        if cuts is not None:
            w._set_section_visibility("show_section_cuts", cuts)
        sync = getattr(w, "_sync_section_menu", None)
        if sync is not None:
            sync()
        self.refresh()

    def _select_plane(self, plane) -> None:
        scene = self._scene()
        if getattr(plane, "hidden", False):
            return                          # no frame to show selected
        scene.selection.clear()
        scene.selection.add(plane)
        self._shown_selection = ()
        scene.bump_view()
        self._window.viewport.update()

    def _selected_groups(self) -> list:
        return [g for g in (self._group_of(item)
                            for item in self.tree.selectedItems())
                if g is not None]

    def _on_tree_selection(self) -> None:
        """Rows picked in the tree become the view's selection. The view
        selects inside ONE context, so the rows that count are the current
        row's siblings; the groups above them open."""
        if self._updating:
            return
        current = self.tree.currentItem()
        plane = self._plane_of(current)
        if plane is not None and current.isSelected():
            self._select_plane(plane)
            return
        group = (self._group_of(current)
                 if current is not None and current.isSelected() else None)
        if group is None:
            picked = self._selected_groups()
            if not picked:
                return
            group = picked[0]
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if path is None:
            return
        siblings = [g for g in self._selected_groups()
                    if outliner.path_to(scene.groups, g) == path]
        if not self._open_to(path):
            self._window.viewport.flash_status(tr(
                "A group around it is hidden or locked: show or unlock "
                "it to select inside"),
                3500)
            return
        picks = [g for g in siblings if scene.entity_selectable(g)]
        # What the view cannot take (hidden, locked) stays picked here.
        self._tree_only = {id(g) for g in siblings if g not in picks}
        scene.selection.clear()
        scene.selection.update(picks)
        # Clicked here, so already in sight: the refresh this triggers must
        # not scroll the tree under the pointer.
        self._shown_selection = tuple(id(g) for g in picks)
        self._shown_path = tuple(id(g) for g in outliner.open_path(scene))
        scene.bump_view()
        self._window.viewport.update()

    def material_popup(self, item):
        """The floating material panel for ``item``'s row, under its
        Material cell. Applies to the selected rows when the row is one of
        them (as the eye and the padlock do), to that row alone otherwise.
        Returns the panel (shown), or ``None`` on a row with no group."""
        group = self._group_of(item)
        if group is None:
            return None
        from tools.paint import PaintTool
        selected = self._selected_groups()
        targets = selected if group in selected else [group]

        def apply(paint) -> None:
            if paint is None:
                self.paint_groups(targets, clear=True)
            else:
                self.paint_groups(targets, material=paint)

        popup = MaterialPopup(self, self._scene(), PaintTool.recent,
                              getattr(group, "material", None), apply)
        rect = self.tree.visualItemRect(item)
        head = self.tree.header()
        rect.setLeft(head.sectionViewportPosition(COL_MATERIAL))
        popup.popup_at(self.tree.viewport().mapToGlobal(rect.bottomLeft()))
        return popup

    def _on_item_clicked(self, item, column) -> None:
        if column == COL_LAYER and item.data(COL_LAYER, Qt.UserRole) \
                is not None and (item is self._sec_root
                                 or self._plane_of(item) is not None):
            self.set_section_fill(not self._fill_state(self._scene())[0])
            return
        if column in (COL_EYE, COL_LOCK):
            plane = self._plane_of(item)
            if plane is not None:
                self._toggle_section(plane, column)
                return
            if item is self._sec_root:
                scene = self._scene()
                if column == COL_EYE:
                    self.set_section_globals(planes=not getattr(
                        scene, "show_section_planes", True))
                else:
                    self.set_section_globals(cuts=not getattr(
                        scene, "show_section_cuts", True))
                return
        group = self._group_of(item)
        if group is None or column not in (COL_EYE, COL_LOCK):
            return
        # Closed by a group around it, not by itself: that group is what
        # opens it — say so instead of setting a state of its own nobody
        # would see.
        state = self._state.get(id(group))
        if state is not None:
            own = group.hidden if column == COL_EYE \
                else getattr(group, "locked", False)
            by = state[11] if column == COL_EYE else state[12]
            if by and not own:
                self._window.viewport.flash_status(
                    tr("Hidden by «{name}»: show it first", name=by)
                    if column == COL_EYE else
                    tr("Locked by «{name}»: unlock it first", name=by), 3500)
                return
        # The eye or the padlock clicked on one of several selected rows
        # acts on all of them, as in an outliner.
        selected = self._selected_groups()
        targets = selected if group in selected else [group]
        if column == COL_EYE:
            self.toggle_hidden(targets)
        else:
            self.toggle_locked(targets)

    def _on_double_clicked(self, item, column) -> None:
        if column not in (COL_EYE, COL_LOCK):
            self.open_item(item)

    def open_item(self, item) -> None:
        """Open the row's group for editing — double-click or Enter. On a
        section plane: it cuts, or stops cutting."""
        plane = self._plane_of(item)
        if plane is not None:
            self._toggle_section(plane, COL_LOCK)
            return
        group = self._group_of(item)
        if group is None or group.hidden or getattr(group, "locked", False):
            return
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if path is None:
            return
        if self._open_to(path + [group]):
            scene.bump_view()
            self._window.viewport.update()
            self.refresh()

    def step_out(self) -> None:
        """Esc: leave the innermost open group."""
        if self._scene().edit_group is None:
            return
        self._window.viewport.end_one_group_edit()
        self._window.viewport.update()
        self.refresh()

    def toggle_hidden(self, groups=None) -> None:
        """Show the rows when any of them is hidden, hide them otherwise —
        one undoable step."""
        from core.history import HideCommand
        if groups is None:
            plane = self._plane_of(self.tree.currentItem())
            if plane is not None:
                self._toggle_section(plane, COL_EYE)
                return
            # Hiding drops the rows from the selection: the current row is
            # what a second Space shows again.
            groups = self._selected_groups()
            current = self._group_of(self.tree.currentItem())
            if not groups and current is not None:
                groups = [current]
        groups = list(groups)
        if not groups:
            return
        hide = not any(g.hidden for g in groups)
        self._window.viewport.history.execute(HideCommand(groups,
                                                          hidden=hide))
        self._keep_picked(groups)
        self._adopt_tree_only()
        self._window.viewport.update()
        self.refresh()

    def _keep_picked(self, groups) -> None:
        """Rows picked here that were just hidden or locked leave the view's
        selection, not this one: still highlighted, a second press of the
        eye or the padlock brings them back."""
        scene = self._scene()
        picked = {id(g) for g in self._selected_groups()}
        for g in groups:
            if id(g) in picked and not scene.entity_selectable(g):
                self._tree_only.add(id(g))
        self._shown_selection = tuple(
            id(g) for g in scene.selection if id(g) in self._items)

    def _adopt_tree_only(self) -> None:
        """Rows picked here while hidden or locked that the view can select
        now (shown, unlocked) join its selection: picked, then shown, they
        stay picked."""
        if not self._tree_only:
            return
        scene = self._scene()
        ready = [g for g in self._selected_groups()
                 if id(g) in self._tree_only and scene.entity_selectable(g)]
        if ready:
            scene.selection.update(ready)
            for g in ready:
                self._tree_only.discard(id(g))
            self._shown_selection = tuple(
                id(g) for g in scene.selection if id(g) in self._items)
            scene.bump_view()

    def toggle_locked(self, groups=None) -> None:
        """Unlock the rows when any of them is locked, lock them otherwise —
        one undoable step."""
        from core.history import LockCommand
        if groups is None:
            groups = self._selected_groups()
            current = self._group_of(self.tree.currentItem())
            if not groups and current is not None:
                groups = [current]
        groups = list(groups)
        if not groups:
            return
        lock = not any(getattr(g, "locked", False) for g in groups)
        if lock and any(g is self._scene().edit_group
                        or g in outliner.open_path(self._scene())
                        for g in groups):
            self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(LockCommand(groups, lock))
        self._keep_picked(groups)
        self._adopt_tree_only()
        self._window.viewport.update()
        self.refresh()

    def _update_rename_button(self) -> None:
        b = getattr(self, "_rename_btn", None)
        if b is not None:
            b.setEnabled(bool(getattr(self, "_items", None)))

    def _shown_groups(self) -> list:
        """Every row, in the tree's order — or, with a filter typed, the
        rows it matches (not the groups shown only to hold them)."""
        scene = self._scene()
        hit = None
        if self._query:
            counts = outliner.instance_counts(scene.groups)
            _keep, hit = outliner.filter_keep(
                scene.groups, self._query,
                lambda g: self._type_text(g, counts))
        return [g for g, _p, _d in outliner.walk(scene.groups)
                if id(g) in self._items and (hit is None or id(g) in hit)]

    def _rename_picked(self) -> None:
        """The pencil button: the selected rows renamed — several at once in
        the Rename selected window, one in its cell; with nothing selected,
        every row the tree shows (all, or what the filter keeps)."""
        picked = self._selected_groups()
        if not picked:
            # Nothing selected: every row on show (what the filter keeps).
            picked = self._shown_groups()
        if len(picked) > 1:
            self.ask_batch_rename(picked)
            return
        item = self.tree.currentItem()
        if picked and self._group_of(item) is not picked[0]:
            item = self._items.get(id(picked[0]))
        if item is not None and self._group_of(item) is not None:
            self.tree.setFocus()
            self.tree.editItem(item, COL_NAME)

    def ask_batch_rename(self, groups) -> bool:
        """The Rename selected window for ``groups`` (in the tree's order);
        what it gives is applied as one undo step. Whether anything was
        renamed."""
        order = {id(g): i for i, (g, _p, _d) in
                 enumerate(outliner.walk(self._scene().groups))}
        groups = sorted((g for g in groups if g is not None),
                        key=lambda g: order.get(id(g), 0))
        if len(groups) < 2:
            return False
        dlg = BatchRenameDialog([g.name or "" for g in groups], self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False
        return self.batch_rename(groups, dlg.names())

    def batch_rename(self, groups, names) -> bool:
        """Give ``groups`` the ``names`` — one undo step, the rows whose
        name does not change left out."""
        from core.history import CompoundCommand, RenameGroupCommand
        cmds = [RenameGroupCommand(g, n) for g, n in zip(groups, names)
                if n.strip() and n != g.name]
        if not cmds:
            return False
        self._window.viewport.history.execute(CompoundCommand(cmds))
        self._window.viewport.update()
        self.refresh()
        return True

    def inside_component_refusal(self, groups) -> str:
        """Why rows inside a component cannot change what they are: its
        parts are what every copy shares — ``""`` for rows that may."""
        scene = self._scene()
        for g in groups:
            path = outliner.path_to(scene.groups, g)
            if path and outliner.in_component(scene.groups, path[-1]):
                return tr("Components keep their parts: Make Unique first "
                          "to change what is inside one")
        return ""

    def make_unique_rows(self, groups) -> bool:
        """Make Unique on the component rows — each a group of its own with
        a name of its own («Silla #2», #620) — as ONE undo step (from the
        view, each copy was a step). Whether anything changed."""
        from core.history import CompoundCommand, MakeUniqueCommand
        comps = [g for g in groups if g is not None and g.is_component()]
        if not comps:
            return False
        why = self.inside_component_refusal(comps)
        if why:
            self._window.viewport.flash_status(why, 5000)
            return False
        self._window.viewport.history.execute(CompoundCommand(
            [MakeUniqueCommand(g, rename=True) for g in comps]))
        self._window.viewport.update()
        self.refresh()
        return True

    def copies_of_rows(self, groups) -> list:
        """Every copy of the components among ``groups`` — nested ones too,
        each definition once — in the tree's order."""
        meshes = {id(g.mesh) for g in groups if g is not None
                  and g.is_component()}
        out, seen = [], set()
        for g, _p, _d in outliner.walk(self._scene().groups):
            if g.is_component() and id(g.mesh) in meshes                     and id(g) not in seen:
                seen.add(id(g))
                out.append(g)
        return out

    def select_copies(self, groups) -> None:
        """Select Instances: every copy of the rows' components, selected in
        the view — the group holding most of them opened when they sit in
        several, and the status bar says how many are elsewhere (the
        «In model» list's way)."""
        copies = self.copies_of_rows(groups)
        if not copies:
            return
        tray = getattr(self._window, "tray", None)
        panel = getattr(tray, "components", None)
        if panel is not None and hasattr(panel, "_select_groups"):
            panel._select_groups(copies)
        else:
            scene = self._scene()
            scene.selection.clear()
            scene.selection.update(c for c in copies
                                   if scene.entity_selectable(c))
            scene.bump_view()
        self._window.viewport.update()
        self.refresh()

    def make_refusal(self, groups) -> str:
        """Why the rows cannot be grouped or made a component — ``""`` when
        they can. Locked or hidden rows cannot be selected, rows from
        different groups are not selected together, and what is inside a
        component is shared by all its copies."""
        scene = self._scene()
        groups = [g for g in groups if g is not None]
        if any(not scene.entity_selectable(g)
               or outliner.locked_on_path(scene.groups, g) for g in groups):
            return tr("Locked or hidden rows cannot be grouped: unlock or "
                      "show them first")
        paths = {tuple(id(p) for p in (outliner.path_to(scene.groups, g)
                                       or ())) for g in groups}
        if len(paths) > 1:
            return tr("Choose rows inside the same group to group them")
        # Rows inside a component: its parts are what every copy shares.
        path = outliner.path_to(scene.groups, groups[0]) if groups else None
        if path and outliner.in_component(scene.groups, path[-1]):
            return tr("Components keep their parts: Make Unique first to "
                      "change what is inside one")
        return ""

    def make_from_rows(self, groups, kind: str) -> None:
        """Make Group (``kind="group"``), Make Component or Explode
        (``kind="explode"``) of the rows: the
        view opens where they sit and selects them — rows from one group
        only, as the view selects in one place — and the window's own
        command runs, so it asks, answers and undoes as from the view."""
        scene = self._scene()
        groups = [g for g in groups if g is not None]
        if not groups:
            return
        why = self.make_refusal(groups)
        if why:
            self._window.viewport.flash_status(why, 5000)
            return
        path = outliner.path_to(scene.groups, groups[0])
        if path is None:
            return
        siblings = [g for g in groups
                    if outliner.path_to(scene.groups, g) == path]
        if not self._open_to(path):
            self._window.viewport.flash_status(tr(
                "A group around it is hidden or locked: show or unlock "
                "it to select inside"), 3500)
            return
        scene.selection.clear()
        scene.selection.update(g for g in siblings
                               if scene.entity_selectable(g))
        if kind == "group":
            self._window._on_make_group()
        elif kind == "explode":
            # Every row at once, one undo step; inside an open group what
            # comes out stays in it (the window's Explode, row by row,
            # made a step per group).
            from core.history import CompoundCommand, ExplodeGroupCommand
            if self._window._can_make_here():
                self._window._execute_make(CompoundCommand(
                    [ExplodeGroupCommand(g) for g in siblings]))
        else:
            self._window._on_make_component()
        self._window.viewport.update()
        self.refresh()

    _REPARENT_REFUSED = {
        "cycle": "A group cannot go inside itself or a group it holds",
        "component": "Components keep their parts: Make Unique first to "
                     "change what is inside one",
        "locked": "Unlock it first",
    }

    def reparent(self, groups, target) -> bool:
        """Put ``groups`` into ``target`` (``None``: the model) — one
        undoable step, nothing moves in the world."""
        from core.history import ReparentGroupsCommand
        scene = self._scene()
        moving = outliner.needs_moving(scene.groups, groups, target)
        if not moving:
            return False
        problem = outliner.reparent_problem(scene.groups, moving, target)
        if problem is not None:
            self._window.viewport.flash_status(
                tr(self._REPARENT_REFUSED[problem]), 4000)
            return False
        # The tools work on what is open: re-nesting under them is not
        # safe, and the view closes them as a click outside would.
        self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(
            ReparentGroupsCommand(moving, target))
        self._window.viewport.update()
        self.refresh()
        if target is not None:
            self._items[id(target)].setExpanded(True)
        first = self._items.get(id(moving[0]))
        if first is not None:
            self._reveal(first)
            self.tree.setCurrentItem(first, COL_NAME,
                                     QItemSelectionModel.NoUpdate)
            self.tree.scrollToItem(first)
        return True

    def indent(self) -> None:
        """Tab: into the group just above, at the same level."""
        current = self.tree.currentItem()
        group = self._group_of(current)
        if group is None:
            return
        parent = current.parent()
        index = parent.indexOfChild(current) if parent is not None else -1
        above = None
        while index > 0:
            index -= 1
            candidate = parent.child(index)
            if not candidate.isHidden():
                above = self._group_of(candidate)
                break
        if above is None:
            return
        self.reparent(self._selected_groups() or [group], above)

    def outdent(self) -> None:
        """Shift+Tab: out of the group it is in, one level up."""
        group = self._group_of(self.tree.currentItem())
        if group is None:
            return
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if not path:
            return
        self.reparent(self._selected_groups() or [group],
                      path[-2] if len(path) > 1 else None)

    # ---- Columns ---------------------------------------------------------
    #: Columns of a fixed width: the eye and the padlock.
    _FIXED = (COL_EYE, COL_LOCK)

    #: The step, in pixels, from one level of nesting to the next.
    INDENT = 12

    #: The factory order, left to right: the eye and the padlock first.
    COLUMN_ORDER = (COL_EYE, COL_LOCK, COL_NAME, COL_TYPE, COL_LAYER,
                    COL_MATERIAL, COL_COPIES, COL_IFC)
    #: The factory widths.
    COLUMN_WIDTHS = {COL_NAME: 200, COL_EYE: 26, COL_LOCK: 26,
                     COL_TYPE: 110, COL_LAYER: 80, COL_MATERIAL: 100,
                     COL_COPIES: 60, COL_IFC: 110}

    def _column_order(self) -> list:
        """The order the user left the columns in, or the factory one."""
        from PySide6.QtCore import QSettings
        raw = QSettings().value("browser/model_column_order")
        if isinstance(raw, str):
            raw = raw.split(",")
        try:
            order = [int(x) for x in raw or ()]
        except (TypeError, ValueError):
            order = []
        if sorted(order) != sorted(self.COLUMN_ORDER):
            return list(self.COLUMN_ORDER)
        return order

    def _apply_column_order(self, order=None) -> None:
        head = self.tree.header()
        head.blockSignals(True)
        try:
            for visual, col in enumerate(order or self._column_order()):
                head.moveSection(head.visualIndex(col), visual)
        finally:
            head.blockSignals(False)

    def _save_column_order(self, *_args) -> None:
        from PySide6.QtCore import QSettings
        head = self.tree.header()
        order = sorted(range(head.count()), key=head.visualIndex)
        QSettings().setValue("browser/model_column_order",
                             ",".join(str(c) for c in order))

    def reset_columns(self) -> None:
        """Window ▸ Panels ▸ Restore default panels, for the Browser: the
        factory order (the eye and the padlock first), the factory columns
        shown and their widths; the choices remembered are forgotten."""
        from PySide6.QtCore import QSettings
        st = QSettings()
        for key in ("browser/model_column_order",
                    "browser/model_hidden_columns", "browser/model_columns"):
            st.remove(key)
        # Following the panel from here on — before the columns move or
        # hide, or the header's saver keeps the widths being dropped.
        self._auto_fit = True
        self._apply_column_order(self.COLUMN_ORDER)
        self._apply_column_choice()
        for col, width in self.COLUMN_WIDTHS.items():
            self._set_width(col, width)
        self._widths_before = None
        self._fit_columns()
        self.tree.horizontalScrollBar().setValue(0)

    def _set_width(self, col: int, width: int) -> None:
        """Resize a column as the program, not the user: not remembered,
        and it does not stop the columns following the panel."""
        self._fitting = True
        try:
            self.tree.header().resizeSection(col, int(width))
        finally:
            self._fitting = False

    def eventFilter(self, obj, ev) -> bool:
        from PySide6.QtCore import QEvent
        if obj is self.tree.header() and ev.type() in (QEvent.Resize,
                                                       QEvent.Show):
            self._place_columns_button()
        if obj is self.tree.header().viewport():
            if ev.type() == QEvent.MouseButtonPress:
                self._header_pressed = True
            elif ev.type() == QEvent.MouseButtonRelease:
                self._header_pressed = False
        return super().eventFilter(obj, ev)

    def _on_section_resized(self, col, old, new) -> None:
        """A column edge dragged by the user: from now on the columns keep
        the widths given them. Only with the mouse down on the header — not
        what Qt does on its own — and not one being shown or hidden."""
        self._place_columns_button()        # it follows its column
        if (self._fitting or not self._header_pressed or not old
                or not new):
            return
        head = self.tree.header()
        getattr(self, "_grown", {}).pop(col, None)   # the user's width now
        if self._auto_fit:
            self._auto_fit = False
            # The widths are the user's now: kept from this drag on (the
            # header's own saver ran before this, while they were not).
            from PySide6.QtCore import QSettings
            QSettings().setValue("browser/model_columns", ",".join(
                str(head.sectionSize(c)) for c in (COL_NAME, COL_TYPE)))

    #: Who gives up room, and down to how much, when the columns do not fit.
    #: Name stops at ``_name_floor``: below it the tree's indent and icons
    #: leave no room for the name itself and the rows read as nothing — a
    #: short scroll bar is the lesser evil.
    _FIT_STEPS = ((COL_TYPE, 80), (COL_IFC, 70), (COL_MATERIAL, 70),
                  (COL_NAME, None), (COL_LAYER, 60), (COL_COPIES, 45),
                  (COL_TYPE, 45), (COL_LAYER, 45), (COL_MATERIAL, 45),
                  (COL_IFC, 45), (COL_COPIES, 35))

    def _name_floor(self) -> int:
        """The narrowest the Name column may get: the indent of the
        document row and of a top-level group, the icon, and some ten
        characters of the name."""
        icon = self.tree.iconSize().width()
        return max(110, self.tree.indentation() * 2
                   + (icon if icon > 0 else 16) + 84)

    def _fit_columns(self) -> None:
        """Every column shown shares the panel's width, without a scroll
        bar — Material, Copies and IFC class too, as they are turned on.
        They give up room in ``_FIT_STEPS`` order: first what reads well
        shorter (Type, IFC class, Material), then Name, then all of them
        down to a last floor, where a long text ends in «…». Only while
        the user has not sized the columns by hand."""
        if not self._auto_fit:
            return
        self._grown = {}                    # starting over from the defaults
        head = self.tree.header()
        room = self.tree.viewport().width()
        if room <= 0:
            return
        shown = [c for c in range(head.count()) if not head.isSectionHidden(c)]
        # The one that takes what room is left: the last.
        last = max(shown, key=head.visualIndex)
        # The eye and the padlock are fixed: their real size (the style's
        # minimum section can be wider than the 26 px asked).
        widths = {c: (head.sectionSize(c) if c in self._FIXED
                      else self.COLUMN_WIDTHS.get(c, head.sectionSize(c)))
                  for c in shown}
        over = sum(widths.values()) - room
        for c, floor in self._FIT_STEPS:
            if over <= 0:
                break
            if floor is None:
                floor = self._name_floor()
            # Qt never draws a section narrower than the style's minimum:
            # a floor below it is room counted that never comes.
            floor = max(floor, head.minimumSectionSize())
            if c in widths:
                give = min(over, max(0, widths[c] - floor))
                widths[c] -= give
                over -= give
        # Still over: the floors above assume the eye and the padlock take
        # 26 px, and a style whose narrowest section is wider (38 px with
        # Fusion here) leaves 13 px of scroll bar with every column on —
        # the short columns go down to 40 px, still a readable «…».
        if over > 0:
            least = max(head.minimumSectionSize(), 40)
            for c in (COL_COPIES, COL_TYPE, COL_LAYER, COL_MATERIAL, COL_IFC):
                if over <= 0:
                    break
                if c in widths:
                    give = min(over, max(0, widths[c] - least))
                    widths[c] -= give
                    over -= give
        # The last one too: the header stretches it over any room left,
        # but never below the width it was given.
        for c, width in widths.items():
            if c in self._FIXED:
                continue
            if c == last:
                width = max(width, room - sum(
                    w for k, w in widths.items() if k != last))
            if head.sectionSize(c) != width:
                self._set_width(c, width)
        self._grow_columns()

    #: How wide a column may grow to show its contents whole.
    _GROW_CAP = {COL_NAME: 340, COL_TYPE: 170, COL_LAYER: 160,
                 COL_MATERIAL: 180, COL_COPIES: 70, COL_IFC: 170}

    def _wanted_width(self, col: int) -> int:
        """What ``col`` needs to show its title and the rows on screen
        whole (the Name column with their indent), up to ``_GROW_CAP``."""
        head = self.tree.header()
        want = max(self.tree.sizeHintForColumn(col),
                   head.sectionSizeFromContents(col).width()) + 6
        if col == COL_MATERIAL:
            want += _MaterialCellDelegate.ARROW    # the ▾ beside the name
        return min(want, self._GROW_CAP.get(col, want))

    def _grow_columns(self) -> None:
        """Room to spare — the panel made wider — goes to the columns cut
        short, Name first, each up to what shows its contents whole; the
        last column keeps the rest. Columns already whole are left as they
        are, sized by hand or not. Programme widths: not remembered.

        What was grown is remembered (``_grown``: the width before) and
        given back first each time, so a panel made narrow again returns
        the columns to the user's widths instead of keeping the growth."""
        head = self.tree.header()
        grown = getattr(self, "_grown", None) or {}
        for c, base in grown.items():
            if not head.isSectionHidden(c) and head.sectionSize(c) != base:
                self._set_width(c, base)
        self._grown = {}
        room = self.tree.viewport().width()
        shown = [c for c in range(head.count()) if not head.isSectionHidden(c)]
        if room <= 0 or len(shown) < 2:
            return
        last = max(shown, key=head.visualIndex)
        others = [c for c in shown if c != last]
        floor_last = self._MIN_WIDTH.get(last, 60)
        free = room - sum(head.sectionSize(c) for c in others) - floor_last
        for c in (COL_NAME, COL_TYPE, COL_LAYER, COL_MATERIAL, COL_COPIES,
                  COL_IFC):
            if free <= 0:
                break
            if c not in others or c in self._FIXED:
                continue
            size = head.sectionSize(c)
            grow = min(free, max(0, self._wanted_width(c) - size))
            if grow:
                self._grown[c] = size
                self._set_width(c, size + grow)
                free -= grow
        # The last column: what is left (the header only ever stretches it
        # wider, so a narrower share is set here).
        rest = room - sum(head.sectionSize(c) for c in others)
        if last not in self._FIXED and rest >= floor_last \
                and head.sectionSize(last) != rest:
            self._set_width(last, rest)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if not getattr(self, "_fit_queued", False):
            from PySide6.QtCore import QTimer
            self._fit_queued = True

            def fit() -> None:
                self._fit_queued = False
                if self._auto_fit:
                    self._fit_columns()     # shares, then grows
                else:
                    self._grow_columns()    # the user's widths, cut ones grown
            QTimer.singleShot(0, fit)

    def _hidden_columns(self) -> set:
        from PySide6.QtCore import QSettings
        raw = QSettings().value("browser/model_hidden_columns")
        if raw is None:
            return {c for c, _l, shown in OPTIONAL_COLUMNS if not shown}
        if isinstance(raw, str):
            raw = [x for x in raw.split(",") if x]
        out = set()
        for x in raw or ():
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                pass
        return out

    def _apply_column_choice(self) -> None:
        hidden = self._hidden_columns()
        for col, _label, _shown in OPTIONAL_COLUMNS:
            self.tree.setColumnHidden(col, col in hidden)

    def set_column_shown(self, col: int, shown: bool) -> None:
        from PySide6.QtCore import QSettings
        hidden = self._hidden_columns()
        (hidden.discard if shown else hidden.add)(col)
        QSettings().setValue("browser/model_hidden_columns",
                             ",".join(str(c) for c in sorted(hidden)) or ",")
        self._apply_column_choice()
        self._place_columns_button()
        if self._auto_fit:
            # Following the panel: every column shown shares it.
            self._fit_columns()
            self._scroll_to_column(col if shown else COL_NAME)
        elif shown:
            self._make_room_for(col)
        else:
            self._give_room_back()

    #: How narrow each column may get to make room for another one.
    _MIN_WIDTH = {COL_NAME: 110, COL_TYPE: 70, COL_LAYER: 60,
                  COL_MATERIAL: 70, COL_COPIES: 45, COL_IFC: 70}
    #: The optional columns, which the others make room for.
    _EXTRA = (COL_MATERIAL, COL_COPIES, COL_IFC)

    def _make_room_for(self, col: int) -> None:
        """A column turned on lands past the right edge of a sidebar-wide
        panel: Name, Type and Layer already fill it, so Material, Copies and
        IFC class seemed not to appear at all. The Name column gives up
        room first, then the others down to a readable width, and the view
        scrolls to the new column if it still does not fit. The widths
        before the first such squeeze are kept, to give back."""
        head = self.tree.header()
        room = self.tree.viewport().width()
        if room <= 0:
            return
        shown = [c for c in range(head.count()) if not head.isSectionHidden(c)]
        if getattr(self, "_widths_before", None) is None:
            self._widths_before = {c: head.sectionSize(c)
                                   for c in (COL_NAME, COL_TYPE, COL_LAYER)}
        over = sum(head.sectionSize(c) for c in shown) - room
        for c in (COL_NAME, COL_TYPE, COL_LAYER) + self._EXTRA:
            if over <= 0:
                break
            if c not in shown or c == col:
                continue
            size = head.sectionSize(c)
            give = min(over, max(0, size - self._MIN_WIDTH[c]))
            if give:
                self._set_width(c, size - give)
                over -= give
        self._scroll_to_column(col)

    def _scroll_to_column(self, col: int) -> None:
        """Bring ``col`` into view once the tree has laid the new widths
        out (the scroll bar's range is stale until then)."""
        from PySide6.QtCore import QTimer

        def go() -> None:
            head = self.tree.header()
            bar = self.tree.horizontalScrollBar()
            room = self.tree.viewport().width()
            left = head.sectionViewportPosition(col)
            right = left + head.sectionSize(col)
            if col == COL_NAME:
                bar.setValue(0)         # the names, with the eye before
            elif left < 0:
                bar.setValue(max(0, bar.value() + left))
            elif right > room:
                bar.setValue(min(bar.maximum(),
                                 bar.value() + min(left, right - room)))
        self.tree.updateGeometries()
        go()
        QTimer.singleShot(0, go)

    def _give_room_back(self) -> None:
        """A column turned off: with none of the optional ones left, the
        others go back to the widths they had before making room; with some
        left, the room freed goes to Name first, up to that width. The last
        column shown is left out of the sums: the header stretches it over
        whatever is left, so its size says nothing about the room there is."""
        head = self.tree.header()
        before = getattr(self, "_widths_before", None) or {}
        shown = [c for c in range(head.count()) if not head.isSectionHidden(c)]
        if not any(c in shown for c in self._EXTRA):
            for c, width in before.items():
                self._set_width(c, width)
            self._widths_before = None
        elif shown:
            room = self.tree.viewport().width()
            last = max(shown, key=head.visualIndex)
            free = room - sum(head.sectionSize(c) for c in shown
                              if c != last) - self._MIN_WIDTH.get(last, 0)
            for c in (COL_NAME, COL_TYPE, COL_LAYER):
                if free <= 0:
                    break
                if c not in shown or c == last:
                    continue
                size = head.sectionSize(c)
                grow = min(free, max(0, before.get(c, size) - size))
                if grow:
                    self._set_width(c, size + grow)
                    free -= grow
        self._scroll_to_column(COL_NAME)

    def _columns_menu(self):
        """Which columns show: the header's right-click and its button."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        hidden = self._hidden_columns()
        for col, label, _shown in OPTIONAL_COLUMNS:
            act = menu.addAction(tr(label), lambda c=col, on=col in hidden:
                                 self.set_column_shown(c, on))
            act.setCheckable(True)
            act.setChecked(col not in hidden)
        return menu

    def _on_header_menu(self, pos) -> None:
        self._columns_menu().exec(self.tree.header().mapToGlobal(pos))

    def _on_columns_button(self) -> None:
        b = self._columns_button
        self._columns_menu().exec(b.mapToGlobal(b.rect().bottomLeft()))

    def _place_columns_button(self) -> None:
        """At the header's right end, as tall as the header; its text says
        how many columns are left to turn on («+3»), or «⋮» when none."""
        b = getattr(self, "_columns_button", None)
        if b is None:
            return
        head = self.tree.header()
        n = len(self._hidden_columns())
        b.setText(f"+{n}" if n else "⋮")
        font = b.font()
        font.setBold(bool(n))               # more to turn on: say it
        b.setFont(font)
        side = max(head.height(), 18)
        width = max(side, b.sizeHint().width())
        tree = self.tree
        if tree.button_strip != width:
            tree.button_strip = width       # the strip it stands in
            tree.updateGeometries()
        # In the strip right of the header: fixed, whatever the columns do.
        g = head.geometry()
        b.setGeometry(g.right() + 1, g.top(), width, g.height())
        b.raise_()

    # ---- Several rows at once --------------------------------------------
    def assign_layer(self, groups, layer: str) -> None:
        """Put the rows on ``layer`` (made if new) — one undo step."""
        from core.history import AssignLayerCommand
        groups = [g for g in groups if g is not None]
        if not groups or not layer:
            return
        self._window.viewport.history.execute(
            AssignLayerCommand(groups, layer))
        self._window.viewport.update()
        self.refresh()

    def _ask_new_layer(self, groups) -> None:
        from views import prompts
        name, ok = prompts.get_text(self, tr("New layer"),
                                    tr("Layer name:"))
        if ok and name.strip():
            self.assign_layer(groups, name.strip())

    def paint_groups(self, groups, material=None, clear=False) -> None:
        """Paint the rows as a whole with ``material`` (the Paint tool's
        current one by default), or take their paint off — the same as
        painting a group from outside it; one undo step."""
        from core.history import (CompoundCommand, SetFaceMaterialTagCommand,
                                  SetGroupMaterialCommand)
        groups = [g for g in groups if g is not None]
        if not groups:
            return
        if clear:
            cmds = [SetGroupMaterialCommand(g, None) for g in groups]
        else:
            from tools.paint import PaintTool
            if material is None:
                if PaintTool.current_is_default:
                    cmds = [SetGroupMaterialCommand(g, None) for g in groups]
                else:
                    mat = PaintTool.current_material
                    material = PaintTool._current_as_material()
                    cmds = [SetFaceMaterialTagCommand(
                        [], mat.name if mat is not None else None, mat)]
                    cmds += [SetGroupMaterialCommand(g, material)
                             for g in groups]
            else:
                cmds = [SetGroupMaterialCommand(g, material) for g in groups]
                # A named paint the document does not know yet (a recent
                # one): registered in the same step, as the Paint tool does.
                name = material.get("mat")
                if name and name not in self._scene().materials:
                    from core.materials import Material
                    col = material.get("color")
                    cmds.insert(0, SetFaceMaterialTagCommand([], name, Material(
                        name, color=tuple(col) if col else None,
                        texture=material.get("texture"),
                        opacity=material.get("opacity"))))
        self._window.viewport.history.execute(CompoundCommand(cmds))
        self._window.viewport.update()
        self.refresh()

    def _batch_menu(self, menu, targets) -> None:
        layers = menu.addMenu(tr("Layer"))
        current = {outliner.layer_name(g) for g in targets}
        for ly in self._scene().layers:
            act = layers.addAction(ly.name, lambda n=ly.name:
                                   self.assign_layer(targets, n))
            act.setCheckable(True)
            act.setChecked(current == {ly.name})
        layers.addSeparator()
        from PySide6.QtCore import QTimer
        layers.addAction(tr("New layer…"), lambda: QTimer.singleShot(
            0, lambda: self._ask_new_layer(targets)))
        menu.addAction(tr("Paint with the active material"),
                       lambda: self.paint_groups(targets))
        # Any material of the document, or a recent paint, without going to
        # the Materials tab (#565, @fafecm).
        from tools.paint import PaintTool
        choices = outliner.material_choices(self._scene(), PaintTool.recent)
        if choices:
            mats = menu.addMenu(tr("Material"))
            current = {repr(getattr(g, "material", None)) for g in targets}
            for label, paint in choices:
                act = mats.addAction(_paint_icon(paint), label,
                                     lambda p=paint: self.paint_groups(
                                         targets, material=p))
                act.setCheckable(True)
                act.setChecked(current == {repr(paint)})
        if any(getattr(g, "material", None) for g in targets):
            menu.addAction(tr("Remove paint"),
                           lambda: self.paint_groups(targets, clear=True))

    # ---- A plan of a group -------------------------------------------------
    def create_plan(self, group, cut_height: float, sheet: bool = True,
                    scale: float = 100.0, open_sheet: bool = False):
        """A floor plan of ``group``: a horizontal cut ``cut_height`` above
        its base (made the active cut), a scene looking straight down on it
        in parallel projection, and — with ``sheet`` — a new sheet with
        that scene at 1:``scale``. One undo step. Returns the scene, or
        ``None`` when the group holds no geometry."""
        import math
        from PySide6.QtGui import QVector3D
        from core.camera import OrbitCamera
        from core.section import SectionPlane as _Plane
        from core.section import next_symbol
        scene = self._scene()
        bounds = outliner.world_bounds(scene.groups, group)
        if bounds is None:
            self._window.viewport.flash_status(
                tr("«{name}» holds no geometry to make a plan of",
                   name=group.name), 3500)
            return None
        (x0, y0, z0), (x1, y1, z1) = bounds
        z = z0 + float(cut_height)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        title = outliner.unique_name(
            tr("Plan {name}", name=group.name),
            [v.name for v in scene.saved_views])
        plane = _Plane(QVector3D(cx, cy, z), QVector3D(0, 0, 1),
                       name=title, symbol=next_symbol(scene.section_planes))
        cam = OrbitCamera()
        cam.target = QVector3D(cx, cy, z)
        cam.set_view("top")
        cam.perspective = False
        span = max(x1 - x0, y1 - y0, 1.0)
        cam.distance = span * 1.2 / (2 * math.tan(math.radians(
            cam.fov_deg) / 2))
        view = self._place_view(title, cam, plane, True, sheet, scale,
                                open_sheet)
        if z > z1 or z < z0:
            self._window.viewport.flash_status(tr(
                "The cut is outside «{name}»: the plan shows it whole",
                name=group.name), 4000)
        return view

    def _place_view(self, title, cam, plane, add_plane, sheet, scale,
                    open_sheet):
        """The part a plan of a group and a view of a cut share: the scene
        from ``cam`` cut by ``plane``, a sheet with it if asked — one undo
        step — and then the way to it: the sheet opened, or Sheets 2D with
        the scene marked, and the status bar saying what was made."""
        from core.composition import Composicion
        from core.history import CreatePlanCommand
        from core.saved_views import SavedView
        scene = self._scene()
        view = SavedView.capture(title, scene, cam)
        view.section = {"active": plane.uid, "planes_shown": False,
                        "cuts_shown": True}
        page = None
        if sheet:
            page = Composicion(name=outliner.unique_name(
                title, [c.name for c in scene.compositions]), paper="A3")
            frame = page.default_frame()
            frame.view_key = f"scene:{title}"
            frame.scale_n = float(scale)
            frame.show_title = True
            page.frames.append(frame)
        self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(
            CreatePlanCommand(plane, view, page, add_plane=add_plane))
        self._window.tray.scenes.refresh()
        self._window._refresh_sheet_tabs()
        self._window.viewport.update()
        self.refresh()
        what = (tr("«{name}»: a scene and a sheet — in the composer",
                   name=title) if page is not None
                else tr("«{name}»: a scene — drag it onto a sheet in the "
                        "composer", name=title))
        self._window.viewport.flash_status(what, 6000)
        if page is not None and open_sheet:
            self._window._show_sheet(
                self._scene().compositions.index(page))
        composer = getattr(self._window, "_composer", None)
        if composer is not None:
            composer.views_panel.show_scene_row(title)
        return view

    def create_cut_view(self, plane, sheet: bool = True,
                        scale: float = 50.0, open_sheet: bool = False):
        """A view of an existing section plane: looking at the cut face on
        (from the side the plane takes away, towards what stays), in
        parallel projection, the plane made the active cut — a section for
        a vertical plane, a plan for a horizontal one. With ``sheet``, on a
        new sheet at 1:``scale``. One undo step; returns the scene."""
        import math
        from PySide6.QtGui import QVector3D
        from core.camera import OrbitCamera
        scene = self._scene()
        lo, hi = scene.bounds()
        n = QVector3D(plane.normal).normalized()
        if lo is None:
            centre, span = QVector3D(plane.point), 10.0
        else:
            centre = (lo + hi) * 0.5
            size = hi - lo
            span = max(size.x(), size.y(), size.z(), 1.0)
        # The target on the plane, facing the model's middle.
        target = centre - n * QVector3D.dotProduct(centre - plane.point, n)
        cam = OrbitCamera()
        cam.target = target
        cam.yaw = math.atan2(n.y(), n.x())
        cam.pitch = math.asin(max(-1.0, min(1.0, n.z())))
        cam.perspective = False
        cam.distance = span * 1.2 / (2 * math.tan(math.radians(
            cam.fov_deg) / 2))
        base = plane.name or tr("Section {symbol}", symbol=plane.symbol)
        title = outliner.unique_name(base, [v.name for v in scene.saved_views])
        return self._place_view(title, cam, plane, False, sheet, scale,
                                open_sheet)

    def ask_cut_view(self, plane) -> None:
        """The dialog for a view of a cut: a sheet or not, its scale, and
        whether to open it."""
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QFormLayout)
        from core.composition import format_scale, parse_scale
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("View of the cut {name}",
                              name=outliner.section_label(plane)))
        form = QFormLayout(dlg)
        on_sheet = QCheckBox(tr("Also place it on a new sheet"))
        on_sheet.setChecked(True)
        form.addRow("", on_sheet)
        scale = QLineEdit(format_scale(50.0))
        form.addRow(tr("Scale:"), scale)
        open_it = QCheckBox(tr("Open the sheet when done"))
        open_it.setChecked(True)
        form.addRow("", open_it)
        on_sheet.toggled.connect(scale.setEnabled)
        on_sheet.toggled.connect(open_it.setEnabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        self._cut_view_dialog = dlg         # reachable from the tests
        if dlg.exec() != QDialog.Accepted:
            return
        self.create_cut_view(plane, on_sheet.isChecked(),
                             parse_scale(scale.text(), 50.0),
                             open_sheet=open_it.isChecked())

    def ask_scale(self, group) -> None:
        self._window._on_scale_dialog(group)
        self.refresh()

    def ask_plan(self, group) -> None:
        """The dialog: cut height above the group's base, a sheet or not,
        and its scale."""
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QFormLayout)
        from core.composition import format_scale, parse_scale
        from core.units import fmt_len
        from views.viewport import _parse_length_field
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Plan of {name}", name=group.name))
        form = QFormLayout(dlg)
        height = QLineEdit(fmt_len(1.2))
        height.setToolTip(tr("Measured up from the lowest point of the "
                             "group — 1.20 m cuts through the windows"))
        form.addRow(tr("Cut height:"), height)
        on_sheet = QCheckBox(tr("Also place it on a new sheet"))
        on_sheet.setChecked(True)
        form.addRow("", on_sheet)
        scale = QLineEdit(format_scale(100.0))
        form.addRow(tr("Scale:"), scale)
        open_it = QCheckBox(tr("Open the sheet when done"))
        open_it.setChecked(True)
        form.addRow("", open_it)
        on_sheet.toggled.connect(scale.setEnabled)
        on_sheet.toggled.connect(open_it.setEnabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        self._plan_dialog = dlg             # reachable from the tests
        if dlg.exec() != QDialog.Accepted:
            return
        cut = _parse_length_field(height.text() or "")
        if cut is None:
            self._window.viewport.flash_status(
                tr("Not a length: {text}", text=height.text()), 3000)
            return
        self.create_plan(group, cut, on_sheet.isChecked(),
                         parse_scale(scale.text(), 100.0),
                         open_sheet=open_it.isChecked())

    def _isolate_targets(self) -> list:
        from core.group import Group
        picked = self._selected_groups()
        if not picked:
            picked = [g for g in self._scene().selection
                      if isinstance(g, Group)]
        return picked

    def _isolated_now(self) -> list:
        """The groups Isolate hid that are hidden still — what leaving the
        isolation brings back. Empty: not isolated (left, undone, or each
        one shown by hand since)."""
        live = {id(g) for g, _p, _d in outliner.walk(self._scene().groups)}
        return [g for g in getattr(self, "_isolated", None) or ()
                if g.hidden and id(g) in live]

    def _update_isolate_button(self) -> None:
        """◎ «Isolate» — or ◉ pressed, «Exit isolation», while isolated.
        Only isolation turns it: what was hidden by hand is not its
        business, and stays hidden when the isolation ends."""
        b = getattr(self, "_isolate_btn", None)
        if b is None:
            return
        isolated = bool(self._isolated_now())
        b.setChecked(isolated)
        b.setIcon(node_icon("isolate_on" if isolated else "isolate"))
        b.setToolTip(tr("Exit isolation: show again what Isolate hid")
                     if isolated else
                     tr("Isolate: hide everything but the selected groups"))

    def _isolate_or_show(self) -> None:
        if self._isolated_now():
            self.exit_isolation()
        else:
            self.isolate()
        self._update_isolate_button()

    def exit_isolation(self) -> None:
        """Show again exactly what Isolate hid — one undoable step; what
        was hidden before isolating stays hidden."""
        from core.history import HideCommand
        back = self._isolated_now()
        self._isolated = []
        if back:
            self._window.viewport.history.execute(HideCommand(back,
                                                              hidden=False))
            self._window.viewport.update()
        self.refresh()

    def isolate(self) -> None:
        """Hide every group but the selected ones and those holding them —
        one undoable step; Exit isolation (or undo) brings them back.
        Loose geometry, dimensions and texts stay (#272)."""
        from core.history import HideCommand
        keep = self._isolate_targets()
        if not keep:
            self._window.viewport.flash_status(tr(
                "Select the groups to keep in view first"), 3000)
            return
        hide = outliner.isolate_hides(self._scene().groups, keep)
        if hide:
            self._window.viewport.history.execute(HideCommand(hide,
                                                              hidden=True))
            # Remembered, to give back exactly these when leaving it (an
            # isolation inside an isolation adds to it).
            self._isolated = self._isolated_now() + [
                g for g in hide if g not in self._isolated_now()]
            self._window.viewport.update()
        self.refresh()

    def _on_header_clicked(self, col: int) -> None:
        """The eye's header hides everything, or shows it all again when
        something is hidden; the padlock's locks or unlocks it all. On the
        model's top-level groups: what they hold follows, faded, and keeps
        its own state — a group locked on purpose inside stays locked."""
        tops = list(self._scene().groups)
        if not tops:
            return
        if col == COL_EYE:
            self.toggle_hidden(tops)
        elif col == COL_LOCK:
            self.toggle_locked(tops)

    def show_all(self) -> None:
        """Show every hidden group of the tree, at every level — one
        undoable step; an isolation ends with it."""
        from core.history import HideCommand
        hidden = [g for g, _p, _d in outliner.walk(self._scene().groups)
                  if g.hidden]
        self._isolated = []
        if hidden:
            self._window.viewport.history.execute(HideCommand(hidden,
                                                              hidden=False))
            self._window.viewport.update()
        self.refresh()

    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != COL_NAME:
            return
        from core.history import RenameGroupCommand
        group = self._group_of(item)
        if group is None:
            return
        name = item.text(COL_NAME).strip()
        if name and name != group.name:
            self._window.viewport.history.execute(
                RenameGroupCommand(group, name))
            self._window.viewport.update()
        self.refresh()

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        group = self._group_of(item)
        menu = QMenu(self)
        plane = self._plane_of(item)
        if plane is not None:
            menu.addAction(tr("Rename… (F2)"),
                           lambda: QTimer.singleShot(
                               0, lambda: self.rename_plane(plane)))
            menu.addAction(tr("Create view of this cut…"),
                           lambda: QTimer.singleShot(
                               0, lambda: self.ask_cut_view(plane)))
            menu.addSeparator()
            current = outliner.section_mode(plane)
            for mode in ("both", "cut", "frame", "off"):
                act = menu.addAction(tr(self._SECTION_MODE_TEXT[mode]),
                                     lambda m=mode: self.set_section_mode(
                                         plane, m))
                act.setCheckable(True)
                act.setChecked(mode == current)
            menu.addSeparator()
            self._fill_actions(menu)
            self._plane_fill_menu(menu, plane)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if item is not None and item is self._sec_root:
            scene = self._scene()
            for text, attr, key in (
                    (tr("Section Planes"), "show_section_planes", "planes"),
                    (tr("Section Cuts"), "show_section_cuts", "cuts")):
                on = bool(getattr(scene, attr, True))
                act = menu.addAction(text, lambda k=key, v=not on:
                                     self.set_section_globals(**{k: v}))
                act.setCheckable(True)
                act.setChecked(on)
            self._fill_actions(menu)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if group is not None:
            menu.addAction(tr("Rename…"), lambda: self.tree.editItem(
                item, COL_NAME))
            selected = self._selected_groups()
            targets = selected if group in selected else [group]
            if len(targets) > 1:
                menu.addAction(tr("Rename selected…"), lambda: QTimer.singleShot(
                    0, lambda: self.ask_batch_rename(targets)))
            menu.addAction(tr("Show") if group.hidden else tr("Hide"),
                           lambda: self.toggle_hidden(targets))
            menu.addAction(tr("Unlock") if getattr(group, "locked", False)
                           else tr("Lock"),
                           lambda: self.toggle_locked(targets))
            menu.addAction(tr("Open for editing"),
                           lambda: self.open_item(item))
            scale_act = menu.addAction(
                tr("Scale…"), lambda: QTimer.singleShot(
                    0, lambda: self.ask_scale(group)))
            scale_act.setEnabled(len(targets) == 1)
            # Make Group / Make Component from here, as from the view's
            # right-click (#561, @BastelBaus); inside an open group what
            # they make goes into it (#490).
            # Greyed, with the reason, when they cannot be: a locked or
            # hidden row cannot be selected, so the command found nothing
            # to group and seemed to do nothing at all.
            why = self.make_refusal(targets)
            menu.setToolTipsVisible(True)
            entries = [("Make Group", "group")] if len(targets) > 1 else []
            entries.append(("Make Component", "component"))
            # Explode: one level dissolved — a group's own geometry left
            # loose, the groups it holds out whole in its place.
            entries.append(("Explode Group", "explode"))
            for text, kind in entries:
                act = menu.addAction(tr(text), lambda k=kind:
                                     QTimer.singleShot(0, lambda:
                                                       self.make_from_rows(
                                                           targets, k)))
                if why:
                    act.setEnabled(False)
                    act.setToolTip(why)
            # Make Unique and Select Instances, for the components among
            # the rows (#87, #620) — as from the view, from here.
            comps = [g for g in targets if g.is_component()]
            if comps:
                inside = self.inside_component_refusal(comps)
                act = menu.addAction(tr("Make Unique"), lambda:
                                     QTimer.singleShot(0, lambda:
                                                       self.make_unique_rows(
                                                           comps)))
                if inside:
                    act.setEnabled(False)
                    act.setToolTip(inside)
                copies = self.copies_of_rows(comps)
                menu.addAction(tr("Select Instances ({n})", n=len(copies)),
                               lambda: self.select_copies(comps))
            if outliner.path_to(self._scene().groups, group):
                menu.addAction(tr("Move out of the group (Shift+Tab)"),
                               lambda: self.outdent())
            menu.addSeparator()
            self._batch_menu(menu, targets)
            menu.addSeparator()
            menu.addAction(tr("Create plan of this group…"),
                           lambda: QTimer.singleShot(
                               0, lambda: self.ask_plan(group)))
        if self._scene().edit_group is not None:
            menu.addAction(tr("Close group"), self.step_out)
        if self._scene().selection:
            menu.addAction(tr("Zoom Selection"),
                           self._window._on_zoom_selection)
        menu.addSeparator()
        if group is not None or self._isolate_targets():
            menu.addAction(tr("Isolate"), self.isolate)
        if self._isolated_now():
            menu.addAction(tr("Exit isolation"), self.exit_isolation)
        # The way out of everything: every hidden group, at every level.
        menu.addAction(tr("Show everything hidden (every level)"),
                       self.show_all)
        menu.addSeparator()
        menu.addAction(tr("Expand all"), self._expand_all)
        menu.addAction(tr("Collapse all"), self._collapse_all)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ---- Sheets 2D -----------------------------------------------------------------

class _SheetsTree(QTreeWidget):
    """The Sheets 2D tree: a scene dragged onto a sheet (or onto one of its
    views) is placed on it; Alt+↑/↓ move a sheet in the set; Supr deletes
    one."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)

    def mimeTypes(self):
        from views.composer import SCENE_MIME
        return [SCENE_MIME]

    def mimeData(self, items):
        """The dragged scenes, by name — what the page of the composer (and
        a sheet row here) takes."""
        from PySide6.QtCore import QMimeData
        from views.composer import SCENE_MIME
        names = [d[1].name for d in (it.data(0, Qt.UserRole) for it in items)
                 if d and d[0] == "scene"]
        data = QMimeData()
        data.setData(SCENE_MIME, "\n".join(names).encode("utf-8"))
        return data

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def dropEvent(self, ev) -> None:
        item = self.itemAt(ev.position().toPoint())
        ev.setDropAction(Qt.IgnoreAction)          # the model moves, not Qt
        ev.accept()
        sheet = self._panel.sheet_of(item)
        scenes = [d[1] for d in (it.data(0, Qt.UserRole)
                                 for it in self.selectedItems())
                  if d and d[0] == "scene"]
        if sheet is not None and scenes:
            for view in scenes:
                self._panel.place_scene(view, sheet)

    def event(self, ev) -> bool:
        from PySide6.QtCore import QEvent
        if (ev.type() == QEvent.ShortcutOverride
                and self.state() != QAbstractItemView.EditingState
                and self._panel.current_sheet() is not None
                and ((ev.key() in (Qt.Key_Up, Qt.Key_Down)
                      and ev.modifiers() & Qt.AltModifier)
                     or ev.key() == Qt.Key_Delete)):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:
        sheet = self._panel.current_sheet()
        if sheet is not None and self.state() != \
                QAbstractItemView.EditingState:
            if ev.key() in (Qt.Key_Up, Qt.Key_Down) and \
                    ev.modifiers() & Qt.AltModifier:
                self._panel.move_sheet(sheet,
                                       -1 if ev.key() == Qt.Key_Up else 1)
                return
            if ev.key() == Qt.Key_Delete:
                self._panel.delete_sheet(sheet)
                return
        super().keyPressEvent(ev)


class SheetsPanel(QWidget):
    """Saved scenes and sheets with their view frames (the Sheets 2D tab) —
    where views go onto sheets: drag a scene onto a sheet, make, order,
    duplicate, delete and print sheets, and see which scenes are on no
    sheet yet."""

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        self._window = window
        #: The sheet composer this panel lives in (its «Views and sheets»
        #: dock): scenes then go onto the page open beside it, through the
        #: composer's own undo, and show a picture of themselves.
        self._composer_win = composer
        self._stale = False
        self._shape = None
        self._thumb_queue: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.tree = _SheetsTree(self)
        if composer is not None:
            from PySide6.QtCore import QSize
            self.tree.setIconSize(QSize(48, 32))
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("Name"), tr("Details")])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        head = self.tree.header()
        head.setStretchLastSection(True)
        head.setSectionResizeMode(0, QHeaderView.Interactive)
        head.resizeSection(0, 230)
        _remember_widths(head, "browser/sheet_columns", (0,))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setToolTip(tr(
            "Drag a scene onto the page to place it where you drop it, or "
            "double-click it to place it in a free spot. Double-click a sheet "
            "to open it. F2 renames, Alt+↑/↓ moves a sheet, Delete removes "
            "it.") if composer is not None else tr(
            "Drag a scene onto a sheet to place it there. Double-click a "
            "scene to show it, a sheet or a view to open the sheet. F2 "
            "renames, Alt+↑/↓ moves a sheet, Delete removes it. Selecting a "
            "scene marks the views that show it."))
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.tree.itemDoubleClicked.connect(
            lambda item, _col: self.activate(item))
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(
            lambda item, _prev: self._mark_related(item))
        self._updating = False
        self._related: list = []
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        lay.addWidget(self.tree, 1)
        new_sheet = _tool_button(tr("New sheet"), tr(
            "Open the sheet composer on a new sheet"), self._new_sheet)
        new_sheet.setToolButtonStyle(Qt.ToolButtonTextOnly)
        export = _tool_button(tr("Export PDF…"), tr(
            "The selected sheets — or all of them — into one PDF"),
            lambda: self.export_pdf())
        export.setToolButtonStyle(Qt.ToolButtonTextOnly)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(new_sheet)
        row.addWidget(export)
        lay.addLayout(row)
        self.scenes_root = None
        self.sheets_root = None
        # The composer is another window and edits sheets without telling
        # the model: while this tab is on screen it checks, once a second,
        # whether what it lists changed (a fingerprint of a few names — it
        # costs nothing when nothing did).
        from PySide6.QtCore import QTimer
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self.refresh)
        self.refresh()

    def _scene(self):
        return self._window.viewport.scene

    def on_scene_changed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._stale = True
            self.sync_composer()        # the composer is another window

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        # Sheets change in the composer window, which does not touch the
        # model's version: looking at the tab is when to catch up.
        self.refresh()
        self._poll.start()

    def hideEvent(self, ev) -> None:
        self._poll.stop()
        super().hideEvent(ev)

    def refresh(self) -> None:
        self._stale = False
        if self.tree.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        scene = self._scene()
        shape = outliner.sheets_shape(scene)
        if shape == self._shape:
            return
        self._shape = shape
        self._updating = True
        try:
            self._fill(scene)
        finally:
            self._updating = False
        self.sync_composer()
        if self._composer_win is not None:
            self._queue_thumbnails()

    def _queue_thumbnails(self) -> None:
        """Pictures of the scenes, one at a time from the event loop — a
        render each, so the panel shows at once and fills in. Queued by
        NAME: a render can refresh the panel, and the row it was for is
        then another one."""
        from PySide6.QtCore import QTimer
        root = self.scenes_root
        self._thumb_queue = []
        for i in range(root.childCount() if root is not None else 0):
            data = root.child(i).data(0, Qt.UserRole)
            if data:
                self._thumb_queue.append(data[1].name)
        QTimer.singleShot(0, self._next_thumbnail)

    def _scene_row(self, name):
        root = self.scenes_root
        for i in range(root.childCount() if root is not None else 0):
            item = root.child(i)
            data = item.data(0, Qt.UserRole)
            if data and data[1].name == name:
                return item
        return None

    def _next_thumbnail(self) -> None:
        from shiboken6 import isValid
        if not self._thumb_queue or not isValid(self):
            return
        name = self._thumb_queue.pop(0)
        icon = self._composer_win.scene_thumbnail(name)
        item = self._scene_row(name)          # after the render: the live row
        if icon is not None and item is not None and isValid(item):
            # A new icon is an item change to Qt, not a rename: unguarded,
            # it went through _on_item_changed, touched the document and
            # rebuilt the list — which queued the pictures again: the
            # scenes flickered, and the file read as modified.
            self._updating = True
            try:
                item.setIcon(0, icon)
            finally:
                self._updating = False
        if self._thumb_queue:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(20, self._next_thumbnail)

    def refresh_thumbnails(self) -> None:
        if self._composer_win is None:
            return
        self._composer_win.forget_thumbnails()
        self._queue_thumbnails()

    def sync_composer(self) -> None:
        """Bring an open composer up to date with the document's sheets
        and scenes. It reloads them when it opens; a sheet or a scene made
        while it is already open (Create plan, the browser) — or one undone
        under it — did not reach it: the new sheet missed from its list,
        or the window kept showing a sheet that no longer existed."""
        comp_win = getattr(self._window, "_composer", None)
        if comp_win is None:
            return
        # Only when the sheets or scenes changed: reloading the composer's
        # list refreshes the sheet strip, which calls back here.
        shape = outliner.sheets_shape(self._scene())
        if shape == getattr(self, "_synced_shape", None):
            return
        self._synced_shape = shape
        comps = self._scene().compositions
        if comp_win.comp not in comps:
            if not comps:
                return                      # it makes its own on showing
            from core.composition import ComposerHistory
            comp_win.comp = comps[0]
            comp_win.history = ComposerHistory(
                on_change=comp_win._on_history_change)
            comp_win._rebuild_canvas()
        comp_win._reload_comp_combo()
        reload = getattr(comp_win, "_reload_view_sources", None)
        if reload is not None:
            reload()
        if comp_win.isVisible():
            # A view placed or taken away from here, on the open sheet.
            comp_win._rebuild_canvas()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, comp_win._auto_render_stale)

    def show_scene_row(self, name: str) -> None:
        """Bring the scene called ``name`` into view, current — which also
        marks the sheet views that show it."""
        self.refresh()
        root = self.scenes_root
        for i in range(root.childCount() if root is not None else 0):
            item = root.child(i)
            data = item.data(0, Qt.UserRole)
            if data and data[1].name == name:
                root.setExpanded(True)
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def _fill(self, scene) -> None:
        current = self.tree.currentItem()
        current_key = self._key(current) if current is not None else None
        self._related = []
        from core.composition import format_scale
        from views.composer import frame_view_name
        expanded = {self._key(it) for it in self._all_items()
                    if it.isExpanded()}
        first = self.tree.topLevelItemCount() == 0
        used = outliner.scene_usage(scene)
        self.tree.clear()
        views = list(getattr(scene, "saved_views", None) or ())
        comps = list(getattr(scene, "compositions", None) or ())
        unplaced = len(outliner.unplaced_scenes(scene))
        self.scenes_root = QTreeWidgetItem(
            [tr("Scenes"), tr("{n} saved · {k} on no sheet", n=len(views),
                              k=unplaced) if unplaced
             else tr("{n} saved", n=len(views))])
        self.scenes_root.setIcon(0, node_icon("folder"))
        self.sheets_root = QTreeWidgetItem(
            [tr("Sheets"), tr("{n} sheets", n=len(comps))])
        self.sheets_root.setIcon(0, node_icon("folder"))
        for root in (self.scenes_root, self.sheets_root):
            font = QFont(root.font(0))
            font.setBold(True)
            root.setFont(0, font)
            root.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(root)
        for view in views:
            on = used.get(view.name, [])
            item = QTreeWidgetItem([view.name, tr("On {sheets}",
                                                  sheets=", ".join(on))
                                    if on else tr("Not on a sheet")])
            item.setIcon(0, node_icon("scene"))
            item.setData(0, Qt.UserRole, ("scene", view))
            item.setFlags((item.flags() | Qt.ItemIsEditable
                           | Qt.ItemIsDragEnabled) & ~Qt.ItemIsDropEnabled)
            if not on:
                font = QFont(item.font(0))
                font.setItalic(True)
                item.setFont(0, font)
            self.scenes_root.addChild(item)
        for index, comp in enumerate(comps):
            orient = tr("landscape") if comp.landscape else tr("portrait")
            sheet = QTreeWidgetItem([comp.name, f"{comp.paper} · {orient}"])
            sheet.setIcon(0, node_icon("sheet"))
            sheet.setData(0, Qt.UserRole, ("sheet", index))
            sheet.setFlags((sheet.flags() | Qt.ItemIsEditable
                            | Qt.ItemIsDropEnabled) & ~Qt.ItemIsDragEnabled)
            self.sheets_root.addChild(sheet)
            for frame in comp.frames:
                if frame.view_key == "__current__":
                    name = tr("Current view")
                else:
                    name = frame_view_name(frame)
                item = QTreeWidgetItem(
                    [f"{name} · {format_scale(frame.scale_n)}", ""])
                item.setData(0, Qt.UserRole, ("frame", index, frame))
                item.setFlags((item.flags() | Qt.ItemIsDropEnabled)
                              & ~Qt.ItemIsDragEnabled)
                if outliner.is_orphan(scene, frame):
                    item.setIcon(0, node_icon("warning"))
                    item.setText(1, tr("Scene missing"))
                    item.setToolTip(0, tr(
                        "This view shows the scene «{name}», which the "
                        "model no longer has. The frame keeps its place on "
                        "the sheet; pick another view for it in the "
                        "composer.", name=outliner.frame_scene(frame)))
                else:
                    item.setIcon(0, node_icon("frame"))
                    item.setText(1, tr("Scene") if outliner.frame_scene(
                        frame) else tr("Standard view")
                        if frame.view_key.startswith("std:")
                        else tr("Live camera"))
                sheet.addChild(item)
        for it in self._all_items():
            if first or self._key(it) in expanded or it in (
                    self.scenes_root, self.sheets_root):
                it.setExpanded(True)
            if current_key is not None and self._key(it) == current_key:
                self.tree.setCurrentItem(it)

    def _all_items(self):
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    @staticmethod
    def _key(item):
        data = item.data(0, Qt.UserRole)
        if data is None:
            return ("root", item.text(0))
        return (data[0], item.text(0))

    # ---- Scenes ↔ views ---------------------------------------------------
    def _mark_related(self, item) -> None:
        """Mark what the current row is linked to: a scene → the views that
        show it, on every sheet; a view → its scene. The link is the one
        a sheet keeps — the scene's name — read both ways."""
        from PySide6.QtGui import QBrush
        for it in self._related:
            for col in (0, 1):
                it.setBackground(col, QBrush())
            it.setData(0, Qt.UserRole + 1, False)
        self._related = []
        data = item.data(0, Qt.UserRole) if item is not None else None
        if not data:
            return
        if data[0] == "scene":
            name = data[1].name
            wanted = lambda d: d[0] == "frame" and \
                outliner.frame_scene(d[2]) == name
        elif data[0] == "frame" and outliner.frame_scene(data[2]):
            name = outliner.frame_scene(data[2])
            wanted = lambda d: d[0] == "scene" and d[1].name == name
        else:
            return
        tint = QColor(_accent())
        tint.setAlpha(60)
        for it in self._all_items():
            d = it.data(0, Qt.UserRole)
            if d and wanted(d):
                for col in (0, 1):
                    it.setBackground(col, tint)
                it.setData(0, Qt.UserRole + 1, True)
                self._related.append(it)
                self._reveal(it)

    @staticmethod
    def _reveal(item) -> None:
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    def related(self) -> list:
        """The rows marked as linked to the current one."""
        return list(self._related)

    # ---- Rename --------------------------------------------------------
    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != 0:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[0] not in ("scene", "sheet"):
            return
        text = item.text(0).strip()
        comps = self._scene().compositions
        current = (data[1].name if data[0] == "scene"
                   else comps[data[1]].name if 0 <= data[1] < len(comps)
                   else None)
        if text == current:
            return                      # not a rename: nothing to do
        if data[0] == "scene":
            self.rename_scene(data[1], text)
        else:
            self.rename_sheet(data[1], text)

    def _touch(self) -> None:
        self._scene().version += 1          # a document change: unsaved
        self._window.viewport.update()
        self._shape = None
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh)  # not under the editor's signal

    def rename_scene(self, view, name: str) -> bool:
        """Rename a scene and carry the sheet views that show it along."""
        if not outliner.rename_scene(self._scene(), view, name):
            if name and name != view.name:
                self._window.viewport.flash_status(tr(
                    "Another scene is already called «{name}»", name=name),
                    3500)
            self._touch()
            return False
        self._window.tray.scenes.refresh()
        composer = getattr(self._window, "_composer", None)
        reload = getattr(composer, "_reload_view_sources", None)
        if reload is not None:
            reload()
        self._touch()
        return True

    def rename_sheet(self, index: int, name: str) -> bool:
        comps = self._scene().compositions
        if not name or not 0 <= index < len(comps) \
                or comps[index].name == name:
            self._touch()
            return False
        comps[index].name = name
        composer = getattr(self._window, "_composer", None)
        if getattr(composer, "comp_combo", None) is not None:
            composer._reload_comp_combo()
        else:
            self._window._refresh_sheet_tabs()
        self._touch()
        return True

    # ---- Working with sheets -----------------------------------------------
    def sheet_of(self, item):
        """The sheet a row is (or is in), or ``None``."""
        data = item.data(0, Qt.UserRole) if item is not None else None
        comps = self._scene().compositions
        if data and data[0] in ("sheet", "frame") and \
                0 <= data[1] < len(comps):
            return comps[data[1]]
        return None

    def current_sheet(self):
        item = self.tree.currentItem()
        data = item.data(0, Qt.UserRole) if item is not None else None
        return self.sheet_of(item) if data and data[0] == "sheet" else None

    def _selected_sheets(self) -> list:
        out = []
        for it in self.tree.selectedItems():
            sheet = self.sheet_of(it)
            if sheet is not None and sheet not in out:
                out.append(sheet)
        return out

    def place_scene(self, view, sheet=None, scale: float = 100.0):
        """Place scene ``view`` on ``sheet`` — on a new sheet named after
        it when ``None`` — in a free spot of the page, at 1:``scale``. One
        undo step; returns the new frame."""
        from core.composition import Composicion, MarcoVista
        from core.history import (AddSheetCommand, CompoundCommand,
                                  PlaceViewCommand)
        scene = self._scene()
        comp_win = self._composer_win
        if comp_win is not None and sheet is not None:
            # Beside the page: open that sheet and put the view in a free
            # place of it, as one step of the composer's own undo.
            comps = scene.compositions
            if comp_win.comp is not sheet and sheet in comps:
                comp_win.show_sheet(comps.index(sheet))
            return comp_win.place_scene_at(view.name)
        cmds = []
        if sheet is None:
            sheet = Composicion(name=outliner.unique_name(
                view.name, [c.name for c in scene.compositions]),
                paper="A3")
            cmds.append(AddSheetCommand(sheet))
        pw, ph = sheet.page_size_mm()
        m = float(getattr(sheet, "margin_mm", 10.0) or 0.0)
        w_mm = max(60.0, (pw - 2 * m) / 2 - 15)
        h_mm = max(45.0, (ph - 2 * m) / 2 - 15)
        # A quarter of the page where there is room; smaller where there is
        # less; over the others, a step aside, only on a full page.
        spot = None
        for k in (1.0, 0.75, 0.5, 0.35):
            spot = outliner.free_slot(sheet, w_mm * k, h_mm * k,
                                      fallback=False)
            if spot is not None:
                w_mm, h_mm = w_mm * k, h_mm * k
                break
        x, y = spot if spot is not None else outliner.free_slot(
            sheet, w_mm, h_mm)
        frame = MarcoVista(x_mm=x, y_mm=y, w_mm=w_mm, h_mm=h_mm,
                           view_key=f"scene:{view.name}",
                           scale_n=float(scale), show_title=True)
        cmds.append(PlaceViewCommand(sheet, frame))
        self._window.viewport.history.execute(
            CompoundCommand(cmds) if len(cmds) > 1 else cmds[0])
        self._window._refresh_sheet_tabs()
        self._window.viewport.flash_status(tr(
            "«{scene}» placed on «{sheet}»", scene=view.name,
            sheet=sheet.name), 4000)
        self.refresh()
        return frame

    def move_sheet(self, sheet, step: int) -> None:
        """Up or down the set — one undo step."""
        from core.history import MoveSheetCommand
        comps = self._scene().compositions
        i = comps.index(sheet) + step
        if not 0 <= i < len(comps):
            return
        self._window.viewport.history.execute(MoveSheetCommand(sheet, i))
        self._window._refresh_sheet_tabs()
        self.refresh()
        self._select_sheet(sheet)

    def _select_sheet(self, sheet) -> None:
        comps = self._scene().compositions
        if sheet not in comps or self.sheets_root is None:
            return
        item = self.sheets_root.child(comps.index(sheet))
        if item is not None:
            self.tree.setCurrentItem(item)

    def duplicate_sheet(self, sheet) -> None:
        comp_win = self._window._ensure_composer()
        comp_win.duplicate_sheet(self._scene().compositions.index(sheet))
        self._window._refresh_sheet_tabs()
        self.refresh()

    def delete_sheet(self, sheet) -> None:
        """Through the composer: it asks first and keeps one sheet."""
        comp_win = self._window._ensure_composer()
        if comp_win.delete_sheet(self._scene().compositions.index(sheet),
                                 self):
            self._window._refresh_sheet_tabs()
            self.refresh()

    def export_pdf(self, sheets=None, path=None) -> None:
        """The selected sheets (all, when none is selected) into one PDF,
        in the set's order — the composer's own atlas export."""
        sheets = sheets if sheets is not None else self._selected_sheets()
        if path is None:
            from views.filedialogs import file_dialogs
            path, _ = file_dialogs.getSaveFileName(
                self, tr("Export PDF…"), "laminas.pdf", "PDF (*.pdf)")
        if not path:
            return
        comp_win = self._window._ensure_composer()
        troubled = comp_win.export_all_pdf(path, sheets or None)
        n = len(sheets) if sheets else len(self._scene().compositions)
        self._window.viewport.flash_status(
            tr("Exported {n} sheets to {name}", n=n, name=path)
            if not troubled else
            tr("Exported {name} — but a view would not render on {sheets}",
               name=path, sheets=", ".join(troubled)), 6000)

    def _place_menu(self, menu, view) -> None:
        sub = menu.addMenu(tr("Place on sheet"))
        for comp in self._scene().compositions:
            sub.addAction(comp.name, lambda c=comp: self.place_scene(view, c))
        sub.addSeparator()
        sub.addAction(tr("On a new sheet"),
                      lambda: self.place_scene(view, None))

    def activate(self, item) -> None:
        """Double-click: a scene shows (in the composer: is placed in a
        free place of the open sheet), a sheet (or one of its views) opens
        in the composer."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        if data[0] == "scene" and self._composer_win is not None:
            self._composer_win.place_scene_at(data[1].name)
        elif data[0] == "scene":
            self._show_scene(data[1])
        else:
            self._window._show_sheet(data[1])

    def _show_scene(self, view) -> None:
        """Through the Scenes panel, so a scene shown from here does all
        a scene shown there does (style menu, selection, layers)."""
        scenes = self._window.tray.scenes
        for i in range(scenes.list.count()):
            row = scenes.list.item(i)
            if row.data(Qt.UserRole) is view:
                scenes._on_activate(row)
                return

    def _new_sheet(self) -> None:
        self._window._show_new_sheet()
        self.refresh()

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item is not None else None
        menu = QMenu(self)
        if data and data[0] == "scene":
            menu.addAction(tr("Show scene"), lambda: self.activate(item))
            menu.addAction(tr("Rename…"), lambda: self.tree.editItem(item, 0))
            self._place_menu(menu, data[1])
        elif data:
            menu.addAction(tr("Open sheet"), lambda: self.activate(item))
            if data[0] == "sheet":
                sheet = self.sheet_of(item)
                menu.addAction(tr("Rename…"),
                               lambda: self.tree.editItem(item, 0))
                menu.addAction(tr("Duplicate sheet"),
                               lambda: self.duplicate_sheet(sheet))
                menu.addAction(tr("Delete sheet"),
                               lambda: self.delete_sheet(sheet))
                menu.addSeparator()
                menu.addAction(tr("Move up (Alt+↑)"),
                               lambda: self.move_sheet(sheet, -1))
                menu.addAction(tr("Move down (Alt+↓)"),
                               lambda: self.move_sheet(sheet, 1))
                menu.addSeparator()
                views = list(self._scene().saved_views)
                if views:
                    sub = menu.addMenu(tr("Place a scene here"))
                    free = outliner.unplaced_scenes(self._scene())
                    for v in free + [v for v in views if v not in free]:
                        sub.addAction(v.name, lambda vv=v, s=sheet:
                                      self.place_scene(vv, s))
                chosen = self._selected_sheets() or [sheet]
                menu.addAction(tr("Export to PDF…") if len(chosen) == 1
                               else tr("Export {n} sheets to PDF…",
                                       n=len(chosen)),
                               lambda: self.export_pdf(chosen))
            if data[0] == "frame":
                name = outliner.frame_scene(data[2])
                view = next((v for v in self._scene().saved_views
                             if v.name == name), None)
                if view is not None:
                    menu.addAction(tr("Show scene"),
                                   lambda: self._show_scene(view))
        menu.addAction(tr("New sheet"), self._new_sheet)
        if self._composer_win is not None:
            menu.addAction(tr("Refresh previews"), self.refresh_thumbnails)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ---- The dock ------------------------------------------------------------------

class ProjectBrowser(QDockWidget):
    """Sidebar tab **Browser**: the model's tree. The sheets have
    their own panel in the sheet composer, beside the page they go on
    («Views and sheets», :class:`SheetsPanel`)."""

    def __init__(self, window) -> None:
        super().__init__(tr("Browser"), window)
        self.setObjectName("tray_project_browser")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetClosable)
        self._window = window
        self.outliner = OutlinerPanel(window)
        self.setWidget(self.outliner)
        self.setMinimumWidth(240)

    def on_scene_changed(self) -> None:
        self.outliner.on_scene_changed()
        composer = getattr(self._window, "_composer", None)
        if composer is not None:
            composer.views_panel.on_scene_changed()
