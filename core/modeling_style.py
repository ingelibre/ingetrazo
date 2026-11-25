# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Modeling display cues and the scene visibility remembered by a style."""
from __future__ import annotations

import math

MODELING_COLORS = {
    "selected": (0.95, 0.45, 0.16),
    "locked": (0.9, 0.12, 0.12),
    "guides": (70 / 255, 90 / 255, 120 / 255),
    "section_inactive": (178 / 255, 182 / 255, 188 / 255),
    "section_active": (243 / 255, 115 / 255, 41 / 255),
    "section_cut": (0.13, 0.17, 0.23),
}
VISIBILITY = ("show_hidden_geometry", "show_section_planes", "show_section_cuts", "show_axes")


def load_modeling_colors(raw) -> dict:
    result = {}
    if isinstance(raw, dict):
        for key in MODELING_COLORS:
            try:
                color = tuple(float(v) for v in raw[key])
                if len(color) == 3 and all(math.isfinite(v) for v in color):
                    result[key] = tuple(min(1.0, max(0.0, v)) for v in color)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
    return result


def load_modeling_visibility(raw) -> dict:
    return {key: bool(raw[key]) for key in VISIBILITY if key in raw} if isinstance(raw, dict) else {}


def modeling_color(style, key: str, default=None) -> tuple:
    colors = getattr(style, "modeling_colors", {})
    if key in colors:
        return tuple(colors[key])
    return tuple(MODELING_COLORS[key] if default is None else default)


def set_modeling_visibility(scene, attr: str, on: bool, *, remember=True) -> None:
    if attr not in VISIBILITY:
        raise ValueError(attr)
    changed = bool(getattr(scene, attr, attr != "show_hidden_geometry")) != bool(on)
    setattr(scene, attr, bool(on))
    style = getattr(scene, "display_style", None)
    if remember and style is not None:
        style.modeling_visibility[attr] = bool(on)
    if changed and attr == "show_hidden_geometry":
        if not on:
            for entity in list(scene.selection):
                if scene.entity_hidden(entity) or getattr(entity, "hidden", False):
                    scene.selection.discard(entity)
        scene.version += 1  # Rebuild snap/pick caches when hidden geometry changes.


def apply_modeling_visibility(scene) -> None:
    for attr, value in getattr(scene.display_style, "modeling_visibility", {}).items():
        set_modeling_visibility(scene, attr, value, remember=False)
    if not getattr(scene.display_style, "show_guides", True):
        for guide in scene.guides:
            scene.selection.discard(guide)


def section_cut_quads(segments, matrix, width, height, pixels):
    """Expand cut segments in screen pixels, returning world-space triangles."""
    import numpy as np

    segments = np.asarray(segments, dtype=np.float64).reshape((-1, 2, 3))
    matrix = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return np.empty((0, 3), dtype=np.float32)
    clip = np.concatenate((segments, np.ones((*segments.shape[:2], 1))), axis=2) @ matrix.T
    a, b = clip[:, 0], clip[:, 1]
    lo, hi = np.zeros(len(a)), np.ones(len(a))
    valid = np.ones(len(a), dtype=bool)
    # Clip at the near/far planes before the perspective division.
    for da, db in ((a[:, 2] + a[:, 3], b[:, 2] + b[:, 3]),
                   (a[:, 3] - a[:, 2], b[:, 3] - b[:, 2]),
                   (a[:, 3] - 1e-8, b[:, 3] - 1e-8)):
        valid &= (da >= 0) | (db >= 0)
        t = np.divide(da, da - db, out=np.zeros_like(da), where=abs(da - db) > 1e-20)
        lo = np.where(da < 0, np.maximum(lo, t), lo)
        hi = np.where(db < 0, np.minimum(hi, t), hi)
    valid &= lo <= hi
    delta = b - a
    b = a + delta * hi[:, None]
    a = a + delta * lo[:, None]
    a, b = a[valid], b[valid]
    direction = (b[:, :2] / b[:, 3:4] - a[:, :2] / a[:, 3:4]) * (width / 2, height / 2)
    length = np.linalg.norm(direction, axis=1)
    valid = length > 1e-8
    a, b, direction, length = a[valid], b[valid], direction[valid], length[valid]
    offset = np.stack((-direction[:, 1], direction[:, 0]), axis=1)
    offset *= (pixels / 2) / length[:, None]
    offset *= (2 / width, 2 / height)
    q0, q1, q2, q3 = a.copy(), b.copy(), b.copy(), a.copy()
    q0[:, :2] -= offset * a[:, 3:4]
    q1[:, :2] -= offset * b[:, 3:4]
    q2[:, :2] += offset * b[:, 3:4]
    q3[:, :2] += offset * a[:, 3:4]
    vertices = np.stack((q0, q1, q2, q0, q2, q3), axis=1).reshape((-1, 4))
    vertices[:, 2] -= vertices[:, 3] * 2e-6  # In front of the coplanar fill.
    world = vertices @ inverse.T
    return (world[:, :3] / world[:, 3:4]).astype(np.float32)
