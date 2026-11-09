# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A length field in the document's units (issue #287).

A dialog asked for the 3D text's height and extrusion in metres whatever
the document's units were: «I select millimetres in the preferences, but
the height and extrusion of the 3D text are shown in metres». This field
SHOWS a length the way every readout does (``core.units``) and READS what
is typed the way the value box does — ``25``, ``2,5 cm``, ``1"``,
``3/4"`` — while ``value()`` stays in metres, the model's unit, so the
code behind the dialog never converts anything.
"""
from __future__ import annotations

from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QDoubleSpinBox, QToolTip

from core import units


class LengthSpinBox(QDoubleSpinBox):
    """A spin box whose value is metres and whose text is the document's
    unit. The arrows add one step of the shown precision (1 mm in a
    millimetre document); text that is not a length («5 m²», «abc») is not
    taken, and the reason shows next to the field."""

    def __init__(self, parent=None, minimum: float = 0.0,
                 maximum: float = 1000.0, unit: str | None = None,
                 decimals: int | None = None) -> None:
        super().__init__(parent)
        self._unit = unit or units.model_unit()
        # At least to the millimetre: a 2 mm text in a document shown to the
        # centimetre must not read «0 cm».
        self._shown = units.fine_precision() if decimals is None else decimals
        # Qt rounds the stored value to decimals(): metres to the micron
        # keep every unit's shown precision exact.
        super().setDecimals(9)
        self.setRange(minimum, maximum)
        self.setSingleStep(units.display_step(self._unit, self._shown))
        self.setAccelerated(True)

    def unit(self) -> str:
        return self._unit

    def textFromValue(self, value: float) -> str:
        return units.localized(
            units.format_length(value, self._unit, self._shown))

    def valueFromText(self, text: str) -> float:
        r = units.parse(text, "length", self._unit)
        return r.value if r.ok else self.value()

    def _reading(self, text: str):
        r = units.parse(text, "length", self._unit)
        if r.ok and not self.minimum() - 1e-12 <= r.value <= self.maximum() + 1e-12:
            from core.i18n import tr
            return None, tr("Out of range: {low} to {high}",
                            low=self.textFromValue(self.minimum()),
                            high=self.textFromValue(self.maximum()))
        return (r.value, "") if r.ok else (None, r.message())

    def validate(self, text: str, pos: int):
        value, _ = self._reading(text)
        state = QValidator.Acceptable if value is not None \
            else QValidator.Intermediate
        return state, text, pos

    def error_text(self) -> str:
        """Why the text in the field is not taken («» when it is)."""
        return self._reading(self.lineEdit().text())[1]

    def fixup(self, text: str) -> str:
        msg = self._reading(text)[1]
        if msg:
            # Leaving the field puts the last good value back; say why.
            QToolTip.showText(self.mapToGlobal(self.rect().bottomLeft()),
                              msg, self)
        return text
