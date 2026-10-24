# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DWG → DXF bridge through the LibreDWG satellite (D3).

DWG is never parsed inside the app: the LibreDWG ``dwg2dxf`` command-line
tool runs as an external converter — the same satellite pattern the
former external converter used, and a straight port of IngeCAD's
``formats/dwg_bridge.py``, scars included. The user double-clicks a
``.dwg`` and never sees the DXF.

Search order for the tool: the bundle shipped with IngeTrazo
(``vendor/libredwg/bin``), the system PATH, and — a development-machine
courtesy — the sibling IngeCAD checkout's bundle, so the two projects
share one built LibreDWG. The build reads DWG up to r2018, which is the
format every AutoCAD from 2018 through 2026 writes.

The two DXF repairs are the price of LibreDWG 0.14's output and ezdxf's
strictness, both documented in IngeCAD where they were first paid:
``_strip_null_handles`` (ENDBLK entities with handle 0, rejected even by
recover mode) and ``_dedupe_handles`` (reused handles that make ezdxf
lose the whole drawing when ``*Model_Space``'s is stolen — reported
upstream as LibreDWG#1356).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEventLoop, QObject, QProcess, QTimer

from core.paths import app_root

_VENDOR_BIN = app_root() / "vendor" / "libredwg" / "bin"
#: Development-machine courtesy: the sibling IngeCAD checkout's bundle.
_SIBLING_BIN = (app_root().parent.parent / "ingecad" / "vendor"
                / "libredwg" / "bin")
_TIMEOUT = 300  # seconds; big real-world DWGs convert in well under this


class DwgBridgeError(Exception):
    """A DWG conversion failed or no converter is available.

    ``kind`` tells the caller what to say to the user: ``"unavailable"`` (no
    converter), ``"failed"``, ``"timeout"`` or ``"cancelled"``."""

    def __init__(self, message: str, kind: str = "failed") -> None:
        super().__init__(message)
        self.kind = kind


#: Leading bytes of a native executable, per platform. The repository keeps
#: the LINUX ELF in ``vendor/libredwg/bin`` (release-macos.yml builds the
#: macOS one from the LibreDWG tarball), so on a plain macOS checkout the
#: file is present but cannot run — reporting it as a usable converter was a
#: false "DWG works". A binary built for another OS must be ignored.
_NATIVE_MAGIC = {
    "darwin": (
        b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",   # Mach-O 64/32 little-endian
        b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce",   # Mach-O 64/32 big-endian
        b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",   # universal (fat)
    ),
    "linux": (b"\x7fELF",),
    "win32": (b"MZ",),
}


def _is_native_executable(path: Path) -> bool:
    """True when *path* starts with the magic of the running platform.

    An unknown platform accepts anything (best effort); an unreadable file
    is rejected.
    """
    magic = _NATIVE_MAGIC.get(sys.platform)
    if not magic:
        return True
    try:
        head = path.open("rb").read(4)
    except OSError:
        return False
    return any(head.startswith(m) for m in magic)


def _find_tool(name: str) -> Optional[Path]:
    # Windows ships dwg2dxf.exe (with libredwg-0.dll and libiconv-2.dll
    # beside it, #101); everywhere else the bare name.
    exe = name + ".exe" if sys.platform == "win32" else name
    for base in (_VENDOR_BIN, _SIBLING_BIN):
        bundled = base / exe
        if bundled.is_file() and _is_native_executable(bundled):
            return bundled
    system = shutil.which(name)
    if system and _is_native_executable(Path(system)):
        return Path(system)
    return None


def find_dwg2dxf() -> Optional[Path]:
    return _find_tool("dwg2dxf")


def have_dwg_support() -> bool:
    return find_dwg2dxf() is not None


def _check_output(out_path: Path, returncode: object, log: str) -> None:
    """LibreDWG often exits non-zero on recoverable warnings while still
    writing a usable file — the output's existence is the real verdict."""
    if not out_path.is_file() or out_path.stat().st_size == 0:
        tail = log.strip().splitlines()[-3:]
        raise DwgBridgeError(
            "conversion produced no output: "
            + (" | ".join(tail) or f"rc={returncode}"))


def _run(cmd: list[str], out_path: Path) -> str:
    """Run the converter; return its stderr so callers can inspect warnings."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            # The converter echoes names from the drawing into its warnings,
            # in the file's own codepage, not UTF-8 (a layer called CAÑERÍAS
            # made the decode raise in IngeCAD). Its log is diagnostics —
            # never a reason to fail.
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DwgBridgeError(f"converter timed out: {' '.join(cmd)}",
                             "timeout") from exc
    _check_output(out_path, proc.returncode, proc.stderr or proc.stdout or "")
    return proc.stderr or ""


def _read_dxf_lines(dxf_path: Path) -> list[str]:
    r"""Split an ASCII DXF on "\n" only — NOT ``str.splitlines()``, which
    also breaks on \x0b, \x0c, \x1c-\x1e and \x85. Real drawings carry those
    bytes, splitlines() invents phantom lines, and every tag/value pair after
    the first goes off by one. Latin-1 keeps the byte stream exact."""
    return dxf_path.read_bytes().decode("latin-1").split("\n")


def _write_dxf_lines(dxf_path: Path, lines: list[str]) -> None:
    dxf_path.write_bytes("\n".join(lines).encode("latin-1"))


def _strip_null_handles(dxf_path: Path) -> None:
    """Drop (5, 0) tag pairs: LibreDWG 0.14 emits ENDBLK entities with handle
    0, which ezdxf rejects even in recover mode; with the pair gone, recover
    assigns a fresh handle."""
    lines = _read_dxf_lines(dxf_path)
    out: list[str] = []
    dropped = 0
    i = 0
    while i + 1 < len(lines):   # ASCII DXF is a strict tag/value pair stream
        if lines[i].strip() == "5" and lines[i + 1].strip() == "0":
            dropped += 1
            i += 2
            continue
        out.append(lines[i])
        out.append(lines[i + 1])
        i += 2
    out.extend(lines[i:])
    if dropped:
        _write_dxf_lines(dxf_path, out)


#: Sections whose objects carry a handle in group 5. HEADER is excluded on
#: purpose: there group 5 is the *value* of $HANDSEED, not an object handle.
_HANDLE_SECTIONS = frozenset({"TABLES", "BLOCKS", "ENTITIES", "OBJECTS"})

#: Handles above this are already corrupt (real ones stay far below), so they
#: must not drag the fresh-handle counter into nonsense.
_MAX_SANE_HANDLE = 1 << 32


def _dedupe_handles(dxf_path: Path) -> int:
    """Give a fresh handle to objects that reuse one; returns how many.

    LibreDWG emits some objects (LAYOUT, GROUP, ACDBPLACEHOLDER...) with a
    handle that already belongs to a table record; one collision on handle 2
    (the ``*Model_Space`` BLOCK_RECORD) is enough for ezdxf to refuse the
    file. The first user keeps the handle — table records are written before
    OBJECTS, so the first is the legitimate owner — and later claimants are
    renumbered above every handle in the file. LibreDWG#1356."""
    lines = _read_dxf_lines(dxf_path)

    spots: list[tuple[int, str]] = []       # (index of the value line, handle)
    seed_at: Optional[int] = None
    section: Optional[str] = None
    expecting = False   # a 0/NAME was just seen, its group 5 still pending
    i = 0
    while i + 1 < len(lines):
        code, value = lines[i].strip(), lines[i + 1].strip()
        if code == "0":
            if value == "ENDSEC":
                section = None
            expecting = value not in ("SECTION", "ENDSEC", "EOF")
        elif code == "2" and section is None:
            section = value                 # the 2/<name> after 0/SECTION
        elif code == "9" and value == "$HANDSEED" and i + 3 < len(lines):
            seed_at = i + 3 if lines[i + 2].strip() == "5" else None
        elif code == "5" and expecting and section in _HANDLE_SECTIONS:
            spots.append((i + 1, value))
            expecting = False
        i += 2

    def as_int(handle: str) -> Optional[int]:
        try:
            return int(handle, 16)
        except ValueError:
            return None

    seen: set[str] = set()
    collisions: list[int] = []
    for idx, handle in spots:
        if handle in seen:
            collisions.append(idx)
        else:
            seen.add(handle)
    if not collisions:
        return 0

    used = {h for _, h in spots}
    sane = [n for n in (as_int(h) for _, h in spots)
            if n is not None and n < _MAX_SANE_HANDLE]
    nxt = (max(sane) if sane else 0) + 1
    for idx in collisions:
        while format(nxt, "X") in used:
            nxt += 1
        fresh = format(nxt, "X")
        used.add(fresh)
        lines[idx] = fresh
        nxt += 1
    if seed_at is not None:
        lines[seed_at] = format(nxt, "X")
    _write_dxf_lines(dxf_path, lines)
    return len(collisions)


def _converter_command(tool: Path, dwg_path: Path, out_dxf: Path) -> list[str]:
    return [str(tool), "-y", "-o", str(out_dxf), str(dwg_path)]


def _repair_dxf(dxf_path: Path) -> None:
    _strip_null_handles(dxf_path)
    _dedupe_handles(dxf_path)


def _new_output() -> tuple[Path, Path]:
    """The converter and a fresh output path for it to write.

    The temp file lands in a fresh ASCII-only directory: satellite argv
    encoding is a known gotcha family (the former external
    converter), so the *output* side stays plain even when the drawing's
    name carries accents."""
    tool = find_dwg2dxf()
    if tool is None:
        raise DwgBridgeError("LibreDWG (dwg2dxf) is not available",
                             "unavailable")
    out_dir = Path(tempfile.mkdtemp(prefix="ingetrazo-dwg-"))
    return tool, out_dir / "converted.dxf"


def dwg_to_dxf(dwg_path: Path) -> Path:
    """Convert a DWG to a temporary DXF; returns the DXF path.

    Blocks the calling thread: the path for scripts and headless callers.
    The window uses :class:`DwgConverter`, which keeps the event loop
    running."""
    dwg_path = Path(dwg_path)
    tool, out_dxf = _new_output()
    try:
        _run(_converter_command(tool, dwg_path, out_dxf), out_dxf)
    except DwgBridgeError:
        discard_temp_dxf(out_dxf)
        raise
    _repair_dxf(out_dxf)
    return out_dxf


class DwgConverter(QObject):
    """``dwg2dxf`` in a :class:`QProcess` (#401).

    :meth:`convert` blocks its caller in a local ``QEventLoop``, so it reads
    like :func:`dwg_to_dxf` while the window keeps painting and a Cancel
    button can call :meth:`cancel`. The :data:`_TIMEOUT` limit stays. On any
    failure the temporary directory is removed before the error is raised."""

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._loop: Optional[QEventLoop] = None
        self._out_dxf: Optional[Path] = None
        self._error: Optional[DwgBridgeError] = None
        self._done = True

    def convert(self, dwg_path: Path) -> Path:
        tool, out_dxf = _new_output()
        self._out_dxf = out_dxf
        self._error = None
        self._done = False
        cmd = _converter_command(tool, Path(dwg_path), out_dxf)
        self._timer.start(int(_TIMEOUT * 1000))
        self._proc.start(cmd[0], cmd[1:])
        if not self._done:
            self._loop = QEventLoop(self)
            self._loop.exec()
            self._loop = None
        if self._error is None:
            try:
                _repair_dxf(out_dxf)
            except OSError as exc:
                self._error = DwgBridgeError(
                    f"cannot read the converted DXF: {exc}")
        if self._error is not None:
            discard_temp_dxf(out_dxf)
            raise self._error
        return out_dxf

    def cancel(self) -> None:
        self._stop(DwgBridgeError("conversion cancelled", "cancelled"))

    def _stop(self, error: DwgBridgeError) -> None:
        """End the run with *error* and kill the process if it still lives."""
        if self._done:
            return
        self._settle(error)
        if self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()
            self._proc.waitForFinished(5000)

    def _settle(self, error: Optional[DwgBridgeError]) -> None:
        self._done = True
        self._error = error
        self._timer.stop()
        if self._loop is not None:
            self._loop.quit()

    def _on_timeout(self) -> None:
        self._stop(DwgBridgeError(
            f"converter timed out after {_TIMEOUT:g} s", "timeout"))

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self._stop(DwgBridgeError(
                "the converter could not be started: "
                + self._proc.errorString()))

    def _on_finished(self, code: int, _status: QProcess.ExitStatus) -> None:
        if self._done:
            return
        log = bytes(self._proc.readAll().data()).decode("utf-8", "replace")
        assert self._out_dxf is not None
        try:
            _check_output(self._out_dxf, code, log)
        except DwgBridgeError as exc:
            self._settle(exc)
        else:
            self._settle(None)


def discard_temp_dxf(dxf_path: Path) -> None:
    """Remove a directory :func:`dwg_to_dxf` made, once its DXF is read into
    memory — /tmp is a tmpfs on most desktops, and a leaked 50 MB DXF per
    opened drawing is 50 MB of RAM that never comes back. Recognised by
    prefix and no other way: tests hand back fixture paths that must
    survive."""
    parent = Path(dxf_path).parent
    if parent.name.startswith("ingetrazo-dwg-"):
        shutil.rmtree(parent, ignore_errors=True)
