# SPDX-License-Identifier: GPL-3.0-or-later
"""Option toggles copy on Mac without stealing Alt from other tools/platforms."""
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QVector3D
from PySide6.QtWidgets import QApplication, QMainWindow

from tools.base import ToolContext
from tools.flip import FlipTool
from tools.line import LineTool
from tools.move import MoveTool
from tools.rotate import RotateTool
from views import viewport as viewport_module


@pytest.fixture
def vp(monkeypatch):
    monkeypatch.setattr(viewport_module, "sys", SimpleNamespace(platform="darwin"))
    window = QMainWindow()
    viewport = viewport_module.Viewport(window)
    window.setCentralWidget(viewport)
    yield viewport
    window.close()


def tap(vp, key=Qt.Key_Alt, modifier=Qt.AltModifier):
    QApplication.sendEvent(vp, QKeyEvent(QEvent.KeyPress, key, modifier))
    QApplication.sendEvent(vp, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier))


@pytest.mark.parametrize("cls", [MoveTool, RotateTool, FlipTool])
def test_option_toggles_copy_with_a_plus_cursor_and_command_still_works(vp, cls):
    tool = cls()
    vp.set_active_tool(tool)
    tap(vp)
    assert tool.cursor_plus
    tap(vp)
    assert not tool.cursor_plus
    tap(vp, Qt.Key_Control, Qt.ControlModifier)
    assert tool.cursor_plus


def test_option_copies_a_line_and_the_copy_is_one_undo_step(vp):
    edge = vp.scene.mesh.add_edge(QVector3D(0, 0, 0), QVector3D(1, 0, 0))
    vp.scene.selection.add(edge)
    tool = MoveTool()
    vp.set_active_tool(tool)

    def ctx(x):
        return ToolContext(vp, QVector3D(x, 0, 0), QPointF(), Qt.NoModifier, None)

    tool.on_click(ctx(0))
    tool.on_hover(ctx(1))
    tap(vp)
    assert tool.cursor_plus
    assert min(v.position.x() for v in vp.scene.mesh.vertices) == pytest.approx(0)
    tool.on_click(ctx(3))
    assert sorted((round(e.a.x()), round(e.b.x())) for e in vp.scene.mesh.edges) == [
        (0, 1), (3, 4)]
    vp.history.undo()
    assert len(vp.scene.mesh.edges) == 1
    assert (vp.scene.mesh.edges[0].a.x(), vp.scene.mesh.edges[0].b.x()) == (0, 1)


def test_an_option_shortcut_does_not_leave_copy_switched(vp):
    tool = MoveTool()
    vp.set_active_tool(tool)
    QApplication.sendEvent(vp, QKeyEvent(QEvent.KeyPress, Qt.Key_Alt, Qt.AltModifier))
    assert tool.cursor_plus
    QApplication.sendEvent(vp, QKeyEvent(QEvent.ShortcutOverride,
                                        Qt.Key_X, Qt.AltModifier, "x"))
    QApplication.sendEvent(vp, QKeyEvent(QEvent.KeyRelease, Qt.Key_Alt, Qt.NoModifier))
    assert not tool.cursor_plus


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_alt_is_not_a_copy_modifier_on_other_platforms(vp, monkeypatch, platform):
    monkeypatch.setattr(viewport_module, "sys", SimpleNamespace(platform=platform))
    tool = MoveTool()
    vp.set_active_tool(tool)
    tap(vp)
    assert not tool.cursor_plus
    tap(vp, Qt.Key_Control, Qt.ControlModifier)
    assert tool.cursor_plus


def test_option_keeps_its_inference_role_in_the_line_tool(vp):
    tool = LineTool()
    vp.set_active_tool(tool)
    tool.on_click(ToolContext(vp, QVector3D(), QPointF(), Qt.NoModifier, None))
    assert vp.linear_inference_mode == "all"
    tap(vp)
    assert vp.linear_inference_mode == "off"


def test_the_move_hint_names_option_instead_of_offering_alt_inferences(vp, monkeypatch):
    from core.i18n import tr
    from views import status_hints
    monkeypatch.setattr(status_hints, "sys", SimpleNamespace(platform="darwin"))
    tool = MoveTool()
    assert tr("Option = copy") in status_hints.hint_for("move", tool)
    tool.start_point = QVector3D()
    hint = status_hints.hint_for("move", tool, linear_mode="all")
    assert tr("Option = copy") in hint
    assert "Alt =" not in hint
