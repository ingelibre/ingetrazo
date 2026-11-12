from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QMouseEvent, QVector3D
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.group_scale import group_scale, scale_command
from core.history import History
from core.scene import Scene
from core.snap import SnapResult
from tests.test_group_axes import _slab
from tools.base import ToolContext
from views.main_window import MainWindow
from views.viewport import Viewport


@pytest.fixture
def manager():
    window = MainWindow()
    viewport = window.viewport
    viewport.resize(400, 400)
    viewport.camera.target = QVector3D(1, 0.5, 0)
    viewport.camera.distance = 20
    viewport.camera.set_view("top")
    group = _slab()
    viewport.scene.groups.append(group)
    window._on_scale_dialog(group)
    QApplication.processEvents()
    tool = window._tools["scale_manager"]
    assert tool._dialog is not None
    yield window, viewport, group, tool, tool._dialog
    if viewport.active_tool is tool:
        window._activate_tool("select")
    window._saved_version = viewport.scene.version
    window.close()


def _ctx(viewport, point, kind="endpoint"):
    pixel = viewport._world_to_pixel(point)
    assert pixel is not None
    return ToolContext(viewport, point, QPointF(*pixel), Qt.NoModifier,
                       SnapResult(point, kind))


def test_linked_fields_follow_x_and_apply_equal_values(manager):
    _, viewport, group, _, dialog = manager
    viewport.history.execute(scale_command(group, (1, 2, 3)))
    dialog._refresh()
    dialog.link_axes.setChecked(True)
    assert not dialog.fields[1].isEnabled()
    assert not dialog.fields[2].isEnabled()
    dialog.fields[0].selectAll()
    QTest.keyClicks(dialog.fields[0], "4")
    assert [field.text() for field in dialog.fields] == ["4", "4", "4"]
    dialog.fields[0].editingFinished.emit()
    assert group_scale(group) == pytest.approx((4, 4, 4))
    dialog.link_axes.setChecked(False)
    assert dialog.fields[1].isEnabled() and dialog.fields[2].isEnabled()
    viewport.history.undo()
    assert group_scale(group) == pytest.approx((1, 2, 3))


def test_box_pick_targets_group_without_changing_selection_and_esc_restores(manager):
    _, viewport, group, tool, dialog = manager
    other = _slab()
    viewport.scene.selection.add(other)
    dialog.box_button.click()
    assert not dialog.isVisible()
    assert tool._dialog is dialog
    assert len(tool.scale_box_state()["grips"]) == 8
    assert viewport.scene.selection == {other}
    point = QVector3D(0, 0, 0)
    tool.on_click(_ctx(viewport, point))
    assert dialog.isVisible() and dialog._pivot == point
    assert viewport.scene.selection == {other}

    dialog.point_button.click()
    assert not dialog.isVisible()
    assert Viewport._tool_busy(tool)
    viewport.axis_lock = "x"
    viewport.escape()
    assert dialog.isVisible() and dialog._pivot == point
    assert viewport.axis_lock is None
    assert viewport.scene.selection == {other}


@pytest.mark.parametrize("kind", ["endpoint", "midpoint", "on_edge", "on_face"])
def test_inference_pick_accepts_snap_and_rejects_empty_space(manager, kind):
    _, viewport, _, tool, dialog = manager
    dialog.point_button.click()
    assert tool.uses_snap
    tool.on_click(_ctx(viewport, QVector3D(0, 0, 0), "none"))
    assert not dialog.isVisible()
    point = QVector3D(2, 1, 0)
    tool.on_click(_ctx(viewport, point, kind))
    assert dialog.isVisible() and dialog._pivot == point


def test_viewport_inference_selects_a_group_endpoint_as_scale_pivot(manager):
    _, viewport, group, tool, dialog = manager
    viewport.scene.version += 1
    dialog.point_button.click()
    point = QVector3D(2, 1, 0)
    pixel = QPointF(*viewport._world_to_pixel(point))
    event = QMouseEvent(QEvent.MouseMove, pixel, pixel, Qt.NoButton,
                        Qt.NoButton, Qt.NoModifier)
    ctx = viewport._build_ctx(event)
    assert ctx is not None and ctx.snap.kind == "endpoint"
    tool.on_click(ctx)
    assert dialog._pivot == point
    dialog.fields[0].setText("2")
    dialog._apply()
    assert max(v.position.x() for v in group.mesh.vertices) == pytest.approx(2)
    assert min(v.position.x() for v in group.mesh.vertices) == pytest.approx(-2)
    dialog._reset()
    assert min(v.position.x() for v in group.mesh.vertices) == pytest.approx(0)


@pytest.mark.parametrize("component", [False, True])
def test_reset_pick_restores_default_pivot_without_scaling(manager, component):
    _, viewport, group, _, dialog = manager
    row = dialog.layout().itemAt(3).layout()
    assert row.itemAt(0).widget() is dialog.reset_pick_button
    assert row.itemAt(1).widget() is dialog.reset_button
    if component:
        group.xform = QMatrix4x4()
        group.xform.translate(5, 2, 0)
    dialog.finish_pick(QVector3D(10, 0, 0))
    dialog.reset_pick_button.click()
    assert dialog._pivot is None
    assert not viewport.history.undo_stack
    assert group_scale(group) == pytest.approx((1, 1, 1))

    dialog.fields[0].setText("2")
    dialog._apply()
    if component:
        assert group.xform.map(QVector3D()) == QVector3D(5, 2, 0)
        assert group.xform.map(QVector3D(2, 0, 0)) == QVector3D(9, 2, 0)
    else:
        xs = [vertex.position.x() for vertex in group.mesh.vertices]
        assert (min(xs), max(xs)) == pytest.approx((-1, 3))

    dialog.finish_pick(QVector3D(0, 0, 0))
    assert dialog._pivot == QVector3D(0, 0, 0)


@pytest.mark.parametrize("component", [False, True])
def test_explicit_pivot_is_fixed_through_scale_reset_and_undo(component):
    group = _slab()
    if component:
        group.xform = QMatrix4x4()
    scene = Scene()
    scene.groups.append(group)
    history = History(scene)
    pivot = QVector3D(0, 0, 0)
    vertex = next(v for v in group.mesh.vertices
                  if v.position == QVector3D(2, 1, 0))
    history.execute(scale_command(group, (2, 3, 1), pivot))
    position = group.xform.map(vertex.position) if component else vertex.position
    assert position == QVector3D(4, 3, 0)
    history.execute(scale_command(group, (1, 1, 1), pivot))
    position = group.xform.map(vertex.position) if component else vertex.position
    assert position == QVector3D(2, 1, 0)
    history.undo()
    position = group.xform.map(vertex.position) if component else vertex.position
    assert position == QVector3D(4, 3, 0)


def test_switching_tools_closes_hidden_dialog(manager):
    window, viewport, _, tool, dialog = manager
    dialog.point_button.click()
    window._activate_tool("select")
    assert viewport.active_tool is window._tools["select"]
    assert tool._dialog is None
    assert not dialog.isVisible()


def test_closing_dialog_returns_to_select(manager):
    window, viewport, _, tool, dialog = manager
    dialog.close_button.click()
    assert tool._dialog is None
    assert viewport.active_tool is window._tools["select"]
