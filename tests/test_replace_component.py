# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Select ▸ All Instances and Replace Component…: select every copy of a
component and swap them for another definition, each copy keeping its
place, turn and scale, its layer, paint and visibility."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, copy_group, world_mesh
from core.history import History, ReplaceComponentCommand
from core.mesh import Mesh
from core.scene import Scene
from core.select_ops import same_definition


@pytest.fixture(autouse=True)
def _no_modal_keep_question(monkeypatch):
    """Replacing the last copies asks whether to keep the definition; a
    modal box would wait for a click no test makes. «Let it go» unless a
    test says otherwise."""
    from views.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_ask_keep_orphans",
                        lambda self, orphans: False)


def _quad(size=1.0, z=0.0):
    m = Mesh()
    m.add_face([V(0, 0, z), V(size, 0, z), V(size, size, z), V(0, size, z)])
    return m


def _component(mesh, name, dx=0.0, turn=0.0, scale=1.0):
    g = Group(mesh, name=name)
    xf = QMatrix4x4()
    xf.translate(dx, 0.0, 0.0)
    xf.rotate(turn, 0.0, 0.0, 1.0)
    xf.scale(scale)
    g.xform = xf
    return g


def _points(group):
    return sorted((round(v.position.x(), 6), round(v.position.y(), 6),
                   round(v.position.z(), 6))
                  for v in world_mesh(group).vertices)


def _model():
    """Three copies of «Silla», two of «Mesa», a classic group and a group
    of groups (a matrix, but not a component)."""
    scene = Scene()
    silla = _component(_quad(1.0), "Silla", dx=0.0)
    sillas = [silla, copy_group(silla, V(5, 0, 0)),
              copy_group(silla, V(10, 0, 0))]
    mesa = _component(_quad(2.0, z=1.0), "Mesa", dx=20.0)
    mesas = [mesa, copy_group(mesa, V(5, 0, 0))]
    classic = Group(_quad(3.0), name="Muro")
    holder = _component(_quad(0.5), "Caja", dx=-5.0)
    holder.component = False
    scene.groups.extend(sillas + mesas + [classic, holder])
    return scene, History(scene), sillas, mesas, classic, holder


# --- Select ▸ All Instances ------------------------------------------------

def test_all_instances_takes_every_copy_and_nothing_else():
    scene, _h, sillas, mesas, classic, holder = _model()
    got = same_definition(scene, [sillas[1]])
    assert set(got) == set(sillas)
    assert not set(got) & {*mesas, classic, holder}


def test_all_instances_of_two_definitions_takes_both_families():
    scene, _h, sillas, mesas, _c, _holder = _model()
    assert set(same_definition(scene, [sillas[0], mesas[1]])) == {
        *sillas, *mesas}


def test_all_instances_ignores_groups_and_loose_geometry():
    scene, _h, _s, _m, classic, holder = _model()
    face = scene.mesh.add_face([V(0, 0, 5), V(1, 0, 5), V(1, 1, 5)])
    assert same_definition(scene, [classic, holder, face]) == []


def test_all_instances_answers_from_the_open_group_only():
    """Inside a group, only the copies at that level — like Select All."""
    scene, _h, sillas, _m, _c, _holder = _model()
    inner = _component(_quad(1.0), "Pata")
    inner_copy = copy_group(inner, V(2, 0, 0))
    box = Group(Mesh(), name="Conjunto")
    box.adopt([inner, inner_copy])
    box.component = False
    scene.groups.append(box)
    scene.begin_group_edit(box)
    try:
        assert set(same_definition(scene, [inner])) == {inner, inner_copy}
        assert same_definition(scene, [sillas[0]]) == []
    finally:
        scene.end_group_edit()


# --- Replace Component -----------------------------------------------------

def test_replace_swaps_the_definition_and_keeps_the_placement():
    scene, hist, sillas, mesas, _c, _h = _model()
    target = sillas[1]
    xf = QMatrix4x4(target.xform)
    hist.execute(ReplaceComponentCommand([target], mesas[0]))
    assert target.mesh is mesas[0].mesh
    assert target.name == "Mesa"
    assert target.xform == xf                       # same place
    # Mesa's own origin lands on the chair's: x 5..7, y 0..2, z 1.
    assert _points(target) == sorted([(5.0, 0.0, 1.0), (7.0, 0.0, 1.0),
                                      (7.0, 2.0, 1.0), (5.0, 2.0, 1.0)])
    # the other chairs are untouched
    assert sillas[0].mesh is sillas[2].mesh and sillas[0].name == "Silla"


def test_replace_follows_the_targets_turn_and_scale():
    scene = Scene()
    hist = History(scene)
    a = _component(_quad(1.0), "A", dx=3.0, turn=90.0, scale=2.0)
    b = _component(_quad(1.0, z=0.5), "B", dx=50.0)
    scene.groups.extend([a, b])
    hist.execute(ReplaceComponentCommand([a], b))
    # B's unit square, turned 90° and doubled at x = 3
    assert _points(a) == sorted([(3.0, 0.0, 1.0), (3.0, 2.0, 1.0),
                                 (1.0, 2.0, 1.0), (1.0, 0.0, 1.0)])


def test_replace_keeps_what_belongs_to_the_copy():
    scene, hist, sillas, mesas, _c, _h = _model()
    t = sillas[0]
    t.layer = "Mobiliario"
    t.material = {"color": (1.0, 0.0, 0.0)}
    t.hidden = True
    uid = t.uid
    mesas[0].ifc = {"class": "IfcFurniture", "name": "Mesa"}
    hist.execute(ReplaceComponentCommand([t], mesas[0]))
    assert t.layer == "Mobiliario"
    assert t.material == {"color": (1.0, 0.0, 0.0)}
    assert t.hidden is True
    assert t.uid == uid
    assert t.ifc == {"class": "IfcFurniture", "name": "Mesa"}
    assert t.ifc is not mesas[0].ifc                # not aliased


def test_replace_all_instances_then_undo_and_redo():
    scene, hist, sillas, mesas, _c, _h = _model()
    before = [(_points(g), g.name) for g in sillas]
    v0 = scene.version
    hist.execute(ReplaceComponentCommand(
        same_definition(scene, [sillas[0]]), mesas[1]))
    assert scene.version > v0
    assert all(g.mesh is mesas[0].mesh for g in sillas)
    assert {g.name for g in sillas} == {"Mesa"}
    assert set(same_definition(scene, [mesas[0]])) == {*sillas, *mesas}
    hist.undo()
    assert [(_points(g), g.name) for g in sillas] == before
    assert sillas[0].mesh is sillas[1].mesh is sillas[2].mesh
    assert sillas[0].mesh is not mesas[0].mesh
    hist.redo()
    assert all(g.mesh is mesas[0].mesh for g in sillas)


def test_replace_skips_its_own_definition_and_non_components():
    scene, _h, sillas, mesas, classic, holder = _model()
    cmd = ReplaceComponentCommand([*mesas, classic, holder, sillas[0]],
                                  mesas[0])
    assert cmd.targets == [sillas[0]]


def test_replaced_copies_share_the_sources_subgroups():
    """A source with subgroups: the replaced copy holds them SHARED, so an
    edit inside any copy reaches every one, as copies of a component do."""
    scene = Scene()
    hist = History(scene)
    banca = _component(_quad(1.0), "Banca", dx=0.0)
    banca.adopt([_component(_quad(0.2, z=0.5), "Respaldo")])
    target = _component(_quad(1.0), "Silla", dx=8.0)
    scene.groups.extend([banca, target])
    hist.execute(ReplaceComponentCommand([target], banca))
    assert len(target.children) == 1
    assert target.children[0].mesh is banca.children[0].mesh
    assert target.children[0] is not banca.children[0]
    assert target.children[0].uid != banca.children[0].uid
    hist.undo()
    assert target.children == [] and target.name == "Silla"


def test_replacement_survives_the_igz(tmp_path):
    from formats import igz
    scene, hist, sillas, mesas, _c, _h = _model()
    hist.execute(ReplaceComponentCommand(sillas, mesas[0]))
    path = tmp_path / "r.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    mesa_groups = [g for g in back.groups if g.name == "Mesa"]
    assert len(mesa_groups) == 5
    assert len({id(g.mesh) for g in mesa_groups}) == 1
    assert sorted(_points(g) for g in mesa_groups) == sorted(
        _points(g) for g in [*sillas, *mesas])


# --- the window --------------------------------------------------------------

def _menu_texts(win, monkeypatch):
    """The right-click menu's entries, submenus included, without opening
    it (a real ``exec`` would wait for a mouse that is not there)."""
    import views.main_window as mw
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    opened = []

    class _NoModal(QMenu):
        def exec(self, *_a, **_k):          # noqa: A003 - Qt's name
            opened.append(self)

    monkeypatch.setattr(mw, "QMenu", _NoModal)
    win.show_viewport_context_menu(QPoint(0, 0))
    menu = opened[-1]
    # Submenus are parented to the menu (QAction.menu() is unreliable
    # under PySide 6.11).
    return [act.text() for m in [menu, *menu.findChildren(QMenu)]
            for act in m.actions()]


def test_the_menu_offers_both_and_replace_swaps_the_selection(monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from core.i18n import tr
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        _s, _h, sillas, mesas, classic, holder = _model()
        scene.groups.extend(sillas + mesas + [classic, holder])
        scene.selection.clear()
        scene.selection.update(sillas)
        texts = _menu_texts(win, monkeypatch)
        assert tr("All Instances") in texts
        assert tr("Replace Component…") in texts

        choices = win._replacement_choices(list(scene.selection))
        assert [g.name for _lb, g in choices] == ["Mesa"]   # not its own
        asked = {}

        def pick(_parent, _title, label, items, *_a, **_k):
            asked["label"], asked["items"] = label, items
            return items[0], True
        monkeypatch.setattr(QInputDialog, "getItem", pick)
        win._on_replace_component()
        assert "3" in asked["label"]
        assert all(g.mesh is mesas[0].mesh for g in sillas)
        win.viewport.history.undo()
        assert all(g.name == "Silla" for g in sillas)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_no_replace_entry_without_another_definition(monkeypatch):
    from core.i18n import tr
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        silla = _component(_quad(1.0), "Silla")
        scene.groups.extend([silla, copy_group(silla, V(4, 0, 0)),
                             Group(_quad(2.0), name="Muro")])
        scene.selection.clear()
        scene.selection.add(silla)
        texts = _menu_texts(win, monkeypatch)
        assert tr("All Instances") in texts
        assert tr("Replace Component…") not in texts
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# --- the tray's «In model» list ----------------------------------------------

def _row_for(win, name, with_kept=False):
    from PySide6.QtCore import Qt
    panel = win.tray.components
    panel.refresh_in_model()
    for i in range(panel._in_model.count()):
        item = panel._in_model.item(i)
        groups = item.data(Qt.UserRole) or []
        kept = item.data(Qt.UserRole + 1)
        definition = groups[0] if groups else kept
        if definition is not None and definition.name == name:
            if with_kept:
                return panel, groups, kept, item.text()
            return panel, groups
    raise AssertionError(f"no row for {name}")


def test_the_in_model_list_selects_and_replaces_from_its_menu():
    from core.i18n import tr
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        _s, _h, sillas, mesas, classic, holder = _model()
        scene.groups.extend(sillas + mesas + [classic, holder])
        scene.selection.clear()

        panel, groups = _row_for(win, "Silla")
        actions = panel._in_model_actions(groups)
        assert actions[0][0] == tr("Select Instances ({n})", n=3)
        # nothing selected yet: Replace is there, greyed
        assert actions[1][:2] == (tr("Replace Selection with This"), None)
        actions[0][1]()
        assert set(scene.selection) == set(sillas)

        # with the chairs selected, the table row offers to replace them
        panel, groups = _row_for(win, "Mesa")
        text, run, _checked, _tip = panel._in_model_actions(groups)[1]
        assert text == tr("Replace {n} Selected with This", n=3)
        run()
        assert all(g.mesh is mesas[0].mesh for g in sillas)
        win.viewport.history.undo()
        assert all(g.name == "Silla" for g in sillas)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_its_own_row_does_not_offer_to_replace_the_selection():
    from core.i18n import tr
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        _s, _h, sillas, mesas, _c, _holder = _model()
        scene.groups.extend(sillas + mesas)
        scene.selection.clear()
        scene.selection.update(sillas)
        panel, groups = _row_for(win, "Silla")
        assert panel._in_model_actions(groups)[1][:2] == (
            tr("Replace Selection with This"), None)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# --- Keep in File: definitions with no copy placed ----------------------------

def test_keep_in_file_survives_deleting_every_copy_and_undoes():
    from core.history import KeepComponentCommand
    from core.kept_components import kept_template
    scene, hist, sillas, _m, _c, _h = _model()
    proto = sillas[0].mesh
    sillas[0].layer = "Mobiliario"
    hist.execute(KeepComponentCommand(sillas[0]))
    t = kept_template(scene, proto)
    assert t is not None and t.mesh is proto and t.name == "Silla"
    assert t not in scene.groups                    # never drawn
    assert t.xform == QMatrix4x4() and t.layer is None
    hist.execute(KeepComponentCommand(sillas[1]))   # already kept: no-op
    assert len(scene.kept_components) == 1
    for g in sillas:
        scene.groups.remove(g)
    assert kept_template(scene, proto) is t
    hist.undo()
    assert len(scene.kept_components) == 1
    hist.undo()
    assert scene.kept_components == []
    hist.redo()
    assert scene.kept_components == [t]


def test_stop_keeping_takes_it_out_and_undo_puts_it_back():
    from core.history import KeepComponentCommand
    scene, hist, sillas, mesas, _c, _h = _model()
    hist.execute(KeepComponentCommand(sillas[0]))
    hist.execute(KeepComponentCommand(mesas[0]))
    silla_t = scene.kept_components[0]
    hist.execute(KeepComponentCommand(silla_t, keep=False))
    assert [t.name for t in scene.kept_components] == ["Mesa"]
    hist.undo()
    assert scene.kept_components[0] is silla_t


def test_an_edit_to_the_definition_reaches_the_kept_template():
    from core.history import KeepComponentCommand
    scene, hist, sillas, _m, _c, _h = _model()
    hist.execute(KeepComponentCommand(sillas[0]))
    t = scene.kept_components[0]
    scene.begin_group_edit(sillas[1])
    scene.mesh.vertices[0].position = V(0, 0, 3)
    scene.end_group_edit()
    assert t.mesh is sillas[0].mesh
    assert any(round(v.position.z(), 6) == 3.0 for v in t.mesh.vertices)


def test_kept_definitions_survive_the_igz_and_share_with_copies(tmp_path):
    from core.history import KeepComponentCommand
    from formats import igz
    scene, hist, sillas, mesas, _c, _h = _model()
    hist.execute(KeepComponentCommand(sillas[0]))   # still placed
    hist.execute(KeepComponentCommand(mesas[0]))
    for g in mesas:                                 # none placed any more
        scene.groups.remove(g)
    path = tmp_path / "k.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    names = sorted(t.name for t in back.kept_components)
    assert names == ["Mesa", "Silla"]
    by_name = {t.name: t for t in back.kept_components}
    assert len(by_name["Mesa"].mesh.faces) == 1
    assert not any(g.name == "Mesa" for g in back.groups)
    sillas_back = [g for g in back.groups if g.name == "Silla"]
    assert all(g.mesh is by_name["Silla"].mesh for g in sillas_back)
    back.clear()
    assert back.kept_components == []


def test_a_kept_definition_with_no_copy_can_replace_and_be_placed():
    from core.history import KeepComponentCommand
    from core.kept_components import place_copy
    scene, hist, sillas, mesas, _c, _h = _model()
    hist.execute(KeepComponentCommand(mesas[0]))
    for g in mesas:
        scene.groups.remove(g)
    t = scene.kept_components[0]
    hist.execute(ReplaceComponentCommand(sillas[:1], t))
    assert sillas[0].mesh is t.mesh and sillas[0].name == "Mesa"
    xf = QMatrix4x4()
    xf.translate(30.0, 0.0, 0.0)
    g = place_copy(t, xf)
    assert g.mesh is t.mesh and g.is_component() and g.xform == xf
    assert g is not t and g.uid != t.uid


def test_the_list_shows_a_kept_definition_with_no_copy(monkeypatch):
    from core.history import KeepComponentCommand
    from core.i18n import tr
    from tools.place_group import PlaceGroupTool
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        _s, _h, sillas, mesas, _c, _holder = _model()
        scene.groups.extend(sillas + mesas)
        win.viewport.history.execute(KeepComponentCommand(mesas[0]))
        for g in mesas:
            scene.groups.remove(g)
        panel, groups, kept, text = _row_for(win, "Mesa", with_kept=True)
        assert groups == [] and kept is scene.kept_components[0]
        assert "0×" in text and tr("kept") in text
        actions = panel._in_model_actions(groups, kept)
        assert actions[0][1] is None                # nothing to select
        assert actions[3][0] == tr("Keep in File") and actions[3][2] is True

        # in the viewport's dialog too, with no copy placed
        scene.selection.clear()
        scene.selection.update(sillas)
        assert [d for _lb, d in win._replacement_choices(sillas)] == [kept]

        # replace the chairs from the row, then place a copy from it
        panel._in_model_actions(groups, kept)[1][1]()
        assert all(g.mesh is kept.mesh for g in sillas)
        panel._in_model_actions(groups, kept)[2][1]()
        tool = win.viewport.active_tool
        assert isinstance(tool, PlaceGroupTool)
        assert tool._group.mesh is kept.mesh
        win.viewport.set_active_tool(None)

        # untick Keep in File: the row goes once no copy is left
        win.viewport.history.undo()                 # the chairs again
        panel, groups, kept, _t = _row_for(win, "Mesa", with_kept=True)
        panel._in_model_actions(groups, kept)[3][1]()
        assert scene.kept_components == []
        with pytest.raises(AssertionError, match="no row"):
            _row_for(win, "Mesa")
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# --- thumbnails in the «In model» list ----------------------------------------

def _painted_pixels(pm):
    img = pm.toImage()
    return sum(1 for x in range(img.width()) for y in range(img.height())
               if img.pixelColor(x, y).alpha() > 0)


def test_a_thumbnail_is_drawn_once_and_again_when_the_geometry_changes():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.component_thumbs import SIZE, thumbnail
    _s, _h, sillas, _m, _c, _holder = _model()
    pm = thumbnail(sillas[0])
    assert pm.width() == pm.height() == SIZE
    assert _painted_pixels(pm) > SIZE * SIZE // 10
    assert thumbnail(sillas[1]) is pm               # same definition: cached
    sillas[0].mesh.vertices[0].position = V(0, 0, 4)
    assert thumbnail(sillas[0]) is not pm           # its geometry changed


def test_every_copy_draws_the_same_wherever_it_stands():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.component_thumbs import _signature
    a = _component(_quad(1.0), "A", dx=0.0)
    b = copy_group(a, V(30, 0, 0))
    b.xform.rotate(45.0, 0.0, 0.0, 1.0)
    assert _signature(a) == _signature(b)


def test_an_empty_definition_gives_a_blank_icon():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.component_thumbs import thumbnail
    g = _component(Mesh(), "Nada")
    assert _painted_pixels(thumbnail(g)) == 0


def test_the_list_rows_carry_a_thumbnail():
    from PySide6.QtCore import Qt
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        _s, _h, sillas, mesas, _c, _holder = _model()
        scene.groups.extend(sillas + mesas)
        panel = win.tray.components
        panel.refresh_in_model()
        rows = [panel._in_model.item(i)
                for i in range(panel._in_model.count())]
        assert len(rows) == 2
        assert all(not r.icon().isNull() for r in rows)
        assert all(r.data(Qt.UserRole) for r in rows)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# --- a long list, and what a purge must leave alone ---------------------------

def test_a_long_list_offers_a_name_filter_that_survives_a_refresh():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        names = ["Silla", "Sillón", "Mesa", "Lámpara", "Puerta P1",
                 "Puerta P2", "Ventana V1", "Ventana V2", "Árbol"]
        for i, n in enumerate(names):
            scene.groups.append(_component(_quad(1.0), n, dx=3.0 * i))
        panel = win.tray.components
        panel.refresh_in_model()
        assert not panel._in_model_filter.isHidden()

        def shown():
            return sorted(panel._in_model.item(i).text().split("  ")[0]
                          for i in range(panel._in_model.count())
                          if not panel._in_model.item(i).isHidden())
        panel._in_model_filter.setText("puerta")
        assert shown() == ["Puerta P1", "Puerta P2"]
        panel.refresh_in_model()                    # a scene change
        assert shown() == ["Puerta P1", "Puerta P2"]
        panel._in_model_filter.setText("SILL")
        assert shown() == ["Silla", "Sillón"]
        panel._in_model_filter.clear()
        assert len(shown()) == len(names)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_short_list_has_no_filter():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        _s, _h, sillas, mesas, _c, _holder = _model()
        win.viewport.scene.groups.extend(sillas + mesas)
        panel = win.tray.components
        panel.refresh_in_model()
        assert panel._in_model_filter.isHidden()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_purge_keeps_what_only_a_kept_definition_wears():
    from core.history import KeepComponentCommand
    from core.purge import used_layers, used_materials
    scene, hist, _s, mesas, _c, _h = _model()
    for f in mesas[0].mesh.faces:
        f.attrs["mat"] = "Roble"
    inner = _component(_quad(0.3), "Cajón")
    inner.layer = "Cajones"
    mesas[0].children = [inner]
    hist.execute(KeepComponentCommand(mesas[0]))
    for g in mesas:
        scene.groups.remove(g)
    assert "Roble" in used_materials(scene)
    assert "Cajones" in used_layers(scene)


# --- the four follow-ups -------------------------------------------------------

def _window_with_model():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    _s, _h, sillas, mesas, classic, holder = _model()
    scene.groups.extend(sillas + mesas + [classic, holder])
    return win, scene, sillas, mesas


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def test_orphaned_by_names_only_definitions_left_with_no_copy():
    from core.history import KeepComponentCommand
    from core.kept_components import orphaned_by
    scene, hist, sillas, mesas, _c, _h = _model()
    assert orphaned_by(scene, sillas[:2]) == []          # one chair stays
    assert [g.name for g in orphaned_by(scene, sillas + mesas[:1])] == [
        "Silla"]
    hist.execute(KeepComponentCommand(sillas[0]))
    assert orphaned_by(scene, sillas) == []              # kept: not lost


def test_a_copy_nested_elsewhere_still_counts_as_a_copy():
    from core.kept_components import orphaned_by
    scene, _h, sillas, _m, _c, _holder = _model()
    box = Group(Mesh(), name="Comedor")
    box.adopt([copy_group(sillas[0], V(0, 5, 0))])
    box.component = False
    scene.groups.append(box)
    assert orphaned_by(scene, sillas) == []


def test_replacing_the_last_copies_can_keep_them_in_one_undo(monkeypatch):
    from views.main_window import MainWindow
    win, scene, sillas, mesas = _window_with_model()
    try:
        asked = []
        monkeypatch.setattr(MainWindow, "_ask_keep_orphans",
                            lambda self, o: asked.append(
                                [g.name for g in o]) or True)
        scene.selection.clear()
        scene.selection.update(sillas)
        assert win.replace_selection_with(mesas[0]) == 3
        assert asked == [["Silla"]]          # asked before swapping
        kept = scene.kept_components
        assert [t.name for t in kept] == ["Silla"]
        assert all(g.mesh is mesas[0].mesh for g in sillas)
        win.viewport.history.undo()                 # both, in one step
        assert scene.kept_components == []
        assert all(g.name == "Silla" for g in sillas)
    finally:
        _close(win)


def test_cancel_in_the_question_replaces_nothing(monkeypatch):
    from views.main_window import MainWindow
    win, scene, sillas, mesas = _window_with_model()
    try:
        monkeypatch.setattr(MainWindow, "_ask_keep_orphans",
                            lambda self, o: None)
        scene.selection.clear()
        scene.selection.update(sillas)
        assert win.replace_selection_with(mesas[0]) == 0
        assert all(g.name == "Silla" for g in sillas)
        assert not win.viewport.history.undo_stack
    finally:
        _close(win)


def test_no_question_while_a_copy_remains(monkeypatch):
    from views.main_window import MainWindow
    win, scene, sillas, mesas = _window_with_model()
    try:
        def boom(self, o):
            raise AssertionError("should not ask")
        monkeypatch.setattr(MainWindow, "_ask_keep_orphans", boom)
        scene.selection.clear()
        scene.selection.update(sillas[:2])
        assert win.replace_selection_with(mesas[0]) == 2
    finally:
        _close(win)


def test_keep_in_file_from_the_viewport_menu(monkeypatch):
    from core.i18n import tr
    win, scene, sillas, mesas = _window_with_model()
    try:
        scene.selection.clear()
        scene.selection.update([sillas[0], mesas[1]])
        assert tr("Keep in File") in _menu_texts(win, monkeypatch)
        win.keep_selected_components(True)
        assert sorted(t.name for t in scene.kept_components) == [
            "Mesa", "Silla"]
        win.keep_selected_components(False)
        assert scene.kept_components == []
        win.viewport.history.undo()
        assert len(scene.kept_components) == 2
    finally:
        _close(win)


def test_rename_reaches_every_copy_and_the_kept_template(monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from core.history import KeepComponentCommand
    win, scene, sillas, mesas = _window_with_model()
    try:
        box = Group(Mesh(), name="Comedor")
        nested = copy_group(sillas[0], V(0, 5, 0))
        box.adopt([nested])
        box.component = False
        scene.groups.append(box)
        win.viewport.history.execute(KeepComponentCommand(sillas[0]))
        monkeypatch.setattr(QInputDialog, "getText",
                            lambda *a, **k: ("Silla Bistró", True))
        win.rename_component(sillas[1])
        assert {g.name for g in sillas} == {"Silla Bistró"}
        assert nested.name == "Silla Bistró"
        assert scene.kept_components[0].name == "Silla Bistró"
        assert {g.name for g in mesas} == {"Mesa"}
        win.viewport.history.undo()
        assert {g.name for g in sillas} == {"Silla"}
        assert scene.kept_components[0].name == "Silla"
    finally:
        _close(win)


def test_rename_is_in_the_list_menu():
    from core.i18n import tr
    win, scene, sillas, _mesas = _window_with_model()
    try:
        panel, groups = _row_for(win, "Silla")
        assert tr("Rename…") in [a[0] for a in panel._in_model_actions(groups)]
    finally:
        _close(win)


def test_components_from_another_file_arrive_kept_and_placeable(tmp_path):
    from formats import igz
    from core.history import KeepComponentCommand
    # the «library» file: two placed definitions, one kept, a plain group
    lib, hist, sillas, mesas, _c, _h = _model()
    lamp = _component(_quad(0.3), "Lámpara")
    for f in lamp.mesh.faces:
        f.attrs["color"] = (0.9, 0.8, 0.1)
    lib.groups.append(lamp)
    hist.execute(KeepComponentCommand(lamp))
    lib.groups.remove(lamp)
    path = tmp_path / "biblioteca.igz"
    igz.save_scene(lib, path)

    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        n = win.import_kept_components(path)
        assert n == 3                       # Silla, Mesa and Lámpara
        names = sorted(t.name for t in scene.kept_components)
        assert "Lámpara" in names and "Silla" in names and "Mesa" in names
        assert "Muro" not in names and "Caja" not in names   # groups
        assert not [g for g in scene.groups if g.name in names]
        lamp_t = next(t for t in scene.kept_components
                      if t.name == "Lámpara")
        assert lamp_t.mesh.faces[0].attrs.get("color") is not None
        win.viewport.history.undo()
        assert scene.kept_components == []
    finally:
        _close(win)


def test_a_file_without_components_changes_nothing(tmp_path):
    from formats import igz
    plain = Scene()
    plain.groups.append(Group(_quad(2.0), name="Muro"))
    path = tmp_path / "muro.igz"
    igz.save_scene(plain, path)
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        assert win.import_kept_components(path) == 0
        assert win.viewport.scene.kept_components == []
        assert not win.viewport.history.undo_stack
    finally:
        _close(win)
