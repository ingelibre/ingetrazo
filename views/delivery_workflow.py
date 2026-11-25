# SPDX-License-Identifier: GPL-3.0-or-later
"""Reversible project, spatial and evidence editing for the delivery workflow."""
import copy
import datetime as dt
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from core.delivery_workflow import specification, new_node, spatial_fields, model_fingerprint
from core.turkiye_delivery import SetDeliveryInformationCommand, check_scene, rules


def label(text):
    # Feature-local strings keep the upstream translation catalogs independent.
    from core.i18n import current_language, tr
    return specification()["labels"].get(text, {}).get(current_language(), tr(text))


def detail_text(detail):
    if isinstance(detail, dict):
        return f"{detail.get('field', '')}: {label(detail.get('message', ''))}"
    detail = str(detail)
    prefix, separator, message = detail.partition(": ")
    return prefix + separator + label(message) if separator else label(detail)


class WorkflowDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.scene = window, window.viewport.scene
        self.project = copy.deepcopy(self.scene.ifc_project)
        self.setWindowTitle(label("Project and delivery workflow"))
        area = self.screen().availableGeometry()
        self.resize(min(1000, area.width()-40), min(780, area.height()-80))
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.edits = {}
        for section, fields in specification()["forms"].items():
            content = QWidget(); form = QFormLayout(content)
            data = self.project if section == "project" else self.project.get(section, {})
            for key, english, turkish, typ in fields:
                edit = self.make_edit(typ, data.get(key), key)
                self.edits[(section, key)] = (edit, typ)
                from core.i18n import current_language
                form.addRow(turkish if current_language() == "tr" else english, edit)
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content)
            self.tabs.addTab(scroll, label(section.title()))
        self.spatial_tab()
        self.quality_tab()
        tools = QWidget(); form = QFormLayout(tools)
        self.validator = QLineEdit(self.project.get("validator", ""))
        form.addRow(label("PDF/A validator JAR"), self.validator)
        choose = QPushButton(label("Choose validator")); choose.clicked.connect(self.choose_validator)
        form.addRow(choose)
        self.summary = QLabel(); self.summary.setWordWrap(True); form.addRow(self.summary)
        export = QPushButton(label("Build verified delivery package")); export.clicked.connect(self.build)
        form.addRow(export)
        tools_scroll = QScrollArea(); tools_scroll.setWidgetResizable(True); tools_scroll.setWidget(tools)
        self.tabs.addTab(tools_scroll, label("Delivery package"))
        buttons = QDialogButtonBox(QDialogButtonBox.Close | QDialogButtonBox.Apply)
        buttons.button(QDialogButtonBox.Close).setText(label("Close"))
        buttons.button(QDialogButtonBox.Apply).setText(label("Apply"))
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        layout.addWidget(buttons)
        self.refresh_report()

    @staticmethod
    def make_edit(typ, value, key=""):
        choices = None
        if typ in ("bool", "boolean"): choices = [("", None), (label("True"), True), (label("False"), False)]
        elif key in ("role", "organization_role"): choices = [("", "")] + [(x, x) for x in specification()["roles"]]
        elif typ == "epsg": choices = [("", "")] + [(f"EPSG:{n}", f"EPSG:{n}") for n in range(5253, 5260)]
        elif key == "discipline": choices = [("", "")] + [(x, x) for x in rules()["disciplines"]]
        elif key in ("kind", "type"):
            choices = [("", "")] + [(x, x) for x in specification()["file_kinds" if key == "kind" else "file_types"]]
        if choices is not None:
            edit = QComboBox()
            for text, data in choices: edit.addItem(text, data)
            edit.setCurrentIndex(max(0, edit.findData(value)))
            return edit
        return QLineEdit("" if value is None else "; ".join(value) if isinstance(value, list) else str(value))

    @staticmethod
    def value(edit, typ):
        if isinstance(edit, QComboBox): return edit.currentData()
        value = edit.text().strip()
        if not value: return None
        if typ in ("float", "number", "integer", "int") or typ.startswith("Ifc") and typ not in ("IfcLabel", "IfcText", "IfcIdentifier", "IfcLabelList"):
            return int(value) if typ in ("integer", "int") else float(value.replace(",", "."))
        if typ == "IfcLabelList": return [x.strip() for x in value.split(";") if x.strip()]
        return value

    def spatial_tab(self):
        content = QWidget(); layout = QVBoxLayout(content)
        hint = QLabel(label("Use name / code examples: MM-BNA-A, MM-BNK-Zemin, K00. Assignment does not move geometry."))
        hint.setWordWrap(True); layout.addWidget(hint)
        self.nodes = QComboBox(); layout.addWidget(self.nodes)
        self.node_form_widget = QWidget(); self.node_form = QFormLayout(self.node_form_widget)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self.node_form_widget); layout.addWidget(scroll)
        row = QHBoxLayout()
        for kind in ("building", "storey"):
            button = QPushButton(label("Add " + kind)); button.clicked.connect(lambda checked=False, k=kind: self.add_node(k)); row.addWidget(button)
        delete = QPushButton(label("Remove selected")); delete.clicked.connect(self.remove_node); row.addWidget(delete)
        layout.addLayout(row)
        self.project.setdefault("spatial", {"site": new_node("site"), "buildings": [], "storeys": []})
        self.node_edits = {}; self.active_node = None
        self.nodes.currentIndexChanged.connect(self.load_node)
        self.reload_nodes()
        self.tabs.addTab(content, label("Site / buildings / storeys"))

    def reload_nodes(self, selected=None):
        self.nodes.blockSignals(True); self.nodes.clear()
        spatial = self.project["spatial"]
        for kind, records in (("site", [spatial["site"]]), ("building", spatial["buildings"]), ("storey", spatial["storeys"])):
            for node in records: self.nodes.addItem(f"{label(kind.title())}: {node.get('name') or node['id'][:8]}", (kind, node))
        index = next((i for i in range(self.nodes.count()) if self.nodes.itemData(i)[1]["id"] == selected), 0)
        self.nodes.setCurrentIndex(index); self.nodes.blockSignals(False); self.active_node = None; self.load_node()

    def save_node(self):
        if not self.active_node: return
        _, node = self.active_node
        for path, (edit, typ) in self.node_edits.items():
            target = node
            for part in path[:-1]: target = target.setdefault(part, {})
            value = self.value(edit, typ)
            if value is None: target.pop(path[-1], None)
            else: target[path[-1]] = value

    def load_node(self, *_):
        try: self.save_node()
        except ValueError:
            QMessageBox.warning(self, self.windowTitle(), label("Invalid numeric value"))
            self.nodes.blockSignals(True)
            for i in range(self.nodes.count()):
                if self.nodes.itemData(i)[1]["id"] == self.active_node[1]["id"]: self.nodes.setCurrentIndex(i)
            self.nodes.blockSignals(False); return
        while self.node_form.rowCount(): self.node_form.removeRow(0)
        self.active_node = self.nodes.currentData(); self.node_edits = {}
        if not self.active_node: return
        kind, node = self.active_node
        fields = [("name", "text"), ("long_name", "text"), ("object_type", "text")]
        fields += [("ref_elevation", "float")] if kind == "site" else [("elevation", "float"), ("code", "text")] if kind == "storey" else []
        for key, typ in fields:
            edit = self.make_edit(typ, node.get(key)); self.node_edits[(key,)] = (edit, typ); self.node_form.addRow(label(key), edit)
        if kind == "storey":
            edit = QComboBox(); edit.addItem("", "")
            for b in self.project["spatial"]["buildings"]: edit.addItem(b.get("name") or b["id"], b["id"])
            edit.setCurrentIndex(max(0, edit.findData(node.get("building_id"))))
            self.node_edits[("building_id",)] = (edit, "text"); self.node_form.addRow(label("Building"), edit)
        for pset, key, typ, value in spatial_fields(kind, node):
            edit = self.make_edit("bool" if typ == "IfcBoolean" else typ, value)
            self.node_edits[("psets", pset, key)] = (edit, typ)
            self.node_form.addRow(f"{pset}.{key} ({typ})", edit)
            field = pset + "." + key
            if field in specification()["conditional_fields"]:
                exception = QLineEdit(node.get("exceptions", {}).get(field, ""))
                self.node_edits[("exceptions", field)] = (exception, "text")
                self.node_form.addRow(label("Conditional exception evidence"), exception)

    def add_node(self, kind):
        try: self.save_node()
        except ValueError as exc: QMessageBox.warning(self, self.windowTitle(), str(exc)); return
        node = new_node(kind)
        self.project["spatial"]["buildings" if kind == "building" else "storeys"].append(node)
        self.reload_nodes(node["id"])

    def remove_node(self):
        if not self.active_node or self.active_node[0] == "site": return
        kind, node = self.active_node
        spatial = self.project["spatial"]
        # References remain visible as validation errors; never reassign geometry silently.
        spatial["buildings" if kind == "building" else "storeys"].remove(node)
        self.active_node = None; self.reload_nodes()

    def quality_tab(self):
        page = QWidget(); layout = QVBoxLayout(page)
        form = QFormLayout(); review = self.project.get("review", {})
        self.reviewer = QLineEdit(review.get("reviewer", "")); self.review_date = QLineEdit(review.get("date", dt.date.today().isoformat()))
        form.addRow(label("Reviewer"), self.reviewer); form.addRow(label("Review date (YYYY-MM-DD)"), self.review_date); layout.addLayout(form)
        self.quality = QTableWidget(0, 3); self.quality.setHorizontalHeaderLabels([label("Check"), label("Answer"), label("Evidence / reference")])
        self.quality_rows = specification()["quality"]["MM" if self.project.get("filename", {}).get("discipline", "MM") == "MM" else "OTHER"]
        self.quality.setRowCount(len(self.quality_rows))
        for i, row in enumerate(self.quality_rows):
            item = QTableWidgetItem(f"{row['number']}. {row['label']}"); item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.quality.setItem(i, 0, item)
            answer = review.get("answers", {}).get(row["key"], {})
            box = QComboBox()
            for title, code in (("Pending", ""), ("Yes", "yes"), ("No", "no"), ("Not applicable", "na")): box.addItem(label(title), code)
            box.setCurrentIndex(max(0, box.findData(answer.get("answer", "")))); self.quality.setCellWidget(i, 1, box)
            self.quality.setItem(i, 2, QTableWidgetItem(answer.get("evidence", "")))
        self.quality.horizontalHeader().setStretchLastSection(True); self.quality.setColumnWidth(0, 450); layout.addWidget(self.quality)
        confirm = QPushButton(label("Confirm review for current model")); confirm.clicked.connect(self.confirm); layout.addWidget(confirm)
        self.tabs.addTab(page, label("Quality review"))
        self.edits[("filename", "discipline")][0].currentIndexChanged.connect(self.change_discipline)

    def change_discipline(self, *_):
        answers = {r["key"]: {"answer": self.quality.cellWidget(i, 1).currentData(), "evidence": self.quality.item(i, 2).text()}
                   for i, r in enumerate(self.quality_rows)}
        discipline = self.edits[("filename", "discipline")][0].currentData()
        self.quality_rows = specification()["quality"]["MM" if discipline == "MM" else "OTHER"]
        self.quality.setRowCount(len(self.quality_rows))
        for i, row in enumerate(self.quality_rows):
            item = QTableWidgetItem(f"{row['number']}. {row['label']}"); item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.quality.setItem(i, 0, item)
            answer = answers.get(row["key"], {})
            box = QComboBox()
            for title, code in (("Pending", ""), ("Yes", "yes"), ("No", "no"), ("Not applicable", "na")): box.addItem(label(title), code)
            box.setCurrentIndex(max(0, box.findData(answer.get("answer", "")))); self.quality.setCellWidget(i, 1, box)
            self.quality.setItem(i, 2, QTableWidgetItem(answer.get("evidence", "")))

    def apply(self):
        try:
            self.save_node()
            for (section, key), (edit, typ) in self.edits.items():
                target = self.project if section == "project" else self.project.setdefault(section, {})
                value = self.value(edit, typ)
                if value is None: target.pop(key, None)
                else: target[key] = value
            self.project.update(delivery_version=2, validator=self.validator.text().strip())
            self.project.setdefault("created_at", int(time.time()))
            review = self.project.setdefault("review", {})
            review.update(reviewer=self.reviewer.text().strip(), date=self.review_date.text().strip())
            review["answers"] = {r["key"]: {"answer": self.quality.cellWidget(i, 1).currentData(), "evidence": self.quality.item(i, 2).text().strip()} for i, r in enumerate(self.quality_rows)}
            previous = self.scene.ifc_project.get("review", {})
            if any(review.get(k) != previous.get(k) for k in ("reviewer", "date", "answers")):
                review.pop("model_fingerprint", None)
            self.window.viewport.history.execute(SetDeliveryInformationCommand(self.scene, copy.deepcopy(self.project)))
            self.window.viewport.update(); self.refresh_report(); return True
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc)); return False

    def confirm(self):
        if not self.apply(): return
        review = self.project["review"]
        try: valid_date = dt.date.fromisoformat(review["date"]) <= dt.date.today()
        except ValueError: valid_date = False
        if not review["reviewer"] or not valid_date:
            QMessageBox.warning(self, self.windowTitle(), label("Reviewer and valid review date required")); return
        self.project["review"]["model_fingerprint"] = model_fingerprint(self.scene)
        self.window.viewport.history.execute(SetDeliveryInformationCommand(self.scene, copy.deepcopy(self.project)))
        self.refresh_report()

    def refresh_report(self):
        report = check_scene(self.scene)
        self.summary.setText("\n".join([f"{label('Issues')}: {len(report['issues'])}"] +
            [detail_text(i) for i in report['issues']] +
            [f"{r['number']}. {r['label']}: {label(r['status'])}" + (" — " + "; ".join(detail_text(a) for a in r['automatic']) if r['automatic'] else "") for r in report.get("checks", [])]))

    def choose_validator(self):
        path, _ = QFileDialog.getOpenFileName(self, label("Choose validator"), "", "veraPDF CLI (*.jar *.exe);;All files (*)")
        if path: self.validator.setText(path)

    def build(self):
        if not self.apply(): return
        path, _ = QFileDialog.getSaveFileName(self, label("Build verified delivery package"), "delivery.zip", "ZIP (*.zip)")
        if not path: return
        from formats.delivery_package import build_package
        try:
            build_package(self.window, path)
            QMessageBox.information(self, self.windowTitle(), label("Verified delivery package created") + "\n" + path)
        except Exception as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
