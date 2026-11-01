# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Several projects open in one window, each in its own tab (#1066).

Each tab is a project with its own viewport — scene, undo history,
camera, saved state, auto-save slot — and ``window.viewport`` answers the
one in front. These tests drive the real window: open in a tab, reuse an
untouched one, jump to a file already open, switch, close, quit, auto-save
and recovery, the extension hooks, copy and paste between projects, and
that a closed project lets its memory go."""
from __future__ import annotations

import gc
import os
import weakref

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from formats import igz as igz_format  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _settle(ms: int = 0) -> None:
    """Run the event loop — deleteLater included, which processEvents()
    alone never runs."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _face(scene, z=0.0, size=2.0):
    scene.mesh.add_face([V(0, 0, z), V(size, 0, z), V(size, size, z),
                         V(0, size, z)])
    scene.version += 1


def _igz(tmp_path, name, z=0.0):
    from core.scene import Scene
    s = Scene()
    _face(s, z)
    path = tmp_path / name
    igz_format.save_scene(s, path)
    return path


def _edit(win, z=5.0):
    """One real, undoable edit in the project in front."""
    from core.history import AddEdgeCommand
    win.viewport.history.execute(AddEdgeCommand(V(0, 0, z), V(1, 0, z)))
    win.viewport.notify_scene_changed()


def _clean_all(win):
    for d in win.documents():
        d.saved_content = d.viewport.scene.content_version


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    _clean_all(w)
    w.close()


# ---- opening -------------------------------------------------------------
def test_one_tab_at_start_and_the_bar_is_shown(win):
    assert len(win.documents()) == 1
    assert win._project_tabs.count() == 1
    assert not win._project_tabs.isHidden()
    assert win.viewport is win.active_document().viewport
    assert win._project_tabs.tabs.tabText(0) == "Untitled"


def test_an_untouched_tab_is_reused_by_open(win, tmp_path):
    first = win.viewport
    assert win.open_path(_igz(tmp_path, "a.igz"))
    assert len(win.documents()) == 1
    assert win.viewport is first
    assert win._project_tabs.tabs.tabText(0) == "a.igz"


def test_open_comes_in_a_new_tab_when_the_front_one_has_work(win, tmp_path):
    _edit(win)
    mine = win.active_document()
    path = _igz(tmp_path, "b.igz", z=3.0)
    assert win.open_path(path)
    assert len(win.documents()) == 2
    assert win.active_document() is not mine
    assert win._current_path == path
    # The unsaved work is still there, in its tab, still unsaved.
    assert mine.path is None and win._doc_is_dirty(mine)
    assert len(mine.viewport.history.undo_stack) == 1
    # The new tab sits right of the one it was opened from.
    assert win.documents() == [mine, win.active_document()]


def test_a_file_already_open_brings_its_tab_back(win, tmp_path):
    a = _igz(tmp_path, "a.igz")
    b = _igz(tmp_path, "b.igz")
    win.open_path(a)
    doc_a = win.active_document()
    win.open_path(b)
    assert len(win.documents()) == 2
    # Edited meanwhile: jumping back must not reread it from disk.
    win.activate_document(doc_a)
    _edit(win)
    win.activate_document(win.documents()[1])
    assert win.open_path(a)
    assert win.active_document() is doc_a
    assert len(win.documents()) == 2
    assert win._doc_is_dirty(doc_a)


def test_a_failed_open_leaves_no_empty_tab_behind(win, tmp_path, monkeypatch):
    _edit(win)
    mine = win.active_document()
    bad = tmp_path / "bad.igz"
    bad.write_text("not a document")
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    assert not win.open_path(bad)
    assert win.documents() == [mine]
    assert win.active_document() is mine


def test_file_new_opens_a_tab_and_reuses_an_untouched_one(win):
    win._on_new()                       # untouched: started over in place
    assert len(win.documents()) == 1
    _edit(win)
    win._on_new()
    assert len(win.documents()) == 2
    assert win._project_tabs.tabs.tabText(1) == "Untitled"
    assert not win._is_dirty()
    # A new project starts with its own scale figure, clean.
    assert win.viewport.scene.groups


def test_the_plus_button_makes_a_project(win):
    _edit(win)
    win._project_tabs.plus.click()
    assert len(win.documents()) == 2


# ---- switching -----------------------------------------------------------
def test_each_tab_keeps_its_own_undo_and_camera(win, tmp_path):
    _edit(win, z=1.0)
    a = win.active_document()
    a.viewport.camera.distance = 77.0
    win._on_new()
    b = win.active_document()
    _edit(win, z=2.0)
    _edit(win, z=3.0)
    assert len(b.viewport.history.undo_stack) == 2
    win._on_undo()
    assert len(b.viewport.history.undo_stack) == 1
    assert len(a.viewport.history.undo_stack) == 1   # untouched by B's undo
    win.activate_document(a)
    assert win.viewport.camera.distance == 77.0
    win._on_undo()
    assert not a.viewport.history.undo_stack
    assert len(b.viewport.history.undo_stack) == 1


def test_switching_drops_the_tool_and_leaves_the_group(win):
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "box")
    win.viewport.scene.groups.append(g)
    win.viewport.scene.version += 1
    win._saved_version = -1                       # some work: not reusable
    a = win.active_document()
    win.viewport.begin_group_edit(g)
    assert win.viewport.scene.edit_group is g
    win._activate_tool("line")
    win._on_new()
    assert a.viewport.active_tool is None
    assert a.viewport.scene.edit_group is None
    assert win.viewport.active_tool is win._tools["select"]
    win.activate_document(a)
    assert win.viewport.active_tool is win._tools["select"]


def test_the_title_and_the_tab_mark_follow_the_front(win, tmp_path):
    path = _igz(tmp_path, "casa.igz")
    win.open_path(path)
    assert win.windowTitle() == "IngeTrazo — casa.igz"
    _edit(win)
    assert win.windowTitle().endswith(" *")
    assert win._project_tabs.tabs.tabText(0) == "casa.igz •"
    win._on_new()
    assert win.windowTitle() == "IngeTrazo — Untitled"
    # The background tab still says it has unsaved changes.
    assert win._project_tabs.tabs.tabText(0) == "casa.igz •"


def test_ctrl_tab_walks_the_projects_or_the_sheets(win, monkeypatch):
    sheets = []
    monkeypatch.setattr(win, "_to_sheets", lambda: sheets.append(1))
    win._ctrl_tab(1)                    # one project: to the sheets (#91)
    assert sheets == [1]
    _edit(win)
    a = win.active_document()
    win._on_new()
    b = win.active_document()
    win._ctrl_tab(1)
    assert win.active_document() is a
    win._ctrl_tab(-1)
    assert win.active_document() is b
    assert sheets == [1]


def test_the_new_shortcuts_do_not_clash(win):
    from PySide6.QtGui import QAction
    from PySide6.QtGui import QKeySequence
    keys = {}
    for act in win.findChildren(QAction):
        for seq in act.shortcuts():
            text = seq.toString()
            if text:
                keys.setdefault(text, []).append(act.text())
    for key in ("Ctrl+W", "Ctrl+PgDown", "Ctrl+PgUp"):
        owners = keys.get(QKeySequence(key).toString(), [])
        assert len(owners) == 1, (key, owners)


def test_panels_forget_what_they_drew_for_the_other_project(win):
    """Two projects can stand at the same content version: a panel that
    skips its refresh on an unchanged version would keep showing the
    other project's rows."""
    _edit(win)
    panel = win.tray.components
    panel._in_model_cv = win.viewport.scene.content_version
    win._on_new()
    assert panel._in_model_cv is None or \
        panel._in_model_cv == win.viewport.scene.content_version
    assert win.project_browser.outliner._scene() is win.viewport.scene


def test_materials_let_go_of_the_meshes_of_the_project_left(win):
    """Materials remembers what each mesh wears; kept across a switch it
    held a closed project's whole geometry (2 722 meshes of the SPR)."""
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    win.viewport.scene.groups.append(Group(m, "box"))
    win.viewport.scene.version += 1
    win._saved_version = -1
    panel = win.tray.materials
    panel.refresh_in_model()
    assert any(hit[0] is m for hit in panel._worn_by_mesh.values())
    win._on_new()
    worn = panel._worn_by_mesh or {}
    assert not any(hit[0] is m for hit in worn.values())


def test_view_preferences_reach_the_tabs_behind(win):
    from views.preferences_dialog import PreferencesDialog
    _edit(win)
    a = win.active_document()
    win._on_new()
    dlg = PreferencesDialog(win)
    dlg._invert.setChecked(not a.viewport._invert_wheel)
    want = dlg._invert.isChecked()
    dlg.accept()
    assert a.viewport._invert_wheel == want
    assert win.viewport._invert_wheel == want


# ---- closing -------------------------------------------------------------
def test_closing_a_clean_tab_asks_nothing(win, tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(win, "_confirm_discard",
                        lambda prompt: asked.append(prompt) or True)
    _edit(win)
    win._saved_version = win.viewport.scene.version
    win._on_new()
    assert win.close_document()
    assert asked == []
    assert len(win.documents()) == 1


def test_closing_asks_only_about_that_project(win, monkeypatch):
    _edit(win)
    a = win.active_document()
    win._on_new()
    _edit(win)
    b = win.active_document()
    asked = []
    monkeypatch.setattr(win, "_confirm_discard",
                        lambda prompt: asked.append(prompt) or False)
    assert not win.close_document(b)              # cancelled: stays
    assert len(asked) == 1 and b in win.documents()
    monkeypatch.setattr(win, "_confirm_discard",
                        lambda prompt: asked.append(prompt) or True)
    assert win.close_document(b)
    assert len(asked) == 2
    assert win.documents() == [a]
    assert win.active_document() is a
    assert win._doc_is_dirty(a)                   # A's work untouched


def test_closing_the_last_tab_leaves_an_empty_project(win, monkeypatch):
    monkeypatch.setattr(win, "_confirm_discard", lambda prompt: True)
    _edit(win)
    old = win.active_document()
    assert win.close_document()
    assert len(win.documents()) == 1
    assert win.active_document() is not old
    assert win._doc_is_blank()


def test_middle_click_closes_a_tab(win):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    _edit(win)
    win._saved_version = win.viewport.scene.version
    win._on_new()
    bar = win._project_tabs.tabs
    win.show()
    _settle()
    centre = QPointF(bar.tabRect(1).center())
    ev = QMouseEvent(QMouseEvent.MouseButtonRelease, centre, centre,
                     Qt.MiddleButton, Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(bar, ev)
    _settle()
    assert len(win.documents()) == 1
    win.hide()


def test_quitting_asks_once_for_every_modified_project(win, monkeypatch):
    _edit(win)
    win._on_new()
    _edit(win)
    win._on_new()                                  # a clean third one
    boxes = []

    def answer(box):
        boxes.append(box.text())
        return QMessageBox.Cancel
    monkeypatch.setattr(QMessageBox, "exec", answer)
    assert not win._confirm_quit()
    assert len(boxes) == 1
    assert boxes[0].count("Untitled") == 2
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda box: QMessageBox.Discard)
    assert win._confirm_quit()


def test_a_closed_project_lets_its_memory_go(win, tmp_path, monkeypatch):
    monkeypatch.setattr(win, "_confirm_discard", lambda prompt: True)
    _edit(win)
    win.open_path(_igz(tmp_path, "big.igz"))
    doc = win.active_document()
    scene = weakref.ref(doc.viewport.scene)
    vp = weakref.ref(doc.viewport)
    win.close_document(doc)
    del doc
    _settle()
    gc.collect()
    _settle()
    gc.collect()
    assert vp() is None, "the closed viewport is still alive"
    assert scene() is None, "the closed scene is still alive"


def test_closing_the_first_tab_lets_it_go_too(win, tmp_path):
    """The bundled panels were built with the first tab's viewport: they
    must not keep it (and its whole project) alive once it is closed."""
    win.open_path(_igz(tmp_path, "first.igz"))
    vp = weakref.ref(win.viewport)
    scene = weakref.ref(win.viewport.scene)
    win.close_document(ask=False)
    _settle()
    gc.collect()
    _settle()
    gc.collect()
    assert vp() is None, "the first viewport is still alive"
    assert scene() is None


def test_closing_a_tab_hands_its_memory_back(win, tmp_path, monkeypatch):
    """The system monitor saw closing the SPR's tab drop only ~1 GB of
    ~5.8 GB: its scene was freed only by the cycle collector, whenever
    that ran, and glibc kept the freed heap anyway. Once the viewport is
    gone the window collects and trims by itself — and takes no hover
    picture of the closing tab (a whole frame drawn again: seconds and
    ~650 MB of draw caches on the SPR)."""
    from core import malloc_arenas
    trims = []
    monkeypatch.setattr(malloc_arenas, "trim", lambda: trims.append(1))
    pictured = []
    monkeypatch.setattr(win, "_tab_thumbnail",
                        lambda vp: pictured.append(vp))
    win.open_path(_igz(tmp_path, "a.igz"))
    win.open_path(_igz(tmp_path, "b.igz"))
    closing = win.viewport
    scene = weakref.ref(closing.scene)
    pictured.clear()                    # a's, taken as b's tab opened
    gc.disable()                        # only the window may collect
    try:
        win.close_document(ask=False)
        del closing
        assert not pictured, "a picture was taken of the closing tab"
        _settle(win.RECLAIM_DELAY_MS + 300)
        assert scene() is None, "the closed project is still in memory"
        assert trims, "the freed heap was not handed back"
    finally:
        gc.enable()


# ---- auto-save and recovery ---------------------------------------------
def test_each_untitled_project_autosaves_to_its_own_slot(win):
    from core import autosave
    _edit(win, z=1.0)
    a = win.active_document()
    win._on_new()
    _edit(win, z=2.0)
    b = win.active_document()
    assert a.untitled_no != b.untitled_no
    try:
        win._on_autosave_tick()
        slot_a = autosave.pending(None, untitled=a.untitled_no)
        slot_b = autosave.pending(None, untitled=b.untitled_no)
        assert slot_a and slot_b and slot_a != slot_b
        # Each slot holds its own project (the tab behind too).
        from core.scene import Scene
        for slot, z in ((slot_a, 1.0), (slot_b, 2.0)):
            s = Scene()
            igz_format.load_into(s, slot)
            assert any(abs(e.v1.position.z() - z) < 1e-6
                       for e in s.mesh.edges)
        # Closing a tab retires only its slot.
        _clean_all(win)
        win.close_document(b)
        assert autosave.pending(None, untitled=b.untitled_no) is None
        assert autosave.pending(None, untitled=a.untitled_no) is not None
    finally:
        for n in (a.untitled_no, b.untitled_no):
            autosave.clear(None, untitled=n)


def test_every_untitled_slot_is_offered_back(win, monkeypatch, tmp_path):
    from core import autosave
    from core.scene import Scene
    for n, z in ((1, 1.0), (2, 2.0)):
        s = Scene()
        _face(s, z)
        igz_format.save_scene(s, autosave.slot_for(None, untitled=n))
    try:
        monkeypatch.setattr(QMessageBox, "question",
                            lambda *a, **k: QMessageBox.Yes)
        win._offer_untitled_recovery()
        docs = win.documents()
        assert len(docs) == 2
        zs = sorted(next(iter(d.viewport.scene.mesh.faces)).vertices[0].z()
                    for d in docs)
        assert zs == [1.0, 2.0]
        assert sorted(d.untitled_no for d in docs) == [1, 2]
        assert all(win._doc_is_dirty(d) for d in docs)
    finally:
        for n in (1, 2):
            autosave.clear(None, untitled=n)


def test_the_classic_slot_names_stay(tmp_path):
    from core import autosave
    assert autosave.slot_for(None).name == "untitled.igz"
    assert autosave.slot_for(None, untitled=1).name == "untitled.igz"
    assert autosave.slot_for(None, untitled=3).name == "untitled-3.igz"


# ---- extensions ----------------------------------------------------------
def test_extension_hooks_follow_the_tabs(win, tmp_path, monkeypatch):
    from views.extension_api import ExtensionApp
    app = ExtensionApp(win, "probe")
    changed, closed = [], []
    app.on_document_changed(lambda: changed.append(app.scene))
    app.on_document_closed(lambda scene: closed.append(scene))
    drawn = []
    app.add_overlay(lambda vp, p: drawn.append(vp))
    _edit(win)
    a_scene = win.viewport.scene
    win._on_new()
    b_scene = win.viewport.scene
    assert changed and changed[-1] is b_scene    # the switch is a change
    assert app.scene is b_scene and app.viewport is win.viewport
    # Registered once, the overlay is in the new tab's viewport too.
    assert win.viewport._ext_overlays is win.documents()[0].viewport._ext_overlays
    n = len(changed)
    _edit(win)                                    # an edit in the new tab
    assert len(changed) > n
    monkeypatch.setattr(win, "_confirm_discard", lambda prompt: True)
    win.close_document(win.active_document())
    assert closed == [b_scene]
    assert app.scene is a_scene


def test_the_ai_bridge_acts_on_the_tab_in_front(win):
    from plugins.ai_bridge import BridgeSection
    section = BridgeSection(win.viewport)
    first = win.viewport
    _edit(win)
    win._on_new()
    assert section._viewport is win.viewport
    assert section._viewport is not first


def test_a_workspace_holds_the_tabs(win):
    from core.history import History
    from core.scene import Scene

    class _Ws:
        def __init__(self):
            self.scene = Scene()
            self.history = History(self.scene)

        def title(self):
            return "job"

        def is_dirty(self):
            return False

        def save(self):
            pass

        def save_as(self):
            pass

        def confirm_leave(self):
            return True

    _edit(win)
    a = win.active_document()
    win._on_new()
    win.enter_workspace(_Ws())
    assert not win._project_tabs.isEnabled()
    win.activate_document(a)                      # refused while it is shown
    assert win.active_document() is not a
    assert win.leave_workspace()
    assert win._project_tabs.isEnabled()


# ---- copy and paste between projects --------------------------------------
def test_copy_in_one_project_paste_in_another(win):
    from core.group import Group
    from core.mesh import Mesh
    vp = win.viewport
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "Banca")
    vp.scene.groups.append(g)
    vp.scene.version += 1
    win._saved_version = -1
    vp.scene.selection.clear()
    vp.scene.selection.add(g)
    vp.copy_selection()
    a_clip = vp.clipboard
    assert a_clip and a_clip["groups"]
    win._on_new()
    b = win.viewport
    assert b.clipboard is None
    before = len(b.scene.groups)
    win._sync_foreign_clipboard()
    clip = b.clipboard
    assert clip and clip is not a_clip
    # Through the document encoding: the pasting project's own copy, no
    # object shared with the other document.
    assert clip["groups"][0] is not a_clip["groups"][0]
    assert clip["groups"][0].mesh is not g.mesh
    from tools.paste import PasteTool
    assert PasteTool.in_place(b)
    assert len(b.scene.groups) == before + 1
    assert any(gr.name == "Banca" for gr in b.scene.groups)
    assert win.documents()[0].viewport.scene.groups.count(g) == 1
    # A second paste reuses the adopted copy, no new decoding.
    win._sync_foreign_clipboard()
    assert b.clipboard is clip


def test_hovering_a_tab_behind_shows_its_picture(win):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QHelpEvent, QImage
    _edit(win)
    a = win.active_document()
    win._on_new()
    img = QImage(280, 160, QImage.Format_RGB32)
    img.fill(QColor(200, 30, 30))
    a.thumbnail = img
    win.show()
    _settle()
    bar = win._project_tabs
    tabs = bar.tabs
    for i, wanted in ((0, True), (1, False)):     # behind / in front
        centre = tabs.tabRect(i).center()
        ev = QHelpEvent(QHelpEvent.ToolTip, centre,
                        tabs.mapToGlobal(centre))
        QApplication.sendEvent(tabs, ev)
        shown = bar._preview is not None and bar._preview.isVisible()
        assert shown is wanted
    bar._hide_preview()
    win.hide()
