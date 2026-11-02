# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A guide behind a wall stays behind it (issue #23, @pacaeiro).

«Guide lines are always in front of other objects, even if they are behind
the object, in the scene.» They were painted in the QPainter overlay, which
runs AFTER the render and has no depth buffer — on top was the only place
they could be.

The cheap fix does not exist: asking the pick index per sample point
(``_is_occluded``, what the snap engine uses) measured **618 µs a ray** on
the Plaza Yanque model, so ten guides would have cost 200 ms a frame. The
depth buffer already knows, for free, so the lines moved into the GL pass —
same recipe as the axes, world-space dashes and depth-write off.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

from core.guide import Guide
from views.viewport import _guide_vertices

_app = QApplication.instance() or QApplication([])
V = QVector3D


# ── The dash generator (no GL needed) ───────────────────────────────────────

def test_the_generator_lays_dashes_along_the_guide():
    g = Guide(V(0, 0, 1), V(1, 0, 0))            # a line along +X at z = 1
    coords, spans = _guide_vertices([g], spacing=1.0)
    assert len(spans) == 1
    start, count, selected = spans[0]
    assert start == 0 and count > 2 and count % 2 == 0   # pairs: GL_LINES
    assert selected is False
    pts = np.asarray(coords, dtype=float).reshape(-1, 3)
    assert np.allclose(pts[:, 1], 0.0)          # never leaves the guide…
    assert np.allclose(pts[:, 2], 1.0)          # …in either direction
    # gaps, not one solid line: consecutive dashes do not touch
    assert pts[1, 0] < pts[2, 0] - 1e-9


def test_a_guide_point_produces_no_dashes():
    """Points are screen-space crosses and stay in the overlay."""
    coords, spans = _guide_vertices([Guide(V(1, 2, 3))], spacing=1.0)
    assert spans == [] and len(coords) == 0


def test_the_selected_guide_is_flagged_for_its_own_colour():
    g1, g2 = Guide(V(0, 0, 0), V(1, 0, 0)), Guide(V(0, 0, 0), V(0, 1, 0))
    _coords, spans = _guide_vertices([g1, g2], spacing=1.0, selection=[g2])
    assert [sel for _s, _c, sel in spans] == [False, True]


def test_the_dash_count_is_capped_however_long_the_guide():
    """A guide is half a million metres long: at a fine spacing that would
    be millions of segments a frame. The spacing grows instead."""
    g = Guide(V(0, 0, 0), V(1, 0, 0))
    _coords, spans = _guide_vertices([g], spacing=0.001)
    _start, count, _sel = spans[0]
    assert count <= 8000                        # 4000 dashes × 2 vertices


# ── The real thing: pixels ──────────────────────────────────────────────────

def _viewport():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        # Closed before skipping: a shown window left behind took the
        # keyboard from the next test's own (CI's batch 5, no OpenGL:
        # Join Segments' Esc never reached its viewport).
        win._saved_version = vp.scene.version
        win.close()
        pytest.skip("no OpenGL context on this platform")
    return win, vp


def _pixels(img: QImage):
    a = img.convertToFormat(QImage.Format_RGB32)
    buf = np.frombuffer(a.constBits(), np.uint8).reshape(
        a.height(), a.bytesPerLine())[:, :a.width() * 4]
    return buf.reshape(a.height(), a.width(), 4)[..., :3].astype(int).copy()


def _changed(before, after) -> int:
    """Pixels the guide altered. Measured as a DIFFERENCE, not by matching
    its colour: a one-pixel GL line under 4× MSAA resolves to a 50 % blend
    with whatever is behind it, so there is no single «guide colour» on
    screen to look for."""
    return int((np.abs(after - before).sum(axis=2) > 8).sum())


def _scene_looking_down_minus_y():
    """A wall in the XZ plane at y = 0, seen from the eye at y = +20. So
    y > 0 is IN FRONT of the wall and y < 0 is behind it.

    The wall is WIDER than the view on purpose: a 10 m one covers only the
    middle of a ~17 m window, and the ends of the guide poking past its
    edges are legitimately visible — they would read as a failure when they
    are the tool working."""
    win, vp = _viewport()
    scene = vp.scene
    scene.mesh.add_face([V(-60, 0, -60), V(60, 0, -60), V(60, 0, 60),
                         V(-60, 0, 60)])
    scene.version += 1
    cam = vp.camera
    cam.target = V(0, 0, 0)
    cam.distance, cam.yaw, cam.pitch = 20.0, 1.5707963, 0.0
    cam.perspective = False
    return win, vp


def test_a_wall_hides_the_guide_behind_it():
    win, vp = _scene_looking_down_minus_y()
    try:
        assert vp.camera.eye().y() > 0          # the eye really is on +Y
        bare = _pixels(vp.render_image(300, 300, overlays=False))

        vp.scene.guides[:] = [Guide(V(0, 4, 0), V(1, 0, 0))]     # in front
        shown = _changed(bare, _pixels(
            vp.render_image(300, 300, overlays=False)))

        vp.scene.guides[:] = [Guide(V(0, -4, 0), V(1, 0, 0))]    # behind
        hidden = _changed(bare, _pixels(
            vp.render_image(300, 300, overlays=False)))

        assert shown > 50, "a guide in front of the wall must be drawn"
        assert hidden == 0, (
            f"the wall must hide the guide behind it "
            f"(hidden={hidden}px, shown={shown}px)")
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_sheet_render_still_carries_no_guides():
    """A styled composer frame never drew the scaffolding and must not
    start now that the pass moved into GL."""
    win, vp = _scene_looking_down_minus_y()
    try:
        from core.style import style_by_name
        vp.style_override = style_by_name("Architectural")
        try:
            bare = _pixels(vp.render_image(300, 300, overlays=False))
            vp.scene.guides[:] = [Guide(V(0, 4, 0), V(1, 0, 0))]
            after = _pixels(vp.render_image(300, 300, overlays=False))
        finally:
            vp.style_override = None
        assert _changed(bare, after) == 0
    finally:
        win._saved_version = vp.scene.version
        win.close()
