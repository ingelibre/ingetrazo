# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#152: the Rectangle's VCB takes "200,100" as two values, the usual convention,
while a comma stays the decimal separator everywhere a single value makes
sense ("2,5" is 2.5) and whenever ";" or a space already separates fields."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from views.viewport import Viewport  # noqa: E402


def _parse(text, lists=False):
    return Viewport._parse_value_buffer(text, comma_lists=lists)


def test_a_multi_value_tool_reads_the_comma_as_a_list_separator():
    assert _parse("200,100", lists=True) == pytest.approx((200.0, 100.0))
    assert _parse("3,2,1", lists=True) == pytest.approx((3.0, 2.0, 1.0))
    # with ";" or a space already there, the comma is the decimal again
    assert _parse("2,5;1,2", lists=True) == pytest.approx((2.5, 1.2))
    assert _parse("200, 100", lists=True) == pytest.approx((200.0, 100.0))
    assert _parse("200;100", lists=True) == pytest.approx((200.0, 100.0))


def test_everywhere_else_the_comma_is_still_the_decimal():
    assert _parse("2,5") == pytest.approx(2.5)
    assert _parse("200,100") == pytest.approx(200.1)       # as before
    assert _parse("2,5;1,2") == pytest.approx((2.5, 1.2))
    assert _parse("200 100") == pytest.approx((200.0, 100.0))
    assert _parse("200, 100") == pytest.approx((200.0, 100.0))


def test_typing_200_comma_100_in_the_rectangle_draws_200_by_100():
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        vp = win.viewport
        win._activate_tool("rectangle")
        tool = vp.active_tool
        assert getattr(tool, "vcb_comma_lists", False)
        tool.start_point = QVector3D(0, 0, 0)
        tool.hover_point = QVector3D(1, 1, 0)          # dragging toward +x +y
        got = []
        real = tool.on_value
        tool.on_value = lambda v, value: (got.append(value), real(v, value))[1]
        vp.setFocus()
        QTest.keyClicks(vp, "200,100")
        QTest.keyClick(vp, Qt.Key_Return)
        assert got, "Enter did not reach the tool"
        assert got[-1] == pytest.approx((200.0, 100.0))
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def _typed(tool_name, keys):
    """The value box after typing ``keys`` with ``tool_name`` active."""
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        vp = win.viewport
        win._activate_tool(tool_name)
        vp.setFocus()
        QTest.keyClicks(vp, keys)
        return vp._value_buffer
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_comma_after_a_decimal_number_starts_the_next_value():
    # #598: «0.9,2.1» lost the comma, because the token already had a
    # decimal point, and became 0.921 without a warning.
    buf = _typed("line", "0.9,2.1")
    assert buf == "0.9;2.1"
    assert _parse(buf) == pytest.approx((0.9, 2.1))
    buf = _typed("line", "2,5,1")
    assert _parse(buf) == pytest.approx((2.5, 1.0))
    # a second decimal point is still refused
    assert _typed("line", "0.9.2") == "0.92"


def test_typing_a_comma_list_of_three_in_the_rectangle_keeps_every_comma():
    # Without ";" or a space every comma separates the Rectangle's fields,
    # so a comma after «3,2» is a separator, not a second decimal point.
    buf = _typed("rectangle", "3,2,1")
    assert _parse(buf, lists=True) == pytest.approx((3.0, 2.0, 1.0))
    buf = _typed("rectangle", "0.9,2.1")
    assert _parse(buf, lists=True) == pytest.approx((0.9, 2.1))


def test_mixed_inches_with_a_comma_and_a_space_are_two_values():
    # #189 (@Loonster83): «1 3/8", 1 3/16"» — a mixed number always carries
    # a space, so the comma was read as a decimal point and the whole entry
    # refused; the rectangle kept the cursor's size.
    inch = 0.0254
    want = (1.375 * inch, 1.1875 * inch)
    assert _parse('1 3/8", 1 3/16"', lists=True) == pytest.approx(want)
    assert _parse('1220, 2440', lists=True) == pytest.approx((1220, 2440))
    # the comma between two digits is still a decimal where a space or a
    # semicolon separates the fields
    assert _parse("1,5 2,5", lists=True) == pytest.approx((1.5, 2.5))


def test_a_macs_typographic_quotes_and_one_character_fractions():
    # A Mac turns " into ” and ' into ’ by itself, and ⅜ is one character.
    inch, foot = 0.0254, 0.3048
    assert _parse("1 ⅜”, 1 3/16”", lists=True) == pytest.approx(
        (1.375 * inch, 1.1875 * inch))
    assert _parse("1⅜”;2½”", lists=True) == pytest.approx(
        (1.375 * inch, 2.5 * inch))
    assert _parse("4’6”") == pytest.approx(4 * foot + 6 * inch)


def test_typing_typographic_inches_in_the_rectangle():
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        vp = win.viewport
        win._activate_tool("rectangle")
        tool = vp.active_tool
        tool.start_point = QVector3D(0, 0, 0)
        tool.hover_point = QVector3D(1, 1, 0)
        got = []
        real = tool.on_value
        tool.on_value = lambda v, value: (got.append(value), real(v, value))[1]
        vp.setFocus()
        # QTest.keyClicks only simulates ASCII (it aborts on ⅜): send each
        # character as the key event a Mac keyboard delivers — its text.
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        for ch in "1⅜”, 1 3/16”":
            if ch.isascii():
                QTest.keyClicks(vp, ch)
            else:
                for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                    QApplication.sendEvent(vp, QKeyEvent(
                        kind, Qt.Key_unknown, Qt.NoModifier, ch))
        QTest.keyClick(vp, Qt.Key_Return)
        assert got, "Enter did not reach the tool"
        assert got[-1] == pytest.approx((1.375 * 0.0254, 1.1875 * 0.0254))
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
