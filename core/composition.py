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
    #: Render style: "sombreado" (the live look), "tecnico" (white faces +
    #: dark edges on white — the plan look) or "lineas" (edges only).
    style: str = "sombreado"
    #: Draw the automatic title under the frame («Planta — 1:100»).
    show_title: bool = False

    def model_height_m(self) -> float:
        return model_height_for_frame(self.h_mm, self.scale_n)

    def render_px(self, dpi: int = RENDER_DPI) -> tuple[int, int]:
        return mm_to_px(self.w_mm, dpi), mm_to_px(self.h_mm, dpi)


@dataclass
class TextoItem:
    """A free text block on the sheet. ``size_pt`` is the printed size in
    points (1 pt = 0.3528 mm on paper), like any DTP tool."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 80.0
    text: str = ""
    size_pt: float = 14.0
    bold: bool = False


@dataclass
class ImagenItem:
    """An image (logo, photo) on the sheet. The file is referenced by path;
    the .igz stores the path, not the pixels (same policy as textures)."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 60.0
    h_mm: float = 40.0
    path: str = ""


@dataclass
class Cajetin:
    """The title block — for the trade, THE item of a sheet. A classic
    bordered grid of labelled fields, anchored wherever the user drops it."""

    x_mm: float = 0.0
    y_mm: float = 0.0
    w_mm: float = 180.0
    h_mm: float = 33.0
    proyecto: str = ""
    autor: str = ""
    fecha: str = ""
    escala: str = ""
    lamina: str = "L-01"

    #: (label, field-name) rows, in drawing order — shared by the canvas
    #: item and the PDF export so both always agree.
    FIELDS = (("PROYECTO", "proyecto"), ("AUTOR", "autor"),
              ("FECHA", "fecha"), ("ESCALA", "escala"),
              ("LÁMINA", "lamina"))


@dataclass
class BarraEscala:
    """A graphic scale bar: alternating black/white segments with metre
    labels — the reader can measure even from a bad photocopy."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    scale_n: float = 100.0
    segments: int = 4

    def segment_m(self) -> float:
        """A round model length per segment so the whole bar prints close
        to (but under) ~100 mm of paper."""
        target_mm = 100.0 / self.segments
        raw_m = target_mm * self.scale_n / 1000.0
        nice = (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50,
                100, 200, 250, 500, 1000, 2000, 5000)
        best = nice[0]
        for n in nice:
            if n <= raw_m:
                best = n
        return float(best)

    def segment_mm(self) -> float:
        return self.segment_m() * 1000.0 / self.scale_n

    @property
    def w_mm(self) -> float:            # noqa: D401 — sizing protocol
        return self.segment_mm() * self.segments

    @property
    def h_mm(self) -> float:
        return 8.0


@dataclass
class Composicion:
    """One sheet: a page plus its items."""

    name: str = "Lámina 1"
    paper: str = "A4"
    landscape: bool = True
    margin_mm: float = 10.0
    frames: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    images: list = field(default_factory=list)
    scalebars: list = field(default_factory=list)
    cajetin: Optional[Cajetin] = None

    def page_size_mm(self) -> tuple[float, float]:
        w, h = PAPER_SIZES_MM[self.paper]
        return (h, w) if self.landscape else (w, h)

    def default_frame(self) -> MarcoVista:
        """A frame filling the page inside the margins (the C1 starter)."""
        pw, ph = self.page_size_mm()
        m = self.margin_mm
        return MarcoVista(x_mm=m, y_mm=m, w_mm=pw - 2 * m, h_mm=ph - 2 * m)

    def default_cajetin(self) -> Cajetin:
        """A title block sized to the page, docked to the bottom-right
        margin corner (where every drawing office expects it)."""
        pw, ph = self.page_size_mm()
        m = self.margin_mm
        w = min(180.0, pw - 2 * m)
        h = 33.0
        return Cajetin(x_mm=pw - m - w, y_mm=ph - m - h, w_mm=w, h_mm=h)

    def all_items(self) -> list:
        out = (list(self.frames) + list(self.texts) + list(self.images)
               + list(self.scalebars))
        if self.cajetin is not None:
            out.append(self.cajetin)
        return out

    # ---- Serialisation (.igz) -----------------------------------------------
    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = {"name": self.name, "paper": self.paper,
             "landscape": self.landscape, "margin_mm": self.margin_mm,
             "frames": [asdict(f) for f in self.frames]}
        if self.texts:
            d["texts"] = [asdict(t) for t in self.texts]
        if self.images:
            d["images"] = [asdict(i) for i in self.images]
        if self.scalebars:
            d["scalebars"] = [asdict(sb) for sb in self.scalebars]
        if self.cajetin is not None:
            d["cajetin"] = asdict(self.cajetin)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Composicion":
        c = cls(name=d.get("name", "Lámina 1"),
                paper=d.get("paper", "A4"),
                landscape=bool(d.get("landscape", True)),
                margin_mm=float(d.get("margin_mm", 10.0)))
        c.frames = [MarcoVista(**f) for f in d.get("frames", [])]
        c.texts = [TextoItem(**t) for t in d.get("texts", [])]
        c.images = [ImagenItem(**i) for i in d.get("images", [])]
        c.scalebars = [BarraEscala(**sb) for sb in d.get("scalebars", [])]
        if "cajetin" in d:
            c.cajetin = Cajetin(**d["cajetin"])
        return c


# ── Composer-scoped undo ────────────────────────────────────────────────────
#
# Sheet items are plain dataclasses, far from the mesh; the drawing History
# (core/history.py) snapshots the mesh transactionally, which would be pure
# overhead here. Same Command invariant, its own light stacks — the QGIS
# shape again (one undo stack per layout).

class ComposerCommand:
    """Reversible operation against a Composicion."""

    def do(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def undo(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class AddItemCommand(ComposerCommand):
    """Append *item* to *container* (a list) or set ``comp.cajetin``."""

    def __init__(self, comp: Composicion, item) -> None:
        self.comp = comp
        self.item = item

    def _list(self):
        if isinstance(self.item, MarcoVista):
            return self.comp.frames
        if isinstance(self.item, TextoItem):
            return self.comp.texts
        if isinstance(self.item, ImagenItem):
            return self.comp.images
        if isinstance(self.item, BarraEscala):
            return self.comp.scalebars
        return None

    def do(self) -> None:
        lst = self._list()
        if lst is None:
            self._prev = self.comp.cajetin
            self.comp.cajetin = self.item
        else:
            lst.append(self.item)

    def undo(self) -> None:
        lst = self._list()
        if lst is None:
            self.comp.cajetin = self._prev
        else:
            lst.remove(self.item)


class RemoveItemCommand(ComposerCommand):
    def __init__(self, comp: Composicion, item) -> None:
        self.comp = comp
        self.item = item

    def _list(self):
        if isinstance(self.item, MarcoVista):
            return self.comp.frames
        if isinstance(self.item, TextoItem):
            return self.comp.texts
        if isinstance(self.item, ImagenItem):
            return self.comp.images
        if isinstance(self.item, BarraEscala):
            return self.comp.scalebars
        return None

    def do(self) -> None:
        lst = self._list()
        if lst is None:
            self.comp.cajetin = None
        else:
            lst.remove(self.item)

    def undo(self) -> None:
        lst = self._list()
        if lst is None:
            self.comp.cajetin = self.item
        else:
            lst.append(self.item)


class EditItemCommand(ComposerCommand):
    """Field-level mutation of any sheet item (move, resize, retype…):
    captures before/after snapshots of the named fields."""

    def __init__(self, item, changes: dict, before: Optional[dict] = None) -> None:
        self.item = item
        self.after = dict(changes)
        # An interactive drag has already mutated the item by release time;
        # the caller passes the state it captured at press.
        self.before = dict(before) if before is not None else \
            {k: getattr(item, k) for k in changes}

    def do(self) -> None:
        for k, v in self.after.items():
            setattr(self.item, k, v)

    def undo(self) -> None:
        for k, v in self.before.items():
            setattr(self.item, k, v)


class ComposerHistory:
    """Undo/redo stacks for one composer session.

    ``execute(..., notify=False)`` lets live panel edits (a keystroke in a
    text field) land on the stack without triggering the canvas rebuild —
    the caller repaints the one item itself. Consecutive edits to the same
    item and fields COALESCE into one undo step, so Ctrl+Z undoes "the
    retype", not letter by letter."""

    def __init__(self, on_change=None) -> None:
        self._undo: list[ComposerCommand] = []
        self._redo: list[ComposerCommand] = []
        self._on_change = on_change

    def execute(self, cmd: ComposerCommand, notify: bool = True,
                coalesce: bool = False) -> None:
        cmd.do()
        top = self._undo[-1] if self._undo else None
        if (coalesce and isinstance(cmd, EditItemCommand)
                and isinstance(top, EditItemCommand)
                and top.item is cmd.item
                and set(top.after) == set(cmd.after)):
            top.after = dict(cmd.after)      # keep top's `before`
        else:
            self._undo.append(cmd)
        self._redo.clear()
        if notify and self._on_change:
            self._on_change()

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        if self._on_change:
            self._on_change()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        cmd.do()
        self._undo.append(cmd)
        if self._on_change:
            self._on_change()
        return True


def snap_mm(value: float, targets, threshold: float = 2.0) -> float:
    """Snap *value* to the nearest target within *threshold* mm (page edges,
    margins, other items' edges). Returns the value untouched when nothing
    is close enough."""
    best = None
    for t in targets:
        d = abs(value - t)
        if d <= threshold and (best is None or d < abs(value - best)):
            best = t
    return value if best is None else best


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
