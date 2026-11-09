# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section Fill covers the cut geometry and nothing else.

The fill used to be a per-pixel trick (the plane painted wherever a back
face was the visible surface), which also filled faces seen from behind
that the plane does not cut. It is now built from the cut itself: the
chords the plane takes out of the triangles, chained into closed rings,
holes left open. Every model here is generated."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QVector3D

from core.mesh import Mesh
from core.section import cut_chords, fill_triangles

_QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
          (0, 2, 6, 4), (1, 5, 7, 3)]
UP = QVector3D(0, 0, 1)


def _box(mesh, x0, y0, z0, sx, sy, sz):
    c = [QVector3D(x0 + dx * sx, y0 + dy * sy, z0 + dz * sz)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])


def _cut(meshes, z=1.0, normal=UP):
    """Plane z = ``z`` through every face of ``meshes``: (chords, fill)."""
    tris = [t for m in meshes for f in m.faces for t in f.triangulate()]
    a = np.array([[t[0].x(), t[0].y(), t[0].z()] for t in tris])
    b = np.array([[t[1].x(), t[1].y(), t[1].z()] for t in tris])
    c = np.array([[t[2].x(), t[2].y(), t[2].z()] for t in tris])
    chords = cut_chords(a, b - a, c - a, normal, QVector3D(0, 0, z))
    return chords, fill_triangles(chords, normal)


def _area(tris) -> float:
    if not len(tris):
        return 0.0
    t = tris.astype(np.float64)
    return float(0.5 * np.linalg.norm(
        np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum())


def _covers(tris, x, y) -> bool:
    for t in tris.astype(np.float64):
        (ax, ay), (bx, by), (cx, cy) = t[0, :2], t[1, :2], t[2, :2]
        d1 = (x - bx) * (ay - by) - (ax - bx) * (y - by)
        d2 = (x - cx) * (by - cy) - (bx - cx) * (y - cy)
        d3 = (x - ax) * (cy - ay) - (cx - ax) * (y - ay)
        neg = d1 < 0 or d2 < 0 or d3 < 0
        pos = d1 > 0 or d2 > 0 or d3 > 0
        if not (neg and pos):
            return True
    return False


def test_a_solid_box_fills_its_cross_section():
    m = Mesh()
    _box(m, 0, 0, 0, 2, 3, 2)
    _chords, fill = _cut([m])
    assert abs(_area(fill) - 6.0) < 1e-6
    assert np.allclose(fill[:, :, 2], 1.0)            # in the plane


def test_the_room_between_four_walls_stays_empty():
    """Four walls, each its own box, crossing at the corners: the walls
    are filled, the room they enclose is not."""
    walls = []
    for args in ((0, 0, 0, 8, 0.2, 3), (0, 5.8, 0, 8, 0.2, 3),
                 (0, 0, 0, 0.2, 6, 3), (7.8, 0, 0, 0.2, 6, 3)):
        m = Mesh()
        _box(m, *args)
        walls.append(m)
    _chords, fill = _cut(walls)
    assert _covers(fill, 4.0, 0.1)                     # in a wall
    assert _covers(fill, 0.1, 3.0)
    assert not _covers(fill, 4.0, 3.0)                 # the room
    assert _area(fill) < 0.2 * 8 * 2 + 0.2 * 6 * 2 + 1e-6


def test_a_hollow_wall_keeps_its_hole_and_a_column_inside_is_solid():
    """One mesh: a square tube (outer ring and inner ring of faces) with a
    column standing in its middle — solid, hole, solid again."""
    m = Mesh()
    o = [QVector3D(x, y, 0) for x, y in ((0, 0), (6, 0), (6, 6), (0, 6))]
    i = [QVector3D(x, y, 0) for x, y in ((1, 1), (5, 1), (5, 5), (1, 5))]
    for ring in (o, i):
        for k in range(4):
            a, b = ring[k], ring[(k + 1) % 4]
            m.add_face([a, b, b + QVector3D(0, 0, 3), a + QVector3D(0, 0, 3)])
    up = QVector3D(0, 0, 3)
    for k in range(4):                 # top and bottom bands of the tube
        for z in (QVector3D(), up):
            m.add_face([o[k] + z, o[(k + 1) % 4] + z,
                        i[(k + 1) % 4] + z, i[k] + z])
    col = Mesh()
    _box(col, 2.5, 2.5, 0, 1, 1, 3)
    _chords, fill = _cut([m, col])
    assert _covers(fill, 0.5, 3.0)                     # the tube's wall
    assert not _covers(fill, 1.8, 3.0)                 # its hollow
    assert _covers(fill, 3.0, 3.0)                     # the column
    assert abs(_area(fill) - (36 - 16 + 1)) < 1e-6


def test_an_open_surface_cut_by_the_plane_is_not_filled():
    m = Mesh()
    m.add_face([QVector3D(0, 0, 0), QVector3D(4, 0, 0),
                QVector3D(4, 0, 3), QVector3D(0, 0, 3)])      # a lone wall
    chords, fill = _cut([m])
    assert chords is not None and len(chords)          # it IS cut (a line)
    assert len(fill) == 0                              # but nothing to fill


def test_nothing_is_filled_where_the_plane_cuts_nothing():
    m = Mesh()
    _box(m, 0, 0, 2, 1, 1, 1)                          # above the plane
    chords, fill = _cut([m])
    assert chords is None and len(fill) == 0


def test_a_box_cut_on_a_slant_fills_in_its_own_plane():
    m = Mesh()
    _box(m, 0, 0, 0, 2, 2, 2)
    n = QVector3D(1, 0, 1).normalized()
    tris = [t for f in m.faces for t in f.triangulate()]
    a = np.array([[t[0].x(), t[0].y(), t[0].z()] for t in tris])
    b = np.array([[t[1].x(), t[1].y(), t[1].z()] for t in tris])
    c = np.array([[t[2].x(), t[2].y(), t[2].z()] for t in tris])
    chords = cut_chords(a, b - a, c - a, n, QVector3D(1, 1, 0.9))
    fill = fill_triangles(chords, n)
    d = fill.reshape(-1, 3).astype(np.float64) @ np.array(
        [n.x(), n.y(), n.z()]) - np.dot([n.x(), n.y(), n.z()], [1, 1, 0.9])
    assert np.abs(d).max() < 1e-5
    # x + z = 1.9 across a 2 m cube: a 1.9·√2 by 2 rectangle.
    assert abs(_area(fill) - 1.9 * 2 ** 0.5 * 2) < 1e-5


def test_the_viewport_fills_the_cut_and_keeps_it_across_a_selection():
    from PySide6.QtWidgets import QApplication
    from core.group import Group
    from core.section import SectionPlane
    from views.main_window import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    scene = win.viewport.scene
    m = Mesh()
    _box(m, 0, 0, 0, 2, 3, 2)
    scene.groups[:] = [Group(m, name="Block")]
    scene.section_planes[:] = [SectionPlane(QVector3D(0, 0, 1), UP,
                                            active=True)]
    scene.version += 1
    vp = win.viewport
    tris = vp._section_fill_tris()
    assert tris is not None and abs(_area(tris) - 6.0) < 1e-5
    scene.selection.add(scene.groups[0])
    scene.bump_view()                      # a click: new version, same cut
    assert vp._section_fill_tris() is tris
    win._saved_version = scene.version


# ---- Pattern, colour, spacing ------------------------------------------------

def _tube_and_column():
    m = Mesh()
    o = [QVector3D(x, y, 0) for x, y in ((0, 0), (6, 0), (6, 6), (0, 6))]
    i = [QVector3D(x, y, 0) for x, y in ((1, 1), (5, 1), (5, 5), (1, 5))]
    up = QVector3D(0, 0, 3)
    for ring in (o, i):
        for k in range(4):
            a, b = ring[k], ring[(k + 1) % 4]
            m.add_face([a, b, b + up, a + up])
    for k in range(4):
        for z in (QVector3D(), up):
            m.add_face([o[k] + z, o[(k + 1) % 4] + z,
                        i[(k + 1) % 4] + z, i[k] + z])
    col = Mesh()
    _box(col, 2.5, 2.5, 0, 1, 1, 3)
    return [m, col]


def test_hatching_stays_inside_the_cut_and_out_of_its_hollow():
    from core.section import hatch_segments
    chords, _fill = _cut(_tube_and_column())
    lines = hatch_segments(chords, UP, 0.25)
    assert len(lines)
    assert np.allclose(lines[:, :, 2], 1.0)            # in the plane
    mids = lines.astype(np.float64).mean(axis=1)
    in_hollow = ((mids[:, 0] > 1.01) & (mids[:, 0] < 4.99)
                 & (mids[:, 1] > 1.01) & (mids[:, 1] < 4.99)
                 & ~((mids[:, 0] > 2.5) & (mids[:, 0] < 3.5)
                     & (mids[:, 1] > 2.5) & (mids[:, 1] < 3.5)))
    assert not in_hollow.any()                         # the hollow is empty
    assert (mids[:, 0] > 2.5).any()                    # the column hatched
    d = lines[:, 1, :2] - lines[:, 0, :2]
    assert np.allclose(np.abs(d[:, 0]), np.abs(d[:, 1]), atol=1e-5)  # 45°


def test_cross_hatching_draws_both_ways_and_spacing_counts():
    from core.section import hatch_segments
    m = Mesh()
    _box(m, 0, 0, 0, 2, 2, 2)
    chords, _fill = _cut([m])
    one = hatch_segments(chords, UP, 0.2)
    both = hatch_segments(chords, UP, 0.2, cross=True)
    finer = hatch_segments(chords, UP, 0.1)
    assert len(both) > 1.8 * len(one)
    assert len(finer) > 1.8 * len(one)


def test_the_plane_fill_over_the_style():
    from core.section import SectionPlane, effective_fill
    from core.style import Style
    style = Style(name="test")
    style.section_fill = True
    style.section_fill_color = (0.2, 0.3, 0.4)
    sp = SectionPlane(QVector3D(), UP)
    assert effective_fill(sp, style)[:2] == ("solid", (0.2, 0.3, 0.4))
    sp.fill = {"pattern": "hatch", "color": (1.0, 0.0, 0.0),
               "spacing": 0.1}
    assert effective_fill(sp, style) == ("hatch", (1.0, 0.0, 0.0), 0.1)
    style.section_fill = False                         # the master switch
    assert effective_fill(sp, style)[0] == "none"
    back = SectionPlane.from_dict(sp.to_dict())
    assert back.fill == {"pattern": "hatch", "color": (1.0, 0.0, 0.0),
                         "spacing": 0.1}
    raw = sp.to_dict()
    raw["fill"]["pattern"] = "plaid"                   # unknown: dropped
    assert SectionPlane.from_dict(raw).fill == {"color": (1.0, 0.0, 0.0),
                                                "spacing": 0.1}


def test_the_viewport_hatches_the_cut_it_fills():
    from PySide6.QtWidgets import QApplication
    from core.group import Group
    from core.section import SectionPlane
    from views.main_window import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    scene = win.viewport.scene
    m = Mesh()
    _box(m, 0, 0, 0, 2, 3, 2)
    scene.groups[:] = [Group(m, name="Block")]
    scene.section_planes[:] = [SectionPlane(QVector3D(0, 0, 1), UP,
                                            active=True)]
    scene.version += 1
    vp = win.viewport
    assert vp._section_fill_tris() is not None
    lines = vp._section_hatch(0.2, False)
    assert lines is not None and len(lines)
    assert vp._section_hatch(0.2, False) is lines      # cached
    win._saved_version = scene.version
