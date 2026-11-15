# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The DXF/DWG import option (#1109): faces on the closed planar outlines,
off by default, and how many were made said at the end."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ezdxf
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDialog

from core.make_faces import faces_from_linework
from core.mesh import Mesh
from core.scene import Scene
from formats.dxf_in import load_dxf

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

SQUARE = [(0, 0), (2, 0), (2, 2), (0, 2)]


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _save(doc, tmp_path):
    out = tmp_path / "plan.dxf"
    doc.saveas(str(out))
    return out


def _load(doc, tmp_path, **kw):
    scene = Scene()
    stats = load_dxf(scene, _save(doc, tmp_path), **kw)
    return scene, stats


def _plan():
    doc = ezdxf.new("R2018")
    doc.modelspace().add_lwpolyline(SQUARE, close=True)
    return doc


def _loop(mesh, pts):
    for a, b in zip(pts, pts[1:] + pts[:1]):
        mesh.add_edge(V(*a), V(*b))


# ---- The loader --------------------------------------------------------------

def test_off_by_default_the_outline_stays_lines(tmp_path):
    scene, stats = _load(_plan(), tmp_path)
    assert stats["outline_faces"] == 0
    assert not scene.groups[0].mesh.faces
    assert len(scene.groups[0].mesh.edges) == 4


def test_on_the_outline_gets_its_face_on_its_lines(tmp_path):
    scene, stats = _load(_plan(), tmp_path, make_faces=True)
    mesh = scene.groups[0].mesh
    assert stats["outline_faces"] == 1 and stats["faces"] == 1
    assert len(mesh.faces) == 1 and len(mesh.edges) == 4
    assert mesh.faces[0].normal().z() > 0.99


def test_a_nested_loop_is_a_hole_and_a_face_of_its_own(tmp_path):
    doc = _plan()
    doc.modelspace().add_circle((1, 1), 0.5)
    scene, stats = _load(doc, tmp_path, make_faces=True)
    mesh = scene.groups[0].mesh
    assert stats["outline_faces"] == 2
    assert sum(1 for f in mesh.faces if f.hole_loops) == 1
    # The circle is still one curve, for a click to select it whole.
    assert len({e.curve for e in mesh.edges if e.curve is not None}) == 1


def test_a_block_is_faced_once_and_every_copy_shows_it(tmp_path):
    # The case the issue was opened for: the outline arrives inside the
    # block's component.
    doc = ezdxf.new("R2018")
    doc.blocks.new("PART").add_lwpolyline(SQUARE, close=True)
    msp = doc.modelspace()
    msp.add_blockref("PART", (0, 0))
    msp.add_blockref("PART", (10, 0))
    scene, stats = _load(doc, tmp_path, make_faces=True)
    a, b = scene.groups
    assert a.mesh is b.mesh and len(a.mesh.faces) == 1
    assert stats["outline_faces"] == 1
    assert stats["components"] == {"PART": 2}


def test_each_layer_is_faced_in_its_own_group(tmp_path):
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_lwpolyline(SQUARE, close=True, dxfattribs={"layer": "WALLS"})
    msp.add_lwpolyline([(5, 0), (6, 0), (6, 1)], close=True,
                       dxfattribs={"layer": "PLOTS"})
    scene, stats = _load(doc, tmp_path, make_faces=True)
    assert stats["outline_faces"] == 2
    assert all(len(g.mesh.faces) == 1 for g in scene.groups)


def test_open_lines_stay_lines_and_nothing_fails(tmp_path):
    doc = ezdxf.new("R2018")
    doc.modelspace().add_lwpolyline([(0, 0), (1, 0), (1, 1)])
    scene, stats = _load(doc, tmp_path, make_faces=True)
    assert stats["outline_faces"] == 0
    assert not scene.groups[0].mesh.faces


def test_a_face_the_file_brought_is_not_doubled(tmp_path):
    doc = ezdxf.new("R2018")
    doc.modelspace().add_3dface([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])
    scene, stats = _load(doc, tmp_path, make_faces=True)
    assert stats["outline_faces"] == 0
    assert len(scene.groups[0].mesh.faces) == 1


def test_a_failure_making_faces_keeps_the_import(tmp_path, monkeypatch):
    import core.make_faces

    def boom(_mesh):
        raise RuntimeError("no")

    monkeypatch.setattr(core.make_faces, "faces_from_linework", boom)
    scene, stats = _load(_plan(), tmp_path, make_faces=True)
    assert stats["outline_faces"] == 0
    assert len(scene.groups[0].mesh.edges) == 4


# ---- A whole drawing ----------------------------------------------------------

def test_levels_and_lines_crossing_without_a_shared_point():
    mesh = Mesh()
    _loop(mesh, [(0, 0), (4, 0), (4, 3), (0, 3)])
    _loop(mesh, [(2, 1), (6, 1), (6, 5), (2, 5)])
    _loop(mesh, [(0, 0, 0.9), (1, 0, 0.9), (1, 1, 0.9), (0, 1, 0.9)])
    assert faces_from_linework(mesh) == 4
    assert not [e for e in mesh.edges if not e.faces]


def test_a_drawing_on_a_wall_gets_its_own_plane():
    mesh = Mesh()
    _loop(mesh, [(0, 0, 0), (2, 0, 0), (2, 0, 1), (0, 0, 1)])
    _loop(mesh, [(5, 0), (6, 0), (6, 1), (5, 1)])
    assert faces_from_linework(mesh) == 2


def test_a_wireframe_box_only_closes_its_flat_loops():
    # Twelve lines of a box: no single plane holds them. A selection that
    # is not flat is an error in the command; an import carries on.
    mesh = Mesh()
    bottom = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    top = [(x, y, 1) for x, y, _z in bottom]
    _loop(mesh, bottom)
    _loop(mesh, top)
    for a, b in zip(bottom, top):
        mesh.add_edge(V(*a), V(*b))
    assert faces_from_linework(mesh) == 2
    assert len(mesh.edges) == 12


def test_nothing_to_do_on_an_empty_mesh():
    assert faces_from_linework(Mesh()) == 0


# ---- The window ----------------------------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    QSettings().remove("import/dxf_make_faces")
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()
    QSettings().remove("import/dxf_make_faces")


def _answer(monkeypatch, tick=None, accept=True):
    """Answer the import dialog; returns the checkbox states it opened with."""
    seen = []

    def run(dlg):
        box = dlg.findChild(QCheckBox)
        assert dlg.findChild(QComboBox) is not None
        seen.append(box.isChecked())
        if tick is not None:
            box.setChecked(tick)
        return QDialog.Accepted if accept else QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", run)
    return seen


def _imported(win):
    return [g for g in win.viewport.scene.groups if g.name == "plan"][0]


def test_the_box_starts_off_and_the_import_makes_no_face(
        win, tmp_path, monkeypatch):
    seen = _answer(monkeypatch)
    assert win._import_dxf_path(_save(_plan(), tmp_path))
    assert seen == [False]
    assert not _imported(win).mesh.faces
    assert "closed outlines" not in win.statusBar().currentMessage()


def test_ticked_the_faces_are_made_and_counted_in_one_undo_step(
        win, tmp_path, monkeypatch):
    _answer(monkeypatch, tick=True)
    assert win._import_dxf_path(_save(_plan(), tmp_path))
    assert len(_imported(win).mesh.faces) == 1
    assert "1 faces made from closed outlines" \
        in win.statusBar().currentMessage()
    scene = win.viewport.scene
    win.viewport.history.undo()
    assert not [g for g in scene.groups if g.name == "plan"]


def test_the_last_answer_comes_back_ticked(win, tmp_path, monkeypatch):
    _answer(monkeypatch, tick=True)
    win._import_dxf_path(_save(_plan(), tmp_path))
    seen = _answer(monkeypatch)
    win._import_dxf_path(_save(_plan(), tmp_path))
    assert seen == [True]


def test_cancelling_imports_nothing_and_remembers_nothing(
        win, tmp_path, monkeypatch):
    before = len(win.viewport.scene.groups)
    _answer(monkeypatch, tick=True, accept=False)
    assert win._import_dxf_path(_save(_plan(), tmp_path)) is False
    assert len(win.viewport.scene.groups) == before
    assert QSettings().value("import/dxf_make_faces", False,
                             type=bool) is False
