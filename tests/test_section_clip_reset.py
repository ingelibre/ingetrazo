# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Deactivating the last section plane must stop clipping the model (#1574).

Every frame ends with the clip switched on (``_draw_previews_after`` ends
with ``_set_section_clip(True)``). When the next frame has no active cut,
``_clip_vecs`` is empty and ``_set_section_clip`` used to return early,
leaving the stale ``u_clip_count`` and ``GL_CLIP_DISTANCE0`` behind — so
the old plane kept cutting the model, with no fill drawn. The reset must
happen even when there is nothing left to clip.
"""
from __future__ import annotations

from PySide6.QtGui import QVector4D

from views.viewport._support import GL_CLIP_DISTANCE0, _MAX_CUT_PLANES
from views.viewport.sections import SectionPlaneMixin


class _FakeProgram:
    """Records the uniform values ``_set_section_clip`` writes."""

    def __init__(self):
        self.values = {}

    def setUniformValue(self, loc, value):
        self.values[loc] = value


class _FakeGL:
    """Records which clip distances are enabled."""

    def __init__(self):
        self.enabled = set()

    def glEnable(self, cap):
        self.enabled.add(cap)

    def glDisable(self, cap):
        self.enabled.discard(cap)


def _mixin():
    obj = object.__new__(SectionPlaneMixin)
    obj._program = _FakeProgram()
    obj._gl = _FakeGL()
    obj._loc_clip_planes = [("plane", i) for i in range(_MAX_CUT_PLANES)]
    obj._loc_clip_count = ("count",)
    return obj


def test_deactivated_section_stops_clipping():
    vp = _mixin()
    vp._clip_vecs = [QVector4D(0, 0, -1, 1.5)]
    vp._set_section_clip(True)
    assert vp._program.values[vp._loc_clip_count] == 1
    assert GL_CLIP_DISTANCE0 in vp._gl.enabled

    # The cut is switched off: no active plane any more.
    vp._clip_vecs = []
    vp._set_section_clip(False)
    assert vp._program.values[vp._loc_clip_count] == 0
    assert GL_CLIP_DISTANCE0 not in vp._gl.enabled


def test_no_cut_from_the_start_leaves_clip_off():
    vp = _mixin()
    vp._clip_vecs = []
    vp._set_section_clip(True)
    assert vp._program.values[vp._loc_clip_count] == 0
    assert not vp._gl.enabled

    # ``_clip_vecs`` is None before the first frame computed it.
    vp2 = _mixin()
    vp2._set_section_clip(False)
    assert vp2._program.values[vp2._loc_clip_count] == 0
    assert not vp2._gl.enabled
