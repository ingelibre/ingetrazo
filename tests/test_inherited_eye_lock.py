# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What a hidden or locked group holds is hidden or locked too, and the
Browser now says so: its eye or padlock shows closed but faded, «Hidden by
«Edificio»», «Locked by «Edificio»». Nothing inside is changed — each row
keeps its own state, so unlocking the group gives every row back as it
was, a row locked on purpose still locked."""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.i18n import tr
from core.mesh import Mesh
from views.outliner import COL_EYE, COL_LOCK, COL_NAME, inherited_states


def _g(name, kids=()):
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, name=name)
    if kids:
        g.xform = QMatrix4x4()
        g.component = False
        g.children = list(kids)
    return g


def _model():
    cocina = _g("Cocina")
    planta = _g("Planta baja", [cocina])
    estructura = _g("Estructura")
    edificio = _g("Edificio", [planta, estructura])
    return edificio, planta, cocina, estructura


def test_the_nearest_closed_group_around_each_one():
    edificio, planta, cocina, estructura = _model()
    edificio.locked = True
    planta.hidden = True
    s = inherited_states([edificio])
    assert s[id(edificio)] == (None, None)
    assert s[id(planta)] == (None, edificio)
    assert s[id(cocina)] == (planta, edificio)
    assert s[id(estructura)] == (None, edificio)


def _window(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups[:] = groups
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_the_rows_inside_a_locked_group_show_a_faded_padlock():
    edificio, planta, cocina, estructura = _model()
    estructura.locked = True                 # locked on its own
    edificio.locked = True
    win, scene, panel = _window(edificio)
    try:
        items = panel._items
        tip = tr("Locked by «{name}»", name="Edificio")
        assert items[id(planta)].toolTip(COL_LOCK) == tip
        assert items[id(cocina)].toolTip(COL_LOCK) == tip
        # its own padlock, not an inherited one
        assert items[id(estructura)].toolTip(COL_LOCK) == ""
        assert items[id(estructura)].data(COL_LOCK, 0x0100)
        assert not items[id(planta)].data(COL_LOCK, 0x0100)
        assert not planta.locked and not cocina.locked   # nothing changed
    finally:
        _close(win)


def test_unlocking_the_group_gives_every_row_back_as_it_was():
    edificio, planta, cocina, estructura = _model()
    estructura.locked = True
    win, scene, panel = _window(edificio)
    try:
        panel.toggle_locked([edificio])
        assert edificio.locked
        panel.toggle_locked([edificio])
        assert not edificio.locked
        assert estructura.locked                         # kept its own
        assert not planta.locked and not cocina.locked
        assert panel._items[id(planta)].toolTip(COL_LOCK) == ""
    finally:
        _close(win)


def test_the_rows_inside_a_hidden_group_show_a_faded_eye_and_grey_names():
    from PySide6.QtGui import QPalette
    edificio, planta, cocina, estructura = _model()
    edificio.hidden = True
    win, scene, panel = _window(edificio)
    try:
        item = panel._items[id(cocina)]
        assert item.toolTip(COL_EYE) == tr("Hidden by «{name}»",
                                           name="Edificio")
        grey = panel.tree.palette().brush(QPalette.PlaceholderText).color()
        assert item.foreground(COL_NAME).color() == grey
        assert not cocina.hidden
    finally:
        _close(win)


def test_pressing_an_inherited_padlock_says_why_and_changes_nothing():
    edificio, planta, cocina, estructura = _model()
    edificio.locked = True
    win, scene, panel = _window(edificio)
    try:
        said = []
        win.viewport.flash_status = lambda text, *a, **k: said.append(text)
        steps = len(win.viewport.history.undo_stack)
        panel._on_item_clicked(panel._items[id(cocina)], COL_LOCK)
        assert not cocina.locked
        assert len(win.viewport.history.undo_stack) == steps
        assert said == [tr("Locked by «{name}»: unlock it first",
                           name="Edificio")]
    finally:
        _close(win)


def test_pressing_an_inherited_eye_says_why_and_changes_nothing():
    edificio, planta, cocina, estructura = _model()
    edificio.hidden = True
    win, scene, panel = _window(edificio)
    try:
        said = []
        win.viewport.flash_status = lambda text, *a, **k: said.append(text)
        panel._on_item_clicked(panel._items[id(planta)], COL_EYE)
        assert not planta.hidden
        assert said == [tr("Hidden by «{name}»: show it first",
                           name="Edificio")]
    finally:
        _close(win)


def test_a_row_locked_on_its_own_inside_unlocks_on_its_own():
    edificio, planta, cocina, estructura = _model()
    estructura.locked = True
    edificio.locked = True
    win, scene, panel = _window(edificio)
    try:
        panel._on_item_clicked(panel._items[id(estructura)], COL_LOCK)
        assert not estructura.locked                     # its own: it may
        assert panel._items[id(estructura)].toolTip(COL_LOCK) == \
            tr("Locked by «{name}»", name="Edificio")    # still, by Edificio
    finally:
        _close(win)
