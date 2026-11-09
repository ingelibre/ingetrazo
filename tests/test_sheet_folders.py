# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet folders (core.sheet_folders): the tree the sheet explorer shows,
its undoable edits, and its trip through the .igz.

The sheet order (``scene.compositions``) follows the tree read top to
bottom — in each folder its subfolders first, then its own sheets — so the
sheet tabs, the PDF atlas and {hoja} count the way the explorer shows."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from core import sheet_folders as sf  # noqa: E402
from core.composition import Composicion  # noqa: E402
from core.history import (  # noqa: E402
    AddSheetFolderCommand, DeleteSheetFoldersCommand, History,
    MoveSheetItemsCommand, RenameSheetFolderCommand, SetSheetPrintCommand,
    SnapshotImport,
)
from core.scene import Scene  # noqa: E402
from core.sheet_folders import SheetFolder  # noqa: E402
from formats import igz  # noqa: E402


def _names(sheets):
    return [c.name for c in sheets]


def _doc():
    """Plans ▸ (Ground, Upper ▸ (Roof)), Details; sheets A at the top, G in
    Plans, R in Roof, D in Details."""
    scene = Scene()
    plans = SheetFolder("Plans")
    roof = SheetFolder("Roof", parent_id=plans.id)
    details = SheetFolder("Details")
    scene.sheet_folders[:] = [plans, roof, details]
    scene.compositions[:] = [
        Composicion(name="A"),
        Composicion(name="G", folder_id=plans.id),
        Composicion(name="R", folder_id=roof.id),
        Composicion(name="D", folder_id=details.id)]
    sf.sync_order(scene)
    return scene, plans, roof, details


def _sheet(scene, name):
    return next(c for c in scene.compositions if c.name == name)


# ---- The tree --------------------------------------------------------------

def test_the_sheet_order_follows_the_tree():
    scene, *_ = _doc()
    # Plans: Roof's R first (a subfolder), then Plans' own G; Details' D;
    # then the top's own A.
    assert _names(scene.compositions) == ["R", "G", "D", "A"]


def test_a_document_without_folders_keeps_its_order():
    scene = Scene()
    scene.compositions[:] = [Composicion(name=n) for n in "CAB"]
    assert not sf.sync_order(scene)
    assert _names(scene.compositions) == ["C", "A", "B"]


def test_printed_sheets_are_the_ticked_ones_in_tree_order():
    scene, *_ = _doc()
    _sheet(scene, "G").print_in_all = False
    assert _names(sf.printed_sheets(scene)) == ["R", "D", "A"]


def test_descendants_reach_every_depth():
    scene, plans, roof, details = _doc()
    assert sf.descendant_ids(scene, plans.id) == {roof.id}
    assert sf.descendant_ids(scene, None) == {plans.id, roof.id, details.id}


# ---- Commands ----------------------------------------------------------------

def test_add_and_rename_a_folder_with_undo():
    scene, plans, *_ = _doc()
    hist = History(scene)
    new = SheetFolder("Sections", parent_id=plans.id)
    hist.execute(AddSheetFolderCommand(new))
    assert new in scene.sheet_folders and new.parent_id == plans.id
    hist.execute(RenameSheetFolderCommand(new, "Cuts"))
    assert new.name == "Cuts"
    hist.undo()
    assert new.name == "Sections"
    hist.undo()
    assert new not in scene.sheet_folders
    hist.redo()
    hist.redo()
    assert new in scene.sheet_folders and new.name == "Cuts"


def test_deleting_a_folder_moves_its_contents_one_level_up():
    scene, plans, roof, _details = _doc()
    hist = History(scene)
    hist.execute(DeleteSheetFoldersCommand([plans]))
    assert plans not in scene.sheet_folders
    assert roof.parent_id is None                  # up to the top
    assert _sheet(scene, "G").folder_id is None
    assert _sheet(scene, "R").folder_id == roof.id  # stays in Roof
    assert len(scene.compositions) == 4             # no sheet deleted
    hist.undo()
    assert plans in scene.sheet_folders and roof.parent_id == plans.id
    assert _sheet(scene, "G").folder_id == plans.id
    assert _names(scene.compositions) == ["R", "G", "D", "A"]


def test_deleting_a_folder_and_its_parent_lands_above_both():
    scene, plans, roof, _details = _doc()
    History(scene).execute(DeleteSheetFoldersCommand([roof, plans]))
    assert _sheet(scene, "R").folder_id is None
    assert _sheet(scene, "G").folder_id is None


def test_moving_sheets_into_a_folder_reorders_the_set():
    scene, plans, roof, details = _doc()
    hist = History(scene)
    hist.execute(MoveSheetItemsCommand([_sheet(scene, "A")], [], details.id))
    assert _sheet(scene, "A").folder_id == details.id
    assert _names(scene.compositions) == ["R", "G", "D", "A"]
    # In front of D, inside Details.
    hist.execute(MoveSheetItemsCommand([_sheet(scene, "A")], [], details.id,
                                       before=_sheet(scene, "D")))
    assert _names(scene.compositions) == ["R", "G", "A", "D"]
    hist.undo()
    hist.undo()
    assert _sheet(scene, "A").folder_id is None
    assert _names(scene.compositions) == ["R", "G", "D", "A"]


def test_moving_a_folder_takes_everything_inside_it():
    scene, plans, roof, details = _doc()
    History(scene).execute(MoveSheetItemsCommand([], [roof], details.id))
    assert roof.parent_id == details.id
    # Details: Roof (R) first, then D; Plans now only G.
    assert _names(scene.compositions) == ["G", "R", "D", "A"]


def test_a_folder_cannot_go_into_itself_or_below_itself():
    scene, plans, roof, _details = _doc()
    hist = History(scene)
    hist.execute(MoveSheetItemsCommand([], [plans], roof.id))
    assert plans.parent_id is None
    hist.execute(MoveSheetItemsCommand([], [plans], plans.id))
    assert plans.parent_id is None
    assert not sf.can_move_folder(scene, plans, roof.id)
    assert sf.can_move_folder(scene, roof, None)


def test_a_folder_moves_in_front_of_another():
    scene, plans, _roof, details = _doc()
    History(scene).execute(MoveSheetItemsCommand([], [details], None,
                                                 before=plans))
    assert _names(scene.compositions) == ["D", "R", "G", "A"]


def test_the_print_flag_is_one_undo_step_for_several_sheets():
    scene, *_ = _doc()
    hist = History(scene)
    two = [_sheet(scene, "A"), _sheet(scene, "D")]
    hist.execute(SetSheetPrintCommand(two, False))
    assert not any(c.print_in_all for c in two)
    hist.undo()
    assert all(c.print_in_all for c in two)


def test_undo_keeps_the_sheets_made_or_deleted_outside_it():
    """The composer adds and deletes sheets without this undo: undoing a
    tree change must not bring a deleted sheet back nor drop a new one."""
    scene, plans, _roof, details = _doc()
    hist = History(scene)
    hist.execute(SetSheetPrintCommand([_sheet(scene, "A")], False))
    hist.execute(MoveSheetItemsCommand([_sheet(scene, "A")], [], plans.id))
    gone = _sheet(scene, "D")
    scene.compositions.remove(gone)                       # the composer's
    new = Composicion(name="N", folder_id=details.id)
    scene.compositions.insert(0, new)                     # the composer's
    hist.undo()                                           # the move
    hist.undo()                                           # the print flag
    assert gone not in scene.compositions
    assert new in scene.compositions and new.folder_id == details.id
    assert _sheet(scene, "A").folder_id is None
    assert _sheet(scene, "A").print_in_all
    assert scene.compositions == sf.tree_order(scene)
    hist.redo()
    assert not _sheet(scene, "A").print_in_all and new in scene.compositions


def test_a_sheet_in_a_folder_an_undo_takes_away_moves_to_the_top():
    scene = Scene()
    hist = History(scene)
    folder = SheetFolder("New")
    hist.execute(AddSheetFolderCommand(folder))
    sheet = Composicion(name="S", folder_id=folder.id)    # made in it
    scene.compositions.append(sheet)
    hist.undo()                                           # the folder goes
    assert sheet in scene.compositions and sheet.folder_id is None


def test_a_failing_import_leaves_no_folder_behind():
    scene = Scene()
    hist = History(scene)

    def boom(s):
        s.sheet_folders.append(SheetFolder("half"))
        raise RuntimeError("loader died")
    hist.execute(SnapshotImport(boom))
    assert scene.sheet_folders == []


def test_an_import_brings_its_folders_and_undo_takes_them():
    scene = Scene()
    hist = History(scene)
    hist.execute(SnapshotImport(
        lambda s: s.sheet_folders.append(SheetFolder("In"))))
    assert [f.name for f in scene.sheet_folders] == ["In"]
    hist.undo()
    assert scene.sheet_folders == []
    hist.redo()
    assert [f.name for f in scene.sheet_folders] == ["In"]


def test_new_document_clears_the_folders():
    scene, *_ = _doc()
    scene.compositions.clear()
    scene.clear()
    assert scene.sheet_folders == []
    only_folders = Scene()
    only_folders.sheet_folders.append(SheetFolder("x"))
    only_folders.clear()                 # folders alone count as content
    assert only_folders.sheet_folders == []


# ---- .igz -----------------------------------------------------------------------

def _round_trip(scene, tmp_path):
    path = tmp_path / "m.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    return back, path


def test_folders_flags_and_order_survive_save_and_open(tmp_path):
    scene, plans, roof, details = _doc()
    roof.expanded = False
    _sheet(scene, "D").print_in_all = False
    back, _ = _round_trip(scene, tmp_path)
    assert [(f.id, f.name, f.parent_id, f.expanded)
            for f in back.sheet_folders] == [
        (plans.id, "Plans", None, True), (roof.id, "Roof", plans.id, False),
        (details.id, "Details", None, True)]
    assert _names(back.compositions) == ["R", "G", "D", "A"]
    assert [c.folder_id for c in back.compositions] == [
        roof.id, plans.id, details.id, None]
    assert [c.print_in_all for c in back.compositions] == [
        True, True, False, True]


def test_a_document_without_folders_saves_as_before(tmp_path):
    scene = Scene()
    scene.compositions.append(Composicion(name="L-01"))
    path = tmp_path / "m.igz"
    igz.save_scene(scene, path)
    data = json.loads(path.read_text(encoding="utf-8"))["scene"]
    assert "sheet_folders" not in data
    assert "folder_id" not in data["compositions"][0]
    assert "print_in_all" not in data["compositions"][0]


def test_an_old_file_opens_flat_with_every_sheet_printed(tmp_path):
    scene = Scene()
    scene.compositions[:] = [Composicion(name=n) for n in ("B", "A")]
    path = tmp_path / "old.igz"
    igz.save_scene(scene, path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scene"].pop("sheet_folders", None)      # as a file from before
    path.write_text(json.dumps(doc), encoding="utf-8")
    back = Scene()
    igz.load_into(back, path)
    assert back.sheet_folders == []
    assert _names(back.compositions) == ["B", "A"]
    assert all(c.folder_id is None and c.print_in_all
               for c in back.compositions)


@pytest.mark.parametrize("damage", ["missing_folder", "missing_parent",
                                    "cycle", "duplicate_id"])
def test_a_damaged_tree_still_opens(tmp_path, damage):
    scene, plans, roof, details = _doc()
    path = tmp_path / "m.igz"
    igz.save_scene(scene, path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    data = doc["scene"]
    folders = data["sheet_folders"]
    if damage == "missing_folder":
        data["sheet_folders"] = [f for f in folders if f["id"] != details.id]
    elif damage == "missing_parent":
        data["sheet_folders"] = [f for f in folders if f["id"] != plans.id]
    elif damage == "cycle":
        for f in folders:
            if f["id"] == plans.id:
                f["parent_id"] = roof.id         # Plans inside Roof inside Plans
    else:
        folders[2]["id"] = folders[0]["id"]      # Details takes Plans' id
    path.write_text(json.dumps(doc), encoding="utf-8")
    back = Scene()
    igz.load_into(back, path)
    assert len(back.compositions) == 4           # every sheet is there
    ids = [f.id for f in back.sheet_folders]
    assert len(ids) == len(set(ids))
    known = set(ids)
    assert all(c.folder_id is None or c.folder_id in known
               for c in back.compositions)
    assert all(f.parent_id is None or f.parent_id in known
               for f in back.sheet_folders)
    for f in back.sheet_folders:                 # no folder inside itself
        assert f.id not in sf.descendant_ids(back, f.id)
    assert _names(back.compositions) == _names(sf.tree_order(back))


def test_autosave_and_recovery_bring_the_folders_back(tmp_path, monkeypatch):
    from core import autosave
    monkeypatch.setattr(autosave, "autosave_dir", lambda: tmp_path)
    scene, plans, roof, _details = _doc()
    slot = autosave.write(scene, None)
    back = Scene()
    igz.load_into(back, slot)
    assert [f.name for f in back.sheet_folders] == ["Plans", "Roof",
                                                    "Details"]
    assert _sheet(back, "R").folder_id == roof.id


def test_a_duplicated_sheet_stays_in_its_folder():
    scene, plans, *_ = _doc()
    dup = Composicion.from_dict(_sheet(scene, "G").to_dict())
    assert dup.folder_id == plans.id
