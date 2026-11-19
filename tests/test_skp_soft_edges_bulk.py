# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bulk flag resolution matches the original final-registry lookup exactly."""
from types import SimpleNamespace

import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.mesh import Mesh
from core.scene import Scene
from formats import igz, skp, skp_openskp


_IDENTITY = QMatrix4x4()


def _payload():
    source = SimpleNamespace(
        vertices={i: SimpleNamespace(x=x, y=y, z=0) for i, (x, y) in enumerate(
            [(0, 0), (40, 0), (40, 40), (0, 40)])},
        edges={i: SimpleNamespace(v1_id=i, v2_id=(i + 1) % 4,
                                  soft=i == 0, hidden=i == 1, smooth=i == 2,
                                  curve_id=17 if i >= 2 else None)
               for i in range(4)})
    segments = []
    skp_openskp._soft_edge_segments(source, QMatrix4x4(), segments)
    square = skp_openskp._world_points(
        np.array([(v.x, v.y, v.z) for v in source.vertices.values()])
        * skp_openskp._INCH, QMatrix4x4())
    faces = [(square, [], {"color": [0.2, 0.4, 0.6], "back": True})]
    # A point first welds to the neighbouring cell; a later point claims
    # its own cell. vertex_at must resolve against that FINAL registry.
    a, b, c = (-4e-5, 0, 0), (5.1e-5, 0, 0), (14.9e-5, 0, 0)
    y, z = (0, 2, 0), (0, 0, 2)
    faces += [([p, y, z], [], {"mat": "Boundary"}) for p in (a, b, c)]
    segments += [(b, y), (y, b), (b, b), ((90, 90, 90), y)]
    for i in range(280):
        x = float(i + 3)
        ring = [(x, 0, 0), (x + 1, 0, 0), (x + 1, 1, 0), (x, 1, 0)]
        holes = [[(x + .2, .2, 0), (x + .4, .2, 0), (x + .4, .4, 0)]] \
            if i % 19 == 0 else []
        faces.append((ring, holes, {"layer": "Faces", "opacity": 0.5}))
        segments += [(ring[0], ring[1]), (ring[1], ring[0])]
    group = {"name": "Large", "faces": faces, "soft_edges": segments}
    proto = dict(group, name="Prototype", instances=[_IDENTITY, _IDENTITY],
                 children=[{"proto": 1, "xform": _IDENTITY}])
    child = {"name": "Child", "faces": faces[:1], "soft_edges": segments[:3],
             "instances": []}
    small = dict(child, name="Small")
    return {"groups": [group, small], "protos": [proto, child]}


def _reference_soften(mesh, vertices, edge_map, segments, tick):
    for k, (a, b) in enumerate(segments):
        if not k & 4095:
            tick()
        va = mesh.vertex_at(QVector3D(*a))
        vb = mesh.vertex_at(QVector3D(*b))
        if va is None or vb is None or va is vb:
            continue
        edge = mesh.find_edge(va, vb)
        if edge is not None:
            edge.soft = True


def _signature(scene):
    def group(g, path):
        # Imports create fresh UUIDs. Give both executions the same ids
        # before comparing their complete re-save bytes.
        g.uid = path
        mesh = g.mesh
        vid = {v: i for i, v in enumerate(mesh.vertices)}
        fid = {f: i for i, f in enumerate(mesh.faces)}
        return (g.name, g.xform.data() if g.xform is not None else None,
                [v.position.toTuple() for v in mesh.vertices],
                [(vid[e.v0], vid[e.v1], e.soft, e.hidden, e.curve, e.layer,
                  [fid[f] for f in e.faces]) for e in mesh.edges],
                [([vid[v] for v in f.loop], [[vid[v] for v in h] for h in f.hole_loops],
                  f.attrs) for f in mesh.faces],
                [group(c, f"{path}/{i}") for i, c in enumerate(g.children or [])])
    return [group(g, str(i)) for i, g in enumerate(scene.groups)]


def test_bulk_flags_match_original_lookup_and_resave(tmp_path, monkeypatch):
    original = Mesh.vertex_at
    calls = []

    def counted(mesh, position):
        calls.append(1)
        return original(mesh, position)

    monkeypatch.setattr(Mesh, "vertex_at", counted)
    expected, actual = Scene(), Scene()
    with monkeypatch.context() as mp:
        mp.setattr(skp, "_soften_bulk_edges", _reference_soften)
        skp.apply_payload(expected, _payload())
    old_calls = len(calls)
    calls.clear()
    skp.apply_payload(actual, _payload())
    assert len(calls) < old_calls // 4
    assert _signature(actual) == _signature(expected)
    assert actual.groups[2].mesh is actual.groups[3].mesh
    # The existing adapter maps soft, hidden and smooth to soft. Curve ids
    # are not imported; this optimization keeps that contract unchanged.
    for edge in actual.groups[0].mesh.edges[:4]:
        assert not edge.hidden and edge.curve is None
    assert [e.soft for e in actual.groups[0].mesh.edges[:4]] == [True, True, True, False]
    before, after = tmp_path / "before.igz", tmp_path / "after.igz"
    igz.save_scene(expected, before)
    igz.save_scene(actual, after)
    assert before.read_bytes() == after.read_bytes()


def test_bulk_flags_keep_reporting_inside_a_large_group(monkeypatch):
    import time

    ticks = iter(range(100000))
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks))
    payload = _payload()
    payload["groups"][0]["soft_edges"] *= 40
    reports = []
    scene = Scene()

    def progress(fraction, text):
        assert all(g.mesh.faces or g.children for g in scene.groups)
        reports.append(fraction)

    skp.apply_payload(scene, payload, progress)
    assert len(reports) > 10
    assert reports == sorted(reports)


def test_noisy_segments_match_final_lookup_without_changing_other_flags():
    for seed in range(20):
        rng = np.random.default_rng(seed)
        points = rng.integers(-3, 4, size=(90, 3)) * .5
        points += rng.choice([0, 4.9e-5, 5.1e-5, 1.49e-4], size=points.shape)
        segments = [(points[a] + noise, points[b])
                    for a, b, noise in zip(rng.integers(len(points), size=200),
                                            rng.integers(len(points), size=200),
                                            rng.choice([0, 1e-6, -1e-6], size=200))]
        meshes = []
        for soften in (_reference_soften, skp._soften_bulk_edges):
            mesh = Mesh()
            vertices, inverse = mesh.bulk_weld(points)
            edges = {}
            mesh.add_faces_welded(vertices, inverse, [3] * 30, [1] * 30, edge_map=edges)
            for i, edge in enumerate(mesh.edges):
                edge.hidden, edge.curve, edge.layer = i % 2 == 0, i + 10, "Edges"
            soften(mesh, vertices, edges, segments, lambda: None)
            meshes.append([(e.soft, e.hidden, e.curve, e.layer) for e in mesh.edges])
        assert meshes[0] == meshes[1]
