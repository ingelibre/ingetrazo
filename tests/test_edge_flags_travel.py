# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Lo que lleva una arista viaja con ella cuando la malla se reconstruye.

«Oculté una arista, funciona bien, pero agrupo ese dibujo, creo un grupo, y la
arista vuelve a aparecer» (Marco, 2026-09-10).

`Edge` lleva cuatro cosas además de sus dos extremos: `soft`, `curve`, `layer`
y `hidden`. Cada comando que reconstruye una malla a partir de coordenadas
sueltas tiene que llevárselas, y olvidarse de una no se nota hasta que alguien
la usa. `soft` ya se había olvidado una vez (agrupar un cilindro enseñaba todas
las costuras); `hidden` llegó a `Edge` después y solo algunas copias se
enteraron. Tres comandos se lo dejaban: crear grupo, deshacer grupo y
reconstruir caras. Ahora las cuatro banderas viajan en una tupla, de un solo
sitio (`core.mesh.edge_flags`), así que la próxima que se añada no se puede
olvidar.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import (ExplodeGroupCommand, HideEdgesCommand, History,
                          MakeGroupCommand, RebuildPlanarFacesCommand)
from core.mesh import EDGE_FLAG_NAMES, edge_flags, edge_is_plain
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cuadrado_con_una_oculta():
    """Un cuadrado con cara, con la arista de abajo oculta y etiquetada."""
    scene = Scene()
    hist = History(scene)
    sq = [V(0, 0), V(2, 0), V(2, 2), V(0, 2)]
    hist.execute(build_add_edges(
        scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)], detect_faces=True))
    abajo = next(e for e in scene.mesh.edges
                 if abs(e.a.y()) < 1e-9 and abs(e.b.y()) < 1e-9)
    hist.execute(HideEdgesCommand([abajo], hidden=True))
    abajo.layer = "Ejes"
    return scene, hist


def _oculta_de(mesh):
    return [e for e in mesh.edges if e.hidden]


def test_agrupar_no_resucita_una_arista_oculta():
    scene, hist = _cuadrado_con_una_oculta()
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    grupo = scene.groups[-1]
    ocultas = _oculta_de(grupo.mesh)
    assert len(ocultas) == 1, "la arista oculta volvió a aparecer al agrupar"
    assert ocultas[0].layer == "Ejes", "y su capa también viajaba con ella"


def test_deshacer_el_grupo_la_devuelve_oculta():
    scene, hist = _cuadrado_con_una_oculta()
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    hist.execute(ExplodeGroupCommand(scene.groups[-1]))
    ocultas = _oculta_de(scene.mesh)
    assert len(ocultas) == 1, "al explotar el grupo la arista reapareció"
    assert ocultas[0].layer == "Ejes"


def test_reconstruir_caras_conserva_la_oculta():
    scene, hist = _cuadrado_con_una_oculta()
    hist.execute(RebuildPlanarFacesCommand())
    assert len(_oculta_de(scene.mesh)) >= 1, "el rebuild la dejó visible"


def test_undo_de_agrupar_deja_todo_como_estaba():
    scene, hist = _cuadrado_con_una_oculta()
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    assert hist.undo() is True
    assert len(_oculta_de(scene.mesh)) == 1


def test_las_banderas_son_una_sola_lista():
    """El contrato que hace que esto no vuelva a pasar: un solo sitio dice
    QUÉ lleva una arista, y los comandos lo preguntan."""
    scene, _hist = _cuadrado_con_una_oculta()
    for nombre in ("soft", "curve", "layer", "hidden"):
        assert nombre in EDGE_FLAG_NAMES
    e = next(iter(_oculta_de(scene.mesh)))
    assert not edge_is_plain(e)
    assert len(edge_flags(e)) == len(EDGE_FLAG_NAMES)
