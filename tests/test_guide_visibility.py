# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Guide lines must survive perspective: the ±10 km 'infinite' segment often
has an endpoint BEHIND the camera, where _world_to_pixel returns None — the
whole guide used to vanish from render, snap and pick (the "protractor doesn't
mark a guide I can draw on" report)."""
from __future__ import annotations

import sys

from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _window_with_guide():
    from core.guide import Guide
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    vp.resize(1200, 800)
    # A guide running from the origin TOWARD the eye: its far endpoint lands
    # behind the camera (the everyday case after orbiting to draw on it).
    d = (vp.camera.eye() - QVector3D(0, 0, 0)).normalized()
    g = Guide(QVector3D(0, 0, 0), d)
    vp.scene.guides.append(g)
    return win, vp, g


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_clip_segment_front_recovers_projectable_span():
    win, vp, g = _window_with_guide()
    try:
        a, b = g.segment()
        raw = [vp._world_to_pixel(a), vp._world_to_pixel(b)]
        assert None in raw                      # the bug's precondition holds
        seg = vp._clip_segment_front(a, b)
        assert seg is not None
        pa, pb = vp._world_to_pixel(seg[0]), vp._world_to_pixel(seg[1])
        assert pa is not None and pb is not None
    finally:
        _close(win)


def test_snap_scene_feeds_clipped_guides_and_points():
    from core.guide import Guide
    win, vp, g = _window_with_guide()
    try:
        vp.scene.guides.append(Guide(QVector3D(2, 3, 0)))    # a guide point
        snap_scene = vp._snap_scene(600, 400)
        extra = [e for e in snap_scene.edges]
        projectable = [
            e for e in extra
            if vp._world_to_pixel(e.a) is not None
            and vp._world_to_pixel(e.b) is not None
        ]
        # The clipped guide line and the guide point both made it in with
        # endpoints the snap engine can project.
        assert len(projectable) >= 2
        pts = [e for e in extra if (e.a - QVector3D(2, 3, 0)).length() < 1e-9]
        assert pts                              # the guide point pseudo-edge
    finally:
        _close(win)


def test_on_guide_snap_in_perspective():
    from core.snap import compute_snap
    win, vp, g = _window_with_guide()
    try:
        # A visible point ON the guide, a bit in front of the camera.
        p = g.point + g.direction * 3.0
        px = vp._world_to_pixel(p)
        assert px is not None
        snap = compute_snap(
            candidate_world=p,
            candidate_pixel=px,
            scene=vp._snap_scene(*px),
            world_to_pixel=vp._world_to_pixel,
            threshold_px=vp.snap_threshold_px,
            edge_threshold_px=vp.edge_snap_threshold_px,
        )
        assert snap.kind != "none"              # the guide is snappable again
        # And the snapped point lies on the guide line.
        off = snap.point - g.point
        along = QVector3D.dotProduct(off, g.direction)
        assert (off - g.direction * along).length() < 1e-3
    finally:
        _close(win)
