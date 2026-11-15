# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Genera pestanas-prueba.igz: una casa sencilla con cuatro escenas, para
seguir el manual de pestañas, escenas y vistas (docs/project-tabs.md).

La casa (8 × 6 × 3 m, tejado a dos aguas, chimenea) y un muro bajo delante
se reconocen en planta, alzado, lateral y perspectiva, y las escenas
«Exterior», «Planta», «Alzado» y «Lateral» salen como pestañas bajo la
vista nada más abrirla.

Desde la carpeta de IngeTrazo, con su entorno activado:

    python examples/pestanas-prueba.py

Deja pestanas-prueba.igz junto a este script (lo reescribe si ya existe).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.camera import OrbitCamera  # noqa: E402
from core.saved_views import SavedView  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402

AQUI = Path(__file__).resolve().parent

#: (nombre, vista) de cada escena, en el orden de sus pestañas.
ESCENAS = (("Exterior", "iso"), ("Planta", "top"),
           ("Alzado", "front"), ("Lateral", "right"))


def caja(mesh, x0, y0, z0, dx, dy, dz) -> None:
    x1, y1, z1 = x0 + dx, y0 + dy, z0 + dz
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for a, b, c, d in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                       (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([p[a], p[b], p[c], p[d]])


def casa(scene) -> None:
    m = scene.mesh
    w, d, h, cumbre = 8.0, 6.0, 3.0, 5.0
    a, b, c, e = V(0, 0, 0), V(w, 0, 0), V(w, d, 0), V(0, d, 0)
    a2, b2, c2, e2 = V(0, 0, h), V(w, 0, h), V(w, d, h), V(0, d, h)
    m.add_face([a, e, c, b])                       # suelo
    m.add_face([a, b, b2, a2])                     # fachadas largas
    m.add_face([c, e, e2, c2])
    t0, t1 = V(0, d / 2, cumbre), V(w, d / 2, cumbre)
    m.add_face([e, a, a2, t0, e2])                 # hastiales
    m.add_face([b, c, c2, t1, b2])
    m.add_face([a2, b2, t1, t0])                   # faldones
    m.add_face([c2, e2, t0, t1])
    caja(m, 1.0, -3.0, 0.0, 6.0, 0.3, 1.0)         # muro bajo delante
    caja(m, 5.5, 3.6, 4.0, 0.6, 0.6, 1.8)          # chimenea


def escenas(scene) -> None:
    lo, hi = scene.bounds()
    for nombre, vista in ESCENAS:
        cam = OrbitCamera()
        cam.perspective = vista == "iso"
        cam.set_view(vista)
        if lo is not None:
            cam.fit_box(lo, hi)
        scene.saved_views.append(SavedView.capture(nombre, scene, cam))


def main() -> Path:
    scene = Scene()
    casa(scene)
    escenas(scene)
    scene.version += 1
    path = AQUI / "pestanas-prueba.igz"
    igz.save_scene(scene, path)
    print("Creado", path, len(list(scene.mesh.faces)), "caras,",
          len(scene.saved_views), "escenas")
    return path


if __name__ == "__main__":
    main()
