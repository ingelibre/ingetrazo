# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A reference image carries a layer like any other entity (``layer_of`` /
``assign_layer`` already handle it), so every road that moves the selection
onto a layer takes it too: the Tag field in Entity Info, right-click ▸ Layer
and the Layers panel's Assign. Before, all three skipped images, so a plan
could only be put on its own layer by deleting and re-importing it."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.image_plane import ImagePlane  # noqa: E402
from core.layers import Layer, is_taggable, layer_of  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def window():
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()


def _image(scene) -> ImagePlane:
    img = ImagePlane("plan.png", QVector3D(0, 0, 0), QVector3D(4, 0, 0),
                     QVector3D(0, 3, 0), aspect=4 / 3)
    scene.image_planes.append(img)
    scene.layers.append(Layer(img.layer))
    scene.layers.append(Layer("Plans"))
    scene.selection.add(img)
    return img


def _panel(window):
    from views.tray import EntityInfoPanel
    return window.findChild(EntityInfoPanel)


def test_an_image_is_taggable():
    img = ImagePlane("plan.png", QVector3D(), QVector3D(1, 0, 0),
                     QVector3D(0, 1, 0))
    assert is_taggable(img)


def test_entity_info_shows_and_changes_the_layer_of_an_image(window):
    scene = window.viewport.scene
    img = _image(scene)
    panel = _panel(window)
    panel.refresh()
    assert panel._layer_box.isVisible()
    assert panel._layer_box.currentData() == img.layer
    panel._layer_box.setCurrentIndex(panel._layer_box.findData("Plans"))
    assert layer_of(img) == "Plans"
    window.viewport.history.undo()
    assert layer_of(img) != "Plans"


def test_right_click_layer_moves_an_image(window):
    scene = window.viewport.scene
    img = _image(scene)
    window._assign_layer("Plans")
    assert layer_of(img) == "Plans"


def test_layers_panel_assign_moves_an_image(window):
    from PySide6.QtCore import Qt
    scene = window.viewport.scene
    img = _image(scene)
    layers = window.tray.layers
    layers.refresh()
    for i in range(layers.tree.topLevelItemCount()):
        item = layers.tree.topLevelItem(i)
        if item.data(0, Qt.UserRole) == "Plans":
            layers.tree.setCurrentItem(item)
    layers._on_assign()
    assert layer_of(img) == "Plans"
