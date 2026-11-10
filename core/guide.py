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


class GuideCircle:
    """A construction guide that is a PERFECT circle: centre, the plane it
    lies on (a unit normal) and its radius.

    Like :class:`Guide` it is scaffolding, never meshed: it lives in
    ``Scene.guides`` and is drawn as a dashed circle. The circle is stored
    analytically — three numbers plus an orientation — so rim, centre,
    quadrant and tangent snaps are exact, not a polygon's vertices.
    """

    def __init__(self, center: QVector3D, normal: QVector3D, radius: float,
                 layer: str | None = None) -> None:
        self.center = QVector3D(center)
        n = QVector3D(normal)
        self.normal = (n.normalized() if n.length() > 1e-12
                       else QVector3D(0.0, 0.0, 1.0))
        self.radius = float(radius)
        self.layer = layer
        #: A circle has no guide-point origin (the dashed segment back to a
        #: vertex); it stays None so Move/Rotate treat it like a bare guide.
        self.origin = None

    @property
    def is_circle(self) -> bool:
        return True

    #: A circle is neither a guide LINE nor a guide point — its own kind.
    @property
    def is_line(self) -> bool:
        return False

    #: ``point`` / ``direction`` duck-typing: the move/rotate commands read
    #: and write ``point`` (rotate also reads ``direction``), so a circle
    #: exposes its centre as the point and its normal as the direction.
    @property
    def point(self) -> QVector3D:
        return self.center

    @point.setter
    def point(self, value: QVector3D) -> None:
        self.center = QVector3D(value)

    @property
    def direction(self) -> QVector3D | None:
        return self.normal

    @direction.setter
    def direction(self, value: QVector3D | None) -> None:
        # RotateGuidesCommand turns the plane's normal through the rotation
        # matrix; a circle's direction IS its normal.
        if value is None:
            return
        n = QVector3D(value)
        self.normal = (n.normalized() if n.length() > 1e-12
                       else QVector3D(0.0, 0.0, 1.0))

    def is_finite(self) -> bool:
        import math
        return (all(math.isfinite(c) for v in (self.center, self.normal)
                    for c in (v.x(), v.y(), v.z()))
                and math.isfinite(self.radius))

    def sample_points(self, n: int = 64) -> list:
        """``n`` points around the rim (world space) — for picking and box
        tests. Display-only approximation; the stored circle stays analytic."""
        import math
        from core.axes import plane_axes
        u, v = plane_axes(self.normal)
        return [self.center + (u * math.cos(2.0 * math.pi * i / n)
                               + v * math.sin(2.0 * math.pi * i / n)) * self.radius
                for i in range(n)]

    # ---- Serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        entry = {
            "kind": "circle",
            "center": [self.center.x(), self.center.y(), self.center.z()],
            "normal": [self.normal.x(), self.normal.y(), self.normal.z()],
            "radius": self.radius,
        }
        if self.layer:
            entry["layer"] = self.layer
        return entry

    @classmethod
    def from_dict(cls, data: dict) -> "GuideCircle":
        c = data.get("center") or [0.0, 0.0, 0.0]
        n = data.get("normal") or [0.0, 0.0, 1.0]
        return cls(QVector3D(*c), QVector3D(*n),
                   float(data.get("radius", 0.0)),
                   layer=data.get("layer") or None)


def is_guide(entity) -> bool:
    """True for a construction guide of either kind — a guide line or point
    (:class:`Guide`) or an analytic guide circle (:class:`GuideCircle`).

    Both kinds duck-type ``point`` / ``direction`` (a circle exposes its
    centre as the point and its plane normal as the direction), so any code
    that filters ``isinstance(ent, Guide)`` must go through this helper or it
    silently drops circles from Move / Rotate / Delete / Zoom Selection.
    """
    return isinstance(entity, Guide) or isinstance(entity, GuideCircle)


def guide_from_dict(data: dict):
    """Rebuild a guide of either kind from its ``.igz`` record.

    A circle carries ``"kind": "circle"``; a guide line or point (the
    original form) has no kind and goes through :meth:`Guide.from_dict`.
    """
    if data.get("kind") == "circle":
        return GuideCircle.from_dict(data)
    return Guide.from_dict(data)
