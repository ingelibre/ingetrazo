# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Parts tray: a component's parts, measured like a cut list."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from core.parts import (cut_list, cut_list_text, part_material,
                        part_points, part_rows, part_size)

_app = QApplication.instance() or QApplication([])

_QUADS = ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
          (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5))


def _box(sx: float, sy: float, sz: float, at=(0.0, 0.0, 0.0),
         color=None) -> Mesh:
    mesh = Mesh()
    x0, y0, z0 = at
    c = [QVector3D(x0 + dx * sx, y0 + dy * sy, z0 + dz * sz)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        f = mesh.add_face([c[k] for k in q])
        if color is not None:
            f.attrs["color"] = list(color)
    return mesh


def _part(mesh: Mesh, name: str, xform=None) -> Group:
    g = Group(mesh, name=name)
    g.xform = xform if xform is not None else QMatrix4x4()
    return g


def _stool() -> Group:
    """A seat and two identical legs, one of them splayed."""
    splay = QMatrix4x4()
    splay.translate(QVector3D(0.5, 0, 0))
    splay.rotate(10, 0, 1, 0)
    kids = [_part(_box(0.40, 0.40, 0.03, color=(0.6, 0.4, 0.2)), "seat"),
            _part(_box(0.04, 0.04, 0.58, color=(0.6, 0.4, 0.2)), "leg A"),
            _part(_box(0.04, 0.04, 0.58, color=(0.6, 0.4, 0.2)), "leg B",
                  splay)]
    stool = Group(name="stool")
    stool.adopt(kids)
    return stool


def test_a_board_measures_on_its_own_axes():
    size = part_size(part_points(_part(_box(0.8, 0.3, 0.018), "board")))
    assert size == pytest.approx((0.8, 0.3, 0.018), abs=1e-6)


def test_a_splayed_leg_measures_along_its_length():
    """Along the stool's axes the leg at 30° is a fat diagonal; along its
    own it is the stick it is."""
    turn = QMatrix4x4()
    turn.rotate(30, 0, 1, 0)
    leg = _part(_box(0.04, 0.04, 0.58), "leg", turn)
    assert part_size(part_points(leg)) == pytest.approx((0.58, 0.04, 0.04),
                                                        abs=1e-5)


def test_a_stepped_carcass_measures_on_the_models_axes():
    """A body with a plinth set back: the tilted box that holds it in a
    little less volume is not a size anyone cuts."""
    import numpy as np
    body = [(x, y, z) for x in (0, 0.442) for y in (-0.052, 0.56)
            for z in (0.085, 0.794)]
    plinth = [(x, y, z) for x in (0, 0.442) for y in (0.0, 0.56)
              for z in (0.0, 0.085)]
    size = part_size(np.array(body + plinth, dtype=float))
    assert size == pytest.approx((0.794, 0.612, 0.442), abs=1e-6)


def test_the_material_is_the_one_covering_most_of_the_part():
    mesh = _box(1.0, 1.0, 0.02, color=(1, 0, 0))
    small = [f for f in mesh.faces if f.area() < 0.1]
    for f in small:                        # the four thin edges: 0.08 m²
        f.attrs["color"] = [0, 0, 1]
    assert part_material(_part(mesh, "top")) == "#ff0000"


def test_a_part_inherits_its_containers_paint_on_default_faces():
    part = _part(_box(0.5, 0.5, 0.5), "cube")
    part.material = {"color": [0, 1, 0]}
    assert part_material(part) == "#00ff00"


def test_identical_parts_are_one_cut_list_line():
    rows = part_rows(_stool())
    lines = cut_list(rows)
    assert [(ln["qty"], ln["names"]) for ln in lines] == [
        (2, ["leg A", "leg B"]), (1, ["seat"])]
    text = cut_list_text(lines, lambda m: f"{m * 1000:.0f}",
                         ["Qty", "Parts", "Material", "L", "W", "T"])
    assert text.splitlines()[1] == "2\tleg A, leg B\t#996633\t580\t40\t40"


def test_the_material_can_be_left_out_of_the_match():
    """A Sweet Home 3D model paints every fragment with its own image, so
    two identical legs never share a material there."""
    stool = _stool()
    for f in stool.children[2].mesh.faces:
        f.attrs["color"] = [0.1, 0.1, 0.1]
    assert [ln["qty"] for ln in cut_list(part_rows(stool))] == [1, 1, 1]
    merged = cut_list(part_rows(stool), by_material=False)
    assert [ln["qty"] for ln in merged] == [2, 1]
    assert merged[0]["material"] == "#996633, #1a1a1a"


def test_names_sort_naturally():
    kids = [_part(_box(0.1, 0.1, 0.1), f"Piece {n}") for n in (10, 2, 1)]
    holder = Group()
    holder.adopt(kids)
    assert cut_list(part_rows(holder))[0]["names"] == [
        "Piece 1", "Piece 2", "Piece 10"]


def _window_with(group):
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups.append(group)
    scene.selection.clear()
    scene.selection.add(group)
    scene.version += 1
    return win, scene


def test_the_tray_lists_selects_hides_and_renames_parts():
    stool = _stool()
    win, scene = _window_with(stool)
    panel = win.tray.parts
    panel.refresh()
    tree = panel.tree
    assert tree.topLevelItemCount() == 3
    assert [tree.topLevelItem(i).text(0) for i in range(3)] == [
        "seat", "leg A", "leg B"]

    panel._on_clicked(tree.topLevelItem(1), 0)     # the Outliner's click
    assert scene.edit_group is stool
    assert scene.selection == {stool.children[1]}
    panel.refresh()
    assert tree.topLevelItemCount() == 3           # still listed inside it

    tree.topLevelItem(2).setCheckState(0, Qt.Unchecked)
    assert stool.children[2].hidden
    tree.topLevelItem(0).setText(0, "Seat board")
    assert stool.children[0].name == "Seat board"
    win.viewport.history.undo()
    assert stool.children[0].name == "seat"
    win.viewport.history.undo()
    assert not stool.children[2].hidden
    win._saved_version = scene.version


def test_a_plain_group_offers_to_split():
    mesh = _box(0.1, 0.1, 0.1)
    for f in _box(0.1, 0.1, 0.1, at=(1, 0, 0)).faces:
        mesh.add_face(f.vertices)
    group = Group(mesh, name="two blocks")
    win, scene = _window_with(group)
    panel = win.tray.parts
    panel.refresh()
    assert not panel.tree.isVisibleTo(panel)
    assert panel._split_btn.isEnabled()
    panel._on_split()
    assert [k.name for k in group.children] == ["Piece 1", "Piece 2"]
    assert panel.tree.topLevelItemCount() == 2
    win._saved_version = scene.version


def test_copy_cut_list_fills_the_clipboard():
    win, scene = _window_with(_stool())
    panel = win.tray.parts
    panel.refresh()
    panel._on_copy()
    lines = QApplication.clipboard().text().splitlines()
    assert len(lines) == 3 and lines[1].startswith("2\t")
    assert len(lines[0].split("\t")) == 6
    win._saved_version = scene.version


def _many_parts(n: int = 20) -> Group:
    kids = [_part(_box(0.1, 0.1, 0.1, at=(i * 0.2, 0, 0)), f"Piece {i + 1}")
            for i in range(n)]
    cab = Group(name="cabinet")
    cab.adopt(kids)
    return cab


def test_the_list_updates_in_place_and_keeps_its_scroll():
    """A click on a row below the fourteenth must not throw the list back
    to its top: the refresh it triggers updates rows, it does not rebuild."""
    cab = _many_parts()
    win, scene = _window_with(cab)
    win.show()
    panel = win.tray.parts
    panel.refresh()
    tree = panel.tree
    _app.processEvents()
    tree.scrollToBottom()
    before = tree.verticalScrollBar().value()
    assert before > 0
    row = tree.topLevelItem(17)
    panel._on_clicked(row, 0)
    win.tray.on_scene_changed()
    _app.processEvents()
    assert tree.topLevelItem(17) is row
    assert tree.verticalScrollBar().value() == before
    assert scene.selection == {cab.children[17]}
    win._saved_version = scene.version


def test_a_part_selected_in_the_canvas_scrolls_into_view():
    cab = _many_parts()
    win, scene = _window_with(cab)
    win.show()
    panel = win.tray.parts
    panel.refresh()
    tree = panel.tree
    _app.processEvents()
    scene.begin_group_edit(cab)
    scene.selection.add(cab.children[19])
    scene.version += 1
    win.tray.on_scene_changed()
    _app.processEvents()
    last = tree.topLevelItem(19)
    assert last.isSelected()
    assert tree.viewport().rect().contains(tree.visualItemRect(last).center())
    scene.end_group_edit()
    win._saved_version = scene.version


def test_all_parts_visible_shows_every_hidden_part():
    cab = _many_parts(4)
    win, scene = _window_with(cab)
    panel = win.tray.parts
    panel.refresh()
    panel.tree.topLevelItem(1).setCheckState(0, Qt.Unchecked)
    panel.tree.topLevelItem(2).setCheckState(0, Qt.Unchecked)
    assert panel._all_visible.checkState() == Qt.PartiallyChecked
    panel._all_visible.click()
    assert not any(k.hidden for k in cab.children)
    assert panel._all_visible.checkState() == Qt.Checked
    win.viewport.history.undo()
    assert sum(k.hidden for k in cab.children) == 2
    win._saved_version = scene.version


def test_a_rename_survives_a_refresh_while_typing():
    from PySide6.QtTest import QTest
    cab = _many_parts(3)
    win, scene = _window_with(cab)
    win.show()
    panel = win.tray.parts
    panel.refresh()
    item = panel.tree.topLevelItem(2)
    panel.tree.editItem(item, 0)
    _app.processEvents()
    win.tray.on_scene_changed()                 # an edit elsewhere lands
    _app.processEvents()
    # The tree's own line editor, looked up AFTER the refresh: the focus
    # widget is whatever window is active, which in a full offscreen run can
    # be another test's viewport («'Viewport' object has no attribute
    # 'setText'», CI 30-09).
    from PySide6.QtWidgets import QLineEdit
    editors = [w for w in panel.tree.viewport().findChildren(QLineEdit)
               if w.isVisible()]
    assert len(editors) == 1
    editor = editors[0]
    editor.setText("Right side wall")
    QTest.keyClick(editor, Qt.Key_Return)
    _app.processEvents()
    assert cab.children[2].name == "Right side wall"
    win._saved_version = scene.version


def test_part_sizes_resolve_the_millimetre_whatever_the_display_precision():
    """A 4 mm hinge leaf in a document shown to the centimetre read
    «0.03 × 0.02 × 0.00 m» — a part that looked like it had no thickness."""
    from core import units
    from core.scene import Scene
    scene = Scene()
    scene.units = {"length": "m", "precision": 2}
    units.bind_scene(scene)
    try:
        assert units.fmt_triple(0.0325, 0.024, 0.0043) == "0.03 × 0.02 × 0.00 m"
        assert units.fmt_triple(0.0325, 0.024, 0.0043, fine=True) == \
            "0.033 × 0.024 × 0.004 m"
        assert units.fmt_len_fine(0.0043) == "0.004 m"
        scene.units = {"length": "mm", "precision": 0}
        assert units.fmt_triple(0.0325, 0.024, 0.0043, fine=True) == \
            "32 × 24 × 4 mm"
    finally:
        units.bind_scene(None)


def _sheet(sx: float, sy: float) -> Mesh:
    mesh = Mesh()
    pts = [QVector3D(0, 0, 0), QVector3D(sx, 0, 0), QVector3D(sx, sy, 0),
           QVector3D(0, sy, 0)]
    mesh.add_face(pts)
    mesh.add_face(list(reversed(pts)))
    return mesh


def test_a_part_with_no_thickness_is_a_surface_not_a_zero_board():
    """A skin or a pane drawn as one plane is kept — it is what the model
    shows — but the cut list must not list it as a 0-thick board."""
    from core.parts import is_surface
    holder = Group()
    holder.adopt([_part(_sheet(0.6, 0.135), "baseboard skin"),
                  _part(_box(0.6, 0.4, 0.018), "shelf")])
    rows = part_rows(holder)
    assert [is_surface(r["size"]) for r in rows] == [True, False]
    text = cut_list_text(cut_list(rows), lambda m: f"{m * 1000:.0f}",
                         ["Qty", "Parts", "Material", "L", "W", "T"])
    lines = text.splitlines()
    assert lines[1].split("\t")[-1] == "18"            # the shelf
    assert lines[2].split("\t")[-1] == "surface"       # the skin


def test_the_tray_shows_a_surface_as_an_area():
    holder = Group(name="unit")
    holder.adopt([_part(_sheet(0.6, 0.135), "skin"),
                  _part(_box(0.6, 0.4, 0.018), "shelf")])
    win, scene = _window_with(holder)
    panel = win.tray.parts
    panel.refresh()
    assert panel.tree.topLevelItem(0).text(1).endswith("surface")
    assert "×" in panel.tree.topLevelItem(1).text(1)
    assert not panel.tree.topLevelItem(1).text(1).endswith("surface")
    win._saved_version = scene.version
