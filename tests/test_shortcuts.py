# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""No two actions may hold the same key: Qt kills BOTH.

Reported by pacaeiro (PR #11, «Fix protractor shortcut conflict with pan»).
When two ``QAction`` in one window share a shortcut, Qt does not pick one —
it flags the shortcut ambiguous, prints ``QAction::event: Ambiguous shortcut
overload`` and fires NOTHING. Measured on 2026-09-10, three keys were dead:

* ``H``  — Protractor against Pan (the report),
* ``O``  — Center Arc against Orbit,
* ``F2`` — Zoom Extents registered twice, once for the toolbar button and
  once for the Camera menu entry.

The plugin loader already knew this failure mode and refuses a taken key to
a plugin (``test_plugin_cannot_steal_a_builtin_shortcut``, whose comment
says it in these words: "instead of creating a Qt ambiguity that disables
the key for both"). Nobody applied the same rule to the built-ins among
themselves. This file does.

The camera keys come from SketchUp's own card: Orbit O, Pan H, Zoom Z, Zoom
Extents Shift+Z. The Protractor and the Center Arc have NO default shortcut
there, so they are the ones that yield — and they keep a Shift+key so they
stay reachable.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

import core.extensions as extensions                              # noqa: E402


@pytest.fixture
def ventana(tmp_path, monkeypatch):
    """A visible MainWindow with no user plugins in sight.

    Shown on purpose: a shortcut only dispatches on a window that is up, and
    this file is about shortcuts actually firing.
    """
    monkeypatch.setattr(extensions, "plugin_dirs", lambda: [tmp_path])
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    yield win
    win._saved_version = win.viewport.scene.version   # no "save?" modal
    win.close()


def _todos_los_atajos(win) -> dict[str, list[str]]:
    """``{atajo: [nombres de las acciones que lo piden]}``, primary and
    alternates alike — an alternate collides exactly the same."""
    por_tecla: dict[str, list[str]] = {}
    for action in win.findChildren(QAction):
        for seq in {action.shortcut(), *action.shortcuts()}:
            texto = seq.toString()
            if texto:
                por_tecla.setdefault(texto, []).append(
                    action.text() or action.toolTip())
    return por_tecla


def _pulsar(win, tecla, modificador=Qt.NoModifier) -> list[str]:
    """Names of the actions that fired for one keystroke on the viewport."""
    disparos: list[str] = []
    conexiones = []
    for action in win.findChildren(QAction):
        conexiones.append(action.triggered.connect(
            lambda _c=False, n=action.text(): disparos.append(n)))
    QTest.keyClick(win.viewport, tecla, modificador)
    QApplication.processEvents()
    return disparos


def _calentar(win) -> None:
    """The first keystroke a freshly shown offscreen window gets is dropped
    before the shortcut map sees it; spend it on a key nobody claims."""
    QTest.keyClick(win.viewport, Qt.Key_F1)
    QApplication.processEvents()


def test_ninguna_accion_pisa_el_atajo_de_otra(ventana):
    chocan = {tecla: nombres
              for tecla, nombres in _todos_los_atajos(ventana).items()
              if len(nombres) > 1}
    assert not chocan, (
        "atajos compartidos — Qt los deja MUERTOS a todos: "
        + "; ".join(f"{t} -> {n}" for t, n in sorted(chocan.items())))


def test_las_teclas_de_camara_son_las_de_sketchup(ventana):
    """O / H / Z / Shift+Z, tal cual la tarjeta de referencia de SketchUp."""
    _calentar(ventana)
    for tecla, modificador, esperado in (
            (Qt.Key_O, Qt.NoModifier, "Orbit"),
            (Qt.Key_H, Qt.NoModifier, "Pan"),
            (Qt.Key_Z, Qt.NoModifier, "Zoom"),
            (Qt.Key_Z, Qt.ShiftModifier, "Zoom Extents"),
            (Qt.Key_F2, Qt.NoModifier, "Zoom Extents"),   # el de toda la vida
    ):
        assert _pulsar(ventana, tecla, modificador) == [esperado]


def test_las_dos_herramientas_que_cedieron_siguen_a_mano(ventana):
    """Ceder la tecla no puede dejarlas sin ninguna."""
    _calentar(ventana)
    assert _pulsar(ventana, Qt.Key_H, Qt.ShiftModifier) == ["Protractor"]
    assert _pulsar(ventana, Qt.Key_O, Qt.ShiftModifier) == ["Center Arc"]


#: Lo que SketchUp SÍ trae atado de fábrica y nosotros respetamos, de su
#: tarjeta 2026. Lo que falta de esa lista es deliberado y está anotado
#: abajo; lo que sobra son teclas que allá están libres.
TARJETA_SKETCHUP = {
    "Space": "Select", "B": "Paint", "E": "Eraser", "L": "Line",
    "R": "Rectangle", "C": "Circle", "A": "Arc", "M": "Move",
    "Q": "Rotate", "S": "Scale", "F": "Offset", "T": "Tape Measure",
    "O": "Orbit", "H": "Pan", "Z": "Zoom", "Shift+Z": "Zoom Extents",
    "G": "Make Component…", "P": "Push / Pull",
}
# Divergencias a propósito, para que nadie las "arregle" sin decidirlo:
#   U       = Empujar/Tirar   (segundo atajo del MISMO comando: la tecla que
#                              IngeTrazo usó hasta el 2026-09-10)
#   Mayús+P = Perspectiva/paralela (SketchUp no le da tecla ninguna)
#   K       = Rectángulo rotado    (SketchUp: aristas traseras; el rotado no
#                                   tiene tecla allá)
#   F2      = Zoom a extensión     (segundo atajo, además de Shift+Z)
#   D J W X Y = Cota, Arco 3 puntos, Sígueme, Texto, Ruta — sin tecla allá.


def test_respetamos_la_tarjeta_de_sketchup(ventana):
    atajos = _todos_los_atajos(ventana)
    for tecla, nombre in TARJETA_SKETCHUP.items():
        assert atajos.get(tecla) == [nombre], (
            f"{tecla} debería ser {nombre!r} como en SketchUp, "
            f"y tiene {atajos.get(tecla)}")


def test_el_arco_de_A_es_el_de_comba_como_en_sketchup(ventana):
    """SketchUp ata A al «2 Point Arc» (cuerda y comba). El nuestro se llama
    solo «Arc», y es ese: su cuadro pide la comba."""
    from tools.arc import ArcTool
    assert ArcTool.shortcut == "A"
    assert ArcTool.vcb_label == "Bulge"


def test_la_p_es_empujar_tirar_y_la_u_sigue_valiendo(ventana):
    """«P como SketchUp» (Marco, 2026-09-10). La U no se tira: es el mismo
    comando con dos atajos, que es lo legal — dos ACCIONES con un atajo es
    lo que Qt mata."""
    _calentar(ventana)
    assert _pulsar(ventana, Qt.Key_P) == ["Push / Pull"]
    assert _pulsar(ventana, Qt.Key_U) == ["Push / Pull"]
    atajos = _todos_los_atajos(ventana)
    assert atajos["P"] == ["Push / Pull"] and atajos["U"] == ["Push / Pull"]


def test_la_perspectiva_se_mudo_a_mayus_p(ventana):
    _calentar(ventana)
    assert _pulsar(ventana, Qt.Key_P, Qt.ShiftModifier) == [
        "Toggle Perspective / Parallel"]
