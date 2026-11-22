# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The toolbar and menu icons fill their canvas at one optical size:
each drawing is scaled and centred until it has the area of an
``_OPTICAL`` square, its long side never past ``_M`` (1 px of the 48 px
render) from the edge, with the lines kept at their weight. Before, the
drawings used about the middle two thirds and looked small in their
buttons; touching the margin every one, the squares looked bigger than
the long shapes."""

import time

import pytest
from PySide6.QtCore import QPointF


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def icons(qapp):
    from views import icons as mod
    mod._fit_cache.clear()
    yield mod
    mod._fit_cache.clear()


def _box(icons, key):
    pm = icons.tool_icon(key).pixmap(icons._PX, icons._PX)
    return icons.ink_bounds(pm)


def test_every_icon_takes_its_optical_size(icons):
    off = []
    for key in icons._DRAW:
        if key in icons.FULL_WEIGHT:
            continue
        box = _box(icons, key)
        if box is None:
            continue
        side = max(box.width(), box.height())
        want = icons._target_side(box.width(), box.height(),
                                  icons._factor_cache[key])
        if abs(side - want) > 2:
            off.append((key, side, round(want, 1)))
    assert not off, f"icons off their optical size: {off[:8]}"


def test_a_square_stops_at_the_optical_size_and_a_long_shape_at_the_margin(
        icons):
    room = icons._PX - 2 * icons._M
    assert icons._target_side(30, 30) == icons._OPTICAL
    assert icons._target_side(40, 10) == room
    # In between, the long side grows with the shape's length.
    assert icons._OPTICAL < icons._target_side(36, 32) < room


def test_a_filled_square_and_a_bar_read_alike(icons, monkeypatch):
    """A block and a wider bar: the block no longer fills the canvas, the
    bar reaches the margin — about the same inked area. (A much longer
    bar is capped by the margin and stays lighter: it cannot grow more.)"""
    from PySide6.QtCore import QRectF

    def block(p, ink):
        p.fillRect(QRectF(16, 16, 16, 16), ink)

    def bar(p, ink):
        p.fillRect(QRectF(14, 17, 20, 14), ink)

    monkeypatch.setitem(icons._DRAW, "_stub_block", block)
    monkeypatch.setitem(icons._DRAW, "_stub_bar", bar)
    b, r = _box(icons, "_stub_block"), _box(icons, "_stub_bar")
    solid = icons._INK_RANGE[0]                 # both are solid: trimmed
    assert abs(b.width() - icons._OPTICAL * solid) <= 1
    assert abs(r.width() - icons._target_side(20, 14, solid)) <= 1.5
    ratio = (b.width() * b.height()) / (r.width() * r.height())
    assert 0.8 < ratio < 1.25


def test_a_solid_shape_is_drawn_smaller_than_its_outline(icons, monkeypatch):
    """Ink weight: a filled square looks bigger than an outlined one of the
    same size, so it is trimmed; a thin outline grows a touch."""
    from PySide6.QtCore import QRectF

    def solid(p, ink):
        p.fillRect(QRectF(12, 12, 24, 24), ink)

    def outline(p, ink):
        p.drawRect(QRectF(12, 12, 24, 24))

    monkeypatch.setitem(icons._DRAW, "_stub_solid", solid)
    monkeypatch.setitem(icons._DRAW, "_stub_outline", outline)
    s, o = _box(icons, "_stub_solid"), _box(icons, "_stub_outline")
    assert s.width() < o.width() - 3
    assert icons._factor_cache["_stub_solid"] == icons._INK_RANGE[0]
    assert icons._factor_cache["_stub_outline"] >= 1.0


def test_the_select_arrow_and_the_house_views_are_trimmed(icons):
    """The solid select arrow stood out, larger than its neighbours, and
    the filled house views looked bigger than the outline icons."""
    for key in ("select", "view_iso", "view_top", "view_front",
                "view_back", "view_right", "view_left"):
        icons.tool_icon(key)
        assert icons._factor_cache[key] < 0.95, key
    icons.tool_icon("line")
    assert icons._factor_cache["line"] >= 1.0
    # The house views stay within a few pixels of each other.
    sides = [max(_box(icons, k).width(), _box(icons, k).height())
             for k in ("view_front", "view_back", "view_right", "view_left",
                       "view_iso", "view_top", "view_bottom")]
    assert max(sides) - min(sides) <= 6


def test_no_icon_crosses_the_margin_and_each_is_centred(icons):
    lo, hi = icons._M - 1, icons._PX - icons._M + 1
    bad = []
    for key in icons._DRAW:
        if key in icons.FULL_WEIGHT:
            continue
        box = _box(icons, key)
        if box is None:
            continue
        inside = (box.left() >= lo and box.top() >= lo
                  and box.right() <= hi and box.bottom() <= hi)
        centred = (abs(box.center().x() - icons._PX / 2) <= 1.5
                   and abs(box.center().y() - icons._PX / 2) <= 1.5)
        if not (inside and centred):
            bad.append((key, box.getRect()))
    assert not bad, f"icons cut or off-centre: {bad[:8]}"


def test_a_small_synthetic_drawing_grows_but_its_line_keeps_its_weight(
        icons, monkeypatch):
    """A short horizontal stroke in the middle: fitted, it spans the canvas
    but for the margin, and stays as thin as it was drawn."""

    def stub(p, ink):
        p.drawLine(QPointF(20, 24), QPointF(28, 24))

    monkeypatch.setitem(icons._DRAW, "_stub_line", stub)
    raw = icons.ink_bounds(icons._render(stub, icons.ICON_STROKE))
    fitted = _box(icons, "_stub_line")
    assert raw.width() < 14
    assert fitted.width() >= icons._PX - 2 * icons._M - 2
    assert fitted.height() <= raw.height() + 1


def test_the_more_tools_chevrons_keep_their_size(icons):
    """They sit on a 12 px button: left as drawn."""
    for key in icons.FULL_WEIGHT:
        drawn = icons.ink_bounds(icons._render(icons._DRAW[key], 1.0))
        assert _box(icons, key).getRect() == drawn.getRect()


def test_fitting_every_icon_is_quick_and_then_cached(icons):
    t0 = time.perf_counter()
    for key in icons._DRAW:
        icons.tool_icon(key)
    first = time.perf_counter() - t0
    assert first < 5.0
    assert set(icons._fit_cache) >= set(icons._DRAW) - icons.FULL_WEIGHT


def test_the_default_toolbar_icon_is_small(qapp, tmp_path, monkeypatch):
    """20 px by default now that the drawings fill it: the bars are
    narrower and the icons read as large as the old 24 px ones."""
    from PySide6.QtCore import QSettings
    from views import icons as mod
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    st = QSettings()
    st.remove("ui/toolbar_icon_px")
    st.remove("ui/large_toolbar_icons")
    assert mod.default_toolbar_icon_px() == 20
    assert mod.toolbar_icon_px() == 20
