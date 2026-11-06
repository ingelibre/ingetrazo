# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The 3D terrain is the document's: saved with its base map, back on
when the file is opened again, its own in each tab. It lived in the
window, so a project saved with the terrain on reopened flat after a
restart, and what stood on the terrain floated over the map."""
from __future__ import annotations

from georef.datum import SceneDatum


def _georef_scene(terrain3d=None):
    from core.scene import Scene
    from georef.tiles import PRESETS, TileLayer
    scene = Scene()
    scene.georef = SceneDatum(-16.39889, -71.53694)
    layer = TileLayer(PRESETS["esri_imagery"], zoom=16)
    layer.set_rectangle(400.0, 300.0)
    if terrain3d is not None:
        layer.terrain3d = terrain3d
    scene.tile_layer = layer
    return scene


def test_the_flag_round_trips_and_old_files_open_flat(tmp_path):
    from core.scene import Scene
    from formats import igz
    for want in (True, False):
        out = tmp_path / f"t{want}.igz"
        igz.save_scene(_georef_scene(want), out)
        back = Scene()
        igz.load_into(back, out)
        assert back.tile_layer.terrain3d is want
    from georef.tiles import TileLayer
    raw = _georef_scene().tile_layer.to_dict()
    del raw["terrain3d"]                       # a file from before
    assert TileLayer.from_dict(raw).terrain3d is False


def _window(monkeypatch):
    from views.main_window import MainWindow
    win = MainWindow()
    built = []
    monkeypatch.setattr(win, "_build_terrain", lambda: built.append(
        bool(win._terrain_on)))
    return win, built


def test_turning_it_on_is_kept_in_the_document(monkeypatch):
    win, built = _window(monkeypatch)
    try:
        scene = win.viewport.scene
        scene.georef = SceneDatum(-16.39889, -71.53694)
        from georef.tiles import PRESETS, TileLayer
        scene.tile_layer = TileLayer(PRESETS["esri_imagery"], zoom=16)
        win.set_terrain_enabled(True)
        assert scene.tile_layer.terrain3d and win._terrain_on
        win.set_terrain_enabled(False)
        assert not scene.tile_layer.terrain3d and not win._terrain_on
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_file_saved_in_3d_opens_in_3d(tmp_path, monkeypatch):
    from formats import igz
    path = tmp_path / "relieve.igz"
    igz.save_scene(_georef_scene(True), path)
    win, built = _window(monkeypatch)
    try:
        assert not win._terrain_on                 # a fresh window: flat
        assert win.open_path(path)
        assert win._terrain_on
        assert built and built[-1] is True         # asked to build it
        assert win.georef_tray.base_map._terrain3d.isChecked()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_file_saved_flat_opens_flat(tmp_path, monkeypatch):
    from formats import igz
    path = tmp_path / "plano.igz"
    igz.save_scene(_georef_scene(False), path)
    win, built = _window(monkeypatch)
    try:
        win.__dict__["_terrain_wish"] = True        # on in another project
        assert win.open_path(path)
        assert not win._terrain_on and not built
        assert not win.georef_tray.base_map._terrain3d.isChecked()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_new_capture_keeps_the_terrain_as_it_was(monkeypatch):
    win, built = _window(monkeypatch)
    try:
        bm = win.georef_tray.base_map
        scene = win.viewport.scene
        scene.georef = SceneDatum(-16.39889, -71.53694)
        bm._capture_around(bm._current_source(), scene, scene.georef,
                           -50, -50, 50, 50)
        win.set_terrain_enabled(True)
        bm._capture_around(bm._current_source(), scene, scene.georef,
                           -500, -500, 500, 500)
        assert scene.tile_layer.terrain3d and win._terrain_on
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
