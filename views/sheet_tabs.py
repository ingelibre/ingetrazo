# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Model | Sheet 1 | Sheet 2 … strip in the status bar of a window.

AutoCAD's Model / Layout tabs, for the same reason: going from the model to
a sheet and back is the most frequent trip of a plan-drawing session, and it
lived three clicks away in File ▸ Sheet composer (Marco, 2026-09-07: «¿no
sería mejor en la barra de abajo dos botones para cambiar del modelo a
composiciones, como lo tiene AutoCAD?» — and then: «debería estar en la
misma fila donde está ese cuadro donde te muestra las medidas»).

So the strip lives INSIDE the status bar, at its left, on the same row as
the measurements box. A plain QStatusBar hides its normal widgets whenever a
temporary message shows, which would make the tabs blink out on every
hint; ``SheetStatusBar`` keeps the tabs and its own message label as
permanent widgets and routes ``showMessage`` into that label instead, so
the row never reflows.

Both windows carry one: the main window's always marks «Model» (that is
what it displays), the composer's marks its open sheet. Clicking a tab
hands over to the other window; the owner re-syncs its strip afterwards so
a window never claims to show something it does not.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy, QStatusBar, QTabBar

from core.i18n import tr


class SheetTabs(QTabBar):
    """The tab strip. ``on_model()`` and ``on_sheet(index)`` are the owner's
    callbacks; ``refresh`` rebuilds the strip from the sheet names and marks
    the current tab (``None`` = the model)."""

    def __init__(self, parent, on_model, on_sheet) -> None:
        super().__init__(parent)
        self.setObjectName("sheet_tabs")
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.ElideRight)
        self.setToolTip(tr(
            "Switch between the model and each sheet — AutoCAD's "
            "Model / Layout tabs."))
        self._on_model = on_model
        self._on_sheet = on_sheet
        # tabBarClicked, not currentChanged: clicking the tab that is
        # already current must still hand over (the composer's «Model»
        # tab is never current there, but the main window's is).
        self.tabBarClicked.connect(self._clicked)
        self._updating = False
        self.refresh([], None)

    # ---- state ----------------------------------------------------------------
    def refresh(self, names, current) -> None:
        """Rebuild the strip: «Model» then one tab per sheet name; ``current``
        is the sheet index to mark, or ``None`` for the model."""
        self._updating = True
        try:
            while self.count():
                self.removeTab(0)
            self.addTab(tr("Model"))
            for name in names:
                self.addTab(str(name) or tr("Sheet"))
            idx = 0 if current is None else int(current) + 1
            self.setCurrentIndex(max(0, min(idx, self.count() - 1)))
        finally:
            self._updating = False

    def names(self) -> list:
        return [self.tabText(i) for i in range(self.count())]

    def current(self):
        """``None`` for the model, else the sheet index."""
        i = self.currentIndex()
        return None if i <= 0 else i - 1

    # ---- clicks ---------------------------------------------------------------
    def _clicked(self, index: int) -> None:
        if self._updating or index < 0:
            return
        if index == 0:
            self._on_model()
        else:
            self._on_sheet(index - 1)

    def click(self, index: int) -> None:
        """Programmatic click (tests): the same path as the mouse."""
        self._clicked(index)


class _ElidedLabel(QLabel):
    """A label that never asks for room: a plain QLabel's minimum width is
    its whole text, and the standing hint of the main window is a long
    line — as a permanent widget it made the window impossible to shrink
    or maximise onto a smaller screen (Marco, 2026-09-07: «no puedo
    maximizar la ventana»). This one reports no minimum and elides."""

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setTextInteractionFlags(Qt.NoTextInteraction)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = str(text or "")
        self._relayout()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, Qt.ElideRight,
                                      max(self.width() - 4, 0)))


class SheetStatusBar(QStatusBar):
    """A status bar whose left end is the Model | sheets strip and whose
    messages go to a label of its own, so the strip shares the row with
    the measurements box and never disappears behind a hint.

    ``showMessage(text)`` (no timeout) sets the standing text; a timed
    message replaces it for a while and then the standing text comes back
    — a plain QStatusBar leaves the bar empty after a timed message."""

    def __init__(self, parent, on_model, on_sheet) -> None:
        super().__init__(parent)
        self.tabs = SheetTabs(self, on_model, on_sheet)
        self._msg = _ElidedLabel(self)
        self._base = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._restore)
        # Permanent widgets, left to right: the strip, then the message
        # label with all the stretch — it soaks up the free width, so the
        # strip stays glued to the left and whatever the windows add later
        # (tool, coordinates, the VCB, the zoom combo) lines up on the right.
        self.addPermanentWidget(self.tabs)
        self.addPermanentWidget(self._msg, 1)

    # ---- messages, routed to our label ---------------------------------------
    def showMessage(self, text: str, timeout: int = 0) -> None:  # noqa: N802
        text = str(text or "")
        if timeout and timeout > 0:
            self._msg.setText(text)
            self._timer.start(int(timeout))
        else:
            self._timer.stop()
            self._base = text
            self._msg.setText(text)

    def clearMessage(self) -> None:  # noqa: N802
        self._timer.stop()
        self._msg.setText(self._base)

    def currentMessage(self) -> str:  # noqa: N802
        return self._msg.text()

    def _restore(self) -> None:
        self._msg.setText(self._base)
