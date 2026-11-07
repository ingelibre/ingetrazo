# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A corner of a 15 mm board pushed right through its thickness (#710).

The report: «when I'm trying to cut the top corner with Push in a 15 mm
thickness, it does not cut». The board came from a file whose coordinates
are single precision, so the 15 mm-wide top face had its normal tilted by
~2e-5. The "backing wall leans away from the push" rule read that cosine as
a lean and limited the push to 0. The lean is now judged by how far the
wall actually strays from square (a fraction of a micron here); a wall that
truly leans still stops the push.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.history import History  # noqa: E402
from core.orient import is_closed  # noqa: E402
from core.scene import Scene  # noqa: E402
from tests.test_fuzz_engine import _push  # noqa: E402

_app = QApplication.instance() or QApplication([])

# The loose board of the reporter's file, verbatim: x = 2.8772 … 2.8922, a
# sloped top, and a 39 × 15 mm corner drawn on its front face (the last but
# one face).
BOARD = [
    [(2.877201795578003, -0.7504384517669678, 0.0), (2.877201795578003, -0.7504384517669678, 0.89000004529953), (2.8922016620635986, -0.7504384517669678, 0.89000004529953), (2.8922016620635986, -0.7504384517669678, 0.0)],
    [(2.8922016620635986, -0.7504384517669678, 0.0), (2.8922016620635986, -1.360438346862793, 0.0), (2.877201795578003, -1.360438346862793, 0.0), (2.877201795578003, -0.7504384517669678, 0.0)],
    [(2.892202377319336, -1.3210762739181519, 1.1055748462677002), (2.8922016620635986, -0.7504384517669678, 0.89000004529953), (2.877201795578003, -0.7504384517669678, 0.89000004529953), (2.8772025108337402, -1.3210762739181519, 1.1055748462677002)],
    [(2.8922019004821777, -1.3604369163513184, 1.1055742502212524), (2.8922016620635986, -1.360438346862793, 0.0), (2.8922016620635986, -0.7504384517669678, 0.0), (2.8922016620635986, -0.7504384517669678, 0.89000004529953), (2.892202377319336, -1.3210762739181519, 1.1055748462677002)],
    [(2.8772025108337402, -1.3210762739181519, 1.1055748462677002), (2.877201795578003, -1.3604364395141602, 1.1055748462677002), (2.8922019004821777, -1.3604369163513184, 1.1055742502212524), (2.892202377319336, -1.3210762739181519, 1.1055748462677002)],
    [(2.877201795578003, -1.360438346862793, 0.0), (2.8922016620635986, -1.360438346862793, 0.0), (2.8922019004821777, -1.3604369163513184, 1.1055742502212524), (2.877201795578003, -1.3604364395141602, 1.1055748462677002), (2.877201795578003, -1.3604364395141602, 1.090574860572815)],
    [(2.8772025108337402, -1.3210762739181519, 1.1055748462677002), (2.8772025108337402, -1.3210762739181519, 1.090574860572815), (2.877201795578003, -1.3604364395141602, 1.090574860572815), (2.877201795578003, -1.3604364395141602, 1.1055748462677002)],
    [(2.877201795578003, -0.7504384517669678, 0.0), (2.877201795578003, -1.360438346862793, 0.0), (2.877201795578003, -1.3604364395141602, 1.090574860572815), (2.8772025108337402, -1.3210762739181519, 1.090574860572815), (2.8772025108337402, -1.3210762739181519, 1.1055748462677002), (2.877201795578003, -0.7504384517669678, 0.89000004529953)],
]
TOP = 1.1055748


def _board():
    scene = Scene()
    for loop in BOARD:
        scene.mesh.add_face([V(*p) for p in loop])
    corner = scene.mesh.faces[6]
    return scene, History(scene), corner


def test_the_corner_is_cut_through_the_board():
    scene, hist, corner = _board()
    assert is_closed(scene.mesh)
    depth = 0.015 if corner.normal().x() > 0 else -0.015   # into the board
    assert _push(scene, hist, corner, depth)
    m = scene.mesh
    assert is_closed(m)
    # The corner block is gone: nothing reaches the top over its 39 mm …
    assert not any(all(abs(v.z() - TOP) < 1e-5 for v in f.vertices)
                   for f in m.faces)
    # … and it left a 39 × 15 mm floor and a 15 × 15 mm step behind.
    areas = sorted(round(f.area() * 1e6) for f in m.faces)
    assert 225 in areas and 590 in areas


def test_a_wall_that_truly_leans_still_stops_the_push():
    # A triangular prism: its slanted roof leans away from a push into the
    # long wall below it, so that push stays a no-op.
    scene = Scene()
    pts = [V(0, 0, 0), V(0, 1, 0), V(0, 0, 1)]
    far = [p + V(1, 0, 0) for p in pts]
    m = scene.mesh
    m.add_face([pts[0], pts[2], pts[1]])
    m.add_face([far[0], far[1], far[2]])
    m.add_face([pts[0], pts[1], far[1], far[0]])        # floor
    m.add_face([pts[0], far[0], far[2], pts[2]])        # back wall
    m.add_face([pts[1], pts[2], far[2], far[1]])        # slanted roof
    assert is_closed(m)
    back = next(f for f in m.faces
                if all(abs(v.y()) < 1e-9 for v in f.vertices))
    depth = 0.2 if back.normal().y() > 0 else -0.2       # into the prism
    assert not _push(scene, History(scene), back, depth)
