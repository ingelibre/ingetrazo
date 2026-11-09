# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Curved surfaces shade round in the viewport, not faceted (#131).

The viewport bakes its matte shading into the vertex colours, one colour
per face from the face's own normal: a sphere or a cylinder joined by soft
edges hid its lines and still showed every facet. Each corner on a curved
surface now takes the colour of the SURFACE's normal there — the smooth
normals the exports write — so neighbouring faces meet in one colour and
the GPU blends across them. A hard edge keeps its crease, and a model
without soft edges is drawn exactly as before."""
from __future__ import annotations

import math
import os
import types
from collections import defaultdict

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np                                                # noqa: E402
import pytest                                                     # noqa: E402
from PySide6.QtGui import QVector3D                               # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from views.viewport import Viewport                               # noqa: E402

SIDES = 12
# A light from the side: every side face of the cylinder gets a clearly
# different flat shade, and the caps (normal ±Z) the darkest one.
SIDE_LIGHT = QVector3D(1.0, 0.3, 0.0).normalized()


def V(x, y, z):
    return QVector3D(float(x), float(y), float(z))


def _cylinder(mesh, soft=True):
    ring0 = [V(math.cos(2 * math.pi * i / SIDES),
               math.sin(2 * math.pi * i / SIDES), 0) for i in range(SIDES)]
    ring1 = [V(p.x(), p.y(), 2) for p in ring0]
    sides = [mesh.add_face([ring0[i], ring0[(i + 1) % SIDES],
                            ring1[(i + 1) % SIDES], ring1[i]])
             for i in range(SIDES)]
    mesh.add_face(list(reversed(ring0)))
    mesh.add_face(ring1)
    if soft:
        for e in mesh.edges:
            if len(e.faces) == 2 and all(f in sides for f in e.faces):
                e.soft = True
    return mesh


def _box(mesh):
    c = [V(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    for q in ([0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4],
              [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]):
        mesh.add_face([c[i] for i in q])
    return mesh


class _VP:
    def __init__(self, scene):
        self.scene = scene

    def width(self):
        return 100

    def height(self):
        return 100


def _stub(scene):
    """A Viewport with no GL: every plain method bound, no disk cache."""
    vp = _VP(scene)
    for name in dir(Viewport):
        if name.startswith("__") or hasattr(vp, name):
            continue
        attr = Viewport.__dict__.get(name)
        if isinstance(attr, types.FunctionType):
            setattr(vp, name, attr.__get__(vp))
        elif isinstance(attr, staticmethod):
            setattr(vp, name, attr.__func__)
        elif not callable(attr) and attr is not None:
            setattr(vp, name, attr)
    vp.active_tool = None
    vp._chunk_cache_load = None
    vp._chunk_cache_store = None
    vp._LIGHT = SIDE_LIGHT
    return vp


def _chunk_rows(mesh):
    scene = Scene()
    g = Group(mesh, name="cilindro")
    scene.groups.append(g)
    vp = _stub(scene)
    return np.frombuffer(vp._group_chunk(g)["vcol"],
                         dtype=np.float32).reshape(-1, 6)


def _colours_at(rows):
    """``{position: {rgb, …}}`` over every drawn corner."""
    out = defaultdict(set)
    for r in rows:
        out[tuple(np.round(r[:3], 5))].add(tuple(np.round(r[3:], 5)))
    return out


def test_a_soft_cylinder_meets_in_one_colour_at_each_seam():
    at = _colours_at(_chunk_rows(_cylinder(Mesh())))
    assert len(at) == 2 * SIDES
    # The side surface brings ONE colour to each corner, the cap its own.
    assert all(len(cols) == 2 for cols in at.values())


def test_hard_seams_keep_one_colour_per_face():
    at = _colours_at(_chunk_rows(_cylinder(Mesh(), soft=False)))
    # Two side faces and a cap meet at each corner, each in its flat colour.
    assert max(len(cols) for cols in at.values()) == 3


def test_a_soft_side_face_shades_across_its_width():
    rows = _chunk_rows(_cylinder(Mesh()))
    side = rows[:6]                     # the first side face, two triangles
    assert len({tuple(np.round(r[3:], 5)) for r in side}) == 2


def test_the_cap_keeps_its_flat_colour_against_a_soft_side():
    mesh = _cylinder(Mesh())
    flat = _stub(Scene())._shaded_color(Viewport.DEFAULT_FACE_COLOR,
                                        QVector3D(0, 0, 1))
    rows = _chunk_rows(mesh)
    caps = [r for r in rows if abs(r[2]) < 1e-6 or abs(r[2] - 2) < 1e-6]
    on_ring = defaultdict(list)
    for r in caps:
        on_ring[tuple(np.round(r[:3], 5))].append(r[3:])
    # Every ring corner shows the cap's flat colour among its two.
    assert len(on_ring) == 2 * SIDES
    assert all(any(np.allclose(c, flat, atol=1e-6) for c in cols)
               for cols in on_ring.values())


def test_a_box_is_drawn_exactly_as_before():
    rows = _chunk_rows(_box(Mesh()))
    tri = rows.reshape(-1, 3, 6)
    # Every triangle in one flat colour, quantised as the face shade is.
    assert np.all(tri[:, :, 3:] == tri[:, :1, 3:])
    assert np.allclose(rows[:, 3:] * 64.0, np.round(rows[:, 3:] * 64.0),
                       atol=1e-4)


def test_coplanar_faces_joined_by_a_soft_edge_keep_the_flat_colour():
    mesh = Mesh()
    a = mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    b = mesh.add_face([V(0, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    for e in mesh.edges:
        if a in e.faces and b in e.faces:
            e.soft = True
    rows = _chunk_rows(mesh)
    assert len({tuple(r[3:]) for r in rows}) == 1


def _loose_face_rows(win):
    sent = {}

    def fake_upload(_vbo, slot, parts, empty=24):
        data = b"".join(parts)
        sent[slot] = data
        return len(data)
    vp = win.viewport
    vp._upload_vbo = fake_upload
    import re
    import views.viewport as vpmod
    src = open(vpmod.__file__, encoding="utf-8").read()
    for name in set(re.findall(r"self\.(_\w+_vbo)\b", src)):
        if not hasattr(vp, name):
            setattr(vp, name, None)
    vp._sync_edges()
    return np.frombuffer(sent["faces"], dtype=np.float32).reshape(-1, 6)


def test_loose_geometry_shades_round_too():
    from views.main_window import MainWindow
    win = MainWindow()
    vp, sc = win.viewport, win.viewport.scene
    vp._LIGHT = SIDE_LIGHT
    _cylinder(sc.mesh)
    sc.version += 1
    at = _colours_at(_loose_face_rows(win))
    assert len(at) == 2 * SIDES
    assert all(len(cols) == 2 for cols in at.values())
    win._saved_version = sc.version
    win.close()

