# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #1269 (@tuxiasumari): closing the window in the first second,
before the model loads, was ignored — the application finished opening
the file and stayed open, and the window had to be closed a second time.

The startup open is deferred behind the first frame, and the load pumps
events at every milestone, so a close can land before the open runs or
while it runs. Neither may be lost: an open queued behind an accepted
close is refused, and a close during the load unwinds it at the next
milestone and then closes the window for real — without asking about
discarding a drawing that is the loader's, not the user's."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def doc(tmp_path):
    from core.group import Group
    from core.mesh import Mesh
    from views.main_window import MainWindow

    w0 = MainWindow()
    scene = w0.viewport.scene
    for i in range(6):
        m = Mesh()
        x = i * 3.0
        m.add_face([QVector3D(x, 0, 0), QVector3D(x + 2, 0, 0),
                    QVector3D(x + 2, 2, 0), QVector3D(x, 2, 0)])
        scene.groups.append(Group(m, name=f"B{i}"))
    scene.version += 1
    path = tmp_path / "plan.igz"
    w0._do_save(path)
    w0._saved_version = scene.version
    w0.close()
    return path


def test_open_queued_behind_an_accepted_close_is_refused(doc, monkeypatch):
    import formats.igz as igz
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    win.close()                       # the user's first-second close
    assert win._closed

    calls = []
    real_load = igz.load_into
    monkeypatch.setattr(igz, "load_into",
                        lambda *a, **k: calls.append((a, k)))
    try:
        assert win.open_path(doc) is False
        assert calls == []            # the file was never even read
        assert win._current_path is None
    finally:
        monkeypatch.setattr(igz, "load_into", real_load)


def test_close_during_the_load_unwinds_it_and_closes(doc, monkeypatch):
    import formats.igz as igz
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    milestones = []
    prompts = []
    monkeypatch.setattr(win, "_confirm_discard",
                        lambda *a, **k: prompts.append(a) or True)

    def fake_load(scene, path, progress=None):
        # Stream the document in: geometry arriving is a content change,
        # and at the second milestone the user closes the window.
        for i in range(10):
            scene.version += 1
            milestones.append(i)
            if progress is not None:
                progress(i / 10.0, "Loading")
            if i == 1:
                win.close()

    monkeypatch.setattr(igz, "load_into", fake_load)
    try:
        assert win.open_path(doc) is False
    finally:
        monkeypatch.undo()
    # The load stopped at the milestone after the close, not at the end.
    assert milestones == [0, 1, 2]
    # No "discard changes?" about the loader's half-finished drawing.
    assert prompts == []
    assert win._current_path is None
    # The deferred real close then went through.
    _app.processEvents()
    assert win._closed
    assert not win.isVisible()


def test_closing_the_bar_during_the_load_closes_the_window(doc, monkeypatch):
    """The bar is window-modal, and Qt drops a close of a window a modal
    dialog blocks: the main window's X did nothing while the bar showed
    (Windows round 0.6.2, secador4). The bar's own X is the way out."""
    import formats.igz as igz
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    milestones = []

    def fake_load(scene, path, progress=None):
        for i in range(10):
            scene.version += 1
            milestones.append(i)
            if progress is not None:
                progress(i / 10.0, "Loading")
            if i == 1:
                win._progress_dlg.close()     # the bar's X (or Esc)

    monkeypatch.setattr(igz, "load_into", fake_load)
    try:
        assert win.open_path(doc) is False
    finally:
        monkeypatch.undo()
    assert milestones == [0, 1, 2]
    _app.processEvents()
    assert win._closed
    assert not win.isVisible()


def test_the_bar_closing_after_the_load_leaves_the_window_open(doc):
    """The bar closes itself once the document is in: that is no close."""
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    try:
        assert win.open_path(doc) is True
        win._progress_dlg.close()
        _app.processEvents()
        assert not win._closed and not win._open_aborted
        assert win.open_path(doc) is True        # the next open is not cut
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_failed_open_does_not_cut_the_next_one(doc, monkeypatch):
    """A failed open closes its bar while the load still counts as running;
    that must not unwind the next open."""
    import formats.igz as igz
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    monkeypatch.setattr("views.main_window.QMessageBox.critical",
                        lambda *a, **k: None)
    real = igz.load_into

    def broken(scene, path, progress=None):
        if progress is not None:
            progress(0.5, "Loading")
        raise ValueError("corrupt")

    monkeypatch.setattr(igz, "load_into", broken)
    try:
        assert win.open_path(doc) is False
        monkeypatch.setattr(igz, "load_into", real)
        assert win.open_path(doc) is True
        assert not win._closed
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_normal_open_still_opens(doc):
    from views.main_window import MainWindow

    win = MainWindow(defer_extensions=True)
    try:
        assert win.open_path(doc) is True
        assert win._current_path == Path(doc)
        assert not win._closed
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
