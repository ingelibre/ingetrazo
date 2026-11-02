# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Genera capas-prueba.igz: un documento de ejemplo con todas las funciones
de capas, para seguir el manual (docs/layers.md).

Desde la carpeta de IngeTrazo, con su entorno activado:

    python examples/capas-prueba.py

Deja capas-prueba.igz junto a este script (lo reescribe si ya existe).
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core import layers as L  # noqa: E402
from core.composition import Composicion, Leyenda, MarcoVista  # noqa: E402
from core.dimension import Dimension  # noqa: E402
from core.group import Group  # noqa: E402
from core.guide import Guide  # noqa: E402
from core.layers import DEFAULT_LAYER, Layer  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.saved_views import SavedView  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.section import SectionPlane  # noqa: E402
from core.textlabel import TextLabel  # noqa: E402
from formats import igz  # noqa: E402

OUT = Path(__file__).with_name("capas-prueba.igz")


def box(mesh, x0, y0, z0, x1, y1, z1):
    """Una caja cerrada de seis caras."""
    mesh.add_face([V(x0, y0, z0), V(x0, y1, z0), V(x1, y1, z0), V(x1, y0, z0)])
    mesh.add_face([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)])
    mesh.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)])
    mesh.add_face([V(x0, y1, z0), V(x0, y1, z1), V(x1, y1, z1), V(x1, y1, z0)])
    mesh.add_face([V(x0, y0, z0), V(x0, y0, z1), V(x0, y1, z1), V(x0, y1, z0)])
    mesh.add_face([V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)])


def obj(scene, name, layer, x0, y0, z0, x1, y1, z1):
    g = Group(Mesh(), name=name)
    box(g.mesh, x0, y0, z0, x1, y1, z1)
    g.layer = None if layer == DEFAULT_LAYER else layer
    scene.groups.append(g)
    return g


def build() -> Scene:
    s = Scene()

    # ---- Carpetas: «Estructura» dentro de «Arquitectura»; una vacía -----
    s.layer_folders = ["Arquitectura", "Estructura", "Instalaciones",
                       "Carpeta vacía"]
    s.folder_parents = {"Estructura": "Arquitectura"}

    # ---- Capas: cada una prueba algo distinto ---------------------------
    s.layers += [
        Layer("Muros", color=(0.80, 0.45, 0.30), folder="Arquitectura",
              lineweight=0.50),
        Layer("Puertas y ventanas", color=(0.35, 0.55, 0.80),
              folder="Arquitectura", linetype="dashed"),
        Layer("Pilares", color=(0.55, 0.55, 0.60), folder="Estructura",
              lineweight=0.35),
        Layer("Vigas", color=(0.45, 0.65, 0.45), folder="Estructura",
              linetype="dashed_long"),
        Layer("Agua", color=(0.20, 0.45, 0.95), folder="Instalaciones",
              linetype="dashed_short"),
        Layer("Gas", color=(0.95, 0.75, 0.10), folder="Instalaciones",
              linetype="phantom"),
        Layer("Electricidad", color=(0.85, 0.20, 0.20),
              folder="Instalaciones", linetype="dashdotdot"),
        Layer("Ejes", color=(0.75, 0.30, 0.65), linetype="center",
              lineweight=0.18),
        Layer("Límites", linetype="border"),
        Layer("Mobiliario", color=(0.60, 0.45, 0.25), opacity=0.5),
        Layer("Referencia", linetype="dotted", printable=False),
        Layer("Terreno", color=(0.45, 0.60, 0.35), locked=True),
        Layer("Oculta a mano", visible=False),
        Layer("Cotas y textos"),
        Layer("Guías", printable=False),
        Layer("Secciones"),
        # Orden natural: «Capa 2» antes que «Capa 10».
        Layer("Capa 2"), Layer("Capa 10"), Layer("Capa 1"),
        # Sin nada: lo que Purgar borraría.
        Layer("Vacía 1"), Layer("Vacía 2"),
    ]

    # ---- Geometría: un objeto por capa, en fila ------------------------
    # Losa suelta en Layer 0 (la geometría suelta se queda en Layer 0).
    s.mesh.add_face([V(-2, -2, 0), V(30, -2, 0), V(30, 12, 0), V(-2, 12, 0)])
    obj(s, "Muro norte", "Muros", 0, 9, 0, 12, 9.3, 3)
    obj(s, "Muro sur", "Muros", 0, 0, 0, 12, 0.3, 3)
    obj(s, "Muro oeste", "Muros", 0, 0, 0, 0.3, 9.3, 3)
    obj(s, "Ventana", "Puertas y ventanas", 4, -0.05, 1, 6, 0.35, 2.2)
    obj(s, "Pilar 1", "Pilares", 3, 3, 0, 3.3, 3.3, 3)
    obj(s, "Pilar 2", "Pilares", 8, 3, 0, 8.3, 3.3, 3)
    obj(s, "Viga", "Vigas", 3, 3, 2.7, 8.3, 3.3, 3)
    obj(s, "Tubo de agua", "Agua", 14, 1, 0.2, 24, 1.15, 0.35)
    obj(s, "Tubo de gas", "Gas", 14, 3, 0.2, 24, 3.15, 0.35)
    obj(s, "Canaleta eléctrica", "Electricidad", 14, 5, 2.4, 24, 5.2, 2.6)
    obj(s, "Eje A", "Ejes", -1, 4.5, 0, 28, 4.55, 0.02)
    obj(s, "Límite de parcela", "Límites", -1.5, -1.5, 0, 29.5, -1.45, 0.02)
    obj(s, "Mesa", "Mobiliario", 5, 5, 0, 7, 6, 0.75)
    obj(s, "Armario", "Mobiliario", 9.5, 7, 0, 11.5, 8.5, 2)
    obj(s, "Silueta de referencia", "Referencia", 15, 8, 0, 20, 10, 0.05)
    obj(s, "Talud", "Terreno", 25, 0, 0, 29, 10, 0.6)
    obj(s, "Caja oculta", "Oculta a mano", 26, 10.5, 0, 27, 11.5, 1)
    obj(s, "Objeto Capa 1", "Capa 1", 0, 13, 0, 1, 14, 1)
    obj(s, "Objeto Capa 2", "Capa 2", 2, 13, 0, 3, 14, 1)
    obj(s, "Objeto Capa 10", "Capa 10", 4, 13, 0, 5, 14, 1)
    obj(s, "Suelto en Layer 0", DEFAULT_LAYER, 6.5, 13, 0, 7.5, 14, 1)

    # ---- Anotaciones en su capa ---------------------------------------
    s.dimensions.append(Dimension(V(0, 0, 0), V(12, 0, 0), V(0, -1, 0),
                                  layer="Cotas y textos"))
    s.text_labels.append(TextLabel(V(6, 4.5, 3), V(0, 0, 1),
                                   "Sala principal", layer="Cotas y textos"))

    # ---- Guías en su capa: una línea por el eje A y un punto ----------
    # Al apagar «Guías» desaparecen y el lápiz deja de engancharse a ellas.
    s.guides.append(Guide(V(0, 4.5, 0), V(1, 0, 0), layer="Guías"))
    s.guides.append(Guide(V(12, 9, 3), None, V(12, 0, 3), layer="Guías"))

    # ---- Plano de sección en su capa ----------------------------------
    plane = SectionPlane(V(6, 0, 0), V(1, 0, 0), name="Corte A",
                         symbol="A")
    plane.layer = "Secciones"
    s.section_planes.append(plane)

    # ---- Escenas -----------------------------------------------------
    # Planta: la orientación de la vista superior estándar (X a la derecha).
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    cam.set_view("top")
    top = dict(target=(14.0, 6.0, 0.0), distance=40.0, yaw=cam.yaw,
               pitch=math.radians(89.9), perspective=False)
    s.saved_views += [
        SavedView("Planta general", hidden_layers=["Mobiliario"], **top),
        SavedView("Solo instalaciones",
                  hidden_layers=["Muros", "Puertas y ventanas", "Pilares",
                                 "Vigas", "Mobiliario", "Terreno"], **top),
        SavedView("Vista 3D", target=(14.0, 5.0, 1.0), distance=45.0),
    ]

    # ---- Capa activa: los objetos nuevos irán a «Muros» --------------
    s.active_layer = "Muros"

    # ---- Una lámina con dos marcos y la leyenda ----------------------
    sheet = Composicion(name="Lámina de capas", paper="A3")
    sheet.frames += [
        MarcoVista(view_key="scene:Planta general", style="vectorial",
                   scale_n=200.0, x_mm=15.0, y_mm=20.0, w_mm=190.0,
                   h_mm=120.0, show_title=True,
                   title_text="Planta general (en negro)"),
        MarcoVista(view_key="scene:Solo instalaciones", style="vectorial",
                   scale_n=200.0, x_mm=215.0, y_mm=20.0, w_mm=190.0,
                   h_mm=120.0, layer_colours=True, show_title=True,
                   title_text="Instalaciones (líneas con el color de su capa)"),
    ]
    rows, swatches = L.legend_rows(s)
    sheet.leyendas.append(Leyenda(x_mm=15.0, y_mm=150.0, w_mm=80.0,
                                  title="CAPAS", rows=rows,
                                  swatches=swatches))
    s.compositions.append(sheet)
    return s


def main() -> None:
    scene = build()
    igz.save_scene(scene, OUT)
    back = Scene()
    igz.load_into(back, OUT)
    print(f"Creado: {OUT}")
    print(f"  {len(back.layers)} capas, {len(L.folders_of(back))} carpetas, "
          f"{len(back.groups)} objetos, {len(back.saved_views)} escenas, "
          f"{len(back.compositions)} lámina(s)")
    print(f"  capa activa: {back.active_layer}")
    print("  no se imprimen: "
          + ", ".join(ly.name for ly in L.unprinted(back)))


if __name__ == "__main__":
    main()
