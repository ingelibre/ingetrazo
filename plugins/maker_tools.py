# SPDX-License-Identifier: GPL-3.0-or-later
# Maker tools contributed for BKRussell's IngeTrazo workflow.
"""Thread, spur gear and aerofoil generators in the Extensions menu."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel, QLineEdit, QMessageBox, QSpinBox)

from core.i18n import tr
from tools.base import Tool


def _run(viewport, title, kind):
    # Imported here so a missing solid kernel is a dialog error, not a
    # failure to discover the other installed extensions.
    from core import maker
    dialog = QDialog(viewport.window())
    dialog.setWindowTitle(tr(title))
    form = QFormLayout(dialog)
    fields = {}

    def number(key, label, value, minimum=.01, maximum=10000., integer=False):
        box = QSpinBox() if integer else QDoubleSpinBox()
        if not integer:
            box.setDecimals(3)
        box.setRange(minimum, maximum)
        box.setValue(value)
        fields[key] = box
        form.addRow(tr(label), box)
        return box

    if kind == "thread":
        mode = QComboBox()
        for label, value in (("Hex-head bolt", "bolt"), ("Threaded rod", "rod"),
                             ("Hex nut (internal thread)", "nut")):
            mode.addItem(tr(label), value)
        form.addRow(tr("Part"), mode)
        presets = QComboBox()
        presets.addItem(tr("Custom"), None)
        for d, pitch, af, head in ((3,.5,5.5,2),(4,.7,7,2.8),(5,.8,8,3.5),
                                  (6,1,10,4),(8,1.25,13,5.3),(10,1.5,17,6.4),
                                  (12,1.75,19,7.5)):
            presets.addItem(f"M{d} x {pitch:g}", (d, pitch, af, head))
        form.addRow(tr("Preset"), presets)
        number("diameter", "Major diameter (mm)", 6)
        number("pitch", "Thread pitch (mm)", 1, .1, 20)
        number("length", "Thread / nut length (mm)", 20, .1, 500)
        number("across_flats", "Hex across flats (mm)", 10)
        number("head_height", "Bolt head height (mm)", 4)
        number("clearance", "Nut radial clearance (mm)", .15, 0, 5)
        number("sides", "Circle sides (quality)", 48, 12, 96, True)
        left = QCheckBox(tr("Left-hand thread"))
        form.addRow(left)
        def preset_changed():
            values = presets.currentData()
            if values:
                for key, val in zip(("diameter", "pitch", "across_flats", "head_height"), values):
                    fields[key].setValue(val)
        presets.currentIndexChanged.connect(preset_changed)
        presets.setCurrentIndex(4)
        def mode_changed():
            value = mode.currentData()
            fields["across_flats"].setEnabled(value != "rod")
            fields["head_height"].setEnabled(value == "bolt")
            fields["clearance"].setEnabled(value == "nut")
            fields["length"].setValue(6 if value == "nut" else 20)
        mode.currentIndexChanged.connect(mode_changed)
        mode_changed()
        hint = tr("Dimensions are in millimetres. Creates a sampled helical thread; nut clearance is radial.")
    elif kind == "gear":
        number("teeth", "Teeth", 24, 8, 200, True)
        number("module", "Module (mm)", 1, .1, 20)
        number("thickness", "Thickness (mm)", 5)
        number("bore", "Bore diameter (mm; 0 = solid)", 5, 0)
        number("pressure_angle", "Pressure angle (degrees)", 20, 14.5, 30)
        number("samples", "Flank samples (quality)", 8, 4, 24, True)
        hint = tr("External involute spur gear. Pitch diameter = module × teeth. Radial roots; no cutter fillets or profile shift.")
    else:
        foil_preset = QComboBox()
        for key, (preset_title, _code, _note) in maker.AEROFOIL_PRESETS.items():
            foil_preset.addItem(tr(preset_title), key)
        foil_preset.addItem(tr("Custom NACA four-digit section"), "custom")
        foil_preset.setObjectName("aerofoil_preset")
        form.addRow(tr("Aerofoil preset"), foil_preset)
        code = QLineEdit("2412")
        code.setObjectName("naca_code")
        code.setMaxLength(4)
        form.addRow(tr("NACA four-digit code"), code)
        number("chord", "Chord (mm)", 150, 1)
        number("span", "Span (mm)", 300, .1)
        number("samples", "Samples per surface", 60, 20, 160, True)
        hint = tr("Examples: 0012 (symmetric), 2412 (cambered). Constant section with a closed trailing edge; chord along X and span along Y.")
    label = QLabel(hint)
    label.setWordWrap(True)
    label.setMaximumWidth(420)
    form.addRow(label)
    if kind == "aerofoil":
        custom_code = ["2412"]
        code.textEdited.connect(lambda text: custom_code.__setitem__(0, text))
        def foil_changed():
            key = foil_preset.currentData()
            code.setEnabled(key == "custom")
            if key == "custom":
                code.setText(custom_code[0])
                label.setText(hint)
            else:
                _name, profile, note = maker.AEROFOIL_PRESETS[key]
                code.setText(profile if profile.isdigit() else "")
                label.setText(tr(note) + "\n\n" + tr(
                    "Stall speed and handling depend on wing loading, Reynolds number, surface finish and the complete wing. Presets select geometry, not guaranteed flight performance."))
        foil_preset.currentIndexChanged.connect(foil_changed)
        foil_changed()
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setText(tr("Create and place"))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    while dialog.exec() == QDialog.Accepted:
        values = {key: box.value() for key, box in fields.items()}
        if kind == "thread":
            values.update(form=mode.currentData(), left_hand=left.isChecked())
        elif kind == "aerofoil":
            values["code"] = code.text().strip()
            values["preset"] = foil_preset.currentData()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            group = getattr(maker, kind)(**values)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(dialog, tr(title), tr(str(exc)))
            continue
        QApplication.restoreOverrideCursor()
        window = viewport.window()
        window._start_place(group)
        viewport.setFocus()
        return


class ThreadMaker(Tool):
    name = "Thread / Bolt / Nut"

    def on_activate(self, viewport):
        _run(viewport, self.name, "thread")

    def on_deactivate(self, viewport):
        pass


class GearMaker(Tool):
    name = "Spur Gear"

    def on_activate(self, viewport):
        _run(viewport, self.name, "gear")

    def on_deactivate(self, viewport):
        pass


class AerofoilMaker(Tool):
    name = "Aerofoil / Wing Section"

    def on_activate(self, viewport):
        _run(viewport, self.name, "aerofoil")

    def on_deactivate(self, viewport):
        pass
