# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Right-side dockable tray (SketchUp-style), built from QDockWidget.

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

from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.mesh import Edge, Face
from core.group import Group
from core.dimension import Dimension
from georef.datum import SceneDatum
from georef.geopath import GeoPath
from georef.tiles import DEFAULT_SOURCE_ID, PRESETS, TileLayer, custom_source
from tools.paint import PaintTool

from core.paths import app_root

_TEX_DIR = app_root() / "resources" / "textures"
#: RAL Classic — the paint standard a drawing can be specified in. Its names
#: are the standard's own, in the standard's own languages, so they live in
#: the data file beside the colour instead of in the UI translations, where
#: "Beige" or "Cream" would collide with strings that mean something else.
_RAL_FILE = app_root() / "resources" / "colors" / "ral.json"
_SWATCH = 44  # swatch pixel size


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
        self._btn.setArrowType(Qt.DownArrow)
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

    def _on_toggle(self, on: bool) -> None:
        self._content.setVisible(on)
        self._btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)


def _color_pixmap(rgb, size=_SWATCH) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor.fromRgbF(*rgb))
    return pm


def _texture_pixmap(path, size=_SWATCH) -> QPixmap | None:
    img = QImage(str(path))
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

        grid.addWidget(QLabel(tr("Zoom:")), 8, 0)
        self._zoom = QSpinBox()
        self._zoom.setRange(1, 21)
        self._zoom.setValue(16)
        self._zoom.valueChanged.connect(self._on_zoom_changed)
        grid.addWidget(self._zoom, 8, 1)

        # Capture area (metres): set by drawing a rectangle in the locator
        # dialog. A square for a site, a long strip for a road. Kept as state,
        # not tray fields (the locator is where you define it).
        self._capture_w = 2400.0
        self._capture_l = 2400.0

        self._find = QPushButton(tr("Search location…"))
        self._find.clicked.connect(self._open_locator)
        grid.addWidget(self._find, 9, 0, 1, 2)

        self._go = QPushButton(tr("Go to location"))
        self._go.clicked.connect(self._go_to)
        grid.addWidget(self._go, 10, 0, 1, 2)

        self._show = QCheckBox(tr("Show base map"))
        self._show.setChecked(True)
        self._show.toggled.connect(self._on_toggle_visible)
        grid.addWidget(self._show, 11, 0, 1, 2)

        self._terrain3d = QCheckBox(tr("3D terrain"))
        self._terrain3d.toggled.connect(self._on_toggle_terrain)
        grid.addWidget(self._terrain3d, 12, 0, 1, 2)

        # The drone survey (Track G, G6). Disabled until one is imported —
        # a checkbox you can tick with nothing behind it just looks broken.
        self._photo_mesh = QCheckBox(tr("Photogrammetric survey"))
        self._photo_mesh.setEnabled(False)
        self._photo_mesh.toggled.connect(self._on_toggle_photo_mesh)
        grid.addWidget(self._photo_mesh, 13, 0, 1, 2)

        # Which layer the survey carries. The import puts it on its own so it
        # can be switched off without taking the model with it; this is for
        # moving it somewhere else (onto an existing "reference" layer, say).
        self._photo_layer = QComboBox()
        self._photo_layer.setEnabled(False)
        self._photo_layer.setToolTip(tr(
            "Layer the survey is on. Hiding that layer hides the survey."))
        self._photo_layer.currentTextChanged.connect(self._on_photo_layer_changed)
        grid.addWidget(QLabel(tr("Layer")), 14, 0)
        grid.addWidget(self._photo_layer, 14, 1)

        self._attribution = QLabel("")
        self._attribution.setWordWrap(True)
        self._attribution.setStyleSheet("color:#9aa3b2; font-size:10px; margin-top:4px;")
        grid.addWidget(self._attribution, 15, 0, 1, 2)

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
        name, ok = QInputDialog.getText(
            self, tr("New XYZ source"), tr("Source name:"))
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(
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
            datum = SceneDatum(self._lat.value(), self._lon.value(),
                               alt=keep_alt)
        scene.georef = datum
        layer = TileLayer(src, zoom=self._zoom.value())
        layer.set_rectangle(self._capture_w, self._capture_l)
        # Guard: a very large capture is capped in detail so it stays bounded.
        if layer.cap_detail(datum, max_tiles=500):
            self._window.viewport.flash_status(tr(
                "Large capture — detail reduced to zoom {z} to stay fast.")
                .format(z=layer.zoom))
        layer.visible = self._show.isChecked()
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

    def _on_toggle_visible(self, on: bool) -> None:
        layer = getattr(self._window.viewport.scene, "tile_layer", None)
        if layer is not None:
            layer.visible = on
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
                    (self._source, self._lat, self._lon, self._zoom, self._show)]
        if datum is not None:
            self._lat.setValue(datum.lat)
            self._lon.setValue(datum.lon)
            self._sync_utm_from_ll()
        if layer is not None:
            idx = self._source.findData(layer.source.id)
            if idx >= 0:
                self._source.setCurrentIndex(idx)
            self._zoom.setValue(layer.zoom)
            self._show.setChecked(layer.visible)
            self._attribution.setText(layer.source.attribution)
        else:
            self._attribution.setText(self._current_source().attribution
                                      if self._current_source() else "")
        del blockers  # release the signal blockers
        self._refresh_remove_btn()

    def on_scene_changed(self) -> None:
        self._sync_from_scene()


class ComponentsPanel(QWidget):
    """SketchUp-style components tray: a grid of clickable thumbnails.

    The thumbnails are STATIC images — the 2D people are their own PNGs and
    the 3D starters ship pre-rendered PNGs in ``resources/components/thumbs``
    (regenerate with the dev script if the models change) — so showing the
    panel costs a handful of pixmap loads and never touches the GL renderer."""

    COLS = 3

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtGui import QIcon
        self._window = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        grid = QGridLayout()
        grid.setSpacing(4)
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

        # "In model": what THIS drawing contains, the way SketchUp's
        # Components tray lists it. The grid above is a library to insert
        # from; it says nothing about what you already have, which is what
        # you actually look for when you want to find or re-place a piece.
        lay.addWidget(QLabel(f"<b>{tr('In model')}</b>"))
        self._in_model = QListWidget()
        self._in_model.setToolTip(tr(
            "Components placed in this drawing — click one to select its "
            "copies"))
        self._in_model.itemClicked.connect(self._select_component)
        lay.addWidget(self._in_model, 1)
        self.refresh_in_model()

    def _components_in_model(self) -> list:
        """``[(name, faces, [groups])]`` per distinct prototype, most copies
        first. Instances share their prototype mesh, so identity groups them —
        no geometry is walked."""
        by_proto: dict = {}
        for g in self._window.viewport.scene.groups:
            if not g.is_instance() or getattr(g, "billboard", False):
                continue
            by_proto.setdefault(id(g.mesh), []).append(g)
        rows = [(gs[0].name, len(gs[0].mesh.faces), gs)
                for gs in by_proto.values()]
        rows.sort(key=lambda r: (-len(r[2]), r[0].lower()))
        return rows

    def refresh_in_model(self) -> None:
        self._in_model.clear()
        for name, faces, gs in self._components_in_model():
            copies = len(gs)
            label = f"{name}  ({copies}×, {faces} " + tr("Faces").lower() + ")"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, gs)
            self._in_model.addItem(item)
        if self._in_model.count() == 0:
            self._in_model.addItem(QListWidgetItem(tr("No components yet")))

    def _select_component(self, item) -> None:
        groups = item.data(Qt.UserRole)
        if not groups:
            return
        scene = self._window.viewport.scene
        scene.selection.clear()
        scene.selection.update(groups)
        scene.version += 1
        self._window.viewport.update()


class MaterialsPanel(QWidget):
    """Swatch palette: pick a colour/texture to paint with."""

    COLS = 5

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._tile_size = 1.0
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)

        # Active material preview.
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Active:")))
        self._preview = QLabel()
        self._preview.setFixedSize(_SWATCH, _SWATCH)
        self._preview.setFrameShape(QFrame.Box)
        row.addWidget(self._preview)
        row.addStretch(1)
        root.addLayout(row)

        # SketchUp's "edit material": tile width/height + rotation, tucked
        # behind an Edit toggle so the panel stays clean. Edits the active
        # texture for future paints, and Apply re-stamps the selected
        # textured faces (undoable).
        from PySide6.QtWidgets import QDoubleSpinBox, QToolButton
        self._edit_toggle = QToolButton()
        self._edit_toggle.setText(tr("Edit texture"))
        self._edit_toggle.setCheckable(True)
        self._edit_toggle.setArrowType(Qt.RightArrow)
        self._edit_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._edit_toggle.setStyleSheet(
            "QToolButton { border: none; padding: 2px; }"
            "QToolButton:hover { background: palette(midlight); }")
        row.insertWidget(2, self._edit_toggle)
        self._edit_body = QWidget()
        edit_row = QHBoxLayout(self._edit_body)
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
        apply_btn = QPushButton(tr("Apply"))
        apply_btn.setToolTip(tr(
            "Resize/rotate the active texture; with textured faces selected, "
            "re-stamps them (undoable)"))
        apply_btn.clicked.connect(self._on_apply_texture_edit)
        edit_row.addWidget(apply_btn)
        self._edit_body.setVisible(False)

        def _toggle_edit(on):
            self._edit_body.setVisible(on)
            self._edit_toggle.setArrowType(Qt.DownArrow if on
                                           else Qt.RightArrow)
            if on:
                self._load_texture_fields()

        self._edit_toggle.toggled.connect(_toggle_edit)
        root.addWidget(self._edit_body)
        self._load_texture_fields()

        root.addWidget(self._heading(tr("In model")))
        self._in_model_grid = QGridLayout()
        self._in_model_grid.setSpacing(2)
        self._in_model_grid.setColumnStretch(self.COLS, 1)
        root.addLayout(self._in_model_grid)

        root.addWidget(self._heading(tr("Library")))
        self._fill_library_categories(root)

        btns = QHBoxLayout()
        add_color = QPushButton(tr("+ Color…"))
        add_color.clicked.connect(self._add_color)
        add_tex = QPushButton(tr("+ Texture…"))
        add_tex.clicked.connect(self._add_texture)
        btns.addWidget(add_color)
        btns.addWidget(add_tex)
        root.addLayout(btns)
        root.addStretch(1)

        self._refresh_preview()
        self.refresh_in_model()

    def _heading(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#9aa3b2; margin-top:6px; font-size:11px;")
        return lbl

    # ---- Library (categorised, SketchUp-style) -------------------------------
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
            btn.setArrowType(Qt.RightArrow)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            btn.setStyleSheet(
                "QToolButton { border: none; padding: 4px 2px;"
                " text-align: left; }"
                "QToolButton:hover { background: palette(midlight); }")
            body = QWidget()
            grid = QGridLayout(body)
            grid.setContentsMargins(4, 2, 0, 4)
            grid.setSpacing(2)
            # Pack swatches left: the leftover width goes to a phantom last
            # column instead of spreading the thumbnails apart.
            grid.setColumnStretch(self.COLS, 1)
            body.setVisible(False)

            pending = [fill]

            def toggle(on, b=btn, w=body, g=grid):
                if on and pending[0] is not None:
                    fn, pending[0] = pending[0], None
                    fn(g)
                w.setVisible(on)
                b.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

            btn.toggled.connect(toggle)
            root.addWidget(btn)
            root.addWidget(body)
            return grid

        # ONE Colours section (SketchUp has a Colors category too): RAL
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

    def refresh_in_model(self) -> None:
        """Rebuild the 'En el modelo' swatches from the materials in use."""
        while self._in_model_grid.count():
            item = self._in_model_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        colors: dict = {}
        textures: dict = {}
        opacities: dict = {}   # texture path → translucency (glass)
        names: dict = {}     # swatch key → material name (registry identity)
        for face in self._window.viewport.scene.render_faces():
            mat = face.attrs.get("mat")
            tex = face.attrs.get("texture")
            if tex and tex.get("path"):
                textures.setdefault(tex["path"], tex)
                if face.attrs.get("opacity") is not None:
                    opacities.setdefault(tex["path"],
                                         face.attrs.get("opacity"))
                if mat:
                    names.setdefault(("t", tex["path"]), mat)
            else:
                col = face.attrs.get("color")
                if col is not None:
                    colors[tuple(col)] = col
                    if mat:
                        names.setdefault(("c", tuple(col)), mat)
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
                # that wears it — right-click the swatch.
                b.setContextMenuPolicy(Qt.CustomContextMenu)
                b.customContextMenuRequested.connect(
                    lambda _pos, n=name, c=tuple(col):
                    self._edit_named_color(n, c))
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
            self._in_model_grid.addWidget(b, i // self.COLS, i % self.COLS)
            i += 1

    # ---- Apply / add --------------------------------------------------------
    def _apply_color(self, rgb, name: str | None = None) -> None:
        PaintTool.current_color = tuple(rgb)
        PaintTool.current_texture = None
        PaintTool.current_opacity = None
        PaintTool.current_material = self._material_for(
            name, color=tuple(rgb))
        self._window._activate_tool("paint")
        self._refresh_preview()

    def _edit_named_color(self, name: str, current_rgb) -> None:
        """Slice (b) of the registry track: edit a named colour material
        and restamp every face wearing it, one undoable step."""
        from core.history import RestampMaterialCommand
        from core.materials import Material
        scene = self._window.viewport.scene
        existing = scene.materials.get(name)
        base = (existing.color if existing and existing.color
                else tuple(current_rgb))
        chosen = QColorDialog.getColor(
            QColor.fromRgbF(*base[:3]), self,
            tr("Edit material: {name}", name=name))
        if not chosen.isValid():
            return
        new_mat = Material(
            name, color=(chosen.redF(), chosen.greenF(), chosen.blueF()),
            opacity=existing.opacity if existing else None)
        self._window.viewport.history.execute(
            RestampMaterialCommand(name, new_mat))
        self._window.viewport.notify_scene_changed()
        self._window.statusBar().showMessage(
            tr("Material '{name}' updated on every face that wears it",
               name=name), 3000)

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
        if tex:
            self._sw_box.setValue(float(tex.get("sw", 1.0)))
            self._sh_box.setValue(float(tex.get("sh", 1.0)))
            self._rot_box.setValue(float(tex.get("rot", 0.0)))
        else:
            self._sw_box.setValue(self._tile_size)
            self._sh_box.setValue(self._tile_size)
            self._rot_box.setValue(0.0)

    def _on_apply_texture_edit(self) -> None:
        """Push the W/H/Rot fields onto the active texture and onto any
        selected textured faces (one undoable step)."""
        from core.history import SetFaceTextureCommand
        sw = self._sw_box.value()
        sh = self._sh_box.value()
        rot = self._rot_box.value() % 360.0
        if PaintTool.current_texture:
            PaintTool.current_texture = {
                **PaintTool.current_texture, "sw": sw, "sh": sh, "rot": rot}
        scene = self._window.viewport.scene
        targets = [f for f in scene.selection
                   if isinstance(f, Face) and f.attrs.get("texture")]
        if targets:
            # Each face keeps its own image; only size/rotation change.
            from core.history import CompoundCommand
            cmds = []
            for f in targets:
                tex = {**f.attrs["texture"], "sw": sw, "sh": sh, "rot": rot}
                cmds.append(SetFaceTextureCommand([f], tex))
            cmd = cmds[0] if len(cmds) == 1 else CompoundCommand(cmds)
            self._window.viewport.history.execute(cmd)
            self._window.viewport.update()
            self._window.statusBar().showMessage(
                tr("Texture updated on {n} faces", n=len(targets)), 2500)
        elif not PaintTool.current_texture:
            self._window.statusBar().showMessage(
                tr("Pick a texture (or select textured faces) first"), 2500)
        self._refresh_preview()

    def _apply_texture(self, path: str, size: float | None = None,
                       sw: float | None = None,
                       sh: float | None = None,
                       name: str | None = None,
                       opacity: float | None = None) -> None:
        w = sw if sw is not None else (size or self._tile_size)
        h = sh if sh is not None else (size or self._tile_size)
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
        chosen = QColorDialog.getColor(QColor.fromRgbF(r, g, b), self, tr("Color"))
        if chosen.isValid():
            # Optional identity: a named colour becomes a registry material
            # (registered on first paint) and shows in per-material takeoffs.
            name, ok = QInputDialog.getText(
                self, tr("Color"), tr("Material name (optional):"))
            self._apply_color(
                (chosen.redF(), chosen.greenF(), chosen.blueF()),
                name=name.strip() if ok and name.strip() else None)

    def _add_texture(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
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

    def _refresh_preview(self) -> None:
        if PaintTool.current_texture is not None:
            pm = _texture_pixmap(PaintTool.current_texture["path"])
            if pm is not None:
                self._preview.setPixmap(pm)
                return
        self._preview.setPixmap(_color_pixmap(PaintTool.current_color))


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
        self._units.addItems(["m", "cm", "mm"])
        self._units.setCurrentText(style.get("units", "m"))
        self._units.currentTextChanged.connect(self._apply)
        grid.addWidget(self._units, 1, 1)

        grid.addWidget(QLabel(tr("Font:")), 2, 0)
        self._font = QSpinBox()
        self._font.setRange(6, 28)
        self._font.setValue(int(style.get("font_size", 9)))
        self._font.valueChanged.connect(self._apply)
        grid.addWidget(self._font, 2, 1)

        grid.addWidget(QLabel(tr("Color:")), 3, 0)
        self._color_btn = QPushButton()
        self._color_btn.clicked.connect(self._pick_color)
        grid.addWidget(self._color_btn, 3, 1)
        self._refresh_color_btn()

    def _style(self) -> dict:
        return self._window.viewport.scene.dimension_style

    def _apply(self) -> None:
        style = self._style()
        style["decimals"] = self._decimals.value()
        style["units"] = self._units.currentText()
        style["font_size"] = self._font.value()
        self._window.viewport.scene.version += 1
        self._window.viewport.update()

    def _pick_color(self) -> None:
        c = self._style().get("color", [45, 55, 75])
        chosen = QColorDialog.getColor(QColor(c[0], c[1], c[2]), self,
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
    """Live editor for ``scene.display_style`` — SketchUp's Styles panel.

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

        grid.addWidget(QLabel(tr("Front color:")), 4, 0)
        self._front_c = self._swatch(
            tr("Front color — paints faces in Hidden line and Monochrome"),
            "front_color")
        grid.addWidget(self._front_c, 4, 1)

        self._sky = QCheckBox(tr("Sky"))
        self._sky.toggled.connect(self._apply_edits)
        grid.addWidget(self._sky, 5, 0)
        self._sky_c = self._swatch(tr("Sky color"), "sky_color")
        grid.addWidget(self._sky_c, 5, 1)

        grid.addWidget(QLabel(tr("Ground:")), 6, 0)
        self._ground_c = self._swatch(tr("Ground color"), "ground_color")
        grid.addWidget(self._ground_c, 6, 1)

        grid.addWidget(QLabel(tr("Background:")), 7, 0)
        self._bg_c = self._swatch(
            tr("Background — visible with the sky off"), "background")
        grid.addWidget(self._bg_c, 7, 1)

        self._fill = QCheckBox(tr("Section Fill"))
        self._fill.toggled.connect(self._apply_edits)
        grid.addWidget(self._fill, 8, 0)
        self._fill_c = self._swatch(tr("Section fill color"),
                                    "section_fill_color")
        grid.addWidget(self._fill_c, 8, 1)

        row = QHBoxLayout()
        save_btn = QPushButton(tr("Save style…"))
        save_btn.clicked.connect(self._on_save)
        row.addWidget(save_btn)
        self._del_btn = QPushButton(tr("Delete"))
        self._del_btn.clicked.connect(self._on_delete)
        row.addWidget(self._del_btn)
        grid.addLayout(row, 9, 0, 1, 2)

        self.refresh()

    # ---- Plumbing -----------------------------------------------------------
    def _style(self):
        return getattr(self._window.viewport.scene, "display_style", None)

    def _swatch(self, title: str, attr: str) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(title)
        btn.clicked.connect(lambda: self._pick_color(title, attr))
        return btn

    @staticmethod
    def _css(color) -> str:
        r, g, b = (max(0, min(255, round(c * 255))) for c in color[:3])
        return f"background: rgb({r},{g},{b}); min-height: 18px;"

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
            self._sky.setChecked(style.sky)
            self._fill.setChecked(style.section_fill)
            self._edge_c.setStyleSheet(self._css(style.edge_color))
            self._front_c.setStyleSheet(self._css(style.front_color))
            self._sky_c.setStyleSheet(self._css(style.sky_color))
            self._ground_c.setStyleSheet(self._css(style.ground_color))
            self._bg_c.setStyleSheet(self._css(style.background))
            self._fill_c.setStyleSheet(self._css(style.section_fill_color))
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
        self._window.viewport.scene.display_style = picked
        self._window._sync_style_menu()          # menu + this panel
        self._window.viewport.update()

    def _apply_edits(self, *_a) -> None:
        style = self._style()
        if style is None or self._updating:
            return
        style.face_mode = self._mode.currentData()
        style.edges = self._edges.isChecked()
        style.profiles = self._profiles.isChecked()
        style.sky = self._sky.isChecked()
        style.section_fill = self._fill.isChecked()
        self._window._sync_style_menu()
        self._window.viewport.update()

    def _pick_color(self, title: str, attr: str) -> None:
        style = self._style()
        if style is None:
            return
        c = getattr(style, attr)
        chosen = QColorDialog.getColor(
            QColor.fromRgbF(*(float(v) for v in c[:3])), self, title)
        if not chosen.isValid():
            return
        setattr(style, attr, (chosen.redF(), chosen.greenF(), chosen.blueF()))
        self.refresh()
        self._window.viewport.update()
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
        if attr == "front_color" and mode not in ("hidden_line", "monochrome"):
            return tr("Front color saved — it paints faces in Hidden line "
                      "and Monochrome modes.")
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
        name, ok = QInputDialog.getText(
            self, tr("Save style"), tr("Style name:"), text=suggested)
        name = name.strip()
        if not ok or not name:
            return
        if name in builtin_names():
            QMessageBox.warning(
                self, tr("Save style"),
                tr("'{name}' is a built-in style — pick another name.",
                   name=name))
            return
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
                self, tr("Delete style"),
                tr("Delete style '{name}'?", name=name)) != QMessageBox.Yes:
            return
        delete_user_style(name)
        self._window._sync_style_menu()


class EntityInfoPanel(QWidget):
    """Read-only facts about the current selection."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self._label = QLabel(tr("Nothing selected"))
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.RichText)
        self._label.setStyleSheet("font-size: 12px;")
        lay.addWidget(self._label)

    def refresh(self) -> None:
        sel = list(self._window.viewport.scene.selection)
        self._label.setText(self._describe(sel))

    def _describe(self, sel: list) -> str:
        if not sel:
            return tr("Nothing selected")
        if len(sel) == 1:
            e = sel[0]
            if isinstance(e, Face):
                mat = self._material_of(e)
                return (f"<b>{tr('Face')}</b><br>{tr('Area')}: {e.area():.3f} m²<br>"
                        f"{tr('Vertices')}: {len(e.vertices)}<br>"
                        f"{tr('Material')}: {mat}")
            if isinstance(e, Edge):
                return (f"<b>{tr('Edge')}</b><br>"
                        f"{tr('Length')}: {(e.b - e.a).length():.3f} m")
            if isinstance(e, Dimension):
                return f"<b>{tr('Dimension')}</b><br>{tr('Measure')}: {e.value():.3f} m"
            if isinstance(e, GeoPath):
                return self._describe_geopath(e)
            if isinstance(e, Group):
                if e.is_instance():
                    # SketchUp's Entity Info tells a component from a group and
                    # says how many copies share the definition. Without it the
                    # two are indistinguishable here, which also made an import
                    # that flattened components impossible to spot.
                    kin = sum(1 for g in self._window.viewport.scene.groups
                              if g.mesh is e.mesh)
                    return (f"<b>{tr('Component')}</b><br>"
                            f"{tr('Name')}: {e.name}<br>"
                            f"{tr('Faces')}: {len(e.mesh.faces)}<br>"
                            f"{tr('In model')}: {kin}")
                return f"<b>{tr('Group')}</b><br>{tr('Faces')}: {len(e.mesh.faces)}"
            return f"<b>{tr('1 entity')}</b>"
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
        return f"<b>{tr('Selection')}</b><br>" + ", ".join(parts)

    @staticmethod
    def _describe_geopath(path) -> str:
        kind = tr("Polygon") if path.closed else tr("Route")
        rows = [f"<b>{kind}</b>",
                f"{tr('Vertices')}: {len(path.points)}",
                f"{tr('Perimeter')}: {path.perimeter():.2f} m"]
        if path.closed:
            area = path.area()
            rows.append(f"{tr('Area (plan)')}: {area:.2f} m² "
                        f"({area / 10000:.4f} ha)")
            sa = path.surface_area()
            if sa is not None:
                rows.append(f"{tr('Area (3D terrain)')}: {sa:.2f} m²")
        return "<br>".join(rows)

    @staticmethod
    def _material_of(face) -> str:
        tex = face.attrs.get("texture")
        if tex and tex.get("path"):
            return Path(tex["path"]).stem
        col = face.attrs.get("color")
        if col is not None:
            return f"color {tuple(round(c, 2) for c in col)}"
        return "—"


def _scrolled(sections) -> QScrollArea:
    """A scroll area wrapping a vertical stack of collapsible sections."""
    inner = QWidget()
    col = QVBoxLayout(inner)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)
    for title, widget in sections:
        col.addWidget(_Section(title, widget))
    col.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    scroll.setMinimumWidth(240)
    return scroll




class LayersPanel(QWidget):
    """Layers / tags (Fase 6): one row per layer with visibility and lock
    checkboxes; buttons to add / remove layers and to move the current
    selection onto a layer. Hiding layers of one model is the '2D that
    emerges' workflow: plan = top view + parallel projection + the right
    layers on."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import (QHBoxLayout, QPushButton, QTreeWidget,
                                       QTreeWidgetItem, QVBoxLayout)
        self._window = window
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("Name"), tr("Visible"), tr("Lock")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 120)
        self.tree.setColumnWidth(1, 52)
        self.tree.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        add_btn = QPushButton(tr("+ Layer"))
        add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton(tr("−"))
        del_btn.setToolTip(tr("Delete layer (its entities go to the default)"))
        del_btn.clicked.connect(self._on_delete)
        assign_btn = QPushButton(tr("Assign selection"))
        assign_btn.setToolTip(tr("Move the selected entities to this layer"))
        assign_btn.clicked.connect(self._on_assign)
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addStretch(1)
        row.addWidget(assign_btn)
        lay.addLayout(row)
        self.refresh()

    # ---- Model → view --------------------------------------------------------
    def refresh(self) -> None:
        from PySide6.QtWidgets import QTreeWidgetItem
        from core.layers import DEFAULT_LAYER
        self._updating = True
        self.tree.clear()
        for ly in self._window.viewport.scene.layers:
            item = QTreeWidgetItem([ly.name, "", ""])
            item.setData(0, Qt.UserRole, ly.name)
            flags = item.flags() | Qt.ItemIsUserCheckable
            if ly.name != DEFAULT_LAYER:
                flags |= Qt.ItemIsEditable
            item.setFlags(flags)
            item.setCheckState(1, Qt.Checked if ly.visible else Qt.Unchecked)
            item.setCheckState(2, Qt.Checked if ly.locked else Qt.Unchecked)
            self.tree.addTopLevelItem(item)
        self._updating = False

    # ---- View → model --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _on_item_changed(self, item, column) -> None:
        if self._updating:
            return
        scene = self._scene()
        old_name = item.data(0, Qt.UserRole)
        ly = scene.layer(old_name)
        if ly is None:
            return
        if column == 0:
            new_name = item.text(0).strip()
            if new_name and new_name != old_name \
                    and scene.layer(new_name) is None:
                self._rename(ly, old_name, new_name)
            self.refresh()
            self._touch()
            return
        ly.visible = item.checkState(1) == Qt.Checked
        ly.locked = item.checkState(2) == Qt.Checked
        if not ly.visible or ly.locked:
            self._prune_selection(ly.name)
        self._touch()

    def _rename(self, ly, old_name: str, new_name: str) -> None:
        from core.layers import layer_of, assign_layer
        scene = self._scene()
        ly.name = new_name
        for ent in list(scene.mesh.faces) + list(scene.mesh.edges) \
                + list(scene.groups):
            if layer_of(ent) == old_name:
                assign_layer(ent, new_name)

    def _prune_selection(self, name: str) -> None:
        from core.layers import layer_of
        scene = self._scene()
        dead = [s for s in scene.selection
                if isinstance(s, (Face, Edge, Group)) and layer_of(s) == name]
        for s in dead:
            scene.selection.discard(s)

    def _on_add(self) -> None:
        from core.layers import Layer
        scene = self._scene()
        base = tr("Layer")
        n = 1
        while scene.layer(f"{base} {n}") is not None:
            n += 1
        scene.layers.append(Layer(f"{base} {n}"))
        self.refresh()
        self._touch()

    def _on_delete(self) -> None:
        from core.layers import DEFAULT_LAYER, layer_of, assign_layer
        scene = self._scene()
        item = self.tree.currentItem()
        if item is None:
            return
        name = item.data(0, Qt.UserRole)
        if name == DEFAULT_LAYER:
            return                                  # the default is permanent
        ly = scene.layer(name)
        if ly is None:
            return
        for ent in list(scene.mesh.faces) + list(scene.mesh.edges) \
                + list(scene.groups):
            if layer_of(ent) == name:
                assign_layer(ent, DEFAULT_LAYER)
        scene.layers.remove(ly)
        self.refresh()
        self._touch()

    def _on_assign(self) -> None:
        from core.layers import assign_layer
        scene = self._scene()
        item = self.tree.currentItem()
        if item is None:
            return
        name = item.data(0, Qt.UserRole)
        moved = 0
        for ent in scene.selection:
            if isinstance(ent, (Face, Edge, Group)):
                assign_layer(ent, name)
                moved += 1
        if moved:
            self._touch()
            self._window.statusBar().showMessage(
                tr("{n} entities moved to '{layer}'", n=moved, layer=name),
                2500)

    def _touch(self) -> None:
        scene = self._scene()
        scene.version += 1
        self._window.viewport.update()




class ScenesPanel(QWidget):
    """Saved views — SketchUp's "Scenes": named camera + layer-visibility
    snapshots. Double-click recalls one; the buttons capture the current
    view, update the selected scene from it, or delete it. Together with
    layers this is the '2D that emerges' workflow bottled: "Planta" = top
    camera + parallel + plan layers, one click away."""

    def __init__(self, window) -> None:
        super().__init__()
        from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                                       QPushButton, QVBoxLayout)
        self._window = window
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        hint = QLabel(tr("Double-click a scene to show it"))
        hint.setStyleSheet("color: gray;")
        lay.addWidget(hint)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._on_activate)
        self.list.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        add_btn = QPushButton(tr("+ Scene"))
        add_btn.setToolTip(tr("Save the current view and layer visibility"))
        add_btn.clicked.connect(self._on_add)
        upd_btn = QPushButton(tr("Update"))
        upd_btn.setToolTip(tr("Update the selected scene from the current view"))
        upd_btn.clicked.connect(self._on_update)
        del_btn = QPushButton(tr("−"))
        del_btn.setToolTip(tr("Delete the selected scene"))
        del_btn.clicked.connect(self._on_delete)
        row.addWidget(add_btn)
        row.addWidget(upd_btn)
        row.addStretch(1)
        row.addWidget(del_btn)
        lay.addLayout(row)
        self.refresh()

    def _scene(self):
        return self._window.viewport.scene

    # ---- Model → view --------------------------------------------------------
    def refresh(self) -> None:
        from PySide6.QtWidgets import QListWidgetItem
        self._updating = True
        self.list.clear()
        for view in self._scene().saved_views:
            item = QListWidgetItem(view.name)
            item.setData(Qt.UserRole, view)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.list.addItem(item)
        self._updating = False

    # ---- View → model --------------------------------------------------------
    def _on_activate(self, item) -> None:
        view = item.data(Qt.UserRole)
        if view is None:
            return
        scene = self._scene()
        view.apply(scene, self._window.viewport.camera)
        # The view may carry a style snapshot — keep the menu in step.
        sync = getattr(self._window, "_sync_style_menu", None)
        if sync is not None:
            sync()
        # Entities that just went invisible/unpickable leave the selection,
        # same as toggling their layer by hand.
        dead = [s for s in scene.selection
                if isinstance(s, (Face, Edge, Group))
                and not scene.entity_selectable(s)]
        for s in dead:
            scene.selection.discard(s)
        self._touch()
        self._window.tray.layers.refresh()
        self._window.statusBar().showMessage(
            tr("Scene '{name}'", name=view.name), 2000)

    def _on_item_changed(self, item) -> None:
        if self._updating:
            return
        view = item.data(Qt.UserRole)
        new_name = item.text().strip()
        if view is not None and new_name:
            view.name = new_name
        self.refresh()
        self._touch()

    def _on_add(self) -> None:
        from core.saved_views import SavedView
        scene = self._scene()
        base = tr("Scene")
        n = 1
        taken = {v.name for v in scene.saved_views}
        while f"{base} {n}" in taken:
            n += 1
        scene.saved_views.append(SavedView.capture(
            f"{base} {n}", scene, self._window.viewport.camera))
        self.refresh()
        self._touch()

    def _on_update(self) -> None:
        item = self.list.currentItem()
        view = item.data(Qt.UserRole) if item is not None else None
        if view is None:
            return
        view.recapture(self._scene(), self._window.viewport.camera)
        self._touch()
        self._window.statusBar().showMessage(
            tr("Scene '{name}' updated", name=view.name), 2000)

    def _on_delete(self) -> None:
        item = self.list.currentItem()
        view = item.data(Qt.UserRole) if item is not None else None
        if view is None:
            return
        scene = self._scene()
        if view in scene.saved_views:
            scene.saved_views.remove(view)
        self.refresh()
        self._touch()

    def _touch(self) -> None:
        scene = self._scene()
        scene.version += 1
        self._window.viewport.update()


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
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 82)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 64)
        self.tree.itemClicked.connect(self._on_pick_object)
        lay.addWidget(self.tree)

        exp = QPushButton(tr("Export quantities CSV…"))
        exp.setToolTip(tr(
            "The takeoff table — the bridge to IngePresupuestos"))
        exp.clicked.connect(self._on_export_csv)
        lay.addWidget(exp)
        self._objects: list = []
        self.refresh()

    def _scene(self):
        return self._window.viewport.scene

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
        """Clicking a row selects the object's geometry in the viewport."""
        idx = self.tree.indexOfTopLevelItem(item)
        if not (0 <= idx < len(self._objects)):
            return
        obj = self._objects[idx]
        scene = self._scene()
        scene.selection.clear()
        if "group" in obj:
            scene.selection.add(obj["group"])
        else:
            scene.selection.update(obj["faces"])
        scene.version += 1
        self._window.viewport.update()

    def _on_export_csv(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        from core.bim import quantities_csv
        path, _ = QFileDialog.getSaveFileName(
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
        self._objects = collect_objects(self._scene())
        self.tree.clear()
        for obj in self._objects:
            faces = obj.get("faces")
            if faces is None:
                faces = list(obj["group"].mesh.faces)
            # The takeoff column shows the class's budget measure (wall face
            # m², column m³, pile m, door und) — the number the IFC/CSV
            # export carries to IngePresupuestos, not the shell area.
            _, _, (metrado, unit) = class_quantities(obj["class"], faces)
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
            if obj["volume"] is None:
                item.setToolTip(3, tr(
                    "Not watertight on its own — no volume"))
            self.tree.addTopLevelItem(item)


class Tray(QDockWidget):
    """Right-side **Properties** dock: what you're working with — the selection's
    info, materials, and annotation styles (context, not geo workspace)."""

    def __init__(self, window) -> None:
        super().__init__(tr("Properties"), window)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)

        self.entity_info = EntityInfoPanel(window)
        self.materials = MaterialsPanel(window)
        self.components = ComponentsPanel(window)
        self.layers = LayersPanel(window)
        self.scenes = ScenesPanel(window)
        self.styles = StylesPanel(window)
        self.dim_style = DimensionStylePanel(window)
        self.setWidget(_scrolled([
            (tr("Entity info"), self.entity_info),
            (tr("Layers"), self.layers),
            (tr("Scenes"), self.scenes),
            (tr("Styles"), self.styles),
            (tr("Materials"), self.materials),
            (tr("Components"), self.components),
            (tr("Dimension style"), self.dim_style),
        ]))

    def on_scene_changed(self) -> None:
        self.entity_info.refresh()
        # The materials panel scans every render face for its swatches —
        # ~0.5 s on an exploded 28k-face mesh, paid per EDIT when run
        # inline. Debounced: one refresh 300 ms after the last edit.
        timer = getattr(self, "_mat_refresh_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._mat_refresh_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.materials.refresh_in_model)
        timer.start(300)
        self.layers.refresh()
        self.scenes.refresh()
        self.components.refresh_in_model()


class BimTray(QDockWidget):
    """Right-side **BIM** dock: the semantic workspace — tag geometry as IFC
    objects and read the live takeoff (kept apart from drawing properties,
    like the Georef workspace)."""

    def __init__(self, window) -> None:
        super().__init__(tr("BIM"), window)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)
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
        path, _ = QFileDialog.getOpenFileName(
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
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetFloatable)
        self.base_map = BaseMapPanel(window)
        self.survey = SurveyPointsPanel(window)
        self.setWidget(_scrolled([(tr("Base map"), self.base_map),
                                  (tr("Survey points"), self.survey)]))

    def on_scene_changed(self) -> None:
        self.base_map.on_scene_changed()
        self.survey.refresh()
