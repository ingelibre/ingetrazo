# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Solid Inspector plugin — find out WHY a solid is not watertight.

IngeTrazo's engine guarantees hermetic solids and its BIM layer only
reports a volume when the object is closed. When Model Info (or the BIM
tray) says "(not watertight)", this plugin answers the next question:
*where is the hole?* — the same job SketchUp users know from thomthom's
Solid Inspector².

One row per solid candidate (the geometry you are editing, plus every
group). For each: face/edge counts, verdict, a breakdown of the exact
problems, and the volume when the object is closed. **Highlight** selects
the offending edges right in the viewport (orange, like any selection),
so you can see the hole instead of hunting for it.

Diagnosis (per edge, counting non-interior incident faces):

- ``0`` faces  → a **stray edge**: loose drawing, not part of any surface.
- ``1`` face   → an **open border**: the rim of a hole in the skin.
- ``>2`` faces → **overconnected**: an internal wall / T-junction the
  boundary should not have.

Watertight = every edge has exactly 2. The volume comes from
:func:`core.bim.face_set_volume` — the same computation behind the BIM
quantities, so this dialog and your takeoff can never disagree.

Read-only: inspecting never modifies the model.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core import bim
from core.i18n import tr
from tools.base import Tool


# ---------------------------------------------------------------------------
# Diagnosis (pure data, no GUI — see tests/test_solid_inspector_plugin.py)
# ---------------------------------------------------------------------------

def inspect_mesh(mesh) -> dict:
    """Classify every edge of *mesh* and compute the closed volume.

    Returns ``{"faces", "edges", "stray", "open", "over", "watertight",
    "volume"}`` where the three problem entries are lists of Edge objects
    and ``volume`` is in m³ (or ``None`` when the mesh is not closed).
    """
    stray, open_borders, over = [], [], []
    for e in mesh.edges:
        n = sum(1 for f in e.faces if not getattr(f, "interior", False))
        if n == 0:
            stray.append(e)
        elif n == 1:
            open_borders.append(e)
        elif n > 2:
            over.append(e)

    watertight = (not stray and not open_borders and not over
                  and bool(mesh.faces))
    volume = None
    if watertight:
        volume = bim.face_set_volume(
            [f for f in mesh.faces if not getattr(f, "interior", False)])

    return {
        "faces": len(mesh.faces),
        "edges": len(mesh.edges),
        "stray": stray,
        "open": open_borders,
        "over": over,
        "watertight": watertight,
        "volume": volume,
    }


def _problem_text(report: dict) -> str:
    """Human breakdown of the problems, empty string when there are none."""
    parts = []
    if report["open"]:
        parts.append(tr("{n} open borders", n=len(report["open"])))
    if report["stray"]:
        parts.append(tr("{n} stray edges", n=len(report["stray"])))
    if report["over"]:
        parts.append(tr("{n} overconnected", n=len(report["over"])))
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class SolidInspectorDialog(QDialog):
    """Modeless inspector: fix, press Refresh, repeat until everything ✓."""

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent or viewport.window())
        self._viewport = viewport
        self._rows: list = []          # payload per table row
        self.setWindowTitle(tr("Solid Inspector"))
        self.setMinimumSize(560, 380)
        self.resize(640, 440)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._summary = QLabel()
        layout.addWidget(self._summary)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(
            [tr("Object"), tr("Faces"), tr("Status"), tr("Problems"),
             tr("Volume")])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.itemDoubleClicked.connect(lambda _i: self.highlight())
        layout.addWidget(self._table, stretch=1)

        btns = QHBoxLayout()
        refresh_btn = QPushButton(tr("Refresh"))
        refresh_btn.clicked.connect(self.refresh)
        btns.addWidget(refresh_btn)
        self._hl_btn = QPushButton(tr("Highlight problems"))
        self._hl_btn.clicked.connect(self.highlight)
        btns.addWidget(self._hl_btn)
        close_btn = QPushButton(tr("Close"))
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    # ---- Data --------------------------------------------------------------
    def refresh(self) -> None:
        scene = self._viewport.scene
        self._rows = []

        # The mesh you are editing right now: the open group's, or the
        # loose one. Problem edges here CAN be highlighted directly.
        if scene.edit_group is not None:
            active_name = tr("Open group: {name}",
                             name=scene.edit_group.name)
        else:
            active_name = tr("Loose geometry")
        self._rows.append({"name": active_name, "kind": "active",
                           "report": inspect_mesh(scene.mesh)})

        # Every group (the one being edited included — its row above is the
        # live one; skip it here to avoid the duplicate).
        for g in scene.groups:
            if g is scene.edit_group:
                continue
            # Billboards (scale figures, 2D cut-out trees/people) are flat
            # by design — listing them as "not watertight" would be noise
            # in every single model.
            if getattr(g, "billboard", False):
                continue
            self._rows.append({"name": g.name, "kind": "group", "group": g,
                               "report": inspect_mesh(g.mesh)})

        table = self._table
        table.setRowCount(len(self._rows))
        ok = QColor(80, 160, 80)
        bad = QColor(200, 90, 60)
        solids = problems = 0
        for i, row in enumerate(self._rows):
            rep = row["report"]
            table.setItem(i, 0, QTableWidgetItem(row["name"]))
            table.setItem(i, 1, QTableWidgetItem(f"{rep['faces']:,}"))
            if not rep["faces"] and not rep["edges"]:
                status = QTableWidgetItem(tr("(empty)"))
            elif rep["watertight"]:
                status = QTableWidgetItem("✔ " + tr("watertight"))
                status.setForeground(ok)
                solids += 1
            else:
                status = QTableWidgetItem("✘ " + tr("not watertight"))
                status.setForeground(bad)
                problems += 1
            table.setItem(i, 2, status)
            table.setItem(i, 3, QTableWidgetItem(_problem_text(rep)))
            vol = (f"{rep['volume']:.3f} m³"
                   if rep["volume"] is not None else "—")
            table.setItem(i, 4, QTableWidgetItem(vol))
        table.resizeRowsToContents()

        self._summary.setText(
            tr("{ok} watertight solids, {bad} with problems",
               ok=solids, bad=problems))

    # ---- Highlight ---------------------------------------------------------
    def _selected_row(self) -> dict | None:
        i = self._table.currentRow()
        if 0 <= i < len(self._rows):
            return self._rows[i]
        return None

    def highlight(self) -> None:
        """Select the problems of the chosen row in the viewport.

        Active-mesh row → the offending edges themselves turn orange.
        Group row → the group is selected (enter it with a double click
        and press Refresh to see its edges)."""
        row = self._selected_row()
        vp = self._viewport
        if row is None:
            return
        scene = vp.scene
        if row["kind"] == "active":
            rep = row["report"]
            edges = rep["open"] + rep["stray"] + rep["over"]
            scene.selection.clear()
            scene.selection.update(edges)
            if edges:
                vp.flash_status(
                    tr("{n} problem edges selected", n=len(edges)))
            else:
                vp.flash_status(tr("Nothing to highlight — watertight"))
        else:
            scene.selection.clear()
            scene.selection.add(row["group"])
            vp.flash_status(tr(
                "Group selected — double-click into it and press Refresh"))
        vp.update()


# ---------------------------------------------------------------------------
# Tool registration (the plugin entry point)
# ---------------------------------------------------------------------------

class SolidInspectorTool(Tool):
    """Extensions-menu entry that opens (or raises) the inspector."""
    name = "Solid Inspector"
    shortcut = None
    uses_snap = False

    def on_activate(self, viewport) -> None:
        window = viewport.window()
        dialog = getattr(window, "_solid_inspector", None)
        if dialog is None or not dialog.isVisible():
            dialog = SolidInspectorDialog(viewport, parent=window)
            window._solid_inspector = dialog
            dialog.show()
        else:
            dialog.refresh()
            dialog.raise_()
            dialog.activateWindow()

    def on_deactivate(self, viewport) -> None:
        pass
