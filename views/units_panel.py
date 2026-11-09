# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The units panel: Preferences ▸ Units (Window ▸ Units…, Ctrl+U).

One profile on top sets everything with a click (Metric, Millimetric,
Imperial); the rows below only fine-tune it, each a unit and its
precision side by side — the length (decimals, or the smallest fraction
of an inch), areas and volumes (by the length, or a unit of their own),
angles — then the decimal separator and a preview of what 1.2345 reads
like with what is picked, before OK. Laid out like the other Preferences
pages: one form, «Label:» on the left, the fields in one column.

The panel only edits a settings dict (``settings()``); the dialog gives
it to the document. Nothing here touches a stored value: the units change
what is shown and what a bare typed number means.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QSizePolicy, QSpinBox, QStackedWidget, QWidget)

from core import units
from core.i18n import tr
from views.theme import style as theme_style


def _combo(items) -> QComboBox:
    box = QComboBox()
    for data, label in items:
        box.addItem(label, data)
    return box


def _pick(box: QComboBox, data) -> None:
    box.setCurrentIndex(max(0, box.findData(data)))


def _decimals_spin() -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 6)
    spin.valueChanged.connect(lambda n, s=spin: s.setSuffix(
        tr(" decimal") if n == 1 else tr(" decimals")))
    spin.setSuffix(tr(" decimals"))
    spin.setMinimumWidth(130)
    spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return spin


def _pair(left: QWidget, right: QWidget) -> QWidget:
    """A unit and its precision on one row."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(left, 1)
    lay.addWidget(right)
    return row


class UnitsPanel(QWidget):
    """Edits a document's units (``core.units`` settings dict). ``form``
    is its layout, so the dialog can add rows in the same columns."""

    changed = Signal()

    def __init__(self, settings: dict | None = None, parent=None) -> None:
        super().__init__(parent)
        self._busy = False
        form = self.form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)

        self.profile = _combo((name, tr(label))
                              for name, label in units.PROFILE_LABELS.items())
        form.addRow(tr("Profile:"), self.profile)

        self.length = _combo((c, units.unit_label(c)) for c in units.UNIT_CHOICES)
        self.decimals = _decimals_spin()
        self.fraction = _combo(enumerate(units.FRACTION_LABELS))
        self.fraction.setToolTip(tr("The smallest fraction of an inch shown"))
        self.fraction.setMinimumWidth(130)
        self._precision = QStackedWidget()
        self._precision.addWidget(self.decimals)
        self._precision.addWidget(self.fraction)
        self._precision.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        form.addRow(tr("Length:"), _pair(self.length, self._precision))

        # «By the length (m²)»: the option says the unit it gives.
        self.area = _combo([("auto", "")]
                           + [(c, units.unit_label(c)) for c in units.AREA_CHOICES])
        self.area_decimals = _decimals_spin()
        form.addRow(tr("Area:"), _pair(self.area, self.area_decimals))
        self.volume = _combo([("auto", "")]
                             + [(c, units.unit_label(c)) for c in units.VOLUME_CHOICES])
        self.volume_decimals = _decimals_spin()
        form.addRow(tr("Volume:"), _pair(self.volume, self.volume_decimals))

        self.angle = _combo((c, units.unit_label(c)) for c in units.ANGLE_CHOICES)
        self.angle_decimals = _decimals_spin()
        form.addRow(tr("Angle:"), _pair(self.angle, self.angle_decimals))

        self.decimal = _combo(((".", tr("Point (1.25)")),
                               (",", tr("Comma (1,25)"))))
        self.decimal.setToolTip(tr(
            "How numbers are shown. Typing takes both: «1,20» and «1.20» "
            "are the same."))
        form.addRow(tr("Decimal separator:"), self.decimal)

        self.preview = QLabel()
        self.preview.setObjectName("unitsPreview")
        theme_style(self.preview, "color:{muted};")
        form.addRow(tr("Preview:"), self.preview)

        for w in (self.length, self.fraction, self.area, self.volume,
                  self.angle, self.decimal):
            w.currentIndexChanged.connect(self._edited)
        for w in (self.decimals, self.area_decimals, self.volume_decimals,
                  self.angle_decimals):
            w.valueChanged.connect(self._edited)
        self.profile.currentIndexChanged.connect(self._profile_picked)

        self.set_settings(settings or dict(units.DEFAULT_MODEL_UNITS))

    # ---- the settings ---------------------------------------------------------
    def _fractional(self) -> bool:
        return self.length.currentData() in ("in-frac", "ft-in-frac")

    def settings(self) -> dict:
        """What the panel shows, as a validated ``core.units`` settings dict
        (keys left at their defaults are absent)."""
        precision = (int(self.fraction.currentData()) if self._fractional()
                     else self.decimals.value())
        raw = {"length": self.length.currentData(), "precision": precision,
               "area": self.area.currentData(),
               "volume": self.volume.currentData(),
               "volume_precision": self.volume_decimals.value(),
               "angle": self.angle.currentData(),
               "angle_precision": self.angle_decimals.value(),
               "decimal": self.decimal.currentData()}
        if raw["area"] != "auto":
            raw["area_precision"] = self.area_decimals.value()
        return units.model_units_of({"units": raw})

    def set_settings(self, settings: dict) -> None:
        s = units.model_units_of({"units": settings})
        self._busy = True
        try:
            _pick(self.length, s["length"])
            self.decimals.setValue(s["precision"])
            self.fraction.setCurrentIndex(max(0, min(4, s["precision"])))
            for combo, spin, key in ((self.area, self.area_decimals, "area"),
                                     (self.volume, self.volume_decimals, "volume")):
                _pick(combo, units.unit_setting(key, s))
                spin.setValue(units.unit_setting(key + "_precision", s))
            _pick(self.angle, units.unit_setting("angle", s))
            self.angle_decimals.setValue(units.unit_setting("angle_precision", s))
            _pick(self.decimal, units.unit_setting("decimal", s))
        finally:
            self._busy = False
        self._refresh()

    # ---- reacting ---------------------------------------------------------------
    def _profile_picked(self) -> None:
        if self._busy:
            return
        name = self.profile.currentData()
        if name in units.PROFILES:
            self.set_settings(units.with_profile(self.settings(), name))
            self.changed.emit()

    def _edited(self) -> None:
        if self._busy:
            return
        if self.sender() is self.length:
            # Moving between decimal and fractional forms keeps the
            # precision index meaningful (2 → 1/16", 2 decimals).
            self._busy = True
            try:
                if self._fractional():
                    self.fraction.setCurrentIndex(min(4, self.decimals.value()))
                else:
                    self.decimals.setValue(self.fraction.currentIndex())
            finally:
                self._busy = False
        self._refresh()
        self.changed.emit()

    def _refresh(self) -> None:
        s = self.settings()
        length = s["length"]
        self._busy = True
        try:
            _pick(self.profile, units.profile_of(s))
            self._precision.setCurrentIndex(1 if self._fractional() else 0)
            for combo, unit in ((self.area, units.area_unit_for(length)),
                                (self.volume, units.volume_unit_for(length))):
                combo.setItemText(0, tr("By the length ({unit})",
                                        unit=units.UNITS[unit].symbol))
            # An area by the length takes its precision too; a volume keeps
            # its own (three decimals unless changed).
            auto = self.area.currentData() == "auto"
            self.area_decimals.setEnabled(not auto)
            if auto:
                self.area_decimals.setValue(units.unit_setting("area_precision", s))
        finally:
            self._busy = False
        self.preview.setText(self.preview_text(s))

    @staticmethod
    def preview_text(settings: dict) -> str:
        """``1.2345 m → 123.5 cm`` and its area, volume and angle — what
        the picked settings make of one value."""
        v = units.PREVIEW_VALUE
        given = units.localized(f"{v}", settings)
        rows = (
            (f"{given} m", units.fmt_len_with(v, settings)),
            (f"{given} m²", units.fmt_area_with(v, settings)),
            (f"{given} m³", units.fmt_volume_with(v, settings)),
            (f"{given} rad", units.fmt_angle_with(v, settings)),
        )
        return "\n".join(f"{src} → {shown}" for src, shown in rows)
