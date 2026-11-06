# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Explicit, reversible editing of the implemented Türkiye delivery fields."""
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from core.bim import collect_objects
from core.turkiye_delivery import (SetDeliveryInformationCommand, check_scene,
                                   generated_name, metadata, rules, ui)


class DeliveryDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.scene = window.viewport.scene
        self.objects = collect_objects(self.scene)
        self.setWindowTitle(ui("Türkiye delivery information"))
        self.resize(760, 700)
        layout = QVBoxLayout(self)
        hint = QLabel(ui("Checks cover the listed fields only. Actor, CRS, geometry/material alignment "
                        "and legal applicability require separate review."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.form = QFormLayout(content)
        self.project_name = QLineEdit(self.scene.ifc_project.get("name", ""))
        self.project_type = QLineEdit(self.scene.ifc_project.get("project_type", ""))
        self.project_description = QLineEdit(self.scene.ifc_project.get("description", ""))
        self.form.addRow(ui("Project identifier supplied by the authority"), self.project_name)
        self.form.addRow(ui("Project type"), self.project_type)
        self.form.addRow(ui("Description"), self.project_description)
        self.object_box = QComboBox()
        self.object_box.setMinimumContentsLength(20)
        self.object_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.object_box.addItem(ui("Project"), None)
        for i, obj in enumerate(self.objects):
            self.object_box.addItem(f"{i + 1}. {obj['class']} — {obj['name']}", i)
        self.form.addRow(ui("BIM object"), self.object_box)
        self.object_widget = QWidget()
        self.object_form = QFormLayout(self.object_widget)
        self.object_form.setContentsMargins(0, 0, 0, 0)
        self.form.addRow(self.object_widget)
        scroll.setWidget(content)
        layout.addWidget(scroll, 3)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setAccessibleName(ui("Check saved data"))
        layout.addWidget(self.report, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(ui("Close"))
        self.apply_button = QPushButton(ui("Apply entered data"))
        check = QPushButton(ui("Check saved data"))
        buttons.addButton(self.apply_button, QDialogButtonBox.ApplyRole)
        buttons.addButton(check, QDialogButtonBox.ActionRole)
        self.apply_button.clicked.connect(self.apply_data)
        check.clicked.connect(self.show_report)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.object_box.currentIndexChanged.connect(self.load_object)
        self.load_object()
        self.show_report()

    def current_object(self):
        index = self.object_box.currentData()
        return self.objects[index] if index is not None else None

    def load_object(self, *_):
        while self.object_form.rowCount():
            self.object_form.removeRow(0)
        self.fields = {}
        self.property_fields = {}
        self.layer_fields = {}
        obj = self.current_object()
        if obj is None:
            return
        spec = rules()["classes"].get(obj["class"])
        if spec is None:
            label = QLabel(ui("No verified category for this IFC class."))
            label.setWordWrap(True)
            self.object_form.addRow(label)
            return
        data = metadata(obj)
        discipline = QComboBox()
        discipline.addItem(ui("Missing / not entered"), "")
        for code in rules()["disciplines"]:
            discipline.addItem(code, code)
        discipline.setCurrentIndex(max(0, discipline.findData(data.get("discipline", ""))))
        self.fields["discipline"] = discipline
        self.object_form.addRow(ui("Discipline"), discipline)
        separator = QComboBox()
        separator.addItem(ui("EK-5: underscore (_)"), "annex5")
        separator.addItem(ui("Article 11: hyphen (-)"), "article11")
        separator.setCurrentIndex(max(0, separator.findData(data.get("separator", "annex5"))))
        self.fields["separator"] = separator
        self.object_form.addRow(ui("Description separators"), separator)
        note = QLabel(ui("The annex and Article 11 differ on description separators. "
                         "Choose the interpretation to review."))
        note.setWordWrap(True)
        self.object_form.addRow(note)
        self.fields["description"] = QLineEdit(data.get("description", ""))
        self.object_form.addRow(ui("Description tokens"), self.fields["description"])
        self.preview = QLineEdit()
        self.preview.setReadOnly(True)
        self.object_form.addRow(ui("Generated name"), self.preview)
        predefined = QComboBox()
        predefined.addItem(ui("Missing / not entered"), "")
        for code in spec["predefined_types"]["IFC4X3_ADD2"]:
            predefined.addItem(code, code)
        predefined.setCurrentIndex(max(0, predefined.findData(data.get("predefined_type", ""))))
        self.fields["predefined_type"] = predefined
        self.object_form.addRow(ui("PredefinedType"), predefined)
        for key, title in (("object_type", "ObjectType"), ("tag", "Tag"),
                           ("material", "Material name and strength")):
            if key == "tag" and not spec["tag_required"]:
                continue
            if key == "material" and obj["class"] == "IfcSpace":
                continue
            edit = QLineEdit(data.get(key, ""))
            self.fields[key] = edit
            self.object_form.addRow(ui(title), edit)
        if spec.get("layer_required"):
            layer = data.get("layer", {})
            for key, title in (("thickness", "Layer thickness (m)"),
                               ("axis", "Layer direction"), ("sense", "Direction sense"),
                               ("offset", "Layer offset (m)")):
                if key in ("axis", "sense"):
                    edit = QComboBox()
                    edit.addItem(ui("Missing / not entered"), None)
                    options = ("AXIS1", "AXIS2", "AXIS3") if key == "axis" else ("POSITIVE", "NEGATIVE")
                    for option in options:
                        edit.addItem(option, option)
                    edit.setCurrentIndex(max(0, edit.findData(layer.get(key))))
                else:
                    edit = QLineEdit(str(layer[key]) if key in layer else "")
                self.layer_fields[key] = edit
                self.object_form.addRow(ui(title), edit)
        for pset, fields in spec["psets"].items():
            title = QLabel(pset)
            title.setWordWrap(True)
            self.object_form.addRow(title)
            for name, kind in fields.items():
                value = data.get("psets", {}).get(pset, {}).get(name)
                if kind == "IfcBoolean":
                    edit = QComboBox()
                    edit.addItem(ui("Missing / not entered"), None)
                    edit.addItem(ui("True"), True)
                    edit.addItem(ui("False"), False)
                    edit.setCurrentIndex(0 if value is None else 1 if value is True else 2)
                else:
                    edit = QLineEdit("" if value is None else str(value))
                self.property_fields[(pset, name)] = (edit, kind)
                self.object_form.addRow(ui(name), edit)
        note = QLabel(ui("Dimensions and thicknesses use metres. Empty fields are not inferred."))
        note.setWordWrap(True)
        self.object_form.addRow(note)
        if spec.get("unimplemented"):
            label = QLabel(ui("Material-layer or space-covering relationship not verified."))
            label.setWordWrap(True)
            self.object_form.addRow(label)
        discipline.currentIndexChanged.connect(self.update_preview)
        separator.currentIndexChanged.connect(self.update_preview)
        self.fields["description"].textChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self, *_):
        obj = self.current_object()
        data = {key: (edit.currentData() if isinstance(edit, QComboBox) else edit.text().strip())
                for key, edit in self.fields.items()}
        self.preview.setText(generated_name(obj["class"], data) or ui("Missing / not entered"))

    def entered_data(self):
        data = {key: (edit.currentData() if isinstance(edit, QComboBox) else edit.text().strip())
                for key, edit in self.fields.items()}
        if self.layer_fields:
            layer = {}
            for key, edit in self.layer_fields.items():
                value = edit.currentData() if isinstance(edit, QComboBox) else edit.text().strip()
                if value not in (None, ""):
                    layer[key] = float(value.replace(",", ".")) if key in ("thickness", "offset") else value
            data["layer"] = layer
        data["psets"] = {}
        for (pset, name), (edit, kind) in self.property_fields.items():
            value = edit.currentData() if isinstance(edit, QComboBox) else edit.text().strip()
            if value in (None, ""):
                continue
            if kind == "IfcPositiveLengthMeasure":
                # A Turkish decimal comma is accepted in this editor; the
                # model stores a number and STEP always uses a period.
                value = float(value.replace(",", "."))
            data["psets"].setdefault(pset, {})[name] = value
        return data

    def apply_data(self):
        from core.turkiye_delivery import property_values
        obj = self.current_object() if self.fields else None
        try:
            data = self.entered_data() if obj is not None else None
            if data is not None:
                list(property_values(obj["class"], data))
        except ValueError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        project = {"name": self.project_name.text().strip(),
                   "project_type": self.project_type.text().strip(),
                   "description": self.project_description.text().strip()}
        command = SetDeliveryInformationCommand(self.scene, project, obj, data)
        self.window.viewport.history.execute(command)
        self.objects = collect_objects(self.scene)
        for i, item in enumerate(self.objects):
            self.object_box.setItemText(i + 1, f"{i + 1}. {item['class']} — {item['name']}")
        self.window.bim_tray.bim.refresh()
        self.window.viewport.update()
        self.show_report()

    def show_report(self):
        report = check_scene(self.scene)
        rows = [f"{i['object'] or i['class']}: {i['field']} — {ui(i['message'])}"
                for i in report["issues"]]
        if not rows:
            rows.append(ui("No missing values in the checked fields. Remaining scope still requires review."))
        rows += ["", ui("Checks cover the listed fields only. Actor, CRS, geometry/material alignment "
                        "and legal applicability require separate review.")]
        self.report.setPlainText("\n".join(rows))
