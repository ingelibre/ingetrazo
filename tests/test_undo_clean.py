"""Undo/redo of drawn geometry must restore exactly — no orphan split edges or
stray vertices left behind (the line-draw plan can't compose a clean per-op
inverse, so it's undone by snapshot)."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edge, build_add_edges
from core.history import EraseSelectionCommand, History
from core.scene import Scene


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _counts(scene):
    m = scene.mesh
    return (len(m.faces), len(m.edges), len(m.vertices))


def test_undo_divider_leaves_no_orphans():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])
    before = _counts(scene)                       # (1, 4, 4)
    hist.execute(build_add_edge(scene, V(2, 0, 0), V(2, 4, 0)))
    assert hist.undo() is True
    assert _counts(scene) == before               # not (1, 6, 6)


def test_undo_hole_punch_leaves_no_orphan_vertices():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0), V(10, 0), V(10, 10), V(0, 10)])
    before = _counts(scene)
    c = [V(3, 3), V(6, 3), V(6, 6), V(3, 6)]
    hist.execute(build_add_edges(scene, [(c[i], c[(i + 1) % 4]) for i in range(4)]))
    assert hist.undo() is True
    assert _counts(scene) == before               # the 4 inner verts are gone too


def test_redo_reproduces_the_split_exactly():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])
    hist.execute(build_add_edge(scene, V(2, 0, 0), V(2, 4, 0)))
    after = _counts(scene)
    for _ in range(3):
        assert hist.undo() is True
        assert hist.redo() is True
        assert _counts(scene) == after            # redo restores, doesn't re-run


def test_mixed_draw_erase_round_trips():
    scene = Scene()
    hist = History(scene)
    states = [_counts(scene)]
    r = [V(0, 0), V(6, 0), V(6, 6), V(0, 6)]
    hist.execute(build_add_edges(scene, [(r[i], r[(i + 1) % 4]) for i in range(4)]))
    states.append(_counts(scene))
    hist.execute(build_add_edge(scene, V(3, 0, 0), V(3, 6, 0)))
    states.append(_counts(scene))
    e = scene.mesh.find_edge(scene.mesh.vertex_at(V(3, 0, 0)),
                             scene.mesh.vertex_at(V(3, 6, 0)))
    hist.execute(EraseSelectionCommand([e]))
    states.append(_counts(scene))

    for i in range(3):                            # step back through every state
        hist.undo()
        assert _counts(scene) == states[-2 - i]
    for i in range(3):                            # and forward again
        hist.redo()
        assert _counts(scene) == states[i + 1]
