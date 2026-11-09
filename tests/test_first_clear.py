# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The first point in sight of an ordered list, asked of the native engine
in one call (``Viewport._first_clear``, #158), is the one
``_occluded_many_now`` gives asking each in turn — over random points in
front of, on and behind the copies, repeated, on the eye — and the corner
``pick_vertex`` picks is the same either way. The rays the engine cannot
call bit for bit are asked as before; a section cut and X-ray are left to
the old path or answered at once. Skipped without the engine."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402

import views.viewport as viewport_mod  # noqa: E402
from tests.test_lazy_native_snap import (  # noqa: E402
    VIEWS, _close, _key, _set_view, _window, pytestmark)

from tests.test_lazy_native_snap import mod  # noqa: E402

pytestmark = [pytestmark, pytest.mark.skipif(
    mod is None or not hasattr(getattr(mod, "InstanceSet", None),
                               "first_clear"),
    reason="native module without first_clear"), pytest.mark.skipif(
    not viewport_mod._qv_hypot3(),
    reason="no vectorised ray formula for this Qt's QVector3D length")]


@pytest.fixture
def win():
    w, vp = _window(lazy=True)
    try:
        yield vp
    finally:
        _close(w)


def _points(rng, vp, n):
    """Corners of the copies, points on their faces and behind them, and
    random ones: hidden and seen in runs, with repeats."""
    e = vp.camera.eye()
    eye = np.array([e.x(), e.y(), e.z()])
    out = []
    for g in vp.scene.groups:
        xf = getattr(g, "xform", None)
        if xf is None:
            continue
        for v in g.mesh.vertices[:8]:
            p = xf.map(v.position)
            out.append((p.x(), p.y(), p.z()))
    out = np.array(out).reshape(-1, 3)
    pts = out[rng.integers(0, len(out), n)]
    k = rng.random(n)
    pts[k < 0.3] += (pts[k < 0.3] - eye) * rng.uniform(0.001, 0.3,
                                                       (int((k < 0.3).sum()), 1))
    pts[(k > 0.8)] = rng.uniform((-1, -1, -1), (18, 14, 4),
                                 (int((k > 0.8).sum()), 3))
    pts = np.concatenate([pts, pts[rng.integers(0, n, n // 5)]])
    return pts[rng.permutation(len(pts))]


def _want(vp, pts, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(viewport_mod, "_OCCLUSION_MEMO", False)
        hid = vp._occluded_many_now(pts)
    seen = [i for i, h in enumerate(hid) if not h]
    return seen[0] if seen else -1


def test_the_first_in_sight_is_the_one_asked_in_turn(win, monkeypatch):
    vp = win
    rng = np.random.default_rng(158)
    found = missed = 0
    for view in VIEWS:
        _set_view(vp, view)
        assert vp._lazy_native() is not None
        for _ in range(25):
            n = int(rng.choice((1, 3, 12, 60, 400)))
            pts = _points(rng, vp, n)
            # Runs of hidden points first, often: the batches go long.
            hid = np.array(vp._occluded_many_now(pts), dtype=bool)
            pts = np.concatenate([pts[hid], pts[~hid]]) if rng.random() < 0.5 \
                else pts
            got = vp._first_clear(pts)
            assert got == _want(vp, pts, monkeypatch), (view, n)
            found += got >= 0
            missed += got < 0
    assert found > 40 and missed > 5


def test_the_eye_itself_is_in_sight(win, monkeypatch):
    vp = win
    _set_view(vp, VIEWS[0])
    e = vp.camera.eye()
    pts = np.array([[e.x(), e.y(), e.z()]])
    assert vp._first_clear(pts) == _want(vp, pts, monkeypatch) == 0


def test_the_rays_it_cannot_call_are_asked_as_before(win, monkeypatch):
    """Every point before the one the engine sees handed back as in doubt:
    each is asked of ``_occluded_many_now`` in order, and the answer is
    the same."""
    vp = win
    rng = np.random.default_rng(7)
    iset = vp._lazy_native()[0]

    class _Doubting:
        def __getattr__(self, n):
            return getattr(iset, n)

        def first_clear(self, *a):
            first, _d = iset.first_clear(*a)
            n = len(a[2]) if first < 0 else first
            return first, np.arange(n, dtype=np.int64)
    asked = []
    real = type(vp)._occluded_many_now
    monkeypatch.setattr(type(vp), "_occluded_many_now",
                        lambda self, w: (asked.append(len(w)),
                                         real(self, w))[1])
    for view in VIEWS[:2]:
        _set_view(vp, view)
        nat = vp._lazy_native()
        monkeypatch.setattr(vp, "_lazy_native",
                            lambda nat=nat: (_Doubting(),) + tuple(nat[1:]))
        for _ in range(10):
            pts = _points(rng, vp, 60)
            want = _want(vp, pts, monkeypatch)
            asked.clear()
            assert vp._first_clear(pts) == want
            assert len(asked) == (want if want >= 0 else len(pts))
        monkeypatch.undo()
        monkeypatch.setattr(type(vp), "_occluded_many_now",
                            lambda self, w: (asked.append(len(w)),
                                             real(self, w))[1])


def test_xray_answers_at_once_and_a_cut_is_left_to_the_batches(win,
                                                               monkeypatch):
    from core.style import Style
    vp = win
    _set_view(vp, VIEWS[0])
    pts = _points(np.random.default_rng(1), vp, 30)
    vp.style_override = Style(name="x", face_mode="xray")
    assert vp._first_clear(pts) == 0 == _want(vp, pts, monkeypatch)
    vp.style_override = None
    monkeypatch.setattr(viewport_mod, "_active_cut", lambda sc: object())
    assert vp._first_clear(pts) is None
    monkeypatch.undo()
    monkeypatch.setattr(viewport_mod, "_FIRST_CLEAR", False)
    assert vp._first_clear(pts) is None


def test_the_corner_picked_is_the_same_asked_in_one_call(win, monkeypatch):
    vp = win
    seen = 0
    for view in VIEWS[:3]:
        _set_view(vp, view)
        for x in np.arange(11.3, 900, 21.0):
            for y in np.arange(7.9, 640, 27.0):
                vp._input_serial = (x, y)
                got = vp.pick_vertex(float(x), float(y))
                with monkeypatch.context() as m:
                    m.setattr(viewport_mod, "_FIRST_CLEAR", False)
                    want = vp.pick_vertex(float(x), float(y))
                assert _key(got) == _key(want), (view, x, y)
                seen += got is not None
    assert seen > 80
