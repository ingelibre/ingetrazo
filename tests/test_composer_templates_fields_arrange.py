# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheet templates, dynamic fields and the arrange commands."""
from __future__ import annotations

import datetime

import pytest

from core.composition import (Cajetin, Composicion, CotaItem, MarcoVista,
                              TextoItem, expand_fields, set_field_context)


def test_dynamic_fields_read_the_sheet():
    comp = Composicion(name="Lámina 3")
    comp.frames.append(MarcoVista(w_mm=100, h_mm=80, scale_n=40.0,
                                  view_key="scene:Planta"))
    comp.frames.append(MarcoVista(w_mm=200, h_mm=120, scale_n=75.0,
                                  view_key="std:front"))
    comp.cajetin = Cajetin(proyecto="Plaza Yanque", autor="MS", lamina="L-03")
    set_field_context(comp=comp, scene=None, path="/x/pileta fuente.igz",
                      index=2, total=5)
    text = ("{proyecto} · {autor} · {lamina} · {escala} · {archivo} · "
            "{hoja}/{total} · {nombre} · {escena} · ESC. 1:{n}")
    out = expand_fields(text)
    assert out.startswith("Plaza Yanque · MS · L-03 · 1:75 · pileta fuente · 3/5")
    assert "· Lámina 3 · Planta · " in out              # main frame has no
    assert out.endswith("ESC. 1:{n}")                  # scene: any bound one;
                                                       # unknown field kept
    assert expand_fields("{fecha}") == datetime.date.today().strftime("%d/%m/%Y")
    assert expand_fields("sin campos") == "sin campos"
    set_field_context()
    assert expand_fields("{escala}|{lamina}") == "|"


def _composer(monkeypatch, tmp_path):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    monkeypatch.setattr(ComposerWindow, "templates_dir",
                        staticmethod(lambda: tmp_path))
    win = MainWindow()
    comp = ComposerWindow(win)
    return win, comp


def _close(win, comp):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def test_templates_save_reuse_and_default(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    win, comp = _composer(monkeypatch, tmp_path)
    try:
        sheet = comp.comp
        sheet.border = True
        sheet.cajetin = sheet.default_cajetin()
        sheet.cajetin.proyecto = "Plaza"
        sheet.frames[0].uid = "abc"
        sheet.cotas.append(CotaItem(anchor_uid="abc", a_world=[0, 0, 0],
                                    b_world=[1, 0, 0]))
        path = comp.save_template("Obra civil A3")
        assert path.exists() and comp.template_names() == ["Obra civil A3"]

        new = comp.new_sheet_from_template("Obra civil A3")
        assert new is comp.comp and new in win.viewport.scene.compositions
        assert new.border and new.cajetin.proyecto == "Plaza"
        assert new.frames[0].uid and new.frames[0].uid != "abc"
        assert new.cotas[0].anchor_uid == ""              # anchors dropped

        comp.set_default_template("Obra civil A3")
        n = len(win.viewport.scene.compositions)
        comp._on_comp_add()
        assert len(win.viewport.scene.compositions) == n + 1
        assert comp.comp.cajetin is not None and comp.comp.border
        comp.set_default_template(None)
        comp._on_comp_add()
        assert comp.comp.cajetin is None                  # plain sheet again
        assert comp.new_sheet_from_template("no existe") is None
    finally:
        QSettings().remove("composer/default_template")
        _close(win, comp)


def test_align_distribute_and_duplicate_are_single_undo_steps(monkeypatch, tmp_path):
    from views.composer import TextItem
    win, comp = _composer(monkeypatch, tmp_path)
    try:
        a = TextoItem(x_mm=10, y_mm=10, w_mm=40, text="a")
        b = TextoItem(x_mm=60, y_mm=30, w_mm=40, text="b")
        c = TextoItem(x_mm=150, y_mm=50, w_mm=40, text="c")
        comp.comp.texts += [a, b, c]
        comp._rebuild_canvas()

        def select_all():
            for it in comp.canvas.items():
                if isinstance(it, TextItem):
                    it.setSelected(True)
        select_all()
        comp.align_selected("left")
        assert (a.x_mm, b.x_mm, c.x_mm) == (10, 10, 10)
        assert (a.y_mm, b.y_mm, c.y_mm) == (10, 30, 50)
        comp.history.undo()
        assert (a.x_mm, b.x_mm, c.x_mm) == (10, 60, 150)   # one step

        select_all()
        comp.align_selected("top")
        assert (a.y_mm, b.y_mm, c.y_mm) == (10, 10, 10)
        select_all()
        comp.distribute_selected("x")
        # span 10..190 holds three 40 mm blocks: two gaps of 30 mm
        assert (a.x_mm, b.x_mm, c.x_mm) == pytest.approx((10, 80, 150))

        select_all()
        comp.duplicate_selected()
        assert len(comp.comp.texts) == 6
        copies = comp.comp.texts[3:]
        assert sorted(t.x_mm for t in copies) == pytest.approx([15, 85, 155])
        assert all(t.y_mm == 15 for t in copies)
        assert sorted(it.model.text for it in comp.canvas.selectedItems()
                      if isinstance(it, TextItem)) == ["a", "b", "c"]
        comp.history.undo()
        assert len(comp.comp.texts) == 3
    finally:
        _close(win, comp)


def test_movable_scale_label_is_a_bound_text_that_follows_its_frame(monkeypatch, tmp_path):
    from views.composer import FrameItem, TextItem
    win, comp = _composer(monkeypatch, tmp_path)
    try:
        frame = comp.comp.frames[0]
        frame.scale_n = 40.0
        big = MarcoVista(x_mm=150, y_mm=20, w_mm=300, h_mm=200, scale_n=100.0)
        comp.comp.frames.append(big)                 # the main frame is now 1:100
        comp._rebuild_canvas()
        label = comp.add_scale_label(frame)
        assert label in comp.comp.texts and label.frame_uid == frame.uid
        comp._set_field_context(comp.comp)
        assert expand_fields(label.text, label.frame_uid) == "ESC. 1:40"
        assert expand_fields(label.text) == "ESC. 1:100"     # unbound → main
        # The frame moves 10 mm right and 5 mm down: the label follows,
        # one undo step brings both back.
        x0, y0 = label.x_mm, label.y_mm
        before = {"x_mm": frame.x_mm, "y_mm": frame.y_mm}
        after = {"x_mm": frame.x_mm + 10.0, "y_mm": frame.y_mm + 5.0}
        frame.x_mm, frame.y_mm = after["x_mm"], after["y_mm"]
        comp.push_geometry_edit(frame, after, before)
        assert (label.x_mm, label.y_mm) == (x0 + 10.0, y0 + 5.0)
        comp.history.undo()
        assert (label.x_mm, label.y_mm) == (x0, y0)
        assert (frame.x_mm, frame.y_mm) == (before["x_mm"], before["y_mm"])
        # It is an ordinary text block: in-place editing applies to it.
        comp._rebuild_canvas()
        item = next(it for it in comp.canvas.items()
                    if isinstance(it, TextItem) and it.model is label)
        comp.edit_text_item(item)
        assert comp._inline_editor is not None and comp._inline_editor.item is item
        comp.end_inline_edit(None, None)
        # round trip keeps the binding
        back = Composicion.from_dict(comp.comp.to_dict())
        assert back.texts[-1].frame_uid == frame.uid and back.texts[-1].follow
    finally:
        _close(win, comp)


def test_group_ungroup_lock_and_group_drags(monkeypatch, tmp_path):
    from views.composer import TextItem
    win, comp = _composer(monkeypatch, tmp_path)
    try:
        a = TextoItem(x_mm=10, y_mm=10, w_mm=30, text="a")
        b = TextoItem(x_mm=60, y_mm=10, w_mm=30, text="b")
        c = TextoItem(x_mm=110, y_mm=10, w_mm=30, text="c")
        comp.comp.texts += [a, b, c]
        comp._rebuild_canvas()

        def items():
            return {it.model.text: it for it in comp.canvas.items()
                    if isinstance(it, TextItem)}
        its = items()
        its["a"].setSelected(True)
        its["b"].setSelected(True)
        comp.group_selected()
        assert a.group_id and a.group_id == b.group_id and not c.group_id
        # selecting one member selects the other
        its = items()
        comp.canvas.clearSelection()
        its["a"].setSelected(True)
        assert its["b"].isSelected() and not its["c"].isSelected()
        # a drag of the group: Qt moves both; the grabbed one reports —
        # the composer records the partner too, as ONE undo step
        comp.note_drag_start()
        a.x_mm += 7.0
        b.x_mm += 7.0
        its["b"].setPos(b.x_mm, b.y_mm)
        comp.push_geometry_edit(a, {"x_mm": a.x_mm, "y_mm": a.y_mm},
                                {"x_mm": 10.0, "y_mm": 10.0})
        assert (a.x_mm, b.x_mm) == (17.0, 67.0)
        comp.history.undo()
        assert (a.x_mm, b.x_mm) == (10.0, 60.0)
        # duplicating a group yields a NEW group for the copies
        its = items()
        comp.canvas.clearSelection()
        its["a"].setSelected(True)
        comp.duplicate_selected()
        copies = comp.comp.texts[3:]
        assert len(copies) == 2 and copies[0].group_id == copies[1].group_id
        assert copies[0].group_id != a.group_id
        comp.history.undo()
        # lock toggles the whole selection, twice = back
        its = items()
        comp.canvas.clearSelection()
        its["a"].setSelected(True)
        comp.lock_selected()
        assert a.locked and b.locked and not c.locked
        its = items()
        comp.canvas.clearSelection()
        its["a"].setSelected(True)
        comp.lock_selected()
        assert not a.locked and not b.locked
        # ungroup, and delete removes every selected item in one step
        its = items()
        comp.canvas.clearSelection()
        its["b"].setSelected(True)
        comp.ungroup_selected()
        assert not a.group_id and not b.group_id
        its = items()
        comp.canvas.clearSelection()
        its["a"].setSelected(True)
        its["c"].setSelected(True)
        comp._on_delete_item()
        assert [t.text for t in comp.comp.texts] == ["b"]
        comp.history.undo()
        assert sorted(t.text for t in comp.comp.texts) == ["a", "b", "c"]
        assert Composicion.from_dict(comp.comp.to_dict()).texts[0].group_id == ""
    finally:
        _close(win, comp)
