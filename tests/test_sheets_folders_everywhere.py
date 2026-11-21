# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet explorer's folders and Print flag (#932) reach the sheet index
(#1409) and the sheets API / MCP tools (#1505): the index's «By folder»
layout lists the real folders, the API reads and moves sheets between
folders, and an export without a sheet list takes what Print all takes."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core import sheet_folders as sf  # noqa: E402
from core.composition import (Composicion, IndiceLaminas,  # noqa: E402
                              sheet_folder, toc_entries)
from core.scene import Scene  # noqa: E402
from core.sheet_folders import SheetFolder  # noqa: E402
from core.sheets_api import SheetError, SheetsAPI  # noqa: E402


def _doc():
    """Cover · Plans/{Ground, Roof/{Eaves}} · Details/{D1}."""
    scene = Scene()
    plans, details = SheetFolder("Plans"), SheetFolder("Details")
    roof = SheetFolder("Roof", parent_id=plans.id)
    scene.sheet_folders[:] = [plans, roof, details]
    for name, fid in (("Cover", None), ("Ground", plans.id),
                      ("Eaves", roof.id), ("D1", details.id)):
        c = Composicion(name=name)
        c.folder_id = fid
        scene.compositions.append(c)
    sf.sync_order(scene)
    return scene, plans, roof, details


def _names(comps):
    return [c.name for c in comps]


# ---- the index ----------------------------------------------------------------

def test_folder_path_walks_up_and_survives_a_cycle():
    scene, plans, roof, _ = _doc()
    assert sf.folder_path(scene, roof.id) == ("Plans", "Roof")
    assert sf.folder_path(scene, None) == ()
    assert sf.folder_path(scene, "gone") == ()
    plans.parent_id = roof.id                    # a damaged file
    assert set(sf.folder_path(scene, roof.id)) == {"Plans", "Roof"}


def test_the_index_by_folder_lists_the_explorer_s_folders():
    scene, *_ = _doc()
    eaves = next(c for c in scene.compositions if c.name == "Eaves")
    assert sheet_folder(eaves, scene) == ("Plans", "Roof")
    assert sheet_folder(eaves) == ()             # no scene: flat, as before
    toc = IndiceLaminas(layout="tree")
    rows = [(e.label, e.number, e.level, e.folder)
            for e in toc_entries(scene.compositions, toc, None, scene)]
    # The sheets in the explorer's order (= the document's), each folder
    # heading where its branch opens, numbers = what {hoja} prints.
    want = []
    open_path: tuple = ()
    for i, c in enumerate(sf.tree_order(scene)):
        path = sf.folder_path(scene, c.folder_id)
        same = 0
        while same < min(len(path), len(open_path)) \
                and path[same] == open_path[same]:
            same += 1
        want += [(path[d], "", d, True) for d in range(same, len(path))]
        open_path = path
        want.append((c.name, str(i + 1), len(path), False))
    assert rows == want
    assert [r[0] for r in rows if r[3]] == ["Plans", "Roof", "Details"]
    assert {r[0] for r in rows if not r[3]} == {"Cover", "Ground", "Eaves",
                                                "D1"}


def test_the_flat_index_keeps_the_document_order():
    scene, *_ = _doc()
    toc = IndiceLaminas()
    assert [e.label for e in toc_entries(scene.compositions, toc, None,
                                         scene)] == _names(scene.compositions)


# ---- the sheets API -----------------------------------------------------------

def test_list_and_get_say_folder_and_print_flag():
    scene, plans, roof, _ = _doc()
    plans.print_in_all = False
    api = SheetsAPI(scene)
    by = {s["name"]: s for s in api.list()}
    assert by["Eaves"]["folder"] == "Plans/Roof"
    assert by["Cover"]["folder"] == ""
    assert by["Eaves"]["print_in_all"] is True
    assert by["Eaves"]["printed"] is False       # its folder is off
    assert by["D1"]["printed"] is True
    assert api.get("Eaves")["folder"] == "Plans/Roof"


def test_list_folders_top_to_bottom():
    scene, plans, roof, details = _doc()
    rows = SheetsAPI(scene).list_folders()
    assert [(r["path"], r["sheets"]) for r in rows] == [
        ("Plans", ["Ground"]), ("Plans/Roof", ["Eaves"]),
        ("Details", ["D1"])]
    assert rows[1]["id"] == roof.id


def test_update_moves_into_a_folder_by_path_or_id_and_switches_print():
    scene, plans, roof, details = _doc()
    api = SheetsAPI(scene)
    api.update("Cover", folder="details")        # by path, any case
    cover = api.sheet("Cover")
    assert cover.folder_id == details.id
    assert _names(scene.compositions) == _names(sf.tree_order(scene))
    api.update("Cover", folder=roof.id)
    assert cover.folder_id == roof.id
    api.update("Cover", folder="")
    assert cover.folder_id is None
    api.update("Cover", print_in_all=False)
    assert cover.print_in_all is False
    assert cover not in sf.printed_sheets(scene)
    with pytest.raises(SheetError, match="no sheet folder"):
        api.update("Cover", folder="Nowhere")


def test_index_moves_stay_inside_the_tree():
    scene, *_ = _doc()
    api = SheetsAPI(scene)
    api.update("D1", index=0)                    # would jump out of Details
    assert _names(scene.compositions) == _names(sf.tree_order(scene))


def test_create_goes_into_the_folder_of_after_or_the_one_named():
    scene, plans, roof, details = _doc()
    api = SheetsAPI(scene)
    api.create("Ground 2", after="Ground", frame=False)
    assert api.sheet("Ground 2").folder_id == plans.id
    api.create("D2", folder="Details", frame=False)
    assert api.sheet("D2").folder_id == details.id
    assert _names(sf.sheets_in(scene, details.id)) == ["D1", "D2"]
    api.create("Loose", frame=False)
    assert api.sheet("Loose").folder_id is None
    assert _names(scene.compositions) == _names(sf.tree_order(scene))
    with pytest.raises(SheetError):
        api.create("X", folder="Nowhere", frame=False)
    assert "X" not in _names(scene.compositions)


# ---- export without a sheet list ----------------------------------------------

@pytest.fixture
def win():
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def test_export_without_sheets_takes_what_print_all_takes(win, tmp_path):
    scene = win.viewport.scene
    scene.compositions.clear()
    folder = SheetFolder("Off", print_in_all=False)
    scene.sheet_folders[:] = [folder]
    for name, fid, flag in (("A", None, True), ("B", None, False),
                            ("C", folder.id, True), ("D", None, True)):
        c = Composicion(name=name)
        c.folder_id, c.print_in_all = fid, flag
        scene.compositions.append(c)
    sf.sync_order(scene)
    out = win._ensure_composer().export_sheets(
        str(tmp_path / "s.png"), fmt="png", dpi=20)
    assert [Path(f).name for f in out["files"]] == ["s-01-A.png",
                                                     "s-02-D.png"]
