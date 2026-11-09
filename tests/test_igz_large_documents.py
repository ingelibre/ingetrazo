# SPDX-License-Identifier: GPL-3.0-or-later
"""Large documents are written compact and deflated fast (#158); small
ones stay indented. Either way the document reads back the same."""
from __future__ import annotations

import json
import zipfile

from core.scene import Scene
from formats import igz


def _doc(tmp_path, n_faces: int, texture=None):
    faces = []
    for i in range(n_faces):
        f = {"vertices": [[i, 0, 0], [i + 1, 0, 0], [i + 1, 1, 0]]}
        if texture:
            f["texture"] = {"path": str(texture), "sw": 1.0, "sh": 1.0}
        faces.append(f)
    src = tmp_path / f"src{n_faces}.igz"
    src.write_text(json.dumps({"igz_format": 1,
                               "scene": {"edges": [], "faces": faces}}))
    scene = Scene()
    igz.load_into(scene, src)
    return scene


def _shape(scene):
    return sorted(
        tuple(sorted((round(v.x(), 6), round(v.y(), 6), round(v.z(), 6))
                     for v in f.vertices))
        for f in scene.mesh.faces)


def _text(path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(path) as zf:
            return zf.read("document.json").decode("utf-8")
    return raw.decode("utf-8")


def test_a_small_document_stays_indented(tmp_path):
    scene = _doc(tmp_path, 3)
    out = tmp_path / "small.igz"
    igz.save_scene(scene, out)
    assert "\n  " in _text(out)


def test_a_large_document_is_compact_and_reads_back_the_same(
        tmp_path, monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 10)
    scene = _doc(tmp_path, 30)
    out = tmp_path / "large.igz"
    igz.save_scene(scene, out)
    text = _text(out)
    assert "\n" not in text and ", " not in text
    again = Scene()
    igz.load_into(again, out)
    assert _shape(again) == _shape(scene)


def test_a_large_textured_container_reads_back_the_same(
        tmp_path, monkeypatch):
    from PySide6.QtGui import QImage
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 10)
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache"))
    png = tmp_path / "t.png"
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x3689E6)
    img.save(str(png))
    scene = _doc(tmp_path, 30, texture=png)
    out = tmp_path / "large-tex.igz"
    assert igz.save_scene(scene, out)["embedded"] == 1
    assert out.read_bytes().startswith(b"PK")
    assert "\n" not in _text(out)
    again = Scene()
    igz.load_into(again, out)
    assert _shape(again) == _shape(scene)


def test_the_count_includes_the_loose_mesh_and_each_prototype_once():
    from core.group import Group
    from core.mesh import Mesh
    from PySide6.QtGui import QMatrix4x4, QVector3D as V
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])   # 1 + 3
    proto = Mesh()
    proto.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)])        # 1 + 3
    for _ in range(3):                    # placed three times, written once
        g = Group(proto)
        g.xform = QMatrix4x4()
        scene.groups.append(g)
    assert igz._live_element_count(scene) == 4 + 4
