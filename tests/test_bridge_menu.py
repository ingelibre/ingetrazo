# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Bridge (issue #614) in the window: Tools menu, right-click menu, one
undo step."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMenu

from core.orient import is_closed

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


class _NoExecMenu(QMenu):
    """A real QMenu whose ``exec`` would block the test on a mouse that
    is not there."""

    opened: list = []

    def exec(self, *args, **kwargs):        # noqa: A003 - Qt's name
        _NoExecMenu.opened.append(self)
        return None


def _context_entries(win, monkeypatch, selection):
    import views.main_window as mw
    _NoExecMenu.opened.clear()
    monkeypatch.setattr(mw, "QMenu", _NoExecMenu)
    win.viewport.scene.select(list(selection))
    win.show_viewport_context_menu(QPoint(0, 0))
    assert _NoExecMenu.opened
    return [a.text() for a in _NoExecMenu.opened[0].actions()]


def _two_squares(scene):
    mesh = scene.mesh
    a = mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    b = mesh.add_face([V(0, 0, 2), V(1, 0, 2), V(1, 1, 2), V(0, 1, 2)])
    return a, b


def _tools_menu(win):
    bar = win.menuBar()
    return next(a.menu() for a in bar.actions() if a.text() == "Tools")


def test_tools_menu_has_bridge(win):
    texts = [a.text() for a in _tools_menu(win).actions()]
    assert "Bridge" in texts
    # Next to Follow Me, with the tools that build faces out of others.
    assert texts.index("Bridge") == texts.index("Follow Me") + 3


def test_modify_toolbar_has_a_bridge_button_after_fillet(win):
    actions = win.toolbars["modify"].actions()
    bridge = win._act_bridge
    assert bridge in actions
    assert actions.index(bridge) == actions.index(
        win._tool_actions["fillet"]) + 1
    assert not bridge.icon().isNull()
    # One action for the button and the menu entry, and no key of its own.
    assert bridge in _tools_menu(win).actions()
    assert bridge.shortcuts() == []


def test_the_button_bridges_the_selection(win):
    scene = win.viewport.scene
    a, b = _two_squares(scene)
    scene.select([a, b])
    win._act_bridge.trigger()
    assert len(scene.mesh.faces) == 6 and is_closed(scene.mesh)


def test_bridge_from_the_window_is_one_undo_step(win):
    scene = win.viewport.scene
    a, b = _two_squares(scene)
    scene.select([a, b])
    win._on_bridge()
    assert len(scene.mesh.faces) == 6 and is_closed(scene.mesh)
    # The new sides end up selected.
    assert len([e for e in scene.selection if e in scene.mesh.faces]) == 4
    win.viewport.history.undo()
    assert len(scene.mesh.faces) == 2
    win.viewport.history.redo()
    assert len(scene.mesh.faces) == 6


def test_a_wrong_selection_changes_nothing(win):
    scene = win.viewport.scene
    a, _b = _two_squares(scene)
    scene.select([a])
    win._on_bridge()
    assert len(scene.mesh.faces) == 2
    assert not win.viewport.history.undo_stack


def test_right_click_offers_bridge_only_when_it_can(win, monkeypatch):
    a, b = _two_squares(win.viewport.scene)
    assert "Bridge" in _context_entries(win, monkeypatch, [a, b])
    assert "Bridge" not in _context_entries(win, monkeypatch, [a])


def test_right_click_keeps_texture_on_one_textured_face(win, monkeypatch):
    # The Bridge check went in above the Texture submenu once and took it
    # along: one textured face (never bridgeable) lost Texture ▸ Position.
    a, _b = _two_squares(win.viewport.scene)
    monkeypatch.setattr(win, "_single_textured_face", lambda: (a, "front"))
    entries = _context_entries(win, monkeypatch, [a])
    assert "Texture" in entries and "Bridge" not in entries


def test_a_big_selection_is_not_walked(win, monkeypatch):
    # Every right-click asks; with Ctrl+A on thousands of faces walking the
    # selection took seconds. A third face is enough to say no.
    import core.bridge

    def walked(*_args):
        raise AssertionError("profiles_from_selection walked the selection")
    monkeypatch.setattr(core.bridge, "profiles_from_selection", walked)
    mesh = win.viewport.scene.mesh
    faces = [mesh.add_face([V(i * 2, 0), V(i * 2 + 1, 0), V(i * 2 + 1, 1),
                            V(i * 2, 1)]) for i in range(3)]
    assert not win._bridgeable(faces)
