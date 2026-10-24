# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The native hidden-line kernel (rust/ingetrazo_core) must draw exactly
what the Python code draws: same segments, same kinds, coordinates within
rounding. Random scenes of overlapping, tilted boxes at several heights,
seen from several cameras, with and without a section cut. Skipped when
the module is not built."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The engine is off by default; this file tests it, so it asks for it.
os.environ.setdefault("INGETRAZO_RUST", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import core._native as _native  # noqa: E402
from core import hlr  # noqa: E402
from core.camera import OrbitCamera  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.section import SectionPlane  # noqa: E402

_app = QApplication.instance() or QApplication([])

pytestmark = pytest.mark.skipif(_native.native is None,
                                reason="native module not built")


def _box(scene, rng):
    w, d, h = rng.uniform(0.3, 2), rng.uniform(0.3, 2), rng.uniform(0.2, 3)
    m = QMatrix4x4()
    m.translate(rng.uniform(-4, 4), rng.uniform(-4, 4), rng.uniform(0, 2))
    m.rotate(rng.uniform(0, 360), 0, 0, 1)
    if rng.random() < 0.3:
        m.rotate(rng.uniform(-30, 30), 1, 0, 0)
    p = [m.map(QVector3D(x, y, z)) for z in (0, h) for y in (0, d)
         for x in (0, w)]
    for loop in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (1, 3, 7, 5),
                 (3, 2, 6, 7), (2, 0, 4, 6)):
        scene.mesh.add_face([p[i] for i in loop])


def _draw(scene, cam, use_native: bool, **kw):
    saved = _native.native
    _native.native = saved if use_native else None
    try:
        return hlr.hlr_drawing(scene, cam, **kw)
    finally:
        _native.native = saved


@pytest.mark.parametrize("seed", range(12))
def test_native_draws_what_python_draws(seed):
    rng = random.Random(seed)
    scene = Scene()
    for _ in range(rng.randint(3, 9)):
        _box(scene, rng)
    if seed % 3 == 0:
        scene.section_planes = [SectionPlane(
            QVector3D(0, 0, rng.uniform(0.5, 1.5)), QVector3D(0, 0, -1),
            active=True)]
    for view in ("top", "front", "right", "iso"):
        cam = OrbitCamera()
        cam.set_view(view)
        lo, hi = scene.bounds()
        cam.fit_to(lo, hi)
        for hidden in (False, True):
            a = _draw(scene, cam, False, hidden=hidden)
            b = _draw(scene, cam, True, hidden=hidden)
            assert a.segs.shape == b.segs.shape, (view, hidden)
            assert (a.kinds == b.kinds).all(), (view, hidden)
            if len(a.segs):
                assert np.abs(a.segs - b.segs).max() < 1e-7, (view, hidden)
