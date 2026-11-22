# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The display ground's half-space (#1218) clips in hardware.

It was a ``discard`` at the top of basic.frag, paid by every fragment of
every frame even with the ground hidden: ~7 ms of each zoom frame on
Marco's plaza (Radeon 780M, 20-11). It is now ``gl_ClipDistance[7]`` in
basic.vert, enabled only around the halves of a frame that draws the
ground. What it keeps is checked by the renders of test_background_style."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

SHADERS = Path(__file__).resolve().parent.parent / "resources" / "shaders"


def _code(name):
    """The shader without its comments."""
    text = (SHADERS / name).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def test_no_fragment_of_the_main_program_pays_for_the_ground():
    frag = _code("basic.frag")
    assert "u_style_ground_clip" not in frag
    vert = _code("basic.vert")
    assert re.search(r"gl_ClipDistance\[7\]\s*=\s*dot\(world,\s*"
                     r"u_style_ground_clip\)", vert)
    assert re.search(r"out float gl_ClipDistance\[8\]", vert)


class _GL:
    def __init__(self):
        self.calls = []

    def glEnable(self, cap):
        self.calls.append(("on", cap))

    def glDisable(self, cap):
        self.calls.append(("off", cap))


def _fake():
    from views.viewport import Viewport
    fake = SimpleNamespace(_gl=_GL())
    fake._set_ground_clip_hw = (
        lambda on: Viewport._set_ground_clip_hw(fake, on))
    fake._without = (
        lambda fn, *a, **k: Viewport._without_ground_clip_hw(fake, fn, *a,
                                                              **k))
    return fake


def test_the_plane_is_switched_only_when_it_changes():
    from views.viewport._support import GL_CLIP_DISTANCE0
    fake = _fake()
    seven = GL_CLIP_DISTANCE0 + 7
    fake._set_ground_clip_hw(False)                 # already off
    assert fake._gl.calls == []
    fake._set_ground_clip_hw(True)
    fake._set_ground_clip_hw(True)
    fake._set_ground_clip_hw(False)
    assert fake._gl.calls == [("on", seven), ("off", seven)]


def test_other_programs_run_with_the_plane_off_and_get_it_back():
    from views.viewport._support import GL_CLIP_DISTANCE0
    seven = GL_CLIP_DISTANCE0 + 7
    fake = _fake()
    fake._set_ground_clip_hw(True)
    seen = []
    fake._without(lambda: seen.append(fake._ground_clip_hw))
    assert seen == [False] and fake._ground_clip_hw
    assert fake._gl.calls == [("on", seven), ("off", seven), ("on", seven)]
    fake._set_ground_clip_hw(False)
    fake._gl.calls.clear()
    fake._without(lambda: None)                    # off: nothing to do
    assert fake._gl.calls == []
