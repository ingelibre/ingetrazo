# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene tree with native internal moves and folder-only drop targets."""
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QRect, Signal, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget


class SceneTree(QTreeWidget):
    moved = Signal()

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setAutoExpandDelay(600)
        self.setUniformRowHeights(True)
        self.setIndentation(18)
        icons = Path(__file__).resolve().parent.parent / "resources/icons"
        self._folder_icons = {
            False: QIcon(str(icons / "folder_collapsed.svg")),
            True: QIcon(str(icons / "folder_expanded.svg")),
        }

    def drawBranches(self, painter, rect, index):
        # The folder icon occupies the native expansion hit area in both trees.
        from core.layers import LayerFolder
        from core.saved_views import SceneFolder
        item = self.itemFromIndex(index)
        if item is not None and isinstance(item.data(0, Qt.UserRole),
                                           (LayerFolder, SceneFolder)):
            icon_rect = QRect(rect.right() - self.indentation() + 2,
                              rect.center().y() - 8, 16, 16)
            self._folder_icons[item.isExpanded()].paint(painter, icon_rect)

    def dropEvent(self, event):
        # Qt rejects self/descendant moves and items without ItemIsDropEnabled.
        blocked = self.blockSignals(True)
        try:
            super().dropEvent(event)
        finally:
            self.blockSignals(blocked)
        if event.isAccepted():
            self.moved.emit()

    def folder_selection(self):
        """Selected roots in display order and their closest common parent.

        A selected folder carries its descendants; permanent rows cannot move.
        """
        selected = []

        def visit(parent):
            for index in range(parent.childCount()):
                item = parent.child(index)
                if item.isSelected() and item.flags() & Qt.ItemIsDragEnabled:
                    selected.append(item)
                else:
                    visit(item)

        visit(self.invisibleRootItem())
        parent = selected[0].parent() if selected else None
        for item in selected[1:]:
            ancestors = []
            ancestor = item.parent()
            while ancestor is not None:
                ancestors.append(ancestor)
                ancestor = ancestor.parent()
            while parent is not None and parent not in ancestors:
                parent = parent.parent()
        return parent, selected


class LayerTree(SceneTree):
    """Keep the row selection when clicking a selected layer's checkboxes."""

    def selectionCommand(self, index, event=None):
        if (event is not None
                and event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease)
                and index.column() in (1, 2)):
            item = self.itemFromIndex(index)
            if item is not None and item.isSelected():
                return QItemSelectionModel.NoUpdate
        return super().selectionCommand(index, event)
