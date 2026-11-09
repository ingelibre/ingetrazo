# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Frustum culling of the consolidated draw spans over arrays
(Viewport._visible_spans_np) gives what the span-by-span walk gives: the
same runs, merged the same way, never across the edit split, the same
culled count — boxes straddling a plane, empty spans, spans without a
box, gaps between spans."""
from __future__ import annotations

import random

import views.viewport as vpm


def _spans(rng, n):
    out = []
    at = 0
    for _ in range(n):
        if rng.random() < 0.1:
            at += rng.randrange(1, 50)          # a gap: no merge across it
        c = rng.choice([0, 3, 6, 30, 300])
        if rng.random() < 0.08:
            box = None
        else:
            lo = [rng.uniform(-50, 50) for _ in range(3)]
            box = (tuple(lo), tuple(x + rng.uniform(0, 8) for x in lo))
        out.append((box, at, c))
        at += c
    return out


def _planes(rng):
    pl = []
    for _ in range(6):
        n = [rng.uniform(-1, 1) for _ in range(3)]
        pl.append((n[0], n[1], n[2], rng.uniform(-10, 40)))
    pl.append((1.0, 0.0, 0.0, 0.0))             # an axis plane: ties at 0
    return pl


def test_vector_culling_is_the_walk(monkeypatch):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        rng = random.Random(4)
        for _ in range(60):
            spans = _spans(rng, rng.randrange(64, 600))
            planes = _planes(rng)
            split = rng.choice([None, spans[len(spans) // 2][1],
                                spans[len(spans) // 3][1] + 1])
            monkeypatch.setattr(vpm, "_SPAN_VECTOR_MIN", 10 ** 9)
            want = vp._visible_spans(spans, planes, split)
            monkeypatch.setattr(vpm, "_SPAN_VECTOR_MIN", 1)
            got = vp._visible_spans(spans, planes, split)
            again = vp._visible_spans(spans, planes, split)  # cached arrays
            assert got == want and again == want
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
