# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Right-to-left interface (Arabic, #1067).

With a right-to-left language Qt mirrors the layouts, the menus and the
standard widgets once the application's layout direction is set; what it
cannot know is in here:

* the 3D view and the sheet canvas are drawings, not text: they stay as
  they are in every language (see ``keep_ltr``);
* numbers, units and coordinates are typed and read left to right, so the
  number fields stay left to right inside the mirrored interface;
* ``QToolButton.setArrowType`` draws its arrow on the left whatever the
  direction (and over the text when the button is narrow): ``set_arrow``
  draws it as an icon, which Qt does mirror, pointing the reading way.

Nothing here changes a left-to-right interface: every helper does exactly
what the code did before unless the application runs right to left.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QStyle,
                               QStyleOption)


def is_rtl_ui() -> bool:
    """Whether the interface runs right to left."""
    app = QApplication.instance()
    return app is not None and app.layoutDirection() == Qt.RightToLeft


class _NumbersLeftToRight(QObject):
    """Every number field (spin boxes: lengths, angles, coordinates, scales,
    percentages…) laid out left to right, as numbers are written."""

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt override
        if (event.type() == QEvent.Polish
                and isinstance(obj, QAbstractSpinBox)
                and not obj.testAttribute(Qt.WA_SetLayoutDirection)):
            obj.setLayoutDirection(Qt.LeftToRight)
        return False


def apply_language_direction(app, lang: str) -> bool:
    """At start-up, after the language is chosen: mirror the interface for
    a right-to-left ``lang``. Returns whether it did. A left-to-right
    language leaves the application exactly as it was."""
    from core.i18n import is_rtl
    if not is_rtl(lang):
        return False
    app.setLayoutDirection(Qt.RightToLeft)
    if getattr(app, "_rtl_numbers", None) is None:
        app._rtl_numbers = _NumbersLeftToRight(app)
        app.installEventFilter(app._rtl_numbers)
    return True


def keep_ltr(*widgets) -> None:
    """Keep ``widgets`` (and what they hold) left to right in a mirrored
    interface: drawings and numbers. A no-op left to right."""
    if not is_rtl_ui():
        return
    for w in widgets:
        if w is not None:
            w.setLayoutDirection(Qt.LeftToRight)


_MIRRORED = {Qt.LeftArrow: Qt.RightArrow, Qt.RightArrow: Qt.LeftArrow}
_PRIMITIVE = {Qt.DownArrow: QStyle.PE_IndicatorArrowDown,
              Qt.UpArrow: QStyle.PE_IndicatorArrowUp,
              Qt.LeftArrow: QStyle.PE_IndicatorArrowLeft,
              Qt.RightArrow: QStyle.PE_IndicatorArrowRight}


def _arrow_icon(button, arrow) -> QIcon:
    size = button.iconSize()
    ratio = max(1.0, button.devicePixelRatioF())
    pm = QPixmap(int(size.width() * ratio), int(size.height() * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    opt = QStyleOption()
    opt.initFrom(button)
    opt.rect = QRect(0, 0, size.width(), size.height())
    p = QPainter(pm)
    button.style().drawPrimitive(_PRIMITIVE[arrow], opt, p, button)
    p.end()
    return QIcon(pm)


def set_arrow(button, arrow) -> None:
    """``button.setArrowType(arrow)``, and in a mirrored interface the
    arrow as an icon at the reading start of the text — a «right» arrow
    (folded, go on) pointing left there."""
    if not button.isRightToLeft():
        button.setArrowType(arrow)
        return
    button.setArrowType(Qt.NoArrow)
    if arrow == Qt.NoArrow:
        button.setIcon(QIcon())
        return
    button.setIcon(_arrow_icon(button, _MIRRORED.get(arrow, arrow)))


def visual_rect(widget, outer: QRect, rect: QRect) -> QRect:
    """``rect``, laid out left to right inside ``outer``, where it goes in
    ``widget``'s direction (mirrored inside ``outer`` right to left)."""
    if not widget.isRightToLeft():
        return rect
    return QStyle.visualRect(Qt.RightToLeft, outer, rect)


def isolate_ltr(text: str, widget=None) -> str:
    """``text`` (``+3``, ``-12.5 m``) kept in its left-to-right order inside
    a mirrored interface — a Unicode isolate; unchanged left to right."""
    rtl = widget.isRightToLeft() if widget is not None else is_rtl_ui()
    return f"⁦{text}⁩" if rtl and text else text
