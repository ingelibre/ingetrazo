# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Locked objects get a red inspection frame without becoming editable (#1209)."""
import numpy as np
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D as V
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.scene import Scene
from tools.base import ToolContext
from tools.select import SelectTool, delete_selection_or_hover
from views.viewport import Viewport
from tests.test_eye_lock_on_selection import _setup, _press, _close
from tests.test_locked_group_not_pickable import _vp, _boxed_group
from views.outliner import COL_NAME


def _click(vp, point, modifiers=Qt.NoModifier):
    SelectTool().on_click(ToolContext(
        viewport=vp, world=V(), screen=QPointF(*point), modifiers=modifiers, snap=None))


def test_real_click_inspects_locked_group_without_making_it_editable():
    vp = _vp()
    group = _boxed_group(vp)
    group.locked = True
    vp.scene.version += 1
    point = vp._world_to_pixel(V(2, 2, 0))
    version = vp.scene.content_version
    _click(vp, point)
    assert vp.scene.locked_selection == {group}
    assert not vp.scene.selection
    assert vp.scene.content_version == version
    assert vp.pick_group(*point) is None
    assert not delete_selection_or_hover(vp)
    assert group in vp.scene.groups
    vp.begin_group_edit(group)
    assert vp.scene.edit_group is None
    _click(vp, point, Qt.ShiftModifier)
    assert not vp.scene.locked_selection
    _click(vp, point)
    _click(vp, (0, 0))
    assert not vp.scene.locked_selection


@pytest.mark.parametrize('hit', ['face', 'rim', 'wire'])
@pytest.mark.parametrize('lock_from_browser', [False, True])
def test_create_group_lock_then_select_with_mouse(hit, lock_from_browser):
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    try:
        vp = win.viewport
        scene = vp.scene
        scene.clear()
        points = [V(1, 1, 0), V(3, 1, 0), V(3, 3, 0), V(1, 3, 0)]
        if hit == 'wire':
            for a, b in zip(points, points[1:] + points[:1]):
                scene.mesh.add_edge(a, b)
        else:
            scene.mesh.add_face(points)
        scene.select(scene.edges + scene.faces)
        win._on_make_group()
        group, = scene.groups
        vp.resize(1000, 600)
        vp.camera.set_aspect(1000, 600)
        vp.camera.set_view('top')
        vp.camera.target = V(2, 2, 0)
        vp.camera.distance = 10
        vp.set_active_tool(SelectTool())
        point = vp._world_to_pixel(V(2, 2 if hit == 'face' else 1, 0))
        if hit == 'rim':
            point = (point[0], point[1] + 2)  # Just outside the face, near its edge.
        assert vp.pick_group(*point) is group
        if lock_from_browser:
            panel = win.project_browser.outliner
            panel.refresh()
            panel.toggle_locked([group])
        else:
            win._lock_groups([group])
        assert group.locked
        scene.clear_selection()
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPointF(*point).toPoint())
        assert scene.locked_selection == {group}
        assert not scene.selection
        assert vp.pick_group(*point) is None
        vp.set_hover(group)  # A hover acquired before locking may still be cached.
        assert not delete_selection_or_hover(vp)
        assert group in scene.groups
        QTest.mouseClick(vp, Qt.LeftButton, Qt.ShiftModifier, QPointF(*point).toPoint())
        assert not scene.locked_selection
    finally:
        _close(win)


@pytest.mark.parametrize('lock_from_browser', [False, True])
def test_cube_click_automatically_selects_its_browser_row(lock_from_browser):
    """The full native path, without injecting a selection or refreshing the tree."""
    if QApplication.platformName() == 'offscreen':
        pytest.skip('requires a native OpenGL widget for automatic paint notifications')
    from tests.test_pick_index_lazy import _cube
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    try:
        win.setAttribute(Qt.WA_DontShowOnScreen)
        win.resize(1280, 820)
        win.show()
        win.project_browser.show()
        win.project_browser.raise_()
        QApplication.processEvents()
        vp = win.viewport
        if not vp.isValid():
            pytest.skip('no native OpenGL context')
        scene = vp.scene
        scene.clear()
        scene.show_axes = False
        scene.mesh = _cube()
        win._on_select_all()
        win._on_make_group()
        group, = scene.groups
        assert len(group.mesh.faces) == 6
        win._activate_tool('select')
        vp.camera.set_view('iso')
        vp.camera.fit_to(V(-0.5, -0.5, -0.5), V(1.5, 1.5, 1.5))
        vp.repaint()
        QTest.qWait(500)
        if lock_from_browser:
            win.project_browser.outliner.toggle_locked([group])
        else:
            win._lock_groups([group])
        vp.repaint()
        QTest.qWait(500)
        point = vp._world_to_pixel(V(0.5, 0.5, 0.5))
        QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPointF(*point).toPoint())
        vp.repaint()
        QTest.qWait(500)
        assert scene.locked_selection == {group}
        assert not scene.selection
        assert win.project_browser.outliner._selected_groups() == [group]
        image = vp.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
        pixels = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), -1, 4)
        assert ((pixels[:, :, 0] > 180) & (pixels[:, :, 1] < 80)
                & (pixels[:, :, 2] < 80)).sum() > 100
    finally:
        _close(win)


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('lazy', [False, True])
def test_transformed_locked_wire_component_can_be_selected(nested, lazy):
    vp = _vp()
    vp._PICK_LAZY_MIN_FACES = 0 if lazy else 10 ** 12
    child = Group(name='Wire component')
    child.mesh.add_edge(V(0, 0, 0), V(2, 0, 0))
    group = child
    if nested:
        group = Group(name='Container')
        group.children.append(child)
    group.xform = QMatrix4x4()
    group.xform.translate(2, 2, 0)
    group.xform.rotate(35, V(0, 0, 1))
    group.component = True
    vp.scene.groups.append(group)
    vp.scene.version += 1
    point = vp._world_to_pixel(group.xform.map(V(1, 0, 0)))
    assert vp.pick_group(*point) is group  # Seed the unlocked pick cache.
    group.locked = True
    vp.scene.version += 1
    _click(vp, (point[0], point[1] + 2))
    assert vp.scene.locked_selection == {group}
    assert not vp.scene.selection


@pytest.mark.parametrize('crossing', [False, True])
def test_box_inspects_locked_group_without_unlocking_it(crossing):
    vp = _vp()
    group = _boxed_group(vp)
    group.locked = True
    vp.scene.version += 1
    corners = [vp._world_to_pixel(p) for p in (V(0, 0, 0), V(4, 4, 0))]
    x0, x1 = sorted(p[0] for p in corners)
    y0, y1 = sorted(p[1] for p in corners)
    SelectTool().on_box_select(vp, (x0, y0, x1, y1), crossing)
    assert vp.scene.locked_selection == {group}
    assert not vp.scene.selection


def test_locked_wire_behind_a_face_or_on_a_locked_layer_is_not_picked():
    from core.layers import Layer

    vp = _vp()
    group = Group(name='Wire')
    group.mesh.add_edge(V(1, 2, 0), V(3, 2, 0))
    group.locked = True
    vp.scene.groups.append(group)
    vp.scene.version += 1
    point = vp._world_to_pixel(V(2, 2, 0))
    assert vp.pick_locked_group(*point) is group
    vp.scene.mesh.add_face([V(0, 0, 1), V(4, 0, 1), V(4, 4, 1), V(0, 4, 1)])
    vp.scene.version += 1
    assert vp.pick_locked_group(*point) is None
    vp.scene.mesh.clear()
    group.layer = 'Locked layer'
    vp.scene.layers.append(Layer('Locked layer', locked=True))
    vp.scene.version += 1
    assert vp.pick_locked_group(*point) is None


@pytest.mark.parametrize('mode,expected', [
    ('add', True), ('toggle', False), ('remove', False), ('replace', True)])
def test_inspection_obeys_selection_modifiers(mode, expected):
    scene = Scene()
    locked = Group(name='Locked')
    locked.locked = True
    normal = Group(name='Normal')
    scene.select([normal, locked])
    assert scene.selection == {normal}
    assert scene.locked_selection == {locked}
    scene.select([locked], mode=mode)
    assert (locked in scene.locked_selection) == expected
    assert locked not in scene.selection
    assert (normal in scene.selection) == (mode != 'replace')
    scene.clear_selection()
    assert not scene.locked_selection and not scene.selection


def test_browser_selects_and_unlocks_inspected_group():
    win, scene, panel, (a, b, c) = _setup()
    try:
        a.locked = True
        scene.version += 1
        panel.refresh()
        row = panel.tree.topLevelItem(0).child(0)
        _press(panel, row, COL_NAME)
        assert scene.locked_selection == {a}
        assert a not in scene.selection
        panel.refresh()
        assert row.isSelected()
        panel.toggle_locked([a])
        assert not a.locked and scene.selection == {a}
        assert not scene.locked_selection
        panel.toggle_locked([a])
        assert scene.locked_selection == {a}
        assert a not in scene.selection
        panel.tree.clearSelection()
        assert not scene.locked_selection
        _press(panel, row, COL_NAME)
        assert scene.locked_selection == {a}
        scene.select([b])
        panel.refresh()
        assert not scene.locked_selection
        assert not row.isSelected()
    finally:
        _close(win)


def test_canvas_inspection_is_synchronized_to_the_browser_and_unlocks():
    win, scene, panel, (a, b, c) = _setup()
    try:
        a.locked = True
        scene.select([a])
        panel.refresh()
        row = panel.tree.topLevelItem(0).child(0)
        assert row.isSelected()
        panel.toggle_locked([a])
        assert scene.selection == {a}
        assert not scene.locked_selection
    finally:
        _close(win)


def test_select_all_keeps_locked_objects_out_of_editing_tools():
    win, scene, panel, (a, b, c) = _setup()
    try:
        a.locked = True
        win._on_select_all()
        assert scene.locked_selection == {a}
        assert scene.selection == {b, c}
        win._on_select_none()
        assert not scene.locked_selection
    finally:
        _close(win)
