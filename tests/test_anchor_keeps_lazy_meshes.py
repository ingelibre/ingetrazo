# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Resolving a dimension's vertex anchor does not build the lazy meshes
it walks past. On Marco's Queñuamarca plaza (3 400 placements) each
anchored cota on a sheet built all 164 deferred meshes to ask their
registries — 3.6 s on opening the composer (2026-11-12)."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core import mesh as M
from core.dimension import resolve_vertex_anchor
from tests.test_deferred_mesh import _open, binary  # noqa: F401
from tests.test_igz_format3 import _scene
from formats import igz


def test_an_anchor_builds_only_the_mesh_it_sits_on(binary, monkeypatch,
                                                   tmp_path):
    path = tmp_path / "doc.igz"
    igz.save_scene(_scene(tmp_path), path)
    lazy = _open(monkeypatch, path, True)
    meshes = {id(g.mesh): g.mesh for g in lazy.groups}
    deferred = [m for m in meshes.values() if type(m) is M.DeferredMesh]
    assert deferred, "the groups should open deferred"
    # A point on no group: nothing is built, no anchor.
    assert resolve_vertex_anchor(lazy, V(55, 55, 55)) is None
    assert all(type(m) is M.DeferredMesh for m in deferred)
    # The corner of the second chair (placed at x = 5, y = 20): found,
    # and only the chairs' prototype is built.
    mesa = next(g.mesh for g in lazy.groups if g.name == "Mesa")
    mesa_lazy = type(mesa) is M.DeferredMesh
    a = resolve_vertex_anchor(lazy, V(6, 21, 0))
    assert a is not None
    assert (type(mesa) is M.DeferredMesh) == mesa_lazy   # left alone
    # The classic group's corner is found too, after the cache of
    # placements was made.
    assert resolve_vertex_anchor(lazy, V(2, 30, 0)) is not None
