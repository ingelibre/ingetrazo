# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tools ▸ Inferences: each point inference can be switched off (#1410,
@pacaeiro: «an option to disable Face Center blue dot»).

A switch that is off never offers its kind, so the next candidate in line
wins — the edge under an endpoint that is off still gives «On edge», it
does not leave the cursor with nothing. «Face center» off also takes the
dots off the selected faces. The choice is remembered and holds in every
view; an extension can add a switch for its own snaps."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.mesh import Mesh
from core.snap import (SNAP_TOGGLES, SnapResult, compute_snap,
                       disabled_snap_kinds, disabled_snap_toggles,
                       register_snap_toggle, set_disabled_snap_toggles,
                       set_snap_toggle_enabled, snap_toggle_enabled)

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture(autouse=True)
def _all_on():
    """Every test starts and ends with every switch on (they are global)."""
    builtin = list(SNAP_TOGGLES)
    set_disabled_snap_toggles(())
    yield
    set_disabled_snap_toggles(())
    SNAP_TOGGLES[:] = builtin


# ---- The switches ------------------------------------------------------------

def test_every_switch_starts_on_and_silences_its_kinds_when_off():
    keys = [t.key for t in SNAP_TOGGLES]
    assert keys == ["endpoint", "midpoint", "intersection", "on_edge",
                    "face_center", "center", "origin"]
    assert disabled_snap_kinds() == frozenset()
    set_snap_toggle_enabled("midpoint", False)
    set_snap_toggle_enabled("on_edge", False)
    assert not snap_toggle_enabled("midpoint")
    assert disabled_snap_toggles() == {"midpoint", "on_edge"}
    assert disabled_snap_kinds() == {"midpoint", "arc_midpoint", "on_edge",
                                     "on_line", "on_circle"}
    set_snap_toggle_enabled("midpoint", True)
    assert disabled_snap_kinds() == {"on_edge", "on_line", "on_circle"}


def test_an_extension_adds_a_switch_and_the_same_key_replaces_it():
    register_snap_toggle("wall_axis", "Wall axis", {"wall_axis"})
    register_snap_toggle("wall_axis", "Wall axis", {"wall_axis", "wall_end"})
    assert [t.key for t in SNAP_TOGGLES].count("wall_axis") == 1
    set_snap_toggle_enabled("wall_axis", False)
    assert disabled_snap_kinds() == {"wall_axis", "wall_end"}


def test_unknown_keys_from_the_settings_are_harmless():
    set_disabled_snap_toggles(["", "no_such_switch", "origin"])
    assert disabled_snap_kinds() == {"origin", "component_origin"}


# ---- In the snap engine: the next candidate wins ------------------------------

def _w2p(p):                      # plan view, 100 px a metre
    return (p.x() * 100.0, -p.y() * 100.0)


def _snap(scene, cand, off=(), **kw):
    return compute_snap(cand, _w2p(cand), scene, _w2p, threshold_px=9.0,
                        edge_threshold_px=14.0, disabled_kinds=off, **kw)


def _square_scene():
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    return SimpleNamespace(edges=[SimpleNamespace(a=e.v0.position, b=e.v1.position)
                                  for e in m.edges])


def test_endpoint_off_gives_the_edge_under_it():
    cand = V(1.95, 0.0)                      # 5 px from the corner (2, 0)
    assert _snap(_square_scene(), cand).kind == "endpoint"
    r = _snap(_square_scene(), cand, off={"endpoint"})
    assert r.kind == "on_edge"


def test_midpoint_off_gives_the_edge_under_it():
    cand = V(1.03, 0.0)
    assert _snap(_square_scene(), cand).kind == "midpoint"
    assert _snap(_square_scene(), cand, off={"midpoint"}).kind == "on_edge"


def test_on_edge_off_leaves_the_face():
    cand = V(0.6, 0.04)
    assert _snap(_square_scene(), cand, face_under_cursor=True).kind == "on_edge"
    r = _snap(_square_scene(), cand, off={"on_edge", "on_line", "on_circle"},
              face_under_cursor=True)
    assert r.kind == "on_face"


def test_intersection_off_gives_the_guide_line():
    far = 1.0e4
    scene = SimpleNamespace(edges=[
        SimpleNamespace(a=V(-far, 1), b=V(far, 1), center=False),
        SimpleNamespace(a=V(1, -far), b=V(1, far), center=False),
    ])
    cand = V(1.03, 1.02)
    assert _snap(scene, cand).kind == "intersection"
    r = _snap(scene, cand, off={"intersection"})
    assert r.kind in ("on_edge", "on_line")


def test_face_center_off_is_on_face_again():
    centers = [(V(1, 1), None)]
    cand = V(1.04, 0.97)
    assert _snap(_square_scene(), cand, face_under_cursor=True,
                 face_centers=centers).kind == "face_center"
    r = _snap(_square_scene(), cand, off={"face_center"},
              face_under_cursor=True, face_centers=centers)
    assert r.kind == "on_face"


def test_center_off_and_origin_off():
    centre = SimpleNamespace(a=V(5, 5), b=V(5, 5), center=True)
    scene = SimpleNamespace(edges=[centre])
    assert _snap(scene, V(5.02, 5.01)).kind == "center"
    assert _snap(scene, V(5.02, 5.01), off={"center"}).kind == "none"
    assert _snap(scene, V(0.02, 0.01)).kind == "origin"
    assert _snap(scene, V(0.02, 0.01), off={"origin"}).kind == "none"


def test_without_the_argument_nothing_changes():
    """A caller that does not pass ``disabled_kinds`` gets every snap."""
    r = compute_snap(V(1.95, 0), _w2p(V(1.95, 0)), _square_scene(), _w2p,
                     threshold_px=9.0, edge_threshold_px=14.0)
    assert r.kind == "endpoint"


# ---- In the viewport ----------------------------------------------------------

def _ring_vp():
    """A 4 × 4 frame with a 2 × 2 hole, seen from above, Line tool on."""
    from tools.line import LineTool
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 600)
    vp.camera.set_aspect(1000, 600)
    vp.flash_status = lambda *a, **k: None
    vp.camera.set_view("top")
    vp.camera.target = V(2, 2, 0)
    vp.camera.distance = 12
    ring = vp.scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)],
                                  [[V(1, 1), V(3, 1), V(3, 3), V(1, 3)]])
    vp.scene.version += 1
    vp.set_active_tool(LineTool())
    return vp, ring


def _hover(vp, world):
    from PySide6.QtCore import QPointF, Qt
    px = vp._world_to_pixel(world)
    vp._process_hover(QPointF(*px), Qt.NoModifier)
    return vp.last_snap


def test_face_center_off_takes_the_dots_and_the_snap_away():
    vp, ring = _ring_vp()
    vp.scene.selection.add(ring)
    assert len(vp._selected_face_centers()) == 1
    assert _hover(vp, V(2.03, 2.02, 0)).kind == "face_center"
    set_snap_toggle_enabled("face_center", False)
    assert vp._selected_face_centers() == []
    assert _hover(vp, V(2.01, 2.04, 0)).kind != "face_center"
    set_snap_toggle_enabled("face_center", True)
    assert len(vp._selected_face_centers()) == 1


def test_an_extensions_snap_whose_switch_is_off_is_passed_over():
    vp, _ring = _ring_vp()
    mine = lambda _vp, snap, px, py: SnapResult(V(9, 9, 0), "wall_axis")
    vp._ext_snap_providers = [mine]
    register_snap_toggle("wall_axis", "Wall axis", {"wall_axis"})
    far = V(8, 8, 0)                         # nothing of the model near
    assert _hover(vp, far).kind == "wall_axis"
    set_snap_toggle_enabled("wall_axis", False)
    assert _hover(vp, V(8.01, 8, 0)).kind != "wall_axis"


# ---- Tools ▸ Inferences --------------------------------------------------------

def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    _app.processEvents()
    return win


def _tools_inferences(win):
    """The «Inferences» entry of the Tools menu (``menuAction``: a
    ``QAction.menu()`` wrapper can come back dead under PySide)."""
    from PySide6.QtWidgets import QMenu
    from core.i18n import tr
    tools = next(m for m in win.menuBar().findChildren(QMenu)
                 if m.title() == tr("Tools"))
    act = win._inference_menu.menuAction()
    assert act in tools.actions() and act.text() == tr("Inferences")
    return act


def test_the_menu_switches_remember_and_turn_all_back_on():
    from PySide6.QtCore import QSettings
    win = _window()
    try:
        assert _tools_inferences(win) is not None
        acts = win._inference_actions
        assert list(acts) == [t.key for t in SNAP_TOGGLES]
        assert all(a.isCheckable() and a.isChecked() for a in acts.values())
        assert not win._act_inferences_all.isEnabled()
        acts["face_center"].setChecked(False)
        assert not snap_toggle_enabled("face_center")
        assert QSettings().value(win._INFERENCES_OFF_KEY) == "face_center"
        assert win._act_inferences_all.isEnabled()
        acts["origin"].setChecked(False)
        assert QSettings().value(win._INFERENCES_OFF_KEY) == "face_center,origin"
        win._act_inferences_all.trigger()
        assert disabled_snap_toggles() == frozenset()
        assert all(a.isChecked() for a in acts.values())
        assert QSettings().value(win._INFERENCES_OFF_KEY) == ""
    finally:
        win.close()
        win.deleteLater()


def test_the_choice_comes_back_on_the_next_start():
    from PySide6.QtCore import QSettings
    from views.main_window import MainWindow
    QSettings().setValue(MainWindow._INFERENCES_OFF_KEY, "endpoint,face_center")
    win = _window()
    try:
        assert disabled_snap_toggles() == {"endpoint", "face_center"}
        assert not win._inference_actions["endpoint"].isChecked()
        assert win._inference_actions["midpoint"].isChecked()
    finally:
        QSettings().remove(MainWindow._INFERENCES_OFF_KEY)
        win.close()
        win.deleteLater()


def test_an_extension_switch_shows_up_when_the_menu_opens():
    win = _window()
    try:
        register_snap_toggle("wall_axis", "Wall axis", {"wall_axis"})
        assert "wall_axis" not in win._inference_actions
        win._inference_menu.aboutToShow.emit()
        act = win._inference_actions["wall_axis"]
        assert act.text() == "Wall axis" and act.isChecked()
        act.setChecked(False)
        assert "wall_axis" in disabled_snap_kinds()
    finally:
        win.close()
        win.deleteLater()
