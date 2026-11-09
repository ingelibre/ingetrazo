# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Flip works on a group that holds other groups (#380, seen in the ArqAi
review: a piece of furniture made of grouped parts did not flip).

The tool measured the selection's box from each group's OWN mesh, and a
group made of groups keeps its geometry in its nested placements, its own
mesh empty: no box, no planes to hover, and the click did nothing (the
mirror would have used the world origin as its centre)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PySide6.QtGui import QVector3D as V

from core.group import Group, placement_points
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from tools.flip import FlipTool


def _cabinet(scene):
    """A container with one asymmetric part inside: a right triangle
    standing at x 2..4 — its tall side at x = 2."""
    m = Mesh()
    m.add_face([V(2, 0, 0), V(4, 0, 0), V(2, 0, 2)])
    part = Group(m, "puerta")
    cab = Group(Mesh(), "mueble")
    cab.adopt([part])
    scene.groups.append(cab)
    scene.selection = {cab}
    return cab


def _vp(scene):
    return SimpleNamespace(scene=scene, history=History(scene),
                           flash_status=lambda *a, **k: None,
                           update=lambda: None)


def test_the_box_of_a_group_of_groups_is_its_parts():
    scene = Scene()
    _cabinet(scene)
    lo, hi = FlipTool()._bounds(_vp(scene))
    assert lo is not None, "no box: the planes could not be drawn"
    assert (lo.x(), hi.x(), hi.z()) == (2.0, 4.0, 2.0)


def test_flipping_a_group_of_groups_mirrors_it_in_place():
    scene = Scene()
    cab = _cabinet(scene)
    vp = _vp(scene)
    assert FlipTool().flip(vp, "x")
    pts = placement_points(cab)
    assert np.allclose(pts[:, 0].min(), 2.0) and np.allclose(
        pts[:, 0].max(), 4.0)                    # same place, not at origin
    tall = pts[np.isclose(pts[:, 2], 2.0)]
    assert np.allclose(tall[:, 0], 4.0)          # tall side now at x = 4
    vp.history.undo()
    tall = placement_points(cab)[np.isclose(placement_points(cab)[:, 2], 2)]
    assert np.allclose(tall[:, 0], 2.0)


def test_a_flipped_copy_of_a_group_of_groups_keeps_its_parts():
    scene = Scene()
    cab = _cabinet(scene)
    assert FlipTool().flip(_vp(scene), "x", copy=True)
    assert len(scene.groups) == 2
    copy = next(g for g in scene.groups if g is not cab)
    pts = placement_points(copy)
    assert len(pts) == 3
    tall = pts[np.isclose(pts[:, 2], 2.0)]
    assert np.allclose(tall[:, 0], 4.0)
