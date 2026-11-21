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

Protocol (framed for the bridge, not for humans): newline-delimited JSON on
127.0.0.1:4763 (``INGETRAZO_AI_PORT`` overrides). Request
``{"id": n, "tool": name, "args": {...}}`` → reply ``{"id": n, "ok": bool,
"result": ... | "error": str}``. One client at a time; everything the tools
touch runs on the Qt MAIN thread (queued-signal relay to a bound method —
the documented PySide6 threading gotcha).
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from core.i18n import tr
from views.fold_section import FoldSection, narrow
from views.headless import open_quietly

DEFAULT_PORT = 4763
#: QSettings key of the panel's «Allow the agent to save the document».
ALLOW_SAVE_KEY = "ai_bridge/allow_save"
_REFUSED = b'{"id": null, "ok": false, "error": "not a bridge request; closing"}\n'


class _NoDialogs(QObject):
    """While an agent's code runs, nobody is at the screen to answer a
    dialog it opens (#694): «Delete sheet» asks Yes/No, a sheet the
    document cannot lose says so in a box. ``exec()`` then waited on the UI
    thread for good — the agent got «timed out», the app looked hung, and
    the next call ran INSIDE that dialog's event loop, nested in the first
    call's undo step. Every dialog shown meanwhile is answered «Cancel» at
    once (as Escape would) and named in the reply, so the agent knows."""

    def __init__(self) -> None:
        super().__init__()
        self.refused: list[str] = []

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Show:
            from PySide6.QtWidgets import QDialog, QMessageBox
            if isinstance(obj, QDialog):
                text = obj.windowTitle()
                if isinstance(obj, QMessageBox) and obj.text():
                    text = f"{text}: {obj.text()}" if text else obj.text()
                self.refused.append(text or type(obj).__name__)
                # Not from inside the Show: exec() only enters its loop
                # after show() returns, and a reject before that is lost.
                QTimer.singleShot(0, obj, obj.reject)
        return False


class _Bridge(QObject):
    """The in-app half: accepts one agent connection and executes its tool
    calls on the Qt main thread."""

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
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._scope: dict = {"__name__": "__ai__"}
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

    # ---- Lifecycle ----------------------------------------------------------
    def start(self, port: int | None = None) -> int:
        """Listen on ``port`` (None: ``INGETRAZO_AI_PORT`` or the default;
        0: any free one — :attr:`port` says which). Raises OSError when it
        cannot."""
        if port is None:
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
                    if not self._drain(conn, buf):
                        break
                    buf = buf[buf.rfind(b"\n") + 1:]

    def _drain(self, conn, buf: bytes) -> bool:
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
            reply = self._handle_line(line)
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

    def _handle_line(self, line: bytes) -> bytes | None:
        """The reply to one request line, or None if it is not a request."""
        try:
            req = json.loads(line)
        except ValueError:
            return None
        if not isinstance(req, dict):
            return None
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
        QApplication.instance().installEventFilter(guard)
        try:
            handler = (getattr(self, f"_tool_{tool}", None)
                       or self._sheet_handler(tool))
            if handler is None:
                raise ValueError(f"unknown tool {tool!r}")
            result = handler(**args)
            if isinstance(result, dict):
                result.setdefault("document_revision",
                                  self._document_revision())
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
            self._busy = False
            job["done"].set()

    # ---- Tools ---------------------------------------------------------------
    def _tool_run_python(self, code: str = "") -> dict:
        """Execute ``code`` via the shared transactional executor (core.ai):
        one undoable step, whole-rollback on error, no undo entry when
        nothing changed."""
        from core.ai import run_transactional
        result = run_transactional(self._viewport, code, self._scope)
        if result.get("changed"):
            self._sync_composer()
        return result

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
        self._sync_composer()
        return {"ok": bool(ok)}

    def _tool_redo(self) -> dict:
        ok = self._viewport.history.redo()
        self._viewport.update()
        self._sync_composer()
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
        w = self._window()
        scene = self._viewport.scene
        path = getattr(w, "_current_path", None)
        dirty = getattr(w, "_doc_is_dirty", None)
        return {
            "path": str(path) if path is not None else None,
            "modified": bool(dirty(w._doc)) if callable(dirty) else None,
            "save_format": (w.save_format() if hasattr(w, "save_format")
                            else "auto"),
            "saving_allowed": self.saving_allowed(),
            "shutdown_allowed": bool(self.allow_shutdown),
            "sheets": [getattr(c, "name", "") for c in
                       getattr(scene, "compositions", []) or []],
            "views": [v.name for v in
                      getattr(scene, "saved_views", []) or []],
        }

    def _tool_open_document(self, path: str = "") -> dict:
        """Open ``path`` in place of the document in front, with no
        question asked (an auto-saved copy is left alone)."""
        p = Path(path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"no such file: {p}")
        if not open_quietly(self._window(), p):
            raise RuntimeError(f"could not open {p}")
        return self._tool_document_info()

    def _tool_save_document(self, path: str | None = None,
                            format: str | None = None) -> dict:  # noqa: A002
        if not self.saving_allowed():
            raise PermissionError(
                "saving over the bridge is off: start IngeTrazo with "
                "--allow-save, or tick «Allow the agent to save the "
                "document» in the AI tab")
        w = self._window()
        target = Path(path).expanduser() if path else \
            getattr(w, "_current_path", None)
        if target is None:
            raise ValueError("the document has never been saved: give a "
                             "path")
        if target.suffix.lower() != ".igz":
            raise ValueError(f"not an .igz path: {target}")
        return w.write_document(target, format or None)

    def _tool_export_pdf(self, path: str = "", sheets=None) -> dict:
        """Every sheet (or the named ones) into one PDF, as File ▸ Export
        all sheets (PDF) does."""
        if not path:
            raise ValueError("give the PDF path")
        out = Path(path).expanduser()
        scene = self._viewport.scene
        comps = list(getattr(scene, "compositions", []) or [])
        if sheets:
            wanted = [str(s) for s in sheets]
            comps = [c for c in comps if getattr(c, "name", "") in wanted]
            unknown = set(wanted) - {getattr(c, "name", "") for c in comps}
            if unknown:
                raise ValueError("no such sheet: " + ", ".join(sorted(unknown)))
        if not comps:
            raise ValueError("the document has no sheets")
        out.parent.mkdir(parents=True, exist_ok=True)
        troubled = self._window()._ensure_composer().export_all_pdf(
            str(out), comps)
        if not out.is_file():
            raise RuntimeError(f"the PDF was not written: {out}")
        return {"path": str(out), "sheets": len(comps),
                "views_not_rendered": list(troubled or [])}

    def _tool_export_view(self, view: str = "", path: str = "",
                          width: int = 1920, height: int = 1080) -> dict:
        """Scene ``view`` rendered to a PNG at ``path``. The camera and
        what the scene shows are put back afterwards, and a document that
        was saved stays saved."""
        if not path:
            raise ValueError("give the PNG path")
        from core.saved_views import SavedView, shown_state
        vp = self._viewport
        scene = vp.scene
        target = next((v for v in scene.saved_views if v.name == view), None)
        if target is None:
            raise ValueError(f"no scene named {view!r}; there are: "
                             + ", ".join(v.name for v in scene.saved_views))
        width = max(64, min(int(width), 8192))
        height = max(64, min(int(height), 8192))
        w = self._window()
        was_clean = (callable(getattr(w, "_doc_is_dirty", None))
                     and not w._doc_is_dirty(w._doc))
        before = SavedView.capture("__bridge_before__", scene, vp.camera)
        state = shown_state(scene)
        out = Path(path).expanduser()
        bumped = False
        try:
            target.apply(scene, vp.camera)
            if shown_state(scene) != state:
                # What the scene shows changed: the caches keyed on the
                # version rebuild — and again once it is put back.
                scene.version += 1
                bumped = True
            image = vp.render_image(width, height)
        finally:
            before.apply(scene, vp.camera)
            if bumped:
                scene.version += 1
            if was_clean:
                w._saved_version = scene.version
            vp.update()
        if image is None or image.isNull():
            raise RuntimeError("the view did not render (no OpenGL "
                               "context?)")
        out.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(out)):
            raise RuntimeError(f"could not write {out}")
        return {"path": str(out), "width": width, "height": height}

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

    # ---- Sheets and saved views (#1505) ---------------------------------------
    # One tool per operation of core.sheets_api.SheetsAPI. The writing ones
    # run as ONE undo step each (SnapshotImport tracks the sheets' content),
    # take an optional ``expected_revision`` and refresh the composer when
    # it exists — open or not; none of them needs the window shown.
    _SHEET_READS = {"list_sheets": "list", "get_sheet": "get",
                    "list_views": "list_views",
                    "list_sheet_folders": "list_folders",
                    "list_sheet_sets": "list_sets",
                    "get_sheet_set": "get_set"}
    _SHEET_WRITES = {
        "create_sheet": "create", "update_sheet": "update",
        "delete_sheet": "delete", "add_frame": "add_frame",
        "update_frame": "update_frame", "remove_frame": "remove_frame",
        "fit_frame": "fit", "set_title_block": "set_title_block",
        "add_text": "add_text", "update_text": "update_text",
        "create_view": "create_view", "update_view": "update_view",
        "delete_view": "delete_view",
        "create_sheet_set": "create_set", "update_sheet_set": "update_set",
        "delete_sheet_set": "delete_set",
    }

    def _sheets_api(self):
        from core.sheets_api import SheetsAPI
        vp = self._viewport
        return SheetsAPI(vp.scene, getattr(vp, "camera", None))

    def _document_revision(self) -> str:
        """A token that changes whenever the document does (a step done or
        undone, by an agent or the user) and not when it is only read: two
        clients see each other's edits as a changed revision."""
        history = getattr(self._viewport, "history", None)
        if history is None:
            return ""
        undo = getattr(history, "undo_stack", [])
        top = id(undo[-1]) if undo else 0
        return f"{len(undo)}-{top & 0xffffff:06x}"

    def _check_revision(self, expected) -> None:
        if expected and expected != self._document_revision():
            raise RuntimeError(
                f"the document changed since revision {expected} (now "
                f"{self._document_revision()}): read it again before "
                f"editing")

    def _sync_composer(self) -> None:
        composer = getattr(self._viewport.window(), "_composer", None)
        sync = getattr(composer, "sync_with_document", None)
        if sync is not None:
            try:
                sync()
            except Exception:  # noqa: BLE001 — the step is done; UI catches up
                import traceback
                traceback.print_exc()
        tabs = getattr(self._viewport.window(), "_refresh_sheet_tabs", None)
        if tabs is not None:
            tabs()

    #: Tool argument → SheetsAPI parameter, where the names differ.
    _ARG_RENAMES = {"get_sheet": {"sheet": "ref"},
                    "update_sheet": {"sheet": "ref"},
                    "delete_sheet": {"sheet": "ref"},
                    "update_view": {"view": "ref"},
                    "delete_view": {"view": "ref"},
                    "get_sheet_set": {"set": "ref"},
                    "update_sheet_set": {"set": "ref"},
                    "delete_sheet_set": {"set": "ref"}}

    def _sheet_handler(self, tool: str):
        renames = self._ARG_RENAMES.get(tool, {})

        def args(kw: dict) -> dict:
            return {renames.get(k, k): v for k, v in kw.items()}

        if tool in self._SHEET_READS:
            method = self._SHEET_READS[tool]

            def read(expected_revision=None, **kw):
                out = getattr(self._sheets_api(), method)(**args(kw))
                return out if isinstance(out, dict) else {tool[5:]: out}
            return read
        if tool in self._SHEET_WRITES:
            method = self._SHEET_WRITES[tool]
            return lambda expected_revision=None, **kw: self._sheet_step(
                method, expected_revision, args(kw))
        return None

    def _sheet_step(self, method: str, expected, kw: dict) -> dict:
        """``SheetsAPI.<method>(**kw)`` as one undoable step; rolled back
        whole when it raises."""
        from core.history import SnapshotImport
        self._check_revision(expected)
        vp = self._viewport
        api = self._sheets_api()
        out: dict = {}

        def mutate(_scene) -> None:
            out["result"] = getattr(api, method)(**kw)

        cmd = SnapshotImport(mutate)
        saved_redo = list(vp.history.redo_stack)
        vp.history.execute(cmd)
        error = vp.history.last_error
        if error is not None:
            raise RuntimeError("rolled back, the document is unchanged: "
                               + error.replace("SnapshotImport: ", ""))
        if not cmd.changed and vp.history.undo_stack \
                and vp.history.undo_stack[-1] is cmd:
            vp.history.undo_stack.pop()        # nothing to undo: no step
            vp.history.redo_stack[:] = saved_redo
        vp.notify_scene_changed()
        self._sync_composer()
        result = out.get("result")
        return {"result": result, "changed": bool(cmd.changed)}

    def _ensure_composer(self):
        """The project's composer — created hidden if it never opened."""
        ensure = getattr(self._viewport.window(), "_ensure_composer", None)
        if ensure is None:
            raise RuntimeError("this window has no sheet composer")
        return ensure()

    def _tool_render_sheet(self, sheet=0, dpi: int = 80,
                           sheet_set=None) -> dict:
        """One sheet as a PNG the client can look at (like screenshot);
        with ``sheet_set``, as that set prints it (#1519): its page number,
        count and index within the set."""
        api = self._sheets_api()
        comp = api.sheet(sheet)
        dpi = max(20, min(int(dpi), 300))
        composer = self._ensure_composer()
        if sheet_set:
            comps, name = composer._sheets_to_export(None, sheet_set)
            with composer.export_scope(comps, name):
                image = composer.render_sheet_image(comp, dpi)
        else:
            image = composer.render_sheet_image(comp, dpi)
        out_dir = Path(tempfile.gettempdir()) / "ingetrazo-ai"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "sheet.png"
        image.save(str(out))
        return {"path": str(out), "sheet": comp.name,
                "width": image.width(), "height": image.height(),
                "warnings": api.warnings(comp)}

    def _tool_export_sheets(self, path: str = "", sheets=None,
                            format: str = "pdf", dpi: int = 150,  # noqa: A002
                            sheet_set=None) -> dict:
        """PDF (one file, every sheet a page) or PNG (one per sheet), with
        the errors of each sheet — the window need not be open."""
        if not path:
            raise ValueError("path is required (an absolute file path)")
        api = self._sheets_api()
        if sheet_set:
            api.sheet_set(sheet_set)          # an unknown set: a clear error
            return self._ensure_composer().export_sheets(
                str(path), None, format, float(dpi), sheet_set=sheet_set)
        comps = None if sheets is None else [api.sheet(s) for s in sheets]
        return self._ensure_composer().export_sheets(str(path), comps, format,
                                              float(dpi))


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
    quoted = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    config = {"mcpServers": {"ingetrazo": {"command": cmd[0], "args": cmd[1:]}}}
    others = "\n".join(f"    {name}: {path}" for name, path in OTHER_CLIENTS)
    return (
        tr("The AI bridge is listening on 127.0.0.1:{port}. Connect ANY MCP "
           "client — MCP is an open standard: Claude Code, Claude Desktop, "
           "Cursor, VS Code, Windsurf, Antigravity CLI, Codex CLI…", port=port)
        + "\n\n"
        + tr("Claude Code (in a terminal):") + "\n"
        + f"    claude mcp add ingetrazo -- {quoted}\n\n"
        + tr("Antigravity CLI (Google; in a terminal):") + "\n"
        + f"    agy mcp add ingetrazo -- {quoted}\n\n"
        + tr("Claude Desktop: add this to {path} and restart Claude Desktop:",
             path=desktop_config_path(platform)) + "\n"
        + json.dumps(config, indent=2) + "\n\n"
        + tr("Other clients take the same block in their own file:") + "\n"
        + others + "\n\n"
        + tr("Keep IngeTrazo open with the bridge on; the tools answer only while it runs.")
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
        self._port = port
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
            port = getattr(self, "_port", DEFAULT_PORT)
            self._status.setText(tr(
                "Listening on 127.0.0.1:{port} — connect your MCP client "
                "with the lines below.", port=port))
            self._text.setPlainText(connect_instructions(port))
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
