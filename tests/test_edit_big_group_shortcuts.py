# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The shortcuts that keep editing inside a big group fast give what the
full work gives (night of 18-11).

- A face moved whole (Move) keeps its triangulation, shifted.
- The open mesh baked for the open group is the bake its copies use.
- A selection moved whole shifts its highlight instead of building it.
- Push/Pull's side edges are classified the same with the box filter.
- Entity info waits for calm only with a big selection.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _grid(mesh, n, z=0.0, holes=False):
    faces = []
    for i in range(n):
        for j in range(n):
            loop = [V(i, j, z), V(i + 1, j, z), V(i + 1, j + 1, z),
                    V(i + 0.5, j + 1.3, z), V(i, j + 1, z)]
            faces.append(mesh.add_face(loop))
    return faces


# ---- per-face geometry ------------------------------------------------------

def test_a_face_moved_whole_keeps_its_triangles_shifted():
    from core.mesh import Mesh
    from core.triangulate import triangulate
    from views.viewport import _face_geometry
    m = Mesh()
    f = _grid(m, 1)[0]
    memo: dict = {}
    _face_geometry(f, memo, triangulate)
    for v in f.loop:
        v.position = v.position + V(3.25, -1.5, 0.75)
    moved = _face_geometry(f, memo, triangulate)
    fresh = _face_geometry(f, None, triangulate)
    assert abs(moved[2] - fresh[2]) < 1e-9
    assert np.allclose(moved[6], fresh[6], atol=1e-5)
    assert (moved[4] - fresh[4]).length() < 1e-5
    assert np.allclose(moved[7][1], fresh[7][1], atol=1e-5)


def test_a_face_bent_is_triangulated_again():
    from core.mesh import Mesh
    from core.triangulate import triangulate
    from views.viewport import _face_geometry
    m = Mesh()
    f = _grid(m, 1)[0]
    memo: dict = {}
    _face_geometry(f, memo, triangulate)
    first = f.loop[3]
    first.position = first.position + V(0.0, 0.4, 0.0)   # one corner only
    again = _face_geometry(f, memo, triangulate)
    fresh = _face_geometry(f, None, triangulate)
    assert abs(again[2] - fresh[2]) < 1e-12
    assert again[6] == fresh[6]


# ---- the open group and its copies -----------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _bake_fields(entry):
    out = {}
    for k, v in entry.items():
        if isinstance(v, (bytes, bytearray)):
            out[k] = bytes(v)
        elif isinstance(v, np.ndarray):
            out[k] = v.tobytes()
    return out


def test_the_open_mesh_is_baked_once_for_the_group_and_its_copies(win):
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.history import SetFaceColorCommand
    from core.mesh import Mesh
    vp = win.viewport
    m = Mesh()
    _grid(m, 6)
    a = Group(m, "flag")
    a.component = True
    b = Group(m, "flag")
    b.component = True
    xf = QMatrix4x4()
    xf.translate(20.0, 0.0, 0.0)
    b.xform = xf
    vp.scene.groups.extend([a, b])
    vp.scene.version += 1
    vp.begin_group_edit(a)
    _app.processEvents()
    E = vp.scene.edit_group
    face = next(iter(E.mesh.faces))
    vp.history.execute(SetFaceColorCommand([face], (0.9, 0.2, 0.1)))
    copies = [g for g in vp.scene.groups if g is not E and g.mesh is E.mesh]
    first = vp._group_chunk(E)
    for g in copies:
        vp._group_chunk(g)
    from views.viewport import _paint_of, _proto_wrapper
    assert copies
    assert vp._fresh_edit_chunk is not None
    assert vp._fresh_edit_chunk[3] is first
    for g in copies:                    # the copies' prototype: that bake
        w = _proto_wrapper(vp, g.mesh, _paint_of(vp, g))
        assert vp._group_chunks[id(w)] is first
    shared = _bake_fields(first)
    # A cold bake makes the very same arrays.
    vp._group_chunks = {}
    vp._fresh_edit_chunk = None
    cold = _bake_fields(vp._group_chunk(E))
    assert shared.keys() == cold.keys()
    for k in shared:
        assert shared[k] == cold[k], k


# ---- the selection highlight -----------------------------------------------

def test_a_selection_moved_whole_shifts_its_highlight(win):
    vp = win.viewport
    faces = _grid(vp.scene.mesh, 18)                 # 324 faces > 256
    vp.scene.version += 1
    vp.scene.select(faces)
    vp._selected_face_runs()
    assert vp._sel_runs_memo is not None
    for v in vp.scene.mesh.vertices:
        v.position = v.position + V(1.5, 2.25, -0.5)
    shifted = vp._selected_face_runs()
    vp._sel_runs_memo = None
    fresh = vp._selected_face_runs()
    assert shifted.keys() == fresh.keys()
    for k in fresh:
        a = np.frombuffer(shifted[k], np.float32)
        b = np.frombuffer(fresh[k], np.float32)
        assert a.shape == b.shape
        # Same triangles, possibly another face order: compare sorted rows.
        ra = np.sort(a.reshape(-1, 9), axis=0)
        rb = np.sort(b.reshape(-1, 9), axis=0)
        assert np.allclose(ra, rb, atol=1e-5)


def test_a_selection_bent_builds_its_highlight_again(win):
    vp = win.viewport
    faces = _grid(vp.scene.mesh, 18)
    vp.scene.version += 1
    vp.scene.select(faces)
    vp._selected_face_runs()
    faces[0].loop[3].position = faces[0].loop[3].position + V(0, 0.3, 0)
    again = vp._selected_face_runs()
    vp._sel_runs_memo = None
    fresh = vp._selected_face_runs()
    for k in fresh:
        assert bytes(again[k]) == bytes(fresh[k])


# ---- Push/Pull side edges ---------------------------------------------------

def test_side_edges_are_classified_as_without_the_box_filter():
    from core.mesh import Mesh
    from core import topology as T
    m = Mesh()
    base = _grid(m, 5)
    # Walls standing on some edges, a far plane, a face across.
    m.add_face([V(0, 0, 0), V(5, 0, 0), V(5, 0, 2), V(0, 0, 2)])
    m.add_face([V(2, 0, 0), V(2, 5, 0), V(2, 5, 3), V(2, 0, 3)])
    m.add_face([V(0, 0, 9), V(5, 0, 9), V(5, 5, 9), V(0, 5, 9)])
    faces = list(m.faces)

    def reference(face, a, b):
        fn = face.normal()
        cop = [g for g in faces if g is not face
               and T._faces_coplanar(fn, g.normal())]
        oth = [g for g in faces if g is not face and g not in cop]
        es = frozenset((T._key(a), T._key(b)))
        for g in cop:
            if es in T._face_all_edges(g) or T._segment_on_face_boundary(a, b, g):
                return ("coplanar", g)
        for s in oth:
            if T._segment_on_face_boundary(a, b, s):
                return ("perp", s)
        return ("free", None)

    for face in base:
        memo: dict = {}
        loop = face.vertices
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            got = T.classify_push_edge(face, a, b, faces, memo)
            want = reference(face, a, b)
            assert got[0] == want[0] and got[1] is want[1]


@pytest.mark.parametrize("seed", range(12))
def test_side_edges_are_classified_as_without_the_box_filter_random(seed):
    """Boxes, holed slabs, walls standing on part of an edge, a face with a
    wider coplanar neighbour (the edge only a sub-segment of its border)."""
    import random
    from core.mesh import Mesh
    from core import topology as T
    rng = random.Random(seed)
    m = Mesh()
    for _ in range(rng.randint(3, 8)):
        x, y = rng.randint(0, 6), rng.randint(0, 6)
        w, d = rng.randint(1, 3), rng.randint(1, 3)
        z = rng.choice([0.0, 0.0, 1.0])
        holes = None
        if w > 1 and d > 1 and rng.random() < .4:
            holes = [[V(x + .4, y + .4, z), V(x + .8, y + .4, z),
                      V(x + .8, y + .8, z), V(x + .4, y + .8, z)]]
        m.add_face([V(x, y, z), V(x + w, y, z), V(x + w, y + d, z),
                    V(x, y + d, z)], holes)
        if rng.random() < .5:                  # a wall on part of an edge
            t = rng.choice([0.0, 0.5])
            m.add_face([V(x + t, y, z), V(x + w, y, z), V(x + w, y, z + 1),
                        V(x + t, y, z + 1)])
        if rng.random() < .3:                  # a wider coplanar neighbour
            m.add_face([V(x - 1, y + d, z), V(x + w + 1, y + d, z),
                        V(x + w + 1, y + d + 1, z), V(x - 1, y + d + 1, z)])
    faces = list(m.faces)

    def reference(face, a, b):
        fn = face.normal()
        cop = [g for g in faces if g is not face
               and T._faces_coplanar(fn, g.normal())]
        oth = [g for g in faces if g is not face and g not in cop]
        es = frozenset((T._key(a), T._key(b)))
        for g in cop:
            if es in T._face_all_edges(g) or T._segment_on_face_boundary(a, b, g):
                return ("coplanar", g)
        for s in oth:
            if T._segment_on_face_boundary(a, b, s):
                return ("perp", s)
        return ("free", None)

    kinds = set()
    for face in faces:
        memo: dict = {}
        for lp in (face.vertices, *face.holes):
            for i in range(len(lp)):
                a, b = lp[i], lp[(i + 1) % len(lp)]
                got = T.classify_push_edge(face, a, b, faces, memo)
                want = reference(face, a, b)
                assert got[0] == want[0] and got[1] is want[1]
                kinds.add(got[0])
    assert "free" in kinds
    assert len(kinds) == 3 or seed % 4, kinds


# ---- Entity info ------------------------------------------------------------

def test_entity_info_waits_for_calm_only_with_a_big_selection(win, monkeypatch):
    tray = win.tray
    calls = []
    monkeypatch.setattr(tray.entity_info, "refresh", lambda: calls.append(1))
    # (The timer connects to the bound method when first made: rebuild it.)
    tray._info_timer = None
    vp = win.viewport
    few = _grid(vp.scene.mesh, 3)
    vp.scene.select(few)
    tray.on_scene_changed()
    assert calls == [1]                              # at once
    many = list(vp.scene.mesh.faces) + _grid(vp.scene.mesh, 46, z=1.0)
    assert len(many) > tray.INFO_DEFER_FROM
    vp.scene.select(many)
    tray.on_scene_changed()
    tray.on_scene_changed()
    assert calls == [1]                              # not yet
    tray._info_timer.timeout.emit()
    assert calls == [1, 1]                           # once, after the burst


# ---- a paint flags only the painted mesh ------------------------------------

def test_a_paint_flags_only_the_mesh_of_its_faces():
    from core.group import Group
    from core.history import SetFaceColorCommand, _dirty_group_chunks
    from core.mesh import Mesh
    from core.scene import Scene
    sc = Scene()
    other = Mesh()
    _grid(other, 2)
    g = Group(other, "other")
    sc.groups.append(g)
    mine = _grid(sc.mesh, 2)
    other._chunk_dirty = other._attrs_dirty = False
    sc.mesh._attrs_dirty = False
    SetFaceColorCommand(mine[:2], (1.0, 0.0, 0.0)).do(sc)
    assert sc.mesh._attrs_dirty and not other._attrs_dirty
    # A face of another mesh: every mesh, as before.
    _dirty_group_chunks(sc, [next(iter(other.faces))])
    assert other._attrs_dirty
    other._attrs_dirty = False
    _dirty_group_chunks(sc)                      # no faces said: all
    assert other._attrs_dirty
