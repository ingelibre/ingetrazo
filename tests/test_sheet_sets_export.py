# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Printing and exporting a sheet set (#1519): its sheets in its order,
{hoja}/{total} and the sheet index counting within the set, {set} its
name — while the canvas keeps the document's numbering — as PDF and
PNG, through the composer, the sheets API and the MCP bridge."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core import sheet_sets as ss  # noqa: E402
from core.composition import (Composicion, IndiceLaminas,  # noqa: E402
                              expand_fields)
from core.sheet_sets import SheetSet  # noqa: E402
from core.sheets_api import SheetError, SheetsAPI  # noqa: E402
from tests.test_bridge_tools import env  # noqa: E402,F401


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _doc(win, n=5):
    scene = win.viewport.scene
    scene.compositions[:] = [Composicion(name=f"S{i + 1}") for i in range(n)]
    roofer = SheetSet("Roofer")
    scene.sheet_sets[:] = [roofer]
    ss.set_members(scene, roofer, [scene.compositions[i] for i in (4, 1, 2)])
    return scene, roofer, win._ensure_composer()


def _pages(pdf: Path) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf.read_bytes()))


# ---- fields and the index ----------------------------------------------------------

def test_fields_count_within_the_set_and_the_canvas_keeps_the_document(win):
    scene, roofer, comp = _doc(win)
    s2 = scene.compositions[1]
    comps, name = comp._sheets_to_export(None, "roofer")
    assert [c.name for c in comps] == ["S5", "S2", "S3"] and name == "Roofer"
    with comp.export_scope(comps, name):
        comp._set_field_context(s2)
        assert expand_fields("{hoja}/{total} {set}") == "2/3 Roofer"
        assert expand_fields("{blatt}/{gesamt} {plansatz}") == "2/3 Roofer"
    comp._set_field_context(s2)              # the canvas: the document
    assert expand_fields("{hoja}/{total}{juego}") == "2/5"


def test_the_index_lists_only_the_set_numbered_within_it(win):
    scene, roofer, comp = _doc(win)
    ix = IndiceLaminas()
    here = scene.compositions[4]
    comps, name = comp._sheets_to_export(None, roofer)
    with comp.export_scope(comps, name):
        rows, _page, _pages = comp.toc_rows(ix, here)
    assert [(r.label, r.number) for r in rows] == [
        ("S5", "1"), ("S2", "2"), ("S3", "3")]
    rows, *_ = comp.toc_rows(ix, here)
    assert [r.number for r in rows] == ["1", "2", "3", "4", "5"]


def test_the_print_flag_leaves_a_member_out(win):
    scene, roofer, comp = _doc(win)
    scene.compositions[1].print_in_all = False         # S2
    comps, _ = comp._sheets_to_export(None, "Roofer")
    assert [c.name for c in comps] == ["S5", "S3"]


def test_an_unknown_set_is_refused(win, tmp_path):
    _scene, _roofer, comp = _doc(win)
    with pytest.raises(ValueError, match="no sheet set"):
        comp.export_all_pdf(str(tmp_path / "x.pdf"), sheet_set="Carpenter")


# ---- the files ----------------------------------------------------------------------

def test_pdf_of_a_set_and_of_everything(win, tmp_path):
    _scene, _roofer, comp = _doc(win)
    pdf = tmp_path / "roofer.pdf"
    comp.export_all_pdf(str(pdf), sheet_set="Roofer")
    assert _pages(pdf) == 3
    all_pdf = tmp_path / "all.pdf"
    comp.export_all_pdf(str(all_pdf))
    assert _pages(all_pdf) == 5


# ---- the sheets API and the bridge ------------------------------------------------------

def test_api_creates_updates_and_deletes_sets(win):
    scene = win.viewport.scene
    scene.compositions[:] = [Composicion(name=n) for n in ("A", "B", "C")]
    api = SheetsAPI(scene)
    info = api.create_set("Client", sheets=["C", "A"], cover="B",
                          description="for the client")
    # The explorer's order (the cover first) unless an order is asked for.
    assert info["sheets"] == ["B", "A", "C"] and info["cover"] == "B"
    assert info["ordered"] is False
    with pytest.raises(SheetError, match="already"):
        api.create_set("client")
    api.update("A", name="A-renamed")
    assert api.get_set("Client")["sheets"] == ["B", "A-renamed", "C"]
    info = api.update_set("Client", sheets=["C", "A-renamed"], ordered=True)
    assert info["sheets"] == ["B", "C", "A-renamed"] and info["ordered"]
    scene.compositions.reverse()                 # an explicit order holds
    assert api.get_set("Client")["sheets"] == ["B", "C", "A-renamed"]
    scene.compositions.reverse()
    assert api.get("C")["sets"] == ["Client"]
    info = api.update_set("Client", name="Owner", remove=["C"], cover="",
                          ordered=False)
    assert info["sheets"] == ["A-renamed"] and info["name"] == "Owner"
    info = api.update_set("Owner", add=["C"])
    assert info["sheets"] == ["A-renamed", "C"]
    with pytest.raises(SheetError, match="confirm"):
        api.delete_set("Owner")
    api.delete_set("Owner", confirm=True)
    assert api.list_sets() == [] and len(scene.compositions) == 3
    with pytest.raises(SheetError, match="no sheet set"):
        api.get_set("Owner")


def test_bridge_set_tools_are_steps_and_export_a_set(env, monkeypatch,
                                                    tmp_path):
    from tests.test_bridge_tools import _err, _ok
    win, vp, bridge = env
    monkeypatch.setattr(vp, "_gl", None)          # the sheet of lines only
    r = _ok(bridge, "create_sheet_set", {"name": "Roofer",
                                         "sheets": ["L-01"]})
    assert r["changed"] and r["result"]["sheets"] == ["Planta general"]
    assert _ok(bridge, "list_sheet_sets")["sets"][0]["name"] == "Roofer"
    assert _ok(bridge, "get_sheet", {"sheet": 1})["sets"] == ["Roofer"]
    r = _ok(bridge, "export_pdf", {"path": str(tmp_path / "r.pdf"),
                                   "sheet_set": "Roofer"})
    assert r["sheet_set"] == "Roofer"
    assert r["sheet_names"] == ["Planta general"]
    assert _pages(tmp_path / "r.pdf") == 1
    r = _ok(bridge, "export_pdf", {"path": str(tmp_path / "png"),
                                   "sheet_set": "roofer", "format": "png",
                                   "dpi": 20})
    assert [Path(f).name for f in r["files"]] == ["01-Planta_general.png"]
    assert "no sheet set" in _err(bridge, "export_pdf", {
        "path": str(tmp_path / "x.pdf"), "sheet_set": "Nobody"})
    assert "not both" in _err(bridge, "export_pdf", {
        "path": str(tmp_path / "x.pdf"), "sheet_set": "Roofer",
        "sheets": [1]})
    _ok(bridge, "render_sheet", {"sheet": 1, "dpi": 20,
                                 "sheet_set": "Roofer"})
    assert _ok(bridge, "undo")["ok"]
    assert vp.scene.sheet_sets == []


def test_mcp_lists_the_set_tools():
    from tests.test_bridge_tools import _mcp_module
    tools = {t["name"]: t for t in _mcp_module().TOOLS}
    assert {"list_sheet_sets", "get_sheet_set", "create_sheet_set",
            "update_sheet_set", "delete_sheet_set",
            "list_sheet_folders"} <= set(tools)
    for name in ("export_pdf", "render_sheet"):
        assert "sheet_set" in tools[name]["inputSchema"]["properties"]
