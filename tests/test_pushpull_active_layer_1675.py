# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A staged push/pull still puts its new geometry on the active layer
(#1675, follow-up to #1366).

The #1366 fix tags what a command drew by comparing the model before and
after it runs. A mouse drag does not commit that way: its preview stages
the push on the live model, and the release commits the held stage as a
``SnapshotMutation.from_states`` — the model already shows the result when
``History.execute`` reads the «before», so the pushed cap and walls counted
as already there and nothing was ever tagged. The cap kept the base face's
layer (it inherits its attrs) while the new walls and edges stayed on
Layer 0: the mix of Layer 0 and Layer 1 the reporter saw in 0.6.3.2.

Headless: the staged-preview harness of ``test_pushpull_staged_preview`` —
a drag is a frame at a distance, the release is ``_commit``.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

import core.layers as L
from core.edits import build_add_edges
from core.history import AddFaceCommand, History
from core.layers import DEFAULT_LAYER, Layer, layer_of
from core.scene import Scene
from tests.test_pushpull_staged_preview import _frame, _start
from tests.test_pushpull_ux import _cube

ACTIVE = "Ebene 1"


def _plane_in_a_plane():
    """A 10×10 plane on Layer 0 with a 4×4 plane drawn inside it while
    «Ebene 1» is active — the reporter's example, the inner plane pulled
    up."""
    scene = Scene()
    hist = History(scene)
    hist.execute(AddFaceCommand(
        [V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0)]))
    scene.layers.append(Layer(ACTIVE))
    L.set_active(scene, ACTIVE)
    inner = [V(3, 3, 0), V(7, 3, 0), V(7, 7, 0), V(3, 7, 0)]
    segments = [(inner[i], inner[(i + 1) % 4]) for i in range(4)]
    hist.execute(build_add_edges(scene, segments, detect_faces=False,
                                 extra=[AddFaceCommand(list(inner))]))
    face = next(f for f in scene.mesh.faces
                if abs(f.centroid().z()) < 1e-9 and not f.holes
                and abs(f.centroid().x() - 5.0) < 0.1)
    return scene, face


def _panel_on_a_box():
    """The same drawing on top of a solid box: the inner panel on the box
    top, pulled up with «Ebene 1» active."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=10.0, height=3.0)
    scene.layers.append(Layer(ACTIVE))
    L.set_active(scene, ACTIVE)
    inner = [V(3, 3, 3), V(7, 3, 3), V(7, 7, 3), V(3, 7, 3)]
    segments = [(inner[i], inner[(i + 1) % 4]) for i in range(4)]
    hist.execute(build_add_edges(scene, segments, detect_faces=False,
                                 extra=[AddFaceCommand(list(inner))]))
    face = next(f for f in scene.mesh.faces
                if abs(f.centroid().z() - 3.0) < 1e-9 and not f.holes
                and abs(f.centroid().x() - 5.0) < 0.1)
    return scene, face


def _drag_and_release(vp, tool, *distances):
    for d in distances:
        _frame(tool, vp, d)
    tool.extrusion = distances[-1]
    tool._commit(vp)


def _raised(scene, z):
    return [f for f in scene.mesh.faces if f.centroid().z() > z + 1e-9]


def test_a_dragged_push_puts_the_new_walls_on_the_active_layer():
    scene, vp, tool = _start(_plane_in_a_plane)
    _drag_and_release(vp, tool, 1.0, 2.0)

    assert len(vp.history.undo_stack) == 1
    raised = _raised(scene, 0.0)
    assert len(raised) == 5                    # the cap plus four walls
    assert all(layer_of(f) == ACTIVE for f in raised)
    assert all(layer_of(e) == ACTIVE for e in scene.mesh.edges
               if e.a.z() > 1e-9 or e.b.z() > 1e-9)
    # The plane the panel was pulled out of is old geometry: it keeps
    # Layer 0, hole and all.
    ground = [f for f in scene.mesh.faces
              if abs(f.centroid().z()) < 1e-9]
    assert len(ground) == 1 and layer_of(ground[0]) == DEFAULT_LAYER


def test_a_dragged_push_on_a_solid_puts_the_new_walls_on_the_active_layer():
    scene, vp, tool = _start(_panel_on_a_box)
    _drag_and_release(vp, tool, 1.0, 2.0)

    raised = _raised(scene, 3.0)
    assert len(raised) == 5
    assert all(layer_of(f) == ACTIVE for f in raised)
    assert all(layer_of(e) == ACTIVE for e in scene.mesh.edges
               if e.a.z() > 3.0 + 1e-9 or e.b.z() > 3.0 + 1e-9)


def test_undo_and_redo_keep_the_pushed_layers():
    scene, vp, tool = _start(_plane_in_a_plane)
    _drag_and_release(vp, tool, 2.0)
    tagged = sorted(layer_of(f) for f in scene.mesh.faces)

    assert vp.history.undo() is True
    assert all(layer_of(f) in (ACTIVE, DEFAULT_LAYER)
               for f in scene.mesh.faces)
    assert [f for f in scene.mesh.faces if f.centroid().z() > 1e-9] == []

    assert vp.history.redo() is True
    assert sorted(layer_of(f) for f in scene.mesh.faces) == tagged
    assert all(layer_of(f) == ACTIVE for f in _raised(scene, 0.0))
