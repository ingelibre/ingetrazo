# SPDX-License-Identifier: GPL-3.0-or-later
"""A Blender.app bundle chosen anywhere is accepted (#328, @dirkolbrich).

On macOS the picker hands back the .app, which is a folder; the saved path
had to be a file, so nothing happened. The program inside the bundle is
used instead, wherever the bundle lives (Blender Launcher keeps one per
version under ~/Documents)."""
from __future__ import annotations

from core import render_blender as rb


def test_the_program_inside_the_bundle_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "in_flatpak", lambda: False)
    app = tmp_path / "stable" / "blender-4.5.3" / "Blender.app"
    exe = app / "Contents" / "MacOS" / "Blender"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    found = rb.find_blender(str(app))
    assert found is not None
    assert found.command == [str(exe)]


def test_any_other_path_is_left_alone(tmp_path):
    exe = tmp_path / "blender"
    exe.write_text("")
    assert rb.app_bundle_executable(str(exe)) == str(exe)
