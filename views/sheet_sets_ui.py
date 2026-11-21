# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet sets' (#1519) place in the interface — as reviewed, with as
little new UI as possible:

* :class:`PlanSetsBox` — the «Plan sets» section of a sheet's properties
  in the composer: the sets, ticked where this sheet is in them, and the
  only place sets are made (+), renamed (F2 / double-click) and deleted
  (−). No dialog of its own. Below it, the sheets of the set selected
  there, in the order the set prints them; a double-click opens one.
* :func:`export_sheets_interactive` — Export all takes the set the sheet
  explorer's Set box shows; the file type picked is the format (PDF, PNG
  or SVG). No dialog of its own either.

A set prints in the sheet explorer's order; nothing here orders sheets.
Every change is one undo step of the document (core.history).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QToolButton,
                               QVBoxLayout, QWidget)

from core import sheet_sets as ss
from core.i18n import tr

#: The combo entry for the implicit set: what Print all takes.
ALL_SHEETS = None


def _theme_muted(label: QLabel) -> None:
    try:
        from views.theme import style as theme_style
        theme_style(label, "color:{muted}; font-size: 11px;")
    except Exception:  # noqa: BLE001 — a plain label is fine too
        pass


def fill_set_combo(combo: QComboBox, scene, current=ALL_SHEETS) -> None:
    """``combo`` lists All sheets and every set (its data: the set's id,
    ``None`` for All sheets), keeping ``current`` (an id) selected when it
    still exists."""
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(tr("All sheets"), ALL_SHEETS)
    for st in ss.sets_of(scene):
        combo.addItem(st.name, st.id)
    at = combo.findData(current) if current is not None else 0
    combo.setCurrentIndex(max(0, at))
    combo.blockSignals(False)


#: Item data of the lists' extra columns: a set's sheet count, and the
#: names after the name (a set's sheets, a sheet's sets), cut to fit with
#: «…» — the row's tooltip has them all.
COUNT_ROLE = Qt.UserRole + 1
DETAIL_ROLE = Qt.UserRole + 2

#: The share of the row the name keeps when a detail column follows it.
_NAME_SHARE = 0.42
_GAP = 8


class _Columns(QStyledItemDelegate):
    """Columns in a list: name · count · details. A delegate rather than a
    table, so a row stays a list item that ticks and renames in place."""

    def _parts(self, opt, index, widget):
        """The rectangles of the name, the count and the details."""
        style = widget.style() if widget is not None else QApplication.style()
        text = style.subElementRect(QStyle.SE_ItemViewItemText, opt, widget)
        fm = opt.fontMetrics
        n = index.data(COUNT_ROLE)
        detail = index.data(DETAIL_ROLE)
        count_w = fm.horizontalAdvance("000") + _GAP if n is not None else 0
        if detail is None:
            name_w = text.width() - count_w
        else:
            name_w = max(int(opt.rect.width() * _NAME_SHARE)
                         - (text.left() - opt.rect.left()),
                         fm.horizontalAdvance("M" * 4))
        name = text.adjusted(0, 0, name_w - text.width(), 0)
        count = name.adjusted(name_w, 0, count_w, 0)
        rest = text.adjusted(name_w + count_w + _GAP, 0, 0, 0)
        return name, count, rest

    def paint(self, painter, option, index) -> None:
        if index.data(COUNT_ROLE) is None and index.data(DETAIL_ROLE) is None:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        label, opt.text = opt.text, ""
        # The row as Qt draws it — background, selection, tick — no text.
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        name_r, count_r, rest_r = self._parts(opt, index, widget)
        selected = bool(opt.state & QStyle.State_Selected)
        main = opt.palette.color(QPalette.HighlightedText if selected
                                 else QPalette.Text)
        muted = main if selected else opt.palette.color(QPalette.Disabled,
                                                        QPalette.Text)
        fm = opt.fontMetrics
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(main)
        align = int(Qt.AlignLeft | Qt.AlignVCenter)
        painter.drawText(name_r, align,
                         fm.elidedText(label, Qt.ElideRight, name_r.width()))
        painter.setPen(muted)
        n = index.data(COUNT_ROLE)
        if n is not None:
            painter.drawText(count_r, int(Qt.AlignRight | Qt.AlignVCenter),
                             str(n))
        detail = index.data(DETAIL_ROLE)
        if detail:
            painter.drawText(rest_r, align, fm.elidedText(
                detail, Qt.ElideRight, max(0, rest_r.width())))
        painter.restore()

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        super().updateEditorGeometry(editor, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        name_r, _count, _rest = self._parts(opt, index, opt.widget)
        g = editor.geometry()
        g.setRight(max(name_r.right(), g.left() + 40))
        editor.setGeometry(g)


class PlanSetsBox(QWidget):
    """The plan sets of one sheet: tick a set to put the sheet in it.

    ``window`` is the main window (its viewport's history keeps the undo);
    ``on_changed`` is called after every change (the composer refreshes
    the sheet explorer with it); ``on_open(sheet)`` opens a sheet picked
    in the list of the selected set's sheets."""

    def __init__(self, window, on_changed=None, on_open=None,
                 parent=None) -> None:
        super().__init__(parent)
        self._window = window
        self._on_changed = on_changed
        self._on_open = on_open
        self._sheet = None
        self._updating = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(2)
        title = QLabel(tr("Plan sets"))
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        head.addWidget(title, 1)

        def button(text, tip, slot, icon=None):
            b = QToolButton()
            b.setAutoRaise(True)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            if icon is not None:
                from views.outliner import node_icon
                b.setIcon(node_icon(icon))
            else:
                b.setText(text)
            b.clicked.connect(lambda _checked=False: slot())
            head.addWidget(b)
            return b

        self.add_btn = button("+", tr("New plan set, with this sheet in it"),
                              self.add_set)
        self.rename_btn = button("", tr("Rename the plan set (F2)"),
                                 self.rename_current, icon="rename")
        self.delete_btn = button("−", tr("Delete the plan set — its sheets "
                                          "stay"), self.delete_current)
        lay.addLayout(head)
        caption = QLabel(tr("This sheet is in these plan sets:"))
        _theme_muted(caption)
        lay.addWidget(caption)
        self.list = QListWidget()
        # Kept here too: a delegate Python lets go of is gone under the view.
        self._delegates = [_Columns(self.list)]
        self.list.setItemDelegate(self._delegates[0])
        self.list.setMinimumHeight(90)
        self.list.setMaximumHeight(150)
        self.list.setEditTriggers(QListWidget.DoubleClicked
                                  | QListWidget.EditKeyPressed)
        self.list.setToolTip(tr(
            "Tick a plan set to put this sheet in it; a sheet can be in "
            "several. A set prints its sheets in the explorer's order, its "
            "pages numbered within it ({juego} prints its name)."))
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.currentRowChanged.connect(lambda _r: self._sync_buttons())
        lay.addWidget(self.list)
        # The sheets of the set selected above, as the set prints them.
        self.members_caption = QLabel()
        _theme_muted(self.members_caption)
        lay.addWidget(self.members_caption)
        self.members = self._sheet_list(tr(
            "The sheets of this plan set, in the order it prints them. "
            "Double-click a sheet to open it. A greyed sheet is not "
            "printed: its printer, or a folder's, is off."))
        lay.addWidget(self.members)
        # ▲ / ▼ between the set's sheets and the others: the selected
        # sheets (several with Ctrl / Shift) move in or out, one undo step.
        moves = QHBoxLayout()
        moves.setSpacing(2)
        moves.addStretch(1)

        def arrow(kind, tip, slot):
            b = QToolButton()
            b.setAutoRaise(True)
            b.setArrowType(kind)
            b.setToolTip(tip)
            b.setAccessibleName(tip)
            b.clicked.connect(lambda _checked=False: slot())
            moves.addWidget(b)
            return b

        self.add_sheets_btn = arrow(
            Qt.UpArrow, tr("Add the selected sheets to the plan set"),
            self.add_selected)
        self.remove_sheets_btn = arrow(
            Qt.DownArrow, tr("Take the selected sheets out of the plan set"),
            self.remove_selected)
        moves.addStretch(1)
        self.moves_row = QWidget()
        self.moves_row.setLayout(moves)
        moves.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.moves_row)
        self.others_caption = QLabel()
        _theme_muted(self.others_caption)
        lay.addWidget(self.others_caption)
        self.others = self._sheet_list(tr(
            "The sheets not in this plan set. Select some (Ctrl / Shift for "
            "several) and press ▲ to add them. Double-click a sheet to "
            "open it."))
        lay.addWidget(self.others)
        self.members.itemSelectionChanged.connect(self._sync_moves)
        self.others.itemSelectionChanged.connect(self._sync_moves)
        self._sync_buttons()

    def _sheet_list(self, tip: str) -> QListWidget:
        lst = QListWidget()
        self._delegates.append(_Columns(lst))
        lst.setItemDelegate(self._delegates[-1])
        lst.setMinimumHeight(80)
        lst.setMaximumHeight(160)
        lst.setEditTriggers(QListWidget.NoEditTriggers)
        lst.setSelectionMode(QListWidget.ExtendedSelection)
        lst.setToolTip(tip)
        lst.itemActivated.connect(self._open_member)
        return lst

    # ---- model ----------------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _execute(self, cmd) -> bool:
        history = self._window.viewport.history
        history.execute(cmd)
        error = getattr(history, "last_error", None)
        if error:
            self._window.viewport.flash_status(
                str(error).split(": ", 1)[-1], 5000)
        self._after_change()
        return not error

    def _after_change(self) -> None:
        self.refresh()
        mark = getattr(self._window, "_mark_dirty", None)
        if callable(mark):
            mark()
        if self._on_changed is not None:
            self._on_changed()

    def set_sheet(self, sheet) -> None:
        self._sheet = sheet
        self.refresh()

    def refresh(self) -> None:
        scene = self._scene()
        current = self.current_set()
        mine = {id(s) for s in ss.sets_of_sheet(scene, self._sheet)} \
            if self._sheet is not None else set()
        self._updating = True
        self.list.clear()
        for st in ss.sets_of(scene):
            names = [c.name for c in ss.members(scene, st)]
            n = len(names)
            item = QListWidgetItem(st.name)
            item.setData(Qt.UserRole, st)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable
                          | Qt.ItemIsEditable)
            item.setCheckState(Qt.Checked if id(st) in mine
                               else Qt.Unchecked)
            item.setToolTip("\n".join(
                [tr("{name}: {n} sheets", name=st.name, n=n)]
                + [f"• {x}" for x in names]))
            item.setData(COUNT_ROLE, n)
            item.setData(DETAIL_ROLE, ", ".join(names))
            self.list.addItem(item)
            if st is current:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            # A set to show the sheets of: the first this sheet is in.
            rows = [i for i in range(self.list.count())
                    if self.list.item(i).checkState() == Qt.Checked]
            self.list.setCurrentRow(rows[0] if rows else 0)
        self._updating = False
        self.setEnabled(self._sheet is not None)
        self._sync_buttons()

    def current_set(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _sync_buttons(self) -> None:
        has = self.current_set() is not None
        self.rename_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        self._show_members()

    def _show_members(self, select=()) -> None:
        """The selected set's sheets as the set prints them, cover first,
        and below the other sheets in the explorer's order; the open sheet
        in bold, the unprinted ones greyed, the sheets in ``select``
        selected (the ones just moved)."""
        from core.sheet_folders import sheet_printed
        st = self.current_set()
        self.members.clear()
        self.others.clear()
        for w in (self.members_caption, self.members, self.moves_row,
                  self.others_caption, self.others):
            w.setVisible(st is not None)
        if st is None:
            self._sync_moves()
            return
        scene = self._scene()
        self.members_caption.setText(tr("Sheets in «{name}»:",
                                        name=st.name))
        self.others_caption.setText(tr("Not in «{name}»:", name=st.name))
        muted = self.members.palette().color(QPalette.Disabled,
                                             QPalette.Text)
        chosen = {id(c) for c in select}

        def put(lst, sheet, text):
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, sheet)
            if sheet is self._sheet:
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            if not sheet_printed(scene, sheet):
                item.setForeground(muted)
            # Which plan sets the sheet is in: a column, all in the tooltip.
            sets = [s.name for s in ss.sets_of_sheet(scene, sheet)]
            item.setData(DETAIL_ROLE, ", ".join(sets))
            item.setToolTip("\n".join(
                [sheet.name, tr("Plan sets") + ":"]
                + [f"• {x}" for x in sets]) if sets else sheet.name)
            lst.addItem(item)
            item.setSelected(id(sheet) in chosen)

        inside = ss.members(scene, st)
        for sheet in inside:
            text = sheet.name
            if st.cover_uid and getattr(sheet, "uid", "") == st.cover_uid:
                text = tr("{name} (cover)", name=sheet.name)
            put(self.members, sheet, text)
        ids = {id(c) for c in inside}
        for sheet in scene.compositions:
            if id(sheet) not in ids:
                put(self.others, sheet, sheet.name)
        self._sync_moves()

    def _sync_moves(self) -> None:
        self.add_sheets_btn.setEnabled(bool(self.others.selectedItems()))
        self.remove_sheets_btn.setEnabled(
            bool(self.members.selectedItems()))

    @staticmethod
    def _picked(lst) -> list:
        """The selected sheets of ``lst``, top to bottom."""
        return [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                if lst.item(i).isSelected()]

    def add_selected(self) -> None:
        """▲: the sheets selected below go into the set."""
        self._move(self._picked(self.others), add=True)

    def remove_selected(self) -> None:
        """▼: the sheets selected in the set leave it (they stay in the
        document)."""
        self._move(self._picked(self.members), add=False)

    def _move(self, sheets, add: bool) -> None:
        from core.history import EditSheetSetCommand
        st = self.current_set()
        if st is None or not sheets:
            return
        now = ss.members(self._scene(), st)
        gone = {id(c) for c in sheets}
        new = now + list(sheets) if add else \
            [c for c in now if id(c) not in gone]
        cover = False if not add and st.cover_uid and any(
            getattr(c, "uid", "") == st.cover_uid for c in sheets) else None
        self._execute(EditSheetSetCommand(st, new, cover=cover,
                                          ordered=st.ordered))
        self._show_members(select=sheets)

    def member_names(self) -> list:
        """The sheets the list of the selected set's sheets shows."""
        return [self.members.item(i).data(Qt.UserRole).name
                for i in range(self.members.count())]

    def other_names(self) -> list:
        """The sheets the list of the sheets not in the set shows."""
        return [self.others.item(i).data(Qt.UserRole).name
                for i in range(self.others.count())]

    def _open_member(self, item) -> None:
        sheet = item.data(Qt.UserRole) if item is not None else None
        if sheet is not None and self._on_open is not None:
            self._on_open(sheet)

    # ---- actions -------------------------------------------------------------
    def _on_item_changed(self, item) -> None:
        if self._updating or self._sheet is None:
            return
        from core.history import (RenameSheetSetCommand,
                                  SetSheetSetsOfSheetCommand)
        st = item.data(Qt.UserRole)
        name = item.text().strip()
        if st is not None and name != st.name:
            if not name:
                self.refresh()
                return
            self._execute(RenameSheetSetCommand(st, name))
            return
        wanted = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                wanted.append(it.data(Qt.UserRole))
        mine = ss.sets_of_sheet(self._scene(), self._sheet)
        if {id(s) for s in wanted} != {id(s) for s in mine}:
            self._execute(SetSheetSetsOfSheetCommand(self._sheet, wanted))

    def add_set(self) -> None:
        """A new set with this sheet in it, its name ready to type."""
        from core.history import AddSheetSetCommand
        st = ss.SheetSet(tr("Plan set"))
        self._execute(AddSheetSetCommand(
            st, [self._sheet] if self._sheet is not None else []))
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) is st:
                self.list.setCurrentItem(item)
                self.list.editItem(item)
                break

    def rename_current(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.list.editItem(item)

    def delete_current(self, ask: bool = True) -> None:
        from core.history import DeleteSheetSetCommand
        st = self.current_set()
        if st is None:
            return
        if ask and QMessageBox.question(
                self, tr("Delete plan set"),
                tr("Delete the plan set «{name}»? Its sheets stay.",
                   name=st.name)) != QMessageBox.Yes:
            return
        self._execute(DeleteSheetSetCommand(st))


#: The file types Export all offers: PDF is one file; PNG and SVG one file
#: per sheet, named after the one picked (``Casa-01-Plan.png``…).
EXPORT_FILTERS = (("pdf", "PDF (*.pdf)"),
                  ("png", "PNG — one image per sheet (*.png)"),
                  ("svg", "SVG — one drawing per sheet (*.svg)"))


def default_export_path(composer, scene, set_id, fmt: str = "pdf") -> str:
    """Beside the project, named after it — and the set: «Casa-Roofer.pdf»."""
    import re
    base = Path(composer.default_pdf_path())
    st = ss.set_by_id(scene, set_id) if set_id is not None else None
    stem = base.stem + (f"-{st.name}" if st is not None else "")
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem)
    return str(base.with_name(f"{stem}.{fmt}"))


def export_sheets_interactive(composer, parent=None, set_id=ALL_SHEETS,
                              status=None) -> bool:
    """Export all — the sheets marked for printing, or set ``set_id``
    (#1519) — asking only where to: the file type picked (PDF, PNG, SVG)
    is the format. ``status(text, ms)`` reports the outcome. True when
    files were written."""
    scene = composer._scene()
    sheets = ss.export_list(scene, set_id)
    say = status or (lambda _t, _ms: None)
    if not sheets:
        say(tr("No sheet is marked for printing"), 4000)
        return False
    st = ss.set_by_id(scene, set_id) if set_id is not None else None
    from views.filedialogs import file_dialogs
    title = (tr("Export the plan set «{name}»…", name=st.name)
             if st is not None else tr("Export all sheets…"))
    path, chosen = file_dialogs.getSaveFileName(
        parent or composer, title,
        default_export_path(composer, scene, set_id),
        ";;".join(tr(label) for _key, label in EXPORT_FILTERS))
    if not path:
        return False
    fmt = Path(path).suffix.lower().lstrip(".")
    if fmt not in ("pdf", "png", "svg"):
        picked = [k for k, label in EXPORT_FILTERS if tr(label) == chosen]
        fmt = picked[0] if picked else "pdf"
        path = str(Path(path).with_suffix("." + fmt))
    if st is None and fmt == "pdf":
        troubled = composer.export_all_pdf(path, sheets)
        files, errors = [path], {name: [] for name in troubled}
    else:
        out = composer.export_sheets(
            path, None if st is not None else sheets, fmt,
            sheet_set=st.id if st is not None else None)
        files, errors = out.get("files") or [], out.get("errors") or {}
    name = files[0] if len(files) == 1 else str(Path(path).parent)
    say(tr("Exported {name} — but a view would not render on {sheets}",
           name=name, sheets=", ".join(errors)) if errors else
        tr("Exported {n} sheets to {name}", n=len(sheets), name=name), 8000)
    return True
