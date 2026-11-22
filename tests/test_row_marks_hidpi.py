# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The small marks of the Browser and Layers rows — eye, padlock, isolate
target, active-layer pencil, printer, colour and «none» swatches, section
fill — are drawn at the screen's pixel ratio. Painted into a bare 18 × 18
px pixmap they came out blurry on a scaled screen (1.5×, 1.67×, 2×): Qt
stretched the 18 px bitmap up to 30–36 device pixels, beside crisp text
and toolbar icons."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize

import views.icons as icons
import views.layers_panel as layers_panel
import views.layers_toolbar as layers_toolbar
import views.outliner as outliner


def _builders():
    return {
        "eye": lambda: outliner._draw("eye"),
        "eye_off": lambda: outliner._draw("eye_off"),
        "lock": lambda: outliner._draw("lock"),
        "lock_open": lambda: outliner._draw("lock_open"),
        "group": lambda: outliner._draw("group"),
        "fill_on": lambda: outliner.fill_icon((0.5, 0.5, 0.5), True),
        "fill_off": lambda: outliner.fill_icon((0.5, 0.5, 0.5), False),
        "isolate": lambda: layers_toolbar.isolate_icon(True),
        "pencil": lambda: layers_panel._pencil_icon(True),
        "printer": lambda: layers_panel.printer_icon(False),
        "swatch": lambda: layers_panel.swatch_icon((1.0, 0.0, 0.0)),
        "none": lambda: layers_panel.none_swatch(),
        "hatch": lambda: layers_panel.hatch_icon(None),
    }


@pytest.fixture
def ratio(monkeypatch):
    """Pretend the screen is scaled: what the marks see as its ratio."""
    def set_ratio(value):
        monkeypatch.setattr(icons, "screen_dpr", lambda: value)
        monkeypatch.setattr(layers_toolbar, "_ISOLATE_ICONS", {})
    return set_ratio


@pytest.mark.parametrize("name", sorted(_builders()))
@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_row_marks_are_drawn_at_the_screen_ratio(ratio, name, dpr):
    ratio(dpr)
    icon = _builders()[name]()
    side = round(18 * dpr)
    # Held at the screen's ratio (mark_pixmap), or sharper — the Browser's
    # drawn marks (eye, padlock, group) are kept at 1x and 3x, so Qt only
    # ever scales them DOWN: never a bitmap smaller than the screen needs.
    sizes = icon.availableSizes()
    assert QSize(18, 18) in sizes or QSize(side, side) in sizes, \
        f"{name} at {dpr}x: {sizes}"
    assert max(s.width() for s in sizes) >= side, \
        f"{name} at {dpr}x: {sizes}"
    # Asked for at the row's size, the mark keeps its logical 18 px.
    pm = icon.pixmap(QSize(18, 18), dpr)
    assert pm.deviceIndependentSize().toSize() == QSize(18, 18)
