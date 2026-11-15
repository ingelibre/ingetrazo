# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The decoded textures are kept only while several views are on screen.

They are kept so that the views joining a document upload from one
decoding (tests/test_views_share_bakes.py); with one view each texture is
uploaded once, and keeping the images only held their memory — ~65 MB on
the plaza, for as long as it stayed open (release check, 14-11)."""
from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])

from views import viewport as VPM                        # noqa: E402


def _png(tmp_path, name):
    path = tmp_path / name
    img = QImage(8, 8, QImage.Format_RGBA8888)
    img.fill(QColor(200, 30, 30))
    img.save(str(path))
    return str(path)


def test_one_view_keeps_no_decoded_image(tmp_path, monkeypatch):
    monkeypatch.setattr(VPM, "_DECODED_TEXTURES", {})
    monkeypatch.setattr(VPM, "_several_views_shown", lambda: False)
    a = _png(tmp_path, "a.png")
    img, cutout = VPM._decoded_texture(a)
    assert not img.isNull()
    assert VPM._DECODED_TEXTURES == {}


def test_several_views_share_the_decoding_and_one_again_lets_it_go(
        tmp_path, monkeypatch):
    monkeypatch.setattr(VPM, "_DECODED_TEXTURES", {})
    shown = [True]
    monkeypatch.setattr(VPM, "_several_views_shown", lambda: shown[0])
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    first = VPM._decoded_texture(a)
    assert VPM._decoded_texture(a) is first         # the second view's
    assert list(VPM._DECODED_TEXTURES) == [a]
    shown[0] = False                                # back to one view
    VPM._decoded_texture(b)
    assert VPM._DECODED_TEXTURES == {}


def test_a_viewport_is_counted_while_it_is_shown():
    from views.viewport import Viewport
    vp = Viewport(None)
    try:
        assert vp in VPM._LIVE_VIEWS
    finally:
        vp.close()
