# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""«My Library»: your own folders of components, as a tree in the
Components tray (#1088, #354). Every folder and file here is generated in
``tmp_path``; ``$INGETRAZO_USER_LIBRARY`` points the library at it."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

from core import user_library as lib


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _box_component(name="Mesa", at=(5.0, 5.0, 0.0), mat=None, layer=None):
    """A 2 × 1 × 3 m box as a component instance placed at ``at``."""
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    c = [V(dx * 2, dy, dz * 3) for dz in (0, 1) for dy in (0, 1)
         for dx in (0, 1)]
    for q in [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3),
              (0, 4, 6, 2), (1, 3, 7, 5)]:
        f = m.add_face([c[i] for i in q])
        if mat:
            f.attrs["mat"] = mat
        if layer:
            f.attrs["layer"] = layer
    g = Group(m, name=name)
    g.xform = QMatrix4x4()
    g.xform.translate(*at)
    g.component = True
    return g


def _scene_with(comp, mat=None, layer=None):
    from core.layers import Layer
    from core.materials import Material
    from core.scene import Scene
    s = Scene()
    s.groups.append(comp)
    if mat:
        s.materials[mat] = Material(name=mat, color=(0.8, 0.2, 0.1))
        s.materials["Sin usar"] = Material(name="Sin usar",
                                           color=(0.1, 0.1, 0.1))
    if layer:
        s.layers.append(Layer(layer))
        s.layers.append(Layer("Otra capa"))
    return s


def _igz(path: Path, name=None) -> Path:
    """A real one-component .igz at ``path``."""
    comp = _box_component(name or path.stem)
    return lib.save_component(comp, _scene_with(comp), path)


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "Mis componentes"
    root.mkdir()
    monkeypatch.setenv("INGETRAZO_USER_LIBRARY", str(root))
    return root


# ---- reading the folders ------------------------------------------------
def test_folders_come_first_sorted_as_read(library):
    (library / "Baño").mkdir()
    (library / "Cocina").mkdir()
    (library / "vacía").mkdir()
    for name in ("Silla 10", "Silla 2", "armario"):
        (library / f"{name}.igz").write_bytes(b"x")
    (library / "Cocina" / "Horno.igz").write_bytes(b"x")
    (library / "notas.txt").write_text("no")
    (library / ".oculta").mkdir()
    (library / ".oculta" / "Secreto.igz").write_bytes(b"x")
    tree = lib.scan(library)
    assert [c.name for c in tree.children] == [
        "Baño", "Cocina", "vacía", "armario", "Silla 2", "Silla 10"]
    assert [c.is_dir for c in tree.children] == [True] * 3 + [False] * 3
    assert [f.name for f in tree.files()] == [
        "Horno", "armario", "Silla 2", "Silla 10"]


def test_an_unreachable_root_is_marked_not_raised(tmp_path):
    tree = lib.scan(tmp_path / "unidad de red apagada")
    assert tree.missing and tree.children == []


def test_the_default_folder_not_made_yet_is_empty_not_missing(
        tmp_path, monkeypatch):
    fresh = tmp_path / "Documents" / "IngeTrazo" / "Components"
    monkeypatch.setattr(lib, "default_folder", lambda: fresh)
    tree = lib.scan(fresh)
    assert not tree.missing and tree.children == []
    assert not fresh.exists()               # reading it creates nothing


def test_the_depth_is_bounded(library):
    deep = library
    for i in range(lib.MAX_DEPTH + 3):
        deep = deep / f"n{i}"
    deep.mkdir(parents=True)
    (deep / "Hondo.igz").write_bytes(b"x")
    assert list(lib.scan(library).files()) == []


def test_the_search_matches_words_without_accents(library):
    (library / "Baño").mkdir()
    (library / "Baño" / "Lavabo.igz").write_bytes(b"x")
    (library / "Cocina").mkdir()
    (library / "Cocina" / "Mesa redonda.igz").write_bytes(b"x")
    (library / "Mesa cuadrada.igz").write_bytes(b"x")
    tree = lib.scan(library)
    hit = lib.filtered(tree, "MESA red")
    assert [f.name for f in hit.files()] == ["Mesa redonda"]
    # A folder whose name matches comes whole.
    hit = lib.filtered(tree, "bano")
    assert [f.name for f in hit.files()] == ["Lavabo"]
    assert lib.filtered(tree, "piano") is None
    assert lib.filtered(tree, "  ") is tree


def test_folders_from_the_settings_without_repeats(tmp_path, monkeypatch):
    monkeypatch.delenv("INGETRAZO_USER_LIBRARY", raising=False)
    lib.set_folders([])
    try:
        assert lib.folders() == [lib.default_folder()]
        a, b = tmp_path / "a", tmp_path / "b"
        assert lib.add_folder(a)
        assert lib.add_folder(b)
        assert not lib.add_folder(a)
        # The folder that was showing stays: + adds, it does not replace.
        default = lib.default_folder()
        assert lib.folders() == [default, a, b]
        lib.remove_folder(default)
        lib.remove_folder(a)
        assert lib.folders() == [b]
        # With every one removed, the default is back: never no library.
        lib.remove_folder(b)
        assert lib.folders() == [default]
    finally:
        lib.set_folders([])


def test_the_environment_list_wins(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("INGETRAZO_USER_LIBRARY",
                       os.pathsep.join([str(a), str(b), str(a)]))
    assert lib.folders() == [a, b]


# ---- names, folders, moves ----------------------------------------------
def test_names_every_system_accepts():
    assert lib.safe_name('Silla: "nueva"/2?') == "Silla- -nueva--2-"
    assert lib.safe_name("  ") == "Component"
    assert lib.safe_name("CON") == "_CON"
    assert lib.safe_name("Mesa. ") == "Mesa"


def test_a_taken_name_is_numbered(library):
    (library / "Mesa.igz").write_bytes(b"x")
    (library / "Mesa (2).igz").write_bytes(b"x")
    assert lib.unique_path(library, "Mesa").name == "Mesa (3).igz"
    assert lib.new_folder(library, "Mesa").name == "Mesa"
    assert lib.new_folder(library, "Mesa").name == "Mesa (2)"


def test_rename_keeps_the_suffix_and_refuses_a_taken_name(library):
    a = library / "Mesa.igz"
    a.write_bytes(b"x")
    (library / "Silla.igz").write_bytes(b"x")
    b = lib.rename(a, "Mesa larga")
    assert b == library / "Mesa larga.igz" and b.exists()
    with pytest.raises(FileExistsError):
        lib.rename(b, "Silla")
    folder = lib.new_folder(library, "Cocina")
    assert lib.rename(folder, "Cocinas").name == "Cocinas"


def test_move_into_a_folder_and_never_into_itself(library):
    f = library / "Mesa.igz"
    f.write_bytes(b"x")
    cocina = lib.new_folder(library, "Cocina")
    (cocina / "Mesa.igz").write_bytes(b"y")
    moved = lib.move_into(f, cocina)
    assert moved == cocina / "Mesa (2).igz" and not f.exists()
    sub = lib.new_folder(cocina, "Encimeras")
    with pytest.raises(ValueError):
        lib.move_into(cocina, sub)
    assert lib.move_into(moved, cocina) == moved


# ---- saving and reading a component -------------------------------------
def test_a_saved_component_comes_back_alone_at_its_own_axes(tmp_path):
    comp = _box_component("Banco", at=(40.0, -3.0, 2.0), mat="Ladrillo",
                          layer="Mobiliario")
    scene = _scene_with(comp, mat="Ladrillo", layer="Mobiliario")
    xform_before = QMatrix4x4(comp.xform)
    path = lib.save_component(comp, scene, tmp_path / "sub" / "Banco")
    assert path == tmp_path / "sub" / "Banco.igz" and path.exists()
    # The open document is as it was.
    assert comp.xform == xform_before and scene.groups == [comp]

    from core.scene import Scene
    from formats import igz
    doc = Scene()
    igz.load_into(doc, path)
    assert len(doc.groups) == 1
    assert set(doc.materials) == {"Ladrillo"}          # only what it wears
    assert {ly.name for ly in doc.layers} >= {"Mobiliario"}
    assert "Otra capa" not in {ly.name for ly in doc.layers}

    back = lib.load_component(path)
    assert back.name == "Banco" and back.is_component()
    assert back.xform == QMatrix4x4()                  # not at (40, -3, 2)
    assert len(back.mesh.faces) == 6


def test_the_picture_cache_follows_the_file(library):
    path = _igz(library / "Mesa.igz")
    first = lib.thumbnail_path(path, 40)
    os.utime(path, ns=(1, 1))
    assert lib.thumbnail_path(path, 40) != first
    assert lib.thumbnail_path(library / "no.igz", 40) is None


# ---- in the window --------------------------------------------------------
def _window():
    QApplication.instance() or QApplication([])
    from views.main_window import MainWindow
    return MainWindow()


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _widget(win):
    return win.tray.components.user_library


def _row(widget, name):
    for it in widget.items():
        if it.text(0) == name:
            return it
    raise AssertionError(f"no row {name!r}: "
                         f"{[i.text(0) for i in widget.items()]}")


def test_the_tray_shows_the_library_as_a_tree(library):
    cocina = lib.new_folder(library, "Cocina")
    _igz(cocina / "Horno.igz")
    _igz(library / "Mesa.igz")
    win = _window()
    try:
        w = _widget(win)
        w.refresh()
        root = w.tree.topLevelItem(0)
        assert root.text(0) == library.name and root.isExpanded()
        assert [root.child(i).text(0) for i in range(root.childCount())] \
            == ["Cocina", "Mesa"]
        assert _row(w, "Horno").parent().text(0) == "Cocina"
        w._search.setText("horn")
        assert [i.text(0) for i in w.file_items()] == ["Horno"]
        w._search.setText("zzz")
        assert w.file_items() == [] and not w._hint.isHidden()
    finally:
        _close(win)


def test_an_empty_library_says_how_to_fill_it(library):
    win = _window()
    try:
        w = _widget(win)
        w.refresh()
        assert "Save to My Library" in w._hint.text()
    finally:
        _close(win)


def test_a_double_click_places_the_component(library):
    _igz(library / "Mesa.igz")
    win = _window()
    try:
        w = _widget(win)
        w.refresh()
        before = len(win.viewport.scene.groups)
        w._on_double_click(_row(w, "Mesa"))
        tool = win.viewport.active_tool
        tool.place_at(win.viewport, V(1, 2, 0))
        groups = win.viewport.scene.groups
        assert len(groups) == before + 1
        placed = groups[-1]
        assert placed.name == "Mesa" and placed.is_component()
        assert placed.xform.map(V(0, 0, 0)) == V(1, 2, 0)
    finally:
        _close(win)


def test_save_to_my_library_from_a_folder_row(library):
    cocina = lib.new_folder(library, "Cocina")
    win = _window()
    try:
        w = _widget(win)
        comp = _box_component("Fregadero")
        scene = win.viewport.scene
        scene.groups.append(comp)
        win.viewport.notify_scene_changed()
        w.refresh()
        folder_row = _row(w, "Cocina")
        acts = {t: cb for t, cb, _tip in w.menu_actions(folder_row) if t}
        assert acts["Save Selected Component Here"] is None   # nothing picked
        scene.selection = {comp}
        acts = {t: cb for t, cb, _tip in w.menu_actions(folder_row) if t}
        acts["Save Selected Component Here"]()
        assert (cocina / "Fregadero.igz").exists()
        # The tree was read again and shows it.
        assert _row(w, "Fregadero").parent().text(0) == "Cocina"
        # Saved again: a second file, numbered, never the first overwritten.
        win.save_component_to_library(comp, cocina)
        assert (cocina / "Fregadero (2).igz").exists()
    finally:
        _close(win)


def test_the_in_model_list_offers_save_to_my_library(library):
    win = _window()
    try:
        comp = _box_component("Lámpara")
        win.viewport.scene.groups.append(comp)
        panel = win.tray.components
        texts = [t for t, *_ in panel._in_model_actions([comp])]
        assert "Save to My Library…" in texts
        win.viewport.scene.selection = {comp}
        assert win.selected_component_definition() is comp
        other = _box_component("Otra")
        win.viewport.scene.groups.append(other)
        win.viewport.scene.selection = {comp, other}
        assert win.selected_component_definition() is None
    finally:
        _close(win)


def test_a_drop_on_a_folder_moves_the_file(library):
    cocina = lib.new_folder(library, "Cocina")
    _igz(library / "Mesa.igz")
    win = _window()
    try:
        w = _widget(win)
        w.refresh()
        w.move_rows(_row(w, "Cocina"), [_row(w, "Mesa")])
        assert (cocina / "Mesa.igz").exists()
        assert not (library / "Mesa.igz").exists()
        assert _row(w, "Mesa").parent().text(0) == "Cocina"
        # The root itself never moves.
        w.move_rows(_row(w, "Cocina"), [w.tree.topLevelItem(0)])
        assert library.is_dir()
    finally:
        _close(win)


def test_new_folder_and_rename_from_the_tree(library):
    _igz(library / "Mesa.igz")
    win = _window()
    try:
        w = _widget(win)
        w.refresh()
        made = w.new_folder(library, "Exterior")
        assert made == library / "Exterior" and made.is_dir()
        w.rename(_row(w, "Mesa"), "Mesa de jardín")
        assert (library / "Mesa de jardín.igz").exists()
        assert _row(w, "Mesa de jardín")
    finally:
        _close(win)


def test_opening_a_folder_draws_the_pictures_it_shows(library):
    cocina = lib.new_folder(library, "Cocina")
    _igz(cocina / "Horno.igz")
    win = _window()
    try:
        w = _widget(win)
        w.resize(300, 400)
        w.show()
        w.refresh()
        folder = _row(w, "Cocina")
        folder.setExpanded(False)
        w._thumb_timer.stop()
        for _ in range(5):
            w._draw_one_thumb()             # nothing left on screen
        assert not w._thumb_timer.isActive()
        folder.setExpanded(True)
        assert w._thumb_timer.isActive()
        for _ in range(5):
            w._draw_one_thumb()
        assert _row(w, "Horno").data(0, Qt.UserRole + 3)
    finally:
        w.hide()
        _close(win)


def test_the_picture_is_drawn_once_and_kept(library):
    from views.user_library import ICON, UserLibraryWidget
    path = _igz(library / "Mesa.igz")
    icon = UserLibraryWidget.picture(path)
    assert icon is not None and not icon.isNull()
    assert lib.thumbnail_path(path, ICON).exists()
    broken = library / "Roto.igz"
    broken.write_bytes(b"no es un zip")
    assert UserLibraryWidget.picture(broken) is None
