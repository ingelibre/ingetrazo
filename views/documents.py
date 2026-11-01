# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Several projects open in one window, each in its own tab (#1066).

A :class:`Document` is one open project. It owns a whole
:class:`views.viewport.Viewport` — the scene, its undo history, the camera,
every drawing cache and the GL textures live there already — plus what the
main window used to keep for its single document: the file, the name of an
import, the version last saved and auto-saved, the auto-save slot of an
untitled drawing, and the sheet composer.

The window keeps the viewports in a stack under a :class:`ProjectTabBar`
and its ``viewport`` is a property that answers the ACTIVE document's. The
hundreds of places that read ``window.viewport`` — the window, the panels,
the extensions — follow the active tab without knowing tabs exist; a tab in
the background is a hidden widget that Qt neither paints nor updates, and
coming back to it rebuilds nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QSizePolicy, QTabBar, QToolButton,
                               QWidget)

from core.i18n import tr


class Document:
    """One open project: its viewport and the window's record of it."""

    def __init__(self, viewport=None) -> None:
        self.viewport = viewport
        #: The .igz it was opened from or saved to (None = never saved).
        self.path: Optional[Path] = None
        #: The imported file's name, shown until the model is saved as .igz.
        self.import_name: Optional[str] = None
        #: Content version at the last save (see MainWindow._saved_version).
        self.saved_content: int = 0
        #: Scene version the auto-save last wrote, or None.
        self.autosaved_version: Optional[int] = None
        #: Which untitled auto-save slot it writes while it has no path
        #: (``core.autosave.slot_for``): 1 is the classic ``untitled.igz``.
        self.untitled_no: int = 1
        #: The sheet composer of this document, created on demand.
        self.composer = None
        #: The composer was on screen when the user left this tab.
        self.composer_shown = False
        self.last_sheet: int = 0
        #: Its viewport's last frame, small, shown on hover over its tab.
        self.thumbnail = None
        #: What an extension put in this project's place in the viewport
        #: stack with ``setCentralWidget`` (MultiView's grid of views, which
        #: holds this viewport), or a blank placeholder between its
        #: ``takeCentralWidget`` and that call; None = the viewport itself.
        #: See MainWindow.centralWidget.
        self.stand_in = None

    def slot_widget(self):
        """The widget this project shows in the viewport stack."""
        return self.stand_in if self.stand_in is not None else self.viewport

    def display_name(self) -> str:
        if self.path is not None:
            return Path(self.path).name
        if self.import_name:
            return str(self.import_name)
        return tr("Untitled")

    def same_file(self, path) -> bool:
        """Whether ``path`` names the file this document holds."""
        if self.path is None or path is None:
            return False
        try:
            return Path(self.path).resolve() == Path(path).resolve()
        except OSError:
            return Path(self.path).absolute() == Path(path).absolute()


class DocumentHost:
    """The main window as one document's sheet composer sees it: everything
    is the window's, except the viewport and the file, which stay that
    document's even while another tab is in front — a composer's timer must
    never render the other project into its frames."""

    def __init__(self, window, doc: Document) -> None:
        object.__setattr__(self, "_host_window", window)
        object.__setattr__(self, "_host_doc", doc)

    @property
    def viewport(self):
        return self._host_doc.viewport

    @property
    def _current_path(self):
        return self._host_doc.path

    def __getattr__(self, name):
        return getattr(self._host_window, name)

    def __setattr__(self, name, value) -> None:
        setattr(self._host_window, name, value)


def live_viewport(viewport):
    """A callable that answers the viewport of the project in front of
    ``viewport``'s window — what a panel built with the viewport of its day
    keeps, so it acts on whichever project the user is looking at. It keeps
    the WINDOW, never that viewport: a panel holding a viewport would hold
    its whole closed project in memory. A viewport outside a tabbed window
    (tests, a lone widget) is answered as it is."""
    try:
        win = viewport.window()
    except (AttributeError, RuntimeError):
        win = None
    if win is not None and hasattr(win, "documents"):
        return lambda: win.viewport
    return lambda: viewport


class ProjectTabBar(QWidget):
    """The project tabs above the viewport: the file name, a dot while it
    has unsaved changes, a × to close; «+» makes a new project; a middle
    click closes; tabs are reordered by dragging them.

    Signals carry the :class:`Document` (each tab's data)."""

    activated = Signal(object)
    closeRequested = Signal(object)
    newRequested = Signal()
    moved = Signal()

    #: The mark of a project with unsaved changes, after its name.
    DIRTY_MARK = " •"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("project_tabs")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        bar = self.tabs = QTabBar(self)
        bar.setObjectName("project_tab_bar")
        bar.setDocumentMode(True)
        bar.setExpanding(False)
        bar.setMovable(True)
        bar.setTabsClosable(True)
        bar.setUsesScrollButtons(True)
        bar.setElideMode(Qt.ElideMiddle)
        bar.setDrawBase(False)
        bar.setSelectionBehaviorOnRemove(QTabBar.SelectPreviousTab)
        bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        bar.tabCloseRequested.connect(self._on_close_index)
        bar.currentChanged.connect(self._on_current)
        bar.tabMoved.connect(lambda *_a: self.moved.emit())
        bar.installEventFilter(self)
        row.addWidget(bar, 0)
        plus = self.plus = QToolButton(self)
        plus.setObjectName("project_tab_new")
        plus.setText("+")
        plus.setAutoRaise(True)
        plus.setToolTip(tr("New project (Ctrl+N)"))
        plus.setCursor(Qt.PointingHandCursor)
        plus.clicked.connect(self.newRequested.emit)
        row.addWidget(plus, 0)
        row.addStretch(1)
        self._quiet = False
        from views.theme import style as theme_style
        theme_style(self,
            "#project_tabs {{ background: palette(window); }}"
            "QTabBar#project_tab_bar::tab {{ padding: 3px 10px;"
            " max-width: 260px; border: none;"
            " border-bottom: 2px solid transparent; }}"
            "QTabBar#project_tab_bar::tab:selected {{"
            " border-bottom: 2px solid rgb({accent_rgb});"
            " background: palette(base); }}"
            "QTabBar#project_tab_bar::tab:!selected:hover {{"
            " background: rgba({accent_rgb}, 40); }}"
            "QToolButton#project_tab_new {{ padding: 0px 8px;"
            " font-weight: bold; }}")

    # ---- the tabs ---------------------------------------------------------
    def count(self) -> int:
        return self.tabs.count()

    def documents(self) -> list:
        return [self.tabs.tabData(i) for i in range(self.tabs.count())]

    def index_of(self, doc) -> int:
        for i in range(self.tabs.count()):
            if self.tabs.tabData(i) is doc:
                return i
        return -1

    def add(self, doc, index: int = -1) -> int:
        self._quiet = True
        try:
            if index < 0:
                i = self.tabs.addTab("")
            else:
                i = self.tabs.insertTab(index, "")
            self.tabs.setTabData(i, doc)
        finally:
            self._quiet = False
        return i

    def remove(self, doc) -> None:
        i = self.index_of(doc)
        if i < 0:
            return
        self._quiet = True
        try:
            self.tabs.removeTab(i)
        finally:
            self._quiet = False

    def set_current(self, doc) -> None:
        i = self.index_of(doc)
        if i >= 0 and i != self.tabs.currentIndex():
            self._quiet = True
            try:
                self.tabs.setCurrentIndex(i)
            finally:
                self._quiet = False

    def current(self):
        i = self.tabs.currentIndex()
        return self.tabs.tabData(i) if i >= 0 else None

    def set_label(self, doc, name: str, dirty: bool, tip: str = "") -> None:
        i = self.index_of(doc)
        if i < 0:
            return
        text = name + (self.DIRTY_MARK if dirty else "")
        if self.tabs.tabText(i) != text:
            self.tabs.setTabText(i, text)
        if self.tabs.tabToolTip(i) != tip:
            self.tabs.setTabToolTip(i, tip)

    def neighbour(self, doc, step: int):
        """The document ``step`` tabs away from ``doc``, wrapping round."""
        n = self.tabs.count()
        i = self.index_of(doc)
        if n == 0 or i < 0:
            return None
        return self.tabs.tabData((i + step) % n)

    # ---- user input -------------------------------------------------------
    def _on_current(self, index: int) -> None:
        if self._quiet or index < 0:
            return
        doc = self.tabs.tabData(index)
        # After the press: QTabBar is still handling it when the signal
        # returns, and the window rebuilds things under the pointer.
        QTimer.singleShot(0, self, lambda d=doc: self.activated.emit(d))

    def _on_close_index(self, index: int) -> None:
        doc = self.tabs.tabData(index)
        if doc is not None:
            QTimer.singleShot(0, self, lambda d=doc: self.closeRequested.emit(d))

    def eventFilter(self, obj, event):  # noqa: N802 — Qt override
        if obj is self.tabs:
            t = event.type()
            if (t == QEvent.MouseButtonRelease
                    and event.button() == Qt.MiddleButton):
                i = self.tabs.tabAt(event.position().toPoint())
                if i >= 0:
                    self._on_close_index(i)
                    return True
            elif (t == QEvent.MouseButtonDblClick
                  and event.button() == Qt.LeftButton
                  and self.tabs.tabAt(event.position().toPoint()) < 0):
                self.newRequested.emit()       # the empty strip: a new tab
                return True
            elif t == QEvent.ToolTip:
                if self._show_preview(event.pos(), event.globalPos()):
                    return True
            elif t in (QEvent.Leave, QEvent.MouseButtonPress, QEvent.Hide):
                self._hide_preview()
            elif t == QEvent.MouseMove and self._preview is not None \
                    and self._preview.isVisible():
                i = self.tabs.tabAt(event.position().toPoint())
                if i < 0 or self.tabs.tabData(i) is not self._preview_doc:
                    self._hide_preview()
        return super().eventFilter(obj, event)

    # ---- preview on hover -------------------------------------------------
    _preview = None
    _preview_doc = None

    def _show_preview(self, pos, global_pos) -> bool:
        """Over a tab in the back: the picture its viewport showed when it
        was left, with the file's place under it. False when there is no
        picture (the tab in front, or one never left): the plain tooltip
        then shows."""
        i = self.tabs.tabAt(pos)
        doc = self.tabs.tabData(i) if i >= 0 else None
        img = getattr(doc, "thumbnail", None)
        if doc is None or img is None or img.isNull() \
                or i == self.tabs.currentIndex():
            self._hide_preview()
            return False
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QLabel, QVBoxLayout
        if self._preview is None:
            box = self._preview = QWidget(self, Qt.ToolTip)
            box.setObjectName("project_tab_preview")
            lay = QVBoxLayout(box)
            lay.setContentsMargins(4, 4, 4, 4)
            lay.setSpacing(2)
            box._pic = QLabel(box)
            box._name = QLabel(box)
            lay.addWidget(box._pic)
            lay.addWidget(box._name)
            box.setStyleSheet("#project_tab_preview { background: palette(base);"
                              " border: 1px solid palette(mid); }")
        box = self._preview
        box._pic.setPixmap(QPixmap.fromImage(img))
        box._name.setText(self.tabs.tabToolTip(i) or self.tabs.tabText(i))
        box.adjustSize()
        r = self.tabs.tabRect(i)
        at = self.tabs.mapToGlobal(r.bottomLeft()) + QPoint(0, 4)
        box.move(at)
        box.show()
        self._preview_doc = doc
        return True

    def _hide_preview(self) -> None:
        if self._preview is not None:
            self._preview.hide()
        self._preview_doc = None

    def tab_rect_global(self, doc):
        i = self.index_of(doc)
        if i < 0:
            return None
        r = self.tabs.tabRect(i)
        return r.translated(self.tabs.mapToGlobal(QPoint(0, 0)))
