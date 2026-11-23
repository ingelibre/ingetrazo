# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Builds workflow-demo.igz: the smallest model that walks through the whole
IngeTrazo workflow, from the model tree to one PDF per trade.

    python examples/workflow-demo/workflow-demo.py

(from the IngeTrazo folder). It writes workflow-demo.igz next to this script.
The example is one room corner that gets new tiles and a sink cabinet:

  Model tree   Ground floor > Trade > Status > Element
  Layers       storey / trade / status layers on the CONTAINERS only
  BIM          IFC class on every element; tiles give 2.4 m2
  Views        V_Tiles (delta) and V_Kitchen (new), filed in folders
  Sheets       Sheet_Tiles and Sheet_Kitchen, one frame each at 1:25
  Sheet sets   (planned feature) shown here as one sheet folder per trade

See WORKFLOW.md in this folder for the walkthrough and the screenshots.
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

try:
    OUT = Path(__file__).with_name("workflow-demo.igz")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
except NameError:          # run inside IngeTrazo's Python console / MCP
    OUT = None
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.composition import Cajetin, Composicion, MarcoVista  # noqa: E402
from core.dimension import Dimension  # noqa: E402
from core.group import Group  # noqa: E402
from core.layers import Layer  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.saved_views import SavedView  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.sheet_folders import SheetFolder  # noqa: E402
from core.style import Style  # noqa: E402
from formats import igz  # noqa: E402

GREY = (0.62, 0.62, 0.62)
YELLOW = (0.95, 0.80, 0.10)
RED = (0.85, 0.15, 0.15)


def box_mesh(x0, y0, z0, x1, y1, z1) -> Mesh:
    m = Mesh()
    m.add_face([V(x0, y0, z0), V(x0, y1, z0), V(x1, y1, z0), V(x1, y0, z0)])
    m.add_face([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)])
    m.add_face([V(x0, y1, z0), V(x0, y1, z1), V(x1, y1, z1), V(x1, y1, z0)])
    m.add_face([V(x0, y0, z0), V(x0, y0, z1), V(x0, y1, z1), V(x0, y1, z0)])
    m.add_face([V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)])
    return m


def element(name, ifc_class, colour, *bbox) -> Group:
    """A building element: geometry + IFC tag, and NO layer (it inherits)."""
    g = Group(box_mesh(*bbox), name=name)
    g.ifc = {"class": ifc_class, "name": name}
    g.material = {"color": colour, "opacity": 1.0}
    return g


def covering(name, colour, *corners) -> Group:
    """A finish (tiles): one face, so its takeoff is exactly its area."""
    m = Mesh()
    m.add_face([V(*c) for c in corners])
    g = Group(m, name=name)
    g.ifc = {"class": "IfcCovering", "name": name}
    g.material = {"color": colour, "opacity": 1.0}
    return g


def container(name, layer, children) -> Group:
    """A container of the tree: carries the layer, holds the children."""
    g = Group(Mesh(), name=name)
    g.layer = layer
    g.adopt(children)
    return g


def build() -> Scene:
    s = Scene()

    # ---- Layers: three kinds, in folders --------------------------------
    s.layer_folders = ["Storey", "Trade", "Status"]
    s.layers += [
        Layer("GF", folder="Storey"),
        Layer("Walls", color=(0.80, 0.80, 0.80), folder="Trade"),
        Layer("Tiles", color=(0.40, 0.65, 0.90), folder="Trade"),
        Layer("Kitchen", color=(0.70, 0.55, 0.35), folder="Trade"),
        Layer("S_Existing", color=GREY, folder="Status"),
        Layer("S_Demolition", color=YELLOW, folder="Status"),
        Layer("S_New", color=RED, folder="Status"),
        Layer("Archive", visible=False),
        Layer("Annotations"),
    ]

    # ---- Elements (metres, Z up). Corner at the origin, room at +X/+Y ---
    floor = element("Floor", "IfcSlab", (0.80, 0.78, 0.74),
                    -0.2, -0.2, -0.2, 3.0, 2.6, 0.0)
    wall_a = element("Wall_A", "IfcWall", (0.92, 0.91, 0.88),
                     -0.2, -0.2, 0.0, 3.0, 0.0, 2.5)
    wall_b = element("Wall_B", "IfcWall", (0.92, 0.91, 0.88),
                     -0.2, 0.0, 0.0, 0.0, 2.6, 2.5)
    # The old splashback on Wall_A goes; the sink moves to Wall_B with new
    # tiles behind it.
    old_tiles = covering("Splashback_old", (0.55, 0.70, 0.55),   # 1.2 m2
                         (0.3, 0.005, 0.85), (0.3, 0.005, 1.45),
                         (2.3, 0.005, 1.45), (2.3, 0.005, 0.85))
    new_tiles = covering("Tiles_new", (0.93, 0.95, 0.98),        # 2.4 m2
                         (0.005, 0.2, 0.85), (0.005, 2.2, 0.85),
                         (0.005, 2.2, 2.05), (0.005, 0.2, 2.05))
    cabinet = element("Sink_base_cabinet", "IfcFurniture",
                      (0.30, 0.35, 0.45), 0.012, 0.6, 0.0, 0.612, 1.4, 0.85)

    # ---- Model tree: Storey > Trade > Status > Element -----------------
    gf = container("GF", "GF", [
        container("Walls", "Walls", [
            container("Walls_Existing", "S_Existing",
                      [floor, wall_a, wall_b])]),
        container("Tiles", "Tiles", [
            container("Tiles_Demolition", "S_Demolition", [old_tiles]),
            container("Tiles_New", "S_New", [new_tiles])]),
        container("Kitchen", "Kitchen", [
            container("Kitchen_New", "S_New", [cabinet])]),
    ])
    s.groups.append(gf)

    # A dimension anchored in the model: the tiled width.
    s.dimensions.append(Dimension(V(0.03, 0.2, 2.05), V(0.03, 2.2, 2.05),
                                  V(0, 0, 0.15), layer="Annotations"))

    # ---- Saved views (scenes), in folders ------------------------------
    delta = Style(name="Delta", color_by_layer=True).to_dict()
    cam = dict(target=(1.3, 1.1, 0.9), distance=7.0,
               yaw=math.radians(45), pitch=math.radians(24),
               perspective=False)   # parallel: sheets print to scale
    s.scene_folders = ["Status", "Trades"]
    s.saved_views += [
        SavedView("V_Tiles", folder="Trades", style=delta,
                  hidden_layers=["Kitchen", "Archive"], **cam),
        SavedView("V_Kitchen", folder="Trades",
                  hidden_layers=["S_Demolition", "Tiles", "Annotations",
                                 "Archive"], **cam),
        SavedView("Corner_old", folder="Status",
                  hidden_layers=["S_New", "Archive"], **cam),
        SavedView("Corner_new", folder="Status",
                  hidden_layers=["S_Demolition", "Archive"], **cam),
        SavedView("Corner_delta", folder="Status", style=delta,
                  hidden_layers=["Archive"], **cam),
    ]

    # ---- Sheets: one frame each, title block with placeholders ---------
    def sheet(name, view, title, number):
        c = Composicion(name=name, paper="A4", landscape=True)
        c.frames.append(MarcoVista(view_key=f"scene:{view}", scale_n=25.0,
                                   x_mm=15.0, y_mm=15.0, w_mm=267.0,
                                   h_mm=140.0, show_title=True,
                                   title_text=title))
        c.cajetin = Cajetin(x_mm=102.0, y_mm=162.0, w_mm=180.0, h_mm=33.0,
                            proyecto="IngeTrazo workflow demo",
                            autor="IngeTrazo contributors",
                            fecha="2026-11-23", escala="1:25",
                            lamina=number)
        return c

    tiles_sheet = sheet("Sheet_Tiles", "V_Tiles",
                        "Tiles: old (yellow) / new (red)", "T-01")
    kitchen_sheet = sheet("Sheet_Kitchen", "V_Kitchen",
                          "Kitchen: sink base cabinet", "K-01")

    # ---- Sheet sets (planned): one sheet folder per trade --------------
    f_tiler = SheetFolder(name="Set_Tiler")
    f_kitchen = SheetFolder(name="Set_Kitchen_fitter")
    s.sheet_folders += [f_tiler, f_kitchen]
    tiles_sheet.folder_id = f_tiler.id
    kitchen_sheet.folder_id = f_kitchen.id
    s.compositions += [tiles_sheet, kitchen_sheet]
    return s


def main(out=None) -> None:
    out = Path(out or OUT)
    scene = build()
    igz.save_scene(scene, out)
    print(f"Written: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
