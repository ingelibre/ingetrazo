# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Point clouds (georef/pointcloud.py, discussion #421): the readers, the
survey offset, thinning, colours, the snap, the document and undo.

Every file here is written by the test itself — a few hundred points in
LAS, PLY and the text layouts — so nothing depends on a real scan."""
from __future__ import annotations

import struct

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

from core.scene import Scene
from formats import igz
from georef import pointcloud as pc
from tests.test_edge_rendering import cube_viewport  # noqa: F401 - native fixture


# ---- Synthetic files ---------------------------------------------------------

def _grid(n=10, origin=(0.0, 0.0, 0.0)):
    """``n × n`` points on a gently sloped plane, metres."""
    xs, ys = np.meshgrid(np.arange(n, dtype=np.float64),
                         np.arange(n, dtype=np.float64))
    xyz = np.stack([xs.ravel(), ys.ravel(),
                    0.1 * xs.ravel() + 0.05 * ys.ravel()], axis=1)
    return xyz + np.asarray(origin)


def write_las(path, xyz, rgb=None, intensity=None, fmt=2, minor=2,
              scale=0.001, compressed=False):
    """A minimal LAS file: header, no VLRs, the points."""
    xyz = np.asarray(xyz, dtype=np.float64)
    n = len(xyz)
    header_size = 375 if minor >= 4 else (235 if minor == 3 else 227)
    record = {0: 20, 1: 28, 2: 26, 3: 34, 6: 30, 7: 36}[fmt]
    rgb_at = {2: 20, 3: 28, 7: 30}.get(fmt)
    offset = np.floor(xyz.min(axis=0))
    ints = np.round((xyz - offset) / scale).astype("<i4")
    rows = np.zeros((n, record), dtype=np.uint8)
    rows[:, 0:12] = ints.view(np.uint8).reshape(n, 12)
    if intensity is not None:
        rows[:, 12:14] = np.asarray(intensity, "<u2").view(
            np.uint8).reshape(n, 2)
    if rgb_at is not None and rgb is not None:
        rows[:, rgb_at:rgb_at + 6] = np.asarray(rgb, "<u2").view(
            np.uint8).reshape(n, 6)
    head = bytearray(header_size)
    head[0:4] = b"LASF"
    head[24], head[25] = 1, minor
    struct.pack_into("<H", head, 94, header_size)
    struct.pack_into("<I", head, 96, header_size)
    head[104] = fmt | (0x80 if compressed else 0)
    struct.pack_into("<H", head, 105, record)
    struct.pack_into("<I", head, 107, 0 if minor >= 4 else n)
    struct.pack_into("<3d", head, 131, scale, scale, scale)
    struct.pack_into("<3d", head, 155, *offset)
    if minor >= 4:
        struct.pack_into("<Q", head, 247, n)
    path.write_bytes(bytes(head) + rows.tobytes())
    return path


def write_ply(path, xyz, rgb=None, binary="binary_little_endian",
              with_faces=False):
    xyz = np.asarray(xyz, dtype=np.float64)
    n = len(xyz)
    lines = ["ply", f"format {binary} 1.0", "comment synthetic",
             f"element vertex {n}", "property float x", "property float y",
             "property double z"]
    if rgb is not None:
        lines += ["property uchar red", "property uchar green",
                  "property uchar blue"]
    if with_faces:
        lines += ["element face 1", "property list uchar int vertex_indices"]
    lines.append("end_header")
    head = ("\n".join(lines) + "\n").encode("ascii")
    if binary == "ascii":
        rows = []
        for i in range(n):
            row = [f"{xyz[i, 0]:.4f}", f"{xyz[i, 1]:.4f}", f"{xyz[i, 2]:.6f}"]
            if rgb is not None:
                row += [str(int(c)) for c in rgb[i]]
            rows.append(" ".join(row))
        body = ("\n".join(rows) + "\n").encode("ascii")
        if with_faces:
            body += b"3 0 1 2\n"
    else:
        end = "<" if binary == "binary_little_endian" else ">"
        fields = [("x", end + "f4"), ("y", end + "f4"), ("z", end + "f8")]
        if rgb is not None:
            fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
        data = np.zeros(n, dtype=fields)
        data["x"], data["y"], data["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        if rgb is not None:
            data["red"], data["green"], data["blue"] = rgb.T
        body = data.tobytes()
        if with_faces:
            body += bytes([3]) + np.array([0, 1, 2], end + "i4").tobytes()
    path.write_bytes(head + body)
    return path


# ---- LAS ---------------------------------------------------------------------

@pytest.mark.parametrize("fmt, minor", [(0, 2), (2, 2), (3, 3), (6, 4),
                                        (7, 4)])
def test_las_formats_read_positions_colour_and_intensity(tmp_path, fmt, minor):
    xyz = _grid(8)
    rgb = np.tile(np.array([[65535, 32768, 0]], dtype=np.uint16), (64, 1))
    inten = np.linspace(0, 60000, 64).astype(np.uint16)
    path = write_las(tmp_path / "scan.las", xyz, rgb, inten, fmt=fmt,
                     minor=minor)
    got, colors, intensity, total = pc.read_las(path)
    assert total == 64
    assert np.allclose(got, xyz, atol=0.0006)
    if fmt in (2, 3, 7):
        assert colors.dtype == np.uint8
        assert tuple(colors[0]) == (255, 128, 0)        # 16 bit → 8 bit
    else:
        assert colors is None
    assert intensity is not None and intensity.max() == pytest.approx(
        60000 / 65535, abs=1e-4)


def test_las_eight_bit_colours_are_kept_as_they_are(tmp_path):
    rgb = np.tile(np.array([[200, 10, 30]], dtype=np.uint16), (4, 1))
    path = write_las(tmp_path / "c.las", _grid(2), rgb, fmt=2)
    _, colors, intensity, _ = pc.read_las(path)
    assert tuple(colors[0]) == (200, 10, 30)
    assert intensity is None                    # all zero = no intensity


def test_laz_and_e57_are_refused_with_a_way_out(tmp_path):
    laz = write_las(tmp_path / "scan.las", _grid(2), compressed=True)
    with pytest.raises(pc.PointCloudError, match="LAZ"):
        pc.read_las(laz)
    e57 = tmp_path / "scan.e57"
    e57.write_bytes(b"ASTM-E57")
    with pytest.raises(pc.PointCloudError, match="E57") as info:
        pc.read_file(e57)
    assert info.value.template.startswith("E57 files")


def test_not_a_las_file(tmp_path):
    bad = tmp_path / "bad.las"
    bad.write_bytes(b"x" * 400)
    with pytest.raises(pc.PointCloudError):
        pc.read_las(bad)


def test_las_cut_short_reads_the_points_that_are_there(tmp_path):
    path = write_las(tmp_path / "s.las", _grid(4), fmt=0)
    data = path.read_bytes()
    path.write_bytes(data[:-20 * 6])            # six records missing
    got, *_rest, total = pc.read_las(path)
    assert total == 10 and len(got) == 10


# ---- PLY ---------------------------------------------------------------------

@pytest.mark.parametrize("binary", ["ascii", "binary_little_endian",
                                    "binary_big_endian"])
def test_ply_layouts(tmp_path, binary):
    xyz = _grid(5)
    rgb = np.tile(np.array([[10, 20, 30]], dtype=np.uint8), (25, 1))
    path = write_ply(tmp_path / "c.ply", xyz, rgb, binary=binary,
                     with_faces=True)
    got, colors, intensity, total = pc.read_ply(path)
    assert total == 25
    assert np.allclose(got, xyz, atol=1e-4)
    assert tuple(colors[3]) == (10, 20, 30)
    assert intensity is None


def test_ply_without_xyz_is_refused(tmp_path):
    path = tmp_path / "n.ply"
    path.write_bytes(b"ply\nformat ascii 1.0\nelement vertex 1\n"
                     b"property float a\nend_header\n1\n")
    with pytest.raises(pc.PointCloudError):
        pc.read_ply(path)


# ---- Text layouts --------------------------------------------------------------

def test_text_xyz_with_spaces(tmp_path):
    path = tmp_path / "c.xyz"
    path.write_text("1 2 3\n4 5 6\n7.5 8 9\n")
    got, colors, intensity, total = pc.read_text(path)
    assert total == 3 and colors is None and intensity is None
    assert got[2].tolist() == [7.5, 8, 9]


def test_text_csv_with_header_and_colour(tmp_path):
    path = tmp_path / "c.csv"
    path.write_text("X,Y,Z,R,G,B\n1,2,3,255,0,0\n4,5,6,0,255,0\n")
    got, colors, _i, total = pc.read_text(path)
    assert total == 2 and tuple(colors[1]) == (0, 255, 0)


def test_text_semicolon_with_decimal_commas(tmp_path):
    path = tmp_path / "c.txt"
    path.write_text("1,5;2,25;3\n4;5;6,75\n")
    got, *_ = pc.read_text(path)
    assert got.tolist() == [[1.5, 2.25, 3.0], [4.0, 5.0, 6.75]]


def test_pts_count_line_intensity_and_colour(tmp_path):
    path = tmp_path / "c.pts"
    path.write_text("2\n1 2 3 -500 10 20 30\n4 5 6 1500 40 50 60\n")
    got, colors, intensity, total = pc.read_text(path)
    assert total == 2
    assert tuple(colors[1]) == (40, 50, 60)
    assert intensity[0] < intensity[1]


def test_text_without_numbers_is_refused(tmp_path):
    path = tmp_path / "c.txt"
    path.write_text("nothing here\n")
    with pytest.raises(pc.PointCloudError):
        pc.read_text(path)


# ---- Placing: survey offset and thinning -----------------------------------------

def test_utm_cloud_is_moved_near_the_origin_by_whole_metres(tmp_path):
    """A scan in UTM (8.5 million metres north) would lose its centimetres in
    float32: it is read in double and moved by one whole-metre offset."""
    xyz = _grid(6, origin=(717623.37, 8278698.81, 3335.2))
    path = write_las(tmp_path / "utm.las", xyz)
    cloud = pc.load_point_cloud(path)
    assert cloud.offset == (717623.0, 8278698.0, 3335.0)
    back = cloud.positions.astype(np.float64) + np.array(cloud.offset)
    assert np.abs(back - xyz).max() < 0.002     # centimetres survive
    assert cloud.positions.dtype == np.float32


def test_second_scan_reuses_the_first_offset_so_they_line_up(tmp_path):
    a = write_las(tmp_path / "a.las", _grid(3, origin=(500100.0, 4000200.0, 10)))
    b = write_las(tmp_path / "b.las", _grid(3, origin=(500150.0, 4000260.0, 12)))
    first = pc.load_point_cloud(a)
    second = pc.load_point_cloud(b, offset=first.offset)
    assert second.offset == first.offset
    assert second.positions[0, 0] == pytest.approx(50.0, abs=1e-3)


def test_local_cloud_is_read_where_it_is(tmp_path):
    cloud = pc.load_point_cloud(write_las(tmp_path / "l.las", _grid(3)))
    assert cloud.offset is None
    assert cloud.positions.min() == pytest.approx(0.0, abs=1e-3)


def test_big_cloud_is_thinned_evenly_and_the_same_way_twice(tmp_path):
    path = write_las(tmp_path / "big.las", _grid(40))       # 1600 points
    a = pc.load_point_cloud(path, max_points=400)
    b = pc.load_point_cloud(path, max_points=400)
    assert a.point_count == 400 and a.total_points == 1600 and a.thinned
    assert np.array_equal(a.positions, b.positions)
    # Evenly spread: every quarter of the file keeps some points.
    assert len(np.unique((a.positions[:, 1] // 10).astype(int))) == 4


def test_non_finite_rows_are_dropped(tmp_path):
    path = tmp_path / "n.xyz"
    path.write_text("1 2 3\nnan 2 3\n4 5 6\n")
    cloud = pc.load_point_cloud(path)
    assert cloud.point_count == 2


# ---- Colours -----------------------------------------------------------------------

def test_colour_modes_and_their_fallbacks():
    xyz = _grid(5)
    cloud = pc.PointCloud(xyz)                              # no colour data
    assert cloud.color_mode == "elevation"
    cloud.color_mode = "rgb"
    assert cloud.effective_mode() == "elevation"            # nothing to show
    cloud.color_mode = "intensity"
    assert cloud.effective_mode() == "elevation"
    cloud.color_mode = "single"
    assert np.all(cloud.display_colors() == 150)
    cloud.color_mode = "elevation"
    ramp = cloud.display_colors()
    low, high = np.argmin(xyz[:, 2]), np.argmax(xyz[:, 2])
    assert ramp[low][2] > ramp[low][0]                      # low = blue
    assert ramp[high][0] > ramp[high][2]                    # high = red


def test_true_colour_is_the_default_when_the_file_has_it():
    rgb = np.full((4, 3), 77, dtype=np.uint8)
    cloud = pc.PointCloud(_grid(2), rgb)
    assert cloud.color_mode == "rgb"
    assert np.all(cloud.display_colors() == 77)


# ---- Snap --------------------------------------------------------------------------

def _top_view_mvp(width=200.0, height=200.0, span=10.0):
    """A plan view of a 10 m square, centred at (5, 5), eye 100 m up."""
    from PySide6.QtGui import QMatrix4x4
    proj = QMatrix4x4()
    proj.ortho(-span / 2, span / 2, -span / 2, span / 2, 1.0, 1000.0)
    view = QMatrix4x4()
    view.lookAt(QVector3D(5, 5, 100), QVector3D(5, 5, 0), QVector3D(0, 1, 0))
    m = proj * view
    return np.array(m.data(), dtype=np.float64).reshape(4, 4, order="F")


def test_snap_picks_the_point_under_the_cursor():
    pts = np.array([[5.0, 5.0, 0.0], [6.0, 5.0, 0.0]], dtype=np.float32)
    mvp = _top_view_mvp()
    # (5, 5) is the centre of the 200 px view; (6, 5) is 20 px right.
    assert pc.nearest_screen_point(pts, mvp, 200, 200, 101, 100) == 0
    assert pc.nearest_screen_point(pts, mvp, 200, 200, 118, 101) == 1
    assert pc.nearest_screen_point(pts, mvp, 200, 200, 150, 150) is None


def test_snap_prefers_the_scanned_surface_in_front():
    """Seen from above, a roof point and the floor point under it fall on
    the same pixel: the one nearer the eye is the one you see."""
    pts = np.array([[5.0, 5.0, 0.0], [5.02, 5.0, 3.0]], dtype=np.float32)
    mvp = _top_view_mvp()
    from PySide6.QtGui import QMatrix4x4
    proj = QMatrix4x4()
    proj.perspective(40.0, 1.0, 1.0, 1000.0)
    view = QMatrix4x4()
    view.lookAt(QVector3D(5, 5, 20), QVector3D(5, 5, 0), QVector3D(0, 1, 0))
    mvp = np.array((proj * view).data(), dtype=np.float64).reshape(
        4, 4, order="F")
    assert pc.nearest_screen_point(pts, mvp, 200, 200, 100, 100) == 1


def test_snap_skips_what_the_cut_hides():
    pts = np.array([[5.0, 5.0, 0.0], [5.05, 5.0, 3.0]], dtype=np.float32)
    mvp = _top_view_mvp()
    below = pc.nearest_screen_point(pts, mvp, 200, 200, 100, 100,
                                    keep=lambda p: p[:, 2] < 1.5)
    assert below == 0


def test_snap_engine_lands_exactly_on_a_cloud_point():
    """The viewport hands the point to the snap engine as a zero-length
    pseudo-edge (like a survey point): the endpoint snap is bit-exact."""
    from types import SimpleNamespace
    from core.snap import compute_snap
    p = QVector3D(3.125, 4.5, 0.75)
    scene = SimpleNamespace(edges=[SimpleNamespace(a=QVector3D(p),
                                                   b=QVector3D(p))])

    def to_px(q):
        return (100.0 + (q.x() - 3) * 50, 100.0 - (q.y() - 4) * 50)

    cand = QVector3D(3.16, 4.52, 0.75)
    res = compute_snap(candidate_world=cand, candidate_pixel=to_px(cand),
                       scene=scene, world_to_pixel=to_px, threshold_px=9.0)
    assert res.kind == "endpoint" and res.point == p


def test_viewport_offers_the_cloud_point_to_the_snap():
    """``_snap_scene`` adds the cloud point under the cursor (a viewport
    double: the snap scene needs no GL)."""
    from views.viewport.pointclouds import PointCloudMixin
    from views.viewport.snapping import SnappingMixin

    scene = Scene()
    cloud = pc.PointCloud(np.array([[5.0, 5.0, 0.0]], dtype=np.float32))
    scene.point_clouds.append(cloud)
    mvp = _top_view_mvp()

    class _VP(PointCloudMixin, SnappingMixin):
        active_tool = None

        def __init__(self):
            self.scene = scene

        def width(self):
            return 200

        def height(self):
            return 200

        def _np_mvp(self):
            return mvp

        def _world_to_pixel(self, w, mvp_=None):
            v = mvp @ np.array([w.x(), w.y(), w.z(), 1.0])
            return ((v[0] / v[3] * 0.5 + 0.5) * 200,
                    (1 - (v[1] / v[3] * 0.5 + 0.5)) * 200)

        def _nearby_group_edges(self, px, py):
            return []

        def _billboard_snap_edges(self):
            return []

        def _selection_box_points(self, skip=None):
            return []

    vp = _VP()
    hit = vp._point_cloud_snap(102, 99)
    assert hit == QVector3D(5, 5, 0)
    cloud.visible = False
    assert vp._point_cloud_snap(102, 99) is None


# ---- Document, undo ---------------------------------------------------------------

def _cloud_for_doc():
    rgb = np.arange(75, dtype=np.uint8).reshape(25, 3)
    cloud = pc.PointCloud(_grid(5), rgb, np.linspace(0, 1, 25),
                          name="fachada", source="C:/scans/fachada.las",
                          offset=(717600.0, 8278600.0, 3300.0),
                          total_points=1000)
    cloud.color_mode = "intensity"
    cloud.point_size = 4.0
    cloud.layer = "Survey"
    return cloud


@pytest.mark.parametrize("fmt", ["auto", "json"])
def test_document_round_trip(tmp_path, fmt):
    scene = Scene()
    cloud = _cloud_for_doc()
    cloud.visible = False
    scene.point_clouds.append(cloud)
    path = tmp_path / "nube.igz"
    igz.save_scene(scene, path, fmt=fmt)
    back = Scene()
    igz.load_into(back, path)
    assert len(back.point_clouds) == 1
    got = back.point_clouds[0]
    assert np.array_equal(got.positions, cloud.positions)
    assert np.array_equal(got.colors, cloud.colors)
    assert np.allclose(got.intensity, cloud.intensity)
    assert got.offset == cloud.offset and got.total_points == 1000
    assert (got.name, got.color_mode, got.point_size, got.visible,
            got.layer) == ("fachada", "intensity", 4.0, False, "Survey")


def test_opening_a_document_without_clouds_forgets_the_previous_ones(tmp_path):
    empty = tmp_path / "vacio.igz"
    igz.save_scene(Scene(), empty)
    scene = Scene()
    scene.point_clouds.append(_cloud_for_doc())
    igz.load_into(scene, empty)
    assert scene.point_clouds == []


def test_damaged_cloud_block_does_not_stop_the_document():
    meta = [{"data": "pointclouds/cloud-00.npz"}]
    assert pc.unpack_clouds(meta, lambda _m: b"not an npz") == []


def test_new_document_clears_the_clouds():
    scene = Scene()
    scene.point_clouds.append(_cloud_for_doc())
    scene.clear()
    assert scene.point_clouds == []


def test_import_remove_and_display_are_undoable():
    from core.history import (AddPointCloudCommand, History,
                              RemovePointCloudsCommand,
                              SetPointCloudDisplayCommand)
    scene = Scene()
    history = History(scene)
    cloud = _cloud_for_doc()
    cloud.layer = "Escaneos"
    assert history.execute(AddPointCloudCommand(cloud))
    assert scene.point_clouds == [cloud] and scene.layer("Escaneos")
    history.execute(SetPointCloudDisplayCommand([cloud], point_size=7.0,
                                                color_mode="rgb"))
    assert cloud.point_size == 7.0 and cloud.color_mode == "rgb"
    history.undo()
    assert cloud.point_size == 4.0 and cloud.color_mode == "intensity"
    history.execute(RemovePointCloudsCommand([cloud]))
    assert scene.point_clouds == []
    history.undo()
    assert scene.point_clouds == [cloud]
    history.undo()                                  # the import itself
    assert scene.point_clouds == [] and scene.layer("Escaneos") is None


def test_error_messages_are_translatable():
    """The window shows ``tr(template, **fields)``: every template is in
    the Spanish catalogue with the same placeholders."""
    import json
    from core.i18n import _I18N_DIR
    es = json.loads((_I18N_DIR / "es.json").read_text(encoding="utf-8"))
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(pc))
    templates = {n.args[0].value for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "PointCloudError"
                 and n.args and isinstance(n.args[0], ast.Constant)}
    assert templates and not (templates - set(es))


# ---- Drawn on screen (native OpenGL only) ----------------------------------------

def test_cloud_is_drawn_and_cut_by_the_section(cube_viewport):  # noqa: F811
    """Red points on the ground: drawn in their own colour, gone once a
    section plane cuts below them, and gone when switched off."""
    from PySide6.QtGui import QImage
    from core.history import SetPointCloudDisplayCommand
    from core.section import SectionPlane
    vp = cube_viewport
    scene = vp.scene
    scene.mesh.clear()
    xyz = _grid(30) / 29.0 * 2.0 - np.array([1.0, 1.0, 0.0])
    xyz[:, 2] = 0.0
    rgb = np.tile(np.array([[255, 0, 0]], dtype=np.uint8), (len(xyz), 1))
    cloud = pc.PointCloud(xyz, rgb)
    cloud.point_size = 6.0
    scene.point_clouds.append(cloud)
    vp.camera.set_view("top")
    vp.camera.fit_to(QVector3D(-1.2, -1.2, -0.1), QVector3D(1.2, 1.2, 0.1))
    scene.version += 1

    def red_in_centre():
        image = vp.render_image(300, 250, overlays=False).convertToFormat(
            QImage.Format_RGBA8888)
        px = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(
            (250, image.bytesPerLine() // 4, 4))[:, :300, :3]
        block = px[110:140, 135:165].reshape(-1, 3).astype(int)
        return bool((np.abs(block - (255, 0, 0)).sum(axis=1) < 40).any())

    assert red_in_centre()
    plane = SectionPlane(QVector3D(0, 0, -0.5), QVector3D(0, 0, 1),
                         active=True, hidden=True)
    scene.section_planes.append(plane)
    scene.version += 1
    assert not red_in_centre()                  # the cut takes them away
    scene.section_planes.remove(plane)
    scene.version += 1
    assert red_in_centre()
    vp.history.execute(SetPointCloudDisplayCommand([cloud], visible=False))
    assert not red_in_centre()
