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

#: Points → millimetres (text sizes on paper).
PT_TO_MM = 25.4 / 72.0


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
    #: Render style: "sombreado" (the model's ACTIVE display style),
    #: "style:<name>" (a core.style built-in preset — Hidden line,
    #: Architectural, ... — per frame, like LayOut viewports),
    #: "vectorial" (exact HLR vector pass), or the legacy "tecnico" /
    #: "lineas" (kept for old documents; the UI maps them onto the
    #: Hidden line / Wireframe presets).
    style: str = "sombreado"
    #: Draw the automatic title under the frame («Planta — 1:100»).
    show_title: bool = False
    #: Coordinate-grid spacing over the view, in model METRES (0 = off) —
    #: QGIS's graticule, the civil habit of gridded plans.
    grid_m: float = 0.0
    #: Stable identity for anchored dimensions ("" until a cota anchors to
    #: this frame — then a uuid4 hex that survives save/load and reorders).
    uid: str = ""
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped
    #: In-place view edits (LayOut: double-click the viewport, then pan /
    #: orbit / zoom). ``None`` = whatever the view or scene provides.
    cam_target: Optional[list] = None      # world point the camera centres on
    cam_yaw: Optional[float] = None        # radians, overrides the view's
    cam_pitch: Optional[float] = None
    #: Draw the model's own dimensions and leader texts in the frame
    #: (LayOut shows SketchUp's). Opt-in per frame; their layers decide
    #: per scene which ones.
    annotations: bool = False
    annot_text_mm: float = 2.8             # their text height on paper
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
        n = f"{self.scale_n:g}"
        try:
            return (self.scale_text or "ESC. 1:{n}").replace("{n}", n)
        except Exception:  # noqa: BLE001 — a broken template still labels
            return f"1:{n}"

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


@dataclass
class ImagenItem:
    """An image (logo, photo) on the sheet. The file is referenced by path;
    the .igz stores the path, not the pixels (same policy as textures)."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    w_mm: float = 60.0
    h_mm: float = 40.0
    path: str = ""
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped


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
    """A north arrow: circle, needle and N, rotatable to the project north."""

    x_mm: float = 20.0
    y_mm: float = 20.0
    size_mm: float = 18.0
    angle_deg: float = 0.0
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped

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

    @property
    def h_mm(self) -> float:
        return 7.5 + 5.5 * max(len(self.rows), 1)


@dataclass
class FormaItem:
    """A drawing shape: line, arrow, rectangle or ellipse. Lines/arrows run
    corner to corner of the box (``invert`` flips which diagonal)."""

    kind: str = "rect"           # linea | flecha | rect | elipse | poligono
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
    radius_mm: float = 0.0       # rect: corner rounding radius
    sides: int = 6               # poligono: number of sides (3..24)
    color: str = "#1e242c"       # stroke colour
    fill_color: str = "#e2e8ee"  # fill colour (when fill is on)


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
    stroke_mm: float = 0.25
    anchor_uid: str = ""         # frame whose geometry the point sits on
    a_world: Optional[list] = None
    uid: str = ""
    z: float = 0.0
    locked: bool = False
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped

    @property
    def anchored(self) -> bool:
        return bool(self.anchor_uid and self.a_world)

    @property
    def h_mm(self) -> float:
        size_mm = self.size_pt * PT_TO_MM
        return max(6.0, size_mm * 1.4 * (self.text.count("\n") + 1))


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
    text_pos: str = "above"      # above | centered | below
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
    z: float = 0.0            # stacking order on the page (higher = on top)
    locked: bool = False         # locked: shown but not movable/resizable
    group_id: str = ""            # sheet group (Ctrl+G); "" = ungrouped

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

    def real_distance_m(self) -> float:
        """Paper length at the cota's scale — for an anchored cota that is
        the distance projected on its frame's view plane, since the
        composer reprojects its endpoints from the model."""
        return math.hypot(self.dx_mm, self.dy_mm) * self.scale_n / 1000.0

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
    etiquetas: list = field(default_factory=list)
    perfiles: list = field(default_factory=list)
    cajetin: Optional[Cajetin] = None
    #: Sheet border drawn on the margin rectangle: width, colour, rounded
    #: corners and line type (single | double | dashed).
    border: bool = False
    border_mm: float = 0.5
    border_color: str = "#1e242c"
    border_radius_mm: float = 0.0
    border_style: str = "single"

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
               + list(self.scalebars) + list(self.nortes)
               + list(self.leyendas) + list(self.shapes) + list(self.cotas)
               + list(self.cotas_ang) + list(self.etiquetas)
               + list(self.perfiles))
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
                         ("etiquetas", self.etiquetas),
                         ("perfiles", self.perfiles)):
            if lst:
                d[key] = [asdict(it) for it in lst]
        if self.cajetin is not None:
            d["cajetin"] = asdict(self.cajetin)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Composicion":
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
        c.frames = [MarcoVista(**f) for f in d.get("frames", [])]
        c.texts = [TextoItem(**t) for t in d.get("texts", [])]
        c.images = [ImagenItem(**i) for i in d.get("images", [])]
        c.scalebars = [BarraEscala(**sb) for sb in d.get("scalebars", [])]
        c.nortes = [FlechaNorte(**n) for n in d.get("nortes", [])]
        c.leyendas = [Leyenda(**le) for le in d.get("leyendas", [])]
        c.shapes = [FormaItem(**f) for f in d.get("shapes", [])]
        c.cotas_ang = [CotaAngularItem(**a) for a in d.get("cotas_ang", [])]
        c.etiquetas = [EtiquetaItem(**e) for e in d.get("etiquetas", [])]
        c.perfiles = [PerfilTerreno(**pf) for pf in d.get("perfiles", [])]
        c.cotas = [CotaItem(**ct) for ct in d.get("cotas", [])]
        if "cajetin" in d:
            c.cajetin = Cajetin(**d["cajetin"])
        _migrate_fixed_scale_labels(c)
        return c


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
        "escala": f"1:{main.scale_n:g}" if main is not None else "",
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
        if isinstance(self.item, EtiquetaItem):
            return self.comp.etiquetas
        if isinstance(self.item, PerfilTerreno):
            return self.comp.perfiles
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
        if isinstance(self.item, EtiquetaItem):
            return self.comp.etiquetas
        if isinstance(self.item, PerfilTerreno):
            return self.comp.perfiles
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
    camera.perspective = False
    camera.distance = ortho_distance_for_height(
        frame.model_height_m(), camera.fov_deg)
    w_px, h_px = frame.render_px()
    camera.aspect = w_px / h_px
