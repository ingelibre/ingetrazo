# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Display styles — Styles, scoped to what serves plans/printing.

A style bundles how the model DRAWS (not what it is): the face mode, edge
look and background. It feeds the viewport live and, through scenes, the
sheet composer (frames rendered in the live look inherit the active style;
the composer's own "tecnico"/"lineas" overrides map to Hidden line /
Wireframe).

Face modes (Face Styles):
- ``textures``    Shaded with textures — the default working look.
- ``shaded``      Colours only: textured faces draw in their texture's
                  average colour (the material colour).
- ``hidden_line`` Flat white faces + edges — THE printing/plan style.
- ``monochrome``  Flat default front/back colours, no materials — the
                  reversed-face checker.
- ``wireframe``   Edges only, no faces (nothing occludes).
X-ray is an independent overlay: it keeps the face mode and makes faces
transparent while allowing inference through them. Legacy ``face_mode=xray``
documents load as textured faces with this overlay enabled.

Deferred (documented, not lost): jitter and watermarks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FACE_MODES = ("textures", "shaded", "hidden_line", "monochrome",
              "wireframe")
EDGE_COLOR_MODES = ("same", "material", "axis")
PROFILE_CAPS = ("butt", "round", "square", "round_extended")
ENDPOINT_TYPES = ("default", "round", "square", "triangle")
EDGE_WIDTH_RANGE = (1, 20)
EDGE_LENGTH_RANGE = (1, 50)
EDGE_EXTENSION_RANGE = (-50, 50)
TRANSPARENCY_QUALITIES = ("faster", "nicer")
XRAY_OPACITY_RANGE = (20, 80)

#: The soft warm white of the faces that wear no material in the shaded
#: modes — the matte cardstock of an architecture model. The style's Front
#: color tints it (``views.viewport._front_tint``).
DEFAULT_FACE_COLOR = (0.96, 0.95, 0.925)

#: The classic default back-face blue-grey: a visible back face means "you are
#: looking at the inside" (or at a genuinely inverted face).
DEFAULT_BACK_COLOR = (0.62, 0.70, 0.78)


@dataclass
class Style:
    name: str = "Default"
    face_mode: str = "textures"
    edges: bool = True
    profiles: bool = True                    # silhouette/profile edge pass
    # Back Edges (K): the edges hidden behind faces, drawn dashed, over an
    # opaque model — where a bar continues behind a face in a shop drawing
    # (issue #234). Off in every preset.
    back_edges: bool = False
    edge_color: tuple = (0.13, 0.17, 0.23)
    # Distances and widths are logical screen pixels, independent of zoom.
    profile_width: int = 1
    profile_cap: str = "butt"
    depth_cue: bool = False
    depth_cue_width: int = 4
    extensions: bool = False
    extension_length: int = 3
    endpoints: bool = False
    endpoint_length: int = 3
    endpoint_type: str = "default"
    endpoint_size: int = 6
    dashes: bool = True
    edge_color_mode: str = "same"
    material_transparency: bool = True
    transparency_quality: str = "faster"
    xray_opacity: int = 60
    # The faces' front colour: every face in Hidden line and Monochrome,
    # and the faces wearing no material in the other modes (issue #776).
    front_color: tuple = (1.0, 1.0, 1.0)
    # Back-face tint (Back color). ``None`` = automatic: the
    # document's adopted tint (``scene.back_face_color``, e.g. from an
    # imported .skp) or ``DEFAULT_BACK_COLOR``. A picked colour wins over
    # both — see ``effective_back_color``.
    back_color: tuple | None = None
    background: tuple = (0.90, 0.91, 0.92)
    sky: bool = True
    # The sky/ground backdrop tones (drawn when ``sky`` is on; with it off
    # the flat ``background`` shows instead). Defaults match the viewport's
    # historical constants, so old documents look identical.
    sky_color: tuple = (0.925, 0.935, 0.945)
    ground_color: tuple = (0.815, 0.820, 0.815)
    # Section Fill: paint the cut-through areas of solids.
    # Lives in the STYLE, with the other modeling settings.
    section_fill: bool = True
    section_fill_color: tuple = (0.35, 0.37, 0.41)
    # Ambient occlusion (#954): the soft darkening where
    # surfaces meet. Off in every preset; the distance is in metres (how
    # far a surface still darkens its neighbour), the intensity 0–2.
    ambient_occlusion: bool = False
    ao_distance: float = 0.5
    ao_intensity: float = 1.0
    # Colour by layer: faces draw in their layer's colour (core.layers
    # .layer_color) instead of their material — the shaded, textured and
    # X-ray modes. Off in every preset; a scene remembers it with the style.
    color_by_layer: bool = False
    xray: bool = False
    # None preserves the historical combined sky/ground backdrop. An explicit
    # value opts into independent ground controls without changing old files.
    ground: bool | None = None
    ground_transparency: int = 0
    ground_from_below: bool = True

    def __post_init__(self):
        if self.face_mode == "xray":
            self.face_mode = "textures"
            self.xray = True

    def to_dict(self) -> dict:
        out = {
            "name": self.name,
            "face_mode": base_face_mode(self),
            "edges": self.edges,
            "profiles": self.profiles,
            "back_edges": self.back_edges,
            "edge_color": list(self.edge_color),
            "front_color": list(self.front_color),
            "back_color": (list(self.back_color)
                           if self.back_color is not None else None),
            "background": list(self.background),
            "sky": self.sky,
            "sky_color": list(self.sky_color),
            "ground_color": list(self.ground_color),
            "section_fill": self.section_fill,
            "section_fill_color": list(self.section_fill_color),
            "ambient_occlusion": self.ambient_occlusion,
            "ao_distance": self.ao_distance,
            "ao_intensity": self.ao_intensity,
        }
        if self.color_by_layer:
            out["color_by_layer"] = True
        if xray_enabled(self):
            out["xray"] = True
        # Keep old/default styles byte-for-byte compatible. New fields are
        # optional, including the values of currently disabled effects.
        defaults = {"profile_width": 1, "profile_cap": "butt", "depth_cue": False,
                    "depth_cue_width": 4, "extensions": False,
                    "extension_length": 3, "endpoints": False,
                    "endpoint_length": 3, "endpoint_type": "default",
                    "endpoint_size": 6, "dashes": True,
                    "edge_color_mode": "same", "material_transparency": True,
                    "transparency_quality": "faster", "xray_opacity": 60,
                    "ground": None, "ground_transparency": 0,
                    "ground_from_below": True}
        for attr, default in defaults.items():
            value = getattr(self, attr)
            if value != default:
                out[attr] = value
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Style":
        mode = raw.get("face_mode", "textures")
        legacy_xray = mode == "xray"
        if legacy_xray:
            mode = "textures"
        if mode not in FACE_MODES:
            mode = "textures"
        d = cls()
        return cls(
            name=raw.get("name", d.name),
            face_mode=mode,
            xray=bool(raw.get("xray", legacy_xray)),
            edges=bool(raw.get("edges", d.edges)),
            profiles=bool(raw.get("profiles", d.profiles)),
            back_edges=bool(raw.get("back_edges", d.back_edges)),
            edge_color=tuple(raw.get("edge_color", d.edge_color)),
            profile_width=_pixel_value(raw.get("profile_width"), d.profile_width,
                                       EDGE_WIDTH_RANGE),
            profile_cap=(raw.get("profile_cap")
                         if raw.get("profile_cap") in PROFILE_CAPS else d.profile_cap),
            depth_cue=bool(raw.get("depth_cue", d.depth_cue)),
            depth_cue_width=_pixel_value(raw.get("depth_cue_width"), d.depth_cue_width,
                                         EDGE_WIDTH_RANGE),
            extensions=bool(raw.get("extensions", d.extensions)),
            extension_length=_pixel_value(raw.get("extension_length"), d.extension_length,
                                          EDGE_EXTENSION_RANGE),
            endpoints=bool(raw.get("endpoints", d.endpoints)),
            endpoint_length=_pixel_value(raw.get("endpoint_length"), d.endpoint_length,
                                         EDGE_LENGTH_RANGE),
            endpoint_type=(raw.get("endpoint_type")
                           if raw.get("endpoint_type") in ENDPOINT_TYPES else d.endpoint_type),
            endpoint_size=_pixel_value(raw.get("endpoint_size"), d.endpoint_size,
                                       EDGE_LENGTH_RANGE),
            dashes=bool(raw.get("dashes", d.dashes)),
            edge_color_mode=(raw.get("edge_color_mode")
                             if raw.get("edge_color_mode") in EDGE_COLOR_MODES else "same"),
            material_transparency=bool(raw.get("material_transparency", d.material_transparency)),
            transparency_quality=(raw.get("transparency_quality")
                                  if raw.get("transparency_quality") in TRANSPARENCY_QUALITIES
                                  else d.transparency_quality),
            xray_opacity=_pixel_value(raw.get("xray_opacity"), d.xray_opacity, XRAY_OPACITY_RANGE),
            front_color=tuple(raw.get("front_color", d.front_color)),
            back_color=_opt_rgb(raw.get("back_color")),
            background=tuple(raw.get("background", d.background)),
            sky=bool(raw.get("sky", d.sky)),
            sky_color=tuple(raw.get("sky_color", d.sky_color)),
            ground_color=tuple(raw.get("ground_color", d.ground_color)),
            ground=(bool(raw["ground"]) if raw.get("ground") is not None else None),
            ground_transparency=_pixel_value(raw.get("ground_transparency"), 0, (0, 100)),
            ground_from_below=bool(raw.get("ground_from_below", True)),
            section_fill=bool(raw.get("section_fill", d.section_fill)),
            section_fill_color=tuple(raw.get("section_fill_color",
                                             d.section_fill_color)),
            ambient_occlusion=bool(raw.get("ambient_occlusion",
                                           d.ambient_occlusion)),
            ao_distance=_clamped(raw.get("ao_distance"), d.ao_distance,
                                 AO_DISTANCE_RANGE),
            ao_intensity=_clamped(raw.get("ao_intensity"), d.ao_intensity,
                                  AO_INTENSITY_RANGE),
            color_by_layer=bool(raw.get("color_by_layer", False)),
        )

    def copy(self) -> "Style":
        return Style.from_dict(self.to_dict())


#: The ambient occlusion controls' ranges (metres; plain factor).
AO_DISTANCE_RANGE = (0.01, 50.0)
AO_INTENSITY_RANGE = (0.0, 2.0)


def _pixel_value(raw, default: int, bounds: tuple) -> int:
    return round(_clamped(raw, default, bounds))


def xray_enabled(style) -> bool:
    """Also accept legacy direct assignments from scripts and extensions."""
    return bool(getattr(style, "xray", False) or getattr(style, "face_mode", None) == "xray")


def base_face_mode(style) -> str:
    mode = getattr(style, "face_mode", "textures")
    return "textures" if mode == "xray" else mode


def sees_through_faces(style) -> bool:
    return xray_enabled(style) or base_face_mode(style) == "wireframe"


def ground_enabled(style) -> bool:
    """Resolve the legacy combined backdrop or the independent ground toggle."""
    ground = getattr(style, "ground", None)
    return bool(style.sky if ground is None else ground)


def _clamped(raw, default: float, bounds: tuple) -> float:
    """A number from a dict, kept in ``bounds``; anything malformed (a
    hand-edited document) falls back to ``default``."""
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    if v != v:                                   # NaN
        return default
    return min(max(v, bounds[0]), bounds[1])


def _opt_rgb(raw) -> tuple | None:
    """An optional RGB from a dict: ``None`` (or anything malformed — an
    old or hand-edited document must never break the style) stays
    ``None``, i.e. automatic."""
    if raw is None:
        return None
    try:
        rgb = tuple(float(c) for c in raw)
    except (TypeError, ValueError):
        return None
    return rgb[:3] if len(rgb) >= 3 else None


def effective_back_color(style, scene=None) -> tuple:
    """The back-face tint that actually draws: the style's own
    ``back_color`` if picked, else the document's adopted tint
    (``scene.back_face_color``), else the classic default blue-grey."""
    picked = getattr(style, "back_color", None)
    if picked is not None:
        return tuple(picked[:3])
    adopted = getattr(scene, "back_face_color", None)
    if adopted is not None:
        return tuple(adopted[:3])
    return DEFAULT_BACK_COLOR


# The usual style collections, adapted: Default (working look),
# Architectural (clean white presentation), and the classic face styles.
def style_by_name(name: str) -> Style | None:
    """A COPY of the style called ``name`` — a built-in preset first, then
    the user's saved library (composer frames keep a ``"style:<name>"``
    reference, so both must resolve here). ``None`` if unknown."""
    for preset in BUILTIN_STYLES:
        if preset.name == name:
            return preset.copy()
    for saved in user_styles():
        if saved.name == name:
            return saved
    return None


BUILTIN_STYLES: list[Style] = [
    Style(name="Default"),
    Style(name="Architectural", background=(1.0, 1.0, 1.0), sky=False),
    Style(name="Shaded", face_mode="shaded"),
    Style(name="Hidden line", face_mode="hidden_line",
          background=(1.0, 1.0, 1.0), sky=False),
    Style(name="Monochrome", face_mode="monochrome",
          background=(1.0, 1.0, 1.0), sky=False),
    Style(name="Wireframe", face_mode="wireframe",
          background=(1.0, 1.0, 1.0), sky=False),
    Style(name="X-ray", xray=True),
]


# ---- User style library ------------------------------------------------------
# Saved styles live in QSettings ("styles/user", a JSON list) like the custom
# basemap sources: small, named, survive across sessions until removed. A
# document doesn't NEED the library — the .igz and saved views carry the full
# style dict — the library is what "Save style…" in the panel feeds and what
# lets a composer frame or another document reference the look by name.

def builtin_names() -> set[str]:
    return {p.name for p in BUILTIN_STYLES}


def _settings():
    """One place to get the QSettings handle, so tests can point it at a
    temp file."""
    from PySide6.QtCore import QSettings
    return QSettings()


def user_styles() -> list[Style]:
    """The saved user styles, in saved order. A broken entry is dropped, not
    fatal — a hand-edited config must never take the panel down."""
    import json
    raw = _settings().value("styles/user", "", type=str)
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except ValueError:
        return []
    out: list[Style] = []
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict) and e.get("name"):
                out.append(Style.from_dict(e))
    return out


def _store_user_styles(styles: list[Style]) -> None:
    import json
    s = _settings()
    s.setValue("styles/user", json.dumps([st.to_dict() for st in styles]))
    # Flush NOW: a saved style must survive even a crash right after saving
    # (QSettings otherwise buffers until a clean exit).
    s.sync()


def save_user_style(style: Style) -> None:
    """Add ``style`` to the library, replacing a same-named entry. A built-in
    preset's name is refused: the presets are the stable vocabulary that
    ``"style:<name>"`` frame references resolve first, so a user style under
    that name could never be reached."""
    if style.name in builtin_names():
        raise ValueError(f"'{style.name}' is a built-in style")
    kept = [s for s in user_styles() if s.name != style.name]
    _store_user_styles(kept + [style.copy()])


def delete_user_style(name: str) -> bool:
    """Remove the user style called ``name``. True if something was removed."""
    styles = user_styles()
    kept = [s for s in styles if s.name != name]
    if len(kept) == len(styles):
        return False
    _store_user_styles(kept)
    return True
