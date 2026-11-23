# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The drawing grid on the ground (issue #780).

A display aid, not model geometry: lines on the Z=0 plane every
``spacing`` metres, a stronger line every ``major`` divisions, and — when
«Snap to Grid» is on — a free point on the ground rounded to the nearest
crossing. Both are OFF by default: the infinite axes stay the spatial
reference of a document that never asks for a grid.

The settings belong to the document (``Scene.grid``) and travel in the
.igz: a piece of furniture and a town square want different spacings.
``None`` there means «never touched»: grid hidden, snap off and the
spacing that suits the model's units (:func:`default_spacing`).
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

#: Smallest and largest spacing accepted, in metres (0.1 mm … 1 km).
MIN_SPACING = 1e-4
MAX_SPACING = 1000.0
#: Divisions between two major lines; 1 makes every line a major one.
MIN_MAJOR, MAX_MAJOR = 1, 100
DEFAULT_MAJOR = 10
#: How far off the ground (metres) a point still counts as on it.
GROUND_TOL = 1e-6

#: The colour of the grid snap marker: the grid's own neutral grey-blue.
COLOR_GRID = (0.36, 0.45, 0.58)


def default_spacing(unit: str | None) -> float:
    """The spacing a new grid starts with, in metres, for a model in
    ``unit``: 1 m in metres, 10 cm in centimetres or millimetres (a room,
    a piece of furniture), one foot in imperial units."""
    if unit in ("cm", "mm"):
        return 0.1
    if unit in ("in", "ft", "ft-in", "in-frac", "ft-in-frac"):
        return 0.3048
    return 1.0


def defaults(unit: str | None = "m") -> dict:
    return {"visible": False, "snap": False,
            "spacing": default_spacing(unit), "major": DEFAULT_MAJOR,
            "color": None}


def _spacing(value, fallback: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(v) or v <= 0:
        return fallback
    return min(MAX_SPACING, max(MIN_SPACING, v))


def _major(value) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAJOR
    return min(MAX_MAJOR, max(MIN_MAJOR, v))


def _color(value):
    """An ``(r, g, b)`` of floats in [0, 1], or None (automatic)."""
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        rgb = tuple(float(c) for c in value[:3])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(c) for c in rgb):
        return None
    return tuple(min(1.0, max(0.0, c)) for c in rgb)


def normalized(raw, unit: str | None = "m") -> dict:
    """``raw`` (a stored dict, or anything) as a complete, valid grid
    setting; what is missing or broken takes its default."""
    base = defaults(unit)
    if not isinstance(raw, dict):
        return base
    return {"visible": bool(raw.get("visible", False)),
            "snap": bool(raw.get("snap", False)),
            "spacing": _spacing(raw.get("spacing"), base["spacing"]),
            "major": _major(raw.get("major", DEFAULT_MAJOR)),
            "color": _color(raw.get("color"))}


def _unit_of(scene) -> str:
    units = getattr(scene, "units", None)
    if isinstance(units, dict):
        return str(units.get("length", "m"))
    return "m"


def grid_of(scene) -> dict:
    """The grid of ``scene``, complete (see :func:`normalized`)."""
    return normalized(getattr(scene, "grid", None), _unit_of(scene))


def set_grid(scene, **changes) -> dict:
    """Change some of ``scene``'s grid settings; returns the result."""
    grid = grid_of(scene)
    grid.update(changes)
    scene.grid = normalized(grid, _unit_of(scene))
    return scene.grid


def to_payload(scene) -> dict | None:
    """What the .igz keeps of the grid: nothing while it was never set
    (old readers and untouched documents see no change)."""
    raw = getattr(scene, "grid", None)
    if raw is None:
        return None
    grid = normalized(raw, _unit_of(scene))
    out = dict(grid)
    if out["color"] is not None:
        out["color"] = list(out["color"])
    return out


def from_payload(payload: dict, unit: str | None = "m") -> dict | None:
    raw = payload.get("grid") if isinstance(payload, dict) else None
    return normalized(raw, unit) if isinstance(raw, dict) else None


def snap_active(scene) -> bool:
    """Snap to Grid acts only while the grid is also shown: a snap the
    user cannot see would only move points for no visible reason."""
    grid = grid_of(scene)
    return grid["visible"] and grid["snap"]


def round_to_grid(point: QVector3D, spacing: float) -> QVector3D | None:
    """The grid crossing nearest ``point``, or None when ``point`` is not
    on the ground (Z=0)."""
    if abs(point.z()) > GROUND_TOL or not spacing > 0:
        return None
    x = round(point.x() / spacing) * spacing
    y = round(point.y() / spacing) * spacing
    return QVector3D(x, y, 0.0)


def snap_point(scene, point: QVector3D) -> QVector3D | None:
    """``point`` moved to the nearest crossing of ``scene``'s grid, or
    None when the grid snap is off or the point is not on the ground."""
    if not snap_active(scene):
        return None
    return round_to_grid(point, grid_of(scene)["spacing"])


def auto_color(base_rgb) -> tuple:
    """A line colour that reads on ``base_rgb`` (the ground or the
    background behind the grid): darker on a light base, lighter on a dark
    one."""
    r, g, b = (float(c) for c in tuple(base_rgb)[:3])
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if luma > 0.5:
        return (max(0.0, r * 0.45), max(0.0, g * 0.45), max(0.0, b * 0.48))
    return (min(1.0, r + 0.45), min(1.0, g + 0.45), min(1.0, b + 0.47))


def line_color(scene, base_rgb) -> tuple:
    grid = grid_of(scene)
    return grid["color"] if grid["color"] is not None else auto_color(base_rgb)
