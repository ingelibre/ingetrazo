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

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core import _native
from core import general_settings as _gs
from core.i18n import LANGUAGE_NAMES as _LANGUAGE_NAMES
from core.i18n import available_languages, current_language, tr


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

        from views.theme import DARK, LIGHT, SYSTEM, saved_theme
        self._theme = QComboBox()
        for key, label in ((DARK, tr("Dark")), (LIGHT, tr("Light")),
                           (SYSTEM, tr("Same as the system"))):
            self._theme.addItem(label, key)
        self._theme.setCurrentIndex(max(0, self._theme.findData(
            saved_theme())))
        self._theme.setToolTip(tr(
            "Colours of menus, panels and toolbars. «Same as the system» "
            "switches along with the desktop's light or dark mode. The 3D "
            "view keeps its own style. Applies at once."))
        form.addRow(tr("Theme:"), self._theme)

        from views.theme import ACCENTS, accent_color, saved_accent
        self._accent = QComboBox()
        for key, label, _rgb in ACCENTS:
            swatch = QPixmap(14, 14)
            swatch.fill(accent_color(key))
            self._accent.addItem(QIcon(swatch), tr(label), key)
        self._accent.setCurrentIndex(max(0, self._accent.findData(
            saved_accent())))
        self._accent.setToolTip(tr(
            "Colour of the details of the icons and of the toolbar buttons "
            "under the mouse. «Same as the system» uses the desktop's "
            "accent colour. The selection in the 3D view stays orange. "
            "Applies at once."))
        form.addRow(tr("Accent colour:"), self._accent)

        self._rest = QComboBox()
        for key, label in _REST_MODES:
            self._rest.addItem(tr(label), key)
        self._rest.setCurrentIndex(max(0, self._rest.findData(
            window.viewport.edit_rest_mode)))
        form.addRow(tr("Rest of model while editing:"), self._rest)

        row = QHBoxLayout()
        self._autosave = QCheckBox(tr("Auto-save every"))
        self._autosave.setChecked(str(_gs.value("autosave", "1", st))
                                  != "0")
        row.addWidget(self._autosave)
        self._autosave_min = QSpinBox()
        self._autosave_min.setRange(1, 60)
        self._autosave_min.setSuffix(" " + tr("min"))
        try:
            self._autosave_min.setValue(int(_gs.value("autosave_min", 5, st)))
        except (TypeError, ValueError):
            self._autosave_min.setValue(5)
        self._autosave.toggled.connect(self._autosave_min.setEnabled)
        self._autosave_min.setEnabled(self._autosave.isChecked())
        row.addWidget(self._autosave_min)
        row.addStretch()
        form.addRow("", row)

        self._backup = QCheckBox(tr("Keep a backup of the previous save "
                                    "(.igz.bak)"))
        self._backup.setChecked(str(_gs.value("backup", "1", st)) != "0")
        form.addRow("", self._backup)

        self._undo_steps = QSpinBox()
        self._undo_steps.setRange(0, 5000)
        self._undo_steps.setSpecialValueText(tr("unlimited"))
        self._undo_steps.setValue(int(_gs.value("undo_steps", 200, st)))
        self._undo_steps.setToolTip(tr(
            "Steps kept for Undo. Each one holds a snapshot of the model, "
            "so fewer steps mean less memory on a big model; 0 = unlimited."))
        form.addRow(tr("Undo steps"), self._undo_steps)

        self._ask_section = QCheckBox(tr(
            "Ask for a name and symbol when placing a section plane"))
        self._ask_section.setChecked(
            str(st.value("section/ask_name", "1")) != "0")
        form.addRow("", self._ask_section)

        # A new document starts with the 1.70 m scale figure; someone who
        # models parts for a 3D printer starts on an empty sheet (#221).
        self._scale_figure = QCheckBox(tr(
            "Put the scale figure in new documents"))
        self._scale_figure.setChecked(
            str(st.value("new_document/scale_figure", "1")) != "0")
        form.addRow("", self._scale_figure)
        self._build_figure_rows(form, st)

        self._invert = QCheckBox(tr("Invert mouse wheel zoom"))
        self._invert.setChecked(str(st.value("nav/invert_wheel", "0"))
                                != "0")
        form.addRow("", self._invert)

        self._invert_orbit = QCheckBox(tr("Invert vertical orbit"))
        self._invert_orbit.setChecked(str(st.value("nav/invert_orbit_y", "0"))
                                      != "0")
        form.addRow("", self._invert_orbit)

        from tools.walkthrough import look_sensitivity
        self._look_sens = QSpinBox()
        self._look_sens.setRange(1, 100)
        self._look_sens.setValue(look_sensitivity())
        self._look_sens.setToolTip(tr(
            "How fast a drag turns the head in First Person"))
        form.addRow(tr("Mouse-look sensitivity:"), self._look_sens)

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

        from views.icons import TOOLBAR_ICON_SIZES, toolbar_icon_px
        self._icon_px = QComboBox()
        for px, label in TOOLBAR_ICON_SIZES:
            self._icon_px.addItem(f"{tr(label)} ({px} px)", px)
        self._icon_px.setCurrentIndex(max(0, self._icon_px.findData(
            toolbar_icon_px())))
        self._icon_px.setToolTip(tr(
            "Size of the icons on every toolbar — the model's and the "
            "sheet composer's. Applies at once."))
        form.addRow(tr("Toolbar icons:"), self._icon_px)

        from core.platform_choice import AUTO, WAYLAND, XCB
        self._platform = QComboBox()
        for key, label in ((AUTO, tr("Automatic (X11 on KDE Plasma or with a fractional display scale)")),
                           (WAYLAND, tr("Wayland")), (XCB, tr("X11 (XWayland)"))):
            self._platform.addItem(label, key)
        self._platform.setCurrentIndex(max(0, self._platform.findData(
            str(_gs.value("platform", AUTO, st) or AUTO))))
        self._platform.setToolTip(tr(
            "Which display server Qt draws through. Under Wayland with a "
            "125 % / 150 % display scale the viewport stutters; X11 "
            "(XWayland) draws smoothly and stays crisp. Takes effect at the "
            "next start."))
        form.addRow(tr("Graphics server:"), self._platform)

        # The experimental Rust engine (core._native): off by default, read
        # once at start. Greyed out in a build that does not carry it.
        self._rust = QCheckBox(tr("Rust engine (experimental)"))
        self._rust.setChecked(str(_gs.value(_native.SETTING, "0", st)) == "1")
        if _native.available() is None:
            self._rust.setEnabled(False)
            self._rust.setToolTip(tr("This build of IngeTrazo does not carry "
                                     "the Rust engine."))
        else:
            self._rust.setToolTip(tr(
                "Computes the heavy parts (hidden lines of the sheets and "
                "more) with the new native engine, much faster on big "
                "models. It is a test: keep a copy of your files and "
                "report anything odd with the label rust-engine. Takes "
                "effect at the next start."))
        form.addRow("", self._rust)
        tabs.addTab(general, tr("General"))

        # ---- 3D mouse (issue #108) -------------------------------------------
        from views.ndof_input import load_settings, shared_input
        nd = load_settings()
        mouse3d = QWidget()
        form = QFormLayout(mouse3d)
        self._ndof_on = QCheckBox(tr("Navigate with a 3D mouse (SpaceMouse)"))
        self._ndof_on.setChecked(nd.enabled)
        form.addRow("", self._ndof_on)
        self._ndof_speed = QSpinBox()
        self._ndof_speed.setRange(25, 400)
        self._ndof_speed.setSingleStep(25)
        self._ndof_speed.setSuffix(" %")
        self._ndof_speed.setValue(int(round(nd.sensitivity * 100)))
        form.addRow(tr("Speed:"), self._ndof_speed)
        # One box per movement (issue #108, a SpaceMouse user: «a
        # checkbox for each axis»); each shows what that axis does now,
        # the old pair switches included.
        self._ndof_inv = {}
        for key, label, on in (
                ("pan_x", tr("Invert pan left / right"),
                 nd.invert_pan != nd.invert_pan_x),
                ("pan_y", tr("Invert pan up / down"),
                 nd.invert_pan != nd.invert_pan_y),
                ("zoom", tr("Invert zoom"), nd.invert_zoom),
                ("tilt", tr("Invert orbit up / down (tilt)"),
                 nd.invert_rotate != nd.invert_tilt),
                ("spin", tr("Invert orbit around (spin)"),
                 nd.invert_rotate != nd.invert_spin)):
            box = QCheckBox(label)
            box.setChecked(on)
            form.addRow("", box)
            self._ndof_inv[key] = box
        self._ndof_lock = QCheckBox(tr(
            "Pan and zoom only (no rotation — for drawing in plan)"))
        self._ndof_lock.setChecked(nd.lock_rotation)
        form.addRow("", self._ndof_lock)
        name = shared_input().backend_name
        status = QLabel(
            tr("Device driver found: {name}", name=name) if name else tr(
                "No 3D mouse driver found. On Linux install and start "
                "«spacenavd»; on Windows the 3Dconnexion driver is enough. "
                "macOS is not supported yet."))
        status.setWordWrap(True)
        form.addRow("", status)
        # Live reading: nobody on the team has a device, so an owner can say
        # which number each move of the cap changes and which way IngeTrazo
        # takes it — one look settles a sign (#108, the 12-10 video).
        if name:
            hint = QLabel(tr("Live reading — move the cap one way at a time:"))
            hint.setWordWrap(True)
            form.addRow("", hint)
            self._ndof_raw = QLabel("—")
            self._ndof_read = QLabel("—")
            mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
            for lab in (self._ndof_raw, self._ndof_read):
                lab.setFont(mono)
                lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow("", lab)
            dev = shared_input()
            dev.raw.connect(self._show_ndof_raw)
            dev.motion.connect(self._show_ndof_read)
            # The device outlives the dialog: let go when it closes.
            self.finished.connect(self._drop_ndof_monitor)
        tabs.addTab(mouse3d, tr("3D Mouse"))

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
        self._api_key.setPlaceholderText(tr("empty = local AI (Ollama, LM Studio)"))
        form.addRow(tr("API key:"), self._api_key)

        self._model = QLineEdit(str(st.value("ia/modelo", "") or ""))
        self._model.setPlaceholderText(tr("model (default per provider)"))
        form.addRow(tr("Model:"), self._model)

        self._ollama = QLineEdit(str(st.value("ia/ollama_url",
                                              "http://localhost:11434") or ""))
        form.addRow(tr("Local AI URL:"), self._ollama)

        self._shots = QCheckBox(tr("Send viewport screenshots to the model"))
        self._shots.setChecked(str(st.value("ia/capturas", "1")) != "0")
        form.addRow("", self._shots)
        tabs.addTab(ia, tr("AI Assistant"))

        # ---- Units (of THIS document) ---------------------------------------
        # Issue #33 (@pacaeiro): «when doing architecture I work in meters
        # and with mechanical pieces all the work is in millimeters». The
        # unit a bare number is typed in and every readout shows. It is a
        # property of the document (it travels in the .igz), shown here
        # because this is where people look for it (Marco, 2026-09-21).
        from core import units as _units
        from views.units_panel import UnitsPanel
        scene = getattr(getattr(self._window, "viewport", None), "scene", None)
        current = _units.model_units_of(scene)
        # The units panel (profile, length, area, volume, angle, decimal
        # separator, preview): everything a readout is shown with. Its rows
        # and the ones below share one form, like the other pages.
        self._units_panel = UnitsPanel(current)
        form = self._units_panel.form
        # Issue #121: the choice used to live only in the open document, so
        # every new file went back to metres.
        self._units_for_new = QCheckBox(tr("Also use for new documents"))
        self._units_for_new.setChecked(
            _units.new_document_units() == current)
        form.addRow("", self._units_for_new)
        from views.units_start_dialog import ask_at_start
        self._units_at_start = QCheckBox(tr("Ask which units to use at startup"))
        self._units_at_start.setChecked(ask_at_start())
        form.addRow("", self._units_at_start)
        note = QLabel(tr(
            "These are the units of the document you have open — they are "
            "saved with it. A number typed without a unit is in this unit "
            "(«2» is 2 mm in a millimetre document; «2m» is always 2 m), and "
            "every length and area on screen is shown in it. The dimension "
            "style follows it; its own panel can still set it apart."))
        note.setWordWrap(True)
        from views.theme import style as theme_style
        theme_style(note, "color:{muted}; font-size:11px;")
        form.addRow("", note)
        un = QWidget()
        page = QVBoxLayout(un)
        page.addWidget(self._units_panel)
        page.addStretch(1)
        tabs.addTab(un, tr("Units"))
        self._units_page = un

        # ---- Keyboard shortcuts (issue #138) -------------------------------
        from views.shortcuts import ShortcutsPanel
        self._shortcuts = ShortcutsPanel(self._window)
        tabs.addTab(self._shortcuts, tr("Keyboard shortcuts"))
        self._tabs = tabs

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _drop_ndof_monitor(self, _result=0) -> None:
        from views.ndof_input import shared_input
        dev = shared_input()
        for sig, slot in ((dev.raw, self._show_ndof_raw),
                          (dev.motion, self._show_ndof_read)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _show_ndof_raw(self, values) -> None:
        names = ("X", "Y", "Z", "RX", "RY", "RZ")
        self._ndof_raw.setText(tr("Device:") + "  " + "  ".join(
            f"{n} {v:+5d}" for n, v in zip(names, values)))

    def _show_ndof_read(self, sample, _dt) -> None:
        self._ndof_read.setText(tr(
            "IngeTrazo: right {r:+.2f}  up {u:+.2f}  forward {f:+.2f}  "
            "tilt {t:+.2f}  twist {s:+.2f}", r=sample.right, u=sample.up,
            f=sample.forward, t=sample.tilt, s=sample.spin))

    def show_units_page(self) -> None:
        """Open on the Units page (Window ▸ Units…, Ctrl+U)."""
        self._tabs.setCurrentWidget(self._units_page)

    def show_shortcut_of(self, action) -> None:
        """Open on the Keyboard shortcuts page with ``action`` picked."""
        self._tabs.setCurrentWidget(self._shortcuts)
        self._shortcuts.pick(action)

    # ---- Apply --------------------------------------------------------------
    # ---- Scale figure of new documents (#655) ----------------------------

    def _build_figure_rows(self, form, st) -> None:
        """Which person stands in a new document: one of the bundled cutouts
        or the user's own picture (a PNG on a transparent background, and
        the height that person stands)."""
        from core import scale_figure as sf
        self._figure = QComboBox()
        for p in sf.people():
            icon = QIcon(str(sf.people_dir() / f"{p['key']}.png"))
            self._figure.addItem(
                icon, f"{tr(p['name'])} ({float(p['height']):.2f} m)",
                p["key"])
        self._figure.addItem(tr("My own picture…"), sf.CUSTOM)
        pick = str(st.value(sf.KEY_PICK, sf.DEFAULT_PICK) or sf.DEFAULT_PICK)
        self._figure.setCurrentIndex(max(0, self._figure.findData(pick)))
        form.addRow(tr("Scale figure:"), self._figure)

        # The user's own picture: what is stored, a new file only once OK
        # copies it into the data folder (Cancel leaves nothing behind).
        image = str(st.value(sf.KEY_IMAGE, "") or "")
        self._figure_image = image if Path(image).is_file() else ""
        self._figure_source = ""
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self._figure_pick_btn = QPushButton(tr("Choose picture…"))
        self._figure_pick_btn.clicked.connect(self._choose_figure_picture)
        self._figure_height = QDoubleSpinBox()
        self._figure_height.setRange(sf.MIN_HEIGHT, sf.MAX_HEIGHT)
        self._figure_height.setDecimals(2)
        self._figure_height.setSingleStep(0.01)
        self._figure_height.setSuffix(" m")
        self._figure_height.setToolTip(tr("The height this person stands"))
        try:
            self._figure_height.setValue(float(st.value(sf.KEY_HEIGHT, 1.70)))
        except (TypeError, ValueError):
            self._figure_height.setValue(1.70)
        self._figure_name = QLineEdit(str(st.value(sf.KEY_NAME, "") or ""))
        self._figure_name.setPlaceholderText(tr("Name"))
        lay.addWidget(self._figure_pick_btn)
        lay.addWidget(self._figure_height)
        lay.addWidget(self._figure_name, 1)
        self._figure_custom_row = row
        form.addRow("", row)
        self._figure_file_label = QLabel()
        self._figure_file_label.setWordWrap(True)
        form.addRow("", self._figure_file_label)

        self._figure.currentIndexChanged.connect(self._on_figure_pick)
        self._scale_figure.toggled.connect(self._sync_figure_rows)
        self._figure_last = self._figure.currentIndex()
        self._sync_figure_rows()

    def _figure_is_custom(self) -> bool:
        from core import scale_figure as sf
        return self._figure.currentData() == sf.CUSTOM

    def _sync_figure_rows(self) -> None:
        on = self._scale_figure.isChecked()
        custom = self._figure_is_custom()
        self._figure.setEnabled(on)
        self._figure_custom_row.setVisible(custom)
        self._figure_custom_row.setEnabled(on)
        shown = self._figure_source or self._figure_image
        self._figure_file_label.setVisible(custom and bool(shown))
        if shown:
            self._figure_file_label.setText(
                "<small>" + Path(shown).name + "</small>")

    def _on_figure_pick(self, _index: int) -> None:
        # «My own picture…» with none chosen yet asks for one at once; a
        # cancelled dialog goes back to the person shown before.
        if (self._figure_is_custom() and not self._figure_image
                and not self._figure_source
                and not self._choose_figure_picture()):
            self._figure.blockSignals(True)
            self._figure.setCurrentIndex(self._figure_last)
            self._figure.blockSignals(False)
        self._figure_last = self._figure.currentIndex()
        self._sync_figure_rows()

    def _choose_figure_picture(self) -> bool:
        from views.filedialogs import file_dialogs as fd
        path, _ = fd.getOpenFileName(
            self, tr("Choose the picture of your scale figure"), "",
            tr("Images") + " (*.png *.webp);;" + tr("All files") + " (*)")
        if not path:
            return False
        from PySide6.QtGui import QImage
        img = QImage(path)
        if img.isNull() or img.height() == 0:
            QMessageBox.warning(self, tr("Scale figure"),
                                tr("That file is not a picture IngeTrazo can read."))
            return False
        if not img.hasAlphaChannel():
            QMessageBox.information(
                self, tr("Scale figure"),
                tr("This picture has no transparent background, so it will "
                   "show as a rectangle. A PNG cut out around the person "
                   "looks best."))
        self._figure_source = path
        if not self._figure_name.text().strip():
            self._figure_name.setText(Path(path).stem.replace("_", " "))
        self._sync_figure_rows()
        return True

    def _save_figure(self, st) -> None:
        from core import scale_figure as sf
        pick = self._figure.currentData()
        if pick == sf.CUSTOM and self._figure_source:
            try:
                self._figure_image = str(sf.store_picture(self._figure_source))
            except (OSError, ValueError):
                QMessageBox.warning(
                    self, tr("Scale figure"),
                    tr("The picture could not be copied; the previous "
                       "figure is kept."))
                return
        if pick == sf.CUSTOM and not self._figure_image:
            return
        st.setValue(sf.KEY_PICK, pick)
        if pick == sf.CUSTOM:
            st.setValue(sf.KEY_IMAGE, self._figure_image)
            st.setValue(sf.KEY_HEIGHT, round(self._figure_height.value(), 3))
            st.setValue(sf.KEY_NAME, self._figure_name.text().strip())

    def accept(self) -> None:  # noqa: D102 — QDialog override
        st = QSettings()

        # Units of the open document (issue #33).
        from core import units as _units
        scene = getattr(getattr(self._window, "viewport", None), "scene", None)
        chosen = self._units_panel.settings()
        if scene is not None and chosen != _units.model_units_of(scene):
            _units.apply_units(scene, chosen)
            scene.version += 1
            self._window.viewport.update()
        if self._units_for_new.isChecked():
            _units.remember_new_document_units(chosen)
        from views.units_start_dialog import set_ask_at_start
        set_ask_at_start(self._units_at_start.isChecked())

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

        # Theme: applies at once (a no-op re-apply is cheap).
        from views.theme import apply_theme, save_theme, saved_theme
        theme = self._theme.currentData()
        if theme != saved_theme():
            save_theme(theme)
            from PySide6.QtWidgets import QApplication
            apply_theme(QApplication.instance(), theme)

        from views.theme import apply_accent, save_accent, saved_accent
        accent = self._accent.currentData()
        if accent != saved_accent():
            save_accent(accent)
            from PySide6.QtWidgets import QApplication
            apply_accent(QApplication.instance())

        # Rest-of-model mode: through the viewport (it persists the setting),
        # then the Camera menu checkmark follows.
        mode = self._rest.currentData()
        if mode != self._window.viewport.edit_rest_mode:
            self._window.viewport.set_edit_rest_mode(mode)
            act = getattr(self._window, "_rest_actions", {}).get(mode)
            if act is not None:
                act.setChecked(True)

        _gs.set_value("autosave", "1" if self._autosave.isChecked() else "0",
                      st)
        _gs.set_value("autosave_min", self._autosave_min.value(), st)
        _gs.set_value("backup", "1" if self._backup.isChecked() else "0", st)
        st.setValue("section/ask_name",
                    "1" if self._ask_section.isChecked() else "0")
        st.setValue("new_document/scale_figure",
                    "1" if self._scale_figure.isChecked() else "0")
        self._save_figure(st)
        _gs.set_value("undo_steps", int(self._undo_steps.value()), st)
        history = getattr(getattr(self._window, "viewport", None), "history", None)
        if history is not None:
            history.max_steps = int(self._undo_steps.value())
        _gs.set_value("platform", self._platform.currentData(), st)
        rust = "1" if self._rust.isChecked() else "0"
        if self._rust.isEnabled() and rust != str(
                _gs.value(_native.SETTING, "0", st)):
            _gs.set_value(_native.SETTING, rust, st)
            QMessageBox.information(
                self, tr("Rust engine (experimental)"),
                tr("Restart IngeTrazo to switch the engine."))
        setup = getattr(self._window, "_setup_autosave", None)
        if callable(setup):
            setup()                     # re-arm the timer with the new pace

        from core.ndof import NdofSettings
        from views.ndof_input import save_settings
        inv = {k: b.isChecked() for k, b in self._ndof_inv.items()}
        # Saved per axis; the old pair switches go back to off.
        nd = NdofSettings(enabled=self._ndof_on.isChecked(),
                          sensitivity=self._ndof_speed.value() / 100.0,
                          invert_pan=False,
                          invert_zoom=inv["zoom"],
                          invert_rotate=False,
                          invert_pan_x=inv["pan_x"],
                          invert_pan_y=inv["pan_y"],
                          invert_tilt=inv["tilt"],
                          invert_spin=inv["spin"],
                          lock_rotation=self._ndof_lock.isChecked())
        save_settings(nd)                # every window reads it live

        st.setValue("nav/invert_wheel",
                    "1" if self._invert.isChecked() else "0")
        self._window.viewport._invert_wheel = self._invert.isChecked()

        st.setValue("nav/invert_orbit_y",
                    "1" if self._invert_orbit.isChecked() else "0")
        self._window.viewport._invert_orbit_y = self._invert_orbit.isChecked()

        # First Person reads it on every look move: nothing to push.
        st.setValue("walk/look_sensitivity", int(self._look_sens.value()))

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

        px = int(self._icon_px.currentData())
        from views.icons import toolbar_icon_px
        if px != toolbar_icon_px():
            apply_px = getattr(self._window, "set_toolbar_icon_size", None)
            if callable(apply_px):
                apply_px(px)             # persists and resizes every toolbar
            else:
                from views.icons import save_toolbar_icon_px
                save_toolbar_icon_px(px)

        st.setValue("import/obj_unit", self._obj_unit.currentData())
        st.setValue("import/dxf_unit", self._dxf_unit.currentData())
        st.setValue("georef/coord_mode", self._coord.currentData())

        st.setValue("ia/proveedor", self._provider.currentData())
        st.setValue("ia/api_key", self._api_key.text())
        st.setValue("ia/modelo", self._model.text().strip())
        st.setValue("ia/ollama_url", self._ollama.text().strip())
        st.setValue("ia/capturas", "1" if self._shots.isChecked() else "0")
        st.sync()
        panel = getattr(self._window, "_ai_assistant", None)
        if panel is not None:          # the AI tab lives on: show the change
            panel._load_settings()
        super().accept()
