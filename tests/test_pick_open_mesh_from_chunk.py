# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Inside a big group, the open mesh's part of the pick index is read from
the open group's chunk (night of 18-11): the same entities in the same
order, the same areas, visibility and selectability (layers hidden and
locked included) and the same triangles as the per-face walk. With a
hidden face the walk is kept: the chunk leaves hidden faces out."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _open_group(win, hidden_face=False):
    from core.group import Group
    from core.layers import Layer
    from core.mesh import Mesh
    vp = win.viewport
    sc = vp.scene
    m = Mesh()
    for i in range(12):
        for j in range(6):
            loop = [V(i, j, 0), V(i + 1, j, 0), V(i + 1, j + 1, 0),
                    V(i + .5, j + 1.4, 0), V(i, j + 1, 0)]
            holes = ([[V(i + .3, j + .3, 0), V(i + .6, j + .3, 0),
                       V(i + .6, j + .6, 0), V(i + .3, j + .6, 0)]]
                     if (i + j) % 4 == 0 else None)
            f = m.add_face(loop, holes)
            if j == 1:
                f.attrs["layer"] = "Oculta"
            elif j == 2:
                f.attrs["layer"] = "Bloqueada"
            elif j == 3:
                f.attrs["layer"] = "Otra"
    # A standing face too, and a few loose edges.
    m.add_face([V(0, 0, 0), V(3, 0, 0), V(3, 0, 2), V(0, 0, 2)])
    if hidden_face:
        next(iter(m.faces)).attrs["hidden"] = True
    hid = Layer("Oculta")
    hid.visible = False
    lock = Layer("Bloqueada")
    lock.locked = True
    sc.layers.extend([hid, lock, Layer("Otra")])
    g = Group(m, "big")
    sc.groups.append(g)
    # Loose geometry at the root: drawn around the open group.
    sc.mesh.add_face([V(20, 0, 0), V(21, 0, 0), V(21, 1, 0), V(20, 1, 0)])
    sc.version += 1
    vp.begin_group_edit(g)
    _app.processEvents()
    return vp


def _index(vp, monkeypatch, fast):
    vp._pick_index_cache = None
    vp._pick_loose_memo = None
    with monkeypatch.context() as mp:
        mp.setattr(type(vp), "PICK_FROM_CHUNK_MIN", 0 if fast else 10 ** 9)
        return vp._pick_index()


def _same(a, b):
    assert len(a.entities) == len(b.entities)
    assert all(x[0] is y[0] and x[1] is y[1]
               for x, y in zip(a.entities, b.entities))
    for name in ("ent_area", "ent_vis", "ent_sel", "ent_infer", "ent_loose"):
        assert np.array_equal(getattr(a, name), getattr(b, name)), name
    for name in ("tri_v0", "tri_e1", "tri_e2", "tri_ent"):
        x, y = getattr(a, name, None), getattr(b, name, None)
        if x is None or y is None:
            assert x is None and y is None, name
            continue
        # Each triangle carries its entity: compare as sets of rows.
        assert x.shape == y.shape, name
    rows = lambda i: np.concatenate(   # noqa: E731
        [i.tri_v0, i.tri_e1, i.tri_e2, i.tri_ent[:, None].astype(float)],
        axis=1)
    ra, rb = rows(a), rows(b)
    ra = ra[np.lexsort(ra.T[::-1])]
    rb = rb[np.lexsort(rb.T[::-1])]
    assert np.array_equal(ra, rb)


def test_the_open_mesh_part_is_the_walk(win, monkeypatch):
    vp = _open_group(win)
    calls = []
    real = type(vp)._open_mesh_pick_part
    monkeypatch.setattr(type(vp), "_open_mesh_pick_part",
                        lambda self: calls.append(1) or real(self))
    fast = _index(vp, monkeypatch, True)
    assert calls and fast is not None
    walk = _index(vp, monkeypatch, False)
    _same(fast, walk)
    assert fast.ent_vis.sum() < len(fast.entities)        # a hidden layer
    assert fast.ent_sel.sum() < fast.ent_vis.sum()        # a locked one


def test_after_an_edit_it_is_still_the_walk(win, monkeypatch):
    from core.history import SetFaceColorCommand
    vp = _open_group(win)
    _index(vp, monkeypatch, True)
    f = list(vp.scene.mesh.faces)[5]
    vp.history.execute(SetFaceColorCommand([f], (0.9, 0.1, 0.1)))
    for v in list(vp.scene.mesh.faces)[7].loop:
        v.position = v.position + V(0, 0, 0.5)
    vp.scene.version += 1
    _same(_index(vp, monkeypatch, True), _index(vp, monkeypatch, False))


def test_a_hidden_face_keeps_the_walk(win, monkeypatch):
    vp = _open_group(win, hidden_face=True)
    with monkeypatch.context() as mp:
        mp.setattr(type(vp), "PICK_FROM_CHUNK_MIN", 0)
        assert vp._open_mesh_pick_part() is None
    _same(_index(vp, monkeypatch, True), _index(vp, monkeypatch, False))


def test_the_selection_highlight_from_the_chunk_is_the_faces_own(win,
                                                                  monkeypatch):
    vp = _open_group(win)
    faces = [f for f in vp.scene.mesh.faces][:60] * 1
    more = list(vp.scene.mesh.faces)
    vp.scene.select(more)
    monkeypatch.setattr(type(vp), "SEL_SHIFT_MIN", 10)
    vp._sel_runs_memo = None
    got = vp._selected_face_runs()
    paint = None
    want: dict = {}
    from views.viewport import effective_back_color
    back = effective_back_color(vp._view_style(), vp.scene)
    for f in sorted(more, key=id):
        key = vp._selection_dot_colors(f, paint, back, {})
        buf = want.setdefault(key, [])
        for t0, t1, t2 in f.triangulate():
            buf.extend([t0.x(), t0.y(), t0.z(), t1.x(), t1.y(), t1.z(),
                        t2.x(), t2.y(), t2.z()])
    assert vp._selected_runs_from_chunk(sorted(more, key=id), [
        vp._selection_dot_colors(f, paint, back, {}) for f in
        sorted(more, key=id)]) is not None
    assert got.keys() == want.keys()
    for k in want:
        a = np.frombuffer(got[k], np.float32).reshape(-1, 9)
        b = np.asarray(want[k], np.float32).reshape(-1, 9)
        assert np.array_equal(a, b)
    del faces
