# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""AI Bridge plugin + MCP server: an agent drives the live document over
localhost, transactionally, and the MCP layer frames it for Claude."""
from __future__ import annotations

import json
import math
import os
import socket
import sys
import threading
from pathlib import Path, PurePosixPath

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


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


def _ask(bridge, tool, args=None):
    """Send a request from a worker thread while THIS (main/Qt) thread pumps
    events — the bridge executes on the Qt main thread via a queued signal."""
    app = QApplication.instance()
    out: dict = {}
    ids = {"instance_id": bridge.instance_id,
           "document_id": bridge._document_id()}

    def worker():
        s = socket.socket()
        s.settimeout(10.0)
        s.connect(("127.0.0.1", bridge.port))
        try:
            out["reply"] = _rpc(s, tool, args, ids)
        finally:
            s.close()

    t = threading.Thread(target=worker)
    t.start()
    while t.is_alive():
        app.processEvents()
        t.join(timeout=0.01)
    return out["reply"]


def test_bridge_runs_python_transactionally(monkeypatch):
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")   # ephemeral test port
    win = MainWindow()
    try:
        vp = win.viewport
        bridge = _Bridge(vp)
        bridge.start()
        assert bridge.port

        edges0 = len(vp.scene.mesh.edges)
        reply = _ask(bridge, "run_python", {"code": (
            "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")})
        assert reply["ok"] and reply["result"]["changed"] is True
        assert len(vp.scene.mesh.edges) == edges0 + 1
        assert vp.history.undo()                    # ONE undoable step
        assert len(vp.scene.mesh.edges) == edges0

        # A crashing script rolls back whole and reports the error.
        depth = len(vp.history.undo_stack)
        reply = _ask(bridge, "run_python", {"code": (
            "mesh.add_edge(QVector3D(9,0,0), QVector3D(9,9,0))\n"
            "raise RuntimeError('boom')")})
        assert reply["ok"] and reply["result"]["changed"] is False
        assert reply["result"]["error"]
        assert len(vp.scene.mesh.edges) == edges0   # nothing half-applied
        assert len(vp.history.undo_stack) == depth

        # Inspect-only runs leave no undo entry.
        reply = _ask(bridge, "run_python",
                     {"code": "print(len(mesh.edges))"})
        assert reply["ok"] and reply["result"]["changed"] is False
        assert reply["result"]["stdout"].strip() == str(edges0)
        assert len(vp.history.undo_stack) == depth

        reply = _ask(bridge, "query_model")
        assert reply["ok"]
        assert reply["result"]["edges"] == edges0
        assert "layers" in reply["result"]

        reply = _ask(bridge, "no_such_tool")
        assert reply["ok"] is False and "unknown tool" in reply["error"]

        bridge.stop()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_sheet_made_through_the_bridge_is_one_undoable_step(monkeypatch):
    """#694: a sheet appended by ``run_python`` was no step at all — the
    reply said nothing changed, and the agent's undo took the user's last
    edit while the sheet stayed. A script that failed after appending one
    left it behind."""
    from core.history import AddEdgeCommand
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    from PySide6.QtGui import QVector3D
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    try:
        vp = win.viewport
        vp.history.execute(AddEdgeCommand(QVector3D(0, 0, 0),
                                          QVector3D(3, 0, 0)))  # the user's
        edges = len(vp.scene.mesh.edges)
        sheets = len(vp.scene.compositions)
        bridge = _Bridge(vp)
        bridge.start()
        add = ("from core.composition import Composicion\n"
               "c = Composicion(name='A1')\n"
               "c.frames.append(c.default_frame())\n"
               "scene.compositions.append(c)\n")

        reply = _ask(bridge, "run_python", {"code": add})
        assert reply["ok"] and reply["result"]["changed"] is True
        assert len(vp.scene.compositions) == sheets + 1
        assert _ask(bridge, "undo")["result"]["ok"]
        assert len(vp.scene.compositions) == sheets      # the sheet went
        assert len(vp.scene.mesh.edges) == edges         # the user's edge stayed
        assert _ask(bridge, "redo")["result"]["ok"]
        assert vp.scene.compositions[-1].name == "A1"
        assert vp.history.undo()

        reply = _ask(bridge, "run_python",
                     {"code": add + "raise RuntimeError('boom')"})
        assert reply["result"]["error"] and reply["result"]["changed"] is False
        assert len(vp.scene.compositions) == sheets      # nothing half-applied
        bridge.stop()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_dialog_opened_by_the_agent_is_cancelled_not_waited_for(monkeypatch):
    """#694: deleting a sheet asks Yes/No, and the last sheet says it must
    stay — over the bridge nobody answers, so exec() held the UI thread for
    good and the next call ran inside that dialog. Now the dialog is
    cancelled at once, the reply names it, and nothing was deleted."""
    import time
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    try:
        vp = win.viewport
        bridge = _Bridge(vp)
        bridge.start()
        two = ("w = viewport.window()\n"
               "w._show_new_sheet()\n"
               "w._composer._on_comp_add()\n"
               "print(len(scene.compositions))")
        reply = _ask(bridge, "run_python", {"code": two})
        assert reply["ok"] and reply["result"]["stdout"].strip() == "2"
        t0 = time.monotonic()
        reply = _ask(bridge, "run_python", {
            "code": "viewport.window()._composer._on_comp_del()\n"
                    "print(len(scene.compositions))"})
        assert time.monotonic() - t0 < 5
        result = reply["result"]
        assert result["stdout"].strip() == "2"          # «No»: nothing deleted
        assert any("Delete" in t for t in result["dialogs_cancelled"])
        assert "cancelled" in result["stderr"]
        # The bridge answers the next call as usual.
        assert _ask(bridge, "query_model")["ok"]
        bridge.stop()
    finally:
        win._saved_version = win.viewport.scene.version
        comp = getattr(win, "_composer", None)
        if comp is not None:
            comp.hide()
        win.close()


def test_a_call_arriving_inside_a_running_one_is_refused():
    """A call delivered by an event loop nested in the previous one must
    not run inside that one's undo step."""
    import threading as _t
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        bridge = _Bridge(win.viewport)
        bridge.start()
        bridge._busy = True
        # #892: a job names its window and document, from a running bridge.
        req = {"id": 7, "tool": "query_model",
               "instance_id": bridge.instance_id,
               "document_id": bridge._document_id()}
        job = {"req": req, "done": _t.Event(), "reply": None,
               "stop": bridge._stop}
        bridge._run_on_main(job)
        assert job["done"].is_set() and job["reply"]["ok"] is False
        assert "previous call" in job["reply"]["error"]
        bridge._busy = False
        job["done"].clear()
        bridge._run_on_main(job)
        assert job["reply"]["ok"] is True, job["reply"]
    finally:
        bridge.stop()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_mcp_server_protocol_and_bridge_down_message(monkeypatch):
    import ingetrazo_mcp as mcp
    monkeypatch.setattr(mcp, "PORT", 1)            # nothing listens there

    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {}})
    assert init["result"]["serverInfo"]["name"] == "ingetrazo"

    tools = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in tools["result"]["tools"]}
    assert {"run_python", "query_model", "screenshot",
            "undo", "redo"} <= names

    assert mcp.handle({"jsonrpc": "2.0",
                       "method": "notifications/initialized"}) is None

    # #892: without a document the client refuses before any socket...
    call = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "query_model", "arguments": {}}})
    result = call["result"]
    assert result["isError"] is True
    assert "list_documents" in result["content"][0]["text"]
    # ...and with one whose bridge is down, it says to enable the bridge.
    call = mcp.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                       "params": {"name": "query_model",
                                  "arguments": {"document_id": "a:b"}}})
    result = call["result"]
    assert result["isError"] is True
    assert "AI bridge" in result["content"][0]["text"]


def test_the_packaged_app_tells_windows_users_the_exe_to_run():
    import json
    from plugins.ai_bridge import connect_instructions, mcp_command, desktop_config_path

    cmd = mcp_command("win32", frozen=True,
                      executable=r"C:\Program Files\IngeTrazo\ingetrazo.exe")
    assert cmd == [r"C:\Program Files\IngeTrazo\ingetrazo-mcp.exe"]
    assert mcp_command("linux", frozen=True, executable="/opt/it/ingetrazo") == \
        ["/opt/it/ingetrazo", "--mcp"]
    # A POSIX root even on a Windows host, where Path("/src/app") is
    # already "\src\app" before mcp_command sees it.
    assert mcp_command("linux", frozen=False,
                       root=PurePosixPath("/src/app")) == \
        ["python3", "/src/app/scripts/ingetrazo_mcp.py"]
    assert mcp_command("win32", frozen=False, root=Path(r"C:\src\app"))[0] == "python"
    assert desktop_config_path("win32").endswith("claude_desktop_config.json")

    text = connect_instructions(4763, "win32", frozen=True,
                                executable=r"C:\Program Files\IngeTrazo\ingetrazo.exe")
    assert 'claude mcp add ingetrazo -- "C:\\Program Files\\IngeTrazo\\ingetrazo-mcp.exe"' in text
    snippet = text[text.index("{"):text.rindex("}") + 1]
    assert json.loads(snippet)["mcpServers"]["ingetrazo"]["command"].endswith("ingetrazo-mcp.exe")


def test_the_linux_packages_print_a_command_that_outlives_the_session():
    # The dialog used to print sys.executable — under an AppImage that is
    # /tmp/.mount_XXXX/…, gone at the next launch; under a Flatpak it is a
    # sandbox path the host cannot run. Marco hit both setting Antigravity
    # up for the tutorial (2026-09-21).
    from plugins.ai_bridge import mcp_command, connect_instructions
    mount = "/tmp/.mount_IngeTrJk3f/usr/bin/ingetrazo"
    assert mcp_command("linux", frozen=True, executable=mount,
                       env={"APPIMAGE": "/home/ana/Apps/IngeTrazo-0.4.9-x86_64.AppImage"}) == \
        ["/home/ana/Apps/IngeTrazo-0.4.9-x86_64.AppImage", "--mcp"]
    assert mcp_command("linux", frozen=False, root=Path("/app/ingetrazo"),
                       env={"FLATPAK_ID": "com.ingetrazo.IngeTrazo"}) == \
        ["flatpak", "run", "com.ingetrazo.IngeTrazo", "--mcp"]
    assert mcp_command("linux", frozen=True, executable="/snap/ingetrazo/12/opt/ingetrazo/ingetrazo",
                       env={"SNAP_NAME": "ingetrazo"}) == ["/snap/bin/ingetrazo", "--mcp"]
    # an empty environment falls back to the plain rules
    assert mcp_command("linux", frozen=True, executable="/opt/it/ingetrazo", env={}) == \
        ["/opt/it/ingetrazo", "--mcp"]
    text = connect_instructions(4763, "linux", frozen=False, root=Path("/app/ingetrazo"),
                                env={"FLATPAK_ID": "com.ingetrazo.IngeTrazo"})
    assert "claude mcp add ingetrazo -- flatpak run com.ingetrazo.IngeTrazo --mcp" in text


def test_the_flatpak_ships_the_mcp_script():
    # `flatpak run <id> --mcp` runs scripts/ingetrazo_mcp.py from /app; the
    # manifest must copy scripts/ with the rest of the tree.
    from core.paths import app_root
    manifest = (app_root() / "packaging" / "flatpak" / "com.ingetrazo.IngeTrazo.yml").read_text(encoding="utf-8")
    line = next(l for l in manifest.splitlines() if "cp -a main.py" in l)
    assert " scripts " in line + " "


def test_the_mcp_script_ships_with_the_app_and_the_flag_finds_it():
    from core.paths import app_root
    assert (app_root() / "scripts" / "ingetrazo_mcp.py").is_file()
    spec = (app_root() / "ingetrazo.spec").read_text(encoding="utf-8")
    assert "('scripts/ingetrazo_mcp.py',   'scripts')" in spec
    assert "name='ingetrazo-mcp'" in spec and "console=True" in spec


def test_the_mcp_door_hands_the_model_the_same_recipe_book_as_the_assistant():
    """The 2026-09-21 measurement: Antigravity built the dining table
    correctly in 81 calls, 46 of them introspection (``dir``, ``inspect``,
    ``dis``), because ``run_python``'s description taught ``mesh.add_face``
    and nothing else while the in-app assistant's prompt taught the whole
    recipe book. One book, both doors — in English over MCP, in Spanish
    in the assistant, with the same helpers in both."""
    import ingetrazo_mcp as mcp
    from core import ai_recipes

    run_python = next(t for t in mcp.TOOLS if t["name"] == "run_python")
    description = run_python["description"]
    for recipe in ("box(", "revolve(", "extrude(", "prism(", "wall(",
                   "house("):
        assert recipe in description, recipe
    # The two things the model paid the most turns to rediscover.
    assert 'f.attrs["color"]' in description
    assert "METRES" in description
    # And what it should not have spent turns on at all.
    assert "Do NOT explore the API" in description

    # The handshake states the stance before any tool is listed.
    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {}})
    instructions = init["result"]["instructions"]
    assert "Engineer" in instructions        # the scale figure, not the model
    assert ai_recipes.RECIPES_EN in instructions

    # The assistant keeps the Spanish edition.
    from plugins.ai_assistant import SYSTEM_PROMPT

    assert ai_recipes.RECIPES in SYSTEM_PROMPT
    assert ai_recipes.SCOPE in SYSTEM_PROMPT
    # Each door names its own unit of execution.
    assert "Cada bloque es UN paso de undo" in SYSTEM_PROMPT
    assert "Each call is ONE undo step" in description


def test_the_mcp_door_speaks_english():
    """Tool names, schemas and errors were English already; the handshake
    and the recipe book were Spanish. An MCP client is any agent, in any
    language: the door speaks English."""
    import ingetrazo_mcp as mcp

    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {}})
    texts = [init["result"]["instructions"]] + [
        t["description"] for t in mcp.TOOLS]
    for text in texts:
        for spanish in ("Recetario", "En el scope", "Cada llamada",
                        "Empieza por", "unidades en METROS", "Estas "
                        "herramientas"):
            assert spanish not in text, spanish


def test_both_editions_of_the_recipe_book_teach_the_same_code():
    """Two languages must not become two books: every helper call and
    keyword argument taught in one edition is taught in the other."""
    import re

    from core import ai_recipes

    def code(text):
        calls = set(re.findall(r"\b([a-z_][a-z_.]*)\(", text))
        kwargs = set(re.findall(r"\b([a-z_]+)=", text))
        return calls, kwargs

    calls_es, kwargs_es = code(ai_recipes.RECIPES)
    calls_en, kwargs_en = code(ai_recipes.RECIPES_EN)
    assert calls_es == calls_en
    assert kwargs_es == kwargs_en
    assert ai_recipes.reference("call", lang="en").startswith(
        ai_recipes.UNITS_EN)
    assert ai_recipes.reference() == ai_recipes.reference("llamada", "es")


def test_no_mcp_python_hides_and_refuses_run_python(monkeypatch):
    """``--no_mcp_python``: run_python is not listed, a call to it is
    refused before any socket, and the handshake carries no recipe book
    the model could not run. Every other tool stays."""
    import ingetrazo_mcp as mcp
    monkeypatch.setattr(mcp, "PORT", 1)            # nothing listens there
    monkeypatch.setattr(mcp, "PYTHON_ALLOWED", False)

    tools = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {t["name"] for t in tools["result"]["tools"]}
    assert "run_python" not in names
    assert {"list_documents", "get_scene_info", "screenshot",
            "apply_material"} <= names

    call = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "run_python",
                                  "arguments": {"document_id": "a:b",
                                                "code": "print(1)"}}})
    result = call["result"]
    assert result["isError"] is True
    assert "--no_mcp_python" in result["content"][0]["text"]

    init = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "initialize",
                       "params": {}})
    instructions = init["result"]["instructions"]
    assert "run_python is disabled" in instructions
    assert "Recipe book" not in instructions

    # The flag, in either spelling, switches it off in main().
    for flag in ("--no_mcp_python", "--no-mcp-python"):
        monkeypatch.setattr(mcp, "PYTHON_ALLOWED", True)
        monkeypatch.setattr(sys, "argv", ["ingetrazo_mcp.py", flag])
        monkeypatch.setattr(sys, "stdin", iter(()))
        mcp.main()
        assert mcp.PYTHON_ALLOWED is False


def test_the_bridge_refuses_run_python_when_told(monkeypatch):
    """The window-less IngeTrazo's own gate (``--no_mcp_python`` reaches
    it through ``main._parse_headless``): a client that talks to the
    bridge directly is refused too; the named tools still answer."""
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    try:
        vp = win.viewport
        bridge = _Bridge(vp)
        bridge.allow_python = False
        bridge.start()
        edges0 = len(vp.scene.mesh.edges)
        reply = _ask(bridge, "run_python", {"code": (
            "mesh.add_edge(QVector3D(0,0,0), QVector3D(2,0,0))")})
        assert reply["ok"] is False
        assert "PermissionError" in reply["error"]
        assert "--no_mcp_python" in reply["error"]
        assert len(vp.scene.mesh.edges) == edges0
        reply = _ask(bridge, "document_info")
        assert reply["ok"] and reply["result"]["python_allowed"] is False
        assert _ask(bridge, "query_model")["ok"]
        bridge.stop()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_packaged_app_would_notice_a_missing_recipe_book():
    """``--check`` is where a packaging slip is supposed to speak up: the
    Flatpak of 0.4.9 shipped without ``scripts/`` and the MCP door was dead
    with the app running fine. Same family as the .skp scaffold."""
    import main

    source = Path(main.__file__).read_text(encoding="utf-8")
    check = source[source.index("def _self_check"):source.index("def main()")]
    assert "ingetrazo_mcp.py" in check
    assert "ai_recipes" in check


def _send_raw(bridge, payload: bytes) -> bytes:
    """Send ``payload`` as-is and read until the bridge closes or goes quiet,
    pumping Qt events on this thread so anything it dispatches can run."""
    app = QApplication.instance()
    out: dict = {"got": b""}

    def worker():
        s = socket.socket()
        s.settimeout(2.0)
        s.connect(("127.0.0.1", bridge.port))
        try:
            s.sendall(payload)
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                out["got"] += chunk
        except OSError:
            pass
        finally:
            s.close()

    t = threading.Thread(target=worker)
    t.start()
    while t.is_alive():
        app.processEvents()
        t.join(timeout=0.01)
    return out["got"]


def test_a_web_page_cannot_run_code_through_the_bridge(monkeypatch):
    """Loopback is not a wall against the browser on the same machine. A page
    can POST to http://127.0.0.1:4763 with ``fetch(..., {mode: "no-cors",
    body})``: a text/plain POST needs no CORS preflight, so the browser sends
    it and only hides the answer. The bridge reads lines, so the HTTP request
    line and headers fail as bad JSON — and the body line, a tool call, ran.
    These are the bytes that request puts on the wire."""
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    try:
        vp = win.viewport
        bridge = _Bridge(vp)
        bridge.start()
        edges0 = len(vp.scene.mesh.edges)
        body = (json.dumps({"id": 1, "tool": "run_python", "args": {"code": (
            "mesh.add_edge(QVector3D(0,0,0), QVector3D(7,0,0))")}}) + "\n").encode()
        request = (
            f"POST / HTTP/1.1\r\nHost: 127.0.0.1:{bridge.port}\r\n"
            "Origin: https://example.com\r\n"
            "Content-Type: text/plain;charset=UTF-8\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode() + body
        _send_raw(bridge, request)
        assert len(vp.scene.mesh.edges) == edges0, (
            "an HTTP request's body ran as a bridge tool call")

        # The agent's own client is unaffected.
        reply = _ask(bridge, "run_python", {"code": "1 + 1"})
        assert reply["ok"]
        bridge.stop()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_screenshot_aims_a_one_shot_camera_and_gives_the_users_back(monkeypatch):
    """``view``/``fit`` let the agent look at the model from a standard
    view without moving the camera the USER is looking through."""
    from plugins.ai_bridge import _Bridge
    from views.main_window import MainWindow
    monkeypatch.setenv("INGETRAZO_AI_PORT", "0")
    win = MainWindow()
    try:
        win.show()                   # a GL context where there is one
        for _ in range(10):
            QApplication.processEvents()
        vp = win.viewport
        bridge = _Bridge(vp)
        bridge.start()
        assert _ask(bridge, "run_python", {"code": (
            "extrude([(0,0),(4,0),(4,3),(0,3)], 0, 2.5, name='Caja')")})["ok"]

        cam = vp.camera
        before = (cam.target.x(), cam.target.y(), cam.target.z(),
                  cam.distance, cam.yaw, cam.pitch, cam.perspective,
                  cam.aspect)
        seen = {}
        real_render = vp.render_image

        def spy(w, h, **kw):
            seen.update(yaw=cam.yaw, pitch=cam.pitch, aspect=cam.aspect,
                        perspective=cam.perspective)
            return real_render(w, h, **kw)

        monkeypatch.setattr(vp, "render_image", spy)
        reply = _ask(bridge, "screenshot",
                     {"width": 800, "height": 400, "view": "top", "fit": True})
        # The camera was aimed for the shot (top view, parallel, 2:1)…
        # (where there is GL to render with: main's bridge refuses first
        # without it, and then there is nothing to aim).
        if seen:
            assert seen["pitch"] == pytest.approx(math.radians(90.0))
            assert seen["aspect"] == pytest.approx(2.0)
            assert seen["perspective"] is False
        # …and given back whether or not this machine could render it.
        after = (cam.target.x(), cam.target.y(), cam.target.z(),
                 cam.distance, cam.yaw, cam.pitch, cam.perspective,
                 cam.aspect)
        assert after == before
        if reply["ok"]:
            assert Path(reply["result"]["path"]).is_file()
        else:
            assert "OpenGL" in reply["error"]

        reply = _ask(bridge, "screenshot", {"view": "sideways"})
        assert reply["ok"] is False and "unknown view" in reply["error"]
        bridge.stop()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_mcp_server_negotiates_the_revision_and_annotates_its_tools():
    import ingetrazo_mcp as mcp

    def init(version):
        return mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": version}})

    # A client's own revision is answered in kind; an unknown one gets ours.
    for version in mcp.PROTOCOLS:
        assert init(version)["result"]["protocolVersion"] == version
    assert init("2099-01-01")["result"]["protocolVersion"] == mcp.PROTOCOL
    assert mcp.PROTOCOL == mcp.PROTOCOLS[0] == max(mcp.PROTOCOLS)

    tools = {t["name"]: t for t in mcp.handle(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    # Looking is safe to auto-approve; running code is not.
    assert tools["query_model"]["annotations"]["readOnlyHint"] is True
    assert tools["screenshot"]["annotations"]["readOnlyHint"] is True
    assert tools["run_python"]["annotations"]["destructiveHint"] is True
    assert all("annotations" in t for t in tools.values())
    # Every name the annotations list is a real tool: a rename (open_file
    # became open_document with #1494) must not leave a stale entry.
    assert set(mcp._READ_ONLY) | set(mcp._DESTRUCTIVE) <= set(tools)
    for tool in ("open_document", "save_document", "shutdown"):
        assert tools[tool]["annotations"]["destructiveHint"] is True

    # The schema offers exactly the views the bridge accepts.
    from views.bridge_tools import STANDARD_VIEWS
    from core.camera import OrbitCamera
    view_enum = tools["screenshot"]["inputSchema"]["properties"]["view"]["enum"]
    assert set(view_enum) == set(STANDARD_VIEWS) == set(OrbitCamera._STANDARD_VIEWS)
