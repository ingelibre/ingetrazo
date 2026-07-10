# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Georef import (Track G): KML + GeoJSON parsing to (lat, lon) features.
Pure — no GUI, no network."""
from __future__ import annotations

from georef.geoimport import parse_geojson, parse_kml

# ---- KML ------------------------------------------------------------------------

KML_LINE = """<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>Road A</name>
    <LineString><coordinates>
      -71.9785,-13.5170,0 -71.9700,-13.5100,0 -71.9600,-13.5050,0
    </coordinates></LineString>
  </Placemark>
</Document></kml>"""

KML_POLY = """<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>Lot 1</name>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>
      -71.98,-13.52 -71.97,-13.52 -71.97,-13.51 -71.98,-13.51 -71.98,-13.52
    </coordinates></LinearRing></outerBoundaryIs></Polygon>
  </Placemark>
</Document></kml>"""


def test_kml_linestring():
    feats = parse_kml(KML_LINE)
    assert len(feats) == 1
    f = feats[0]
    assert f.name == "Road A" and not f.closed
    assert len(f.points) == 3
    # (lat, lon) order — first point.
    assert abs(f.points[0][0] - (-13.5170)) < 1e-6
    assert abs(f.points[0][1] - (-71.9785)) < 1e-6


def test_kml_polygon_closed_and_dedup():
    feats = parse_kml(KML_POLY)
    assert len(feats) == 1
    f = feats[0]
    assert f.closed and f.name == "Lot 1"
    assert len(f.points) == 4       # 5 coords, closing dup dropped


def test_kml_malformed_returns_empty():
    assert parse_kml("<not really kml") == []


# ---- GeoJSON --------------------------------------------------------------------

def test_geojson_linestring_feature():
    data = """{"type":"FeatureCollection","features":[
      {"type":"Feature","properties":{"name":"Canal 3"},
       "geometry":{"type":"LineString",
         "coordinates":[[-71.98,-13.51],[-71.97,-13.50],[-71.96,-13.49]]}}]}"""
    feats = parse_geojson(data)
    assert len(feats) == 1
    assert feats[0].name == "Canal 3" and not feats[0].closed
    assert abs(feats[0].points[0][0] - (-13.51)) < 1e-9   # lat
    assert abs(feats[0].points[0][1] - (-71.98)) < 1e-9   # lon


def test_geojson_polygon_closed_dedup():
    data = """{"type":"Feature","properties":{},"geometry":{"type":"Polygon",
      "coordinates":[[[-71.98,-13.52],[-71.97,-13.52],[-71.97,-13.51],[-71.98,-13.52]]]}}"""
    feats = parse_geojson(data)
    assert len(feats) == 1 and feats[0].closed
    assert len(feats[0].points) == 3    # closing dup dropped


def test_geojson_multilinestring():
    data = """{"type":"MultiLineString",
      "coordinates":[[[-71.9,-13.5],[-71.8,-13.4]],[[-71.7,-13.3],[-71.6,-13.2]]]}"""
    feats = parse_geojson(data)
    assert len(feats) == 2 and all(not f.closed for f in feats)


def test_geojson_malformed_returns_empty():
    assert parse_geojson("{ not json") == []
