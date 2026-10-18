# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Browser's optional columns (Material, Copies, IFC class) turned on
from the header's right-click: on a sidebar-wide panel Name, Type and Layer
already fill the width, so they landed past the right edge and seemed not
to appear at all. Turning one on makes room for it (Name first) and scrolls
to it; turning it off gives the room back."""
from __future__ import annotations

from views.outliner import (COL_COPIES, COL_IFC, COL_LAYER, COL_MATERIAL,
                            COL_NAME, COL_TYPE)


def _panel():
    from PySide6.QtWidgets import QApplication
    from views.main_window import MainWindow
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    QApplication.processEvents()
    panel = win.project_browser.outliner
    panel.refresh()
    QApplication.processEvents()
    return win, panel


def _close(win, panel):
    for col in (COL_MATERIAL, COL_COPIES, COL_IFC):     # leave as found
        panel.set_column_shown(col, False)
    win._saved_version = win.viewport.scene.version
    win.close()


def _in_view(panel, col) -> bool:
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    head = panel.tree.header()
    left = head.sectionViewportPosition(col)
    room = panel.tree.viewport().width()
    return (not head.isSectionHidden(col) and left >= 0
            and left + min(head.sectionSize(col), 40) <= room)


def test_a_column_turned_on_is_in_view():
    win, panel = _panel()
    try:
        head = panel.tree.header()
        room = panel.tree.viewport().width()
        assert room < 446       # narrower than Name, Type and Layer
        panel.set_column_shown(COL_MATERIAL, True)
        assert _in_view(panel, COL_MATERIAL)
        assert head.sectionSize(COL_NAME) < 200  # Name gave up room
        panel.set_column_shown(COL_COPIES, True)
        assert _in_view(panel, COL_COPIES)
        panel.set_column_shown(COL_IFC, True)
        assert _in_view(panel, COL_IFC)
        for col in (COL_NAME, COL_TYPE, COL_LAYER, COL_MATERIAL):
            assert head.sectionSize(col) >= 40               # still legible
    finally:
        _close(win, panel)


def test_turning_them_off_gives_the_name_its_room_back():
    from PySide6.QtWidgets import QApplication
    win, panel = _panel()
    try:
        head = panel.tree.header()
        QApplication.processEvents()
        before = {c: head.sectionSize(c) for c in (COL_NAME, COL_TYPE)}
        for col in (COL_MATERIAL, COL_COPIES, COL_IFC):
            panel.set_column_shown(col, True)
        assert head.sectionSize(COL_NAME) < before[COL_NAME] or             before[COL_NAME] <= panel._name_floor()
        for col in (COL_MATERIAL, COL_COPIES, COL_IFC):
            panel.set_column_shown(col, False)
        QApplication.processEvents()
        assert {c: head.sectionSize(c)
                for c in (COL_NAME, COL_TYPE)} == before     # as it was
        assert panel.tree.horizontalScrollBar().value() == 0  # names in view
    finally:
        _close(win, panel)


# --- the order: the eye and the padlock first ---------------------------------

def _drag(panel, col, width):
    """A column edge dragged on the header: the mouse is down on it."""
    panel._header_pressed = True
    try:
        panel.tree.header().resizeSection(col, width)
    finally:
        panel._header_pressed = False


def _visual(panel):
    head = panel.tree.header()
    return sorted(range(head.count()), key=head.visualIndex)


def test_the_eye_and_the_padlock_come_before_the_name():
    from views.outliner import COL_EYE, COL_LOCK
    win, panel = _panel()
    try:
        assert _visual(panel)[:5] == [COL_EYE, COL_LOCK, COL_NAME, COL_TYPE,
                                      COL_LAYER]
        assert panel.tree.treePosition() == COL_NAME   # branches on names
    finally:
        _close(win, panel)


def test_a_dragged_order_is_remembered_and_restore_panels_resets_it():
    from PySide6.QtWidgets import QApplication
    from views.outliner import COL_EYE, COL_LOCK, OutlinerPanel
    win, panel = _panel()
    try:
        head = panel.tree.header()
        head.moveSection(head.visualIndex(COL_LAYER), 0)   # Layer first
        panel.set_column_shown(COL_IFC, True)
        _drag(panel, COL_TYPE, 150)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
    win2, panel2 = _panel()
    try:
        assert _visual(panel2)[0] == COL_LAYER              # remembered
        assert not panel2._auto_fit                          # sized by hand
        win2.restore_default_trays()
        for _ in range(5):
            QApplication.processEvents()
        head = panel2.tree.header()
        assert _visual(panel2) == list(OutlinerPanel.COLUMN_ORDER)
        assert _visual(panel2)[:2] == [COL_EYE, COL_LOCK]
        assert head.isSectionHidden(COL_IFC)
        assert panel2._auto_fit                              # fits again
    finally:
        _close(win2, panel2)
    win3, panel3 = _panel()
    try:
        head = panel3.tree.header()
        assert _visual(panel3) == list(OutlinerPanel.COLUMN_ORDER)
        # as a fresh profile has them: no hand-made widths kept
        assert panel3._auto_fit
    finally:
        _close(win3, panel3)


# --- Name, Type and Layer share the panel ------------------------------------

def _sized(panel, width):
    """The side tray dragged to ``width``, the Browser in front."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    win = panel._window
    win.project_browser.raise_()
    win.resizeDocks([win.project_browser], [width], Qt.Horizontal)
    for _ in range(10):
        QApplication.processEvents()
    head = panel.tree.header()
    return {c: head.sectionSize(c) for c in (COL_NAME, COL_TYPE, COL_LAYER)}


def test_the_columns_fit_a_sidebar_wide_panel_without_scrolling():
    win, panel = _panel()
    try:
        panel._auto_fit = True
        w = _sized(panel, 440)
        assert panel.tree.viewport().width() > 380           # it took
        assert panel.tree.horizontalScrollBar().maximum() == 0
        assert 80 <= w[COL_TYPE] < 110, w    # Type gave up room first
        # Name keeps the largest share — not a pixel count: the widths
        # follow the platform's fonts and margins (CI on Linux: 179 px).
        assert w[COL_NAME] > w[COL_TYPE] and w[COL_NAME] > w[COL_LAYER], w
        assert w[COL_NAME] >= panel._name_floor()
        wide = _sized(panel, 800)
        assert wide[COL_TYPE] == 110 and wide[COL_NAME] == 200
    finally:
        _close(win, panel)


def test_a_column_sized_by_hand_is_left_alone():
    win, panel = _panel()
    try:
        panel._auto_fit = True
        _sized(panel, 800)
        _drag(panel, COL_TYPE, 140)                         # the user's drag
        assert not panel._auto_fit
        assert _sized(panel, 440)[COL_TYPE] == 140
    finally:
        _close(win, panel)


def test_turning_on_material_copies_and_ifc_still_fits_the_panel():
    win, panel = _panel()
    try:
        panel._auto_fit = True
        _sized(panel, 440)
        head = panel.tree.header()
        for col in (COL_MATERIAL, COL_COPIES, COL_IFC):
            panel.set_column_shown(col, True)
            from PySide6.QtWidgets import QApplication
            for _ in range(5):
                QApplication.processEvents()
            assert panel.tree.horizontalScrollBar().maximum() == 0, col
            assert panel._auto_fit                   # Qt's own resizes
        for col in (COL_NAME, COL_TYPE, COL_LAYER, COL_MATERIAL, COL_COPIES,
                    COL_IFC):
            assert head.sectionSize(col) >= 35
        wide = _sized(panel, 900)
        assert wide[COL_NAME] == 200                 # room again: back up
        assert panel.tree.horizontalScrollBar().maximum() == 0
    finally:
        _close(win, panel)


def test_a_resize_qt_makes_on_its_own_does_not_end_the_fitting():
    win, panel = _panel()
    try:
        panel._auto_fit = True
        panel.tree.header().resizeSection(COL_TYPE, 140)   # no mouse down
        assert panel._auto_fit
    finally:
        _close(win, panel)


# --- the columns button at the header's right end ----------------------------

def test_the_columns_button_says_how_many_are_off_and_opens_the_menu():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from core.i18n import tr
    win, panel = _panel()
    try:
        panel._auto_fit = True
        _sized(panel, 440)
        b = panel._columns_button
        head = panel.tree.header()
        assert b.text() == "+3"                     # Material, Copies, IFC
        assert b.isVisible()
        # in a strip of its own right of the header: no title runs under it
        assert b.geometry().left() == head.geometry().right() + 1
        assert b.geometry().top() == head.geometry().top()
        panel.set_column_shown(COL_MATERIAL, True)
        assert b.text() == "+2"
        found = []

        def read():
            menu = QApplication.activePopupWidget()
            if menu is None:
                QTimer.singleShot(10, read)
                return
            found.extend(a.text() for a in menu.actions())
            menu.close()
        QTimer.singleShot(0, read)
        b.click()
        assert tr("Copies") in found and tr("IFC class") in found
        for col in (COL_COPIES, COL_IFC):
            panel.set_column_shown(col, True)
        assert b.text() == "⋮"                      # all on
    finally:
        _close(win, panel)


def test_names_stay_readable_with_every_column_on():
    win, panel = _panel()
    try:
        panel._auto_fit = True
        _sized(panel, 440)
        for col in (COL_MATERIAL, COL_COPIES, COL_IFC):
            panel.set_column_shown(col, True)
        assert panel.tree.header().sectionSize(COL_NAME) >= \
            panel._name_floor() >= 110
    finally:
        _close(win, panel)


def test_a_short_step_per_level_of_nesting():
    """Nested rows step in 12 px a level, not Qt's 20: a deep tree keeps
    its names in a sidebar-wide panel."""
    win, panel = _panel()
    try:
        assert panel.tree.indentation() == panel.INDENT == 12
    finally:
        _close(win, panel)


def test_the_button_stays_at_the_right_whatever_the_columns_do():
    """Dragged wider by hand (no more fitting) and scrolled to the end, the
    columns move under the header; the button does not."""
    from PySide6.QtWidgets import QApplication
    win, panel = _panel()
    try:
        _sized(panel, 440)
        b = panel._columns_button
        tree = panel.tree
        where = b.geometry()
        assert where.right() <= tree.width() - 1
        _drag(panel, COL_NAME, 400)                     # the user's drag
        for _ in range(5):
            QApplication.processEvents()
        assert tree.horizontalScrollBar().maximum() > 0  # now it scrolls
        assert b.geometry() == where
        tree.horizontalScrollBar().setValue(
            tree.horizontalScrollBar().maximum())
        for _ in range(5):
            QApplication.processEvents()
        assert b.geometry() == where
    finally:
        panel.reset_columns()
        _close(win, panel)


def test_the_strip_under_the_button_wears_the_rows_colours():
    """The strip kept for the button, below it, continues each row — its
    alternate tone and the selection — instead of the frame's lighter
    colour."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QVector3D as V
    from PySide6.QtWidgets import QApplication
    from core.group import Group
    from core.mesh import Mesh
    win, panel = _panel()
    try:
        scene = win.viewport.scene
        for name in ("A", "B", "C", "D"):
            m = Mesh()
            m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
            scene.groups.append(Group(m, name=name))
        scene.version += 1
        _sized(panel, 440)
        panel.refresh()
        tree = panel.tree
        tree.setCurrentItem(tree.topLevelItem(0).child(1))
        for _ in range(5):
            QApplication.processEvents()
        filler = tree._filler
        assert filler.isVisible()
        assert filler.geometry().left() == tree.viewport().geometry().right() + 1
        rows = tree.grab(tree.viewport().geometry()).toImage()
        strip = filler.grab().toImage()
        x = tree.viewport().width() - 3
        for row in range(4):
            item = tree.topLevelItem(0).child(row)
            r = tree.visualItemRect(item)
            y = r.center().y()
            assert strip.pixelColor(QPoint(3, y)) == rows.pixelColor(
                QPoint(x, y)), (row, item.text(0))
    finally:
        _close(win, panel)


# --- a wider panel: the columns cut short grow back ---------------------------

def _long_rows(win, panel):
    from PySide6.QtGui import QMatrix4x4, QVector3D as V
    from core.group import Group, copy_group
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    comp = Group(m, name="Un nombre de grupo bastante largo")
    comp.xform = QMatrix4x4()
    scene = win.viewport.scene
    scene.groups[:] = [comp, copy_group(comp, V(2, 0, 0))]
    scene.version += 1
    panel.refresh()


def test_widening_grows_the_columns_cut_short_and_narrowing_shrinks_them():
    win, panel = _panel()
    try:
        panel._auto_fit = True
        _long_rows(win, panel)
        narrow = _sized(panel, 440)
        wide = _sized(panel, 900)
        # Type held «Component (2 copies)» cut short: it grows to show it
        assert wide[COL_TYPE] > narrow[COL_TYPE]
        assert wide[COL_TYPE] >= panel._wanted_width(COL_TYPE) - 1
        assert panel.tree.horizontalScrollBar().maximum() == 0
        again = _sized(panel, 440)
        assert again[COL_TYPE] <= narrow[COL_TYPE] + 1
    finally:
        _close(win, panel)


def test_widths_set_by_hand_grow_too_and_come_back_to_the_users():
    win, panel = _panel()
    try:
        panel._auto_fit = True
        _long_rows(win, panel)
        _sized(panel, 440)
        _drag(panel, COL_TYPE, 60)                   # the user's width
        assert not panel._auto_fit
        wide = _sized(panel, 900)
        assert wide[COL_TYPE] > 60                   # cut short: grown
        again = _sized(panel, 440)
        assert again[COL_TYPE] == 60                 # the user's again
    finally:
        _close(win, panel)
