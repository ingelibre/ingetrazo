# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Move + Ctrl copies, and "3x" / "/3" lay an array (issue #20).

Tapping Ctrl during a Move leaves the original where it is and stamps a
translated copy on the second click; right afterwards, typing ``3x`` makes
three copies at multiples of the distance and ``/3`` three copies dividing
it. Rotate already worked this way; Move did not (reported by @pacaeiro).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.group import Group
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from tools.base import ToolContext
from tools.move import MoveTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashed = []

    def update(self):
        pass

    def flash_status(self, msg, *a, **k):
        self.flashed.append(msg)

    def pick_edge(self, x, y):
        return None

    def pick_face(self, x, y):
        return None

    def pick_group(self, x, y):
        return None


def _ctx(vp, x, y, z=0.0):
    return ToolContext(viewport=vp, world=V(x, y, z), screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=None)


def _square(scene, x0=0.0):
    return scene.mesh.add_face([V(x0, 0), V(x0 + 1, 0), V(x0 + 1, 1), V(x0, 1)])


def _xs(scene):
    return sorted(round(min(v.x() for v in f.vertices), 6) for f in scene.mesh.faces)


def test_ctrl_leaves_the_original_and_stamps_a_copy():
    scene = Scene()
    face = _square(scene)
    scene.selection = [face]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))                     # grab the corner
    tool.on_hover(_ctx(vp, 1, 0))                     # dragging: original follows…
    assert _xs(scene) == [1.0]
    assert tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    assert tool._copy and _xs(scene) == [0.0]         # …until Ctrl: it goes back
    tool.on_hover(_ctx(vp, 3, 0))
    assert _xs(scene) == [0.0]                        # the original stays put
    ghost = tool.rubber_band_lines()
    assert len(ghost) == 1 + 4                        # move vector + the copy's outline
    tool.on_click(_ctx(vp, 3, 0))                     # drop the copy 3 m right
    assert _xs(scene) == [0.0, 3.0]
    assert not tool._copy                             # Ctrl arms ONE operation
    vp.history.undo()
    assert _xs(scene) == [0.0]


def test_ctrl_again_turns_copy_off_and_the_original_follows():
    scene = Scene()
    face = _square(scene)
    scene.selection = [face]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_hover(_ctx(vp, 2, 0))
    assert _xs(scene) == [0.0]
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)   # copy off: the preview resumes
    assert _xs(scene) == [2.0]
    tool.on_click(_ctx(vp, 2, 0))
    assert _xs(scene) == [2.0]                        # a plain move after all


def test_external_array_after_a_copy():
    scene = Scene()
    scene.selection = [_square(scene)]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 2, 0))                     # one copy at +2
    assert _xs(scene) == [0.0, 2.0]
    assert tool.on_array_value(vp, 3, "x")            # "3x": three copies at 2, 4, 6
    assert _xs(scene) == [0.0, 2.0, 4.0, 6.0]
    assert tool.on_array_value(vp, 2, "x")            # retyping re-lays: 2, 4
    assert _xs(scene) == [0.0, 2.0, 4.0]
    vp.history.undo()                                 # the array is ONE undo step
    assert _xs(scene) == [0.0]


def test_internal_array_divides_the_distance():
    scene = Scene()
    scene.selection = [_square(scene)]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 6, 0))
    assert tool.on_array_value(vp, 3, "/")            # "/3": copies at 2, 4, 6
    assert _xs(scene) == [0.0, 2.0, 4.0, 6.0]


def test_the_array_window_closes_at_the_next_click():
    scene = Scene()
    scene.selection = [_square(scene)]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 2, 0))
    scene.selection = []
    tool.on_click(_ctx(vp, 5, 5))                     # nothing there: no move starts…
    assert tool.start_point is None
    tool.on_click(_ctx(vp, 5, 5))
    assert tool.on_array_value(vp, 3, "x") is True    # …so the window is still open
    scene.selection = [scene.mesh.faces[0]]
    tool.on_click(_ctx(vp, 0, 0))                     # a real new move closes it
    tool.on_cancel(vp)
    assert tool.on_array_value(vp, 3, "x") is False


def test_a_plain_move_offers_no_array():
    scene = Scene()
    scene.selection = [_square(scene)]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_click(_ctx(vp, 2, 0))
    assert _xs(scene) == [2.0]
    assert tool.on_array_value(vp, 3, "x") is False


def test_a_group_copies_as_a_sibling_and_arrays():
    scene = Scene()
    m = Mesh()
    m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    g = Group(m, name="Banca")
    scene.groups.append(g)
    scene.selection.clear()
    scene.selection.add(g)
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 0, 3))
    assert len(scene.groups) == 2
    copy = [x for x in scene.groups if x is not g][0]
    assert copy.name == "Banca"
    assert abs(min(v.y() for v in copy.mesh.faces[0].vertices) - 3.0) < 1e-6
    assert abs(min(v.y() for v in g.mesh.faces[0].vertices)) < 1e-6   # original untouched
    assert tool.on_array_value(vp, 4, "x")
    # A group makes a live array (core/array.py): one container that
    # holds the original and its four copies.
    (array,) = scene.groups
    assert array.children[0] is g and len(array.children) == 5
    vp.history.undo()
    assert scene.groups == [g]


def test_the_value_box_understands_the_array_forms():
    from views.viewport import Viewport
    parse = Viewport._parse_value_buffer
    assert parse("3x") == ("array", 3, "x")
    assert parse("3X") == ("array", 3, "x")
    assert parse("*3") == ("array", 3, "x")
    assert parse("3*") == ("array", 3, "x")
    assert parse("/3") == ("array", 3, "/")
    assert parse("3/") == ("array", 3, "/")
    assert parse("3") == 3.0                          # a plain length still is one
    assert parse("3/4\"") != ("array", 3, "/")        # the imperial fraction survives


def test_count_and_spacing_in_one_entry_after_a_copy():
    """#111: «5x10m» — five copies ten metres apart, typed once."""
    scene = Scene()
    scene.selection = [_square(scene)]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_click(_ctx(vp, 2, 0))                     # one copy at +2 (direction)
    assert tool.on_array_value(vp, 3, "x", step=10.0)
    assert _xs(scene) == [0.0, 10.0, 20.0, 30.0]
    vp.history.undo()
    assert _xs(scene) == [0.0]


def test_count_and_spacing_typed_during_the_ctrl_drag():
    """The cursor gives the direction, the entry the count and the step."""
    scene = Scene()
    scene.selection = [_square(scene)]
    vp = _Vp(scene)
    tool = MoveTool()
    tool.on_click(_ctx(vp, 0, 0))
    tool.on_key(vp, Qt.Key_Control, Qt.NoModifier)
    tool.on_hover(_ctx(vp, 0.7, 0))                   # pointing along +X
    assert tool.on_array_value(vp, 4, "x", step=2.5)
    assert _xs(scene) == [0.0, 2.5, 5.0, 7.5, 10.0]
    assert tool.start_point is None                   # the operation is done


def test_the_value_box_reads_count_times_spacing():
    from views.viewport import Viewport
    parse = Viewport._parse_value_buffer
    assert parse("5x10m") == ("array", 5, "x", 10.0)
    assert parse("5x10") == ("array", 5, "x", 10.0)
    assert parse("3*250cm") == ("array", 3, "x", 2.5)
    assert parse("5x-2") is None                      # a spacing is a distance
