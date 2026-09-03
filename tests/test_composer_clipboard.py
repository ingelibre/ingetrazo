# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Copy / cut / paste of sheet items (Ctrl+C / Ctrl+X / Ctrl+V), within a
sheet and across sheets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from core.composition import (AddItemCommand, Composicion, CotaItem,
                              EtiquetaItem, MarcoVista, TextoItem)


def _composer(monkeypatch):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    ComposerWindow._clipboard = []
    ComposerWindow._clipboard_from = None
    win = MainWindow()
    return win, ComposerWindow(win)


def _close(win, comp):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_copy_paste_offsets_remaps_bindings_and_undoes_in_one_step(monkeypatch):
    from views.composer import ComposerWindow, _SheetItem
    win, comp = _composer(monkeypatch)
    try:
        f = MarcoVista(x_mm=20.0, y_mm=20.0, w_mm=80.0, h_mm=60.0, uid="f1")
        t = TextoItem(x_mm=60.0, y_mm=82.0, w_mm=40.0, text="ESC. {escala}",
                      frame_uid="f1")
        cota = CotaItem(x_mm=30.0, y_mm=30.0, dx_mm=40.0, anchor_uid="f1",
                        a_world=[0.0, 0.0, 0.0], b_world=[1.0, 0.0, 0.0])
        loose = EtiquetaItem(x_mm=120.0, y_mm=30.0, text="Muro",
                             anchor_uid="other", a_world=[0.0, 0.0, 0.0])
        for m in (f, t, cota, loose):
            comp.history.execute(AddItemCommand(comp.comp, m))
        comp._rebuild_canvas()
        for m in (f, t, cota, loose):
            comp._item_for(m).setSelected(True)
        comp.copy_selected()
        assert len(ComposerWindow._clipboard) == 4
        assert all(c is not m for c in ComposerWindow._clipboard
                   for m in (f, t, cota, loose))
        n0 = len(comp.comp.all_items())
        comp.paste_clipboard()
        assert len(comp.comp.all_items()) == n0 + 4
        f2, t2 = comp.comp.frames[-1], comp.comp.texts[-1]
        c2, l2 = comp.comp.cotas[-1], comp.comp.etiquetas[-1]
        assert f2 is not f and f2.uid and f2.uid != "f1"
        assert (f2.x_mm, f2.y_mm, t2.x_mm, t2.y_mm) == (25.0, 25.0, 65.0, 87.0)
        assert t2.frame_uid == f2.uid                    # follows the copy
        assert c2.anchor_uid == f2.uid and c2.a_world == [0.0, 0.0, 0.0]
        assert l2.anchor_uid == "" and l2.a_world is None  # frame not copied
        assert f2.z > f.z and min(m.z for m in (f2, t2, c2, l2)) > max(
            m.z for m in (f, t, cota, loose))
        sel = {id(it.model) for it in comp.canvas.selectedItems()
               if isinstance(it, _SheetItem)}
        assert sel == {id(m) for m in (f2, t2, c2, l2)}
        comp.paste_clipboard()                            # steps further
        assert (comp.comp.frames[-1].x_mm, comp.comp.texts[-1].y_mm) == (
            30.0, 92.0)
        assert comp.comp.texts[-1].frame_uid == comp.comp.frames[-1].uid
        comp.history.undo()
        assert len(comp.comp.all_items()) == n0 + 4
        comp.history.undo()
        assert len(comp.comp.all_items()) == n0
        assert f in comp.comp.frames and t in comp.comp.texts
    finally:
        _close(win, comp)


def test_cut_and_paste_between_sheets_keeps_the_place(monkeypatch):
    win, comp = _composer(monkeypatch)
    try:
        first = comp.comp
        f = MarcoVista(x_mm=10.0, y_mm=10.0, uid="f1")
        t = TextoItem(x_mm=40.0, y_mm=50.0, w_mm=30.0, text="Corte",
                      frame_uid="f1")
        comp.history.execute(AddItemCommand(first, f))
        comp.history.execute(AddItemCommand(first, t))
        comp._rebuild_canvas()
        comp._item_for(t).setSelected(True)
        comp.cut_selected()
        assert t not in first.texts and f in first.frames
        comp.history.undo()
        assert t in first.texts                           # cut = one step
        comp.history.redo()
        second = Composicion(name="Lámina 2")
        scene = win.viewport.scene
        scene.compositions.append(second)
        comp._on_comp_switched(scene.compositions.index(second))
        assert comp.comp is second
        comp.paste_clipboard()
        t2 = second.texts[-1]
        assert (t2.x_mm, t2.y_mm, t2.text) == (40.0, 50.0, "Corte")
        assert t2.frame_uid == ""              # its frame stayed on sheet 1
        comp.paste_clipboard()                 # now it is "this sheet": steps
        assert second.texts[-1].x_mm == 45.0
        comp.history.undo()
        comp.history.undo()
        assert second.texts == []
    finally:
        _close(win, comp)


def test_keys_reach_the_canvas_but_not_the_inline_editor(monkeypatch):
    from views.composer import ComposerCanvasView, ComposerWindow
    win, comp = _composer(monkeypatch)
    try:
        t = TextoItem(x_mm=40.0, y_mm=50.0, w_mm=30.0, text="Planta")
        comp.history.execute(AddItemCommand(comp.comp, t))
        comp._rebuild_canvas()
        view = comp.findChildren(ComposerCanvasView)[0]
        item = comp._item_for(t)
        item.setSelected(True)
        QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier)
        assert [m.text for m in ComposerWindow._clipboard] == ["Planta"]
        QTest.keyClick(view, Qt.Key_V, Qt.ControlModifier)
        assert len(comp.comp.texts) == 2 and comp.comp.texts[-1].x_mm == 45.0
        # while editing in place the keys belong to the editor
        comp.begin_inline_edit(comp._item_for(t))
        ComposerWindow._clipboard = []
        QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier)
        assert ComposerWindow._clipboard == []
        comp.end_inline_edit(None, None)
    finally:
        _close(win, comp)


def test_property_pages_keep_their_rows_at_the_top(monkeypatch):
    from PySide6.QtWidgets import QScrollArea
    win, comp = _composer(monkeypatch)
    try:
        page = comp.props.widget(2)               # the text block page
        assert isinstance(page, QScrollArea) and page.widgetResizable()
        lay = page.widget().layout()
        assert lay.count() == 2 and lay.itemAt(1).spacerItem() is not None
        assert comp.text_bold.isAncestorOf(comp.text_bold) or page.isAncestorOf(comp.text_bold)
    finally:
        _close(win, comp)
