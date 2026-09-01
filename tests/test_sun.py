# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The NOAA solar position math (core/sun.py), pinned to astronomy.

Reference facts that do not depend on our implementation: at an equinox the
sun stands over the equator (zenith at solar noon, rising due east, setting
due west), and at the June solstice it stands over the Tropic of Cancer —
seen from Arequipa (16.4°S) that noon sun is to the NORTH at about
90° − (16.4° + 23.44°) elevation. Tolerances are loose enough to survive
the ±0.1° class of the algorithm and the few minutes between clock noon
and solar noon.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.sun import (
    DEFAULT_LAT,
    DEFAULT_LON,
    ShadowSettings,
    default_utc_offset,
    solar_position,
    sun_direction,
)


def test_equinox_noon_sun_is_overhead_at_the_equator():
    elev, _az = solar_position(0.0, 0.0,
                               datetime(2026, 3, 20, 12, 7))
    assert elev > 87.0


def test_equinox_sun_rises_due_east_and_sets_due_west():
    elev, az = solar_position(0.0, 0.0, datetime(2026, 3, 20, 6, 8))
    assert abs(elev) < 2.0
    assert abs(az - 90.0) < 3.0
    elev, az = solar_position(0.0, 0.0, datetime(2026, 3, 20, 17, 0))
    assert 10.0 < elev < 20.0          # ~75° hour angle at the equator
    assert abs(az - 270.0) < 5.0


def test_winter_noon_in_arequipa_sun_is_north():
    """June solstice, local noon (UTC-5): from 16.4°S the sun leans north
    at ≈ 90° − (16.41° + 23.44°) ≈ 50° elevation."""
    elev, az = solar_position(DEFAULT_LAT, DEFAULT_LON,
                              datetime(2026, 6, 21, 17, 0))
    assert 48.0 < elev < 52.5
    assert az < 30.0 or az > 330.0     # north side

    d = sun_direction(DEFAULT_LAT, DEFAULT_LON,
                      datetime(2026, 6, 21, 17, 0))
    assert d is not None
    assert d[1] > 0.0                  # toward the north (+Y)
    assert d[2] > 0.7                  # well above the horizon


def test_night_has_no_sun_direction():
    assert sun_direction(DEFAULT_LAT, DEFAULT_LON,
                         datetime(2026, 6, 21, 7, 0)) is None  # 02:00 local


def test_daylight_window_follows_site_and_zone():
    """The time slider's bounds: daylight for the LOCAL clock. In Arequipa
    at the equinox with the natural zone (UTC−5) the sun runs roughly
    06:00→18:00; forcing UTC−10 shifts the same daylight five clock hours
    earlier — odd-looking and correct, which is exactly what SketchUp's
    slider shows for a mismatched zone."""
    from core.sun import daylight_minutes
    rng = daylight_minutes(DEFAULT_LAT, DEFAULT_LON, 3, 21)
    assert rng is not None
    first, last = rng
    assert 320 <= first <= 380                # ~05:20–06:20
    assert 1050 <= last <= 1105               # ~17:30–18:25

    shifted = daylight_minutes(DEFAULT_LAT, DEFAULT_LON, 3, 21,
                               utc_offset=-10)
    assert shifted is not None
    assert abs((first - shifted[0]) - 300) <= 10   # 5 h earlier
    # Polar night: no sun, no window. Midnight sun: the whole day.
    assert daylight_minutes(80.0, 0.0, 12, 21) is None
    assert daylight_minutes(80.0, 0.0, 6, 21) == (0, 1439)


def test_shadow_settings_round_trip_and_utc_offset():
    assert default_utc_offset(DEFAULT_LON) == -5   # Peru
    assert default_utc_offset(0.3) == 0

    s = ShadowSettings(enabled=True, month=6, day=21, hour=15, minute=30,
                       darkness=0.4)
    restored = ShadowSettings.from_dict(s.to_dict())
    assert restored == s
    # Local 12:00 at a UTC-5 site is 17:00 UTC.
    assert ShadowSettings(hour=12).when_utc(DEFAULT_LON).hour == 17

    # Broken values fall back to defaults instead of exploding.
    bad = ShadowSettings.from_dict({"month": 40, "hour": "x",
                                    "darkness": 9})
    assert bad.month == 3 and bad.hour == 12 and bad.darkness == 1.0
