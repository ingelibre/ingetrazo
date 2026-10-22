# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""No NaN reaches a tool or the mesh (#466, #754: the length box read
«nan m» while drawing with Line on a wall's base, and the click failed
with «AddEdgeCommand: cannot convert float NaN to integer»).

The inference that produced the NaN is not known (no file yet); the two
gates are: a snap point that is not finite counts as no point, and a
segment with a non-finite end is not planned into the mesh."""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D as V

from core.edits import build_add_edges
from core.history import History
from core.scene import Scene
from core.snap import SnapResult

NAN = float("nan")


def test_a_segment_with_a_nan_end_is_skipped_not_the_whole_stroke():
    """Without the gate the NaN failed the whole command: History rolled it
    back, the good segment of the same stroke went with it and the user saw
    «Operation failed and was undone»."""
    scene = Scene()
    hist = History(scene)
    hist.execute(build_add_edges(scene, [(V(0, 0, 0), V(1, 0, 0)),
                                         (V(1, 0, 0), V(NAN, 0, 0)),
                                         (V(1, 0, 0), V(1, math.inf, 0))]))
    assert hist.last_error is None
    assert len(scene.mesh.edges) == 1
    assert all(math.isfinite(c) for v in scene.mesh.vertices
               for c in (v.position.x(), v.position.y(), v.position.z()))


def test_a_nan_snap_is_no_point_for_the_tools():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.inference.snap = lambda *a, **k: SnapResult(V(NAN, 0, 0), "on_edge")
        assert vp._snap_at(10, 10, None) is None
        vp.inference.snap = lambda *a, **k: SnapResult(V(1, 2, 3), "on_edge")
        assert vp._snap_at(10, 10, None).point == V(1, 2, 3)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
