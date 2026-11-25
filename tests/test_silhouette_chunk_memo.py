# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The outline pass keeps each loose group's chunk while the scene's
version stays (night of 19-11): every ~80 ms of an orbit it asked all the
groups for theirs again. Frame after frame the outline uploaded is the one
worked out asking afresh, and an edit shows in the next one."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.test_edit_context_keeps_rows import _box  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Vbo:
    def __init__(self):
        self.raw = None

    def bind(self):
        pass

    def release(self):
        pass

    def allocate(self, raw, n=None):
        self.raw = raw if isinstance(raw, (bytes, bytearray)) else b""


@pytest.fixture
def vp():
    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    v = win.viewport
    v.resize(1000, 700)
    sc = v.scene
    sc.guides.clear()
    for i in range(12):
        sc.groups.append(Group(_box(2.0 * i, (i % 3) * 2.0, 1.0,
                                    curved=i % 2 == 0), name=f"G{i}"))
    sc.version += 1
    v.camera.set_view("iso")
    v.camera.fit_to(V(-1, -1, 0), V(25, 7, 2))
    v._silhouette_vbo = _Vbo()
    try:
        yield v
    finally:
        win._saved_version = sc.version
        win.close()


def _outline(vp, fresh):
    vp._sil_last = None
    if fresh:
        vp._sil_chunk_memo = None
    vp._upload_silhouette_edges()
    return vp._silhouette_vbo.raw


def test_the_outline_is_the_one_asked_afresh(vp, monkeypatch):
    asked = []
    real = type(vp)._group_chunk

    def spy(self, g):
        asked.append(g.name)
        return real(self, g)

    monkeypatch.setattr(type(vp), "_group_chunk", spy)
    seen = set()
    for k in range(10):
        vp.camera.yaw += math.radians(37)
        vp.camera.pitch = math.radians(10 + 7 * (k % 5))
        got = _outline(vp, fresh=False)
        n = len(asked)
        want = _outline(vp, fresh=True)
        assert got == want, k
        seen.add(got)
        if k:
            assert n == n0, "the kept chunks were asked for again"
        n0 = len(asked)
        asked.clear()
        _outline(vp, fresh=False)              # warm the memo again
        n0 = len(asked)
        asked.clear()
    assert len(seen) > 2 and all(seen)          # the outline changes, and is


def test_dense_outline_refresh_matches_a_rebuilt_table(vp):
    import numpy as np
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.history import MoveGroupCommand
    from tests.test_move_incremental_passes import _prisma

    meshes = [_prisma(8, r=0.5 + i / 32) for i in range(16)]
    children = [Group(meshes[i % len(meshes)]) for i in range(1031)]
    for i, child in enumerate(children):
        child.xform = QMatrix4x4()
        child.xform.translate(i % 41, i // 41, i % 3 - 1.)
        if i % 3 == 0:
            child.xform.rotate(i % 37, 0., 0., 1.)
        if i % 11 == 0:
            child.xform.scale(-.75, 1.25, 1.)
        if i % 17 == 0:
            child.material = {"color": (.23, .47, .52)}
    parent = Group()
    parent.material = {"color": (.12, .18, .22)}
    parent.adopt(children)
    vp.scene.groups[:] = [parent]
    vp.scene.version += 1
    eye = V(-3., 8., 12.)
    groups = vp._placements()
    table, rest = vp._silhouette_table(groups)
    assert not rest

    def snapshot(entries):
        return tuple((np.asarray(t["xf"], np.float64).tobytes(),
                          *(t[key].tobytes() for key in ("fwd", "inv", "lo", "hi")))
                         for t in entries)

    command = MoveGroupCommand(parent, V(.125, -.375, .625))
    for apply in (lambda: vp.history.execute(command), vp.history.undo):
        assert apply()
        groups = vp._placements()
        moved, rest = vp._silhouette_table(groups)
        assert not rest and moved is table
        actual = vp._instanced_silhouettes(groups, eye, None)
        memo = vp._sil_table
        vp._sil_table = None
        try:
            fresh, rest = vp._silhouette_table(groups)
            assert not rest and fresh is not table
            assert snapshot(moved) == snapshot(fresh)
            assert actual == vp._instanced_silhouettes(groups, eye, None)
        finally:
            vp._sil_table = memo

    # One valid changed row followed by a singular row must leave the table intact.
    before = snapshot(table), tuple(t["rev"] for t in table)
    table[0]["groups"][0].xform.translate(.5, 0., 0.)
    table[-1]["groups"][-1].xform.scale(0., 0., 0.)
    assert not vp._sil_table_moved(table, [])
    assert before == (snapshot(table), tuple(t["rev"] for t in table))


def test_an_edit_shows_in_the_next_outline(vp):
    before = _outline(vp, fresh=False)
    g = next(g for g in vp.scene.groups if g.name == "G1")   # not curved
    g.mesh = _box(2.0, 2.0, 1.0, curved=True)   # its curved remake
    vp.scene.version += 1
    after = _outline(vp, fresh=False)
    assert after == _outline(vp, fresh=True)
    assert len(after) > len(before)


def test_a_vertex_moved_in_place_shows_in_the_next_outline(vp):
    g = next(g for g in vp.scene.groups if g.name == "G0")   # curved
    before = _outline(vp, fresh=False)
    for v in list(g.mesh.vertices):
        g.mesh.place_vertex(v, v.position + V(0.0, 0.0, 0.5))
    vp.scene.version += 1
    after = _outline(vp, fresh=False)
    assert after == _outline(vp, fresh=True)
    assert after != before


def test_a_mesh_swapped_without_a_version_is_read(vp):
    """_group_chunk tells another mesh from its entry's at any version
    (#134): so does the kept chunk."""
    g = next(g for g in vp.scene.groups if g.name == "G3")   # not curved
    before = _outline(vp, fresh=False)
    g.mesh = _box(6.0, 0.0, 1.0, curved=True)
    after = _outline(vp, fresh=False)
    assert after == _outline(vp, fresh=True)
    assert after != before
