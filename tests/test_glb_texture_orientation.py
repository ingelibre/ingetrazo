# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A textured GLB comes in the right way up (#1141).

glTF counts V from the top of the image; the viewport, like OBJ and COLLADA,
from the bottom. The exporter turned V over and the importer did not turn it
back, so every picture in a GLB came in upside down: the scale figure of a
file IngeTrazo itself had written, and the textures of anybody else's.
"""
from __future__ import annotations

import json
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QColor, QImage, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.scene import Scene  # noqa: E402
from core.texture import affine_uv, fit_uv_affine  # noqa: E402
from formats.glb import load_glb, read_triangles  # noqa: E402
from formats.gltf import save_glb  # noqa: E402


def _png_bytes(tmp_path) -> bytes:
    path = tmp_path / "picture.png"
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 30, 30))
    assert img.save(str(path))
    return path.read_bytes()


def _corners_uv(scene):
    """{(rounded x, rounded z): (u, v)} of every imported corner."""
    out = {}
    for face in scene.groups[-1].mesh.faces:
        points = [v.position for v in face.loop]
        uvs = affine_uv(face.attrs["texture"]["uvw"], points)
        for p, uv in zip(points, uvs):
            out[(round(p.x(), 4), round(p.z(), 4))] = uv
    return out


def _wall_glb(path, png: bytes, file_uvs, uv_transform=None) -> None:
    """A wall 1 m wide and 2 m tall, standing on the ground (glTF's Y is up),
    with the UVs ``file_uvs`` for its bottom-left, bottom-right, top-right and
    top-left corners. Written by hand: the file of another program."""
    positions = struct.pack("<12f", 0, 0, 0, 1, 0, 0, 1, 2, 0, 0, 2, 0)
    uvs = struct.pack("<8f", *[c for uv in file_uvs for c in uv])
    indices = struct.pack("<6I", 0, 1, 2, 0, 2, 3)
    blob = positions + uvs + indices + png
    blob += b"\0" * (-len(blob) % 4)
    views = []
    at = 0
    for part in (positions, uvs, indices, png):
        views.append({"buffer": 0, "byteOffset": at, "byteLength": len(part)})
        at += len(part)
    texture = {"index": 0}
    if uv_transform:
        texture["extensions"] = {"KHR_texture_transform": uv_transform}
    gltf = {
        "asset": {"version": "2.0", "generator": "Another program"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
            "indices": 2, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": texture}}],
        "textures": [{"source": 0}],
        "images": [{"bufferView": 3, "mimeType": "image/png"}],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 4,
             "type": "VEC3", "min": [0, 0, 0], "max": [1, 2, 0]},
            {"bufferView": 1, "componentType": 5126, "count": 4,
             "type": "VEC2"},
            {"bufferView": 2, "componentType": 5125, "count": 6,
             "type": "SCALAR"}],
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2,
                            12 + 8 + len(js) + 8 + len(blob)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        f.write(struct.pack("<II", len(blob), 0x004E4942) + blob)


def test_a_picture_comes_back_from_our_own_glb_the_right_way_up(tmp_path):
    _png_bytes(tmp_path)
    scene = Scene()
    corners = [V(0, 0, 0), V(1, 0, 0), V(1, 0, 2), V(0, 0, 2)]
    face = scene.loose_mesh.add_face(corners)
    face.attrs["texture"] = {
        "path": str(tmp_path / "picture.png"), "sw": 1.0, "sh": 2.0,
        "uvw": fit_uv_affine(corners, [(0, 0), (1, 0), (1, 1), (0, 1)])}
    path = tmp_path / "ours.glb"
    save_glb(scene, path)

    back = Scene()
    load_glb(back, path)

    uv = _corners_uv(back)
    assert uv[(0.0, 0.0)] == pytest.approx((0.0, 0.0), abs=1e-5)
    assert uv[(1.0, 0.0)] == pytest.approx((1.0, 0.0), abs=1e-5)
    assert uv[(1.0, 2.0)] == pytest.approx((1.0, 1.0), abs=1e-5)
    assert uv[(0.0, 2.0)] == pytest.approx((0.0, 1.0), abs=1e-5)


def test_the_file_of_another_program_comes_in_the_right_way_up(tmp_path):
    """V = 0 is the top row of the image, by the glTF specification."""
    path = tmp_path / "theirs.glb"
    # The whole picture, stood up: V = 0 (its top row) on top of the wall.
    _wall_glb(path, _png_bytes(tmp_path), [(0, 1), (1, 1), (1, 0), (0, 0)])

    back = Scene()
    load_glb(back, path)

    uv = _corners_uv(back)
    # The viewport's V: 1 on top of the wall, 0 at its foot.
    assert uv[(0.0, 2.0)][1] == pytest.approx(1.0, abs=1e-5)
    assert uv[(1.0, 2.0)][1] == pytest.approx(1.0, abs=1e-5)
    assert uv[(0.0, 0.0)][1] == pytest.approx(0.0, abs=1e-5)
    assert uv[(1.0, 0.0)][1] == pytest.approx(0.0, abs=1e-5)


def test_a_texture_transform_is_read_before_v_is_turned_over(tmp_path):
    """KHR_texture_transform speaks the file's V: the top half of the image
    (V 0 to 0.5 in glTF) stays the top half, 0.5 to 1 in the viewport."""
    path = tmp_path / "half.glb"
    _wall_glb(path, _png_bytes(tmp_path), [(0, 1), (1, 1), (1, 0), (0, 0)],
              {"offset": [0.0, 0.0], "scale": [1.0, 0.5]})

    back = Scene()
    load_glb(back, path)

    uv = _corners_uv(back)
    assert uv[(0.0, 2.0)][1] == pytest.approx(1.0, abs=1e-5)
    assert uv[(0.0, 0.0)][1] == pytest.approx(0.5, abs=1e-5)


def test_the_reader_keeps_the_files_own_v(tmp_path):
    """scripts/glb_to_component.py writes what read_triangles gives back into
    a new GLB, so the reader must keep glTF's V: turned over there, the
    components it makes would come in upside down."""
    path = tmp_path / "theirs.glb"
    file_uvs = [(0, 1), (1, 1), (1, 0), (0, 0)]
    _wall_glb(path, _png_bytes(tmp_path), file_uvs)

    batches, _js = read_triangles(path)

    uvs = batches[0][1]
    assert np.allclose(uvs[0], np.array(file_uvs)[[0, 1, 2]])
