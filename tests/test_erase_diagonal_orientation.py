# SPDX-License-Identifier: GPL-3.0-or-later
"""Erasing a rectangle's diagonal must preserve its front and back sides."""
import pytest
from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edge, build_add_edges
from core.history import AddFaceCommand, EraseSelectionCommand, History
from core.mesh import Mesh
from core.scene import Scene


@pytest.mark.parametrize("plane", ["xy", "xz", "tilted"])
@pytest.mark.parametrize("reversed_face", [False, True])
@pytest.mark.parametrize("diagonal", [(0, 2), (2, 0), (1, 3), (3, 1)])
def test_draw_split_erase_preserves_normal_and_paint(plane, reversed_face, diagonal):
    if plane == "xy":
        corners = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)]
    elif plane == "xz":
        corners = [V(0, 0, 0), V(2, 0, 0), V(2, 0, 2), V(0, 0, 2)]
    else:
        corners = [V(0, 0, 0), V(2, 0, 2), V(2, 2, 2), V(0, 2, 0)]
    if reversed_face:
        corners.reverse()
    scene = Scene()
    hist = History(scene)
    hist.execute(build_add_edges(
        scene, [(corners[i], corners[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(corners)]))
    normal = scene.faces[0].normal()
    attrs = {"color": "#cc8844", "back": {"color": "#336699"}}
    scene.faces[0].attrs = attrs.copy()
    a, b = (corners[i] for i in diagonal)
    hist.execute(build_add_edge(scene, a, b))
    assert len(scene.faces) == 2
    assert all(V.dotProduct(f.normal(), normal) > 0.999 for f in scene.faces)
    m = scene.mesh
    edge = m.find_edge(m.vertex_at(a), m.vertex_at(b))
    hist.execute(EraseSelectionCommand([edge]))

    def check_merged():
        assert len(scene.faces) == 1
        assert len(scene.edges) == 4
        assert V.dotProduct(scene.faces[0].normal(), normal) > 0.999
        assert scene.faces[0].attrs == attrs

    check_merged()
    assert hist.undo()
    assert len(scene.faces) == 2
    assert len(scene.edges) == 5
    assert all(V.dotProduct(f.normal(), normal) > 0.999 for f in scene.faces)
    assert hist.redo()
    check_merged()


@pytest.mark.parametrize("method,opposite_fragment", [
    ("region", False), ("pair", False), ("region", True)])
@pytest.mark.parametrize("trace_sign", [-1, 1])
def test_merge_orients_outer_and_hole_independently(
    monkeypatch, method, opposite_fragment, trace_sign
):
    import core.mesh as mesh_module

    m = Mesh()
    left = m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 4, 0), V(0, 4, 0)],
                      [[V(.5, 1, 0), V(.5, 2, 0), V(1.5, 2, 0), V(1.5, 1, 0)]])
    right = m.add_face([V(2, 0, 0), V(4, 0, 0), V(4, 4, 0), V(2, 4, 0)])
    normal = left.normal()
    if opposite_fragment:
        right.loop.reverse()
    trace = mesh_module._trace_loops

    def trace_backwards(outline):
        # The undirected tracer may return either winding for EACH loop.
        loops = trace(outline)
        for loop in loops:
            if mesh_module.Face(loop).normal().z() * trace_sign < 0:
                loop.reverse()
        return loops

    monkeypatch.setattr(mesh_module, "_trace_loops", trace_backwards)
    if method == "region":
        merged = m.dissolve_coplanar_region([left, right])
    else:
        merged = m.dissolve_coplanar_pair(left, right)["merged"]
    assert V.dotProduct(merged.normal(), normal) > 0.999
    assert len(merged.hole_loops) == 1
    assert V.dotProduct(mesh_module.Face(merged.hole_loops[0]).normal(), normal) < -0.999
    assert merged.area() == pytest.approx(16.0)
    assert mesh_module.Face(merged.hole_loops[0]).area() == pytest.approx(1.0)
