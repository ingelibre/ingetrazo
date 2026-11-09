# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Locking changes the selection color, not face opacity or edge visibility."""
import numpy as np
import pytest
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.history import History, LockCommand
from core.style import Style


@pytest.fixture
def cube_viewport():
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from views.viewport import Viewport

    if QApplication.platformName() == 'offscreen':
        pytest.skip('requires a native OpenGL widget')
    gc.collect()
    vp = Viewport()
    vp.setAttribute(Qt.WA_DontShowOnScreen)
    vp.resize(900, 750)
    vp.show()
    try:
        for _ in range(3):
            QApplication.processEvents()
        if not vp.isValid() or getattr(vp, '_gl', None) is None:
            pytest.skip('no native OpenGL context')
        yield vp
    finally:
        vp.close()
        vp.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _box(mesh, lo, hi):
    points = [V(x, y, z) for z in (lo[2], hi[2])
              for y in (lo[1], hi[1]) for x in (lo[0], hi[0])]
    for face in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                 (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)):
        mesh.add_face([points[i] for i in face])


def _scene(vp, placement='plain'):
    scene = vp.scene
    scene.clear()
    scene.show_axes = False
    scene.display_style = Style(sky=False, profiles=False)
    scene.display_style.ground = False
    scene.display_style.modeling_colors = {'selected': (0, 0, 1), 'locked': (0, 0, 1)}
    group = Group(name='Large and small cubes')
    _box(group.mesh, (0, 0, 0), (2, 2, 2))
    _box(group.mesh, (2, 0.75, 0.75), (2.75, 1.5, 1.5))
    if placement == 'nested':
        parent = Group(name='Container')
        parent.children = [group]
        group = parent
    if placement != 'plain':
        group.xform = QMatrix4x4()
        group.xform.translate(-1, 0.5, 0)
        group.xform.rotate(20, V(0, 0, 1))
    scene.groups.append(group)
    scene.version += 1
    vp.camera.set_view('iso')
    vp.camera.fit_to(V(-2, -1, -1), V(4, 4, 3))
    return group


def _live(vp):
    vp.update()
    QApplication.processEvents()
    image = vp.grabFramebuffer().convertToFormat(QImage.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), -1, 4).copy()


@pytest.mark.parametrize('placement', ['plain', 'transformed', 'nested'])
def test_lock_preserves_the_selected_edges_box_and_opaque_faces(cube_viewport, placement):
    vp = cube_viewport
    group = _scene(vp, placement)
    vp.scene.select([group])
    ordinary = _live(vp)
    History(vp.scene).execute(LockCommand([group]))
    vp.scene.select([group])
    locked = _live(vp)
    assert np.array_equal(ordinary, locked), 'Locking changed more than the selection color'


@pytest.mark.parametrize('locked', [False, True])
def test_visible_edges_inside_the_group_box_are_highlighted(cube_viewport, locked):
    vp = cube_viewport
    group = _scene(vp)
    group.locked = locked
    vp.scene.select([group])
    pixels = _live(vp)
    samples = 0
    for edge in group.mesh.edges:
        point = (edge.a + edge.b) * 0.5
        # Edges on the smaller cube, away from the overall bounding-box edges.
        if point.x() < 2.01 or vp._is_occluded(point):
            continue
        x, y = map(round, vp._world_to_pixel(point))
        patch = pixels[y - 2:y + 3, x - 2:x + 3, :3].astype(int)
        assert ((patch[:, :, 2] > patch[:, :, 0] + 80)
                & (patch[:, :, 2] > patch[:, :, 1] + 80)).any(), point
        samples += 1
    assert samples >= 2


def test_group_selection_is_absent_from_export_and_reuses_gpu_geometry(cube_viewport):
    vp = cube_viewport
    group = _scene(vp)
    def exported():
        image = vp.render_image(600, 400, overlays=False).convertToFormat(QImage.Format_RGBA8888)
        return bytes(image.constBits())
    baseline = exported()
    vp.scene.select([group])
    _live(vp)
    entries = {key: value['edges_vbo'] for key, value in vp._proto_draw.items()}
    group.locked = True
    vp.scene.select([group])
    _live(vp)
    assert {key: value['edges_vbo'] for key, value in vp._proto_draw.items()} == entries
    assert exported() == baseline


@pytest.mark.parametrize('change', ['clear', 'hide', 'delete'])
def test_red_inspection_disappears_when_no_longer_visible(cube_viewport, change):
    vp = cube_viewport
    group = _scene(vp)
    vp.scene.display_style.modeling_colors['locked'] = (1, 0, 0)
    group.locked = True
    vp.scene.select([group])
    def red_count():
        pixels = _live(vp)
        return ((pixels[:, :, 0] > 180) & (pixels[:, :, 1] < 80)
                & (pixels[:, :, 2] < 80)).sum()
    assert red_count() > 100
    if change == 'clear':
        vp.scene.clear_selection()
    elif change == 'hide':
        group.hidden = True
        vp.scene.version += 1
    else:
        vp.scene.groups.remove(group)
        vp.scene.version += 1
    assert red_count() == 0
