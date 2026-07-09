# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scene datum (Track G, G0): UTM zone/hemisphere, geodetic ↔ local-metre
round-trip precision, and .igz persistence."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.scene import Scene
from formats import igz
from georef.datum import SceneDatum, utm_forward, utm_inverse, zone_for_lon


# Anchor points spanning hemispheres / zones.
LIMA = (-12.0464, -77.0428)        # Peru, zone 18S
QUITO = (-0.1807, -78.4678)        # Ecuador, near the equator, zone 17S
OSLO = (59.9139, 10.7522)          # Norway, zone 32N


# ---- Zone / hemisphere ---------------------------------------------------------

def test_zone_for_lon():
    assert zone_for_lon(-77.0428) == 18   # Lima
    assert zone_for_lon(-78.4678) == 17   # Quito
    assert zone_for_lon(10.7522) == 32    # Oslo
    assert zone_for_lon(-180) == 1
    assert zone_for_lon(179.9) == 60


def test_datum_derives_zone_and_hemisphere():
    d = SceneDatum(*LIMA)
    assert d.zone == 18
    assert d.hemisphere == "S"
    assert d.northern is False

    n = SceneDatum(*OSLO)
    assert n.zone == 32
    assert n.hemisphere == "N"
    assert n.northern is True


# ---- UTM forward matches surveyed values --------------------------------------

def test_utm_forward_lima():
    # Lima's UTM 18S is roughly (280 km E, 8 666 km N) — sanity, not sub-mm.
    east, north = utm_forward(*LIMA, zone=18)
    assert abs(east - 279_000) < 3000
    assert abs(north - 8_666_000) < 3000


def test_utm_forward_inverse_round_trip():
    for lat, lon in (LIMA, QUITO, OSLO):
        zone = zone_for_lon(lon)
        east, north = utm_forward(lat, lon, zone)
        rlat, rlon = utm_inverse(east, north, zone, northern=lat >= 0)
        # ~1e-8 deg ≈ 1 mm — the series-expansion floor; the metric round-trip
        # (test_round_trip_under_1mm_city_scale) is the real DoD.
        assert abs(rlat - lat) < 1e-8
        assert abs(rlon - lon) < 1e-8


# ---- The G0 DoD: geodetic ↔ local round-trip under 1 mm at city scale ---------

def _offset_geodetic(lat, lon, d_north_m, d_east_m):
    """Nudge a geodetic point by a metric offset (small-angle approximation)."""
    dlat = d_north_m / 111_320.0
    dlon = d_east_m / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def test_anchor_maps_to_local_origin():
    d = SceneDatum(*LIMA)
    p = d.geodetic_to_local(*LIMA)
    assert p.length() < 1e-6   # the anchor is the local origin


def test_round_trip_under_1mm_city_scale():
    # Sweep points up to ~10 km around each anchor (well past a city).
    for anchor in (LIMA, QUITO, OSLO):
        d = SceneDatum(*anchor)
        for dn in (-10_000, -100, 0, 250, 10_000):
            for de in (-10_000, -50, 0, 500, 10_000):
                lat, lon = _offset_geodetic(anchor[0], anchor[1], dn, de)
                local = d.geodetic_to_local(lat, lon, alt=37.5)
                rlat, rlon, ralt = d.local_to_geodetic(local)
                back = d.geodetic_to_local(rlat, rlon, ralt)
                # Round-trip error, measured in metres in the local frame.
                assert (local - back).length() < 1e-3
                assert abs(ralt - 37.5) < 1e-6


def test_local_frame_axes_orientation():
    d = SceneDatum(*LIMA)
    lat, lon = _offset_geodetic(*LIMA, d_north_m=1000, d_east_m=0)
    p = d.geodetic_to_local(lat, lon)
    assert p.y() > 900          # going north grows +Y
    assert abs(p.x()) < 50      # ~no easting change
    lat2, lon2 = _offset_geodetic(*LIMA, d_north_m=0, d_east_m=1000)
    q = d.geodetic_to_local(lat2, lon2)
    assert q.x() > 900          # going east grows +X
    assert abs(q.y()) < 50


def test_altitude_is_relative_to_datum():
    d = SceneDatum(*LIMA, alt=100.0)
    p = d.geodetic_to_local(*LIMA, alt=142.0)
    assert abs(p.z() - 42.0) < 1e-6


# ---- Serialisation -------------------------------------------------------------

def test_datum_dict_round_trip():
    d = SceneDatum(-12.0464, -77.0428, 154.0)
    r = SceneDatum.from_dict(d.to_dict())
    assert (r.lat, r.lon, r.alt) == (d.lat, d.lon, d.alt)
    assert r.zone == d.zone and r.northern == d.northern


def test_datum_survives_igz_round_trip(tmp_path):
    scene = Scene()
    scene.add_edge(QVector3D(0, 0, 0), QVector3D(1, 0, 0))
    scene.georef = SceneDatum(-12.0464, -77.0428, 154.0)
    path = tmp_path / "geo.igz"
    igz.save_scene(scene, path)

    loaded = Scene()
    igz.load_into(loaded, path)
    assert loaded.georef is not None
    assert abs(loaded.georef.lat - (-12.0464)) < 1e-12
    assert abs(loaded.georef.lon - (-77.0428)) < 1e-12
    assert abs(loaded.georef.alt - 154.0) < 1e-12


def test_ungeoreferenced_document_has_no_georef(tmp_path):
    scene = Scene()
    scene.add_edge(QVector3D(0, 0, 0), QVector3D(1, 0, 0))
    path = tmp_path / "plain.igz"
    igz.save_scene(scene, path)
    assert '"georef"' not in path.read_text()   # terse: no block written

    loaded = Scene()
    igz.load_into(loaded, path)
    assert loaded.georef is None


def test_clear_resets_datum():
    scene = Scene()
    scene.georef = SceneDatum(*LIMA)
    scene.clear()
    assert scene.georef is None
