# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Perpendicular a una arista, EN EL PLANO en el que se dibuja.

«Dibujé un plano inclinado, bien; entonces de una arista del medio quiero
dibujar a la otra arista del medio, pero hay una línea de referencia magenta
que me restringe» (Marco, 2026-09-10).

La inferencia «perpendicular a la arista en la que empezaste» giraba 90° EN
XY: `(-dy, dx, 0)`, siempre horizontal. En el suelo es correcta; en una rampa
no está sobre la rampa, así que cruzar la pendiente de una arista a la otra
quedaba enganchado a una dirección horizontal imposible de satisfacer — y esa
regla gana a los puntos medios y a la arista de destino (está pensada para
ganarlos: es la que traza el tabique perpendicular a un muro).

`cross(normal, arista)` da lo mismo en el suelo —cross((0,0,1),(dx,dy,dz)) es
(-dy, dx, 0), la fórmula vieja clavada— y lo correcto en cualquier otro plano.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.snap import _direction_from_edge


class _Arista:
    def __init__(self, a, b):
        self.a, self.b = a, b


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def test_en_el_suelo_es_exactamente_lo_de_antes():
    """La generalización no puede mover el caso de siempre ni un pelo."""
    for a, b in (((0, 0, 0), (3, 0, 0)), ((1, 2, 0), (4, 7, 0)),
                 ((0, 0, 5), (2, -3, 5)), ((0, 0, 0), (1, 1, 1))):
        arista = _Arista(V(*a), V(*b))
        antes = QVector3D(-(b[1] - a[1]), b[0] - a[0], 0.0).normalized()
        ahora = _direction_from_edge(arista, "perpendicular", V(0, 0, 1))
        assert (ahora - antes).length() < 1e-6, f"{a}->{b}"
        # Y sin plano explícito se sigue comportando como el suelo.
        assert (_direction_from_edge(arista, "perpendicular")
                - antes).length() < 1e-6


def test_en_una_rampa_la_perpendicular_está_en_la_rampa():
    """Una rampa que sube 1 por cada 2 en Y; su arista de abajo va por X."""
    normal = QVector3D(0.0, -1.0, 2.0).normalized()
    arista = _Arista(V(0, 0, 0), V(4, 0, 0))          # horizontal, sobre X
    perp = _direction_from_edge(arista, "perpendicular", normal)
    assert perp is not None
    # Está EN el plano (perpendicular a la normal) y es square a la arista.
    assert abs(QVector3D.dotProduct(perp, normal)) < 1e-6
    assert abs(QVector3D.dotProduct(perp, V(1, 0, 0))) < 1e-6
    # Y sube: es la línea de máxima pendiente, no la horizontal de antes.
    assert abs(perp.z()) > 0.4, f"salió horizontal otra vez: {perp}"


def test_en_un_muro_la_perpendicular_sube():
    """Plano vertical XZ: perpendicular a su arista horizontal es la vertical,
    que la fórmula vieja no podía dar (siempre devolvía algo con z=0)."""
    normal = V(0, 1, 0)
    arista = _Arista(V(0, 0, 0), V(3, 0, 0))
    perp = _direction_from_edge(arista, "perpendicular", normal)
    assert perp is not None and abs(abs(perp.z()) - 1.0) < 1e-6


def test_una_arista_clavada_al_plano_no_tiene_perpendicular():
    """Si la arista es la propia normal no hay dirección que devolver, y hay
    que decirlo con None en vez de un vector nulo que pase por bueno."""
    arista = _Arista(V(0, 0, 0), V(0, 0, 2))
    assert _direction_from_edge(arista, "perpendicular", V(0, 0, 1)) is None


def test_paralela_no_depende_del_plano():
    arista = _Arista(V(0, 0, 0), V(1, 1, 1))
    esperado = V(1, 1, 1).normalized()
    for normal in (None, V(0, 0, 1), V(0, 1, 0)):
        d = _direction_from_edge(arista, "parallel", normal)
        assert (d - esperado).length() < 1e-6


def test_el_angulo_de_la_rampa_se_respeta():
    """La perpendicular de la rampa tiene la pendiente de la rampa: subir 1
    por cada 2 son 26,57°."""
    normal = QVector3D(0.0, -1.0, 2.0).normalized()
    arista = _Arista(V(0, 0, 0), V(4, 0, 0))
    perp = _direction_from_edge(arista, "perpendicular", normal)
    grados = math.degrees(math.asin(abs(perp.z())))
    assert abs(grados - math.degrees(math.atan2(1, 2))) < 1e-4


# ---- de punta a punta, que es como lo vio Marco ----------------------------

#: Una rampa suave, que es donde muerde de verdad: la inferencia
#: perpendicular se dispara dentro de 8°, así que una pendiente por debajo de
#: eso queda atrapada por el bloqueo horizontal. (Con una rampa empinada el
#: bloqueo ni se activa — por eso el bug se ve en rampas de obra, no en cuñas.)
SUBIDA = 0.35        # 5° sobre 4 m


def _rampa():
    """Una rampa de 4×4 que sube 0,35 m hacia +Y, con sus cuatro aristas."""
    from core.scene import Scene
    scene = Scene()
    esquinas = [V(0, 0, 0), V(4, 0, 0), V(4, 4, SUBIDA), V(0, 4, SUBIDA)]
    for i in range(4):
        scene.mesh.add_edge(esquinas[i], esquinas[(i + 1) % 4])
    normal = QVector3D.crossProduct(V(4, 0, 0), V(0, 4, SUBIDA)).normalized()
    return scene, normal


def _snap_en_la_rampa(scene, normal, inicio, cursor):
    from core.snap import compute_snap

    def w2p(p):
        return (p.x() * 100.0, p.y() * 100.0)

    def proyecta(start, direccion):
        d = direccion.normalized()
        return start + d * QVector3D.dotProduct(cursor - start, d)

    return compute_snap(cursor, w2p(cursor), scene, w2p,
                        threshold_px=9.0, edge_threshold_px=14.0,
                        start_point=inicio, project_onto_line=proyecta,
                        work_plane_normal=normal)


def test_cruzar_la_rampa_llega_a_la_arista_de_enfrente():
    """Desde el medio de la arista de abajo hacia la de arriba: el punto tiene
    que aterrizar EN la arista de enfrente, no quedarse a ras de suelo."""
    scene, normal = _rampa()
    cursor = V(2, 3.9, SUBIDA * 3.9 / 4.0)
    r = _snap_en_la_rampa(scene, normal, V(2, 0, 0), cursor)
    assert abs(r.point.z() - SUBIDA) < 1e-6, (
        f"el punto se quedó fuera de la rampa: {r.point}")
    assert abs(r.point.y() - 4.0) < 1e-6
    assert r.kind == "intersection"


def test_sin_el_plano_el_magenta_lo_dejaba_a_ras_de_suelo():
    """La conducta vieja, para que se vea qué cambia: sin plano, el bloqueo
    perpendicular es horizontal y el punto nunca sube por la rampa."""
    scene, _normal = _rampa()
    cursor = V(2, 3.9, SUBIDA * 3.9 / 4.0)
    r = _snap_en_la_rampa(scene, None, V(2, 0, 0), cursor)
    assert r.kind == "reference"          # el magenta que restringía
    assert abs(r.point.z()) < 1e-9        # z = 0: fuera de la rampa
