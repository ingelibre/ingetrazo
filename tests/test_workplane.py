# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The first-point work-plane rule: dimensioning/drawing in a standard view
stays in the plane you're looking at instead of falling to the ground."""
from PySide6.QtGui import QVector3D

from core.snap import first_point_work_plane

C = QVector3D(3.0, 4.0, 5.0)          # a model centre off every axis


def _fw(x, y, z):
    return QVector3D(x, y, z)


class TestFirstPointWorkPlane:
    def test_front_view_gives_the_frontal_plane(self):
        # looking along -Y (front view): plane normal ±Y through the centre
        pt, n = first_point_work_plane(_fw(0, -1, 0), C)
        assert (n.x(), n.z()) == (0.0, 0.0) and abs(n.y()) == 1.0
        assert pt == C                     # at the model's depth, not Z=0

    def test_side_view_gives_the_sagittal_plane(self):
        pt, n = first_point_work_plane(_fw(1, 0, 0), C)
        assert abs(n.x()) == 1.0 and (n.y(), n.z()) == (0.0, 0.0)

    def test_plan_view_gives_the_horizontal_plane(self):
        pt, n = first_point_work_plane(_fw(0, 0, -1), C)
        assert (n.x(), n.y()) == (0.0, 0.0) and abs(n.z()) == 1.0
        assert pt == C

    def test_oblique_orbit_view_returns_none(self):
        # a 3/4 view is not axis-aligned → keep the ground fallback
        assert first_point_work_plane(_fw(1, 1, 1), C) is None
        assert first_point_work_plane(_fw(0.6, 0.6, 0.5), C) is None

    def test_near_axis_still_counts(self):
        # a few degrees off front still reads as the frontal plane
        assert first_point_work_plane(_fw(0.05, -0.998, 0.03), C) is not None

    def test_degenerate_forward_is_none(self):
        assert first_point_work_plane(QVector3D(0, 0, 0), C) is None
