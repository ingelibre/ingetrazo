# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«My Library» in the Components tray: your own folders of components,
as a tree (#1088, #354). The rules live in :mod:`core.user_library`.

A double click inserts a component, which then follows the cursor as
File ▸ Import does. A right click on a folder makes a subfolder, renames
it, opens it in the file manager or saves the selected component into it;
on a file it inserts, renames or shows it. Dragging a row onto a folder
moves the file there — on the disk, since the folders ARE the library.

Pictures are drawn for the rows on screen only, one per tick, and kept
in a cache keyed by the file's size and time (see
:func:`core.user_library.thumbnail_path`): a library on a network drive
costs one read per file, once.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMenu, QMessageBox, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core import user_library as lib
from core.i18n import tr
from views.side_tree import SideTree

#: Picture side of a component row, as in the «In model» list.
ICON = 40
#: Rows of the tree shown before it scrolls.
ROWS = 7

#: Item data: the entry's path, and whether it is a folder.
PATH_ROLE = Qt.UserRole
DIR_ROLE = Qt.UserRole + 1
ROOT_ROLE = Qt.UserRole + 2


class LibraryTree(SideTree):
    """The tree itself: what a drop lands on is a folder row (a file row
    means its folder), and the drop moves the files on the disk."""

    def drop_target(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return None
        if not item.data(0, DIR_ROLE):
            item = item.parent()
        return item

    def drop_items(self, token):
        return [token] if token is not None else []

    def drop_text(self, token) -> str:
        if token is None:
            return tr("Drop on a folder")
        return tr("Move to {folder}", folder=token.text(0))

    def drop_rect(self, token):
        if token is None:
            from PySide6.QtCore import QRect
            return QRect()
        return super().drop_rect(token)

    def apply_drop(self, token, rows) -> None:
        self._panel.move_rows(token, rows)

    def drag_starter(self, rows):
        """One component file dragged: let go in the view, it is placed
        there, as its double click places it. Folders, or several rows,
        only move."""
        if len(rows) != 1 or rows[0].data(0, DIR_ROLE):
            return None
        path = Path(self._panel._key(rows[0]))
        return lambda: self._panel.insert(path)

    def resizeEvent(self, event) -> None:            # noqa: N802 — Qt
        super().resizeEvent(event)
        # Taller, it shows rows that had no room: their pictures now.
        self._panel._schedule_thumbs()


class UserLibraryWidget(QWidget):
    """The «My Library» section of the Components tray."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._expanded: set = set()
        self._roots: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.addWidget(QLabel(f"<b>{tr('My Library')}</b>"), 1)
        self._add_btn = self._tool_button("folder_add", tr(
            "Add a folder of your own (on this computer or the network) "
            "to the library"), lambda: self.add_folder())
        head.addWidget(self._add_btn)
        self._refresh_btn = self._tool_button(
            "refresh", tr("Read the library folders again"), self.refresh)
        head.addWidget(self._refresh_btn)
        lay.addLayout(head)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("Search my library…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._rebuild)
        lay.addWidget(self._search)

        self.tree = LibraryTree(self)
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setIconSize(QSize(ICON, ICON))
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.setToolTip(tr(
            "Your own components, one .igz file each, sorted in folders — "
            "double-click one to place it, or drag it into the view"))
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemCollapsed.connect(
            lambda it: self._expanded.discard(self._key(it)))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.setMinimumHeight(ICON * 3)
        self.tree.setMaximumHeight((ICON + 6) * ROWS)
        self.tree.verticalScrollBar().valueChanged.connect(
            self._schedule_thumbs)
        lay.addWidget(self.tree)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setEnabled(False)
        lay.addWidget(self._hint)

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(15)
        self._thumb_timer.timeout.connect(self._draw_one_thumb)
        self._blank = None
        self.refresh()

    @staticmethod
    def _tool_button(key: str, tip: str, slot) -> QToolButton:
        """A flat button with one of the app's icons, drawn again with
        the theme (``icon_key``), as the Scenes panel's are."""
        from views.icons import tool_icon
        btn = QToolButton()
        btn.setIcon(tool_icon(key))
        btn.setProperty("icon_key", key)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        btn.clicked.connect(lambda _c=False: slot())
        return btn

    def _folder_icon(self) -> QIcon:
        """The folder at its own size, in the middle of a picture's room:
        the names of folders and components then start at the same place,
        and a folder does not grow to the size of a picture."""
        if getattr(self, "_folder", None) is None:
            from PySide6.QtGui import QPainter
            from views.outliner import node_icon
            side = 20
            pm = QPixmap(ICON, ICON)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.drawPixmap((ICON - side) // 2, (ICON - side) // 2,
                         node_icon("folder").pixmap(side, side))
            p.end()
            self._folder = QIcon(pm)
        return self._folder

    # ---- what is shown --------------------------------------------------
    @staticmethod
    def _key(item) -> str:
        return str(item.data(0, PATH_ROLE))

    def _on_expanded(self, item) -> None:
        self._expanded.add(self._key(item))
        # The rows a folder opens onto get their pictures too, not only
        # the ones a scroll brings into view.
        self._schedule_thumbs()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self.refresh()

    def refresh(self) -> None:
        """Read the folders from the disk and show them."""
        self._roots = [lib.scan(r) for r in lib.folders()]
        if not self._expanded:
            # The first time, the roots open: that is the library.
            self._expanded = {str(r.path) for r in self._roots}
        self._rebuild()

    def _rebuild(self, _text=None) -> None:
        tree = self.tree
        tree.clear()
        text = self._search.text()
        shown = 0
        for root in self._roots:
            node = lib.filtered(root, text)
            if node is None:
                continue
            item = self._add(None, node, root=True)
            shown += sum(1 for _ in node.files())
            if text.strip():
                tree.expandAll()
        total = sum(sum(1 for _ in r.files()) for r in self._roots)
        if text.strip() and not shown:
            self._hint.setText(tr("No component matches"))
        elif not total:
            self._hint.setText(tr(
                "No components yet. Right-click a component in the model "
                "▸ Save to My Library…, or put .igz files in the folder."))
        else:
            self._hint.setText("")
        self._hint.setVisible(bool(self._hint.text()))
        self._schedule_thumbs()

    def _add(self, parent, node, root=False):
        item = QTreeWidgetItem([node.name])
        item.setData(0, PATH_ROLE, str(node.path))
        item.setData(0, DIR_ROLE, node.is_dir)
        item.setData(0, ROOT_ROLE, root)
        if node.is_dir:
            item.setIcon(0, self._folder_icon())
            tip = str(node.path)
            if node.missing:
                item.setText(0, tr("{name} (not found)", name=node.name))
                tip = tr("This folder cannot be read now: {path}",
                         path=node.path)
            item.setToolTip(0, tip)
            item.setFlags(item.flags() | Qt.ItemIsDropEnabled)
        else:
            item.setIcon(0, self._blank_icon())
            item.setToolTip(0, str(node.path))
            item.setFlags(item.flags() & ~Qt.ItemIsDropEnabled)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        for c in node.children:
            self._add(item, c)
        if node.is_dir and str(node.path) in self._expanded:
            item.setExpanded(True)
        return item

    def _blank_icon(self) -> QIcon:
        if self._blank is None:
            pm = QPixmap(ICON, ICON)
            pm.fill(Qt.transparent)
            self._blank = QIcon(pm)
        return self._blank

    def items(self):
        """Every row, depth first (folders and files)."""
        out = []

        def walk(it):
            out.append(it)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    def file_items(self):
        return [it for it in self.items() if not it.data(0, DIR_ROLE)]

    # ---- pictures -------------------------------------------------------
    def _schedule_thumbs(self, _value=None) -> None:
        timer = getattr(self, "_thumb_timer", None)  # None while building
        if timer is not None:
            timer.start()

    def _visible_unpictured(self):
        vp = self.tree.viewport().rect()
        for it in self.file_items():
            if it.data(0, Qt.UserRole + 3):
                continue
            r = self.tree.visualItemRect(it)
            if r.isValid() and r.intersects(vp):
                return it
        return None

    def _draw_one_thumb(self) -> None:
        it = self._visible_unpictured()
        if it is None:
            self._thumb_timer.stop()
            return
        it.setData(0, Qt.UserRole + 3, True)
        icon = self.picture(Path(self._key(it)))
        if icon is not None:
            it.setIcon(0, icon)

    @staticmethod
    def picture(path: Path):
        """The icon of a library file: from the cache, or drawn (and then
        kept). ``None`` when the file cannot be read."""
        cached = lib.thumbnail_path(path, ICON)
        if cached is None:
            return None
        if cached.exists():
            return QIcon(str(cached))
        try:
            comp = lib.load_component(path)
        except Exception:  # noqa: BLE001 - a broken file keeps no picture
            return None
        if comp is None:
            return None
        from views.component_thumbs import thumbnail
        pm = thumbnail(comp, ICON)
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            pm.save(str(cached), "PNG")
        except OSError:
            pass
        return QIcon(pm)

    # ---- acting ---------------------------------------------------------
    def _on_double_click(self, item, _col=0) -> None:
        if not item.data(0, DIR_ROLE):
            self.insert(Path(self._key(item)))

    def insert(self, path: Path) -> None:
        """Place the component of ``path``: it follows the cursor and a
        click drops it, as File ▸ Import does."""
        self._window.insert_library_file(path)

    def _folder_of(self, item) -> Path | None:
        if item is None:
            return None
        if item.data(0, DIR_ROLE):
            return Path(self._key(item))
        return Path(self._key(item)).parent

    def _menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self.tree)
        menu.setToolTipsVisible(True)
        for text, callback, tip in self.menu_actions(item):
            if text is None:
                menu.addSeparator()
                continue
            act = menu.addAction(text)
            if tip:
                act.setToolTip(tip)
            if callback is None:
                act.setEnabled(False)
            else:
                act.triggered.connect(lambda _c=False, cb=callback: cb())
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def menu_actions(self, item) -> list:
        """``[(text, callback, tip)]`` for a right click on ``item`` (or
        on the empty list): kept apart so it can be read without a menu.
        ``callback`` None = shown greyed; ``text`` None = a separator."""
        from core.desktop_open import open_url
        out: list = []
        if item is not None and not item.data(0, DIR_ROLE):
            path = Path(self._key(item))
            out.append((tr("Place in Model"),
                        lambda: self.insert(path), None))
            out.append((tr("Rename…"), lambda: self.rename(item), None))
            out.append((tr("Show in Folder"),
                        lambda: open_url(path.parent), None))
            return out
        if item is not None:
            folder = Path(self._key(item))
            definition = self._window.selected_component_definition()
            out.append((tr("Save Selected Component Here"),
                        (lambda: self._window.save_component_to_library(
                            definition, folder))
                        if definition is not None else None,
                        None if definition is not None else tr(
                            "Select one component in the model first")))
            out.append((tr("New Folder…"),
                        lambda: self.new_folder(folder), None))
            if not item.data(0, ROOT_ROLE):
                out.append((tr("Rename…"), lambda: self.rename(item), None))
            out.append((tr("Open Folder"),
                        lambda: self.open_folder(folder), None))
            if item.data(0, ROOT_ROLE):
                out.append((None, None, None))
                out.append((tr("Remove from Library"),
                            lambda: self.remove_root(folder),
                            tr("Stop listing this folder here. Its files "
                               "stay where they are.")))
        out.append((None, None, None))
        out.append((tr("Add Folder…"), self.add_folder, None))
        out.append((tr("Refresh"), self.refresh, None))
        return out

    def open_folder(self, folder: Path) -> None:
        """Open ``folder`` in the file manager — made first when it is the
        default one, not created yet, so there is somewhere to put files."""
        from core.desktop_open import open_url
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        open_url(folder)

    def _ask_name(self, title, label, text="") -> str | None:
        name, ok = QInputDialog.getText(self, title, label, text=text)
        name = (name or "").strip()
        return name if ok and name else None

    def new_folder(self, parent: Path, name: str | None = None):
        if name is None:
            name = self._ask_name(tr("New Folder"), tr("Folder name:"))
            if name is None:
                return None
        try:
            path = lib.new_folder(parent, name)
        except OSError as exc:
            QMessageBox.warning(self, tr("New Folder"), str(exc))
            return None
        self._expanded.add(str(parent))
        self.refresh()
        return path

    def rename(self, item, name: str | None = None):
        path = Path(self._key(item))
        if name is None:
            name = self._ask_name(tr("Rename"), tr("New name:"),
                                  path.stem if path.is_file() else path.name)
            if name is None:
                return None
        try:
            new = lib.rename(path, name)
        except FileExistsError:
            QMessageBox.warning(self, tr("Rename"), tr(
                "There is already one called “{name}” there.", name=name))
            return None
        except OSError as exc:
            QMessageBox.warning(self, tr("Rename"), str(exc))
            return None
        if str(path) in self._expanded:
            self._expanded.add(str(new))
        self.refresh()
        return new

    def add_folder(self, path=None) -> None:
        if path is None:
            from views.filedialogs import file_dialogs
            start = str(lib.folders()[0]) if lib.folders() else ""
            path = file_dialogs.getExistingDirectory(
                self, tr("Add Folder to My Library"), start)
            if not path:
                return
        lib.add_folder(path)
        self._expanded.add(str(Path(path)))
        self.refresh()

    def remove_root(self, folder: Path) -> None:
        lib.remove_folder(folder)
        self.refresh()

    def move_rows(self, token, rows) -> None:
        """A drop: the dragged files (or folders) go into ``token``'s folder
        on the disk."""
        folder = self._folder_of(token)
        if folder is None:
            return
        moved = 0
        for it in rows:
            if it.data(0, ROOT_ROLE):
                continue                  # a root is not inside anything
            try:
                lib.move_into(Path(self._key(it)), folder)
                moved += 1
            except (OSError, ValueError):
                continue
        if moved:
            self._expanded.add(str(folder))
            self.refresh()
