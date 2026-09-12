# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""La inferencia «Centro» de SketchUp.

«Cuando dibujo un círculo o tengo un cilindro, en la cara circular
SketchUp me marca un punto verde en el centro del círculo cuando me pongo
en la cara; esto me sirve para dibujar, acotar, mover: es una referencia
más» (Marco, 2026-09-11). Al pasar por la arista de una curva o por una
cara que la tiene de borde, el centro queda como referencia (un punto
verde) y el cursor snapea a él.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from core.snap import curve_centers_of_face, fit_circle


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _circle_pts(cx, cy, r, n=24, z=0.0):
    return [V(cx + r * math.cos(2 * math.pi * i / n),
              cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n)]


def test_fit_circle_encuentra_centro_y_radio_y_rechaza_lo_que_no_es_circulo():
    c, r = fit_circle(_circle_pts(3.0, 2.0, 1.5))
    assert (c - V(3, 2)).length() < 1e-6 and abs(r - 1.5) < 1e-6
    arco = _circle_pts(3.0, 2.0, 1.5)[:7]                 # un arco de 90°
    c, r = fit_circle(arco)
    assert (c - V(3, 2)).length() < 1e-6 and abs(r - 1.5) < 1e-6
    assert fit_circle([V(0, 0), V(1, 0), V(2, 0), V(3, 0), V(3, 1)]) is None
    assert fit_circle([V(0, 0), V(1, 0)]) is None


def test_una_cara_circular_da_su_centro_y_una_cara_con_hueco_circular_tambien():
    m = Mesh()
    pts = _circle_pts(3.0, 2.0, 1.5)
    f = m.add_face(pts)
    m.tag_curve(pts, closed=True)                          # una sola curva
    [(c, r, cid)] = curve_centers_of_face(f)
    assert (c - V(3, 2)).length() < 1e-6 and abs(r - 1.5) < 1e-6
    # un cuadrado con un hueco circular: el centro del hueco
    m2 = Mesh()
    hole = _circle_pts(5.0, 5.0, 1.0)
    g = m2.add_face([V(0, 0), V(10, 0), V(10, 10), V(0, 10)], [hole])
    m2.tag_curve(hole, closed=True)
    [(c, r, _)] = curve_centers_of_face(g)
    assert (c - V(5, 5)).length() < 1e-6 and abs(r - 1.0) < 1e-6
    # un cuadrado sin curvas: nada
    assert curve_centers_of_face(m2.add_face([V(20, 0), V(21, 0), V(21, 1), V(20, 1)])) == []


def test_la_cara_de_un_componente_da_el_centro_colocado():
    m = Mesh()
    pts = _circle_pts(0.0, 0.0, 1.0)
    f = m.add_face(pts)
    m.tag_curve(pts, closed=True)
    xf = QMatrix4x4()
    xf.translate(10.0, 20.0, 3.0)
    [(c, r, _)] = curve_centers_of_face(f, xf)
    assert (c - V(10, 20, 3)).length() < 1e-6


class _Visor:
    """Lo justo del visor: una escena, el pick de cara/arista y la
    proyección de planta (x, y) → píxel."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self._hover_edge = None
        self._center_ref = None
        self._pick = (None, None)
        self.snap_threshold_px = 9.0
        self.active_tool = None
        from views.viewport import Viewport
        for m in ("_update_center_ref", "_snap_scene", "_selection_box_points",
                  "_billboard_snap_edges", "_nearby_group_edges",
                  "_gedge_screen", "_pick_index", "_group_chunk",
                  "_placements", "_expand_placements", "_context_placements",
                  "_owner_of", "_rest_is_hidden", "_clip_segment_front"):
            setattr(self, m, getattr(Viewport, m).__get__(self))

    def pick_face_any(self, _x, _y):
        return self._pick

    def _world_to_pixel(self, v):
        return (v.x() * 10.0, v.y() * 10.0)

    _edit_rest_mode = "fade"


def test_pasar_por_la_cara_del_circulo_deja_el_centro_como_referencia_y_snapea():
    from core.snap import compute_snap
    scene = Scene()
    pts = _circle_pts(3.0, 2.0, 1.5)
    f = scene.mesh.add_face(pts)
    scene.mesh.tag_curve(pts, closed=True)
    vp = _Visor(scene)
    vp._pick = (f, None)
    vp._update_center_ref(30.0, 20.0)                     # el cursor sobre la cara
    assert vp._center_ref is not None
    c, r, _ = vp._center_ref
    assert (c - V(3, 2)).length() < 1e-6
    # el centro entra al motor de snap como pseudo-arista «center»
    ss = vp._snap_scene(30.0, 20.0)
    centros = [e for e in ss.edges if getattr(e, "center", False)]
    assert len(centros) == 1
    snap = compute_snap(candidate_world=V(3.05, 2.02), candidate_pixel=(30.5, 20.2),
                        scene=ss, world_to_pixel=vp._world_to_pixel,
                        threshold_px=9.0, is_occluded=lambda p: False)
    assert snap.kind == "center" and (snap.point - V(3, 2)).length() < 1e-6
    # sin nada bajo el cursor la referencia se queda (se va al cambiar de herramienta)
    vp._pick = (None, None)
    vp._update_center_ref(500.0, 500.0)
    assert vp._center_ref is not None


def test_la_arista_de_la_curva_tambien_da_el_centro():
    scene = Scene()
    pts = _circle_pts(3.0, 2.0, 1.5)
    scene.mesh.add_face(pts)
    scene.mesh.tag_curve(pts, closed=True)
    vp = _Visor(scene)
    vp._hover_edge = next(e for e in scene.mesh.edges if e.curve is not None)
    vp._update_center_ref(0.0, 0.0)
    c, r, key = vp._center_ref
    assert (c - V(3, 2)).length() < 1e-6 and key[0] == "loose"


def test_un_circulo_importado_sin_id_de_curva_tambien_da_su_centro():
    """La plaza de Marco viene de un archivo: sus círculos no traen id de
    curva. Un círculo de segmentos SUAVES, y hasta uno pelado (segmentos
    iguales girando un ángulo constante), se leen por su forma."""
    m = Mesh()
    pts = _circle_pts(3.0, 2.0, 1.5, n=24)
    f = m.add_face(pts)
    for e in m.edges:
        e.soft = True
    [(c, r, _)] = curve_centers_of_face(f)
    assert (c - V(3, 2)).length() < 1e-6 and abs(r - 1.5) < 1e-6
    m2 = Mesh()
    g = m2.add_face(_circle_pts(-4.0, 1.0, 0.8, n=16))         # sin flags
    [(c, r, _)] = curve_centers_of_face(g)
    assert (c - V(-4, 1)).length() < 1e-6 and abs(r - 0.8) < 1e-6


def test_una_losa_con_un_cuarto_de_circulo_en_el_borde_da_el_centro_del_arco():
    """Las piezas del pavimento alrededor de la pileta: cada una toca un
    trozo del círculo. El arco, aunque sea parte de un contorno con lados
    rectos, da el centro del círculo entero."""
    m = Mesh()
    arc = [V(5 + 2 * math.cos(a), 5 + 2 * math.sin(a))
           for a in [math.radians(t) for t in range(0, 91, 10)]]     # de (7,5) a (5,7)
    loop = [V(0, 0), V(7, 0)] + arc + [V(0, 7)]
    f = m.add_face(loop)
    [(c, r, _)] = curve_centers_of_face(f)
    assert (c - V(5, 5)).length() < 1e-6 and abs(r - 2.0) < 1e-6
    # un rectángulo pelado no inventa centros
    assert curve_centers_of_face(m.add_face([V(20, 0), V(30, 0), V(30, 4), V(20, 4)])) == []


def test_un_triangulo_no_es_un_circulo_ni_un_trapecio_de_una_revolucion():
    """Tres puntos siempre caen en ALGÚN círculo, y cuatro muchas veces
    (cada trapecio isósceles de una superficie revolucionada es cíclico):
    la pileta daba 14 505 centros. Sin id de curva hacen falta cinco."""
    m = Mesh()
    t = m.add_face([V(0, 0), V(2, 0), V(1, 1.5)])
    assert curve_centers_of_face(t) == []
    trap = m.add_face([V(10, 0), V(14, 0), V(13, 2), V(11, 2)])
    for e in m.edges:
        e.soft = True
    assert curve_centers_of_face(trap) == []
    # con cuatro segmentos suaves seguidos (cinco puntos) sí
    m2 = Mesh()
    arc = [V(5 + 2 * math.cos(a), 5 + 2 * math.sin(a))
           for a in [math.radians(x) for x in (0, 22.5, 45, 67.5, 90)]]
    f = m2.add_face([V(0, 0), V(7, 0)] + arc + [V(0, 7)])
    arc_pts = {(round(p.x(), 6), round(p.y(), 6)) for p in arc}
    for e in m2.edges:
        if all((round(q.x(), 6), round(q.y(), 6)) in arc_pts for q in (e.a, e.b)):
            e.soft = True                                  # solo el arco
    assert len(curve_centers_of_face(f)) == 1
