# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The status bar shows ONE hint for the tool and its step (Marco,
2026-09-15: a strip of every shortcut at once «no es bueno»)."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from tools.arc import ArcTool
from tools.fillet import FilletTool
from tools.line import LineTool
from views.status_hints import HINTS, NAV_HINTS, hint_for, phase_of


def test_the_hint_follows_the_tools_step():
    line = LineTool()
    idle = hint_for("line", line)
    assert idle.startswith("Click the start point")
    line.start_point = QVector3D(0, 0, 0)
    assert hint_for("line", line).startswith("Click the end point")
    arc = ArcTool()
    assert phase_of("arc", arc) == "idle"
    arc.start_point = QVector3D(0, 0, 0)
    assert phase_of("arc", arc) == "end"
    arc.end_point = QVector3D(1, 0, 0)
    assert phase_of("arc", arc) == "bulge"
    assert "Ns" in hint_for("arc", arc)
    fil = FilletTool()
    assert "size" in hint_for("fillet", fil)
    assert "Ctrl = measure (Radius)" in hint_for("fillet", fil)
    fil.sizing = True
    assert phase_of("fillet", fil) == "sizing"
    assert "'0.3p' = profile" in hint_for("fillet", fil)


def test_navigation_and_unknown_tools_have_a_line_too():
    class Odd:
        name = "Odd"
    assert hint_for(None, Odd()).startswith("Odd")
    assert hint_for("line", LineTool(), nav_mode="orbit") == NAV_HINTS["orbit"]


def test_every_registered_tool_has_a_hint():
    from PySide6.QtWidgets import QApplication
    import pytest
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.main_window import MainWindow
    win = MainWindow()
    missing = [k for k in win._tools if k not in HINTS and not k.startswith("plugin_")]
    assert not missing, missing
    win._activate_tool("line")
    # The tool's name leads its hint (it used to sit apart on the right).
    assert win.status_hint.startswith("Line — Click the start point")
    assert win.statusBar().currentMessage().startswith("Line — Click the start point")
    win._activate_nav("orbit")
    assert win.status_hint.startswith("Orbit — Drag to orbit")
    # The Model | Sheet strip stays first: no normal widget was added left of it.
    from views.sheet_tabs import SheetTabs
    bar = win.statusBar()
    kids = [w for w in bar.findChildren(SheetTabs)]
    win.show()
    app.processEvents()
    tabs = kids[0]
    assert tabs.x() <= bar._msg.x()            # the strip, then the hint
    # A timed message covers the hint and the hint comes back.
    win.viewport.flash_status("Guide at 2.2 m", 50)
    assert bar.currentMessage().startswith("Guide at")
    bar._restore()
    assert bar.currentMessage().startswith("Orbit — Drag to orbit")
    win.close()


def test_the_message_keeps_to_its_share_of_the_bar():
    from PySide6.QtWidgets import QApplication
    import pytest
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    elif not isinstance(app, QApplication):
        pytest.skip("another Qt application flavour is already running")
    from views.sheet_tabs import SheetStatusBar
    bar = SheetStatusBar(None, on_model=lambda: None, on_sheet=lambda i: None)
    bar.show()
    bar.resize(1600, 28)
    app.processEvents()
    assert bar._msg.maximumWidth() == int(1600 * bar.MESSAGE_SHARE)
    bar.showMessage("Select objects.")
    app.processEvents()
    assert bar._msg.x() < 200                   # glued to the left, after the strip
    assert bar._msg.width() >= 700
    bar.resize(200, 28)
    app.processEvents()
    assert bar._msg.maximumWidth() == 120       # never squeezed to nothing
    bar.close()
