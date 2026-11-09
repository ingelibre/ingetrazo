# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The front face at a pixel over the engine's lazy placements (#158),
without gathering every face the ray meets
(``Viewport._front_face_lean``): the face and placement the argmin over
all of them gave — pixel by pixel, from several views, over copies
twinned on the very same spot (equal t, the first of equals wins) and a
fixed group sharing a copy's spot (the index's face wins the tie).
Skipped without the engine."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4

import views.viewport as viewport_mod
from tests.test_lazy_native_snap import (  # noqa: F401
    VIEWS, _close, _face_key, _set_view, _window, pytestmark)

pytestmark = pytestmark


def _twinned():
    from core.group import Group
    w, vp = _window(lazy=True)
    sc = vp.scene
    copies = [g for g in sc.groups if g.name.startswith("C")]
    for k, g in enumerate(copies[::3]):
        t = Group(g.mesh, name=f"T{k}")             # the same spot
        t.xform = QMatrix4x4(g.xform)
        sc.groups.insert(0 if k % 2 else len(sc.groups), t)
    # A fixed group (no matrix) with a copy's very faces.
    from core.mesh import Mesh
    g = copies[5]
    m = Mesh()
    for f in g.mesh.faces:
        m.add_face([g.xform.map(v) for v in f.vertices])
    sc.groups.append(Group(m, name="F"))
    # A copy left where its mesh is (the identity) over a fixed group of
    # those very points: the same triangles, the same t.
    from tests.test_lazy_native_snap import _cube
    cube = _cube(1.3, 1.1, 0.9, (4.0, 9.0, 4.5))
    c = Group(cube, name="I")
    c.xform = QMatrix4x4()
    sc.groups.append(c)
    same = _cube(1.3, 1.1, 0.9, (4.0, 9.0, 4.5))
    sc.groups.append(Group(same, name="F2"))
    sc.version += 1
    return w, vp


@pytest.fixture
def win():
    w, vp = _twinned()
    try:
        yield vp
    finally:
        _close(w)


def _key(h):
    if h is None:
        return None
    return (id(h[0]), id(h[1]), _face_key(*h))


def test_the_front_face_is_the_one_every_hit_gave(win, monkeypatch):
    vp = win
    leaned = []
    real = type(vp)._front_face_lean
    monkeypatch.setattr(type(vp), "_front_face_lean",
                        lambda self, *a: (leaned.append(1),
                                          real(self, *a))[1])
    seen = twins = fixed = 0
    for view in VIEWS:
        _set_view(vp, view)
        for x in np.arange(6.1, 900, 17.0):
            for y in np.arange(4.3, 640, 19.0):
                x, y = float(x), float(y)
                got = vp._front_face_at(x, y)
                with monkeypatch.context() as m:
                    m.setattr(viewport_mod, "_FRONT_LEAN", False)
                    want = vp._front_face_at(x, y)
                assert _key(got) == _key(want), (view, x, y)
                seen += want is not None
                twins += want is not None and getattr(
                    want[1], "name", "")[:1] in ("T", "F")
                fixed += want is not None and getattr(
                    want[1], "name", "") == "F2"
    assert leaned and seen > 300
    assert twins > 5                      # the ties really were met
    assert fixed > 3                      # the index's face won them
