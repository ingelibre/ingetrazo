# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
# The panels follow moominot's «dc_tools» extension (GPL-3.0-or-later,
# https://github.com/moominot/ingetrazo-skp-dc-import): its «Component
# Options» and «Component Attributes».
"""Dynamic components in the interface.

- **Component options** (a section of Properties): the options the
  selected dynamic component offers — a width, a number of leaves, a
  list — and Apply, which redraws it as one undo step.
- **Component attributes…** (a window): make a component dynamic, and
  write its parts' attributes and formulas.

Both work on :mod:`core.dynamic`; neither keeps any state of its own.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMenu, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core.dynamic import apply as A
from core.dynamic import author as AU
from core.dynamic import formula as F
from core.dynamic import options as O
from core.dynamic.document import (DynamicError, make_dynamic_in_document,
                                   redraw_in_document, selected_one)
from core.dynamic.evaluate import _num
from core.dynamic.messages import tr_msg
from core.dynamic.model import INCH
from core.dynamic.redraw import LEN, _LiveEvaluator, live_value
from core.i18n import tr

_log = logging.getLogger(__name__)

#: Shown in the header, not as options.
HEADER_ONLY = ("name", "summary", "description", "imageurl", "dialogwidth",
               "dialogheight")
#: The units a component's formulas can be written in.
UNITS = (("CENTIMETERS", "Centimeters"), ("MILLIMETERS", "Millimeters"),
         ("METERS", "Meters"), ("INCHES", "Inches"), ("FEET", "Feet"))
#: How an attribute's value is shown.
VALUE_UNITS = (("DEFAULT", "Default"), ("CENTIMETERS", "Centimeters"),
               ("MILLIMETERS", "Millimeters"), ("METERS", "Meters"),
               ("INCHES", "Inches"), ("FEET", "Feet"),
               ("DEGREES", "Degrees"), ("PERCENT", "Percent"),
               ("INTEGER", "Whole number"), ("FLOAT", "Decimal number"),
               ("STRING", "Text"))
#: Who sees an attribute in Component options.
ACCESS_LABELS = (("NONE", "Users cannot see this attribute"),
                 ("VIEW", "Users can see this attribute"),
                 ("TEXTBOX", "Users can edit as a textbox"),
                 ("LIST", "Users can select from a list"))
#: The sections of the «Add attribute» menu.
SECTION_LABELS = {"Component Info": "Component info", "Position": "Position",
                  "Size": "Size", "Rotation": "Rotation",
                  "Behaviors": "Behaviors", "Form Design": "Form design"}


def _error_text(exc) -> str:
    msg = getattr(exc, "msg", None)
    return tr_msg(msg) if msg is not None else str(exc)


def _problems_text(problems) -> str:
    if not problems:
        return ""
    return tr("{n} formula(s) could not be evaluated and kept their value.",
              n=len(problems))


# ---- Component options ---------------------------------------------------------
class ComponentOptionsPanel(QWidget):
    """The selected dynamic component's options; Apply redraws it."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self.group = None
        self.rows: list = []                     # (Option, widget, initial)
        #: What Revert goes back to: the options the component had when it
        #: was selected (``{name: stored value}``), kept through Apply.
        self._initial_uid = None
        self._initial: dict = {}
        self._current: dict = {}
        self._attributes = None                  # the open attributes window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.RichText)
        outer.addWidget(self.title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        outer.addWidget(self.form_host)
        buttons = QHBoxLayout()
        self.apply_btn = QPushButton(tr("Apply"))
        self.apply_btn.setToolTip(
            tr("Redraw the component with these options (one undo step)"))
        self.apply_btn.clicked.connect(self.apply)
        self.revert_btn = QPushButton(tr("Revert"))
        self.revert_btn.setToolTip(
            tr("Back to the values it had when you selected it: drops what "
               "you typed, or undoes what you applied (one more undo step)"))
        self.revert_btn.clicked.connect(self.revert)
        self.attr_btn = QPushButton(tr("Attributes…"))
        self.attr_btn.setToolTip(
            tr("Make the selected component dynamic and edit its attributes "
               "and formulas"))
        self.attr_btn.clicked.connect(self.open_attributes)
        # Two rows: the tray stays as narrow as its other sections.
        for b in (self.apply_btn, self.revert_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        outer.addLayout(buttons)
        second = QHBoxLayout()
        second.addWidget(self.attr_btn)
        second.addStretch(1)
        outer.addLayout(second)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.show_group(None, True)

    # -- following the selection ------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def refresh(self) -> None:
        try:
            g = selected_one(self._scene())
        except Exception:  # noqa: BLE001 - a document switching underneath
            return
        if g is not self.group:
            self.show_group(g)
        any_one = selected_one(self._scene(), dynamic_only=False)
        self.attr_btn.setEnabled(any_one is not None)

    def _clear(self) -> None:
        # Taken out now, deleted later: the row cleared may be the field
        # whose Enter key is still being handled.
        while self.form.rowCount():
            taken = self.form.takeRow(0)
            for item in (taken.labelItem, taken.fieldItem):
                w = item.widget() if item is not None else None
                if w is not None:
                    w.hide()
                    w.deleteLater()
        self.rows = []

    def show_group(self, group, force: bool = False) -> None:
        if group is self.group and not force:
            return
        self.group = group
        self._clear()
        self.status.setText("")
        dyn = group is not None
        self.apply_btn.setEnabled(dyn)
        self.revert_btn.setEnabled(dyn)
        self.summary.hide()
        if not dyn:
            self._initial_uid, self._initial, self._current = None, {}, {}
            self.title.setText(tr("Select a dynamic component to see its options."))
            return
        root, _frame = A.part_in_context(self._scene(), group)
        ev = _LiveEvaluator(root)
        opts = [o for o in O.options_of(root.attrs) if o.name not in HEADER_ONLY]
        self.title.setText("<b>%s</b>" % _html(root.name))
        summary = str(root.attrs.get("summary") or "").strip()
        if summary and str(root.attrs.get("_summary_access") or "").upper() != "NONE":
            self.summary.setText(summary)
            self.summary.show()
        if not opts:
            self.status.setText(tr("This component has no options for its users."))
        for opt in opts:
            if opt.name in LEN:
                opt.value = live_value(root, opt.name)
            elif opt.access == "VIEW" or root.formula(opt.name):
                try:
                    opt.value = ev.value(root, opt.name)
                except Exception:  # noqa: BLE001 - show what is stored
                    pass
            if opt.access == "LIST" and opt.choices:
                w = QComboBox()
                for label, raw in opt.choices:
                    w.addItem(label, raw)
                idx = O.current_choice(opt)
                if idx < 0:
                    w.addItem(O.display(opt), None)
                    idx = w.count() - 1
                w.setCurrentIndex(idx)
                initial = idx
            elif opt.access == "VIEW":
                w = QLabel(O.display(opt))
                w.setTextInteractionFlags(Qt.TextSelectableByMouse)
                initial = None
            else:
                w = QLineEdit(O.display(opt))
                w.returnPressed.connect(lambda: QTimer.singleShot(0, self.apply))
                initial = w.text()
            label = QLabel(opt.label)
            label.setWordWrap(True)
            self.form.addRow(label, w)
            self.rows.append((opt, w, initial))
        self._current = {o.name: o.value for o in opts if o.access != "VIEW"}
        if group.uid != self._initial_uid:
            # Newly selected: this is what Revert will go back to. A redraw
            # keeps the uid, so Apply does not move the mark.
            self._initial_uid = group.uid
            self._initial = dict(self._current)

    # -- applying -----------------------------------------------------------------
    def collect(self):
        """The options changed: ({attribute: stored value}, [errors])."""
        options, errors = {}, []
        root = None
        for opt, w, initial in self.rows:
            if opt.access == "VIEW":
                continue
            if isinstance(w, QComboBox):
                if w.currentIndex() == initial:
                    continue
                raw = w.currentData()
                if raw is None:
                    continue
                if str(raw).startswith("="):
                    # A choice whose value is a formula.
                    root = root or A.part_in_context(self._scene(), self.group)[0]
                    ev = _LiveEvaluator(root)
                    try:
                        v = F.evaluate(F.parse(str(raw)[1:]), ev._lookup(root))
                        raw = ev.from_formula(root, opt.name, v)
                    except Exception as exc:  # noqa: BLE001
                        errors.append("%s: %s" % (opt.label, _error_text(exc)))
                        continue
                n = _num(raw)
                options[opt.name] = n if isinstance(n, float) else raw
            else:
                if w.text() == initial:
                    continue
                try:
                    options[opt.name] = O.parse(opt, w.text())
                except ValueError:
                    errors.append(tr("{label}: «{text}» is not a number",
                                     label=opt.label, text=w.text()))
        return options, errors

    def apply(self) -> None:
        if self.group is None:
            return
        options, errors = self.collect()
        if errors:
            self.status.setText("\n".join(errors))
            return
        try:
            new, problems = redraw_in_document(self._window.viewport,
                                               self.group, options)
        except (DynamicError, Exception) as exc:  # noqa: BLE001 - never crash
            _log.exception("redraw failed")
            self.status.setText(tr("Could not redraw: {error}",
                                   error=_error_text(exc)))
            return
        self.show_group(new, True)
        self.status.setText(_problems_text(problems) or tr("Redrawn."))

    def revert(self) -> None:
        """Typed changes not applied yet: drop them. Otherwise go back to
        the options the component had when it was selected, redrawing it
        (one more undo step)."""
        if self.group is None:
            return
        typed, errors = self.collect()
        if typed or errors:
            self.show_group(self.group, True)
            self.status.setText(tr("Typed changes discarded."))
            return
        back = {n: v for n, v in self._initial.items()
                if not _same(v, self._current.get(n))}
        if not back:
            self.status.setText(tr(
                "Nothing to revert: it has the values it had when you selected it."))
            return
        try:
            new, problems = redraw_in_document(self._window.viewport,
                                               self.group, back)
        except Exception as exc:  # noqa: BLE001 - never crash
            _log.exception("revert failed")
            self.status.setText(tr("Could not redraw: {error}",
                                   error=_error_text(exc)))
            return
        self.show_group(new, True)
        self.status.setText(_problems_text(problems) or tr(
            "Back to the values it had when you selected it."))

    # -- the attributes window ------------------------------------------------------
    def open_attributes(self) -> None:
        g = selected_one(self._scene(), dynamic_only=False)
        if g is None:
            return
        if self._attributes is None:
            self._attributes = AttributesDialog(self._window, self)
        self._attributes.show_root(g, ())
        self._attributes.show()
        self._attributes.raise_()
        self._attributes.activateWindow()


def _same(a, b) -> bool:
    """Two stored option values that mean the same (numbers to 1e-6)."""
    na, nb = _num(a), _num(b)
    if isinstance(na, float) and isinstance(nb, float):
        return abs(na - nb) <= 1e-6 * max(1.0, abs(na), abs(nb))
    return str(a if a is not None else "") == str(b if b is not None else "")


def _html(text) -> str:
    import html
    return html.escape(str(text or ""))


# ---- Component attributes --------------------------------------------------------
def part_at(root, path):
    g = root
    for i in path:
        kids = g.children or []
        if i >= len(kids):
            return None
        g = kids[i]
    return g


def _units_of(attrs: dict, name: str, part_unit: str) -> str:
    """How a value of ``name`` is read and shown."""
    if name in ("x", "y", "z", "lenx", "leny", "lenz"):
        return part_unit
    if name in ("rotx", "roty", "rotz"):
        return "DEGREES"
    u = str(attrs.get(f"_{name}_units") or "").upper()
    if u in ("", "DEFAULT"):
        fu = str(attrs.get(f"_{name}_formulaunits") or "").upper()
        return fu if fu in INCH else "STRING"
    return u


def _copies_of(root, part) -> list:
    """The copies (Copy > 0) of ``part`` among its siblings."""
    name = AU.merged(part).get("_name") or part.name

    def parent_of(g):
        for c in g.children or ():
            if c is part:
                return g
            hit = parent_of(c)
            if hit is not None:
                return hit
        return None

    parent = parent_of(root)
    out = []
    for c in (parent.children if parent is not None else ()) or ():
        if c is part:
            continue
        a = AU.merged(c)
        copy = _num(a.get("copy"))
        if isinstance(copy, float) and copy > 0 and (a.get("_name") or c.name) == name:
            out.append(c)
    return out


class AttributeOptionsDialog(QDialog):
    """One attribute's display rule: its label, who sees it, its units and
    the choices of a list."""

    def __init__(self, parent, name: str, attrs: dict) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Attribute options — {name}", name=name))
        form = QFormLayout(self)
        self.label = QLineEdit(str(attrs.get(f"_{name}_formlabel")
                                   or attrs.get(f"_{name}_label") or name))
        form.addRow(tr("Display label"), self.label)
        self.access = QComboBox()
        for key, text in ACCESS_LABELS:
            self.access.addItem(tr(text), key)
        cur = str(attrs.get(f"_{name}_access") or "NONE").upper()
        self.access.setCurrentIndex(max(0, self.access.findData(cur)))
        form.addRow(tr("Access"), self.access)
        self.units = QComboBox()
        for key, text in VALUE_UNITS:
            self.units.addItem(tr(text), key)
        cu = str(attrs.get(f"_{name}_units") or "DEFAULT").upper()
        self.units.setCurrentIndex(max(0, self.units.findData(cu)))
        form.addRow(tr("Display in"), self.units)
        self.choices = QTableWidget(0, 2)
        self.choices.setHorizontalHeaderLabels([tr("Option"), tr("Value")])
        self.choices.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for label, value in O.parse_choices(attrs.get(f"_{name}_options")):
            self._add_choice(label, value)
        row = QHBoxLayout()
        add, rem = QPushButton("+"), QPushButton("−")
        add.setToolTip(tr("Add a choice"))
        rem.setToolTip(tr("Remove the selected choice"))
        add.clicked.connect(lambda: self._add_choice("", ""))
        rem.clicked.connect(self._remove_choice)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.choices)
        lay.addLayout(row)
        form.addRow(tr("List options"), box)
        self.access.currentIndexChanged.connect(
            lambda _i: box.setEnabled(self.access.currentData() == "LIST"))
        box.setEnabled(self.access.currentData() == "LIST")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _add_choice(self, label, value) -> None:
        r = self.choices.rowCount()
        self.choices.insertRow(r)
        self.choices.setItem(r, 0, QTableWidgetItem(str(label)))
        self.choices.setItem(r, 1, QTableWidgetItem(str(value)))

    def _remove_choice(self) -> None:
        r = self.choices.currentRow()
        if r >= 0:
            self.choices.removeRow(r)

    def changes(self, name: str) -> dict:
        choices = []
        for r in range(self.choices.rowCount()):
            lab = (self.choices.item(r, 0) or QTableWidgetItem("")).text().strip()
            val = (self.choices.item(r, 1) or QTableWidgetItem("")).text().strip()
            if lab:
                choices.append((lab, val if val else lab))
        access = self.access.currentData()
        units = self.units.currentData()
        return AU.set_changes(name, formlabel=self.label.text().strip() or "",
                              access=access,
                              units=units if units != "DEFAULT" else "",
                              options=choices if access == "LIST" else [])


class AttributesDialog(QDialog):
    """Make a component dynamic and edit its parts' attributes and
    formulas. Every change redraws the component as one undo step."""

    def __init__(self, window, options_panel=None) -> None:
        super().__init__(window if isinstance(window, QWidget) else None)
        self._window = window
        self._options = options_panel
        self.root = None
        self.path = ()
        self._filling = False
        self.setWindowTitle(tr("Component attributes"))
        self.resize(560, 560)
        outer = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.RichText)
        outer.addWidget(self.title)
        mk = QHBoxLayout()
        self.make_btn = QPushButton(tr("Make dynamic"))
        self.make_btn.setToolTip(
            tr("Give the selected component or group dynamic attributes"))
        self.make_btn.clicked.connect(self.make_dynamic)
        self.units = QComboBox()
        for key, text in UNITS:
            self.units.addItem(tr(text), key)
        self.units.setToolTip(tr("The units its formulas are written in"))
        mk.addWidget(self.make_btn)
        mk.addWidget(self.units)
        mk.addStretch(1)
        outer.addLayout(mk)
        split = QSplitter(Qt.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._tree_changed)
        split.addWidget(self.tree)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [tr("Attribute"), tr("Value or =formula"), tr("Result")])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemChanged.connect(self._cell_changed)
        split.addWidget(self.table)
        split.setStretchFactor(1, 2)
        outer.addWidget(split, 1)
        row = QHBoxLayout()
        self.add_btn = QToolButton()
        self.add_btn.setText(tr("Add attribute"))
        self.add_btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.add_btn)
        for title, items in AU.GROUPS:
            menu.addSection(tr(SECTION_LABELS.get(title, title)))
            for name, _u in items:
                menu.addAction(AU.LABELS[name],
                               lambda n=name: self.add_attribute(n))
        menu.addSeparator()
        menu.addAction(tr("Custom name…"), self.add_custom)
        self.add_btn.setMenu(menu)
        self.del_btn = QPushButton(tr("Delete"))
        self.del_btn.setToolTip(tr("Delete the selected attribute"))
        self.del_btn.clicked.connect(self.delete_attribute)
        self.opt_btn = QPushButton(tr("Options…"))
        self.opt_btn.setToolTip(
            tr("Label, who can see or edit it, units, list choices"))
        self.opt_btn.clicked.connect(self.edit_options)
        for w in (self.add_btn, self.del_btn, self.opt_btn):
            row.addWidget(w)
        row.addStretch(1)
        outer.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self._refresh_enabled()

    def _scene(self):
        return self._window.viewport.scene

    def _refresh_enabled(self) -> None:
        dyn = self.root is not None and A.is_dynamic_root(self.root)
        self.make_btn.setEnabled(self.root is not None and not dyn)
        self.units.setEnabled(self.root is not None and not dyn)
        for w in (self.add_btn, self.del_btn, self.opt_btn, self.table,
                  self.tree):
            w.setEnabled(self.root is not None)

    def show_root(self, root, path=()) -> None:
        self.root, self.path = root, tuple(path)
        self.status.setText("")
        self._filling = True
        try:
            self.tree.clear()
            if root is None:
                self.title.setText(tr("Select a component or group."))
            else:
                name = AU.merged(root).get("_name") or root.name
                text = "<b>%s</b>" % _html(name)
                if not A.is_dynamic_root(root):
                    text += " — " + _html(tr(
                        "not dynamic yet: add an attribute and it becomes dynamic."))
                self.title.setText(text)
                self._fill_tree(root, None, ())
                self.tree.expandAll()
                self._select_tree(self.path)
        finally:
            self._filling = False
        self._refresh_enabled()
        self.show_part()

    def _fill_tree(self, g, parent_item, path) -> None:
        a = AU.merged(g)
        label = str(a.get("_name") or g.name or tr("(part)"))
        copy = _num(a.get("copy"))
        is_copy = isinstance(copy, float) and copy > 0
        if is_copy:
            label += "  " + tr("(copy {n})", n=int(copy))
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.UserRole, path)
        if is_copy:
            f = QFont()
            f.setItalic(True)
            item.setFont(0, f)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setToolTip(0, tr("A copy made by Copies: edit the original"))
        if parent_item is None:
            self.tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)
        for i, c in enumerate(g.children or ()):
            self._fill_tree(c, item, path + (i,))

    def _select_tree(self, path) -> None:
        def find(item):
            if tuple(item.data(0, Qt.UserRole) or ()) == tuple(path):
                return item
            for i in range(item.childCount()):
                hit = find(item.child(i))
                if hit is not None:
                    return hit
            return None
        if self.tree.topLevelItemCount():
            top = self.tree.topLevelItem(0)
            self.tree.setCurrentItem(find(top) or top)

    def _tree_changed(self, cur, _prev) -> None:
        if self._filling or cur is None:
            return
        self.path = tuple(cur.data(0, Qt.UserRole) or ())
        self.show_part()

    # -- the table ------------------------------------------------------------------
    def _part(self):
        return part_at(self.root, self.path) if self.root is not None else None

    def _part_unit(self, attrs) -> str:
        u = str(attrs.get("_lengthunits") or "").upper()
        if u in INCH:
            return u
        root_u = str(AU.merged(self.root).get("_lengthunits") or "").upper()
        return root_u if root_u in INCH else "CENTIMETERS"

    def _evaluated_part(self):
        tree = A.part_in_context(self._scene(), self.root)[0]
        part = tree
        for i in self.path:
            part = part.children[i]
        return tree, part

    def show_part(self) -> None:
        self._filling = True
        try:
            self.table.setRowCount(0)
            g = self._part()
            if g is None or not A.is_dynamic_root(self.root):
                return
            attrs = AU.merged(g)
            unit = self._part_unit(attrs)
            try:
                tree, part = self._evaluated_part()
                ev = _LiveEvaluator(tree)
            except Exception:  # noqa: BLE001
                part, ev = None, None
            for name in AU.attribute_names(attrs):
                r = self.table.rowCount()
                self.table.insertRow(r)
                head = QTableWidgetItem(AU.LABELS.get(name, name))
                head.setData(Qt.UserRole, name)
                head.setFlags(head.flags() & ~Qt.ItemIsEditable)
                f = attrs.get(f"_{name}_formula")
                units = _units_of(attrs, name, unit)
                opt = O.Option(name, name, "TEXTBOX", units, attrs.get(name))
                text = f"={f}" if f not in (None, "") else O.display(opt)
                result = ""
                if part is not None and ev is not None:
                    try:
                        result = O.display(opt, ev.value(part, name))
                    except Exception:  # noqa: BLE001
                        result = "?"
                res = QTableWidgetItem(result)
                res.setFlags(res.flags() & ~Qt.ItemIsEditable)
                access = str(attrs.get(f"_{name}_access") or "").upper()
                if access and access != "NONE":
                    head.setToolTip(tr("Shown to users"))
                    fh = QFont()
                    fh.setBold(True)
                    head.setFont(fh)
                self.table.setItem(r, 0, head)
                self.table.setItem(r, 1, QTableWidgetItem(text))
                self.table.setItem(r, 2, res)
            self.table.resizeColumnToContents(0)
        finally:
            self._filling = False

    def _selected_name(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        return it.data(Qt.UserRole) if it else None

    # -- editing ----------------------------------------------------------------------
    def _commit(self, changes: dict, message: str) -> None:
        g = self._part()
        if g is None or not changes:
            return
        attrs = AU.merged(g)
        if not attrs.get("_name"):
            changes.setdefault("_name", g.name or "part")
        if not attrs.get("_lengthunits"):
            changes.setdefault("_lengthunits", self._part_unit(attrs))
        # The part's copies get the same change: they are the original again.
        targets = [g] + _copies_of(self.root, g)
        try:
            new, problems = redraw_in_document(
                self._window.viewport, self.root, {},
                {id(t): dict(changes) for t in targets})
        except Exception as exc:  # noqa: BLE001
            _log.exception("attribute edit failed")
            self.status.setText(tr("Could not apply: {error}",
                                   error=_error_text(exc)))
            return
        self.show_root(new, self.path)
        extra = _problems_text(problems)
        self.status.setText(message + (" " + extra if extra else ""))
        if self._options is not None:
            self._options.show_group(new if A.is_dynamic_root(new) else None, True)

    def _cell_changed(self, item) -> None:
        if self._filling or item.column() != 1:
            return
        head = self.table.item(item.row(), 0)
        name = head.data(Qt.UserRole) if head else None
        if not name:
            return
        text = item.text().strip()
        g = self._part()
        attrs = AU.merged(g)
        if text.startswith("="):
            try:
                F.parse(text[1:])
            except F.FormulaError as exc:
                self.status.setText("%s: %s" % (name, _error_text(exc)))
                QTimer.singleShot(0, self.show_part)
                return
            self._commit(AU.set_changes(name, formula=text),
                         tr("{name} set.", name=name))
            return
        units = _units_of(attrs, name, self._part_unit(attrs))
        opt = O.Option(name, name, "TEXTBOX", units, attrs.get(name))
        try:
            value = O.parse(opt, text) if text else ""
        except ValueError:
            self.status.setText(tr("{label}: «{text}» is not a number",
                                   label=name, text=text))
            QTimer.singleShot(0, self.show_part)
            return
        if isinstance(value, float):
            value = repr(value)          # option values are kept as text
        self._commit(AU.set_changes(name, value=value, formula=""),
                     tr("{name} set.", name=name))

    def _ensure_dynamic(self) -> bool:
        g = self.root
        if g is None:
            return False
        if A.is_dynamic_root(g):
            return True
        return self.make_dynamic()

    def make_dynamic(self) -> bool:
        g = self.root
        if g is None:
            return False
        try:
            new = make_dynamic_in_document(self._window.viewport, g,
                                           g.name or tr("Component"),
                                           self.units.currentData())
        except Exception as exc:  # noqa: BLE001
            _log.exception("make dynamic failed")
            self.status.setText(tr("Could not make it dynamic: {error}",
                                   error=_error_text(exc)))
            return False
        self.show_root(new, self.path)
        return True

    def add_attribute(self, name: str) -> None:
        if not self._ensure_dynamic():
            return
        g = self._part()
        if g is None:
            return
        attrs = AU.merged(g)
        label = AU.LABELS.get(name, name)
        if name in AU.attribute_names(attrs):
            self.status.setText(tr("{name} is already there.", name=label))
            return
        value = ""
        if name in ("x", "y", "z", "lenx", "leny", "lenz"):
            # Starts at what the part measures now.
            try:
                tree, part = self._evaluated_part()
                value = repr(float(_LiveEvaluator(tree).value(part, name)))
            except Exception:  # noqa: BLE001
                value = "0"
        elif name in ("rotx", "roty", "rotz", "copies", "hidden", "scaletool"):
            value = "0"
        self._commit(AU.set_changes(name, value=value),
                     tr("{name} added.", name=label))

    def add_custom(self) -> None:
        if self.root is None:
            return
        name, ok = QInputDialog.getText(self, tr("Add attribute"),
                                        tr("Name (letters, digits, _):"))
        if not ok:
            return
        name = name.strip().lower()
        if not AU.valid_name(name) or name in AU.PREDEFINED_NAMES:
            self.status.setText(tr("«{name}» cannot be an attribute name.",
                                   name=name))
            return
        if not self._ensure_dynamic():
            return
        self._commit(AU.set_changes(name, value="", label=name),
                     tr("{name} added.", name=name))

    def delete_attribute(self) -> None:
        name = self._selected_name()
        g = self._part()
        if not name or g is None:
            return
        self._commit(AU.delete_changes(AU.merged(g), name),
                     tr("{name} deleted.", name=name))

    def edit_options(self) -> None:
        name = self._selected_name()
        g = self._part()
        if not name or g is None:
            self.status.setText(tr("Select an attribute first."))
            return
        dlg = AttributeOptionsDialog(self, name, AU.merged(g))
        if dlg.exec() == QDialog.Accepted:
            self._commit(dlg.changes(name), tr("{name} set.", name=name))
