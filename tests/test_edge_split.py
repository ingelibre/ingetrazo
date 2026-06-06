"""Auto-split of crossing edges — Phase 1, sub-step 2.

When a new edge crosses an existing one, both must split at the intersection
so they share a topological vertex (otherwise the cycle finder can't route a
face through the crossing). Covers:

- the ``segment_intersection`` primitive (X-cross, T-junction, skew reject,
  parallel/collinear reject, out-of-segment reject);
- the ``plan_edge_split`` planner;
- end-to-end via ``build_add_edge`` + ``History`` (X, T, multi-crossing,
  undo restores the original edge, and auto-facing still works).

Headless: pure ``QVector3D`` value types, no ``QApplication`` needed.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edge
from core.geometry import Edge
from core.history import AddEdgeCommand, History
from core.scene import Scene
from core.topology import plan_edge_split, same_position, segment_intersection


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(x, y, z)


def _edge_keyset(scene) -> set:
    """Each edge as an orientation-independent frozenset of rounded endpoints."""
    def k(p):
        return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
    return {frozenset((k(e.a), k(e.b))) for e in scene.edges}


def _has_vertex(scene, p) -> bool:
    return any(
        same_position(v, p) for e in scene.edges for v in (e.a, e.b)
    )


# ---- segment_intersection ---------------------------------------------------

def test_intersection_x_crossing():
    p = segment_intersection(V(0, 0), V(2, 0), V(1, -1), V(1, 1))
    assert p is not None and same_position(p, V(1, 0))


def test_intersection_t_junction():
    # Second segment's endpoint sits on the first segment's interior.
    p = segment_intersection(V(0, 0), V(2, 0), V(1, 0), V(1, 1))
    assert p is not None and same_position(p, V(1, 0))


def test_intersection_shared_endpoint():
    # Touching only at a shared corner still reports the point.
    p = segment_intersection(V(0, 0), V(1, 0), V(1, 0), V(1, 1))
    assert p is not None and same_position(p, V(1, 0))


def test_intersection_no_touch():
    assert segment_intersection(V(0, 0), V(1, 0), V(0, 1), V(1, 1)) is None


def test_intersection_collinear_overlap_is_none():
    # Collinear overlap is a merge problem, not a crossing — out of scope here.
    assert segment_intersection(V(0, 0), V(2, 0), V(1, 0), V(3, 0)) is None


def test_intersection_skew_in_3d_rejected():
    # Cross in XY projection but separated by 1 unit in Z → not a real meeting.
    assert segment_intersection(
        V(0, 0, 0), V(2, 0, 0), V(1, -1, 1), V(1, 1, 1)
    ) is None


def test_intersection_outside_segment_rejected():
    # Lines meet at (1,0) but that point is off the second segment.
    assert segment_intersection(V(0, 0), V(2, 0), V(1, 1), V(1, 2)) is None


# ---- plan_edge_split --------------------------------------------------------

def test_plan_x_crossing_splits_both():
    existing = [Edge(V(0, 0), V(2, 0))]
    new_segs, edge_cuts = plan_edge_split(existing, V(1, -1), V(1, 1))
    # Existing edge is cut at (1,0).
    assert edge_cuts[existing[0]] is not None
    assert same_position(edge_cuts[existing[0]], V(1, 0))
    # New edge is broken into two halves through (1,0).
    assert len(new_segs) == 2
    assert same_position(new_segs[0][1], V(1, 0))


def test_plan_t_junction_splits_existing_only():
    existing = [Edge(V(0, 0), V(2, 0))]
    new_segs, edge_cuts = plan_edge_split(existing, V(1, 0), V(1, 1))
    assert existing[0] in edge_cuts          # existing edge splits
    assert len(new_segs) == 1                # new edge is not split (its endpoint)


def test_plan_no_crossing():
    existing = [Edge(V(0, 0), V(2, 0))]
    new_segs, edge_cuts = plan_edge_split(existing, V(0, 1), V(2, 1))
    assert edge_cuts == {}
    assert new_segs == [(V(0, 1), V(2, 1))]


def test_plan_multiple_crossings_ordered():
    existing = [Edge(V(1, -1), V(1, 1)), Edge(V(2, -1), V(2, 1))]
    new_segs, edge_cuts = plan_edge_split(existing, V(0, 0), V(3, 0))
    assert len(edge_cuts) == 2
    # New edge broken into 3 pieces, cuts ordered along x.
    assert len(new_segs) == 3
    assert same_position(new_segs[0][1], V(1, 0))
    assert same_position(new_segs[1][1], V(2, 0))


# ---- end to end via History -------------------------------------------------

def _scene_with_edge(a, b):
    scene = Scene()
    hist = History(scene)
    hist.execute(AddEdgeCommand(a, b))
    return scene, hist


def test_x_crossing_end_to_end():
    scene, hist = _scene_with_edge(V(0, 0), V(2, 0))
    hist.execute(build_add_edge(scene, V(1, -1), V(1, 1)))
    assert len(scene.edges) == 4
    assert _has_vertex(scene, V(1, 0))
    assert _edge_keyset(scene) == _edge_keyset_from(
        [(V(0, 0), V(1, 0)), (V(1, 0), V(2, 0)),
         (V(1, -1), V(1, 0)), (V(1, 0), V(1, 1))]
    )


def test_t_junction_end_to_end():
    scene, hist = _scene_with_edge(V(0, 0), V(2, 0))
    hist.execute(build_add_edge(scene, V(1, 0), V(1, 1)))
    assert len(scene.edges) == 3
    assert _has_vertex(scene, V(1, 0))


def test_crossing_undo_restores_original():
    scene, hist = _scene_with_edge(V(0, 0), V(2, 0))
    original = scene.edges[0]
    hist.execute(build_add_edge(scene, V(1, -1), V(1, 1)))
    assert hist.undo() is True
    assert scene.edges == [original]


def test_crossing_redo():
    scene, hist = _scene_with_edge(V(0, 0), V(2, 0))
    hist.execute(build_add_edge(scene, V(1, -1), V(1, 1)))
    hist.undo()
    assert hist.redo() is True
    assert len(scene.edges) == 4


def test_no_crossing_is_single_edge_no_split():
    scene, hist = _scene_with_edge(V(0, 0), V(2, 0))
    hist.execute(build_add_edge(scene, V(0, 1), V(2, 1)))
    assert len(scene.edges) == 2  # untouched original + the new edge


def test_closing_loop_still_auto_faces():
    """Auto-face regression: a chain of four edges that closes a square
    should still produce exactly one face through the cycle finder."""
    scene = Scene()
    hist = History(scene)
    chain = [V(0, 0), V(1, 0), V(1, 1), V(0, 1), V(0, 0)]
    for i in range(4):
        hist.execute(build_add_edge(scene, chain[i], chain[i + 1]))
    assert len(scene.faces) == 1
    assert len(scene.edges) == 4


# ---- helper -----------------------------------------------------------------

def _edge_keyset_from(segments):
    def k(p):
        return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))
    return {frozenset((k(a), k(b))) for a, b in segments}
