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


def test_the_mcp_script_ships_with_the_app_and_the_flag_finds_it():
    from core.paths import app_root
    assert (app_root() / "scripts" / "ingetrazo_mcp.py").is_file()
    spec = (app_root() / "ingetrazo.spec").read_text()
    assert "('scripts/ingetrazo_mcp.py',   'scripts')" in spec
    assert "name='ingetrazo-mcp'" in spec and "console=True" in spec
