# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The hover's pick passes with the native engine give Python's answers,
bit for bit (Block 6 of 0.6.3): the projection of the pick index's points
to pixels, the corner under the cursor and the edge under the cursor —
over random points with every kind of special value, and at every pixel of
a few views of an open group beside a field of groups, where corners and
edges tie on purpose. The engine's half is skipped without the module."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from views import viewport as vv  # noqa: E402

_app = QApplication.instance() or QApplication([])
mod = _native.native
needs_native = pytest.mark.skipif(
    mod is None or not hasattr(mod, "project_px"),
    reason="native module not built")


def _bits(a):
    """Bitwise identity, every NaN alike."""
    a = np.asarray(a)
    if a.dtype == bool:
        return a.tobytes()
    a = np.where(np.isnan(a), np.nan, a)
    return a.tobytes()


def _points(rng, n):
    p = rng.normal(size=(n, 3)) * 10.0 ** rng.uniform(-3, 4, (n, 1))
    p[:32] = np.round(p[:32])
    specials = (np.nan, np.inf, -np.inf, 0.0, -0.0, 1e308, -1e308, 5e-324)
    for k, v in enumerate(specials):
        p[32 + k, k % 3] = v
    return p


def _mvps(rng):
    out = [rng.normal(size=(4, 4))]
    for yaw, pitch, persp in ((30.0, 35.0, True), (200.0, -20.0, True),
                              (115.0, 89.0, False)):
        from core.camera import OrbitCamera as Camera
        cam = Camera()
        cam.perspective = persp
        cam.yaw, cam.pitch = math.radians(yaw), math.radians(pitch)
        cam.target = V(1.5, -2.0, 0.5)
        cam.distance = 14.0
        m = cam.projection_matrix() * cam.view_matrix()
        out.append(np.array(m.data(), dtype=np.float64).reshape(4, 4,
                                                               order="F"))
    return out


@needs_native
def test_the_projection_is_numpys_bit_for_bit():
    rng = np.random.default_rng(1963)
    for M in _mvps(rng):
        for n in (0, 1, 7, 5000, 40000):
            p = _points(rng, max(n, 40))[:n]
            for pts in (p, p.astype(np.float32), np.asfortranarray(p)):
                with np.errstate(all="ignore"):
                    want = vv._project_px_numpy(pts, M, 900, 640)
                got = mod.project_px(np.ascontiguousarray(pts, np.float64),
                                     M.ravel().tolist(), 900.0, 640.0)
                for g, w in zip(got, want):
                    assert g.dtype == w.dtype
                    assert _bits(g) == _bits(w)


@needs_native
def test_the_projection_refuses_what_it_cannot_read():
    with pytest.raises(ValueError):
        mod.project_px(np.zeros((3, 4)), [0.0] * 16, 1.0, 1.0)
    with pytest.raises(ValueError):
        mod.project_px(np.zeros((3, 3)), [0.0] * 15, 1.0, 1.0)


def _argsort_walk(d, thr):
    """What the old loop over ``np.argsort(d)[:8]`` reads before it stops."""
    out = []
    for i in np.argsort(d)[:8]:
        if not d[int(i)] < thr:
            break
        out.append(int(i))
    return out


def _walk(order, d, thr):
    out = []
    for i in order[:8]:
        if not d[int(i)] < thr:
            break
        out.append(int(i))
    return out


def test_the_nearest_order_is_the_full_sorts():
    rng = np.random.default_rng(71)
    for trial in range(400):
        n = int(rng.integers(0, 3000))
        d = rng.uniform(0, 40, n)
        if trial % 3 == 0:
            d = np.round(d)                       # ties
        if trial % 5 == 0 and n:
            d[rng.integers(0, n, 5)] = np.nan
        if trial % 7 == 0 and n:
            d[rng.integers(0, n, 50)] = np.inf
        if trial % 11 == 0:
            d[:] = 3.0                            # every one tied
        thr = float(rng.choice([0.0, 5.0, 8.0, 50.0]))
        got = _walk(vv._nearest_order(d, thr), d, thr)
        assert got == _argsort_walk(d, thr), trial


# --- In a window ------------------------------------------------------------

def _sheet(mesh, n, at=(0.0, 0.0, 0.0), step=1.0):
    ox, oy, oz = at
    for i in range(n):
        for j in range(n):
            z = oz + 0.25 * math.sin(i * 0.7) * math.cos(j * 0.4)
            x0, y0 = ox + i * step, oy + j * step
            mesh.add_face([V(x0, y0, z), V(x0 + step, y0, z),
                           V(x0 + step, y0 + step, z), V(x0, y0 + step, z)])


def _window():
    """A field of placed sheets and an open group of ~2 000 faces: more
    loose edges than _PROJECT_NATIVE_MIN, more corners than _px_near hands
    to the engine."""
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(900, 640)
    sc = vp.scene
    sc.clear()
    proto = Mesh()
    _sheet(proto, 8, step=0.5)
    for i in range(6):
        for j in range(5):
            g = Group(proto, name=f"S{i}{j}")
            m = QMatrix4x4()
            m.translate(-30.0 + 5.0 * i, -25.0 + 5.0 * j, 0.1 * (i - j))
            m.rotate(7.0 * i + 3.0 * j, 0.0, 0.0, 1.0)
            g.xform = m
            sc.groups.append(g)
    inner = Mesh()
    _sheet(inner, 32, at=(0.0, 0.0, 1.0), step=0.5)
    for k, e in enumerate(inner.edges):
        if k % 9 == 4:
            e.soft = True               # not drawn: no visible pick
    host = Group(inner, name="Host")
    sc.groups.append(host)
    # The rest of the model's loose edges ride in the index while the group
    # is open: snappable, not selectable.
    _sheet(sc.mesh, 12, at=(-9.0, -2.0, 0.6), step=0.7)
    sc.version += 1
    vp.begin_group_edit(host)
    win._activate_tool("line")
    return win, vp


VIEWS = ((30.0, 35.0, True, 40.0), (200.0, 20.0, True, 25.0),
         (115.0, 60.0, False, 30.0), (0.0, 89.9, False, 18.0))


def _set_view(vp, view):
    yaw, pitch, persp, dist = view
    cam = vp.camera
    cam.perspective = persp
    cam.yaw, cam.pitch = math.radians(yaw), math.radians(pitch)
    cam.target = V(4.0, 4.0, 0.5)
    cam.distance = dist
    vp._tick = getattr(vp, "_tick", 0) + 1


def _key(p):
    return None if p is None else (p.x(), p.y(), p.z())


def _ekey(e):
    return None if e is None else (_key(e.a), _key(e.b))


@pytest.fixture
def pair():
    a, va = _window()
    b, vb = _window()
    try:
        yield va, vb
    finally:
        for w in (a, b):
            w._saved_version = w.viewport.scene.version
            w.close()


def _answers(vp, x, y):
    return (_key(vp.pick_vertex(x, y)),
            _ekey(vp.pick_edge(x, y)),
            _ekey(vp.pick_visible_edge(x, y)),
            _ekey(vp._pick_edge(x, y, True, "snap", True)))


def _old_answers(vp, x, y):
    return (_key(_old_pick_vertex(vp, x, y)),
            _ekey(_old_pick_edge(vp, x, y, False)),
            _ekey(_old_pick_edge(vp, x, y, True)),
            _ekey(_old_pick_edge(vp, x, y, True, "snap", True)))


def test_the_corner_and_the_edge_under_the_cursor_are_as_they_were(pair):
    """On Python, the new passes answer as the old ones at every pixel."""
    va, vb = pair
    saved = _native.native
    _native.native = None
    try:
        found = 0
        for view in VIEWS:
            _set_view(va, view)
            _set_view(vb, view)
            for x in np.arange(11.0, 900, 23.0):
                for y in np.arange(7.5, 640, 21.0):
                    x, y = float(x), float(y)
                    got = _answers(va, x, y)
                    assert got == _old_answers(vb, x, y), (view, x, y)
                    found += sum(v is not None for v in got)
        assert found > 200
    finally:
        _native.native = saved


@needs_native
def test_the_corner_and_the_edge_under_the_cursor_are_pythons(pair):
    """With the engine, the answers of the old passes on Python."""
    va, vb = pair
    idx = va._pick_index(near="skip")
    assert len(idx.edge_a) >= vv._PROJECT_NATIVE_MIN
    assert len(idx.gedge_a) > 2048
    found = [0, 0, 0, 0]
    for view in VIEWS:
        _set_view(va, view)
        _set_view(vb, view)
        for x in np.arange(11.0, 900, 23.0):
            for y in np.arange(7.5, 640, 21.0):
                x, y = float(x), float(y)
                got = _answers(va, x, y)
                saved = _native.native
                _native.native = None
                try:
                    want = _old_answers(vb, x, y)
                finally:
                    _native.native = saved
                assert got == want, (view, x, y)
                for k, v in enumerate(got):
                    found[k] += v is not None
    assert min(found) > 50, found


def test_the_shared_projection_is_the_held_indexs():
    """_pick_edge reads _ledge_screen's projection as the one of the index
    it holds: an index made again under the same key (here by hand, the
    loose edges moved under it) is projected again, not read stale."""
    win, vp = _window()
    try:
        _set_view(vp, VIEWS[2])
        idx = vp._pick_index(near="skip")
        first = vp._ledge_screen()
        assert vp._ledge_screen() is first            # kept
        mesh = vp.scene.mesh
        for v in list(mesh.vertices)[:200]:
            mesh.move_vertex(v, V(0.0, 0.0, 3.0))
        vp._pick_index_cache = None                    # same key, new index
        idx2 = vp._pick_index(near="skip")
        assert idx2.edge_a is not idx.edge_a
        lp = vp._ledge_screen()
        want = vv._project_px_numpy(idx2.edge_a, vp._np_mvp(), vp.width(),
                                    vp.height())
        assert _bits(lp[0]) == _bits(want[0])
        assert _bits(lp[1]) == _bits(want[1])
        assert not np.array_equal(lp[1], first[1])
    finally:
        win._saved_version = vp.scene.version
        win.close()


# --- The passes as they were before the engine took them (d83b83f2) ---------
# Verbatim, for the answers the new code must keep giving.
from PySide6.QtGui import QVector3D  # noqa: E402
from views.viewport import _active_cut  # noqa: E402,F401


def _old_pick_edge(self, screen_x: float, screen_y: float,
               visible_only: bool, which: str = "sel",
               with_soft: bool = False):
    """``which``: "sel" for the edges a click means, "snap" for the ones a
    reference may hold — the rest of the model's loose edges, drawn
    around an open group / component, are snappable and not selectable."""
    import numpy as np
    idx = self._pick_index(near="skip")
    if idx.edge_a is None:
        return None
    ax, ay, oka = self._project_px(idx.edge_a)
    bx, by, okb = self._project_px(idx.edge_b)
    allowed = (idx.edge_sel if which == "sel"
               else getattr(idx, "edge_snap", idx.edge_sel))
    ok = oka & okb & allowed
    soft = getattr(idx, "edge_soft", None)
    if (visible_only and not with_soft and soft is not None
            and not getattr(self.scene, "show_hidden_geometry", False)):
        ok &= ~soft
    sp = _active_cut(self.scene)
    if sp is not None:
        ok &= ~(sp.hidden(idx.edge_a) & sp.hidden(idx.edge_b))
    if not ok.any():
        return None
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    safe = np.where(l2 > 1e-12, l2, 1.0)
    t = np.clip(((screen_x - ax) * dx + (screen_y - ay) * dy) / safe,
                0.0, 1.0)
    d = np.hypot(ax + t * dx - screen_x, ay + t * dy - screen_y)
    d = np.where(ok, d, np.inf)
    if not visible_only:
        i = int(np.argmin(d))
        return idx.edges[i] if d[i] < self.pick_threshold_px else None
    # Nearest first, skipping the ones hidden behind the model; a few
    # tries are plenty (the threshold holds only a handful).
    for i in np.argsort(d)[:8]:
        i = int(i)
        if not d[i] < self.pick_threshold_px:
            return None
        e = idx.edges[i]
        p = self.edge_point_under_cursor(e, screen_x, screen_y)
        if p is None or not self._is_occluded(p):
            return e
    return None


def _old_pick_vertex(self, screen_x: float, screen_y: float):
    """Return the scene vertex (corner) closest to the cursor within the
    pick threshold, or ``None``. Used to acquire a corner as a 'from point'
    reference while drawing. Occluded vertices are ignored (tested in
    ascending screen distance, so the nearest visible corner wins — the
    same answer the old per-edge scan produced)."""
    import numpy as np
    nat = (self._lazy_native() if hasattr(self, "_lazy_native")
           else None)
    if nat is not None:
        return self._pick_vertex_unbaked(screen_x, screen_y, nat)
    idx = self._pick_index(near=("px", screen_x, screen_y))
    # On the projections the viewport already caches per camera pose
    # (this runs on EVERY hover now — encouraged points): one numpy
    # distance pass, no re-projection of the model per mouse move.
    xs, ys, oks = [], [], []
    n = 0
    ledge = getattr(self, "_ledge_screen", None)      # stub VPs in tests
    lp = ledge() if ledge is not None else None
    if lp is None and idx.edge_a is not None and len(idx.edge_a):
        ax, ay, oka = self._project_px(idx.edge_a)
        bx, by, okb = self._project_px(idx.edge_b)
        lp = (ax, ay, bx, by, oka & okb)
    if lp is not None:
        ax, ay, bx, by, ok = lp
        xs += [ax, bx]; ys += [ay, by]; oks += [ok, ok]
        n = len(idx.edges)
    m = 0
    gp = self._gedge_screen()
    if gp is not None:
        # Group corners too — dimensioning/drawing over an imported
        # reference model needs its vertices as 'from points'.
        ax, ay, bx, by, ok = gp
        xs += [ax, bx]; ys += [ay, by]; oks += [ok, ok]
        m = len(idx.gedge_a)
    if not xs:
        return None
    # The concatenation is the same until the scene or camera moves.
    ckey = (id(lp), id(gp), n, m)
    cat = getattr(self, "_vertex_px_cache", None)
    if cat is None or cat[0] != ckey:
        cat = (ckey, np.concatenate(xs), np.concatenate(ys), np.concatenate(oks))
        self._vertex_px_cache = cat
    _c, px, py, ok = cat
    d = np.where(ok, np.hypot(px - screen_x, py - screen_y), np.inf)
    cand = np.where(d < self.pick_threshold_px)[0]

    def vertex_of(i):
        if i < 2 * n:
            e = idx.edges[int(i) % n]
            return e.a if i < n else e.b
        j = int(i) - 2 * n
        arr = idx.gedge_a if j < m else idx.gedge_b
        p = arr[j % m]
        return QVector3D(p[0], p[1], p[2])
    order = cand[np.argsort(d[cand])]
    if not len(order):
        return None
    # A corner only an edge that draws nothing holds is not on screen:
    # acquiring it as a from-point is how a phantom point gets into the
    # next face (the same rule the snap scene applies to the edges).
    snap_ok = None if n == 0 else getattr(idx, "edge_snap", None)
    if snap_ok is not None:
        order = np.asarray([i for i in order
                            if i >= 2 * n or snap_ok[int(i) % n]],
                           dtype=order.dtype)
        if not len(order):
            return None
    # The nearest one, alone first (usually the answer); then the
    # rest in batches of 8, 16, 32… sharing one occlusion pass, as the
    # snap engine reads its candidates. One ray per candidate, in turn,
    # took minutes a pointer move over a dense mesh whose hundreds of
    # nearby corners were nearly all hidden (a 128 788-face STL in #158).
    # A corner shared by several edges comes once per end: asked once
    # (the same point, the same answer), in batches of at most 1 024 —
    # zoomed out over the plant of #158 some 65 000 hidden corners lay
    # under the cursor, and a batch of 32 768 rays built ~1.4 GB of box
    # tests and took 7 s.
    first = vertex_of(order[0])
    if not self._is_occluded(first):
        return first
    if len(order) > 1:
        # Each point once, where it first comes (the nearest of its
        # copies on screen): the same answer as asking every copy.
        xyz = np.empty((len(order), 3))
        for lo_i, hi_i, arr, base in (
                (0, n, idx.edge_a, 0), (n, 2 * n, idx.edge_b, n),
                (2 * n, 2 * n + m, idx.gedge_a, 2 * n),
                (2 * n + m, 2 * n + 2 * m, idx.gedge_b, 2 * n + m)):
            w = np.flatnonzero((order >= lo_i) & (order < hi_i))
            if len(w):
                xyz[w] = arr[order[w] - base]
        _u, at = np.unique(xyz, axis=0, return_index=True)
        at.sort()
        order = order[at]
    many = getattr(self, "_occluded_many", None)
    k, size = 1, 8
    while k < len(order):
        batch = [vertex_of(i) for i in order[k:k + size]]
        hidden = (many(batch) if many is not None
                  else [self._is_occluded(v) for v in batch])
        for v, h in zip(batch, hidden):
            if not h:
                return v
        k += size
        size = min(size * 2, 1024)
    return None
