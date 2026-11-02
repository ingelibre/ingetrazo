# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Move on an untagged model does not walk it for BIM tags.

Since tags are found inside groups (#1030), the takeoff — run after every
edit, even with the BIM panel hidden — walks every group: 26 ms per edit
on the 21 406 groups of #158, none of them tagged (0.1 ms before). A
command that keeps paint (Move, Rotate, Scale, Flip) keeps every tag
too, so a takeoff that found nothing still finds nothing; anything else
— a tag, an edit outside the history — walks again."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group  # noqa: E402
from core.history import MoveGroupCommand  # noqa: E402
from core.mesh import Mesh  # noqa: E402


def _box(x):
    m = Mesh()
    p = [V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0),
         V(x, 0, 1), V(x + 1, 0, 1), V(x + 1, 1, 1), V(x, 1, 1)]
    for q in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
              [2, 3, 7, 6], [3, 0, 4, 7]):
        m.add_face([p[i] for i in q])
    return m


def _model(scene):
    """Two containers holding a box each, nothing tagged."""
    outs = []
    for i in range(2):
        inner = Group(_box(3.0 * i), f"box {i}")
        outer = Group(Mesh(), f"holder {i}")
        outer.adopt([inner])
        outs.append(outer)
    scene.groups += outs
    scene.version += 1
    return outs


def _counting(monkeypatch):
    import core.bim as bim
    calls = []
    real = bim.collect_objects
    monkeypatch.setattr(bim, "collect_objects",
                        lambda s, *a: calls.append(1) or real(s, *a))
    return calls


def test_a_move_on_an_untagged_model_skips_the_walk(monkeypatch):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scene = vp.scene
        outs = _model(scene)
        panel = win.bim_tray.bim
        panel.refresh()
        assert panel.tree.topLevelItemCount() == 0
        calls = _counting(monkeypatch)
        vp.history.execute(MoveGroupCommand(outs[0], V(1, 0, 0)))
        panel.refresh()
        vp.history.undo()
        panel.refresh()
        assert calls == []                    # nothing could have been tagged
        assert panel.tree.topLevelItemCount() == 0
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_tag_after_the_move_is_found(monkeypatch):
    from core.bim import tag_group
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        scene = vp.scene
        outs = _model(scene)
        panel = win.bim_tray.bim
        panel.refresh()
        vp.history.execute(MoveGroupCommand(outs[1], V(0, 2, 0)))
        panel.refresh()
        calls = _counting(monkeypatch)
        tag_group(outs[0].children[0], "IfcColumn", "C-1")   # nested
        scene.version += 1                    # an edit outside the history
        panel.refresh()
        assert calls == [1]
        assert [o["name"] for o in panel._objects] == ["C-1"]
        # Tagged now: a Move walks again, and measures as a fresh takeoff.
        vp.history.execute(MoveGroupCommand(outs[0], V(1, 0, 0)))
        panel.refresh()
        assert calls == [1, 1]
        assert abs(panel._objects[0]["volume"] - 1.0) < 1e-6
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_another_project_is_measured_on_its_own(monkeypatch):
    """Project tabs (#1066): the panel is one for every tab; an untagged
    takeoff of one project says nothing about another."""
    from core.bim import tag_group
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        first = win._doc
        _model(win.viewport.scene)
        panel = win.bim_tray.bim
        panel.refresh()
        win._new_document()
        scene = win.viewport.scene
        g = Group(_box(0.0), "tagged")
        tag_group(g, "IfcBeam", "V-1")
        scene.groups.append(g)
        scene.version += 1
        panel.refresh()
        assert [o["name"] for o in panel._objects] == ["V-1"]
        win.activate_document(first)
        panel.refresh()
        assert panel._objects == []
    finally:
        for d in list(win._documents):
            d.saved_content = d.viewport.scene.content_version
        win._saved_version = win.viewport.scene.version
        win.close()


def test_an_empty_takeoff_maps_no_tree(monkeypatch):
    """With nothing tagged there are no rows to hang from the groups: the
    panel does not map the whole tree for them on each edit."""
    from core import outliner
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        _model(scene)
        panel = win.bim_tray.bim
        calls = []
        real = outliner.parents
        monkeypatch.setattr(outliner, "parents",
                            lambda groups: calls.append(1) or real(groups))
        scene.version += 1
        panel.refresh()
        assert calls == []
        assert panel.tree.topLevelItemCount() == 0
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
