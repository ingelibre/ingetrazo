# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Right-to-left interface for Arabic (#1067).

Arabic mirrors the interface at start-up; every left-to-right language
starts exactly as before. Inside the mirrored interface the 3D view, the
sheet canvas and the number fields stay left to right, the toolbars keep
their order (first bar at the right), fold arrows point the reading way
and the swatch grid fills from the right.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtWidgets import (QApplication, QDoubleSpinBox, QToolBar,
                               QToolButton, QWidget)

from core import i18n

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def rtl_app():
    """The application mirrored for the test, put back afterwards."""
    from views.rtl import apply_language_direction
    apply_language_direction(_app, "ar")
    try:
        yield _app
    finally:
        _app.setLayoutDirection(Qt.LeftToRight)
        f = getattr(_app, "_rtl_numbers", None)
        if f is not None:
            _app.removeEventFilter(f)
            _app._rtl_numbers = None


def test_rtl_languages():
    assert i18n.is_rtl("ar")
    assert i18n.is_rtl("fa-IR") and i18n.is_rtl("he") and i18n.is_rtl("ur")
    for lang in ("es", "en", "pt-BR", "zh-CN", "uk", "vi", "", None):
        assert not i18n.is_rtl(lang)


def test_arabic_is_offered_and_complete():
    assert i18n.LANGUAGE_NAMES["ar"] == "العربية"
    assert "ar" in i18n.available_languages()
    before = i18n.current_language()
    try:
        i18n.set_language("ar")
        # The «AI» tab: artificial intelligence, not Amnesty International.
        assert i18n.tr("AI") == "الذكاء الاصطناعي"
    finally:
        i18n.set_language(before)


@pytest.mark.parametrize("lang, direction", [
    ("ar", Qt.RightToLeft), ("es", Qt.LeftToRight), ("en", Qt.LeftToRight),
    ("de", Qt.LeftToRight)])
def test_startup_direction_follows_the_language(lang, direction, tmp_path,
                                                monkeypatch):
    import main
    path = tmp_path / "start.ini"
    st = QSettings(str(path), QSettings.IniFormat)
    st.setValue("language", lang)
    st.sync()
    monkeypatch.setattr(main, "QSettings",
                        lambda: QSettings(str(path), QSettings.IniFormat))
    monkeypatch.setattr(main, "_install_qt_translator", lambda _l: None)
    before = i18n.current_language()
    try:
        main._init_language()
        assert _app.layoutDirection() == direction
        # Left to right nothing is installed: the app is as it always was.
        assert (getattr(_app, "_rtl_numbers", None) is not None) == (
            direction == Qt.RightToLeft)
    finally:
        i18n.set_language(before)
        _app.setLayoutDirection(Qt.LeftToRight)
        f = getattr(_app, "_rtl_numbers", None)
        if f is not None:
            _app.removeEventFilter(f)
            _app._rtl_numbers = None


def test_number_fields_stay_left_to_right(rtl_app):
    box = QDoubleSpinBox()
    box.show()
    rtl_app.processEvents()
    assert box.layoutDirection() == Qt.LeftToRight
    plain = QWidget()
    assert plain.layoutDirection() == Qt.RightToLeft
    box.close()


def test_fold_arrow_left_to_right_is_untouched():
    from views.rtl import set_arrow
    b = QToolButton()
    set_arrow(b, Qt.RightArrow)
    assert b.arrowType() == Qt.RightArrow and b.icon().isNull()


def test_fold_arrow_right_to_left_is_an_icon(rtl_app):
    from views.rtl import set_arrow
    b = QToolButton()
    b.setText("x")
    set_arrow(b, Qt.RightArrow)
    assert b.arrowType() == Qt.NoArrow and not b.icon().isNull()
    set_arrow(b, Qt.NoArrow)
    assert b.icon().isNull()


def test_isolate_only_right_to_left(rtl_app):
    from views.rtl import isolate_ltr
    w = QWidget()
    assert isolate_ltr("+3", w) == "⁦+3⁩"
    w.setLayoutDirection(Qt.LeftToRight)
    assert isolate_ltr("+3", w) == "+3"


def _flow(direction):
    from views.tray import FlowLayout
    host = QWidget()
    host.setLayoutDirection(direction)
    lay = FlowLayout(host)
    kids = []
    for _ in range(3):
        k = QWidget()
        k.setFixedSize(40, 20)
        lay.addWidget(k)
        kids.append(k)
    lay.setGeometry(QRect(0, 0, 200, 100))
    return [k.geometry() for k in kids]


def test_flow_layout_fills_from_the_right_only_right_to_left():
    ltr = _flow(Qt.LeftToRight)
    assert [g.x() for g in ltr] == [0, 42, 84]
    rtl = _flow(Qt.RightToLeft)
    assert [g.right() for g in rtl] == [199, 157, 115]


def test_views_and_canvas_are_not_mirrored(rtl_app):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        assert win.isRightToLeft()
        assert win.viewport.layoutDirection() == Qt.LeftToRight
        assert win._vcb_value.layoutDirection() == Qt.LeftToRight
        comp = win._ensure_composer()
        assert comp._canvas_area.layoutDirection() == Qt.LeftToRight
        assert comp.isRightToLeft()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
        win.deleteLater()


def test_toolbars_keep_their_order_right_to_left(rtl_app):
    """The first bar of the top row (the one with Select) is its rightmost
    one, and nothing in that row is cut to its overflow arrow that was not
    cut left to right — the bars came back reversed and the first ones
    were lost in the overflow."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        win.resize(1500, 950)
        win.show()
        rtl_app.processEvents()
        win._pack_toolbars()
        rtl_app.processEvents()
        top = [tb for tb in win.findChildren(QToolBar)
               if tb.isVisible() and not tb.isFloating()
               and win.toolBarArea(tb) == Qt.TopToolBarArea]
        first_row = min(tb.geometry().y() for tb in top)
        row = [tb for tb in top if tb.geometry().y() == first_row]
        rightmost = max(row, key=lambda tb: tb.geometry().right())
        assert rightmost.objectName() == "main"
        order = sorted(row, key=win._toolbar_seat_key(False))
        assert order[0] is rightmost
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
        win.deleteLater()
