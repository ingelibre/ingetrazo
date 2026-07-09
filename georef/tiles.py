# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Slippy-map tiles — the satellite/street base layer (Track G, G1).

Standard Web-Mercator XYZ tiles (the ``z/x/y`` scheme every web map uses), so
IngeTrazo is provider-agnostic: pick a legal preset or paste any XYZ template.
This module is the **pure, headless core** — slippy math, tile sources, URL
templating and an on-disk LRU cache. It imports only ``math`` + stdlib, so it
tests without a GUI or network. The async download lives in :mod:`~georef.tiles`
``TileFetcher`` (needs Qt-net); the GL quads live in the viewport.

Legal note (invariant #5): the shipped presets are all licensed for this use
(Esri World Imagery, OSM, EOX Sentinel-2). A **custom XYZ** template lets the
user paste any URL — including Google's — but IngeTrazo never ships Google's as
a default. The risk of a pasted URL is the user's, exactly like QGIS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


# ---- Slippy-map math (Web Mercator, EPSG:3857) --------------------------------

def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[float, float]:
    """Geodetic (degrees) → fractional tile coordinates at ``zoom``.

    The integer parts are the tile indices; the fractions locate the point
    inside the tile. Latitude is clamped to the Web-Mercator limit (~85.0511°).
    """
    lat_deg = max(-85.05112878, min(85.05112878, lat_deg))
    lat_rad = math.radians(lat_deg)
    n = 2 ** zoom
    xtile = (lon_deg + 180.0) / 360.0 * n
    ytile = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return xtile, ytile


def num2deg(xtile: float, ytile: float, zoom: int) -> tuple[float, float]:
    """Fractional tile coordinates → geodetic ``(lat, lon)`` in degrees.

    For integer ``xtile``/``ytile`` this is the tile's **north-west corner**;
    the south-east corner is ``num2deg(x + 1, y + 1, zoom)``.
    """
    n = 2 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    return math.degrees(lat_rad), lon_deg


def tile_bbox(x: int, y: int, zoom: int) -> tuple[float, float, float, float]:
    """Geodetic bounding box of tile ``(x, y, zoom)``.

    Returns ``(lat_south, lon_west, lat_north, lon_east)``.
    """
    lat_n, lon_w = num2deg(x, y, zoom)
    lat_s, lon_e = num2deg(x + 1, y + 1, zoom)
    return lat_s, lon_w, lat_n, lon_e


def tiles_covering(lat_s: float, lon_w: float, lat_n: float, lon_e: float,
                   zoom: int) -> list[tuple[int, int]]:
    """Every tile index ``(x, y)`` that overlaps the geodetic bbox at ``zoom``."""
    x0, y0 = deg2num(lat_n, lon_w, zoom)   # NW corner → min x, min y
    x1, y1 = deg2num(lat_s, lon_e, zoom)   # SE corner → max x, max y
    n = 2 ** zoom
    xa, xb = int(math.floor(min(x0, x1))), int(math.floor(max(x0, x1)))
    ya, yb = int(math.floor(min(y0, y1))), int(math.floor(max(y0, y1)))
    out = []
    for tx in range(xa, xb + 1):
        for ty in range(ya, yb + 1):
            if 0 <= tx < n and 0 <= ty < n:
                out.append((tx, ty))
    return out


# ---- Tile sources -------------------------------------------------------------

@dataclass(frozen=True)
class TileSource:
    """A slippy-map provider: an ``{z}/{x}/{y}`` URL template plus metadata.

    ``url_template`` may use ``{z}``, ``{x}``, ``{y}`` in any order (ArcGIS
    serves ``{z}/{y}/{x}``) and an optional ``{s}`` subdomain placeholder that
    rotates through ``subdomains``.
    """

    id: str
    name: str
    url_template: str
    max_zoom: int = 19
    attribution: str = ""
    subdomains: tuple[str, ...] = field(default_factory=tuple)
    tile_size: int = 256

    def url(self, x: int, y: int, z: int) -> str:
        s = self.subdomains[(x + y) % len(self.subdomains)] if self.subdomains else ""
        return (self.url_template
                .replace("{s}", s)
                .replace("{z}", str(z))
                .replace("{x}", str(x))
                .replace("{y}", str(y)))


# Shipped presets — all licensed for this use. NEVER add Google here; it goes
# through the custom-XYZ field where the user assumes the risk (invariant #5).
PRESETS: dict[str, TileSource] = {
    "esri_imagery": TileSource(
        id="esri_imagery",
        name="Esri World Imagery (satélite)",
        url_template="https://server.arcgisonline.com/ArcGIS/rest/services/"
                     "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        max_zoom=19,
        attribution="Esri, Maxar, Earthstar Geographics, and the GIS community",
    ),
    "s2cloudless": TileSource(
        id="s2cloudless",
        name="Sentinel-2 cloudless (EOX)",
        url_template="https://tiles.maps.eox.at/wmts/1.0.0/"
                     "s2cloudless-2020_3857/default/GoogleMapsCompatible/"
                     "{z}/{y}/{x}.jpg",
        max_zoom=17,
        attribution="Sentinel-2 cloudless — https://s2maps.eu by EOX IT Services "
                    "GmbH (Contains modified Copernicus Sentinel data)",
    ),
    "osm": TileSource(
        id="osm",
        name="OpenStreetMap (calles)",
        url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        max_zoom=19,
        attribution="© OpenStreetMap contributors",
    ),
}

DEFAULT_SOURCE_ID = "esri_imagery"


def custom_source(url_template: str, max_zoom: int = 19) -> TileSource:
    """Build a user-pasted XYZ source. Risk is the user's (invariant #5)."""
    return TileSource(
        id="custom",
        name="XYZ personalizado",
        url_template=url_template,
        max_zoom=max_zoom,
        attribution="Fuente personalizada (definida por el usuario)",
    )


# ---- Disk cache (LRU) ---------------------------------------------------------

class TileCache:
    """On-disk tile cache, ``root/<source_id>/<z>/<x>/<y>``, LRU by budget.

    Keeps tiles across sessions so a previously-viewed area opens offline. The
    cache is deliberately dumb bytes-in/bytes-out — decoding to an image is the
    caller's job (keeps this module GUI-free and testable).
    """

    def __init__(self, root: Path, max_bytes: int = 256 * 1024 * 1024) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, source_id: str, x: int, y: int, z: int) -> Path:
        return self.root / source_id / str(z) / str(x) / str(y)

    def get(self, source_id: str, x: int, y: int, z: int) -> bytes | None:
        p = self.path_for(source_id, x, y, z)
        if p.exists():
            try:
                data = p.read_bytes()
            except OSError:
                return None
            self._touch(p)
            return data
        return None

    def put(self, source_id: str, x: int, y: int, z: int, data: bytes) -> None:
        if not data:
            return
        p = self.path_for(source_id, x, y, z)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self._evict_if_needed()

    def _touch(self, p: Path) -> None:
        # Bump mtime so LRU eviction treats a just-read tile as fresh. Best
        # effort — a failed touch only skews eviction order, never correctness.
        try:
            import os
            st = p.stat()
            os.utime(p, (st.st_atime, st.st_mtime + 1))
        except OSError:
            pass

    def _evict_if_needed(self) -> None:
        files = [f for f in self.root.rglob("*") if f.is_file()]
        total = sum(f.stat().st_size for f in files)
        if total <= self.max_bytes:
            return
        # Oldest-first (smallest mtime) until back under budget.
        for f in sorted(files, key=lambda f: f.stat().st_mtime):
            if total <= self.max_bytes:
                break
            try:
                total -= f.stat().st_size
                f.unlink()
            except OSError:
                pass
