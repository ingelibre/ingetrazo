# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ahsan Mehmood (OpenSKP) — IngeTrazo plugin contribution.
"""Python Console plugin — interactive REPL console for model inspection and automation.

Provides a live Python console window (SketchUp Ruby Console equivalent) allowing
developers and users to inspect, script, and programmatically manipulate 3D models.

Usage: Select **Extensions → Python Console** from the menu or press ``Ctrl+Shift+P``.
"""
from __future__ import annotations

import io
import sys
import traceback
from pathlib import Path

from tools.base import Tool

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PythonConsoleDialog(QDialog):
    """Interactive Python REPL console dialog."""

    def __init__(self, viewport, parent=None) -> None:
        super().__init__(parent or viewport.window())
        self._viewport = viewport
        self._history: list[str] = []
        self._history_idx = -1

        self.setWindowTitle("🐍 Python Console — IngeTrazo")
        self.setMinimumSize(640, 480)
        self.resize(720, 540)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        self._build_ui()
        self._init_context()
        self._print_welcome()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Header bar
        header_layout = QHBoxLayout()
        title_label = QLabel("🐍 IngeTrazo Interactive Python REPL")
        title_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        help_btn = QPushButton("❓ API Help")
        help_btn.setToolTip("Show available variables and code snippets")
        help_btn.clicked.connect(self._print_help)
        header_layout.addWidget(help_btn)

        run_file_btn = QPushButton("📁 Run Script File...")
        run_file_btn.setToolTip("Execute a .py script file live in the console")
        run_file_btn.clicked.connect(self._on_run_script_file)
        header_layout.addWidget(run_file_btn)

        clear_btn = QPushButton("🧹 Clear")
        clear_btn.clicked.connect(self._on_clear)
        header_layout.addWidget(clear_btn)

        layout.addLayout(header_layout)

        # Output console (monospaced)
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        mono_font = QFont("Consolas", 10)
        mono_font.setStyleHint(QFont.Monospace)
        self._output.setFont(mono_font)
        self._output.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4; "
            "border: 1px solid #333333; border-radius: 4px; padding: 6px; }"
        )
        layout.addWidget(self._output, stretch=1)

        # Input row
        input_layout = QHBoxLayout()
        input_layout.setSpacing(6)

        prompt_label = QLabel(">>>")
        prompt_label.setFont(QFont("Consolas", 11, QFont.Bold))
        prompt_label.setStyleSheet("color: #4ec9b0;")
        input_layout.addWidget(prompt_label)

        self._input = QLineEdit()
        self._input.setFont(mono_font)
        self._input.setStyleSheet(
            "QLineEdit { background-color: #252526; color: #f1f1f1; "
            "border: 1px solid #3c3c3c; border-radius: 4px; padding: 5px; }"
        )
        self._input.setPlaceholderText("Type Python code here and press Enter (or Up/Down for history)...")
        self._input.returnPressed.connect(self._on_execute)
        input_layout.addWidget(self._input, stretch=1)

        exec_btn = QPushButton("Run")
        exec_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 5px 15px; }")
        exec_btn.clicked.connect(self._on_execute)
        input_layout.addWidget(exec_btn)

        layout.addLayout(input_layout)

        # Key event filter for command history (Up/Down)
        self._input.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == event.Type.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                self._navigate_history(-1)
                return True
            elif key == Qt.Key_Down:
                self._navigate_history(1)
                return True
        return super().eventFilter(obj, event)

    def _navigate_history(self, direction: int) -> None:
        if not self._history:
            return
        self._history_idx += direction
        if self._history_idx < 0:
            self._history_idx = 0
        elif self._history_idx >= len(self._history):
            self._history_idx = len(self._history)
            self._input.clear()
            return
        self._input.setText(self._history[self._history_idx])

    def _init_context(self) -> None:
        """Initialize the execution scope with live IngeTrazo objects."""
        from PySide6.QtGui import QVector3D
        from core.mesh import Mesh, Vertex, Edge, Face
        from core.group import Group
        from core.scene import Scene

        win = self._viewport.window()
        scene = self._viewport.scene

        self._scope = {
            "app": QApplication.instance(),
            "window": win,
            "viewport": self._viewport,
            "scene": scene,
            "model": scene,
            "mesh": scene.mesh,
            "selection": scene.selection,
            "groups": scene.groups,
            "layers": scene.layers,
            "materials": getattr(scene, "materials", None),
            # Classes
            "QVector3D": QVector3D,
            "Mesh": Mesh,
            "Group": Group,
            "Scene": Scene,
            "Vertex": Vertex,
            "Edge": Edge,
            "Face": Face,
            "console": self,
        }

    def _print_welcome(self) -> None:
        self._append_text("IngeTrazo Python Console v0.1", "#569cd6")
        self._append_text(
            "Live variables: `scene` (or `model`), `mesh`, `viewport`, `window`, `selection`, `groups`, `layers`.",
            "#808080"
        )
        self._append_text("Type Python expressions and press Enter. Click '❓ API Help' for code snippets.\n", "#808080")

    def _print_help(self) -> None:
        help_text = (
            "=== IngeTrazo Python Console API Quick Reference ===\n\n"
            "Live Scope Objects:\n"
            "  scene      - Active Scene container\n"
            "  mesh       - Shared topology Mesh (scene.mesh)\n"
            "  viewport   - 3D OpenGL Viewport widget\n"
            "  window     - MainWindow instance\n"
            "  selection  - Active selected entities set\n"
            "  groups     - List of scene Group objects\n"
            "  layers     - List of scene Layer objects\n\n"
            "Common Snippets:\n"
            "  # 1. Print mesh vertex/face counts:\n"
            "  print(len(mesh.vertices), len(mesh.faces))\n\n"
            "  # 2. Add a 3D triangle face:\n"
            "  pts = [QVector3D(0,0,0), QVector3D(5,0,0), QVector3D(2.5,4,0)]\n"
            "  mesh.add_face(pts)\n"
            "  viewport.update()\n\n"
            "  # 3. Inspect selection:\n"
            "  print(selection)\n\n"
            "  # 4. Clear scene selection:\n"
            "  selection.clear()\n"
            "  viewport.update()\n"
        )
        self._append_text(help_text, "#ce9178")

    def _append_text(self, text: str, color_hex: str = "#d4d4d4") -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._output.setTextCursor(cursor)
        # HTML formatting for color styling
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        self._output.insertHtml(f'<span style="color: {color_hex}; font-family: Consolas;">{escaped}</span><br>')
        self._output.ensureCursorVisible()

    def _on_execute(self) -> None:
        code = self._input.text().strip()
        if not code:
            return

        self._input.clear()
        self._history.append(code)
        self._history_idx = len(self._history)

        self._append_text(f">>> {code}", "#4ec9b0")

        # Capture stdout & stderr during execution
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout_buf, stderr_buf

        try:
            # Try evaluating as expression first (e.g. `mesh.vertices`)
            try:
                compiled = compile(code, "<console>", "eval")
                result = eval(compiled, self._scope)
                if result is not None:
                    print(repr(result))
            except SyntaxError:
                # Execute as statement/block
                exec(code, self._scope)

            # Trigger viewport redraw if scene version changed
            self._viewport.update()

        except Exception:
            traceback.print_exc()

        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

        out = stdout_buf.getvalue()
        err = stderr_buf.getvalue()

        if out:
            self._append_text(out.rstrip(), "#d4d4d4")
        if err:
            self._append_text(err.rstrip(), "#f44747")

    def _on_run_script_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Run Python Script", "", "Python Files (*.py);;All Files (*)"
        )
        if not file_path:
            return

        p = Path(file_path)
        self._append_text(f"▶ Executing script: {p.name}", "#dcdcaa")
        try:
            script_code = p.read_text(encoding="utf-8")
            old_stdout, old_stderr = sys.stdout, sys.stderr
            stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
            sys.stdout, sys.stderr = stdout_buf, stderr_buf

            try:
                exec(script_code, self._scope)
                self._viewport.update()
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr

            out = stdout_buf.getvalue()
            err = stderr_buf.getvalue()

            if out:
                self._append_text(out.rstrip(), "#d4d4d4")
            if err:
                self._append_text(err.rstrip(), "#f44747")
            self._append_text(f"✓ Script executed successfully.", "#6a9955")

        except Exception as e:
            self._append_text(f"✖ Error running script: {e}", "#f44747")

    def _on_clear(self) -> None:
        self._output.clear()
        self._print_welcome()


class PythonConsoleTool(Tool):
    """Tool registration for Python Console extension."""
    name = "Python Console"
    shortcut = "Ctrl+Shift+P"
    uses_snap = False

    def on_activate(self, viewport) -> None:
        dialog = PythonConsoleDialog(viewport, parent=viewport.window())
        dialog.show()

    def on_deactivate(self, viewport) -> None:
        pass
