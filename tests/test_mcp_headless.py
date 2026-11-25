# SPDX-License-Identifier: GPL-3.0-or-later
"""``ingetrazo_mcp.py --headless --open …``: one command for the MCP client.
The server starts a window-less IngeTrazo of its own, serves it, and ends
with that IngeTrazo's exit code."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingetrazo_mcp.py"
EXAMPLE = ROOT / "examples" / "capas-prueba.igz"


def _server(*args):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    return subprocess.Popen(
        [sys.executable, str(SCRIPT), "--headless", *args], cwd=str(ROOT),
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)


def _rpc(proc, n, method, params=None) -> dict:
    msg = {"jsonrpc": "2.0", "id": n, "method": method}
    if params is not None:
        msg["params"] = params
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, proc.stderr.read().decode("utf-8", "replace")
    return json.loads(line)


def _tool(proc, n, name, **args) -> dict:
    if name != "list_documents" and "document_id" not in args:
        # #892: the agent names the document; the server's own IngeTrazo
        # has exactly one.
        listed = json.loads(_text(_tool(proc, 1000 + n, "list_documents")))
        args["document_id"] = listed["documents"][0]["document_id"]
    return _rpc(proc, n, "tools/call", {"name": name, "arguments": args})[
        "result"]


def _text(result) -> str:
    return "".join(c.get("text", "") for c in result["content"])


def test_a_document_that_will_not_open_ends_the_server(tmp_path):
    proc = _server("--open", str(tmp_path / "nope.igz"))
    _out, err = proc.communicate(timeout=180)
    assert proc.returncode == 3, err
    assert b"ended before it was ready" in err


def test_open_save_shutdown_ends_with_0(tmp_path):
    doc = tmp_path / "Casa.igz"
    shutil.copy(EXAMPLE, doc)
    proc = _server("--open", str(doc), "--allow-save", "--save-format",
                   "json", "--allow-shutdown")
    try:
        init = _rpc(proc, 1, "initialize", {})
        assert init["result"]["serverInfo"]["name"] == "ingetrazo"
        names = {t["name"] for t in _rpc(proc, 2, "tools/list")["result"][
            "tools"]}
        assert {"save_document", "shutdown", "export_view",
                "document_info", "open_document", "export_pdf"} <= names
        info = json.loads(_text(_tool(proc, 3, "document_info")))
        assert Path(info["path"]) == doc
        r = _tool(proc, 4, "run_python", code=(
            "mesh.add_edge(QVector3D(70, 0, 0), QVector3D(71, 0, 0))"))
        assert not r["isError"], _text(r)
        r = _tool(proc, 5, "save_document")
        assert not r.get("isError"), _text(r)
        r = _tool(proc, 6, "shutdown")
        assert not r.get("isError"), _text(r)
        proc.stdin.close()
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, proc.stderr.read()
    assert doc.read_bytes().startswith(b"{\n")


def test_the_client_going_away_ends_both_with_5(tmp_path):
    doc = tmp_path / "Casa.igz"
    shutil.copy(EXAMPLE, doc)
    proc = _server("--open", str(doc))
    try:
        _rpc(proc, 1, "initialize", {})
        r = _tool(proc, 2, "shutdown")
        assert r["isError"] and "--allow-shutdown" in _text(r)
        proc.stdin.close()
        proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 5, proc.stderr.read()
