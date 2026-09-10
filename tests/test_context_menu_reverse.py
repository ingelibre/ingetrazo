# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«Ahora debería haber una opción de invertir cara» (Marco, 2026-09-10).

La había — en el menú Edición — y no la encontró, porque SketchUp la pone en
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
    assert "Hide Edges" in textos, "y las aristas siguen con lo suyo"


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
