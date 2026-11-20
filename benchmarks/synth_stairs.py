# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic stair DXFs for the stitch / DXF-import benchmarks.

Built from scratch from a few parameters, so they can be shared and
committed: no real project goes in. They reproduce what made real stair
exports slow, as a stair CAD writes them:

* one block per part, one block for the whole stair (an assembly), placed
  once in model space;
* treads and stringers as triangulated 3DFACE solids whose neighbouring
  faces are cut differently, so their shared edges carry long chains of
  T-junctions (a stringer's sloped underside is two triangles while its
  sides have a vertex at every step);
* balusters and a handrail as POLYFACE meshes (faceted cylinders), many
  curved parts on one layer;
* a straight flight, or a helical one (``turn`` degrees), whose curved
  stringers come out as many nearly coplanar strips.

    python benchmarks/synth_stairs.py OUTDIR   # the standard set (8 files)
    python benchmarks/dxf_import_ab.py TREE FILE.dxf   # one import, one JSON line
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import ezdxf
from ezdxf.render import MeshVertexMerger


def tri(block, a, b, c):
    block.add_3dface([a, b, c, c])


def quad_grid(block, p00, p10, p01, nu, nv):
    """A planar parallelogram cut into nu x nv quads, two triangles each."""
    def at(i, j):
        u, v = i / nu, j / nv
        return tuple(p00[k] + u * (p10[k] - p00[k]) + v * (p01[k] - p00[k])
                     for k in range(3))
    for i in range(nu):
        for j in range(nv):
            a, b, c, d = at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)
            tri(block, a, b, c)
            tri(block, a, c, d)


def box(block, o, ex, ey, ez, cuts):
    """A box from corner ``o`` along edge vectors ex, ey, ez. ``cuts`` gives
    each face pair its own subdivision, so the shared edges disagree: every
    edge carries a chain of T-junctions."""
    (a1, b1), (a2, b2), (a3, b3) = cuts
    add = lambda p, q: tuple(p[k] + q[k] for k in range(3))
    quad_grid(block, o, add(o, ey), add(o, ex), a1, b1)                    # bottom
    top = add(o, ez)
    quad_grid(block, top, add(top, ex), add(top, ey), b1 + 1, a1 + 2)      # top
    quad_grid(block, o, add(o, ex), add(o, ez), a2, b2)                    # front
    back = add(o, ey)
    quad_grid(block, back, add(back, ez), add(back, ex), b2 + 2, a2 + 1)   # back
    quad_grid(block, o, add(o, ez), add(o, ey), a3, b3)                    # left
    right = add(o, ex)
    quad_grid(block, right, add(right, ey), add(right, ez), b3 + 1, a3 + 3)  # right


def stair_path(i, steps, going, rise, turn, radius):
    """(centre point, unit direction, unit lateral) of step ``i``'s front
    edge: a straight run, or a helix of ``turn`` degrees."""
    if turn == 0:
        return (0.0, i * going), (0.0, 1.0), (1.0, 0.0)
    a = math.radians(turn) * i / steps
    c = (radius * math.cos(a), radius * math.sin(a))
    return c, (-math.sin(a), math.cos(a)), (math.cos(a), math.sin(a))


def stringer(block, steps, going, rise, depth, thick, side, turn, radius,
             width, sub):
    """A stringer as vertical strips, one per step (a vertex at every step
    on its sides), with a sloped underside cut ``sub`` times as coarsely:
    the underside's long edges are T-junction chains."""
    off = (-width / 2 - thick) if side < 0 else width / 2
    def pt(i, dl, z):
        (cx, cy), _d, (lx, ly) = stair_path(i, steps, going, rise, turn, radius)
        return (cx + lx * (off + dl), cy + ly * (off + dl), z)
    for i in range(steps):
        z0, z1 = i * rise, (i + 1) * rise
        for dl in (0.0, thick):
            a, b = pt(i, dl, z0 - depth), pt(i + 1, dl, z1 - depth)
            c, d = pt(i + 1, dl, z1 + rise), pt(i, dl, z0 + rise)
            tri(block, a, b, c)
            tri(block, a, c, d)
        # top of the strip
        tri(block, pt(i, 0, z0 + rise), pt(i + 1, 0, z1 + rise), pt(i + 1, thick, z1 + rise))
        tri(block, pt(i, 0, z0 + rise), pt(i + 1, thick, z1 + rise), pt(i, thick, z0 + rise))
    # underside: coarse strips over ``sub`` steps each (T-junctions)
    for i in range(0, steps, sub):
        j = min(steps, i + sub)
        a, b = pt(i, 0, i * rise - depth), pt(j, 0, j * rise - depth)
        c, d = pt(j, thick, j * rise - depth), pt(i, thick, i * rise - depth)
        tri(block, a, b, c)
        tri(block, a, c, d)
    for i, z in ((0, -depth), (steps, steps * rise - depth)):           # ends
        zz = i * rise
        a, b = pt(i, 0, zz - depth), pt(i, thick, zz - depth)
        c, d = pt(i, thick, zz + rise), pt(i, 0, zz + rise)
        tri(block, a, b, c)
        tri(block, a, c, d)


def cylinder_polyface(block, base, height, r, sides, rings=1):
    """A faceted cylinder as one POLYFACE (closed: two caps)."""
    pf = MeshVertexMerger()
    pf.append_face = pf.add_face
    x, y, z = base
    for k in range(rings):
        z0 = z + height * k / rings
        z1 = z + height * (k + 1) / rings
        for s in range(sides):
            a0 = 2 * math.pi * s / sides
            a1 = 2 * math.pi * (s + 1) / sides
            p = lambda a, zz: (x + r * math.cos(a), y + r * math.sin(a), zz)
            pf.append_face([p(a0, z0), p(a1, z0), p(a1, z1), p(a0, z1)])
    ring = lambda zz: [(x + r * math.cos(2 * math.pi * s / sides),
                        y + r * math.sin(2 * math.pi * s / sides), zz)
                       for s in range(sides)]
    pf.append_face(list(reversed(ring(z))))
    pf.append_face(ring(z + height))
    pf.render_polyface(block)


def tube_polyface(block, path, r, sides):
    """A handrail: a faceted tube along ``path`` (open polyline), capped."""
    pf = MeshVertexMerger()
    pf.append_face = pf.add_face
    rings = []
    for k, p in enumerate(path):
        q = path[min(k + 1, len(path) - 1)]
        o = path[max(k - 1, 0)]
        t = [q[i] - o[i] for i in range(3)]
        n = math.sqrt(sum(c * c for c in t)) or 1.0
        t = [c / n for c in t]
        u = [-t[1], t[0], 0.0]
        nu = math.sqrt(u[0] ** 2 + u[1] ** 2) or 1.0
        u = [c / nu for c in u]
        v = [t[1] * u[2] - t[2] * u[1], t[2] * u[0] - t[0] * u[2],
             t[0] * u[1] - t[1] * u[0]]
        rings.append([tuple(p[i] + r * (math.cos(a) * u[i] + math.sin(a) * v[i])
                            for i in range(3))
                      for a in (2 * math.pi * s / sides for s in range(sides))])
    for a, b in zip(rings, rings[1:]):
        for s in range(sides):
            s1 = (s + 1) % sides
            pf.append_face([a[s], a[s1], b[s1], b[s]])
    pf.append_face(list(reversed(rings[0])))
    pf.append_face(rings[-1])
    pf.render_polyface(block)


def make_stair(path, steps=16, width=900.0, going=250.0, rise=180.0,
               tread=40.0, turn=0.0, radius=1600.0, detail=2,
               balusters=True, rail_sides=16, nested=False):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4                                   # mm
    for name in ("Marches", "Limons", "Garde-corps"):
        doc.layers.add(name)
    whole = doc.blocks.new("Escalier")
    d = detail
    for i in range(steps):
        b = doc.blocks.new(f"Marche{i + 1}")
        (cx, cy), (dx, dy), (lx, ly) = stair_path(i, steps, going, rise, turn, radius)
        depth = going if turn == 0 else math.radians(turn) / steps * radius
        o = (cx - lx * width / 2, cy - ly * width / 2, (i + 1) * rise - tread)
        box(b, o, (lx * width, ly * width, 0.0), (dx * depth, dy * depth, 0.0),
            (0.0, 0.0, tread), ((6 * d, 2 * d), (6 * d + 1, d), (2 * d + 1, d)))
        whole.add_blockref(f"Marche{i + 1}", (0, 0, 0), dxfattribs={"layer": "Marches"})
    for side, name in ((-1, "Limon Gauche"), (1, "Limon Droit")):
        b = doc.blocks.new(name)
        stringer(b, steps, going, rise, 300.0, 40.0, side, turn, radius, width,
                 sub=max(2, steps // 3))
        whole.add_blockref(name, (0, 0, 0), dxfattribs={"layer": "Limons"})
    if balusters:
        rail = []
        for i in range(steps + 1):
            (cx, cy), _d, (lx, ly) = stair_path(i, steps, going, rise, turn, radius)
            x, y = cx + lx * (width / 2 + 20), cy + ly * (width / 2 + 20)
            rail.append((x, y, i * rise + 900.0))
            if i < steps:
                b = doc.blocks.new(f"Balustre{i + 1}")
                cylinder_polyface(b, (x, y, (i + 1) * rise), 900.0 - rise, 15.0,
                                  rail_sides, rings=4 * d)
                whole.add_blockref(f"Balustre{i + 1}", (0, 0, 0),
                                   dxfattribs={"layer": "Garde-corps"})
        b = doc.blocks.new("Main courante")
        fine = []
        for p, q in zip(rail, rail[1:]):
            for k in range(4 * d):
                t = k / (4 * d)
                fine.append(tuple(p[c] + t * (q[c] - p[c]) for c in range(3)))
        fine.append(rail[-1])
        tube_polyface(b, fine, 25.0, rail_sides)
        whole.add_blockref("Main courante", (0, 0, 0), dxfattribs={"layer": "Garde-corps"})
    top = "Escalier"
    if nested:
        outer = doc.blocks.new("Projet")
        outer.add_blockref("Escalier", (0, 0, 0))
        top = "Projet"
    doc.modelspace().add_blockref(top, (0, 0, 0))
    doc.saveas(path)


STANDARD = {
    "synth-droit-16": dict(steps=16, detail=1),
    "synth-droit-16-fin": dict(steps=16, detail=3),
    "synth-droit-40": dict(steps=40, detail=2),
    "synth-helico-180": dict(steps=18, turn=180, detail=2),
    "synth-helico-360": dict(steps=36, turn=360, radius=1200, detail=2),
    "synth-helico-360-fin": dict(steps=36, turn=360, radius=1200, detail=4),
    "synth-droit-sans-gc": dict(steps=24, detail=3, balusters=False),
    "synth-imbrique": dict(steps=20, turn=90, detail=2, nested=True),
}


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name, kw in STANDARD.items():
        p = out / f"{name}.dxf"
        make_stair(p, **kw)
        n = sum(1 for _ in ezdxf.readfile(p).query("3DFACE"))
        print(f"{p.name}: {n} 3DFACE in blocks, {p.stat().st_size // 1024} KB")
