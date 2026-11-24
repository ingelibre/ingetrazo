# SPDX-License-Identifier: GPL-3.0-or-later
"""A window or a door that stands upright (blue axis up, like every dynamic
component) says which of its sides is flush with the wall: its «cut plane».
The hole is cut from that side, into the wall; the arrow over it shows the
way, and flipping reverses it. Choosing the plane is one undo step."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402

from core import openings  # noqa: E402
from core.group import Group  # noqa: E402
from core.history import History, InsertGroupCommand  # noqa: E402
from core.orient import orient_outward  # noqa: E402
from core.scene import Scene  # noqa: E402


def _wall(mesh, length=3.0, thick=0.2, height=2.5):
    p = [V(0, 0, 0), V(length, 0, 0), V(length, thick, 0), V(0, thick, 0)]
    q = [V(0, 0, height), V(length, 0, height), V(length, thick, height),
         V(0, thick, height)]
    mesh.add_face(p)
    mesh.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        mesh.add_face([p[i], p[j], q[j], q[i]])
    orient_outward(mesh)


def _upright_window(x=1.0, z=0.9, w=1.0, h=1.2, depth=0.05, bars=False):
    """Standing as drawn in the front view: x across, z up, y into the wall;
    its front is at y = 0. ``bars`` builds it of four bars (no single face
    is the outline) instead of one pane."""
    g = Group(name="Window")
    m = g.mesh
    if bars:
        t = 0.05
        for lo, hi in (((x, z), (x + t, z + h)),
                       ((x + w - t, z), (x + w, z + h)),
                       ((x, z), (x + w, z + t)),
                       ((x, z + h - t), (x + w, z + h))):
            m.add_face([V(lo[0], 0, lo[1]), V(hi[0], 0, lo[1]),
                        V(hi[0], 0, hi[1]), V(lo[0], 0, hi[1])])
    else:
        m.add_face([V(x, 0, z), V(x + w, 0, z), V(x + w, 0, z + h), V(x, 0, z + h)])
        m.add_face([V(x, depth, z), V(x, depth, z + h),
                    V(x + w, depth, z + h), V(x + w, depth, z)])
    return g


def _closed(mesh) -> bool:
    return all(len(e.faces) == 2 for e in mesh.edges)


@pytest.fixture
def model():
    scene = Scene()
    _wall(scene.mesh)
    return scene, History(scene)


def _choose(history, scene, g, side):
    history.execute(openings.SetCutPlaneCommand([g], side))


def test_an_upright_window_has_nothing_to_cut_on_its_base_plane():
    g = _upright_window()
    fp = openings.footprint(g)
    n = openings._normal(fp)
    assert abs(n.z()) > 0.99                      # horizontal: not the wall


def test_the_front_plane_takes_the_outline_on_the_wall(model):
    scene, history = model
    g = _upright_window()
    history.execute(InsertGroupCommand(g))
    before = len(scene.mesh.faces)
    _choose(history, scene, g, "front")
    assert openings.side_of(g) == "front"
    fp = openings.footprint(g)
    assert all(abs(p.y()) < 1e-6 for p in fp)
    assert {round(p.x(), 4) for p in fp} == {1.0, 2.0}
    assert {round(p.z(), 4) for p in fp} == {0.9, 2.1}
    assert len(scene.mesh.faces) == 10 and before == 6   # opened through
    assert _closed(scene.mesh)


def test_choosing_the_plane_is_one_undo_step(model):
    scene, history = model
    g = _upright_window()
    history.execute(InsertGroupCommand(g))
    _choose(history, scene, g, "front")
    history.undo()
    assert len(scene.mesh.faces) == 6
    assert openings.side_of(g) is None
    history.redo()
    assert len(scene.mesh.faces) == 10


def test_the_arrow_points_into_the_wall_and_flipping_reverses_the_cut(model):
    scene, history = model
    g = _upright_window()
    history.execute(InsertGroupCommand(g))
    _choose(history, scene, g, "front")
    centre, n = openings.direction(g)
    assert n.y() > 0.99 and abs(centre.y()) < 1e-6        # from y = 0 into the wall
    assert openings.flipped_side(g) == "back"
    _choose(history, scene, g, openings.flipped_side(g))
    assert len(scene.mesh.faces) == 6                      # air behind: wall whole
    assert openings.direction(g)[1].y() < -0.99
    _choose(history, scene, g, openings.flipped_side(g))   # and back again
    assert len(scene.mesh.faces) == 10


def test_a_component_of_bars_can_take_the_covered_rectangle(model):
    scene, history = model
    g = _upright_window(bars=True)
    openings.set_ext_entry(g, {"on": True})
    history.execute(openings.SetCutPlaneCommand([g], "front"))
    bar = openings.footprint(g)
    assert {round(p.x(), 4) for p in bar} == {1.0, 1.05}   # one bar: not the window
    entry = dict(g.ext["opening"])
    entry["plane"] = dict(entry["plane"], outline="box")
    openings.set_ext_entry(g, entry)
    box = openings.footprint(g)
    assert {round(p.x(), 4) for p in box} == {1.0, 2.0}
    assert {round(p.z(), 4) for p in box} == {0.9, 2.1}


def test_the_base_plane_is_unchanged_when_none_is_chosen():
    g = _upright_window()
    assert openings.side_of(g) is None
    assert openings.flipped_side(g) == "bottom"


# ---- the window: the menu's command and the arrow ------------------------------
@pytest.fixture
def win(tmp_path, monkeypatch):
    # Same isolation as tests/test_extension_api_v2.py's window.
    import sys
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    store = tmp_path / "settings"
    store.mkdir()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(store))
    shared = next(m._settings_dir for n, m in list(sys.modules.items())
                  if n.endswith("conftest") and hasattr(m, "_settings_dir"))
    import core.extensions as extensions
    monkeypatch.setattr(extensions, "user_plugins_dir",
                        lambda: tmp_path / "plugins")
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1000, 700)
    w.show()
    QApplication.processEvents()
    yield w
    w._workspace = None
    w._saved_version = w.viewport.scene.version
    w.close()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, shared)


def test_the_menu_command_and_the_arrow(win):
    from PySide6.QtGui import QColor, QImage, QPainter
    vp = win.viewport
    _wall(vp.scene.mesh)
    g = _upright_window()
    vp.history.execute(InsertGroupCommand(g))
    vp.scene.selection.clear()
    vp.scene.selection.add(g)
    win.set_cut_plane("front")                      # chooses the side, marks it
    assert openings.side_of(g) == "front" and openings.wants_opening(g)
    assert len(vp.scene.mesh.faces) == 10
    win.set_cut_plane("flip")                       # air behind: it closes
    assert openings.side_of(g) == "back" and len(vp.scene.mesh.faces) == 6
    win.set_cut_plane("flip")
    assert len(vp.scene.mesh.faces) == 10
    img = QImage(vp.width(), vp.height(), QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    vp._draw_cut_arrows(p)                          # the arrow, over the selection
    p.end()
    orange = QColor(232, 116, 42).rgb()
    assert any(img.pixel(x, y) == orange
               for x in range(0, img.width(), 2) for y in range(0, img.height(), 2))
