# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What every tree of the side tray has in common.

The Browser (Model 3D) and the Layers tab are the same kind of list, and
some of their manners are nobody's in particular: the strip the columns
button stands in, the alternate tone of the rows, a press on a cell that
acts at once and leaves the selection as it was, dragging rows with a
picture of them and the place they land on outlined, and the menu of
columns that stays open while its switches are flipped.

A new tree of the tray inherits from :class:`SideTree` and says only what
a drop lands on and what it does — :meth:`drop_target`,
:meth:`drop_items`, :meth:`drop_text` and :meth:`apply_drop` — instead of
writing the drag, the cells and the strip again.
"""
from __future__ import annotations

from PySide6.QtCore import (QEvent, QPoint, QRect, QRectF, Qt, QTimer)
from PySide6.QtGui import (QColor, QCursor, QDrag, QPainter, QPalette, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QMenu, QStyle,
                               QStyleOptionHeader, QToolButton, QTreeWidget,
                               QWidget)

from core.i18n import tr


class _HeaderButton(QToolButton):
    """The columns button, in a strip of its own at the tree's right edge,
    level with the header: the columns scroll, stretch and move under the
    header beside it, and it stays put. Drawn as a header section — the
    same face as the columns, after the header's own last line — so it
    reads as part of the header, not as a stray number on the first row."""

    def paintEvent(self, _ev) -> None:          # noqa: N802 — Qt override
        opt = QStyleOptionHeader()
        opt.initFrom(self)
        opt.rect = self.rect()
        opt.orientation = Qt.Horizontal
        opt.position = QStyleOptionHeader.End
        # «+3» stays «+3» in a right-to-left interface (#1067).
        from views.rtl import isolate_ltr
        opt.text = isolate_ltr(self.text(), self)
        opt.textAlignment = Qt.AlignCenter
        if self.isDown():
            opt.state |= QStyle.State_Sunken
        else:
            opt.state |= QStyle.State_Raised
        if self.underMouse():
            opt.state |= QStyle.State_MouseOver
        p = QPainter(self)
        p.setFont(self.font())
        self.style().drawControl(QStyle.CE_Header, opt, p, self)
        # The line before it. The header's last column draws none on its
        # right (the style leaves the end of a header open), so the style
        # draws it here: a section beside this one, its right edge — the
        # separator every other column has — 1 px inside this button, the
        # rest clipped away. 2 px of clip: at 125 % display scaling one
        # logical pixel falls between device pixels and the line vanished.
        r = self.rect()
        edge = QStyleOptionHeader()
        edge.initFrom(self)
        edge.orientation = Qt.Horizontal
        edge.position = QStyleOptionHeader.Middle
        edge.state |= QStyle.State_Raised
        edge.rect = r.translated(-r.width() + 2, 0)
        p.setClipRect(0, 0, 2, r.height())
        self.style().drawControl(QStyle.CE_HeaderSection, edge, p, self)
        p.end()


class StayOpenMenu(QMenu):
    """A menu of switches that stays open while they are flipped — several
    columns on or off in one go — and closes on a click outside or Esc.
    An entry with the ``keep_open`` property set stays open too; one with
    the ``close`` property closes the menu, as a menu does by default."""

    @staticmethod
    def _stays(action) -> bool:
        return (action is not None and action.isEnabled()
                and not action.property("close")
                and (action.isCheckable()
                     or bool(action.property("keep_open"))))

    def mouseReleaseEvent(self, event) -> None:
        action = self.actionAt(event.position().toPoint())
        if self._stays(action):
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        action = self.activeAction()
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space)
                and self._stays(action)):
            action.trigger()
            event.accept()
            return
        super().keyPressEvent(event)


class _StripFiller(QWidget):
    """The strip kept at the tree's right for the columns button, below the
    button: painted as the rows beside it — their tone, alternate or not,
    and the selection's — so it reads as their end, not as a lighter band
    (the frame behind it shows the window's colour)."""

    def __init__(self, tree) -> None:
        super().__init__(tree)
        self._tree = tree

    def paintEvent(self, _ev) -> None:          # noqa: N802 — Qt override
        tree = self._tree
        pal = tree.palette()
        p = QPainter(self)
        p.fillRect(self.rect(), pal.color(QPalette.Base))
        vp = tree.viewport()
        y = 0
        odd = None
        while y < vp.height():
            index = tree.indexAt(QPoint(1, y))
            if not index.isValid():
                break
            rect = tree.visualRect(index)
            if rect.height() <= 0:
                break
            # The first row's parity once, then every row flips it.
            odd = tree.row_parity(index) if odd is None else not odd
            item = tree.itemFromIndex(index)
            if item is not None and item.isSelected():
                colour = pal.color(QPalette.Highlight)
            elif tree.alternatingRowColors() and odd:
                colour = pal.color(QPalette.AlternateBase)
            else:
                colour = pal.color(QPalette.Base)
            p.fillRect(0, rect.top(), self.width(), rect.height(), colour)
            y = rect.bottom() + 1
        p.end()


class SideTree(QTreeWidget):
    """A tree of the side tray: the columns button's strip, the alternate
    tone of the rows, cells that act without touching the selection, and
    rows dragged with their picture and their landing place marked.

    Subclasses fill in what a drop lands on (``drop_target``), the rows the
    outline covers (``drop_items``), the words that say it (``drop_text``)
    and what the drop does (``apply_drop``). A press on one of ``CELLS`` is
    answered by the panel's ``cell_clicked(item, column)``; the selection
    is left as it was, so a click on the eye of one of several selected
    rows acts on all of them."""

    #: How see-through the dragged rows are, and how many are drawn before
    #: the rest is only counted.
    DRAG_OPACITY = 0.55
    DRAG_ROWS = 6

    #: Hovering a folded row this long unfolds it while dragging.
    AUTO_EXPAND_MS = 600

    #: The cells a press acts on directly, without selecting their row.
    CELLS: tuple = ()

    #: Whether Delete (and Backspace) removes the current row here. The
    #: Browser leaves Delete to the view's own command: in the Layers tab it
    #: is the layer list's.
    DELETE_KEY = False

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        #: Width of the strip kept free at the right for the columns button.
        self.button_strip = 0
        self._filler = _StripFiller(self)
        self._filler.hide()
        # It repaints with the rows: scrolled, expanded, selected.
        self.viewport().installEventFilter(self)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        # Qt's line between rows says «between these two», which a drop here
        # never means: the row or the folder it files into is outlined
        # instead, and the words at the foot of the list say where.
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setAutoExpandDelay(self.AUTO_EXPAND_MS)
        #: While a drag is over the tree: ``(target,)`` — whatever the drop
        #: would land on; else ``None``.
        self.drop_hint: tuple | None = None
        #: A press on one of :attr:`CELLS` is the panel's until the button
        #: is let go: Qt never saw it, so a move with the button held would
        #: draw a selection box from wherever Qt's last press was — a few
        #: pixels of wobble while clicking an eye selected a run of rows.
        self._cell_press = False

    # ---- The strip of the columns button ---------------------------------
    def updateGeometries(self) -> None:          # noqa: N802 — Qt override
        """Qt lays the header over the whole viewport; a strip is then kept
        at the right for the columns button, header and rows one strip
        narrower."""
        super().updateGeometries()
        m = self.viewportMargins()
        if m.right() != self.button_strip:
            self.setViewportMargins(m.left(), m.top(), self.button_strip,
                                    m.bottom())
        vg = self.viewport().geometry()
        head = self.header()
        if not head.isHidden():
            head.setGeometry(vg.left(), vg.top() - m.top(), vg.width(),
                             m.top())
        b = self._columns_button()
        if b is not None:
            g = head.geometry()
            b.setGeometry(g.right() + 1, g.top(), b.width(), g.height())
        self._filler.setGeometry(vg.right() + 1, vg.top(), self.button_strip,
                                 vg.height())
        self._filler.setVisible(self.button_strip > 0)

    def _columns_button(self):
        """The panel's columns button: the Browser and Layers name it
        differently (it grew from each)."""
        b = getattr(self._panel, "columns_button", None)
        return b if b is not None else getattr(
            self._panel, "_columns_button", None)

    def row_parity(self, index) -> bool:
        """Whether the row of ``index`` is one the tree paints in the
        alternate tone: every other row shown, counted from the top. For
        the first row on screen, scrolling by rows already counts them."""
        if (self.verticalScrollMode() == QAbstractItemView.ScrollPerItem
                and index == self.indexAt(self.viewport().rect().topLeft())):
            return bool(self.verticalScrollBar().value() % 2)
        n = 0
        above = self.indexAbove(index)
        while above.isValid():
            n += 1
            above = self.indexAbove(above)
        return bool(n % 2)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.viewport() and ev.type() == QEvent.Paint:
            self._filler.update()
        return super().eventFilter(obj, ev)

    # ---- The cells that act at once --------------------------------------
    def _cell_click(self, event) -> bool:
        """Act on a plain left click on one of :attr:`CELLS`; whether it
        was one (and so taken)."""
        if (event.button() != Qt.LeftButton
                or event.modifiers() & (Qt.ControlModifier
                                        | Qt.ShiftModifier)):
            return False
        pos = event.position().toPoint()
        item = self.itemAt(pos)
        col = self.columnAt(pos.x())
        if item is None or col not in self.CELLS:
            return False
        event.accept()
        self._cell_press = True
        self.cell_clicked(item, col)
        return True

    def cell_clicked(self, item, column) -> None:
        """A press on one of :attr:`CELLS`: the panel answers it. The panel
        may defer the action and keep only what it read here — a press that
        rebuilds the rows would leave the item behind."""
        self._panel.cell_clicked(item, column)

    def mousePressEvent(self, event) -> None:    # noqa: N802 — Qt override
        if not self._cell_click(event):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — Qt override
        # Two quick clicks on a cell are two clicks (off and on again), not
        # a double click for the list to select or rename the row with.
        if not self._cell_click(event):
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:         # noqa: N802 — Qt override
        if self._cell_press:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:      # noqa: N802 — Qt override
        if self._cell_press:
            self._cell_press = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---- Delete ----------------------------------------------------------
    def _is_delete(self, event) -> bool:
        return (self.DELETE_KEY
                and event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
                and self.state() != QAbstractItemView.EditingState)

    def event(self, event) -> bool:
        # Delete belongs to the list while it has the focus, not to a
        # window shortcut.
        if event.type() == QEvent.ShortcutOverride and self._is_delete(event):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if self._is_delete(event):
            event.accept()
            self._panel.delete_row()
            return
        super().keyPressEvent(event)

    # ---- Dragging --------------------------------------------------------
    def drag_rows(self):
        """The rows the drag carries, in the order they are shown."""
        rows = [it for it in self.selectedItems()
                if self.visualItemRect(it).isValid()]
        rows.sort(key=lambda it: self.visualItemRect(it).top())
        return rows

    def drag_pixmap(self):
        """The rows being dragged, as they look in the list, stacked with
        no gaps between them (however far apart they sit) and see-through,
        so the rows under the pointer still show. ``(pixmap, rows)``."""
        vp = self.viewport()
        rows = self.drag_rows()
        shown = rows[:self.DRAG_ROWS]
        if not shown:
            return QPixmap(), []
        width = vp.width()
        heights = [self.visualItemRect(it).height() for it in shown]
        extra = len(rows) - len(shown)
        foot = heights[0] if extra else 0
        dpr = vp.devicePixelRatioF()
        pm = QPixmap(round(width * dpr), round((sum(heights) + foot) * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setOpacity(self.DRAG_OPACITY)
        y = 0
        for it, h in zip(shown, heights):
            r = self.visualItemRect(it)
            p.drawPixmap(0, y, vp.grab(QRect(0, r.top(), width, h)))
            y += h
        p.setOpacity(1.0)
        accent = QColor(QApplication.palette().highlight().color())
        if extra:
            p.setPen(QApplication.palette().text().color())
            p.drawText(QRectF(0, y, width, foot), Qt.AlignCenter,
                       tr("+{n} more", n=extra))
        p.setPen(QPen(accent, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(0.75, 0.75, width - 1.5, y + foot - 1.5),
                          3, 3)
        p.end()
        return pm, rows

    def startDrag(self, actions) -> None:
        pm, rows = self.drag_pixmap()
        if not rows:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(rows))
        drag.setPixmap(pm)
        # Held where it was picked up: the pointer stays on the row it
        # pressed, within the first row's height.
        at = self.viewport().mapFromGlobal(QCursor.pos())
        first = self.visualItemRect(rows[0])
        drag.setHotSpot(QPoint(max(0, min(at.x(), first.width() - 1)),
                               max(0, min(at.y() - first.top(),
                                          first.height() - 1))))
        drag.exec(Qt.MoveAction)
        self._clear_hint()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self:
            super().dragMoveEvent(event)             # auto-scroll, unfold
            event.setDropAction(Qt.MoveAction)
            event.accept()
            hint = (self.drop_target(event.position().toPoint()),)
            if hint != self.drop_hint:
                self.drop_hint = hint
                self.viewport().update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        super().dragLeaveEvent(event)
        self._clear_hint()

    def _clear_hint(self) -> None:
        if self.drop_hint is not None:
            self.drop_hint = None
            self.viewport().update()

    # ---- Where a drop lands ----------------------------------------------
    def drop_target(self, pos):
        """What a drop at ``pos`` (viewport coordinates) lands on."""
        return None

    def drop_items(self, token):
        """The rows the outline covers for ``token``."""
        return []

    def drop_text(self, token) -> str:
        """What the pill at the foot of the list says for ``token``."""
        return ""

    def apply_drop(self, token, rows) -> None:
        """Do the drop: move the rows in the document, then rebuild."""

    def drop_rect(self, token):
        """Where the drop lands, in viewport coordinates: the rows of
        ``token``, full width; the whole list for nothing (out of every
        folder, at the top level)."""
        if token is None:
            return self.viewport().rect()
        rect = QRect()
        for item in self.drop_items(token):
            if item is None or item.isHidden():
                continue
            r = self.visualItemRect(item)
            if r.isValid():
                rect = rect.united(r)
        if rect.isNull():
            return QRect()
        vp = self.viewport().rect()
        return QRect(vp.left(), rect.top(), vp.width(), rect.height())

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.drop_hint is None:
            return
        token = self.drop_hint[0]
        accent = QColor(QApplication.palette().highlight().color())
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.drop_rect(token)
        if rect.isValid():
            tint = QColor(accent)
            tint.setAlpha(45)
            p.setBrush(tint)
            p.setPen(QPen(accent, 2.0))
            p.drawRoundedRect(QRectF(rect).adjusted(1.5, 1.5, -1.5, -1.5),
                              4, 4)
        # Said in words too, at the foot of the list: with rows inside rows
        # the outline alone can leave a doubt.
        text = self.drop_text(token)
        if text:
            fm = p.fontMetrics()
            vp = self.viewport().rect()
            w = fm.horizontalAdvance(text) + 16
            h = fm.height() + 6
            pill = QRectF(vp.right() - w - 6, vp.bottom() - h - 6, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            p.drawRoundedRect(pill, h / 2, h / 2)
            p.setPen(QApplication.palette().highlightedText().color())
            p.drawText(pill, Qt.AlignCenter, text)
        p.end()

    def dropEvent(self, event) -> None:
        self._clear_hint()
        if event.source() is not self:
            event.ignore()
            return
        token = self.drop_target(event.position().toPoint())
        rows = self.drag_rows()
        # Accepted, but as nothing for Qt to do: the panel moves the rows in
        # the document and rebuilds the tree from it.
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
        QTimer.singleShot(0, lambda: self.apply_drop(token, rows))
