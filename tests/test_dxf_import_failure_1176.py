# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A DXF or DWG that brings nothing in says so and leaves no tab (#1176, #1172).

``history.execute`` rolls a failed command back and does not raise, so the
importer's ``except`` never ran: a drawing with nothing to import opened an
empty tab named after the file, with no word to the user. And the rollback
moves the version on, so even a failure that was caught left the new tab
looking changed, and it stayed."""
from __future__ import annotations

import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ezdxf = pytest.importorskip("ezdxf")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import (QApplication, QInputDialog,  # noqa: E402
                               QMessageBox)

from core.history import AddEdgeCommand  # noqa: E402
from formats import dwg_bridge, dxf_in  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _settle(ms: int = 0) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _dxf(tmp_path, fill=None, name="drawing.dxf"):
    doc = ezdxf.new()
    if fill is not None:
        fill(doc)
    path = tmp_path / name
    doc.saveas(path)
    return path


def _only_text(doc):
    msp = doc.modelspace()
    msp.add_text("a note")
    msp.add_text("another note")
    msp.add_point((1, 1))


def _annotation_block(doc):
    block = doc.blocks.new("LABEL")
    block.add_text("a note")
    doc.modelspace().add_blockref("LABEL", (0, 0))


def _line(doc):
    doc.modelspace().add_line((0, 0), (5, 0))


def _edit(win):
    win.viewport.history.execute(AddEdgeCommand(V(0, 0, 5), V(1, 0, 5)))
    win.viewport.notify_scene_changed()


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    for d in w.documents():
        d.saved_content = d.viewport.scene.content_version
    w.close()
    _settle()


@pytest.fixture
def errors(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical",
                        lambda _parent, title, text: shown.append((title, text)))
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda _p, _t, _l, items, _i, _e:
                                     (items[2], True)))
    return shown


# ---- Nothing to import is said (#1172) --------------------------------------
@pytest.mark.parametrize("fill", [None, _only_text, _annotation_block],
                         ids=["empty", "only_text", "annotation_block"])
def test_a_drawing_with_nothing_to_import_says_so(win, errors, tmp_path, fill):
    path = _dxf(tmp_path, fill)
    assert win.open_path(path) is False
    assert len(errors) == 1
    title, text = errors[0]
    assert title == "Import DXF failed"
    assert "drawing.dxf" in text and "nothing that can be imported" in text


def test_the_message_names_what_was_left_out(win, errors, tmp_path,
                                             monkeypatch):
    def only_skipped(*_a, **_k):
        raise dxf_in.NothingToImport({"3DSOLID": 12, "MTEXT": 3})
    monkeypatch.setattr(dxf_in, "load_dxf", only_skipped)
    assert win._import_dxf_path(_dxf(tmp_path, _line)) is False
    assert "3DSOLID ×12, MTEXT ×3" in errors[0][1]


def test_a_real_skipped_kind_reaches_the_message(win, errors, tmp_path):
    path = _dxf(tmp_path, _only_text)
    assert win.open_path(path) is False
    assert "TEXT ×2" in errors[0][1]




# ---- No tab stays (#1176) ---------------------------------------------------
@pytest.mark.parametrize("fill", [None, _only_text],
                         ids=["empty", "only_text"])
def test_a_failed_import_leaves_no_tab_behind(win, errors, tmp_path, fill):
    _edit(win)
    mine = win.active_document()
    assert win.open_path(_dxf(tmp_path, fill)) is False
    assert win.documents() == [mine]
    assert win.active_document() is mine
    assert win._is_dirty()                          # his work still counts


def test_an_unreadable_file_leaves_no_tab_behind(win, errors, tmp_path):
    _edit(win)
    mine = win.active_document()
    bad = tmp_path / "bad.dxf"
    bad.write_bytes(b"not a drawing at all\x00\x01")
    assert win.open_path(bad) is False
    assert win.documents() == [mine]
    assert len(errors) == 1


def test_a_loader_that_dies_says_why_and_leaves_no_tab(win, errors, tmp_path,
                                                       monkeypatch):
    _edit(win)
    mine = win.active_document()

    def dies(*_a, **_k):
        raise RuntimeError("bad entity on layer X")
    monkeypatch.setattr(dxf_in, "load_dxf", dies)
    assert win.open_path(_dxf(tmp_path, _line)) is False
    assert win.documents() == [mine]
    assert errors == [("Import DXF failed", "bad entity on layer X")]


def test_the_untouched_tab_in_front_stays_untouched(win, errors, tmp_path):
    """The only tab cannot go (a window always has one): it stays as it was,
    with nothing to ask about on closing and ready to be reused."""
    mine = win.active_document()
    assert win.open_path(_dxf(tmp_path)) is False
    assert win.documents() == [mine]
    assert not win._is_dirty()
    assert win._doc_is_blank(mine)
    assert mine.import_name is None
    assert "*" not in win.windowTitle()


def test_import_from_the_menu_into_a_saved_project_keeps_it_saved(
        win, errors, tmp_path):
    from formats import igz as igz_format
    from core.scene import Scene
    path = tmp_path / "model.igz"
    igz_format.save_scene(Scene(), path)
    assert win.open_path(path)
    doc = win.active_document()
    assert win._import_dxf_path(_dxf(tmp_path)) is False
    assert not win._is_dirty()
    assert doc.path == path and doc.import_name is None
    assert not win.viewport.history.undo_stack


def test_a_dwg_with_nothing_to_import_goes_the_same_way(win, errors, tmp_path,
                                                        monkeypatch):
    _edit(win)
    mine = win.active_document()
    dxf = _dxf(tmp_path, name="converted.dxf")
    temp = tmp_path / "ingetrazo-dwg-x" / "intermediate.dxf"
    temp.parent.mkdir()

    def convert(self, _dwg):
        shutil.copy(dxf, temp)
        return temp
    monkeypatch.setattr(dwg_bridge, "have_dwg_support", lambda: True)
    monkeypatch.setattr(dwg_bridge.DwgConverter, "convert", convert)
    assert win.open_path(tmp_path / "furniture.dwg") is False
    assert win.documents() == [mine]
    assert not temp.exists()
    title, text = errors[0]
    assert title == "Import DWG failed"
    assert "furniture.dwg" in text and "intermediate" not in text


# ---- What works goes on working ---------------------------------------------
def test_a_good_drawing_still_comes_in_a_tab_of_its_own(win, errors, tmp_path):
    _edit(win)
    mine = win.active_document()
    assert win.open_path(_dxf(tmp_path, _line)) is True
    doc = win.active_document()
    assert doc is not mine
    assert doc.import_name == "drawing.dxf"
    assert doc.viewport.scene.groups
    assert not errors
    assert win._is_dirty() or doc.viewport.history.undo_stack
