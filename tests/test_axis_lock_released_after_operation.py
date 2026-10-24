# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The arrow-key axis lock lasts one operation, not until Esc (issue #30).

@pacaeiro: «In SK, if you're drawing a line and press Arrow to lock X and
finish drawing the line, the X lock is released automatically. In ingeTrazo
the Axis lock keeps active (it can be released with an Escape key, not a big
deal). If we are trying to somewhat mimic SK, it's a detail to consider.»

It is more than a detail: the lock outlived the line it was for, so the
NEXT line silently came out constrained to the same axis, and the label
stayed on screen claiming a state the user had finished with.

Same shape as the Alt toggle in issue #26 — a mode meant to last one
operation that lasted the session — and released at the same three places
an operation can end: a click that commits, a stroke released, a typed
value applied. The Down-arrow reference is deliberately left alone: it is
bound to an edge the user went and picked.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent, QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _viewport():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    return win, win.viewport


def _close(win, vp):
    win._saved_version = vp.scene.version
    win.close()


def _click(vp, x=5.0, y=5.0):
    vp._dispatch_tool_click(QMouseEvent(
        QMouseEvent.MouseButtonPress, QPointF(x, y), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))


def test_the_lock_goes_the_moment_the_SEGMENT_exists():
    """Corrected 2026-09-18 by @pacaeiro, testing 0.4.4: «I draw a line with
    hard lock (arrows) and, after the line is created the lock is still
    active».

    This test used to assert the opposite — that the lock survives the
    second click — and that was my reading, not the real behaviour. The first fix
    released the lock when the OPERATION ended, and for the Line tool the
    operation is the whole polyline, because it chains. He means the
    moment the line EXISTS. He draws this way every day; the test was
    encoding my guess over his measurement.

    The signal is «did this click make something», not «is the tool idle».
    """
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        vp.active_tool.start_point = QVector3D(0.0, 0.0, 0.0)
        vp.axis_lock = "x"
        _click(vp)                       # this one commits a segment
        assert vp.axis_lock is None
    finally:
        _close(win, vp)


def test_but_a_click_that_makes_NOTHING_keeps_it():
    """The first click of a line only sets the start point, so a lock taken
    before it must still be there to constrain the segment — otherwise the
    lock would be useless in the only place it is used."""
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        vp.axis_lock = "x"
        _click(vp)                       # first click: nothing committed
        assert vp.axis_lock == "x"
        assert vp._tool_busy(vp.active_tool), "the line is under way"
    finally:
        _close(win, vp)


def test_the_lock_goes_when_the_line_is_finished():
    """The Line tool CHAINS — after the second click it keeps drawing from
    there — so «the operation» is the whole polyline, and it ends when the
    chain does: closing the loop resets the tool, and the lock goes with
    it. (Ending with Esc was already covered: releasing the constraint is
    the cascade's second step.)"""
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        tool = vp.active_tool
        tool.start_point = QVector3D(1.0, 0.0, 0.0)
        vp.axis_lock = "x"
        tool._reset()                              # the chain closed
        vp._release_axis_lock_after_operation()
        assert vp.axis_lock is None
    finally:
        _close(win, vp)


def test_switching_tool_drops_it_too():
    """The leak that was worse than the report: this reset cleared every
    other sticky state and forgot the axis lock, so a lock taken while
    drawing a line silently constrained the next tool."""
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        vp.axis_lock = "x"
        win._activate_tool("rectangle")
        assert vp.axis_lock is None
    finally:
        _close(win, vp)


def test_a_typed_length_ends_the_operation_too():
    """The lock is released however the line ends, and typing a distance and
    pressing Enter is the other way to end one."""
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        vp.axis_lock = "y"
        vp.active_tool.start_point = None
        vp._release_axis_lock_after_operation()
        assert vp.axis_lock is None
    finally:
        _close(win, vp)


def test_a_typed_length_actually_drops_the_lock():
    """The path that had the bug (Marco): the Line tool chains, so the
    instant the typed value commits a segment the tool is STILL busy. The
    old code called ``_release_axis_lock_after_operation()`` without the
    committed flag, the busy-tool guard ate it, and the hard lock survived a
    typed length while the second CLICK dropped it. Same commit signal as
    the click path: did this input make geometry?"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        tool = vp.active_tool
        tool.start_point = QVector3D(0.0, 0.0, 0.0)
        tool.hover_point = QVector3D(1.0, 0.0, 0.0)     # pointing along X
        vp.axis_lock = "x"
        before = len(vp.history.undo_stack)
        for ch in "1500":
            vp._handle_value_key(
                QKeyEvent(QEvent.KeyPress, Qt.Key_0, Qt.NoModifier, ch))
        vp._handle_value_key(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r"))
        assert len(vp.history.undo_stack) == before + 1, "the segment exists"
        assert vp.axis_lock is None
    finally:
        _close(win, vp)


def test_the_down_arrow_reference_is_left_alone():
    """Not in the report and not the same gesture: it is bound to an edge
    the user went and picked, and Esc still drops it."""
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        vp.reference_mode = "parallel"
        vp.active_tool.start_point = None
        vp._release_axis_lock_after_operation()
        assert vp.reference_mode == "parallel"
        assert vp.release_constraints() is True     # …and Esc still does
        assert vp.reference_mode is None
    finally:
        _close(win, vp)


def test_esc_still_releases_it_mid_operation():
    """The Esc cascade is untouched: mid-line you can still drop the lock
    without cancelling the line."""
    win, vp = _viewport()
    try:
        win._activate_tool("line")
        vp.active_tool.start_point = QVector3D(0.0, 0.0, 0.0)
        vp.axis_lock = "z"
        assert vp.release_constraints() is True
        assert vp.axis_lock is None
    finally:
        _close(win, vp)
