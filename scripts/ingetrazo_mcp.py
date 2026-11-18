#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IngeTrazo MCP server — connect Claude (Code / Desktop) to the live app.

Stdlib-only stdio MCP server: it bridges the Model Context Protocol to the
AI Bridge plugin's localhost TCP port (start it first: IngeTrazo ▸
Extensiones ▸ "AI Bridge (MCP)").

Register it with Claude Code:

    claude mcp add ingetrazo -- python3 /path/to/app/scripts/ingetrazo_mcp.py

Tools: run_python (transactional, one undo step per call), query_model,
screenshot (the agent SEES the viewport), undo, redo; document_info,
open_document, save_document, export_pdf, export_view and shutdown for
automation. Every mutation goes through IngeTrazo's command engine — the
hermeticity guard validates the agent's recipes, and Ctrl+Z always works.

**Without a window** — one command for the MCP client, no IngeTrazo to
start first:

    ingetrazo_mcp.py --headless --open Casa.igz [--allow-save]
                     [--save-format json] [--allow-shutdown]

starts an IngeTrazo of its own with no window (``ingetrazo --headless``)
on a free port, talks to it, and ends it when the client goes. When that
IngeTrazo ends — the agent's ``shutdown``, or an open that failed — this
server ends too, with its exit code (see ``main.EXIT_*``).
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PORT = int(os.environ.get("INGETRAZO_AI_PORT", 4763))
#: Where the bridge is. It only ever listens on the app machine's loopback
#: (no authentication, and run_python runs code in the app); a client in
#: a container or on another machine reaches it through a tunnel the user
#: sets up, and names the tunnel's end here (issue #130).
HOST = os.environ.get("INGETRAZO_AI_HOST", "").strip() or "127.0.0.1"
PROTOCOL = "2024-11-05"

# The recipe book the model needs, from the app's own copy — the SAME text
# the in-app assistant teaches (core/ai_recipes.py explains what its absence
# cost). This process is stdlib-only and starts from four layouts (checkout,
# PyInstaller bundle, AppImage, Flatpak), so the app root goes on the path
# first; if that import ever fails the server still answers, with the short
# reference it can state truthfully.
_APP_ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, _APP_ROOT)
try:
    from core.ai_recipes import reference as _reference
    REFERENCE = _reference("llamada")
except ImportError:                             # pragma: no cover - packaging
    REFERENCE = ("IngeTrazo: Z arriba, unidades en METROS. En el scope: "
                 "scene, mesh, selection, groups, layers, viewport, "
                 "QVector3D, Mesh, Group, Edge, Face, bim. Recetario: "
                 "revolve / extrude / prism / wall / house.")
finally:
    if sys.path and sys.path[0] == _APP_ROOT:   # leave the process as found
        del sys.path[0]

#: MCP's ``initialize`` hands this to the client before any tool is listed —
#: the stance, with the recipes themselves on ``run_python`` where every
#: client is sure to put them in front of the model.
INSTRUCTIONS = (
    "Estas herramientas operan el documento ABIERTO de IngeTrazo, en vivo: "
    "lo que escribas aparece en la pantalla del usuario y entra en su "
    "historial de deshacer.\n" + REFERENCE + "\nEmpieza por query_model "
    "para ver qué hay, construye con run_python y MIRA el resultado con "
    "screenshot. Automatización: document_info dice qué está abierto y qué "
    "se permite; save_document guarda (si IngeTrazo lo permite); "
    "export_view / export_pdf sacan imágenes y láminas; shutdown cierra un "
    "IngeTrazo sin ventana al terminar.")

TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python against the LIVE IngeTrazo document (Z-up, "
            "metres). Returns stdout/stderr. The reference below is "
            "everything you need — read it instead of exploring the API.\n\n"
            + REFERENCE),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
    },
    {
        "name": "query_model",
        "description": ("Model overview: entity counts, group/component "
                        "names, materials, layers, bounds, selection size."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "screenshot",
        "description": ("Render the current viewport and LOOK at it — use "
                        "after building to verify and iterate."),
        "inputSchema": {
            "type": "object",
            "properties": {"width": {"type": "integer"},
                           "height": {"type": "integer"}},
        },
    },
    {
        "name": "undo",
        "description": "Undo the last step in IngeTrazo.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "redo",
        "description": "Redo the last undone step in IngeTrazo.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "document_info",
        "description": ("The open document: its path, whether it has unsaved "
                        "changes, the save format, its sheets and scenes "
                        "(saved views), and whether save_document and "
                        "shutdown are allowed."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_document",
        "description": ("Open an .igz (or .skp/.dae/.dxf) file. An error if "
                        "it cannot be opened."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "save_document",
        "description": (
            "Save the open document, to its own path or to `path` (.igz). "
            "`format`: 'json' (plain JSON for version control; images go to "
            "a <name>.assets folder beside it) or 'auto'; default: the one "
            "IngeTrazo was told to use. Only works when the user allowed it "
            "(--allow-save, or the checkbox in the AI tab)."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"},
                           "format": {"type": "string",
                                      "enum": ["auto", "json"]}},
        },
    },
    {
        "name": "export_pdf",
        "description": ("Export the document's sheets (all, or the named "
                        "ones) into one PDF at `path`."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"},
                           "sheets": {"type": "array",
                                      "items": {"type": "string"}}},
            "required": ["path"],
        },
    },
    {
        "name": "export_view",
        "description": ("Render a scene (saved view, by name — see "
                        "document_info) to a PNG at `path`. The camera is "
                        "put back afterwards."),
        "inputSchema": {
            "type": "object",
            "properties": {"view": {"type": "string"},
                           "path": {"type": "string"},
                           "width": {"type": "integer"},
                           "height": {"type": "integer"}},
            "required": ["view", "path"],
        },
    },
    {
        "name": "shutdown",
        "description": (
            "End this IngeTrazo when the work is done (exit code 0). Only "
            "for an IngeTrazo started with --allow-shutdown. Refused with "
            "unsaved changes unless discard_changes is true."),
        "inputSchema": {
            "type": "object",
            "properties": {"discard_changes": {"type": "boolean"}},
        },
    },
]

_sock: socket.socket | None = None
_req_id = 0


def _bridge(tool: str, args: dict) -> dict:
    """One request to the in-app bridge (reconnecting once if it dropped)."""
    global _sock, _req_id
    for attempt in (0, 1):
        if _sock is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(180.0)
            s.connect((HOST, PORT))
            _sock = s
        _req_id += 1
        try:
            _sock.sendall((json.dumps(
                {"id": _req_id, "tool": tool, "args": args}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = _sock.recv(65536)
                if not chunk:
                    raise OSError("bridge closed the connection")
                buf += chunk
            return json.loads(buf.split(b"\n", 1)[0])
        except OSError:
            try:
                _sock.close()
            except OSError:
                pass
            _sock = None
            if attempt:
                raise
    raise OSError("unreachable")


def _tool_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call(name: str, args: dict) -> dict:
    try:
        reply = _bridge(name, args)
    except OSError as exc:
        return _tool_result(
            "Cannot reach IngeTrazo's AI bridge on %s:%d (%s). "
            "In IngeTrazo: the AI tab of the side tray > Start bridge (or Extensions > AI Bridge (MCP))."
            % (HOST, PORT, exc), is_error=True)
    if not reply.get("ok"):
        return _tool_result(str(reply.get("error")), is_error=True)
    result = reply.get("result") or {}
    if name == "export_view" and result.get("path"):
        try:
            with open(result["path"], "rb") as fh:
                data = base64.b64encode(fh.read()).decode()
            return {"content": [
                {"type": "text", "text": "Written to " + result["path"]},
                {"type": "image", "data": data, "mimeType": "image/png"}]}
        except OSError:
            pass                          # the path alone, below
    if name == "screenshot" and result.get("path"):
        try:
            with open(result["path"], "rb") as fh:
                data = base64.b64encode(fh.read()).decode()
            return {"content": [{"type": "image", "data": data,
                                 "mimeType": "image/png"}]}
        except OSError as exc:
            return _tool_result(f"screenshot unreadable: {exc}",
                                is_error=True)
    if name == "run_python":
        parts = []
        if result.get("stdout"):
            parts.append(result["stdout"].rstrip())
        if result.get("stderr"):
            parts.append("stderr:\n" + result["stderr"].rstrip())
        if result.get("error"):
            parts.append("ROLLED BACK — the document is unchanged: "
                         + str(result["error"]))
        parts.append("(changed: %s)" % result.get("changed"))
        return _tool_result("\n".join(p for p in parts if p),
                            is_error=bool(result.get("error")))
    return _tool_result(json.dumps(result, indent=2, ensure_ascii=False))


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message → the reply dict (None for notifications)."""
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ingetrazo", "version": "1.0.0"},
            "instructions": INSTRUCTIONS,
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        result = _call(params.get("name", ""),
                       params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if msg_id is None:          # notification (initialized, cancelled, ...)
        return None
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"unknown {method}"}}


# ---- A window-less IngeTrazo of our own (--headless) -------------------------
_child: subprocess.Popen | None = None
#: How long the child may take to open its document and start listening.
READY_TIMEOUT = float(os.environ.get("INGETRAZO_HEADLESS_TIMEOUT", 300))


def _app_command() -> list[str]:
    """How to start IngeTrazo from here: the program beside this one in a
    package (``ingetrazo-mcp.exe`` → ``ingetrazo.exe``; ``ingetrazo --mcp``
    is the program itself), or ``main.py`` from a checkout."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        if exe.stem.lower() == "ingetrazo-mcp":
            return [str(exe.with_name("ingetrazo" + exe.suffix))]
        return [str(exe)]
    return [sys.executable, str(Path(_APP_ROOT) / "main.py")]


def _start_child(argv: list[str]) -> int:
    """Start ``ingetrazo --headless`` with ``argv`` and wait until its
    bridge listens; the port. If it ends first (its document would not
    open…), so does this server, with its exit code."""
    global _child
    ready = Path(tempfile.mkdtemp(prefix="ingetrazo-mcp-")) / "port"
    cmd = _app_command() + ["--headless", "--ai-bridge", "--port", "0",
                            "--ready-file", str(ready),
                            "--exit-on-stdin-eof"]
    cmd += [a for a in argv if a not in ("--headless", "--ai-bridge",
                                         "--exit-on-stdin-eof")]
    try:
        err_out = sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        err_out = subprocess.DEVNULL
    # Our stdout is the MCP channel: nothing of the child's may land there.
    # Its stdin is a pipe we never write — when this process goes, however
    # it goes, the pipe closes and the child ends (--exit-on-stdin-eof).
    _child = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=err_out, stderr=err_out,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    atexit.register(_stop_child)
    end = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < end:
        if ready.is_file():
            try:
                return int(ready.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        code = _child.poll()
        if code is not None:
            sys.stderr.write(f"ingetrazo-mcp: IngeTrazo ended before it was "
                             f"ready (exit code {code})\n")
            raise SystemExit(code or 1)
        time.sleep(0.1)
    sys.stderr.write("ingetrazo-mcp: IngeTrazo was not ready in time\n")
    _stop_child()
    raise SystemExit(1)


def _stop_child() -> None:
    if _child is None or _child.poll() is not None:
        return
    try:
        _child.stdin.close()               # asks it to end (code 5)
        _child.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        _child.kill()
        _child.wait()


def _child_ended(wait: float = 0.0) -> int | None:
    """The child's exit code once it has ended (waiting up to ``wait``
    seconds), else None. None too without a child."""
    if _child is None:
        return None
    try:
        return _child.wait(timeout=wait) if wait else _child.poll()
    except subprocess.TimeoutExpired:
        return None


def main() -> None:
    global PORT
    argv = sys.argv[1:]
    if "--headless" in argv:
        PORT = _start_child(argv)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
        if _child is not None:
            shut = (msg.get("method") == "tools/call"
                    and (msg.get("params") or {}).get("name") == "shutdown"
                    and not (reply or {}).get("result", {}).get("isError"))
            code = _child_ended(30.0 if shut else 0.0)
            if code is not None:
                # Its IngeTrazo is gone (the agent's shutdown, a crash):
                # nothing left to serve — end with its code.
                raise SystemExit(code)
    # The client went away: so does our IngeTrazo, and we end with its code.
    if _child is not None:
        _stop_child()
        raise SystemExit(_child.returncode)


if __name__ == "__main__":
    main()
