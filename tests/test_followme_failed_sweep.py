# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Follow Me sweep that fails or declines is a no-op: the user's previous
step stays on the undo stack and what they can redo stays redoable.

The tool used to call ``history.undo()`` after any unsuccessful sweep to
drop "the no-op entry". When the sweep raised, History had already rolled
it back and recorded nothing, so that undo took the user's own last step
and the cleared redo stack lost it for good."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import AddEdgeCommand, History
from core.scene import Scene
from tools.base import ToolContext

_FAILED = ("Follow Me: could not sweep along that path "
           "(reversal or degenerate segment)")


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.messages = []
        self._pick = None

    def update(self):
        pass

    def set_hover(self, *_):
        pass

    def flash_status(self, text, msec=2500):
        self.messages.append(text)

    def pick_face(self, x, y):
        return self._pick


def _drawn(vp, a, b):
    """A line the user drew: one step on the undo stack."""
    cmd = AddEdgeCommand(a, b)
    vp.history.execute(cmd)
    assert vp.history.undo_stack[-1] is cmd
    return cmd


def _model(tmp_path):
    """A square profile standing on the start of a 4 m path the user drew;
    then a second line, drawn and taken back (it waits on the redo stack)."""
    scene = Scene()
    vp = _Vp(scene)
    vp.history.error_log = str(tmp_path / "errors.log")
    m = scene.mesh
    profile = m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 1), V(0, 0, 1)])
    path = _drawn(vp, V(0, 0, 0), V(0, 4, 0))
    other = _drawn(vp, V(3, 0, 0), V(3, 4, 0))
    assert vp.history.undo()
    return vp, profile, path, other


def _sweep_along(vp, profile, path_cmd):
    """Select the path, activate Follow Me and click the profile."""
    from tools.followme import FollowMeTool
    vp.scene.selection.clear()
    vp.scene.selection.add(path_cmd.edge)
    tool = FollowMeTool()
    tool.on_activate(vp)
    assert tool._path is not None
    vp._pick = profile
    ctx = ToolContext(viewport=vp, world=V(0, 0), screen=QPointF(0, 0),
                      modifiers=Qt.NoModifier, snap=None)
    tool.on_hover(ctx)
    tool.on_click(ctx)
    return tool


def _assert_untouched(vp, profile, path, other):
    m = vp.scene.mesh
    assert vp.history.undo_stack == [path]          # the drawn path is still there
    assert vp.history.redo_stack == [other]         # …and the undone line is redoable
    assert m.faces == [profile]
    assert path.edge in m.edges
    assert vp.history.redo() and other.edge in m.edges
    assert vp.history.undo() and vp.history.undo()
    assert path.edge not in m.edges                 # the path's own step undoes it


def test_a_sweep_that_raises_keeps_the_previous_step_and_redo(
        tmp_path, monkeypatch):
    import tools.followme as followme
    vp, profile, path, other = _model(tmp_path)

    def broken(mesh, face, pts, closed):
        mesh.remove_face(face)                      # half-way through…
        mesh.add_edge(V(5, 5, 5), V(5, 5, 5))       # …and the engine raises

    monkeypatch.setattr(followme, "sweep_profile", broken)
    _sweep_along(vp, profile, path)
    assert vp.history.last_error                    # History rolled it back
    assert _FAILED in vp.messages
    _assert_untouched(vp, profile, path, other)


def test_a_declined_sweep_records_nothing_and_keeps_redo(tmp_path):
    vp, profile, path, other = _model(tmp_path)
    from tools.followme import FollowMeTool
    reversal = [V(0, 0, 0), V(0, 4, 0), V(0, 0, 0)]  # the engine declines
    FollowMeTool()._commit(vp, profile, reversal, False)
    assert vp.messages[-1] == _FAILED
    assert vp.history.last_error is None            # declined, not failed
    _assert_untouched(vp, profile, path, other)
    assert vp.history.last_rejected == _FAILED      # History's no-op channel


def test_a_declined_sweep_at_the_step_limit_keeps_the_oldest_step():
    scene = Scene()
    vp = _Vp(scene)
    vp.history.max_steps = 2
    profile = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 1),
                                   V(0, 0, 1)])
    first = _drawn(vp, V(5, 0, 0), V(5, 4, 0))
    second = _drawn(vp, V(6, 0, 0), V(6, 4, 0))
    from tools.followme import FollowMeTool
    FollowMeTool()._commit(vp, profile,
                           [V(0, 0, 0), V(0, 4, 0), V(0, 0, 0)], False)
    assert vp.history.undo_stack == [first, second]


def test_a_sweep_that_works_is_still_one_step(tmp_path):
    vp, profile, path, other = _model(tmp_path)
    _sweep_along(vp, profile, path)
    m = vp.scene.mesh
    assert len(m.faces) == 6                        # the 1 × 1 × 4 box
    assert vp.history.undo_stack[:-1] == [path]
    assert vp.history.redo_stack == []              # a new step clears redo
    assert not vp.scene.selection
    assert vp.history.undo() and m.faces == [profile]
    assert vp.history.undo_stack == [path]
