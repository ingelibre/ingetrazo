# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Test workers preserve their reports/status and never hide a native crash."""
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import pytest_batches

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("status", [0, 7])
def test_worker_exit_flushes_its_report_and_preserves_status(tmp_path, status):
    cleanup = tmp_path / "unexpected-cleanup.txt"
    code = (
        "import atexit, sys\n"
        "from pathlib import Path\n"
        "from scripts.pytest_batches import exit_test_process\n"
        "atexit.register(lambda: Path(sys.argv[1]).write_text('cleanup'))\n"
        "print('test report')\n"
        "exit_test_process(int(sys.argv[2]))\n"
        "print('unreachable')\n"
    )
    result = subprocess.run([sys.executable, "-c", code, str(cleanup), str(status)],
                            cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == status, result.stderr
    assert result.stdout == "test report\n"
    assert not cleanup.exists()


@pytest.mark.parametrize("stderr,fault", [
    ("", False),
    ("Windows fatal exception: access violation\n", True),
    # Qt's printer setup can catch a COM exception after faulthandler reports
    # it. A zero exit with passing tests is not a crash for that diagnostic.
    ("Windows fatal exception: code 0x80040155\n", False),
])
def test_batch_runner_rejects_native_fault_after_a_passing_summary(
    monkeypatch, tmp_path, capsys, stderr, fault,
):
    (tmp_path / "test_example.py").write_text("def test_example(): pass\n")
    monkeypatch.setattr(sys, "argv", ["pytest_batches", "--batches", "1", str(tmp_path)])
    monkeypatch.setattr(pytest_batches.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(stdout="1 passed in 0.01s\n", stderr=stderr,
                                        returncode=0))
    assert pytest_batches.main() == (1 if fault else 0)
    output = capsys.readouterr()
    assert ("CRASHED" in output.out) is fault
    if fault:
        assert stderr in output.err
