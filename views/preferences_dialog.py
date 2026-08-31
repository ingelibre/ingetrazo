# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Window ▸ Preferences — the scattered QSettings, gathered in one dialog.

Three tabs. **General**: UI language (applied on restart, same contract as
the Window ▸ Language menu) and how the rest of the model reads while
editing a group (applied live through ``set_edit_rest_mode``, the same path
the Camera menu uses, so its checkmarks stay honest). **Import**: the units
suggested by the OBJ and DXF/DWG import dialogs (each dialog still asks —
these are the preselected answers) and the coordinate-entry mode shared by
the georef dialogs. **AI Assistant**: the same ``ia/*`` keys the assistant
dialog reads when it opens — provider, API key, model, Ollama URL,
screenshots.

Values are written on OK (with a ``sync()`` flush, the house crash-safety
pattern); Cancel touches nothing.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.i18n import available_languages, current_language, tr

_LANGUAGE_NAMES = {"en": "English", "es": "Español"}

#: The import dialogs' unit vocabularies (must match the dialogs in
#: main_window — the setting is their preselected answer).
_OBJ_UNITS = (("m", "Metres"), ("cm", "Centimetres"), ("mm", "Millimetres"),
              ("in", "Inches"), ("ft", "Feet"))
_DXF_UNITS = (("mm", "Millimetres"), ("cm", "Centimetres"), ("m", "Metres"),
              ("in", "Inches"), ("ft", "Feet"))
_REST_MODES = (("normal", "Show normally"), ("fade", "Fade"),
               ("hide", "Hide (fastest)"))


class PreferencesDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setWindowTitle(tr("Preferences") + " — IngeTrazo")
        self.setMinimumWidth(440)
        st = QSettings()

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ---- General --------------------------------------------------------
        general = QWidget()
        form = QFormLayout(general)
        self._lang = QComboBox()
        for code in available_languages():
            self._lang.addItem(_LANGUAGE_NAMES.get(code, code), code)
        pending = str(st.value("language") or current_language())
        self._lang.setCurrentIndex(max(0, self._lang.findData(pending)))
        form.addRow(tr("Language:"), self._lang)

        self._rest = QComboBox()
        for key, label in _REST_MODES:
            self._rest.addItem(tr(label), key)
        self._rest.setCurrentIndex(max(0, self._rest.findData(
            window.viewport.edit_rest_mode)))
        form.addRow(tr("Rest of model while editing:"), self._rest)

        row = QHBoxLayout()
        self._autosave = QCheckBox(tr("Auto-save every"))
        self._autosave.setChecked(str(st.value("general/autosave", "1"))
                                  != "0")
        row.addWidget(self._autosave)
        self._autosave_min = QSpinBox()
        self._autosave_min.setRange(1, 60)
        self._autosave_min.setSuffix(" " + tr("min"))
        try:
            self._autosave_min.setValue(int(st.value("general/autosave_min",
                                                     5)))
        except (TypeError, ValueError):
            self._autosave_min.setValue(5)
        self._autosave.toggled.connect(self._autosave_min.setEnabled)
        self._autosave_min.setEnabled(self._autosave.isChecked())
        row.addWidget(self._autosave_min)
        row.addStretch()
        form.addRow("", row)

        self._backup = QCheckBox(tr("Keep a backup of the previous save "
                                    "(.igz.bak)"))
        self._backup.setChecked(str(st.value("general/backup", "1")) != "0")
        form.addRow("", self._backup)

        self._invert = QCheckBox(tr("Invert mouse wheel zoom"))
        self._invert.setChecked(str(st.value("nav/invert_wheel", "0"))
                                != "0")
        form.addRow("", self._invert)

        self._msaa = QComboBox()
        for n in (0, 2, 4, 8):
            self._msaa.addItem(tr("Off") if n == 0 else f"{n}x", n)
        try:
            msaa_now = int(st.value("display/msaa", 4))
        except (TypeError, ValueError):
            msaa_now = 4
        self._msaa.setCurrentIndex(max(0, self._msaa.findData(
            msaa_now if msaa_now in (0, 2, 4, 8) else 4)))
        form.addRow(tr("Anti-aliasing (MSAA):"), self._msaa)
        tabs.addTab(general, tr("General"))

        # ---- Import ---------------------------------------------------------
        imp = QWidget()
        form = QFormLayout(imp)
        self._obj_unit = QComboBox()
        for key, label in _OBJ_UNITS:
            self._obj_unit.addItem(tr(label), key)
        self._obj_unit.setCurrentIndex(max(0, self._obj_unit.findData(
            str(st.value("import/obj_unit", "m") or "m"))))
        form.addRow(tr("Suggested unit for OBJ:"), self._obj_unit)

        self._dxf_unit = QComboBox()
        for key, label in _DXF_UNITS:
            self._dxf_unit.addItem(tr(label), key)
        self._dxf_unit.setCurrentIndex(max(0, self._dxf_unit.findData(
            str(st.value("import/dxf_unit", "mm") or "mm"))))
        form.addRow(tr("Suggested unit for DXF/DWG:"), self._dxf_unit)

        self._coord = QComboBox()
        self._coord.addItem(tr("Geographic (lat/lon)"), "geo")
        self._coord.addItem(tr("UTM WGS84"), "utm")
        self._coord.setCurrentIndex(max(0, self._coord.findData(
            str(st.value("georef/coord_mode", "geo") or "geo"))))
        form.addRow(tr("Coordinate entry:"), self._coord)
        tabs.addTab(imp, tr("Import"))

        # ---- AI Assistant ---------------------------------------------------
        ia = QWidget()
        form = QFormLayout(ia)
        self._provider = QComboBox()
        self._provider.addItem(tr("Auto (by key prefix)"), "auto")
        try:
            from core import ai
            for prov in ai.PROVIDERS:
                self._provider.addItem(ai.PROVIDER_INFO[prov][0], prov)
        except Exception:           # noqa: BLE001 — the tab, not the dialog
            pass
        self._provider.setCurrentIndex(max(0, self._provider.findData(
            str(st.value("ia/proveedor", "auto") or "auto"))))
        form.addRow(tr("Provider:"), self._provider)

        self._api_key = QLineEdit(str(st.value("ia/api_key", "") or ""))
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText(tr("empty = local Ollama"))
        form.addRow(tr("API key:"), self._api_key)

        self._model = QLineEdit(str(st.value("ia/modelo", "") or ""))
        self._model.setPlaceholderText(tr("model (default per provider)"))
        form.addRow(tr("Model:"), self._model)

        self._ollama = QLineEdit(str(st.value("ia/ollama_url",
                                              "http://localhost:11434") or ""))
        form.addRow(tr("Ollama URL:"), self._ollama)

        self._shots = QCheckBox(tr("Send viewport screenshots to the model"))
        self._shots.setChecked(str(st.value("ia/capturas", "1")) != "0")
        form.addRow("", self._shots)
        tabs.addTab(ia, tr("AI Assistant"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---- Apply --------------------------------------------------------------
    def accept(self) -> None:  # noqa: D102 — QDialog override
        st = QSettings()

        # Language: same contract as the menu (persists; applies on restart).
        # Reverting a still-pending change back to the running language just
        # rewrites the stored value — no restart note for a no-op.
        code = self._lang.currentData()
        saved = str(st.value("language") or current_language())
        if code != saved:
            st.setValue("language", code)
            if code != current_language():
                from core.i18n import set_language
                set_language(code)
                QMessageBox.information(
                    self, tr("Language changed"),
                    tr("Restart IngeTrazo to apply the new language."))

        # Rest-of-model mode: through the viewport (it persists the setting),
        # then the Camera menu checkmark follows.
        mode = self._rest.currentData()
        if mode != self._window.viewport.edit_rest_mode:
            self._window.viewport.set_edit_rest_mode(mode)
            act = getattr(self._window, "_rest_actions", {}).get(mode)
            if act is not None:
                act.setChecked(True)

        st.setValue("general/autosave",
                    "1" if self._autosave.isChecked() else "0")
        st.setValue("general/autosave_min", self._autosave_min.value())
        st.setValue("general/backup", "1" if self._backup.isChecked() else "0")
        setup = getattr(self._window, "_setup_autosave", None)
        if callable(setup):
            setup()                     # re-arm the timer with the new pace

        st.setValue("nav/invert_wheel",
                    "1" if self._invert.isChecked() else "0")
        self._window.viewport._invert_wheel = self._invert.isChecked()

        msaa = self._msaa.currentData()
        st.setValue("display/msaa", msaa)
        vp = self._window.viewport
        if getattr(vp, "_msaa", None) != msaa:
            vp._msaa = msaa
            # Void the FBO size so the next paint rebuilds it at the new
            # sample count (the rebuild happens with the context current).
            vp._fbo_size = None
            update = getattr(vp, "update", None)
            if callable(update):
                update()

        st.setValue("import/obj_unit", self._obj_unit.currentData())
        st.setValue("import/dxf_unit", self._dxf_unit.currentData())
        st.setValue("georef/coord_mode", self._coord.currentData())

        st.setValue("ia/proveedor", self._provider.currentData())
        st.setValue("ia/api_key", self._api_key.text())
        st.setValue("ia/modelo", self._model.text().strip())
        st.setValue("ia/ollama_url", self._ollama.text().strip())
        st.setValue("ia/capturas", "1" if self._shots.isChecked() else "0")
        st.sync()
        super().accept()
