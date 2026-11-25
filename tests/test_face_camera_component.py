# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group, copy_group
from core.history import GroupToComponentCommand
from core.scene import Scene
from formats.igz import load_into, save_scene
from views.viewport import Viewport


@pytest.mark.parametrize("perspective", [False, True])
def test_tilted_component_keeps_its_axis_and_shares_the_draw_and_pick_pose(
        perspective, tmp_path):
    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    vp.resize(1000, 760)
    scene = vp.scene
    g = Group()
    g.mesh.add_face([V(1, 0, 0), V(3, 0, 0), V(3, 0, 2), V(1, 0, 2)])
    g.mesh.add_face([V(1, 0, 2), V(3, 0, 2), V(3, 1, 2), V(1, 1, 2)])
    g.xform = QMatrix4x4()
    g.xform.translate(1, 2, 0)
    g.xform.rotate(25, 0, 1, 0)
    scene.groups.append(g)
    vp.history.execute(GroupToComponentCommand(g, "Tilted solid", face_camera=True))
    original = QMatrix4x4(g.xform)
    vp.camera.target = original.map(V())
    vp.camera.distance = 12
    vp.camera.pitch = 0.20
    vp.camera.perspective = perspective
    poses = []
    for yaw in (0.15, 1.5, 3.0):
        vp.camera.yaw = yaw
        placed, = vp._placements()
        matrix = placed.xform
        pivot = matrix.map(V())
        blue = matrix.mapVector(V(0, 0, 1)).normalized()
        assert (pivot - original.map(V())).length() < 1e-5
        assert (blue - original.mapVector(V(0, 0, 1))).length() < 1e-5
        front = matrix.mapVector(V(0, -1, 0)).normalized()
        camera = vp._faceme_dir(pivot)
        camera -= blue * V.dotProduct(blue, camera)
        assert V.dotProduct(camera.normalized(), front) > 0.9999
        assert (matrix.map(V(1, 1, 2)) - matrix.map(V(1, 0, 2))).length() == pytest.approx(1.0)
        pos = vp._world_to_pixel(matrix.map(V(2, 0, 1)))
        assert vp.pick_group(*pos) is g
        poses.append(tuple(matrix.data()))
        assert g.xform == original
    assert len(set(poses)) == 3
    assert copy_group(g).face_camera

    saved = tmp_path / "facing.igz"
    save_scene(scene, saved)
    reopened = Scene()
    load_into(reopened, saved)
    assert reopened.groups[0].face_camera and reopened.groups[0].xform == original
    assert vp.history.undo() and not g.face_camera


def test_nested_geometry_inherits_the_camera_turn():
    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    parent, child = Group(), Group()
    child.xform = QMatrix4x4()
    child.xform.translate(2, 0, 1)
    parent.adopt([child])
    parent.face_camera = True
    vp.scene.groups.append(parent)
    vp.scene.version += 1
    vp.camera.yaw = 2.1
    outer, inner = vp._placements()
    assert inner.owner is parent
    assert (inner.xform.map(V()) - outer.xform.map(V(2, 0, 1))).length() < 1e-5


def test_make_component_dialog_enables_camera_facing():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QCheckBox
    from views.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow(defer_extensions=True)
    try:
        scene = win.viewport.scene
        face = scene.mesh.add_face([V(), V(2, 0, 0), V(1, 0, 2)])
        scene.select([face])
        flags = []

        def accept():
            dialog = app.activeModalWidget()
            checkbox = dialog.findChild(QCheckBox)
            flags.append(checkbox.isChecked())
            checkbox.setChecked(True)
            dialog.accept()

        QTimer.singleShot(0, accept)
        win._on_make_component()
        assert flags == [False]
        assert any(g.is_component() and g.face_camera for g in scene.groups)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_flat_component_box_follows_displayed_pose_as_camera_orbits():
    from core.group import oriented_box_corners

    app = QApplication.instance() or QApplication([])
    vp = Viewport(None)
    component = Group()
    points = [V(0, 0, 0), V(2, 0, 0), V(2, 0, 3), V(0, 0, 3)]
    component.mesh.add_face(points)
    component.xform = QMatrix4x4()
    component.xform.translate(3, 2, 0)
    component.xform.rotate(30, 0, 1, 0)
    component.face_camera = True
    vp.scene.groups.append(component)
    vp.scene.version += 1

    for yaw in (0.3, 1.6, 2.8):
        vp.camera.yaw = yaw
        displayed, = vp._placements()
        box = oriented_box_corners(*vp._group_obb(component))
        expected = [displayed.xform.map(point) for point in points]
        assert all(min((corner - point).length() for point in expected) < 1e-5
                   for corner in box)
        assert all(min((corner - point).length() for corner in box) < 1e-5
                   for point in expected)
