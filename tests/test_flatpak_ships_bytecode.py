# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #440 (@cdblue999): the Flatpak runs from source on a read-only
/app, so without bytecode compiled at build time Python recompiled the whole
tree on every launch. ostree also sets every mtime to 0, which turns
timestamp-checked .pyc files stale — they must be hash-based and unchecked."""
from __future__ import annotations

from pathlib import Path

RECIPE = (Path(__file__).resolve().parents[1]
          / "packaging" / "flatpak" / "com.ingetrazo.IngeTrazo.yml")


def _commands() -> list[str]:
    return [line.strip() for line in RECIPE.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("- ")]


def test_the_flatpak_compiles_the_app_after_dropping_the_pycache():
    cmds = _commands()
    drop = next(i for i, c in enumerate(cmds) if "__pycache__" in c and "rm -rf" in c)
    compile_ = [i for i, c in enumerate(cmds) if "compileall" in c]
    assert compile_, "the Flatpak recipe no longer compiles the bytecode"
    assert compile_[0] > drop, "compiling before the __pycache__ purge is undone by it"


def test_the_bytecode_does_not_depend_on_file_times():
    line = next(c for c in _commands() if "compileall" in c)
    assert "--invalidation-mode unchecked-hash" in line
    assert "/ingetrazo" in line and "/lib" in line
