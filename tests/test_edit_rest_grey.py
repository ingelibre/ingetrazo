# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Inside a group, the rest of the model turns grey («quiero que al entrar a
un grupo o componente lo demás quede gris», 14-10). The fade went towards
the background, and white faces on a light background stayed white: nothing
said you were inside a group. Renders two groups, opens one, reads pixels.

Needs a GL context that renders; skipped where the platform has none."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from views.viewport import edit_fade_color

_app = QApplication.instance() or QApplication([])


def test_the_fade_colour_is_a_grey_away_from_a_light_background():
    light = (0.93, 0.93, 0.93)
    grey = edit_fade_color(light)
    assert all(abs(c - grey[0]) < 1e-9 for c in grey)      # neutral
    assert light[0] - grey[0] > 0.15                         # clearly darker
    dark = (0.15, 0.15, 0.17)
    assert edit_fade_color(dark)[0] > dark[0] + 0.1          # lifted on dark


def _square(x, comp):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 2, 0, 0), V(x + 2, 2, 0), V(x, 2, 0)])
    g = Group(m, name=f"g{x}")
    if comp:
        g.xform = QMatrix4x4()
    return g


@pytest.mark.parametrize("comp", [False, True], ids=["group", "component"])
def test_the_rest_reads_grey_and_the_group_keeps_its_colour(comp):
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    try:
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        sc = vp.scene
        sc.groups.clear()
        a, b = _square(0, comp), _square(4, comp)
        sc.groups.extend([a, b])
        sc.version += 1
        vp.set_edit_rest_mode("fade")
        vp.camera.set_view("top")
        vp.camera.target = V(3, 1, 0)
        vp.camera.distance = 12

        def colour(p):
            vp.update()
            _app.processEvents()
            img = vp.grabFramebuffer()
            x, y = vp._world_to_pixel(p)
            r = img.devicePixelRatio()
            return img.pixelColor(int(x * r), int(y * r))

        before = colour(V(5, 1, 0))
        vp.begin_group_edit(a)
        after = colour(V(5, 1, 0))
        inside = colour(V(1, 1, 0))
        # the other group lost a clear step of lightness: grey, not white
        assert before.lightnessF() - after.lightnessF() > 0.08
        # the open one keeps its own colour
        assert abs(inside.lightnessF() - before.lightnessF()) < 0.03
    finally:
        w._saved_version = vp.scene.version
        w.close()
