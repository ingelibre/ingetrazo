# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Display styles (SketchUp Styles): presets, persistence, scene binding."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from core.scene import Scene
from core.style import BUILTIN_STYLES, FACE_MODES, Style

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def test_style_roundtrip_and_defaults():
    s = Style()
    assert s.face_mode == "textures" and s.edges and s.profiles and s.sky
    again = Style.from_dict(s.to_dict())
    assert again.to_dict() == s.to_dict()
    assert Style.from_dict({"face_mode": "no_such_mode"}).face_mode == "textures"
    c = s.copy()
    c.edges = False
    assert s.edges is True                     # copies never alias


def test_builtin_presets_cover_the_sketchup_classics():
    names = {p.name for p in BUILTIN_STYLES}
    assert {"Default", "Architectural", "Shaded", "Hidden line",
            "Monochrome", "Wireframe", "X-ray"} <= names
    for p in BUILTIN_STYLES:
        assert p.face_mode in FACE_MODES
    hidden = next(p for p in BUILTIN_STYLES if p.name == "Hidden line")
    assert hidden.face_mode == "hidden_line"
    assert hidden.background == (1.0, 1.0, 1.0) and not hidden.sky


def test_scene_carries_a_style_and_clear_resets_it():
    scene = Scene()
    assert scene.display_style.face_mode == "textures"
    scene.display_style = Style(name="Hidden line", face_mode="hidden_line")
    scene.mesh.add_edge(_v(0, 0), _v(1, 0))    # so clear() has work to do
    scene.clear()
    assert scene.display_style.face_mode == "textures"


def test_igz_roundtrip_keeps_the_style(tmp_path):
    from formats import igz as igz_format
    scene = Scene()
    scene.mesh.add_edge(_v(0, 0), _v(1, 0))
    scene.display_style = Style(name="Monochrome", face_mode="monochrome",
                                background=(1.0, 1.0, 1.0), sky=False)
    path = tmp_path / "estilo.igz"
    igz_format.save_scene(scene, path)

    fresh = Scene()
    igz_format.load_into(fresh, path)
    assert fresh.display_style.name == "Monochrome"
    assert fresh.display_style.face_mode == "monochrome"
    assert fresh.display_style.sky is False

    # A default style stays implicit — old readers see the same terse file.
    scene2 = Scene()
    scene2.mesh.add_edge(_v(0, 0), _v(1, 0))
    igz_format.save_scene(scene2, path)
    fresh2 = Scene()
    igz_format.load_into(fresh2, path)
    assert fresh2.display_style.to_dict() == Style().to_dict()


def test_saved_view_remembers_the_style():
    from core.camera import OrbitCamera
    from core.saved_views import SavedView
    scene = Scene()
    cam = OrbitCamera()
    scene.display_style = Style(name="Hidden line", face_mode="hidden_line")
    view = SavedView.capture("Planta", scene, cam)

    scene.display_style = Style()              # user switches back to Default
    view.apply(scene, cam)                     # recalling the scene restores it
    assert scene.display_style.face_mode == "hidden_line"

    # Round-trip through the .igz dict form.
    again = SavedView.from_dict(view.to_dict())
    scene.display_style = Style()
    again.apply(scene, cam)
    assert scene.display_style.name == "Hidden line"


def test_style_by_name_returns_copies():
    from core.style import style_by_name
    a = style_by_name("Architectural")
    assert a is not None and a.face_mode == "textures"
    assert a.background == (1.0, 1.0, 1.0) and a.sky is False
    a.edges = False
    b = style_by_name("Architectural")
    assert b.edges is True                     # presets stay pristine
    assert style_by_name("No existe") is None


def test_composer_style_combo_lists_the_presets():
    # The composer's per-frame style list must carry the model styles
    # (the "Architectural is missing in layout" report) and map legacy
    # keys onto their preset equivalents.
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win._on_open_composer()
        composer = win._composer
        combo = composer.style_combo
        keys = [combo.itemData(i) for i in range(combo.count())]
        assert "sombreado" in keys             # the model's active style
        assert "style:Architectural" in keys
        assert "style:Hidden line" in keys
        assert "vectorial" in keys
        assert "tecnico" not in keys           # legacy keys leave the UI
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _v(x, y, z=0.0):
    from PySide6.QtGui import QVector3D
    return QVector3D(x, y, z)
