# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""GuideCircle — the analytic circular construction guide.

Stored exactly (centre + plane normal + radius), scaffolded like a guide
line, and round-tripped through the .igz with its own ``kind``.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.guide import Guide, GuideCircle, guide_from_dict


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def test_a_circle_guide_is_analytic_not_a_line():
    c = GuideCircle(V(1, 2, 3), V(0, 0, 2), 1.5)
    assert c.is_circle is True
    assert c.is_line is False
    assert c.center == V(1, 2, 3)
    assert (c.normal - V(0, 0, 1)).length() < 1e-9      # the normal is unit
    assert c.radius == 1.5


def test_the_duck_typed_point_is_the_centre():
    c = GuideCircle(V(1, 2), V(0, 0, 1), 3.0)
    assert c.point == V(1, 2)
    c.point = V(4, 5)
    assert c.center == V(4, 5)
    assert c.direction is c.normal


def test_is_finite_rejects_nan():
    assert GuideCircle(V(0, 0), V(0, 0, 1), 1.0).is_finite()
    assert not GuideCircle(V(float("nan"), 0), V(0, 0, 1), 1.0).is_finite()
    assert not GuideCircle(V(0, 0), V(0, 0, 1), float("nan")).is_finite()


def test_dict_round_trip_keeps_everything():
    c = GuideCircle(V(3, 4, 5), V(1, 0, 0), 2.5, layer="Guías")
    back = GuideCircle.from_dict(c.to_dict())
    assert (back.center - c.center).length() < 1e-12
    assert (back.normal - c.normal).length() < 1e-12
    assert back.radius == 2.5
    assert back.layer == "Guías"


def test_guide_from_dict_dispatches_on_kind():
    circ = guide_from_dict({"kind": "circle", "center": [0, 0, 0],
                            "normal": [0, 0, 1], "radius": 2.0})
    assert isinstance(circ, GuideCircle)
    line = guide_from_dict({"point": [0, 0, 0], "direction": [1, 0, 0]})
    assert isinstance(line, Guide) and not isinstance(line, GuideCircle)
    assert line.is_line is True


def test_a_circle_guide_survives_the_igz(tmp_path):
    from core.scene import Scene
    from formats.igz import load_into, save_scene

    scene = Scene()
    scene.guides.append(GuideCircle(V(1, 2, 3), V(0, 1, 0), 4.0))
    path = tmp_path / "circle.igz"
    save_scene(scene, path)

    scene2 = Scene()
    load_into(scene2, path)
    assert len(scene2.guides) == 1
    g = scene2.guides[0]
    assert isinstance(g, GuideCircle)
    assert (g.center - V(1, 2, 3)).length() < 1e-6
    assert (g.normal - V(0, 1, 0)).length() < 1e-6
    assert g.radius == 4.0


def test_closest_on_circle_is_exact():
    from core.snap import _closest_on_circle
    circ = GuideCircle(V(0, 0, 0), V(0, 0, 1), 2.0)

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    px = w2p(V(2.05, 0.0, 0.0))
    d, rim = _closest_on_circle(circ, V(2.05, 0.0, 0.0), px[0], px[1], w2p, 14.0)
    assert abs(d - 5.0) < 1e-3                    # 0.05 m off the rim, 100 px/m
    assert (rim - V(2.0, 0.0, 0.0)).length() < 1e-4


def test_compute_snap_lands_on_a_guide_circles_rim():
    import math
    from types import SimpleNamespace
    from core.snap import compute_snap
    circ = GuideCircle(V(0, 0, 0), V(0, 0, 1), 2.0)

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    # 45°: on the rim, but not a quadrant, so the generic rim snap fires.
    cursor = V(1.45, 1.45, 0.0)
    snap = compute_snap(
        candidate_world=cursor, candidate_pixel=w2p(cursor),
        scene=SimpleNamespace(edges=[], circles=[circ]), world_to_pixel=w2p,
        threshold_px=9.0, edge_threshold_px=14.0,
        project_onto_line=lambda s, d: s + d * QVector3D.dotProduct(cursor - s, d))
    assert snap.kind == "on_circle"
    r = math.sqrt(2.0)                     # the rim point at 45°, radius 2
    assert (snap.point - V(r, r, 0.0)).length() < 1e-3


def test_compute_snap_lands_on_a_guide_circles_center():
    from types import SimpleNamespace
    from core.snap import compute_snap
    center = V(1.0, 2.0, 0.0)
    center_edge = SimpleNamespace(a=center, b=center, center=True)

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    cursor = V(1.02, 2.0, 0.0)
    snap = compute_snap(
        candidate_world=cursor, candidate_pixel=w2p(cursor),
        scene=SimpleNamespace(edges=[center_edge], circles=[]),
        world_to_pixel=w2p, threshold_px=9.0, edge_threshold_px=14.0,
        project_onto_line=lambda s, d: s + d * QVector3D.dotProduct(cursor - s, d))
    assert snap.kind == "center"
    assert (snap.point - center).length() < 1e-6


def test_two_guide_circles_intersect_at_the_true_chord():
    import math
    from core.snap import _circle_circle_intersections
    n = V(0, 0, 1)
    pts = _circle_circle_intersections(V(0, 0, 0), 1.0, n, V(1, 0, 0), 1.0, n)
    assert len(pts) == 2
    xs = sorted(p.x() for p in pts)
    assert abs(xs[0] - 0.5) < 1e-6 and abs(xs[1] - 0.5) < 1e-6
    ys = sorted(abs(p.y()) for p in pts)
    assert abs(ys[0] - math.sqrt(3.0) / 2.0) < 1e-6


def test_a_segment_through_a_guide_circle_gives_two_points():
    from core.snap import _segment_circle_intersections
    pts = _segment_circle_intersections(
        V(-3, 0, 0), V(3, 0, 0), V(0, 0, 0), 2.0, V(0, 0, 1))
    assert len(pts) == 2
    xs = sorted(p.x() for p in pts)
    assert abs(xs[0] + 2.0) < 1e-6 and abs(xs[1] - 2.0) < 1e-6


def test_compute_snap_lands_on_a_circle_circle_intersection():
    import math
    from types import SimpleNamespace
    from core.snap import compute_snap
    n = V(0, 0, 1)
    c1 = GuideCircle(V(0, 0, 0), n, 1.0)
    c2 = GuideCircle(V(1, 0, 0), n, 1.0)
    top = V(0.5, math.sqrt(3.0) / 2.0, 0.0)

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    cursor = V(0.5, top.y() + 0.02, 0.0)
    snap = compute_snap(
        candidate_world=cursor, candidate_pixel=w2p(cursor),
        scene=SimpleNamespace(edges=[], circles=[c1, c2]), world_to_pixel=w2p,
        threshold_px=9.0, edge_threshold_px=14.0,
        project_onto_line=lambda s, d: s + d * QVector3D.dotProduct(cursor - s, d))
    assert snap.kind == "intersection"
    assert (snap.point - top).length() < 1e-4


def test_a_line_started_at_one_crossing_detects_the_other():
    """Two circles side by side cross on a chord that lines up with an axis:
    the SECOND crossing must still read as an intersection, not be stolen by
    the axis magnet the drag is engaged on (#238)."""
    import math
    from types import SimpleNamespace
    from core.snap import compute_snap
    n = V(0, 0, 1)
    c1 = GuideCircle(V(0, 0, 0), n, 1.0)
    c2 = GuideCircle(V(1, 0, 0), n, 1.0)
    A = V(0.5, math.sqrt(3.0) / 2.0, 0.0)   # the first crossing
    B = V(0.5, -math.sqrt(3.0) / 2.0, 0.0)  # the second, vertically below

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    snap = compute_snap(
        candidate_world=B, candidate_pixel=w2p(B),
        scene=SimpleNamespace(edges=[], circles=[c1, c2]), world_to_pixel=w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=A,
        project_onto_line=lambda s, d: s + d * V.dotProduct(B - s, d),
        magnetic_axis_deg=3.0)
    assert snap.kind == "intersection"
    assert (snap.point - B).length() < 1e-6


def test_circle_tool_ctrl_toggles_guide_mode_and_draws_a_guide():
    from PySide6.QtCore import QPointF, Qt
    from tools.base import ToolContext
    from tools.circle import CircleTool
    from core.scene import Scene
    from core.history import History

    class _Stub:
        def __init__(self):
            self.scene = Scene()
            self.history = History(self.scene)

        def update(self):
            pass

        def flash_status(self, *a, **k):
            pass

        def refresh_status_hint(self):
            pass

        def ctrl_tapped(self):
            return True

    st = _Stub()
    tool = CircleTool()
    tool.on_activate(st)
    assert tool._guide_mode is False
    assert "guide circle" in tool.status_clause().lower()

    # A clean Ctrl tap toggles into guide mode.
    assert tool.on_key(st, Qt.Key_Control, Qt.NoModifier) is True
    assert tool.on_key_release(st, Qt.Key_Control) is True
    assert tool._guide_mode is True

    def ctx(world):
        return ToolContext(viewport=st, world=world, screen=QPointF(0, 0),
                           modifiers=Qt.NoModifier, snap=None)

    # Centre + rim in guide mode → one analytic guide circle, no face.
    tool.on_click(ctx(V(0, 0, 0)))
    tool.on_click(ctx(V(2, 0, 0)))
    assert len(st.scene.guides) == 1
    assert not st.scene.faces
    g = st.scene.guides[0]
    assert isinstance(g, GuideCircle)
    assert (g.center - V(0, 0, 0)).length() < 1e-9
    assert abs(g.radius - 2.0) < 1e-6

    # Another Ctrl tap toggles back to the circle face.
    assert tool.on_key(st, Qt.Key_Control, Qt.NoModifier) is True
    assert tool.on_key_release(st, Qt.Key_Control) is True
    assert tool._guide_mode is False


def test_compute_snap_lands_on_a_guide_circle_quadrant():
    from types import SimpleNamespace
    from core.snap import compute_snap
    circ = GuideCircle(V(0, 0, 0), V(0, 0, 1), 2.0)

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    cursor = V(2.02, 0.0, 0.0)
    snap = compute_snap(
        candidate_world=cursor, candidate_pixel=w2p(cursor),
        scene=SimpleNamespace(edges=[], circles=[circ]), world_to_pixel=w2p,
        threshold_px=9.0, edge_threshold_px=14.0,
        project_onto_line=lambda s, d: s + d * QVector3D.dotProduct(cursor - s, d))
    assert snap.kind == "quadrant"
    assert (snap.point - V(2.0, 0.0, 0.0)).length() < 1e-4


def test_compute_snap_lands_on_a_guide_circle_tangent():
    import math
    from types import SimpleNamespace
    from core.snap import compute_snap
    circ = GuideCircle(V(0, 0, 0), V(0, 0, 1), 2.0)
    start = V(5.0, 0.0, 0.0)
    # cos_b = r/d = 0.4, sin_b = sqrt(0.84)
    target = V(0.8, 2.0 * math.sqrt(0.84), 0.0)

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    cursor = V(0.8, target.y() + 0.02, 0.0)
    snap = compute_snap(
        candidate_world=cursor, candidate_pixel=w2p(cursor),
        scene=SimpleNamespace(edges=[], circles=[circ]), world_to_pixel=w2p,
        threshold_px=9.0, edge_threshold_px=14.0, start_point=start,
        project_onto_line=lambda s, d: s + d * QVector3D.dotProduct(cursor - s, d))
    assert snap.kind == "tangent"
    assert (snap.point - target).length() < 1e-4


def test_move_guides_command_moves_a_guide_circle_and_undoes():
    from core.scene import Scene
    from core.history import AddGuideCommand, History, MoveGuidesCommand

    scene = Scene()
    hist = History(scene)
    g = GuideCircle(V(0, 0, 0), V(0, 0, 1), 2.0)
    hist.execute(AddGuideCommand(g))
    hist.execute(MoveGuidesCommand([g], V(1, 2, 0)))
    assert (g.center - V(1, 2, 0)).length() < 1e-9
    hist.undo()
    assert (g.center - V(0, 0, 0)).length() < 1e-9
    hist.redo()
    assert (g.center - V(1, 2, 0)).length() < 1e-9


def test_rotate_guides_command_rotates_a_guide_circle_and_undoes():
    from core.scene import Scene
    from core.history import AddGuideCommand, History, RotateGuidesCommand

    scene = Scene()
    hist = History(scene)
    g = GuideCircle(V(1, 0, 0), V(0, 0, 1), 2.0)
    hist.execute(AddGuideCommand(g))
    # 90° about Z: centre (1,0,0) → (0,1,0); the normal (0,0,1) is unchanged.
    hist.execute(RotateGuidesCommand([g], V(0, 0, 0), V(0, 0, 1), 90.0))
    assert (g.center - V(0, 1, 0)).length() < 1e-4
    assert abs(QVector3D.dotProduct(g.normal, V(0, 0, 1)) - 1.0) < 1e-6
    hist.undo()
    assert (g.center - V(1, 0, 0)).length() < 1e-4
    assert abs(QVector3D.dotProduct(g.normal, V(0, 0, 1)) - 1.0) < 1e-6


def test_add_and_delete_guide_circle_undo_redo():
    from core.scene import Scene
    from core.history import AddGuideCommand, DeleteGuidesCommand, History

    scene = Scene()
    hist = History(scene)
    g = GuideCircle(V(0, 0, 0), V(0, 0, 1), 2.0)

    hist.execute(AddGuideCommand(g))
    assert g in scene.guides
    hist.undo()
    assert g not in scene.guides
    hist.redo()
    assert g in scene.guides

    hist.execute(DeleteGuidesCommand([g]))
    assert g not in scene.guides
    hist.undo()
    assert g in scene.guides


def test_a_guide_circle_lands_on_the_guides_layer():
    from core.history import AddGuideCommand, History
    from core.layers import layer_of
    from core.scene import Scene

    scene = Scene()
    hist = History(scene)
    hist.execute(AddGuideCommand(GuideCircle(V(0, 0, 0), V(0, 0, 1), 2.0)))
    assert layer_of(scene.guides[-1]) == "Guides"   # like a guide line
    assert scene.layer("Guides") is not None


def test_guide_mode_previews_the_circle_dashed_not_solid():
    from tools.circle import CircleTool

    tool = CircleTool()
    tool._reset()
    tool.work_plane = (V(0, 0, 0), V(0, 0, 1))
    tool.start_point = V(0, 0, 0)
    tool.hover_point = V(2, 0, 0)

    tool._guide_mode = False
    assert len(tool.rubber_band_lines()) == 24      # the solid circle
    assert tool.guide_preview_lines() == []

    tool._guide_mode = True
    assert tool.rubber_band_lines() == []           # no solid rubber band
    assert len(tool.guide_preview_lines()) == 24    # the dashed rim instead
