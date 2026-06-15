"""Static linear dimension — a measured annotation between two world points.

A ``Dimension`` records two endpoints ``a``/``b`` (snapped to geometry when
placed) and an ``offset`` vector giving where the dimension line sits relative
to the measured segment. It is **static**: ``a`` and ``b`` are fixed positions
captured at placement, so the measured value never drifts. (Dimensions that
re-measure when the geometry moves are a later, anchored variant.)

It is an annotation, not geometry: it lives in ``Scene.dimensions`` and is drawn
as a screen-space overlay (extension lines + dimension line + value label), not
in the mesh.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QVector3D


@dataclass(eq=False)
class Dimension:
    a: QVector3D
    b: QVector3D
    offset: QVector3D  # displacement from the a–b segment to the dimension line

    def value(self) -> float:
        """Measured length (metres)."""
        return (self.b - self.a).length()

    def label(self) -> str:
        return f"{self.value():.2f} m"

    def line_points(self) -> tuple[QVector3D, QVector3D]:
        """The dimension line's endpoints (``a``/``b`` shifted by the offset)."""
        return self.a + self.offset, self.b + self.offset

    def midpoint(self) -> QVector3D:
        ap, bp = self.line_points()
        return (ap + bp) * 0.5

    @staticmethod
    def offset_for_cursor(a: QVector3D, b: QVector3D,
                          cursor: QVector3D) -> QVector3D:
        """Offset placing the dimension line through ``cursor`` while staying
        parallel to ``a``–``b``: the component of ``cursor − a`` perpendicular
        to the segment direction."""
        ab = b - a
        length = ab.length()
        if length < 1e-9:
            return cursor - a
        dir_ = ab / length
        to_cursor = cursor - a
        along = QVector3D.dotProduct(to_cursor, dir_)
        return to_cursor - dir_ * along
