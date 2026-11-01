# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A textured loose face moved or turned keeps its image on it (#1034).

A group already carried its texture map along (``_remap_uvws``); loose
faces kept the old placement — the planar projection was recomputed at
the new spot and the image slid across the panel (or came out turned when
the panel was folded about an edge)."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

from core.history import (AddFaceCommand, History,
                          MoveVerticesCommand, RotateVerticesCommand)
from core.scene import Scene
from core.texture import face_uv_axes

TEX = {"path": "/x/wood.png", "sw": 0.1, "sh": 0.2, "rot": 0.0}


def _panels():
    """A 0.1 × 0.2 face split across its middle: two 0.1 × 0.1 panels,
    both textured with the planar map."""
    scene = Scene()
    hist = History(scene)
    hist.execute(AddFaceCommand(
        [V(0, 0, 0), V(0.1, 0, 0), V(0.1, 0.1, 0), V(0, 0.1, 0)]))
    hist.execute(AddFaceCommand(
        [V(0, 0.1, 0), V(0.1, 0.1, 0), V(0.1, 0.2, 0), V(0, 0.2, 0)]))
    assert len(scene.mesh.faces) == 2
    for f in scene.mesh.faces:
        f.attrs = {"texture": dict(TEX)}
    return scene, hist


def _lower(scene):
    return next(f for f in scene.mesh.faces
                if min(p.y() for p in f.vertices) < 0.05)


def _upper(scene):
    """The panel that never moves: flat on z = 0, from y = 0.1 to 0.2."""
    return next(f for f in scene.mesh.faces
                if all(abs(p.z()) < 1e-9 and p.y() > 0.1 - 1e-9
                       for p in f.vertices))


def _dot(a, b):
    return V.dotProduct(a, b)


def _uv_list(face, order):
    gu, cu, gv, cv = face_uv_axes(face.attrs["texture"], face.normal())
    return [(_dot(gu, p) + cu, _dot(gv, p) + cv) for p in order]


def _flat(uvs):
    return [c for uv in uvs for c in uv]


@pytest.mark.parametrize("delta", [V(0.03, 0.0, 0.0), V(0.0, 0.0, 0.5)])
def test_moved_loose_face_keeps_its_texture(delta):
    scene, hist = _panels()
    low = _lower(scene)
    before_pts = [V(p) for p in low.vertices]
    before = _uv_list(low, before_pts)
    upper_before = dict(_upper(scene).attrs["texture"])
    hist.execute(MoveVerticesCommand(before_pts, delta, carry_textures=True))
    low = next(f for f in scene.mesh.faces
               if all(any((q - (p + delta)).length() < 1e-9
                          for p in before_pts) for q in f.vertices))
    after = _uv_list(low, [p + delta for p in before_pts])
    for (u0, v0), (u1, v1) in zip(before, after):
        assert u1 == pytest.approx(u0, abs=1e-6)
        assert v1 == pytest.approx(v0, abs=1e-6)
    # undo gives the planar map back, untouched
    hist.undo()
    assert "uvw" not in _lower(scene).attrs["texture"]
    assert _upper(scene).attrs["texture"] == upper_before


def test_panel_folded_about_its_edge_keeps_its_texture():
    scene, hist = _panels()
    low = _lower(scene)
    pts = [V(p) for p in low.vertices]
    before = _uv_list(low, pts)
    upper_before = dict(_upper(scene).attrs["texture"])
    hist.execute(RotateVerticesCommand(pts, V(0, 0.1, 0), V(1, 0, 0), 90.0,
                                       carry_textures=True))
    from core.history import rotation_matrix
    m = rotation_matrix(V(0, 0.1, 0), V(1, 0, 0), 90.0)
    turned = [m.map(p) for p in pts]
    low = next(f for f in scene.mesh.faces
               if all(any((q - t).length() < 1e-9 for t in turned)
                      for q in f.vertices))
    after = _uv_list(low, turned)
    for (u0, v0), (u1, v1) in zip(before, after):
        assert u1 == pytest.approx(u0, abs=1e-6)
        assert v1 == pytest.approx(v0, abs=1e-6)
    # the panel that stayed keeps its planar map
    assert _upper(scene).attrs["texture"] == upper_before
    hist.undo()
    hist.redo()
    low = next(f for f in scene.mesh.faces
               if all(any((q - t).length() < 1e-9 for t in turned)
                      for q in f.vertices))
    assert _flat(_uv_list(low, turned)) == pytest.approx(_flat(after))


def test_partial_move_leaves_the_texture_alone():
    """Only faces the move carries whole are re-mapped: a stretched face
    keeps the planar map it had."""
    scene, hist = _panels()
    hist.execute(MoveVerticesCommand([V(0, 0.2, 0), V(0.1, 0.2, 0)],
                                     V(0, 0.05, 0), carry_textures=True))
    for f in scene.mesh.faces:
        assert "uvw" not in f.attrs["texture"]


# ---- the tools hand the flag over -------------------------------------------

class _Vp:
    def __init__(self, scene, hist):
        self.scene = scene
        self.history = hist

    def update(self):
        pass

    def flash_status(self, *a):
        pass


def test_move_tool_carries_the_texture():
    from tools.move import MoveTool
    scene, hist = _panels()
    low = _lower(scene)
    pts = [V(p) for p in low.vertices]
    before = _uv_list(low, pts)
    tool = MoveTool()
    tool._reset()
    tool._positions = list(pts)
    delta = V(0.03, 0.0, 0.0)
    tool._commit(_Vp(scene, hist), delta)
    moved = [p + delta for p in pts]
    low = next(f for f in scene.mesh.faces
               if all(any((q - t).length() < 1e-9 for t in moved)
                      for q in f.vertices))
    assert _flat(_uv_list(low, moved)) == pytest.approx(_flat(before),
                                                     abs=1e-6)


def test_rotate_tool_carries_the_texture(monkeypatch):
    from tools.rotate import RotateTool
    scene, hist = _panels()
    low = _lower(scene)
    pts = [V(p) for p in low.vertices]
    before = _uv_list(low, pts)
    tool = RotateTool()
    tool._reset()
    tool.start_point = V(0, 0.1, 0)
    monkeypatch.setattr(tool, "_axis", lambda: V(1, 0, 0))
    tool._positions = list(pts)
    hist.execute(tool._make_builder()([90.0]))
    from core.history import rotation_matrix
    m = rotation_matrix(V(0, 0.1, 0), V(1, 0, 0), 90.0)
    turned = [m.map(p) for p in pts]
    low = next(f for f in scene.mesh.faces
               if all(any((q - t).length() < 1e-9 for t in turned)
                      for q in f.vertices))
    assert _flat(_uv_list(low, turned)) == pytest.approx(_flat(before),
                                                      abs=1e-6)


def test_warped_face_keeps_the_projection_it_was_drawn_with():
    """The planar map is materialised with the renderer's own normal
    (Newell's). The first corner's cross product read this slightly warped
    quad as standing on its side and the image jumped to that projection."""
    scene = Scene()
    hist = History(scene)
    f = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 0.0005),
                             V(0, 1, 0.0002)])
    f.attrs = {"texture": dict(TEX)}
    pts = [V(p) for p in f.vertices]
    before = _uv_list(f, pts)
    delta = V(0.4, 0.2, 0.0)
    hist.execute(MoveVerticesCommand(pts, delta, carry_textures=True))
    assert f in scene.mesh.faces
    assert _flat(_uv_list(f, [p + delta for p in pts])) == pytest.approx(
        _flat(before), abs=1e-6)
