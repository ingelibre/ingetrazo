# SPDX-License-Identifier: GPL-3.0-or-later
"""Autofold after lowering a curve onto the one below it (#1294).

A block whose end is an arc in plan: Move takes the whole top arc down onto
the bottom arc to make a ramp. Earcut folded the warped top with pieces
whose three corners were all on the lowered arc — flat in the floor's plane,
doubling the floor — and the join guard refused the whole move. The fold
now picks pieces that leave no face doubled, and merges them back only
while the merged face stays flat."""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QVector3D as V

from core.history import History, MoveVerticesCommand
from core.scene import Scene
from core.topology import fold_nonplanar_faces

H, L, D = 2.0, 4.0, 1.5


def _block(segments=12, bulge=0.8, arc_end=True):
    """The block, and its top and bottom loops. With ``arc_end`` the left
    end is the arc (it is lowered whole); otherwise the arc is the front
    and the straight left edge is lowered."""
    if arc_end:
        arc = [(-bulge * math.sin(math.pi * i / segments),
                D - D * i / segments) for i in range(segments + 1)]
        plan = arc + [(L, 0), (L, D)]
    else:
        front = [(L * i / segments, -bulge * math.sin(math.pi * i / segments))
                 for i in range(segments + 1)]
        plan = front + [(L, D), (0, D)]
    sc = Scene()
    m = sc.mesh
    bot = [V(x, y, 0) for x, y in plan]
    top = [V(x, y, H) for x, y in plan]
    m.add_face(list(reversed(bot)))
    m.add_face(top)
    n = len(plan)
    for i in range(n):
        j = (i + 1) % n
        m.add_face([bot[i], bot[j], top[j], top[i]])
    return sc, History(sc), top


def _worst_warp(mesh) -> float:
    worst = 0.0
    for f in mesh.faces:
        p = np.array([[q.x(), q.y(), q.z()] for q in f.vertices])
        if len(p) > 3:
            c = p.mean(0)
            worst = max(worst,
                        float(np.abs((p - c) @ np.linalg.svd(p - c)[2][-1])
                              .max()))
    return worst


def _closed(mesh) -> bool:
    return all(len(e.faces) == 2 for e in mesh.edges)


def _doubled_floor(mesh) -> int:
    return sum(1 for f in mesh.faces
               if all(abs(p.z()) < 1e-6 for p in f.vertices))


def test_lowering_the_top_arc_onto_the_bottom_one_makes_a_ramp():
    sc, h, top = _block()
    cmd = MoveVerticesCommand(top[:13], V(0, 0, -H))
    h.execute(cmd)
    assert h.last_rejected is None and h.last_error is None
    assert cmd.welded
    assert _closed(sc.mesh)
    assert _doubled_floor(sc.mesh) == 1        # only the floor itself
    assert _worst_warp(sc.mesh) < 1e-3


def test_the_ramp_holds_for_fine_and_coarse_arcs():
    for segments in (3, 24, 64):
        for bulge in (0.3, 1.5):
            sc, h, top = _block(segments, bulge)
            h.execute(MoveVerticesCommand(top[:segments + 1], V(0, 0, -H)))
            assert h.last_rejected is None, (segments, bulge)
            assert _closed(sc.mesh), (segments, bulge)
            assert _doubled_floor(sc.mesh) == 1, (segments, bulge)
            assert _worst_warp(sc.mesh) < 1e-3, (segments, bulge)


def test_undo_gives_the_block_back():
    sc, h, top = _block()
    before = (len(sc.mesh.vertices), len(sc.mesh.edges), len(sc.mesh.faces))
    h.execute(MoveVerticesCommand(top[:13], V(0, 0, -H)))
    h.undo()
    assert (len(sc.mesh.vertices), len(sc.mesh.edges),
            len(sc.mesh.faces)) == before
    assert _worst_warp(sc.mesh) < 1e-9


def test_a_straight_end_lowered_still_goes_through():
    """The straight end lowered: the curved front warps and folds with
    earcut's pieces, as before — never refused (thin pieces left unmerged
    read as overlapping to the join guard)."""
    for segments in (12, 48, 90):
        sc, h, _top = _block(segments, 0.3, arc_end=False)
        h.execute(MoveVerticesCommand([V(0, D, H), V(0, 0, H)],
                                      V(0, 0, -H)))
        assert h.last_rejected is None, segments
        assert _closed(sc.mesh), segments


def test_a_lifted_quad_corner_still_folds_into_two_triangles():
    """The classic fold is untouched."""
    sc = Scene()
    sc.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0.2), V(0, 1, 0)])
    folded = fold_nonplanar_faces(sc.mesh)
    assert len(folded) == 1
    assert sorted(len(f.loop) for f in sc.mesh.faces) == [3, 3]


def test_the_move_tool_on_screen_lowers_the_arc():
    """The reporter's gesture through the real tool: the top arc selected,
    picked at its end and dropped on the bottom arc's end."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        QApplication([])
    from tools.move import MoveTool
    from views.viewport import Viewport, _HoverEvent

    vp = Viewport(None)
    vp.resize(1400, 850)
    vp.camera.set_aspect(1400, 850)
    said = []
    vp.flash_status = lambda text, *a, **k: said.append(text)
    vp.camera.yaw = math.radians(-35.0)
    vp.camera.pitch = math.radians(30.0)
    vp.camera.target = V(1.5, 0.75, 1.0)
    vp.camera.distance = 12.0
    sc, _h, top = _block()
    for f in list(sc.mesh.faces):
        vp.scene.mesh.add_face(list(f.vertices))
    keys = {(round(p.x(), 6), round(p.y(), 6)) for p in top[:13]}
    vp.scene.selection = {
        e for e in vp.scene.mesh.edges
        if abs(e.a.z() - H) < 1e-9 and abs(e.b.z() - H) < 1e-9
        and (round(e.a.x(), 6), round(e.a.y(), 6)) in keys
        and (round(e.b.x(), 6), round(e.b.y(), 6)) in keys}
    assert len(vp.scene.selection) == 12
    t = MoveTool()
    vp.active_tool = t
    t.on_activate(vp)

    def click(p):
        x, y = vp._world_to_pixel(p)
        vp._process_hover(QPointF(x, y), Qt.NoModifier)
        t.on_click(vp._build_ctx(_HoverEvent(QPointF(x, y), Qt.NoModifier)))

    click(V(0, D, H))
    click(V(0, D, 0))
    assert vp.history.last_rejected is None, said
    assert vp.history.last_error is None
    m = vp.scene.mesh
    assert _closed(m)
    assert _doubled_floor(m) == 1
    assert max(p.z() for f in m.faces for p in f.vertices
               if abs(p.x()) < 1.0) < 1e-6      # the arc end is down
