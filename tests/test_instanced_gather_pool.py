# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The instanced pass's batches (Viewport._gather_instanced), worked out
from the placement pool's codes and matrix rows, are the ones the
per-placement walk made: the same pools in the same order (by their first
placement), the same placements in each, mirrored and painted copies
apart, and matrix rows that are the placements' own. A frame that keeps
the same placements in view hands back the very same batches."""
from __future__ import annotations

import random

import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, effective_material
from core.mesh import Mesh
from views.viewport import _material_sig


def _proto(k):
    m = Mesh()
    s = 1.0 + 0.1 * k
    m.add_face([V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0)])
    return m


def _scene(win, rng):
    protos = [_proto(k) for k in range(6)]
    for i in range(80):
        g = Group(rng.choice(protos), name=f"P{i}")
        x = QMatrix4x4()
        x.translate(rng.uniform(-20, 20), rng.uniform(-20, 20), 0)
        if rng.random() < 0.3:
            x.scale(-1, 1, 1)                    # mirrored copy
        g.xform = x
        if rng.random() < 0.2:
            g.material = {"color": [0.9, 0.2, 0.1]}
        win.viewport.scene.groups.append(g)
    win.viewport.scene.version += 1


def _reference(vp, planes=None):
    """The per-placement walk the pool replaced, culled by ``planes``."""
    out: dict = {}
    for g in vp._placements():
        if not vp.scene.entity_visible(g) or not vp._instanced_eligible(g):
            continue
        if planes is not None:
            lo, hi = vp._placement_bbox(g)
            if not all(sum(n * (h if n >= 0 else l)
                           for n, l, h in zip(pl[:3], lo, hi)) + pl[3] >= 0
                       for pl in planes):
                continue
        paint = effective_material(g)
        mirrored = g.xform.determinant() < 0.0
        out.setdefault((id(g.mesh), _material_sig(paint), mirrored),
                       (g.mesh, paint, [], mirrored))[2].append(g)
    return out


def test_batches_are_the_walks():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        for seed, planes in ((0, None), (1, None), (2, [(1.0, 0.0, 0.0, 0.0)]),
                             (3, [(-1.0, 0.0, 0.0, 2.0),
                                  (0.0, 1.0, 0.0, 5.0)])):
            vp.scene.groups.clear()
            _scene(win, random.Random(seed))
            vp._frame_planes = planes
            got = vp._gather_instanced()
            want = _reference(vp, planes)
            assert 0 < sum(len(v[2]) for v in want.values()) < 80 \
                or planes is None
            assert list(got) == list(want)
            for key, (mesh, paint, batch, mirrored) in got.items():
                wm, _wp, wgroups, wmir = want[key]
                assert mesh is wm and mirrored == wmir
                assert list(batch) == wgroups
                rows = batch.mats[batch.idx]
                assert rows.tolist() == np.array(
                    [g.xform.data() for g in wgroups],
                    dtype=np.float32).tolist()
            assert vp._gather_instanced() is got     # same view, same batches
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_cull_is_the_array_formula():
    """The per-plane cull of _gather_instanced keeps exactly what the
    (planes, boxes, 3) formula it replaced kept — infinite boxes against
    planes with a zero component (inf·0) included."""
    rng = np.random.default_rng(2)
    lo = rng.uniform(-50, 50, size=(500, 3))
    hi = lo + rng.uniform(0, 9, size=(500, 3))
    lo[:20], hi[:20] = -np.inf, np.inf            # boxless placements
    for _ in range(40):
        pl = rng.uniform(-1, 1, size=(6, 4))
        pl[rng.integers(0, 6), rng.integers(0, 3)] = 0.0
        pl[:, 3] *= 30
        n = pl[:, :3]
        pick = np.where(n[:, None, :] >= 0.0, hi[None, :, :], lo[None, :, :])
        want = ((pick * n[:, None, :]).sum(axis=2)
                + pl[:, 3][:, None] >= 0.0).all(axis=0)
        got = np.ones(len(lo), dtype=bool)
        for row in pl.tolist():
            nx, ny, nz, d = row
            px = hi[:, 0] if nx >= 0.0 else lo[:, 0]
            py = hi[:, 1] if ny >= 0.0 else lo[:, 1]
            pz = hi[:, 2] if nz >= 0.0 else lo[:, 2]
            got &= ((px * nx + py * ny) + pz * nz) + d >= 0.0
        assert np.array_equal(got, want)
