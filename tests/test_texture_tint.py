# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Colourizing a texture — SketchUp's colour on a textured material.

Asked for by Marco while modelling Plaza Yanque: "when I edit a material's
texture, say the flagstone, I should be able to change the colour too".
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage, QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh
from core.texture import (COLORIZE_SHIFT, COLORIZE_TINT, colorize_image,
                          tinted_texture, untinted_texture)


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _png(pixels) -> bytes:
    """A tiny RGBA PNG from a list of rows of (r, g, b, a) tuples."""
    from PySide6.QtCore import QBuffer
    h, w = len(pixels), len(pixels[0])
    img = QImage(w, h, QImage.Format.Format_RGBA8888)
    for y, row in enumerate(pixels):
        for x, (r, g, b, a) in enumerate(row):
            img.setPixelColor(x, y, QColor(r, g, b, a))
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _read(data: bytes):
    img = QImage.fromData(data).convertToFormat(QImage.Format.Format_RGBA8888)
    return [[img.pixelColor(x, y).getRgb() for x in range(img.width())]
            for y in range(img.height())]


@pytest.fixture
def stone(tmp_path):
    """A grey stone with real variation, written to a file."""
    rows = [[(120, 118, 116, 255), (150, 148, 145, 255)],
            [(95, 93, 92, 255), (170, 168, 166, 255)]]
    p = tmp_path / "piedra_laja.png"
    p.write_bytes(_png(rows))
    return p


def test_tint_mode_keeps_lightness_variation(stone):
    """TINT greyscales and re-hues: the light pixel stays lighter."""
    out = colorize_image(stone.read_bytes(), (200, 40, 40), COLORIZE_TINT)
    px = _read(out)
    oscuro = sum(px[1][0][:3])
    claro = sum(px[1][1][:3])
    assert claro > oscuro, "the texture's variation was flattened"
    # And it really is reddish now.
    r, g, b = px[1][1][:3]
    assert r > g and r > b


def test_shift_moves_the_hue_without_flattening(stone):
    out = colorize_image(stone.read_bytes(), (40, 120, 200), COLORIZE_SHIFT)
    px = _read(out)
    assert sum(px[1][1][:3]) > sum(px[1][0][:3])
    r, g, b = px[1][1][:3]
    assert b > r


def test_alpha_survives_so_a_cutout_stays_a_cutout(tmp_path):
    rows = [[(120, 118, 116, 255), (150, 148, 145, 0)]]
    p = tmp_path / "reja.png"
    p.write_bytes(_png(rows))
    out = colorize_image(p.read_bytes(), (200, 40, 40), COLORIZE_TINT)
    px = _read(out)
    assert px[0][0][3] == 255 and px[0][1][3] == 0


def test_tinted_texture_records_the_base_and_the_recipe(stone):
    tex = {"path": str(stone), "sw": 1.0, "sh": 1.0, "rot": 0.0}
    out = tinted_texture(tex, (0.8, 0.2, 0.2), COLORIZE_TINT)
    assert out["base"] == str(stone)
    assert out["path"] != str(stone)
    assert out["tint"] == [0.8, 0.2, 0.2]
    assert out["tint_mode"] == COLORIZE_TINT
    assert out["sw"] == 1.0 and out["rot"] == 0.0    # the rest rides along


def test_retinting_starts_from_the_base_never_from_the_last_result(stone):
    """Sliding through colours must not tint a tint — that degrades."""
    once = tinted_texture({"path": str(stone)}, (0.8, 0.2, 0.2), COLORIZE_TINT)
    twice = tinted_texture(once, (0.8, 0.2, 0.2), COLORIZE_TINT)
    assert twice["path"] == once["path"], "a re-tint compounded on itself"
    assert twice["base"] == str(stone)


def test_removing_the_colour_restores_the_original_exactly(stone):
    tex = {"path": str(stone), "sw": 2.0}
    tinted = tinted_texture(tex, (0.1, 0.6, 0.3), COLORIZE_SHIFT)
    plain = untinted_texture(tinted)
    assert plain == {"path": str(stone), "sw": 2.0}


def test_untinting_an_untinted_entry_is_a_no_op(stone):
    tex = {"path": str(stone), "sw": 2.0}
    assert untinted_texture(tex) == tex


def test_an_unreadable_source_leaves_the_entry_alone():
    tex = {"path": "/no/existe.png", "sw": 1.0}
    assert tinted_texture(tex, (1.0, 0.0, 0.0)) == tex


def test_the_igz_carries_the_base_so_the_tint_stays_editable(stone, tmp_path):
    """Without the base embedded, a document opened elsewhere could only
    re-tint the tinted image and 'remove colour' would have nothing to
    restore."""
    from core.scene import Scene
    from formats import igz
    scene = Scene()
    f = scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    f.attrs["texture"] = tinted_texture(
        {"path": str(stone), "sw": 1.0, "sh": 1.0},
        (0.8, 0.2, 0.2), COLORIZE_TINT)
    horneada = f.attrs["texture"]["path"]
    doc = tmp_path / "prueba.igz"
    igz.save_scene(scene, doc)

    vuelta = Scene()
    igz.load_into(vuelta, doc)
    tex = vuelta.mesh.faces[0].attrs["texture"]
    assert tex.get("tint") == [0.8, 0.2, 0.2]
    assert tex.get("tint_mode") == COLORIZE_TINT
    assert tex.get("base"), "the untinted source did not survive the save"
    # Both images came back, and the tinted one is the same picture.
    assert _read(open(tex["path"], "rb").read()) == \
           _read(open(horneada, "rb").read())
    # And removing the colour lands on an image that really is the original.
    assert _read(open(untinted_texture(tex)["path"], "rb").read()) == \
           _read(stone.read_bytes())


def test_restamping_a_material_reaches_faces_inside_components():
    """The bug found while investigating this feature: 'edit the material
    once and restamp every face' walked scene.groups as a flat list."""
    from core.history import History, RestampMaterialCommand
    from core.materials import Material
    from core.scene import Scene

    scene = Scene()
    hondo = Mesh()
    dentro = hondo.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    hijo = Group(hondo, name="Silla")
    hijo.xform = QMatrix4x4()
    padre = Group(Mesh(), name="Mesa")
    padre.adopt([hijo])
    scene.groups.append(padre)
    suelta = scene.mesh.add_face([V(9, 0), V(11, 0), V(11, 2), V(9, 2)])
    for f in (dentro, suelta):
        f.attrs["mat"] = "Piedra laja"
        f.attrs["color"] = (0.5, 0.5, 0.5)
    scene.materials["Piedra laja"] = Material("Piedra laja",
                                              color=(0.5, 0.5, 0.5))
    History(scene).execute(RestampMaterialCommand(
        "Piedra laja", Material("Piedra laja", color=(0.9, 0.2, 0.1))))
    assert suelta.attrs["color"] == (0.9, 0.2, 0.1)
    assert dentro.attrs["color"] == (0.9, 0.2, 0.1), "nested face missed"
