# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The distance inference skips a mesh by its 3D box's projected corners,
all meshes in one projection (night of 19-11), before projecting any of
its vertices: the same reference — distance, point and kind — as when
every mesh was projected whole, for cameras with meshes beside, behind
and around the eye."""
from __future__ import annotations

import random

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from tools.pushpull import PushPullTool


class _Vp:
    """Projects through a real perspective camera, both ways the tool asks."""

    def __init__(self, scene, eye, at, w=800, h=600):
        self.scene = scene
        m = QMatrix4x4()
        m.perspective(60.0, w / h, 0.1, 500.0)
        v = QMatrix4x4()
        v.lookAt(eye, at, V(0, 0, 1))
        self._m = np.array((m * v).data(), dtype=np.float64).reshape(
            4, 4, order="F")
        self._w, self._h = w, h
        self.snap_threshold_px = 9.0
        self._hover_edge = None

    def width(self):
        return self._w

    def height(self):
        return self._h

    def _np_mvp(self):
        return self._m

    def _project_px(self, pts):
        M = self._m
        clip = (pts[:, 0:1] * M[:, 0] + pts[:, 1:2] * M[:, 1]
                + pts[:, 2:3] * M[:, 2] + M[:, 3])
        w = clip[:, 3]
        ok = w > 0
        safe = np.where(ok, w, 1.0)
        px = (clip[:, 0] / safe * 0.5 + 0.5) * self._w
        py = (1.0 - (clip[:, 1] / safe * 0.5 + 0.5)) * self._h
        return px, py, ok

    def _world_to_pixel(self, p):
        px, py, ok = self._project_px(np.array([[p.x(), p.y(), p.z()]]))
        return (float(px[0]), float(py[0])) if ok[0] else None

    def pick_face_any(self, x, y):
        return None, None


def _scene(rng):
    sc = Scene()
    for _ in range(rng.randint(20, 60)):
        m = Mesh()
        c = V(rng.uniform(-30, 30), rng.uniform(-30, 30), rng.uniform(-3, 6))
        s = rng.uniform(0.2, 4.0)
        for _k in range(rng.randint(1, 4)):
            o = c + V(rng.uniform(-s, s), rng.uniform(-s, s), rng.uniform(-s, s))
            m.add_face([o, o + V(s, 0, 0), o + V(s, s, rng.uniform(-1, 1)),
                        o + V(0, s, 0)])
        sc.groups.append(Group(m, "g"))
    return sc


def _ask(tool, vp, x, y):
    from types import SimpleNamespace
    from PySide6.QtCore import QPointF
    tool._inference_point = tool._inference_kind = None
    got = tool._infer_reference_distance(
        SimpleNamespace(viewport=vp, screen=QPointF(x, y)))
    p = tool._inference_point
    return (None if got is None else round(got, 9),
            None if p is None else (p.x(), p.y(), p.z()), tool._inference_kind)


@pytest.mark.parametrize("seed", range(12))
def test_the_same_reference_with_the_corner_boxes(seed, monkeypatch):
    rng = random.Random(seed)
    sc = _scene(rng)
    eyes = [(V(rng.uniform(-40, 40), rng.uniform(-40, 40), rng.uniform(2, 30)),
             V(rng.uniform(-5, 5), rng.uniform(-5, 5), 0)) for _ in range(2)]
    eyes.append((V(0, 0, 2), V(10, 3, 1)))      # inside the scatter
    tool = PushPullTool()
    tool._anchor, tool._normal = V(0, 0, 0), V(0, 0, 1)
    tool._cap_positions = []
    monkeypatch.setattr(tool, "_reference_hidden", lambda vp, p: False)
    monkeypatch.setattr(tool, "_infer_edge_midpoint", lambda *a: None)
    monkeypatch.setattr(tool, "_infer_guide_line", lambda *a: None)
    skipped = 0
    for eye, at in eyes:
        vp = _Vp(sc, eye, at)
        # Cursor spots: on projected corners (so references engage) and
        # anywhere.
        pts = []
        for g in rng.sample(sc.groups, 6):
            pix = vp._world_to_pixel(g.mesh.vertices[0].position)
            if pix is not None:
                pts.append((pix[0] + rng.uniform(-4, 4),
                            pix[1] + rng.uniform(-4, 4)))
        pts += [(rng.uniform(0, 800), rng.uniform(0, 600)) for _ in range(6)]
        for x, y in pts:
            tool._infer_cache = None
            got = _ask(tool, vp, x, y)
            approx = sum(1 for b in tool._infer_boxes[1].values()
                         if len(b) > 4)
            skipped += approx
            with monkeypatch.context() as mp:
                mp.setattr(tool, "_corner_boxes", lambda proj, boxes: None)
                tool._infer_cache = None
                want = _ask(tool, vp, x, y)
            assert got == want, (seed, x, y)
    assert skipped > 0, "no mesh was ever skipped by its corners"


def test_some_cases_engage_a_vertex(monkeypatch):
    kinds = set()
    for seed in range(12):
        rng = random.Random(seed)
        sc = _scene(rng)
        tool = PushPullTool()
        tool._anchor, tool._normal = V(0, 0, 0), V(0, 0, 1)
        tool._cap_positions = []
        monkeypatch.setattr(tool, "_reference_hidden", lambda vp, p: False)
        monkeypatch.setattr(tool, "_infer_edge_midpoint", lambda *a: None)
        monkeypatch.setattr(tool, "_infer_guide_line", lambda *a: None)
        vp = _Vp(sc, V(30, -30, 20), V(0, 0, 0))
        for g in sc.groups[:5]:
            pix = vp._world_to_pixel(g.mesh.vertices[0].position)
            if pix:
                tool._infer_cache = None
                kinds.add(_ask(tool, vp, *pix)[2])
    assert "vertex" in kinds


@pytest.mark.parametrize("far", [4.0, 9.0, 20.0])
def test_a_mesh_reaching_behind_the_eye_is_projected_whole(far, monkeypatch):
    """A box with corners behind the camera says nothing on screen: the mesh
    is projected whole, and its corner in front still engages."""
    sc = Scene()
    m = Mesh()
    m.add_face([V(-6, -1, 0), V(far, -1, 0), V(far, 1.5, 0.5), V(-6, 1, 0)])
    sc.groups.append(Group(m, "long"))
    tool = PushPullTool()
    tool._anchor, tool._normal = V(0, 0, 3), V(0, 0, 1)
    tool._cap_positions = []
    monkeypatch.setattr(tool, "_reference_hidden", lambda vp, p: False)
    monkeypatch.setattr(tool, "_infer_edge_midpoint", lambda *a: None)
    monkeypatch.setattr(tool, "_infer_guide_line", lambda *a: None)
    vp = _Vp(sc, V(0, 0, 2), V(10, 0, 1.5))
    for corner in (V(far, -1, 0), V(far, 1.5, 0.5)):
        pix = vp._world_to_pixel(corner)
        assert pix is not None
        tool._infer_cache = None
        got = _ask(tool, vp, *pix)
        assert got[2] == "vertex"
        assert got[1] == pytest.approx((corner.x(), corner.y(), corner.z()))


@pytest.mark.parametrize("seed", range(30))
def test_every_vertex_in_front_lies_in_its_corner_box(seed):
    rng = random.Random(seed)
    tool = PushPullTool()
    eye = V(rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(0, 4))
    vp = _Vp(Scene(), eye, eye + V(rng.uniform(-1, 1), rng.uniform(-1, 1),
                                   rng.uniform(-0.3, 0.3)))
    arrs = []
    for _ in range(40):
        c = np.array([rng.uniform(-15, 15), rng.uniform(-15, 15),
                      rng.uniform(-5, 8)])
        arrs.append(c + np.array([[rng.uniform(-6, 6) for _a in range(3)]
                                  for _v in range(rng.randint(1, 12))]))
    tool._infer_bounds = [(a.min(axis=0), a.max(axis=0)) for a in arrs]
    boxes: dict = {}
    tool._corner_boxes(vp._project_px, boxes)
    for n, a in enumerate(arrs):
        box = boxes.get(n)
        if box is None:
            continue
        px, py, ok = vp._project_px(a)
        assert ok.all()
        assert (px >= box[0] - 1e-6).all() and (px <= box[1] + 1e-6).all()
        assert (py >= box[2] - 1e-6).all() and (py <= box[3] + 1e-6).all()
