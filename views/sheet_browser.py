# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet composer's Sheets page: the scenes above, the sheet explorer
below.

The sheet explorer shows the sheets in the nested folders of
:mod:`core.sheet_folders`, each with the scenes placed on it and its Print
flag — what Print all and Export all take. Sheets and folders are dragged
to reorder or re-file them; a scene dragged from the list above onto a
sheet is placed on it. The scenes list is just that — a list to pick scenes
up from; they are made and changed in the main window's Scenes panel.

Each panel needs only the main window, never the page or dock it sits in,
and the panels speak to each other only through the document and the drag
data: a layout rework can later move them anywhere
(docs/sheet-browser-plan.md).
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QMimeData, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core import sheet_folders as sf
from core.i18n import tr

#: The sheet explorer's columns.
COL_NAME, COL_PRINT = 0, 1

_FOLDER, _SHEET, _FRAME = "folder", "sheet", "frame"

#: Drag data of sheets and folders moved inside the explorer (the rows
#: themselves travel in the panel: the drag never leaves it).
TREE_MIME = "application/x-ingetrazo-sheet-tree"

#: How many scenes the list above the sheets shows before it scrolls.
SCENE_ROWS = 7


class _SheetTree(QTreeWidget):
    """The explorer's tree: sheets and folders drag within it, scenes drop
    on it. Delete removes what is picked, F2 renames, Space flips Print,
    Alt+↑/↓ moves."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def mimeTypes(self):
        from views.composer import SCENE_MIME
        return [TREE_MIME, SCENE_MIME]

    def mimeData(self, items):
        sheets, folders = self._panel._items_of(items)
        self._panel._dragging = (sheets, folders)
        data = QMimeData()
        data.setData(TREE_MIME, b"1")
        return data

    def supportedDropActions(self):
        return Qt.MoveAction | Qt.CopyAction

    def dragEnterEvent(self, ev) -> None:
        if any(ev.mimeData().hasFormat(m) for m in self.mimeTypes()):
            ev.acceptProposedAction()
            super().dragEnterEvent(ev)
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:
        super().dragMoveEvent(ev)
        if any(ev.mimeData().hasFormat(m) for m in self.mimeTypes()):
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        item = self.itemAt(ev.position().toPoint())
        where = self.dropIndicatorPosition()
        mime = ev.mimeData()
        ev.setDropAction(Qt.IgnoreAction)          # the model moves, not Qt
        ev.accept()
        self._panel.drop(item, where, mime)

    def event(self, ev) -> bool:
        from PySide6.QtCore import QEvent
        if (ev.type() == QEvent.ShortcutOverride
                and self.state() != QAbstractItemView.EditingState
                and (ev.key() in (Qt.Key_Delete, Qt.Key_F2, Qt.Key_Space)
                     or (ev.key() in (Qt.Key_Up, Qt.Key_Down)
                         and ev.modifiers() & Qt.AltModifier))):
            ev.accept()                 # the composer's own keys wait
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:
        if self.state() != QAbstractItemView.EditingState and \
                not ev.isAutoRepeat():
            key = ev.key()
            if key in (Qt.Key_Up, Qt.Key_Down) and \
                    ev.modifiers() & Qt.AltModifier:
                self._panel.move_current(-1 if key == Qt.Key_Up else 1)
                return
            if key == Qt.Key_Delete:
                self._panel.delete_selected()
                return
            if key == Qt.Key_F2:
                self._panel.rename_current()
                return
            if key == Qt.Key_Space:
                self._panel.toggle_print_selected()
                return
        super().keyPressEvent(ev)


def _icon(key: str):
    from views.outliner import node_icon
    return node_icon(key)


def _print_icon(state: str):
    """``on``: printed; ``off``: switched off itself; ``inherited``: on
    itself but left out by a folder around it switched off — faded, as the
    Browser shows what a hidden group hides."""
    if state == "on":
        return _icon("print")
    if state == "off":
        return _icon("print_off")
    from views.outliner import _faded
    return _faded(_icon("print_off"))


class SheetExplorer(QWidget):
    """The document's sheets in their folders, each with the scenes placed
    on it: filter them, open one with a double-click, add sheets and
    folders, rename, delete, drag them around, choose which ones Print all
    and Export all take, print or export them.

    ``composer`` is the sheet composer it lives in: the sheet open there is
    marked, and scenes dropped on a sheet go through its undo."""

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        self._window = window
        self._composer_win = composer
        self._updating = False
        self._shape = None
        self._query = ""
        self._dragging = ([], [])
        self._related: list = []
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
            # Called with nothing: ``clicked`` passes its ``checked`` flag,
            # which the slots took for their optional argument — the new
            # sheet landed in a folder called False and never showed.
            btn = _tool_button("", tip, lambda _checked=False, s=slot: s())
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
            "switch it; a folder switched off leaves out everything inside "
            "it"))
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        head.setSectionResizeMode(COL_PRINT, QHeaderView.Fixed)
        head.resizeSection(COL_PRINT, 28)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setToolTip(tr(
            "Double-click a sheet to open it; drag sheets and folders to "
            "order them, and a scene onto a sheet to place it. The printer "
            "marks the sheets Print all and Export all take. Right-click for "
            "more."))
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
        self._poll.timeout.connect(self._poll_tick)
        self.refresh()

    # ---- Model → view ----------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _fingerprint(self, scene) -> tuple:
        current = getattr(self._composer_win, "comp", None)
        return (
            tuple((f.id, f.name, f.parent_id, f.expanded, f.print_in_all,
                   f.pos) for f in sf.folders_of(scene)),
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

    def _poll_tick(self) -> None:
        """The once-a-second check; it stops itself off screen. (No Python
        hideEvent for that: Qt calls it while it destroys the widget, when
        the timer may be gone already — memory went bad there and a later
        test crashed in native code.)"""
        if not self.isVisible():
            self._poll.stop()
            return
        self.refresh()

    @staticmethod
    def _print_state(scene, obj) -> str:
        """A folder's or sheet's printer: ``off`` when its own switch is
        off, ``inherited`` when it is on but a folder around it is off,
        ``on`` otherwise. What a folder holds never changes it."""
        if not getattr(obj, "print_in_all", True):
            return "off"
        around = (obj.parent_id if isinstance(obj, sf.SheetFolder)
                  else obj.folder_id)
        return "on" if sf.folder_printed(scene, around) else "inherited"

    @staticmethod
    def _left_out_by(scene, obj):
        """The nearest folder around ``obj`` switched off, or ``None``."""
        fid = (obj.parent_id if isinstance(obj, sf.SheetFolder)
               else obj.folder_id)
        seen: set = set()
        while fid is not None and fid not in seen:
            seen.add(fid)
            f = sf.folder_by_id(scene, fid)
            if f is None:
                return None
            if not f.print_in_all:
                return f
            fid = f.parent_id
        return None

    def _set_print_cell(self, scene, item, obj) -> None:
        state = self._print_state(scene, obj)
        item.setIcon(COL_PRINT, _print_icon(state))
        by = self._left_out_by(scene, obj) if state == "inherited" else None
        item.setToolTip(COL_PRINT, tr(
            "Left out by the folder «{name}», switched off",
            name=by.name) if by is not None else "")

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
        self._related = []
        open_sheet = getattr(self._composer_win, "comp", None)
        bold = QFont(self.tree.font())
        bold.setBold(True)
        from core import outliner
        from core.composition import format_scale
        from views.composer import frame_view_name

        def add(parent_item, folder_id, seen) -> None:
            # Folders and sheets mixed, as the user placed them.
            for entry in sf.children(scene, folder_id):
                if isinstance(entry, sf.SheetFolder):
                    f = entry
                    if f.id in seen:
                        continue
                    item = QTreeWidgetItem([f.name, ""])
                    item.setData(COL_NAME, Qt.UserRole, (_FOLDER, f))
                    item.setIcon(COL_NAME, _icon("folder"))
                    self._set_print_cell(scene, item, f)
                    item.setFlags(item.flags() | Qt.ItemIsEditable
                                  | Qt.ItemIsDragEnabled
                                  | Qt.ItemIsDropEnabled)
                    parent_item.addChild(item)
                    self.items[id(f)] = item
                    add(item, f.id, seen | {f.id})
                    item.setExpanded(f.expanded)
                    continue
                c = entry
                item = QTreeWidgetItem([c.name, ""])
                item.setData(COL_NAME, Qt.UserRole, (_SHEET, c))
                item.setIcon(COL_NAME, _icon("sheet"))
                self._set_print_cell(scene, item, c)
                item.setFlags(item.flags() | Qt.ItemIsEditable
                              | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
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
                    # A scene row is part of its sheet: dropped on, it
                    # means the sheet; it is not dragged by itself.
                    row.setFlags((row.flags() | Qt.ItemIsDropEnabled)
                                 & ~Qt.ItemIsDragEnabled)
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

    # ---- A scene and the views that show it ------------------------------------
    def mark_scene(self, name) -> list:
        """Mark the views showing the scene called ``name`` (``None``:
        none). Returns the marked rows."""
        from core import outliner
        from views.tray import mark_row
        # A mark is an item change to Qt, not an edit of the row.
        self._updating = True
        try:
            for row in self._related:
                mark_row(row, False)
            self._related = []
            if name is not None:
                for item in self.items.values():
                    d = item.data(COL_NAME, Qt.UserRole)
                    if d and d[0] == _FRAME and \
                            outliner.frame_scene(d[2]) == name:
                        mark_row(item, True)
                        self._related.append(item)
        finally:
            self._updating = False
        return list(self._related)

    def related(self) -> list:
        return list(self._related)

    # ---- Reading the selection ---------------------------------------------------
    @staticmethod
    def _items_of(rows) -> tuple[list, list]:
        """``(sheets, folders)`` among ``rows`` (a scene row stands for its
        sheet)."""
        sheets, folders = [], []
        for item in rows:
            d = item.data(COL_NAME, Qt.UserRole)
            if not d:
                continue
            if d[0] == _FOLDER:
                folders.append(d[1])
            elif d[1] not in sheets:
                sheets.append(d[1])
        return sheets, folders

    def _picked(self) -> tuple[list, list]:
        return self._items_of(self.tree.selectedItems())

    def _target_folder_id(self):
        """Where a new sheet or folder goes: into the selected folder, or
        beside the selected sheet; the top when nothing is selected."""
        item = self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if not d or not item.isSelected():
            return None
        return d[1].id if d[0] == _FOLDER else d[1].folder_id

    def current_sheet(self):
        item = self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return d[1] if d and d[0] in (_SHEET, _FRAME) else None

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
        a printer, a name typed, a drop) arrives while Qt still holds the
        row it changed, and rebuilding the tree right then deletes that row
        under it."""
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
        obj = d[1]
        # Left out by a folder around it, not by itself: that folder is
        # what brings it back — say so, as the Browser does for a group.
        by = self._left_out_by(scene, obj)
        if by is not None and obj.print_in_all:
            self._window.viewport.flash_status(tr(
                "Left out by the folder «{name}»: switch it on first",
                name=by.name), 3500)
            return
        # On one of several selected rows: all of them, as the Browser's
        # eye does.
        sheets, folders = self._picked()
        if obj not in sheets and obj not in folders:
            sheets, folders = (([], [obj]) if d[0] == _FOLDER
                               else ([obj], []))
        self.set_printed(sheets, not obj.print_in_all, defer=True,
                         folders=folders)

    def set_printed(self, sheets, on: bool, defer: bool = False,
                    folders=()) -> None:
        """The Print switch of ``sheets`` and ``folders`` — one undo step.
        A folder's is its own: what it holds keeps theirs."""
        sheets = [c for c in sheets if c.print_in_all != bool(on)]
        folders = [f for f in folders if f.print_in_all != bool(on)]
        if not sheets and not folders:
            return
        from core.history import SetSheetPrintCommand
        self._history().execute(SetSheetPrintCommand(sheets, on, folders))
        (self._after_edit_in_tree if defer else self._after_tree_change)()

    def toggle_print_selected(self) -> None:
        """Space: the selected sheets and folders flip together — on,
        unless all of them already are."""
        sheets, folders = self._picked()
        rows = sheets + folders
        if rows:
            self.set_printed(sheets, not all(r.print_in_all for r in rows),
                             folders=folders)

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

    # ---- Moving: drag & drop, Alt+↑/↓ ----------------------------------------
    def move(self, sheets, folders, target_id, before=None) -> None:
        """Sheets and folders into folder ``target_id`` in front of
        ``before`` (a sheet or folder; ``None``: at the end) — one undo
        step. A folder never goes into itself; the sheet tabs follow the
        new order."""
        scene = self._scene()
        folders = [f for f in folders
                   if sf.can_move_folder(scene, f, target_id)]
        # A folder's own sheets travel with it: only the loose ones move.
        moving_ids = set()
        for f in folders:
            moving_ids |= {f.id} | sf.descendant_ids(scene, f.id)
        sheets = [c for c in sheets if c.folder_id not in moving_ids]
        if not sheets and not folders:
            return
        from core.history import MoveSheetItemsCommand
        self._history().execute(MoveSheetItemsCommand(
            sheets, folders, target_id, before))

    def drop(self, item, where, mime) -> None:
        """What a drop on ``item`` at ``where`` (Qt's indicator) does:
        scenes are placed on the sheet dropped on — a new one when dropped
        on no sheet; sheets and folders move there."""
        from views.composer import SCENE_MIME
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if mime.hasFormat(SCENE_MIME):
            names = [n for n in bytes(mime.data(SCENE_MIME)).decode(
                "utf-8").split("\n") if n]
            views = {v.name: v for v in self._scene().saved_views}
            sheet = d[1] if d and d[0] in (_SHEET, _FRAME) else None
            folder_id = (d[1].id if d and d[0] == _FOLDER
                         else sheet.folder_id if sheet is not None else None)
            for name in names:
                if name in views:
                    self.place_scene(views[name], sheet, folder_id=folder_id)
            self._after_edit_in_tree()
            return
        if not mime.hasFormat(TREE_MIME):
            return
        sheets, folders = self._dragging
        self._dragging = ([], [])
        if d and d[0] == _FRAME:            # a scene row means its sheet
            item, d = self.items.get(id(d[1])), (_SHEET, d[1])
            where = QAbstractItemView.OnItem
        scene = self._scene()
        if d is None:                       # empty space: the top, at the end
            target, before = None, None
        elif where == QAbstractItemView.OnItem and d[0] == _FOLDER:
            target, before = d[1].id, None  # into the folder
        else:
            obj = d[1]
            target = obj.parent_id if d[0] == _FOLDER else obj.folder_id
            if where == QAbstractItemView.AboveItem:
                before = obj
            else:                           # below, or on a sheet: after it
                before = self._next_sibling(scene, obj, sheets, folders)
        self.move(sheets, folders, target, before)
        self._after_edit_in_tree()

    @staticmethod
    def _next_sibling(scene, obj, sheets, folders):
        """The item after ``obj`` in its folder that is not moving — what
        «after ``obj``» goes in front of (``None``: the end)."""
        moving = {id(x) for x in list(sheets) + list(folders)}
        parent = (obj.parent_id if isinstance(obj, sf.SheetFolder)
                  else obj.folder_id)
        sibs = [x for x in sf.children(scene, parent)
                if id(x) not in moving or x is obj]
        at = next((k for k, x in enumerate(sibs) if x is obj), None)
        rest = [x for x in sibs[at + 1:] if id(x) not in moving] \
            if at is not None else []
        return rest[0] if rest else None

    def move_current(self, step: int) -> None:
        """Alt+↑/↓: the current sheet (or folder) one place up or down
        among its neighbours in the same folder — sheets and folders
        alike."""
        item = self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if not d or d[0] == _FRAME:
            return
        scene = self._scene()
        obj = d[1]
        target = obj.parent_id if d[0] == _FOLDER else obj.folder_id
        sibs = sf.children(scene, target)
        i = next(k for k, x in enumerate(sibs) if x is obj)
        j = i + step
        if not 0 <= j < len(sibs):
            return
        others = [x for x in sibs if x is not obj]
        before = others[j] if j < len(others) else None
        sheets, folders = ([], [obj]) if d[0] == _FOLDER else ([obj], [])
        self.move(sheets, folders, target, before)
        self._after_tree_change()
        moved = self.items.get(id(obj))
        if moved is not None:
            self.tree.setCurrentItem(moved)

    # ---- Scenes on sheets ---------------------------------------------------------
    def place_scene(self, view, sheet=None, scale: float = 100.0,
                    folder_id=None):
        """Place scene ``view`` on ``sheet`` — on a new sheet named after
        it, in ``folder_id``, when ``None`` — in a free spot of the page, at
        1:``scale``. One undo step; returns the new frame."""
        from core import outliner
        from core.composition import Composicion, MarcoVista
        from core.history import (AddSheetCommand, CompoundCommand,
                                  PlaceViewCommand)
        scene = self._scene()
        comp_win = self._composer_win
        if comp_win is not None and sheet is not None:
            # Beside the page: open that sheet and put the view in a free
            # place of it, as one step of the composer's own undo.
            comps = scene.compositions
            if comp_win.comp is not sheet and sheet in comps:
                comp_win.show_sheet(comps.index(sheet))
            return comp_win.place_scene_at(view.name)
        cmds = []
        if sheet is None:
            sheet = Composicion(name=outliner.unique_name(
                view.name, [c.name for c in scene.compositions]),
                paper="A3", folder_id=folder_id)
            cmds.append(AddSheetCommand(sheet))
        pw, ph = sheet.page_size_mm()
        m = float(getattr(sheet, "margin_mm", 10.0) or 0.0)
        w_mm = max(60.0, (pw - 2 * m) / 2 - 15)
        h_mm = max(45.0, (ph - 2 * m) / 2 - 15)
        # A quarter of the page where there is room; smaller where there is
        # less; over the others, a step aside, only on a full page.
        spot = None
        for k in (1.0, 0.75, 0.5, 0.35):
            spot = outliner.free_slot(sheet, w_mm * k, h_mm * k,
                                      fallback=False)
            if spot is not None:
                w_mm, h_mm = w_mm * k, h_mm * k
                break
        x, y = spot if spot is not None else outliner.free_slot(
            sheet, w_mm, h_mm)
        frame = MarcoVista(x_mm=x, y_mm=y, w_mm=w_mm, h_mm=h_mm,
                           view_key=f"scene:{view.name}",
                           scale_n=float(scale), show_title=True)
        cmds.append(PlaceViewCommand(sheet, frame))
        self._history().execute(
            CompoundCommand(cmds) if len(cmds) > 1 else cmds[0])
        sf.sync_order(scene)
        refresh_tabs = getattr(self._window, "_refresh_sheet_tabs", None)
        if refresh_tabs is not None:
            refresh_tabs()
        self._window.viewport.flash_status(tr(
            "«{scene}» placed on «{sheet}»", scene=view.name,
            sheet=sheet.name), 4000)
        self.refresh(force=True)
        return frame

    # ---- Right-click ---------------------------------------------------------
    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if item is not None and not item.isSelected():
            self.tree.setCurrentItem(item)
        menu = self.build_menu(d)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def build_menu(self, d):
        """The right-click menu for a row's data ``d`` (``None``: empty
        space) — the bar's actions, for what was clicked."""
        from core import outliner
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
            views = list(getattr(scene, "saved_views", None) or ())
            if views:
                sub = menu.addMenu(_icon("scene"), tr("Place a scene here"))
                free = outliner.unplaced_scenes(scene)
                for v in free + [v for v in views if v not in free]:
                    sub.addAction(v.name, lambda vv=v, s=sheet:
                                  self.place_scene(vv, s))
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
            menu.addAction(tr("Move up (Alt+↑)"),
                           lambda: (self.tree.setCurrentItem(
                               self.items[id(sheet)]), self.move_current(-1)))
            menu.addAction(tr("Move down (Alt+↓)"),
                           lambda: (self.tree.setCurrentItem(
                               self.items[id(sheet)]), self.move_current(1)))
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
            on = not all(f.print_in_all for f in folders)
            menu.addAction(_print_icon("on" if on else "off"),
                           tr("Include in Print all") if on
                           else tr("Exclude from Print all"),
                           lambda: self.set_printed([], on, folders=folders))
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
            menu.addAction(_icon("print"), tr("Print all…"),
                           lambda: self.print_all())
            menu.addAction(_icon("pdf"), tr("Export all (PDF)…"),
                           lambda: self.export_all())
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
                self, tr("Export PDF…"),
                self._window._ensure_composer().default_pdf_path(),
                "PDF (*.pdf)")
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
                self, tr("Export all (PDF)…"),
                self._window._ensure_composer().default_pdf_path(),
                "PDF (*.pdf)")
        self.export_sheets(sheets, path)


class SheetsTab(QWidget):
    """Scenes above, sheets below, with a divider between them to drag —
    the composer's Sheets page. The scenes list shows :data:`SCENE_ROWS`
    scenes and scrolls past them; the sheets take the rest."""

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        from views.tray import ScenesPanel
        self._window = window
        self._composer_win = composer
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # Just the list, to drag scenes onto sheets — they are made and
        # changed in the main window's Scenes panel. In the composer a
        # double-click places the scene on the open sheet, and each scene
        # shows its picture.
        self.scenes = ScenesPanel(
            window, compact=True,
            on_activate=(lambda view: composer.place_scene_at(view.name))
            if composer is not None else None,
            icon_for=composer.scene_thumbnail if composer is not None
            else None)
        self.sheets = SheetExplorer(window, composer=composer)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(_titled(tr("Scenes"), self.scenes))
        split.addWidget(_titled(tr("Sheets"), self.sheets))
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        self.splitter = split
        lay.addWidget(split)
        self._fit_scenes()
        # A scene and the views that show it mark each other.
        self.scenes.list.currentItemChanged.connect(
            lambda item, _prev: self.sheets.mark_scene(
                item.text() if item is not None else None))
        self.sheets.tree.currentItemChanged.connect(
            lambda item, _prev: self._mark_from_sheets(item))

    def _fit_scenes(self) -> None:
        """Room for :data:`SCENE_ROWS` scenes; more scroll."""
        lst = self.scenes.list
        row = max(lst.fontMetrics().height(), lst.iconSize().height()) + 6
        frame = 2 * lst.frameWidth()
        lst.setMaximumHeight(SCENE_ROWS * row + frame)
        lst.setMinimumHeight(2 * row + frame)

    def _mark_from_sheets(self, item) -> None:
        from core import outliner
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        name = outliner.frame_scene(d[2]) if d and d[0] == _FRAME else None
        self.scenes.mark(name)

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
