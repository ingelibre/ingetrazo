# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Move updates the placement passes row by row (#158, «sin lag»).

Picking an object up (the preview) and putting it down (one matrix) made
every per-placement pass start over: on the plant of #158 each was ~1 s.
The placements epoch now remembers what it was made of, so a pass can ask
whether only matrices moved since it was built — and then bring just those
rows up to date. Every answer here is compared with a pass made afresh."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _prisma(n=12, r=1.0, h=2.0):
    """A smooth n-sided prism: soft vertical edges, a curved side."""
    from core.mesh import Mesh
    m = Mesh()
    ring = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
            for i in range(n)]
    for i in range(n):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % n]
        m.add_face([V(x0, y0, 0), V(x1, y1, 0), V(x1, y1, h), V(x0, y0, h)])
    for e in m.edges:
        if abs(e.a.z() - e.b.z()) > 1e-9:
            e.soft = True
    return m


def _scene():
    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    protos = [_prisma(12), _prisma(7, r=0.5, h=3.0)]
    gs = []
    for k in range(10):
        m = QMatrix4x4()
        m.translate(2.5 * k, (k % 3) * 1.7, 0.2 * k)
        m.rotate(23.0 * k, 0.1 * (k % 2), 0.3, 1.0)
        g = Group(protos[k % 2], name=f"P{k}")
        g.xform = m
        vp.scene.groups.append(g)
        gs.append(g)
    vp.scene.version += 1
    return win, vp, gs


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _rows(raw):
    a = np.frombuffer(raw, np.float32).reshape(-1, 6)
    return sorted(map(tuple, np.round(a, 3)))


def _fresh(vp, gs, eye, skip=()):
    return b"".join(vp._instance_silhouette(g, eye, None) for g in gs
                    if id(g) not in skip)


def test_moving_one_placement_updates_its_rows_only():
    win, vp, gs = _scene()
    try:
        eye = V(20, -15, 8)
        vp._instanced_silhouettes(gs, eye, None)
        table = vp._sil_table[1]
        old = vp._placements_epoch()
        m = QMatrix4x4(gs[3].xform)
        m.translate(0.0, 4.0, 1.0)
        m.rotate(40.0, 0.0, 0.0, 1.0)
        gs[3].xform = m
        vp.scene.version += 1
        assert vp._placements_epoch() != old
        assert vp._epoch_only_matrices(old)
        got, rest = vp._instanced_silhouettes(gs, eye, None)
        assert vp._sil_table[1] is table                 # kept, rows moved
        assert rest == [] and _rows(got) == _rows(_fresh(vp, gs, eye))
    finally:
        _close(win)


def test_a_previewed_placement_is_left_out_without_a_new_table():
    win, vp, gs = _scene()
    try:
        eye = V(-6, 9, 3)
        vp._instanced_silhouettes(gs, eye, None)
        table = vp._sil_table[1]
        skip = {id(gs[2]), id(gs[5])}
        got, _ = vp._instanced_silhouettes(gs, eye, None, skip=skip)
        assert vp._sil_table[1] is table
        assert _rows(got) == _rows(_fresh(vp, gs, eye, skip))
    finally:
        _close(win)


def test_an_edit_of_a_mesh_is_not_only_matrices():
    win, vp, gs = _scene()
    try:
        eye = V(4, 1, 30)
        vp._instanced_silhouettes(gs, eye, None)
        table = vp._sil_table[1]
        old = vp._placements_epoch()
        gs[0].mesh.add_face([V(0, 0, 5), V(1, 0, 5), V(1, 1, 5)])
        vp.scene.version += 1
        assert not vp._epoch_only_matrices(old)
        got, _ = vp._instanced_silhouettes(gs, eye, None)
        assert vp._sil_table[1] is not table             # made again
        assert _rows(got) == _rows(_fresh(vp, gs, eye))
    finally:
        _close(win)


def test_a_new_layer_state_is_not_only_matrices():
    win, vp, gs = _scene()
    try:
        old = vp._placements_epoch()
        gs[4].hidden = True
        vp.scene.version += 1
        assert not vp._epoch_only_matrices(old)
    finally:
        _close(win)


def _look(vp):
    cam = vp.camera
    cam.perspective = True
    cam.target = V(12, 2, 1)
    cam.distance, cam.yaw, cam.pitch = 40.0, 0.3, 0.4
    vp._frame_planes = vp._frustum_planes(
        cam.projection_matrix() * cam.view_matrix())


def _batches(vp):
    """{id(placement): its matrix} of what the instanced pass draws."""
    out = {}
    for _m, _p, batch, _mir in vp._gather_instanced().values():
        for i, g in zip(batch.idx.tolist(), batch):
            out[id(g)] = tuple(np.round(batch.mats[i], 5))
    return out


def _fresh_batches(vp):
    keep = (vp._inst_pool, vp._inst_frame_memo)
    vp._inst_pool, vp._inst_frame_memo = None, {}
    try:
        return _batches(vp)
    finally:
        vp._inst_pool, vp._inst_frame_memo = keep


def test_the_instanced_pool_moves_one_row():
    win, vp, gs = _scene()
    try:
        _look(vp)
        before = _batches(vp)
        pool = vp._inst_pool
        m = QMatrix4x4(gs[6].xform)
        m.translate(1.0, -2.0, 0.5)
        gs[6].xform = m
        vp.scene.version += 1
        after = _batches(vp)
        assert vp._inst_pool[1] is pool[1]                # kept, row moved
        assert after == _fresh_batches(vp)
        assert after[id(gs[6])] != before[id(gs[6])]
    finally:
        _close(win)


def test_a_picked_up_placement_leaves_the_batches_and_comes_back():
    win, vp, gs = _scene()
    try:
        _look(vp)
        everything = set(_batches(vp))
        assert id(gs[1]) in everything
        pool = vp._inst_pool
        # what begin_groups_preview does to the caches (it uploads too)
        vp._frozen_cache_version = vp.scene.version
        vp._preview_groups = {id(gs[1])}
        vp._preview_epoch = getattr(vp, "_preview_epoch", 0) + 1
        vp._tick = getattr(vp, "_tick", 0) + 1            # a new frame
        assert set(_batches(vp)) == everything - {id(gs[1])}
        assert vp._inst_pool[1] is pool[1]                 # the same pool
        vp._frozen_cache_version = None
        vp._preview_groups = set()
        vp._preview_epoch += 1
        vp._tick += 1
        assert set(_batches(vp)) == everything
    finally:
        _close(win)


def test_a_turn_into_a_mirror_image_makes_a_new_pool():
    win, vp, gs = _scene()
    try:
        _look(vp)
        _batches(vp)
        pool = vp._inst_pool
        m = QMatrix4x4(gs[2].xform)
        m.scale(-1.0, 1.0, 1.0)
        gs[2].xform = m
        vp.scene.version += 1
        assert _batches(vp) == _fresh_batches(vp)
        assert vp._inst_pool[1] is not pool[1]
    finally:
        _close(win)


def test_moving_a_plain_group_is_only_matrices_unless_its_mesh_is_a_prototype():
    from core.group import Group
    win, vp, gs = _scene()
    try:
        plain = Group(_prisma(5), name="plain")             # no matrix
        vp.scene.groups.append(plain)
        vp.scene.version += 1
        old = vp._placements_epoch()
        plain.mesh.add_face([V(0, 0, 9), V(1, 0, 9), V(1, 1, 9)])   # edited
        vp.scene.version += 1
        assert vp._epoch_only_matrices(old)
        # the same mesh drawn by a placement too: its edit is not a move
        shared = Group(gs[0].mesh, name="shared")
        vp.scene.groups.append(shared)
        vp.scene.version += 1
        old = vp._placements_epoch()
        shared.mesh.add_face([V(0, 0, 7), V(1, 0, 7), V(1, 1, 7)])
        vp.scene.version += 1
        assert not vp._epoch_only_matrices(old)
    finally:
        _close(win)
