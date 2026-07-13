# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fast coplanar fusion for imported triangle soups (formats.fuse)."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from formats.fuse import fuse_coplanar_loops, soften_smooth_edges


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _grid_triangles(nx, ny, attrs=None):
    """A triangulated nx×ny quad grid on z=0 (2·nx·ny triangles)."""
    out = []
    for i in range(nx):
        for j in range(ny):
            a, b = V(i, j), V(i + 1, j)
            c, d = V(i + 1, j + 1), V(i, j + 1)
            out.append(([a, b, c], attrs))
            out.append(([a, c, d], attrs))
    return out


def test_grid_fuses_to_one_face():
    fused = fuse_coplanar_loops(_grid_triangles(4, 3))
    assert len(fused) == 1
    outer, holes, attrs, originals = fused[0]
    assert not holes
    assert len(originals) == 24
    # Rectangle boundary: every vertex on the perimeter of the 4×3 grid.
    assert all(p.x() in (0.0, 4.0) or p.y() in (0.0, 3.0) for p in outer)


def test_hole_is_traced():
    # Grid with the middle cell missing → one face with one hole.
    loops = [t for t in _grid_triangles(3, 3)
             if not all(1.0 <= p.x() <= 2.0 and 1.0 <= p.y() <= 2.0
                        for p in t[0])]
    fused = fuse_coplanar_loops(loops)
    assert len(fused) == 1
    outer, holes, _attrs, _orig = fused[0]
    assert len(holes) == 1
    assert len(holes[0]) == 4


def test_material_boundary_splits_regions():
    red = {"color": [1.0, 0.0, 0.0]}
    loops = _grid_triangles(2, 1, None) + [
        ([V(2, 0), V(3, 0), V(3, 1)], red),
        ([V(2, 0), V(3, 1), V(2, 1)], red),
    ]
    fused = fuse_coplanar_loops(loops)
    assert len(fused) == 2
    assert {f[2] and f[2].get("color") is not None for f in fused} == {False, True} or \
           sorted(len(f[3]) for f in fused) == [2, 4]


def test_crease_is_not_merged():
    # Two quads meeting at a 90° fold stay two faces.
    loops = [([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)], None),
             ([V(0, 0, 0), V(1, 1, 0), V(0, 1, 0)], None),
             ([V(0, 0, 0), V(1, 0, 0), V(1, 0, 1)], None),
             ([V(0, 0, 0), V(1, 0, 1), V(0, 0, 1)], None)]
    fused = fuse_coplanar_loops(loops)
    assert len(fused) == 2
    assert all(len(f[3]) == 2 for f in fused)


def test_soften_smooth_edges_marks_shallow_dihedrals():
    from core.mesh import Mesh
    m = Mesh()
    # Nearly-flat pair (fold of ~5°) + a hard 90° corner.
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0.05), V(0, 1, 0.05)])
    m.add_face([V(0, 1, 0.05), V(1, 1, 0.05), V(1, 2, 0.0), V(0, 2, 0.0)])
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 1), V(0, 0, 1)])
    soften_smooth_edges(m)
    soft = [e for e in m.edges if e.soft]
    assert len(soft) == 1
    ys = {round(soft[0].a.y(), 2), round(soft[0].b.y(), 2)}
    assert ys == {1.0}                      # the shallow fold, not the corner
