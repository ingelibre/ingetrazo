# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Windowizer example extension (Bane Andreev's port of Rick Wilson's
Windowizer 3): windows from faces, as one container group each — and the
extension API it needed: add_menu, add_context_menu and group.ext."""
from __future__ import annotations

import os
import shutil
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

import core.extensions as extensions  # noqa: E402
from core.history import AddFaceCommand  # noqa: E402

_app = QApplication.instance() or QApplication([])

EXAMPLE = os.path.join(os.path.dirname(__file__), os.pardir, "examples",
                       "extensions", "windowizer.py")


@pytest.fixture
def win(tmp_path, monkeypatch):
    shutil.copy(EXAMPLE, tmp_path / "windowizer.py")
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _mod():
    return next(m for n, m in sys.modules.items()
                if n.endswith("windowizer") and hasattr(m, "make_window"))


def _wall(vp):
    """A 4 m × 3 m wall, 25 cm thick, and a 1.5 × 1.2 m rectangle drawn on
    its front face — what a user does before Windowize."""
    m = vp.scene.mesh
    p = [V(0, 0, 0), V(4, 0, 0), V(4, .25, 0), V(0, .25, 0),
         V(0, 0, 3), V(4, 0, 3), V(4, .25, 3), V(0, .25, 3)]
    for loop in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in loop])
    vp.history.execute(AddFaceCommand(
        [V(1, 0, 1), V(2.5, 0, 1), V(2.5, 0, 2.2), V(1, 0, 2.2)]))
    return next(f for f in m.faces if abs(f.area() - 1.8) < 1e-6)


def _windowize(win, monkeypatch, **params):
    mod = _mod()
    vp = win.viewport
    face = _wall(vp)
    vp.scene.selection.clear()
    vp.scene.selection.add(face)
    chosen = dict(mod.DEFAULTS, **params)
    monkeypatch.setattr(mod.WindowizerDialog, "ask",
                        classmethod(lambda cls, *a, **k: dict(chosen)))
    mod.windowize(vp)
    wins = [g for g in vp.scene.groups if mod.window_data(g) is not None]
    assert len(wins) == 1
    return mod, vp, wins[0]


def test_a_face_on_a_wall_becomes_a_window_in_one_undo(win, monkeypatch):
    mod, vp, g = _windowize(win, monkeypatch, rows="1", cols="2")
    assert g.ifc["class"] == "IfcWindow"
    names = sorted(c.name for c in g.children)
    assert names == ["Frame", "Glass 1", "Glass 2"]
    assert mod.KEY in g.ext and "windowizer" not in g.ifc
    assert vp.history.undo()
    assert g not in vp.scene.groups
    assert vp.history.redo()
    assert g in vp.scene.groups


def test_retagging_in_bim_keeps_the_window_editable(win, monkeypatch):
    mod, vp, g = _windowize(win, monkeypatch)
    g.ifc = {"class": "IfcWindow", "name": "V-01"}     # what the BIM panel does
    assert mod.window_data(g) is not None


def test_copies_keep_their_own_parameters(win, monkeypatch):
    from core.group import copy_group
    mod, vp, g = _windowize(win, monkeypatch)
    c = copy_group(g)
    assert mod.window_data(c) == mod.window_data(g)
    c.ext[mod.KEY]["params"]["rows"] = "5"
    assert mod.window_data(g)["params"]["rows"] != "5"


def test_edit_rebuilds_in_place(win, monkeypatch):
    mod, vp, g = _windowize(win, monkeypatch, rows="1", cols="1")
    vp.scene.selection.clear()
    vp.scene.selection.add(g)
    monkeypatch.setattr(mod.WindowizerDialog, "ask", classmethod(
        lambda cls, *a, **k: dict(mod.DEFAULTS, rows="2", cols="3")))
    mod.edit(vp)
    assert sum(c.name.startswith("Glass") for c in g.children) == 6
    assert vp.history.undo()
    assert sum(c.name.startswith("Glass") for c in g.children) == 1


def test_a_saved_window_reopens_editable(win, monkeypatch, tmp_path):
    from core.scene import Scene
    from formats import igz
    mod, vp, g = _windowize(win, monkeypatch)
    path = tmp_path / "wall.igz"
    igz.save_scene(vp.scene, path)
    again = Scene()
    igz.load_into(again, path)
    wins = [x for x in again.groups if mod.window_data(x) is not None]
    assert len(wins) == 1
    assert wins[0].ext[mod.KEY]["params"] == g.ext[mod.KEY]["params"]


def test_erase_closes_the_wall_again(win, monkeypatch):
    mod, vp, g = _windowize(win, monkeypatch)
    vp.scene.selection.clear()
    vp.scene.selection.add(g)
    mod.erase(vp)
    assert g not in vp.scene.groups
    # Back to what the user drew: the wall face with the rectangle in it,
    # and the back of the wall whole again (the cut went through it).
    front = sorted(round(f.area(), 3) for f in vp.scene.mesh.faces
                   if abs(f.normal().y() + 1) < 1e-6)
    assert front == [1.8, 12.0]
    back = [f for f in vp.scene.mesh.faces if abs(f.normal().y() - 1) < 1e-6]
    assert [len(f.holes) for f in back] == [0]


def test_its_menus_come_from_the_extension_api(win, monkeypatch):
    mod = _mod()
    ext = win._ext_menu
    subs = [a.menu() for a in ext.actions() if a.menu() is not None]
    assert any(m.title() == "Windowizer" for m in subs)
    vp = win.viewport
    face = _wall(vp)
    vp.scene.selection.clear()
    vp.scene.selection.add(face)
    menu = QMenu()
    for fn in win._ext_context_menus:
        fn(menu, list(vp.scene.selection))
    titles = [a.text() for a in menu.actions()]
    assert "Windowizer" in titles
    # ...and the window's own QMenu name is never swapped any more.
    import views.main_window as mw
    assert mw.QMenu is QMenu
