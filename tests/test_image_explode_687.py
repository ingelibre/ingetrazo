# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An imported image can become a material and geometry (#687,
@alexanderpavel85-alt: «no permite usarla como textura», «el gotero no da la
opción de seleccionarla», «no encontré la opción para explotarla»).

A reference image is a tracing underlay on purpose, but nothing led from it
to the model: Explode Image now turns it into a group holding one face
textured with the picture where the image was, and the eyedropper over an
image takes its picture as the current paint, mapped where it sits."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group  # noqa: E402
from core.history import AddImagePlaneCommand, History  # noqa: E402
from core.image_plane import IMAGE_LAYER, ImagePlane  # noqa: E402
from core.scene import Scene  # noqa: E402
from tools.base import ToolContext  # noqa: E402
from tools.paint import PaintTool  # noqa: E402


def _uv(uvw, p):
    return (uvw[0] * p.x() + uvw[1] * p.y() + uvw[2] * p.z() + uvw[3],
            uvw[4] * p.x() + uvw[5] * p.y() + uvw[6] * p.z() + uvw[7])


def _facade():
    """A 4 m × 3 m photo standing on the XZ plane, 2 m off the origin."""
    return ImagePlane("/scans/fachada.png", V(1, 2, 0), V(4, 0, 0),
                      V(0, 0, 3), aspect=0.75, name="fachada", opacity=0.6)


def test_the_exploded_face_shows_the_picture_where_the_image_was():
    image = _facade()
    group = image.as_group()
    assert isinstance(group, Group) and group.name == "fachada"
    assert group.layer == IMAGE_LAYER and group.xform is None
    [face] = group.mesh.faces
    assert [v.position for v in face.loop] == image.corners()
    # The image's front stays the face's front.
    assert (face.normal() - image.normal()).length() < 1e-6
    tex = face.attrs["texture"]
    assert tex["path"] == "/scans/fachada.png"
    assert (tex["sw"], tex["sh"]) == (4.0, 3.0)
    # The whole picture once, with (0, 0) at the origin corner — how the
    # image itself is drawn.
    for corner, want in zip(image.corners(),
                            [(0, 0), (1, 0), (1, 1), (0, 1)]):
        got = _uv(tex["uvw"], corner)
        assert got == pytest.approx(want, abs=1e-6)
    assert face.attrs["back"] is True           # seen from both sides
    assert face.attrs["opacity"] == pytest.approx(0.6)


def test_a_flat_image_explodes_to_nothing():
    flat = ImagePlane("/x.png", V(0, 0, 0), V(1, 0, 0), V(2, 0, 0))
    assert flat.as_group() is None


def test_explode_image_is_one_undo_step():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scene = vp.scene
        image = _facade()
        vp.history.execute(AddImagePlaneCommand(image))
        assert scene.selection == {image}
        before = len(scene.groups)
        win._on_explode_image()
        assert image not in scene.image_planes
        [group] = scene.groups[before:]
        assert scene.selection == {group}
        assert group.mesh.faces[0].attrs["texture"]["path"] == image.path
        assert vp.history.undo()
        assert image in scene.image_planes
        assert group not in scene.groups
        # Explode on a selected image (the Explode key) explodes it too.
        scene.selection.clear()
        scene.selection.add(image)
        win._on_explode_group()
        assert image not in scene.image_planes
        assert len(scene.groups) == before + 1
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


class _Viewport:
    """Just enough viewport for the eyedropper: no face under the cursor,
    and a chosen image there (GL picking needs a real display)."""

    def __init__(self, image, face=None, in_front=None):
        self.scene = Scene()
        self.history = History(self.scene)
        self._image, self._face, self._front = image, face, in_front

    def pick_face_any(self, _x, _y):
        return self._face, None

    def image_plane_at(self, _x, _y):
        return self._image

    def image_in_front_of(self, _face, _x, _y):
        return self._front

    def update(self):
        pass

    def set_hover(self, _f):
        pass


def _click(vp, modifiers=Qt.AltModifier):
    PaintTool().on_click(ToolContext(viewport=vp, world=V(),
                                     screen=QPointF(0, 0),
                                     modifiers=modifiers, snap=None))


@pytest.fixture(autouse=True)
def _reset_paint_state():
    yield
    PaintTool.current_material = None
    PaintTool.current_texture = None
    PaintTool.current_texture_plane = None
    PaintTool.current_opacity = None
    PaintTool.current_is_default = False
    PaintTool.current_color = (0.80, 0.45, 0.30)


def test_the_eyedropper_samples_an_image_and_paints_it_in_place():
    image = _facade()
    vp = _Viewport(image)
    _click(vp)
    tex = PaintTool.current_texture
    assert tex["path"] == image.path and tex["uvw"]
    assert PaintTool.current_opacity == pytest.approx(0.6)
    # A face drawn over the image, on its plane, takes the picture exactly
    # under it.
    face = vp.scene.mesh.add_face([V(2, 2, 1), V(3, 2, 1), V(3, 2, 2),
                                   V(2, 2, 2)])
    vp._face, vp._image = face, None
    _click(vp, modifiers=Qt.NoModifier)
    painted = face.attrs["texture"]
    assert painted["path"] == image.path
    assert _uv(painted["uvw"], V(2, 2, 1)) == pytest.approx((0.25, 1 / 3))


def test_an_image_behind_the_face_is_not_sampled():
    image = _facade()
    vp = Scene()
    face = vp.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    face.attrs["color"] = (0.1, 0.2, 0.3)
    view = _Viewport(image, face=face, in_front=None)
    view.scene = vp
    view.history = History(vp)
    _click(view)
    assert PaintTool.current_texture is None
    assert PaintTool.current_color == (0.1, 0.2, 0.3)
