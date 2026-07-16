# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Regenerate the static thumbnails of the 3D starter components.

The Components tray shows PRE-RENDERED images (resources/components/thumbs)
so opening the panel never touches the GL renderer. Run this whenever the
component models change:

    QT_QPA_PLATFORM=xcb venv/bin/python scripts/gen_component_thumbs.py

Needs a real display (the render pipeline is the app's own paintGL); axes
and sky are patched out for a clean flat background.
"""
import math
import os
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
app.setOrganizationName("IngeTrazoThumbs")
app.setApplicationName("gen-thumbs")

import views.viewport as vpmod

# No axes, no sky: flat light background for the thumbnails.
vpmod._axes_vertices = lambda spacing: (
    array("f"), {"x": (0, 0), "y": (0, 0), "z": (0, 0)})

from views.main_window import MainWindow  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "resources" / "components" / "thumbs"
KEYS = ["person", "tree", "bush", "car"]

window = MainWindow()
window.resize(700, 700)
window.show()
viewport = window.viewport
viewport._draw_sky = lambda mvp: None


def snap(i: int = 0) -> None:
    if i >= len(KEYS):
        os._exit(0)
    key = KEYS[i]
    viewport.scene.clear()
    viewport.scene.groups.clear()
    window._on_insert_component(key)
    viewport.scene.selection.clear()      # no orange selection tint
    lo, hi = viewport.scene.bounds()
    cam = viewport.camera
    cam.yaw = math.radians(-50.0)
    cam.pitch = math.radians(12.0)
    pad = 0.08 * max(hi.x() - lo.x(), hi.y() - lo.y(), hi.z() - lo.z(), 0.5)
    from PySide6.QtGui import QVector3D
    cam.fit_to(QVector3D(lo.x() - pad, lo.y() - pad, lo.z() - pad),
               QVector3D(hi.x() + pad, hi.y() + pad, hi.z() + pad))
    image = viewport.render_image(320)
    OUT.mkdir(parents=True, exist_ok=True)
    image.save(str(OUT / f"{key}.png"))
    print("thumb:", key, image.width(), "x", image.height(), flush=True)
    QTimer.singleShot(300, lambda: snap(i + 1))


QTimer.singleShot(900, lambda: snap(0))
QTimer.singleShot(30000, lambda: os._exit(1))
app.exec()
