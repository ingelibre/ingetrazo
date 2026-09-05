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
import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QKeySequence,
                           QPageLayout, QPageSize, QPainter, QPdfWriter,
                           QPen, QShortcut, QTransform, QVector3D)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGraphicsItem,
                               QGraphicsTextItem,
                               QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from core.composition import (COMMON_SCALES, PAPER_SIZES_MM, RENDER_DPI,
                              AddItemCommand, BarraEscala, Cajetin,
                              ComposerHistory, Composicion, CompoundCommand, CotaAngularItem, CotaItem,
                              EditItemCommand, EtiquetaItem, expand_fields, set_field_context, FlechaNorte, FormaItem,
                              ImagenItem, Leyenda, MarcoVista,
                              PerfilTerreno, RemoveItemCommand, TextoItem,
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
                  italic: bool = False, family: str = "Sans Serif",
                  underline: bool = False) -> None:
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
    font.setUnderline(underline)
    painter.setFont(font)
    painter.setPen(color)
    s = size_mm / 100.0 * 0.75   # pixelSize≈cap height/0.75 — visual match
    painter.scale(s, s)
    painter.drawText(QRectF(rect.x() / s, rect.y() / s,
                            rect.width() / s, rect.height() / s),
                     int(align | Qt.TextWordWrap), text)
    painter.restore()


def _fit_text_size_mm(text: str, rect: QRectF, base_size_mm: float,
                      bold: bool = False,
                      family: str = "Sans Serif") -> float:
    """Largest size ≤ base at which *text*, word-wrapped, fits *rect*
    (mm units) — the title-block habit: a long project name drops to two
    or three lines and only then starts shrinking."""
    from PySide6.QtGui import QFontMetricsF
    font = QFont(family or "Sans Serif")
    font.setPixelSize(100)
    font.setBold(bold)
    fm = QFontMetricsF(font)
    size = base_size_mm
    while size > 1.0:
        s = size / 100.0 * 0.75
        box = QRectF(0, 0, rect.width() / s, rect.height() / s)
        need = fm.boundingRect(box, int(Qt.AlignLeft | Qt.TextWordWrap),
                               text)
        if need.height() <= box.height() and need.width() <= box.width():
            return size
        size *= 0.88
    return 1.0


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


def _paint_scale_label_mm(painter: QPainter, frame: MarcoVista) -> None:
    """The frame's scale label, under a corner or inside it (with a white
    halo box inside, over the render)."""
    size = max(1.5, float(getattr(frame, "scale_mm", 3.0) or 3.0))
    text = frame.scale_label()
    pos = getattr(frame, "scale_pos", "under-right") or "under-right"
    h = size * 1.4
    if pos.startswith("under"):
        rect = QRectF(0, frame.h_mm + 1.0, frame.w_mm, h)
        align = (Qt.AlignLeft if pos == "under-left" else Qt.AlignRight)
        _draw_text_mm(painter, rect, text, size, bold=True,
                      align=align | Qt.AlignTop, color=QColor(40, 46, 54))
        return
    pad = 1.0
    w = len(text) * size * 0.62 + 2 * pad
    x = pad if pos == "inside-bl" else frame.w_mm - w - pad
    rect = QRectF(x, frame.h_mm - h - pad, w, h)
    painter.save()
    painter.setClipRect(QRectF(0, 0, frame.w_mm, frame.h_mm))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
    painter.drawRect(rect)
    _draw_text_mm(painter, rect, text, size, bold=True,
                  align=Qt.AlignHCenter | Qt.AlignVCenter,
                  color=QColor(40, 46, 54))
    painter.restore()


def _paint_stale_badge(painter: QPainter, frame: MarcoVista) -> None:
    """Small "Outdated" tag in the frame's top-right corner: the model
    changed since this view was rendered (auto-render off, or a vector
    frame waiting for Update)."""
    text = tr("Outdated")
    font = QFont()
    font.setPointSizeF(2.6)
    painter.setFont(font)
    fm = painter.fontMetrics()
    w = fm.horizontalAdvance(text) + 3.0
    h = fm.height() + 1.5
    r = QRectF(frame.w_mm - w - 1.5, 1.5, w, h)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 196, 60, 215))
    painter.drawRoundedRect(r, 1.0, 1.0)
    painter.setPen(QColor(60, 40, 0))
    painter.drawText(r, Qt.AlignCenter, text)


def _paint_view_edit_border(painter: QPainter, frame: MarcoVista) -> None:
    """The frame whose view is being edited in place: a blue dashed inset
    border and a small tag (LayOut greys the rest of the page instead)."""
    pen = QPen(QColor(58, 110, 165), 0.6, Qt.DashLine)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(0.8, 0.8, frame.w_mm - 1.6, frame.h_mm - 1.6))
    text = tr("Editing view")
    font = QFont()
    font.setPointSizeF(2.6)
    painter.setFont(font)
    fm = painter.fontMetrics()
    w = fm.horizontalAdvance(text) + 3.0
    h = fm.height() + 1.5
    r = QRectF(1.5, frame.h_mm - h - 1.5, w, h)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(58, 110, 165, 215))
    painter.drawRoundedRect(r, 1.0, 1.0)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(r, Qt.AlignCenter, text)


#: Traced georef paths on paper: the viewport's cyan, so the sheet reads
#: like the model (Marco, 2026-09-05: "no se ve la línea del path").
_GEO_PATH_INK = QColor(0, 150, 170)


def _paint_annots_mm(painter: QPainter, frame: MarcoVista, annots) -> None:
    """Model dimensions, leader texts and traced paths projected into the
    frame (mm): ``("line", x0, y0, x1, y1)``,
    ``("text", x, y, deg, text, size)`` and ``("poly", [(x, y), …])``."""
    r = QRectF(0, 0, frame.w_mm, frame.h_mm)
    painter.save()
    painter.setClipRect(r)
    ink = QColor(45, 55, 75)
    halo = QColor(255, 255, 255, 230)
    # Lines first with a white halo under the ink, so a leader over dark
    # water or stone still reads.
    for a in annots:
        if a[0] == "line":
            painter.setPen(QPen(halo, 0.7))
            painter.drawLine(QPointF(a[1], a[2]), QPointF(a[3], a[4]))
        elif a[0] == "poly":
            pts = [QPointF(x, y) for x, y in a[1]]
            painter.setPen(QPen(halo, 0.9, Qt.SolidLine, Qt.RoundCap,
                                Qt.RoundJoin))
            painter.drawPolyline(pts)
    for a in annots:
        if a[0] == "poly":
            pts = [QPointF(x, y) for x, y in a[1]]
            painter.setPen(QPen(_GEO_PATH_INK, 0.4, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline(pts)
            # Node marks, as the viewport draws them — small on paper.
            painter.setBrush(_GEO_PATH_INK)
            painter.setPen(QPen(halo, 0.15))
            for q in pts:
                painter.drawEllipse(q, 0.45, 0.45)
            painter.setBrush(Qt.NoBrush)
        elif a[0] == "line":
            painter.setPen(QPen(ink, 0.25))
            painter.drawLine(QPointF(a[1], a[2]), QPointF(a[3], a[4]))
        elif a[0] == "text":
            _kind, x, y, deg, text, size = a
            box = QRectF(-60, -size * 1.3, 120, size * 1.3)
            painter.save()
            painter.translate(QPointF(x, y))
            painter.rotate(deg)
            d = max(0.12, size * 0.06)
            for dx, dy in ((-d, 0), (d, 0), (0, -d), (0, d),
                           (-d, -d), (d, d), (-d, d), (d, -d)):
                _draw_text_mm(painter, box.translated(dx, dy), text, size,
                              bold=True,
                              align=Qt.AlignHCenter | Qt.AlignBottom,
                              color=halo)
            _draw_text_mm(painter, box, text, size, bold=True,
                          align=Qt.AlignHCenter | Qt.AlignBottom, color=ink)
            painter.restore()
    painter.restore()


def paint_frame_mm(painter: QPainter, frame: MarcoVista,
                   image: Optional[QImage], hlr=None, annots=None,
                   screen: bool = False) -> None:
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
    if annots:
        _paint_annots_mm(painter, frame, annots)
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
    if getattr(frame, "border", False):
        pen = QPen(QColor(getattr(frame, "border_color", "#282e36")))
        pen.setWidthF(max(0.1, float(getattr(frame, "border_mm", 0.3))))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
    elif screen:
        # Canvas-only guide so a borderless frame still reads as a frame;
        # the print gets nothing here (Marco, 2026-09-02).
        pen = QPen(QColor(150, 158, 166), 0.2, Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
    if frame.show_title:
        _draw_text_mm(painter,
                      QRectF(0, frame.h_mm + 1.2, frame.w_mm, 8.0),
                      frame_title_text(frame), 4.2, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignTop)
    if getattr(frame, "show_scale", False):
        _paint_scale_label_mm(painter, frame)


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


def chainage_step(length: float, step_m: float = 0.0) -> float:
    """The chainage step in metres: the user's, or the round one that spans
    *length* in about six marks. Shared by the profile's axis and the plan
    view's marks, so a sheet's chainages agree by construction."""
    from views.profile_panel import _nice_ticks
    if step_m and step_m > 0:
        return float(step_m)
    ticks = _nice_ticks(0.0, length, 6)
    return (ticks[1] - ticks[0]) if len(ticks) > 1 else (length or 1.0)


def _chainage(s: float, step: float) -> str:
    """Civil chainage, ``1+250`` style; decimals only when the step needs them."""
    km, m = int(s // 1000), s % 1000
    if step >= 1.0:
        return f"{km}+{m:03.0f}"
    return f"{km}+{m:06.2f}"


def paint_perfil_mm(painter: QPainter, m: PerfilTerreno, profile,
                    path_name: str = "", message=None) -> None:
    """The longitudinal profile in paper mm: title and scale caption, the
    grid with chainage and elevation labels, the ground line over its
    tinted fill, the axes. Horizontal scale 1:N (or fit to the width) and a
    vertical exaggeration (or fit to the height) — the pair every road and
    canal plan states next to the profile."""
    from views.profile_panel import _nice_ticks
    w, h = float(m.w_mm), float(m.h_mm)
    ink = QColor(30, 36, 44)
    grey = QColor(90, 98, 110)
    pen = QPen(ink)
    pen.setWidthF(0.25)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(0, 0, w, h))
    t = max(1.0, float(m.text_mm))
    title = m.title or tr("Longitudinal profile — {name}",
                          name=path_name or tr("path"))
    _draw_text_mm(painter, QRectF(2.0, 1.0, w - 4.0, t * 1.7), title,
                  t * 1.15, bold=True)
    if profile is None or not profile.samples or profile.max_elevation() is None:
        _draw_text_mm(painter, QRectF(2.0, h / 2 - t, w - 4.0, t * 2.2),
                      message or tr("Loading terrain…"), t,
                      align=Qt.AlignCenter, color=grey)
        return
    left, right = 4.0 + t * 4.2, w - 3.0
    top, bottom = t * 1.7 + 3.0 + t * 1.4, h - (t * 2.2 + 3.0)
    pw, ph = right - left, bottom - top
    if pw < 10.0 or ph < 8.0:
        return
    length = profile.length or 1.0
    elo, ehi = profile.min_elevation(), profile.max_elevation()
    if ehi - elo < 1.0:
        elo, ehi = elo - 1.0, ehi + 1.0
    v_ticks = _nice_ticks(elo, ehi, 4)
    step_v = float(m.grid_v_m) or (v_ticks[1] - v_ticks[0] if len(v_ticks) > 1 else 1.0)
    base = math.floor(elo / step_v) * step_v            # cota de comparación
    topv = math.ceil(ehi / step_v) * step_v
    if topv <= base:
        topv = base + step_v
    fitted_h = False
    if m.scale_n > 0:
        mm_per_m_h = 1000.0 / float(m.scale_n)
        if length * mm_per_m_h > pw:                    # would not fit: fall back
            mm_per_m_h, fitted_h = pw / length, True
    else:
        mm_per_m_h = pw / length
    if m.exag > 0:
        mm_per_m_v = mm_per_m_h * float(m.exag)
        if (topv - base) * mm_per_m_v > ph:
            mm_per_m_v = ph / (topv - base)
    else:
        mm_per_m_v = ph / (topv - base)
    exag_eff = mm_per_m_v / mm_per_m_h if mm_per_m_h > 0 else 1.0

    def sx(s):
        return left + s * mm_per_m_h

    def sy(e):
        return bottom - (e - base) * mm_per_m_v

    plot_right = sx(length)
    plot_top = sy(topv)
    # grid + labels
    step_h = chainage_step(length, float(m.grid_h_m))
    light = QPen(QColor(200, 206, 214))
    light.setWidthF(0.12)
    s_val = 0.0
    while s_val <= length + 1e-6:
        x = sx(s_val)
        if m.grid:
            painter.setPen(light)
            painter.drawLine(QPointF(x, plot_top), QPointF(x, bottom))
        _draw_text_mm(painter, QRectF(x - 12.0, bottom + 0.8, 24.0, t * 1.4),
                      _chainage(s_val, step_h), t,
                      align=Qt.AlignHCenter | Qt.AlignTop, color=grey)
        s_val += step_h
    e_val = base
    while e_val <= topv + 1e-6:
        y = sy(e_val)
        if m.grid:
            painter.setPen(light)
            painter.drawLine(QPointF(left, y), QPointF(plot_right, y))
        _draw_text_mm(painter, QRectF(1.0, y - t * 0.7, left - 2.0, t * 1.4),
                      f"{e_val:g}", t, align=Qt.AlignRight | Qt.AlignVCenter,
                      color=grey)
        e_val += step_v
    # the ground: runs split where the DEM is still missing
    runs, cur = [], []
    for smp in profile.samples:
        if smp.elevation is None:
            if cur:
                runs.append(cur)
                cur = []
        else:
            cur.append(QPointF(sx(smp.station), sy(smp.elevation)))
    if cur:
        runs.append(cur)
    from PySide6.QtGui import QPolygonF
    for run in runs:
        if len(run) < 2:
            continue
        if m.fill:
            poly = QPolygonF(run + [QPointF(run[-1].x(), bottom),
                                    QPointF(run[0].x(), bottom)])
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(120, 170, 110, 60)))
            painter.drawPolygon(poly)
            painter.setBrush(Qt.NoBrush)
        line = QPen(QColor(60, 110, 50))
        line.setWidthF(0.4)
        painter.setPen(line)
        painter.drawPolyline(QPolygonF(run))
    # axes
    axis = QPen(ink)
    axis.setWidthF(0.3)
    painter.setPen(axis)
    painter.drawLine(QPointF(left, plot_top), QPointF(left, bottom))
    painter.drawLine(QPointF(left, bottom), QPointF(plot_right, bottom))
    # caption: the scales, as a plan states them
    cap = tr("Scale H 1:{h} · V 1:{v} · vert. exag. ×{k}",
             h=f"{1000.0 / mm_per_m_h:.0f}", v=f"{1000.0 / mm_per_m_v:.0f}",
             k=f"{exag_eff:.1f}")
    if fitted_h:
        cap += "  " + tr("(fitted to the width)")
    if message:
        cap += "  " + message
    _draw_text_mm(painter, QRectF(2.0, t * 1.7 + 1.6, w - 4.0, t * 1.4), cap,
                  t * 0.9, color=grey)


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
    pen = QPen(QColor(f.color))
    pen.setWidthF(f.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(QBrush(QColor(f.fill_color))
                     if f.fill and f.kind in ("rect", "elipse", "poligono")
                     else Qt.NoBrush)
    r = QRectF(0, 0, f.w_mm, f.h_mm)
    if f.kind == "rect":
        rad = min(f.radius_mm, f.w_mm / 2, f.h_mm / 2)
        if rad > 0.01:
            painter.drawRoundedRect(r, rad, rad)
        else:
            painter.drawRect(r)
    elif f.kind == "elipse":
        painter.drawEllipse(r)
    elif f.kind == "poligono":
        import math as _math
        from PySide6.QtGui import QPolygonF
        n = max(3, min(int(f.sides), 24))
        cx, cy = f.w_mm / 2, f.h_mm / 2
        # vertex at the top, inscribed in the item's box (an octagon in a
        # square box comes out regular)
        pts = [QPointF(cx + cx * _math.sin(2 * _math.pi * i / n),
                       cy - cy * _math.cos(2 * _math.pi * i / n))
               for i in range(n)]
        painter.drawPolygon(QPolygonF(pts))
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
    ang = _math.atan2(ct.dy_mm, ct.dx_mm)
    label = ct.label()
    mid = QPointF((a2.x() + b2.x()) / 2, (a2.y() + b2.y()) / 2)
    text_pos = getattr(ct, "text_pos", "above") or "above"
    length = _math.hypot(ct.dx_mm, ct.dy_mm)
    if text_pos == "centered":
        # The label sits ON the line, which opens around it (LayOut's
        # "centered" text position).
        half = len(label) * ct.text_mm * 0.3 + 1.0
        if 2 * half < length - 2.0:
            ux, uy = _math.cos(ang), _math.sin(ang)
            painter.drawLine(a2, QPointF(mid.x() - ux * half,
                                         mid.y() - uy * half))
            painter.drawLine(QPointF(mid.x() + ux * half,
                                     mid.y() + uy * half), b2)
        else:
            painter.drawLine(a2, b2)
    else:
        painter.drawLine(a2, b2)
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
    painter.save()
    painter.translate(mid)
    deg = _math.degrees(ang)
    if deg > 90 or deg < -90:
        deg += 180                      # keep the label readable
    if (getattr(ct, "text_align", "aligned") or "aligned") == "horizontal":
        deg = 0.0
    painter.rotate(deg)
    tcol = QColor(ct.text_color) if getattr(ct, "text_color", "") else color
    if text_pos == "below":
        rect = QRectF(-40, ct.offset_mm, 80, ct.text_mm * 1.3)
        align = Qt.AlignHCenter | Qt.AlignTop
    elif text_pos == "centered":
        rect = QRectF(-40, -ct.text_mm * 0.65, 80, ct.text_mm * 1.3)
        align = Qt.AlignHCenter | Qt.AlignVCenter
    else:
        rect = QRectF(-40, -ct.offset_mm - ct.text_mm, 80, ct.text_mm * 1.3)
        align = Qt.AlignHCenter | Qt.AlignTop
    bg = getattr(ct, "text_bg", "") or ""
    if bg and label:
        tw = len(label) * ct.text_mm * 0.62 + 2.0
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(
            bg, getattr(ct, "text_bg_opacity", 1.0))))
        painter.drawRect(QRectF(-tw / 2, rect.top() - 0.4, tw,
                                rect.height() + 0.8))
        painter.restore()
    _draw_text_mm(painter, rect, label, ct.text_mm, align=align, color=tcol)
    painter.restore()


def _label_block_h(et: EtiquetaItem) -> float:
    return et.h_mm


def paint_etiqueta_mm(painter: QPainter, et: EtiquetaItem) -> None:
    """Label with a leader: the text block at the origin, a line from the
    block's nearest edge midpoint to the pointed-at spot, arrow head there."""
    import math as _math
    from PySide6.QtGui import QBrush, QPolygonF
    text = expand_fields(et.text)
    size_mm = et.size_pt * PT_TO_MM
    h = _label_block_h(et)
    color = QColor(et.color)
    # leader: from the block edge closest to the anchor
    ax, ay = et.ax_mm, et.ay_mm
    cx, cy = et.w_mm / 2, h / 2
    if ax < 0:
        sx, sy = -0.8, cy
    elif ax > et.w_mm:
        sx, sy = et.w_mm + 0.8, cy
    elif ay < 0:
        sx, sy = cx, -0.8
    else:
        sx, sy = cx, h + 0.8
    pen = QPen(color)
    pen.setWidthF(et.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawLine(QPointF(sx, sy), QPointF(ax, ay))
    if et.arrow:
        ang = _math.atan2(sy - ay, sx - ax)        # from the tip back
        L = max(1.8, et.stroke_mm * 7)
        base = _math.radians(14)
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygonF([
            QPointF(ax, ay),
            QPointF(ax + L * _math.cos(ang + base), ay + L * _math.sin(ang + base)),
            QPointF(ax + L * _math.cos(ang - base), ay + L * _math.sin(ang - base))]))
        painter.restore()
    bg = et.bg_color or ""
    if bg:
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(bg, et.bg_opacity)))
        painter.drawRect(QRectF(-TEXT_BG_PAD_MM, -TEXT_BG_PAD_MM,
                                et.w_mm + 2 * TEXT_BG_PAD_MM,
                                h + 2 * TEXT_BG_PAD_MM))
        painter.restore()
    _draw_text_mm(painter, QRectF(0, 0, et.w_mm, h + size_mm), text, size_mm,
                  et.bold, align=Qt.AlignLeft | Qt.AlignTop, color=color,
                  italic=getattr(et, "italic", False),
                  underline=getattr(et, "underline", False))


def paint_cota_angular_mm(painter: QPainter, ca: CotaAngularItem) -> None:
    """Angular dimension: two rays from the vertex to the measured points
    (extended to the arc when shorter), the arc at ``radius_mm`` with
    arrows / ticks, and the angle label outside its middle."""
    import math as _math
    from PySide6.QtGui import QBrush, QPainterPath, QPolygonF
    color = QColor(ca.color)
    pen = QPen(color)
    pen.setWidthF(ca.stroke_mm)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    a0, sweep = ca.angles()
    R = max(ca.radius_mm, 1.0)
    for px, py in ((ca.ax_mm, ca.ay_mm), (ca.bx_mm, ca.by_mm)):
        length = _math.hypot(px, py)
        if length < 1e-9:
            continue
        reach = max(length, R + 1.2)
        painter.drawLine(QPointF(0, 0), QPointF(px / length * reach,
                                                py / length * reach))
    rect = QRectF(-R, -R, 2 * R, 2 * R)
    path = QPainterPath()
    path.arcMoveTo(rect, -_math.degrees(a0))
    path.arcTo(rect, -_math.degrees(a0), -_math.degrees(sweep))
    painter.drawPath(path)
    a1 = a0 + sweep
    sgn = 1.0 if sweep >= 0 else -1.0
    ends = [(a0, sgn), (a1, -sgn)]           # (angle, direction into the arc)
    if ca.ends == "arrow":
        L = max(1.8, ca.stroke_mm * 6)
        painter.save()
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        for ang, d in ends:
            tip = QPointF(R * _math.cos(ang), R * _math.sin(ang))
            heading = _math.atan2(d * _math.cos(ang), -d * _math.sin(ang))
            base = _math.radians(12)
            painter.drawPolygon(QPolygonF([
                tip,
                QPointF(tip.x() + L * _math.cos(heading + base),
                        tip.y() + L * _math.sin(heading + base)),
                QPointF(tip.x() + L * _math.cos(heading - base),
                        tip.y() + L * _math.sin(heading - base))]))
        painter.restore()
    elif ca.ends != "none":
        tick = 1.6
        for ang, _d in ends:
            cx, cy = R * _math.cos(ang), R * _math.sin(ang)
            t = ang + _math.radians(45)
            painter.drawLine(QPointF(cx - tick * _math.cos(t),
                                     cy - tick * _math.sin(t)),
                             QPointF(cx + tick * _math.cos(t),
                                     cy + tick * _math.sin(t)))
    am = a0 + sweep / 2.0
    d = R + ca.offset_mm + ca.text_mm * 0.75
    lx, ly = d * _math.cos(am), d * _math.sin(am)
    tcol = QColor(ca.text_color) if ca.text_color else color
    label = ca.label()
    bg = getattr(ca, "text_bg", "") or ""
    if bg and label:
        tw = len(label) * ca.text_mm * 0.62 + 2.0
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(
            bg, getattr(ca, "text_bg_opacity", 1.0))))
        painter.drawRect(QRectF(lx - tw / 2, ly - ca.text_mm * 0.75, tw,
                                ca.text_mm * 1.5))
        painter.restore()
    _draw_text_mm(painter, QRectF(lx - 20, ly - ca.text_mm * 0.65, 40,
                                  ca.text_mm * 1.3),
                  label, ca.text_mm,
                  align=Qt.AlignHCenter | Qt.AlignVCenter, color=tcol)


TEXT_BG_PAD_MM = 1.0


def _with_opacity(color: str, opacity) -> QColor:
    c = QColor(color)
    try:
        c.setAlphaF(max(0.0, min(1.0, float(opacity))))
    except (TypeError, ValueError):
        pass
    return c


def paint_sheet_border_mm(painter: QPainter, comp) -> None:
    """The sheet's border on the margin rectangle: width, colour, rounded
    corners and line type (single / double / dashed)."""
    if not getattr(comp, "border", False):
        return
    pw, ph = comp.page_size_mm()
    m = comp.margin_mm
    r = QRectF(m, m, pw - 2 * m, ph - 2 * m)
    width = max(0.1, float(comp.border_mm))
    radius = max(0.0, float(comp.border_radius_mm))
    pen = QPen(QColor(comp.border_color), width)
    if comp.border_style == "dashed":
        pen.setStyle(Qt.DashLine)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.save()
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def rect_path(rr):
        if radius > 0.01:
            painter.drawRoundedRect(rr, radius, radius)
        else:
            painter.drawRect(rr)
    rect_path(r)
    if comp.border_style == "double":
        inset = width * 2.0 + 1.5
        pen2 = QPen(QColor(comp.border_color), max(0.1, width * 0.5))
        pen2.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen2)
        rect_path(r.adjusted(inset, inset, -inset, -inset))
    painter.restore()


def paint_text_mm(painter: QPainter, item: TextoItem) -> None:
    size_mm = item.size_pt * PT_TO_MM
    text = expand_fields(item.text, getattr(item, "frame_uid", "") or "")
    bg = getattr(item, "bg_color", "") or ""
    if bg:
        lines = item.text.count("\n") + 1
        block_h = max(6.0, size_mm * 1.4 * lines)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(_with_opacity(
            bg, getattr(item, "bg_opacity", 1.0))))
        painter.drawRect(QRectF(-TEXT_BG_PAD_MM, -TEXT_BG_PAD_MM,
                                item.w_mm + 2 * TEXT_BG_PAD_MM,
                                block_h + 2 * TEXT_BG_PAD_MM))
        painter.restore()
    rect = QRectF(0, 0, item.w_mm, size_mm * 1.35 * (text.count("\n") + 3))
    align = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
             "right": Qt.AlignRight}.get(item.align, Qt.AlignLeft)
    _draw_text_mm(painter, rect, text, size_mm, item.bold,
                  align=align | Qt.AlignTop, color=QColor(item.color),
                  italic=item.italic, family=item.family,
                  underline=getattr(item, "underline", False))


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


def _outline_path(w: float, h: float, corner: str, r: float):
    """The title block's outline: square, rounded or chamfered corners."""
    from PySide6.QtGui import QPainterPath
    r = max(0.0, min(float(r or 0.0), w / 2.0, h / 2.0))
    path = QPainterPath()
    if corner == "rounded" and r > 0:
        path.addRoundedRect(QRectF(0, 0, w, h), r, r)
    elif corner == "chamfer" and r > 0:
        pts = [(r, 0), (w - r, 0), (w, r), (w, h - r), (w - r, h), (r, h),
               (0, h - r), (0, r)]
        path.moveTo(QPointF(*pts[0]))
        for p in pts[1:]:
            path.lineTo(QPointF(*p))
        path.closeSubpath()
    else:
        path.addRect(QRectF(0, 0, w, h))
    return path


def cajetin_outline(c: Cajetin):
    return _outline_path(c.w_mm, c.h_mm, getattr(c, "corner", "square"),
                         getattr(c, "radius_mm", 0.0))


def paint_cajetin_mm(painter: QPainter, c: Cajetin) -> None:
    """The title block in its design: the outline shape (square / rounded /
    chamfered, optionally doubled), then the rows as a labelled grid, a
    header band over a grid, or a line-free minimal layout."""
    import math as _math
    w, h = c.w_mm, c.h_mm
    outline = cajetin_outline(c)
    corner = getattr(c, "corner", "square") or "square"
    layout = getattr(c, "layout", "grid") or "grid"
    fill = getattr(c, "fill_color", "") or ""
    line_color = QColor(getattr(c, "line_color", "") or "#1e242c")
    label_color = QColor(getattr(c, "label_color", "") or "#5a626c")
    text_color = QColor(getattr(c, "text_color", "") or "#1e242c")
    heavy = QPen(line_color)
    heavy.setWidthF(c.border_mm)
    light = QPen(line_color)
    light.setWidthF(c.line_mm)
    campos = c.campos or [[label, getattr(c, attr)]
                          for label, attr in Cajetin.FIELDS]
    # Dynamic fields in the values; an empty ESCALA row reads the sheet's
    # main frame by itself (the title block that never lies about scale).
    expanded = []
    for label, value in campos:
        v = expand_fields(str(value or ""))
        if not v and str(label).strip().lower() in ("escala", "scale"):
            v = expand_fields("{escala}")
        expanded.append([label, v])
    campos = expanded

    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.drawPath(outline)
    painter.setClipPath(outline)          # fills and lines stay in shape

    band, rest = (None, campos)
    if layout == "banded" and len(campos) > 1:
        band, rest = campos[0], campos[1:]
    band_h = 0.0
    if band is not None:
        band_h = h * 1.5 / (len(rest) + 1.5)
        if fill:
            painter.fillRect(QRectF(0, 0, w, band_h), QColor(fill))
        painter.setPen(light)
        painter.drawLine(QPointF(0, band_h), QPointF(w, band_h))
        lrect = QRectF(1.5, 0.4, w - 3.0, band_h * 0.32)
        _draw_text_mm(painter, lrect, str(band[0]), max(1.4, band_h * 0.2),
                      bold=True, align=Qt.AlignLeft | Qt.AlignTop,
                      color=label_color)
        vrect = QRectF(1.5, band_h * 0.3, w - 3.0, band_h * 0.68)
        vsize = _fit_text_size_mm(str(band[1]), vrect, band_h * 0.4,
                                  bold=True)
        _draw_text_mm(painter, vrect, str(band[1]), vsize, bold=True,
                      align=Qt.AlignHCenter | Qt.AlignVCenter,
                      color=text_color)
    y_top = band_h
    body_h = h - band_h
    cols = max(1, min(int(c.columns), max(1, len(rest))))
    per = max(1, _math.ceil(len(rest) / cols))
    col_w = w / cols
    row_h = body_h / per
    label_mm = float(getattr(c, "label_mm", 0.0) or 0.0)
    for k in range(cols):
        x0 = k * col_w
        chunk = rest[k * per:(k + 1) * per]
        if layout == "minimal":
            # no lines at all: a small label over its value, per cell
            for j, (label, value) in enumerate(chunk):
                y = y_top + j * row_h
                lrect = QRectF(x0 + 1.5, y + 0.4, col_w - 3.0, row_h * 0.36)
                _draw_text_mm(painter, lrect, str(label),
                              max(1.4, row_h * 0.24), bold=True,
                              align=Qt.AlignLeft | Qt.AlignTop,
                              color=label_color)
                vrect = QRectF(x0 + 1.5, y + row_h * 0.36, col_w - 3.0,
                               row_h * 0.62)
                vsize = _fit_text_size_mm(str(value), vrect, row_h * 0.42)
                _draw_text_mm(painter, vrect, str(value), vsize,
                              align=Qt.AlignLeft | Qt.AlignVCenter,
                              color=text_color)
            continue
        label_w = (min(col_w * 0.6, label_mm) if label_mm > 0
                   else min(28.0, col_w * 0.3))
        if fill:
            painter.fillRect(QRectF(x0, y_top, label_w, body_h), QColor(fill))
        painter.setPen(light)
        if k:
            painter.drawLine(QPointF(x0, y_top), QPointF(x0, h))
        painter.drawLine(QPointF(x0 + label_w, y_top),
                         QPointF(x0 + label_w, h))
        for j, (label, value) in enumerate(chunk):
            y = y_top + j * row_h
            if j:
                painter.drawLine(QPointF(x0, y), QPointF(x0 + col_w, y))
            # Long content wraps to more lines inside its cell and only
            # shrinks when even wrapped it does not fit.
            lrect = QRectF(x0 + 1.2, y + 0.5, label_w - 2, row_h - 1.0)
            lsize = _fit_text_size_mm(str(label), lrect, row_h * 0.38,
                                      bold=True)
            _draw_text_mm(painter, lrect, str(label), lsize, bold=True,
                          align=Qt.AlignLeft | Qt.AlignVCenter,
                          color=label_color)
            vrect = QRectF(x0 + label_w + 1.5, y + 0.5,
                           col_w - label_w - 3, row_h - 1.0)
            vsize = _fit_text_size_mm(str(value), vrect, row_h * 0.52)
            _draw_text_mm(painter, vrect, str(value), vsize,
                          align=Qt.AlignLeft | Qt.AlignVCenter,
                          color=text_color)
    painter.restore()
    painter.setPen(heavy)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(outline)
    if getattr(c, "double_border", False):
        inset = 1.2
        inner = _outline_path(w - 2 * inset, h - 2 * inset, corner,
                              float(getattr(c, "radius_mm", 0.0) or 0.0) - inset)
        painter.save()
        painter.translate(inset, inset)
        painter.setPen(light)
        painter.drawPath(inner)
        painter.restore()


# ── Canvas items ────────────────────────────────────────────────────────────

class InlineTextEditor(QGraphicsTextItem):
    """Edit a text block or a label IN PLACE on the sheet (LayOut): the same
    font at the same paper size, over the item; focus-out or Ctrl+Enter
    commits (one undo step), Esc cancels."""

    def __init__(self, composer, item) -> None:
        super().__init__()
        self.composer = composer
        self.item = item
        m = item.model
        self._original = m.text
        size_mm = float(m.size_pt) * PT_TO_MM
        font = QFont(getattr(m, "family", "") or "Sans Serif")
        font.setPixelSize(100)                # like _draw_text_mm…
        font.setBold(bool(getattr(m, "bold", False)))
        font.setItalic(bool(getattr(m, "italic", False)))
        font.setUnderline(bool(getattr(m, "underline", False)))
        self.setFont(font)
        self.setDefaultTextColor(QColor(getattr(m, "color", "#1e242c")))
        s = size_mm / 100.0 * 0.75            # …scaled like _draw_text_mm
        self.setScale(s)
        self.setTextWidth(max(10.0, float(m.w_mm)) / s)
        self.setPlainText(m.text)
        self.setPos(item.pos())
        self.setZValue(2e6)
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self._done = False

    def paint(self, painter, option, widget=None) -> None:
        # a white card under the words so the item beneath does not bleed
        painter.save()
        painter.setPen(QPen(QColor(58, 110, 165), 0.0))
        painter.setBrush(QBrush(QColor(255, 255, 255, 235)))
        painter.drawRect(self.boundingRect())
        painter.restore()
        super().paint(painter, option, widget)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.finish(commit=False)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (
                event.modifiers() & Qt.ControlModifier):
            self.finish(commit=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.finish(commit=True)

    def finish(self, commit: bool) -> None:
        if self._done:
            return
        self._done = True
        text = self.toPlainText().rstrip("\n")
        self.composer.end_inline_edit(self, text if commit else None)


class _SheetBorderCanvasItem(QGraphicsItem):
    """The sheet border on the canvas — the same painter the print uses."""

    def __init__(self, comp) -> None:
        super().__init__()
        self.comp = comp
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)

    def boundingRect(self) -> QRectF:
        pw, ph = self.comp.page_size_mm()
        return QRectF(-2, -2, pw + 4, ph + 4)

    def paint(self, painter, option, widget=None) -> None:
        paint_sheet_border_mm(painter, self.comp)


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
        self.setAcceptHoverEvents(True)
        self._press_state: Optional[dict] = None
        self._resizing = False

    # -- hover: advertise the resize handle with the right cursor -------------
    def hoverMoveEvent(self, event) -> None:
        if (not getattr(self.model, "locked", False)
                and self._on_resize_handle(event.pos())):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    # -- arrange / lock (context menu) ----------------------------------------
    def contextMenuEvent(self, event) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        front = menu.addAction(tr("Bring to front"))
        up = menu.addAction(tr("Raise"))
        down = menu.addAction(tr("Lower"))
        back = menu.addAction(tr("Send to back"))
        menu.addSeparator()
        grp = menu.addAction(tr("Group (Ctrl+G)"))
        ungrp = menu.addAction(tr("Ungroup (Ctrl+Shift+G)"))
        ungrp.setEnabled(bool(getattr(self.model, "group_id", "")))
        cp = menu.addAction(tr("Copy (Ctrl+C)"))
        cut = menu.addAction(tr("Cut (Ctrl+X)"))
        paste = menu.addAction(tr("Paste (Ctrl+V)"))
        paste.setEnabled(bool(getattr(self.composer, "_clipboard", None)))
        dup = menu.addAction(tr("Duplicate (Ctrl+D)"))
        copy_style = menu.addAction(tr("Copy style"))
        paste_style = menu.addAction(tr("Paste style"))
        paste_style.setEnabled(self.composer.can_paste_style(self.model))
        edit_view = fit = None
        if hasattr(self.model, "view_key"):          # a model-view frame
            menu.addSeparator()
            edit_view = menu.addAction(tr("Edit view (pan / orbit / zoom)"))
            fit = menu.addAction(tr("Frame the model"))
        menu.addSeparator()
        lock = menu.addAction(tr("Unlock")
                              if getattr(self.model, "locked", False)
                              else tr("Lock"))
        chosen = menu.exec(event.screenPos())
        if chosen is None:
            return
        if chosen is grp:
            self.setSelected(True)
            self.composer.group_selected()
            return
        if chosen is ungrp:
            self.setSelected(True)
            self.composer.ungroup_selected()
            return
        if chosen is dup:
            self.setSelected(True)
            self.composer.duplicate_selected()
            return
        if chosen is cp:
            self.setSelected(True)
            self.composer.copy_selected()
            return
        if chosen is cut:
            self.setSelected(True)
            self.composer.cut_selected()
            return
        if chosen is paste:
            self.composer.paste_clipboard()
            return
        if chosen is copy_style:
            self.composer.copy_style(self)
            return
        if chosen is paste_style:
            self.composer.paste_style()
            return
        if edit_view is not None and chosen is edit_view:
            self.composer.begin_view_edit(self)
        elif fit is not None and chosen is fit:
            self.composer.zoom_extents(self)
        elif chosen is front:
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
        if self.RESIZABLE and not getattr(self.model, "locked", False):
            painter.setBrush(QBrush(QColor(58, 110, 165)))
            painter.setPen(QPen(QColor(255, 255, 255), 0.3))
            painter.drawRect(QRectF(w - _HANDLE_MM / 2, h - _HANDLE_MM / 2,
                                    _HANDLE_MM, _HANDLE_MM))

    # -- interaction ---------------------------------------------------------
    def _on_resize_handle(self, pos: QPointF) -> bool:
        w, h = self.size_mm()
        return (self.RESIZABLE
                and abs(pos.x() - w) <= _HANDLE_MM
                and abs(pos.y() - h) <= _HANDLE_MM)

    def mousePressEvent(self, event) -> None:
        note = getattr(self.composer, "note_drag_start", None)
        if note is not None:
            note()
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
            if value and getattr(self.model, "group_id", ""):
                sync = getattr(self.composer, "sync_group_selection", None)
                if sync is not None:
                    sync(self)
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
                       hlr=self.composer.hlr_cache.get(id(self.model)),
                       annots=self.composer.annot_cache.get(id(self.model)),
                       screen=True)
        if self.composer.is_stale(self.model):
            _paint_stale_badge(painter, self.model)
        if self.composer.view_edit_item is self:
            _paint_view_edit_border(painter, self.model)
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event) -> None:
        # LayOut: double-click a model viewport to edit its view in place.
        self.composer.begin_view_edit(self)
        event.accept()


class ScaleBarItem(_SheetItem):
    RESIZABLE = False

    def boundingRect(self) -> QRectF:
        return QRectF(-12.5, -0.5, self.model.w_mm + 25.0, 12.0)

    def paint(self, painter, option, widget=None) -> None:
        paint_scalebar_mm(painter, self.model)
        self._paint_selection(painter)


class PerfilItem(_SheetItem):
    """A terrain-profile item: resizable like a frame, sampled on demand."""
    def paint(self, painter, option, widget=None) -> None:
        profile, name, message = self.composer.profile_for(self.model)
        paint_perfil_mm(painter, self.model, profile, name, message)
        self._paint_selection(painter)


class TextItem(_SheetItem):
    RESIZABLE = True

    def size_mm(self):
        size_mm = self.model.size_pt * PT_TO_MM
        lines = self.model.text.count("\n") + 1
        return self.model.w_mm, max(6.0, size_mm * 1.4 * lines)

    def boundingRect(self) -> QRectF:
        r = super().boundingRect()
        if getattr(self.model, "bg_color", ""):
            pad = TEXT_BG_PAD_MM + 0.5
            return r.adjusted(-pad, -pad, pad, pad)
        return r

    def mouseDoubleClickEvent(self, event) -> None:
        # LayOut: double-click a text block to edit it.
        self.composer.edit_text_item(self)
        event.accept()

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


class EtiquetaCanvasItem(_SheetItem):
    """A label on the canvas: drag moves the text (the pointed-at spot
    stays put — it is stored relative, so we counter-move it); dragging the
    spot's handle moves only the spot; double-click edits the text."""

    def size_mm(self):
        return (self.model.w_mm, self.model.h_mm)

    def boundingRect(self) -> QRectF:
        m = self.model
        x0 = min(0.0, m.ax_mm) - 3.0
        y0 = min(0.0, m.ay_mm) - 3.0
        x1 = max(m.w_mm, m.ax_mm) + 3.0
        y1 = max(m.h_mm, m.ay_mm) + 3.0
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def shape(self):
        from PySide6.QtGui import QPainterPath, QPainterPathStroker
        m = self.model
        path = QPainterPath()
        path.addRect(QRectF(-1, -1, m.w_mm + 2, m.h_mm + 2))
        line = QPainterPath()
        line.moveTo(m.w_mm / 2, m.h_mm / 2)
        line.lineTo(m.ax_mm, m.ay_mm)
        stroker = QPainterPathStroker()
        stroker.setWidth(2.0 * _HANDLE_MM)
        path.addPath(stroker.createStroke(line))
        return path

    def _on_resize_handle(self, pos: QPointF) -> bool:
        return False

    def _on_anchor_handle(self, pos: QPointF) -> bool:
        return (abs(pos.x() - self.model.ax_mm) <= _HANDLE_MM
                and abs(pos.y() - self.model.ay_mm) <= _HANDLE_MM)

    def hoverMoveEvent(self, event) -> None:
        if not getattr(self.model, "locked", False) and \
                self._on_anchor_handle(event.pos()):
            self.setCursor(Qt.CrossCursor)
        else:
            self.unsetCursor()
        super(_SheetItem, self).hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        note = getattr(self.composer, "note_drag_start", None)
        if note is not None:
            note()
        self._press_state = {k: getattr(self.model, k)
                             for k in ("x_mm", "y_mm", "ax_mm", "ay_mm")}
        self._anchor_drag = (not getattr(self.model, "locked", False)
                             and self._on_anchor_handle(event.pos()))
        if self._anchor_drag:
            event.accept()
            self.setSelected(True)
            return
        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event) -> None:
        if getattr(self, "_anchor_drag", False):
            self.prepareGeometryChange()
            self.model.ax_mm = event.pos().x()
            self.model.ay_mm = event.pos().y()
            self.model.anchor_uid, self.model.a_world = "", None   # re-anchor by hand later
            self.update()
            return
        QGraphicsItem.mouseMoveEvent(self, event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and \
                getattr(self, "_press_state", None) is not None and \
                not getattr(self, "_anchor_drag", False):
            # the block moved: keep the pointed-at spot where it was
            dx = self.pos().x() - self._press_state["x_mm"]
            dy = self.pos().y() - self._press_state["y_mm"]
            self.model.ax_mm = self._press_state["ax_mm"] - dx
            self.model.ay_mm = self._press_state["ay_mm"] - dy
            self.prepareGeometryChange()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event) -> None:
        was = getattr(self, "_anchor_drag", False)
        self._anchor_drag = False
        QGraphicsItem.mouseReleaseEvent(self, event)
        if self._press_state is None:
            return
        current = {k: getattr(self.model, k) for k in self._press_state}
        if current != self._press_state:
            self.composer.push_geometry_edit(self.model, current,
                                             self._press_state)
        self._press_state = None
        if was:
            self.composer.on_item_geometry(self, final=True)

    def mouseDoubleClickEvent(self, event) -> None:
        self.composer.edit_text_item(self)
        event.accept()

    def paint(self, painter, option, widget=None) -> None:
        paint_etiqueta_mm(painter, self.model)
        self._paint_selection(painter)


class CotaAngularCanvasItem(_SheetItem):
    """An angular dimension on the canvas: the vertex is the item's
    position; dragging near the arc's middle changes its radius."""

    def size_mm(self):
        return (self.model.w_mm, self.model.h_mm)

    def _arc_mid(self) -> tuple[float, float]:
        import math as _math
        a0, sweep = self.model.angles()
        am = a0 + sweep / 2.0
        R = self.model.radius_mm
        return (R * _math.cos(am), R * _math.sin(am))

    def boundingRect(self) -> QRectF:
        m = self.model
        reach = max(m.radius_mm + m.offset_mm + m.text_mm * 2.5,
                    abs(m.ax_mm), abs(m.ay_mm), abs(m.bx_mm), abs(m.by_mm))
        pad = 3.0
        return QRectF(-reach - pad, -reach - pad,
                      2 * (reach + pad), 2 * (reach + pad))

    def shape(self):
        import math as _math
        from PySide6.QtGui import QPainterPath, QPainterPathStroker
        m = self.model
        R = max(m.radius_mm, 1.0)
        a0, sweep = m.angles()
        lines = QPainterPath()
        for px, py in ((m.ax_mm, m.ay_mm), (m.bx_mm, m.by_mm)):
            length = _math.hypot(px, py)
            if length < 1e-9:
                continue
            reach = max(length, R + 1.2)
            lines.moveTo(0, 0)
            lines.lineTo(px / length * reach, py / length * reach)
        rect = QRectF(-R, -R, 2 * R, 2 * R)
        lines.arcMoveTo(rect, -_math.degrees(a0))
        lines.arcTo(rect, -_math.degrees(a0), -_math.degrees(sweep))
        stroker = QPainterPathStroker()
        stroker.setWidth(2.0 * _HANDLE_MM)
        path = stroker.createStroke(lines)
        am = a0 + sweep / 2.0
        d = R + m.offset_mm + m.text_mm * 0.75
        w = len(m.label()) * m.text_mm * 0.7 + 2.0
        path.addRect(QRectF(d * _math.cos(am) - w / 2,
                            d * _math.sin(am) - m.text_mm * 0.8, w,
                            m.text_mm * 1.6))
        return path

    def _on_resize_handle(self, pos: QPointF) -> bool:
        return False

    def _on_radius_handle(self, pos: QPointF) -> bool:
        mx, my = self._arc_mid()
        return abs(pos.x() - mx) <= _HANDLE_MM and abs(pos.y() - my) <= _HANDLE_MM

    def hoverMoveEvent(self, event) -> None:
        if not getattr(self.model, "locked", False) and \
                self._on_radius_handle(event.pos()):
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()
        super(_SheetItem, self).hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        note = getattr(self.composer, "note_drag_start", None)
        if note is not None:
            note()
        self._press_state = {k: getattr(self.model, k)
                             for k in ("x_mm", "y_mm", "radius_mm")}
        self._radius_drag = (not getattr(self.model, "locked", False)
                             and self._on_radius_handle(event.pos()))
        if self._radius_drag:
            event.accept()
            self.setSelected(True)
            return
        QGraphicsItem.mousePressEvent(self, event)

    def mouseMoveEvent(self, event) -> None:
        if getattr(self, "_radius_drag", False):
            import math as _math
            self.prepareGeometryChange()
            self.model.radius_mm = max(2.0, _math.hypot(event.pos().x(),
                                                        event.pos().y()))
            self.update()
            return
        QGraphicsItem.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event) -> None:
        was = getattr(self, "_radius_drag", False)
        self._radius_drag = False
        QGraphicsItem.mouseReleaseEvent(self, event)
        if self._press_state is None:
            return
        current = {k: getattr(self.model, k) for k in self._press_state}
        if current != self._press_state:
            self.composer.push_geometry_edit(self.model, current,
                                             self._press_state)
        self._press_state = None
        if was:
            self.composer.on_item_geometry(self, final=True)

    def paint(self, painter, option, widget=None) -> None:
        paint_cota_angular_mm(painter, self.model)
        self._paint_selection(painter)


class CotaCanvasItem(_SheetItem):
    def mouseDoubleClickEvent(self, event) -> None:
        # LayOut: double-click a dimension to edit its text.
        self.composer.edit_cota_text(self)
        event.accept()

    _sep_dragging = False

    def size_mm(self):
        return self.model.w_mm, self.model.h_mm

    def hoverMoveEvent(self, event) -> None:
        if not getattr(self.model, "locked", False) and (
                self._on_sep_handle(event.pos())
                or self._on_resize_handle(event.pos())):
            self.setCursor(Qt.SizeAllCursor)
        else:
            self.unsetCursor()
        super(_SheetItem, self).hoverMoveEvent(event)

    def _line_mid(self) -> tuple[float, float]:
        nx, ny = self.model.normal()
        s = self.model.sep_mm
        return (self.model.dx_mm / 2 + nx * s, self.model.dy_mm / 2 + ny * s)

    def shape(self):
        """Hit area = the drawn lines (extension, dimension, label strip)
        with a few mm of slack — not the bounding box, which for a long
        oblique cota covers half the sheet and steals every click meant for
        the small cotas inside it (Marco, 2026-09-02)."""
        from PySide6.QtGui import QPainterPath, QPainterPathStroker, QTransform
        m = self.model
        nx, ny = m.normal()
        s = m.sep_mm
        p0, p1 = QPointF(0.0, 0.0), QPointF(m.dx_mm, m.dy_mm)
        a2 = QPointF(nx * s, ny * s)
        b2 = QPointF(m.dx_mm + nx * s, m.dy_mm + ny * s)
        lines = QPainterPath()
        for a, b in ((p0, a2), (p1, b2), (a2, b2)):
            lines.moveTo(a)
            lines.lineTo(b)
        stroker = QPainterPathStroker()
        stroker.setWidth(2.0 * _HANDLE_MM)
        path = stroker.createStroke(lines)
        # The label strip above the dimension line, rotated with it.
        import math as _math
        length = _math.hypot(m.dx_mm, m.dy_mm)
        w = min(80.0, length + 2 * m.text_mm)
        strip = QPainterPath()
        pos = getattr(m, "text_pos", "above") or "above"
        if pos == "below":
            strip.addRect(QRectF(-w / 2, -1.0, w,
                                 m.offset_mm + m.text_mm * 1.3 + 2.0))
        elif pos == "centered":
            strip.addRect(QRectF(-w / 2, -m.text_mm * 0.8, w,
                                 m.text_mm * 1.6))
        else:
            strip.addRect(QRectF(-w / 2, -m.offset_mm - m.text_mm * 1.3 - 1.0,
                                 w, m.offset_mm + m.text_mm * 1.3 + 2.0))
        deg = _math.degrees(_math.atan2(m.dy_mm, m.dx_mm))
        if deg > 90 or deg <= -90:
            deg += 180
        if (getattr(m, "text_align", "aligned") or "aligned") == "horizontal":
            deg = 0.0
        mid = QPointF((a2.x() + b2.x()) / 2, (a2.y() + b2.y()) / 2)
        t = QTransform().translate(mid.x(), mid.y()).rotate(deg)
        path.addPath(t.map(strip))
        return path

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
        note = getattr(self.composer, "note_drag_start", None)
        if note is not None:
            note()
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
        self._pan_last = None          # viewport px while panning the sheet
        self._ang_pts: list = []       # angular cota: vertex, A, B (page mm)
        # Tools that define a segment/rectangle take EITHER a drag or two
        # clicks (click the first vertex, move, click the second) — the
        # click-click habit of the model's dimension tool must work here too.
        self._two_point = {m for m, _i, _t, drag in composer.TOOLS if drag}

    #: Tools that draw OVER the model views and deserve geometry snapping.
    #: Frames, text blocks, images etc. place freely — computing the snap
    #: set for them froze the composer on photogrammetry-scale models.
    _GEOM_SNAP_TOOLS = frozenset(
        ("cota", "linea", "flecha", "rect", "elipse", "poligono"))

    def _snapped(self, pos):
        """Snap *pos* (scene mm) to the nearest frame geometry point when a
        drawing tool is armed. Returns (QPointF, hit). Threshold scales with
        zoom so it's ~7 px on screen."""
        from PySide6.QtCore import QPointF
        if self.composer.tool_mode not in self._GEOM_SNAP_TOOLS:
            self._last_hit = None
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
        edit = getattr(self.composer, "view_edit_item", None)
        if edit is not None:
            pos = self.mapToScene(event.position().toPoint())
            if edit.sceneBoundingRect().contains(pos):
                steps = event.angleDelta().y() / 120.0
                self.composer.zoom_view_gesture(edit, 1.1 ** steps,
                                                (pos.x(), pos.y()))
                event.accept()
                return
        self._wheel_page(event)

    def _wheel_page(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            f = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.scale(f, f)
            self.composer.update_zoom_label()
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        edit = getattr(self.composer, "view_edit_item", None)
        if edit is not None:
            pos = self.mapToScene(event.position().toPoint())
            inside = edit.sceneBoundingRect().contains(pos)
            if inside and event.button() in (Qt.LeftButton, Qt.MiddleButton):
                orbit = (event.button() == Qt.MiddleButton
                         or bool(event.modifiers() & Qt.ControlModifier))
                self.composer.start_view_drag(
                    edit, pos, event.position().toPoint(), orbit)
                event.accept()
                return
            if not inside and event.button() == Qt.LeftButton:
                self.composer.end_view_edit()      # click outside = done
        mode = self.composer.tool_mode
        if mode == "estilo" and event.button() == Qt.LeftButton:
            hit = next((it for it in self.items(event.position().toPoint())
                        if isinstance(it, _SheetItem)), None)
            self.composer.format_painter_click(hit)
            event.accept()
            return
        if mode == "cota_ang" and event.button() == Qt.LeftButton:
            pos, _ = self._snapped(self.mapToScene(event.position().toPoint()))
            if len(self._ang_pts) < 3:
                self._ang_pts.append((pos.x(), pos.y()))
                self._update_angular_preview(pos)
            else:
                import math as _math
                v = self._ang_pts[0]
                radius = _math.hypot(pos.x() - v[0], pos.y() - v[1])
                pts = list(self._ang_pts)
                self.cancel_placement()
                self.composer.place_angular(pts[0], pts[1], pts[2], radius)
            event.accept()
            return
        if event.button() == Qt.MiddleButton or (
                event.button() == Qt.LeftButton and mode == "pan"):
            # Pan the sheet: the middle button anywhere, or the Pan tool.
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
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
                # (unless it lands on the first point — keep waiting). The
                # test is in SCENE mm at the current zoom: the user may
                # have panned/zoomed between the clicks, so the first
                # press's viewport pixels mean nothing here.
                thr = 4.0 / max(self.transform().m11(), 1e-6)
                if (abs(pos.x() - self._drag_start.x())
                        + abs(pos.y() - self._drag_start.y())) >= thr:
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
        if self._pan_last is not None:
            p = event.position().toPoint()
            d = p - self._pan_last
            self._pan_last = p
            hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
            hbar.setValue(hbar.value() - d.x())
            vbar.setValue(vbar.value() - d.y())
            event.accept()
            return
        raw = self.mapToScene(event.position().toPoint())
        if getattr(self.composer, "view_drag_active", lambda: False)():
            self.composer.move_view_drag(raw, event.position().toPoint())
            event.accept()
            return
        pos, _ = self._snapped(raw)
        self.composer.update_cursor_label(pos.x(), pos.y())
        if self._ang_pts:
            self._update_angular_preview(pos)
            event.accept()
            return
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

    def _update_angular_preview(self, pos) -> None:
        """Rubber band of the angular tool: the rays placed so far, and
        once both are down, the arc at the cursor's distance."""
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
        pts = self._ang_pts
        v = pts[0]
        path = QPainterPath()
        targets = pts[1:] + ([(pos.x(), pos.y())] if len(pts) < 3 else [])
        for t in targets:
            path.moveTo(QPointF(*v))
            path.lineTo(QPointF(*t))
        if len(pts) == 3:
            R = max(2.0, _math.hypot(pos.x() - v[0], pos.y() - v[1]))
            model = CotaAngularItem(ax_mm=pts[1][0] - v[0], ay_mm=pts[1][1] - v[1],
                                    bx_mm=pts[2][0] - v[0], by_mm=pts[2][1] - v[1])
            a0, sweep = model.angles()
            rect = QRectF(v[0] - R, v[1] - R, 2 * R, 2 * R)
            path.arcMoveTo(rect, -_math.degrees(a0))
            path.arcTo(rect, -_math.degrees(a0), -_math.degrees(sweep))
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
        if self._pan_last is not None and event.button() in (
                Qt.MiddleButton, Qt.LeftButton):
            self._pan_last = None
            self.setCursor(Qt.OpenHandCursor
                           if self.composer.tool_mode == "pan"
                           else Qt.ArrowCursor)
            event.accept()
            return
        if getattr(self.composer, "view_drag_active", lambda: False)():
            self.composer.finish_view_drag()
            event.accept()
            return
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
        hit_a = self._hit_a
        self._hit_a = None
        if self.composer.tool_mode == "etiqueta":
            self.composer.place_tool(start.x(), start.y(), end.x(), end.y(),
                                     hit_a=hit_a)
        else:
            self.composer.place_tool(start.x(), start.y(), end.x(), end.y())

    def cancel_placement(self) -> None:
        """Drop an in-progress two-point placement (Esc / tool switch)."""
        self._drag_start = None
        self._second_pt = None
        self._ang_pts = []
        self._press_vp = None
        self._ignore_release = False
        self._hit_a = self._hit_b = None
        if self._preview is not None:
            self.scene().removeItem(self._preview)
            self._preview = None
        self._clear_snap_marker()

    def keyPressEvent(self, event) -> None:
        scene = self.scene()
        editing = scene is not None and isinstance(scene.focusItem(),
                                                   InlineTextEditor)
        if not editing:
            for seq, slot in ((QKeySequence.Copy, "copy_selected"),
                              (QKeySequence.Cut, "cut_selected"),
                              (QKeySequence.Paste, "paste_clipboard")):
                if event.matches(seq) and hasattr(self.composer, slot):
                    getattr(self.composer, slot)()
                    event.accept()
                    return
        if (event.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter)
                and getattr(self.composer, "view_edit_item", None)
                is not None):
            self.composer.end_view_edit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and (
                self._drag_start is not None or self._ang_pts):
            self.cancel_placement()
            event.accept()
            return
        if (event.key() == Qt.Key_Escape
                and self.composer.tool_mode == "estilo"
                and hasattr(self.composer, "_set_tool_mode")):
            self.composer._set_tool_mode("select")
            actions = getattr(self.composer, "_tool_actions", {})
            if "select" in actions:
                actions["select"].setChecked(True)
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self.scene() is not None:
            # LayOut / SketchUp: Esc drops the selection.
            self.scene().clearSelection()
            notify = getattr(self.composer, "on_selection_changed", None)
            if notify is not None:
                notify()
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
        # Auto-render (LayOut's "Auto"): the viewport announces every model
        # version; stale frames get a badge and, when auto is on and the
        # window is visible, the raster ones re-render by themselves after a
        # short quiet period. Vector frames (seconds each) wait for Update.
        from PySide6.QtCore import QSettings
        self._auto_render = str(QSettings().value(
            "composer/auto_render", "1")) != "0"
        self._stale: set = set()
        self._sheet_version = None
        vp = getattr(main_window, "viewport", None)
        self._last_model_version = (vp.scene.version
                                    if vp is not None else None)
        self._view_edit = None            # FrameItem whose view is edited
        self._view_drag = None            # the gesture in progress
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(400)
        self._auto_timer.timeout.connect(self._auto_render_stale)
        if vp is not None and hasattr(vp, "sceneVersionChanged"):
            vp.sceneVersionChanged.connect(self._on_model_version)
        self.render_cache: dict[int, QImage] = {}
        self.hlr_cache: dict[int, object] = {}
        self.snap_cache: dict[int, object] = {}   # frame → page-mm snap pts
        self.annot_cache: dict[int, list] = {}    # frame → model annotations
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
        self._build_arrange_toolbar()

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
        self.statusBar().addPermanentWidget(self._pos_label)
        # QGIS-style zoom combo: fit modes + presets, editable percentage.
        self._zoom_combo = QComboBox()
        self._zoom_combo.setEditable(True)
        self._zoom_combo.setInsertPolicy(QComboBox.NoInsert)
        self._zoom_combo.setMinimumWidth(170)
        self._zoom_combo.addItem(tr("Fit page width"), "fitw")
        self._zoom_combo.addItem(tr("Fit page"), "fit")
        for pct in (800.0, 400.0, 200.0, 100.0, 50.0, 25.0, 12.5):
            self._zoom_combo.addItem(f"{pct:g}%", pct)
        self._zoom_combo.activated.connect(self._on_zoom_chosen)
        self._zoom_combo.lineEdit().returnPressed.connect(
            self._on_zoom_typed)
        self.statusBar().addPermanentWidget(self._zoom_combo)
        self.update_zoom_label()

        QShortcut(QKeySequence.Undo, self, activated=self._on_undo)
        QShortcut(QKeySequence.Redo, self, activated=self._on_redo)
        QShortcut(QKeySequence.Delete, self, activated=self._on_delete_item)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.duplicate_selected)
        QShortcut(QKeySequence("Ctrl+G"), self, activated=self.group_selected)
        QShortcut(QKeySequence("Ctrl+Shift+G"), self,
                  activated=self.ungroup_selected)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.lock_selected)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.copy_style)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, activated=self.paste_style)

        self._rebuild_canvas()

    # ---- left tools toolbar (QGIS-style) -------------------------------------
    #: mode → (icon key, tooltip, drag?) — drag tools take a press-release
    #: extent, click tools place at the click point.
    TOOLS = (
        ("select", "select", "Select / move items", False),
        ("pan", "pan", "Pan the sheet (or drag with the middle button "
                       "anywhere)", False),
        ("estilo", "eyedropper",
         "Format painter: click an item to copy its style, then click the "
         "items to paste it on (Esc to finish)", False),
        ("vista", "comp_vista", "Add a model-view frame (two clicks or drag)", True),
        ("texto", "text", "Add a text block", False),
        ("etiqueta", "comp_etiqueta",
         "Add a label with a leader (click the point, then where the text "
         "goes)", True),
        ("imagen", "image", "Add an image", False),
        ("cajetin", "comp_cajetin", "Add the title block", False),
        ("escala", "comp_escala", "Add a graphic scale bar", False),
        ("norte", "comp_norte", "Add a north arrow", False),
        ("leyenda", "comp_leyenda", "Add the layer legend", False),
        ("perfil", "comp_perfil",
         "Add a terrain profile along a traced path (two clicks or drag)", True),
        ("linea", "line", "Draw a line (two clicks or drag)", True),
        ("flecha", "comp_flecha", "Draw an arrow (two clicks or drag)", True),
        ("rect", "rectangle", "Draw a rectangle (two clicks or drag)", True),
        ("elipse", "circle", "Draw an ellipse (two clicks or drag)", True),
        ("poligono", "polygon", "Draw a polygon (two clicks or drag)", True),
        ("cota", "dimension", "Draw a dimension (two points + separation)", True),
        ("cota_ang", "protractor",
         "Draw an angular dimension (vertex, two points, then the arc)", False),
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
        if hasattr(self, "_view"):
            self._view.setCursor({"pan": Qt.OpenHandCursor,
                                  "estilo": Qt.CrossCursor}.get(
                                      mode, Qt.ArrowCursor))
        if mode == "estilo":
            # The format painter starts by taking a style: the first click
            # copies, every later click pastes.
            self._painter_armed = True
            self.statusBar().showMessage(tr(
                "Format painter: click the item whose style you want to "
                "copy."), 6000)
        if mode == "imagen":
            # the image tool needs its file first; place at margins
            self._on_add_image()
            self._set_tool_mode("select")
            self._tool_actions["select"].setChecked(True)

    def place_tool(self, x0: float, y0: float, x1: float, y1: float,
                   sep_mm: float = 0.0, anchors=None, hit_a=None) -> None:
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
        elif mode == "etiqueta":
            # first click = the pointed-at spot, second = the text block
            item = EtiquetaItem(x_mm=x1, y_mm=y1, ax_mm=x0 - x1,
                                ay_mm=y0 - y1, text=tr("Label"))
            if hit_a is not None and hit_a[3] is not None:
                frame = hit_a[3]
                if not frame.uid:
                    import uuid
                    frame.uid = uuid.uuid4().hex
                item.anchor_uid = frame.uid
                item.a_world = list(hit_a[2])
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
        elif mode == "perfil":
            paths = getattr(self._scene(), "geo_paths", None) or []
            item = PerfilTerreno(x_mm=x, y_mm=y, w_mm=max(w, 80.0),
                                 h_mm=max(h, 40.0),
                                 path_index=self._perfil_default_path(paths))
        elif mode in ("linea", "flecha", "rect", "elipse", "poligono"):
            kind = mode
            invert = (x1 < x0) != (y1 < y0)
            if kind in ("linea", "flecha"):
                # a line's box legitimately degenerates to zero in one
                # axis — clamping tilted every snapped horizontal by 2 mm
                item = FormaItem(kind=kind, x_mm=x, y_mm=y,
                                 w_mm=w, h_mm=h, invert=invert)
            else:
                item = FormaItem(kind=kind, x_mm=x, y_mm=y,
                                 w_mm=max(w, 2.0), h_mm=max(h, 2.0))
        elif mode == "cota":
            n = self.comp.frames[0].scale_n if self.comp.frames else 100.0
            style = dict(getattr(self, "_last_cota_style", None) or {})
            style.setdefault("offset_mm", 0.8)
            item = CotaItem(x_mm=x0, y_mm=y0, dx_mm=x1 - x0, dy_mm=y1 - y0,
                            scale_n=n, sep_mm=sep_mm, **style)
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

    def place_angular(self, vertex, a, b, radius_mm: float) -> None:
        """The angular tool's four clicks landed: vertex, a point on each
        side, and the arc's radius."""
        import math as _math
        radius = max(2.0, float(radius_mm))
        style = dict(getattr(self, "_last_cota_style", None) or {})
        keep = {k: v for k, v in style.items()
                if k in ("text_mm", "stroke_mm", "color", "text_color")}
        item = CotaAngularItem(x_mm=vertex[0], y_mm=vertex[1],
                               ax_mm=a[0] - vertex[0], ay_mm=a[1] - vertex[1],
                               bx_mm=b[0] - vertex[0], by_mm=b[1] - vertex[1],
                               radius_mm=radius, **keep)
        if _math.hypot(item.ax_mm, item.ay_mm) < 1e-6 or \
                _math.hypot(item.bx_mm, item.by_mm) < 1e-6:
            return
        item.z = self._next_z()
        self._pending_sel = item
        self.history.execute(AddItemCommand(self.comp, item))
        self.tool_mode = "select"
        self._tool_actions["select"].setChecked(True)

    def update_cursor_label(self, x: float, y: float) -> None:
        self._pos_label.setText(f"x: {x:.1f} mm  y: {y:.1f} mm")

    # ---- zoom (QGIS-style combo) ---------------------------------------------
    def _px_per_mm(self) -> float:
        """Screen pixels per PAPER millimetre at 100% (true paper size)."""
        return self._view.logicalDpiX() / 25.4

    def zoom_percent(self) -> float:
        return self._view.transform().m11() / self._px_per_mm() * 100.0

    def set_zoom(self, pct: float) -> None:
        """Zoom to *pct* percent of true paper size, keeping the view
        centred where it was."""
        pct = max(1.0, min(float(pct), 1600.0))
        center = self._view.mapToScene(
            self._view.viewport().rect().center())
        s = pct / 100.0 * self._px_per_mm()
        self._view.setTransform(QTransform().scale(s, s))
        self._view.centerOn(center)
        self.update_zoom_label()

    def zoom_fit_page(self) -> None:
        pw, ph = self.comp.page_size_mm()
        self._view.fitInView(QRectF(-5, -5, pw + 10, ph + 10),
                             Qt.KeepAspectRatio)
        self.update_zoom_label()

    def zoom_fit_width(self) -> None:
        pw, _ph = self.comp.page_size_mm()
        vw = max(self._view.viewport().width(), 1)
        s = vw / (pw + 10.0)
        y = self._view.mapToScene(
            self._view.viewport().rect().center()).y()
        self._view.setTransform(QTransform().scale(s, s))
        self._view.centerOn(QPointF(pw / 2.0, y))
        self.update_zoom_label()

    def _on_zoom_chosen(self, index: int) -> None:
        data = self._zoom_combo.itemData(index)
        if data == "fitw":
            self.zoom_fit_width()
        elif data == "fit":
            self.zoom_fit_page()
        elif data is not None:
            self.set_zoom(float(data))

    def _on_zoom_typed(self) -> None:
        text = self._zoom_combo.lineEdit().text().strip().rstrip("%")
        try:
            self.set_zoom(float(text.replace(",", ".")))
        except ValueError:
            self.update_zoom_label()

    def update_zoom_label(self) -> None:
        if not hasattr(self, "_zoom_combo") or not hasattr(self, "_view"):
            return
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setEditText(f"{self.zoom_percent():.1f}%")
        self._zoom_combo.blockSignals(False)

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
        tpl_btn = QPushButton(tr("Templates…"))
        tpl_btn.setToolTip(tr(
            "Save this sheet as a template, start a new sheet from one, or "
            "pick the template every new sheet uses."))
        tpl_btn.clicked.connect(self._on_templates_menu)
        mgr.addWidget(tpl_btn)
        dis_lay.addLayout(mgr)
        fields_note = QLabel(tr(
            "Dynamic fields for texts and the title block: {proyecto} "
            "{autor} {lamina} {escala} {escena} {fecha} {archivo} {hoja} "
            "{total}"))
        fields_note.setWordWrap(True)
        fields_note.setStyleSheet("color: #8a94a0; font-size: 11px;")
        dis_lay.addWidget(fields_note)

        # Page
        form = QFormLayout()
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(list(PAPER_SIZES_MM))
        self.paper_combo.currentTextChanged.connect(self._on_page_changed)
        form.addRow(tr("Paper"), self.paper_combo)
        self.landscape_check = QCheckBox(tr("Landscape"))
        self.landscape_check.toggled.connect(self._on_page_changed)
        form.addRow("", self.landscape_check)
        self.border_check = QCheckBox(tr("Sheet border"))
        self.border_check.setToolTip(tr(
            "Draw a border on the margin rectangle, on screen and in print."))
        self.border_check.toggled.connect(self._on_border_changed)
        form.addRow("", self.border_check)
        self.border_mm = QDoubleSpinBox()
        self.border_mm.setRange(0.1, 3.0)
        self.border_mm.setSingleStep(0.1)
        self.border_mm.setSuffix(" mm")
        self.border_mm.setValue(0.5)
        self.border_mm.valueChanged.connect(self._on_border_changed)
        form.addRow(tr("Border width"), self.border_mm)
        self.border_radius = QDoubleSpinBox()
        self.border_radius.setRange(0.0, 30.0)
        self.border_radius.setSingleStep(0.5)
        self.border_radius.setSuffix(" mm")
        self.border_radius.valueChanged.connect(self._on_border_changed)
        form.addRow(tr("Corner radius"), self.border_radius)
        self.border_style = QComboBox()
        for label, key in ((tr("Single"), "single"), (tr("Double"), "double"),
                           (tr("Dashed"), "dashed")):
            self.border_style.addItem(label, key)
        self.border_style.currentIndexChanged.connect(self._on_border_changed)
        form.addRow(tr("Border style"), self.border_style)
        self.border_color_btn = QPushButton()
        self.border_color_btn.setFixedHeight(22)
        self.border_color_btn.clicked.connect(self._on_pick_border_color)
        form.addRow(tr("Border colour"), self.border_color_btn)
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

        def _top_aligned(page: QWidget) -> QWidget:
            # A form given the whole tab spreads its rows over the height;
            # keep them together at the top and scroll when they don't fit.
            from PySide6.QtWidgets import QScrollArea
            outer = QWidget()
            lay = QVBoxLayout(outer)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(page)
            lay.addStretch(1)
            scroll = QScrollArea()
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(outer)
            return scroll

        self.props.addWidget(_top_aligned(self._page_none()))      # 0: nothing selected
        self.props.addWidget(_top_aligned(self._page_frame()))     # 1
        self.props.addWidget(_top_aligned(self._page_text()))      # 2
        self.props.addWidget(_top_aligned(self._page_image()))     # 3
        self.props.addWidget(_top_aligned(self._page_cajetin()))   # 4
        self.props.addWidget(_top_aligned(self._page_scalebar()))  # 5
        self.props.addWidget(_top_aligned(self._page_norte()))     # 6
        self.props.addWidget(_top_aligned(self._page_leyenda()))   # 7
        self.props.addWidget(_top_aligned(self._page_forma()))     # 8
        self.props.addWidget(_top_aligned(self._page_cota()))      # 9
        self.props.addWidget(_top_aligned(self._page_cota_ang()))  # 10
        self.props.addWidget(_top_aligned(self._page_etiqueta()))  # 11
        self.props.addWidget(_top_aligned(self._page_perfil()))    # 12
        self._tabs.addTab(self.props, tr("Item properties"))

        refresh_btn = QPushButton(tr("Update all views"))
        refresh_btn.clicked.connect(self.refresh_all_frames)
        outer.addWidget(refresh_btn)
        self.auto_check = QCheckBox(tr("Auto-render"))
        self.auto_check.setToolTip(tr(
            "Re-render the views by themselves when the model changes "
            "(LayOut's Auto). Vector views keep their badge and wait for "
            "Update."))
        self.auto_check.setChecked(self._auto_render)
        self.auto_check.toggled.connect(self._set_auto_render)
        outer.addWidget(self.auto_check)
        export_btn = QPushButton(tr("Export PDF…"))
        export_btn.clicked.connect(self._on_export_pdf)
        outer.addWidget(export_btn)
        preview_btn = QPushButton(tr("Print preview…"))
        preview_btn.setToolTip(tr(
            "See the sheet exactly as it prints, and print it from there."))
        preview_btn.clicked.connect(self._on_print_preview)
        outer.addWidget(preview_btn)
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
        self._reload_scale_options()
        self.scale_combo.currentTextChanged.connect(self._on_frame_props)
        # A typed scale beyond the presets joins the document's list once
        # committed (Enter / focus out), so every frame offers it again.
        self.scale_combo.lineEdit().editingFinished.connect(
            self._on_scale_committed)
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
        # The model's display styles, one to one (SketchUp: LayOut viewports
        # pick any style). "Model style" = whatever is active in the model;
        # legacy "tecnico"/"lineas" frames map onto Hidden line / Wireframe.
        from core.style import BUILTIN_STYLES, user_styles
        self.style_combo.addItem(tr("Model style"), "sombreado")
        for preset in BUILTIN_STYLES:
            self.style_combo.addItem(tr(preset.name), f"style:{preset.name}")
        for saved in user_styles():
            # The user library too (saved names stay verbatim — they are the
            # user's own words, not ours to translate).
            self.style_combo.addItem(saved.name, f"style:{saved.name}")
        self.style_combo.addItem(
            tr("Vector (hidden lines removed)"), "vectorial")
        self.style_combo.currentIndexChanged.connect(self._on_frame_props)
        form.addRow(tr("Style"), self.style_combo)
        self.title_check = QCheckBox(tr("Title under the frame"))
        self.title_check.toggled.connect(self._on_frame_props)
        form.addRow("", self.title_check)
        self.annot_check = QCheckBox(tr(
            "Model annotations (dimensions and leader texts)"))
        self.annot_check.setToolTip(tr(
            "Draw the model's own cotas and texts in this frame, like "
            "LayOut does with SketchUp's. Hide their layer in the scene "
            "to leave them out."))
        self.annot_check.toggled.connect(self._on_frame_props)
        form.addRow("", self.annot_check)
        self.annot_mm_spin = QDoubleSpinBox()
        self.annot_mm_spin.setRange(1.0, 12.0)
        self.annot_mm_spin.setSingleStep(0.2)
        self.annot_mm_spin.setSuffix(" mm")
        self.annot_mm_spin.setValue(2.8)
        self.annot_mm_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Annotation text height"), self.annot_mm_spin)
        self.km_check = QCheckBox(tr("Chainage marks on traced paths"))
        self.km_check.setToolTip(tr(
            "A tick and a 0+020 label every step along each traced path, "
            "measured as the profile does. Step «auto» is the one the "
            "profile picks, so plan and profile agree; type the same step "
            "in both to choose it."))
        self.km_check.toggled.connect(self._on_frame_props)
        form.addRow("", self.km_check)
        self.km_step_spin = QDoubleSpinBox()
        self.km_step_spin.setRange(0.0, 100000.0)
        self.km_step_spin.setDecimals(1)
        self.km_step_spin.setSuffix(" m")
        self.km_step_spin.setSpecialValueText(tr("auto"))
        self.km_step_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Chainage step"), self.km_step_spin)
        self.frame_border_check = QCheckBox(tr("Printed border"))
        self.frame_border_check.setToolTip(tr(
            "Draw the frame's outline in print. Off, the canvas still shows "
            "a light guide that never prints."))
        self.frame_border_check.toggled.connect(self._on_frame_props)
        form.addRow("", self.frame_border_check)
        self.frame_border_mm = QDoubleSpinBox()
        self.frame_border_mm.setRange(0.1, 2.0)
        self.frame_border_mm.setSingleStep(0.05)
        self.frame_border_mm.setSuffix(" mm")
        self.frame_border_mm.setValue(0.3)
        self.frame_border_mm.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Border width"), self.frame_border_mm)
        self.frame_border_btn = QPushButton()
        self.frame_border_btn.setFixedHeight(22)
        self.frame_border_btn.clicked.connect(
            lambda: self._pick_item_color("border_color",
                                          self.frame_border_btn))
        form.addRow(tr("Border colour"), self.frame_border_btn)
        scale_btn = QPushButton(tr("Add a scale label"))
        scale_btn.setToolTip(tr(
            "A text block bound to this frame: it reads the frame's scale "
            "({escala}), moves with the frame, and you can drag it anywhere "
            "and double-click to edit it."))
        scale_btn.clicked.connect(self._on_add_scale_label)
        form.addRow(scale_btn)
        self.grid_spin = QDoubleSpinBox()
        self.grid_spin.setRange(0.0, 1000.0)
        self.grid_spin.setSuffix(" m")
        self.grid_spin.setToolTip(tr("Coordinate grid spacing (0 = off)"))
        self.grid_spin.valueChanged.connect(self._on_frame_props)
        form.addRow(tr("Grid"), self.grid_spin)
        btn = QPushButton(tr("Update view"))
        btn.clicked.connect(self._on_refresh_selected_frame)
        form.addRow(btn)
        fit_btn = QPushButton(tr("Frame the model"))
        fit_btn.setToolTip(tr(
            "Centre the whole model in the frame at the largest common "
            "scale that fits (LayOut's Zoom Extents). Double-click the "
            "frame to pan, orbit and zoom the view by hand."))
        fit_btn.clicked.connect(self._on_zoom_extents_selected)
        form.addRow(fit_btn)
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
        self.text_edit.setToolTip(tr(
            "Dynamic fields: {proyecto} {autor} {lamina} {escala} {escena} "
            "{fecha} {archivo} {nombre} {hoja} {total}"))
        self.text_edit.setFixedHeight(70)
        self.text_edit.textChanged.connect(self._on_text_props)
        form.addRow(tr("Text"), self.text_edit)
        self.text_family = QFontComboBox()
        self.text_family.currentFontChanged.connect(self._on_text_family)
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
        self.text_underline = QCheckBox(tr("Underline"))
        self.text_underline.toggled.connect(self._on_text_props)
        style_row.addWidget(self.text_underline)
        form.addRow("", style_row)
        self.text_align = QComboBox()
        for label, key in ((tr("Left"), "left"), (tr("Center"), "center"),
                           (tr("Right"), "right")):
            self.text_align.addItem(label, key)
        self.text_align.currentIndexChanged.connect(self._on_text_align)
        form.addRow(tr("Alignment"), self.text_align)
        self.text_color_btn = QPushButton()
        self.text_color_btn.setFixedHeight(22)
        self.text_color_btn.clicked.connect(self._on_pick_text_color)
        form.addRow(tr("Colour"), self.text_color_btn)
        self.text_bg_check = QCheckBox(tr("Background"))
        self.text_bg_check.toggled.connect(self._on_text_bg_toggled)
        form.addRow("", self.text_bg_check)
        self.text_bg_btn = QPushButton()
        self.text_bg_btn.setFixedHeight(22)
        self.text_bg_btn.clicked.connect(self._on_pick_text_bg)
        form.addRow(tr("Background colour"), self.text_bg_btn)
        self.text_bg_opacity = self._opacity_spin("bg_opacity")
        form.addRow(tr("Background opacity"), self.text_bg_opacity)
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
        self._forma_form = form
        self.forma_stroke = QDoubleSpinBox()
        self.forma_stroke.setRange(0.1, 3.0)
        self.forma_stroke.setSingleStep(0.05)
        self.forma_stroke.setSuffix(" mm")
        self.forma_stroke.valueChanged.connect(self._on_forma_props)
        form.addRow(tr("Line width"), self.forma_stroke)
        self.forma_color_btn = QPushButton()
        self.forma_color_btn.setFixedHeight(22)
        self.forma_color_btn.clicked.connect(
            lambda: self._pick_forma_color("color", self.forma_color_btn))
        form.addRow(tr("Line colour"), self.forma_color_btn)
        self.forma_radius = QDoubleSpinBox()
        self.forma_radius.setRange(0.0, 100.0)
        self.forma_radius.setSingleStep(0.5)
        self.forma_radius.setSuffix(" mm")
        self.forma_radius.valueChanged.connect(self._on_forma_props)
        form.addRow(tr("Corner radius"), self.forma_radius)
        self.forma_sides = QDoubleSpinBox()
        self.forma_sides.setRange(3, 24)
        self.forma_sides.setDecimals(0)
        self.forma_sides.valueChanged.connect(self._on_forma_props)
        form.addRow(tr("Sides"), self.forma_sides)
        self.forma_fill = QCheckBox(tr("Fill"))
        self.forma_fill.toggled.connect(self._on_forma_props)
        form.addRow("", self.forma_fill)
        self.forma_fill_btn = QPushButton()
        self.forma_fill_btn.setFixedHeight(22)
        self.forma_fill_btn.clicked.connect(
            lambda: self._pick_forma_color("fill_color",
                                           self.forma_fill_btn))
        form.addRow(tr("Fill colour"), self.forma_fill_btn)
        self.forma_invert = QCheckBox(tr("Flip diagonal"))
        self.forma_invert.toggled.connect(self._on_forma_props)
        form.addRow("", self.forma_invert)
        return w

    def _forma_row_visible(self, widget, visible: bool) -> None:
        widget.setVisible(visible)
        label = self._forma_form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def _pick_forma_color(self, attr: str, button) -> None:
        from PySide6.QtWidgets import QColorDialog
        item = self._selected_item()
        if not isinstance(item, FormaCanvasItem):
            return
        col = QColorDialog.getColor(QColor(getattr(item.model, attr)),
                                    self, tr("Colour"))
        if col.isValid():
            self._panel_edit(item, {attr: col.name()})
            button.setStyleSheet(f"background: {col.name()};")

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
        self.cota_units = QComboBox()
        from core.units import UNIT_CHOICES
        self.cota_units.addItems(list(UNIT_CHOICES))
        self.cota_units.setToolTip(tr(
            "How the measurement reads: metres, centimetres, millimetres, "
            "decimal inches or feet, feet-and-inches, or fractional inches "
            "(1 1/2\"). For fractions, Decimals picks the finest denominator: "
            "0 = whole inches, 1 = 1/4, 2 = 1/16, 3 = 1/32, 4 = 1/64."))
        self.cota_units.currentTextChanged.connect(self._on_cota_props)
        form.addRow(tr("Units"), self.cota_units)
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
        self.cota_text_pos = QComboBox()
        for label, key in ((tr("Above the line"), "above"),
                           (tr("Centered on the line"), "centered"),
                           (tr("Below the line"), "below")):
            self.cota_text_pos.addItem(label, key)
        self.cota_text_pos.currentIndexChanged.connect(self._on_cota_props)
        form.addRow(tr("Text position"), self.cota_text_pos)
        self.cota_text_align = QComboBox()
        for label, key in ((tr("Aligned to the line"), "aligned"),
                           (tr("Horizontal"), "horizontal")):
            self.cota_text_align.addItem(label, key)
        self.cota_text_align.currentIndexChanged.connect(self._on_cota_props)
        form.addRow(tr("Text orientation"), self.cota_text_align)
        self.cota_text_same = QCheckBox(tr("Text colour = line colour"))
        self.cota_text_same.setChecked(True)
        self.cota_text_same.toggled.connect(self._on_cota_props)
        form.addRow("", self.cota_text_same)
        self.cota_text_color_btn = QPushButton()
        self.cota_text_color_btn.setFixedHeight(22)
        self.cota_text_color_btn.clicked.connect(self._on_pick_cota_text_color)
        form.addRow(tr("Text colour"), self.cota_text_color_btn)
        self.cota_bg_check = QCheckBox(tr("Text background"))
        self.cota_bg_check.toggled.connect(
            lambda on: self._toggle_item_bg("text_bg", on, self.cota_bg_btn))
        form.addRow("", self.cota_bg_check)
        self.cota_bg_btn = QPushButton()
        self.cota_bg_btn.setFixedHeight(22)
        self.cota_bg_btn.clicked.connect(
            lambda: self._pick_item_bg("text_bg", self.cota_bg_check,
                                       self.cota_bg_btn))
        form.addRow(tr("Background colour"), self.cota_bg_btn)
        self.cota_bg_opacity = self._opacity_spin("text_bg_opacity")
        form.addRow(tr("Background opacity"), self.cota_bg_opacity)
        return w

    def _page_etiqueta(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.et_text = QPlainTextEdit()
        self.et_text.setMaximumHeight(70)
        self.et_text.setToolTip(tr(
            "Dynamic fields: {proyecto} {autor} {lamina} {escala} {escena} "
            "{fecha} {archivo} {nombre} {hoja} {total}"))
        self.et_text.textChanged.connect(self._on_etiqueta_props)
        form.addRow(tr("Text"), self.et_text)
        self.et_size = QDoubleSpinBox()
        self.et_size.setRange(4.0, 72.0)
        self.et_size.setSuffix(" pt")
        self.et_size.setValue(11.0)
        self.et_size.valueChanged.connect(self._on_etiqueta_props)
        form.addRow(tr("Size"), self.et_size)
        et_style = QHBoxLayout()
        self.et_bold = QCheckBox(tr("Bold"))
        self.et_bold.toggled.connect(self._on_etiqueta_props)
        et_style.addWidget(self.et_bold)
        self.et_italic = QCheckBox(tr("Italic"))
        self.et_italic.toggled.connect(self._on_etiqueta_props)
        et_style.addWidget(self.et_italic)
        self.et_underline = QCheckBox(tr("Underline"))
        self.et_underline.toggled.connect(self._on_etiqueta_props)
        et_style.addWidget(self.et_underline)
        form.addRow("", et_style)
        self.et_arrow = QCheckBox(tr("Arrow head"))
        self.et_arrow.setChecked(True)
        self.et_arrow.toggled.connect(self._on_etiqueta_props)
        form.addRow("", self.et_arrow)
        self.et_stroke = QDoubleSpinBox()
        self.et_stroke.setRange(0.1, 1.5)
        self.et_stroke.setSingleStep(0.05)
        self.et_stroke.setSuffix(" mm")
        self.et_stroke.setValue(0.25)
        self.et_stroke.valueChanged.connect(self._on_etiqueta_props)
        form.addRow(tr("Line width"), self.et_stroke)
        self.et_color_btn = QPushButton()
        self.et_color_btn.setFixedHeight(22)
        self.et_color_btn.clicked.connect(
            lambda: self._pick_item_color("color", self.et_color_btn))
        form.addRow(tr("Colour"), self.et_color_btn)
        self.et_bg_check = QCheckBox(tr("Background"))
        self.et_bg_check.toggled.connect(
            lambda on: self._toggle_item_bg("bg_color", on, self.et_bg_btn))
        form.addRow("", self.et_bg_check)
        self.et_bg_btn = QPushButton()
        self.et_bg_btn.setFixedHeight(22)
        self.et_bg_btn.clicked.connect(
            lambda: self._pick_item_bg("bg_color", self.et_bg_check,
                                       self.et_bg_btn))
        form.addRow(tr("Background colour"), self.et_bg_btn)
        self.et_bg_opacity = self._opacity_spin("bg_opacity")
        form.addRow(tr("Background opacity"), self.et_bg_opacity)
        return w

    def _page_cota_ang(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.cang_text = QLineEdit()
        self.cang_text.setPlaceholderText(tr("(automatic)"))
        self.cang_text.editingFinished.connect(self._on_cota_ang_props)
        form.addRow(tr("Label"), self.cang_text)
        self.cang_radius = QDoubleSpinBox()
        self.cang_radius.setRange(2.0, 300.0)
        self.cang_radius.setSingleStep(0.5)
        self.cang_radius.setSuffix(" mm")
        self.cang_radius.valueChanged.connect(self._on_cota_ang_props)
        form.addRow(tr("Arc radius"), self.cang_radius)
        self.cang_text_mm = QDoubleSpinBox()
        self.cang_text_mm.setRange(1.0, 10.0)
        self.cang_text_mm.setSingleStep(0.2)
        self.cang_text_mm.setSuffix(" mm")
        self.cang_text_mm.valueChanged.connect(self._on_cota_ang_props)
        form.addRow(tr("Text height"), self.cang_text_mm)
        self.cang_decimals = QDoubleSpinBox()
        self.cang_decimals.setRange(0, 4)
        self.cang_decimals.setDecimals(0)
        self.cang_decimals.valueChanged.connect(self._on_cota_ang_props)
        form.addRow(tr("Decimals"), self.cang_decimals)
        self.cang_ends = QComboBox()
        for label, key in ((tr("Arrows"), "arrow"),
                           (tr("Oblique ticks"), "tick"),
                           (tr("None"), "none")):
            self.cang_ends.addItem(label, key)
        self.cang_ends.currentIndexChanged.connect(self._on_cota_ang_props)
        form.addRow(tr("Ends"), self.cang_ends)
        self.cang_stroke = QDoubleSpinBox()
        self.cang_stroke.setRange(0.1, 1.5)
        self.cang_stroke.setSingleStep(0.05)
        self.cang_stroke.setSuffix(" mm")
        self.cang_stroke.valueChanged.connect(self._on_cota_ang_props)
        form.addRow(tr("Line width"), self.cang_stroke)
        self.cang_color_btn = QPushButton()
        self.cang_color_btn.setFixedHeight(22)
        self.cang_color_btn.clicked.connect(
            lambda: self._pick_item_color("color", self.cang_color_btn))
        form.addRow(tr("Colour"), self.cang_color_btn)
        self.cang_text_color_btn = QPushButton()
        self.cang_text_color_btn.setFixedHeight(22)
        self.cang_text_color_btn.clicked.connect(
            lambda: self._pick_item_color("text_color",
                                          self.cang_text_color_btn))
        form.addRow(tr("Text colour"), self.cang_text_color_btn)
        self.cang_bg_check = QCheckBox(tr("Text background"))
        self.cang_bg_check.toggled.connect(
            lambda on: self._toggle_item_bg("text_bg", on, self.cang_bg_btn))
        form.addRow("", self.cang_bg_check)
        self.cang_bg_btn = QPushButton()
        self.cang_bg_btn.setFixedHeight(22)
        self.cang_bg_btn.clicked.connect(
            lambda: self._pick_item_bg("text_bg", self.cang_bg_check,
                                       self.cang_bg_btn))
        form.addRow(tr("Background colour"), self.cang_bg_btn)
        self.cang_bg_opacity = self._opacity_spin("text_bg_opacity")
        form.addRow(tr("Background opacity"), self.cang_bg_opacity)
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
        # -- design: the built-in looks, then the user's saved title blocks
        design_row = QWidget()
        dh = QHBoxLayout(design_row)
        dh.setContentsMargins(0, 0, 0, 0)
        self.caj_design = QComboBox()
        self.caj_design.setToolTip(tr(
            "A built-in look, or one of your saved title blocks (rows, "
            "size and look). The rows stay yours when you pick a look."))
        self.caj_design.currentIndexChanged.connect(self._on_cajetin_design)
        dh.addWidget(self.caj_design, 1)
        tpl_btn = QPushButton(tr("Templates…"))
        tpl_btn.setToolTip(tr(
            "Save this title block as a template, apply one, or make one "
            "the default for new title blocks."))
        tpl_btn.clicked.connect(self._on_cajetin_templates_menu)
        dh.addWidget(tpl_btn)
        form.addRow(tr("Design"), design_row)
        self._reload_cajetin_designs()
        self.caj_table = QTableWidget(0, 2)
        self.caj_table.setHorizontalHeaderLabels([tr("Field"), tr("Value")])
        self.caj_table.horizontalHeader().setStretchLastSection(True)
        self.caj_table.verticalHeader().setVisible(False)
        self.caj_table.setMinimumHeight(150)
        self.caj_table.itemChanged.connect(self._on_cajetin_props)
        form.addRow(self.caj_table)
        btns = QWidget()
        hb = QHBoxLayout(btns)
        hb.setContentsMargins(0, 0, 0, 0)
        add_btn = QPushButton(tr("+ Row"))
        add_btn.clicked.connect(self._on_cajetin_add_row)
        del_btn = QPushButton(tr("− Row"))
        del_btn.clicked.connect(self._on_cajetin_del_row)
        hb.addWidget(add_btn)
        hb.addWidget(del_btn)
        hb.addStretch(1)
        form.addRow(btns)
        self.caj_w = QDoubleSpinBox()
        self.caj_w.setRange(30.0, 2000.0)
        self.caj_w.setSuffix(" mm")
        self.caj_w.valueChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Width"), self.caj_w)
        self.caj_h = QDoubleSpinBox()
        self.caj_h.setRange(10.0, 500.0)
        self.caj_h.setSuffix(" mm")
        self.caj_h.valueChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Height"), self.caj_h)
        self.caj_columns = QDoubleSpinBox()
        self.caj_columns.setRange(1, 4)
        self.caj_columns.setDecimals(0)
        self.caj_columns.valueChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Columns"), self.caj_columns)
        self.caj_label_mm = QDoubleSpinBox()
        self.caj_label_mm.setRange(0.0, 150.0)
        self.caj_label_mm.setSingleStep(1.0)
        self.caj_label_mm.setSuffix(" mm")
        self.caj_label_mm.setSpecialValueText(tr("automatic"))
        self.caj_label_mm.valueChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Label column"), self.caj_label_mm)
        self.caj_layout = QComboBox()
        for label, key in ((tr("Grid"), "grid"), (tr("Header band"), "banded"),
                           (tr("Minimal"), "minimal")):
            self.caj_layout.addItem(label, key)
        self.caj_layout.currentIndexChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Layout"), self.caj_layout)
        self.caj_corner = QComboBox()
        for label, key in ((tr("Square"), "square"), (tr("Rounded"), "rounded"),
                           (tr("Chamfered"), "chamfer")):
            self.caj_corner.addItem(label, key)
        self.caj_corner.currentIndexChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Corners"), self.caj_corner)
        self.caj_radius = QDoubleSpinBox()
        self.caj_radius.setRange(0.5, 25.0)
        self.caj_radius.setSingleStep(0.5)
        self.caj_radius.setSuffix(" mm")
        self.caj_radius.valueChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Corner radius"), self.caj_radius)
        self.caj_border = QDoubleSpinBox()
        self.caj_border.setRange(0.1, 2.5)
        self.caj_border.setSingleStep(0.05)
        self.caj_border.setSuffix(" mm")
        self.caj_border.valueChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Outer border"), self.caj_border)
        self.caj_line = QDoubleSpinBox()
        self.caj_line.setRange(0.05, 1.5)
        self.caj_line.setSingleStep(0.05)
        self.caj_line.setSuffix(" mm")
        self.caj_line.valueChanged.connect(self._on_cajetin_props)
        form.addRow(tr("Inner lines"), self.caj_line)
        self.caj_double = QCheckBox(tr("Double border"))
        self.caj_double.toggled.connect(self._on_cajetin_props)
        form.addRow("", self.caj_double)
        self.caj_fill_check = QCheckBox(tr("Fill (labels / band)"))
        self.caj_fill_check.toggled.connect(self._on_cajetin_fill_toggled)
        form.addRow("", self.caj_fill_check)
        self.caj_fill_btn = QPushButton()
        self.caj_fill_btn.setFixedHeight(22)
        self.caj_fill_btn.clicked.connect(
            lambda: self._pick_item_bg("fill_color", self.caj_fill_check,
                                       self.caj_fill_btn))
        form.addRow(tr("Fill colour"), self.caj_fill_btn)
        self.caj_color_btns = {}
        for attr, label in (("label_color", tr("Label colour")),
                            ("text_color", tr("Text colour")),
                            ("line_color", tr("Line colour"))):
            btn = QPushButton()
            btn.setFixedHeight(22)
            btn.clicked.connect(
                lambda _c=False, a=attr, b=btn: self._pick_item_color(a, b))
            form.addRow(label, btn)
            self.caj_color_btns[attr] = btn
        return w

    def _reload_cajetin_designs(self) -> None:
        """The design combo: "(custom)", the built-in looks, then the
        user's saved title blocks."""
        from core.composition import CAJETIN_DESIGNS
        combo = self.caj_design
        was = self._updating
        self._updating = True
        combo.clear()
        combo.addItem(tr("(custom)"), "")
        for key, label, _fields in CAJETIN_DESIGNS:
            combo.addItem(tr(label), key)
        names = self.cajetin_template_names()
        if names:
            combo.insertSeparator(combo.count())
            for n in names:
                combo.addItem(n, "tpl:" + n)
        self._updating = was

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

    def _page_perfil(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.pf_path = QComboBox()
        self.pf_path.currentIndexChanged.connect(self._on_perfil_props)
        form.addRow(tr("Traced path"), self.pf_path)
        self.pf_scale = QComboBox()
        self.pf_scale.setEditable(True)
        self.pf_scale.addItem(tr("Fit to width"), 0.0)
        for n in COMMON_SCALES:
            self.pf_scale.addItem(f"1:{n}", float(n))
        self.pf_scale.currentTextChanged.connect(self._on_perfil_props)
        form.addRow(tr("Horizontal scale"), self.pf_scale)
        self.pf_exag = QDoubleSpinBox()
        self.pf_exag.setRange(0.0, 100.0)
        self.pf_exag.setDecimals(1)
        self.pf_exag.setSingleStep(1.0)
        self.pf_exag.setPrefix("×")
        self.pf_exag.setSpecialValueText(tr("auto (fit the height)"))
        self.pf_exag.valueChanged.connect(self._on_perfil_props)
        form.addRow(tr("Vertical exaggeration"), self.pf_exag)
        self.pf_grid = QCheckBox(tr("Grid"))
        self.pf_grid.toggled.connect(self._on_perfil_props)
        form.addRow("", self.pf_grid)
        self.pf_grid_h = QDoubleSpinBox()
        self.pf_grid_h.setRange(0.0, 100000.0)
        self.pf_grid_h.setDecimals(1)
        self.pf_grid_h.setSuffix(" m")
        self.pf_grid_h.setSpecialValueText(tr("auto"))
        self.pf_grid_h.valueChanged.connect(self._on_perfil_props)
        form.addRow(tr("Chainage step"), self.pf_grid_h)
        self.pf_grid_v = QDoubleSpinBox()
        self.pf_grid_v.setRange(0.0, 10000.0)
        self.pf_grid_v.setDecimals(1)
        self.pf_grid_v.setSuffix(" m")
        self.pf_grid_v.setSpecialValueText(tr("auto"))
        self.pf_grid_v.valueChanged.connect(self._on_perfil_props)
        form.addRow(tr("Elevation step"), self.pf_grid_v)
        self.pf_fill = QCheckBox(tr("Tint the ground"))
        self.pf_fill.toggled.connect(self._on_perfil_props)
        form.addRow("", self.pf_fill)
        self.pf_title = QLineEdit()
        self.pf_title.setPlaceholderText(tr("Longitudinal profile — <path>"))
        self.pf_title.textChanged.connect(self._on_perfil_props)
        form.addRow(tr("Title"), self.pf_title)
        self.pf_text = QDoubleSpinBox()
        self.pf_text.setRange(1.0, 8.0)
        self.pf_text.setDecimals(1)
        self.pf_text.setSingleStep(0.2)
        self.pf_text.setSuffix(" mm")
        self.pf_text.valueChanged.connect(self._on_perfil_props)
        form.addRow(tr("Text size"), self.pf_text)
        self.pf_w = QDoubleSpinBox()
        self.pf_w.setRange(20.0, 2000.0)
        self.pf_w.setSuffix(" mm")
        self.pf_w.valueChanged.connect(self._on_perfil_props)
        form.addRow(tr("Width"), self.pf_w)
        self.pf_h = QDoubleSpinBox()
        self.pf_h.setRange(15.0, 2000.0)
        self.pf_h.setSuffix(" mm")
        self.pf_h.valueChanged.connect(self._on_perfil_props)
        form.addRow(tr("Height"), self.pf_h)
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
        QTimer.singleShot(0, self._auto_render_stale)
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
        default = self.default_template_name()
        comp = self._composition_from_template(default) if default else None
        if comp is None:
            comp = Composicion(name=tr("Sheet {n}", n=len(comps) + 1))
            comp.frames.append(comp.default_frame())
        else:
            comp.name = tr("Sheet {n}", n=len(comps) + 1)
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
        # The selection lives on the items, and the items die with the
        # canvas: every rebuild — the auto-render pass after a scale or size
        # edit, a page change, a title-block field — dropped it, so each
        # property change in the panel meant clicking the frame again for
        # the next one (Marco, 2026-09-05). Remember the selected MODELS and
        # pick their new items up below; a caller's _pending_sel still wins.
        keep = [it.model for it in self.canvas.selectedItems()
                if isinstance(it, _SheetItem)]
        # canvas.clear() below deletes EVERY item — including the snap
        # marker and rubber-band preview the canvas view may be holding
        # mid-placement (undo between the two clicks is routine). Drop the
        # placement first or the next mouse move touches dead C++ objects.
        if hasattr(self, "_view"):
            self._view.cancel_placement()
        # Likewise the frame whose view is being edited in place: its item
        # dies with the canvas, and ending the edit afterwards (the next
        # double-click does) would touch a deleted C++ object.
        self._view_edit = None
        self._view_drag = None
        self._reproject_anchored_cotas()
        self._set_field_context(self.comp)
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
        if getattr(self.comp, "border", False):
            border_item = _SheetBorderCanvasItem(self.comp)
            border_item.setZValue(1e6)            # above every item…
            border_item.setAcceptedMouseButtons(Qt.NoButton)   # …but inert
            border_item.setAcceptHoverEvents(False)
            self.canvas.addItem(border_item)

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
        for ca in getattr(self.comp, "cotas_ang", []) or []:
            self.canvas.addItem(CotaAngularCanvasItem(self, ca))
        for et in getattr(self.comp, "etiquetas", []) or []:
            self.canvas.addItem(EtiquetaCanvasItem(self, et))
        for pf in getattr(self.comp, "perfiles", []) or []:
            self.canvas.addItem(PerfilItem(self, pf))
        if self.comp.cajetin is not None:
            self.canvas.addItem(CajetinItem(self, self.comp.cajetin))
        if keep:
            for it in self.canvas.items():
                if isinstance(it, _SheetItem) and any(it.model is m for m in keep):
                    it.setSelected(True)

        self.paper_combo.setCurrentText(self.comp.paper)
        self.landscape_check.setChecked(self.comp.landscape)
        if hasattr(self, "border_check"):
            self._sync_border_panel()
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
                self._reload_scale_options()
                f: MarcoVista = item.model
                idx = self.view_combo.findData(f.view_key)
                self.view_combo.setCurrentIndex(max(idx, 0))
                self.scale_combo.setCurrentText(f"1:{f.scale_n:g}")
                self.fw_spin.setValue(f.w_mm)
                self.fh_spin.setValue(f.h_mm)
                skey = {"tecnico": "style:Hidden line",
                        "lineas": "style:Wireframe"}.get(f.style, f.style)
                sidx = self.style_combo.findData(skey)
                self.style_combo.setCurrentIndex(max(sidx, 0))
                self.title_check.setChecked(f.show_title)
                self.annot_check.setChecked(getattr(f, "annotations", False))
                self.annot_mm_spin.setValue(
                    float(getattr(f, "annot_text_mm", 2.8) or 2.8))
                self.km_check.setChecked(bool(getattr(f, "km_marks", False)))
                self.km_step_spin.setValue(
                    float(getattr(f, "km_step_m", 0.0) or 0.0))
                self.frame_border_check.setChecked(
                    bool(getattr(f, "border", False)))
                self.frame_border_mm.setValue(
                    float(getattr(f, "border_mm", 0.3) or 0.3))
                self.frame_border_btn.setStyleSheet(
                    f"background: {getattr(f, 'border_color', '#282e36')};")
                self.grid_spin.setValue(f.grid_m)
                self.props.setCurrentIndex(1)
            elif isinstance(item, TextItem):
                t: TextoItem = item.model
                if self.text_edit.toPlainText() != t.text:
                    self.text_edit.setPlainText(t.text)
                self.text_size.setValue(t.size_pt)
                self.text_bold.setChecked(t.bold)
                self.text_italic.setChecked(t.italic)
                self.text_underline.setChecked(
                    bool(getattr(t, "underline", False)))
                from PySide6.QtGui import QFont as _QF
                self.text_family.setCurrentFont(_QF(t.family))
                aidx = self.text_align.findData(t.align)
                self.text_align.setCurrentIndex(max(aidx, 0))
                self.text_color_btn.setStyleSheet(
                    f"background: {t.color};")
                bg = getattr(t, "bg_color", "") or ""
                self.text_bg_check.setChecked(bool(bg))
                self.text_bg_btn.setStyleSheet(
                    f"background: {bg};" if bg else "")
                self.text_bg_opacity.setValue(
                    100.0 * float(getattr(t, "bg_opacity", 1.0)))
                self.props.setCurrentIndex(2)
            elif isinstance(item, ImageItem):
                self.img_label.setText(item.model.path or "—")
                self.props.setCurrentIndex(3)
            elif isinstance(item, CajetinItem):
                c = item.model
                self.caj_table.blockSignals(True)
                self.caj_table.setRowCount(len(c.campos))
                for i, (label, value) in enumerate(c.campos):
                    self.caj_table.setItem(
                        i, 0, QTableWidgetItem(str(label)))
                    self.caj_table.setItem(
                        i, 1, QTableWidgetItem(str(value)))
                self.caj_table.blockSignals(False)
                self.caj_w.setValue(c.w_mm)
                self.caj_h.setValue(c.h_mm)
                self.caj_columns.setValue(c.columns)
                self.caj_border.setValue(c.border_mm)
                self.caj_line.setValue(c.line_mm)
                self.caj_label_mm.setValue(
                    float(getattr(c, "label_mm", 0.0) or 0.0))
                self.caj_layout.setCurrentIndex(max(0, self.caj_layout.findData(
                    getattr(c, "layout", "grid") or "grid")))
                self.caj_corner.setCurrentIndex(max(0, self.caj_corner.findData(
                    getattr(c, "corner", "square") or "square")))
                self.caj_radius.setValue(
                    float(getattr(c, "radius_mm", 3.0) or 3.0))
                self.caj_double.setChecked(
                    bool(getattr(c, "double_border", False)))
                fill = getattr(c, "fill_color", "") or ""
                self.caj_fill_check.setChecked(bool(fill))
                self.caj_fill_btn.setStyleSheet(
                    f"background: {fill};" if fill else "")
                for attr, btn in self.caj_color_btns.items():
                    btn.setStyleSheet(
                        f"background: {getattr(c, attr, '') or '#1e242c'};")
                self._reload_cajetin_designs()
                key = c.design_key() if hasattr(c, "design_key") else ""
                self.caj_design.setCurrentIndex(
                    max(0, self.caj_design.findData(key)) if key else 0)
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
                fm = item.model
                fillable = fm.kind in ("rect", "elipse", "poligono")
                self.forma_stroke.setValue(fm.stroke_mm)
                self.forma_fill.setChecked(fm.fill)
                self.forma_invert.setChecked(fm.invert)
                self.forma_radius.setValue(fm.radius_mm)
                self.forma_sides.setValue(fm.sides)
                self.forma_color_btn.setStyleSheet(
                    f"background: {fm.color};")
                self.forma_fill_btn.setStyleSheet(
                    f"background: {fm.fill_color};")
                self.forma_invert.setVisible(
                    fm.kind in ("linea", "flecha"))
                self.forma_fill.setVisible(fillable)
                self._forma_row_visible(self.forma_radius,
                                        fm.kind == "rect")
                self._forma_row_visible(self.forma_sides,
                                        fm.kind == "poligono")
                self._forma_row_visible(self.forma_fill_btn, fillable)
                self.props.setCurrentIndex(8)
            elif isinstance(item, CotaCanvasItem):
                self.cota_scale.setCurrentText(f"1:{item.model.scale_n:g}")
                self.cota_text.setText(item.model.text)
                self.cota_sep.setValue(item.model.sep_mm)
                self.cota_text_mm.setValue(item.model.text_mm)
                self.cota_decimals.setValue(item.model.decimals)
                self.cota_units.setCurrentText(
                    getattr(item.model, "units", "m") or "m")
                eidx = self.cota_ends.findData(item.model.ends)
                self.cota_ends.setCurrentIndex(max(eidx, 0))
                self.cota_stroke.setValue(item.model.stroke_mm)
                self.cota_color_btn.setStyleSheet(
                    f"background: {item.model.color};")
                pidx = self.cota_text_pos.findData(
                    getattr(item.model, "text_pos", "above") or "above")
                self.cota_text_pos.setCurrentIndex(max(pidx, 0))
                aidx = self.cota_text_align.findData(
                    getattr(item.model, "text_align", "aligned") or "aligned")
                self.cota_text_align.setCurrentIndex(max(aidx, 0))
                tcol = getattr(item.model, "text_color", "") or ""
                self.cota_text_same.setChecked(not tcol)
                self.cota_text_color_btn.setStyleSheet(
                    f"background: {tcol or item.model.color};")
                tbg = getattr(item.model, "text_bg", "") or ""
                self.cota_bg_check.setChecked(bool(tbg))
                self.cota_bg_btn.setStyleSheet(
                    f"background: {tbg};" if tbg else "")
                self.cota_bg_opacity.setValue(100.0 * float(
                    getattr(item.model, "text_bg_opacity", 1.0)))
                self.props.setCurrentIndex(9)
            elif isinstance(item, EtiquetaCanvasItem):
                m = item.model
                if self.et_text.toPlainText() != m.text:
                    self.et_text.setPlainText(m.text)
                self.et_size.setValue(m.size_pt)
                self.et_bold.setChecked(m.bold)
                self.et_italic.setChecked(bool(getattr(m, "italic", False)))
                self.et_underline.setChecked(
                    bool(getattr(m, "underline", False)))
                self.et_arrow.setChecked(m.arrow)
                self.et_stroke.setValue(m.stroke_mm)
                self.et_color_btn.setStyleSheet(f"background: {m.color};")
                self.et_bg_check.setChecked(bool(m.bg_color))
                self.et_bg_btn.setStyleSheet(
                    f"background: {m.bg_color};" if m.bg_color else "")
                self.et_bg_opacity.setValue(100.0 * float(m.bg_opacity))
                self.props.setCurrentIndex(11)
            elif isinstance(item, PerfilItem):
                m = item.model
                self._reload_perfil_paths()
                self.pf_path.setCurrentIndex(
                    max(0, self.pf_path.findData(int(m.path_index))))
                self.pf_scale.setCurrentText(
                    tr("Fit to width") if not m.scale_n else f"1:{m.scale_n:g}")
                self.pf_exag.setValue(float(m.exag))
                self.pf_grid.setChecked(bool(m.grid))
                self.pf_grid_h.setValue(float(m.grid_h_m))
                self.pf_grid_v.setValue(float(m.grid_v_m))
                self.pf_fill.setChecked(bool(m.fill))
                if self.pf_title.text() != m.title:
                    self.pf_title.setText(m.title)
                self.pf_text.setValue(float(m.text_mm))
                self.pf_w.setValue(float(m.w_mm))
                self.pf_h.setValue(float(m.h_mm))
                self.props.setCurrentIndex(12)
            elif isinstance(item, CotaAngularCanvasItem):
                m = item.model
                self.cang_text.setText(m.text)
                self.cang_radius.setValue(m.radius_mm)
                self.cang_text_mm.setValue(m.text_mm)
                self.cang_decimals.setValue(m.decimals)
                eidx = self.cang_ends.findData(m.ends)
                self.cang_ends.setCurrentIndex(max(eidx, 0))
                self.cang_stroke.setValue(m.stroke_mm)
                self.cang_color_btn.setStyleSheet(f"background: {m.color};")
                self.cang_text_color_btn.setStyleSheet(
                    f"background: {m.text_color or m.color};")
                abg = getattr(m, "text_bg", "") or ""
                self.cang_bg_check.setChecked(bool(abg))
                self.cang_bg_btn.setStyleSheet(
                    f"background: {abg};" if abg else "")
                self.cang_bg_opacity.setValue(
                    100.0 * float(getattr(m, "text_bg_opacity", 1.0)))
                self.props.setCurrentIndex(10)
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
    def _follow_commands(self, model, after: dict, before: dict) -> list:
        """Texts bound to a moved frame move by the same delta (one undo
        step with the frame): the movable scale label stays put relative
        to its view."""
        if not isinstance(model, MarcoVista) or not model.uid:
            return []
        dx = float(after.get("x_mm", before.get("x_mm", 0.0))) - float(
            before.get("x_mm", after.get("x_mm", 0.0)))
        dy = float(after.get("y_mm", before.get("y_mm", 0.0))) - float(
            before.get("y_mm", after.get("y_mm", 0.0)))
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return []
        return [EditItemCommand(t, {"x_mm": t.x_mm + dx, "y_mm": t.y_mm + dy})
                for t in self.comp.texts
                if getattr(t, "frame_uid", "") == model.uid
                and getattr(t, "follow", True)]

    def note_drag_start(self) -> None:
        """Called when any item is pressed: remember where every selected
        item was, so a drag that moved the whole selection (a group) can
        be undone as one step."""
        self._drag_snapshot = {
            id(it.model): (float(it.model.x_mm), float(it.model.y_mm))
            for it in self.canvas.selectedItems() if isinstance(it, _SheetItem)}

    def _group_drag_commands(self, model) -> list:
        snap = getattr(self, "_drag_snapshot", None) or {}
        cmds = []
        for it in self.canvas.selectedItems():
            if not isinstance(it, _SheetItem) or it.model is model:
                continue
            was = snap.get(id(it.model))
            if was is None:
                continue
            m = it.model
            if abs(m.x_mm - was[0]) > 1e-9 or abs(m.y_mm - was[1]) > 1e-9:
                cmds.append(EditItemCommand(
                    m, {"x_mm": m.x_mm, "y_mm": m.y_mm},
                    before={"x_mm": was[0], "y_mm": was[1]}))
        return cmds

    def push_geometry_edit(self, model, after: dict, before: dict) -> None:
        extra = self._follow_commands(model, after, before)
        extra += self._group_drag_commands(model)
        self._drag_snapshot = {}
        if extra:
            self.history.execute(CompoundCommand(
                [EditItemCommand(model, after, before)] + extra))
            self._rebuild_canvas()
            for it in self.canvas.items():
                if isinstance(it, _SheetItem) and it.model is model:
                    it.setSelected(True)
            return
        self.history.execute(EditItemCommand(model, after, before))

    def add_scale_label(self, frame) -> TextoItem:
        """A movable scale label for *frame*: a bound text block under its
        bottom-right corner, "ESC. {escala}", bold."""
        import uuid
        if not frame.uid:
            frame.uid = uuid.uuid4().hex
        item = TextoItem(x_mm=frame.x_mm + frame.w_mm - 40.0,
                         y_mm=frame.y_mm + frame.h_mm + 1.5, w_mm=40.0,
                         text="ESC. {escala}", size_pt=10.0, bold=True,
                         align="right", frame_uid=frame.uid, follow=True)
        item.z = self._next_z()
        self._pending_sel = item
        self.history.execute(AddItemCommand(self.comp, item))
        return item

    def _on_add_scale_label(self) -> None:
        it = self._selected_item()
        if isinstance(it, FrameItem):
            self.add_scale_label(it.model)

    def on_item_geometry(self, item: _SheetItem, final: bool = False) -> None:
        if isinstance(item, FrameItem) and final:
            self.render_cache.pop(id(item.model), None)
            self.hlr_cache.pop(id(item.model), None)
            self.snap_cache.pop(id(item.model), None)
            self.annot_cache.pop(id(item.model), None)
            item.update()
        if isinstance(item, FrameItem) and not self._updating \
                and item is self._selected_item():
            self._updating = True
            self.fw_spin.setValue(item.model.w_mm)
            self.fh_spin.setValue(item.model.h_mm)
            self._updating = False

    # ---- Sheet templates (QGIS layout templates) ------------------------------
    @staticmethod
    def templates_dir():
        from pathlib import Path
        from PySide6.QtCore import QStandardPaths
        base = (QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
                or str(Path.home() / ".ingetrazo"))
        d = Path(base) / "plantillas"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def template_names(self) -> list:
        return sorted(p.stem for p in self.templates_dir().glob("*.json"))

    def save_template(self, name: str):
        """Write the current sheet (every item, page settings, border) as a
        reusable template; frames keep their view bindings by name."""
        import json
        name = (name or "").strip()
        if not name:
            return None
        safe = "".join(ch if ch not in '/\\:*?"<>|' else "_" for ch in name)
        path = self.templates_dir() / f"{safe}.json"
        d = self.comp.to_dict()
        d["name"] = name
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path

    def _composition_from_template(self, name: str):
        import json
        import uuid
        path = self.templates_dir() / f"{name}.json"
        if not path.is_file():
            return None
        try:
            comp = Composicion.from_dict(json.loads(
                path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 — a broken template is skipped
            return None
        for f in comp.frames:               # fresh identities per sheet
            f.uid = uuid.uuid4().hex
        for ct in comp.cotas:
            ct.anchor_uid, ct.a_world, ct.b_world = "", None, None
        return comp

    def new_sheet_from_template(self, name: str):
        comps = self._scene().compositions
        comp = self._composition_from_template(name)
        if comp is None:
            return None
        comp.name = tr("Sheet {n}", n=len(comps) + 1)
        comps.append(comp)
        self.comp = comp
        self._mark_dirty()
        self._reload_comp_combo()
        self._rebuild_canvas()
        return comp

    @staticmethod
    def default_template_name():
        from PySide6.QtCore import QSettings
        name = str(QSettings().value("composer/default_template", "") or "")
        return name or None

    @staticmethod
    def set_default_template(name) -> None:
        from PySide6.QtCore import QSettings
        QSettings().setValue("composer/default_template", name or "")

    def _on_templates_menu(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMenu
        from PySide6.QtGui import QCursor, QDesktopServices
        from PySide6.QtCore import QUrl
        menu = QMenu(self)
        save = menu.addAction(tr("Save this sheet as a template…"))
        names = self.template_names()
        new_menu = menu.addMenu(tr("New sheet from template"))
        new_acts = {new_menu.addAction(n): n for n in names}
        new_menu.setEnabled(bool(names))
        def_menu = menu.addMenu(tr("Default template for new sheets"))
        current = self.default_template_name()
        none_act = def_menu.addAction(tr("(none — an empty sheet)"))
        none_act.setCheckable(True)
        none_act.setChecked(not current)
        def_acts = {}
        for n in names:
            a = def_menu.addAction(n)
            a.setCheckable(True)
            a.setChecked(n == current)
            def_acts[a] = n
        menu.addSeparator()
        folder = menu.addAction(tr("Open the templates folder"))
        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if chosen is save:
            name, ok = QInputDialog.getText(
                self, tr("Save template"), tr("Template name:"),
                text=self.comp.name)
            if ok and name.strip():
                self.save_template(name)
                self.statusBar().showMessage(
                    tr("Template saved: {name}", name=name.strip()), 4000)
        elif chosen in new_acts:
            self.new_sheet_from_template(new_acts[chosen])
        elif chosen is none_act:
            self.set_default_template(None)
        elif chosen in def_acts:
            self.set_default_template(def_acts[chosen])
        elif chosen is folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(
                str(self.templates_dir())))

    # ---- Arrange: align / distribute / duplicate (QGIS's Align toolbar) -----
    def _selected_sheet_items(self) -> list:
        return [it for it in self.canvas.selectedItems()
                if isinstance(it, _SheetItem)
                and not getattr(it.model, "locked", False)]

    @staticmethod
    def _item_box(it) -> tuple:
        w, h = it.size_mm()
        m = it.model
        return (float(m.x_mm), float(m.y_mm), float(w), float(h))

    def _apply_moves(self, moves: list) -> None:
        """``moves`` = [(item, new_x, new_y)] → one undo step, rebuilt canvas,
        selection kept."""
        cmds = []
        for it, nx, ny in moves:
            m = it.model
            changes = {}
            if abs(nx - m.x_mm) > 1e-9:
                changes["x_mm"] = nx
            if abs(ny - m.y_mm) > 1e-9:
                changes["y_mm"] = ny
            if changes:
                cmds.append(EditItemCommand(m, changes))
        if not cmds:
            return
        keep = [it.model for it, _x, _y in moves]
        self.history.execute(CompoundCommand(cmds), notify=False)
        self._mark_dirty()
        self._rebuild_canvas()
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and any(it.model is k for k in keep):
                it.setSelected(True)

    def align_selected(self, mode: str) -> None:
        """left | right | top | bottom | hcenter | vcenter, against the
        selection's bounding box (QGIS)."""
        items = self._selected_sheet_items()
        if len(items) < 2:
            return
        boxes = {id(it): self._item_box(it) for it in items}
        x0 = min(b[0] for b in boxes.values())
        x1 = max(b[0] + b[2] for b in boxes.values())
        y0 = min(b[1] for b in boxes.values())
        y1 = max(b[1] + b[3] for b in boxes.values())
        moves = []
        for it in items:
            x, y, w, h = boxes[id(it)]
            nx, ny = x, y
            if mode == "left":
                nx = x0
            elif mode == "right":
                nx = x1 - w
            elif mode == "hcenter":
                nx = (x0 + x1) / 2 - w / 2
            elif mode == "top":
                ny = y0
            elif mode == "bottom":
                ny = y1 - h
            elif mode == "vcenter":
                ny = (y0 + y1) / 2 - h / 2
            moves.append((it, nx, ny))
        self._apply_moves(moves)

    def distribute_selected(self, axis: str) -> None:
        """Equal gaps between the selected items along ``x`` or ``y``."""
        items = self._selected_sheet_items()
        if len(items) < 3:
            return
        k = 0 if axis == "x" else 1
        boxes = {id(it): self._item_box(it) for it in items}
        order = sorted(items, key=lambda it: boxes[id(it)][k])
        first, last = boxes[id(order[0])], boxes[id(order[-1])]
        span = (last[k] + last[k + 2]) - first[k]
        inner = sum(boxes[id(it)][k + 2] for it in order)
        gap = (span - inner) / (len(order) - 1)
        pos = first[k]
        moves = []
        for it in order:
            x, y, w, h = boxes[id(it)]
            if k == 0:
                moves.append((it, pos, y))
            else:
                moves.append((it, x, pos))
            pos += (w if k == 0 else h) + gap
        self._apply_moves(moves)

    def sync_group_selection(self, item) -> None:
        """Selecting one member of a group selects the whole group."""
        if getattr(self, "_syncing_sel", False):
            return
        gid = getattr(item.model, "group_id", "")
        if not gid:
            return
        self._syncing_sel = True
        try:
            for it in self.canvas.items():
                if (isinstance(it, _SheetItem)
                        and getattr(it.model, "group_id", "") == gid
                        and not it.isSelected()):
                    it.setSelected(True)
        finally:
            self._syncing_sel = False

    def _reselect(self, models) -> None:
        keep = list(models)
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and any(it.model is k for k in keep):
                it.setSelected(True)

    def group_selected(self) -> None:
        """Ctrl+G: the selected items become one group (the title block
        stays on its own)."""
        import uuid
        items = [it for it in self.canvas.selectedItems()
                 if isinstance(it, _SheetItem)
                 and not isinstance(it.model, Cajetin)]
        if len(items) < 2:
            self.statusBar().showMessage(
                tr("Select two or more items to group them."), 3000)
            return
        gid = uuid.uuid4().hex
        cmds = [EditItemCommand(it.model, {"group_id": gid}) for it in items]
        self.history.execute(CompoundCommand(cmds), notify=False)
        self._mark_dirty()
        self._rebuild_canvas()
        self._reselect([it.model for it in items])
        self.statusBar().showMessage(
            tr("{n} items grouped.", n=len(items)), 3000)

    def ungroup_selected(self) -> None:
        """Ctrl+Shift+G: dissolve every group touched by the selection."""
        gids = {getattr(it.model, "group_id", "")
                for it in self.canvas.selectedItems()
                if isinstance(it, _SheetItem)}
        gids.discard("")
        if not gids:
            return
        members = [m for m in self.comp.all_items()
                   if getattr(m, "group_id", "") in gids]
        cmds = [EditItemCommand(m, {"group_id": ""}) for m in members]
        self.history.execute(CompoundCommand(cmds), notify=False)
        self._mark_dirty()
        self._rebuild_canvas()
        self._reselect(members)
        self.statusBar().showMessage(tr("Ungrouped."), 3000)

    def lock_selected(self) -> None:
        """Ctrl+L: lock the selection; if every selected item is already
        locked, unlock them instead."""
        items = [it for it in self.canvas.selectedItems()
                 if isinstance(it, _SheetItem)]
        if not items:
            return
        lock = not all(getattr(it.model, "locked", False) for it in items)
        cmds = [EditItemCommand(it.model, {"locked": lock}) for it in items
                if getattr(it.model, "locked", False) != lock]
        if not cmds:
            return
        self.history.execute(CompoundCommand(cmds), notify=False)
        self._mark_dirty()
        self._rebuild_canvas()
        self._reselect([it.model for it in items])
        self.statusBar().showMessage(
            tr("{n} item(s) locked.", n=len(cmds)) if lock
            else tr("{n} item(s) unlocked.", n=len(cmds)), 3000)

    def duplicate_selected(self) -> None:
        """Ctrl+D: copies 5 mm down-right, on top, selected afterwards."""
        import copy
        import uuid
        items = [it for it in self.canvas.selectedItems()
                 if isinstance(it, _SheetItem)
                 and not isinstance(it.model, Cajetin)]
        if not items:
            return
        cmds, copies = [], []
        new_gids: dict = {}
        for it in items:
            m = copy.deepcopy(it.model)
            m.x_mm += 5.0
            m.y_mm += 5.0
            m.locked = False
            old_gid = getattr(m, "group_id", "")
            if old_gid:
                m.group_id = new_gids.setdefault(old_gid, uuid.uuid4().hex)
            if hasattr(m, "uid"):
                m.uid = uuid.uuid4().hex if isinstance(m, MarcoVista) else ""
            if hasattr(m, "anchor_uid"):
                m.anchor_uid, m.a_world, m.b_world = "", None, None
            m.z = self._next_z() + len(copies)
            cmds.append(AddItemCommand(self.comp, m))
            copies.append(m)
        self.history.execute(CompoundCommand(cmds), notify=False)
        self._mark_dirty()
        self.canvas.clearSelection()         # the copies become the selection
        self._rebuild_canvas()
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and any(it.model is c for c in copies):
                it.setSelected(True)
        self.statusBar().showMessage(
            tr("{n} item(s) duplicated.", n=len(copies)), 3000)


    # ---- Clipboard (Ctrl+C / Ctrl+X / Ctrl+V) --------------------------------
    #: The sheet clipboard: deep copies of the models, shared by every sheet
    #: and composer window so items travel between láminas. A copied text
    #: block or label also lands on the system clipboard as plain text.
    _clipboard: list = []
    _clipboard_from = None

    def _copyable(self) -> list:
        return [it.model for it in self.canvas.selectedItems()
                if isinstance(it, _SheetItem)
                and not isinstance(it.model, Cajetin)]

    def copy_selected(self) -> None:
        """Ctrl+C: the selected items go to the sheet clipboard."""
        import copy
        models = self._copyable()
        if not models:
            return
        ComposerWindow._clipboard = [copy.deepcopy(m) for m in models]
        ComposerWindow._clipboard_from = self.comp
        texts = [m.text for m in models
                 if isinstance(m, (TextoItem, EtiquetaItem)) and m.text]
        if texts:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText("\n".join(texts))
        self.statusBar().showMessage(
            tr("{n} item(s) copied.", n=len(models)), 3000)

    def cut_selected(self) -> None:
        """Ctrl+X: copy, then remove — one undo step."""
        models = self._copyable()
        if not models:
            return
        self.copy_selected()
        self.history.execute(CompoundCommand(
            [RemoveItemCommand(self.comp, m) for m in models]))

    def paste_clipboard(self) -> None:
        """Ctrl+V: the clipboard's items land on this sheet — 5 mm down-right
        of the originals on the same sheet, at the same place on another —
        on top and selected, one undo step; pasting again steps further.
        Frames get a new uid; a text bound to a copied frame, and a cota or
        label anchored to one, follow the pasted frame. Anchors to frames
        that were not copied are dropped (like Duplicate: the copy would
        otherwise snap back onto the original); a text's binding to a
        frame that is on this sheet is kept."""
        import copy
        import uuid
        src = ComposerWindow._clipboard
        if not src:
            return
        same = ComposerWindow._clipboard_from is self.comp
        step = 5.0 if same else 0.0
        here = {f.uid for f in self.comp.frames if f.uid}
        uid_map: dict = {}
        new_gids: dict = {}
        pasted = []
        z = self._next_z()
        for m0 in src:
            m = copy.deepcopy(m0)
            m.x_mm += step
            m.y_mm += step
            m.locked = False
            gid = getattr(m, "group_id", "")
            if gid:
                m.group_id = new_gids.setdefault(gid, uuid.uuid4().hex)
            if isinstance(m, MarcoVista):
                new_uid = uuid.uuid4().hex
                if m.uid:
                    uid_map[m.uid] = new_uid
                m.uid = new_uid
            elif hasattr(m, "uid"):
                m.uid = ""
            m.z = z
            z += 1.0
            pasted.append(m)
        for m in pasted:
            ref = getattr(m, "frame_uid", "")
            if ref in uid_map:                  # its frame was copied too
                m.frame_uid = uid_map[ref]
            elif ref and ref not in here:
                m.frame_uid = ""
            ref = getattr(m, "anchor_uid", "")
            if ref:
                m.anchor_uid = uid_map.get(ref, "")
                if not m.anchor_uid:
                    m.a_world = None
                    if hasattr(m, "b_world"):
                        m.b_world = None
        self.history.execute(CompoundCommand(
            [AddItemCommand(self.comp, m) for m in pasted]), notify=False)
        self._mark_dirty()
        self.canvas.clearSelection()         # what was pasted is the selection
        self._rebuild_canvas()
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and any(it.model is p for p in pasted):
                it.setSelected(True)
        for m0, m in zip(src, pasted):      # the next paste steps on from here
            m0.x_mm, m0.y_mm = m.x_mm, m.y_mm
        ComposerWindow._clipboard_from = self.comp
        self.statusBar().showMessage(
            tr("{n} item(s) pasted.", n=len(pasted)), 3000)

    def _build_arrange_toolbar(self) -> None:
        from PySide6.QtGui import QAction
        from PySide6.QtWidgets import QToolBar
        tb = QToolBar(tr("Arrange"), self)
        tb.setMovable(False)
        for text, tip, slot in (
                ("⇤", tr("Align left"), lambda: self.align_selected("left")),
                ("⇥", tr("Align right"), lambda: self.align_selected("right")),
                ("⤒", tr("Align top"), lambda: self.align_selected("top")),
                ("⤓", tr("Align bottom"), lambda: self.align_selected("bottom")),
                ("↔", tr("Center horizontally"),
                 lambda: self.align_selected("hcenter")),
                ("↕", tr("Center vertically"),
                 lambda: self.align_selected("vcenter")),
                ("⇔", tr("Distribute horizontally"),
                 lambda: self.distribute_selected("x")),
                ("⇕", tr("Distribute vertically"),
                 lambda: self.distribute_selected("y")),
                ("⧉", tr("Duplicate (Ctrl+D)"), self.duplicate_selected),
                ("⊞", tr("Group (Ctrl+G)"), self.group_selected),
                ("⊟", tr("Ungroup (Ctrl+Shift+G)"), self.ungroup_selected),
                ("🔒", tr("Lock / unlock (Ctrl+L)"), self.lock_selected)):
            act = QAction(text, self)
            act.setToolTip(tip)
            act.triggered.connect(lambda _c, s=slot: s())
            tb.addAction(act)
        self.addToolBar(Qt.TopToolBarArea, tb)

    # ---- Copy / paste style (LayOut's Edit ▸ Copy Style / Paste Style) -------
    #: The look of each item kind — never its geometry or content.
    STYLE_FIELDS = {
        CotaItem: ("text_mm", "decimals", "units", "ends", "stroke_mm", "color",
                   "offset_mm", "text_pos", "text_align", "text_color",
                   "text_bg", "text_bg_opacity"),
        TextoItem: ("size_pt", "bold", "italic", "underline", "family",
                    "color", "align", "bg_color", "bg_opacity"),
        FormaItem: ("stroke_mm", "color", "fill", "fill_color", "radius_mm"),
        MarcoVista: ("style", "scale_n", "show_title", "annotations",
                     "annot_text_mm", "km_marks", "km_step_m", "grid_m",
                     "border", "border_mm", "border_color"),
        CotaAngularItem: ("text_mm", "decimals", "ends", "stroke_mm",
                          "color", "offset_mm", "text_color", "text_bg",
                          "text_bg_opacity"),
        EtiquetaItem: ("size_pt", "bold", "italic", "underline", "color",
                       "bg_color", "bg_opacity", "arrow", "stroke_mm"),
        Cajetin: Cajetin.LOOK_FIELDS,
    }

    def _style_fields_for(self, model):
        for kind, fields in self.STYLE_FIELDS.items():
            if isinstance(model, kind):
                return kind, tuple(f for f in fields if hasattr(model, f))
        return None, ()

    def copy_style(self, item=None) -> None:
        """Remember the selected item's look (Ctrl+Shift+C)."""
        item = item if item is not None else self._selected_item()
        if item is None:
            return
        kind, fields = self._style_fields_for(item.model)
        if kind is None:
            self.statusBar().showMessage(
                tr("This item has no style to copy."), 3000)
            return
        self._style_clip = (kind, {f: getattr(item.model, f) for f in fields})
        self.statusBar().showMessage(tr("Style copied — select items of the "
                                        "same kind and paste it."), 4000)

    def format_painter_click(self, item) -> None:
        """The format-painter tool clicked *item*: the first click takes its
        style, the following ones paste it onto items of the same kind."""
        if item is None:
            return
        if getattr(self, "_painter_armed", True) or \
                getattr(self, "_style_clip", None) is None:
            kind, _f = self._style_fields_for(item.model)
            if kind is None:
                self.statusBar().showMessage(
                    tr("This item has no style to copy."), 3000)
                return
            self.copy_style(item)
            self._painter_armed = False
            self.statusBar().showMessage(tr(
                "Style copied — click the items to paste it on (Esc to "
                "finish)."), 6000)
            return
        if not self.can_paste_style(item.model):
            self.statusBar().showMessage(
                tr("That item is of another kind — the style does not "
                   "apply."), 3000)
            return
        self._apply_style([item])

    def can_paste_style(self, model) -> bool:
        clip = getattr(self, "_style_clip", None)
        return clip is not None and isinstance(model, clip[0])

    def paste_style(self) -> None:
        """Apply the remembered look to every selected item of that kind
        (Ctrl+Shift+V); one undo step per item."""
        clip = getattr(self, "_style_clip", None)
        if clip is None:
            return
        kind, style = clip
        targets = [it for it in self.canvas.selectedItems()
                   if isinstance(it, _SheetItem) and isinstance(it.model, kind)]
        self._apply_style(targets)

    def _apply_style(self, targets) -> None:
        clip = getattr(self, "_style_clip", None)
        if clip is None:
            return
        kind, style = clip
        n = 0
        for it in targets:
            changes = {k: v for k, v in style.items()
                       if getattr(it.model, k, None) != v}
            if not changes:
                continue
            it.prepareGeometryChange()
            self.history.execute(EditItemCommand(it.model, changes),
                                 notify=False)
            if isinstance(it.model, MarcoVista):
                for cache in (self.render_cache, self.hlr_cache,
                              self.snap_cache, self.annot_cache):
                    cache.pop(id(it.model), None)
            if isinstance(it.model, CotaItem):
                self._remember_cota_style(it.model)
            n += 1
        if n:
            self._mark_dirty()
            self._rebuild_canvas()
            for it in self.canvas.items():
                if isinstance(it, _SheetItem) and any(
                        it.model is t.model for t in targets):
                    it.setSelected(True)
            self.on_selection_changed()
        self.statusBar().showMessage(
            tr("Style pasted on {n} item(s).", n=n), 3000)

    # ---- Editing a frame's view in place (LayOut) ----------------------------
    @property
    def view_edit_item(self):
        return self._view_edit

    def begin_view_edit(self, item) -> None:
        """Double-click on a frame: pan / orbit / zoom its view with the
        mouse until Enter, Esc or a click outside."""
        if not isinstance(item, FrameItem) or getattr(item.model, "locked",
                                                      False):
            return
        if self._view_edit is not None and self._view_edit is not item:
            self.end_view_edit()
        self._view_edit = item
        item.setSelected(True)
        item.update()
        self.statusBar().showMessage(tr(
            "Editing the view: drag = pan, middle button or Ctrl+drag = "
            "orbit, wheel = zoom, Enter/Esc = done."), 8000)

    def end_view_edit(self) -> None:
        item = self._view_edit
        if item is None:
            return
        self._view_edit = None
        self._view_drag = None
        import shiboken6
        if shiboken6.isValid(item):
            item.update()
        self.statusBar().clearMessage()

    def _item_for(self, model):
        for it in self.canvas.items():
            if isinstance(it, _SheetItem) and it.model is model:
                return it
        return None

    def _frame_camera_state(self, item):
        """``(target, right, up, yaw, pitch)`` of the frame's camera as it
        is applied for rendering — every pan/orbit step builds on it."""
        from core.hlr import camera_basis

        def run():
            cam = self._window.viewport.camera
            _e, right, up, _f = camera_basis(cam)
            t = cam.target
            return ((t.x(), t.y(), t.z()), right.copy(), up.copy(),
                    cam.yaw, cam.pitch)
        return self._with_frame_camera(item.model, run)

    @staticmethod
    def _view_scale_k(frame) -> float:
        """Page millimetres per model metre at the frame's scale."""
        from core.composition import model_height_for_frame
        return frame.h_mm / model_height_for_frame(frame.h_mm, frame.scale_n)

    @staticmethod
    def _view_state(frame) -> dict:
        return {"cam_target": (None if frame.cam_target is None
                               else list(frame.cam_target)),
                "cam_yaw": frame.cam_yaw, "cam_pitch": frame.cam_pitch,
                "scale_n": frame.scale_n}

    def pan_view(self, item, dx_mm: float, dy_mm: float) -> None:
        """Slide the drawing inside the frame by a page delta: the camera
        target moves the other way, in its own plane."""
        import numpy as np
        frame = item.model
        (tx, ty, tz), right, up, _y, _p = self._frame_camera_state(item)
        k = self._view_scale_k(frame)
        t = np.array([tx, ty, tz]) - right * (dx_mm / k) + up * (dy_mm / k)
        frame.cam_target = [float(v) for v in t]
        self._after_view_edit(item)

    def orbit_view(self, item, dyaw: float, dpitch: float) -> None:
        import math
        frame = item.model
        _t, _r, _u, yaw, pitch = self._frame_camera_state(item)
        frame.cam_yaw = float(yaw + dyaw)
        frame.cam_pitch = float(max(-math.radians(89.0),
                                    min(math.radians(89.0), pitch + dpitch)))
        self._after_view_edit(item)

    def zoom_view(self, item, factor: float, at_mm=None) -> None:
        """Zoom by ``factor`` (>1 = closer: 1:N with a smaller N). With
        ``at_mm`` (a page point) the model under the cursor stays put."""
        import numpy as np
        frame = item.model
        old_n = frame.scale_n
        new_n = max(0.01, old_n / factor)
        if at_mm is not None:
            (tx, ty, tz), right, up, _y, _p = self._frame_camera_state(item)
            k = self._view_scale_k(frame)
            mx = (at_mm[0] - frame.x_mm) / k - (frame.w_mm / k) / 2.0
            my = (frame.h_mm / k) / 2.0 - (at_mm[1] - frame.y_mm) / k
            s = new_n / old_n
            t = np.array([tx, ty, tz]) + (right * mx + up * my) * (1.0 - s)
            frame.cam_target = [float(v) for v in t]
        frame.scale_n = round(new_n, 3)
        self._after_view_edit(item)

    def zoom_extents(self, item) -> None:
        """LayOut's Zoom Extents: centre the whole model in the frame at the
        largest common scale that still fits it."""
        import numpy as np
        from core.hlr import _to_cam, camera_basis
        frame = item.model
        scene = self._scene()
        lo, hi = scene.bounds()
        if lo is None:
            return
        before = self._view_state(frame)
        frame.cam_target = [(lo.x() + hi.x()) / 2.0, (lo.y() + hi.y()) / 2.0,
                            (lo.z() + hi.z()) / 2.0]
        corners = np.array([[x, y, z] for x in (lo.x(), hi.x())
                            for y in (lo.y(), hi.y())
                            for z in (lo.z(), hi.z())], dtype=np.float64)

        def run():
            cam = self._window.viewport.camera
            eye, right, up, fwd = camera_basis(cam)
            return _to_cam(corners, eye, right, up, fwd)
        c = self._with_frame_camera(frame, run)
        ext_w = float(c[:, 0].max() - c[:, 0].min())
        ext_h = float(c[:, 1].max() - c[:, 1].min())
        need_h = max(ext_h, ext_w * frame.h_mm / frame.w_mm) * 1.1 or 1.0
        n_min = need_h * 1000.0 / frame.h_mm        # 1:N showing need_h
        candidates = sorted(set(COMMON_SCALES) | {
            1, 2, 5, 10, 20, 25, 75, 125, 150, 300, 400, 750, 1500, 2500,
            5000})
        frame.scale_n = float(next((n for n in candidates if n >= n_min),
                                   round(n_min, 1)))
        self._commit_view_edit(item, before)

    def _after_view_edit(self, item, final: bool = False) -> None:
        """Live feedback while dragging: raster frames re-render (a few
        hundredths of a second); vector frames wait for the release."""
        frame = item.model
        self.render_cache.pop(id(frame), None)
        self.hlr_cache.pop(id(frame), None)
        self.snap_cache.pop(id(frame), None)
        self.annot_cache.pop(id(frame), None)
        if final or frame.style != "vectorial":
            self.render_frame(frame)
        item.update()

    def _commit_view_edit(self, item, before: dict) -> None:
        """One undo step for a whole pan / orbit / zoom gesture."""
        frame = item.model
        after = self._view_state(frame)
        if after != before:
            self.history.execute(EditItemCommand(frame, after, before),
                                 notify=False)
            self._mark_dirty()
        self._after_view_edit(item, final=True)
        self.on_selection_changed()          # the scale combo follows
        self._rebuild_canvas()               # anchored cotas reproject
        if self._view_edit is not None:
            self._view_edit = self._item_for(frame)
            if self._view_edit is not None:
                self._view_edit.setSelected(True)

    def start_view_drag(self, item, pos_mm, pos_px, orbit: bool) -> None:
        self._view_drag = {"item": item, "orbit": orbit,
                           "last_mm": (pos_mm.x(), pos_mm.y()),
                           "last_px": (pos_px.x(), pos_px.y()),
                           "before": self._view_state(item.model)}

    def view_drag_active(self) -> bool:
        return self._view_drag is not None

    def move_view_drag(self, pos_mm, pos_px) -> None:
        d = self._view_drag
        if d is None:
            return
        item = d["item"]
        if d["orbit"]:
            dx = pos_px.x() - d["last_px"][0]
            dy = pos_px.y() - d["last_px"][1]
            self.orbit_view(item, -dx * 0.01, -dy * 0.01)   # like the viewport
        else:
            self.pan_view(item, pos_mm.x() - d["last_mm"][0],
                          pos_mm.y() - d["last_mm"][1])
        d["last_mm"] = (pos_mm.x(), pos_mm.y())
        d["last_px"] = (pos_px.x(), pos_px.y())

    def finish_view_drag(self) -> None:
        d = self._view_drag
        self._view_drag = None
        if d is not None:
            self._commit_view_edit(d["item"], d["before"])

    def zoom_view_gesture(self, item, factor: float, at_mm) -> None:
        before = self._view_state(item.model)
        self.zoom_view(item, factor, at_mm)
        self._commit_view_edit(item, before)

    def edit_text_item(self, item) -> None:
        """Double-click on a text block or a label: edit it in place."""
        self.begin_inline_edit(item)

    def begin_inline_edit(self, item) -> None:
        if getattr(item.model, "locked", False):
            return
        self.end_inline_edit(None, None)          # one editor at a time
        editor = InlineTextEditor(self, item)
        self.canvas.addItem(editor)
        self._inline_editor = editor
        editor.setFocus(Qt.MouseFocusReason)
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        self.statusBar().showMessage(tr(
            "Editing the text: click outside or Ctrl+Enter to finish, "
            "Esc to cancel."), 6000)

    def end_inline_edit(self, editor, text) -> None:
        """Remove the inline editor; ``text`` = the committed text, or None
        to cancel. One undo step when it changed."""
        current = getattr(self, "_inline_editor", None)
        if editor is None:
            editor = current
        if editor is None:
            return
        if editor is current:
            self._inline_editor = None
        item = editor.item
        if editor.scene() is not None:
            editor.scene().removeItem(editor)
        if text is not None and text != item.model.text:
            item.prepareGeometryChange()
            self.history.execute(EditItemCommand(item.model, {"text": text}),
                                 notify=False)
            self._mark_dirty()
        item.update()
        self.on_selection_changed()

    def edit_cota_text(self, item) -> None:
        """Double-click on a sheet cota: edit its text. ``<>`` stands for
        the measured value; an empty text (or a bare ``<>``, or the value
        itself) goes back to the automatic label. One undo step."""
        from PySide6.QtWidgets import QInputDialog
        model = item.model
        if getattr(model, "locked", False):
            return
        auto = model.auto_label()
        current = model.text if model.text else auto
        text, ok = QInputDialog.getText(
            self, tr("Dimension"),
            tr("Dimension text (<> = measured value):"), text=current)
        if not ok:
            return
        new = text.strip()
        if new in ("", "<>", auto):
            new = ""
        if new == (model.text or ""):
            return
        item.prepareGeometryChange()
        self.history.execute(EditItemCommand(model, {"text": new}),
                             notify=False)
        self._mark_dirty()
        item.update()
        self.on_selection_changed()          # the Label box follows

    def compute_annotations(self, frame: MarcoVista) -> list:
        """The model's paper overlay for *frame* (frame-local mm), every
        style alike — the GL render comes back without overlays and the
        vector pass only knows edges. Traced georef paths ALWAYS (they are
        the design, drawn on the ground as the viewport drapes them);
        dimensions and leader texts when the frame opts in. Hidden layers
        of the frame's scene apply."""
        import math
        import numpy as np
        from core.composition import model_height_for_frame
        from core.hlr import _to_cam, camera_basis

        def run():
            vp = self._window.viewport
            scene = vp.scene
            eye, right, up, fwd = camera_basis(vp.camera)
            model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
            k = frame.h_mm / model_h
            half_h = model_h / 2.0
            half_w = half_h * (frame.w_mm / frame.h_mm)

            def pt(p):
                c = _to_cam(np.array([[p.x(), p.y(), p.z()]], dtype=float),
                            eye, right, up, fwd)[0]
                return ((c[0] + half_w) * k, (half_h - c[1]) * k)

            out: list = []
            drape = getattr(vp, "drape", None) or (lambda p: p)
            for path in getattr(scene, "geo_paths", None) or []:
                pts = [pt(drape(p)) for p in path.points]
                if len(pts) < 2:
                    continue
                if path.closed and len(pts) > 2:
                    pts.append(pts[0])
                out.append(("poly", pts))
            if getattr(frame, "km_marks", False):
                out.extend(self._chainage_marks(frame, scene, pt, drape))
            if not getattr(frame, "annotations", False):
                return out
            size = float(getattr(frame, "annot_text_mm", 2.8) or 2.8)
            style = getattr(scene, "dimension_style", {}) or {}
            fmt = getattr(vp, "_format_dim_value", None)
            for dim in getattr(scene, "dimensions", []) or []:
                if not scene.entity_visible(dim):
                    continue
                ap, bp = dim.line_points()
                a, b = pt(dim.a), pt(dim.b)
                a2, b2 = pt(ap), pt(bp)
                out.append(("line", a[0], a[1], a2[0], a2[1]))
                out.append(("line", b[0], b[1], b2[0], b2[1]))
                out.append(("line", a2[0], a2[1], b2[0], b2[1]))
                ang = math.atan2(b2[1] - a2[1], b2[0] - a2[0])
                for x, y in (a2, b2):                 # oblique ticks
                    t = 1.6
                    out.append(("line",
                                x - t * math.cos(ang + math.radians(45)),
                                y - t * math.sin(ang + math.radians(45)),
                                x + t * math.cos(ang + math.radians(45)),
                                y + t * math.sin(ang + math.radians(45))))
                measured = (fmt(dim.value(), style) if fmt is not None
                            else dim.label())
                text = (dim.display_text(measured)
                        if hasattr(dim, "display_text") else measured)
                deg = math.degrees(ang)
                if deg > 90 or deg <= -90:
                    deg += 180
                out.append(("text", (a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2,
                            deg, text, size))
            for lab in getattr(scene, "text_labels", []) or []:
                if not scene.entity_visible(lab):
                    continue
                a = pt(lab.anchor)
                p = pt(lab.position())
                out.append(("line", a[0], a[1], p[0], p[1]))
                lines = lab.text.splitlines() or [""]
                side = 1.0 if p[0] >= a[0] else -1.0    # away from the anchor
                for i, line in enumerate(lines):
                    width = max(len(line) * size * 0.55, 1.0)
                    x = p[0] + side * (1.5 + width / 2)
                    out.append(("text", x, p[1] + i * size * 1.3, 0.0,
                                line, size))
            return out
        return self._with_frame_camera(frame, run)

    @staticmethod
    def _chainage_marks(frame: MarcoVista, scene, pt, drape) -> list:
        """Tick + «0+020» label at every chainage step along each traced
        path, as ``("line", …)`` / ``("text", …)`` overlay tuples (paper
        mm). Chainage is the horizontal length the profile plots, and the
        step the same one the profile picks, so the plan's marks line up
        with the profile's axis. Labels stand perpendicular to the path
        (the civil convention: they never pile up on a short step)."""
        import math
        from georef.profile import point_at_station, polyline_length
        out: list = []
        size = float(getattr(frame, "annot_text_mm", 2.8) or 2.8)
        tick = 0.9
        for path in getattr(scene, "geo_paths", None) or []:
            nodes = path.profile_points()
            length = polyline_length(nodes)
            if len(nodes) < 2 or length <= 1e-9:
                continue
            step = chainage_step(length, getattr(frame, "km_step_m", 0.0))
            stations, s = [], 0.0
            while s <= length + 1e-6:
                stations.append(min(s, length))
                s += step
            # The end of the path too, unless a mark already (nearly) sits
            # there.
            if length - stations[-1] > 0.3 * step:
                stations.append(length)
            for s in stations:
                x, y = point_at_station(nodes, s)
                p = pt(drape(QVector3D(x, y, 0.0)))
                # Local direction on paper from a point half a metre along
                # (backwards at the very end).
                if s + 0.5 <= length:
                    xq, yq = point_at_station(nodes, s + 0.5)
                    q = pt(drape(QVector3D(xq, yq, 0.0)))
                    dx, dy = q[0] - p[0], q[1] - p[1]
                else:
                    xq, yq = point_at_station(nodes, max(s - 0.5, 0.0))
                    q = pt(drape(QVector3D(xq, yq, 0.0)))
                    dx, dy = p[0] - q[0], p[1] - q[1]
                norm = math.hypot(dx, dy)
                if norm < 1e-9:
                    dx, dy = 1.0, 0.0
                else:
                    dx, dy = dx / norm, dy / norm
                nx, ny = -dy, dx
                out.append(("line", p[0] - nx * tick, p[1] - ny * tick,
                            p[0] + nx * tick, p[1] + ny * tick))
                # Always the same side of the path (the right of travel);
                # the reading direction alone flips so the label is never
                # upside down (vertical ones read bottom-up, as dimensions
                # do). The text is centred on its anchor, so the side holds
                # whichever way it reads.
                deg = (math.degrees(math.atan2(ny, nx)) + 90.0) % 180.0 - 90.0
                text = _chainage(s, step)
                width = max(len(text) * size * 0.55, 1.0)
                off = tick + 0.6 + width / 2
                out.append(("text", p[0] + nx * off, p[1] + ny * off, deg,
                            text, size))
        return out

    def _on_zoom_extents_selected(self) -> None:
        item = self._selected_item()
        if isinstance(item, FrameItem):
            self.zoom_extents(item)

    # ---- Auto-render (LayOut's Auto) -----------------------------------------
    def _on_model_version(self, version) -> None:
        """The viewport painted a new scene version: unless it is one of our
        own sheet edits, every frame is now stale."""
        if version == self._sheet_version:
            self._last_model_version = version
            return
        if version == self._last_model_version:
            return
        self._last_model_version = version
        self._invalidate_geometry_caches()
        self.__dict__.setdefault("_profile_cache", {}).clear()   # a path may have moved
        for comp in getattr(self._scene(), "compositions", []) or []:
            for f in comp.frames:
                self._stale.add(id(f))
        self.canvas.update()
        if self._auto_render and self.isVisible():
            self._auto_timer.start()

    def is_stale(self, frame) -> bool:
        return id(frame) in self._stale

    def _set_auto_render(self, on: bool) -> None:
        from PySide6.QtCore import QSettings
        self._auto_render = bool(on)
        QSettings().setValue("composer/auto_render", "1" if on else "0")
        if on:
            self._auto_render_stale()

    def _auto_render_stale(self) -> None:
        """Re-render the current sheet's stale (or never rendered) raster
        frames; vector frames keep their badge and wait for Update — their
        exact pass costs seconds on a real model."""
        self._auto_timer.stop()          # a pending auto pass is this one
        if not self._auto_render or not self.isVisible():
            return
        done = False
        for f in list(self.comp.frames):
            if f.style == "vectorial":
                continue
            if id(f) in self._stale or id(f) not in self.render_cache:
                self.render_frame(f)
                done = True
        if done:
            self._rebuild_canvas()
        else:
            self.canvas.update()

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
        self._sheet_version = scene.version      # ours: not a model change
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
        items = [it for it in self.canvas.selectedItems()
                 if isinstance(it, _SheetItem)]
        if not items:
            return
        if len(items) == 1:
            self.history.execute(RemoveItemCommand(self.comp, items[0].model))
            return
        self.history.execute(CompoundCommand(
            [RemoveItemCommand(self.comp, it.model) for it in items]))

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
        default = self.default_cajetin_template_name()
        tpl = self.load_cajetin_template(default) if default else None
        if tpl:
            for k, v in tpl.items():
                setattr(c, k, v)
            pw, ph = self.comp.page_size_mm()      # keep it docked
            m = self.comp.margin_mm
            c.x_mm, c.y_mm = pw - m - c.w_mm, ph - m - c.h_mm
        c.set_field("FECHA", datetime.date.today().strftime("%d/%m/%Y"))
        if self.comp.frames:
            f = self.comp.frames[0]
            c.set_field("ESCALA", f"1:{f.scale_n:g}")
        c.z = self._next_z()
        self.history.execute(AddItemCommand(self.comp, c))

    # ---- property edits ------------------------------------------------------
    def _scale_options(self) -> list:
        """1:N presets plus the scales this document has collected."""
        custom = getattr(self._scene(), "custom_scales", None) or []
        return sorted(set(float(n) for n in COMMON_SCALES)
                      | set(float(n) for n in custom))

    def _reload_scale_options(self) -> None:
        combo = self.scale_combo
        combo.blockSignals(True)
        current = combo.currentText()
        combo.clear()
        combo.addItems([f"1:{n:g}" for n in self._scale_options()])
        if current:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def _on_scale_committed(self) -> None:
        """Enter / focus-out on the scale box: remember a new 1:N in the
        document (LayOut keeps only its presets; here a project's odd
        scale, say 1:75, is one click away on the next frame)."""
        n = round(self._current_scale_n(), 3)
        if any(abs(n - k) < 1e-6 for k in self._scale_options()):
            return
        scales = getattr(self._scene(), "custom_scales", None)
        if scales is None:
            return
        scales.append(n)
        self._mark_dirty()
        self._reload_scale_options()

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

    def _on_border_changed(self, *_a) -> None:
        if self._updating:
            return
        self.comp.border = self.border_check.isChecked()
        self.comp.border_mm = self.border_mm.value()
        self.comp.border_radius_mm = self.border_radius.value()
        self.comp.border_style = self.border_style.currentData() or "single"
        self._mark_dirty()
        self._rebuild_canvas()

    def _on_pick_border_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        col = QColorDialog.getColor(QColor(self.comp.border_color), self,
                                    tr("Border colour"))
        if col.isValid():
            self.comp.border_color = col.name()
            self.border_color_btn.setStyleSheet(f"background: {col.name()};")
            self._mark_dirty()
            self._rebuild_canvas()

    def _sync_border_panel(self) -> None:
        self._updating = True
        try:
            c = self.comp
            self.border_check.setChecked(bool(getattr(c, "border", False)))
            self.border_mm.setValue(float(getattr(c, "border_mm", 0.5)))
            self.border_radius.setValue(
                float(getattr(c, "border_radius_mm", 0.0)))
            sidx = self.border_style.findData(
                getattr(c, "border_style", "single") or "single")
            self.border_style.setCurrentIndex(max(sidx, 0))
            self.border_color_btn.setStyleSheet(
                f"background: {getattr(c, 'border_color', '#1e242c')};")
        finally:
            self._updating = False

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
            "show_title": self.title_check.isChecked(),
            "annotations": self.annot_check.isChecked(),
            "annot_text_mm": self.annot_mm_spin.value(),
            "km_marks": self.km_check.isChecked(),
            "km_step_m": float(self.km_step_spin.value()),
            "border": self.frame_border_check.isChecked(),
            "border_mm": self.frame_border_mm.value()})
        self.render_cache.pop(id(item.model), None)
        self.hlr_cache.pop(id(item.model), None)
        self.snap_cache.pop(id(item.model), None)
        self.annot_cache.pop(id(item.model), None)
        self.canvas.update()                 # bound scale labels re-read {escala}

    def _on_text_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, TextItem):
            return
        self._panel_edit(item, {
            "text": self.text_edit.toPlainText(),
            "size_pt": self.text_size.value(),
            "bold": self.text_bold.isChecked(),
            "italic": self.text_italic.isChecked(),
            "underline": self.text_underline.isChecked()})

    def _on_text_family(self, font) -> None:
        # Its own step: the combo settles on the nearest installed family
        # while syncing, so folding it into _on_text_props would rewrite
        # the stored family on every unrelated edit.
        item = self._selected_item()
        if self._updating or not isinstance(item, TextItem):
            return
        self._panel_edit(item, {"family": font.family()})

    def _on_text_align(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, TextItem):
            return
        self._panel_edit(item, {"align": self.text_align.currentData()
                                or "left"})

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

    def _cajetin_table_rows(self) -> list:
        rows = []
        for i in range(self.caj_table.rowCount()):
            label = self.caj_table.item(i, 0)
            value = self.caj_table.item(i, 1)
            rows.append([label.text() if label else "",
                         value.text() if value else ""])
        return rows

    def _on_cajetin_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CajetinItem):
            return
        item.prepareGeometryChange()
        self._panel_edit(item, {
            "campos": self._cajetin_table_rows(),
            "w_mm": self.caj_w.value(),
            "h_mm": self.caj_h.value(),
            "columns": int(self.caj_columns.value()),
            "border_mm": self.caj_border.value(),
            "line_mm": self.caj_line.value(),
            "label_mm": self.caj_label_mm.value(),
            "layout": self.caj_layout.currentData() or "grid",
            "corner": self.caj_corner.currentData() or "square",
            "radius_mm": self.caj_radius.value(),
            "double_border": self.caj_double.isChecked()})
        self._sync_cajetin_design_combo(item.model)

    def _sync_cajetin_design_combo(self, c) -> None:
        was = self._updating
        self._updating = True
        key = c.design_key() if hasattr(c, "design_key") else ""
        self.caj_design.setCurrentIndex(
            max(0, self.caj_design.findData(key)) if key else 0)
        self._updating = was

    def _on_cajetin_fill_toggled(self, on: bool) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CajetinItem):
            return
        last = getattr(self, "_last_cajetin_fill", "#e9ecf0")
        item.prepareGeometryChange()
        self._panel_edit(item, {"fill_color": last if on else ""})
        self.caj_fill_btn.setStyleSheet(f"background: {last};" if on else "")
        self._sync_cajetin_design_combo(item.model)

    def _on_cajetin_design(self, *_a) -> None:
        """A built-in look keeps the rows and the size; a saved title block
        brings its rows, size and look."""
        from core.composition import CAJETIN_DESIGN_BASE, CAJETIN_DESIGNS
        item = self._selected_item()
        if self._updating or not isinstance(item, CajetinItem):
            return
        data = self.caj_design.currentData()
        if not data:
            return
        if str(data).startswith("tpl:"):
            self.apply_cajetin_template(item, str(data)[4:])
            return
        fields = next((dict(CAJETIN_DESIGN_BASE, **f)
                       for k, _l, f in CAJETIN_DESIGNS if k == data), None)
        if fields is None:
            return
        item.prepareGeometryChange()
        self._panel_edit(item, fields)
        self.on_selection_changed()

    # ---- Title-block templates (the user's own designs) ----------------------
    @staticmethod
    def cajetin_templates_dir():
        from pathlib import Path
        from PySide6.QtCore import QStandardPaths
        base = (QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
                or str(Path.home() / ".ingetrazo"))
        d = Path(base) / "cajetines"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cajetin_template_names(self) -> list:
        try:
            return sorted(p.stem for p in self.cajetin_templates_dir().glob("*.json"))
        except OSError:
            return []

    def save_cajetin_template(self, name: str, cajetin):
        """Write a title block (rows, size, look — not its place) as a
        reusable template."""
        import json
        name = (name or "").strip()
        if not name:
            return None
        safe = "".join(ch if ch not in '/\\:*?"<>|' else "_" for ch in name)
        path = self.cajetin_templates_dir() / f"{safe}.json"
        d = cajetin.template_dict()
        d["name"] = name
        path.write_text(json.dumps(d, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path

    def load_cajetin_template(self, name: str):
        """The template's fields, restricted to what a Cajetin has."""
        import json
        from dataclasses import fields as _fields
        path = self.cajetin_templates_dir() / f"{name}.json"
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        allowed = {f.name for f in _fields(Cajetin)} - {
            "x_mm", "y_mm", "z", "locked", "group_id"}
        d = {k: v for k, v in raw.items() if k in allowed}
        if "campos" in d:
            d["campos"] = [[str(r[0]), str(r[1])] for r in d["campos"]
                           if isinstance(r, (list, tuple)) and len(r) >= 2]
        return d or None

    def apply_cajetin_template(self, item, name: str) -> bool:
        d = self.load_cajetin_template(name)
        if d is None or not isinstance(item, CajetinItem):
            return False
        item.prepareGeometryChange()
        self._panel_edit(item, d)
        self.on_selection_changed()
        return True

    @staticmethod
    def default_cajetin_template_name():
        from PySide6.QtCore import QSettings
        name = str(QSettings().value("composer/default_cajetin", "") or "")
        return name or None

    @staticmethod
    def set_default_cajetin_template(name) -> None:
        from PySide6.QtCore import QSettings
        QSettings().setValue("composer/default_cajetin", name or "")

    def _on_cajetin_templates_menu(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QMenu
        from PySide6.QtGui import QCursor, QDesktopServices
        from PySide6.QtCore import QUrl
        item = self._selected_item()
        have = isinstance(item, CajetinItem)
        menu = QMenu(self)
        save = menu.addAction(tr("Save this title block as a template…"))
        save.setEnabled(have)
        names = self.cajetin_template_names()
        apply_menu = menu.addMenu(tr("Apply template"))
        apply_acts = {apply_menu.addAction(n): n for n in names}
        apply_menu.setEnabled(bool(names) and have)
        def_menu = menu.addMenu(tr("Default for new title blocks"))
        current = self.default_cajetin_template_name()
        none_act = def_menu.addAction(tr("(none — the classic block)"))
        none_act.setCheckable(True)
        none_act.setChecked(not current)
        def_acts = {}
        for n in names:
            a = def_menu.addAction(n)
            a.setCheckable(True)
            a.setChecked(n == current)
            def_acts[a] = n
        del_menu = menu.addMenu(tr("Delete template"))
        del_acts = {del_menu.addAction(n): n for n in names}
        del_menu.setEnabled(bool(names))
        menu.addSeparator()
        folder = menu.addAction(tr("Open the title blocks folder"))
        chosen = menu.exec(QCursor.pos())
        if chosen is None:
            return
        if chosen is save:
            name, ok = QInputDialog.getText(
                self, tr("Save template"), tr("Template name:"),
                text=tr("My title block"))
            if ok and name.strip():
                self.save_cajetin_template(name, item.model)
                self._reload_cajetin_designs()
                self._sync_cajetin_design_combo(item.model)
                self.statusBar().showMessage(tr(
                    "Title block template saved: {name}",
                    name=name.strip()), 4000)
        elif chosen in apply_acts:
            self.apply_cajetin_template(item, apply_acts[chosen])
        elif chosen is none_act:
            self.set_default_cajetin_template(None)
        elif chosen in def_acts:
            self.set_default_cajetin_template(def_acts[chosen])
        elif chosen in del_acts:
            try:
                (self.cajetin_templates_dir()
                 / f"{del_acts[chosen]}.json").unlink()
            except OSError:
                pass
            if self.default_cajetin_template_name() == del_acts[chosen]:
                self.set_default_cajetin_template(None)
            self._reload_cajetin_designs()
            if have:
                self._sync_cajetin_design_combo(item.model)
        elif chosen is folder:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.cajetin_templates_dir())))

    def _on_cajetin_add_row(self) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CajetinItem):
            return
        rows = self._cajetin_table_rows() + [[tr("FIELD"), ""]]
        self._panel_edit(item, {"campos": rows})
        self.on_selection_changed()          # refresh the table

    def _on_cajetin_del_row(self) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CajetinItem):
            return
        rows = self._cajetin_table_rows()
        if len(rows) <= 1:
            return                           # a title block keeps one row
        idx = self.caj_table.currentRow()
        rows.pop(idx if 0 <= idx < len(rows) else len(rows) - 1)
        self._panel_edit(item, {"campos": rows})
        self.on_selection_changed()

    def _on_text_bg_toggled(self, on: bool) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, TextItem):
            return
        last = getattr(self, "_last_text_bg", "#ffffff")
        item.prepareGeometryChange()
        self._panel_edit(item, {"bg_color": last if on else ""})
        self.text_bg_btn.setStyleSheet(
            f"background: {last};" if on else "")

    def _on_pick_text_bg(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        item = self._selected_item()
        if not isinstance(item, TextItem):
            return
        current = item.model.bg_color or getattr(self, "_last_text_bg",
                                                 "#ffffff")
        col = QColorDialog.getColor(QColor(current), self,
                                    tr("Background colour"))
        if col.isValid():
            self._last_text_bg = col.name()
            item.prepareGeometryChange()
            self._panel_edit(item, {"bg_color": col.name()})
            self._updating = True
            self.text_bg_check.setChecked(True)
            self._updating = False
            self.text_bg_btn.setStyleSheet(f"background: {col.name()};")

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
        item.prepareGeometryChange()
        self._panel_edit(item, {"stroke_mm": self.forma_stroke.value(),
                                "fill": self.forma_fill.isChecked(),
                                "invert": self.forma_invert.isChecked(),
                                "radius_mm": self.forma_radius.value(),
                                "sides": int(self.forma_sides.value())})

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
            "units": self.cota_units.currentText() or "m",
            "ends": self.cota_ends.currentData() or "tick",
            "stroke_mm": self.cota_stroke.value(),
            "text_pos": self.cota_text_pos.currentData() or "above",
            "text_align": self.cota_text_align.currentData() or "aligned",
            "text_color": ("" if self.cota_text_same.isChecked()
                           else (item.model.text_color or item.model.color))})
        self._remember_cota_style(item.model)

    def _on_etiqueta_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, EtiquetaCanvasItem):
            return
        item.prepareGeometryChange()
        self._panel_edit(item, {
            "text": self.et_text.toPlainText(),
            "size_pt": self.et_size.value(),
            "bold": self.et_bold.isChecked(),
            "italic": self.et_italic.isChecked(),
            "underline": self.et_underline.isChecked(),
            "arrow": self.et_arrow.isChecked(),
            "stroke_mm": self.et_stroke.value()})

    def _on_cota_ang_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, CotaAngularCanvasItem):
            return
        item.prepareGeometryChange()
        self._panel_edit(item, {
            "text": self.cang_text.text(),
            "radius_mm": self.cang_radius.value(),
            "text_mm": self.cang_text_mm.value(),
            "decimals": int(self.cang_decimals.value()),
            "ends": self.cang_ends.currentData() or "arrow",
            "stroke_mm": self.cang_stroke.value()})

    def _opacity_spin(self, attr: str) -> QDoubleSpinBox:
        """A 0–100 % spin bound to a 0..1 opacity field of the selected
        item (background fills)."""
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 100.0)
        spin.setSingleStep(5.0)
        spin.setDecimals(0)
        spin.setSuffix(" %")
        spin.setValue(100.0)
        spin.valueChanged.connect(
            lambda v, a=attr: self._on_opacity_changed(a, v))
        return spin

    def _on_opacity_changed(self, attr: str, value: float) -> None:
        item = self._selected_item()
        if self._updating or item is None or not hasattr(item.model, attr):
            return
        item.update()
        self._panel_edit(item, {attr: max(0.0, min(1.0, value / 100.0))})
        if isinstance(item.model, CotaItem):
            self._remember_cota_style(item.model)

    def _toggle_item_bg(self, attr: str, on: bool, button) -> None:
        item = self._selected_item()
        if self._updating or item is None or not hasattr(item.model, attr):
            return
        last = getattr(self, "_last_text_bg", "#ffffff")
        item.prepareGeometryChange()
        self._panel_edit(item, {attr: last if on else ""})
        button.setStyleSheet(f"background: {last};" if on else "")
        if isinstance(item.model, CotaItem):
            self._remember_cota_style(item.model)

    def _pick_item_bg(self, attr: str, check, button) -> None:
        from PySide6.QtWidgets import QColorDialog
        item = self._selected_item()
        if item is None or not hasattr(item.model, attr):
            return
        current = getattr(item.model, attr, "") or getattr(
            self, "_last_text_bg", "#ffffff")
        col = QColorDialog.getColor(QColor(current), self,
                                    tr("Background colour"))
        if col.isValid():
            self._last_text_bg = col.name()
            item.prepareGeometryChange()
            self._panel_edit(item, {attr: col.name()})
            self._updating = True
            check.setChecked(True)
            self._updating = False
            button.setStyleSheet(f"background: {col.name()};")
            if isinstance(item.model, CotaItem):
                self._remember_cota_style(item.model)

    def _pick_item_color(self, attr: str, button) -> None:
        from PySide6.QtWidgets import QColorDialog
        item = self._selected_item()
        if item is None:
            return
        current = getattr(item.model, attr, "") or getattr(
            item.model, "color", "#1e242c")
        col = QColorDialog.getColor(QColor(current), self, tr("Colour"))
        if col.isValid():
            item.prepareGeometryChange()
            self._panel_edit(item, {attr: col.name()})
            button.setStyleSheet(f"background: {col.name()};")

    def _on_pick_cota_text_color(self) -> None:
        from PySide6.QtWidgets import QColorDialog
        item = self._selected_item()
        if not isinstance(item, CotaCanvasItem):
            return
        col = QColorDialog.getColor(
            QColor(item.model.text_color or item.model.color), self,
            tr("Text colour"))
        if col.isValid():
            self._updating = True
            self.cota_text_same.setChecked(False)
            self._updating = False
            self._panel_edit(item, {"text_color": col.name()})
            self.cota_text_color_btn.setStyleSheet(
                f"background: {col.name()};")
            self._remember_cota_style(item.model)

    #: Style fields a new cota inherits from the last one edited (LayOut
    #: draws new dimensions with the current style settings).
    _COTA_STYLE_FIELDS = ("text_mm", "decimals", "ends", "stroke_mm",
                          "color", "offset_mm", "text_pos", "text_align",
                          "text_color", "text_bg", "text_bg_opacity", "units")

    def _remember_cota_style(self, model) -> None:
        self._last_cota_style = {k: getattr(model, k)
                                 for k in self._COTA_STYLE_FIELDS
                                 if hasattr(model, k)}

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
        if isinstance(model, EtiquetaItem):
            first = model.text.split("\n")[0][:24] if model.text else "—"
            return tr("Label") + ": " + first
        if isinstance(model, CotaAngularItem):
            return tr("Angle") + " " + model.label()
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
        if isinstance(model, PerfilTerreno):
            return tr("Terrain profile") + (": " + model.title if model.title else "")
        if isinstance(model, Leyenda):
            return model.title or tr("Legend")
        if isinstance(model, FormaItem):
            return {"linea": tr("Line"), "flecha": tr("Arrow"),
                    "rect": tr("Rectangle"), "elipse": tr("Ellipse"),
                    "poligono": tr("Polygon")}.get(model.kind, model.kind)
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

    # ---- terrain profile items ------------------------------------------------
    @staticmethod
    def _perfil_default_path(paths) -> int:
        """The path a new profile item starts on: the first open one (a road,
        a canal), else the first."""
        for i, p in enumerate(paths):
            if not getattr(p, "closed", False) and len(getattr(p, "points", [])) >= 2:
                return i
        return 0

    def _reload_perfil_paths(self) -> None:
        was = self._updating
        self._updating = True
        try:
            self.pf_path.clear()
            paths = getattr(self._scene(), "geo_paths", None) or []
            for i, p in enumerate(paths):
                name = p.name or tr("Path {n}", n=i + 1)
                self.pf_path.addItem(
                    f"{name} — {p.length():.0f} m", i)
            if not paths:
                self.pf_path.addItem(tr("(no traced path yet)"), 0)
        finally:
            self._updating = was

    def _on_perfil_props(self, *_a) -> None:
        item = self._selected_item()
        if self._updating or not isinstance(item, PerfilItem):
            return
        m = item.model
        text = self.pf_scale.currentText().strip()
        if ":" in text:
            try:
                n = float(text.split(":", 1)[1].replace(",", "."))
            except ValueError:
                n = m.scale_n
        elif text == self.pf_scale.itemText(0) or not text:
            n = 0.0
        else:
            try:
                n = float(text.replace(",", "."))
            except ValueError:
                n = m.scale_n
        data = self.pf_path.currentData()
        item.prepareGeometryChange()
        self._panel_edit(item, {
            "path_index": int(data) if data is not None else int(m.path_index),
            "scale_n": max(0.0, n),
            "exag": float(self.pf_exag.value()),
            "grid": self.pf_grid.isChecked(),
            "grid_h_m": float(self.pf_grid_h.value()),
            "grid_v_m": float(self.pf_grid_v.value()),
            "fill": self.pf_fill.isChecked(),
            "title": self.pf_title.text(),
            "text_mm": float(self.pf_text.value()),
            "w_mm": float(self.pf_w.value()),
            "h_mm": float(self.pf_h.value())})
        self.__dict__.setdefault("_profile_cache", {}).pop(id(m), None)
        item.update()

    def _profile_sampler(self, datum):
        """The elevation sampler a profile item reads — the same choice the
        profile dock makes: a visible photogrammetric survey beats the DEM
        (the profile that decides where a canal sits comes off the flight
        the engineer made), the DEM answers everywhere else. Rebuilt when
        the datum or the survey changes; DEM tiles arriving later repaint."""
        scene = self._scene()
        cur = getattr(self, "_prof_sampler", None)
        cur_datum = getattr(self, "_prof_datum", None)
        cur_kind = getattr(self, "_prof_kind", None)
        survey = getattr(scene, "photo_mesh", None)
        if survey is not None and getattr(survey, "visible", False):
            if (cur_kind == "survey" and cur_datum is datum
                    and getattr(cur, "mesh", None) is survey):
                return cur
            from georef.photomesh import PhotoMeshSampler
            self._prof_sampler = PhotoMeshSampler(survey, datum)
            self._prof_datum, self._prof_kind = datum, "survey"
            return self._prof_sampler
        if cur_kind == "dem" and cur_datum is datum:
            return cur
        from georef.dem import DEMSampler
        sampler = DEMSampler(datum, parent=self)
        sampler.changed.connect(self._on_profile_terrain_changed)
        self._prof_sampler, self._prof_datum, self._prof_kind = sampler, datum, "dem"
        return sampler

    def _on_profile_terrain_changed(self) -> None:
        self.__dict__.setdefault("_profile_cache", {}).clear()
        self.canvas.update()

    def profile_for(self, m) -> tuple:
        """``(profile, path_name, message)`` for a PerfilTerreno: the sampled
        terrain under its path (cached until the path, the sampler or the
        item's sampling changes), the path's display name, and what to show
        instead when there is nothing to plot yet."""
        scene = self._scene()
        paths = getattr(scene, "geo_paths", None) or []
        if not paths:
            return None, "", tr("Trace a path with the Path tool (T) first.")
        idx = int(m.path_index)
        if idx < 0 or idx >= len(paths):
            return None, "", tr("Path {n} no longer exists.", n=idx + 1)
        path = paths[idx]
        name = path.name or tr("Path {n}", n=idx + 1)
        datum = getattr(scene, "georef", None)
        if datum is None:
            return None, name, tr("Set a base map location first (Tray ▸ Base map).")
        pts = path.profile_points()
        if len(pts) < 2:
            return None, name, tr("The path needs two points.")
        sampler = self._profile_sampler(datum)
        key = (idx, tuple((round(p.x(), 3), round(p.y(), 3)) for p in pts),
               float(m.spacing_m), id(sampler))
        cache = self.__dict__.setdefault("_profile_cache", {})
        hit = cache.get(id(m))
        if hit is not None and hit[0] == key:
            prof = hit[1]
        else:
            from georef.profile import sample_profile
            prof = sample_profile(pts, sampler, spacing=m.spacing_m or None)
            cache[id(m)] = (key, prof)
        if not prof.samples or prof.max_elevation() is None:
            return prof, name, tr("Loading terrain…")
        return prof, name, (tr("(loading DEM…)") if not prof.complete else None)

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
            self._invalidate_geometry_caches()
            self._on_frame_props()
            self.render_frame(item.model)
            self._rebuild_canvas()

    def refresh_all_frames(self) -> None:
        self._invalidate_geometry_caches()
        for f in self.comp.frames:
            self.render_frame(f)
        # anchored cotas follow the refreshed drawing (rebuild reprojects)
        self._rebuild_canvas()

    def _with_frame_camera(self, frame: MarcoVista, fn):
        """Run ``fn()`` with the live camera pointed at *frame* (exact
        scale), restoring camera, aspect, up, layer visibility, section
        state and display style after — the composer never disturbs the
        viewport. A frame bound to a scene applies that scene WHOLE (its
        cut and style included, via SavedView.apply), so all of it must
        come back: a sheet with a section scene used to leave the live
        model cut and restyled (Marco, 2026-09-02)."""
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
        keep_section = (
            scene.active_section() if hasattr(scene, "active_section")
            else None,
            getattr(scene, "show_section_planes", True),
            getattr(scene, "show_section_cuts", True))
        keep_style = getattr(scene, "display_style", None)
        try:
            apply_frame_camera(cam, frame, saved_view, scene)
            return fn()
        finally:
            (cam.target, cam.distance, cam.yaw, cam.pitch, cam.fov_deg,
             cam.perspective, cam.aspect, cam.up) = keep[:8]
            for ly, visible in keep[8]:
                ly.visible = visible
            if hasattr(scene, "set_active_section"):
                scene.set_active_section(keep_section[0])
                scene.show_section_planes = keep_section[1]
                scene.show_section_cuts = keep_section[2]
            if hasattr(scene, "display_style"):
                scene.display_style = keep_style
            vp.update()

    #: Above this many hard edges the EXACT hidden-line snap pass (minutes
    #: on a photogrammetry-scale scene — it is O(edges × triangles)) gives
    #: way to projecting every edge point without occlusion: instant, and
    #: an occasional snap to a hidden vertex beats a frozen composer.
    _EXACT_SNAP_EDGE_BUDGET = 20_000

    def _scene_geometry(self):
        """collect_geometry(scene), cached — camera-independent, so every
        frame (and every re-snap) shares one collection. Follows the same
        staleness rule as the frame renders: refreshed when the composer
        reopens or a frame is explicitly refreshed, not on sheet edits."""
        cached = getattr(self, "_geom_cache", None)
        if cached is not None:
            return cached
        vp = self._window.viewport
        fast = getattr(vp, "hlr_geometry", None)
        if fast is not None:
            self._geom_cache = fast()               # arrays, ~30 ms
        else:                                       # stub viewports (tests)
            from core.hlr import collect_geometry
            import numpy as np
            tris, hard, soft = collect_geometry(self._scene())
            nan3 = (float("nan"),) * 3
            self._geom_cache = (
                np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3),
                np.asarray(hard, dtype=np.float64).reshape(-1, 2, 3),
                np.asarray([(p0, p1) for p0, p1, _a, _b in soft],
                           dtype=np.float64).reshape(-1, 2, 3),
                np.asarray([(na, nan3 if nb is None else nb)
                            for _p0, _p1, na, nb in soft],
                           dtype=np.float64).reshape(-1, 2, 3))
        return self._geom_cache

    def _invalidate_geometry_caches(self) -> None:
        """The model may have changed: drop the collected geometry and
        every frame's snap set (renders are handled by their own caches)."""
        self._geom_cache = None
        self.snap_cache.clear()

    def frame_snap_points(self, frame: MarcoVista):
        """Snappable geometry points of *frame*'s view — an ``(M, 2)`` array
        in PAGE millimetres paired with the same points in WORLD metres
        ``(M, 3)`` (the anchor data): every edge endpoint plus each edge's
        midpoint. Cached by frame id. Small scenes use the same exact
        hidden-line pass the vector style uses (a point only snaps where
        the drawing shows an edge); big scenes project every edge without
        the visibility kernel (see ``_EXACT_SNAP_EDGE_BUDGET``)."""
        import numpy as np
        cached = self.snap_cache.get(id(frame))
        if cached is not None:
            return cached
        from core.composition import model_height_for_frame
        from core.hlr import _to_cam, camera_basis, hlr_view

        geometry = self._scene_geometry()
        tris, hard, soft, _soft_n = geometry

        def page_mapper():
            model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
            k = frame.h_mm / model_h
            half_h = model_h / 2.0
            half_w = half_h * (frame.w_mm / frame.h_mm)

            def to_page(mx, my):
                return (frame.x_mm + (mx + half_w) * k,
                        frame.y_mm + (half_h - my) * k)
            return to_page

        def clip(arr, warr):
            m = ((arr[:, 0] >= frame.x_mm - 0.5)
                 & (arr[:, 0] <= frame.x_mm + frame.w_mm + 0.5)
                 & (arr[:, 1] >= frame.y_mm - 0.5)
                 & (arr[:, 1] <= frame.y_mm + frame.h_mm + 0.5))
            return arr[m], warr[m]

        def run_exact():
            vp = self._window.viewport
            segs, world = hlr_view(vp.scene, vp.camera, return_world=True,
                                   geometry=geometry)
            if not len(segs):
                return np.empty((0, 2)), np.empty((0, 3))
            to_page = page_mapper()
            pts = []
            wpts = []
            for (x0, y0, x1, y1), (w0, w1) in zip(segs, world):
                pts.append(to_page(x0, y0))
                pts.append(to_page(x1, y1))
                pts.append(to_page((x0 + x1) / 2, (y0 + y1) / 2))
                wpts.extend((w0, w1, (w0 + w1) / 2))
            return clip(np.array(pts), np.array(wpts))

        def run_fast():
            vp = self._window.viewport
            E = np.concatenate([np.asarray(hard, dtype=np.float64),
                                np.asarray(soft, dtype=np.float64)])
            if not len(E):
                return np.empty((0, 2)), np.empty((0, 3))
            eye, right, up, fwd = camera_basis(vp.camera)
            a2 = _to_cam(E[:, 0, :], eye, right, up, fwd)[:, :2]
            b2 = _to_cam(E[:, 1, :], eye, right, up, fwd)[:, :2]
            to_page = page_mapper()
            cam = np.concatenate([a2, b2, (a2 + b2) / 2.0])
            world = np.concatenate([E[:, 0, :], E[:, 1, :],
                                    (E[:, 0, :] + E[:, 1, :]) / 2.0])
            px, py = to_page(cam[:, 0], cam[:, 1])
            return clip(np.stack([px, py], axis=1), world)

        exact = len(hard) + len(soft) <= self._EXACT_SNAP_EDGE_BUDGET
        pair = self._with_frame_camera(frame, run_exact if exact
                                       else run_fast)
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
                # 2.5 paper mm at the frame scale, hard-capped at 0.5 m —
                # at 1:1000 an uncapped tolerance is 2.5 m and captures
                # unrelated vertices.
                tol = min(2.5 * frame.scale_n / 1000.0, 0.5)
                old_pages = self._frame_world_to_page(
                    frame, [ct.a_world, ct.b_world])
                for attr, (px, py) in zip(("a_world", "b_world"),
                                          old_pages):
                    # An anchor whose point projects OUTSIDE the frame is
                    # clipped from the snap set, not moved — re-snapping it
                    # would capture whatever visible point is nearest.
                    inside = (frame.x_mm - 0.5 <= px
                              <= frame.x_mm + frame.w_mm + 0.5
                              and frame.y_mm - 0.5 <= py
                              <= frame.y_mm + frame.h_mm + 0.5)
                    if not inside:
                        continue
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
        # Labels: the pointed-at spot follows the model; the text stays.
        for et in getattr(self.comp, "etiquetas", []) or []:
            if not et.anchored:
                continue
            frame = frames.get(et.anchor_uid)
            if frame is None:
                continue
            try:
                _pts, wpts = self.frame_snap_points(frame)
                tol = min(2.5 * frame.scale_n / 1000.0, 0.5)
                (px, py), = self._frame_world_to_page(frame, [et.a_world])
                inside = (frame.x_mm - 0.5 <= px <= frame.x_mm + frame.w_mm + 0.5
                          and frame.y_mm - 0.5 <= py
                          <= frame.y_mm + frame.h_mm + 0.5)
                if inside and len(wpts):
                    w = np.asarray(et.a_world, dtype=np.float64)
                    d2 = ((wpts - w) ** 2).sum(axis=1)
                    i = int(np.argmin(d2))
                    if d2[i] <= tol * tol:
                        et.a_world = [float(v) for v in wpts[i]]
                (px, py), = self._frame_world_to_page(frame, [et.a_world])
                et.ax_mm, et.ay_mm = px - et.x_mm, py - et.y_mm
            except Exception:  # noqa: BLE001
                pass

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
            segs = hlr_view(vp.scene, vp.camera,
                            geometry=self._scene_geometry())
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
            self._stale.discard(id(frame))
            self.hlr_cache[id(frame)] = out
            return out

        return self._with_frame_camera(frame, run)

    def model_view_segments(self, frame: MarcoVista):
        """The frame's hidden-line view in MODEL units (metres, view
        plane) — what the DXF bridge to IngeCAD writes."""
        from core.hlr import hlr_view

        def run():
            vp = self._window.viewport
            return hlr_view(vp.scene, vp.camera,
                            geometry=self._scene_geometry())

        return self._with_frame_camera(frame, run)

    def render_frame(self, frame: MarcoVista) -> Optional[QImage]:
        """Fill *frame*: a GL render for the raster styles, the exact
        hidden-line pass for the vector style. Cached by frame identity;
        the live viewport state always comes back untouched."""
        # The model's annotations (and traced paths) are a paper overlay for
        # EVERY style: text at a paper height with a halo, never baked into
        # the render pixels (where a 9 pt screen font came out unreadably
        # small).
        self.annot_cache[id(frame)] = self.compute_annotations(frame)
        if frame.style == "vectorial":
            self.compute_hlr(frame)
            return None

        def run():
            vp = self._window.viewport
            try:
                if frame.style in ("tecnico", "lineas"):
                    vp.plano_style = frame.style
                elif (isinstance(frame.style, str)
                        and frame.style.startswith("style:")):
                    from core.style import style_by_name
                    vp.style_override = style_by_name(frame.style[6:])
                w_px, h_px = frame.render_px(RENDER_DPI)
                return vp.render_image(w_px, h_px, overlays=False)
            finally:
                vp.plano_style = None
                vp.style_override = None

        image = self._with_frame_camera(frame, run)
        if image is not None and image.hasAlphaChannel():
            # The FBO read-back comes back labelled premultiplied while a
            # translucent face (the water, opacity 0.75) leaves alpha ≈ 0.8
            # under fully bright texels — invalid premultiplied data that
            # the canvas's smooth scaling turns into red and yellow blotches
            # on the water (Marco, 2026-09-02). The render already composed
            # its own background: on paper it is simply opaque.
            image = image.convertToFormat(QImage.Format_RGB32)
        if image is not None:
            self.render_cache[id(frame)] = image
        self._stale.discard(id(frame))
        return image

    def _on_renumber(self) -> None:
        for i, comp in enumerate(self._scene().compositions):
            if comp.cajetin is not None:
                comp.cajetin.set_field("LÁMINA", f"L-{i + 1:02d}")
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

    def _printer_for_sheet(self):
        from PySide6.QtGui import QPageLayout, QPageSize
        from PySide6.QtPrintSupport import QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(getattr(QPageSize, self.comp.paper)))
        printer.setPageOrientation(QPageLayout.Landscape if self.comp.landscape
                                   else QPageLayout.Portrait)
        printer.setFullPage(True)         # the sheet carries its own margins
        return printer

    def _paint_to_printer(self, printer) -> None:
        """Paint the current sheet on *printer* (preview or real print) at
        its resolution, in mm space like the PDF export."""
        painter = QPainter(printer)
        try:
            dpi = float(printer.resolution() or RENDER_DPI)
            painter.scale(dpi / 25.4, dpi / 25.4)
            self._paint_sheet(painter, self.comp)
        finally:
            painter.end()

    def _on_print_preview(self) -> None:
        from PySide6.QtPrintSupport import QPrintPreviewDialog
        printer = self._printer_for_sheet()
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle(tr("Print preview") + " — " + self.comp.name)
        dlg.paintRequested.connect(self._paint_to_printer)
        dlg.resize(1100, 800)
        dlg.exec()

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

    def _set_field_context(self, comp) -> None:
        comps = list(getattr(self._scene(), "compositions", []) or [])
        idx = comps.index(comp) if comp in comps else None
        set_field_context(comp=comp, scene=self._scene(),
                          path=getattr(self._window, "_current_path", None),
                          index=idx, total=len(comps))

    def _paint_sheet(self, painter: QPainter, comp: Composicion) -> None:
        """Draw one sheet's items in mm space (painter already scaled), in
        STACKING order (z) — the print must layer exactly like the canvas."""
        self._set_field_context(comp)
        def paint(m) -> None:
            if isinstance(m, MarcoVista):
                paint_frame_mm(painter, m, self.render_cache.get(id(m)),
                               hlr=self.hlr_cache.get(id(m)),
                               annots=self.annot_cache.get(id(m)))
            elif isinstance(m, ImagenItem):
                paint_image_mm(painter, m, self.image_cache(m.path))
            elif isinstance(m, TextoItem):
                paint_text_mm(painter, m)
            elif isinstance(m, BarraEscala):
                paint_scalebar_mm(painter, m)
            elif isinstance(m, PerfilTerreno):
                paint_perfil_mm(painter, m, *self.profile_for(m))
            elif isinstance(m, FlechaNorte):
                paint_norte_mm(painter, m)
            elif isinstance(m, Leyenda):
                paint_leyenda_mm(painter, m)
            elif isinstance(m, FormaItem):
                paint_forma_mm(painter, m)
            elif isinstance(m, CotaItem):
                paint_cota_mm(painter, m)
            elif isinstance(m, CotaAngularItem):
                paint_cota_angular_mm(painter, m)
            elif isinstance(m, EtiquetaItem):
                paint_etiqueta_mm(painter, m)
            elif isinstance(m, Cajetin):
                paint_cajetin_mm(painter, m)

        for m in sorted(comp.all_items(),
                        key=lambda it: getattr(it, "z", 0.0)):
            painter.save()
            painter.translate(m.x_mm, m.y_mm)
            paint(m)
            painter.restore()
        # The sheet border goes on top: a frame that reaches the margin
        # must not cover it with its render (Marco, 2026-09-02).
        paint_sheet_border_mm(painter, comp)

    # ---- lifecycle -----------------------------------------------------------
    def closeEvent(self, event) -> None:
        from PySide6.QtCore import QSettings
        QSettings().setValue("composer/panel_width",
                             self._splitter.sizes()[1])
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        QTimer.singleShot(0, self._auto_render_stale)
        QTimer.singleShot(0, self._reload_scale_options)
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
        self._invalidate_geometry_caches()
        self._rebuild_canvas()
        super().showEvent(event)
        # First impression: the whole page in view, whatever the paper size.
        self._view.fitInView(self.canvas.sceneRect(), Qt.KeepAspectRatio)
        self.update_zoom_label()
