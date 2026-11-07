# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The face under the cursor is the plane the shape is built on (#545).

Marco, @pacaeiro: «se eu coloco o rato directamente na face diz (on face),
mas o plano permanece imutável» — the badge honoured the face and the
shape did not. A rectangle started on the top vertex of a 2 m cube, the
cursor held over a wall: the point came back 1.20 m off that wall, on the
horizontal plane through the vertex, and the second click built nothing
there. The status bar read «On face» all along, because the FACE was read
off the hover while the PLANE came from the axis inference — the camera
plane through the first corner. Three things, three answers.

A shape lives in ONE plane. With the cursor over a face, that face is the
plane: an edge or a vertex snap still wins (it comes off the face and
``snapped_plane`` re-plans the shape onto it), but the axis inference does
not get to answer with a plane the point is not on.

The iso view has its eye at (+X, −Y, +Z), so the faces in sight are
x = 2, y = 0 and z = 2, and each is asked in turn.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

from core.snap import face_plane_world

_app = QApplication.instance() or QApplication([])

SIZE = 2.0

# First corner at the CENTRE of another visible face — that is what froze the
# plane —, then the point and outward normal of the face the cursor moves on
# to. Centres on purpose: a metre from every edge, so no endpoint, midpoint or
# edge snap moves the corner (which would re-plan the shape by itself).
FACES = [
    ((2.0, 1.0, 1.0), (1.0, 0.0, 1.0), (0.0, -1.0, 0.0)),      # → y = 0, wall
    ((1.0, 0.0, 1.0), (2.0, 1.0, 1.0), (1.0, 0.0, 0.0)),       # → x = 2
    ((1.0, 0.0, 1.0), (1.0, 1.0, 2.0), (0.0, 0.0, 1.0)),       # → z = 2, top
]


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cube(scene):
    lo, hi = 0.0, SIZE
    p = [V(lo, lo, lo), V(hi, lo, lo), V(hi, hi, lo), V(lo, hi, lo),
         V(lo, lo, hi), V(hi, lo, hi), V(hi, hi, hi), V(lo, hi, hi)]
    for loop in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh = getattr(scene, "mesh", scene)
        mesh.add_face([p[i] for i in loop])


def _scene(grouped=False):
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    win.resize(1200, 800)
    _app.processEvents()
    vp = win.viewport
    if grouped:
        from core.group import Group
        from core.mesh import Mesh
        mesh = Mesh()
        _cube(mesh)
        vp.scene.groups.append(Group(mesh, "cubo"))
    else:
        _cube(vp.scene)
    vp.camera.set_view("iso")
    vp.scene.version += 1
    _app.processEvents()
    return win, vp


def _pixel(vp, world):
    px, py = vp._world_to_pixel(world)
    vp._last_mouse_pos = QPointF(px, py)
    vp._refresh_snap()
    return px, py


def _press(vp, px, py):
    vp._dispatch_tool_click(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(px, py),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


def _picked_plane(vp, px, py):
    """The plane of the face the viewport itself sees there — the test's
    guard that it is really asking about the face it means."""
    face, grp = vp.pick_face_any(px, py)
    assert face is not None, "no face under the cursor"
    point, normal = face_plane_world(face, getattr(grp, "xform", None))
    return QVector3D(point), QVector3D(normal).normalized()


def _off_plane(p, plane):
    point, normal = plane
    return abs(QVector3D.dotProduct(p - point, normal))


@pytest.mark.parametrize("start, hover, normal", FACES)
def test_the_rectangle_lands_on_the_face_it_is_drawn_over(start, hover, normal):
    win, vp = _scene()
    try:
        win._activate_tool("rectangle")
        _app.processEvents()
        plano = (V(*hover), V(*normal).normalized())
        _press(vp, *_pixel(vp, V(*start)))      # first corner, another face
        _app.processEvents()
        assert vp.active_tool.start_point is not None
        assert _off_plane(QVector3D(vp.active_tool.start_point), plano) > 0.5

        px, py = _pixel(vp, V(*hover))          # the cursor moves onto the face
        visto = _picked_plane(vp, px, py)
        assert QVector3D.dotProduct(visto[1], plano[1]) > 0.999, (
            "the test is asking about another face")
        snap = vp.inference.snap(px, py, Qt.NoModifier)
        assert snap is not None
        assert _off_plane(snap.point, plano) < 1e-3, (
            "the point offered is not on the face the cursor is over")
        drawn = vp.active_tool.drawing_plane()
        assert abs(QVector3D.dotProduct(
            QVector3D(drawn[1]).normalized(), plano[1])) > 0.999, (
                "the shape is being built on another plane")
        assert _off_plane(QVector3D(drawn[0]), plano) < 1e-3

        _press(vp, px, py)                      # second corner
        _app.processEvents()
        built = [f for f in vp.scene.mesh.faces
                 if f.area() > 0.05
                 and all(_off_plane(v, plano) < 1e-6 for v in f.vertices)]
        assert built, "nothing was built on the face"
    finally:
        win._saved_version = vp.scene.version
        win.close()


@pytest.mark.parametrize("grouped", [False, True], ids=["loose-face", "group"])
def test_a_selected_object_still_supplies_the_planar_tool_plane(grouped):
    win, vp = _scene(grouped=grouped)
    try:
        win._activate_tool("rectangle")
        _app.processEvents()
        _press(vp, *_pixel(vp, V(1.0, 1.0, 2.0)))
        _app.processEvents()

        px, py = vp._world_to_pixel(V(2.0, 1.0, 1.0))
        face, group = vp.pick_face_placement(px, py)
        assert face is not None
        vp.scene.selection.add(group if grouped else face)

        vp._last_mouse_pos = QPointF(px, py)
        vp._refresh_snap()
        plane = vp.active_tool.drawing_plane()
        assert abs(QVector3D.dotProduct(
            QVector3D(plane[1]).normalized(), V(1.0, 0.0, 0.0))) > 0.999
        assert abs(QVector3D.dotProduct(
            QVector3D(plane[0]) - V(2.0, 1.0, 1.0),
            V(1.0, 0.0, 0.0))) < 1e-3
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_circles_rim_follows_the_cursor_across_the_face():
    """#545's other half, the one the MAGNET did: the circle is drawn on the
    TOP face with its centre on that face, and the cursor then moves along
    the face in the direction the FACE CANNOT HOLD — over an axis-aligned
    face the screen magnet's own axis is the plane's normal (blue, straight
    up out of the top face). The magnet followed it, so the rim left the
    face while the radius was measured IN it: @pacaeiro watched the circle
    come out «a metade ou menos ainda». The rim must follow the cursor ON
    the face."""
    import math

    win, vp = _scene()
    try:
        win._activate_tool("circle")
        _app.processEvents()
        centro_px = V(1.0, 1.0, 2.0)            # the middle of the top face
        plano = (V(1.0, 1.0, 2.0), V(0.0, 0.0, 1.0))
        _press(vp, *_pixel(vp, centro_px))
        _app.processEvents()
        centro = QVector3D(vp.active_tool.start_point)
        assert centro is not None and _off_plane(centro, plano) < 0.05

        # A point of the face whose PIXEL sits on the screen image of the
        # world +Z line through the centre — the gesture that made the
        # screen magnet answer the face's own normal.
        # Half the reach: at 0.3 the point lands ~1.42 m out, on the cube's
        # corner in some window sizes, and the rim snaps to the corner.
        alvo = _cursor_on_the_blue_line(vp, centro, reach=0.15)
        assert alvo is not None
        px, py = _pixel(vp, alvo)
        visto = _picked_plane(vp, px, py)
        assert QVector3D.dotProduct(visto[1], plano[1]) > 0.999, (
            "the cursor must be over the top face, not off it")
        sx, sy = vp._world_to_pixel(centro)
        qx, qy = vp._world_to_pixel(centro + V(0.0, 0.0, 1.0))
        ux, uy = qx - sx, qy - sy
        assert math.hypot(ux, uy) > 12.0, "the blue axis is on its nose here"
        assert abs((px - sx) * uy - (py - sy) * ux) / math.hypot(ux, uy) <= 9.0, (
            "the test's cursor is not on the blue axis after all")

        snap = vp.inference.snap(px, py, Qt.NoModifier)
        assert snap is not None
        assert _off_plane(snap.point, plano) < 1e-3, (
            "the rim point is not on the face the cursor is over")

        _press(vp, px, py)                      # the radius
        _app.processEvents()
        radio = (QVector3D(snap.point) - centro).length()
        # The disc is the face with MANY vertices on the plane — the cube's
        # are quads. «Many» and not «more than N»: the circle is tessellated
        # around a dozen segments (12 with this radius), and a threshold
        # sitting on the tessellation itself turned the test red for a
        # millimetre of radius.
        disco = [f for f in vp.scene.mesh.faces
                 if len(f.vertices) >= 8
                 and all(_off_plane(v, plano) < 1e-6 for v in f.vertices)]
        assert disco, "the disc was not built in the face"
        # The rim followed the cursor: the disc has the radius the rim point
        # offered, not half of it, not twice.
        assert any(abs(f.area() - math.pi * radio * radio)
                   < 0.25 * math.pi * radio * radio for f in disco), (
            "the disc does not have the radius the rim point offered")
    finally:
        win._saved_version = vp.scene.version
        win.close()


def _cursor_on_the_blue_line(vp, centre, reach=0.3):
    """A point of the horizontal plane through ``centre`` whose PIXEL lies on
    the screen image of the world +Z line through it.

    The view's map is projective, so the point is solved with the viewport's
    own ``_world_to_pixel``: two in-plane probes give how the plane's two
    world directions move the pixel, and the combination whose image runs
    along the blue axis comes out of those."""
    import math

    p0 = vp._world_to_pixel(centre)
    pz = vp._world_to_pixel(centre + V(0.0, 0.0, 1.0))
    ex = vp._world_to_pixel(centre + V(1.0, 0.0, 0.0))
    ey = vp._world_to_pixel(centre + V(0.0, 1.0, 0.0))
    dx, dy = pz[0] - p0[0], pz[1] - p0[1]
    if math.hypot(dx, dy) < 1e-6:
        return None
    tx, ty = dx * reach, dy * reach            # the blue axis, ``reach`` out
    ax, ay = ex[0] - p0[0], ex[1] - p0[1]
    bx, by = ey[0] - p0[0], ey[1] - p0[1]
    det = ax * by - ay * bx
    if abs(det) < 1e-9:
        return None
    a = (tx * by - ty * bx) / det
    b = (ax * ty - ay * tx) / det
    return centre + V(a, b, 0.0)


def test_an_arrow_lock_holds_the_plane_against_the_face_under_the_cursor():
    """#545's other half: the face wins when NOTHING was asked for. With an
    arrow answering, the plane asked for is the plane the shape is on — and
    it is anchored at the first point, where the shape stands, so the face
    under the cursor does not take it over (``_planar_face_plane`` yields to
    a lock)."""
    win, vp = _scene()
    try:
        win._activate_tool("rectangle")
        _app.processEvents()
        _press(vp, *_pixel(vp, V(1.0, 1.0, 2.0)))       # a corner on the top face
        _app.processEvents()
        assert vp.active_tool.start_point is not None
        # The arrow asks for the YZ plane through that corner (x = 1); the
        # face about to be under the cursor is the wall x = 2.
        assert vp.active_tool.on_key(vp, int(Qt.Key_Right), Qt.NoModifier)
        assert vp.active_tool.plane_lock == "x"
        px, py = _pixel(vp, V(2.0, 1.0, 1.0))           # onto the wall
        visto = _picked_plane(vp, px, py)
        assert QVector3D.dotProduct(visto[1], V(1.0, 0.0, 0.0)) > 0.999, (
            "the test is asking about another face")
        drawn = vp.active_tool.drawing_plane()
        assert abs(QVector3D.dotProduct(
            QVector3D(drawn[1]).normalized(), V(1.0, 0.0, 0.0))) > 0.999, (
                "the face under the cursor took the locked plane over")
        assert (QVector3D(drawn[0])
                - QVector3D(vp.active_tool.start_point)).length() < 1e-6, (
            "the locked plane is not the one through the first point")
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_shift_marks_the_plane_the_shape_is_on_and_gives_it_back():
    """Marco's gesture: «marca o plano que está a ser considerado, por
    exemplo uma face num cubo». Shift is Down HELD: the plane the shape is
    on stays put while the key is down (the cursor may wander over another
    face) and the release hands it back to the cursor."""
    win, vp = _scene()
    try:
        win._activate_tool("rectangle")
        _app.processEvents()
        tool = vp.active_tool
        _press(vp, *_pixel(vp, V(1.0, 1.0, 2.0)))       # a corner on the top face
        _app.processEvents()
        _pixel(vp, V(2.0, 1.0, 1.0))                    # the cursor onto the x = 2 wall
        face = tool.drawing_plane()
        assert abs(QVector3D.dotProduct(
            QVector3D(face[1]).normalized(), V(1.0, 0.0, 0.0))) > 0.999, (
                "the wall under the cursor is not the plane (#545)")

        vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Shift,
                                   Qt.ShiftModifier))
        assert tool.plane_ref is not None and tool.plane_ref[1] == "plane"
        assert abs(QVector3D.dotProduct(
            QVector3D(tool.plane_ref[0]).normalized(), V(1.0, 0.0, 0.0))) > 0.999

        _pixel(vp, V(1.0, 1.0, 2.0))                    # the cursor onto the top face
        held = tool.drawing_plane()
        assert abs(QVector3D.dotProduct(
            QVector3D(held[1]).normalized(), V(1.0, 0.0, 0.0))) > 0.999, (
                "the marked plane let the cursor take it away")
        assert (QVector3D(held[0]) - QVector3D(face[0])).length() < 1e-9

        vp.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Shift,
                                     Qt.NoModifier))
        assert tool.plane_ref is None
        freed = tool.drawing_plane()                    # the face answers again
        assert abs(QVector3D.dotProduct(
            QVector3D(freed[1]).normalized(), V(0.0, 0.0, 1.0))) > 0.999, (
                "the release did not hand the plane back")
    finally:
        win._saved_version = vp.scene.version
        win.close()
