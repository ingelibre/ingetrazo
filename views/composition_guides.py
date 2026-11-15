# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Composition guides: lines to frame a picture by, as a camera's
viewfinder shows them — the rule of thirds, the golden ratio, a grid, the
diagonals, the centre.

They are only drawn, never exported: over the preview of Export View
(SVG) and over the 3D view (a scene tab's right-click menu ▸ Composition
Guides), where they fall inside the camera's frame when it has one.
"""
from __future__ import annotations

from PySide6.QtCore import QLineF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

#: Every guide, ``"none"`` first (no lines), and how a file's value is read
#: — the camera keeps the guide it shows (``OrbitCamera.composition_guide``).
from core.camera import COMPOSITION_GUIDES as GUIDES  # noqa: F401
from core.camera import read_composition_guide as read_guide  # noqa: F401
from core.i18n import tr

#: The guides the SVG preview begins with, and the one the view's switch
#: turns on before any other was chosen.
DEFAULT_GUIDES = "thirds"

#: The golden section of a side: where the golden ratio's lines fall.
GOLDEN = (5.0 ** 0.5 - 1.0) / 2.0         # 0.618…


def guide_names() -> dict:
    """Each guide's name, in the interface language."""
    return {"none": tr("No guides"), "thirds": tr("Rule of thirds"),
            "golden": tr("Golden ratio"), "grid": tr("Grid"),
            "diagonals": tr("Diagonals"), "centre": tr("Centre")}


def draw_guides(p: QPainter, page: QRectF, key: str) -> None:
    """The composition guides ``key`` over the rectangle ``page``: a light
    line over a dark one, so they read on paper and on a picture alike."""
    x0, y0, w, h = page.x(), page.y(), page.width(), page.height()
    lines = []

    def across(fracs):
        for f in fracs:
            lines.append(QLineF(x0 + f * w, y0, x0 + f * w, y0 + h))
            lines.append(QLineF(x0, y0 + f * h, x0 + w, y0 + f * h))

    if key == "thirds":
        across((1.0 / 3.0, 2.0 / 3.0))
    elif key == "golden":
        across((1.0 - GOLDEN, GOLDEN))
    elif key == "grid":
        across((0.25, 0.5, 0.75))
    elif key == "diagonals":
        lines.append(QLineF(page.topLeft(), page.bottomRight()))
        lines.append(QLineF(page.bottomLeft(), page.topRight()))
    elif key == "centre":
        c = page.center()
        arm = min(w, h) * 0.12
        lines.append(QLineF(c.x() - arm, c.y(), c.x() + arm, c.y()))
        lines.append(QLineF(c.x(), c.y() - arm, c.x(), c.y() + arm))
    if not lines:
        return
    ring = min(w, h) * 0.04 if key == "centre" else 0.0
    p.save()
    p.setClipRect(page)
    p.setBrush(Qt.NoBrush)
    for pen in (QPen(QColor(0, 0, 0, 90), 2.2),
                QPen(QColor(255, 255, 255, 200), 1.0)):
        p.setPen(pen)
        p.drawLines(lines)
        if ring:
            p.drawEllipse(page.center(), ring, ring)
    p.restore()
