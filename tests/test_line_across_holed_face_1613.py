# SPDX-License-Identifier: GPL-3.0-or-later
"""A line beside, across or along a drawn opening keeps it open (#1613,
reopening #1407). The steps of the report: a rectangle, another on it, its
inside deleted, a line from edge to edge — the cycle holding the hole was
faced without it, and the plane rebuild took that for a redraw. On a solid,
the face below the lid read as a face filling the opening."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402

import tests.test_fuzz_engine as F  # noqa: E402
from core.group import Group  # noqa: E402
from core.history import DeleteFaceCommand  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.topology import _point_in_face_solid  # noqa: E402
from tests.test_drawing_tools import _VP, _ctx  # noqa: E402
from tools.line import LineTool  # noqa: E402
from tools.rectangle import RectangleTool  # noqa: E402

W, H = 1.19, 1.53                 # not round: float32 endpoints, as drawn


def _draw(tool, vp, a, b):
    t = tool()
    for p in (a, b):
        t.on_hover(_ctx(vp, p))
        t.on_click(_ctx(vp, p))


def _filling(mesh, p):
    return [f for f in mesh.faces
            if abs(V.dotProduct(f.normal(), p - f.vertices[0])) < 1e-3
            and _point_in_face_solid(f, p)]


def _plate(where, holes=1):
    scene = Scene()
    vp = _VP(scene)
    if where == "group":
        g = Group(name="Plate")
        scene.groups.append(g)
        scene.begin_group_edit(g)
    _draw(RectangleTool, vp, V(0, 0, 0), V(W, H, 0))
    z = 0.0
    if where == "solid":
        f = scene.mesh.faces[0]
        F._push(scene, vp.history, f, 0.8 if f.normal().z() > 0 else -0.8)
        z = max(v.position.z() for v in scene.mesh.vertices)
    centres = []
    for k in range(holes):
        c = V(W * (k + 0.5) / holes, H * 0.45, z)
        d = V(W / holes * 0.25, H * 0.2, 0)
        _draw(RectangleTool, vp, c - d, c + d)
        centres.append(c)
    for c in centres:
        inner, = _filling(scene.mesh, c)
        inner.attrs["color"] = (0, 0, 1)
        vp.history.execute(DeleteFaceCommand(inner))
    for f in scene.mesh.faces:
        f.attrs["color"] = (1, 0, 0)
    return scene, vp, z, centres


LINES = {"beside": (0.83, 0.91), "through": (0.47, 0.52),
         "along the rim": (0.65, 0.65), "corner to corner": (0.0, 1.0)}


@pytest.mark.parametrize("where", ["flat", "group", "solid"])
@pytest.mark.parametrize("holes", [1, 2])
@pytest.mark.parametrize("line", LINES)
def test_the_openings_stay_open_and_the_face_is_divided(where, holes, line):
    scene, vp, z, centres = _plate(where, holes)
    lid = [f for f in scene.mesh.faces
           if all(abs(p.z() - z) < 1e-5 for p in f.vertices)]
    assert len(lid) == 1 and len(lid[0].holes) == holes
    a, b = LINES[line]
    _draw(LineTool, vp, V(0, H * a, z), V(W, H * b, z))
    if where == "solid" and line in ("through", "corner to corner"):
        # On a box's lid a line across the opening closes it, as the
        # reference modeller does: its two halves are new faces.
        assert any(_filling(scene.mesh, c) for c in centres)
        return
    for c in centres:
        for dx, dy in ((0.011, 0.013), (-0.02, 0.01), (0.015, -0.02)):
            assert not _filling(scene.mesh, c + V(dx, dy, 0))
    lid = [f for f in scene.mesh.faces
           if all(abs(p.z() - z) < 1e-5 for p in f.vertices)]
    assert len(lid) >= 2
    assert all(f.attrs.get("color") == (1, 0, 0) for f in lid)


def test_an_opening_still_filled_by_its_own_face_keeps_it():
    scene = Scene()
    vp = _VP(scene)
    _draw(RectangleTool, vp, V(0, 0, 0), V(W, H, 0))
    _draw(RectangleTool, vp, V(0.3, 0.4, 0), V(0.9, 0.9, 0))
    _draw(LineTool, vp, V(0, 1.3, 0), V(W, 1.35, 0))
    assert len(scene.mesh.faces) == 3
    assert len(_filling(scene.mesh, V(0.6, 0.6, 0))) == 1
