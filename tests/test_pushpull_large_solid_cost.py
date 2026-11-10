# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull on a solid that already has many features does each piece of
bookkeeping once, not once per question.

Measured on a slab with sixty 32-sided cylinders raised on it (2000 faces):
the sixtieth push took 1.9 s, and a third of it was asking the same thing
again — every face re-triangulated for each of its orientation probes (the
cap holed sixty times is 0.1 s of ear clipping each time), and that cap's
2000 edges listed anew for each of the 32 edges of the circle being pushed.

Counted, not timed: a count does not depend on the machine.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import History
from core.mesh import Face
from core.scene import Scene
from tests.test_pushpull_ux import _cube, _push


def _slab_with_cylinders(n: int):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, size=10.0, height=3.0)
    for i in range(n):
        _raise(scene, hist, _circle(scene, hist, i))
    return scene, hist


def _circle(scene, hist, i: int):
    cx, cy = 1.0 + (i % 5) * 1.8, 1.0 + (i // 5) * 1.8
    pts = [QVector3D(cx + 0.4 * math.cos(2 * math.pi * k / 32),
                     cy + 0.4 * math.sin(2 * math.pi * k / 32), 3.0)
           for k in range(32)]
    hist.execute(build_add_edges(
        scene, [(pts[k], pts[(k + 1) % 32]) for k in range(32)]))
    return next(
        f for f in scene.faces
        if len(f.vertices) == 32 and not f.holes
        and all(abs(v.z() - 3.0) < 1e-6 for v in f.vertices)
        and abs(f.centroid().x() - cx) < 1e-3
        and abs(f.centroid().y() - cy) < 1e-3)


def _raise(scene, hist, face):
    _push(scene, face, 0.5)


def test_an_orientation_pass_triangulates_each_face_once(monkeypatch):
    from core import orient

    scene, _hist = _slab_with_cylinders(4)
    # What earlier passes kept (a face whose corners have not moved is not
    # cut again at all) is forgotten, so this pass starts from nothing.
    orient._TRI_MEMO.pop(scene.mesh, None)
    calls = []
    real = Face.triangulate
    monkeypatch.setattr(
        Face, "triangulate",
        lambda self, *a, **k: calls.append(self) or real(self, *a, **k))
    assert orient.orient_outward(scene.mesh) == []      # already outward
    per_face = {}
    for f in calls:
        per_face[f] = per_face.get(f, 0) + 1
    assert set(per_face) == set(scene.mesh.faces)
    assert max(per_face.values()) == 1, "a face was triangulated again"
    # ... and the next pass, with nothing moved, cuts none.
    calls.clear()
    assert orient.orient_outward(scene.mesh) == []
    assert calls == []


def test_a_push_lists_each_neighbours_edges_once_per_question(monkeypatch):
    from core import topology

    scene, hist = _slab_with_cylinders(4)
    face = _circle(scene, hist, 4)
    seen = []
    real = topology._face_all_edges
    monkeypatch.setattr(
        topology, "_face_all_edges",
        lambda f: seen.append(f) or real(f))
    memo: dict = {}
    loop = face.vertices
    kinds = [topology.classify_push_edge(
        face, loop[i], loop[(i + 1) % 32], scene.faces, memo)
        for i in range(32)]
    assert all(kind == "coplanar" for kind, _g in kinds)
    assert len(seen) == len(set(seen)), "a face's edges were listed twice"


def test_the_memo_answers_what_the_plain_question_answers():
    """Same verdict, edge by edge and hole by hole, with and without it."""
    from core import topology

    scene, hist = _slab_with_cylinders(3)
    face = _circle(scene, hist, 3)
    top = next(f for f in scene.faces if f.holes)
    for subject in (face, top):
        for loop in (subject.vertices, *subject.holes):
            memo: dict = {}
            n = len(loop)
            for i in range(n):
                a, b = loop[i], loop[(i + 1) % n]
                assert (topology.classify_push_edge(subject, a, b,
                                                    scene.faces, memo)
                        == topology.classify_push_edge(subject, a, b,
                                                       scene.faces))
