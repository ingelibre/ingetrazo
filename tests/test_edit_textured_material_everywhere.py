# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Editing a textured material changes it wherever it is worn.

A YouTube review of 0.6.1 (#1308): «when you edit an already applied
material, say change the colour, it does not affect the applied materials
in the model, almost as if it creates another material definition». The
Materials panel's Apply changed the texture to paint with next and the
faces SELECTED: with nothing selected the model kept the old look, with
one face selected the same name came out in two colours. Here two faces
and a component are painted with the Paint tool's clicks, the material is
picked again from «In model», given a colour and applied: everything that
wears it changes, each face keeps its own placement, one undo puts it all
back."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QMatrix4x4, QVector3D as V
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

BLUE = QColor(40, 120, 220)


@pytest.fixture
def scene(tmp_path, monkeypatch):
    import views.tray as tray
    from core.group import Group
    from core.mesh import Mesh
    from tools.paint import PaintTool
    from views.main_window import MainWindow
    saved = (PaintTool.current_texture, PaintTool.current_material,
             PaintTool.current_is_default, PaintTool.current_color,
             PaintTool.current_opacity, list(PaintTool.recent))
    monkeypatch.setattr(tray, "save_recent_materials", lambda *_a: None)
    win = MainWindow()
    win.resize(1200, 900)
    win.show()
    vp, sc = win.viewport, win.viewport.scene
    f1 = sc.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    f2 = sc.mesh.add_face([V(4, 0, 0), V(6, 0, 0), V(6, 2, 0), V(4, 2, 0)])
    # A component beside them: a click paints it whole, on the container.
    m = Mesh()
    m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    comp = Group(m, name="Tile")
    comp.xform = QMatrix4x4()
    comp.xform.translate(8, 0, 0)
    sc.groups.append(comp)
    sc.version += 1
    image = tmp_path / "brick.png"
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(180, 80, 60))
    img.save(str(image))
    panel = win.findChild(tray.MaterialsPanel)
    vp.camera.set_view("top")
    vp.camera.fit_to(V(-1, -1, 0), V(11, 3, 0.1))
    QApplication.processEvents()
    panel._apply_texture(str(image), 1.0, name="Brick")

    def click(p):
        w, h = vp.width(), vp.height()
        vp.camera.set_aspect(w, h)
        c = (vp.camera.projection_matrix() * vp.camera.view_matrix()).map(p)
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier,
                         QPoint(round((c.x() + 1) / 2 * w),
                                round((1 - c.y()) / 2 * h)))
        QApplication.processEvents()

    for p in (V(1, 1, 0), V(5, 1, 0), V(9, 1, 0)):
        click(p)
    monkeypatch.setattr(tray, "get_color", lambda *a, **k: BLUE)
    yield win, panel, sc, (f1, f2, comp)
    (PaintTool.current_texture, PaintTool.current_material,
     PaintTool.current_is_default, PaintTool.current_color,
     PaintTool.current_opacity, PaintTool.recent) = saved
    win._saved_version = sc.version
    for doc in list(win._documents):
        doc.saved_content = doc.viewport.scene.content_version
    win.close()


def _tex(worn):
    """The texture a face wears, or a component painted whole."""
    attrs = getattr(worn, "attrs", None)
    return ((attrs if attrs is not None else worn.material or {})
            .get("texture") or {})


def _tint(worn):
    t = _tex(worn).get("tint")
    return None if t is None else tuple(round(c, 3) for c in t)


BLUE_F = tuple(round(c, 3) for c in (BLUE.redF(), BLUE.greenF(), BLUE.blueF()))


@pytest.mark.parametrize("selected", ["none", "one"])
def test_a_colour_given_to_a_textured_material_reaches_every_face(
        scene, selected):
    win, panel, sc, faces = scene
    f1, f2, comp = faces
    assert f1.attrs.get("mat") == f2.attrs.get("mat") == "Brick"
    assert comp.material.get("mat") == "Brick"     # painted whole
    assert all(_tint(f) is None for f in faces)
    sc.selection.clear()
    if selected == "one":
        sc.select([faces[0]])
    panel._on_pick_tint()
    panel._on_apply_texture_edit()
    assert [_tint(f) for f in faces] == [BLUE_F] * 3
    reg = sc.materials["Brick"].texture
    assert tuple(round(c, 3) for c in reg["tint"]) == BLUE_F
    # One step back: the model as it was, the registry too.
    win.viewport.history.undo()
    assert [_tint(f) for f in faces] == [None] * 3
    assert not sc.materials["Brick"].texture.get("tint")


def test_each_face_keeps_its_own_placement_and_size(scene):
    win, panel, sc, (f1, f2, _comp) = scene
    # A texture placed by hand on one face, another tile size on the next.
    f1.attrs["texture"] = {**f1.attrs["texture"], "uvw": [1, 2, 3, 4]}
    f2.attrs["texture"] = {**f2.attrs["texture"], "sw": 0.25, "sh": 0.5}
    sc.selection.clear()
    panel._on_pick_tint()
    panel._on_apply_texture_edit()
    assert f1.attrs["texture"]["uvw"] == [1, 2, 3, 4]
    assert (f2.attrs["texture"]["sw"], f2.attrs["texture"]["sh"]) == (0.25, 0.5)
    assert _tint(f1) == _tint(f2) == BLUE_F


def test_a_size_changed_in_the_panel_reaches_every_face(scene):
    win, panel, sc, faces = scene
    sc.selection.clear()
    panel._sw_box.setValue(2.5)
    panel._on_apply_texture_edit()
    assert [_tex(f)["sw"] for f in faces] == [2.5] * 3
    assert sc.materials["Brick"].texture["sw"] == 2.5


def test_picking_a_tinted_swatch_again_and_resizing_keeps_its_colour(scene):
    win, panel, sc, faces = scene
    sc.selection.clear()
    panel._on_pick_tint()
    panel._on_apply_texture_edit()
    # Picked again from «In model», as its swatch does: the image it shows.
    reg = sc.materials["Brick"].texture
    panel._apply_texture(reg["path"], reg.get("sw", 1.0), name="Brick")
    panel._sw_box.setValue(3.0)
    panel._on_apply_texture_edit()
    assert [_tint(f) for f in faces] == [BLUE_F] * 3
    assert [_tex(f)["sw"] for f in faces] == [3.0] * 3
