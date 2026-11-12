# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«Ahora debería haber una opción de invertir cara» (Marco, 2026-09-10).

La había — en el menú Edición — y no la encontró, porque lo habitual es ponerla en
el menú del BOTÓN DERECHO sobre la cara, que es donde uno la busca. Aquí el
menú contextual ofrecía agrupar, ocultar aristas, cortar, copiar y borrar,
pero no invertir.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication, QMenu

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)


def _V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


@pytest.fixture
def ventana():
    from views.main_window import MainWindow
    win = MainWindow()
    yield win
    win._saved_version = win.viewport.scene.version
    win.close()


class _MenuSinModal(QMenu):
    """Un QMenu de verdad al que se le quita el `exec`, que bloquearía la
    prueba esperando a un ratón que no existe."""

    abiertos: list = []

    def exec(self, *args, **kwargs):        # noqa: A003 - el nombre es de Qt
        _MenuSinModal.abiertos.append(self)
        return None


def _entradas(win, monkeypatch, seleccion):
    """Textos del menú contextual con esa selección."""
    import views.main_window as mw
    _MenuSinModal.abiertos.clear()
    monkeypatch.setattr(mw, "QMenu", _MenuSinModal)
    win.viewport.scene.select(list(seleccion))
    win.show_viewport_context_menu(QPoint(0, 0))
    assert _MenuSinModal.abiertos, "no se llegó a abrir ningún menú"
    return [a.text() for a in _MenuSinModal.abiertos[0].actions()]


def _cara(scene):
    return scene.mesh.add_face([_V(0, 0), _V(2, 0), _V(2, 2), _V(0, 2)])


def test_con_una_cara_seleccionada_el_menu_ofrece_invertir(ventana, monkeypatch):
    cara = _cara(ventana.viewport.scene)
    assert "Reverse Faces" in _entradas(ventana, monkeypatch, [cara])


def test_solo_con_aristas_no_aparece(ventana, monkeypatch):
    """Invertir una arista no significa nada: la entrada es de caras."""
    cara = _cara(ventana.viewport.scene)
    arista = ventana.viewport.scene.mesh.edges[0]
    assert cara is not None
    textos = _entradas(ventana, monkeypatch, [arista])
    assert "Reverse Faces" not in textos
    # «Hide» since 2026-09-18: the one entry hides objects and edges alike.
    assert "Hide" in textos, "y las aristas siguen con lo suyo"


def test_invertir_desde_el_menu_da_la_vuelta_a_la_cara(ventana):
    """La entrada tiene que hacer el trabajo, no solo estar."""
    scene = ventana.viewport.scene
    cara = _cara(scene)
    antes = cara.normal()
    scene.select([cara])
    ventana._on_reverse_faces()
    assert QVector3D.dotProduct(cara.normal(), antes) < -0.99
    ventana.viewport.history.undo()
    assert QVector3D.dotProduct(cara.normal(), antes) > 0.99


@pytest.mark.parametrize("vertices", [
    [_V(0, 0), _V(2, 0), _V(2, 2), _V(0, 2)],
    [_V(0, 2), _V(2, 2), _V(2, 0), _V(0, 0)],
    [_V(0, 0), _V(0, 2), _V(0, 2, 3), _V(0, 0, 3)],
    [_V(0, 0), _V(2, 0, 2), _V(2, 2, 2), _V(0, 2)],
])
def test_align_view_from_face_menu(ventana, monkeypatch, vertices):
    scene = ventana.viewport.scene
    face = scene.mesh.add_face(vertices)
    camera = ventana.viewport.camera
    camera.set_projection("parallel")
    distance = camera.distance
    assert "Align View" in _entradas(ventana, monkeypatch, [face])
    next(a for a in _MenuSinModal.abiertos[-1].actions()
         if a.text() == "Align View").trigger()
    assert (camera.target - face.centroid()).length() < 1e-5
    assert QVector3D.dotProduct(camera.forward(), face.normal()) < -0.99999
    assert camera.distance == distance
    assert camera.projection_mode() == "parallel"


def test_align_view_only_for_one_face(ventana, monkeypatch):
    scene = ventana.viewport.scene
    first = _cara(scene)
    second = scene.mesh.add_face([_V(3, 0), _V(4, 0), _V(4, 1), _V(3, 1)])
    assert "Align View" not in _entradas(ventana, monkeypatch, [scene.mesh.edges[0]])
    assert "Align View" not in _entradas(ventana, monkeypatch, [first, second])


def test_align_view_in_nested_transformed_component(ventana, monkeypatch):
    import views.main_window as mw
    from PySide6.QtGui import QContextMenuEvent, QMatrix4x4
    from core.group import Group
    from core.mesh import Mesh

    scene = ventana.viewport.scene
    mesh = Mesh()
    mesh.add_face([_V(0, 0), _V(2, 0), _V(2, 2), _V(0, 2)])
    child = Group(mesh, "component")
    child.xform = QMatrix4x4()
    child.xform.translate(3, 4, 5)
    child.xform.rotate(40, 0, 1, 0)
    parent = Group(Mesh(), "group")
    parent.xform = QMatrix4x4()
    parent.xform.translate(12, 8, 2)
    parent.xform.rotate(30, 0, 0, 1)
    parent.component = False
    parent.children = [child]
    world = parent.xform * child.xform
    expected_center = world.map(_V(1, 1))
    expected_normal = world.mapVector(_V(0, 0, 1)).normalized()
    scene.groups.append(parent)
    ventana.viewport.begin_group_edit(parent)
    ventana.viewport.begin_group_edit(child)
    face = scene.mesh.faces[0]
    camera = ventana.viewport.camera
    camera.target = expected_center
    camera.set_view("top")
    ventana.viewport.resize(1000, 600)
    camera.set_aspect(1000, 600)
    camera.set_projection("two_point")
    px = ventana.viewport._world_to_pixel(expected_center)
    pos = QPoint(round(px[0]), round(px[1]))
    _MenuSinModal.abiertos.clear()
    monkeypatch.setattr(mw, "QMenu", _MenuSinModal)
    ventana.viewport.contextMenuEvent(
        QContextMenuEvent(QContextMenuEvent.Mouse, pos, pos))
    assert face in scene.selection
    next(a for a in _MenuSinModal.abiertos[-1].actions()
         if a.text() == "Align View").trigger()
    assert (camera.target - expected_center).length() < 1e-5
    assert QVector3D.dotProduct(camera.forward(), expected_normal) < -0.99999
    view_normal = camera.view_matrix().mapVector(expected_normal)
    assert abs(view_normal.x()) < 1e-5 and abs(view_normal.y()) < 1e-5
    assert camera.projection_mode() == "perspective"
