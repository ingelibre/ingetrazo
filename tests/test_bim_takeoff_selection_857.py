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


def test_an_edit_remeasures_only_the_object_it_touched(monkeypatch):
    import core.bim as bim
    from core.scene import Scene
    scene = Scene()
    bars = [_bar(i) for i in range(3)]
    scene.groups += bars
    measured = []
    real = bim.face_set_volume

    def measure(faces):
        measured.append(1)
        return real(faces)

    monkeypatch.setattr(bim, "face_set_volume", measure)
    memo = {}
    bim.collect_objects(scene, memo)
    again = bim.collect_objects(scene, memo)
    assert [o["volume"] for o in again] == pytest.approx([1, 1, 1])
    assert len(measured) == 3
    bars[1].xform.scale(2.0)
    third = bim.collect_objects(scene, memo)
    assert [o["volume"] for o in third] == pytest.approx([1, 8, 1])
    assert len(measured) == 4
    bars[2].ifc = dict(bars[2].ifc, name="renamed")
    fourth = bim.collect_objects(scene, memo)
    assert fourth[2]["name"] == "renamed"
    assert len(measured) == 4  # tags do not alter numeric quantities
    scene.groups.remove(bars[0])
    assert [o["name"] for o in bim.collect_objects(scene, memo)] == [
        "bar 1", "renamed"]


def test_takeoff_updates_after_hole_removal_and_direct_winding_edits():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        bar = _bar(0)
        bar.ifc["class"] = "IfcColumn"
        scene.groups.append(bar)
        panel = win.bim_tray.bim

        def volume():
            scene.version += 1
            panel.refresh()
            return panel.tree.topLevelItem(0).text(3)

        assert volume() == "1.00"
        top = bar.mesh.faces[1]
        hole = bar.mesh.add_hole(
            top, [V(.25, .25, 1), V(.25, .75, 1),
                  V(.75, .75, 1), V(.75, .25, 1)])
        assert volume() == "—"
        bar.mesh.remove_hole(top, hole)
        assert volume() == "1.00"
        top.loop.reverse()
        assert volume() == "0.33"
        assert panel.tree.topLevelItem(0).text(2) == "0.33 m³"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
