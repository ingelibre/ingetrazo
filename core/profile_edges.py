# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Align adjacent face planes for silhouette tests without changing faces.

Two consistently wound faces walk their shared edge in opposite directions.
Compensating for that traversal makes the view-side test independent of which
side the user chose as the front, including on an open or concave surface.
"""
from __future__ import annotations

import numpy as np


def edge_normal_sign(edge, windings: dict) -> int:
    """Sign to apply to the second normal; cache loop walks for this build."""
    if len(edge.faces) != 2:
        return 1

    def along(face):
        if face not in windings:
            from core.mesh import Face
            from PySide6.QtGui import QVector3D

            directed = set()
            outer_normal = None
            for ring in (face.loop, *face.hole_loops):
                if not ring:
                    continue
                # Holes bound the opposite side of their loop. Importers may
                # supply either winding; normalize only this display lookup.
                if ring is face.loop:
                    reverse = False
                else:
                    if outer_normal is None:
                        outer_normal = face.normal()
                    reverse = QVector3D.dotProduct(Face(ring).normal(), outer_normal) > 0
                for a, b in zip(ring, ring[1:] + ring[:1]):
                    directed.add((b, a) if reverse else (a, b))
            windings[face] = directed
        return (edge.v0, edge.v1) in windings[face]

    return -1 if along(edge.faces[0]) == along(edge.faces[1]) else 1


def plan_normal_signs(plan) -> np.ndarray:
    """The same signs from deferred arrays, without building mesh topology."""
    signs = np.ones(len(plan.edges), dtype=np.int8)
    if not len(plan.corners):
        return signs
    ends = np.cumsum(plan.ring_sizes)
    starts = ends - plan.ring_sizes
    nxt = np.arange(1, len(plan.corners) + 1)
    nxt[ends - 1] = starts
    a, b = plan.corners, plan.corners[nxt]
    direction = np.where(a < b, 1, -1)
    if np.any(plan.ring_counts > 1):
        ring_normals = np.add.reduceat(np.cross(plan.pos[a], plan.pos[b]), starts)
        first = np.r_[0, np.cumsum(plan.ring_counts)[:-1]]
        outer = np.repeat(ring_normals[first], plan.ring_counts, axis=0)
        reverse = np.einsum("ij,ij->i", ring_normals, outer) > 0
        reverse[first] = False
        direction *= np.repeat(np.where(reverse, -1, 1), plan.ring_sizes)
    size = len(plan.pos)
    keys = np.minimum(a, b) * size + np.maximum(a, b)
    order = np.argsort(keys, kind="stable")
    unique, first, counts = np.unique(keys[order], return_index=True, return_counts=True)
    paired = counts == 2
    pair_signs = np.ones(len(unique), dtype=np.int8)
    pair_signs[paired] = -direction[order[first[paired]]] * direction[order[first[paired] + 1]]
    edge_keys = plan.edges.min(axis=1) * size + plan.edges.max(axis=1)
    indices = np.searchsorted(unique, edge_keys)
    found = indices < len(unique)
    found[found] &= unique[indices[found]] == edge_keys[found]
    signs[found] = pair_signs[indices[found]]
    return signs
