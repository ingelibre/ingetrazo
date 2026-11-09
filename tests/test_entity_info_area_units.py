# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #432 (@dns-0): Entity Info wrote a face's area in m² whatever the
document's units — a feet-and-inches model showed a metric area."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import units  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    units.bind_scene(None)
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _face_text(window, length_unit):
    from views.tray import EntityInfoPanel
    scene = window.viewport.scene
    scene.units = {"length": length_unit, "precision": 2}
    units.bind_scene(scene)
    face = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    return window.findChild(EntityInfoPanel)._describe([face])


def test_a_face_in_a_feet_document_shows_square_feet(window):
    text = _face_text(window, "ft")
    assert "m²" not in text
    assert units.fmt_area(1.0) in text          # 1 m² ≈ 10.76 ft²


def test_a_face_in_a_metre_document_still_shows_square_metres(window):
    assert "m²" in _face_text(window, "m")
