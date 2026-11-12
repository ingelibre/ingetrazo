"""Push/Pull's corner inference over a pile of vertices (#1092): the prototypes
of a big model pile up at their local origin, over a million vertices within
the radius, and every move read them all. The nearest one that counts is the
same answer without reading the rest."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.topology import _key  # noqa: E402
from tools.pushpull import PushPullTool  # noqa: E402
from types import SimpleNamespace  # noqa: E402


class _Counted:
    """A vertex list that counts what is read of it."""

    def __init__(self, pts):
        self.pts = pts
        self.read = 0

    def __len__(self):
        return len(self.pts)

    def __getitem__(self, i):
        self.read += 1
        x, y, z = self.pts[int(i)]
        return SimpleNamespace(position=V(float(x), float(y), float(z)))


class _Vp:
    """A pixel per unit, looking down Z. The scene is empty: the entries of
    the tool's cache are the test's."""

    snap_threshold_px = 9.0
    scene = SimpleNamespace(mesh=SimpleNamespace(vertices=[]), groups=[],
                            guides=[])
    _hover_edge = None
    mvp_calls = 0

    def __init__(self, hidden=()):
        self.hidden = set(hidden)
        self.asked = 0
        self.projected = 0
        self.eye = 1.0

    def width(self):
        return 1000

    def height(self):
        return 1000

    def _np_mvp(self):
        return np.eye(4) * self.eye

    def _project_px(self, pts):
        self.projected += 1
        return (pts[:, 0] * self.eye, pts[:, 1] * self.eye,
                np.ones(len(pts), bool))

    def _world_to_pixel(self, p):
        return (p.x() * self.eye, p.y() * self.eye)

    def pick_face_any(self, *a, **k):
        return None, None

    def _is_occluded(self, world):
        self.asked += 1
        return _key(world) in self.hidden


def _tool(cache, cap=()):
    t = PushPullTool()
    t._infer_cache = cache
    t._anchor = V(0, 0, 0)
    t._normal = V(0, 0, 1)
    t._cap_positions = list(cap)
    t._infer_edge_midpoint = lambda *a: None
    t._infer_guide_line = lambda *a: None
    return t


def _ctx(vp, x, y):
    return SimpleNamespace(viewport=vp, screen=QPointF(x, y), hit=None,
                           ctrl=False)


def _brute(cache, vp, sx, sy, exclude):
    """What the scan answered reading every candidate."""
    best = None
    for verts, arr in cache:
        px, py, ok = vp._project_px(arr)
        d2 = (px - sx) ** 2 + (py - sy) ** 2
        for i in np.flatnonzero(ok & (d2 <= 81.0)):
            p = verts[int(i)].position
            if _key(p) in exclude:
                continue
            if (best is None or float(d2[i]) < best[0]) \
                    and not vp._is_occluded(p):
                best = (float(d2[i]), p)
    return best


def _pile(n, seed, at=(100.0, 100.0)):
    r = np.random.default_rng(seed)
    pts = np.zeros((n, 3))
    pts[:, 0] = at[0] + r.integers(-12, 13, n)
    pts[:, 1] = at[1] + r.integers(-12, 13, n)
    pts[:, 2] = r.integers(0, 5, n)
    return _Counted(pts), pts


def test_only_the_winner_is_read():
    verts, arr = _pile(5000, 1)
    vp = _Vp()
    t = _tool([(verts, arr)])
    assert t._infer_reference_distance(_ctx(vp, 100.2, 100.3)) is not None
    assert t._inference_kind == "vertex"
    assert verts.read <= 2
    assert vp.asked == 1


def test_same_answer_as_reading_them_all():
    rnd = random.Random(7)
    for seed in range(60):
        cache = [_pile(300, seed * 10 + k, (100.0 + 6 * k, 100.0))
                 for k in range(3)]
        cap = [tuple(map(float, cache[0][1][j])) for j in range(5)]
        hidden = {_key(V(*map(float, cache[k][1][j])))
                  for k in range(3) for j in range(0, 300, 2)}
        vp = _Vp(hidden)
        t = _tool(cache, [V(*c) for c in cap])
        for _ in range(5):
            sx, sy = rnd.uniform(90, 125), rnd.uniform(88, 112)
            exclude = {_key(V(*c)) for c in cap}
            want = _brute(cache, vp, sx, sy, exclude)
            t._inference_point = None
            got = t._infer_reference_distance(_ctx(vp, sx, sy))
            if want is None:
                assert t._inference_kind != "vertex" or got is None
            else:
                assert t._inference_kind == "vertex"
                assert _key(t._inference_point) == _key(want[1])
                assert abs(got - want[1].z()) < 1e-9


def test_a_prototype_far_from_the_cursor_is_projected_once():
    near, near_a = _pile(50, 1)
    far, far_a = _pile(50, 2, (800.0, 800.0))
    vp = _Vp()
    t = _tool([(near, near_a), (far, far_a)])
    t._infer_reference_distance(_ctx(vp, 100.0, 100.0))
    assert vp.projected == 2
    for k in range(5):
        t._infer_reference_distance(_ctx(vp, 100.0 + k, 100.0))
    assert vp.projected == 2 + 5


def test_a_camera_move_forgets_the_boxes():
    far, far_a = _pile(50, 2, (800.0, 800.0))
    vp = _Vp()
    t = _tool([(far, far_a)])
    assert t._infer_reference_distance(_ctx(vp, 400.0, 400.0)) is None
    vp.eye = 0.5                       # the same vertices now under the cursor
    assert t._infer_reference_distance(_ctx(vp, 400.0, 400.0)) is not None
    assert t._inference_kind == "vertex"


class _VpFirstClear(_Vp):
    """A viewport whose engine answers for an ordered list in one call, and
    says nothing under a section cut."""

    def __init__(self, hidden=(), silent=False):
        super().__init__(hidden)
        self.silent = silent
        self.batches = 0

    def _first_clear(self, pts):
        if self.silent:
            return None
        self.batches += 1
        for j, p in enumerate(pts):
            if _key(V(*map(float, p))) not in self.hidden:
                return j
        return -1


def test_the_hidden_ones_go_to_the_engine_in_one_call():
    verts, arr = _pile(2000, 3)
    # All hidden but the farthest few: thousands of single questions before.
    d2 = (arr[:, 0] - 100.0) ** 2 + (arr[:, 1] - 100.0) ** 2
    keep = {_key(V(*map(float, arr[j]))) for j in np.flatnonzero(d2 <= 81.0)
            if d2[j] >= 72.0}
    hidden = {_key(V(*map(float, p))) for p in arr} - keep
    vp = _VpFirstClear(hidden)
    t = _tool([(verts, arr)])
    assert t._infer_reference_distance(_ctx(vp, 100.0, 100.0)) is not None
    assert _key(t._inference_point) in keep
    assert vp.asked == 0
    assert vp.batches == 1
    assert verts.read <= 2


def test_the_engine_answers_as_the_questions_did():
    rnd = random.Random(11)
    for seed in range(40):
        cache = [_pile(300, seed * 10 + k, (100.0 + 6 * k, 100.0))
                 for k in range(3)]
        cap = [V(*map(float, cache[0][1][j])) for j in range(5)]
        hidden = {_key(V(*map(float, cache[k][1][j])))
                  for k in range(3) for j in range(0, 300, 2)}
        a, b = _VpFirstClear(hidden), _VpFirstClear(hidden, silent=True)
        ta, tb = _tool(cache, cap), _tool(cache, cap)
        for _ in range(4):
            sx, sy = rnd.uniform(90, 125), rnd.uniform(88, 112)
            ta._inference_point = tb._inference_point = None
            got_a = ta._infer_reference_distance(_ctx(a, sx, sy))
            got_b = tb._infer_reference_distance(_ctx(b, sx, sy))
            assert got_a == got_b
            if got_a is not None:
                assert ta._inference_point == tb._inference_point
