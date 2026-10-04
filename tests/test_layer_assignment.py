# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Changing an object's layer where people look for it.

Rafael, 2026-09-16 (39:00–40:00): «no sé cómo cambiar el objeto de capa…
las propiedades del objeto… no lo veo. Botón derecho… no lo veo tampoco.
Asignar selección… algo no había seleccionado bien». The only road was
the Layers panel's button, silent when nothing was selected or no layer
highlighted. Now Entity Info has a Layer field, the right-click has a
Layer submenu, and all three go through one undoable command.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core.group import Group
from core.history import AssignLayerCommand, History
from core.layers import Layer, layer_of
from core.mesh import Mesh
from core.scene import Scene


def _square(mesh, x0=0.0):
    return mesh.add_face([QVector3D(x0, 0, 0), QVector3D(x0 + 1, 0, 0),
                          QVector3D(x0 + 1, 1, 0), QVector3D(x0, 1, 0)])


def test_assign_layer_command_moves_a_mixed_selection_and_undoes_exactly():
    scene = Scene()
    history = History(scene)
    scene.layers.append(Layer("Muros"))
    face = _square(scene.mesh)
    edge = scene.mesh.edges[0]
    g = Group(Mesh(), name="caja")
    g.layer = "Muros"
    scene.groups.append(g)

    history.execute(AssignLayerCommand([face, edge, g], "Mobiliario"))
    assert layer_of(face) == layer_of(edge) == layer_of(g) == "Mobiliario"
    assert scene.layer("Mobiliario") is not None      # created on the way

    history.undo()
    assert layer_of(face) == "Layer 0" and layer_of(edge) == "Layer 0"
    assert layer_of(g) == "Muros"
    assert scene.layer("Mobiliario") is None          # …and taken back
    history.redo()
    assert layer_of(g) == "Mobiliario"


def _window():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win


def test_entity_info_shows_the_layer_and_changes_it():
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.layers.append(Layer("Muros"))
        face = _square(scene.mesh)
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        panel = win.tray.entity_info

        scene.select([face])
        panel.refresh()
        assert panel._layer_box.isVisibleTo(panel)
        assert panel._layer_box.currentData() == "Layer 0"

        idx = panel._layer_box.findData("Muros")
        panel._layer_box.setCurrentIndex(idx)          # the user picks Muros
        assert layer_of(face) == "Muros"
        vp.history.undo()
        assert layer_of(face) == "Layer 0"

        # a mixed selection reads as such, and picking moves everything
        g.layer = "Muros"
        scene.select([face, g])
        panel.refresh()
        assert panel._layer_box.currentData() is None
        assert panel._layer_box.currentText() == "(several)"
        panel._layer_box.setCurrentIndex(panel._layer_box.findData("Muros"))
        assert layer_of(face) == "Muros" and layer_of(g) == "Muros"

        scene.clear_selection()
        panel.refresh()
        assert not panel._layer_box.isVisibleTo(panel)
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_right_click_layer_submenu_and_new_layer():
    from PySide6.QtWidgets import QInputDialog, QMenu
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.layers.append(Layer("Muros"))
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        scene.select([g])
        menu = QMenu()
        win._add_layer_submenu(menu, list(scene.selection))
        sub = [a for a in menu.actions() if a.menu() is not None][0].menu()
        names = [a.text() for a in sub.actions() if not a.isSeparator()]
        assert names[:2] == ["Layer 0", "Muros"] and names[-1] == "New layer…"
        ticked = [a.text() for a in sub.actions() if a.isChecked()]
        assert ticked == ["Layer 0"]
        [a for a in sub.actions() if a.text() == "Muros"][0].trigger()
        assert layer_of(g) == "Muros"

        QInputDialog.getText = staticmethod(lambda *a, **k: ("Jardín", True))
        win._assign_new_layer()
        assert layer_of(g) == "Jardín" and scene.layer("Jardín") is not None
        vp.history.undo()
        assert layer_of(g) == "Muros" and scene.layer("Jardín") is None
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_layers_panel_assign_button_speaks_and_undoes():
    from PySide6.QtCore import Qt
    win = _window()
    vp = win.viewport
    try:
        scene = vp.scene
        scene.layers.append(Layer("Muros"))
        g = Group(Mesh(), name="caja")
        scene.groups.append(g)
        panel = win.tray.layers
        panel.refresh()
        # nothing highlighted in the list: it says so instead of doing nothing
        panel.tree.setCurrentItem(None)
        scene.select([g])
        panel._on_assign()
        assert layer_of(g) == "Layer 0"
        assert "layer" in win.statusBar().currentMessage().lower()
        # highlight Muros, nothing selected in the model: says so too
        item = [panel.tree.topLevelItem(i) for i in range(panel.tree.topLevelItemCount())
                if panel.tree.topLevelItem(i).data(0, Qt.UserRole) == "Muros"][0]
        panel.tree.setCurrentItem(item)
        panel._set_active_layer("Muros")
        scene.clear_selection()
        panel._on_assign()
        assert "select" in win.statusBar().currentMessage().lower()
        # both in place: moves, undoably
        scene.select([g])
        panel._on_assign()
        assert layer_of(g) == "Muros"
        vp.history.undo()
        assert layer_of(g) == "Layer 0"
    finally:
        win._saved_version = vp.scene.version
        win.close()


def test_layer_appearance_dialog_applies_overrides():
    from core.layers import Layer
    from views.tray import LayerAppearanceDialog

    from PySide6.QtWidgets import QPushButton
    from core.scene import Scene
    layer = Layer("Muros")
    scene = Scene()
    scene.layers.append(layer)
    scene.layers.append(Layer("Plans"))
    dialog = LayerAppearanceDialog(layer, scene)
    dialog._name.setText("Walls")
    dialog._parent.setCurrentIndex(dialog._parent.findData("Plans"))
    dialog._transparency.setValue(35)
    dialog._set_color("tint_color", (0.2, 0.4, 0.6))
    dialog._set_color("edge_color", (0.1, 0.2, 0.3))
    assert [button.text() for button in dialog.findChildren(QPushButton)
            if button.text() == "Clear"] == ["Clear", "Clear", "Clear"]
    dialog.apply_to(layer)

    assert layer.tint_color == (0.2, 0.4, 0.6)
    assert layer.edge_color == (0.1, 0.2, 0.3)
    assert layer.parent == "Plans"
    assert layer.transparency == 35
    assert dialog._name.text() == "Walls"


def test_layers_panel_displays_nested_rows_and_color_swatches():
    from PySide6.QtCore import Qt
    from PySide6.QtCore import QSettings
    from core.layers import Layer
    from views.main_window import MainWindow

    win = MainWindow()
    settings = QSettings()
    old_columns = {
        key: settings.value(f"layers/columns/{key}", None)
        for key in ("tint", "line", "transparency")
    }
    try:
        for key in old_columns:
            settings.setValue(f"layers/columns/{key}", True)
        scene = win.viewport.scene
        parent = Layer("Plans", tint_color=(0.1, 0.2, 0.3),
                       transparency=35)
        child = Layer("Walls", parent="Plans",
                      edge_color=(0.8, 0.2, 0.1))
        scene.layers.extend((parent, child))
        panel = win.tray.layers
        panel.refresh()
        root = next(panel.tree.topLevelItem(i)
                    for i in range(panel.tree.topLevelItemCount())
                    if panel.tree.topLevelItem(i).data(0, Qt.UserRole)
                    == "Plans")
        assert root.childCount() == 1
        assert root.child(0).data(0, Qt.UserRole) == "Walls"
        assert panel.tree.columnCount() == 6
        assert [panel.tree.headerItem().text(i)
                for i in range(6)] == [
                    "Name", "Visible", "Lock", "Tint", "Line", "Transp."]
        assert panel.tree.itemWidget(root, 3) is not None
        assert panel.tree.itemWidget(root.child(0), 4) is not None
        assert root.text(3) == root.text(4) == ""
        assert root.child(0).text(3) == root.child(0).text(4) == ""
        assert root.text(5) == "35%"
        assert root.text(0) == "Plans"
        assert root.child(0).text(0) == "Walls"
        assert root.checkState(1) == Qt.Checked
        root.setCheckState(1, Qt.Unchecked)
        assert scene.layer_state("Walls")[0] is False
        action = next(action for action in panel._columns_menu.actions()
                      if action.text() == "Tint")
        action.setChecked(False)
        assert panel.tree.isColumnHidden(3)
        assert not any(panel.tree.isColumnHidden(column)
                       for column in (0, 1, 2))
        assert settings.value("layers/columns/tint", True, type=bool) is False
        assert panel.tree.header().contextMenuPolicy() == \
            Qt.CustomContextMenu
        assert not panel.tree.isSortingEnabled()
        from PySide6.QtWidgets import QHeaderView
        assert panel.tree.header().sectionResizeMode(0) == QHeaderView.Stretch
        assert panel.tree.columnWidth(1) >= panel.tree.header().sectionSizeHint(1)
        assert panel.tree.columnWidth(2) >= panel.tree.header().sectionSizeHint(2)
        assert panel.tree.dragEnabled()
        panel._set_active_layer("Walls")
        current_root = next(panel.tree.topLevelItem(i)
                            for i in range(panel.tree.topLevelItemCount())
                            if panel.tree.topLevelItem(i).data(0, Qt.UserRole)
                            == "Plans")
        wall_item = current_root.child(0)
        assert wall_item.text(0).startswith("● ")
        assert not current_root.text(0).startswith("● ")
        assert "○" not in current_root.text(0)
    finally:
        for key, value in old_columns.items():
            if value is None:
                settings.remove(f"layers/columns/{key}")
            else:
                settings.setValue(f"layers/columns/{key}", value)
        win._saved_version = win.viewport.scene.version
        win.close()


def test_layer_table_multiselect_visibility_and_sorting():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QAbstractItemView, QPushButton
    from core.layers import Layer
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        scene = win.viewport.scene
        scene.layers.extend((Layer("Zulu"), Layer("Alpha")))
        panel = win.tray.layers
        panel.refresh()
        tree = panel.tree
        rows = {
            tree.topLevelItem(i).data(0, Qt.UserRole):
            tree.topLevelItem(i)
            for i in range(tree.topLevelItemCount())
        }
        assert tree.selectionMode() == QAbstractItemView.ExtendedSelection
        rows["Zulu"].setSelected(True)
        rows["Alpha"].setSelected(True)
        rows["Alpha"].setCheckState(1, Qt.Unchecked)
        assert not scene.layer("Alpha").visible
        assert not scene.layer("Zulu").visible
        first = tree.takeTopLevelItem(2)
        tree.insertTopLevelItem(1, first)
        panel._on_layers_reordered()
        assert [layer.name for layer in scene.layers] == [
            "Layer 0", "Alpha", "Zulu"]
        header = tree.header()
        assert header.sectionsClickable()
        x = header.sectionViewportPosition(0) + header.sectionSize(0) // 2
        QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, 5))
        assert tree.isSortingEnabled()
        ordered = [
            tree.topLevelItem(i).data(0, Qt.UserRole)
            for i in range(tree.topLevelItemCount())
        ]
        assert ordered == sorted(ordered)
        panel._on_header_clicked(0)
        assert tree.header().sortIndicatorOrder() == Qt.DescendingOrder
        panel._on_header_clicked(0)
        assert not tree.isSortingEnabled()
        assert [layer.name for layer in scene.layers] == [
            "Layer 0", "Alpha", "Zulu"]
        assert tree.dragEnabled()
        panel._on_header_clicked(0)
        panel._clear_sort()
        assert not tree.isSortingEnabled()
        assert panel._sort_column == -1
        assert any(action.text() == "Clear sort"
                   for action in panel._columns_menu.actions())
        # Choosing the active layer is independent of row selection.
        panel._set_active_layer("Zulu")
        assert panel._active_layer == "Zulu"
        active = next(tree.topLevelItem(i) for i in
                      range(tree.topLevelItemCount())
                      if tree.topLevelItem(i).data(0, Qt.UserRole) == "Zulu")
        assert active.text(0).startswith("● ")
        make_active = next(
            button for button in panel.findChildren(QPushButton)
            if button.text() == "Make active")
        alpha_item = next(
            tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
            if tree.topLevelItem(i).data(0, Qt.UserRole) == "Alpha")
        panel.tree.setCurrentItem(alpha_item)
        make_active.click()
        assert panel._active_layer == "Alpha"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_layer_action_buttons_disable_until_required_selection():
    from PySide6.QtCore import Qt
    from core.group import Group
    from core.layers import DEFAULT_LAYER, Layer
    from core.mesh import Mesh
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        panel = win.tray.layers
        scene = win.viewport.scene
        scene.layers.append(Layer("Walls"))
        panel.refresh()
        panel.tree.setCurrentItem(None)
        panel._update_action_buttons()
        assert not panel.delete_button.isEnabled()
        assert not panel.edit_button.isEnabled()
        assert not panel.active_button.isEnabled()
        assert not panel.assign_button.isEnabled()

        default_item = next(
            panel.tree.topLevelItem(i)
            for i in range(panel.tree.topLevelItemCount())
            if panel.tree.topLevelItem(i).data(0, Qt.UserRole) == DEFAULT_LAYER)
        panel.tree.setCurrentItem(default_item)
        panel._update_action_buttons()
        assert not panel.delete_button.isEnabled()
        assert panel.edit_button.isEnabled()
        assert panel.active_button.isEnabled()

        wall_item = next(
            panel.tree.topLevelItem(i)
            for i in range(panel.tree.topLevelItemCount())
            if panel.tree.topLevelItem(i).data(0, Qt.UserRole) == "Walls")
        panel.tree.setCurrentItem(wall_item)
        panel._update_action_buttons()
        assert panel.delete_button.isEnabled()
        assert panel.edit_button.isEnabled()
        assert panel.active_button.isEnabled()

        group = Group(Mesh(), name="Box")
        scene.select([group])
        panel._update_action_buttons()
        assert panel.assign_button.isEnabled()
        scene.clear_selection()
        panel._update_action_buttons()
        assert not panel.assign_button.isEnabled()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_layers_and_scenes_can_expand_beyond_five_rows():
    from PySide6.QtCore import Qt
    from core.layers import Layer
    from core.saved_views import SavedView
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        scene = win.viewport.scene
        scene.layers.extend(Layer(f"Layer {i}") for i in range(1, 8))
        scene.saved_views.extend(SavedView(f"Scene {i}")
                                 for i in range(1, 8))
        layers = win.tray.layers
        scenes = win.tray.scenes
        layers.refresh()
        scenes.refresh()
        layer_height = layers.tree.height()
        scene_height = scenes.list.height()
        assert layers.tree.minimumHeight() < layer_height
        assert scenes.list.minimumHeight() < scene_height
        layers._resize_handle._view.setFixedHeight(layer_height + 120)
        scenes._resize_handle._view.setFixedHeight(scene_height + 120)
        layers._remember_resize()
        scenes._remember_resize()
        assert layers.tree.height() == layer_height + 120
        assert scenes.list.height() == scene_height + 120
        assert layers._resize_handle.cursor().shape() == Qt.SplitVCursor
        assert scenes._resize_handle.cursor().shape() == Qt.SplitVCursor
        layers._resize_handle._resize_to(layer_height - 80)
        scenes._resize_handle._resize_to(scene_height - 80)
        assert layers.tree.height() == layers._resize_handle._minimum_height
        assert scenes.list.height() == scenes._resize_handle._minimum_height
        assert layers._resize_handle.height() == 14
        assert scenes._resize_handle.height() == 14
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_layer_filter_hides_nonmatches_and_clear_restores_every_row():
    from PySide6.QtCore import Qt
    from core.layers import Layer
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        scene = win.viewport.scene
        scene.layers.extend((
            Layer("Building"), Layer("Walls", parent="Building"),
            Layer("Windows", parent="Building"), Layer("Site"),
        ))
        panel = win.tray.layers
        panel.refresh()
        section = panel.parentWidget()
        assert section._btn.isChecked()
        assert panel.filter_input.isClearButtonEnabled()
        assert panel.tree.topLevelItemCount() >= 2
        rows = {}

        def collect(item):
            rows[item.data(0, Qt.UserRole)] = item
            for index in range(item.childCount()):
                collect(item.child(index))

        for index in range(panel.tree.topLevelItemCount()):
            collect(panel.tree.topLevelItem(index))
        panel.filter_input.setText("walls")
        assert not rows["Building"].isHidden()
        assert not rows["Walls"].isHidden()
        assert rows["Windows"].isHidden()
        assert rows["Site"].isHidden()
        panel.filter_input.clear()
        assert not any(item.isHidden() for item in rows.values())
        assert panel.tree.topLevelItemCount() == 3
        assert panel.tree.viewport().isVisibleTo(panel.tree)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
