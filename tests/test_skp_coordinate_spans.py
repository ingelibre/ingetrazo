# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Packed input must keep the established scalar/bulk topology and float bits."""
import pickle

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

from core.mesh import Mesh
from core.scene import Scene
from formats import igz, skp
from formats.skp_coordinates import PointRows, flatten_rings


@pytest.mark.parametrize('section', [slice(None), slice(None, None, -1),
    slice(None, None, 2), slice(None, None, -2), slice(5, 0, -2), slice(0, 0)])
def test_spans_preserve_bits_and_order_without_iterating(section, monkeypatch):
    source = np.array([[0., -0., 1e-42], [1.2, -2., 4.], [5., 6., 7.],
                       [8., 9., 10.], [11., 12., 13.], [14., 15., 16.]], np.float32)
    rows = PointRows(source)
    ring = pickle.loads(pickle.dumps(rows[section]))
    expected = np.array(list(ring), np.float32).reshape(-1, 3)
    monkeypatch.setattr(PointRows, '__iter__', lambda self: pytest.fail('row expansion'))
    actual = flatten_rings([rows[:0], ring], len(ring))
    assert actual.tobytes() == expected.tobytes()
    assert source.tobytes() == rows._coordinate_span()[0].tobytes()
    with pytest.raises(ValueError):
        rows._coordinate_span()[0][0, 0] = 17


def _signature(scene):
    result = []
    for i, group in enumerate(scene.groups):
        group.uid = str(i)
        mesh = group.mesh
        vid = {v: j for j, v in enumerate(mesh.vertices)}
        fid = {f: j for j, f in enumerate(mesh.faces)}
        result.append((
            [v.position.toTuple() for v in mesh.vertices],
            [(vid[e.v0], vid[e.v1], e.soft, [fid[f] for f in e.faces]) for e in mesh.edges],
            [([vid[v] for v in f.loop], [[vid[v] for v in h] for h in f.hole_loops], f.attrs)
             for f in mesh.faces]))
    return result


@pytest.mark.parametrize('count', [3, 400])
def test_mixed_payload_matches_legacy_weld_order_and_archive(count, tmp_path, monkeypatch):
    rings = []
    for i in range(count):
        # Include points on either side of weld-cell boundaries.
        x = i + (5.1e-5 if i % 2 else -4e-5)
        rings.append([(x, 0., -0.), (x + .9, 0., 0.), (x + .9, 1., 0.)])
    packed = PointRows(np.asarray(rings, np.float32).reshape(-1, 3))
    faces = []
    for i in range(count):
        ring = packed[3*i:3*i+3]
        if i % 2:
            ring = ring[::-1]
        if i % 5 == 0:
            ring = [QVector3D(*p) for p in ring]
        hole = [[(.2, .2, 0), (.4, .2, 0), (.3, .4, 0)]] if i == 0 else []
        faces.append((ring, hole, {'color': [.2, .4, .6]}))
    def payload(expand):
        def plain(r):
            return [p.toTuple() if hasattr(p, 'x') else list(p) for p in r]
        return {'groups': [{'name': 'Test', 'faces': [
            (plain(r) if expand else r, h, a) for r, h, a in faces], 'soft_edges': []}]}
    expected, actual = Scene(), Scene()
    # Reference the old flattening operation, retaining the same threshold.
    import formats.skp_coordinates as coordinates
    with monkeypatch.context() as mp:
        mp.setattr(coordinates, 'flatten_rings', lambda rr, size:
            np.array([p.toTuple() if hasattr(p, 'x') else p for r in rr for p in r],
                     dtype=np.float64).reshape(-1, 3))
        skp.apply_payload(expected, payload(True))
    calls = []
    original = Mesh.bulk_weld
    def weld(self, pos):
        calls.append(len(pos))
        return original(self, pos)
    monkeypatch.setattr(Mesh, 'bulk_weld', weld)
    skp.apply_payload(actual, payload(False))
    assert bool(calls) == (count == 400)
    assert _signature(actual) == _signature(expected)
    before, after = tmp_path/'before.igz', tmp_path/'after.igz'
    igz.save_scene(expected, before)
    igz.save_scene(actual, after)
    assert before.read_bytes() == after.read_bytes()


def test_adjacent_range_stops_do_not_imply_adjacent_strided_rows():
    rows = PointRows(np.arange(36, dtype=np.float32).reshape(-1, 3))
    for rings in ([rows[:5:2], rows[5:10:2]], [rows[10:5:-2], rows[5::-2]],
                  [rows[:6:2], rows[6::2]]):
        expected = np.asarray([p for r in rings for p in r], np.float32)
        actual = flatten_rings(rings, sum(map(len, rings)))
        assert actual.tobytes() == expected.tobytes()
