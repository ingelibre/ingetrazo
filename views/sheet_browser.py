# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet composer's Sheets and Scenes tabs.

The Sheets tab (:class:`SheetExplorer`) shows the sheets as pages, as a PDF
reader lists its pages — moved, copied, pasted, duplicated, deleted and
renamed there — or, in its List view, in the nested folders of
:mod:`core.sheet_folders` with their Print flag (what Print all and Export
all take). Neither view lists the scenes placed on each sheet: those are
the Scenes tab's. The Scenes tab (:class:`SceneList`) holds the scenes in
the folders of the main window's Scenes tab, only to be picked up from;
they are made, filed and changed there, and a scene dragged onto a sheet
is placed on it.

Each panel needs only the main window, never the page or dock it sits in,
and the panels speak to each other only through the document and the drag
data: a layout rework can later move them anywhere
(docs/sheet-browser-plan.md).
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QMimeData, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QSplitter,
    QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from core import sheet_folders as sf
from core import sheet_sets as ss
from core.i18n import tr
from views.sheet_pages import holds, index_of

#: The sheet explorer's columns (its List view).
COL_NAME, COL_PRINT = 0, 1

_FOLDER, _SHEET = "folder", "sheet"

#: Drag data of sheets and folders moved inside the explorer (the rows
#: themselves travel in the panel: the drag never leaves it).
TREE_MIME = "application/x-ingetrazo-sheet-tree"

#: Drag data of pages moved in the Pages view (the sheets travel in the
#: panel, as the tree's rows do).
PAGE_MIME = "application/x-ingetrazo-sheet-pages"

#: How many scenes the list above the sheets shows before it scrolls.
SCENE_ROWS = 7


def _own_key(ev):
    """Which of the Sheets tab's own keys ``ev`` is — ``"up"``, ``"down"``,
    ``"delete"``, ``"rename"``, ``"copy"``, ``"paste"``, ``"duplicate"`` —
    or ``None``. Exactly those keys: with another modifier held (Shift+Del,
    Ctrl+F2, Ctrl+Shift+D…) the key is someone else's."""
    from PySide6.QtGui import QKeySequence
    key = ev.key()
    mods = ev.modifiers() & ~Qt.KeypadModifier
    if mods == Qt.AltModifier and key in (Qt.Key_Up, Qt.Key_Down):
        return "up" if key == Qt.Key_Up else "down"
    if mods == Qt.NoModifier and key == Qt.Key_Delete:
        return "delete"
    if mods == Qt.NoModifier and key == Qt.Key_F2:
        return "rename"
    if ev.matches(QKeySequence.Copy):
        return "copy"
    if ev.matches(QKeySequence.Paste):
        return "paste"
    if mods == Qt.ControlModifier and key == Qt.Key_D:
        return "duplicate"
    return None


def _shortcut_keys(ev) -> bool:
    """The keys the Sheets tab answers itself while it has the focus — and
    only then: the canvas keeps Ctrl+C / Ctrl+V / Ctrl+D / Delete for its
    own items everywhere else."""
    return _own_key(ev) is not None


def _panel_key(panel, ev) -> bool:
    """Run the Sheets tab's own key ``ev``; whether it was one."""
    what = _own_key(ev)
    if what in ("up", "down"):
        panel.move_current(-1 if what == "up" else 1)
    elif what == "delete":
        panel.delete_selected()
    elif what == "rename":
        panel.rename_current()
    elif what == "copy":
        panel.copy_selected()
    elif what == "paste":
        panel.paste()
    elif what == "duplicate":
        panel.duplicate_selected()
    else:
        return False
    return True


class _SheetTree(QTreeWidget):
    """The List view's tree: sheets and folders drag within it, scenes
    drop on it. Delete removes what is picked, F2 renames, Space flips
    Print, Alt+↑/↓ moves, Ctrl+C / Ctrl+V / Ctrl+D copy, paste and
    duplicate sheets."""

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
                and (_shortcut_keys(ev) or ev.key() == Qt.Key_Space)):
            ev.accept()                 # the composer's own keys wait
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:
        if self.state() != QAbstractItemView.EditingState and \
                not ev.isAutoRepeat():
            if ev.key() == Qt.Key_Space:
                self._panel.toggle_print_selected()
                return
            if _panel_key(self._panel, ev):
                return
        super().keyPressEvent(ev)


class _PageDelegate(QStyledItemDelegate):
    """A page of the Pages view: the sheet's picture — a grey sheet of its
    paper's shape until the picture lands — and under it its number and
    name, as a PDF reader shows its pages. The open sheet's page has an
    accent frame; F2 edits the name in place, under the page."""

    #: Room around the page in its cell, and between the page and its name.
    PAD, GAP = 8, 4

    def __init__(self, panel, view) -> None:
        super().__init__(view)
        self._panel = panel
        self._view = view

    def _label_h(self) -> int:
        return self._view.fontMetrics().height() + 2

    def page_rect(self, rect, sheet):
        """Where the page itself sits in the cell ``rect``."""
        from PySide6.QtCore import QRect
        box = self._panel.page_box(sheet)
        x = rect.x() + (rect.width() - box.width()) // 2
        return QRect(x, rect.y() + self.PAD, box.width(), box.height())

    def label_rect(self, rect, sheet):
        from PySide6.QtCore import QRect
        page = self.page_rect(rect, sheet)
        return QRect(rect.x() + 4, page.bottom() + 1 + self.GAP,
                     rect.width() - 8, self._label_h())

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        sheet = index.data(Qt.UserRole)
        box = self._panel.page_box(sheet)
        return QSize(self._panel.cell_width(),
                     box.height() + 2 * self.PAD + self.GAP + self._label_h())

    def paint(self, painter, option, index) -> None:
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPen
        from PySide6.QtWidgets import QStyle
        sheet = index.data(Qt.UserRole)
        rect = option.rect
        pal = option.palette
        accent = pal.highlight().color()
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        cell = QRectF(rect).adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.State_Selected)
        marked = id(sheet) in self._panel._marked
        if selected or marked or option.state & QStyle.State_MouseOver:
            tint = QColor(accent)
            tint.setAlpha(90 if selected else 60 if marked else 28)
            painter.setPen(Qt.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(cell, 5, 5)
        page = self.page_rect(rect, sheet)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 60))
        painter.drawRect(QRectF(page).translated(2, 2))
        pm = self._panel.page_pixmap(sheet)
        if pm is None:
            # Not painted yet: a grey sheet of its paper's shape.
            painter.setBrush(QColor(222, 225, 229))
            painter.drawRect(page)
        else:
            painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform,
                                  True)
            painter.drawPixmap(page, pm)
        is_open = sheet is getattr(self._panel._composer_win, "comp", None)
        if is_open:
            painter.setPen(QPen(accent, 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(page).adjusted(-2, -2, 2, 2))
        else:
            painter.setPen(QPen(QColor(150, 156, 162), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(page).adjusted(-0.5, -0.5, 0.5, 0.5))
        if index.row() == self._panel._drop_on_row:
            pen = QPen(accent, 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(QRectF(page).adjusted(-4, -4, 4, 4))
        # «3  Name» under the page — the open one in bold.
        font = QFont(option.font)
        font.setBold(is_open)
        painter.setFont(font)
        painter.setPen(pal.text().color())
        label = self.label_rect(rect, sheet)
        text = f"{index.row() + 1}   {sheet.name}"
        text = painter.fontMetrics().elidedText(text, Qt.ElideRight,
                                                label.width())
        painter.drawText(label, Qt.AlignHCenter | Qt.AlignVCenter, text)
        painter.restore()

    # ---- the name, edited in place under the page ----------------------------
    def createEditor(self, parent, option, index):  # noqa: N802
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignHCenter)
        return editor

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        editor.setText(index.data(Qt.UserRole).name)
        editor.selectAll()

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        editor.setGeometry(self.label_rect(option.rect,
                                           index.data(Qt.UserRole)))

    def setModelData(self, editor, model, index) -> None:  # noqa: N802
        self._panel.rename_page(index.data(Qt.UserRole), editor.text())


class _PageList(QListWidget):
    """The Pages view: one column of pages in the order of the set. A
    click opens a sheet; Ctrl/Shift pick several; they drag to another
    place (a line shows where they land); a scene dropped on a page is
    placed on that sheet. Its keys — Ctrl+C, Ctrl+V, Ctrl+D, Delete, F2,
    Alt+↑/↓ — act only while it has the focus."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        #: Where dragged pages would land: a place between two pages.
        self.gap = None
        self.setViewMode(QListWidget.ListMode)
        self.setFlow(QListWidget.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListWidget.Adjust)
        self.setUniformItemSizes(False)
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setMouseTracking(True)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)          # our own line, below
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def sheet_at(self, row: int):
        item = self.item(row)
        return item.data(Qt.UserRole) if item is not None else None

    # ---- what is on screen -----------------------------------------------------
    def on_screen(self) -> list:
        """The sheets whose pages show now, top to bottom."""
        view = self.viewport().rect()
        out = []
        for row in range(self.count()):
            item = self.item(row)
            if self.visualItemRect(item).intersects(view):
                out.append(item.data(Qt.UserRole))
        return out

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._panel._on_pages_resized()

    # ---- drag & drop ---------------------------------------------------------------
    def mimeTypes(self):
        from views.composer import SCENE_MIME
        return [PAGE_MIME, SCENE_MIME]

    def mimeData(self, items):
        picked = {id(it.data(Qt.UserRole)) for it in items}
        self._panel._dragging_pages = [
            c for c in self._panel._scene().compositions if id(c) in picked]
        data = QMimeData()
        data.setData(PAGE_MIME, b"1")
        return data

    def supportedDropActions(self):
        return Qt.MoveAction | Qt.CopyAction

    def gap_at(self, pos) -> int:
        """The place between two pages nearest ``pos``: in front of the
        page under it when in its upper half, after it otherwise."""
        item = self.itemAt(pos)
        if item is None:
            if not self.count():
                return 0
            first = self.visualItemRect(self.item(0))
            return 0 if pos.y() < first.top() else self.count()
        rect = self.visualItemRect(item)
        row = self.row(item)
        return row if pos.y() < rect.center().y() else row + 1

    def _accepts(self, ev) -> bool:
        return any(ev.mimeData().hasFormat(m) for m in self.mimeTypes())

    def dragEnterEvent(self, ev) -> None:  # noqa: N802
        if self._accepts(ev):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev) -> None:  # noqa: N802
        if not self._accepts(ev):
            ev.ignore()
            return
        super().dragMoveEvent(ev)       # Qt's autoscroll near the edges
        pos = ev.position().toPoint()
        if ev.mimeData().hasFormat(PAGE_MIME):
            self.gap, self._panel._drop_on_row = self.gap_at(pos), None
        else:
            item = self.itemAt(pos)
            self.gap = None
            self._panel._drop_on_row = (self.row(item) if item is not None
                                        else None)
        ev.acceptProposedAction()
        self.viewport().update()

    def dragLeaveEvent(self, ev) -> None:  # noqa: N802
        super().dragLeaveEvent(ev)
        self.gap, self._panel._drop_on_row = None, None
        self.viewport().update()

    def dropEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position().toPoint()
        mime = ev.mimeData()
        gap = self.gap_at(pos)
        item = self.itemAt(pos)
        self.gap, self._panel._drop_on_row = None, None
        ev.setDropAction(Qt.IgnoreAction)          # the model moves, not Qt
        ev.accept()
        self.viewport().update()
        self._panel.drop_on_pages(mime, gap,
                                  item.data(Qt.UserRole) if item else None)

    def gap_y(self, gap: int):
        """The height of the line drawn at place ``gap``."""
        if not self.count():
            return None
        if gap < self.count():
            return self.visualItemRect(self.item(gap)).top() - 1
        return self.visualItemRect(self.item(self.count() - 1)).bottom() + 2

    def paintEvent(self, ev) -> None:  # noqa: N802
        super().paintEvent(ev)
        if self.gap is None:
            return
        y = self.gap_y(self.gap)
        if y is None:
            return
        from PySide6.QtGui import QPainter, QPen
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, True)
        accent = self.palette().highlight().color()
        painter.setPen(QPen(accent, 3, Qt.SolidLine, Qt.RoundCap))
        w = self.viewport().width()
        painter.drawLine(10, y, w - 10, y)
        painter.setBrush(accent)
        painter.drawEllipse(4, y - 4, 8, 8)
        painter.drawEllipse(w - 12, y - 4, 8, 8)
        painter.end()

    # ---- keys -------------------------------------------------------------------
    def event(self, ev) -> bool:
        from PySide6.QtCore import QEvent
        if (ev.type() == QEvent.ShortcutOverride
                and self.state() != QAbstractItemView.EditingState
                and (_shortcut_keys(ev)
                     or ev.key() in (Qt.Key_Return, Qt.Key_Enter))):
            ev.accept()                 # the composer's own keys wait
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if self.state() != QAbstractItemView.EditingState and \
                not ev.isAutoRepeat():
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
                sheet = self._panel.current_sheet()
                if sheet is not None:
                    self._panel.open_sheet(sheet)
                return
            if _panel_key(self._panel, ev):
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
    """The document's sheets, as pages or as a list.

    **Pages** (the default; Marco, 20-11: «parecido a las vistas de
    miniatura de ciertos programas conocidos de pdf, de allí podría mover
    el orden, copiar, pegar, eliminar»): one column of pages in the order
    of the set, each its sheet's picture with its number and name; the
    open one marked. Click opens a sheet; drag reorders; Ctrl+C / Ctrl+V
    copy and paste sheets, Ctrl+D duplicates, Delete deletes, F2 renames —
    each one step of the composer's undo.

    **List**: the sheets in their nested folders (:mod:`core.sheet_folders`)
    with their Print flag — what Print all and Export all take — a filter,
    folders to add, rename and delete, sheets and folders dragged to
    reorder or re-file them.

    Neither shows the scenes placed on each sheet: they are in the Scenes
    tab, and here they only cluttered the sheets (Marco, 20-11: «solo
    aparezcan las hojas limpias … si ya está en Escenas no debería estar
    en Láminas»). A scene dragged onto a sheet is still placed on it.

    ``composer`` is the sheet composer it lives in: the sheet open there is
    marked, and the sheets change through its undo."""

    #: The sheets copied with Ctrl+C (each one's ``to_dict()``): pasted as
    #: new sheets with Ctrl+V — in this document or another one.
    clipboard: list = []

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        self._window = window
        self._composer_win = composer
        self._updating = False
        self._shape = None
        self._query = ""
        self._dragging = ([], [])
        self._dragging_pages: list = []
        self._related: list = []
        #: Sheets marked as showing the scene current in the Scenes tab.
        self._marked: set = set()
        self._drop_on_row = None
        self._pages_shape = None
        self.items: dict = {}
        #: The page of each sheet (Pages view), by ``id(sheet)``.
        self.page_items: dict = {}
        #: The page pictures (only in the composer, which paints them).
        self.pictures = None
        if composer is not None:
            from views.sheet_pages import SheetPictures
            self.pictures = SheetPictures(
                composer, self._on_picture, self._pages_shown, parent=self,
                box=self.picture_box, first=self._pages_on_screen)
        #: Pages (``True``) or List — only the composer has pages.
        self.thumbnails = (self.pictures is not None
                           and self._saved_thumbnails())
        #: The Pages-or-List button (only in the composer); the page puts
        #: it in the «Sheets» heading, as it does the scenes' one.
        self.view_btn = (self._view_button() if self.pictures is not None
                         else None)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        # The filter field (List only) and, beside it, the actions as small
        # icons — the Browser's bar.
        from views.outliner import _tool_button
        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter sheets and folders…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_filter)
        bar.addWidget(self.search, 1)
        self._bar_stretch = QWidget()
        bar.addWidget(self._bar_stretch, 1)
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
        # The sheet set Print all and Export all take (#1519): shown only
        # once the document has sets — a document without stays as it was.
        # A set prints in this tree's order; the sheets outside it grey.
        self._set_id = None
        self.set_row = QWidget()
        set_lay = QHBoxLayout(self.set_row)
        set_lay.setContentsMargins(0, 0, 0, 0)
        set_lay.setSpacing(6)
        set_label = QLabel(tr("Set:"))
        set_lay.addWidget(set_label)
        self.set_combo = QComboBox()
        self.set_combo.setToolTip(tr(
            "Which sheets Print all and Export all take: all the sheets "
            "marked for printing, or one plan set — its marked sheets, in "
            "this order, their pages numbered within the set. Plan sets "
            "are made in a sheet's properties."))
        set_label.setBuddy(self.set_combo)
        self.set_combo.currentIndexChanged.connect(self._on_set_picked)
        set_lay.addWidget(self.set_combo, 1)
        self.set_row.setVisible(False)
        lay.addWidget(self.set_row)

        from PySide6.QtWidgets import QStackedWidget
        self.stack = QStackedWidget()
        self.pages = _PageList(self)
        self.pages.setItemDelegate(_PageDelegate(self, self.pages))
        self.pages.setToolTip(tr(
            "Click a page to open its sheet; drag pages to order them. "
            "Ctrl+C and Ctrl+V copy and paste sheets, Ctrl+D duplicates, "
            "Delete deletes, F2 renames. Right-click for more."))
        self.pages.itemClicked.connect(self._on_page_clicked)
        self.pages.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pages.customContextMenuRequested.connect(self._on_page_menu)
        self.pages.verticalScrollBar().valueChanged.connect(
            lambda *_a: self.pictures.kick() if self.pictures else None)
        self.stack.addWidget(self.pages)

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
        self.stack.addWidget(self.tree)
        lay.addWidget(self.stack, 1)
        # The composer edits sheets without telling the model: while this
        # panel is on screen it checks, once a second, whether what it
        # lists changed (a fingerprint of a few fields — nothing to do
        # when nothing did).
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._poll_tick)
        self._show_view_mode()
        self.refresh()

    # ---- Pages or List ------------------------------------------------------------
    #: Where the choice is kept; Pages to start with — what Marco asked for.
    THUMBS_KEY = "composer/sheet_thumbnails"

    @classmethod
    def _saved_thumbnails(cls) -> bool:
        from PySide6.QtCore import QSettings
        raw = QSettings().value(cls.THUMBS_KEY, True)
        return raw not in (False, "false", "0", 0)

    def _view_button(self):
        """The Pages-or-List button, as the scenes list's."""
        from PySide6.QtGui import QActionGroup
        from PySide6.QtWidgets import QMenu, QToolButton
        from views.icons import tool_icon
        btn = QToolButton()
        btn.setAutoRaise(True)
        btn.setPopupMode(QToolButton.InstantPopup)
        btn.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        btn.setToolTip(tr(
            "Show the sheets as pages, or as a list with their folders and "
            "what Print all takes"))
        menu = QMenu(btn)
        group = QActionGroup(self)
        self.thumbs_action = menu.addAction(tool_icon("scenes_thumbs"),
                                            tr("Pages"))
        self.list_action = menu.addAction(tool_icon("scenes_list"), tr("List"))
        for act in (self.list_action, self.thumbs_action):
            act.setCheckable(True)
            group.addAction(act)
        self.list_action.triggered.connect(
            lambda: self.set_thumbnails(False))
        self.thumbs_action.triggered.connect(
            lambda: self.set_thumbnails(True))
        btn.setMenu(menu)
        return btn

    def set_thumbnails(self, on: bool) -> None:
        """The Pages view (``True``) or the List, and remember the choice."""
        from PySide6.QtCore import QSettings
        if self.pictures is None:
            return
        self.thumbnails = bool(on)
        QSettings().setValue(self.THUMBS_KEY, self.thumbnails)
        self._show_view_mode()
        self.refresh(force=True)
        if self.thumbnails:
            self.pictures.kick()

    def _show_view_mode(self) -> None:
        pages = self.thumbnails
        if self.view_btn is not None:
            from views.icons import tool_icon
            self.thumbs_action.setChecked(pages)
            self.list_action.setChecked(not pages)
            self.view_btn.setIcon(tool_icon(
                "scenes_thumbs" if pages else "scenes_list"))
        self.stack.setCurrentWidget(self.pages if pages else self.tree)
        # The filter and the folders are the List's; the pages are all
        # there is to see.
        self.search.setVisible(not pages)
        self._bar_stretch.setVisible(pages)
        self.add_folder_btn.setVisible(not pages)
        self.add_sheet_btn.setToolTip(
            tr("New sheet, after the selected one") if pages
            else tr("New sheet, in the selected folder"))
        self.delete_btn.setToolTip(
            tr("Delete the selected sheets (Delete)") if pages else tr(
                "Delete the selected sheets and folders (Delete) — a "
                "deleted folder moves what it holds one level up"))

    # ---- The pages' size and pictures ------------------------------------------------
    #: The widest a page gets, in logical pixels, however wide the panel.
    PAGE_MAX_PX = 420

    def cell_width(self) -> int:
        return max(40, self.pages.viewport().width()
                   - 2 * self.pages.spacing())

    def _page_width(self) -> int:
        return max(48, min(self.PAGE_MAX_PX,
                           self.cell_width() - 2 * _PageDelegate.PAD - 4))

    @staticmethod
    def _fit(sheet, width: int) -> QSize:
        """A page ``width`` wide (a portrait one no taller than 1.42 times
        that), in proportion to its paper."""
        pw, ph = sheet.page_size_mm()
        if pw <= 0 or ph <= 0:
            return QSize(width, width)
        w, h = width, width * ph / pw
        if h > 1.42 * width:
            w, h = 1.42 * width * pw / ph, 1.42 * width
        return QSize(max(1, round(w)), max(1, round(h)))

    def page_box(self, sheet) -> QSize:
        """The page's size on screen now — it follows the panel's width."""
        return self._fit(sheet, self._page_width())

    #: The pictures are painted at widths in steps of this: a panel dragged
    #: wider by a few pixels scales the ones it has instead.
    PICTURE_STEP_PX = 48

    def picture_box(self, sheet) -> QSize:
        step = self.PICTURE_STEP_PX
        width = -(-self._page_width() // step) * step
        return self._fit(sheet, min(width, self.PAGE_MAX_PX))

    def page_pixmap(self, sheet):
        return (self.pictures.pixmap_for(id(sheet))
                if self.pictures is not None else None)

    def _pages_shown(self) -> bool:
        return (self.thumbnails and self.isVisible()
                and self.pages.isVisible())

    def _pages_on_screen(self) -> list:
        return self.pages.on_screen() if self._pages_shown() else []

    def _on_pages_resized(self) -> None:
        self.pages.doItemsLayout()
        if self.pictures is not None and self.thumbnails:
            self.pictures.wanted(list(self._scene().compositions))

    def touch_picture(self, sheet=None) -> None:
        """``sheet`` changed (``None``: all of them): its page is painted
        again shortly — the composer calls this on every canvas change."""
        if self.pictures is not None:
            self.pictures.touch(sheet)

    def _on_picture(self, key) -> None:
        item = self.page_items.get(key)
        if item is not None:
            self.pages.viewport().update(self.pages.visualItemRect(item))

    # ---- Model → view ----------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _fingerprint(self, scene) -> tuple:
        current = getattr(self._composer_win, "comp", None)
        return (
            tuple((f.id, f.name, f.parent_id, f.expanded, f.print_in_all,
                   f.pos) for f in sf.folders_of(scene)),
            tuple((id(c), c.name, c.folder_id, c.print_in_all,
                   c.page_size_mm(),
                   tuple((id(f), f.view_key) for f in c.frames))
                  for c in scene.compositions),
            tuple(v.name for v in getattr(scene, "saved_views", None) or ()),
            tuple((st.id, st.name, tuple(st.sheet_uids), st.ordered,
                   st.cover_uid) for st in ss.sets_of(scene)),
            tuple(c.uid for c in scene.compositions),
            self._set_id, id(current))

    def on_scene_changed(self) -> None:
        if self.isVisible():
            self.refresh()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self.refresh()
        self._poll.start()
        if self.pictures is not None and self.thumbnails:
            self.pictures.kick()

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

    @staticmethod
    def _lost_scenes(scene, sheet) -> list:
        """The scenes the frames of ``sheet`` show that the model lost."""
        from core import outliner
        return [outliner.frame_scene(f) for f in sheet.frames
                if outliner.is_orphan(scene, f)]

    def _sheet_tip(self, scene, sheet) -> str:
        tip = tr("{name} — double-click to open it", name=sheet.name)
        lost = self._lost_scenes(scene, sheet)
        if lost:
            tip += "\n" + tr(
                "A view on this sheet shows the scene «{name}», which the "
                "model no longer has: pick another view for it in the "
                "composer.", name=lost[0])
        return tip

    def refresh(self, force: bool = False) -> None:
        scene = self._scene()
        shape = self._fingerprint(scene)
        if shape == self._shape and not force:
            return
        self._shape = shape
        self._refresh_tree(scene)
        self._refresh_pages(scene)

    def _refresh_tree(self, scene) -> None:
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
                # A sheet is a row of its own, nothing under it: the scenes
                # it shows are the Scenes tab's (Marco, 20-11).
                c = entry
                item = QTreeWidgetItem([c.name, ""])
                item.setData(COL_NAME, Qt.UserRole, (_SHEET, c))
                item.setIcon(COL_NAME, _icon(
                    "warning" if self._lost_scenes(scene, c) else "sheet"))
                self._set_print_cell(scene, item, c)
                item.setFlags(item.flags() | Qt.ItemIsEditable
                              | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
                item.setToolTip(COL_NAME, self._sheet_tip(scene, c))
                if c is open_sheet:
                    item.setFont(COL_NAME, bold)
                parent_item.addChild(item)
                self.items[id(c)] = item

        add(self.tree.invisibleRootItem(), None, frozenset())
        self._show_set(scene)
        for key, item in self.items.items():
            if key in picked:
                item.setSelected(True)
            if key == current_key:
                self.tree.setCurrentItem(item, COL_NAME,
                                         QItemSelectionModel.NoUpdate)
        self._updating = False
        self._apply_filter()
        self._apply_marks()

    def _refresh_pages(self, scene) -> None:
        """The pages: built again only when the set of sheets or their
        order changed; otherwise only the names and the marks repaint."""
        comps = list(scene.compositions)
        shape = tuple(id(c) for c in comps)
        self._updating = True
        try:
            if shape != self._pages_shape:
                self._pages_shape = shape
                picked = {id(c) for c in self._selected_pages()}
                cur = self.pages.currentItem()
                cur_key = id(cur.data(Qt.UserRole)) if cur else None
                self.pages.clear()
                self.page_items = {}
                for c in comps:
                    item = QListWidgetItem(c.name)
                    item.setData(Qt.UserRole, c)
                    item.setFlags(item.flags() | Qt.ItemIsEditable
                                  | Qt.ItemIsDragEnabled)
                    self.pages.addItem(item)
                    self.page_items[id(c)] = item
                for key in picked:
                    if key in self.page_items:
                        self.page_items[key].setSelected(True)
                if cur_key in self.page_items:
                    self.pages.setCurrentItem(
                        self.page_items[cur_key],
                        QItemSelectionModel.NoUpdate)
            for c in comps:
                item = self.page_items.get(id(c))
                if item is not None:
                    if item.text() != c.name:
                        item.setText(c.name)
                    item.setToolTip(self._sheet_tip(scene, c))
        finally:
            self._updating = False
        self.pages.viewport().update()
        if self.pictures is not None and self.thumbnails:
            self.pictures.wanted(comps)

    # ---- The sheet set Print all and Export all take (#1519) -----------------
    def current_set_id(self):
        """The id of the set the Set box shows; ``None``: All sheets."""
        return self._set_id

    def _on_set_picked(self, _index: int) -> None:
        if self._updating:
            return
        self._set_id = self.set_combo.currentData()
        self.refresh(force=True)

    def _show_set(self, scene) -> None:
        """The Set box follows the document's sets; the sheets outside the
        chosen set grey, and the print and export buttons say what they
        take."""
        from views.sheet_sets_ui import fill_set_combo
        if self._set_id is not None and ss.set_by_id(scene, self._set_id) \
                is None:
            self._set_id = None                   # the set was deleted
        fill_set_combo(self.set_combo, scene, self._set_id)
        self.set_row.setVisible(bool(ss.sets_of(scene)))
        # The open sheet's «Plan sets» box follows too (an undo, the AI).
        box = getattr(self._composer_win, "plan_sets", None)
        if box is not None:
            box.refresh()
        st = ss.set_by_id(scene, self._set_id) \
            if self._set_id is not None else None
        if st is None:
            self.print_btn.setToolTip(tr(
                "Print all: the sheets marked for printing, each on its "
                "own paper"))
            self.export_btn.setToolTip(tr(
                "Export all: the sheets marked for printing — one PDF, or "
                "PNG / SVG files"))
            return
        inside = {id(c) for c in ss.members(scene, st)}
        n = len(ss.export_list(scene, st))
        self.print_btn.setToolTip(tr(
            "Print the plan set «{name}»: {n} sheets", name=st.name, n=n))
        self.export_btn.setToolTip(tr(
            "Export the plan set «{name}»: {n} sheets", name=st.name, n=n))
        from PySide6.QtGui import QBrush
        grey = QBrush(self.palette().color(QPalette.Disabled,
                                           QPalette.Text))
        for c in scene.compositions:
            item = self.items.get(id(c))
            if item is not None and id(c) not in inside:
                item.setForeground(COL_NAME, grey)
                item.setToolTip(COL_NAME, tr(
                    "{name} — not in the plan set «{set}»", name=c.name,
                    set=st.name))

    @staticmethod
    def _key(item):
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return id(d[1]) if d else None

    # ---- Filter (List) ------------------------------------------------------------
    def _on_filter(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Hide the rows the filter leaves out: a row stays when its name
        matches, when something inside it does (its folders open to show
        it), or when a folder around it does (all of it shows)."""
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

    # ---- A scene and the sheets that show it ------------------------------------
    def mark_scene(self, name) -> list:
        """Mark the sheets showing the scene called ``name`` (``None``:
        none) — their rows in the List, their pages. Returns the marked
        rows."""
        from core import outliner
        self._marked = set()
        if name is not None:
            for c in self._scene().compositions:
                if any(outliner.frame_scene(f) == name for f in c.frames):
                    self._marked.add(id(c))
        self._apply_marks()
        self.pages.viewport().update()
        return list(self._related)

    def _apply_marks(self) -> None:
        # A mark is an item change to Qt, not an edit of the row.
        self._updating = True
        try:
            for row in self._related:
                mark_row(row, False)
            self._related = []
            for key in self._marked:
                item = self.items.get(key)
                if item is not None:
                    mark_row(item, True)
                    self._related.append(item)
        finally:
            self._updating = False

    def related(self) -> list:
        return list(self._related)

    # ---- Reading the selection ---------------------------------------------------
    @staticmethod
    def _items_of(rows) -> tuple[list, list]:
        """``(sheets, folders)`` among ``rows``."""
        sheets, folders = [], []
        for item in rows:
            d = item.data(COL_NAME, Qt.UserRole)
            if not d:
                continue
            if d[0] == _FOLDER:
                folders.append(d[1])
            elif not holds(sheets, d[1]):
                sheets.append(d[1])
        return sheets, folders

    def _selected_pages(self) -> list:
        """The sheets of the selected pages, in the order of the set."""
        picked = {id(it.data(Qt.UserRole))
                  for it in self.pages.selectedItems()}
        return [c for c in self._scene().compositions if id(c) in picked]

    def _picked(self) -> tuple[list, list]:
        if self.thumbnails:
            return self._selected_pages(), []
        return self._items_of(self.tree.selectedItems())

    def selected_sheets(self) -> list:
        """The selected sheets, in the order of the set."""
        sheets = self._picked()[0]
        return [c for c in self._scene().compositions if holds(sheets, c)]

    def _target_folder_id(self):
        """Where a new sheet or folder goes: into the selected folder, or
        beside the selected sheet; the top when nothing is selected."""
        item = self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if not d or not item.isSelected():
            return None
        return d[1].id if d[0] == _FOLDER else d[1].folder_id

    def current_sheet(self):
        if self.thumbnails:
            item = self.pages.currentItem()
            return item.data(Qt.UserRole) if item is not None else None
        item = self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return d[1] if d and d[0] == _SHEET else None

    def select_sheets(self, sheets, current=None) -> None:
        """Select ``sheets`` (their pages or rows), ``current`` (or the
        first) the current one."""
        keys = {id(c) for c in sheets}
        current = current if current is not None else (
            sheets[0] if sheets else None)
        if self.thumbnails:
            self.pages.clearSelection()
            for key in keys:
                item = self.page_items.get(key)
                if item is not None:
                    item.setSelected(True)
            item = self.page_items.get(id(current))
            if item is not None:
                self.pages.setCurrentItem(item, QItemSelectionModel.NoUpdate)
                self.pages.scrollToItem(item)
        else:
            self.tree.clearSelection()
            for key in keys:
                item = self.items.get(key)
                if item is not None:
                    item.setSelected(True)
            item = self.items.get(id(current))
            if item is not None:
                self.tree.setCurrentItem(item, COL_NAME,
                                         QItemSelectionModel.NoUpdate)

    # ---- View → model --------------------------------------------------------------
    def _history(self):
        return self._window.viewport.history

    def _composer(self):
        return self._composer_win or self._window._ensure_composer()

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
        if not holds(comps, sheet):
            return
        index = index_of(comps, sheet)
        if self._composer_win is not None:
            self._composer_win.show_sheet(index)
        else:
            self._window._show_sheet(index)
        self.refresh(force=True)

    def activate(self, item) -> None:
        """A sheet opens in the composer (a folder only opens or closes,
        as Qt does by itself)."""
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if d and d[0] == _SHEET:
            self.open_sheet(d[1])

    def _on_page_clicked(self, item) -> None:
        """A plain click opens the page's sheet; with Ctrl or Shift it only
        picks pages."""
        from PySide6.QtWidgets import QApplication
        if QApplication.keyboardModifiers() & (Qt.ControlModifier
                                               | Qt.ShiftModifier):
            return
        sheet = item.data(Qt.UserRole) if item is not None else None
        if sheet is not None and sheet is not getattr(
                self._composer_win, "comp", None):
            self.open_sheet(sheet)

    def _on_double_clicked(self, item, column) -> None:
        if column == COL_PRINT:
            return                  # the printer: a click already flipped it
        self.activate(item)

    def _on_item_clicked(self, item, column) -> None:
        if column != COL_PRINT or self._updating:
            return
        d = item.data(COL_NAME, Qt.UserRole)
        if not d:
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
        if not holds(sheets, obj) and not holds(folders, obj):
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
        """A new sheet — as the «+» tab makes it — opened in the composer:
        in the Pages view right after the selected page (one undo step),
        in the List in the selected folder (or ``folder_id``)."""
        if self.thumbnails and folder_id is ...:
            new = self._composer().new_sheet_after(self.current_sheet())
            self._after_tree_change()
            if new is not None:
                self.select_sheets([new])
            return
        scene = self._scene()
        if folder_id is ...:
            folder_id = self._target_folder_id()
        before = list(scene.compositions)
        self._window._show_new_sheet()
        new = [c for c in scene.compositions if not holds(before, c)]
        if new and folder_id is not None:
            for c in new:
                c.folder_id = folder_id
            sf.sync_order(scene)
            composer = getattr(self._window, "_composer", None)
            if composer is not None:
                composer.show_sheet(index_of(scene.compositions, new[-1]))
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
        """Type a new name for the sheet (or folder) — in place, under its
        page or in its row."""
        if self.thumbnails and item is None:
            page = self.pages.currentItem()
            if page is not None:
                self.pages.editItem(page)
            return
        item = item if item is not None else self.tree.currentItem()
        if isinstance(item, QListWidgetItem):
            self.pages.editItem(item)
            return
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if d and d[0] in (_FOLDER, _SHEET):
            self.tree.editItem(item, COL_NAME)

    def rename_page(self, sheet, name: str) -> None:
        """A name typed under a page: the sheet's new name — one undo step
        — on the next turn (the editor is still closing)."""
        name = (name or "").strip()
        if not name or name == sheet.name:
            return

        def later():
            comps = self._scene().compositions
            if holds(comps, sheet):
                self._composer().rename_sheet(index_of(comps, sheet), name)
                self._after_tree_change()
        QTimer.singleShot(0, self, later)

    def duplicate_sheet(self, sheet) -> None:
        self.duplicate_sheets([sheet])

    def duplicate_sheets(self, sheets) -> list:
        """A copy of each sheet right after it — one undo step; the copies
        are selected."""
        made = self._composer().duplicate_sheets(sheets) if sheets else []
        self._after_tree_change()
        if made:
            self.select_sheets(made)
        return made

    def duplicate_selected(self) -> None:
        self.duplicate_sheets(self.selected_sheets())

    def copy_selected(self) -> int:
        """Ctrl+C: the selected sheets to the sheets' clipboard. How many."""
        sheets = self.selected_sheets()
        if not sheets:
            return 0
        SheetExplorer.clipboard = [c.to_dict() for c in sheets]
        self._window.viewport.flash_status(
            tr("Sheets copied: {n}", n=len(sheets)), 2500)
        return len(sheets)

    def paste(self) -> list:
        """Ctrl+V: copies of the copied sheets right after the current one
        (the open one when none is) — one undo step; they are selected."""
        if not SheetExplorer.clipboard:
            return []
        made = self._composer().paste_sheets(
            list(SheetExplorer.clipboard), after=self.current_sheet())
        self._after_tree_change()
        if made:
            self.select_sheets(made)
        return made

    def delete_selected(self) -> None:
        """Delete what is selected: the folders — what they hold moves one
        level up — in one undo step, and the sheets through the composer,
        which asks first, keeps at least one, and makes it one step of its
        own undo."""
        sheets, folders = self._picked()
        self.delete(sheets, folders)

    def delete(self, sheets, folders) -> None:
        from core.history import DeleteSheetFoldersCommand
        if folders:
            self._history().execute(DeleteSheetFoldersCommand(folders))
        if sheets:
            self._composer().delete_sheets(sheets, self)
        if folders or sheets:
            self._after_tree_change()

    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != COL_NAME:
            return
        d = item.data(COL_NAME, Qt.UserRole)
        if not d:
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
            self._after_edit_in_tree()
        else:
            self.rename_page(obj, name)

    def _set_expanded(self, item, on: bool) -> None:
        """A folder's open or closed is kept with the document (it opens
        the way it was left) — not an edit to undo, so straight onto the
        folder."""
        if self._updating:
            return
        d = item.data(COL_NAME, Qt.UserRole)
        if d and d[0] == _FOLDER:
            d[1].expanded = on
            self._shape = self._fingerprint(self._scene())

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

    def move_pages(self, sheets, gap: int) -> bool:
        """Pages (sheets) to place ``gap`` between two pages — one step of
        the composer's undo; they stay selected."""
        moved = self._composer().move_sheets(sheets, gap)
        self._after_tree_change()
        if moved:
            self.select_sheets(sheets, self.current_sheet()
                               if holds(sheets, self.current_sheet()) else None)
        return moved

    def drop_on_pages(self, mime, gap: int, sheet) -> None:
        """What a drop on the pages does: pages move to ``gap``; scenes are
        placed on ``sheet`` — a new sheet when dropped on no page."""
        from views.composer import SCENE_MIME
        if mime.hasFormat(SCENE_MIME):
            names = [n for n in bytes(mime.data(SCENE_MIME)).decode(
                "utf-8").split("\n") if n]
            views = {v.name: v for v in self._scene().saved_views}
            for name in names:
                if name in views:
                    self.place_scene(views[name], sheet)
            QTimer.singleShot(0, self, self._after_tree_change)
            return
        if not mime.hasFormat(PAGE_MIME):
            return
        sheets, self._dragging_pages = self._dragging_pages, []
        if sheets:
            # On the next turn: Qt still holds the drag's pages.
            QTimer.singleShot(0, self, lambda: self.move_pages(sheets, gap))

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
            sheet = d[1] if d and d[0] == _SHEET else None
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
        """Alt+↑/↓: the selected pages one place up or down (Pages); the
        current sheet (or folder) one place among its neighbours in the
        same folder (List)."""
        if self.thumbnails:
            sheets = self.selected_sheets() or [
                c for c in (self.current_sheet(),) if c is not None]
            if not sheets:
                return
            comps = self._scene().compositions
            rows = [index_of(comps, c) for c in sheets]
            gap = min(rows) - 1 if step < 0 else max(rows) + 2
            if 0 <= gap <= len(comps):
                self.move_pages(sheets, gap)
            return
        item = self.tree.currentItem()
        d = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        if not d:
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
            if comp_win.comp is not sheet and holds(comps, sheet):
                comp_win.show_sheet(index_of(comps, sheet))
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
    def _add_copy_actions(self, menu, sheets) -> None:
        """Duplicate, Copy and Paste — the keys' actions, for ``sheets``."""
        menu.addAction(tr("Duplicate (Ctrl+D)"),
                       lambda: self.duplicate_sheets(sheets))
        menu.addAction(tr("Copy (Ctrl+C)"),
                       lambda: (self.select_sheets(sheets),
                                self.copy_selected()))
        paste = menu.addAction(tr("Paste (Ctrl+V)"), self.paste)
        paste.setEnabled(bool(SheetExplorer.clipboard))

    def _on_page_menu(self, pos) -> None:
        item = self.pages.itemAt(pos)
        if item is not None and not item.isSelected():
            self.pages.setCurrentItem(item)
        menu = self.build_page_menu(item.data(Qt.UserRole)
                                    if item is not None else None)
        menu.exec(self.pages.viewport().mapToGlobal(pos))

    def build_page_menu(self, sheet):
        """The right-click menu of a page (``None``: the space below the
        pages): what its keys do, and printing."""
        from core import outliner
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        scene = self._scene()
        if sheet is not None:
            sheets = self.selected_sheets()
            if not holds(sheets, sheet):
                sheets = [sheet]
            menu.addAction(_icon("sheet"), tr("Open sheet"),
                           lambda: self.open_sheet(sheet))
            menu.addAction(_icon("rename"), tr("Rename… (F2)"),
                           lambda: self.pages.editItem(
                               self.page_items.get(id(sheet))))
            self._add_copy_actions(menu, sheets)
            menu.addAction(_icon("delete"), tr("Delete"),
                           lambda: self.delete(sheets, []))
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
                           lambda: (self.select_sheets(sheets),
                                    self.move_current(-1)))
            menu.addAction(tr("Move down (Alt+↓)"),
                           lambda: (self.select_sheets(sheets),
                                    self.move_current(1)))
            menu.addSeparator()
        else:
            paste = menu.addAction(tr("Paste (Ctrl+V)"), self.paste)
            paste.setEnabled(bool(SheetExplorer.clipboard))
        menu.addAction(_icon("sheet_add"), tr("New sheet"),
                       lambda: self.add_sheet())
        if sheet is None:
            menu.addSeparator()
            menu.addAction(_icon("print"), tr("Print all…"),
                           lambda: self.print_all())
            menu.addAction(_icon("pdf"), tr("Export all (PDF)…"),
                           lambda: self.export_all())
        return menu

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
        if d and d[0] == _SHEET:
            sheet = d[1]
            if not holds(sheets, sheet):
                sheets, folders = [sheet], []
            menu.addAction(_icon("sheet"), tr("Open sheet"),
                           lambda: self.open_sheet(sheet))
            menu.addAction(_icon("rename"), tr("Rename… (F2)"),
                           lambda: self.rename_current(
                               self.items.get(id(sheet))))
            self._add_copy_actions(menu, sheets)
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
        order = [c for c in self._scene().compositions if holds(sheets, c)]
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
        """Print the sheets marked for printing — or those of the set the
        Set box shows, numbered within it — in the order shown."""
        sheets = ss.export_list(self._scene(), self._set_id)
        if not sheets:
            self._window.viewport.flash_status(
                tr("No sheet is marked for printing"), 4000)
            return
        if self._set_id is not None:
            self._window._ensure_composer().print_sheets(
                sheets, self, sheet_set=self._set_id)
            return
        self.print_sheets(sheets)

    def export_all(self, path=None) -> None:
        """The sheets marked for printing — or the set the Set box shows —
        in the order shown: one PDF, or PNG / SVG files (the file type
        picked)."""
        composer = self._window._ensure_composer()
        status = self._window.viewport.flash_status
        if path is None:
            from views.sheet_sets_ui import export_sheets_interactive
            export_sheets_interactive(composer, self, self._set_id,
                                      status=status)
            return
        sheets = ss.export_list(self._scene(), self._set_id)
        if not sheets:
            status(tr("No sheet is marked for printing"), 4000)
            return
        if self._set_id is None:
            self.export_sheets(sheets, path)
            return
        from pathlib import Path
        fmt = Path(path).suffix.lower().lstrip(".") or "pdf"
        composer.export_sheets(str(path), None, fmt,
                               sheet_set=self._set_id)


def mark_row(item, on: bool, column: int = 0) -> None:
    """A row marked as related to the current one elsewhere — a scene and
    the views that show it: a soft accent behind it, and ``UserRole + 1``
    set. Works on list and tree rows alike."""
    from PySide6.QtGui import QBrush, QColor
    from PySide6.QtWidgets import QApplication
    brush = QBrush()
    if on:
        tint = QColor(QApplication.palette().highlight().color())
        tint.setAlpha(60)
        brush = QBrush(tint)
    if isinstance(item, QTreeWidgetItem):
        item.setBackground(column, brush)
        item.setData(column, Qt.UserRole + 1, bool(on))
    else:
        item.setBackground(brush)
        item.setData(Qt.UserRole + 1, bool(on))


class _SceneTree(QTreeWidget):
    """The scenes in their folders; scene rows drag out by name — what a
    sheet in the explorer and the composer's page take. Folders only hold
    them: they do not drag."""

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

    def mimeTypes(self):
        from views.composer import SCENE_MIME
        return [SCENE_MIME]

    def mimeData(self, items):
        from views.composer import SCENE_MIME
        names = [it.text(0) for it in items
                 if (it.data(0, Qt.UserRole) or ("",))[0] == "scene"]
        data = QMimeData()
        data.setData(SCENE_MIME, "\n".join(names).encode("utf-8"))
        return data


class SceneList(QWidget):
    """The scenes above the sheets, filed in the folders of the main
    window's Scenes tab (:mod:`core.scene_folders`) — but only to pick them
    up from: no hint, no buttons, no renaming, deleting or re-filing. Scenes
    and folders are made and changed in the Scenes tab
    (:class:`views.tray.ScenesPanel`); here the scenes only drag onto
    sheets, and the tree scrolls in the space it is given. A folder folded
    here stays folded while the window is open.

    ``on_activate(view)`` is what a double-click on a scene does (the
    composer places the scene on the open sheet; without it the scene is
    shown, as the Scenes tab would). ``icon_for(name)`` gives each scene a
    picture, drawn one at a time while the list is on screen."""

    def __init__(self, window, on_activate=None, icon_for=None) -> None:
        super().__init__()
        self._window = window
        self._activate_hook = on_activate
        self._icon_for = icon_for
        self._icon_queue: list = []
        self._shape = None
        self._collapsed: set = set()
        #: Each scene with its picture (only with ``icon_for``), or a list.
        self.thumbnails = icon_for is not None and self._saved_thumbnails()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 8)
        #: The list-or-thumbnails button (only with ``icon_for``) — not laid
        #: out here: the page puts it in the heading above the list, where
        #: it takes no line of its own.
        self.view_btn = self._view_button() if icon_for is not None else None
        self.tree = _SceneTree()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(self._on_activate)
        self.tree.itemCollapsed.connect(lambda it: self._on_folded(it, False))
        self.tree.itemExpanded.connect(lambda it: self._on_folded(it, True))
        lay.addWidget(self.tree, 1)
        self.tree.setToolTip(tr(
            "Drag a scene onto a sheet. Double-click places it on the "
            "open sheet.") if on_activate is not None else tr(
            "Drag a scene onto a sheet. Double-click shows it."))
        self._show_view_mode()
        self.refresh()

    def _scene(self):
        return self._window.viewport.scene

    # ---- The list or the thumbnails --------------------------------------------------
    #: Where the choice is kept — the composer's own, apart from the
    #: Scenes tab's (``scenes/thumbnails``).
    THUMBS_KEY = "composer/scene_thumbnails"

    @classmethod
    def _saved_thumbnails(cls) -> bool:
        from PySide6.QtCore import QSettings
        raw = QSettings().value(cls.THUMBS_KEY, True)
        return raw not in (False, "false", "0", 0)

    def _view_button(self):
        """The list-or-thumbnails button, as in the Scenes tab: a menu of
        the two, the icon saying which is shown."""
        from PySide6.QtGui import QActionGroup
        from PySide6.QtWidgets import QMenu, QToolButton
        from views.icons import tool_icon
        btn = QToolButton()
        btn.setAutoRaise(True)
        btn.setPopupMode(QToolButton.InstantPopup)
        # No menu arrow: the icon alone, as small as the heading's text.
        btn.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        btn.setToolTip(tr(
            "Show the scenes as a list or with a picture of each"))
        menu = QMenu(btn)
        group = QActionGroup(self)
        self.list_action = menu.addAction(tool_icon("scenes_list"), tr("List"))
        self.thumbs_action = menu.addAction(tool_icon("scenes_thumbs"),
                                            tr("Thumbnails"))
        for act in (self.list_action, self.thumbs_action):
            act.setCheckable(True)
            group.addAction(act)
        self.list_action.triggered.connect(
            lambda: self.set_thumbnails(False))
        self.thumbs_action.triggered.connect(
            lambda: self.set_thumbnails(True))
        btn.setMenu(menu)
        return btn

    def set_thumbnails(self, on: bool) -> None:
        """Show each scene with its picture (``True``) or as a plain list,
        and remember the choice."""
        from PySide6.QtCore import QSettings
        if self._icon_for is None:
            return
        self.thumbnails = bool(on)
        QSettings().setValue(self.THUMBS_KEY, self.thumbnails)
        self._show_view_mode()
        self._shape = None
        self.refresh()

    def _show_view_mode(self) -> None:
        if self.view_btn is not None:
            from views.icons import tool_icon
            self.thumbs_action.setChecked(self.thumbnails)
            self.list_action.setChecked(not self.thumbnails)
            self.view_btn.setIcon(tool_icon(
                "scenes_thumbs" if self.thumbnails else "scenes_list"))
        self.tree.setIconSize(QSize(48, 32) if self.thumbnails
                              else QSize(16, 16))
        self.fit_rows()

    def fit_rows(self) -> None:
        """Room for :data:`SCENE_ROWS` rows at the rows' height now (the
        pictures make them taller); more scroll."""
        tree = self.tree
        row = max(tree.fontMetrics().height(), tree.iconSize().height()) + 6
        frame = 2 * tree.frameWidth()
        # On a page of its own (the composer's Scenes tab) it takes the
        # page's whole height.
        tree.setMaximumHeight(16777215 if getattr(self, "fills_page", False)
                              else SCENE_ROWS * row + frame)
        tree.setMinimumHeight(2 * row + frame)

    # ---- Rows --------------------------------------------------------------------
    def _rows(self) -> list:
        """Every row, folders and scenes, top to bottom."""
        out: list = []

        def walk(item) -> None:
            for i in range(item.childCount()):
                child = item.child(i)
                out.append(child)
                walk(child)
        walk(self.tree.invisibleRootItem())
        return out

    def scene_rows(self) -> list:
        """The scene rows, top to bottom (folders left out)."""
        return [it for it in self._rows()
                if it.data(0, Qt.UserRole)[0] == "scene"]

    def row_for(self, name: str):
        """The row of the scene called ``name``, or ``None``."""
        return next((it for it in self.scene_rows() if it.text(0) == name),
                    None)

    def _on_folded(self, item, opened: bool) -> None:
        kind, name = item.data(0, Qt.UserRole)
        if kind != "folder":
            return
        if opened:
            self._collapsed.discard(name)
        else:
            self._collapsed.add(name)

    # ---- Model → view ------------------------------------------------------------
    def refresh(self) -> None:
        from core import scene_folders as SF
        from views.outliner import node_icon
        scene = self._scene()
        views = list(scene.saved_views)
        folders = SF.folders_of(scene)
        # Rebuilt only when the scenes or their folders changed: every edit
        # of the model calls here, and a rebuild throws the pictures away.
        shape = (tuple((id(v), v.name, SF.folder_of(scene, v))
                       for v in views),
                 tuple((f, SF.folder_parent(scene, f)) for f in folders))
        if shape == self._shape:
            return
        self._shape = shape
        current = self.tree.currentItem()
        current = current.text(0) if current is not None and \
            current.data(0, Qt.UserRole)[0] == "scene" else None
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            folder_icon = node_icon("folder")
            scene_icon = node_icon("scene")
            ro =Qt.ItemIsEnabled | Qt.ItemIsSelectable

            def level(parent, name) -> None:
                for f in SF.subfolders(scene, name):
                    item = QTreeWidgetItem([f])
                    item.setData(0, Qt.UserRole, ("folder", f))
                    item.setIcon(0, folder_icon)
                    item.setFlags(ro)
                    parent.addChild(item)
                    level(item, f)
                    item.setExpanded(f not in self._collapsed)
                for view in SF.scenes_in(scene, name):
                    item = QTreeWidgetItem([view.name])
                    item.setData(0, Qt.UserRole, ("scene", view))
                    item.setFlags(ro | Qt.ItemIsDragEnabled)
                    if not self.thumbnails:        # pictures come queued
                        item.setIcon(0, scene_icon)
                    parent.addChild(item)
            level(self.tree.invisibleRootItem(), None)
            if current is not None:
                row = self.row_for(current)
                if row is not None:
                    self.tree.setCurrentItem(row)
        finally:
            self.tree.blockSignals(False)
        self._queue_icons()

    # ---- Pictures (icon_for) -------------------------------------------------------
    def showEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().showEvent(ev)
        self._queue_icons()

    def _queue_icons(self) -> None:
        """The scenes' pictures, one at a time from the event loop — a
        render each, so the list shows at once and fills in. Queued by NAME:
        a render can refresh the list, and the row is then another one.
        Only while on screen: a hidden list renders nothing."""
        if (self._icon_for is None or not self.thumbnails
                or not self.isVisible()):
            return
        # Only the scenes still without a picture.
        self._icon_queue = [it.text(0) for it in self.scene_rows()
                            if it.icon(0).isNull()]
        if self._icon_queue:
            QTimer.singleShot(0, self, self._next_icon)

    def _next_icon(self) -> None:
        from shiboken6 import isValid
        if not self._icon_queue or not isValid(self):
            return
        if not self.isVisible() or not self.thumbnails:
            # Off screen since it was queued (its window closing): a render
            # now would go through a view that may be on its way out.
            self._icon_queue = []
            return
        name = self._icon_queue.pop(0)
        icon = self._icon_for(name)
        item = self.row_for(name)
        if icon is not None and item is not None:
            item.setIcon(0, icon)
        if self._icon_queue:
            QTimer.singleShot(20, self, self._next_icon)

    def mark(self, name) -> list:
        """Mark the scene called ``name`` (``None``: none) — a view of it
        is the current row of the sheet explorer. Returns the marked
        rows."""
        out = []
        for item in self.scene_rows():
            on = name is not None and item.text(0) == name
            mark_row(item, on)
            if on:
                out.append(item)
        return out

    def show_scene(self, name: str) -> bool:
        """Make the scene called ``name`` the current row, its folders
        unfolded. Whether it is in the list."""
        self.refresh()
        item = self.row_for(name)
        if item is None:
            return False
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        return True

    # ---- View → model ------------------------------------------------------------
    def _on_activate(self, item, _column=0) -> None:
        kind, view = item.data(0, Qt.UserRole)
        if kind != "scene":
            return                         # a folder: Qt folds it
        if self._activate_hook is not None:
            self._activate_hook(view)
        else:
            self._window.tray.scenes.activate_view(view)


class SheetsTab(QWidget):
    """The composer's Sheets page, and beside it its Scenes page
    (:attr:`scenes_page`). They were one page, scenes above sheets with a
    divider; apart since 20-11 (Marco: «laminas aparte y escenas aparte»):
    a double-click on a scene places it on the open sheet, and with the two
    lists together a click meant for a sheet put a scene on it. A scene
    still drags onto a sheet's tab or onto the canvas, and a scene and the
    views that show it still mark each other."""

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        self._window = window
        self._composer_win = composer
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        # Just the scenes in their folders, to drag onto sheets — they are
        # made and changed in the main window's Scenes tab. In the composer
        # a double-click places the scene on the open sheet, and each scene
        # shows its picture (the composer keeps them, by name).
        self.scenes = SceneList(
            window,
            on_activate=(lambda view: composer.place_scene_at(view.name))
            if composer is not None else None,
            icon_for=composer.scene_thumbnail if composer is not None
            else None)
        self.scenes.fills_page = True
        self.scenes.fit_rows()
        self.sheets = SheetExplorer(window, composer=composer)
        #: The Scenes page: the composer puts it in its side panel as a tab
        #: of its own («scenes»), next to this one.
        self.scenes_page = _titled(tr("Scenes"), self.scenes,
                                   tail=self.scenes.view_btn)
        lay.addWidget(_titled(tr("Sheets"), self.sheets,
                              tail=self.sheets.view_btn))
        # A scene and the views that show it mark each other (a folder
        # row marks nothing).
        self.scenes.tree.currentItemChanged.connect(
            lambda item, _prev: self.sheets.mark_scene(
                item.text(0) if item is not None
                and item.data(0, Qt.UserRole)[0] == "scene" else None))
        self.sheets.tree.currentItemChanged.connect(
            lambda item, _prev: self._mark_from_sheets(item))

    def _mark_from_sheets(self, item) -> None:
        """A sheet row marks no scene: the sheets list no scenes any more
        (Marco, 20-11), and a sheet may show many."""
        self.scenes.mark(None)

    def on_scene_changed(self) -> None:
        if self._composer_win is not None:
            sync_composer(self._window)
        self.scenes.refresh()
        self.sheets.on_scene_changed()

    def show_scene_row(self, name: str) -> None:
        """Make the scene called ``name`` the current row (a plan just
        made: the user sees where it went)."""
        self.scenes.show_scene(name)


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


def _titled(title: str, panel, tail=None) -> QWidget:
    """A panel under a small bold heading; ``tail`` (a small button) at
    the heading's right end, on the same line."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(0)
    head = QLabel(title)
    font = QFont(head.font())
    font.setBold(True)
    head.setFont(font)
    head.setContentsMargins(8, 0, 8, 0)
    if tail is None:
        lay.addWidget(head)
    else:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(0)
        row.addWidget(head)
        row.addStretch(1)
        side = head.sizeHint().height() + 4
        tail.setIconSize(QSize(side - 6, side - 6))
        tail.setFixedSize(side, side)
        row.addWidget(tail)
        lay.addLayout(row)
    lay.addWidget(panel, 1)
    return box
