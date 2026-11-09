# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What changes inside an open group shows at once, however deep it sits.

A group opened inside another, or a container opened with faces of its own,
keeps a matrix, and it used to draw through the instanced path, whose caches
trust the placements epoch: the epoch leaves the open mesh out on purpose, so
paint, new faces and moves did not show until it was closed. The other half: a
closed mesh repainted (an undo after leaving it, a material edited) bumped no
serial. Real frames are read back, in the offscreen platform's GL context."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.history import (SetFaceBackCommand, SetFaceColorCommand,
                          SetFaceOpacityCommand, SetFaceTextureCommand,
                          SetFaceMaterialTagCommand)
from core.mesh import Mesh

_app = QApplication.instance() or QApplication([])


def _box_mesh(x0=-1, y0=-1, z0=0, x1=1, y1=1, z1=2):
    m = Mesh()
    p = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in idx])
    return m


def _at(x, y, z):
    m = QMatrix4x4()
    m.translate(x, y, z)
    return m


def plain(vp):
    g = Group(_box_mesh())
    vp.scene.groups.append(g)
    return [g]


def component(vp):
    g = Group(_box_mesh(0, 0, 0, 2, 2, 2))
    g.xform = _at(-1, -1, 0)
    g.component = "c"
    vp.scene.groups.append(g)
    return [g]


def nested_plain(vp):
    kid = Group(_box_mesh())
    other = Group(_box_mesh(5, 5, 0, 6, 6, 1))
    top = Group(Mesh())
    top.adopt([kid, other])
    vp.scene.groups.append(top)
    return [top, kid]


def nested_component(vp):
    kid = Group(_box_mesh(0, 0, 0, 2, 2, 2))
    kid.xform = _at(-1, -1, 0)
    kid.component = "c"
    other = Group(_box_mesh(5, 5, 0, 6, 6, 1))
    top = Group(Mesh())
    top.adopt([kid, other])
    top.xform = _at(0, 0, 0)
    vp.scene.groups.append(top)
    return [top, kid]


def container_own(vp):
    kid = Group(_box_mesh(5, 5, 0, 6, 6, 1))
    top = Group(_box_mesh())
    top.adopt([kid])
    vp.scene.groups.append(top)
    return [top]


LAYOUTS = [plain, component, nested_plain, nested_component, container_own]


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    for _ in range(10):
        _app.processEvents()
    vp = w.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        w.close()
        pytest.skip("no OpenGL context")
    vp.scene.guides.clear()
    yield w
    w._saved_version = vp.scene.version
    w.close()


def _pixel(vp):
    img = vp.grabFramebuffer()
    c = img.pixelColor(img.width() // 2 + 15, img.height() // 2 + 15)
    return (c.red(), c.green(), c.blue())


def _red(rgb):
    return rgb[0] > 120 and rgb[1] < 90 and rgb[2] < 90


def _front_face(vp):
    best = None
    for f in vp.scene.mesh.faces:
        ys = [v.y() for v in f.vertices]
        if max(ys) - min(ys) < 1e-6 and (best is None or ys[0] < best[0]):
            best = (ys[0], f)
    return best[1]


def _open(vp, layout):
    path = layout(vp)
    vp.scene.version += 1
    vp.camera.set_view("front")
    vp.camera.perspective = False
    vp.camera.fit_to(V(-3, -1, -1), V(3, 1, 3))
    _pixel(vp)
    for g in path:
        vp.begin_group_edit(g)
        _pixel(vp)
    _pixel(vp)



def _blue(rgb):
    return rgb[2] > 120 and rgb[0] < 90 and rgb[1] < 90


def _red_image(tmp_path):
    from PySide6.QtGui import QColor, QImage
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(255, 0, 0))
    path = str(tmp_path / "red.png")
    img.save(path)
    return {"path": path, "sw": 1.0, "sh": 1.0}


every_layout = pytest.mark.parametrize("layout", LAYOUTS,
                                       ids=lambda l: l.__name__)


@every_layout
def test_a_painted_colour_shows_and_undo_and_redo_too(win, layout):
    vp = win.viewport
    _open(vp, layout)
    vp.history.execute(SetFaceColorCommand([_front_face(vp)], (1.0, 0.0, 0.0)))
    assert _red(_pixel(vp))
    vp.history.undo()
    assert not _red(_pixel(vp))
    vp.history.redo()
    assert _red(_pixel(vp))


def nested_component_turned(vp):
    """A matrix that does not round-trip to the bit: the edited definition
    comes back a hair off, which reads as a tiny translation of its bake."""
    kid = Group(_box_mesh(0, 0, 0, 2, 2, 2))
    m = _at(0.008682441711426, -1.4345712661743164, -0.5000573992729187)
    m.rotate(45.0, 0.0, 0.0, 1.0)
    kid.xform = m
    kid.component = "c"
    other = Group(_box_mesh(5, 5, 0, 6, 6, 1))
    top = Group(Mesh())
    top.adopt([kid, other])
    top.xform = _at(0, 0, 0)
    vp.scene.groups.append(top)
    return [top, kid]


@pytest.mark.parametrize("layout", LAYOUTS + [nested_component_turned],
                         ids=lambda l: l.__name__)
def test_a_paint_stays_on_screen_after_leaving_the_groups(win, layout):
    """What was seen inside is what is seen outside: an edited component goes
    back through restore_state, and a bake that took it for a move kept the
    old material (the letters of the plaza, 04-11)."""
    vp = win.viewport
    _open(vp, layout)
    img = vp.grabFramebuffer()
    x = (img.width() // 2 + 15) * vp.width() // img.width()
    y = (img.height() // 2 + 15) * vp.height() // img.height()
    face = vp.pick_face_any(x, y)[0]
    assert face is not None
    vp.history.execute(SetFaceColorCommand([face], (1.0, 0.0, 0.0)))
    assert _red(_pixel(vp))
    vp.end_group_edit()
    assert _red(_pixel(vp))
    vp.history.undo()
    assert not _red(_pixel(vp))
    vp.history.redo()
    assert _red(_pixel(vp))


@every_layout
def test_a_painted_texture_shows(win, layout, tmp_path):
    vp = win.viewport
    _open(vp, layout)
    vp.history.execute(SetFaceTextureCommand([_front_face(vp)],
                                             _red_image(tmp_path)))
    assert _red(_pixel(vp))
    vp.history.undo()
    assert not _red(_pixel(vp))


@every_layout
def test_a_translucent_paint_draws_once(win, layout):
    """It leaves the opaque path as it turns translucent: drawn by both, the
    old grey showed through (178, 105, 103 where a plain group gives 141, 76,
    85)."""
    vp = win.viewport
    plain_look = (141, 76, 85)
    _open(vp, layout)
    f = _front_face(vp)
    vp.history.execute(SetFaceColorCommand([f], (1.0, 0.0, 0.0)))
    vp.history.execute(SetFaceOpacityCommand([f], 0.4))
    got = _pixel(vp)
    assert all(abs(a - b) <= 3 for a, b in zip(got, plain_look)), got


@every_layout
def test_a_painted_back_shows_and_undo_clears_it(win, layout):
    vp = win.viewport
    _open(vp, layout)
    mesh = vp.scene.mesh
    mesh.remove_face(_front_face(vp))            # to see inside, onto a back
    vp.scene.version += 1
    _pixel(vp)
    far = max((f for f in mesh.faces
               if max(v.y() for v in f.vertices)
               - min(v.y() for v in f.vertices) < 1e-6),
              key=lambda f: f.vertices[0].y())
    vp.history.execute(SetFaceBackCommand([far], [{"color": [0.0, 0.0, 1.0]}]))
    assert _blue(_pixel(vp))
    vp.history.undo()
    assert not _blue(_pixel(vp))


@every_layout
def test_a_texture_on_the_back_shows_over_a_painted_front(win, layout, tmp_path):
    vp = win.viewport
    _open(vp, layout)
    mesh = vp.scene.mesh
    mesh.remove_face(_front_face(vp))
    vp.scene.version += 1
    _pixel(vp)
    far = max((f for f in mesh.faces
               if max(v.y() for v in f.vertices)
               - min(v.y() for v in f.vertices) < 1e-6),
              key=lambda f: f.vertices[0].y())
    vp.history.execute(SetFaceColorCommand([far], (0.0, 1.0, 0.0)))
    vp.history.execute(SetFaceBackCommand([far],
                                          [{"texture": _red_image(tmp_path)}]))
    assert _red(_pixel(vp))
    assert far.attrs["color"] == [0.0, 1.0, 0.0]       # the front keeps its own


@every_layout
def test_a_new_face_shows(win, layout):
    vp = win.viewport
    _open(vp, layout)
    mesh = vp.scene.mesh
    face = mesh.add_face([V(-1, -1.5, 0), V(1, -1.5, 0),
                          V(1, -1.5, 2), V(-1, -1.5, 2)])
    face.attrs["color"] = (1.0, 0.0, 0.0)
    vp.scene.version += 1
    assert _red(_pixel(vp))


@every_layout
def test_moving_all_of_it_shows(win, layout):
    """The whole mesh by one vector shifts its bake in place, same uid."""
    vp = win.viewport
    _open(vp, layout)
    mesh = vp.scene.mesh
    before = _pixel(vp)
    for v in list(mesh.vertices):
        mesh.move_vertex(v, V(0, 0, 50))
    vp.scene.version += 1
    assert _pixel(vp) != before


@every_layout
def test_undo_after_leaving_the_group_shows(win, layout):
    vp = win.viewport
    _open(vp, layout)
    vp.history.execute(SetFaceColorCommand([_front_face(vp)], (1.0, 0.0, 0.0)))
    _pixel(vp)
    vp.end_group_edit()
    assert _red(_pixel(vp))
    while vp.history.undo_stack:
        vp.history.undo()
    assert not _red(_pixel(vp))


@every_layout
def test_a_material_edited_with_the_group_closed_shows(win, layout):
    from core.history import RestampMaterialCommand
    from core.materials import Material
    vp = win.viewport
    _open(vp, layout)
    f = _front_face(vp)
    vp.history.execute(SetFaceMaterialTagCommand(
        [f], "M", Material("M", color=(0.0, 1.0, 0.0))))
    vp.history.execute(SetFaceColorCommand([f], (0.0, 1.0, 0.0)))
    _pixel(vp)
    vp.end_group_edit()
    _pixel(vp)
    vp.history.execute(RestampMaterialCommand(
        "M", Material("M", color=(1.0, 0.0, 0.0))))
    assert _red(_pixel(vp))
    vp.history.undo()
    assert not _red(_pixel(vp))


def _single_child(vp):
    kid = Group(_box_mesh())
    top = Group(Mesh())
    top.adopt([kid])
    vp.scene.groups.append(top)
    return [top, kid]


def test_left_closed_it_draws_what_it_wore_inside(win):
    vp = win.viewport
    _open(vp, _single_child)
    vp.history.execute(SetFaceColorCommand([_front_face(vp)], (1.0, 0.0, 0.0)))
    _pixel(vp)
    vp.end_group_edit()
    assert _red(_pixel(vp))


def test_turned_translucent_inside_it_stays_on_screen_when_left(win):
    vp = win.viewport
    _open(vp, _single_child)
    f = _front_face(vp)
    vp.history.execute(SetFaceColorCommand([f], (1.0, 0.0, 0.0)))
    vp.history.execute(SetFaceOpacityCommand([f], 0.4))
    _pixel(vp)
    vp.end_group_edit()
    got = _pixel(vp)
    assert got[0] > got[1] + 20, got


def test_copies_outside_still_draw_instanced(win):
    """Only the open mesh leaves the instanced path, and only while open."""
    vp = win.viewport
    _open(vp, nested_plain)
    top = vp.scene.groups[-1]
    sibling = next(g for g in vp._placements()
                   if g.mesh is top.children[1].mesh)
    assert vp._instanced_eligible(sibling)
    opened = next(g for g in vp._placements() if g.mesh is vp.scene.mesh)
    assert not vp._instanced_eligible(opened)
    vp.end_group_edit()
    _pixel(vp)
    closed = next(g for g in vp._placements()
                  if g.mesh is top.children[0].mesh)
    assert vp._instanced_eligible(closed)


def test_leaving_a_nested_component_counts_its_copies(win, monkeypatch):
    vp = win.viewport
    said = []
    monkeypatch.setattr(vp, "flash_status",
                        lambda text, *_a: said.append(text))
    _open(vp, nested_component)
    vp.history.execute(SetFaceColorCommand([_front_face(vp)], (1.0, 0.0, 0.0)))
    vp.end_group_edit()
    assert any(" 1 " in text for text in said), said
