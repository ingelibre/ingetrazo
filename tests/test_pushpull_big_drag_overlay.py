# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Push/Pull on a big mesh drags with the overlay from the first frame
(night of 19-11, Marco: «sí, hazlo»): its stage was slower than
_SLOW_STAGE_S anyway — the first move froze ~2 s in a 9 674-face group of
the Plaza, and the rest of the drag showed the overlay regardless. A mesh
whose last stage was slow starts on the overlay too. The release runs the
pipeline as always, so the result is the commit's; smaller meshes stage as
before. The distance inference keeps each unchanged mesh's positions from
one drag to the next."""
from __future__ import annotations

import math

import numpy as np
import pytest

from tests.test_pushpull_staged_preview import (
    _canon, _direct, _frame, _split_top, _spy_mutate)
from tests.test_pushpull_ux import _ctx, _StubViewport
from tools.pushpull import PushPullTool


def _start(build, big=None):
    scene, face = build()
    vp = _StubViewport(scene)
    tool = PushPullTool()
    tool._SLOW_STAGE_S = math.inf
    if big is not None:
        tool._BIG_STAGE_FACES = big
    tool.hovered_face = face
    tool.on_click(_ctx(vp))
    assert tool.dragging and tool._attached and not tool._prism_cap
    return scene, vp, tool


@pytest.mark.parametrize("dists", [[0.5, 1.2, 0.8], [-0.6, -1.1], [0.4, -0.9, 1.3]])
def test_a_big_mesh_drags_on_the_overlay_and_commits_the_same(monkeypatch, dists):
    scene, vp, tool = _start(_split_top, big=1)
    clean = _canon(scene)
    serial = scene.mesh._mut_serial
    calls = _spy_mutate(monkeypatch, tool)
    for d in dists:
        _frame(tool, vp, d)
        assert tool._stage_d is None, "a big mesh staged"
        assert tool.preview_faces(), "no overlay"
        assert _canon(scene) == clean and scene.mesh._mut_serial == serial
    tool._commit(vp)
    assert calls == [dists[-1]]              # the pipeline, once, at release
    assert _canon(scene) == _canon(_direct(_split_top, dists[-1]))


def test_a_mesh_under_the_size_stages_as_before(monkeypatch):
    scene, vp, tool = _start(_split_top)     # the default size: far above it
    assert len(scene.mesh.faces) < tool._BIG_STAGE_FACES
    _frame(tool, vp, 0.5)
    assert tool._stage_d == 0.5 and tool.preview_faces() == []
    assert _canon(scene) == _canon(_direct(_split_top, 0.5))


def test_a_mesh_whose_stage_was_slow_starts_on_the_overlay_next_time():
    scene, face = _split_top()
    vp = _StubViewport(scene)

    def drag(slow_s):
        tool = PushPullTool()
        tool._SLOW_STAGE_S = slow_s
        tool.hovered_face = next(f for f in scene.faces
                                 if f is face or f.vertices == face.vertices)
        tool.on_click(_ctx(vp))
        _frame(tool, vp, 0.5)
        staged = tool._stage_d is not None
        tool.on_cancel(vp)
        return staged

    assert drag(0.0) is True                 # it staged, and it was slow
    assert scene.mesh in PushPullTool._slow_meshes
    assert drag(math.inf) is False           # next time: the overlay
    # Another mesh does not inherit it.
    other, _f = _split_top()
    assert other.mesh not in PushPullTool._slow_meshes


def test_the_inference_keeps_an_unchanged_meshs_positions(monkeypatch):
    scene, vp, tool = _start(_split_top, big=1)
    mesh = scene.mesh
    PushPullTool._infer_memo.pop(mesh, None)
    reads = []
    real = np.fromiter

    def spy(*a, **k):
        reads.append(1)
        return real(*a, **k)

    import tools.pushpull as pp
    monkeypatch.setattr(pp.np if hasattr(pp, "np") else np, "fromiter", spy)
    vp._world_to_pixel = lambda p: None      # nothing on screen to engage
    ctx = _ctx(vp)
    first = tool._infer_reference_distance(ctx)
    n1 = len(reads)
    held = PushPullTool._infer_memo.get(mesh)
    assert held is not None and held[0][0] == mesh._mut_serial
    tool._infer_cache = None                 # a new drag
    second = tool._infer_reference_distance(ctx)
    assert second == first
    assert len(reads) == n1, "the unchanged mesh was read again"
    # An edit: read again, and the new positions are the ones used.
    v = mesh.vertices[0]
    mesh.place_vertex(v, v.position)
    tool._infer_cache = None
    tool._infer_reference_distance(ctx)
    assert len(reads) > n1
    assert PushPullTool._infer_memo[mesh][0][0] == mesh._mut_serial
    arr = PushPullTool._infer_memo[mesh][1][1]
    want = np.array([[p.x(), p.y(), p.z()]
                     for p in (u.position for u in mesh.vertices)])
    assert np.array_equal(arr, want)
