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

- the .skp import to keep the .skp file's material NAMES ("Wood_Floor", not
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
    #: How the surface answers light in a render (core.finish): one of
    #: ``core.finish.FINISHES``, or ``None`` = guessed from the name.
    finish: Optional[str] = None

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
        if self.finish is not None:
            entry["finish"] = self.finish
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "Material":
        color = raw.get("color")
        return cls(
            name=raw.get("name", ""),
            color=tuple(color) if color is not None else None,
            texture=dict(raw["texture"]) if raw.get("texture") else None,
            opacity=raw.get("opacity"),
            finish=raw.get("finish") or None,
        )


def is_translucent(attrs) -> bool:
    """Whether a face's FRONT material lets light through: a translucency
    below 1, or a texture with real see-through pixels (glass, water, a
    raschel mesh, foliage)."""
    if not attrs:
        return False
    if float(attrs.get("opacity", 1.0)) < 0.999:
        return True
    tex = attrs.get("texture")
    if tex and tex.get("path"):
        from core.texture import image_has_cutout
        return image_has_cutout(tex["path"])
    return False


def back_is_default(attrs) -> bool:
    """Whether the BACK of a face shows the style's default back colour.

    Painting covers exactly the side you click: the front of a wall takes
    the brick, its back keeps the blue-grey default — unless the material
    is translucent, when paint goes on both sides so glass, water and a
    mesh read the same from either side («solo en el caso de una malla o
    cristal o agua», Marco, 2026-09-11). ``attrs["back"]`` says when the
    back has something of its own: ``True`` mirrors the front (a two-sided
    face, what the mesh formats describe), a dict is its own material.
    """
    if attrs and attrs.get("back"):
        return False
    return not is_translucent(attrs)


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


def has_own_material(attrs) -> bool:
    """Whether a face was painted itself (a colour or a texture of its own),
    as opposed to wearing the default material."""
    return bool(attrs) and (attrs.get("texture") is not None
                            or attrs.get("color") is not None)


def effective_attrs(attrs, material):
    """The attrs a face is DRAWN with inside a container that carries
    ``material`` (a group's or component instance's paint, issue #47).

    The classic rule, as @pacaeiro spelled it out: the face's own material
    always wins; only the faces wearing the default material take the
    container's, front and back alike. ``material`` is a dict with the same
    keys a face uses (``color`` / ``texture``, ``opacity``, ``mat``).

    Colour by layer (``core.layers.layer_paint``) passes a ``by_layer``
    table instead: then EVERY face draws in a layer's colour on both sides —
    its own layer's when it carries one, else the container's — over its
    material and texture, keeping only its opacity.

    The layers' own look (``core.layers.layer_look``) wraps either of
    those in a ``layer_fx`` table: a layer's opacity makes its faces see-
    through, and a locked layer's faces wash toward white."""
    if material and material.get("layer_fx") is not None:
        merged = effective_attrs(attrs, material.get("base"))
        own = (attrs or {}).get("layer")
        fx = material["layer_fx"].get(own) if own else None
        if fx is None:
            fx = material.get("fx_self")
        if not fx:
            return merged
        opacity, fade = fx
        merged = dict(merged or {})
        if opacity < 1.0:
            merged["opacity"] = min(float(merged.get("opacity", 1.0)),
                                    float(opacity))
        if fade > 0.0 and not merged.get("texture"):
            from core.layers import DEFAULT_LAYER_COLOR
            rgb = merged.get("color") or DEFAULT_LAYER_COLOR
            merged["color"] = tuple(c + (1.0 - c) * fade for c in rgb[:3])
        return merged
    if material and material.get("by_layer") is not None:
        own = (attrs or {}).get("layer")
        rgba = material["by_layer"].get(own) if own else None
        if rgba is None:
            rgba = material.get("color")
        merged = dict(attrs or {})
        for key in ("texture", "mat"):
            merged.pop(key, None)
        merged["color"] = tuple(rgba[:3]) if rgba is not None else None
        # The picked colour's alpha is meaningful only in Colour by layer.
        # Keep it independent of the layer-wide opacity (the layer_fx block
        # above), while respecting a face/material that is already clearer.
        if rgba is not None and len(rgba) > 3:
            alpha = min(1.0, max(0.0, float(rgba[3])))
            if alpha < 1.0:
                merged["opacity"] = min(
                    float(merged.get("opacity", 1.0)), alpha)
        merged["back"] = True
        return merged
    if not material or has_own_material(attrs):
        return attrs
    merged = dict(attrs or {})
    for key in ("color", "texture", "opacity", "mat"):
        if key in material and material[key] is not None:
            merged[key] = material[key]
    if not merged.get("back"):
        merged["back"] = True            # both sides wear the container's
    return merged


def material_sig(material):
    """A hashable signature of a container material for cache keys, or
    ``None`` when there is none."""
    if not material:
        return None
    if material.get("layer_fx") is not None:
        return ("layer_fx", material_sig(material.get("base")),
                tuple(sorted(material["layer_fx"].items())),
                material.get("fx_self"))
    if material.get("by_layer") is not None:
        color = material.get("color")
        return ("by_layer", tuple(color) if color is not None else None,
                tuple(sorted((k, tuple(v))
                             for k, v in material["by_layer"].items())))
    tex = material.get("texture")
    return (tuple(material["color"]) if material.get("color") is not None else None,
            (tex.get("path"), tex.get("sw"), tex.get("sh"), tex.get("rot"))
            if isinstance(tex, dict) else None,
            material.get("opacity"), material.get("mat"))


def free_name(base: str, taken) -> str:
    """*base*, or ``"base (2)"``, ``"base (3)"``… — the first that is not
    in *taken* (a registry dict or any container of names)."""
    name = base
    n = 2
    while name in taken:
        name = f"{base} ({n})"
        n += 1
    return name
