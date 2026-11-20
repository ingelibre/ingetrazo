# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Portable image layers belonging to a display style, not model geometry."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from uuid import uuid4


def _number(value, default, lo, hi):
    try:
        value = float(value)
        return round(min(hi, max(lo, value))) if math.isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default


@dataclass(frozen=True)
class Watermark:
    id: str
    name: str
    image: str  # Embedded PNG, base64; independent of the imported file's path.
    visible: bool = True
    layer: str = "foreground"
    placement: str = "positioned"
    anchor: int = 8
    scale: int = 25
    opacity: int = 100
    keep_aspect: bool = True
    create_mask: bool = False

    @classmethod
    def create(cls, name: str, image: str) -> "Watermark":
        return cls(uuid4().hex, name, image)

    def to_dict(self) -> dict:
        out = asdict(self)
        if not self.create_mask:
            out.pop("create_mask")
        return out

    @classmethod
    def from_dict(cls, raw) -> "Watermark | None":
        if not isinstance(raw, dict) or not isinstance(raw.get("image"), str) or not raw["image"]:
            return None
        return cls(
            id=str(raw.get("id") or uuid4().hex),
            name=str(raw.get("name", "")), image=raw["image"],
            visible=bool(raw.get("visible", True)),
            layer="background" if raw.get("layer") == "background" else "foreground",
            placement=(raw["placement"] if raw.get("placement") in
                       ("positioned", "stretched", "tiled") else "positioned"),
            anchor=_number(raw.get("anchor", 8), 8, 0, 8),
            scale=_number(raw.get("scale", 25), 25, 1, 200),
            opacity=_number(raw.get("opacity", 100), 100, 0, 100),
            keep_aspect=bool(raw.get("keep_aspect", True)),
            create_mask=bool(raw.get("create_mask", False)),
        )


def load_watermarks(raw) -> list[Watermark]:
    if not isinstance(raw, list):
        return []
    return [mark for entry in raw if (mark := Watermark.from_dict(entry)) is not None]
