#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Run the test suite in batches of files, one process each, and print ONE
summary line in pytest's own words ("4283 passed, 12 skipped in …").

Why (07-10-2026): the fast suite no longer fits in memory as one process.
~170 test files build a MainWindow and none destroys it; each keeps
~18 MB until the process ends, and one run went past 15 GB and into swap.
Destroying them per test was tried (08-10) and turned up Qt/Python
lifetime crashes file by file; batches bound the memory without changing
what the tests do. A batch that crashes counts as a failure, by name.

    scripts/pytest_batches.py [-m 'not slow'] [--batches 6] [tests]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|"
                    r"deselected|warnings?)")
_NATIVE_FAULT = re.compile(
    r"Windows fatal exception: (?:access violation|stack overflow|illegal instruction|"
    r"integer divide by zero|code 0xc000(?:0005|00fd|001d|0409|0094))"
    r"|Fatal Python error|Segmentation fault", re.IGNORECASE)


def exit_test_process(status: int) -> NoReturn:
    """Flush test reports and exit without unsafe Qt teardown on Windows."""
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        # The CRT exit path can still detach Qt DLLs after os._exit. End only
        # this test process once pytest has written all reports and its status.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        current = kernel.GetCurrentProcess
        current.argtypes = []
        current.restype = wintypes.HANDLE
        terminate = kernel.TerminateProcess
        terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
        terminate.restype = wintypes.BOOL
        if not terminate(current(), status):
            raise ctypes.WinError(ctypes.get_last_error())
    os._exit(status)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", dest="marker", default=None)
    ap.add_argument("--batches", type=int, default=6)
    ap.add_argument("path", nargs="?", default="tests")
    args = ap.parse_args()

    files = sorted(str(p) for p in Path(args.path).glob("test_*.py"))
    n = max(1, min(args.batches, len(files)))
    chunks = [files[i::n] for i in range(n)]   # interleaved: even weights
    totals: dict[str, int] = {}
    crashed = []
    t0 = time.monotonic()
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get(
        "QT_QPA_PLATFORM", "offscreen"))
    for i, chunk in enumerate(chunks, 1):
        cmd = [sys.executable, "-X", "faulthandler", "-m", "pytest", "-q",
               "-p", "no:cacheprovider"]
        if args.marker:
            cmd += ["-m", args.marker]
        # pytest writes UTF-8; text=True alone decodes with the locale's
        # codepage (cp1252 on Windows), which died on the first byte it
        # has no character for and left stdout None (ronda Windows 0.5.9).
        proc = subprocess.run(cmd + chunk, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        last = lines[-1] if lines else ""
        for num, kind in _COUNT.findall(last):
            kind = {"error": "errors", "warning": "warnings"}.get(kind, kind)
            totals[kind] = totals.get(kind, 0) + int(num)
        # 0 ok, 1 failures (counted above), 5 nothing collected for -m.
        native_fault = _NATIVE_FAULT.search(proc.stdout + proc.stderr) is not None
        if proc.returncode not in (0, 1, 5) or native_fault:
            detail = f"exit {proc.returncode}"
            if native_fault:
                detail += "; native fault reported"
            crashed.append(f"batch {i} ({detail})")
            sys.stderr.write(proc.stdout[-3000:] + proc.stderr[-3000:])
        elif proc.returncode == 1:
            # The failures' own report too: a test that fails once in a
            # while must leave its reason behind, not only its name.
            out = proc.stdout
            a = out.find("= FAILURES =")
            b = out.find("short test summary")
            if a >= 0:
                head = out.rfind("\n", 0, a) + 1
                sys.stderr.write(out[head:b if b > a else None][-20000:])
            sys.stderr.write("\n".join(ln for ln in lines
                                       if ln.startswith(("FAILED", "ERROR")))
                             + "\n")
        print(f"batch {i}/{n}: {last}", file=sys.stderr)
    order = ("failed", "passed", "skipped", "xfailed", "xpassed", "errors",
             "deselected", "warnings")
    parts = [f"{totals[k]} {k}" for k in order if totals.get(k)]
    parts += [f"CRASHED: {c}" for c in crashed]
    elapsed = round(time.monotonic() - t0)
    print(", ".join(parts) + f" in {elapsed}s ({n} batches)")
    return 1 if totals.get("failed") or totals.get("errors") or crashed \
        else 0


if __name__ == "__main__":
    sys.exit(main())
