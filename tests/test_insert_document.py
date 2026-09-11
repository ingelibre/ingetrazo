# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Importar otro documento .igz como UN componente.

«Quiero agregar mobiliario que ya había trabajado como pérgolas, arco,
luminaria y demás… son archivos .igz, ¿cómo haría?» (Marco, 2026-09-11).
Como el Import de un .skp en SketchUp: el archivo entero llega como un
componente que se coloca con un clic, con sus grupos, materiales y capas.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group, iter_placements, placement_points
from core.history import History
from core.insert import (component_from_scene, ensure_layers,
                         import_document_as_component, merge_materials)
from core.layers import Layer, assign_layer
from core.materials import Material
from core.mesh import Mesh
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cuadrado(mesh, x0=0.0, lado=1.0, z=0.0):
    mesh.add_face([V(x0, 0, z), V(x0 + lado, 0, z),
                   V(x0 + lado, lado, z), V(x0, lado, z)])
    return mesh


def _pergola():
    """Un documento de mobiliario: geometría suelta + dos grupos, uno de
    ellos instancia, y un muñeco de escala."""
    src = Scene()
    _cuadrado(src.mesh, 0.0, 3.0)                       # el piso, suelto
    poste = Group(_cuadrado(Mesh(), 0.0, 0.2), name="Poste")
    techo = Group(_cuadrado(Mesh(), 0.0, 3.0, z=2.4), name="Techo")
    techo.xform = QMatrix4x4()
    figura = Group(Mesh(), name="Sumari")
    figura.billboard = True
    src.groups += [poste, techo, figura]
    return src, poste, techo


def test_un_documento_entero_es_un_contenedor_con_sus_grupos_de_hijos():
    src, poste, techo = _pergola()
    comp = component_from_scene(src, "pergola")
    assert comp.name == "pergola"
    assert len(comp.mesh.faces) == 1, "lo suelto es la malla propia"
    assert comp.children == [poste, techo], "los grupos, hijos; el muñeco fuera"
    assert comp.xform is not None, "un contenedor siempre es instancia"
    assert techo.xform is not None and poste.xform is None, "cada hijo como era"


def test_un_documento_que_es_un_solo_grupo_entra_como_ese_grupo():
    src = Scene()
    arco = Group(_cuadrado(Mesh()))              # se llama "Group N"
    src.groups.append(arco)
    assert component_from_scene(src, "arco") is arco
    assert arco.name == "arco", "un nombre automático cede al del archivo"
    src2 = Scene()
    con_nombre = Group(_cuadrado(Mesh()), name="Arco de piedra")
    src2.groups.append(con_nombre)
    assert component_from_scene(src2, "arco").name == "Arco de piedra"


def test_solo_geometria_suelta_entra_como_grupo_simple_y_nada_es_nada():
    src = Scene()
    _cuadrado(src.mesh)
    comp = component_from_scene(src, "banca")
    assert comp.mesh is src.mesh and not comp.children and comp.xform is None
    assert component_from_scene(Scene(), "vacio") is None


def test_los_materiales_cruzan_por_nombre_y_un_choque_reestampa():
    src, poste, techo = _pergola()
    poste.mesh.faces[0].attrs["mat"] = "Madera"
    poste.mesh.faces[0].attrs["color"] = [0.5, 0.3, 0.1]
    techo.mesh.faces[0].attrs["mat"] = "Vidrio"
    techo.mesh.faces[0].attrs["back"] = {"color": [0, 0, 1], "mat": "Vidrio"}
    src.materials = {"Madera": Material("Madera", color=(0.5, 0.3, 0.1)),
                     "Vidrio": Material("Vidrio", color=(0.0, 0.0, 1.0),
                                        opacity=0.4)}
    dst = Scene()
    dst.materials = {"Madera": Material("Madera", color=(0.5, 0.3, 0.1)),
                     "Vidrio": Material("Vidrio", color=(0.9, 0.9, 0.9))}
    comp = component_from_scene(src, "pergola")
    renamed = merge_materials(src.materials, dst.materials, comp)
    assert renamed == {"Vidrio": "Vidrio (2)"}, "misma receta = misma; distinta = (2)"
    assert dst.materials["Vidrio (2)"].opacity == 0.4
    assert poste.mesh.faces[0].attrs["mat"] == "Madera"
    assert techo.mesh.faces[0].attrs["mat"] == "Vidrio (2)"
    assert techo.mesh.faces[0].attrs["back"]["mat"] == "Vidrio (2)"


def test_las_capas_que_faltan_se_crean_visibles():
    src, poste, techo = _pergola()
    assign_layer(poste, "Mobiliario")
    assign_layer(techo.mesh.faces[0], "Cubiertas")
    dst = Scene()
    dst.layers.append(Layer("Mobiliario", visible=False))
    comp = component_from_scene(src, "pergola")
    added = ensure_layers(dst, comp)
    assert added == ["Cubiertas"]
    nombres = {ly.name: ly.visible for ly in dst.layers}
    assert nombres["Cubiertas"] is True
    assert nombres["Mobiliario"] is False, "la del documento manda"


def test_el_archivo_guardado_entra_como_componente(tmp_path):
    from formats.igz import load_into, save_scene
    src, _p, _t = _pergola()
    path = tmp_path / "pergola.igz"
    save_scene(src, path)
    temp = Scene()
    load_into(temp, path)
    dst = Scene()
    comp = import_document_as_component(dst, temp, path.stem)
    assert comp is not None and comp.name == "pergola"
    assert [c.name for c in comp.children] == ["Poste", "Techo"]
    assert len(placement_points(comp)) == 12


# ---- colocar un contenedor -------------------------------------------------

class _Visor:
    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)

    def update(self):
        pass

    def flash_status(self, *_a, **_k):
        pass

    def window(self):
        return None


def test_colocar_un_contenedor_compone_su_matriz_y_no_toca_las_mallas():
    from tools.base import ToolContext
    from tools.place_group import PlaceGroupTool
    src, poste, techo = _pergola()
    comp = component_from_scene(src, "pergola")
    antes = {id(g): [QVector3D(v.position) for v in g.mesh.vertices]
             for g, _m in iter_placements(comp)}   # Mesh.vertices son Vertex
    vp = _Visor()
    tool = PlaceGroupTool(comp)
    # el ancla es el centro de la base de TODO el componente (3×3 en z=0)
    assert (tool._anchor - V(1.5, 1.5, 0)).length() < 1e-6
    destino = V(10, 20, 0)
    tool.on_click(ToolContext(viewport=vp, world=destino,
                              screen=QPointF(0, 0), modifiers=Qt.NoModifier,
                              snap=None))
    assert comp in vp.scene.groups and comp in vp.scene.selection
    for g, _m in iter_placements(comp):
        assert [QVector3D(v.position) for v in g.mesh.vertices] == antes[id(g)], (
            "ni la malla propia ni las de los hijos se mueven")
    pts = placement_points(comp)
    lo = pts.min(axis=0)
    assert abs(lo[0] - 8.5) < 1e-6 and abs(lo[1] - 18.5) < 1e-6, (
        "el componente entero se corrió con la matriz")
    assert vp.history.undo() and comp not in vp.scene.groups


def test_el_igz_conserva_los_nombres_de_los_grupos(tmp_path):
    """Pendiente viejo («.igz pierde nombres de grupo»): el archivo nunca
    escribía el nombre, así que una «Pérgola» volvía como «Group 7». Y el
    contador de nombres automáticos salta por encima de los guardados,
    para que un grupo nuevo no repita uno que el documento ya usa."""
    from core.group import Group as _G
    from formats.igz import load_into, save_scene
    src = Scene()
    src.groups.append(Group(_cuadrado(Mesh()), name="Pérgola"))
    auto = Group(_cuadrado(Mesh(), 5.0))          # "Group N"
    src.groups.append(auto)
    path = tmp_path / "nombres.igz"
    save_scene(src, path)
    back = Scene()
    load_into(back, path)
    assert [g.name for g in back.groups] == ["Pérgola", auto.name]
    nuevo = _G(Mesh())
    assert nuevo.name != auto.name
    n_auto = int(auto.name.split()[1])
    assert int(nuevo.name.split()[1]) > n_auto


def test_un_documento_importado_se_sostiene_por_su_origen():
    """El arco tiene zapatas bajo z=0: colgado de su base se saldría del
    suelo; colgado de su ORIGEN (los ejes del componente en SketchUp) las
    zapatas quedan enterradas como las dibujó Marco."""
    from tools.base import ToolContext
    from tools.place_group import PlaceGroupTool
    src = Scene()
    zapata = Group(_cuadrado(Mesh(), 0.0, 1.0, z=-1.3), name="Zapata")
    src.groups += [zapata, Group(_cuadrado(Mesh(), 0.0, 1.0, z=0.0), name="Piso")]
    comp = component_from_scene(src, "arco")
    tool = PlaceGroupTool(comp, anchor=V(0, 0, 0))
    assert (tool._anchor - V(0, 0, 0)).length() < 1e-9
    vp = _Visor()
    tool.on_click(ToolContext(viewport=vp, world=V(10, 10, 0),
                              screen=QPointF(0, 0), modifiers=Qt.NoModifier,
                              snap=None))
    pts = placement_points(comp)
    assert abs(float(pts[:, 2].min()) - (-1.3)) < 1e-6, "la zapata sigue enterrada"
    assert abs(float(pts[:, 0].min()) - 10.0) < 1e-6
