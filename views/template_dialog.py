# SPDX-License-Identifier: GPL-3.0-or-later
"""File > Save As Template: the dialog, laid out like SketchUp's (Name,
Description, File, "Set as default template")."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLineEdit, QPlainTextEdit,
                               QVBoxLayout)

from core.i18n import tr


class SaveTemplateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Save As Template"))
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setModal(True)
        self.setMinimumWidth(430)
        self._file_touched = False

        self._name = QLineEdit()
        self._desc = QPlainTextEdit()
        self._desc.setTabChangesFocus(True)
        self._desc.setFixedHeight(92)
        self._file = QLineEdit()
        self._default = QCheckBox(tr("Set as default template"))
        self._default.setChecked(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.addRow(tr("Name:"), self._name)
        form.addRow(tr("Description:"), self._desc)
        form.addRow(tr("File:"), self._file)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                               | QDialogButtonBox.StandardButton.Cancel)
        self._ok = box.button(QDialogButtonBox.StandardButton.Save)
        self._ok.setText(tr("Save"))
        self._ok.setDefault(True)
        self._ok.setEnabled(False)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(
            tr("Cancel"))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 14)
        lay.setSpacing(12)
        lay.addLayout(form)
        lay.addWidget(self._default)
        lay.addWidget(box)

        self._name.textChanged.connect(self._on_name)
        self._file.textEdited.connect(self._on_file_edited)
        self._name.setFocus()

    # Like SketchUp: File follows Name until the user types in it.
    def _on_name(self, text: str) -> None:
        if not self._file_touched:
            self._file.setText(text.strip())
        self._validate()

    def _on_file_edited(self, _text: str) -> None:
        self._file_touched = True
        self._validate()

    def _validate(self) -> None:
        self._ok.setEnabled(bool(self._name.text().strip())
                            and bool(self._file.text().strip()))

    def name(self) -> str:
        return self._name.text().strip()

    def description(self) -> str:
        return self._desc.toPlainText().strip()

    def file_stem(self) -> str:
        return self._file.text().strip() or self.name()

    def make_default(self) -> bool:
        return self._default.isChecked()
