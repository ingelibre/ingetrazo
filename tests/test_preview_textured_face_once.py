# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A textured PREVIEW face (a push's overlay, a paste) is baked with its
normal worked out once (night of 19-11): the same floats, in the same run,
as the walk that asked for it three times — convex, concave, holed, thin
and degenerate faces, maps with and without a fitted ``uvw``."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math  # noqa: E402
import random  # noqa: E402
from array import array  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.geometry import Face  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _before(vp, by_texture, face, tex):
    from core.texture import face_uv_axes
    key = (tex["path"], vp._shade_factor(face.normal()))
    buf = by_texture.setdefault(key, array("f"))
    gu, cu, gv, cv = face_uv_axes(tex, face.normal())
    for tri in face.triangulate():
        for p in tri:
            buf.extend([p.x(), p.y(), p.z(),
                        V.dotProduct(gu, p) + cu, V.dotProduct(gv, p) + cv])


def _faces(rng):
    out = []
    for _ in range(40):
        kind = rng.choice(["quad", "star", "holed", "thin", "tiny", "line"])
        o = V(rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5))
        ax = V(rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        u = V.crossProduct(ax, V(0.3, 0.1, 1)).normalized()
        w = V.crossProduct(ax, u).normalized()
        if kind == "quad":
            a, b = rng.uniform(0.1, 3), rng.uniform(0.1, 3)
            out.append(Face([o, o + u * a, o + u * a + w * b, o + w * b]))
        elif kind in ("star", "holed"):
            n = rng.randint(5, 40)
            pts = [o + u * (math.cos(2 * math.pi * k / n)
                            * (1.0 if k % 2 or kind == "holed" else 0.45))
                   + w * (math.sin(2 * math.pi * k / n)
                          * (1.0 if k % 2 or kind == "holed" else 0.45))
                   for k in range(n)]
            holes = ([[o + u * (0.3 * math.cos(-2 * math.pi * k / 6))
                       + w * (0.3 * math.sin(-2 * math.pi * k / 6))
                       for k in range(6)]] if kind == "holed" else [])
            out.append(Face(pts, holes))
        elif kind == "thin":
            out.append(Face([o, o + u * 3, o + u * 3 + w * 1e-7, o + w * 1e-7]))
        elif kind == "tiny":
            out.append(Face([o, o + u * 1e-6, o + w * 1e-6]))
        else:
            out.append(Face([o, o + u]))
    return out


@pytest.mark.parametrize("seed", range(6))
def test_a_preview_face_bakes_what_it_baked(seed):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        rng = random.Random(seed)
        maps = [{"path": "/x/a.png", "width": 1.0, "height": 1.0},
                {"path": "/x/b.png", "width": 0.37, "height": 2.5,
                 "rotation": 30.0, "offset": [0.2, 0.1]}]
        got, want = {}, {}
        for f in _faces(rng):
            tex = rng.choice(maps)
            vp._append_textured_face(got, f, tex)
            _before(vp, want, f, tex)
        assert {k: v.tobytes() for k, v in got.items()} == \
            {k: v.tobytes() for k, v in want.items() if len(v)} | \
            {k: b"" for k, v in want.items() if not len(v) and k in got}
        assert any(len(v) for v in got.values())
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
