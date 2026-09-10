# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rotated Rectangle draws in a PLANE, which is the point of the tool.

Marco, 2026-09-10, after reading how SketchUp's works: «sospecho que no es
igual». It was not. `work_plane` was declared, reset and read — and never
assigned — so `_perp` always fell back to world +Z:

* on a wall the width shot off the wall horizontally,
* a vertical base edge made cross(Z, Z) zero, and the tool then did nothing
  at all without a word,
* and the class was `RotatedRectangleTool(Tool)` while Rectangle, Circle,
  Polygon and every arc are `(PlaneLock, Tool)` — the arrow keys never even
  reached it.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.mesh import Mesh
from tools.base import PLANE_LOCK_KEYS, PlaneLock, ToolContext
from tools.rotated_rectangle import RotatedRectangleTool

WALL_N = QVector3D(0.0, 1.0, 0.0)      # a wall in the XZ plane


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _VP:
    """Just enough viewport: a face under the cursor, and a loud status bar."""

    def __init__(self, face=None, scene=None):
        self.face = face
        self.said = []
        self.scene = scene
        self.history = None

    def pick_face_any(self, x, y):
        return (self.face, None)

    def flash_status(self, text, msec=2500):
        self.said.append(text)

    def update(self):
        pass


def _ctx(vp, world):
    return ToolContext(viewport=vp, world=world, screen=QPointF(0.0, 0.0),
                       modifiers=Qt.NoModifier, snap=None)


def _wall_face():
    mesh = Mesh()
    return mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 0, 3), V(0, 0, 3)])


def _off_plane(corners, origin, normal):
    n = normal.normalized()
    return [round(QVector3D.dotProduct(p - origin, n), 6) for p in corners]


def test_it_is_a_plane_locking_tool_like_every_other_planar_one():
    assert issubclass(RotatedRectangleTool, PlaneLock)
    assert hasattr(RotatedRectangleTool, "on_key")


def test_the_arrow_keys_reach_it():
    tool = RotatedRectangleTool()
    vp = _VP()
    key = next(k for k, axis in PLANE_LOCK_KEYS.items() if axis == "y")
    assert tool.on_key(vp, key, None) is True
    assert tool.plane_lock == "y"
    tool._reset()
    assert tool.plane_lock is None, "the lock must not outlive the shape"


def test_the_first_click_captures_the_face_it_landed_on():
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())
    tool.on_click(_ctx(vp, V(1, 0, 1)))
    assert tool.work_plane is not None, "the face under the click was ignored"
    _point, normal = tool.work_plane
    assert abs(abs(normal.normalized().y()) - 1.0) < 1e-6


def test_a_rectangle_on_a_wall_stays_on_the_wall():
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(3, 0, 0)))
    assert tool.base_point is not None
    corners = tool._corners(1.0)
    assert corners
    assert _off_plane(corners, V(0, 0, 0), WALL_N) == [0.0, 0.0, 0.0, 0.0]


def test_a_vertical_base_edge_works_on_a_wall():
    """cross(Z, Z) was zero and the tool went quiet; in the wall's own plane
    a vertical edge is perfectly ordinary."""
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(0, 0, 3)))
    assert tool.base_point is not None
    assert tool._corners(1.0)
    assert not vp.said


def test_an_edge_perpendicular_to_the_plane_is_refused_OUT_LOUD():
    tool = RotatedRectangleTool()
    vp = _VP(face=None)                       # no face: the ground plane
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    assert tool.work_plane is None
    tool.on_click(_ctx(vp, V(0, 0, 3)))       # straight up, off the ground
    assert tool.base_point is None, "it accepted an impossible base edge"
    assert vp.said, "it refused without a word"


def test_the_ground_case_is_unchanged():
    tool = RotatedRectangleTool()
    vp = _VP(face=None)
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    tool.on_click(_ctx(vp, V(3, 0, 0)))
    corners = tool._corners(2.0)
    assert corners == [V(0, 0, 0), V(3, 0, 0), V(3, 2, 0), V(0, 2, 0)]


def test_an_arrow_lock_beats_the_face_under_the_cursor():
    tool = RotatedRectangleTool()
    vp = _VP(face=_wall_face())               # a wall says XZ...
    key = next(k for k, axis in PLANE_LOCK_KEYS.items() if axis == "z")
    tool.on_key(vp, key, None)                # ...but the user asked for XY
    tool.on_click(_ctx(vp, V(0, 0, 0)))
    _point, normal = tool.work_plane
    assert abs(abs(normal.normalized().z()) - 1.0) < 1e-6


# ---- el tercer paso es ancho Y ÁNGULO (el transportador de SketchUp) -------
#
# «Quiero dibujar un rectángulo que esté perpendicular así como en SketchUp»
# (Marco, 2026-09-10, con la captura de SketchUp for Web al lado: «Anchura,
# Ángulo: 3.79 m, 90.0»). El transportador de SketchUp gira sobre la ARISTA
# BASE, así que con la base tumbada el ancho se levanta hasta ponerse de pie.
# Capturar el plano en el primer clic —lo que ya se arregló— no da eso.

def _tool_con_base(scene, a=V(0, 0), b=V(9, 0)):
    from core.history import History
    vp = _VP(scene=scene)
    vp.history = History(scene)
    tool = RotatedRectangleTool()
    tool.on_click(_ctx(vp, a))
    tool.on_click(_ctx(vp, b))
    return tool, vp


def test_escribir_ancho_y_angulo_levanta_el_rectangulo():
    from core.scene import Scene
    scene = Scene()
    tool, vp = _tool_con_base(scene)
    tool.hover_point = V(9, 1)
    assert tool.on_value(vp, (3.0, 90.0)) is True
    assert len(scene.mesh.faces) == 1
    face = scene.mesh.faces[0]
    assert sorted({round(v.z(), 3) for v in face.vertices}) == [0.0, 3.0]
    # Una cara de pie tiene la normal horizontal.
    assert abs(face.normal().z()) < 1e-6


def test_un_solo_numero_mantiene_el_angulo_actual():
    from core.scene import Scene
    scene = Scene()
    tool, vp = _tool_con_base(scene)
    tool.hover_point = V(9, 1)
    tool.angle = 90.0
    assert tool.on_value(vp, 2.0) is True
    assert sorted({round(v.z(), 3) for v in scene.mesh.faces[0].vertices}) == [0.0, 2.0]


def test_el_cursor_fuera_del_plano_da_el_angulo_solo():
    from core.scene import Scene
    tool, _vp = _tool_con_base(Scene())
    ancho, angulo = tool._width_and_angle(V(9, 0, 2.5))
    assert abs(ancho - 2.5) < 1e-6
    assert abs(angulo - 90.0) < 1e-6
    ancho, angulo = tool._width_and_angle(V(9, 1.5, 0))
    assert abs(ancho - 1.5) < 1e-6
    assert abs(angulo) < 1e-6, "en el plano el ángulo es 0"


def test_el_angulo_se_pega_a_plano_y_perpendicular():
    from core.scene import Scene
    tool, _vp = _tool_con_base(Scene())
    import math
    # 88.5° está dentro del imán de 3°: debe caer en 90 clavado.
    casi = V(9, 1.5 * math.cos(math.radians(88.5)),
             1.5 * math.sin(math.radians(88.5)))
    assert abs(tool._width_and_angle(casi)[1] - 90.0) < 1e-9
    # 60° no se toca.
    lejos = V(9, 1.5 * math.cos(math.radians(60)),
              1.5 * math.sin(math.radians(60)))
    assert abs(tool._width_and_angle(lejos)[1] - 60.0) < 0.01


def test_ancho_cero_avisa_en_vez_de_reventar():
    """Un clic sobre la propia arista base fundía las esquinas y el plan
    moría con «degenerate edge», revertido y sin explicación."""
    from core.history import History
    from core.scene import Scene
    scene = Scene()
    vp = _VP(scene=scene)
    vp.history = History(scene)
    tool = RotatedRectangleTool()
    tool.on_click(_ctx(vp, V(0, 0)))
    tool.on_click(_ctx(vp, V(9, 0)))
    tool.on_click(_ctx(vp, V(4, 0)))          # encima de la base
    assert scene.mesh.faces == []
    assert vp.history.last_error is None, "no debe llegar a lanzar"
    assert vp.said, "y debe decir por qué"


def test_el_rectangulo_tumbado_no_cambia():
    from core.history import History
    from core.scene import Scene
    scene = Scene()
    vp = _VP(scene=scene)
    vp.history = History(scene)
    tool = RotatedRectangleTool()
    tool.on_click(_ctx(vp, V(0, 0)))
    tool.on_click(_ctx(vp, V(9, 0)))
    tool.on_click(_ctx(vp, V(9, 1.13)))
    assert len(scene.mesh.faces) == 1
    assert vp.history.last_error is None
    assert all(abs(v.z()) < 1e-9 for v in scene.mesh.faces[0].vertices)


# ---- el bloqueo de eje manda sobre el snap ---------------------------------

class _VPLock(_VP):
    def __init__(self, scene=None, axis_lock=None):
        super().__init__(scene=scene)
        self.axis_lock = axis_lock


def _con_base(scene, lock=None, a=V(7.2, 21.4), b=V(16.2, 21.4)):
    from core.history import History
    vp = _VPLock(scene=scene, axis_lock=lock)
    vp.history = History(scene)
    tool = RotatedRectangleTool()
    tool.on_click(_ctx(vp, a))
    tool.on_click(_ctx(vp, b))
    return tool, vp


def test_el_snap_no_puede_tumbar_un_rectangulo_con_el_eje_bloqueado():
    """El caso reportado, con sus coordenadas: la vista previa decía 90° y
    el clic llegaba pegado a una arista del suelo, a 0,60 m de la base. Salía
    un rectángulo tumbado en vez del vertical que se estaba viendo."""
    from core.scene import Scene
    scene = Scene()
    tool, vp = _con_base(scene, lock="z")
    tool.on_hover(_ctx(vp, V(16.2, 21.4, 1.05)))       # el ratón, arriba
    tool.on_click(_ctx(vp, V(16.2, 22.0, 0.0)))        # el snap, al suelo
    assert len(scene.mesh.faces) == 1
    face = scene.mesh.faces[0]
    assert sorted({round(v.z(), 3) for v in face.vertices}) == [0.0, 1.05]
    assert {round(v.y(), 3) for v in face.vertices} == {21.4}


def test_sin_bloqueo_el_clic_sigue_mandando():
    """Sin eje bloqueado no hay nada que respetar: el punto del clic decide,
    aunque se aparte de lo que mostraba la vista previa."""
    from core.scene import Scene
    scene = Scene()
    tool, vp = _con_base(scene)
    tool.on_hover(_ctx(vp, V(16.2, 21.4, 1.05)))
    tool.on_click(_ctx(vp, V(16.2, 22.0, 0.0)))
    face = scene.mesh.faces[0]
    assert sorted({round(v.z(), 3) for v in face.vertices}) == [0.0]


def test_el_eje_bloqueado_fija_la_direccion_del_ancho():
    from core.scene import Scene
    tool, vp = _con_base(Scene(), lock="z")
    d = tool.locked_dir(vp)
    assert d is not None
    assert abs(d.z() - 1.0) < 1e-9, "con Z bloqueado el ancho sube"
    tool2, vp2 = _con_base(Scene(), lock="x")
    # La base va por X, así que un bloqueo en X no deja dirección: se ignora.
    assert tool2.locked_dir(vp2) is None
