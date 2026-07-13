# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A.4 — hand-drawn subdivisions survive the plane rebuild.

``apply_rebuild`` used to union every region of a touched plane, dissolving a
diagonal the user drew on a wall whenever a push landed anything on that
plane. Now the push's own rims (captured by position at fixpoint entry) are
the only edges allowed to dissolve: any other face-bearing plane edge is the
user's structure and survives as a union boundary. The op's seams — a stacked
strip's belt, a flush landing's contact line — still merge away.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edge
from core.history import History
from core.orient import is_closed, orient_outward
from core.scene import Scene
from tests.test_fuzz_engine import V, _draw_rect, _push, _up


def _key(p):
    return (round(p.x(), 6), round(p.y(), 6), round(p.z(), 6))


def _cube_with_chord():
    """Cube with a hand-drawn chord splitting the y=0 wall in two."""
    scene = Scene()
    hist = History(scene)
    _draw_rect(scene, hist, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    f = scene.mesh.faces[0]
    _push(scene, hist, f, _up(f, 3.0))
    hist.execute(build_add_edge(scene, V(0, 0, 1), V(4, 0, 2)))
    return scene, hist


def _chord_edges(mesh):
    return [e for e in mesh.edges
            if {_key(e.a), _key(e.b)} == {(0.0, 0.0, 1.0), (4.0, 0.0, 2.0)}]


def test_chord_splits_the_wall():
    scene, _hist = _cube_with_chord()
    walls = [f for f in scene.mesh.faces
             if all(abs(v.y()) < 1e-9 for v in f.vertices)]
    assert len(walls) == 2
    assert len(_chord_edges(scene.mesh)) == 1


def test_chord_survives_bump_on_same_wall():
    # A bump pushed out elsewhere on the wall rebuilds the wall plane; the
    # chord must survive it (the DoD's "diagonal sobrevive al re-push").
    scene, hist = _cube_with_chord()
    m = scene.mesh
    _draw_rect(scene, hist,
               [V(1, 0, 0.2), V(2, 0, 0.2), V(2, 0, 0.8), V(1, 0, 0.8)], [])
    rect = next(f for f in m.faces if len(f.vertices) == 4 and not f.holes
                and all(abs(v.y()) < 1e-9 for v in f.vertices)
                and f.area() < 0.7)
    n = rect.normal()
    _push(scene, hist, rect, 0.5 if n.y() < 0 else -0.5)
    assert len(_chord_edges(m)) == 1, "user chord dissolved by the rebuild"
    assert is_closed(m)
    assert orient_outward(m) == []


def test_chord_survives_ctrl_stack_on_top():
    # A Ctrl-stack on the cube top lands strips on the wall planes; the chord
    # below must survive while the stack's own belt machinery works as usual.
    scene, hist = _cube_with_chord()
    m = scene.mesh
    top = next(f for f in m.faces
               if all(abs(v.z() - 3) < 1e-9 for v in f.vertices))
    _push(scene, hist, top, 1.0, keep_base=True)
    assert len(_chord_edges(m)) == 1, "user chord dissolved by the Ctrl stack"
    assert is_closed(m)
    assert orient_outward(m) == []


def test_stacked_strip_seam_still_dissolves():
    # The op's own seams keep merging: extending a bump leaves its flank one
    # face, not a strip-stacked pair (the DoD's "el seam del strip sí se
    # disuelve").
    scene = Scene()
    hist = History(scene)
    _draw_rect(scene, hist, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    f = scene.mesh.faces[0]
    _push(scene, hist, f, _up(f, 3.0))
    m = scene.mesh
    _draw_rect(scene, hist, [V(1, 0, 1), V(2, 0, 1), V(2, 0, 2), V(1, 0, 2)],
               [])
    rect = next(fc for fc in m.faces if len(fc.vertices) == 4 and not fc.holes
                and all(abs(v.y()) < 1e-9 for v in fc.vertices)
                and 0.9 < fc.centroid().x() < 2.1)
    n = rect.normal()
    _push(scene, hist, rect, 0.5 if n.y() < 0 else -0.5)
    cap = next(fc for fc in m.faces
               if all(abs(v.y() + 0.5) < 1e-6 for v in fc.vertices))
    n = cap.normal()
    _push(scene, hist, cap, 0.5 if n.y() < 0 else -0.5)   # extend the bump
    flanks = [fc for fc in m.faces
              if all(abs(v.x() - 2) < 1e-9 for v in fc.vertices)
              and fc.centroid().y() < -0.01]
    assert len(flanks) == 1, "the stacked strip seam did not dissolve"
    assert is_closed(m)


def test_chord_attrs_partition_survives_push():
    # A.3 meets A.4: each side of the chord can carry its own material and
    # both survive a push that rebuilds the wall plane.
    scene, hist = _cube_with_chord()
    m = scene.mesh
    lower = next(f for f in m.faces
                 if all(abs(v.y()) < 1e-9 for v in f.vertices)
                 and f.centroid().z() < 1.4)
    upper = next(f for f in m.faces
                 if all(abs(v.y()) < 1e-9 for v in f.vertices)
                 and f is not lower)
    lower.attrs = {"color": "zocalo"}
    upper.attrs = {"color": "muro"}
    top = next(f for f in m.faces
               if all(abs(v.z() - 3) < 1e-9 for v in f.vertices))
    _push(scene, hist, top, 1.0, keep_base=True)  # rebuilds the wall plane
    colors = {f.attrs.get("color") for f in m.faces
              if all(abs(v.y()) < 1e-9 for v in f.vertices)}
    assert {"zocalo", "muro"} <= colors


# ---- Lines drawn on a populated plane subdivide it (aa.igz plaza, 2026-07-12)


def _slab_with_inner_rect():
    """A 6×4×1 slab whose top face carries a rect subdivision at x 2..4."""
    scene = Scene()
    hist = History(scene)
    _draw_rect(scene, hist, [V(0, 0), V(6, 0), V(6, -4), V(0, -4)], [])
    f = scene.mesh.faces[0]
    _push(scene, hist, f, _up(f, 1.0))
    _draw_rect(scene, hist,
               [V(2, -1, 1), V(4, -1, 1), V(4, -3, 1), V(2, -3, 1)], [])
    return scene, hist


def _top_faces(mesh):
    return [f for f in mesh.faces
            if all(abs(v.z() - 1.0) < 1e-6 for v in f.vertices)]


def test_line_grazing_hole_boundary_subdivides_not_stacks():
    # A line across the top from the outline to the outline, collinear with
    # the inner rect's left edge, must fence the top into left/right regions —
    # not stack a flipped duplicate over the mother (the aa.igz failure).
    scene, hist = _slab_with_inner_rect()
    m = scene.mesh
    hist.execute(build_add_edge(scene, V(2, 0, 1), V(2, -4, 1)))
    assert hist.last_error is None
    tops = _top_faces(m)
    areas = sorted(round(f.area(), 2) for f in tops)
    # left 2×4=8, inner rect 2×2=4, right region 6×4−8−4=12
    assert areas == [4.0, 8.0, 12.0]
    assert all(f.normal().z() > 0.99 for f in tops), "a top face came out flipped"
    assert is_closed(m)


def test_deleting_the_fence_line_fuses_the_plane_back():
    from core.history import EraseSelectionCommand
    scene, hist = _slab_with_inner_rect()
    m = scene.mesh
    hist.execute(build_add_edge(scene, V(2, 0, 1), V(2, -4, 1)))
    fence = [e for e in m.edges
             if abs(e.a.x() - 2) < 1e-6 and abs(e.b.x() - 2) < 1e-6
             and abs(e.a.z() - 1) < 1e-6 and abs(e.b.z() - 1) < 1e-6
             and not (min(e.a.y(), e.b.y()) >= -3.0 - 1e-6
                      and max(e.a.y(), e.b.y()) <= -1.0 + 1e-6)]
    assert fence, "fence pieces outside the rect edge expected"
    hist.execute(EraseSelectionCommand(fence))
    assert hist.last_error is None
    tops = _top_faces(m)
    big = [f for f in tops if f.area() > 15]
    assert big, "the mother top face must survive and re-fuse"
    assert len(big[0].holes) == 1              # the inner rect is a hole again
    assert is_closed(m)


# ---- Slit edges: a fence line joining an inner boundary to the outline
# (ss.igz report, 2026-07-12) -------------------------------------------------


def _flat_ring_with_fence():
    """30×20 mother + 10×8 inner rect + a fence line from the inner rect's
    corner (10,6) to the outline (10,0). The plane rebuild traces the mother
    as ONE cut-open ring walking the fence twice (a slit edge)."""
    from core.history import AddFaceCommand
    from core.edits import build_add_edges

    scene = Scene()
    hist = History(scene)

    def rect(a, c):
        cs = [V(a[0], a[1]), V(c[0], a[1]), V(c[0], c[1]), V(a[0], c[1])]
        segs = [(cs[i], cs[(i + 1) % 4]) for i in range(4)]
        hist.execute(build_add_edges(scene, segs, detect_faces=False,
                                     extra=[AddFaceCommand(list(cs))]))

    rect((0, 0), (30, 20))
    rect((10, 6), (24, 14))
    hist.execute(build_add_edge(scene, V(10, 6), V(10, 0)))
    return scene, hist


def _slit_edges(mesh):
    return [e for e in mesh.edges
            if len(e.faces) == 2 and e.faces[0] is e.faces[1]]


def test_deleting_a_slit_edge_keeps_the_face():
    # Erasing the fence line used to dissolve the ring face "with itself":
    # the face vanished and the line stayed. It must be the other way around.
    from core.history import EraseSelectionCommand
    scene, hist = _flat_ring_with_fence()
    m = scene.mesh
    slits = _slit_edges(m)
    assert len(slits) == 1
    hist.execute(EraseSelectionCommand(slits))
    assert hist.last_error is None
    assert not _slit_edges(m)                     # the line is gone
    big = [f for f in m.faces if f.area() > 400]
    assert big, "the ring face must survive the fence deletion"
    assert len(big[0].holes) == 1                 # back to outer + hole
    assert hist.undo() is True                    # exact round-trip
    assert len(_slit_edges(m)) == 1


def test_deleting_one_piece_of_a_two_piece_fence():
    # Only the erased piece goes; the other survives as a free edge on the
    # healed face (SketchUp).
    from core.history import AddFaceCommand
    from core.edits import build_add_edges
    from core.history import EraseSelectionCommand

    scene = Scene()
    hist = History(scene)

    def rect(a, c):
        cs = [V(a[0], a[1]), V(c[0], a[1]), V(c[0], c[1]), V(a[0], c[1])]
        segs = [(cs[i], cs[(i + 1) % 4]) for i in range(4)]
        hist.execute(build_add_edges(scene, segs, detect_faces=False,
                                     extra=[AddFaceCommand(list(cs))]))

    rect((0, 0), (30, 20))
    rect((10, 6), (24, 14))
    hist.execute(build_add_edge(scene, V(10, 6), V(10, 3)))   # fence, 2 strokes
    hist.execute(build_add_edge(scene, V(10, 3), V(10, 0)))
    m = scene.mesh
    lower = [e for e in _slit_edges(m) if max(e.a.y(), e.b.y()) < 3.01]
    assert len(lower) == 1
    hist.execute(EraseSelectionCommand(lower))
    assert hist.last_error is None
    big = [f for f in m.faces if f.area() > 400]
    assert big and len(big[0].holes) == 1
    upper = [e for e in m.edges if not e.faces
             and abs(e.a.x() - 10) < 1e-6 and abs(e.b.x() - 10) < 1e-6]
    assert upper, "the untouched fence piece must survive as a free edge"
