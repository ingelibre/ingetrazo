# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""RAL Classic in the Materials tray.

The palette is not there to have more colours: it is there so a painted
face carries a reference a painter can buy. Picking RAL 7035 must leave the
face wearing the material "RAL 7035 Gris claro", not an RGB triple."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

from core.i18n import tr  # noqa: E402

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _panel(win):
    from views.tray import MaterialsPanel
    return win.findChild(MaterialsPanel)


def test_picking_a_ral_colour_paints_a_material_with_its_name():
    from core.i18n import current_language, set_language
    from tools.paint import PaintTool
    from views.main_window import MainWindow

    was = current_language()
    set_language("es")
    win = MainWindow()
    try:
        panel = _panel(win)
        assert panel is not None
        # Everything lives in the one Colours section — no RAL headings of
        # their own to click through.
        colors = [b for b in panel.findChildren(QToolButton)
                  if b.isCheckable() and b.text().strip().startswith(
                      tr("Colors"))]
        assert len(colors) == 1, [b.text() for b in colors]
        assert not [b for b in panel.findChildren(QToolButton)
                    if b.isCheckable() and "RAL" in b.text()]
        colors[0].setChecked(True)              # the swatches build on open
        swatch = next(b for b in panel.findChildren(QToolButton)
                      if not b.isCheckable()
                      and b.toolTip().startswith("RAL 7035"))
        assert swatch.toolTip() == "RAL 7035 · Gris claro"
        swatch.click()
        mat = PaintTool.current_material
        assert mat is not None and mat.name == "RAL 7035 Gris claro"
        assert PaintTool.current_texture is None
        # sRGB of RAL 7035, as the standard gives it.
        assert [round(v * 255) for v in PaintTool.current_color] == \
            [203, 208, 204]
    finally:
        set_language(was)
        win.close()


def test_the_families_build_only_when_opened():
    # Four hundred textures and two hundred colours must not be read at
    # start-up to fill panels that are closed. This is what keeps the window
    # opening in a fifth of a second instead of a whole one.
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        panel = _panel(win)
        swatches = [b for b in panel.findChildren(QToolButton)
                    if not b.isCheckable() and b.toolTip().startswith("RAL")]
        assert swatches == [], "the RAL swatches were built before opening"
    finally:
        win.close()


def test_the_ral_name_follows_the_language():
    from core.i18n import current_language, set_language
    from views.tray import _ral_name

    entry = {"name": "Light grey", "name_es": "Gris claro"}
    was = current_language()
    try:
        set_language("es")
        assert _ral_name(entry) == "Gris claro"
        set_language("en")
        assert _ral_name(entry) == "Light grey"
        # A family with no translation falls back rather than showing blank.
        assert _ral_name({"name": "Grey"}) == "Grey"
    finally:
        set_language(was)


def test_every_colour_in_the_tray_has_a_name():
    # The eight unnamed starter swatches are gone: beside 213 colours that
    # each carry a reference a painter can buy, a nameless square is only
    # confusing (Marco).
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        panel = _panel(win)
        header = next(b for b in panel.findChildren(QToolButton)
                      if b.isCheckable()
                      and b.text().strip().startswith(tr("Colors")))
        header.setChecked(True)
        swatches = [b for b in panel.findChildren(QToolButton)
                    if not b.isCheckable() and b.toolTip()
                    and not b.toolTip().startswith("RAL")]
        assert swatches == [], [b.toolTip() for b in swatches[:5]]
        assert len([b for b in panel.findChildren(QToolButton)
                    if not b.isCheckable()
                    and b.toolTip().startswith("RAL")]) == 213
    finally:
        win.close()
