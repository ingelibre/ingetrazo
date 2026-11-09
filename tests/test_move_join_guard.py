# SPDX-License-Identifier: GPL-3.0-or-later
"""A move that lands on other vertices joins them — unless the join would
break a face. Then the whole move is refused and the scene stays as it was:
nothing on the undo stack, nothing in the error log, and the reason kept in
``History.last_rejected`` for the Move tool to say."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.history import (CompoundCommand, History, MoveGroupCommand,
                          MoveVerticesCommand)
from core.mesh import Mesh
from core.scene import Scene
from core.topology import defects_near, new_defects

P = [V(0, 0, 0), V(3, 0, 0), V(3, 4, 0), V(0, 4, 0),
     V(0, 0, 2.6), V(3, 0, 2.6), V(3, 4, 2.6), V(0, 4, 2.6)]


def _box():
    sc = Scene()
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        sc.mesh.add_face([P[i] for i in idx])
    return sc, History(sc)


def _square(sc, x0=0.0):
    sc.mesh.add_face([V(x0, 0, 0), V(x0 + 1, 0, 0),
                      V(x0 + 1, 1, 0), V(x0, 1, 0)])


def _shape(mesh):
    """Positions of every face loop, order-free: equal shapes compare equal
    even when vertex objects were rebuilt."""
    def r(p):
        return (round(p.x(), 5), round(p.y(), 5), round(p.z(), 5))
    return sorted(sorted(r(p) for p in f.vertices) for f in mesh.faces)


def _refused(sc, h, src, delta):
    shape = _shape(sc.mesh)
    counts = (len(sc.mesh.vertices), len(sc.mesh.edges), len(sc.mesh.faces))
    undo_before = len(h.undo_stack)
    cmd = MoveVerticesCommand(src, delta)
    h.execute(cmd)
    assert h.last_rejected, "the join should have been refused"
    assert h.last_error is None
    assert len(h.undo_stack) == undo_before
    assert not cmd.welded
    assert _shape(sc.mesh) == shape
    assert (len(sc.mesh.vertices), len(sc.mesh.edges),
            len(sc.mesh.faces)) == counts
    return h.last_rejected


# ---- joins that stay clean go through -------------------------------------

def test_the_ramp_still_joins():
    sc, h = _box()
    cmd = MoveVerticesCommand([P[5], P[6]], V(0, 0, -2.6))
    h.execute(cmd)
    assert h.last_rejected is None and h.last_error is None
    assert cmd.welded
    assert len(sc.mesh.vertices) == 6
    assert all(len(e.faces) == 2 for e in sc.mesh.edges)


def test_a_corner_onto_its_neighbour_joins():
    sc, h = _box()
    cmd = MoveVerticesCommand([P[4]], P[5] - P[4])
    h.execute(cmd)
    assert h.last_rejected is None and cmd.welded
    assert len(sc.mesh.vertices) == 7


def test_two_squares_side_by_side_share_the_edge():
    sc = Scene()
    h = History(sc)
    _square(sc)
    _square(sc, 2.0)
    cmd = MoveVerticesCommand([V(2, 0, 0), V(2, 1, 0)], V(-1, 0, 0))
    h.execute(cmd)
    assert h.last_rejected is None and cmd.welded
    assert len(sc.mesh.vertices) == 6
    assert sorted(len(e.faces) for e in sc.mesh.edges) == [1] * 6 + [2]


def test_a_move_that_lands_nowhere_is_not_checked(monkeypatch):
    import core.history as history
    sc, h = _box()
    calls = []
    monkeypatch.setattr(history, "defects_near",
                        lambda vs: calls.append(1) or {})
    h.execute(MoveVerticesCommand([P[5], P[6]], V(0, 0, -1.0)))
    assert calls == [] and h.last_rejected is None


def test_undo_and_redo_of_a_clean_join():
    sc, h = _box()
    h.execute(MoveVerticesCommand([P[5], P[6]], V(0, 0, -2.6)))
    assert h.undo()
    assert len(sc.mesh.vertices) == 8
    assert h.redo()
    assert len(sc.mesh.vertices) == 6


# ---- joins that would break a face are refused ----------------------------

def test_a_corner_onto_the_opposite_corner_of_its_face():
    sc = Scene()
    h = History(sc)
    _square(sc)
    why = _refused(sc, h, [V(0, 0, 0)], V(1, 1, 0))
    assert "touches itself" in why


def test_a_top_flattened_onto_the_bottom():
    sc, h = _box()
    why = _refused(sc, h, P[4:], V(0, 0, -2.6))
    assert "doubled" in why


def test_a_square_dropped_onto_another():
    sc = Scene()
    h = History(sc)
    _square(sc)
    _square(sc, 2.0)
    _refused(sc, h, [V(2, 0, 0), V(3, 0, 0), V(3, 1, 0), V(2, 1, 0)],
             V(-2, 0, 0))


def test_a_corner_through_the_box_onto_the_far_corner():
    # Folding leaves triangles lying over the box's own sides.
    sc, h = _box()
    why = _refused(sc, h, [P[4]], P[2] - P[4])
    assert "overlapping" in why


def test_a_refusal_is_not_logged_as_a_failure(monkeypatch):
    sc, h = _box()
    logged = []
    monkeypatch.setattr(h, "_log_failure", lambda *a: logged.append(a))
    _refused(sc, h, P[4:], V(0, 0, -2.6))
    assert logged == []


def test_a_refusal_keeps_the_redo_stack():
    sc, h = _box()
    h.execute(MoveVerticesCommand([P[5]], V(0, 0, 0.5)))
    assert h.undo()
    assert len(h.redo_stack) == 1
    _refused(sc, h, P[4:], V(0, 0, -2.6))
    assert len(h.redo_stack) == 1


def test_the_next_command_clears_the_refusal():
    sc, h = _box()
    _refused(sc, h, P[4:], V(0, 0, -2.6))
    h.execute(MoveVerticesCommand([P[5]], V(0, 0, 0.5)))
    assert h.last_rejected is None


def test_a_group_moved_alongside_goes_back_too():
    sc, h = _box()
    gm = Mesh()
    gm.add_face([V(10, 0, 0), V(11, 0, 0), V(11, 1, 0), V(10, 1, 0)])
    g = Group(gm)
    sc.groups.append(g)

    def where():
        return sorted((round(v.position.x(), 6), round(v.position.y(), 6),
                       round(v.position.z(), 6)) for v in g.mesh.vertices)

    before = where()
    d = V(0, 0, -2.6)
    h.execute(CompoundCommand([MoveGroupCommand(g, d),
                               MoveVerticesCommand(P[4:], d)]))
    assert h.last_rejected and h.undo_stack == []
    assert where() == before


# ---- the detector on its own ----------------------------------------------

def test_old_damage_elsewhere_does_not_block_a_join():
    sc, h = _box()
    # Two faces over one square, far from the move: old damage.
    sc.mesh.add_face([V(20, 0, 0), V(21, 0, 0), V(21, 1, 0), V(20, 1, 0)])
    sc.mesh.add_face([V(20, 0, 0), V(21, 0, 0), V(21, 1, 0), V(20, 1, 0)])
    cmd = MoveVerticesCommand([P[5], P[6]], V(0, 0, -2.6))
    h.execute(cmd)
    assert h.last_rejected is None and cmd.welded


def test_a_clean_box_has_no_defects():
    sc, _h = _box()
    assert not any(defects_near(sc.mesh.vertices).values())


def test_a_bow_tie_is_a_crossed_face():
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    f = next(iter(m.faces))
    # Swap two corners in place: the sides now cross.
    a, b = f.loop[1], f.loop[2]
    pa, pb = V(a.position), V(b.position)
    m.place_vertex(a, V(5, 5, 0))
    m.place_vertex(b, pa)
    m.place_vertex(a, pb)
    assert defects_near(m.vertices)["crossed_face"] == 1


def test_a_partition_inside_a_box_is_not_a_defect():
    sc, _h = _box()
    sc.mesh.add_face([V(1.5, 0, 0), V(1.5, 4, 0), V(1.5, 4, 2.6),
                      V(1.5, 0, 2.6)])
    assert not any(defects_near(sc.mesh.vertices).values())


def test_new_defects_lists_only_what_grew_worst_first():
    before = {"flat_face": 1, "zero_edge": 0}
    after = {"flat_face": 1, "zero_edge": 2, "duplicate_face": 1}
    assert new_defects(before, after) == ["duplicate_face", "zero_edge"]


# ---- the Move tool says what happened -------------------------------------

class _Viewport:
    def __init__(self, history):
        self.history = history
        self.said = []

    def flash_status(self, text, *ms):
        self.said.append(text)


def test_the_tool_says_joined():
    from tools.move import MoveTool
    sc, h = _box()
    cmd = MoveVerticesCommand([P[5], P[6]], V(0, 0, -2.6))
    h.execute(cmd)
    vp = _Viewport(h)
    MoveTool._tell_join(vp, [cmd])
    assert vp.said == ["Vertices joined"]


def test_the_tool_says_why_it_refused():
    from tools.move import MoveTool
    sc, h = _box()
    cmd = MoveVerticesCommand(P[4:], V(0, 0, -2.6))
    h.execute(cmd)
    vp = _Viewport(h)
    MoveTool._tell_join(vp, [cmd])
    assert vp.said == [h.last_rejected]


def test_the_tool_stays_quiet_on_a_plain_move():
    from tools.move import MoveTool
    sc, h = _box()
    cmd = MoveVerticesCommand([P[5]], V(0, 0, 0.5))
    h.execute(cmd)
    vp = _Viewport(h)
    MoveTool._tell_join(vp, [cmd])
    assert vp.said == []
