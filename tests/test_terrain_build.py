# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Draw ▸ Terrain from survey data: a TIN through survey points, a ground
through contour lines, Set Height for a 2D drawing's flat contours and
points, and a DXF's POINT entities arriving as guide points."""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.group import Group
from core.guide import Guide
from core.history import History
from core.scene import Scene
from core.terrain_build import (TerrainBuildError, contour_terrain,
                                convex_hull, delaunay, merge_points,
                                peel_long_rim, points_terrain)
from tools.base import ToolContext
from tools.terrain import (TerrainFromContoursTool, TerrainFromPointsTool,
                           TerrainHeightTool, line_chain, selected_points)


def _circumcircle(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    sa, sb, sc = (p[0] ** 2 + p[1] ** 2 for p in (a, b, c))
    ux = (sa * (b[1] - c[1]) + sb * (c[1] - a[1]) + sc * (a[1] - b[1])) / d
    uy = (sa * (c[0] - b[0]) + sb * (a[0] - c[0]) + sc * (b[0] - a[0])) / d
    return ux, uy, (a[0] - ux) ** 2 + (a[1] - uy) ** 2


# ---- Points ------------------------------------------------------------------

def test_delaunay_leaves_every_circumcircle_empty_and_turns_ccw():
    rng = np.random.default_rng(5)
    xy = [tuple(p) for p in rng.uniform(0, 50, (300, 2))]
    tris = delaunay(xy)
    P = np.array(xy)
    hull = convex_hull(xy)
    # Euler for a triangulated point set: 2n - 2 - h triangles.
    assert len(tris) == 2 * len(xy) - 2 - len(hull)
    for a, b, c in tris:
        A, B, C = xy[a], xy[b], xy[c]
        assert (B[0] - A[0]) * (C[1] - A[1]) - (B[1] - A[1]) * (C[0] - A[0]) > 0
        ux, uy, r2 = _circumcircle(A, B, C)
        inside = ((P[:, 0] - ux) ** 2 + (P[:, 1] - uy) ** 2) < r2 * (1 - 1e-9)
        assert not inside.any()


def test_delaunay_copes_with_survey_coordinates():
    """UTM-sized coordinates (N ≈ 8 200 000) triangulate as well."""
    rng = np.random.default_rng(2)
    xy = [(240000.0 + x, 8200000.0 + y) for x, y in rng.uniform(0, 80, (60, 2))]
    assert len(delaunay(xy)) == 2 * 60 - 2 - len(convex_hull(xy))


def test_points_terrain_passes_through_every_point():
    rng = np.random.default_rng(9)
    pts = [QVector3D(float(x), float(y), float(math.sin(x / 7) * 3 + y / 10))
           for x, y in rng.uniform(0, 60, (120, 2))]
    verts, tris = points_terrain(pts)
    got = {(round(v.x(), 6), round(v.y(), 6)): v.z() for v in verts}
    for p in pts:
        assert got[(round(p.x(), 6), round(p.y(), 6))] == pytest.approx(p.z())
    for a, b, c in tris:
        n = QVector3D.crossProduct(verts[b] - verts[a], verts[c] - verts[a])
        assert n.z() > 0                               # facing up


def test_points_closer_than_a_millimetre_are_one_at_their_mean_height():
    pts = merge_points([QVector3D(1, 1, 2), QVector3D(1.0002, 1, 4),
                        QVector3D(5, 5, 0)])
    assert len(pts) == 2
    assert pts[0].z() == pytest.approx(3.0)


def test_points_terrain_refuses_too_few_or_aligned_points():
    with pytest.raises(TerrainBuildError):
        points_terrain([QVector3D(0, 0, 0), QVector3D(1, 0, 0)])
    with pytest.raises(TerrainBuildError):
        points_terrain([QVector3D(i, 2 * i, i) for i in range(5)])


def test_long_rim_triangles_peel_off_and_inner_ones_stay():
    # A square survey 10 m apart, plus one far point that only joins the
    # rest with long thin triangles round the outside.
    xy = [(float(x), float(y)) for x in range(0, 31, 10) for y in range(0, 31, 10)]
    xy.append((15.0, 90.0))
    tris = delaunay(xy)
    peeled = peel_long_rim(xy, tris, 20.0)
    assert all(len(xy) - 1 not in t for t in peeled)   # the far point goes
    assert len(peeled) == 18                            # the 3×3 squares stay
    assert peel_long_rim(xy, tris, 0.0) == tris         # 0 = no limit


# ---- Contours ----------------------------------------------------------------

def _line(a, b, n=20):
    pts = [a + (b - a) * (k / n) for k in range(n + 1)]
    return list(zip(pts, pts[1:]))


def test_contours_ramp_evenly_from_one_line_to_the_next():
    segs = (_line(QVector3D(0, 0, 0), QVector3D(40, 0, 0))
            + _line(QVector3D(0, 20, 10), QVector3D(40, 20, 10)))
    verts, tris = contour_terrain(segs, 1.0)
    assert tris
    for v in verts:
        assert v.z() == pytest.approx(v.y() * 0.5, abs=0.05)


def test_contours_pass_through_their_lines_and_stay_inside_them():
    segs = []
    for r, z in ((8.0, 6.0), (16.0, 3.0), (24.0, 0.0)):
        ring = [QVector3D(30 + r * math.cos(2 * math.pi * k / 48),
                          30 + r * math.sin(2 * math.pi * k / 48), z)
                for k in range(48)]
        segs += list(zip(ring, ring[1:] + ring[:1]))
    verts, _tris = contour_terrain(segs, 0.5)
    for v in verts:
        r = math.hypot(v.x() - 30, v.y() - 30)
        assert r <= 24.0 + 1.0                         # clipped to the outline
        for rr, z in ((8.0, 6.0), (16.0, 3.0)):
            if abs(r - rr) < 0.1:
                assert v.z() == pytest.approx(z, abs=0.15)
        if 9.0 < r < 15.0:
            assert 3.0 - 0.05 < v.z() < 6.0 + 0.05     # between its contours


def test_contours_refuse_nothing_and_a_single_spot():
    with pytest.raises(TerrainBuildError):
        contour_terrain([], 1.0)
    with pytest.raises(TerrainBuildError):
        contour_terrain(_line(QVector3D(0, 0, 0), QVector3D(10, 0, 0)), 1.0)


# ---- Tools -------------------------------------------------------------------

class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashes = []
        self.pick_threshold_px = 8.0
        self.guide = None
        self.edge = None
        self.group = None

    def update(self):
        pass

    def flash_status(self, text, *_a):
        self.flashes.append(text)

    def pick_guide(self, x, y):
        return self.guide

    def pick_edge(self, x, y):
        return self.edge

    def pick_group(self, x, y):
        return self.group

    def _world_to_pixel(self, p):
        return (p.x() * 10.0, p.y() * 10.0)


def _ctx(vp, x, y, z=0.0):
    return ToolContext(viewport=vp, world=QVector3D(x, y, z),
                       screen=QPointF(x * 10.0, y * 10.0),
                       modifiers=Qt.NoModifier,
                       snap=SimpleNamespace(kind="none"))


def test_from_contours_builds_on_pick_up_and_rebuilds_with_a_typed_cell():
    scene = Scene()
    edges = [scene.mesh.add_edge(a, b) for a, b in
             _line(QVector3D(0, 0, 0), QVector3D(30, 0, 0), 6)
             + _line(QVector3D(0, 15, 5), QVector3D(30, 15, 5), 6)]
    scene.selection.update(edges)
    vp = _Vp(scene)
    tool = TerrainFromContoursTool()
    tool.on_activate(vp)
    assert len(scene.groups) == 1
    first = len(scene.groups[0].mesh.faces)
    assert tool.on_value(vp, 3.0)                       # coarser cell
    assert len(scene.groups) == 1                       # rebuilt, not added
    assert len(scene.groups[0].mesh.faces) < first
    assert len(vp.history.undo_stack) == 1              # still one step
    vp.history.undo()
    assert scene.groups == []


def test_from_contours_reads_an_imported_layer_group():
    scene = Scene()
    g = Group(name="CURVAS")
    for a, b in (_line(QVector3D(0, 0, 100), QVector3D(20, 0, 100), 4)
                 + _line(QVector3D(0, 10, 101), QVector3D(20, 10, 101), 4)):
        g.mesh.add_edge(a, b)
    scene.groups.append(g)
    scene.selection.add(g)
    vp = _Vp(scene)
    TerrainFromContoursTool().on_activate(vp)
    terrain = scene.groups[-1]
    assert terrain is not g
    zs = [v.position.z() for v in terrain.mesh.vertices]
    assert min(zs) == pytest.approx(100.0) and max(zs) == pytest.approx(101.0)


def test_from_contours_with_nothing_selected_says_so():
    vp = _Vp(Scene())
    TerrainFromContoursTool().on_activate(vp)
    assert vp.flashes and vp.scene.groups == []


def test_from_points_takes_every_guide_point_when_none_is_selected():
    scene = Scene()
    rng = np.random.default_rng(4)
    for x, y in rng.uniform(0, 30, (40, 2)):
        scene.guides.append(Guide(QVector3D(float(x), float(y), float(x) / 10)))
    scene.guides.append(Guide(QVector3D(0, 0, 0), QVector3D(1, 0, 0)))  # a line
    assert len(selected_points(scene)) == 40
    vp = _Vp(scene)
    tool = TerrainFromPointsTool()
    tool.on_activate(vp)
    assert len(scene.groups) == 1
    assert len(scene.groups[0].mesh.vertices) == 40
    n = len(scene.groups[0].mesh.faces)
    assert tool.on_value(vp, 6.0)                       # trim the long rim
    assert len(scene.groups) == 1
    assert len(scene.groups[0].mesh.faces) < n


def test_set_height_lifts_a_whole_loose_contour():
    scene = Scene()
    chain = [scene.mesh.add_edge(a, b) for a, b in
             _line(QVector3D(0, 0, 0), QVector3D(10, 5, 0), 5)]
    other = scene.mesh.add_edge(QVector3D(0, 20, 0), QVector3D(10, 20, 0))
    vp = _Vp(scene)
    vp.edge = chain[2]
    tool = TerrainHeightTool()
    tool.on_click(_ctx(vp, 5, 2.5))
    assert len(tool.rubber_band_lines()) == 5           # the whole line
    assert tool.on_value(vp, 2450.0)
    for e in chain:
        assert e.a.z() == pytest.approx(2450.0) and e.b.z() == pytest.approx(2450.0)
    assert other.a.z() == 0.0                           # the next one stays
    vp.history.undo()
    assert all(e.a.z() == 0.0 for e in chain)


def test_set_height_reads_a_line_of_a_group_from_outside_and_a_guide_point():
    scene = Scene()
    g = Group(name="CURVAS")
    for a, b in _line(QVector3D(0, 0, 0), QVector3D(10, 0, 0), 5):
        g.mesh.add_edge(a, b)
    g.mesh.add_edge(QVector3D(0, 8, 0), QVector3D(10, 8, 0))
    scene.groups.append(g)
    vp = _Vp(scene)
    vp.group = g
    tool = TerrainHeightTool()
    tool.on_click(_ctx(vp, 4.0, 0.2))                   # near the first line
    tool.on_value(vp, 12.0)
    zs = sorted({round(v.position.z(), 6) for v in g.mesh.vertices})
    assert zs == [0.0, 12.0]
    assert sum(1 for v in g.mesh.vertices if v.position.z() == 12.0) == 6
    # A guide point.
    guide = Guide(QVector3D(3, 3, 0))
    scene.guides.append(guide)
    vp.group, vp.guide = None, guide
    tool.on_click(_ctx(vp, 3, 3))
    tool.on_value(vp, 7.5)
    assert guide.point.z() == pytest.approx(7.5)
    vp.history.undo()
    assert guide.point.z() == 0.0


def test_set_height_typed_before_a_click_only_asks_for_one():
    vp = _Vp(Scene())
    tool = TerrainHeightTool()
    assert tool.on_value(vp, 3.0)
    assert vp.flashes and not vp.history.undo_stack


def test_line_chain_stops_at_faces():
    scene = Scene()
    m = scene.mesh
    m.add_face([QVector3D(0, 0, 0), QVector3D(4, 0, 0), QVector3D(4, 4, 0)])
    e = m.add_edge(QVector3D(4, 4, 0), QVector3D(8, 4, 0))
    m.add_edge(QVector3D(8, 4, 0), QVector3D(9, 6, 0))
    assert len(line_chain(m, e)) == 3                   # not the triangle's


# ---- DXF points --------------------------------------------------------------

def test_dxf_points_come_in_as_guide_points_and_undo_takes_them(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from core.history import SnapshotImport
    from formats.dxf_in import load_dxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("COTAS")
    for x, y, z in ((0, 0, 101.5), (10, 0, 102.0), (5, 8, 103.25)):
        msp.add_point((x, y, z), dxfattribs={"layer": "COTAS"})
    pl = msp.add_lwpolyline([(0, 20), (10, 20), (10, 30)],
                            dxfattribs={"layer": "CURVAS"})
    pl.dxf.elevation = 104.0
    path = tmp_path / "survey.dxf"
    doc.saveas(path)
    scene = Scene()
    history = History(scene)
    stats = {}
    history.execute(SnapshotImport(
        lambda s: stats.update(load_dxf(s, path, scale=1.0))))
    assert history.last_error is None
    assert stats["points"] == 3
    zs = sorted(g.point.z() for g in scene.guides)
    assert zs == pytest.approx([101.5, 102.0, 103.25])
    assert {g.layer for g in scene.guides} == {"COTAS"}
    assert scene.layer("COTAS") is not None
    # The contour keeps its elevation.
    curvas = next(g for g in scene.groups if g.name == "CURVAS")
    assert {round(v.position.z(), 6) for v in curvas.mesh.vertices} == {104.0}
    history.undo()
    assert scene.guides == [] and scene.groups == []


def test_a_dxf_of_points_only_imports():
    ezdxf = pytest.importorskip("ezdxf")
    import tempfile, pathlib
    from formats.dxf_in import load_dxf
    doc = ezdxf.new()
    for k in range(5):
        doc.modelspace().add_point((k, k * k, k))
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "points.dxf"
        doc.saveas(path)
        scene = Scene()
        stats = load_dxf(scene, path, scale=1.0)
    assert stats["points"] == 5 and stats["groups"] == 0
    assert len(scene.guides) == 5
