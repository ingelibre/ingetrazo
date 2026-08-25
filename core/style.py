# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Display styles — SketchUp's Styles, scoped to what serves plans/printing.

A style bundles how the model DRAWS (not what it is): the face mode, edge
look and background. It feeds the viewport live and, through scenes, the
sheet composer (frames rendered in the live look inherit the active style;
the composer's own "tecnico"/"lineas" overrides map to Hidden line /
Wireframe).

Face modes (SketchUp's Face Styles):
- ``textures``    Shaded with textures — the default working look.
- ``shaded``      Colours only: textured faces draw in their texture's
                  average colour (SketchUp shows the material colour).
- ``hidden_line`` Flat white faces + edges — THE printing/plan style.
- ``monochrome``  Flat default front/back colours, no materials — the
                  reversed-face checker.
- ``wireframe``   Edges only, no faces (nothing occludes).
- ``xray``        Everything translucent, edges always visible.

Deferred (documented, not lost): back edges, depth cue, extensions,
endpoints, jitter, watermarks, per-material edge colour.
"""
from __future__ import annotations

from dataclasses import dataclass, field

FACE_MODES = ("textures", "shaded", "hidden_line", "monochrome",
              "wireframe", "xray")


@dataclass
class Style:
    name: str = "Default"
    face_mode: str = "textures"
    edges: bool = True
    profiles: bool = True                    # silhouette/profile edge pass
    edge_color: tuple = (0.13, 0.17, 0.23)
    front_color: tuple = (1.0, 1.0, 1.0)     # hidden line / monochrome faces
    background: tuple = (0.90, 0.91, 0.92)
    sky: bool = True
    # SketchUp 2018+ Section Fill: paint the cut-through areas of solids.
    # Lives in the STYLE, exactly like SketchUp's modeling settings.
    section_fill: bool = True
    section_fill_color: tuple = (0.35, 0.37, 0.41)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "face_mode": self.face_mode,
            "edges": self.edges,
            "profiles": self.profiles,
            "edge_color": list(self.edge_color),
            "front_color": list(self.front_color),
            "background": list(self.background),
            "sky": self.sky,
            "section_fill": self.section_fill,
            "section_fill_color": list(self.section_fill_color),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Style":
        mode = raw.get("face_mode", "textures")
        if mode not in FACE_MODES:
            mode = "textures"
        d = cls()
        return cls(
            name=raw.get("name", d.name),
            face_mode=mode,
            edges=bool(raw.get("edges", d.edges)),
            profiles=bool(raw.get("profiles", d.profiles)),
            edge_color=tuple(raw.get("edge_color", d.edge_color)),
            front_color=tuple(raw.get("front_color", d.front_color)),
            background=tuple(raw.get("background", d.background)),
            sky=bool(raw.get("sky", d.sky)),
            section_fill=bool(raw.get("section_fill", d.section_fill)),
            section_fill_color=tuple(raw.get("section_fill_color",
                                             d.section_fill_color)),
        )

    def copy(self) -> "Style":
        return Style.from_dict(self.to_dict())


# The best of SketchUp's collections, adapted: Default (working look),
# Architectural (clean white presentation), and the classic face styles.
def style_by_name(name: str) -> Style | None:
    """A COPY of the built-in preset called ``name`` (composer frames keep a
    ``"style:<name>"`` reference), or ``None`` if unknown."""
    for preset in BUILTIN_STYLES:
        if preset.name == name:
            return preset.copy()
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
    Style(name="X-ray", face_mode="xray"),
]
