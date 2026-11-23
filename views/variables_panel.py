# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The side tray's **Variables** tab: the model's named measurements.

A variable is defined once here — ``ancho`` = ``3.20m`` — and every
calculation typed after «=» reads it by name: ``=ancho/2`` in the value box
or in any length field (``core.units.parse_expression``). The value is kept
as typed, a measurement with its unit, a plain number (``4``) or a
calculation of its own (``=ancho-2*muro``); the third column says what it
comes to, or why it does not. Every edit goes through the undo history
(``core.history.SetVariablesCommand``) and travels in the .igz."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QHBoxLayout,
                               QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from core import units
from core.i18n import tr

COL_NAME, COL_VALUE, COL_RESULT = range(3)


def result_text(name: str, variables: dict) -> tuple[str, bool]:
    """What the variable ``name`` comes to, as the third column shows it,
    and whether it is an error."""
    kind, value = units.read_variable(name, variables)
    if kind is None:
        return value.message(), True
    if kind == "length":
        return units.fmt_len(value), False
    if kind == "area":
        return units.fmt_area(value), False
    if kind == "volume":
        return units.fmt_volume(value), False
    if kind == "angle":
        return units.fmt_angle(value), False
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return tr("{value} (number)", value=units.localized(text)), False


def new_name(variables: dict) -> str:
    """A free name for a new variable: ``variable1``, ``variable2``…"""
    i = 1
    taken = {k.lower() for k in variables}
    while f"variable{i}" in taken:
        i += 1
    return f"variable{i}"


class VariablesPanel(QWidget):
    """The table of variables — Name, Value, Result — and its add and
    remove buttons. ``window`` gives the viewport (its scene and history)."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        hint = QLabel(tr(
            "Give a measurement a name and type it in any calculation: "
            "=width/2 in the value box or in a field."))
        hint.setWordWrap(True)
        box.addWidget(hint)
        bar = QHBoxLayout()
        self.add_button = QToolButton()
        self.add_button.setText("+")
        self.add_button.setToolTip(tr("Add a variable"))
        self.add_button.clicked.connect(self.add_variable)
        self.remove_button = QToolButton()
        self.remove_button.setText("−")
        self.remove_button.setToolTip(tr("Delete the selected variables"))
        self.remove_button.clicked.connect(self.remove_selected)
        bar.addWidget(self.add_button)
        bar.addWidget(self.remove_button)
        bar.addStretch(1)
        box.addLayout(bar)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("Name"), tr("Value"), tr("Result")])
        self.table.verticalHeader().hide()
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(COL_NAME, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(COL_VALUE, QHeaderView.Stretch)
        head.setSectionResizeMode(COL_RESULT, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.itemChanged.connect(self._edited)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        box.addWidget(self.table, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color:#c0392b;")
        self.message.hide()
        box.addWidget(self.message)
        self.refresh()

    # ---- The model -----------------------------------------------------------
    def _viewport(self):
        return getattr(self._window, "viewport", None)

    def variables(self) -> dict:
        vp = self._viewport()
        return units.model_variables(vp.scene) if vp is not None else {}

    def _apply(self, variables: dict) -> None:
        from core.history import SetVariablesCommand
        vp = self._viewport()
        if vp is None or variables == self.variables():
            self.refresh()
            return
        vp.history.execute(SetVariablesCommand(variables))
        update = getattr(vp, "update", None)
        if callable(update):
            update()
        self.refresh()

    # ---- Showing -------------------------------------------------------------
    def on_scene_changed(self) -> None:
        if self.table.state() != QAbstractItemView.EditingState:
            self.refresh()

    def refresh(self) -> None:
        variables = self.variables()
        self._updating = True
        try:
            self.table.setRowCount(len(variables))
            for row, (name, text) in enumerate(variables.items()):
                self.table.setItem(row, COL_NAME, QTableWidgetItem(name))
                self.table.setItem(row, COL_VALUE, QTableWidgetItem(text))
                shown, bad = result_text(name, variables)
                cell = QTableWidgetItem(shown)
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                cell.setToolTip(shown)
                if bad:
                    cell.setForeground(Qt.red)
                self.table.setItem(row, COL_RESULT, cell)
        finally:
            self._updating = False
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.remove_button.setEnabled(bool(self.table.selectedItems()))

    def _say(self, text: str = "") -> None:
        self.message.setText(text)
        self.message.setVisible(bool(text))

    # ---- Editing -------------------------------------------------------------
    def add_variable(self) -> str:
        """A new variable, ``variableN`` = 0, its name ready to type over."""
        variables = self.variables()
        name = new_name(variables)
        variables[name] = "0"
        self._say()
        self._apply(variables)
        row = list(self.variables()).index(name)
        self.table.setCurrentCell(row, COL_NAME)
        self.table.editItem(self.table.item(row, COL_NAME))
        return name

    def remove_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedItems()}
        names = list(self.variables())
        keep = {n: t for i, (n, t) in enumerate(self.variables().items())
                if i not in rows}
        if len(keep) != len(names):
            self._say()
            self._apply(keep)

    def _edited(self, item) -> None:
        if self._updating:
            return
        row, col = item.row(), item.column()
        pairs = list(self.variables().items())
        if not 0 <= row < len(pairs):
            return
        old_name, old_text = pairs[row]
        if col == COL_NAME:
            name = item.text().strip()
            others = [n for i, (n, _t) in enumerate(pairs) if i != row]
            error = units.variable_name_error(name, others)
            if error:
                self._say(tr(error, name=name) if "{name}" in error
                          else tr(error))
                self.refresh()
                return
            if name == old_name:
                return
            self._say()
            self._apply(units.rename_variable(dict(pairs), old_name, name))
            return
        elif col == COL_VALUE:
            pairs[row] = (old_name, item.text().strip() or "0")
        else:
            return
        self._say()
        self._apply(dict(pairs))


class VariablesDock(QDockWidget):
    """Sidebar tab **Variables**, after Scenes; it starts closed (Window ▸
    Panels opens it)."""

    def __init__(self, window) -> None:
        super().__init__(tr("Variables"), window)
        self.setObjectName("tray_variables")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetClosable)
        self.panel = VariablesPanel(window)
        self.setWidget(self.panel)
        self.setMinimumWidth(240)

    def on_scene_changed(self) -> None:
        self.panel.on_scene_changed()
