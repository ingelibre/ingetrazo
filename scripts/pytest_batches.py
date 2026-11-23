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
import signal
import sys
import tempfile
import time
from pathlib import Path

_COUNT = re.compile(r"(\d+) (passed|failed|skipped|errors?|xfailed|xpassed|"
                    r"deselected|warnings?)")


def _switches_theme(path: str) -> bool:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return False
    return "apply_theme(" in text or "apply_accent(" in text


#: A batch takes ~12 min on a CI runner. One that has stopped answering is
#: killed, with the stack of the test it was in, so a job does not hang for
#: the six hours GitHub allows (23-11).
BATCH_LIMIT = 3000
TEST_LIMIT = 600


def _run(cmd: list[str], env: dict):
    """The finished process, or None if it had to be killed. Output goes to
    files: a pipe kept open by a grandchild would hold us after the kill."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            cmd, env=env, stdout=out, stderr=err,
            start_new_session=os.name == "posix")
        late = False
        try:
            proc.wait(timeout=BATCH_LIMIT)
        except subprocess.TimeoutExpired:
            late = True
        except BaseException:
            _kill(proc)             # Ctrl+C: its session is not ours
            raise
        if late:
            _kill(proc)
        out.seek(0)
        err.seek(0)
        text = [f.read().decode("utf-8", "replace") for f in (out, err)]
    if late:
        # A stack says which test: the newest is what it was still in.
        sys.stderr.write(text[0][-3000:] + text[1][-8000:] + "\n")
        return None
    return subprocess.CompletedProcess(cmd, proc.returncode, *text)


def _kill(proc) -> None:
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        proc.kill()
    proc.wait()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", dest="marker", default=None)
    ap.add_argument("--batches", type=int, default=6)
    ap.add_argument("path", nargs="?", default="tests")
    args = ap.parse_args()

    files = sorted(str(p) for p in Path(args.path).glob("test_*.py"))
    # The files that switch the app's theme run first, each in a process of
    # its own. A theme switch makes Qt walk every widget alive, and a
    # batch's earlier files leave ~385 000 behind (their MainWindows are
    # never destroyed, see above): test_theme_slate segfaulted inside
    # QApplication::setStyleSheet mid-batch, on Linux and Windows, while
    # 250 switches with the app's own windows never did (13-11). Together
    # in one process they still walked test_layers_panel's windows, ~30 s
    # a switch: 37 min, against 2.3 min one file per process (14-11).
    themed = [f for f in files if _switches_theme(f)]
    files = [f for f in files if f not in themed]
    n = max(1, min(args.batches, len(files)))
    chunks = [[f] for f in themed]
    chunks += [files[i::n] for i in range(n)]   # interleaved: even weights
    n = len(chunks)
    totals: dict[str, int] = {}
    crashed = []
    t0 = time.monotonic()
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get(
        "QT_QPA_PLATFORM", "offscreen"))
    for i, chunk in enumerate(chunks, 1):
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "-o", f"faulthandler_timeout={TEST_LIMIT}"]
        if args.marker:
            cmd += ["-m", args.marker]
        # pytest writes UTF-8; text=True alone decodes with the locale's
        # codepage (cp1252 on Windows), which died on the first byte it
        # has no character for and left stdout None (ronda Windows 0.5.9).
        proc = _run(cmd + chunk, env)
        if proc is None:
            crashed.append(f"batch {i} (no answer in {BATCH_LIMIT} s)")
            print(f"batch {i}/{n}: stopped", file=sys.stderr, flush=True)
            continue
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        last = lines[-1] if lines else ""
        for num, kind in _COUNT.findall(last):
            kind = {"error": "errors", "warning": "warnings"}.get(kind, kind)
            totals[kind] = totals.get(kind, 0) + int(num)
        # 0 ok, 1 failures (counted above), 5 nothing collected for -m.
        if proc.returncode not in (0, 1, 5):
            crashed.append(f"batch {i} (exit {proc.returncode})")
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
    print(", ".join(parts) + f" in {time.monotonic() - t0:.0f}s "
          f"({n} batches)")
    return 1 if totals.get("failed") or totals.get("errors") or crashed \
        else 0


if __name__ == "__main__":
    sys.exit(main())
