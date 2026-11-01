# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Work a pointer move must not redo on a huge model (#942).

On the plant of #158 (21 406 placements) two things made a move or a click
cost a second where the median is one frame:

* ``Scene.bounds()`` walked every placement again after a click that only
  SELECTED (a view-only bump), and after any edit it re-read the boxes of
  the placements that had not changed;
* the centre reference built a still-lazy group mesh whole (~0.5 s) only to
  learn that the edge under the cursor was not a circle's.

Each answer must stay the one the full walk / the built mesh gives."""
from __future__ import annotations

import math

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

import core._native as _native
from core import mesh as M
from core.group import Group
from core.scene import Scene
from formats import igz


@pytest.fixture
def binary(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)


def _box(m, o, s=1.0):
    x, y, z = o
    m.add_face([V(x, y, z), V(x + s, y, z), V(x + s, y + s, z),
                V(x, y + s, z)])
    m.add_face([V(x, y, z + s), V(x + s, y, z + s), V(x + s, y + s, z + s),
                V(x, y + s, z + s)])


def _circle(m, c, r=1.0, n=24):
    pts = [V(c[0] + r * math.cos(2 * math.pi * i / n),
             c[1] + r * math.sin(2 * math.pi * i / n), c[2])
           for i in range(n)]
    m.add_face(pts)
    m.tag_curve(pts, closed=True)
    return pts


def _scene():
    sc = Scene()
    _box(sc.mesh, (-1, -1, 0))
    proto = M.Mesh()
    _box(proto, (0, 0, 0), 2.0)
    for k in range(4):
        g = Group(proto, name=f"B{k}")
        x = QMatrix4x4()
        x.translate(k * 5.0, 1.0, 0.5)
        x.rotate(17.0 * k, 0, 0, 1)
        g.xform = x
        sc.groups.append(g)
    round_ = Group(name="R")
    _box(round_.mesh, (0, 0, 0))
    _circle(round_.mesh, (5.0, 5.0, 1.0), 1.5)
    x = QMatrix4x4()
    x.translate(-10.0, 3.0, 0.0)
    round_.xform = x
    sc.groups.append(round_)
    return sc


def _lazy(tmp_path):
    path = tmp_path / "doc.igz"
    igz.save_scene(_scene(), path)
    sc = Scene()
    igz.load_into(sc, path)
    assert any(type(g.mesh) is M.DeferredMesh for g in sc.groups)
    return sc


def _walk(sc):
    """The box as a full walk gives it (no cache of any kind)."""
    sc.__dict__.pop("_bounds_cache", None)
    sc.__dict__.pop("_bounds_parts", None)
    lo, hi = sc.bounds()
    return lo.toTuple(), hi.toTuple()


def _box_of(sc):
    lo, hi = sc.bounds()
    return lo.toTuple(), hi.toTuple()


def test_a_selection_keeps_the_box_without_a_walk():
    sc = _scene()
    first = _box_of(sc)
    sc.select([sc.groups[0]])                   # bump_view
    sc.clear_selection()
    sc.placements = None                        # a walk would raise
    assert _box_of(sc) == first


def test_what_changes_the_box_still_changes_it():
    sc = _scene()
    _box_of(sc)
    g = sc.groups[1]
    g.hidden = True
    sc.version += 1
    assert _box_of(sc) == _walk(sc)
    g.hidden = False
    sc.version += 1
    m = QMatrix4x4()
    m.translate(100.0, 0.0, 0.0)
    g.xform = m * g.xform
    sc.version += 1
    moved = _box_of(sc)
    assert moved[1][0] > 100.0 and moved == _walk(sc)
    sc.begin_group_edit(sc.groups[-1])          # the context swaps the mesh
    assert _box_of(sc) == _walk(sc)
    sc.end_group_edit()
    assert _box_of(sc) == _walk(sc)


def test_a_lazy_placements_box_is_kept_until_it_changes(binary, tmp_path):
    sc = _lazy(tmp_path)
    assert _box_of(sc) == _walk(sc)
    kept = dict(sc._bounds_parts)
    assert kept, "the lazy placements' boxes are kept"
    # Another version, nothing moved: every lazy box comes from the memo.
    sc.version += 1
    sc.bounds()
    assert all(sc._bounds_parts[k] is part for k, part in kept.items())
    assert _box_of(sc) == _walk(sc)
    # Moved: the moved placement is read again, the box follows.
    g = next(g for g in sc.groups if type(g.mesh) is M.DeferredMesh)
    m = QMatrix4x4()
    m.translate(0.0, 0.0, 250.0)
    g.xform = m * g.xform
    sc.version += 1
    got = _box_of(sc)
    assert got[1][2] > 250.0 and got == _walk(sc)
    # Built and edited in place (an edit inside the group): never the memo.
    v = g.mesh.vertices[0]
    v.position = v.position + V(0.0, 0.0, 600.0)
    sc.version += 1
    got = _box_of(sc)
    assert got[1][2] > 800.0 and got == _walk(sc)


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        from views.viewport import Viewport
        for m in ("_center_of_group_edge", "_center_of_edge"):
            setattr(self, m, getattr(Viewport, m).__get__(self))


def _pseudo(g, a, b):
    from views.viewport import _SnapEdge
    xf = g.xform
    return _SnapEdge(xf.map(a), xf.map(b), in_group=True, context="group",
                     group=g)


def test_a_straight_edge_of_a_lazy_group_answers_without_building_it(
        binary, tmp_path):
    sc = _lazy(tmp_path)
    vp = _Vp(sc)
    g = sc.groups[-1]
    assert type(g.mesh) is M.DeferredMesh
    assert vp._center_of_group_edge(_pseudo(g, V(0, 0, 0), V(1, 0, 0))) \
        is None
    assert type(g.mesh) is M.DeferredMesh       # nothing was built
    box = sc.groups[0]
    assert vp._center_of_group_edge(_pseudo(box, V(0, 0, 0), V(2, 0, 0))) \
        is None
    assert type(box.mesh) is M.DeferredMesh


def test_a_circle_edge_of_a_lazy_group_still_gives_its_centre(binary,
                                                             tmp_path):
    lazy = _lazy(tmp_path)
    g = lazy.groups[-1]
    from core.lazy_mesh import plan_of
    plan = plan_of(g.mesh)
    i = next(k for k, c in enumerate(plan.curve) if c is not None)
    a, b = (V(*plan.pos[j]) for j in plan.edges[i])
    found = _Vp(lazy)._center_of_group_edge(_pseudo(g, a, b))
    assert found is not None
    # The same answer as on the scene built eagerly.
    eager = _scene()
    e = eager.groups[-1]
    want = _Vp(eager)._center_of_group_edge(_pseudo(e, a, b))
    assert want is not None
    assert found[0].toTuple() == want[0].toTuple()
    assert found[1] == want[1]
