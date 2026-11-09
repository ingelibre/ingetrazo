"""A click on loose geometry does not select a group whose edge is hidden
behind it.

When the cursor ray hit a loose face and no face of any group, the pick fell
back to «the group edge nearest on screen», visible or not — so a click on a
loose box standing on a slab group, a few pixels from the slab's far edge
behind the box, selected the slab instead of the box.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.group import Group  # noqa: E402
from core.mesh import Face, Mesh  # noqa: E402
from tools.select import SelectTool  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _box(m, x0, y0, z0, x1, y1, z1):
    for lp in ([V(x0, y0, z0), V(x0, y1, z0), V(x1, y1, z0), V(x1, y0, z0)],
               [V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)],
               [V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)],
               [V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)],
               [V(x1, y1, z0), V(x0, y1, z0), V(x0, y1, z1), V(x1, y1, z1)],
               [V(x0, y1, z0), V(x0, y0, z0), V(x0, y0, z1), V(x0, y1, z1)]):
        m.add_face(lp)


def _vp():
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


def _slab_scene():
    """A slab group with two loose boxes on it, as in the report: a low
    wide one and a tall one at the back corner."""
    vp = _vp()
    m = Mesh()
    _box(m, 0, 0, 0, 8, 5, 0.4)
    slab = Group(m, "losa")
    vp.scene.groups.append(slab)
    _box(vp.scene.mesh, 0.6, 0.3, 0.4, 6, 2.4, 1.0)
    _box(vp.scene.mesh, 0, 3.0, 0.0, 1.6, 5.0, 3.0)
    vp.scene.version += 1
    vp.camera.target = V(4, 2.5, 0.5)
    vp.camera.distance = 16
    return vp, slab


def test_a_click_on_a_loose_box_never_selects_the_slab_behind_it():
    vp, slab = _slab_scene()
    tool = SelectTool()
    checked = 0
    for sx in range(0, 1000, 8):
        for sy in range(0, 700, 8):
            face, owner = vp.pick_face_any(sx, sy)
            if face is None or owner is not None:
                continue                    # not over a loose face
            checked += 1
            assert tool._pick(vp, sx, sy) is not slab, \
                f"({sx}, {sy}) is on a loose box but picked the slab"
    assert checked > 100


def test_the_slab_s_visible_outline_still_picks_the_slab():
    vp, slab = _slab_scene()
    # Just below the slab's front bottom edge: the ray meets nothing, the
    # edge is in plain sight a few pixels away.
    x, y = vp._world_to_pixel(V(7, 0, 0))
    y += 3
    assert vp.pick_face_any(x, y) == (None, None)
    assert vp.pick_group(x, y) is slab
    assert SelectTool()._pick(vp, x, y) is slab


def _lines_group_under_lid(vp):
    """A lines-only group (a square of edges at z = 0) and a loose lid at
    z = 1 covering half of it, seen from the top."""
    vp.camera.set_view("top")
    vp.camera.target = V(3, 3, 0)
    vp.camera.distance = 12
    m = Mesh()
    pts = [V(0, 0), V(6, 0), V(6, 6), V(0, 6)]
    for i in range(4):
        m.add_edge(pts[i], pts[(i + 1) % 4])
    lines = Group(m, "líneas")
    vp.scene.groups.append(lines)
    lid = vp.scene.mesh.add_face([V(-1, -1, 1), V(3, -1, 1), V(3, 7, 1),
                                  V(-1, 7, 1)])
    vp.scene.version += 1
    return lines, lid


def test_a_lines_only_group_under_a_loose_face_is_not_picked_through_it():
    vp = _vp()
    lines, lid = _lines_group_under_lid(vp)
    covered = vp._world_to_pixel(V(0, 3, 0))      # under the lid
    assert vp.pick_group(*covered) is None
    picked = SelectTool()._pick(vp, *covered)
    assert isinstance(picked, Face) and picked is lid
    open_ = vp._world_to_pixel(V(6, 3, 0))        # beyond the lid
    assert vp.pick_group(*open_) is lines


def test_x_ray_still_picks_the_edge_through_the_face():
    """X-ray shows everything, so a hidden edge is a visible one there."""
    vp = _vp()
    lines, _ = _lines_group_under_lid(vp)
    vp._effective_style = lambda: type("S", (), {"face_mode": "xray"})()
    covered = vp._world_to_pixel(V(0, 3, 0))
    assert vp.pick_group(*covered) is lines
