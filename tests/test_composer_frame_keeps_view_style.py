# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rendering a sheet frame draws it in the frame's own style and gives the
model view back the style it had: the render used to end by clearing the
view's plan style and style override to None, so a style the window had
set was lost after any sheet render (an extension worked around it by
wrapping ``render_frame``)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def comp():
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    c = ComposerWindow(win)
    yield c, win
    c.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _seen(vp, monkeypatch):
    seen = []

    def fake_render(w, h, **kw):
        seen.append((vp.plano_style, vp.style_override))
        img = QImage(4, 4, QImage.Format_RGB32)
        img.fill(0xFFFFFFFF)
        return img
    monkeypatch.setattr(vp, "render_image", fake_render)
    return seen


@pytest.mark.parametrize("style", ["tecnico", "sombreado", "style:Hidden line"])
def test_a_frame_render_gives_the_view_its_style_back(comp, monkeypatch, style):
    from core.composition import MarcoVista
    from core.style import style_by_name
    c, win = comp
    vp = win.viewport
    seen = _seen(vp, monkeypatch)
    window_style = style_by_name("Hidden line")
    vp.plano_style = "lineas"
    vp.style_override = window_style
    c.render_frame(MarcoVista(style=style))
    assert len(seen) == 1
    plano, override = seen[0]
    # The frame drew in its own style, not the window's ...
    if style == "tecnico":
        assert plano == "tecnico" and override is None
    elif style == "sombreado":
        assert plano is None and override is None
    else:
        assert plano is None and override is not None
        assert override is not window_style
    # ... and the window has its own back.
    assert vp.plano_style == "lineas"
    assert vp.style_override is window_style
    assert vp._export_edge_px == 1 and vp._export_profile_px == 1


def test_a_view_with_no_style_stays_without(comp, monkeypatch):
    from core.composition import MarcoVista
    c, win = comp
    vp = win.viewport
    _seen(vp, monkeypatch)
    vp.plano_style = None
    vp.style_override = None
    c.render_frame(MarcoVista(style="style:Hidden line", paper_bg=True))
    assert vp.plano_style is None and vp.style_override is None
