# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet compositions — printing the model as a plan, at exact scale.

QGIS-composer-shaped (see docs/composer-plan.md): a ``Composicion`` is a
paper page with items on it; the central item is a ``MarcoVista`` — a frame
that references a view (a saved scene, a standard view or the live camera)
plus a 1:N scale, and is filled by rendering the model with a parallel
camera through the viewport's own pipeline.

This module is headless on purpose (no Qt imports): the geometry of paper
and the scale math live here so they are testable without a GL context.
Model units are METRES; composer units are MILLIMETRES of paper.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

#: ISO 216 portrait sizes, mm (width, height).
PAPER_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}

#: Scales offered in the UI; any positive N is legal.
COMMON_SCALES = (50, 100, 200, 250, 500, 1000, 2000)

#: Print resolution for the raster fill of a view frame.
RENDER_DPI = 300


def mm_to_px(mm: float, dpi: int = RENDER_DPI) -> int:
    """Paper millimetres → device pixels at ``dpi`` (rounded)."""
    return max(int(round(mm / 25.4 * dpi)), 1)


def model_height_for_frame(frame_h_mm: float, scale_n: float) -> float:
    """Metres of model that a frame ``frame_h_mm`` tall shows at 1:N.

    1:100 on a 200 mm frame ⇒ 20 m of model — the sacred equation of the
    whole composer (docs/composer-plan.md)."""
    if frame_h_mm <= 0 or scale_n <= 0:
        raise ValueError("frame height and scale must be positive")
    return frame_h_mm * scale_n / 1000.0


def ortho_distance_for_height(model_h_m: float, fov_deg: float) -> float:
    """Camera ``distance`` that makes OrbitCamera's parallel projection show
    exactly ``model_h_m`` metres vertically.

    The camera derives its ortho half-height from distance·tan(fov/2)
    (core/camera.py), so we invert that instead of duplicating projection
    code — one source of truth for the frustum."""
    half = model_h_m / 2.0
    t = math.tan(math.radians(fov_deg) / 2.0)
    if t <= 0:
        raise ValueError("fov must be in (0, 180)")
    return half / t


@dataclass
class MarcoVista:
    """A model-view frame on the page.

    ``view_key`` names what fills it: ``"__current__"`` (the live camera),
    ``"std:top"``/``"std:front"``/… (standard views), or ``"scene:<name>"``
    (a SavedView by name). The fill is re-rendered on demand; the frame
    stores no pixels of its own."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 170.0
    h_mm: float = 170.0
    scale_n: float = 100.0
    view_key: str = "__current__"

    def model_height_m(self) -> float:
        return model_height_for_frame(self.h_mm, self.scale_n)

    def render_px(self, dpi: int = RENDER_DPI) -> tuple[int, int]:
        return mm_to_px(self.w_mm, dpi), mm_to_px(self.h_mm, dpi)


@dataclass
class Composicion:
    """One sheet (C1: single page, single frame; C2 grows items/pages)."""

    name: str = "Lámina 1"
    paper: str = "A4"
    landscape: bool = True
    margin_mm: float = 10.0
    frames: list = field(default_factory=list)

    def page_size_mm(self) -> tuple[float, float]:
        w, h = PAPER_SIZES_MM[self.paper]
        return (h, w) if self.landscape else (w, h)

    def default_frame(self) -> MarcoVista:
        """A frame filling the page inside the margins (the C1 starter)."""
        pw, ph = self.page_size_mm()
        m = self.margin_mm
        return MarcoVista(x_mm=m, y_mm=m, w_mm=pw - 2 * m, h_mm=ph - 2 * m)


def apply_frame_camera(camera, frame: MarcoVista,
                       saved_view=None, scene=None) -> None:
    """Point ``camera`` (an OrbitCamera) at the frame's view, parallel, at
    exact scale. Mutates the camera (and layer visibility when a saved view
    is given) — callers snapshot/restore around this; see
    ``views/composer.py``."""
    if saved_view is not None and scene is not None:
        saved_view.apply(scene, camera)
    elif frame.view_key.startswith("std:"):
        camera.set_view(frame.view_key[4:])
        # A standard view carries an orientation but no framing: centre on
        # the model, or a big scale leaves it cropped out of the frame (the
        # live/saved views keep their own target — the user framed those).
        if scene is not None:
            lo, hi = scene.bounds()
            if lo is not None:
                camera.target = (lo + hi) * 0.5
    camera.perspective = False
    camera.distance = ortho_distance_for_height(
        frame.model_height_m(), camera.fov_deg)
    w_px, h_px = frame.render_px()
    camera.aspect = w_px / h_px
