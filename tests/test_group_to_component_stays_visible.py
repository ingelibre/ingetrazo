# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Make Component on a classic group: the object stays on screen. The group
gains a matrix, which moves it from the static draw to the instanced one; the
placement passes took that for a Move and kept their old lists, so neither
path drew it until something else rebuilt them.

The pixel test needs a GL context that renders; skipped where the platform
has none. The epoch tests run everywhere."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.history import GroupToComponentCommand, MakeGroupCommand

_app = QApplication.instance() or QApplication([])


def _box(scene):
    p = [V(-1, -1, 0), V(1, -1, 0), V(1, 1, 0), V(-1, 1, 0),
         V(-1, -1, 2), V(1, -1, 2), V(1, 1, 2), V(-1, 1, 2)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        scene.mesh.add_face([p[i] for i in idx])
    scene.version += 1


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    for _ in range(10):
        _app.processEvents()
    sc = w.viewport.scene
    sc.groups.clear()
    sc.guides.clear()
    _box(sc)
    yield w
    w._saved_version = sc.version
    w.close()


def _group_the_box(vp):
    sc = vp.scene
    vp.history.execute(MakeGroupCommand(list(sc.mesh.faces),
                                        list(sc.mesh.edges)))
    return sc.groups[-1]


def test_gaining_or_losing_a_matrix_is_not_a_move(win):
    vp = win.viewport
    g = _group_the_box(vp)
    classic = vp._placements_epoch()
    vp.history.execute(GroupToComponentCommand(g, "Caja"))
    component = vp._placements_epoch()
    assert classic != component
    assert not vp._epoch_only_matrices(classic, component)
    vp.history.undo()
    assert not vp._epoch_only_matrices(component, vp._placements_epoch())


def test_moving_a_component_is_still_a_move(win):
    # The fast path a Move lives on (#158) stays open.
    vp = win.viewport
    g = _group_the_box(vp)
    vp.history.execute(GroupToComponentCommand(g, "Caja"))
    before = vp._placements_epoch()
    g.xform.translate(3.0, 0.0, 0.0)
    vp.scene.version += 1
    after = vp._placements_epoch()
    assert before != after
    assert vp._epoch_only_matrices(before, after)


def test_the_box_stays_on_screen(win):
    from views import prompts
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    sc = vp.scene
    sc.display_style.sky = False
    vp.camera.set_view("front")                           # looking toward +Y
    vp.camera.perspective = False
    vp.camera.fit_to(V(-3, -1, -1), V(3, 1, 3))

    def on_face():
        img = vp.grabFramebuffer()
        dpr = img.width() / max(vp.width(), 1)
        # Off the face's centre, clear of any edge or axis.
        x, y = vp._world_to_pixel(V(0.37, -1, 0.73))[:2]
        return img.pixelColor(int(x * dpr), int(y * dpr)).name()

    def on_background():
        img = vp.grabFramebuffer()
        dpr = img.width() / max(vp.width(), 1)
        x, y = vp._world_to_pixel(V(2.7, -1, 2.7))[:2]
        return img.pixelColor(int(x * dpr), int(y * dpr)).name()

    g = _group_the_box(vp)
    face = on_face()
    assert face != on_background()                        # the box is drawn

    sc.selection.clear()
    sc.selection.add(g)
    orig = prompts.get_text
    prompts.get_text = lambda *a, text="", **k: ("Caja", True)
    try:
        win._on_make_component()
    finally:
        prompts.get_text = orig
    assert g.is_component()
    assert on_face() == face                              # the report

    vp.history.undo()
    assert not g.is_component()
    assert on_face() == face
