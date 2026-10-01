# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #179 (Georges Le Roux): insert an .igz as a component from Python,
without the file dialog — for a palette that places components as the
mouse moves. ``window.import_igz_path`` and ``app.import_igz``."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _bench(tmp_path):
    """A 1 x 1 x 0.5 box drawn from the origin, saved as bench.igz."""
    scene = Scene()
    m = scene.mesh
    p = [QVector3D(0, 0, 0), QVector3D(1, 0, 0), QVector3D(1, 1, 0),
         QVector3D(0, 1, 0), QVector3D(0, 0, 0.5), QVector3D(1, 0, 0.5),
         QVector3D(1, 1, 0.5), QVector3D(0, 1, 0.5)]
    for loop in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in loop])
    path = tmp_path / "bench.igz"
    igz.save_scene(scene, path)
    return path


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _bounds(group):
    from core.group import world_mesh
    mesh = world_mesh(group)
    xs = [v.position.x() for v in mesh.vertices]
    ys = [v.position.y() for v in mesh.vertices]
    zs = [v.position.z() for v in mesh.vertices]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def test_at_a_point_the_component_lands_there_in_one_undo_step(window,
                                                               tmp_path):
    scene = window.viewport.scene
    n0 = len(scene.groups)
    comp = window.import_igz_path(_bench(tmp_path), at=(4.0, 2.0, 0.0))
    assert comp is not None and comp in scene.groups
    assert len(scene.groups) == n0 + 1
    lo, hi = _bounds(comp)                     # its origin went to (4, 2, 0)
    assert lo == pytest.approx((4.0, 2.0, 0.0), abs=1e-6)
    assert hi == pytest.approx((5.0, 3.0, 0.5), abs=1e-6)
    window.viewport.history.undo()
    assert comp not in scene.groups and len(scene.groups) == n0


def test_without_a_point_it_waits_for_the_click(window, tmp_path):
    from tools.place_group import PlaceGroupTool
    scene = window.viewport.scene
    n0 = len(scene.groups)
    comp = window.import_igz_path(_bench(tmp_path))
    assert isinstance(window.viewport.active_tool, PlaceGroupTool)
    assert comp not in scene.groups and len(scene.groups) == n0


def test_the_extension_api_offers_it(window, tmp_path):
    from views.extension_api import ExtensionApp
    app = ExtensionApp(window, "palette")
    comp = app.import_igz(_bench(tmp_path),
                          at=QVector3D(-2.0, 0.0, 0.0))
    assert comp in window.viewport.scene.groups


def test_an_unreadable_file_raises_and_changes_nothing(window, tmp_path):
    bad = tmp_path / "broken.igz"
    bad.write_bytes(b"not a document")
    scene = window.viewport.scene
    n0 = len(scene.groups)
    with pytest.raises(Exception):
        window.import_igz_path(bad, at=(0, 0, 0))
    assert len(scene.groups) == n0
