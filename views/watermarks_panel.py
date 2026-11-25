# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Live image-layer editor used by the Styles window."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSlider,
    QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from core.i18n import tr
from core.watermark import Watermark
from views.filedialogs import file_dialogs
from views.icons import tool_icon
from views.watermarks import import_image, watermark_image


class WatermarksPanel(QWidget):
    _MODEL_SPACE = object()  # A UI boundary, never an image in the saved style.

    def __init__(self, style_provider, changed, parent=None):
        super().__init__(parent)
        self._style = style_provider
        self._changed = changed
        self._updating = False
        self._signature = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.display = QCheckBox(tr("Display watermarks"))
        self.display.toggled.connect(self._toggle_display)
        layout.addWidget(self.display)
        self.images = QListWidget()
        self.images.setIconSize(QSize(36, 28))
        self.images.setMinimumHeight(80)
        self.images.setMaximumHeight(120)
        self.images.currentRowChanged.connect(self._select)
        layout.addWidget(self.images)
        buttons = QHBoxLayout()
        self.add = QPushButton(tr("Add image…"))
        self.add.clicked.connect(self._choose_image)
        self.remove = QPushButton(tr("Delete"))
        self.remove.clicked.connect(self._remove)
        buttons.addWidget(self.add, 1)
        buttons.addWidget(self.remove)
        self.up = QToolButton()
        self.up.setText("↑")
        self.up.setToolTip(tr("Move up"))
        self.up.clicked.connect(lambda: self._move(-1))
        self.down = QToolButton()
        self.down.setText("↓")
        self.down.setToolTip(tr("Move down"))
        self.down.clicked.connect(lambda: self._move(1))
        buttons.addWidget(self.up)
        buttons.addWidget(self.down)
        layout.addLayout(buttons)

        self.options = QWidget()
        form = QGridLayout(self.options)
        form.setContentsMargins(0, 4, 0, 0)
        form.setColumnStretch(1, 1)
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._apply)
        form.addWidget(QLabel(tr("Name:")), 0, 0)
        form.addWidget(self.name, 0, 1)
        self.visible = QCheckBox(tr("Visible"))
        self.visible.toggled.connect(self._apply)
        form.addWidget(self.visible, 1, 0, 1, 2)
        self.layer = QComboBox()
        self.layer.addItem(tr("In front of model"), "foreground")
        self.layer.addItem(tr("Behind model"), "background")
        self.layer.currentIndexChanged.connect(self._apply)
        form.addWidget(QLabel(tr("Layer:")), 2, 0)
        form.addWidget(self.layer, 2, 1)
        self.placement = QComboBox()
        self.placement.addItem(tr("Positioned"), "positioned")
        self.placement.addItem(tr("Stretched"), "stretched")
        self.placement.addItem(tr("Tiled"), "tiled")
        self.placement.currentIndexChanged.connect(self._apply)
        form.addWidget(QLabel(tr("Placement:")), 3, 0)
        form.addWidget(self.placement, 3, 1)
        opacity_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix(" %")
        self.opacity_slider.setAccessibleName(tr("Opacity:"))
        self.opacity.setAccessibleName(tr("Opacity:"))
        self.opacity_slider.valueChanged.connect(self.opacity.setValue)
        self.opacity.valueChanged.connect(self.opacity_slider.setValue)
        self.opacity.valueChanged.connect(self._apply)
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity)
        form.addWidget(QLabel(tr("Opacity:")), 4, 0)
        form.addLayout(opacity_row, 4, 1)
        self.scale_label = QLabel(tr("Scale:"))
        self.scale = QSpinBox()
        self.scale.setRange(1, 200)
        self.scale.setSuffix(" %")
        self.scale.valueChanged.connect(self._apply)
        form.addWidget(self.scale_label, 5, 0)
        form.addWidget(self.scale, 5, 1)
        self.anchor_label = QLabel(tr("Position:"))
        self.anchor = QComboBox()
        for label in (tr("Top left"), tr("Top center"), tr("Top right"),
                      tr("Middle left"), tr("Center"), tr("Middle right"),
                      tr("Bottom left"), tr("Bottom center"), tr("Bottom right")):
            self.anchor.addItem(label)
        self.anchor.currentIndexChanged.connect(self._apply)
        form.addWidget(self.anchor_label, 6, 0)
        form.addWidget(self.anchor, 6, 1)
        self.keep_aspect = QCheckBox(tr("Keep aspect ratio"))
        self.keep_aspect.toggled.connect(self._apply)
        form.addWidget(self.keep_aspect, 7, 0, 1, 2)
        self.create_mask = QCheckBox(tr("Create mask"))
        self.create_mask.setToolTip(tr(
            "White becomes transparent; black uses the style's background color. "
            "Gray gives partial transparency. The original image is preserved."))
        self.create_mask.toggled.connect(self._apply)
        form.addWidget(self.create_mask, 8, 0, 1, 2)
        layout.addWidget(self.options)
        layout.addStretch(1)

    def _selected(self):
        item = self.images.currentItem()
        style = self._style()
        if item is None or style is None:
            return None
        return next((mark for mark in style.watermarks
                     if mark.id == item.data(Qt.UserRole)), None)

    def _selection_key(self):
        item = self.images.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole) or self._MODEL_SPACE

    def _stack(self):
        marks = self._style().watermarks
        return ([mark for mark in marks if mark.layer == "foreground"] + [None]
                + [mark for mark in marks if mark.layer == "background"])

    def refresh(self, selected_id=None):
        style = self._style()
        if style is None:
            return
        selected_id = selected_id or self._selection_key()
        previous_row = self.images.currentRow()
        self._updating = True
        try:
            self.display.setChecked(style.watermarks_visible)
            signature = (tuple((m.id, m.name, m.image, m.visible, m.layer)
                               for m in style.watermarks), self.palette().cacheKey())
            if signature != self._signature:
                self._signature = signature
                self.images.clear()
                for mark in self._stack():
                    if mark is None:
                        item = QListWidgetItem(tool_icon("view_iso"), tr("Model space"))
                        item.setToolTip(tr(
                            "Images above this row appear in front of the model; "
                            "images below stay behind it."))
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        item.setBackground(self.palette().midlight())
                        item.setSizeHint(QSize(0, 32))
                        self.images.addItem(item)
                        continue
                    pixmap = QPixmap.fromImage(watermark_image(mark.image)).scaled(
                        36, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    item = QListWidgetItem(QIcon(pixmap), mark.name)
                    item.setData(Qt.UserRole, mark.id)
                    self.images.addItem(item)
                self.images.setCurrentRow(max(0, min(previous_row, self.images.count() - 1)))
            if selected_id:
                for index in range(self.images.count()):
                    key = self.images.item(index).data(Qt.UserRole) or self._MODEL_SPACE
                    if key == selected_id:
                        self.images.setCurrentRow(index)
                        break
        finally:
            self._updating = False
        self._select()

    def _select(self, *_args):
        if self._updating:
            return
        mark = self._selected()
        self._updating = True
        try:
            self.options.setEnabled(mark is not None)
            self.remove.setEnabled(mark is not None)
            row = self.images.currentRow()
            self.up.setEnabled(row > 0)
            self.down.setEnabled(0 <= row < self.images.count() - 1)
            if mark is None:
                self.name.clear()
                return
            self.name.setText(mark.name)
            self.visible.setChecked(mark.visible)
            self.layer.setCurrentIndex(self.layer.findData(mark.layer))
            self.placement.setCurrentIndex(self.placement.findData(mark.placement))
            self.opacity.setValue(mark.opacity)
            self.scale.setValue(mark.scale)
            self.anchor.setCurrentIndex(mark.anchor)
            self.keep_aspect.setChecked(mark.keep_aspect)
            self.create_mask.setChecked(mark.create_mask)
            positioned = mark.placement == "positioned"
            for widget in (self.anchor_label, self.anchor):
                widget.setEnabled(positioned)
            for widget in (self.scale_label, self.scale):
                widget.setEnabled(mark.placement != "stretched")
            self.keep_aspect.setEnabled(mark.placement == "stretched")
        finally:
            self._updating = False

    def _toggle_display(self, visible):
        if not self._updating and self._style() is not None:
            self._style().watermarks_visible = visible
            self._changed()

    def _choose_image(self):
        path, _filter = file_dialogs.getOpenFileName(
            self, tr("Add image…"), "",
            tr("Images (*.png *.jpg *.jpeg *.bmp *.webp)"))
        if path:
            self.add_image(path)

    def add_image(self, path: str) -> bool:
        try:
            mark = Watermark.create(Path(path).stem, import_image(path))
        except (ValueError, OSError):
            QMessageBox.warning(self, tr("Watermark settings"),
                                tr("The selected file could not be read as an image."))
            return False
        self._style().watermarks.insert(0, mark)
        self.refresh(mark.id)
        self._changed()
        return True

    def _apply(self, *_args):
        if self._updating:
            return
        mark = self._selected()
        if mark is None:
            return
        updated = replace(mark, name=self.name.text(), visible=self.visible.isChecked(),
                          layer=self.layer.currentData(), placement=self.placement.currentData(),
                          anchor=self.anchor.currentIndex(), scale=self.scale.value(),
                          opacity=self.opacity.value(), keep_aspect=self.keep_aspect.isChecked(),
                          create_mask=self.create_mask.isChecked())
        style = self._style()
        style.watermarks[style.watermarks.index(mark)] = updated
        self.refresh(mark.id)
        self._changed()

    def _remove(self):
        mark = self._selected()
        if mark is not None:
            self._style().watermarks.remove(mark)
            self.refresh()
            self._changed()

    def _move(self, delta):
        selected = self._selection_key()
        if selected is None:
            return
        stack = self._stack()
        index = self.images.currentRow()
        other = index + delta
        if 0 <= other < len(stack):
            stack[index], stack[other] = stack[other], stack[index]
            model_index = stack.index(None)
            self._style().watermarks = [
                replace(mark, layer="foreground" if row < model_index else "background")
                for row, mark in enumerate(stack) if mark is not None]
            self.refresh(selected)
            self._changed()
