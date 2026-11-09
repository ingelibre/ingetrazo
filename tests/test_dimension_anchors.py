# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Model dimensions attached to the geometry they measure — the three things
the first user of DriveMeca's video missed (2026-09-20), in Marco's words:
«dibujamos algo, lo acotamos, después lo escalamos y la acotación se queda
allí, no se redimensiona con el dibujo y no se actualiza la nueva medición»;
«con M de mover podemos mover la cota conservando la línea guía»; and the
ends, «los extremos no tiene para cambiarla»."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.dimension import Dimension
from core.group import Group
from core.history import (AddDimensionCommand, History, MoveDimensionsCommand,
                          MoveGroupCommand,
                          MoveVerticesCommand)
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext
from tools.move import MoveTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None

    def pick_group(self, x, y):
        return None

    def pick_dimension(self, x, y):
        return None


def _ctx(vp, x, y, z=0.0):
    return ToolContext(viewport=vp, world=V(x, y, z), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _square(scene, size=4.0):
    return scene.mesh.add_face([V(0, 0), V(size, 0), V(size, size),
                                V(0, size)])


# ---- 1. the dimension follows the geometry ---------------------------------

def test_a_dimension_on_two_vertices_follows_a_scale_and_re_measures():
    scene = Scene()
    _square(scene)
    hist = History(scene)
    d = Dimension(V(0, 0), V(4, 0), V(0, -1))
    hist.execute(AddDimensionCommand(d))
    assert d.anchored and d.value() == pytest.approx(4.0)
    # stretch the square: the right side goes from x=4 to x=6
    hist.execute(MoveVerticesCommand([V(4, 0), V(4, 4)], V(2, 0)))
    assert d.b == V(6, 0)
    assert d.value() == pytest.approx(6.0)               # re-measured
    ap, bp = d.line_points()
    assert bp == V(6, -1)                                # the line came along
    hist.undo()
    assert d.value() == pytest.approx(4.0)               # and back


def test_the_scale_tool_command_takes_the_dimension_along():
    """The user's very case: draw, dimension, scale — the dimension must
    grow with the drawing and say the new length."""
    from core.history import ScaleVerticesCommand
    scene = Scene()
    _square(scene)
    hist = History(scene)
    d = Dimension(V(0, 0), V(4, 0), V(0, -1))
    hist.execute(AddDimensionCommand(d))
    corners = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    hist.execute(ScaleVerticesCommand(corners, V(0, 0), 1.5))
    assert d.value() == pytest.approx(6.0)
    assert d.b == V(6, 0)
    hist.undo()
    assert d.value() == pytest.approx(4.0)


def test_an_endpoint_off_any_vertex_stays_static():
    scene = Scene()
    _square(scene)
    hist = History(scene)
    d = Dimension(V(0, 0), V(2, 0), V(0, -1))            # b on a midpoint
    hist.execute(AddDimensionCommand(d))
    assert d.anchor_a is not None and d.anchor_b is None and not d.anchored
    hist.execute(MoveVerticesCommand([V(4, 0), V(4, 4)], V(2, 0)))
    assert d.b == V(2, 0) and d.value() == pytest.approx(2.0)


def test_a_dimension_on_a_group_made_from_geometry_follows_the_scale_tool():
    """Marco, 2026-09-20: «la vez pasada arreglamos a medias… faltaba en
    grupo: tenga un grupo acotado y lo escalo». Make Group moves the
    geometry into the group's mesh and leaves ORPHAN vertices behind in
    the loose one, at the same spots; the anchor found those ghosts first
    and the group scaled away from under the dimension. A vertex nothing
    references is no anchor."""
    from core.edits import build_add_edges
    from core.history import MakeGroupCommand
    from tools.scale import ScaleTool
    scene = Scene()
    vp = _Vp(scene)
    sq = [V(2, 0), V(6, 0), V(6, 2), V(2, 2)]
    vp.history.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)]))
    vp.history.execute(MakeGroupCommand(list(scene.mesh.faces),
                                        list(scene.mesh.edges)))
    g = scene.groups[0]
    d = Dimension(V(2, 0), V(6, 0), V(0, -1))
    vp.history.execute(AddDimensionCommand(d))
    assert d.anchored
    assert d.anchor_a.mesh is g.mesh and d.anchor_a.chain == (g,)
    scene.selection.clear()
    scene.selection.add(g)
    t = ScaleTool()
    t.on_activate(vp)
    grip = next(gr for gr in t._grips if gr.params == (1.0, 1.0, 0.5))
    t._grab(vp, grip, (0.0, 0.0))                    # anchor = corner (2, 0)
    t._commit(vp, (1.5, 1.5, 1.0))
    assert d.value() == pytest.approx(6.0)           # 4 m × 1.5
    assert d.b == V(8, 0)
    vp.history.undo()
    assert d.value() == pytest.approx(4.0)


def test_a_dimension_grouped_with_its_geometry_follows_the_group():
    """Marco, 2026-09-20: «hice un cubo, lo acoté, y todo en su conjunto
    hasta la cota hice como grupo; escalo, la cota no sigue». The
    dimension had been holding the LOOSE vertices; Make Group replaced
    them with new ones in the group's mesh at the same spots, and the
    hold died. A dead hold looks again where the endpoint last was and
    takes the vertex standing there — the group's — so scaling the group
    takes the dimension along; undoing the group hands it back to the
    loose vertices."""
    from core.edits import build_add_edges
    from core.history import MakeGroupCommand
    from tools.scale import ScaleTool
    scene = Scene()
    vp = _Vp(scene)
    sq = [V(2, 0), V(6, 0), V(6, 2), V(2, 2)]
    vp.history.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)]))
    d = Dimension(V(2, 0), V(6, 0), V(0, -1))
    vp.history.execute(AddDimensionCommand(d))       # holds the loose vertices
    assert d.anchored and d.anchor_a.chain == ()
    vp.history.execute(MakeGroupCommand(list(scene.mesh.faces),
                                        list(scene.mesh.edges)))
    g = scene.groups[0]
    assert d.a == V(2, 0)                            # re-bound on the read
    assert d.anchor_a is not None and d.anchor_a.chain == (g,)
    scene.selection.clear()
    scene.selection.add(g)
    t = ScaleTool()
    t.on_activate(vp)
    grip = next(gr for gr in t._grips if gr.params == (1.0, 1.0, 0.5))
    t._grab(vp, grip, (0.0, 0.0))
    t._commit(vp, (1.5, 1.5, 1.0))
    assert d.value() == pytest.approx(6.0)
    vp.history.undo()                                # the scale
    assert d.value() == pytest.approx(4.0)
    vp.history.undo()                                # the group itself
    assert not scene.groups
    assert d.value() == pytest.approx(4.0)
    assert d.anchor_a is not None and d.anchor_a.chain == ()   # loose again
    scene.mesh.move_vertex(scene.mesh.vertex_at(V(6, 0)), V(1, 0, 0))
    assert d.value() == pytest.approx(5.0)           # and still following


def test_far_out_coordinates_still_bind_through_a_placement():
    """A point that came through a placement's float32 matrix and back is
    off by a micron or so at hundreds of metres; the old 1e-6 tolerance
    rejected the very vertex the registry had found."""
    from core.group import world_mesh
    scene = Scene()
    m = Mesh()
    m.add_face([V(0, 0), V(2.37, 0), V(2.37, 1.41), V(0, 1.41)])
    g = Group(m, "lejos")
    g.xform = QMatrix4x4()
    g.xform.translate(412.345, -387.89, 3.2)
    g.xform.rotate(33.0, 0, 0, 1)
    scene.groups.append(g)
    for v in world_mesh(g).vertices:                 # what the snap hands over
        d = Dimension(v.position, v.position + V(1, 0), V(0, -1))
        d.bind(scene)
        assert d.anchor_a is not None, v.position


def test_a_dimension_inside_a_component_follows_its_placement():
    scene = Scene()
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    g = Group(m, "caja")
    g.xform = QMatrix4x4()
    g.xform.translate(10.0, 0.0, 0.0)
    scene.groups.append(g)
    d = Dimension(V(10, 0), V(12, 0), V(0, -1))
    d.bind(scene)
    assert d.anchored and d.anchor_a.chain == (g,)
    t = QMatrix4x4()
    t.translate(0.0, 5.0, 0.0)
    g.xform = t * g.xform                                 # the instance moves
    assert d.a == V(10, 5) and d.b == V(12, 5)
    s = QMatrix4x4()
    s.scale(2.0, 2.0, 2.0)
    g.xform = g.xform * s                                 # …and is scaled
    assert d.value() == pytest.approx(4.0)


def test_a_vertex_that_is_gone_freezes_the_endpoint():
    scene = Scene()
    f = _square(scene)
    d = Dimension(V(0, 0), V(4, 0), V(0, -1))
    d.bind(scene)
    assert d.anchored
    scene.mesh.remove_face(f)
    for e in list(scene.mesh.edges):
        scene.mesh.remove_edge(e)
    scene.mesh.prune_orphan_vertices()                   # what an erase does
    assert d.a == V(0, 0) and d.b == V(4, 0)             # last known spot
    assert not d.anchored                                # and let go


def test_the_igz_round_trip_binds_again(tmp_path):
    from formats import igz
    scene = Scene()
    _square(scene)
    hist = History(scene)
    hist.execute(AddDimensionCommand(Dimension(V(0, 0), V(4, 0), V(0, -1))))
    path = tmp_path / "cota.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    d = back.dimensions[0]
    assert d.anchored
    back.mesh.move_vertex(back.mesh.vertex_at(V(4, 0)), V(1, 0, 0))
    assert d.value() == pytest.approx(5.0)


# ---- 2. Move slides the line, the extension lines keep their vertices ----

def test_move_on_an_anchored_dimension_slides_its_line_only():
    scene = Scene()
    _square(scene)
    vp = _Vp(scene)
    d = Dimension(V(0, 0), V(4, 0), V(0, -1))
    vp.history.execute(AddDimensionCommand(d))
    scene.selection.add(d)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 2, -1))                        # grab the line
    tool.on_hover(_ctx(vp, 3, -3))                        # drag: +1 along, -2 away
    assert d.offset == V(0, -3)                           # only the ⟂ part
    assert d.a == V(0, 0) and d.b == V(4, 0)              # ends hold
    tool.on_click(_ctx(vp, 3, -3))
    assert d.offset == V(0, -3)
    assert scene.mesh.vertex_at(V(0, 0)) is not None      # geometry untouched
    vp.history.undo()
    assert d.offset == V(0, -1)


def test_moving_the_geometry_with_the_dimension_selected_moves_it_once():
    scene = Scene()
    f = _square(scene)
    vp = _Vp(scene)
    d = Dimension(V(0, 0), V(4, 0), V(0, -1))
    vp.history.execute(AddDimensionCommand(d))
    scene.selection.add(f)
    scene.selection.add(d)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 0, 10))                        # everything up 10
    assert d.a == V(0, 10) and d.b == V(4, 10)            # rode with its vertices
    assert d.offset == V(0, -1)                           # the line not shifted twice


def test_a_free_dimension_moves_rigidly():
    scene = Scene()
    vp = _Vp(scene)
    d = Dimension(V(1, 1), V(3, 1), V(0, -1))             # on nothing
    vp.history.execute(AddDimensionCommand(d))
    assert not d.anchored
    scene.selection.add(d)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 2, 0))
    tool.on_click(_ctx(vp, 2, 5))
    assert d.a == V(1, 6) and d.b == V(3, 6) and d.offset == V(0, -1)
    vp.history.undo()
    assert d.a == V(1, 1)


def test_the_command_alone_undoes_cleanly():
    scene = Scene()
    _square(scene)
    d = Dimension(V(0, 0), V(4, 0), V(0, -1))
    d.bind(scene)
    hist = History(scene)
    hist.execute(MoveDimensionsCommand({d: "line"}, V(0, -2)))
    assert d.offset == V(0, -3)
    hist.undo()
    assert d.offset == V(0, -1)


# ---- 3. the ends -----------------------------------------------------------

def test_new_documents_take_arrows_and_old_ones_keep_their_ticks(tmp_path):
    from formats import igz
    assert Scene().dimension_style["ends"] == "arrow"
    scene = Scene()
    scene.dimension_style["ends"] = "none"
    path = tmp_path / "ends.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.dimension_style["ends"] == "none"          # travels
    legacy = Scene()
    legacy.dimension_style.update({"ends": "tick", **{"decimals": 3}})
    assert legacy.dimension_style["ends"] == "tick"
    # the loader's own rule: a style saved without the key means ticks —
    # a plain-JSON document (the older shape the reader still takes)
    import json
    payload = {"igz_format": 1, "scene": {
        "vertices": [], "edges": [], "faces": [],
        "dimension_style": {"decimals": 3, "units": "cm"}}}
    old = tmp_path / "old.igz"
    old.write_text(json.dumps(payload), encoding="utf-8")
    back = Scene()
    igz.load_into(back, old)
    assert back.dimension_style["ends"] == "tick"
    assert back.dimension_style["decimals"] == 3


# ---- 4. edit contexts (issue #621) ------------------------------------------

def _component(scene, at=10.0):
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    g = Group(m, "caja")
    g.xform = QMatrix4x4()
    g.xform.translate(at, 0.0, 0.0)
    scene.groups.append(g)
    return g


def _classic_group(scene):
    m = Mesh()
    m.add_face([V(10, 0), V(12, 0), V(12, 2), V(10, 2)])
    g = Group(m, "grupo")
    scene.groups.append(g)
    return g


def test_entering_a_component_leaves_its_dimensions_where_they_were():
    """#621, item 5: entering a component puts the instance on a world copy
    of its definition and clears the placement; a hold on the definition's
    vertex then read its LOCAL coordinates as world ones — the dimension
    jumped by the placement, and came back on leaving."""
    scene = Scene()
    g = _component(scene)
    d = Dimension(V(10, 0), V(12, 0), V(0, -1))
    d.bind(scene)
    assert d.anchored
    scene.begin_group_edit(g)
    assert d.a == V(10, 0) and d.b == V(12, 0)
    assert d.line_points()[0] == V(10, -1)
    scene.end_group_edit()
    assert d.a == V(10, 0) and d.b == V(12, 0)
    t = QMatrix4x4()
    t.translate(0.0, 5.0, 0.0)
    g.xform = t * g.xform                                 # and still holds
    assert d.a == V(10, 5) and d.b == V(12, 5)


@pytest.mark.parametrize("make", [_component, _classic_group],
                         ids=["component", "group"])
def test_a_dimension_drawn_inside_an_object_moves_with_it(make):
    """#621, item 6: a dimension added while the object is open held the
    edited mesh as if it were loose geometry, so the hold was dead from
    the start and the dimension froze — moving the closed object left it
    behind."""
    scene = Scene()
    g = make(scene)
    hist = History(scene)
    scene.begin_group_edit(g)
    d = Dimension(V(10, 0), V(12, 0), V(0, -1))
    hist.execute(AddDimensionCommand(d))
    assert d.value() == pytest.approx(2.0)                # read while open
    scene.end_group_edit()
    assert d.anchored
    assert d.a == V(10, 0) and d.b == V(12, 0)
    hist.execute(MoveGroupCommand(g, V(0, 5)))
    assert d.a == V(10, 5) and d.b == V(12, 5)
    assert d.line_points()[0] == V(10, 4)
    hist.undo()
    assert d.a == V(10, 0)


def test_an_edit_inside_a_component_reaches_its_dimension_on_leaving():
    """Leaving after an edit writes the world copy back into the shared
    definition; the dimension lets go of the copy and holds the definition
    again — the edit measured, the placement still applied once."""
    scene = Scene()
    g = _component(scene)
    hist = History(scene)
    d = Dimension(V(10, 0), V(12, 0), V(0, -1))
    hist.execute(AddDimensionCommand(d))
    scene.begin_group_edit(g)
    hist.execute(MoveVerticesCommand([V(12, 0), V(12, 2)], V(1, 0)))
    assert d.b == V(13, 0)                                # live inside
    scene.end_group_edit()
    assert d.a == V(10, 0) and d.b == V(13, 0)
    assert d.anchor_b.mesh is g.mesh and d.anchor_b.chain == (g,)
    hist.execute(MoveGroupCommand(g, V(0, 5)))
    assert d.b == V(13, 5)


def _close(p, q):
    return (p - q).length() < 1e-5


@pytest.mark.parametrize("make", [_component, _classic_group],
                         ids=["component", "group"])
@pytest.mark.parametrize("motion", ["move", "rotate"])
def test_a_groups_preview_shows_the_dimension_where_the_commit_puts_it(
        make, motion):
    """#621, item 7: Move and Rotate preview a group through a matrix and
    touch no geometry until the commit, so a dimension on it waited for
    the release. ``carried`` draws it through the same matrix — and it
    must land exactly where the committed command then reads it."""
    from core.history import RotateGroupCommand, rotation_matrix
    scene = Scene()
    g = make(scene)
    hist = History(scene)
    d = Dimension(V(10, 0), V(12, 2), V(1, -1))
    hist.execute(AddDimensionCommand(d))
    assert d.ends_riding({id(g)}) == ("a", "b")
    assert d.ends_riding({id(object())}) == ()
    if motion == "move":
        m = QMatrix4x4()
        m.translate(V(3, 4, 1))
        cmd = MoveGroupCommand(g, V(3, 4, 1))
    else:
        m = rotation_matrix(V(11, 1), V(0, 0, 1), 90.0)
        cmd = RotateGroupCommand(g, V(11, 1), V(0, 0, 1), 90.0)
    shown = d.carried(m, d.ends_riding({id(g)}))
    assert d.a == V(10, 0)                         # the original untouched
    hist.execute(cmd)
    assert _close(shown.a, d.a) and _close(shown.b, d.b)
    for p, q in zip(shown.line_points(), d.line_points()):
        assert _close(p, q)
    assert shown.value() == pytest.approx(d.value())


def test_only_the_riding_end_is_carried():
    """A dimension from loose geometry to a group: the group's end comes
    along, the loose end stays."""
    scene = Scene()
    scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    g = _component(scene)
    hist = History(scene)
    d = Dimension(V(1, 0), V(10, 0), V(0, -1))
    hist.execute(AddDimensionCommand(d))
    assert d.ends_riding({id(g)}) == ("b",)
    m = QMatrix4x4()
    m.translate(V(5, 0))
    shown = d.carried(m, ("b",))
    assert shown.a == V(1, 0) and shown.b == V(15, 0)
