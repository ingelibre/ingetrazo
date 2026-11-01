# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Lock targets, face constraints, near-ties and visible edge portions.

These cases reproduce the snap review's incorrect coordinates or metadata;
controls preserve deliberate off-plane point targets and unconstrained snaps.
No OpenGL context is required.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D as V

from core import snap
from core.topology import segment_intersection


def edge(a, b, **flags):
    return SimpleNamespace(a=a, b=b, **flags)


def scene(*edges):
    return SimpleNamespace(edges=list(edges))


def to_pixel(p):
    return p.x() * 100.0, p.y() * 100.0


def project(candidate):
    def onto_line(start, direction):
        u = direction.normalized()
        return start + u * V.dotProduct(candidate - start, u)
    return onto_line


def compute(model, candidate, **kwargs):
    return snap.compute_snap(
        candidate, to_pixel(candidate), model, to_pixel,
        threshold_px=9.0, edge_threshold_px=14.0,
        project_onto_line=project(candidate), **kwargs,
    )


def lock(mode):
    if mode == "arrow":
        return {"axis_lock": "x"}
    if mode == "shift":
        return {"shift_lock_dir": V(1, 0, 0)}
    return {"reference_edge": edge(V(0, 9, 0), V(1, 9, 0)),
            "reference_mode": "parallel"}


@pytest.mark.parametrize("mode", ["arrow", "shift", "reference"])
def test_origin_on_lock_line_is_exact(mode):
    candidate = V(0.03, 0.02, 0)
    result = compute(scene(), candidate, start_point=V(-2, 0, 0), **lock(mode))
    assert result.kind == "origin", (result.kind, result.point)
    assert result.point.length() < 1e-6


@pytest.mark.parametrize("mode", ["arrow", "shift", "reference"])
def test_midpoint_on_collinear_lock_line_is_exact(mode):
    model = scene(edge(V(2, 10, 0), V(8, 10, 0)))
    result = compute(model, V(5.03, 10.02, 0), start_point=V(0, 10, 0),
                     **lock(mode))
    assert result.kind == "midpoint", (result.kind, result.point)
    assert (result.point - V(5, 10, 0)).length() < 1e-6


def test_locked_endpoint_respects_occlusion():
    model = scene(edge(V(5, 10, 0), V(5, 11, 0)))
    result = compute(model, V(5, 10.02, 0), start_point=V(0, 10, 0),
                     axis_lock="x", is_occluded=lambda p: True)
    assert result.kind == "axis", (result.kind, result.point)


def test_locked_endpoint_is_the_nearest_and_independent_of_edge_order():
    far = edge(V(5.08, 10, 0), V(6, 11, 0))
    near = edge(V(5.01, 10, 0), V(7, 12, 0))
    kwargs = {"start_point": V(0, 10, 0), "axis_lock": "x"}
    first = compute(scene(far, near), V(5, 10, 0), **kwargs)
    reverse = compute(scene(near, far), V(5, 10, 0), **kwargs)
    assert (first.point - reverse.point).length() < 1e-6, (first, reverse)
    assert (first.point - near.a).length() < 1e-6


@pytest.mark.parametrize("mode", ["arrow", "shift", "reference"])
@pytest.mark.parametrize("kind", ["center", "component_origin", "arc_midpoint"])
def test_lock_preserves_named_pseudo_points(kind, mode):
    point = V(5, 10, 0)
    model = scene(edge(point, point, context="component", **{kind: True}))
    result = compute(model, point, start_point=V(0, 10, 0), **lock(mode))
    assert result.kind == kind, (result.kind, result.point)
    assert result.context == "component"
    assert result.lock_color is not None


def test_parallel_offset_extension_does_not_leave_face_plane():
    # A roof edge at z=1 extends above the floor at z=0. The cursor beyond
    # its endpoint is over the floor. A line inference must stay on that face.
    model = scene(edge(V(0, 0, 1), V(2, 0, 1)))
    result = compute(model, V(3, 0, 0), start_point=V(2, 0, 0),
                     face_under_cursor=True, work_plane_normal=V(0, 0, 1))
    assert abs(result.point.z()) < 1e-6, (result.kind, result.point)


def test_control_real_edge_intersection_can_replane_a_shape():
    model = scene(edge(V(0, 0, 1), V(2, 0, 3)),
                  edge(V(-1.04, -1, -0.04), V(-1.04, 1, -0.04)))
    result = compute(model, V(-1.05, 0, 0), start_point=V(0, 0, 1),
                     face_under_cursor=True, work_plane_normal=V(0, 0, 1))
    # A real point target is allowed off the current face (POINT_SNAP_KINDS).
    # This is distinct from an unbounded extension or a derived from-point.
    assert result.kind == "intersection"
    assert result.kind in snap.POINT_SNAP_KINDS
    assert (result.point - V(-1.04, 0, -0.04)).length() < 1e-5


@pytest.mark.parametrize("diagonal", [False, True])
def test_two_encouraged_points_keep_derived_snap_on_face(diagonal):
    result = compute(
        scene(), V(2.02, 3.02, 0), face_under_cursor=True,
        work_plane_normal=V(0, 0, 1),
        acquired_point=V(0, 3, 1),
        acquired_points=[V(2, 0, 1), V(0, 3, 1)],
        diagonal_span=diagonal,
        start_point=V(-3, -4, 0) if diagonal else None,
    )
    assert abs(result.point.z()) < 1e-6, (result.kind, result.point)


def test_uncaptured_shift_does_not_infer_axis_outside_shape_plane():
    start, candidate = V(0, 0, 0), V(2, 0, 0.04)
    normal = V(-0.02, 0, 1).normalized()
    result = compute(scene(), candidate, start_point=start,
                     shift_held=True, magnetic_axis_deg=3.0,
                     face_under_cursor=True, work_plane_normal=normal,
                     axis_in_plane=True)
    off_plane = abs(V.dotProduct(result.point - start, normal))
    assert off_plane < 1e-6, (result.kind, result.point, off_plane)


def test_long_segment_crossing_is_not_lost_by_lock_solver():
    direction = V(math.cos(math.radians(5)), math.sin(math.radians(5)), 0)
    expected = V(10, 0, 0)
    a, b = expected - direction * 10000, expected + direction * 10000
    # Independent solver on the very same represented endpoints succeeds.
    reference = segment_intersection(V(0, 0, 0), V(20, 0, 0), a, b)
    assert reference is not None and (reference - expected).length() < 1e-6
    result = snap._line_segment_intersection(V(0, 0, 0), V(1, 0, 0), a, b)
    assert result is not None, (a, b, reference)
    assert (result - expected).length() < 1e-3


def test_engaged_axis_skips_intersection_work_whose_result_it_discards(monkeypatch):
    calls = []

    def search(*args, **kwargs):
        calls.append(1)
        return None

    monkeypatch.setattr(snap, "_intersection_snap", search)
    result = compute(scene(), V(5, 10.01, 0), start_point=V(0, 10, 0),
                     magnetic_axis_deg=3.0)
    assert result.kind == "axis" and result.axis == "x"
    assert calls == [], "Intersection result is discarded while an axis is engaged"


def test_context_near_tie_is_preserved_across_half_pixel_bucket_boundary():
    component = edge(V(2.000001, 0, 0), V(2, 2, 0), context="component")
    loose = edge(V(0, 0, 0), V(2, 0, 0), context=None)
    candidate = V(2.005, 0, 0)
    component_distance = abs(to_pixel(candidate)[0] - to_pixel(component.a)[0])
    loose_distance = abs(to_pixel(candidate)[0] - to_pixel(loose.b)[0])
    assert abs(component_distance - loose_distance) < 0.001
    result = compute(scene(component, loose), candidate)
    assert result.context is None, (component_distance, loose_distance, result)
    assert result.point == loose.b


def test_visible_part_of_edge_crossing_camera_plane_still_snaps():
    from core.camera import OrbitCamera
    from core.scene import Scene
    from views.viewport import Viewport

    camera = OrbitCamera()
    camera.set_aspect(1000, 800)
    camera.look_from(V(0, 0, 0), V(0, 1, 0))
    viewport = SimpleNamespace(camera=camera, width=lambda: 1000,
                               height=lambda: 800)

    def perspective(point):
        return Viewport._world_to_pixel(viewport, point)

    model = Scene()
    model.mesh.add_edge(V(0.2, -1, 0), V(0.2, 4, 0))
    candidate = V(0.2, 2, 0)
    assert perspective(model.edges[0].a) is None
    assert perspective(model.edges[0].b) is not None
    assert 0 < perspective(candidate)[0] < 1000
    result = snap.compute_snap(candidate, perspective(candidate), model,
                               perspective, threshold_px=9.0,
                               edge_threshold_px=14.0,
                               project_onto_line=project(candidate))
    assert result.kind == "on_edge", (result.kind, result.point)
    assert (result.point - candidate).length() < 1e-6


def test_control_unlocked_origin_is_exact():
    result = compute(scene(), V(0.03, 0.02, 0))
    assert result.kind == "origin" and result.point.length() < 1e-6


def test_control_unlocked_midpoint_is_exact():
    result = compute(scene(edge(V(2, 10, 0), V(8, 10, 0))), V(5.03, 10.02, 0))
    assert result.kind == "midpoint"
    assert (result.point - V(5, 10, 0)).length() < 1e-6


def test_control_hidden_endpoint_without_lock_is_not_offered():
    result = compute(scene(edge(V(5, 10, 0), V(5, 11, 0))), V(5, 10.02, 0),
                     is_occluded=lambda p: True)
    assert result.kind == "none"


def test_control_extension_in_face_remains_on_face():
    result = compute(scene(edge(V(0, 0, 0), V(2, 0, 0))), V(3, 0, 0),
                     start_point=V(2, 0, 0), face_under_cursor=True,
                     work_plane_normal=V(0, 0, 1))
    assert result.kind == "extension" and abs(result.point.z()) < 1e-6


@pytest.mark.parametrize("mode", ["arrow", "shift", "reference"])
def test_lock_chooses_visible_endpoints_in_batches(mode):
    model = scene(*(edge(V(5 + i * 0.01, 10, 0), V(6 + i * 0.01, 11, 0))
                    for i in range(13)))
    singles, batches = [], []

    def hidden(point):
        return point.x() < 5.045

    def one(point):
        singles.append(point)
        return hidden(point)

    def many(points):
        batches.append(len(points))
        return [hidden(point) for point in points]

    result = compute(model, V(5, 10.01, 0), start_point=V(0, 10, 0),
                     is_occluded=one, are_occluded=many, **lock(mode))
    assert result.kind == "endpoint"
    assert (result.point - V(5.05, 10, 0)).length() < 1e-5
    assert len(singles) == 1
    assert batches == [8]


@pytest.mark.parametrize("batched", [False, True])
def test_hidden_nearest_point_does_not_anchor_context_tie(batched):
    hidden_point = V(2, 10, 0)
    component = edge(V(2.0049, 10, 0), V(0, 22, 0), context="component")
    loose = edge(V(2.0051, 10, 0), V(0, 24, 0), context=None)
    model = scene(edge(hidden_point, V(0, 20, 0)), component, loose)
    calls = []

    def hidden(point):
        calls.append(point.toTuple())
        return point == hidden_point

    kwargs = {"are_occluded": lambda points: [hidden(p) for p in points]} if batched else {}
    result = compute(model, hidden_point, is_occluded=hidden, **kwargs)
    assert result.context is None and result.point == loose.a
    assert len(calls) == len(set(calls))


def test_locked_points_prefer_the_current_context_in_a_near_tie():
    component = edge(V(5.000001, 10, 0), V(7, 12, 0), context="component")
    loose = edge(V(5, 10, 0), V(6, 11, 0), context=None)
    result = compute(scene(component, loose), V(5.005, 10, 0),
                     start_point=V(0, 10, 0), axis_lock="x")
    assert result.context is None and result.point == loose.a


@pytest.mark.parametrize("angle", [1, 5, 30, 45, 85])
@pytest.mark.parametrize("length", [1, 1000, 10000])
def test_lock_line_solver_handles_different_lengths_and_angles(angle, length):
    direction = V(math.cos(math.radians(angle)), math.sin(math.radians(angle)), 0)
    expected = V(10, 0, 0)
    a, b = expected - direction * length, expected + direction * length
    result = snap._line_segment_intersection(V(0, 0, 0), V(1, 0, 0), a, b)
    assert result is not None
    assert (result - expected).length() < 1e-3


@pytest.mark.parametrize("a,b", [
    (V(5, -1, 0.01), V(5, 1, 0.01)),  # skew by more than the absolute tolerance
    (V(5, 1, 0), V(5, 2, 0)),         # meeting outside the segment
    (V(1, 1, 0), V(10, 1, 0)),        # parallel
    (V(5, 0, 0), V(5, 0, 0)),         # degenerate
])
def test_lock_line_solver_rejects_false_crossings(a, b):
    assert snap._line_segment_intersection(V(0, 0, 0), V(1, 0, 0), a, b) is None


def test_explicit_axis_lock_can_still_leave_a_shape_plane():
    result = compute(scene(), V(2, 0, 0.04), start_point=V(0, 0, 0),
                     axis_lock="x", face_under_cursor=True,
                     work_plane_normal=V(-0.02, 0, 1).normalized(),
                     axis_in_plane=True)
    assert result.kind == "axis" and result.point == V(2, 0, 0)


def test_two_encouraged_points_on_a_face_keep_their_crossing():
    result = compute(scene(), V(2.02, 3.02, 0), face_under_cursor=True,
                     work_plane_normal=V(0, 0, 1), acquired_point=V(0, 3, 0),
                     acquired_points=[V(2, 0, 0), V(0, 3, 0)])
    assert result.kind == "from_point"
    assert (result.point - V(2, 3, 0)).length() < 1e-6


def test_unprojectable_edge_does_not_create_an_endpoint_or_midpoint():
    # A perspective looking down -Z, with one endpoint behind the eye.
    def perspective(point):
        if point.z() >= 0:
            return None
        return point.x() * 100 / -point.z(), point.y() * 100 / -point.z()

    model = scene(edge(V(0.2, 0, 1), V(0.2, 0, -4)))
    for candidate in (V(0.2, 0, -2), V(0.2, 0, -0.5)):
        result = snap.compute_snap(candidate, perspective(candidate), model,
                                   perspective, threshold_px=0.1,
                                   edge_threshold_px=0.1,
                                   project_onto_line=project(candidate))
        assert result.kind == "on_edge"
        assert (result.point - candidate).length() < 1e-6


def test_edge_wholly_behind_camera_is_not_offered():
    def perspective(point):
        return None if point.z() >= 0 else (point.x() * 100, point.y() * 100)

    candidate = V(2, 3, -1)
    result = snap.compute_snap(candidate, perspective(candidate),
                               scene(edge(V(2, 3, 1), V(2, 3, 4))),
                               perspective, threshold_px=9,
                               project_onto_line=project(candidate))
    assert result.kind == "none"
