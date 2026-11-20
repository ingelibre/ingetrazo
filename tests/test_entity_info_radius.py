# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Entity Info — radius editing for curves and guide circles."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win


def test_entity_info_radius_field_changes_a_circle():
    from core.curve_segments import read_curve
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        r, n = 2.0, 24
        pts = [QVector3D(r * math.cos(2 * math.pi * k / n),
                         r * math.sin(2 * math.pi * k / n), 0.0)
               for k in range(n)]
        scene.mesh.add_face(pts)
        scene.mesh.tag_curve(pts, closed=True)
        panel = win.tray.entity_info

        scene.select([e for e in scene.mesh.edges if e.curve is not None])
        panel.refresh()
        assert panel._radius_box.isVisibleTo(panel)
        assert abs(panel._radius_box.value() - 2.0) < 1e-6

        panel._radius_box.setValue(3.0)          # the user types a new radius
        edge = next(e for e in scene.mesh.edges if e.curve is not None)
        assert abs(read_curve(scene.mesh, edge).radius - 3.0) < 1e-6

        vp.history.undo()
        edge = next(e for e in scene.mesh.edges if e.curve is not None)
        assert abs(read_curve(scene.mesh, edge).radius - 2.0) < 1e-6
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_guide_circle_entity_info_edits_radius_and_layer_with_undo():
    from core.guide import Guide, GuideCircle
    from core.layers import Layer, layer_of
    from core.units import fmt_len

    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.layers.append(Layer("Construction"))
        circle = GuideCircle(QVector3D(1, 2, 3), QVector3D(0, 1, 0), 2.0)
        scene.guides.append(circle)
        scene.select([circle])
        panel = win.tray.entity_info
        panel.refresh()

        assert panel._describe([circle]) == (
            f"<b>Guide Circle</b><br>Diameter: {fmt_len(4.0)}")
        assert panel._radius_box.isVisibleTo(panel)
        assert panel._radius_box.isEnabled()
        assert panel._radius_box.value() == 2.0
        assert panel._layer_box.isVisibleTo(panel)

        version = scene.version
        panel._radius_box.setValue(3.0)
        assert circle.radius == 3.0
        assert scene.version > version
        assert fmt_len(6.0) in panel._label.text()
        assert circle.center == QVector3D(1, 2, 3)
        assert circle.normal == QVector3D(0, 1, 0)
        win._on_undo()
        assert circle.radius == 2.0
        assert panel._radius_box.value() == 2.0
        assert fmt_len(4.0) in panel._label.text()
        win._on_redo()
        assert circle.radius == 3.0
        assert panel._radius_box.value() == 3.0
        assert fmt_len(6.0) in panel._label.text()

        panel._radius_box.setValue(0.0001)
        assert circle.radius == 0.0001
        win._on_undo()
        assert circle.radius == 3.0

        panel._layer_box.setCurrentIndex(
            panel._layer_box.findData("Construction"))
        assert layer_of(circle) == "Construction"
        win._on_undo()
        assert layer_of(circle) == "Layer 0"

        scene.select([Guide(QVector3D(0, 0, 0))])
        panel.refresh()
        assert not panel._radius_box.isVisibleTo(panel)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_nonflat_circle_radius_is_editable_but_sides_are_locked():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from core.curve_segments import read_curve
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        n = 12
        top = [QVector3D(2 * math.cos(2 * math.pi * k / n),
                         2 * math.sin(2 * math.pi * k / n), 0)
               for k in range(n)]
        bottom = [p + QVector3D(0, 0, -3) for p in top]
        scene.mesh.add_face(top)
        for i in range(n):
            j = (i + 1) % n
            scene.mesh.add_face([top[i], bottom[i], bottom[j], top[j]])
        scene.mesh.tag_curve(top, closed=True)
        edges = [e for e in scene.mesh.edges if e.curve is not None]
        scene.select(edges)
        panel = win.tray.entity_info
        panel.refresh()
        assert not panel._seg_box.isEnabled()
        assert panel._radius_box.isEnabled()
        panel._radius_box.lineEdit().setText("3 m")
        QTest.keyClick(panel._radius_box.lineEdit(), Qt.Key_Return)
        assert read_curve(scene.mesh, edges[0]).radius == pytest.approx(3.0)
        assert not panel._seg_box.isEnabled()
        win._on_undo()
        assert read_curve(scene.mesh, edges[0]).radius == pytest.approx(2.0)
        assert panel._radius_box.value() == pytest.approx(2.0)
        win._on_redo()
        assert read_curve(scene.mesh, edges[0]).radius == pytest.approx(3.0)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_guide_circle_radius_enter_invalidates_render_cache_and_undoes():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from core.guide import GuideCircle
    from views.viewport import _guide_cache_key, _guide_vertices

    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        circle = GuideCircle(QVector3D(0, 0, 0), QVector3D(0, 0, 1), 2.0)
        scene.guides.append(circle)
        scene.select([circle])
        panel = win.tray.entity_info
        panel.refresh()

        def render_state():
            return _guide_cache_key([circle], scene.selection, 10.0,
                                    QVector3D(0, 0, 0), None)

        original_key = render_state()
        original_vertices, _ = _guide_vertices([circle], spacing=0.5)
        panel._radius_box.lineEdit().setText("3 m")
        QTest.keyClick(panel._radius_box.lineEdit(), Qt.Key_Return)
        assert circle.radius == 3.0
        assert render_state() != original_key
        new_vertices, _ = _guide_vertices([circle], spacing=0.5)
        assert new_vertices != original_vertices

        win._on_undo()
        assert circle.radius == 2.0
        assert render_state() == original_key
        win._on_redo()
        assert circle.radius == 3.0
        assert render_state() != original_key
    finally:
        win._saved_version = vp.scene.version
        win.close()
