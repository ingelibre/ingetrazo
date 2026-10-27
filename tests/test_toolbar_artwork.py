# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Toolbar artwork follows live colors without changing the tool cursors."""
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import QApplication

from views import icons, theme, toolbar_icons


@pytest.fixture(autouse=True)
def restore_palette_and_accent():
    app = QApplication.instance()
    palette, accent = app.palette(), theme.saved_accent()
    yield
    app.setPalette(palette)
    theme.save_accent(accent)
    icons.clear_cursor_cache()


def _pixels(icon, size=48):
    image = icon.pixmap(size, size).toImage()
    return bytes(image.constBits())[:image.sizeInBytes()]


def _has_color(image, color):
    return any(image.pixelColor(x, y) == color
               for y in range(image.height()) for x in range(image.width()))


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("accent", [entry[0] for entry in theme.ACCENTS])
def test_all_icons_render_in_every_preset_and_appearance(mode, accent):
    app = QApplication.instance()
    app.setPalette(theme.dark_palette() if mode == "dark" else theme.light_palette())
    theme.save_accent(accent)
    for key in icons._DRAW:
        icon = icons.tool_icon(key)
        assert not icon.isNull(), key
        image = icon.pixmap(48, 48).toImage()
        assert any(image.pixelColor(x, y).alpha()
                   for y in range(48) for x in range(48)), key
    assert icons.tool_icon("unknown-key").isNull()


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("accent", [entry[0] for entry in theme.ACCENTS])
def test_opaque_accent_details_are_readable_and_keep_the_selected_hue(mode, accent):
    background = (theme.dark_palette() if mode == "dark" else theme.light_palette()).window().color()
    base = theme.accent_color(accent)
    tone = toolbar_icons.accent_tone(base, background)
    assert toolbar_icons._contrast(tone, background) >= (4.5 if mode == "dark" else 3.2)
    assert abs(tone.hslHue() - base.hslHue()) <= 2


def test_live_palette_and_system_accent_are_not_baked_into_cached_icons(monkeypatch):
    app = QApplication.instance()
    theme.save_accent(theme.SYSTEM_ACCENT)
    app.setPalette(theme.light_palette())
    monkeypatch.setattr(theme, "_system_accent", QColor("#e03384"))
    first = icons.tool_icon("line")
    tone = toolbar_icons.accent_tone(theme.accent_color(), app.palette().window().color())
    assert _has_color(first.pixmap(48, 48).toImage(), tone)
    monkeypatch.setattr(theme, "_system_accent", QColor("#3399ee"))
    second = icons.tool_icon("line")
    assert _pixels(first) != _pixels(second)
    app.setPalette(theme.dark_palette())
    third = icons.tool_icon("line")
    assert _pixels(second) != _pixels(third)
    assert _has_color(third.pixmap(48, 48).toImage(), icons._ink())


def test_toolbar_requests_leave_cursor_bitmaps_and_hotspots_unchanged():
    keys = ("rectangle", "line", "offset", "pushpull", "pan", "tape")
    before = {key: (icons.tool_cursor(key).pixmap().toImage(),
                    icons.tool_cursor(key).hotSpot()) for key in keys}
    for key in icons._DRAW:
        icons.tool_icon(key)
    icons.clear_cursor_cache()
    for key, (image, hotspot) in before.items():
        cursor = icons.tool_cursor(key)
        assert cursor.pixmap().toImage() == image
        assert cursor.hotSpot() == hotspot


def test_small_and_hidpi_sizes_have_real_rasters():
    icon = icons.tool_icon("pushpull")
    for size in (20, 24, 32, 40, 48, 80, 96, 120):
        assert QSize(size, size) in icon.availableSizes()
    for logical in (20, 24, 32, 40):
        for dpr in (1.0, 1.5, 2.0, 3.0):
            pm = icon.pixmap(QSize(logical, logical), dpr)
            assert pm.width() == round(logical * dpr)
            assert pm.devicePixelRatio() == dpr


def test_caller_mutation_does_not_corrupt_the_icon_cache():
    first = icons.tool_icon("offset")
    expected = _pixels(first)
    first.swap(QIcon())
    assert _pixels(icons.tool_icon("offset")) == expected


def test_missing_artwork_keeps_the_legacy_toolbar_icon(monkeypatch):
    toolbar_icons._render.cache_clear()
    monkeypatch.setattr(toolbar_icons, "_templates", lambda: {})
    assert not icons.tool_icon("rectangle").isNull()
    toolbar_icons._render.cache_clear()


def test_new_tool_keys_keep_their_drawing_fallback(monkeypatch):
    monkeypatch.setitem(icons._DRAW, "future_tool", icons._circle)
    assert not icons.tool_icon("future_tool").isNull()


def test_template_keys_match_tools():
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "resources/icons/toolbar.json").read_text(encoding="utf-8"))
    assert set(data["icons"]) == set(icons._DRAW)


def test_artwork_loads_from_the_frozen_resource_root(monkeypatch, tmp_path):
    import sys
    import shutil

    source = Path(__file__).resolve().parents[1] / "resources/icons/toolbar.json"
    target = tmp_path / "resources/icons/toolbar.json"
    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    toolbar_icons._templates.cache_clear()
    toolbar_icons._render.cache_clear()
    try:
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert set(toolbar_icons._templates()) == set(icons._DRAW)
        assert not icons.tool_icon("pushpull").isNull()
    finally:
        toolbar_icons._templates.cache_clear()
        toolbar_icons._render.cache_clear()
