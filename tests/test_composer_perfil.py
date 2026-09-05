# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The terrain-profile sheet item (Marco, 2026-09-03: "perfil de terreno en
láminas"): elevation under a traced path against chainage, with a horizontal
scale, a vertical exaggeration and a grid — sampled from the survey or the
DEM at paint time, saved with the sheet as what to plot and how."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import AddItemCommand, Composicion, PerfilTerreno
from georef.datum import SceneDatum
from georef.geopath import GeoPath
from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow, PerfilItem, paint_perfil_mm

_app = QApplication.instance() or QApplication([])


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class StubSampler:
    """Elevation = f(x, y): a 10 % grade along x, no tiles, no network."""
    def __init__(self, datum):
        self.datum = datum

    def ensure_area(self, *_a):
        pass

    def elevation_at_local(self, p):
        return 2500.0 + 0.10 * p.x() + 0.02 * p.y()


def _composer(with_datum=True, with_path=True):
    host = QWidget()
    host.viewport = _FakeViewport()
    scene = host.viewport.scene
    if with_datum:
        scene.georef = SceneDatum(-12.0464, -77.0428)
    if with_path:
        scene.geo_paths.append(GeoPath([V(0, 0), V(100, 0), V(100, 50)],
                                       name="Eje canal"))
    composer = ComposerWindow(host)
    stub = StubSampler(getattr(scene, "georef", None))
    composer._profile_sampler = lambda datum: stub      # no DEM download in tests
    return composer, host


def _add_profile(composer, **kw):
    pf = PerfilTerreno(x_mm=20, y_mm=20, w_mm=180, h_mm=70, **kw)
    composer.history.execute(AddItemCommand(composer.comp, pf))
    composer._rebuild_canvas()
    item = next(it for it in composer.canvas.items()
                if isinstance(it, PerfilItem) and it.model is pf)
    return pf, item


def _paint(item):
    img = QImage(800, 400, QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    painter.scale(4.0, 4.0)
    item.paint(painter, None, None)
    painter.end()
    return img


def test_the_profile_samples_the_ground_under_the_path():
    composer, host = _composer()
    pf, item = _add_profile(composer)
    profile, name, message = composer.profile_for(pf)
    assert name == "Eje canal" and message is None
    assert profile.length == 150.0                   # 100 m east, then 50 m north
    first, last = profile.samples[0], profile.samples[-1]
    assert first.elevation == 2500.0
    assert abs(last.elevation - (2500.0 + 10.0 + 1.0)) < 1e-6
    assert profile.complete
    img = _paint(item)
    # something got drawn inside the box (the ground line and its tint)
    assert any(img.pixelColor(x, 200).green() != 255 for x in range(80, 700, 20))


def test_a_profile_without_a_base_map_says_so_instead_of_crashing():
    composer, host = _composer(with_datum=False)
    pf, item = _add_profile(composer)
    profile, name, message = composer.profile_for(pf)
    assert profile is None and "base map" in message
    _paint(item)                                      # draws the message, no error
    composer2, host2 = _composer(with_path=False)
    pf2, item2 = _add_profile(composer2)
    profile, name, message = composer2.profile_for(pf2)
    assert profile is None and "Path tool" in message
    _paint(item2)


def test_the_profile_travels_with_the_sheet():
    comp = Composicion()
    comp.perfiles.append(PerfilTerreno(x_mm=30, y_mm=40, w_mm=150, h_mm=60,
                                       path_index=2, scale_n=1000.0, exag=10.0,
                                       grid_h_m=20.0, title="Perfil eje"))
    d = comp.to_dict()
    assert d["perfiles"][0]["scale_n"] == 1000.0
    back = Composicion.from_dict(d)
    assert len(back.perfiles) == 1
    assert back.perfiles[0].path_index == 2 and back.perfiles[0].exag == 10.0
    assert back.perfiles[0].title == "Perfil eje"
    assert back.perfiles[0] in back.all_items()


def test_the_panel_edits_the_selected_profile_and_keeps_it_selected():
    composer, host = _composer()
    pf, item = _add_profile(composer)
    item.setSelected(True)
    composer.on_selection_changed()
    assert composer.props.currentIndex() == 12
    assert "Eje canal" in composer.pf_path.currentText()
    composer.pf_exag.setValue(5.0)                    # a panel edit
    assert pf.exag == 5.0
    composer.pf_scale.setCurrentText("1:500")
    assert pf.scale_n == 500.0
    composer._rebuild_canvas()                        # what the auto-render does
    assert composer._selected_item().model is pf


def test_scales_and_exaggeration_state_themselves_in_the_caption():
    """At 1:1000 horizontal and ×10, a 150 m path spans 150 mm and 11 m of
    relief spans 110 mm — more than the 70 mm box, so the vertical scale
    is fitted and the caption says which pair got drawn."""
    composer, host = _composer()
    pf, item = _add_profile(composer, scale_n=1000.0, exag=10.0)
    profile, name, message = composer.profile_for(pf)
    drawn = []

    class Spy(QPainter):
        pass
    img = QImage(400, 200, QImage.Format_ARGB32)
    painter = QPainter(img)
    import views.composer as vc
    original = vc._draw_text_mm

    def spy(p, rect, text, *a, **k):
        drawn.append(text)
        return original(p, rect, text, *a, **k)
    vc._draw_text_mm = spy
    try:
        paint_perfil_mm(painter, pf, profile, name, message)
    finally:
        vc._draw_text_mm = original
        painter.end()
    caption = next(t for t in drawn if "1:" in t and "×" in t)
    assert "H 1:1000" in caption
    assert any(t.startswith("0+000") for t in drawn)        # chainage labels
    assert any(t.startswith("2500") for t in drawn)         # elevation labels
