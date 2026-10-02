# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The GPU profile pass decides like the NumPy one.

``silhouette.vert`` gets, per soft edge, the two face planes ``n·p = d`` in
the prototype's coordinates and a ``single`` flag, and marks the edge a
profile when the eye — taken into those coordinates through the inverse of
the placement matrix — sees one face from the front and the other from the
back. ``_sil_vertex_array`` lays those numbers out; this replays the
shader's arithmetic in NumPy over random meshes, placements (rotations,
non-uniform scales, mirrors) and eyes, and asks the same question the way
``_instanced_silhouettes`` asks it. Both answers must agree on every edge.

Headless: NumPy only — the GL side is checked by rendering both paths of a
real model to images (0 differing pixels on three orbit views, 2026-10-02).
"""
from __future__ import annotations

import numpy as np
import pytest

from views.viewport import _sil_vertex_array


def _chunk(rng, n):
    seg = rng.normal(size=(n, 2, 3)) * 3.0
    n0 = rng.normal(size=(n, 3))
    n0 /= np.linalg.norm(n0, axis=1)[:, None]
    n1 = rng.normal(size=(n, 3))
    n1 /= np.linalg.norm(n1, axis=1)[:, None]
    c0 = seg[:, 0] + rng.normal(size=(n, 3)) * 0.1      # a point on each face
    c1 = seg[:, 1] + rng.normal(size=(n, 3)) * 0.1
    single = rng.random(n) < 0.1
    return {"soft_pts": seg.astype(np.float32).reshape(n, 6),
            "soft_n0": n0, "soft_c0": c0, "soft_n1": n1, "soft_c1": c1,
            "soft_single": single}


def _placement(rng):
    a, b, c = rng.uniform(0, 2 * np.pi, 3)
    rx = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    rz = np.array([[np.cos(c), -np.sin(c), 0], [np.sin(c), np.cos(c), 0], [0, 0, 1]])
    scale = np.diag(rng.uniform(0.3, 3.0, 3) * rng.choice([-1, 1], 3))  # mirrors too
    m = np.eye(4)
    m[:3, :3] = rz @ ry @ rx @ scale
    m[:3, 3] = rng.uniform(-20, 20, 3)
    return m


def _numpy_mask(chunk, m, eye):
    """What _instanced_silhouettes draws: eye in local coordinates, the two
    faces straddle the view, or a single-faced edge."""
    inv = np.linalg.inv(m)
    eye_l = inv[:3, :3] @ eye + inv[:3, 3]
    n0 = np.asarray(chunk["soft_n0"]); n1 = np.asarray(chunk["soft_n1"])
    s0 = np.einsum("ij,ij->i", n0, np.asarray(chunk["soft_c0"]) - eye_l)
    s1 = np.einsum("ij,ij->i", n1, np.asarray(chunk["soft_c1"]) - eye_l)
    return np.asarray(chunk["soft_single"]) | ((s0 < 0) != (s1 < 0))


def _shader_mask(verts, m, eye):
    """silhouette.vert's arithmetic on the vertex array (float32, as the
    GPU sees it): s = d - n·eye_l per face; profile = single || signs differ."""
    inv = np.linalg.inv(m)
    eye_l = (inv[:3, :3] @ eye + inv[:3, 3]).astype(np.float32)
    v = verts[:, 0, :]                                 # both vertices agree
    s0 = v[:, 9] - v[:, 3:6] @ eye_l
    s1 = v[:, 10] - v[:, 6:9] @ eye_l
    return (v[:, 11] > 0.5) | ((s0 < 0) != (s1 < 0))


def test_vertex_layout():
    rng = np.random.default_rng(1)
    chunk = _chunk(rng, 50)
    verts = _sil_vertex_array(chunk)
    assert verts.shape == (50, 2, 12) and verts.dtype == np.float32
    seg = np.asarray(chunk["soft_pts"]).reshape(50, 2, 3)
    np.testing.assert_array_equal(verts[:, :, :3], seg.astype(np.float32))
    np.testing.assert_array_equal(verts[:, 0, 3:], verts[:, 1, 3:])  # per edge
    assert set(np.unique(verts[:, 0, 11])) <= {0.0, 1.0}


@pytest.mark.parametrize("seed", range(6))
def test_shader_decides_like_the_numpy_pass(seed):
    rng = np.random.default_rng(seed)
    chunk = _chunk(rng, 400)
    verts = _sil_vertex_array(chunk)
    for _ in range(8):
        m = _placement(rng)
        eye = rng.uniform(-30, 30, 3)
        want = _numpy_mask(chunk, m, eye)
        got = _shader_mask(verts, m, eye)
        # float32 vs float64 can only disagree where a face plane passes
        # within rounding of the eye — exclude those few from the strict
        # comparison and require them to be rare.
        inv = np.linalg.inv(m)
        eye_l = inv[:3, :3] @ eye + inv[:3, 3]
        s0 = np.einsum("ij,ij->i", chunk["soft_n0"], chunk["soft_c0"] - eye_l)
        s1 = np.einsum("ij,ij->i", chunk["soft_n1"], chunk["soft_c1"] - eye_l)
        sure = (np.abs(s0) > 1e-3) & (np.abs(s1) > 1e-3)
        assert sure.mean() > 0.99
        np.testing.assert_array_equal(got[sure], want[sure])
        assert got.any() and not got.all()             # a real mix of both
