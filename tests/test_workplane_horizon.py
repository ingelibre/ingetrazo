# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Near-horizon escape hatch for the captured work plane.

A first click on a horizontal face (the ground, a slab) captures its plane and
pins the drawing chain flat — which made drawing a line UPWARD impossible: the
SketchUp gesture is to orbit down to the horizon, where the horizontal plane
is unreadable anyway, and draw up. At near-horizon views a HORIZONTAL captured
plane now yields to the vertical plane through the start point; vertical
captured planes (walls) are untouched.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.viewport import Viewport
    return Viewport(None)


class _Tool:
    def __init__(self):
        self.work_plane = (QVector3D(0, 0, 0), QVector3D(0, 0, 1))
        self.start_point = QVector3D(2, 3, 0)


def test_iso_view_keeps_captured_ground_plane(viewport):
    viewport.active_tool = _Tool()
    viewport.camera.set_view("iso")
    _, n = viewport._current_work_plane()
    assert abs(n.z()) > 0.99                        # still the ground plane


def test_horizon_view_unlocks_vertical_drawing(viewport):
    tool = _Tool()
    viewport.active_tool = tool
    viewport.camera.set_view("front")               # camera at the horizon
    pt, n = viewport._current_work_plane()
    assert abs(n.z()) < 1e-6                        # vertical plane
    assert (pt - tool.start_point).length() < 1e-9  # through the start point


def test_captured_wall_plane_is_untouched_at_horizon(viewport):
    tool = _Tool()
    tool.work_plane = (QVector3D(0, 0, 0), QVector3D(1, 0, 0))  # a wall
    viewport.active_tool = tool
    viewport.camera.set_view("front")
    _, n = viewport._current_work_plane()
    assert abs(n.x()) > 0.99                        # the wall keeps its plane


# ---------------------------------------------------------------------------
# El punto no puede irse al horizonte (Marco, 2026-09-10)
#
# «Cuando quiero elegir el segundo punto como que se atora en la referencia de
# una cara». En la captura, el cursor está sobre una viga a unos 30 m y la
# barra dice «En cara»… con una longitud de 1757,25 m en una plaza de 100 m.
#
# El plano del suelo capturado en el primer clic y la cámara a 16° bajo la
# horizontal —justo por encima del umbral que suelta el plano vertical—: el
# rayo roza el plano y la intersección se dispara. Medido en el propio visor,
# a media pantalla 85 m, veinte píxeles más arriba 405 m, y de ahí a los miles.
# Cerca del horizonte un píxel vale cientos de metros: eso es lo que se siente
# como que «se atora», porque el punto ya no tiene nada que ver con el cursor.
# Y float32 se rinde a ~1,5 km del origen, así que el número ni siquiera era
# recuperable.

import math                                                        # noqa: E402


def _camara_rasante(viewport, pitch_deg=16.0):
    viewport.resize(1600, 1000)
    viewport.camera.target = QVector3D(0, 0, 0)
    viewport.camera.distance = 60.0
    viewport.camera.yaw = math.radians(-90.0)
    viewport.camera.pitch = math.radians(pitch_deg)
    viewport.camera.set_aspect(1600, 1000)


def test_cerca_del_horizonte_el_punto_no_se_dispara(viewport):
    viewport.active_tool = _Tool()                 # suelo capturado + start
    _camara_rasante(viewport)
    # A media pantalla el plano se lee bien y el punto sigue saliendo.
    cerca = viewport._world_from_pixel(800, 700)
    assert cerca is not None and cerca.length() < 60.0
    # Pegado al horizonte ya no: antes devolvía 405 m, y subiendo, miles.
    assert viewport._world_from_pixel(800, 200) is None


def test_una_vista_normal_no_cambia(viewport):
    """El guardia solo puede morder donde el plano es ilegible: en una vista
    de trabajo corriente no aparece por ningún lado de la pantalla."""
    viewport.active_tool = _Tool()
    _camara_rasante(viewport, pitch_deg=25.0)
    for py in range(200, 1000, 50):
        assert viewport._world_from_pixel(800, py) is not None


def test_si_hay_una_cara_bajo_el_cursor_el_punto_cae_en_ella(viewport, monkeypatch):
    """Lo que pasaba en la captura: el cursor SOBRE una viga y el punto a
    1757 m. Si hay una cara ahí, es la cara la que manda."""
    from core.mesh import Mesh
    viewport.active_tool = _Tool()
    _camara_rasante(viewport)
    mesh = Mesh()
    # Un muro de 4 m de alto atravesado por la mirada, a 30 m del objetivo.
    cara = mesh.add_face([QVector3D(-10, 30, 0), QVector3D(10, 30, 0),
                          QVector3D(10, 30, 4), QVector3D(-10, 30, 4)])
    monkeypatch.setattr(viewport, "pick_face_any", lambda x, y: (cara, None))
    punto = viewport._world_from_pixel(800, 200)
    assert punto is not None, "había una cara justo ahí"
    assert abs(punto.y() - 30.0) < 1e-3, f"no cayó en la cara: {punto}"
    assert punto.length() < 60.0
