# SPDX-License-Identifier: GPL-3.0-or-later
"""The marking of the face under the cursor sits ON the part it is over.

A face inside a component is stored in its part's own coordinates; the
matrix of the placement it was reached through puts it in the world. The
hover marking was built from the face alone, so on a component that had been
placed and exploded it appeared metres from the real part."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core.group import Group, world_mesh
from core.history import ExplodeViewCommand
from core.mesh import Mesh
from tools.base import ToolContext
from tools.paint import PaintTool

_app = QApplication.instance() or QApplication([])

_QUADS = ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
          (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5))


def _cube(at) -> Group:
    mesh = Mesh()
    x0, y0, z0 = at
    c = [QVector3D(x0 + dx, y0 + dy, z0 + dz) for dz in (0, 1)
         for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])
    g = Group(mesh)
    g.xform = QMatrix4x4()
    return g


def _window_with_a_placed_exploded_component():
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    vp = win.viewport
    box = Group(name="box")
    box.adopt([_cube((0, 0, 0)), _cube((-3, 0, 0)), _cube((3, 0, 0)),
               _cube((0, 0, 3))])
    box.xform = QMatrix4x4()
    box.xform.translate(QVector3D(10, 5, 0))
    box.xform.rotate(35, 0, 0, 1)
    vp.scene.groups.append(box)
    vp.scene.version += 1
    vp.history.execute(ExplodeViewCommand(box, 1.0))
    vp.camera.target = QVector3D(10, 5, 1)
    vp.camera.distance = 13.0
    return win, vp


def _bounds(mesh):
    pts = np.array([[v.position.x(), v.position.y(), v.position.z()]
                    for v in mesh.vertices])
    return pts.min(axis=0), pts.max(axis=0)


def _ctx(vp, x, y):
    return ToolContext(viewport=vp, world=QVector3D(), screen=QPointF(x, y),
                       modifiers=Qt.NoModifier, snap=None)


def _probe(vp):
    """``(face, placement)`` for every probe pixel that lands on a face."""
    for y in range(100, 740, 20):
        for x in range(100, 1120, 25):
            face, placement = vp.pick_face_placement(x, y)
            if face is not None and placement is not None:
                yield x, y, face, placement


def test_the_paint_hover_marking_lies_on_the_part_it_is_over():
    win, vp = _window_with_a_placed_exploded_component()
    try:
        tool = PaintTool()
        checked = 0
        for x, y, _face, _placement in _probe(vp):
            tool.on_hover(_ctx(vp, x, y))
            face, placement = vp._hover_entity, vp._hover_placement
            assert face is not None and placement is not None
            marking = np.array(vp._hover_face_data(face, placement),
                               dtype=float).reshape(-1, 3)
            lo, hi = _bounds(world_mesh(placement))
            assert np.all(marking.min(axis=0) >= lo - 1e-3)
            assert np.all(marking.max(axis=0) <= hi + 1e-3)
            checked += 1
        assert checked >= 8
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_without_the_placement_the_marking_is_where_the_part_would_be_unplaced():
    """What the fix corrects: the same face, built from its own coordinates
    alone, is far from the part on screen."""
    win, vp = _window_with_a_placed_exploded_component()
    try:
        _x, _y, face, placement = next(_probe(vp))
        bare = np.array(vp._hover_face_data(face, None),
                        dtype=float).reshape(-1, 3)
        lo, hi = _bounds(world_mesh(placement))
        assert not np.all(bare.min(axis=0) >= lo - 1e-3) \
            or not np.all(bare.max(axis=0) <= hi + 1e-3)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_loose_face_needs_no_placement():
    from views.viewport import Viewport
    mesh = Mesh()
    face = mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                          QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    data = np.array(Viewport._hover_face_data(face, None),
                    dtype=float).reshape(-1, 3)
    assert data.max(axis=0).tolist() == [1.0, 1.0, 0.0]


def test_hovering_the_same_face_through_another_placement_updates_the_marking():
    win, vp = _window_with_a_placed_exploded_component()
    try:
        _x, _y, face, placement = next(_probe(vp))
        vp.set_hover(face, placement)
        other = type("Placement", (), {"xform": QMatrix4x4()})()
        vp.set_hover(face, other)
        assert vp._hover_placement is other
    finally:
        win._saved_version = vp.scene.version
        win.close()
