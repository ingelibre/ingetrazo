# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The material registry: NAMED materials over the per-face attrs.

IngeTrazo's ground truth for pixels has always been the face itself:
``attrs["color"]`` (floats 0–1), ``attrs["texture"]`` and ``attrs["opacity"]``
ride the attrs dict, which the engine already carries across push/pull and
the plane rebuild. That stays exactly as is — the renderer and the engine
do not know this module exists.

What was missing is IDENTITY: "these 40 faces are *Concreto visto*", not
just "these 40 faces happen to be grey". A :class:`Material` gives a name
to one recipe of attrs, the scene keeps a registry of them, and a face that
was painted with a material carries ``attrs["mat"] = name`` alongside the
baked values. That one extra key — surviving face churn for free, like
every attr — is what enables:

- the .skp import to keep SketchUp's material NAMES ("Wood_Floor", not
  an anonymous colour),
- per-material quantities ("how many m² of *Tarrajeo*?"),
- editing a material once and restamping every face that wears it,
- exports that say ``Concreto_visto`` instead of ``mat0``.

The baked attrs remain authoritative for rendering: a face whose ``mat``
names a missing registry entry still renders exactly as painted — the
name is then just a label with nothing behind it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Material:
    """A named paint recipe: what stamping this material puts on a face."""

    name: str
    #: RGB floats 0–1 (the ``attrs["color"]`` convention), or ``None`` for
    #: a purely textured material.
    color: Optional[tuple] = None
    #: ``{"path", "sw", "sh"}`` — the ``attrs["texture"]`` dict (tile size
    #: in metres). ``.igz`` embedding rewrites ``path``→``embed`` inside
    #: containers and back; this module never needs to know.
    texture: Optional[dict] = None
    #: 0–1 translucency, or ``None`` for opaque (the attrs convention:
    #: the key is simply absent on opaque faces).
    opacity: Optional[float] = None

    def face_attrs(self) -> dict:
        """The attrs this material stamps on a face (its own name included)."""
        out: dict = {"mat": self.name}
        if self.color is not None:
            out["color"] = tuple(self.color)
        if self.texture is not None:
            out["texture"] = dict(self.texture)
        if self.opacity is not None:
            out["opacity"] = float(self.opacity)
        return out

    # ---- Serialization (.igz) -------------------------------------------
    def to_dict(self) -> dict:
        entry: dict = {"name": self.name}
        if self.color is not None:
            entry["color"] = list(self.color)
        if self.texture is not None:
            entry["texture"] = dict(self.texture)
        if self.opacity is not None:
            entry["opacity"] = float(self.opacity)
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "Material":
        color = raw.get("color")
        return cls(
            name=raw.get("name", ""),
            color=tuple(color) if color is not None else None,
            texture=dict(raw["texture"]) if raw.get("texture") else None,
            opacity=raw.get("opacity"),
        )


def register(materials: dict, mat: Material) -> str:
    """Add *mat* to the registry dict (name → Material), deduplicating.

    Same name + same recipe → the existing entry wins (idempotent, the
    common case when re-importing). Same name + different recipe → the new
    one registers under ``"name (2)"`` etc., so no import silently
    repaints another material's faces. Returns the final name."""
    base = mat.name or "Material"
    name = base
    n = 2
    while name in materials:
        other = materials[name]
        if (other.color == mat.color and other.texture == mat.texture
                and other.opacity == mat.opacity):
            return name
        name = f"{base} ({n})"
        n += 1
    if name != mat.name:
        mat = Material(name, mat.color, mat.texture, mat.opacity)
    materials[name] = mat
    return name
