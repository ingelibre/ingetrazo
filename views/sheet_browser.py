# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Sheets tab: the Scenes panel above, the sheet explorer below.

The same two panels, built the same way, sit in the main window (a tab
beside the Browser) and in the sheet composer (its «Sheets» page), so both
windows look and work alike. The sheet explorer shows the sheets in the
nested folders of :mod:`core.sheet_folders`, each with the scenes placed on
it and its Print flag — what Print all and Export all take.

Each panel needs only the main window, never the tab or dock it sits in,
and the panels speak to each other only through the document: a layout
rework can later move them anywhere (docs/sheet-browser-plan.md).
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDockWidget, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import sheet_folders as sf
from core.i18n import tr

#: The sheet explorer's columns.
COL_NAME, COL_PRINT = 0, 1

_FOLDER, _SHEET, _FRAME = "folder", "sheet", "frame"


class _SheetTree(QTreeWidget):
    """The explorer's tree. Delete removes what is picked, F2 renames,
    Space flips Print."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel

    def keyPressEvent(self, ev) -> None:
        if self.state() != QAbstractItemView.EditingState and \
                not ev.isAutoRepeat():
            if ev.key() == Qt.Key_Delete:
                self._panel.delete_selected()
                return
            if ev.key() == Qt.Key_F2:
                self._panel.rename_current()
                return
            if ev.key() == Qt.Key_Space:
                self._panel.toggle_print_selected()
                return
        super().keyPressEvent(ev)


def _icon(key: str):
    from views.outliner import node_icon
    return node_icon(key)


def _print_icon(state: str):
    """``on``: printed; ``off``: not; ``some``: a folder only partly."""
    if state == "on":
        return _icon("print")
    if state == "off":
        return _icon("print_off")
    from views.outliner import _faded
    return _faded(_icon("print"))


class SheetExplorer(QWidget):
    """The document's sheets in their folders, each with the scenes placed
    on it: filter them, open one with a double-click, add sheets and
    folders, rename, delete, choose which ones Print all and Export all
    take, print or export them.

    ``composer`` is the sheet composer this copy lives in (``None`` in the
    main window): there, the sheet open beside it is marked."""

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        self._window = window
        self._composer_win = composer
        self._updating = False
        self._shape = None
        self._query = ""
        #: Sheets the user folded (their scenes hidden). Sheets open by
        #: default; this is the panel's memory, not the document's.
        self._folded_sheets: set = set()
        self.items: dict = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        # The filter field and, beside it, the actions as small icons —
        # the Browser's bar.
        from views.outliner import _tool_button
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter sheets, folders, scenes…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_filter)
        bar.addWidget(self.search, 1)
        buttons = (
            ("add_sheet_btn", "sheet_add",
             tr("New sheet, in the selected folder"), self.add_sheet),
            ("add_folder_btn", "folder_add",
             tr("New folder, inside the selected one"), self.add_folder),
            ("rename_btn", "rename", tr("Rename (F2)"), self.rename_current),
            ("delete_btn", "delete",
             tr("Delete the selected sheets and folders (Delete) — a "
                "deleted folder moves what it holds one level up"),
             self.delete_selected),
            ("print_btn", "print",
             tr("Print all: the sheets marked for printing, each on its "
                "own paper"), self.print_all),
            ("export_btn", "pdf",
             tr("Export all (PDF): the sheets marked for printing into one "
                "PDF, each page at its own paper size"), self.export_all),
        )
        for attr, icon, tip, slot in buttons:
            btn = _tool_button("", tip, slot)
            btn.setIcon(_icon(icon))
            setattr(self, attr, btn)
            bar.addWidget(btn)
        lay.addLayout(bar)

        self.tree = _SheetTree(self)
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("Name"), ""])
        head_item = self.tree.headerItem()
        head_item.setIcon(COL_PRINT, _icon("print"))
        head_item.setToolTip(COL_PRINT, tr(
            "Printed by Print all and Export all — click a row's printer to "
            "switch it; a folder's switches every sheet inside it"))
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        head.setSectionResizeMode(COL_PRINT, QHeaderView.Fixed)
        head.resizeSection(COL_PRINT, 28)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setToolTip(tr(
            "Double-click a sheet to open it. The printer marks the sheets "
            "Print all and Export all take. Right-click for more."))
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemExpanded.connect(
            lambda item: self._set_expanded(item, True))
        self.tree.itemCollapsed.connect(
            lambda item: self._set_expanded(item, False))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        lay.addWidget(self.tree, 1)
        # The composer edits sheets without telling the model: while this
        # panel is on screen it checks, once a second, whether what it
        # lists changed (a fingerprint of a few fields — nothing to do
        # when nothing did).
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self.refresh)
        self.refresh()

    # ---- Model → view ----------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _fingerprint(self, scene) -> tuple:
        current = getattr(self._composer_win, "comp", None)
        return (
            tuple((f.id, f.name, f.parent_id, f.expanded)
                  for f in sf.folders_of(scene)),
            tuple((id(c), c.name, c.folder_id, c.print_in_all,
                   tuple((id(f), f.view_key, f.scale_n) for f in c.frames))
                  for c in scene.compositions),
            tuple(v.name for v in getattr(scene, "saved_views", None) or ()),
            id(current))

    def on_scene_changed(self) -> None:
        if self.isVisible():
            self.refresh()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self.refresh()
        self._poll.start()

    def hideEvent(self, ev) -> None:
        self._poll.stop()
        super().hideEvent(ev)

    def _folder_print_state(self, scene, folder) -> str:
        """``on`` when every sheet inside (at any depth) prints, ``off``
        when none does — an empty folder too — ``some`` in between."""
        sheets = self._sheets_under(scene, folder)
        printed = sum(1 for c in sheets if c.print_in_all)
        if sheets and printed == len(sheets):
            return "on"
        return "off" if printed == 0 else "some"

    @staticmethod
    def _sheets_under(scene, folder) -> list:
        ids = {folder.id} | sf.descendant_ids(scene, folder.id)
        return [c for c in scene.compositions if c.folder_id in ids]

    def refresh(self, force: bool = False) -> None:
        scene = self._scene()
        shape = self._fingerprint(scene)
        if shape == self._shape and not force:
            return
        self._shape = shape
        picked = {self._key(it) for it in self.tree.selectedItems()}
        current = self.tree.currentItem()
        current_key = self._key(current) if current is not None else None
        self._updating = True
        self.tree.clear()
        self.items = {}
        open_sheet = getattr(self._composer_win, "comp", None)
        bold = QFont(self.tree.font())
        bold.setBold(True)
        from core import outliner
        from core.composition import format_scale
        from views.composer import frame_view_name

        def add(parent_item, folder_id, seen) -> None:
            for f in sf.subfolders(scene, folder_id):
                if f.id in seen:
                    continue
                item = QTreeWidgetItem([f.name, ""])
                item.setData(COL_NAME, Qt.UserRole, (_FOLDER, f))
                item.setIcon(COL_NAME, _icon("folder"))
                item.setIcon(COL_PRINT, _print_icon(
                    self._folder_print_state(scene, f)))
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                parent_item.addChild(item)
                self.items[id(f)] = item
                add(item, f.id, seen | {f.id})
                item.setExpanded(f.expanded)
            for c in sf.sheets_in(scene, folder_id):
                item = QTreeWidgetItem([c.name, ""])
                item.setData(COL_NAME, Qt.UserRole, (_SHEET, c))
                item.setIcon(COL_NAME, _icon("sheet"))
                item.setIcon(COL_PRINT, _print_icon(
                    "on" if c.print_in_all else "off"))
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setToolTip(COL_NAME, tr(
                    "{name} — double-click to open it", name=c.name))
                if c is open_sheet:
                    item.setFont(COL_NAME, bold)
                parent_item.addChild(item)
                self.items[id(c)] = item
                for frame in c.frames:
                    name = (tr("Current view")
                            if frame.view_key == "__current__"
                            else frame_view_name(frame))
                    row = QTreeWidgetItem(
                        [f"{name} · {format_scale(frame.scale_n)}", ""])
                    row.setData(COL_NAME, Qt.UserRole, (_FRAME, c, frame))
                    if outliner.is_orphan(scene, frame):
                        row.setIcon(COL_NAME, _icon("warning"))
                        row.setToolTip(COL_NAME, tr(
                            "This view shows the scene «{name}», which the "
                            "model no longer has. The frame keeps its place "
                            "on the sheet; pick another view for it in the "
                            "composer.", name=outliner.frame_scene(frame)))
                    else:
                        row.setIcon(COL_NAME, _icon(
                            "scene" if outliner.frame_scene(frame)
                            else "frame"))
                    item.addChild(row)
                    self.items[id(frame)] = row
                item.setExpanded(id(c) not in self._folded_sheets)

        add(self.tree.invisibleRootItem(), None, frozenset())
        for key, item in self.items.items():
            if key in picked:
                item.setSelected(True)
            if key == current_key:
                self.tree.setCurrentItem(item, COL_NAME,
                                         QItemSelectionModel.NoUpdate)
        self._updating = False
        self._apply_filter()

    @staticmethod
    def _key(item):
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if not d:
            return None
        return id(d[2]) if d[0] == _FRAME else id(d[1])

    # ---- Filter ---------------------------------------------------------------
    def _on_filter(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Hide the rows the filter leaves out: a row stays when its name
        matches, when something inside it does (its folders open to show
        it), or when a folder or sheet around it does (all of it shows)."""
        query = self._query
        root = self.tree.invisibleRootItem()

        def walk(item, inside_hit) -> bool:
            hit = bool(query) and query in item.text(COL_NAME).casefold()
            shown_child = False
            for i in range(item.childCount()):
                if walk(item.child(i), inside_hit or hit):
                    shown_child = True
            keep = not query or hit or inside_hit or shown_child
            item.setHidden(not keep)
            if query and shown_child and not hit:
                item.setExpanded(True)
            return keep

        self._updating = True
        for i in range(root.childCount()):
            walk(root.child(i), False)
        self._updating = False

    # ---- Reading the selection ---------------------------------------------------
    def _picked(self) -> tuple[list, list]:
        """``(sheets, folders)`` among the selected rows (a scene row
        stands for its sheet)."""
        sheets, folders = [], []
        for item in self.tree.selectedItems():
            d = item.data(COL_NAME, Qt.UserRole)
            if not d:
                continue
            if d[0] == _FOLDER:
                folders.append(d[1])
            elif d[1] not in sheets:
                sheets.append(d[1])
        return sheets, folders

    def _target_folder_id(self):
        """Where a new sheet or folder goes: into the selected folder, or
        beside the selected sheet; the top when nothing is selected."""
        item = self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if not d or not item.isSelected():
            return None
        return d[1].id if d[0] == _FOLDER else d[1].folder_id

    # ---- View → model --------------------------------------------------------------
    def _history(self):
        return self._window.viewport.history

    def _after_tree_change(self) -> None:
        """The sheet order may have changed: the composer's list and both
        windows' sheet strips follow, then this panel."""
        composer = getattr(self._window, "_composer", None)
        if composer is not None and hasattr(composer, "_reload_comp_combo"):
            composer._reload_comp_combo()
        refresh_tabs = getattr(self._window, "_refresh_sheet_tabs", None)
        if refresh_tabs is not None:
            refresh_tabs()
        self._window.viewport.update()
        self.refresh(force=True)

    def _after_edit_in_tree(self) -> None:
        """The same, on the next turn: an edit made IN the tree (a click on
        a printer, a name typed) arrives while Qt still holds the row it
        changed, and rebuilding the tree right then deletes that row under
        it."""
        QTimer.singleShot(0, self, self._after_tree_change)

    def open_sheet(self, sheet) -> None:
        comps = self._scene().compositions
        if sheet not in comps:
            return
        index = comps.index(sheet)
        if self._composer_win is not None:
            self._composer_win.show_sheet(index)
        else:
            self._window._show_sheet(index)
        self.refresh(force=True)

    def activate(self, item) -> None:
        """A sheet, or a scene on it, opens the sheet in the composer (a
        folder only opens or closes, as Qt does by itself)."""
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if d and d[0] in (_SHEET, _FRAME):
            self.open_sheet(d[1])

    def _on_double_clicked(self, item, column) -> None:
        if column == COL_PRINT:
            return                  # the printer: a click already flipped it
        self.activate(item)

    def _on_item_clicked(self, item, column) -> None:
        if column != COL_PRINT or self._updating:
            return
        d = item.data(COL_NAME, Qt.UserRole)
        if not d or d[0] == _FRAME:
            return
        scene = self._scene()
        if d[0] == _FOLDER:
            sheets = self._sheets_under(scene, d[1])
            on = self._folder_print_state(scene, d[1]) != "on"
        else:
            # On one of several selected sheets: all of them, as the
            # Browser's eye does.
            picked, _folders = self._picked()
            sheets = picked if d[1] in picked else [d[1]]
            on = not d[1].print_in_all
        self.set_printed(sheets, on, defer=True)

    def set_printed(self, sheets, on: bool, defer: bool = False) -> None:
        """Whether Print all and Export all take ``sheets`` — one undo
        step."""
        sheets = [c for c in sheets if c.print_in_all != bool(on)]
        if not sheets:
            return
        from core.history import SetSheetPrintCommand
        self._history().execute(SetSheetPrintCommand(sheets, on))
        (self._after_edit_in_tree if defer else self._after_tree_change)()

    def toggle_print_selected(self) -> None:
        """Space: the selected sheets (and every sheet in the selected
        folders) flip together — on, unless all of them already are."""
        scene = self._scene()
        sheets, folders = self._picked()
        for f in folders:
            sheets += [c for c in self._sheets_under(scene, f)
                       if c not in sheets]
        if sheets:
            self.set_printed(sheets, not all(c.print_in_all for c in sheets))

    def add_sheet(self, folder_id=...) -> None:
        """A new sheet — as the «+» tab makes it — in the selected folder
        (or ``folder_id``), opened in the composer."""
        scene = self._scene()
        if folder_id is ...:
            folder_id = self._target_folder_id()
        before = list(scene.compositions)
        self._window._show_new_sheet()
        new = [c for c in scene.compositions if c not in before]
        if new and folder_id is not None:
            for c in new:
                c.folder_id = folder_id
            sf.sync_order(scene)
            composer = getattr(self._window, "_composer", None)
            if composer is not None:
                composer.show_sheet(scene.compositions.index(new[-1]))
        self._after_tree_change()

    def add_folder(self, parent=...) -> None:
        """A new folder inside the selected one (or beside the selected
        sheet, or inside ``parent``), its name ready to type."""
        from core.history import AddSheetFolderCommand
        from core.sheet_folders import SheetFolder
        scene = self._scene()
        if parent is ...:
            parent = self._target_folder_id()
        taken = {f.name for f in sf.subfolders(scene, parent)}
        base = tr("New folder")
        name, n = base, 2
        while name in taken:
            name, n = f"{base} {n}", n + 1
        folder = SheetFolder(name, parent_id=parent)
        self._history().execute(AddSheetFolderCommand(folder))
        if parent is not None:
            parent_folder = sf.folder_by_id(scene, parent)
            if parent_folder is not None:
                parent_folder.expanded = True
        self._after_tree_change()
        item = self.items.get(id(folder))
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.editItem(item, COL_NAME)

    def rename_current(self, item=None) -> None:
        """Type a new name for the folder or sheet in the row."""
        item = item if item is not None else self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if d and d[0] in (_FOLDER, _SHEET):
            self.tree.editItem(item, COL_NAME)

    def duplicate_sheet(self, sheet) -> None:
        comps = self._scene().compositions
        if sheet in comps:
            self._window._ensure_composer().duplicate_sheet(
                comps.index(sheet))
            self._after_tree_change()

    def delete_selected(self) -> None:
        """Delete what is selected: the folders — what they hold moves one
        level up — in one undo step, and the sheets through the composer,
        which asks first and keeps at least one."""
        sheets, folders = self._picked()
        self.delete(sheets, folders)

    def delete(self, sheets, folders) -> None:
        from core.history import DeleteSheetFoldersCommand
        if folders:
            self._history().execute(DeleteSheetFoldersCommand(folders))
        if sheets:
            comp_win = self._window._ensure_composer()
            for c in sheets:
                comps = self._scene().compositions
                if c in comps:
                    comp_win.delete_sheet(comps.index(c), self)
        if folders or sheets:
            self._after_tree_change()

    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != COL_NAME:
            return
        d = item.data(COL_NAME, Qt.UserRole)
        if not d or d[0] == _FRAME:
            return
        kind, obj = d[0], d[1]
        name = item.text(COL_NAME).strip()
        if not name or name == obj.name:
            self._shape = None                  # show the old name again
            self._after_edit_in_tree()
            return
        if kind == _FOLDER:
            from core.history import RenameSheetFolderCommand
            self._history().execute(RenameSheetFolderCommand(obj, name))
        else:
            obj.name = name
            self._scene().version += 1
        self._after_edit_in_tree()

    def _set_expanded(self, item, on: bool) -> None:
        """A folder's open or closed is kept with the document (it opens
        the way it was left) — not an edit to undo, so straight onto the
        folder; a sheet's is this panel's memory."""
        if self._updating:
            return
        d = item.data(COL_NAME, Qt.UserRole)
        if not d:
            return
        if d[0] == _FOLDER:
            d[1].expanded = on
            self._shape = self._fingerprint(self._scene())
        elif d[0] == _SHEET:
            (self._folded_sheets.discard if on
             else self._folded_sheets.add)(id(d[1]))

    # ---- Right-click ---------------------------------------------------------
    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if item is not None and not item.isSelected():
            self.tree.setCurrentItem(item)
        menu = self.build_menu(d)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def build_menu(self, d):
        """The right-click menu for a row's data ``d`` (``None``: empty
        space) — the bar's actions, for what was clicked."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        scene = self._scene()
        sheets, folders = self._picked()
        if d and d[0] in (_SHEET, _FRAME):
            sheet = d[1]
            if sheet not in sheets:
                sheets, folders = [sheet], []
            menu.addAction(_icon("sheet"), tr("Open sheet"),
                           lambda: self.open_sheet(sheet))
            if d[0] == _SHEET:
                menu.addAction(_icon("rename"), tr("Rename… (F2)"),
                               lambda: self.rename_current(
                                   self.items.get(id(sheet))))
            menu.addAction(tr("Duplicate sheet"),
                           lambda: self.duplicate_sheet(sheet))
            menu.addAction(_icon("delete"), tr("Delete"),
                           lambda: self.delete(sheets, folders))
            menu.addSeparator()
            on = not all(c.print_in_all for c in sheets)
            menu.addAction(_print_icon("on" if on else "off"),
                           tr("Include in Print all") if on
                           else tr("Exclude from Print all"),
                           lambda: self.set_printed(sheets, on))
            menu.addAction(_icon("print"), tr("Print…"),
                           lambda: self.print_sheets(sheets))
            menu.addAction(_icon("pdf"), tr("Export PDF…"),
                           lambda: self.export_sheets(sheets))
            menu.addSeparator()
            here = sheet.folder_id
        elif d and d[0] == _FOLDER:
            folder = d[1]
            if folder not in folders:
                sheets, folders = [], [folder]
            inside = self._sheets_under(scene, folder)
            menu.addAction(_icon("rename"), tr("Rename… (F2)"),
                           lambda: self.rename_current(
                               self.items.get(id(folder))))
            menu.addAction(_icon("delete"), tr("Delete folder (its sheets "
                                               "move one level up)"),
                           lambda: self.delete(sheets, folders))
            menu.addSeparator()
            on = self._folder_print_state(scene, folder) != "on"
            act = menu.addAction(_print_icon("on" if on else "off"),
                                 tr("Include all in Print all") if on
                                 else tr("Exclude all from Print all"),
                                 lambda: self.set_printed(inside, on))
            act.setEnabled(bool(inside))
            printed = [c for c in sf.printed_sheets(scene) if c in inside]
            act = menu.addAction(_icon("print"), tr("Print…"),
                                 lambda: self.print_sheets(printed))
            act.setEnabled(bool(printed))
            act = menu.addAction(_icon("pdf"), tr("Export PDF…"),
                                 lambda: self.export_sheets(printed))
            act.setEnabled(bool(printed))
            menu.addSeparator()
            here = folder.id
        else:
            here = None
        menu.addAction(_icon("sheet_add"), tr("New sheet here")
                       if d else tr("New sheet"),
                       lambda: self.add_sheet(here))
        menu.addAction(_icon("folder_add"), tr("New folder here")
                       if d else tr("New folder"),
                       lambda: self.add_folder(here))
        if not d:
            menu.addSeparator()
            menu.addAction(_icon("print"), tr("Print all…"), self.print_all)
            menu.addAction(_icon("pdf"), tr("Export all (PDF)…"),
                           self.export_all)
        return menu

    # ---- Print / Export -------------------------------------------------------
    def print_sheets(self, sheets) -> None:
        if not sheets:
            return
        order = [c for c in self._scene().compositions if c in sheets]
        self._window._ensure_composer().print_sheets(order, self)

    def export_sheets(self, sheets, path=None) -> None:
        """``sheets`` into one PDF, in the order shown."""
        if not sheets:
            return
        if path is None:
            from views.filedialogs import file_dialogs
            path, _ = file_dialogs.getSaveFileName(
                self, tr("Export PDF…"), "sheets.pdf", "PDF (*.pdf)")
        if not path:
            return
        troubled = self._window._ensure_composer().export_all_pdf(
            path, sheets)
        self._window.viewport.flash_status(
            tr("Exported {n} sheets to {name}", n=len(sheets), name=path)
            if not troubled else
            tr("Exported {name} — but a view would not render on {sheets}",
               name=path, sheets=", ".join(troubled)), 6000)

    def print_all(self) -> None:
        """Print the sheets marked for printing, in the order shown."""
        sheets = sf.printed_sheets(self._scene())
        if not sheets:
            self._window.viewport.flash_status(
                tr("No sheet is marked for printing"), 4000)
            return
        self.print_sheets(sheets)

    def export_all(self, path=None) -> None:
        """The sheets marked for printing into one PDF, in the order
        shown."""
        sheets = sf.printed_sheets(self._scene())
        if not sheets:
            self._window.viewport.flash_status(
                tr("No sheet is marked for printing"), 4000)
            return
        if path is None:
            from views.filedialogs import file_dialogs
            path, _ = file_dialogs.getSaveFileName(
                self, tr("Export all (PDF)…"), "sheets.pdf", "PDF (*.pdf)")
        self.export_sheets(sheets, path)


class SheetsTab(QWidget):
    """Scenes above, sheets below, with a divider between them to drag —
    the contents of the main window's Sheets tab and of the composer's
    Sheets page alike."""

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        from views.tray import ScenesPanel
        self._window = window
        self._composer_win = composer
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scenes = ScenesPanel(window)
        self.sheets = SheetExplorer(window, composer=composer)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(_titled(tr("Scenes"), self.scenes))
        split.addWidget(_titled(tr("Sheets"), self.sheets))
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        self.splitter = split
        lay.addWidget(split)

    def on_scene_changed(self) -> None:
        if self._composer_win is not None:
            sync_composer(self._window)
        self.scenes.refresh()
        self.sheets.on_scene_changed()

    def show_scene_row(self, name: str) -> None:
        """Make the scene called ``name`` the current row (a plan just
        made: the user sees where it went)."""
        self.scenes.refresh()
        lst = self.scenes.list
        for i in range(lst.count()):
            item = lst.item(i)
            view = item.data(Qt.UserRole)
            if view is not None and view.name == name:
                lst.setCurrentItem(item)
                lst.scrollToItem(item)
                return


def sync_composer(window) -> None:
    """Bring an open composer up to date with the document's sheets and
    scenes. It reloads them when it opens; a sheet or a scene made while it
    is already open (Create plan, the browser) — or one undone under it —
    did not reach it: the new sheet missed from its list, or the window
    kept showing a sheet that no longer existed."""
    from core import outliner
    comp_win = getattr(window, "_composer", None)
    if comp_win is None:
        return
    scene = window.viewport.scene
    # Only when the sheets or scenes changed: reloading the composer's list
    # refreshes the sheet strip, which calls back here.
    shape = outliner.sheets_shape(scene)
    if shape == getattr(comp_win, "_synced_shape", None):
        return
    comp_win._synced_shape = shape
    comps = scene.compositions
    if comp_win.comp not in comps:
        if not comps:
            return                          # it makes its own on showing
        from core.composition import ComposerHistory
        comp_win.comp = comps[0]
        comp_win.history = ComposerHistory(
            on_change=comp_win._on_history_change)
        comp_win._rebuild_canvas()
    comp_win._reload_comp_combo()
    reload = getattr(comp_win, "_reload_view_sources", None)
    if reload is not None:
        reload()
    if comp_win.isVisible():
        # A view placed or taken away from here, on the open sheet.
        comp_win._rebuild_canvas()
        QTimer.singleShot(0, comp_win._auto_render_stale)


def _titled(title: str, panel) -> QWidget:
    """A panel under a small bold heading."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(0)
    head = QLabel(title)
    font = QFont(head.font())
    font.setBold(True)
    head.setFont(font)
    head.setContentsMargins(8, 0, 8, 0)
    lay.addWidget(head)
    lay.addWidget(panel, 1)
    return box


class SheetsTray(QDockWidget):
    """Sidebar tab **Sheets**, beside the Browser: :class:`SheetsTab`."""

    def __init__(self, window) -> None:
        super().__init__(tr("Sheets"), window)
        self.setObjectName("tray_sheets")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetClosable)
        self.tab = SheetsTab(window)
        self.setWidget(self.tab)
        self.setMinimumWidth(240)

    def on_scene_changed(self) -> None:
        self.tab.on_scene_changed()
