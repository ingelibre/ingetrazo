# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The professional view title (sheets plan, 2026-09-05, point 2): LayOut's
numbered bubble + title + «ESC. 1:N» over a rule, the vertical bar of the
Brazilian plans, or the old simple line — fields expanded, the frame's
box grown to fit, paint-only (no render redone)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import Cajetin, Composicion, MarcoVista
from tests.test_composer_canvas import _FakeViewport
from views.composer import (ComposerWindow, FrameItem, frame_title_text,
                            paint_frame_mm, view_title_extent,
                            view_title_texts)

_app = QApplication.instance() or QApplication([])
V = QVector3D


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    host.viewport.scene.mesh.add_face(
        [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
    composer = ComposerWindow(host)
    composer.comp.cajetin = Cajetin()
    composer.comp.cajetin.lamina = "A-101"
    composer._set_field_context(composer.comp)
    return composer, host


def test_title_texts_default_to_the_view_name_and_expand_fields():
    composer, _host = _composer()
    f = composer.comp.frames[0]
    f.view_key, f.scale_n, f.show_title = "std:top", 50.0, True
    t = view_title_texts(f)
    assert t["title"] == "Top (plan)" and t["scale"] == "ESC. 1:50"
    assert t["number"] == "" and t["sheet"] == "" and t["subtitle"] == ""
    assert frame_title_text(f) == "Top (plan) — 1:50"     # the DXF layer name
    f.title_text = "PLANTA — {escala}"
    f.title_number = "1"
    f.title_sheet = "{lamina}"
    f.title_scale = False
    t = view_title_texts(f)
    assert t["title"] == "PLANTA — 1:50"       # THIS frame's scale, no uid needed
    assert t["sheet"] == "A-101" and t["number"] == "1"
    assert t["scale"] == ""


def test_the_frame_box_grows_where_the_title_goes():
    f = MarcoVista(w_mm=100.0, h_mm=80.0)
    assert view_title_extent(f) == (0.0, 0.0, 0.0)
    f.show_title = True
    left, top, bottom = view_title_extent(f)
    assert left == 0 and top == 0 and bottom > 5.0
    f.title_number = "1"                           # the bubble is taller
    assert view_title_extent(f)[2] > bottom
    f.title_pos = "above"
    l2, t2, b2 = view_title_extent(f)
    assert t2 > 0 and b2 == 0
    f.title_style = "bar"
    l3, t3, b3 = view_title_extent(f)
    assert l3 > 5.0 and t3 == 0 and b3 == 0
    f.title_subtitle = "Nivel 1"
    assert view_title_extent(f)[0] > l3


def _ink(frame, k=4):
    """Paint the frame with its title on white; return the image and the
    origin offset so callers can probe around the frame."""
    left, top, bottom = view_title_extent(frame)
    W, H = frame.w_mm + left + 4, frame.h_mm + top + bottom + 4
    img = QImage(int(W * k), int(H * k), QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(k, k)
    p.translate(left + 2, top + 2)
    paint_frame_mm(p, frame, None, hlr=[])
    p.end()
    return img, (left + 2) * k, (top + 2) * k, k


def _dark_in(img, x0, y0, x1, y1):
    return sum(1 for x in range(int(x0), int(x1)) for y in range(int(y0), int(y1))
               if img.pixelColor(x, y).lightness() < 140)


def test_each_style_inks_where_it_says():
    f = MarcoVista(style="vectorial", w_mm=100.0, h_mm=60.0, show_title=True,
                   title_number="1", title_sheet="A1")
    # layout below: ink under the frame, none above or left
    img, ox, oy, k = _ink(f)
    below = _dark_in(img, ox, oy + f.h_mm * k + 2, ox + f.w_mm * k,
                     img.height())
    above = _dark_in(img, ox, 0, ox + f.w_mm * k, oy - 2)
    assert below > 50 and above == 0
    # the rule reaches the frame's right edge
    _l, _t, bottom = view_title_extent(f)
    rule_band = _dark_in(img, ox + f.w_mm * k - 8, oy + f.h_mm * k + 2,
                         ox + f.w_mm * k, oy + (f.h_mm + bottom) * k)
    assert rule_band > 0
    f.title_pos = "above"
    img, ox, oy, k = _ink(f)
    assert _dark_in(img, ox, 0, ox + f.w_mm * k, oy - 2) > 50
    assert _dark_in(img, ox, oy + f.h_mm * k + 2, ox + f.w_mm * k,
                    img.height()) == 0
    f.title_style = "bar"
    img, ox, oy, k = _ink(f)
    assert _dark_in(img, 0, oy, ox - 2, oy + f.h_mm * k) > 50   # left strip
    assert _dark_in(img, ox, oy + f.h_mm * k + 2, ox + f.w_mm * k,
                    img.height()) == 0
    f.title_style = "simple"
    f.title_pos = "below"
    img, ox, oy, k = _ink(f)
    assert _dark_in(img, ox, oy + f.h_mm * k + 2, ox + f.w_mm * k,
                    img.height()) > 50
    assert _dark_in(img, 0, oy, ox - 2, oy + f.h_mm * k) == 0


def test_title_fields_roundtrip_and_old_sheets_keep_their_look():
    c = Composicion()
    c.frames.append(MarcoVista(show_title=True, title_style="bar",
                               title_text="PLANTA", title_subtitle="Sub",
                               title_number="2", title_sheet="{lamina}",
                               title_scale=False, title_align="right",
                               title_pos="above", title_mm=5.0))
    back = Composicion.from_dict(c.to_dict()).frames[-1]
    assert (back.title_style, back.title_text, back.title_subtitle,
            back.title_number, back.title_sheet) == (
        "bar", "PLANTA", "Sub", "2", "{lamina}")
    assert back.title_scale is False and back.title_align == "right"
    assert back.title_pos == "above" and back.title_mm == 5.0
    legacy = Composicion.from_dict({"frames": [{"show_title": True}]}).frames[0]
    assert legacy.title_style == "layout" and legacy.title_scale is True
    assert view_title_texts(legacy)["title"] == "View"


def test_panel_edits_the_title_without_redoing_the_render():
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.view_key, frame.style = "std:front", "vectorial"
    composer.render_frame(frame)
    before = composer.hlr_cache[id(frame)]
    item = next(it for it in composer.canvas.items()
                if getattr(it, "model", None) is frame)
    assert isinstance(item, FrameItem)
    item.setSelected(True)
    composer.on_selection_changed()
    assert not composer.title_style_combo.isEnabled()   # no title yet
    composer.title_check.setChecked(True)
    assert frame.show_title is True
    assert composer.title_style_combo.isEnabled()
    h0 = item.boundingRect().height()
    composer.title_number_edit.setText("1")
    composer.title_text_edit.setText("PLANTA")
    assert frame.title_number == "1" and frame.title_text == "PLANTA"
    assert item.boundingRect().height() > h0          # the bubble grew it
    composer.title_style_combo.setCurrentIndex(
        composer.title_style_combo.findData("bar"))
    assert frame.title_style == "bar"
    assert not composer.title_align_combo.isEnabled()  # meaningless for the bar
    assert item.boundingRect().left() < -5.0
    assert composer.hlr_cache.get(id(frame)) is before  # paint-only


def test_optional_sections_hide_their_rows_when_they_do_not_apply():
    """Marco, 2026-09-05: the panel at 480 px was cut and too long — the
    title rows only show with the title on, the pen rows only for the
    vector style, and the checkboxes span the whole width."""
    composer, _host = _composer()
    frame = composer.comp.frames[0]
    frame.style = "sombreado"
    item = next(it for it in composer.canvas.items()
                if getattr(it, "model", None) is frame)
    item.setSelected(True)
    composer.on_selection_changed()
    form = composer._frame_form
    assert composer._title_rows and composer._pen_rows
    assert not any(form.isRowVisible(r) for r in composer._title_rows)
    assert not any(form.isRowVisible(r) for r in composer._pen_rows)
    composer.title_check.setChecked(True)
    assert all(form.isRowVisible(r) for r in composer._title_rows)
    composer.style_combo.setCurrentIndex(composer.style_combo.findData("vectorial"))
    assert all(form.isRowVisible(r) for r in composer._pen_rows)
    composer.title_check.setChecked(False)
    assert not any(form.isRowVisible(r) for r in composer._title_rows)
    # a checkbox row spans both columns: no label widget beside it
    from PySide6.QtWidgets import QFormLayout
    row, role = form.getWidgetPosition(composer.annot_check)
    assert role == QFormLayout.SpanningRole
    assert form.rowWrapPolicy() == QFormLayout.WrapLongRows
