# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A.3 — Face.attrs survive the engine's face churn (region inheritance).

The rebuild/dissolve/dedupe/fold paths delete and re-create faces; anything a
user hangs on a face (a material today, a BIM tag tomorrow) must ride along:
each new face inherits the attrs of the face it is the continuation of —
decided by region (interior-point containment) in the plane rebuild, by
dominant contributor (largest area with attrs) in merges, by the mother in
folds and subdivisions. This is the DoD of next-session item A.3; Materials
(Fase 7) builds on it.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History, MoveVerticesCommand
from core.mesh import Mesh
from core.orient import is_closed
from core.scene import Scene
from tests.test_fuzz_engine import V, _draw_rect, _push, _up

RED = {"color": "red"}


def _cube_scene(size=4.0, height=3.0):
    scene = Scene()
    hist = History(scene)
    user: list = []
    _draw_rect(scene, hist, [V(0, 0), V(size, 0), V(size, size), V(0, size)],
               user)
    f = scene.mesh.faces[0]
    _push(scene, hist, f, _up(f, height))
    return scene, hist, user


def _top(scene, z):
    return next(f for f in scene.mesh.faces
                if all(abs(v.z() - z) < 1e-6 for v in f.vertices))


# ---- re-push of the cap (extend) ---------------------------------------------

def test_attrs_survive_prism_extend():
    scene, hist, _user = _cube_scene()
    top = _top(scene, 3.0)
    top.attrs = dict(RED)
    _push(scene, hist, top, 1.0)           # prism translate: cube gets taller
    assert _top(scene, 4.0).attrs == RED


def test_attrs_survive_extrude_path_repush():
    # A sub-rect on the top forces the extrude path (not a prism translate):
    # the moved cap is a new face and must continue the consumed base's attrs.
    scene, hist, user = _cube_scene()
    _draw_rect(scene, hist, [V(1, 1, 3), V(2, 1, 3), V(2, 2, 3), V(1, 2, 3)],
               user)
    block = next(f for f in scene.mesh.faces
                 if len(f.vertices) == 4 and not f.holes
                 and all(abs(v.z() - 3) < 1e-6 for v in f.vertices)
                 and max(v.x() for v in f.vertices) <= 2.001)
    block.attrs = dict(RED)
    n = block.normal()
    _push(scene, hist, block, 1.0 if n.z() > 0 else -1.0)
    raised = _top(scene, 4.0)
    assert raised.attrs == RED


# ---- notch: the trimmed floor keeps its attrs ----------------------------------

def test_attrs_survive_corner_notch_through_floor():
    scene, hist, user = _cube_scene(size=10.0, height=3.0)
    floor = next(f for f in scene.mesh.faces
                 if all(abs(v.z()) < 1e-6 for v in f.vertices))
    floor.attrs = dict(RED)
    corner = [V(0, 0, 3), V(4, 0, 3), V(4, 4, 3), V(0, 4, 3)]
    _draw_rect(scene, hist, corner, user)
    cface = next(f for f in scene.mesh.faces
                 if len(f.vertices) == 4 and not f.holes
                 and all(abs(v.z() - 3) < 1e-6 for v in f.vertices)
                 and max(v.x() for v in f.vertices) <= 4.001
                 and max(v.y() for v in f.vertices) <= 4.001)
    n = cface.normal()
    _push(scene, hist, cface, -99.0 if n.z() > 0 else 99.0)  # clamped flush
    floors = [f for f in scene.mesh.faces
              if all(abs(v.z()) < 1e-6 for v in f.vertices)]
    assert len(floors) == 1 and len(floors[0].vertices) == 6  # the L
    assert floors[0].attrs == RED


# ---- flush-dissolve: the host wall rebuilt by the collapse keeps attrs ---------

def test_attrs_survive_bump_flush_dissolve():
    scene, hist, user = _cube_scene()
    wall = next(f for f in scene.mesh.faces
                if all(abs(v.y()) < 1e-6 for v in f.vertices))
    wall.attrs = dict(RED)
    _draw_rect(scene, hist, [V(1, 0, 1), V(2, 0, 1), V(2, 0, 2), V(1, 0, 2)],
               user)
    rect = next(f for f in scene.mesh.faces
                if len(f.vertices) == 4 and not f.holes
                and all(abs(v.y()) < 1e-6 for v in f.vertices)
                and 0.9 < f.centroid().x() < 2.1)
    n = rect.normal()
    _push(scene, hist, rect, 1.0 if n.y() < 0 else -1.0)   # bump out
    bump_cap = next(f for f in scene.mesh.faces
                    if all(abs(v.y() + 1) < 1e-6 for v in f.vertices))
    n = bump_cap.normal()
    _push(scene, hist, bump_cap, -1.0 if n.y() < 0 else 1.0)  # flush back
    m = scene.mesh
    assert is_closed(m) and len(m.faces) == 6   # pristine cube again
    healed = next(f for f in m.faces
                  if all(abs(v.y()) < 1e-6 for v in f.vertices))
    assert healed.attrs == RED


# ---- fold: both planar pieces continue the warped mother -----------------------

def test_attrs_survive_autofold():
    scene = Scene()
    hist = History(scene)
    face = scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    face.attrs = dict(RED)
    hist.execute(MoveVerticesCommand([V(2, 2, 0)], QVector3D(0, 0, 1)))
    m = scene.mesh
    assert len(m.faces) == 2
    assert all(f.attrs == RED for f in m.faces)


# ---- dedupe: the survivor carries the dropped duplicate's attrs ----------------

def test_attrs_survive_dedupe():
    m = Mesh()
    outer = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    plain = m.add_face(outer)
    dup = m.add_face(list(outer))
    dup.attrs = dict(RED)
    assert m.dedupe_faces() == 1
    survivor = m.faces[0]
    assert survivor.attrs == RED


# ---- merges keep the dominant contributor's attrs ------------------------------

def test_attrs_survive_coplanar_dissolve():
    m = Mesh()
    big = m.add_face([V(0, 0), V(3, 0), V(3, 2), V(0, 2)])
    small = m.add_face([V(3, 0), V(4, 0), V(4, 2), V(3, 2)])
    big.attrs = dict(RED)
    small.attrs = {"color": "blue"}
    merged = m.dissolve_coplanar_region([big, small])
    assert merged is not None
    assert merged.attrs == RED              # largest-area contributor wins


# ---- snapshots (undo/redo) round-trip attrs ------------------------------------

def test_attrs_survive_snapshot_roundtrip():
    scene, hist, _user = _cube_scene()
    top = _top(scene, 3.0)
    top.attrs = dict(RED)
    snap = scene.mesh.capture_state()
    top.attrs = {"color": "blue"}
    scene.mesh.restore_state(snap)
    assert top.attrs == RED


def test_flip_faces_command_reverses_winding_and_undoes():
    # SketchUp's Reverse Faces: flips the normal, undo flips back, identity
    # of the Face object is preserved throughout.
    from core.history import FlipFacesCommand, History
    from core.scene import Scene
    from PySide6.QtGui import QVector3D

    scene = Scene()
    hist = History(scene)
    face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                                QVector3D(1, 1, 0)])
    assert face.normal().z() > 0
    hist.execute(FlipFacesCommand([face]))
    assert face.normal().z() < 0          # flipped
    assert face in scene.mesh.faces       # same object, still in the mesh
    hist.undo()
    assert face.normal().z() > 0          # back
    hist.redo()
    assert face.normal().z() < 0
