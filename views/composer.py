# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The sheet composer window — QGIS-composer-shaped (docs/composer-plan.md).

C2: several model-view frames per sheet, text / image / title-block items,
drag with snapping (page edges, margins, centre, other items), corner
resize, a composition manager (N sheets per document, persisted in the
.igz), and composer-scoped undo. The canvas is a ``QGraphicsScene`` whose
units are paper MILLIMETRES; every item paints itself in mm-space through
the same code the PDF export uses, so screen and paper always agree.
"""
from __future__ import annotations

import datetime
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QKeySequence,
                           QPageLayout, QPageSize, QPainter, QPdfWriter,
                           QPen, QShortcut)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGraphicsItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from core.composition import (COMMON_SCALES, PAPER_SIZES_MM, RENDER_DPI,
                              AddItemCommand, BarraEscala, Cajetin,
                              ComposerHistory, Composicion, CotaItem,
                              EditItemCommand, FlechaNorte, FormaItem,
                              ImagenItem, Leyenda, MarcoVista,
                              RemoveItemCommand, TextoItem,
                              apply_frame_camera, snap_mm)
from core.i18n import tr

PT_TO_MM = 25.4 / 72.0
_HANDLE_MM = 3.0          # corner resize handle, in paper mm
_SNAP_MM = 2.0

#: Standard views offered as frame sources (label key → camera.set_view key).
_STD_VIEWS = (
    ("Top (plan)", "top"),
    ("Front", "front"),
    ("Back", "back"),
    ("Left", "left"),
    ("Right", "right"),
    ("Isometric", "iso"),
)


# ── mm-space painters (shared by canvas and PDF) ────────────────────────────

def _draw_text_mm(painter: QPainter, rect: QRectF, text: str, size_mm: float,
                  bold: bool = False, align=Qt.AlignLeft | Qt.AlignTop,
                  color: QColor = QColor(30, 36, 44),
                  italic: bool = False, family: str = "Sans Serif") -> None:
    """Draw *text* inside *rect* (mm units) at ``size_mm`` tall. Fonts don't
    take fractional-mm sizes, so set a large pixel size and scale the
    painter down — crisp at any output DPI."""
    if not text:
        return
    painter.save()
    font = QFont(family or "Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    font.setItalic(italic)
    painter.setFont(font)
    painter.setPen(color)
    s = size_mm / 100.0 * 0.75   # pixelSize≈cap height/0.75 — visual match
    painter.scale(s, s)
    painter.drawText(QRectF(rect.x() / s, rect.y() / s,
                            rect.width() / s, rect.height() / s),
                     int(align | Qt.TextWordWrap), text)
    painter.restore()


def frame_title_text(frame: MarcoVista) -> str:
    """The automatic title: view name — scale («Planta — 1:100»)."""
    key = frame.view_key
    if key.startswith("scene:"):
        name = key[6:]
    elif key.startswith("std:"):
        name = {k: tr(lbl) for lbl, k in _STD_VIEWS}.get(key[4:], key[4:])
    else:
        name = tr("View")
    return f"{name} — 1:{frame.scale_n:g}"


def paint_frame_mm(painter: QPainter, frame: MarcoVista,
                   image: Optional[QImage], hlr=None) -> None:
    r = QRectF(0, 0, frame.w_mm, frame.h_mm)
    if frame.style == "vectorial":
        painter.fillRect(r, QColor(255, 255, 255))
        if hlr is not None and len(hlr):
            pen = QPen(QColor(30, 36, 44))
            pen.setWidthF(0.22)          # a 0.2 mm technical pen
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.save()
            painter.setClipRect(r)
            for x0, y0, x1, y1 in hlr:
                painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            painter.restore()
        else:
            _draw_text_mm(painter, r.adjusted(2, 2, -2, -2),
                          tr("Update the view to render"), 3.5,
                          color=QColor(140, 150, 160))
    elif image is not None and not image.isNull():
        painter.drawImage(r, image)
    else:
        painter.fillRect(r, QColor(245, 246, 248))
        _draw_text_mm(painter, r.adjusted(2, 2, -2, -2),
                      tr("Update the view to render"), 3.5,
                      color=QColor(140, 150, 160))
    if frame.grid_m > 0:
        # the graticule: model-metre grid at the frame's scale
        from core.composition import model_height_for_frame
        model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
        step = frame.grid_m * frame.h_mm / model_h
        if step >= 2.0:                     # below 2 mm it's just moiré
            gpen = QPen(QColor(90, 140, 190, 120))
            gpen.setWidthF(0.12)
            painter.save()
            painter.setClipRect(r)
            painter.setPen(gpen)
            x = step
            while x < frame.w_mm:
                painter.drawLine(QPointF(x, 0), QPointF(x, frame.h_mm))
                x += step
            y = step
            while y < frame.h_mm:
                painter.drawLine(QPointF(0, y), QPointF(frame.w_mm, y))
                y += step
            painter.restore()
    pen = QPen(QColor(40, 46, 54))
    pen.setWidthF(0.3)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r)
    if frame.show_title:
        _draw_text_mm(painter,
                      QRectF(0, frame.h_mm + 1.2, frame.w_mm, 8.0),
                      frame_title_text(frame), 4.2, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignTop)


def paint_scalebar_mm(painter: QPainter, sb: BarraEscala) -> None:
    """Alternating black/white boxes + metre labels + the 1:N caption."""
    seg_mm = sb.segment_mm()
    seg_m = sb.segment_m()
    bar_h = 2.4
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.25)
    painter.setPen(pen)
    for i in range(sb.segments):
        r = QRectF(i * seg_mm, 0, seg_mm, bar_h)
        painter.setBrush(QBrush(QColor(30, 36, 44)) if i % 2 == 0
                         else QBrush(QColor(255, 255, 255)))
        painter.drawRect(r)
    for i in range(sb.segments + 1):
        v = i * seg_m
        label = f"{v:g}"
        _draw_text_mm(painter,
                      QRectF(i * seg_mm - 12, bar_h + 0.8, 24, 4),
                      label, 2.6, align=Qt.AlignHCenter | Qt.AlignTop)
    _draw_text_mm(painter,
                  QRectF(0, bar_h + 4.6, sb.w_mm, 4),
                  tr("metres — scale 1:{n}", n=f"{sb.scale_n:g}"), 2.6,
                  align=Qt.AlignHCenter | Qt.AlignTop)


def paint_norte_mm(painter: QPainter, n: FlechaNorte) -> None:
    """Circle + needle + N, rotated to the project north."""
    sz = n.size_mm
    c = sz / 2.0
    painter.save()
    painter.translate(c, c)
    painter.rotate(n.angle_deg)
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.35)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(0, 0), c * 0.92, c * 0.92)
    from PySide6.QtGui import QPolygonF
    r = c * 0.78
    painter.setBrush(QBrush(QColor(30, 36, 44)))
    painter.drawPolygon(QPolygonF([QPointF(0, -r), QPointF(r * 0.28, r * 0.35),
                                   QPointF(0, r * 0.12)]))
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawPolygon(QPolygonF([QPointF(0, -r), QPointF(-r * 0.28, r * 0.35),
                                   QPointF(0, r * 0.12)]))
    painter.restore()
    _draw_text_mm(painter, QRectF(0, sz * 0.30, sz, sz * 0.4), "N",
                  sz * 0.30, bold=True,
                  align=Qt.AlignHCenter | Qt.AlignTop)


def paint_leyenda_mm(painter: QPainter, le: Leyenda) -> None:
    r = QRectF(0, 0, le.w_mm, le.h_mm)
    painter.fillRect(r, QColor(255, 255, 255))
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(0.3)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r)
    _draw_text_mm(painter, QRectF(2, 1.4, le.w_mm - 4, 5), le.title,
                  3.2, bold=True)
    y = 7.5
    rows = le.rows or [tr("(no layers)")]
    for name in rows:
        painter.setBrush(QBrush(QColor(226, 232, 238)))
        painter.setPen(QPen(QColor(30, 36, 44), 0.2))
        painter.drawRect(QRectF(2.2, y + 0.8, 4.0, 3.2))
        _draw_text_mm(painter, QRectF(8, y + 0.7, le.w_mm - 10, 5),
                      name, 2.8)
        y += 5.5


def paint_forma_mm(painter: QPainter, f: FormaItem) -> None:
    pen = QPen(QColor(30, 36, 44))
    pen.setWidthF(f.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(226, 232, 238))
                     if f.fill and f.kind in ("rect", "elipse")
                     else Qt.NoBrush)
    r = QRectF(0, 0, f.w_mm, f.h_mm)
    if f.kind == "rect":
        painter.drawRect(r)
    elif f.kind == "elipse":
        painter.drawEllipse(r)
    else:
        a = QPointF(0, f.h_mm if f.invert else 0)
        b = QPointF(f.w_mm, 0 if f.invert else f.h_mm)
        painter.drawLine(a, b)
        if f.kind == "flecha":
            import math as _math
            from PySide6.QtGui import QPolygonF
            ang = _math.atan2(b.y() - a.y(), b.x() - a.x())
            L = max(2.5, f.stroke_mm * 7)
            for da in (_math.radians(153), -_math.radians(153)):
                painter.drawLine(b, QPointF(
                    b.x() + L * _math.cos(ang + da),
                    b.y() + L * _math.sin(ang + da)))


def paint_cota_mm(painter: QPainter, ct: CotaItem) -> None:
    """Architect-style dimension: the line runs ``sep_mm`` off the measured
    points along their normal (LayOut-style), tied back with extension
    lines; oblique ticks / arrows / bare ends; centred label of the REAL
    model distance (paper length × N)."""
    import math as _math
    from PySide6.QtGui import QBrush, QPolygonF
    nx, ny = ct.normal()
    s = ct.sep_mm
    a = QPointF(0, 0)
    b = QPointF(ct.dx_mm, ct.dy_mm)
    a2 = QPointF(nx * s, ny * s)
    b2 = QPointF(ct.dx_mm + nx * s, ct.dy_mm + ny * s)
    color = QColor(ct.color)
    pen = QPen(color)
    pen.setWidthF(ct.stroke_mm)
    painter.setPen(pen)
    if abs(s) > 0.05:
        # extension lines: small gap at the measured point, small overshoot
        # past the dimension line (the drafting convention LayOut follows)
        sign = 1.0 if s >= 0 else -1.0
        gap, over = 1.0 * sign, 1.2 * sign
        for p, p2 in ((a, a2), (b, b2)):
            painter.drawLine(
                QPointF(p.x() + nx * gap, p.y() + ny * gap),
                QPointF(p2.x() + nx * over, p2.y() + ny * over))
    painter.drawLine(a2, b2)
    ang = _math.atan2(ct.dy_mm, ct.dx_mm)
    if ct.ends == "arrow":
        L = max(1.8, ct.stroke_mm * 6)
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        for pt, direction in ((a2, ang), (b2, ang + _math.pi)):
            tip = pt
            base = _math.radians(12)
            painter.drawPolygon(QPolygonF([
                tip,
                QPointF(tip.x() + L * _math.cos(direction + base),
                        tip.y() + L * _math.sin(direction + base)),
                QPointF(tip.x() + L * _math.cos(direction - base),
                        tip.y() + L * _math.sin(direction - base))]))
        painter.restore()
    elif ct.ends != "none":
        tick = 1.6
        for pt in (a2, b2):
            painter.drawLine(
                QPointF(pt.x() - tick * _math.cos(ang + _math.radians(45)),
                        pt.y() - tick * _math.sin(ang + _math.radians(45))),
                QPointF(pt.x() + tick * _math.cos(ang + _math.radians(45)),
                        pt.y() + tick * _math.sin(ang + _math.radians(45))))
    mid = QPointF((a2.x() + b2.x()) / 2, (a2.y() + b2.y()) / 2)
    painter.save()
    painter.translate(mid)
    deg = _math.degrees(ang)
    if deg > 90 or deg < -90:
        deg += 180                      # keep the label readable
    painter.rotate(deg)
    _draw_text_mm(painter, QRectF(-40, -ct.offset_mm - ct.text_mm, 80,
                                  ct.text_mm * 1.3),
                  ct.label(), ct.text_mm,
                  align=Qt.AlignHCenter | Qt.AlignTop, color=color)
    painter.restore()


def paint_text_mm(painter: QPainter, item: TextoItem) -> None:
    size_mm = item.size_pt * PT_TO_MM
    rect = QRectF(0, 0, item.w_mm, size_mm * 1.35 * (item.text.count("\n") + 3))
    align = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
             "right": Qt.AlignRight}.get(item.align, Qt.AlignLeft)
    _draw_text_mm(painter, rect, item.text, size_mm, item.bold,
                  align=align | Qt.AlignTop, color=QColor(item.color),
                  italic=item.italic, family=item.family)


def paint_image_mm(painter: QPainter, item: ImagenItem,
                   image: Optional[QImage]) -> None:
    r = QRectF(0, 0, item.w_mm, item.h_mm)
    if image is not None and not image.isNull():
        painter.drawImage(r, image)
    else:
        painter.fillRect(r, QColor(240, 240, 242))
        pen = QPen(QColor(170, 176, 184))
        pen.setWidthF(0.25)
        painter.setPen(pen)
        painter.drawRect(r)
        painter.drawLine(r.topLeft(), r.bottomRight())
        painter.drawLine(r.topRight(), r.bottomLeft())


def paint_cajetin_mm(painter: QPainter, c: Cajetin) -> None:
    r = QRectF(0, 0, c.w_mm, c.h_mm)
    painter.fillRect(r, QColor(255, 255, 255))
    heavy = QPen(QColor(30, 36, 44))
    heavy.setWidthF(0.5)
    light = QPen(QColor(30, 36, 44))
    light.setWidthF(0.2)
    rows = len(Cajetin.FIELDS)
    row_h = c.h_mm / rows
    label_w = min(28.0, c.w_mm * 0.3)
    painter.setPen(light)
    for i in range(1, rows):
        y = i * row_h
        painter.drawLine(QPointF(0, y), QPointF(c.w_mm, y))
    painter.drawLine(QPointF(label_w, 0), QPointF(label_w, c.h_mm))
    for i, (label, attr) in enumerate(Cajetin.FIELDS):
        y = i * row_h
        _draw_text_mm(painter,
                      QRectF(1.2, y + row_h * 0.18, label_w - 2, row_h),
                      label, row_h * 0.38, bold=True,
                      color=QColor(90, 98, 108))
        _draw_text_mm(painter,
                      QRectF(label_w + 1.5, y + row_h * 0.12,
                             c.w_mm - label_w - 3, row_h),
                      getattr(c, attr), row_h * 0.52)
    painter.setPen(heavy)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(r)


# ── Canvas items ────────────────────────────────────────────────────────────

class _SheetItem(QGraphicsItem):
    """A sheet item on the canvas: movable, snappable, corner-resizable.
    Wraps one dataclass (``model`` with x_mm/y_mm and usually w_mm/h_mm)."""

    RESIZABLE = True

    def __init__(self, composer: "ComposerWindow", model) -> None:
        super().__init__()
        self.composer = composer
        self.model = model
        self.setPos(model.x_mm, model.y_mm)
        self.setZValue(getattr(model, "z", 0.0))
        # A locked item stays visible and selectable (to unlock it) but
        # cannot be dragged or resized — QGIS's composer habit.
        self.setFlag(QGraphicsItem.ItemIsMovable,
                     not getattr(model, "locked", False))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self._press_state: Optional[dict] = None
        self._resizing = False

    # -- arrange / lock (context menu) ----------------------------------------
    def contextMenuEvent(self, event) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        front = menu.addAction(tr("Bring to front"))
        up = menu.addAction(tr("Raise"))
        down = menu.addAction(tr("Lower"))
        back = menu.addAction(tr("Send to back"))
        menu.addSeparator()
        lock = menu.addAction(tr("Unlock")
                              if getattr(self.model, "locked", False)
                              else tr("Lock"))
        chosen = menu.exec(event.screenPos())
        if chosen is front:
            self.composer.z_shift(self, "front")
        elif chosen is up:
            self.composer.z_shift(self, "raise")
        elif chosen is down:
            self.composer.z_shift(self, "lower")
        elif chosen is back:
            self.composer.z_shift(self, "back")
        elif chosen is lock:
            self.composer.toggle_lock(self)
        event.accept()

    # -- geometry ------------------------------------------------------------
    def size_mm(self) -> tuple[float, float]:
        return self.model.w_mm, getattr(self.model, "h_mm", 12.0)

    def boundingRect(self) -> QRectF:
        w, h = self.size_mm()
        pad = _HANDLE_MM
        return QRectF(-0.5, -0.5, w + pad + 0.5, h + pad + 0.5)

    def _paint_selection(self, painter: QPainter) -> None:
        if not self.isSelected():
            return
        w, h = self.size_mm()
        pen = QPen(QColor(58, 110, 165), 0.35, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(0, 0, w, h))
        if self.RESIZABLE:
            painter.setBrush(QBrush(QColor(58, 110, 165)))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(w - _HANDLE_MM / 2, h - _HANDLE_MM / 2,
                                    _HANDLE_MM, _HANDLE_MM))

    # -- interaction ---------------------------------------------------------
    def _on_resize_handle(self, pos: QPointF) -> bool:
        w, h = self.size_mm()
        return (self.RESIZABLE
                and abs(pos.x() - w) <= _HANDLE_MM
                and abs(pos.y() - h) <= _HANDLE_MM)

    def mousePressEvent(self, event) -> None:
        self._press_state = {
            k: getattr(self.model, k)
            for k in ("x_mm", "y_mm", "w_mm", "h_mm")
            if hasattr(self.model, k)}
        self._resizing = (not getattr(self.model, "locked", False)
                          and self._on_resize_handle(event.pos()))
        if self._resizing:
            event.accept()
            self.setSelected(True)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            w = max(10.0, event.pos().x())
            h = max(6.0, event.pos().y())
            targets_x = self.composer.snap_targets_x(exclude=self)
            targets_y = self.composer.snap_targets_y(exclude=self)
            w = snap_mm(self.pos().x() + w, targets_x, _SNAP_MM) - self.pos().x()
            h = snap_mm(self.pos().y() + h, targets_y, _SNAP_MM) - self.pos().y()
            self.prepareGeometryChange()
            self.model.w_mm = w
            if hasattr(self.model, "h_mm"):
                self.model.h_mm = h
            self.composer.on_item_geometry(self)
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_resizing = self._resizing
        self._resizing = False
        super().mouseReleaseEvent(event)
        if self._press_state is None:
            return
        current = {k: getattr(self.model, k) for k in self._press_state}
        if current != self._press_state:
            self.composer.push_geometry_edit(self.model, current,
                                             self._press_state)
        self._press_state = None
        if was_resizing:
            self.composer.on_item_geometry(self, final=True)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            w, h = self.size_mm()
            x = snap_mm(value.x(), self.composer.snap_targets_x(exclude=self),
                        _SNAP_MM)
            x = snap_mm(x + w, self.composer.snap_targets_x(exclude=self),
                        _SNAP_MM) - w
            y = snap_mm(value.y(), self.composer.snap_targets_y(exclude=self),
                        _SNAP_MM)
            y = snap_mm(y + h, self.composer.snap_targets_y(exclude=self),
                        _SNAP_MM) - h
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.model.x_mm = self.pos().x()
            self.model.y_mm = self.pos().y()
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.composer.on_selection_changed()
        return super().itemChange(change, value)


class FrameItem(_SheetItem):
    def boundingRect(self) -> QRectF:
        r = super().boundingRect()
        if self.model.show_title:
            r.setHeight(r.height() + 9.0)
        return r

    def paint(self, painter, option, widget=None) -> None:
        paint_frame_mm(painter, self.model,
                       self.composer.render_cache.get(id(self.model)),
                       hlr=self.composer.hlr_cache.get(id(self.model)))
        self._paint_selection(painter)


class ScaleBarItem(_SheetItem):
    RESIZABLE = False

    def boundingRect(self) -> QRectF:
        return QRectF(-12.5, -0.5, self.model.w_mm + 25.0, 12.0)

    def paint(self, painter, option, widget=None) -> None:
        paint_scalebar_mm(painter, self.model)
        self._paint_selection(painter)


class TextItem(_SheetItem):
    RESIZABLE = True

    def size_mm(self):
        size_mm = self.model.size_pt * PT_TO_MM
        lines = self.model.text.count("\n") + 1
        return self.model.w_mm, max(6.0, size_mm * 1.4 * lines)

    def paint(self, painter, option, widget=None) -> None:
        paint_text_mm(painter, self.model)
        self._paint_selection(painter)


class ImageItem(_SheetItem):
    def paint(self, painter, option, widget=None) -> None:
        paint_image_mm(painter, self.model,
                       self.composer.image_cache(self.model.path))
        self._paint_selection(painter)


class CajetinItem(_SheetItem):
    def paint(self, painter, option, widget=None) -> None:
        paint_cajetin_mm(painter, self.model)
        self._paint_selection(painter)


class NorteItem(_SheetItem):
    def paint(self, painter, option, widget=None) -> None:
        paint_norte_mm(painter, self.model)
        self._paint_selection(painter)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            self.prepareGeometryChange()
            self.model.size_mm = max(8.0, min(event.pos().x(),
                                              event.pos().y()))
            self.update()
            return
        super(_SheetItem, self).mouseMoveEvent(event)


class LeyendaItem(_SheetItem):
    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            self.prepareGeometryChange()
            self.model.w_mm = max(25.0, event.pos().x())
            self.update()
            return
        super(_SheetItem, self).mouseMoveEvent(event)

    def paint(self, painter, option, widget=None) -> None:
        paint_leyenda_mm(painter, self.model)
        self._paint_selection(painter)


class FormaCanvasItem(_SheetItem):
    def paint(self, painter, option, widget=None) -> None:
        paint_forma_mm(painter, self.model)
        self._paint_selection(painter)


class CotaCanvasItem(_SheetItem):
    _sep_dragging = False

    def size_mm(self):
        return self.model.w_mm, self.model.h_mm

    def _line_mid(self) -> tuple[float, float]:
        nx, ny = self.model.normal()
        s = self.model.sep_mm
        return (self.model.dx_mm / 2 + nx * s, self.model.dy_mm / 2 + ny * s)

    def boundingRect(self) -> QRectF:
        m = self.model
        nx, ny = m.normal()
        pad = m.offset_mm + m.text_mm + 4
        xs = (0.0, m.dx_mm, nx * m.sep_mm, m.dx_mm + nx * m.sep_mm)
        ys = (0.0, m.dy_mm, ny * m.sep_mm, m.dy_mm + ny * m.sep_mm)
        return QRectF(min(xs) - pad, min(ys) - pad,
                      max(xs) - min(xs) + 2 * pad,
                      max(ys) - min(ys) + 2 * pad)

    def _on_resize_handle(self, pos: QPointF) -> bool:
        return (abs(pos.x() - self.model.dx_mm) <= _HANDLE_MM
                and abs(pos.y() - self.model.dy_mm) <= _HANDLE_MM)

    def _on_sep_handle(self, pos: QPointF) -> bool:
        mx, my = self._line_mid()
        return (abs(pos.x() - mx) <= _HANDLE_MM
                and abs(pos.y() - my) <= _HANDLE_MM)

    def mouseMoveEvent(self, event) -> None:
        if self._sep_dragging:
            nx, ny = self.model.normal()
            self.prepareGeometryChange()
            self.model.sep_mm = (event.pos().x() * nx + event.pos().y() * ny)
            self.update()
            return
        if self._resizing:
            self.prepareGeometryChange()
            self.model.dx_mm = event.pos().x()
            self.model.dy_mm = event.pos().y()
            self.update()
            return
        super(_SheetItem, self).mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._press_state = {k: getattr(self.model, k)
                             for k in ("x_mm", "y_mm", "dx_mm", "dy_mm",
                                       "sep_mm", "anchor_uid", "a_world",
                                       "b_world")}
        locked = getattr(self.model, "locked", False)
        self._sep_dragging = (not locked
                              and self._on_sep_handle(event.pos()))
        self._resizing = (not locked and not self._sep_dragging
                          and self._on_resize_handle(event.pos()))
        if self._sep_dragging or self._resizing:
            event.accept()
            self.setSelected(True)
            return
        super(_SheetItem, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._sep_dragging = False
        # Moving the cota or one of its measured points BY HAND means the
        # user wants it off the geometry: break the model anchor (the next
        # reprojection would otherwise snap it right back). Undoable — the
        # anchor fields ride in the same _press_state snapshot.
        if self._press_state is not None and self.model.anchored:
            moved = any(getattr(self.model, k) != self._press_state[k]
                        for k in ("x_mm", "y_mm", "dx_mm", "dy_mm"))
            if moved:
                self.model.anchor_uid = ""
                self.model.a_world = None
                self.model.b_world = None
        super().mouseReleaseEvent(event)

    def _paint_selection(self, painter: QPainter) -> None:
        if not self.isSelected():
            return
        anchored = QColor(41, 158, 92)       # green: tied to the model
        free = QColor(58, 110, 165)          # blue: paper-only points
        painter.setBrush(QBrush(anchored if self.model.anchored else free))
        painter.setPen(Qt.NoPen)
        mx, my = self._line_mid()
        for px, py in ((0.0, 0.0), (self.model.dx_mm, self.model.dy_mm),
                       (mx, my)):
            painter.drawRect(QRectF(px - 1.2, py - 1.2, 2.4, 2.4))

    def paint(self, painter, option, widget=None) -> None:
        paint_cota_mm(painter, self.model)
        self._paint_selection(painter)


class ComposerCanvasView(QGraphicsView):
    """The page view: placement clicks/drags for the left-toolbar tools,
    live mm cursor readout, Ctrl+wheel zoom (QGIS habits)."""

    def __init__(self, canvas, composer) -> None:
        super().__init__(canvas)
        self.composer = composer
        self.setMouseTracking(True)
        self._drag_start = None
        self._press_vp = None          # viewport px of the press (click vs drag)
        self._ignore_release = False   # release of a finishing second click
        self._second_pt = None         # cota: measured points fixed, placing
        self._preview = None           #       the dimension line (sep phase)
        self._snap_marker = None       # green dot over a frame vertex/edge
        self._last_hit = None          # richest snap hit of the last _snapped
        self._hit_a = None             # snap hits of the two measured points
        self._hit_b = None             # (world anchors for the cota)
        # Tools that define a segment/rectangle take EITHER a drag or two
        # clicks (click the first vertex, move, click the second) — the
        # click-click habit of the model's dimension tool must work here too.
        self._two_point = {m for m, _i, _t, drag in composer.TOOLS if drag}

    def _snapped(self, pos):
        """Snap *pos* (scene mm) to the nearest frame geometry point when a
        drawing tool is armed. Returns (QPointF, hit). Threshold scales with
        zoom so it's ~7 px on screen."""
        from PySide6.QtCore import QPointF
        if self.composer.tool_mode == "select":
            return pos, False
        if self._second_pt is not None:
            # sep phase: the points are fixed; the dimension line goes where
            # the cursor says — snapping would fight the offset.
            self._clear_snap_marker()
            return pos, False
        thr_mm = 7.0 / max(self.transform().m11(), 1e-6)
        hit = self.composer.nearest_snap_point(pos.x(), pos.y(), thr_mm)
        self._last_hit = hit
        if hit is None:
            self._clear_snap_marker()
            return pos, False
        self._show_snap_marker(hit[0], hit[1])
        return QPointF(hit[0], hit[1]), True

    def _show_snap_marker(self, x, y):
        from PySide6.QtGui import QBrush
        if self._snap_marker is None:
            self._snap_marker = self.scene().addEllipse(
                QRectF(), QPen(QColor(255, 255, 255), 0.3),
                QBrush(QColor(41, 158, 92)))     # elementary Lime/green
            self._snap_marker.setZValue(100001)
        r = 1.6
        self._snap_marker.setRect(QRectF(x - r, y - r, 2 * r, 2 * r))

    def _clear_snap_marker(self):
        if self._snap_marker is not None:
            self.scene().removeItem(self._snap_marker)
            self._snap_marker = None

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            f = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.scale(f, f)
            self.composer.update_zoom_label()
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        mode = self.composer.tool_mode
        if mode != "select" and event.button() == Qt.LeftButton:
            pos, _ = self._snapped(self.mapToScene(event.position().toPoint()))
            if self._second_pt is not None:
                # Third click of a dimension: fixes the line separation.
                self._finish_cota(pos)
                self._ignore_release = True
                event.accept()
                return
            if self._drag_start is not None:
                # Second click of a click-move-click placement finishes it
                # (unless it lands on the first point — keep waiting).
                if (event.position().toPoint() - self._press_vp
                        ).manhattanLength() >= 4:
                    if mode == "cota":
                        self._enter_sep_phase(pos)
                    else:
                        self._finish_placement(pos)
                    self._ignore_release = True
                event.accept()
                return
            self._drag_start = pos
            self._hit_a = self._last_hit
            self._press_vp = event.position().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        raw = self.mapToScene(event.position().toPoint())
        pos, _ = self._snapped(raw)
        self.composer.update_cursor_label(pos.x(), pos.y())
        if self._second_pt is not None:
            self._update_sep_preview(pos)
            event.accept()
            return
        if self._drag_start is not None:
            if self._preview is None:
                pen = QPen(QColor(58, 110, 165), 0.3, Qt.DashLine)
                self._preview = self.scene().addRect(QRectF(), pen)
                self._preview.setZValue(100000)
            r = QRectF(self._drag_start, pos).normalized()
            self._preview.setRect(r)
            event.accept()
            return
        super().mouseMoveEvent(event)

    # ---- dimension sep phase (points fixed, placing the line) ---------------

    def _cota_sep(self, pos) -> float:
        """Signed ⟂ distance from the measured segment to *pos* (page mm)."""
        import math as _math
        a, b = self._drag_start, self._second_pt
        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = _math.hypot(dx, dy)
        if length < 1e-9:
            return 0.0
        nx, ny = -dy / length, dx / length
        return (pos.x() - a.x()) * nx + (pos.y() - a.y()) * ny

    def _enter_sep_phase(self, second) -> None:
        self._second_pt = second
        self._hit_b = self._last_hit
        self._clear_snap_marker()
        if self._preview is not None:
            self.scene().removeItem(self._preview)
            self._preview = None
        self._update_sep_preview(second)

    def _update_sep_preview(self, pos) -> None:
        import math as _math
        from PySide6.QtGui import QPainterPath
        from PySide6.QtWidgets import QGraphicsPathItem
        if self._preview is None or not isinstance(
                self._preview, QGraphicsPathItem):
            if self._preview is not None:
                self.scene().removeItem(self._preview)
            pen = QPen(QColor(58, 110, 165), 0.3, Qt.DashLine)
            self._preview = QGraphicsPathItem()
            self._preview.setPen(pen)
            self._preview.setZValue(100000)
            self.scene().addItem(self._preview)
        a, b = self._drag_start, self._second_pt
        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = _math.hypot(dx, dy)
        nx, ny = ((-dy / length, dx / length) if length > 1e-9 else (0.0, -1.0))
        s = self._cota_sep(pos)
        path = QPainterPath()
        for p in (a, b):
            path.moveTo(p)
            path.lineTo(p.x() + nx * s, p.y() + ny * s)
        path.moveTo(a.x() + nx * s, a.y() + ny * s)
        path.lineTo(b.x() + nx * s, b.y() + ny * s)
        self._preview.setPath(path)

    def _finish_cota(self, pos) -> None:
        start, second = self._drag_start, self._second_pt
        sep = self._cota_sep(pos)
        # Both points snapped to geometry of the SAME frame → the cota
        # anchors to those 3D model points and follows the model.
        anchors = None
        if (self._hit_a is not None and self._hit_b is not None
                and self._hit_a[3] is self._hit_b[3]):
            anchors = (self._hit_a[3], self._hit_a[2], self._hit_b[2])
        self._drag_start = None
        self._second_pt = None
        self._press_vp = None
        self._hit_a = self._hit_b = None
        if self._preview is not None:
            self.scene().removeItem(self._preview)
            self._preview = None
        self._clear_snap_marker()
        self.composer.place_tool(start.x(), start.y(),
                                 second.x(), second.y(), sep_mm=sep,
                                 anchors=anchors)

    def mouseReleaseEvent(self, event) -> None:
        if self._ignore_release and event.button() == Qt.LeftButton:
            self._ignore_release = False
            event.accept()
            return
        if self._second_pt is not None and event.button() == Qt.LeftButton:
            event.accept()                # sep phase ends on the next press
            return
        if self._drag_start is not None and event.button() == Qt.LeftButton:
            # A press-and-release on the same spot with a two-point tool is
            # the FIRST click of click-move-click: keep the rubber band (and
            # the snapping) alive until the second click.
            if (self.composer.tool_mode in self._two_point
                    and (event.position().toPoint() - self._press_vp
                         ).manhattanLength() < 4):
                event.accept()
                return
            end, _ = self._snapped(self.mapToScene(event.position().toPoint()))
            if self.composer.tool_mode == "cota":
                self._enter_sep_phase(end)
            else:
                self._finish_placement(end)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _finish_placement(self, end) -> None:
        start = self._drag_start
        self._drag_start = None
        self._press_vp = None
        self._hit_a = self._hit_b = None
        if self._preview is not None:
            self.scene().removeItem(self._preview)
            self._preview = None
        self._clear_snap_marker()
        self.composer.place_tool(start.x(), start.y(), end.x(), end.y())

    def cancel_placement(self) -> None:
        """Drop an in-progress two-point placement (Esc / tool switch)."""
        self._drag_start = None
        self._second_pt = None
        self._press_vp = None
        self._ignore_release = False
        self._hit_a = self._hit_b = None
        if self._preview is not None:
            self.scene().removeItem(self._preview)
            self._preview = None
        self._clear_snap_marker()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self._drag_start is not None:
            self.cancel_placement()
            event.accept()
            return
        super().keyPressEvent(event)


# ── The window ──────────────────────────────────────────────────────────────

class ComposerWindow(QMainWindow):
    """Page canvas on the left, composition manager + properties on the
    right. Compositions live in ``scene.compositions`` and persist in the
    .igz; every mutation goes through the composer's own undo history."""

    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self.setWindowFlag(Qt.Window, True)
        self._window = main_window
        self.render_cache: dict[int, QImage] = {}
        self.hlr_cache: dict[int, object] = {}
        self.snap_cache: dict[int, object] = {}   # frame → page-mm snap pts
        self._images: dict[str, QImage] = {}
        self._updating = False
        self.history = ComposerHistory(on_change=self._on_history_change)

        scene = main_window.viewport.scene
        if not scene.compositions:
            comp = Composicion()
            comp.frames.append(comp.default_frame())
            scene.compositions.append(comp)
        self.comp: Composicion = scene.compositions[0]

        self.setWindowTitle(tr("Sheet composer"))
        self.resize(1280, 840)
        self.tool_mode = "select"
        self.canvas = QGraphicsScene(self)
        view = ComposerCanvasView(self.canvas, self)
        view.setRenderHints(QPainter.Antialiasing
                            | QPainter.SmoothPixmapTransform)
        view.setBackgroundBrush(QColor(70, 76, 84))
        self._view = view
        self._build_tools_toolbar()

        panel = self._build_panel()
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QSplitter
        split = QSplitter(Qt.Horizontal)
        split.addWidget(view)
        split.addWidget(panel)
        split.setStretchFactor(0, 1)      # the canvas absorbs resizes
        split.setStretchFactor(1, 0)
        split.setCollapsible(0, False)
        saved = QSettings().value("composer/panel_width", 300, int)
        split.setSizes([max(self.width() - saved, 400), saved])
        split.splitterMoved.connect(
            lambda *_a: QSettings().setValue(
                "composer/panel_width", split.sizes()[1]))
        self._splitter = split
        self.setCentralWidget(split)

        self._pos_label = QLabel("")
        self._zoom_label = QLabel("")
        self.statusBar().addPermanentWidget(self._pos_label)
        self.statusBar().addPermanentWidget(self._zoom_label)
        self.update_zoom_label()

        QShortcut(QKeySequence.Undo, self, activated=self._on_undo)
        QShortcut(QKeySequence.Redo, self, activated=self._on_redo)
        QShortcut(QKeySequence.Delete, self, activated=self._on_delete_item)

        self._rebuild_canvas()

    # ---- left tools toolbar (QGIS-style) -------------------------------------
    #: mode → (icon key, tooltip, drag?) — drag tools take a press-release
    #: extent, click tools place at the click point.
    TOOLS = (
        ("select", "select", "Select / move items", False),
        ("vista", "comp_vista", "Add a model-view frame (two clicks or drag)", True),
        ("texto", "text", "Add a text block", False),
        ("imagen", "image", "Add an image", False),
        ("cajetin", "comp_cajetin", "Add the title block", False),
        ("escala", "comp_escala", "Add a graphic scale bar", False),
        ("norte", "comp_norte", "Add a north arrow", False),
        ("leyenda", "comp_leyenda", "Add the layer legend", False),
        ("linea", "line", "Draw a line (two clicks or drag)", True),
        ("flecha", "comp_flecha", "Draw an arrow (two clicks or drag)", True),
        ("rect", "rectangle", "Draw a rectangle (two clicks or drag)", True),
        ("elipse", "circle", "Draw an ellipse (two clicks or drag)", True),
        ("cota", "dimension", "Draw a dimension (two points + separation)", True),
    )

    def _build_tools_toolbar(self) -> None:
        from PySide6.QtGui import QAction, QActionGroup
        from PySide6.QtWidgets import QToolBar
        from views.icons import tool_icon
        tb = QToolBar(tr("Composer tools"), self)
        tb.setOrientation(Qt.Vertical)
        tb.setMovable(False)
        group = QActionGroup(self)
        group.setExclusive(True)
        self._tool_actions = {}
        for mode, icon_key, tip, _drag in self.TOOLS:
            act = QAction(tool_icon(icon_key), tr(tip), self)
            act.setCheckable(True)
            act.setChecked(mode == "select")
            act.triggered.connect(
                lambda _c, m=mode: self._set_tool_mode(m))
            group.addAction(act)
            tb.addAction(act)
            self._tool_actions[mode] = act
        self.addToolBar(Qt.LeftToolBarArea, tb)

    def _set_tool_mode(self, mode: str) -> None:
        if hasattr(self, "_view"):
            self._view.cancel_placement()
        self.tool_mode = mode
        if mode == "imagen":
            # the image tool needs its file first; place at margins
            self._on_add_image()
            self._set_tool_mode("select")
            self._tool_actions["select"].setChecked(True)

    def place_tool(self, x0: float, y0: float, x1: float, y1: float,
                   sep_mm: float = 0.0, anchors=None) -> None:
        """A click (or drag) landed on the page with a placement tool
        armed: create the item there, through the history. ``anchors``
        (cota only) is ``(frame, a_world, b_world)`` when both measured
        points snapped to the same frame's geometry."""
        mode = self.tool_mode
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        x = min(x0, x1)
        y = min(y0, y1)
        item = None
        if mode == "vista":
            item = MarcoVista(x_mm=x, y_mm=y,
                              w_mm=max(w, 60.0), h_mm=max(h, 50.0))
        elif mode == "texto":
            item = TextoItem(x_mm=x0, y_mm=y0, text=tr("Text"))
        elif mode == "cajetin":
            if self.comp.cajetin is None:
                self._on_add_cajetin()
        elif mode == "escala":
            n = self.comp.frames[0].scale_n if self.comp.frames else 100.0
            item = BarraEscala(x_mm=x0, y_mm=y0, scale_n=n)
        elif mode == "norte":
            item = FlechaNorte(x_mm=x0, y_mm=y0)
        elif mode == "leyenda":
            item = Leyenda(x_mm=x0, y_mm=y0,
                           rows=[ly.name for ly in
                                 self._scene().layers if ly.visible])
        elif mode in ("linea", "flecha", "rect", "elipse"):
            kind = {"linea": "linea", "flecha": "flecha",
                    "rect": "rect", "elipse": "elipse"}[mode]
            invert = (x1 < x0) != (y1 < y0)
            item = FormaItem(kind=kind, x_mm=x, y_mm=y,
                             w_mm=max(w, 2.0), h_mm=max(h, 2.0),
                             invert=invert if kind in ("linea", "flecha")
                             else False)
        elif mode == "cota":
            n = self.comp.frames[0].scale_n if self.comp.frames else 100.0
            item = CotaItem(x_mm=x0, y_mm=y0, dx_mm=x1 - x0, dy_mm=y1 - y0,
                            scale_n=n, sep_mm=sep_mm, offset_mm=0.8)
            if anchors is not None:
                frame, a_world, b_world = anchors
                if not frame.uid:
                    import uuid
                    frame.uid = uuid.uuid4().hex
                item.anchor_uid = frame.uid
                item.a_world = list(a_world)
                item.b_world = list(b_world)
                item.scale_n = frame.scale_n
        if item is not None:
            item.z = self._next_z()         # new items land on top (QGIS)
            self._pending_sel = item
            self.history.execute(AddItemCommand(self.comp, item))
        self.tool_mode = "select"
        self._tool_actions["select"].setChecked(True)

    def update_cursor_label(self, x: float, y: float) -> None:
        self._pos_label.setText(f"x: {x:.1f} mm  y: {y:.1f} mm")

    def update_zoom_label(self) -> None:
        z = self._view.transform().m11() if hasattr(self, "_view") else 1.0
        # 1 scene mm on screen ≈ z px; "100%" = fit-ish 3 px/mm baseline
        self._zoom_label.setText(f"{z * 100 / 3:.0f}%")

    # ---- panel ---------------------------------------------------------------
    def _build_panel(self) -> QWidget:
        from PySide6.QtWidgets import QListWidget, QTabWidget
        panel = QWidget()
        panel.setMinimumWidth(230)        # resizable via the splitter
        outer = QVBoxLayout(panel)

        self._tabs = QTabWidget()
        outer.addWidget(self._tabs, 1)

        # -- tab Diseño: page + sheet manager
        dis = QWidget()
        dis_lay = QVBoxLayout(dis)

        # Composition manager
        mgr = QHBoxLayout()
        self.comp_combo = QComboBox()
        self.comp_combo.setEditable(True)
        self.comp_combo.setInsertPolicy(QComboBox.NoInsert)
        self.comp_combo.setToolTip(tr("Type to rename the sheet"))
        self._reload_comp_combo()
        self.comp_combo.currentIndexChanged.connect(self._on_comp_switched)
        self.comp_combo.lineEdit().editingFinished.connect(self._on_comp_rename)
        mgr.addWidget(self.comp_combo, 1)
        for text, tip, slot in ((tr("+"), tr("New sheet"), self._on_comp_add),
                                (tr("⧉"), tr("Duplicate sheet"),
                                 self._on_comp_dup),
                                (tr("−"), tr("Delete sheet"),
                                 self._on_comp_del)):
            b = QPushButton(text)
            b.setFixedWidth(28)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            mgr.addWidget(b)
        dis_lay.addLayout(mgr)

        # Page
        form = QFormLayout()
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(list(PAPER_SIZES_MM))
        self.paper_combo.currentTextChanged.connect(self._on_page_changed)
        form.addRow(tr("Paper"), self.paper_combo)
        self.landscape_check = QCheckBox(tr("Landscape"))
        self.landscape_check.toggled.connect(self._on_page_changed)
        form.addRow("", self.landscape_check)
        dis_lay.addLayout(form)
        renum_btn = QPushButton(tr("Renumber sheets"))
        renum_btn.setToolTip(tr(
            "Set every title block's sheet number to L-01, L-02, … "
            "in manager order."))
        renum_btn.clicked.connect(self._on_renumber)
        dis_lay.addWidget(renum_btn)
        atlas_btn = QPushButton(tr("Export all sheets (PDF)…"))
        atlas_btn.clicked.connect(self._on_export_all)
        dis_lay.addWidget(atlas_btn)
        dis_lay.addStretch(1)
        self._tabs.addTab(dis, tr("Layout"))

        # -- tab Elementos: the item list
        from PySide6.QtWidgets import QListWidget
        ele = QWidget()
        ele_lay = QVBoxLayout(ele)
        self.items_list = QListWidget()
        self.items_list.itemSelectionChanged.connect(self._on_list_select)
        ele_lay.addWidget(self.items_list)
        self._tabs.addTab(ele, tr("Items"))

        # -- tab Propiedades: per-type pages
        self.props = QStackedWidget()
        self.props.addWidget(self._page_none())      # 0: nothing selected
        self.props.addWidget(self._page_frame())     # 1
        self.props.addWidget(self._page_text())      # 2
        self.props.addWidget(self._page_image())     # 3
        self.props.addWidget(self._page_cajetin())   # 4
        self.props.addWidget(self._page_scalebar())  # 5
        self.props.addWidget(self._page_norte())     # 6
        self.props.addWidget(self._page_leyenda())   # 7
        self.props.addWidget(self._page_forma())     # 8
        self.props.addWidget(self._page_cota())      # 9
        self._tabs.addTab(self.props, tr("Item properties"))

        refresh_btn = QPushButton(tr("Update all views"))
        refresh_btn.clicked.connect(self.refresh_all_frames)
        outer.addWidget(refresh_btn)
        export_btn = QPushButton(tr("Export PDF…"))
        export_btn.clicked.connect(self._on_export_pdf)
        outer.addWidget(export_btn)
        return panel

    def _page_none(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel(tr("Select an item to edit it. Drag to move; the "
                         "corner handle resizes. Items snap to margins "
                         "and to each other."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        lay.addWidget(hint)
        return w

    def _page_frame(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.view_combo = QComboBox()
        self.view_combo.currentIndexChanged.connect(self._on_frame_props)
        form.addRow(tr("View"), self.view_combo)
        self.scale_combo = QComboBox()
        self.scale_combo.setEditable(True)
        self.scale_combo.addItems([f"1:{n}" for n in COMMON_SCALES])
        self.scale_combo.currentTextChanged.connect(self._on_frame_props)
        form.addRow(tr("Scale"), self.scale_combo)
        self.fw_spin = QDoubleSpinBox()
        self.fw_spin.setRange(10.0, 2000.0)
        self.fw_spin.setSuffix(" mm")
        self.fw_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Frame width"), self.fw_spin)
        self.fh_spin = QDoubleSpinBox()
        self.fh_spin.setRange(10.0, 2000.0)
        self.fh_spin.setSuffix(" mm")
        self.fh_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Frame height"), self.fh_spin)
        self.style_combo = QComboBox()
        for label, key in ((tr("Shaded"), "sombreado"),
                           (tr("Technical (white + edges)"), "tecnico"),
                           (tr("Lines only"), "lineas"),
                           (tr("Vector (hidden lines removed)"), "vectorial")):
            self.style_combo.addItem(label, key)
        self.style_combo.currentIndexChanged.connect(self._on_frame_props)
        form.addRow(tr("Style"), self.style_combo)
        self.title_check = QCheckBox(tr("Title under the frame"))
        self.title_check.toggled.connect(self._on_frame_props)
        form.addRow("", self.title_check)
        self.grid_spin = QDoubleSpinBox()
        self.grid_spin.setRange(0.0, 1000.0)
        self.grid_spin.setSuffix(" m")
        self.grid_spin.setToolTip(tr("Coordinate grid spacing (0 = off)"))
        self.grid_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Grid"), self.grid_spin)
        btn = QPushButton(tr("Update view"))
        btn.clicked.connect(self._on_refresh_selected_frame)
        form.addRow(btn)
        dxf_btn = QPushButton(tr("Export view as DXF…"))
        dxf_btn.setToolTip(tr(
            "Write the hidden-line view as DXF lines in model units "
            "(metres) — open it in IngeCAD."))
        dxf_btn.clicked.connect(self._on_export_dxf)
        form.addRow(dxf_btn)
        return w

    def _page_text(self) -> QWidget:
        from PySide6.QtWidgets import QFontComboBox
        w = QWidget()
        form = QFormLayout(w)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setFixedHeight(70)
        self.text_edit.textChanged.connect(self._on_text_props)
        form.addRow(tr("Text"), self.text_edit)
        self.text_family = QFontComboBox()
        self.text_family.currentFontChanged.connect(self._on_text_props)
        form.addRow(tr("Font"), self.text_family)
        self.text_size = QDoubleSpinBox()
        self.text_size.setRange(4.0, 96.0)
        self.text_size.setSuffix(" pt")
        self.text_size.valueChanged.connect(self._on_text_props)
        form.addRow(tr("Size"), self.text_size)
        style_row = QHBoxLayout()
        self.text_bold = QCheckBox(tr("Bold"))
        self.text_bold.toggled.connect(self._on_text_props)
        style_row.addWidget(self.text_bold)
        self.text_italic = QCheckBox(tr("Italic"))
        self.text_italic.toggled.connect(self._on_text_props)
        style_row.addWidget(self.text_italic)
        form.addRow("", style_row)
        self.text_align = QComboBox()
        for label, key in ((tr("Left"), "left"), (tr("Center"), "center"),
                           (tr("Right"), "right")):
            self.text_align.addItem(label, key)
        self.text_align.currentIndexChanged.connect(self._on_text_props)
        form.addRow(tr("Alignment"), self.text_align)
        self.text_color_btn = QPushButton()
        self.text_color_btn.setFixedHeight(22)
        self.text_color_btn.clicked.connect(self._on_pick_text_color)
        form.addRow(tr("Colour"), self.text_color_btn)
        return w

    def _page_norte(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.norte_size = QDoubleSpinBox()
        self.norte_size.setRange(8.0, 80.0)
        self.norte_size.setSuffix(" mm")
        self.norte_size.valueChanged.connect(self._on_norte_props)
        form.addRow(tr("Size"), self.norte_size)
        self.norte_angle = QDoubleSpinBox()
        self.norte_angle.setRange(-180.0, 180.0)
        self.norte_angle.setSuffix(" °")
        self.norte_angle.valueChanged.connect(self._on_norte_props)
        form.addRow(tr("Angle"), self.norte_angle)
        return w

    def _page_leyenda(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.ley_title = QLineEdit()
        self.ley_title.editingFinished.connect(self._on_leyenda_props)
        form.addRow(tr("Title"), self.ley_title)
        btn = QPushButton(tr("Refresh layers"))
        btn.setToolTip(tr("Re-read the visible layers of the model."))
        btn.clicked.connect(self._on_leyenda_refresh)
        form.addRow(btn)
        return w

    def _page_forma(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.forma_stroke = QDoubleSpinBox()
        self.forma_stroke.setRange(0.1, 3.0)
        self.forma_stroke.setSingleStep(0.05)
        self.forma_stroke.setSuffix(" mm")
        self.forma_stroke.valueChanged.connect(self._on_forma_props)
        form.addRow(tr("Line width"), self.forma_stroke)
        self.forma_fill = QCheckBox(tr("Fill"))
        self.forma_fill.toggled.connect(self._on_forma_props)
        form.addRow("", self.forma_fill)
        self.forma_invert = QCheckBox(tr("Flip diagonal"))
        self.forma_invert.toggled.connect(self._on_forma_props)
        form.addRow("", self.forma_invert)
        return w

    def _page_cota(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.cota_scale = QComboBox()
        self.cota_scale.setEditable(True)
        self.cota_scale.addItems([f"1:{n}" for n in COMMON_SCALES])
        self.cota_scale.currentTextChanged.connect(self._on_cota_props)
        form.addRow(tr("Scale"), self.cota_scale)
        self.cota_text = QLineEdit()
        self.cota_text.setPlaceholderText(tr("(automatic)"))
        self.cota_text.editingFinished.connect(self._on_cota_props)
        form.addRow(tr("Label"), self.cota_text)
        self.cota_sep = QDoubleSpinBox()
        self.cota_sep.setRange(-100.0, 100.0)
        self.cota_sep.setSingleStep(0.5)
        self.cota_sep.setSuffix(" mm")
        self.cota_sep.valueChanged.connect(self._on_cota_props)
        form.addRow(tr("Separation"), self.cota_sep)
        self.cota_text_mm = QDoubleSpinBox()
        self.cota_text_mm.setRange(1.0, 10.0)
        self.cota_text_mm.setSingleStep(0.2)
        self.cota_text_mm.setSuffix(" mm")
        self.cota_text_mm.valueChanged.connect(self._on_cota_props)
        form.addRow(tr("Text height"), self.cota_text_mm)
        self.cota_decimals = QDoubleSpinBox()
        self.cota_decimals.setRange(0, 4)
        self.cota_decimals.setDecimals(0)
        self.cota_decimals.valueChanged.connect(self._on_cota_props)
        form.addRow(tr("Decimals"), self.cota_decimals)
        self.cota_ends = QComboBox()
        for label, key in ((tr("Oblique ticks"), "tick"),
                           (tr("Arrows"), "arrow"),
                           (tr("None"), "none")):
            self.cota_ends.addItem(label, key)
        self.cota_ends.currentIndexChanged.connect(self._on_cota_props)
        form.addRow(tr("Ends"), self.cota_ends)
        self.cota_stroke = QDoubleSpinBox()
        self.cota_stroke.setRange(0.1, 1.5)
        self.cota_stroke.setSingleStep(0.05)
        self.cota_stroke.setSuffix(" mm")
        self.cota_stroke.valueChanged.connect(self._on_cota_props)
        form.addRow(tr("Line width"), self.cota_stroke)
        self.cota_color_btn = QPushButton()
        self.cota_color_btn.setFixedHeight(22)
        self.cota_color_btn.clicked.connect(self._on_pick_cota_color)
        form.addRow(tr("Colour"), self.cota_color_btn)
        return w

    def _page_image(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.img_label = QLabel("—")
        self.img_label.setWordWrap(True)
        form.addRow(tr("File"), self.img_label)
        btn = QPushButton(tr("Choose image…"))
        btn.clicked.connect(self._on_pick_image)
        form.addRow(btn)
        return w

    def _page_cajetin(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.caj_edits: dict[str, QLineEdit] = {}
        for label, attr in Cajetin.FIELDS:
            edit = QLineEdit()
            edit.editingFinished.connect(self._on_cajetin_props)
            self.caj_edits[attr] = edit
            form.addRow(label.capitalize(), edit)
        return w

    def _page_scalebar(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.sb_scale = QComboBox()
        self.sb_scale.setEditable(True)
        self.sb_scale.addItems([f"1:{n}" for n in COMMON_SCALES])
        self.sb_scale.currentTextChanged.connect(self._on_scalebar_props)
        form.addRow(tr("Scale"), self.sb_scale)
        self.sb_segments = QDoubleSpinBox()
        self.sb_segments.setRange(2, 10)
        self.sb_segments.setDecimals(0)
        self.sb_segments.valueChanged.connect(self._on_scalebar_props)
        form.addRow(tr("Segments"), self.sb_segments)
        return w

    # ---- composition manager -------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def _reload_comp_combo(self) -> None:
        self._updating = True
        self.comp_combo.clear()
        for c in self._scene().compositions:
            self.comp_combo.addItem(c.name)
        self.comp_combo.setCurrentIndex(
            self._scene().compositions.index(self.comp)
            if self.comp in self._scene().compositions else 0)
        self._updating = False

    def _on_comp_switched(self, idx: int) -> None:
        if self._updating or idx < 0:
            return
        comps = self._scene().compositions
        if 0 <= idx < len(comps):
            self.comp = comps[idx]
            self.history = ComposerHistory(on_change=self._on_history_change)
            self._rebuild_canvas()

    def _on_comp_rename(self) -> None:
        if self._updating:
            return
        name = self.comp_combo.currentText().strip()
        if name and name != self.comp.name:
            self.comp.name = name
            self._mark_dirty()
            self._reload_comp_combo()

    def _on_comp_add(self) -> None:
        comps = self._scene().compositions
        comp = Composicion(name=tr("Sheet {n}", n=len(comps) + 1))
        comp.frames.append(comp.default_frame())
        comps.append(comp)
        self.comp = comp
        self._mark_dirty()
        self._reload_comp_combo()
        self._rebuild_canvas()

    def _on_comp_dup(self) -> None:
        comps = self._scene().compositions
        dup = Composicion.from_dict(self.comp.to_dict())
        dup.name = self.comp.name + tr(" (copy)")
        comps.append(dup)
        self.comp = dup
        self._mark_dirty()
        self._reload_comp_combo()
        self._rebuild_canvas()

    def _on_comp_del(self) -> None:
        comps = self._scene().compositions
        if len(comps) <= 1:
            return
        if QMessageBox.question(
                self, tr("Delete sheet"),
                tr("Delete '{name}'?", name=self.comp.name)) \
                != QMessageBox.Yes:
            return
        comps.remove(self.comp)
        self.comp = comps[0]
        self._mark_dirty()
        self._reload_comp_combo()
        self._rebuild_canvas()

    # ---- canvas --------------------------------------------------------------
    def _rebuild_canvas(self) -> None:
        self._updating = True
        self.snap_cache.clear()
        self._reproject_anchored_cotas()
        self.canvas.clear()
        pw, ph = self.comp.page_size_mm()
        self.canvas.setSceneRect(-20, -20, pw + 40, ph + 40)
        shadow = self.canvas.addRect(2.0, 2.0, pw, ph, QPen(Qt.NoPen),
                                     QBrush(QColor(0, 0, 0, 70)))
        shadow.setZValue(-100003)
        page = self.canvas.addRect(0, 0, pw, ph,
                                   QPen(QColor(120, 128, 136), 0.3),
                                   QBrush(QColor(255, 255, 255)))
        page.setZValue(-100002)
        m = self.comp.margin_mm
        margin = self.canvas.addRect(m, m, pw - 2 * m, ph - 2 * m,
                                     QPen(QColor(190, 196, 202), 0.2,
                                          Qt.DashLine))
        margin.setZValue(-100001)

        for f in self.comp.frames:
            self.canvas.addItem(FrameItem(self, f))
        for t in self.comp.texts:
            self.canvas.addItem(TextItem(self, t))
        for i in self.comp.images:
            self.canvas.addItem(ImageItem(self, i))
        for sb in self.comp.scalebars:
            self.canvas.addItem(ScaleBarItem(self, sb))
        for n in self.comp.nortes:
            self.canvas.addItem(NorteItem(self, n))
        for le in self.comp.leyendas:
            self.canvas.addItem(LeyendaItem(self, le))
        for fo in self.comp.shapes:
            self.canvas.addItem(FormaCanvasItem(self, fo))
        for ct in self.comp.cotas:
            self.canvas.addItem(CotaCanvasItem(self, ct))
        if self.comp.cajetin is not None:
            self.canvas.addItem(CajetinItem(self, self.comp.cajetin))

        self.paper_combo.setCurrentText(self.comp.paper)
        self.landscape_check.setChecked(self.comp.landscape)
        self._refresh_items_list()
        self._updating = False
        self.on_selection_changed()

    def _selected_item(self) -> Optional[_SheetItem]:
        for it in self.canvas.selectedItems():
            if isinstance(it, _SheetItem):
                return it
        return None

    def on_selection_changed(self) -> None:
        if self._updating:
            return
        item = self._selected_item()
        self._updating = True
        try:
            if isinstance(item, FrameItem):
                self._reload_view_sources()
                f: MarcoVista = item.model
                idx = self.view_combo.findData(f.view_key)
                self.view_combo.setCurrentIndex(max(idx, 0))
                self.scale_combo.setCurrentText(f"1:{f.scale_n:g}")
                self.fw_spin.setValue(f.w_mm)
                self.fh_spin.setValue(f.h_mm)
                sidx = self.style_combo.findData(f.style)
                self.style_combo.setCurrentIndex(max(sidx, 0))
                self.title_check.setChecked(f.show_title)
                self.grid_spin.setValue(f.grid_m)
                self.props.setCurrentIndex(1)
            elif isinstance(item, TextItem):
                t: TextoItem = item.model
                if self.text_edit.toPlainText() != t.text:
                    self.text_edit.setPlainText(t.text)
                self.text_size.setValue(t.size_pt)
                self.text_bold.setChecked(t.bold)
                self.text_italic.setChecked(t.italic)
                from PySide6.QtGui import QFont as _QF
                self.text_family.setCurrentFont(_QF(t.family))
                aidx = self.text_align.findData(t.align)
                self.text_align.setCurrentIndex(max(aidx, 0))
                self.text_color_btn.setStyleSheet(
                    f"background: {t.color};")
                self.props.setCurrentIndex(2)
            elif isinstance(item, ImageItem):
                self.img_label.setText(item.model.path or "—")
                self.props.setCurrentIndex(3)
            elif isinstance(item, CajetinItem):
                for attr, edit in self.caj_edits.items():
                    edit.setText(getattr(item.model, attr))
                self.props.setCurrentIndex(4)
            elif isinstance(item, ScaleBarItem):
                self.sb_scale.setCurrentText(f"1:{item.model.scale_n:g}")
                self.sb_segments.setValue(item.model.segments)
                self.props.setCurrentIndex(5)
            elif isinstance(item, NorteItem):
                self.norte_size.setValue(item.model.size_mm)
                self.norte_angle.setValue(item.model.angle_deg)
                self.props.setCurrentIndex(6)
            elif isinstance(item, LeyendaItem):
                self.ley_title.setText(item.model.title)
                self.props.setCurrentIndex(7)
            elif isinstance(item, FormaCanvasItem):
                self.forma_stroke.setValue(item.model.stroke_mm)
                self.forma_fill.setChecked(item.model.fill)
                self.forma_invert.setChecked(item.model.invert)
                self.forma_invert.setVisible(
                    item.model.kind in ("linea", "flecha"))
                self.forma_fill.setVisible(
                    item.model.kind in ("rect", "elipse"))
                self.props.setCurrentIndex(8)
            elif isinstance(item, CotaCanvasItem):
                self.cota_scale.setCurrentText(f"1:{item.model.scale_n:g}")
                self.cota_text.setText(item.model.text)
                self.cota_sep.setValue(item.model.sep_mm)
                self.cota_text_mm.setValue(item.model.text_mm)
                self.cota_decimals.setValue(item.model.decimals)
                eidx = self.cota_ends.findData(item.model.ends)
                self.cota_ends.setCurrentIndex(max(eidx, 0))
                self.cota_stroke.setValue(item.model.stroke_mm)
                self.cota_color_btn.setStyleSheet(
                    f"background: {item.model.color};")
                self.props.setCurrentIndex(9)
            else:
                self.props.setCurrentIndex(0)
            if item is not None and hasattr(self, "_tabs"):
                self._tabs.setCurrentIndex(2)     # jump to properties
            self._sync_items_list(item)
        finally:
            self._updating = False

    # ---- snapping ------------------------------------------------------------
    def snap_targets_x(self, exclude=None) -> list[float]:
        pw, _ = self.comp.page_size_mm()
        m = self.comp.margin_mm
        out = [0.0, m, pw / 2, pw - m, pw]
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and it is not exclude:
                w, _h = it.size_mm()
                out += [it.pos().x(), it.pos().x() + w]
        return out

    def snap_targets_y(self, exclude=None) -> list[float]:
        _, ph = self.comp.page_size_mm()
        m = self.comp.margin_mm
        out = [0.0, m, ph / 2, ph - m, ph]
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and it is not exclude:
                _w, h = it.size_mm()
                out += [it.pos().y(), it.pos().y() + h]
        return out

    # ---- item mutations (all through the composer history) -------------------
    def push_geometry_edit(self, model, after: dict, before: dict) -> None:
        self.history.execute(EditItemCommand(model, after, before))

    def on_item_geometry(self, item: _SheetItem, final: bool = False) -> None:
        if isinstance(item, FrameItem) and final:
            self.render_cache.pop(id(item.model), None)
            self.hlr_cache.pop(id(item.model), None)
            self.snap_cache.pop(id(item.model), None)
            item.update()
        if isinstance(item, FrameItem) and not self._updating \
                and item is self._selected_item():
            self._updating = True
            self.fw_spin.setValue(item.model.w_mm)
            self.fh_spin.setValue(item.model.h_mm)
            self._updating = False

    def _on_history_change(self) -> None:
        self._mark_dirty()
        # Commands mutate the models; a rebuild keeps canvas and panel
        # honest. DEFERRED: the change may arrive mid mouse-release, and a
        # synchronous clear would destroy the item still handling the event.
        if getattr(self, "_pending_sel", None) is None:
            selected = self._selected_item()
            self._pending_sel = selected.model if selected else None
        QTimer.singleShot(0, self._rebuild_after_change)

    def _rebuild_after_change(self) -> None:
        self._rebuild_canvas()
        if getattr(self, "_pending_sel", None) is not None:
            for it in self.canvas.items():
                if isinstance(it, _SheetItem) and it.model is self._pending_sel:
                    it.setSelected(True)
                    break
        self._pending_sel = None

    def _mark_dirty(self) -> None:
        scene = self._scene()
        scene.version += 1
        if hasattr(self._window, "set_dirty"):
            self._window.set_dirty()

    def _on_undo(self) -> None:
        self.history.undo()

    def _on_redo(self) -> None:
        self.history.redo()

    def _on_delete_item(self) -> None:
        from PySide6.QtWidgets import (QApplication, QAbstractSpinBox,
                                       QLineEdit, QPlainTextEdit)
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QAbstractSpinBox)) \
                or isinstance(focus, QComboBox):
            return                      # Delete belongs to the text field
        item = self._selected_item()
        if item is None:
            return
        self.history.execute(RemoveItemCommand(self.comp, item.model))

    # ---- add items -----------------------------------------------------------
    def _on_add_frame(self) -> None:
        pw, ph = self.comp.page_size_mm()
        f = MarcoVista(x_mm=self.comp.margin_mm + 5 * len(self.comp.frames),
                       y_mm=self.comp.margin_mm + 5 * len(self.comp.frames),
                       w_mm=min(120.0, pw / 2), h_mm=min(90.0, ph / 2))
        f.z = self._next_z()
        self.history.execute(AddItemCommand(self.comp, f))

    def _on_add_text(self) -> None:
        t = TextoItem(x_mm=self.comp.margin_mm + 4,
                      y_mm=self.comp.margin_mm + 4,
                      text=tr("Text"))
        t.z = self._next_z()
        self.history.execute(AddItemCommand(self.comp, t))

    def _on_add_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Choose image…"), "",
            tr("Images (*.png *.jpg *.jpeg)"))
        if not path:
            return
        img = QImage(path)
        w_mm = 60.0
        h_mm = w_mm * (img.height() / img.width()) if img.width() else 40.0
        self.history.execute(AddItemCommand(self.comp, ImagenItem(
            x_mm=self.comp.margin_mm + 4, y_mm=self.comp.margin_mm + 4,
            w_mm=w_mm, h_mm=h_mm, path=path, z=self._next_z())))

    def _on_add_scalebar(self) -> None:
        n = self.comp.frames[0].scale_n if self.comp.frames else 100.0
        _pw, ph = self.comp.page_size_mm()
        self.history.execute(AddItemCommand(self.comp, BarraEscala(
            x_mm=self.comp.margin_mm + 4,
            y_mm=ph - self.comp.margin_mm - 12, scale_n=n,
            z=self._next_z())))

    def _on_add_cajetin(self) -> None:
        if self.comp.cajetin is not None:
            return
        c = self.comp.default_cajetin()
        c.fecha = datetime.date.today().strftime("%d/%m/%Y")
        if self.comp.frames:
            f = self.comp.frames[0]
            c.escala = f"1:{f.scale_n:g}"
        c.z = self._next_z()
        self.history.execute(AddItemCommand(self.comp, c))

    # ---- property edits ------------------------------------------------------
    def _current_scale_n(self) -> float:
        text = self.scale_combo.currentText().strip()
        if ":" in text:
            text = text.split(":", 1)[1]
        try:
            n = float(text.replace(",", "."))
        except ValueError:
            n = 100.0
        return n if n > 0 else 100.0

    def _on_page_changed(self, *_a) -> None:
        if self._updating:
            return
        self.comp.paper = self.paper_combo.currentText()
        self.comp.landscape = self.landscape_check.isChecked()
        self._mark_dirty()
        self._rebuild_canvas()

    # ---- arrange / lock ------------------------------------------------------
    def _next_z(self) -> float:
        """z for a NEW item: on top of everything already on the sheet."""
        zs = [getattr(m, "z", 0.0) for m in self.comp.all_items()]
        return (max(zs) + 1.0) if zs else 0.0

    def _normalize_z(self) -> None:
        """Re-number z as 0..N-1 in the current visual order — a visual
        no-op that gives the step operations clean integer neighbours."""
        for i, m in enumerate(sorted(self.comp.all_items(),
                                     key=lambda m: getattr(m, "z", 0.0))):
            m.z = float(i)

    def z_shift(self, item: "_SheetItem", op: str) -> None:
        """QGIS-style arrange: front / raise / lower / back, one undo step."""
        self._normalize_z()
        order = sorted(self.comp.all_items(),
                       key=lambda m: getattr(m, "z", 0.0))
        model = item.model
        # identity, not ==: dataclasses compare by value and two identical
        # items (say, two fresh text blocks) must not alias each other
        idx = next(i for i, m in enumerate(order) if m is model)
        if op == "front" and idx < len(order) - 1:
            new = order[-1].z + 1.0
        elif op == "back" and idx > 0:
            new = order[0].z - 1.0
        elif op == "raise" and idx < len(order) - 1:
            new = order[idx + 1].z + 0.5
        elif op == "lower" and idx > 0:
            new = order[idx - 1].z - 0.5
        else:
            return                          # already at that end
        self._pending_sel = model           # keep it selected after rebuild
        self.history.execute(EditItemCommand(model, {"z": new}))

    def toggle_lock(self, item: "_SheetItem") -> None:
        self._pending_sel = item.model
        self.history.execute(EditItemCommand(
            item.model,
            {"locked": not getattr(item.model, "locked", False)}))

    def _panel_edit(self, item: "_SheetItem", changes: dict) -> None:
        """A live property edit from the panel: one coalesced undo step,
        repainting just the touched item (no canvas rebuild mid-typing)."""
        model = item.model
        if all(getattr(model, k) == v for k, v in changes.items()):
            return
        item.prepareGeometryChange()
        self.history.execute(EditItemCommand(model, changes),
                             notify=False, coalesce=True)
        self._mark_dirty()
        item.update()

    def _on_frame_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, FrameItem):
            return
        self._panel_edit(item, {
            "view_key": self.view_combo.currentData() or "__current__",
            "scale_n": self._current_scale_n(),
            "w_mm": self.fw_spin.value(),
            "h_mm": self.fh_spin.value(),
            "style": self.style_combo.currentData() or "sombreado",
            "show_title": self.title_check.isChecked()})
        self.render_cache.pop(id(item.model), None)
        self.hlr_cache.pop(id(item.model), None)
        self.snap_cache.pop(id(item.model), None)

    def _on_text_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, TextItem):
            return
        self._panel_edit(item, {
            "text": self.text_edit.toPlainText(),
            "size_pt": self.text_size.value(),
            "bold": self.text_bold.isChecked()})

    def _on_pick_image(self) -> None:
        item = self._selected_item()
        if not isinstance(item, ImageItem):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Choose image…"), "",
            tr("Images (*.png *.jpg *.jpeg)"))
        if not path:
            return
        self.history.execute(EditItemCommand(item.model, {"path": path}))

    def _on_cajetin_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CajetinItem):
            return
        self._panel_edit(item, {attr: edit.text()
                                for attr, edit in self.caj_edits.items()})

    def _on_pick_text_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        item = self._selected_item()
        if not isinstance(item, TextItem):
            return
        col = QColorDialog.getColor(QColor(item.model.color), self,
                                    tr("Colour"))
        if col.isValid():
            self._panel_edit(item, {"color": col.name()})
            self.text_color_btn.setStyleSheet(f"background: {col.name()};")

    def _on_norte_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, NorteItem):
            return
        item.prepareGeometryChange()
        self._panel_edit(item, {"size_mm": self.norte_size.value(),
                                "angle_deg": self.norte_angle.value()})

    def _on_leyenda_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, LeyendaItem):
            return
        self._panel_edit(item, {"title": self.ley_title.text()})

    def _on_leyenda_refresh(self) -> None:
        item = self._selected_item()
        if not isinstance(item, LeyendaItem):
            return
        item.prepareGeometryChange()
        self._panel_edit(item, {"rows": [ly.name for ly in
                                         self._scene().layers if ly.visible]})

    def _on_forma_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, FormaCanvasItem):
            return
        self._panel_edit(item, {"stroke_mm": self.forma_stroke.value(),
                                "fill": self.forma_fill.isChecked(),
                                "invert": self.forma_invert.isChecked()})

    def _on_cota_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CotaCanvasItem):
            return
        text = self.cota_scale.currentText().strip()
        if ":" in text:
            text = text.split(":", 1)[1]
        try:
            n = float(text.replace(",", "."))
        except ValueError:
            n = item.model.scale_n
        item.prepareGeometryChange()
        self._panel_edit(item, {
            "scale_n": n if n > 0 else item.model.scale_n,
            "text": self.cota_text.text(),
            "sep_mm": self.cota_sep.value(),
            "text_mm": self.cota_text_mm.value(),
            "decimals": int(self.cota_decimals.value()),
            "ends": self.cota_ends.currentData() or "tick",
            "stroke_mm": self.cota_stroke.value()})

    def _on_pick_cota_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        item = self._selected_item()
        if not isinstance(item, CotaCanvasItem):
            return
        col = QColorDialog.getColor(QColor(item.model.color), self,
                                    tr("Colour"))
        if col.isValid():
            self._panel_edit(item, {"color": col.name()})
            self.cota_color_btn.setStyleSheet(f"background: {col.name()};")

    def _item_label(self, model) -> str:
        if isinstance(model, MarcoVista):
            return frame_title_text(model)
        if isinstance(model, TextoItem):
            first = model.text.split("\n")[0][:24] if model.text else "—"
            return tr("Text") + ": " + first
        if isinstance(model, ImagenItem):
            return tr("Image")
        if isinstance(model, BarraEscala):
            return tr("Scale bar") + f" 1:{model.scale_n:g}"
        if isinstance(model, FlechaNorte):
            return tr("North arrow")
        if isinstance(model, Leyenda):
            return model.title or tr("Legend")
        if isinstance(model, FormaItem):
            return {"linea": tr("Line"), "flecha": tr("Arrow"),
                    "rect": tr("Rectangle"),
                    "elipse": tr("Ellipse")}.get(model.kind, model.kind)
        if isinstance(model, CotaItem):
            return tr("Dimension") + " " + model.label()
        if isinstance(model, Cajetin):
            return tr("Title block")
        return type(model).__name__

    def _refresh_items_list(self) -> None:
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QListWidgetItem
        self.items_list.blockSignals(True)
        self.items_list.clear()
        # top of the stack first — the reading order of a layers panel
        for model in sorted(self.comp.all_items(),
                            key=lambda m: getattr(m, "z", 0.0),
                            reverse=True):
            label = self._item_label(model)
            if getattr(model, "locked", False):
                label = "🔒 " + label
            row = QListWidgetItem(label)
            row.setData(_Qt.UserRole, id(model))
            self.items_list.addItem(row)
        self.items_list.blockSignals(False)

    def _sync_items_list(self, item) -> None:
        from PySide6.QtCore import Qt as _Qt
        self.items_list.blockSignals(True)
        self.items_list.clearSelection()
        if item is not None:
            target = id(item.model)
            for i in range(self.items_list.count()):
                if self.items_list.item(i).data(_Qt.UserRole) == target:
                    self.items_list.setCurrentRow(i)
                    break
        self.items_list.blockSignals(False)

    def _on_list_select(self) -> None:
        from PySide6.QtCore import Qt as _Qt
        if self._updating:
            return
        rows = self.items_list.selectedItems()
        if not rows:
            return
        target = rows[0].data(_Qt.UserRole)
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and id(it.model) == target:
                self._updating = True
                self.canvas.clearSelection()
                self._updating = False
                it.setSelected(True)
                break

    def _on_scalebar_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, ScaleBarItem):
            return
        text = self.sb_scale.currentText().strip()
        if ":" in text:
            text = text.split(":", 1)[1]
        try:
            n = float(text.replace(",", "."))
        except ValueError:
            n = item.model.scale_n
        item.prepareGeometryChange()
        self._panel_edit(item, {"scale_n": n if n > 0 else item.model.scale_n,
                                "segments": int(self.sb_segments.value())})

    # ---- rendering -----------------------------------------------------------
    def image_cache(self, path: str) -> Optional[QImage]:
        if not path:
            return None
        if path not in self._images:
            self._images[path] = QImage(path)
        return self._images[path]

    def _reload_view_sources(self) -> None:
        self.view_combo.blockSignals(True)
        current = self.view_combo.currentData()
        self.view_combo.clear()
        self.view_combo.addItem(tr("Current view"), "__current__")
        for label, key in _STD_VIEWS:
            self.view_combo.addItem(tr(label), f"std:{key}")
        for sv in self._scene().saved_views:
            self.view_combo.addItem(tr("Scene: {name}", name=sv.name),
                                    f"scene:{sv.name}")
        idx = self.view_combo.findData(current)
        if idx >= 0:
            self.view_combo.setCurrentIndex(idx)
        self.view_combo.blockSignals(False)

    def _on_refresh_selected_frame(self) -> None:
        item = self._selected_item()
        if isinstance(item, FrameItem):
            self._on_frame_props()
            self.render_frame(item.model)
            item.update()

    def refresh_all_frames(self) -> None:
        for f in self.comp.frames:
            self.render_frame(f)
        for it in self.canvas.items():
            if isinstance(it, FrameItem):
                it.update()

    def _with_frame_camera(self, frame: MarcoVista, fn):
        """Run ``fn()`` with the live camera pointed at *frame* (exact
        scale), restoring camera, aspect, up and layer visibility after —
        the composer never disturbs the viewport."""
        vp = self._window.viewport
        cam = vp.camera
        scene = vp.scene
        saved_view = None
        if frame.view_key.startswith("scene:"):
            name = frame.view_key[6:]
            saved_view = next((sv for sv in scene.saved_views
                               if sv.name == name), None)
        keep = (cam.target, cam.distance, cam.yaw, cam.pitch, cam.fov_deg,
                cam.perspective, cam.aspect, cam.up,
                [(ly, ly.visible) for ly in scene.layers])
        try:
            apply_frame_camera(cam, frame, saved_view, scene)
            return fn()
        finally:
            (cam.target, cam.distance, cam.yaw, cam.pitch, cam.fov_deg,
             cam.perspective, cam.aspect, cam.up) = keep[:8]
            for ly, visible in keep[8]:
                ly.visible = visible
            vp.update()

    def frame_snap_points(self, frame: MarcoVista):
        """Visible geometry points of *frame*'s view — an ``(M, 2)`` array in
        PAGE millimetres paired with the same points in WORLD metres
        ``(M, 3)`` (the anchor data): every edge endpoint plus each edge's
        midpoint. Cached by frame id; computed from the same hidden-line
        pass the vector style uses, so a point only snaps where the drawing
        actually shows an edge.
        """
        import numpy as np
        cached = self.snap_cache.get(id(frame))
        if cached is not None:
            return cached
        from core.composition import model_height_for_frame
        from core.hlr import hlr_view

        def run():
            vp = self._window.viewport
            segs, world = hlr_view(vp.scene, vp.camera, return_world=True)
            if not len(segs):
                return np.empty((0, 2)), np.empty((0, 3))
            model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
            k = frame.h_mm / model_h
            half_h = model_h / 2.0
            half_w = half_h * (frame.w_mm / frame.h_mm)

            def to_page(mx, my):
                return (frame.x_mm + (mx + half_w) * k,
                        frame.y_mm + (half_h - my) * k)

            pts = []
            wpts = []
            for (x0, y0, x1, y1), (w0, w1) in zip(segs, world):
                pts.append(to_page(x0, y0))
                pts.append(to_page(x1, y1))
                pts.append(to_page((x0 + x1) / 2, (y0 + y1) / 2))  # midpoint
                wpts.extend((w0, w1, (w0 + w1) / 2))
            arr = np.array(pts)
            warr = np.array(wpts)
            # clip to the frame rectangle (points outside are off the sheet)
            m = ((arr[:, 0] >= frame.x_mm - 0.5)
                 & (arr[:, 0] <= frame.x_mm + frame.w_mm + 0.5)
                 & (arr[:, 1] >= frame.y_mm - 0.5)
                 & (arr[:, 1] <= frame.y_mm + frame.h_mm + 0.5))
            return arr[m], warr[m]

        pair = self._with_frame_camera(frame, run)
        self.snap_cache[id(frame)] = pair
        return pair

    def _frame_world_to_page(self, frame: MarcoVista, world_pts):
        """Project points in WORLD metres to PAGE millimetres through
        *frame*'s camera — the inverse trip of a snap hit."""
        import numpy as np
        from core.composition import model_height_for_frame
        from core.hlr import _to_cam, camera_basis

        def run():
            vp = self._window.viewport
            eye, right, up, fwd = camera_basis(vp.camera)
            cam = _to_cam(np.asarray(world_pts, dtype=np.float64),
                          eye, right, up, fwd)
            model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
            k = frame.h_mm / model_h
            half_h = model_h / 2.0
            half_w = half_h * (frame.w_mm / frame.h_mm)
            return [(frame.x_mm + (mx + half_w) * k,
                     frame.y_mm + (half_h - my) * k)
                    for mx, my in cam[:, :2]]

        return self._with_frame_camera(frame, run)

    def _reproject_anchored_cotas(self) -> None:
        """Anchored cotas follow the model: re-attach each 3D anchor to the
        nearest CURRENT snap point within a small paper tolerance (the
        wall moved → the cota moves with it, and the label re-measures),
        then reproject through the frame's camera so moving/rescaling the
        frame or changing its view keeps the cota true. Derived-state
        sync, like the render caches — never an undo step."""
        import numpy as np
        frames = {f.uid: f for f in self.comp.frames if f.uid}
        for ct in self.comp.cotas:
            if not ct.anchored:
                continue
            frame = frames.get(ct.anchor_uid)
            if frame is None:
                continue                  # frame gone: a free paper cota now
            try:
                _pts, wpts = self.frame_snap_points(frame)
                tol = 2.5 * frame.scale_n / 1000.0   # 2.5 paper mm, metres
                for attr in ("a_world", "b_world"):
                    w = np.asarray(getattr(ct, attr), dtype=np.float64)
                    if len(wpts):
                        d2 = ((wpts - w) ** 2).sum(axis=1)
                        i = int(np.argmin(d2))
                        if d2[i] <= tol * tol:
                            setattr(ct, attr, [float(v) for v in wpts[i]])
                (ax, ay), (bx, by) = self._frame_world_to_page(
                    frame, [ct.a_world, ct.b_world])
                ct.x_mm, ct.y_mm = ax, ay
                ct.dx_mm, ct.dy_mm = bx - ax, by - ay
                ct.scale_n = frame.scale_n
            except Exception:  # noqa: BLE001 — a broken projection must
                pass           # never take the composer down; cota stays put

    def nearest_snap_point(self, x_mm: float, y_mm: float, thr_mm: float):
        """Nearest frame snap point to (x_mm, y_mm) within *thr_mm*, or
        None. Returns ``(x, y, world_xyz, frame)`` — the page position, the
        matching model point in world metres, and the frame it belongs to.
        Searches every frame whose rectangle contains the cursor first, then
        all frames (so an edge just past a frame border still catches)."""
        import numpy as np
        best = None
        best_d2 = thr_mm * thr_mm
        for frame in self.comp.frames:
            pts, wpts = self.frame_snap_points(frame)
            if not len(pts):
                continue
            d2 = ((pts[:, 0] - x_mm) ** 2 + (pts[:, 1] - y_mm) ** 2)
            i = int(np.argmin(d2))
            if d2[i] < best_d2:
                best_d2 = float(d2[i])
                best = (float(pts[i, 0]), float(pts[i, 1]),
                        (float(wpts[i, 0]), float(wpts[i, 1]),
                         float(wpts[i, 2])), frame)
        return best

    def compute_hlr(self, frame: MarcoVista):
        """Hidden-line segments of *frame*'s view in PAPER millimetres
        (frame-local), cached by frame identity."""
        import numpy as np
        from core.composition import model_height_for_frame
        from core.hlr import hlr_view

        def run():
            vp = self._window.viewport
            segs = hlr_view(vp.scene, vp.camera)
            model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
            k = frame.h_mm / model_h                 # paper mm per metre
            half_h = model_h / 2.0
            half_w = half_h * (frame.w_mm / frame.h_mm)
            if len(segs):
                out = np.empty_like(segs)
                out[:, 0] = (segs[:, 0] + half_w) * k
                out[:, 1] = (half_h - segs[:, 1]) * k
                out[:, 2] = (segs[:, 2] + half_w) * k
                out[:, 3] = (half_h - segs[:, 3]) * k
            else:
                out = segs
            self.hlr_cache[id(frame)] = out
            return out

        return self._with_frame_camera(frame, run)

    def model_view_segments(self, frame: MarcoVista):
        """The frame's hidden-line view in MODEL units (metres, view
        plane) — what the DXF bridge to IngeCAD writes."""
        from core.hlr import hlr_view

        def run():
            vp = self._window.viewport
            return hlr_view(vp.scene, vp.camera)

        return self._with_frame_camera(frame, run)

    def render_frame(self, frame: MarcoVista) -> Optional[QImage]:
        """Fill *frame*: a GL render for the raster styles, the exact
        hidden-line pass for the vector style. Cached by frame identity;
        the live viewport state always comes back untouched."""
        if frame.style == "vectorial":
            self.compute_hlr(frame)
            return None

        def run():
            vp = self._window.viewport
            try:
                if frame.style in ("tecnico", "lineas"):
                    vp.plano_style = frame.style
                w_px, h_px = frame.render_px(RENDER_DPI)
                return vp.render_image(w_px, h_px, overlays=False)
            finally:
                vp.plano_style = None

        image = self._with_frame_camera(frame, run)
        if image is not None:
            self.render_cache[id(frame)] = image
        return image

    def _on_renumber(self) -> None:
        for i, comp in enumerate(self._scene().compositions):
            if comp.cajetin is not None:
                comp.cajetin.lamina = f"L-{i + 1:02d}"
        self._mark_dirty()
        self._rebuild_canvas()

    def _on_export_all(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export all sheets (PDF)…"), "laminas.pdf",
            "PDF (*.pdf)")
        if not path:
            return
        self.export_all_pdf(path)
        self.statusBar().showMessage(tr("Exported {name}", name=path), 4000)

    def _on_export_dxf(self) -> None:
        item = self._selected_item()
        if not isinstance(item, FrameItem):
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export view as DXF…"), "vista.dxf", "DXF (*.dxf)")
        if not path:
            return
        segs = self.model_view_segments(item.model)
        from formats.dxf_out import save_dxf_lines
        layer = frame_title_text(item.model).split(" — ")[0]
        n = save_dxf_lines(path, segs, layer=layer)
        self.statusBar().showMessage(
            tr("Exported {n} lines to {name}", n=n, name=path), 5000)

    # ---- export --------------------------------------------------------------
    def _on_export_pdf(self) -> None:
        self.refresh_all_frames()
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Export PDF…"), "lamina.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.export_pdf(path)
        self.statusBar().showMessage(tr("Exported {name}", name=path), 4000)

    def export_pdf(self, path: str) -> None:
        """Write the current sheet to ``path`` with exact physical page
        metrics. Every item paints through the same mm-space painters the
        canvas uses; the painter is scaled device-px-per-mm once."""
        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(getattr(QPageSize, self.comp.paper)))
        if self.comp.landscape:
            writer.setPageOrientation(QPageLayout.Landscape)
        writer.setResolution(RENDER_DPI)
        painter = QPainter(writer)
        try:
            painter.scale(RENDER_DPI / 25.4, RENDER_DPI / 25.4)
            self._paint_sheet(painter, self.comp)
        finally:
            painter.end()

    def export_all_pdf(self, path: str) -> None:
        """The atlas: every sheet of the document into ONE PDF, each on
        its own page at its own paper size."""
        comps = self._scene().compositions
        writer = QPdfWriter(path)
        writer.setResolution(RENDER_DPI)
        painter = None
        try:
            for i, comp in enumerate(comps):
                for f in comp.frames:          # fresh renders per sheet
                    saved = self.comp
                    self.comp = comp
                    try:
                        self.render_frame(f)
                    finally:
                        self.comp = saved
                writer.setPageSize(QPageSize(getattr(QPageSize, comp.paper)))
                writer.setPageOrientation(
                    QPageLayout.Landscape if comp.landscape
                    else QPageLayout.Portrait)
                if painter is None:
                    painter = QPainter(writer)
                else:
                    writer.newPage()
                painter.resetTransform()
                painter.scale(RENDER_DPI / 25.4, RENDER_DPI / 25.4)
                self._paint_sheet(painter, comp)
        finally:
            if painter is not None:
                painter.end()

    def _paint_sheet(self, painter: QPainter, comp: Composicion) -> None:
        """Draw one sheet's items in mm space (painter already scaled), in
        STACKING order (z) — the print must layer exactly like the canvas."""
        def paint(m) -> None:
            if isinstance(m, MarcoVista):
                paint_frame_mm(painter, m, self.render_cache.get(id(m)),
                               hlr=self.hlr_cache.get(id(m)))
            elif isinstance(m, ImagenItem):
                paint_image_mm(painter, m, self.image_cache(m.path))
            elif isinstance(m, TextoItem):
                paint_text_mm(painter, m)
            elif isinstance(m, BarraEscala):
                paint_scalebar_mm(painter, m)
            elif isinstance(m, FlechaNorte):
                paint_norte_mm(painter, m)
            elif isinstance(m, Leyenda):
                paint_leyenda_mm(painter, m)
            elif isinstance(m, FormaItem):
                paint_forma_mm(painter, m)
            elif isinstance(m, CotaItem):
                paint_cota_mm(painter, m)
            elif isinstance(m, Cajetin):
                paint_cajetin_mm(painter, m)

        for m in sorted(comp.all_items(),
                        key=lambda it: getattr(it, "z", 0.0)):
            painter.save()
            painter.translate(m.x_mm, m.y_mm)
            paint(m)
            painter.restore()

    # ---- lifecycle -----------------------------------------------------------
    def closeEvent(self, event) -> None:
        from PySide6.QtCore import QSettings
        QSettings().setValue("composer/panel_width",
                             self._splitter.sizes()[1])
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        # The document may have been swapped under us (New / Open) while
        # the window was closed — re-adopt the scene's compositions.
        scene = self._scene()
        if not scene.compositions:
            comp = Composicion()
            comp.frames.append(comp.default_frame())
            scene.compositions.append(comp)
        if self.comp not in scene.compositions:
            self.comp = scene.compositions[0]
            self.history = ComposerHistory(on_change=self._on_history_change)
        self._reload_comp_combo()
        self._rebuild_canvas()
        super().showEvent(event)
        # First impression: the whole page in view, whatever the paper size.
        self._view.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)
        self.update_zoom_label()
