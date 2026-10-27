# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The interactive Iso command lands on the isometric view NEAREST the
camera, not always the single classic corner.

The static preset stays put — sheets and scripts that ask for ``"iso"``
through ``set_view`` still get the same corner every time.
"""
from __future__ import annotations

import math

import pytest

from core.camera import OrbitCamera


@pytest.mark.parametrize(
    ("yaw_deg", "pitch_deg", "expected_yaw", "expected_pitch"),
    [
        (-45.0, 30.0, -45.0, 30.0),    # the classic corner, unchanged
        (10.0, 20.0, 45.0, 30.0),      # nearest diagonal, above
        (-10.0, 20.0, -45.0, 30.0),
        (100.0, 20.0, 135.0, 30.0),
        (200.0, 20.0, 225.0, 30.0),
        (10.0, -20.0, 45.0, -30.0),    # nearest diagonal, below
        (-10.0, -20.0, -45.0, -30.0),
        (0.0, 30.0, -45.0, 30.0),      # the tie at 0° favours the classic
    ],
)
def test_snap_iso_lands_on_the_nearest_isometric(
        yaw_deg, pitch_deg, expected_yaw, expected_pitch):
    c = OrbitCamera()
    c.yaw = math.radians(yaw_deg)
    c.pitch = math.radians(pitch_deg)
    c.snap_iso()
    assert c.yaw == pytest.approx(math.radians(expected_yaw), abs=1e-9)
    assert c.pitch == pytest.approx(math.radians(expected_pitch), abs=1e-9)


def test_set_view_iso_stays_the_static_corner():
    """Sheets and scripts call ``set_view("iso")`` and expect the same
    corner every time, whatever the camera did before."""
    c = OrbitCamera()
    c.yaw = math.radians(120.0)
    c.pitch = math.radians(-50.0)
    c.set_view("iso")
    assert c.yaw == pytest.approx(math.radians(-45.0), abs=1e-9)
    assert c.pitch == pytest.approx(math.radians(30.0), abs=1e-9)
