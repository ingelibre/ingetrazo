# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Entity Info — the material swatches: a face's front/back and a group's
container paint, from the document's named materials."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication, QMenu

_app = QApplication.instance() or QApplication([])

from core.group import Group
from core.materials import Material
from core.mesh import Mesh


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win


def test_entity_info_paints_a_face_front_and_back_with_a_named_material():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.materials["Vermelho"] = Material("Vermelho",
                                               color=(1.0, 0.0, 0.0))
        face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                                    QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
        panel = win.tray.entity_info
        scene.select([face])
        panel.refresh()
        assert panel._front_btn.isVisibleTo(panel)
        assert panel._back_btn.isVisibleTo(panel)

        mat = scene.materials["Vermelho"]
        panel._apply_face_material([face], "front", mat)
        assert face.attrs.get("mat") == "Vermelho"
        assert tuple(face.attrs.get("color") or ()) == (1.0, 0.0, 0.0)

        panel._apply_face_material([face], "back", mat)
        assert face.attrs.get("back") == {"mat": "Vermelho",
                                          "color": (1.0, 0.0, 0.0)}

        vp.history.undo()          # the back paint
        vp.history.undo()          # the front paint
        assert "back" not in face.attrs
        assert "mat" not in face.attrs and "color" not in face.attrs
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_entity_info_back_can_mirror_the_front():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.materials["Verde"] = Material("Verde", color=(0.0, 1.0, 0.0))
        face = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                                    QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
        panel = win.tray.entity_info
        scene.select([face])
        panel.refresh()

        panel._apply_face_material([face], "front", scene.materials["Verde"])
        panel._apply_face_material([face], "back", None, same=True)
        assert face.attrs.get("back") is True

        vp.history.undo()          # the "same as front" back
        assert "back" not in face.attrs
        vp.history.undo()          # the front paint
        assert "mat" not in face.attrs
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_entity_info_paints_a_group_with_its_material():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.materials["Azul"] = Material("Azul", color=(0.0, 0.0, 1.0))
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        panel = win.tray.entity_info
        scene.select([g])
        panel.refresh()
        assert panel._mat_btn.isVisibleTo(panel)
        assert not panel._front_btn.isVisibleTo(panel)

        mat = scene.materials["Azul"]
        panel._apply_group_material(g, mat)
        assert g.material == {"mat": "Azul", "color": (0.0, 0.0, 1.0)}

        vp.history.undo()
        assert g.material is None
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_group_and_component_show_image_materials_and_allow_replacement(
        tmp_path, monkeypatch):
    from core.history import SetGroupMaterialCommand
    from tools.paint import PaintTool

    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor(210, 45, 70))
    path = tmp_path / "brick.png"
    assert image.save(str(path))
    texture = {"path": str(path), "sw": 1.0, "sh": 1.0}
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        mat = Material("Brick", texture=texture)
        scene.materials[mat.name] = mat
        group = Group(Mesh(), name="group")
        component = Group(Mesh(), name="component")
        component.xform = QMatrix4x4()
        component.component = True
        scene.groups.extend([group, component])
        panel = win.tray.entity_info
        monkeypatch.setattr(PaintTool, "current_texture", texture)
        monkeypatch.setattr(PaintTool, "current_opacity", None)
        monkeypatch.setattr(PaintTool, "current_material", mat)

        class CaptureMenu(QMenu):
            choice = None
            checked = {}
            icons = {}

            def exec(self, _pos):
                self.__class__.checked = {
                    a.text(): a.isChecked() for a in self.actions() if a.isCheckable()}
                self.__class__.icons = {
                    a.text(): a.icon() for a in self.actions() if a.isCheckable()}
                if self.choice:
                    next(a for a in self.actions() if a.text() == self.choice).trigger()

        monkeypatch.setattr("views.tray.QMenu", CaptureMenu)
        for obj in (group, component):
            vp.history.execute(SetGroupMaterialCommand(
                obj, PaintTool._current_as_material()))
            scene.select([obj])
            panel.refresh()
            color = panel._mat_btn.icon().pixmap(16, 16).toImage().pixelColor(8, 8)
            assert color == QColor(210, 45, 70)
            assert panel._mat_btn.toolTip() == "Brick"
            panel._on_pick_group_material()
            assert CaptureMenu.checked["Brick"]
            assert not CaptureMenu.checked["Default material"]
            icon = CaptureMenu.icons["Brick"].pixmap(16, 16).toImage()
            assert icon.pixelColor(8, 8) == QColor(210, 45, 70)

            obj.material = {"texture": texture}
            panel.refresh()
            assert panel._mat_btn.toolTip() == "brick"
            panel._on_pick_group_material()
            assert not CaptureMenu.checked["Default material"]
            CaptureMenu.choice = "Brick"
            panel._on_pick_group_material()
            assert obj.material == mat.face_attrs()
            assert vp.history.undo()
            assert obj.material == {"texture": texture}
            assert vp.history.redo()
            assert obj.material == mat.face_attrs()
            CaptureMenu.choice = "Default material"
            panel._on_pick_group_material()
            assert obj.material is None
            panel._on_pick_group_material()
            assert CaptureMenu.checked["Default material"]
            CaptureMenu.choice = None

        face = scene.mesh.add_face([
            QVector3D(0, 0, 0), QVector3D(1, 0, 0),
            QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
        face.attrs.update(mat.face_attrs())
        scene.select([face])
        panel.refresh()
        color = panel._front_btn.icon().pixmap(16, 16).toImage().pixelColor(8, 8)
        assert color == QColor(210, 45, 70)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_material_menu_offers_unnamed_textures_from_model(tmp_path, monkeypatch):
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor(210, 45, 70))
    path = tmp_path / "brick.png"
    assert image.save(str(path))
    texture = {"path": str(path), "sw": 2.0, "sh": 3.0, "rot": 15.0}
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        source = Group(Mesh(), name="source")
        source.material = {"texture": texture, "opacity": 0.6}
        target = Group(Mesh(), name="target")
        target.xform = QMatrix4x4()
        target.component = True
        scene.groups.extend([source, target])
        face = scene.mesh.add_face([
            QVector3D(0, 0, 0), QVector3D(1, 0, 0),
            QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
        face.attrs["back"] = {"texture": {**texture, "uvw": [1, 2, 3]},
                              "opacity": 0.6}
        panel = win.tray.entity_info

        class ChooseTexture(QMenu):
            choice = None
            checked = {}

            def exec(self, _pos):
                actions = [a for a in self.actions() if a.isCheckable()]
                self.__class__.checked = {a.text(): a.isChecked() for a in actions}
                if self.choice:
                    next(a for a in actions if a.text() == self.choice).trigger()

        monkeypatch.setattr("views.tray.QMenu", ChooseTexture)
        scene.select([source])
        panel.refresh()
        panel._on_pick_group_material()
        assert ChooseTexture.checked["brick"]

        scene.select([target])
        panel.refresh()
        ChooseTexture.choice = "brick"
        panel._on_pick_group_material()
        assert target.material == source.material
        assert vp.history.undo()
        assert target.material is None
        assert vp.history.redo()
        assert target.material == source.material

        scene.select([face])
        panel.refresh()
        panel._on_pick_front()
        assert face.attrs["texture"] == texture
        assert face.attrs["opacity"] == 0.6
        assert "mat" not in face.attrs
        assert vp.history.undo()
        assert "texture" not in face.attrs
        assert face.attrs["back"]["texture"]["uvw"] == [1, 2, 3]
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_material_menu_applies_unregistered_back_texture_to_multiple_faces(
        tmp_path, monkeypatch):
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor(10, 80, 140))
    path = tmp_path / "tile.png"
    assert image.save(str(path))
    texture = {"path": str(path), "sw": 2.0, "sh": 1.0, "rot": 30.0}
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        mesh = Mesh()
        source = mesh.add_face([
            QVector3D(0, 0, 0), QVector3D(1, 0, 0),
            QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
        source.attrs["back"] = {
            "mat": "Imported tile", "texture": {**texture, "uvw": [1, 2, 3]},
            "opacity": 0.7}
        parent = Group(Mesh(), name="parent")
        parent.adopt([Group(mesh, name="nested")])
        scene.groups.append(parent)
        faces = [scene.mesh.add_face([
            QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0),
            QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)]) for x in (2, 4)]
        scene.select(faces)
        panel = win.tray.entity_info
        panel.refresh()

        class ChooseTexture(QMenu):
            def exec(self, _pos):
                next(a for a in self.actions() if a.text() == "Imported tile").trigger()

        monkeypatch.setattr("views.tray.QMenu", ChooseTexture)
        panel._on_pick_back()
        expected = {"mat": "Imported tile", "texture": texture, "opacity": 0.7}
        assert all(face.attrs["back"] == expected for face in faces)
        assert "Imported tile" not in scene.materials
        assert vp.history.undo()
        assert all("back" not in face.attrs for face in faces)
        assert vp.history.redo()
        assert all(face.attrs["back"] == expected for face in faces)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_multiple_faces_show_each_side_and_apply_materials_with_undo(monkeypatch):
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        red = Material("Red", color=(1.0, 0.0, 0.0))
        blue = Material("Blue", color=(0.0, 0.0, 1.0))
        green = Material("Green", color=(0.0, 1.0, 0.0))
        scene.materials.update({m.name: m for m in (red, blue, green)})
        faces = [scene.mesh.add_face([
            QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0),
            QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)]) for x in (0, 2)]
        for face, back in zip(faces, (red, blue)):
            face.attrs.update(green.face_attrs())
            face.attrs["back"] = back.face_attrs()
        scene.select(faces)
        panel = win.tray.entity_info
        panel.refresh()
        assert panel._front_btn.isVisibleTo(panel)
        assert panel._back_btn.isVisibleTo(panel)
        assert panel._front_btn.text() == ""
        assert panel._front_btn.toolTip() == "Green"
        assert panel._back_btn.text() == "?"
        assert panel._back_btn.icon().isNull()

        class MenuChooseBlue(QMenu):
            def exec(self, _pos):
                next(a for a in self.actions() if a.text() == "Blue").trigger()

        monkeypatch.setattr("views.tray.QMenu", MenuChooseBlue)
        panel._on_pick_back()
        assert all(face.attrs["back"] == blue.face_attrs() for face in faces)
        assert panel._back_btn.text() == ""
        assert panel._back_btn.toolTip() == "Blue"
        win._on_undo()
        assert [face.attrs["back"] for face in faces] == [
            red.face_attrs(), blue.face_attrs()]
        assert panel._back_btn.text() == "?"
        win._on_redo()
        assert all(face.attrs["back"] == blue.face_attrs() for face in faces)

        faces[0].attrs.update(red.face_attrs())
        panel.refresh()
        assert panel._front_btn.text() == "?"
        assert panel._back_btn.text() == ""
        panel._on_pick_front()
        assert all(face.attrs["mat"] == "Blue" for face in faces)
        win._on_undo()
        assert [face.attrs["mat"] for face in faces] == ["Red", "Green"]
        assert all(face.attrs["back"] == blue.face_attrs() for face in faces)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_multiple_faces_distinguish_material_identity_and_mirrored_backs():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        faces = [scene.mesh.add_face([
            QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0),
            QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)]) for x in (0, 2)]
        faces[0].attrs.update({"mat": "A", "color": [1, 0, 0], "back": True})
        faces[1].attrs.update({"mat": "B", "color": [1, 0, 0], "back": True})
        scene.select(faces)
        panel = win.tray.entity_info
        panel.refresh()
        assert panel._front_btn.text() == "?"
        assert panel._back_btn.text() == "?"

        faces[1].attrs["mat"] = "A"
        faces[1].attrs["back"] = {"mat": "A", "color": [1, 0, 0]}
        panel.refresh()
        assert panel._front_btn.text() == ""
        assert panel._back_btn.text() == ""
        panel._apply_face_material(faces, "back", None, same=True)
        assert all(face.attrs["back"] is True for face in faces)
        vp.history.undo()
        assert faces[0].attrs["back"] is True
        assert isinstance(faces[1].attrs["back"], dict)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_multiple_faces_can_reset_and_mirror_back_from_menu(monkeypatch):
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        faces = [scene.mesh.add_face([
            QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0),
            QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)]) for x in (0, 2)]
        faces[0].attrs["back"] = {"color": (1.0, 0.0, 0.0)}
        faces[1].attrs["back"] = True
        scene.select(faces)
        panel = win.tray.entity_info
        panel.refresh()
        assert panel._back_btn.text() == "?"

        class MenuChoose(QMenu):
            choice = "Default material"

            def exec(self, _pos):
                next(a for a in self.actions() if a.text() == self.choice).trigger()

        monkeypatch.setattr("views.tray.QMenu", MenuChoose)
        panel._on_pick_back()
        assert all("back" not in face.attrs for face in faces)
        assert panel._back_btn.text() == ""
        win._on_undo()
        assert faces[0].attrs["back"] == {"color": (1.0, 0.0, 0.0)}
        assert faces[1].attrs["back"] is True
        MenuChoose.choice = "Same as front"
        panel._on_pick_back()
        assert all(face.attrs["back"] is True for face in faces)
        win._on_undo()
        assert faces[0].attrs["back"] == {"color": (1.0, 0.0, 0.0)}
        assert faces[1].attrs["back"] is True
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_multiple_faces_compare_unnamed_textures_independent_of_position():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        faces = [scene.mesh.add_face([
            QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0),
            QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)]) for x in (0, 2)]
        faces[0].attrs["texture"] = {"path": "brick.png", "uvw": [1, 2]}
        faces[1].attrs["texture"] = {"path": "brick.png", "uvw": [3, 4]}
        scene.select(faces)
        panel = win.tray.entity_info
        panel.refresh()
        assert panel._front_btn.text() == ""
        faces[1].attrs["texture"]["path"] = "wood.png"
        panel.refresh()
        assert panel._front_btn.text() == "?"
        scene.select([faces[0]])
        panel.refresh()
        assert panel._front_btn.text() == ""
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_translucent_front_is_also_the_effective_back_material():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        faces = [scene.mesh.add_face([
            QVector3D(x, 0, 0), QVector3D(x + 1, 0, 0),
            QVector3D(x + 1, 1, 0), QVector3D(x, 1, 0)]) for x in (0, 2)]
        for face in faces:
            face.attrs.update({"mat": "Glass", "color": (0.2, 0.3, 0.4),
                               "opacity": 0.5})
        faces[1].attrs["back"] = {"mat": "Glass", "color": (0.2, 0.3, 0.4),
                                  "opacity": 0.5}
        scene.select(faces)
        panel = win.tray.entity_info
        panel.refresh()
        assert panel._back_btn.text() == ""
        assert panel._back_btn.toolTip() == "Glass"
        faces[1].attrs["back"]["mat"] = "Other glass"
        panel.refresh()
        assert panel._back_btn.text() == "?"
    finally:
        win._saved_version = vp.scene.version
        win.close()
