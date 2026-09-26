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

from core.i18n import tr as _tr

#: ISO 216 portrait sizes, mm (width, height).
PAPER_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}

#: Scales offered in the UI; any positive N is legal.
#: The scale list, as DENOMINATORS of 1:N. Below 1 they are enlargements:
#: 0.5 is 2:1, 0.1 is 10:1. Architecture reduces, but «cuando utilizamos
#: objetos que son más pequeños, pues aquí necesitamos poner 10 a uno de
#: ampliación… no la tienes en la lista» (Rafael, 34:00).
COMMON_SCALES = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 25,
                 50, 100, 200, 250, 500, 1000, 2000)


def format_scale(n: float) -> str:
    """A scale the way a drawing writes it: ``1:50`` when it reduces,
    ``10:1`` when it enlarges, ``1:1`` at full size. Never ``1:0.1``, which
    is what the sheet used to print for a tenfold enlargement (Rafael,
    35:00: «no me muestra la escala que yo le había metido, que era 10 a
    uno»)."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    if n < 1.0:
        return f"{1.0 / n:g}:1"
    return f"1:{n:g}"


def parse_scale(text: str, default: float = 100.0) -> float:
    """The denominator a typed scale means. ``1:50`` → 50, ``10:1`` → 0.1,
    ``50`` → 50. Reading only what follows the colon turned a typed
    ``10:1`` into 1:1 — silently, on a technical drawing."""
    s = str(text or "").strip().replace(",", ".")
    if ":" in s:
        left, _, right = s.partition(":")
        try:
            a, b = float(left), float(right)
        except ValueError:
            return default
        if a <= 0 or b <= 0:
            return default
        return b / a                      # 1:50 → 50, 10:1 → 0.1
    try:
        n = float(s)
    except ValueError:
        return default
    return n if n > 0 else default

#: Print resolution for the raster fill of a view frame.
RENDER_DPI = 300

#: Points → millimetres (text sizes on paper).
PT_TO_MM = 25.4 / 72.0


def pen_px(mm: float, dpi: int = RENDER_DPI) -> int:
    """A pen width on paper as whole render pixels (at least the one-pixel
    hairline): 0.18 mm at 300 dpi is 2 px, 0.35 mm is 4 px."""
    return max(1, int(round(float(mm or 0.0) / 25.4 * dpi)))


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


def fit_distance_for_scene(scene, fov_deg: float,
                           default: float = 30.0) -> float:
    """Eye distance that fits the whole model in a perspective frame — what
    a view with no scene of its own (``std:iso``, the live camera) needs the
    moment it turns perspective, or it would open standing inside a wall."""
    if scene is None:
        return default
    try:
        lo, hi = scene.bounds()
    except Exception:  # noqa: BLE001 — a stub scene in tests
        return default
    if lo is None:
        return default
    a, b = _xyz(lo), _xyz(hi)
    diag = math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
    if diag <= 0:
        return default
    t = math.tan(math.radians(fov_deg) / 2.0)
    return (diag / 2.0) / max(t, 1e-6) * 1.15


def frame_page_projector(frame: "MarcoVista", camera):
    """``(cx, cy, cz) -> (px, py)``: a point in CAMERA space (metres — x
    right, y up, z depth away from the eye, as ``core.hlr._to_cam`` gives
    it) to FRAME-LOCAL page millimetres, for the very camera that rendered
    the frame. Scalars or NumPy arrays alike.

    Parallel frames keep their exact-scale arithmetic untouched (the scale
    IS the contract); a perspective frame divides by depth, which is the
    whole difference between an axonometric and standing there. Points at
    or behind the eye have no projection: they are pushed a bounded way off
    the page instead of to infinity, so a polyline crossing the eye plane
    still leaves the frame in the right direction rather than drawing a
    line to the next galaxy."""
    import numpy as np

    ar = frame.w_mm / frame.h_mm if frame.h_mm else 1.0
    if not getattr(frame, "perspective", False):
        half_h = model_height_for_frame(frame.h_mm, frame.scale_n) / 2.0
        half_w = half_h * ar
        k = frame.h_mm / (2.0 * half_h) if half_h else 0.0

        def to_page(cx, cy, cz=None):
            return ((cx + half_w) * k, (half_h - cy) * k)
        return to_page

    t = math.tan(math.radians(getattr(camera, "fov_deg", 45.0)) / 2.0)
    lim_x, lim_y = 10.0 * frame.w_mm, 10.0 * frame.h_mm

    def to_page(cx, cy, cz=None):
        if cz is None:                       # depth-less call: cannot divide
            raise ValueError("a perspective frame projects with the depth")
        hh = t * np.maximum(np.asarray(cz, dtype=float), 1e-4)
        px = (np.asarray(cx, dtype=float) / (hh * ar) + 1.0) * frame.w_mm / 2.0
        py = (1.0 - np.asarray(cy, dtype=float) / hh) * frame.h_mm / 2.0
        px = np.clip(px, -lim_x, lim_x + frame.w_mm)
        py = np.clip(py, -lim_y, lim_y + frame.h_mm)
        if np.isscalar(cz) or np.ndim(cz) == 0:
            return (float(px), float(py))
        return (px, py)
    return to_page


#: The style a NEW model view is born with: the Architectural preset —
#: white background, no sky, edges and profiles, the look of a plan sheet
#: (Marco, 2026-09-07: «el model view, cuando se abre por defecto el
#: compositor, que sea el estilo de arquitectura»). A frame's style stays
#: whatever the document saved; this only decides the starting point of a
#: frame the user has not styled yet.
NEW_FRAME_STYLE = "style:Architectural"


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
    #: Render style: "sombreado" (the model's ACTIVE display style),
    #: "style:<name>" (a core.style built-in preset — Hidden line,
    #: Architectural, ... — per frame, like LayOut viewports),
    #: "vectorial" (exact HLR vector pass), or the legacy "tecnico" /
    #: "lineas" (kept for old documents; the UI maps them onto the
    #: Hidden line / Wireframe presets).
    style: str = "sombreado"
    #: Paper background: render on white with no sky, whatever the style
    #: says (Marco, 2026-09-08, the rebar in X-ray: «no me gusta que tenga
    #: el fondo gris del model»). Off = the style's own background.
    paper_bg: bool = False
    #: Draw the view title under the frame («Planta — 1:100»).
    show_title: bool = False
    #: How the title reads. "layout": LayOut's label — numbered bubble +
    #: title + «ESC. 1:N» over a rule; "bar": a vertical strip at the
    #: frame's left with title / subtitle / scale turned 90° (the habit of
    #: Brazilian offices' plans); "simple": the historic centred line.
    #: ``title_text`` empty = the view's name; fields ({escala}, {lamina},
    #: {escena}…) expand in every text.
    title_style: str = "layout"
    title_text: str = ""
    title_subtitle: str = ""
    title_number: str = ""            # the bubble's number; "" = no bubble
    title_sheet: str = ""             # the bubble's lower half («A101», {lamina})
    title_scale: bool = True          # append «ESC. 1:N»
    title_align: str = "left"         # left | center | right
    title_pos: str = "below"          # below | above (not for the bar)
    title_mm: float = 4.0             # text height on paper
    #: Coordinate-grid spacing over the view, in model METRES (0 = off) —
    #: QGIS's graticule, the civil habit of gridded plans.
    grid_m: float = 0.0
    #: Stable identity for anchored dimensions ("" until a cota anchors to
    #: this frame — then a uuid4 hex that survives save/load and reorders).
    uid: str = ""
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False
    #: In-place view edits (LayOut: double-click the viewport, then pan /
    #: orbit / zoom). ``None`` = whatever the view or scene provides.
    cam_target: Optional[list] = None      # world point the camera centres on
    cam_yaw: Optional[float] = None        # radians, overrides the view's
    cam_pitch: Optional[float] = None
    #: PERSPECTIVE frame (LayOut's viewport switch): the view renders with a
    #: real vanishing point instead of the parallel projection every other
    #: frame uses — the 3D «como si lo viera en campo» that an axonometric
    #: never gives (Marco, 2026-09-17). Off by default and never inherited
    #: from the bound scene: a sheet made before this existed must open
    #: drawing exactly what it drew, and half the scenes of a model are
    #: saved in perspective from modelling. A perspective frame has NO
    #: scale (its size on paper depends on depth), so the scale box, the
    #: scale label and anchored dimensions step aside for it.
    perspective: bool = False
    #: Eye distance to the camera target, in metres, and the field of view
    #: in degrees — the perspective frame's «zoom». ``None`` = whatever the
    #: bound scene carries, or a fit to the model when there is no scene.
    cam_distance: Optional[float] = None
    cam_fov: Optional[float] = None
    #: Sun shadows in THIS frame: ``None`` = whatever the bound scene (or
    #: the live model) says, True / False force them for the frame alone —
    #: the field 3D wants the sun on while the plan beside it does not.
    #: ``sun_hour`` (local decimal hour, 0–24) overrides the model's time
    #: of day so one sheet can raking-light a view without moving the
    #: model's own sun. ``None`` = the model's hour.
    shadows: Optional[bool] = None
    sun_hour: Optional[float] = None
    #: Turn of the DRAWING inside the frame, in degrees CLOCKWISE on paper
    #: (the north arrow's and QPainter's convention) — the frame, its title
    #: and the sheet stay put while the model spins, so a plan sits straight
    #: on the sheet without touching the model. It is a roll of the frame's
    #: camera, so every derived thing (the render, the vector pass, snap
    #: points, anchored cotas, section marks, the DXF) turns with it.
    rot_deg: float = 0.0
    #: Draw the model's own dimensions and leader texts in the frame
    #: (LayOut shows SketchUp's). Opt-in per frame; their layers decide
    #: per scene which ones.
    annotations: bool = False
    annot_text_mm: float = 2.8             # their text height on paper
    #: Section marks: the trace of every section plane of the model that
    #: cuts across this view, drawn as the cut line with arrows toward the
    #: side the section looks at and the plane's letter in bubbles — the
    #: plan says where «Corte A-A» was taken. Opt-in per frame.
    section_marks: bool = False
    #: Chainage marks along the traced georef paths in the frame: a tick
    #: and a «0+020» label every ``km_step_m`` metres of horizontal length
    #: — the profile's chainage, so plan and profile agree. 0 = the round
    #: step the profile picks on its own for that path.
    km_marks: bool = False
    km_step_m: float = 0.0
    #: Printed border of the frame. Off by default: on screen the canvas
    #: still shows a light guide, on paper the view sits borderless (the
    #: sheet's own border is a Composicion setting).
    border: bool = False
    border_mm: float = 0.3
    border_color: str = "#282e36"
    #: Pens of the vector style, in paper mm — the three weights that make
    #: a drawing read as a plan: the section cut, the profiles (SketchUp's:
    #: silhouettes and outlines against the background) and the plain
    #: edges between two faces. ``profiles`` off draws every edge thin.
    pen_cut_mm: float = 0.5
    pen_profile_mm: float = 0.35
    pen_edge_mm: float = 0.18
    profiles: bool = True
    #: Hidden edges inked thin and dashed (issue #81) — the standard of a
    #: technical drawing; off by default, as a view shows what is seen.
    hidden_lines: bool = False
    #: Poché of the vector style where the section plane slices a solid:
    #: "solid" | "hatch" (45° lines every ``cut_hatch_mm``) | "none".
    cut_fill: str = "solid"
    cut_fill_color: str = "#595e69"
    cut_hatch_mm: float = 1.5
    #: Scale label of the frame ("ESC. 1:40"): follows the scale, sits
    #: under or inside the frame; ``{n}`` in the text is the scale number.
    show_scale: bool = False
    scale_text: str = "ESC. 1:{n}"
    scale_pos: str = "under-right"   # under-left | under-right |
                                     # inside-bl | inside-br
    scale_mm: float = 3.0

    def scale_label(self) -> str:
        if getattr(self, "perspective", False):
            return _tr("NO SCALE")
        shown = format_scale(self.scale_n)
        try:
            template = self.scale_text or "ESC. 1:{n}"
            # «1:{n}» is the old template and means «the scale»; an
            # enlargement has to come out as 10:1, not 1:0.1.
            if "1:{n}" in template:
                return template.replace("1:{n}", shown)
            return template.replace("{n}", f"{self.scale_n:g}")
        except Exception:  # noqa: BLE001 — a broken template still labels
            return shown

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
    italic: bool = False
    underline: bool = False
    family: str = "Sans Serif"
    color: str = "#1e242c"
    align: str = "left"          # left | center | right
    bg_color: str = ""           # "" = no background; else a fill behind the block
    bg_opacity: float = 1.0      # 0..1 of the background fill
    #: Bound to a frame (its uid): {escala} / {escena} read THAT frame, and
    #: the block moves along when the frame moves (a movable scale label).
    frame_uid: str = ""
    follow: bool = True
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False


@dataclass
class ImagenItem:
    """An image (logo, photo) on the sheet. The file is referenced by path;
    the .igz stores the path, not the pixels (same policy as textures)."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 60.0
    h_mm: float = 40.0
    path: str = ""
    #: Presentation (Marco, 2026-09-05: «poder poner transparencia… mostrar
    #: en círculo o algo así con bordes que se desvanezcan»): overall
    #: opacity, the cut-out shape, its corner radius, a feathered edge
    #: (mm of fade inward from the outline) and how the picture fills the
    #: box — stretched, cropped to cover it, or letterboxed inside it.
    opacity: float = 1.0
    shape: str = "rect"          # rect | rounded | ellipse
    radius_mm: float = 4.0       # rounded corners
    feather_mm: float = 0.0      # 0 = a hard edge
    fit: str = "stretch"         # stretch | cover | contain
    border: bool = False
    border_mm: float = 0.3
    border_color: str = "#282e36"
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False


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
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False
    #: The EDITABLE rows: [label, value] pairs, in drawing order. Filled
    #: from the legacy fixed attributes on load when absent (old docs);
    #: all edits and painting go through this list.
    campos: list = field(default_factory=list)
    #: Lay the rows out in N side-by-side column groups (each with its own
    #: label/value pair of sub-columns) — wide title blocks read that way.
    columns: int = 1
    border_mm: float = 0.5       # outer border line width
    line_mm: float = 0.2         # inner grid line width
    #: The look (see ``CAJETIN_DESIGNS`` for the presets the panel offers):
    corner: str = "square"       # square | rounded | chamfer
    radius_mm: float = 3.0       # for rounded / chamfered corners
    layout: str = "grid"         # grid | banded | minimal
    double_border: bool = False  # a light second outline inside the heavy one
    fill_color: str = ""         # label column / header band fill ("" = none)
    label_color: str = "#5a626c"
    text_color: str = "#1e242c"
    line_color: str = "#1e242c"
    label_mm: float = 0.0        # label sub-column width; 0 = automatic

    #: Look-only fields — what a design preset sets and copy/paste style
    #: carries; never the rows, the size or the place on the page.
    LOOK_FIELDS = ("corner", "radius_mm", "layout", "double_border",
                   "fill_color", "label_color", "text_color", "line_color",
                   "label_mm", "border_mm", "line_mm")

    #: (label, field-name) legacy rows — the pre-editable schema, kept to
    #: migrate old documents into ``campos``.
    FIELDS = (("PROYECTO", "proyecto"), ("AUTOR", "autor"),
              ("FECHA", "fecha"), ("ESCALA", "escala"),
              ("LÁMINA", "lamina"))

    def __post_init__(self) -> None:
        if not self.campos:
            self.campos = [[label, getattr(self, attr)]
                           for label, attr in self.FIELDS]

    def set_field(self, label: str, value: str) -> None:
        """Set the first row whose label matches (case-insensitive); add
        the row if the title block does not have it yet."""
        for row in self.campos:
            if str(row[0]).strip().upper() == label.strip().upper():
                row[1] = value
                return
        self.campos.append([label, value])

    def look(self) -> dict:
        return {k: getattr(self, k) for k in self.LOOK_FIELDS}

    def design_key(self) -> str:
        """The preset this look matches, or "" when it is the user's own."""
        mine = self.look()
        for key, _label, fields in CAJETIN_DESIGNS:
            base = dict(CAJETIN_DESIGN_BASE)
            base.update(fields)
            if all(_same(mine[k], v) for k, v in base.items()):
                return key
        return ""

    def template_dict(self) -> dict:
        """What a saved title-block template carries: rows, size and look
        — not where it sits on the page."""
        from dataclasses import asdict
        d = asdict(self)
        for k in ("x_mm", "y_mm", "z", "locked", "group_id",
                  "proyecto", "autor", "fecha", "escala", "lamina"):
            d.pop(k, None)
        return d


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except (TypeError, ValueError):
            return False
    return a == b


#: The look every design starts from; a preset overrides some of it.
CAJETIN_DESIGN_BASE = {
    "corner": "square", "radius_mm": 3.0, "layout": "grid",
    "double_border": False, "fill_color": "", "label_color": "#5a626c",
    "text_color": "#1e242c", "line_color": "#1e242c", "label_mm": 0.0,
    "border_mm": 0.5, "line_mm": 0.2,
}

#: Built-in title-block designs: (key, label for tr(), look overrides).
CAJETIN_DESIGNS = (
    ("classic", "Classic", {}),
    ("rounded", "Rounded corners", {"corner": "rounded", "radius_mm": 3.0}),
    ("chamfer", "Chamfered corners", {"corner": "chamfer", "radius_mm": 2.5}),
    ("shaded", "Shaded labels", {"fill_color": "#e9ecf0"}),
    ("banded", "Header band", {"layout": "banded", "fill_color": "#dfe4ea",
                               "label_color": "#40474f"}),
    ("minimal", "Minimal", {"layout": "minimal", "corner": "rounded",
                            "radius_mm": 2.0, "line_mm": 0.15,
                            "label_color": "#7a828c"}),
    ("double", "Double border", {"double_border": True, "border_mm": 0.7,
                                 "corner": "chamfer", "radius_mm": 3.0}),
)


@dataclass
class BarraEscala:
    """A graphic scale bar: alternating black/white segments with metre
    labels — the reader can measure even from a bad photocopy."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    scale_n: float = 100.0
    segments: int = 4
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

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
class FlechaNorte:
    """A north arrow: circle, needle and N, rotatable to the project north.

    The N rides the needle's tip, outside the circle, and turns with the
    needle (Marco, 2026-09-20). It used to sit at the middle, on top of
    the black-and-white needle, which is what Rafael saw — «la N de norte
    quizás por aquí arriba estaría mejor, porque ahí se ve mal» (33:20);
    then in a band above the compass, which did not turn. Keeping the
    middle as an option was a bad idea of mine: rendered side by side,
    the needle simply swallows the letter (Marco, 2026-09-19). There is
    one north arrow, and it reads.
    """

    x_mm: float = 20.0
    y_mm: float = 20.0
    size_mm: float = 18.0
    angle_deg: float = 0.0
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    @property
    def w_mm(self) -> float:
        return self.size_mm

    @property
    def h_mm(self) -> float:
        return self.size_mm


@dataclass
class PerfilTerreno:
    """A longitudinal terrain profile on the sheet: the ground elevation
    under a traced path (``Scene.geo_paths``) against chainage, the way a
    road or canal plan shows it — a horizontal scale, a vertical
    exaggeration, a grid and chainage labels. The elevations are sampled at
    paint time from the survey or the DEM (``ComposerWindow.profile_for``);
    the sheet stores only what to plot and how."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 180.0
    h_mm: float = 70.0
    path_index: int = 0          # which of Scene.geo_paths
    scale_n: float = 0.0         # horizontal 1:N; 0 = fit the path to the width
    exag: float = 0.0            # vertical exaggeration; 0 = fit the relief to the height
    grid: bool = True
    grid_h_m: float = 0.0        # chainage grid step (m); 0 = automatic
    grid_v_m: float = 0.0        # elevation grid step (m); 0 = automatic
    fill: bool = True            # tint the ground under the line
    title: str = ""              # "" = "Longitudinal profile — <path>"
    text_mm: float = 2.4
    spacing_m: float = 0.0       # sampling step (m); 0 = automatic
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False


@dataclass
class Leyenda:
    """A legend box: title + one row per model layer (snapshotted when
    added / refreshed, so the sheet stays stable if layers change)."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 55.0
    title: str = "LEYENDA"
    rows: list = field(default_factory=list)
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    @property
    def h_mm(self) -> float:
        return 7.5 + 5.5 * max(len(self.rows), 1)


@dataclass
class FormaItem:
    """A drawing shape: line, arrow, rectangle or ellipse. Lines/arrows run
    corner to corner of the box (``invert`` flips which diagonal)."""

    kind: str = "rect"           # linea | flecha | rect | elipse | poligono | terreno
    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 40.0
    h_mm: float = 25.0
    stroke_mm: float = 0.35
    fill: bool = False
    invert: bool = False
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False
    radius_mm: float = 0.0       # rect: corner rounding radius
    sides: int = 6               # poligono: number of sides (3..24)
    color: str = "#1e242c"       # stroke colour
    fill_color: str = "#e2e8ee"  # fill colour (when fill is on)
    # terreno — the ground line of an elevation, drawn like ``linea`` with
    # the drafting convention under it (Marco, 2026-09-08, the Yanque arch:
    # «de esta línea para abajo es el terreno»): ``ticks`` = short 45°
    # strokes hanging from the line, ``hatch`` = a hatched band, ``band``
    # = a filled translucent band. ``invert`` picks the diagonal, like a
    # line; the ground is always UNDER the line (positive page y).
    ground: str = "ticks"        # ticks | hatch | band
    tick_mm: float = 2.5         # stroke length (ticks / hatch band depth)
    tick_step_mm: float = 3.0    # spacing along the line
    band_mm: float = 6.0         # band depth (hatch / band)


@dataclass(eq=False)
class EtiquetaItem:
    """A label with a leader (LayOut's Label, SketchUp's leader text): a
    text block on the page and a leader line to the point it names, with
    an arrow head there. The point may anchor to model geometry of a
    frame and then follows the model like a cota."""

    x_mm: float = 0.0            # text block, page mm
    y_mm: float = 0.0
    w_mm: float = 50.0
    ax_mm: float = -20.0         # the pointed-at spot, relative to the block
    ay_mm: float = 15.0
    text: str = "Texto"
    size_pt: float = 11.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str = "#1e242c"
    bg_color: str = ""
    bg_opacity: float = 1.0
    arrow: bool = True
    #: A dot where the leader leaves the words (LayOut's label leader,
    #: AutoCAD's landing dot) — Marco, 2026-09-14: «el inicio de la línea
    #: donde está el texto debería ser un punto».
    dot: bool = True
    stroke_mm: float = 0.25
    anchor_uid: str = ""         # frame whose geometry the point sits on
    a_world: Optional[list] = None
    #: Further pointed-at spots for the SAME words (AutoCAD's multileader:
    #: «BUZÓN» with an arrow to each of three manholes). Each is a dict
    #: ``{"ax_mm", "ay_mm", "anchor_uid", "a_world"}`` relative to the
    #: block, exactly like the first spot above (Marco, 2026-09-14).
    leaders: list = field(default_factory=list)
    uid: str = ""
    z: float = 0.0
    locked: bool = False
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    @property
    def anchored(self) -> bool:
        return bool(self.anchor_uid and self.a_world)

    @property
    def h_mm(self) -> float:
        size_mm = self.size_pt * PT_TO_MM
        return max(6.0, size_mm * 1.4 * (self.text.count("\n") + 1))

    # ---- Every pointed-at spot, the first one included ----------------------
    def spots(self) -> list:
        """``[(ax_mm, ay_mm), …]`` — the first spot then the extra leaders."""
        out = [(float(self.ax_mm), float(self.ay_mm))]
        for ld in self.leaders or []:
            out.append((float(ld.get("ax_mm", 0.0)), float(ld.get("ay_mm", 0.0))))
        return out

    def add_leader(self, ax_mm: float, ay_mm: float, anchor_uid: str = "",
                   a_world=None) -> dict:
        ld = {"ax_mm": float(ax_mm), "ay_mm": float(ay_mm),
              "anchor_uid": anchor_uid or "",
              "a_world": list(a_world) if a_world else None}
        self.leaders = list(self.leaders or []) + [ld]
        return ld


@dataclass(eq=False)
class NivelItem:
    """A level mark (cota de nivel): the elevation of a point of the model
    written as «N.P.T. +0.15» beside the symbol — an open triangle on its
    apex for sections and elevations, a quartered circle for plans — with
    the level line running from it. Anchored to a frame's geometry it reads
    the point's Z (minus the project datum) and follows the model like a
    cota; free, it shows the typed level."""

    x_mm: float = 0.0            # the symbol's apex on the page
    y_mm: float = 0.0
    ax_mm: float = 0.0           # the model point, relative to the apex
    ay_mm: float = 0.0           # (a thin leader joins them when apart)
    symbol: str = "triangle"     # triangle | circle
    text: str = "N.P.T. {z}"     # {z} = the signed level
    z_m: float = 0.0             # the level when free (metres)
    datum_m: float = 0.0         # the project's ±0.00, in model metres
    decimals: int = 2
    size_mm: float = 2.5         # text height
    line_mm: float = 14.0        # the level line from the apex
    mirror: bool = False         # line and text to the LEFT of the symbol
    stroke_mm: float = 0.25
    color: str = "#1e242c"
    anchor_uid: str = ""         # frame whose geometry the point sits on
    a_world: Optional[list] = None
    uid: str = ""
    z: float = 0.0
    locked: bool = False
    group_id: str = ""           # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    @property
    def anchored(self) -> bool:
        return bool(self.anchor_uid and self.a_world)

    def level_m(self) -> float:
        """The level shown: the anchored point's Z or the typed one, less
        the datum."""
        z = (float(self.a_world[2]) if self.anchored and len(self.a_world) > 2
             else float(self.z_m))
        return z - float(self.datum_m)

    def value_text(self) -> str:
        """«+0.15», «-0.30», «±0.00» (zero at the shown precision)."""
        d = max(0, int(self.decimals))
        v = self.level_m()
        if round(v, d) == 0:
            return "±" + f"{0.0:.{d}f}"
        return f"{v:+.{d}f}"

    def label(self) -> str:
        text = self.text or "{z}"
        if "{z}" not in text:
            text = text.rstrip() + " {z}"
        return text.replace("{z}", self.value_text())

    @property
    def symbol_mm(self) -> float:
        return max(1.5, self.size_mm * 1.2)


@dataclass(eq=False)
class LlamadaItem:
    """A detail callout: a dashed box (or circle) around the part of a
    view that another drawing enlarges, a leader, and the bubble that
    names that drawing — «3» over «L-05». Bound to the frame it sits on,
    it moves along with it."""

    x_mm: float = 20.0           # the box on the page
    y_mm: float = 20.0
    w_mm: float = 30.0
    h_mm: float = 20.0
    shape: str = "rect"          # rect | circle
    number: str = "1"            # the detail's number (bubble, upper half)
    sheet: str = "{lamina}"      # the sheet it is drawn on (lower half)
    bx_mm: float = 36.0          # bubble centre, relative to the box
    by_mm: float = -6.0
    size_mm: float = 3.0         # bubble text height
    stroke_mm: float = 0.3
    color: str = "#1e242c"
    frame_uid: str = ""          # the frame it was drawn on
    follow: bool = True          # …moves with it
    uid: str = ""
    z: float = 0.0
    locked: bool = False
    group_id: str = ""           # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    @property
    def bubble_mm(self) -> float:
        return max(3.0, self.size_mm * 2.4)


@dataclass(eq=False)
class CotaAngularItem:
    """A sheet angular dimension (LayOut's Angular Dimension tool): a vertex
    on the page, two rays to the measured points, and an arc of
    ``radius_mm`` between them carrying the angle label."""

    x_mm: float = 0.0            # vertex, page mm
    y_mm: float = 0.0
    ax_mm: float = 30.0          # first ray point, relative to the vertex
    ay_mm: float = 0.0
    bx_mm: float = 0.0           # second ray point, relative to the vertex
    by_mm: float = -30.0
    radius_mm: float = 15.0      # the arc's radius
    offset_mm: float = 0.8       # label gap outside the arc
    text: str = ""               # "" = automatic angle; <> = the value
    text_mm: float = 2.8
    decimals: int = 1
    ends: str = "arrow"          # arrow | tick | none
    stroke_mm: float = 0.25
    color: str = "#1e242c"
    text_color: str = ""         # "" = the line colour
    text_bg: str = ""            # "" = no background behind the label
    text_bg_opacity: float = 1.0
    uid: str = ""
    z: float = 0.0
    locked: bool = False
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    def angles(self) -> tuple[float, float]:
        """``(start, sweep)`` in radians, page coordinates (y down): the
        arc runs from the first ray to the second the SHORT way round."""
        a0 = math.atan2(self.ay_mm, self.ax_mm)
        a1 = math.atan2(self.by_mm, self.bx_mm)
        sweep = a1 - a0
        while sweep > math.pi:
            sweep -= 2 * math.pi
        while sweep <= -math.pi:
            sweep += 2 * math.pi
        return a0, sweep

    def angle_deg(self) -> float:
        return abs(math.degrees(self.angles()[1]))

    def auto_label(self) -> str:
        n = max(0, min(int(self.decimals), 4))
        return f"{self.angle_deg():.{n}f}°"

    def label(self) -> str:
        if self.text:
            return self.text.replace("<>", self.auto_label())
        return self.auto_label()

    @property
    def w_mm(self) -> float:
        return max(abs(self.ax_mm), abs(self.bx_mm), self.radius_mm, 2.0)

    @property
    def h_mm(self) -> float:
        return max(abs(self.ay_mm), abs(self.by_mm), self.radius_mm, 2.0)


def cota_line_deg(ct) -> float:
    """The legible rotation of a cota's text: the angle of its DIMENSION
    LINE, not of the segment it measures — a cota forced horizontal reads
    horizontal however slanted the two points are."""
    (ax, ay), (bx, by) = ct.line_points()
    return readable_deg(bx - ax, by - ay)


def readable_deg(dx_mm: float, dy_mm: float) -> float:
    """The rotation a dimension's TEXT takes so it is read, not deciphered.

    ISO 129: dimension text is read from the bottom and from the right of
    the sheet — you tilt your head to the LEFT, never to the right. It is
    the rule Rafael repeats most in his video (09:00, 10:00), and it is
    circular: it holds at every inclination, not just the vertical.

    On the page Y grows downward, so the legible half-turn is
    **[-90°, 90°)** — a vertical dimension's text runs bottom-to-top
    whichever way the line happened to be drawn.

    It used to be written out at five call sites in two contradictory
    spellings: three tested ``deg > 90 or deg < -90``, which let the exact
    +90° of a cota drawn DOWNWARD through, and two tested ``deg <= -90``,
    which turned every vertical the wrong way round — that second pair is
    what projected the MODEL's dimensions onto a sheet, so those always
    read head-to-the-right.
    """
    deg = math.degrees(math.atan2(dy_mm, dx_mm))
    return (deg + 90.0) % 180.0 - 90.0


@dataclass
class CotaItem:
    """A sheet dimension between two measured points; the label is the REAL
    model distance implied by the paper length at 1:N («3.45 m»).

    LayOut-style: the dimension LINE runs parallel to the measured segment,
    ``sep_mm`` away along its normal (0 = directly on the points, the pre-C5
    look), with extension lines connecting it back to the measured points.
    """

    x_mm: float = 20.0
    y_mm: float = 20.0
    dx_mm: float = 40.0
    dy_mm: float = 0.0
    scale_n: float = 100.0
    sep_mm: float = 0.0          # dimension line ⟂ offset from the points
    offset_mm: float = 4.0       # label gap above the dimension line
    text: str = ""               # "" = automatic distance label
    text_mm: float = 2.8         # label height on paper
    decimals: int = 2
    units: str = "m"            # m | cm | mm | in | ft | ft-in | in-frac | ft-in-frac
    ends: str = "tick"           # tick | arrow | none
    stroke_mm: float = 0.25
    color: str = "#1e242c"
    #: Label style (LayOut's dimension text options): where the label sits
    #: relative to the dimension line, whether it follows the line or stays
    #: horizontal, and its own colour ("" = the line colour).
    text_pos: str = "above"      # above | centered | below | aside | aside_below
    # Along the line: the label over the middle, or OUTSIDE the start /
    # end of the dimension line (AutoCAD's outside placement; Marco,
    # 2026-09-08: «al lado de la cota, ya sea derecho o izquierdo»).
    text_along: str = "middle"   # middle | start | end
    # LayOut: the text box is dragged freely by the mouse — this is that
    # drag, page mm from the automatic spot (0, 0 = automatic).
    text_dx_mm: float = 0.0
    text_dy_mm: float = 0.0
    text_align: str = "aligned"  # aligned | horizontal
    text_color: str = ""
    text_bg: str = ""            # "" = no background behind the label
    text_bg_opacity: float = 1.0
    #: Model anchoring: when both points snapped to geometry of one frame,
    #: the cota remembers WHICH frame (its uid) and the two 3D points in
    #: model metres; the composer reprojects it whenever the frame or the
    #: model changes. The label is the distance PROJECTED on the frame's
    #: view plane (LayOut): on an elevation the fountain's top and the
    #: slab's front edge read 2.40 m tall, not the 3.87 m diagonal between
    #: two points 3 m apart in depth (Marco, 2026-09-02). "" / None = a
    #: free paper dimension (the pre-anchor behaviour).
    anchor_uid: str = ""
    a_world: Optional[list] = None
    b_world: Optional[list] = None
    #: Direction of the dimension LINE. ``""`` measures the segment
    #: itself, the way LayOut and SketchUp do (AutoCAD calls it DIMALIGNED);
    #: ``"h"`` / ``"v"`` measure only the horizontal or vertical part of it
    #: and draw the line straight, with extension lines of DIFFERENT
    #: lengths reaching each real point (AutoCAD's DIMLINEAR).
    #:
    #: It is what Rafael could not do (41:30–43:00): «si el punto a acotar
    #: no está perfectamente alineado con el otro… ¿veis cómo queda la cota
    #: inclinada? La cota no puede quedar inclinada si estás acotando algo
    #: en vertical». Forcing the second POINT onto an axis, which is what
    #: Shift used to do, loses the snap to the point he actually wants and
    #: leaves the measurement to the eye — «software técnico: a ojo no».
    axis: str = ""               # "" aligned | h | v
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    @property
    def anchored(self) -> bool:
        return bool(self.anchor_uid and self.a_world and self.b_world)

    @property
    def w_mm(self) -> float:
        return max(abs(self.dx_mm), 2.0)

    @property
    def h_mm(self) -> float:
        return max(abs(self.dy_mm), 2.0)

    def normal(self) -> tuple[float, float]:
        """Unit normal of the measured segment (the ``sep_mm`` direction)."""
        length = math.hypot(self.dx_mm, self.dy_mm)
        if length < 1e-9:
            return (0.0, -1.0)
        return (-self.dy_mm / length, self.dx_mm / length)

    def line_points(self) -> tuple[tuple, tuple]:
        """The DIMENSION LINE's two ends, in item space (origin = the first
        measured point). Aligned: the segment itself pushed ``sep_mm`` along
        its normal. Forced horizontal or vertical: a straight line at
        ``sep_mm``, spanning only the part of the segment it measures."""
        if self.axis == "h":
            return (0.0, self.sep_mm), (self.dx_mm, self.sep_mm)
        if self.axis == "v":
            return (self.sep_mm, 0.0), (self.sep_mm, self.dy_mm)
        nx, ny = self.normal()
        s = self.sep_mm
        return (nx * s, ny * s), (self.dx_mm + nx * s, self.dy_mm + ny * s)

    def label_extent_mm(self) -> float:
        """How much room the words take ALONG the dimension line — their
        width when they follow it, the shadow of their box when they are
        kept horizontal on a slanted or vertical cota."""
        tw = len(self.label()) * self.text_mm * 0.62 + 2.0
        if (getattr(self, "text_align", "aligned") or "aligned") != "horizontal":
            return tw
        d = math.radians(cota_line_deg(self))
        th = self.text_mm * 1.3 + 0.8
        return tw * abs(math.cos(d)) + th * abs(math.sin(d))

    def text_tail(self):
        """Rule 4: when the words sit OUTSIDE an end, the dimension line
        runs on under them — «la línea de cota se prolonga hasta cubrir
        todo el texto; si el texto crece, la línea crece» (Rafael, 08:00).
        A line that stops short and leaves the number floating is also
        rule 6's «prohibido».

        Returns the EXTRA segment, in item space, or ``None`` when the
        words are over the line or the drafter has dragged them away by
        hand — then the line stays where he put it, as LayOut does.
        """
        along = getattr(self, "text_along", "middle") or "middle"
        if along not in ("start", "end"):
            return None
        if (abs(float(getattr(self, "text_dx_mm", 0.0) or 0.0)) > 1e-9
                or abs(float(getattr(self, "text_dy_mm", 0.0) or 0.0)) > 1e-9):
            return None
        (ax, ay), (bx, by) = self.line_points()
        dx, dy = bx - ax, by - ay
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            return None
        ux, uy = dx / ln, dy / ln
        reach = self.label_extent_mm() + 1.8
        if along == "start":
            return ((ax, ay), (ax - ux * reach, ay - uy * reach))
        return ((bx, by), (bx + ux * reach, by + uy * reach))

    def measured_mm(self) -> float:
        """Paper length the label reports: the whole segment, or only its
        horizontal / vertical part when the cota is forced straight."""
        if self.axis == "h":
            return abs(self.dx_mm)
        if self.axis == "v":
            return abs(self.dy_mm)
        return math.hypot(self.dx_mm, self.dy_mm)

    def real_distance_m(self) -> float:
        """Paper length at the cota's scale — for an anchored cota that is
        the distance projected on its frame's view plane, since the
        composer reprojects its endpoints from the model."""
        return self.measured_mm() * self.scale_n / 1000.0

    def auto_label(self) -> str:
        """The measured value, formatted in the cota's units (metres by
        default; inches, feet, feet-and-inches, fractional inches too)."""
        from core.units import format_length
        d = self.real_distance_m()
        n = max(0, min(int(self.decimals), 6))
        units = getattr(self, "units", "m") or "m"
        if units == "m" and d >= 1000:
            return f"{d / 1000:.3f} km"
        return format_length(d, units, n)

    def label(self) -> str:
        """Custom text when set — with ``<>`` standing for the measured
        value (LayOut / SketchUp) — else the measurement itself."""
        if self.text:
            return self.text.replace("<>", self.auto_label())
        return self.auto_label()


@dataclass
class CotaRadialItem:
    """A radius or diameter dimension (AutoCAD's DIMRADIUS / DIMDIAMETER).

    Rafael asked for the radius after we shipped Fillet — «ya que pusisteis
    el redondeo, pues sería lo suyo» (revisión 2, 42:40) — and his video on
    drafting standards adds the diameter and the rules both obey, drawn
    case by case on his AutoCAD reference sheet (`rafael-cotas/f1230.jpg`):

    * the line ALWAYS reaches the centre — a radius starts there (rule 12)
      and a diameter passes through it (rule 8); a leader that stops short
      of the centre is out of standard (rule 15);
    * the symbol goes with the value, ``R`` or ``Ø`` (rules 8, 12);
    * the text sits ABOVE the line, and changing quadrant must not leave it
      upside down (rule 13) — that falls out of :func:`readable_deg`;
    * it all fits inside → inside, arrows pointing outward at the arc
      (rule 9); it does not → the line is prolonged outside and the arrows
      point back AT the centre (rules 10, 14, 15);
    * an arc is dimensioned exactly like a circle (rule 16).
    """

    x_mm: float = 0.0            # the CENTRE, page mm
    y_mm: float = 0.0
    radius_mm: float = 15.0      # the circle's radius ON PAPER
    angle_deg: float = -30.0     # heading the dimension line leaves by
    kind: str = "radius"         # radius | diameter
    scale_n: float = 100.0
    text: str = ""               # "" = automatic; <> stands for the value
    text_mm: float = 2.8
    decimals: int = 2
    units: str = "m"
    offset_mm: float = 0.5       # line → text baseline gap
    ends: str = "arrow"          # arrow | tick | none
    stroke_mm: float = 0.25
    color: str = "#1e242c"
    text_color: str = ""
    text_bg: str = ""
    text_bg_opacity: float = 1.0
    #: ``auto`` decides by whether the words fit; ``in`` / ``out`` force it.
    placement: str = "auto"      # auto | in | out
    centre_mark: bool = True     # the little cross at the centre
    uid: str = ""
    z: float = 0.0
    locked: bool = False
    group_id: str = ""
    #: The name the user gave it in the Items list (issue #93); "" =
    #: the automatic one (its kind and what it shows).
    list_name: str = ""
    #: Hidden from the sheet — not drawn, not printed, not picked;
    #: shown again from the Items list's eye (QGIS; Marco, 26-09).
    hidden: bool = False

    @property
    def w_mm(self) -> float:
        return max(2.0 * self.radius_mm, 2.0)

    @property
    def h_mm(self) -> float:
        return max(2.0 * self.radius_mm, 2.0)

    def symbol(self) -> str:
        return "\u00d8" if self.kind == "diameter" else "R"

    def measured_mm(self) -> float:
        """Paper length of what the label reports."""
        r = abs(float(self.radius_mm))
        return 2.0 * r if self.kind == "diameter" else r

    def real_distance_m(self) -> float:
        return self.measured_mm() * self.scale_n / 1000.0

    def heading(self) -> tuple[float, float]:
        a = math.radians(self.angle_deg)
        return math.cos(a), math.sin(a)

    def line_points(self) -> tuple[tuple, tuple]:
        """The dimension LINE's two ends in item space (origin = centre): a
        radius runs from the centre out to the arc, a diameter right across
        it. Rule 15: neither ever stops short of the centre."""
        ux, uy = self.heading()
        r = float(self.radius_mm)
        if self.kind == "diameter":
            return (-ux * r, -uy * r), (ux * r, uy * r)
        return (0.0, 0.0), (ux * r, uy * r)

    def label_width_mm(self) -> float:
        return len(self.label()) * self.text_mm * 0.62 + 2.0

    def outside(self) -> bool:
        """Whether the words go beyond the arc. ``auto`` measures: they go
        inside while they fit on the line with a little air (rule 9), and
        out when they do not (rules 10, 14)."""
        if self.placement in ("in", "out"):
            return self.placement == "out"
        (ax, ay), (bx, by) = self.line_points()
        room = math.hypot(bx - ax, by - ay)
        arrow = max(1.8, self.stroke_mm * 6) * (
            2 if self.kind == "diameter" else 1)
        return self.label_width_mm() + arrow + 1.0 > room

    def text_anchor(self) -> tuple[float, float]:
        """Where the words sit, in item space: over the middle of the line
        when they fit, past its end when they do not.

        A DIAMETER's middle is the centre itself, and the centre belongs to
        the axes — «un número encima de un eje se lee mal, sobre todo la
        coma» (rule 3). So it rides the middle of the RIGHT-HAND half — the
        half the text reads towards — whichever way the line was drawn:
        Marco, 2026-09-20, «para el caso de diámetros deberá ir al costado
        derecho, no al medio, porque se cruzaría con otras líneas de dibujo
        que salen del radio». That is where the Ø41,96 of the reference
        sheet sits; a vertical diameter's right is its top, since its text
        reads bottom-to-top."""
        ux, uy = self.heading()
        if not self.outside():
            if self.kind == "diameter":
                d = math.radians(readable_deg(ux, uy))
                h = float(self.radius_mm) / 2.0
                return (math.cos(d) * h, math.sin(d) * h)
            (ax, ay), (bx, by) = self.line_points()
            return ((ax + bx) / 2.0, (ay + by) / 2.0)
        reach = float(self.radius_mm) + self.label_width_mm() / 2.0 + 2.0
        return (ux * reach, uy * reach)

    def tail_end(self) -> tuple[float, float]:
        """The far end of the line once it is prolonged to carry the words
        outside (rule 10: «la línea se prolonga»); the arc end otherwise."""
        ux, uy = self.heading()
        if not self.outside():
            return (ux * self.radius_mm, uy * self.radius_mm)
        reach = float(self.radius_mm) + self.label_width_mm() + 2.5
        return (ux * reach, uy * reach)

    def auto_label(self) -> str:
        from core.units import format_length
        d = self.real_distance_m()
        n = max(0, min(int(self.decimals), 6))
        units = getattr(self, "units", "m") or "m"
        if units == "m" and d >= 1000:
            return self.symbol() + f"{d / 1000:.3f} km"
        return self.symbol() + format_length(d, units, n)

    def label(self) -> str:
        if self.text:
            return self.text.replace("<>", self.auto_label())
        return self.auto_label()


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
    nortes: list = field(default_factory=list)
    leyendas: list = field(default_factory=list)
    shapes: list = field(default_factory=list)
    cotas: list = field(default_factory=list)
    cotas_ang: list = field(default_factory=list)
    cotas_rad: list = field(default_factory=list)
    etiquetas: list = field(default_factory=list)
    perfiles: list = field(default_factory=list)
    niveles: list = field(default_factory=list)
    llamadas: list = field(default_factory=list)
    cajetin: Optional[Cajetin] = None
    #: Sheet border drawn on the margin rectangle: width, colour, rounded
    #: corners and line type (single | double | dashed).
    border: bool = False
    border_mm: float = 0.5
    border_color: str = "#1e242c"
    border_radius_mm: float = 0.0
    border_style: str = "single"
    # QGIS's guides: vertical guides at these x (mm) and horizontal ones at
    # these y, dragged off the rulers; items snap to them (Marco,
    # 2026-09-08: «en QGIS muestran como unas guías… sería bueno
    # implementar eso en composición»).
    guides_v: list = field(default_factory=list)
    guides_h: list = field(default_factory=list)

    def page_size_mm(self) -> tuple[float, float]:
        w, h = PAPER_SIZES_MM[self.paper]
        return (h, w) if self.landscape else (w, h)

    def default_frame(self) -> MarcoVista:
        """A frame filling the page inside the margins (the C1 starter)."""
        pw, ph = self.page_size_mm()
        m = self.margin_mm
        return MarcoVista(x_mm=m, y_mm=m, w_mm=pw - 2 * m, h_mm=ph - 2 * m,
                          style=NEW_FRAME_STYLE)

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
               + list(self.scalebars) + list(self.nortes)
               + list(self.leyendas) + list(self.shapes) + list(self.cotas)
               + list(self.cotas_ang) + list(self.cotas_rad)
               + list(self.etiquetas)
               + list(self.perfiles) + list(self.niveles)
               + list(self.llamadas))
        if self.cajetin is not None:
            out.append(self.cajetin)
        return out

    # ---- Serialisation (.igz) -----------------------------------------------
    def to_dict(self) -> dict:
        from dataclasses import asdict
        d = {"name": self.name, "paper": self.paper,
             "landscape": self.landscape, "margin_mm": self.margin_mm,
             "frames": [asdict(f) for f in self.frames]}
        if self.border:
            d["border"] = {"on": True, "mm": self.border_mm,
                           "color": self.border_color,
                           "radius_mm": self.border_radius_mm,
                           "style": self.border_style}
        if self.texts:
            d["texts"] = [asdict(t) for t in self.texts]
        if self.images:
            d["images"] = [asdict(i) for i in self.images]
        if self.scalebars:
            d["scalebars"] = [asdict(sb) for sb in self.scalebars]
        for key, lst in (("nortes", self.nortes), ("leyendas", self.leyendas),
                         ("shapes", self.shapes), ("cotas", self.cotas),
                         ("cotas_ang", self.cotas_ang),
                         ("cotas_rad", self.cotas_rad),
                         ("etiquetas", self.etiquetas),
                         ("perfiles", self.perfiles),
                         ("niveles", self.niveles),
                         ("llamadas", self.llamadas)):
            if lst:
                d[key] = [asdict(it) for it in lst]
        if self.cajetin is not None:
            d["cajetin"] = asdict(self.cajetin)
        if self.guides_v or self.guides_h:
            d["guides"] = {"v": [float(x) for x in self.guides_v],
                           "h": [float(y) for y in self.guides_h]}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Composicion":
        """Rebuild a sheet from its .igz record. Keys this version does not
        know (a sheet saved by a newer IngeTrazo) are dropped, not fatal:
        the model must open whatever the sheets carry."""
        c = cls(name=d.get("name", "Lámina 1"),
                paper=d.get("paper", "A4"),
                landscape=bool(d.get("landscape", True)),
                margin_mm=float(d.get("margin_mm", 10.0)))
        b = d.get("border")
        if isinstance(b, dict) and b.get("on"):
            c.border = True
            c.border_mm = float(b.get("mm", 0.5))
            c.border_color = str(b.get("color", "#1e242c"))
            c.border_radius_mm = float(b.get("radius_mm", 0.0))
            c.border_style = str(b.get("style", "single"))
        c.frames = _items(MarcoVista, d.get("frames"))
        c.texts = _items(TextoItem, d.get("texts"))
        c.images = _items(ImagenItem, d.get("images"))
        c.scalebars = _items(BarraEscala, d.get("scalebars"))
        c.nortes = _items(FlechaNorte, d.get("nortes"))
        c.leyendas = _items(Leyenda, d.get("leyendas"))
        c.shapes = _items(FormaItem, d.get("shapes"))
        c.cotas_ang = _items(CotaAngularItem, d.get("cotas_ang"))
        c.cotas_rad = _items(CotaRadialItem, d.get("cotas_rad"))
        c.etiquetas = _items(EtiquetaItem, d.get("etiquetas"))
        c.perfiles = _items(PerfilTerreno, d.get("perfiles"))
        c.niveles = _items(NivelItem, d.get("niveles"))
        c.llamadas = _items(LlamadaItem, d.get("llamadas"))
        c.cotas = _items(CotaItem, d.get("cotas"))
        if isinstance(d.get("cajetin"), dict):
            c.cajetin = _build(Cajetin, d["cajetin"])
        g = d.get("guides")
        if isinstance(g, dict):
            c.guides_v = [float(x) for x in (g.get("v") or [])]
            c.guides_h = [float(y) for y in (g.get("h") or [])]
        _migrate_fixed_scale_labels(c)
        return c


def _build(kind, raw):
    """``kind(**raw)`` keeping only the fields *kind* declares — a record
    from a newer version loads with its extra keys ignored."""
    from dataclasses import fields
    known = {f.name for f in fields(kind)}
    return kind(**{k: v for k, v in raw.items() if k in known})


def _items(kind, raw_list) -> list:
    """The items of one kind from their records; anything that is not a
    record (a corrupt entry) is skipped."""
    if not isinstance(raw_list, list):
        return []
    return [_build(kind, r) for r in raw_list if isinstance(r, dict)]


def _migrate_fixed_scale_labels(c: "Composicion") -> None:
    """Sheets from before the movable scale label carried it as a FRAME flag
    (``show_scale`` + ``scale_text``/``scale_pos``/``scale_mm``), painted by
    the frame itself. The panel no longer exposes those, so a loaded sheet
    turns each one into a text block bound to its frame — same place, same
    size — that the user can move, restyle or delete like any other text."""
    import uuid
    zs = [getattr(it, "z", 0.0) for it in c.all_items()]
    z = (max(zs) + 1.0) if zs else 0.0
    for f in c.frames:
        if not getattr(f, "show_scale", False):
            continue
        f.show_scale = False
        if not f.uid:
            f.uid = uuid.uuid4().hex
        template = f.scale_text or "ESC. 1:{n}"
        text = template.replace("1:{n}", "{escala}").replace("{n}", "{escala}")
        size_mm = max(1.5, float(f.scale_mm or 3.0))
        size_pt = size_mm / PT_TO_MM
        pos = f.scale_pos or "under-right"
        w = 40.0
        h = size_mm * 1.4
        bg = ""
        if pos == "under-left":
            x, y, align = f.x_mm, f.y_mm + f.h_mm + 1.0, "left"
        elif pos == "inside-bl":
            x, y, align = f.x_mm + 1.0, f.y_mm + f.h_mm - h - 1.0, "left"
            bg = "#ffffff"
        elif pos == "inside-br":
            x, y, align = f.x_mm + f.w_mm - w - 1.0, f.y_mm + f.h_mm - h - 1.0, "right"
            bg = "#ffffff"
        else:  # under-right
            x, y, align = f.x_mm + f.w_mm - w, f.y_mm + f.h_mm + 1.0, "right"
        c.texts.append(TextoItem(
            x_mm=x, y_mm=y, w_mm=w, text=text, size_pt=size_pt, bold=True,
            align=align, bg_color=bg, bg_opacity=0.86 if bg else 1.0,
            frame_uid=f.uid, follow=True, z=z))
        z += 1.0


# ── Composer-scoped undo ────────────────────────────────────────────────────
#
# Sheet items are plain dataclasses, far from the mesh; the drawing History
# (core/history.py) snapshots the mesh transactionally, which would be pure
# overhead here. Same Command invariant, its own light stacks — the QGIS
# shape again (one undo stack per layout).

# ---- Dynamic fields ({proyecto}, {escala}, {fecha}…) ----------------------
#: What the sheet being drawn knows about itself; set by the composer
#: before painting a sheet (canvas or print), read by ``expand_fields``.
_FIELD_CTX: dict = {}


def set_field_context(comp=None, scene=None, path=None, index=None,
                      total=None) -> None:
    _FIELD_CTX.clear()
    _FIELD_CTX.update(comp=comp, scene=scene, path=path, index=index,
                      total=total)


def field_values(frame_uid: str = "") -> dict:
    """The values behind every ``{campo}`` a text or title block may use.
    ``frame_uid`` makes {escala}/{escena} read that frame instead of the
    sheet's main one (a text bound to a frame)."""
    import datetime
    from pathlib import Path
    comp = _FIELD_CTX.get("comp")
    path = _FIELD_CTX.get("path")
    caj = getattr(comp, "cajetin", None) if comp is not None else None
    frames = list(getattr(comp, "frames", []) or []) if comp is not None else []
    main = max(frames, key=lambda f: f.w_mm * f.h_mm) if frames else None
    if frame_uid:
        bound = next((f for f in frames if f.uid == frame_uid), None)
        if bound is not None:
            main = bound
    scene_name = ""
    for f in ([main] if main is not None else []) + frames:
        if f is not None and f.view_key.startswith("scene:"):
            scene_name = f.view_key[6:]          # the main frame's, else any
            break
    idx, total = _FIELD_CTX.get("index"), _FIELD_CTX.get("total")
    return {
        "proyecto": (getattr(caj, "proyecto", "") or "") if caj else "",
        "autor": (getattr(caj, "autor", "") or "") if caj else "",
        "lamina": ((getattr(caj, "lamina", "") or "") if caj else "")
                  or (comp.name if comp is not None else ""),
        "nombre": comp.name if comp is not None else "",
        "escala": format_scale(main.scale_n) if main is not None else "",
        "escena": scene_name,
        "fecha": datetime.date.today().strftime("%d/%m/%Y"),
        "archivo": Path(str(path)).stem if path else "",
        "hoja": str(idx + 1) if idx is not None else "",
        "total": str(total) if total else "",
    }


_FIELD_RE = None


def expand_fields(text, frame_uid: str = "") -> str:
    """Replace ``{proyecto}``, ``{lamina}``, ``{escala}``, ``{escena}``,
    ``{fecha}``, ``{archivo}``, ``{autor}``, ``{nombre}``, ``{hoja}`` and
    ``{total}`` with the sheet's live values (QGIS-style dynamic text).
    Unknown fields — the scale label's ``{n}`` included — stay as typed."""
    global _FIELD_RE
    if not text or "{" not in text:
        return text or ""
    import re
    if _FIELD_RE is None:
        _FIELD_RE = re.compile(r"\{([A-Za-z_]+)\}")
    vals = field_values(frame_uid)

    def rep(m):
        return vals.get(m.group(1).lower(), m.group(0))
    return _FIELD_RE.sub(rep, text)


class ComposerCommand:
    """Reversible operation against a Composicion."""

    def do(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def undo(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class CompoundCommand(ComposerCommand):
    """Several commands as ONE undo step (align, distribute, duplicate)."""

    def __init__(self, commands) -> None:
        self.commands = list(commands)

    def do(self) -> None:
        for c in self.commands:
            c.do()

    def undo(self) -> None:
        for c in reversed(self.commands):
            c.undo()


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
        if isinstance(self.item, FlechaNorte):
            return self.comp.nortes
        if isinstance(self.item, Leyenda):
            return self.comp.leyendas
        if isinstance(self.item, FormaItem):
            return self.comp.shapes
        if isinstance(self.item, CotaItem):
            return self.comp.cotas
        if isinstance(self.item, CotaAngularItem):
            return self.comp.cotas_ang
        if isinstance(self.item, CotaRadialItem):
            return self.comp.cotas_rad
        if isinstance(self.item, EtiquetaItem):
            return self.comp.etiquetas
        if isinstance(self.item, PerfilTerreno):
            return self.comp.perfiles
        if isinstance(self.item, NivelItem):
            return self.comp.niveles
        if isinstance(self.item, LlamadaItem):
            return self.comp.llamadas
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
        if isinstance(self.item, FlechaNorte):
            return self.comp.nortes
        if isinstance(self.item, Leyenda):
            return self.comp.leyendas
        if isinstance(self.item, FormaItem):
            return self.comp.shapes
        if isinstance(self.item, CotaItem):
            return self.comp.cotas
        if isinstance(self.item, CotaAngularItem):
            return self.comp.cotas_ang
        if isinstance(self.item, CotaRadialItem):
            return self.comp.cotas_rad
        if isinstance(self.item, EtiquetaItem):
            return self.comp.etiquetas
        if isinstance(self.item, PerfilTerreno):
            return self.comp.perfiles
        if isinstance(self.item, NivelItem):
            return self.comp.niveles
        if isinstance(self.item, LlamadaItem):
            return self.comp.llamadas
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


def _edits_of(cmd) -> list:
    """The field edits a command is made of: itself, or a compound's."""
    if isinstance(cmd, EditItemCommand):
        return [cmd]
    if isinstance(cmd, CompoundCommand) and cmd.commands and all(
            isinstance(c, EditItemCommand) for c in cmd.commands):
        return list(cmd.commands)
    return []


def _edit_signature(cmd):
    """Which items and fields a field edit touches — two edits with the
    same signature coalesce into one undo step (a retype, letter by
    letter; the same retype over a multiple selection)."""
    edits = _edits_of(cmd)
    if not edits:
        return None
    return tuple((id(e.item), frozenset(e.after)) for e in edits)


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
        if (coalesce and top is not None
                and _edit_signature(top) is not None
                and _edit_signature(top) == _edit_signature(cmd)):
            # keep top's `before`
            for t, c in zip(_edits_of(top), _edits_of(cmd)):
                t.after = dict(c.after)
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


def _xyz(v) -> tuple:
    """``(x, y, z)`` from a QVector3D or from a plain 3-tuple (the headless
    cameras of the tests use tuples)."""
    if hasattr(v, "x"):
        return (v.x(), v.y(), v.z())
    x, y, z = v
    return (float(x), float(y), float(z))


def roll_camera(camera, deg: float) -> None:
    """Spin ``camera`` about its own line of sight so the drawing turns
    ``deg`` degrees CLOCKWISE on paper (a plan rotated 30° here wants the
    north arrow at 30° too — same number, same direction).

    Only the up vector moves: ``camera_basis`` (and Qt's ``lookAt``) derive
    right and screen-up from it, so the whole view — GL render, hidden-line
    pass, snap points, projected annotations — turns as one."""
    if not deg:
        return
    th = math.radians(float(deg))
    cp, sp = math.cos(camera.pitch), math.sin(camera.pitch)
    cy, sy = math.cos(camera.yaw), math.sin(camera.yaw)
    f = (-cp * cy, -cp * sy, -sp)          # eye → target, as the camera builds it
    u0 = _xyz(camera.up_vector() if hasattr(camera, "up_vector")
              else camera.up)
    r = (f[1] * u0[2] - f[2] * u0[1],      # right = f × up
         f[2] * u0[0] - f[0] * u0[2],
         f[0] * u0[1] - f[1] * u0[0])
    rn = math.sqrt(sum(c * c for c in r))
    if rn < 1e-9:                          # up along the sight line: no roll
        return
    r = tuple(c / rn for c in r)
    u = (r[1] * f[2] - r[2] * f[1],        # screen-up = right × forward
         r[2] * f[0] - r[0] * f[2],
         r[0] * f[1] - r[1] * f[0])
    c, s_ = math.cos(th), math.sin(th)
    up = tuple(u[i] * c - r[i] * s_ for i in range(3))
    try:
        from PySide6.QtGui import QVector3D
        camera.up = QVector3D(*up)
    except ImportError:                    # headless tests use plain tuples
        camera.up = up


def apply_frame_camera(camera, frame: MarcoVista,
                       saved_view=None, scene=None) -> None:
    """Point ``camera`` (an OrbitCamera) at the frame's view, parallel, at
    exact scale. Mutates the camera (and layer visibility when a saved view
    is given) — callers snapshot/restore around this; see
    ``views/composer.py``."""
    if saved_view is not None and scene is not None:
        saved_view.apply(scene, camera)
    elif frame.view_key.startswith("std:"):
        key = frame.view_key[4:]
        camera.set_view(key)
        if key in ("top", "bottom"):
            # The interactive preset stops at 89° to dodge the lookAt
            # singularity with up = +Z. On paper that 1° writes double
            # lines (a 3 m wall offsets 0.5 mm at 1:100), so the plan
            # views go to a TRUE 90° and swap the up vector to +Y.
            camera.pitch = math.radians(90.0 if key == "top" else -90.0)
            try:
                from PySide6.QtGui import QVector3D
                camera.up = QVector3D(0.0, 1.0, 0.0)
            except ImportError:      # headless tests use plain tuples
                camera.up = (0.0, 1.0, 0.0)
        # A standard view carries an orientation but no framing: centre on
        # the model, or a big scale leaves it cropped out of the frame (the
        # live/saved views keep their own target — the user framed those).
        if scene is not None:
            lo, hi = scene.bounds()
            if lo is not None:
                camera.target = (lo + hi) * 0.5
    # Per-frame view edits (LayOut: double-click the viewport, then pan /
    # orbit / zoom) override whatever the view or the scene set.
    if frame.cam_yaw is not None:
        camera.yaw = float(frame.cam_yaw)
    if frame.cam_pitch is not None:
        camera.pitch = float(frame.cam_pitch)
        if abs(frame.cam_pitch) < math.radians(89.5):
            try:                            # orbited off a plan: Z is up again
                from PySide6.QtGui import QVector3D
                camera.up = QVector3D(0.0, 0.0, 1.0)
            except ImportError:
                camera.up = (0.0, 0.0, 1.0)
    if frame.cam_target is not None:
        x, y, z = (float(v) for v in frame.cam_target)
        try:
            from PySide6.QtGui import QVector3D
            camera.target = QVector3D(x, y, z)
        except ImportError:
            camera.target = (x, y, z)
    # Last, over whatever up vector the view left: the frame's own turn.
    roll_camera(camera, float(getattr(frame, "rot_deg", 0.0) or 0.0))
    w_px, h_px = frame.render_px()
    camera.aspect = w_px / h_px
    if getattr(frame, "perspective", False):
        # A perspective frame is framed by WHERE THE EYE STANDS, not by a
        # scale: distance and field of view are the whole framing.
        fov = frame.cam_fov
        if fov is None and saved_view is not None:
            fov = saved_view.fov_deg
        if fov is not None:
            camera.fov_deg = max(5.0, min(120.0, float(fov)))
        dist = frame.cam_distance
        if dist is None and saved_view is not None:
            dist = saved_view.distance
        if dist is None:
            dist = fit_distance_for_scene(scene, camera.fov_deg)
        camera.perspective = True
        camera.distance = max(1e-3, float(dist))
        return
    camera.perspective = False
    camera.distance = ortho_distance_for_height(
        frame.model_height_m(), camera.fov_deg)
