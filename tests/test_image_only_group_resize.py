# SPDX-License-Identifier: GPL-3.0-or-later
"""An image wrapped in a group or component remains resizable by Tape."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.group import copy_group
from core.history import History, MakeImageGroupCommand
from core.image_plane import ImagePlane
from core.resize import ResizeCommand, resize_anchor
from core.scene import Scene
from core.snap import SnapResult
from tools.base import ToolContext
from tools.select import SelectTool
from tools.tape import TapeMeasureTool
from views.main_window import MainWindow


def v(x, y, z=0):
    return QVector3D(float(x), float(y), float(z))


def close(a, b):
    return (a - b).length() < 1e-5


def photo_group(vp, *, component=False):
    vp.scene.groups.clear()  # the main window starts with a scale figure
    vp.scene.version += 1
    image = ImagePlane("plan.png", v(2, 3), v(4, 0), v(0, 3))
    vp.scene.image_planes.append(image)
    vp.history.execute(MakeImageGroupCommand(
        [image], component=component, name="Plan"))
    return vp.scene.groups[0], image


def test_photo_only_group_opens_with_a_box_and_tape_scales_its_image(monkeypatch):
    win = MainWindow()
    try:
        vp = win.viewport
        group, image = photo_group(vp)
        monkeypatch.setattr(vp, "_pixel_to_ray",
                            lambda *_args: (v(4, 4, 10), v(0, 0, -1)))
        assert vp.pick_group(0, 0) is group
        SelectTool().on_double_click(ToolContext(
            viewport=vp, world=v(4, 4), screen=QPointF(0, 0),
            modifiers=Qt.NoModifier, snap=None))
        assert vp.scene.edit_group is group
        assert vp._edit_group_box_corners() is not None
        assert close(resize_anchor(vp.scene), v(0, 0))

        monkeypatch.setattr(TapeMeasureTool, "_confirm_resize",
                            staticmethod(lambda *_args: True))
        tape = TapeMeasureTool()
        tape.on_activate(vp)
        for point in (v(2, 3), v(6, 3)):
            tape.on_click(ToolContext(
                viewport=vp, world=point, screen=QPointF(0, 0),
                modifiers=Qt.NoModifier,
                snap=SnapResult(point, "endpoint", (0, 0, 0))))
        assert tape.on_value(vp, 8.0)
        assert close(group.images[0].origin, v(4, 6))
        assert close(group.images[0].u, v(8, 0))
        assert close(group.images[0].v, v(0, 6))
        vp.end_one_group_edit()
        assert vp.scene.edit_group is None
        assert group.images[0] is image
        assert close(image.u, v(8, 0))
        assert vp.history.undo()
        assert close(image.u, v(4, 0))
        assert vp.history.redo()
        assert close(image.u, v(8, 0))
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_photo_component_resize_reaches_other_copies_and_undoes():
    win = MainWindow()
    try:
        vp = win.viewport
        component, image = photo_group(vp, component=True)
        sibling = copy_group(component, v(10, 0))
        vp.scene.groups.append(sibling)
        assert sibling.images[0] is image
        vp.begin_group_edit(sibling)
        assert vp.scene.edit_group is sibling
        assert close(sibling.images[0].origin, v(12, 3))
        assert close(resize_anchor(vp.scene), v(10, 0))

        vp.history.execute(ResizeCommand(vp.scene, 2.0))
        vp.end_one_group_edit()
        assert sibling.images[0] is image
        assert close(image.origin, v(4, 6))
        assert close(image.u, v(8, 0))
        assert vp.history.undo()
        assert close(image.origin, v(2, 3))
        assert close(image.u, v(4, 0))
        assert vp.history.redo()
        assert close(image.origin, v(4, 6))
        assert close(image.u, v(8, 0))
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_open_and_close_photo_component_without_edit_keeps_definition():
    scene = Scene()
    image = ImagePlane("plan.png", v(2, 3), v(4, 0), v(0, 3))
    from core.group import Group
    from PySide6.QtGui import QMatrix4x4
    group = Group(name="Plan")
    group.images = [image]
    group.xform = QMatrix4x4()
    group.xform.translate(10, 0, 0)
    scene.groups.append(group)
    scene.begin_group_edit(group)
    assert group.images[0] is not image
    assert close(group.images[0].origin, v(12, 3))
    scene.end_group_edit()
    assert group.images[0] is image
    assert close(image.origin, v(2, 3))
    assert close(image.u, v(4, 0))


def test_headless_edit_resizes_the_shared_image_definition():
    from core.group import Group
    from PySide6.QtGui import QMatrix4x4

    scene = Scene()
    image = ImagePlane("plan.png", v(2, 3), v(4, 0), v(0, 3))
    group = Group(name="Plan")
    group.images = [image]
    group.xform = QMatrix4x4()
    group.xform.translate(10, 0, 0)
    sibling = copy_group(group, v(-10, 0))
    scene.groups.extend([group, sibling])
    scene.begin_group_edit(group)
    assert close(resize_anchor(scene), v(10, 0))
    History(scene).execute(ResizeCommand(scene, 2.0))
    scene.end_group_edit()
    assert group.images[0] is sibling.images[0] is image
    assert close(image.origin, v(4, 6))
    assert close(image.u, v(8, 0))
