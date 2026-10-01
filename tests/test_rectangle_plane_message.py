# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""When a rectangle comes out flat, say WHY (found live, 2026-09-18).

Marco, drawing the step of exercise 18: «pongo el vértice del rectángulo en
la esquina de una pared, pero no me deja en la esquina de la otra pared…
con rectángulo rotado todo bien».

He had picked the opposite corner, correctly — and was told to pick the
opposite corner. Reproduced with his wall (4.000 x 0.150 x 2.400):

    plane from the FRONT face (vertical)   → 4.000 x 0.000   refused
    plane from the BASE face (horizontal)  → 4.000 x 0.150   drawn

Clicking the first corner while hovering the wall's vertical face locks the
rectangle to that plane, where the two base corners share a line. A step on
the ground cannot be drawn from there at all. Rotated Rectangle works
because it takes its plane from the edge you draw, not the face under the
cursor.

The behaviour is the classic one and stays; the message was the bug.

Since 2026-09-29 a far corner SNAPPED off the plane picks the plane itself
(``tests/test_snapped_plane.py``): his base corner, snapped, now draws the
step on the ground. The message is left for what no axis plane can hold.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.i18n import set_language
from tools.rectangle import RectangleTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


#: Marco's wall, to the millimetre.
ESQUINA = V(3.309, 2.777, 0.0)
OPUESTA = V(7.309, 2.927, 0.0)


def _tool(normal):
    t = RectangleTool()
    t.start_point = QVector3D(ESQUINA)
    t.work_plane = (QVector3D(ESQUINA), normal)
    return t


def test_a_corner_off_the_plane_blames_the_plane():
    set_language("en")
    msg = _tool(V(0, -1, 0))._degenerate_reason(OPUESTA)
    assert "off the drawing plane" in msg
    assert "opposite corner" not in msg, "that was the lie"


def test_and_names_the_arrow_that_fixes_it():
    """The span is 4 m of X and 15 cm of Y with no Z, so the plane he wants
    is XY — the Up arrow."""
    set_language("en")
    msg = _tool(V(0, -1, 0))._degenerate_reason(OPUESTA)
    assert "XY" in msg
    assert "↑" in msg


def test_a_genuinely_flat_pick_keeps_the_old_message():
    """Two corners on the same row IN the plane really is «pick the
    opposite corner», and that message stays."""
    set_language("en")
    t = _tool(V(0, 0, 1))                     # horizontal plane
    msg = t._degenerate_reason(V(7.309, 2.777, 0.0))   # same y, in-plane
    assert "opposite corner" in msg


def test_the_horizontal_plane_draws_the_step():
    """The other half of the report: on the right plane it just works."""
    t = _tool(V(0, 0, 1))
    far, _ = t._square_corner(t.start_point, OPUESTA)
    du, dv = t._dimensions(t.start_point, far)
    assert abs(du) > 1e-6 and abs(dv) > 1e-6
    assert round(abs(du), 3) == 4.0
    assert round(abs(dv), 3) == 0.15


def test_it_is_said_in_spanish_too():
    set_language("es")
    try:
        msg = _tool(V(0, -1, 0))._degenerate_reason(OPUESTA)
        assert "plano de dibujo" in msg
    finally:
        set_language("en")


def test_a_snapped_corner_now_draws_the_step():
    """The same two corners, the far one snapped (off the front face's
    plane): the rectangle takes the ground plane that holds both."""
    t = _tool(V(0, -1, 0))
    t.hover_point = QVector3D(OPUESTA)
    far, _ = t._square_corner(t.start_point, OPUESTA)
    du, dv = t._dimensions(t.start_point, far)
    assert sorted((round(abs(du), 3), round(abs(dv), 3))) == [0.15, 4.0]
