# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Unticking the section that cuts shows the whole model in the same frame.

The main shader cuts with ``u_clip_count`` planes, a uniform the program
keeps from one frame to the next. ``_set_section_clip`` did nothing at all
when no plane cuts, so the count the last cut frame left set stayed — and the
faces, drawn before the pass that switched the cut off, were still clipped in
the first frame after the section was unticked (or View ▸ Section Cuts
turned off): half a model until something repainted it again.

Seen with the AI bridge's screenshot: with a plane active the picture is
cut; after unticking it, the faces were still cut (the edges, drawn later,
were whole). Here the GL calls are recorded, not drawn.
"""
from __future__ import annotations

from PySide6.QtGui import QVector4D

from views.viewport._support import GL_CLIP_DISTANCE0
from views.viewport.sections import SectionPlaneMixin


class _Program:
    """Records the uniforms the viewport sets, the way the program keeps them."""

    def __init__(self):
        self.uniforms = {}

    def setUniformValue(self, loc, value):
        self.uniforms[loc] = value


class _GL:
    def __init__(self):
        self.enabled = set()

    def glEnable(self, cap):
        self.enabled.add(cap)

    def glDisable(self, cap):
        self.enabled.discard(cap)


class _Viewport(SectionPlaneMixin):
    COUNT = 100

    def __init__(self):
        self._program = _Program()
        self._gl = _GL()
        self._loc_clip_planes = list(range(7))
        self._loc_clip_count = self.COUNT
        self._clip_vecs = []

    def frame(self, n_planes: int) -> None:
        """What a frame starts with: the planes that cut now."""
        self._clip_vecs = [QVector4D(1.0, 0.0, 0.0, float(i)) for i in range(n_planes)]

    @property
    def count(self):
        return self._program.uniforms.get(self.COUNT)


def test_the_cut_a_frame_left_set_is_cleared_by_the_next_frames_first_pass():
    vp = _Viewport()
    vp.frame(1)                          # a section cuts
    vp._set_section_clip(True)
    assert vp.count == 1 and GL_CLIP_DISTANCE0 in vp._gl.enabled
    # (a pass that ends with the cut still on: the guides, the figures, a fill's edge…)
    vp.frame(0)                          # the section is unticked: nothing cuts now
    vp._set_section_clip(True)           # the pass before the faces
    assert vp.count == 0, "the faces of the first frame without a cut were still clipped"
    assert GL_CLIP_DISTANCE0 not in vp._gl.enabled


def test_a_box_leaves_nothing_set_either():
    vp = _Viewport()
    vp.frame(6)                          # a section box: six planes
    vp._set_section_clip(True)
    assert vp.count == 6
    vp.frame(0)
    vp._set_section_clip(False)          # (whichever call comes first clears it)
    assert vp.count == 0
    assert not (vp._gl.enabled & {GL_CLIP_DISTANCE0 + i for i in range(6)})


def test_with_a_cut_nothing_changes():
    vp = _Viewport()
    vp.frame(2)
    vp._set_section_clip(True, skip=0)
    assert vp.count == 2
    assert GL_CLIP_DISTANCE0 not in vp._gl.enabled and GL_CLIP_DISTANCE0 + 1 in vp._gl.enabled
    vp._set_section_clip(False)
    assert vp.count == 0 and not vp._gl.enabled


def test_a_model_that_was_never_cut_costs_no_gl_calls():
    vp = _Viewport()
    for _ in range(3):
        vp._set_section_clip(True)
        vp._set_section_clip(False)
    assert vp._program.uniforms == {} and vp._gl.enabled == set()


def test_cleared_once_not_every_call():
    vp = _Viewport()
    vp.frame(1)
    vp._set_section_clip(True)
    vp.frame(0)
    vp._set_section_clip(True)
    assert vp.count == 0
    vp._program.uniforms.clear()
    vp._set_section_clip(False)
    assert vp._program.uniforms == {}, "nothing left to clear: no more uniform calls"
