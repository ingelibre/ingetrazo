# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""AI Bridge plugin — let an AI coding agent drive the live document (MCP).

The realisation of invariant #5 (AI-native): the agent generates RECIPES of
actions over the deterministic engine, never raw meshes. Extensiones ▸
"AI Bridge (MCP)" toggles a localhost-only TCP server; the companion
``scripts/ingetrazo_mcp.py`` bridges it to Claude Code / Claude Desktop as
an MCP server. The same pattern as sketchup-mcp (a TCP server inside the
app + an MCP process outside), with three legs up on SketchUp's:

- ``run_python`` executes through the Python Console's transactional
  machinery: every AI action is ONE undo step, and a script that raises is
  rolled back whole — the agent can never leave the document half-mutated.
- ``screenshot`` renders the real viewport (``render_image``), closing the
  "the agent can't see what it built" gap: describe → build → LOOK → fix.
- The hermeticity guard stays in the loop: recipes that would commit a
  broken solid are refused by the engine itself.

Protocol (framed for the bridge, not for humans): newline-delimited JSON on
127.0.0.1:4763 (``INGETRAZO_AI_PORT`` overrides). Request
``{"id": n, "tool": name, "args": {...}}`` → reply ``{"id": n, "ok": bool,
"result": ... | "error": str}``. One client at a time; everything the tools
touch runs on the Qt MAIN thread (queued-signal relay to a bound method —
the documented PySide6 threading gotcha).
"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import tempfile
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

from core.history import SnapshotImport
from core.i18n import tr
from tools.base import Tool

DEFAULT_PORT = 4763


class _Bridge(QObject):
    """The in-app half: accepts one agent connection and executes its tool
    calls on the Qt main thread."""

    # Signal(object), NOT Signal(dict): a dict payload on a queued
    # connection may be marshalled into a QVariantMap — the slot then gets a
    # COPY, sets the copied Event, and the worker times out forever. object
    # passes the PyObject by reference. (Cost us a hunt; now documented.)
    _dispatch = Signal(object)

    def __init__(self, viewport) -> None:
        super().__init__(viewport)
        self._viewport = viewport
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._scope: dict = {"__name__": "__ai__"}
        self.port: int | None = None
        # Queued to a BOUND method of this main-thread QObject — connecting a
        # lambda would run the slot on the worker thread (CLAUDE.md gotcha).
        self._dispatch.connect(self._run_on_main, Qt.QueuedConnection)

    # ---- Lifecycle ----------------------------------------------------------
    def start(self) -> int:
        port = int(os.environ.get("INGETRAZO_AI_PORT", DEFAULT_PORT))
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        srv.settimeout(0.5)
        self._server = srv
        self.port = srv.getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve, name="ingetrazo-ai-bridge", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        self.port = None

    @property
    def running(self) -> bool:
        return self._server is not None

    # ---- Worker side ---------------------------------------------------------
    def _serve(self) -> None:
        srv = self._server
        while not self._stop.is_set() and srv is not None:
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(0.5)
                buf = b""
                while not self._stop.is_set():
                    try:
                        chunk = conn.recv(65536)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        reply = self._handle_line(line)
                        try:
                            conn.sendall(reply)
                        except OSError:
                            break

    def _handle_line(self, line: bytes) -> bytes:
        try:
            req = json.loads(line)
        except ValueError:
            return b'{"id": null, "ok": false, "error": "bad json"}\n'
        job = {"req": req, "done": threading.Event(), "reply": None}
        self._dispatch.emit(job)
        job["done"].wait(timeout=120.0)
        reply = job["reply"] or {"id": req.get("id"), "ok": False,
                                 "error": "timed out on the UI thread"}
        return (json.dumps(reply) + "\n").encode()

    # ---- Main-thread side ----------------------------------------------------
    def _run_on_main(self, job: dict) -> None:
        req = job["req"]
        tool = req.get("tool", "")
        args = req.get("args") or {}
        try:
            handler = getattr(self, f"_tool_{tool}", None)
            if handler is None:
                raise ValueError(f"unknown tool {tool!r}")
            result = handler(**args)
            job["reply"] = {"id": req.get("id"), "ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001 — reported to the agent
            job["reply"] = {"id": req.get("id"), "ok": False,
                            "error": f"{type(exc).__name__}: {exc}"}
        finally:
            job["done"].set()

    # ---- Tools ---------------------------------------------------------------
    def _refresh_scope(self) -> None:
        from PySide6.QtGui import QVector3D
        from core import bim
        from core.group import Group
        from core.mesh import Edge, Face, Mesh, Vertex
        vp = self._viewport
        self._scope.update(
            viewport=vp, scene=vp.scene, model=vp.scene, mesh=vp.scene.mesh,
            selection=vp.scene.selection, groups=vp.scene.groups,
            layers=vp.scene.layers, bim=bim, QVector3D=QVector3D, Mesh=Mesh,
            Group=Group, Vertex=Vertex, Edge=Edge, Face=Face)

    def _tool_run_python(self, code: str = "") -> dict:
        """Execute ``code`` exactly like the Python Console: one undoable
        step, rolled back whole on error, no undo entry if nothing changed."""
        self._refresh_scope()
        vp = self._viewport
        history = vp.history
        out_buf, err_buf = io.StringIO(), io.StringIO()

        def mutate(_scene) -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = out_buf, err_buf
            try:
                try:
                    compiled = compile(code, "<ai>", "eval")
                except SyntaxError:
                    compiled = None
                if compiled is None:
                    exec(compile(code, "<ai>", "exec"), self._scope)
                else:
                    result = eval(compiled, self._scope)
                    if result is not None:
                        self._scope["_"] = result
                        print(repr(result))
            except Exception:
                traceback.print_exc(file=err_buf)
                raise
            finally:
                sys.stdout, sys.stderr = old_out, old_err

        cmd = SnapshotImport(mutate)
        saved_redo = list(history.redo_stack)
        history.execute(cmd)
        error = history.last_error
        changed = True
        if error is None:
            # Same rule as the Python Console: an inspect-only run leaves no
            # undo entry behind.
            unchanged = (cmd.before == cmd.after
                         and not cmd.added_groups and not cmd.added_layers
                         and not cmd.added_views and not cmd.added_dims
                         and not cmd.added_texts)
            if (unchanged and history.undo_stack
                    and history.undo_stack[-1] is cmd):
                history.undo_stack.pop()
                history.redo_stack[:] = saved_redo
                changed = False
        else:
            changed = False
        vp.notify_scene_changed()
        return {"stdout": out_buf.getvalue(), "stderr": err_buf.getvalue(),
                "error": error, "changed": changed}

    def _tool_query_model(self) -> dict:
        vp = self._viewport
        scene = vp.scene
        lo, hi = scene.bounds()
        insts = sum(1 for g in scene.groups
                    if getattr(g, "xform", None) is not None)
        return {
            "faces": len(scene.mesh.faces),
            "edges": len(scene.mesh.edges),
            "groups": len(scene.groups) - insts,
            "component_instances": insts,
            "group_names": [g.name for g in scene.groups][:100],
            "materials": sorted(getattr(scene, "materials", {}) or {})[:100],
            "layers": [ly.name for ly in scene.layers],
            "dimensions": len(getattr(scene, "dimensions", []) or []),
            "section_planes": len(getattr(scene, "section_planes", []) or []),
            "selection": len(scene.selection),
            "bounds": (None if lo is None else
                       {"min": [lo.x(), lo.y(), lo.z()],
                        "max": [hi.x(), hi.y(), hi.z()]}),
        }

    def _tool_screenshot(self, width: int = 1024, height: int = 768) -> dict:
        width = max(64, min(int(width), 4096))
        height = max(64, min(int(height), 4096))
        image = self._viewport.render_image(width, height)
        out_dir = Path(tempfile.gettempdir()) / "ingetrazo-ai"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "viewport.png"
        image.save(str(out))
        return {"path": str(out), "width": width, "height": height}

    def _tool_undo(self) -> dict:
        ok = self._viewport.history.undo()
        self._viewport.update()
        return {"ok": bool(ok)}

    def _tool_redo(self) -> dict:
        ok = self._viewport.history.redo()
        self._viewport.update()
        return {"ok": bool(ok)}


class AIBridgeTool(Tool):
    """Extensions-menu entry: toggle the localhost bridge on/off."""
    name = "AI Bridge (MCP)"
    uses_snap = False

    def on_activate(self, viewport) -> None:
        window = viewport.window()
        bridge = getattr(window, "_ai_bridge", None)
        if bridge is None:
            bridge = _Bridge(viewport)
            window._ai_bridge = bridge
        if bridge.running:
            bridge.stop()
            viewport.flash_status(tr("AI bridge stopped"))
            return
        try:
            port = bridge.start()
        except OSError as exc:
            viewport.flash_status(tr(
                "AI bridge could not start: {err}", err=str(exc)))
            return
        viewport.flash_status(tr(
            "AI bridge listening on 127.0.0.1:{port} — connect Claude with "
            "scripts/ingetrazo_mcp.py", port=port), 8000)

    def on_deactivate(self, viewport) -> None:
        pass
