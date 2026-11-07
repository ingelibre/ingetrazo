# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The native GL replay only takes entry points it can call: a driver that
answers an unknown name with 1, 2, 3 or -1 (some Windows wglGetProcAddress)
instead of null leaves the recorded passes to the PySide wrappers."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import views.viewport as viewport  # noqa: E402


@pytest.mark.parametrize("addr", [0, 1, 2, 3, -1, (1 << 64) - 1])
def test_a_bogus_entry_point_is_not_called(addr):
    assert not viewport._callable_proc(addr)


def test_a_real_entry_point_is():
    assert viewport._callable_proc(0x7F12_3456_7000)


class _Ctx:
    def __init__(self, bad):
        self.bad = bad

    def getProcAddress(self, name):
        return 3 if name == self.bad else 0x7F00_0000_1000


class _Native:
    made: list = []

    class GlReplay:
        def __init__(self, addrs):
            _Native.made.append(addrs)


@pytest.mark.parametrize("bad", [None, b"glBindTexture"])
def test_the_replay_is_made_only_from_callable_entries(monkeypatch, bad):
    from core import _native
    monkeypatch.setattr(_native, "native", _Native)
    monkeypatch.setattr(viewport, "_LEAN_NATIVE_REPLAY", True)
    _Native.made = []
    vp = viewport.Viewport(None)
    ctx = _Ctx(bad)
    monkeypatch.setattr(vp, "context", lambda: ctx)
    got = vp._gl_replay()
    if bad is None:
        assert isinstance(got, _Native.GlReplay) and len(_Native.made) == 1
    else:
        assert got is None and _Native.made == []
