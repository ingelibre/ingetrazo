# SPDX-License-Identifier: GPL-3.0-or-later
"""Saving never rewrites the live scene's textures (#877).

A group or component painted whole kept its paint in ``group.material``,
and the save copied it with a shallow ``dict()``: packing the texture into
the archive then swapped ``"path"`` for ``"embed"`` in the live dict too.
The next save of the session — an autosave is enough — found no path and
wrote the document without the image."""
from __future__ import annotations

import zipfile

from PySide6.QtGui import QImage, QVector3D as V

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


def _png(tmp_path):
    png = tmp_path / "wood.png"
    img = QImage(4, 4, QImage.Format_RGB32)
    img.fill(0x8B5A2B)
    img.save(str(png))
    return png


def _painted_group(png) -> tuple[Scene, Group]:
    scene = Scene()
    g = Group(name="Caja")
    g.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g.material = {"color": [0.5, 0.4, 0.3],
                  "texture": {"path": str(png), "sw": 1.0, "sh": 1.0,
                              "base": str(png)}}
    scene.groups.append(g)
    return scene, g


def _members(path):
    with zipfile.ZipFile(path) as z:
        return [n for n in z.namelist() if n.startswith("textures/")]


def test_saving_leaves_a_group_paint_as_it_was(tmp_path):
    png = _png(tmp_path)
    scene, g = _painted_group(png)
    before = {k: dict(v) if isinstance(v, dict) else v
              for k, v in g.material.items()}
    igz.save_scene(scene, tmp_path / "a.igz")
    assert g.material == before


def test_a_second_save_still_carries_the_image(tmp_path):
    png = _png(tmp_path)
    scene, _g = _painted_group(png)
    igz.save_scene(scene, tmp_path / "a.igz")
    igz.save_scene(scene, tmp_path / "b.igz")
    assert _members(tmp_path / "b.igz") == _members(tmp_path / "a.igz") != []
    back = Scene()
    igz.load_into(back, tmp_path / "b.igz")
    tex = back.groups[0].material["texture"]
    assert tex.get("path") and tex.get("base")
    assert "embed" not in tex and "base_embed" not in tex


def test_shared_definitions_keep_their_face_textures(tmp_path):
    png = _png(tmp_path)
    scene = Scene()
    proto = Mesh()
    face = proto.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    face.attrs["texture"] = {"path": str(png), "sw": 1.0, "sh": 1.0}
    for name in ("A", "B"):
        scene.groups.append(Group(proto, name=name))
    for n in ("a.igz", "b.igz"):
        igz.save_scene(scene, tmp_path / n)
    assert face.attrs["texture"] == {"path": str(png), "sw": 1.0, "sh": 1.0}
    assert _members(tmp_path / "b.igz") != []
