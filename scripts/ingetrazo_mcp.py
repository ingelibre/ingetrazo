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
automation; and the sheet tools (list_sheets, get_sheet,
create/update/delete_sheet, add/update/remove_frame, fit_frame,
set_title_block, add/update_text, list/create/update/delete_view,
render_sheet, export_sheets; #1505). Every mutation goes through
IngeTrazo's command engine — the hermeticity guard validates the agent's
recipes, and Ctrl+Z always works.

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
        "description": ("Open an .igz (or .skp/.dae/.dxf) file in place of "
                        "the document in front, always as it is on disk now "
                        "(a file already open is read again). Refused when "
                        "that would drop unsaved changes, unless "
                        "discard_changes is true. An error if it cannot be "
                        "opened."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"},
                           "discard_changes": {"type": "boolean"}},
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

# ---- Sheets and saved views (#1505) -----------------------------------------
# Stable tools over core/sheets_api.py — no run_python, no private composer
# methods, no open Composer window. Each WRITE is one undo step, returns
# {"result", "changed", "document_revision"} and accepts expected_revision:
# a stale revision is refused, so two clients cannot build on each other's
# deleted views unawares.

#: The {placeholders} sheet texts and title blocks expand, every spelling.
try:
    sys.path.insert(0, _APP_ROOT)
    from core.composition import FIELD_NAMES as _FIELDS
    PLACEHOLDERS = "; ".join(
        "{%s}" % es + "".join(", {%s}" % a for a in names)
        for es, names in _FIELDS.items())
except ImportError:                             # pragma: no cover - packaging
    PLACEHOLDERS = ("{proyecto}/{project}/{projekt}, {lamina}/{sheet}, "
                    "{escala}/{scale}/{massstab}, {fecha}/{date}/{datum}…")
finally:
    if sys.path and sys.path[0] == _APP_ROOT:
        del sys.path[0]

_S = {"type": ["string", "integer"],
      "description": "Sheet: 0-based index in document order, or its name."}
_F = {"type": ["string", "integer"],
      "description": "Frame: index within the sheet, its uid or list name."}
_REV = {"type": "string", "description": (
    "Optional: the document_revision you last read; the call is refused "
    "if the document changed since.")}
_NUM = {"type": "number"}
_FRAME_PROPS = {
    "view": {"type": "string", "description": (
        "A saved view (scene) name, 'std:top' / 'std:front' / 'std:iso'…, "
        "or '__current__' for the live camera.")},
    "scale": {"type": ["number", "string"],
              "description": "Denominator (50) or '1:50' / '10:1'."},
    "x_mm": _NUM, "y_mm": _NUM, "w_mm": _NUM, "h_mm": _NUM,
    "fit": {"type": "string", "enum": ["content", "view"], "description": (
        "content: centre on the visible geometry of the view (its hidden "
        "layers respected); view: drop the frame's own target and use the "
        "saved view's.")},
    "style": {"type": "string", "description": (
        "'style:Architectural', 'style:Hidden line', 'vectorial', "
        "'sombreado'…")},
    "perspective": {"type": "boolean"},
    "cam_target": {"type": ["array", "null"], "items": _NUM,
                   "description": "World point [x,y,z] in m, or null."},
    "show_title": {"type": "boolean"}, "title_text": {"type": "string"},
    "show_scale": {"type": "boolean"}, "hidden": {"type": "boolean"},
    "list_name": {"type": "string"},
}
_TEXT_PROPS = {"text": {"type": "string", "description": (
    "May hold placeholders: " + PLACEHOLDERS)},
    "x_mm": _NUM, "y_mm": _NUM, "w_mm": _NUM, "size_pt": _NUM,
    "bold": {"type": "boolean"}, "align": {"type": "string",
                                           "enum": ["left", "center", "right"]},
    "frame_uid": {"type": "string"}}


def _tool(name, description, props=None, required=(), write=False):
    props = dict(props or {})
    if write:
        props["expected_revision"] = _REV
    schema = {"type": "object", "properties": props}
    if required:
        schema["required"] = list(required)
    return {"name": name, "description": description, "inputSchema": schema}


TOOLS += [
    _tool("list_sheets", (
        "All sheets in document order: index, name, paper, orientation, "
        "frame/text counts, title block yes/no and WARNINGS (frames on a "
        "missing saved view, content clipped at the frame's scale, "
        "non-standard scales with a suggested one, placeholders that will "
        "print literally). Start here.")),
    _tool("get_sheet", (
        "One sheet as JSON: frames (view, scale, x/y/w/h mm, style, "
        "perspective, cam_target, content_mm = drawing extent on paper and "
        "whether it is clipped), texts, title block fields, warnings. "
        "Dimensions only as a count unless cotas=true."),
        {"sheet": _S, "cotas": {"type": "boolean"}}, ["sheet"]),
    _tool("create_sheet", (
        "New sheet: empty with one frame filling the page, or a copy of "
        "the sheet 'template' names; placed after the sheet 'after' names "
        "(in its folder; else last), or at the end of 'folder' (a sheet "
        "folder's path 'A/B' or id; '' = the top)."),
        {"name": {"type": "string"}, "template": _S, "after": _S,
         "paper": {"type": "string", "enum": ["A4", "A3", "A2", "A1", "A0"]},
         "landscape": {"type": "boolean"}, "frame": {"type": "boolean"},
         "title_block": {"type": "boolean"},
         "folder": {"type": "string"}}, ["name"], write=True),
    _tool("update_sheet", "Rename a sheet, change its paper, move it to "
          "'index' (sheets stay with their folders), into 'folder' (path "
          "'A/B' or id; '' = the top), or switch 'print_in_all' (whether "
          "Print all / Export all take it).",
          {"sheet": _S, "name": {"type": "string"},
           "paper": {"type": "string", "enum": ["A4", "A3", "A2", "A1",
                                                "A0"]},
           "landscape": {"type": "boolean"}, "index": {"type": "integer"},
           "margin_mm": _NUM, "folder": {"type": "string"},
           "print_in_all": {"type": "boolean"}}, ["sheet"], write=True),
    _tool("list_sheet_folders", "The sheet explorer's folders, top to "
          "bottom: id, path, Print flag, whether it prints (it and every "
          "folder around it on) and its own sheets. list_sheets gives each "
          "sheet's folder, print_in_all and printed."),
    _tool("delete_sheet", "Delete a sheet (needs confirm=true; a document "
          "keeps at least one).",
          {"sheet": _S, "confirm": {"type": "boolean"}}, ["sheet"],
          write=True),
    _tool("add_frame", "Add a view frame to a sheet. Without x/y/w/h it "
          "fills the page inside the margins.",
          {"sheet": _S, **_FRAME_PROPS}, ["sheet"], write=True),
    _tool("update_frame", "Change a frame: view, scale, position/size, "
          "style, framing (fit)…",
          {"sheet": _S, "frame": _F, **_FRAME_PROPS}, ["sheet", "frame"],
          write=True),
    _tool("remove_frame", "Remove a frame from a sheet.",
          {"sheet": _S, "frame": _F}, ["sheet", "frame"], write=True),
    _tool("fit_frame", "Re-frame a frame: mode 'content' centres it on what "
          "its view shows, 'view' takes the saved view's target. Returns "
          "the drawing extent in mm (content_mm) to check it fits.",
          {"sheet": _S, "frame": _F, "mode": _FRAME_PROPS["fit"]},
          ["sheet", "frame"], write=True),
    _tool("set_title_block", (
        "Title block of one sheet or of every sheet (sheet='all'). fields "
        "= [[label, value], …], set row by row (added if missing) unless "
        "replace=true. Values may use placeholders, so ONE set_title_block"
        "('all', …) keeps every sheet current: " + PLACEHOLDERS),
        {"sheet": _S, "fields": {"type": "array", "items": {
            "type": "array", "items": {"type": "string"}}},
         "columns": {"type": "integer"}, "replace": {"type": "boolean"},
         "x_mm": _NUM, "y_mm": _NUM, "w_mm": _NUM, "h_mm": _NUM},
        ["sheet"], write=True),
    _tool("add_text", "Add a text block to a sheet.",
          {"sheet": _S, **_TEXT_PROPS}, ["sheet", "text"], write=True),
    _tool("update_text", "Change a text block (by its index in get_sheet).",
          {"sheet": _S, "index": {"type": "integer"}, **_TEXT_PROPS},
          ["sheet", "index"], write=True),
    _tool("list_views", "Saved views (scenes): name, folder, section, "
          "perspective, hidden layers, target, and the sheets that use "
          "each one."),
    _tool("create_view", "New saved view: a copy of from_view (or of the "
          "live camera), optionally with other hidden layers / target.",
          {"name": {"type": "string"}, "from_view": {"type": "string"},
           "folder": {"type": "string"},
           "hidden_layers": {"type": "array", "items": {"type": "string"}},
           "target": {"type": "array", "items": _NUM}}, ["name"],
          write=True),
    _tool("update_view", "Change a saved view. Renaming it renames every "
          "frame that shows it — no sheet is orphaned.",
          {"view": {"type": "string"}, "name": {"type": "string"},
           "folder": {"type": "string"},
           "hidden_layers": {"type": "array", "items": {"type": "string"}},
           "target": {"type": "array", "items": _NUM}}, ["view"],
          write=True),
    _tool("delete_view", "Delete a saved view (needs confirm=true; the "
          "reply names the sheets left with a missing view).",
          {"view": {"type": "string"}, "confirm": {"type": "boolean"}},
          ["view"], write=True),
    _tool("render_sheet", "Render one sheet to a PNG and LOOK at it — the "
          "screenshot of a sheet. Works with the Composer window closed.",
          {"sheet": _S, "dpi": {"type": "integer",
                                "description": "20-300, default 80"},
           "sheet_set": {"type": "string", "description": (
               "Render it as this sheet set prints it: page number, count "
               "and sheet index within the set, {set} = its name.")}},
          ["sheet"]),
    _tool("export_sheets", (
        "Export sheets without the Composer window: format 'pdf' writes "
        "one file with every sheet a page; 'png' and 'svg' one file per "
        "sheet next "
        "to path. Without 'sheets': the sheets Print all takes (printed in "
        "list_sheets), in the explorer's order. Returns the files and the errors of each sheet (missing "
        "views, frames that did not render)."),
        {"path": {"type": "string", "description": "Absolute file path."},
         "sheets": {"type": "array", "items": _S},
         "format": {"type": "string", "enum": ["pdf", "png", "svg"]},
         "dpi": {"type": "integer"},
         "sheet_set": {"type": "string", "description": (
             "Export this sheet set instead (name or id): its sheets with "
             "Print on, in the set's order; {hoja}/{page}, {total} and the "
             "sheet index count within the set, {set} prints its name.")}},
        ["path"]),
    _tool("list_sheet_sets", "Sheet sets (plan sets): named, ordered "
          "selections of sheets for one audience (permit, roofer, client…). "
          "Each with its sheets in its order (cover first) and those Print "
          "takes. 'All sheets' is implicit: what Print all takes."),
    _tool("get_sheet_set", "One sheet set by name or id.",
          {"set": {"type": "string"}}, ["set"]),
    _tool("create_sheet_set", "New sheet set with 'sheets' (names); they "
          "print in the sheet explorer's order, or with ordered=true in the "
          "order given. Optional cover sheet (printed first) and "
          "description.",
          {"name": {"type": "string"},
           "sheets": {"type": "array", "items": _S}, "cover": _S,
           "description": {"type": "string"},
           "ordered": {"type": "boolean"}}, ["name"], write=True),
    _tool("update_sheet_set", "Rename a set, replace its sheets ('sheets') "
          "or add / remove some; set its cover ('' clears) or description; "
          "ordered=true keeps an explicit order (the order of 'sheets'), "
          "false follows the explorer's order. Sets follow renamed and "
          "moved sheets.",
          {"set": {"type": "string"}, "name": {"type": "string"},
           "sheets": {"type": "array", "items": _S},
           "add": {"type": "array", "items": _S},
           "remove": {"type": "array", "items": _S},
           "cover": _S, "description": {"type": "string"},
           "ordered": {"type": "boolean"}}, ["set"], write=True),
    _tool("delete_sheet_set", "Delete a sheet set (needs confirm=true); its "
          "sheets stay.",
          {"set": {"type": "string"}, "confirm": {"type": "boolean"}},
          ["set"], write=True),
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
    if name in ("screenshot", "render_sheet") and result.get("path"):
        try:
            with open(result["path"], "rb") as fh:
                data = base64.b64encode(fh.read()).decode()
            content = [{"type": "image", "data": data,
                        "mimeType": "image/png"}]
            if name == "render_sheet":
                meta = {k: v for k, v in result.items() if k != "path"}
                content.append({"type": "text", "text": json.dumps(
                    meta, indent=2, ensure_ascii=False)})
            return {"content": content}
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


def _utf8_stdio() -> None:
    """MCP's stdio transport is UTF-8 by definition, but Python reads and
    writes the console's locale encoding — cp1252 on Windows: a «Küche»
    in run_python code arrived as «KÃ¼che» and matched nothing (#1505)."""
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):     # pragma: no cover
            pass


def main() -> None:
    global PORT
    _utf8_stdio()
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
