# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet sets in the interface (#1519), as reviewed: the «Plan sets» box of
a sheet's properties makes, renames, deletes and ticks sets; the sheet
explorer's Set box (shown once there are sets) picks what Print all and
Export all take; the file type picked is the export format."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core import sheet_sets as ss  # noqa: E402
from core.history import AddSheetSetCommand  # noqa: E402
from core.sheet_sets import SheetSet  # noqa: E402
from tests.test_sheet_browser import (_close, _pdf_pages, _sheet,  # noqa: E402
                                      _window)


@pytest.fixture
def doc():
    win, scene, explorer, *_ = _window()          # A · Plans/G · Plans/Details/D
    yield win, scene, explorer, win._composer
    _close(win)


def _rows(box):
    return [(box.list.item(i).text(),
             box.list.item(i).checkState() == Qt.Checked)
            for i in range(box.list.count())]


# ---- the Plan sets box ------------------------------------------------------------

def test_plus_makes_a_set_with_this_sheet_in_it_and_undo_takes_it(doc):
    win, scene, explorer, comp = doc
    box = comp.plan_sets
    comp.comp = _sheet(scene, "G")
    box.set_sheet(comp.comp)
    assert _rows(box) == []
    box.add_set()
    (st,) = scene.sheet_sets
    assert [c.name for c in ss.members(scene, st)] == ["G"]
    assert _rows(box) == [(st.name, True)]
    assert win.viewport.history.undo()
    assert scene.sheet_sets == []
    explorer.refresh()          # its once-a-second check: the box follows
    assert _rows(box) == []


def test_ticking_renaming_and_deleting(doc, monkeypatch):
    win, scene, explorer, comp = doc
    hist = win.viewport.history
    roofer, client = SheetSet("Roofer"), SheetSet("Client")
    hist.execute(AddSheetSetCommand(roofer))
    hist.execute(AddSheetSetCommand(client))
    box = comp.plan_sets
    d = _sheet(scene, "D")
    box.set_sheet(d)
    assert _rows(box) == [("Roofer", False), ("Client", False)]
    box.list.item(1).setCheckState(Qt.Checked)          # tick Client
    assert ss.sets_of_sheet(scene, d) == [client]
    box.list.item(0).setCheckState(Qt.Checked)
    assert ss.sets_of_sheet(scene, d) == [roofer, client]
    box.list.item(0).setCheckState(Qt.Unchecked)
    assert ss.sets_of_sheet(scene, d) == [client]
    box.list.item(1).setText("Owner")                   # an in-place rename
    assert client.name == "Owner"
    box.list.setCurrentRow(1)
    box.delete_current(ask=False)
    assert scene.sheet_sets == [roofer]
    assert d in scene.compositions                      # its sheets stay
    assert hist.undo()                                  # the set comes back
    assert scene.sheet_sets == [roofer, client] and client.name == "Owner"


def test_a_taken_name_is_refused(doc):
    win, scene, explorer, comp = doc
    hist = win.viewport.history
    hist.execute(AddSheetSetCommand(SheetSet("A")))
    hist.execute(AddSheetSetCommand(SheetSet("B")))
    box = comp.plan_sets
    box.set_sheet(_sheet(scene, "A"))
    box.list.item(1).setText("a")
    assert [s.name for s in scene.sheet_sets] == ["A", "B"]
    assert [r[0] for r in _rows(box)] == ["A", "B"]


def test_the_selected_sets_sheets_are_listed_below(doc):
    from PySide6.QtGui import QPalette
    win, scene, explorer, comp = doc
    hist = win.viewport.history
    a, g, d = (_sheet(scene, n) for n in "AGD")
    roofer, client = SheetSet("Roofer"), SheetSet("Client")
    hist.execute(AddSheetSetCommand(roofer, [d, a]))
    hist.execute(AddSheetSetCommand(client, [g]))
    box = comp.plan_sets
    box.set_sheet(g)
    # Shown at once: the first set this sheet is in.
    assert box.current_set() is client
    assert not box.members.isHidden()
    assert box.member_names() == ["G"]
    assert "Client" in box.members_caption.text()
    assert box.members.item(0).font().bold()            # the open sheet
    box.list.setCurrentRow(0)                           # pick Roofer
    assert box.member_names() == ["D", "A"]             # the explorer's order
    assert "Roofer" in box.members_caption.text()
    # Ticking the open sheet into the set adds it to the list.
    box.list.item(0).setCheckState(Qt.Checked)
    assert box.current_set() is roofer
    assert box.member_names() == ["D", "G", "A"]       # Details/D before G
    # A sheet that does not print is greyed.
    d.print_in_all = False
    box.refresh()
    muted = box.members.palette().color(QPalette.Disabled, QPalette.Text)
    assert box.members.item(0).foreground().color() == muted
    assert box.members.item(2).foreground().color() != muted
    # A double-click opens the sheet.
    box.members.itemActivated.emit(box.members.item(2))
    assert comp.comp is a


def test_the_sheet_list_hides_without_sets(doc):
    win, scene, explorer, comp = doc
    box = comp.plan_sets
    box.set_sheet(_sheet(scene, "A"))
    assert box.current_set() is None
    assert box.members.isHidden() and box.members_caption.isHidden()


# ---- the explorer's Set box -----------------------------------------------------

def test_the_set_box_shows_once_there_are_sets_and_greys_the_others(doc):
    win, scene, explorer, comp = doc
    assert explorer.set_row.isHidden()
    st = SheetSet("Roofer")
    win.viewport.history.execute(AddSheetSetCommand(
        st, [_sheet(scene, "D"), _sheet(scene, "A")]))
    explorer.refresh(force=True)
    assert not explorer.set_row.isHidden()
    assert [explorer.set_combo.itemText(i)
            for i in range(explorer.set_combo.count())] == [
        "All sheets", "Roofer"]
    explorer.set_combo.setCurrentIndex(1)
    assert explorer.current_set_id() == st.id
    grey = explorer.items[id(_sheet(scene, "G"))].foreground(0).color()
    own = explorer.items[id(_sheet(scene, "D"))].foreground(0).color()
    assert grey != own
    assert "2 sheets" in explorer.print_btn.toolTip()
    win.viewport.history.undo()                          # the set goes
    explorer.refresh(force=True)
    assert explorer.current_set_id() is None and explorer.set_row.isHidden()


def test_print_and_export_take_the_chosen_set(doc, tmp_path, monkeypatch):
    win, scene, explorer, comp = doc
    st = SheetSet("Roofer")
    win.viewport.history.execute(AddSheetSetCommand(
        st, [_sheet(scene, "D"), _sheet(scene, "A")]))
    explorer.refresh(force=True)
    explorer.set_combo.setCurrentIndex(1)
    printed = []
    monkeypatch.setattr(comp, "print_sheets",
                        lambda sheets, parent=None, printer=None,
                        sheet_set=None: printed.append(
                            ([c.name for c in sheets], sheet_set)))
    explorer.print_all()
    # The tree's order: G and D sit in Plans above A.
    assert printed == [(["D", "A"], st.id)]
    explorer.export_all(str(tmp_path / "roofer.pdf"))
    assert len(_pdf_pages(tmp_path / "roofer.pdf")) == 2


def test_the_file_type_picked_is_the_format(doc, tmp_path, monkeypatch):
    from views.filedialogs import file_dialogs
    win, scene, explorer, comp = doc
    st = SheetSet("Roofer")
    win.viewport.history.execute(AddSheetSetCommand(
        st, [_sheet(scene, "G"), _sheet(scene, "A")]))
    win._current_path = tmp_path / "Casa.igz"
    explorer.refresh(force=True)
    explorer.set_combo.setCurrentIndex(1)
    offered = []
    monkeypatch.setattr(
        file_dialogs, "getSaveFileName",
        lambda parent, title, name, filters, *a, **k: offered.append(
            (title, name, filters)) or (str(tmp_path / "out.svg"), ""))
    explorer.export_all()
    title, name, filters = offered[0]
    assert "Roofer" in title and name == str(tmp_path / "Casa-Roofer.pdf")
    assert "PNG" in filters and "SVG" in filters
    assert sorted(p.name for p in tmp_path.glob("out-*.svg")) == [
        "out-01-G.svg", "out-02-A.svg"]
    win._current_path = None
