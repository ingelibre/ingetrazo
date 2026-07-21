# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""glTF/GLB + COLLADA (.dae) export: valid containers, geometry survives,
textures embed/copy, and the scene's geolocation rides along (the location a
sun/shadow study needs)."""
from __future__ import annotations

import json
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtGui import QImage, QVector3D

from core.history import History
from core.scene import Scene
from formats import dae as dae_format
from formats import gltf as gltf_format
from georef.datum import SceneDatum
import tests.test_fuzz_engine as F

_NS = "{http://www.collada.org/2005/11/COLLADASchema}"


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cube(scene, hist, size=4.0, height=3.0):
    loop = [V(0, 0), V(size, 0), V(size, size), V(0, size)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    f = scene.mesh.faces[0]
    F._push(scene, hist, f, height if f.normal().z() > 0 else -height)


def _make_png(path: Path) -> Path:
    img = QImage(4, 4, QImage.Format_RGBA8888)
    img.fill(0xFF3366CC)
    img.save(str(path), "PNG")
    return path


def _read_glb(path: Path):
    """Return (gltf_json_dict, bin_chunk_bytes) from a GLB file."""
    data = Path(path).read_bytes()
    magic, version, total = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "bad glTF magic"
    assert version == 2
    assert total == len(data)
    off = 12
    json_len, json_type = struct.unpack_from("<II", data, off)
    assert json_type == 0x4E4F534A, "first chunk must be JSON"
    off += 8
    gltf = json.loads(data[off:off + json_len].decode("utf-8"))
    off += json_len
    bin_bytes = b""
    if off < len(data):
        bin_len, bin_type = struct.unpack_from("<II", data, off)
        assert bin_type == 0x004E4942, "second chunk must be BIN"
        off += 8
        bin_bytes = data[off:off + bin_len]
    return gltf, bin_bytes


# ---- GLB -----------------------------------------------------------------------

def test_glb_is_valid_and_has_geometry(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "cube.glb"
    gltf_format.save_glb(scene, path)

    gltf, binc = _read_glb(path)
    assert gltf["asset"]["version"] == "2.0"
    assert gltf["meshes"][0]["primitives"], "expected at least one primitive"
    prim = gltf["meshes"][0]["primitives"][0]
    assert "POSITION" in prim["attributes"]
    assert "NORMAL" in prim["attributes"]
    assert "indices" in prim
    # POSITION accessor must carry min/max (required by the spec).
    pos_acc = gltf["accessors"][prim["attributes"]["POSITION"]]
    assert pos_acc["type"] == "VEC3" and len(pos_acc["min"]) == 3
    assert gltf["buffers"][0]["byteLength"] == len(binc)


def test_glb_is_y_up(tmp_path):
    # A box from z=0..3 in IngeTrazo (Z-up) must land y=0..3 in glTF (Y-up).
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist, height=3.0)
    path = tmp_path / "cube.glb"
    gltf_format.save_glb(scene, path)
    gltf, _ = _read_glb(path)
    ys = [gltf["accessors"][p["attributes"]["POSITION"]]["max"][1]
          for p in gltf["meshes"][0]["primitives"]]
    assert max(ys) > 2.9, "height should map to +Y in glTF"


def test_glb_embeds_geolocation(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    scene.georef = SceneDatum(-15.6167, -71.9333, 3416.0)  # Yanque, Arequipa
    path = tmp_path / "geo.glb"
    gltf_format.save_glb(scene, path)
    gltf, _ = _read_glb(path)
    geo = gltf["asset"]["extras"]["ingetrazo_geolocation"]
    assert abs(geo["lat"] - -15.6167) < 1e-6
    assert abs(geo["lon"] - -71.9333) < 1e-6
    assert abs(geo["alt"] - 3416.0) < 1e-3


def test_glb_embeds_texture_image(tmp_path):
    png = _make_png(tmp_path / "brick.png")
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    top = max(scene.mesh.faces, key=lambda f: f.centroid().z())
    top.attrs["texture"] = {"path": str(png), "sw": 1.0, "sh": 1.0}
    path = tmp_path / "tex.glb"
    gltf_format.save_glb(scene, path)
    gltf, binc = _read_glb(path)
    assert gltf.get("images"), "texture should embed an image"
    img = gltf["images"][0]
    assert img["mimeType"] == "image/png"
    # The embedded bytes are the real PNG (magic \x89PNG).
    view = gltf["bufferViews"][img["bufferView"]]
    blob = binc[view["byteOffset"]:view["byteOffset"] + view["byteLength"]]
    assert blob[:4] == b"\x89PNG"
    # A textured primitive carries UVs.
    assert any("TEXCOORD_0" in p["attributes"]
               for p in gltf["meshes"][0]["primitives"])


# ---- DAE -----------------------------------------------------------------------

def test_dae_is_wellformed_zup_with_geometry(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "cube.dae"
    dae_format.save_dae(scene, path)

    root = ET.parse(path).getroot()
    up = root.find(f"{_NS}asset/{_NS}up_axis")
    assert up is not None and up.text.strip() == "Z_UP"
    tris = list(root.iter(f"{_NS}triangles"))
    assert tris, "expected <triangles>"
    total = sum(int(t.get("count")) for t in tris)
    assert total == 12  # box = 12 triangles
    # geometry sits inside a <node> (importers skip top-level instance_geometry)
    node = root.find(f"{_NS}library_visual_scenes/{_NS}visual_scene/{_NS}node")
    assert node.find(f"{_NS}instance_geometry") is not None


def test_dae_geolocation_present_only_when_georeferenced(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    plain = tmp_path / "plain.dae"
    dae_format.save_dae(scene, plain)
    root = ET.parse(plain).getroot()
    assert root.find(f"{_NS}asset/{_NS}coverage") is None

    scene.georef = SceneDatum(-15.6167, -71.9333, 3416.0)
    geo = tmp_path / "geo.dae"
    dae_format.save_dae(scene, geo)
    root = ET.parse(geo).getroot()
    loc = root.find(f"{_NS}asset/{_NS}coverage/{_NS}geographic_location")
    assert loc is not None
    assert abs(float(loc.find(f"{_NS}latitude").text) - -15.6167) < 1e-6
    assert abs(float(loc.find(f"{_NS}longitude").text) - -71.9333) < 1e-6


def test_dae_roundtrip_geometry_and_location(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    scene.georef = SceneDatum(-15.6167, -71.9333, 3416.0)
    path = tmp_path / "rt.dae"
    dae_format.save_dae(scene, path)

    # Re-import into a fresh scene: geometry returns and the location is adopted.
    scene2 = Scene()
    dae_format.load_dae(scene2, path)
    assert scene2.mesh.faces or scene2.groups
    assert scene2.georef is not None
    assert abs(scene2.georef.lat - -15.6167) < 1e-5
    assert abs(scene2.georef.lon - -71.9333) < 1e-5


def test_dae_copies_texture_image(tmp_path):
    png = _make_png(tmp_path / "wood.png")
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    top = max(scene.mesh.faces, key=lambda f: f.centroid().z())
    top.attrs["texture"] = {"path": str(png), "sw": 1.0, "sh": 1.0}
    out = tmp_path / "sub" / "tex.dae"
    out.parent.mkdir()
    dae_format.save_dae(scene, out)
    root = ET.parse(out).getroot()
    img = root.find(f"{_NS}library_images/{_NS}image/{_NS}init_from")
    assert img is not None and img.text == "wood.png"
    assert (out.parent / "wood.png").exists(), "image copied next to the .dae"
