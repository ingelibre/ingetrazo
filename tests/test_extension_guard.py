# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #306: an extension whose ``setup()`` kills the process (a
segfault cannot be caught with ``try``) must not take every following
launch down with it. The loader arms a marker naming the extension
before each ``setup()`` and disarms it when the call returns; a marker
left behind means the previous launch died in that extension, which is
then crash-disabled — skipped and reported — until re-enabled."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import core.paths                                   # noqa: E402
from core import extension_guard as guard           # noqa: E402


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(core.paths, "user_log_dir", lambda: tmp_path)
    return tmp_path


def test_arm_and_disarm(state_dir):
    guard.arm("hello")
    assert (state_dir / "extension-setup.marker").read_text() == "hello"
    guard.disarm()
    assert not (state_dir / "extension-setup.marker").exists()
    assert guard.note_crash() is None
    assert guard.crash_disabled() == []


def test_a_leftover_marker_disables_its_extension(state_dir):
    guard.arm("boom")                       # …and the launch died there
    assert guard.note_crash() == "boom"
    assert guard.crash_disabled() == ["boom"]
    # The marker is consumed: a later clean start reports nothing new,
    # and the extension stays disabled until re-enabled.
    assert guard.note_crash() is None
    assert guard.crash_disabled() == ["boom"]
    guard.reenable("boom")
    assert guard.crash_disabled() == []


def test_a_setup_that_kills_the_process_is_caught_next_start(state_dir):
    # The proposal's own test: a fake extension whose setup() kills the
    # process; the next start must skip it and say so.
    root = Path(__file__).resolve().parents[1]
    child = (
        "import os\n"
        "from pathlib import Path\n"
        "import core.paths\n"
        f"core.paths.user_log_dir = lambda: Path({str(state_dir)!r})\n"
        "from core import extension_guard as g\n"
        "g.arm('killer')\n"
        "def setup(app):\n"
        "    os._exit(42)\n"
        "setup(None)\n"
    )
    env = dict(os.environ, PYTHONPATH=str(root))
    proc = subprocess.run([sys.executable, "-c", child], cwd=root,
                          env=env, capture_output=True, timeout=120)
    assert proc.returncode == 42
    assert guard.note_crash() == "killer"
    assert guard.crash_disabled() == ["killer"]


def test_the_loader_skips_a_crash_disabled_extension(state_dir,
                                                     monkeypatch):
    from core.extensions import LoadedPlugin
    from views.main_window import MainWindow

    guard.arm("bad")
    assert guard.note_crash() == "bad"      # it died last launch

    called = []

    def fake_discover():
        return ([
            LoadedPlugin(stem="bad", path=Path("bad.py"), tools=[],
                         setup=lambda app: called.append("bad")),
            LoadedPlugin(stem="good", path=Path("good.py"), tools=[],
                         setup=lambda app: called.append("good")),
        ], [])

    monkeypatch.setattr("core.extensions.discover_plugins", fake_discover)
    w = MainWindow(defer_extensions=True)
    try:
        w.load_extensions()
    finally:
        w.close()
    assert called == ["good"]               # bad's setup never ran
    assert "bad" in w._extension_load_errors
