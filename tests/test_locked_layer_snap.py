# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Objects on locked layers can be snapped to (#1510).

A locked layer protects its objects from editing, not from snapping:
like an object-locked group (#1210), a group on a locked layer stays a
snap reference — its faces are inference targets and its edges are
offered — while it stays unselectable. Loose geometry on a locked layer
follows the same rule its edges already had.
"""
import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.layers import Layer, assign_layer
from core.mesh import Mesh
from core.scene import Scene
from views.viewport import Viewport


def _box(m, x0, y0, z0, x1, y1, z1):
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0)])
    m.add_face([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)])
    m.add_face([V(x0, y1, z0), V(x1, y1, z0), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x0, y1, z0), V(x0, y1, z1), V(x0, y0, z1)])
    m.add_face([V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)])


@pytest.fixture()
def locked_scene():
    scene = Scene()
    scene.layers += [Layer("A"), Layer("B", locked=True)]
    ga = Group(Mesh(), name="BoxA")
    ga.layer = "A"
    _box(ga.mesh, 0, 0, 0, 2, 2, 2)
    gb = Group(Mesh(), name="BoxB")
    gb.layer = "B"
    _box(gb.mesh, 10, 0, 0, 12, 2, 2)
    scene.groups += [ga, gb]
    vp = Viewport(None)
    vp.flash_status = lambda *args, **kwargs: None
    vp.resize(900, 600)
    vp.camera.set_aspect(900, 600)
    vp.camera.target = V(6.0, 1.0, 1.0)
    vp.camera.distance = 20.0
    vp.scene = scene
    vp.scene.version += 1
    yield vp, scene, ga, gb
    vp.close()


def test_locked_layer_group_is_a_snap_reference_but_not_selectable(locked_scene):
    vp, scene, ga, gb = locked_scene
    assert scene.group_snappable(gb)
    assert not scene.entity_selectable(gb)
    idx = vp._pick_flat(vp._pick_index(near="all"))
    names = [getattr(g, "name", None) for _f, g in idx.entities]
    locked = [i for i, n in enumerate(names) if n == "BoxB"]
    assert locked, "BoxB's faces are in the index"
    assert idx.ent_infer[locked].all()
    assert not idx.ent_sel[locked].any()
    assert "BoxB" in [getattr(g, "name", None)
                      for g in idx.gedge_groups]
    px = vp._world_to_pixel(V(11.0, 0.0, 2.0))
    assert vp._nearby_group_edges(*px)
    assert vp.pick_group(*px) is None


def test_locked_layer_loose_face_is_inferable_but_not_selectable(locked_scene):
    vp, scene, ga, gb = locked_scene
    _box(scene.mesh, 20, 0, 0, 22, 2, 2)
    for f in scene.mesh.faces:
        assign_layer(f, "B")
    scene.version += 1
    idx = vp._pick_flat(vp._pick_index(near="all"))
    loose = np.nonzero(idx.ent_loose)[0]
    assert len(loose) == 6
    assert idx.ent_infer[loose].all()
    assert not idx.ent_sel[loose].any()


def test_locked_layer_loose_edge_is_snappable(locked_scene):
    vp, scene, ga, gb = locked_scene
    _box(scene.mesh, 20, 0, 0, 22, 2, 2)
    for e in scene.mesh.edges:
        e.layer = "B"
    scene.version += 1
    edge = scene.mesh.edges[0]
    assert scene.edge_snappable(edge)
    idx = vp._pick_flat(vp._pick_index(near="all"))
    assert idx.edge_snap.all()


def test_hidden_layer_group_is_not_a_snap_reference(locked_scene):
    vp, scene, ga, gb = locked_scene
    scene.layer("B").visible = False
    scene.version += 1
    assert not scene.group_snappable(gb)
    idx = vp._pick_flat(vp._pick_index(near="all"))
    names = [getattr(g, "name", None) for _f, g in idx.entities]
    locked = [i for i, n in enumerate(names) if n == "BoxB"]
    assert not idx.ent_infer[locked].any()
    assert "BoxB" not in [getattr(g, "name", None)
                          for g in idx.gedge_groups]
