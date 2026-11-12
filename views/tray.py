# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Right-side dockable tray, built from QDockWidget.

Holds collapsible sections:
- **Materiales** — a palette of colour + texture swatches ("En el modelo" and a
  bundled "Biblioteca"). Clicking a swatch makes it the active Paint material
  and switches to the Paint tool. ``+ Textura…`` adds an image with a tile size.
- **Estilo de cota** — precision, unit, font size and colour of dimensions,
  applied live to ``scene.dimension_style``.
- **Info de entidad** — read-only facts about the current selection (face area,
  edge length, dimension value, material).

A ``QDockWidget`` gives docking/floating/closing for free; the sections are a
vertical stack of lightweight collapsibles inside a scroll area.
"""
from __future__ import annotations

from views import prompts as _prompts

import math
import os
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStyledItemDelegate,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from views.color_dialog import get_color
from views.side_tree import SideTree
from core.i18n import tr
from views.theme import style as theme_style
from views.rtl import set_arrow
from views.filedialogs import file_dialogs
from core.mesh import Edge, Face
from core.bim import face_net_area
from core.group import Group
from core.dimension import Dimension
from georef.datum import SceneDatum
from georef.geopath import GeoPath
from georef.tiles import DEFAULT_SOURCE_ID, PRESETS, TileLayer, custom_source
from tools.paint import RECENT_MAX, PaintTool

from core.paths import app_root
from core.units import fmt_area, fmt_len, fmt_volume

_TEX_DIR = app_root() / "resources" / "textures"
#: RAL Classic — the paint standard a drawing can be specified in. Its names
#: are the standard's own, in the standard's own languages, so they live in
#: the data file beside the colour instead of in the UI translations, where
#: "Beige" or "Cream" would collide with strings that mean something else.
_RAL_FILE = app_root() / "resources" / "colors" / "ral.json"
_SWATCH = 44  # swatch pixel size


def _ral_rgb(name: str):
    """The library colour of a material named after a RAL colour
    («RAL 7035 Gris claro», in either language), or None."""
    if not name or not name.startswith("RAL "):
        return None
    global _RAL_BY_CODE
    if _RAL_BY_CODE is None:
        import json
        _RAL_BY_CODE = {}
        if _RAL_FILE.exists():
            data = json.loads(_RAL_FILE.read_text(encoding="utf-8"))
            for fam in data.get("families", []):
                for c in fam.get("colors", []):
                    _RAL_BY_CODE[c["code"]] = c
    entry = _RAL_BY_CODE.get(" ".join(name.split()[:2]))
    if entry is None:
        return None
    if name not in ("%s %s" % (entry["code"], entry.get("name", "")),
                    "%s %s" % (entry["code"], entry.get("name_es", ""))):
        return None
    return tuple(entry["rgb"][:3])


_RAL_BY_CODE = None


def _ral_name(entry: dict) -> str:
    """The RAL name in the language the app is running in."""
    from core.i18n import current_language
    if current_language().startswith("es") and entry.get("name_es"):
        return entry["name_es"]
    return entry["name"]


class _Section(QWidget):
    """A collapsible section: a header button that toggles its content."""

    def __init__(self, title: str, content: QWidget) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._btn = QToolButton()
        self._btn.setText(f"  {title}")
        self._btn.setCheckable(True)
        self._btn.setChecked(True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        set_arrow(self._btn, Qt.DownArrow)
        # Clean, light header (QGIS-style): plain bold title on the panel
        # background with a subtle underline — no dark bar. Uses palette() roles
        # so it adapts to light and dark themes.
        self._btn.setStyleSheet(
            "QToolButton { font-weight: bold; padding: 6px 4px; border: none;"
            " border-bottom: 1px solid palette(mid); text-align: left; }"
            "QToolButton:hover { background: palette(midlight); }")
        self._btn.toggled.connect(self._on_toggle)
        self._content = content
        lay.addWidget(self._btn)
        lay.addWidget(content)
        # Open or folded, as the user left it last time (a user in Brazil,
        # 25-09: «sempre que eu abro o software ele vem aberta… deve vir como
        # eu deixei»). Keyed by the panel's class, not its title: the title
        # changes with the language.
        self._key = f"tray/collapsed/{type(content).__name__}"
        from PySide6.QtCore import QSettings
        if str(QSettings().value(self._key, "0")) == "1":
            self._btn.setChecked(False)

    def _on_toggle(self, on: bool) -> None:
        self._content.setVisible(on)
        set_arrow(self._btn, Qt.DownArrow if on else Qt.RightArrow)
        key = getattr(self, "_key", None)
        if key is not None:
            from PySide6.QtCore import QSettings
            QSettings().setValue(key, "0" if on else "1")


def style_slider(slider) -> None:
    """A slider whose track reads on any theme. The platform style draws
    the groove in a shade of the window colour, which on macOS's dark
    appearance is black on near-black — the slider looked like a bare
    knob floating in the tray. The track is lifted off the background, the
    part up to the knob wears the highlight colour, and the knob is light
    with a highlight rim, on light and dark themes alike."""
    pal = slider.palette()
    dark = pal.window().color().lightness() < 128
    groove = "#9aa1ad" if dark else "#b9bec7"
    knob = "#e8eaee" if dark else "#ffffff"
    hi = pal.highlight().color().name()
    slider.setStyleSheet(
        "QSlider::groove:horizontal {"
        f" height: 6px; background: {groove}; border-radius: 3px; }}"
        "QSlider::sub-page:horizontal {"
        f" height: 6px; background: {hi}; border-radius: 3px; }}"
        "QSlider::handle:horizontal {"
        f" background: {knob}; border: 1px solid {hi};"
        " width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }")
    slider.setMinimumHeight(20)


def fit_rows(view, min_rows: int = 3, max_rows: int | None = None,
             rows: int | None = None) -> None:
    """Grow a list / tree to show ALL its rows — no scroll bar of its own,
    so the only scrolling in a tray is the tray's (Marco, 2026-09-14: «no
    me gusta hacer scroll dentro del scroll»). Call after every refill;
    ``min_rows`` keeps an empty list from collapsing to a sliver.

    ``max_rows`` caps that: past it the view stops growing and scrolls on
    its own — for the lists that get long, Layers and Components in the
    model (issue #55, @pacaeiro: «should have their own vertical scroll
    bar»). Short lists keep the no-nested-scroll rule. ``rows`` overrides
    the count — a tree passes the rows its open branches show."""
    from PySide6.QtWidgets import QAbstractItemView, QTreeView
    if rows is None:
        model = view.model()
        rows = model.rowCount() if model is not None else 0
    capped = max_rows is not None and rows > max_rows
    view.setVerticalScrollBarPolicy(
        Qt.ScrollBarAsNeeded if capped else Qt.ScrollBarAlwaysOff)
    view.setSizePolicy(view.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
    if capped:
        rows = max_rows
    if isinstance(view, QTreeView):
        row_h = view.sizeHintForRow(0) if rows else 0
        header = view.header().height() if not view.header().isHidden() else 0
    else:
        row_h = view.sizeHintForRow(0) if rows else 0
        header = 0
    if row_h <= 0:
        row_h = view.fontMetrics().height() + 8
    h = header + max(rows, min_rows) * row_h + 2 * view.frameWidth() + 2
    view.setFixedHeight(h)


def _color_pixmap(rgb, size=_SWATCH) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor.fromRgbF(*rgb))
    return pm


def _default_pixmap(size=_SWATCH) -> QPixmap:
    """The «Default» material swatch: the front's cream and the
    back's blue-grey split on the diagonal."""
    from PySide6.QtGui import QPainter, QPolygonF
    from PySide6.QtCore import QPointF
    pm = QPixmap(size, size)
    pm.fill(QColor.fromRgbF(0.96, 0.95, 0.925))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(164, 176, 196))
    p.drawPolygon(QPolygonF([QPointF(size, 0), QPointF(size, size),
                             QPointF(0, size)]))
    p.end()
    return pm


_texture_swatches: dict = {}


def _file_stamp(path):
    """What tells a picture file changed on disk (``None``: unreadable)."""
    import os
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _texture_pixmap(path, size=_SWATCH) -> QPixmap | None:
    """A swatch of the image at *path*. Read with the allocation limit off:
    ``QImage(path)`` refuses anything over Qt's 256 MB default, so a big
    texture (a packaging artwork, #460) painted fine — the viewport lifts
    the limit — but had no swatch at all.

    Kept per file (path, size, modification time): «In model» is rebuilt
    after every edit, and it read each texture image from disk again —
    ~0.9 s an undo on the plant of #158."""
    import os
    try:
        st = os.stat(path)
        key = (str(path), size, st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and key in _texture_swatches:
        return _texture_swatches[key]
    pm = _read_texture_pixmap(path, size)
    if key is not None:
        if len(_texture_swatches) > 512:
            _texture_swatches.clear()
        _texture_swatches[key] = pm
    return pm


def _read_texture_pixmap(path, size) -> QPixmap | None:
    from PySide6.QtGui import QImageReader
    limit = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(0)
    try:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        img = reader.read()
    finally:
        QImageReader.setAllocationLimit(limit)
    if img.isNull():
        return None
    return QPixmap.fromImage(img.scaled(size, size, Qt.IgnoreAspectRatio,
                                        Qt.SmoothTransformation))


def _swatch_button(pm: QPixmap, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(QIcon(pm))
    b.setIconSize(QSize(_SWATCH, _SWATCH))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    return b


class FlowLayout(QLayout):
    """A grid that REFLOWS with the width: swatches and component buttons
    fill as many columns as fit and wrap, so a widened tray shows more per
    row instead of a blank right half (Marco, 2026-09-15: «cuando
    redimensiono la barra debería ocupar ese espacio con más columnas»).
    Qt's classic flow layout; ``addWidget`` also accepts and ignores the
    ``row, col`` the grid callers used to pass."""

    def __init__(self, parent=None, spacing: int = 2) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    # ---- QLayout interface ---------------------------------------------------
    def addItem(self, item) -> None:            # noqa: N802 — Qt override
        self._items.append(item)
        self._hfw = None

    def addWidget(self, w, *_grid_pos) -> None:  # noqa: N802 — Qt override
        super().addWidget(w)

    def setColumnStretch(self, *_a) -> None:     # noqa: N802 — grid compat
        pass

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):               # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):               # noqa: N802
        self._hfw = None
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def invalidate(self) -> None:               # noqa: N802 — Qt override
        self._hfw = None
        super().invalidate()

    def expandingDirections(self):              # noqa: N802
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:        # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        # Asked again and again for the same width while the tray lays
        # itself out (4 000 times after one edit on the plant of #158,
        # ~0.2 s): kept until an item comes, goes or changes size.
        hit = getattr(self, "_hfw", None)
        if hit is not None and hit[0] == width:
            return hit[1]
        h = self._do_layout(QRect(0, 0, width, 0), test_only=True)
        self._hfw = (width, h)
        return h

    def setGeometry(self, rect) -> None:        # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):                         # noqa: N802
        return self.minimumSize()

    def minimumSize(self):                      # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def columns_at(self, width: int) -> int:
        """How many items the first row holds at ``width`` (for tests)."""
        m = self.contentsMargins()
        x = m.left()
        cols = 0
        for item in self._items:
            w = item.sizeHint().width()
            if cols and x + w > width - m.right():
                break
            x += w + self._spacing
            cols += 1
        return cols

    def _do_layout(self, rect, test_only: bool) -> int:
        m = self.contentsMargins()
        x = rect.x() + m.left()
        y = rect.y() + m.top()
        right = rect.right() - m.right()
        row_h = 0
        # Right to left (#1067) the rows fill from the right: Qt mirrors
        # its own layouts, a custom one mirrors itself.
        owner = self.parentWidget()
        mirror = (not test_only and owner is not None
                  and owner.isRightToLeft())
        for item in self._items:
            hint = item.sizeHint()
            if row_h and x + hint.width() - 1 > right:
                x = rect.x() + m.left()
                y += row_h + self._spacing
                row_h = 0
            if not test_only:
                geo = QRect(QPoint(x, y), hint)
                if mirror:
                    geo = QStyle.visualRect(Qt.RightToLeft, rect, geo)
                item.setGeometry(geo)
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
        return y + row_h + m.bottom() - rect.y()


class BaseMapPanel(QWidget):
    """Satellite/street base map (Track G): pick a source, go to a place.

    Setting a location anchors the scene datum (if unset) at that lat/lon and
    shows the tile layer around the origin. The tiles are display-only — they
    never enter the modelling mesh.
    """

    _ADD = "__add__"

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 8)

        grid.addWidget(QLabel(tr("Source:")), 0, 0)
        self._source = QComboBox()
        # Saved custom XYZ sources live in the combo alongside the presets
        # (QGIS-style: add once with a name, it is always there).
        self._custom_entries: dict[str, dict] = {}
        self._last_sid: str | None = None
        self._source.currentIndexChanged.connect(self._on_source_changed)
        grid.addWidget(self._source, 0, 1)

        self._remove_btn = QPushButton(tr("Remove this source"))
        self._remove_btn.setStyleSheet("font-size:11px; padding:2px 8px;")
        self._remove_btn.clicked.connect(self._remove_current_custom)
        self._remove_btn.setVisible(False)
        grid.addWidget(self._remove_btn, 1, 1)
        self._populate_sources(select=DEFAULT_SOURCE_ID)

        # One coordinate frame at a time — lat/lon OR UTM WGS84 — chosen
        # here and remembered across sessions (drone users live in UTM).
        grid.addWidget(QLabel(tr("Coordinates:")), 2, 0)
        self._coord_mode = QComboBox()
        self._coord_mode.addItem(tr("Geographic (lat/lon)"), "geo")
        self._coord_mode.addItem(tr("UTM WGS84"), "utm")
        self._coord_mode.currentIndexChanged.connect(self._on_coord_mode)
        grid.addWidget(self._coord_mode, 2, 1)

        self._lat_label = QLabel(tr("Latitude:"))
        grid.addWidget(self._lat_label, 3, 0)
        self._lat = QDoubleSpinBox()
        self._lat.setRange(-85.0, 85.0)
        self._lat.setDecimals(6)
        self._lat.setValue(-12.046400)
        grid.addWidget(self._lat, 3, 1)

        self._lon_label = QLabel(tr("Longitude:"))
        grid.addWidget(self._lon_label, 4, 0)
        self._lon = QDoubleSpinBox()
        self._lon.setRange(-180.0, 180.0)
        self._lon.setDecimals(6)
        self._lon.setValue(-77.042800)
        grid.addWidget(self._lon, 4, 1)

        # The same anchor in UTM WGS84 — the frame a drone survey or a
        # total station reports. Both entries stay in sync: type E/N from
        # the survey OR lat/lon, whichever the paper in hand shows.
        zrow = QWidget()
        zbox = QHBoxLayout(zrow)
        zbox.setContentsMargins(0, 0, 0, 0)
        self._utm_zone = QSpinBox()
        self._utm_zone.setRange(1, 60)
        self._utm_zone.editingFinished.connect(self._sync_ll_from_utm)
        zbox.addWidget(self._utm_zone)
        self._utm_hemi = QComboBox()
        self._utm_hemi.addItem(tr("North"), True)
        self._utm_hemi.addItem(tr("South"), False)
        self._utm_hemi.activated.connect(self._sync_ll_from_utm)
        zbox.addWidget(self._utm_hemi, 1)
        self._utm_zone_label = QLabel(tr("UTM zone:"))
        grid.addWidget(self._utm_zone_label, 5, 0)
        grid.addWidget(zrow, 5, 1)
        self._utm_zone_row = zrow

        self._utm_e_label = QLabel(tr("UTM E:"))
        grid.addWidget(self._utm_e_label, 6, 0)
        self._utm_e = QDoubleSpinBox()
        self._utm_e.setRange(100000.0, 900000.0)
        self._utm_e.setDecimals(2)
        self._utm_e.setGroupSeparatorShown(True)
        self._utm_e.editingFinished.connect(self._sync_ll_from_utm)
        grid.addWidget(self._utm_e, 6, 1)

        self._utm_n_label = QLabel(tr("UTM N:"))
        grid.addWidget(self._utm_n_label, 7, 0)
        self._utm_n = QDoubleSpinBox()
        self._utm_n.setRange(0.0, 10000000.0)
        self._utm_n.setDecimals(2)
        self._utm_n.setGroupSeparatorShown(True)
        self._utm_n.editingFinished.connect(self._sync_ll_from_utm)
        grid.addWidget(self._utm_n, 7, 1)

        self._lat.editingFinished.connect(self._sync_utm_from_ll)
        self._lon.editingFinished.connect(self._sync_utm_from_ll)
        self._sync_utm_from_ll()
        saved_mode = str(QSettings().value("georef/coord_mode", "geo"))
        idx = self._coord_mode.findData(saved_mode)
        self._coord_mode.setCurrentIndex(max(idx, 0))
        self._apply_coord_mode()

        # North angle: turns the map, terrain and
        # every geographic import UNDER the model — the model, its standard
        # views and axis locks stay square. 0 = the green axis points north.
        self._north_label = QLabel(tr("North:"))
        grid.addWidget(self._north_label, 8, 0)
        self._north = QDoubleSpinBox()
        self._north.setRange(-180.0, 180.0)
        self._north.setDecimals(2)
        self._north.setSingleStep(1.0)
        self._north.setWrapping(True)
        self._north.setSuffix("°")
        self._north.setToolTip(tr(
            "Where true north lies, in degrees clockwise from the green (Y) "
            "axis. Turns the base map, the terrain and every geographic "
            "import under the model; the model itself does not move, so its "
            "front/right/top views and axis locks stay square."))
        self._north.editingFinished.connect(self._on_north_edited)
        grid.addWidget(self._north, 8, 1)

        self._straighten = QPushButton(tr("Straighten model on the map"))
        self._straighten.setToolTip(tr(
            "Select the model you turned and dragged onto the site (one "
            "top-level component): it goes back to its own axes and the map "
            "turns under it instead — the north angle and the origin are "
            "set for you, nothing moves on the map."))
        self._straighten.clicked.connect(self._on_straighten)
        grid.addWidget(self._straighten, 9, 0, 1, 2)

        grid.addWidget(QLabel(tr("Zoom:")), 10, 0)
        self._zoom = QSpinBox()
        self._zoom.setRange(1, 21)
        self._zoom.setValue(16)
        self._zoom.valueChanged.connect(self._on_zoom_changed)
        grid.addWidget(self._zoom, 10, 1)

        # Capture area (metres): set by drawing a rectangle in the locator
        # dialog. A square for a site, a long strip for a road. Kept as state,
        # not tray fields (the locator is where you define it).
        self._capture_w = 2400.0
        self._capture_l = 2400.0

        self._find = QPushButton(tr("Search location…"))
        self._find.clicked.connect(self._open_locator)
        grid.addWidget(self._find, 11, 0, 1, 2)

        self._go = QPushButton(tr("Go to location"))
        self._go.clicked.connect(self._go_to)
        grid.addWidget(self._go, 12, 0, 1, 2)

        self._show = QCheckBox(tr("Show base map"))
        self._show.setChecked(True)
        self._show.toggled.connect(self._on_toggle_visible)
        grid.addWidget(self._show, 13, 0, 1, 2)

        # Map opacity: fade the imagery so the model and its lines read on
        # top of it (a plan sheet over the satellite). Document state, lives
        # on the tile layer and travels in the .igz.
        self._opacity = QSlider(Qt.Horizontal)
        style_slider(self._opacity)
        self._opacity.setRange(10, 100)
        self._opacity.setValue(100)
        self._opacity.setToolTip(tr(
            "Map opacity: fade the imagery so the model and its lines read "
            "on top of it"))
        self._opacity.valueChanged.connect(self._on_opacity_changed)
        self._opacity_label = QLabel(tr("Opacity") + " 100 %")
        grid.addWidget(self._opacity_label, 14, 0)
        grid.addWidget(self._opacity, 14, 1)

        self._terrain3d = QCheckBox(tr("3D terrain"))
        self._terrain3d.toggled.connect(self._on_toggle_terrain)
        grid.addWidget(self._terrain3d, 15, 0, 1, 2)

        # The drone survey (Track G, G6). Disabled until one is imported —
        # a checkbox you can tick with nothing behind it just looks broken.
        self._photo_mesh = QCheckBox(tr("Photogrammetric survey"))
        self._photo_mesh.setEnabled(False)
        self._photo_mesh.toggled.connect(self._on_toggle_photo_mesh)
        grid.addWidget(self._photo_mesh, 16, 0, 1, 2)

        # Which layer the survey carries. The import puts it on its own so it
        # can be switched off without taking the model with it; this is for
        # moving it somewhere else (onto an existing "reference" layer, say).
        self._photo_layer = QComboBox()
        self._photo_layer.setEnabled(False)
        self._photo_layer.setToolTip(tr(
            "Layer the survey is on. Hiding that layer hides the survey."))
        self._photo_layer.currentTextChanged.connect(self._on_photo_layer_changed)
        grid.addWidget(QLabel(tr("Layer")), 17, 0)
        grid.addWidget(self._photo_layer, 17, 1)

        self._attribution = QLabel("")
        self._attribution.setWordWrap(True)
        theme_style(self._attribution, "color:{muted}; font-size:10px; margin-top:4px;")
        grid.addWidget(self._attribution, 18, 0, 1, 2)

        self._restore_saved_source()
        self._sync_from_scene()

    # ---- Source -------------------------------------------------------------
    def _current_source(self):
        sid = self._source.currentData()
        if sid in self._custom_entries:
            entry = self._custom_entries[sid]
            return custom_source(entry["url"], max_zoom=self._zoom.maximum(),
                                 name=entry["name"])
        if sid == self._ADD or sid is None:
            return None
        return PRESETS[sid]

    # -- Saved custom sources (QGIS-style: named, permanent, in the menu) -----
    def _load_custom_sources(self) -> list[dict]:
        """``[{"name", "url"}]`` from QSettings. Migrates the short-lived
        single-URL preference (``basemap/custom_url``) into a named entry."""
        import json
        from PySide6.QtCore import QSettings
        settings = QSettings()
        raw = settings.value("basemap/custom_sources", "", type=str)
        entries: list[dict] = []
        if raw:
            try:
                entries = [e for e in json.loads(raw)
                           if isinstance(e, dict)
                           and e.get("name") and e.get("url")]
            except ValueError:
                entries = []
        legacy = settings.value("basemap/custom_url", "", type=str)
        if legacy:
            if not any(e["url"] == legacy for e in entries):
                entries.append({"name": "XYZ personalizado", "url": legacy})
                self._store_custom_sources(entries)
            settings.remove("basemap/custom_url")
        return entries

    @staticmethod
    def _store_custom_sources(entries: list[dict]) -> None:
        import json
        from PySide6.QtCore import QSettings
        settings = QSettings()
        settings.setValue("basemap/custom_sources", json.dumps(entries))
        # Flush NOW: a hand-added source must survive even a crash right
        # after saving (QSettings otherwise buffers until a clean exit).
        settings.sync()

    def _populate_sources(self, select: str | None = None) -> None:
        """Rebuild the combo: presets + every saved custom source (by name)
        + the "Add…" action item. Passive — never kicks a tile reset."""
        from PySide6.QtCore import QSignalBlocker
        from georef.tiles import source_slug
        blocker = QSignalBlocker(self._source)
        wanted = select or self._source.currentData()
        self._source.clear()
        for sid, src in PRESETS.items():
            self._source.addItem(tr(src.name), sid)
        self._custom_entries = {}
        for entry in self._load_custom_sources():
            sid = "custom-" + source_slug(entry["name"])
            self._custom_entries[sid] = entry
            self._source.addItem(entry["name"], sid)
        self._source.addItem(tr("Add XYZ source…"), self._ADD)
        idx = self._source.findData(wanted)
        if idx < 0 or wanted == self._ADD:
            idx = self._source.findData(DEFAULT_SOURCE_ID)
        self._source.setCurrentIndex(idx)
        del blocker
        self._last_sid = self._source.currentData()
        self._refresh_remove_btn()

    def _refresh_remove_btn(self) -> None:
        self._remove_btn.setVisible(
            self._source.currentData() in self._custom_entries)

    def add_custom_source(self, name: str, url: str) -> bool:
        """Save a named XYZ source (upsert by name) and select it. Headless —
        the dialog flow and tests both land here. Returns ``False`` when the
        URL lacks the {z}/{x}/{y} placeholders."""
        from georef.tiles import source_slug
        name = name.strip()
        url = url.strip()
        if not name or not all(k in url for k in ("{z}", "{x}", "{y}")):
            return False
        entries = self._load_custom_sources()
        entries = [e for e in entries
                   if source_slug(e["name"]) != source_slug(name)]
        entries.append({"name": name, "url": url})
        self._store_custom_sources(entries)
        self._populate_sources(select="custom-" + source_slug(name))
        self._save_source_pref()
        self._apply_source()
        return True

    def _on_add_source(self) -> None:
        name, ok = _prompts.get_text(
            self, tr("New XYZ source"), tr("Source name:"))
        if not ok or not name.strip():
            return
        url, ok = _prompts.get_text(
            self, tr("New XYZ source"),
            tr("Tile URL (with {z}/{x}/{y}):"),
            text="https://…/{z}/{x}/{y}.png")
        if not ok:
            return
        if not self.add_custom_source(name, url):
            self._window.statusBar().showMessage(tr(
                "The URL must contain the {z}, {x} and {y} placeholders"),
                5000)
            return
        self._window.statusBar().showMessage(tr(
            "Source '{name}' saved — it will always be in the menu",
            name=name.strip()), 4000)

    def _remove_current_custom(self) -> None:
        from georef.tiles import source_slug
        sid = self._source.currentData()
        entry = self._custom_entries.get(sid)
        if entry is None:
            return
        entries = [e for e in self._load_custom_sources()
                   if source_slug(e["name"]) != source_slug(entry["name"])]
        self._store_custom_sources(entries)
        self._populate_sources(select=DEFAULT_SOURCE_ID)
        self._save_source_pref()
        self._apply_source()

    def _restore_saved_source(self) -> None:
        """Select the source used in the last session (QSettings)."""
        from PySide6.QtCore import QSettings, QSignalBlocker
        sid = QSettings().value("basemap/source", "", type=str)
        if sid and sid != self._ADD:
            idx = self._source.findData(sid)
            if idx >= 0:
                blocker = QSignalBlocker(self._source)
                self._source.setCurrentIndex(idx)
                del blocker
        self._last_sid = self._source.currentData()
        self._refresh_remove_btn()
        src = self._current_source()
        if src is not None:
            self._attribution.setText(src.attribution)

    def _save_source_pref(self) -> None:
        from PySide6.QtCore import QSettings
        sid = self._source.currentData()
        if sid and sid != self._ADD:
            settings = QSettings()
            settings.setValue("basemap/source", sid)
            settings.sync()

    def _on_source_changed(self) -> None:
        if self._source.currentData() == self._ADD:
            # The "Add…" row is an action, not a source: bounce back to the
            # previous selection and open the dialog.
            self._populate_sources(select=self._last_sid)
            self._on_add_source()
            return
        self._last_sid = self._source.currentData()
        self._refresh_remove_btn()
        self._apply_source()

    def _apply_source(self) -> None:
        self._save_source_pref()
        src = self._current_source()
        if src is None:
            return
        self._attribution.setText(src.attribution)
        layer = getattr(self._window.viewport.scene, "tile_layer", None)
        if layer is not None:
            layer.source = src
            self._window.viewport.reset_tiles()

    def _on_zoom_changed(self, z: int) -> None:
        layer = getattr(self._window.viewport.scene, "tile_layer", None)
        if layer is not None:
            layer.zoom = z
            self._window.viewport.reset_tiles()

    # ---- Location -----------------------------------------------------------
    def _on_coord_mode(self, *_a) -> None:
        QSettings().setValue("georef/coord_mode",
                             self._coord_mode.currentData())
        self._apply_coord_mode()

    def _apply_coord_mode(self) -> None:
        utm = self._coord_mode.currentData() == "utm"
        for w in (self._lat_label, self._lat, self._lon_label, self._lon):
            w.setVisible(not utm)
        for w in (self._utm_zone_label, self._utm_zone_row,
                  self._utm_e_label, self._utm_e,
                  self._utm_n_label, self._utm_n):
            w.setVisible(utm)

    def _sync_utm_from_ll(self, *_a) -> None:
        from georef.datum import utm_forward, zone_for_lon
        from PySide6.QtCore import QSignalBlocker
        lat, lon = self._lat.value(), self._lon.value()
        zone = zone_for_lon(lon)
        east, north = utm_forward(lat, lon, zone)
        blockers = [QSignalBlocker(w) for w in
                    (self._utm_zone, self._utm_hemi,
                     self._utm_e, self._utm_n)]
        self._utm_zone.setValue(zone)
        self._utm_hemi.setCurrentIndex(0 if lat >= 0 else 1)
        self._utm_e.setValue(east)
        self._utm_n.setValue(north)
        del blockers

    def _sync_ll_from_utm(self, *_a) -> None:
        from georef.datum import utm_inverse
        from PySide6.QtCore import QSignalBlocker
        lat, lon = utm_inverse(self._utm_e.value(), self._utm_n.value(),
                               int(self._utm_zone.value()),
                               bool(self._utm_hemi.currentData()))
        if not (-85.0 <= lat <= 85.0 and -180.0 <= lon <= 180.0):
            return
        blockers = [QSignalBlocker(w) for w in (self._lat, self._lon)]
        self._lat.setValue(lat)
        self._lon.setValue(lon)
        del blockers

    def _open_locator(self) -> None:
        """Open the map locator; on accept, drop the chosen lat/lon and go."""
        from views.location_dialog import pick_location
        src = self._current_source() or PRESETS[DEFAULT_SOURCE_ID]
        result = pick_location(src, self._lat.value(), self._lon.value(), self)
        if result is not None:
            lat, lon, width_m, length_m = result
            self._lat.setValue(lat)
            self._lon.setValue(lon)
            self._sync_utm_from_ll()
            if width_m and length_m:      # a capture rectangle was drawn
                self._capture_w = width_m
                self._capture_l = length_m
            self._go_to()

    def _go_to(self) -> None:
        src = self._current_source()
        if src is None:
            return
        scene = self._window.viewport.scene
        old_datum = getattr(scene, "georef", None)
        moved = (old_datum is not None
                 and (abs(old_datum.lat - self._lat.value()) > 1e-9
                      or abs(old_datum.lon - self._lon.value()) > 1e-9))
        if moved:
            # Moving the anchor relocates everything drawn (the model keeps
            # its LOCAL coordinates) — never do that silently.
            answer = QMessageBox.question(
                self, tr("Move the project origin?"),
                tr("This project already has a location. Moving it makes "
                   "the new point the model's origin (0,0): everything "
                   "drawn keeps its local coordinates and shows up at the "
                   "new spot on the map.\n\nMove the origin?"))
            if answer != QMessageBox.Yes:
                return
        if old_datum is not None and not moved:
            datum = old_datum          # keep the datum (and its altitude)
        else:
            # The altitude reference (e.g. a drone survey's foot elevation)
            # only survives a NEARBY adjustment; carrying it to a distant
            # site would misplace tiles/terrain by the sites' elevation
            # difference — the classic invisible-in-top-view Z error.
            keep_alt = 0.0
            if old_datum is not None:
                import math as _math
                dlat = (self._lat.value() - old_datum.lat) * 111320.0
                dlon = ((self._lon.value() - old_datum.lon) * 111320.0
                        * _math.cos(_math.radians(self._lat.value())))
                if _math.hypot(dlat, dlon) < 1000.0:
                    keep_alt = old_datum.alt
            # The north set with Tools ▸ North before there was a location
            # (or the old datum's) is how the model is drawn on its site:
            # it carries over, the sun does not jump.
            from core.sun import scene_north_deg
            datum = SceneDatum(self._lat.value(), self._lon.value(),
                               alt=keep_alt, north=scene_north_deg(scene))
        scene.georef = datum
        layer = TileLayer(src, zoom=self._zoom.value())
        layer.set_rectangle(self._capture_w, self._capture_l)
        # Guard: a very large capture is capped in detail so it stays bounded.
        if layer.cap_detail(datum, max_tiles=500):
            self._window.viewport.flash_status(tr(
                "Large capture — detail reduced to zoom {z} to stay fast.")
                .format(z=layer.zoom))
        layer.visible = self._show.isChecked()
        # A new capture keeps the terrain as it was (3D or flat).
        layer.terrain3d = bool(getattr(self._window, "_terrain_on", False))
        scene.tile_layer = layer
        self._attribution.setText(src.attribution)
        self._window.viewport.reset_tiles()
        self._frame_camera(max(self._capture_w, self._capture_l) / 2.0)

    def setup_for_import(self, datum, geo_paths) -> None:
        """After a georef import: anchor the base map at the imported data with a
        reference capture covering it, so 'Show base map' verifies the location."""
        from PySide6.QtCore import QSignalBlocker
        src = self._current_source() or PRESETS[DEFAULT_SOURCE_ID]
        scene = self._window.viewport.scene
        pts = [p for gp in geo_paths for p in gp.points]
        if not pts:
            return
        minx = min(p.x() for p in pts)
        maxx = max(p.x() for p in pts)
        miny = min(p.y() for p in pts)
        maxy = max(p.y() for p in pts)
        self._capture_around(src, scene, datum, minx, miny, maxx, maxy)

    def setup_for_bounds(self, datum, lo, hi) -> None:
        """Same, from a plain local-metre bounding box.

        A photogrammetric survey has no ``geo_paths`` to measure — its extent is
        the mesh itself. Without this the base map keeps whatever capture it had
        (a 1200 m square at the origin, by default), which for a flight a few
        hundred metres away reads as "the imagery doesn't line up" when in fact
        it was simply never fetched for that ground.
        """
        src = self._current_source() or PRESETS[DEFAULT_SOURCE_ID]
        scene = self._window.viewport.scene
        self._capture_around(src, scene, datum,
                             lo.x(), lo.y(), hi.x(), hi.y())

    def _capture_around(self, src, scene, datum, minx, miny, maxx, maxy) -> None:
        from PySide6.QtCore import QSignalBlocker
        margin = 0.15 * max(maxx - minx, maxy - miny, 200.0)
        cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
        self._capture_w = (maxx - minx) + 2 * margin
        self._capture_l = (maxy - miny) + 2 * margin
        layer = TileLayer(src, zoom=self._zoom.value())
        layer.set_rectangle(self._capture_w, self._capture_l, cx=cx, cy=cy)
        layer.cap_detail(datum, max_tiles=500)
        layer.visible = self._show.isChecked()
        layer.terrain3d = bool(getattr(self._window, "_terrain_on", False))
        scene.tile_layer = layer
        self._attribution.setText(src.attribution)
        blockers = [QSignalBlocker(w) for w in (self._lat, self._lon)]
        self._lat.setValue(datum.lat)
        self._lon.setValue(datum.lon)
        del blockers
        self._sync_utm_from_ll()
        self._window.viewport.reset_tiles()

    def _frame_camera(self, radius: float) -> None:
        from PySide6.QtGui import QVector3D
        vp = self._window.viewport
        vp.camera.set_view("top")
        vp.camera.fit_to(QVector3D(-radius, -radius, 0.0),
                         QVector3D(radius, radius, 0.0))
        vp.update()

    # ---- North angle ----------------------------------------------------------
    def _on_north_edited(self) -> None:
        """Retarget the datum's north angle: a NEW datum object (the tile
        geometry is cached by datum identity), tiles and terrain rebuilt."""
        vp = self._window.viewport
        scene = vp.scene
        datum = getattr(scene, "georef", None)
        if datum is None:
            return
        value = self._north.value()
        if abs(value - getattr(datum, "north", 0.0)) < 1e-9:
            return
        scene.georef = SceneDatum(datum.lat, datum.lon, alt=datum.alt,
                                  north=value)
        scene.version += 1
        self._refresh_map()

    def _refresh_map(self) -> None:
        """The datum changed under the map: drop tile geometry, redo the
        terrain if it is on, repaint."""
        vp = self._window.viewport
        vp.reset_tiles()
        if getattr(self._window, "_terrain_on", False):
            self._window._build_terrain()
        vp.notify_scene_changed()

    def _on_straighten(self) -> None:
        """Undo the turn+drag placement of the selected model by turning the
        map instead (StraightenModelCommand); one undo step."""
        from core.history import StraightenModelCommand, placement_is_identity
        vp = self._window.viewport
        scene = vp.scene
        groups = [g for g in scene.selection
                  if isinstance(g, Group) and g in scene.groups]
        if not groups and len(scene.groups) == 1 and not scene.mesh.faces:
            groups = list(scene.groups)      # the whole model is one component
        if len(groups) != 1 or groups[0].xform is None:
            QMessageBox.information(
                self, tr("Straighten model on the map"),
                tr("Select the placed model: one top-level component (the "
                   "group you turned and dragged onto the site)."))
            return
        if getattr(scene, "georef", None) is None:
            QMessageBox.information(
                self, tr("Straighten model on the map"),
                tr("Set a location first (Go to location)."))
            return
        if placement_is_identity(groups[0].xform):
            # Nothing to take out of this placement — the user picked the
            # wrong group (the DWG instead of the plaza he turned: eleven
            # silent no-ops, Marco 2026-09-14).
            QMessageBox.information(
                self, tr("Straighten model on the map"),
                tr("“{name}” is not turned or moved. Select the model you "
                   "turned and dragged onto the site.",
                   name=groups[0].name))
            return
        cmd = StraightenModelCommand(groups[0])
        vp.history.execute(cmd)
        if vp.history.last_error:
            QMessageBox.warning(self, tr("Straighten model on the map"),
                                tr("Could not straighten: {error}",
                                   error=vp.history.last_error))
            return
        # Keep looking at the same thing: the camera rides the same transform.
        import math
        w, ok = cmd._placement.inverted()
        if ok:
            cam = vp.camera
            cam.target = w.map(cam.target)
            cam.yaw = cam.yaw - math.radians(cmd.degrees)
        self._sync_from_scene()
        self._refresh_map()
        vp.flash_status(tr("Model straightened: north angle {deg}°",
                           deg=f"{scene.georef.north:.2f}"))

    def _on_toggle_visible(self, on: bool) -> None:
        layer = getattr(self._window.viewport.scene, "tile_layer", None)
        if layer is not None:
            layer.visible = on
            self._window.viewport.update()

    def _on_opacity_changed(self, value: int) -> None:
        self._opacity_label.setText(tr("Opacity") + f" {value} %")
        layer = getattr(self._window.viewport.scene, "tile_layer", None)
        if layer is not None:
            layer.opacity = value / 100.0
            self._window.viewport.update()

    def _on_toggle_terrain(self, on: bool) -> None:
        self._window.set_terrain_enabled(on)

    def _on_toggle_photo_mesh(self, on: bool) -> None:
        mesh = getattr(self._window.viewport.scene, "photo_mesh", None)
        if mesh is None:
            return
        mesh.visible = on
        self._window.viewport.update()

    def _on_photo_layer_changed(self, name: str) -> None:
        mesh = getattr(self._window.viewport.scene, "photo_mesh", None)
        if mesh is None or not name:
            return
        from core.layers import DEFAULT_LAYER
        mesh.layer = None if name == DEFAULT_LAYER else name
        self._window.viewport.update()

    def sync_photo_mesh(self) -> None:
        """Enable the survey controls after an import (or on load)."""
        from PySide6.QtCore import QSignalBlocker
        from core.layers import DEFAULT_LAYER
        scene = self._window.viewport.scene
        mesh = getattr(scene, "photo_mesh", None)
        with QSignalBlocker(self._photo_mesh):
            self._photo_mesh.setEnabled(mesh is not None)
            self._photo_mesh.setChecked(mesh is not None
                                        and getattr(mesh, "visible", False))
        with QSignalBlocker(self._photo_layer):
            self._photo_layer.clear()
            self._photo_layer.setEnabled(mesh is not None)
            if mesh is None:
                return
            self._photo_layer.addItems([ly.name for ly in scene.layers])
            current = getattr(mesh, "layer", None) or DEFAULT_LAYER
            index = self._photo_layer.findText(current)
            if index >= 0:
                self._photo_layer.setCurrentIndex(index)

    def sync_from_document(self) -> None:
        """After opening a document: mirror its base map into the panel AND
        fetch the tiles for the capture it carries.

        The passive sync alone is not enough on open — the layer is restored
        with an empty image cache, so without kicking the fetcher the panel
        claims a visible base map over an empty scene.
        """
        self._sync_from_scene()
        layer = getattr(self._window.viewport.scene, "tile_layer", None)
        if layer is not None:
            self._window.viewport.reset_tiles()
            # Saved with the 3D terrain on: build it again (it is display
            # only, never in the file; it fills in as the elevation arrives).
            if getattr(layer, "terrain3d", False):
                self._window._build_terrain()
            self._window.viewport.update()

    def _sync_from_scene(self) -> None:
        """Reflect a datum/layer already on the scene (e.g. loaded from .igz).

        Widgets are updated with signals blocked so this passive sync never
        kicks off a tile reset or a camera move — it only mirrors state.
        """
        from PySide6.QtCore import QSignalBlocker
        scene = self._window.viewport.scene
        datum = getattr(scene, "georef", None)
        layer = getattr(scene, "tile_layer", None)
        blockers = [QSignalBlocker(w) for w in
                    (self._source, self._lat, self._lon, self._zoom, self._show,
                     self._north, self._terrain3d, self._photo_mesh,
                     self._opacity)]
        # A scene recalls the terrain / survey visibility too: keep the
        # boxes honest (an unchecked box over a hidden terrain re-shows it).
        terrain = getattr(scene, "terrain", None)
        hidden = terrain is not None and not getattr(terrain, "visible", True)
        self._terrain3d.setChecked(
            bool(getattr(self._window, "_terrain_on", False)) and not hidden)
        mesh = getattr(scene, "photo_mesh", None)
        if mesh is not None:
            self._photo_mesh.setChecked(getattr(mesh, "visible", False))
        if datum is not None:
            self._lat.setValue(datum.lat)
            self._lon.setValue(datum.lon)
            self._north.setValue(getattr(datum, "north", 0.0))
            self._sync_utm_from_ll()
        if layer is not None:
            idx = self._source.findData(layer.source.id)
            if idx >= 0:
                self._source.setCurrentIndex(idx)
            self._zoom.setValue(layer.zoom)
            self._show.setChecked(layer.visible)
            pct = int(round(100 * float(getattr(layer, "opacity", 1.0))))
            self._opacity.setValue(pct)
            self._opacity_label.setText(tr("Opacity") + f" {pct} %")
            self._attribution.setText(layer.source.attribution)
        else:
            self._attribution.setText(self._current_source().attribution
                                      if self._current_source() else "")
        del blockers  # release the signal blockers
        self._refresh_remove_btn()

    def on_scene_changed(self) -> None:
        self._sync_from_scene()


class ComponentsPanel(QWidget):
    """Components tray: a grid of clickable thumbnails.

    The thumbnails are STATIC images — the 2D people are their own PNGs and
    the 3D starters ship pre-rendered PNGs in ``resources/components/thumbs``
    (regenerate with the dev script if the models change) — so showing the
    panel costs a handful of pixmap loads and never touches the GL renderer."""

    COLS = 3
    #: Rows from which the «In model» list offers its name filter.
    FILTER_FROM = 8

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtGui import QIcon
        self._window = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        grid = FlowLayout(spacing=4)
        res = app_root() / "resources" / "components"
        import json as _json
        items = []
        # The 2D people are data too: resources/components/people.json lists
        # key/name/tip and the REAL height each one stands, which is the whole
        # point of a scale figure — <key>.png is the cutout, cropped tight so
        # the height it is given is the height it reads.
        people = res / "people.json"
        if people.exists():
            for entry in _json.loads(people.read_text(encoding="utf-8")):
                items.append(
                    (res / f"{entry['key']}.png", tr(entry["name"]),
                     tr(entry.get("tip", entry["name"])),
                     lambda _c=False, k=entry["key"], h=entry["height"],
                     n=entry["name"]:
                         window._on_insert_person_2d(f"{k}.png", h, n)))
        # The 3D starters are data: resources/components/components.json
        # lists key/name/tip; the model is <key>.glb (Sketchfab CC-BY set,
        # see SOURCES.md) with a pre-rendered thumbs/<key>.png.
        manifest = res / "components.json"
        if manifest.exists():
            for entry in _json.loads(manifest.read_text(encoding="utf-8")):
                items.append(
                    (res / "thumbs" / f"{entry['key']}.png",
                     tr(entry["name"]), tr(entry.get("tip", entry["name"])),
                     lambda _c=False, k=entry["key"], n=entry["name"]:
                         window._on_insert_component(k, tr(n))))
        for i, (icon_path, label, tip, callback) in enumerate(items):
            btn = QToolButton()
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIcon(QIcon(str(icon_path)))
            btn.setIconSize(QSize(56, 56))
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            btn.setMinimumWidth(72)
            btn.clicked.connect(callback)
            grid.addWidget(btn, i // self.COLS, i % self.COLS)
        lay.addLayout(grid)
        # The bundled grid is a handful; the rest of the catalogue lives
        # online and is browsed from here (see core/library.py).
        more = QPushButton(tr("More components…"))
        more.setToolTip(tr(
            "Browse the online library and download a model as a component"))
        more.clicked.connect(window._on_open_library)
        lay.addWidget(more)
        custom = QPushButton(tr("Face-me image (PNG)…"))
        custom.setToolTip(tr(
            "Insert your own cutout PNG at real height, always facing "
            "the camera"))
        custom.clicked.connect(window._on_insert_faceme_image)
        lay.addWidget(custom)

        # "In model": what THIS drawing contains, the way a components
        # tray usually lists it. The grid above is a library to insert
        # from; it says nothing about what you already have, which is what
        # you actually look for when you want to find or re-place a piece.
        lay.addWidget(QLabel(f"<b>{tr('In model')}</b>"))
        # A long list is searched by name rather than scrolled (the list
        # «can get quite big», PR #4 review). Only shown once it is long.
        self._in_model_filter = QLineEdit()
        self._in_model_filter.setPlaceholderText(tr("Filter by name…"))
        self._in_model_filter.setClearButtonEnabled(True)
        self._in_model_filter.textChanged.connect(self._apply_in_model_filter)
        lay.addWidget(self._in_model_filter)
        self._in_model = QListWidget()
        self._in_model.setToolTip(tr(
            "Components placed in this drawing — click one to select its "
            "copies"))
        self._in_model.itemClicked.connect(self._select_component)
        # Each row shows what the component looks like
        # (views/component_thumbs.py), not only its name.
        from views.component_thumbs import SIZE as _THUMB
        self._in_model.setIconSize(QSize(_THUMB, _THUMB))
        # Right-click a row: the same two moves the viewport's menu offers,
        # from the list — which is where a long one is searched anyway.
        self._in_model.setContextMenuPolicy(Qt.CustomContextMenu)
        self._in_model.customContextMenuRequested.connect(
            self._in_model_menu)
        # Pictures are drawn for the rows on screen only: a plant of 1 815
        # components drew all of them at every refresh (#158).
        self._in_model.verticalScrollBar().valueChanged.connect(
            self._schedule_thumbs)
        lay.addWidget(self._in_model)
        # The definitions of another document, kept here unplaced: a
        # library drawn from a file of one's own.
        from_file = QPushButton(tr("Components from File…"))
        from_file.setToolTip(tr(
            "Add the components of another IngeTrazo document to this "
            "list, kept in the file and ready to place or swap in"))
        from_file.clicked.connect(window._on_components_from_file)
        lay.addWidget(from_file)
        self.refresh_in_model()

    def _components_in_model(self) -> list:
        """``[(name, faces, [groups], template)]`` per distinct prototype,
        most copies first. Instances share their prototype mesh, so identity
        groups them — no geometry is walked. Copies nested inside groups
        count too: one put into a group from the Browser used to drop off
        the list (#599, @chakkreetiya). ``template`` is the definition
        kept in the file (``None`` when it is not kept); a kept one with no
        copy placed is a row too, with an empty list."""
        from core.kept_components import kept_template
        from core.purge import iter_groups
        scene = self._window.viewport.scene
        by_proto: dict = {}
        for g in iter_groups(scene.groups):
            if not g.is_component() or getattr(g, "billboard", False):
                continue
            by_proto.setdefault(id(g.mesh), []).append(g)
        from core.mesh import face_count
        rows = [(gs[0].name, face_count(gs[0].mesh), gs,
                 kept_template(scene, gs[0].mesh))
                for gs in by_proto.values()]
        rows += [(t.name, face_count(t.mesh), [], t)
                 for t in getattr(scene, "kept_components", None) or ()
                 if id(t.mesh) not in by_proto]
        rows.sort(key=lambda r: (-len(r[2]), (r[0] or "").lower()))
        return rows

    def on_scene_changed(self) -> None:
        """The tray's per-change call. The «In model» list reads every
        definition's signature (its faces and paint) to know whether its
        thumbnail changed: on the Plaza that was +20 ms on every edit, its
        section folded or its tab hidden (release_check, 09-10). Refreshed
        now when on screen, on showing otherwise — like the Browser. A
        window not shown yet (scripts, tests) refreshes at once, as before.

        A change of the view alone (a selection, a group opened) leaves the
        list as it is and only marks the selected row: on the plant of #158
        every click rebuilt it — 0.1 s of ~1 s per click."""
        cv = self._window.viewport.scene.content_version
        if (cv == getattr(self, "_in_model_cv", None)
                and not getattr(self, "_in_model_stale", False)
                and self._in_model.count()):
            self._mark_selected_row()
            return
        if not self._window.isVisible():
            self.refresh_in_model()
            return
        if not self.isVisible():
            if not getattr(self, "_in_model_stale", False):
                # Its rows hold the groups they list: kept while it waits,
                # they held a whole previous document in memory after
                # Open (+130 MB on the Plaza, release_check 10-10).
                self._in_model.clear()
            self._in_model_stale = True
            return
        # On screen: one refresh 300 ms after the last edit, as Materials
        # does — a burst of edits (arrows, repeated pushes) pays it once.
        timer = getattr(self, "_in_model_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._in_model_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.refresh_in_model)
        timer.start(300)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if getattr(self, "_in_model_stale", False):
            self._in_model_stale = False
            self.refresh_in_model()

    def refresh_in_model(self) -> None:
        from views.component_thumbs import thumbnail
        self._in_model_cv = self._window.viewport.scene.content_version
        rows = self._components_in_model()

        def label_of(name, faces, gs, kept):
            label = (f"{name}  ({len(gs)}×, {faces} " + tr("Faces").lower()
                     + ")")
            if kept is not None:
                label += "  · " + tr("kept")
            return label

        def ident(gs, kept):
            d = gs[0] if gs else kept
            return id(d.mesh) if d is not None else None
        # The same definitions in the same order (a copy deleted or pasted:
        # one count changes): the rows are brought up to date where they
        # are. Emptied and filled again, the list of 1 815 laid the whole
        # tray out again, ~0.3 s after each edit on the plant of #158.
        lst = self._in_model
        if (rows and lst.count() == len(rows)
                and all(ident(lst.item(i).data(Qt.UserRole) or [],
                              lst.item(i).data(Qt.UserRole + 1))
                        == ident(r[2], r[3]) for i, r in enumerate(rows))):
            # Only what differs is set: each change of a row makes the
            # list lay all of them out again.
            for i, (name, faces, gs, kept) in enumerate(rows):
                item = lst.item(i)
                label = label_of(name, faces, gs, kept)
                if item.text() != label:
                    item.setText(label)
                old = item.data(Qt.UserRole) or []
                if len(old) != len(gs) or any(a is not b
                                              for a, b in zip(old, gs)):
                    item.setData(Qt.UserRole, gs)
                if item.data(Qt.UserRole + 1) is not kept:
                    item.setData(Qt.UserRole + 1, kept)
            self._mark_selected_row()
            self._apply_in_model_filter()
            return
        self._in_model.clear()
        for name, faces, gs, kept in rows:
            item = QListWidgetItem(label_of(name, faces, gs, kept))
            item.setIcon(self._blank_thumb())
            item.setData(Qt.UserRole, gs)
            item.setData(Qt.UserRole + 1, kept)
            self._in_model.addItem(item)
        if self._in_model.count() == 0:
            self._in_model.addItem(QListWidgetItem(tr("No components yet")))
        self._mark_selected_row()
        self._in_model_filter.setVisible(
            self._in_model.count() >= self.FILTER_FROM
            or bool(self._in_model_filter.text()))
        self._apply_in_model_filter()
        self._schedule_thumbs()

    def _blank_thumb(self) -> QIcon:
        icon = getattr(self, "_blank_icon", None)
        if icon is None:
            from views.component_thumbs import SIZE as _THUMB
            pm = QPixmap(_THUMB, _THUMB)
            pm.fill(Qt.transparent)
            icon = self._blank_icon = QIcon(pm)
        return icon

    def _schedule_thumbs(self, _value=None) -> None:
        """Draw the pictures of the rows now on screen, once the list has
        laid itself out (a scroll, a refresh, a filter, a resize)."""
        timer = getattr(self, "_thumbs_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._thumbs_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._draw_visible_thumbs)
        timer.start(0)

    def _draw_visible_thumbs(self) -> None:
        from views.component_thumbs import thumbnail
        lst = self._in_model
        area = lst.viewport().rect()
        # From the first row on screen down to the last: asking every row
        # of 1 815 for its place took ~0.15 s after each edit (#158).
        first = lst.indexAt(area.topLeft()).row()
        for i in range(max(first, 0), lst.count()):
            item = lst.item(i)
            if item.isHidden():
                continue
            rect = lst.visualItemRect(item)
            if rect.top() > area.bottom():
                break
            if not rect.intersects(area):
                continue
            groups = item.data(Qt.UserRole) or []
            definition = groups[0] if groups else item.data(Qt.UserRole + 1)
            if definition is None:
                continue
            # The picture (from the cache while the definition is as it
            # was) is set when it is not the one the row shows already.
            pm = thumbnail(definition)
            if item.data(Qt.UserRole + 2) != pm.cacheKey():
                item.setIcon(QIcon(pm))
                item.setData(Qt.UserRole + 2, pm.cacheKey())

    def _mark_selected_row(self) -> None:
        """Light the row whose instances are what the model has selected.

        A click on a row selects its instances, the selection bumps the
        scene, and the refresh that follows rebuilt the list -- the row lit
        for a fraction of a second and went dark (#636). Read from the
        selection, the highlight also goes when the selection does."""
        selected = {id(e) for e in self._window.viewport.scene.selection}
        for i in range(self._in_model.count()):
            item = self._in_model.item(i)
            groups = item.data(Qt.UserRole) or []
            if selected and {id(g) for g in groups} == selected:
                self._in_model.setCurrentItem(item)
                return
        self._in_model.setCurrentItem(None)

    def _apply_in_model_filter(self, _text=None) -> None:
        """Hide the rows whose name does not hold the filter text (any
        case, accents as typed). The list keeps its rows; only their
        visibility changes, so a refresh does not lose the filter."""
        needle = self._in_model_filter.text().strip().casefold()
        for i in range(self._in_model.count()):
            item = self._in_model.item(i)
            groups = item.data(Qt.UserRole) or []
            kept = item.data(Qt.UserRole + 1)
            definition = groups[0] if groups else kept
            name = (definition.name or "") if definition is not None else ""
            item.setHidden(bool(needle) and definition is not None
                           and needle not in name.casefold())
        fit_rows(self._in_model, max_rows=12)
        self._schedule_thumbs()

    def _select_component(self, item) -> None:
        groups = item.data(Qt.UserRole)
        if groups:
            self._select_groups(groups)

    def _in_model_actions(self, groups, kept=None) -> list:
        """``[(text, callback, checked, tip)]`` for a row of the «In model»
        list — its right-click menu, kept apart so it can be read without
        opening one. ``callback`` None = shown greyed; ``checked`` None =
        not a check entry; ``tip`` None = no tooltip."""
        from core.kept_components import make_template, place_copy
        definition = kept if kept is not None else groups[0]
        swap = [g for g in self._window.viewport.scene.selection
                if isinstance(g, Group) and g.is_component()
                and g.mesh is not definition.mesh]
        out = [(tr("Select Instances ({n})", n=len(groups)),
                (lambda: self._select_groups(groups)) if groups else None,
                None, None)]
        if swap:
            out.append((tr("Replace {n} Selected with This", n=len(swap)),
                        lambda: self._window.replace_selection_with(
                            definition), None, None))
        else:
            out.append((tr("Replace Selection with This"), None, None,
                        tr("Select the instances of another component in "
                           "the model first")))
        out.append((tr("Place a Copy"),
                    lambda: self._window._start_place(place_copy(
                        kept if kept is not None
                        else make_template(definition))), None, None))
        out.append((tr("Keep in File"),
                    lambda: self._window.keep_component(
                        definition, kept is None), kept is not None,
                    tr("Keep this definition in the file even with no copy "
                       "placed, to place it or swap copies for it later")))
        out.append((tr("Rename…"),
                    lambda: self._window.rename_component(definition),
                    None, tr("Renames every copy of this component")))
        return out

    def _in_model_menu(self, pos) -> None:
        item = self._in_model.itemAt(pos)
        if item is None:
            return
        groups = item.data(Qt.UserRole) or []
        kept = item.data(Qt.UserRole + 1)
        if not groups and kept is None:
            return                          # «No components yet»
        menu = QMenu(self._in_model)
        menu.setToolTipsVisible(True)
        for text, callback, checked, tip in self._in_model_actions(
                groups, kept):
            act = menu.addAction(text)
            if checked is not None:
                act.setCheckable(True)
                act.setChecked(checked)
            if tip:
                act.setToolTip(tip)
            if callback is None:
                act.setEnabled(False)
            else:
                act.triggered.connect(lambda _c=False, cb=callback: cb())
        menu.exec(self._in_model.viewport().mapToGlobal(pos))

    def _select_groups(self, groups) -> None:
        """Select the copies. The view selects inside ONE open group, so
        when they sit in several, the group holding most of them opens (the
        one already open wins a tie, then the first in the model) and those
        are selected; the status bar says how many are left elsewhere."""
        from core import outliner
        from views.outliner import open_to
        vp = self._window.viewport
        scene = vp.scene
        by_path: dict = {}
        for g in groups:
            path = outliner.path_to(scene.groups, g)
            if path is not None:
                by_path.setdefault(tuple(id(p) for p in path),
                                   (path, []))[1].append(g)
        if not by_path:
            return
        here = tuple(id(p) for p in outliner.open_path(scene))
        path, picks = max(by_path.values(), key=lambda pg: (
            len(pg[1]), tuple(id(p) for p in pg[0]) == here))
        if not open_to(vp, path):
            vp.flash_status(tr(
                "A group around it is hidden or locked: show or unlock "
                "it to select inside"), 3500)
            return
        others = len(groups) - len(picks)
        picks = [g for g in picks if scene.entity_selectable(g)]
        scene.selection.clear()
        scene.selection.update(picks)
        scene.bump_view()
        vp.update()
        self._window.statusBar().showMessage(
            tr("{n} entities selected", n=len(picks)) if not others
            else tr("{n} copies selected; {m} more are inside other groups",
                    n=len(picks), m=others), 4000)


class PartsPanel(QWidget):
    """The parts of the selected component — an outliner, one level
    deep, measured like a cut list.

    Select a component made of parts (an imported model, or one regrouped
    with Split into Pieces) and every part is a row: its name, the material
    most of it wears and its size as length × width × thickness. Clicking a
    row opens the component and selects that part, as double-clicking into
    it would; the check shows or hides it; the name edits in place. Copy
    cut list puts the parts on the clipboard as a table, identical parts
    counted once with their quantity."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QPushButton,
                                       QTreeWidget, QVBoxLayout)
        self._window = window
        self._updating = False
        self._container = None
        self._rows: list = []
        self._cache: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self._title = QLabel()
        self._title.setWordWrap(True)
        lay.addWidget(self._title)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("Name"), tr("Size"), tr("Material")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 110)
        self.tree.setColumnWidth(1, 130)
        self.tree.setToolTip(tr(
            "Click a part to select it inside the component; the check "
            "shows or hides it. To rename: double-click the name, press F2, "
            "or right-click ▸ Rename"))
        from PySide6.QtWidgets import QAbstractItemView
        self.tree.setEditTriggers(QAbstractItemView.DoubleClicked
                                  | QAbstractItemView.EditKeyPressed
                                  | QAbstractItemView.SelectedClicked)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self._items: list = []          # one per part, in the tree's order
        self._shown_selection: tuple = ()
        # «All parts visible»: checked when none is hidden, partial when
        # some are — a click shows every part (or hides them all when all
        # already show).
        self._all_visible = QCheckBox(tr("All parts visible"))
        self._all_visible.setTristate(True)
        self._all_visible.clicked.connect(self._on_all_visible)
        lay.addWidget(self._all_visible)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        self._split_btn = QPushButton(tr("Split into Pieces"))
        self._split_btn.setToolTip(tr(
            "Regroup the component by the solids that do not touch"))
        self._split_btn.clicked.connect(self._on_split)
        self._copy_btn = QPushButton(tr("Copy cut list"))
        self._copy_btn.setToolTip(tr(
            "Copy the parts as a table (quantity, parts, material, length, "
            "width, thickness) — pastes into a spreadsheet"))
        self._copy_btn.clicked.connect(self._on_copy)
        row.addWidget(self._split_btn)
        row.addStretch(1)
        row.addWidget(self._copy_btn)
        lay.addLayout(row)
        self._by_material, by_material_row = _wrapping_check(
            tr("Count identical parts only when the material matches too"))
        self._by_material.setChecked(True)
        lay.addWidget(by_material_row)

        # Exploded view (core/explode.py): the parts pulled apart from the
        # assembly's centre. Dragging previews live and lands as ONE undo
        # step on release.
        from PySide6.QtWidgets import QComboBox, QSlider, QWidget as _W
        self._explode_box = _W()
        ex = QVBoxLayout(self._explode_box)
        ex.setContentsMargins(0, 6, 0, 0)
        ex.addWidget(QLabel(f"<b>{tr('Exploded view')}</b>"))
        top = QHBoxLayout()
        self._explode_mode = QComboBox()
        for key, label in (("outward", tr("Outward")),
                           ("z", tr("Along blue (up)")),
                           ("x", tr("Along red")),
                           ("y", tr("Along green"))):
            self._explode_mode.addItem(label, key)
        self._explode_mode.setToolTip(tr(
            "Which way the parts move away from the assembly's centre"))
        self._explode_mode.currentIndexChanged.connect(self._on_explode_mode)
        self._reassemble_btn = QPushButton(tr("Reassemble"))
        self._reassemble_btn.setToolTip(tr(
            "Put every part back where it sits assembled (a part you moved "
            "by hand keeps that move)"))
        self._reassemble_btn.clicked.connect(self._on_reassemble)
        top.addWidget(self._explode_mode, 1)
        top.addWidget(self._reassemble_btn)
        ex.addLayout(top)
        slide = QHBoxLayout()
        self._explode_slider = QSlider(Qt.Horizontal)
        style_slider(self._explode_slider)
        self._explode_slider.setRange(0, 300)
        self._explode_slider.setSingleStep(5)
        self._explode_slider.setPageStep(25)
        self._explode_slider.setToolTip(tr(
            "How far apart: 100% puts every part twice as far from the "
            "centre as it sits assembled"))
        self._explode_value = QLabel("0%")
        self._explode_value.setMinimumWidth(36)
        self._explode_slider.sliderPressed.connect(self._on_explode_press)
        self._explode_slider.valueChanged.connect(self._on_explode_value)
        self._explode_slider.sliderReleased.connect(self._on_explode_release)
        slide.addWidget(self._explode_slider, 1)
        slide.addWidget(self._explode_value)
        ex.addLayout(slide)
        lay.addWidget(self._explode_box)
        self._drag = None           # (container, snapshot, centres) mid-drag
        self.refresh()

    # ---- Model → view --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def container(self):
        """The component whose parts are listed: the one selected, or the
        one open for editing while you work among its parts."""
        from core.group import Group
        scene = self._scene()
        groups = [g for g in scene.selection if isinstance(g, Group)]
        if len(groups) == 1 and groups[0].children:
            return groups[0]
        edit = scene.edit_group
        if edit is not None and getattr(edit, "children", None):
            return edit
        if len(groups) == 1:
            return groups[0]            # a plain group: offer Split
        return None

    def _row(self, part, shared=None) -> dict:
        """``part``'s row, measured once per version of its geometry — a
        tray refresh follows every edit, and a part is only re-measured
        when it itself changed. ``shared`` is one refresh's cache: the
        parts that are copies of one definition read it once."""
        from core.group import iter_placements
        from core.parts import part_row
        sig = tuple(
            (id(g.mesh), getattr(g.mesh, "_mut_serial", 0),
             tuple(m.data()) if m is not None else None,
             id(getattr(g, "material", None)))
            for g, m in iter_placements(part))
        hit = self._cache.get(id(part))
        if hit is not None and hit[0] == sig:
            row = hit[1]
        else:
            row = part_row(part, shared)
            self._cache[id(part)] = (sig, row)
        row = dict(row)
        row["name"] = part.name
        row["hidden"] = bool(getattr(part, "hidden", False))
        return row

    def refresh(self) -> None:
        """Bring the list up to date — IN PLACE when the component and its
        parts are the ones already listed. Rebuilding on every change threw
        the list back to its top after each click (a part below the
        fourteenth row scrolled out from under the pointer) and killed a
        rename half-typed; only a different component, or a different set
        of parts, rebuilds."""
        from PySide6.QtWidgets import QAbstractItemView, QTreeWidgetItem
        from core.parts import is_surface
        from core.units import fmt_len_fine, fmt_triple
        if self.tree.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        self._updating = True
        cont = self._container = self.container()
        kids = list(getattr(cont, "children", None) or ())
        alive = {id(k) for k in kids}
        for key in [k for k in self._cache if k not in alive]:
            del self._cache[key]
        shared: dict = {}
        self._rows = [self._row(k, shared) for k in kids]
        listed = [it.data(0, Qt.UserRole) for it in self._items]
        if len(listed) != len(kids) or any(a is not b
                                           for a, b in zip(listed, kids)):
            self.tree.clear()
            self._items = []
            self._shown_selection = ()
            for row in self._rows:
                item = QTreeWidgetItem(["", "", ""])
                item.setData(0, Qt.UserRole, row["part"])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable
                              | Qt.ItemIsEditable)
                self.tree.addTopLevelItem(item)
                self._items.append(item)
        for item, row in zip(self._items, self._rows):
            if is_surface(row["size"]):
                # No thickness: a skin, a decal, a pane drawn as one plane.
                # Kept — it is what the model shows — but not read as a
                # board with a thickness of 0.
                length, width = row["size"][:2]
                size = tr("{area} — surface", area=(
                    f"{fmt_len_fine(length)} × {fmt_len_fine(width)}"))
                item.setToolTip(1, tr(
                    "No thickness: a surface drawn as a single plane (a "
                    "skin, a decal, a glass pane). It stays in the model; "
                    "the cut list marks it as a surface."))
            else:
                size = fmt_triple(*row["size"], fine=True)
                item.setToolTip(1, "")
            for col, text in enumerate((row["name"], size, row["material"])):
                if item.text(col) != text:
                    item.setText(col, text)
            state = Qt.Unchecked if row["hidden"] else Qt.Checked
            if item.checkState(0) != state:
                item.setCheckState(0, state)
            item.setToolTip(0, tr("{n} faces", n=row["faces"]))
        self._sync_selection()
        hidden = sum(1 for r in self._rows if r["hidden"])
        self._all_visible.setCheckState(
            Qt.Checked if hidden == 0 else
            Qt.Unchecked if hidden == len(self._rows) else Qt.PartiallyChecked)
        self._all_visible.setVisible(bool(kids))
        if cont is None:
            self._title.setText(tr(
                "Select a component to see its parts."))
        elif not kids:
            self._title.setText(tr(
                "«{name}» is one piece. Split into Pieces finds the solids "
                "inside it that do not touch.", name=cont.name))
        else:
            self._title.setText(tr("<b>{name}</b> — {n} parts",
                                   name=cont.name, n=len(kids)))
        self.tree.setVisible(bool(kids))
        self._explode_box.setVisible(len(kids) > 1)
        state = getattr(cont, "exploded", None) or {}
        if self._drag is None:
            self._explode_slider.blockSignals(True)
            self._explode_slider.setValue(
                int(round(100 * float(state.get("factor", 0.0)))))
            self._explode_slider.blockSignals(False)
            self._explode_value.setText(f"{self._explode_slider.value()}%")
            i = self._explode_mode.findData(state.get("mode", "outward"))
            self._explode_mode.blockSignals(True)
            self._explode_mode.setCurrentIndex(max(i, 0))
            self._explode_mode.blockSignals(False)
        self._reassemble_btn.setEnabled(bool(state))
        self._copy_btn.setEnabled(bool(kids))
        self._by_material.parentWidget().setVisible(bool(kids))
        self._split_btn.setEnabled(cont is not None
                                   and not getattr(cont, "billboard", False))
        fit_rows(self.tree, max_rows=14)
        self._updating = False

    def _sync_selection(self) -> None:
        """Highlight the parts selected in the model, and — when that
        selection changed — scroll the first of them into view, so a part
        clicked in the canvas is found in the list without hunting."""
        scene = self._scene()
        chosen = tuple(id(it.data(0, Qt.UserRole)) for it in self._items
                       if it.data(0, Qt.UserRole) in scene.selection)
        self.tree.blockSignals(True)
        for it in self._items:
            want = it.data(0, Qt.UserRole) in scene.selection
            if it.isSelected() != want:
                it.setSelected(want)
        self.tree.blockSignals(False)
        if chosen and chosen != self._shown_selection:
            first = next(it for it in self._items
                         if id(it.data(0, Qt.UserRole)) == chosen[0])
            from PySide6.QtCore import QItemSelectionModel
            self.tree.setCurrentItem(first, 0, QItemSelectionModel.NoUpdate)
            self.tree.scrollToItem(first)
        self._shown_selection = chosen

    # ---- View → model --------------------------------------------------------
    def _on_all_visible(self) -> None:
        """Show every part — or, when every part already shows, hide them
        all — as one undoable step."""
        from core.history import HideCommand
        parts = [r["part"] for r in self._rows]
        hidden = [p for p in parts if p.hidden]
        if hidden:
            cmd = HideCommand(hidden, hidden=False)
        elif parts:
            cmd = HideCommand(parts, hidden=True)
        else:
            return
        self._window.viewport.history.execute(cmd)
        self._window.viewport.update()
        self.refresh()

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            part = item.data(0, Qt.UserRole)
            menu.addAction(tr("Rename…"), lambda: self.tree.editItem(item, 0))
            menu.addAction(tr("Show") if part.hidden else tr("Hide"),
                           lambda: item.setCheckState(
                               0, Qt.Checked if part.hidden else Qt.Unchecked))
            menu.addSeparator()
        menu.addAction(tr("Show all parts"), self._show_all)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _show_all(self) -> None:
        from core.history import HideCommand
        hidden = [r["part"] for r in self._rows if r["part"].hidden]
        if hidden:
            self._window.viewport.history.execute(
                HideCommand(hidden, hidden=False))
            self._window.viewport.update()
            self.refresh()

    def _on_clicked(self, item, column) -> None:
        """Open the component and select the part — the Outliner's click."""
        part = item.data(0, Qt.UserRole)
        cont = self._container
        if part is None or cont is None or part.hidden:
            return
        vp = self._window.viewport
        scene = self._scene()
        # Ctrl/Shift-click picks several rows: select every one of them.
        parts = [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]
        parts = [p for p in parts if p is not None and not p.hidden] or [part]
        if scene.edit_group is not cont:
            vp.begin_group_edit(cont)
            if scene.edit_group is not cont:
                return                      # locked: it did not open
        scene.selection.clear()
        scene.selection.update(parts)
        # Clicked here, so already in view: the refresh this triggers must
        # not scroll the list under the pointer.
        self._shown_selection = tuple(
            id(it.data(0, Qt.UserRole)) for it in self._items
            if it.data(0, Qt.UserRole) in scene.selection)
        scene.bump_view()
        vp.update()

    def _on_item_changed(self, item, column) -> None:
        if self._updating:
            return
        from core.history import HideCommand, RenameGroupCommand
        part = item.data(0, Qt.UserRole)
        if part is None:
            return
        history = self._window.viewport.history
        name = item.text(0).strip()
        if name and name != part.name:
            history.execute(RenameGroupCommand(part, name))
        hide = item.checkState(0) != Qt.Checked
        if hide != bool(part.hidden):
            history.execute(HideCommand([part], hidden=hide))
        self._window.viewport.update()
        self.refresh()

    def _on_split(self) -> None:
        cont = self._container
        if cont is None:
            return
        scene = self._scene()
        if scene.edit_group is cont:
            # Split works on a closed component: step out of it, keep it
            # selected, and split that.
            self._window.viewport.end_group_edit()
        scene.selection.clear()
        scene.selection.add(cont)
        self._window._on_split_into_pieces()
        self.refresh()

    # ---- Exploded view -----------------------------------------------------
    def _explode_target(self):
        """The container the slider drives, ready for its matrix to move:
        leaving an open container first, so the parts are pulled apart in
        the component's own frame rather than a baked world copy."""
        cont = self._container
        if cont is None or len(getattr(cont, "children", None) or ()) < 2:
            return None
        scene = self._scene()
        if scene.edit_group is cont:
            self._window.viewport.end_group_edit()
            scene.selection.clear()
            scene.selection.add(cont)
        return cont

    def _mode(self) -> str:
        return self._explode_mode.currentData() or "outward"

    def _run_explode(self, factor: float) -> None:
        from core.history import ExplodeViewCommand
        cont = self._explode_target()
        if cont is None:
            return
        self._window.viewport.history.execute(
            ExplodeViewCommand(cont, factor, self._mode()))
        self._window.viewport.update()

    def _on_explode_press(self) -> None:
        from core import explode
        cont = self._explode_target()
        if cont is None:
            return
        self._drag = (cont, explode.snapshot(cont),
                      explode.assembled_centres(cont))

    def _on_explode_value(self, value: int) -> None:
        self._explode_value.setText(f"{value}%")
        if self._drag is None:
            # A click on the track or an arrow key: one step, one command.
            self._run_explode(value / 100.0)
            return
        from core import explode
        cont, _snap, centres = self._drag
        explode.apply_explode(cont, value / 100.0, self._mode(), centres)
        scene = self._scene()
        scene.version += 1
        self._window.viewport.update()

    def _on_explode_release(self) -> None:
        if self._drag is None:
            return
        from core import explode
        cont, snap, _centres = self._drag
        self._drag = None
        explode.restore(cont, snap)      # the preview was not a step…
        self._run_explode(self._explode_slider.value() / 100.0)  # …this is

    def _on_explode_mode(self, _index: int) -> None:
        cont = self._container
        if cont is not None and getattr(cont, "exploded", None):
            self._run_explode(self._explode_slider.value() / 100.0)

    def _on_reassemble(self) -> None:
        self._run_explode(0.0)

    def _on_copy(self) -> None:
        from PySide6.QtGui import QGuiApplication
        from core.parts import cut_list, cut_list_text
        from core.units import fmt_len_fine
        lines = cut_list(self._rows,
                         by_material=self._by_material.isChecked())
        text = cut_list_text(lines, fmt_len_fine, [
            tr("Qty"), tr("Parts"), tr("Material"), tr("Length"),
            tr("Width"), tr("Thickness")], surface=tr("surface"))
        QGuiApplication.clipboard().setText(text)
        self._window.viewport.flash_status(tr(
            "Cut list copied: {n} lines, {parts} parts", n=len(lines),
            parts=sum(ln["qty"] for ln in lines)), 4000)


class MaterialsPanel(QWidget):
    """Swatch palette: pick a colour/texture to paint with."""

    COLS = 5

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if getattr(self, "_in_model_stale", False):
            self._in_model_stale = False
            self.refresh_in_model()

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._tile_size = 1.0
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)

        # Active material preview. A flow, so the Default swatch drops to a
        # second line in a narrow tray instead of widening it.
        row = FlowLayout(spacing=6)
        row.addWidget(QLabel(tr("Active:")))
        self._preview = QLabel()
        self._preview.setFixedSize(_SWATCH, _SWATCH)
        self._preview.setFrameShape(QFrame.Box)
        row.addWidget(self._preview)
        # The «Default» swatch: paints the material OFF a side.
        default_btn = _swatch_button(
            _default_pixmap(),
            tr("Default material (no material) — paint with it to remove "
               "a face's or an object's material"))
        default_btn.clicked.connect(self._apply_default)
        root.addLayout(row)

        # The active material's NAME and colour, on a line of their own
        # under the swatch: in the «Active:» flow they pushed the Default
        # swatch onto a second line and sat lower than the 44 px swatches.
        # A material already in the model is renamed/recoloured on every
        # face that wears it (one undo); the library itself never changes —
        # a library colour edited here becomes a new material of the model.
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(4)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(tr("Material name"))
        self._name_edit.setToolTip(tr(
            "Rename the active material — on every face that wears it. "
            "The library keeps its own name."))
        self._name_edit.editingFinished.connect(self._on_name_edited)
        name_row.addWidget(self._name_edit, 1)
        self._color_btn = QPushButton()
        side = self._name_edit.sizeHint().height()
        self._color_btn.setFixedSize(side, side)
        self._color_btn.setToolTip(tr(
            "Change the active colour — on every face that wears it"))
        self._color_btn.clicked.connect(self._on_pick_active_color)
        name_row.addWidget(self._color_btn)
        # As long as the «Recent» row is when full, field and button
        # together: a bar the width of the tray read as out of place.
        cell = _swatch_button(_color_pixmap((1, 1, 1)),
                              "").sizeHint().width()
        recent_w = RECENT_MAX * cell + (RECENT_MAX - 1) * 2
        self._name_edit.setMaximumWidth(max(recent_w - side - 4, 80))
        name_row.addStretch(0)   # only what the field cannot take
        root.addLayout(name_row)

        # The usual "edit material": tile width/height + rotation, tucked
        # behind an Edit toggle so the panel stays clean. Edits the active
        # texture for future paints, and Apply re-stamps the selected
        # textured faces (undoable).
        from PySide6.QtWidgets import QDoubleSpinBox, QToolButton
        self._edit_toggle = QToolButton()
        self._edit_toggle.setText(tr("Edit texture"))
        self._edit_toggle.setCheckable(True)
        set_arrow(self._edit_toggle, Qt.RightArrow)
        self._edit_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._edit_toggle.setStyleSheet(
            "QToolButton { border: none; padding: 2px; }"
            "QToolButton:hover { background: palette(midlight); }")
        row.addWidget(self._edit_toggle)
        row.addWidget(default_btn)
        self._edit_body = QWidget()
        # Two rows, not one: tile size + rotation above, colour below. A
        # single row with W/H/Rot/Colour/mode/Apply runs past the panel's
        # 480 px and the labels start eliding.
        edit_col = QVBoxLayout(self._edit_body)
        edit_col.setContentsMargins(0, 0, 0, 0)
        edit_col.setSpacing(3)
        edit_row = QHBoxLayout()
        edit_col.addLayout(edit_row)
        edit_row.setContentsMargins(0, 0, 0, 0)
        edit_row.addWidget(QLabel(tr("W")))
        self._sw_box = QDoubleSpinBox()
        self._sw_box.setRange(0.01, 1000.0)
        self._sw_box.setDecimals(2)
        self._sw_box.setSingleStep(0.1)
        self._sw_box.setSuffix(" m")
        edit_row.addWidget(self._sw_box)
        edit_row.addWidget(QLabel(tr("H")))
        self._sh_box = QDoubleSpinBox()
        self._sh_box.setRange(0.01, 1000.0)
        self._sh_box.setDecimals(2)
        self._sh_box.setSingleStep(0.1)
        self._sh_box.setSuffix(" m")
        edit_row.addWidget(self._sh_box)
        edit_row.addWidget(QLabel(tr("Rot")))
        self._rot_box = QDoubleSpinBox()
        self._rot_box.setRange(-360.0, 360.0)
        self._rot_box.setDecimals(0)
        self._rot_box.setSingleStep(15.0)
        self._rot_box.setSuffix("°")
        edit_row.addWidget(self._rot_box)
        edit_row.addStretch(1)

        # Colourized material (.skp format): a textured material also carries a
        # COLOUR, and the image is re-tinted toward it. Two genuinely
        # different pictures — Shift keeps the stone's veining and moves it
        # in tone, Tint greyscales first and keeps only the lightness.
        from PySide6.QtWidgets import QComboBox
        tint_row = QHBoxLayout()
        edit_col.addLayout(tint_row)
        tint_row.setContentsMargins(0, 0, 0, 0)
        #: The tint currently in the fields: RGB floats 0-1, or None.
        self._tint = None
        tint_row.addWidget(QLabel(tr("Color")))
        self._tint_btn = QPushButton()
        self._tint_btn.setFixedWidth(44)
        self._tint_btn.setToolTip(tr("Tint the texture toward a colour"))
        self._tint_btn.clicked.connect(self._on_pick_tint)
        tint_row.addWidget(self._tint_btn)
        self._tint_clear = QToolButton()
        self._tint_clear.setText("×")
        self._tint_clear.setToolTip(tr("Remove the colour (back to the "
                                       "original image)"))
        self._tint_clear.clicked.connect(self._on_clear_tint)
        tint_row.addWidget(self._tint_clear)
        self._tint_mode = QComboBox()
        self._tint_mode.addItem(tr("Shift"), 0)
        self._tint_mode.addItem(tr("Tint"), 1)
        self._tint_mode.setToolTip(tr(
            "Shift: move every pixel's hue toward the colour, keeping the "
            "texture's variation. Tint: replace hue and saturation, keeping "
            "only the lightness."))
        tint_row.addWidget(self._tint_mode)
        tint_row.addStretch(1)
        apply_btn = QPushButton(tr("Apply"))
        apply_btn.setToolTip(tr(
            "Resize/rotate/tint the active texture; with textured faces "
            "selected, re-stamps them (undoable)"))
        apply_btn.clicked.connect(self._on_apply_texture_edit)
        tint_row.addWidget(apply_btn)
        self._edit_body.setVisible(False)

        def _toggle_edit(on):
            self._edit_body.setVisible(on)
            set_arrow(self._edit_toggle, Qt.DownArrow if on
                      else Qt.RightArrow)
            if on:
                self._load_texture_fields()

        self._edit_toggle.toggled.connect(_toggle_edit)
        root.addWidget(self._edit_body)
        self._load_texture_fields()

        # The last materials painted with, so texturing a model does not
        # mean hunting for the same brick in the library every time.
        self._recent_heading = self._heading(tr("Recent"))
        root.addWidget(self._recent_heading)
        self._recent_grid = FlowLayout(spacing=2)
        root.addLayout(self._recent_grid)
        if not PaintTool.recent:
            PaintTool.recent = load_recent_materials()
        self._refresh_recent()

        root.addWidget(self._heading(tr("In model")))
        self._in_model_grid = FlowLayout(spacing=2)
        root.addLayout(self._in_model_grid)

        root.addWidget(self._heading(tr("Library")))
        self._fill_library_categories(root)

        btns = FlowLayout(spacing=4)         # wraps in a narrow tray
        add_color = QPushButton(tr("+ Color…"))
        add_color.clicked.connect(self._add_color)
        add_tex = QPushButton(tr("+ Texture…"))
        add_tex.clicked.connect(self._add_texture)
        purge = QPushButton(tr("Purge"))
        purge.setToolTip(tr("Delete every material no face wears"))
        purge.clicked.connect(self._on_purge)
        btns.addWidget(add_color)
        btns.addWidget(add_tex)
        btns.addWidget(purge)
        root.addLayout(btns)
        root.addStretch(1)

        self._refresh_preview()
        self.refresh_in_model()

    def _heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        theme_style(lbl, "color:{muted}; margin-top:6px; font-size:11px;")
        return lbl

    # ---- Library (categorised) ------------------------------------------------
    #: Category ids from the manifest → display names (translated).
    CATEGORY_NAMES = {
        "brick": "Brick", "concrete": "Concrete", "stone": "Stone",
        "wood": "Wood", "roof": "Roofing", "floor": "Flooring",
        "metal": "Metal", "ground": "Ground", "glass": "Glass",
        "water": "Water",
        # From the Sweet Home 3D texture libraries (see SOURCES.md): what a
        # wall is finished with, and what goes inside the room.
        "wall": "Wall", "wallpaper": "Wallpaper", "fabric": "Fabric",
        "rug": "Rug", "sky": "Sky", "misc": "Miscellaneous",
    }

    def _fill_library_categories(self, root) -> None:
        """Collapsible category sections fed by the bundled library manifest
        (our own procedural set from scripts/gen_textures.py plus the Sweet
        Home 3D libraries — see SOURCES.md), a Colours section, and any loose
        PNGs the user dropped in resources/textures.

        A section's swatches are built the first time it is OPENED. They all
        start closed, and reading four hundred images to fill panels nobody
        has looked at cost most of the program's start-up: 0.21 s to 0.95 s
        when the libraries arrived. Now the cost falls on the category you
        actually expand, once.
        """
        import json as _json
        from PySide6.QtWidgets import QToolButton

        def section(title, fill=None):
            btn = QToolButton()
            btn.setText(f"  {title}")
            btn.setCheckable(True)
            btn.setChecked(False)
            set_arrow(btn, Qt.RightArrow)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setStyleSheet(
                "QToolButton { border: none; padding: 4px 2px;"
                " text-align: left; }"
                "QToolButton:hover { background: palette(midlight); }")
            body = QWidget()
            grid = FlowLayout(body, spacing=2)
            grid.setContentsMargins(4, 2, 0, 4)
            body.setVisible(False)

            pending = [fill]

            def toggle(on, b=btn, w=body, g=grid):
                if on and pending[0] is not None:
                    fn, pending[0] = pending[0], None
                    fn(g)
                w.setVisible(on)
                set_arrow(b, Qt.DownArrow if on else Qt.RightArrow)

            btn.toggled.connect(toggle)
            root.addWidget(btn)
            root.addWidget(body)
            return grid

        # ONE Colours section (the usual Colors category): RAL
        # Classic in code order — which is family order, yellows through
        # blacks, without carving the tray up into nine more headings to
        # click through. The eight unnamed swatches that used to sit at the
        # top are gone at Marco's request: beside 213 colours that each
        # carry a reference, a nameless square is only confusing.
        #
        # RAL is the paint you can actually specify, so a colour picked here
        # paints as a NAMED material ("RAL 7035 Gris claro"): what the
        # drawing carries is a reference a painter can buy, not an RGB
        # triple nobody can match.
        ral_colors = []
        if _RAL_FILE.exists():
            data = _json.loads(_RAL_FILE.read_text(encoding="utf-8"))
            for fam in data.get("families", []):
                ral_colors.extend(fam.get("colors", []))

        def fill_colors(grid):
            row = 0
            for c in ral_colors:
                label = "%s · %s" % (c["code"], _ral_name(c))
                b = _swatch_button(_color_pixmap(c["rgb"]), label)
                b.clicked.connect(
                    lambda _=False, col=c: self._apply_color(
                        col["rgb"], "%s %s" % (col["code"], _ral_name(col))))
                grid.addWidget(b, row // self.COLS, row % self.COLS)
                row += 1

        section("%s  (%d)" % (tr("Colors"), len(ral_colors)), fill_colors)

        def fill_items(grid, items):
            row = 0
            for item in items:
                path = _TEX_DIR / "library" / item["file"]
                pm = _texture_pixmap(path)
                if pm is None:
                    continue
                b = _swatch_button(pm, tr(item["name"]))
                b.clicked.connect(
                    lambda _=False, p=str(path), it=item:
                    self._apply_texture(p, sw=it.get("sw"),
                                        sh=it.get("sh"),
                                        name=tr(it["name"]),
                                        opacity=it.get("opacity")))
                grid.addWidget(b, row // self.COLS, row % self.COLS)
                row += 1

        manifest = _TEX_DIR / "library.json"
        if manifest.exists():
            data = _json.loads(manifest.read_text(encoding="utf-8"))
            for cat in data.get("categories", []):
                items = cat.get("items", [])
                if not items:
                    continue
                title = tr(self.CATEGORY_NAMES.get(cat["id"], cat["id"]))
                section("%s  (%d)" % (title, len(items)),
                        lambda g, it=items: fill_items(g, it))

        def fill_loose(grid, paths):
            for i, path in enumerate(paths):
                pm = _texture_pixmap(path)
                if pm is None:
                    continue
                b = _swatch_button(pm, path.stem)
                b.clicked.connect(
                    lambda _=False, p=str(path), n=path.stem:
                    self._apply_texture(p, name=n))
                grid.addWidget(b, i // self.COLS, i % self.COLS)

        loose = sorted(_TEX_DIR.glob("*.png"))
        if loose:
            section(tr("Other"), lambda g, ps=loose: fill_loose(g, ps))

    def _on_purge(self) -> None:
        """Sweep the registry materials no face wears.

        These are invisible here — the swatches above are built from painted
        faces, not from the registry — so an import's leftovers only ever
        show up as weight in the saved ``.igz``."""
        from PySide6.QtWidgets import QMessageBox
        from core.history import PurgeUnusedCommand
        scene = self._window.viewport.scene
        cmd = PurgeUnusedCommand(layers=False, materials=True)
        _, n_mats = cmd.counts(scene)
        if not n_mats:
            QMessageBox.information(
                self, tr("Purge"), tr("Every material is in use."))
            return
        names = [n for n, _m in (cmd._materials or [])]
        preview = ", ".join(names[:12]) + ("…" if len(names) > 12 else "")
        if QMessageBox.question(
                self, tr("Purge"),
                tr("Delete {n} materials no face wears?", n=n_mats)
                + f"\n\n{preview}") != QMessageBox.Yes:
            return
        self._window.viewport.history.execute(cmd)
        self.refresh_in_model()
        self._window.statusBar().showMessage(
            tr("{n} unused materials purged", n=n_mats), 3000)

    def refresh_in_model(self) -> None:
        """Rebuild the 'En el modelo' swatches from the materials in use."""
        vp = self._window.viewport
        self._in_model_cv = vp.scene.content_version
        hist = getattr(vp, "history", None)
        # What each mesh wears, from the last scan, holds while nothing but
        # commands that keep groups (or paint) changed the model since: a
        # Delete or a Paste beside 2 722 meshes reads only the new ones
        # (~0.4 s on the plant of #158).
        worn = getattr(self, "_worn_by_mesh", None)
        if (worn is None or hist is None
                or hist.groups_cv.get("paint") != self._in_model_cv):
            worn = self._worn_by_mesh = {}
        if hist is not None:
            hist.paint_cv = self._in_model_cv
            hist.groups_cv["paint"] = self._in_model_cv
        # Keep the tray where the user left it. The old swatches only went
        # away at the next event-loop turn (deleteLater), so for a moment
        # the grid held both sets, grew, and the scroll area jumped — the
        # library list slid by itself each time a component was made
        # (Rafael, revision 4, 02:14 and 06:20).
        from PySide6.QtWidgets import QScrollArea
        area = self.parent()
        while area is not None and not isinstance(area, QScrollArea):
            area = area.parent()
        bar = area.verticalScrollBar() if area is not None else None
        keep = bar.value() if bar is not None else None
        colors: dict = {}
        textures: dict = {}
        opacities: dict = {}   # texture path → translucency (glass)
        names: dict = {}     # swatch key → material name (registry identity)
        scene = self._window.viewport.scene

        live: dict = {}

        def mesh_wears(mesh, face_attrs):
            # Each mesh's first face of every distinct paint, in face order:
            # what the tally below keeps of it (a later face with the same
            # name, picture, opacity and colour adds nothing).
            m = mesh.__dict__.get("_mut_serial") if hasattr(
                mesh, "__dict__") else None
            hit = worn.get(id(mesh))
            if hit is not None and hit[0] is mesh and hit[1] == m:
                live[id(mesh)] = hit
                return hit[2]
            out, keys = [], set()
            for attrs in face_attrs(mesh):
                tex = attrs.get("texture")
                path = tex.get("path") if tex else None
                col = attrs.get("color")
                k = (attrs.get("mat"), path,
                     attrs.get("opacity") if path else None,
                     None if path or col is None else tuple(col))
                if k not in keys:
                    keys.add(k)
                    out.append(attrs)
            live[id(mesh)] = (mesh, m, out)
            return out

        def in_use():
            # The first wear of each paint is all the tally keeps, so each
            # mesh is read once, not once per copy (21 406 copies of 2 722
            # meshes in #158), and a lazy one stays unbuilt.
            from core.mesh import face_attrs
            for f in scene.loose_mesh.faces:
                if scene.entity_visible(f):
                    yield f.attrs
            seen: set = set()
            for g, _m in scene.placements():
                if id(g.mesh) not in seen:
                    seen.add(id(g.mesh))
                    yield from mesh_wears(g.mesh, face_attrs)
            # A group's paint lives on the group, not on its faces (#133,
            # @fafecm: it only showed up here once the group was exploded).
            from core.group import iter_placements
            for top in scene.groups:
                for g, _m in iter_placements(top):
                    paint = getattr(g, "material", None)
                    if paint:
                        yield paint

        tally = list(in_use())
        self._worn_by_mesh = live        # the meshes the model still has
        for attrs in tally:
            mat = attrs.get("mat")
            tex = attrs.get("texture")
            if tex and tex.get("path"):
                textures.setdefault(tex["path"], tex)
                if attrs.get("opacity") is not None:
                    opacities.setdefault(tex["path"], attrs.get("opacity"))
                if mat:
                    names.setdefault(("t", tex["path"]), mat)
            else:
                col = attrs.get("color")
                if col is not None:
                    colors[tuple(col)] = col
                    if mat:
                        names.setdefault(("c", tuple(col)), mat)
        # The same swatches as on screen (a Delete, a Paste that brought no
        # new paint): they stay — laying out a hundred buttons again took
        # ~0.2 s on the plant of #158.
        sig = (tuple((k, tuple(c), names.get(("c", k)))
                     for k, c in colors.items()),
               tuple((p, repr(sorted(t.items())), names.get(("t", p)),
                      opacities.get(p), _file_stamp(p))
                     for p, t in textures.items()))
        if (sig == getattr(self, "_swatch_sig", None)
                and self._in_model_grid.count() == self._swatch_count):
            return
        while self._in_model_grid.count():
            item = self._in_model_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        i = 0
        for col in colors.values():
            # A named material shows its NAME (the registry identity the
            # .skp import now preserves); an anonymous paint stays "Color".
            name = names.get(("c", tuple(col)))
            label = name or tr("Color")
            b = _swatch_button(_color_pixmap(tuple(col)), label)
            b.clicked.connect(lambda _=False, c=tuple(col), n=name:
                              self._apply_color(c, name=n))
            if name:
                # Slice (b): edit the material once, restamp every face
                # that wears it — right-click the swatch; and its finish
                # for the render (#181).
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(
                    lambda _pos, n=name, c=tuple(col), w=b:
                    self._swatch_menu(w, n, color=c))
            self._in_model_grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1
        for path, tex in textures.items():
            pm = _texture_pixmap(path)
            if pm is None:
                continue
            t_name = names.get(("t", path))
            b = _swatch_button(pm, t_name or Path(path).stem)
            b.clicked.connect(
                lambda _=False, t=dict(tex), n=t_name,
                o=opacities.get(path): self._apply_texture(
                    t["path"], t.get("sw", 1.0), name=n, opacity=o))
            if t_name:
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(
                    lambda _pos, n=t_name, w=b: self._swatch_menu(w, n))
            self._in_model_grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1
        self._swatch_sig = sig
        self._swatch_count = self._in_model_grid.count()
        if bar is not None and keep is not None:
            from PySide6.QtCore import QTimer
            bar.setValue(keep)
            # …and once more after the layout settles its new height.
            QTimer.singleShot(0, lambda b=bar, v=keep: b.setValue(v))

    # ---- Apply / add --------------------------------------------------------
    def _apply_color(self, rgb, name: str | None = None) -> None:
        PaintTool.current_is_default = False
        PaintTool.current_color = tuple(rgb)
        PaintTool.current_texture = None
        PaintTool.current_opacity = None
        PaintTool.current_material = self._material_for(
            name, color=tuple(rgb))
        self._window._activate_tool("paint")
        self._refresh_preview()

    def _swatch_menu(self, button, name: str, color=None) -> None:
        """Right-click on a named material: edit its colour, and choose its
        finish for Render with Blender (#181) — «Automatic» names the finish
        it would be guessed as, so the user sees what the name already says."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        from core import finish as fin
        scene = self._window.viewport.scene
        mat = scene.materials.get(name)
        menu = QMenu(button)
        if mat is not None:
            from PySide6.QtCore import QTimer
            menu.addAction(tr("Rename…"),
                           lambda: QTimer.singleShot(
                               0, lambda: self._ask_rename(name)))
        if color is not None:
            # The dialog opens once the menu has closed: a modal opened
            # inside the menu's own event loop came back without a colour.
            from PySide6.QtCore import QTimer
            menu.addAction(tr("Edit colour…"),
                           lambda: QTimer.singleShot(
                               0, lambda: self._edit_named_color(name, color)))
        if mat is not None:
            sub = menu.addMenu(tr("Finish for the render"))
            pic = (mat.texture or {}).get("path")
            guessed = fin.guess(name, pic and Path(pic).name, mat.opacity)
            auto = sub.addAction(tr("Automatic: {finish}",
                                    finish=tr(fin.LABELS[guessed])))
            auto.setCheckable(True)
            auto.setChecked(mat.finish not in fin.FINISHES)
            auto.triggered.connect(lambda: self._set_finish(name, None))
            sub.addSeparator()
            for key in fin.FINISHES:
                act = sub.addAction(tr(fin.LABELS[key]))
                act.setCheckable(True)
                act.setChecked(mat.finish == key)
                act.triggered.connect(
                    lambda _c=False, k=key: self._set_finish(name, k))
        if not menu.isEmpty():
            menu.exec(QCursor.pos())

    def _set_finish(self, name: str, finish) -> None:
        from core.finish import LABELS
        from core.history import SetMaterialFinishCommand
        self._window.viewport.history.execute(
            SetMaterialFinishCommand(name, finish))
        label = tr("Automatic") if finish is None else tr(LABELS[finish])
        self._window.statusBar().showMessage(
            tr("Finish of '{name}' for the render: {finish}", name=name,
               finish=label), 3000)

    def _edit_named_color(self, name: str, current_rgb) -> None:
        """Slice (b) of the registry track: edit a named colour material
        and restamp every face wearing it, one undoable step."""
        from core.history import RestampMaterialCommand
        from core.materials import Material
        scene = self._window.viewport.scene
        existing = scene.materials.get(name)
        base = (existing.color if existing and existing.color
                else tuple(current_rgb))
        chosen = get_color(
            QColor.fromRgbF(*base[:3]), self,
            tr("Edit material: {name}", name=name))
        if not chosen.isValid():
            return
        rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        new_mat = Material(
            self._recoloured_name(name, rgb), color=rgb,
            opacity=existing.opacity if existing else None,
            finish=existing.finish if existing else None)
        self._restamp(name, new_mat)

    # ---- Rename / recolour in the model ----------------------------------
    def _recoloured_name(self, name: str, rgb) -> str:
        """The name a material keeps when it takes colour *rgb*: its own —
        unless it is a library colour, whose name is a reference a painter
        buys by («RAL 7035»). That one would be a lie in another colour, so
        the edit becomes a new material, «RAL 7035 … (modified)», and the
        library keeps its colour under its name."""
        ref = _ral_rgb(name)
        if ref is None or all(abs(a - b) < 0.002
                              for a, b in zip(ref, rgb[:3])):
            return name
        from core.materials import free_name
        return free_name("%s %s" % (name, tr("(modified)")),
                         self._window.viewport.scene.materials)

    def _restamp(self, old_name: str, new_mat) -> bool:
        """Put *new_mat* on every face and group wearing *old_name* — a new
        recipe, a new name, or both — in one undoable step. A name another
        material of the model already has is refused: that would merge
        two materials, not rename one."""
        from core.history import RestampMaterialCommand
        from tools.paint import rename_recent
        scene = self._window.viewport.scene
        if new_mat.name != old_name and new_mat.name in scene.materials:
            self._window.statusBar().showMessage(tr(
                "There is already a material called '{name}'",
                name=new_mat.name), 4000)
            return False
        self._window.viewport.history.execute(
            RestampMaterialCommand(old_name, new_mat))
        self._window.viewport.notify_scene_changed()
        active = PaintTool.current_material
        if active is not None and active.name == old_name:
            PaintTool.current_material = new_mat
            if new_mat.color is not None and not PaintTool.current_texture:
                PaintTool.current_color = tuple(new_mat.color)
        recent = rename_recent(PaintTool.recent, old_name,
                               new_mat.face_attrs())
        if recent != PaintTool.recent:
            PaintTool.recent = recent
            self.recent_materials_changed()
        self.refresh_in_model()
        self._refresh_preview()
        if new_mat.name != old_name:
            msg = tr("Material '{old}' is now '{name}' on every face that "
                     "wears it", old=old_name, name=new_mat.name)
        else:
            msg = tr("Material '{name}' updated on every face that wears it",
                     name=old_name)
        self._window.statusBar().showMessage(msg, 3000)
        return True

    def _renamed(self, old_name: str, new_name: str) -> bool:
        """Rename the model's material *old_name* to *new_name*."""
        from core.materials import Material
        old = self._window.viewport.scene.materials.get(old_name)
        if old is None:
            return False
        return self._restamp(old_name, Material(
            new_name, color=old.color, texture=old.texture,
            opacity=old.opacity, finish=old.finish))

    def _ask_rename(self, name: str) -> None:
        """Right-click ▸ Rename… on a swatch of «In model»."""
        new, ok = QInputDialog.getText(
            self, tr("Rename material"), tr("New name:"), text=name)
        new = new.strip() if ok else ""
        if new and new != name:
            self._renamed(name, new)

    def _on_name_edited(self) -> None:
        """The name field of «Active:» was confirmed. In the model: rename
        it everywhere. Not yet in the model (a library swatch, a fresh
        colour): only what is painted from now on takes the new name."""
        new = self._name_edit.text().strip()
        if PaintTool.current_is_default:
            self._refresh_preview()
            return
        mat = PaintTool.current_material
        old = mat.name if mat is not None else ""
        if not new or new == old:
            self._refresh_preview()
            return
        scene = self._window.viewport.scene
        if mat is not None and old in scene.materials:
            if not self._renamed(old, new):
                self._refresh_preview()
            return
        from core.materials import Material
        if new in scene.materials:
            # The model's own material of that name: paint with it.
            PaintTool.current_material = scene.materials[new]
        elif PaintTool.current_texture:
            PaintTool.current_material = Material(
                new, texture=dict(PaintTool.current_texture),
                opacity=PaintTool.current_opacity)
        else:
            PaintTool.current_material = Material(
                new, color=tuple(PaintTool.current_color),
                opacity=PaintTool.current_opacity)
        self._refresh_preview()
        self._window.statusBar().showMessage(tr(
            "Active material named '{name}' — click faces to paint it",
            name=new), 3000)

    def _on_pick_active_color(self) -> None:
        """The colour button of «Active:»."""
        if PaintTool.current_is_default or PaintTool.current_texture:
            return
        chosen = get_color(QColor.fromRgbF(*PaintTool.current_color[:3]),
                           self, tr("Colour"))
        if chosen.isValid():
            self._recolour_active(
                (chosen.redF(), chosen.greenF(), chosen.blueF()))
            self._refresh_preview()

    def _material_for(self, name, color=None, texture=None, opacity=None):
        """The Material identity for the active swatch: the registry's
        entry when the name already exists (keeps its full recipe), a fresh
        one otherwise — registered lazily by the paint command itself, so
        merely CLICKING a library swatch never pollutes the registry."""
        if not name:
            return None
        from core.materials import Material
        existing = self._window.viewport.scene.materials.get(name)
        return existing or Material(name, color=color, texture=texture,
                                    opacity=opacity)

    def _load_texture_fields(self) -> None:
        tex = PaintTool.current_texture
        mat = PaintTool.current_material
        vp = getattr(self._window, "viewport", None)
        reg = (vp.scene.materials.get(mat.name)
               if mat is not None and vp is not None else None)
        if (tex and not tex.get("tint") and reg is not None and reg.texture
                and reg.texture.get("tint")
                and reg.texture.get("path") == tex.get("path")):
            # A tinted swatch of «In model» hands over the image it shows,
            # not its colour: the fields read the colour off the material,
            # or an Apply to change the size would strip it everywhere.
            tex = {**reg.texture, **{k: tex[k] for k in ("sw", "sh", "rot")
                                     if k in tex}}
        if tex:
            self._sw_box.setValue(float(tex.get("sw", 1.0)))
            self._sh_box.setValue(float(tex.get("sh", 1.0)))
            self._rot_box.setValue(float(tex.get("rot", 0.0)))
            # The tint has to load too: otherwise opening the panel and
            # pressing Apply to nudge the tile size would silently strip a
            # colour the user set earlier.
            tint = tex.get("tint")
            self._tint = tuple(tint) if tint else None
            mode = int(tex.get("tint_mode", 0) or 0)
            self._tint_mode.setCurrentIndex(1 if mode == 1 else 0)
        else:
            self._sw_box.setValue(self._tile_size)
            self._sh_box.setValue(self._tile_size)
            self._rot_box.setValue(0.0)
            self._tint = None
        self._refresh_tint_swatch()

    def _refresh_tint_swatch(self) -> None:
        """The colour button wears the tint (or reads "—" when there is
        none), so the panel says at a glance whether this texture carries
        one."""
        if getattr(self, "_tint_btn", None) is None:
            return
        if self._tint is None:
            self._tint_btn.setText("—")
            self._tint_btn.setStyleSheet("")
            self._tint_clear.setEnabled(False)
            self._tint_mode.setEnabled(False)
            return
        r, g, b = (int(round(c * 255)) for c in self._tint[:3])
        self._tint_btn.setText("")
        self._tint_btn.setStyleSheet(
            f"background: rgb({r},{g},{b}); border: 1px solid #555;")
        self._tint_clear.setEnabled(True)
        self._tint_mode.setEnabled(True)

    def _on_pick_tint(self) -> None:
        base = self._tint or (0.7, 0.7, 0.7)
        colour_only = not PaintTool.current_texture
        if colour_only and self._tint is None and \
                not PaintTool.current_is_default:
            base = PaintTool.current_color
        chosen = get_color(
            QColor.fromRgbF(*base[:3]), self,
            tr("Colour") if colour_only else tr("Tint the texture"))
        if not chosen.isValid():
            return
        rgb = (chosen.redF(), chosen.greenF(), chosen.blueF())
        if colour_only and self._recolour_active(rgb):
            # A plain colour changes at once: nothing to tint, no Apply.
            self._refresh_preview()
            return
        self._tint = rgb
        if not self._tint_mode.isEnabled():
            self._tint_mode.setEnabled(True)
        self._refresh_tint_swatch()

    def _on_clear_tint(self) -> None:
        self._tint = None
        self._refresh_tint_swatch()

    def _retinted(self, tex: dict) -> dict:
        """*tex* with the panel's colour applied (or removed).

        Always re-tints from the entry's untinted ``base``, never from the
        last result, so sliding through colours cannot degrade the image."""
        from core.texture import tinted_texture, untinted_texture
        if self._tint is None:
            return untinted_texture(tex)
        mode = self._tint_mode.currentData()
        return tinted_texture(tex, self._tint,
                              int(mode if mode is not None else 0))

    def _on_apply_texture_edit(self) -> None:
        """Push the W/H/Rot fields onto the active texture and onto any
        selected textured faces (one undoable step)."""
        from core.history import SetFaceTextureCommand
        sw = self._sw_box.value()
        sh = self._sh_box.value()
        rot = self._rot_box.value() % 360.0
        scene = self._window.viewport.scene
        targets = [f for f in scene.selection
                   if isinstance(f, Face) and f.attrs.get("texture")]
        if self._edit_model_material(sw, sh, rot, targets):
            return
        if PaintTool.current_texture:
            PaintTool.current_texture = self._retinted({
                **PaintTool.current_texture, "sw": sw, "sh": sh, "rot": rot})
        if targets:
            # Each face keeps its own image; size/rotation and the tint change.
            from core.history import CompoundCommand
            cmds = []
            for f in targets:
                tex = self._retinted({**f.attrs["texture"], "sw": sw,
                                      "sh": sh, "rot": rot})
                cmds.append(SetFaceTextureCommand([f], tex))
            cmd = cmds[0] if len(cmds) == 1 else CompoundCommand(cmds)
            self._window.viewport.history.execute(cmd)
            self._window.viewport.update()
            self._window.statusBar().showMessage(
                tr("Texture updated on {n} faces", n=len(targets)), 2500)
        elif not PaintTool.current_texture:
            # A plain colour is active: the Color row changes IT — the
            # place everyone looks for (Marco, testing 0.5.7, tinted a
            # colour material here and nothing happened: tinting needs a
            # texture, and the right-click edit was out of sight).
            if not self._recolour_active(self._tint):
                self._window.statusBar().showMessage(
                    tr("Pick a texture (or select textured faces) first"),
                    2500)
        self._refresh_preview()

    def _edit_model_material(self, sw, sh, rot, selected=()) -> bool:
        """Apply on a textured material of the model: the material itself
        changes, on every face and object that wears it, one undo step —
        not only the faces selected, which left one name in two looks
        (#1308). The tile size and turn reach those faces only when they
        were changed here; otherwise each face keeps its own (a texture
        placed by hand stays where it was). Selected textured faces of
        other materials take the fields, as before, in the same step.
        False when the active texture is no model material: then Apply
        works on the selection alone."""
        mat = PaintTool.current_material
        scene = self._window.viewport.scene
        reg = scene.materials.get(mat.name) if mat is not None else None
        if not PaintTool.current_texture or reg is None or not reg.texture:
            return False
        from core.history import (CompoundCommand,
                                  EditTexturedMaterialCommand,
                                  SetFaceTextureCommand)
        old = reg.texture
        was = (float(old.get("sw", 1.0)), float(old.get("sh", 1.0)),
               float(old.get("rot", 0.0)) % 360.0)
        size = (sw, sh, rot)
        if all(abs(a - b) < 1e-9 for a, b in zip(size, was)):
            size = None
        mode = self._tint_mode.currentData()
        cmds = [EditTexturedMaterialCommand(
            reg.name, self._tint, int(mode if mode is not None else 0),
            size)]
        for f in selected:
            if f.attrs.get("mat") != reg.name:
                cmds.append(SetFaceTextureCommand([f], self._retinted({
                    **f.attrs["texture"], "sw": sw, "sh": sh, "rot": rot})))
        self._window.viewport.history.execute(
            cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
        new = scene.materials.get(reg.name) or reg
        PaintTool.current_material = new
        PaintTool.current_texture = dict(new.texture or {}) or None
        self._window.viewport.notify_scene_changed()
        self._window.viewport.update()
        self.refresh_in_model()
        self._refresh_preview()
        self._window.statusBar().showMessage(
            tr("Material '{name}' updated on every face that wears it",
               name=reg.name), 3000)
        return True

    def _recolour_active(self, rgb) -> bool:
        """Give the active plain colour ``rgb``: a named material is edited
        and restamped on every face and group that wears it (one undo
        step); an anonymous colour becomes the colour to paint next.
        False when there is no colour to change."""
        if rgb is None or PaintTool.current_is_default:
            return False
        rgb = tuple(float(c) for c in rgb[:3])
        mat = PaintTool.current_material
        scene = self._window.viewport.scene
        if mat is not None and mat.name in scene.materials:
            from core.materials import Material
            old = scene.materials[mat.name]
            new_mat = Material(self._recoloured_name(mat.name, rgb),
                               color=rgb, opacity=old.opacity,
                               finish=old.finish)
            if self._restamp(mat.name, new_mat):
                PaintTool.current_material = new_mat
                PaintTool.current_color = rgb
            return True
        PaintTool.current_color = rgb
        if mat is not None:
            from core.materials import Material
            PaintTool.current_material = Material(
                self._recoloured_name(mat.name, rgb), color=rgb)
        self._window.statusBar().showMessage(
            tr("Active colour changed — click faces to paint it"), 3000)
        return True

    def _apply_texture(self, path: str, size: float | None = None,
                       sw: float | None = None,
                       sh: float | None = None,
                       name: str | None = None,
                       opacity: float | None = None) -> None:
        w = sw if sw is not None else (size or self._tile_size)
        h = sh if sh is not None else (size or self._tile_size)
        PaintTool.current_is_default = False
        PaintTool.current_texture = {"path": path, "sw": w, "sh": h,
                                     "rot": 0.0}
        PaintTool.current_opacity = opacity
        PaintTool.current_material = self._material_for(
            name, texture=dict(PaintTool.current_texture), opacity=opacity)
        self._window._activate_tool("paint")
        self._load_texture_fields()
        self._refresh_preview()

    def _add_color(self) -> None:
        r, g, b = PaintTool.current_color
        chosen = get_color(QColor.fromRgbF(r, g, b), self, tr("Color"))
        if chosen.isValid():
            # Optional identity: a named colour becomes a registry material
            # (registered on first paint) and shows in per-material takeoffs.
            name, ok = _prompts.get_text(
                self, tr("Color"), tr("Material name (optional):"))
            self._apply_color(
                (chosen.redF(), chosen.greenF(), chosen.blueF()),
                name=name.strip() if ok and name.strip() else None)

    def _add_texture(self) -> None:
        path_str, _ = file_dialogs.getOpenFileName(
            self, tr("Choose texture"), str(_TEX_DIR),
            tr("Images (*.png *.jpg *.jpeg *.bmp);;All (*)"))
        if not path_str:
            return
        size, ok = QInputDialog.getDouble(
            self, tr("Texture size"), tr("Real tile size (meters):"),
            self._tile_size, 0.001, 1000.0, 3)
        if not ok:
            return
        self._tile_size = size
        # A texture picked from disk is a material named after its file.
        self._apply_texture(path_str, size, name=Path(path_str).stem)

    # ---- Recent ----------------------------------------------------------
    def recent_materials_changed(self) -> None:
        """The Paint tool painted with a material: keep it and show it."""
        save_recent_materials(PaintTool.recent)
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        while self._recent_grid.count():
            w = self._recent_grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for entry in PaintTool.recent:
            tex = entry.get("texture")
            pm = (_texture_pixmap(tex["path"]) if tex
                  else _color_pixmap(tuple(entry.get("color") or (1, 1, 1))))
            if pm is None:
                continue
            label = entry.get("mat") or (
                Path(tex["path"]).stem if tex else tr("Color"))
            b = _swatch_button(pm, label)
            b.clicked.connect(lambda _=False, e=entry: self._apply_recent(e))
            self._recent_grid.addWidget(b)
        shown = self._recent_grid.count() > 0
        self._recent_heading.setVisible(shown)

    def _apply_recent(self, entry: dict) -> None:
        """Make a recent material the active paint, exactly as it was
        painted: image with its size, turn and tint, or the colour; its
        translucency and its name."""
        tex = entry.get("texture")
        PaintTool.current_is_default = False
        PaintTool.current_texture_plane = None
        if tex:
            PaintTool.current_texture = dict(tex)
        else:
            PaintTool.current_texture = None
            PaintTool.current_color = tuple(entry.get("color") or (1, 1, 1))
        PaintTool.current_opacity = entry.get("opacity")
        PaintTool.current_material = self._material_for(
            entry.get("mat"),
            color=None if tex else PaintTool.current_color,
            texture=dict(tex) if tex else None,
            opacity=entry.get("opacity"))
        self._window._activate_tool("paint")
        self._load_texture_fields()
        self._refresh_preview()

    def sync_from_paint(self) -> None:
        """Mirror what the Paint tool holds NOW — called after the
        eyedropper sampled a face, so the «Activo» swatch and the size
        fields say what the next click will paint (issue #47)."""
        if PaintTool.current_texture is not None:
            self._load_texture_fields()
        self._refresh_preview()

    def _apply_default(self) -> None:
        """The «Default» material: paint with it to take a side's
        material off (@pacaeiro, #47)."""
        PaintTool.current_is_default = True
        PaintTool.current_texture = None
        PaintTool.current_texture_plane = None
        PaintTool.current_opacity = None
        PaintTool.current_material = None
        self._window._activate_tool("paint")
        self._refresh_preview()

    def _refresh_name_bar(self) -> None:
        """The name field and colour button say what «Active:» holds."""
        if getattr(self, "_name_edit", None) is None:
            return
        default = PaintTool.current_is_default
        mat = PaintTool.current_material
        self._name_edit.blockSignals(True)
        self._name_edit.setText("" if default or mat is None else mat.name)
        self._name_edit.blockSignals(False)
        self._name_edit.setEnabled(not default)
        plain = not default and not PaintTool.current_texture
        self._color_btn.setVisible(plain)
        if plain:
            r, g, b = (int(round(c * 255))
                       for c in PaintTool.current_color[:3])
            self._color_btn.setStyleSheet(
                f"background: rgb({r},{g},{b}); border: 1px solid #555;")

    def _refresh_preview(self) -> None:
        self._refresh_name_bar()
        if PaintTool.current_is_default:
            self._preview.setPixmap(_default_pixmap())
            self._preview.setToolTip(tr("Default material (no material)"))
            return
        self._preview.setToolTip("")
        if PaintTool.current_texture is not None:
            pm = _texture_pixmap(PaintTool.current_texture["path"])
            if pm is not None:
                self._preview.setPixmap(pm)
                return
        self._preview.setPixmap(_color_pixmap(PaintTool.current_color))


_RECENT_KEY = "paint/recent_materials"


def load_recent_materials() -> list[dict]:
    """The «Recent» materials saved by the last session. An image that is
    gone from disk (an import's temporary folder) is dropped."""
    import json
    raw = QSettings().value(_RECENT_KEY) or ""
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return []
    out = []
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict) or not (e.get("texture") or e.get("color")):
            continue
        tex = e.get("texture")
        if tex and not (isinstance(tex, dict) and tex.get("path")
                        and Path(tex["path"]).exists()):
            continue
        out.append(e)
    return out[:RECENT_MAX]


def save_recent_materials(entries: list[dict]) -> None:
    import json
    try:
        QSettings().setValue(_RECENT_KEY, json.dumps(entries[:RECENT_MAX]))
    except (TypeError, ValueError):
        pass                       # a value JSON cannot hold: keep the old


def _dialog_parent(panel) -> QWidget:
    """Where a dialog opened from a toolbar-dropdown panel must hang: the
    main window, with the dropdown closed first. Parented to the panel, the
    modal dialog's transient parent is the menu POPUP — Wayland never maps
    it, and exec() waits forever for a window no one sees («Añadir
    localización se queda cargando», Marco on the 0.5.1 Flatpak)."""
    w = panel.parentWidget()
    while w is not None:
        if isinstance(w, QMenu):
            w.close()
            break
        w = w.parentWidget()
    return panel._window


class DimensionStylePanel(QWidget):
    """Live editor for ``scene.dimension_style``."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 8)
        style = self._style()

        grid.addWidget(QLabel(tr("Decimals:")), 0, 0)
        self._decimals = QSpinBox()
        self._decimals.setRange(0, 4)
        self._decimals.setValue(int(style.get("decimals", 2)))
        self._decimals.valueChanged.connect(self._apply)
        grid.addWidget(self._decimals, 0, 1)

        grid.addWidget(QLabel(tr("Unit:")), 1, 0)
        self._units = QComboBox()
        from core.units import UNIT_CHOICES
        self._units.addItems(list(UNIT_CHOICES))
        self._units.setCurrentText(style.get("units", "m"))
        self._units.currentTextChanged.connect(self._apply)
        grid.addWidget(self._units, 1, 1)

        # «1.30» instead of «1.30 m»: many drawings state the unit once, in
        # the title block or a note (#374).
        self._show_unit = QCheckBox(tr("Show unit"))
        self._show_unit.setChecked(bool(style.get("show_unit", True)))
        self._show_unit.toggled.connect(self._apply)
        grid.addWidget(self._show_unit, 2, 1)

        grid.addWidget(QLabel(tr("Font:")), 3, 0)
        self._font = QSpinBox()
        self._font.setRange(6, 28)
        self._font.setValue(int(style.get("font_size", 9)))
        self._font.valueChanged.connect(self._apply)
        grid.addWidget(self._font, 3, 1)

        grid.addWidget(QLabel(tr("Color:")), 4, 0)
        self._color_btn = QPushButton()
        self._color_btn.clicked.connect(self._pick_color)
        grid.addWidget(self._color_btn, 4, 1)
        self._refresh_color_btn()

        # The drafting standard (``dimension_style["norma"]``) stays in the
        # document, but ISO is the only one offered for now: the
        # German/Japanese switch is off the panel until a future release
        # (Marco, 2026-09-20: «hagamos las ISO por ahora, la alemana o
        # japonesa quítalo»).

        # What closes the dimension line — a document-wide choice, like
        # the units (a user of DriveMeca's video, 2026-09-20: «los
        # extremos no tiene para cambiarla»).
        grid.addWidget(QLabel(tr("Ends:")), 5, 0)
        self._ends = QComboBox()
        for label, key in ((tr("Arrows"), "arrow"),
                           (tr("Oblique ticks"), "tick"),
                           (tr("None"), "none")):
            self._ends.addItem(label, key)
        i = self._ends.findData(str(style.get("ends", "arrow") or "arrow"))
        self._ends.setCurrentIndex(max(i, 0))
        self._ends.currentIndexChanged.connect(self._apply)
        grid.addWidget(self._ends, 5, 1)

        # AutoCAD's DIMDLI: how far apart the rows of a baseline run sit.
        grid.addWidget(QLabel(tr("Baseline step:")), 6, 0)
        self._base_step = QDoubleSpinBox()
        self._base_step.setRange(1.0, 60.0)
        self._base_step.setSingleStep(0.5)
        self._base_step.setDecimals(1)
        self._base_step.setSuffix(" mm")
        self._base_step.setValue(float(style.get("base_step_mm", 8.0)))
        self._base_step.setToolTip(tr(
            "How far apart the rows of a baseline dimension run sit on "
            "paper. It travels with the document."))
        self._base_step.valueChanged.connect(self._apply)
        grid.addWidget(self._base_step, 6, 1)

    def _style(self) -> dict:
        return self._window.viewport.scene.dimension_style

    def _apply(self) -> None:
        style = self._style()
        style["decimals"] = self._decimals.value()
        style["units"] = self._units.currentText()
        style["show_unit"] = self._show_unit.isChecked()
        style["font_size"] = self._font.value()
        style["ends"] = self._ends.currentData() or "arrow"
        style["base_step_mm"] = float(self._base_step.value())
        self._window.viewport.scene.version += 1
        self._window.viewport.update()

    def _pick_color(self) -> None:
        c = self._style().get("color", [45, 55, 75])
        chosen = get_color(QColor(c[0], c[1], c[2]), _dialog_parent(self),
                                       tr("Dimension color"))
        if chosen.isValid():
            self._style()["color"] = [chosen.red(), chosen.green(), chosen.blue()]
            self._refresh_color_btn()
            self._apply()

    def _refresh_color_btn(self) -> None:
        c = self._style().get("color", [45, 55, 75])
        self._color_btn.setStyleSheet(
            f"background: rgb({c[0]},{c[1]},{c[2]}); min-height: 18px;")


class StylesPanel(QWidget):
    """Live editor for ``scene.display_style`` — the Styles panel.

    The top combo picks a style (built-ins + the user's saved library); the
    controls below edit the ACTIVE style in place, live — the viewport reads
    it every frame, so there is nothing to "apply". «Save style…» snapshots
    the current look under a name into the user library (QSettings), where
    ``style_by_name`` — and with it the composer's per-frame style combo —
    resolves it like any preset. Edits are not undoable, same as the
    dimension-style panel: they change how the model draws, not what it is.
    """

    #: (mode key, translatable label) — labels, not the builtin style names:
    #: "Shaded" the style is a preset bundle, "Shaded" the mode is one field.
    _MODES = (("textures", "Textures"), ("shaded", "Shaded"),
              ("hidden_line", "Hidden line"), ("monochrome", "Monochrome"),
              ("wireframe", "Wireframe"), ("xray", "X-ray"))

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 8)

        self._combo = QComboBox()
        self._combo.activated.connect(self._on_pick)
        grid.addWidget(self._combo, 0, 0, 1, 2)

        grid.addWidget(QLabel(tr("Face mode:")), 1, 0)
        self._mode = QComboBox()
        for key, label in self._MODES:
            self._mode.addItem(tr(label), key)
        self._mode.currentIndexChanged.connect(self._apply_edits)
        grid.addWidget(self._mode, 1, 1)

        self._edges = QCheckBox(tr("Edges"))
        self._edges.toggled.connect(self._apply_edits)
        grid.addWidget(self._edges, 2, 0)
        self._edge_c = self._swatch(tr("Edge color"), "edge_color")
        grid.addWidget(self._edge_c, 2, 1)

        self._profiles = QCheckBox(tr("Profiles"))
        self._profiles.toggled.connect(self._apply_edits)
        grid.addWidget(self._profiles, 3, 0)
        self._back_edges = QCheckBox(tr("Back edges"))
        self._back_edges.setToolTip(tr(
            "Draw the edges hidden behind faces as dashed lines."))
        self._back_edges.toggled.connect(self._apply_edits)
        grid.addWidget(self._back_edges, 3, 1)

        grid.addWidget(QLabel(tr("Front color:")), 4, 0)
        self._front_c = self._swatch(
            tr("Front color — paints the faces with no material (every "
               "face in Hidden line and Monochrome)"),
            "front_color")
        grid.addWidget(self._front_c, 4, 1)

        # Back color: the tint of faces seen from behind (the
        # inside of a solid, or a reversed face).
        grid.addWidget(QLabel(tr("Back color:")), 5, 0)
        self._back_c = self._swatch(
            tr("Back color — paints faces seen from behind"), "back_color")
        grid.addWidget(self._back_c, 5, 1)

        self._sky = QCheckBox(tr("Sky"))
        self._sky.toggled.connect(self._apply_edits)
        grid.addWidget(self._sky, 6, 0)
        self._sky_c = self._swatch(tr("Sky color"), "sky_color")
        grid.addWidget(self._sky_c, 6, 1)

        grid.addWidget(QLabel(tr("Ground:")), 7, 0)
        self._ground_c = self._swatch(tr("Ground color"), "ground_color")
        grid.addWidget(self._ground_c, 7, 1)

        grid.addWidget(QLabel(tr("Background:")), 8, 0)
        self._bg_c = self._swatch(
            tr("Background — visible with the sky off"), "background")
        grid.addWidget(self._bg_c, 8, 1)

        self._fill = QCheckBox(tr("Section Fill"))
        self._fill.toggled.connect(self._apply_edits)
        grid.addWidget(self._fill, 9, 0)
        self._fill_c = self._swatch(tr("Section fill color"),
                                    "section_fill_color")
        grid.addWidget(self._fill_c, 9, 1)

        # Ambient occlusion (#954): off in every preset. The
        # two values only take edits while the switch is on.
        self._ao = QCheckBox(tr("Ambient occlusion"))
        self._ao.setToolTip(tr(
            "Softly darkens where surfaces meet — corners, the foot of a "
            "wall, under a bench."))
        self._ao.toggled.connect(self._apply_edits)
        grid.addWidget(self._ao, 10, 0, 1, 2)
        self._ao_dist_lbl = QLabel()             # its unit: _sync_ao_controls
        grid.addWidget(self._ao_dist_lbl, 11, 0)
        # A slider and its value, like the intensity below, on a log scale:
        # a centimetre matters at the foot of a skirting board, ten metres
        # between two buildings.
        dist_row = QHBoxLayout()
        self._ao_dist = QSlider(Qt.Horizontal)
        self._ao_dist.setRange(0, self._AO_DIST_STEPS)
        self._ao_dist.setToolTip(tr(
            "How far a surface still darkens its neighbour"))
        self._ao_dist.valueChanged.connect(self._on_ao_dist_slider)
        dist_row.addWidget(self._ao_dist, 1)
        self._ao_dist_val = QLabel()
        self._ao_dist_val.setMinimumWidth(28)
        dist_row.addWidget(self._ao_dist_val)
        grid.addLayout(dist_row, 11, 1)
        self._ao_int_lbl = QLabel(tr("Intensity:"))
        grid.addWidget(self._ao_int_lbl, 12, 0)
        int_row = QHBoxLayout()
        self._ao_int = QSlider(Qt.Horizontal)
        self._ao_int.setRange(0, 20)             # tenths: 0.0 – 2.0
        self._ao_int.valueChanged.connect(self._apply_edits)
        int_row.addWidget(self._ao_int, 1)
        self._ao_int_val = QLabel()
        self._ao_int_val.setMinimumWidth(28)
        int_row.addWidget(self._ao_int_val)
        grid.addLayout(int_row, 12, 1)

        row = QHBoxLayout()
        save_btn = QPushButton(tr("Save style…"))
        save_btn.clicked.connect(self._on_save)
        row.addWidget(save_btn)
        self._del_btn = QPushButton(tr("Delete"))
        self._del_btn.clicked.connect(self._on_delete)
        row.addWidget(self._del_btn)
        grid.addLayout(row, 13, 0, 1, 2)

        self.refresh()

    # ---- Plumbing -----------------------------------------------------------
    def _style(self):
        """The active view's style, to show (with several views, the one
        worked in)."""
        active = getattr(self._window, "active_style", None)
        if active is not None:
            return active()
        return getattr(self._window.viewport.scene, "display_style", None)

    def _own_style(self):
        """The active view's style, to change: its own copy first when it is
        one of several views still showing the window's."""
        own = getattr(self._window, "own_style", None)
        return own() if own is not None else self._style()

    def _repaint(self) -> None:
        again = getattr(self._window, "repaint_styled", None)
        if again is not None:
            again()
        else:
            self._window.viewport.update()

    def _shown_color(self, attr: str):
        """The colour a swatch shows for ``attr``. Back color may be unset
        (automatic): show the tint that actually draws."""
        style = self._style()
        if attr == "back_color":
            from core.style import effective_back_color
            return effective_back_color(style, self._window.viewport.scene)
        return getattr(style, attr)

    def _swatch(self, title: str, attr: str) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(title)
        btn.clicked.connect(lambda: self._pick_color(title, attr))
        return btn

    @staticmethod
    def _css(color) -> str:
        r, g, b = (max(0, min(255, round(c * 255))) for c in color[:3])
        return (f"QAbstractButton {{ background: rgb({r},{g},{b}); "
                "min-height: 18px; }")

    def refresh(self) -> None:
        """Mirror the active style and the user library (called on loads,
        preset applies and saves via ``_sync_style_menu``)."""
        from core.style import BUILTIN_STYLES, user_styles
        style = self._style()
        users = user_styles()
        self._updating = True
        try:
            self._combo.clear()
            for p in BUILTIN_STYLES:
                self._combo.addItem(tr(p.name), p.name)
            if users:
                self._combo.insertSeparator(self._combo.count())
                for s in users:
                    self._combo.addItem(s.name, s.name)
            if style is None:
                return
            # -1 (nothing shown) when the active style matches no entry —
            # e.g. a document carrying a look that is in no library.
            self._combo.setCurrentIndex(self._combo.findData(style.name))
            self._mode.setCurrentIndex(
                self._mode.findData(style.face_mode))
            self._edges.setChecked(style.edges)
            self._profiles.setChecked(style.profiles)
            self._back_edges.setChecked(getattr(style, "back_edges", False))
            self._sky.setChecked(style.sky)
            self._fill.setChecked(style.section_fill)
            self._edge_c.setStyleSheet(self._css(style.edge_color))
            self._front_c.setStyleSheet(self._css(style.front_color))
            self._back_c.setStyleSheet(
                self._css(self._shown_color("back_color")))
            self._sky_c.setStyleSheet(self._css(style.sky_color))
            self._ground_c.setStyleSheet(self._css(style.ground_color))
            self._bg_c.setStyleSheet(self._css(style.background))
            self._fill_c.setStyleSheet(self._css(style.section_fill_color))
            self._ao.setChecked(getattr(style, "ambient_occlusion", False))
            self._ao_dist.setValue(
                self._ao_dist_pos(getattr(style, "ao_distance", 0.5)))
            self._ao_int.setValue(round(getattr(style, "ao_intensity", 1.0)
                                        * 10))
            self._sync_ao_controls()
            self._del_btn.setEnabled(
                any(s.name == self._combo.currentData() for s in users))
        finally:
            self._updating = False

    # ---- Actions ------------------------------------------------------------
    def _on_pick(self, index: int) -> None:
        from core.style import style_by_name
        picked = style_by_name(self._combo.itemData(index))
        if picked is None:
            return
        put = getattr(self._window, "set_active_style", None)
        if put is not None:
            put(picked)
        else:
            self._window.viewport.scene.display_style = picked
        self._window._sync_style_menu()          # menu + this panel
        self._repaint()

    def _apply_edits(self, *_a) -> None:
        if self._style() is None or self._updating:
            return
        style = self._own_style()
        style.face_mode = self._mode.currentData()
        style.edges = self._edges.isChecked()
        style.profiles = self._profiles.isChecked()
        style.back_edges = self._back_edges.isChecked()
        style.sky = self._sky.isChecked()
        style.section_fill = self._fill.isChecked()
        style.ambient_occlusion = self._ao.isChecked()
        style.ao_intensity = self._ao_int.value() / 10.0
        self._sync_ao_controls()
        self._window._sync_style_menu()
        self._repaint()

    _AO_DIST_STEPS = 200

    @classmethod
    def _ao_dist_at(cls, pos: int) -> float:
        """The distance a slider position stands for, rounded to what reads
        well in the field: centimetres under a metre, tenths to ten metres,
        whole metres beyond."""
        from core.style import AO_DISTANCE_RANGE
        lo, hi = AO_DISTANCE_RANGE
        v = lo * (hi / lo) ** (pos / cls._AO_DIST_STEPS)
        v = round(v, 2) if v < 1.0 else round(v, 1) if v < 10.0 else round(v)
        return min(max(v, lo), hi)

    @classmethod
    def _ao_dist_pos(cls, value: float) -> int:
        from core.style import AO_DISTANCE_RANGE
        lo, hi = AO_DISTANCE_RANGE
        value = min(max(value, lo), hi)
        return round(math.log(value / lo) / math.log(hi / lo)
                     * cls._AO_DIST_STEPS)

    def _on_ao_dist_slider(self, pos: int) -> None:
        # Only a drag writes the distance: a value from a file that sits
        # between two slider steps is kept as it is until then.
        if self._style() is None or self._updating:
            return
        style = self._own_style()
        style.ao_distance = self._ao_dist_at(pos)
        self._apply_edits()

    def _sync_ao_controls(self) -> None:
        """The distance and intensity follow the switch; a graphics driver
        that refused the pass this session greys the switch with the
        reason, instead of a box that does nothing."""
        on = self._ao.isChecked()
        for w in (self._ao_dist_lbl, self._ao_dist, self._ao_dist_val,
                  self._ao_int_lbl, self._ao_int, self._ao_int_val):
            w.setEnabled(on)
        # Both values read alike: a bare number, two decimals, the model's
        # decimal mark; the distance's unit goes once, in its label.
        from core import units
        u = units.model_unit()
        if u in ("in", "in-frac"):
            symbol = "in"
        elif u in ("ft", "ft-in", "ft-in-frac"):
            symbol = "ft"
        else:
            row = units.UNITS.get(u)
            symbol = row.symbol if row is not None else "m"
        self._ao_dist_lbl.setText(tr("Distance ({unit}):", unit=symbol))
        style = self._style()
        dist = units.length_number(getattr(style, "ao_distance", 0.5), u)
        self._ao_dist_val.setText(units.localized(f"{dist:.2f}"))
        self._ao_int_val.setText(
            units.localized(f"{self._ao_int.value() / 10.0:.2f}"))
        ao = getattr(self._window.viewport, "_ao", None)
        broken = getattr(ao, "broken", None)
        if broken:
            self._ao.setEnabled(False)
            self._ao.setToolTip(tr(
                "Your graphics driver cannot draw ambient occlusion "
                "({reason}).", reason=broken))

    def _pick_color(self, title: str, attr: str) -> None:
        style = self._style()
        if style is None:
            return
        c = self._shown_color(attr)
        chosen = get_color(
            QColor.fromRgbF(*(float(v) for v in c[:3])), _dialog_parent(self), title)
        if not chosen.isValid():
            return
        style = self._own_style()
        setattr(style, attr, (chosen.redF(), chosen.greenF(), chosen.blueF()))
        self.refresh()
        self._repaint()
        # Every colour is editable in every mode (build the look, save it) —
        # but an edit that can't show RIGHT NOW says so, or it reads as
        # "styles don't work" (it did, live, 2026-08-31).
        hint = self._color_hint(attr)
        if hint:
            bar = getattr(self._window, "statusBar", None)
            if callable(bar):
                bar().showMessage(hint, 4000)

    def _color_hint(self, attr: str) -> str | None:
        """Why the colour just edited may not be visible right now (``None``
        when it should be showing)."""
        style = self._style()
        if style is None:
            return None
        mode = style.face_mode
        if attr == "front_color" and mode == "wireframe":
            return tr("Front color saved — Wireframe draws no faces.")
        if attr == "back_color" and mode in ("hidden_line", "wireframe"):
            return tr("Back color saved — it paints back faces in Textures, "
                      "Shaded, Monochrome and X-ray modes.")
        if attr == "background" and style.sky:
            return tr("Background saved — it shows with the sky off.")
        if attr in ("sky_color", "ground_color") and not style.sky:
            return tr("Sky and ground colors show with the sky on.")
        if attr == "edge_color" and not style.edges and mode != "wireframe":
            return tr("Edge color saved — this style has edges off.")
        if attr == "section_fill_color" and not style.section_fill:
            return tr("Section fill color saved — section fill is off in "
                      "this style.")
        return None

    def _on_save(self) -> None:
        style = self._style()
        if style is None:
            return
        from core.style import builtin_names, save_user_style
        suggested = "" if style.name in builtin_names() else style.name
        parent = _dialog_parent(self)
        name, ok = _prompts.get_text(
            parent, tr("Save style"), tr("Style name:"), text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        if name in builtin_names():
            QMessageBox.warning(
                parent, tr("Save style"),
                tr("'{name}' is a built-in style — pick another name.",
                   name=name))
            return
        style = self._own_style()
        style.name = name        # the active style takes the saved identity
        save_user_style(style)
        self._window._sync_style_menu()
        self._window.statusBar().showMessage(
            tr("Style '{name}' saved.", name=name), 3000)

    def _on_delete(self) -> None:
        from core.style import delete_user_style
        name = self._combo.currentData()
        if not name:
            return
        if QMessageBox.question(
                _dialog_parent(self), tr("Delete style"),
                tr("Delete style '{name}'?", name=name)) != QMessageBox.Yes:
            return
        delete_user_style(name)
        self._window._sync_style_menu()


class ShadowsPanel(QWidget):
    """Shadow settings, driven by the REAL sun (core/sun.py):
    on/off, the local date and hour the sun stands at, and how dark the
    shade goes. Edits write ``scene.shadows`` (document data, saved in the
    ``.igz``) and repaint — the viewport re-derives the sun position and
    rebuilds its shadow map from the changed key, so dragging the time
    slider sweeps the shadows live: the asoleamiento study. The site is
    the model's geolocation; without one, Arequipa."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 6, 8, 8)

        self._enable = QCheckBox(tr("Show shadows"))
        self._enable.toggled.connect(self._apply)
        grid.addWidget(self._enable, 0, 0, 1, 2)

        grid.addWidget(QLabel(tr("Date:")), 1, 0)
        self._date = QDateEdit()
        self._date.setDisplayFormat("dd/MM")
        self._date.dateChanged.connect(self._on_date_edited)
        grid.addWidget(self._date, 1, 1)

        # The month bar: a day-of-year slider with the month initials
        # underneath — drag it and the asoleamiento sweeps the year.
        self._doy = QSlider(Qt.Horizontal)
        style_slider(self._doy)
        self._doy.setRange(1, 365)
        self._doy.valueChanged.connect(self._on_doy_slid)
        grid.addWidget(self._doy, 2, 0, 1, 2)
        months = QHBoxLayout()
        months.setSpacing(0)
        for initial in tr("J F M A M J J A S O N D").split():
            lbl = QLabel(initial)
            lbl.setAlignment(Qt.AlignCenter)
            theme_style(lbl, "color:{muted}; font-size: 10px;")
            months.addWidget(lbl, 1)
        grid.addLayout(months, 3, 0, 1, 2)

        grid.addWidget(QLabel(tr("Time:")), 4, 0)
        row = QHBoxLayout()
        self._time = QSlider(Qt.Horizontal)
        style_slider(self._time)
        # Range follows DAYLIGHT for the date/zone/site (the
        # slider runs sunrise → sunset, so the sun can never be dragged
        # below the horizon and "shadows silently off" cannot happen).
        self._time.setRange(0, 24 * 60 - 1)
        self._time.setSingleStep(5)
        self._time.valueChanged.connect(self._apply)
        row.addWidget(self._time, 1)
        self._time_lbl = QLabel("12:00")
        row.addWidget(self._time_lbl)
        grid.addLayout(row, 4, 1)

        span = QHBoxLayout()
        self._sunrise_lbl = QLabel("")
        theme_style(self._sunrise_lbl, "color:{muted}; font-size: 10px;")
        span.addWidget(self._sunrise_lbl)
        span.addStretch(1)
        self._sunset_lbl = QLabel("")
        theme_style(self._sunset_lbl, "color:{muted}; font-size: 10px;")
        span.addWidget(self._sunset_lbl)
        grid.addLayout(span, 5, 1)

        grid.addWidget(QLabel(tr("Darkness:")), 6, 0)
        self._dark = QSlider(Qt.Horizontal)
        style_slider(self._dark)
        self._dark.setRange(0, 80)              # 100 % black is never useful
        self._dark.valueChanged.connect(self._apply)
        grid.addWidget(self._dark, 6, 1)

        grid.addWidget(QLabel(tr("Time zone:")), 7, 0)
        self._tz = QComboBox()
        self._tz.addItem(tr("Automatic (by longitude)"), None)
        for off in range(-12, 15):
            self._tz.addItem(f"UTC{off:+03d}:00", off)
        self._tz.currentIndexChanged.connect(self._apply)
        grid.addWidget(self._tz, 7, 1)

        # Where true north lies (core.sun.scene_north_deg): typed here, or
        # aimed on screen with Tools ▸ North — the button picks it up.
        grid.addWidget(QLabel(tr("North:")), 8, 0)
        north_row = QHBoxLayout()
        self._north = QDoubleSpinBox()
        self._north.setRange(-180.0, 180.0)
        self._north.setDecimals(1)
        self._north.setSingleStep(1.0)
        self._north.setWrapping(True)
        self._north.setSuffix("°")
        self._north.setToolTip(tr(
            "Where true north lies, in degrees clockwise from the green (Y) "
            "axis. The shadows turn with it; the model does not move."))
        self._north.editingFinished.connect(self._on_north_edited)
        north_row.addWidget(self._north, 1)
        self._north_btn = QPushButton(tr("On screen"))
        self._north_btn.setToolTip(tr(
            "Tools ▸ North: click a centre, then click toward north."))
        self._north_btn.clicked.connect(self._on_north_tool)
        north_row.addWidget(self._north_btn)
        grid.addLayout(north_row, 8, 1)

        self._site = QLabel("")
        self._site.setWordWrap(True)
        theme_style(self._site, "color:{muted}; font-size: 11px;")
        grid.addWidget(self._site, 9, 0, 1, 2)

        self._locate_btn = QPushButton(tr("Add location…"))
        self._locate_btn.clicked.connect(self._on_add_location)
        grid.addWidget(self._locate_btn, 10, 0, 1, 2)

        self.refresh()

    def _shadows(self):
        return getattr(self._window.viewport.scene, "shadows", None)

    @staticmethod
    def _doy_of(month: int, day: int) -> int:
        import datetime
        try:
            return datetime.date(2026, month, day).timetuple().tm_yday
        except ValueError:
            return 80                       # Mar 21, the default

    @staticmethod
    def _month_day_of(doy: int) -> tuple[int, int]:
        import datetime
        d = (datetime.date(2026, 1, 1)
             + datetime.timedelta(days=max(1, min(365, doy)) - 1))
        return d.month, d.day

    def _site_latlon(self) -> tuple[float, float]:
        from core.sun import DEFAULT_LAT, DEFAULT_LON
        datum = getattr(self._window.viewport.scene, "georef", None)
        if datum is not None:
            return datum.lat, datum.lon
        return DEFAULT_LAT, DEFAULT_LON

    def _sync_daylight(self, sh, write_back: bool) -> None:
        """Fit the time slider to the day's sunlight for the current date,
        zone and site. With ``write_back`` the clamped slider value flows
        into ``sh`` (an edit moved the window from under the hour);
        without it only the range and labels move (a refresh must never
        mutate the document). Caller holds ``_updating``."""
        from core.sun import daylight_minutes
        lat, lon = self._site_latlon()
        try:
            rng = daylight_minutes(lat, lon, sh.month, sh.day, sh.utc_offset)
        except ValueError:
            rng = None
        if rng is None:                     # polar night: leave the full day
            self._time.setRange(0, 24 * 60 - 1)
            self._sunrise_lbl.setText("—")
            self._sunset_lbl.setText("—")
            return
        lo, hi = rng
        self._time.setRange(lo, hi)         # Qt clamps the value for us
        self._sunrise_lbl.setText(f"{lo // 60:02d}:{lo % 60:02d}")
        self._sunset_lbl.setText(f"{hi // 60:02d}:{hi % 60:02d}")
        if write_back:
            v = self._time.value()
            if (sh.hour, sh.minute) != (v // 60, v % 60):
                sh.hour, sh.minute = v // 60, v % 60
            self._time_lbl.setText(f"{sh.hour:02d}:{sh.minute:02d}")

    def refresh(self) -> None:
        sh = self._shadows()
        if sh is None:
            return
        from PySide6.QtCore import QDate
        self._updating = True
        try:
            self._enable.setChecked(sh.enabled)
            self._date.setDate(QDate(2026, sh.month, sh.day))
            self._doy.setValue(self._doy_of(sh.month, sh.day))
            self._sync_daylight(sh, write_back=False)
            self._time.setValue(sh.hour * 60 + sh.minute)
            self._time_lbl.setText(f"{sh.hour:02d}:{sh.minute:02d}")
            self._dark.setValue(round((1.0 - sh.darkness) * 100))
            idx = self._tz.findData(sh.utc_offset)
            self._tz.setCurrentIndex(idx if idx >= 0 else 0)
            from core.sun import scene_north_deg
            self._north.setValue(scene_north_deg(self._window.viewport.scene))
            datum = getattr(self._window.viewport.scene, "georef", None)
            if datum is not None:
                self._site.setText(tr(
                    "Sun at the model's geolocation ({lat:.3f}, {lon:.3f}).",
                    lat=datum.lat, lon=datum.lon))
            else:
                self._site.setText(tr(
                    "No geolocation — using Arequipa. Add the real site for "
                    "a true sun study."))
        finally:
            self._updating = False

    def showEvent(self, event) -> None:
        # The north may have been aimed on screen (or undone) since the
        # panel last dropped down.
        self.refresh()
        super().showEvent(event)

    def _on_north_edited(self) -> None:
        if self._updating:
            return
        from core.history import SetNorthCommand
        from core.sun import scene_north_deg
        from tools.north import refresh_north_display
        vp = self._window.viewport
        value = self._north.value()
        if abs(value - scene_north_deg(vp.scene)) < 1e-9:
            return
        vp.history.execute(SetNorthCommand(value))
        refresh_north_display(vp)

    def _on_north_tool(self) -> None:
        activate = getattr(self._window, "_activate_tool", None)
        if callable(activate):
            activate("north")

    def _on_date_edited(self, *_a) -> None:
        if self._updating:
            return
        d = self._date.date()
        self._updating = True
        self._doy.setValue(self._doy_of(d.month(), d.day()))
        self._updating = False
        self._apply()

    def _on_doy_slid(self, value: int) -> None:
        if self._updating:
            return
        from PySide6.QtCore import QDate
        month, day = self._month_day_of(value)
        self._updating = True
        self._date.setDate(QDate(2026, month, day))
        self._updating = False
        self._apply()

    def _on_add_location(self) -> None:
        """Add Location, scoped to the sun: pick the site on the
        map and it becomes the model's geographic datum (which is also what
        the Terrain workspace reads — one location, one truth)."""
        from georef.tiles import DEFAULT_SOURCE_ID, PRESETS
        from views.location_dialog import pick_location
        datum = getattr(self._window.viewport.scene, "georef", None)
        from core.sun import DEFAULT_LAT, DEFAULT_LON
        lat0 = datum.lat if datum is not None else DEFAULT_LAT
        lon0 = datum.lon if datum is not None else DEFAULT_LON
        result = pick_location(PRESETS[DEFAULT_SOURCE_ID], lat0, lon0,
                               _dialog_parent(self))
        if result is None:
            return
        lat, lon, _w, _l = result
        from core.sun import scene_north_deg
        from georef.datum import SceneDatum
        scene = self._window.viewport.scene
        # Tools ▸ North set before the location carries over.
        scene.georef = SceneDatum(lat, lon, north=scene_north_deg(scene))
        self._window.viewport.scene.version += 1
        self.refresh()
        self._window.viewport.update()

    def _apply(self, *_a) -> None:
        sh = self._shadows()
        if sh is None or self._updating:
            return
        sh.enabled = self._enable.isChecked()
        d = self._date.date()
        sh.month, sh.day = d.month(), d.day()
        v = self._time.value()
        sh.hour, sh.minute = v // 60, v % 60
        sh.darkness = 1.0 - self._dark.value() / 100.0
        sh.utc_offset = self._tz.currentData()
        self._time_lbl.setText(f"{sh.hour:02d}:{sh.minute:02d}")
        # A date/zone/site change moves the daylight window; the slider
        # follows it (and clamps the hour back into the sun).
        self._updating = True
        try:
            self._sync_daylight(sh, write_back=True)
        finally:
            self._updating = False
        act = getattr(self._window, "_act_shadows", None)
        if act is not None:
            act.blockSignals(True)
            act.setChecked(sh.enabled)
            act.blockSignals(False)
        # Version bump: marks the document dirty (the sun stance is DATA)
        # and the shadow-map key follows the settings on the next paint.
        self._window.viewport.scene.version += 1
        self._window.viewport.update()


class EntityInfoPanel(QWidget):
    """Facts about the current selection, plus the one thing an Entity
    Info panel lets you CHANGE here: the layer (its Tag field). Rafael
    went looking for it exactly here — «debo de tener que ir a las
    propiedades del objeto… no sé cómo cambiarlo de aquí» (2026-09-16,
    39:00) — and found only the Layers panel's button, which he did not
    understand."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import QComboBox, QHBoxLayout
        self._window = window
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self._label = QLabel(tr("Nothing selected"))
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.RichText)
        self._label.setStyleSheet("font-size: 12px;")
        lay.addWidget(self._label)
        # The name of ONE group or component, edited here — where everyone
        # looks for it (issue #214: «there seems to be no way to name this
        # group»). The Parts panel could already rename, out of sight.
        from PySide6.QtWidgets import QLineEdit
        from PySide6.QtWidgets import QSpinBox, QStackedWidget
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        self._name_caption = QLabel(tr("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setToolTip(
            tr("The name of the selected group or component — Enter keeps it"))
        self._name_edit.editingFinished.connect(self._on_name_edited)
        name_row.addWidget(self._name_caption)
        name_row.addWidget(self._name_edit, 1)
        self._named = None               # the group the field is showing
        # The segment count of ONE circle, arc or polygon, changed after
        # it is drawn — the «24s» of the tools only reaches the shape just
        # drawn. It shares the name's line: a curve is never a group, and
        # the panel keeps its height (see below).
        seg_row = QHBoxLayout()
        seg_row.setContentsMargins(0, 0, 0, 0)
        self._seg_caption = QLabel(tr("Sides:"))
        self._seg_box = QSpinBox()
        self._seg_box.setKeyboardTracking(False)      # one rebuild per entry
        self._seg_box.valueChanged.connect(self._on_segments_picked)
        seg_row.addWidget(self._seg_caption)
        seg_row.addWidget(self._seg_box)
        seg_row.addStretch(1)
        self._curve = None               # (edge, shape) the field is showing
        self._first_row = QStackedWidget()
        for row_lay in (name_row, seg_row):
            page = QWidget()
            page.setLayout(row_lay)
            self._first_row.addWidget(page)
        self._first_row.setSizePolicy(QSizePolicy.Preferred,
                                      QSizePolicy.Fixed)
        lay.addWidget(self._first_row)
        row = QHBoxLayout()
        self._layer_caption = QLabel(tr("Layer:"))
        self._layer_box = QComboBox()
        self._layer_box.setToolTip(
            tr("The layer the selection is on — pick another to move it"))
        self._layer_box.currentIndexChanged.connect(self._on_layer_picked)
        row.addWidget(self._layer_caption)
        row.addWidget(self._layer_box, 1)
        lay.addLayout(row)
        # A steady height. Selecting something used to resize this panel —
        # one line for nothing, two for an edge, four and a layer row for a
        # face — and everything below it (layers, scenes, the materials
        # library) slid up and down with every click (Marco, 23-09, four
        # screenshots). The layer row keeps its place when hidden, and the
        # text keeps room for the four lines a face or a solid shows.
        for w in (self._layer_caption, self._layer_box, self._first_row):
            pol = w.sizePolicy()
            pol.setRetainSizeWhenHidden(True)
            w.setSizePolicy(pol)
        # One caption column, so the name, count and layer fields start
        # at the same x (they sat at three different ones).
        fm = self._layer_caption.fontMetrics()
        cap_w = max(fm.horizontalAdvance(t) for t in (
            tr("Name:"), tr("Sides:"), tr("Segments:"), tr("Layer:"))) + 4
        for cap in (self._name_caption, self._seg_caption,
                    self._layer_caption):
            cap.setFixedWidth(cap_w)
        from PySide6.QtGui import QFont, QFontMetrics
        font = QFont(self._label.font())
        font.setPixelSize(12)
        self._label.setMinimumHeight(QFontMetrics(font).lineSpacing() * 4 + 4)
        self._layer_caption.hide()
        self._layer_box.hide()
        self._first_row.hide()

    def refresh(self) -> None:
        sel = list(self._window.viewport.scene.selection)
        self._label.setText(self._styled(self._describe(sel)))
        self._refresh_name(sel)
        self._refresh_segments(sel)
        self._first_row.setVisible(self._named is not None
                                   or self._curve is not None)
        self._refresh_layer(sel)

    # ---- Name field ---------------------------------------------------------
    def _refresh_name(self, sel: list) -> None:
        one = sel[0] if len(sel) == 1 and isinstance(sel[0], Group) else None
        changed = one is not self._named
        self._named = one
        if one is None:
            return
        self._first_row.setCurrentIndex(0)
        # Not while typing into it — unless the selection moved on.
        if changed or not self._name_edit.hasFocus():
            self._name_edit.setText(one.name or "")

    def _on_name_edited(self) -> None:
        group = self._named
        if group is None:
            return
        name = self._name_edit.text().strip()
        if not name or name == (group.name or ""):
            self._name_edit.setText(group.name or "")    # empty: keep it
            return
        from core.history import RenameGroupCommand
        self._window.viewport.history.execute(RenameGroupCommand(group, name))
        self._window.viewport.update()

    # ---- Segments field -----------------------------------------------------
    def _refresh_segments(self, sel: list) -> None:
        """One curve selected (its edges, all sharing one curve id) that
        reads back as a regular circle, arc or polygon."""
        from core.curve_segments import MAX_SEGMENTS, read_curve
        self._curve = None
        ids = {getattr(e, "curve", None) if isinstance(e, Edge) else None
               for e in sel}
        if len(ids) != 1 or None in ids:
            return
        mesh = self._window.viewport.scene.mesh
        shape = read_curve(mesh, sel[0])
        if shape is None or len(sel) != shape.segments:
            return
        self._curve = (sel[0], shape)
        self._first_row.setCurrentIndex(1)
        # «Sides» for a closed shape, as the Circle and Polygon tools
        # count them; «Segments» for an arc, as the Arc tool does.
        self._seg_caption.setText(tr("Sides:") if shape.closed
                                  else tr("Segments:"))
        self._seg_box.setEnabled(shape.flat)
        self._seg_box.setToolTip(
            tr("How many straight pieces the curve is made of — "
               "it is rebuilt in place")
            if shape.flat else
            tr("Only for a flat curve: this one also bounds faces out of "
               "its plane, such as the side of a pushed cylinder"))
        self._updating = True
        try:
            self._seg_box.setRange(shape.minimum, MAX_SEGMENTS)
            self._seg_box.setValue(shape.segments)
        finally:
            self._updating = False

    def _on_segments_picked(self, n: int) -> None:
        if self._updating or self._curve is None:
            return
        edge, shape = self._curve
        if n == shape.segments:
            return
        from core.curve_segments import ResegmentCurveCommand
        vp = self._window.viewport
        vp.history.execute(ResegmentCurveCommand(edge, n))
        vp.update()
        if getattr(vp.history, "last_rejected", None):
            self._window.statusBar().showMessage(
                tr("This curve cannot be rebuilt"), 2500)
        self.refresh()

    # ---- Layer field --------------------------------------------------------
    def _refresh_layer(self, sel: list) -> None:
        from core.layers import layer_of, taggable
        tagged = taggable(sel)
        show = bool(tagged)
        self._layer_caption.setVisible(show)
        self._layer_box.setVisible(show)
        if not show:
            return
        scene = self._window.viewport.scene
        names = [ly.name for ly in scene.layers]
        current = {layer_of(e) for e in tagged}
        self._updating = True
        try:
            self._layer_box.clear()
            if len(current) > 1:
                # A mixed selection reads as such; picking a layer moves
                # everything onto it.
                self._layer_box.addItem(tr("(several)"), None)
            for name in names:
                self._layer_box.addItem(name, name)
            if len(current) == 1:
                idx = self._layer_box.findData(next(iter(current)))
                self._layer_box.setCurrentIndex(max(idx, 0))
            else:
                self._layer_box.setCurrentIndex(0)
        finally:
            self._updating = False

    def _on_layer_picked(self, _index: int) -> None:
        if self._updating:
            return
        name = self._layer_box.currentData()
        if not name:
            return
        from core.history import AssignLayerCommand
        from core.layers import layer_of, taggable
        scene = self._window.viewport.scene
        targets = [e for e in taggable(scene.selection)
                   if layer_of(e) != name]
        if not targets:
            return
        self._window.viewport.history.execute(AssignLayerCommand(targets, name))
        self._window.viewport.update()
        self._window.statusBar().showMessage(
            tr("{n} entities moved to '{layer}'", n=len(targets), layer=name),
            2500)

    #: Past this many selected entities the totals are left out (#274).
    TOTALS_UP_TO = 20000

    def _describe(self, sel: list) -> str:
        if not sel:
            return tr("Nothing selected")
        if len(sel) == 1:
            e = sel[0]
            if isinstance(e, Face):
                mat = self._material_of(e)
                return (f"<b>{tr('Face')}</b><br>{tr('Area')}: {fmt_area(face_net_area(e))}<br>"
                        f"{tr('Vertices')}: {len(e.vertices)}<br>"
                        f"{tr('Material')}: {mat}")
            if isinstance(e, Edge):
                return (f"<b>{tr('Edge')}</b><br>"
                        f"{tr('Length')}: {fmt_len((e.b - e.a).length())}")
            if isinstance(e, Dimension):
                return f"<b>{tr('Dimension')}</b><br>{tr('Measure')}: {fmt_len(e.value())}"
            if isinstance(e, GeoPath):
                return self._describe_geopath(e)
            if isinstance(e, Group):
                # The usual «Solid Group» / «Solid Component» with its
                # volume, the Solid Tools' own test (core.solids).
                vol = self._solid_volume(e)
                solid = (f"<br>{tr('Volume')}: {fmt_volume(vol)}"
                         if vol is not None else "")
                if e.is_component():
                    # Entity Info usually tells a component from a group and
                    # says how many copies share the definition. Without it the
                    # two are indistinguishable here, which also made an import
                    # that flattened components impossible to spot.
                    kin = sum(1 for g in self._window.viewport.scene.groups
                              if g.mesh is e.mesh)
                    title = (tr("Solid Component") if vol is not None
                             else tr("Component"))
                    return (f"<b>{title}</b><br>"
                            f"{tr('Faces')}: {len(e.mesh.faces)}<br>"
                            f"{tr('In model')}: {kin}{solid}")
                title = tr("Solid Group") if vol is not None else tr("Group")
                return (f"<b>{title}</b><br>"
                        f"{tr('Faces')}: {len(e.mesh.faces)}{solid}")
            return f"<b>{tr('1 entity')}</b>"
        curve = self._describe_curve(sel)
        if curve is not None:
            return curve
        counts = {"faces": 0, "edges": 0, "dimensions": 0, "groups": 0}
        for e in sel:
            if isinstance(e, Face):
                counts["faces"] += 1
            elif isinstance(e, Edge):
                counts["edges"] += 1
            elif isinstance(e, Dimension):
                counts["dimensions"] += 1
            elif isinstance(e, Group):
                counts["groups"] += 1
        parts = [f"{n} {tr(k)}" for k, n in counts.items() if n]
        text = f"<b>{tr('Selection')}</b><br>" + ", ".join(parts)
        # The usual totals of a multiple selection: the faces' area and the
        # edges' length (#274) -- skipped past a size where summing them on
        # every selection change would slow the panel down.
        if len(sel) <= self.TOTALS_UP_TO:
            if counts["faces"]:
                area = sum(face_net_area(e) for e in sel
                           if isinstance(e, Face))
                text += f"<br>{tr('Area')}: {fmt_area(area)}"
            if counts["edges"]:
                length = sum((e.b - e.a).length() for e in sel
                             if isinstance(e, Edge))
                text += f"<br>{tr('Length')}: {fmt_len(length)}"
        return text

    @staticmethod
    def _styled(text: str) -> str:
        """The description as a data sheet: each «Label: value» line with
        its label in the muted colour, so the values stand out — the plain
        run of text read as one block."""
        import html
        import re
        from views.theme import tokens
        muted = tokens()["muted"]
        lines = text.split("<br>")
        for i, line in enumerate(lines):
            m = re.match(r"^([^<>:]+:)(\s.*)$", line)
            if m:
                lines[i] = (f'<span style="color:{muted}">'
                            f'{html.escape(m.group(1), quote=False)}</span>'
                            f'{m.group(2)}')
        return "<br>".join(lines)

    def _describe_curve(self, sel: list) -> str | None:
        """One whole circle, polygon or arc: named as such, with the
        measures one draws it by, rather than «Selection · 24 edges»."""
        from core.curve_segments import read_curve
        ids = {getattr(e, "curve", None) if isinstance(e, Edge) else None
               for e in sel}
        if len(ids) != 1 or None in ids:
            return None
        shape = read_curve(self._window.viewport.scene.mesh, sel[0])
        if shape is None or len(sel) != shape.segments:
            return None
        n = shape.segments
        side = (shape.verts[1].position - shape.verts[0].position).length()
        length = side * n
        if not shape.closed:
            import math
            return "<br>".join([
                f"<b>{tr('Arc')}</b>",
                f"{tr('Radius')}: {fmt_len(shape.radius)}",
                f"{tr('Angle')}: {math.degrees(shape.sweep):.1f}°",
                f"{tr('Length')}: {fmt_len(length)}"])
        # The Circle and Polygon tools draw the same thing, a regular
        # N-gon; from a dozen sides on it reads as a circle (the tools
        # default to 24 and 6).
        if n >= 12:
            return "<br>".join([
                f"<b>{tr('Circle')}</b>",
                f"{tr('Radius')}: {fmt_len(shape.radius)}",
                f"{tr('Diameter')}: {fmt_len(2.0 * shape.radius)}",
                f"{tr('Perimeter')}: {fmt_len(length)}"])
        return "<br>".join([
            f"<b>{tr('Polygon')}</b>",
            f"{tr('Radius')}: {fmt_len(shape.radius)}",
            f"{tr('Side')}: {fmt_len(side)}",
            f"{tr('Perimeter')}: {fmt_len(length)}"])

    def _solid_volume(self, group):
        """Cached per scene version: the panel refreshes on every change and
        the check walks the whole mesh."""
        from core.solids import solid_volume
        version = self._window.viewport.scene.version
        cache = getattr(self, "_solid_cache", None)
        if cache is None or cache[0] != version:
            cache = self._solid_cache = (version, {})
        if id(group) not in cache[1]:
            cache[1][id(group)] = solid_volume(group)
        return cache[1][id(group)]

    @staticmethod
    def _describe_geopath(path) -> str:
        kind = tr("Polygon") if path.closed else tr("Route")
        rows = [f"<b>{kind}</b>",
                f"{tr('Vertices')}: {len(path.points)}",
                f"{tr('Perimeter')}: {fmt_len(path.perimeter())}"]
        if path.closed:
            area = path.area()
            rows.append(f"{tr('Area (plan)')}: {fmt_area(area)} "
                        f"({area / 10000:.4f} ha)")
            sa = path.surface_area()
            if sa is not None:
                rows.append(f"{tr('Area (3D terrain)')}: {fmt_area(sa)}")
        return "<br>".join(rows)

    @staticmethod
    def _material_of(face) -> str:
        tex = face.attrs.get("texture")
        if tex and tex.get("path"):
            return Path(tex["path"]).stem
        col = face.attrs.get("color")
        if col is not None:
            # A swatch of the colour and its hex code, not a tuple of floats.
            hexa = "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}"
                                 for c in col[:3])
            return f'<span style="color:{hexa}">■</span> {hexa}'
        return "—"


class _ScrollAnchor(QObject):
    """Keeps what you are looking at still when a section ABOVE it changes
    height. Entity Info fills up when you select something, and everything
    below it — the materials library you had scrolled to — slid down by
    that much (Marco, 23-09: «la lista sigue saltando… cuando selecciono un
    componente se llena Info de entidad»). Browsers call it scroll
    anchoring: a section that grows or shrinks above the top of the view
    moves the scroll bar by the same amount."""

    def __init__(self, scroll: QScrollArea) -> None:
        super().__init__(scroll)
        self._scroll = scroll

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent, QTimer
        if event.type() == QEvent.Resize:
            delta = event.size().height() - event.oldSize().height()
            bar = self._scroll.verticalScrollBar()
            # Only a section wholly ABOVE the view: the one you are looking
            # at also resizes for a moment as the layout settles, and moving
            # for it too doubled the correction.
            if (delta and event.oldSize().height() > 0
                    and obj.y() + event.oldSize().height() <= bar.value()):
                target = bar.value() + delta
                # After the layout has taken the new height, or the bar's
                # range would clamp the move.
                QTimer.singleShot(0, lambda b=bar, t=target: b.setValue(t))
        return False


def _wrapping_check(text: str):
    """A check box whose text wraps: ``(checkbox, row widget)``. A long
    QCheckBox label is one line and sets the tray's minimum width; here the
    label is a word-wrapping QLabel beside a text-less box, and clicking the
    label toggles the box like a check box's own text would."""
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    check = QCheckBox()
    label = QLabel(text)
    label.setWordWrap(True)
    label.mousePressEvent = lambda _e: check.isEnabled() and check.toggle()
    box.addWidget(check, 0, Qt.AlignTop)
    box.addWidget(label, 1)
    return check, row


#: Combo boxes in a tray ask for this many characters, not their longest
#: item: «Esri World Imagery (satellite)» would otherwise set the width.
_COMBO_MIN_CHARS = 8


def _let_narrow(widget: QWidget) -> None:
    """Keep a tray's combo boxes from sizing the dock area to their longest
    item; the popup still shows every item in full."""
    for combo in widget.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(_COMBO_MIN_CHARS)


def _scrolled(sections) -> QScrollArea:
    """A scroll area wrapping a vertical stack of collapsible sections."""
    inner = QWidget()
    col = QVBoxLayout(inner)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    scroll = QScrollArea()
    anchor = _ScrollAnchor(scroll)
    for title, widget in sections:
        section = _Section(title, widget)
        section.installEventFilter(anchor)
        col.addWidget(section)
    col.addStretch(1)
    _let_narrow(inner)
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    scroll.setMinimumWidth(240)
    return scroll




#: Kill-switch: set INGETRAZO_SCENE_ALWAYS_BUMP=1 to bump ``scene.version``
#: on every scene recall, as before — also one that only moves the camera.
_SCENE_ALWAYS_BUMP = os.environ.get("INGETRAZO_SCENE_ALWAYS_BUMP", "") == "1"


#: The picture of a scene in the Scenes tab's thumbnails view — the size
#: the sheets' «Views and sheets» list draws them at.
_SCENE_THUMB = QSize(96, 64)


class _SceneNameDelegate(QStyledItemDelegate):
    """The name being typed in a box one line high, centred beside the
    picture, as in Layers' rows — not a box as tall as a thumbnail."""

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        super().updateEditorGeometry(editor, option, index)
        rect = editor.geometry()
        h = min(rect.height(), editor.sizeHint().height())
        rect.setTop(option.rect.center().y() - h // 2)
        rect.setHeight(h)
        editor.setGeometry(rect)


class _SceneTree(SideTree):
    """The Scenes tab's tree, taking drops of its own rows: dropped on a
    folder they go into it; dropped on a scene they go right before it, in
    its folder; on the empty space, out of any folder. Qt never moves a row
    by itself here: the document changes and the tree is rebuilt from it."""

    #: Delete belongs to the list while it has the focus.
    DELETE_KEY = True

    def drop_target(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return ("folder", None)
        kind, obj = item.data(0, Qt.UserRole)
        return ("folder", obj) if kind == "folder" else ("before", obj)

    def drop_items(self, token):
        kind, obj = token
        if kind == "before":
            row = self._panel.row_for(obj)
            return [row] if row is not None else []
        row = self._panel.folder_row(obj) if obj is not None else None
        if row is None:
            return []
        items, stack = [row], [row]
        while stack:
            node = stack.pop()
            if not node.isExpanded():
                continue
            for i in range(node.childCount()):
                child = node.child(i)
                if not child.isHidden():
                    items.append(child)
                    stack.append(child)
        return items

    def drop_text(self, token) -> str:
        kind, obj = token
        if kind == "before":
            return tr("Before «{name}»", name=obj.name)
        return (tr("Into «{folder}»", folder=obj) if obj is not None
                else tr("Out of any folder"))

    def apply_drop(self, token, rows) -> None:
        self._panel.drop_rows(token, rows)


class ScenesPanel(QWidget):
    """Saved views — "Scenes": named camera + layer-visibility
    snapshots. Double-click recalls one; the bar adds a scene from the
    current view or a folder, updates the selected scene, filters the
    list and switches between the list and the thumbnails; the
    right-click menu has every scene action. Together with
    layers this is the '2D that emerges' workflow bottled: "Planta" = top
    camera + parallel + plan layers, one click away.

    Its own tab of the side tray since #1158, with the bar of Layers and
    the Browser and their kind of tree: scenes filed in folders (inside
    folders, as deep as wanted) and dragged into them or to another place.
    Everything it changes goes through the undo history, and the menu runs
    the window's scene actions (Camera ▸ Scenes), the same ones the sheets'
    list runs."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtGui import QActionGroup
        from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout,
                                       QVBoxLayout)
        from views.icons import tool_icon
        self._window = window
        self._updating = False
        self._shape = None
        #: Folders folded shut by the user (by name).
        self._collapsed: set = set()
        #: The scene shown last from here, the sheets' list or a key: its
        #: row carries the mark (#1158, point 6).
        self.shown = None
        #: Scene pictures, by name and contents: a scene updated or renamed
        #: is drawn again; one that changed nothing is not.
        self._thumbs: dict = {}
        self._thumb_queue: list = []
        self._drawing = None              # the key of the picture in hand
        self._names = None                # the names the composer last got
        #: Pictures drawn before the model last changed: still shown, drawn
        #: again one by one while the tab is in sight.
        self._old: set = set()
        #: The model's content version the pictures show.
        self._model_seen = self._scene().content_version
        # A model edited: once it has been still for a moment (not at each
        # stroke of a drag), the pictures go old.
        from PySide6.QtCore import QTimer
        self._old_timer = QTimer(self)
        self._old_timer.setSingleShot(True)
        self._old_timer.setInterval(self.OLD_AFTER_MS)
        self._old_timer.timeout.connect(self._mark_old)
        # A picture that could not be drawn is asked for again a little
        # later, a few times: at start-up the view may not be ready to
        # draw yet, and the scene kept the camera for good.
        self._misses: dict = {}
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.setInterval(self.RETRY_AFTER_MS)
        self._retry_timer.timeout.connect(self._queue_thumbnails)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        # The add buttons, then the filter — the bar of Layers and the
        # Browser: flat tool buttons that raise on hover.
        bar = QHBoxLayout()
        self.add_btn = self._tool_button(
            "scene_add",
            tr("Save the current view and layer visibility"), self._on_add)
        self.add_folder_btn = self._tool_button(
            "folder_add", tr("Add folder"), self._on_add_folder)
        self.update_btn = self._tool_button(
            "refresh",
            tr("Update the selected scene from the current view"),
            self._on_update)
        bar.addWidget(self.add_btn)
        bar.addWidget(self.add_folder_btn)
        bar.addWidget(self.update_btn)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter scenes… (* and ? work)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._apply_filter())
        bar.addWidget(self.search, 1)
        # The list or the thumbnails: a picture of each scene, as the
        # sheets' list draws them — the thumbnails unless chosen otherwise.
        self.view_btn = QToolButton()
        self.view_btn.setAutoRaise(True)
        self.view_btn.setPopupMode(QToolButton.InstantPopup)
        self.view_btn.setToolTip(tr(
            "Show the scenes as a list or with a picture of each"))
        menu = QMenu(self.view_btn)
        group = QActionGroup(self)
        self.list_action = menu.addAction(tool_icon("scenes_list"), tr("List"))
        self.thumbs_action = menu.addAction(tool_icon("scenes_thumbs"),
                                            tr("Thumbnails"))
        self.list_action.setProperty("icon_key", "scenes_list")
        self.thumbs_action.setProperty("icon_key", "scenes_thumbs")
        for act in (self.list_action, self.thumbs_action):
            act.setCheckable(True)
            group.addAction(act)
        self.list_action.triggered.connect(
            lambda: self.set_thumbnails(False))
        self.thumbs_action.triggered.connect(
            lambda: self.set_thumbnails(True))
        self.view_btn.setMenu(menu)
        bar.addWidget(self.view_btn)
        lay.addLayout(bar)
        self.tree = _SceneTree(self)
        self.tree.setItemDelegate(_SceneNameDelegate(self.tree))
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setToolTip(tr("Double-click a scene to show it"))
        # Ctrl/Shift+click picks several rows; Delete removes them all in
        # one undo step (#280).
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.SelectedClicked
                                  | QAbstractItemView.EditKeyPressed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemExpanded.connect(lambda it: self._on_folded(it, True))
        self.tree.itemCollapsed.connect(lambda it: self._on_folded(it, False))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        # One place up or down within its folder, from the keyboard.
        from PySide6.QtGui import QAction, QKeySequence
        for keys, step in (("Alt+Up", -1), ("Alt+Down", 1)):
            move = QAction(self.tree)
            move.setShortcut(QKeySequence(keys))
            move.setShortcutContext(Qt.WidgetShortcut)
            move.triggered.connect(
                lambda _c=False, s=step: self._on_move(s))
            self.tree.addAction(move)
        lay.addWidget(self.tree, 1)
        self.thumbnails = self._saved_thumbnails()
        self._show_view_mode()
        self.refresh()

    @staticmethod
    def _tool_button(key: str, tip: str, slot) -> QToolButton:
        from views.icons import tool_icon
        btn = QToolButton()
        btn.setIcon(tool_icon(key))
        # Drawn in the theme's ink when made: named, so a change of theme
        # draws it again (views.theme._redraw_icons).
        btn.setProperty("icon_key", key)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        btn.clicked.connect(lambda _c=False: slot())
        return btn

    def _scene(self):
        return self._window.viewport.scene

    def _history(self):
        return self._window.viewport.history

    # ---- The list or the thumbnails -----------------------------------------
    @staticmethod
    def _saved_thumbnails() -> bool:
        from PySide6.QtCore import QSettings
        raw = QSettings().value("scenes/thumbnails", True)
        return raw not in (False, "false", "0", 0)

    def set_thumbnails(self, on: bool) -> None:
        """Show each scene with its picture (``True``) or as a plain list,
        and remember the choice."""
        from PySide6.QtCore import QSettings
        self.thumbnails = bool(on)
        QSettings().setValue("scenes/thumbnails", self.thumbnails)
        self._show_view_mode()
        self._shape = None
        self.refresh()

    def _show_view_mode(self) -> None:
        from views.icons import tool_icon
        self.thumbs_action.setChecked(self.thumbnails)
        self.list_action.setChecked(not self.thumbnails)
        key = "scenes_thumbs" if self.thumbnails else "scenes_list"
        self.view_btn.setIcon(tool_icon(key))
        self.view_btn.setProperty("icon_key", key)
        self.tree.setIconSize(_SCENE_THUMB if self.thumbnails
                              else QSize(16, 16))

    @staticmethod
    def _thumb_key(view) -> tuple:
        """What the picture shows: the name and the scene's contents, its
        folder aside (filing a scene changes no picture)."""
        import json
        data = {k: v for k, v in view.to_dict().items() if k != "folder"}
        return (view.name, json.dumps(data, sort_keys=True, default=str))

    def _folder_icon(self):
        """The folder of the rows. Among the pictures it keeps its own
        size, in the middle of a picture's room, instead of growing to it."""
        from views.outliner import node_icon
        icon = node_icon("folder")
        if not self.thumbnails:
            return icon
        from PySide6.QtGui import QPainter
        size = _SCENE_THUMB
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.drawPixmap((size.width() - 32) // 2, (size.height() - 32) // 2,
                     icon.pixmap(32, 32))
        p.end()
        return QIcon(pm)

    def _scene_icon(self, view):
        from views.outliner import node_icon
        if self.thumbnails:
            icon = self._thumbs.get(self._thumb_key(view))
            if icon is not None:
                return icon
        return node_icon("scene")

    def _queue_thumbnails(self) -> None:
        """Pictures of the scenes that have none yet, one at a time from the
        event loop — a render each, so the tab shows at once and fills in.
        Only while the tab is on screen: a hidden one draws them when it
        shows."""
        if not self.thumbnails or not self.isVisible():
            return
        from PySide6.QtCore import QTimer
        queued = bool(self._thumb_queue)
        # The one being drawn is not asked for again: a refresh while
        # it renders would queue it a second time.
        self._thumb_queue = [v for v in self._scene().saved_views
                             if (self._thumb_key(v) not in self._thumbs
                                 or self._thumb_key(v) in self._old)
                             and self._thumb_key(v) != self._drawing]
        if self._thumb_queue and not queued:
            QTimer.singleShot(0, self._next_thumbnail)

    def _next_thumbnail(self) -> None:
        from shiboken6 import isValid
        if not isValid(self) or not self._thumb_queue or not self.thumbnails:
            self._thumb_queue = []
            return
        view = self._thumb_queue.pop(0)
        if any(v is view for v in self._scene().saved_views):
            key = self._thumb_key(view)
            self._drawing = key
            try:
                icon = self._render_thumbnail(view)
            finally:
                self._drawing = None
            # Nothing drawn (no picture to be had): the camera stays, and
            # the scene is not asked for again until it changes. An old
            # picture that could not be drawn again is kept.
            if icon is None and key in self._old:
                icon = self._thumbs.get(key)
            if (icon is None
                    and self._misses.get(key, 0) < self.RETRIES):
                # Not noted as "has none": asked for again in a moment.
                self._misses[key] = self._misses.get(key, 0) + 1
                self._retry_timer.start()
                if self._thumb_queue:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(20, self._next_thumbnail)
                return
            if icon is not None:
                self._misses.pop(key, None)
            self._old.discard(key)
            self._thumbs[key] = icon
            if not self._old_timer.isActive() and not self._old:
                # Drawn from the model as it is now (an edit since would
                # have started the timer).
                self._model_seen = self._scene().content_version
            row = self.row_for(view)
            if icon is not None and row is not None:
                self._updating = True
                try:
                    row.setIcon(0, icon)
                finally:
                    self._updating = False
        if self._thumb_queue:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(20, self._next_thumbnail)

    def _render_thumbnail(self, view):
        """A picture of ``view`` — the render a sheet frame gets, through
        the (hidden) composer — or ``None``."""
        ensure = getattr(self._window, "_ensure_composer", None)
        if ensure is None:
            return None
        try:
            composer = ensure()
            # Its own pictures are kept by name: this one may have changed.
            composer.__dict__.get("_thumbs", {}).pop(view.name, None)
            return composer.scene_thumbnail(view.name)
        except Exception:                          # noqa: BLE001
            return None

    def refresh_thumbnails(self) -> None:
        """Draw every picture again (the model changed since)."""
        self._thumbs.clear()
        self._old.clear()
        self._misses.clear()
        self._model_seen = self._scene().content_version
        self._shape = None
        self.refresh()

    #: How long the model must stay still before the pictures go old.
    OLD_AFTER_MS = 1500
    #: A picture that could not be drawn: how many times it is asked for
    #: again, and how long after.
    RETRIES = 3
    RETRY_AFTER_MS = 400

    def _watch_model(self) -> None:
        """Called on every refresh: the model changed since the pictures
        were drawn → they go old once it has been still a moment."""
        version = self._scene().content_version
        if not any(icon is not None for icon in self._thumbs.values()):
            self._model_seen = version       # no picture yet: none is old
        elif version != self._model_seen:
            self._old_timer.start()          # (re)started: waits for calm

    def _mark_old(self) -> None:
        """Every picture old: each is shown until its new one is drawn —
        now if the tab is in sight, else when it shows."""
        from shiboken6 import isValid
        if not isValid(self):
            return
        self._model_seen = self._scene().content_version
        self._old = set(self._thumbs)
        self._queue_thumbnails()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().showEvent(event)
        self._queue_thumbnails()

    # ---- Model → view --------------------------------------------------------
    def refresh(self) -> None:
        from PySide6.QtWidgets import QTreeWidgetItem
        from core import scene_folders as SF
        from views.outliner import node_icon
        scene = self._scene()
        views = list(scene.saved_views)
        if self.shown is not None and not any(v is self.shown for v in views):
            self.shown = None
        folders = SF.folders_of(scene)
        # Rebuilt only when what the rows show changed: every edit of the
        # model calls here, and a rebuild drops the selection.
        shape = (tuple((id(v), v.name, SF.folder_of(scene, v))
                       for v in views),
                 tuple((f, SF.folder_parent(scene, f)) for f in folders),
                 id(self.shown), self.thumbnails)
        self._watch_model()
        if shape == self._shape:
            self._queue_thumbnails()
            self._follow(views)
            return
        self._shape = shape
        keep = {self._row_key(it) for it in self.tree.selectedItems()}
        current = self.tree.currentItem()
        current = self._row_key(current) if current is not None else None
        self._updating = True
        try:
            self.tree.clear()
            folder_icon = self._folder_icon()

            def level(parent, name) -> None:
                for f in SF.subfolders(scene, name):
                    item = QTreeWidgetItem([f])
                    item.setData(0, Qt.UserRole, ("folder", f))
                    item.setIcon(0, folder_icon)
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    self._add_row(parent, item)
                    level(item, f)
                    item.setExpanded(f not in self._collapsed)
                for view in SF.scenes_in(scene, name):
                    item = QTreeWidgetItem([view.name])
                    item.setData(0, Qt.UserRole, ("scene", view))
                    item.setIcon(0, self._scene_icon(view))
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    if view is self.shown:
                        font = item.font(0)
                        font.setBold(True)
                        item.setFont(0, font)
                        item.setToolTip(0, tr("The scene shown last"))
                    self._add_row(parent, item)
            level(None, None)
            for item in self._rows():
                key = self._row_key(item)
                if key == current:
                    self.tree.setCurrentItem(item)
                item.setSelected(key in keep)
        finally:
            self._updating = False
        self._apply_filter()
        self._queue_thumbnails()
        self._follow(views)

    def _follow(self, views) -> None:
        """The scene tabs under the viewport list the same scenes, in the
        same order; so do the view sources of the sheet composer — those
        only when the names changed, since every edit passes through here."""
        follow = getattr(self._window, "_refresh_scene_tabs", None)
        if callable(follow):
            follow()
        names = [v.name for v in views]
        if names != self._names:
            self._names = names
            composer = getattr(self._window, "_composer", None)
            reload = getattr(composer, "_reload_view_sources", None)
            if reload is not None:
                reload()

    def _add_row(self, parent, item) -> None:
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)

    @staticmethod
    def _row_key(item):
        kind, obj = item.data(0, Qt.UserRole)
        return (kind, id(obj) if kind == "scene" else obj)

    def _rows(self) -> list:
        """Every row, folders and scenes, from top to bottom."""
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        out = []
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            out.append(it.value())
            it += 1
        return out

    def scene_rows(self) -> list:
        """The scenes' rows, from top to bottom."""
        return [it for it in self._rows()
                if it.data(0, Qt.UserRole)[0] == "scene"]

    def row_for(self, view):
        """The row of scene ``view``, or None."""
        return next((it for it in self.scene_rows()
                     if it.data(0, Qt.UserRole)[1] is view), None)

    def folder_row(self, name):
        """The row of folder ``name``, or None."""
        return next((it for it in self._rows()
                     if it.data(0, Qt.UserRole) == ("folder", name)), None)

    def current_view(self):
        """The scene of the current row, or None (a folder or nothing)."""
        item = self.tree.currentItem()
        if item is None:
            return None
        kind, obj = item.data(0, Qt.UserRole)
        return obj if kind == "scene" else None

    def selected_views(self) -> list:
        return [it.data(0, Qt.UserRole)[1] for it in self.tree.selectedItems()
                if it.data(0, Qt.UserRole)[0] == "scene"]

    def _context_folder(self):
        """The folder a new scene or folder goes into: the current folder
        row, the folder of the current scene, or none."""
        item = self.tree.currentItem()
        if item is None or not item.isSelected():
            return None
        kind, obj = item.data(0, Qt.UserRole)
        if kind == "folder":
            return obj
        from core.scene_folders import folder_of
        return folder_of(self._scene(), obj)

    def _apply_filter(self) -> None:
        """Rows whose name passes the filter stay (``*`` and ``?`` as in
        Layers), with the folders on the way to them; a folder whose name
        passes shows all it holds. Filtered, the rows do not drag: a row
        dropped among hidden ones would land in a place nobody sees."""
        from PySide6.QtWidgets import QAbstractItemView
        from core.outliner import text_matches
        text = self.search.text().strip().casefold()

        def show(item, inherited: bool) -> bool:
            here = inherited or text_matches(item.text(0), text)
            kind = item.data(0, Qt.UserRole)[0]
            below = False
            for i in range(item.childCount()):
                below = show(item.child(i), here and kind == "folder") \
                    or below
            visible = here or below
            item.setHidden(not visible)
            if text and below and kind == "folder":
                item.setExpanded(True)
            return visible

        self._updating = True
        try:
            for i in range(self.tree.topLevelItemCount()):
                show(self.tree.topLevelItem(i), False)
            if not text:
                for item in self._rows():
                    kind, obj = item.data(0, Qt.UserRole)
                    if kind == "folder":
                        item.setExpanded(obj not in self._collapsed)
        finally:
            self._updating = False
        self.tree.setDragDropMode(QAbstractItemView.NoDragDrop if text
                                  else QAbstractItemView.InternalMove)

    def select_view(self, view) -> None:
        """Make ``view``'s row the current one (and the only one picked),
        its folders open."""
        self.refresh()
        row = self.row_for(view)
        self._select_row(row)

    def _select_row(self, row) -> None:
        self.tree.clearSelection()
        if row is None:
            return
        parent = row.parent()
        while parent is not None:
            self._collapsed.discard(parent.data(0, Qt.UserRole)[1])
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(row)
        row.setSelected(True)
        self.tree.scrollToItem(row)

    # ---- View → model --------------------------------------------------------
    def _on_folded(self, item, opened: bool) -> None:
        if self._updating:
            return
        kind, name = item.data(0, Qt.UserRole)
        if kind != "folder":
            return
        if opened:
            self._collapsed.discard(name)
        else:
            self._collapsed.add(name)

    def _on_double_click(self, item, _column=0) -> None:
        if item.data(0, Qt.UserRole)[0] == "scene":
            self._on_activate(item)

    def _on_context_menu(self, pos) -> None:
        menu = self.context_menu(self.tree.itemAt(pos))
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def context_menu(self, item) -> QMenu:
        """The right-click menu over ``item`` (``None``: the empty space
        under the rows). Over a scene, the window's scene actions (Camera ▸
        Scenes): the panel, the scene tabs and the sheets' list run the same
        ones (#1158, point 7). The row clicked becomes the one they act on."""
        if item is not None and not item.isSelected():
            self._select_row(item)
        acts = getattr(self._window, "_scene_actions", None) or {}
        menu = QMenu(self)
        kind = item.data(0, Qt.UserRole)[0] if item is not None else None
        if kind == "scene":
            keys = ("scene_show", "scene_update", None, "scene_rename",
                    "scene_duplicate", None, "scene_delete")
        else:
            keys = ("scene_add",)
        for key in keys:
            if key is None:
                menu.addSeparator()
            elif key in acts:
                menu.addAction(acts[key])
        if kind == "scene":
            from core import scene_folders as SF
            view = item.data(0, Qt.UserRole)[1]
            scene = self._scene()
            edit = getattr(self._window, "edit_scene_camera", None)
            if edit is not None:
                from views.icons import tool_icon
                act = menu.addAction(tool_icon("camera_settings"),
                                     tr("Camera Settings…"))
                act.setStatusTip(tr(
                    "Show this scene and set its camera: lens, shift, frame "
                    "and more. The changes are kept in the scene."))
                act.triggered.connect(lambda _c=False, v=view: edit(v))
            mates = list(SF.scenes_in(scene, SF.folder_of(scene, view)))
            at = next(i for i, v in enumerate(mates) if v is view)
            menu.addSeparator()
            up = menu.addAction(tr("Move up (Alt+↑)"),
                                lambda: self._on_move(-1))
            up.setEnabled(at > 0)
            down = menu.addAction(tr("Move down (Alt+↓)"),
                                  lambda: self._on_move(1))
            down.setEnabled(at < len(mates) - 1)
        if kind == "folder":
            menu.addAction(tr("Add folder"), self._on_add_folder)
            menu.addSeparator()
            menu.addAction(tr("Rename folder…"),
                           lambda: self.tree.editItem(item, 0))
            menu.addAction(tr("Delete folder"), self.delete_row)
        elif kind is None:
            menu.addAction(tr("Add folder"), self._on_add_folder)
        if self.thumbnails:
            menu.addSeparator()
            menu.addAction(tr("Refresh previews"), self.refresh_thumbnails)
        return menu

    def activate_view(self, view) -> None:
        """Show ``view`` — what a double-click on its row does."""
        row = self.row_for(view)
        if row is None:
            self._shape = None
            self.refresh()
            row = self.row_for(view)
        if row is not None:
            self._on_activate(row)
        else:
            # A view that is no scene of the list (the view as it was,
            # put back after an export showed another scene).
            self._show(view)

    def _on_activate(self, item, _column=0) -> None:
        kind, view = item.data(0, Qt.UserRole)
        if kind != "scene" or view is None:
            return
        self._show(view)

    def _show(self, view) -> None:
        scene = self._scene()
        self._begin_own()
        from core.saved_views import shown_state
        before = shown_state(scene)
        # With several views, the scene goes to the one worked in: its
        # camera, and its style as that view's own.
        w = self._window
        pick = getattr(w, "_active_view", None)
        vp = pick() if pick is not None else w.viewport
        if vp is w.viewport:
            keep = getattr(w, "keep_other_views_style", None)
            if keep is not None:          # the others keep their style
                keep()
            view.apply(scene, vp.camera)
        else:
            def own(style, vp=vp):
                vp.view_style = style
            view.apply(scene, vp.camera, own)
            vp.update()
        # A scene that only moves the camera changes nothing the caches
        # keyed on ``scene.version`` hold: bumping it re-synced every edge
        # and profile of the model (120 ms on a 1 M-face building) and
        # marked the document modified for a look around.
        changed = _SCENE_ALWAYS_BUMP or shown_state(scene) != before
        # The view may carry a style snapshot and a projection — keep the
        # menu and the projection buttons in step.
        sync = (getattr(self._window, "on_active_view_changed", None)
                or getattr(self._window, "_sync_style_menu", None))
        if sync is not None:
            sync()
        # Entities that just went invisible/unpickable leave the selection,
        # same as toggling their layer by hand.
        dead = [s for s in scene.selection
                if isinstance(s, (Face, Edge, Group))
                and not scene.entity_selectable(s)]
        for s in dead:
            scene.selection.discard(s)
        self.shown = view
        if changed:
            self._touch()
        else:
            self._window.viewport.update()
        self.refresh()
        dock = getattr(self._window, "layers_dock", None)
        if dock is not None:
            dock.panel.refresh()
        row = getattr(self._window, "_scene_tabs", None)
        if row is not None:
            row.mark_view(view)
        self._window.statusBar().showMessage(
            tr("Scene '{name}'", name=view.name), 2000)
        # The keyboard goes back to the model, as after a click on it: the
        # list kept the letters for its own search, so Z (Zoom), L (Line)…
        # pressed next did nothing, and «35mm» typed for Zoom was lost.
        self._window.viewport.setFocus(Qt.OtherFocusReason)

    def _on_item_changed(self, item, _column=0) -> None:
        if self._updating:
            return
        kind, obj = item.data(0, Qt.UserRole)
        new_name = item.text(0).strip()
        if kind == "scene":
            if obj is not None and new_name and new_name != obj.name:
                # Through the browser's rule: the sheet views that show
                # this scene follow the new name instead of losing it.
                self.rename(obj, new_name)
        elif new_name and new_name != obj:
            self.rename_folder(obj, new_name)
        self._shape = None
        self.refresh()

    def rename_view(self, view, name: str) -> bool:
        """Rename the scene ``view``, as one undo step (its row, the scene
        tabs, the composer's panel, Camera ▸ Scenes). False when nothing
        changed: an empty name, the same one, or another scene's."""
        name = (name or "").strip()
        if view is None or not name or name == view.name:
            return False
        return self.rename(view, name)

    def ask_rename(self, view, in_row: bool = False) -> None:
        """Ask for a new name of ``view`` in the program's name prompt (a
        scene tab: the name is asked where the user is). ``in_row`` (the
        panel's menu, Camera ▸ Scenes): in its row when the Scenes tab is
        in sight, as Layers and the Browser rename."""
        if view is None:
            return
        self.select_view(view)
        row = self.row_for(view)
        if (in_row and row is not None and self.tree.isVisible()
                and not row.isHidden()):
            self.tree.scrollToItem(row)
            self.tree.setCurrentItem(row)
            self.tree.editItem(row, 0)      # _on_item_changed renames
            return
        from views import prompts as _prompts
        name, ok = _prompts.get_text(
            self._window, tr("Rename Scene"), tr("Name:"), text=view.name)
        if ok:
            self.rename_view(view, name)

    def show_view(self, view) -> None:
        """Show the saved ``view`` (a click on a scene tab, Camera ▸
        Scenes ▸ Show): what a double-click on its row does."""
        if view is not None:
            self.activate_view(view)

    def rename(self, view, name: str) -> bool:
        """Rename ``view`` undoably; a name another scene has is refused
        with the Browser's message."""
        from core.saved_views import RenameSceneCommand
        history = self._history()
        self._begin_own()
        history.execute(RenameSceneCommand(view, name))
        if history.last_rejected is not None:
            self._window.statusBar().showMessage(tr(
                "Another scene is already called «{name}»",
                name=name.strip()), 3500)
            return False
        self.refresh()
        self._touch()
        return True

    def _tree_change(self, change) -> bool:
        """Run ``change(scene)`` (helpers of core.scene_folders) as one undo
        step; whether it changed anything."""
        from core import scene_folders as SF
        from core.history import SceneTreeCommand

        def run(scene) -> bool:
            before = SF.signature(scene)
            change(scene)
            return SF.signature(scene) != before
        history = self._history()
        self._begin_own()
        history.execute(SceneTreeCommand(run))
        if history.last_rejected is not None:
            return False
        self._shape = None
        self.refresh()
        self._touch()
        return True

    def rename_folder(self, old: str, new: str) -> bool:
        from core import scene_folders as SF
        new = new.strip()
        if not self._tree_change(lambda s: SF.rename_folder(s, old, new)):
            if new and new != old:
                self._window.statusBar().showMessage(tr(
                    "Another folder is already called «{name}»", name=new),
                    3500)
            return False
        if old in self._collapsed:
            self._collapsed.discard(old)
            self._collapsed.add(new)
        return True

    def _on_add_folder(self) -> None:
        """A new folder in the folder picked (or at the top), its name open
        to type over."""
        from core import scene_folders as SF
        parent = self._context_folder()
        made = []
        if not self._tree_change(lambda s: made.append(
                SF.add_folder(s, tr("Folder"), parent))):
            return
        row = self.folder_row(made[0]) if made else None
        self._select_row(row)
        if row is not None:
            self.tree.editItem(row, 0)

    def add_scene(self):
        """Keep the current view as a new scene («+» of the scene tabs):
        filed with the scene shown, since the panel may be out of sight;
        its tab is marked. The new scene."""
        from core import scene_folders as SF
        shown = self.shown
        folder = (SF.folder_of(self._scene(), shown)
                  if shown is not None else None)
        view = self._on_add(folder=folder)
        row = getattr(self._window, "_scene_tabs", None)
        if row is not None:
            row.mark_view(view)
        return view

    _CONTEXT = object()          # _on_add: the folder picked in the tree

    def _live_view(self):
        """The camera and style a new or updated scene takes: with several
        views, the active one's (its own camera, projection and style)."""
        w = self._window
        pick = getattr(w, "_active_view", None)
        vp = pick() if pick is not None else w.viewport
        active = getattr(w, "active_style", None)
        return vp.camera, (active() if active is not None else None)

    def _on_add(self, folder=_CONTEXT):
        """A scene from the current view, in the folder picked (or
        ``folder``); it becomes the current row. The new scene."""
        from core.history import AddSceneCommand
        from core.saved_views import SavedView
        scene = self._scene()
        if folder is ScenesPanel._CONTEXT:
            folder = self._context_folder()
        base = tr("Scene")
        n = 1
        taken = {v.name for v in scene.saved_views}
        while f"{base} {n}" in taken:
            n += 1
        camera, style = self._live_view()
        view = SavedView.capture(f"{base} {n}", scene, camera, style)
        view.folder = folder
        self._begin_own()
        self._history().execute(AddSceneCommand(view))
        self.select_view(view)
        self._touch()
        return view

    def _on_update(self) -> None:
        self.update_view(self.current_view())

    def update_view(self, view) -> None:
        """Keep the current view in the scene ``view``, as one undo step
        (the bar, the right-click menus, Camera ▸ Scenes)."""
        if view is None:
            return
        from core.history import UpdateSceneCommand
        self._begin_own()
        self._history().execute(
            UpdateSceneCommand(view, *self._live_view()))
        self._touch()
        self.refresh()                     # its picture is drawn again
        self._window.statusBar().showMessage(
            tr("Scene '{name}' updated", name=view.name), 2000)

    def drop_rows(self, token, rows) -> None:
        """Rows dropped: into a folder, or right before a scene in its
        folder — one undo step. The scene tabs and the sheets' list follow
        the new order."""
        from shiboken6 import isValid
        from core import scene_folders as SF
        rows = [r for r in rows if isValid(r)]
        views = [r.data(0, Qt.UserRole)[1] for r in rows
                 if r.data(0, Qt.UserRole)[0] == "scene"]
        folders = [r.data(0, Qt.UserRole)[1] for r in rows
                   if r.data(0, Qt.UserRole)[0] == "folder"]
        kind, obj = token
        scene = self._scene()
        if kind == "before":
            folder = SF.folder_of(scene, obj)
            before = None if any(obj is v for v in views) else obj
        else:
            folder, before = obj, None
        if folder is not None:
            self._collapsed.discard(folder)
        self._tree_change(lambda s: SF.move_rows(s, views, folders, folder,
                                                 before))

    def move_view(self, view, index: int) -> None:
        """Move ``view`` to ``index`` of the list (a scene tab dragged),
        as one undo step. Folders keep together: it lands right before the
        scene that comes after it there, in that scene's folder — what a
        drop on that row does; at the end, after the scene before it."""
        from core import scene_folders as SF
        scene = self._scene()
        if view is None or not any(v is view for v in scene.saved_views):
            return
        order = [v for v in scene.saved_views if v is not view]
        index = max(0, min(int(index), len(order)))
        if index < len(order):
            nxt = order[index]
            folder, before = SF.folder_of(scene, nxt), nxt
        else:
            prev = order[-1] if order else None
            folder = SF.folder_of(scene, prev) if prev is not None else None
            before = None
        self._tree_change(
            lambda s: SF.move_rows(s, [view], [], folder, before))

    def _on_move(self, step: int) -> None:
        """One place up or down for the current scene, among the scenes of
        its folder (Alt+↑/↓, the right-click menu)."""
        from core import scene_folders as SF
        view = self.current_view()
        if view is None:
            return
        scene = self._scene()
        folder = SF.folder_of(scene, view)
        mates = list(SF.scenes_in(scene, folder))
        at = next(i for i, v in enumerate(mates) if v is view)
        to = at + step
        if not 0 <= to < len(mates):
            return
        rest = [v for v in mates if v is not view]
        before = rest[to] if to < len(rest) else None
        self._tree_change(
            lambda s: SF.move_rows(s, [view], [], folder, before))
        self.select_view(view)

    def delete_row(self) -> None:
        """Delete (the key or the menu): the scenes picked go, one undo
        step; a folder goes and what it held stays, one level up."""
        folders = [it.data(0, Qt.UserRole)[1]
                   for it in self.tree.selectedItems()
                   if it.data(0, Qt.UserRole)[0] == "folder"]
        if not folders:
            self._on_delete()
            return
        from core import scene_folders as SF
        views = self.selected_views()

        def change(scene) -> None:
            for f in folders:
                SF.delete_folder(scene, f)
            scene.saved_views[:] = [v for v in scene.saved_views
                                    if not any(v is d for d in views)]
        self._tree_change(change)

    def _on_delete(self) -> None:
        views = self.selected_views()
        if not views:
            view = self.current_view()
            views = [view] if view is not None else []
        self.delete_views(views)

    def delete_views(self, views) -> None:
        """Delete these scenes, as one undo step (Delete, the menus)."""
        views = [v for v in views if v is not None]
        if not views:
            return
        from core.history import DeleteScenesCommand
        self._begin_own()
        self._history().execute(DeleteScenesCommand(views))
        self.refresh()
        self._touch()

    def _begin_own(self) -> None:
        """An edit of the scenes from here begins: it changes no picture
        but the ones it names (keyed by contents), so pictures up to date
        before it stay so after it — :meth:`_touch` closes it."""
        self._own_fresh = (
            self._scene().content_version == self._model_seen
            and not self._old_timer.isActive())

    def _touch(self) -> None:
        scene = self._scene()
        scene.version += 1
        if getattr(self, "_own_fresh", False):
            self._model_seen = scene.content_version
            self._old_timer.stop()
        self._own_fresh = False
        self._window.viewport.update()


class ScenesDock(QDockWidget):
    """Sidebar tab **Scenes**, beside Layers (#1158) — it was a section of
    Properties."""

    def __init__(self, window) -> None:
        super().__init__(tr("Scenes"), window)
        self.setObjectName("tray_scenes")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetClosable)
        self.panel = ScenesPanel(window)
        self.setWidget(self.panel)
        self.setMinimumWidth(240)

    def on_scene_changed(self) -> None:
        self.panel.refresh()


class BimPanel(QWidget):
    """BIM tagging (the thesis layer): mark the selected geometry as an IFC
    object — class + name — and read its LIVE quantities. Freeform stays
    freeform; a tag is metadata the takeoff (and the future IFC export)
    consumes. Untagged geometry is just drawing."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit,
                                       QPushButton, QTreeWidget, QVBoxLayout)
        self._window = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)

        row = QHBoxLayout()
        self.class_box = QComboBox()
        from core.bim import IFC_CLASSES
        self.class_box.addItems(IFC_CLASSES)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("Name (e.g. Wall axis A)"))
        row.addWidget(self.class_box)
        row.addWidget(self.name_edit, 1)
        lay.addLayout(row)

        btns = QHBoxLayout()
        tag_btn = QPushButton(tr("Tag selection"))
        tag_btn.setToolTip(tr(
            "Mark the selected faces / group as this IFC object"))
        tag_btn.clicked.connect(self._on_tag)
        untag_btn = QPushButton(tr("Untag"))
        untag_btn.clicked.connect(self._on_untag)
        btns.addWidget(tag_btn)
        btns.addWidget(untag_btn)
        btns.addStretch(1)
        lay.addLayout(btns)

        # Active class (tag-as-you-draw): while checked, every face you draw
        # is stamped with the class/name above, and pushing it extends the
        # tag to the whole solid. One BIM object per activation.
        self.active_check = QCheckBox(tr("Tag as you draw"))
        self.active_check.setToolTip(tr(
            "New geometry assumes this class while active — each trace "
            "becomes its own BIM object with this name"))
        self.active_check.toggled.connect(self._on_active_toggle)
        self.class_box.currentIndexChanged.connect(self._rearm_active)
        self.name_edit.editingFinished.connect(self._rearm_active)
        lay.addWidget(self.active_check)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("Class"), tr("Name"),
                                   tr("Takeoff"), tr("Vol m³")])
        # Rows sit in the groups that hold them, as the Browser shows them:
        # a tagged group is the parent of what is tagged inside it.
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(12)
        self.tree.setColumnWidth(0, 110)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 64)
        self.tree.itemClicked.connect(self._on_pick_object)
        self.tree.itemExpanded.connect(self._fit_tree)
        self.tree.itemCollapsed.connect(self._fit_tree)
        lay.addWidget(self.tree)

        exp = QPushButton(tr("Export quantities CSV…"))
        exp.setToolTip(tr(
            "The takeoff table — the bridge to IngePresupuestos"))
        exp.clicked.connect(self._on_export_csv)
        lay.addWidget(exp)
        self._objects: list = []
        self._containers: list = []
        self.refresh()

    def _scene(self):
        return self._window.viewport.scene

    def _fit_tree(self, *_a) -> None:
        """``fit_rows`` for the rows an open branch shows, not only the top."""
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        it = QTreeWidgetItemIterator(
            self.tree, QTreeWidgetItemIterator.NotHidden)
        rows = 0
        while it.value() is not None:
            item = it.value()
            p = item.parent()
            while p is not None and p.isExpanded():
                p = p.parent()
            rows += p is None
            it += 1
        fit_rows(self.tree, rows=rows)

    def _folded_groups(self) -> set:
        """The ``id`` of the group behind each folded row of the table."""
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        folded = set()
        it = QTreeWidgetItemIterator(self.tree)
        while it.value() is not None:
            item = it.value()
            if item.childCount() and not item.isExpanded():
                idx = item.data(0, Qt.UserRole)
                group = (self._containers[-idx - 1] if idx < 0
                         else self._objects[idx].get("group"))
                folded.add(id(group))
            it += 1
        return folded

    # ---- Actions -------------------------------------------------------------
    def _on_tag(self) -> None:
        from core.bim import next_object_id, tag_faces, tag_group
        scene = self._scene()
        faces = [s for s in scene.selection if isinstance(s, Face)]
        groups = [s for s in scene.selection if isinstance(s, Group)]
        cls = self.class_box.currentText()
        name = self.name_edit.text().strip()
        tagged = 0
        for g in groups:
            tag_group(g, cls, name or g.name)
            tagged += 1
        if faces:
            tag_faces(faces, cls, name, next_object_id(scene))
            tagged += 1
        if not tagged:
            self._window.statusBar().showMessage(
                tr("Select faces (or a group) to tag first"), 2500)
            return
        scene.version += 1
        self._window.viewport.update()
        self.refresh()

    def _on_active_toggle(self, checked: bool) -> None:
        scene = self._scene()
        if checked:
            cls = self.class_box.currentText()
            name = (self.name_edit.text().strip()
                    or cls.removeprefix("Ifc"))
            # Class + name only: each draw commit allocates its own object id
            # (one wall per trace = one BIM object, honest per-object metrado).
            scene.active_ifc = {"class": cls, "name": name}
            self._window.statusBar().showMessage(tr(
                "Drawing as {name} ({cls}) — new geometry assumes this tag",
                name=name, cls=cls), 4000)
        else:
            scene.active_ifc = None

    def _rearm_active(self, *_) -> None:
        """Changing class/name while active updates what new traces assume."""
        if self.active_check.isChecked():
            self._on_active_toggle(True)

    def _on_untag(self) -> None:
        from core.bim import untag_faces, untag_group
        scene = self._scene()
        untag_faces(s for s in scene.selection if isinstance(s, Face))
        for g in scene.selection:
            if isinstance(g, Group):
                untag_group(g)
        scene.version += 1
        self._window.viewport.update()
        self.refresh()

    def _on_pick_object(self, item, _col) -> None:
        """Clicking a row selects the object's geometry in the viewport; a
        group row selects that group."""
        idx = item.data(0, Qt.UserRole)
        if not isinstance(idx, int):
            return
        vp = self._window.viewport
        scene = self._scene()
        if idx < 0:
            self._pick_container(self._containers[-idx - 1])
            return
        if idx >= len(self._objects):
            return
        obj = self._objects[idx]
        # A grouped object is selected where it sits: the groups around it
        # open, as the Browser opens them to pick a nested row.
        target = obj.get("group") or obj.get("owner")
        if target is not None:
            from core import outliner
            from views.outliner import open_to
            path = outliner.path_to(scene.groups, target)
            if "owner" in obj and path is not None:
                path = path + [target]
            if path is None or not open_to(vp, path):
                vp.flash_status(tr(
                    "A group around it is hidden or locked: show or unlock "
                    "it to select inside"), 3500)
                return
        scene.selection.clear()
        if "group" in obj:
            scene.selection.add(obj["group"])
        elif "owner" in obj:
            # Opening a copy edits a world copy of its mesh: the faces are
            # found again by their tag.
            scene.selection.update(
                f for f in scene.mesh.faces
                if (f.attrs.get("ifc") or {}).get("id") == obj["tag_id"])
        else:
            scene.selection.update(obj["faces"])
        scene.bump_view()
        vp.update()

    def _pick_container(self, g) -> None:
        """Select an untagged group that holds tagged objects."""
        from core import outliner
        from views.outliner import open_to
        vp = self._window.viewport
        scene = self._scene()
        path = outliner.path_to(scene.groups, g)
        if path is None or not open_to(vp, path):
            vp.flash_status(tr(
                "A group around it is hidden or locked: show or unlock "
                "it to select inside"), 3500)
            return
        scene.selection.clear()
        scene.selection.add(g)
        scene.bump_view()
        vp.update()

    def _on_export_csv(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from core.bim import quantities_csv
        path, _ = file_dialogs.getSaveFileName(
            self, tr("Export quantities CSV"), "metrado.csv",
            tr("CSV (*.csv);;All files (*)"))
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(quantities_csv(self._scene()))
        self._window.statusBar().showMessage(
            tr("Quantities exported to {path}", path=path), 4000)

    # ---- Model → view ----------------------------------------------------------
    def refresh(self) -> None:
        from PySide6.QtWidgets import QTreeWidgetItem
        from core.bim import collect_objects
        from core.bim import class_quantities
        # File ▸ New (scene.clear) drops the active class — mirror it in the UI.
        if self.active_check.isChecked() and not self._scene().active_ifc:
            self.active_check.blockSignals(True)
            self.active_check.setChecked(False)
            self.active_check.blockSignals(False)
        # The takeoff reads geometry and tags, never the selection: a
        # view-only change (a click, a box selection) keeps the last one.
        # Re-measuring 238 rebar bars on every selection took 25 s (#857).
        scene = self._scene()
        key = (id(scene), scene.content_version)
        if key == getattr(self, "_takeoff_key", None):
            return
        self._takeoff_key = key
        # Nothing tagged at the last takeoff, and only commands that keep
        # every tag since (a Move, a Rotate): still nothing — without the
        # walk of every group (26 ms per edit on the 21 406 of #158).
        hist = getattr(self._window.viewport, "history", None)
        if (hist is not None and not self._objects
                and getattr(self, "_untagged_scene", None) == id(scene)
                and hist.tags_cv == scene.content_version):
            return
        # The rows are rebuilt below, and opening a group is a change of
        # content: what the user folded has to survive it (#1117).
        folded = self._folded_groups()
        # A memo per panel: an edit re-measures only the objects it touched.
        memo = self.__dict__.setdefault("_takeoff_memo", {})
        self._objects = collect_objects(scene, memo)
        self._untagged_scene = None if self._objects else id(scene)
        if hist is not None:
            hist.tags_cv = scene.content_version
        self.tree.clear()
        self._containers = []
        if not self._objects:
            # Nothing to hang from the groups: no map of the tree to build
            # (6.5 ms on the 21 406 groups of #158).
            self._fit_tree()
            return
        from core import outliner
        up = outliner.parents(scene.groups)
        # A tagged group's row is also the parent of what is tagged inside it.
        tagged_rows: dict = {}
        group_rows: dict = {}

        def row_for(g):
            """The row a group's tagged contents hang from (made on demand,
            with the rows of the groups around it)."""
            if g is None:
                return None
            row = tagged_rows.get(id(g)) or group_rows.get(id(g))
            if row is not None:
                return row
            row = QTreeWidgetItem([g.name or (
                tr("Component") if outliner.kind(g) == "component"
                else tr("Group"))])
            row.setData(0, Qt.UserRole, -len(self._containers) - 1)
            self._containers.append(g)
            font = row.font(0)
            font.setItalic(True)
            row.setFont(0, font)
            row.setToolTip(0, tr("Group — click to select it"))
            group_rows[id(g)] = row
            parent = row_for(up.get(id(g)))
            if parent is None:
                self.tree.addTopLevelItem(row)
            else:
                parent.addChild(row)
            row.setFirstColumnSpanned(True)
            return row

        for idx, obj in enumerate(self._objects):
            if "metrado" not in obj:
                faces = obj.get("faces")
                if faces is None:
                    faces = list(obj["group"].mesh.faces)
                # The takeoff column shows the class's budget measure (wall
                # face m², column m³, pile m, door und) — the number the
                # IFC/CSV export carries to IngePresupuestos, not the shell
                # area. Kept on the object, so a memoised one reuses it.
                obj["metrado"] = class_quantities(obj["class"], faces)[2]
            metrado, unit = obj["metrado"]
            pretty = {"m2": "m²", "m3": "m³"}.get(unit, unit)
            if metrado is None:
                met = "—"
            elif unit == "und":
                met = f"{metrado:.0f} {pretty}"
            else:
                met = f"{metrado:.2f} {pretty}"
            vol = "—" if obj["volume"] is None else f"{obj['volume']:.2f}"
            item = QTreeWidgetItem([
                obj["class"].removeprefix("Ifc"),
                obj["name"], met, vol])
            item.setData(0, Qt.UserRole, idx)
            if obj["volume"] is None:
                item.setToolTip(3, tr(
                    "Not watertight on its own — no volume"))
            if "group" in obj:
                g = obj["group"]
                stale = group_rows.pop(id(g), None)
                tagged_rows[id(g)] = item
                if stale is not None:
                    # Its contents came first: move them under the object row.
                    item.addChildren(stale.takeChildren())
                    (stale.parent() or self.tree.invisibleRootItem()
                     ).removeChild(stale)
                parent = row_for(up.get(id(g)))
            else:
                parent = row_for(obj.get("owner"))
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
        self.tree.expandAll()
        self.tree.blockSignals(True)            # one _fit_tree, below
        try:
            for rows in (tagged_rows, group_rows):
                for key, row in rows.items():
                    if key in folded:
                        row.setExpanded(False)
        finally:
            self.tree.blockSignals(False)
        self._fit_tree()


class Tray(QDockWidget):
    """Right-side **Properties** dock: what you're working with — the selection's
    info, materials, and annotation styles (context, not geo workspace)."""

    def __init__(self, window) -> None:
        super().__init__(tr("Properties"), window)
        self.setObjectName("tray_properties")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # Closable: without it Qt greys out the Window-menu entry, and a
        # tray the sidebar fold left hidden had no way back (Marco, 0.5.1).
        # The empty title bar shows no close button either way.
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)

        self.entity_info = EntityInfoPanel(window)
        self.materials = MaterialsPanel(window)
        self.components = ComponentsPanel(window)
        self.parts = PartsPanel(window)
        #: The Scenes panel: its own tab since #1158 (ScenesDock). The
        #: window sets it here once that tab is built, so
        #: ``tray.scenes`` keeps working for the Browser, the scene
        #: actions and extensions.
        self.scenes = None
        # Styles, Shadows and Dimension style are NOT here: they live in
        # their own on-demand docks (toolbar toggles) — the always-open tray
        # was drowning.
        self.setWidget(_scrolled([
            (tr("Entity info"), self.entity_info),
            (tr("Materials"), self.materials),
            (tr("Components"), self.components),
            (tr("Parts"), self.parts),
        ]))

    def on_scene_changed(self) -> None:
        self.entity_info.refresh()
        # The materials panel scans every render face for its swatches —
        # ~0.5 s on an exploded 28k-face mesh, paid per EDIT when run
        # inline. Debounced: one refresh 300 ms after the last edit.
        # Only when the document changed: a selection (a view-only bump)
        # leaves every material where it was, and on the plant of #158 the
        # scan of 32 million face paints after each click froze the window
        # for over a second.
        # Nor after a Move: a command that keeps paint (History.paint_cv)
        # leaves the swatches as they were (~0.4 s a drop on the plant).
        vp = self.materials._window.viewport
        cv = vp.scene.content_version
        if (cv != getattr(self.materials, "_in_model_cv", None)
                and cv != getattr(getattr(vp, "history", None),
                                  "paint_cv", None)):
            if (self.materials._window.isVisible()
                    and not self.materials.isVisible()):
                # Its tab not shown: refreshed on showing, as the
                # Components and Layers lists are (~0.15 s of every edit
                # on the plant of #158, for swatches nobody sees).
                self.materials._in_model_stale = True
                return self._after_materials()
            timer = getattr(self, "_mat_refresh_timer", None)
            if timer is None:
                from PySide6.QtCore import QTimer
                timer = self._mat_refresh_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self.materials.refresh_in_model)
            timer.start(300)
        self._after_materials()

    def _after_materials(self) -> None:
        self.components.on_scene_changed()
        self.parts.refresh()


class BimTray(QDockWidget):
    """Right-side **BIM** dock: the semantic workspace — tag geometry as IFC
    objects and read the live takeoff (kept apart from drawing properties,
    like the Georef workspace)."""

    def __init__(self, window) -> None:
        super().__init__(tr("BIM"), window)
        self.setObjectName("tray_bim")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # Closable: without it Qt greys out the Window-menu entry, and a
        # tray the sidebar fold left hidden had no way back (Marco, 0.5.1).
        # The empty title bar shows no close button either way.
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
        self.bim = BimPanel(window)
        self.setWidget(_scrolled([(tr("BIM tagging"), self.bim)]))

    def on_scene_changed(self) -> None:
        self.bim.refresh()


class SurveyPointsPanel(QWidget):
    """Import GPS / total-station points (the municipal flow's field data):
    a UTM CSV in the classic P,N,E,Z,desc layout becomes snappable reference
    markers. When the scene has no datum yet, the first point anchors it
    (the user supplies the UTM zone + hemisphere the CSV was surveyed in)."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout
        self._window = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self._count = QLabel()
        lay.addWidget(self._count)
        row = QHBoxLayout()
        imp = QPushButton(tr("Import CSV…"))
        imp.setToolTip(tr(
            "Survey CSV in UTM: point, north, east, elevation, description"))
        imp.clicked.connect(self._on_import)
        clear = QPushButton(tr("Clear"))
        clear.clicked.connect(self._on_clear)
        row.addWidget(imp)
        row.addWidget(clear)
        row.addStretch(1)
        lay.addLayout(row)
        self.refresh()

    def _scene(self):
        return self._window.viewport.scene

    def _on_import(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        from core.history import AddGeoPointsCommand
        from georef.points import (datum_for_rows, parse_points_csv,
                                   points_from_rows)
        path, _ = file_dialogs.getOpenFileName(
            self, tr("Import survey points CSV"), "",
            tr("CSV (*.csv *.txt);;All files (*)"))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                rows = parse_points_csv(fh.read())
        except (OSError, ValueError):
            self._window.statusBar().showMessage(tr(
                "Could not read survey points (expected P,N,E,Z,desc in UTM)"),
                5000)
            return
        scene = self._scene()
        datum = scene.georef
        new_datum = None
        if datum is None:
            # A bare CSV doesn't carry its UTM zone — ask, then anchor the
            # scene datum at the first point.
            zone, ok = QInputDialog.getInt(
                self, tr("UTM zone"),
                tr("UTM zone of the survey (Peru: 17-19):"), 18, 1, 60)
            if not ok:
                return
            hemi, ok = QInputDialog.getItem(
                self, tr("Hemisphere"), tr("Hemisphere:"),
                [tr("South"), tr("North")], 0, False)
            if not ok:
                return
            new_datum = datum_for_rows(rows, zone, hemi == tr("North"))
            datum = new_datum
        points = points_from_rows(rows, datum)
        self._window.viewport.history.execute(
            AddGeoPointsCommand(points, datum=new_datum))
        self._fit_to(points)
        self._window.statusBar().showMessage(
            tr("{n} survey points imported", n=len(points)), 4000)
        self._window.viewport.update()
        self.refresh()

    def _fit_to(self, points) -> None:
        if not points:
            return
        xs = [p.position.x() for p in points]
        ys = [p.position.y() for p in points]
        zs = [p.position.z() for p in points]
        from PySide6.QtGui import QVector3D
        pad = 5.0
        self._window.viewport.camera.fit_to(
            QVector3D(min(xs) - pad, min(ys) - pad, min(zs) - pad),
            QVector3D(max(xs) + pad, max(ys) + pad, max(zs) + pad))

    def _on_clear(self) -> None:
        from core.history import DeleteGeoPointsCommand
        scene = self._scene()
        if not scene.geo_points:
            return
        self._window.viewport.history.execute(
            DeleteGeoPointsCommand(list(scene.geo_points)))
        self._window.viewport.update()
        self.refresh()

    def refresh(self) -> None:
        n = len(getattr(self._scene(), "geo_points", []) or [])
        self._count.setText(tr("{n} points loaded", n=n))


class GeorefTray(QDockWidget):
    """Right-side **Terrain** dock: the location workspace — base map source,
    search/locate, capture area, 3D terrain (kept apart from properties).
    Renamed from "Georef" 2026-07-14: the trade's word, per the unified-flow
    architecture (terreno → trazo → BIM → presupuesto)."""

    def __init__(self, window) -> None:
        super().__init__(tr("Terrain"), window)
        self.setObjectName("tray_georef")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        # Closable: without it Qt greys out the Window-menu entry, and a
        # tray the sidebar fold left hidden had no way back (Marco, 0.5.1).
        # The empty title bar shows no close button either way.
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
        self.base_map = BaseMapPanel(window)
        self.survey = SurveyPointsPanel(window)
        self.setWidget(_scrolled([(tr("Base map"), self.base_map),
                                  (tr("Survey points"), self.survey)]))

    def on_scene_changed(self) -> None:
        self.base_map.on_scene_changed()
        self.survey.refresh()
