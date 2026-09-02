# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Composer auto-render (LayOut's Auto) and the array geometry path the
hidden-line pass takes from the viewport caches."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QVector3D


def _fountain_like(scene):
    """A soft-edged solid of revolution in a group + a loose square: the
    two families collect_geometry walks."""
    from core.ai import _recipe_helpers
    helpers = _recipe_helpers(scene)
    helpers["revolve"]([(0.5, 0.0), (0.6, 0.5), (0.4, 1.0)], segments=24,
                       name="Vaso")
    scene.mesh.add_face([QVector3D(-2, -2, 0), QVector3D(2, -2, 0),
                         QVector3D(2, 2, 0), QVector3D(-2, 2, 0)])
    scene.version += 1


def test_hlr_geometry_matches_the_python_walk():
    """Viewport.hlr_geometry() (arrays from the caches) carries the same
    triangles, hard edges and soft edges as core.hlr.collect_geometry, and
    hlr_view draws the same segments from either."""
    from core.camera import OrbitCamera
    from core.hlr import collect_geometry, hlr_view
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(800, 600)
        scene = vp.scene
        _fountain_like(scene)
        tris, hard, soft, soft_n = vp.hlr_geometry()
        lt, lh, ls = collect_geometry(scene)
        assert (len(tris), len(hard), len(soft)) == (len(lt), len(lh), len(ls))
        assert soft_n.shape == (len(soft), 2, 3)

        def sym(pairs):
            out = set()
            for a, b in pairs:
                a = tuple(np.round(np.asarray(a, dtype=float), 5))
                b = tuple(np.round(np.asarray(b, dtype=float), 5))
                out.add((a, b) if a <= b else (b, a))
            return out
        assert sym(hard) == sym(lh)
        assert sym(soft) == sym([(p0, p1) for p0, p1, _a, _b in ls])
        # Open-boundary flag: the revolve caps close everything here.
        assert not np.isnan(soft_n[:, 1, 0]).any()

        cam = OrbitCamera()
        cam.set_view("front")
        cam.perspective = False
        lo, hi = scene.bounds()
        cam.fit_to(lo, hi, 1.1)
        slow = hlr_view(scene, cam)
        fast = hlr_view(scene, cam, geometry=(tris, hard, soft, soft_n))
        assert len(fast) == len(slow)
        assert sym([(s[:2], s[2:]) for s in slow]) == sym(
            [(s[:2], s[2:]) for s in fast])
        # Section cut: the array path falls back to the list clipper.
        from core.section import SectionPlane
        sp = SectionPlane(QVector3D(0, 0, 0.5), QVector3D(0, 0, 1),
                          name="Planta", symbol="1")
        scene.section_planes.append(sp)
        scene.set_active_section(sp)
        cut_slow = hlr_view(scene, cam)
        cut_fast = hlr_view(scene, cam, geometry=(tris, hard, soft, soft_n))
        assert len(cut_fast) == len(cut_slow) != len(slow)   # chords added
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_auto_render_rerenders_raster_frames_and_ignores_sheet_edits(
        monkeypatch):
    """A model change marks every frame stale and, with Auto on, the raster
    frames re-render after the quiet period; vector frames keep the badge.
    The composer's own sheet edits bump the document version too — they
    must not count as model changes (or the sheet would re-render itself)."""
    from core.composition import MarcoVista
    from views.composer import ComposerWindow
    from views.main_window import MainWindow

    rendered: list = []
    monkeypatch.setattr(ComposerWindow, "render_frame",
                        lambda self, f: rendered.append(f))
    win = MainWindow()
    comp = None
    try:
        vp = win.viewport
        scene = vp.scene
        comp = ComposerWindow(win)
        comp.show()
        raster = comp.comp.frames[0]
        vector = MarcoVista(view_key="std:front", style="vectorial")
        comp.comp.frames.append(vector)
        comp.auto_check.setChecked(True)
        rendered.clear()
        comp._stale.clear()

        # A model edit: the viewport paints a new version.
        scene.version += 1
        vp.sceneVersionChanged.emit(scene.version)
        assert comp.is_stale(raster) and comp.is_stale(vector)
        assert comp._auto_timer.isActive()
        comp._auto_render_stale()                       # the timer's job
        assert rendered.count(raster) == 1 and vector not in rendered
        assert comp.is_stale(vector)                    # waits for Update

        # A sheet edit (move a frame, add a cota…) is NOT a model change.
        rendered.clear()
        comp._stale.clear()
        comp._mark_dirty()
        vp.sceneVersionChanged.emit(scene.version)
        assert not comp.is_stale(raster)
        assert not comp._auto_timer.isActive()

        # Auto off: stale badge, no re-render until Update.
        comp.auto_check.setChecked(False)
        scene.version += 1
        vp.sceneVersionChanged.emit(scene.version)
        assert comp.is_stale(raster) and not comp._auto_timer.isActive()
        comp._auto_render_stale()
        assert raster not in rendered
        # Switching Auto back on renders what is pending.
        comp.auto_check.setChecked(True)
        assert rendered.count(raster) == 1
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()
