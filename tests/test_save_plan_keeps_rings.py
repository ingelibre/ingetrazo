# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A lazy mesh saved twice asks once which holes are nested (#1092: the next
save, the autosave, has it), and curve and layer ids are still seen by the
quicker test: the same bytes as the mesh built and saved. Skipped without
the engine."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402

import core._native as _native  # noqa: E402
from core import mesh as M  # noqa: E402
from core import topology  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402
from tests.test_deferred_mesh import _open  # noqa: E402

pytestmark = pytest.mark.skipif(
    _native.native is None or _native.qt_hypot() is None,
    reason="engine off or not built")


def _square(x, y, s, z=0.0):
    return [V(x, y, z), V(x + s, y, z), V(x + s, y + s, z), V(x, y + s, z)]


def _doc(tmp_path, monkeypatch, curve=False, layer=False):
    # On file with the nested hole still there: an older save could leave it.
    with monkeypatch.context() as ctx:
        ctx.setattr(topology, "_maximal_holes", lambda h: h)
        scene = Scene()
        m = scene.mesh
        m.add_face(_square(0, 0, 10), [_square(1, 1, 4), _square(2, 2, 1),
                                       _square(6, 6, 2)])
        m.add_face(_square(20, 0, 10), [_square(21, 1, 2)])
        for k in range(4):
            m.add_face(_square(0, 20 + 3 * k, 2))
        if curve:
            m.edges[3].curve = 40
        if layer:
            m.edges[5].layer = "Muros"
        path = tmp_path / "doc.igz"
        igz.save_scene(scene, path)
    return path


@pytest.fixture
def binary(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 0)


@pytest.mark.parametrize("curve,layer", [(False, False), (True, False),
                                         (False, True), (True, True)])
def test_the_bytes_are_those_of_the_built_mesh(binary, monkeypatch, tmp_path,
                                               curve, layer):
    path = _doc(tmp_path, monkeypatch, curve, layer)
    lazy = _open(monkeypatch, path, True)
    eager = _open(monkeypatch, path, False)
    assert type(lazy.mesh) is M.DeferredMesh and type(eager.mesh) is M.Mesh
    a, b, c = (tmp_path / n for n in ("a.igz", "b.igz", "c.igz"))
    igz.save_scene(lazy, a)
    igz.save_scene(lazy, b)
    assert type(lazy.mesh) is M.DeferredMesh, "saving built it"
    igz.save_scene(eager, c)
    assert a.read_bytes() == c.read_bytes()
    assert a.read_bytes() != path.read_bytes(), "no hole was dropped"
    assert b.read_bytes() == c.read_bytes()


def test_the_second_save_does_not_ask_again(binary, monkeypatch, tmp_path):
    path = _doc(tmp_path, monkeypatch)
    lazy = _open(monkeypatch, path, True)
    calls = []
    real = topology._maximal_holes
    monkeypatch.setattr(topology, "_maximal_holes",
                        lambda h: calls.append(1) or real(h))
    igz.save_scene(lazy, tmp_path / "a.igz")
    assert len(calls) == 1
    igz.save_scene(lazy, tmp_path / "b.igz")
    assert len(calls) == 1
