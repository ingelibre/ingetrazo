# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Model | Sheet 1 | Sheet 2 … | + strip in the status bar of a window.

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

The strip ends in a «+» tab, AutoCAD's «new layout»: a fresh document has
no sheets, and a strip that only said «Model» gave no way into the
composer at all (Marco, 0.3.13 Flatpak: «no aparece compositor de láminas
abajo»). «+» opens the composer on a new sheet.

Both windows carry one: the main window's always marks «Model» (that is
what it displays), the composer's marks its open sheet. Clicking a tab
hands over to the other window; the owner re-syncs its strip afterwards so
a window never claims to show something it does not. The hand-over runs
AFTER the click, from the event loop: QTabBar still works on the tab it
pressed when the clicked signal returns (it makes it current), so a strip
rebuilt inside the signal ended up marking the pressed tab instead of what
its window shows, and tearing tabs down under a press in progress is the
kind of thing that segfaults.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy, QStatusBar, QTabBar, QWidget

from core.i18n import tr


class SheetTabs(QTabBar):
    """The tab strip. ``on_model()``, ``on_sheet(index)`` and ``on_new()``
    are the owner's callbacks; ``refresh`` rebuilds the strip from the
    sheet names and marks the current tab (``None`` = the model)."""

    def __init__(self, parent, on_model, on_sheet, on_new=None,
                 on_menu=None) -> None:
        super().__init__(parent)
        self.setObjectName("sheet_tabs")
        # Right-click on a sheet tab: the owner's menu — rename, duplicate,
        # delete (Marco, 2026-09-08: «desde los botones de lámina de abajo
        # con el menú del mouse»). Gets (sheet index, global pos).
        self._on_menu = on_menu
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setUsesScrollButtons(True)
        # Scroll, never elide: an elided strip squeezes every name to «L…»
        # before the ◀ ▶ buttons ever show.
        self.setElideMode(Qt.ElideNone)
        # The keys here too, not only on each tab: where Qt cannot tell
        # which tab is under the pointer (Marco's Wayland screen at 120 %)
        # this is the tip that shows.
        self.setToolTip(tr(
            "Model and sheets — Ctrl+Tab switches between them; in the "
            "sheets, Ctrl+PgUp / Ctrl+PgDown go to the sheet before / "
            "after."))
        self._on_model = on_model
        self._on_sheet = on_sheet
        self._on_new = on_new
        self._names: list = []
        self._labels: list = []
        # tabBarClicked, not currentChanged: clicking the tab that is
        # already current must still hand over (the composer's «Model»
        # tab is never current there, but the main window's is).
        self.tabBarClicked.connect(self._clicked)
        self._updating = False
        self.refresh([], None)

    # ---- state ----------------------------------------------------------------
    # The strip has a width budget (a share of the bar): past it, QTabBar's
    # own ◀ ▶ scroll buttons appear, the way spreadsheet tabs scroll, and the
    # tabs keep their look. With four sheets the strip had left the hint a
    # stub, and with ten it would have left nothing (Marco, 23-09; he tried
    # folding the tabs into a «▾ N more» menu and preferred the arrows).
    # The LOGICAL layout — «Model», one tab per sheet, «+» — is what
    # ``names``/``current``/``plus_index``/``click`` speak.

    def _wanted(self, names) -> list:
        labels = [tr("Model")] + [str(n) or tr("Sheet") for n in names]
        if self._has_new():
            labels.append("+")
        return labels

    def _has_new(self) -> bool:
        return self._on_new is not None and getattr(self, "_show_new", True)

    def set_show_new(self, show: bool) -> None:
        """Whether the «+» tab is offered (the model window drops it once
        the document has sheets: there it only goes model ↔ sheet)."""
        self._show_new = bool(show)

    def set_budget(self, px) -> None:
        """The width the strip may take; past it the scroll arrows show."""
        self.setMaximumWidth(16777215 if px is None else max(int(px), 120))

    def _slots(self) -> list:
        """What each displayed tab stands for: ``("model",)``,
        ``("sheet", i)`` or ``("new",)``."""
        n = len(self._names)
        return ([("model",)] + [("sheet", i) for i in range(n)]
                + ([("new",)] if self._has_new() else []))

    def _slot_label(self, slot) -> str:
        kind = slot[0]
        if kind == "model":
            return self._labels[0]
        if kind == "sheet":
            return self._labels[1 + slot[1]]
        return "+"

    def refresh(self, names, current) -> None:
        """Rebuild the strip: «Model» then one tab per sheet name (then «+»);
        ``current`` is the sheet index to mark, or ``None`` for the model.
        The tabs are only torn down when what they show changed — a hint or
        a hand-over must not rebuild the widget under the mouse."""
        self._labels = self._wanted(names)
        self._names = [str(n) for n in names]
        cur = None if current is None else int(current)
        if cur is not None and not 0 <= cur < len(self._names):
            cur = None
        self._current = cur
        self._rebuild()

    def _rebuild(self) -> None:
        if not hasattr(self, "_current"):
            return
        slots = self._slots()
        shown = [self._slot_label(sl) for sl in slots]
        self._updating = True
        try:
            if shown != getattr(self, "_shown", None):
                while self.count():
                    self.removeTab(0)
                for i, (label, sl) in enumerate(zip(shown, slots)):
                    self.addTab(label)
                    # The keys that walk the strip, where the hand already
                    # is (Marco, 24-09: «un mensaje informativo cuando me
                    # acerque a modelo o lámina»).
                    if sl[0] == "new":
                        self.setTabToolTip(i, tr("New sheet"))
                    elif sl[0] == "model":
                        self.setTabToolTip(i, tr(
                            "Model — Ctrl+Tab goes to the sheet"))
                    else:
                        self.setTabToolTip(i, tr(
                            "Sheet — Ctrl+Tab goes back to the model; "
                            "Ctrl+PgUp / Ctrl+PgDown, the sheet before / "
                            "after"))
                self._shown = shown
            self._slot_list = slots
            want = ("model",) if self._current is None else ("sheet", self._current)
            self.setCurrentIndex(slots.index(want) if want in slots else 0)
        finally:
            self._updating = False

    def names(self) -> list:
        """«Model» and the sheet names — never the «+» tab."""
        return self._labels[:1 + len(self._names)]

    def current(self):
        """``None`` for the model, else the sheet index."""
        return self._current

    def plus_index(self):
        """The index of the «+» tab, or ``None`` without one."""
        return len(self._names) + 1 if self._has_new() else None

    # ---- clicks ---------------------------------------------------------------
    def _clicked(self, index: int) -> None:
        if self._updating or index < 0:
            return
        slots = getattr(self, "_slot_list", [])
        if index >= len(slots):
            return
        slot = slots[index]
        # Let QTabBar finish its press first (see the module docstring).
        QTimer.singleShot(0, lambda: self._dispatch_slot(slot))

    def _dispatch_slot(self, slot) -> None:
        kind = slot[0]
        if kind == "model":
            self._on_model()
        elif kind == "new":
            self._on_new()
        elif kind == "sheet":
            self._on_sheet(slot[1])

    def _dispatch(self, index: int) -> None:
        """A LOGICAL index: 0 the model, 1…n the sheets, then «+»."""
        if index == 0:
            self._on_model()
        elif index == self.plus_index():
            self._on_new()
        elif index <= len(self._names):
            self._on_sheet(index - 1)

    def click(self, index: int) -> None:
        """Programmatic click (tests): the same hand-over as the mouse,
        run right away, on the LOGICAL layout whatever is displayed."""
        self._dispatch(index)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        i = self.tabAt(event.pos())
        slots = getattr(self, "_slot_list", [])
        if (self._on_menu is not None and 0 <= i < len(slots)
                and slots[i][0] == "sheet"):
            self._on_menu(slots[i][1], event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)


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
        shown = fm.elidedText(self._full, Qt.ElideRight, max(self.width() - 4, 0))
        super().setText(shown)
        # Cut short, the whole line is one hover away (Marco, 23-09).
        self.setToolTip(self._full if shown != self._full else "")


class SheetStatusBar(QStatusBar):
    """A status bar whose left end is the Model | sheets strip and whose
    messages go to a label of its own, so the strip shares the row with
    the measurements box and never disappears behind a hint.

    ``showMessage(text)`` (no timeout) sets the standing text; a timed
    message replaces it for a while and then the standing text comes back
    — a plain QStatusBar leaves the bar empty after a timed message."""

    def __init__(self, parent, on_model, on_sheet, on_new=None,
                 on_menu=None) -> None:
        super().__init__(parent)
        self.tabs = SheetTabs(self, on_model, on_sheet, on_new, on_menu)
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
        self.addPermanentWidget(self._msg, 10)
        # An empty filler takes what the capped message leaves, so the
        # strip and the message stay glued to the LEFT (without it the
        # bar's own leading spacer pushed them toward the middle — Marco,
        # 2026-09-15: «debería estar alineado a la izquierda»).
        self._filler = QWidget(self)
        self.addPermanentWidget(self._filler, 1)
        # A menu entry's description (its status tip) reaches the bar
        # through Qt's C++ showMessage, which never calls the override
        # below: it went to QStatusBar's own message area, hidden behind
        # our widgets, so hovering a menu showed nothing (0.5.7, #213).
        # Qt still announces it, and the announcement goes to our label.
        self.messageChanged.connect(self._on_qt_message)

    #: The message never takes more than this share of the bar, so the
    #: right end stays clear for the coordinates and the VCB (Marco,
    #: 2026-09-15: «que no llegue hasta el otro extremo derecho»). It was
    #: half; the tool's name moved into the hint (23-09) and freed its own
    #: label, and the hint, now longer by that name, gets that room.
    MESSAGE_SHARE = 0.6

    #: The sheet strip's share of the bar before its tabs fold.
    TABS_SHARE = 0.3

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._msg.setMaximumWidth(max(120, int(self.width() * self.MESSAGE_SHARE)))
        self.tabs.set_budget(max(200, int(self.width() * self.TABS_SHARE)))

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

    def _on_qt_message(self, text: str) -> None:
        """A status tip (a menu entry being hovered) while it lasts; the
        standing text again when it clears."""
        if text:
            self._timer.stop()
            self._msg.setText(text)
        else:
            self._msg.setText(self._base)
