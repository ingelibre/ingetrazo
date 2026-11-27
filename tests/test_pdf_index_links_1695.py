# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet index as links in the PDF of all the sheets (#1695).

Each row of the index opens its sheet's page; every other page carries a
small «back to the index» button that opens the index's page. Qt writes no
links between pages, so :mod:`formats.pdf_links` adds them as an
incremental update of the file Qt wrote."""
from __future__ import annotations

import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core.composition import (Composicion, IndiceLaminas,  # noqa: E402
                              TocEntry, toc_entries, toc_row_boxes)
from formats import pdf_links as PL  # noqa: E402


def _pdf(path, pages=3):
    """A plain PDF of ``pages`` pages, the way the atlas writes one: A4
    portrait, then A3 landscape."""
    w = QPdfWriter(str(path))
    w.setResolution(150)
    p = None
    for i in range(pages):
        w.setPageSize(QPageSize(QPageSize.A4 if i % 2 == 0 else QPageSize.A3))
        w.setPageOrientation(QPageLayout.Portrait if i % 2 == 0
                             else QPageLayout.Landscape)
        if p is None:
            p = QPainter(w)
        else:
            w.newPage()
        p.drawText(100, 100, f"page {i + 1}")
    p.end()
    del w
    return path


def _annots(data: bytes) -> list:
    """``(rect, dest page object)`` of every link annotation in the file."""
    out = []
    for m in re.finditer(rb"/Subtype /Link\s*/Rect \[([^\]]*)\][^>]*?"
                         rb"/Dest \[(\d+) 0 R /Fit\]", data):
        out.append((tuple(float(v) for v in m.group(1).split()),
                    int(m.group(2))))
    return out


# ---- The post-processor -----------------------------------------------------

def test_pages_are_found_in_reading_order(tmp_path):
    data = _pdf(tmp_path / "a.pdf").read_bytes()
    pages = PL.page_objects(data)
    assert pages is not None and len(pages) == 3
    assert len(set(pages)) == 3


def test_links_are_appended_as_an_update(tmp_path):
    path = _pdf(tmp_path / "a.pdf")
    before = path.read_bytes()
    pages = PL.page_objects(before)
    links = [PL.PdfLink(0, (10, 20, 110, 40), 2, "Section"),
             PL.PdfLink(0, (10, 50, 110, 70), 1, "Plan"),
             PL.PdfLink(2, (500, 800, 520, 820), 0, "Index")]
    assert PL.add_links(path, links)
    after = path.read_bytes()
    assert after.startswith(before)               # Qt's bytes untouched
    assert after.count(b"%%EOF") == before.count(b"%%EOF") + 1
    found = _annots(after)
    assert ((10.0, 20.0, 110.0, 40.0), pages[2]) in found
    assert ((10.0, 50.0, 110.0, 70.0), pages[1]) in found
    assert ((500.0, 800.0, 520.0, 820.0), pages[0]) in found
    # The updated file is still one the reader walks: pages and trailer.
    assert PL.page_objects(after) == pages
    tr = PL._trailer(after)
    assert tr["startxref"] == after.rfind(b"xref\n") or \
        after[tr["startxref"]:].startswith(b"xref")
    assert b"/Prev %d" % PL._trailer(before)["startxref"] in after
    # …and a second update chains onto the first.
    assert PL.add_links(path, [PL.PdfLink(1, (0, 0, 5, 5), 0)])
    assert len(_annots(path.read_bytes())) == 4


def test_links_to_pages_that_are_not_there_are_skipped(tmp_path):
    path = _pdf(tmp_path / "a.pdf", pages=2)
    before = path.read_bytes()
    assert not PL.add_links(path, [PL.PdfLink(0, (0, 0, 1, 1), 5)])
    assert not PL.add_links(path, [])
    assert path.read_bytes() == before


def test_a_file_it_cannot_read_is_left_alone(tmp_path):
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.7\nnot really\n%%EOF\n")
    assert not PL.add_links(path, [PL.PdfLink(0, (0, 0, 1, 1), 0)])
    assert path.read_bytes() == b"%PDF-1.7\nnot really\n%%EOF\n"


def test_the_update_reads_in_a_pdf_library(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    path = _pdf(tmp_path / "a.pdf")
    PL.add_links(path, [PL.PdfLink(0, (10, 20, 110, 40), 2, "Ünïcode ✓")])
    reader = pypdf.PdfReader(str(path))
    annots = reader.pages[0]["/Annots"]
    link = [a.get_object() for a in annots
            if a.get_object()["/Subtype"] == "/Link"][-1]
    assert link["/Dest"][0].get_object() == reader.pages[2].get_object()
    assert link["/Contents"] == "Ünïcode ✓"


def test_mm_become_points_from_the_bottom_of_the_page():
    # 10 pt margin, an A4 page (842 pt high): 1 inch = 25.4 mm = 72 pt.
    x0, y0, x1, y1 = PL.mm_rect_to_pdf((25.4, 25.4, 25.4, 12.7),
                                       (10, 10), 842)
    assert (x0, x1) == pytest.approx((82, 154))
    assert (y1, y0) == pytest.approx((842 - 82, 842 - 118))


# ---- The index's rows -------------------------------------------------------

def test_a_row_knows_its_sheet_and_where_it_sits():
    comps = [Composicion(name=n) for n in ("Cover", "Plan", "Section")]
    ix = IndiceLaminas(x_mm=20, y_mm=30, w_mm=90)
    rows = toc_entries(comps, ix, here=comps[0])
    assert [r.sheet for r in rows] == comps
    # equality is the row's text, not the sheet object
    assert rows[1] == TocEntry("Plan", "2", 0, False, False)
    boxes = toc_row_boxes(ix, rows)
    ys = [b[1] for _e, b in boxes]
    assert ys[0] == pytest.approx(ix.PAD_MM + ix.title_mm())
    assert ys[1] - ys[0] == pytest.approx(ix.row_mm())
    assert all(b[0] + b[2] == pytest.approx(ix.w_mm - ix.PAD_MM)
               for _e, b in boxes)


def test_the_new_settings_load_from_an_older_file():
    ix = Composicion.from_dict({"name": "S", "indices": [{"title": "T"}]}
                               ).indices[0]
    assert (ix.pdf_back_link, ix.pdf_back_corner, ix.pdf_back_size_mm) == (
        True, "top-right", 8.0)


# ---- The PDF of all the sheets ----------------------------------------------

def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups[:] = []
    scene.version += 1
    return win, scene


def _close(win, comp_win):
    comp_win._saved_version = win.viewport.scene.version
    win._saved_version = win.viewport.scene.version
    comp_win.close()
    win.close()


def _atlas(tmp_path, *, back=True, corner="top-right", leave_out=None):
    """Index on «Cover», then «Plan» (A3 landscape) and «Section»: the
    PDF's bytes and the page objects, in order."""
    win, scene = _window()
    cover = Composicion(name="Cover")
    plan = Composicion(name="Plan", paper="A3", landscape=True)
    section = Composicion(name="Section")
    cover.indices.append(IndiceLaminas(
        x_mm=20, y_mm=30, w_mm=100, pdf_back_link=back,
        pdf_back_corner=corner))
    scene.compositions[:] = [cover, plan, section]
    comp_win = win._ensure_composer()
    path = tmp_path / "all.pdf"
    sheets = [c for c in scene.compositions if c.name != leave_out]
    assert comp_win.export_all_pdf(str(path), sheets) == []
    data = path.read_bytes()
    _close(win, comp_win)
    return data, PL.page_objects(data)


def _links_on(data, page_obj):
    """The links listed by one page (its /Annots array, last version)."""
    body = PL._find_object(data, page_obj)
    ref = re.search(rb"/Annots\s+(\d+)\s+0\s+R", body)
    arr = PL._find_object(data, int(ref.group(1))) if ref else body
    nums = [int(n) for n in re.findall(rb"(\d+)\s+0\s+R",
                                       re.search(rb"\[([^\]]*)\]",
                                                 arr).group(1))]
    out = []
    for n in nums:
        a = PL._find_object(data, n)
        m = re.search(rb"/Dest \[(\d+) 0 R", a or b"")
        if m:
            rect = re.search(rb"/Rect \[([^\]]*)\]", a).group(1).split()
            out.append((tuple(float(v) for v in rect), int(m.group(1))))
    return out


def test_every_row_of_the_index_opens_its_sheet(tmp_path):
    data, pages = _atlas(tmp_path)
    assert len(pages) == 3
    on_cover = _links_on(data, pages[0])
    assert sorted(d for _r, d in on_cover) == sorted(pages)
    # top to bottom in the order of the rows: Cover, Plan, Section
    by_top = [d for r, d in sorted(on_cover, key=lambda x: -x[0][3])]
    assert by_top == pages
    # the rows sit where the index is drawn: 20 mm from the left edge
    left = min(r[0] for r, _d in on_cover)
    assert left == pytest.approx(10 + (20 + IndiceLaminas.PAD_MM)
                                 * PL.PT_PER_MM, abs=0.5)


def test_every_other_page_leads_back_to_the_index(tmp_path):
    data, pages = _atlas(tmp_path)
    for page in pages[1:]:
        back = _links_on(data, page)
        assert [d for _r, d in back] == [pages[0]]
    # top-right on the landscape A3 plan: near its right and top edges
    (x0, y0, x1, y1), _d = _links_on(data, pages[1])[0]
    assert x1 > 1100 and y1 > 780


def test_the_button_can_be_moved_or_left_out(tmp_path):
    data, pages = _atlas(tmp_path, corner="bottom-left")
    (x0, y0, x1, y1), _d = _links_on(data, pages[2])[0]
    assert x0 < 60 and y0 < 60
    data, pages = _atlas(tmp_path, back=False)
    assert _links_on(data, pages[1]) == []
    assert len(_links_on(data, pages[0])) == 3       # the rows still link


def test_a_sheet_left_out_of_the_pdf_gets_no_link(tmp_path):
    data, pages = _atlas(tmp_path, leave_out="Plan")
    assert len(pages) == 2
    # Cover and Section link to their pages; Plan is not in this PDF.
    assert sorted(d for _r, d in _links_on(data, pages[0])) == sorted(pages)
