# SPDX-License-Identifier: GPL-3.0-or-later
"""#1505: sheets and scenes over MCP without the composer window.

A public API (``core.sheets_api``, also ``sheets`` in ``run_python``), one
resolver for sheets shared with the bridge, one undo step per edit that
reports ``changed``, a scene rename that keeps its frames, warnings for what
would print wrong, and render / export with the window never shown."""
from __future__ import annotations

import json
import math
import os
import unicodedata

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import ai  # noqa: E402
from core.composition import Composicion  # noqa: E402
from core.saved_views import SavedView  # noqa: E402
from core.sheets_api import (SheetError, SheetsAPI, find_sheet,  # noqa: E402
                             is_standard_scale, snap_scale,
                             unresolved_placeholders)
from tests.test_bridge_tools import (_err, _mcp_call, _mcp_module,  # noqa: E402,F401
                                     _ok, env)


# ---- pure helpers -------------------------------------------------------------

def test_scale_helpers():
    assert is_standard_scale(50) and is_standard_scale(100)
    assert not is_standard_scale(110) and not is_standard_scale(90.909)
    assert snap_scale(90.909) == 100 and snap_scale(110) == 100


def test_unresolved_placeholders_are_found_in_every_language():
    assert unresolved_placeholders("{projekt} {datum} {scale} {n}") == []
    assert unresolved_placeholders("{contents:20:1} {projet}") == [
        "contents:20:1", "projet"]


def test_one_resolver_by_place_name_number_and_unicode_form():
    a, b = Composicion(name="Küche"), Composicion(name="L-02 Ubicación")
    b.cajetin = b.default_cajetin()
    b.cajetin.set_field("LÁMINA", "L-02")
    comps = [a, b]
    assert find_sheet(comps, 1) is a and find_sheet(comps, "2") is b
    assert find_sheet(comps, unicodedata.normalize("NFD", "Küche")) is a
    assert find_sheet(comps, "KÜCHE") is a
    assert find_sheet(comps, "l-02") is b              # the number
    assert find_sheet(comps, b) is b
    with pytest.raises(SheetError, match="1…2"):
        find_sheet(comps, 3)
    with pytest.raises(SheetError):
        find_sheet(comps, 0)                           # places start at 1
    assert isinstance(SheetError("x"), ValueError)


# ---- the API on a live document -----------------------------------------------

@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _model(win, scene_name="Grundriss"):
    """A 4×3×2 m box and a parallel top scene of it, looking at (10, 10)."""
    vp = win.viewport
    r = ai.run_transactional(vp, "box((0, 0, 0), (4, 3, 2), name='Haus')",
                             {"__name__": "__ai__"})
    assert r["error"] is None, r
    vp.scene.saved_views.append(SavedView(
        scene_name, target=(10.0, 10.0, 0.0), yaw=-math.pi / 2,
        pitch=math.pi / 2, perspective=False))
    return vp


def test_create_copy_reorder_rename_and_delete(win):
    api = SheetsAPI(win.viewport.scene)
    n = len(api.list())
    api.create("EG", paper="A3", title_block=True)
    api.create("OG", template="EG", after="EG")
    names = [s["name"] for s in api.list()]
    assert names[-2:] == ["EG", "OG"] and len(names) == n + 2
    assert api.get("OG")["title_block"] is not None         # copied
    api.update("OG", index=1, name="Obergeschoss", paper="A2")
    first = api.list()[0]
    assert first["index"] == 1 and first["name"] == "Obergeschoss"
    assert first["paper"] == "A2"
    with pytest.raises(SheetError):
        api.create("eg")                                    # a duplicate
    with pytest.raises(SheetError):
        api.delete("Obergeschoss")                          # no confirm
    api.delete("Obergeschoss", confirm=True)
    assert "Obergeschoss" not in [s["name"] for s in api.list()]


def test_renaming_a_scene_keeps_its_frames_and_deleting_warns(win):
    vp = _model(win)
    api = SheetsAPI(vp.scene, vp.camera)
    api.create("Plan", frame=False)
    api.add_frame("Plan", view="Grundriss", scale=100)
    assert api.list_scenes()[-1]["used_by"] == ["Plan"]
    api.update_scene("Grundriss", name="Grundriss EG")
    assert api.get("Plan")["frames"][0]["view"] == "scene:Grundriss EG"
    assert not [w for w in api.get("Plan")["warnings"]
                if w["kind"] == "missing_scene"]
    with pytest.raises(SheetError, match="Plan"):
        api.delete_scene("Grundriss EG")                    # names its users
    api.delete_scene("Grundriss EG", confirm=True)
    kinds = [w["kind"] for w in api.get("Plan")["warnings"]]
    assert "missing_scene" in kinds


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
    warnings = api.get("Plan")["warnings"]
    kinds = {(w["kind"], w.get("frame")) for w in warnings}
    assert ("clipped", 1) in kinds
    assert ("nonstandard_scale", 2) in kinds
    assert ("clipped", 2) not in kinds                      # 36 mm fits
    odd = [w for w in warnings if w["kind"] == "nonstandard_scale"]
    assert odd[0]["suggested"] == "1:100"
    msgs = [w for w in warnings if w["kind"] == "unresolved_placeholder"]
    assert msgs[0]["placeholders"] == ["contents:20:1"]     # {projekt} is fine


def test_fit_content_centres_the_frame_on_the_geometry(win):
    vp = _model(win)
    api = SheetsAPI(vp.scene, vp.camera)
    api.create("Plan", frame=False)
    f = api.add_frame("Plan", view="Grundriss", scale=50)
    assert f["index"] == 1
    # The scene looks at (10, 10, 0): the box is off-centre.
    assert abs(f["content_mm"]["dx_mm"]) > 50
    f = api.fit("Plan", 1, "content")
    c = f["content_mm"]
    assert abs(c["dx_mm"]) < 0.5 and abs(c["dy_mm"]) < 0.5
    assert c["w_mm"] == pytest.approx(80, abs=0.5)          # 4 m at 1:50
    assert c["h_mm"] == pytest.approx(60, abs=0.5)
    assert api.fit("Plan", 1, "view")["cam_target"] is None


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


def test_sheets_in_run_python_is_one_undo_step_in_place(win):
    vp = win.viewport
    scope = {"__name__": "__ai__"}
    ai.run_transactional(vp, "sheets.create('Plan')", scope)
    comp = SheetsAPI(vp.scene).sheet("Plan")
    frame = comp.frames[0]
    r = ai.run_transactional(vp, "sheets.update_frame('Plan', 1, scale=25)",
                             scope)
    assert r["error"] is None and r["changed"] is True
    assert frame.scale_n == 25
    assert vp.history.undo()
    assert comp.frames[0] is frame and frame.scale_n == 100
    assert vp.history.redo()
    assert frame.scale_n == 25


# ---- the bridge tools -------------------------------------------------------------

def test_bridge_sheet_tools_are_steps_with_a_revision(env):
    win, vp, bridge = env
    r = _ok(bridge, "create_sheet", {"name": "Schnitt Nord-Süd",
                                     "frame": False})
    assert r["changed"] is True and r["result"]["index"] == 3
    rev = r["document_revision"]
    assert rev == _ok(bridge, "list_sheets")["document_revision"]
    r = _ok(bridge, "add_frame", {"sheet": "Schnitt Nord-Süd",
                                  "view": "Planta", "scale": 50,
                                  "fit": "content",
                                  "fields": {"list_name": "Grundriss"},
                                  "expected_revision": rev})
    assert r["result"]["list_name"] == "Grundriss"
    # A stale revision is refused, and nothing changes.
    assert "changed since" in _err(bridge, "update_frame", {
        "sheet": "Schnitt Nord-Süd", "frame": 1, "scale": 20,
        "expected_revision": rev})
    got = _ok(bridge, "get_sheet", {"sheet": "Schnitt Nord-Süd"})
    assert got["frames"][0]["scale_n"] == 50
    # Refused edits are no step either.
    undo = len(vp.history.undo_stack)
    assert "confirm" in _err(bridge, "delete_sheet",
                             {"sheet": "Schnitt Nord-Süd"})
    assert "unknown frame field" in _err(bridge, "update_frame", {
        "sheet": 3, "frame": "Grundriss", "fields": {"nonsense": 1}})
    assert len(vp.history.undo_stack) == undo
    # An edit that changes nothing is no step.
    r = _ok(bridge, "update_frame", {"sheet": 3, "frame": 1, "scale": 50})
    assert r["changed"] is False and len(vp.history.undo_stack) == undo
    # The scene's used_by, and a rename that keeps the frame.
    scenes = _ok(bridge, "list_scenes")["scenes"]
    assert scenes[0]["used_by"] == ["Schnitt Nord-Süd"]
    _ok(bridge, "update_scene", {"scene": "Planta", "name": "Planta baja"})
    assert _ok(bridge, "get_sheet", {"sheet": 3})["frames"][0]["view"] \
        == "scene:Planta baja"
    # Undo goes back step by step: the rename, the frame, the sheet.
    assert _ok(bridge, "undo")["ok"]
    assert vp.scene.saved_views[0].name == "Planta"
    assert _ok(bridge, "undo")["ok"]
    assert _ok(bridge, "get_sheet", {"sheet": 3})["frames"] == []
    assert _ok(bridge, "undo")["ok"]
    assert "Schnitt Nord-Süd" not in [
        s["name"] for s in _ok(bridge, "list_sheets")["sheets"]]


def test_render_and_png_export_never_show_the_composer(env, monkeypatch,
                                                       tmp_path):
    win, vp, bridge = env
    monkeypatch.setattr(vp, "_gl", None)          # the sheet of lines only
    got = _ok(bridge, "render_sheet", {"sheet": "L-01", "dpi": 30})
    assert "warnings" in got
    composer = win._composer
    assert not composer.isVisible()
    r = _ok(bridge, "export_pdf", {"path": str(tmp_path / "plans.png"),
                                   "sheets": ["L-01"], "format": "png",
                                   "dpi": 30})
    assert [p.name for p in tmp_path.iterdir()] == [
        "plans-01-Planta_general.png"]
    assert r["files"] == [str(tmp_path / "plans-01-Planta_general.png")]
    folder = tmp_path / "out"
    _ok(bridge, "export_pdf", {"path": str(folder), "sheets": [1],
                               "format": "png", "dpi": 30})
    assert [p.name for p in folder.iterdir()] == ["01-Planta_general.png"]
    assert "format must be" in _err(bridge, "export_pdf", {
        "path": str(tmp_path / "x.svg"), "format": "svg"})
    assert not composer.isVisible()
    assert not win._is_dirty()


def test_an_agent_edit_reaches_a_composer_that_is_open(env):
    """The composer stays on the same frame objects after the agent's
    step and its undo (they are restored in place)."""
    win, vp, bridge = env
    composer = win._ensure_composer()
    frame = composer.comp.frames[0]
    _ok(bridge, "update_frame", {"sheet": composer.comp.name, "frame": 1,
                                 "scale": 20})
    assert frame.scale_n == 20 and composer.comp.frames[0] is frame
    _ok(bridge, "undo")
    assert composer.comp.frames[0] is frame and frame.scale_n != 20


# ---- the MCP server ---------------------------------------------------------------

def test_mcp_lists_the_sheet_tools_one_name_per_job():
    mod = _mcp_module()
    tools = {t["name"]: t for t in mod.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    for name in ("list_sheets", "get_sheet", "list_sheet_folders",
                 "create_sheet", "update_sheet", "delete_sheet", "add_frame",
                 "update_frame", "remove_frame", "fit_frame",
                 "set_title_block", "add_text", "update_text",
                 "list_scenes", "create_scene", "update_scene",
                 "delete_scene", "render_sheet", "export_pdf"):
        assert name in tools, name
        json.dumps(tools[name]["inputSchema"])
    for name in ("list_views", "create_view", "update_view", "delete_view",
                 "export_sheets"):
        assert name not in tools, name
    assert "expected_revision" in tools["update_frame"]["inputSchema"][
        "properties"]
    assert tools["export_pdf"]["inputSchema"]["properties"]["format"][
        "enum"] == ["pdf", "png"]
    assert tools["get_sheet"]["annotations"]["readOnlyHint"] is True
    assert tools["delete_scene"]["annotations"]["destructiveHint"] is True
