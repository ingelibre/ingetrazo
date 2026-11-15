"""The way out on Windows skips the DLLs' exit code, where shiboken's binding
manager could crash on wrappers Qt had already deleted. Everything else about
leaving stays the same on every system."""
import ctypes
from types import SimpleNamespace

import pytest

import main


class _Exited(Exception):
    pass


def _fake_kernel32(calls, result=1):
    def terminate(handle, status):
        calls.append(("terminate", handle, status))
        return result
    return SimpleNamespace(
        GetCurrentProcess=lambda: "this process",
        TerminateProcess=terminate)


def _fake_exit(calls):
    def _exit(status):
        calls.append(("os._exit", status))
        raise _Exited
    return _exit


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_other_systems_leave_with_os_exit(monkeypatch, platform):
    calls = []
    monkeypatch.setattr(main.sys, "platform", platform)
    monkeypatch.setattr(main.os, "_exit", _fake_exit(calls))
    monkeypatch.setattr(
        main, "_terminate_windows_process",
        lambda status: calls.append(("terminate", status)))
    with pytest.raises(_Exited):
        main._exit_now(3)
    assert calls == [("os._exit", 3)]


def test_windows_terminates_with_the_exit_status(monkeypatch):
    calls = []
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.os, "_exit", _fake_exit(calls))
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name: _fake_kernel32(calls), raising=False)
    with pytest.raises(_Exited):
        main._exit_now(3)
    # os._exit stays behind it, for a call that returns instead of ending.
    assert calls == [("terminate", "this process", 3), ("os._exit", 3)]


def test_windows_settings_are_synced_before_terminating(monkeypatch):
    from PySide6.QtCore import QSettings
    calls = []
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.os, "_exit", _fake_exit(calls))
    monkeypatch.setattr(
        QSettings, "sync", lambda self: calls.append(("sync",)))
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name: _fake_kernel32(calls), raising=False)
    with pytest.raises(_Exited):
        main._exit_now(0)
    assert calls[0] == ("sync",)
    assert calls[1][0] == "terminate"


def test_a_status_that_is_not_a_number_leaves_with_zero(monkeypatch):
    calls = []
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.os, "_exit", _fake_exit(calls))
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name: _fake_kernel32(calls), raising=False)
    with pytest.raises(_Exited):
        main._exit_now(None)
    assert calls == [("terminate", "this process", 0), ("os._exit", 0)]


def test_a_negative_status_keeps_its_32_bits(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name: _fake_kernel32(calls), raising=False)
    main._terminate_windows_process(-1)
    assert calls == [("terminate", "this process", 0xFFFFFFFF)]


def test_a_missing_kernel32_falls_back_to_os_exit(monkeypatch):
    calls = []

    def no_dll(name):
        raise OSError("no such library")
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.os, "_exit", _fake_exit(calls))
    monkeypatch.setattr(ctypes, "WinDLL", no_dll, raising=False)
    with pytest.raises(_Exited):
        main._exit_now(2)
    assert calls == [("os._exit", 2)]


def test_a_failed_terminate_falls_back_to_os_exit(monkeypatch):
    calls = []
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.os, "_exit", _fake_exit(calls))
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name: _fake_kernel32(calls, result=0),
        raising=False)
    with pytest.raises(_Exited):
        main._exit_now(4)
    assert calls == [("terminate", "this process", 4), ("os._exit", 4)]
