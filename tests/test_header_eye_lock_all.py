# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A click on the eye's or the padlock's own column header acts on the whole
model: hides everything (or shows it all again when something is hidden),
locks everything (or unlocks it all). On the top-level groups, as one undo
step: what they hold follows, faded, and keeps its own state."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QMouseEvent, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from views.outliner import COL_EYE, COL_LOCK, COL_NAME


def _g(name, kids=()):
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, name=name)
    if kids:
        g.xform = QMatrix4x4()
        g.component = False
        g.children = list(kids)
    return g


def _setup():
    from views.main_window import MainWindow
    win = MainWindow()
    inner = _g("Estructura")
    edificio = _g("Edificio", [inner])
    casa, muro = _g("Casa"), _g("Muro")
    scene = win.viewport.scene
    scene.groups[:] = [edificio, casa, muro]
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    # A header click needs a header on screen: press and release.
    win.resize(1400, 900)
    win.show()
    win.project_browser.raise_()
    for _ in range(10):
        QApplication.processEvents()
    return win, scene, panel, (edificio, inner, casa, muro)


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _click_header(panel, col):
    head = panel.tree.header()
    x = head.sectionViewportPosition(col) + head.sectionSize(col) // 2
    pt = QPointF(x, head.height() // 2)
    glob = QPointF(head.viewport().mapToGlobal(pt.toPoint()))
    for kind, buttons in ((QEvent.MouseButtonPress, Qt.LeftButton),
                          (QEvent.MouseButtonRelease, Qt.NoButton)):
        QApplication.sendEvent(head.viewport(), QMouseEvent(
            kind, pt, glob, Qt.LeftButton, buttons, Qt.NoModifier))
    QApplication.processEvents()


@pytest.mark.parametrize("col, attr", [(COL_EYE, "hidden"),
                                       (COL_LOCK, "locked")])
def test_the_header_closes_everything_then_opens_it_all(col, attr):
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        steps = len(win.viewport.history.undo_stack)
        _click_header(panel, col)
        assert all(getattr(g, attr) for g in (edificio, casa, muro))
        assert not getattr(inner, attr, False)        # follows, faded
        assert len(win.viewport.history.undo_stack) == steps + 1
        _click_header(panel, col)
        assert not any(getattr(g, attr) for g in (edificio, casa, muro))
    finally:
        _close(win)


@pytest.mark.parametrize("col, attr", [(COL_EYE, "hidden"),
                                       (COL_LOCK, "locked")])
def test_with_something_closed_the_header_opens_it_all(col, attr):
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        setattr(casa, attr, True)
        scene.version += 1
        panel.refresh()
        _click_header(panel, col)
        assert not any(getattr(g, attr) for g in (edificio, casa, muro))
    finally:
        _close(win)


def test_a_group_closed_on_purpose_inside_keeps_its_state():
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        inner.locked = True
        scene.version += 1
        panel.refresh()
        _click_header(panel, COL_LOCK)                # lock all
        _click_header(panel, COL_LOCK)                # unlock all
        assert not edificio.locked and inner.locked
    finally:
        _close(win)


def test_other_headers_do_nothing_of_the_kind():
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        _click_header(panel, COL_NAME)
        assert not any(g.hidden or getattr(g, "locked", False)
                       for g in (edificio, casa, muro))
    finally:
        _close(win)


def _shows(button, key):
    """The button wears the drawn ``key`` icon and no character (#658)."""
    from views.outliner import node_icon
    return (button.text() == ""
            and button.icon().cacheKey() == node_icon(key).cacheKey())


# --- Isolate and Show all: one button -----------------------------------------

def test_one_button_isolates_then_shows_it_all():
    from core.i18n import tr
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        b = panel._isolate_btn
        assert not b.isChecked() and _shows(b, "isolate")
        assert b.toolTip() == tr(
            "Isolate: hide everything but the selected groups")
        root = panel.tree.topLevelItem(0)
        panel.tree.setCurrentItem(root.child(1))           # «Casa»
        b.click()                                          # isolate
        assert not casa.hidden and edificio.hidden and muro.hidden
        assert b.isChecked() and _shows(b, "isolate_on")
        assert b.toolTip() == tr("Exit isolation: show again what Isolate "
                                 "hid")
        b.click()                                          # exit isolation
        assert not any(g.hidden for g in (edificio, casa, muro))
        assert not b.isChecked() and _shows(b, "isolate")
    finally:
        _close(win)


def test_something_hidden_by_hand_is_not_the_buttons_business():
    """Hidden by hand, it stays ◎: the button is for isolating only."""
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        muro.hidden = True
        scene.version += 1
        panel.refresh()
        assert not panel._isolate_btn.isChecked()
        assert _shows(panel._isolate_btn, "isolate")
    finally:
        _close(win)


def test_leaving_the_isolation_keeps_what_was_hidden_by_hand():
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        muro.hidden = True                     # hidden on purpose
        scene.version += 1
        panel.refresh()
        root = panel.tree.topLevelItem(0)
        panel.tree.setCurrentItem(root.child(1))           # «Casa»
        b = panel._isolate_btn
        b.click()                                          # isolate
        assert edificio.hidden and muro.hidden and not casa.hidden
        assert b.isChecked()
        b.click()                                          # exit
        assert not edificio.hidden and not casa.hidden
        assert muro.hidden                                 # as it was
        assert not b.isChecked()
    finally:
        _close(win)


def test_undoing_the_isolation_ends_it():
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        root = panel.tree.topLevelItem(0)
        panel.tree.setCurrentItem(root.child(1))
        panel._isolate_btn.click()
        assert panel._isolate_btn.isChecked()
        win.viewport.history.undo()
        panel.refresh()
        assert not edificio.hidden and not muro.hidden
        assert not panel._isolate_btn.isChecked()
    finally:
        _close(win)


def test_the_menu_offers_exit_and_the_way_out_of_everything():
    from PySide6.QtCore import QTimer
    from core.i18n import tr
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        inner.hidden = True                    # hidden inside a group
        scene.version += 1
        panel.refresh()
        root = panel.tree.topLevelItem(0)
        panel.tree.setCurrentItem(root.child(1))
        panel._isolate_btn.click()
        texts = []

        def read():
            m = QApplication.activePopupWidget()
            if m is None:
                QTimer.singleShot(10, read)
                return
            texts.extend(a.text() for a in m.actions())
            m.close()
        QTimer.singleShot(0, read)
        panel._on_context_menu(panel.tree.visualItemRect(
            root.child(1)).center())
        assert tr("Exit isolation") in texts
        assert tr("Show everything hidden (every level)") in texts
        assert tr("Show all groups") not in texts
        panel.show_all()                       # the way out of everything
        assert not any(g.hidden for g in (edificio, inner, casa, muro))
        assert not panel._isolate_btn.isChecked()
    finally:
        _close(win)


def test_isolating_with_nothing_selected_says_so():
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        said = []
        win.viewport.flash_status = lambda text, *a, **k: said.append(text)
        panel.tree.clearSelection()
        scene.selection.clear()
        panel._isolate_btn.click()
        assert said and not any(g.hidden for g in (edificio, casa, muro))
        assert not panel._isolate_btn.isChecked()
    finally:
        _close(win)


# --- Expand all and Collapse all: one button ----------------------------------

def test_one_button_expands_everything_then_collapses_it():
    from core.i18n import tr
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        b = panel._expand_btn
        item = panel._items[id(edificio)]
        item.setExpanded(False)
        assert _shows(b, "expand_all") and b.toolTip() == tr("Expand all")
        b.click()
        assert item.isExpanded()
        assert _shows(b, "collapse_all") and b.toolTip() == tr("Collapse all")
        b.click()
        assert not item.isExpanded()
        assert panel.tree.topLevelItem(0).isExpanded()   # the document row
        assert _shows(b, "expand_all")
    finally:
        _close(win)


def test_unfolding_by_hand_turns_it_into_collapse_all():
    win, scene, panel, (edificio, inner, casa, muro) = _setup()
    try:
        item = panel._items[id(edificio)]
        item.setExpanded(False)
        assert _shows(panel._expand_btn, "expand_all")
        item.setExpanded(True)                  # the arrow, by hand
        assert _shows(panel._expand_btn, "collapse_all")
    finally:
        _close(win)
