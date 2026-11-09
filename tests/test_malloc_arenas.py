# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The arena cap (core.malloc_arenas) applies on Linux with glibc and is a
no-op elsewhere; main.py calls it before anything else allocates."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core import malloc_arenas


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc only")
def test_it_applies_on_linux():
    assert malloc_arenas.limit() is True


def test_it_does_nothing_elsewhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert malloc_arenas.limit() is False


def test_main_calls_it_before_the_crash_log_and_qt():
    src = (Path(__file__).resolve().parents[1] / "main.py").read_text("utf-8")
    call = src.index("malloc_arenas.limit()")
    assert call < src.index("open_crash_log()")
    assert call < src.index("from PySide6")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="glibc only")
def test_trim_runs_on_linux():
    assert malloc_arenas.trim() is True


def test_trim_does_nothing_elsewhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert malloc_arenas.trim() is False
