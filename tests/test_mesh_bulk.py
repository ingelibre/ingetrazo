# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The bulk mesh builders (Mesh.bulk_weld / add_faces_welded) must produce
exactly what the sequential add_face path produces — same vertices (welds
included), same edge order/orientation/incidence, same faces and attrs.
The import and .igz-load fast paths depend on this equivalence."""
import random

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

from core.mesh import Mesh


def _gen_faces(n, seed):
    """A grid of quads with sub-weld-tolerance jitter (some corners cross
    key-cell boundaries — the hard welding cases), plus a face with a hole
    and a degenerate sliver whose corners weld to one vertex."""
    rng = random.Random(seed)
    faces = []
    for i in range(n):
        x, y = (i % 10) * 1.0, (i // 10) * 1.0
        quad = [(x, y, 0.0), (x + 1, y, 0.0), (x + 1, y + 1, 0.0),
                (x, y + 1, 0.0)]
        quad = [(px + rng.uniform(-9e-5, 9e-5), py + rng.uniform(-9e-5, 9e-5),
                 pz + rng.uniform(-9e-5, 9e-5)) for px, py, pz in quad]
        faces.append((quad, [], {"color": [0.5, 0.2, 0.1]}
                      if i % 3 == 0 else None))
    faces.append(([(20, 0, 0), (24, 0, 0), (24, 4, 0), (20, 4, 0)],
                  [[(21, 1, 0), (22, 1, 0), (22, 2, 0), (21, 2, 0)]],
                  {"mat": "X"}))
    faces.append(([(30, 0, 0), (30 + 1e-6, 0, 0), (30, 1e-6, 0)], [], None))
    return faces


def _build_sequential(faces):
    mesh = Mesh()
    for outer, holes, attrs in faces:
        f = mesh.add_face([QVector3D(*p) for p in outer],
                          [[QVector3D(*p) for p in h] for h in holes] or None)
        if attrs:
            f.attrs.update(attrs)
    return mesh


def _build_bulk(faces):
    mesh = Mesh()
    flat, ring_sizes, ring_counts, attrs_list = [], [], [], []
    for outer, holes, attrs in faces:
        rings = [outer] + list(holes)
        ring_counts.append(len(rings))
        for r in rings:
            ring_sizes.append(len(r))
            flat.extend(r)
        attrs_list.append(attrs)
    mesh.add_faces_bulk(np.array(flat, dtype=np.float64),
                        ring_sizes, ring_counts, attrs_list)
    return mesh


def _fingerprint(mesh):
    def pk(p):
        return (p.x(), p.y(), p.z())

    fidx = {id(f): i for i, f in enumerate(mesh.faces)}
    return {
        "verts": [pk(v.position) for v in mesh.vertices],
        "faces": [([pk(v.position) for v in f.loop],
                   [[pk(v.position) for v in h] for h in f.hole_loops],
                   sorted(f.attrs.items(), key=str)) for f in mesh.faces],
        "edges": [(pk(e.v0.position), pk(e.v1.position), e.soft, e.curve,
                   [fidx[id(x)] for x in e.faces]) for e in mesh.edges],
    }


@pytest.mark.parametrize("seed", range(8))
def test_bulk_faces_match_sequential(seed):
    faces = _gen_faces(120, seed)
    seq = _fingerprint(_build_sequential(faces))
    blk = _fingerprint(_build_bulk(faces))
    # Vertex creation ORDER may differ (non-candidate cells build first);
    # the welded SET, and everything faces/edges reference, must not.
    assert sorted(seq.pop("verts")) == sorted(blk.pop("verts"))
    assert seq == blk


def test_bulk_edges_dedup_flags_and_degenerates():
    mesh = Mesh()
    pos = np.array([(0, 0, 0), (1, 0, 0),          # edge A
                    (1, 0, 0), (0, 0, 0),          # duplicate, reversed
                    (2, 0, 0), (2 + 1e-6, 0, 0)],  # degenerate: welds shut
                   dtype=np.float64)
    vobjs, ids = mesh.bulk_weld(pos)
    flags = [(True, 7, None), (False, None, "L1"), (False, None, None)]
    mesh.add_edges_welded(vobjs, ids[0::2], ids[1::2], flags)
    assert len(mesh.edges) == 1                    # dedup + degenerate skip
    e = mesh.edges[0]
    assert e.soft is True and e.curve == 7 and e.layer == "L1"


def test_bulk_weld_reuses_preexisting_vertices():
    mesh = Mesh()
    v0 = mesh.vertex(QVector3D(0.0, 0.0, 0.0))
    vobjs, ids = mesh.bulk_weld(np.array([(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)]))
    assert vobjs[ids[0]] is v0
    assert len(mesh.vertices) == 2


@pytest.mark.parametrize("gauge", [0.0003048, 0.000381],
                         ids=["12mil-tape", "15mil-flashing"])
def test_indexed_thin_film_retains_short_edges_and_enclosed_volume(gauge):
    # A 1 m long triangular nib, 0.05 mm wide, on a real-gauge film.
    # Its shared topology is authoritative even though the short edges fall
    # inside the ordinary sticky-geometry weld distance.
    pos = np.array([(20, 12, 3), (21, 12, 3), (21, 12.00005, 3),
                    (20, 12, 3 + gauge), (21, 12, 3 + gauge),
                    (21, 12.00005, 3 + gauge)], dtype=np.float64)
    triangles = np.array([(0, 2, 1), (3, 4, 5), (0, 1, 4), (0, 4, 3),
                          (1, 2, 5), (1, 5, 4), (2, 0, 3), (2, 3, 5)])
    mesh = Mesh()
    mesh.add_faces_indexed(pos, triangles.reshape(-1), [3] * 8, [1] * 8)

    assert len(mesh.vertices) == 6
    assert len(mesh.edges) == 12
    assert len(mesh.faces) == 8
    assert all(len(e.faces) == 2 and e.v0 is not e.v1 for e in mesh.edges)
    live = np.array([v.position.toTuple() for v in mesh.vertices])
    assert np.ptp(live[:, 2]) == pytest.approx(gauge, abs=2e-7)
    drawn = np.array([[p.toTuple() for p in tri] for f in mesh.faces
                      for tri in f.triangulate()])
    assert len(drawn) == 8
    # Measure the actual rendered triangles, centred to avoid cancellation
    # in this small volume at house-scale world coordinates.
    drawn -= live[0]
    volume = np.einsum("ij,ij->i", drawn[:, 0],
                       np.cross(drawn[:, 1], drawn[:, 2])).sum() / 6
    expected = np.prod(np.ptp(live, axis=0)) / 2
    assert volume == pytest.approx(expected, rel=1e-6)


def test_indexed_snapshot_keeps_same_cell_vertices_available_for_drawing():
    mesh = Mesh()
    mesh.add_faces_indexed(
        np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                  (0, 0, 0), (-1, 0, 0), (0, -1, 0),
                  (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
        np.arange(9), [3, 3, 3], [1, 1, 1])
    first, second, third = mesh.vertices[0::3]
    snap = mesh.capture_state()
    mesh.move_vertex(first, QVector3D(0, 0, 1))
    mesh.restore_state(snap)
    mesh.move_vertex(first, QVector3D(0, 0, 2))
    assert mesh.vertex(QVector3D()) is second
    mesh.move_vertex(second, QVector3D(0, 0, 3))
    assert mesh.vertex(QVector3D()) is third
    assert len(mesh.vertices) == 9
