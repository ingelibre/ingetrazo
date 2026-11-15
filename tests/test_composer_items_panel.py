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
        # Layout, Views and sheets, Items, Properties
        assert comp._tabs.count() == 4
        items = comp._tabs.indexOf(comp._pages["items"])
        comp._tabs.setCurrentIndex(items)
        comp._refresh_items_list()
        frame = comp.comp.frames[0]
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        comp.items_list.setCurrentItem(row)       # picked in the list…
        _app.processEvents()
        assert comp._selected_item().model is frame
        assert comp._tabs.currentIndex() == items  # …stays there to rename
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
        comp._tabs.setCurrentWidget(comp._pages["items"])
        comp._refresh_items_list()
        frame = comp.comp.frames[0]
        row = next(r for r in comp._item_rows()
                   if r.data(0, Qt.UserRole) == id(frame))
        comp.items_list.setCurrentItem(row)
        assert comp._tabs.currentWidget() is comp._pages["items"]  # stays
        comp.items_list.itemDoubleClicked.emit(row, 2)
        assert comp._tabs.currentWidget() is comp._pages["props"]  # double
        assert comp._selected_item().model is frame
    finally:
        _close(comp, win)


def _live_tree_iterators() -> int:
    import gc
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    gc.collect()
    return sum(type(o) is QTreeWidgetItemIterator for o in gc.get_objects())


def test_walking_the_list_leaves_no_iterator_in_its_model(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        comp._refresh_items_list()
        before = _live_tree_iterators()
        rows = list(comp._item_rows())
        assert rows
        comp._sync_items_list(comp._selected_item())
        for it in comp.canvas.items():
            if hasattr(it, "force_select") and hasattr(it, "model"):
                it.force_select()                   # walks to the row, stops
                break
        assert _live_tree_iterators() == before
    finally:
        _close(comp, win)


def test_rows_come_in_list_order_with_folders_or_not(monkeypatch):
    comp, win = _composer(monkeypatch)
    try:
        for _ in range(3):
            comp._on_add_text()
        _app.processEvents()
        for grouped in (False, True):
            comp.items_group_check.setChecked(grouped)
            comp._refresh_items_list()
            shown = []

            def walk(item):
                if item.data(0, Qt.UserRole) is not None:
                    shown.append(item)
                for i in range(item.childCount()):
                    walk(item.child(i))

            for i in range(comp.items_list.topLevelItemCount()):
                walk(comp.items_list.topLevelItem(i))
            assert shown and list(comp._item_rows()) == shown
    finally:
        comp.items_group_check.setChecked(False)
        _close(comp, win)


_RIGHT_CLICK_THEN_EYES = r"""
import faulthandler, os, sys
faulthandler.enable()
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication
QSettings.setDefaultFormat(QSettings.IniFormat)
for scope in (QSettings.UserScope, QSettings.SystemScope):
    QSettings.setPath(QSettings.IniFormat, scope, sys.argv[1])
app = QApplication([])
from views.composer import ComposerWindow
from views.main_window import MainWindow
ComposerWindow.render_frame = lambda self, f: None
win = MainWindow()
comp = ComposerWindow(win)
comp.show()

def pump():
    loop = QEventLoop()
    QTimer.singleShot(5, loop.quit)
    loop.exec()

for _ in range(5):
    comp._on_add_text()
pump()
tree = comp.items_list
row = next(comp._item_rows())
QTimer.singleShot(5, lambda: QApplication.activePopupWidget().close())
comp._items_context_menu(tree.visualRect(tree.indexFromItem(row, 2)).center())
del row
for n in range(8):                          # the eye, and its deferred rebuild
    rows = list(comp._item_rows())
    row = rows[(n + 1) % len(rows)]
    row.setCheckState(0, Qt.Unchecked if row.checkState(0) == Qt.Checked
                      else Qt.Checked)
    del row, rows
    pump()
print("survived", flush=True)
os._exit(0)
"""


def test_rebuilding_after_a_right_click_on_a_row_does_not_crash(tmp_path):
    """A native crash, so in a process of its own: the row the menu's actions
    hold must not leave the list's model pointing at freed memory (05-11)."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", INGETRAZO_RUST="0",
               PYTHONPATH=str(Path(__file__).resolve().parent.parent))
    for var, sub in (("XDG_CONFIG_HOME", "c"), ("XDG_DATA_HOME", "d"),
                     ("XDG_CACHE_HOME", "k"), ("XDG_STATE_HOME", "s")):
        (tmp_path / sub).mkdir()
        env[var] = str(tmp_path / sub)
    run = subprocess.run(
        [sys.executable, "-c", _RIGHT_CLICK_THEN_EYES, str(tmp_path / "qs")],
        env=env, capture_output=True, text=True, timeout=120)
    # Windows: os._exit after «survived» can still die in shiboken's own
    # teardown (0xC0000005, 3 runs in 10 on the 0.6.2 round, as in 0.6.1);
    # the scenario already got through by then.
    exit_ok = run.returncode == 0 or (
        sys.platform == "win32" and run.returncode == 0xC0000005)
    assert exit_ok and "survived" in run.stdout, run.stderr[-2000:]
