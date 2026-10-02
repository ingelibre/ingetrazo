# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Synthetic benchmark documents: the same city at four sizes.

The release check measures one private document (the Plaza Yanque); this
builds PUBLIC, deterministic ones that anybody can regenerate, at sizes that
show how a cost grows with the model — the "it gets out of hand as the
model grows" complaint needs more than one point on the curve.

A city block is what a push/pull modeller is used for: buildings (one group
each, world coordinates) whose walls carry recessed windows — faces with
holes, the earcut path — on every floor, a round column (a curved surface,
soft edges), and trees as COMPONENT copies sharing one prototype mesh (the
instancing path). Same seed, same document, every run.

    python scripts/bench_models.py S M L XL      # -> benchmarks/models/*.igz (git-ignored)

Sizes (buildings / tree copies / faces drawn / .igz, measured):

    S    3×3 /    30 /     8 k /   5 MB
    M    8×8 /   250 /    73 k /  45 MB
    L   16×16 / 1200 /   331 k / 187 MB
    XL  28×28 / 4000 / 1 075 k / 579 MB
"""
from __future__ import annotations

import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats.igz import save_scene  # noqa: E402

SIZES = {"S": (3, 30), "M": (8, 250), "L": (16, 1200), "XL": (28, 4000)}
OUT_DIR = Path(__file__).resolve().parents[1] / "benchmarks" / "models"

P = QVector3D
UP = P(0.0, 0.0, 1.0)
WALL = (0.86, 0.84, 0.80)
GLASS = (0.55, 0.72, 0.82)
BARK = (0.42, 0.30, 0.20)
LEAF = (0.30, 0.52, 0.28)
STONE = (0.62, 0.60, 0.58)


def _face(mesh, loop, holes=None, color=None):
    f = mesh.add_face(loop, holes)
    if color is not None and f is not None:
        f.attrs["color"] = color
    return f


def _wall(mesh, p, q, z0, h, windows, rng):
    """One floor of the wall p→q (outward = (q-p) × up) with ``windows``
    recessed openings: the wall face with holes, four reveals and the
    glass at the back of each."""
    u = q - p
    length = u.length()
    u = u / length
    n = QVector3D.crossProduct(u, UP)
    depth = 0.18
    holes = []
    ww, wh = min(1.2, length / (windows * 2 + 1)), 1.4
    gap = (length - windows * ww) / (windows + 1)
    for k in range(windows):
        a = gap + k * (ww + gap)
        b = z0 + 0.9
        c0 = p + u * a + UP * (b - p.z())
        c1 = c0 + u * ww
        c2 = c1 + UP * wh
        c3 = c0 + UP * wh
        hole = [c0, c1, c2, c3]
        holes.append(hole[::-1])
        back = [c - n * depth for c in hole]
        for i in range(4):
            j = (i + 1) % 4
            _face(mesh, [hole[i], back[i], back[j], hole[j]], color=STONE)
        _face(mesh, back, color=GLASS)
    pb, qb = p + UP * (z0 - p.z()), q + UP * (z0 - q.z())
    _face(mesh, [pb, qb, qb + UP * h, pb + UP * h], holes, color=WALL)


def _building(x0, y0, w, d, floors, rng):
    mesh = Mesh()
    fh = 3.0
    corners = [P(x0, y0, 0), P(x0 + w, y0, 0), P(x0 + w, y0 + d, 0),
               P(x0, y0 + d, 0)]
    for fl in range(floors):
        for i in range(4):
            p, q = corners[i], corners[(i + 1) % 4]
            win = max(1, int((q - p).length() // 2.6))
            _wall(mesh, p, q, fl * fh, fh, win, rng)
    top = floors * fh
    _face(mesh, [c + UP * top for c in corners], color=STONE)
    _face(mesh, corners[::-1], color=STONE)
    # A round column by the entrance: 32 tall quads + caps.
    cx, cy, r, seg = x0 + w / 2, y0 - 1.2, 0.35, 32
    ring = [P(cx + r * math.cos(2 * math.pi * i / seg),
              cy + r * math.sin(2 * math.pi * i / seg), 0) for i in range(seg)]
    for i in range(seg):
        a, b = ring[i], ring[(i + 1) % seg]
        _face(mesh, [a, b, b + UP * fh, a + UP * fh], color=STONE)
    _face(mesh, [c + UP * fh for c in ring], color=STONE)
    _face(mesh, ring[::-1], color=STONE)
    return Group(mesh, name=f"Building {x0:.0f},{y0:.0f}")


def _tree_proto():
    mesh = Mesh()
    seg, r, th = 12, 0.15, 2.2
    ring = [P(r * math.cos(2 * math.pi * i / seg),
              r * math.sin(2 * math.pi * i / seg), 0) for i in range(seg)]
    for i in range(seg):
        a, b = ring[i], ring[(i + 1) % seg]
        _face(mesh, [a, b, b + UP * th, a + UP * th], color=BARK)
    # Crown: a UV sphere, 16 × 10 — the faceted round shape trees are.
    cz, cr, lon, lat = th + 1.6, 1.8, 16, 10

    def sp(i, j):
        t = math.pi * j / lat
        f = 2 * math.pi * i / lon
        return P(cr * math.sin(t) * math.cos(f), cr * math.sin(t) * math.sin(f),
                 cz + cr * math.cos(t))
    for j in range(lat):
        for i in range(lon):
            a, b = sp(i, j), sp(i + 1, j)
            c, d = sp(i + 1, j + 1), sp(i, j + 1)
            loop = [a, d, c] if j == 0 else ([a, d, b] if j == lat - 1
                                             else [a, d, c, b])
            _face(mesh, loop, color=LEAF)
    return mesh


def build(size: str) -> Scene:
    grid, trees = SIZES[size]
    rng = random.Random(1234)
    scene = Scene()
    pitch = 26.0
    for gx in range(grid):
        for gy in range(grid):
            w, d = rng.uniform(10, 18), rng.uniform(8, 14)
            floors = rng.randint(2, 8)
            scene.groups.append(_building(gx * pitch, gy * pitch, w, d,
                                          floors, rng))
    proto = _tree_proto()
    span = grid * pitch
    for k in range(trees):
        g = Group(proto, name="Tree")
        m = QMatrix4x4()
        m.translate(rng.uniform(-6, span), rng.uniform(-6, span), 0)
        m.rotate(rng.uniform(0, 360), 0, 0, 1)
        s = rng.uniform(0.8, 1.3)
        m.scale(s, s, s)
        g.xform = m
        scene.groups.append(g)
    scene.version += 1
    return scene


def faces_drawn(scene: Scene) -> int:
    return sum(len(g.mesh.faces) for g in scene.groups)


def main(argv) -> int:
    sizes = [a.upper() for a in argv] or ["S", "M"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        t0 = time.perf_counter()
        scene = build(size)
        path = OUT_DIR / f"city-{size}.igz"
        save_scene(scene, path)
        print(f"city-{size}: {len(scene.groups)} objects, "
              f"{faces_drawn(scene):,} faces drawn, "
              f"{path.stat().st_size / 1e6:.1f} MB, "
              f"{time.perf_counter() - t0:.1f} s -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
