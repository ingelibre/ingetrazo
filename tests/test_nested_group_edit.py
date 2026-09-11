# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Entrar a un grupo que tiene grupos dentro, sin fundirlos.

«Hago doble clic en ese grupo grande y quiero entrar en el grupo de la
jardinera, pero parece que todo está combinado» (Marco, 2026-09-11). Lo
estaba: `begin_group_edit` llamaba a `materialize()` y los nueve grupos de
su plaza se volvían una sola malla de 17 577 caras. Además de perder la
estructura se pierde rendimiento — nueve chunks independientes pasan a ser
uno solo y el instanciado desaparece.

Esta es la fase 1: la PILA de contextos. Entrar a un hijo del grupo abierto
empuja un nivel; `end_one_group_edit` saca uno (el Esc de SketchUp) y
`end_group_edit` cierra todo, que es lo que el resto de la aplicación da por
hecho antes de guardar o exportar.
"""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cuadrado(mesh, x0=0.0, lado=1.0):
    mesh.add_face([V(x0, 0), V(x0 + lado, 0),
                   V(x0 + lado, lado), V(x0, lado)])
    return mesh


def _plaza():
    """Un contenedor con dos hijos, como la plaza de Marco en pequeño."""
    scene = Scene()
    hijo1 = Group(_cuadrado(Mesh(), 0.0), name="Jardinera")
    hijo2 = Group(_cuadrado(Mesh(), 3.0), name="Pavimento")
    padre = Group(Mesh(), name="Plaza")
    padre.adopt([hijo1, hijo2])
    scene.groups.append(padre)
    return scene, padre, hijo1, hijo2


def test_entrar_no_funde_los_hijos():
    scene, padre, h1, h2 = _plaza()
    scene.begin_group_edit(padre)
    assert scene.edit_group is padre
    assert len(padre.children) == 2, "los hijos se hornearon al entrar"
    assert padre.children[0] is h1 and padre.children[1] is h2
    assert len(h1.mesh.faces) == 1 and len(h2.mesh.faces) == 1
    assert len(padre.mesh.faces) == 0, "la malla propia del contenedor está vacía"
    scene.end_group_edit()
    assert len(padre.children) == 2


def test_entrar_a_un_hijo_empuja_un_nivel():
    scene, padre, h1, _h2 = _plaza()
    scene.begin_group_edit(padre)
    scene.begin_group_edit(h1)                  # doble clic dentro
    assert scene.edit_group is h1
    assert scene.mesh is h1.mesh
    assert len(scene._edit_stack) == 2
    scene.end_one_group_edit()                  # Esc
    assert scene.edit_group is padre, "Esc debe dejarte DENTRO del padre"
    assert scene.mesh is padre.mesh
    scene.end_one_group_edit()
    assert scene.edit_group is None


def test_end_group_edit_cierra_todos_los_niveles():
    """El contrato viejo: la aplicación entera llama a esto antes de guardar
    o exportar y da por hecho que al volver no queda nada abierto."""
    scene, padre, h1, _h2 = _plaza()
    suelta = scene.mesh
    scene.begin_group_edit(padre)
    scene.begin_group_edit(h1)
    scene.end_group_edit()
    assert scene.edit_group is None
    assert scene._edit_stack == []
    assert scene.mesh is suelta, "no volvió a la malla suelta"
    assert scene.loose_mesh is suelta


def test_entrar_a_otro_grupo_cierra_lo_abierto():
    scene, padre, h1, _h2 = _plaza()
    otro = Group(_cuadrado(Mesh(), 9.0), name="Suelto")
    scene.groups.append(otro)
    scene.begin_group_edit(padre)
    scene.begin_group_edit(h1)
    scene.begin_group_edit(otro)                # no es hijo del abierto
    assert scene.edit_group is otro
    assert len(scene._edit_stack) == 1


def test_un_contenedor_movido_entra_sin_moverse():
    """Mover un contenedor compone en su matriz. Al entrar, esa matriz baja a
    los hijos: dentro se dibuja en coordenadas del mundo y nada se mueve."""
    scene, padre, h1, h2 = _plaza()
    t = QMatrix4x4()
    t.translate(10.0, 5.0, 0.0)
    padre.xform = t
    antes = sorted(round(c, 6)
                   for g in (h1, h2)
                   for v in g.mesh.vertices
                   for c in (t.map(v.position)).toTuple())
    scene.begin_group_edit(padre)
    assert padre.xform == QMatrix4x4(), "el contenedor debe quedar en identidad"
    despues = sorted(round(c, 6)
                     for g in (h1, h2)
                     for v in g.mesh.vertices
                     for c in ((g.xform.map(v.position) if g.xform is not None
                                else v.position)).toTuple())
    assert antes == despues, "la geometría se movió al entrar"


def test_un_grupo_normal_sigue_funcionando_igual():
    """Sin hijos, todo como siempre: la malla de la escena pasa a ser la suya
    y al salir vuelve la suelta."""
    scene = Scene()
    g = Group(_cuadrado(Mesh()), name="Caja")
    scene.groups.append(g)
    suelta = scene.mesh
    scene.begin_group_edit(g)
    assert scene.mesh is g.mesh and scene.edit_group is g
    scene.end_group_edit()
    assert scene.mesh is suelta and scene.edit_group is None
