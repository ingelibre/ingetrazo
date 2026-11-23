# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Soften Edges (#347): soften the selection's edges by the angle their
faces fold, all at once — the round end of the hand-softening Soften.

The controls live in :class:`SoftenEdgesPanel`, shown both in the
Properties palette (under Entity info) and in the Edit ▸ Soften Edges…
window. Moving the angle softens every edge of the selection whose two
faces fold that much or less, and hardens the others, live. However many
moves it takes, they are ONE undo step — each move takes back the previous
one before it applies, the way a typed value retypes the last push.

The first move takes the edges and clears the selection: the selection's
colour would hide the very thing being tuned. The panel keeps working on
those edges until something else is selected, which starts a new step.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QHBoxLayout, QLabel, QSlider,
                               QVBoxLayout, QWidget)

from core.i18n import tr

#: The angle the controls open with, and the last one used this session.
DEFAULT_DEGREES = 20.0


class SoftenEdgesPanel(QWidget):
    """The angle, the coplanar option and what they act on."""

    _last = DEFAULT_DEGREES
    _last_coplanar = False

    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        self._cmd = None             # the step applied, retyped by the next
        self._targets_key = None     # which edges that step was made for
        self._held: list = []        # the edges taken when the selection went
        self._held_in = None         # (scene, mesh) they belong to
        self._busy = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        intro = QLabel(tr(
            "Edges whose faces fold this angle or less turn soft; the "
            "others turn hard."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 180)
        self.box = QDoubleSpinBox()
        self.box.setRange(0.0, 180.0)
        self.box.setDecimals(1)
        self.box.setSuffix("°")
        self.box.setKeyboardTracking(False)
        row.addWidget(QLabel(tr("Angle:")))
        row.addWidget(self.slider, 1)
        row.addWidget(self.box)
        lay.addLayout(row)
        self.coplanar = QCheckBox(tr("Soften coplanar edges too"))
        lay.addWidget(self.coplanar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.box.setValue(SoftenEdgesPanel._last)
        self.slider.setValue(int(round(SoftenEdgesPanel._last)))
        self.coplanar.setChecked(SoftenEdgesPanel._last_coplanar)
        self.slider.valueChanged.connect(self._on_slider)
        self.box.valueChanged.connect(self._on_box)
        self.coplanar.toggled.connect(lambda _on: self.apply())
        self.refresh()

    # ---- What it acts on ------------------------------------------------------
    def _context(self):
        vp = self._window.viewport
        return vp.scene, vp.scene.mesh

    def _selected_targets(self) -> list:
        """The selection's edges an angle can act on: those between two
        faces (a loose line or a border has no fold)."""
        sel = list(self._window.viewport.scene.selection)
        if not sel:
            return []
        return [e for e in self._window._soften_targets(sel)
                if len(getattr(e, "faces", ())) == 2]

    def _targets(self) -> list:
        """The selection's edges; with nothing selected, the ones the last
        move took — still in the same document and the same open group."""
        if self._window.viewport.scene.selection:
            return self._selected_targets()
        if self._held and self._held_in == self._context():
            return list(self._held)
        return []

    def forget(self) -> None:
        """Let go of the edges taken: the next move starts a new step."""
        self._held = []
        self._held_in = None
        self._cmd = None

    def refresh(self) -> None:
        """Say what it acts on, without changing anything."""
        if self._window.viewport.scene.selection:
            self._held, self._held_in = [], None   # a new selection wins
        edges = self._targets()
        if not edges:
            self.status.setText(tr("Select edges or faces first."))
            return
        soft = sum(1 for e in edges if e.soft)
        text = tr("{soft} of {n} edges soft", soft=soft, n=len(edges))
        if self._held:
            text += "\n" + tr("Deselected so the result shows; select "
                              "something else to soften it instead.")
        self.status.setText(text)

    # ---- Changing it ----------------------------------------------------------
    def _on_slider(self, value: int) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.box.setValue(float(value))
        finally:
            self._busy = False
        self.apply()

    def _on_box(self, value: float) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self.slider.setValue(int(round(value)))
        finally:
            self._busy = False
        self.apply()

    def apply(self) -> None:
        """Soften and harden the edges at the angle shown — the previous
        move taken back first, so the whole session is one step — and
        clear the selection so the model shows the result."""
        from core.history import soften_by_angle_command
        viewport = self._window.viewport
        history = viewport.history
        degrees = float(self.box.value())
        coplanar = self.coplanar.isChecked()
        SoftenEdgesPanel._last = degrees
        SoftenEdgesPanel._last_coplanar = coplanar
        edges = self._targets()
        key = frozenset(id(e) for e in edges)
        if (self._cmd is not None and key == self._targets_key
                and history.undo_stack and history.undo_stack[-1] is self._cmd):
            history.undo()
            # Taken back to be retyped, not to be redone: a new angle that
            # changes nothing must not leave Redo holding the old one.
            if history.redo_stack and history.redo_stack[-1] is self._cmd:
                history.redo_stack.pop()
        self._cmd = None
        self._targets_key = key
        if not edges:
            self.refresh()
            return
        cmd = soften_by_angle_command(edges, degrees, coplanar)
        if cmd is not None:
            history.execute(cmd)
            if history.undo_stack and history.undo_stack[-1] is cmd:
                self._cmd = cmd
        # The selection's colour would hide the result: hold the edges and
        # let the selection go.
        self._held, self._held_in = list(edges), self._context()
        viewport.scene.clear_selection()
        viewport.update()
        self.refresh()


class SoftenEdgesDialog(QDialog):
    """Edit ▸ Soften Edges…: the same controls in a small window that stays
    open beside the model."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle(tr("Soften Edges"))
        self.setModal(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        self.panel = SoftenEdgesPanel(window, self)
        lay.addWidget(self.panel)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.setContentsMargins(8, 0, 8, 0)
        buttons.rejected.connect(self.close)
        lay.addWidget(buttons)
        self.slider = self.panel.slider
        self.box = self.panel.box
        self.coplanar = self.panel.coplanar
        self.status = self.panel.status

    def refresh(self) -> None:
        self.panel.refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        self.panel.forget()
        super().closeEvent(event)
