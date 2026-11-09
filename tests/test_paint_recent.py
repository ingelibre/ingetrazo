# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The «Recent» row of the Materials panel: the last materials painted
with, newest first, no duplicates, at most ``RECENT_MAX``; one click makes
one the active paint again, exactly as it was painted; the list survives
a restart, minus images that are gone from disk."""
from __future__ import annotations

import os
import random

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QSettings, Qt
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.history import History                                  # noqa: E402
from core.materials import Material                               # noqa: E402
from core.scene import Scene                                      # noqa: E402
from tools.base import ToolContext                                # noqa: E402
from tools.paint import (                                         # noqa: E402
    RECENT_MAX, PaintTool, push_recent, recent_key)


def _quad(mesh, z=0.0):
    return mesh.add_face([QVector3D(0, 0, z), QVector3D(4, 0, z),
                          QVector3D(4, 4, z), QVector3D(0, 4, z)])


class _FakeViewport:
    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)
        self._pick = None

    def pick_face_any(self, _x, _y):
        return self._pick, None

    def update(self):
        pass

    def set_hover(self, _f):
        pass


def _click(vp, face):
    vp._pick = face
    PaintTool().on_click(ToolContext(viewport=vp, world=QVector3D(),
                                     screen=QPointF(0, 0),
                                     modifiers=Qt.NoModifier, snap=None))


def _use(color=None, texture=None, name=None, opacity=None):
    """Make this the active paint, as the tray would."""
    PaintTool.current_is_default = False
    PaintTool.current_texture = texture
    if color is not None:
        PaintTool.current_color = color
    PaintTool.current_opacity = opacity
    PaintTool.current_material = (
        Material(name, color=color, texture=texture) if name else None)


def _png(path, rgb):
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor.fromRgbF(*rgb))
    assert img.save(str(path))
    return str(path)


@pytest.fixture(autouse=True)
def _reset_paint_state():
    PaintTool.recent = []
    QSettings().remove("paint/recent_materials")
    yield
    PaintTool.recent = []
    PaintTool.current_is_default = False
    PaintTool.current_material = None
    PaintTool.current_texture = None
    PaintTool.current_texture_plane = None
    PaintTool.current_opacity = None
    PaintTool.current_color = (0.80, 0.45, 0.30)
    QSettings().remove("paint/recent_materials")


# ---- the list itself --------------------------------------------------------

def test_push_recent_against_a_reference_model():
    """Hundreds of random paints from a pool of materials: the list always
    equals «distinct materials, most recent use first, cut at the cap»."""
    rng = random.Random(1234)
    pool = []
    for i in range(15):
        if i % 3 == 0:
            pool.append({"texture": {"path": f"/t/{i}.png", "sw": 1.0,
                                     "sh": 1.0, "rot": 0.0}})
        elif i % 3 == 1:
            pool.append({"color": [rng.random(), rng.random(), rng.random()],
                         "mat": f"Mat {i}"})
        else:
            pool.append({"color": [rng.random(), rng.random(), rng.random()]})
    entries, history = [], []
    for _ in range(500):
        e = rng.choice(pool)
        entries = push_recent(entries, dict(e))
        history.append(recent_key(e))
        expected = []
        for k in reversed(history):
            if k not in expected:
                expected.append(k)
        assert [recent_key(x) for x in entries] == expected[:RECENT_MAX]


def test_a_named_material_is_one_entry_whatever_its_look():
    a = {"color": [1, 0, 0], "mat": "Ladrillo"}
    b = {"color": [0.9, 0.1, 0.1], "mat": "Ladrillo"}
    assert push_recent([a], b) == [b]


def test_same_image_at_another_size_is_another_entry():
    t1 = {"texture": {"path": "/a.png", "sw": 1.0, "sh": 1.0, "rot": 0.0}}
    t2 = {"texture": {"path": "/a.png", "sw": 2.0, "sh": 2.0, "rot": 0.0}}
    assert len(push_recent([t1], t2)) == 2


# ---- painting fills it --------------------------------------------------------

def test_painting_puts_the_material_first():
    vp = _FakeViewport()
    face = _quad(vp.scene.mesh)
    _use(color=(0.1, 0.2, 0.3), name="Azul")
    _click(vp, face)
    _use(color=(0.9, 0.8, 0.7))
    _click(vp, face)
    assert [e.get("mat") for e in PaintTool.recent] == [None, "Azul"]
    _use(color=(0.1, 0.2, 0.3), name="Azul")
    _click(vp, face)
    assert [e.get("mat") for e in PaintTool.recent] == ["Azul", None]


def test_seven_materials_keep_the_last_six():
    vp = _FakeViewport()
    face = _quad(vp.scene.mesh)
    for i in range(RECENT_MAX + 1):
        _use(color=(i / 10, 0.5, 0.5), name=f"M{i}")
        _click(vp, face)
    assert [e["mat"] for e in PaintTool.recent] == [
        f"M{i}" for i in range(RECENT_MAX, 0, -1)]


def test_default_material_is_not_remembered():
    vp = _FakeViewport()
    face = _quad(vp.scene.mesh)
    PaintTool.current_is_default = True
    _click(vp, face)
    assert PaintTool.recent == []


def test_a_sampled_positioned_texture_is_remembered_without_its_map():
    """The world→UV map only means something on its own plane: the recent
    entry carries the look (image, size, turn), not the map."""
    vp = _FakeViewport()
    face = _quad(vp.scene.mesh)
    tex = {"path": "/x.png", "sw": 0.5, "sh": 0.5, "rot": 30.0,
           "uvw": [[1, 0, 0, 0], [0, 1, 0, 0]]}
    _use(texture=tex, name="Piedra")
    _click(vp, face)
    (entry,) = PaintTool.recent
    assert "uvw" not in entry["texture"]
    assert entry["texture"]["rot"] == 30.0 and entry["mat"] == "Piedra"


# ---- the panel ----------------------------------------------------------------

def _row_tips(panel):
    g = panel._recent_grid
    return [g.itemAt(i).widget().toolTip() for i in range(g.count())]


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


def _panel(w):
    from views.tray import MaterialsPanel
    return w.findChild(MaterialsPanel)


def test_panel_row_follows_paints_and_hides_when_empty(window, tmp_path):
    panel = _panel(window)
    vp = window.viewport
    assert _row_tips(panel) == []
    assert panel._recent_heading.isHidden()
    face = _quad(vp.scene.mesh)
    vp._pixel_to_ray = lambda *_a: (None, None)
    vp.pick_face_any = lambda *_a: (face, None)
    tex = _png(tmp_path / "ladrillo.png", (0.7, 0.3, 0.2))
    _use(texture={"path": tex, "sw": 0.3, "sh": 0.2, "rot": 0.0})
    PaintTool().on_click(ToolContext(viewport=vp, world=QVector3D(),
                                     screen=QPointF(0, 0),
                                     modifiers=Qt.NoModifier, snap=None))
    _use(color=(0.2, 0.4, 0.6), name="RAL 5015")
    PaintTool().on_click(ToolContext(viewport=vp, world=QVector3D(),
                                     screen=QPointF(0, 0),
                                     modifiers=Qt.NoModifier, snap=None))
    assert _row_tips(panel) == ["RAL 5015", "ladrillo"]
    assert not panel._recent_heading.isHidden()


def test_clicking_a_recent_swatch_restores_it_exactly(window, tmp_path):
    panel = _panel(window)
    tex = _png(tmp_path / "vidrio.png", (0.6, 0.8, 0.9))
    PaintTool.recent = [
        {"texture": {"path": tex, "sw": 1.5, "sh": 0.75, "rot": 90.0},
         "opacity": 0.4, "mat": "Vidrio"},
        {"color": [0.25, 0.5, 0.75]},
    ]
    panel._refresh_recent()
    PaintTool.current_is_default = True
    panel._recent_grid.itemAt(0).widget().click()
    assert PaintTool.current_is_default is False
    assert PaintTool.current_texture == {"path": tex, "sw": 1.5, "sh": 0.75,
                                         "rot": 90.0}
    assert PaintTool.current_opacity == 0.4
    assert PaintTool.current_material.name == "Vidrio"
    assert panel._sw_box.value() == 1.5 and panel._rot_box.value() == 90.0
    assert isinstance(window.viewport.active_tool, PaintTool)

    panel._recent_grid.itemAt(1).widget().click()
    assert PaintTool.current_texture is None
    assert PaintTool.current_color == (0.25, 0.5, 0.75)
    assert PaintTool.current_material is None
    assert PaintTool.current_opacity is None
    # Picking from the row does not reorder it: only painting does.
    assert PaintTool.recent[0]["mat"] == "Vidrio"


def test_the_list_survives_a_restart_minus_missing_images(tmp_path):
    from views.tray import load_recent_materials, save_recent_materials
    kept = _png(tmp_path / "kept.png", (0.5, 0.5, 0.5))
    entries = [
        {"texture": {"path": kept, "sw": 1.0, "sh": 1.0, "rot": 0.0},
         "mat": "Gris"},
        {"texture": {"path": str(tmp_path / "gone.png"), "sw": 1.0,
                     "sh": 1.0, "rot": 0.0}},
        {"color": [0.1, 0.2, 0.3], "opacity": 0.5},
    ]
    save_recent_materials(entries)
    assert load_recent_materials() == [entries[0], entries[2]]


def test_corrupt_settings_read_as_empty():
    from views.tray import load_recent_materials
    QSettings().setValue("paint/recent_materials", "{not json")
    assert load_recent_materials() == []
    QSettings().setValue("paint/recent_materials", '[1, "x", {"foo": 2}]')
    assert load_recent_materials() == []
