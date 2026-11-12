# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Of several views, the exports of the view take the one worked in.

A 0.6.2 review on Windows: with four views and Top the active one, File ▸
Export ▸ Image wrote the Perspective view — the window's own — as the
view-line exports (DXF, SVG) would. Styles, Shift+P and the standard
views already went to the view clicked; now the picture, the lines and
the SVG do too."""
from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 800)
    w.show()
    w.set_view_layout("four")
    QApplication.processEvents()
    yield w
    for doc in list(w._documents):
        doc.saved_content = doc.viewport.scene.content_version
    w._saved_version = w.viewport.scene.version
    w.close()


def _top(win):
    cell = next(c for c in win._doc.view_grid.cells if c.view == "top")
    vp = cell.viewport
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier,
                     QPoint(vp.width() - 6, vp.height() - 6))
    QApplication.processEvents()
    assert vp is not win.viewport           # not the window's own view
    assert win._active_view() is vp
    return vp


def _spy(win, monkeypatch, name, result):
    called = []
    for cell in win._doc.view_grid.cells:
        def fake(*a, _vp=cell.viewport, **k):
            called.append(_vp)
            return result() if callable(result) else result
        monkeypatch.setattr(cell.viewport, name, fake)
    return called


def test_export_image_renders_the_active_view(win, monkeypatch, tmp_path):
    import views.export_image_dialog as eid
    from views.filedialogs import file_dialogs
    top = _top(win)

    class _Options:
        def __init__(self, *a, **k):
            from PySide6.QtWidgets import QSpinBox
            self.width_box = QSpinBox()
            self.width_box.setRange(1, 10000)
            self.width_box.setValue(64)

        def exec(self):
            return 1

        def transparent(self):
            return False

        def deleteLater(self):
            pass

    out = tmp_path / "view.png"
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(eid, "ExportImageDialog", _Options)

    def picture():
        img = QImage(64, 40, QImage.Format_RGB32)
        img.fill(0)
        return img
    called = _spy(win, monkeypatch, "render_image", picture)
    win._on_export_image()
    assert called == [top]
    assert out.exists()


def test_the_view_lines_and_the_svg_take_the_active_view(win, monkeypatch):
    top = _top(win)
    called = _spy(win, monkeypatch, "hlr_geometry", None)
    win._view_line_groups()
    assert called and set(called) == {top}
    # The SVG builder draws its picture and faces from the same view.
    called = _spy(win, monkeypatch, "render_image",
                  lambda: QImage(8, 8, QImage.Format_RGB32))
    builder = win.view_svg_builder()
    builder._image_fn(64)
    assert called == [top]
