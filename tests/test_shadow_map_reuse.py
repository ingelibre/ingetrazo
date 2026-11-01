# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Turning the sun OFF and back ON with nothing else changed must not kill
the next render.

``_ensure_shadow_map`` caches the map by geometry + sun + cut + bounds, and
a pass with the sun off returns early setting ``_shadow_vp = None`` — but it
leaves the map AND its key in place. The next pass with the sun on hit the
cache, returned the live map and never restored the matrix, so the geometry
pass pushed ``None`` into the ``u_light_vp`` uniform and PySide6 raised
``setUniformValue(15, None)``.

Marco, 2026-09-17, exporting Plaza Yanque's sheets: «pongo exportar todas
las láminas en pdf y la lámina 4 no la considera» — the atlas renders every
frame in a row, and the sheet held a 3D frame with its own sun next to
plans without one, so the export died on sheet 4 and the PDF came out with
three pages. The live viewport hit the same hole on any Shadows off→on with
no edit in between; it was only ever one toggle away."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _viewport():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        win._saved_version = vp.scene.version   # not left shown (see
        win.close()                             # test_guides_behind_geometry)
        pytest.skip("no OpenGL context on this platform")
    vp.scene.mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)])
    vp.scene.mesh.add_face([V(1, 1, 2), V(3, 1, 2), V(3, 3, 2), V(1, 3, 2)])
    vp.scene.version += 1
    vp.scene.shadows.month, vp.scene.shadows.day = 6, 21
    vp.scene.shadows.hour = 10
    return win, vp


def test_the_light_matrix_comes_back_with_the_reused_map():
    win, vp = _viewport()
    try:
        vp.makeCurrent()
        vp.scene.shadows.enabled = True
        assert vp._ensure_shadow_map() is not None
        built = vp._shadow_vp
        assert built is not None

        vp.scene.shadows.enabled = False          # a frame without the sun
        assert vp._ensure_shadow_map() is None
        assert vp._shadow_vp is None              # cleared, map still cached

        vp.scene.shadows.enabled = True           # …and one with it again
        assert vp._ensure_shadow_map() is not None
        # THE regression: the matrix must be back, not left at None
        assert vp._shadow_vp is not None
        assert vp._shadow_vp == built
    finally:
        vp.doneCurrent()
        win._saved_version = vp.scene.version     # close without the prompt
        win.close()


def test_a_render_survives_the_same_off_on_sequence():
    """End to end: the three renders the atlas does, in the order it does
    them. Before the fix the third raised ValueError from PySide6."""
    win, vp = _viewport()
    try:
        for enabled in (True, False, True):
            vp.scene.shadows.enabled = enabled
            img = vp.render_image(160, 120, overlays=False)
            assert img is not None and img.width() == 160
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_an_exported_picture_draws_its_own_sharper_map_and_leaves_the_views():
    """Export image and the sheets draw the sun's map for that one picture
    at a finer size (the view's 2048 spreads a 100 m plaza over 5 cm per
    texel); the view's own map, its key and its size come back untouched,
    so the next frame on screen reuses it as before."""
    win, vp = _viewport()
    try:
        vp.scene.shadows.enabled = True
        vp.render_image(400, 300, overlays=False)
        view_map, view_key = vp._shadow_fbo, vp._shadow_key
        assert view_map is not None and view_map.width() == vp._SHADOW_MAP_SIZE
        sizes = []
        real = vp._render_shadow_map

        def spy(light_vp):
            sizes.append(vp._shadow_fbo.width())
            return real(light_vp)

        vp._render_shadow_map = spy
        try:
            assert vp.render_image(400, 300, overlays=False,
                                   sharp_shadows=True) is not None
            vp.render_image(400, 300, overlays=False)
        finally:
            del vp._render_shadow_map
        assert sizes and sizes[0] > vp._SHADOW_MAP_SIZE   # one sharp map...
        assert len(sizes) == 1                            # ...the view rebuilt none
        assert vp._shadow_fbo is view_map and vp._shadow_key == view_key
        assert vp._shadow_size == vp._SHADOW_MAP_SIZE
    finally:
        win._saved_version = vp.scene.version
        win.close()
