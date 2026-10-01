# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #205: a render light is selected by clicking its bulb with the
Select tool and deleted with Supr, one undo step — through the extension
API's ``add_pickable``, without the model's selection ever holding it."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication([])

from core import render_blender as rb  # noqa: E402
from tools.base import ToolContext  # noqa: E402


@pytest.fixture
def window(monkeypatch):
    from core import extensions
    from core.paths import app_root
    monkeypatch.setattr(extensions, "plugin_dirs",
                        lambda: [app_root() / "plugins"])
    monkeypatch.setattr(rb, "find_blender",
                        lambda saved=None: rb.BlenderFound(["/x/blender"],
                                                           "/x/blender"))
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    QApplication.processEvents()
    yield win
    win._saved_version = win.viewport.scene.version
    win.close()


def _panel(win):
    for dock in win._extension_docks:
        if type(dock.widget()).__name__ == "RenderPanel":
            return dock.widget()
    raise AssertionError("no Render tab")


def _click(win, point):
    """A Select-tool click on the pixel where ``point`` is drawn."""
    vp = win.viewport
    win._activate_tool("select")
    px = vp._world_to_pixel(point)
    assert px is not None
    vp.active_tool.on_click(ToolContext(
        viewport=vp, world=point, screen=QPointF(px[0], px[1]),
        modifiers=Qt.NoModifier, snap=None))


def _two_lights(win):
    panel = _panel(win)
    panel.add_light("point", V(0, 0, 3))
    panel.add_light("spot", V(4, 0, 3))
    vp = win.viewport
    vp.camera.fit_to(V(-2, -2, 0), V(6, 2, 4))
    return panel, vp


def test_a_click_on_the_bulb_selects_that_light(window):
    panel, vp = _two_lights(window)
    _click(window, V(4, 0, 3))
    assert vp.extension_pick is not None
    assert panel._view_pick == 1 and panel.selected_index() == 1
    assert not vp.scene.selection            # the model's selection: empty


def test_supr_deletes_it_in_one_undo_step(window):
    from tools.select import delete_selection_or_hover
    panel, vp = _two_lights(window)
    _click(window, V(0, 0, 3))
    assert delete_selection_or_hover(vp) is True
    lights = panel.app.document_data({})["lights"]
    assert [lt["kind"] for lt in lights] == ["spot"]
    assert vp.extension_pick is None and panel._view_pick is None
    assert vp.history.undo()
    assert len(panel.app.document_data({})["lights"]) == 2


def test_a_click_elsewhere_or_esc_lets_it_go(window):
    panel, vp = _two_lights(window)
    _click(window, V(4, 0, 3))
    _click(window, V(2, 0, 0))              # empty ground
    assert vp.extension_pick is None and panel._view_pick is None
    _click(window, V(4, 0, 3))
    vp.escape()
    assert vp.extension_pick is None and panel._view_pick is None


def test_after_an_undo_supr_does_not_delete_by_a_stale_index(window):
    from tools.select import delete_selection_or_hover
    panel, vp = _two_lights(window)
    _click(window, V(4, 0, 3))              # light #1 picked
    vp.history.undo()                        # the spot is gone again
    # Whatever still remembers index 1, the document changed since the
    # pick: Supr lets it go and deletes nothing.
    delete_selection_or_hover(vp)
    assert len(panel.app.document_data({})["lights"]) == 1
    assert vp.extension_pick is None
