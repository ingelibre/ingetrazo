# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood (OpenSKP) — IngeTrazo plugin contribution.
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Model Info plugin — model statistics in a dialog (Extensions menu).

A tabbed breakdown of the open document: geometry counts, bounding box,
materials in use, layers, BIM objects, and its geographic location — the
one place in it that changes the document (set or clear the location, one
undo step, as SketchUp's Model Info ▸ Geo-location). The numbers agree
with the rest of the application because they come from the same sources:

- geometry reads ``scene.loose_mesh`` (NOT ``scene.mesh``, which is swapped
  while a group is open for editing — reading it would double-count);
- materials mirror the Paint tray's idiom: ``attrs["color"]`` (floats 0–1)
  and ``attrs["texture"]`` on each face — IngeTrazo has no material
  registry to query;
- BIM objects come from :func:`core.bim.collect_objects`, the same call
  behind the BIM tray and the IFC export, so a six-face wall with one tag
  is ONE ``IfcWall`` here too — with its area and (when the face set is
  watertight) its volume;
- lengths are formatted by the dimension style (unit + precision), so the
  dialog speaks the same units as the rest of the document;
- the location is ``scene.georef`` — the one the sun, the base map and the
  terrain read; it is set with the same map locator as Shadows ▸ Add
  location… (:func:`views.location_dialog.pick_location`).
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import bim
from core.i18n import tr
from tools.base import Tool
from core.units import fmt_area, fmt_volume


# ---------------------------------------------------------------------------
# Statistics collection (pure data, no GUI — see tests/test_model_info_plugin)
# ---------------------------------------------------------------------------

def _fmt_len(metres: float, style: dict) -> str:
    """A length in the document's dimension style (Viewport's formatter)."""
    from views.viewport import Viewport
    return Viewport._format_dim_value(metres, style)


def _location(scene):
    """The model's geographic location as plain numbers, or None."""
    datum = getattr(scene, "georef", None)
    if datum is None:
        return None
    from georef.datum import utm_forward
    east, north = utm_forward(datum.lat, datum.lon, datum.zone)
    return {"lat": datum.lat, "lon": datum.lon, "alt": datum.alt,
            "zone": datum.zone, "northern": datum.northern,
            "east": east, "north": north,
            "north_deg": float(getattr(datum, "north", 0.0) or 0.0)}


def _location_anchored(scene) -> bool:
    """Whether the document holds things placed by its location — survey
    points, traced paths, a drone survey: moving or clearing the location
    from here would leave them behind, so the Terrain panel does that."""
    return bool(getattr(scene, "geo_points", None)
                or getattr(scene, "geo_paths", None)
                or getattr(scene, "photo_mesh", None) is not None)


def _location_rows(loc) -> list[tuple[str, str]]:
    """(label, value) rows of a location, labels without their colon."""
    def label(text):
        return tr(text).rstrip(" :：")
    hemi = "N" if loc["northern"] else "S"
    return [
        (label("Latitude:"), f"{loc['lat']:.6f}°"),
        (label("Longitude:"), f"{loc['lon']:.6f}°"),
        (label("UTM zone:"), f"{loc['zone']}{hemi}"),
        (label("UTM E:"), f"{loc['east']:.2f} m"),
        (label("UTM N:"), f"{loc['north']:.2f} m"),
        (label("North:"), f"{loc['north_deg']:.1f}°"),
    ]


def _collect_stats(scene) -> dict:
    """Walk the document and return a statistics dictionary (raw numbers;
    formatting happens at display time with the dimension style)."""
    loose = scene.loose_mesh          # the real loose mesh, group open or not
    groups = scene.groups

    loose_verts = len(loose.vertices)
    loose_edges = len(loose.edges)
    loose_faces = len(loose.faces)

    group_count = len(groups)
    instance_count = sum(1 for g in groups if g.is_component())

    # Instances share their prototype mesh; counting it once per instance is
    # deliberate — these are render/entity counts, the way modellers usually
    # report them, not a dedup of prototypes.
    from core.group import iter_placements
    placed = [(pg, m) for g in groups for pg, m in iter_placements(g)]

    group_verts = sum(len(g.mesh.vertices) for g, _m in placed)
    group_edges = sum(len(g.mesh.edges) for g, _m in placed)
    group_faces = sum(len(g.mesh.faces) for g, _m in placed)

    all_faces = list(loose.faces) + [f for g, _m in placed for f in g.mesh.faces]
    tri_count = sum(len(f.loop) - 2 for f in all_faces if len(f.loop) >= 3)

    # --- Bounding box (world space: instance prototypes through their xform)
    positions = [v.position for v in loose.vertices]
    for g, m in placed:
        if m is not None:
            positions.extend(m.map(v.position) for v in g.mesh.vertices)
        else:
            positions.extend(v.position for v in g.mesh.vertices)
    if positions:
        xs = [p.x() for p in positions]
        ys = [p.y() for p in positions]
        zs = [p.z() for p in positions]
        bbox = {"min_x": min(xs), "max_x": max(xs),
                "min_y": min(ys), "max_y": max(ys),
                "min_z": min(zs), "max_z": max(zs),
                "width": max(xs) - min(xs),
                "depth": max(ys) - min(ys),
                "height": max(zs) - min(zs)}
    else:
        bbox = {k: 0.0 for k in ("min_x", "max_x", "min_y", "max_y",
                                 "min_z", "max_z", "width", "depth", "height")}

    # --- Materials in use — the Paint tray's idiom (attrs, floats 0–1) -----
    colors: dict[tuple, dict] = {}
    textures: dict[str, dict] = {}
    for f in all_faces:
        tex = f.attrs.get("texture")
        if tex and tex.get("path"):
            entry = textures.setdefault(
                tex["path"], {"name": Path(tex["path"]).stem,
                              "faces": 0, "area": 0.0})
        else:
            col = f.attrs.get("color")
            if col is None:
                continue
            entry = colors.setdefault(
                tuple(col), {"rgb": tuple(col), "faces": 0, "area": 0.0})
        # Registry identity (attrs["mat"], core.materials): the entry shows
        # ITS name — "Concreto visto: 84 m²", a finishes takeoff line —
        # instead of an anonymous rgb() or a texture-file stem.
        if f.attrs.get("mat") and "mat" not in entry:
            entry["mat"] = f.attrs["mat"]
        entry["faces"] += 1
        entry["area"] += bim.face_net_area(f)   # a slab's opening is not paint

    # --- BIM objects — the same call behind the BIM tray and IFC export ----
    objects = [{"class": o["class"], "name": o["name"],
                "area": o["area"], "volume": o["volume"]}
               for o in bim.collect_objects(scene)]
    by_class: dict[str, int] = {}
    for o in objects:
        by_class[o["class"]] = by_class.get(o["class"], 0) + 1

    return {
        "loose_verts": loose_verts, "loose_edges": loose_edges,
        "loose_faces": loose_faces,
        "group_count": group_count,
        "instances": instance_count,
        "classic_groups": group_count - instance_count,
        "group_verts": group_verts, "group_edges": group_edges,
        "group_faces": group_faces,
        "total_verts": loose_verts + group_verts,
        "total_edges": loose_edges + group_edges,
        "total_faces": loose_faces + group_faces,
        "tri_count": tri_count,
        "bbox": bbox,
        "colors": list(colors.values()),
        "textures": list(textures.values()),
        "layers": [{"name": ly.name, "visible": ly.visible,
                    "locked": ly.locked} for ly in scene.layers],
        "bim_objects": objects,
        "bim_by_class": by_class,
        "dims_count": len(scene.dimensions),
        "text_count": len(scene.text_labels),
        "guides_count": len(scene.guides),
        "saved_views_count": len(scene.saved_views),
        "geo_paths_count": len(scene.geo_paths),
        "location": _location(scene),
        "style": dict(scene.dimension_style),
    }


def _material_rows(stats: dict) -> list[dict]:
    """The materials-in-use table as rows, in the order the tab shows:
    named materials first, then by painted area, largest first.

    One row per entry of ``stats["textures"]`` / ``stats["colors"]``:
    ``label`` (the registry name, the texture's name, or ``rgb(r,g,b)``
    for an anonymous colour), ``faces``, ``area`` (raw square metres)
    and ``rgb`` (the colour's floats 0-1, or ``None`` for a texture).
    Shared by the table itself and :func:`materials_csv`, so the
    spreadsheet a user takes to a budget is the table they saw."""
    rows = []
    for m in stats["textures"]:
        rows.append({"label": m.get("mat") or m["name"],
                     "faces": m["faces"], "area": m["area"],
                     "rgb": None, "mat": m.get("mat")})
    for m in stats["colors"]:
        r, g, b = (int(round(c * 255)) for c in m["rgb"][:3])
        rows.append({"label": m.get("mat") or f"rgb({r},{g},{b})",
                     "faces": m["faces"], "area": m["area"],
                     "rgb": m["rgb"], "mat": m.get("mat")})
    rows.sort(key=lambda m: (0 if m.get("mat") else 1, -m["area"]))
    return rows


def materials_csv(stats: dict) -> str:
    """The materials-in-use table as CSV — its spreadsheet form (#1277).

    The columns mirror the tab (material, faces, area); the area is the
    raw square-metre number, not the document-unit text the tab shows,
    so a spreadsheet can sum it straight into a budget. Names go through
    the csv module: a material called ``Paint, white`` must not split
    into two columns."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["material", "faces", "area_m2"])
    for m in _material_rows(stats):
        writer.writerow([m["label"], m["faces"], f"{m['area']:.4f}"])
    return out.getvalue()


def _stats_to_text(stats: dict) -> str:
    """Plain-text summary (the Copy to Clipboard payload)."""
    s, style = stats, stats["style"]
    lines = [
        "=== IngeTrazo — " + tr("Model Info") + " ===",
        "",
        "--- " + tr("Geometry") + " ---",
        f"{tr('Vertices')}:  {s['total_verts']:,}",
        f"{tr('Edges')}:     {s['total_edges']:,}",
        f"{tr('Faces')}:     {s['total_faces']:,}",
        f"{tr('Triangles (est.)')}: {s['tri_count']:,}",
        f"{tr('Groups (classic)')}: {s['classic_groups']:,}  /  "
        f"{tr('Component instances')}: {s['instances']:,}",
        "",
        "--- " + tr("Bounding box") + " ---",
        f"X: {_fmt_len(s['bbox']['width'], style)}   "
        f"Y: {_fmt_len(s['bbox']['depth'], style)}   "
        f"Z: {_fmt_len(s['bbox']['height'], style)}",
        "",
        "--- " + tr("Materials in use") + " ---",
    ]
    for m in s["textures"]:
        label = m.get("mat") or m["name"]
        lines.append(f"  {label}: {m['faces']} {tr('faces')}, "
                     f"{fmt_area(m['area'])}")
    for m in s["colors"]:
        r, g, b = (int(round(c * 255)) for c in m["rgb"][:3])
        label = m.get("mat") or f"rgb({r},{g},{b})"
        lines.append(f"  {label}: {m['faces']} {tr('faces')}, "
                     f"{fmt_area(m['area'])}")
    if not s["textures"] and not s["colors"]:
        lines.append("  " + tr("(none)"))

    lines += ["", f"--- {tr('Layers')} ({len(s['layers'])}) ---"]
    for ly in s["layers"]:
        vis = "✓" if ly["visible"] else "✗"
        lock = " 🔒" if ly["locked"] else ""
        lines.append(f"  [{vis}] {ly['name']}{lock}")

    if s["bim_objects"]:
        lines += ["", f"--- {tr('BIM objects')} ({len(s['bim_objects'])}) ---"]
        for o in s["bim_objects"]:
            vol = (fmt_volume(o['volume']) if o["volume"] is not None
                   else "—")
            lines.append(f"  {o['class']}  {o['name']}: "
                         f"{fmt_area(o['area'])}, {vol}")

    lines += [
        "",
        "--- " + tr("Annotations") + " ---",
        f"{tr('Dimensions')}: {s['dims_count']}   "
        f"{tr('Text labels')}: {s['text_count']}   "
        f"{tr('Guides')}: {s['guides_count']}",
        f"{tr('Saved views')}: {s['saved_views_count']}   "
        f"{tr('Geo paths')}: {s['geo_paths_count']}",
        "",
        "--- " + tr("Location") + " ---",
    ]
    loc = s.get("location")
    if loc is None:
        lines.append("  " + tr("This model has no location yet."))
    else:
        lines += [f"  {k}: {v}" for k, v in _location_rows(loc)]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

def _make_table(headers: list[str]) -> QTableWidget:
    """The dialog's uniform read-only table (no edit, no selection)."""
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.setSelectionMode(QTableWidget.NoSelection)
    return t


class ModelInfoDialog(QDialog):
    """Tabbed, read-only model statistics."""

    @property
    def _viewport(self):
        """The viewport of the project in front (projects in tabs, #1066):
        the one handed in at setup may be a tab in the back, or closed."""
        return self._live_viewport()

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent or viewport.window())
        from views.documents import live_viewport
        self._live_viewport = live_viewport(viewport)
        self.setWindowTitle(tr("Model Info"))
        self.setMinimumSize(480, 520)
        self.resize(520, 600)
        self._build_ui()
        self._refresh()

    # ---- Layout ------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, stretch=1)

        # Geometry tab
        geom_tab = QWidget()
        gl = QVBoxLayout(geom_tab)
        self._geom_table = _make_table([tr("Property"), tr("Value")])
        gl.addWidget(self._geom_table)
        self._tabs.addTab(geom_tab, tr("Geometry"))

        # Materials & layers tab
        mat_tab = QWidget()
        ml = QVBoxLayout(mat_tab)
        ml.addWidget(QLabel(tr("Materials in use")))
        self._mat_table = _make_table(
            [tr("Material"), tr("Faces"), tr("Area")])
        ml.addWidget(self._mat_table, stretch=1)
        self._export_materials_btn = QPushButton(
            tr("Export materials CSV…"))
        self._export_materials_btn.clicked.connect(
            self._export_materials_csv)
        ml.addWidget(self._export_materials_btn)
        ml.addWidget(QLabel(tr("Layers")))
        self._layer_table = _make_table(
            [tr("Layer"), tr("Visible"), tr("Locked")])
        ml.addWidget(self._layer_table, stretch=1)
        self._tabs.addTab(mat_tab, tr("Materials & Layers"))

        # BIM tab
        bim_tab = QWidget()
        bl = QVBoxLayout(bim_tab)
        self._bim_label = QLabel()
        bl.addWidget(self._bim_label)
        self._bim_table = _make_table(
            [tr("IFC Class"), tr("Name"), tr("Area"), tr("Volume")])
        bl.addWidget(self._bim_table, stretch=1)
        self._no_bim_label = QLabel(tr(
            "No BIM tags yet.\nSelect faces or a group and use the BIM "
            "panel to assign an IFC class\n(IfcWall, IfcSlab, ...); tagged "
            "objects export to .ifc with their quantities."))
        self._no_bim_label.setAlignment(Qt.AlignCenter)
        bl.addWidget(self._no_bim_label)
        self._tabs.addTab(bim_tab, tr("BIM"))

        # Location tab — the model's geographic location (scene.georef)
        loc_tab = QWidget()
        ll = QVBoxLayout(loc_tab)
        self._loc_table = _make_table([tr("Property"), tr("Value")])
        ll.addWidget(self._loc_table, stretch=1)
        self._no_loc_label = QLabel(tr("This model has no location yet."))
        self._no_loc_label.setAlignment(Qt.AlignCenter)
        ll.addWidget(self._no_loc_label, stretch=1)
        loc_btns = QHBoxLayout()
        self._set_loc_btn = QPushButton(tr("Set project location"))
        self._set_loc_btn.clicked.connect(self._set_location)
        loc_btns.addWidget(self._set_loc_btn)
        self._clear_loc_btn = QPushButton(tr("Clear location"))
        self._clear_loc_btn.clicked.connect(self._clear_location)
        loc_btns.addWidget(self._clear_loc_btn)
        loc_btns.addStretch(1)
        ll.addLayout(loc_btns)
        self._tabs.addTab(loc_tab, tr("Location"))

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton(tr("Refresh"))
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)
        copy_btn = QPushButton(tr("Copy to clipboard"))
        copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(copy_btn)
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ---- Data refresh ------------------------------------------------------
    def _refresh(self) -> None:
        self._stats = _collect_stats(self._viewport.scene)
        self._populate_geom()
        self._populate_materials()
        self._populate_bim()
        self._populate_location()

    def _populate_geom(self) -> None:
        s, style = self._stats, self._stats["style"]
        rows = [
            (tr("TOTALS"), ""),
            (tr("Vertices"), f"{s['total_verts']:,}"),
            (tr("Edges"), f"{s['total_edges']:,}"),
            (tr("Faces"), f"{s['total_faces']:,}"),
            (tr("Triangles (est.)"), f"{s['tri_count']:,}"),
            (tr("LOOSE GEOMETRY"), ""),
            (tr("Vertices"), f"{s['loose_verts']:,}"),
            (tr("Edges"), f"{s['loose_edges']:,}"),
            (tr("Faces"), f"{s['loose_faces']:,}"),
            (tr("GROUPS / COMPONENTS"), ""),
            (tr("Groups (classic)"), f"{s['classic_groups']:,}"),
            (tr("Component instances"), f"{s['instances']:,}"),
            (tr("Group vertices"), f"{s['group_verts']:,}"),
            (tr("Group faces"), f"{s['group_faces']:,}"),
            (tr("BOUNDING BOX"), ""),
            (tr("Width (X)"), _fmt_len(s["bbox"]["width"], style)),
            (tr("Depth (Y)"), _fmt_len(s["bbox"]["depth"], style)),
            (tr("Height (Z)"), _fmt_len(s["bbox"]["height"], style)),
            (tr("ANNOTATIONS"), ""),
            (tr("Dimensions"), str(s["dims_count"])),
            (tr("Text labels"), str(s["text_count"])),
            (tr("Guides"), str(s["guides_count"])),
            (tr("Saved views"), str(s["saved_views_count"])),
            (tr("Geo paths"), str(s["geo_paths_count"])),
        ]
        table = self._geom_table
        table.setRowCount(len(rows))
        for i, (prop, val) in enumerate(rows):
            p_item = QTableWidgetItem(prop)
            if not val:                      # section header row
                font = p_item.font()
                font.setBold(True)
                p_item.setFont(font)
            table.setItem(i, 0, p_item)
            table.setItem(i, 1, QTableWidgetItem(val))
        table.resizeRowsToContents()

    def _populate_materials(self) -> None:
        s = self._stats
        # Named materials first, biggest painted area first — the order a
        # finishes takeoff reads in (see _material_rows).
        mats = _material_rows(s)
        self._export_materials_btn.setEnabled(bool(mats))
        self._mat_table.setRowCount(max(len(mats), 1))
        if not mats:
            self._mat_table.setItem(
                0, 0, QTableWidgetItem(tr("(none)")))
            self._mat_table.setItem(0, 1, QTableWidgetItem(""))
            self._mat_table.setItem(0, 2, QTableWidgetItem(""))
        for i, m in enumerate(mats):
            name_item = QTableWidgetItem(m["label"])
            if m["rgb"] is not None:
                rgb = m["rgb"][:3]
                name_item.setBackground(QColor.fromRgbF(*rgb))
                # Legible over any swatch colour.
                lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
                name_item.setForeground(
                    QColor("black") if lum > 0.5 else QColor("white"))
            self._mat_table.setItem(i, 0, name_item)
            self._mat_table.setItem(
                i, 1, QTableWidgetItem(f"{m['faces']:,}"))
            self._mat_table.setItem(
                i, 2, QTableWidgetItem(f"{fmt_area(m['area'])}"))
        self._mat_table.resizeRowsToContents()

        layers = s["layers"]
        self._layer_table.setRowCount(len(layers))
        for i, ly in enumerate(layers):
            self._layer_table.setItem(i, 0, QTableWidgetItem(ly["name"]))
            vis = QTableWidgetItem("✓" if ly["visible"] else "✗")
            vis.setTextAlignment(Qt.AlignCenter)
            self._layer_table.setItem(i, 1, vis)
            lock = QTableWidgetItem("🔒" if ly["locked"] else "—")
            lock.setTextAlignment(Qt.AlignCenter)
            self._layer_table.setItem(i, 2, lock)
        self._layer_table.resizeRowsToContents()

    def _populate_bim(self) -> None:
        objects = self._stats["bim_objects"]
        by_class = self._stats["bim_by_class"]
        summary = "   ".join(f"{c}: {n}" for c, n in sorted(by_class.items()))
        self._bim_label.setText(
            tr("BIM objects: {n}", n=len(objects))
            + (f"   ({summary})" if summary else ""))
        self._bim_table.setVisible(bool(objects))
        self._no_bim_label.setVisible(not objects)
        self._bim_table.setRowCount(len(objects))
        for i, o in enumerate(objects):
            self._bim_table.setItem(i, 0, QTableWidgetItem(o["class"]))
            self._bim_table.setItem(i, 1, QTableWidgetItem(o["name"]))
            self._bim_table.setItem(
                i, 2, QTableWidgetItem(f"{fmt_area(o['area'])}"))
            vol = (fmt_volume(o['volume']) if o["volume"] is not None
                   else tr("(not watertight)"))
            self._bim_table.setItem(i, 3, QTableWidgetItem(vol))
        self._bim_table.resizeRowsToContents()

    # ---- Export ------------------------------------------------------------
    def _export_materials_csv(self) -> None:
        """Save the materials-in-use table as a CSV spreadsheet (#1277):
        the takeoff a user asked to carry into their budget."""
        from views.filedialogs import file_dialogs
        path, _ = file_dialogs.getSaveFileName(
            self, tr("Export materials CSV"), "materials.csv",
            tr("CSV (*.csv);;All files (*)"))
        if not path:
            return
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(materials_csv(self._stats))

    # ---- Clipboard ---------------------------------------------------------
    def _populate_location(self) -> None:
        loc = self._stats.get("location")
        self._loc_table.setVisible(loc is not None)
        self._no_loc_label.setVisible(loc is None)
        rows = _location_rows(loc) if loc is not None else []
        self._loc_table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self._loc_table.setItem(i, 0, QTableWidgetItem(k))
            self._loc_table.setItem(i, 1, QTableWidgetItem(v))
        # Survey points, traced paths and a drone survey are placed by the
        # location: they would stay behind, so the Terrain panel moves it.
        anchored = loc is not None and _location_anchored(self._viewport.scene)
        tip = (tr("This model has survey points, traced paths or a drone "
                  "survey placed by its location: change it in the Terrain "
                  "panel.") if anchored else "")
        for btn in (self._set_loc_btn, self._clear_loc_btn):
            btn.setEnabled(not anchored)
            btn.setToolTip(tip)
        self._clear_loc_btn.setVisible(loc is not None)

    def _apply_location(self, lat, lon) -> None:
        from core.history import SetLocationCommand
        from tools.north import refresh_north_display
        vp = self._viewport
        vp.history.execute(SetLocationCommand(lat, lon))
        refresh_north_display(vp)
        vp.update()
        self._refresh()

    def _set_location(self) -> None:
        """The map locator (as Shadows ▸ Add location…), from where the
        model is — or the sun's default site when it has no location."""
        from core.sun import DEFAULT_LAT, DEFAULT_LON
        from georef.tiles import DEFAULT_SOURCE_ID, PRESETS
        from views.location_dialog import pick_location
        loc = self._stats.get("location")
        lat0, lon0 = ((loc["lat"], loc["lon"]) if loc is not None
                      else (DEFAULT_LAT, DEFAULT_LON))
        result = pick_location(PRESETS[DEFAULT_SOURCE_ID], lat0, lon0, self)
        if result is None:
            return
        lat, lon, _w, _l = result
        self._apply_location(lat, lon)

    def _clear_location(self) -> None:
        """Clear Location (SketchUp's words): the model keeps its geometry
        and its north angle; the sun goes back to the default site. Undo
        brings the location back."""
        if self._stats.get("location") is not None:
            self._apply_location(None, None)

    def _copy_to_clipboard(self) -> None:
        QApplication.clipboard().setText(_stats_to_text(self._stats))
        self.setWindowTitle(tr("Model Info") + " — " + tr("copied!"))
        QTimer.singleShot(
            1500, lambda: self.setWindowTitle(tr("Model Info")))


# ---------------------------------------------------------------------------
# Tool registration (the plugin entry point)
# ---------------------------------------------------------------------------

class ModelInfoTool(Tool):
    """Extensions-menu tool that opens the Model Info dialog."""
    name = "Model Info"
    shortcut = None          # menu entry only; no key to fight over
    description = (
        "Show the model's statistics: faces, edges, groups, materials "
        "and more.")
    uses_snap = False

    def on_activate(self, viewport) -> None:
        ModelInfoDialog(viewport, parent=viewport.window()).exec()

    def on_deactivate(self, viewport) -> None:
        pass
