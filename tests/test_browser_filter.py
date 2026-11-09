# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser's search and funnel: wildcards, the quick filters by row
state, inverting them, and the section planes that follow the same search.

Every model here is generated, as in tests/test_outliner.py.
"""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from core.section import SectionPlane

_app = QApplication.instance() or QApplication([])

_QUADS = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6),
          (0, 2, 6, 4), (1, 5, 7, 3)]


def _box(at=(0.0, 0.0, 0.0), size=0.1) -> Mesh:
    mesh = Mesh()
    x0, y0, z0 = at
    c = [QVector3D(x0 + dx * size, y0 + dy * size, z0 + dz * size)
         for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
    for q in _QUADS:
        mesh.add_face([c[k] for k in q])
    return mesh


def _group(name, layer=None) -> Group:
    g = Group(_box(), name=name)
    g.layer = layer
    return g


def _container(name, kids) -> Group:
    g = Group(name=name)
    g.adopt(kids)
    g.component = False
    return g


def _window_with(*groups):
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    scene.groups[:] = groups        # without the template's scale figure
    scene.version += 1
    panel = win.project_browser.outliner
    panel.refresh()
    return win, scene, panel


def _close(win):
    win.viewport.scene.end_group_edit()
    win._saved_version = win.viewport.scene.version
    win.close()


def _shown(panel) -> set:
    """The names of the rows the tree is showing."""
    return {panel._groups[key].name for key, item in panel._items.items()
            if not item.isHidden()}


def test_the_search_takes_wildcards_and_plain_text():
    win, _scene, panel = _window_with(
        _group("Muro A"), _group("Muro B"), _group("Ventana"))
    try:
        panel.search.setText("*MUR*")
        assert _shown(panel) == {"Muro A", "Muro B"}
        panel.search.setText("Muro ?")
        assert _shown(panel) == {"Muro A", "Muro B"}
        panel.search.setText("vent")                 # a plain substring
        assert _shown(panel) == {"Ventana"}
        panel.search.setText("nope")
        assert _shown(panel) == set()
        panel.search.setText("")
        assert _shown(panel) == {"Muro A", "Muro B", "Ventana"}
        assert panel.summary.text() == "3 groups · 0 components · 0 hidden"
    finally:
        _close(win)


def test_hidden_rows_count_what_a_group_around_them_hides():
    kid = _group("Kid")
    parent = _container("Building", [kid])
    parent.hidden = True
    win, _scene, panel = _window_with(parent, _group("Outside"))
    try:
        panel.set_state_filter("hidden")
        assert _shown(panel) == {"Building", "Kid"}
        assert panel.summary.text() == "2 of 3 match"

        panel.set_state_filter("visible")
        assert _shown(panel) == {"Outside"}
        assert panel.summary.text() == "1 of 3 match"
    finally:
        _close(win)


def test_locked_rows_count_what_a_group_around_them_locks():
    kid = _group("Kid")
    parent = _container("Building", [kid])
    parent.locked = True
    win, _scene, panel = _window_with(parent, _group("Outside"))
    try:
        panel.set_state_filter("locked")
        assert _shown(panel) == {"Building", "Kid"}

        # Locked is still drawn, so the visibility filter keeps it: only the
        # eye hides a row.
        panel.set_state_filter("visible")
        assert _shown(panel) == {"Building", "Kid", "Outside"}
    finally:
        _close(win)


def test_the_selection_filter_keeps_the_path_to_the_picked_rows():
    kid = _group("Kid")
    parent = _container("Building", [kid])
    other = _group("Other")
    win, scene, panel = _window_with(parent, other)
    try:
        scene.selection.add(kid)
        panel.set_state_filter("selection")
        # The picked row and the container on the way to it; not its sibling.
        assert _shown(panel) == {"Building", "Kid"}
        assert panel.summary.text() == "1 of 3 match"
    finally:
        _close(win)


def test_the_funnel_separates_components_images_and_plain_groups():
    comp = _group("Chair")
    comp.xform = QMatrix4x4()
    comp.component = True
    image = _group("Poster")
    image.billboard = True
    win, _scene, panel = _window_with(comp, image, _group("Wall"))
    try:
        panel.set_state_filter("components")
        assert _shown(panel) == {"Chair"}
        panel.set_state_filter("images")
        assert _shown(panel) == {"Poster"}
        panel.set_state_filter("all")
        assert _shown(panel) == {"Chair", "Poster", "Wall"}
    finally:
        _close(win)


def test_inverting_the_filter_shows_the_rows_it_leaves_out():
    hidden = _group("Hidden")
    hidden.hidden = True
    win, _scene, panel = _window_with(hidden, _group("A"), _group("B"))
    try:
        panel.set_state_filter("hidden")
        assert _shown(panel) == {"Hidden"}

        panel.set_invert_filter(True)
        assert _shown(panel) == {"A", "B"}
        assert panel.summary.text() == "2 of 3 match"

        panel.set_invert_filter(False)
        assert _shown(panel) == {"Hidden"}
    finally:
        _close(win)


def test_the_search_and_the_funnel_combine():
    win, _scene, panel = _window_with(
        _group("Muro A"), _group("Muro B"), _group("Ventana"))
    try:
        scene = win.viewport.scene
        scene.groups[0].hidden = True
        scene.groups[2].hidden = True
        panel.refresh()
        panel.search.setText("muro")
        panel.set_state_filter("hidden")
        assert _shown(panel) == {"Muro A"}
        assert panel.summary.text() == "1 of 3 match"

        panel.set_invert_filter(True)   # the rows outside the filter, both
        assert _shown(panel) == {"Muro B", "Ventana"}
    finally:
        _close(win)


def test_clearing_the_filter_brings_every_row_back():
    a = _group("A")
    a.hidden = True
    win, _scene, panel = _window_with(a, _group("B"))
    try:
        panel.set_state_filter("hidden")
        assert _shown(panel) == {"A"}
        panel.set_state_filter("all")
        assert _shown(panel) == {"A", "B"}
        assert panel.filter_btn.toolTip() == "Filter: All rows"

        panel.search.setText("b")
        assert _shown(panel) == {"B"}
        panel.search.clear()
        assert _shown(panel) == {"A", "B"}
    finally:
        _close(win)


def test_section_planes_follow_the_search_and_the_funnel():
    win, scene, panel = _window_with(_group("Building"))
    try:
        plane = SectionPlane(QVector3D(0, 0, 1), QVector3D(0, 0, 1),
                             name="Cut A")
        scene.section_planes.append(plane)
        scene.version += 1
        panel.refresh()
        row = panel._sec_items[id(plane)]

        panel.search.setText("*a")
        assert not row.isHidden()
        assert not panel._sec_root.isHidden()

        panel.search.setText("zzz")
        assert row.isHidden()
        assert panel._sec_root.isHidden()

        panel.search.clear()
        assert not row.isHidden()

        plane.hidden = True
        panel.set_state_filter("hidden")
        assert not row.isHidden()
        panel.set_state_filter("visible")
        assert row.isHidden()
    finally:
        _close(win)


def test_the_section_planes_filter_shows_the_planes_alone():
    kid = _group("Kid")
    win, scene, panel = _window_with(_container("Building", [kid]),
                                     _group("Wall"))
    try:
        cut_a = SectionPlane(QVector3D(0, 0, 1), QVector3D(0, 0, 1),
                             name="Cut A")
        cut_b = SectionPlane(QVector3D(0, 0, 2), QVector3D(1, 0, 0),
                             name="Cut B")
        cut_b.hidden = True                  # hidden planes count too
        scene.section_planes += [cut_a, cut_b]
        scene.version += 1
        panel.refresh()
        rows = [panel._sec_items[id(cut_a)], panel._sec_items[id(cut_b)]]

        panel.set_state_filter("sections")
        assert _shown(panel) == set()                    # no group at all
        assert not panel._sec_root.isHidden()
        assert not any(r.isHidden() for r in rows)
        assert panel.summary.text() == "0 of 3 match"
        assert panel.filter_btn.toolTip() == "Filter: Section planes"

        panel.search.setText("*b")                       # with the search
        assert [r.isHidden() for r in rows] == [True, False]
        panel.search.clear()

        panel.set_invert_filter(True)                    # the groups alone
        assert _shown(panel) == {"Building", "Kid", "Wall"}
        assert panel._sec_root.isHidden()
        panel.set_invert_filter(False)

        panel.set_state_filter("all")
        assert _shown(panel) == {"Building", "Kid", "Wall"}
        assert not any(r.isHidden() for r in rows)
    finally:
        _close(win)


def test_the_section_planes_filter_hides_the_layer_headings():
    from PySide6.QtCore import QSettings
    from core.layers import DEFAULT_LAYER, Layer
    QSettings().setValue("browser/order", "layer")
    win, scene, panel = _window_with(_group("Wall", "Walls"), _group("Site"))
    try:
        scene.layers[:] = [Layer(DEFAULT_LAYER), Layer("Walls")]
        scene.section_planes.append(SectionPlane(
            QVector3D(0, 0, 1), QVector3D(0, 0, 1), name="Cut A"))
        scene.version += 1
        panel._shape = None
        panel.refresh()
        assert len(panel._heads) == 2
        panel.set_state_filter("sections")
        assert all(h.isHidden() for h in panel._heads.values())
        assert not panel._sec_root.isHidden()
        panel.set_state_filter("all")
        assert not any(h.isHidden() for h in panel._heads.values())
    finally:
        QSettings().remove("browser/order")
        _close(win)


def test_the_funnel_menu_offers_the_section_planes():
    win, _scene, panel = _window_with(_group("A"))
    try:
        assert ("sections", "Section planes") in panel.STATE_FILTERS
        assert panel.STATE_FILTERS[-1][0] == "sections"
    finally:
        _close(win)


def test_the_funnel_button_fills_and_says_what_it_is_doing():
    win, _scene, panel = _window_with(_group("A"), _group("B"))
    try:
        idle = panel.filter_btn.icon().cacheKey()
        assert panel.filter_btn.toolTip() == "Filter: All rows"

        panel.set_state_filter("hidden")
        assert panel.filter_btn.toolTip() == "Filter: Hidden rows"
        assert panel.filter_btn.icon().cacheKey() != idle

        panel.set_invert_filter(True)
        assert panel.filter_btn.toolTip() == "Filter: Hidden rows · inverted"

        panel.set_state_filter("all")
        assert panel.filter_btn.toolTip() == "Filter: All rows · inverted"
        panel.set_invert_filter(False)
        assert panel.filter_btn.icon().cacheKey() == idle
    finally:
        _close(win)


def test_an_unknown_state_falls_back_to_every_row():
    win, _scene, panel = _window_with(_group("A"))
    try:
        panel.set_state_filter("nonsense")
        assert panel.state_filter == "all"
        assert _shown(panel) == {"A"}
    finally:
        _close(win)
