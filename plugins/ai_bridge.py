# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""AI Bridge plugin — let an AI coding agent drive the live document (MCP).

The realisation of invariant #5 (AI-native): the agent generates RECIPES of
actions over the deterministic engine, never raw meshes. The «AI» tab of
the side tray (section "AI bridge (MCP)", or Extensions ▸ AI Bridge (MCP))
starts a localhost-only TCP server; the companion
``scripts/ingetrazo_mcp.py`` bridges it to Claude Code / Claude Desktop as
an MCP server. The usual pattern for app MCP bridges (a TCP server inside
the app + an MCP process outside), with three legs up:

- ``run_python`` executes through the Python Console's transactional
  machinery: every AI action is ONE undo step, and a script that raises is
  rolled back whole — the agent can never leave the document half-mutated.
- ``screenshot`` renders the real viewport (``render_image``), closing the
  "the agent can't see what it built" gap: describe → build → LOOK → fix.
- The hermeticity guard stays in the loop: recipes that would commit a
  broken solid are refused by the engine itself.
- Named tools with a schema (``views/bridge_tools.py``: scene info,
  layers, scenes, camera, selection, materials, sheets, open / save /
  import / export) for the clients that do not allow ``run_python``; and
  ``ingetrazo --server`` runs all of it without a window (main.py).

Protocol (framed for the bridge, not for humans): newline-delimited JSON on
an automatically assigned loopback port (``INGETRAZO_AI_PORT`` can pin it).
Each enabled window publishes its own discovery record. ``list_documents``
returns live metadata; other requests must carry both ``instance_id`` and
``document_id`` alongside ``id``, ``tool`` and ``args``. Everything the tools
touch runs on the Qt MAIN thread through a queued-signal relay.
"""
from __future__ import annotations

import base64
import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from PySide6.QtCore import (QBuffer, QCoreApplication, QEvent, QIODevice,
                            QObject, Qt, QTimer, Signal)
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from core import ai_discovery
from core.i18n import tr
from views.bridge_tools import NO_GL, BridgeTools, absolute, out_dir
from views.fold_section import FoldSection, narrow
from views.headless import DialogRefuser, open_quietly

DEFAULT_PORT = 0
#: QSettings key of the panel's «Allow the agent to save the document».
ALLOW_SAVE_KEY = "ai_bridge/allow_save"
_REFUSED = b'{"id": null, "ok": false, "error": "not a bridge request; closing"}\n'


#: While an agent's code runs, nobody is at the screen to answer a dialog it
#: opens (#694): «Delete sheet» asks Yes/No, a sheet the document cannot
#: lose says so in a box. ``exec()`` then waited on the UI thread for good —
#: the agent got «timed out», the app looked hung, and the next call ran
#: INSIDE that dialog's event loop, nested in the first call's undo step.
#: Every dialog shown meanwhile is answered «Cancel» at once (as Escape
#: would) and named in the reply. The same filter the window-less run keeps
#: on for good (views/headless.py) — one copy since PR #1494.
_NoDialogs = DialogRefuser


def _expand(path):
    """``~`` expanded, the rest as given (``absolute`` refuses a relative
    path rather than resolving it against wherever the app started)."""
    if isinstance(path, str) and path.startswith("~"):
        return str(Path(path).expanduser())
    return path


class _Bridge(BridgeTools, QObject):
    """The in-app half: accepts one agent connection and executes its tool
    calls on the Qt main thread. The named tools (scene info, layers,
    camera, files…) come from :class:`views.bridge_tools.BridgeTools` and
    go through the same request check as ``run_python`` (Marco, 19-11)."""

    # Signal(object), NOT Signal(dict): a dict payload on a queued
    # connection may be marshalled into a QVariantMap — the slot then gets a
    # COPY, sets the copied Event, and the worker times out forever. object
    # passes the PyObject by reference. (Cost us a hunt; now documented.)
    _dispatch = Signal(object)
    #: From the worker once a shutdown's reply is sent (see _after_reply).
    _shutdown_now = Signal()

    @property
    def _viewport(self):
        """The viewport of the project in front (projects in tabs, #1066):
        the one handed in at setup may be a tab in the back, or closed."""
        return self._live_viewport()

    def __init__(self, viewport) -> None:
        # The window's, not the viewport's: a project tab closed must not
        # take the bridge with it (#1066).
        super().__init__(viewport.window() or viewport)
        from views.documents import live_viewport
        self._live_viewport = live_viewport(viewport)
        self.instance_id = uuid.uuid4().hex
        self._server: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pending_job: dict | None = None
        self._registration: Path | None = None
        self._scope: dict = {"__name__": "__ai__"}
        self._scope_document_id: str | None = None
        self.port: int | None = None
        self._busy = False
        #: Whether ``save_document`` may write: ``--allow-save`` without a
        #: window, else the panel's checkbox (remembered, off by default).
        self.allow_save: bool | None = None
        #: Whether ``shutdown`` may end the app — set from the command
        #: line only (``--allow-shutdown``), never from the window.
        self.allow_shutdown = False
        #: Called by ``shutdown`` instead of quitting outright, so the
        #: window-less run can tell its exit apart (main._run_headless).
        self.on_shutdown = None
        # Queued to a BOUND method of this main-thread QObject — connecting a
        # lambda would run the slot on the worker thread (CLAUDE.md gotcha).
        self._dispatch.connect(self._run_on_main, Qt.QueuedConnection)
        self._shutdown_now.connect(self._finish_shutdown, Qt.QueuedConnection)
        self._shutdown_pending = False
        QCoreApplication.instance().aboutToQuit.connect(self.stop)

    # ---- Lifecycle ----------------------------------------------------------
    def start(self, port: int | None = None) -> int:
        """Listen on loopback, on ``port`` (``ingetrazo --server --port``),
        else ``INGETRAZO_AI_PORT``, else a free port (0, #892): each window
        publishes its own discovery record for the MCP client. 0 picks any
        free port — :attr:`port` says which. Raises OSError when it cannot."""
        if self.running:
            return self.port
        if port is None:
            port = int(os.environ.get("INGETRAZO_AI_PORT", DEFAULT_PORT))
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        registration = None
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", port))
            srv.listen(1)
            srv.settimeout(0.5)
            port = srv.getsockname()[1]
            registration = ai_discovery.register(self.instance_id, port)
            self._server = srv
            self.port = port
            self._registration = registration
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._serve, args=(srv, self._stop),
                name="ingetrazo-ai-bridge", daemon=True)
            self._thread.start()
        except Exception:
            self._stop.set()
            self._thread = None
            self._server = None
            self.port = None
            self._registration = None
            srv.close()
            if registration is not None:
                registration.unlink(missing_ok=True)
            raise
        return port

    @staticmethod
    def _close_socket(sock: socket.socket | None) -> None:
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def stop(self) -> None:
        self._stop.set()
        server, self._server = self._server, None
        self.port = None
        registration, self._registration = self._registration, None
        try:
            if registration is not None:
                registration.unlink(missing_ok=True)
        finally:
            with self._lock:
                connection = self._connection
                job = self._pending_job
                if job is not None:
                    job["reply"] = {"id": job["req"].get("id"), "ok": False,
                                    "error": "AI bridge stopped; enable it and call list_documents."}
                    job["done"].set()
            self._close_socket(connection)
            self._close_socket(server)
            thread, self._thread = self._thread, None
            if thread is not None and thread is not threading.current_thread():
                thread.join()

    @property
    def running(self) -> bool:
        return self._server is not None and not self._stop.is_set()

    # ---- Worker side ---------------------------------------------------------
    def _serve(self, srv: socket.socket, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(0.5)
                with self._lock:
                    if stop.is_set():
                        return
                    self._connection = conn
                try:
                    buf = b""
                    while not stop.is_set():
                        try:
                            chunk = conn.recv(65536)
                        except socket.timeout:
                            continue
                        except OSError:
                            break
                        if not chunk:
                            break
                        buf += chunk
                        if not self._drain(conn, buf, stop):
                            break
                        buf = buf[buf.rfind(b"\n") + 1:]
                finally:
                    with self._lock:
                        if self._connection is conn:
                            self._connection = None

    def _drain(self, conn, buf: bytes, stop: threading.Event) -> bool:
        """Answer every complete line in ``buf``. False when the connection
        must close: a line that is not a JSON request ends it, and nothing
        after it runs.

        Loopback is not a wall against the browser on this machine. A web page
        can ``fetch("http://127.0.0.1:4763", {method: "POST", mode: "no-cors",
        body})`` — a text/plain POST needs no CORS preflight, so the browser
        sends it and only hides the reply. Read line by line, its request line
        and headers failed as bad JSON and its body, a tool call, ran. The
        first line of any HTTP request is ``POST / HTTP/1.1``, so refusing the
        connection there stops the body from ever being read. The MCP client
        sends nothing but JSON lines and never meets this."""
        lines = buf.split(b"\n")[:-1]
        for line in lines:
            if not line.strip():
                continue
            reply = self._handle_line(line, stop)
            try:
                conn.sendall(reply if reply is not None else _REFUSED)
            except OSError:
                return self._after_reply(False)
            if reply is None:
                return False
            if not self._after_reply(True):
                return False
        return True

    def _after_reply(self, keep: bool) -> bool:
        """A shutdown asked for in the call just answered starts now, on
        the main thread; the connection closes. Else ``keep``."""
        if not self._shutdown_pending:
            return keep
        self._shutdown_pending = False
        self._shutdown_now.emit()
        return False

    def _handle_line(self, line: bytes, stop: threading.Event) -> bytes | None:
        """The reply to one request line, or None if it is not a request."""
        try:
            req = json.loads(line)
        except ValueError:
            return None
        if not isinstance(req, dict):
            return None
        job = {"req": req, "done": threading.Event(), "reply": None,
               "stop": stop}
        with self._lock:
            if stop.is_set():
                return None
            self._pending_job = job
        try:
            self._dispatch.emit(job)
            if not job["done"].wait(timeout=180.0):
                job["done"].set()  # An expired queued request must never run later.
            reply = job["reply"] or {"id": req.get("id"), "ok": False,
                                     "error": "timed out on the UI thread"}
        finally:
            with self._lock:
                if self._pending_job is job:
                    self._pending_job = None
        return (json.dumps(reply) + "\n").encode()

    # ---- Main-thread side ----------------------------------------------------
    def _run_on_main(self, job: dict) -> None:
        req = job["req"]
        if job["done"].is_set():
            return
        tool = req.get("tool", "")
        args = req.get("args") or {}
        if self._busy:
            # A call delivered by an event loop nested in the previous one
            # (something it ran is still waiting): never run inside it.
            job["reply"] = {"id": req.get("id"), "ok": False, "error":
                            "IngeTrazo is still running the previous call"}
            job["done"].set()
            return
        self._busy = True
        from PySide6.QtWidgets import QApplication
        guard = _NoDialogs()
        self._guard = guard          # the named tools read what it cancelled
        QApplication.instance().installEventFilter(guard)
        try:
            if (not self.running or job["stop"] is not self._stop
                    or job["stop"].is_set()):
                raise RuntimeError("AI bridge stopped; enable it and call list_documents.")
            if self._replacing_document():
                raise RuntimeError("Document replacement in progress; call list_documents again.")
            if ("instance_id" in req
                    and req["instance_id"] != self.instance_id):
                raise ValueError("Stale instance_id; call list_documents.")
            document_id = self._document_id()
            if tool != "list_documents":
                if req.get("instance_id") != self.instance_id:
                    raise ValueError("instance_id is required; call list_documents.")
                if req.get("document_id") != document_id:
                    raise ValueError("Missing or stale document_id; call list_documents.")
            handler = getattr(self, f"_tool_{tool}", None)
            if handler is None:
                raise ValueError(f"unknown tool {tool!r}")
            result = handler(**args)
            if guard.refused and isinstance(result, dict):
                result["dialogs_cancelled"] = list(guard.refused)
                result["stderr"] = (result.get("stderr") or "") + "".join(
                    f"A dialog nobody can answer over the bridge was "
                    f"cancelled: {t!r}\n" for t in guard.refused)
            job["reply"] = {"id": req.get("id"), "ok": True, "result": result}
        except Exception as exc:  # noqa: BLE001 — reported to the agent
            job["reply"] = {"id": req.get("id"), "ok": False,
                            "error": f"{type(exc).__name__}: {exc}"}
        finally:
            QApplication.instance().removeEventFilter(guard)
            self._guard = None
            self._busy = False
            job["done"].set()

    # ---- Tools ---------------------------------------------------------------
    def _replacing_document(self) -> bool:
        """A document is coming in: the window's open is running, or its
        viewport is held still for it (#892). The whole window is also held
        while the composer covers it (main, 19-11); that is no replacement,
        and the sheets are exactly what an agent may be working on."""
        window = self._viewport.window()
        if getattr(window, "_open_in_progress", False):
            return True
        return (not self._viewport.updatesEnabled()
                and not getattr(window, "_paint_held", False))

    def _document_id(self) -> str:
        document_id = f"{self.instance_id}:{self._viewport.scene.document_id}"
        if document_id != self._scope_document_id:
            self._scope = {"__name__": "__ai__"}
            self._scope_document_id = document_id
        return document_id

    def _tool_list_documents(self) -> dict:
        window = self._viewport.window()
        workspace = getattr(window, "_workspace", None)
        path = None if workspace is not None else getattr(window, "_current_path", None)
        if workspace is not None:
            name = workspace.title()
        elif path is not None:
            path = Path(path).resolve()
            name = path.name
        else:
            name = getattr(window, "_import_name", None) or tr("Untitled")
        return {"documents": [{
            "document_id": self._document_id(),
            "instance_id": self.instance_id,
            "pid": os.getpid(),
            "name": name,
            "path": str(path) if path is not None else None,
            "title": window.windowTitle(),
            "dirty": window._is_dirty(),
            "revision": self._viewport.scene.content_version,
        }]}

    def _tool_run_python(self, code: str = "") -> dict:
        """Execute ``code`` via the shared transactional executor (core.ai):
        one undoable step, whole-rollback on error, no undo entry when
        nothing changed."""
        from core.ai import run_transactional
        return run_transactional(self._viewport, code, self._scope)

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

    def _tool_undo(self) -> dict:
        ok = self._viewport.history.undo()
        self._viewport.update()
        return {"ok": bool(ok)}

    def _tool_redo(self) -> dict:
        ok = self._viewport.history.redo()
        self._viewport.update()
        return {"ok": bool(ok)}

    # ---- Document tools (headless automation) --------------------------------
    def _window(self):
        return self._viewport.window()

    def saving_allowed(self) -> bool:
        if self.allow_save is not None:
            return bool(self.allow_save)
        from PySide6.QtCore import QSettings
        return str(QSettings().value(ALLOW_SAVE_KEY, "0")) == "1"

    def _tool_document_info(self) -> dict:
        """What is open and what the agent may do with it. The model itself
        is ``query_model`` / ``get_scene_info``."""
        w = self._window()
        scene = self._viewport.scene
        path = getattr(w, "_current_path", None)
        return {
            # The target ids (#892): after open_document they are the new
            # document's, so the agent goes on without list_documents.
            "instance_id": self.instance_id,
            "document_id": self._document_id(),
            "path": str(path) if path is not None else None,
            "modified": bool(w._is_dirty()),
            "save_format": (w.save_format() if hasattr(w, "save_format")
                            else "auto"),
            "saving_allowed": self.saving_allowed(),
            "shutdown_allowed": bool(self.allow_shutdown),
            "sheets": [getattr(c, "name", "") for c in
                       getattr(scene, "compositions", []) or []],
            "views": [v.name for v in
                      getattr(scene, "saved_views", []) or []],
        }

    # Reconciled with the named tools (PR #1494 + n63-mcp, 19-11): one
    # tool per job, under the PR's name, with what the other side had more
    # — the refusal to drop unsaved work, the tab put in place of the one in
    # front, the dialogs a failure showed, the sheets by number or place.
    def _tool_open_document(self, path: str = "",
                            discard_changes: bool = False) -> dict:
        """Open ``path`` in place of the document in front, with no
        question asked (an auto-saved copy is left alone). Unsaved changes
        there are never dropped in silence: an error, unless
        ``discard_changes`` — no «save changes?» box nobody would answer."""
        src = absolute(_expand(path), must_exist=True)
        win = self._window()
        suffix = src.suffix.lower()
        known = (".igz", ".dae", ".skp", ".dxf", ".dwg",
                 *getattr(win, "file_openers", {}))
        if suffix not in known:
            raise ValueError(f"IngeTrazo does not open {suffix!r} files; "
                             "one of " + ", ".join(known)
                             + " (import_file takes more)")
        if win._is_dirty() and not discard_changes:
            current = getattr(win, "_current_path", None)
            raise RuntimeError(
                "the document in front has unsaved changes ("
                + (current.name if current else "untitled")
                + "): save it with save_document first, or pass "
                "discard_changes=true to drop them")
        previous = win._doc
        mark = self._mark()
        win.viewport.end_group_edit()
        if not open_quietly(win, src):
            raise self._failed(f"could not open {src}", mark)
        if previous is not win._doc and previous in win._documents:
            # In place of the one in front, not beside it: an agent that
            # opens ten files must not leave ten tabs behind.
            win.close_document(previous, ask=False)
        return self._tool_document_info()

    def _tool_save_document(self, path: str | None = None,
                            format: str | None = None) -> dict:  # noqa: A002
        """File ▸ Save — or, with ``path``, Save As (``.igz``) — in the
        format asked, else the one IngeTrazo was told to use. Only when the
        user allowed it."""
        if not self.saving_allowed():
            raise PermissionError(
                "saving over the bridge is off: start IngeTrazo with "
                "--allow-save, or tick «Allow the agent to save the "
                "document» in the AI tab")
        w = self._window()
        if path:
            target = absolute(_expand(path))
            if not target.parent.is_dir():
                raise FileNotFoundError(
                    f"the folder does not exist: {target.parent}")
        else:
            target = getattr(w, "_current_path", None)
        if target is None:
            raise ValueError("the document has never been saved: give a "
                             "path (an absolute .igz path)")
        if target.suffix.lower() != ".igz":
            raise ValueError(f"not an .igz path: {target} (a document is "
                             "saved as .igz; export_file writes the other "
                             "formats)")
        mark = self._mark()
        w._end_group_edits()
        reply = w.write_document(target, format or None)
        warned = self._cancelled(mark)
        if warned:
            reply["warnings"] = warned
        return reply

    def _tool_export_pdf(self, path: str = "", sheets=None,
                         format: str = "pdf",  # noqa: A002 — the tool's name
                         dpi: float = 150.0, sheet_set=None) -> dict:
        """Every sheet (or the given ones: name, title-block number or
        place) as File ▸ Export all sheets does: ``format="pdf"`` writes
        one PDF, the atlas; ``format="png"`` one PNG per sheet,
        ``<stem>-<nn>-<sheet>.png`` beside ``path`` (a ``.png`` name) or
        inside it (a folder), at ``dpi``. ``sheet_set`` (#1519) exports
        that set instead: its sheets with Print on, in its order, their
        pages numbered within it and ``{set}`` its name."""
        if not path:
            raise ValueError("give the path")
        fmt = str(format or "pdf").lower()
        if fmt not in ("pdf", "png"):
            raise ValueError(f"format must be 'pdf' or 'png', not {format!r}")
        out = absolute(_expand(path))
        scene = self._viewport.scene
        comps = list(getattr(scene, "compositions", []) or [])
        if not comps:
            raise ValueError("the document has no sheets")
        set_name = None
        if sheet_set:
            if sheets:
                raise ValueError("give sheets or sheet_set, not both")
            found = self._sheets_api().sheet_set(sheet_set)
            from core import sheet_sets as ss
            comps, set_name = ss.export_list(scene, found), found.name
            if not comps:
                raise ValueError(f"the set {found.name!r} has no sheet "
                                 f"that prints")
        elif sheets:
            if isinstance(sheets, (str, int)):
                sheets = [sheets]
            picked = []
            for ref in sheets:
                comp = self._sheet(ref)
                if comp not in picked:
                    picked.append(comp)
            # In the document's order, as the atlas prints them.
            comps = [c for c in comps if c in picked]
        composer = self._composer_for(comps)
        scope = composer.export_scope(
            comps if set_name is not None else None, set_name or "")
        with scope:
            if fmt == "png":
                reply = self._export_pngs(composer, comps, out, dpi)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                troubled = composer._paint_atlas_pdf(str(out), comps)
                if not out.is_file():
                    raise RuntimeError(f"the PDF was not written: {out}")
                reply = {"path": str(out), "sheets": len(comps),
                         "sheet_names": [c.name for c in comps],
                         "views_not_rendered": list(troubled or [])}
        if set_name is not None:
            reply["sheet_set"] = set_name
        return reply

    @staticmethod
    def _export_pngs(composer, comps, out: Path, dpi) -> dict:
        dpi = max(20.0, min(600.0, float(dpi)))
        if out.suffix and out.suffix.lower() != ".png":
            raise ValueError("a PNG export goes to a .png name or a folder")
        done = composer.export_sheet_files(comps, out, "png", dpi)
        return {"files": done["files"], "sheets": len(comps),
                "sheet_names": [c.name for c in comps], "dpi": dpi,
                "views_not_rendered": done["errors"]}

    def _tool_export_view(self, view: str = "", path: str | None = None,
                          width: int = 1920, height: int = 1080) -> dict:
        """Scene ``view`` rendered to a PNG (at ``path``, else the bridge's
        own folder). The camera and what the scene shows are put back
        afterwards, and a document that was saved stays saved."""
        from core.saved_views import SavedView, shown_state
        vp = self._viewport
        scene = vp.scene
        try:
            target = self._scene_view(view)
        except KeyError as exc:
            raise ValueError(exc.args[0]) from None
        if not self._has_gl():
            # Before the scene is put up: nothing to put back.
            raise RuntimeError("the view did not render (" + NO_GL + ")")
        width = max(64, min(int(width), 8192))
        height = max(64, min(int(height), 8192))
        out = absolute(_expand(path)) if path else out_dir() / "view.png"
        w = self._window()
        was_clean = not w._is_dirty()
        before = SavedView.capture("__bridge_before__", scene, vp.camera)
        state = shown_state(scene)
        bumped = False
        try:
            target.apply(scene, vp.camera)
            if shown_state(scene) != state:
                # What the scene shows changed: the caches keyed on the
                # version rebuild — and again once it is put back.
                scene.version += 1
                bumped = True
            image = self._render_view(width, height)
        finally:
            before.apply(scene, vp.camera)
            if bumped:
                scene.version += 1
            if was_clean:
                w._saved_version = scene.version
            vp.notify_scene_changed()
        out.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(out)):
            raise RuntimeError(f"could not write {out}")
        return {"path": str(out), "view": target.name,
                "width": width, "height": height}

    def _tool_shutdown(self, discard_changes: bool = False) -> dict:
        """End IngeTrazo — only when started with ``--allow-shutdown``.
        Refused with unsaved changes unless ``discard_changes``."""
        if not self.allow_shutdown:
            raise PermissionError(
                "shutdown over the bridge is off: start IngeTrazo with "
                "--allow-shutdown")
        w = self._window()
        dirty = getattr(w, "_doc_is_dirty", None)
        if not discard_changes and callable(dirty) and dirty(w._doc):
            raise RuntimeError(
                "the document has unsaved changes: save_document first, or "
                "call shutdown with discard_changes=true")
        # Not now: once this reply has gone out (see _drain), so the agent
        # hears that it worked before the connection drops.
        self._shutdown_pending = True
        return {"shutting_down": True}

    def _finish_shutdown(self) -> None:
        """Main thread, after the shutdown reply was sent."""
        self.stop()
        if self.on_shutdown is not None:
            self.on_shutdown()
        else:
            from PySide6.QtWidgets import QApplication
            QApplication.instance().exit(0)


def mcp_command(platform: str | None = None, frozen: bool | None = None,
                executable: str | None = None, root: Path | None = None,
                env: dict | None = None) -> list[str]:
    """The command an MCP client must run to reach this IngeTrazo — the
    packaged app carries the server, so nobody needs Python installed:
    ``ingetrazo-mcp.exe`` beside the app on Windows, ``<ingetrazo> --mcp``
    for the Linux/macOS packages, and the script itself from a checkout.

    The Linux packages need the command that is valid FROM THE HOST and
    OUTLIVES this run, not ``sys.executable``: an AppImage mounts itself
    under a fresh ``/tmp/.mount_*`` each launch (the path the dialog used
    to print died with the session), a Flatpak's executable lives inside
    the sandbox (``flatpak run <id> --mcp`` is the door), and a snap is
    reached through ``/snap/bin``. Marco found the gap setting Antigravity
    up for the tutorial (2026-09-21)."""
    from pathlib import PurePosixPath, PureWindowsPath
    platform = platform or sys.platform
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = executable or sys.executable
    env = os.environ if env is None else env
    windows = platform.startswith("win")
    PathOf = PureWindowsPath if windows else PurePosixPath   # host-agnostic
    if not windows:
        if env.get("APPIMAGE"):
            return [env["APPIMAGE"], "--mcp"]
        if env.get("FLATPAK_ID"):
            return ["flatpak", "run", env["FLATPAK_ID"], "--mcp"]
        if env.get("SNAP_NAME"):
            return [f"/snap/bin/{env['SNAP_NAME']}", "--mcp"]
    if frozen:
        exe = PathOf(executable)
        if windows:
            return [str(exe.with_name("ingetrazo-mcp.exe"))]
        return [str(exe), "--mcp"]
    root = PathOf(str(root or Path(__file__).resolve().parents[1]))
    python = "python" if windows else "python3"
    return [python, str(root / "scripts" / "ingetrazo_mcp.py")]


def desktop_config_path(platform: str | None = None) -> str:
    """Where Claude Desktop reads its MCP servers on this platform."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        return r"%APPDATA%\\Claude\\claude_desktop_config.json"
    if platform == "darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


#: Where the common MCP clients read a ``mcpServers`` block like the one the
#: dialog prints (the same JSON, or the equivalent, works in every one:
#: MCP is an open standard, not a Claude feature).
OTHER_CLIENTS = (
    ("Cursor", "~/.cursor/mcp.json"),
    ("VS Code (Copilot)", ".vscode/mcp.json  (key \"servers\")"),
    ("Windsurf", "~/.codeium/windsurf/mcp_config.json"),
    # Google retired Gemini CLI's free Google-account login on 2026-06-18;
    # its successor for individuals is Antigravity CLI (`agy`), which reads
    # this file (Marco hit the shutdown notice on 2026-09-21).
    ("Antigravity CLI (Google)", "~/.gemini/config/mcp_config.json"),
    ("Codex CLI", "~/.codex/config.toml  ([mcp_servers.ingetrazo])"),
)


def connect_instructions(port: int, platform: str | None = None, **kw) -> str:
    """Copy-and-paste text for the dialog the Extensions entry shows once
    the bridge is up: Claude Code's one-liner, the JSON every other MCP
    client takes, and where each of them reads it."""
    cmd = mcp_command(platform, **kw)
    env = kw.get("env")
    env = os.environ if env is None else env
    client_env = {}
    if env.get("INGETRAZO_AI_REGISTRY"):
        client_env["INGETRAZO_AI_REGISTRY"] = str(
            Path(env["INGETRAZO_AI_REGISTRY"]).expanduser().resolve())
    pinned_port = env.get("INGETRAZO_AI_PORT")
    if pinned_port and int(pinned_port) != 0:
        client_env["INGETRAZO_AI_HOST"] = env.get("INGETRAZO_AI_HOST", "127.0.0.1")
        client_env["INGETRAZO_AI_PORT"] = pinned_port
    windows = (platform or sys.platform).startswith("win")
    quote = (lambda value: subprocess.list2cmdline([value])) if windows else shlex.quote
    quoted = " ".join(quote(c) for c in cmd)
    env_options = "".join(
        f" --env {quote(f'{key}={value}')}" for key, value in client_env.items())
    server = {"command": cmd[0], "args": cmd[1:]}
    if client_env:
        server["env"] = client_env
    config = {"mcpServers": {"ingetrazo": server}}
    others = "\n".join(f"    {name}: {path}" for name, path in OTHER_CLIENTS)
    return (
        tr("The AI bridge is listening on 127.0.0.1:{port}. Connect ANY MCP "
           "client — MCP is an open standard: Claude Code, Claude Desktop, "
           "Cursor, VS Code, Windsurf, Antigravity CLI, Codex CLI…", port=port)
        + "\n\n"
        + tr("Claude Code (in a terminal):") + "\n"
        + f"    claude mcp add ingetrazo{env_options} -- {quoted}\n\n"
        + tr("Antigravity CLI (Google; in a terminal):") + "\n"
        + f"    agy mcp add ingetrazo{env_options} -- {quoted}\n\n"
        + tr("Claude Desktop: add this to {path} and restart Claude Desktop:",
             path=desktop_config_path(platform)) + "\n"
        + json.dumps(config, indent=2) + "\n\n"
        + tr("Other clients take the same block in their own file:") + "\n"
        + others + "\n\n"
        + tr("Keep IngeTrazo open with the bridge on. Call list_documents to discover "
             "enabled windows, then choose the document_id for every document tool.")
    )


def _bridge_of(viewport) -> _Bridge:
    window = viewport.window()
    bridge = getattr(window, "_ai_bridge", None)
    if bridge is None:
        bridge = _Bridge(viewport)
        window._ai_bridge = bridge
    return bridge


class BridgeSection(QWidget):
    """The bridge's part of the «AI» tab: on/off, where it listens, and
    the exact lines to paste into the MCP client — the user who reached
    this is rarely the one who knows them by heart."""

    @property
    def _viewport(self):
        """The viewport of the project in front (projects in tabs, #1066):
        the one handed in at setup may be a tab in the back, or closed."""
        return self._live_viewport()

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent)
        from views.documents import live_viewport
        self._live_viewport = live_viewport(viewport)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 4)
        self.section = FoldSection(tr("AI bridge (MCP)"), "ia/open_bridge",
                                   default_open=False)
        lay.addWidget(self.section)
        body = QVBoxLayout(self.section.body)
        self._status = QLabel()
        self._status.setWordWrap(True)
        body.addWidget(self._status)
        row = QHBoxLayout()
        self._toggle = QPushButton()
        self._toggle.clicked.connect(self.toggle)
        row.addWidget(self._toggle)
        self._copy = QPushButton(tr("Copy"))
        self._copy.setToolTip(tr("Copy the connection instructions"))
        self._copy.clicked.connect(self._on_copy)
        row.addWidget(self._copy)
        body.addLayout(row)
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QCheckBox
        self._allow_save = QCheckBox(tr("Allow the agent to save the "
                                        "document"))
        self._allow_save.setToolTip(tr(
            "Lets the agent write the open document to disk with its "
            "save_document tool (File ▸ Save, in the format chosen in "
            "Preferences). Off: it can change the model, never the file."))
        self._allow_save.setChecked(
            str(QSettings().value(ALLOW_SAVE_KEY, "0")) == "1")
        self._allow_save.toggled.connect(
            lambda on: QSettings().setValue(ALLOW_SAVE_KEY,
                                            "1" if on else "0"))
        body.addWidget(self._allow_save)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self._text.setMinimumHeight(140)
        body.addWidget(self._text)
        narrow(self._toggle, self._copy)
        self._refresh()

    @property
    def running(self) -> bool:
        bridge = getattr(self._viewport.window(), "_ai_bridge", None)
        return bridge is not None and bridge.running

    def start(self) -> bool:
        bridge = _bridge_of(self._viewport)
        if bridge.running:
            return True
        try:
            port = bridge.start()
        except OSError as exc:
            self._viewport.flash_status(tr(
                "AI bridge could not start: {err}", err=str(exc)))
            self._refresh(error=str(exc))
            return False
        self._viewport.flash_status(tr(
            "AI bridge listening on 127.0.0.1:{port}", port=port), 8000)
        self._refresh()
        return True

    def stop(self) -> None:
        bridge = getattr(self._viewport.window(), "_ai_bridge", None)
        if bridge is not None and bridge.running:
            bridge.stop()
            self._viewport.flash_status(tr("AI bridge stopped"))
        self._refresh()

    def toggle(self) -> None:
        if self.running:
            self.stop()
        else:
            self.start()

    def _refresh(self, error: str | None = None) -> None:
        on = self.running
        self._toggle.setText(tr("Stop bridge") if on else tr("Start bridge"))
        self._copy.setVisible(on)
        self._text.setVisible(on)
        if on:
            bridge = self._viewport.window()._ai_bridge
            port = bridge.port
            self._status.setText(tr(
                "Listening on 127.0.0.1:{port} — connect your MCP client "
                "with the lines below.", port=port))
            # Use the published location, not a relative override interpreted
            # against a later working directory (or the MCP client's cwd).
            env = dict(os.environ,
                       INGETRAZO_AI_REGISTRY=str(bridge._registration.parent))
            self._text.setPlainText(connect_instructions(port, env=env))
        elif error:
            self._status.setText(tr(
                "AI bridge could not start: {err}", err=error))
        else:
            self._status.setText(tr(
                "Off. Start it to let an AI agent (Claude, Cursor, "
                "Antigravity…) model in this document over MCP."))

    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._text.toPlainText())
        self._viewport.flash_status(tr("Copied"))


def setup(app) -> None:
    """The bridge joins the assistant in the side tray's «AI» tab; the
    Extensions entry opens that section and starts the bridge."""
    section = BridgeSection(app.viewport)
    dock = app.add_panel(tr("AI"), section, panel="ai", icon="panel_ai")
    app.window._ai_bridge_section = section

    def summon() -> None:
        app.show_panel(dock)
        section.section.set_open(True)
        section.start()

    app.add_menu_action(tr("AI Bridge (MCP)"), summon, tip=tr(
        "Start the local bridge through which an AI agent (MCP) drives "
        "the open document."))
