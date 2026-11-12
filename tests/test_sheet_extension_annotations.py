# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An extension draws on the sheets too (``add_sheet_annotations``): what an
overlay shows only on screen — a road's stationing, a canal's marks — is
printed in the model-view frames, projected by the frame's own camera."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D


def _setup():
    from views.composer import ComposerWindow
    from views.extension_api import ExtensionApp
    from views.main_window import MainWindow
    win = MainWindow()
    comp = ComposerWindow(win)
    frame = comp.comp.frames[0]
    frame.view_key, frame.style = "std:top", "vectorial"
    frame.w_mm, frame.h_mm, frame.scale_n = 200.0, 100.0, 500.0
    return win, comp, frame, ExtensionApp(win, "test_ext")


def _close(win, comp):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _of(annots, kind):
    return [a for a in annots if a[0] == kind]


def test_lines_and_texts_land_where_the_frame_projects_them():
    win, comp, frame, app = _setup()
    try:
        seen = {}

        def provide(scene, sheet):
            seen["paper"] = sheet.paper([(0, 0, 0), (40, 0, 0)])
            seen["scale"] = sheet.scale_n
            return [{"line": [(0, 0, 0), (40, 0, 0)], "width_mm": 0.5,
                     "color": (200, 0, 0)},
                    {"text": "0+040", "at": (40, 0, 0), "size_mm": 2.0}]
        app.add_sheet_annotations(provide)
        annots = comp.compute_annotations(frame)
        assert seen["scale"] == 500.0
        (poly,) = _of(annots, "xpoly")
        assert poly[1] == seen["paper"] and poly[2] == 0.5
        assert poly[3] == (200, 0, 0)
        (text,) = _of(annots, "xtext")
        assert (text[1], text[2]) == seen["paper"][1]
        assert text[4] == "0+040" and text[5] == 2.0 and text[3] == 0.0
        # 40 m at 1:500 is 80 mm of paper, whatever the frame's annotations
        (a, b) = seen["paper"]
        assert math.isclose(math.hypot(b[0] - a[0], b[1] - a[1]), 80.0,
                            rel_tol=1e-6)
        assert frame.annotations is False
    finally:
        _close(win, comp)


def test_a_text_is_never_upside_down_and_can_start_at_its_point():
    win, comp, frame, app = _setup()
    try:
        app.add_sheet_annotations(lambda scene, sheet: [
            {"text": "west", "at": (0, 0, 0), "toward": (-10, 0, 0),
             "anchor": "start"},
            {"text": "east", "at": (0, 20, 0), "toward": (10, 20, 0),
             "anchor": "start"}])
        west, east = _of(comp.compute_annotations(frame), "xtext")
        for t in (west, east):
            assert -90.0 <= t[3] <= 90.0
        # read left to right, the westward one ends at its point
        assert east[10] == 0.0
        assert math.isclose(west[10], -west[11])
    finally:
        _close(win, comp)


def test_ranked_texts_give_way_where_they_would_overlap():
    win, comp, frame, app = _setup()
    try:
        app.add_sheet_annotations(lambda scene, sheet: [
            {"text": "0+010", "at": (0.5, 0, 0), "priority": 3},
            {"text": "0+000", "at": (0, 0, 0), "priority": 0},
            {"text": "1+000", "at": (60, 0, 0), "priority": 3},
            {"text": "free", "at": (0.2, 0, 0)}])      # no rank: always
        words = sorted(t[4] for t in _of(comp.compute_annotations(frame),
                                         "xtext"))
        assert words == ["1+000", "free"]
    finally:
        _close(win, comp)


def test_a_provider_that_raises_is_dropped_and_the_sheet_still_draws():
    win, comp, frame, app = _setup()
    try:
        def broken(scene, sheet):
            raise RuntimeError("boom")
        app.add_sheet_annotations(broken)
        app.add_sheet_annotations(
            lambda scene, sheet: [{"text": "ok", "at": (0, 0, 0)}])
        assert [t[4] for t in _of(comp.compute_annotations(frame),
                                  "xtext")] == ["ok"]
        assert broken not in win._ext_sheet_annots
    finally:
        _close(win, comp)


def test_the_items_are_painted_on_paper():
    from views.composer import _paint_annots_mm
    win, comp, frame, app = _setup()
    try:
        app.add_sheet_annotations(lambda scene, sheet: [
            {"line": [(-40, 0, 0), (40, 0, 0)], "width_mm": 1.0,
             "color": (220, 0, 0)},
            {"text": "0+000", "at": (0, 10, 0), "size_mm": 6.0,
             "color": (0, 0, 220), "background": (0, 220, 0)}])
        annots = comp.compute_annotations(frame)
        img = QImage(400, 200, QImage.Format_ARGB32)
        img.fill(QColor(255, 255, 255))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.scale(2.0, 2.0)                       # 2 px per paper mm
        _paint_annots_mm(p, frame, annots)
        p.end()
        colours = {img.pixelColor(x, y).name()
                   for x in range(0, 400, 2) for y in range(0, 200, 2)}
        assert "#dc0000" in colours                     # the line
        assert "#00dc00" in colours                     # the label's box
        assert any(QColor(c).blue() > 150 and QColor(c).red() < 80
                   and QColor(c).green() < 80 for c in colours)  # its ink
    finally:
        _close(win, comp)
