# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood (OpenSKP) — IngeTrazo plugin contribution.
"""Model Info plugin — displays comprehensive model statistics in a dialog.

Activating this tool opens a tabbed PySide6 dialog showing geometry counts,
bounding box dimensions, groups/components, materials, layers, and BIM tags
for the current IngeTrazo scene. Read-only — never modifies geometry.

Usage: press ``Ctrl+I`` or select **Extensions → Model Info** from the menu.
"""
from __future__ import annotations

from tools.base import Tool

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Statistics collection (pure data, no GUI)
# ---------------------------------------------------------------------------

def _collect_stats(scene) -> dict:
    """Walk the scene and return a statistics dictionary."""
    mesh = scene.mesh
    groups = scene.groups

    # --- Loose geometry ---
    loose_verts = len(mesh.vertices)
    loose_edges = len(mesh.edges)
    loose_faces = len(mesh.faces)

    # --- Group / component geometry ---
    group_count = len(groups)
    instance_count = sum(1 for g in groups if g.is_instance())
    classic_count = group_count - instance_count

    group_verts = sum(len(g.mesh.vertices) for g in groups)
    group_edges = sum(len(g.mesh.edges) for g in groups)
    group_faces = sum(len(g.mesh.faces) for g in groups)

    total_verts = loose_verts + group_verts
    total_edges = loose_edges + group_edges
    total_faces = loose_faces + group_faces

    # --- Triangle count (for GPU/render estimate) ---
    tri_count = 0
    for f in mesh.faces:
        n = len(f.loop)
        if n >= 3:
            tri_count += n - 2
    for g in groups:
        for f in g.mesh.faces:
            n = len(f.loop)
            if n >= 3:
                tri_count += n - 2

    # --- Bounding box ---
    all_positions = [v.position for v in mesh.vertices]
    for g in groups:
        if g.xform is not None:
            # Component instance: transform prototype verts to world space.
            for v in g.mesh.vertices:
                all_positions.append(g.xform.map(v.position))
        else:
            all_positions.extend(v.position for v in g.mesh.vertices)

    if all_positions:
        xs = [p.x() for p in all_positions]
        ys = [p.y() for p in all_positions]
        zs = [p.z() for p in all_positions]
        bbox = {
            "min_x": min(xs), "max_x": max(xs),
            "min_y": min(ys), "max_y": max(ys),
            "min_z": min(zs), "max_z": max(zs),
            "width": max(xs) - min(xs),
            "depth": max(ys) - min(ys),
            "height": max(zs) - min(zs),
        }
    else:
        bbox = {k: 0.0 for k in (
            "min_x", "max_x", "min_y", "max_y",
            "min_z", "max_z", "width", "depth", "height")}

    # --- Materials ---
    material_names: set[str] = set()
    material_colors: dict[str, tuple] = {}
    for f in mesh.faces:
        mat = f.attrs.get("material")
        if mat:
            name = mat if isinstance(mat, str) else str(mat)
            material_names.add(name)
        color = f.attrs.get("color")
        if color and mat:
            material_colors[str(mat)] = tuple(color) if isinstance(color, (list, tuple)) else ()
    for g in groups:
        for f in g.mesh.faces:
            mat = f.attrs.get("material")
            if mat:
                name = mat if isinstance(mat, str) else str(mat)
                material_names.add(name)
            color = f.attrs.get("color")
            if color and mat:
                material_colors[str(mat)] = tuple(color) if isinstance(color, (list, tuple)) else ()

    # --- Layers ---
    layers_info = []
    for ly in scene.layers:
        layers_info.append({
            "name": ly.name,
            "visible": ly.visible,
            "locked": getattr(ly, "locked", False),
        })

    # --- BIM tags ---
    bim_tags: dict[str, int] = {}
    for g in groups:
        if g.ifc:
            cls = g.ifc.get("class", "Unknown") if isinstance(g.ifc, dict) else str(g.ifc)
            bim_tags[cls] = bim_tags.get(cls, 0) + 1
    for f in mesh.faces:
        ifc = f.attrs.get("ifc_class") or f.attrs.get("ifc")
        if ifc:
            cls = ifc.get("class", "Unknown") if isinstance(ifc, dict) else str(ifc)
            bim_tags[cls] = bim_tags.get(cls, 0) + 1
    for g in groups:
        for f in g.mesh.faces:
            ifc = f.attrs.get("ifc_class") or f.attrs.get("ifc")
            if ifc:
                cls = ifc.get("class", "Unknown") if isinstance(ifc, dict) else str(ifc)
                bim_tags[cls] = bim_tags.get(cls, 0) + 1

    # --- Scene metadata ---
    dims_count = len(getattr(scene, "dimensions", []))
    text_count = len(getattr(scene, "text_labels", []))
    guides_count = len(getattr(scene, "guides", []))
    saved_views_count = len(getattr(scene, "saved_views", []))
    geo_paths_count = len(getattr(scene, "geo_paths", []))

    return {
        "loose_verts": loose_verts,
        "loose_edges": loose_edges,
        "loose_faces": loose_faces,
        "group_count": group_count,
        "classic_groups": classic_count,
        "instances": instance_count,
        "group_verts": group_verts,
        "group_edges": group_edges,
        "group_faces": group_faces,
        "total_verts": total_verts,
        "total_edges": total_edges,
        "total_faces": total_faces,
        "tri_count": tri_count,
        "bbox": bbox,
        "materials": sorted(material_names),
        "material_colors": material_colors,
        "layers": layers_info,
        "bim_tags": bim_tags,
        "dims_count": dims_count,
        "text_count": text_count,
        "guides_count": guides_count,
        "saved_views_count": saved_views_count,
        "geo_paths_count": geo_paths_count,
    }


def _stats_to_text(stats: dict) -> str:
    """Format stats as a plain-text summary for clipboard."""
    lines = [
        "=== IngeTrazo Model Info ===",
        "",
        "--- Geometry ---",
        f"Total vertices:    {stats['total_verts']:,}",
        f"Total edges:       {stats['total_edges']:,}",
        f"Total faces:       {stats['total_faces']:,}",
        f"Triangles (est.):  {stats['tri_count']:,}",
        f"  Loose:  {stats['loose_verts']:,} V / {stats['loose_edges']:,} E / {stats['loose_faces']:,} F",
        f"  Groups: {stats['group_verts']:,} V / {stats['group_edges']:,} E / {stats['group_faces']:,} F",
        "",
        "--- Groups ---",
        f"Total groups:      {stats['group_count']:,}",
        f"  Classic groups:  {stats['classic_groups']:,}",
        f"  Instances:       {stats['instances']:,}",
        "",
        "--- Bounding Box ---",
        f"Width  (X): {stats['bbox']['width']:.3f} m",
        f"Depth  (Y): {stats['bbox']['depth']:.3f} m",
        f"Height (Z): {stats['bbox']['height']:.3f} m",
        "",
        "--- Annotations ---",
        f"Dimensions:   {stats['dims_count']}",
        f"Text labels:  {stats['text_count']}",
        f"Guides:       {stats['guides_count']}",
        f"Saved views:  {stats['saved_views_count']}",
        f"Geo paths:    {stats['geo_paths_count']}",
        "",
        f"--- Materials ({len(stats['materials'])}) ---",
    ]
    for m in stats["materials"]:
        lines.append(f"  • {m}")
    if not stats["materials"]:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"--- Layers ({len(stats['layers'])}) ---")
    for ly in stats["layers"]:
        vis = "✓" if ly["visible"] else "✗"
        lock = " 🔒" if ly["locked"] else ""
        lines.append(f"  [{vis}] {ly['name']}{lock}")

    if stats["bim_tags"]:
        lines.append("")
        lines.append(f"--- BIM Tags ({sum(stats['bim_tags'].values())}) ---")
        for cls, count in sorted(stats["bim_tags"].items()):
            lines.append(f"  {cls}: {count}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dialog (PySide6 GUI)
# ---------------------------------------------------------------------------

class ModelInfoDialog(QDialog):
    """Tabbed dialog showing model statistics."""

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent or viewport)
        self._viewport = viewport
        self.setWindowTitle("Model Info")
        self.setMinimumSize(480, 520)
        self.resize(520, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._refresh()

    # ---- Layout ------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        header = QLabel("Model Info")
        header.setFont(QFont("Segoe UI", 14, QFont.Bold))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # Tabs
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs, stretch=1)

        self._geom_tab = QWidget()
        self._mat_tab = QWidget()
        self._bim_tab = QWidget()
        self._tabs.addTab(self._geom_tab, "Geometry")
        self._tabs.addTab(self._mat_tab, "Materials && Layers")
        self._tabs.addTab(self._bim_tab, "BIM")

        self._build_geom_tab()
        self._build_mat_tab()
        self._build_bim_tab()

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_row.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _build_geom_tab(self) -> None:
        layout = QVBoxLayout(self._geom_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Geometry table
        self._geom_table = QTableWidget()
        self._geom_table.setColumnCount(2)
        self._geom_table.setHorizontalHeaderLabels(["Property", "Value"])
        self._geom_table.horizontalHeader().setStretchLastSection(True)
        self._geom_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._geom_table.verticalHeader().setVisible(False)
        self._geom_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._geom_table.setAlternatingRowColors(True)
        self._geom_table.setSelectionMode(QTableWidget.NoSelection)
        layout.addWidget(self._geom_table)

    def _build_mat_tab(self) -> None:
        layout = QVBoxLayout(self._mat_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        mat_label = QLabel("Materials")
        mat_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(mat_label)

        self._mat_table = QTableWidget()
        self._mat_table.setColumnCount(2)
        self._mat_table.setHorizontalHeaderLabels(["Material", "Color"])
        self._mat_table.horizontalHeader().setStretchLastSection(True)
        self._mat_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._mat_table.verticalHeader().setVisible(False)
        self._mat_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._mat_table.setAlternatingRowColors(True)
        self._mat_table.setSelectionMode(QTableWidget.NoSelection)
        layout.addWidget(self._mat_table, stretch=1)

        layer_label = QLabel("Layers")
        layer_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(layer_label)

        self._layer_table = QTableWidget()
        self._layer_table.setColumnCount(3)
        self._layer_table.setHorizontalHeaderLabels(["Layer", "Visible", "Locked"])
        self._layer_table.horizontalHeader().setStretchLastSection(True)
        self._layer_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._layer_table.verticalHeader().setVisible(False)
        self._layer_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._layer_table.setAlternatingRowColors(True)
        self._layer_table.setSelectionMode(QTableWidget.NoSelection)
        layout.addWidget(self._layer_table, stretch=1)

    def _build_bim_tab(self) -> None:
        layout = QVBoxLayout(self._bim_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._bim_label = QLabel()
        self._bim_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(self._bim_label)

        self._bim_table = QTableWidget()
        self._bim_table.setColumnCount(2)
        self._bim_table.setHorizontalHeaderLabels(["IFC Class", "Count"])
        self._bim_table.horizontalHeader().setStretchLastSection(True)
        self._bim_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._bim_table.verticalHeader().setVisible(False)
        self._bim_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._bim_table.setAlternatingRowColors(True)
        self._bim_table.setSelectionMode(QTableWidget.NoSelection)
        layout.addWidget(self._bim_table, stretch=1)

        self._no_bim_label = QLabel(
            "No BIM tags found.\n\n"
            "Use Edit → BIM Tagging to assign IFC classes\n"
            "(IfcWall, IfcSlab, IfcColumn, ...) to your geometry,\n"
            "then export to .ifc for quantity takeoff."
        )
        self._no_bim_label.setAlignment(Qt.AlignCenter)
        self._no_bim_label.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._no_bim_label)

    # ---- Data refresh ------------------------------------------------------
    def _refresh(self) -> None:
        scene = self._viewport.scene
        self._stats = _collect_stats(scene)
        self._populate_geom_tab()
        self._populate_mat_tab()
        self._populate_bim_tab()

    def _populate_geom_tab(self) -> None:
        s = self._stats
        rows = [
            ("", ""),  # section header row
            ("TOTALS", ""),
            ("Vertices", f"{s['total_verts']:,}"),
            ("Edges", f"{s['total_edges']:,}"),
            ("Faces", f"{s['total_faces']:,}"),
            ("Triangles (est.)", f"{s['tri_count']:,}"),
            ("", ""),
            ("LOOSE GEOMETRY", ""),
            ("Vertices", f"{s['loose_verts']:,}"),
            ("Edges", f"{s['loose_edges']:,}"),
            ("Faces", f"{s['loose_faces']:,}"),
            ("", ""),
            ("GROUPS / COMPONENTS", ""),
            ("Groups (classic)", f"{s['classic_groups']:,}"),
            ("Component instances", f"{s['instances']:,}"),
            ("Group vertices", f"{s['group_verts']:,}"),
            ("Group edges", f"{s['group_edges']:,}"),
            ("Group faces", f"{s['group_faces']:,}"),
            ("", ""),
            ("BOUNDING BOX", ""),
            ("Width (X)", f"{s['bbox']['width']:.3f} m"),
            ("Depth (Y)", f"{s['bbox']['depth']:.3f} m"),
            ("Height (Z)", f"{s['bbox']['height']:.3f} m"),
            ("X range", f"{s['bbox']['min_x']:.3f} → {s['bbox']['max_x']:.3f}"),
            ("Y range", f"{s['bbox']['min_y']:.3f} → {s['bbox']['max_y']:.3f}"),
            ("Z range", f"{s['bbox']['min_z']:.3f} → {s['bbox']['max_z']:.3f}"),
            ("", ""),
            ("ANNOTATIONS", ""),
            ("Dimensions", str(s['dims_count'])),
            ("Text labels", str(s['text_count'])),
            ("Guides", str(s['guides_count'])),
            ("Saved views", str(s['saved_views_count'])),
            ("Geo paths", str(s['geo_paths_count'])),
        ]
        table = self._geom_table
        table.setRowCount(len(rows))
        bold_font = QFont("Segoe UI", 9, QFont.Bold)
        for i, (prop, val) in enumerate(rows):
            p_item = QTableWidgetItem(prop)
            v_item = QTableWidgetItem(val)
            # Section headers: bold, spanning
            if val == "" and prop:
                p_item.setFont(bold_font)
                p_item.setForeground(QColor(120, 180, 240))
            table.setItem(i, 0, p_item)
            table.setItem(i, 1, v_item)
        table.resizeRowsToContents()

    def _populate_mat_tab(self) -> None:
        s = self._stats
        # Materials
        mats = s["materials"]
        self._mat_table.setRowCount(len(mats) if mats else 1)
        if not mats:
            self._mat_table.setItem(0, 0, QTableWidgetItem("(no materials)"))
            self._mat_table.setItem(0, 1, QTableWidgetItem(""))
        else:
            for i, name in enumerate(mats):
                self._mat_table.setItem(i, 0, QTableWidgetItem(name))
                color = s["material_colors"].get(name, ())
                if len(color) >= 3:
                    c_item = QTableWidgetItem("")
                    r, g, b = int(color[0]), int(color[1]), int(color[2])
                    c_item.setBackground(QColor(r, g, b))
                    c_item.setText(f"rgb({r}, {g}, {b})")
                    self._mat_table.setItem(i, 1, c_item)
                else:
                    self._mat_table.setItem(i, 1, QTableWidgetItem("—"))
        self._mat_table.resizeRowsToContents()

        # Layers
        layers = s["layers"]
        self._layer_table.setRowCount(len(layers))
        for i, ly in enumerate(layers):
            self._layer_table.setItem(i, 0, QTableWidgetItem(ly["name"]))
            vis_item = QTableWidgetItem("✓" if ly["visible"] else "✗")
            vis_item.setTextAlignment(Qt.AlignCenter)
            if not ly["visible"]:
                vis_item.setForeground(QColor(180, 80, 80))
            self._layer_table.setItem(i, 1, vis_item)
            lock_item = QTableWidgetItem("🔒" if ly["locked"] else "—")
            lock_item.setTextAlignment(Qt.AlignCenter)
            self._layer_table.setItem(i, 2, lock_item)
        self._layer_table.resizeRowsToContents()

    def _populate_bim_tab(self) -> None:
        tags = self._stats["bim_tags"]
        total = sum(tags.values())
        self._bim_label.setText(f"BIM-tagged entities: {total}")
        if not tags:
            self._bim_table.hide()
            self._no_bim_label.show()
        else:
            self._no_bim_label.hide()
            self._bim_table.show()
            sorted_tags = sorted(tags.items(), key=lambda x: -x[1])
            self._bim_table.setRowCount(len(sorted_tags))
            for i, (cls, count) in enumerate(sorted_tags):
                self._bim_table.setItem(i, 0, QTableWidgetItem(cls))
                c_item = QTableWidgetItem(str(count))
                c_item.setTextAlignment(Qt.AlignCenter)
                self._bim_table.setItem(i, 1, c_item)
            self._bim_table.resizeRowsToContents()

    # ---- Clipboard ---------------------------------------------------------
    def _copy_to_clipboard(self) -> None:
        text = _stats_to_text(self._stats)
        QApplication.clipboard().setText(text)
        # Brief visual feedback
        self.setWindowTitle("Model Info — Copied to Clipboard!")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self.setWindowTitle("Model Info"))


# ---------------------------------------------------------------------------
# Tool registration (the plugin entry point)
# ---------------------------------------------------------------------------

class ModelInfoTool(Tool):
    """Toolbar tool that opens the Model Info dialog."""
    name = "Model Info"
    shortcut = None  # Registered via menu, not shortcut (avoids collisions)
    uses_snap = False

    def on_activate(self, viewport) -> None:
        dialog = ModelInfoDialog(viewport, parent=viewport.window())
        dialog.exec()

    def on_deactivate(self, viewport) -> None:
        pass  # Nothing to clean up
