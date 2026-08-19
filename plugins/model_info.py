# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood (OpenSKP) — IngeTrazo plugin contribution.
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Model Info plugin — model statistics in a dialog (Extensions menu).

A read-only, tabbed breakdown of the open document: geometry counts,
bounding box, materials in use, layers, and BIM objects. The numbers agree
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
  dialog speaks the same units as the rest of the document.
"""
from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Statistics collection (pure data, no GUI — see tests/test_model_info_plugin)
# ---------------------------------------------------------------------------

def _fmt_len(metres: float, style: dict) -> str:
    """A length in the document's dimension style (Viewport's formatter)."""
    from views.viewport import Viewport
    return Viewport._format_dim_value(metres, style)


def _collect_stats(scene) -> dict:
    """Walk the document and return a statistics dictionary (raw numbers;
    formatting happens at display time with the dimension style)."""
    loose = scene.loose_mesh          # the real loose mesh, group open or not
    groups = scene.groups

    loose_verts = len(loose.vertices)
    loose_edges = len(loose.edges)
    loose_faces = len(loose.faces)

    group_count = len(groups)
    instance_count = sum(1 for g in groups if g.is_instance())

    # Instances share their prototype mesh; counting it once per instance is
    # deliberate — these are render/entity counts, the way SketchUp reports
    # them, not a dedup of prototypes.
    group_verts = sum(len(g.mesh.vertices) for g in groups)
    group_edges = sum(len(g.mesh.edges) for g in groups)
    group_faces = sum(len(g.mesh.faces) for g in groups)

    all_faces = list(loose.faces) + [f for g in groups for f in g.mesh.faces]
    tri_count = sum(len(f.loop) - 2 for f in all_faces if len(f.loop) >= 3)

    # --- Bounding box (world space: instance prototypes through their xform)
    positions = [v.position for v in loose.vertices]
    for g in groups:
        if g.xform is not None:
            positions.extend(g.xform.map(v.position) for v in g.mesh.vertices)
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
        entry["area"] += f.area()

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
        "style": dict(scene.dimension_style),
    }


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
                     f"{m['area']:.2f} m²")
    for m in s["colors"]:
        r, g, b = (int(round(c * 255)) for c in m["rgb"][:3])
        label = m.get("mat") or f"rgb({r},{g},{b})"
        lines.append(f"  {label}: {m['faces']} {tr('faces')}, "
                     f"{m['area']:.2f} m²")
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
            vol = (f"{o['volume']:.3f} m³" if o["volume"] is not None
                   else "—")
            lines.append(f"  {o['class']}  {o['name']}: "
                         f"{o['area']:.2f} m², {vol}")

    lines += [
        "",
        "--- " + tr("Annotations") + " ---",
        f"{tr('Dimensions')}: {s['dims_count']}   "
        f"{tr('Text labels')}: {s['text_count']}   "
        f"{tr('Guides')}: {s['guides_count']}",
        f"{tr('Saved views')}: {s['saved_views_count']}   "
        f"{tr('Geo paths')}: {s['geo_paths_count']}",
    ]
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

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent or viewport.window())
        self._viewport = viewport
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
        mats = ([{"label": m.get("mat") or m["name"], "swatch": None, **m}
                 for m in s["textures"]]
                + [{"label": m.get("mat") or "", "swatch": m["rgb"], **m}
                   for m in s["colors"]])
        # Named materials first, biggest painted area first — the order a
        # finishes takeoff reads in.
        mats.sort(key=lambda m: (0 if m.get("mat") else 1, -m["area"]))
        self._mat_table.setRowCount(max(len(mats), 1))
        if not mats:
            self._mat_table.setItem(
                0, 0, QTableWidgetItem(tr("(none)")))
            self._mat_table.setItem(0, 1, QTableWidgetItem(""))
            self._mat_table.setItem(0, 2, QTableWidgetItem(""))
        for i, m in enumerate(mats):
            name_item = QTableWidgetItem(m["label"])
            if m["swatch"] is not None:
                rgb = m["swatch"][:3]
                name_item.setBackground(QColor.fromRgbF(*rgb))
                if not m["label"]:
                    r, g, b = (int(round(c * 255)) for c in rgb)
                    name_item.setText(f"rgb({r},{g},{b})")
                # Legible over any swatch colour.
                lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
                name_item.setForeground(
                    QColor("black") if lum > 0.5 else QColor("white"))
            self._mat_table.setItem(i, 0, name_item)
            self._mat_table.setItem(
                i, 1, QTableWidgetItem(f"{m['faces']:,}"))
            self._mat_table.setItem(
                i, 2, QTableWidgetItem(f"{m['area']:.2f} m²"))
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
                i, 2, QTableWidgetItem(f"{o['area']:.2f} m²"))
            vol = (f"{o['volume']:.3f} m³" if o["volume"] is not None
                   else tr("(not watertight)"))
            self._bim_table.setItem(i, 3, QTableWidgetItem(vol))
        self._bim_table.resizeRowsToContents()

    # ---- Clipboard ---------------------------------------------------------
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
    uses_snap = False

    def on_activate(self, viewport) -> None:
        ModelInfoDialog(viewport, parent=viewport.window()).exec()

    def on_deactivate(self, viewport) -> None:
        pass
