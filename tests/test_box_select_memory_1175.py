# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""#1175: box selection must not duplicate an import's full point arrays."""
from types import SimpleNamespace
import gc
import tracemalloc
import weakref

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D

from tools.select import _box_group_fast, _local_bounds, _seg_rect_overlap


def _chunk(v0=(), e1=(), e2=(), edges=(), uid=1, dtype=np.float64):
    return dict(v0=np.asarray(v0, dtype=dtype).reshape(-1, 3),
                e1=np.asarray(e1, dtype=dtype).reshape(-1, 3),
                e2=np.asarray(e2, dtype=dtype).reshape(-1, 3),
                edges=np.asarray(edges, dtype=np.float32).reshape(-1, 3).tobytes(), uid=uid)


class _Viewport:
    def __init__(self, chunks, transforms=None, perspective=False):
        self.places = [SimpleNamespace(mesh=object(), xform=xf, material=None, billboard=False)
                       for xf in (transforms or [None] * len(chunks))]
        self.chunks = {id(g.mesh): ch for g, ch in zip(self.places, chunks)}
        self.perspective = perspective
        self.projected = 0

    def _group_chunk(self, group):
        return self.chunks[id(group.mesh)]

    def _expand_placements(self, _group):
        return self.places

    def _project_px(self, points):
        self.projected += len(points)
        ok = points[:, 2] > 0 if self.perspective else np.ones(len(points), dtype=bool)
        w = np.where(ok, points[:, 2], 1) if self.perspective else 1
        return points[:, 0] / w, points[:, 1] / w, ok


def _scalar_verdict(viewport, rect, crossing):
    """Per-point/per-edge oracle, independent of chunking and bounds shortcuts."""
    vertices, edges = [], []
    for group in viewport.places:
        chunk = viewport.chunks[id(group.mesh)]

        def project(p):
            if group.xform is not None:
                p = group.xform.map(QVector3D(*p))
                p = (p.x(), p.y(), p.z())
            if viewport.perspective:
                if p[2] <= 0:
                    return None
                return p[0] / p[2], p[1] / p[2]
            return p[0], p[1]

        for tri in zip(chunk['v0'], chunk['e1'], chunk['e2']):
            a, b, c = tri
            vertices.extend(project(p) for p in (a, a + b, a + c))
        pairs = np.frombuffer(chunk['edges'], np.float32).reshape(-1, 2, 3)
        for a, b in pairs:
            pa, pb = project(a), project(b)
            vertices.extend((pa, pb))
            edges.append((pa, pb))
    if not vertices:
        return None

    def inside(p):
        return p is not None and rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]

    if not crossing:
        return all(inside(p) for p in vertices)
    return any(inside(p) for p in vertices) or any(
        a is not None and b is not None and _seg_rect_overlap(a, b, rect)
        for a, b in edges)


@pytest.mark.parametrize('crossing', [False, True])
@pytest.mark.parametrize('perspective', [False, True])
@pytest.mark.parametrize('placed', [False, True])
@pytest.mark.parametrize('dtype', [np.float32, np.float64])
def test_chunked_selection_matches_scalar_geometry(crossing, perspective, placed, dtype):
    rng = np.random.default_rng(1175)
    for _ in range(12):
        chunks, transforms = [], []
        for _ in range(3):
            a = rng.uniform(-5, 5, (23, 3))
            b, c = rng.uniform(-1, 1, (2, 23, 3))
            chunks.append(_chunk(a, b, c, rng.uniform(-6, 6, (17 * 2, 3)), dtype=dtype))
            xf = None
            if placed:
                xf = QMatrix4x4()
                xf.translate(2, -1, 0.4)
                xf.rotate(31, 0, 0, 1)
                xf.scale(-0.7, 1.3, 0.8)
            transforms.append(xf)
        vp = _Viewport(chunks, transforms, perspective)
        for rect in [(-1, -1, 1, 1), (10, 10, 12, 12), (-20, -20, 20, 20)]:
            assert _box_group_fast(vp, vp.places[0], rect, crossing) == _scalar_verdict(
                vp, rect, crossing)


def _large_chunk(n=200_000):
    v0 = np.zeros((n, 3))
    v0[:, 0], v0[:, 1] = np.arange(n) % 1000, np.arange(n) // 1000
    e1, e2 = np.tile([1., 0., 0.], (n, 1)), np.tile([0., 1., 0.], (n, 1))
    edges = np.empty((n * 2, 3), dtype=np.float32)
    edges[0::2], edges[1::2] = v0, v0 + e2
    return _chunk(v0, e1, e2, edges)


def _peak_bytes(fn):
    # Input geometry is allocated before tracing. The budget measures scratch
    # storage for selection, not the mesh's own persistent arrays.
    tracemalloc.start()
    try:
        result = fn()
        _current, peak = tracemalloc.get_traced_memory()
        return result, peak
    finally:
        tracemalloc.stop()


def test_large_bounds_use_bounded_scratch_memory():
    chunk = _large_chunk()
    bounds, peak = _peak_bytes(lambda: _local_bounds(chunk))
    np.testing.assert_array_equal(bounds[0], [0, 0, 0])
    np.testing.assert_array_equal(bounds[1], [1000, 200, 0])
    assert peak < 8 * 1024**2, f'bounds allocated {peak / 1024**2:.1f} MiB of scratch'


@pytest.mark.parametrize('placed', [False, True])
def test_large_crossing_miss_uses_bounded_scratch_memory(placed):
    xf = None
    if placed:
        xf = QMatrix4x4()
        xf.translate(7, -3, 0)
    vp = _Viewport([_large_chunk()], [xf])
    rect = (407.8, 97.8, 407.9, 97.9) if placed else (400.8, 100.8, 400.9, 100.9)
    result, peak = _peak_bytes(lambda: _box_group_fast(vp, vp.places[0], rect, True))
    assert result is False
    assert peak < 8 * 1024**2, f'selection allocated {peak / 1024**2:.1f} MiB of scratch'


@pytest.mark.parametrize('crossing,expected', [(True, True), (False, False)])
def test_partial_box_stops_projecting_after_a_decisive_batch(crossing, expected):
    vp = _Viewport([_large_chunk()])
    result = _box_group_fast(vp, vp.places[0], (-1, -1, 10, 10), crossing)
    assert result is expected
    assert vp.projected < 25_000, f'projected {vp.projected} points after a decisive result'


@pytest.mark.parametrize('field', ['v0', 'e1', 'e2', 'edges'])
def test_bounds_cache_tracks_all_geometry_arrays(field):
    chunk = _chunk([[0, 0, 0]], [[1, 0, 0]], [[0, 1, 0]], [[0, 0, 0], [0, 1, 0]])
    _local_bounds(chunk)
    if field == 'edges':
        chunk[field] = np.array([[0, 0, 0], [9, 9, 9]], np.float32).tobytes()
    else:
        chunk[field] = chunk[field] + 9
    bounds = _local_bounds(chunk)
    all_points = np.concatenate([chunk['v0'], chunk['v0'] + chunk['e1'],
                                 chunk['v0'] + chunk['e2'],
                                 np.frombuffer(chunk['edges'], np.float32).reshape(-1, 3)])
    np.testing.assert_array_equal(bounds[0], all_points.min(axis=0))
    np.testing.assert_array_equal(bounds[1], all_points.max(axis=0))


def test_a_crossing_edge_late_in_a_large_wire_is_found():
    pairs = np.tile([[20., 20., 0.], [21., 21., 0.]], (8193, 1))
    pairs[-2:] = [[-10, 0.5, 0], [10, 0.5, 0]]
    vp = _Viewport([_chunk(edges=pairs)])
    assert _box_group_fast(vp, vp.places[0], (0, 0, 1, 1), True) is True


@pytest.mark.parametrize('field', ['v0', 'e1', 'e2'])
def test_bounds_cache_does_not_keep_replaced_triangle_arrays_alive(field):
    chunk = _chunk([[0, 0, 0]], [[1, 0, 0]], [[0, 1, 0]])
    _local_bounds(chunk)
    previous = weakref.ref(chunk[field])
    chunk[field] = chunk[field].copy()
    gc.collect()
    assert previous() is None


def test_clearing_triangle_arrays_drops_the_cached_bounds():
    chunk = _chunk([[0, 0, 0]], [[1, 0, 0]], [[0, 1, 0]])
    assert _local_bounds(chunk) is not None
    chunk['v0'] = chunk['e1'] = chunk['e2'] = None
    gc.collect()
    assert _local_bounds(chunk) is None


@pytest.mark.parametrize('cache', ['none', 'valid', 'stale'])
def test_placed_edges_keep_the_renderers_float32_rounding(cache):
    from views.viewport import _placed_maps
    chunk = _chunk([[-2, -1, 0]], [[4, 0, 0]], [[0, 2, 0]],
                   [[-1, 0.1, 0], [1, 0.1, 0]])
    xf = QMatrix4x4()
    xf.translate(0, 10000.123, 0)
    vp = _Viewport([chunk], [xf])
    group = vp.places[0]
    _linear, tv, tp = _placed_maps(xf)
    if cache != 'none':
        edges = np.frombuffer(chunk['edges'], np.float32).reshape(-1, 3)
        world = dict(v0=tp(chunk['v0']), e1=tv(chunk['e1']), e2=tv(chunk['e2']),
                     edges=tp(edges.astype(np.float64)).astype(np.float32).tobytes(),
                     ikey=(chunk['uid'] if cache == 'valid' else -1, tuple(xf.data())))
        if cache == 'stale':
            world['edges'] = (edges + 1000).astype(np.float32).tobytes()
        vp._inst_chunks = {id(group): world}
    for field in ('v0', 'e1', 'e2'):
        chunk[field].flags.writeable = False
    # The world edge rounds to y=10000.22265625 in the renderer. A double
    # transform without that rounding would miss this thin rectangle.
    assert _box_group_fast(vp, group, (-0.5, 10000.2225, 0.5, 10000.2228), True) is True


def test_empty_and_unavailable_chunks_keep_the_fallback():
    vp = _Viewport([_chunk()])
    assert _box_group_fast(vp, vp.places[0], (0, 0, 1, 1), True) is None
    def unavailable(_group):
        raise ValueError('unavailable')
    vp._group_chunk = unavailable
    assert _box_group_fast(vp, vp.places[0], (0, 0, 1, 1), True) is None
