# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet sets (#1519): named, ordered selections of the sheets — the
model, saving, undo, and what printing a set takes."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core import sheet_folders as sf  # noqa: E402
from core import sheet_sets as ss  # noqa: E402
from core.composition import Composicion  # noqa: E402
from core.history import (AddSheetSetCommand, DeleteSheetSetCommand,  # noqa: E402
                          EditSheetSetCommand, History,
                          RenameSheetSetCommand, SetSheetSetsOfSheetCommand,
                          SnapshotImport)
from core.scene import Scene  # noqa: E402
from core.sheet_folders import SheetFolder  # noqa: E402
from core.sheet_sets import SheetSet, SheetSetError  # noqa: E402
from formats import igz  # noqa: E402


def _doc(n=5):
    scene = Scene()
    scene.compositions[:] = [Composicion(name=f"S{i + 1}") for i in range(n)]
    return scene


def _sheet(scene, name):
    return next(c for c in scene.compositions if c.name == name)


def _names(comps):
    return [c.name for c in comps]


def _history(scene):
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication(sys.argv[:1])
    return History(scene)


# ---- the model ------------------------------------------------------------------

def test_a_sheet_gets_its_uid_when_it_first_joins_a_set():
    scene = _doc()
    s1 = _sheet(scene, "S1")
    assert s1.uid == "" and "uid" not in s1.to_dict()
    roofer = SheetSet("Roofer")
    scene.sheet_sets.append(roofer)
    ss.add_to_set(scene, roofer, s1)
    assert s1.uid and s1.to_dict()["uid"] == s1.uid
    assert roofer.sheet_uids == [s1.uid]


def test_joining_a_set_keeps_the_explorer_s_order():
    scene = _doc()
    st = SheetSet("Client")
    scene.sheet_sets.append(st)
    for name in ("S4", "S1", "S3"):
        ss.add_to_set(scene, st, _sheet(scene, name))
    assert _names(ss.members(scene, st)) == ["S1", "S3", "S4"]


def test_a_set_keeps_its_own_order_and_the_cover_comes_first():
    scene = _doc()
    st = SheetSet("Permit")
    scene.sheet_sets.append(st)
    ss.set_members(scene, st, [_sheet(scene, n) for n in ("S5", "S2", "S3")])
    st.cover_uid = ss.sheet_uid(_sheet(scene, "S1"))
    assert _names(ss.members(scene, st)) == ["S1", "S5", "S2", "S3"]
    scene.compositions.reverse()             # the document's order moves…
    assert _names(ss.members(scene, st)) == ["S1", "S5", "S2", "S3"]


def test_a_sheet_in_several_sets_and_a_renamed_one_stays():
    scene = _doc()
    a, b = SheetSet("A"), SheetSet("B")
    scene.sheet_sets[:] = [a, b]
    s2 = _sheet(scene, "S2")
    ss.set_sheet_sets(scene, s2, [a, b])
    assert ss.sets_of_sheet(scene, s2) == [a, b]
    s2.name = "Ground floor"
    assert _names(ss.members(scene, a)) == ["Ground floor"]
    ss.set_sheet_sets(scene, s2, [b])
    assert ss.sets_of_sheet(scene, s2) == [b] and a.sheet_uids == []


def test_find_set_by_name_id_or_all_sheets():
    scene = _doc()
    st = SheetSet("Roofer")
    scene.sheet_sets.append(st)
    assert ss.find_set(scene, "roofer") is st
    assert ss.find_set(scene, st.id) is st
    assert ss.find_set(scene, None) is None
    assert ss.find_set(scene, "") is None
    assert ss.find_set(scene, "All sheets") is None
    with pytest.raises(SheetSetError, match="no sheet set"):
        ss.find_set(scene, "Carpenter")


def test_the_print_flag_filters_a_set_too():
    scene = _doc()
    off = SheetFolder("Off", print_in_all=False)
    scene.sheet_folders.append(off)
    _sheet(scene, "S2").folder_id = off.id
    _sheet(scene, "S4").print_in_all = False
    sf.sync_order(scene)
    st = SheetSet("All of them")
    scene.sheet_sets.append(st)
    ss.set_members(scene, st, list(scene.compositions))
    assert _names(ss.export_list(scene, st)) == ["S1", "S3", "S5"]
    assert _names(ss.export_list(scene, None)) == ["S1", "S3", "S5"]


def test_prune_and_repair():
    scene = _doc()
    st = SheetSet("X")
    scene.sheet_sets.append(st)
    ss.set_members(scene, st, scene.compositions[:3])
    st.cover_uid = ss.sheet_uid(scene.compositions[4])
    gone = scene.compositions.pop(0)
    scene.compositions.pop()                 # the cover
    assert ss.prune(scene) == 2
    assert gone.uid not in st.sheet_uids and st.cover_uid == ""
    # A damaged file: a copied sheet with the same uid, twin sets.
    scene.compositions[1].uid = scene.compositions[0].uid
    twin = SheetSet("x", id=st.id, sheet_uids=[scene.compositions[0].uid] * 2)
    scene.sheet_sets.append(twin)
    assert ss.repair(scene) >= 3
    uids = [c.uid for c in scene.compositions if c.uid]
    assert len(uids) == len(set(uids))
    assert twin.id != st.id and twin.name == "x (2)"
    assert twin.sheet_uids == [scene.compositions[0].uid]


# ---- saving -----------------------------------------------------------------------

def _round_trip(scene, tmp_path, fmt="auto"):
    path = tmp_path / "m.igz"
    igz.save_scene(scene, path, fmt=fmt)
    back = Scene()
    igz.load_into(back, path)
    return back, path


@pytest.mark.parametrize("fmt", ["auto", "json"])
def test_sets_survive_save_and_open(tmp_path, fmt):
    scene = _doc()
    st = SheetSet("Roofer", description="Roof plan and details")
    scene.sheet_sets.append(st)
    ss.set_members(scene, st, [_sheet(scene, "S4"), _sheet(scene, "S2")])
    st.cover_uid = ss.sheet_uid(_sheet(scene, "S1"))
    back, _ = _round_trip(scene, tmp_path, fmt)
    (b,) = back.sheet_sets
    assert (b.id, b.name, b.description) == (st.id, "Roofer",
                                             "Roof plan and details")
    assert _names(ss.members(back, b)) == ["S1", "S4", "S2"]


def test_a_document_without_sets_saves_as_before(tmp_path):
    scene = _doc(2)
    _, path = _round_trip(scene, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))["scene"]
    assert "sheet_sets" not in data
    assert all("uid" not in c for c in data["compositions"])


def test_a_copied_sheet_is_in_none_of_the_sets(tmp_path):
    from core.sheets_api import SheetsAPI
    scene = _doc(2)
    st = SheetSet("A")
    scene.sheet_sets.append(st)
    ss.add_to_set(scene, st, _sheet(scene, "S1"))
    api = SheetsAPI(scene)
    api.create("Copy", template="S1")
    assert _sheet(scene, "Copy").uid == ""
    assert _names(ss.members(scene, st)) == ["S1"]


def test_deleting_a_sheet_leaves_every_set_but_a_set_keeps_the_sheets():
    from core.sheets_api import SheetsAPI
    scene = _doc(3)
    a, b = SheetSet("A"), SheetSet("B")
    scene.sheet_sets[:] = [a, b]
    s2 = _sheet(scene, "S2")
    ss.set_sheet_sets(scene, s2, [a, b])
    SheetsAPI(scene).delete("S2", confirm=True)
    assert a.sheet_uids == [] and b.sheet_uids == []
    ss.set_sheet_sets(scene, _sheet(scene, "S1"), [a])
    scene.sheet_sets.remove(a)
    assert _names(scene.compositions) == ["S1", "S3"]


def test_new_document_clears_the_sets():
    scene = _doc(1)
    scene.compositions.clear()
    scene.sheet_sets.append(SheetSet("only"))
    scene.clear()                             # sets alone count as content
    assert scene.sheet_sets == []


# ---- undo -------------------------------------------------------------------------

def test_add_rename_delete_are_steps():
    scene = _doc()
    h = _history(scene)
    st = SheetSet("Roofer")
    h.execute(AddSheetSetCommand(st, [_sheet(scene, "S3"),
                                      _sheet(scene, "S1")]))
    assert scene.sheet_sets == [st]
    assert _names(ss.members(scene, st)) == ["S1", "S3"]
    h.execute(AddSheetSetCommand(SheetSet("roofer")))
    assert scene.sheet_sets[1].name == "roofer (2)"
    h.undo()
    h.execute(RenameSheetSetCommand(st, "Roof"))
    assert st.name == "Roof"
    h.execute(DeleteSheetSetCommand(st))
    assert scene.sheet_sets == []
    h.undo()
    assert scene.sheet_sets == [st] and st.name == "Roof"
    h.undo()
    assert st.name == "Roofer"
    h.undo()
    assert scene.sheet_sets == []
    assert _sheet(scene, "S1").uid == ""      # the uid it got goes back too
    h.redo()
    assert scene.sheet_sets == [st]
    assert _names(ss.members(scene, st)) == ["S1", "S3"]


def test_a_taken_name_is_refused_and_nothing_changes():
    scene = _doc()
    h = _history(scene)
    a, b = SheetSet("A"), SheetSet("B")
    h.execute(AddSheetSetCommand(a))
    h.execute(AddSheetSetCommand(b))
    h.execute(RenameSheetSetCommand(b, "a"))
    assert b.name == "B"


def test_edit_members_cover_description_and_per_sheet_sets():
    scene = _doc()
    h = _history(scene)
    a, b = SheetSet("A"), SheetSet("B")
    h.execute(AddSheetSetCommand(a))
    h.execute(AddSheetSetCommand(b))
    h.execute(EditSheetSetCommand(a, [_sheet(scene, "S5"),
                                      _sheet(scene, "S2")],
                                  cover=_sheet(scene, "S1"),
                                  description="for the roofer"))
    assert _names(ss.members(scene, a)) == ["S1", "S5", "S2"]
    s3 = _sheet(scene, "S3")
    h.execute(SetSheetSetsOfSheetCommand(s3, [a, b]))
    assert ss.sets_of_sheet(scene, s3) == [a, b]
    h.undo()
    assert ss.sets_of_sheet(scene, s3) == []
    h.undo()
    assert a.sheet_uids == [] and a.cover_uid == "" and a.description == ""
    h.redo()
    h.redo()
    # S3 joins before the first member that follows it in the document.
    assert _names(ss.members(scene, a)) == ["S1", "S3", "S5", "S2"]
    h.execute(EditSheetSetCommand(a, cover=False))
    assert a.cover_uid == ""


def test_an_edit_through_the_api_scope_is_one_step():
    """SnapshotImport (run_python, the sheet tools) tracks the sets: one
    added, and one edited inside, both come back on undo."""
    scene = _doc()
    h = _history(scene)
    keep = SheetSet("Keep")
    scene.sheet_sets.append(keep)

    def mutate(s):
        s.sheet_sets.append(SheetSet("New"))
        ss.add_to_set(s, keep, _sheet(s, "S2"))
    cmd = SnapshotImport(mutate)
    h.execute(cmd)
    assert cmd.changed
    assert [x.name for x in scene.sheet_sets] == ["Keep", "New"]
    h.undo()
    assert [x.name for x in scene.sheet_sets] == ["Keep"]
    assert keep.sheet_uids == []
