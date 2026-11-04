# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Small, deterministic style samples painted without an OpenGL context."""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF,
)

from core.style import DEFAULT_FACE_COLOR, Style, effective_back_color


def _color(rgb, shade: float = 1.0) -> QColor:
    return QColor.fromRgbF(*(max(0.0, min(1.0, float(v) * shade))
                             for v in rgb[:3]))


def _polygon(points) -> QPolygonF:
    return QPolygonF([QPointF(x, y) for x, y in points])


def style_preview(style: Style, size: QSize) -> QPixmap:
    """Paint a sample box with an unpainted face, material and back face.

    The sample illustrates the style's existing display settings, rather
    than rendering the current model. It needs only a QApplication, so it
    remains cheap and available on systems without an OpenGL context.
    """
    pixmap = QPixmap(size)
    pixmap.fill(_color(style.background))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size.width() / 100.0, size.height() / 80.0)
    try:
        if style.sky:
            horizon = getattr(style, "horizon_color", None) or (0.98, 0.98, 0.98)
            sky = QLinearGradient(0, 0, 0, 48)
            sky.setColorAt(0, _color(style.sky_color))
            sky.setColorAt(1, _color(horizon))
            painter.fillRect(QRectF(0, 0, 100, 48), sky)
            ground = QLinearGradient(0, 48, 0, 80)
            ground.setColorAt(0, _color(style.ground_color, 1.07))
            ground.setColorAt(1, _color(style.ground_color))
            painter.fillRect(QRectF(0, 48, 100, 32), ground)

        mode = style.face_mode
        edge = _color(style.edge_color)
        top = [(47, 13), (79, 28), (49, 43), (17, 28)]
        left = [(17, 28), (49, 43), (49, 73), (17, 58)]
        right = [(49, 43), (79, 28), (79, 58), (49, 73)]
        hidden = [((17, 58), (47, 43)), ((47, 43), (79, 58)),
                  ((47, 13), (47, 43))]

        if mode != "wireframe":
            flat = mode in ("hidden_line", "monochrome")
            front = (style.front_color if flat else
                     tuple(a * b for a, b in zip(DEFAULT_FACE_COLOR,
                                                style.front_color)))
            material = front if flat else (0.68, 0.55, 0.39)
            painter.setPen(Qt.NoPen)
            if mode == "xray":
                painter.setOpacity(0.48)
            for points, rgb, shade in ((top, front, 1.0),
                                       (left, front, 0.91 if not flat else 1.0),
                                       (right, material, 0.78 if not flat else 1.0)):
                painter.setBrush(_color(rgb, shade))
                painter.drawPolygon(_polygon(points))

            # A small recessed panel exposes a back face in the sample.
            if mode != "hidden_line":
                painter.setBrush(_color(effective_back_color(style)))
                painter.drawPolygon(_polygon([(27, 40), (39, 46),
                                               (39, 62), (27, 56)]))

            if mode == "textures":
                painter.save()
                pen = QPen(_color(material, 0.66), 0.65)
                painter.setPen(pen)
                for offset in (6, 12, 18, 24):
                    painter.drawLine(QPointF(49 + offset, 43 - offset / 2),
                                     QPointF(49 + offset, 73 - offset / 2))
                painter.restore()
            painter.setOpacity(1.0)

        if mode in ("wireframe", "xray") or style.back_edges:
            pen = QPen(edge, 0.95)
            if mode != "wireframe":
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            for start, end in hidden:
                painter.drawLine(QPointF(*start), QPointF(*end))

        if style.edges or style.profiles or mode in ("wireframe", "xray"):
            from core.edge_style import AXIS_COLORS
            # Local sample edges with their 3D axis and a small independent
            # paint sample. This is a style illustration, not model geometry.
            segments = ((top[0], top[1], 0), (top[1], top[2], 1),
                        (top[2], top[3], 0), (top[3], top[0], 1),
                        (left[0], left[3], 2), (left[3], left[2], 0),
                        (left[2], left[1], 2), (right[1], right[2], 2),
                        (right[2], right[3], 1))
            outline = {0, 3, 4, 5, 7, 8}
            for index, (a, b, axis) in enumerate(segments):
                if not style.edges and mode not in ("wireframe", "xray") and index not in outline:
                    continue
                color = edge
                if style.edge_color_mode == "axis":
                    color = _color(AXIS_COLORS[axis])
                elif style.edge_color_mode == "material" and index in (1, 7, 8):
                    color = _color((0.68, 0.55, 0.39))
                width = style.profile_width if style.profiles and index in outline else 1.0
                if style.depth_cue:
                    width = max(width, 1 + (style.depth_cue_width - 1) * (a[1] + b[1]) / 160)
                width = min(8, width)
                pen = QPen(color, width)
                painter.setPen(pen)
                dx, dy = b[0] - a[0], b[1] - a[1]
                length = max(math.hypot(dx, dy), 1e-6)
                dx, dy = dx / length, dy / length
                extension = min(10, style.extension_length) if style.extensions else 0
                painter.drawLine(QPointF(a[0] - dx * extension, a[1] - dy * extension),
                                 QPointF(b[0] + dx * extension, b[1] + dy * extension))
                if style.endpoints:
                    pen.setWidthF(width + 2)
                    painter.setPen(pen)
                    size = min(length / 2, style.endpoint_length)
                    painter.drawLine(QPointF(*a), QPointF(a[0] + dx * size, a[1] + dy * size))
                    painter.drawLine(QPointF(*b), QPointF(b[0] - dx * size, b[1] - dy * size))
    finally:
        painter.end()
    return pixmap
