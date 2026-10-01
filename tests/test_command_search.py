# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Command search (F3): a box that filters the window's own actions and
runs the one picked — Blender's F3, Rhino's prompt."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication([])

import core.extensions as extensions                              # noqa: E402
from core import string_search as ss                             # noqa: E402
from views import command_search as cs                           # noqa: E402


@pytest.fixture
def ventana(tmp_path, monkeypatch):
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    QSettings().remove("command_search")
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    yield win
    QSettings().remove("command_search")
    win._saved_version = win.viewport.scene.version   # no "save?" modal
    win.close()


def _names(win, query):
    return [c.name for c in cs.search(win, query)]


def _box(win, text="", scope=""):
    box = cs.open_search(win, text, scope)
    QApplication.processEvents()
    return box


def _shown(box):
    return [c.name for c in box._model.rows]


def _type(box, text):
    QTest.keyClicks(box._edit, text)
    QApplication.processEvents()


# ---- the matching (Blender's), without a window ------------------------------
def _rank(query, *labels):
    entries = [(label, [ss.Item(label.split(" ▸ "))]) for label in labels]
    return ss.rank(query, entries)


def test_every_word_typed_must_be_found():
    assert _rank("orient", "Orient Faces") == ["Orient Faces"]
    assert _rank("faces orient", "Orient Faces") == ["Orient Faces"]
    assert _rank("orient walls", "Orient Faces") == []


def test_accents_and_case_do_not_matter():
    assert _rank("rotacion", "Rotación") == ["Rotación"]
    assert _rank("ROTACIÓN", "rotacion") == ["rotacion"]


def test_initials_find_a_command():
    """Blender's «seboulo» → Select Boundary Loop."""
    assert _rank("rf", "Orient Faces", "Reverse Faces")[0] == "Reverse Faces"
    assert _rank("seboulo", "Select Boundary Loop") == [
        "Select Boundary Loop"]


def test_a_typing_error_is_forgiven():
    assert _rank("orinet", "Orient Faces", "Reverse Faces") == [
        "Orient Faces"]
    assert _rank("fcaes", "Orient Faces") == ["Orient Faces"]


def test_a_word_beginning_beats_initials_and_typos():
    assert _rank("rev", "Remove Everything", "Reverse Faces")[0] ==         "Reverse Faces"


def test_the_name_counts_more_than_the_path():
    assert _rank("faces", "Faces ▸ Something", "Edit ▸ Orient Faces")[0]         == "Edit ▸ Orient Faces"


def test_the_shortest_name_comes_first_among_equals():
    assert _rank("line", "Line Style", "Line")[0] == "Line"


def test_words_out_of_order_rank_lower():
    assert _rank("faces orient", "Faces Orient", "Orient Faces")[0] ==         "Faces Orient"


def test_recent_ones_lead_only_with_one_letter_or_none():
    entries = [(n, [ss.Item([n])]) for n in ("Copy", "Cut", "Cutter")]
    recent = {"Cutter": 2}.get
    assert ss.rank("", entries, lambda n: recent(n, -1))[0] == "Cutter"
    assert ss.rank("c", entries, lambda n: recent(n, -1))[0] == "Cutter"
    assert ss.rank("cut", entries, lambda n: recent(n, -1))[0] == "Cut"


def test_damerau_levenshtein():
    assert ss.damerau_levenshtein("abc", "abc") == 0
    assert ss.damerau_levenshtein("abc", "acb") == 1      # a swap
    assert ss.damerau_levenshtein("kitten", "sitting") == 3


# ---- the window's commands ------------------------------------------------------
def test_the_menus_tools_and_trays_are_all_there(ventana):
    names = _names(ventana, "")
    for expected in ("Orient Faces", "Line", "Push / Pull", "Preferences…",
                     "Properties", "Show all panels"):     # Window ▸ Panels
        assert expected in names
    assert "Search commands…" not in names     # not itself


def test_a_command_knows_its_menu_path(ventana):
    cmd = next(c for c in cs.search(ventana, "unhide all"))
    assert cmd.path == "Edit ▸ Unhide"
    assert cmd.name == "All"


def test_found_in_english_while_the_menus_speak_spanish(ventana):
    from core.i18n import set_language
    from views.main_window import MainWindow
    set_language("es")
    try:
        win = MainWindow()
        try:
            assert _names(win, "orient faces")[0] == "Orientar caras"
            assert _names(win, "orientar")[0] == "Orientar caras"
            assert _names(win, "preferences")[0] == "Preferencias…"
            # The menu path, too, in either language, accents or not.
            assert "Todo" in _names(win, "edit all")
            assert "Todo" in _names(win, "edicion mostrar todo")
        finally:
            win._saved_version = win.viewport.scene.version
            win.close()
    finally:
        set_language("en")


def test_a_plugin_action_is_found_without_registering_anything(ventana):
    act = QAction("Frobnicate the walls", ventana)
    ventana.addAction(act)
    assert _names(ventana, "frobnic") == ["Frobnicate the walls"]


def test_a_hidden_action_is_not_offered(ventana):
    act = QAction("Secret squirrel", ventana)
    act.setVisible(False)
    ventana.addAction(act)
    assert _names(ventana, "squirrel") == []


# ---- the box ----------------------------------------------------------------------
def test_f3_opens_the_box(ventana):
    QTest.keyClick(ventana.viewport, Qt.Key_F1)      # the warm-up keystroke
    QApplication.processEvents()
    QTest.keyClick(ventana.viewport, Qt.Key_F3)
    QApplication.processEvents()
    box = getattr(ventana, "_command_search", None)
    assert box is not None and box.isVisible()
    box.close()


def test_enter_runs_the_first_match_and_remembers_it(ventana):
    fired = []
    act = QAction("Frobnicate the walls", ventana)
    act.triggered.connect(lambda: fired.append(1))
    ventana.addAction(act)
    box = _box(ventana)
    _type(box, "frobnicate")
    QTest.keyClick(box._edit, Qt.Key_Return)
    QApplication.processEvents()                     # the deferred trigger
    assert fired == [1]
    assert not box.isVisible()
    assert _names(ventana, "")[0] == "Frobnicate the walls"   # recent first


def test_arrows_move_and_skip_disabled_commands(ventana):
    fired = []
    for text, enabled in (("Zyx alpha", True), ("Zyx beta", False),
                          ("Zyx gamma", True)):
        act = QAction(text, ventana)
        act.setEnabled(enabled)
        act.triggered.connect(lambda _c=False, t=text: fired.append(t))
        ventana.addAction(act)
    box = _box(ventana)
    _type(box, "zyx")
    QTest.keyClick(box._edit, Qt.Key_Down)
    QTest.keyClick(box._edit, Qt.Key_Return)
    QApplication.processEvents()
    assert fired == ["Zyx gamma"]


def test_esc_closes_without_running_anything(ventana):
    fired = []
    act = QAction("Frobnicate the walls", ventana)
    act.triggered.connect(lambda: fired.append(1))
    ventana.addAction(act)
    box = _box(ventana)
    _type(box, "frob")
    QTest.keyClick(box._edit, Qt.Key_Escape)
    QApplication.processEvents()
    assert fired == [] and not box.isVisible()


def test_no_results_says_so(ventana):
    box = _box(ventana)
    _type(box, "xqzwv")
    assert box._model.rows == [] and not box._empty.isHidden()
    box.close()


def test_one_line_per_command_path_first(ventana):
    """Blender's layout: faded path, then the name; ten rows at a time."""
    box = _box(ventana)
    _type(box, "orient faces")
    index = box._model.index(0, 0)
    assert box._model.data(index, Qt.DisplayRole) == "Orient Faces"
    assert box._model.data(index, cs._PATH_ROLE) == "Edit"
    row_h = box._list.sizeHintForRow(0)
    assert box._list.height() >= row_h * cs.VISIBLE_ROWS
    box.close()


def test_a_menu_scope_searches_only_that_menu(ventana):
    box = _box(ventana, "a", "Edit ▸ Unhide")
    assert set(_shown(box)) <= {"All", "Selected", "Last"}
    assert "All" in _shown(box)
    assert box._edit.text() == "a" and not box._scope_label.isHidden()
    # Backspace in the empty box widens the search to everything.
    box._edit.clear()
    QTest.keyClick(box._edit, Qt.Key_Backspace)
    assert box._scope == "" and box._scope_label.isHidden()
    assert "Orient Faces" in _shown(box)
    box.close()


def test_a_letter_typed_in_an_open_menu_searches_it(ventana):
    edit = next(a.menu() for a in ventana.menuBar().actions()
                if a.menu() is not None and a.menu().title() == "Edit")
    edit.popup(ventana.mapToGlobal(ventana.rect().center()))
    QApplication.processEvents()
    QTest.keyClick(edit, Qt.Key_O)
    QApplication.processEvents()
    box = ventana._command_search
    assert box.isVisible() and not edit.isVisible()
    assert box._scope == "Edit" and box._edit.text() == "o"
    assert _shown(box)[0] == "Orient Faces"
    box.close()


def test_change_shortcut_opens_preferences_on_that_command(ventana,
                                                           monkeypatch):
    opened = []
    monkeypatch.setattr(ventana, "open_preferences",
                        lambda shortcut_of=None: opened.append(shortcut_of))
    box = _box(ventana)
    _type(box, "orient faces")
    act = box._model.rows[0].action
    box.change_shortcut(act)
    QApplication.processEvents()
    assert opened == [act] and not box.isVisible()


def test_preferences_open_on_the_picked_shortcut(ventana):
    from views.preferences_dialog import PreferencesDialog
    from views.shortcuts import collect_actions
    act = next(a for a in collect_actions(ventana)
               if a.text() == "Orient Faces")
    dlg = PreferencesDialog(ventana)
    try:
        dlg.show_shortcut_of(act)
        assert dlg._tabs.currentWidget() is dlg._shortcuts
        assert dlg._shortcuts._current()[1] is act
    finally:
        dlg.deleteLater()


# ---- where the box opens ------------------------------------------------------------
from PySide6.QtCore import QPoint, QRect, QSize                  # noqa: E402

_SCREEN = QRect(0, 0, 1920, 1040)
_WORK = QRect(300, 100, 1300, 800)        # between the toolbars and trays
_BOX = QSize(560, 330)


def _fit(x, y, work=_WORK, screen=_SCREEN, size=_BOX):
    return cs.fit_box(QPoint(x, y), size, 30, work, screen)


def _inside(inner, outer):
    return outer.contains(inner)


def test_the_box_opens_under_the_mouse():
    r = _fit(900, 400)
    assert abs(r.center().x() - 900) <= 1
    assert r.top() == 400 - 15                  # its text field at the mouse
    assert _inside(r, _WORK)


def test_near_a_tray_it_moves_in_instead_of_covering_it():
    for x, y in ((1590, 400), (310, 400), (900, 890), (900, 105),
                 (1900, 1000), (5, 5)):         # also clicked on a tray
        r = _fit(x, y)
        assert _inside(r, _WORK), (x, y, r)
        assert r.size() == _BOX


def test_a_small_modelling_area_is_overflowed_keeping_the_size():
    small = QRect(300, 100, 400, 250)
    r = _fit(500, 200, work=small)
    assert r.size() == _BOX                     # not shrunk
    assert _inside(r, _SCREEN)
    # Only the axis that does not fit overflows: here both do not.
    wide = QRect(300, 100, 1300, 250)
    r = _fit(900, 200, work=wide)
    assert r.left() >= wide.left() and r.right() <= wide.right()
    assert r.size() == _BOX


def test_smaller_only_when_the_screen_cannot_hold_it():
    tiny_screen = QRect(0, 0, 500, 300)
    r = _fit(250, 150, work=QRect(0, 0, 500, 300), screen=tiny_screen)
    assert r.size() == QSize(500, 300)
    assert _inside(r, tiny_screen)


def test_the_real_box_is_fitted_to_the_modelling_area(ventana,
                                                      monkeypatch):
    """The area handed to fit_box is the viewport's, not the window's."""
    seen = []

    def spy(cursor, size, edit_h, work, screen):
        seen.append(work)
        return QRect(work.topLeft(), size)
    monkeypatch.setattr(cs, "fit_box", spy)
    QApplication.processEvents()                 # the layout settled first
    central = ventana.centralWidget()
    box = cs.open_search(ventana)
    assert central is ventana.viewport
    assert seen == [QRect(central.mapToGlobal(QPoint(0, 0)),
                          central.size())]
    assert box.geometry().topLeft() == seen[0].topLeft()
    box.close()


# ---- the sheet composer ----------------------------------------------------------
def _composer(win):
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL here: the composer renders its views")
    comp = win._ensure_composer()
    comp.show()
    QApplication.processEvents()
    return comp


def test_f3_works_in_the_composer_with_its_own_commands(ventana):
    comp = _composer(ventana)
    QTest.keyClick(comp, Qt.Key_F1)                  # the warm-up keystroke
    QTest.keyClick(comp, Qt.Key_F3)
    QApplication.processEvents()
    box = getattr(comp, "_command_search", None)
    assert box is not None and box.isVisible()
    names = [c.name for c in box._pool]
    assert "Chain dimension" in names and "Orient Faces" not in names
    box.close()
    comp.close()


def test_the_main_window_does_not_list_the_composers_commands(ventana):
    _composer(ventana).close()
    names = _names(ventana, "")
    assert "Chain dimension" not in names and "Ungroup" not in names
    assert "Orient Faces" in names


def test_a_composer_tool_has_a_short_name_and_its_sentence_as_tip(ventana):
    comp = _composer(ventana)
    act = comp._tool_actions["cota_cadena"]
    assert act.text() == "Chain dimension"
    assert act.toolTip().startswith("Chain dimensions the way AutoCAD")
    cmd = next(c for c in cs.commands(comp) if c.action is act)
    assert cmd.path == "Draw"                       # its toolbar
    comp.close()


def test_keys_written_in_the_name_go_to_their_column(ventana):
    comp = _composer(ventana)
    cmd = next(c for c in cs.commands(comp) if c.name == "Ungroup")
    assert cmd.keys == "Ctrl+Shift+G"
    # Brackets that are not keys stay in the name.
    for text in ("AI Bridge (MCP)", "Português (Brasil)", "IFC (BIM)…",
                 "Rebuild Faces (Planar)"):
        assert cs._keys_in(text) is None, text
    comp.close()


def test_the_composer_box_opens_over_the_sheet_not_the_panel(ventana,
                                                             monkeypatch):
    comp = _composer(ventana)
    seen = []
    monkeypatch.setattr(cs, "fit_box",
                        lambda c, size, e, work, screen: seen.append(work)
                        or QRect(work.topLeft(), size))
    QApplication.processEvents()
    area = comp.command_search_area()
    cs.open_search(comp).close()
    assert seen == [QRect(area.mapToGlobal(QPoint(0, 0)), area.size())]
    comp.close()


# ---- the explanation on hover (Blender's tooltip) --------------------------------
def test_the_description_drops_the_name_and_keys_a_tooltip_repeats():
    act = QAction("Orbit")
    act.setToolTip("Orbit  (O) — left-drag to rotate the view")
    assert cs.Command(act, "").tip == "Left-drag to rotate the view"
    act.setToolTip("Line  (L)")
    act.setText("Line")
    assert cs.Command(act, "").tip == ""
    act.setText("Pan")
    act.setToolTip("Pan the sheet (or drag with the middle button)")
    assert cs.Command(act, "").tip.startswith("Pan the sheet")


def test_the_tooltip_is_name_description_and_keys_wrapped(ventana):
    comp = _composer(ventana)
    cmd = next(c for c in cs.commands(comp) if c.name == "Chain dimension")
    tip = cs.tooltip_html(cmd)
    assert "<b>Chain dimension</b>" in tip
    assert "every click adds the next cota" in tip
    assert "<table width=" in tip                  # long: wrapped, not cut
    comp.close()


def test_a_command_run_from_f3_is_the_one_shift_r_repeats(ventana):
    """F3 and Repeat last command (#145) work together: what F3 ran is
    what Shift+R runs again."""
    box = _box(ventana)
    _type(box, "line")
    QTest.keyClick(box._edit, Qt.Key_Return)
    QApplication.processEvents()                     # the deferred trigger
    assert ventana.viewport.active_tool is ventana._tools["line"]
    ventana._activate_tool("select")
    assert ventana.repeat_last_command()
    assert ventana.viewport.active_tool is ventana._tools["line"]


# ---- opening fast (0.5.6: the shadow showed first, the list ~100 ms after) --
def test_an_unchanged_command_is_not_worked_out_again(ventana):
    first = {c.action: c for c in cs.commands(ventana)}
    again = {c.action: c for c in cs.commands(ventana)}
    assert first and all(again[a] is first[a] for a in first)


def test_a_command_that_changed_is_worked_out_again(ventana):
    act = QAction("Frobnicate the walls", ventana)
    ventana.addAction(act)
    before = next(c for c in cs.commands(ventana) if c.action is act)
    act.setText("Frobnicate the floors")
    after = next(c for c in cs.commands(ventana) if c.action is act)
    assert after is not before and after.name == "Frobnicate the floors"
    act.setShortcut("Ctrl+Alt+F")
    keyed = next(c for c in cs.commands(ventana) if c.action is act)
    assert keyed is not after and keyed.keys


def test_a_removed_action_leaves_the_cache(ventana):
    act = QAction("Frobnicate the walls", ventana)
    ventana.addAction(act)
    cs.commands(ventana)
    assert act in ventana._command_cache
    act.setParent(None)
    cs.commands(ventana)
    assert act not in ventana._command_cache


def test_warm_up_works_out_the_commands_before_f3(ventana):
    ventana._command_search = None
    ventana._command_cache = None
    cs.warm_up(ventana, 0)
    QTest.qWait(50)
    assert ventana._command_cache
    # the box itself waits for F3, as up to 0.5.6.1
    assert ventana._command_search is None


@pytest.mark.parametrize("platform", ["wayland", "wayland-egl", "xcb",
                                      "windows", "cocoa"])
def test_warm_up_makes_no_native_popup_ahead_of_f3(ventana, monkeypatch,
                                                   platform):
    """Made ahead of F3, the popup's native window left the main window
    flickering under GNOME's Wayland (a black band, the toolbar half over
    the menu bar; Marco, 30-09, bisected to the warm-up). Off everywhere
    until tried on each platform: the commands are still worked out, the
    native window waits for the first F3."""
    from PySide6.QtGui import QGuiApplication
    monkeypatch.setattr(QGuiApplication, "platformName",
                        staticmethod(lambda: platform))
    made = []
    monkeypatch.setattr(cs.CommandSearch, "winId",
                        lambda self: made.append(self) or 0)
    ventana._command_search = None
    ventana._command_cache = None
    cs.warm_up(ventana, 0)
    QTest.qWait(50)
    assert ventana._command_cache
    assert made == [] and ventana._command_search is None


def test_every_command_says_what_it_does(ventana):
    """Blender explains every command on hover; so do both windows."""
    comp = _composer(ventana)
    for win in (ventana, comp):
        bare = [c.name for c in cs.commands(win)
                if not c.tip and c.action.isEnabled()]
        assert bare == [], bare
    comp.close()


def test_a_toolbar_button_shows_its_description_under_name_and_keys(
        ventana):
    act = ventana._tool_actions["line"]
    name_keys, desc = act.toolTip().split("\n")
    assert name_keys == "Line  (L)"
    assert desc == act.statusTip() == \
        "Draw edges point by point; closing a loop makes a face."
    cmd = next(c for c in cs.commands(ventana) if c.action is act)
    assert cmd.tip == desc                         # F3 shows the same
