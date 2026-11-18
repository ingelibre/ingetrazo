# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #630 in the value box: «=» opens a calculation, every key typed
after it is part of it (no M for Move, no Space for Select), Enter draws
the result, and a calculation that does not add up stays in the box with
the reason, to be fixed instead of typed again."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import units  # noqa: E402
from views.viewport import Viewport  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    units.bind_scene(w.viewport.scene)
    yield w
    w._saved_version = w.viewport.scene.version   # no "save?" modal
    w.close()
    units.bind_scene(None)


def _type(vp, text):
    for ch in text:
        vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, 0, Qt.NoModifier, ch))


def _enter(vp):
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                               Qt.NoModifier, "\r"))


def _override(vp, text):
    ev = QKeyEvent(QEvent.ShortcutOverride, 0, Qt.NoModifier, text)
    vp.event(ev)
    return ev.isAccepted()


def test_the_buffer_reads_calculations():
    parse = Viewport._parse_value_buffer
    assert parse("=1.25*2+2.45/2") == pytest.approx(3.725)
    assert parse("=1.20m + 35cm") == pytest.approx(1.55)
    w, h = parse("=3/2;=1+0,5")
    assert (w, h) == (pytest.approx(1.5), pytest.approx(1.5))
    assert parse("=2*2;1+1;3") == (pytest.approx(4), pytest.approx(2),
                                   pytest.approx(3))     # later «=» optional
    assert parse("=2*2, 1+1") == (pytest.approx(4), pytest.approx(2))
    assert parse("=200,100", comma_lists=True) == pytest.approx(200.1)
    assert parse("=2+") is None
    assert parse("=1;2;3;4") is None


def test_equals_opens_a_calculation_and_every_key_types_into_it(win):
    vp = win.viewport
    win._activate_tool("line")
    assert _override(vp, "=") is True            # not a shortcut
    _type(vp, "=")
    assert vp._value_buffer == "="
    for ch in "m( *+)c ":
        assert _override(vp, ch) is True, ch     # M is not Move here
    _type(vp, "(1.2m + 35cm)*2")
    assert vp._value_buffer == "=(1.2m + 35cm)*2"


def test_letters_outside_a_calculation_stay_shortcuts(win):
    vp = win.viewport
    win._activate_tool("line")
    assert _override(vp, "m") is False
    assert _override(vp, "(") is False


def test_a_calculation_that_does_not_add_up_stays_in_the_box(win):
    vp = win.viewport
    win._activate_tool("line")
    flashed = []
    vp.flash_status = lambda text, ms=0: flashed.append(text)
    _type(vp, "=2m*3m")
    _enter(vp)
    assert vp._value_buffer == "=2m*3m"          # kept, to fix it
    assert flashed and "multipl" in flashed[0].lower()
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Backspace,
                               Qt.NoModifier, ""))
    assert vp._value_buffer == "=2m*3"


def test_a_rectangle_drawn_from_a_calculation(win):
    vp = win.viewport
    win._activate_tool("rectangle")
    tool = vp.active_tool
    tool.start_point = QVector3D(0, 0, 0)
    tool.hover_point = QVector3D(1, 1, 0)
    shown = []
    vp.measurementChanged.connect(shown.append)
    _type(vp, "=1.25*2;=3-0.5")
    _enter(vp)
    assert len(vp.scene.faces) == 1
    xs = [v.x() for v in vp.scene.faces[0].vertices]
    ys = [v.y() for v in vp.scene.faces[0].vertices]
    assert max(xs) - min(xs) == pytest.approx(2.5, abs=1e-6)
    assert max(ys) - min(ys) == pytest.approx(2.5, abs=1e-6)
    assert vp._value_buffer == ""
    assert shown and "=" not in shown[-1]        # the result, not the sum
