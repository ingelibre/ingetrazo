# SPDX-License-Identifier: GPL-3.0-or-later
"""Add, Update and Delete Scene are window actions (#695, discussions #639
and #640: «a shortcut to add or remove scenes»).

The Scenes panel's buttons were the only way in, and a button is no
``QAction``: Preferences ▸ Shortcuts had nothing to give a key to. They are
now Camera ▸ Scenes, with no factory keys, and each runs what its button
runs.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import core.extensions as extensions                              # noqa: E402

_KEYS = ("scene_add", "scene_update", "scene_delete")


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def test_the_three_take_a_key_in_preferences_and_have_none_yet(win):
    from views.shortcuts import action_key, collect_actions
    keys = {action_key(a): a for a in collect_actions(win)}
    for key in _KEYS:
        assert key in keys, f"{key} is not offered in Preferences ▸ Shortcuts"
        assert keys[key].shortcut().isEmpty(), "the known interface changed"


def test_they_live_in_camera_scenes(win):
    from PySide6.QtWidgets import QMenu
    menus = {m.title(): m for m in win.menuBar().findChildren(QMenu)}
    scenes = menus["Scenes"]
    assert scenes.menuAction() in menus["Camera"].actions()
    assert [a.objectName() for a in scenes.actions()] == list(_KEYS)


def test_add_update_and_delete_do_what_the_buttons_do(win):
    scene = win.viewport.scene
    cam = win.viewport.camera
    acts = win._scene_actions
    n = len(scene.saved_views)

    acts["scene_add"].trigger()
    assert len(scene.saved_views) == n + 1
    added = scene.saved_views[-1]
    assert "added" in win.statusBar().currentMessage()
    # The new scene is the current one, so Update right after updates it.
    cam.distance = added.distance * 2
    acts["scene_update"].trigger()
    assert added.distance == pytest.approx(cam.distance)

    acts["scene_delete"].trigger()
    assert added not in scene.saved_views
    assert win.viewport.history.undo()            # still one undo step
    assert scene.saved_views[-1] is added


def test_without_a_selected_scene_the_status_bar_says_why(win):
    scene = win.viewport.scene
    win.tray.scenes.refresh()                     # nothing selected
    before = list(scene.saved_views)
    for key in ("scene_update", "scene_delete"):
        win.statusBar().clearMessage()
        win._scene_actions[key].trigger()
        assert "Select a scene" in win.statusBar().currentMessage()
    assert scene.saved_views == before


def test_a_key_given_to_add_scene_adds_one(win):
    seq = QKeySequence("Ctrl+Alt+Shift+F11")
    from PySide6.QtGui import QAction
    assert not any(a.shortcut() == seq for a in win.findChildren(QAction))
    win._scene_actions["scene_add"].setShortcut(seq)
    QTest.keyClick(win.viewport, Qt.Key_F1)       # the first key is dropped
    QApplication.processEvents()
    n = len(win.viewport.scene.saved_views)
    QTest.keyClick(win.viewport, Qt.Key_F11,
                   Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier)
    QApplication.processEvents()
    assert len(win.viewport.scene.saved_views) == n + 1
