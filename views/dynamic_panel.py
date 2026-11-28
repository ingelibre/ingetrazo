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
import re

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMenu, QPushButton, QScrollArea, QSplitter, QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core.dynamic import apply as A
from core.dynamic import author as AU
from core.dynamic import formula as F
from core.dynamic import options as O
from core.dynamic.document import (DynamicError, make_dynamic_in_document,
                                   redraw_in_document, selected_one)
from core.dynamic.evaluate import Evaluator, _num
from core.dynamic.messages import tr_msg
from core.dynamic.model import INCH
from core.dynamic.redraw import LEN, _LiveEvaluator, live_value
from core.i18n import tr

_log = logging.getLogger(__name__)

#: Shown in the header, not as options.
HEADER_ONLY = ("name", "itemcode", "summary", "description", "imageurl", "dialogwidth",
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
class UnitLineEdit(QLineEdit):
    """Keep the display unit visible even for empty or unfinished input."""

    def __init__(self, text="", units=None):
        super().__init__(text)
        self.unit_label = QLabel(self)
        self.unit_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.unit_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.textChanged.connect(self._update_unit)
        self.set_display_unit(units)

    def set_display_unit(self, units):
        suffix = O.UNIT_SUFFIX.get(units, {"DEGREES": "°", "PERCENT": "%"}.get(units, ""))
        self.unit_label.setText(suffix)
        self._update_unit()

    def _update_unit(self, *_args):
        text = self.text().strip()
        has_suffix = not text.startswith("=") and re.search(r"[\d.\s](?:mm|cm|in|ft|m|%|°)$", text, re.I)
        visible = bool(self.unit_label.text()) and not has_suffix
        self.unit_label.setVisible(visible)
        width = self.unit_label.sizeHint().width() + 8 if visible else 0
        self.setTextMargins(0, 0, width, 0)
        self.unit_label.setGeometry(max(0, self.width() - width - 6), 0, width, self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "unit_label"):
            self._update_unit()


class StatusLabel(QLabel):
    def setText(self, text):
        super().setText(text)
        self.setVisible(bool(text))


def _button_footer(layout, buttons):
    height = max(button.sizeHint().height() for button in buttons)
    for button in buttons:
        button.setFixedHeight(height)
    footer = QWidget()
    footer.setFixedHeight(height + 16)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setAlignment(Qt.AlignVCenter)
    footer.setLayout(layout)
    return footer


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
        self._preview_root_mesh = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        self.banner = QFrame()
        self.banner.setAutoFillBackground(True)
        self.banner.setBackgroundRole(QPalette.Button)
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(10, 8, 10, 8)
        banner_layout.setSpacing(12)
        self.preview = QLabel()
        self.preview.setFixedSize(88, 88)
        self.preview.setAlignment(Qt.AlignCenter)
        banner_layout.addWidget(self.preview)
        info = QVBoxLayout()
        info.setSpacing(3)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.RichText)
        title_font = QFont(self.title.font())
        title_font.setBold(True)
        title_font.setPointSizeF(title_font.pointSizeF() + 2)
        self.title.setFont(title_font)
        info.addWidget(self.title)
        self.itemcode = QLabel()
        self.itemcode.setTextFormat(Qt.RichText)
        self.itemcode.setWordWrap(True)
        self.itemcode.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.addWidget(self.itemcode)
        info.addStretch(1)
        banner_layout.addLayout(info, 1)
        outer.addWidget(self.banner)
        self.form_host = QFrame()
        self.form_host.setAutoFillBackground(True)
        self.form_host.setBackgroundRole(QPalette.Base)
        body = QVBoxLayout(self.form_host)
        body.setContentsMargins(10, 6, 10, 6)
        body.setSpacing(4)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        summary_font = QFont(self.summary.font())
        summary_font.setBold(True)
        summary_font.setPointSizeF(summary_font.pointSizeF() + 1)
        self.summary.setFont(summary_font)
        body.addWidget(self.summary)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextFormat(Qt.RichText)
        body.addWidget(self.description)
        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form.setHorizontalSpacing(8)
        self.form.setVerticalSpacing(2)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        body.addLayout(self.form)
        body.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.form_host)
        outer.addWidget(self.scroll, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.apply_btn = QPushButton(tr("Apply"))
        self.apply_btn.setToolTip(
            tr("Redraw the component with these options (one undo step)"))
        self.apply_btn.clicked.connect(self.apply)
        self.revert_btn = QPushButton(tr("Revert"))
        self.revert_btn.setToolTip(
            tr("Back to the values it had when you selected it: drops what "
               "you typed, or undoes what you applied (one more undo step)"))
        self.revert_btn.clicked.connect(self.revert)
        from views.icons import tool_icon
        self.interact_btn = QPushButton(tool_icon("interact"), tr("Interact"))
        self.interact_btn.setToolTip(tr("Click a dynamic component to interact"))
        self.interact_btn.clicked.connect(self.activate_interact)
        for b in (self.apply_btn, self.revert_btn, self.interact_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.status = StatusLabel("")
        self.status.hide()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        outer.addWidget(_button_footer(buttons, (self.apply_btn, self.revert_btn, self.interact_btn)))
        self.show_group(None, True)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.ApplicationPaletteChange, QEvent.PaletteChange, QEvent.StyleChange,
                            QEvent.ThemeChange) and hasattr(self, "interact_btn"):
            from views.icons import tool_icon
            self.interact_btn.setIcon(tool_icon("interact"))

    # -- following the selection ------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def refresh(self) -> None:
        if getattr(self._scene(), "_finish_dynamic_preview", None) is not None:
            return
        try:
            g = selected_one(self._scene())
        except Exception:  # noqa: BLE001 - a document switching underneath
            return
        if g is not self.group:
            self.show_group(g)

    def activate_interact(self):
        self._window._activate_tool("interact")
        self._window.activateWindow()
        self._window.viewport.setFocus()

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
        self.description.hide()
        if not dyn:
            self._initial_uid, self._initial, self._current = None, {}, {}
            self.title.setText(tr("Select a dynamic component to see its options."))
            self.itemcode.clear()
            self.itemcode.hide()
            self.preview.clear()
            self.preview.hide()
            return
        root, _frame = A.part_in_context(self._scene(), group)
        ev = _LiveEvaluator(root)
        opts = [o for o in O.options_of(root.attrs) if o.name not in HEADER_ONLY]
        self.title.setText(str(root.attrs.get("name") or _html(root.name)))
        self.itemcode.setText(str(root.attrs.get("itemcode") or ""))
        self.itemcode.setVisible(bool(self.itemcode.text()))
        self._update_preview(group)
        summary = str(root.attrs.get("summary") or "").strip()
        if summary and str(root.attrs.get("_summary_access") or "").upper() != "NONE":
            self.summary.setText(summary)
            self.summary.show()
        description = str(root.attrs.get("description") or "").strip()
        if description:
            self.description.setText(description)
            self.description.show()
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
                w = UnitLineEdit(O.display(opt), opt.units)
                w.returnPressed.connect(lambda: QTimer.singleShot(0, self.apply))
                initial = w.text()
            w.setFixedHeight(max(22, w.fontMetrics().height() + 8))
            if isinstance(w, QLineEdit):
                w.setStyleSheet("QLineEdit { padding: 1px 5px; }")
            if isinstance(w, (QLineEdit, QComboBox)):
                w.setMinimumWidth(120)
            label = QLabel(opt.label)
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(False)
            label.setToolTip(opt.label)
            self.form.addRow(label, w)
            self.rows.append((opt, w, initial))
        self._current = {o.name: o.value for o in opts if o.access != "VIEW"}
        if group.uid != self._initial_uid:
            # Newly selected: this is what Revert will go back to. A redraw
            # keeps the uid, so Apply does not move the mark.
            self._initial_uid = group.uid
            self._initial = dict(self._current)

    def _update_preview(self, group):
        from types import SimpleNamespace
        from core.mesh import Mesh
        from views.component_thumbs import thumbnail

        def visible(part):
            return SimpleNamespace(mesh=part.mesh, xform=part.xform, material=part.material,
                                   children=[visible(child) for child in part.children
                                             if not child.hidden])

        try:
            if self._preview_root_mesh is None:
                self._preview_root_mesh = Mesh()
            # Thumbnail definitions omit their outer placement. Wrapping this
            # instance keeps its current scale/rotation in the small picture.
            definition = SimpleNamespace(mesh=self._preview_root_mesh, material=None,
                                         children=[visible(group)])
            self.preview.setPixmap(thumbnail(definition, size=84))
            self.preview.show()
        except Exception:  # noqa: BLE001 - malformed geometry must not block options
            _log.exception("dynamic component preview failed")
            self.preview.clear()
            self.preview.hide()

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


def _plain_text(value) -> str:
    """SketchUp's Name/ItemCode can contain HTML; show their readable text."""
    text = str(value)
    if "<" not in text:
        return text
    document = QTextDocument()
    document.setHtml(text)
    return document.toPlainText()


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
        explicit = str(attrs.get(f"_{name}_units") or "").upper()
        return explicit if explicit in INCH else part_unit
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


class AttributeLabels(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if index.column() == 1 and not option.text and index.data(Qt.UserRole + 4):
            option.text = index.data(Qt.UserRole + 4)
            option.displayAlignment = Qt.AlignRight | Qt.AlignVCenter
        if index.column() == 0:
            option.text = "  " + option.text
            brush = index.data(Qt.ForegroundRole)
            if brush is not None:
                option.palette.setBrush(QPalette.HighlightedText, brush)


class AttributeBlockOutline(QWidget):
    """Draw above cell widgets so headers cannot cover the rounded frame."""

    def __init__(self, table):
        super().__init__(table.viewport())
        self.table = table
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, event):
        table = self.table
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        border = self.palette().text().color()
        border.setAlpha(110)
        for first, last in table.blocks:
            bottom = next((r for r in range(last, first - 1, -1)
                           if not table.isRowHidden(r)), first)
            top = table.rowViewportPosition(first)
            height = table.rowViewportPosition(bottom) + table.rowHeight(bottom) - top
            if top + height < 0 or top >= self.height():
                continue
            frame = QPainterPath()
            frame.addRoundedRect(QRectF(2, top + 1, self.width() - 5, height - 2), 8, 8)
            outside = QPainterPath()
            outside.addRect(QRectF(0, top, self.width(), height))
            painter.fillPath(outside.subtracted(frame), self.palette().window())
            painter.setPen(QPen(border, 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(frame)
        painter.end()


class AttributeSheet(QTableWidget):
    """One scrollable sheet; rounded frames separate the component blocks."""

    def __init__(self):
        super().__init__(0, 4)
        self.blocks = []
        self.setItemDelegate(AttributeLabels(self))
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(25)
        self._outline = AttributeBlockOutline(self)
        self._frame_refresh = QTimer(self)
        self._frame_refresh.setSingleShot(True)
        self._frame_refresh.timeout.connect(self._redraw_block_frames)

    def refresh_block_frames(self):
        # Row visibility changes use partial viewport repaints. The overlay
        # needs a full repaint after the new row positions have settled.
        self._frame_refresh.start(0)

    def _redraw_block_frames(self):
        self.doItemsLayout()
        self.viewport().update()
        self._outline.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        self._outline.setGeometry(self.viewport().rect())
        self._outline.raise_()


class DynamicDialog(QDialog):
    """Owned Windows dialogs minimize to the bottom of the work area."""

    minimized_slot = 0

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self._place_minimized)

    def _place_minimized(self):
        import sys
        if sys.platform != "win32" or not self.isMinimized():
            return
        import ctypes
        from ctypes import wintypes as W

        class Placement(ctypes.Structure):
            _fields_ = [("length", W.UINT), ("flags", W.UINT), ("showCmd", W.UINT),
                        ("ptMinPosition", W.POINT), ("ptMaxPosition", W.POINT),
                        ("rcNormalPosition", W.RECT)]

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT),
                        ("rcWork", W.RECT), ("dwFlags", W.DWORD)]

        api = ctypes.windll.user32
        api.MonitorFromWindow.argtypes = [W.HWND, W.DWORD]
        api.MonitorFromWindow.restype = W.HANDLE
        api.GetMonitorInfoW.argtypes = [W.HANDLE, ctypes.POINTER(MonitorInfo)]
        api.GetWindowPlacement.argtypes = [W.HWND, ctypes.POINTER(Placement)]
        api.SetWindowPlacement.argtypes = [W.HWND, ctypes.POINTER(Placement)]
        hwnd = W.HWND(int(self.winId()))
        placement = Placement()
        placement.length = ctypes.sizeof(placement)
        monitor = MonitorInfo()
        monitor.cbSize = ctypes.sizeof(monitor)
        if not (api.GetWindowPlacement(hwnd, ctypes.byref(placement))
                and api.GetMonitorInfoW(api.MonitorFromWindow(hwnd, 2), ctypes.byref(monitor))):
            return
        # Placement coordinates are relative to the monitor work area.
        x = self.minimized_slot * (api.GetSystemMetrics(57) + 4)
        y = max(0, monitor.rcWork.bottom - monitor.rcWork.top - api.GetSystemMetrics(58))
        if placement.flags & 1 and (placement.ptMinPosition.x, placement.ptMinPosition.y) == (x, y):
            return
        placement.flags |= 1  # WPF_SETMINPOSITION; preserve restore geometry.
        placement.ptMinPosition.x, placement.ptMinPosition.y = x, y
        api.SetWindowPlacement(hwnd, ctypes.byref(placement))


class AttributesDialog(DynamicDialog):
    """Make a component dynamic and edit its parts' attributes and
    formulas. Every change redraws the component as one undo step."""

    def __init__(self, window, options_panel=None) -> None:
        super().__init__(window if isinstance(window, QWidget) else None)
        self._window = window
        self._options = options_panel
        self.root = None
        self.path = ()
        self._filling = False
        self._draft = False
        self._edit_target = None
        self._cell_editor = None
        self._cell_editor_row = None
        self._section_rows = {}
        self._attribute_rows = {}
        self._attribute_display_units = {}
        self._attribute_option_buttons = {}
        self._options_icon_accent = None
        self._block_rows = {}
        self._collapsed = set()
        self._block_buttons = {}
        self._unit_buttons = {}
        self._block_add_buttons = []
        self._default_display_unit = None  # preserve each imported attribute's display unit
        self._display_units = {}
        self._axis_colors = None
        self._selection_color = None
        self.setWindowTitle(tr("Component attributes"))
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        self.resize(980, 720)
        outer = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.RichText)
        mk = QHBoxLayout()
        mk.addWidget(self.title, 1)
        mk.addStretch(1)
        mk.addWidget(QLabel(tr("Display in")))
        self.display_unit_combo = QComboBox()
        self.display_unit_combo.addItem(tr("Original"), None)
        for key, text in UNITS:
            self.display_unit_combo.addItem(tr(text), key)
        self.display_unit_combo.currentIndexChanged.connect(self._choose_display_unit)
        mk.addWidget(self.display_unit_combo)
        self.display_units_btn = QToolButton()
        self.display_units_btn.setText("cm / inch")
        self.display_units_btn.setToolTip(tr("Centimeters") + " / " + tr("Inches"))
        self.display_units_btn.clicked.connect(self._toggle_display_units)
        mk.addWidget(self.display_units_btn)
        outer.addLayout(mk)
        edit = QHBoxLayout()
        self.edit_target = QLabel(tr("Value or =formula"))
        self.edit_target.setMinimumWidth(160)
        self.edit_target.setMaximumWidth(280)
        self.edit_target.setWordWrap(True)
        self.formula_edit = UnitLineEdit()
        self._formula_input = self.formula_edit
        self._formula_selection = None
        self.formula_edit.setPlaceholderText(tr("Value or =formula"))
        self.formula_edit.textEdited.connect(self._formula_edited)
        self.formula_edit.returnPressed.connect(self.apply_formula)
        self.formula_edit.installEventFilter(self)
        self.formula_apply = QPushButton(tr("Apply"))
        self.formula_apply.setAutoDefault(False)
        self.formula_apply.clicked.connect(self.apply_formula)
        self.formula_cancel = QPushButton(tr("Cancel"))
        self.formula_cancel.setAutoDefault(False)
        self.formula_cancel.clicked.connect(self.cancel_formula)
        edit.addWidget(self.edit_target)
        edit.addWidget(self.formula_edit, 1)
        edit.addWidget(self.formula_apply)
        edit.addWidget(self.formula_cancel)
        outer.addLayout(edit)
        hint = QLabel(tr("Start with =, then click another attribute to insert a reference. "
                         "Enter applies; Esc cancels."))
        hint.setWordWrap(True)
        outer.addWidget(hint)
        split = QSplitter(Qt.Horizontal)
        self._sheet_split = split
        self._tree_width = 190
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._tree_changed)
        split.addWidget(self.tree)
        self._table_container = QWidget()
        table_layout = QHBoxLayout(self._table_container)
        table_layout.setContentsMargins(16, 0, 0, 0)
        self.table = AttributeSheet()
        table_layout.addWidget(self.table)
        self.table.setHorizontalHeaderLabels(
            [tr("Attribute"), tr("Value or =formula"), tr("Result"), ""])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 28)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.currentCellChanged.connect(self._table_selected)
        self.table.cellDoubleClicked.connect(self._edit_selected)
        self.table.installEventFilter(self)
        self.table.viewport().installEventFilter(self)
        split.addWidget(self._table_container)
        split.setStretchFactor(1, 2)
        split.setSizes([190, 750])
        sheet_row = QHBoxLayout()
        sheet_row.setContentsMargins(0, 0, 0, 0)
        sheet_row.setSpacing(2)
        # A direct child of QSplitter becomes a third pane and its fixed
        # height constrains the entire sheet. Overlay the dialog instead.
        self.tree_toggle = QToolButton(self)
        self.tree_toggle.setFixedSize(14, 56)
        self.tree_toggle.setIconSize(QSize(12, 12))
        from views.icons import tool_icon
        from views.theme import style as theme_style
        self.tree_toggle.setIcon(tool_icon("side_expand"))
        self.tree_toggle.setAutoRaise(True)
        self.tree_toggle.setCursor(Qt.PointingHandCursor)
        theme_style(self.tree_toggle,
                    "QToolButton {{ background: palette(mid); border: none; border-radius: 4px; }}"
                    "QToolButton:hover {{ background: rgb({accent_rgb}); }}")
        self.tree_toggle.setToolTip(self.windowTitle())
        self.tree_toggle.clicked.connect(self._toggle_tree)
        sheet_row.addWidget(split, 1)
        split.installEventFilter(self)
        split.splitterMoved.connect(lambda *_: self._place_tree_handle())
        outer.addLayout(sheet_row, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.add_btn = QPushButton(tr("Add attribute"))
        self.add_btn.setAutoDefault(False)
        self.add_btn.setMenu(self._attribute_menu(self.add_btn))
        self.del_btn = QPushButton(tr("Delete"))
        self.del_btn.setAutoDefault(False)
        self.del_btn.setToolTip(tr("Delete the selected attribute"))
        self.del_btn.clicked.connect(self.delete_attribute)
        from core.dynamic.catalog import category, entries
        self.function_combo = QComboBox()
        self.function_combo.setMinimumWidth(230)
        self.function_combo.setMaximumWidth(300)
        self.function_combo.setMaxVisibleItems(18)
        self.function_combo.addItem(tr("Functions"), None)
        def heading(label):
            self.function_combo.addItem(label, None)
            item = self.function_combo.model().item(self.function_combo.count() - 1)
            item.setFlags(Qt.ItemIsEnabled)
            font = QFont(item.font())
            font.setBold(True)
            item.setFont(font)
            item.setBackground(self.palette().button())

        for group, title in (("math", tr("Maths")), ("context", "IngeTrazo"),
                             ("trig", tr("Trigonometry")), ("texture", tr("Texture")),
                             ("text", tr("Text")), ("logic", tr("Logic")), ("onclick", "onClick")):
            heading(title)
            for name, signature, kind, supported in entries():
                if category(name) != group:
                    continue
                label = "    " + signature
                if not supported:
                    label += " — " + tr("Not yet supported")
                self.function_combo.addItem(label, (name, kind, supported))
                item = self.function_combo.model().item(self.function_combo.count() - 1)
                item.setToolTip(label.strip())
                item.setEnabled(supported)
        heading(tr("Operators"))
        for operator in ("+", "-", "*", "/", "^", "&", "()", "<", ">", "=", "<=", ">=", "<>"):
            self.function_combo.addItem(operator, (operator, "operator", True))
        self.insert_function_btn = QPushButton(tr("Insert"))
        self.insert_function_btn.setAutoDefault(False)
        self.insert_function_btn.clicked.connect(self.insert_function)
        self.function_combo.currentIndexChanged.connect(self._edit_controls)
        for w in (self.add_btn, self.del_btn, self.function_combo, self.insert_function_btn):
            row.addWidget(w)
        row.addStretch(1)
        self.status = StatusLabel("")
        self.status.hide()
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        outer.addWidget(_button_footer(row, (self.add_btn, self.del_btn, self.function_combo,
                                            self.insert_function_btn)))
        self._refresh_enabled()
        self.formula_edit.setEnabled(False)
        self._edit_controls()
        self._sync_timer = QTimer(self)
        self._sync_timer.setInterval(150)
        self._sync_timer.timeout.connect(self._sync_root)

    def _toggle_tree(self):
        from views.icons import tool_icon
        if not self.tree.isHidden():
            self._tree_width = max(100, self._sheet_split.sizes()[0])
            self.tree.hide()
            self.tree_toggle.setIcon(tool_icon("side_collapse"))
        else:
            self.tree.show()
            self._sheet_split.setSizes([self._tree_width,
                                        max(100, self._sheet_split.width() - self._tree_width)])
            self.tree_toggle.setIcon(tool_icon("side_expand"))
        QTimer.singleShot(0, self._place_tree_handle)

    def _place_tree_handle(self):
        split = self._sheet_split
        x = 0 if self.tree.isHidden() else split.sizes()[0] - 7
        self.tree_toggle.move(split.mapTo(self, QPoint(max(0, x), max(0, (split.height() - 56) // 2))))
        self.tree_toggle.raise_()

    def _attribute_menu(self, parent):
        menu = QMenu(parent)
        for title, items in AU.GROUPS:
            if menu.actions():
                menu.addSeparator()
            section = menu.addAction(tr(SECTION_LABELS.get(title, title)))
            font = QFont(section.font())
            font.setBold(True)
            section.setFont(font)
            section.setToolTip(", ".join(AU.LABELS[n] for n, _u in items))
            section.triggered.connect(
                lambda _checked=False, members=items, label=title:
                self.add_attributes([n for n, _u in members],
                                    tr(SECTION_LABELS.get(label, label))))
            for name, _u in items:
                menu.addAction("    " + AU.LABELS[name],
                               lambda n=name: self.add_attribute(n))
        menu.addSeparator()
        menu.addAction(tr("Custom name…"), self.add_custom)
        return menu

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer.start()

    def hideEvent(self, event):
        self._sync_timer.stop()
        super().hideEvent(event)

    def _sync_root(self):
        self._refresh_axis_colors()
        if getattr(
                self._scene(), "_finish_dynamic_preview", None) is not None:
            return
        if self.root is None:
            self._follow_scene_selection()
            return
        selection = self._selection_key()
        selection_changed = selection != self._selection_seen
        if not self._draft and self._display_version != self._scene().version:
            from core.group import iter_placements
            current = next((g for top in self._scene().groups
                            for g, _matrix in iter_placements(top) if g.uid == self.root.uid), None)
            if (current is not self.root
                    or self._display_content_version != self._scene().content_version):
                self.show_root(current, self.path)
            else:
                self._display_version = self._scene().version
        if selection_changed:
            self._selection_seen = selection
            self._follow_scene_selection()

    def _selection_key(self):
        return (frozenset(id(e) for e in self._scene().selection),
                id(getattr(self._scene(), "edit_group", None)))

    def _follow_scene_selection(self):
        selected = list(self._scene().selection)
        if not selected and getattr(self._scene(), "edit_group", None) is not None:
            selected = [self._scene().edit_group]
        if len(selected) != 1:
            return
        target = selected[0]
        # Shared geometry is not an identity: recover any placement proxy.
        wanted = next((key for key, proxy in
                       (getattr(self._window.viewport, "_placement_proxies", None) or {}).items()
                       if proxy is target), id(target))
        paths = getattr(self, "_group_paths", {})
        path = paths.get(wanted)
        if path is None:
            path = paths.get(id(getattr(target, "owner", None)))
        if path is None:
            from core.outliner import walk
            hit = next((g for g, _parent, _depth in walk(self._scene().groups)
                        if id(g) == wanted), None)
            if hit is not None:
                if self._draft and not self.apply_formula():
                    return
                self.show_root(hit)
            return
        blocked = self.tree.blockSignals(True)
        try:
            self._select_tree(path)
        finally:
            self.tree.blockSignals(blocked)
        self._expand_block(path)
        if self._draft:
            self._scroll_to(path)
        else:
            self._select_attribute(path)

    def _refresh_axis_colors(self):
        from core.modeling_style import modeling_color
        from views.theme import accent_color
        accent = accent_color().name()
        if accent != self._options_icon_accent:
            from views.icons import tool_icon
            self._options_icon_accent = accent
            icon = tool_icon("panel_properties")
            for button in self._attribute_option_buttons.values():
                button.setIcon(icon)
        selected = modeling_color(self._scene().display_style, "selected")
        color = QColor.fromRgbF(*selected)
        if (selected != self._selection_color or any(
                widget.palette().color(state, QPalette.Highlight) != color
                for widget in (self, self.tree, self.table)
                for state in (QPalette.Active, QPalette.Inactive))):
            self._selection_color = selected
            color = QColor.fromRgbF(*selected)
            text = (Qt.black if sum(a * b for a, b in zip(selected, (.299, .587, .114))) > .55
                    else Qt.white)
            palette = QPalette(self.palette())
            for group in (QPalette.Active, QPalette.Inactive):
                palette.setColor(group, QPalette.Highlight, color)
                palette.setColor(group, QPalette.HighlightedText, QColor(text))
            self.setPalette(palette)
            self.tree.setPalette(palette)
            self.table.setPalette(palette)
        colors = tuple(modeling_color(self._scene().display_style, "axis_" + axis)
                       for axis in ("x", "y", "z"))
        if colors == self._axis_colors:
            return
        self._axis_colors = colors
        for (_path, name), row in self._attribute_rows.items():
            if name in ("x", "y", "z", "lenx", "leny", "lenz", "rotx", "roty", "rotz"):
                self.table.item(row, 0).setForeground(QColor.fromRgbF(*colors["xyz".index(name[-1])]))

    def _scene(self):
        return self._window.viewport.scene

    def _refresh_enabled(self) -> None:
        for w in (self.add_btn, self.del_btn, self.function_combo, self.table,
                  self.tree):
            w.setEnabled(self.root is not None)

    def show_root(self, root, path=()) -> None:
        self._close_cell_editor()
        self._draft = False
        self._edit_target = None
        self.root, self.path = root, tuple(path)
        while self.path and (root is None or part_at(root, self.path) is None):
            self.path = self.path[:-1]
        self._display_version = self._scene().version
        self._display_content_version = self._scene().content_version
        self._selection_seen = self._selection_key()
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

    def _display_unit(self, path, native=None):
        group = part_at(self.root, path)
        return (self._display_units.get(group.uid) or self._default_display_unit
                or native or self._part_unit(AU.merged(group)))

    def _choose_display_unit(self, _index):
        if self._draft:
            return
        self._close_cell_editor()
        self._default_display_unit = self.display_unit_combo.currentData()
        self._display_units.clear()
        self._sync_display_controls()
        self.show_part()

    def _sync_display_controls(self):
        blocked = self.display_unit_combo.blockSignals(True)
        self.display_unit_combo.setCurrentIndex(self.display_unit_combo.findData(self._default_display_unit))
        self.display_unit_combo.blockSignals(blocked)
        self.display_units_btn.setText(O.UNIT_SUFFIX.get(self._default_display_unit, "cm / inch"))

    def _toggle_display_units(self, _checked=False, path=None):
        if self._draft:
            return
        self._close_cell_editor()
        if path is None:
            current = self._display_unit(()) if self.root is not None else "CENTIMETERS"
            self._default_display_unit = ("INCHES" if current == "CENTIMETERS"
                                          else "CENTIMETERS")
            self._display_units.clear()
        else:
            group = part_at(self.root, path)
            self._display_units[group.uid] = ("INCHES" if self._display_unit(path) == "CENTIMETERS"
                                              else "CENTIMETERS")
        self._sync_display_controls()
        self.show_part()

    def _toggle_block(self, path):
        group = part_at(self.root, path)
        if self._draft and self._edit_target[0] == path:
            return
        if group.uid in self._collapsed:
            self._collapsed.remove(group.uid)
        else:
            self._collapsed.add(group.uid)
        self._apply_block_visibility(path)

    def _expand_block(self, path):
        if path not in self._block_rows:
            return
        self._collapsed.discard(part_at(self.root, path).uid)
        self._apply_block_visibility(path)

    def _apply_block_visibility(self, path):
        first, last = self._block_rows[path]
        collapsed = part_at(self.root, path).uid in self._collapsed
        for row in range(first + 1, last + 1):
            self.table.setRowHidden(row, collapsed)
        self._block_buttons[path].setArrowType(Qt.RightArrow if collapsed else Qt.DownArrow)
        self.table.viewport().update()
        self.table.refresh_block_frames()

    def _block_attribute_menu(self, path, button):
        if self._draft:
            return
        self._select_attribute(path)
        menu = self._attribute_menu(button)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(button.mapToGlobal(button.rect().bottomLeft()))

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
        path = tuple(cur.data(0, Qt.UserRole) or ())
        if self._reference_mode():
            self._expand_block(path)
            self._scroll_to(path)
            return
        if self._draft and not self.apply_formula():
            return
        self.path = path
        self._select_attribute(path)

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
        """One sheet for the entire component, with a section per part."""
        selected = self._selected_name()
        self._close_cell_editor()
        self._filling = True
        try:
            self.table.blocks = []
            self.table.clearSpans()
            self.table.setRowCount(0)
            self._section_rows = {}
            self._attribute_rows = {}
            self._attribute_display_units = {}
            self._attribute_option_buttons = {}
            self._block_rows = {}
            self._group_paths = {}
            self._block_buttons = {}
            self._unit_buttons = {}
            self._block_add_buttons = []
            if self.root is None:
                self.formula_edit.clear()
                self.formula_edit.setEnabled(False)
                self._edit_controls()
                return
            try:
                tree = A.part_in_context(self._scene(), self.root)[0]
                ev = _LiveEvaluator(tree)
            except Exception:  # noqa: BLE001
                tree, ev = None, None

            def fill(g, path, part):
                attrs = AU.merged(g)
                copy = _num(attrs.get("copy"))
                if isinstance(copy, float) and copy > 0:
                    return              # generated copies are edited at their original
                r = self.table.rowCount()
                if r:
                    self.table.insertRow(r)
                    self.table.setRowHeight(r, 20)
                    spacer = QTableWidgetItem()
                    spacer.setFlags(Qt.NoItemFlags)
                    spacer.setBackground(self.table.palette().window())
                    self.table.setItem(r, 0, spacer)
                    self.table.setSpan(r, 0, 1, 4)
                    r += 1
                self.table.insertRow(r)
                self._group_paths[id(g)] = path
                part_name = str(attrs.get("_name") or g.name or tr("(part)"))
                title = QTableWidgetItem()
                title.setData(Qt.UserRole + 1, path)
                title.setData(Qt.UserRole + 2, "component")
                title.setData(Qt.UserRole + 3, part_name)
                title.setFlags(title.flags() & ~Qt.ItemIsEditable)
                font = QFont()
                font.setBold(True)
                header_font = QFont(self.table.font())
                header_font.setBold(True)
                header_font.setPointSizeF(header_font.pointSizeF() + 1)
                title.setFont(header_font)
                title.setBackground(self.table.palette().button())
                self.table.setItem(r, 0, title)
                self.table.setSpan(r, 0, 1, 4)
                self.table.setRowHeight(r, 32)
                self._section_rows[path] = r
                header = QWidget()
                header.setAutoFillBackground(True)
                header.setBackgroundRole(QPalette.Button)
                layout = QHBoxLayout(header)
                layout.setContentsMargins(8, 0, 8, 0)
                toggle = QToolButton()
                toggle.setText(part_name)
                toggle.setFont(header_font)
                toggle.setStyleSheet("QToolButton { font-weight: 700; font-size: %spt; }"
                                    % header_font.pointSizeF())
                toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                toggle.setAutoRaise(True)
                toggle.clicked.connect(lambda _checked=False, p=path: self._toggle_block(p))
                layout.addWidget(toggle)
                layout.addStretch(1)
                unit_button = QToolButton()
                unit_button.setText(O.UNIT_SUFFIX[self._display_unit(path)])
                unit_button.setToolTip(self.display_units_btn.toolTip())
                unit_button.clicked.connect(lambda _checked=False, p=path: self._toggle_display_units(path=p))
                layout.addWidget(unit_button)
                self.table.setCellWidget(r, 0, header)
                self._block_buttons[path] = toggle
                self._unit_buttons[path] = unit_button
                unit = self._part_unit(attrs)
                names = AU.attribute_names(attrs)
                # Keep component information first, then the author's own
                # parameters before the geometric and behaviour attributes.
                for label, members in (AU.GROUPS[0], (None, ()), *AU.GROUPS[1:]):
                    subset = ([name for name, _u in members if name in names] if label else
                              [name for name in names if name not in AU.PREDEFINED_NAMES])
                    if not subset:
                        continue
                    if label:
                        section = QTableWidgetItem(tr(SECTION_LABELS.get(label, label)))
                        section.setFont(font)
                        section.setBackground(self.table.palette().button())
                        section.setFlags(Qt.ItemIsEnabled)
                        section.setData(Qt.UserRole + 1, path)
                        section.setData(Qt.UserRole + 2, "category")
                        row = self.table.rowCount()
                        self.table.insertRow(row)
                        self.table.setItem(row, 0, section)
                        self.table.setSpan(row, 0, 1, 4)
                    for name in subset:
                        self._add_attribute_row(path, name, attrs, unit, part, ev)
                footer = self.table.rowCount()
                self.table.insertRow(footer)
                self.table.setRowHeight(footer, 32)
                self.table.setSpan(footer, 0, 1, 4)
                button = QToolButton()
                button.setText("+ " + tr("Add attribute"))
                button.setAutoRaise(True)
                button.clicked.connect(lambda _checked=False, p=path, b=button: self._block_attribute_menu(p, b))
                footer_widget = QWidget()
                footer_layout = QHBoxLayout(footer_widget)
                footer_layout.setContentsMargins(8, 0, 8, 0)
                footer_layout.addWidget(button)
                footer_layout.addStretch(1)
                self.table.setCellWidget(footer, 0, footer_widget)
                self._block_add_buttons.append(button)
                self._block_rows[path] = (r, footer)
                self.table.blocks.append((r, footer))
                self._apply_block_visibility(path)
                for i, child in enumerate(g.children or ()):
                    child_part = part.children[i] if part is not None else None
                    fill(child, path + (i,), child_part)

            fill(self.root, (), tree)
            self.table.setColumnWidth(0, 220)
            self.table.setColumnWidth(2, 140)
            self._axis_colors = None
            self._refresh_axis_colors()
        finally:
            self._filling = False
        self._select_attribute(self.path, selected)

    def _add_attribute_row(self, path, name, attrs, unit, part, ev):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._attribute_rows[(path, name)] = r
        head = QTableWidgetItem(AU.LABELS.get(name, name))
        head.setData(Qt.UserRole, name)
        head.setData(Qt.UserRole + 1, path)
        head.setFlags(head.flags() & ~Qt.ItemIsEditable)
        f = attrs.get(f"_{name}_formula")
        units = _units_of(attrs, name, unit)
        if units in INCH:
            units = self._display_unit(path, units)
        self._attribute_display_units[(path, name)] = units
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
        value_item = QTableWidgetItem(text)
        value_item.setData(Qt.UserRole + 4, O.UNIT_SUFFIX.get(units, ""))
        self.table.setItem(r, 1, value_item)
        self.table.setItem(r, 2, res)
        from views.icons import tool_icon
        button = QToolButton()
        button.setAutoRaise(True)
        button.setIcon(tool_icon("panel_properties"))
        button.setIconSize(QSize(14, 14))
        button.setToolTip(tr("Options…"))
        button.clicked.connect(lambda _checked=False, p=path, n=name: self._row_options(p, n))
        self.table.setCellWidget(r, 3, button)
        self._attribute_option_buttons[(path, name)] = button

    def _row_options(self, path, name):
        if self._draft:
            return
        self._select_attribute(path, name)
        self.edit_options()

    def _scroll_to(self, path):
        row = self._section_rows.get(tuple(path))
        if row is not None:
            self.table.scrollToItem(self.table.item(row, 0), QAbstractItemView.PositionAtTop)

    def _select_attribute(self, path, name=None):
        path = tuple(path)
        self._expand_block(path)
        row = self._attribute_rows.get((path, name)) if name else None
        if row is None:
            row = next((r for (p, _n), r in self._attribute_rows.items() if p == path),
                       self._section_rows.get(path))
        if row is not None:
            self.table.setCurrentCell(row, 1 if (path, name) in self._attribute_rows else 0)
            self._table_selected(row, self.table.currentColumn(), -1, -1)
            self._scroll_to(path)
        else:
            self._edit_target = None
            self.formula_edit.clear()
            self.formula_edit.setEnabled(False)
        self._edit_controls()

    def _table_selected(self, row, _column, *_previous):
        if self._filling or self._draft:
            return
        head = self.table.item(row, 0)
        name = head.data(Qt.UserRole) if head else None
        path = tuple(head.data(Qt.UserRole + 1) or ()) if head else self.path
        if self._cell_editor is not None and name and self._edit_target == (path, name):
            return
        self._close_cell_editor()
        self.path = path
        was_blocked = self.tree.blockSignals(True)
        try:
            self._select_tree(path)
        finally:
            self.tree.blockSignals(was_blocked)
        self._edit_target = (path, name) if name else None
        self.edit_target.setText(
            "%s ! %s" % (AU.merged(self._part()).get("_name") or self._part().name,
                          AU.LABELS.get(name, name)) if name else tr("Value or =formula"))
        self.formula_edit.setText(self.table.item(row, 1).text() if name else "")
        self.formula_edit.set_display_unit(self._attribute_display_units.get((path, name)))
        self.formula_edit.setEnabled(bool(name))
        self._edit_controls()

    def _edit_controls(self, *_args):
        self.formula_apply.setEnabled(self._draft)
        self.formula_cancel.setEnabled(self._draft)
        self.display_units_btn.setEnabled(not self._draft)
        self.display_unit_combo.setEnabled(not self._draft)
        for button in (*self._unit_buttons.values(), *self._block_add_buttons):
            button.setEnabled(not self._draft)
        for button in self._attribute_option_buttons.values():
            button.setEnabled(not self._draft)
        if hasattr(self, "add_btn"):
            self.add_btn.setEnabled(self.root is not None and not self._draft)
            self.del_btn.setEnabled(self._edit_target is not None and not self._draft)
            entry = self.function_combo.currentData()
            allowed = (entry is not None and entry[2] and self._edit_target is not None
                       and (entry[1] != "action" or self._edit_target[1] == "onclick"))
            self.insert_function_btn.setEnabled(bool(allowed))

    def insert_function(self):
        entry = self.function_combo.currentData()
        if not self.insert_function_btn.isEnabled() or entry is None:
            return
        name, kind, _supported = entry
        onclick = self._edit_target[1] == "onclick"
        if not self._draft:
            editor = self._formula_input
            if not onclick and not editor.text().lstrip().startswith("="):
                if self._cell_editor is None:
                    self._edit_selected(self.table.currentRow(), 1)
                editor = self._cell_editor
                editor.clear()
                editor.insert("=")
        else:
            editor = self._formula_input
        saved = self._formula_selection
        if saved is not None and saved[0] is editor and saved[1] == editor.text():
            _input, _text, cursor, selection, length = saved
            if selection >= 0:
                editor.setSelection(selection, length)
            else:
                editor.setCursorPosition(cursor)
        self._formula_selection = None
        if kind == "action":
            if editor.text() and editor.cursorPosition() == len(editor.text()) and not editor.text().endswith(';'):
                editor.insert(';')
            snippet = ('REDRAW()' if name == 'REDRAW' else
                       'ANIMATECUSTOM("",1,0,100,0,1)' if name == 'ANIMATECUSTOM' else name + '("",0,1)')
        elif kind == "operator":
            snippet = name
        elif name in ('TRUE', 'FALSE'):
            snippet = name
        else:
            snippet = name + '()'
        start = editor.selectionStart() if editor.hasSelectedText() else editor.cursorPosition()
        editor.insert(snippet)
        if '(' in snippet and name not in ('PI', 'REDRAW'):
            editor.setCursorPosition(start + snippet.index('(') + 1 + (1 if kind == 'action' else 0))
        if editor is self._cell_editor:
            self._cell_formula_edited(editor.text())
        else:
            self._formula_edited(editor.text())
        editor.setFocus()

    def _edit_selected(self, row, _column):
        if self._edit_target is not None:
            row = self._attribute_rows[self._edit_target]
            if self._cell_editor is None:
                editor = UnitLineEdit(self.formula_edit.text(), self._attribute_display_units[self._edit_target])
                editor.setFrame(False)
                editor.textEdited.connect(self._cell_formula_edited)
                editor.installEventFilter(self)
                self._cell_editor, self._cell_editor_row = editor, row
                self.table.setCellWidget(row, 1, editor)
            self.table.scrollToItem(self.table.item(row, 1))
            self._formula_input = self._cell_editor
            self._cell_editor.setFocus()
            self._cell_editor.selectAll()

    def _close_cell_editor(self):
        if self._cell_editor is not None:
            editor, row = self._cell_editor, self._cell_editor_row
            self._cell_editor = self._cell_editor_row = None
            self._formula_input = self.formula_edit
            editor.removeEventFilter(self)
            self.table.removeCellWidget(row, 1)

    def _cell_formula_edited(self, text):
        self._formula_input = self._cell_editor
        self.formula_edit.setText(text)
        self._mark_draft()

    def _formula_edited(self, text):
        self._formula_input = self.formula_edit
        if self._cell_editor is not None and self._cell_editor.text() != text:
            self._cell_editor.setText(text)
        self._mark_draft()

    def _mark_draft(self):
        if self._edit_target is not None:
            self._draft = True
            self._edit_controls()

    def _reference_mode(self):
        return self._draft and self.formula_edit.text().lstrip().startswith("=")

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_sheet_split", None) and event.type() in (
                QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            QTimer.singleShot(0, self._place_tree_handle)
        if not hasattr(self, "table"):
            return super().eventFilter(obj, event)
        if event.type() == QEvent.FocusIn and obj in (self.formula_edit, self._cell_editor):
            self._formula_input = obj
            self._formula_selection = None
        if event.type() == QEvent.FocusOut and obj in (self.formula_edit, self._cell_editor):
            self._formula_selection = (obj, obj.text(), obj.cursorPosition(), obj.selectionStart(),
                                       len(obj.selectedText()))
        if obj is self.table.viewport() and event.type() in (
                QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick):
            if event.button() == Qt.LeftButton:
                index = self.table.indexAt(event.position().toPoint())
                if self._reference_mode():
                    if event.type() == QEvent.MouseButtonPress and index.isValid():
                        self._insert_reference(index.row())
                    return True
                if self._draft and event.type() == QEvent.MouseButtonPress and index.isValid():
                    head = self.table.item(index.row(), 0)
                    path, name = tuple(head.data(Qt.UserRole + 1) or ()), head.data(Qt.UserRole)
                    if self.apply_formula():
                        self._select_attribute(path, name)
                        if index.column() == 1 and name:
                            self._edit_selected(self.table.currentRow(), 1)
                    return True
                if (event.type() == QEvent.MouseButtonPress and index.isValid()
                        and index.column() == 1 and self.table.item(index.row(), 1) is not None):
                    self.table.setCurrentCell(index.row(), 1)
                    self._edit_selected(index.row(), 1)
                    return True
        if obj in (self.formula_edit, self.table, self._cell_editor) and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape and (self._draft or obj is self._cell_editor):
                self.cancel_formula()
                self.table.setFocus()
                return True
            if obj is self._cell_editor and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                if self.apply_formula():
                    self._close_cell_editor()
                    self.table.setFocus()
                return True
            if obj is self.table and self._edit_target is not None:
                text = event.text()
                if text and text.isprintable() and not event.modifiers() & (
                        Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
                    if self._cell_editor is None:
                        self._edit_selected(self.table.currentRow(), 1)
                    if not self._draft:
                        self._cell_editor.selectAll()
                    self._cell_editor.insert(text)
                    self._cell_formula_edited(self._cell_editor.text())
                    return True
                if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
                    self._edit_selected(self.table.currentRow(), 1)
                    return True
        return super().eventFilter(obj, event)

    def _insert_reference(self, row):
        head = self.table.item(row, 0)
        name = head.data(Qt.UserRole) if head else None
        if not name or self._edit_target is None:
            return
        source_path = tuple(head.data(Qt.UserRole + 1) or ())
        target_path, _attribute = self._edit_target
        attr = AU.LABELS.get(name, name)
        if source_path == target_path:
            reference = attr
        else:
            source = part_at(self.root, source_path)
            owner = ("parent" if target_path and source_path == target_path[:-1]
                     else str(AU.merged(source).get("_name") or source.name))
            reference = owner + "!" + attr
        try:
            F.parse(reference)
            tree, target = self._evaluated_part()
            source = tree
            for i in source_path:
                source = source.children[i]
            owner = reference.rsplit("!", 1)[0] if "!" in reference else "self"
            if Evaluator(tree).resolve(target, owner) is not source:
                self.status.setText(tr("Cannot reference this part by name: {name}", name=owner))
                return
        except (ValueError, F.FormulaError) as exc:
            self.status.setText(tr("Could not apply: {error}", error=_error_text(exc)))
            return
        editor = self._formula_input
        editor.insert(reference)
        if editor is self._cell_editor:
            self._cell_formula_edited(editor.text())
        else:
            self._formula_edited(editor.text())
        editor.setFocus()

    def apply_formula(self):
        if not self._draft or self._edit_target is None:
            return True
        path, name = self._edit_target
        self.path = path
        if not self._apply_text(name, self.formula_edit.text().strip()):
            return False
        self._select_attribute(path, name)
        return True

    def cancel_formula(self):
        target = self._edit_target
        self._close_cell_editor()
        self._draft = False
        if target is not None:
            self.path = target[0]
            self._select_attribute(*target)
        self.status.clear()

    def reject(self):
        if self._draft:
            self.cancel_formula()
        else:
            super().reject()

    def closeEvent(self, event):
        self.cancel_formula()
        super().closeEvent(event)

    def _selected_name(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        return it.data(Qt.UserRole) if it else None

    # -- editing ----------------------------------------------------------------------
    def _commit(self, changes: dict, message: str) -> bool:
        g = self._part()
        if g is None or not changes:
            return False
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
            return False
        self.show_root(new, self.path)
        extra = _problems_text(problems)
        self.status.setText(message + (" " + extra if extra else ""))
        if self._options is not None:
            self._options.show_group(new if A.is_dynamic_root(new) else None, True)
        return True

    def _cell_changed(self, item) -> None:
        if self._filling or item.column() != 1:
            return
        head = self.table.item(item.row(), 0)
        name = head.data(Qt.UserRole) if head else None
        if not name:
            return
        self.path = tuple(head.data(Qt.UserRole + 1) or ())
        self._apply_text(name, item.text().strip())

    def _apply_text(self, name, text):
        g = self._part()
        if g is None:
            return False
        attrs = AU.merged(g)
        if text.startswith("="):
            try:
                F.parse(text[1:])
            except F.FormulaError as exc:
                self.status.setText("%s: %s" % (name, _error_text(exc)))
                return False
            return self._commit(AU.set_changes(name, formula=text),
                                tr("{name} set.", name=name))
        units = _units_of(attrs, name, self._part_unit(attrs))
        if units in INCH:
            units = self._display_unit(self.path, units)
        opt = O.Option(name, name, "TEXTBOX", units, attrs.get(name))
        try:
            value = O.parse(opt, text) if text else ""
        except ValueError:
            self.status.setText(tr("{label}: «{text}» is not a number",
                                   label=name, text=text))
            return False
        if isinstance(value, float):
            value = repr(value)          # option values are kept as text
        return self._commit(AU.set_changes(name, value=value, formula=""),
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
                                           "CENTIMETERS")
        except Exception as exc:  # noqa: BLE001
            _log.exception("make dynamic failed")
            self.status.setText(tr("Could not make it dynamic: {error}",
                                   error=_error_text(exc)))
            return False
        self.show_root(new, self.path)
        return True

    def add_attribute(self, name: str) -> None:
        self.add_attributes([name], AU.LABELS.get(name, name))

    def add_attributes(self, names, label):
        """Add only missing members, in one redraw/undo step."""
        if not self._ensure_dynamic():
            return
        g = self._part()
        if g is None:
            return
        attrs = AU.merged(g)
        present = set(AU.attribute_names(attrs))
        missing = [name for name in dict.fromkeys(names) if name not in present]
        if not missing:
            self.status.setText(tr("{name} is already there.", name=label))
            return
        changes = {}
        for name in missing:
            value = ""
            if name in ("x", "y", "z", "lenx", "leny", "lenz"):
                try:
                    tree, part = self._evaluated_part()
                    value = repr(float(_LiveEvaluator(tree).value(part, name)))
                except Exception:  # noqa: BLE001
                    value = "0"
            elif name in ("rotx", "roty", "rotz", "copies", "hidden", "scaletool"):
                value = "0"
            changes.update(AU.set_changes(name, value=value))
        path = self.path
        if self._commit(changes, tr("{name} added.", name=label)):
            self._select_attribute(path, missing[0])

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
