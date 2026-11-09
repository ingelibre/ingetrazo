# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A component placement baked for the pick index leaves its draw-only
fields (colours, texture runs, re-shading) for later: hundreds of lazy
placements came in per pointer move on the plant of #158, and that part of
the bake was most of the cost. Asked for, each field is exactly what the
eager bake gave."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import views.viewport as viewport  # noqa: E402
from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402

DRAW_ONLY = ("dback", "vcol", "by_texture", "tcol", "ttex", "back_vcol",
             "back_tex", "back_tcol", "back_ttex", "fvcol", "soft_pts",
             "soft_n0", "soft_c0", "soft_n1", "soft_c1")


def _box():
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for q in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
              [2, 3, 7, 6], [3, 0, 4, 7]):
        m.add_face([p[i] for i in q])
    # A face in a material of its own, and a lone edge: more runs to bake.
    m.faces[1].attrs["material"] = "rojo"
    m.add_edge(V(0, 0, 0), V(2, 2, 2))
    return m


def _placements():
    """Plain, moved, turned, mirrored and unevenly scaled copies."""
    out = []
    for i, (deg, sx, sy, sz) in enumerate(
            [(0, 1, 1, 1), (40, 1, 1, 1), (0, -1, 1, 1), (25, 2, 1, 0.5),
             (90, 1, -1, 1)]):
        m = QMatrix4x4()
        m.translate(3.0 * i, 1.0, 0.5 * i)
        m.rotate(deg, 1, 0.3, 0)
        m.scale(sx, sy, sz)
        out.append(m)
    return out


def _scene(vp, proto):
    groups = []
    for i, xf in enumerate(_placements()):
        g = Group(proto, f"copia {i}")
        g.xform = xf
        groups.append(g)
    vp.scene.groups += groups
    vp.scene.version += 1
    return groups


def _same(a, b):
    if isinstance(a, dict):
        return (isinstance(b, dict) and a.keys() == b.keys()
                and all(_same(a[k], b[k]) for k in a))
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return np.array_equal(np.asarray(a), np.asarray(b))
    if isinstance(a, (list, tuple)):
        return (type(a) is type(b) and len(a) == len(b)
                and all(_same(x, y) for x, y in zip(a, b)))
    return a == b


def test_the_pick_index_does_not_bake_what_only_drawing_reads():
    vp = viewport.Viewport(None)
    groups = _scene(vp, _box())
    vp._pick_index()
    for g in groups:
        entry = vp._inst_chunks[id(g)]
        pending = [k for k in DRAW_ONLY if not dict.__contains__(entry, k)]
        assert pending == list(DRAW_ONLY), g.name


def test_each_field_asked_for_is_what_the_eager_bake_gave(monkeypatch):
    proto = _box()
    lazy_vp = viewport.Viewport(None)
    lazy = [lazy_vp._instance_chunk(g) for g in _scene(lazy_vp, proto)]

    class Eager(viewport._LazyChunk):
        __slots__ = ()

        def __init__(self, data, later):
            super().__init__(data, later)
            self._made()

    monkeypatch.setattr(viewport, "_LazyChunk", Eager)
    eager_vp = viewport.Viewport(None)
    eager = [eager_vp._instance_chunk(g) for g in _scene(eager_vp, proto)]
    for a, b in zip(lazy, eager):
        assert set(a) == set(b)
        for k in a:
            if k in ("uid", "ikey"):         # serials, not geometry
                continue
            assert _same(a[k], b[k]), k


def test_a_field_set_before_it_is_read_stays_as_set():
    """The Move drag's shift writes fields back: a write wins over the
    pending bake, and reading first then writing works as on a dict."""
    made = []
    c = viewport._LazyChunk({"a": 1}, {"b": lambda: made.append(1) or 2,
                                       "c": lambda: 3})
    assert "b" in c and c.get("b") == 2 and made == [1]
    c["c"] = 30
    assert c["c"] == 30 and dict(c.items()) == {"a": 1, "b": 2, "c": 30}
    with pytest.raises(KeyError):
        c["nada"]                       # noqa: B018
    assert c.get("nada", 7) == 7


def test_a_moved_copy_reads_to_the_index_as_a_fresh_bake():
    """A pure translation shifts a cached bake instead of making it again;
    what the pick index reads (triangles, hard edges) comes out the same,
    bit for bit, as a bake at the new place — the native engine answers
    for the placements it does not bake from that formula (#158)."""
    proto = _box()
    vp = viewport.Viewport(None)
    groups = _scene(vp, proto)
    for g in groups:
        vp._instance_chunk(g)
        m = QMatrix4x4(g.xform)
        m.translate(0.1234567, -7.654321, 3.3333333)  # in local axes
        moved = QMatrix4x4()
        moved.translate(0.3, 0.7, -0.1)
        g.xform = moved * m
    for g in groups:
        old = tuple(vp._inst_chunks[id(g)]["ikey"][1])
        shifted = vp._instance_chunk(g)
        assert shifted["ikey"][1] != old
        fresh_vp = viewport.Viewport(None)
        fresh_vp.scene.groups.append(g)
        fresh = fresh_vp._instance_chunk(g)
        assert shifted["edges"] == fresh["edges"], g.name
        for k in ("v0", "e1", "e2"):
            assert np.array_equal(shifted[k], fresh[k]), (g.name, k)
