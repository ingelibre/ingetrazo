# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pick index's span grid changes nothing but how fast a ray gets there.

A chunk of more than ``_SPAN_GRID_MIN`` triangles goes into the index as
grid cells (``_split_chunk_spans``) instead of one span, so a ray that meets
the box of a big group tests only the cells it crosses. The triangles are
reordered, never altered: same triangles, same entities, every cell's box
around its triangles, the cells tiling the range. And ``_ray_hits`` — per
entity and nearest overall — answers exactly as with one span per chunk,
for random rays through and around clustered, flat and scattered meshes.

Headless: NumPy only.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

import views.viewport as vv
from views.viewport import Viewport, _split_chunk_spans


def _chunk(rng, n, kind):
    if kind == "cluster":           # most triangles bunched in one corner
        v0 = np.where(rng.random((n, 1)) < 0.8,
                      rng.normal(0.0, 0.3, (n, 3)),
                      rng.uniform(-5, 5, (n, 3)))
    elif kind == "flat":            # a slab: thin on one axis
        v0 = rng.uniform(-5, 5, (n, 3)) * np.array([1.0, 1.0, 0.01])
    else:
        v0 = rng.uniform(-5, 5, (n, 3))
    e1 = rng.normal(0, 0.05, (n, 3))
    e2 = rng.normal(0, 0.05, (n, 3))
    te = rng.integers(0, n // 3, n)
    pts = np.concatenate([v0, v0 + e1, v0 + e2])
    bbox = (tuple(pts.min(axis=0)), tuple(pts.max(axis=0)))
    return {"v0": v0, "e1": e1, "e2": e2, "tri_ent": te, "bbox": bbox,
            "rev": 1}


def _rows(v0, e1, e2, te):
    return sorted(map(tuple, np.column_stack([v0, e1, e2, te]).round(12)))


@pytest.mark.parametrize("kind", ["uniform", "cluster", "flat"])
def test_the_grid_is_a_permutation_with_tight_cells(kind):
    rng = np.random.default_rng(3)
    ch = _chunk(rng, 30000, kind)
    v0, e1, e2, te, cells = _split_chunk_spans(ch)
    assert cells is not None and len(cells) > 1
    assert _rows(v0, e1, e2, te) == _rows(ch["v0"], ch["e1"], ch["e2"],
                                          ch["tri_ent"])
    starts = [s for _bb, s, _n in cells]
    assert starts == sorted(starts)
    assert sum(n for _bb, _s, n in cells) == len(v0)
    pos = 0
    for (lo, hi), s, n in cells:
        assert s == pos and n > 0
        pos += n
        pts = np.concatenate([v0[s:s + n], v0[s:s + n] + e1[s:s + n],
                              v0[s:s + n] + e2[s:s + n]])
        assert (pts >= np.array(lo) - 1e-12).all()
        assert (pts <= np.array(hi) + 1e-12).all()
    # The refinement bounds the cells, even where triangles cluster.
    assert max(n for _bb, _s, n in cells) <= 2 * vv._SPAN_CELL_TRIS * 1.05


def test_small_chunks_and_the_kill_switch_keep_one_span(monkeypatch):
    rng = np.random.default_rng(4)
    assert _split_chunk_spans(_chunk(rng, 5000, "uniform"))[4] is None
    monkeypatch.setattr(vv, "_NO_SPAN_GRID", True)
    assert _split_chunk_spans(_chunk(rng, 30000, "uniform"))[4] is None


def _index(chunks, grid):
    v0s, e1s, e2s, tes, spans = [], [], [], [], []
    off = 0
    for ch in chunks:
        if grid:
            v0, e1, e2, te, cells = _split_chunk_spans(dict(ch))
        else:
            v0, e1, e2, te, cells = ch["v0"], ch["e1"], ch["e2"], ch["tri_ent"], None
        v0s.append(v0)
        e1s.append(e1)
        e2s.append(e2)
        tes.append(te)
        if cells is None:
            spans.append((ch["bbox"], off, len(v0)))
        else:
            spans += [(bb, off + s, n) for bb, s, n in cells]
        off += len(v0)
    n_ent = int(max(t.max() for t in tes)) + 1
    return SimpleNamespace(
        tri_v0=np.concatenate(v0s), tri_e1=np.concatenate(e1s),
        tri_e2=np.concatenate(e2s), tri_ent=np.concatenate(tes),
        tri_spans=spans, own_spans=[], entities=[None] * n_ent)


@pytest.mark.parametrize("seed", [1, 2])
def test_ray_hits_answers_as_with_one_span_per_chunk(seed):
    rng = np.random.default_rng(seed)
    chunks = [_chunk(rng, 20000, k) for k in ("uniform", "cluster", "flat")]
    plain = _index(chunks, grid=False)
    gridded = _index(chunks, grid=True)
    assert len(gridded.tri_spans) > len(plain.tri_spans)
    mask = np.ones(len(plain.entities), bool)
    mask[::7] = False                      # some entities invisible
    stub = SimpleNamespace()
    hits = 0
    for _ in range(150):
        o = rng.uniform(-12, 12, 3)
        target = rng.normal(0, 2.0, 3)
        d = target - o
        d /= np.linalg.norm(d)
        O, D = QVector3D(*o), QVector3D(*d)
        a = Viewport._ray_hits(stub, plain, O, D, mask)
        b = Viewport._ray_hits(stub, gridded, O, D, mask)
        np.testing.assert_array_equal(a, b)
        ga = Viewport._ray_hits(stub, plain, O, D, mask, reduce_global=True)
        gb = Viewport._ray_hits(stub, gridded, O, D, mask, reduce_global=True)
        assert ga == gb
        hits += int(np.isfinite(a).any())
    assert hits > 20                       # the rays do hit things
