# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Of several views, the one clicked is the one worked in: Camera ▸ Style,
the Styles panel, Alt+X, the projection buttons and the standard views act
on it alone, and every view shown repaints at once (a 0.6.1 review on
Windows: Wireframe asked for the Top view went to two views, the others
caught up only under the mouse, and Perspective changed the Perspective
view while Top was the active one)."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    w.set_view_layout("four")
    QApplication.processEvents()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _cell(win, view):
    return next(c for c in win._doc.view_grid.cells if c.view == view)


def _click(cell):
    """A click in an empty corner of the view, as the hand does."""
    vp = cell.viewport
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier,
                     QPoint(vp.width() - 6, vp.height() - 6))
    QApplication.processEvents()


def _mode(cell):
    return cell.viewport._effective_style().face_mode


def test_a_style_goes_to_the_view_clicked_only(win):
    top, persp = _cell(win, "top"), _cell(win, "perspective")
    others = [c for c in win._doc.view_grid.cells if c is not top]
    before = {c.index: _mode(c) for c in others}
    _click(top)
    win._style_actions["Wireframe"].trigger()
    assert _mode(top) == "wireframe"
    assert {c.index: _mode(c) for c in others} == before
    assert win.viewport is persp.viewport        # the document's style...
    assert win.viewport.scene.display_style.face_mode == before[persp.index]


def test_the_windows_own_view_takes_a_style_and_the_others_keep_theirs(win):
    persp = _cell(win, "perspective")
    others = [c for c in win._doc.view_grid.cells if c is not persp]
    before = {c.index: _mode(c) for c in others}
    _click(persp)
    win._style_actions["X-ray"].trigger()
    assert _mode(persp) == "xray"
    assert {c.index: _mode(c) for c in others} == before


def test_every_view_shown_repaints_with_a_style(win, monkeypatch):
    painted = []
    for cell in win._doc.view_grid.cells:
        monkeypatch.setattr(cell.viewport, "update",
                            lambda c=cell: painted.append(c.index))
    _click(_cell(win, "top"))
    painted.clear()
    win._style_actions["Wireframe"].trigger()
    assert sorted(set(painted)) == [0, 1, 2, 3]


def test_an_edge_toggle_goes_to_the_view_clicked_only(win):
    top, front = _cell(win, "top"), _cell(win, "front")
    _click(top)
    edges = top.viewport._effective_style().edges
    win._act_style_edges.setChecked(not edges)
    assert top.viewport._effective_style().edges is (not edges)
    assert front.viewport._effective_style().edges is edges
    assert win.viewport._effective_style().edges is edges


def test_the_menu_says_the_style_of_the_view_clicked(win):
    top, persp = _cell(win, "top"), _cell(win, "perspective")
    _click(top)
    win._style_actions["Wireframe"].trigger()
    _click(persp)
    assert not win._style_actions["Wireframe"].isChecked()
    _click(top)
    assert win._style_actions["Wireframe"].isChecked()


def test_the_styles_panel_edits_the_view_clicked(win):
    from core.style import style_by_name
    top, front = _cell(win, "top"), _cell(win, "front")
    _click(top)
    panel = win.styles_panel
    panel._on_pick(panel._combo.findData("Wireframe"))
    assert _mode(top) == "wireframe"
    assert _mode(front) != "wireframe"
    assert panel._style() is top.viewport.view_style
    del style_by_name


def test_alt_x_comes_back_in_the_same_view(win):
    top, front = _cell(win, "top"), _cell(win, "front")
    _click(top)
    was = _mode(top)
    win._toggle_xray()
    assert _mode(top) == "xray" and _mode(front) != "xray"
    win._toggle_xray()
    assert _mode(top) == was


def test_a_projection_button_changes_the_view_clicked(win):
    top, persp = _cell(win, "top"), _cell(win, "perspective")
    assert not top.viewport.camera.perspective
    assert persp.viewport.camera.perspective
    _click(top)
    win._projection_actions["perspective"].trigger()
    assert top.viewport.camera.perspective
    win._projection_actions["parallel"].trigger()
    assert not top.viewport.camera.perspective
    assert persp.viewport.camera.perspective     # untouched both times


def test_the_projection_buttons_say_the_view_clicked(win):
    top, persp = _cell(win, "top"), _cell(win, "perspective")
    _click(top)
    assert win._projection_actions["parallel"].isChecked()
    _click(persp)
    assert win._projection_actions["perspective"].isChecked()


def test_a_standard_view_goes_to_the_view_clicked(win):
    front, persp = _cell(win, "front"), _cell(win, "perspective")
    yaw = persp.viewport.camera.yaw
    _click(front)
    QTest.keySequence(win, "Ctrl+1")             # Top
    QApplication.processEvents()
    assert front.view == "top"
    assert front.header.text() == "Top"
    assert persp.viewport.camera.yaw == yaw


def test_one_view_works_as_before(win):
    win.set_view_layout("single")
    QApplication.processEvents()
    assert win._active_view() is win.viewport
    win._style_actions["Wireframe"].trigger()
    assert win.viewport.scene.display_style.face_mode == "wireframe"
    win._projection_actions["parallel"].trigger()
    assert not win.viewport.camera.perspective


def test_each_views_style_stays_with_its_project_tab(win):
    top = _cell(win, "top")
    _click(top)
    win._style_actions["Wireframe"].trigger()
    state = win._doc.view_grid.state()
    grid = win._doc.view_grid
    grid.restore(None)
    assert _mode(top) != "wireframe"
    grid.restore(state)
    assert _mode(top) == "wireframe"


def test_shift_p_changes_the_view_clicked(win):
    top, persp = _cell(win, "top"), _cell(win, "perspective")
    _click(top)
    QTest.keySequence(win, "Shift+P")
    QApplication.processEvents()
    assert top.viewport.camera.perspective
    assert persp.viewport.camera.perspective
    assert win._projection_actions["perspective"].isChecked()
