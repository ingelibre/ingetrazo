# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pictures placed on sheets travel inside the document.

They were saved by path alone: a document saved on Windows and opened on
the laptop showed crossed boxes where the renders and the photo of «L-07A
Detalle de pileta» were (Marco, 21-11). Now they are packed like the face
textures, and come back as files of this machine's image cache."""
from __future__ import annotations

import json
import zipfile

from PySide6.QtGui import QImage

from core.composition import Composicion, ImagenItem
from core.scene import Scene
from formats import igz


def _png(path, rgb=0x3C78B4):
    img = QImage(6, 4, QImage.Format_RGB32)
    img.fill(rgb)
    img.save(str(path))
    return path


def _scene_with_picture(png) -> Scene:
    scene = Scene()
    sheet = Composicion(name="L-07A Detalle de pileta")
    sheet.images.append(ImagenItem(path=str(png), w_mm=80, h_mm=50))
    scene.compositions.append(sheet)
    return scene


def _members(path):
    with zipfile.ZipFile(path) as z:
        return [n for n in z.namelist() if n.startswith("textures/")]


def test_a_sheet_picture_rides_inside_and_comes_back_elsewhere(tmp_path):
    src = _png(tmp_path / "pileta_marco0.png")
    scene = _scene_with_picture(src)
    out = tmp_path / "plaza.igz"
    igz.save_scene(scene, out)
    assert len(_members(out)) == 1
    with zipfile.ZipFile(out) as z:
        doc = z.read("document.json").decode()
    assert str(tmp_path) not in doc            # no machine-local path left
    src.unlink()                               # «another machine»
    back = Scene()
    igz.load_into(back, out)
    item = back.compositions[0].images[0]
    assert item.path and item.path != str(src)
    img = QImage(item.path)
    assert not img.isNull() and img.size().width() == 6
    assert not hasattr(item, "embed")


def test_saving_leaves_the_live_sheet_as_it_was(tmp_path):
    src = _png(tmp_path / "a.png")
    scene = _scene_with_picture(src)
    igz.save_scene(scene, tmp_path / "a.igz")
    assert scene.compositions[0].images[0].path == str(src)


def test_a_reopened_document_saves_its_pictures_again(tmp_path):
    src = _png(tmp_path / "a.png")
    igz.save_scene(_scene_with_picture(src), tmp_path / "a.igz")
    src.unlink()
    back = Scene()
    igz.load_into(back, tmp_path / "a.igz")
    igz.save_scene(back, tmp_path / "b.igz")
    assert _members(tmp_path / "b.igz") == _members(tmp_path / "a.igz") != []


def test_one_picture_on_two_sheets_is_stored_once(tmp_path):
    src = _png(tmp_path / "a.png")
    scene = _scene_with_picture(src)
    other = Composicion(name="L-07")
    other.images.append(ImagenItem(path=str(src)))
    scene.compositions.append(other)
    igz.save_scene(scene, tmp_path / "a.igz")
    assert len(_members(tmp_path / "a.igz")) == 1


def test_a_picture_whose_file_is_gone_keeps_its_path(tmp_path):
    """Nothing to pack: the reference stays, so the document is no worse
    than before — and the picture shows again once the file is back."""
    gone = r"C:\Users\Admin\AppData\Local\IngeTrazo\textures\x.png"
    scene = Scene()
    sheet = Composicion(name="L-03")
    sheet.images.append(ImagenItem(path=gone))
    scene.compositions.append(sheet)
    stats = igz.save_scene(scene, tmp_path / "a.igz")
    assert stats["missing"] == 1
    back = Scene()
    igz.load_into(back, tmp_path / "a.igz")
    assert back.compositions[0].images[0].path == gone


def test_the_text_layout_puts_the_picture_in_its_folder(tmp_path):
    src = _png(tmp_path / "a.png")
    out = tmp_path / "doc" / "Plaza.igz"
    out.parent.mkdir()
    igz.save_scene(_scene_with_picture(src), out, fmt="json")
    data = json.loads(out.read_bytes())
    assert str(tmp_path / "a.png") not in json.dumps(data)
    assert list((out.parent / "Plaza.assets" / "textures").iterdir())
    src.unlink()
    back = Scene()
    igz.load_into(back, out)
    assert not QImage(back.compositions[0].images[0].path).isNull()
