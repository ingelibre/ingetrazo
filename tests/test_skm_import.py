# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""``.skm`` material files (#1482): read into a Material, and
taken by the Materials palette's *Import…* like an ``.igmat`` (#1427).

The fixtures are built here in the shape real files have (a ZIP with
``document.xml`` and the image under ``ref/``): colour only, textured with
its tile size, translucent, colourized, and the ways a file can be broken.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from formats import igmat                                         # noqa: E402
from formats.igmat import MaterialFileError                       # noqa: E402
from formats.skm import SkmError, load_skm                        # noqa: E402
from tools.paint import PaintTool                                 # noqa: E402

_NS = ('xmlns="http://sketchup.google.com/schemas/sketchup/1.0/material" '
       'xmlns:mat="http://sketchup.google.com/schemas/sketchup/1.0/material" '
       'xmlns:r="http://sketchup.google.com/schemas/1.0/references"')


def _png(path, rgb, size=8):
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(QColor.fromRgbF(*rgb))
    assert img.save(str(path))
    return Path(path).read_bytes()


def _skm(path, material_xml, files=None, ns=_NS):
    """An .skm as real files lay it out: document.xml, the two other XML
    files, a thumbnail and the images (``files``: member → bytes)."""
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
           f'<materialDocument {ns}>\n{material_xml}\n</materialDocument>\n')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("document.xml", doc)
        zf.writestr("documentProperties.xml", "<documentProperties/>")
        zf.writestr("references.xml", "<references/>")
        zf.writestr("doc_thumbnail.png", b"")
        for member, data in (files or {}).items():
            zf.writestr(member, data)
    return path


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
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


# ---- reading --------------------------------------------------------------

def test_a_colour_material(tmp_path):
    path = _skm(tmp_path / "rojo.skm",
                '<mat:material name="Rojo teja" type="0" colorRed="204" '
                'colorGreen="102" colorBlue="51" colorizeType="0" trans="0" '
                'useTrans="0" hasTexture="0"/>')
    (mat,) = load_skm(path)
    assert mat.name == "Rojo teja"
    assert mat.color == (0.8, 0.4, 0.2)
    assert mat.texture is None and mat.opacity is None


def test_a_textured_material_keeps_its_image_and_tile_size(tmp_path):
    """xScale / yScale are the tile size in inches: 11.81 in ≈ 0.3 m."""
    data = _png(tmp_path / "mdf.png", (0.8, 0.6, 0.4))
    path = _skm(tmp_path / "mdf.skm",
                '<mat:material name="MDF 18 mm" type="1" workflow="0" '
                'colorRed="204" colorGreen="153" colorBlue="102" '
                'colorizeType="0" trans="0" useTrans="0" hasTexture="1">'
                '<mat:texture textureFilename="mdf.png" xScale="96.0" '
                'yScale="48.0" avgColor="6724044"><mat:images>'
                '<mat:image id="1" path="mdf_1.png" file_name="mdf.png"/>'
                '</mat:images></mat:texture></mat:material>',
                {"ref/mdf_1.png": data})
    (mat,) = load_skm(path)
    assert mat.name == "MDF 18 mm"
    assert mat.color is None
    tex = mat.texture
    assert Path(tex["path"]).read_bytes() == data
    assert tex["sw"] == pytest.approx(96 * 0.0254)        # 2.44 m
    assert tex["sh"] == pytest.approx(48 * 0.0254)        # 1.22 m
    assert "tint" not in tex


@pytest.mark.parametrize("use, trans, opacity", [
    ("1", "0.5", 0.5), ("1", "0.75", 0.25), ("0", "0.5", None),
    ("1", "0", None)])
def test_translucency_counts_only_with_use_trans(tmp_path, use, trans,
                                                 opacity):
    path = _skm(tmp_path / "glass.skm",
                '<mat:material name="Vidrio" type="0" colorRed="150" '
                'colorGreen="200" colorBlue="230" '
                f'trans="{trans}" useTrans="{use}" hasTexture="0"/>')
    (mat,) = load_skm(path)
    assert mat.opacity == (pytest.approx(opacity) if opacity else None)


@pytest.mark.parametrize("ctype", [0, 1])
def test_a_colourized_texture_is_tinted_from_its_original(tmp_path, ctype):
    """type 2: the stored image is the original, re-tinted toward the
    colour, shift (0) or tint (1) — kept as a tint IngeTrazo can change
    or take off again."""
    data = _png(tmp_path / "piedra.png", (0.5, 0.5, 0.5))
    path = _skm(tmp_path / "piedra.skm",
                '<mat:material name="Piedra verde" type="2" colorRed="51" '
                f'colorGreen="153" colorBlue="51" colorizeType="{ctype}" '
                'hasTexture="1"><mat:texture textureFilename="piedra.png" '
                'xScale="39.37" yScale="39.37"><mat:images><mat:image id="1" '
                'path="piedra_1.png"/></mat:images></mat:texture>'
                '</mat:material>',
                {"ref/piedra_1.png": data})
    (mat,) = load_skm(path)
    tex = mat.texture
    assert tex["tint"] == pytest.approx([0.2, 0.6, 0.2])
    assert tex["tint_mode"] == ctype
    assert Path(tex["base"]).read_bytes() == data
    assert Path(tex["path"]).read_bytes() != data
    assert tex["sw"] == pytest.approx(1.0, abs=1e-4)


def test_the_image_is_found_by_its_file_name_or_alone_in_ref(tmp_path):
    """No mat:image (an older writer): textureFilename under ref/, else the
    only image there. No namespace at all is read the same."""
    data = _png(tmp_path / "a.png", (0.1, 0.5, 0.9))
    by_name = _skm(tmp_path / "a.skm",
                   '<material name="A" type="1" hasTexture="1">'
                   '<texture textureFilename="C:\\Texturas\\a.png"/>'
                   '</material>', {"ref/a.png": data}, ns="")
    alone = _skm(tmp_path / "b.skm",
                 '<mat:material name="B" type="1" hasTexture="1">'
                 '<mat:texture textureFilename="other.png"/></mat:material>',
                 {"ref/whatever_1.png": data})
    for path in (by_name, alone):
        (mat,) = load_skm(path)
        assert Path(mat.texture["path"]).read_bytes() == data
        assert mat.texture["sw"] == mat.texture["sh"] == 1.0  # no size: 1 m


def test_a_lost_image_leaves_the_colour(tmp_path):
    path = _skm(tmp_path / "lost.skm",
                '<mat:material name="Lost" type="1" colorRed="10" '
                'colorGreen="20" colorBlue="30" hasTexture="1">'
                '<mat:texture textureFilename="gone.png"/></mat:material>')
    (mat,) = load_skm(path)
    assert mat.texture is None
    assert mat.color == pytest.approx((10 / 255, 20 / 255, 30 / 255))


def test_a_nameless_material_is_named_after_its_file(tmp_path):
    path = _skm(tmp_path / "Ladrillo visto.skm",
                '<mat:material name="  " type="0" colorRed="1" '
                'colorGreen="2" colorBlue="3"/>')
    (mat,) = load_skm(path)
    assert mat.name == "Ladrillo visto"


@pytest.mark.parametrize("kind", ["not-zip", "no-doc", "dtd", "bad-xml",
                                  "no-material"])
def test_a_file_that_is_not_an_skm_is_refused(tmp_path, kind):
    path = tmp_path / "bad.skm"
    if kind == "not-zip":
        path.write_bytes(b"plain text, RAL 1000, 190, 189, 127")
    elif kind == "no-doc":
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("references.xml", "<references/>")
    elif kind == "dtd":
        _skm(path, '<!DOCTYPE x [<!ENTITY a "aaaa">]>'
                   '<mat:material name="&a;"/>')
    elif kind == "bad-xml":
        _skm(path, '<mat:material name="unclosed"')
    else:
        _skm(path, '<somethingElse/>')
    with pytest.raises(SkmError):
        load_skm(path)
    assert issubclass(SkmError, MaterialFileError)


# ---- the Materials palette ------------------------------------------------

@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_import_takes_an_skm(window, tmp_path, monkeypatch):
    from views import tray
    from views.tray import MaterialsPanel
    data = _png(tmp_path / "roble.png", (0.6, 0.4, 0.2))
    path = _skm(tmp_path / "Roble.SKM",
                '<mat:material name="Roble" type="1" hasTexture="1">'
                '<mat:texture textureFilename="roble.png" xScale="39.37" '
                'yScale="19.685"><mat:images><mat:image id="1" '
                'path="roble_1.png"/></mat:images></mat:texture>'
                '</mat:material>', {"ref/roble_1.png": data})
    seen = {}

    def ask(*args, **_kw):
        seen["filter"] = args[3]
        return str(path), ""
    monkeypatch.setattr(tray.file_dialogs, "getOpenFileName", ask)
    window.findChild(MaterialsPanel)._on_import_material()
    assert "*.skm" in seen["filter"] and "*.igmat" in seen["filter"]
    assert PaintTool.current_material.name == "Roble"
    assert PaintTool.current_texture["sh"] == pytest.approx(0.5, abs=1e-4)
    assert PaintTool.recent[0]["mat"] == "Roble"
