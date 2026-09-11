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


# ---- fase 2: dentro del grupo, sus hijos se pueden tocar -------------------

class _VP:
    """Lo justo del visor para las rutas de colocaciones y contexto."""

    def __init__(self, scene):
        self.scene = scene
        self._placement_proxies = {}

    _placements = None          # se enchufan las reales abajo


def _visor(scene):
    from views.viewport import Viewport
    vp = _VP(scene)
    for m in ("_placements", "_expand_placements", "_context_placements",
              "_owner_of", "_draws_in_edit_context"):
        setattr(_VP, m, getattr(Viewport, m))
    return vp


def test_dentro_del_grupo_los_hijos_son_lo_seleccionable():
    """En la raíz, un clic en la jardinera selecciona la plaza entera. Dentro
    de la plaza, ese mismo clic tiene que seleccionar LA JARDINERA."""
    scene, padre, h1, h2 = _plaza()
    vp = _visor(scene)
    fuera = {id(vp._owner_of(g)) for g in vp._placements() if g is not padre}
    assert fuera == {id(padre)}, "en la raíz todo apunta al contenedor"

    scene.begin_group_edit(padre)
    dentro = vp._context_placements()
    assert {vp._owner_of(g).name for g in dentro} == {"Jardinera", "Pavimento"}
    assert padre not in dentro, "el contenedor no se selecciona desde dentro"


def test_el_contexto_no_deja_tocar_el_resto_del_modelo():
    scene, padre, _h1, _h2 = _plaza()
    suelto = Group(_cuadrado(Mesh(), 20.0), name="Otro edificio")
    scene.groups.append(suelto)
    vp = _visor(scene)
    assert suelto in vp._context_placements()      # en la raíz, sí
    scene.begin_group_edit(padre)
    assert suelto not in vp._context_placements(), (
        "desde dentro de un grupo no se puede agarrar lo de fuera")


def test_los_hijos_no_se_atenúan_pero_el_resto_sí():
    scene, padre, h1, _h2 = _plaza()
    suelto = Group(_cuadrado(Mesh(), 20.0), name="Otro edificio")
    scene.groups.append(suelto)
    vp = _visor(scene)
    scene.begin_group_edit(padre)
    dentro = vp._context_placements()
    assert not any(vp._draws_in_edit_context(g) for g in dentro), (
        "los hijos del grupo abierto son el sujeto, no el decorado")
    assert vp._draws_in_edit_context(suelto), "lo de fuera se atenúa"


def test_dos_niveles_y_esc_sube_de_uno_en_uno():
    scene, padre, h1, _h2 = _plaza()
    nieto = Group(_cuadrado(Mesh(), 6.0), name="Banca")
    h1.adopt([nieto])
    vp = _visor(scene)
    scene.begin_group_edit(padre)
    scene.begin_group_edit(h1)
    assert scene.edit_group is h1
    assert {vp._owner_of(g).name for g in vp._context_placements()} == {"Banca"}
    scene.end_one_group_edit()
    assert scene.edit_group is padre
    assert {vp._owner_of(g).name for g in vp._context_placements()} == {
        "Jardinera", "Pavimento"}


def test_en_el_segundo_nivel_tambien_se_desvanece_lo_de_fuera():
    """«Cuando hago doble clic en un grupo lo demás se desvanece, está bien
    porque solo me interesa ese grupo; eso igual debe ser para grupos
    anidados» (Marco, 2026-09-11).

    En el primer nivel ya pasaba. En el segundo no: el marcado de contexto
    solo se ponía sobre los hijos de un grupo de PRIMER nivel, así que al
    entrar a un grupo dentro de otro se atenuaba justo lo que estabas
    editando.
    """
    scene, padre, h1, h2 = _plaza()
    nieto_a = Group(_cuadrado(Mesh(), 6.0), name="Banca")
    nieto_b = Group(_cuadrado(Mesh(), 8.0), name="Farola")
    h1.adopt([nieto_a, nieto_b])
    vp = _visor(scene)

    scene.begin_group_edit(padre)
    scene.begin_group_edit(h1)                       # dos niveles adentro
    assert scene.edit_group is h1
    dentro = vp._context_placements()
    assert {vp._owner_of(g).name for g in dentro} == {"Banca", "Farola"}
    assert not any(vp._draws_in_edit_context(g) for g in dentro), (
        "los nietos son el sujeto en el segundo nivel")
    # y el hermano del grupo abierto, ese sí se atenúa
    hermano = next(g for g in vp._placements()
                   if getattr(g, "owner", None) is not None
                   and g.name == "Pavimento")
    assert vp._draws_in_edit_context(hermano)


def test_el_nieto_se_selecciona_solo_en_su_nivel():
    """Desde la raíz, un clic en la banca selecciona la plaza. Dentro de la
    plaza, selecciona la jardinera. Dentro de la jardinera, la banca."""
    scene, padre, h1, _h2 = _plaza()
    nieto = Group(_cuadrado(Mesh(), 6.0), name="Banca")
    h1.adopt([nieto])
    vp = _visor(scene)

    def dueño_de_la_banca():
        entrada = next(g for g in vp._placements() if g.name == "Banca")
        return vp._owner_of(entrada).name

    assert dueño_de_la_banca() == "Plaza"
    scene.begin_group_edit(padre)
    assert dueño_de_la_banca() == "Jardinera"
    scene.begin_group_edit(h1)
    assert dueño_de_la_banca() == "Banca"


def test_las_instancias_tambien_se_atenuan():
    """«Hago doble clic y lo demás no se atenúa» (Marco, 2026-09-11).

    El camino instanciado de la GPU es OTRA llamada de dibujo: el corte de
    atenuado que llevan los búferes por trozos no le dice nada. Mientras
    estabas dentro de un grupo, toda colocación instanciada seguía
    dibujándose a plena luz — y agrupar la plaza convirtió a sus hijos en
    justo eso.
    """
    from views.viewport import Viewport, EDIT_REST_FADE
    scene, padre, h1, h2 = _plaza()
    suelto = Group(_cuadrado(Mesh(), 20.0), name="Otro")
    scene.groups.append(suelto)
    vp = _visor(scene)
    vp._edit_rest_mode = "fade"
    _VP._instanced_batches = Viewport._instanced_batches

    assert vp._instanced_batches([h1, suelto]) == [([h1, suelto], 0.0)], (
        "en la raíz no se atenúa nada")

    scene.begin_group_edit(padre)
    hijos = [g for g in vp._placements() if getattr(g, "context", None) is padre]
    lotes = vp._instanced_batches(hijos + [suelto])
    assert lotes[0] == ([suelto], EDIT_REST_FADE), "lo de fuera, atenuado"
    assert lotes[1] == (hijos, 0.0), "lo de dentro, a plena luz"

    vp._edit_rest_mode = "hide"
    lotes = vp._instanced_batches(hijos + [suelto])
    assert lotes == [(hijos, 0.0)], "en modo ocultar, lo de fuera ni se dibuja"


def test_entrar_a_un_grupo_ANIDADO_no_lo_atenua_a_el():
    """La captura de Marco del 2026-09-11: entró a un grupo que vivía dentro
    de otro y salió lavado él, con el resto del modelo a plena luz.

    Dos agujeros, el mismo origen: el código buscaba al grupo editado POR
    IDENTIDAD en la lista de dibujo, y ahí lo que hay es una proxy suya. Así
    que la proxy se marcaba como decorado —se atenuaba el sujeto— y el corte
    del atenuado no se ponía nunca, con lo que no se atenuaba nada más.
    """
    scene, padre, h1, h2 = _plaza()
    suelto = Group(_cuadrado(Mesh(), 20.0), name="Otro")
    scene.groups.append(suelto)
    vp = _visor(scene)

    scene.begin_group_edit(h1)          # DIRECTO al hijo, sin pasar por el padre
    assert scene.edit_group is h1
    assert h1 not in scene.groups, "vive dentro de la plaza"

    proxy = next(g for g in vp._placements() if g.name == "Jardinera")
    assert not vp._draws_in_edit_context(proxy), (
        "el grupo que se está editando no puede atenuarse a sí mismo")
    assert vp._draws_in_edit_context(suelto), "y lo de fuera sí"
    hermano = next(g for g in vp._placements() if g.name == "Pavimento")
    assert vp._draws_in_edit_context(hermano)
    assert proxy not in vp._context_placements(), (
        "no se selecciona el grupo en el que estás")


def test_el_aviso_dice_en_que_nivel_estas():
    """Sin esto, anidar se lee como un programa roto: haces clic fuera, el
    programa sube UN nivel a un padre que también es contenedor, todo sigue
    atenuado y parece que no pasó nada (Marco, 2026-09-11)."""
    from views.viewport import Viewport
    scene, padre, h1, _h2 = _plaza()
    nieto = Group(_cuadrado(Mesh(), 6.0), name="Banca")
    h1.adopt([nieto])
    vp = _visor(scene)
    _VP.edit_path_text = Viewport.edit_path_text

    assert vp.edit_path_text() == ""
    scene.begin_group_edit(padre)
    assert vp.edit_path_text() == "Plaza"
    scene.begin_group_edit(h1)
    assert vp.edit_path_text() == "Plaza ▸ Jardinera"
    scene.begin_group_edit(nieto)
    assert vp.edit_path_text() == "Plaza ▸ Jardinera ▸ Banca"
    scene.end_one_group_edit()
    assert vp.edit_path_text() == "Plaza ▸ Jardinera"


def test_el_corte_del_atenuado_se_apunta_aunque_el_sujeto_dibuje_por_otra_via():
    """El sujeto puede dibujarse por el camino INSTANCIADO, que no pasa por
    el búfer de trozos. Si la frontera solo se apuntaba para los que sí caen
    en ese búfer, entrar a un grupo instanciado dejaba el corte sin poner —
    y sin corte no se atenúa nada (Marco, 2026-09-11, segundo nivel)."""
    import inspect
    from views.viewport import Viewport
    fuente = inspect.getsource(Viewport._sync_edges)
    i_corte = fuente.index("self._edit_split_f = gface_start")
    i_salto = fuente.index("or self._instanced_eligible(g)):", i_corte - 2000)
    assert i_corte < i_salto, (
        "el corte de caras debe apuntarse ANTES del continue que salta "
        "las colocaciones instanciadas")


def test_las_caras_texturadas_saben_quien_es_el_sujeto():
    """El pase texturado decide el atenuado con su propia bandera. Comparaba
    por identidad contra scene.edit_group, así que con un grupo anidado —que
    en la lista de dibujo es una proxy— marcaba TODAS las caras texturadas
    como decorado: la plaza entera salía lavada, el grupo editado incluido."""
    import inspect
    from views.viewport import Viewport
    fuente = inspect.getsource(Viewport._sync_edges)
    assert "subj = not self._draws_in_edit_context(g)" in fuente
    assert "subj = g is self.scene.edit_group" not in fuente
