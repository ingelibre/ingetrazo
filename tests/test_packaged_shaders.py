# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every shader in the repo is packaged and asked for by --check (#1541)."""
import re
from fnmatch import fnmatch
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parent.parent


def _shaders():
    return {p.name for p in (ROOT / "resources" / "shaders").iterdir()
            if not p.name.startswith(".")}


def test_the_spec_packages_every_shader():
    spec = (ROOT / "ingetrazo.spec").read_text(encoding="utf-8")
    globs = re.findall(r"\('resources/shaders/([^']+)',", spec)
    missing = {n for n in _shaders() if not any(fnmatch(n, g) for g in globs)}
    assert not missing


def test_check_asks_for_every_shader():
    assert set(main.SHADERS) == _shaders()
