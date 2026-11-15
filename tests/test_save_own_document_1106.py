# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Saving writes each project's own document (#1106).

``window.viewport`` is the view in front, and an extension may assign it: a
split pane on a scene of its own. Assigning it used to replace the project's
viewport itself, so Save, Save As, the auto-save and the unsaved-changes
state all went to that other scene, and the file of the tab in front was
overwritten with it. These tests drive the real window and read back the
real file, on every path that writes one."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core import autosave  # noqa: E402
from core.history import AddEdgeCommand  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz as igz_format  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _settle(ms: int = 0) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _edges(view, n) -> None:
    """``n`` real, undoable edges: a count that tells the documents apart."""
    base = len(view.scene.mesh.edges)
    for i in range(base, base + n):
        view.history.execute(AddEdgeCommand(V(i, 0, 5), V(i, 1, 5)))
    view.notify_scene_changed()


def _edges_in_file(path) -> int:
    scene = Scene()
    igz_format.load_into(scene, path)
    return len(scene.mesh.edges)


def _new_tab(win, n, path=None):
    """A new project in front with ``n`` unsaved edges, its file ``path``."""
    win._on_new()
    doc = win.active_document()
    _edges(win.viewport, n)
    doc.path = path
    return doc


def _pane(win, n=7):
    """What a split-view extension assigns: a view on another scene."""
    from views.viewport import Viewport
    pane = Viewport(win)
    pane.hide()
    _edges(pane, n)
    return pane


@pytest.fixture
def win(tmp_path, monkeypatch):
    slots = tmp_path / "autosave"
    slots.mkdir()
    monkeypatch.setattr(autosave, "autosave_dir", lambda: slots)
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for d in w.documents():
        d.saved_content = d.viewport.scene.content_version
    w.close()
    _settle()


# ---- A view of an extension in front ---------------------------------------
def test_save_writes_the_tab_and_not_the_view_in_front(win, tmp_path):
    path = tmp_path / "model.igz"
    doc = _new_tab(win, 3, path)
    win.viewport = _pane(win)
    assert win.viewport is not doc.viewport         # extensions still see it
    win._on_save()
    assert _edges_in_file(path) == 3
    assert not win._is_dirty()


def test_save_as_writes_the_tab_and_not_the_view_in_front(win, tmp_path,
                                                          monkeypatch):
    from views import main_window as mw
    path = tmp_path / "named.igz"
    doc = _new_tab(win, 3)
    win.viewport = _pane(win)
    monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    win._on_save_as()
    assert _edges_in_file(path) == 3
    assert doc.path == path
    assert not win._is_dirty()


def test_the_camera_saved_is_the_one_of_the_project(win, tmp_path):
    path = tmp_path / "model.igz"
    doc = _new_tab(win, 2, path)
    doc.viewport.camera.distance = 33.0
    pane = _pane(win)
    pane.camera.distance = 99.0
    win.viewport = pane
    win._on_save()
    scene = Scene()
    igz_format.load_into(scene, path)
    assert scene.camera_home["distance"] == 33.0


def test_the_unsaved_state_is_the_one_of_the_project(win, tmp_path):
    doc = _new_tab(win, 2, tmp_path / "model.igz")
    win._on_save()
    pane = _pane(win)
    win.viewport = pane
    pane.scene.view_version += 5            # a click there, say
    assert not win._is_dirty()              # the pane's edges are not its own
    _edges(pane, 1)
    assert not win._is_dirty()
    _edges(doc.viewport, 1)
    assert win._is_dirty()
    win._on_save()
    assert not win._is_dirty()
    assert _edges_in_file(doc.path) == 3


def test_the_auto_save_writes_the_project(win, tmp_path):
    path = tmp_path / "model.igz"
    _new_tab(win, 3, path)
    win.viewport = _pane(win)
    win._on_autosave_tick()
    slot = autosave.pending(path)
    assert slot is not None
    assert _edges_in_file(slot) == 3


def test_closing_its_tab_saves_the_project(win, tmp_path, monkeypatch):
    path = tmp_path / "a.igz"
    a = _new_tab(win, 3, path)
    win.viewport = _pane(win)
    _new_tab(win, 2, tmp_path / "b.igz")
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.Save)
    assert win.close_document(a)
    assert _edges_in_file(path) == 3
    assert a not in win.documents()


def test_quitting_saves_each_project_with_a_view_in_front_of_one(
        win, tmp_path, monkeypatch):
    a_path, b_path = tmp_path / "a.igz", tmp_path / "b.igz"
    _new_tab(win, 3, a_path)
    win.viewport = _pane(win)
    _new_tab(win, 2, b_path)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.SaveAll)
    assert win._confirm_quit()
    assert _edges_in_file(a_path) == 3
    assert _edges_in_file(b_path) == 2


def test_the_own_viewport_ends_the_replacement_in_its_project(win, tmp_path):
    """An extension restoring tab A's viewport with tab B in front: B stays
    B, and A shows its own again. It used to make B save A's scene."""
    a = _new_tab(win, 3, tmp_path / "a.igz")
    own = win.viewport
    win.viewport = _pane(win)
    b = _new_tab(win, 2, tmp_path / "b.igz")
    win.viewport = own
    assert win.viewport is b.viewport and b.viewport is not own
    win._on_save()
    assert _edges_in_file(b.path) == 2
    win.activate_document(a)
    assert win.viewport is own
    win._on_save()
    assert _edges_in_file(a.path) == 3


def test_the_replacement_stays_with_its_tab(win, tmp_path):
    a = _new_tab(win, 3, tmp_path / "a.igz")
    pane = _pane(win)
    win.viewport = pane
    b = _new_tab(win, 2)
    assert win.viewport is b.viewport
    win.activate_document(a)
    assert win.viewport is pane
    win.viewport = a.viewport
    assert win.viewport is a.viewport
    assert a.front_view is None


def test_a_file_opened_under_a_view_does_not_land_on_it(win, tmp_path):
    """The untitled tab in front would be reused, and what is read would go
    to the pane's scene while the next Save writes the empty project over
    the file just opened."""
    source = Scene()
    for i in range(4):
        source.mesh.add_edge(V(i, 0, 0), V(i, 1, 0))
    path = tmp_path / "other.igz"
    igz_format.save_scene(source, path)
    blank = win.active_document()
    win.viewport = _pane(win)
    assert win.open_path(path)
    assert win.active_document() is not blank
    assert win.active_document().path == path
    win._on_save()
    assert _edges_in_file(path) == 4


def test_file_new_under_a_view_opens_a_tab(win):
    blank = win.active_document()
    pane = _pane(win)
    win.viewport = pane
    win._on_new()
    assert win.active_document() is not blank
    assert len(pane.scene.mesh.edges) == 7          # not cleared


def test_closing_retires_the_own_viewport(win, tmp_path, monkeypatch):
    a = _new_tab(win, 3, tmp_path / "a.igz")
    own = a.viewport
    pane = _pane(win)
    win.viewport = pane
    assert own in win.all_viewports() and pane not in win.all_viewports()
    assert win.close_document(a, ask=False)
    assert own not in win.all_viewports()
    assert a.viewport is None and a.front_view is None


def test_a_workspace_is_not_asked_about_another_tab(win, tmp_path,
                                                    monkeypatch):
    """Closing a tab behind a workspace: the question, and its Save, would be
    about the workspace's document, and the tab closed with its work lost."""
    a = _new_tab(win, 3, tmp_path / "a.igz")
    _new_tab(win, 2, tmp_path / "b.igz")
    scene = Scene()

    class Workspace:
        allowed_tools = None
        history = win.viewport.history.__class__(scene)
        camera = None

        def __init__(self):
            self.scene = scene

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

    assert win.enter_workspace(Workspace())
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.Save)
    assert not win.close_document(a)
    assert a in win.documents()
    assert win.leave_workspace()


def test_leaving_a_workspace_finds_the_project_clean(win, tmp_path):
    """A saved model stays saved after a workspace on a view in front."""
    _new_tab(win, 3, tmp_path / "a.igz")
    win._on_save()
    win.viewport = _pane(win)
    scene = Scene()

    class Workspace:
        allowed_tools = None
        history = win.viewport.history.__class__(scene)
        camera = None

        def __init__(self):
            self.scene = scene

        def title(self):
            return "job"

        def is_dirty(self):
            return False

        def confirm_leave(self):
            return True

    assert win.enter_workspace(Workspace())
    assert win.leave_workspace()
    assert not win._is_dirty()


def test_saving_ends_the_group_open_in_the_project(win, tmp_path):
    """With a view in front the open group of the project itself ends too:
    what is written is the model, not the group's edit state."""
    from core.group import Group
    from core.mesh import Mesh
    path = tmp_path / "a.igz"
    doc = _new_tab(win, 3, path)
    mesh = Mesh()
    mesh.add_edge(V(0, 0, 9), V(1, 0, 9))
    group = Group(mesh, name="g")
    scene = doc.viewport.scene
    scene.groups.append(group)
    scene.version += 1
    doc.viewport.begin_group_edit(group)
    assert scene.edit_group is group
    win.viewport = _pane(win)
    win._on_save()
    assert scene.edit_group is None
    assert _edges_in_file(path) == 3


# ---- Plain tabs: nobody writes over anybody ---------------------------------
def test_each_tab_saves_its_own_file(win, tmp_path):
    a = _new_tab(win, 3, tmp_path / "a.igz")
    b = _new_tab(win, 2, tmp_path / "b.igz")
    win._on_save()
    assert _edges_in_file(b.path) == 2
    assert not a.path.exists()
    win.activate_document(a)
    win._on_save()
    assert _edges_in_file(a.path) == 3
    assert _edges_in_file(b.path) == 2


def test_closing_a_tab_behind_saves_that_tab(win, tmp_path, monkeypatch):
    a = _new_tab(win, 3, tmp_path / "a.igz")
    b = _new_tab(win, 2, tmp_path / "b.igz")
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.Save)
    assert win.close_document(a)
    assert _edges_in_file(a.path) == 3
    assert not b.path.exists()
    assert win.active_document() is b


def test_quitting_with_one_changed_tab_behind_saves_that_tab(win, tmp_path,
                                                             monkeypatch):
    a = _new_tab(win, 3, tmp_path / "a.igz")
    b = _new_tab(win, 2, tmp_path / "b.igz")
    win._on_save()
    assert not win._doc_is_dirty(b)
    assert win._doc_is_dirty(a)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.Save)
    assert win._confirm_quit()
    assert _edges_in_file(a.path) == 3
    assert _edges_in_file(b.path) == 2


def test_quitting_saves_all_each_to_its_own_file(win, tmp_path, monkeypatch):
    a = _new_tab(win, 3, tmp_path / "a.igz")
    b = _new_tab(win, 2, tmp_path / "b.igz")
    c = _new_tab(win, 5, tmp_path / "c.igz")
    win.activate_document(b)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.SaveAll)
    assert win._confirm_quit()
    assert [_edges_in_file(d.path) for d in (a, b, c)] == [3, 2, 5]


def test_cancelling_a_save_as_on_quit_stays_and_writes_nothing_wrong(
        win, tmp_path, monkeypatch):
    from views import main_window as mw
    a = _new_tab(win, 3, tmp_path / "a.igz")
    _new_tab(win, 2)                                # untitled: Save As
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.SaveAll)
    monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                        lambda *a, **k: ("", ""))
    assert not win._confirm_quit()
    assert _edges_in_file(a.path) == 3


def test_a_failed_save_on_quit_stays(win, tmp_path, monkeypatch):
    from views import main_window as mw
    path = tmp_path / "a.igz"
    a = _new_tab(win, 3, path)
    _new_tab(win, 2, tmp_path / "b.igz")

    def fail(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(mw.igz_format, "save_scene", fail)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.SaveAll)
    assert not win._confirm_quit()
    assert win._doc_is_dirty(a)
    assert not path.exists()


def test_save_as_retires_the_recovery_copy_of_the_old_name(win, tmp_path,
                                                           monkeypatch):
    """Its work is safe under the new name: the slot of the old one would
    offer that stale copy back whenever the old file is opened again."""
    from views import main_window as mw
    old, new = tmp_path / "old.igz", tmp_path / "new.igz"
    _new_tab(win, 3, old)
    win._on_autosave_tick()
    assert autosave.pending(old) is not None
    monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(new), ""))
    win._on_save_as()
    assert autosave.pending(old) is None
    assert autosave.pending(new) is None


def test_the_auto_save_of_a_tab_behind_goes_to_its_own_slot(win, tmp_path):
    a = _new_tab(win, 3, tmp_path / "a.igz")
    b = _new_tab(win, 2, tmp_path / "b.igz")
    win._on_autosave_tick()
    assert _edges_in_file(autosave.pending(a.path)) == 3
    assert _edges_in_file(autosave.pending(b.path)) == 2


def test_the_camera_saved_is_the_one_of_each_tab(win, tmp_path):
    a = _new_tab(win, 1, tmp_path / "a.igz")
    a.viewport.camera.distance = 11.0
    b = _new_tab(win, 1, tmp_path / "b.igz")
    b.viewport.camera.distance = 22.0
    win._on_save()
    win.activate_document(a)
    win._on_save()
    for doc, want in ((a, 11.0), (b, 22.0)):
        scene = Scene()
        igz_format.load_into(scene, doc.path)
        assert scene.camera_home["distance"] == want
