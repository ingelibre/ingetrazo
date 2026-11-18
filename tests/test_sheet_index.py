# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet index — a table of contents of the document's sheets (#1409).

It reads the sheets live, numbers them as ``{hoja}`` does, splits over
several elements (``per_page`` / ``page``) and, ready for sheet folders,
lists them by folder when a sheet carries one."""
from __future__ import annotations

import pytest

from core.composition import (AddItemCommand, Composicion, IndiceLaminas,
                              RemoveItemCommand, sheet_folder, toc_entries,
                              toc_page_count, toc_slice)


def _sheets(*names):
    return [Composicion(name=n) for n in names]


# ---- the rows ---------------------------------------------------------------
def test_one_row_per_sheet_numbered_by_position():
    comps = _sheets("Cover", "Plan", "Section")
    rows = toc_entries(comps, IndiceLaminas(), here=comps[0])
    assert [(r.label, r.number) for r in rows] == [
        ("Cover", "1"), ("Plan", "2"), ("Section", "3")]
    assert [r.current for r in rows] == [True, False, False]
    assert not any(r.folder or r.level for r in rows)


def test_the_sheet_holding_the_index_can_be_left_out():
    comps = _sheets("Cover", "Plan", "Section")
    rows = toc_entries(comps, IndiceLaminas(include_self=False),
                       here=comps[0])
    # the other sheets keep their own numbers
    assert [(r.label, r.number) for r in rows] == [("Plan", "2"),
                                                   ("Section", "3")]


def test_a_renamed_sheet_reads_its_new_name():
    comps = _sheets("Cover", "Plan")
    ix = IndiceLaminas()
    comps[1].name = "Ground floor"
    assert toc_entries(comps, ix)[1].label == "Ground floor"


# ---- split over several sheets ---------------------------------------------
def test_per_page_splits_the_index_and_page_picks_the_slice():
    comps = _sheets(*[f"S{i}" for i in range(1, 8)])        # 7 sheets
    ix = IndiceLaminas(per_page=3, page=2)
    rows, page, pages = toc_slice(toc_entries(comps, ix), ix)
    assert [r.label for r in rows] == ["S4", "S5", "S6"]
    assert (page, pages) == (2, 3)
    ix.page = 3
    rows, page, pages = toc_slice(toc_entries(comps, ix), ix)
    assert [r.label for r in rows] == ["S7"]


def test_a_page_past_the_end_shows_the_last_one():
    comps = _sheets("A", "B", "C")
    ix = IndiceLaminas(per_page=2, page=9)
    rows, page, pages = toc_slice(toc_entries(comps, ix), ix)
    assert (page, pages) == (2, 2) and [r.label for r in rows] == ["C"]


def test_no_split_is_one_page_with_everything():
    comps = _sheets("A", "B", "C")
    ix = IndiceLaminas(per_page=0, page=4)
    rows, page, pages = toc_slice(toc_entries(comps, ix), ix)
    assert (len(rows), page, pages) == (3, 1, 1)
    assert toc_page_count(0, 5) == 1 and toc_page_count(11, 5) == 3


def test_a_split_index_keeps_a_full_page_height():
    """The last, shorter slice is as tall as the others: indices on
    consecutive sheets line up."""
    ix = IndiceLaminas(per_page=10)
    assert ix.height_mm(3) == ix.height_mm(10)
    free = IndiceLaminas()
    assert free.height_mm(3) < free.height_mm(10)


def test_text_size_and_title_set_the_height():
    small, big = IndiceLaminas(size_pt=8), IndiceLaminas(size_pt=16)
    assert big.height_mm(5) > small.height_mm(5)
    assert (IndiceLaminas(show_title=False).height_mm(5)
            < IndiceLaminas(show_title=True).height_mm(5))


# ---- prepared for sheet folders ----------------------------------------------
def test_sheet_folder_reads_a_path_or_a_list():
    c = Composicion()
    assert sheet_folder(c) == ()                  # sheets have no folder yet
    c.folder = "Plans / Ground floor"
    assert sheet_folder(c) == ("Plans", "Ground floor")
    c.folder = ["Details"]
    assert sheet_folder(c) == ("Details",)


def test_tree_layout_without_folders_is_the_flat_list():
    comps = _sheets("A", "B")
    assert (toc_entries(comps, IndiceLaminas(layout="tree"))
            == toc_entries(comps, IndiceLaminas(layout="flat")))


def test_tree_layout_groups_sheets_under_their_folders():
    comps = _sheets("Cover", "GF plan", "Door detail", "FF plan")
    comps[1].folder = "Plans/Ground"
    comps[2].folder = "Details"
    comps[3].folder = "Plans/First"
    rows = toc_entries(comps, IndiceLaminas(layout="tree"))
    assert [(r.label, r.number, r.level, r.folder) for r in rows] == [
        ("Cover", "1", 0, False),
        ("Plans", "", 0, True),
        ("Ground", "", 1, True),
        ("GF plan", "2", 2, False),
        ("First", "", 1, True),
        ("FF plan", "4", 2, False),
        ("Details", "", 0, True),
        ("Door detail", "3", 1, False),
    ]


# ---- the sheet keeps it ---------------------------------------------------------
def test_round_trip_through_the_igz_record():
    c = Composicion()
    c.indices.append(IndiceLaminas(x_mm=15, title="INDEX", size_pt=11,
                                   leader="line", show_numbers=False,
                                   layout="tree", per_page=12, page=2,
                                   include_self=False, border=False))
    back = Composicion.from_dict(c.to_dict())
    assert back.indices == c.indices
    assert back.indices[0] in back.all_items()


def test_a_sheet_without_an_index_saves_no_key():
    assert "indices" not in Composicion().to_dict()


def test_keys_from_a_newer_version_are_ignored():
    d = Composicion().to_dict()
    d["indices"] = [{"title": "X", "columns": 2}]
    assert Composicion.from_dict(d).indices[0].title == "X"


def test_add_and_remove_are_undoable():
    c = Composicion()
    ix = IndiceLaminas()
    add = AddItemCommand(c, ix)
    add.do()
    assert c.indices == [ix]
    add.undo()
    assert c.indices == []
    add.do()
    rem = RemoveItemCommand(c, ix)
    rem.do()
    assert c.indices == []
    rem.undo()
    assert c.indices == [ix]


# ---- on paper -------------------------------------------------------------------
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _ink(ix, rows, **kw):
    from PySide6.QtGui import QColor, QImage, QPainter
    from views.composer import paint_indice_mm
    img = QImage(800, 800, QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(8, 8)                                   # 8 px per mm
    paint_indice_mm(p, ix, rows, **kw)
    p.end()
    return img


def test_the_index_paints_its_rows(qapp):
    comps = _sheets("Cover", "Plan")
    ix = IndiceLaminas(border=False, show_title=False)
    rows = toc_entries(comps, ix)
    assert _ink(ix, rows) != _ink(ix, [])


def test_the_leader_and_numbers_can_be_switched_off(qapp):
    comps = _sheets("Cover", "Plan")
    styles = [IndiceLaminas(leader=lead, show_numbers=num)
              for lead, num in (("dots", True), ("line", True),
                                ("none", True), ("none", False))]
    images = [_ink(ix, toc_entries(comps, ix)) for ix in styles]
    assert len({im.cacheKey() for im in images}) == 4
    for a in range(len(images)):
        for b in range(a + 1, len(images)):
            assert images[a] != images[b]


# ---- in the composer ------------------------------------------------------------
@pytest.fixture
def composer(monkeypatch, tmp_path, qapp):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    monkeypatch.setattr(ComposerWindow, "templates_dir",
                        staticmethod(lambda: tmp_path))
    win = MainWindow()
    sheets = _sheets("Cover", "Plan", "Section")
    sheets[0].indices.append(IndiceLaminas(x_mm=20, y_mm=20))
    win.viewport.scene.compositions = sheets
    comp = ComposerWindow(win)
    comp.comp = sheets[0]
    comp._rebuild_canvas()
    yield comp
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _index_item(comp):
    from views.composer import IndiceCanvasItem
    return next(i for i in comp.canvas.items()
                if isinstance(i, IndiceCanvasItem))


def test_the_index_is_on_the_canvas_and_grows_with_the_document(composer):
    item = _index_item(composer)
    h3 = item.size_mm()[1]
    composer._scene().compositions.append(Composicion(name="Detail"))
    composer._reload_comp_combo()
    assert item.size_mm()[1] > h3
    rows, _p, _n = composer.toc_rows(item.model)
    assert [r.label for r in rows][-1] == "Detail"


def test_the_panel_splits_the_index(composer):
    item = _index_item(composer)
    composer.canvas.clearSelection()
    item.setSelected(True)
    composer.on_selection_changed()
    assert composer.props.currentIndex() == 16
    composer.ix_per_page.setValue(2)
    composer.ix_page.setValue(2)
    composer._on_indice_props()
    assert (item.model.per_page, item.model.page) == (2, 2)
    rows, page, pages = composer.toc_rows(item.model)
    assert [r.label for r in rows] == ["Section"] and (page, pages) == (2, 2)
    composer.history.undo()
    assert (item.model.per_page, item.model.page) == (0, 1)


def test_the_print_reads_the_sheet_it_is_on(composer):
    """Printing sheet 1 from a composer showing sheet 2: «this sheet» is
    the printed one."""
    ix = composer._scene().compositions[0].indices[0]
    ix.include_self = False
    composer.comp = composer._scene().compositions[1]
    rows, _p, _n = composer.toc_rows(ix, composer._scene().compositions[0])
    assert [r.label for r in rows] == ["Plan", "Section"]
