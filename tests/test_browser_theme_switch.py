# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser repaints its rows' marks when the theme changes with the
app open (views/outliner.py, OutlinerPanel.refresh_icons): its rows set
their icons once, so Light's black eyes and padlocks stayed on Dark's rows
— the Layers tab's #1086, for the Browser.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh
from views import theme
from views.outliner import COL_EYE, COL_LOCK


def _g(name):
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    g = Group(m, name=name)
    g.xform = QMatrix4x4()
    return g


def _lightest(icon) -> int:
    img = (icon if hasattr(icon, "toImage") else icon.pixmap(18, 18)).toImage()
    return max((img.pixelColor(x, y).lightness()
                for x in range(img.width()) for y in range(img.height())
                if img.pixelColor(x, y).alpha() > 200), default=0)


@pytest.fixture
def win():
    from views.main_window import MainWindow
    app = QApplication.instance()
    before = theme.saved_theme()
    theme.apply_theme(app, theme.LIGHT)
    w = MainWindow()
    scene = w.viewport.scene
    scene.groups[:] = [_g("Muro"), _g("Losa")]
    scene.version += 1
    w.project_browser.outliner.refresh()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()
    theme.save_theme(before)
    theme.apply_theme(app, theme.DARK)


@pytest.mark.parametrize("then", [theme.DARK, theme.SLATE])
def test_rows_take_the_new_theme_s_ink(win, then):
    app = QApplication.instance()
    panel = win.project_browser.outliner
    item = next(iter(panel._items.values()))
    assert _lightest(item.icon(COL_EYE)) < 100        # Light: a dark ink
    theme.apply_theme(app, then)
    win._refresh_toolbar_icons()        # what the palette change triggers
    for col in (COL_EYE, COL_LOCK):
        assert _lightest(item.icon(col)) > 150, col  # Dark: a light ink
    head = panel.tree.headerItem()
    assert _lightest(head.icon(COL_EYE)) > 150


def test_and_back_to_light(win):
    app = QApplication.instance()
    panel = win.project_browser.outliner
    item = next(iter(panel._items.values()))
    theme.apply_theme(app, theme.DARK)
    win._refresh_toolbar_icons()
    theme.apply_theme(app, theme.LIGHT)
    win._refresh_toolbar_icons()
    img = item.icon(COL_EYE).pixmap(18, 18).toImage()
    darkest = min(img.pixelColor(x, y).lightness()
                  for x in range(18) for y in range(18)
                  if img.pixelColor(x, y).alpha() > 200)
    assert darkest < 100


def _stale(app, top):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    base = app.palette().base().color()
    window = app.palette().window().color()
    return [w for w in [top, *top.findChildren(QWidget)]
            if not w.testAttribute(Qt.WA_SetPalette) and not w.styleSheet()
            and (w.palette().base().color() != base
                 or w.palette().window().color() != window)]


@pytest.mark.parametrize("modes", [
    (theme.SLATE, theme.DARK, theme.LIGHT),
    (theme.LIGHT, theme.SLATE, theme.DARK, theme.LIGHT),
    (theme.SLATE, theme.DARK, theme.SLATE, theme.LIGHT),
])
def test_no_panel_keeps_an_old_theme(win, modes):
    """Round 19: after Slate's sheet came and went, hundreds of widgets
    (the Properties and Layers tabs, at times the menu bar) kept Dark's
    palette in Light."""
    app = QApplication.instance()
    win.layers_dock.raise_()
    for m in modes:
        theme.apply_theme(app, m)
        app.processEvents()
    assert _stale(app, win) == []


@pytest.mark.parametrize("then", [theme.DARK, theme.SLATE])
def test_the_layers_drop_down_takes_the_new_ink(win, then):
    """Round 20: the closed Layers drop-down kept Light's dark eye and
    padlock on Dark and Slate — its rows are drawn once per set of layers."""
    app = QApplication.instance()
    combo = win.layers_toolbar.combo
    combo.refresh()
    assert combo.count() > 0
    def eye_and_padlock():
        # The row icon holds eye, padlock and swatch side by side: the
        # swatch (white for Layer 0) is left out.
        from views.layers_toolbar import _SWATCH_X
        size = combo.iconSize()
        pm = combo.itemIcon(0).pixmap(size)
        return _lightest(pm.copy(0, 0, _SWATCH_X - 6, pm.height()))
    before = eye_and_padlock()
    theme.apply_theme(app, then)
    win._refresh_toolbar_icons()
    after = eye_and_padlock()
    assert before < 100 < 150 < after
