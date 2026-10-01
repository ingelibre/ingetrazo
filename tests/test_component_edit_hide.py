# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Component Edit: Hide Rest of Model (Alt+Q) and Hide
Similar Components (Alt+W).

Hide Rest toggles the existing «rest of model while editing» mode between
``hide`` and whatever it was before; Hide Similar takes the other copies of
the component being edited out of the frame — and out of the pick.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence, QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _instance(proto, dx):
    g = Group(proto, name="Silla")
    m = QMatrix4x4()
    m.translate(dx, 0, 0)
    g.xform = m
    return g


def _three_chairs():
    """Two copies of one definition, and an unrelated component."""
    scene = Scene()
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    other = Mesh()
    other.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    a, b = _instance(proto, 0), _instance(proto, 5)
    c = _instance(other, 10)
    scene.groups.extend([a, b, c])
    return scene, a, b, c


def test_hide_similar_hides_only_the_siblings_while_editing():
    scene, a, b, c = _three_chairs()
    scene.hide_similar_components = True
    assert scene.entity_visible(b), "nothing is hidden at the root"
    scene.begin_group_edit(a)
    assert not scene.entity_visible(b)
    assert not scene.entity_selectable(b)
    assert scene.entity_visible(c), "another definition stays"
    assert scene.entity_visible(a)
    scene.end_group_edit()
    assert scene.entity_visible(b)


def test_hide_similar_off_leaves_the_siblings():
    scene, a, b, _c = _three_chairs()
    scene.begin_group_edit(a)
    assert scene.entity_visible(b)
    scene.end_group_edit()


def test_a_classic_group_has_no_similar():
    scene = Scene()
    m = Mesh()
    m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    g = Group(m, name="Muro")
    scene.groups.append(g)
    scene.hide_similar_components = True
    scene.begin_group_edit(g)
    assert scene.edit_definition() is None
    scene.end_group_edit()


def _window():
    from views.main_window import MainWindow
    return MainWindow()


def test_the_shortcuts_are_alt_q_and_alt_w():
    win = _window()
    assert win._act_hide_rest.shortcut() == QKeySequence("Alt+Q")
    assert win._act_hide_similar.shortcut() == QKeySequence("Alt+W")
    win._saved_version = win.viewport.scene.version
    win.close()


def test_hide_rest_toggles_back_to_the_previous_mode():
    win = _window()
    vp = win.viewport
    before = vp.edit_rest_mode
    try:
        vp.set_edit_rest_mode("normal")
        win._act_hide_rest.trigger()
        assert vp.edit_rest_mode == "hide"
        assert win._act_hide_rest.isChecked()
        win._act_hide_rest.trigger()
        assert vp.edit_rest_mode == "normal"
        assert not win._act_hide_rest.isChecked()
    finally:
        vp.set_edit_rest_mode(before)
        win._saved_version = vp.scene.version
        win.close()


def test_hide_similar_action_flips_the_scene_flag():
    win = _window()
    vp = win.viewport
    before = vp.scene.hide_similar_components
    try:
        win._act_hide_similar.trigger()
        assert vp.scene.hide_similar_components is (not before)
        assert win._act_hide_similar.isChecked() is (not before)
    finally:
        vp.set_hide_similar_components(before)
        win._saved_version = vp.scene.version
        win.close()
