# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Title-block designs (corner shapes, layouts, colours), the built-in
presets, and user title-block templates."""
from __future__ import annotations

from PySide6.QtGui import QImage, QPainter

from core.composition import (CAJETIN_DESIGN_BASE, CAJETIN_DESIGNS, Cajetin,
                              Composicion)


def _render(c: Cajetin, scale: int = 3) -> QImage:
    from views.composer import paint_cajetin_mm
    img = QImage(int((c.w_mm + 4) * scale), int((c.h_mm + 4) * scale),
                 QImage.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    p.scale(scale, scale)
    p.translate(2, 2)
    paint_cajetin_mm(p, c)
    p.end()
    return img


def _rgb(img: QImage, x: int, y: int) -> int:
    return img.pixel(x, y) & 0xFFFFFF


def test_look_fields_round_trip_and_old_documents_default():
    c = Composicion()
    c.cajetin = Cajetin(w_mm=120.0, h_mm=30.0, corner="rounded", radius_mm=4.0,
                        layout="banded", double_border=True, fill_color="#eeeeee",
                        label_color="#333333", text_color="#111111",
                        line_color="#222222", label_mm=35.0)
    back = Composicion.from_dict(c.to_dict()).cajetin
    assert back.look() == c.cajetin.look()
    d = c.to_dict()
    for k in Cajetin.LOOK_FIELDS:
        d["cajetin"].pop(k, None)               # a pre-designs document
    old = Composicion.from_dict(d).cajetin
    assert old.look() == dict(CAJETIN_DESIGN_BASE)
    assert old.design_key() == "classic"


def test_every_preset_paints_and_is_recognised():
    for key, _label, fields in CAJETIN_DESIGNS:
        c = Cajetin(w_mm=150.0, h_mm=36.0, **dict(CAJETIN_DESIGN_BASE, **fields))
        assert c.design_key() == key
        img = _render(c)
        assert img.width() > 0                  # painted without raising
        for cols in (1, 2, 3):
            c.columns = cols
            _render(c)
    custom = Cajetin(**dict(CAJETIN_DESIGN_BASE, fill_color="#123456"))
    assert custom.design_key() == ""


def test_rounded_and_chamfered_corners_clip_the_fill():
    base = dict(w_mm=100.0, h_mm=30.0, fill_color="#3355aa", columns=1)
    square = _render(Cajetin(corner="square", **base))
    rounded = _render(Cajetin(corner="rounded", radius_mm=6.0, **base))
    chamfer = _render(Cajetin(corner="chamfer", radius_mm=6.0, **base))
    # the label column is filled: the very corner is fill with square
    # corners and page-white when the corner is cut away
    corner = (int(2.4 * 3), int(2.4 * 3))
    assert _rgb(square, *corner) == 0x3355AA
    assert _rgb(rounded, *corner) == 0xFFFFFF
    assert _rgb(chamfer, *corner) == 0xFFFFFF
    # deeper inside, all three are filled
    inside = (int(12 * 3), int(15 * 3))
    assert {_rgb(square, *inside), _rgb(rounded, *inside),
            _rgb(chamfer, *inside)} == {0x3355AA}


def test_banded_and_minimal_layouts_differ_from_the_grid():
    rows = [["PROYECTO", "Plaza de Yanque"], ["AUTOR", "Municipalidad"],
            ["FECHA", "2026"], ["LÁMINA", "L-01"]]
    grid = Cajetin(w_mm=120.0, h_mm=36.0, campos=[list(r) for r in rows])
    banded = Cajetin(w_mm=120.0, h_mm=36.0, campos=[list(r) for r in rows],
                     layout="banded", fill_color="#dddddd")
    minimal = Cajetin(w_mm=120.0, h_mm=36.0, campos=[list(r) for r in rows],
                      layout="minimal")
    g, b, m = _render(grid), _render(banded), _render(minimal)
    assert g != b and g != m and b != m
    # banded: the whole top band is filled, edge to edge
    assert _rgb(b, int(60 * 3), int(4 * 3)) == 0xDDDDDD
    assert _rgb(b, int(110 * 3), int(4 * 3)) == 0xDDDDDD
    # grid: no fill there (white page under the value cell)
    assert _rgb(g, int(110 * 3), int(4 * 3)) == 0xFFFFFF


def test_double_border_draws_a_second_outline_inside():
    single = _render(Cajetin(w_mm=100.0, h_mm=30.0, border_mm=0.5))
    double = _render(Cajetin(w_mm=100.0, h_mm=30.0, border_mm=0.5,
                             double_border=True))
    # a strip 1–1.5 mm inside the left edge, mid-height: ink only with the
    # double border (the outer line sits at 0 mm, the label column at 28)
    # (sampled between the first row's text and the row line under it)
    y = int((2 + 5.4) * 3)
    xs = range(int((2 + 0.9) * 3), int((2 + 1.6) * 3) + 1)
    dark_single = any(_rgb(single, x, y) != 0xFFFFFF for x in xs)
    dark_double = any(_rgb(double, x, y) != 0xFFFFFF for x in xs)
    assert dark_double and not dark_single


def test_template_dict_keeps_rows_size_and_look_only():
    c = Cajetin(x_mm=50.0, y_mm=60.0, z=7.0, w_mm=140.0, h_mm=40.0,
                corner="rounded", campos=[["OBRA", "Pileta"]], locked=True)
    d = c.template_dict()
    assert d["w_mm"] == 140.0 and d["campos"] == [["OBRA", "Pileta"]]
    assert d["corner"] == "rounded"
    assert not {"x_mm", "y_mm", "z", "locked", "group_id"} & set(d)
    fresh = Cajetin(x_mm=1.0, y_mm=2.0)
    for k, v in d.items():
        setattr(fresh, k, v)
    assert (fresh.x_mm, fresh.y_mm) == (1.0, 2.0) and fresh.look() == c.look()


def _composer(monkeypatch, tmp_path):
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    monkeypatch.setattr(ComposerWindow, "cajetin_templates_dir",
                        staticmethod(lambda: tmp_path))
    store = {}
    monkeypatch.setattr(ComposerWindow, "default_cajetin_template_name",
                        staticmethod(lambda: store.get("d")))
    monkeypatch.setattr(ComposerWindow, "set_default_cajetin_template",
                        staticmethod(lambda n: store.__setitem__("d", n)))
    win = MainWindow()
    return win, ComposerWindow(win), store


def _close(win, comp):
    comp.close()
    win._saved_version = win.viewport.scene.version
    win.close()


def _select(comp, model):
    comp._rebuild_canvas()
    it = comp._item_for(model)
    it.setSelected(True)
    comp.on_selection_changed()
    return it


def test_panel_design_presets_apply_and_keep_the_rows(monkeypatch, tmp_path):
    win, comp, _ = _composer(monkeypatch, tmp_path)
    try:
        comp._on_add_cajetin()
        c = comp.comp.cajetin
        rows = [list(r) for r in c.campos]
        _select(comp, c)
        assert comp.caj_design.currentData() == "classic"
        comp.caj_design.setCurrentIndex(comp.caj_design.findData("banded"))
        assert c.design_key() == "banded"
        assert c.layout == "banded" and c.fill_color == "#dfe4ea"
        assert c.campos == rows                    # the rows stay
        assert comp.caj_layout.currentData() == "banded"
        assert comp.caj_fill_check.isChecked()
        comp.caj_corner.setCurrentIndex(comp.caj_corner.findData("rounded"))
        assert c.corner == "rounded"
        comp.caj_double.setChecked(True)
        assert c.double_border is True
        assert comp.caj_design.currentData() == ""   # now the user's own
        comp.history.undo()
        assert c.double_border is False
        comp.caj_fill_check.setChecked(False)
        assert c.fill_color == ""
        from views.composer import ComposerWindow
        assert "corner" in ComposerWindow.STYLE_FIELDS[Cajetin]
    finally:
        _close(win, comp)


def test_title_block_templates_save_apply_and_default(monkeypatch, tmp_path):
    win, comp, store = _composer(monkeypatch, tmp_path)
    try:
        comp._on_add_cajetin()
        c = comp.comp.cajetin
        c.campos = [["OBRA", "Pileta"], ["LÁMINA", "L-07"]]
        c.corner, c.radius_mm, c.w_mm = "chamfer", 4.0, 140.0
        path = comp.save_cajetin_template("Municipal", c)
        assert path.is_file() and comp.cajetin_template_names() == ["Municipal"]
        d = comp.load_cajetin_template("Municipal")
        assert d["campos"] == [["OBRA", "Pileta"], ["LÁMINA", "L-07"]]
        assert d["corner"] == "chamfer" and "x_mm" not in d and "name" not in d
        assert comp.load_cajetin_template("nope") is None

        scene = win.viewport.scene
        second = Composicion(name="L2")
        scene.compositions.append(second)
        comp._on_comp_switched(scene.compositions.index(second))
        comp._on_add_cajetin()
        c2 = second.cajetin
        pos = (c2.x_mm, c2.y_mm)
        it = _select(comp, c2)
        assert comp.caj_design.findData("tpl:Municipal") >= 0
        assert comp.apply_cajetin_template(it, "Municipal")
        assert c2.campos == [["OBRA", "Pileta"], ["LÁMINA", "L-07"]]
        assert (c2.corner, c2.radius_mm, c2.w_mm) == ("chamfer", 4.0, 140.0)
        assert (c2.x_mm, c2.y_mm) == pos           # stays where it was
        comp.history.undo()
        assert c2.corner == "square" and c2.campos[0][0] == "PROYECTO"

        comp.set_default_cajetin_template("Municipal")
        third = Composicion(name="L3")
        scene.compositions.append(third)
        comp._on_comp_switched(scene.compositions.index(third))
        comp._on_add_cajetin()
        c3 = third.cajetin
        assert c3.corner == "chamfer" and c3.w_mm == 140.0
        assert c3.campos[0] == ["OBRA", "Pileta"]
        assert any(r[0] == "FECHA" and r[1] for r in c3.campos)
        pw, ph = third.page_size_mm()
        m = third.margin_mm
        assert abs(c3.x_mm - (pw - m - 140.0)) < 1e-6   # docked with its size
        assert abs(c3.y_mm - (ph - m - c3.h_mm)) < 1e-6
    finally:
        _close(win, comp)
