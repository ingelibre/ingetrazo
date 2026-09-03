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
