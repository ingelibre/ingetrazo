# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The units to work in, asked once when IngeTrazo starts.

Three ready configurations — metres (m, m², m³, degrees), millimetres and
imperial feet-and-inches — or Custom…, which takes the user to the units
panel (Preferences ▸ Units) to pick each one; so the first thing drawn is
already in the right unit. The choice applies to the new document and to every new one
after it. «Don't show this at startup» turns the question off; Preferences
▸ Units turns it back on, and Ctrl+U opens the full panel any time.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog,
                               QDialogButtonBox, QLabel, QRadioButton,
                               QVBoxLayout)

from core import units
from core.i18n import tr

#: QSettings key: "0" once the user asked not to see the dialog again.
ASK_KEY = "units/ask_at_start"

#: The three configurations, in the order shown: (profile, title, what
#: it sets). Everything else follows the length (areas in its square,
#: volumes in its cube) and angles are degrees.
CHOICES = (
    ("metric", "Metres", "m · m² · m³ · °"),
    ("millimetric", "Millimetres", "mm · mm² · cm³ · °"),
    ("imperial", "Imperial (feet and inches)", "ft-in, 1/16\" · ft² · ft³ · °"),
)


def ask_at_start() -> bool:
    return str(QSettings().value(ASK_KEY, "1")) != "0"


def set_ask_at_start(ask: bool) -> None:
    st = QSettings()
    st.setValue(ASK_KEY, "1" if ask else "0")
    st.sync()


class UnitsStartDialog(QDialog):
    """Pick one of :data:`CHOICES`; ``settings()`` is the result."""

    def __init__(self, parent=None, current: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Units"))
        self.setMinimumWidth(480)
        self._current = units.model_units_of(
            {"units": current or units.new_document_units()})
        root = QVBoxLayout(self)
        intro = QLabel(tr(
            "Which units do you work in? Lengths, areas, volumes and angles "
            "will be shown and typed in them. You can change this at any "
            "time in Preferences ▸ Units (Ctrl+U)."))
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.group = QButtonGroup(self)
        self.buttons = {}
        picked = units.profile_of(self._current)
        for name, title, detail in CHOICES:
            btn = QRadioButton(f"{tr(title)}   —   {detail}")
            btn.setProperty("profile", name)
            self.group.addButton(btn)
            self.buttons[name] = btn
            root.addWidget(btn)
        # Custom…: OK takes the user to the units panel, to pick each unit
        # and its precision (an own mix of an earlier start shows there).
        btn = QRadioButton(tr("Custom…"))
        btn.setProperty("profile", "custom")
        btn.setToolTip(tr("Opens the units panel to choose each unit"))
        self.group.addButton(btn)
        self.buttons["custom"] = btn
        root.addWidget(btn)
        self.buttons[picked].setChecked(True)

        self.preview = QLabel()
        self.preview.setObjectName("unitsStartPreview")
        from views.theme import style as theme_style
        theme_style(self.preview, "color:{muted}; margin: 6px 0 6px 22px;")
        root.addWidget(self.preview)
        self.group.buttonToggled.connect(lambda *_: self._refresh())

        self.dont_ask = QCheckBox(tr("Don't show this at startup"))
        self.dont_ask.setToolTip(tr(
            "Preferences ▸ Units can show it again."))
        root.addWidget(self.dont_ask)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)
        self._refresh()

    def profile(self) -> str:
        btn = self.group.checkedButton()
        return btn.property("profile") if btn is not None else "metric"

    def settings(self) -> dict:
        """The settings picked; for Custom, the current ones (the units
        panel opened next is where they change)."""
        name = self.profile()
        if name == "custom":
            return dict(self._current)
        return units.with_profile(self._current, name)

    def _refresh(self) -> None:
        from views.units_panel import UnitsPanel
        self.preview.setText(UnitsPanel.preview_text(self.settings()))


def offer_at_start(window) -> dict | None:
    """Ask, if the user has not turned it off; apply the answer to the
    window's (new, empty) document and remember it for new documents.
    Returns the settings chosen, or None when nothing was asked."""
    if not ask_at_start():
        return None
    dlg = UnitsStartDialog(window)
    accepted = dlg.exec() == QDialog.Accepted
    if dlg.dont_ask.isChecked():
        set_ask_at_start(False)
    chosen = dlg.settings() if accepted else None
    custom = accepted and dlg.profile() == "custom"
    dlg.deleteLater()
    if custom:
        return open_units_panel(window)
    if chosen is None:
        return None
    units.remember_new_document_units(chosen)
    scene = window.viewport.scene
    if chosen != units.model_units_of(scene):
        # Not an edit of the document: nothing to save yet.
        units.apply_units(scene, chosen)
        window.viewport.update()
    return chosen


def open_units_panel(window) -> dict | None:
    """Custom…: Preferences on its Units page, with «Also use for new
    documents» ticked — what is picked there is what this start chose.
    Returns the document's units after it, or None when cancelled."""
    from views.preferences_dialog import PreferencesDialog
    scene = window.viewport.scene
    untouched = scene.version == getattr(window, "_saved_version", None)
    prefs = PreferencesDialog(window)
    prefs.show_units_page()
    prefs._units_for_new.setChecked(True)
    accepted = prefs.exec() == QDialog.Accepted
    prefs.deleteLater()
    if not accepted:
        return None
    if untouched:
        # Choosing the units of an empty new document is not an edit:
        # nothing to save yet, as with the three ready choices.
        window._saved_version = scene.version
        update_title = getattr(window, "_update_title", None)
        if callable(update_title):
            update_title()
    return units.model_units_of(scene)
