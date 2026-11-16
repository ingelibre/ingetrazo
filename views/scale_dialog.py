"""Scale… — edit a group or component's X, Y, Z scale.

X can drive all three values; the default pivot can be replaced by a box
grip or an inferred viewport point. Reset pick restores the default pivot;
reset scale uses the current pivot.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QVBoxLayout)

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
    def __init__(self, window, group, pick_point=None) -> None:
        super().__init__(window)
        self._window = window
        self._group = group
        self._pick_point = pick_point
        self._pivot = None
        self.setWindowTitle(tr("Scale"))
        self.setModal(True)
        form = QFormLayout()
        self.fields: list[QLineEdit] = []
        self.link_axes = QCheckBox()
        self.link_axes.setToolTip(tr("Use X for all three scales"))
        self.link_axes.toggled.connect(self._link_changed)
        for axis in "XYZ":
            edit = _Field()
            edit.editingFinished.connect(self._apply)
            if axis == "X":
                row = QHBoxLayout()
                row.addWidget(self.link_axes)
                row.addWidget(edit)
                form.addRow(axis, row)
                edit.textEdited.connect(self._x_edited)
            else:
                form.addRow(axis, edit)
            self.fields.append(edit)
        self.box_button = QPushButton(tr("Pick bounding box point"))
        self.point_button = QPushButton(tr("Pick inference point"))
        self.box_button.clicked.connect(lambda: self._start_pick("box"))
        self.point_button.clicked.connect(lambda: self._start_pick("point"))
        self.box_button.setEnabled(pick_point is not None)
        self.point_button.setEnabled(pick_point is not None)
        self.reset_pick_button = QPushButton(tr("Reset pick"))
        self.reset_pick_button.setToolTip(tr("Restore the default pivot"))
        self.reset_pick_button.clicked.connect(self._reset_pick)
        self.reset_button = QPushButton(tr("Reset scale"))
        self.reset_button.clicked.connect(self._reset)
        self.close_button = QPushButton(tr("Close"))
        self.close_button.clicked.connect(self.accept)
        # Enter belongs to the fields, not to a default button.
        for b in (self.box_button, self.point_button,
                  self.reset_pick_button, self.reset_button, self.close_button):
            b.setAutoDefault(False)
            b.setDefault(False)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.box_button)
        layout.addWidget(self.point_button)
        reset_row = QHBoxLayout()
        reset_row.addWidget(self.reset_pick_button)
        reset_row.addWidget(self.reset_button)
        layout.addLayout(reset_row)
        layout.addWidget(self.close_button)
        for seq, step in ((QKeySequence.Undo, "undo"),
                          (QKeySequence.Redo, "redo"),
                          (QKeySequence("Ctrl+Shift+Z"), "redo")):
            QShortcut(seq, self, lambda s=step: self._history(s))
        self._refresh()

    def _link_changed(self, checked: bool) -> None:
        for edit in self.fields[1:]:
            edit.setEnabled(not checked)

    def _x_edited(self, text: str) -> None:
        if self.link_axes.isChecked():
            for edit in self.fields[1:]:
                edit.setText(text)

    def _start_pick(self, mode: str) -> None:
        if self._pick_point is not None:
            self.hide()
            self._pick_point(mode)

    def finish_pick(self, point) -> None:
        if point is not None:
            self._pivot = QVector3D(point)
        self.show()
        self.raise_()
        self.activateWindow()

    def _reset_pick(self) -> None:
        self._pivot = None

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
        cmd = scale_command(self._group, target, self._pivot) if target else None
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
