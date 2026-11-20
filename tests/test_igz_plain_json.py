# SPDX-License-Identifier: GPL-3.0-or-later
"""``save_scene(..., fmt="json")``: plain JSON for version control.

Always indented text, whatever the size, images in ``<name>.assets/``
beside it — and it opens again as the same model."""
from __future__ import annotations

import json
import shutil

import pytest
from PySide6.QtGui import QVector3D as V

from core.scene import Scene
from formats import igz
from tests.test_igz_formats_unchanged import _PNG, _scene, fingerprint


@pytest.fixture
def textured(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    png = src / "wood.png"
    png.write_bytes(_PNG)
    return _scene(png)


def _faces(scene) -> int:
    return len(scene.mesh.faces) + sum(len(g.mesh.faces)
                                       for g in scene.groups)


def _texture(scene) -> dict | None:
    for f in scene.mesh.faces:
        if f.attrs.get("texture"):
            return f.attrs["texture"]
    return None


def test_a_textured_document_is_text_with_its_images_beside(textured,
                                                            tmp_path):
    out = tmp_path / "doc" / "Casa.igz"
    out.parent.mkdir()
    stats = igz.save_scene(textured, out, fmt="json")
    raw = out.read_bytes()
    assert not raw.startswith(b"PK")
    data = json.loads(raw)
    assert data["igz_format"] == igz.PLAIN_FORMAT
    assert data["assets"] == "Casa.assets"
    images = list((out.parent / "Casa.assets" / "textures").iterdir())
    assert len(images) == 1 and images[0].read_bytes() == _PNG
    assert stats["assets"] == 1 and stats["missing"] == 0
    # No machine-local path in the text: the entry names the member.
    assert str(tmp_path) not in raw.decode()

    back = Scene()
    igz.load_into(back, out)
    assert _faces(back) == _faces(textured)
    tex = _texture(back)
    assert tex and "embed" not in tex
    with open(tex["path"], "rb") as fh:
        assert fh.read() == _PNG


def test_it_travels_with_its_folder(textured, tmp_path):
    out = tmp_path / "a" / "Casa.igz"
    out.parent.mkdir()
    igz.save_scene(textured, out, fmt="json")
    moved = tmp_path / "elsewhere"
    shutil.copytree(out.parent, moved)
    shutil.rmtree(out.parent)
    back = Scene()
    igz.load_into(back, moved / "Casa.igz")
    assert _texture(back) and _texture(back).get("path")


def test_without_its_folder_the_geometry_still_opens(textured, tmp_path):
    out = tmp_path / "Casa.igz"
    igz.save_scene(textured, out, fmt="json")
    shutil.rmtree(tmp_path / "Casa.assets")
    back = Scene()
    igz.load_into(back, out)
    assert _faces(back) == _faces(textured)
    assert not (_texture(back) or {}).get("path")


def test_saving_twice_gives_the_same_bytes(textured, tmp_path):
    out = tmp_path / "Casa.igz"
    igz.save_scene(textured, out, fmt="json")
    first = out.read_bytes()
    image = next((tmp_path / "Casa.assets" / "textures").iterdir())
    stamp = image.stat().st_mtime_ns
    igz.save_scene(textured, out, fmt="json")
    assert out.read_bytes() == first
    assert image.stat().st_mtime_ns == stamp      # unchanged: not rewritten


def test_a_texture_taken_off_leaves_the_folder(textured, tmp_path):
    out = tmp_path / "Casa.igz"
    (tmp_path / "Casa.assets").mkdir()
    keep = tmp_path / "Casa.assets" / "notes.txt"   # not the writer's
    keep.write_text("mine")
    igz.save_scene(textured, out, fmt="json")
    for f in textured.mesh.faces:
        f.attrs.pop("texture", None)
    igz.save_scene(textured, out, fmt="json")
    assert "assets" not in json.loads(out.read_bytes())
    assert not (tmp_path / "Casa.assets" / "textures").exists()
    assert keep.read_text() == "mine"


def test_untextured_it_is_a_format_1_document_with_its_mark(tmp_path,
                                                           monkeypatch):
    import itertools

    import core.group
    for name in ("auto", "json"):
        count = itertools.count()
        monkeypatch.setattr(core.group, "new_uid",
                            lambda: f"{next(count):016x}")
        scene = _scene()
        # PR #1236: every document carries its own random IFC namespace;
        # the two saves must compare as the same document.
        scene.ifc_namespace = "0123456789abcdef0123456789abcdef"
        igz.save_scene(scene, tmp_path / f"{name}.igz", fmt=name)
    auto = json.loads((tmp_path / "auto.igz").read_bytes())
    plain = json.loads((tmp_path / "json.igz").read_bytes())
    assert plain.pop("layout") == igz.PLAIN_JSON_LAYOUT
    assert plain == auto
    assert not (tmp_path / "json.assets").exists()


def test_the_layout_is_remembered_on_open(textured, tmp_path):
    out = tmp_path / "Casa.igz"
    igz.save_scene(textured, out, fmt="json")
    back = Scene()
    igz.load_into(back, out)
    assert back.saved_layout == "json"
    igz.save_scene(textured, tmp_path / "zip.igz")
    igz.load_into(back, tmp_path / "zip.igz")
    assert back.saved_layout is None


def test_a_large_document_stays_text(tmp_path, monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    scene = _scene()
    out = tmp_path / "big.igz"
    igz.save_scene(scene, out, fmt="json")
    raw = out.read_bytes()
    assert not raw.startswith(b"PK")
    assert b'"geom"' not in raw and raw.startswith(b"{\n  ")
    back = Scene()
    igz.load_into(back, out)
    assert _faces(back) == _faces(scene)
    # ... while the default still packs it (format 3).
    igz.save_scene(scene, tmp_path / "packed.igz")
    assert (tmp_path / "packed.igz").read_bytes().startswith(b"PK")


def test_a_member_name_cannot_leave_the_folder(tmp_path):
    (tmp_path / "secret.png").write_bytes(_PNG)
    folder = igz._AssetFolder(tmp_path / "Casa.assets")
    for member in ("../secret.png", "textures/../../secret.png",
                   "/etc/passwd", "other/x.png"):
        with pytest.raises(KeyError):
            folder.read(member)


def test_an_unknown_format_is_refused(tmp_path):
    with pytest.raises(ValueError):
        igz.save_scene(Scene(), tmp_path / "x.igz", fmt="xml")


def test_fingerprint_helper_reads_plain_files(tmp_path):
    p = tmp_path / "x.igz"
    igz.save_scene(Scene(), p, fmt="json")
    assert len(fingerprint(p)) == 64
