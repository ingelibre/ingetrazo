# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet sets' (#1519) place in the interface — as reviewed, with as
little new UI as possible:

* :class:`PlanSetsBox` — the «Plan sets» section of a sheet's properties
  in the composer: the sets, ticked where this sheet is in them, and the
  only place sets are made (+), renamed (F2 / double-click) and deleted
  (−). No dialog of its own.
* :func:`export_sheets_interactive` — Export all takes the set the sheet
  explorer's Set box shows; the file type picked is the format (PDF, PNG
  or SVG). No dialog of its own either.

A set prints in the sheet explorer's order; nothing here orders sheets.
Every change is one undo step of the document (core.history).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QToolButton, QVBoxLayout, QWidget)

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


class PlanSetsBox(QWidget):
    """The plan sets of one sheet: tick a set to put the sheet in it.

    ``window`` is the main window (its viewport's history keeps the undo);
    ``on_changed`` is called after every change (the composer refreshes
    the sheet explorer with it)."""

    def __init__(self, window, on_changed=None, parent=None) -> None:
        super().__init__(parent)
        self._window = window
        self._on_changed = on_changed
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
        self._sync_buttons()

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
            n = len(ss.members(scene, st))
            item = QListWidgetItem(st.name)
            item.setData(Qt.UserRole, st)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable
                          | Qt.ItemIsEditable)
            item.setCheckState(Qt.Checked if id(st) in mine
                               else Qt.Unchecked)
            item.setToolTip(tr("{name}: {n} sheets", name=st.name, n=n))
            self.list.addItem(item)
            if st is current:
                self.list.setCurrentItem(item)
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
