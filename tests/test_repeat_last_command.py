# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Repeat last command: Blender's Shift+R, and right-click ▸ Repeat.

A tool comes back as if its key were pressed; a one-shot command (Reverse
Faces, Make Group, Intersect…) runs again on the CURRENT selection.

Only on deliberate gestures. Space stays the usual Select and Enter keeps
doing nothing on Select: a key pressed out of habit that repeated could
bring back the Eraser — the next click to select would erase — or run
Explode on whatever happens to be selected (Marco, 2026-09-26: «solo
Shift+R y clic derecho»).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QKeyEvent, QVector3D
from PySide6.QtWidgets import QApplication, QMenu

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)


def _V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _face(scene, x0=0.0):
    return scene.mesh.add_face([_V(x0, 0), _V(x0 + 2, 0),
                                _V(x0 + 2, 2), _V(x0, 2)])


def _enter(vp):
    vp.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return,
                               Qt.NoModifier, "\r"))


def _edit_action(win, text):
    for act in win.menuBar().actions():
        if act.menu() is not None and act.text() == "Edit":
            for sub in act.menu().actions():
                if sub.text() == text:
                    return sub
    raise AssertionError(f"no {text!r} in the Edit menu")


def test_nothing_to_repeat_on_a_new_document(win):
    assert not win._repeat_action.isEnabled()
    assert win.repeat_last_command() is False
    assert win.viewport.active_tool is win._tools["select"]


def test_shift_r_is_the_only_owner_of_its_key(win):
    """An ambiguous shortcut fires NEITHER action (the F2 lesson)."""
    owners = [a for a in win.findChildren(QAction)
              if a.shortcut().toString() == "Shift+R"]
    assert owners == [win._repeat_action]


def test_a_tool_comes_back_after_space(win):
    win._activate_tool("line")
    win._activate_tool("select")          # Space
    assert win._repeat_action.text() == "Repeat Line"
    assert win.repeat_last_command()
    assert win.viewport.active_tool is win._tools["line"]
    assert win._tool_actions["line"].isChecked()


def test_select_and_context_tools_are_not_remembered(win):
    win._activate_tool("rectangle")
    win._activate_tool("select")
    win._activate_tool("texture_position")
    win._activate_tool("select")
    win.repeat_last_command()
    assert win.viewport.active_tool is win._tools["rectangle"]


def test_a_command_runs_again_on_the_new_selection(win):
    """The point of it: reverse this face, select the next, repeat."""
    scene = win.viewport.scene
    a, b = _face(scene), _face(scene, 5.0)
    na, nb = a.normal(), b.normal()
    scene.select([a])
    _edit_action(win, "Reverse Faces").trigger()   # a menu passes `checked`
    assert QVector3D.dotProduct(a.normal(), na) < -0.99
    assert win._repeat_action.text() == "Repeat Reverse Faces"
    scene.select([b])
    assert win.repeat_last_command()
    assert QVector3D.dotProduct(b.normal(), nb) < -0.99
    assert QVector3D.dotProduct(a.normal(), na) < -0.99, "a is left alone"


def test_the_right_click_entry_is_repeatable_after_its_menu_dies(win,
                                                                  monkeypatch):
    """The context menu builds its QActions afresh; what is remembered is
    the command, so the repeat outlives that menu."""
    import views.main_window as mw

    opened = []

    class _Menu(QMenu):
        def exec(self, *args, **kwargs):     # noqa: A003 - Qt's name
            opened.append(self)

    monkeypatch.setattr(mw, "QMenu", _Menu)
    scene = win.viewport.scene
    a, b = _face(scene), _face(scene, 5.0)
    nb = b.normal()
    scene.select([a])
    win.show_viewport_context_menu(QPoint(0, 0))
    entry = next(x for x in opened[0].actions() if x.text() == "Reverse Faces")
    entry.trigger()
    opened[0].deleteLater()
    QApplication.processEvents()
    scene.select([b])
    win.repeat_last_command()
    assert QVector3D.dotProduct(b.normal(), nb) < -0.99


def test_intersect_repeats_with_the_same_mode(win, monkeypatch):
    import core.intersect as inter
    seen = []
    monkeypatch.setattr(inter, "segments_for",
                        lambda scene, mode: seen.append(mode) or [])
    scene = win.viewport.scene
    scene.select([_face(scene)])
    win._on_intersect_faces(inter.WITH_SELECTION)
    win.repeat_last_command()
    assert seen == [inter.WITH_SELECTION, inter.WITH_SELECTION]


def test_the_last_one_wins_tool_or_command(win):
    scene = win.viewport.scene
    scene.select([_face(scene)])
    win._activate_tool("move")
    win._activate_tool("select")
    win._on_reverse_faces()
    assert win._repeat_action.text() == "Repeat Reverse Faces"
    win._activate_tool("circle")
    assert win._repeat_action.text() == "Repeat Circle"


def test_enter_on_select_is_not_a_repeat(win):
    """Rhino and AutoCAD repeat on Enter; here it was tried and taken out."""
    scene = win.viewport.scene
    face = _face(scene)
    normal = face.normal()
    scene.select([face])
    win._on_reverse_faces()
    win._activate_tool("line")
    win._activate_tool("select")
    _enter(win.viewport)
    assert win.viewport.active_tool is win._tools["select"]
    assert QVector3D.dotProduct(face.normal(), normal) < -0.99,         "the reversed face was not reversed back"


# ---- Where you see it: the right-click menu and the status bar ------------

def _context_entries(win, monkeypatch):
    import views.main_window as mw
    opened = []

    class _Menu(QMenu):
        def exec(self, *args, **kwargs):     # noqa: A003 - Qt's name
            opened.append(self)

    monkeypatch.setattr(mw, "QMenu", _Menu)
    win.show_viewport_context_menu(QPoint(0, 0))
    return opened[0].actions()


def test_right_click_offers_the_repeat_first(win, monkeypatch):
    scene = win.viewport.scene
    a, b = _face(scene), _face(scene, 5.0)
    nb = b.normal()
    scene.select([a])
    win._on_reverse_faces()
    scene.select([b])
    first = _context_entries(win, monkeypatch)[0]
    assert first.text() == "Repeat Reverse Faces"
    first.trigger()
    assert QVector3D.dotProduct(b.normal(), nb) < -0.99


def test_right_click_has_no_repeat_before_anything_was_done(win, monkeypatch):
    texts = [a.text() for a in _context_entries(win, monkeypatch)]
    assert not any(t.startswith("Repeat") for t in texts)


# TODO(MAC-04): Baseline macOS shows the Shift symbol in the repeat hint.
# See docs/macos-test-failures.md; confirmed on the baseline commit, not fixed yet.
def test_the_status_bar_says_what_would_repeat_only_in_select(win):
    lab = win._repeat_label
    assert lab.isHidden(), "nothing to repeat yet"
    win._activate_tool("line")
    assert lab.isHidden(), "inside a tool the corner is the VCB's"
    win._activate_tool("select")
    assert not lab.isHidden()
    assert lab.text() == "Shift+R: repeat Line"


def test_the_shortcut_editor_keeps_one_key_for_it_whatever_it_says(win):
    """The shortcut editor (#138) files an action under its object name or
    its English text — and this one's text changes with every command."""
    from views.shortcuts import action_key
    before = action_key(win._repeat_action)
    win._activate_tool("line")
    assert win._repeat_action.text() == "Repeat Line"
    assert action_key(win._repeat_action) == before == "repeat_last_command"


def test_shift_r_is_not_a_key_the_viewport_reads_itself():
    from PySide6.QtGui import QKeySequence
    from views.shortcuts import reserved_reason
    assert reserved_reason(QKeySequence("Shift+R")) is None


# TODO(MAC-05): Baseline macOS shows native symbols for the customized repeat shortcut.
# See docs/macos-test-failures.md; confirmed on the baseline commit, not fixed yet.
def test_the_hint_names_the_keys_it_has_now(win):
    """Remapped in the shortcut editor (#138), the hint follows; with no
    key at all it still names what would repeat."""
    from PySide6.QtGui import QKeySequence
    win._activate_tool("line")
    win._activate_tool("select")
    win._repeat_action.setShortcut(QKeySequence("Ctrl+Shift+Y"))
    win._refresh_repeat_hint()
    assert win._repeat_label.text() == "Ctrl+Shift+Y: repeat Line"
    win._repeat_action.setShortcut(QKeySequence())
    win._refresh_repeat_hint()
    assert win._repeat_label.text() == "Repeat Line"
