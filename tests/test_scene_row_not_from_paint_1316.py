# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1316: an .skp import that brought scenes crashed the app on macOS
right after it finished. The first frame announced the new version from
inside paintGL, the Scenes panel followed, and the scene tab row came up
under the viewport — resizing the view in the middle of its own frame;
the flush after it crashed. The row now comes or goes once the frame is
out."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from views.viewport import Viewport  # noqa: E402


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _add_scene(win, name="Scene 1"):
    from core.saved_views import SavedView
    win.viewport.scene.saved_views.append(
        SavedView.capture(name, win.viewport.scene, win.viewport.camera))


def test_the_row_waits_for_the_frame_to_be_out(win):
    row = win._scene_tabs
    assert row.isHidden()
    _add_scene(win)
    Viewport.painting += 1                 # as from inside paintGL
    try:
        win.tray.scenes.refresh()
        win.tray.scenes.refresh()          # a burst…
        assert row.isHidden()              # …never from inside the paint
    finally:
        Viewport.painting -= 1
    QApplication.processEvents()
    assert not row.isHidden()              # the next turn shows it
    assert row.tabs.count() == 1


def test_outside_a_paint_the_row_follows_at_once(win):
    _add_scene(win)
    win.tray.scenes.refresh()
    assert not win._scene_tabs.isHidden()


def test_paintgl_counts_itself_even_when_it_raises(win, monkeypatch):
    vp = win.viewport
    seen = []

    def frame(self):
        seen.append(Viewport.painting)
        raise RuntimeError("a broken frame")

    monkeypatch.setattr(Viewport, "_paint_frame", frame)
    with pytest.raises(RuntimeError):
        vp.paintGL()
    assert seen == [1]
    assert Viewport.painting == 0
