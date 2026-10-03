# SPDX-License-Identifier: GPL-3.0-or-later
"""The Components tray as a tree of user-owned categories.

A flat grid is fine for a dozen components and an endless scroll for a
hundred. Here the components sit in categories (``core/component_categories.py``) the user creates, renames, deletes, nests up to three levels
and hides; a search box and a "Show all categories" switch sit on top.

The widget knows nothing about how a component is inserted: the panel hands
it :class:`ComponentEntry` rows, each with its own ``insert`` callback, so
bundled models, plugin components and 2D scale figures all go through one
door.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QInputDialog,
    QLineEdit, QMenu, QMessageBox, QSizePolicy, QStyle, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from core.i18n import tr
from core.component_categories import MAX_DEPTH, Taxonomy, TaxonomyError
from views import prompts as _prompts

_KIND = Qt.UserRole          # "cat" | "item"
_REF = Qt.UserRole + 1       # category id | item key

_SHOW_ALL_KEY = "components/show_all_categories"
_EXPANDED_KEY = "components/expanded_categories"

#: Past this many visible rows the tree scrolls on its own instead of
#: growing the tray further (same rule as the Layers list).
MAX_ROWS = 18
ICON_PX = 32


@dataclass(frozen=True)
class ComponentEntry:
    """One insertable thing in the tray."""
    key: str                          # "component:<key>" | "person:<key>"
    label: str
    tip: str
    insert: Callable[[], None]
    icon: Path | None = None
    default_path: tuple = ()


class _DropTree(QTreeWidget):
    """A tree that reports a drop instead of performing it: the category
    tree is data, so the panel moves the thing in the model and rebuilds."""

    #: kind, ref, the category the drag started in (None for a top-level
    #: category), the category dropped on (None = empty space), and whether
    #: Alt/Ctrl asked for a copy — a component may be listed in several
    #: categories, so dragging with a modifier ADDS instead of moving.
    dropped = Signal(str, str, object, object, bool)

    def dropEvent(self, event) -> None:            # noqa: N802 — Qt override
        src = self.currentItem()
        if src is None:
            event.ignore()
            return
        target = self.itemAt(event.position().toPoint())
        if target is not None and target.data(0, _KIND) == "item":
            target = target.parent()              # dropped on a component
        target_id = target.data(0, _REF) if target is not None else None
        origin = src.parent()
        origin_id = origin.data(0, _REF) if origin is not None else None
        copy = bool(event.modifiers() & (Qt.ControlModifier | Qt.AltModifier))
        self.dropped.emit(src.data(0, _KIND), src.data(0, _REF),
                          origin_id, target_id, copy)
        event.ignore()


class ComponentTree(QWidget):
    """Search box, "Show all categories", and the category tree."""

    def __init__(self, taxonomy: Taxonomy,
                 entries: list[ComponentEntry] | None = None) -> None:
        super().__init__()
        self._tax = taxonomy
        self._entries: list[ComponentEntry] = []
        self._by_key: dict = {}
        self._expanded: set = self._load_expanded()
        self._building = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search components…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.refresh())
        lay.addWidget(self.search)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        self.show_all = QCheckBox(tr("Show all categories"))
        self.show_all.setToolTip(tr(
            "Also list the categories you have hidden (right-click a "
            "category ▸ Hide category)"))
        self.show_all.setChecked(
            str(QSettings().value(_SHOW_ALL_KEY, "0")) == "1")
        self.show_all.toggled.connect(self._on_show_all)
        bar.addWidget(self.show_all, 1)
        self.add_btn = QToolButton()
        self.add_btn.setText("＋")
        self.add_btn.setToolTip(tr("New category"))
        self.add_btn.clicked.connect(lambda: self.prompt_new_category(None))
        bar.addWidget(self.add_btn)
        lay.addLayout(bar)

        self.tree = _DropTree()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(ICON_PX, ICON_PX))
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemActivated.connect(self._on_activated)
        self.tree.itemExpanded.connect(self._on_expanded)
        self.tree.itemCollapsed.connect(self._on_collapsed)
        self.tree.dropped.connect(self._on_dropped)
        self.tree.setToolTip(tr(
            "Double-click a component to insert it · right-click to manage "
            "categories · drag a component onto a category to move it "
            "(hold Alt or Ctrl to list it there as well)"))
        lay.addWidget(self.tree)

        self.set_entries(entries or [])

    # ---- data in ---------------------------------------------------------------

    def set_entries(self, entries: list[ComponentEntry]) -> None:
        self._entries = list(entries)
        self._by_key = {e.key: e for e in self._entries}
        self.refresh()

    # ---- building the tree -----------------------------------------------------

    def _categories_of(self, entry: ComponentEntry) -> list:
        return self._tax.nodes_of(entry.key, entry.default_path)

    def _visible(self, node_id: str) -> bool:
        return self.show_all.isChecked() or not self._tax.is_hidden(node_id)

    def refresh(self) -> None:
        """Rebuild from the model (categories, hidden flags, the search box)."""
        self._building = True
        try:
            tax = self._tax
            query = self.search.text().strip().casefold()
            by_node: dict = {}
            for e in self._entries:
                if query and query not in e.label.casefold() \
                        and query not in e.tip.casefold():
                    continue
                for node in self._categories_of(e):
                    by_node.setdefault(node.id, []).append(e)
            self.tree.clear()
            folder = self._folder_icon()

            def build(parent_item, parent_id) -> set:
                """The keys of the components under this level. A set, so a
                component listed in two subcategories counts once in their
                common parent."""
                found: set = set()
                for node in tax.children(parent_id):
                    if not self._visible(node.id):
                        continue
                    item = QTreeWidgetItem()
                    item.setData(0, _KIND, "cat")
                    item.setData(0, _REF, node.id)
                    item.setIcon(0, folder)
                    item.setFlags(item.flags() | Qt.ItemIsDropEnabled)
                    if parent_item is None:
                        self.tree.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    own = sorted(by_node.get(node.id, ()),
                                 key=lambda e: e.label.casefold())
                    for e in own:
                        leaf = QTreeWidgetItem()
                        leaf.setData(0, _KIND, "item")
                        leaf.setData(0, _REF, e.key)
                        leaf.setText(0, e.label)
                        leaf.setToolTip(0, e.tip)
                        if e.icon is not None:
                            leaf.setIcon(0, QIcon(str(e.icon)))
                        leaf.setFlags((leaf.flags() | Qt.ItemIsDragEnabled)
                                      & ~Qt.ItemIsDropEnabled)
                        item.addChild(leaf)
                    below = build(item, node.id)
                    count = len({e.key for e in own} | below)
                    hidden = tax.is_hidden(node.id)
                    label = f"{node.name}  ({count})"
                    if hidden:
                        label += "  · " + tr("hidden")
                    item.setText(0, label)
                    if hidden:
                        font = QFont(item.font(0))
                        font.setItalic(True)
                        item.setFont(0, font)
                        item.setForeground(
                            0, self.palette().placeholderText())
                    # While searching, hide the categories with nothing in
                    # them so the matches are what you see.
                    if query and count == 0:
                        if parent_item is None:
                            self.tree.takeTopLevelItem(
                                self.tree.indexOfTopLevelItem(item))
                        else:
                            parent_item.removeChild(item)
                        continue
                    item.setExpanded(bool(query)
                                     or node.id in self._expanded)
                    found |= {e.key for e in own} | below
                return found

            build(None, None)
            self._fit()
        finally:
            self._building = False

    def _folder_icon(self) -> QIcon:
        """The platform folder, drawn smaller than the thumbnails and centred
        in the same square so the labels of folders and components line up."""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainter, QPixmap
        small = self.style().standardIcon(QStyle.SP_DirIcon).pixmap(
            QSize(20, 20))
        canvas = QPixmap(ICON_PX, ICON_PX)
        canvas.fill(Qt.transparent)
        p = QPainter(canvas)
        p.drawPixmap(QRect((ICON_PX - 20) // 2, (ICON_PX - 20) // 2, 20, 20),
                     small)
        p.end()
        return QIcon(canvas)

    def _visible_rows(self) -> int:
        def count(item) -> int:
            n = 1
            if item.isExpanded():
                n += sum(count(item.child(i))
                         for i in range(item.childCount()))
            return n
        return sum(count(self.tree.topLevelItem(i))
                   for i in range(self.tree.topLevelItemCount()))

    def _fit(self) -> None:
        """Grow to the visible rows — no scroll bar of its own until there are
        a lot of them, so the tray's scroll stays the only one."""
        rows = self._visible_rows()
        capped = rows > MAX_ROWS
        self.tree.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if capped else Qt.ScrollBarAlwaysOff)
        self.tree.setSizePolicy(self.tree.sizePolicy().horizontalPolicy(),
                                QSizePolicy.Fixed)
        shown = min(rows, MAX_ROWS)
        first = self.tree.topLevelItem(0)
        row_h = self.tree.visualItemRect(first).height() if first else 0
        if row_h <= 0:
            row_h = max(ICON_PX, self.tree.fontMetrics().height()) + 6
        self.tree.setFixedHeight(
            max(shown, 3) * row_h + 2 * self.tree.frameWidth() + 4)

    # ---- expanded state --------------------------------------------------------

    @staticmethod
    def _load_expanded() -> set:
        raw = str(QSettings().value(_EXPANDED_KEY, "") or "")
        return {p for p in raw.split(",") if p}

    def _on_expanded(self, item) -> None:
        if not self._building and item.data(0, _KIND) == "cat":
            self._expanded.add(item.data(0, _REF))
            QSettings().setValue(_EXPANDED_KEY, ",".join(sorted(self._expanded)))
            self._fit()

    def _on_collapsed(self, item) -> None:
        if not self._building and item.data(0, _KIND) == "cat":
            self._expanded.discard(item.data(0, _REF))
            QSettings().setValue(_EXPANDED_KEY, ",".join(sorted(self._expanded)))
            self._fit()

    def _on_show_all(self, on: bool) -> None:
        QSettings().setValue(_SHOW_ALL_KEY, "1" if on else "0")
        self.refresh()

    # ---- model edits (the testable surface) ------------------------------------

    def create_category(self, name: str, parent_id: str | None = None) -> str:
        node = self._tax.create(name, parent_id)
        if parent_id is not None:
            self._expanded.add(parent_id)       # show what you just made
        self.refresh()
        return node.id

    def rename_category(self, node_id: str, name: str) -> None:
        self._tax.rename(node_id, name)
        self.refresh()

    def delete_category(self, node_id: str) -> None:
        self._tax.delete(node_id)
        self._expanded.discard(node_id)
        self.refresh()

    def set_category_hidden(self, node_id: str, hidden: bool) -> None:
        self._tax.set_hidden(node_id, hidden)
        self.refresh()

    def move_category(self, node_id: str, parent_id: str | None) -> None:
        self._tax.move(node_id, parent_id)
        if parent_id is not None:
            self._expanded.add(parent_id)
        self.refresh()

    def _default_path(self, item_key: str) -> tuple:
        entry = self._by_key.get(item_key)
        return entry.default_path if entry is not None else ()

    def add_item(self, item_key: str, node_id: str) -> None:
        """List a component in one more category (it stays in the others)."""
        self._tax.add_to(item_key, node_id, self._default_path(item_key))
        self._expanded.add(node_id)
        self.refresh()

    def move_item(self, item_key: str, from_id: str, to_id: str) -> None:
        """Take a component out of one category and into another."""
        self._tax.move_item(item_key, from_id, to_id,
                            self._default_path(item_key))
        self._expanded.add(to_id)
        self.refresh()

    def remove_item(self, item_key: str, node_id: str) -> None:
        """Stop listing a component in one category."""
        self._tax.remove_from(item_key, node_id, self._default_path(item_key))
        self.refresh()

    def leaf_labels(self) -> list:
        """The names of every component currently listed, collapsed
        categories included."""
        out: list = []
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, _KIND) == "item":
                out.append(it.text(0))
            stack.extend(it.child(i) for i in range(it.childCount()))
        return out

    def find_items(self, ref: str) -> list:
        """Every tree row for a category id or an item key — a component
        listed in three categories has three rows."""
        out: list = []
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, _REF) == ref:
                out.append(it)
            stack.extend(it.child(i) for i in range(it.childCount()))
        return out

    def find_item(self, ref: str):
        """The first tree row for a category id or an item key, or ``None``."""
        rows = self.find_items(ref)
        return rows[0] if rows else None

    # ---- user gestures ---------------------------------------------------------

    def _warn(self, err: TaxonomyError) -> None:
        QMessageBox.warning(self, tr("Categories"), tr(str(err)))

    def _guarded(self, fn, *args) -> bool:
        try:
            fn(*args)
            return True
        except TaxonomyError as err:
            self._warn(err)
            return False

    def prompt_new_category(self, parent_id: str | None) -> None:
        title = tr("New category") if parent_id is None \
            else tr("New subcategory")
        name, ok = _prompts.get_text(self, title, tr("Name:"))
        if ok:
            self._guarded(self.create_category, name, parent_id)

    def _prompt_rename(self, node_id: str) -> None:
        node = self._tax.get(node_id)
        if node is None:
            return
        name, ok = _prompts.get_text(self, tr("Rename category"), tr("Name:"),
                                     text=node.name)
        if ok:
            self._guarded(self.rename_category, node_id, name)

    def _prompt_delete(self, node_id: str) -> None:
        node = self._tax.get(node_id)
        if node is None:
            return
        subs = len(self._tax.descendants(node_id))
        extra = (tr(" and its %d subcategories") % subs) if subs else ""
        up = tr("their parent category") if node.parent_id \
            else tr("«Uncategorized»")
        answer = QMessageBox.question(
            self, tr("Delete category"),
            tr("Delete «%s»%s?\n\nThe components inside are not deleted — "
               "they move to %s.") % (node.name, extra, up))
        if answer == QMessageBox.Yes:
            self._guarded(self.delete_category, node_id)

    def _pick_category(self, item_key: str, title: str):
        """Ask which category, leaving out the ones the component is already
        in. ``None`` when cancelled or there is nowhere left to put it."""
        taken = {n.id for n in self._tax.nodes_of(
            item_key, self._default_path(item_key))}
        choices = [(nid, label) for nid, label in self._tax.choices()
                   if nid not in taken]
        if not choices:
            QMessageBox.information(
                self, title, tr("It is already in every category."))
            return None
        labels = [label for _id, label in choices]
        label, ok = QInputDialog.getItem(
            self, title, tr("Category:"), labels, 0, False)
        return choices[labels.index(label)][0] if ok else None

    def _prompt_add_item(self, item_key: str) -> None:
        node_id = self._pick_category(item_key, tr("Also list in category"))
        if node_id is not None:
            self._guarded(self.add_item, item_key, node_id)

    def _prompt_move_item(self, item_key: str, from_id: str) -> None:
        node_id = self._pick_category(item_key, tr("Move to category"))
        if node_id is not None:
            self._guarded(self.move_item, item_key, from_id, node_id)

    def _on_activated(self, item, _col=0) -> None:
        if item.data(0, _KIND) == "item":
            entry = self._by_key.get(item.data(0, _REF))
            if entry is not None:
                entry.insert()
        else:
            item.setExpanded(not item.isExpanded())

    def _on_dropped(self, kind: str, ref: str, origin_id, target_id,
                    copy: bool = False) -> None:
        if kind == "item":
            if target_id is None:
                return
            if copy or origin_id is None:
                self._guarded(self.add_item, ref, target_id)
            else:
                self._guarded(self.move_item, ref, origin_id, target_id)
        elif kind == "cat":
            self._guarded(self.move_category, ref, target_id)

    def _on_context_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        menu = QMenu(self)
        if item is None:
            menu.addAction(tr("New category…"),
                           lambda: self.prompt_new_category(None))
        elif item.data(0, _KIND) == "item":
            key = item.data(0, _REF)
            here = item.parent().data(0, _REF)
            here_name = self._tax.get(here).name if self._tax.get(here) else ""
            menu.addAction(tr("Insert"), lambda: self._on_activated(item))
            menu.addSeparator()
            menu.addAction(tr("Also list in another category…"),
                           lambda: self._prompt_add_item(key))
            menu.addAction(tr("Move to another category…"),
                           lambda: self._prompt_move_item(key, here))
            remove = menu.addAction(
                tr("Remove from «%s»") % here_name,
                lambda: self._guarded(self.remove_item, key, here))
            remove.setEnabled(len(self._tax.nodes_of(
                key, self._default_path(key))) > 1)
        else:
            nid = item.data(0, _REF)
            node = self._tax.get(nid)
            if node is None:
                return
            sub = menu.addAction(tr("New subcategory…"),
                                 lambda: self.prompt_new_category(nid))
            sub.setEnabled(self._tax.depth(nid) < MAX_DEPTH)
            menu.addAction(tr("Rename…"), lambda: self._prompt_rename(nid))
            menu.addSeparator()
            menu.addAction(
                tr("Show category") if node.hidden else tr("Hide category"),
                lambda: self.set_category_hidden(nid, not node.hidden))
            menu.addSeparator()
            menu.addAction(tr("Delete…"), lambda: self._prompt_delete(nid))
            menu.addSeparator()
            menu.addAction(tr("New category…"),
                           lambda: self.prompt_new_category(None))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
