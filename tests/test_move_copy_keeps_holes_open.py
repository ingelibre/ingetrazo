# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Move copy keeps open what the original had open.

The edges of a copied face are planned like drawn lines (#379), and the
planner faces every loop it closes. A hole's rim is such a loop, so a
frame (a ring pushed into a slab) copied with Move+Ctrl, or arrayed with
«5x», came out with its opening faced over on both sides.
"""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.scene import Scene
from tools.move import MoveTool
from tests.test_move_copy import _ctx, _Vp

OUTER = [(0, 0), (1.4, 0), (1.4, 2), (0.7, 2.8), (0, 2)]
INNER = [(0.1, 0.1), (1.3, 0.1), (1.3, 1.95), (0.7, 2.66), (0.1, 1.95)]
T = 0.1                                   # the frame's thickness (along X)


def _p(x, yz):
    return QVector3D(float(x), float(yz[0]), float(yz[1]))


def _frame(scene):
    m = scene.mesh
    m.add_face([_p(0, q) for q in OUTER], [[_p(0, q) for q in INNER]])
    m.add_face([_p(T, q) for q in reversed(OUTER)],
               [[_p(T, q) for q in reversed(INNER)]])
    for ring in (OUTER, INNER):
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            m.add_face([_p(0, a), _p(0, b), _p(T, b), _p(T, a)])


def _faces_per_piece(scene, step):
    return Counter(round(min(v.x() for v in f.vertices) / step)
                   for f in scene.mesh.faces)


def _copy(scene, step):
    scene.selection = list(scene.mesh.faces) + list(scene.mesh.edges)
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, step, 0))
    return vp, tool


def test_a_copied_frame_keeps_its_opening():
    scene = Scene()
    _frame(scene)
    assert len(scene.mesh.faces) == 12
    _copy(scene, 0.5)
    assert _faces_per_piece(scene, 0.5) == {0: 12, 1: 12}


def test_an_array_of_frames_keeps_every_opening():
    scene = Scene()
    _frame(scene)
    vp, tool = _copy(scene, 0.5)
    assert tool.on_array_value(vp, 5, "x")
    assert _faces_per_piece(scene, 0.5) == {k: 12 for k in range(6)}
    vp.history.undo()
    assert len(scene.mesh.faces) == 12


def test_a_copied_flat_ring_keeps_its_hole():
    scene = Scene()
    scene.mesh.add_face([_p(0, q) for q in OUTER], [[_p(0, q) for q in INNER]])
    _copy(scene, 0.5)
    faces = list(scene.mesh.faces)
    assert len(faces) == 2 and all(len(f.holes) == 1 for f in faces)
