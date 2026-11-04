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
        #: Its viewport's frame, small, shown on hover over its tab; drawn
        #: then, if it is due (MainWindow._tab_picture).
        self.thumbnail = None
        self.picture_due = False
        #: Its scenes shown as tabs under the viewport (views/scene_tabs.py);
        #: its tab's right-click menu turns them off and on.
        from views.scene_tabs import SCENE_TABS_DEFAULT
        self.scene_tabs: bool = SCENE_TABS_DEFAULT
        #: How many views it shows (views/multi_view.py LAYOUTS) and the
        #: grid holding them, made the first time it shows more than one.
        self.view_layout: str = "single"
        self.view_grid = None
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


#: The «+» after a row of tabs: its icon (px). The project tabs and the
#: scene tabs under the viewport share the same «+».
PLUS_ICON = 16


def size_plus_button(plus, tabs) -> None:
    """``plus`` as tall as a tab of ``tabs`` and a little wider than tall —
    the same «+» after the project tabs and after the scene tabs."""
    h = tabs.sizeHint().height() if tabs.count() else 0
    if h <= 0:
        probe = QTabBar()
        probe.setFont(tabs.font())
        probe.addTab("Xg")
        h = probe.sizeHint().height()
    if plus.height() != h or plus.width() != max(30, h + 4):
        plus.setFixedSize(max(30, h + 4), h)


class _ProjectTabs(QTabBar):
    """The project tabs, drawn as the side panels' tabs are (the same
    QTabBar and style, the same height), with a line in the accent colour
    under the active project's name; as wide as a name and its cross need,
    and the cross bigger and against the tab's right edge."""

    #: The accent line: thickness and gap above the tab's foot (px).
    LINE_PX = 2
    LINE_GAP = 3
    #: The close cross: its button, the icon in it, its gap from the edge.
    CLOSE_PX = 16
    CLOSE_ICON = 13
    CLOSE_EDGE = 4
    #: Room around a name: left, between name and cross, and right (px).
    PAD_LEFT, PAD_GAP, PAD_RIGHT = 10, 4, 4

    def tabSizeHint(self, index: int):  # noqa: N802 — Qt override
        hint = super().tabSizeHint(index)
        height = self._panel_tab_height()
        # Qt asks for every tab many times over a single layout.
        name = self.tabText(index)
        key = (name, hint.width(), self.font().key(), self.style().name())
        width = self._hint_widths.get(key)
        if width is None:
            width = self._hint_widths[key] = self._tab_width(index, hint,
                                                             height)
        hint.setWidth(width)
        hint.setHeight(height)
        return hint

    def _tab_width(self, index: int, hint, height: int) -> int:
        fm = self.fontMetrics()
        name = self.tabText(index)
        width = (self.PAD_LEFT + fm.horizontalAdvance(name) + self.PAD_GAP
                 + self.CLOSE_PX + self.PAD_RIGHT)
        # The style keeps margins of its own around the name: widen until
        # the whole name fits, measured as the selected tab (the narrower
        # text area), so the size does not change when it comes to front.
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QStyle, QStyleOptionTab
        opt = QStyleOptionTab()
        self.initStyleOption(opt, index)
        opt.state |= QStyle.State_Selected
        opt.position = QStyleOptionTab.Middle
        need = fm.horizontalAdvance(name) + 2
        while width < hint.width():
            opt.rect = QRect(0, 0, width, height)
            if self.style().subElementRect(
                    QStyle.SE_TabBarTabText, opt, self).width() >= need:
                break
            width += 2
        return min(hint.width(), width)

    _hint_widths: dict = {}
    _probe_heights: dict = {}

    def _panel_tab_height(self) -> int:
        """A side panel's tab height: the style's tab for this font, with
        no button in it (Qt makes a tab with a cross taller)."""
        key = (self.font().key(), self.style().name())
        h = self._probe_heights.get(key)
        if h is None:
            probe = QTabBar()
            probe.setFont(self.font())
            probe.setStyle(self.style())
            probe.addTab("Xg")
            h = self._probe_heights[key] = probe.tabSizeHint(0).height()
            probe.deleteLater()
        return h

    def sizeHint(self):  # noqa: N802 — Qt override
        """Exactly as wide as its tabs: Qt's hint keeps room for the
        scroll arrows, which left «+» a gap away from the last tab."""
        hint = super().sizeHint()
        if self.count():
            hint.setWidth(sum(self.tabSizeHint(i).width()
                              for i in range(self.count())))
        return hint

    def minimumSizeHint(self):  # noqa: N802 — Qt override
        hint = super().minimumSizeHint()
        hint.setWidth(min(hint.width(), self.sizeHint().width()))
        return hint

    # ---- the cross ---------------------------------------------------------
    def tabInserted(self, index: int) -> None:  # noqa: N802 — Qt override
        super().tabInserted(index)
        from PySide6.QtCore import QSize
        from views.icons import tool_icon
        btn = QToolButton(self)
        btn.setObjectName("project_tab_close")
        btn.setProperty("icon_key", "close")
        btn.setIcon(tool_icon("close"))
        btn.setIconSize(QSize(self.CLOSE_ICON, self.CLOSE_ICON))
        btn.setFixedSize(self.CLOSE_PX, self.CLOSE_PX)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(tr("Close Project") + " (Ctrl+W)")
        btn.setAccessibleName(tr("Close Project"))
        btn.clicked.connect(lambda _c=False, b=btn: self._close_clicked(b))
        self.setTabButton(index, QTabBar.RightSide, btn)

    def _close_clicked(self, btn) -> None:
        for i in range(self.count()):
            if self.tabButton(i, QTabBar.RightSide) is btn:
                self.tabCloseRequested.emit(i)
                return

    def tabLayoutChange(self) -> None:  # noqa: N802 — Qt override
        super().tabLayoutChange()
        self._seat_close_buttons()

    def resizeEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(ev)
        self._seat_close_buttons()

    def _seat_close_buttons(self) -> None:
        """Against the tab's right edge, centred on its height (the style
        lays it out with a margin of its own)."""
        for i in range(self.count()):
            btn = self.tabButton(i, QTabBar.RightSide)
            if btn is None:
                continue
            r = self.tabRect(i)
            want = QPoint(r.right() - self.CLOSE_EDGE - btn.width() + 1,
                          r.top() + (r.height() - btn.height()) // 2)
            if btn.pos() != want:
                btn.move(want)

    # ---- the accent line ---------------------------------------------------
    def underline_rect(self):
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QStyle, QStyleOptionTab
        i = self.currentIndex()
        if i < 0 or not self.tabText(i):
            return None
        opt = QStyleOptionTab()
        self.initStyleOption(opt, i)
        text = self.style().subElementRect(QStyle.SE_TabBarTabText, opt, self)
        width = min(self.fontMetrics().horizontalAdvance(opt.text),
                    text.width())
        tab = self.tabRect(i)
        y = tab.bottom() - self.LINE_GAP - self.LINE_PX + 1
        return QRect(text.center().x() - width // 2, y, width, self.LINE_PX)

    def paintEvent(self, ev) -> None:  # noqa: N802 — Qt override
        # Qt seats the crosses again on its own (a click on a tab did, and
        # the cross jumped back to the style's place): every frame, before
        # drawing, they go back against the edge.
        self._seat_close_buttons()
        super().paintEvent(ev)
        rect = self.underline_rect()
        if rect is None:
            return
        from PySide6.QtGui import QPainter
        from views.theme import accent_color
        p = QPainter(self)
        p.fillRect(rect, accent_color())
        p.end()


class ProjectTabBar(QWidget):
    """The project tabs above the viewport: the file name, a dot while it
    has unsaved changes, a × to close; «+» makes a new project; a middle
    click closes; tabs are reordered by dragging them.

    Signals carry the :class:`Document` (each tab's data)."""

    activated = Signal(object)
    closeRequested = Signal(object)
    newRequested = Signal()
    moved = Signal()
    #: The views button: the layouts of the project in front.
    viewsRequested = Signal()
    #: A right-click on a tab: its document and where (global position).
    menuRequested = Signal(object, QPoint)

    #: The mark of a project with unsaved changes, after its name.
    DIRTY_MARK = " •"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("project_tabs")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 0, 0)
        row.setSpacing(0)
        from PySide6.QtCore import QSize
        from views.icons import tool_icon
        # The views button, first: one, two, three or four views of the
        # project in front (views/multi_view.py).
        views = self.views_button = QToolButton(self)
        views.setObjectName("project_views")
        views.setProperty("icon_key", "four_views")
        views.setIcon(tool_icon("four_views"))
        views.setIconSize(QSize(18, 18))
        views.setFixedSize(26, 26)
        views.setCheckable(True)
        views.setAutoRaise(True)
        views.setCursor(Qt.PointingHandCursor)
        views.setToolTip(tr(
            "View layout: one, two, three or four views of the model"))
        views.setAccessibleName(views.toolTip())
        views.clicked.connect(lambda _c=False: self.viewsRequested.emit())
        row.addWidget(views, 0, Qt.AlignVCenter)
        row.addSpacing(4)
        bar = self.tabs = _ProjectTabs(self)
        bar.setObjectName("project_tab_bar")
        # Drawn as the side panels' tabs (no document mode, no style sheet
        # of its own) with the accent line under the active name.
        bar.setDocumentMode(False)
        bar.setExpanding(False)
        bar.setMovable(True)
        bar.setTabsClosable(False)          # our own, bigger cross
        bar.setUsesScrollButtons(True)
        bar.setElideMode(Qt.ElideMiddle)
        bar.setDrawBase(False)
        bar.setSelectionBehaviorOnRemove(QTabBar.SelectPreviousTab)
        bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        bar.tabCloseRequested.connect(self._on_close_index)
        bar.currentChanged.connect(self._on_current)
        bar.tabMoved.connect(lambda *_a: self.moved.emit())
        bar.installEventFilter(self)
        bar.setContextMenuPolicy(Qt.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._on_menu)
        row.addWidget(bar, 0, Qt.AlignBottom)
        # «+» right after the last tab, as tall as a tab; drawn, so it is
        # centred to the pixel (a font's «+» sits off centre).
        plus = self.plus = QToolButton(self)
        plus.setObjectName("project_tab_new")
        plus.setProperty("icon_key", "plus")
        plus.setIcon(tool_icon("plus"))
        plus.setIconSize(QSize(PLUS_ICON, PLUS_ICON))
        plus.setToolButtonStyle(Qt.ToolButtonIconOnly)
        plus.setAutoRaise(True)
        plus.setToolTip(tr("New project (Ctrl+N)"))
        plus.setCursor(Qt.PointingHandCursor)
        plus.clicked.connect(self.newRequested.emit)
        row.addWidget(plus, 0, Qt.AlignBottom)
        row.addStretch(1)
        self._quiet = False
        from views.theme import style as theme_style
        theme_style(self,
            "#project_tabs {{ background: palette(window); }}"
            "QToolButton#project_tab_close {{ border: none;"
            " border-radius: 4px; background: transparent; padding: 0px; }}"
            "QToolButton#project_tab_close:hover {{"
            " background: rgba({accent_rgb}, 66); }}"
            "QToolButton#project_tab_new, QToolButton#project_views {{"
            " border: none; border-radius: 6px; background: transparent;"
            " padding: 0px; }}"
            "QToolButton#project_tab_new:hover,"
            " QToolButton#project_views:hover {{"
            " background: rgba({accent_rgb}, 36); }}"
            "QToolButton#project_views:checked {{"
            " background: rgba({accent_rgb}, 60); }}")

    def showEvent(self, ev) -> None:  # noqa: N802 — Qt override
        super().showEvent(ev)
        self.match_plus_to_tabs()

    def match_plus_to_tabs(self) -> None:
        """«+» as tall as a tab (a little wider than tall)."""
        size_plus_button(self.plus, self.tabs)

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

    def _on_menu(self, pos) -> None:
        i = self.tabs.tabAt(pos)
        if i >= 0:
            self.menuRequested.emit(self.tabs.tabData(i),
                                    self.tabs.mapToGlobal(pos))

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
    #: The picture of a document in the back (the window draws it if due).
    picture_of = staticmethod(lambda doc: doc.thumbnail)

    def _show_preview(self, pos, global_pos) -> bool:
        """Over a tab in the back: the picture its viewport showed when it
        was left, with the file's name under it. False when there is no
        picture (the tab in front, or one never left): the plain tooltip
        then shows."""
        i = self.tabs.tabAt(pos)
        doc = self.tabs.tabData(i) if i >= 0 else None
        img = None
        if doc is not None and i != self.tabs.currentIndex():
            img = self.picture_of(doc)
        if img is None or img.isNull():
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
        box._name.setText(doc.display_name())
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
