# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Side panels never refresh under the user's hands (release_check 09-10).

After every edit the viewport says the model changed. The Components «In
model» list (its thumbnails' signatures) and the Browser (every row's
state) answered at once — +20 ms per edit on the Plaza, even with the
section folded or the tab hidden. Now: hidden, they wait until shown;
on screen, one refresh 300 ms after the last edit of a burst.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _count_calls(monkeypatch, obj, name):
    calls = []
    original = getattr(obj, name)
    monkeypatch.setattr(obj, name, lambda *a, **k: (calls.append(1),
                                                   original(*a, **k)))
    return calls


def test_a_hidden_components_list_waits_until_it_is_shown(win, monkeypatch):
    panel = win.tray.components
    panel.hide()
    calls = _count_calls(monkeypatch, panel, "refresh_in_model")
    for _ in range(3):
        win.viewport.scene.version += 1          # three edits, panel hidden
        panel.on_scene_changed()
    assert calls == []
    panel.show()
    _app.processEvents()
    assert len(calls) == 1                       # caught up on showing


def test_hidden_material_swatches_wait_until_shown(win, monkeypatch):
    """Its tab not shown, the Materials panel scanned every face paint
    after each edit anyway (~0.15 s on the plant of #158)."""
    panel = win.tray.materials
    panel.hide()
    calls = _count_calls(monkeypatch, panel, "refresh_in_model")
    for _ in range(3):
        win.viewport.scene.version += 1          # three edits, tab hidden
        win.tray.on_scene_changed()
    timer = getattr(win.tray, "_mat_refresh_timer", None)
    assert calls == [] and (timer is None or not timer.isActive())
    panel.show()
    _app.processEvents()
    assert len(calls) == 1                       # caught up on showing


def test_a_burst_of_edits_refreshes_the_visible_panels_once(win, monkeypatch):
    panel = win.tray.components
    outliner = win.project_browser.outliner
    if not (panel.isVisible() and outliner.isVisible()):
        pytest.skip("the factory layout hides one of the panels here")
    comp_calls = _count_calls(monkeypatch, panel, "refresh_in_model")
    tree_calls = _count_calls(monkeypatch, outliner, "refresh")
    for _ in range(5):
        win.viewport.scene.version += 1
        panel.on_scene_changed()
        outliner.on_scene_changed()
    assert comp_calls == [] and tree_calls == []     # nothing inline
    panel._in_model_timer.timeout.emit()
    outliner._refresh_timer.timeout.emit()
    assert len(comp_calls) == 1 and len(tree_calls) == 1


def test_a_selection_leaves_the_in_model_lists_as_they_are(win, monkeypatch):
    """A click bumps only the view: on the plant of #158 it rebuilt the
    «In model» list and rescanned every material (over a second)."""
    from PySide6.QtGui import QVector3D as V
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "placed")
    g.component = True
    vp = win.viewport
    vp.scene.groups.append(g)
    vp.scene.version += 1
    panel = win.tray.components
    panel.refresh_in_model()
    win.tray.materials.refresh_in_model()
    _app.processEvents()
    timer = getattr(win.tray, "_mat_refresh_timer", None)
    if timer is not None:
        timer.stop()                            # the edit above, done
    comp_calls = _count_calls(monkeypatch, panel, "refresh_in_model")
    vp.scene.select([g])                        # a view-only change
    win.tray.on_scene_changed()
    timer = getattr(win.tray, "_mat_refresh_timer", None)
    assert comp_calls == []
    assert timer is None or not timer.isActive()
    vp.scene.version += 1                       # an edit refreshes again
    win.tray.on_scene_changed()
    if panel._in_model_timer.isActive():
        panel._in_model_timer.timeout.emit()
    assert len(comp_calls) == 1
    assert win.tray._mat_refresh_timer.isActive()


def test_hidden_panels_let_the_previous_document_go(win):
    """Waiting to be shown, the «In model» list and the Browser kept their
    rows — and each row holds its group, so after New or Open the whole
    previous document stayed in memory (+130 MB on the Plaza,
    release_check 10-10)."""
    import gc
    from PySide6.QtGui import QVector3D as V
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "previous-document-marker")
    g.component = True
    vp = win.viewport
    vp.scene.groups.append(g)
    vp.scene.version += 1
    panel = win.tray.components
    browser = win.project_browser.outliner
    panel.refresh_in_model()
    browser.refresh()
    assert browser._groups                      # the rows hold the group
    panel.hide()
    browser.hide()
    del g, m
    win._saved_version = vp.scene.version       # no «discard?» question
    win._on_new()
    _app.processEvents()
    gc.collect()
    alive = [o for o in gc.get_objects() if isinstance(o, Group)
             and o.name == "previous-document-marker"]
    assert alive == []


def test_a_selection_notice_leaves_the_browser_rows_as_they_are(win, monkeypatch):
    """Its rows show what the model is: after a click (a view-only bump)
    the Browser read all 21 406 of them again on the plant of #158."""
    from PySide6.QtGui import QVector3D as V
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "row")
    vp = win.viewport
    vp.scene.groups.append(g)
    vp.scene.version += 1
    outliner = win.project_browser.outliner
    outliner.refresh()
    rows = _count_calls(monkeypatch, outliner, "_update_rows")
    vp.scene.select([g])                        # a view-only change
    outliner.refresh(rows_if_changed=True)
    assert rows == []
    vp.scene.version += 1                       # an edit
    outliner.refresh(rows_if_changed=True)
    assert len(rows) == 1
    outliner.refresh()                          # asked directly: always
    assert len(rows) == 2


def test_a_move_leaves_the_material_swatches_as_they_are(win):
    """Moving a group changes no material: on the plant of #158 each drop
    rescanned every face paint (~0.4 s). A paint does rescan."""
    from PySide6.QtGui import QVector3D as V
    from core.group import Group
    from core.history import MoveGroupCommand, SetFaceColorCommand
    from core.mesh import Mesh
    m = Mesh()
    f = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "moved")
    vp = win.viewport
    vp.scene.groups.append(g)
    vp.scene.version += 1
    win.tray.materials.refresh_in_model()
    _app.processEvents()
    timer = getattr(win.tray, "_mat_refresh_timer", None)
    if timer is not None:
        timer.stop()
    vp.history.execute(MoveGroupCommand(g, V(2, 0, 0)))
    win.tray.on_scene_changed()
    timer = getattr(win.tray, "_mat_refresh_timer", None)
    assert timer is None or not timer.isActive()
    vp.history.undo()                           # undoing it: the same
    win.tray.on_scene_changed()
    assert timer is None or not timer.isActive()
    vp.history.execute(SetFaceColorCommand([f], (1.0, 0.0, 0.0)))
    win.tray.on_scene_changed()
    assert win.tray._mat_refresh_timer.isActive()


def test_a_move_leaves_the_browser_rows_as_they_are(win, monkeypatch):
    """No row shows where a thing is: on the plant of #158 each drop read
    the 21 406 rows again. A paint does read them, and so does a Move
    when an extension's kind adds properties (they may be sizes)."""
    from PySide6.QtGui import QVector3D as V
    from core.group import Group
    from core.history import MoveGroupCommand, SetFaceColorCommand
    from core.mesh import Mesh
    m = Mesh()
    f = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "moved")
    vp = win.viewport
    vp.scene.groups.append(g)
    vp.scene.version += 1
    outliner = win.project_browser.outliner
    outliner.refresh()
    rows = _count_calls(monkeypatch, outliner, "_update_rows")
    vp.history.execute(MoveGroupCommand(g, V(2, 0, 0)))
    outliner.refresh(rows_if_changed=True)
    vp.history.undo()
    outliner.refresh(rows_if_changed=True)
    assert rows == []
    vp.history.execute(SetFaceColorCommand([f], (1.0, 0.0, 0.0)))
    outliner.refresh(rows_if_changed=True)
    assert len(rows) == 1
    vp.history.execute(MoveGroupCommand(g, V(2, 0, 0)))
    outliner.refresh(rows_if_changed=True)
    assert len(rows) == 1
    vp.scene.version += 1                       # an edit outside history
    vp.history.execute(MoveGroupCommand(g, V(2, 0, 0)))
    outliner.refresh(rows_if_changed=True)
    assert len(rows) == 2
    win._outliner_kinds = [lambda grp: None]
    vp.history.execute(MoveGroupCommand(g, V(2, 0, 0)))
    outliner.refresh(rows_if_changed=True)
    assert len(rows) == 3
