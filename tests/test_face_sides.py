# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Una cara tiene dos lados, y se pinta el que se clica.

«Si a una cara le aplico un color o textura, también se aplica a su revés,
lo cual no debería; solo en el caso de una malla o cristal o agua» (Marco,
2026-09-11). Es la regla de SketchUp: el cubo pinta el lado bajo el cursor,
el otro conserva el color de reverso del estilo, y un material translúcido
se ve igual por los dos lados. ``attrs["back"]``: ausente = reverso por
defecto, ``True`` = cara de dos lados (el reverso copia al frente), dict =
material propio del reverso.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.history import History, SetFaceBackCommand              # noqa: E402
from core.materials import Material, back_is_default, is_translucent  # noqa: E402
from core.scene import Scene                                      # noqa: E402
from tools.base import ToolContext                                # noqa: E402
from tools.paint import PaintTool, clicked_back_side              # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _quad(mesh):
    return mesh.add_face([V(0, 0), V(4, 0), V(4, 4), V(0, 4)])   # normal +Z


class _Visor:
    """Lo justo de un visor para el cubo de pintura: escena, historial, un
    pick que devuelve la cara elegida y un rayo que la mira desde ARRIBA
    (el frente, normal +Z) o desde ABAJO (el revés)."""

    def __init__(self, desde_abajo=False):
        self.scene = Scene()
        self.history = History(self.scene)
        self._pick = None
        self._desde_abajo = desde_abajo

    def pick_face_any(self, _x, _y):
        return self._pick, None

    def _pixel_to_ray(self, _x, _y):
        if self._desde_abajo:
            return V(2, 2, -10), V(0, 0, 1)      # mirando hacia +Z: ve el revés
        return V(2, 2, 10), V(0, 0, -1)          # mirando hacia −Z: ve el frente

    def update(self):
        pass


def _click(vp, face, modifiers=Qt.NoModifier):
    vp._pick = face
    PaintTool().on_click(ToolContext(viewport=vp, world=QVector3D(),
                                     screen=QPointF(0, 0),
                                     modifiers=modifiers, snap=None))


@pytest.fixture(autouse=True)
def _estado_limpio():
    yield
    PaintTool.current_material = None
    PaintTool.current_texture = None
    PaintTool.current_texture_plane = None
    PaintTool.current_opacity = None
    PaintTool.current_color = (0.80, 0.45, 0.30)


# ---- la regla ---------------------------------------------------------------

def test_el_reves_es_el_por_defecto_salvo_que_tenga_algo_o_el_frente_sea_translucido(tmp_path):
    assert back_is_default(None)
    assert back_is_default({"color": [1, 0, 0]})
    assert not back_is_default({"color": [1, 0, 0], "back": True})
    assert not back_is_default({"color": [1, 0, 0], "back": {"color": [0, 0, 1]}})
    # cristal / agua: opacidad < 1
    assert is_translucent({"color": [0, 0, 1], "opacity": 0.4})
    assert not back_is_default({"color": [0, 0, 1], "opacity": 0.4})
    # malla / hoja: textura con píxeles transparentes de verdad
    calada = QImage(8, 8, QImage.Format_RGBA8888)
    calada.fill(0x00000000)
    calada.setPixelColor(0, 0, Qt.red)
    calada.save(str(tmp_path / "malla.png"), "PNG")
    opaca = QImage(8, 8, QImage.Format_RGB32)
    opaca.fill(0xFF336699)
    opaca.save(str(tmp_path / "muro.png"), "PNG")
    assert not back_is_default({"texture": {"path": str(tmp_path / "malla.png")}})
    assert back_is_default({"texture": {"path": str(tmp_path / "muro.png")}})


def test_el_lado_clicado_sale_del_rayo_contra_la_normal():
    vp = _Visor()
    f = _quad(vp.scene.mesh)
    assert clicked_back_side(vp, f, None, 0, 0) is False
    assert clicked_back_side(_Visor(desde_abajo=True), f, None, 0, 0) is True


# ---- el cubo -----------------------------------------------------------------

def test_pintar_el_frente_no_toca_el_reves():
    vp = _Visor()
    f = _quad(vp.scene.mesh)
    PaintTool.current_color = (1.0, 0.0, 0.0)
    _click(vp, f)
    assert f.attrs["color"] == [1.0, 0.0, 0.0]
    assert "back" not in f.attrs, "el revés queda con el color por defecto"
    assert back_is_default(f.attrs)


def test_pintar_el_reves_le_da_material_propio_y_deja_el_frente():
    vp = _Visor(desde_abajo=True)
    f = _quad(vp.scene.mesh)
    f.attrs["color"] = [1.0, 0.0, 0.0]
    PaintTool.current_color = (0.0, 0.0, 1.0)
    PaintTool.current_material = Material(name="Azul", color=(0.0, 0.0, 1.0))
    _click(vp, f)
    assert f.attrs["color"] == [1.0, 0.0, 0.0], "el frente no cambia"
    assert f.attrs["back"] == {"color": [0.0, 0.0, 1.0], "mat": "Azul"}
    assert "mat" not in f.attrs, "la identidad es del lado pintado"
    assert "Azul" in vp.scene.materials, "el material se registra igual"
    assert vp.history.undo()
    assert "back" not in f.attrs
    assert "Azul" not in vp.scene.materials


def test_pintar_el_reves_con_textura_posicionada_respeta_el_plano():
    vp = _Visor(desde_abajo=True)
    f = _quad(vp.scene.mesh)
    otra = vp.scene.mesh.add_face([V(0, 0), V(4, 0), V(4, 0, 3), V(0, 0, 3)])
    from tools.paint import _face_plane
    PaintTool.current_texture = {"path": "x.png", "sw": 1, "sh": 1,
                                 "uvw": [1, 0, 0, 0, 0, 1, 0, 0]}
    PaintTool.current_texture_plane = _face_plane(f)
    _click(vp, f)
    assert f.attrs["back"]["texture"].get("uvw"), "en su plano conserva el mapa"
    vp.scene.selection.clear()
    vp._desde_abajo = False          # la pared se mira de frente
    vp._pick = otra
    # otro plano: el mapa no viaja
    PaintTool().on_click(ToolContext(viewport=vp, world=QVector3D(),
                                     screen=QPointF(0, 0),
                                     modifiers=Qt.NoModifier, snap=None))
    assert "uvw" not in otra.attrs["texture"]


def test_el_cuentagotas_toma_el_lado_bajo_el_cursor():
    f_vp = _Visor()
    f = _quad(f_vp.scene.mesh)
    f.attrs["color"] = [1.0, 0.0, 0.0]
    f.attrs["back"] = {"color": [0.0, 0.0, 1.0]}
    _click(f_vp, f, Qt.AltModifier)
    assert PaintTool.current_color == (1.0, 0.0, 0.0)
    b_vp = _Visor(desde_abajo=True)
    b_vp.scene = f_vp.scene
    _click(b_vp, f, Qt.AltModifier)
    assert PaintTool.current_color == (0.0, 0.0, 1.0)
    # un revés por defecto muestrea la pintura por defecto
    f.attrs.pop("back")
    _click(b_vp, f, Qt.AltModifier)
    from tools.paint import DEFAULT_FACE_COLOR
    assert PaintTool.current_color == DEFAULT_FACE_COLOR
    # una cara de dos lados muestrea su frente desde atrás
    f.attrs["back"] = True
    _click(b_vp, f, Qt.AltModifier)
    assert PaintTool.current_color == (1.0, 0.0, 0.0)


def test_set_face_back_command_deshace_a_lo_que_habia():
    scene = Scene()
    hist = History(scene)
    f = _quad(scene.mesh)
    f.attrs["back"] = True
    hist.execute(SetFaceBackCommand([f], {"color": [0.0, 1.0, 0.0]}))
    assert f.attrs["back"] == {"color": [0.0, 1.0, 0.0]}
    hist.execute(SetFaceBackCommand([f], None))
    assert "back" not in f.attrs
    assert hist.undo() and f.attrs["back"] == {"color": [0.0, 1.0, 0.0]}
    assert hist.undo() and f.attrs["back"] is True


# ---- el documento ----------------------------------------------------------

def test_igz_guarda_la_cara_de_dos_lados_como_true(tmp_path):
    from formats.igz import load_into, save_scene
    scene = Scene()
    dos = _quad(scene.mesh)
    dos.attrs["color"] = [1.0, 0.0, 0.0]
    dos.attrs["back"] = True
    propio = scene.mesh.add_face([V(6, 0), V(8, 0), V(8, 2), V(6, 2)])
    propio.attrs["color"] = [1.0, 0.0, 0.0]
    propio.attrs["back"] = {"color": [0.0, 0.0, 1.0]}
    solo = scene.mesh.add_face([V(10, 0), V(12, 0), V(12, 2), V(10, 2)])
    solo.attrs["color"] = [1.0, 0.0, 0.0]
    path = tmp_path / "lados.igz"
    save_scene(scene, path)
    back = Scene()
    load_into(back, path)
    por_x = {round(min(v.x() for v in f.vertices)): f for f in back.mesh.faces}
    assert por_x[0].attrs["back"] is True
    assert por_x[6].attrs["back"] == {"color": [0.0, 0.0, 1.0]}
    assert "back" not in por_x[10].attrs


# ---- el dibujo ---------------------------------------------------------------

def test_el_trozo_lleva_los_triangulos_del_reves_por_defecto():
    """El tinte del reverso se dibuja con un pase propio (culling frontal)
    a partir de ``chunk["dback"]``: solo las caras con reverso por defecto y
    frente opaco entran."""
    from tests.test_pick_index import _VP, _bind
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    m = Mesh()
    defecto = m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    defecto.attrs["color"] = [1, 0, 0]
    dos = m.add_face([V(2, 0), V(3, 0), V(3, 1), V(2, 1)])
    dos.attrs["color"] = [1, 0, 0]
    dos.attrs["back"] = True
    vidrio = m.add_face([V(4, 0), V(5, 0), V(5, 1), V(4, 1)])
    vidrio.attrs["color"] = [0, 0, 1]
    vidrio.attrs["opacity"] = 0.3
    sin_pintar = m.add_face([V(6, 0), V(7, 0), V(7, 1), V(6, 1)])
    g = Group(m)
    scene.groups.append(g)
    vp = _bind(_VP(scene))
    chunk = vp._group_chunk(g)
    import numpy as np
    tris = np.frombuffer(chunk["dback"], dtype=np.float32).reshape(-1, 3, 3)
    xs = sorted({int(t[:, 0].min()) for t in tris})
    assert xs == [0, 6], "solo la pintada por delante y la sin pintar"
    assert len(tris) == 4                      # dos triángulos por cara


def test_la_huella_del_trozo_ve_el_reves_la_opacidad_y_el_mapa():
    """Lo primero que probó Marco: pintar el REVÉS de una cara dentro de un
    grupo, y no cambiaba nada en pantalla. La huella de sesión del trozo
    solo miraba color, textura y capa, así que el trozo viejo se daba por
    bueno. El reverso, la translucidez y un mapa posicionado también son
    lo que el trozo hornea."""
    from core.mesh import Mesh
    from views.viewport import Viewport
    m = Mesh()
    f = _quad(m)
    f.attrs["texture"] = {"path": "muro.png", "sw": 1, "sh": 1}
    fp0 = Viewport._mesh_fingerprint(m)
    f.attrs["back"] = {"texture": {"path": "piedra.jpg", "sw": 1, "sh": 1}}
    fp_back = Viewport._mesh_fingerprint(m)
    assert fp_back != fp0
    f.attrs["opacity"] = 0.4
    fp_op = Viewport._mesh_fingerprint(m)
    assert fp_op != fp_back
    f.attrs["texture"]["uvw"] = [1, 0, 0, 0, 0, 1, 0, 0]
    assert Viewport._mesh_fingerprint(m) != fp_op


def test_los_trozos_se_distinguen_por_numero_de_construccion_no_por_id():
    """Una cara pintada dentro de un componente volvía sin pintar un nivel
    arriba: el trozo reconstruido del prototipo podía caer en la misma
    dirección de memoria que el viejo (mismo ``id``, misma ``rev`` 0), y la
    instancia y la entrada GL derivadas del viejo se daban por vigentes.
    Cada construcción lleva ahora su número."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh
    from tests.test_pick_index import _VP, _bind
    scene = Scene()
    proto = Mesh()
    f = _quad(proto)
    inst = Group(proto, name="Arco")
    inst.xform = QMatrix4x4()
    scene.groups.append(inst)
    vp = _bind(_VP(scene))
    from views.viewport import Viewport
    for name in ("_proto_base_chunk", "_normal_of", "_tris_of", "_area_of",
                 "_newell_of"):
        setattr(vp, name, getattr(Viewport, name).__get__(vp))
    base0 = vp._proto_base_chunk(proto)
    chunk0 = vp._group_chunk(inst)
    assert chunk0["ikey"][0] == base0["uid"]
    f.attrs["texture"] = {"path": "sillar.jpg", "sw": 0.4, "sh": 0.4}
    proto._chunk_dirty = True
    proto._attrs_dirty = True
    scene.version += 1
    base1 = vp._proto_base_chunk(proto)
    assert base1["uid"] != base0["uid"], "otra construcción, otro número"
    chunk1 = vp._group_chunk(inst)
    assert chunk1["ikey"][0] == base1["uid"]
    assert any(k[0] == "sillar.jpg" for k in chunk1["by_texture"]), (
        "la instancia sigue al prototipo repintado")
