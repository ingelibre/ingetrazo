#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IngeTrazo MCP server — connect Claude (Code / Desktop) to the live app.

Stdlib-only stdio MCP server: it discovers every enabled local AI Bridge
and routes each document tool to the explicitly selected document. Enable
the bridge in IngeTrazo's AI side tray or Extensions > AI Bridge (MCP).

Register it with Claude Code:

    claude mcp add ingetrazo -- python3 /path/to/app/scripts/ingetrazo_mcp.py

Tools: list_documents, run_python (transactional, one undo step per call),
query_model, screenshot (the agent SEES the viewport), undo, redo. Every
mutation goes through IngeTrazo's command engine — the hermeticity guard
validates the agent's recipes, and Ctrl+Z always works.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

# A configured PORT deliberately selects one forwarded endpoint. Otherwise
# discover all local windows, regardless of HOST (which only names a tunnel).
_PORT = os.environ.get("INGETRAZO_AI_PORT", "").strip()
PORT = (int(_PORT) or None) if _PORT else None
HOST = os.environ.get("INGETRAZO_AI_HOST", "").strip() or "127.0.0.1"
DISCOVERY_TIMEOUT = 0.5
OPERATION_TIMEOUT = 180.0
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
    from core.ai_discovery import read_endpoints
    try:
        from core.ai_recipes import reference as _reference
        REFERENCE = _reference("llamada")
    except ImportError:                         # pragma: no cover - packaging
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
    "Estas herramientas operan documentos ABIERTOS de IngeTrazo, en vivo: "
    "lo que escribas aparece en la pantalla del usuario y entra en su "
    "historial de deshacer. Empieza por list_documents y elige explícitamente "
    "un document_id para cada llamada. Si cambia o se cierra el documento, "
    "vuelve a list_documents; nunca se elige una ventana por defecto.\n"
    + REFERENCE + "\nUsa query_model para ver qué hay, construye con "
    "run_python y MIRA el resultado con screenshot.")

TOOLS = [
    {
        "name": "list_documents",
        "description": (
            "Discover enabled IngeTrazo windows and their live document IDs, "
            "names, paths, titles, dirty state and revisions. Enable the "
            "AI bridge in each desired window. Rescan after New/Open/close."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_python",
        "description": (
            "Execute Python against the LIVE IngeTrazo document (Z-up, "
            "metres). Returns stdout/stderr. The reference below is "
            "everything you need — read it instead of exploring the API.\n\n"
            + REFERENCE),
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"},
                           "code": {"type": "string"}},
            "required": ["document_id", "code"],
        },
    },
    {
        "name": "query_model",
        "description": ("Model overview: entity counts, group/component "
                        "names, materials, layers, bounds, selection size."),
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
        },
    },
    {
        "name": "screenshot",
        "description": ("Render the current viewport and LOOK at it — use "
                        "after building to verify and iterate."),
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"},
                           "width": {"type": "integer"},
                           "height": {"type": "integer"}},
            "required": ["document_id"],
        },
    },
    {
        "name": "undo",
        "description": "Undo the last step in IngeTrazo.",
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
        },
    },
    {
        "name": "redo",
        "description": "Redo the last undone step in IngeTrazo.",
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "string"}},
            "required": ["document_id"],
        },
    },
]

_req_id = 0


def _bridge(endpoint: dict, tool: str, args: dict,
            document_id: str | None = None) -> dict:
    """Send once on a fresh socket; an uncertain operation is never replayed."""
    global _req_id
    _req_id += 1
    request = {"id": _req_id, "tool": tool, "args": args}
    if endpoint.get("instance_id"):
        request["instance_id"] = endpoint["instance_id"]
    if document_id is not None:
        request["document_id"] = document_id
    timeout = DISCOVERY_TIMEOUT if tool == "list_documents" else OPERATION_TIMEOUT
    with socket.create_connection((endpoint["host"], endpoint["port"]),
                                  timeout=timeout) as connection:
        connection.sendall((json.dumps(request) + "\n").encode())
        with connection.makefile("rb") as stream:
            line = stream.readline()
        if not line.endswith(b"\n"):
            raise OSError("bridge closed before replying; operation was not retried")
        reply = json.loads(line)
    if (not isinstance(reply, dict)
            or type(reply.get("id")) is not int
            or reply["id"] != request["id"]):
        raise ValueError("bridge reply has a mismatched request ID")
    if type(reply.get("ok")) is not bool:
        raise ValueError("bridge returned an invalid response")
    if reply["ok"] and not isinstance(reply.get("result"), dict):
        raise ValueError("bridge returned an invalid result")
    return reply


def _discover() -> list[tuple[dict, dict]]:
    """Read registry and live metadata anew; stale records are never targets."""
    endpoints = ([{"host": HOST, "port": PORT}] if PORT is not None
                 else read_endpoints())
    documents = []
    for endpoint in endpoints:
        try:
            reply = _bridge(endpoint, "list_documents", {})
            if not reply["ok"]:
                continue
            metadata = reply["result"].get("documents")
            if not isinstance(metadata, list):
                continue
            for document in metadata:
                if not isinstance(document, dict):
                    continue
                instance_id = document.get("instance_id")
                document_id = document.get("document_id")
                if (not isinstance(instance_id, str) or not instance_id
                        or not isinstance(document_id, str)
                        or not document_id.startswith(instance_id + ":")
                        or document_id == instance_id + ":"
                        or (endpoint.get("instance_id") is not None
                            and endpoint["instance_id"] != instance_id)):
                    continue
                live_endpoint = dict(endpoint, instance_id=instance_id)
                documents.append((document, live_endpoint))
        except (OSError, ValueError):
            continue
    return documents


def _target(document_id: str) -> dict:
    for document, endpoint in _discover():
        if document["document_id"] == document_id:
            return endpoint
    location = f" at {HOST}:{PORT}" if PORT is not None else ""
    raise ValueError(
        f"Document {document_id!r} is no longer available{location}. "
        "Call list_documents and choose a live document_id. Enable the AI "
        "bridge in the desired IngeTrazo window (AI side tray > Start bridge "
        "or Extensions > AI Bridge (MCP)).")


def _tool_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call(name: str, args: dict) -> dict:
    if name not in {tool["name"] for tool in TOOLS}:
        return _tool_result(f"Unknown tool: {name}", is_error=True)
    if not isinstance(args, dict):
        return _tool_result("Tool arguments must be an object.", is_error=True)
    if name == "list_documents":
        return _tool_result(json.dumps(
            {"documents": [document for document, _ in _discover()]},
            indent=2, ensure_ascii=False))
    document_id = args.get("document_id")
    if not isinstance(document_id, str) or not document_id.strip():
        return _tool_result(
            "document_id is required. Call list_documents and choose a live "
            "document explicitly.", is_error=True)
    try:
        endpoint = _target(document_id)
        bridge_args = {key: value for key, value in args.items()
                       if key != "document_id"}
        reply = _bridge(endpoint, name, bridge_args, document_id)
    except (OSError, ValueError) as exc:
        return _tool_result(
            f"Cannot operate on document {document_id!r}: {exc}. "
            "No operation was retried. Call list_documents to rediscover "
            "available documents; enable the AI bridge in the desired "
            "IngeTrazo window if necessary.", is_error=True)
    if not reply.get("ok"):
        return _tool_result(str(reply.get("error")), is_error=True)
    result = reply.get("result") or {}
    if name == "screenshot":
        if (not isinstance(result.get("data"), str)
                or result.get("mimeType") != "image/png"):
            return _tool_result("Bridge returned an invalid screenshot.",
                                is_error=True)
        return {"content": [{"type": "image", "data": result["data"],
                             "mimeType": result["mimeType"]}]}
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
            "serverInfo": {"name": "ingetrazo", "version": "2.0.0"},
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
