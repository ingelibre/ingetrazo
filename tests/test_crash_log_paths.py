# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The black-box logs never depend on the install folder being writable,
and never touch a missing sys.stderr (the v0.3.8/v0.3.9 Windows startup
crash: installed under Program Files, 'sys.stderr is None')."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from core import paths


@pytest.fixture
def state_home(tmp_path, monkeypatch):
    d = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(d))
    monkeypatch.setenv("LOCALAPPDATA", str(d))
    return d


def test_user_log_dir_is_writable_and_outside_the_app(state_home):
    d = paths.user_log_dir()
    assert d.is_absolute() and d.is_dir()
    assert not str(d).startswith(str(paths.app_root()))
    if not sys.platform.startswith("win") and sys.platform != "darwin":
        assert d == state_home / "ingetrazo"
    (d / "probe").write_text("x", encoding="utf-8")


def test_crash_log_opens_with_a_read_only_cwd_and_no_stderr(tmp_path, state_home, monkeypatch):
    ro = tmp_path / "program-files"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    monkeypatch.chdir(ro)
    monkeypatch.setattr(sys, "stderr", None)
    try:
        if os.access(ro, os.W_OK):
            pytest.skip("running as a user that writes anywhere")
        with pytest.raises(PermissionError):
            open("ingetrazo-crash.log", "a")          # the old behaviour
        fh = paths.open_crash_log()
        assert fh is not None
        fh.write("ok\n")
        fh.close()
        assert (paths.user_log_dir() / "ingetrazo-crash.log").read_text().endswith("ok\n")
        # the startup rule: a handle → faulthandler on it; none → only if stderr
        import faulthandler
        fh = paths.open_crash_log()
        assert fh is not None
        faulthandler.enable(file=fh)
        faulthandler.disable()
        fh.close()
    finally:
        ro.chmod(stat.S_IRWXU)


def test_failed_commands_log_into_the_user_folder(state_home):
    from core.history import Command, History
    from core.scene import Scene

    class _Boom(Command):
        def do(self, scene):
            raise ValueError("kaboom")

        def undo(self, scene):
            pass

    hist = History(Scene())
    hist.execute(_Boom())
    assert hist.last_error and "kaboom" in hist.last_error
    log = Path(hist.default_error_log())
    assert log.parent == paths.user_log_dir()
    assert "kaboom" in log.read_text(encoding="utf-8")


def test_no_default_writes_land_in_the_working_directory(tmp_path, state_home, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from core.history import History
    assert not Path("ingetrazo-errors.log").exists()
    assert Path(History.default_error_log()).is_absolute()
