# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The fixed sample the viewport bakes both ways once per session before
the Rust engine bakes tool preview faces (``Viewport._preview_native_ok``):
convex, concave, holed, thin, tiny and degenerate faces facing every way —
straight up and down, a hair off the vertical, slanted — under a colour, a
planar map, a turned map and a fitted ``uvw``; and the sweeps a push shows
(a round pillar, a holed slab, a slanted ring)."""
from __future__ import annotations

import math
import random

from PySide6.QtGui import QVector3D as V

from core.geometry import Face

#: The maps and colours of the sample (two maps share a path: one run).
MATERIALS = (
    None,
    {"color": (0.8, 0.3, 0.2)},
    {"color": [1.0, 1.0, 1.0, 1.0]},
    {"texture": {"path": "/probe/a.png", "sw": 0.5, "sh": 0.25}},
    {"texture": {"path": "/probe/a.png", "sw": 1.3, "sh": 0.7, "rot": 30.0,
                 "planar": True}},
    {"texture": {"path": "/probe/b.png", "rot": -112.5}},
    {"texture": {"path": "/probe/b.png",
                 "uvw": [0.31, -0.2, 0.05, 0.125, 0.0, 0.7, -0.3, -2.5]}},
    {"texture": {"path": "/probe/c.png", "sw": 0, "sh": None, "rot": 0}},
)


def _axes(rng, kind):
    """Two in-plane axes of a face facing ``kind``."""
    if kind == "up":
        return V(1, 0, 0), V(0, 1, 0)
    if kind == "down":
        return V(0, 1, 0), V(1, 0, 0)
    if kind == "hair":                        # ~1e-3 off the vertical
        t = rng.choice([9.9e-4, 1.0e-3, 1.0002e-3, 2e-3, 5e-4])
        return V(1, 0, 0), V(0, math.cos(t), math.sin(t))
    ax = V(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
    u = V.crossProduct(ax, V(0.3, 0.1, 1)).normalized()
    return u, V.crossProduct(ax, u).normalized()


def _attrs(rng):
    m = rng.choice(MATERIALS)
    if m is None:
        return None
    out = dict(m)
    if "texture" in out:
        out["texture"] = dict(out["texture"])
    return out


def probe_faces(seed: int = 20261119, count: int = 48) -> list:
    """``count`` preview faces of every kind, with their materials."""
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        kind = rng.choice(["quad", "star", "holed", "thin", "tiny", "line",
                           "empty", "ngon"])
        o = V(rng.uniform(-50, 50), rng.uniform(-50, 50), rng.uniform(-5, 5))
        u, w = _axes(rng, rng.choice(["up", "down", "hair", "any", "any"]))
        attrs = _attrs(rng)
        if kind == "quad":
            a, b = rng.uniform(0.1, 3), rng.uniform(0.1, 3)
            pts, holes = [o, o + u * a, o + u * a + w * b, o + w * b], []
        elif kind in ("star", "holed", "ngon"):
            n = rng.randint(5, 40)
            r = rng.uniform(0.2, 4)
            pts = [o + u * (r * math.cos(2 * math.pi * k / n)
                            * (1.0 if k % 2 or kind != "star" else 0.45))
                   + w * (r * math.sin(2 * math.pi * k / n)
                          * (1.0 if k % 2 or kind != "star" else 0.45))
                   for k in range(n)]
            holes = ([[o + u * (0.3 * r * math.cos(-2 * math.pi * k / 6))
                       + w * (0.3 * r * math.sin(-2 * math.pi * k / 6))
                       for k in range(6)], [o, o + u * 0.01]]
                     if kind == "holed" else [])
        elif kind == "thin":
            pts, holes = [o, o + u * 3, o + u * 3 + w * 1e-7, o + w * 1e-7], []
        elif kind == "tiny":
            e = rng.choice([1e-6, 3e-5, 1e-4])
            pts, holes = [o, o + u * e, o + w * e], []
        elif kind == "line":
            pts, holes = [o, o + u], []
        else:
            pts, holes = [], []
        out.append(Face(pts, holes, attrs=attrs))
    return out


def _sweep(rings, off, attrs, wall):
    """``tools.pushpull._sweep_faces`` of ``rings`` by ``off``, as plain
    faces: the cap with its holes, then the walls ring by ring."""
    moved = [[p + off for p in r] for r in rings]
    out = [Face(moved[0], moved[1:], attrs=attrs)]
    for low, high in zip(rings, moved):
        count = len(low)
        for i in range(count):
            j = (i + 1) % count
            out.append(Face([low[i], low[j], high[j], high[i]], attrs=wall))
    return out


def probe_sweeps(seed: int = 20261119):
    """``(faces, sweeps)``: the faces a push's overlay builds and the
    ``(rings, off, cap_attrs, wall_attrs)`` they are built from."""
    rng = random.Random(seed + 1)
    sweeps = []
    # A round pillar of 100 sides, a holed slab, a slanted ring.
    c = V(12.25, -3.5, 0.0)
    pillar = [c + V(0.35 * math.cos(2 * math.pi * k / 100),
                    0.35 * math.sin(2 * math.pi * k / 100), 0.0)
              for k in range(100)]
    slab = [V(0, 0, 1), V(4, 0, 1), V(4, 3, 1), V(0, 3, 1)]
    hole = [V(1, 1, 1), V(1, 2, 1), V(2, 2, 1), V(2, 1, 1)]
    u, w = _axes(rng, "any")
    o = V(-7.0, 8.0, 2.0)
    ring = [o + u * math.cos(2 * math.pi * k / 24) + w * math.sin(2 * math.pi * k / 24)
            for k in range(24)]
    n = V.crossProduct(u, w).normalized()
    for rings, nrm, ds in (([pillar], V(0, 0, 1), (2.75,)),
                           ([slab, hole], V(0, 0, -1), (-0.4, 1e-4)),
                           ([ring], n, (2.75, -0.4))):
        for d in ds:
            attrs = _attrs(rng)
            wall = None
            if attrs:
                wall = {k: v for k, v in attrs.items()}
                if "texture" in wall:
                    wall["texture"] = {**{k: v for k, v in
                                          wall["texture"].items()
                                          if k != "uvw"}, "planar": True}
            sweeps.append(([list(r) for r in rings], nrm * d, attrs, wall))
    faces = []
    for rings, off, attrs, wall in sweeps:
        faces += _sweep(rings, off, attrs, wall)
    return faces, sweeps
