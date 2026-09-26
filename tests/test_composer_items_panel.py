# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The composer's Items list (issue #93, @pacaeiro): items can be renamed
and grouped by type. It keeps its own tab, the properties the next one —
Marco tried them sharing one tab, the list folded and floating, and kept
separate tabs (26-09). No sheet navigator: the sheet
strip at the bottom already switches sheets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    comp.show()
    _app.processEvents()
    return comp, win


def _close(comp, win):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_three_tabs_and_a_pick_in_the_list_stays_in_the_list(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        assert comp._tabs.count() == 3            # Layout, Items, Properties
        comp._tabs.setCurrentIndex(1)
        comp._refresh_items_list()
        frame = comp.comp.frames[0]
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        comp.items_list.setCurrentItem(row)       # picked in the list…
        _app.processEvents()
        assert comp._selected_item().model is frame
        assert comp._tabs.currentIndex() == 1     # …stays there to rename
    finally:
        _close(comp, win)


def test_an_item_renamed_in_the_list_keeps_its_name_and_undoes(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        frame = comp.comp.frames[0]
        comp._refresh_items_list()
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        row.setText(2, "Planta general")                 # typed in the list
        _app.processEvents()
        assert frame.list_name == "Planta general"
        assert any(r.text(2) == "Planta general" for r in comp._item_rows())
        comp.history.undo()
        assert frame.list_name == ""
        # An empty name, or the automatic one, is no name.
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        row.setText(2, "")
        _app.processEvents()
        assert frame.list_name == ""
    finally:
        _close(comp, win)


def test_grouping_puts_the_items_in_folders(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        comp.items_group_check.setChecked(True)
        folders = [comp.items_list.topLevelItem(i)
                   for i in range(comp.items_list.topLevelItemCount())]
        assert folders and all(f.data(0, Qt.UserRole) is None
                               for f in folders)
        names = [f.text(2) for f in folders]
        assert any(n.startswith("Views") or n.startswith("Vistas")
                   for n in names)
        n_rows = len(list(comp._item_rows()))
        assert n_rows == len(comp.comp.all_items())
        comp.items_group_check.setChecked(False)
        assert all(comp.items_list.topLevelItem(i).data(0, Qt.UserRole)
                   is not None
                   for i in range(comp.items_list.topLevelItemCount()))
    finally:
        _close(comp, win)


def test_the_name_survives_the_igz(tmp_path):
    from core.composition import Composicion, MarcoVista
    c = Composicion()
    c.frames.append(MarcoVista(list_name="Alzado norte"))
    back = Composicion.from_dict(c.to_dict())
    assert back.frames[0].list_name == "Alzado norte"


def test_the_eye_hides_and_the_padlock_locks_as_in_qgis(monkeypatch):
    """Marco, 26-09: «en elementos debería poder ocultar, mostrar,
    bloquear, desbloquear así como lo tiene QGIS»."""
    from PySide6.QtGui import QImage, QPainter
    from views.composer import FrameItem
    comp, win = _composer(monkeypatch)
    try:
        frame = comp.comp.frames[0]
        comp._refresh_items_list()

        def row():
            return next(r for r in comp._item_rows()
                        if r.data(0, Qt.UserRole) == id(frame))

        assert row().checkState(0) == Qt.Checked         # visible
        assert row().checkState(1) == Qt.Unchecked       # unlocked
        row().setCheckState(0, Qt.Unchecked)             # the eye: hide
        _app.processEvents()
        assert frame.hidden
        item = next(it for it in comp.canvas.items()
                    if isinstance(it, FrameItem))
        assert not item.isVisible()
        comp.history.undo()                              # undoable
        _app.processEvents()
        assert not frame.hidden
        row().setCheckState(1, Qt.Checked)               # the padlock
        _app.processEvents()
        assert frame.locked
        row().setCheckState(1, Qt.Unchecked)
        _app.processEvents()
        assert not frame.locked
    finally:
        _close(comp, win)


def test_a_hidden_item_is_not_printed(monkeypatch):
    from core.composition import TextoItem
    comp, win = _composer(monkeypatch)
    try:
        t = TextoItem(x_mm=30, y_mm=30, text="SECRETO", size_pt=40)
        comp.comp.texts.append(t)
        painted = []
        import views.composer as vc
        monkeypatch.setattr(vc, "paint_text_mm",
                            lambda p, m, *a, **k: painted.append(m))
        from PySide6.QtGui import QImage, QPainter
        img = QImage(400, 300, QImage.Format_ARGB32)
        p = QPainter(img)
        comp._paint_sheet(p, comp.comp)
        p.end()
        assert t in painted
        painted.clear()
        t.hidden = True
        p = QPainter(img)
        comp._paint_sheet(p, comp.comp)
        p.end()
        assert t not in painted
    finally:
        _close(comp, win)


def test_double_click_opens_the_properties(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        comp._tabs.setCurrentIndex(1)
        comp._refresh_items_list()
        frame = comp.comp.frames[0]
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        comp.items_list.setCurrentItem(row)
        assert comp._tabs.currentIndex() == 1            # a click stays
        comp.items_list.itemDoubleClicked.emit(row, 2)
        assert comp._tabs.currentIndex() == 2            # double: properties
        assert comp._selected_item().model is frame
    finally:
        _close(comp, win)
