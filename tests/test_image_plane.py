# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Reference images: import a scan, size it, trace over it, save it with the
document. The invariant under all of it — an image is reference, never
geometry, so it must never reach the topology mesh."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage, QVector3D

from core.history import (
    AddImagePlaneCommand,
    DeleteImagePlanesCommand,
    History,
    TransformImagePlaneCommand,
)
from core.image_plane import IMAGE_LAYER, ImagePlane, image_aspect
from core.scene import Scene


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def _png(tmp_path: Path, w: int = 200, h: int = 100) -> Path:
    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(QColor(220, 40, 40))
    out = tmp_path / "plan.png"
    img.save(str(out))
    return out


def _image(path="scan.png", width=4.0, height=3.0) -> ImagePlane:
    return ImagePlane(path, V(0, 0), V(width, 0), V(0, height),
                      aspect=height / width)


# ---- Geometry ---------------------------------------------------------------
def test_corners_run_counter_clockwise_from_the_origin():
    im = _image()
    c = im.corners()
    assert [tuple(p.toTuple()) for p in c] == [
        (0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (4.0, 3.0, 0.0), (0.0, 3.0, 0.0)]
    assert im.width() == 4.0 and im.height() == 3.0


def test_normal_and_plane_follow_the_edge_vectors():
    # An image stood up on the XZ plane must report a horizontal normal, so
    # drawing on it lands on the wall and not on the ground.
    im = ImagePlane("s.png", V(0, 0), V(2, 0, 0), V(0, 0, 2))
    assert im.normal().y() == -1.0
    point, normal = im.plane()
    assert point == V(1, 0, 1) and normal == im.normal()


def test_project_maps_the_rectangle_to_unit_fractions():
    im = _image()
    assert im.project(im.origin) == (0.0, 0.0)
    assert im.project(im.center()) == (0.5, 0.5)
    assert im.contains_uv(*im.project(V(2, 1)))
    assert not im.contains_uv(*im.project(V(9, 1)))


def test_border_edges_close_the_loop():
    edges = _image().border_edges()
    assert len(edges) == 4
    assert edges[-1][1] == edges[0][0]


# ---- Scaling ----------------------------------------------------------------
def test_scaling_keeps_the_picture_undistorted():
    im = _image(width=4.0, height=3.0)          # aspect 0.75
    u, v = im.scaled(8.0)
    assert u.length() == 8.0
    assert abs(v.length() - 6.0) < 1e-9         # height follows the aspect


def test_scaling_without_the_aspect_lock_leaves_the_height_alone():
    im = _image(width=4.0, height=3.0)
    u, v = im.scaled(8.0, keep_aspect=False)
    assert u.length() == 8.0 and v.length() == 3.0


def test_scaling_is_a_no_op_on_a_degenerate_or_negative_request():
    im = _image()
    assert im.scaled(0.0)[0].length() == 4.0
    assert im.scaled(-3.0)[0].length() == 4.0


# ---- Commands ---------------------------------------------------------------
def test_add_lands_on_its_own_layer_and_undo_takes_the_layer_back():
    scene, hist = Scene(), History(Scene())
    hist = History(scene)
    im = _image()
    hist.execute(AddImagePlaneCommand(im))
    assert scene.image_planes == [im]
    assert scene.layer(IMAGE_LAYER) is not None
    assert im in scene.selection
    hist.undo()
    assert scene.image_planes == []
    assert scene.layer(IMAGE_LAYER) is None      # the import left no residue


def test_add_undo_keeps_a_layer_the_document_already_had():
    scene = Scene()
    from core.layers import Layer
    scene.layers.append(Layer(IMAGE_LAYER))
    hist = History(scene)
    hist.execute(AddImagePlaneCommand(_image()))
    hist.undo()
    assert scene.layer(IMAGE_LAYER) is not None


def test_transform_round_trips_through_undo_and_redo():
    scene = Scene()
    hist = History(scene)
    im = _image()
    hist.execute(AddImagePlaneCommand(im))
    hist.execute(TransformImagePlaneCommand(im, *((None,) + im.scaled(8.0))))
    assert (im.width(), im.height()) == (8.0, 6.0)
    hist.undo()
    assert (im.width(), im.height()) == (4.0, 3.0)
    hist.redo()
    assert (im.width(), im.height()) == (8.0, 6.0)


def test_delete_restores_stacking_order_on_undo():
    scene = Scene()
    hist = History(scene)
    a, b, c = _image("a.png"), _image("b.png"), _image("c.png")
    for im in (a, b, c):
        hist.execute(AddImagePlaneCommand(im))
    hist.execute(DeleteImagePlanesCommand([b]))
    assert scene.image_planes == [a, c]
    hist.undo()
    assert scene.image_planes == [a, b, c]       # b is back in the middle


def test_an_image_never_reaches_the_topology_mesh():
    """Invariant #4: reference is not geometry."""
    scene = Scene()
    hist = History(scene)
    hist.execute(AddImagePlaneCommand(_image()))
    assert scene.mesh.faces == [] and scene.mesh.edges == []
    assert scene.bounds() == (None, None)


def test_clear_wipes_the_images():
    scene = Scene()
    scene.image_planes.append(_image())
    scene.clear()
    assert scene.image_planes == []


# ---- The file itself --------------------------------------------------------
def test_image_aspect_reads_the_header(tmp_path):
    aspect, w, h = image_aspect(_png(tmp_path, 200, 100))
    assert (aspect, w, h) == (0.5, 200, 100)


def test_image_aspect_survives_a_file_it_cannot_read(tmp_path):
    bogus = tmp_path / "not-a-picture.png"
    bogus.write_bytes(b"nope")
    assert image_aspect(bogus) == (1.0, 0, 0)


def test_document_carries_the_picture_inside_it(tmp_path):
    """The point of embedding: the model must still show the scan after the
    file it was imported from is gone."""
    from formats.igz import load_into, save_scene

    src = _png(tmp_path)
    aspect, _, _ = image_aspect(src)
    scene = Scene()
    scene.image_planes.append(
        ImagePlane(str(src), V(1, 2), V(8, 0), V(0, 4), aspect=aspect,
                   name="plan"))
    doc = tmp_path / "model.igz"
    save_scene(scene, doc)
    src.unlink()                                 # the original is gone

    loaded = Scene()
    load_into(loaded, doc)
    im = loaded.image_planes[0]
    assert im.name == "plan"
    assert (im.width(), im.height()) == (8.0, 4.0)
    assert im.aspect == aspect
    assert Path(im.path).exists()                # restored from the document
    assert not QImage(im.path).isNull()


def test_a_document_without_images_loads_clean(tmp_path):
    from formats.igz import load_into, save_scene

    doc = tmp_path / "empty.igz"
    save_scene(Scene(), doc)
    loaded = Scene()
    loaded.image_planes.append(_image())         # stale state must be cleared
    load_into(loaded, doc)
    assert loaded.image_planes == []


# ---- Placement tool ---------------------------------------------------------
def test_the_drag_sets_the_width_and_the_aspect_sets_the_height():
    from tools.image import ImageTool

    tool = ImageTool()
    tool.load("scan.png", aspect=0.5)
    tool.start_point, tool.hover_point = V(0, 0), V(10, 2)
    u, v = tool._frame(tool.start_point, tool.hover_point)
    assert u.length() == 10.0
    assert abs(v.length() - 5.0) < 1e-9          # 10 × 0.5, not the 2 dragged


def test_shift_releases_the_aspect_lock():
    from tools.image import ImageTool

    tool = ImageTool()
    tool.load("scan.png", aspect=0.5)
    tool._free_aspect = True
    u, v = tool._frame(V(0, 0), V(10, 2))
    assert (u.length(), v.length()) == (10.0, 2.0)


def test_the_preview_is_the_four_sides_of_the_picture():
    from tools.image import ImageTool

    tool = ImageTool()
    tool.load("scan.png", aspect=0.5)
    tool.start_point, tool.hover_point = V(0, 0), V(4, 1)
    assert len(tool.rubber_band_lines()) == 4
    assert "×" in tool.value_label()[0]


def test_an_unarmed_tool_places_nothing():
    from tools.image import ImageTool

    tool = ImageTool()
    assert not tool.armed
    assert tool.rubber_band_lines() == []
    assert tool.value_label() is None


# ---- Move / Rotate / Scale --------------------------------------------------
def test_move_shifts_the_corner_and_nothing_else():
    from core.history import MoveImagePlanesCommand

    scene = Scene()
    hist = History(scene)
    im = _image()
    hist.execute(AddImagePlaneCommand(im))
    hist.execute(MoveImagePlanesCommand([im], V(5, 5, 2)))
    assert im.origin == V(5, 5, 2)
    assert (im.width(), im.height()) == (4.0, 3.0)      # size untouched
    hist.undo()
    assert im.origin == V(0, 0, 0)


def test_rotate_turns_the_picture_without_resizing_it():
    from core.history import RotateImagePlanesCommand

    scene = Scene()
    hist = History(scene)
    im = _image()
    hist.execute(AddImagePlaneCommand(im))
    hist.execute(RotateImagePlanesCommand([im], im.center(), V(0, 0, 1), 90.0))
    assert abs(im.width() - 4.0) < 1e-6
    assert abs(im.height() - 3.0) < 1e-6
    assert abs(im.u.y() - 4.0) < 1e-6                   # u now runs along +Y
    hist.undo()
    assert abs(im.u.x() - 4.0) < 1e-6


def test_rotate_about_a_horizontal_axis_stands_the_picture_up():
    """A facade photo lying on the ground, tipped onto a wall."""
    from core.history import RotateImagePlanesCommand

    scene = Scene()
    hist = History(scene)
    im = _image()
    hist.execute(AddImagePlaneCommand(im))
    assert abs(im.normal().z()) == 1.0                  # flat
    hist.execute(RotateImagePlanesCommand([im], im.origin, V(1, 0, 0), 90.0))
    assert abs(im.normal().z()) < 1e-6                  # vertical now
    assert abs(im.height() - 3.0) < 1e-6                # and the same size


def test_scale_keeps_the_picture_undistorted():
    from core.history import ScaleImagePlanesCommand

    scene = Scene()
    hist = History(scene)
    im = _image(width=4.0, height=3.0)
    hist.execute(AddImagePlaneCommand(im))
    hist.execute(ScaleImagePlanesCommand([im], im.origin, 2.5))
    assert abs(im.width() - 10.0) < 1e-6
    assert abs(im.height() - 7.5) < 1e-6
    assert abs(im.height() / im.width() - 0.75) < 1e-9  # proportions held
    hist.undo()
    assert abs(im.width() - 4.0) < 1e-6


def test_scale_moves_the_image_relative_to_its_anchor():
    from core.history import ScaleImagePlanesCommand

    scene = Scene()
    hist = History(scene)
    im = ImagePlane("s.png", V(2, 0), V(4, 0), V(0, 3))
    hist.execute(AddImagePlaneCommand(im))
    hist.execute(ScaleImagePlanesCommand([im], V(0, 0), 2.0))
    assert im.origin == V(4, 0, 0)                      # anchor at the origin
    hist.undo()
    assert im.origin == V(2, 0, 0)


def test_a_degenerate_scale_undo_is_a_no_op_instead_of_a_crash():
    from core.history import ScaleImagePlanesCommand

    scene = Scene()
    im = _image()
    scene.image_planes.append(im)
    cmd = ScaleImagePlanesCommand([im], V(0, 0), 0.0)
    cmd.do(scene)
    cmd.undo(scene)                                     # must not divide by 0


# ---- What the transform tools grab -----------------------------------------
class _StubViewport:
    """Enough viewport for ``gather_images``: a scene and a pick that answers
    with whatever the test put under the cursor."""

    def __init__(self, scene, under_cursor=None, locked=False):
        self.scene = scene
        self._hit = under_cursor
        self._locked = locked

    def pick_image_plane(self, x, y):
        if self._hit is None or self._locked:
            return None                                  # locked = not pickable
        return self._hit


class _StubCtx:
    def __init__(self, viewport):
        self.viewport = viewport

        class _P:
            def x(self_inner): return 10.0
            def y(self_inner): return 10.0
        self.screen = _P()


def test_transform_tools_grab_the_selected_images():
    from tools.move import gather_images

    scene = Scene()
    a, b = _image("a.png"), _image("b.png")
    scene.image_planes += [a, b]
    scene.selection.add(a)
    assert gather_images(_StubCtx(_StubViewport(scene))) == [a]


def test_transform_tools_grab_the_image_under_the_cursor_when_nothing_is_selected():
    from tools.move import gather_images

    scene = Scene()
    im = _image()
    scene.image_planes.append(im)
    ctx = _StubCtx(_StubViewport(scene, under_cursor=im))
    assert gather_images(ctx) == [im]


def test_a_locked_image_is_never_grabbed_by_a_transform_tool():
    from tools.move import gather_images

    scene = Scene()
    im = _image()
    im.locked = True
    scene.image_planes.append(im)
    ctx = _StubCtx(_StubViewport(scene, under_cursor=im, locked=True))
    assert gather_images(ctx) == []


def test_a_selection_of_geometry_does_not_drag_images_along():
    from tools.move import gather_images

    scene = Scene()
    im = _image()
    scene.image_planes.append(im)
    face = scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    scene.selection.add(face)
    # Something IS selected, and it is not the image — the hover fallback
    # must stay off, or moving a face would carry the scan with it.
    ctx = _StubCtx(_StubViewport(scene, under_cursor=im))
    assert gather_images(ctx) == []
