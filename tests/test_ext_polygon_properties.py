# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Polygon properties example extension (issue #229, by Rony Leonel
Janampa Monago) against textbook values: rectangles, a hollow section, an
L, a rotated bar, a section drawn in pieces, and a real face read off the
scene's selection."""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

_PATH = Path(__file__).resolve().parents[1] / "examples" / "extensions" / "propiedades_poligono.py"
_spec = importlib.util.spec_from_file_location("ext_polygon_properties", _PATH)
pp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pp)


def rect(b, h, cx=0.0, cy=0.0, ang=0.0, cw=False):
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    pts = [(x * c - y * s + cx, x * s + y * c + cy)
           for x, y in [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)]]
    return pts[::-1] if cw else pts


def test_a_rectangle_gives_bh3_over_12():
    p = pp.polygon_properties(rect(0.30, 0.60, cx=2.0, cy=1.0))
    assert p["area"] == pytest.approx(0.18)
    assert p["perimeter"] == pytest.approx(1.8)
    assert p["centroid"] == pytest.approx((2.0, 1.0))
    assert p["Ix_centroid"] == pytest.approx(0.30 * 0.60 ** 3 / 12)
    assert p["Iy_centroid"] == pytest.approx(0.60 * 0.30 ** 3 / 12)
    assert p["Ixy_centroid"] == pytest.approx(0.0, abs=1e-15)
    # parallel axis theorem to the plane's origin
    assert p["Ix_origin"] == pytest.approx(0.30 * 0.60 ** 3 / 12 + 0.18 * 1.0)
    assert p["rx"] == pytest.approx(0.60 / math.sqrt(12))


def test_the_winding_does_not_matter():
    a = pp.polygon_properties(rect(3, 1, cx=1, cy=2))
    b = pp.polygon_properties(rect(3, 1, cx=1, cy=2, cw=True))
    for k in ("area", "Ix_centroid", "Iy_centroid", "Ixy_origin"):
        assert a[k] == pytest.approx(b[k])


def test_a_hollow_section_subtracts_its_hole():
    """A 0.40 × 0.40 tube, 0.30 × 0.30 inside — in either winding."""
    for cw in (False, True):
        p = pp.region_properties([rect(0.4, 0.4)], [rect(0.3, 0.3, cw=cw)])
        assert p["area"] == pytest.approx(0.16 - 0.09)
        assert p["Ix_centroid"] == pytest.approx((0.4 ** 4 - 0.3 ** 4) / 12)
        assert p["perimeter"] == pytest.approx(1.6 + 1.2)


def test_an_l_section():
    # 100 × 20 flange + 20 × 80 web: centroid and Ix by hand.
    L = [(0, 0), (0.10, 0), (0.10, 0.02), (0.02, 0.02), (0.02, 0.10), (0, 0.10)]
    p = pp.polygon_properties(L)
    a1, a2 = 0.10 * 0.02, 0.02 * 0.08
    cy = (a1 * 0.01 + a2 * 0.06) / (a1 + a2)
    ix = (0.10 * 0.02 ** 3 / 12 + a1 * (cy - 0.01) ** 2
          + 0.02 * 0.08 ** 3 / 12 + a2 * (0.06 - cy) ** 2)
    assert p["area"] == pytest.approx(a1 + a2)
    assert p["centroid"][1] == pytest.approx(cy)
    assert p["Ix_centroid"] == pytest.approx(ix)
    assert p["Ixy_centroid"] < 0.0 or p["Ixy_centroid"] > 0.0


@pytest.mark.parametrize("ang", [0.0, 30.0, -45.0, 100.0])
def test_the_principal_axis_runs_across_a_bar(ang):
    """I1, the largest, is about the axis ACROSS a bar: a 4 × 1 bar at 30°
    has it at −60°."""
    p = pp.polygon_properties(rect(4, 1, ang=ang))
    assert p["I1"] == pytest.approx(1 * 4 ** 3 / 12)
    assert p["I2"] == pytest.approx(4 * 1 ** 3 / 12)
    across = (ang + 90.0 + 90.0) % 180.0 - 90.0
    got = math.degrees(p["theta"])
    assert min(abs(got - across), 180 - abs(got - across)) < 1e-6
    assert -90.0 < got <= 90.0


def test_a_section_drawn_in_pieces_is_one_section():
    whole = pp.polygon_properties(rect(0.2, 0.6, cx=0.1, cy=0.3))
    parts = pp.region_properties([rect(0.2, 0.3, cx=0.1, cy=0.15),
                                  rect(0.2, 0.3, cx=0.1, cy=0.45)])
    for k in ("area", "centroid", "Ix_centroid", "Iy_centroid", "Ixy_centroid"):
        assert parts[k] == pytest.approx(whole[k])


def test_it_reads_the_selected_faces_of_a_scene():
    """A vertical 2 × 3 m wall panel with a 1 × 1 m window: net area 5 m²,
    centroid in the model, u along red and v up."""
    from core.scene import Scene
    sc = Scene()
    f = sc.mesh.add_face([V(0, 5, 0), V(2, 5, 0), V(2, 5, 3), V(0, 5, 3)])
    sc.mesh.add_hole(f, [V(0.5, 5, 1), V(1.5, 5, 1), V(1.5, 5, 2), V(0.5, 5, 2)])
    sc.selection.clear()
    sc.selection.add(f)
    props, (o, u, v, n), counts = pp.selection_properties(sc)
    assert counts == (1, 1)
    assert props["area"] == pytest.approx(5.0, abs=1e-5)
    c = props["centroid_world"]
    zc = (6 * 1.5 - 1 * 1.5) / 5
    assert (c.x(), c.y(), c.z()) == pytest.approx((1.0, 5.0, zc), abs=1e-5)
    assert abs(u.x()) == pytest.approx(1.0, abs=1e-6)
    text = pp.format_report(props, (o, u, v, n), counts)
    assert "5.00 m²" in text


def test_faces_in_different_planes_are_refused():
    from core.scene import Scene
    sc = Scene()
    a = sc.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    b = sc.mesh.add_face([V(3, 0, 1), V(4, 0, 1), V(4, 1, 1), V(3, 1, 1)])
    sc.selection.clear()
    sc.selection.update({a, b})
    with pytest.raises(pp.PolygonError):
        pp.selection_properties(sc)
    sc.selection.clear()
    with pytest.raises(pp.PolygonError):
        pp.selection_properties(sc)


def test_it_is_listed_among_the_example_extensions():
    from views.main_window import MainWindow
    titles = [t for _p, t, _b in MainWindow.example_extensions()]
    assert "Polygon properties" in titles


def test_installed_it_adds_its_entries_and_changes_nothing(tmp_path, monkeypatch):
    """Loaded like a user's plugin: an Extensions entry, a right-click
    entry when a face is selected, and a report that leaves the document
    and its undo history as they were."""
    import shutil
    import core.extensions as extensions
    from PySide6.QtWidgets import QDialog, QMenu
    shutil.copy(_PATH, tmp_path / _PATH.name)
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    w = MainWindow()
    try:
        texts = [a.text() for a in w._ext_menu.actions()]
        assert any("Polygon properties" in t or "Propiedades del polígono" in t
                   for t in texts)
        vp = w.viewport
        f = vp.scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 1, 0), V(0, 1, 0)])
        vp.scene.selection.clear()
        vp.scene.selection.add(f)
        menu = QMenu()
        for fn in getattr(w, "_ext_context_menus", []) or []:
            fn(menu, set(vp.scene.selection))
        assert any("Polygon properties" in a.text() or "Propiedades" in a.text()
                   for a in menu.actions())
        ver, undo = vp.scene.version, len(vp.history.undo_stack)
        shown = []
        monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(self) or 0)
        mod = next(m for n, m in sys.modules.items()
                   if n.endswith("propiedades_poligono") and hasattr(m, "show_properties"))
        mod.show_properties(vp)
        assert shown, "the report opened"
        assert (vp.scene.version, len(vp.history.undo_stack)) == (ver, undo)
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()
