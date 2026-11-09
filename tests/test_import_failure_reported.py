# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A mesh import that fails says so, and leaves things as they were.

``history.execute`` rolls a failed command back and does not raise, so the
``except`` around it never ran: a broken file read «Imported x» in the status
bar with no dialog, and opening one left an empty tab named after it. The
rollback also moves the version on, so an untouched project asked to be saved
(the DXF importer's fix, #1176, for the other mesh formats)."""
from __future__ import annotations

import json
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from core.history import AddEdgeCommand  # noqa: E402
from formats import dae, glb, obj, skp, stl  # noqa: E402
from views.filedialogs import file_dialogs  # noqa: E402


_app = QApplication.instance() or QApplication([])

_CUBE_OBJ = ("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\n").encode()

_GOOD_STL = (b"solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\n"
             b"vertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t\n")

_GOOD_DAE = b"""<?xml version="1.0"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<library_geometries><geometry id="g"><mesh>
<source id="p"><float_array id="a" count="9">0 0 0 1 0 0 0 1 0</float_array>
<technique_common><accessor source="#a" count="3" stride="3">
<param name="X" type="float"/><param name="Y" type="float"/>
<param name="Z" type="float"/></accessor></technique_common></source>
<vertices id="v"><input semantic="POSITION" source="#p"/></vertices>
<triangles count="1"><input semantic="VERTEX" source="#v" offset="0"/>
<p>0 1 2</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="s"><node id="n">
<instance_geometry url="#g"/></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#s"/></scene>
</COLLADA>"""

# What each importer was handed: not its format at all, or its format with
# nothing inside.
BROKEN = {
    "dae_garbage": ("broken.dae", b"<COLLADA><not closed"),
    "dae_empty": ("broken.dae", b"<COLLADA></COLLADA>"),
    "glb_garbage": ("broken.glb", b"glTF\x02\x00\x00\x00 not a real chunk"),
    "gltf_empty": ("broken.gltf", b'{"asset": {"version": "2.0"}}'),
    "obj_bad_vertex": ("broken.obj", b"v a b c\nf 1 2 3\n"),
    "obj_garbage": ("broken.obj", b"\x00\x01 this is no model\nat all\n"),
    "obj_no_faces": ("broken.obj", b"v 0 0 0\nv 1 0 0\n"),
    "obj_faces_out_of_range": ("broken.obj", b"v 0 0 0\nf 1 2 3\n"),
    "obj_degenerate": ("broken.obj", b"v 0 0 0\nv 0 0 0\nv 0 0 0\nf 1 2 3\n"),
    "obj_collinear": ("broken.obj", b"v 0 0 0\nv 1 0 0\nv 2 0 0\nf 1 2 3\n"),
    "stl_garbage": ("broken.stl", b"\x00\x01 no model"),
    "stl_truncated": ("broken.stl",
                      b"\0" * 80 + (5).to_bytes(4, "little") + b"\0" * 10),
    "stl_empty": ("broken.stl", b"solid t\nendsolid t\n"),
}
TITLES = {".dae": "Import DAE failed", ".glb": "Import glTF/GLB failed",
          ".gltf": "Import glTF/GLB failed", ".obj": "Import OBJ failed",
          ".stl": "Import STL failed"}


def _settle(ms: int = 0) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _edit(win):
    win.viewport.history.execute(AddEdgeCommand(V(0, 0, 5), V(1, 0, 5)))
    win.viewport.notify_scene_changed()


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _menu_import(win, path, monkeypatch):
    """The File ▸ Import entry for ``path``, with its file and unit dialogs
    answered."""
    monkeypatch.setattr(file_dialogs, "getOpenFileName",
                        lambda *_a, **_k: (str(path), ""))
    monkeypatch.setattr(win, "_obj_unit", lambda _p: 1.0, raising=True)
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.Accepted)
    {".dae": win._on_import_dae, ".glb": win._on_import_glb,
     ".gltf": win._on_import_glb, ".obj": win._on_import_obj,
     ".stl": win._on_import_stl}[path.suffix]()


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
    return shown


@pytest.mark.parametrize("case", BROKEN)
def test_a_broken_file_says_so_and_never_reads_imported(win, errors, tmp_path,
                                                        monkeypatch, case):
    path = _write(tmp_path, *BROKEN[case])
    _menu_import(win, path, monkeypatch)
    assert [title for title, _ in errors] == [TITLES[path.suffix]]
    assert errors[0][1]                             # with the reason
    assert "Imported" not in win.statusBar().currentMessage()


@pytest.mark.parametrize("case", BROKEN)
def test_a_broken_file_leaves_a_clean_project_clean(win, errors, tmp_path,
                                                    monkeypatch, case):
    mine = win.active_document()
    _menu_import(win, _write(tmp_path, *BROKEN[case]), monkeypatch)
    assert win.documents() == [mine]
    assert not win._is_dirty()
    assert mine.import_name is None
    assert win._doc_is_blank(mine)
    assert "*" not in win.windowTitle()
    assert not win.viewport.history.undo_stack


@pytest.mark.parametrize("case", BROKEN)
def test_a_broken_file_keeps_the_work_in_front(win, errors, tmp_path,
                                               monkeypatch, case):
    _edit(win)
    mine = win.active_document()
    edges = len(win.viewport.scene.mesh.edges)
    steps = len(win.viewport.history.undo_stack)
    _menu_import(win, _write(tmp_path, *BROKEN[case]), monkeypatch)
    assert win.documents() == [mine]
    assert win._is_dirty()                          # his work still counts
    assert len(win.viewport.scene.mesh.edges) == edges
    assert len(win.viewport.history.undo_stack) == steps


@pytest.mark.parametrize("case", ["dae_garbage", "dae_empty"])
def test_opening_a_broken_dae_leaves_no_tab_behind(win, errors, tmp_path, case):
    """The file association and the Open dialog land here (the DAE is the one
    mesh format they accept)."""
    _edit(win)
    mine = win.active_document()
    assert win.open_path(_write(tmp_path, *BROKEN[case])) is False
    assert win.documents() == [mine]
    assert win.active_document() is mine
    assert len(errors) == 1


def test_opening_a_broken_dae_on_the_only_tab_leaves_it_untouched(win, errors,
                                                                  tmp_path):
    mine = win.active_document()
    assert win.open_path(_write(tmp_path, *BROKEN["dae_garbage"])) is False
    assert win.documents() == [mine]
    assert not win._is_dirty()
    assert win._doc_is_blank(mine)


@pytest.mark.parametrize("module, loader, name, data", [
    (dae, "load_dae", "model.dae", _GOOD_DAE),
    (glb, "load_glb", "model.glb", b"unused"),
    (obj, "load_obj", "model.obj", _CUBE_OBJ),
], ids=["dae", "glb", "obj"])
def test_a_loader_that_dies_halfway_takes_back_what_it_did(
        win, errors, tmp_path, monkeypatch, module, loader, name, data):
    """A failure after some geometry went in: none of it stays."""
    _edit(win)
    edges = len(win.viewport.scene.mesh.edges)

    def dies(scene, *_a, **_k):
        scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)])
        raise RuntimeError("bad entity")
    monkeypatch.setattr(module, loader, dies)
    _menu_import(win, _write(tmp_path, name, data), monkeypatch)
    assert errors and errors[0][1] == "bad entity"
    assert len(win.viewport.scene.mesh.edges) == edges
    assert not win.viewport.scene.mesh.faces


def test_an_stl_that_fails_going_into_the_scene_is_said(win, errors, tmp_path,
                                                        monkeypatch):
    """The parse runs on a worker and always reported; the second step, on
    the UI thread, did not."""
    def dies(*_a, **_k):
        raise RuntimeError("bad mesh")
    monkeypatch.setattr(stl, "add_stl_mesh", dies)
    _menu_import(win, _write(tmp_path, "model.stl", _GOOD_STL), monkeypatch)
    assert errors == [("Import STL failed", "bad mesh")]
    assert not win._is_dirty()
    assert "Imported" not in win.statusBar().currentMessage()


def test_an_skp_that_fails_going_into_the_scene_is_said(win, errors, tmp_path,
                                                        monkeypatch):
    def dies(*_a, **_k):
        raise RuntimeError("bad payload")
    monkeypatch.setattr(skp, "can_handle", lambda _p: True)
    monkeypatch.setattr(win, "_parse_skp_threaded", lambda _p, _c: ({}, None))
    monkeypatch.setattr(skp, "apply_payload", dies)
    assert win.import_skp_path(tmp_path / "model.skp") is False
    assert errors == [("Import SKP failed", "bad payload")]
    assert not win._is_dirty()
    assert "Imported" not in win.statusBar().currentMessage()


# ---- What works goes on working ---------------------------------------------
@pytest.mark.parametrize("name, data", [
    ("good.dae", _GOOD_DAE), ("good.obj", _CUBE_OBJ), ("good.stl", _GOOD_STL),
], ids=["dae", "obj", "stl"])
def test_a_good_file_still_comes_in(win, errors, tmp_path, monkeypatch, name,
                                    data):
    _menu_import(win, _write(tmp_path, name, data), monkeypatch)
    assert not errors
    assert win.statusBar().currentMessage() == f"Imported {name}"
    assert win.active_document().import_name == name
    assert win.viewport.scene.mesh.faces
    assert win.viewport.history.undo_stack


def _good_glb() -> bytes:
    """One triangle, the smallest GLB there is."""
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    chunk = json.dumps({
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteLength": len(positions)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3,
                       "type": "VEC3"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}], "scene": 0,
    }).encode()
    chunk += b" " * (-len(chunk) % 4)
    total = 12 + 8 + len(chunk) + 8 + len(positions)
    return (struct.pack("<4sII", b"glTF", 2, total)
            + struct.pack("<I4s", len(chunk), b"JSON") + chunk
            + struct.pack("<I4s", len(positions), b"BIN\0") + positions)


def test_a_good_glb_still_comes_in(win, errors, tmp_path, monkeypatch):
    _menu_import(win, _write(tmp_path, "good.glb", _good_glb()), monkeypatch)
    assert not errors
    assert win.statusBar().currentMessage() == "Imported good.glb"
    assert win.active_document().import_name == "good.glb"
    assert win.viewport.scene.groups


def test_opening_a_good_dae_gets_a_tab_of_its_own(win, errors, tmp_path):
    _edit(win)
    mine = win.active_document()
    assert win.open_path(_write(tmp_path, "good.dae", _GOOD_DAE)) is True
    assert win.active_document() is not mine
    assert win.active_document().import_name == "good.dae"
    assert not errors
