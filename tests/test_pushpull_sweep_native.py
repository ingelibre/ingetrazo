# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A push's drag overlay is drawn from its sweep (Bloque 6c): the tool
keeps the rings and the offset, not ~400 fresh faces a frame, and the
Rust engine bakes the faces and draws the wireframe from them. The faces
made on demand are the ones the tool always made; the engine's
wireframe is the very bytes ``rubber_band_lines`` uploads; its bake the
very floats the Python bake makes — holed, concave, textured and plain
faces, pushed out and in, and a face that is almost a line."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402
import random  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from tools.pushpull import (PushPullTool, _sweep_arrays,  # noqa: E402
                            _SweepFaces, sweep_segments)
from views.viewport import _baked_bytes  # noqa: E402
from views.viewport.render import _segment_bytes  # noqa: E402

_app = QApplication.instance() or QApplication([])

ENGINE = (_native.native is not None and _native.qt_hypot() is not None
          and hasattr(_native.native, "preview_sweep_lines"))
needs_engine = pytest.mark.skipif(not ENGINE, reason="the Rust engine is off")

TEX = {"path": "/x/a.png", "sw": 0.5, "sh": 0.7, "rot": 15.0}


def _ring(o, u, w, n, r, star=False, turn=1):
    return [o + u * (r * math.cos(turn * 2 * math.pi * k / n)
                     * (0.45 if star and k % 2 == 0 else 1.0))
            + w * (r * math.sin(turn * 2 * math.pi * k / n)
                   * (0.45 if star and k % 2 == 0 else 1.0))
            for k in range(n)]


def _random_sweeps(rng, count=12):
    out = []
    for _ in range(count):
        o = V(rng.uniform(-20, 20), rng.uniform(-20, 20), rng.uniform(-3, 3))
        ax = V(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        u = V.crossProduct(ax, V(0.3, 0.1, 1)).normalized()
        w = V.crossProduct(ax, u).normalized()
        n = V.crossProduct(u, w).normalized()
        kind = rng.choice(["round", "star", "holed", "thin", "two", "quad"])
        if kind == "round":
            rings = [_ring(o, u, w, rng.choice([24, 64, 100]), rng.uniform(0.1, 3))]
        elif kind == "star":
            rings = [_ring(o, u, w, rng.randint(5, 30) * 2, 2.0, star=True)]
        elif kind == "holed":
            rings = [_ring(o, u, w, 4, 5.0)]
            rings += [_ring(o + u * dx, u, w, 12, 0.6, turn=-1)
                      for dx in (-2.0, 0.0, 2.0)]
        elif kind == "thin":
            rings = [[o, o + u * 3, o + u * 3 + w * 1e-6, o + w * 1e-6]]
        elif kind == "two":
            rings = [[o, o + u]]
        else:
            rings = [[o, o + u * 2, o + u * 2 + w, o + w]]
        d = rng.choice([2.75, -0.4, 1e-3, -3.5, 1e-6])
        out.append((rings, n * d, None, None))
    return out


@needs_engine
@pytest.mark.parametrize("cos", [0.85, -1.0, 0.0, 0.99999])
@pytest.mark.parametrize("seed", range(8))
def test_the_engines_wireframe_is_pythons(seed, cos):
    sweeps = _random_sweeps(random.Random(seed))
    pairs = [(list(r), [p + off for p in r])
             for rings, off, _c, _w in sweeps for r in rings]
    want = _segment_bytes(sweep_segments(pairs, cos))
    pos, sizes, counts, off3, _c, _w, _k = _sweep_arrays(sweeps, cos)
    got = _native.native.preview_sweep_lines(pos, sizes, counts, off3, cos,
                                             _native.qt_hypot())
    assert got == want


@needs_engine
def test_a_non_finite_sweep_is_left_to_python():
    sweeps = [([[V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)]], V(0, 0, float("nan")),
               None, None)]
    pos, sizes, counts, off3, _c, _w, _k = _sweep_arrays(sweeps, 0.85)
    assert _native.native.preview_sweep_lines(
        pos, sizes, counts, off3, 0.85, _native.qt_hypot()) is None


# ---- The tool and the view -------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    from views.viewport import Viewport
    w = MainWindow()
    if ENGINE and Viewport._preview_native_state is not True:
        Viewport._preview_native_state = None
        assert w.viewport._check_preview_native()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _holed(mesh):
    outer = [V(10, -5, 0), V(30, -5, 0), V(30, 15, 0), V(10, 15, 0)]
    holes = [_ring(V(12.5 + 5 * i, -2.5 + 5 * j, 0), V(1, 0, 0), V(0, 1, 0),
                   24, 1.2, turn=-1) for i in range(4) for j in range(4)]
    return mesh.add_face(outer, holes)


def _star(mesh):
    return mesh.add_face(_ring(V(-8, 4, 0), V(1, 0, 0), V(0, 1, 0), 40, 3.0,
                               star=True))


def _sliver(mesh):
    o = V(0, -30, 0)
    return mesh.add_face([o, o + V(5, 0, 0), o + V(5, 2e-4, 0),
                          o + V(0, 2e-4, 0)])


SHAPES = {"holed": _holed, "star": _star, "sliver": _sliver}


def _drag(win, shape, textured, d):
    from tests.test_pushpull_ux import _ctx
    vp = win.viewport
    sc = vp.scene
    face = SHAPES[shape](sc.mesh)
    face.attrs = {"texture": dict(TEX)} if textured else {"color": (0.3, 0.6, 0.2)}
    sc.version += 1
    win._activate_tool("pushpull")
    tool = vp.active_tool
    tool.hovered_face = face
    tool.on_click(_ctx(vp))
    assert tool.dragging and not tool._attached
    tool.extrusion = d
    tool._show_light_preview(vp)
    return vp, tool


@pytest.mark.parametrize("d", [1.75, -0.9])
@pytest.mark.parametrize("textured", [True, False])
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_overlay_is_drawn_from_the_sweep(win, shape, textured, d):
    vp, tool = _drag(win, shape, textured, d)
    try:
        faces = tool.preview_faces()
        assert isinstance(faces, _SweepFaces) and faces
        if ENGINE:
            got = vp._bake_preview_faces(faces, tool)
            raw = vp._preview_lines_native(tool)
            assert faces._faces is None, "the engine's frame made the faces"
            assert raw is not None
        # Made on demand: the faces and wireframe the tool always made.
        want_faces = tool._build_light_faces()      # the eager list
        tool._light_faces = faces
        tool._light_rings = None
        tool._light_spec = (faces, faces._sweeps)
        assert [(f.vertices, f.holes, f.attrs) for f in faces] == \
            [(f.vertices, f.holes, f.attrs) for f in want_faces]
        lines = tool.rubber_band_lines()
        assert lines == sweep_segments(
            [(low, [p + low_off for p in low])
             for rings, low_off, _c, _w in faces._sweeps for low in rings],
            tool._CURVE_FACET_COS)
        want = vp._bake_preview_faces_py(list(want_faces))
        if ENGINE:
            assert _baked_bytes(got) == _baked_bytes(want)
            assert raw == _segment_bytes(lines)
        else:
            assert vp._preview_lines_native(tool) is None
            assert _baked_bytes(vp._bake_preview_faces(faces, tool)) == \
                _baked_bytes(want)
    finally:
        tool.on_cancel(vp)


def test_a_stale_overlay_leaves_the_tools_wireframe_alone(win):
    vp, tool = _drag(win, "star", False, 1.0)
    try:
        old = tool.preview_faces()
        tool.extrusion = 2.0
        tool._show_light_preview(vp)
        new = tool.preview_faces()
        assert len(old) == len(new)               # the old one, made late
        assert tool._light_rings is None or tool._light_faces is new
        high = [p.z() for _l, h in (tool._light_rings or []) for p in h]
        lines = tool.rubber_band_lines()
        assert {round(b.z(), 4) for _a, b in lines} >= {2.0}
        assert all(abs(z - 2.0) < 1e-4 for z in high)
    finally:
        tool.on_cancel(vp)


def test_the_eager_sweep_still_is_a_list():
    from tests.test_pushpull_staged_preview import _split_top
    scene, face = _split_top()
    tool = PushPullTool()
    tool.base_face = face
    tool._normal = face.normal()
    tool.extrusion = 0.5
    out = tool._build_light_faces()
    assert type(out) is list and out
    assert tool.preview_sweeps() is None    # built, not shown
