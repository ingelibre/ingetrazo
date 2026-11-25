# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Install the native Cocoa accessibility ownership fix before building views.

The shim contains only Objective-C callbacks: it must remain loaded for the
rest of the process, including Qt's shutdown. Source launches build it with
Apple's Command Line Tools; frozen applications carry the compiled library.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile
import threading

from core.paths import app_root, is_frozen


QT_VERSION = "6.11.2"
LIBRARY_NAME = "libingetrazo_cocoa_accessibility.dylib"

# Do not unload a library whose function pointers are installed in Qt's
# Objective-C class. Keep it even if its install function reports an error.
_library = None
_installed = False


def _library_matches_architecture(path: Path, arch: str) -> bool:
    """Accept only a thin 64-bit Mach-O library for this interpreter's CPU."""
    try:
        with path.open("rb") as library:
            header = library.read(8)
    except OSError:
        return False
    if len(header) != 8:
        return False
    byte_order = {b"\xcf\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">"}.get(header[:4])
    if byte_order is None:
        return False
    cpu_type = struct.unpack(byte_order + "I", header[4:])[0]
    return cpu_type == {"arm64": 0x0100000C, "x86_64": 0x01000007}[arch]


def build_cocoa_accessibility_fix() -> Path:
    """Compile the shim when absent/stale and return its source-build path."""
    if sys.platform != "darwin":
        raise RuntimeError("The Cocoa accessibility fix can only be built on macOS.")
    if is_frozen():
        raise RuntimeError("A packaged application cannot build its accessibility fix; "
                           "rebuild or reinstall IngeTrazo.")

    root = app_root()
    source = root / "packaging" / "macos" / "cocoa-accessibility-fix.m"
    output = root / "build" / "macos" / LIBRARY_NAME
    if not source.is_file():
        raise RuntimeError(f"Missing Cocoa accessibility source: {source}. "
                           "Use a complete IngeTrazo source checkout.")
    arch = platform.machine()
    if arch not in ("arm64", "x86_64"):
        raise RuntimeError(f"Unsupported macOS build architecture: {arch}.")
    if (output.is_file()
            and output.stat().st_mtime_ns >= source.stat().st_mtime_ns
            and _library_matches_architecture(output, arch)):
        return output

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Publish only a complete library; a failed compile must never leave
        # an empty or partly linked file that a later launch could load.
        with tempfile.TemporaryDirectory(prefix=".cocoa-fix-", dir=output.parent) as work:
            temporary_output = Path(work) / LIBRARY_NAME
            command = ["xcrun", "clang", "-dynamiclib", "-fno-objc-arc", "-O2",
                       "-Wall", "-Wextra", "-arch", arch,
                       "-mmacosx-version-min=12.0", "-install_name", f"@rpath/{LIBRARY_NAME}",
                       "-framework", "Foundation",
                       str(source), "-o", str(temporary_output)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            temporary_output.replace(output)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise RuntimeError(
            "Could not compile the Cocoa accessibility fix. Install Apple's "
            "Command Line Tools with 'xcode-select --install', then retry. "
            f"Compiler output:\n{detail}") from error
    except OSError as error:
        raise RuntimeError(
            "Could not build the Cocoa accessibility fix. Ensure Apple's "
            "Command Line Tools are installed ('xcode-select --install') and "
            f"the build directory is writable: {output.parent}. {error}") from error
    return output


def _validate_runtime(app) -> None:
    import PySide6
    from PySide6.QtCore import QCoreApplication, QThread, qVersion

    if QCoreApplication.instance() is not app:
        raise RuntimeError("Install the Cocoa accessibility fix after creating QApplication.")
    qt_version = qVersion()
    if PySide6.__version__ != QT_VERSION or qt_version != QT_VERSION:
        raise RuntimeError(
            f"The Cocoa accessibility fix requires PySide6 and Qt {QT_VERSION}; "
            f"found PySide6 {PySide6.__version__}, Qt {qt_version}. "
            "Run python -m pip install -r requirements.txt with the application interpreter.")
    if (threading.current_thread() is not threading.main_thread()
            or QThread.currentThread() != app.thread()):
        raise RuntimeError("Install the Cocoa accessibility fix on the application's main thread.")


def install_cocoa_accessibility_fix(app) -> bool:
    """Install once for the supported Cocoa runtime; fail before opening views."""
    global _library, _installed
    if sys.platform != "darwin":
        return False
    if app is None:
        raise RuntimeError("Install the Cocoa accessibility fix after creating QApplication.")
    if app.platformName() != "cocoa":
        return False
    _validate_runtime(app)
    if _installed:
        return True

    if is_frozen():
        library_path = app_root() / "resources" / "native" / LIBRARY_NAME
        if not library_path.is_file():
            raise RuntimeError(
                f"The application is missing its Cocoa accessibility fix: {library_path}. "
                "Rebuild or reinstall IngeTrazo.")
    else:
        library_path = build_cocoa_accessibility_fix()

    if _library is None:
        try:
            _library = ctypes.CDLL(str(library_path))
        except OSError as error:
            raise RuntimeError(
                f"Could not load the Cocoa accessibility fix: {library_path}. "
                f"Rebuild IngeTrazo for this Mac. {error}") from error
    try:
        install = _library.ingetrazo_install_cocoa_accessibility_fix
        install.argtypes = []
        install.restype = ctypes.c_int
        error_message = _library.ingetrazo_cocoa_accessibility_fix_error
        error_message.argtypes = []
        error_message.restype = ctypes.c_char_p
    except AttributeError as error:
        raise RuntimeError("The Cocoa accessibility library is incompatible; "
                           "rebuild or reinstall IngeTrazo.") from error

    status = install()
    if status:
        detail = error_message()
        message = detail.decode("utf-8", errors="replace") if detail else "unsupported Qt runtime"
        raise RuntimeError(f"Could not install the Cocoa accessibility fix ({status}): {message}")
    _installed = True
    return True


def main() -> int:
    try:
        output = build_cocoa_accessibility_fix()
    except RuntimeError as error:
        print(f"IngeTrazo: {error}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
