# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood (OpenSKP) — IngeTrazo plugin contribution.
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Python Console plugin — a live REPL over the open document.

The classic scripting console: inspect the model, script geometry,
prototype the next plugin — against the running application, no restart.

What makes this one a good citizen of IngeTrazo (and where it differs from
the original contribution, PR #3):

- **Every execution runs as a Command** (:class:`core.history.SnapshotImport`
  via ``viewport.history.execute``): geometry a script creates is undoable
  with Ctrl+Z, marks the document dirty (so closing warns about unsaved
  work), and repaints immediately — the version bump the raw ``exec`` never
  produced. A script that raises is **rolled back whole**, not left half
  applied. Executions that only inspect (``print(len(mesh.faces))``) are
  detected and leave no undo entry behind.
- The scope's ``scene``/``mesh``/``selection``/``groups``/``layers`` are
  re-bound on every run, so they always point at the CURRENT document —
  not the one that happened to be open when the console was first shown.
- One console per window (re-activating raises it), monospace from the
  system (no hardcoded Consolas), output preserves indentation.

Undo covers what the snapshot covers: mesh mutations plus added groups,
layers, saved views, dimensions and text labels. Exotic state a script
touches beyond that (camera, styles, files on disk) is its own business.
"""
from __future__ import annotations

import io
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from core.history import SnapshotImport
from core.i18n import tr
from views.filedialogs import file_dialogs
from tools.base import Tool


#: The console's colours by ROLE, for each theme: VS Code's Dark+ and
#: Light+ (issue #92, @xyont: the light theme left the console black).
_PALETTES = {
    "dark": {"bg": "#1e1e1e", "fg": "#d4d4d4", "border": "#333333",
             "input_bg": "#252526", "input_fg": "#f1f1f1",
             "input_border": "#3c3c3c",
             "out": "#d4d4d4", "title": "#569cd6", "muted": "#808080",
             "help": "#ce9178", "error": "#f44747", "echo": "#4ec9b0",
             "run": "#dcdcaa"},
    "light": {"bg": "#ffffff", "fg": "#1f1f1f", "border": "#c8ccd2",
              "input_bg": "#f5f6f8", "input_fg": "#1f1f1f",
              "input_border": "#c8ccd2",
              "out": "#1f1f1f", "title": "#0451a5", "muted": "#6a737d",
              "help": "#a31515", "error": "#cd3131", "echo": "#267f99",
              "run": "#795e26"},
}


def _palette() -> dict:
    """The colours for the theme in force (the app palette's window)."""
    from PySide6.QtGui import QGuiApplication, QPalette
    app = QGuiApplication.instance()
    dark = (app is None
            or app.palette().color(QPalette.Window).lightness() < 128)
    return _PALETTES["dark" if dark else "light"]


class PythonConsoleDialog(QDialog):
    """Interactive Python REPL over the live document."""

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent or viewport.window())
        self._viewport = viewport
        self._history: list[str] = []
        self._history_idx = 0
        self._scope: dict = {"__name__": "__console__"}
        #: What the output shows, as (text, role): repainted in the other
        #: palette when the theme changes with the console open.
        self._lines: list[tuple[str, str]] = []

        self.setWindowTitle(tr("Python Console") + " — IngeTrazo")
        self.setMinimumSize(640, 480)
        self.resize(720, 540)

        self._build_ui()
        self._print_welcome()

    # ---- Layout ------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(QLabel(tr("Python Console")))
        header.addStretch()
        help_btn = QPushButton(tr("API help"))
        help_btn.clicked.connect(self._print_help)
        header.addWidget(help_btn)
        run_file_btn = QPushButton(tr("Run script file…"))
        run_file_btn.clicked.connect(self._on_run_script_file)
        header.addWidget(run_file_btn)
        clear_btn = QPushButton(tr("Clear"))
        clear_btn.clicked.connect(self._on_clear)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(10)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(mono)
        self._prompt = None
        layout.addWidget(self._output, stretch=1)

        row = QHBoxLayout()
        prompt = QLabel(">>>")
        prompt.setFont(mono)
        self._prompt = prompt
        row.addWidget(prompt)
        self._input = QLineEdit()
        self._input.setFont(mono)

        self._input.setPlaceholderText(
            tr("Python code — Enter runs it, Up/Down browse history"))
        self._input.returnPressed.connect(self._on_execute)
        self._input.installEventFilter(self)
        row.addWidget(self._input, stretch=1)
        run_btn = QPushButton(tr("Run"))
        run_btn.clicked.connect(self._on_execute)
        row.addWidget(run_btn)
        layout.addLayout(row)
        self._apply_colors()

    def _apply_colors(self) -> None:
        """The panes in the theme's palette, and the text already shown."""
        c = _palette()
        self._output.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {c['bg']}; "
            f"color: {c['fg']}; border: 1px solid {c['border']}; "
            "border-radius: 4px; padding: 6px; }")
        self._prompt.setStyleSheet(f"color: {c['echo']};")
        self._input.setStyleSheet(
            f"QLineEdit {{ background-color: {c['input_bg']}; "
            f"color: {c['input_fg']}; border: 1px solid {c['input_border']}; "
            "border-radius: 4px; padding: 5px; }")
        self._output.clear()
        for text, role in self._lines:
            self._write(text, c[role])

    def changeEvent(self, event) -> None:
        """Preferences ▸ Theme (or the desktop's scheme) changed."""
        super().changeEvent(event)
        if (event.type() == event.Type.PaletteChange
                and getattr(self, "_colors_for", None) is not _palette()):
            self._colors_for = _palette()
            self._apply_colors()

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Up:
                self._navigate_history(-1)
                return True
            if event.key() == Qt.Key_Down:
                self._navigate_history(1)
                return True
        return super().eventFilter(obj, event)

    def _navigate_history(self, direction: int) -> None:
        if not self._history:
            return
        self._history_idx = max(
            0, min(self._history_idx + direction, len(self._history)))
        if self._history_idx == len(self._history):
            self._input.clear()
        else:
            self._input.setText(self._history[self._history_idx])

    # ---- Output ------------------------------------------------------------
    def _append_text(self, text: str, role: str = "out") -> None:
        self._lines.append((text, role))
        self._write(text, _palette()[role])

    def _write(self, text: str, color_hex: str) -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._output.setTextCursor(cursor)
        escaped = (text.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
        # pre-wrap: tracebacks and aligned output keep their indentation.
        self._output.appendHtml(
            f'<span style="color:{color_hex}; white-space:pre-wrap;">'
            f'{escaped}</span>')
        self._output.ensureCursorVisible()

    def _print_welcome(self) -> None:
        self._append_text("IngeTrazo — " + tr("Python Console"), "title")
        self._append_text(
            tr("Live objects: scene, mesh, viewport, window, selection, "
               "groups, layers. Changes are undoable (Ctrl+Z)."), "muted")
        self._append_text("", "muted")

    def _print_help(self) -> None:
        self._append_text(
            "=== API ===\n\n"
            "scene / model   core.scene.Scene — the document\n"
            "mesh            the ACTIVE mesh (the open group's, inside one)\n"
            "viewport        the 3D view;  window   the MainWindow\n"
            "selection       set of selected entities;  groups / layers\n"
            "bim             core.bim — tag_faces(), collect_objects(), ...\n"
            "QVector3D, Mesh, Group, Vertex, Edge, Face   the CAD classes\n\n"
            "# count entities\n"
            "print(len(mesh.vertices), len(mesh.faces))\n\n"
            "# draw a slab and tag it (undoable as ONE step)\n"
            "pts = [QVector3D(0,0,0), QVector3D(5,0,0),\n"
            "       QVector3D(5,4,0), QVector3D(0,4,0)]\n"
            "f = mesh.add_face(pts)\n"
            "bim.tag_faces([f], 'IfcSlab', 'Losa 1', bim.next_object_id(scene))\n\n"
            "# paint the selection red (floats 0-1, the Paint idiom)\n"
            "for face in [e for e in selection if hasattr(e, 'loop')]:\n"
            "    face.attrs['color'] = (0.8, 0.1, 0.1)\n",
            "help")

    # ---- Execution ---------------------------------------------------------
    def _refresh_scope(self) -> None:
        """Re-bind the live objects: always the CURRENT document, not the one
        open when the console appeared (documents change under New/Open)."""
        from PySide6.QtGui import QVector3D
        from PySide6.QtWidgets import QApplication
        from core import bim
        from core.group import Group
        from core.mesh import Edge, Face, Mesh, Vertex
        from core.scene import Scene

        vp = self._viewport
        self._scope.update(
            app=QApplication.instance(), window=vp.window(), viewport=vp,
            scene=vp.scene, model=vp.scene, mesh=vp.scene.mesh,
            selection=vp.scene.selection, groups=vp.scene.groups,
            layers=vp.scene.layers, bim=bim, console=self,
            QVector3D=QVector3D, Mesh=Mesh, Group=Group, Scene=Scene,
            Vertex=Vertex, Edge=Edge, Face=Face)

    def _run_code(self, code: str, label: str) -> None:
        """Execute ``code`` as one undoable command against the document.

        The SnapshotImport wrapper gives us, for free: rollback when the code
        raises (no half-built geometry), Ctrl+Z when it succeeds, the dirty
        flag, and the version bump the viewport's VBO rebuild keys on. A run
        that changed nothing is popped back off the undo stack (and the redo
        stack it cleared is restored), so inspecting never eats an undo step.
        """
        self._refresh_scope()
        vp = self._viewport
        history = vp.history
        out_buf, err_buf = io.StringIO(), io.StringIO()

        def mutate(_scene) -> None:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = out_buf, err_buf
            try:
                # Compile-as-expression is probed OUTSIDE the try that runs
                # the code: running exec inside the `except SyntaxError`
                # handler would chain that internal, irrelevant SyntaxError
                # onto every error a multi-line script raises ("During
                # handling of the above exception...") — caught on the first
                # dogfooding screenshot.
                try:
                    compiled = compile(code, label, "eval")
                except SyntaxError:
                    compiled = None
                if compiled is None:
                    exec(compile(code, label, "exec"), self._scope)
                else:
                    result = eval(compiled, self._scope)
                    if result is not None:
                        self._scope["_"] = result
                        print(repr(result))
            except Exception:
                traceback.print_exc(file=err_buf)
                raise            # history rolls the document back whole
            finally:
                sys.stdout, sys.stderr = old_out, old_err

        cmd = SnapshotImport(mutate)
        saved_redo = list(history.redo_stack)
        history.execute(cmd)

        if history.last_error is None:
            unchanged = (cmd.before == cmd.after
                         and not cmd.added_groups and not cmd.added_layers
                         and not cmd.added_views and not cmd.added_dims
                         and not cmd.added_texts)
            if (unchanged and history.undo_stack
                    and history.undo_stack[-1] is cmd):
                history.undo_stack.pop()
                history.redo_stack[:] = saved_redo

        vp.notify_scene_changed()

        if out := out_buf.getvalue():
            self._append_text(out.rstrip(), "out")
        if err := err_buf.getvalue():
            self._append_text(err.rstrip(), "error")
            if history.last_error is not None:
                self._append_text(
                    tr("(rolled back — the document is unchanged)"),
                    "muted")

    def _on_execute(self) -> None:
        code = self._input.text().strip()
        if not code:
            return
        self._input.clear()
        self._history.append(code)
        self._history_idx = len(self._history)
        self._append_text(f">>> {code}", "echo")
        self._run_code(code, "<console>")

    def _on_run_script_file(self) -> None:
        path, _f = file_dialogs.getOpenFileName(
            self, tr("Run Python script"), "",
            tr("Python files (*.py);;All files (*)"))
        if not path:
            return
        p = Path(path)
        self._append_text(f"— {tr('running {name}', name=p.name)}", "run")
        try:
            source = p.read_text(encoding="utf-8")
        except OSError as exc:
            self._append_text(str(exc), "error")
            return
        self._scope["__file__"] = str(p.resolve())
        self._run_code(source, str(p))

    def _on_clear(self) -> None:
        self._output.clear()
        self._lines.clear()
        self._print_welcome()


class PythonConsoleTool(Tool):
    """Extensions-menu entry that opens (or raises) the console."""
    name = "Python Console"
    shortcut = "Ctrl+Shift+P"
    description = (
        "Open a Python prompt over the open document, to inspect it "
        "or script it.")
    uses_snap = False

    def on_activate(self, viewport) -> None:
        window = viewport.window()
        dialog = getattr(window, "_python_console", None)
        if dialog is None or not dialog.isVisible():
            dialog = PythonConsoleDialog(viewport, parent=window)
            window._python_console = dialog
            dialog.show()
        else:
            dialog.raise_()
            dialog.activateWindow()

    def on_deactivate(self, viewport) -> None:
        pass
