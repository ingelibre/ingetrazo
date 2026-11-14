# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Profiles without Edges (issue #1253): with the Edges style option off
and Profiles on, a curved surface lost its outline entirely — the
profile (silhouette) pass was gated on Edges, although SketchUp draws
profiles as an independent option. Renders a soft-seamed cylinder and
reads the pixels along its silhouette.

Needs a GL context that renders; skipped where the platform has none."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

SIDES = 12
RADIUS = 1.0
HEIGHT = 2.0


def _cylinder(mesh):
    """A closed 12-sided cylinder around the Z axis; its side seams are
    soft, so the only lines the outline can come from are profiles."""
    ring0 = [V(RADIUS * math.cos(2 * math.pi * i / SIDES),
               RADIUS * math.sin(2 * math.pi * i / SIDES), 0)
             for i in range(SIDES)]
    ring1 = [V(p.x(), p.y(), HEIGHT) for p in ring0]
    sides = []
    for i in range(SIDES):
        j = (i + 1) % SIDES
        sides.append(mesh.add_face([ring0[i], ring0[j], ring1[j], ring1[i]]))
    mesh.add_face(list(reversed(ring0)))              # bottom, facing -Z
    mesh.add_face(ring1)                              # top, facing +Z
    for e in mesh.edges:
        if len(e.faces) == 2 and all(f in sides for f in e.faces):
            e.soft = True


def _dark(c):
    """Ink on paper: clearly darker than the white faces and the grey
    background (antialiasing spreads a 1 px line over two rows)."""
    return c.lightnessF() < 0.72


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        w.close()
        pytest.skip("no OpenGL context on this platform")
    sc = vp.scene
    sc.guides.clear()
    _cylinder(sc.mesh)
    sc.version += 1
    st = sc.display_style
    st.face_mode, st.sky = "hidden_line", False
    vp.camera.set_view("front")                       # looking toward +Y
    vp.camera.perspective = False
    vp.camera.fit_to(V(-1.6, -1, 0), V(1.6, 1, 2))
    yield w
    w._saved_version = vp.scene.version
    w.close()


def _column(win, x=-RADIUS, z0=0.3, z1=1.7, n=40):
    """The darkest pixel across the vertical run at world ``x`` (the
    cylinder's silhouette line), ±2 px along the screen horizontal."""
    vp = win.viewport
    img = vp.grabFramebuffer()
    vp.grabFramebuffer()                              # settle a second frame
    img = vp.grabFramebuffer()
    dpr = img.width() / max(vp.width(), 1)
    out = []
    for i in range(n):
        p = V(x, 0, z0 + (z1 - z0) * i / (n - 1))
        px = vp._world_to_pixel(p)
        cx, cy = px[0] * dpr, px[1] * dpr
        out.append(min(
            (img.pixelColor(math.floor(cx + k), math.floor(cy))
             for k in (-2, -1, 0, 1, 2)),
            key=lambda c: c.lightnessF()))
    return out


def _ink_fraction(win):
    col = _column(win)
    return sum(1 for c in col if _dark(c)) / len(col)


def test_profiles_draw_without_edges(win):
    st = win.viewport.scene.display_style
    st.edges, st.profiles = False, True
    assert _ink_fraction(win) > 0.8


def test_no_profiles_no_outline_without_edges(win):
    st = win.viewport.scene.display_style
    st.edges, st.profiles = False, False
    assert _ink_fraction(win) < 0.2


def test_profiles_still_draw_with_edges(win):
    st = win.viewport.scene.display_style
    st.edges, st.profiles = True, True
    assert _ink_fraction(win) > 0.8
