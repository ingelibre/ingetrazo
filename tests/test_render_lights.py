# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Render tab and its lights (#181; Marco: «aprovechar la barra lateral
derecha para el apartado renderizar… lo único que le falta es puntos de
luz o focos, como para renderizar de noche»). Render with Blender lives in
the side tray, not a menu; point lights and spots are clicked onto the
model, kept in the document (undoable, saved in the .igz) and become real
Blender lights; an ambience of day, night or overcast sets the sky."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication([])

from core import render_blender as rb  # noqa: E402
from core.camera import OrbitCamera  # noqa: E402
from core.scene import Scene  # noqa: E402


# ---- The data ----------------------------------------------------------------

def test_clean_lights_keeps_only_well_formed_ones():
    raw = [
        {"kind": "point", "pos": [1, 2, 3], "color": "cool", "power": 250},
        {"kind": "spot", "pos": [0, 0, 5], "dir": [0, 0, 0], "angle": 500},
        {"kind": "laser", "pos": [0, 0, 0]},             # unknown kind
        {"kind": "point", "pos": ["x", 0, 0]},           # not a number
        {"kind": "point", "pos": [float("nan"), 0, 0]},  # not finite
        "garbage",
    ]
    out = rb.clean_lights(raw)
    assert [lt["kind"] for lt in out] == ["point", "spot"]
    assert out[0]["color"] == list(rb.LIGHT_COLORS["cool"])
    assert out[1]["dir"] == [0.0, 0.0, -1.0]             # a null aim → down
    assert out[1]["angle"] == 179.0                      # clamped
    assert out[1]["power"] == rb.DEFAULT_POWER["spot"]
    assert rb.clean_lights(None) == []


def _box():
    scene = Scene()
    m = scene.mesh
    p = [V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0),
         V(0, 0, 2), V(2, 0, 2), V(2, 2, 2), V(0, 2, 2)]
    for loop in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in loop])
    return scene


def _cam(scene):
    cam = OrbitCamera()
    cam.set_aspect(320, 180)
    cam.yaw, cam.pitch = -1.0, 0.4
    lo, hi = scene.bounds()
    cam.fit_to(lo, hi)
    return cam


def test_night_and_overcast_have_no_sun_and_lights_off_stay_out(tmp_path):
    scene = _box()
    lights = [{"kind": "point", "pos": [1, 1, 3], "on": True},
              {"kind": "spot", "pos": [1, 1, 5], "on": False}]
    for amb in rb.AMBIENCES:
        job = json.loads(rb.write_job(scene, _cam(scene), tmp_path / amb,
                                      ambience=amb, lights=lights)
                         .read_text())
        assert job["ambience"] == amb
        assert job["exposure"] == rb.EXPOSURE[amb]
        assert len(job["lights"]) == 1 and job["lights"][0]["kind"] == "point"
        if amb != "day":
            assert job["sun"] is None
    with pytest.raises(ValueError):
        rb.write_job(scene, _cam(scene), tmp_path / "x", ambience="dusk")


# ---- The panel -----------------------------------------------------------------

@pytest.fixture
def window(monkeypatch, tmp_path):
    from core import extensions
    # Only the bundled plugins: the Render tab must come from THEM.
    from core.paths import app_root
    monkeypatch.setattr(extensions, "plugin_dirs",
                        lambda: [app_root() / "plugins"])
    monkeypatch.setattr(rb, "find_blender",
                        lambda saved=None: rb.BlenderFound(["/x/blender"],
                                                           "/x/blender"))
    from views.main_window import MainWindow
    win = MainWindow()
    yield win
    win._saved_version = win.viewport.scene.version
    win.close()


def _panel(win):
    for dock in win._extension_docks:
        w = dock.widget()
        if type(w).__name__ == "RenderPanel":
            return w
    raise AssertionError("no Render tab in the side tray")


def test_the_extensions_entry_brings_back_the_render_tab(window):
    # The tab is the tool; Extensions only brings it forward, even hidden
    # (Marco: «no aparece en el menú Extensiones»).
    panel = _panel(window)
    dock = next(d for d in window._extension_docks if d.widget() is panel)
    window.set_tray_shown(dock, False)
    entry = next(a for a in window._ext_menu.actions()
                 if "Blender" in a.text())
    entry.trigger()
    assert not dock.isHidden()


def test_a_light_clicked_onto_the_model_is_kept_and_undone(window, tmp_path):
    panel = _panel(window)
    vp = window.viewport
    panel._begin_pick("new", "spot")
    tool = vp.active_tool
    assert tool.uses_snap
    from core.snap import SnapResult
    from tools.base import ToolContext
    tool.on_click(ToolContext(viewport=vp, world=V(3, 4, 5.2),
                              screen=QPointF(0, 0), modifiers=Qt.NoModifier,
                              snap=SnapResult(V(3, 4, 5.2), "endpoint",
                                              (0, 0, 0))))
    lights = panel.app.document_data({})["lights"]
    assert len(lights) == 1
    assert lights[0]["kind"] == "spot"
    assert lights[0]["pos"] == pytest.approx([3, 4, 5.2])
    assert lights[0]["dir"] == [0.0, 0.0, -1.0]
    assert type(vp.active_tool).__name__ != type(tool).__name__  # back to Select
    assert panel._lights.count() == 1
    # Saved with the document, ambience included.
    panel._ambience.setCurrentIndex(panel._ambience.findData("night"))
    panel._on_ambience(0)
    path = tmp_path / "noche.igz"
    from formats import igz
    igz.save_scene(vp.scene, path)
    again = Scene()
    igz.load_into(again, path)
    data = again.plugin_data["render_blender"]
    assert data["ambience"] == "night" and len(data["lights"]) == 1
    # Undo: the ambience, then the light.
    vp.history.undo()
    vp.history.undo()
    assert not (panel.app.document_data({}) or {}).get("lights")


def test_a_point_light_clicked_on_a_face_sits_a_hand_above_it(window):
    panel = _panel(window)
    panel.add_light("point", V(1, 1, 0), on_face=True)
    lt = panel.app.document_data({})["lights"][-1]
    assert lt["pos"][2] == pytest.approx(0.1)


def test_esc_while_placing_cancels(window):
    panel = _panel(window)
    vp = window.viewport
    panel._begin_pick("new", "point")
    tool = vp.active_tool
    assert tool.on_key(vp, Qt.Key_Escape, Qt.NoModifier) is True
    assert vp.active_tool is not tool
    assert not (panel.app.document_data({}) or {}).get("lights")


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("blender") is None,
                    reason="no Blender on this machine")
def test_a_night_render_with_lights(tmp_path):
    scene = _box()
    job = rb.write_job(scene, _cam(scene), tmp_path, engine="eevee",
                       quality=0, width=160, height=90, ambience="night",
                       lights=[{"kind": "spot", "pos": [1, 1, 5]},
                               {"kind": "point", "pos": [3, 1, 1]}])
    found = rb.BlenderFound([shutil.which("blender")], "blender")
    run = subprocess.run(rb.command(found, job), capture_output=True,
                         text=True, env=rb.clean_env(), timeout=600)
    assert run.returncode == 0, run.stdout[-2000:]
    assert "INGETRAZO sky night" in run.stdout
    assert "INGETRAZO lights 2" in run.stdout
    assert (tmp_path / "render.png").is_file()


def test_the_lights_are_drawn_over_the_viewport(window):
    """The overlay paints a bulb at each light (an overlay that raised would
    only be logged and skipped, so draw it here and look at the pixels)."""
    from PySide6.QtGui import QImage, QPainter
    import importlib
    panel = _panel(window)
    vp = window.viewport
    vp.resize(400, 300)
    vp.camera.set_aspect(400, 300)
    vp.camera.target = V(0, 0, 0)
    vp.camera.distance = 10
    panel.add_light("spot", V(0, 0, 1))
    panel._lights.setCurrentRow(0)
    mod = importlib.import_module(type(panel).__module__)
    img = QImage(400, 300, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    mod.draw_lights(panel.app, panel, vp, painter)
    painter.end()
    px = vp._world_to_pixel(V(0, 0, 1))
    assert px is not None
    assert img.pixelColor(int(px[0]), int(px[1])).alpha() > 0


# ---- Temperature, aim, the sun, the image window (Marco's second round) ------

def test_temperature_is_a_range_and_old_names_still_read():
    warm, day, sky = (rb.kelvin_to_rgb(k) for k in (2700, 6500, 10000))
    assert warm[0] == 1.0 and warm[2] < 0.5          # orange
    assert min(day) > 0.95                           # almost white
    assert sky[2] == 1.0 and sky[0] < 0.85           # bluish
    old = rb.clean_lights([{"kind": "point", "pos": [0, 0, 0],
                            "color": "neutral"}])[0]
    assert old["kelvin"] == 4000
    new = rb.clean_lights([{"kind": "point", "pos": [0, 0, 0],
                            "kelvin": 99999}])[0]
    assert new["kelvin"] == rb.MAX_KELVIN            # clamped


@pytest.mark.parametrize("heading, tilt", [(0, 90), (90, 45), (225, 30),
                                           (310, -20)])
def test_a_spot_aims_by_heading_and_tilt(heading, tilt):
    d = rb.aim_from_angles(heading, tilt)
    h, t = rb.angles_from_aim(d)
    assert t == pytest.approx(tilt, abs=0.1)
    if tilt != 90:
        assert h == pytest.approx(heading, abs=0.1)


def test_the_panel_sets_temperature_aim_and_sun(window):
    panel = _panel(window)
    panel.add_light("spot", V(0, 0, 4))
    panel._lights.setCurrentRow(0)
    panel._kelvin_spin.setValue(5000)
    panel._on_light_edited()
    panel._heading.setValue(90)
    panel._tilt.setValue(45)
    panel._on_aim_edited()
    lt = panel.app.document_data({})["lights"][0]
    assert lt["kelvin"] == 5000
    assert lt["dir"] == pytest.approx(rb.aim_from_angles(90, 45))
    panel._sun_scale.setValue(150)
    panel._on_sun_scale()
    assert panel.app.document_data({})["sun_scale"] == 1.5


def test_a_finished_render_opens_its_own_window(window, tmp_path):
    from PySide6.QtGui import QImage
    panel = _panel(window)
    panel._work = tmp_path
    img = QImage(64, 40, QImage.Format_RGB32)
    img.fill(0x336699)
    img.save(str(tmp_path / "render.png"))
    panel._finished(0, None)
    assert panel._viewer is not None and panel._viewer.isVisible()
    first = panel._viewer
    panel._finished(0, None)                         # a second render…
    assert panel._viewer is not first                # …reuses one window
    panel._viewer.close()


def test_the_sun_strength_reaches_the_job(tmp_path):
    scene = _box()
    job = json.loads(rb.write_job(scene, _cam(scene), tmp_path,
                                  sun_scale=0.5).read_text())
    assert job["sun_strength"] == pytest.approx(1.5)


# ---- The tray layout (Marco's third round) --------------------------------------

def test_sections_fold_and_remember_it(window):
    from PySide6.QtCore import QSettings
    panel = _panel(window)
    import importlib
    mod = importlib.import_module(type(panel).__module__)
    sections = {s.header.text(): s for s in panel.findChildren(mod.FoldSection)}
    lights = sections[mod.tr("Lights")]
    lights.header.setChecked(False)
    assert lights.body.isHidden()
    assert str(QSettings().value("render/open_lights")) == "0"
    again = mod._Section("x", "lights")                # a new panel: folded
    assert again.body.isHidden()
    lights.header.setChecked(True)
    assert not lights.body.isHidden()


def test_the_panel_never_scrolls_sideways(window):
    panel = _panel(window)
    from PySide6.QtWidgets import QScrollArea
    area = panel.findChild(QScrollArea)
    assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert area.widget().minimumSizeHint().width() < 260


def test_save_and_open_folder_live_in_the_image_window(window, tmp_path):
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QPushButton
    panel = _panel(window)
    panel._work = tmp_path
    img = QImage(32, 20, QImage.Format_RGB32)
    img.fill(0x808080)
    img.save(str(tmp_path / "render.png"))
    panel._finished(0, None)
    labels = {b.text() for b in panel._viewer.findChildren(QPushButton)}
    import importlib
    mod = importlib.import_module(type(panel).__module__)
    assert {mod.tr("Save image…"), mod.tr("Open folder")} <= labels
    tray = {b.text() for b in panel.findChildren(QPushButton)}
    assert mod.tr("Save image…") not in tray and mod.tr("Open folder") not in tray
    assert "href" in panel._status.text()            # a link back to it
    panel._viewer.close()


def test_change_date_and_time_drops_the_shadows_panel(window, monkeypatch):
    """The button under the day's sun opens the Shadows panel from its
    toolbar button (its tooltip carries a line of help under the title)."""
    from PySide6.QtWidgets import QToolButton
    opened = []
    monkeypatch.setattr(QToolButton, "showMenu",
                        lambda self: opened.append(self.menu()))
    _panel(window)._open_shadows()
    assert len(opened) == 1
    assert window.shadows_panel in [a.defaultWidget() for a in opened[0].actions()
                                    if hasattr(a, "defaultWidget")]
