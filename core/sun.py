# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The real sun — position from geography and clock, SketchUp's Shadows.

The model already carries a geographic datum (lat/lon, the georef anchor),
so shadows here are not a mood light: elevation and azimuth come from the
NOAA solar position equations (the "General Solar Position Calculations"
spreadsheet algorithm, accurate to well under 0.1° for 1900-2100), which
turns the shadow study into a deliverable — sun at THIS site, THIS date,
THIS hour.

Conventions: the scene is X=east, Y=north, Z=up (see core/camera.py);
azimuth is degrees clockwise from north, elevation degrees above the
horizon. ``ShadowSettings`` stores LOCAL clock time plus a UTC offset in
hours; the default offset is the solar-time approximation round(lon/15) —
right for Peru (-71.5° → -5) and every zone that follows its meridian, and
editable where politics disagree with the sun.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

#: Fallback site when the model has no geographic datum yet: Arequipa.
DEFAULT_LAT = -16.409
DEFAULT_LON = -71.537


def solar_position(lat: float, lon: float,
                   when_utc: datetime) -> tuple[float, float]:
    """``(elevation_deg, azimuth_deg)`` of the sun — NOAA equations.

    ``when_utc`` must be an aware or naive datetime already expressed in
    UTC. Azimuth is clockwise from north; elevation is geometric (no
    atmospheric refraction — at shadow-casting elevations it is < 0.15°,
    invisible in a drawing).
    """
    # Julian day from the proleptic Gregorian calendar, then Julian century.
    y, m = when_utc.year, when_utc.month
    d = (when_utc.day + when_utc.hour / 24.0 + when_utc.minute / 1440.0
         + when_utc.second / 86400.0)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    jd = (math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1))
          + d + b - 1524.5)
    t = (jd - 2451545.0) / 36525.0

    # Geometric mean longitude and anomaly of the sun (degrees).
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
    m_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m_anom)
    center = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
              + math.sin(3 * mr) * 0.000289)
    true_long = l0 + center
    omega = 125.04 - 1934.136 * t
    app_long = (true_long - 0.00569
                - 0.00478 * math.sin(math.radians(omega)))

    # Obliquity of the ecliptic, corrected.
    obliq0 = (23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059
              - t * 0.001813))) / 60.0) / 60.0)
    obliq = obliq0 + 0.00256 * math.cos(math.radians(omega))

    # Declination and the equation of time (minutes).
    decl = math.degrees(math.asin(
        math.sin(math.radians(obliq)) * math.sin(math.radians(app_long))))
    var_y = math.tan(math.radians(obliq / 2.0)) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        var_y * math.sin(2 * l0r)
        - 2.0 * ecc * math.sin(mr)
        + 4.0 * ecc * var_y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * var_y * var_y * math.sin(4 * l0r)
        - 1.25 * ecc * ecc * math.sin(2 * mr))

    # True solar time (minutes) → hour angle (degrees; solar noon = 0).
    minutes = (when_utc.hour * 60.0 + when_utc.minute
               + when_utc.second / 60.0)
    tst = (minutes + eot + 4.0 * lon) % 1440.0
    ha = tst / 4.0 - 180.0
    if ha < -180.0:
        ha += 360.0

    latr = math.radians(lat)
    declr = math.radians(decl)
    har = math.radians(ha)
    cos_zen = (math.sin(latr) * math.sin(declr)
               + math.cos(latr) * math.cos(declr) * math.cos(har))
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zenith = math.degrees(math.acos(cos_zen))
    elevation = 90.0 - zenith

    # Azimuth, clockwise from north.
    denom = math.cos(latr) * math.sin(math.radians(zenith))
    if abs(denom) < 1e-12:
        azimuth = 180.0            # sun at the zenith: any azimuth will do
    else:
        cos_az = ((math.sin(latr) * cos_zen - math.sin(declr)) / denom)
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.degrees(math.acos(cos_az))
        # NOAA: afternoon (ha > 0) → az + 180; morning → 540 − az.
        azimuth = (az + 180.0) % 360.0 if ha > 0 else (540.0 - az) % 360.0
    return elevation, azimuth


def sun_direction(lat: float, lon: float,
                  when_utc: datetime) -> tuple[float, float, float] | None:
    """Unit vector pointing FROM the scene TOWARD the sun, in scene axes
    (X=east, Y=north, Z=up) — or ``None`` when the sun is below the horizon
    (night: no shadows to draw)."""
    elevation, azimuth = solar_position(lat, lon, when_utc)
    if elevation <= 0.0:
        return None
    er = math.radians(elevation)
    ar = math.radians(azimuth)
    return (math.cos(er) * math.sin(ar),      # east
            math.cos(er) * math.cos(ar),      # north
            math.sin(er))                     # up


def default_utc_offset(lon: float) -> int:
    """Solar-time approximation of the zone: ``round(lon / 15)`` hours."""
    return int(round(lon / 15.0))


def daylight_minutes(lat: float, lon: float, month: int, day: int,
                     utc_offset: int | None = None, year: int = 2026,
                     step: int = 5) -> tuple[int, int] | None:
    """First and last minute of the LOCAL clock day with the sun above the
    horizon, or ``None`` when it never rises (polar night). The clock is
    whatever ``utc_offset`` says — a deliberately wrong zone shifts daylight
    to odd hours, which is exactly what it means (SketchUp's time slider
    behaves the same way). Sampled every ``step`` minutes: ±5 min is well
    under what a shadow can show."""
    off = utc_offset if utc_offset is not None else default_utc_offset(lon)
    tz = timezone(timedelta(hours=off))
    first = last = None
    for m in range(0, 1440, step):
        local = datetime(year, month, day, m // 60, m % 60, tzinfo=tz)
        elev, _az = solar_position(lat, lon,
                                   local.astimezone(timezone.utc))
        if elev > 0.0:
            if first is None:
                first = m
            last = m
    if first is None:
        return None
    return first, min(1439, last + step - 1)


@dataclass
class ShadowSettings:
    """Document data (lives on the Scene, saved in the .igz): whether the
    sun draws shadows, and the local date/time it stands at. ``utc_offset``
    ``None`` means "derive from the site's longitude"."""
    enabled: bool = False
    month: int = 3
    day: int = 21
    hour: int = 12
    minute: int = 0
    darkness: float = 0.55            # shadowed-area brightness multiplier
    utc_offset: int | None = None

    def when_utc(self, lon: float, year: int = 2026) -> datetime:
        off = (self.utc_offset if self.utc_offset is not None
               else default_utc_offset(lon))
        local = datetime(year, self.month, self.day, self.hour, self.minute,
                         tzinfo=timezone(timedelta(hours=off)))
        return local.astimezone(timezone.utc)

    def to_dict(self) -> dict:
        d = {"enabled": self.enabled, "month": self.month, "day": self.day,
             "hour": self.hour, "minute": self.minute,
             "darkness": self.darkness}
        if self.utc_offset is not None:
            d["utc_offset"] = self.utc_offset
        return d

    @classmethod
    def from_dict(cls, raw: dict) -> "ShadowSettings":
        d = cls()
        off = raw.get("utc_offset")

        def _int(key, lo, hi, default):
            try:
                v = int(raw.get(key, default))
            except (TypeError, ValueError):
                return default
            return v if lo <= v <= hi else default

        try:
            dark = float(raw.get("darkness", d.darkness))
        except (TypeError, ValueError):
            dark = d.darkness
        return cls(
            enabled=bool(raw.get("enabled", d.enabled)),
            month=_int("month", 1, 12, d.month),
            day=_int("day", 1, 31, d.day),
            hour=_int("hour", 0, 23, d.hour),
            minute=_int("minute", 0, 59, d.minute),
            darkness=max(0.0, min(1.0, dark)),
            utc_offset=int(off) if off is not None else None,
        )
