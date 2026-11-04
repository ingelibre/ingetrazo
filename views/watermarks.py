# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Paint the same resolution-independent image layers in previews and 3D views."""
from __future__ import annotations

import base64
import binascii
from functools import lru_cache

from PySide6.QtCore import QBuffer, QIODevice, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QImage, QImageReader, QPainter, QTransform


def import_image(path: str) -> str:
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise ValueError(reader.errorString())
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ValueError("PNG encoding failed")
    return base64.b64encode(bytes(buffer.data())).decode("ascii")


@lru_cache(maxsize=32)
def watermark_image(data: str) -> QImage:
    try:
        return QImage.fromData(base64.b64decode(data, validate=True), "PNG")
    except (ValueError, binascii.Error):
        return QImage()


def paint_watermarks(painter: QPainter, style, size: QSize, layer: str) -> None:
    if not getattr(style, "watermarks_visible", True):
        return
    width, height = size.width(), size.height()
    if width <= 0 or height <= 0:
        return
    painter.save()
    try:
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setClipRect(QRectF(0, 0, width, height), Qt.IntersectClip)
        # A layer list reads topmost first, like a stack of sheets.
        for mark in reversed(getattr(style, "watermarks", ())):
            if not mark.visible or mark.layer != layer or mark.opacity <= 0:
                continue
            image = watermark_image(mark.image)
            if image.isNull():
                continue
            painter.setOpacity(mark.opacity / 100.0)
            if mark.placement == "stretched":
                target = QRectF(0, 0, width, height)
                if mark.keep_aspect:
                    factor = max(width / image.width(), height / image.height())
                    w, h = image.width() * factor, image.height() * factor
                    target = QRectF((width - w) / 2, (height - h) / 2, w, h)
                painter.drawImage(target, image)
                continue
            w = width * mark.scale / 100.0
            h = w * image.height() / image.width()
            if mark.placement == "tiled":
                brush = QBrush(image)
                brush.setTransform(QTransform.fromScale(w / image.width(), h / image.height()))
                painter.fillRect(QRectF(0, 0, width, height), brush)
                continue
            margin = min(width, height) * 0.02
            col, row = mark.anchor % 3, mark.anchor // 3
            x = (margin, (width - w) / 2, width - w - margin)[col]
            y = (margin, (height - h) / 2, height - h - margin)[row]
            painter.drawImage(QRectF(x, y, w, h), image)
    finally:
        painter.restore()
