# SPDX-License-Identifier: GPL-3.0-or-later
"""A component clicked in the tray's «In model» list stays lit (#636).

The click selects the instances, the selection bumps the scene, and the
refresh that follows rebuilt the list: the row lit for a fraction of a
second and went dark. The rebuilt list lights the row whose instances are
selected."""
from __future__ import annotations

from PySide6.QtCore import Qt

from tests.test_in_model_nested import _close, _component, _quad, _window
from core.group import copy_group


def test_the_clicked_row_is_still_lit_after_the_refresh():
    win = _window()
    try:
        scene = win.viewport.scene
        silla = _component(_quad(), "Silla")
        mesa = _component(_quad(2.0), "Mesa", dx=5.0)
        scene.groups += [silla, copy_group(silla), mesa]
        panel = win.tray.components
        panel.refresh_in_model()
        row = next(panel._in_model.item(i)
                   for i in range(panel._in_model.count())
                   if (panel._in_model.item(i).data(Qt.UserRole) or [None])[0]
                   is not None
                   and panel._in_model.item(i).data(Qt.UserRole)[0].name
                   == "Silla")
        panel._in_model.itemClicked.emit(row)          # the user's click
        assert {g.name for g in scene.selection} == {"Silla"}
        panel.refresh_in_model()                        # the deferred refresh
        current = panel._in_model.currentItem()
        assert current is not None
        assert current.data(Qt.UserRole)[0].name == "Silla"
        scene.selection.clear()                         # click in empty space
        panel.refresh_in_model()
        assert panel._in_model.currentItem() is None
    finally:
        _close(win)
