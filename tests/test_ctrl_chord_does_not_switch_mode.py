# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl+Z (or any Ctrl shortcut) must not switch a tool's Ctrl mode (#342,
@pacaeiro). The Protractor's guides, Scale's «about the centre» and the
Rectangle's «from the centre» toggled on the Ctrl PRESS, so undoing flipped
them silently. They still toggle on the press — the cursor, the anchor and
the pencil badge change at once — and a Ctrl that turns out to be part of a
shortcut takes it back on the release, as Move, Rotate and Flip do."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from tools.protractor import ProtractorTool
from tools.rectangle import RectangleTool
from tools.scale import ScaleTool


class _VP:
    """Just what the Ctrl handling touches; ``alone`` is what the real
    viewport's ctrl_tapped() answers on the release."""

    def __init__(self, alone: bool) -> None:
        self.alone = alone

    def ctrl_tapped(self) -> bool:
        return self.alone

    def flash_status(self, *a, **k) -> None:
        pass

    def update(self) -> None:
        pass

    def refresh_status_hint(self) -> None:
        pass

    def _apply_tool_cursor(self) -> None:
        pass


CASES = [
    (ProtractorTool, "_guides"),
    (ScaleTool, "about_center"),
    (RectangleTool, "_from_center"),
]


@pytest.mark.parametrize("cls, attr", CASES)
def test_a_ctrl_tap_switches_the_mode(cls, attr):
    tool, vp = cls(), _VP(alone=True)
    before = getattr(tool, attr)
    assert tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    assert getattr(tool, attr) is (not before)       # at once, on the press
    assert tool.on_key_release(vp, Qt.Key_Control)
    assert getattr(tool, attr) is (not before)       # and it stays


@pytest.mark.parametrize("cls, attr", CASES)
def test_ctrl_z_leaves_the_mode_as_it_was(cls, attr):
    tool, vp = cls(), _VP(alone=False)                # Ctrl+Z: not alone
    before = getattr(tool, attr)
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_key_release(vp, Qt.Key_Control)
    assert getattr(tool, attr) is before
