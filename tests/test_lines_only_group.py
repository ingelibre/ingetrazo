# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A group made of nothing but lines and arcs is still a group.

GitHub #8 (@pacaeiro, 2026-09-09): "When we have a Group made just from
lines and arcs, there are no Snap points available when we try to get a
point from the group. Also, that group is difficult to select if we try
to click on the lines."

Both halves come from the same place — the pick index — so both are
tested here: inference has to see the group's edges, and a click on one
of its lines has to select it. Every other group in a drawing has faces,
which is why this went unnoticed: the moment a group has one face it
behaves correctly.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Mesh


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


#: The first line's midpoint — where the cursor goes in every test here.
ON_THE_LINE = V(1.0, 0.0, 0.0)


def _lines_and_arcs() -> Mesh:
    """Two straight lines and a quarter arc: what a plan detail is made of,
    and not one face among them."""
    mesh = Mesh()
    mesh.add_edge(V(0, 0, 0), V(2, 0, 0))
    mesh.add_edge(V(2, 0, 0), V(2, 2, 0))
    for i in range(8):                       # an arc IS a chain of segments
        a0, a1 = i * math.pi / 16, (i + 1) * math.pi / 16
        mesh.add_edge(V(2 + math.cos(a0), 2 + math.sin(a0), 0),
                      V(2 + math.cos(a1), 2 + math.sin(a1), 0))
    return mesh


def _viewport_with_a_lines_only_group():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    group = Group(_lines_and_arcs(), name="detalle")
    vp.scene.groups.append(group)
    vp.scene.version += 1
    vp.resize(800, 600)
    cam = vp.camera
    cam.yaw, cam.pitch = math.radians(-45.0), math.radians(35.0)
    cam.target = V(1.0, 1.0, 0.0)
    cam.distance = 8.0
    return win, vp, group


def _pixel_on_the_line(vp):
    px = vp._world_to_pixel(ON_THE_LINE)
    if px is None:
        pytest.skip("the point is not on screen offscreen")
    return px


def test_its_edges_reach_the_pick_index():
    """The root cause, stated once: a faceless group used to be dropped
    from the index entirely, and everything below follows from that."""
    win, vp, group = _viewport_with_a_lines_only_group()
    try:
        index = vp._pick_index()
        assert index.gedge_a is not None, "the group never reached the index"
        assert len(index.gedge_a) == 10          # 2 lines + 8 arc segments
        assert group in index.gedge_groups
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_inference_sees_them():
    """Snapping asks the viewport for the edges near the cursor; a group
    of lines answered with nothing at all."""
    win, vp, _group = _viewport_with_a_lines_only_group()
    try:
        px = _pixel_on_the_line(vp)
        assert vp._nearby_group_edges(px[0], px[1]), "no edge to snap to"
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_an_endpoint_of_the_group_actually_snaps():
    """What the report literally says — "no Snap points available when we
    try to get a point from the group". Not the plumbing this time: the
    real inference, asked at the corner where the two lines meet."""
    from core.snap import compute_snap

    win, vp, _group = _viewport_with_a_lines_only_group()
    try:
        corner = V(2.0, 0.0, 0.0)             # where the two lines meet
        px = vp._world_to_pixel(corner)
        if px is None:
            pytest.skip("the corner is not on screen offscreen")
        # Aim a few pixels off, the way a hand does.
        aim = (px[0] + 4.0, px[1] + 4.0)
        world = vp._world_from_pixel(*aim)
        if world is None:
            pytest.skip("no work plane offscreen")
        snap = compute_snap(
            candidate_world=world,
            candidate_pixel=aim,
            scene=vp._snap_scene(*aim),
            world_to_pixel=vp._world_to_pixel,
            threshold_px=vp.snap_threshold_px,
        )
        assert snap is not None, "nothing to snap to on the group"
        assert snap.kind == "endpoint"
        assert (snap.point - corner).length() < 1e-6
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_clicking_one_of_its_lines_selects_it():
    """`pick_group` has an edge fallback written for exactly this case —
    "a lines-only group" says its own comment — but it read the same empty
    index, so it never had anything to find."""
    win, vp, group = _viewport_with_a_lines_only_group()
    try:
        px = _pixel_on_the_line(vp)
        assert vp.pick_group(px[0], px[1]) is group
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_a_group_with_faces_is_unaffected():
    """The guard being removed was doing nothing for the normal case."""
    win, vp, _group = _viewport_with_a_lines_only_group()
    try:
        mesh = Mesh()
        mesh.add_face([V(5, 0, 0), V(6, 0, 0), V(6, 1, 0), V(5, 1, 0)])
        solid = Group(mesh, name="con caras")
        vp.scene.groups.append(solid)
        vp.scene.version += 1
        index = vp._pick_index()
        assert any(owner is solid for _face, owner in index.entities)
        px = vp._world_to_pixel(V(5.5, 0.5, 0.0))
        if px is not None:
            assert vp.pick_group(px[0], px[1]) is solid
    finally:
        win._saved_version = vp.scene.version
        win.close()
