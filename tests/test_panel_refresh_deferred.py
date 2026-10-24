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
        panel.on_scene_changed()                 # three edits, panel hidden
    assert calls == []
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
        panel.on_scene_changed()
        outliner.on_scene_changed()
    assert comp_calls == [] and tree_calls == []     # nothing inline
    panel._in_model_timer.timeout.emit()
    outliner._refresh_timer.timeout.emit()
    assert len(comp_calls) == 1 and len(tree_calls) == 1


def test_hidden_panels_let_the_previous_document_go(win):
    """Waiting panels must release the geometry held by their old rows,
    including BIM takeoff objects, when New replaces the document."""
    import gc
    from PySide6.QtGui import QVector3D as V
    from core.bim import tag_group
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, "previous-document-marker")
    g.component = True
    tag_group(g, "IfcSlab", "Previous")
    vp = win.viewport
    vp.scene.groups.append(g)
    vp.scene.version += 1
    _show_bim(win)
    _bim_scene_changed(win)
    panel = win.tray.components
    browser = win.project_browser.outliner
    panel.refresh_in_model()
    browser.refresh()
    assert browser._groups                      # the rows hold the group
    assert _bim_rows(win) == [("Slab", "Previous", "1.00 m²", "—")]
    panel.hide()
    browser.hide()
    win.bim_tray.hide()
    del g, m
    win._saved_version = vp.scene.version       # no «discard?» question
    win._on_new()
    _app.processEvents()
    gc.collect()
    alive = [o for o in gc.get_objects() if isinstance(o, Group)
             and o.name == "previous-document-marker"]
    assert alive == []


def _bim_slab(win, width=2, name="Slab"):
    from PySide6.QtGui import QVector3D as V
    from core.bim import tag_faces
    face = win.viewport.scene.loose_mesh.add_face(
        [V(0, 0, 0), V(width, 0, 0), V(width, 2, 0), V(0, 2, 0)])
    tag_faces([face], "IfcSlab", name, 1)
    return face


def _bim_scene_changed(win):
    scene = win.viewport.scene
    scene.version += 1
    win.viewport.notify_scene_changed()
    _app.processEvents()


def _bim_rows(win):
    tree = win.bim_tray.bim.tree
    return [tuple(tree.topLevelItem(i).text(col) for col in range(4))
            for i in range(tree.topLevelItemCount())]


def _show_bim(win):
    win.bim_tray.show()
    win.bim_tray.raise_()
    _app.processEvents()


@pytest.mark.parametrize("hidden_by", ["closed", "another_tab"])
def test_hidden_bim_waits_and_shows_the_latest_quantities(win, hidden_by):
    from core.bim import tag_faces
    _show_bim(win)
    face = _bim_slab(win)
    _bim_scene_changed(win)
    assert _bim_rows(win) == [("Slab", "Slab", "4.00 m²", "—")]
    if hidden_by == "closed":
        win.bim_tray.close()
    else:
        win.tray.show()
        win.tray.raise_()
    _app.processEvents()

    scene = win.viewport.scene
    scene.layers[0].visible = False
    _bim_scene_changed(win)
    scene.loose_mesh.remove_face(face)
    face = _bim_slab(win, width=4, name="Intermediate")
    _bim_scene_changed(win)
    tag_faces([face], "IfcSlab", "Latest", 1)
    _bim_scene_changed(win)

    _show_bim(win)
    # Takeoff covers the whole model, including the now-hidden layer.
    assert _bim_rows(win) == [("Slab", "Latest", "8.00 m²", "—")]


def test_visible_bim_tracks_geometry_and_tag_changes(win):
    from core.bim import tag_faces, untag_faces
    _show_bim(win)
    face = _bim_slab(win)
    _bim_scene_changed(win)
    assert _bim_rows(win) == [("Slab", "Slab", "4.00 m²", "—")]

    win.viewport.scene.loose_mesh.remove_face(face)
    face = _bim_slab(win, width=3)
    _bim_scene_changed(win)
    assert _bim_rows(win) == [("Slab", "Slab", "6.00 m²", "—")]

    tag_faces([face], "IfcWall", "Retagged", 1)
    _bim_scene_changed(win)
    assert _bim_rows(win) == [("Wall", "Retagged", "6.00 m²", "—")]
    untag_faces([face])
    _bim_scene_changed(win)
    assert _bim_rows(win) == []


def test_bim_reopening_without_edits_keeps_the_correct_quantities(win):
    _show_bim(win)
    _bim_slab(win)
    _bim_scene_changed(win)
    win.bim_tray.hide()
    _app.processEvents()
    _show_bim(win)
    assert _bim_rows(win) == [("Slab", "Slab", "4.00 m²", "—")]


def test_hidden_bim_rebuilds_rows_after_selection_only_notification(win):
    _show_bim(win)
    face = _bim_slab(win)
    _bim_scene_changed(win)
    win.bim_tray.hide()
    _app.processEvents()
    scene = win.viewport.scene
    content_version = scene.content_version
    scene.select([face])
    win.viewport.notify_scene_changed()
    _app.processEvents()
    assert scene.content_version == content_version
    _show_bim(win)
    assert _bim_rows(win) == [("Slab", "Slab", "4.00 m²", "—")]
