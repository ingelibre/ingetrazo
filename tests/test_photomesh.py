# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Photogrammetric mesh import (Track G, G6): ODM anchor parsing, corner welding,
and placement into the scene's local frame. Headless, synthetic ODM output."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication

from georef.datum import SceneDatum, utm_forward, utm_inverse
from georef.photomesh import (DEFAULT_TEXTURE_BUDGET, ODMAnchor, atlas_bytes,
                              find_anchor, load_atlas, load_odm_obj, parse_anchor,
                              parse_mtl, plan_texture_sizes)

_app = QGuiApplication.instance() or QGuiApplication([])

# Chanchallay: UTM 18S, the real anchor from the user's own survey.
ANCHOR_TEXT = "WGS84 UTM 18S\n717623 8278698\n"

OBJ = """\
mtllib model.mtl
v 0.0 0.0 1750.0
v 10.0 0.0 1750.0
v 10.0 10.0 1752.0
v 0.0 10.0 1752.0
vt 0.0 0.0
vt 1.0 0.0
vt 1.0 1.0
vt 0.0 1.0
usemtl material0000
f 1/1 2/2 3/3
usemtl material0001
f 1/1 3/3 4/4
"""

MTL = """\
newmtl material0000
Kd 1.0 1.0 1.0
map_Kd atlas0.png
newmtl material0001
Kd 1.0 1.0 1.0
"""


def _datum_at_anchor():
    """A datum sitting exactly on the ODM anchor, so local == OBJ coordinates."""
    lat, lon = -15.5, -72.5                     # zone 18S
    d = SceneDatum(lat, lon, 0.0)
    return d


def _write_odm_tree(tmp_path, obj=OBJ, anchor=ANCHOR_TEXT, mtl=MTL):
    """Mirror ODM's real layout: odm_texturing/ beside odm_georeferencing/."""
    tex = tmp_path / "odm_texturing"
    geo = tmp_path / "odm_georeferencing"
    tex.mkdir()
    geo.mkdir()
    (tex / "model.obj").write_text(obj)
    if mtl is not None:
        (tex / "model.mtl").write_text(mtl)
    if anchor is not None:
        (geo / "odm_georeferencing_model_geo.txt").write_text(anchor)
    return tex / "model.obj"


# ---- the anchor sidecar ----------------------------------------------------

def test_parse_anchor_reads_zone_and_offset():
    a = parse_anchor(ANCHOR_TEXT)
    assert a == ODMAnchor(717623.0, 8278698.0, 18, False)
    assert a.hemisphere == "S"


def test_parse_anchor_northern_and_spaced_zone():
    assert parse_anchor("WGS84 UTM 30N\n500000 4000000\n").northern is True
    spaced = parse_anchor("WGS84 UTM 18 S\n717623 8278698\n")
    assert spaced == ODMAnchor(717623.0, 8278698.0, 18, False)


@pytest.mark.parametrize("text", ["", "WGS84 UTM 18S\n", "not a crs\n1 2\n",
                                  "WGS84 UTM 18S\nnot numbers\n"])
def test_parse_anchor_rejects_garbage(text):
    assert parse_anchor(text) is None


def test_find_anchor_walks_up_to_the_georeferencing_folder(tmp_path):
    obj = _write_odm_tree(tmp_path)
    assert find_anchor(obj) == ODMAnchor(717623.0, 8278698.0, 18, False)


def test_find_anchor_none_when_missing(tmp_path):
    obj = _write_odm_tree(tmp_path, anchor=None)
    assert find_anchor(obj) is None


# ---- materials -------------------------------------------------------------

def test_parse_mtl_maps_textures_and_keeps_untextured():
    maps = parse_mtl(MTL)
    assert maps == {"material0000": "atlas0.png", "material0001": None}


# ---- geometry --------------------------------------------------------------

def test_load_welds_corners_and_keeps_triangles(tmp_path):
    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    # 4 positions x 4 uvs, but only 4 distinct (v, vt) pairs are used.
    assert mesh.vertex_count == 4
    assert mesh.triangle_count == 2
    assert mesh.triangles.dtype == np.uint32
    assert mesh.vertices.dtype == np.float32


def test_material_runs_cover_every_triangle(tmp_path):
    obj = _write_odm_tree(tmp_path)
    (obj.parent / "atlas0.png").write_bytes(b"")
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert [(m.name, m.start, m.count) for m in mesh.materials] == [
        ("material0000", 0, 1), ("material0001", 1, 1)]
    assert sum(m.count for m in mesh.materials) == mesh.triangle_count
    assert mesh.materials[0].texture.name == "atlas0.png"
    assert mesh.materials[1].texture is None      # no map_Kd in the .mtl
    assert mesh.missing_textures == []


def test_absent_atlases_are_reported_not_dropped(tmp_path):
    """An ODM export moved without its PNGs must say so — silently rendering
    grey is how you end up tracing over a texture that never loaded."""
    obj = _write_odm_tree(tmp_path)                 # atlas0.png never written
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert mesh.materials[0].texture is not None    # path kept
    assert [p.name for p in mesh.missing_textures] == ["atlas0.png"]


def test_uv_v_axis_is_flipped_for_images(tmp_path):
    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    # OBJ vt (0,0) is bottom-left; images are top-down, so V must come out 1.0.
    assert mesh.uvs.min() == pytest.approx(0.0)
    assert mesh.uvs.max() == pytest.approx(1.0)
    corner = mesh.vertices[:, :2].sum(axis=1).argmin()   # the (0,0) vertex
    assert mesh.uvs[corner][1] == pytest.approx(1.0)


# ---- placement -------------------------------------------------------------

def test_placement_shifts_by_the_anchor(tmp_path):
    """The mesh must land where the anchor says, not at the scene origin."""
    obj = _write_odm_tree(tmp_path)
    datum = _datum_at_anchor()
    mesh = load_odm_obj(obj, datum)

    east0, north0 = utm_forward(datum.lat, datum.lon, datum.zone)
    expect_x = 717623.0 - east0        # OBJ vertex 1 is at (0, 0)
    expect_y = 8278698.0 - north0

    lo, _ = mesh.bounds()
    assert lo.x() == pytest.approx(expect_x, abs=1e-3)
    assert lo.y() == pytest.approx(expect_y, abs=1e-3)


def test_ground_reference_drops_z_to_the_shared_plane(tmp_path):
    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor(), ground_ref=1750.0)
    lo, hi = mesh.bounds()
    assert lo.z() == pytest.approx(0.0, abs=1e-3)     # 1750 absolute → 0 local
    assert hi.z() == pytest.approx(2.0, abs=1e-3)


def test_without_anchor_lands_at_the_origin(tmp_path):
    obj = _write_odm_tree(tmp_path, anchor=None)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert mesh.georeferenced is False
    lo, _ = mesh.bounds()
    assert lo.x() == pytest.approx(0.0)
    assert lo.y() == pytest.approx(0.0)


def test_cross_zone_reprojects_instead_of_translating(tmp_path):
    """A datum in another UTM zone must reproject: the grids are rotated, so a
    plain translation would skew the survey."""
    obj = _write_odm_tree(tmp_path)
    far = SceneDatum(-15.5, -71.5, 0.0)          # zone 19, just across from 18
    assert far.zone != 18
    mesh = load_odm_obj(obj, far)

    # OBJ vertex 1 sits exactly on the anchor, so it must land where that
    # geodetic point falls in the far datum. Compared in metres, against the
    # actual vertex — the bbox corner isn't a vertex once the grid is rotated.
    lat0, lon0 = utm_inverse(717623.0, 8278698.0, 18, False)
    expected = far.geodetic_to_local(lat0, lon0, 0.0)
    assert mesh.vertices[0][0] == pytest.approx(expected.x(), abs=0.05)
    assert mesh.vertices[0][1] == pytest.approx(expected.y(), abs=0.05)


# ---- robustness ------------------------------------------------------------

def test_ngon_faces_are_fan_triangulated(tmp_path):
    quad = OBJ.replace("usemtl material0000\nf 1/1 2/2 3/3\n"
                       "usemtl material0001\nf 1/1 3/3 4/4\n",
                       "usemtl material0000\nf 1/1 2/2 3/3 4/4\n")
    obj = _write_odm_tree(tmp_path, obj=quad)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert mesh.triangle_count == 2
    assert mesh.materials[0].count == 2


def test_faces_without_texcoords_still_load(tmp_path):
    plain = "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    obj = _write_odm_tree(tmp_path, obj=plain, mtl=None)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert mesh.triangle_count == 1
    assert mesh.uvs.shape == (3, 2)
    assert np.all(mesh.uvs == 0.0)


# ---- texture planning ------------------------------------------------------

def test_hardware_limit_is_a_hard_ceiling():
    """An atlas over GL_MAX_TEXTURE_SIZE doesn't render badly — it fails to
    upload at all. Chanchallay's real atlas vs a real AMD 780M."""
    sizes = [(24576, 24576)] + [(2048, 2048)] * 20
    planned = plan_texture_sizes(sizes, gl_max=16384, budget=10 * 1024**3)
    assert max(max(w, h) for w, h in planned) <= 16384
    assert planned[1:] == [(2048, 2048)] * 20      # small ones untouched


def test_budget_shrinks_the_largest_atlas_first():
    sizes = [(24576, 24576)] + [(2048, 2048)] * 20
    planned = plan_texture_sizes(sizes, gl_max=16384,
                                 budget=DEFAULT_TEXTURE_BUDGET)
    assert atlas_bytes(planned) <= DEFAULT_TEXTURE_BUDGET
    assert planned[1:] == [(2048, 2048)] * 20      # detail kept where it's cheap
    assert planned[0][0] < 16384                   # the big sheet paid for it


def test_non_square_atlas_keeps_its_aspect_ratio():
    planned = plan_texture_sizes([(20000, 5000)], gl_max=8192,
                                 budget=10 * 1024**3)
    w, h = planned[0]
    assert max(w, h) <= 8192
    assert w / h == pytest.approx(4.0, rel=1e-2)


def test_planner_stops_before_making_imagery_useless():
    """A budget too small to satisfy must not grind atlases down to nothing —
    better to overshoot than to hand back a survey you can't trace over."""
    planned = plan_texture_sizes([(4096, 4096)] * 8, gl_max=16384, budget=1)
    assert all(max(w, h) >= 256 for w, h in planned)


def test_planner_handles_no_textures():
    assert plan_texture_sizes([], gl_max=16384) == []


def test_atlas_within_limits_is_left_alone():
    sizes = [(1024, 1024), (512, 512)]
    assert plan_texture_sizes(sizes, gl_max=16384) == sizes


def test_load_atlas_downscales_and_caches(tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache"))
    src = tmp_path / "atlas.png"
    QImage(1024, 1024, QImage.Format.Format_RGB32).save(str(src), "PNG")

    img = load_atlas(src, (256, 256))
    assert (img.width(), img.height()) == (256, 256)

    cached = list((tmp_path / "cache" / "odm").glob("*.jpg"))
    assert len(cached) == 1
    # Second read must come from the cache, not the 1024px original.
    again = load_atlas(src, (256, 256))
    assert (again.width(), again.height()) == (256, 256)


# ---- querying the surface --------------------------------------------------

def _ramp(tmp_path, size=40.0, slope=0.1):
    """A single quad sloping in +X: Z is exactly ``slope * x``, so every
    sampled elevation has an arithmetic answer to check against."""
    obj = ["v 0 0 0", f"v {size} 0 {size * slope}",
           f"v {size} {size} {size * slope}", f"v 0 {size} 0",
           "f 1 2 3", "f 1 3 4"]
    path = _write_odm_tree(tmp_path, obj="\n".join(obj) + "\n",
                           anchor=None, mtl=None)
    return load_odm_obj(path, _datum_at_anchor())


def test_height_at_interpolates_across_the_surface(tmp_path):
    mesh = _ramp(tmp_path)
    assert mesh.height_at(0.0, 20.0) == pytest.approx(0.0, abs=1e-4)
    assert mesh.height_at(20.0, 20.0) == pytest.approx(2.0, abs=1e-4)
    assert mesh.height_at(37.5, 5.0) == pytest.approx(3.75, abs=1e-4)


def test_height_at_outside_the_survey_is_none(tmp_path):
    """Off the flight there is no answer — a profile must show a gap, not a
    made-up elevation."""
    mesh = _ramp(tmp_path)
    assert mesh.height_at(-5.0, 20.0) is None
    assert mesh.height_at(20.0, 500.0) is None


def test_height_at_hits_corners_and_edges(tmp_path):
    mesh = _ramp(tmp_path, size=40.0)
    assert mesh.height_at(0.0, 0.0) == pytest.approx(0.0, abs=1e-4)
    assert mesh.height_at(40.0, 40.0) == pytest.approx(4.0, abs=1e-4)
    # The shared diagonal of the two triangles must not be a crack.
    assert mesh.height_at(20.0, 20.0) is not None


def test_overhang_returns_the_upper_surface(tmp_path):
    """Two sheets over the same plan area: the one you would stand on wins."""
    obj = ["v 0 0 0", "v 10 0 0", "v 10 10 0", "v 0 10 0",
           "v 0 0 5", "v 10 0 5", "v 10 10 5", "v 0 10 5",
           "f 1 2 3", "f 1 3 4", "f 5 6 7", "f 5 7 8"]
    path = _write_odm_tree(tmp_path, obj="\n".join(obj) + "\n",
                           anchor=None, mtl=None)
    mesh = load_odm_obj(path, _datum_at_anchor())
    assert mesh.height_at(5.0, 5.0) == pytest.approx(5.0, abs=1e-4)


def test_index_is_rebuilt_after_moving_the_mesh(tmp_path):
    """The import re-zeroes Z when there's no DEM; a stale index would keep
    answering from where the geometry used to be."""
    mesh = _ramp(tmp_path)
    assert mesh.height_at(20.0, 20.0) == pytest.approx(2.0, abs=1e-4)
    mesh.vertices[:, 2] += 100.0
    mesh.invalidate_index()
    assert mesh.height_at(20.0, 20.0) == pytest.approx(102.0, abs=1e-4)


def test_empty_mesh_has_no_heights(tmp_path):
    obj = _write_odm_tree(tmp_path, obj="# empty\n", mtl=None)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert mesh.height_at(0.0, 0.0) is None


def test_sampler_feeds_a_longitudinal_profile(tmp_path):
    """The bridge case: a traced line across the survey must come back as
    stations with real elevations, straight from the flight."""
    from PySide6.QtGui import QVector3D

    from georef.photomesh import PhotoMeshSampler
    from georef.profile import sample_profile

    mesh = _ramp(tmp_path, size=40.0, slope=0.1)
    datum = _datum_at_anchor()
    sampler = PhotoMeshSampler(mesh, datum)

    line = [QVector3D(0.0, 20.0, 0.0), QVector3D(40.0, 20.0, 0.0)]
    profile = sample_profile(line, sampler, spacing=10.0)

    assert profile.samples, "the profile must not come back empty"
    assert profile.samples[0].elevation == pytest.approx(0.0, abs=1e-3)
    assert profile.samples[-1].elevation == pytest.approx(4.0, abs=1e-3)
    # A constant 10% slope must read as a constant 10% slope.
    first, last = profile.samples[0], profile.samples[-1]
    rise = last.elevation - first.elevation
    run = last.station - first.station
    assert rise / run == pytest.approx(0.1, rel=1e-3)


def test_sampler_reports_gaps_outside_the_flight(tmp_path):
    from PySide6.QtGui import QVector3D

    from georef.photomesh import PhotoMeshSampler

    mesh = _ramp(tmp_path)
    sampler = PhotoMeshSampler(mesh, _datum_at_anchor())
    sampler.ensure_area(0, 0, 1, 1)                      # no-op, must not raise
    assert sampler.elevation_at_local(QVector3D(20.0, 20.0, 0.0)) is not None
    assert sampler.elevation_at_local(QVector3D(-99.0, 20.0, 0.0)) is None


# ---- the vertical reference ------------------------------------------------

def test_vertical_origin_is_the_foot_of_the_survey(tmp_path):
    """The model must sit ON the Z=0 plane, because that plane is where the
    flat base map lives and a map has to read as ground."""
    from georef.photomesh import vertical_origin

    mesh = _ramp(tmp_path, size=40.0, slope=0.1)     # Z = 0.1x, 0 .. 4
    mesh.vertices[:, 2] += 1700.0                    # a real Andean altitude
    mesh.invalidate_index()
    origin = vertical_origin(mesh)
    assert origin == pytest.approx(1700.0, abs=0.1)  # the low end, not mid-slope
    assert (mesh.vertices[:, 2] - origin).max() == pytest.approx(4.0, abs=0.1)


def test_vertical_origin_ignores_reconstruction_spikes(tmp_path):
    """Photogrammetry leaves holes and spikes. On the real survey the single
    lowest vertex sat 45 m below the 0.1th percentile — 94 of 222 622 — and
    anchoring the scene on it would drop everything into a hole that isn't
    there."""
    from georef.photomesh import vertical_origin

    # A 30x30 grid of ground at 1800 m, plus 2 bad vertices 200 m down: 0.2%,
    # the same order as the real thing.
    n = 30
    verts, faces = [], []
    for j in range(n):
        for i in range(n):
            verts.append(f"v {i * 10} {j * 10} 1800.0")
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i + 1
            faces.append(f"f {a} {a + 1} {a + n + 1}")
            faces.append(f"f {a} {a + n + 1} {a + n}")
    verts[0] = "v 0 0 1600.0"
    verts[1] = "v 10 0 1600.0"
    path = _write_odm_tree(tmp_path, obj="\n".join(verts + faces) + "\n",
                           anchor=None, mtl=None)
    mesh = load_odm_obj(path, _datum_at_anchor())

    assert mesh.vertices[:, 2].min() == pytest.approx(1600.0, abs=0.1)
    origin = vertical_origin(mesh)
    assert origin == pytest.approx(1800.0, abs=1.0)   # the spikes didn't win


def test_vertical_origin_is_deterministic(tmp_path):
    """THE regression that started this: the zero used to come from the global
    DEM, so it depended on whether tiles had finished downloading — the same
    model could import at two different sets of elevations. It must depend on
    nothing but the survey."""
    from georef.photomesh import vertical_origin

    obj = _write_odm_tree(tmp_path)
    first = vertical_origin(load_odm_obj(obj, _datum_at_anchor()))
    second = vertical_origin(load_odm_obj(obj, _datum_at_anchor()))
    assert first == second
    assert first is not None


def test_vertical_origin_of_an_empty_mesh_is_none(tmp_path):
    from georef.photomesh import vertical_origin

    obj = _write_odm_tree(tmp_path, obj="# nothing\n", mtl=None)
    assert vertical_origin(load_odm_obj(obj, _datum_at_anchor())) is None


def test_sampler_reports_absolute_altitude_not_local_metres(tmp_path):
    """A profile must read like a level, not like an offset from an unknown
    plane — and must agree with what DEMSampler returns."""
    from PySide6.QtGui import QVector3D

    from georef.photomesh import PhotoMeshSampler

    mesh = _ramp(tmp_path, size=40.0, slope=0.1)     # local Z = 0.1x
    datum = SceneDatum(-15.5, -72.5, 1700.0)         # scene Z=0 sits at 1700 m
    sampler = PhotoMeshSampler(mesh, datum)
    assert sampler.elevation_at_local(QVector3D(20.0, 20.0, 0.0)) == \
        pytest.approx(1702.0, abs=1e-3)


def test_the_survey_declares_where_its_heights_came_from(tmp_path):
    from georef.photomesh import VERTICAL_ODM

    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert mesh.vertical_reference == VERTICAL_ODM


def test_profile_csv_states_its_vertical_reference():
    """The deliverable has to be self-describing: it gets emailed, filed, and
    opened a year later by somebody who wasn't there."""
    from georef.profile import Profile, ProfileSample, profile_to_csv

    profile = Profile(samples=[ProfileSample(0.0, 0.0, 0.0, 1783.19)], length=0.0)
    text = profile_to_csv(profile, vertical="odm", datum_alt=1746.27)
    assert "ellipsoidal" in text                 # the caveat is spelled out
    assert "ground control points" in text
    assert "1746.270" in text                    # where Z=0 sits
    assert "1783.190" in text

    local = profile_to_csv(profile, vertical="local")
    assert "relative, not absolute" in local


# ---- storing the survey in the document ------------------------------------

def _round_trip(tmp_path, mesh):
    """Save a scene holding ``mesh`` to an .igz and load it back."""
    from core.scene import Scene
    from formats import igz

    scene = Scene()
    scene.photo_mesh = mesh
    out = tmp_path / "doc.igz"
    igz.save_scene(scene, out)

    back = Scene()
    igz.load_into(back, out)
    return back.photo_mesh, out


def test_survey_survives_a_save_load_round_trip(tmp_path):
    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor(), ground_ref=1750.0)
    restored, _ = _round_trip(tmp_path, mesh)

    assert restored is not None
    assert restored.triangle_count == mesh.triangle_count
    assert restored.vertex_count == mesh.vertex_count
    np.testing.assert_allclose(restored.vertices, mesh.vertices, atol=1e-6)
    np.testing.assert_allclose(restored.uvs, mesh.uvs, atol=1e-6)
    np.testing.assert_array_equal(restored.triangles, mesh.triangles)


def test_anchor_and_material_runs_survive(tmp_path):
    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    restored, _ = _round_trip(tmp_path, mesh)

    assert restored.anchor == mesh.anchor          # still georeferenced
    assert [(m.name, m.start, m.count) for m in restored.materials] == \
           [(m.name, m.start, m.count) for m in mesh.materials]


def test_atlases_are_embedded_not_referenced(tmp_path):
    """The whole point: the document must open on a machine that never had the
    455 MB ODM export."""
    from PySide6.QtGui import QImage

    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    image = QImage(64, 64, QImage.Format.Format_RGB32)
    image.fill(0xFF3366AA)
    mesh.images = {0: image}

    restored, out = _round_trip(tmp_path, mesh)
    assert 0 in restored.images
    assert (restored.images[0].width(), restored.images[0].height()) == (64, 64)
    # And it really is inside the container, not a path pointing outside.
    import zipfile
    with zipfile.ZipFile(out) as zf:
        assert "survey/atlas-00.jpg" in zf.namelist()
        assert "survey/geometry.npz" in zf.namelist()
    assert restored.materials[0].texture is None    # nothing to resolve on disk
    assert restored.missing_textures == []


def test_vertical_reference_survives_the_round_trip(tmp_path):
    from georef.photomesh import VERTICAL_ODM

    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    restored, _ = _round_trip(tmp_path, mesh)
    assert restored.vertical_reference == VERTICAL_ODM


def test_layer_survives_the_round_trip(tmp_path):
    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    mesh.layer = "Survey"
    restored, _ = _round_trip(tmp_path, mesh)
    assert restored.layer == "Survey"


def test_the_survey_answers_to_the_layer_system(tmp_path):
    """A survey is tagged like a Group, so hiding its layer hides it through
    exactly the same machinery as everything else in the document."""
    from core.layers import Layer, layer_of
    from core.scene import Scene

    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    scene = Scene()
    scene.layers.append(Layer("Survey"))
    scene.photo_mesh = mesh

    assert layer_of(mesh) == "Layer 0"          # untagged reads as default
    assert scene.entity_visible(mesh) is True

    mesh.layer = "Survey"
    assert layer_of(mesh) == "Survey"
    assert scene.entity_visible(mesh) is True

    scene.layer("Survey").visible = False
    assert scene.entity_visible(mesh) is False   # hidden by its layer alone


def test_visibility_is_remembered(tmp_path):
    obj = _write_odm_tree(tmp_path)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    mesh.visible = False
    restored, _ = _round_trip(tmp_path, mesh)
    assert restored.visible is False


def test_document_without_a_survey_stays_plain_json(tmp_path):
    """No survey must not turn every document into a ZIP container."""
    from core.scene import Scene
    from formats import igz

    out = tmp_path / "plain.igz"
    igz.save_scene(Scene(), out)
    assert out.read_bytes()[:2] != b"PK"

    back = Scene()
    igz.load_into(back, out)
    assert back.photo_mesh is None


def test_damaged_survey_block_does_not_break_the_document(tmp_path):
    """A missing geometry blob must cost the survey, not the whole file."""
    from georef.photomesh import unpack_mesh
    assert unpack_mesh({"geometry": "survey/geometry.npz"}, lambda m: b"") is None
    assert unpack_mesh({"geometry": "gone"}, lambda m: b"not an npz") is None


def test_empty_mesh_has_empty_bounds(tmp_path):
    obj = _write_odm_tree(tmp_path, obj="# nothing here\n", mtl=None)
    mesh = load_odm_obj(obj, _datum_at_anchor())
    assert mesh.vertex_count == 0
    assert mesh.bounds() == (None, None)
