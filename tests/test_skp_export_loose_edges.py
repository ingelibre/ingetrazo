# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Edges that bound no face reach the .skp (issue #137, @pacaeiro: «edges
without face are not exported to .skp» — the path circles of the sphere
file). A circle goes out as one curve, closed; a lone line on its own."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import History, TagCurveCommand
from core.scene import Scene
from formats import skp_out as skp_out_format
from tests.test_skp_export import _cube, _parse_skp

IN = 0.0254


def _loose(model):
    return [e for e in model.root.edges if not getattr(e, "faces", None)]


def _scene():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)                                  # faces: unchanged
    pts = [V(10 + 2 * math.cos(2 * math.pi * k / 24),
             2 * math.sin(2 * math.pi * k / 24), 0) for k in range(24)]
    hist.execute(build_add_edges(
        scene, [(pts[k], pts[(k + 1) % 24]) for k in range(24)],
        detect_faces=False, extra=[TagCurveCommand(list(pts), closed=True)]))
    hist.execute(build_add_edges(scene, [(V(-5, 0, 0), V(-5, 3, 2))],
                                 detect_faces=False))
    return scene


def test_face_less_edges_are_exported(tmp_path):
    scene = _scene()
    free = [e for e in scene.mesh.edges if not e.faces]
    assert len(free) == 25                              # 24 + 1
    path = tmp_path / "loose.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    assert len(model.root.faces) >= 6                   # the cube is there
    root = model.root
    verts = root.vertices

    def key(v):
        return (round(v.x, 1), round(v.y, 1), round(v.z, 1))

    written = {frozenset((key(verts[e.v1_id]), key(verts[e.v2_id]))): e
               for e in root.edges.values()}
    ring_curves = set()
    for e in free:
        a = tuple(round(c / IN, 1) for c in (e.a.x(), e.a.y(), e.a.z()))
        b = tuple(round(c / IN, 1) for c in (e.b.x(), e.b.y(), e.b.z()))
        got = written.get(frozenset((a, b)))
        assert got is not None, (a, b)
        if e.curve is not None:
            ring_curves.add(got.curve_id)
    assert len(ring_curves) == 1 and None not in ring_curves   # one curve


def test_the_circle_chains_into_one_ring():
    from formats.skp_out import _loose_edge_runs
    runs = _loose_edge_runs(_scene().mesh)
    rings = [r for r in runs if r[1]]
    lines = [r for r in runs if not r[1]]
    assert len(rings) == 1 and len(rings[0][0]) == 24
    # In inches, like every other point written (2 m radius = 78.7 in).
    assert abs(max(p[0] for p in rings[0][0]) - 12 / IN) < 1e-3
    assert len(lines) == 1 and len(lines[0][0]) == 2
