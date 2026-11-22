#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IngeTrazo MCP server — connect Claude (Code / Desktop) to the live app.

Stdlib-only stdio MCP server: it discovers every enabled local AI Bridge
and routes each document tool to the explicitly selected document. Enable
the bridge in IngeTrazo's AI side tray or Extensions > AI Bridge (MCP).

Register it with Claude Code:

    claude mcp add ingetrazo -- python3 /path/to/app/scripts/ingetrazo_mcp.py

Tools: list_documents (start here: every other call names its
document_id, #892), run_python (transactional, one undo step per call),
query_model, screenshot (the agent SEES the viewport), undo, redo — and
named tools with a schema, for clients that do not allow code:
get_scene_info, get_object_info, list_layers, set_layer_visibility,
list_scenes, show_scene, set_camera, select, render_sheet, export_view,
list_materials, apply_material, import_file, export_file; and for
automation document_info, open_document, save_document, export_pdf and
shutdown. Every mutation goes through IngeTrazo's command engine — the
hermeticity guard validates the agent's recipes, and Ctrl+Z always works.

**Without a window** — one command for the MCP client, no IngeTrazo to
start first:

    ingetrazo_mcp.py --headless --open Casa.igz [--allow-save]
                     [--save-format json] [--allow-shutdown]

starts an IngeTrazo of its own with no window (``ingetrazo --headless``)
on a free port, talks to it, and ends it when the client goes. When that
IngeTrazo ends — the agent's ``shutdown``, or an open that failed — this
server ends too, with its exit code (see ``main.EXIT_*``). An IngeTrazo
started by hand without a window (``ingetrazo --server [file.igz]``, the
short form of ``--headless --ai-bridge --open``) is reached like a
windowed one.
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

# A configured PORT deliberately selects one forwarded endpoint. Otherwise
# discover all local windows, regardless of HOST (which only names a tunnel).
_PORT = os.environ.get("INGETRAZO_AI_PORT", "").strip()
PORT = (int(_PORT) or None) if _PORT else None
HOST = os.environ.get("INGETRAZO_AI_HOST", "").strip() or "127.0.0.1"
#: The MCP revisions this server speaks (PR #463): the stdio framing and the
#: tools/* methods used here are the same in all three. A client's own is
#: answered in kind, any other gets the newest.
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
PROTOCOL = PROTOCOLS[0]
DISCOVERY_TIMEOUT = 0.5
OPERATION_TIMEOUT = 180.0

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
    + REFERENCE + "\nLuego get_scene_info para ver qué hay, construye con "
    "run_python (o con las herramientas con nombre si tu cliente no permite "
    "código) y MIRA el resultado con screenshot, export_view o render_sheet. "
    "Automatización: document_info dice qué está abierto y qué se permite "
    "(y el document_id nuevo tras open_document); save_document guarda (si "
    "IngeTrazo lo permite); export_pdf saca las láminas; shutdown cierra un "
    "IngeTrazo sin ventana al terminar.")

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
                        "after building to verify and iterate (a saved "
                        "scene: export_view). Needs OpenGL (an error says "
                        "so when there is none)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "minimum": 64,
                          "maximum": 4096},
                "height": {"type": "integer", "minimum": 64,
                           "maximum": 4096},
                "path": {"type": "string",
                         "description": "absolute .png / .jpg path to "
                                        "keep it"},
                "view": {"type": "string",
                         "enum": ["iso", "top", "bottom", "front", "back",
                                  "left", "right"],
                         "description": "aim the camera for this picture "
                                        "only"},
                "fit": {"type": "boolean",
                        "description": "zoom to the whole model for this "
                                       "picture only"},
            },
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
        "description": ("Open a document (absolute path; .igz, .dae, .skp, "
                        ".dxf, .dwg) in place of the one in front. An error "
                        "if it cannot be opened, and a refusal if the one "
                        "in front has unsaved changes, unless "
                        "discard_changes is true."),
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
        "description": ("Export the document's sheets (all, or the ones "
                        "given by name, title-block number such as L-02, "
                        "or place, 1 = first): format pdf (default) writes "
                        "ONE PDF at `path`; format png writes one PNG per "
                        "sheet, <stem>-<nn>-<sheet>.png beside a .png "
                        "`path` or inside a folder `path`, at `dpi`."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"},
                           "sheets": {"type": "array",
                                      "items": {"type": ["string",
                                                         "integer"]}},
                           "format": {"type": "string",
                                      "enum": ["pdf", "png"]},
                           "dpi": {"type": "number",
                                   "description": "png only (default 150)"}},
            "required": ["path"],
        },
    },
    {
        "name": "export_view",
        "description": ("Render a scene (saved view, by name — see "
                        "document_info) to a PNG and LOOK at it; kept at "
                        "`path` when given. The user's view (camera, "
                        "layers, style, hidden objects) is put back "
                        "afterwards. Needs OpenGL."),
        "inputSchema": {
            "type": "object",
            "properties": {"view": {"type": "string"},
                           "path": {"type": "string"},
                           "width": {"type": "integer"},
                           "height": {"type": "integer"}},
            "required": ["view"],
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

_STR = {"type": "string"}
_NAMES = {"type": "array", "items": {"type": "string"},
          "description": "group / component names"}
_IDS = {"type": "array", "items": {"type": "string"},
        "description": "group / component ids (get_object_info's id)"}
_POINT = {"type": "array", "items": {"type": "number"},
          "minItems": 3, "maxItems": 3, "description": "[x, y, z] metres"}
#: A sheet tool's guard against a stale read (#1505).
EXPECTED = {"type": "integer",
            "description": ("the document_revision a read gave: the edit "
                            "is refused if the document changed since")}
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
        "description": ("The saved scenes (named views) in the Scenes "
                        "tab's order (index 1 = first), the one shown, and "
                        "the sheets whose frames show each (used_by)."),
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
        "name": "list_sheets",
        "description": ("Every sheet (lámina) in order: index (1 = first), "
                        "name, title-block number, paper, frames, folder, "
                        "Print flag, and warnings (a frame on a missing "
                        "scene, clipped, at a non-standard scale with a "
                        "suggested one, {placeholders} printed literally). "
                        "Also document_revision for expected_revision."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_sheet",
        "description": ("One sheet in full: frames (index, uid, view, "
                        "scale, box, where the drawing lands on paper), "
                        "texts, title block rows, warnings. dimensions="
                        "true adds the sheet's dimensions."),
        "inputSchema": {"type": "object",
                        "properties": {"sheet": _SHEET,
                                       "dimensions": {"type": "boolean"}},
                        "required": ["sheet"]},
    },
    {
        "name": "list_sheet_folders",
        "description": ("The sheet explorer's folders, top to bottom: id, "
                        "path, Print flag, and their sheets."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_sheet",
        "description": ("A new sheet (one undo step): empty with one frame "
                        "filling the page, or a copy of `template`; after "
                        "the sheet `after` (into its folder) or last; "
                        "`folder` (path A/B, '' the top) puts it there."),
        "inputSchema": {"type": "object", "properties": {
            "name": _STR, "template": _SHEET, "after": _SHEET,
            "paper": {"type": "string",
                      "enum": ["A0", "A1", "A2", "A3", "A4"]},
            "landscape": {"type": "boolean"}, "frame": {"type": "boolean"},
            "title_block": {"type": "boolean"}, "folder": _STR,
            "expected_revision": EXPECTED},
            "required": ["name"]},
    },
    {
        "name": "update_sheet",
        "description": ("Rename a sheet, change its paper or margin, move "
                        "it to place `index` (1 = first) or into `folder`, "
                        "or switch its Print flag. One undo step."),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "name": _STR,
            "paper": {"type": "string",
                      "enum": ["A0", "A1", "A2", "A3", "A4"]},
            "landscape": {"type": "boolean"},
            "index": {"type": "integer"}, "margin_mm": {"type": "number"},
            "folder": _STR, "print_in_all": {"type": "boolean"},
            "expected_revision": EXPECTED},
            "required": ["sheet"]},
    },
    {
        "name": "delete_sheet",
        "description": ("Delete a sheet (needs confirm=true; a document "
                        "keeps at least one). One undo step."),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "confirm": {"type": "boolean"},
            "expected_revision": EXPECTED},
            "required": ["sheet", "confirm"]},
    },
    {
        "name": "add_frame",
        "description": ("A view frame on a sheet. `view`: a scene's name, "
                        "std:top / std:front / … or __current__. scale 50 "
                        "or '1:50'. Without a box it fills the page inside "
                        "the margins. fit 'content' centres the drawing, "
                        "'view' takes the scene's own framing. `fields`: "
                        "more frame attributes (style, show_title, "
                        "title_text, list_name, hidden, …)."),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "view": _STR,
            "scale": {"type": ["number", "string"]},
            "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
            "w_mm": {"type": "number"}, "h_mm": {"type": "number"},
            "fit": {"type": "string", "enum": ["content", "view"]},
            "fields": {"type": "object"},
            "expected_revision": EXPECTED},
            "required": ["sheet"]},
    },
    {
        "name": "update_frame",
        "description": ("Change a frame (by place, 1 = first, uid or Items "
                        "name): view, scale, box, fit, `fields`."),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "frame": {"type": ["integer", "string"]},
            "view": _STR, "scale": {"type": ["number", "string"]},
            "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
            "w_mm": {"type": "number"}, "h_mm": {"type": "number"},
            "fit": {"type": "string", "enum": ["content", "view"]},
            "fields": {"type": "object"},
            "expected_revision": EXPECTED},
            "required": ["sheet", "frame"]},
    },
    {
        "name": "remove_frame",
        "description": "Remove a frame from a sheet. One undo step.",
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "frame": {"type": ["integer", "string"]},
            "expected_revision": EXPECTED},
            "required": ["sheet", "frame"]},
    },
    {
        "name": "fit_frame",
        "description": ("Frame a view: mode 'content' centres it on what "
                        "the view shows, 'view' takes the scene's (or the "
                        "model's) centre."),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "frame": {"type": ["integer", "string"]},
            "mode": {"type": "string", "enum": ["content", "view"]},
            "expected_revision": EXPECTED},
            "required": ["sheet", "frame"]},
    },
    {
        "name": "set_title_block",
        "description": ("Fill the title block of one sheet, or of every "
                        "sheet with sheet='all': fields [[label, value], "
                        "…] (set, added if missing; replace=true makes them "
                        "THE rows). Values may use {placeholders}: "
                        "{proyecto}/{project}, {fecha}/{date}, {escala}, "
                        "{hoja}/{page}, {total}, …"),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET,
            "fields": {"type": "array", "items": {
                "type": "array", "items": {"type": "string"},
                "minItems": 2, "maxItems": 2}},
            "columns": {"type": "integer"},
            "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
            "w_mm": {"type": "number"}, "h_mm": {"type": "number"},
            "replace": {"type": "boolean"},
            "expected_revision": EXPECTED}},
    },
    {
        "name": "add_text",
        "description": ("A text block on a sheet at x_mm, y_mm; `fields`: "
                        "size_pt, bold, align, w_mm, color, …"),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "text": _STR,
            "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
            "fields": {"type": "object"},
            "expected_revision": EXPECTED},
            "required": ["sheet", "text"]},
    },
    {
        "name": "update_text",
        "description": ("Change a text block (`text` is its place on the "
                        "sheet, 1 = first): `fields` text, x_mm, size_pt, "
                        "…"),
        "inputSchema": {"type": "object", "properties": {
            "sheet": _SHEET, "text": {"type": "integer"},
            "fields": {"type": "object"},
            "expected_revision": EXPECTED},
            "required": ["sheet", "text", "fields"]},
    },
    {
        "name": "create_scene",
        "description": ("A new scene (saved view): a copy of `from_scene`, "
                        "else what the camera shows now; folder, hidden "
                        "layers, target [x, y, z] in metres."),
        "inputSchema": {"type": "object", "properties": {
            "name": _STR, "from_scene": _STR, "folder": _STR,
            "hidden_layers": {"type": "array", "items": _STR}, "target": _POINT,
            "expected_revision": EXPECTED},
            "required": ["name"]},
    },
    {
        "name": "update_scene",
        "description": ("Change a scene. Renaming it renames every frame "
                        "that shows it, so no sheet loses its view."),
        "inputSchema": {"type": "object", "properties": {
            "scene": _STR, "name": _STR, "folder": _STR,
            "hidden_layers": {"type": "array", "items": _STR}, "target": _POINT,
            "expected_revision": EXPECTED},
            "required": ["scene"]},
    },
    {
        "name": "delete_scene",
        "description": ("Delete a scene (needs confirm=true); the reply "
                        "names the sheets whose frames showed it."),
        "inputSchema": {"type": "object", "properties": {
            "scene": _STR, "confirm": {"type": "boolean"},
            "expected_revision": EXPECTED},
            "required": ["scene", "confirm"]},
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
        "description": ("Export the model by the file's extension "
                        "(absolute path): .ifc (BIM-tagged objects), .glb, "
                        ".dae, .stl (unit, default mm), .obj, .dxf (the "
                        "view's lines). Sheets: export_pdf; pictures: "
                        "screenshot, export_view, render_sheet."),
        "inputSchema": {
            "type": "object",
            "properties": {"path": _STR, "unit": _UNIT,
                           "selection_only": {"type": "boolean"}},
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
IMAGE_TOOLS = ("screenshot", "render_sheet", "export_view")


# Every tool but list_documents names the document it acts on (#892): the
# named tools above get the same document_id the PR's tools carry.
for _tool in TOOLS:
    if _tool["name"] == "list_documents":
        continue
    _schema = _tool["inputSchema"]
    _schema.setdefault("properties", {})["document_id"] = {"type": "string"}
    if "document_id" not in _schema.setdefault("required", []):
        _schema["required"].append("document_id")
del _tool, _schema
_req_id = 0


#: MCP tool annotations (PR #463): looking is safe for a client to
#: auto-approve; running code or opening another document is not. Every
#: other tool changes the document through one undoable step.
_READ_ONLY = ("list_documents", "query_model", "screenshot", "get_scene_info",
              "get_object_info", "list_layers", "list_scenes",
              "list_materials", "render_sheet", "document_info",
              "export_view", "list_sheets", "get_sheet",
              "list_sheet_folders")
# Opening another document, overwriting a file or ending the program can
# lose work a client did not mean to lose (names as merged with #1494).
_DESTRUCTIVE = ("run_python", "open_document", "save_document", "shutdown",
                "delete_sheet", "delete_scene")
for _tool in TOOLS:
    _name = _tool["name"]
    _tool["annotations"] = (
        {"readOnlyHint": True, "openWorldHint": False}
        if _name in _READ_ONLY else
        {"readOnlyHint": False, "destructiveHint": _name in _DESTRUCTIVE,
         "openWorldHint": False})


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
            "IngeTrazo window if necessary (or start one without a window: "
            "ingetrazo --server [file.igz]).", is_error=True)
    if not reply.get("ok"):
        return _tool_result(str(reply.get("error")), is_error=True)
    result = reply.get("result") or {}
    if name in IMAGE_TOOLS and not isinstance(result.get("data"), str) \
            and result.get("path"):
        # main's named tools (views/bridge_tools.py) write the PNG to a
        # path; the client reads it and shows it inline, as #892 does.
        try:
            with open(result["path"], "rb") as fh:
                result = dict(result, data=base64.b64encode(fh.read()).decode(),
                              mimeType="image/png")
        except OSError as exc:
            return _tool_result(f"{name} unreadable: {exc}", is_error=True)
    if name in IMAGE_TOOLS:
        if (not isinstance(result.get("data"), str)
                or result.get("mimeType") != "image/png"):
            return _tool_result("Bridge returned an invalid screenshot.",
                                is_error=True)
        content = [{"type": "image", "data": result["data"],
                    "mimeType": result["mimeType"]}]
        # main's named renders also say what was drawn (sheet, size, path).
        meta = {k: v for k, v in result.items()
                if k not in ("data", "mimeType")}
        if meta:
            content.append({"type": "text",
                            "text": json.dumps(meta, ensure_ascii=False)})
        return {"content": content}
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
        asked = (msg.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": (asked if asked in PROTOCOLS
                                else PROTOCOL),
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
