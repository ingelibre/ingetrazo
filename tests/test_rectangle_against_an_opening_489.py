# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A rectangle drawn on a ring's top against the opening's rim (#489,
@soulerblood's second video: triangles appeared in the opening after the
next pushes). The rectangle was punched as a second hole sharing an edge
with the first, which triangulates into slivers over both. The opening
must grow to take it in instead, and undo must give the old one back."""
from __future__ import annotations

from collections import Counter

from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import History
from core.orient import is_closed
from core.scene import Scene
from tests import test_pushpull_ux as T

_RECT = [V(1.5, 3, 1), V(1.5, 3.6, 1), V(2.5, 3.6, 1), V(2.5, 3, 1)]


def _ring():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)],
                        [[V(1, 1, 0), V(1, 3, 0), V(3, 3, 0), V(3, 1, 0)]])
    T._push(scene, scene.mesh.faces[0], 1.0)
    return scene, hist


def _top(scene):
    return [f for f in scene.mesh.faces
            if all(abs(v.z() - 1) < 1e-6 for v in f.vertices)]


def _state(scene):
    return sorted((round(f.area(), 6), len(f.holes),
                   tuple(len(h) for h in f.holes)) for f in _top(scene))


def test_the_opening_grows_to_take_the_rectangle_in():
    scene, hist = _ring()
    before = _state(scene)
    hist.execute(build_add_edges(
        scene, list(zip(_RECT, _RECT[1:])), detect_faces=True))
    ring = next(f for f in _top(scene) if f.holes)
    assert len(ring.holes) == 1 and len(ring.holes[0]) == 8
    assert abs(ring.area() - 16.0) < 1e-6
    assert any(abs(f.area() - 0.6) < 1e-6 and not f.holes
               for f in _top(scene))
    assert set(Counter(len(e.faces) for e in scene.mesh.edges)) == {2}
    assert is_closed(scene.mesh)
    after = _state(scene)
    hist.undo()
    assert _state(scene) == before
    hist.redo()
    assert _state(scene) == after
