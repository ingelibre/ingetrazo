# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""With the engine's lazy placements (#158), what a point's ray meets is
kept for the view (``Viewport._occluded_many``): a pointer move asks again
only the points the last ones did not. The answers are the ones asked
afresh — in any order, batch and repeat — and anything that changes what
a ray may meet (the eye, the model, a group opened, X-ray) asks again.
Skipped without the engine."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402

import views.viewport as viewport_mod  # noqa: E402
from tests.test_lazy_native_snap import (  # noqa: E402
    VIEWS, _close, _key, _set_view, _window, pytestmark)

pytestmark = pytestmark


@pytest.fixture
def win():
    w, vp = _window(lazy=True)
    try:
        yield vp
    finally:
        _close(w)


def _fresh(vp, pts, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(viewport_mod, "_OCCLUSION_MEMO", False)
        return vp._occluded_many(pts)


def _points(rng, vp, n=250):
    pts = [V(*rng.uniform((-1, -1, -1), (18, 14, 4))) for _ in range(n)]
    for g in vp.scene.groups[::3]:
        if getattr(g, "xform", None) is not None:
            pts.append(g.xform.map(V(0, 0, 0)))
            pts.append(g.xform.map(V(1, 1, 1)))
    return pts


def test_kept_answers_are_the_ones_asked_afresh(win, monkeypatch):
    vp = win
    rng = np.random.default_rng(11)
    asked = []
    real = type(vp)._occluded_many_now
    monkeypatch.setattr(type(vp), "_occluded_many_now",
                        lambda self, w: (asked.append(len(w)),
                                         real(self, w))[1])
    hidden = 0
    for view in VIEWS:
        _set_view(vp, view)
        assert vp._lazy_native() is not None
        pts = _points(rng, vp)
        want = _fresh(vp, pts, monkeypatch)
        asked.clear()
        # Overlapping batches, out of order, repeated, as arrays and not.
        order = rng.permutation(len(pts))
        for lo in range(0, len(pts), 37):
            sel = order[lo:lo + 60]
            got = vp._occluded_many([pts[i] for i in sel])
            assert got == [want[i] for i in sel], view
        arr = np.array([(p.x(), p.y(), p.z()) for p in pts])
        n = sum(asked)
        assert vp._occluded_many(arr) == want
        assert [vp._is_occluded(p) for p in pts[:30]] == want[:30]
        assert sum(asked) == n              # all of it kept
        assert n == len(pts)                # each point asked once
        hidden += sum(want)
    assert 0 < hidden < sum(len(_points(rng, vp)) for _ in VIEWS)


def test_the_corner_picked_is_the_same_with_kept_answers(win, monkeypatch):
    vp = win
    seen = 0
    for view in VIEWS[:2]:
        _set_view(vp, view)
        for x in np.arange(13.37, 900, 23.0):
            for y in np.arange(9.71, 640, 29.0):
                vp._input_serial = (x, y)
                got = vp.pick_vertex(float(x), float(y))
                with monkeypatch.context() as m:
                    m.setattr(viewport_mod, "_OCCLUSION_MEMO", False)
                    want = vp.pick_vertex(float(x), float(y))
                assert _key(got) == _key(want), (view, x, y)
                seen += got is not None
    assert seen > 50


def _changes(vp):
    sc = vp.scene
    copies = [g for g in sc.groups if getattr(g, "xform", None) is not None
              and not getattr(g, "hidden", False)]

    def hide():
        for g in copies[::2]:
            g.hidden = True
        sc.version += 1

    def move():
        for g in copies[1::2]:
            m = QMatrix4x4(g.xform)
            m.translate(0.0, 0.0, 1.7)
            g.xform = m
        sc.version += 1

    def turn():
        _set_view(vp, (75.0, 25.0, True))

    def xray():
        from core.style import Style
        vp.style_override = Style(name="x", face_mode="xray")

    def solid():
        vp.style_override = None

    def open_group():
        sc.begin_group_edit(copies[3])

    return [("hide", hide), ("move", move), ("turn", turn), ("xray", xray),
            ("solid", solid), ("open", open_group)]


def test_what_changes_a_ray_asks_again(win, monkeypatch):
    vp = win
    rng = np.random.default_rng(5)
    _set_view(vp, VIEWS[0])
    pts = _points(rng, vp, 400)
    vp._occluded_many(pts)
    flips = 0
    for name, change in _changes(vp):
        before = vp._occluded_many(pts)
        change()
        if vp._lazy_native() is None:
            continue
        want = _fresh(vp, pts, monkeypatch)
        assert vp._occluded_many(pts) == want, name
        flips += sum(a != b for a, b in zip(before, want))
    assert flips > 20
