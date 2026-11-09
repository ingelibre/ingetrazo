# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Selecting does not re-measure the BIM takeoff (#857, @buildsmart888).

The BIM dock re-measured every tagged object — a world mesh and a volume
each — on every scene change, and a selection is one: on a rebar model of
238 tagged bars a box selection waited 25 s. The takeoff reads geometry
and tags, never the selection, so a view-only change keeps it; an edit
or an undo still re-measures."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402


def _bar(x):
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for q in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
              [2, 3, 7, 6], [3, 0, 4, 7]):
        m.add_face([p[i] for i in q])
    g = Group(m, f"bar {x}")
    g.xform = QMatrix4x4()
    g.xform.translate(x * 2.0, 0, 0)
    g.ifc = {"class": "IfcReinforcingBar", "name": f"bar {x}", "id": x + 1}
    return g


def test_a_selection_keeps_the_takeoff_and_an_edit_remeasures(monkeypatch):
    from views.main_window import MainWindow
    import core.bim as bim
    win = MainWindow()
    try:
        scene = win.viewport.scene
        bars = [_bar(i) for i in range(3)]
        scene.groups += bars
        scene.version += 1
        panel = win.bim_tray.bim
        panel.refresh()
        assert panel.tree.topLevelItemCount() == 3
        calls = []
        real = bim.collect_objects
        monkeypatch.setattr(bim, "collect_objects",
                            lambda s, *a: calls.append(1) or real(s, *a))
        scene.select([bars[0]])
        scene.select(bars, mode="add")
        scene.clear_selection()
        panel.refresh()
        assert calls == []                    # nothing to re-measure
        assert panel.tree.topLevelItemCount() == 3
        bars[0].xform.scale(2.0)              # an edit
        scene.version += 1
        panel.refresh()
        assert calls == [1]
        assert panel.tree.topLevelItem(0).text(3) == "8.00"   # 2³ m³
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_an_edit_remeasures_only_the_object_it_touched():
    from core.bim import collect_objects
    from core.scene import Scene
    scene = Scene()
    bars = [_bar(i) for i in range(3)]
    scene.groups += bars
    memo = {}
    first = collect_objects(scene, memo)
    again = collect_objects(scene, memo)
    assert all(a is b for a, b in zip(first, again))      # nothing re-measured
    bars[1].xform.scale(2.0)
    third = collect_objects(scene, memo)
    assert third[0] is first[0] and third[2] is first[2]
    assert third[1] is not first[1]
    assert third[1]["volume"] == pytest.approx(8.0)
    bars[2].ifc = dict(bars[2].ifc, name="renamed")
    fourth = collect_objects(scene, memo)
    assert fourth[2] is not third[2] and fourth[2]["name"] == "renamed"
    # Untagged or removed objects leave the memo.
    scene.groups.remove(bars[0])
    collect_objects(scene, memo)
    assert len(memo) == 2
    # Without a memo every call measures afresh, as the IFC export wants.
    assert collect_objects(scene)[0] is not collect_objects(scene)[0]
