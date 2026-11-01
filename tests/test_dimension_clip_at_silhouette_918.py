# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An annotation line that goes behind a surface stops AT the surface's
silhouette (issue #918): it used to be cut back a whole sixteenth of its
length at a time, and the cut jumped from sample to sample as the view
turned — the dimensions clipped in and out behind other surfaces. Moving
the occluder a little now moves the end of the line a little.

Needs a GL context that renders; skipped where the platform has none."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


class _Pen:
    """Records the lines a painter is asked to draw."""

    def __init__(self):
        self.lines = []

    def drawLine(self, a, b):
        self.lines.append(((a.x(), a.y()), (b.x(), b.y())))

    def length(self):
        return sum(math.hypot(b[0] - a[0], b[1] - a[1])
                   for a, b in self.lines)


def _box(mesh, x0, y0, z0, x1, y1, z1):
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    return [mesh.add_face([p[i] for i in idx])
            for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))]


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    try:
        w.show()
        for _ in range(5):
            _app.processEvents()
        if getattr(w.viewport, "_gl", None) is None \
                or not w.viewport.isValid():
            pytest.skip("no OpenGL context on this platform")
        yield w
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()


def _seen_length(vp, x_edge, left=False):
    """How much of a line from x=-2 to x=2 behind a wall whose left edge
    is at ``x_edge`` (its right edge, ``left``) the overlay draws, in
    pixels."""
    sc = vp.scene
    for f in list(sc.mesh.faces):
        sc.mesh.remove_face(f)
    if left:
        _box(sc.mesh, -3, -0.1, 0, x_edge, 0.1, 3)
    else:
        _box(sc.mesh, x_edge, -0.1, 0, 3, 0.1, 3)
    sc.version += 1
    vp.grabFramebuffer()
    if getattr(vp, "_depth_snap", None) is None:
        pytest.skip("this GL context gives no depth read-back")
    pen = _Pen()
    vp._draw_occluded_segment(pen, V(-2, 2, 1), V(2, 2, 1))
    return pen.length()


def test_the_line_ends_at_the_silhouette_and_follows_it(win):
    from core.dimension import Dimension
    vp = win.viewport
    vp.scene.groups[:] = []                  # the scale figure stands in front
    # A dimension in the scene: the frame then keeps its depth for the
    # overlay (``_annotations_need_depth``).
    vp.scene.dimensions.append(Dimension(V(-2, 2, 1), V(2, 2, 1),
                                         V(0, 0, 0.5)))
    vp.camera.set_view("front")                      # looking toward +Y
    vp.camera.perspective = False
    vp.camera.fit_to(V(-3, -1, 0), V(3, 3, 3))
    for _ in range(3):
        _app.processEvents()
    full = _seen_length(vp, 2.5)                     # wall clear of it
    assert full > 100
    px_per_m = full / 4.0
    # The wall's edge walks across two sample steps (4 m / 16 each) in
    # fifths of one: the seen part follows it, never sticking for a step.
    lengths = [_seen_length(vp, 0.0 + k * 0.05) for k in range(11)]
    for k, got in enumerate(lengths):
        expect = (2.0 + k * 0.05) * px_per_m
        assert abs(got - expect) < 3.0, (k, got, expect)
    assert all(b > a for a, b in zip(lengths, lengths[1:])), lengths
    # From the other side: the line comes out from behind the wall.
    lengths = [_seen_length(vp, 0.0 + k * 0.05, left=True) for k in range(11)]
    for k, got in enumerate(lengths):
        expect = (2.0 - k * 0.05) * px_per_m
        assert abs(got - expect) < 3.0, (k, got, expect)
    assert all(b < a for a, b in zip(lengths, lengths[1:])), lengths
