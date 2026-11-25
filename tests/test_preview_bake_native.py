# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rust engine bakes a tool's preview faces (a push's overlay, a paste,
a move's stretched faces) to the very floats, runs and order the Python
bake makes (19-11): random faces of every kind and map, the sweep a push
builds from its base, empty lists, degenerate and non-finite corners."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402
import random  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core.geometry import Face  # noqa: E402
from core.preview_probe import MATERIALS, _sweep, probe_faces, probe_sweeps  # noqa: E402
from views.viewport import _baked_bytes  # noqa: E402

_app = QApplication.instance() or QApplication([])

needs_engine = pytest.mark.skipif(
    _native.native is None or _native.qt_hypot() is None
    or not hasattr(_native.native, "preview_faces_bake"),
    reason="the Rust engine is off")


@pytest.fixture(scope="module")
def vp():
    from views.main_window import MainWindow
    win = MainWindow()
    yield win.viewport
    win._saved_version = win.viewport.scene.version
    win.close()


def _same(got, want):
    assert got is not None, "the engine refused faces Python bakes"
    assert _baked_bytes(got) == _baked_bytes(want)


@needs_engine
def test_the_check_passes_here(vp):
    from views.viewport import Viewport
    Viewport._preview_native_state = None
    assert not vp._preview_native_ok()      # queued, Python meanwhile
    assert vp._check_preview_native()
    assert vp._preview_native_ok()


@needs_engine
@pytest.mark.parametrize("seed", range(12))
def test_random_faces_bake_alike(vp, seed):
    faces = probe_faces(seed=seed, count=120)
    _same(vp._bake_preview_faces_native(faces), vp._bake_preview_faces_py(faces))


@needs_engine
@pytest.mark.parametrize("seed", range(8))
def test_sweeps_bake_alike(vp, seed):
    faces, sweeps = probe_sweeps(seed=seed)
    _same(vp._bake_preview_sweeps_native(sweeps),
          vp._bake_preview_faces_py(faces))
    _same(vp._bake_preview_faces_native(faces),
          vp._bake_preview_faces_py(faces))


@needs_engine
@pytest.mark.parametrize("seed", range(6))
def test_random_sweeps_at_many_distances(vp, seed):
    """A drag's every frame: one base, distances from 1e-5 to 1e3 either
    way, along slanted normals; holes; every material."""
    rng = random.Random(seed)
    for _ in range(25):
        n = rng.randint(3, 64)
        o = V(rng.uniform(-90, 90), rng.uniform(-90, 90), rng.uniform(-9, 9))
        ax = V(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        u = V.crossProduct(ax, V(0.3, 0.1, 1)).normalized()
        w = V.crossProduct(ax, u).normalized()
        r = rng.uniform(0.05, 6)
        outer = [o + u * (r * math.cos(2 * math.pi * k / n))
                 + w * (r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        rings = [outer]
        if rng.random() < 0.4:
            rings.append([o + u * (0.2 * r * math.cos(-2 * math.pi * k / 5))
                          + w * (0.2 * r * math.sin(-2 * math.pi * k / 5))
                          for k in range(5)])
        nrm = V.crossProduct(u, w).normalized()
        d = rng.choice([-1, 1]) * 10 ** rng.uniform(-5, 3)
        attrs = rng.choice(MATERIALS)
        wall = None
        if attrs and "texture" in attrs:
            wall = {"texture": {**{k: v for k, v in attrs["texture"].items()
                                   if k != "uvw"}, "planar": True}}
        elif attrs:
            wall = dict(attrs)
        spec = [(rings, nrm * d, attrs, wall)]
        faces = _sweep(rings, nrm * d, attrs, wall)
        _same(vp._bake_preview_sweeps_native(spec),
              vp._bake_preview_faces_py(faces))


@needs_engine
def test_edge_cases(vp):
    py, nat = vp._bake_preview_faces_py, vp._bake_preview_faces_native
    _same(nat([]), py([]))
    _same(vp._bake_preview_sweeps_native([]), py([]))
    tex = {"texture": {"path": "/x.png"}}
    odd = [Face([]), Face([V(1, 2, 3)]), Face([V(0, 0, 0), V(1, 0, 0)], attrs=tex),
           Face([V(0, 0, 0)] * 4, attrs=tex),               # all one point
           Face([V(0, 0, 0), V(1, 0, 0), V(2, 0, 0)]),      # collinear
           Face([V(0, 0, 0), V(1e-5, 0, 0), V(0, 1e-5, 0)], attrs=tex),
           Face([V(1e30, 0, 0), V(1e30, 1e30, 0), V(0, 1e30, 0)]),
           Face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)],
                [[V(0.2, 0.2, 0)], [V(0.5, 0.5, 0), V(0.6, 0.5, 0)]], attrs=tex),
           # A bow tie, a hole touching the outer ring, a doubled corner.
           Face([V(0, 0, 0), V(1, 1, 0), V(1, 0, 0), V(0, 1, 0)]),
           Face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)],
                [[V(0, 0, 0), V(0.5, 1, 0), V(1, 0.5, 0)]], attrs=tex),
           Face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])]
    _same(nat(odd), py(odd))


@needs_engine
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_corners_fall_back(vp, bad):
    """A NaN or infinite corner is outside what the start-up check vouches
    for (Qt's hypot on it), and Python's shade may raise on it: the engine
    hands such a frame back (None) and Python does what it always did."""
    good = Face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    for f in (Face([V(0, 0, 0), V(bad, 0, 0), V(1, 1, 0)]),
              Face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)], [[V(0, bad, 0)] * 3])):
        assert vp._bake_preview_faces_native([good, f]) is None
    assert vp._bake_preview_sweeps_native(
        [([[V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)]], V(0, 0, bad), None, None)]) is None


@needs_engine
def test_mesh_faces_stay_in_python(vp):
    class Loopy(Face):
        loop = ()
    f = Loopy([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    assert vp._bake_preview_faces_native([f]) is None


def test_python_bake_without_the_engine(vp, monkeypatch):
    """No engine: the draw bakes in Python, as before."""
    from views.viewport import Viewport
    monkeypatch.setattr(_native, "native", None)
    monkeypatch.setattr(Viewport, "_preview_native_state", None)
    assert not vp._check_preview_native()
    assert not vp._preview_native_ok()
    faces = probe_faces(count=30)
    _same(vp._bake_preview_faces(faces), vp._bake_preview_faces_py(faces))


@needs_engine
def test_the_drawn_bake_is_the_sweep_one(vp, monkeypatch):
    """The draw takes the tool's sweep (``preview_sweeps``) when it is the
    very list of faces shown, the faces otherwise."""
    from views.viewport import Viewport
    monkeypatch.setattr(Viewport, "_preview_native_state", True)
    faces, sweeps = probe_sweeps()
    calls = []

    class Tool:
        def preview_sweeps(self):
            calls.append(1)
            return (faces, sweeps)
    _same(vp._bake_preview_faces(faces, Tool()), vp._bake_preview_faces_py(faces))
    assert calls
    other = list(faces)
    _same(vp._bake_preview_faces(other, Tool()), vp._bake_preview_faces_py(other))


@needs_engine
def test_the_start_check_waits_for_the_hand_to_pause(vp, monkeypatch):
    """The check bakes its sample in Python too: not while the user drags
    (19-11) — it waits for a pause, then runs."""
    from views.viewport import Viewport
    monkeypatch.setattr(Viewport, "_preview_native_state", None)
    monkeypatch.setattr(vp, "_preview_check_waits", 0, raising=False)
    busy = [True]
    monkeypatch.setattr(vp, "view_busy", lambda: busy[0])
    queued = []
    monkeypatch.setattr(vp, "_schedule_preview_check",
                        lambda delay_ms=1500: queued.append(delay_ms))
    assert vp._check_preview_native() is False
    assert Viewport._preview_native_state is None and queued == [300]
    busy[0] = False
    assert vp._check_preview_native() is True
    assert Viewport._preview_native_state is True
