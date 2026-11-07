# SPDX-License-Identifier: GPL-3.0-or-later
"""Entity Info adds up a multiple selection (#274).

With several faces or edges selected it only counted them; the usual totals
-- the faces' area, the edges' length -- are what a rough building model is
measured with."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V


def test_two_faces_and_three_edges_show_their_totals():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        m = scene.mesh
        a = m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 3, 0), V(0, 3, 0)])  # 6 m²
        b = m.add_face([V(5, 0, 0), V(6, 0, 0), V(6, 1, 0), V(5, 1, 0)])  # 1 m²
        loose = [m.add_edge(V(0, 5, 0), V(4, 5, 0)),                      # 4 m
                 m.add_edge(V(0, 6, 0), V(0.5, 6, 0))]                    # 0.5 m
        edge = m.find_edge(m.vertex_at(V(0, 0, 0)), m.vertex_at(V(0, 3, 0)))
        text = win.tray.entity_info._describe([a, b])
        assert "7" in text.split(":")[-1]
        text = win.tray.entity_info._describe(loose + [edge])
        assert "7.5" in text.replace(",", ".")
        both = win.tray.entity_info._describe([a, b] + loose)
        assert both.count("<br>") == 3              # header, area, length
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_face_with_an_opening_shows_its_net_area():
    """Entity Info reads the face as it is drawn: a 4×4 m face with a
    1×1 m opening is 15 m², alone and in a selection total."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        m = win.viewport.scene.mesh
        f = m.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0)],
                       [[V(1, 1, 0), V(1, 2, 0), V(2, 2, 0), V(2, 1, 0)]])
        g = m.add_face([V(6, 0, 0), V(7, 0, 0), V(7, 1, 0), V(6, 1, 0)])
        one = win.tray.entity_info._describe([f]).replace(",", ".")
        assert "15" in one and "16" not in one
        both = win.tray.entity_info._describe([f, g]).replace(",", ".")
        assert "16" in both.split(":")[-1]          # 15 + 1
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
