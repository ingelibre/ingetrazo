# SPDX-License-Identifier: GPL-3.0-or-later
"""Edit ▸ Intersect Faces tells the truth about what it did (tutorial hunt
2, A12).

A sphere made with Follow Me through a cube gave crossings of 21–90 µm.
Their two ends weld into one vertex, that degenerate edge refused the whole
step, and the status still said «178 intersection edges added»."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _window(monkeypatch, segs):
    import core.intersect
    from views.main_window import MainWindow
    win = MainWindow()
    win._confirm_discard = lambda *a, **k: True   # never a modal on close
    face = win.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    win.viewport.scene.selection.add(face)
    monkeypatch.setattr(core.intersect, "segments_for",
                        lambda scene, mode: list(segs))
    said = []
    monkeypatch.setattr(win.viewport, "flash_status",
                        lambda text, *a, **k: said.append(text))
    warned = []
    import views.main_window as mw
    monkeypatch.setattr(mw.QMessageBox, "warning",
                        lambda *a, **k: warned.append(a[1:]))
    return win, said, warned


def test_a_crossing_shorter_than_the_weld_is_left_out(monkeypatch):
    from core.intersect import WITH_MODEL
    segs = [(V(1, 0, 0), V(1, 2, 0)),
            (V(1.5, 1, 0), V(1.5, 1.00005, 0))]       # 50 µm
    win, said, warned = _window(monkeypatch, segs)
    try:
        undo = len(win.viewport.history.undo_stack)
        win._on_intersect_faces(WITH_MODEL)
        assert win.viewport.history.last_error is None
        assert len(win.viewport.history.undo_stack) == undo + 1
        assert not warned
        assert said and "1" in said[-1]
    finally:
        win.close()


def test_a_refused_intersection_says_so(monkeypatch):
    from core.intersect import WITH_MODEL
    win, said, warned = _window(monkeypatch, [(V(1, 0, 0), V(1, 2, 0))])
    history = win.viewport.history

    def refuse(cmd):
        history.last_error = "degenerate edge"
    monkeypatch.setattr(history, "execute", refuse)
    try:
        win._on_intersect_faces(WITH_MODEL)
        assert warned
        assert not any("added" in s or "añadid" in s for s in said)
    finally:
        win.close()
