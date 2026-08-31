# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Hide/unhide edges (SketchUp's Edit ▸ Hide scoped to edges).

``Edge.hidden`` predates this feature (imported foliage cards use it); what
these pin down is the *reversible* path: the command restores mixed states
exactly, a hidden edge leaves the selection, the chunk fingerprint SEES the
flag (a stale chunk would keep drawing the line inside groups), and the flag
round-trips through the ``.igz``. Plus the Shift+eraser gesture: hide the
stroke, not erase it, as one undo step.

Headless: commands against a ``Scene``; the fingerprint via the staticmethod.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import HideEdgesCommand, History
from core.scene import Scene


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _square(detect_faces: bool = True):
    scene = Scene()
    hist = History(scene)
    sq = [V(0, 0), V(2, 0), V(2, 2), V(0, 2)]
    hist.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)],
        detect_faces=detect_faces))
    return scene, hist


def test_hide_and_undo_restores_mixed_states():
    scene, hist = _square()
    e0, e1 = scene.mesh.edges[0], scene.mesh.edges[1]
    e1.hidden = True                       # already hidden (mixed selection)

    hist.execute(HideEdgesCommand([e0, e1], hidden=True))
    assert e0.hidden and e1.hidden

    assert hist.undo() is True
    assert not e0.hidden                   # back to visible
    assert e1.hidden                       # was hidden before: stays hidden


def test_unhide_and_redo():
    scene, hist = _square()
    edges = scene.mesh.edges[:2]
    hist.execute(HideEdgesCommand(edges, hidden=True))
    hist.execute(HideEdgesCommand(edges, hidden=False))
    assert not any(e.hidden for e in edges)
    hist.undo()
    assert all(e.hidden for e in edges)
    assert hist.redo() is True
    assert not any(e.hidden for e in edges)


def test_hiding_drops_edges_from_selection():
    scene, hist = _square()
    e0 = scene.mesh.edges[0]
    scene.selection.add(e0)
    hist.execute(HideEdgesCommand([e0], hidden=True))
    assert e0 not in scene.selection
    # The face survives untouched: hiding is a render flag, not topology.
    assert len(scene.faces) == 1
    assert len(scene.mesh.edges) == 4


def test_fingerprint_sees_hidden_edges():
    """A hide toggle inside a group must invalidate its cached chunk — the
    fingerprint carries an index-sensitive hidden term (a count would call
    "hide A, undo, hide B" unchanged and serve the stale VBO)."""
    from views.viewport import Viewport
    scene, _ = _square()
    mesh = scene.mesh
    fp0 = Viewport._mesh_fingerprint(mesh)

    mesh.edges[0].hidden = True
    fp_a = Viewport._mesh_fingerprint(mesh)
    assert fp_a != fp0

    mesh.edges[0].hidden = False
    mesh.edges[1].hidden = True            # same count, different edge
    fp_b = Viewport._mesh_fingerprint(mesh)
    assert fp_b != fp_a and fp_b != fp0

    mesh.edges[1].hidden = False
    assert Viewport._mesh_fingerprint(mesh) == fp0


def test_hidden_round_trips_through_igz(tmp_path):
    from formats import igz
    scene, _ = _square()
    scene.mesh.edges[2].hidden = True
    path = tmp_path / "hidden.igz"
    igz.save_scene(scene, path)
    loaded = Scene()
    igz.load_into(loaded, path)
    assert sum(1 for e in loaded.mesh.edges
               if getattr(e, "hidden", False)) == 1


class _FakeViewport:
    """Just enough viewport for the eraser's release path."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass


def test_eraser_shift_stroke_hides_instead_of_erasing():
    from tools.eraser import EraserTool
    scene, _ = _square()
    vp = _FakeViewport(scene)
    tool = EraserTool()
    tool._stroke = True
    tool._hide = True                      # Shift was down at press
    tool.marked = set(scene.mesh.edges[:2])
    tool.on_release(vp)
    assert len(scene.mesh.edges) == 4      # nothing erased
    assert len(scene.faces) == 1           # the face is still there
    assert sum(1 for e in scene.mesh.edges if e.hidden) == 2
    vp.history.undo()                      # one undo step for the stroke
    assert not any(e.hidden for e in scene.mesh.edges)
