# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Empujar una cara que está DENTRO de un grupo o componente.

Dos reglas, y la segunda llegó después de usar la primera en obra:

1. Dentro del componente, el push llega a todas las copias — son la misma
   definición (Marco, 2026-09-04: «hice copias del componente, edito uno y
   los demás no cambian»).
2. **Desde fuera no se empuja.** La herramienta lo hacía —y en una instancia
   abría a tus espaldas una sesión de edición y compartía el resultado a
   todas las copias, cosa que se escribió como «mejor que SketchUp» el
   2026-06-10—. Dibujando de verdad eso se lee como que el modelo cambia
   donde no apuntaste (Marco, 2026-09-10: «cuando un dibujo esté agrupado y
   haga push sin entrar al grupo con doble clic no debería hacer push»). Es
   además lo que dice la propia guía de SketchUp: *the Push/Pull tool cannot
   extrude objects that are a part of a Component or Group… double-click the
   Group or Component to edit it*.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, world_mesh
from core.mesh import Mesh
from core.orient import is_closed, signed_volume
from tools.base import ToolContext
from tools.pushpull import PushPullTool


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _box(mesh, s=1.0):
    pts = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
           V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
             (2, 3, 7, 6), (3, 0, 4, 7)]
    faces = [mesh.add_face([pts[i] for i in q]) for q in quads]
    return faces[1]                                   # the top face


def _ctx(vp, mods=Qt.NoModifier):
    return ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                       modifiers=mods, snap=None)


def _instances(scene):
    proto = Mesh()
    top = _box(proto)
    a, b = Group(proto, name="Pilar"), Group(proto, name="Pilar")
    xb = QMatrix4x4()
    xb.translate(3.0, 0.0, 0.0)
    a.xform, b.xform = QMatrix4x4(), xb
    scene.groups += [a, b]
    scene.version += 1
    return proto, top, a, b


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    return win, win.viewport


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


# ---- 2. desde fuera, no ----------------------------------------------------

def test_una_instancia_cerrada_no_se_empuja():
    win, vp = _window()
    try:
        scene = vp.scene
        proto, top, a, b = _instances(scene)
        pp = PushPullTool()
        vp.active_tool = pp
        pp.hovered_face = top
        pp._hover_group = b
        pp.on_click(_ctx(vp))
        assert not pp.dragging, "arrancó un push dentro de un grupo cerrado"
        assert scene.edit_group is None, "abrió una sesión a espaldas del usuario"
        assert b.mesh is proto and b.xform is not None    # sigue compartida
        assert abs(signed_volume(proto) - 1.0) < 1e-6     # y sin tocar
        assert not vp.history.undo_stack
        dicho = win.statusBar().currentMessage().lower()
        assert "group" in dicho and "double-click" in dicho, (
            "se negó sin decir por qué, que es lo que se lee como roto "
            f"(dijo: {dicho!r})")
    finally:
        _close(win)


def test_el_doble_clic_tampoco():
    """El doble clic repite la última distancia; sobre un grupo cerrado, no."""
    win, vp = _window()
    try:
        scene = vp.scene
        proto, top, a, b = _instances(scene)
        pp = PushPullTool()
        vp.active_tool = pp
        PushPullTool.last_distance = 1.5
        try:
            vp.pick_face_any = lambda x, y: (top, b)
            pp.on_double_click(_ctx(vp))
        finally:
            PushPullTool.last_distance = None
            del vp.pick_face_any
        assert not pp.dragging and scene.edit_group is None
        assert abs(signed_volume(proto) - 1.0) < 1e-6
    finally:
        _close(win)


def test_la_cara_de_un_grupo_cerrado_ni_se_sombrea():
    """Sombrearla sería prometer un empuje que no va a ocurrir."""
    win, vp = _window()
    try:
        scene = vp.scene
        _proto, top, _a, b = _instances(scene)
        pp = PushPullTool()
        vp.active_tool = pp
        vp.pick_face_any = lambda x, y: (top, b)
        try:
            pp.on_hover(_ctx(vp))
        finally:
            del vp.pick_face_any
        assert vp._hover_entity is None, "sombreó una cara que no se puede empujar"
    finally:
        _close(win)


# ---- 1. dentro, sí, y llega a todas las copias -----------------------------

def test_dentro_del_componente_el_push_llega_a_todas_las_copias():
    win, vp = _window()
    try:
        scene = vp.scene
        proto, _top, a, b = _instances(scene)
        vp.begin_group_edit(b)                       # el doble clic del usuario
        assert scene.edit_group is b and b.xform is None
        cara = next(f for f in scene.mesh.faces
                    if all(abs(v.z() - 1.0) < 1e-9 for v in f.vertices))
        assert abs(cara.centroid().x() - 3.5) < 1e-6, "es la copia en el mundo"
        pp = PushPullTool()
        vp.active_tool = pp
        pp.hovered_face = cara
        pp._hover_group = None                       # dentro, la malla ES la copia
        pp.on_click(_ctx(vp))
        assert pp.dragging
        pp.extrusion = 2.0
        pp._commit(vp)
        vp.end_group_edit()                          # Esc

        assert b.mesh is proto and b.xform is not None    # compartida otra vez
        assert a.mesh is proto
        assert is_closed(proto) and abs(signed_volume(proto) - 3.0) < 1e-6
        wa, wb = world_mesh(a), world_mesh(b)
        assert abs(signed_volume(wa) - 3.0) < 1e-6
        assert abs(signed_volume(wb) - 3.0) < 1e-6
        assert abs(max(v.position.x() for v in wb.vertices) - 4.0) < 1e-6
        assert vp.history.undo()
        assert abs(signed_volume(proto) - 1.0) < 1e-6
        assert vp.history.redo()
        assert abs(signed_volume(proto) - 3.0) < 1e-6
    finally:
        _close(win)
