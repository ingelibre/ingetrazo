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

DEFAULT_LAYER = "Layer 0"

# Where an imported photogrammetric survey lands (Track G, G6). Its own layer
# by default, not the default one: the whole point of importing a survey is to
# draw on top of it, and you need to switch it off to look at what you drew —
# which would take your model with it if they shared a layer. A plain stored
# name like DEFAULT_LAYER, not a translated one: layer names are document data
# and must not change with the interface language.
SURVEY_LAYER = "Survey"


class Layer:
    """A named tag with display state."""

    def __init__(self, name: str, visible: bool = True,
                 locked: bool = False, folder_id=None, position=0, color=None) -> None:
        self.name = name
        self.color = tuple(color) if color is not None else default_layer_color(name)
        self.visible = visible
        self.locked = locked
        self.folder_id = folder_id if name != DEFAULT_LAYER else None
        self.position = int(position)

    def to_dict(self) -> dict:
        entry: dict = {"name": self.name, "color": list(self.color)}
        if not self.visible:
            entry["visible"] = False
        if self.locked:
            entry["locked"] = True
        if self.folder_id is not None:
            entry["folder_id"] = self.folder_id
        if self.position:
            entry["position"] = self.position
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "Layer":
        return cls(raw.get("name", DEFAULT_LAYER),
                   visible=raw.get("visible", True),
                   locked=raw.get("locked", False),
                   folder_id=raw.get("folder_id"), position=raw.get("position", 0),
                   color=raw.get("color"))


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


class LayerFolder:
    """Nested tag organization, with inherited visibility and locking."""

    def __init__(self, name, uid=None, parent_id=None, position=0,
                 expanded=True, visible=True, locked=False):
        from uuid import uuid4
        self.name = name
        self.uid = uid or str(uuid4())
        self.parent_id = parent_id
        self.position = int(position)
        self.expanded = bool(expanded)
        self.visible = bool(visible)
        self.locked = bool(locked)

    def to_dict(self):
        return dict(name=self.name, uid=self.uid, parent_id=self.parent_id,
                    position=self.position, expanded=self.expanded,
                    visible=self.visible, locked=self.locked)

    @classmethod
    def from_dict(cls, raw):
        return cls(raw.get("name", "Folder"), uid=raw.get("uid"),
                   parent_id=raw.get("parent_id"), position=raw.get("position", 0),
                   expanded=raw.get("expanded", True),
                   visible=raw.get("visible", True), locked=raw.get("locked", False))


def default_layer_color(name):
    """Stable, distinct colours for new tags; RGB floats like materials."""
    if name == DEFAULT_LAYER:
        return (0.78, 0.78, 0.78)
    from colorsys import hsv_to_rgb
    from zlib import crc32
    return hsv_to_rgb((crc32(name.encode("utf-8")) % 360) / 360, 0.55, 0.85)


def display_layer_name(entity, inherited=DEFAULT_LAYER):
    """Untagged geometry inherits its container's tag for colour display."""
    name = layer_of(entity)
    return inherited if name == DEFAULT_LAYER else name
