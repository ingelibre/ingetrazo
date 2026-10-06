# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Position Texture — the classic fixed pins (Rafael's review of 2026-09-10,
C1: «no encontré manera de cambiar la escala a la textura»).

The pins sit on the corners of the tile under the click; red drags the
texture, green scales and rotates about red, blue scales and shears with
red and green held; a click lifts a pin and the next click sets it down
without touching the texture. Done writes the face's world→UV affine map
as one undo step; Esc restores first and leaves second.
"""
from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

from core.edits import build_add_edges
from core.texture import face_uv_axes
from tools.base import ToolContext
from tools.texture_position import (PIN_MOVE, PIN_SCALE_ROTATE,
                                    PIN_SCALE_SHEAR, TexturePositionTool)


@pytest.fixture(scope="module")
def viewport():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.viewport import Viewport
    vp = Viewport(None)
    vp.resize(1000, 700)
    vp.camera.set_aspect(1000, 700)
    vp.flash_status = lambda *a, **k: None
    return vp


TEX = {"path": "brick.png", "sw": 0.5, "sh": 0.5}


def _textured_square(vp):
    vp.scene.mesh.clear()
    vp.history.undo_stack.clear()
    vp.history.redo_stack.clear()
    sq = [QVector3D(0, 0, 0), QVector3D(2, 0, 0),
          QVector3D(2, 2, 0), QVector3D(0, 2, 0)]
    vp.history.execute(build_add_edges(
        vp.scene, [(sq[i], sq[(i + 1) % 4]) for i in range(4)]))
    face = vp.scene.mesh.faces[0]
    if face.normal().z() < 0:
        face.loop.reverse()                      # look up: U runs along +X
    face.attrs["texture"] = dict(TEX)
    vp.camera.target = QVector3D(1, 1, 0)
    vp.camera.distance = 6.0
    vp.camera.pitch = math.radians(-80.0)
    return face


def _ctx(vp, world, modifiers=Qt.NoModifier):
    world = QVector3D(*world) if isinstance(world, tuple) else QVector3D(world)
    px = vp._world_to_pixel(world)
    assert px is not None
    return ToolContext(viewport=vp, world=world, screen=QPointF(*px),
                       modifiers=modifiers, snap=None)


def _begin(vp, face, at=(0.7, 0.3, 0)):
    tool = TexturePositionTool()
    vp.set_active_tool(tool)
    assert tool.begin(vp, face, QVector3D(*at))
    return tool


def _drag(vp, tool, start, end):
    tool.on_click(_ctx(vp, start))
    tool.on_hover(_ctx(vp, end))
    tool.on_release(vp)


def _uv(tool, p):
    tex = tool.result_texture()
    gu, cu, gv, cv = face_uv_axes(tex, tool.face.normal())
    p = QVector3D(*p)
    return (QVector3D.dotProduct(gu, p) + cu, QVector3D.dotProduct(gv, p) + cv)


def _close(a, b, tol=1e-3):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_pins_start_on_the_tile_under_the_click(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face, at=(0.7, 0.3, 0))
    pins = tool.pins()
    # 0.5 m tiles: the tile under (0.7, 0.3) spans u∈[1,2], v∈[0,1].
    assert _close(pins[PIN_MOVE].toTuple(), (0.5, 0.0, 0.0))
    assert _close(pins[PIN_SCALE_ROTATE].toTuple(), (1.0, 0.0, 0.0))
    assert _close(pins[PIN_SCALE_SHEAR].toTuple(), (0.5, 0.5, 0.0))
    assert _close(pins[3].toTuple(), (1.0, 0.5, 0.0))
    assert tool.pin_uv[PIN_MOVE] == (1.0, 0.0)
    assert not tool.changed()
    assert tool.result_texture()["path"] == "brick.png"
    assert face in viewport._suppressed_faces


def test_the_red_pin_moves_the_texture_without_scaling_it(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    _drag(viewport, tool, (0.5, 0, 0), (0.8, 0.2, 0))
    assert tool.changed()
    assert _close(_uv(tool, (0.8, 0.2, 0)), (1.0, 0.0))
    assert _close(_uv(tool, (1.3, 0.2, 0)), (2.0, 0.0))      # still 0.5 m tiles
    assert _close(_uv(tool, (0.8, 0.7, 0)), (1.0, 1.0))
    # Dragging the texture body does the same.
    _drag(viewport, tool, (1.5, 1.5, 0), (1.6, 1.5, 0))
    assert _close(_uv(tool, (0.9, 0.2, 0)), (1.0, 0.0))
    assert len(tool._undo) == 2


def test_the_green_pin_scales_and_rotates_about_the_red_one(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    # Twice as far from red: the tile doubles to 1 m.
    _drag(viewport, tool, (1.0, 0, 0), (1.5, 0, 0))
    assert _close(_uv(tool, (0.5, 0, 0)), (1.0, 0.0))        # red stays
    assert _close(_uv(tool, (1.5, 0, 0)), (2.0, 0.0))
    assert _close(_uv(tool, (0.5, 1.0, 0)), (1.0, 1.0))      # uniform
    # A quarter turn: green goes above red at the same distance.
    _drag(viewport, tool, (1.5, 0, 0), (0.5, 1.0, 0))
    assert _close(_uv(tool, (0.5, 1.0, 0)), (2.0, 0.0))
    assert _close(_uv(tool, (-0.5, 0.0, 0)), (1.0, 1.0))     # V turned with it


def test_the_blue_pin_scales_vertically_and_shears(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    _drag(viewport, tool, (0.5, 0.5, 0), (0.75, 1.0, 0))
    assert _close(_uv(tool, (0.5, 0, 0)), (1.0, 0.0))        # red stays
    assert _close(_uv(tool, (1.0, 0, 0)), (2.0, 0.0))        # green stays
    assert _close(_uv(tool, (0.75, 1.0, 0)), (1.0, 1.0))     # blue landed


def test_a_click_lifts_a_pin_and_the_next_click_sets_it_down(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    tool.on_click(_ctx(viewport, (0.5, 0, 0)))
    tool.on_release(viewport)                     # no motion: a click
    assert tool._lifted == PIN_MOVE
    tool.on_hover(_ctx(viewport, (0.0, 0.0, 0)))
    assert _close(tool.pins()[PIN_MOVE].toTuple(), (0.0, 0.0, 0.0))
    tool.on_click(_ctx(viewport, (0.0, 0.0, 0)))  # set it down on the corner
    assert tool._lifted is None
    assert not tool.changed()                     # the texture did not move
    assert _close(tool.pin_uv[PIN_MOVE], (0.0, 0.0))
    # Scaling now pivots on the corner: green to (2, 0) → 1 m tiles from 0.
    _drag(viewport, tool, (1.0, 0, 0), (2.0, 0, 0))
    assert _close(_uv(tool, (0.0, 0, 0)), (0.0, 0.0))
    assert _close(_uv(tool, (2.0, 0, 0)), (2.0, 0.0))


def test_done_writes_one_undoable_map_and_esc_restores_then_leaves(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    _drag(viewport, tool, (0.5, 0, 0), (0.8, 0.2, 0))
    depth = len(viewport.history.undo_stack)
    assert tool.on_key(viewport, Qt.Key_Return, Qt.NoModifier)
    assert tool.face is None                      # left the tool
    assert not viewport._suppressed_faces
    assert len(viewport.history.undo_stack) == depth + 1
    uvw = face.attrs["texture"]["uvw"]
    gu, cu, gv, cv = face_uv_axes(face.attrs["texture"], face.normal())
    p = QVector3D(0.8, 0.2, 0)
    assert abs(QVector3D.dotProduct(gu, p) + cu - 1.0) < 1e-3
    assert abs(QVector3D.dotProduct(gv, p) + cv - 0.0) < 1e-3
    assert len(uvw) == 8
    viewport.history.undo()
    assert "uvw" not in face.attrs["texture"]
    # Esc: restore, then leave.
    tool = _begin(viewport, face)
    _drag(viewport, tool, (0.5, 0, 0), (0.8, 0.2, 0))
    tool.on_cancel(viewport)
    assert tool.active and not tool.changed()
    tool.on_cancel(viewport)
    assert tool.face is None
    assert "uvw" not in face.attrs["texture"]


def test_rotate_flip_reset_and_undo_inside_the_tool(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    tool.rotate(90)
    assert _close(_uv(tool, (0.5, 0, 0)), (1.0, 0.0))
    assert _close(_uv(tool, (0.5, 0.5, 0)), (2.0, 0.0))      # U now runs up
    tool.flip(True)
    assert _close(_uv(tool, (0.5, -0.5, 0)), (2.0, 0.0))
    assert tool.undo_step()
    assert _close(_uv(tool, (0.5, 0.5, 0)), (2.0, 0.0))
    tool.reset()
    assert not tool.changed()
    assert _close(_uv(tool, (1.0, 0, 0)), (2.0, 0.0))


def test_the_grid_and_the_preview_follow_the_working_map(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    faces = tool.preview_faces()
    assert len(faces) == 1 and faces[0].attrs["texture"]["uvw"]
    lines = tool.grid_lines()
    # 0.5 m tiles on a 2 m square: 5 U lines and 5 V lines.
    assert len(lines) == 10
    _drag(viewport, tool, (1.0, 0, 0), (1.5, 0, 0))          # 1 m tiles
    # U now spans 0.5..2.5 (4 lattice lines), V 0..2 (3 lines).
    assert len(tool.grid_lines()) == 7


def test_a_face_without_an_image_is_refused(viewport):
    face = _textured_square(viewport)
    face.attrs.pop("texture")
    tool = TexturePositionTool()
    assert not tool.begin(viewport, face, QVector3D(1, 1, 0))
    assert not tool.active


def test_the_back_side_texture_is_positioned_and_stored_on_the_back(viewport):
    face = _textured_square(viewport)
    face.attrs.pop("texture")
    face.attrs["back"] = {"texture": dict(TEX), "mat": "brick_clay"}
    tool = TexturePositionTool()
    viewport.set_active_tool(tool)
    assert TexturePositionTool.side_texture(face, "front") is None
    assert not tool.begin(viewport, face, QVector3D(0.7, 0.3, 0), side="front")
    assert tool.begin(viewport, face, QVector3D(0.7, 0.3, 0), side="back")
    _drag(viewport, tool, (0.5, 0, 0), (0.8, 0.2, 0))
    assert tool.on_key(viewport, Qt.Key_Return, Qt.NoModifier)
    assert "texture" not in face.attrs                 # the front stays bare
    back = face.attrs["back"]
    assert back["mat"] == "brick_clay" and len(back["texture"]["uvw"]) == 8
    viewport.history.undo()
    assert "uvw" not in face.attrs["back"]["texture"]
    # Reset on the back side clears its map too.
    viewport.history.redo()
    cmd = TexturePositionTool.side_command(
        face, "back", {k: v for k, v in back["texture"].items() if k != "uvw"})
    viewport.history.execute(cmd)
    assert "uvw" not in face.attrs["back"]["texture"]


# ---- The protractor on the green pin (Rafael, 2026-09-16, 04:30) -------------

def _px_per_metre(vp, at=(0.5, 0.0, 0.0)):
    a = vp._world_to_pixel(QVector3D(*at))
    b = vp._world_to_pixel(QVector3D(at[0] + 1.0, at[1], at[2]))
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _green_to(vp, tool, angle_deg, radius, modifiers=Qt.NoModifier):
    """Drag the green pin (at (1,0,0) after a fresh begin, red at (0.5,0,0))
    to ``angle_deg`` about the red pin, ``radius`` metres away."""
    a = math.radians(angle_deg)
    end = (0.5 + radius * math.cos(a), radius * math.sin(a), 0.0)
    tool.on_click(_ctx(vp, (1.0, 0, 0)))
    tool.on_hover(_ctx(vp, end, modifiers))
    return end


def _tile_angle(tool):
    e = tool.map.e_u
    return math.degrees(math.atan2(e.y(), e.x()))


def test_the_sweep_snaps_to_15_degree_steps_wherever_the_cursor_is(viewport):
    """«Te bloquea a los 0, a los 45 y a los 90» (Rafael) — the
    protractor's 15° steps, which include them; and not only near the
    disc: Marco's recording shows the steps with the cursor three radii
    out, and the original «Ctrl = Sin ajuste» says the snap is the
    default everywhere."""
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    ppm = _px_per_metre(viewport)
    for radius in (tool.DISC_PX / ppm, tool.DISC_PX * 4.0 / ppm):
        for wanted, off in ((90.0, 87.0), (45.0, 41.0), (0.0, -6.0), (135.0, 138.0)):
            _green_to(viewport, tool, off, radius=radius)
            assert tool._sweep_deg == wanted and tool._on_tick, (wanted, off, tool._sweep_deg)
            assert abs(_tile_angle(tool) - wanted) < 1e-6
            assert tool.value_label()[0] == f"{wanted:+.1f}°"
            tool.on_release(viewport)
            assert tool._sweep_deg is None and tool.value_label() is None
            tool.reset()


def test_ctrl_keeps_the_sweep_free(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    near = (tool.DISC_PX * 1.0) / _px_per_metre(viewport)
    _green_to(viewport, tool, 87.0, radius=near, modifiers=Qt.ControlModifier)
    assert not tool._on_tick
    assert abs(_tile_angle(tool) - 87.0) < 0.11
    tool.on_release(viewport)


def test_the_snap_keeps_the_scale_the_cursor_asked_for(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    near = (tool.DISC_PX * 1.0) / _px_per_metre(viewport)
    _green_to(viewport, tool, 88.0, radius=near)
    assert tool._sweep_deg == 90.0
    assert abs(tool.map.e_u.length() - near) < 1e-3     # the tile = the radius
    tool.on_release(viewport)


# TODO(MAC-08): Baseline float radius difference is 2.98e-08, above the 1e-9 tolerance.
# See docs/macos-test-failures.md; confirmed on the baseline commit, not fixed yet.
def test_the_protractor_sits_on_the_red_pin_with_its_zero_on_the_start_arm(viewport):
    face = _textured_square(viewport)
    tool = _begin(viewport, face)
    near = (tool.DISC_PX * 1.0) / _px_per_metre(viewport)
    _green_to(viewport, tool, 30.0, radius=near)
    disc = tool._protractor_segments(viewport)
    R, u, v, r = disc["frame"]
    assert _close(R.toTuple(), (0.5, 0.0, 0.0))
    assert _close(u.toTuple(), (1.0, 0.0, 0.0))          # zero = where the drag began
    assert len(disc["ring"]) == 48
    assert abs(r * _px_per_metre(viewport) - tool.DISC_PX) < 0.5   # fixed screen size
    assert disc["wedge"][0] == R and len(disc["wedge"]) >= 3
    # the start arm across the disc, its stub, and a square on each arm at
    # the same reach; the current arm runs from the pivot along the sweep
    a, b = disc["diameter"]
    assert _close(((a + b) * 0.5).toTuple(), R.toTuple())
    sq_base, sq_cur = disc["squares"]
    assert abs((sq_base - R).length() - (sq_cur - R).length()) < 1e-9
    assert disc["base_stub"] == (R, sq_base)
    c, d = disc["current_arm"]
    assert c == R
    cur = (d - c).normalized()
    assert abs(math.degrees(math.atan2(cur.y(), cur.x())) - 30.0) < 1e-4
    tool.on_release(viewport)
    assert tool._protractor_segments(viewport) is None
