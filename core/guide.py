# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Construction guides (Tape Measure) — guide lines and points.

A guide is scaffolding, not geometry: an infinite dashed construction line (or a
lone point) used to align real drawing. It never enters the topology mesh; it
lives in ``Scene.guides``, renders as a fine dashed overlay, and feeds the snap
engine so drawing tools can lock onto it — that is its whole purpose.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

# Half-length used when a conceptually infinite guide line needs segment form
# (render clipping and snap both work on segments).
GUIDE_HALF_LEN = 1.0e4


class Guide:
    """A construction guide: an infinite line (``point`` + ``direction``) or,
    when ``direction`` is None, a guide point.

    A guide point pulled from a vertex keeps ``origin``, the vertex it was
    measured from: a dashed *guide segment* is drawn from there to
    the point (Rafael, Revisión 3: «un segmento guía que termina en un
    puntito»), which is how the eye reads what the point is 1,5 m from.
    The segment is a drawing, not a snap target — the point is."""

    def __init__(self, point: QVector3D, direction: QVector3D | None = None,
                 origin: QVector3D | None = None,
                 layer: str | None = None) -> None:
        self.point = QVector3D(point)
        self.direction = (QVector3D(direction).normalized()
                          if direction is not None and
                          QVector3D(direction).length() > 1e-12 else None)
        self.origin = (QVector3D(origin)
                       if origin is not None and self.direction is None
                       else None)
        #: Layer (tag) the guide lives on; ``None`` = default layer. A
        #: hidden layer hides its guides — drawn, snapped and picked no
        #: more — like the dimensions and texts on it.
        self.layer = layer

    @property
    def is_line(self) -> bool:
        return self.direction is not None

    def is_finite(self) -> bool:
        """Every coordinate is a number. A guide at NaN cannot be drawn or
        snapped to, and the file refused to save over one (#723)."""
        import math
        return all(math.isfinite(c) for v in (self.point, self.direction,
                                              self.origin)
                   if v is not None for c in (v.x(), v.y(), v.z()))

    def segment(self) -> tuple[QVector3D, QVector3D]:
        """The guide as a long finite segment (for render clipping and snap)."""
        if self.direction is None:
            return QVector3D(self.point), QVector3D(self.point)
        d = self.direction * GUIDE_HALF_LEN
        return self.point - d, self.point + d

    # Snap-engine duck-typing: guides are fed to ``compute_snap`` as pseudo
    # edges, which only reads ``.a`` / ``.b``.
    @property
    def a(self) -> QVector3D:
        return self.segment()[0]

    @property
    def b(self) -> QVector3D:
        return self.segment()[1]

    # ---- Serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        entry = {"point": [self.point.x(), self.point.y(), self.point.z()]}
        if self.direction is not None:
            entry["direction"] = [self.direction.x(), self.direction.y(),
                                  self.direction.z()]
        if self.origin is not None:
            entry["origin"] = [self.origin.x(), self.origin.y(),
                               self.origin.z()]
        if self.layer:
            entry["layer"] = self.layer
        return entry

    @classmethod
    def from_dict(cls, data: dict) -> "Guide":
        d = data.get("direction")
        o = data.get("origin")
        return cls(QVector3D(*data["point"]),
                   QVector3D(*d) if d else None,
                   QVector3D(*o) if o else None,
                   layer=data.get("layer") or None)
