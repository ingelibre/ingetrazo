# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The extension API, version 2 (views/extension_api.py) — what a bigger
extension needs beyond Levels: a CAM job, say, which has its own panels,
draws toolpaths over the view, opens its own files and shows its own
document in place of the model.

- **Panels** keep a stable name, go back where the user left them, have a
  Window-menu entry, and asking twice returns the first.
- **Overlays** get the vectorised projection; one that raises is logged
  once and removed, and the painter state never leaks.
- **File openers**: a document of the extension's type goes to it from
  Open Recent, the command line or a double-click.
- **Workspaces**: the model is parked, not closed, and comes back with its
  geometry, undo steps, file, camera and saved state; meanwhile the File
  actions, the title, the prompts, autosave and the tool set belong to the
  workspace, and the viewport's id()-keyed caches are reset at each swap.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent, QColor, QImage, QPainter, QVector3D as V
from PySide6.QtWidgets import QApplication, QLabel

from core.history import History
from core.scene import Scene

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win(tmp_path, monkeypatch):
    path = tmp_path / "prefs.ini"
    import PySide6.QtCore as qc
    import views.main_window as mw
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory, raising=False)
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    _app.processEvents()
    yield w
    w._workspace = None                 # let the window close without prompts
    w._saved_version = w.viewport.scene.version
    w.close()


def _app_for(win, key="myext"):
    from views.extension_api import ExtensionApp
    return ExtensionApp(win, key)


def test_the_api_version_is_2():
    from views.extension_api import API_VERSION, ExtensionApp
    assert API_VERSION == 2 and ExtensionApp.api_version == 2


# ---- panels -----------------------------------------------------------------------

def test_panels_have_stable_names_a_menu_entry_and_are_added_once(win):
    app = _app_for(win)
    main = app.add_panel("My panel", QLabel("main"))
    extra = app.add_panel("Extra", QLabel("extra"), name="extra")
    _app.processEvents()
    assert main.objectName() == "extension_myext"
    assert extra.objectName() == "extension_myext_extra"
    assert app.add_panel("Again", QLabel("ignored")) is main
    assert set(win.extension_panels()) == {"extension_myext", "extension_myext_extra"}
    # Tabbed with the trays, not squeezed beside them.
    assert main in win.tabifiedDockWidgets(win.tray) or win.tray in \
        win.tabifiedDockWidgets(main)
    # A Window-menu entry per panel, below the menu's own separator.
    actions = win._window_menu.actions()
    assert main.toggleViewAction() in actions and extra.toggleViewAction() in actions
    assert win._plugin_dock_sep.isVisible()


def test_a_panel_comes_back_where_the_user_left_it(win, tmp_path):
    app = _app_for(win)
    dock = app.add_panel("Floating", QLabel("x"))
    dock.setFloating(True)
    _app.processEvents()
    state = win.saveState()
    from views.main_window import MainWindow
    again = MainWindow()
    again.restoreState(state)
    again.show()
    dock2 = _app_for(again).add_panel("Floating", QLabel("y"))
    _app.processEvents()
    assert dock2.isFloating()
    again._saved_version = again.viewport.scene.version
    again.close()


# ---- overlays -----------------------------------------------------------------------

def _frame(vp):
    """One overlay pass on an image (offscreen has no GL frame to paint)."""
    img = QImage(200, 200, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    vp._draw_extension_overlays(p)
    p.end()
    return img


def test_an_overlay_draws_and_never_leaks_painter_state(win):
    vp = win.viewport
    seen = []

    def paint(viewport, painter):
        seen.append(viewport)
        painter.setPen(QColor("#FF0000"))
        painter.translate(1000, 1000)          # must not survive the call

    def after(viewport, painter):
        seen.append(painter.transform().dx())

    app = _app_for(win)
    app.add_overlay(paint)
    app.add_overlay(after)
    _frame(vp)
    assert seen[0] is vp and seen[1] == 0


def test_a_failing_overlay_is_dropped_once_and_the_others_still_run(win, caplog):
    vp = win.viewport
    ran = []

    def broken(_vp, _p):
        raise RuntimeError("boom")

    def fine(_vp, _p):
        ran.append(1)

    app = _app_for(win)
    app.add_overlay(broken)
    app.add_overlay(fine)
    _frame(vp)
    _frame(vp)
    assert broken not in vp._ext_overlays and fine in vp._ext_overlays
    assert len(ran) == 2
    assert sum("failed; removed" in r.message for r in caplog.records) == 1


def test_the_vectorised_projection_matches_the_per_point_one(win):
    vp = win.viewport
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 0.5], [-3.0, 1.0, 2.0]])
    px, py, front = _app_for(win).world_to_pixels(pts)
    for i, p in enumerate(pts):
        one = vp.world_to_pixel(V(*p))
        if one is None:
            assert not front[i]
        else:
            assert front[i]
            assert px[i] == pytest.approx(one[0], abs=1e-3)   # float32 vs float64
            assert py[i] == pytest.approx(one[1], abs=1e-3)


# ---- file openers ----------------------------------------------------------------------

def test_an_extension_opens_its_own_file_type(win):
    opened = []
    _app_for(win).add_file_opener("XYZ", lambda p: opened.append(p) or True)
    assert ".xyz" in win.file_openers
    assert win.open_path(Path("/tmp/job.XYZ"))
    assert opened == [Path("/tmp/job.XYZ")]


def test_the_launcher_hands_an_extension_file_to_the_window():
    """A double-click or a command-line path of a registered type reaches
    ``open_path`` (main._open_document_in), like an .igz."""
    import main

    class W:
        file_openers = {".xyz": None}
        opened = []

        def open_path(self, p):
            self.opened.append(p)

    w = W()
    main._open_document_in(w, Path("/tmp/a.xyz"))
    main._open_document_in(w, Path("/tmp/b.unknown"))
    assert w.opened == [Path("/tmp/a.xyz")]


# ---- workspaces -----------------------------------------------------------------------

class FakeWorkspace:
    def __init__(self, allowed=None, leave=True):
        self.scene = Scene()
        self.history = History(self.scene)
        self.allowed_tools = allowed
        self.saved = 0
        self.dirty = False
        self.leave_answer = leave
        self.gone = False

    def title(self):
        return "job.xyz"

    def is_dirty(self):
        return self.dirty

    def save(self):
        self.saved += 1
        self.dirty = False

    def save_as(self):
        self.save()

    def confirm_leave(self):
        return self.leave_answer

    def left(self):
        self.gone = True


def test_the_model_is_parked_and_comes_back(win):
    app = _app_for(win)
    model = win.viewport.scene
    model.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    history = win.viewport.history
    win._saved_version = model.version                   # a saved model
    ws = FakeWorkspace()
    assert app.enter_workspace(ws)
    assert app.workspace() is ws
    assert win.viewport.scene is ws.scene and win.viewport.history is ws.history
    assert ws.scene.version > model.version              # no render cache is shared
    assert win.windowTitle() == "IngeTrazo — job.xyz"
    assert not app.enter_workspace(FakeWorkspace())      # one at a time
    assert app.leave_workspace()
    assert win.viewport.scene is model and win.viewport.history is history
    assert len(model.mesh.faces) == 1
    assert not win._is_dirty()                           # still saved
    assert ws.gone and app.workspace() is None


def test_each_swap_resets_the_document_caches(win, monkeypatch):
    calls = []
    orig = win.viewport.reset_document_caches
    monkeypatch.setattr(win.viewport, "reset_document_caches",
                        lambda: (calls.append(1), orig())[1])
    app = _app_for(win)
    app.enter_workspace(FakeWorkspace())
    app.leave_workspace()
    assert len(calls) == 2


def test_file_actions_and_the_title_go_to_the_workspace(win):
    ws = FakeWorkspace()
    _app_for(win).enter_workspace(ws)
    ws.dirty = True
    win._update_title()
    assert win.windowTitle().endswith("job.xyz *")
    assert win._is_dirty()
    win._on_save()
    assert ws.saved == 1 and not win._is_dirty()
    win.leave_workspace()


def test_the_tool_filter_keeps_other_tools_out(win):
    ws = FakeWorkspace(allowed={"select", "line", "rectangle"})
    _app_for(win).enter_workspace(ws)
    assert not win._tool_actions["pushpull"].isEnabled()
    assert win._tool_actions["line"].isEnabled()
    win._activate_tool("pushpull")
    assert win.viewport.active_tool is not win._tools["pushpull"]
    win.leave_workspace()
    assert win._tool_actions["pushpull"].isEnabled()


def test_a_workspace_that_will_not_go_stops_quitting(win):
    ws = FakeWorkspace(leave=False)
    _app_for(win).enter_workspace(ws)
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    assert win.workspace() is ws
    ws.leave_answer = True
    assert win.leave_workspace()


def test_opening_an_igz_leaves_the_workspace_first(win, tmp_path):
    from formats import igz
    doc = tmp_path / "model.igz"
    igz.save_scene(Scene(), doc)
    ws = FakeWorkspace()
    _app_for(win).enter_workspace(ws)
    assert win.open_path(doc)
    assert win.workspace() is None and ws.gone


def test_autosave_pauses_while_the_model_is_parked(win, monkeypatch):
    from core import autosave
    written = []
    monkeypatch.setattr(autosave, "write", lambda *a, **k: written.append(a))
    ws = FakeWorkspace()
    _app_for(win).enter_workspace(ws)
    ws.dirty = True
    win._on_autosave_tick()
    assert written == []
    win.leave_workspace()
