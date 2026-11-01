# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DXF assemblies: a model exported as one block for the whole and one block
per part (stair, joinery and mechanical CAD do this) imports as one named
component per part, each stitched on its own — not as a single mesh where
touching parts weld together and the names are lost."""
from __future__ import annotations

import math
import time

import pytest

ezdxf = pytest.importorskip("ezdxf")

from core.group import world_mesh                         # noqa: E402
from core.scene import Scene                              # noqa: E402
from formats.dxf_in import load_dxf                       # noqa: E402


def _box_faces(block, x0, y0, z0, x1, y1, z1):
    """A closed box as 12 triangles (3DFACE), the way CAD exports solids."""
    p = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)]
    for a, b, c, d in quads:
        block.add_3dface([p[a], p[b], p[c], p[c]])
        block.add_3dface([p[a], p[c], p[d], p[d]])


def _stair(tmp_path, steps=3, nested=False):
    """Treads 900 x 250 x 40 mm resting on two stringers, all touching:
    one block per part, one block for the whole stair."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    for i in range(steps):
        b = doc.blocks.new(f"Marche{i + 1}")
        _box_faces(b, 0, 0, 0, 900, 250, 40)
    for side in ("Gauche", "Droit"):
        b = doc.blocks.new(f"Limon {side}")
        _box_faces(b, 0, 0, 0, 40, 250 * steps, 200 * steps + 40)
    whole = doc.blocks.new("Escalier")
    for i in range(steps):
        whole.add_blockref(f"Marche{i + 1}", (40, 250 * i, 200 * (i + 1)))
    whole.add_blockref("Limon Gauche", (0, 0, 0))
    whole.add_blockref("Limon Droit", (940, 0, 0))
    top = "Escalier"
    if nested:                       # an assembly inside an assembly
        outer = doc.blocks.new("Projet")
        outer.add_blockref("Escalier", (1000, 0, 0), dxfattribs={"rotation": 90})
        top = "Projet"
    doc.modelspace().add_blockref(top, (0, 0, 0))
    out = tmp_path / "stair.dxf"
    doc.saveas(str(out))
    return out


def test_each_part_of_an_assembly_is_its_own_named_component(tmp_path):
    scene = Scene()
    stats = load_dxf(scene, _stair(tmp_path), scale=0.001)
    names = sorted(g.name for g in scene.groups)
    assert names == ["Limon Droit", "Limon Gauche",
                     "Marche1", "Marche2", "Marche3"]
    assert stats["groups"] == 5
    for g in scene.groups:
        mesh = world_mesh(g)
        # stitched and merged on its own: a box, six quads, closed
        assert len(mesh.faces) == 6, (g.name, len(mesh.faces))
        assert all(len(e.faces) == 2 for e in mesh.edges)


def test_parts_land_where_the_assembly_puts_them(tmp_path):
    scene = Scene()
    load_dxf(scene, _stair(tmp_path), scale=0.001)
    m3 = next(g for g in scene.groups if g.name == "Marche3")
    zs = [v.position.z() for v in world_mesh(m3).vertices]
    ys = [v.position.y() for v in world_mesh(m3).vertices]
    assert min(zs) == pytest.approx(0.6) and max(zs) == pytest.approx(0.64)
    assert min(ys) == pytest.approx(0.5) and max(ys) == pytest.approx(0.75)


def test_nested_assemblies_compose_their_placements(tmp_path):
    scene = Scene()
    load_dxf(scene, _stair(tmp_path, nested=True), scale=0.001)
    assert len(scene.groups) == 5
    lg = next(g for g in scene.groups if g.name == "Limon Gauche")
    pts = [v.position for v in world_mesh(lg).vertices]
    # rotated 90 deg about Z then moved 1 m along X: x in [1 - 0.75, 1]
    xs = [p.x() for p in pts]
    ys = [p.y() for p in pts]
    assert min(xs) == pytest.approx(0.25) and max(xs) == pytest.approx(1.0)
    assert min(ys) == pytest.approx(0.0) and max(ys) == pytest.approx(0.04)


def test_a_block_mixing_geometry_and_inserts_still_explodes(tmp_path):
    """Unchanged behaviour: geometry plus INSERTs stay one prototype."""
    doc = ezdxf.new("R2018")
    part = doc.blocks.new("Part")
    _box_faces(part, 0, 0, 0, 1, 1, 1)
    mixed = doc.blocks.new("Mixed")
    _box_faces(mixed, 5, 0, 0, 6, 1, 1)
    mixed.add_blockref("Part", (0, 0, 0))
    doc.modelspace().add_blockref("Mixed", (0, 0, 0))
    out = tmp_path / "mixed.dxf"
    doc.saveas(str(out))
    scene = Scene()
    load_dxf(scene, out, scale=1.0)
    assert [g.name for g in scene.groups] == ["Mixed"]


def test_many_triangle_pairs_merge_without_quadratic_restarts(tmp_path):
    """A curved strip exported as triangle pairs (each facet = 2 triangles,
    no two facets coplanar), the shape of a CAD stair slab underside: each
    facet merges back into one quad, in one scan per round instead of one
    full rescan per merge."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4
    b = doc.blocks.new("Paillasse")
    n, r = 60, 1000.0                         # 3 deg between facets
    for k in range(n):
        t0, t1 = math.pi * k / n, math.pi * (k + 1) / n
        a = (r * math.cos(t0), 0, r * math.sin(t0))
        c = (r * math.cos(t1), 0, r * math.sin(t1))
        a2 = (a[0], 300, a[2])
        c2 = (c[0], 300, c[2])
        b.add_3dface([a, c, c2, c2])
        b.add_3dface([a, c2, a2, a2])
    doc.modelspace().add_blockref("Paillasse", (0, 0, 0))
    out = tmp_path / "strip.dxf"
    doc.saveas(str(out))
    scene = Scene()
    t = time.perf_counter()
    load_dxf(scene, out, scale=0.001)
    elapsed = time.perf_counter() - t
    mesh = world_mesh(scene.groups[0])
    assert len(mesh.faces) == n
    assert elapsed < 10.0, elapsed
