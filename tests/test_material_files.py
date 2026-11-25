# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Material files, ``.igmat`` (#1427): a material set up once — its name,
picture, tile size, tint, translucency and render finish — leaves the model
in a file and comes back the same in another project; «My materials» keeps
such files in the user's folder and offers them in every project."""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.materials import Material                               # noqa: E402
from formats import igmat                                         # noqa: E402
from formats.igmat import (                                       # noqa: E402
    MaterialFileError, load_materials, save_materials)
from tools.base import ToolContext                                # noqa: E402
from tools.paint import PaintTool                                 # noqa: E402


def _png(path, rgb, size=8):
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(QColor.fromRgbF(*rgb))
    assert img.save(str(path))
    return str(path)


def _same_image(a, b) -> bool:
    return Path(a).read_bytes() == Path(b).read_bytes()


@pytest.fixture(autouse=True)
def _reset_paint_state(tmp_path, monkeypatch):
    monkeypatch.setattr(igmat, "user_materials_dir",
                        lambda: tmp_path / "my-materials")
    PaintTool.recent = []
    QSettings().remove("paint/recent_materials")
    yield
    PaintTool.recent = []
    PaintTool.current_is_default = False
    PaintTool.current_material = None
    PaintTool.current_texture = None
    PaintTool.current_texture_plane = None
    PaintTool.current_opacity = None
    PaintTool.current_color = (0.80, 0.45, 0.30)
    QSettings().remove("paint/recent_materials")


# ---- the file -------------------------------------------------------------

def test_a_textured_material_comes_back_the_same(tmp_path):
    """Every field survives, and the picture travels inside the file: the
    original image can be gone by the time the file is opened."""
    pic = _png(tmp_path / "mdf.png", (0.8, 0.6, 0.4))
    base = _png(tmp_path / "mdf-raw.png", (0.5, 0.5, 0.5))
    mat = Material("MDF 18 mm", color=(0.8, 0.6, 0.4),
                   texture={"path": pic, "sw": 2.44, "sh": 1.22,
                            "rot": 90.0, "tint": [0.8, 0.6, 0.4],
                            "tint_mode": 1, "base": base},
                   opacity=0.9, finish="satin")
    out = tmp_path / "mdf.igmat"
    assert save_materials(out, [mat]) == {"embedded": 2, "missing": 0}
    Path(pic).unlink()
    Path(base).unlink()

    (back,) = load_materials(out)
    assert back.name == "MDF 18 mm"
    assert back.color == (0.8, 0.6, 0.4)
    assert back.opacity == 0.9 and back.finish == "satin"
    tex = dict(back.texture)
    new_pic, new_base = tex.pop("path"), tex.pop("base")
    assert tex == {"sw": 2.44, "sh": 1.22, "rot": 90.0,
                   "tint": [0.8, 0.6, 0.4], "tint_mode": 1}
    assert Path(new_pic).is_file() and Path(new_base).is_file()
    assert not _same_image(new_pic, new_base)
    # The material being saved is not touched by packing its images.
    assert mat.texture["path"] == pic and mat.texture["base"] == base


def test_one_file_holds_several_materials(tmp_path):
    pic = _png(tmp_path / "roble.png", (0.6, 0.4, 0.2))
    mats = [Material("Blanco", color=(1.0, 1.0, 1.0)),
            Material("Roble", texture={"path": pic, "sw": 1.0, "sh": 1.0})]
    out = tmp_path / "panels.igmat"
    save_materials(out, mats)
    back = load_materials(out)
    assert [m.name for m in back] == ["Blanco", "Roble"]
    assert back[0] == mats[0]
    assert _same_image(back[1].texture["path"], pic)


def test_saving_twice_writes_the_same_bytes(tmp_path):
    pic = _png(tmp_path / "a.png", (0.1, 0.2, 0.3))
    mat = Material("A", texture={"path": pic, "sw": 1.0, "sh": 1.0})
    save_materials(tmp_path / "1.igmat", [mat])
    save_materials(tmp_path / "2.igmat", [mat])
    assert ((tmp_path / "1.igmat").read_bytes()
            == (tmp_path / "2.igmat").read_bytes())


def test_an_image_that_cannot_be_read_is_counted_missing(tmp_path):
    mat = Material("Gone", color=(0.3, 0.3, 0.3),
                   texture={"path": str(tmp_path / "nope.png"),
                            "sw": 1.0, "sh": 1.0})
    out = tmp_path / "gone.igmat"
    assert save_materials(out, [mat]) == {"embedded": 0, "missing": 1}


def test_a_member_the_file_lost_keeps_the_rest_of_the_material(tmp_path):
    """The JSON still points at an image the ZIP no longer has: the
    material paints with its colour instead of failing the read; a
    material with nothing left to paint with is dropped."""
    out = tmp_path / "broken.igmat"
    doc = {"format": 1, "materials": [
        {"name": "Tinted", "color": [0.2, 0.4, 0.6],
         "texture": {"embed": "textures/x-a.png", "sw": 1.0, "sh": 1.0}},
        {"name": "Only a picture",
         "texture": {"embed": "textures/x-b.png", "sw": 1.0, "sh": 1.0}},
        {"name": "", "color": [0, 0, 0]},
        "junk",
    ]}
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("material.json", json.dumps(doc))
    (only,) = load_materials(out)
    assert only.name == "Tinted"
    assert only.texture is None and only.color == (0.2, 0.4, 0.6)


@pytest.mark.parametrize("content", [
    b"not a zip at all",
    "no-material-json",
    {"format": 99, "materials": []},
    {"format": 1},
    ["a", "list"],
])
def test_a_file_that_is_not_a_material_file_is_refused(tmp_path, content):
    out = tmp_path / "bad.igmat"
    if isinstance(content, bytes):
        out.write_bytes(content)
    else:
        with zipfile.ZipFile(out, "w") as zf:
            if content == "no-material-json":
                zf.writestr("document.json", "{}")
            else:
                zf.writestr("material.json", json.dumps(content))
    with pytest.raises(MaterialFileError):
        load_materials(out)


def test_my_materials_names_the_file_after_the_material(tmp_path):
    a = igmat.add_user_material(Material("MDF 15/18 mm: blanco",
                                         color=(1, 1, 1)))
    assert a.name == "MDF 1518 mm blanco.igmat"
    # Adding it again after a change replaces the file, not a second one.
    igmat.add_user_material(Material("MDF 15/18 mm: blanco",
                                     color=(0.9, 0.9, 0.9)))
    assert igmat.user_material_files() == [a]
    (back,) = load_materials(a)
    assert back.color == (0.9, 0.9, 0.9)
    assert igmat.file_stem("") == "Material"
    assert igmat.file_stem("...") == "Material"


# ---- the Materials palette ------------------------------------------------

@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _panel(w):
    from views.tray import MaterialsPanel
    return w.findChild(MaterialsPanel)


def _paint_a_face(window):
    vp = window.viewport
    face = vp.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(4, 0, 0),
                                   QVector3D(4, 4, 0), QVector3D(0, 4, 0)])
    vp._pixel_to_ray = lambda *_a: (None, None)
    vp.pick_face_any = lambda *_a: (face, None)
    PaintTool().on_click(ToolContext(viewport=vp, world=QVector3D(),
                                     screen=QPointF(0, 0),
                                     modifiers=Qt.NoModifier, snap=None))
    return face


def _import(window, monkeypatch, path):
    from views import tray
    monkeypatch.setattr(tray.file_dialogs, "getOpenFileName",
                        lambda *a, **k: (str(path), ""))
    _panel(window)._on_import_material()


def test_import_makes_it_the_paint_and_painting_registers_it(
        window, tmp_path, monkeypatch):
    pic = _png(tmp_path / "mdf.png", (0.8, 0.6, 0.4))
    out = tmp_path / "mdf.igmat"
    save_materials(out, [Material(
        "MDF", texture={"path": pic, "sw": 2.44, "sh": 1.22, "rot": 0.0},
        finish="satin")])
    _import(window, monkeypatch, out)

    assert PaintTool.current_is_default is False
    assert PaintTool.current_material.name == "MDF"
    assert PaintTool.current_texture["sw"] == 2.44
    assert isinstance(window.viewport.active_tool, PaintTool)
    assert PaintTool.recent[0]["mat"] == "MDF"
    # Importing alone changes nothing in the model.
    assert "MDF" not in window.viewport.scene.materials

    face = _paint_a_face(window)
    reg = window.viewport.scene.materials["MDF"]
    assert reg.finish == "satin"
    assert face.attrs["mat"] == "MDF"
    assert face.attrs["texture"]["sh"] == 1.22


def test_import_never_repaints_a_different_material_of_that_name(
        window, tmp_path, monkeypatch):
    scene = window.viewport.scene
    scene.materials["Wood"] = Material("Wood", color=(0.5, 0.3, 0.1))
    out = tmp_path / "wood.igmat"
    save_materials(out, [Material("Wood", color=(0.9, 0.8, 0.7))])
    _import(window, monkeypatch, out)
    assert PaintTool.current_material.name == "Wood (2)"
    assert PaintTool.current_color == (0.9, 0.8, 0.7)
    assert scene.materials["Wood"].color == (0.5, 0.3, 0.1)

    # The very same recipe is simply the model's own material.
    save_materials(out, [Material("Wood", color=(0.5, 0.3, 0.1))])
    _import(window, monkeypatch, out)
    assert PaintTool.current_material is scene.materials["Wood"]


def test_a_file_of_several_puts_them_all_in_recent(
        window, tmp_path, monkeypatch):
    out = tmp_path / "set.igmat"
    save_materials(out, [Material(n, color=(i / 4, 0.5, 0.5))
                         for i, n in enumerate(("A", "B", "C"))])
    _import(window, monkeypatch, out)
    assert PaintTool.current_material.name == "A"
    assert [e["mat"] for e in PaintTool.recent] == ["A", "B", "C"]
    panel = _panel(window)
    tips = [panel._recent_grid.itemAt(i).widget().toolTip()
            for i in range(panel._recent_grid.count())]
    assert tips == ["A", "B", "C"]


def test_a_bad_file_says_so_and_changes_nothing(
        window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[2]))
    out = tmp_path / "bad.igmat"
    out.write_bytes(b"nope")
    before = PaintTool.current_material
    _import(window, monkeypatch, out)
    assert warned and "bad.igmat" in warned[0]
    assert PaintTool.current_material is before and PaintTool.recent == []


def test_export_writes_the_models_material(window, tmp_path, monkeypatch):
    from views import tray
    scene = window.viewport.scene
    scene.materials["Glass"] = Material("Glass", color=(0.6, 0.8, 0.9),
                                        opacity=0.3, finish="glass")
    out = tmp_path / "glass"            # the extension is added
    monkeypatch.setattr(tray.file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    _panel(window)._export_material("Glass")
    (back,) = load_materials(tmp_path / "glass.igmat")
    assert back == scene.materials["Glass"]


def test_my_materials_offers_what_was_added(window, tmp_path):
    panel = _panel(window)
    scene = window.viewport.scene
    scene.materials["Melamina"] = Material("Melamina", color=(0.95, 0.95, 0.9),
                                           finish="satin")
    assert panel._my_toggle.text().endswith("(0)")
    panel._add_to_my_materials("Melamina")
    assert panel._my_toggle.text().endswith("(1)")
    assert [p.name for p in igmat.user_material_files()] == ["Melamina.igmat"]

    # Another project: the section reads the folder when opened.
    scene.materials.clear()
    panel._my_toggle.setChecked(True)
    assert panel._my_grid.count() == 1
    swatch = panel._my_grid.itemAt(0).widget()
    assert swatch.toolTip() == "Melamina"
    swatch.click()
    assert PaintTool.current_material.name == "Melamina"
    assert PaintTool.current_color == (0.95, 0.95, 0.9)

    # Open, it follows what is added next.
    scene.materials["Roble"] = Material("Roble", color=(0.6, 0.4, 0.2))
    panel._add_to_my_materials("Roble")
    assert [panel._my_grid.itemAt(i).widget().toolTip()
            for i in range(panel._my_grid.count())] == ["Melamina", "Roble"]


def test_removing_from_my_materials_deletes_its_file(
        window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    panel = _panel(window)
    path = igmat.add_user_material(Material("Old", color=(0.1, 0.1, 0.1)))
    panel._my_toggle.setChecked(True)
    assert panel._my_grid.count() == 1
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.No)
    panel._remove_my_material(path)
    assert path.exists()
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)
    panel._remove_my_material(path)
    assert not path.exists()
    assert panel._my_grid.count() == 0
    assert panel._my_toggle.text().endswith("(0)")


def test_a_recent_entry_from_a_file_keeps_its_finish_until_painted(
        window, tmp_path, monkeypatch):
    out = tmp_path / "steel.igmat"
    save_materials(out, [Material("Steel", color=(0.7, 0.7, 0.75),
                                  finish="metal")])
    _import(window, monkeypatch, out)
    PaintTool.current_material = None
    panel = _panel(window)
    panel._recent_grid.itemAt(0).widget().click()
    assert PaintTool.current_material.finish == "metal"
    _paint_a_face(window)
    assert window.viewport.scene.materials["Steel"].finish == "metal"
