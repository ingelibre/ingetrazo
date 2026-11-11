# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A kerb of the plaza under the sixty facets of a curved bench finishes.

Seen on the plaza with the faces' geometry taken exact in double
precision: a 0.08 m² horizontal kerb (face 17 of the drawing, with an
exact duplicate) overlapped by sixty 1.5 mm facets of a curved bench,
each passing in front of part of it. Cut to the side where each facet is
nearer, their parts met the kerb's corners and each other to the last
bit, and the booleans of the visible parts ran away on them — never
finished, and ate the machine's memory. No half of the sixty does it
alone. The case is kept as it was, exact, in ``tests/data``; the engine
runs it in a child with a time limit, so a return of the runaway is a
failure here and not a hung suite, and what it leaves is what the Python
pass leaves."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from core import _native
from core import vista_caras as VC
from core.vista_caras import FaceFill

FIXTURE = Path(__file__).resolve().parent / "data" / "plaza_kerb_fan.json"

native = _native.available()
pytestmark = pytest.mark.skipif(
    native is None or not hasattr(native, "visible_parts"),
    reason="Rust engine without visible_parts")

CHILD = r"""
import json, sys, numpy as np
from core import vista_caras as VC, _native
from core.vista_caras import FaceFill
raw = json.load(open(sys.argv[1]))
faces = [FaceFill(rings=[np.array(r, float) for r in f["rings"]], rgb=(0, 0, 0),
                  layer="0", opacity=f["opacity"], depth=f["depth"],
                  extra={"near": tuple(f["near"])}) for f in raw]
out = VC._visible_parts_native(faces, _native.available())
print(json.dumps([[f.depth, sum(VC._area(r) for r in f.rings)] for f in out]))
"""


def _faces():
    return [FaceFill(rings=[np.array(r, float) for r in f["rings"]],
                     rgb=(0, 0, 0), layer="0", opacity=f["opacity"],
                     depth=f["depth"], extra={"near": tuple(f["near"])})
            for f in json.load(open(FIXTURE))]


def test_the_kerb_under_the_fan_of_facets_finishes_as_python_does():
    faces = _faces()
    assert len(faces) == 62
    py = [(f.depth, sum(VC._area(r) for r in f.rings))
          for f in VC._visible_parts_py(faces)]
    try:
        done = subprocess.run(
            [sys.executable, "-c", CHILD, str(FIXTURE)], capture_output=True,
            text=True, timeout=60, cwd=str(FIXTURE.parent.parent.parent),
            env={**__import__("os").environ, "INGETRAZO_RUST": "1"})
    except subprocess.TimeoutExpired:
        pytest.fail("the engine's visible parts ran away on the kerb and "
                    "the fan of facets (60 s)")
    assert done.returncode == 0, done.stderr[-2000:]
    rust = json.loads(done.stdout.strip().splitlines()[-1])
    assert [round(d, 9) for d, _a in rust] == [round(d, 9) for d, _a in py]
    for (_d, a), (_e, b) in zip(rust, py):
        assert abs(a - b) < 1e-9, (a, b)
