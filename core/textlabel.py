# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Leader text — an annotation label pointing at the model.

A ``TextLabel`` records the world ``anchor`` it points at (snapped to
geometry when placed) and an ``offset`` to where the label floats; a leader
line joins them. Like ``Dimension`` it is an annotation, not geometry: it
lives in ``Scene.text_labels`` and is drawn as a screen-space overlay.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QVector3D


@dataclass(eq=False)
class TextLabel:
    anchor: QVector3D
    offset: QVector3D          # displacement from the anchor to the label
    text: str
    #: Layer (tag) the label lives on; ``None`` = default layer.
    layer: str | None = None
    #: Hidden by Hide (#272): a plain flag, like an object's — a label
    #: is not geometry, so it cannot borrow a face's ``attrs``
    #: (``core.layers`` reads a layer out of that dict).
    hidden: bool = False

    def position(self) -> QVector3D:
        """Where the label text floats (anchor + offset)."""
        return self.anchor + self.offset

    # ---- Serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "anchor": [self.anchor.x(), self.anchor.y(), self.anchor.z()],
            "offset": [self.offset.x(), self.offset.y(), self.offset.z()],
            "text": self.text,
            **({"layer": self.layer} if self.layer else {}),
            **({"hidden": True} if self.hidden else {}),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TextLabel":
        return cls(QVector3D(*data.get("anchor", [0, 0, 0])),
                   QVector3D(*data.get("offset", [0, 0, 0])),
                   data.get("text", ""),
                   layer=data.get("layer") or None,
                   hidden=bool(data.get("hidden")))
