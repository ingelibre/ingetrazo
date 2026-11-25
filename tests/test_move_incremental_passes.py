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


def test_dense_parent_move_and_undo_match_fresh_pool_and_frames(monkeypatch):
    from PySide6.QtGui import QVector4D
    from core import _native
    from core.group import Group
    from core.history import MoveGroupCommand
    from views.viewport import Viewport

    vp = Viewport()
    try:
        prototypes = (_prisma(5), _prisma(7, h=1.5))
        siblings = []
        for i in range(96):
            group = Group(prototypes[i % 2])
            group.xform = QMatrix4x4()
            group.xform.translate((i % 12) * 1.5, (i // 12) * 1.25, (i % 7) * .2)
            group.xform.rotate(i * 11., .25, .5, 1.)
            if i % 3 == 0:
                group.xform.scale(-1., 1., 1.)
            if i == 5:
                group.xform.setRow(3, QVector4D(.01, 0., 0., 1.))
            if i % 4 == 0:
                group.material = {"color": (.2, .4, .7), "opacity": 1.}
            siblings.append(group)
        middle, parent = Group(prototypes[0]), Group(prototypes[1])
        middle.adopt(siblings)
        middle.xform.rotate(19., 0., 1., 0.)
        parent.adopt([middle])
        parent.xform.rotate(-17., 0., 0., 1.)
        fixed = Group(prototypes[0])
        fixed.xform = QMatrix4x4()
        vp.scene.groups[:] = [parent, fixed]
        vp.scene.version += 1
        assert vp._gather_instanced()
        old = vp._inst_pool
        assert len(old[1]) == len(siblings) + 3
        assert {mirrored for _, _, mirrored in old[5]} == {False, True}

        kernel = _native.qt_world_boxes()
        masks = []
        if kernel is not None:
            def record_boxes(bounds, matrices):
                boxes, mask = kernel(bounds, matrices)
                masks.append(mask)
                return boxes, mask

            monkeypatch.setattr(_native, "qt_world_boxes", lambda: record_boxes)
        command = MoveGroupCommand(parent, V(2.25, -.875, .625))
        for apply in (lambda: vp.history.execute(command), vp.history.undo):
            assert apply()
            if kernel is None:
                vp._placements()
            assert vp._gather_instanced()
            moved = vp._inst_pool
            assert moved[1] is old[1]
            moved_count = len(siblings) + 2
            assert np.count_nonzero((moved[6] != old[6]).any(axis=1)) == moved_count
            if kernel is not None:
                assert len(masks) == 1
                mask = masks.pop()
                assert len(mask) == moved_count and mask.any() and not mask.all()

            frames = vp._placement_frames
            memo = vp._placements_memo
            vp._placement_frames, vp._placements_memo = {}, None
            try:
                fresh = vp._inst_pool_build(moved[0])
                assert tuple(moved[1]) == tuple(fresh[1]) and moved[5] == fresh[5]
                for i in (2, 3, 4, 6, 7):
                    assert moved[i].tobytes() == fresh[i].tobytes()
                for group in moved[1]:
                    key, (bounds, inverse) = frames[id(group)]
                    ref, (ref_bounds, ref_inverse) = vp._placement_frames[id(group)]
                    assert key[0] == ref[0]
                    assert np.asarray(key[1]).tobytes() == np.asarray(ref[1]).tobytes()
                    assert np.asarray(bounds).tobytes() == np.asarray(ref_bounds).tobytes()
                    assert (np.asarray(inverse.data()).tobytes()
                            == np.asarray(ref_inverse.data()).tobytes())
            finally:
                vp._placement_frames = frames
                vp._placements_memo = memo
            old = moved
    finally:
        vp.close()


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
