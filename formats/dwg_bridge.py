# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""DWG → DXF bridge through the LibreDWG satellite (D3).

DWG is never parsed inside the app: the LibreDWG ``dwg2dxf`` command-line
tool runs as an external converter — the same satellite pattern skp2dae
uses, and a straight port of IngeCAD's ``formats/dwg_bridge.py``, scars
included. The user double-clicks a ``.dwg`` and never sees the DXF.

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
import tempfile
from pathlib import Path
from typing import Optional

from core.paths import app_root

_VENDOR_BIN = app_root() / "vendor" / "libredwg" / "bin"
#: Development-machine courtesy: the sibling IngeCAD checkout's bundle.
_SIBLING_BIN = (app_root().parent.parent / "ingecad" / "vendor"
                / "libredwg" / "bin")
_TIMEOUT = 300  # seconds; big real-world DWGs convert in well under this


class DwgBridgeError(Exception):
    """A DWG conversion failed or no converter is available."""


def _find_tool(name: str) -> Optional[Path]:
    for base in (_VENDOR_BIN, _SIBLING_BIN):
        bundled = base / name
        if bundled.is_file():
            return bundled
    system = shutil.which(name)
    return Path(system) if system else None


def find_dwg2dxf() -> Optional[Path]:
    return _find_tool("dwg2dxf")


def have_dwg_support() -> bool:
    return find_dwg2dxf() is not None


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
        raise DwgBridgeError(f"converter timed out: {' '.join(cmd)}") from exc
    # LibreDWG often exits non-zero on recoverable warnings while still
    # writing a usable file — the output's existence is the real verdict.
    if not out_path.is_file() or out_path.stat().st_size == 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        raise DwgBridgeError(
            "conversion produced no output: "
            + (" | ".join(tail) or f"rc={proc.returncode}"))
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


def dwg_to_dxf(dwg_path: Path) -> Path:
    """Convert a DWG to a temporary DXF; returns the DXF path.

    The temp file lands in a fresh ASCII-only directory: satellite argv
    encoding is a known gotcha family (skp2dae), so the *output* side stays
    plain even when the drawing's name carries accents."""
    tool = find_dwg2dxf()
    if tool is None:
        raise DwgBridgeError("LibreDWG (dwg2dxf) is not available")
    dwg_path = Path(dwg_path)
    out_dir = Path(tempfile.mkdtemp(prefix="ingetrazo-dwg-"))
    out_dxf = out_dir / "converted.dxf"
    _run([str(tool), "-y", "-o", str(out_dxf), str(dwg_path)], out_dxf)
    _strip_null_handles(out_dxf)
    _dedupe_handles(out_dxf)
    return out_dxf


def discard_temp_dxf(dxf_path: Path) -> None:
    """Remove a directory :func:`dwg_to_dxf` made, once its DXF is read into
    memory — /tmp is a tmpfs on most desktops, and a leaked 50 MB DXF per
    opened drawing is 50 MB of RAM that never comes back. Recognised by
    prefix and no other way: tests hand back fixture paths that must
    survive."""
    parent = Path(dxf_path).parent
    if parent.name.startswith("ingetrazo-dwg-"):
        shutil.rmtree(parent, ignore_errors=True)
