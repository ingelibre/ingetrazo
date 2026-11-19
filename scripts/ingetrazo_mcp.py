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
screenshot (the agent SEES the viewport), undo, redo — and named tools
with a schema, for clients that do not allow code: get_scene_info,
get_object_info, list_layers, set_layer_visibility, list_scenes,
show_scene, set_camera, select, render_sheet, open_file, save_file,
import_file, export_file, list_materials, apply_material. Every mutation
goes through IngeTrazo's command engine — the hermeticity guard validates
the agent's recipes, and Ctrl+Z always works.

Without a window: ``ingetrazo --server [file.igz] [--port N]`` starts the
app headless with the bridge on (docs/ai-bridge.md).
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
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
    "historial de deshacer.\n" + REFERENCE + "\nEmpieza por "
    "get_scene_info para ver qué hay, construye con run_python (o con las "
    "herramientas con nombre si tu cliente no permite código) y MIRA el "
    "resultado con screenshot o render_sheet.")

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
                        "after building to verify and iterate. With "
                        "`scene`, render that saved scene instead; the "
                        "user's view is put back right after. Needs "
                        "OpenGL (an error says so when there is none)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "minimum": 64,
                          "maximum": 4096},
                "height": {"type": "integer", "minimum": 64,
                           "maximum": 4096},
                "scene": {"type": "string",
                          "description": "a saved scene's name"},
                "path": {"type": "string",
                         "description": "absolute .png path to keep it"},
            },
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

_STR = {"type": "string"}
_NAMES = {"type": "array", "items": {"type": "string"},
          "description": "group / component names"}
_IDS = {"type": "array", "items": {"type": "string"},
        "description": "group / component ids (get_object_info's id)"}
_POINT = {"type": "array", "items": {"type": "number"},
          "minItems": 3, "maxItems": 3, "description": "[x, y, z] metres"}
_SHEET = {"type": ["string", "integer"],
          "description": "the sheet's name, its number in the title block "
                         "(L-02) or its place (1 = first)"}
_UNIT = {"type": "string", "enum": ["m", "cm", "mm", "in", "ft"]}

#: Tools with a name and a schema — no code: a client that does not allow
#: run_python works with these (Marco, 19-11). Each one is an order of the
#: bridge (views/bridge_tools.py); what changes the document is one undo
#: step, like run_python.
TOOLS += [
    {
        "name": "get_scene_info",
        "description": ("The document: file, unsaved changes, counts, "
                        "groups, materials, layers with visibility, saved "
                        "scenes, sheets, georeference, bounds, whether it "
                        "can render. Start here."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_object_info",
        "description": ("One group or component by name or id: bounding "
                        "box, layer, material, children, BIM (IFC) tag."),
        "inputSchema": {"type": "object",
                        "properties": {"name": _STR, "id": _STR}},
    },
    {
        "name": "list_layers",
        "description": "The layers: name, visible, locked, folder; the active one.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_layer_visibility",
        "description": "Show or hide layers (one undo step).",
        "inputSchema": {
            "type": "object",
            "properties": {"layers": {"type": "array",
                                      "items": {"type": "string"}},
                           "visible": {"type": "boolean"}},
            "required": ["layers", "visible"],
        },
    },
    {
        "name": "list_scenes",
        "description": "The saved scenes (named views) and the one shown.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "show_scene",
        "description": ("Show a saved scene, as clicking it in the Scenes "
                        "tab: its camera, layers, style, hidden objects."),
        "inputSchema": {"type": "object", "properties": {"name": _STR},
                        "required": ["name"]},
    },
    {
        "name": "set_camera",
        "description": ("Move the camera: a standard view, or eye/target "
                        "(Z up, metres); projection perspective / parallel "
                        "/ two_point; fov in degrees; zoom_extents frames "
                        "the whole model. Returns the camera."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "string",
                         "enum": ["top", "bottom", "front", "back", "left",
                                  "right", "iso"]},
                "eye": _POINT, "target": _POINT, "up": _POINT,
                "projection": {"type": "string",
                               "enum": ["perspective", "parallel",
                                        "two_point"]},
                "fov": {"type": "number"},
                "zoom_extents": {"type": "boolean"},
            },
        },
    },
    {
        "name": "select",
        "description": ("Select groups / components by names or ids "
                        "(mode replace, add, remove, toggle), or clear."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "names": _NAMES, "ids": _IDS,
                "clear": {"type": "boolean"},
                "mode": {"type": "string",
                         "enum": ["replace", "add", "remove", "toggle"]},
            },
        },
    },
    {
        "name": "render_sheet",
        "description": ("Render a sheet (lámina) of the composer as a PNG "
                        "and LOOK at it. Views that are GL renders need "
                        "OpenGL."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sheet": _SHEET,
                "width": {"type": "integer",
                          "description": "pixels across (default 1600)"},
                "dpi": {"type": "number",
                        "description": "instead of width"},
                "path": {"type": "string",
                         "description": "absolute .png path to keep it"},
            },
            "required": ["sheet"],
        },
    },
    {
        "name": "open_file",
        "description": ("Open a document (absolute path; .igz, .dae, .skp, "
                        ".dxf, .dwg) in place of the one in front. Refuses "
                        "if that one has unsaved changes, unless "
                        "discard_changes is true."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": _STR,
                           "discard_changes": {"type": "boolean"}},
            "required": ["path"],
        },
    },
    {
        "name": "save_file",
        "description": ("Save the document; with path (absolute .igz), "
                        "save it as that file."),
        "inputSchema": {"type": "object", "properties": {"path": _STR}},
    },
    {
        "name": "import_file",
        "description": ("Import a file into the document (one undo step): "
                        ".igz (as a component), .dae, .glb/.gltf, .skp, "
                        ".obj, .stl, .dxf, .dwg. unit for OBJ/STL/DXF, "
                        "make_faces for DXF/DWG."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": _STR, "unit": _UNIT,
                           "make_faces": {"type": "boolean"}},
            "required": ["path"],
        },
    },
    {
        "name": "export_file",
        "description": ("Export by the file's extension (absolute path): "
                        ".ifc (BIM-tagged objects), .glb, .dae, .stl "
                        "(unit, default mm), .obj, .dxf (the view's lines), "
                        ".pdf (sheet, or every sheet), .png/.jpg (the "
                        "view, width px)."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": _STR, "sheet": _SHEET, "unit": _UNIT,
                           "selection_only": {"type": "boolean"},
                           "width": {"type": "integer"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_materials",
        "description": "The document's materials: name, colour, texture, opacity.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "apply_material",
        "description": ("Paint with one of the document's materials: the "
                        "objects named (names / ids) as a whole, or else "
                        "the selection. One undo step."),
        "inputSchema": {
            "type": "object",
            "properties": {"material": _STR, "names": _NAMES, "ids": _IDS},
            "required": ["material"],
        },
    },
]

#: The tools whose reply is a picture the client is shown.
IMAGE_TOOLS = ("screenshot", "render_sheet")

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
            "In IngeTrazo: the AI tab of the side tray > Start bridge (or Extensions > AI Bridge (MCP)); "
            "or start one without a window: ingetrazo --server [file.igz]."
            % (HOST, PORT, exc), is_error=True)
    if not reply.get("ok"):
        return _tool_result(str(reply.get("error")), is_error=True)
    result = reply.get("result") or {}
    if name in IMAGE_TOOLS and result.get("path"):
        try:
            with open(result["path"], "rb") as fh:
                data = base64.b64encode(fh.read()).decode()
            return {"content": [
                {"type": "image", "data": data, "mimeType": "image/png"},
                {"type": "text",
                 "text": json.dumps(result, ensure_ascii=False)}]}
        except OSError as exc:
            return _tool_result(f"{name} unreadable: {exc}",
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
