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
screenshot (the agent SEES the viewport), undo, redo. Every mutation goes
through IngeTrazo's command engine — the hermeticity guard validates the
agent's recipes, and Ctrl+Z always works.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys

PORT = int(os.environ.get("INGETRAZO_AI_PORT", 4763))
PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python against the LIVE IngeTrazo document. In scope: "
            "scene, mesh, selection, groups, layers, viewport, QVector3D, "
            "Mesh, Group, Edge, Face, bim. Draw with mesh.add_face([...]) / "
            "mesh.add_edge(a, b); every call is ONE undo step and rolls "
            "back whole on error. Returns stdout/stderr. Prefer several "
            "small steps with screenshots over one huge script."),
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
            s.connect(("127.0.0.1", PORT))
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
            "Cannot reach IngeTrazo's AI bridge on 127.0.0.1:%d (%s). "
            "In IngeTrazo: Extensiones > AI Bridge (MCP) to start it."
            % (PORT, exc), is_error=True)
    if not reply.get("ok"):
        return _tool_result(str(reply.get("error")), is_error=True)
    result = reply.get("result") or {}
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


def main() -> None:
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


if __name__ == "__main__":
    main()
