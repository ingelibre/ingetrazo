# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Circle, Polygon, Rotated Rectangle and Arc tools — the geometry they commit."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.arc import ArcTool, ThreePointArcTool
from tools.base import ToolContext
from tools.circle import CircleTool, PolygonTool
from tools.rotated_rectangle import RotatedRectangleTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _VP:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, text, msec=2500):
        pass


def _ctx(vp, world):
    return ToolContext(viewport=vp, world=world, screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


# ---- Circle / Polygon ----------------------------------------------------------

def test_circle_commits_24gon_at_radius():
    scene = Scene()
    vp = _VP(scene)
    tool = CircleTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))     # centre
    tool.on_hover(_ctx(vp, V(2, 0, 0)))     # radius 2
    tool.on_click(_ctx(vp, V(2, 0, 0)))     # commit
    faces = scene.mesh.faces
    assert len(faces) == 1
    assert len(faces[0].vertices) == 24
    for v in faces[0].vertices:
        assert abs(v.length() - 2.0) < 1e-4   # all on the radius-2 circle (z=0)


def test_polygon_commits_hexagon():
    scene = Scene()
    vp = _VP(scene)
    tool = PolygonTool()
    tool.on_click(_ctx(vp, V(1, 1, 0)))
    tool.on_hover(_ctx(vp, V(3, 1, 0)))     # radius 2 toward +X
    tool.on_click(_ctx(vp, V(3, 1, 0)))
    f = scene.mesh.faces[0]
    assert len(f.vertices) == 6
    # one vertex points toward the cursor (+X from the centre).
    assert any((v - V(1, 1, 0)).x() > 1.99 for v in f.vertices)


def test_circle_radius_via_vcb():
    scene = Scene()
    vp = _VP(scene)
    tool = CircleTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_hover(_ctx(vp, V(1, 0, 0)))     # direction set, radius will be typed
    assert tool.on_value(vp, 5.0) is True
    f = scene.mesh.faces[0]
    assert all(abs(v.length() - 5.0) < 1e-4 for v in f.vertices)


def test_circle_tangent_to_edge_vertex_commits(  # circc.igz report (2026-07-12)
):
    """A circle whose rim snaps onto an existing edge endpoint must commit.

    Float32 puts the tangent vertex a hair past the edge, so the adjacent
    circle segments graze it ~1e-5 from the shared vertex. The rounded
    same_position key can miss that pair across a rounding cell, planning a
    sub-weld split that add_edge rejects as degenerate — the whole circle
    then rolled back ("degenerate edge: endpoints weld to one vertex")."""
    scene = Scene()
    vp = _VP(scene)
    from core.edits import build_add_edge
    # Exact float32-sensitive coordinates from the user's file: a 36×18 slab
    # whose bottom edge is split at the future tangent point.
    t = V(3.639848232269287, -18.0)
    for a, b in ((V(0, 0), V(36, 0)), (V(36, 0), V(36, -18)),
                 (V(36, -18), t), (t, V(0, -18)), (V(0, -18), V(0, 0))):
        vp.history.execute(build_add_edge(scene, a, b))
    tool = CircleTool()
    center = V(3.639848232269287, -14.399999618530273)
    tool.on_click(_ctx(vp, center))
    tool.on_hover(_ctx(vp, t))
    tool.on_click(_ctx(vp, t))              # rim snapped to the edge vertex
    assert vp.history.last_error is None
    # The disc face exists (24-gon area) and no degenerate slivers were left.
    disc = 0.5 * 24 * 3.6 * 3.6 * math.sin(2 * math.pi / 24)
    areas = sorted(f.area() for f in scene.mesh.faces)
    assert any(abs(a - disc) < 0.01 for a in areas)
    assert all((e.b - e.a).length() > 1e-4 for e in scene.mesh.edges)


# ---- Rotated rectangle ---------------------------------------------------------

def _has_corner(face, p, tol=1e-4):
    return any((v - p).length() < tol for v in face.vertices)


def test_rotated_rectangle_axis_aligned_case():
    scene = Scene()
    vp = _VP(scene)
    tool = RotatedRectangleTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))     # corner 1
    tool.on_click(_ctx(vp, V(4, 0, 0)))     # base edge +X, length 4
    tool.on_hover(_ctx(vp, V(2, 3, 0)))     # width 3 toward +Y
    tool.on_click(_ctx(vp, V(2, 3, 0)))     # commit
    f = scene.mesh.faces[0]
    assert len(f.vertices) == 4
    for c in (V(0, 0, 0), V(4, 0, 0), V(4, 3, 0), V(0, 3, 0)):
        assert _has_corner(f, c)


def test_rotated_rectangle_diagonal_base_is_rotated():
    scene = Scene()
    vp = _VP(scene)
    tool = RotatedRectangleTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(3, 3, 0)))     # base at 45°, length 3√2
    # width 1 perpendicular; perp = Z × (1,1,0)/√2 = (-1,1,0)/√2
    perp = V(-1, 1, 0)
    perp = perp / perp.length()
    cursor = V(3, 3, 0) + perp * 1.0
    tool.on_hover(_ctx(vp, cursor))
    tool.on_click(_ctx(vp, cursor))
    f = scene.mesh.faces[0]
    assert len(f.vertices) == 4
    assert _has_corner(f, V(0, 0, 0))
    assert _has_corner(f, V(3, 3, 0))
    assert _has_corner(f, V(3, 3, 0) + perp)        # base corner + width
    assert _has_corner(f, perp)                      # start corner + width


# ---- Arc -----------------------------------------------------------------------

def test_arc_points_span_chord_and_bulge():
    tool = ArcTool()
    tool.start_point = V(0, 0, 0)
    tool.end_point = V(4, 0, 0)
    tool.work_plane = None
    pts = tool._points(V(2, 1, 0))              # bulge 1 toward +Y
    assert len(pts) == 17                        # _SEGMENTS + 1
    assert (pts[0] - V(0, 0, 0)).length() < 1e-6
    assert (pts[-1] - V(4, 0, 0)).length() < 1e-6
    # max bulge (perpendicular extent) reaches ~1 at the apex.
    assert abs(max(p.y() for p in pts) - 1.0) < 1e-4


def test_arc_flat_bulge_is_straight_chord():
    tool = ArcTool()
    tool.start_point = V(0, 0, 0)
    tool.end_point = V(4, 0, 0)
    tool.work_plane = None
    pts = tool._points(V(2, 0, 0))               # ~zero bulge
    assert pts == [V(0, 0, 0), V(4, 0, 0)]


def test_arc_commits_polyline_edges():
    scene = Scene()
    vp = _VP(scene)
    tool = ArcTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(4, 0, 0)))
    tool.on_hover(_ctx(vp, V(2, 1, 0)))
    tool.on_click(_ctx(vp, V(2, 1, 0)))
    assert len(scene.mesh.edges) == 16           # _SEGMENTS edges
    assert not any(e.soft for e in scene.mesh.edges)  # the drawn arc is visible


def test_3point_arc_passes_through_all_three():
    scene = Scene()
    vp = _VP(scene)
    tool = ThreePointArcTool()
    tool.on_click(_ctx(vp, V(0, 0, 0)))          # start
    tool.on_click(_ctx(vp, V(2, 2, 0)))          # through
    tool.on_hover(_ctx(vp, V(4, 0, 0)))
    pts = tool._points(V(4, 0, 0))
    assert (pts[0] - V(0, 0, 0)).length() < 1e-6
    assert (pts[-1] - V(4, 0, 0)).length() < 1e-6
    # the arc passes through the mid point (some sample lands on it)
    assert any((p - V(2, 2, 0)).length() < 1e-4 for p in pts)


# ---- Side count + soft (clean) edges ------------------------------------------

def test_typed_number_before_centre_sets_sides():
    scene = Scene()
    vp = _VP(scene)
    tool = PolygonTool()
    assert tool.on_value(vp, 8.0) is True        # 8 sides, before any click
    assert tool.sides == 8
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_hover(_ctx(vp, V(2, 0, 0)))
    tool.on_click(_ctx(vp, V(2, 0, 0)))
    assert len(scene.mesh.faces[0].vertices) == 8   # octagon


def test_drawn_circle_outline_is_visible():
    # A flat circle/polygon shows its outline (no edge is hidden); only a swept
    # curve's facets are softened later, by Push/Pull.
    scene = Scene()
    vp = _VP(scene)
    c = CircleTool()
    c.on_click(_ctx(vp, V(0, 0, 0)))
    c.on_hover(_ctx(vp, V(2, 0, 0)))
    c.on_click(_ctx(vp, V(2, 0, 0)))
    assert not any(e.soft for e in scene.mesh.edges)   # the circle line stays


def test_pushed_circle_hides_facets_but_keeps_the_circle_line():
    # A circle extruded: the vertical facet seams are soft (smooth side), but the
    # top/bottom circle outline edges stay visible. A polygon keeps every edge.
    import tests.test_fuzz_engine as F
    scene = Scene()
    vp = _VP(scene)
    c = CircleTool()
    c.on_click(_ctx(vp, V(0, 0, 0)))
    c.on_hover(_ctx(vp, V(2, 0, 0)))
    c.on_click(_ctx(vp, V(2, 0, 0)))
    circ = next(f for f in scene.mesh.faces if len(f.vertices) == 24)
    F._push(scene, vp.history, circ, 3.0 if circ.normal().z() > 0 else -3.0)
    soft = [e for e in scene.mesh.edges if e.soft]
    hard = [e for e in scene.mesh.edges if not e.soft]
    assert len(soft) == 24      # the 24 vertical facet seams are hidden
    assert len(hard) == 48      # the top + bottom circle outlines stay visible
    # the hidden ones are the vertical seams (run along Z)
    assert all(abs((e.b - e.a).normalized().z()) > 0.99 for e in soft)

    scene2 = Scene()
    vp2 = _VP(scene2)
    p = PolygonTool()
    p.on_click(_ctx(vp2, V(0, 0, 0)))
    p.on_hover(_ctx(vp2, V(2, 0, 0)))
    p.on_click(_ctx(vp2, V(2, 0, 0)))
    poly = next(f for f in scene2.mesh.faces if len(f.vertices) == 6)
    F._push(scene2, vp2.history, poly, 3.0 if poly.normal().z() > 0 else -3.0)
    assert not any(e.soft for e in scene2.mesh.edges)  # hexagonal prism stays hard


def test_cylinder_side_is_one_surface():
    # Clicking a side quad of a cylinder should act on the whole curved surface
    # (24 quads joined by soft edges), while the caps (hard-edged) stay separate.
    import tests.test_fuzz_engine as F
    scene = Scene()
    vp = _VP(scene)
    c = CircleTool()
    c.on_click(_ctx(vp, V(0, 0, 0)))
    c.on_hover(_ctx(vp, V(2, 0, 0)))
    c.on_click(_ctx(vp, V(2, 0, 0)))
    circ = next(f for f in scene.mesh.faces if len(f.vertices) == 24)
    F._push(scene, vp.history, circ, 3.0 if circ.normal().z() > 0 else -3.0)
    side = next(f for f in scene.mesh.faces if len(f.vertices) == 4)
    assert len(scene.mesh.surface_of(side)) == 24    # whole curved side
    cap = next(f for f in scene.mesh.faces if len(f.vertices) == 24)
    assert len(scene.mesh.surface_of(cap)) == 1      # a cap is its own surface


def test_deleting_cylinder_side_leaves_no_dangling_seams():
    # Erasing the curved side surface prunes its hidden vertical seams — no stray
    # vertical lines remain, just the two cap circles.
    import tests.test_fuzz_engine as F
    from core.history import EraseSelectionCommand
    scene = Scene()
    vp = _VP(scene)
    c = CircleTool()
    c.on_click(_ctx(vp, V(0, 0, 0)))
    c.on_hover(_ctx(vp, V(2, 0, 0)))
    c.on_click(_ctx(vp, V(2, 0, 0)))
    circ = next(f for f in scene.mesh.faces if len(f.vertices) == 24)
    F._push(scene, vp.history, circ, 3.0 if circ.normal().z() > 0 else -3.0)
    side = next(f for f in scene.mesh.faces if len(f.vertices) == 4)
    surface = scene.mesh.surface_of(side)

    vp.history.execute(EraseSelectionCommand([], surface))
    assert len(scene.mesh.faces) == 2                       # the two caps remain
    assert not any(e.soft and not e.faces for e in scene.mesh.edges)  # no dangle
    vp.history.undo()
    assert len(scene.mesh.faces) == 26                      # restored


def test_box_face_is_its_own_surface():
    import tests.test_fuzz_engine as F
    scene = Scene()
    hist = History(scene)
    F._draw_rect(scene, hist, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    f = scene.mesh.faces[0]
    F._push(scene, hist, f, 3.0 if f.normal().z() > 0 else -3.0)
    for face in scene.mesh.faces:
        assert scene.mesh.surface_of(face) == [face]  # no soft edges anywhere


def test_soft_survives_snapshot_and_igz(tmp_path):
    import tests.test_fuzz_engine as F
    from formats import igz
    scene = Scene()
    vp = _VP(scene)
    c = CircleTool()
    c.on_click(_ctx(vp, V(0, 0, 0)))
    c.on_hover(_ctx(vp, V(2, 0, 0)))
    c.on_click(_ctx(vp, V(2, 0, 0)))
    circ = next(f for f in scene.mesh.faces if len(f.vertices) == 24)
    F._push(scene, vp.history, circ, 3.0 if circ.normal().z() > 0 else -3.0)
    n_soft = sum(1 for e in scene.mesh.edges if e.soft)
    assert n_soft == 24
    vp.history.undo()
    vp.history.redo()
    assert sum(1 for e in scene.mesh.edges if e.soft) == n_soft
    path = tmp_path / "cyl.igz"
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    assert sum(1 for e in loaded.mesh.edges if e.soft) == n_soft


# ---- Splitting a painted face keeps its paint -------------------------------

_TEX = {"path": "/tmp/piedra.jpg", "sw": 0.5, "sh": 0.5,
        "uvw": [2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0]}


def _painted_square(scene, hist, size=4.0, z=0.0):
    from core.edits import build_add_edges
    from core.history import AddFaceCommand
    ring = [V(0, 0, z), V(size, 0, z), V(size, size, z), V(0, size, z)]
    hist.execute(build_add_edges(
        scene, [(ring[i], ring[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(ring))]))
    face = scene.faces[0]
    face.attrs.update({"mat": "Piedra", "texture": dict(_TEX)})
    return face


def test_a_line_across_a_painted_face_keeps_the_paint_on_both_halves():
    # Drawing a line across a textured rectangle wiped the texture off both
    # halves (Marco, 2026-08-27): the chord split deleted the mother and added
    # two bare faces. The halves ARE the mother, cut in two.
    from core.edits import build_add_edges

    scene = Scene()
    hist = History(scene)
    _painted_square(scene, hist)
    hist.execute(build_add_edges(scene, [(V(2, 0), V(2, 4))]))

    assert len(scene.faces) == 2
    for f in scene.faces:
        assert f.attrs.get("mat") == "Piedra"
        t = f.attrs.get("texture")
        assert t is not None and t["path"] == _TEX["path"]
        # Verbatim: both halves stay on the mother's world→UV map, so the
        # image runs straight across the cut instead of restarting.
        assert t["uvw"] == _TEX["uvw"]


def test_the_split_survives_undo():
    from core.edits import build_add_edges

    scene = Scene()
    hist = History(scene)
    _painted_square(scene, hist)
    hist.execute(build_add_edges(scene, [(V(2, 0), V(2, 4))]))
    assert hist.undo() is True
    assert len(scene.faces) == 1
    assert scene.faces[0].attrs.get("mat") == "Piedra"


def test_a_line_across_one_face_of_a_painted_box_keeps_every_face_painted():
    # The cut also inserts a collinear vertex into the two side faces whose
    # top edge it lands on; those are the SAME faces and must keep their paint
    # too (they lost it as well — four faces went bare, not two).
    from core.edits import build_add_edges

    scene = Scene()
    hist = History(scene)
    z = 3.0
    c = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0),
         V(0, 0, z), V(4, 0, z), V(4, 4, z), V(0, 4, z)]
    for q in [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
              (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        scene.mesh.add_face([c[i] for i in q])
    for f in scene.faces:
        f.attrs.update({"mat": "Piedra", "texture": dict(_TEX)})

    hist.execute(build_add_edges(scene, [(V(2, 0, z), V(2, 4, z))]))

    assert len(scene.faces) == 7               # the top split in two
    bare = [f for f in scene.faces if not f.attrs.get("texture")]
    assert bare == [], "%d faces came out bare" % len(bare)


def test_a_door_drawn_down_to_the_floor_edge_takes_the_wall_texture():
    # Three edges plus the wall's own bottom edge close the door: it is carved
    # out of the wall (AddFaceCommand's direction C). Only the REMAINDER
    # inherited, so the door came out bare (Marco, 2026-08-27).
    from core.edits import build_add_edges
    from core.history import AddFaceCommand

    scene = Scene()
    hist = History(scene)
    wall = [V(0, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)]
    hist.execute(build_add_edges(
        scene, [(wall[i], wall[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(wall))]))
    scene.faces[0].attrs.update({"mat": "Piedra", "texture": dict(_TEX)})

    door = [V(1, 0, 0), V(1, 0, 2), V(2.5, 0, 2), V(2.5, 0, 0)]
    hist.execute(build_add_edges(scene, [(door[0], door[1]), (door[1], door[2]),
                                         (door[2], door[3])]))

    assert len(scene.faces) == 2
    for f in scene.faces:
        assert f.attrs.get("mat") == "Piedra"
        t = f.attrs.get("texture")
        assert t is not None, "%d-vertex face came out bare" % len(f.vertices)
        # Coplanar with the wall, so the same map: the image runs straight
        # across the door's outline instead of restarting inside it.
        assert t["uvw"] == _TEX["uvw"]


def test_a_rectangle_drawn_inside_a_painted_face_takes_its_paint_too():
    # Same gesture, not touching the boundary: the new face falls strictly
    # inside the mother (direction A, which punches a hole in her).
    from core.edits import build_add_edges
    from core.history import AddFaceCommand

    scene = Scene()
    hist = History(scene)
    _painted_square(scene, hist, size=6.0)
    inner = [V(2, 2), V(4, 2), V(4, 4), V(2, 4)]
    hist.execute(build_add_edges(
        scene, [(inner[i], inner[(i + 1) % 4]) for i in range(4)]))

    small = min(scene.faces, key=lambda f: f.area())
    assert small.attrs.get("mat") == "Piedra"
    assert small.attrs.get("texture", {}).get("uvw") == _TEX["uvw"]


def test_a_face_drawn_with_its_own_paint_keeps_it():
    # Inheritance fills gaps only: whatever the face already declares wins.
    from core.history import AddFaceCommand

    scene = Scene()
    hist = History(scene)
    _painted_square(scene, hist, size=6.0)
    inner = [V(2, 2), V(4, 2), V(4, 4), V(2, 4)]
    hist.execute(AddFaceCommand(inner, attrs={"mat": "Vidrio"}))

    small = min(scene.faces, key=lambda f: f.area())
    assert small.attrs["mat"] == "Vidrio"          # its own, not the mother's
    assert small.attrs.get("texture", {}).get("uvw") == _TEX["uvw"]
