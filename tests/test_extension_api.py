# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The extension API beyond tools — ``setup(app)`` (views/extension_api.py).

Marco, 25-09, on José Castro's Levels: «hacer muchas funciones que cada
usuario me pida cargaría mucho al sistema… ¿no sería bueno hacerlo como una
extensión?». So a plugin can now keep data in the document, add a side
panel, draw over the viewport and offer an inference — and Levels is the
worked example, living in examples/extensions/, not in the core."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D as V

from core.history import History, SetPluginDataCommand
from core.scene import Scene

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "extensions"


def test_extension_data_travels_in_the_igz_and_new_clears_it(tmp_path):
    from formats import igz
    scene = Scene()
    scene.plugin_data["niveles"] = {"levels": [{"name": "PA", "z": 2.6}]}
    scene.plugin_data["roto"] = {1, 2}          # not JSON: dropped, not fatal
    path = tmp_path / "m.igz"
    igz.save_scene(scene, path)
    other = Scene()
    igz.load_into(other, path)
    assert other.plugin_data == {"niveles": {"levels": [{"name": "PA",
                                                          "z": 2.6}]}}
    other.clear()
    assert other.plugin_data == {}


def test_setting_extension_data_is_one_undo_step():
    scene = Scene()
    hist = History(scene)
    hist.execute(SetPluginDataCommand("niveles", {"guides": True}))
    hist.execute(SetPluginDataCommand("niveles", {"guides": False}))
    assert scene.plugin_data["niveles"] == {"guides": False}
    hist.undo()
    assert scene.plugin_data["niveles"] == {"guides": True}
    hist.undo()
    assert "niveles" not in scene.plugin_data
    hist.redo()
    assert scene.plugin_data["niveles"] == {"guides": True}


def test_a_setup_only_plugin_is_discovered(tmp_path):
    from core.extensions import discover_plugins
    (tmp_path / "solo_panel.py").write_text(
        "def setup(app):\n    app.called = True\n")
    plugins, errors = discover_plugins([tmp_path])
    assert not errors
    assert [p.stem for p in plugins] == ["solo_panel"]
    assert plugins[0].tools == [] and callable(plugins[0].setup)


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_a_failing_setup_is_an_error_entry_not_a_crash(tmp_path, monkeypatch):
    from core import extensions
    (tmp_path / "rota.py").write_text(
        "def setup(app):\n    raise RuntimeError('boom')\n")
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    win = _window()
    try:
        ext = next(m for m in win.menuBar().actions()
                   if m.menu() is not None and "xtensi" in m.text()).menu()
        entries = [a for a in ext.actions() if "rota" in a.text()]
        assert entries and not entries[0].isEnabled()
        assert "boom" in entries[0].toolTip()
    finally:
        _close(win)


@pytest.fixture
def levels(monkeypatch):
    """A window with the Levels example installed."""
    from core import extensions
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [EXAMPLES])
    win = _window()
    yield win
    _close(win)


def _app(win):
    from views.extension_api import ExtensionApp
    return ExtensionApp(win, "niveles")


def test_levels_adds_its_tab_and_keeps_levels_in_the_document(levels):
    win = levels
    assert any(d.objectName() == "extension_niveles"
               for d in win._extension_docks)
    app = _app(win)
    app.set_document_data({"levels": [{"name": "PB", "z": 0.0},
                                      {"name": "PA", "z": 2.6}],
                           "guides": True})
    panel = win._extension_docks[0].widget()
    assert panel.list.count() == 2
    assert panel.list.item(0).text().startswith("PA")     # highest on top
    win._on_undo()                                        # one undo step
    assert panel.list.count() == 0


def _front_parallel(vp):
    vp.camera.set_view("front")
    vp.camera.perspective = False
    vp.camera.target = V(0, 0, 1.5)
    vp.camera.distance = 20.0
    vp.resize(800, 600)
    vp.camera.set_aspect(800, 600)


def test_levels_snap_in_a_parallel_elevation_and_say_which(levels):
    from core.snap import SnapResult
    win = levels
    vp = win.viewport
    _app(win).set_document_data({"levels": [{"name": "PA", "z": 2.6}],
                                 "guides": True})
    _front_parallel(vp)
    near = vp._world_to_pixel(V(1.0, 0.0, 2.6))
    free = SnapResult(V(1.0, 0.0, 2.58), "on_face")
    got = vp._extension_snap(free, near[0], near[1])
    assert got is not free and got.label == "PA"
    assert got.point.z() == pytest.approx(2.6)
    # a named point is never taken away
    corner = SnapResult(V(1.0, 0.0, 2.58), "endpoint")
    assert vp._extension_snap(corner, near[0], near[1]) is corner
    # far from the level: the engine's answer stands
    far = SnapResult(V(1.0, 0.0, 0.5), "on_face")
    assert vp._extension_snap(far, *vp._world_to_pixel(far.point)) is far
    # in perspective no level snaps (heights do not read)
    vp.camera.perspective = True
    assert vp._extension_snap(free, near[0], near[1]) is free


def test_levels_guides_turn_off_with_their_checkbox(levels):
    from core.snap import SnapResult
    win = levels
    vp = win.viewport
    _app(win).set_document_data({"levels": [{"name": "PA", "z": 2.6}],
                                 "guides": False})
    _front_parallel(vp)
    free = SnapResult(V(1.0, 0.0, 2.58), "on_face")
    near = vp._world_to_pixel(V(1.0, 0.0, 2.6))
    assert vp._extension_snap(free, near[0], near[1]) is free


def test_a_raising_provider_cannot_take_the_cursor(levels):
    from core.snap import SnapResult
    vp = levels.viewport

    def broken(*_a):
        raise ValueError("plugin bug")
    vp._ext_snap_providers.insert(0, broken)
    s = SnapResult(V(0, 0, 0), "on_face")
    assert vp._extension_snap(s, 10, 10) is s


def test_levels_panel_has_a_one_click_way_to_where_the_guides_show(levels):
    """«Hice niveles pero no veo nada en el dibujo» — the camera was in
    perspective. The panel's button goes to a parallel front elevation."""
    win = levels
    vp = win.viewport
    vp.camera.perspective = True
    panel = win._extension_docks[0].widget()
    panel._show_elevation()
    assert not vp.camera.perspective
    assert abs(vp.camera.pitch) < 1e-6


def test_the_example_extensions_ship_but_install_only_on_request(tmp_path,
                                                                 monkeypatch):
    """Marco: «sería bueno tener esa extensión como ejemplo en IngeTrazo para
    que otros usuarios vean» — shipped with the app, listed in Extensions ▸
    Example extensions, loaded only once someone installs it there."""
    from PySide6.QtWidgets import QMessageBox
    from core import extensions
    from views.main_window import MainWindow
    examples = MainWindow.example_extensions()
    assert any(p.name == "niveles.py" and title == "Niveles"
               for p, title, _blurb in examples)
    user = tmp_path / "plugins"
    monkeypatch.setattr(extensions, "user_plugins_dir", lambda: user)
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [user])
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    win = _window()
    try:
        assert not win._extension_docks            # not loaded by default
        menu = next(m for m in win.menuBar().actions()
                    if m.menu() is not None and "xtensi" in m.text()).menu()
        sub = next(a.menu() for a in menu.actions()
                   if a.menu() is not None)
        act = next(a for a in sub.actions() if a.text() == "Niveles")
        assert not act.isChecked()
        act.trigger()                               # install
        assert (user / "niveles.py").read_bytes() == \
            (EXAMPLES / "niveles.py").read_bytes()
        act.trigger()                               # and remove
        assert not (user / "niveles.py").exists()
    finally:
        _close(win)


def test_an_example_extension_can_be_a_package(tmp_path, monkeypatch):
    """A bigger example extension (CAM, PR #132) is a folder with an
    ``__init__.py``: it is listed from its package docstring, installed as
    the whole folder (no ``__pycache__``) and removed as a whole."""
    from PySide6.QtWidgets import QMessageBox
    from core import extensions, paths
    from views.main_window import MainWindow
    root = tmp_path / "app"
    pkg = root / "examples" / "extensions" / "demo"
    (pkg / "engine").mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        '"""Demo — a packaged example\n\nTwo files and a subfolder."""\n'
        "def setup(app):\n    pass\n", encoding="utf-8")
    (pkg / "engine" / "core.py").write_text("X = 1\n", encoding="utf-8")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "junk.pyc").write_bytes(b"x")
    monkeypatch.setattr(paths, "app_root", lambda: root)
    user = tmp_path / "plugins"
    monkeypatch.setattr(extensions, "user_plugins_dir", lambda: user)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    examples = MainWindow.example_extensions()
    assert [(p.name, t, b) for p, t, b in examples] == [
        ("demo", "Demo", "Two files and a subfolder.")]
    MainWindow._toggle_example_extension(None, pkg, "Demo", True)
    assert (user / "demo" / "engine" / "core.py").read_text() == "X = 1\n"
    assert not (user / "demo" / "__pycache__").exists()
    MainWindow._toggle_example_extension(None, pkg, "Demo", False)
    assert not (user / "demo").exists()
