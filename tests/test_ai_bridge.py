# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""AI Bridge plugin + MCP server: an agent drives the live document over
localhost, transactionally, and the MCP layer frames it for Claude."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _rpc(sock, tool, args=None):
    sock.sendall((json.dumps(
        {"id": 1, "tool": tool, "args": args or {}}) + "\n").encode())
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

    def worker():
        s = socket.socket()
        s.settimeout(10.0)
        s.connect(("127.0.0.1", bridge.port))
        try:
            out["reply"] = _rpc(s, tool, args)
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

    call = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "query_model", "arguments": {}}})
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
    assert mcp_command("linux", frozen=False, root=Path("/src/app")) == \
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
    manifest = (app_root() / "packaging" / "flatpak" / "com.ingetrazo.IngeTrazo.yml").read_text()
    line = next(l for l in manifest.splitlines() if "cp -a main.py" in l)
    assert " scripts " in line + " "


def test_the_mcp_script_ships_with_the_app_and_the_flag_finds_it():
    from core.paths import app_root
    assert (app_root() / "scripts" / "ingetrazo_mcp.py").is_file()
    spec = (app_root() / "ingetrazo.spec").read_text()
    assert "('scripts/ingetrazo_mcp.py',   'scripts')" in spec
    assert "name='ingetrazo-mcp'" in spec and "console=True" in spec


def test_the_mcp_door_hands_the_model_the_same_recipe_book_as_the_assistant():
    """The 2026-09-21 measurement: Antigravity built the dining table
    correctly in 81 calls, 46 of them introspection (``dir``, ``inspect``,
    ``dis``), because ``run_python``'s description taught ``mesh.add_face``
    and nothing else while the in-app assistant's prompt taught the whole
    recipe book. One text, both doors."""
    import ingetrazo_mcp as mcp
    from core import ai_recipes

    run_python = next(t for t in mcp.TOOLS if t["name"] == "run_python")
    description = run_python["description"]
    for recipe in ("revolve(", "extrude(", "prism(", "wall(", "house("):
        assert recipe in description, recipe
    # The two things the model paid the most turns to rediscover.
    assert 'f.attrs["color"]' in description
    assert "METROS" in description
    # And what it should not have spent turns on at all.
    assert "NO explores la API" in description

    # The handshake states the stance before any tool is listed.
    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {}})
    instructions = init["result"]["instructions"]
    assert "Ingeniero" in instructions       # the scale figure, not the model
    assert ai_recipes.RECIPES in instructions

    # Same source as the assistant's prompt: teach a helper once.
    from plugins.ai_assistant import SYSTEM_PROMPT

    assert ai_recipes.RECIPES in SYSTEM_PROMPT
    assert ai_recipes.SCOPE in SYSTEM_PROMPT
    # Each door names its own unit of execution.
    assert "Cada bloque es UN paso de undo" in SYSTEM_PROMPT
    assert "Cada llamada es UN paso de undo" in description


def test_the_packaged_app_would_notice_a_missing_recipe_book():
    """``--check`` is where a packaging slip is supposed to speak up: the
    Flatpak of 0.4.9 shipped without ``scripts/`` and the MCP door was dead
    with the app running fine. Same family as the .skp scaffold."""
    import main

    source = Path(main.__file__).read_text(encoding="utf-8")
    check = source[source.index("def _self_check"):source.index("def main()")]
    assert "ingetrazo_mcp.py" in check
    assert "ai_recipes" in check
