# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""2D CAD View — floor plans, elevations and sections as a layered DXF.

Extensions ▸ 2D CAD view… opens a small dialog: the view (a floor plan cut
at a height, an elevation N/S/E/W, or one of the document's section
planes), its view depth, which disciplines to keep, and the scale the
dashes and hatch are sized for. Export DXF writes the exact hidden-line
drawing (``core.cad_views``) with every line on its discipline layer —
``A-WALL-CUT``, ``S-COLS-PROJ``, ``M-DUCT-HIDN`` — and each layer's pen
(``core.cad_layers``), ready for a CAD title block.

Nothing is added to the document: the cut and the view range live in the
dialog, not in the model. The modules are imported at the top on purpose:
``ingetrazo.spec`` finds what a bundled plugin needs by reading its
imports, and these would otherwise be missing from the packaged builds.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFormLayout, QHBoxLayout,
                               QMessageBox, QPushButton, QVBoxLayout)

from core import cad_layers, cad_views
from core.i18n import tr
from formats import dxf_cad  # noqa: F401  (bundled with the plugin, see above)
from views.filedialogs import file_dialogs


def _length_box(value: float, lo: float, hi: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(2)
    box.setSingleStep(0.1)
    box.setSuffix(" m")
    box.setValue(value)
    return box


class CadViewDialog(QDialog):
    """The view, its range and the export, in one small window."""

    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self._app = app
        self.setWindowTitle(tr("2D CAD View"))
        form = QFormLayout()

        self.view = QComboBox()
        form.addRow(tr("View"), self.view)
        self.level = _length_box(0.0, -1000.0, 1000.0)
        form.addRow(tr("Level"), self.level)
        self.cut = _length_box(1.2, 0.0, 100.0)
        form.addRow(tr("Cut height"), self.cut)
        self.depth = _length_box(1.5, 0.0, 1000.0)
        form.addRow(tr("View depth (0 = unlimited)"), self.depth)

        self.disciplines = QComboBox()
        for key, label in (("all", tr("All")),
                           ("architectural", tr("Architectural")),
                           ("structural", tr("Structural")),
                           ("mep", tr("MEP"))):
            self.disciplines.addItem(label, key)
        form.addRow(tr("Disciplines"), self.disciplines)

        self.scale = QDoubleSpinBox()
        self.scale.setRange(1.0, 10000.0)
        self.scale.setDecimals(0)
        self.scale.setPrefix("1:")
        self.scale.setValue(100.0)
        form.addRow(tr("Scale"), self.scale)

        self.hidden = QCheckBox(tr("Show hidden lines (dashed)"))
        self.hatch = QCheckBox(tr("Hatch the cut"))
        self.hatch.setChecked(True)
        form.addRow(self.hidden)
        form.addRow(self.hatch)

        export = QPushButton(tr("Export DXF…"))
        export.setDefault(True)
        export.clicked.connect(self._on_export)
        close = QPushButton(tr("Close"))
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(export)
        buttons.addWidget(close)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(buttons)
        self.view.currentIndexChanged.connect(self._sync)
        self.refresh()

    def refresh(self) -> None:
        """Fill the view list from the open document (its section planes
        change between openings)."""
        current = self.view.currentData()
        self.view.blockSignals(True)
        self.view.clear()
        self.view.addItem(tr("Floor plan"), (cad_views.PLAN, None))
        for side, label in (("N", tr("North")), ("S", tr("South")),
                            ("E", tr("East")), ("W", tr("West"))):
            self.view.addItem(tr("Elevation — {side}", side=label),
                              (cad_views.ELEVATION, side))
        for i, plane in enumerate(getattr(self._app.scene,
                                          "section_planes", ())):
            name = plane.name or plane.symbol or str(i + 1)
            self.view.addItem(tr("Section «{name}»", name=name),
                              (cad_views.SECTION, plane.uid))
        idx = self.view.findData(current)
        self.view.setCurrentIndex(max(idx, 0))
        self.view.blockSignals(False)
        self._sync()

    def _sync(self) -> None:
        kind = (self.view.currentData() or (cad_views.PLAN, None))[0]
        self.level.setEnabled(kind == cad_views.PLAN)
        self.cut.setEnabled(kind == cad_views.PLAN)

    def spec(self) -> cad_views.ViewSpec:
        kind, arg = self.view.currentData() or (cad_views.PLAN, None)
        return cad_views.ViewSpec(
            kind=kind, level=self.level.value(), cut_height=self.cut.value(),
            view_depth=self.depth.value(),
            direction=arg if kind == cad_views.ELEVATION else "S",
            section_uid=arg if kind == cad_views.SECTION else None,
            hidden=self.hidden.isChecked())

    def _on_export(self) -> None:
        path, _ = file_dialogs.getSaveFileName(
            self, tr("Export DXF…"), "view.dxf", "DXF (*.dxf)")
        if not path:
            return
        filt = cad_layers.DISCIPLINE_FILTERS[self.disciplines.currentData()]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            result = cad_views.export_dxf(
                self._app.scene, self.spec(), path, disciplines=filt,
                scale_n=self.scale.value(), hatch=self.hatch.isChecked())
        except Exception as exc:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr("Export DXF failed"), str(exc))
            return
        QApplication.restoreOverrideCursor()
        if not result["lines"]:
            QMessageBox.information(self, tr("2D CAD View"),
                                    tr("Nothing to draw in this view."))
            return
        self._app.window.statusBar().showMessage(
            tr("Exported {n} lines on {layers} layers to {name}",
               n=result["lines"], layers=len(result["layers"]),
               name=Path(path).name), 6000)


def setup(app) -> None:
    dialog = None

    def open_dialog() -> None:
        nonlocal dialog
        if dialog is None:
            dialog = CadViewDialog(app, app.window)
        dialog.refresh()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    app.add_menu_action(
        tr("2D CAD view…"), open_dialog,
        tip=tr("Floor plans, elevations and sections as a layered DXF, "
               "hidden lines removed."))
