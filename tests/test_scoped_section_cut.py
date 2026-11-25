# SPDX-License-Identifier: GPL-3.0-or-later
"""The scoped section resolves a placement path, independent of shared meshes."""
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.scene import Scene
from core.section import ScopedSectionCut


def test_scope_includes_children_and_excludes_shared_mesh_copies():
    scene = Scene()
    owner = Group()
    nested = Group()
    owner.children.append(nested)
    sibling = Group(mesh=owner.mesh)
    scene.groups.extend([owner, sibling])

    cut = ScopedSectionCut(scene, owner.uid, V(0, 0, 1), V(0, 0, 1))
    assert cut.hidden(V(0, 0, 2), owner)
    assert cut.hidden(V(0, 0, 2), nested)
    assert not cut.hidden(V(0, 0, 0), nested)
    assert not cut.hidden(V(0, 0, 2), sibling)
    assert not cut.hidden(V(0, 0, 2), None)


def test_nested_cut_moves_with_its_placement_and_transforms_the_normal():
    scene = Scene()
    parent = Group()
    parent.xform = QMatrix4x4()
    parent.xform.translate(3, 0, 0)
    parent.xform.rotate(90, 0, 1, 0)
    owner = Group()
    owner.xform = QMatrix4x4()
    owner.xform.scale(2, 1, 3)
    parent.children.append(owner)
    scene.groups.append(parent)

    cut = ScopedSectionCut(scene, owner.uid, V(0, 0, 1), V(1, 0, 1))
    assert (cut.point - V(6, 0, 0)).length() < 1e-5
    assert (cut.normal - V(2, 0, -3).normalized()).length() < 1e-5
    assert cut.hidden(cut.point + cut.normal, owner)
    assert not cut.hidden(cut.point + cut.normal, parent)

    scene.groups.clear()
    gone = ScopedSectionCut(scene, owner.uid, V(), V(0, 0, 1))
    assert not gone.applies_to(owner)


def test_draw_clipping_keeps_winding_and_interpolates_uv_at_the_cut():
    import numpy as np

    scene = Scene()
    owner = Group()
    scene.groups.append(owner)
    cut = ScopedSectionCut(scene, owner.uid, V(), V(1, 0, 0))
    triangle = np.asarray([
        [-1, -1, 0, 0, 0], [1, 0, 0, 1, 0.5], [-1, 1, 0, 0, 1],
    ], dtype=np.float32)
    raw = cut.clip_draw_primitives(triangle.tobytes(), stride=5, arity=3)
    clipped = np.frombuffer(raw, np.float32).reshape(2, 3, 5)
    assert (clipped[..., 0] <= 0).all()
    boundary = clipped[clipped[..., 0] == 0]
    assert (boundary[:, 3] == 0.5).all()
    assert set(boundary[:, 4]) == {0.25, 0.75}
    a, b, c = clipped[..., :3].transpose(1, 0, 2)
    assert (np.cross(b - a, c - a)[:, 2] > 0).all()

    edge = np.asarray([[1.0, 0, 0], [-1.0, 0, 0]], dtype=np.float32)
    raw = cut.clip_draw_primitives(edge.tobytes(), stride=3, arity=2)
    assert np.frombuffer(raw, np.float32).reshape(-1, 3).tolist() == [
        [0, 0, 0], [-1, 0, 0],
    ]
