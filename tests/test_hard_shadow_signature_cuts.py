# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The defined-shadow picture of a PNG export is kept while its signature
holds. The signature read the single ``_clip_vec`` of before the section
box, which the viewport no longer sets: moving a cut kept the old shadow
picture (20-11). It reads every cut that clips the frame now."""
from __future__ import annotations

from PySide6.QtGui import QVector4D


def test_moving_a_cut_changes_the_shadow_signature():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp._sun_dir_now = lambda: (0.3, -0.4, 0.86)
        vp._clip_vecs = []
        none = vp._hard_shadow_signature(800, 600)
        vp._clip_vecs = [QVector4D(0, 0, -1, 1.0)]
        one = vp._hard_shadow_signature(800, 600)
        vp._clip_vecs = [QVector4D(0, 0, -1, 2.0)]
        moved = vp._hard_shadow_signature(800, 600)
        vp._clip_vecs = [QVector4D(0, 0, -1, 2.0), QVector4D(1, 0, 0, 0.5)]
        box = vp._hard_shadow_signature(800, 600)
        assert len({none, one, moved, box}) == 4
        vp._clip_vecs = [QVector4D(0, 0, -1, 2.0)]
        assert vp._hard_shadow_signature(800, 600) == moved
    finally:
        win.close()
