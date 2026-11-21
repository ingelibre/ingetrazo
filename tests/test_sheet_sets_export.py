# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Printing and exporting a sheet set (#1519): its sheets in its order,
{hoja}/{total} and the sheet index counting within the set, {set} its
name — while the canvas keeps the document's numbering — as PDF, PNG and
SVG, through the composer, the sheets API and the MCP bridge."""
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

def test_pdf_png_and_svg_of_a_set(win, tmp_path):
    _scene, _roofer, comp = _doc(win)
    pdf = tmp_path / "roofer.pdf"
    comp.export_all_pdf(str(pdf), sheet_set="Roofer")
    assert _pages(pdf) == 3
    all_pdf = tmp_path / "all.pdf"
    comp.export_all_pdf(str(all_pdf))
    assert _pages(all_pdf) == 5
    out = comp.export_sheets(str(tmp_path / "r.png"), fmt="png", dpi=20,
                             sheet_set="Roofer")
    assert [Path(f).name for f in out["files"]] == [
        "r-01-S5.png", "r-02-S2.png", "r-03-S3.png"]
    out = comp.export_sheets(str(tmp_path / "r.svg"), fmt="svg",
                             sheet_set="Roofer")
    names = [Path(f).name for f in out["files"]]
    assert names == ["r-01-S5.svg", "r-02-S2.svg", "r-03-S3.svg"]
    svg = (tmp_path / names[0]).read_text(encoding="utf-8")
    assert svg.lstrip().startswith("<?xml") and "<svg" in svg


def test_a_set_s_page_carries_its_numbers_in_the_svg(win, tmp_path):
    from core.composition import TextoItem
    scene, _roofer, comp = _doc(win)
    scene.compositions[1].texts.append(TextoItem(
        x_mm=20, y_mm=20, w_mm=80, text="Blatt {blatt} von {gesamt}"))
    out = comp.export_sheets(str(tmp_path / "r.svg"), fmt="svg",
                             sheet_set="Roofer")
    svg = Path(out["files"][1]).read_text(encoding="utf-8")
    assert "Blatt 2 von 3" in svg


# ---- the sheets API and the bridge ------------------------------------------------------

def test_api_creates_updates_and_deletes_sets(win):
    scene = win.viewport.scene
    scene.compositions[:] = [Composicion(name=n) for n in ("A", "B", "C")]
    api = SheetsAPI(scene)
    info = api.create_set("Client", sheets=["C", "A"], cover="B",
                          description="for the client")
    assert info["sheets"] == ["B", "C", "A"] and info["cover"] == "B"
    with pytest.raises(SheetError, match="already"):
        api.create_set("client")
    api.update("A", name="A-renamed")
    assert api.get_set("Client")["sheets"] == ["B", "C", "A-renamed"]
    assert api.get("C")["sets"] == ["Client"]
    info = api.update_set("Client", name="Owner", remove=["C"], cover="")
    assert info["sheets"] == ["A-renamed"] and info["name"] == "Owner"
    info = api.update_set("Owner", add=["C"])
    assert info["sheets"] == ["A-renamed", "C"]
    with pytest.raises(SheetError, match="confirm"):
        api.delete_set("Owner")
    api.delete_set("Owner", confirm=True)
    assert api.list_sets() == [] and len(scene.compositions) == 3
    with pytest.raises(SheetError, match="no sheet set"):
        api.get_set("Owner")


def test_bridge_set_tools_are_steps_and_export_a_set(win, monkeypatch,
                                                    tmp_path):
    from plugins.ai_bridge import _Bridge
    from tests.test_sheets_mcp_1505 import _ask
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    scene = win.viewport.scene
    scene.compositions[:] = [Composicion(name=n) for n in ("A", "B", "C")]
    bridge = _Bridge(win.viewport)
    bridge.start()
    try:
        r = _ask(bridge, "create_sheet_set", {"name": "Roofer",
                                              "sheets": ["C", "A"]})
        assert r["ok"] and r["result"]["changed"], r
        r = _ask(bridge, "list_sheet_sets")
        assert r["result"]["sheet_sets"][0]["sheets"] == ["C", "A"]
        r = _ask(bridge, "export_sheets", {"path": str(tmp_path / "r.pdf"),
                                           "sheet_set": "Roofer"})
        assert r["ok"], r
        assert _pages(tmp_path / "r.pdf") == 2
        r = _ask(bridge, "export_sheets", {"path": str(tmp_path / "x.pdf"),
                                           "sheet_set": "Nobody"})
        assert not r["ok"] and "no sheet set" in r["error"]
        r = _ask(bridge, "render_sheet", {"sheet": "A", "dpi": 20,
                                          "sheet_set": "Roofer"})
        assert r["ok"], r
        assert _ask(bridge, "undo")["result"]["ok"]
        assert scene.sheet_sets == []
    finally:
        bridge.stop()


def test_mcp_lists_the_set_tools():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import ingetrazo_mcp as mcp
    names = {t["name"] for t in mcp.TOOLS}
    assert {"list_sheet_sets", "get_sheet_set", "create_sheet_set",
            "update_sheet_set", "delete_sheet_set",
            "list_sheet_folders"} <= names
    export = next(t for t in mcp.TOOLS if t["name"] == "export_sheets")
    assert "sheet_set" in export["inputSchema"]["properties"]
    assert "svg" in export["inputSchema"]["properties"]["format"]["enum"]
