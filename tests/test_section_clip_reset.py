# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A section plane switched off stops clipping (#1574).

Every frame ends with ``_set_section_clip(True)`` (``_draw_previews_after``),
so the program keeps ``u_clip_count`` and the clip distances of the last
frame. When the next frame has no cut, ``_set_section_clip`` used to return
at once and the old plane went on clipping the model, without a fill."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QVector4D


class _GL:
    def __init__(self):
        self.calls = []

    def glEnable(self, cap):
        self.calls.append(("on", cap))

    def glDisable(self, cap):
        self.calls.append(("off", cap))


class _Program:
    def __init__(self):
        self.uniforms = {}

    def setUniformValue(self, loc, value):
        self.uniforms[loc] = value


def _fake():
    from views.viewport import Viewport
    from views.viewport._support import _MAX_CUT_PLANES
    fake = SimpleNamespace(_gl=_GL(), _program=_Program(),
                           _loc_clip_count="count",
                           _loc_clip_planes=[f"plane{i}" for i in
                                             range(_MAX_CUT_PLANES)])
    fake.clip = lambda on, skip=None: Viewport._set_section_clip(
        fake, on, skip)
    return fake


def _enabled(fake):
    from views.viewport._support import GL_CLIP_DISTANCE0
    state = {}
    for what, cap in fake._gl.calls:
        state[cap] = what == "on"
    return {cap - GL_CLIP_DISTANCE0 for cap, on in state.items() if on}


def test_a_frame_without_cut_clears_the_last_frames_plane():
    fake = _fake()
    fake._clip_vecs = [QVector4D(0, 0, -1, 1.5)]         # frame 1: cut z=1.5
    fake.clip(False)
    fake.clip(True)                                     # end of frame 1
    assert fake._program.uniforms["count"] == 1 and _enabled(fake) == {0}

    fake._clip_vecs = []                                # frame 2: no cut
    fake.clip(False)
    assert fake._program.uniforms["count"] == 0
    assert _enabled(fake) == set()


def test_the_reset_happens_once_per_switch_off():
    fake = _fake()
    fake._clip_vecs = [QVector4D(0, 0, -1, 1.5)]
    fake.clip(True)
    fake._clip_vecs = []
    fake.clip(True)                                     # resets
    fake._gl.calls.clear()
    fake._program.uniforms.clear()
    fake.clip(False)                                    # nothing left to do
    fake.clip(True)
    assert fake._gl.calls == [] and fake._program.uniforms == {}


def test_nothing_happens_when_no_plane_ever_cut():
    fake = _fake()
    fake._clip_vecs = []
    fake.clip(True)
    fake.clip(False)
    assert fake._gl.calls == [] and fake._program.uniforms == {}


def test_the_ground_clip_distance_is_left_alone():
    from views.viewport._support import GL_CLIP_DISTANCE0
    fake = _fake()
    fake._clip_vecs = [QVector4D(0, 0, -1, 1.5)]
    fake.clip(True)
    fake._clip_vecs = []
    fake.clip(False)
    assert ("off", GL_CLIP_DISTANCE0 + 7) not in fake._gl.calls
