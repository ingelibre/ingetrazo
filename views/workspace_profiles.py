# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ibrahim Halim Gokbulut (h-skycloud).
"""Opt-in layouts over the existing docks/actions; no command IDs change."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QActionGroup

from core.i18n import tr

PROFILES = {
    "original": "Original IngeTrazo",
    "cad": "CAD / Technical Drawing",
    "bim": "BIM / Building Modeling",
    "simple": "Easy 3D Modeling",
}
_BARS = {
    "cad": {"main", "draw", "modify", "annotate", "sections", "view", "layers"},
    "bim": {"main", "draw", "modify", "annotate", "sections", "solids", "view", "layers"},
    "simple": {"main", "draw", "modify", "view"},
}
_PANELS = {
    "cad": {"tray_properties", "tray_layers"},
    "bim": {"tray_bim", "tray_project_browser", "tray_layers"},
    "simple": {"tray_properties"},
}


class WorkspaceProfiles:
    def __init__(self, window, menu) -> None:
        self.window = window
        self.menu = menu
        self.current = str(QSettings().value("workspace_profiles/current", "original"))
        self.enabled = (QSettings().contains("workspace_profiles/current")
                        and self.current in PROFILES)
        if self.current not in PROFILES:
            self.current = "original"
        self.group = QActionGroup(window)
        self.actions = {}
        for key, label in PROFILES.items():
            action = menu.addAction(tr(label))
            action.setObjectName("workspace_profile_" + key)
            action.setCheckable(True)
            action.setChecked(key == self.current)
            action.triggered.connect(lambda _on=False, k=key: self.apply(k))
            self.group.addAction(action)
            self.actions[key] = action
        menu.addSeparator()
        intro = menu.addAction(tr("Getting started"))
        intro.setObjectName("workspace_getting_started")
        intro.triggered.connect(lambda: show_intro(window))

    def save(self) -> None:
        if not self.enabled:
            return
        st = QSettings()
        prefix = "workspace_profiles/" + self.current
        st.setValue(prefix + "/state", self.window.saveState())
        hidden = [d.objectName() for d in self.window._sidebar_docks() if d.isHidden()]
        st.setValue(prefix + "/hidden", hidden)
        st.setValue("ui/hidden_trays", hidden)
        for side, action, remembered in (
                ("right", self.window._act_sidebar, "_sidebar_was"),
                ("left", self.window._act_left_sidebar, "_left_was")):
            st.setValue(prefix + "/" + side, action.isChecked())
            st.setValue(prefix + "/" + side + "_was",
                        [d.objectName() for d in getattr(self.window, remembered, ())])
        st.setValue("workspace_profiles/current", self.current)

    def restore_controls(self, fresh: bool = False) -> None:
        """Restore fold buttons and their remembered panels, not just Qt's blob."""
        from views.icons import tool_icon
        st, win = QSettings(), self.window
        prefix = "workspace_profiles/" + self.current
        if not self.enabled:
            return
        if not fresh and not st.contains(prefix + "/state"):
            return
        docks = {d.objectName(): d for d in win._sidebar_docks()}
        for side, action, remembered, handle in (
                ("right", win._act_sidebar, "_sidebar_was", win._sidebar_handle),
                ("left", win._act_left_sidebar, "_left_was", win._left_handle)):
            on = st.value(prefix + "/" + side, True, type=bool)
            names = st.value(prefix + "/" + side + "_was", []) or []
            if isinstance(names, str):
                names = [names]
            setattr(win, remembered, [docks[n] for n in names if n in docks])
            action.blockSignals(True)
            action.setChecked(on)
            action.blockSignals(False)
            key = "side_collapse" if on else "side_expand"
            if side == "left":
                key = "side_expand" if on else "side_collapse"
            handle.setIcon(tool_icon(key))
            win._icon_actions = [(a, key if a is handle else k)
                                 for a, k in win._icon_actions]
            if not on:
                area = Qt.LeftDockWidgetArea if side == "left" else Qt.RightDockWidgetArea
                for dock in win._side_docks(area):
                    dock.hide()
        win._place_sidebar_handle()

    def apply(self, key: str) -> None:
        if key not in PROFILES:
            raise ValueError(key)
        if key == self.current:
            return
        win = self.window
        if win._act_clean_screen.isChecked():
            win._act_clean_screen.setChecked(False)
        self.enabled = True
        self.save()
        st = QSettings()
        prefix = "workspace_profiles/" + key
        saved = st.value(prefix + "/state")
        if saved is not None:
            win.restoreState(saved)
            hidden = st.value(prefix + "/hidden", []) or []
            if isinstance(hidden, str):
                hidden = [hidden]
            for dock in win._sidebar_docks():
                dock.setVisible(dock.objectName() not in hidden)
        elif key != "original":
            # Existing extension panels/toolbars are left to their owners.
            for name, bar in win.toolbars.items():
                bar.setVisible(name in _BARS[key])
            for dock in win._default_tray_order():
                dock.setVisible(dock.objectName() in _PANELS[key])
            if key == "bim":
                win.bim_tray.show()
                win.bim_tray.raise_()
                win.resizeDocks([win.bim_tray], [490], Qt.Horizontal)
            elif key == "cad":
                win.layers_dock.show()
                win.layers_dock.raise_()
            else:
                win.tray.raise_()
        else:
            win.restore_default_toolbars()
            win.restore_default_trays()
        # Keep the existing panel-persistence mechanism authoritative.
        hidden = [d.objectName() for d in win._sidebar_docks() if d.isHidden()]
        st.setValue("ui/hidden_trays", hidden)
        self.current = key
        self.restore_controls(fresh=True)
        self.actions[key].setChecked(True)
        self.save()
        st.setValue("ui/window_state", win.saveState())
        win._toolbar_wrap_timer.start()


def show_intro(window) -> None:
    """A skippable guide. It changes layout/units only on explicit Apply."""
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                                   QDialogButtonBox, QLabel, QVBoxLayout)
    from core.units import remember_new_document_units

    dialog = QDialog(window)
    dialog.setWindowTitle(tr("Getting started"))
    dialog.setMinimumWidth(540)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(14)
    title = QLabel(tr("Choose a workspace"))
    font = title.font()
    font.setPointSize(font.pointSize() + 3)
    font.setBold(True)
    title.setFont(font)
    layout.addWidget(title)
    description = QLabel(tr("Switch workspaces from Window at any time. Your original layout stays available."))
    description.setWordWrap(True)
    layout.addWidget(description)
    picker = QComboBox(dialog)
    picker.setAccessibleName(tr("Workspace"))
    for key, label in PROFILES.items():
        picker.addItem(tr(label), key)
    picker.setCurrentIndex(picker.findData(window.workspace_profiles.current))
    layout.addWidget(picker)
    metric = QCheckBox(tr("Use metres and decimal comma for new documents"))
    metric.setToolTip(tr("Existing documents keep their units. Change this later in Preferences > Units."))
    layout.addWidget(metric)
    heading = QLabel(tr("Five-minute project"))
    heading.setFont(font)
    layout.addWidget(heading)
    steps = QLabel(tr(
        "1. Draw a rectangle with Rectangle.\n"
        "2. Give it height with Push / Pull.\n"
        "3. Select the solid, open the BIM panel and tag it as IfcWall or IfcSlab.\n"
        "4. Check its area and closed-solid volume in the takeoff table.\n"
        "5. Use the IFC export command in File to export the tagged model.\n\n"
        "Press F3 to find commands in Turkish or English. Shortcuts stay unchanged."))
    steps.setWordWrap(True)
    steps.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(steps)
    buttons = QDialogButtonBox(dialog)
    buttons.addButton(tr("Apply workspace"), QDialogButtonBox.AcceptRole)
    buttons.addButton(tr("Skip"), QDialogButtonBox.RejectRole)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.Accepted:
        window.workspace_profiles.apply(picker.currentData())
        if metric.isChecked():
            remember_new_document_units({"length": "m", "precision": 2, "decimal": ","})
    QSettings().setValue("workspace_profiles/intro_seen", True)


def offer_intro(window) -> bool:
    from core.i18n import current_language
    st = QSettings()
    if current_language() != "tr" or st.value("workspace_profiles/intro_seen", False, type=bool):
        return False
    show_intro(window)
    return True
