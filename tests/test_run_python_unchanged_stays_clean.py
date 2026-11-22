# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A ``run_python`` that changes nothing leaves the document clean (0.6.3
modelling test, 20-11).

Through the MCP server, ``x = 1`` answered «changed: False» and yet
``document_info`` read ``modified: true`` afterwards, so the agent's
``shutdown`` was refused for unsaved changes. The snapshot command bumps
``scene.version`` on every run; the empty step was taken off the undo
stack, but the bump stayed and counted as content."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core import ai

app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    vp = w.viewport
    vp.scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                            QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    vp.scene.version += 1
    w._saved_version = vp.scene.version          # as if just saved
    assert not w._is_dirty()
    yield w
    w._saved_version = vp.scene.version
    w.close()


@pytest.mark.parametrize("code", [
    "x = 1",
    "print(len(scene.mesh.faces))",
    "len(scene.mesh.faces)",
])
def test_code_that_changes_nothing_leaves_the_document_clean(win, code):
    vp = win.viewport
    undo = len(vp.history.undo_stack)
    version = vp.scene.version
    r = ai.run_transactional(vp, code, {"__name__": "__ai__"})
    assert r["error"] is None and r["changed"] is False
    assert len(vp.history.undo_stack) == undo
    assert vp.scene.version > version, "the caches must still refresh"
    assert not win._is_dirty(), "nothing changed, yet the document is dirty"


def test_code_that_changes_the_model_still_dirties_it(win):
    vp = win.viewport
    r = ai.run_transactional(
        vp, "scene.mesh.add_edge(V(3, 0, 0), V(4, 0, 0))",
        {"__name__": "__ai__", "V": QVector3D})
    assert r["error"] is None and r["changed"] is True
    assert win._is_dirty()


def test_a_bump_made_by_the_code_itself_is_kept(win):
    """Code that says it changed something (an API that bumps the version
    by hand, untracked by the snapshot) keeps the document dirty: only the
    command's own bumps are taken back."""
    vp = win.viewport
    r = ai.run_transactional(vp, "scene.version += 1", {"__name__": "__ai__"})
    assert r["error"] is None and r["changed"] is False
    assert win._is_dirty()
