# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Layer / tag system: visibility and locking (tags).

A layer never *owns* geometry — it is a label an entity carries (faces via
``attrs["layer"]``, edges via their ``layer`` slot, groups via ``.layer``).
Hiding a layer removes its entities from render, picking and box selection;
locking keeps them visible but unpickable. Everything unlabelled lives on the
default layer, which always exists and cannot be removed.

This is what makes the '2D that emerges' workflow real: structure / walls /
plumbing / furniture live on their own layers of one model, and a top view in
parallel projection with the right layers on IS the plan drawing.
"""
from __future__ import annotations

import math

DEFAULT_LAYER = "Layer 0"

# Where an imported photogrammetric survey lands (Track G, G6). Its own layer
# by default, not the default one: the whole point of importing a survey is to
# draw on top of it, and you need to switch it off to look at what you drew —
# which would take your model with it if they shared a layer. A plain stored
# name like DEFAULT_LAYER, not a translated one: layer names are document data
# and must not change with the interface language.
SURVEY_LAYER = "Survey"

LINE_STYLES = ("solid", "dashed", "dotted")


def _optional_rgb(raw) -> tuple[float, float, float] | None:
    if raw is None:
        return None
    try:
        values = tuple(float(c) for c in raw)
    except (TypeError, ValueError):
        return None
    if len(values) < 3 or not all(math.isfinite(c) for c in values[:3]):
        return None
    return tuple(max(0.0, min(1.0, c)) for c in values[:3])


class Layer:
    """A named tag with display state and optional appearance overrides."""

    def __init__(self, name: str, visible: bool = True,
                 locked: bool = False, tint_color=None, edge_color=None,
                 line_style: str | None = None, parent: str | None = None,
                 transparency: int = 0) -> None:
        self.name = name
        self.visible = visible
        self.locked = locked
        self.tint_color = _optional_rgb(tint_color)
        self.edge_color = _optional_rgb(edge_color)
        self.line_style = (line_style if line_style in LINE_STYLES else None)
        self.parent = parent if isinstance(parent, str) and parent else None
        try:
            value = float(transparency)
            self.transparency = (max(0, min(100, round(value)))
                                 if math.isfinite(value) else 0)
        except (TypeError, ValueError):
            self.transparency = 0

    def to_dict(self) -> dict:
        entry: dict = {"name": self.name}
        if not self.visible:
            entry["visible"] = False
        if self.locked:
            entry["locked"] = True
        if self.tint_color is not None:
            entry["tint_color"] = list(self.tint_color)
        if self.edge_color is not None:
            entry["edge_color"] = list(self.edge_color)
        if self.line_style is not None:
            entry["line_style"] = self.line_style
        if self.parent is not None:
            entry["parent"] = self.parent
        if self.transparency:
            entry["transparency"] = self.transparency
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "Layer":
        return cls(raw.get("name", DEFAULT_LAYER),
                   visible=raw.get("visible", True),
                   locked=raw.get("locked", False),
                   tint_color=raw.get("tint_color"),
                   edge_color=raw.get("edge_color"),
                   line_style=raw.get("line_style"),
                   parent=raw.get("parent"),
                   transparency=raw.get("transparency", 0))


def layer_of(entity) -> str:
    """The layer name an entity carries (default when unlabelled)."""
    attrs = getattr(entity, "attrs", None)
    if attrs is not None:                          # Face
        return attrs.get("layer") or DEFAULT_LAYER
    return getattr(entity, "layer", None) or DEFAULT_LAYER


def assign_layer(entity, name: str) -> None:
    """Label an entity with a layer (default name clears the label)."""
    value = None if name == DEFAULT_LAYER else name
    attrs = getattr(entity, "attrs", None)
    if attrs is not None:                          # Face
        if value is None:
            attrs.pop("layer", None)
        else:
            attrs["layer"] = value
    elif hasattr(entity, "layer"):
        entity.layer = value
