"""Scale… — a modal with the X, Y, Z scale of one group or component,
edited in place the way Blender's N panel does."""
from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QPushButton,
                               QVBoxLayout)

from core.group_scale import group_scale, scale_command
from core.i18n import tr


def _fmt(value: float) -> str:
    return f"{value:.6g}"


class _Field(QLineEdit):
    """A line edit that leaves Ctrl+Z / Ctrl+Y to the dialog's shortcuts
    (the model's history) instead of undoing its own text."""

    def event(self, e) -> bool:
        if e.type() == QEvent.ShortcutOverride and (
                e.matches(QKeySequence.Undo) or e.matches(QKeySequence.Redo)):
            e.ignore()
            return True
        return super().event(e)


class ScaleDialog(QDialog):
    def __init__(self, window, group) -> None:
        super().__init__(window)
        self._window = window
        self._group = group
        self.setWindowTitle(tr("Scale"))
        self.setModal(True)
        form = QFormLayout()
        self.fields: list[QLineEdit] = []
        for axis in "XYZ":
            edit = _Field()
            edit.editingFinished.connect(self._apply)
            form.addRow(axis, edit)
            self.fields.append(edit)
        self.reset_button = QPushButton(tr("Reset scale"))
        self.reset_button.clicked.connect(self._reset)
        self.close_button = QPushButton(tr("Close"))
        self.close_button.clicked.connect(self.accept)
        # Enter belongs to the fields, not to a default button.
        for b in (self.reset_button, self.close_button):
            b.setAutoDefault(False)
            b.setDefault(False)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.close_button)
        for seq, step in ((QKeySequence.Undo, "undo"),
                          (QKeySequence.Redo, "redo"),
                          (QKeySequence("Ctrl+Shift+Z"), "redo")):
            QShortcut(seq, self, lambda s=step: self._history(s))
        self._refresh()

    def _history(self, step: str) -> None:
        vp = self._window.viewport
        getattr(vp.history, step)()
        vp.update()
        self._refresh()

    def _refresh(self) -> None:
        for edit, value in zip(self.fields, group_scale(self._group)):
            edit.setText(_fmt(value))

    def _typed(self):
        try:
            return tuple(float(e.text().replace(",", ".").strip())
                         for e in self.fields)
        except ValueError:
            return None

    def _set(self, target) -> None:
        cmd = scale_command(self._group, target) if target else None
        if cmd is not None:
            vp = self._window.viewport
            vp.history.execute(cmd)
            vp.update()
        self._refresh()      # invalid or unchanged input snaps back

    def _apply(self) -> None:
        now = group_scale(self._group)
        typed = self._typed()
        # A field left as shown keeps the exact value, not its rounded text.
        if typed is not None:
            typed = tuple(n if _fmt(n) == _fmt(t) else t
                          for t, n in zip(typed, now))
        self._set(typed)

    def _reset(self) -> None:
        self._set((1.0, 1.0, 1.0))


def ask_scale(window, group) -> None:
    ScaleDialog(window, group).exec()
