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


def test_entity_info_adapts_its_height_to_the_selection():
    from PySide6.QtGui import QVector3D as V
    from views.main_window import MainWindow
    win = MainWindow()
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
        heights.append(panel.sizeHint().height())
    assert heights[0] < heights[1] < heights[2], heights
    win._saved_version = sc.version
    win.close()


def test_entity_info_packs_visible_properties_without_gaps():
    import math

    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QVector3D as V
    from core.group import Group
    from core.guide import GuideCircle
    from core.mesh import Mesh
    from core.section import SectionPlane
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    panel = win.tray.entity_info
    sc = win.viewport.scene
    face = sc.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    circle = GuideCircle(V(0, 0, 0), V(0, 0, 1), 1.0)
    group = Group(Mesh(), name="Group")
    sc.groups.append(group)
    section = SectionPlane(V(0, 0, 0), V(0, 0, 1), name="Cut", symbol="A")
    points = [V(math.cos(2 * math.pi * k / 12),
                math.sin(2 * math.pi * k / 12), 2) for k in range(12)]
    second_face = sc.mesh.add_face(points)
    sc.mesh.tag_curve(points, closed=True)
    curve = [e for e in sc.mesh.edges if e.curve is not None]

    def gap(above, below):
        y = above.mapTo(panel, QPoint(0, 0)).y()
        return below.mapTo(panel, QPoint(0, 0)).y() - (y + above.height())

    try:
        for selection, rows in (
                ([], [panel._label]),
                ([face], [panel._label, panel._front_btn, panel._layer_box]),
                ([face, second_face], [panel._label, panel._front_btn,
                                       panel._layer_box]),
                ([circle], [panel._label, panel._radius_box, panel._layer_box]),
                (curve, [panel._label, panel._seg_box, panel._radius_box,
                         panel._layer_box, panel._soft_check]),
                ([group], [panel._label, panel._name_edit, panel._mat_btn,
                           panel._layer_box, panel._hidden_check]),
                ([section], [panel._label, panel._name_edit, panel._layer_box])):
            sc.select(selection) if selection else sc.clear_selection()
            panel.refresh()
            _settle()
            assert all(widget.isVisibleTo(panel) for widget in rows)
            assert panel._label.y() == panel.layout().contentsMargins().top()
            assert panel._label.height() == panel._label.heightForWidth(panel._label.width())
            for above, below in zip(rows, rows[1:]):
                assert 0 <= gap(above, below) <= 12, (selection, gap(above, below))
            last = rows[-1]
            last_bottom = last.mapTo(panel, QPoint(0, 0)).y() + last.height()
            assert 0 <= panel.height() - last_bottom <= (
                panel.layout().contentsMargins().bottom() + 4)
            last_global = last.mapToGlobal(QPoint(0, last.height())).y()
            materials_top = win.tray.materials.parentWidget().mapToGlobal(QPoint()).y()
            assert 0 <= materials_top - last_global <= (
                panel.layout().contentsMargins().bottom() + 6)
    finally:
        win._saved_version = sc.version
        win.close()


def test_entity_info_resize_keeps_scrolled_materials_in_place():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QVector3D as V
    from views.main_window import MainWindow
    from views.tray import EntityInfoPanel

    win = MainWindow()
    panel = EntityInfoPanel(win)
    library = QWidget()
    library.setMinimumHeight(2000)
    scroll = _scrolled([("Info", panel), ("Library", library)])
    scroll.resize(300, 400)
    scroll.show()
    sc = win.viewport.scene
    face = sc.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    try:
        _settle()
        scroll.verticalScrollBar().setValue(600)
        _settle()
        before = library.mapToGlobal(QPoint()).y()
        sc.select([face])
        panel.refresh()
        _settle()
        assert library.mapToGlobal(QPoint()).y() == before
        sc.clear_selection()
        panel.refresh()
        _settle()
        assert library.mapToGlobal(QPoint()).y() == before
    finally:
        scroll.close()
        win._saved_version = sc.version
        win.close()


def test_entity_info_wraps_long_text_without_clipping():
    from PySide6.QtGui import QVector3D as V
    from core.textlabel import TextLabel
    from views.main_window import MainWindow

    win = MainWindow()
    win.show()
    panel = win.tray.entity_info
    panel.setFixedWidth(240)
    _settle()
    normal_height = panel.minimumHeight()
    sc = win.viewport.scene
    label = TextLabel(V(0, 0, 0), V(1, 1, 0), "Long text " * 60)
    try:
        sc.select([label])
        panel.refresh()
        _settle()
        assert panel._label.height() >= panel._label.heightForWidth(panel._label.width())
        assert panel.minimumHeight() > normal_height
        assert panel._layer_box.y() >= panel._label.y() + panel._label.height()
        assert panel._layer_box.y() + panel._layer_box.height() <= panel.height()
        expanded_height = panel.minimumHeight()
        panel.setFixedWidth(320)
        _settle()
        assert panel._label.height() >= panel._label.heightForWidth(panel._label.width())
        assert panel.minimumHeight() < expanded_height
        panel.setFixedWidth(240)
        _settle()
        assert panel._label.height() >= panel._label.heightForWidth(panel._label.width())
        assert panel.minimumHeight() == expanded_height
        sc.clear_selection()
        panel.refresh()
        _settle()
        assert panel.minimumHeight() == normal_height
    finally:
        win._saved_version = sc.version
        win.close()
