# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Refined toolbar artwork with live palette colors, separate from cursors.

One SVG template per tool supplies the geometry. Neutral ink follows Qt's
palette; accents retain the selected hue with a tone suited to the toolbar
background. Explicit raster sizes keep small and HiDPI toolbar buttons crisp.
"""
from __future__ import annotations

import colorsys
from functools import lru_cache
import json
import logging

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from core.paths import app_root

_INK_TOKEN = "__INGETRAZO_INK__"
_ACCENT_TOKEN = "__INGETRAZO_ACCENT__"
_PIXEL_SIZES = (20, 24, 32, 40, 48, 80, 96, 120)
_LOG = logging.getLogger(__name__)


def _luminance(color: QColor) -> float:
    def linear(channel):
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    return sum(weight * linear(channel) for weight, channel in zip(
        (0.2126, 0.7152, 0.0722), (color.redF(), color.greenF(), color.blueF())))


def _contrast(first: QColor, second: QColor) -> float:
    low, high = sorted((_luminance(first), _luminance(second)))
    return (high + 0.05) / (low + 0.05)


def accent_tone(accent: QColor, background: QColor) -> QColor:
    """Return a readable accent tone without changing the selected hue.

    This applies to opaque strokes and handles. Decorative translucent fills
    retain their original opacity; cursor colors and hover colors are untouched.
    """
    dark = background.lightnessF() < 0.5
    target = 4.5 if dark else 3.2
    hue, lightness, saturation = colorsys.rgb_to_hls(
        accent.redF(), accent.greenF(), accent.blueF())
    if dark:
        lightness = max(lightness, 0.68)
    for _ in range(201):
        channels = colorsys.hls_to_rgb(hue, lightness, saturation)
        tone = QColor(*(round(channel * 255) for channel in channels))
        if _contrast(tone, background) >= target:
            return tone
        lightness = max(0.0, min(1.0, lightness + (0.005 if dark else -0.005)))
    # A nonstandard mid-grey palette may not permit the preferred tone.
    return max((QColor("black"), QColor("white")),
               key=lambda color: _contrast(color, background))


@lru_cache(maxsize=1)
def _templates() -> dict[str, str]:
    path = app_root() / "resources" / "icons" / "toolbar.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))["icons"]
    except (OSError, ValueError, KeyError):
        _LOG.warning("Refined toolbar artwork unavailable; using the drawn icons", exc_info=True)
        return {}


@lru_cache(maxsize=256)
def _render(key: str, ink_rgba: int, accent_rgba: int) -> QIcon | None:
    template = _templates().get(key)
    if template is None:
        return None
    svg = template.replace(_INK_TOKEN, QColor.fromRgba(ink_rgba).name())
    svg = svg.replace(_ACCENT_TOKEN, QColor.fromRgba(accent_rgba).name())
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        _LOG.warning("Invalid refined toolbar artwork: %s", key)
        return None
    icon = QIcon()
    for size in _PIXEL_SIZES:
        image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(QPixmap.fromImage(image))
    return icon


def toolbar_icon(key: str, ink: QColor, accent: QColor, background: QColor) -> QIcon | None:
    """Return the themed artwork, or None for the legacy drawing fallback."""
    tone = accent_tone(accent, background)
    icon = _render(key, ink.rgba(), tone.rgba())
    # QIcon is implicitly shared. Return a copy so callers cannot mutate the cache.
    return QIcon(icon) if icon is not None else None
