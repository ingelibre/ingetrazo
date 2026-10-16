"""A section growing above what you are looking at does not move it
(Marco, 23-09: the materials list jumped whenever Entity Info filled up on
selecting something)."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from views.tray import _scrolled

_app = QApplication.instance() or QApplication([])


def _settle():
    for _ in range(5):
        _app.processEvents()


def test_growing_a_section_above_keeps_the_view_still():
    top = QLabel("info")
    top.setMinimumHeight(40)
    tall = QWidget()
    tall.setMinimumHeight(2000)
    scroll = _scrolled([("Info", top), ("Library", tall)])
    scroll.resize(300, 400)
    scroll.show()
    _settle()
    bar = scroll.verticalScrollBar()
    bar.setValue(600)                  # looking at the library, far below
    _settle()
    top.setMinimumHeight(240)          # Entity Info fills up: +200 px
    _settle()
    assert bar.value() == 800          # the library did not move on screen
    scroll.close()


def test_at_the_top_nothing_is_compensated():
    top = QLabel("info")
    top.setMinimumHeight(40)
    tall = QWidget()
    tall.setMinimumHeight(2000)
    scroll = _scrolled([("Info", top), ("Library", tall)])
    scroll.resize(300, 400)
    scroll.show()
    _settle()
    bar = scroll.verticalScrollBar()
    bar.setValue(0)
    top.setMinimumHeight(240)
    _settle()
    assert bar.value() == 0
    scroll.close()


def test_entity_info_collapses_unused_rows():
    from PySide6.QtGui import QVector3D as V
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    panel = win.tray.entity_info if hasattr(win, "tray") else None
    if panel is None:
        from views.tray import EntityInfoPanel
        panel = next(w for w in win.findChildren(EntityInfoPanel))
    sc = win.viewport.scene
    face = sc.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    edge = next(iter(sc.mesh.edges))
    heights = []
    for sel in ([], [edge], [face]):
        sc.select(sel) if sel else sc.clear_selection()
        panel.refresh()
        _settle()
        heights.append(panel.sizeHint().height())
    # Only relevant properties take space; no reserved name/material rows.
    assert heights[0] < heights[1] < heights[2], heights
    assert panel._name_edit.isHidden()
    assert [caption.text() for caption, value in panel._facts
            if not value.isHidden()] == ["Area:", "Vertices:"]
    win._saved_version = sc.version
    win.close()
