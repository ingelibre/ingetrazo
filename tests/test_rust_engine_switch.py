# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The experimental Rust engine is OFF unless Preferences turns it on, and
INGETRAZO_RUST overrides the preference either way (tests, benches)."""
from __future__ import annotations

import importlib

import pytest

import core._native as _native
from core import general_settings


@pytest.fixture
def fresh(monkeypatch):
    """A newly imported core._native (``native`` is fixed per session)."""
    def make():
        _native.__dict__.pop("native", None)
        return importlib.reload(_native)
    saved = _native.__dict__.get("native", _native)
    yield make
    general_settings.set_value(_native.SETTING, "0")
    make()
    if saved is not _native:
        _native.native = saved      # what the rest of the session saw


def test_off_by_default(fresh, monkeypatch):
    monkeypatch.delenv("INGETRAZO_RUST", raising=False)
    general_settings.set_value(_native.SETTING, "0")
    mod = fresh()
    assert mod.native is None
    assert mod.engine() == "Python"


def test_preference_turns_it_on(fresh, monkeypatch):
    if _native.available() is None:
        pytest.skip("native module not built")
    monkeypatch.delenv("INGETRAZO_RUST", raising=False)
    general_settings.set_value(_native.SETTING, "1")
    mod = fresh()
    assert mod.native is not None
    assert mod.engine() == "Rust"


@pytest.mark.parametrize("env,pref,on", [("0", "1", False), ("1", "0", True)])
def test_environment_overrides_preference(fresh, monkeypatch, env, pref, on):
    if on and _native.available() is None:
        pytest.skip("native module not built")
    monkeypatch.setenv("INGETRAZO_RUST", env)
    general_settings.set_value(_native.SETTING, pref)
    mod = fresh()
    assert (mod.native is not None) is on


def test_a_start_that_never_drew_turns_the_engine_off(monkeypatch):
    """The start guard: with the engine on, a start marks itself under way
    and the first drawn frame clears the mark; a start that finds the mark
    still there (the last one never got to the window) goes back to the
    normal engine, saved, and says so once."""
    monkeypatch.delenv("INGETRAZO_RUST", raising=False)
    try:
        general_settings.set_value(_native.SETTING, "1")
        general_settings.set_value(_native.STARTING, "0")
        assert _native.start_guard([]) is False
        assert general_settings.value(_native.STARTING) == "1"
        _native.start_ok()                         # the window drew
        assert general_settings.value(_native.STARTING) == "0"
        assert _native.start_guard([]) is False    # a good start again
        # ... and this one dies before its first frame.
        assert _native.start_guard([]) is True
        assert general_settings.value(_native.SETTING) == "0"
        assert general_settings.value(_native.STARTING) == "0"
        assert _native.start_guard([]) is False    # off now: nothing to say
    finally:
        general_settings.set_value(_native.SETTING, "0")
        general_settings.set_value(_native.STARTING, "0")


def test_python_engine_flag_wins_for_one_run(monkeypatch):
    monkeypatch.delenv("INGETRAZO_RUST", raising=False)
    try:
        general_settings.set_value(_native.SETTING, "1")
        assert _native.start_guard(["--python-engine"]) is False
        import os
        assert os.environ["INGETRAZO_RUST"] == "0"
        assert general_settings.value(_native.SETTING) == "1"   # kept
        assert _native.wanted() is False
    finally:
        monkeypatch.delenv("INGETRAZO_RUST", raising=False)
        general_settings.set_value(_native.SETTING, "0")
        general_settings.set_value(_native.STARTING, "0")
