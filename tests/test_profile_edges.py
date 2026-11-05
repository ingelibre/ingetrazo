# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Silhouettes depend on geometry, independently of the front/back choice."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

from core.edge_style import EDGE_FLOATS, edge_vertices, marker_candidates
from core.scene import Scene
from core.style import Style


def _surface(mesh, kind):
    if kind == "cube":
        points = [V(x, y, z) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
        for ring in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                     (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)):
            mesh.add_face([points[i] for i in ring])
    elif kind == "open_fold":
        mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
        mesh.add_face([V(2, 0, 0), V(0, 0, 0), V(0, 0, 2), V(2, 0, 2)])
    else:
        outer = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)]
        hole = [V(1, 1, 0), V(3, 1, 0), V(3, 3, 0), V(1, 3, 0)]
        mesh.add_face(outer, [hole if kind == "hole_same" else hole[::-1]])
        mesh.add_face(hole)


def _profiles(data, eye):
    pairs = data.reshape((-1, 2, EDGE_FLOATS))
    toward = np.asarray(eye) - pairs[:, :, :3].mean(axis=1)
    first = pairs[:, 0]
    return ((first[:, 13] > 0.5)
            | ((first[:, 6:9] * toward).sum(axis=1)
               * (first[:, 9:12] * toward).sum(axis=1) < 0))


@pytest.mark.parametrize("kind", ["cube", "open_fold", "hole_same", "hole_opposite"])
def test_reversing_any_face_keeps_silhouettes_and_marker_owners(kind):
    scene = Scene()
    _surface(scene.mesh, kind)
    original = edge_vertices(scene.mesh, scene)
    style = Style(edges=False, profiles=True, endpoints=True, endpoint_type="square")
    eyes = [(4, 3, 2), (-3, 4, 1), (2, -3, -4), (-4, -3, 2)]
    if kind.startswith("hole"):
        # Filling a hole creates coplanar seams, regardless of either ring's
        # winding. Only the four outer boundaries belong to the silhouette.
        assert _profiles(original, eyes[0]).sum() == 4
    for face in scene.mesh.faces:
        face.loop.reverse()
        for hole in face.hole_loops:
            hole.reverse()
        reversed_data = edge_vertices(scene.mesh, scene)
        for eye in eyes:
            np.testing.assert_array_equal(_profiles(reversed_data, eye), _profiles(original, eye))
            for perspective in (False, True):
                def owners(data):
                    return marker_candidates(data, np.eye(4), style, "shaded", np.asarray(eye),
                                             -np.asarray(eye), perspective)[:, :3]
                np.testing.assert_array_equal(owners(reversed_data), owners(original))
        face.loop.reverse()
        for hole in face.hole_loops:
            hole.reverse()


@pytest.mark.parametrize("kind", ["cube", "open_fold", "hole_same", "hole_opposite"])
def test_deferred_profile_normals_match_materialized_mesh_with_mixed_winding(
        kind, tmp_path, monkeypatch):
    from core import _native
    from core.group import Group
    from core.mesh import DeferredMesh
    from formats import igz
    from tests.test_chunk_stale_materials import _stub

    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)
    scene = Scene()
    group = Group()
    scene.groups.append(group)
    _surface(group.mesh, kind)
    group.mesh.faces[0].loop.reverse()
    for hole in group.mesh.faces[0].hole_loops:
        hole.reverse()
    for edge in group.mesh.edges:
        edge.soft = True
    path = tmp_path / "reversed.igz"
    igz.save_scene(scene, path)
    opened = Scene()
    igz.load_into(opened, path)
    group = opened.groups[0]
    mesh = group.mesh
    assert type(mesh) is DeferredMesh
    lazy = edge_vertices(mesh, opened)
    assert type(mesh) is DeferredMesh
    # Also cover the original one-pixel soft-edge rendering path when the
    # native array baker is available, without requiring it on every platform.
    from views.array_bake import can_bake
    if can_bake(mesh):
        lazy_chunk = _stub(opened)._group_chunk(group)
        assert type(mesh) is DeferredMesh
    else:
        lazy_chunk = None
    mesh.faces
    np.testing.assert_allclose(lazy, edge_vertices(mesh, opened))
    if lazy_chunk is not None:
        eager_chunk = _stub(opened)._group_chunk(group)
        for key in ("soft_pts", "soft_n0", "soft_n1", "soft_c0", "soft_c1", "soft_single"):
            np.testing.assert_allclose(lazy_chunk[key], eager_chunk[key])


@pytest.mark.parametrize("grouped", [False, True])
def test_vector_exports_keep_the_same_soft_silhouettes_after_a_face_flip(grouped):
    from types import SimpleNamespace
    from core.group import Group
    from core.history import FlipFacesCommand, History
    from core.hlr import collect_geometry
    from core.mesh import Mesh
    from tests.test_chunk_stale_materials import _stub

    scene = Scene()
    mesh = scene.mesh
    _surface(mesh, "cube")
    for edge in mesh.edges:
        edge.soft = True
    if grouped:
        scene.groups.append(Group(mesh))
        scene.mesh = Mesh()
    vp = _stub(scene)
    vp._pick_index = lambda **kwargs: SimpleNamespace()
    vp._pick_flat = lambda index: index
    vp._placements = lambda: scene.groups

    def profiles():
        _, _, soft = collect_geometry(scene)
        _, _, _segments, normals = vp.hlr_geometry()
        normals = np.asarray(normals)
        for direction in ((4, 3, 2), (-3, 4, 1), (2, -3, -4)):
            slow = np.asarray([np.dot(a, direction) * np.dot(b, direction) < 0
                               for _p, _q, a, b in soft])
            fast = (normals[:, 0] @ direction) * (normals[:, 1] @ direction) < 0
            np.testing.assert_array_equal(slow, fast)
            yield slow.copy()

    expected = list(profiles())
    history = History(scene)
    for face in mesh.faces:
        history.execute(FlipFacesCommand([face]))
        np.testing.assert_array_equal(list(profiles()), expected)
        history.undo()
