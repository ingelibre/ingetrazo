# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A broken extension cannot freeze every right-click (#588, @hamzah1985:
an extension written for 0.5.7 stopped working in 0.5.8 and every right-
click froze for about five seconds).

An extension whose right-click entry raises or takes longer than the
budget is left out of the menu for the session and named once in the
status bar; the others keep their entries."""
from __future__ import annotations

import time

from tests.test_extension_menus_grouped import (  # noqa: F401 — fixture
    _context_menu, _extension, _select_a_face, _texts, win)


def _all_texts(menu):
    out = []
    for a in menu.actions():
        if a.menu() is not None:
            out += _all_texts(a.menu())
        elif not a.isSeparator():
            out.append(a.text())
    return out


def _slow_and_broken(win, monkeypatch, calls):
    from views.extension_api import ExtensionApp
    monkeypatch.setattr(type(win), "EXT_CONTEXT_BUDGET_S", 0.05)

    def slow(menu, _sel):
        calls.append("slow")
        time.sleep(0.1)
        menu.addAction("Slow entry", lambda: None)

    def broken(menu, _sel):
        calls.append("broken")
        raise AttributeError("API of 0.5.7")

    ExtensionApp(win, "slow_ext").add_context_menu(slow)
    ExtensionApp(win, "broken_ext").add_context_menu(broken)
    _extension(win, "good_ext", ["Good entry"])


def test_a_slow_or_broken_extension_is_left_out_after_one_try(
        win, monkeypatch):
    calls = []
    _slow_and_broken(win, monkeypatch, calls)
    _select_a_face(win)
    first = _all_texts(_context_menu(win, monkeypatch))
    assert "Good entry" in first
    assert "Broken ext" in win.statusBar().currentMessage()
    second = _all_texts(_context_menu(win, monkeypatch))
    assert calls == ["slow", "broken"]          # not asked a second time
    assert "Good entry" in second and "Slow entry" not in second


def test_flat_mode_isolates_them_too(win, monkeypatch):
    from core import general_settings as gs
    gs.set_value("ext_menus", "flat")
    calls = []
    _slow_and_broken(win, monkeypatch, calls)
    _select_a_face(win)
    _context_menu(win, monkeypatch)
    second = _all_texts(_context_menu(win, monkeypatch))
    assert calls == ["slow", "broken"]
    assert "Good entry" in second
