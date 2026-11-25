# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Locked inspection adds depth-tested edges without changing face opacity."""
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
def test_lock_preserves_opaque_face_interiors(cube_viewport, placement):
    vp = cube_viewport
    group = _scene(vp, placement)
    ordinary = _live(vp)
    History(vp.scene).execute(LockCommand([group]))
    vp.scene.select([group])
    locked = _live(vp)
    # Flat face interiors must keep their colour; edge pixels acquire the
    # inspection overlay. Ordinary selection keeps the release's own cues.
    rgb = ordinary[:, :, :3].astype(int)
    flat = np.ones(rgb.shape[:2], dtype=bool)
    for dy, dx in ((-3, 0), (3, 0), (0, -3), (0, 3)):
        flat &= abs(rgb - np.roll(rgb, (dy, dx), (0, 1))).max(axis=2) < 2
    flat &= (abs(rgb - rgb[0, 0])).max(axis=2) > 15
    assert flat.sum() > 1000
    changed = (abs(ordinary[flat].astype(int) - locked[flat].astype(int))).max(axis=1) > 2
    # A bounding-box line can cross a flat face; it must occupy less than
    # one percent of these interiors, rather than making a face translucent.
    assert changed.mean() < 0.01, (changed.sum(), flat.sum())


def test_visible_edges_inside_the_group_box_are_highlighted(cube_viewport):
    vp = cube_viewport
    group = _scene(vp)
    group.locked = True
    vp.scene.select([group])
    pixels = _live(vp)
    samples = 0
    for edge in group.mesh.edges:
        point = (edge.a + edge.b) * 0.5
        # Edges on the smaller cube, away from the overall bounding-box edges.
        if point.x() < 2.01 or vp._is_occluded(point):
            continue
        ratio = vp.devicePixelRatioF()
        x, y = (round(p * ratio) for p in vp._world_to_pixel(point))
        radius = max(2, round(2 * ratio))
        patch = pixels[y - radius:y + radius + 1,
                       x - radius:x + radius + 1, :3].astype(int)
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
    group.locked = True
    vp.scene.select([group])
    _live(vp)
    entries = {key: value['edges_vbo'] for key, value in vp._proto_draw.items()}
    vp.camera.orbit(2, 1, vp.height())
    _live(vp)
    assert {key: value['edges_vbo'] for key, value in vp._proto_draw.items()} == entries
    vp.scene.clear_selection()
    baseline = exported()
    vp.scene.select([group])
    assert exported() == baseline


def test_orbit_reuses_inspection_batches_boxes_and_gpu_upload(cube_viewport, monkeypatch):
    vp = cube_viewport
    group = _scene(vp)
    group.locked = True
    vp.scene.select([group])
    _live(vp)
    geometry = vp._locked_geometry_cache
    uploaded = vp._locked_box_uploaded
    def unexpected(*args, **kwargs):
        pytest.fail('Orbiting rebuilt the cached locked inspection')
    monkeypatch.setattr(vp, '_expand_placements', unexpected)
    monkeypatch.setattr(vp, '_group_obb', unexpected)
    for _ in range(3):
        vp.camera.orbit(2, 1, vp.height())
        _live(vp)
        assert vp._locked_geometry_cache is geometry
        assert vp._locked_box_uploaded is uploaded


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
