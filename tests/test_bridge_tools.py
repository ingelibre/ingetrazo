# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The AI bridge's named tools (Marco, 19-11): an agent whose client does
not allow ``run_python`` works through tools with a name and a schema —
each one tried here through the REAL bridge on a free port, the way
``scripts/ingetrazo_mcp.py`` talks to it; what changes the document is one
undo step; errors say what went wrong; and ``ingetrazo --server`` runs it
all without a window."""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

ROOT = Path(__file__).resolve().parents[1]


def _rpc(sock, tool, args=None, ids=None):
    # #892: every request but list_documents names its window and document.
    sock.sendall((json.dumps(
        {"id": 1, "tool": tool, "args": args or {}, **(ids or {})})
        + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        assert chunk, "bridge closed"
        buf += chunk
    return json.loads(buf.split(b"\n", 1)[0])


def _pump_while(fn):
    """Run ``fn`` on a worker while THIS (Qt main) thread pumps events —
    the bridge executes on the main thread via a queued signal."""
    app = QApplication.instance()
    out: dict = {}

    def worker():
        try:
            out["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            out["error"] = exc

    t = threading.Thread(target=worker)
    t.start()
    while t.is_alive():
        app.processEvents()
        t.join(timeout=0.01)
    if "error" in out:
        raise out["error"]
    return out["value"]


def _ids(bridge) -> dict:
    return {"instance_id": bridge.instance_id,
            "document_id": bridge._document_id()}


def _ask(bridge, tool, args=None):
    ids = _ids(bridge)

    def call():
        with socket.create_connection(("127.0.0.1", bridge.port), 30) as s:
            return _rpc(s, tool, args, ids)
    return _pump_while(call)


def _ok(bridge, tool, args=None):
    reply = _ask(bridge, tool, args)
    assert reply["ok"], reply
    return reply["result"]


def _err(bridge, tool, args=None) -> str:
    reply = _ask(bridge, tool, args)
    assert reply["ok"] is False, reply
    return reply["error"]


def _mcp_module():
    spec = importlib.util.spec_from_file_location(
        "_mcp_named_tools", ROOT / "scripts" / "ingetrazo_mcp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mcp_call(bridge, name, args=None):
    """The MCP server's own ``tools/call``, against this bridge."""
    mod = _mcp_module()
    mod.PORT = bridge.port
    # #892: the client opens a fresh socket per call and needs the document.
    args = {"document_id": bridge._document_id(), **(args or {})}
    return _pump_while(lambda: mod.handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": name, "arguments": args}})["result"])


def _sheet(name, style):
    from core.composition import Composicion
    c = Composicion(name=name)
    f = c.default_frame()
    f.style = style
    c.frames.append(f)
    c.cajetin = c.default_cajetin()
    return c


@pytest.fixture
def env():
    """A window with two boxes, a layer, a material, a scene and two
    sheets (one drawn by lines, one a GL render), clean, and a bridge on a
    free port."""
    from core.ai import run_transactional
    from core.layers import Layer, assign_layer
    from core.materials import Material
    from core.saved_views import SavedView
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    run_transactional(vp, (
        "extrude([(0,0),(2,0),(2,1),(0,1)], 0, 3, name='Caja')\n"
        "extrude([(5,0),(6,0),(6,1),(5,1)], 0, 1, name='Banco')\n"), {})
    scene = vp.scene
    scene.layers.append(Layer("Muros"))
    caja = next(g for g in scene.groups if g.name == "Caja")
    assign_layer(caja, "Muros")
    scene.materials["Ladrillo"] = Material("Ladrillo", color=(0.7, 0.3, 0.2))
    plan = SavedView.capture("Planta", scene, vp.camera)
    plan.hidden_layers = ["Muros"]
    plan.perspective = False
    scene.saved_views.append(plan)
    lines = _sheet("Planta general", "vectorial")
    lines.cajetin.set_field("LÁMINA", "L-01")
    shaded = _sheet("Vista 3D", "sombreado")
    shaded.cajetin.set_field("LÁMINA", "L-02")
    scene.compositions[:] = [lines, shaded]
    vp.history.clear()
    scene.version += 1
    win._saved_version = scene.version
    bridge = _Bridge(vp)
    bridge.allow_save = True          # save_document is gated (PR #1494)
    bridge.start(0)
    try:
        yield win, vp, bridge
    finally:
        bridge.stop()
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- The schema ----------------------------------------------------------------

NAMED = ("get_scene_info", "get_object_info", "list_layers",
         "set_layer_visibility", "list_scenes", "show_scene", "set_camera",
         "select", "screenshot", "export_view", "render_sheet",
         "export_pdf", "document_info", "open_document", "save_document",
         "shutdown", "import_file", "export_file", "list_materials",
         "apply_material")
#: One tool per job (PR #1494 reconciled with n63-mcp, 19-11): the names
#: the PR gave to the same job are the ones left.
RETIRED = ("open_file", "save_file")


def test_tools_list_gives_every_tool_with_its_schema_and_a_bridge_order():
    from plugins.ai_bridge import _Bridge
    mod = _mcp_module()
    reply = mod.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = {t["name"]: t for t in reply["result"]["tools"]}
    for name in NAMED + ("run_python", "query_model", "undo", "redo"):
        assert name in tools, name
    for name in RETIRED:
        assert name not in tools, name
    assert len(tools) == len({t["name"] for t in reply["result"]["tools"]})
    assert "scene" not in tools["screenshot"]["inputSchema"]["properties"]
    for name, tool in tools.items():
        assert callable(getattr(_Bridge, f"_tool_{name}", None)), name
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        props = schema.get("properties", {})
        assert set(schema.get("required", ())) <= set(props), name
        assert tool["description"], name
    # A call's arguments are the handler's: every property is one it takes.
    import inspect
    for name, tool in tools.items():
        params = inspect.signature(getattr(_Bridge, f"_tool_{name}")).parameters
        for prop in tool["inputSchema"].get("properties", {}):
            if prop == "document_id":     # #892: the client's, not sent on
                continue
            assert prop in params, (name, prop)
    assert tools["open_document"]["inputSchema"]["required"] == [
        "path", "document_id"]                      # #892: the document too
    assert "discard_changes" in \
        tools["open_document"]["inputSchema"]["properties"]


# ---- Looking -------------------------------------------------------------------

def test_the_agent_reads_the_document_without_code(env):
    win, vp, bridge = env
    info = _ok(bridge, "get_scene_info")
    assert {"Caja", "Banco"} <= set(info["group_names"])      # query_model's
    assert info["scenes"] == ["Planta"]
    assert [s["number"] for s in info["sheets"]] == ["L-01", "L-02"]
    assert {"name": "Muros", "visible": True, "locked": False,
            "folder": None} in info["layers"]
    assert info["modified"] is False and info["path"] is None
    assert info["saving_allowed"] is True             # the fixture's
    assert info["shutdown_allowed"] is False
    assert "georef" in info and "can_render" in info

    caja = next(g for g in vp.scene.groups if g.name == "Caja")
    by_name = _ok(bridge, "get_object_info", {"name": "Caja"})
    assert by_name["id"] == caja.uid and by_name["layer"] == "Muros"
    assert by_name["bounds"]["size"] == pytest.approx([2.0, 1.0, 3.0])
    by_id = _ok(bridge, "get_object_info", {"id": caja.uid})
    assert by_id["name"] == "Caja"
    assert "no object with name 'Nadie'" in _err(
        bridge, "get_object_info", {"name": "Nadie"})

    layers = _ok(bridge, "list_layers")
    assert [ly["name"] for ly in layers["layers"]][-1] == "Muros"
    scenes = _ok(bridge, "list_scenes")
    assert scenes["scenes"][0]["projection"] == "parallel"
    assert scenes["scenes"][0]["hidden_layers"] == ["Muros"]
    mats = _ok(bridge, "list_materials")["materials"]
    assert any(m["name"] == "Ladrillo" for m in mats)
    assert not win._is_dirty()              # looking changes nothing


# ---- Changes are undo steps --------------------------------------------------------

def test_hiding_a_layer_is_one_undo_step(env):
    win, vp, bridge = env
    depth = len(vp.history.undo_stack)
    out = _ok(bridge, "set_layer_visibility",
              {"layers": ["Muros"], "visible": False})
    assert {"name": "Muros", "visible": False, "locked": False,
            "folder": None} in out["layers"]
    assert vp.scene.layer("Muros").visible is False
    assert len(vp.history.undo_stack) == depth + 1
    assert _ok(bridge, "undo")["ok"]
    assert vp.scene.layer("Muros").visible is True
    assert "no layer called 'Techo'" in _err(
        bridge, "set_layer_visibility", {"layers": ["Techo"],
                                         "visible": False})


def test_painting_named_objects_or_the_selection_is_one_undo_step(env):
    win, vp, bridge = env
    caja = next(g for g in vp.scene.groups if g.name == "Caja")
    depth = len(vp.history.undo_stack)
    out = _ok(bridge, "apply_material", {"material": "Ladrillo",
                                         "names": ["Caja"]})
    assert out["objects"] == 1
    assert caja.material["mat"] == "Ladrillo"
    assert len(vp.history.undo_stack) == depth + 1
    assert _ok(bridge, "undo")["ok"]
    assert not caja.material

    # The selection's loose faces, face by face.
    _ok(bridge, "run_python", {"code": (
        "mesh.add_face([QVector3D(9,0,0), QVector3D(10,0,0), "
        "QVector3D(10,1,0), QVector3D(9,1,0)])")})
    face = vp.scene.mesh.faces[-1]
    vp.scene.select([face])
    out = _ok(bridge, "apply_material", {"material": "Ladrillo"})
    assert out["faces"] == 1 and face.attrs.get("mat") == "Ladrillo"
    assert _ok(bridge, "undo")["ok"]
    assert face.attrs.get("mat") is None

    vp.scene.clear_selection()
    assert "nothing to paint" in _err(bridge, "apply_material",
                                      {"material": "Ladrillo"})
    assert "no material called 'Oro'" in _err(
        bridge, "apply_material", {"material": "Oro", "names": ["Caja"]})


def test_camera_selection_and_scenes_are_the_view_not_the_document(env):
    win, vp, bridge = env
    cam = _ok(bridge, "set_camera", {"view": "top", "projection": "parallel",
                                     "zoom_extents": True})
    assert cam["projection"] == "parallel"
    assert vp.camera.perspective is False
    cam = _ok(bridge, "set_camera", {"eye": [10, -10, 5], "target": [1, 0, 1],
                                     "projection": "perspective", "fov": 50})
    assert cam["eye"] == pytest.approx([10, -10, 5], abs=1e-3)
    assert cam["target"] == pytest.approx([1, 0, 1])
    assert cam["fov"] == 50
    assert "unknown view" in _err(bridge, "set_camera", {"view": "sky"})
    assert "eye and target go together" in _err(
        bridge, "set_camera", {"eye": [1, 2, 3]})

    caja = next(g for g in vp.scene.groups if g.name == "Caja")
    out = _ok(bridge, "select", {"names": ["Caja", "Banco"]})
    assert out["selected"] == 2
    out = _ok(bridge, "select", {"ids": [caja.uid], "mode": "remove"})
    assert out["selected"] == 1 and caja not in vp.scene.selection
    assert _ok(bridge, "select", {"clear": True})["selected"] == 0
    assert "no object with id 'zzz'" in _err(bridge, "select",
                                              {"ids": ["zzz"]})

    out = _ok(bridge, "show_scene", {"name": "Planta"})
    assert out["camera"]["projection"] == "parallel"
    assert vp.scene.layer("Muros").visible is False      # the scene's layers
    assert "no scene called 'Alzado'" in _err(bridge, "show_scene",
                                              {"name": "Alzado"})
    assert not vp.history.undo_stack                     # none was a step


# ---- Renders ---------------------------------------------------------------------

def test_without_opengl_the_renders_say_why_and_the_rest_works(env,
                                                               monkeypatch):
    win, vp, bridge = env
    monkeypatch.setattr(vp, "_gl", None)
    assert "no OpenGL context" in _err(bridge, "screenshot")
    assert "no OpenGL context" in _err(bridge, "export_view",
                                       {"view": "Planta"})
    assert "no OpenGL context" in _err(bridge, "render_sheet",
                                       {"sheet": "L-02"})     # a GL view
    assert _ok(bridge, "get_scene_info")["can_render"] is False
    # The scene was never shown: the user's layers are as they were.
    assert vp.scene.layer("Muros").visible is True


def test_a_screenshot_of_a_scene_leaves_the_users_view_as_it_was(
        env, monkeypatch, tmp_path):
    """``export_view``: the picture is the scene's (its
    layers, its camera), and the user gets back the view he had — and a
    clean document stays clean."""
    from PySide6.QtGui import QImage
    from views import bridge_tools
    win, vp, bridge = env
    seen = {}

    def render(self, width, height):
        seen["muros"] = vp.scene.layer("Muros").visible
        seen["perspective"] = vp.camera.perspective
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(0)
        return image

    monkeypatch.setattr(bridge_tools.BridgeTools, "_render_view", render)
    monkeypatch.setattr(bridge_tools, "can_render", lambda vp: True)
    vp.camera.perspective = True
    yaw = vp.camera.yaw
    out = tmp_path / "planta.png"
    got = _ok(bridge, "export_view", {"view": "Planta", "width": 200,
                                      "height": 100, "path": str(out)})
    assert out.is_file() and (got["width"], got["height"]) == (200, 100)
    assert seen == {"muros": False, "perspective": False}   # the scene's
    assert vp.scene.layer("Muros").visible is True          # the user's
    assert vp.camera.perspective is True and vp.camera.yaw == yaw
    assert not win._is_dirty()
    assert "no scene called 'Alzado'" in _err(bridge, "export_view",
                                              {"view": "Alzado"})
    # Without a path it goes to the bridge's folder, and the client is
    # SHOWN the picture.
    result = _mcp_call(bridge, "export_view", {"view": "Planta",
                                               "width": 120, "height": 80})
    assert result["content"][0]["type"] == "image"
    assert not win._is_dirty()


def test_a_sheet_of_lines_renders_without_opengl(env, monkeypatch, tmp_path):
    win, vp, bridge = env
    monkeypatch.setattr(vp, "_gl", None)
    out = tmp_path / "l01.png"
    got = _ok(bridge, "render_sheet", {"sheet": "L-01", "width": 800,
                                       "path": str(out)})
    assert got["sheet"] == "Planta general" and out.is_file()
    assert got["width"] == 800 or abs(got["width"] - 800) <= 2
    assert _ok(bridge, "render_sheet", {"sheet": 1})["sheet"] == \
        "Planta general"
    assert "no sheet 'L-09'" in _err(bridge, "render_sheet",
                                     {"sheet": "L-09"})
    # A name that begins with the sheet's number finds it by the number.
    assert _ok(bridge, "render_sheet", {"sheet": "Planta"})["sheet"] == \
        "Planta general"
    # The title block's «N.º» is the number, before «LÁMINA» (which
    # plaza-final3 uses for the title).
    vp.scene.compositions[1].cajetin.set_field("N.º", "A-07")
    # Found by it (then refused for its GL view, here without GL).
    assert "no OpenGL" in _err(bridge, "render_sheet", {"sheet": "a-07"})
    assert _ok(bridge, "get_scene_info")["sheets"][1]["number"] == "A-07"
    vp.scene.compositions[1].name = "Planta 3D"
    assert "begins several sheets" in _err(bridge, "render_sheet",
                                           {"sheet": "Planta"})
    # Through the MCP server: the client is SHOWN the picture.
    result = _mcp_call(bridge, "render_sheet", {"sheet": "Planta general",
                                                "width": 400})
    assert result["content"][0]["type"] == "image"
    assert result["content"][0]["mimeType"] == "image/png"
    assert json.loads(result["content"][1]["text"])["sheet"] == \
        "Planta general"
    assert not win._is_dirty()


# ---- Files -----------------------------------------------------------------------

def test_saving_and_opening_never_lose_unsaved_work(env, tmp_path):
    win, vp, bridge = env
    assert "never been saved" in _err(bridge, "save_document")
    assert "must be absolute" in _err(bridge, "save_document",
                                      {"path": "casa.igz"})
    assert "saved as .igz" in _err(bridge, "save_document",
                                   {"path": str(tmp_path / "casa.obj")})
    first = tmp_path / "primera.igz"
    assert _ok(bridge, "save_document", {"path": str(first)})["path"] == \
        str(first)
    assert first.is_file() and not win._is_dirty()

    _ok(bridge, "run_python", {"code": "scene.groups[-1].name = 'Otra'"})
    _ok(bridge, "run_python", {"code": (
        "mesh.add_edge(QVector3D(0,0,0), QVector3D(0,0,9))")})
    assert win._is_dirty()
    second = tmp_path / "segunda.igz"
    second.write_bytes(first.read_bytes())
    msg = _err(bridge, "open_document", {"path": str(second)})
    assert "unsaved changes" in msg and "discard_changes" in msg
    assert win._is_dirty() and win._current_path == first   # untouched

    assert "no such file" in _err(bridge, "open_document",
                                  {"path": str(tmp_path / "nada.igz")})
    bad = tmp_path / "nota.txt"
    bad.write_text("x")
    assert "does not open '.txt'" in _err(bridge, "open_document",
                                          {"path": str(bad),
                                           "discard_changes": True})
    tabs = len(win._documents)
    info = _ok(bridge, "open_document", {"path": str(second),
                                         "discard_changes": True})
    assert info["path"] == str(second) and info["modified"] is False
    assert len(win._documents) == tabs          # in place, not a new tab
    assert win._current_path == second

    # A save that fails says so (a folder that is not there).
    assert "folder does not exist" in _err(bridge, "save_document", {
        "path": str(tmp_path / "no" / "x.igz")})


def test_an_import_is_one_undo_step(env, tmp_path):
    win, vp, bridge = env
    obj = tmp_path / "piezas.obj"
    _ok(bridge, "export_file", {"path": str(obj)})
    groups = len(vp.scene.groups)
    depth = len(vp.history.undo_stack)

    def counts():
        q = _ok(bridge, "query_model")
        return q["faces"], q["groups"], q["component_instances"]
    before = counts()
    got = _ok(bridge, "import_file", {"path": str(obj), "unit": "m"})
    assert got["undo_steps"] == 1
    assert counts() != before
    assert _ok(bridge, "undo")["ok"]
    assert counts() == before
    assert len(vp.history.undo_stack) == depth

    igz = tmp_path / "pieza.igz"
    _ok(bridge, "save_document", {"path": str(igz)})
    got = _ok(bridge, "import_file", {"path": str(igz)})
    assert got["undo_steps"] == 1 and len(vp.scene.groups) == groups + 1
    assert _ok(bridge, "undo")["ok"]
    assert len(vp.scene.groups) == groups

    assert "unknown import format '.xyz'" in _err(
        bridge, "import_file", {"path": str(_touch(tmp_path / "a.xyz"))})
    assert "no such file" in _err(bridge, "import_file",
                                  {"path": str(tmp_path / "b.obj")})
    assert "unit is one of" in _err(bridge, "import_file",
                                    {"path": str(obj), "unit": "yd"})
    broken = tmp_path / "roto.dae"
    broken.write_text("<not collada")
    msg = _err(bridge, "import_file", {"path": str(broken)})
    assert "could not import" in msg
    assert len(vp.scene.groups) == groups       # nothing half-applied


def _touch(p: Path) -> Path:
    p.write_text("")
    return p


def test_export_writes_each_format_by_its_extension(env, tmp_path):
    from core.bim import tag_group
    win, vp, bridge = env
    for suffix in (".glb", ".dae", ".stl", ".obj", ".dxf"):
        out = tmp_path / f"modelo{suffix}"
        assert _ok(bridge, "export_file", {"path": str(out)})["exported"] \
            == str(out)
        assert out.is_file() and out.stat().st_size > 0, suffix
    assert "only objects tagged" in _err(
        bridge, "export_file", {"path": str(tmp_path / "m.ifc")})
    tag_group(next(g for g in vp.scene.groups if g.name == "Caja"),
              "IfcWall", "Muro")
    got = _ok(bridge, "export_file", {"path": str(tmp_path / "m.ifc")})
    assert got["elements"] == 1
    assert "IFCWALL" in (tmp_path / "m.ifc").read_text().upper()
    pdf = tmp_path / "l01.pdf"
    got = _ok(bridge, "export_pdf", {"path": str(pdf), "sheets": ["L-01"]})
    assert got["sheet_names"] == ["Planta general"] and got["sheets"] == 1
    assert pdf.read_bytes().startswith(b"%PDF")
    # The sheet by its place, as the tabs count; an unknown one is named.
    assert _ok(bridge, "export_pdf", {"path": str(pdf),
                                      "sheets": [1]})["sheets"] == 1
    assert "no sheet 'L-09'" in _err(bridge, "export_pdf",
                                     {"path": str(pdf), "sheets": ["L-09"]})
    # One tool per job: the sheets and the pictures are not export_file's.
    for suffix in (".pdf", ".png", ".jpg"):
        assert "not a model format" in _err(
            bridge, "export_file", {"path": str(tmp_path / f"m{suffix}")})
    assert "unknown export format '.xyz'" in _err(
        bridge, "export_file", {"path": str(tmp_path / "m.xyz")})
    assert "use .glb" in _err(bridge, "export_file",
                              {"path": str(tmp_path / "m.gltf")})
    assert "must be absolute" in _err(bridge, "export_file",
                                      {"path": "m.glb"})
    # The layers ride along in a GLB for a web viewer, and only there.
    glb = tmp_path / "capas.glb"
    _ok(bridge, "export_file", {"path": str(glb), "layers": True})
    from tests.test_gltf_dae_export import _read_glb
    gltf, _ = _read_glb(glb)
    assert [ly["name"] for ly in gltf["asset"]["extras"]["ingetrazo_layers"]] \
        == [ly.name for ly in vp.scene.layers]
    assert "for .glb only" in _err(bridge, "export_file", {
        "path": str(tmp_path / "m.obj"), "layers": True})
    assert not vp.history.undo_stack            # exporting is no step


def test_a_web_page_cannot_reach_the_named_tools_either(env, tmp_path):
    """The new orders go through the bridge's one request check: an HTTP
    POST is cut at its first line, its body never read."""
    win, vp, bridge = env
    target = tmp_path / "robado.igz"
    body = json.dumps({"id": 1, "tool": "save_document",
                       "args": {"path": str(target)}, **_ids(bridge)})
    raw = (f"POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: text/plain"
           f"\r\nContent-Length: {len(body)}\r\n\r\n{body}\n").encode()

    def send():
        with socket.create_connection(("127.0.0.1", bridge.port), 10) as s:
            s.sendall(raw)
            data = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    return data
                data += chunk
    reply = _pump_while(send)
    assert b"not a bridge request" in reply
    assert not target.exists()


# ---- ingetrazo --server --------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM is POSIX")
def test_the_server_mode_answers_and_ends_on_sigterm(tmp_path):
    from core.scene import Scene
    from formats import igz
    from PySide6.QtGui import QVector3D
    scene = Scene()
    scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                         QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([QVector3D(0, 0, 1), QVector3D(1, 0, 1), QVector3D(1, 1, 1)])
    scene.groups.append(Group(m, name="Mesa"))
    doc = tmp_path / "pequeno.igz"
    igz.save_scene(scene, doc)

    env = dict(os.environ)
    for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        (tmp_path / k).mkdir()
        env[k] = str(tmp_path / k)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("INGETRAZO_AI_PORT", None)
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py"), "--server", str(doc),
         "--port", "0"],
        cwd=str(ROOT), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        port, seen = None, []
        deadline = time.monotonic() + 90
        while port is None and time.monotonic() < deadline:
            line = proc.stderr.readline()
            if not line:
                break
            seen.append(line)
            if "AI bridge on 127.0.0.1:" in line:
                port = int(line.split("127.0.0.1:")[1].split()[0])
        assert port, "".join(seen)
        assert "pequeno.igz" in seen[-1]
        # The ready line says whether it can render (offscreen: depends on
        # the machine's drivers), and the screenshot keeps its word.
        renders = "no OpenGL context" not in seen[-1]
        with socket.create_connection(("127.0.0.1", port), 30) as s:
            s.settimeout(60)
            # #892: the server names its one document; every order names it.
            listed = _rpc(s, "list_documents")
            assert listed["ok"], listed
            doc_meta = listed["result"]["documents"][0]
            ids = {"instance_id": doc_meta["instance_id"],
                   "document_id": doc_meta["document_id"]}
            reply = _rpc(s, "get_scene_info", None, ids)
            assert reply["ok"], reply
            assert reply["result"]["group_names"] == ["Mesa"]
            assert reply["result"]["path"] == str(doc)
            png = tmp_path / "vista.png"
            shot = _rpc(s, "screenshot", {"width": 320, "height": 200,
                                          "path": str(png)}, ids)
            if renders:
                assert shot["ok"] and png.is_file(), shot
            else:
                assert shot["ok"] is False and "no OpenGL" in shot["error"]
            assert _rpc(s, "list_layers", None, ids)["ok"]   # still alive
        proc.send_signal(signal.SIGTERM)
        # ``--server`` is ``--headless --ai-bridge``: a signal is the
        # «ended any other way» code, 5; only the agent's shutdown is 0.
        assert proc.wait(timeout=30) == 5
        assert "ended (signal" in proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
