# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Style colors and visibility of the modeling aids."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QLabel, QPushButton, QWidget
from PySide6.QtGui import QColor

from core.i18n import tr
from core.modeling_style import modeling_color, set_modeling_visibility
from views.color_dialog import get_color


class ModelingPanel(QWidget):
    def __init__(self, scene_provider, changed, parent=None):
        super().__init__(parent)
        self._scene = scene_provider
        self._changed = changed
        self._updating = False
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        self.colors = {}
        for key, label, row, col in (
                ("selected", tr("Selected"), 0, 0),
                ("locked", tr("Locked"), 1, 0),
                ("guides", tr("Guides"), 2, 0),
                ("section_inactive", tr("Inactive section"), 0, 2),
                ("section_active", tr("Active section"), 1, 2),
                ("section_cut", tr("Section cuts"), 2, 2)):
            text = QLabel(label)
            text.setWordWrap(True)
            grid.addWidget(text, row, col)
            button = QPushButton()
            button.setAutoDefault(False)
            button.setFixedSize(36, 24)
            button.setToolTip(label)
            if key == "locked":
                button.setToolTip(tr("Color of the selection outline for locked objects."))
            button.setAccessibleName(label)
            button.clicked.connect(lambda _checked=False, key=key: self._pick_color(key))
            self.colors[key] = button
            grid.addWidget(button, row, col + 1)
        grid.addWidget(QLabel(tr("Section cut width:")), 3, 0, 1, 2)
        self.cut_width = QDoubleSpinBox()
        self.cut_width.setRange(1, 20)
        self.cut_width.setDecimals(1)
        self.cut_width.setSingleStep(0.5)
        self.cut_width.setSuffix(tr(" px"))
        self.cut_width.valueChanged.connect(self._apply)
        grid.addWidget(self.cut_width, 3, 2, 1, 2)
        self.visibility = {}
        for index, (key, label) in enumerate((
                ("show_hidden_geometry", tr("Hidden Geometry")),
                ("show_section_planes", tr("Section Planes")),
                ("color_by_layer", tr("Color by layer")),
                ("show_section_cuts", tr("Section Cuts")),
                ("show_guides", tr("Guides")),
                ("show_axes", tr("Model axes")))):
            check = QCheckBox(label)
            check.toggled.connect(self._apply)
            self.visibility[key] = check
            grid.addWidget(check, 4 + index // 2, (index % 2) * 2, 1, 2)

    def refresh(self):
        scene = self._scene()
        style = scene.display_style
        self._updating = True
        try:
            for key, button in self.colors.items():
                fallback = style.edge_color if key == "section_cut" else None
                color = modeling_color(style, key, fallback)
                rgb = ",".join(str(round(c * 255)) for c in color)
                button.setStyleSheet(f"QPushButton {{ background: rgb({rgb}); }}")
            self.cut_width.setValue(style.section_cut_width)
            for key, check in self.visibility.items():
                owner = style if key in ("show_guides", "color_by_layer") else scene
                check.setChecked(bool(getattr(owner, key)))
        finally:
            self._updating = False

    def _apply(self, *_args):
        if self._updating:
            return
        scene = self._scene()
        style = scene.display_style
        style.section_cut_width = self.cut_width.value()
        style.color_by_layer = self.visibility["color_by_layer"].isChecked()
        guides = self.visibility["show_guides"].isChecked()
        if guides != style.show_guides:
            style.show_guides = guides
            if not guides:
                for guide in scene.guides:
                    scene.selection.discard(guide)
            scene.version += 1
        for key, check in self.visibility.items():
            if key not in ("show_guides", "color_by_layer"):
                set_modeling_visibility(scene, key, check.isChecked())
        self._changed()

    def _pick_color(self, key):
        scene = self._scene()
        color = modeling_color(scene.display_style, key,
                               scene.display_style.edge_color if key == "section_cut" else None)
        chosen = get_color(QColor.fromRgbF(*color), self, self.colors[key].toolTip())
        if chosen.isValid():
            scene.display_style.modeling_colors[key] = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._changed()
