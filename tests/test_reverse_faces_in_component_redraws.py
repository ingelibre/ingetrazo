# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A face reversed inside a component reads the same inside and out.

Two roads led to the same picture: right inside, inverted again on leaving.

The drawing: the session reverses a face on a world COPY of the definition.
Leaving wrote the right loops into the definition, but a reversed loop changes
no count, coordinate or paint, so the definition's cached chunk went on serving
the old winding — #197 again, for components instead of groups.

The data: a mirrored placement shows its faces as the definition has them, but
the world copy it opened on kept each loop's order through the reflection, so
its faces read the other way round inside. «Fixing» one there inverted it
outside, this time for real.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core.group import Group, transformed_mesh, world_mesh
from core.history import FlipFacesCommand, History, ReshareInstanceCommand
from core.mesh import Mesh
from core.scene import Scene
from tests.test_chunk_stale_materials import _stub
from views.viewport import Viewport, _proto_wrapper

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _translation(x=3.0):
    m = QMatrix4x4()
    m.translate(x, 0.0, 0.0)
    return m


def _mirror(x=-3.0):
    m = QMatrix4x4()
    m.translate(x, 0.0, 0.0)
    m.scale(-1.0, 1.0, 1.0)
    return m


def _box(inverted=None):
    """A closed box, its fronts out; ``inverted`` names a face wound inward."""
    m = Mesh()
    c = [V(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    for i in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
              (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)):
        m.add_face([c[k] for k in i])
    if inverted is not None:
        m.faces[inverted].loop.reverse()
    return m


def _square():
    m = Mesh()
    m.add_face([V(-1, -1), V(1, -1), V(1, 1), V(-1, 1)])
    return m


def _placed(mesh, xform, name="Pieza"):
    g = Group(mesh, name=name)
    g.xform = xform
    return g


def _drawn_sides(vp, mesh):
    """Each cached triangle's normal, as signs: the side the chunk draws."""
    ch = vp._group_chunk(_proto_wrapper(vp, mesh, None))
    e1 = np.asarray(ch["e1"], float).reshape(-1, 3)
    e2 = np.asarray(ch["e2"], float).reshape(-1, 3)
    return sorted(map(tuple, np.sign(np.round(np.cross(e1, e2), 3)).tolist()))


def _drawn_sides_of_group(vp, group):
    ch = vp._group_chunk(group)
    return np.round(np.cross(ch["e1"], ch["e2"]), 3).tolist()


def _reverse_inside_and_leave(scene, history, group, face_index):
    """What the viewport does: reverse on the world copy, one share-back."""
    scene.begin_group_edit(group)
    history.execute(FlipFacesCommand([scene.mesh.faces[face_index]]))
    grp, proto, xform, _state = scene.take_edit_share()
    scene.end_group_edit()
    history.execute(ReshareInstanceCommand(grp, proto, xform, grp.mesh, []))


# ---- The drawing -------------------------------------------------------------

@pytest.mark.parametrize("cara", [0, 3, 5])
def test_the_definition_draws_the_reversed_face_on_leaving(cara):
    scene = Scene()
    proto = _box(inverted=cara)
    g = _placed(proto, _translation())
    scene.groups.append(g)
    vp = _stub(scene)
    before = _drawn_sides(vp, proto)
    _reverse_inside_and_leave(scene, History(scene), g, cara)
    after = _drawn_sides(vp, proto)
    assert after != before, "the component still draws the old winding"
    assert after == _drawn_sides(_stub(scene), proto), \
        "the open viewport disagrees with one reading the data afresh"


def test_undo_and_redo_of_the_edit_redraw():
    scene = Scene()
    proto = _box(inverted=3)
    g = _placed(proto, _translation())
    scene.groups.append(g)
    vp = _stub(scene)
    history = History(scene)
    before = _drawn_sides(vp, proto)
    _reverse_inside_and_leave(scene, history, g, 3)
    after = _drawn_sides(vp, proto)
    assert after != before
    history.undo()
    assert _drawn_sides(vp, proto) == before, "undo left the new winding"
    history.redo()
    assert _drawn_sides(vp, proto) == after, "redo left the old winding"


def test_leaving_without_a_viewport_says_so_too():
    """The headless road (tests, the AI bridge) shares back by itself."""
    scene = Scene()
    proto = _box(inverted=3)
    g = _placed(proto, _translation())
    scene.groups.append(g)
    vp = _stub(scene)
    before = _drawn_sides(vp, proto)
    scene.begin_group_edit(g)
    FlipFacesCommand([scene.mesh.faces[3]]).do(scene)
    scene.end_group_edit()
    assert _drawn_sides(vp, proto) != before


def test_reversing_and_moving_everything_in_one_session_redraws():
    """A whole-mesh move takes the translation fast path, which reuses the
    cached triangles as they are: it must not carry the old winding along."""
    scene = Scene()
    proto = _box(inverted=3)
    g = _placed(proto, _translation())
    scene.groups.append(g)
    vp = _stub(scene)
    before = _drawn_sides(vp, proto)
    scene.begin_group_edit(g)
    FlipFacesCommand([scene.mesh.faces[3]]).do(scene)
    for v in list(scene.mesh.vertices):
        scene.mesh.move_vertex(v, V(0.5, 0.0))
    scene.end_group_edit()
    assert _drawn_sides(vp, proto) != before


def test_every_copy_of_the_component_shows_it():
    scene = Scene()
    proto = _box(inverted=3)
    a, b = _placed(proto, _translation(3.0)), _placed(proto, _translation(6.0))
    scene.groups += [a, b]
    vp = _stub(scene)
    vp._group_chunk(b)
    _reverse_inside_and_leave(scene, History(scene), a, 3)
    fresh = _stub(scene)._group_chunk(b)
    got = vp._group_chunk(b)
    assert np.allclose(np.cross(got["e1"], got["e2"]),
                       np.cross(fresh["e1"], fresh["e2"]))


def test_a_painted_copy_shows_it_too():
    """A painted copy bakes a chunk of its own from the same definition: the
    first one rebuilt clears the dirty marks, and must not fool the other."""
    scene = Scene()
    proto = _box(inverted=3)
    plain = _placed(proto, _translation(3.0))
    painted = _placed(proto, _translation(6.0))
    painted.material = {"color": [0.8, 0.2, 0.2]}
    scene.groups += [plain, painted]
    vp = _stub(scene)
    sides = lambda ch: np.round(np.cross(ch["e1"], ch["e2"]), 3).tolist()
    before = sides(vp._group_chunk(painted))
    vp._group_chunk(plain)
    _reverse_inside_and_leave(scene, History(scene), plain, 3)
    vp._group_chunk(plain)                          # rebuilt first
    assert sides(vp._group_chunk(painted)) != before


def test_reversing_inside_a_classic_group_reaches_a_second_viewport():
    """#197's own road: a flip in place, read by two chunks of one mesh."""
    scene = Scene()
    mesh = _box()
    g = Group(mesh, name="Grupo")
    scene.groups.append(g)
    a, b = _stub(scene), _stub(scene)
    before = _drawn_sides_of_group(b, g)
    _drawn_sides_of_group(a, g)
    History(scene).execute(FlipFacesCommand([mesh.faces[3]]))
    _drawn_sides_of_group(a, g)
    assert _drawn_sides_of_group(b, g) != before


def test_an_unrelated_component_keeps_its_chunk():
    """The fix must not cost the other definitions their cached chunk."""
    scene = Scene()
    proto, other = _box(inverted=3), _box()
    g, h = _placed(proto, _translation(3.0)), _placed(other, _translation(6.0))
    scene.groups += [g, h]
    vp = _stub(scene)
    kept = vp._group_chunk(_proto_wrapper(vp, other, None))
    _reverse_inside_and_leave(scene, History(scene), g, 3)
    assert vp._group_chunk(_proto_wrapper(vp, other, None)) is kept


# ---- The chunk cache on disk -------------------------------------------------

def _key(mesh):
    return Viewport._chunk_cache_key(mesh, Viewport._mesh_fingerprint(mesh))


def test_the_disk_key_tells_the_windings_apart():
    """A file saved with the face turned reopens with no flip counted: the
    chunk stored before the turn must not answer for it."""
    assert _key(_box()) != _key(_box(inverted=3))
    assert _key(_box(inverted=3)) != _key(_box(inverted=4))


def test_the_disk_key_is_stable_for_the_same_content():
    assert _key(_box(inverted=3)) == _key(_box(inverted=3))


def test_two_sessions_with_one_flip_each_do_not_share_a_key():
    """Counting flips could not tell which face each session turned."""
    a, b = _box(), _box()
    a.faces[1].loop.reverse()
    b.faces[2].loop.reverse()
    a._winding_rev = b._winding_rev = 1
    assert _key(a) != _key(b)


# ---- A mirrored placement ----------------------------------------------------

def _big_grid(n=30):
    """Enough faces for ``transformed_mesh``'s bulk road."""
    m = Mesh()
    for i in range(n):
        for j in range(n):
            m.add_face([V(i, j), V(i + 1, j), V(i + 1, j + 1), V(i, j + 1)])
    return m


@pytest.mark.parametrize("build", [_square, _big_grid],
                         ids=["walk", "bulk"])
def test_a_mirror_copy_keeps_the_side_each_face_shows(build):
    """Reflected across a plane the face is square to, the side stays."""
    src = build()
    up = [f.normal().z() for f in src.faces]
    copy = transformed_mesh(src, _mirror())
    assert [f.normal().z() for f in copy.faces] == pytest.approx(up)


@pytest.mark.parametrize("big", [False, True], ids=["walk", "bulk"])
def test_a_mirror_copy_turns_the_holes_with_their_face(big):
    src = _big_grid() if big else Mesh()
    f = src.add_face([V(100, 0), V(110, 0), V(110, 10), V(100, 10)],
                     [[V(102, 2), V(102, 8), V(108, 8), V(108, 2)]])
    copy = transformed_mesh(src, _mirror())
    i = src.faces.index(f)
    nf = copy.faces[i]
    assert nf.normal().z() == pytest.approx(f.normal().z())
    assert len(nf.hole_loops) == 1
    # The hole winds against its face, as it did before the mirror.
    pts = nf.holes[0]
    s = sum(a.x() * b.y() - b.x() * a.y()
            for a, b in zip(pts, pts[1:] + pts[:1]))
    assert s * nf.normal().z() < 0


def test_a_turn_or_a_move_leaves_the_loops_alone():
    src = _box(inverted=3)
    t = _translation()
    t.rotate(30.0, 0.2, 0.4, 1.0)
    copy = transformed_mesh(src, t)
    moved = [t.map(p) for p in src.faces[3].vertices]
    got = copy.faces[3].vertices
    assert all((a - b).length() < 1e-5 for a, b in zip(moved, got))


def test_a_mirrored_copy_reads_the_same_on_entering():
    scene = Scene()
    proto = _square()
    up = proto.faces[0].normal().z()
    g = _placed(proto, _mirror())
    scene.groups.append(g)
    scene.begin_group_edit(g)
    assert scene.mesh.faces[0].normal().z() == pytest.approx(up)
    scene.end_group_edit()


def test_entering_and_leaving_a_mirrored_copy_changes_nothing():
    scene = Scene()
    proto = _box(inverted=3)
    state = [[v.position for v in f.loop] for f in proto.faces]
    g = _placed(proto, _mirror())
    scene.groups.append(g)
    scene.begin_group_edit(g)
    scene.end_group_edit()
    assert g.mesh is proto
    assert [[v.position for v in f.loop] for f in proto.faces] == state


def test_a_face_reversed_inside_a_mirrored_copy_comes_out_the_same():
    scene = Scene()
    proto = _square()
    up = proto.faces[0].normal().z()
    g = _placed(proto, _mirror())
    scene.groups.append(g)
    scene.begin_group_edit(g)
    FlipFacesCommand(list(scene.mesh.faces)).do(scene)
    inside = scene.mesh.faces[0].normal().z()
    scene.end_group_edit()
    assert inside == pytest.approx(-up)
    assert proto.faces[0].normal().z() == pytest.approx(inside), \
        "the reversed face came out the other way round"


def test_an_edit_inside_a_mirrored_copy_keeps_every_other_face():
    """The way back mirrors again: nothing but the edit may change side."""
    scene = Scene()
    proto = _box()
    normals = [tuple(round(c, 3) for c in (f.normal().x(), f.normal().y(),
                                           f.normal().z()))
               for f in proto.faces]
    g = _placed(proto, _mirror())
    scene.groups.append(g)
    scene.begin_group_edit(g)
    FlipFacesCommand([scene.mesh.faces[3]]).do(scene)
    scene.end_group_edit()
    after = [tuple(round(c, 3) for c in (f.normal().x(), f.normal().y(),
                                         f.normal().z()))
             for f in proto.faces]
    assert after[3] == tuple(-c + 0.0 for c in normals[3])
    assert after[:3] + after[4:] == normals[:3] + normals[4:]


def test_making_a_mirrored_copy_real_keeps_its_sides():
    """Everything that bakes a placement goes through the same copy."""
    g = _placed(_square(), _mirror())
    up = g.mesh.faces[0].normal().z()
    assert world_mesh(g).faces[0].normal().z() == pytest.approx(up)


def test_a_mirrored_nested_placement_bakes_with_its_sides():
    child = _placed(_square(), _mirror())
    up = child.mesh.faces[0].normal().z()
    parent = Group(Mesh(), name="Padre")
    parent.xform = QMatrix4x4()
    parent.children = [child]
    baked = world_mesh(parent)
    assert baked.faces[0].normal().z() == pytest.approx(up)


def test_a_mirrored_placement_in_a_mirrored_parent_cancels_out():
    """Two reflections are a turn: the loops stay as they were."""
    leaf = _placed(_square(), _mirror())
    up = leaf.mesh.faces[0].normal().z()
    parent = Group(Mesh(), name="Padre")
    parent.xform = _mirror(5.0)
    parent.children = [leaf]
    assert world_mesh(parent).faces[0].normal().z() == pytest.approx(up)


# ---- On screen ---------------------------------------------------------------

def _pixel(vp, p):
    vp.update()
    for _ in range(6):
        _app.processEvents()
    img = vp.grabFramebuffer()
    dpr = img.width() / max(vp.width(), 1)
    x, y = vp._world_to_pixel(p)
    c = img.pixelColor(int(x * dpr), int(y * dpr))
    return (c.redF(), c.greenF(), c.blueF())


def _same_colour(a, b):
    return all(abs(x - y) < 0.05 for x, y in zip(a, b))


@pytest.mark.parametrize("xform, centre",
                         [(_translation(), V(3, 0)), (_mirror(), V(-3, 0))],
                         ids=["moved", "mirrored"])
def test_inside_and_outside_show_the_same_colour(xform, centre):
    """Needs a GL context that renders; skipped where the platform has none."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.show()
        for _ in range(10):
            _app.processEvents()
        vp = win.viewport
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        scene = vp.scene
        scene.guides.clear()
        proto = _square()
        if proto.faces[0].normal().z() > 0:         # inverted, seen from above
            proto.faces[0].loop.reverse()
        g = _placed(proto, xform)
        scene.groups.append(g)
        scene.version += 1
        vp.camera.set_view("top")
        vp.camera.perspective = False
        vp.camera.fit_to(centre - V(3, 3), centre + V(3, 3))
        q = centre + V(0.2, 0.5)                    # off the axes

        back = _pixel(vp, q)
        vp.begin_group_edit(g)
        assert _same_colour(_pixel(vp, q), back), "entering changed the side"
        vp.history.execute(FlipFacesCommand([scene.mesh.faces[0]]))
        front = _pixel(vp, q)
        assert not _same_colour(front, back), "reversing changed nothing"
        vp.end_one_group_edit()
        assert _same_colour(_pixel(vp, q), front), \
            "the face went back on leaving the component"
        vp.history.undo()
        assert _same_colour(_pixel(vp, q), back), "undo did not redraw"
        vp.history.redo()
        assert _same_colour(_pixel(vp, q), front), "redo did not redraw"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
