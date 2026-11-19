# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1505: sheets and saved views over MCP without the composer window —
a public API (core.sheets_api), one undo step per edit that reports
«changed», a rename that keeps frames attached, warnings for what would
print wrong, and render/export with the window closed."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core import ai  # noqa: E402
from core.saved_views import SavedView  # noqa: E402
from core.sheets_api import (SheetError, SheetsAPI, is_standard_scale,  # noqa: E402
                             snap_scale, unresolved_placeholders)


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _model(win, view_name="Grundriss"):
    """A 4×3×2 m box and a parallel top view of it."""
    vp = win.viewport
    r = ai.run_transactional(vp, "box((0, 0, 0), (4, 3, 2), name='Haus')",
                             {"__name__": "__ai__"})
    assert r["error"] is None, r
    import math
    vp.scene.saved_views.append(SavedView(
        view_name, target=(10.0, 10.0, 0.0), yaw=-math.pi / 2,
        pitch=math.pi / 2, perspective=False))
    return vp


def _ask(bridge, tool, args=None):
    """One request from a worker thread while this (Qt) thread pumps
    events — as in test_ai_bridge."""
    import socket
    import threading
    app = QApplication.instance()
    out: dict = {}

    def worker():
        s = socket.socket()
        s.settimeout(30.0)
        s.connect(("127.0.0.1", bridge.port))
        try:
            s.sendall((json.dumps({"id": 1, "tool": tool,
                                   "args": args or {}}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                assert chunk, "bridge closed"
                buf += chunk
            out["reply"] = json.loads(buf.split(b"\n", 1)[0])
        finally:
            s.close()

    t = threading.Thread(target=worker)
    t.start()
    while t.is_alive():
        app.processEvents()
        t.join(timeout=0.01)
    return out["reply"]


# ---- pure helpers -------------------------------------------------------------

def test_scale_helpers():
    assert is_standard_scale(50) and is_standard_scale(100)
    assert not is_standard_scale(110) and not is_standard_scale(90.909)
    assert snap_scale(90.909) == 100 and snap_scale(110) == 100


def test_unresolved_placeholders_are_found_in_every_language():
    assert unresolved_placeholders("{projekt} {datum} {scale} {n}") == []
    assert unresolved_placeholders("{contents:20:1} {projet}") == [
        "contents:20:1", "projet"]


# ---- the API on a live document ---------------------------------------------

def test_sheets_are_found_by_name_whatever_the_unicode_form(win):
    api = SheetsAPI(win.viewport.scene)
    api.create("Küche")                                   # NFC
    decomposed = "Küche"                            # NFD
    assert api.sheet(decomposed).name == "Küche"
    assert api.sheet("KÜCHE").name == "Küche"
    with pytest.raises(SheetError):
        api.create("küche")                               # a duplicate


def test_create_copy_reorder_rename_and_delete(win):
    api = SheetsAPI(win.viewport.scene)
    n = len(api.list())
    api.create("EG", paper="A3", title_block=True)
    api.create("OG", template="EG", after="EG")
    names = [s["name"] for s in api.list()]
    assert names[-2:] == ["EG", "OG"] and len(names) == n + 2
    assert api.get("OG")["title_block"] is not None       # copied
    api.update("OG", index=0, name="Obergeschoss", paper="A2")
    first = api.list()[0]
    assert first["name"] == "Obergeschoss" and first["paper"] == "A2"
    with pytest.raises(SheetError):
        api.delete("Obergeschoss")                        # no confirm
    api.delete("Obergeschoss", confirm=True)
    assert "Obergeschoss" not in [s["name"] for s in api.list()]


def test_renaming_a_view_keeps_its_frames_and_deleting_warns(win):
    vp = _model(win)
    api = SheetsAPI(vp.scene, vp.camera)
    api.create("Plan", frame=False)
    api.add_frame("Plan", view="Grundriss", scale=100)
    assert api.list_views()[-1]["used_by"] == ["Plan"]
    api.update_view("Grundriss", name="Grundriss EG")
    assert api.get("Plan")["frames"][0]["view"] == "scene:Grundriss EG"
    assert not [w for w in api.get("Plan")["warnings"]
                if w["kind"] == "missing_view"]
    with pytest.raises(SheetError, match="Plan"):
        api.delete_view("Grundriss EG")                   # names its users
    api.delete_view("Grundriss EG", confirm=True)
    kinds = [w["kind"] for w in api.get("Plan")["warnings"]]
    assert "missing_view" in kinds


def test_warnings_for_scale_clipping_and_placeholders(win):
    vp = _model(win)
    api = SheetsAPI(vp.scene, vp.camera)
    api.create("Plan", frame=False)
    # 4 m at 1:20 is 200 mm: does not fit a 100 mm frame.
    api.add_frame("Plan", view="Grundriss", scale=20, x_mm=20, y_mm=20,
                  w_mm=100, h_mm=100, fit="content")
    api.add_frame("Plan", view="Grundriss", scale="1:110", x_mm=150,
                  y_mm=20, w_mm=100, h_mm=100, fit="content")
    api.add_text("Plan", "{contents:20:1}")
    api.set_title_block("Plan", fields=[["PROJEKT", "{projekt}"]])
    kinds = {(w["kind"], w.get("frame")) for w in api.get("Plan")["warnings"]}
    assert ("clipped", 0) in kinds
    assert ("nonstandard_scale", 1) in kinds
    assert ("unresolved_placeholder", None) in kinds
    assert ("clipped", 1) not in kinds                    # 36 mm fits
    msgs = [w for w in api.get("Plan")["warnings"]
            if w["kind"] == "unresolved_placeholder"]
    assert msgs[0]["placeholders"] == ["contents:20:1"]   # {projekt} is fine


def test_fit_content_centres_the_frame_on_the_geometry(win):
    vp = _model(win)
    api = SheetsAPI(vp.scene, vp.camera)
    api.create("Plan", frame=False)
    f = api.add_frame("Plan", view="Grundriss", scale=50)
    # The saved view looks at (10, 10, 0): the box is off-centre.
    assert abs(f["content_mm"]["dx_mm"]) > 50
    f = api.fit("Plan", 0, "content")
    c = f["content_mm"]
    assert abs(c["dx_mm"]) < 0.5 and abs(c["dy_mm"]) < 0.5
    assert c["w_mm"] == pytest.approx(80, abs=0.5)        # 4 m at 1:50
    assert c["h_mm"] == pytest.approx(60, abs=0.5)
    f = api.fit("Plan", 0, "view")
    assert f["cam_target"] is None


def test_set_title_block_on_all_sheets(win):
    api = SheetsAPI(win.viewport.scene)
    api.create("A")
    api.create("B")
    done = api.set_title_block("all", fields=[["PROJEKT", "{projekt}"],
                                              ["DATUM", "{datum}"]])
    assert set(done) >= {"A", "B"}
    for s in api.list():
        rows = api.get(s["index"])["title_block"]["fields"]
        assert ["DATUM", "{datum}"] in rows


# ---- one undo step per edit, «changed» told the truth ----------------------------

def test_editing_inside_a_sheet_is_a_step_that_undo_reverts(win):
    vp = win.viewport
    ai.run_transactional(vp, "sheet('Plan')", {"__name__": "__ai__"})
    r = ai.run_transactional(
        vp, "sheets.update_frame('Plan', 0, scale=25)", {"__name__": "__ai__"})
    assert r["error"] is None and r["changed"] is True
    comp = SheetsAPI(vp.scene).sheet("Plan")
    assert comp.frames[0].scale_n == 25
    assert vp.history.undo()
    assert comp.frames[0].scale_n == 100                  # in place
    assert vp.history.redo()
    assert comp.frames[0].scale_n == 25


def test_a_failed_script_puts_layer_visibility_back(win):
    vp = win.viewport
    ai.run_transactional(vp, "layers.append(Layer('Möbel'))",
                         {"__name__": "__ai__"})
    r = ai.run_transactional(
        vp, "[l for l in layers if l.name == 'Möbel'][0].visible = False\n"
            "raise RuntimeError('boom')", {"__name__": "__ai__"})
    assert r["error"] and r["changed"] is False
    assert [ly for ly in vp.scene.layers if ly.name == "Möbel"][0].visible


# ---- the bridge tools --------------------------------------------------------------

def test_bridge_sheet_tools_undo_revision_render_and_export(win, monkeypatch,
                                                            tmp_path):
    from plugins.ai_bridge import _Bridge
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    vp = _model(win)
    bridge = _Bridge(vp)
    bridge.start()
    try:
        r = _ask(bridge, "create_sheet", {"name": "Schnitt Nord-Süd",
                                          "frame": False})
        assert r["ok"], r
        assert r["result"]["changed"] is True
        rev = r["result"]["document_revision"]
        r = _ask(bridge, "add_frame", {"sheet": "Schnitt Nord-Süd",
                                       "view": "Grundriss", "scale": 50,
                                       "fit": "content",
                                       "expected_revision": rev})
        assert r["ok"], r
        # A stale revision is refused, and nothing changes.
        r = _ask(bridge, "update_frame", {"sheet": "Schnitt Nord-Süd",
                                          "frame": 0, "scale": 20,
                                          "expected_revision": rev})
        assert not r["ok"] and "changed since" in r["error"]
        r = _ask(bridge, "get_sheet", {"sheet": "Schnitt Nord-Süd"})
        assert r["result"]["frames"][0]["scale_n"] == 50
        # A refused edit is no step either.
        r = _ask(bridge, "delete_sheet", {"sheet": "Schnitt Nord-Süd"})
        assert not r["ok"] and "confirm" in r["error"]
        # Look at it, with the composer never shown.
        r = _ask(bridge, "render_sheet", {"sheet": "Schnitt Nord-Süd",
                                          "dpi": 30})
        assert r["ok"], r
        assert Path(r["result"]["path"]).is_file()
        assert not win._composer.isVisible()
        pdf = tmp_path / "plans.pdf"
        r = _ask(bridge, "export_sheets", {"path": str(pdf),
                                           "sheets": ["Schnitt Nord-Süd"]})
        assert r["ok"], r
        assert pdf.stat().st_size > 0 and r["result"]["errors"] == {}
        r = _ask(bridge, "export_sheets", {"path": str(tmp_path / "p.png"),
                                           "sheets": ["Schnitt Nord-Süd"],
                                           "format": "png", "dpi": 30})
        assert r["ok"] and Path(r["result"]["files"][0]).is_file()
        # Undo takes the frame, then the sheet.
        assert _ask(bridge, "undo")["result"]["ok"]
        r = _ask(bridge, "get_sheet", {"sheet": "Schnitt Nord-Süd"})
        assert r["result"]["frames"] == []
        assert _ask(bridge, "undo")["result"]["ok"]
        r = _ask(bridge, "list_sheets")
        assert "Schnitt Nord-Süd" not in [s["name"]
                                          for s in r["result"]["sheets"]]
    finally:
        bridge.stop()


def test_a_missing_view_is_reported_by_the_export(win, monkeypatch, tmp_path):
    from plugins.ai_bridge import _Bridge
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    vp = _model(win)
    api = SheetsAPI(vp.scene)
    api.create("Plan", frame=False)
    api.add_frame("Plan", view="Grundriss")
    vp.scene.saved_views[:] = [v for v in vp.scene.saved_views
                               if v.name != "Grundriss"]
    bridge = _Bridge(vp)
    bridge.start()
    try:
        r = _ask(bridge, "export_sheets", {"path": str(tmp_path / "x.pdf"),
                                           "sheets": ["Plan"]})
        assert r["ok"], r
        assert "Grundriss" in r["result"]["errors"]["Plan"][0]
    finally:
        bridge.stop()


# ---- the MCP server --------------------------------------------------------------

def test_mcp_lists_the_sheet_tools_with_the_placeholders():
    import ingetrazo_mcp as mcp
    tools = {t["name"]: t for t in mcp.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    for name in ("list_sheets", "get_sheet", "create_sheet", "update_sheet",
                 "delete_sheet", "add_frame", "update_frame", "remove_frame",
                 "fit_frame", "set_title_block", "add_text", "update_text",
                 "list_views", "create_view", "update_view", "delete_view",
                 "render_sheet", "export_sheets"):
        assert name in tools, name
        json.dumps(tools[name]["inputSchema"])
    desc = tools["set_title_block"]["description"]
    assert "{projekt}" in desc and "{massstab}" in desc and "{blatt}" in desc
    assert "expected_revision" in tools["update_frame"]["inputSchema"][
        "properties"]


def test_mcp_reads_its_requests_as_utf8(monkeypatch):
    """cp1252 stdin turned «Küche» into «KÃ¼che» before it reached the app."""
    import io
    import ingetrazo_mcp as mcp
    raw = io.TextIOWrapper(io.BytesIO("Küche\n".encode("utf-8")),
                           encoding="cp1252")
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", raw)
    monkeypatch.setattr(sys, "stdout", out)
    mcp._utf8_stdio()
    assert sys.stdin.readline().strip() == "Küche"
