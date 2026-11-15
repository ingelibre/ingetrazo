# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1316: an .skp import that brought scenes crashed the app on macOS
right after it finished. ``_sync_edges`` runs inside ``paintGL`` and
announced the new version there; the Scenes panel followed and the scene
tab row came up under the viewport, resizing the view in the middle of
its own frame — the flush after it crashed. What a frame finds is now
announced once the frame is out, so no listener runs inside a paint."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from tests.test_view_only_bumps import _fake_gl  # noqa: E402


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(800, 600)
    vp = win.viewport
    vp.scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
    vp.scene.version += 1
    _fake_gl(vp)
    return win


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_the_sync_announces_once_the_frame_is_out():
    win = _window()
    try:
        vp = win.viewport
        seen: list = []
        vp.sceneVersionChanged.connect(seen.append)
        vp._sync_edges()
        assert seen == []                     # not from inside the paint
        _app.processEvents()
        assert seen == [vp._edges_version]
    finally:
        _close(win)


def test_a_burst_of_frames_says_the_latest_once():
    win = _window()
    try:
        vp = win.viewport
        seen: list = []
        vp.sceneVersionChanged.connect(seen.append)
        vp._sync_edges()
        vp.scene.select(list(vp.scene.edges)[:1])   # a view-only bump
        vp._sync_edges()
        vp.scene.version += 1                       # an edit
        vp._sync_edges()
        assert seen == []
        _app.processEvents()
        assert seen == [vp._edges_version]
    finally:
        _close(win)


def test_the_scene_row_comes_up_after_the_frame():
    """The crash itself: an import brings scenes, the next frame finds
    them, and the row under the view must wait for that frame."""
    from core.saved_views import SavedView
    win = _window()
    try:
        vp = win.viewport
        row = win._scene_tabs
        win.show()
        _app.processEvents()
        vp.scene.saved_views.append(
            SavedView.capture("Scene 1", vp.scene, vp.camera))
        vp.scene.version += 1
        vp._sync_edges()
        assert row.isHidden()
        _app.processEvents()
        assert not row.isHidden() and row.tabs.count() == 1
    finally:
        _close(win)


def test_notify_scene_changed_still_says_it_at_once():
    win = _window()
    try:
        vp = win.viewport
        seen: list = []
        vp.sceneVersionChanged.connect(seen.append)
        vp.notify_scene_changed()
        assert seen == [vp.scene.version]
    finally:
        _close(win)
