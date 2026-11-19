# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Cocoa fix must be installed completely before any affected view opens."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core import macos_accessibility as fix


class _Function:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.result


@pytest.fixture
def cocoa(monkeypatch, tmp_path):
    import PySide6
    from PySide6 import QtCore

    app = SimpleNamespace(platformName=lambda: "cocoa",
                          thread=lambda: QtCore.QThread.currentThread())
    monkeypatch.setattr(fix, "sys", SimpleNamespace(platform="darwin", stderr=sys.stderr))
    monkeypatch.setattr(fix, "platform", SimpleNamespace(machine=lambda: "arm64"))
    monkeypatch.setattr(fix, "app_root", lambda: tmp_path)
    monkeypatch.setattr(fix, "is_frozen", lambda: False)
    monkeypatch.setattr(fix, "_library", None)
    monkeypatch.setattr(fix, "_installed", False)
    monkeypatch.setattr(PySide6, "__version__", "6.11.2")
    monkeypatch.setattr(QtCore, "qVersion", lambda: "6.11.2")
    monkeypatch.setattr(QtCore.QCoreApplication, "instance", staticmethod(lambda: app))
    return app


@pytest.fixture
def source(cocoa, tmp_path):
    path = tmp_path / "packaging" / "macos" / "cocoa-accessibility-fix.m"
    path.parent.mkdir(parents=True)
    path.write_text("// native source\n")
    return path


def _native_library(status=0, message=b"unsupported native layout"):
    return SimpleNamespace(
        ingetrazo_install_cocoa_accessibility_fix=_Function(status),
        ingetrazo_cocoa_accessibility_fix_error=_Function(message))


def _must_not_run(*_args, **_kwargs):
    pytest.fail("this operation must not run")


def _macho_library(arch, payload=b"library"):
    cpu_type = {"arm64": 0x0100000C, "x86_64": 0x01000007}[arch]
    return struct.pack("<8I", 0xFEEDFACF, cpu_type, 0, 6, 0, 0, 0, 0) + payload


@pytest.mark.parametrize("system", ["linux", "win32"])
def test_other_platforms_do_not_touch_qt_or_native_code(monkeypatch, system):
    monkeypatch.setattr(fix, "sys", SimpleNamespace(platform=system))
    monkeypatch.setattr(fix, "_validate_runtime", _must_not_run)
    monkeypatch.setattr(fix.ctypes, "CDLL", _must_not_run)
    assert fix.install_cocoa_accessibility_fix(None) is False


def test_non_cocoa_macos_does_not_build_or_load(cocoa, monkeypatch):
    cocoa.platformName = lambda: "offscreen"
    monkeypatch.setattr(fix, "_validate_runtime", _must_not_run)
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", _must_not_run)
    assert fix.install_cocoa_accessibility_fix(cocoa) is False


def test_install_requires_an_initialized_application(cocoa, monkeypatch):
    from PySide6.QtCore import QCoreApplication

    monkeypatch.setattr(QCoreApplication, "instance", staticmethod(lambda: None))
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", _must_not_run)
    with pytest.raises(RuntimeError, match="after creating QApplication"):
        fix.install_cocoa_accessibility_fix(cocoa)


def test_install_before_application_creation_is_reported(cocoa):
    with pytest.raises(RuntimeError, match="after creating QApplication"):
        fix.install_cocoa_accessibility_fix(None)


@pytest.mark.parametrize("binding,qt", [("6.9.0", "6.11.2"), ("6.11.2", "6.12.0")])
def test_both_runtime_versions_are_checked_before_build(cocoa, monkeypatch, binding, qt):
    import PySide6
    from PySide6 import QtCore

    monkeypatch.setattr(PySide6, "__version__", binding)
    monkeypatch.setattr(QtCore, "qVersion", lambda: qt)
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", _must_not_run)
    with pytest.raises(RuntimeError, match="requires PySide6 and Qt 6.11.2"):
        fix.install_cocoa_accessibility_fix(cocoa)


def test_install_requires_python_main_thread(cocoa, monkeypatch):
    monkeypatch.setattr(fix, "threading", SimpleNamespace(
        current_thread=lambda: object(), main_thread=lambda: object()))
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", _must_not_run)
    with pytest.raises(RuntimeError, match="main thread"):
        fix.install_cocoa_accessibility_fix(cocoa)


def test_install_requires_qt_application_thread(cocoa, monkeypatch):
    cocoa.thread = lambda: object()
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", _must_not_run)
    with pytest.raises(RuntimeError, match="main thread"):
        fix.install_cocoa_accessibility_fix(cocoa)


def test_source_launch_builds_before_load_and_keeps_library(cocoa, monkeypatch, tmp_path):
    events = []
    path = tmp_path / fix.LIBRARY_NAME
    native = _native_library()

    def build():
        events.append("build")
        return path

    def load(name):
        events.append("load")
        assert name == str(path)
        return native

    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", build)
    monkeypatch.setattr(fix.ctypes, "CDLL", load)
    assert fix.install_cocoa_accessibility_fix(cocoa) is True
    assert events == ["build", "load"]
    assert fix._library is native
    assert native.ingetrazo_install_cocoa_accessibility_fix.calls == 1
    assert native.ingetrazo_install_cocoa_accessibility_fix.argtypes == []
    assert native.ingetrazo_install_cocoa_accessibility_fix.restype is ctypes.c_int
    assert native.ingetrazo_cocoa_accessibility_fix_error.restype is ctypes.c_char_p
    assert fix.install_cocoa_accessibility_fix(cocoa) is True
    assert events == ["build", "load"]
    assert native.ingetrazo_install_cocoa_accessibility_fix.calls == 1


def test_frozen_launch_requires_bundled_library(cocoa, monkeypatch):
    monkeypatch.setattr(fix, "is_frozen", lambda: True)
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", _must_not_run)
    monkeypatch.setattr(fix.ctypes, "CDLL", _must_not_run)
    with pytest.raises(RuntimeError, match="missing its Cocoa accessibility fix"):
        fix.install_cocoa_accessibility_fix(cocoa)


def test_frozen_launch_loads_bundle_without_compiling(cocoa, monkeypatch, tmp_path):
    monkeypatch.setattr(fix, "is_frozen", lambda: True)
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", _must_not_run)
    path = tmp_path / "resources" / "native" / fix.LIBRARY_NAME
    path.parent.mkdir(parents=True)
    path.write_bytes(b"bundled library")
    loaded = []
    native = _native_library()
    monkeypatch.setattr(fix.ctypes, "CDLL", lambda name: (loaded.append(name) or native))
    assert fix.install_cocoa_accessibility_fix(cocoa) is True
    assert loaded == [str(path)]
    assert fix._library is native


def test_native_install_failure_retains_library_but_does_not_mark_installed(
        cocoa, monkeypatch, tmp_path):
    native = _native_library(status=4, message=b"unsupported axid ivar")
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", lambda: tmp_path / fix.LIBRARY_NAME)
    monkeypatch.setattr(fix.ctypes, "CDLL", lambda _name: native)
    with pytest.raises(RuntimeError, match=r"fix \(4\): unsupported axid ivar"):
        fix.install_cocoa_accessibility_fix(cocoa)
    assert fix._library is native
    assert not fix._installed


def test_load_failure_is_actionable(cocoa, monkeypatch, tmp_path):
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", lambda: tmp_path / fix.LIBRARY_NAME)

    def load(_name):
        raise OSError("incompatible architecture")

    monkeypatch.setattr(fix.ctypes, "CDLL", load)
    with pytest.raises(RuntimeError,
                       match="Rebuild IngeTrazo for this Mac.*incompatible architecture"):
        fix.install_cocoa_accessibility_fix(cocoa)
    assert fix._library is None
    assert not fix._installed


def test_missing_native_exports_fail_before_install(cocoa, monkeypatch, tmp_path):
    native = SimpleNamespace()
    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", lambda: tmp_path / fix.LIBRARY_NAME)
    monkeypatch.setattr(fix.ctypes, "CDLL", lambda _name: native)
    with pytest.raises(RuntimeError, match="library is incompatible"):
        fix.install_cocoa_accessibility_fix(cocoa)
    assert fix._library is native
    assert not fix._installed


def test_missing_library_is_compiled_and_published_atomically(source, monkeypatch, tmp_path):
    output = tmp_path / "build" / "macos" / fix.LIBRARY_NAME
    commands = []

    def compile_library(command, **kwargs):
        commands.append(command)
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        assert not output.exists()
        Path(command[-1]).write_bytes(b"compiled library")

    monkeypatch.setattr(fix.subprocess, "run", compile_library)
    assert fix.build_cocoa_accessibility_fix() == output
    assert output.read_bytes() == b"compiled library"
    assert commands[0][:3] == ["xcrun", "clang", "-dynamiclib"]
    assert "-fno-objc-arc" in commands[0]
    assert commands[0][commands[0].index("-arch") + 1] == "arm64"
    assert str(source) in commands[0]
    assert list(output.parent.iterdir()) == [output]


def test_stale_library_is_rebuilt_before_it_can_be_loaded(source, monkeypatch, tmp_path):
    output = tmp_path / "build" / "macos" / fix.LIBRARY_NAME
    output.parent.mkdir(parents=True)
    output.write_bytes(b"old library")
    os.utime(output, ns=(1_000_000_000, 1_000_000_000))
    os.utime(source, ns=(2_000_000_000, 2_000_000_000))

    def compile_library(command, **_kwargs):
        assert output.read_bytes() == b"old library"
        Path(command[-1]).write_bytes(b"new library")

    monkeypatch.setattr(fix.subprocess, "run", compile_library)
    assert fix.build_cocoa_accessibility_fix() == output
    assert output.read_bytes() == b"new library"


@pytest.mark.parametrize("runtime", ["arm64", "x86_64"])
def test_current_library_does_not_need_a_compiler(source, monkeypatch, tmp_path, runtime):
    monkeypatch.setattr(fix, "platform", SimpleNamespace(machine=lambda: runtime))
    output = tmp_path / "build" / "macos" / fix.LIBRARY_NAME
    output.parent.mkdir(parents=True)
    output.write_bytes(_macho_library(runtime))
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    os.utime(output, ns=(2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(fix.subprocess, "run", _must_not_run)
    assert fix.build_cocoa_accessibility_fix() == output


def test_recent_library_cannot_bypass_architecture_validation(source, monkeypatch, tmp_path):
    output = tmp_path / "build" / "macos" / fix.LIBRARY_NAME
    output.parent.mkdir(parents=True)
    output.write_bytes(_macho_library("arm64"))
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    os.utime(output, ns=(2_000_000_000, 2_000_000_000))
    monkeypatch.setattr(fix, "platform", SimpleNamespace(machine=lambda: "i386"))
    monkeypatch.setattr(fix.subprocess, "run", _must_not_run)
    with pytest.raises(RuntimeError, match="Unsupported macOS build architecture: i386"):
        fix.build_cocoa_accessibility_fix()


@pytest.mark.parametrize("runtime,cached", [("arm64", "x86_64"), ("x86_64", "arm64")])
def test_switching_interpreter_architecture_rebuilds_recent_library(
        source, monkeypatch, tmp_path, runtime, cached):
    monkeypatch.setattr(fix, "platform", SimpleNamespace(machine=lambda: runtime))
    output = tmp_path / "build" / "macos" / fix.LIBRARY_NAME
    output.parent.mkdir(parents=True)
    old_library = _macho_library(cached)
    new_library = _macho_library(runtime)
    output.write_bytes(old_library)
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    os.utime(output, ns=(2_000_000_000, 2_000_000_000))
    commands = []

    def compile_library(command, **_kwargs):
        commands.append(command)
        assert output.read_bytes() == old_library
        assert command[command.index("-arch") + 1] == runtime
        Path(command[-1]).write_bytes(new_library)

    monkeypatch.setattr(fix.subprocess, "run", compile_library)
    assert fix.build_cocoa_accessibility_fix() == output
    assert len(commands) == 1
    assert output.read_bytes() == new_library


@pytest.mark.parametrize("cached", [b"", b"\xcf\xfa\xed\xfe", b"not a Mach-O library"])
def test_recent_invalid_library_is_rebuilt(source, monkeypatch, tmp_path, cached):
    output = tmp_path / "build" / "macos" / fix.LIBRARY_NAME
    output.parent.mkdir(parents=True)
    output.write_bytes(cached)
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    os.utime(output, ns=(2_000_000_000, 2_000_000_000))
    compiled = _macho_library("arm64")

    def compile_library(command, **_kwargs):
        Path(command[-1]).write_bytes(compiled)

    monkeypatch.setattr(fix.subprocess, "run", compile_library)
    assert fix.build_cocoa_accessibility_fix() == output
    assert output.read_bytes() == compiled


def test_compiler_failure_preserves_previous_library_and_reports_stderr(
        source, monkeypatch, tmp_path):
    output = tmp_path / "build" / "macos" / fix.LIBRARY_NAME
    output.parent.mkdir(parents=True)
    output.write_bytes(b"old library")
    os.utime(output, ns=(1_000_000_000, 1_000_000_000))

    def compile_library(command, **_kwargs):
        Path(command[-1]).write_bytes(b"incomplete library")
        raise subprocess.CalledProcessError(1, command, stderr="clang: compilation failed")

    monkeypatch.setattr(fix.subprocess, "run", compile_library)
    with pytest.raises(RuntimeError, match="xcode-select --install.*\nclang: compilation failed"):
        fix.build_cocoa_accessibility_fix()
    assert output.read_bytes() == b"old library"
    assert list(output.parent.iterdir()) == [output]


def test_missing_command_line_tools_are_reported(source, monkeypatch):
    def compile_library(*_args, **_kwargs):
        raise FileNotFoundError("xcrun")

    monkeypatch.setattr(fix.subprocess, "run", compile_library)
    with pytest.raises(RuntimeError, match="Command Line Tools.*xcode-select --install"):
        fix.build_cocoa_accessibility_fix()


def test_missing_source_is_reported(cocoa):
    with pytest.raises(RuntimeError, match="Missing Cocoa accessibility source"):
        fix.build_cocoa_accessibility_fix()


def test_frozen_application_cannot_compile(cocoa, monkeypatch):
    monkeypatch.setattr(fix, "is_frozen", lambda: True)
    with pytest.raises(RuntimeError, match="packaged application cannot build"):
        fix.build_cocoa_accessibility_fix()


def test_build_cli_reports_failure_without_traceback(monkeypatch, capsys):
    def build():
        raise RuntimeError("Command Line Tools are missing")

    monkeypatch.setattr(fix, "build_cocoa_accessibility_fix", build)
    assert fix.main() == 1
    assert "Command Line Tools are missing" in capsys.readouterr().err
