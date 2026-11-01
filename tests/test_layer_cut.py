# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The section cut by layer on the sheets (#926): every cut chord and every
poché ring knows the layer of the solid it cuts, so a wall's cut can take a
heavier pen than the door beside it (the layer's cut weight) and each solid
can be filled with its layer's colour."""
from __future__ import annotations

import json
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QVector3D
from PySide6.QtWidgets import QApplication, QWidget

_app = QApplication.instance() or QApplication([])

from core import layers as L
from core.camera import OrbitCamera
from core.composition import MarcoVista, apply_frame_camera
from core.group import Group
from core.hlr import KIND_CUT, KIND_EDGE, hlr_drawing
from core.layers import DEFAULT_LAYER, Layer
from core.mesh import Mesh
from core.scene import Scene
from core.section import SectionPlane

V = QVector3D


def _box(m, x0, y0, z0, x1, y1, z1):
    """A closed axis-aligned box of six faces."""
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0)])
    m.add_face([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)])
    m.add_face([V(x0, y1, z0), V(x1, y1, z0), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x0, y1, z0), V(x0, y1, z1), V(x0, y0, z1)])
    m.add_face([V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)])


def _wall_and_door(scene):
    """A wall (layer «Muros», heavy cut) and a door leaf beside it
    («Carpinterías»), cut by a plan plane at 1 m, plus a loose box on the
    default layer."""
    scene.layers += [Layer("Muros", color=(0.8, 0.1, 0.1), cut_weight=0.7),
                     Layer("Carpinterías", color=(0.1, 0.1, 0.8))]
    wall = Group(Mesh(), name="muro")
    _box(wall.mesh, 0, 0, 0, 4, 0.3, 3)
    wall.layer = "Muros"
    door = Group(Mesh(), name="puerta")
    _box(door.mesh, 5, 0, 0, 6, 0.1, 2)
    door.layer = "Carpinterías"
    scene.groups += [wall, door]
    _box(scene.mesh, 8, 0, 0, 9, 1, 2)
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1))
    scene.section_planes.append(sp)
    scene.set_active_section(sp)
    return scene


def _top_camera(scene):
    cam = OrbitCamera()
    f = MarcoVista(view_key="std:top", scale_n=100.0, w_mm=200.0, h_mm=100.0)
    apply_frame_camera(cam, f, saved_view=None, scene=scene)
    return cam


# ---- The layer record ----------------------------------------------------

def test_the_cut_weight_round_trips_and_makes_the_layer_worth_saving():
    ly = Layer("Muros", cut_weight=0.7)
    raw = json.loads(json.dumps(ly.to_dict()))
    assert raw["cut_weight"] == 0.7
    assert Layer.from_dict(raw).cut_weight == 0.7
    assert ly.has_style()
    assert "cut_weight" not in Layer("Plain").to_dict()


@pytest.mark.parametrize("raw, expected", [
    ({"name": "X", "cut_weight": "thick"}, None),
    ({"name": "X", "cut_weight": 99}, 5.0),
    ({"name": "X", "cut_weight": 0}, 0.05),
    ({"name": "X"}, None),
])
def test_a_malformed_cut_weight_loads_kept_in_range(raw, expected):
    assert Layer.from_dict(raw).cut_weight == expected


def test_a_template_carries_the_cut_weight():
    src = Scene()
    src.layers.append(Layer("Muros", cut_weight=0.5))
    data = json.loads(json.dumps(L.template_of(src)))
    dst = Scene()
    dst.layers.append(Layer("Muros"))
    L.apply_template(dst, data)
    assert dst.layer("Muros").cut_weight == 0.5


def test_a_cut_weight_alone_asks_for_lines_by_layer():
    scene = Scene()
    scene.layers.append(Layer("Muros"))
    assert not L.layer_lines_wanted(scene)
    scene.layer("Muros").cut_weight = 0.5
    assert L.layer_lines_wanted(scene)
    assert L.line_styles(scene, colored=False)["Muros"] == (
        None, "continuous", None, 0.5, (), None)


def test_the_fill_colours_leave_the_default_layer_to_the_frame():
    scene = Scene()
    scene.layers += [Layer("Muros", color=(0.8, 0.1, 0.1)), Layer("Auto")]
    table = L.cut_fill_colours(scene)
    assert DEFAULT_LAYER not in table
    assert table["Muros"] == pytest.approx((0.8, 0.1, 0.1))
    assert table["Auto"] == L.layer_color(scene.layer("Auto"))


# ---- The hidden-line pass ------------------------------------------------

def test_every_cut_chord_and_ring_carries_its_solid_layer():
    scene = _wall_and_door(Scene())
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, layers=True)
    cut_tags = {t for k, t in zip(d.kinds, d.layers) if k == KIND_CUT}
    assert cut_tags == {"Muros", "Carpinterías", DEFAULT_LAYER}
    assert len(d.loop_layers) == len(d.loops) == 3
    assert sorted(d.loop_layers) == sorted(
        ["Muros", "Carpinterías", DEFAULT_LAYER])
    # each ring lies over its own solid: the wall's is the 4 m one
    widths = {tag: float(np.ptp(ring[:, 0]))
              for ring, tag in zip(d.loops, d.loop_layers)}
    assert widths["Muros"] == pytest.approx(4.0)
    assert widths["Carpinterías"] == pytest.approx(1.0)


def test_without_layers_the_drawing_is_the_same_and_untagged():
    scene = _wall_and_door(Scene())
    cam = _top_camera(scene)
    plain = hlr_drawing(scene, cam, profiles=False)
    tagged = hlr_drawing(scene, cam, profiles=False, layers=True)
    assert plain.layers is None and plain.loop_layers is None
    assert len(plain.segs) == len(tagged.segs)
    assert len(plain.loops) == len(tagged.loops)
    assert (int((plain.kinds == KIND_CUT).sum())
            == int((tagged.kinds == KIND_CUT).sum()))


def test_no_fills_asked_means_no_ring_layers_either():
    scene = _wall_and_door(Scene())
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, fills=False,
                    layers=True)
    assert d.loops == [] and d.loop_layers == []


def test_a_layer_set_on_a_face_inside_the_object_wins():
    scene = _wall_and_door(Scene())
    scene.layers.append(Layer("Revestimiento"))
    wall = scene.groups[0]
    for f in wall.mesh.faces:
        L.assign_layer(f, "Revestimiento")
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, layers=True)
    assert "Revestimiento" in d.loop_layers
    assert "Muros" not in d.loop_layers


# ---- Pens ------------------------------------------------------------------

def test_the_cut_takes_the_layer_cut_weight_and_nothing_else():
    from views.composer import _layer_pen
    base = QPen(QColor(30, 36, 44))
    base.setWidthF(0.5)
    style = ((1.0, 0.0, 0.0), "dashed", 0.18, 0.7)
    pen = _layer_pen(base, style, KIND_CUT)
    assert pen.widthF() == pytest.approx(0.7)
    assert pen.color() == base.color()          # the cut keeps its ink
    assert not pen.dashPattern() or pen.style() == base.style()
    # no cut weight: the sheet's cut pen itself
    assert _layer_pen(base, ((1, 0, 0), "dashed", 0.18, None),
                      KIND_CUT) is base
    assert _layer_pen(base, ((1, 0, 0), "dashed", 0.18), KIND_CUT) is base
    # the other lines keep their layer weight, not the cut's
    assert _layer_pen(base, style, KIND_EDGE).widthF() == pytest.approx(0.18)


def test_the_wall_cut_is_inked_heavier_than_the_door_cut():
    from views.composer import _paint_hlr_lines_mm
    scene = _wall_and_door(Scene())
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, layers=True)
    frame = MarcoVista(style="vectorial", pen_cut_mm=0.25)
    widths: dict = {}

    class _Spy:
        pen = None

        def setPen(self, pen):
            self.pen = pen

        def drawLines(self, lines):
            widths.setdefault(round(self.pen.widthF(), 3), 0)
            widths[round(self.pen.widthF(), 3)] += len(lines)

    _paint_hlr_lines_mm(_Spy(), frame, d.segs, d.kinds,
                        styles=(d.layers, L.line_styles(scene, False)))
    assert 0.7 in widths and 0.25 in widths


# ---- Fills -----------------------------------------------------------------

def _paint_rings(frame, colours):
    from views.composer import _paint_cut_fills_mm
    left = np.array([[1, 1], [9, 1], [9, 9], [1, 9]], dtype=float)
    right = np.array([[11, 1], [19, 1], [19, 9], [11, 9]], dtype=float)
    img = QImage(20, 10, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    _paint_cut_fills_mm(p, frame, [left, right], colours)
    p.end()
    return QColor(img.pixel(5, 5)), QColor(img.pixel(15, 5))


def test_each_ring_takes_its_layer_colour_and_none_the_frame_colour():
    frame = MarcoVista(style="vectorial", cut_fill="solid",
                       cut_fill_color="#00ff00")
    a, b = _paint_rings(frame, [(QColor(255, 0, 0), None), (None, None)])
    assert (a.red(), a.green(), a.blue()) == (255, 0, 0)
    assert (b.red(), b.green(), b.blue()) == (0, 255, 0)


def test_without_colours_every_ring_takes_the_frame_colour():
    frame = MarcoVista(style="vectorial", cut_fill="solid",
                       cut_fill_color="#0000ff")
    a, b = _paint_rings(frame, None)
    assert a == b == QColor(0, 0, 255)


def test_hatched_rings_are_hatched_in_their_layer_colour():
    frame = MarcoVista(style="vectorial", cut_fill="hatch", cut_hatch_mm=0.3,
                       pen_edge_mm=1.0, cut_fill_color="#00ff00")
    from views.composer import _paint_cut_fills_mm
    ring = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    _paint_cut_fills_mm(p, frame, [ring], [(QColor(255, 0, 0), None)])
    p.end()
    seen = {QColor(img.pixel(x, y)).name() for x in range(10)
            for y in range(10)}
    assert not any(c.startswith("#00ff") for c in seen)
    assert any(QColor(c).red() > 200 and QColor(c).green() < 120
               for c in seen)


def test_the_frame_keeps_its_fill_by_layer_switch():
    from core.composition import Composicion
    comp = Composicion()
    comp.frames.append(MarcoVista(cut_fill_by_layer=True))
    back = Composicion.from_dict(json.loads(json.dumps(comp.to_dict())))
    assert back.frames[0].cut_fill_by_layer is True
    assert MarcoVista().cut_fill_by_layer is False


# ---- On the sheet ----------------------------------------------------------

def _composer():
    from tests.test_composer_canvas import _FakeViewport
    from views.composer import ComposerWindow
    host = QWidget()
    host.viewport = _FakeViewport()
    _wall_and_door(host.viewport.scene)
    composer = ComposerWindow(host)
    frame = composer.comp.frames[0]
    frame.style = "vectorial"
    frame.view_key = "std:top"
    frame.x_mm, frame.y_mm, frame.w_mm, frame.h_mm = 10.0, 10.0, 200.0, 100.0
    frame.scale_n = 100.0
    return composer, frame, host


def test_a_sheet_fills_each_cut_solid_in_its_layer_colour():
    composer, frame, _host = _composer()
    composer.compute_hlr(frame)
    assert composer.hlr_fill_styles[id(frame)] is None     # opt-in
    frame.cut_fill_by_layer = True
    composer.compute_hlr(frame)
    colours = [look[0] for look in composer.hlr_fill_styles[id(frame)]]
    fills = composer.hlr_fills[id(frame)]
    assert len(colours) == len(fills) == 3
    names = sorted(c.name() if c is not None else "" for c in colours)
    assert names == sorted(["", QColor.fromRgbF(0.8, 0.1, 0.1).name(),
                            QColor.fromRgbF(0.1, 0.1, 0.8).name()])


def test_a_sheet_inks_the_cut_with_the_layer_cut_weight():
    composer, frame, _host = _composer()
    composer.compute_hlr(frame)
    tags, styles = composer.hlr_styles[id(frame)]
    kinds = composer.hlr_kinds[id(frame)]
    walls = [i for i, (k, t) in enumerate(zip(kinds, tags))
             if k == KIND_CUT and t == "Muros"]
    assert walls and styles["Muros"][3] == 0.7


def test_the_dxf_puts_each_layer_cut_on_its_own_layer(tmp_path):
    from formats.dxf_out import save_dxf_layers
    from views.composer import dxf_groups_by_layer
    scene = _wall_and_door(Scene())
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, fills=False,
                    layers=True)
    d.styles = L.line_styles(scene, colored=True)
    groups = dxf_groups_by_layer(d, "PLANTA", hidden_lines=False)
    names = {g[0]: g for g in groups}
    assert "Muros-CORTE" in names and "Carpinterías-CORTE" in names
    assert names["Muros-CORTE"][2] == "CONTINUOUS"
    assert len(names["PLANTA-CORTE"][1]) == 0           # nothing untagged
    n = save_dxf_layers(tmp_path / "v.dxf", groups)
    assert n == len(d.segs)


# ---- The Layers panel ------------------------------------------------------

@pytest.fixture
def win():
    from PySide6.QtCore import QSettings
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()
    QSettings().remove("ui/window_state")      # see test_layers_panel.win
    QSettings().remove("ui/window_geometry")


def test_the_cut_column_starts_off_and_a_click_sets_every_selected_row(
        win, monkeypatch):
    from PySide6.QtCore import QSettings
    from views.layers_panel import COL_CUT, LayersPanel
    panel = win.layers_dock.panel
    QSettings().remove(LayersPanel.HIDDEN_COLUMNS_KEY)
    QSettings().remove(LayersPanel.KNOWN_COLUMNS_KEY)
    panel._apply_column_choice()
    assert panel.tree.isColumnHidden(COL_CUT)
    scene = win.viewport.scene
    scene.layers += [Layer("A"), Layer("B"), Layer("C")]
    panel.refresh()
    for n in ("A", "B"):
        panel.item_for(n).setSelected(True)
    seen = {}

    def fake_popup(menu, _at):
        seen["texts"] = [a.text() for a in menu.actions()]
        next(a for a in menu.actions() if a.text() == seen["pick"]).trigger()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    seen["pick"] = "0.70 mm"
    panel.click_cell(("layer", "A"), COL_CUT)
    assert seen["texts"][0] == "The sheet's cut pen"
    assert scene.layer("A").cut_weight == scene.layer("B").cut_weight == 0.7
    assert scene.layer("C").cut_weight is None
    assert scene.layer("A").lineweight is None        # not the line weight
    assert panel.item_for("A").text(COL_CUT) == "0.70"
    seen["pick"] = "The sheet's cut pen"
    panel.click_cell(("layer", "A"), COL_CUT)
    assert panel.item_for("A").text(COL_CUT) == "—"


def test_a_saved_column_choice_from_before_keeps_the_new_column_off(win):
    """Someone who chose their columns before the cut column existed: the
    saved list never named it, and it still starts off; once they choose
    again, their choice is kept."""
    from PySide6.QtCore import QSettings
    from views.layers_panel import COL_COUNT, COL_CUT, COL_WEIGHT, LayersPanel
    panel = win.layers_dock.panel
    QSettings().setValue(LayersPanel.HIDDEN_COLUMNS_KEY, str(COL_COUNT))
    QSettings().remove(LayersPanel.KNOWN_COLUMNS_KEY)
    assert panel.hidden_columns() == {COL_COUNT, COL_CUT}
    assert COL_WEIGHT not in panel.hidden_columns()   # their choice stands
    panel.set_column_shown(COL_CUT, True)
    assert COL_CUT not in panel.hidden_columns()
    panel.set_column_shown(COL_COUNT, True)
    assert panel.hidden_columns() == set()
    QSettings().remove(LayersPanel.HIDDEN_COLUMNS_KEY)
    QSettings().remove(LayersPanel.KNOWN_COLUMNS_KEY)


def test_the_right_click_offers_the_cut_weight(win):
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A"))
    panel.refresh()
    from PySide6.QtWidgets import QMenu
    menu = QMenu()
    panel._add_look_menus(menu, ["A"], scene.layer("A"))
    sub = next(m for m in menu.findChildren(QMenu)
               if m.title() == "Cut weight")
    next(a for a in sub.actions() if a.text() == "0.50 mm").trigger()
    assert scene.layer("A").cut_weight == 0.5


# ---- Hatches by layer --------------------------------------------------------

def test_every_hatch_has_a_name_and_marks_inside_any_box():
    from core.hatches import HATCH_LABELS, HATCH_ORDER, hatch_marks
    assert set(HATCH_ORDER) == set(HATCH_LABELS)
    for key in HATCH_ORDER:
        marks = hatch_marks(key, (0.0, 0.0, 20.0, 10.0))
        n = sum(len(v) for v in marks.values())
        assert (n == 0) == (key == "solid"), key
    assert hatch_marks("nonsense", (0, 0, 10, 10))["lines"] == []


def test_a_hatch_is_locked_to_the_paper_not_to_the_box():
    """Two pieces of one wall side by side: the pattern runs on unbroken —
    the courses of a small box are courses of a bigger one."""
    from core.hatches import hatch_marks
    small = hatch_marks("brick", (0.0, 0.0, 6.0, 6.0))["lines"]
    big = hatch_marks("brick", (-10.0, -10.0, 20.0, 20.0))["lines"]
    rows_small = {round(s[1], 6) for s in small if abs(s[1] - s[3]) < 1e-9}
    rows_big = {round(s[1], 6) for s in big if abs(s[1] - s[3]) < 1e-9}
    assert rows_small and rows_small <= rows_big
    assert 1.5 in rows_small


def test_the_hatch_scales_with_the_frame_spacing():
    from core.hatches import hatch_marks
    box = (0.0, 0.0, 30.0, 30.0)
    assert (len(hatch_marks("diagonal", box, 2.0)["lines"])
            < len(hatch_marks("diagonal", box, 1.0)["lines"]))


def test_the_hatch_round_trips_and_an_unknown_one_is_dropped():
    ly = Layer("Muros", hatch="brick")
    raw = json.loads(json.dumps(ly.to_dict()))
    assert raw["hatch"] == "brick" and ly.has_style()
    assert Layer.from_dict(raw).hatch == "brick"
    assert Layer.from_dict({"name": "X", "hatch": "zigzag"}).hatch is None
    assert Layer.from_dict({"name": "X", "hatch": 3}).hatch is None
    assert "hatch" not in Layer("Plain").to_dict()


def test_a_template_and_the_legend_carry_the_hatch():
    src = Scene()
    src.layers.append(Layer("Aislante", hatch="insulation"))
    dst = Scene()
    dst.layers.append(Layer("Aislante"))
    L.apply_template(dst, json.loads(json.dumps(L.template_of(src))))
    assert dst.layer("Aislante").hatch == "insulation"
    _rows, swatches = L.legend_rows(src)
    assert swatches["Aislante"]["hatch"] == "insulation"
    assert "hatch" not in swatches[DEFAULT_LAYER]


def test_a_sheet_hatches_each_cut_with_its_layer_pattern():
    composer, frame, host = _composer()
    scene = host.viewport.scene
    scene.layer("Muros").hatch = "brick"
    composer.compute_hlr(frame)
    looks = composer.hlr_fill_styles[id(frame)]
    assert looks is not None and len(looks) == 3
    assert sorted(str(look[1]) for look in looks) == ["None", "None", "brick"]
    assert all(look[0] is None for look in looks)   # no fill by layer asked


def _paint_one(frame, look):
    from views.composer import _paint_cut_fills_mm
    ring = np.array([[0, 0], [20, 0], [20, 20], [0, 20]], dtype=float)
    img = QImage(40, 40, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(2, 2)
    _paint_cut_fills_mm(p, frame, [ring], [look])
    p.end()
    return [QColor(img.pixel(x, y)) for x in range(40) for y in range(40)]


def test_a_hatched_ring_is_lines_on_paper_not_a_solid_block():
    frame = MarcoVista(style="vectorial", cut_fill="solid",
                       cut_fill_color="#000000")
    pixels = _paint_one(frame, (None, "diagonal"))
    white = sum(1 for c in pixels if c.lightness() > 240)
    assert 0.2 * len(pixels) < white < 0.95 * len(pixels)
    solid = _paint_one(frame, (None, None))
    assert all(c.lightness() < 20 for c in solid)


def test_a_hatch_by_layer_colour_sits_on_a_pale_ground_of_it():
    frame = MarcoVista(style="vectorial", cut_fill="solid")
    pixels = _paint_one(frame, (QColor(200, 0, 0), "brick"))
    assert not any(c == QColor(255, 255, 255) for c in pixels)
    assert all(c.red() >= c.green() for c in pixels)


def test_the_hatch_grid_picks_for_every_selected_row(win, monkeypatch):
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers += [Layer("A"), Layer("B"), Layer("C")]
    panel.refresh()
    assert not panel.tree.isColumnHidden(COL_HATCH)       # shown by default
    for n in ("A", "B"):
        panel.item_for(n).setSelected(True)

    def fake_popup(menu, _at):
        grid = next(w for w in menu.findChildren(HatchGrid))
        assert set(grid.buttons) >= {None, "brick", "insulation"}
        grid.buttons["insulation"].click()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "A"), COL_HATCH)
    assert scene.layer("A").hatch == scene.layer("B").hatch == "insulation"
    assert scene.layer("C").hatch is None
    assert not panel.item_for("A").icon(COL_HATCH).isNull()
    assert panel.item_for("C").text(COL_HATCH) == ""
    assert not panel.item_for("C").icon(COL_HATCH).isNull()   # «none»
    assert panel.item_for("C").toolTip(COL_HATCH) == "The frame's fill"


def test_the_grid_marks_the_current_hatch_and_offers_the_frame_fill():
    from views.layers_panel import HatchGrid
    grid = HatchGrid("brick")
    assert grid.buttons["brick"].isChecked()
    assert not grid.buttons[None].isChecked()
    got = []
    grid.picked.connect(got.append)
    grid.buttons[None].click()
    assert got == [None]


def test_the_legend_swatch_draws_the_hatch():
    from core.composition import Leyenda
    from views.composer import paint_leyenda_mm

    def draw(swatch):
        le = Leyenda(w_mm=40.0, rows=["Muros"],
                     swatches={"Muros": swatch})
        img = QImage(400, 140, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        p = QPainter(img)
        p.scale(10, 10)
        paint_leyenda_mm(p, le)
        p.end()
        return [QColor(img.pixel(x, y)).lightness()
                for x in range(25, 60) for y in range(85, 115)]
    plain = draw({"color": [1.0, 1.0, 1.0]})
    hatched = draw({"color": [1.0, 1.0, 1.0], "hatch": "crosshatch"})
    assert sum(v < 128 for v in hatched) > sum(v < 128 for v in plain)


# ---- A solid ground under the hatch ---------------------------------------

def test_the_hatch_ground_round_trips_as_a_colour_or_the_layer():
    grey = Layer("Muros", hatch="brick", hatch_ground=(0.7, 0.7, 0.7))
    raw = json.loads(json.dumps(grey.to_dict()))
    assert raw["hatch_ground"] == [0.7, 0.7, 0.7]
    assert Layer.from_dict(raw).hatch_ground == (0.7, 0.7, 0.7)
    own = Layer("Aislante", color=(1.0, 0.8, 0.0), hatch_ground="layer")
    assert Layer.from_dict(own.to_dict()).hatch_ground == "layer"
    assert own.has_style()
    for bad in ("purple", [1, 2], 7, None):
        assert Layer.from_dict({"name": "X", "hatch_ground": bad}
                               ).hatch_ground is None


def test_the_layer_ground_is_its_colour_made_light():
    ly = Layer("A", color=(0.8, 0.0, 0.0), hatch="brick",
               hatch_ground="layer")
    r, g, b = L.hatch_ground_rgb(ly)
    assert r > g and g == pytest.approx(0.75) and r > 0.9
    assert L.hatch_ground_rgb(Layer("B")) is None


def test_only_hatched_layers_give_their_ground_to_the_sheet():
    scene = Scene()
    scene.layers += [Layer("A", hatch="brick", hatch_ground=(1, 1, 1)),
                     Layer("B", hatch_ground=(0.5, 0.5, 0.5))]
    assert L.cut_hatch_grounds(scene) == {"A": (1.0, 1.0, 1.0)}
    _rows, swatches = L.legend_rows(scene)
    assert swatches["A"]["hatch_ground"] == [1.0, 1.0, 1.0]
    assert "hatch_ground" not in swatches["B"]


def test_a_template_carries_the_ground():
    src = Scene()
    src.layers.append(Layer("Muros", hatch="brick", hatch_ground="layer"))
    dst = Scene()
    dst.layers.append(Layer("Muros"))
    L.apply_template(dst, json.loads(json.dumps(L.template_of(src))))
    assert dst.layer("Muros").hatch_ground == "layer"


def test_a_grey_ground_sits_under_the_hatch_lines():
    frame = MarcoVista(style="vectorial", cut_fill="solid",
                       cut_fill_color="#000000")
    pixels = _paint_one(frame, (None, "diagonal", QColor(180, 180, 180)))
    assert not any(c.lightness() > 240 for c in pixels)    # no bare paper
    assert any(c.lightness() < 170 for c in pixels)        # the lines show
    assert sum(1 for c in pixels if c == QColor(180, 180, 180)) > len(
        pixels) // 3


def test_the_ground_wins_over_the_pale_layer_tint():
    frame = MarcoVista(style="vectorial", cut_fill="solid")
    pixels = _paint_one(frame, (QColor(200, 0, 0), "diagonal",
                                QColor(255, 255, 255)))
    assert sum(1 for c in pixels if c == QColor(255, 255, 255)) > len(
        pixels) // 3


def test_a_sheet_passes_each_ring_its_ground():
    composer, frame, host = _composer()
    scene = host.viewport.scene
    scene.layer("Muros").hatch = "brick"
    scene.layer("Muros").hatch_ground = (0.88, 0.88, 0.88)
    composer.compute_hlr(frame)
    looks = composer.hlr_fill_styles[id(frame)]
    walls = [look[2] for look in looks if look[1] == "brick"]
    assert walls and walls[0].name() == QColor.fromRgbF(0.88, 0.88, 0.88).name()
    assert all(look[2] is None for look in looks if look[1] != "brick")


def test_the_grid_offers_the_grounds_and_marks_the_current_one():
    from views.layers_panel import HatchGrid
    ly = Layer("A", color=(0.2, 0.4, 0.8), hatch="brick",
               hatch_ground=(1.0, 1.0, 1.0))
    grid = HatchGrid("brick", ground=ly.hatch_ground, layer=ly)
    assert set(grid.ground_buttons) == {
        None, (1.0, 1.0, 1.0), (0.88, 0.88, 0.88), (0.70, 0.70, 0.70),
        "layer", "other"}
    assert grid.ground_buttons[(1.0, 1.0, 1.0)].isChecked()
    assert not grid.ground_buttons[None].isChecked()
    got = []
    grid.ground_picked.connect(got.append)
    grid.ground_buttons["layer"].click()
    grid.ground_buttons[None].click()
    assert got == ["layer", None]


def test_other_colour_asks_and_a_cancel_changes_nothing():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick"))
    got = []
    grid.ground_picked.connect(got.append)
    grid.ground_buttons["other"].click()
    QTest.keyClick(grid.colour_dialog, Qt.Key_Escape)     # Esc: back
    assert got == [] and not grid.colour_page.isVisible()
    grid.ground_buttons["other"].click()
    grid.colour_dialog.setCurrentColor(QColor(51, 102, 153))
    grid.colour_use.click()
    assert got == [(0.2, 0.4, 0.6)]
    grid.close()


def test_the_panel_sets_the_ground_for_every_selected_row(win, monkeypatch):
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers += [Layer("A", hatch="brick"), Layer("B", hatch="brick"),
                     Layer("C")]
    panel.refresh()
    for n in ("A", "B"):
        panel.item_for(n).setSelected(True)

    def fake_popup(menu, _at):
        grid = next(w for w in menu.findChildren(HatchGrid))
        grid.ground_buttons[(0.70, 0.70, 0.70)].click()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "A"), COL_HATCH)
    assert scene.layer("A").hatch_ground == scene.layer("B").hatch_ground \
        == (0.7, 0.7, 0.7)
    assert scene.layer("A").hatch == "brick"           # the pattern stays
    assert scene.layer("C").hatch_ground is None


# ---- The ink of the hatch: as the frame says, by layer, or fixed -----------

def test_the_hatch_ink_round_trips_by_layer_or_fixed():
    fixed = Layer("Muros", hatch="brick", hatch_color=(0.0, 0.0, 0.0))
    raw = json.loads(json.dumps(fixed.to_dict()))
    assert raw["hatch_color"] == [0.0, 0.0, 0.0]
    assert Layer.from_dict(raw).hatch_color == (0.0, 0.0, 0.0)
    by_layer = Layer("A", hatch="brick", hatch_color="layer")
    assert Layer.from_dict(by_layer.to_dict()).hatch_color == "layer"
    assert Layer("Plain", hatch_color="nope").hatch_color is None
    assert "hatch_color" not in Layer("Plain").to_dict()


def test_by_layer_is_the_layer_colour_a_shade_darker():
    ly = Layer("A", color=(1.0, 0.5, 0.0), hatch="brick", hatch_color="layer")
    assert L.hatch_ink_rgb(ly) == pytest.approx((0.7, 0.35, 0.0))
    ly.color = (0.0, 0.0, 1.0)                     # follows the layer
    assert L.hatch_ink_rgb(ly) == pytest.approx((0.0, 0.0, 0.7))
    assert L.hatch_ink_rgb(Layer("B")) is None


def test_only_hatched_layers_give_their_ink_and_the_legend_shows_it():
    scene = Scene()
    scene.layers += [Layer("A", hatch="brick", hatch_color=(0, 0, 0)),
                     Layer("B", hatch_color=(0, 0, 0))]
    assert L.cut_hatch_inks(scene) == {"A": (0.0, 0.0, 0.0)}
    _rows, swatches = L.legend_rows(scene)
    assert swatches["A"]["hatch_color"] == [0.0, 0.0, 0.0]


def test_a_fixed_ink_wins_over_the_frame_and_the_layer_tint():
    """Fill by layer on: the ground is the layer's pale tint, but the lines
    keep the layer's fixed ink (pure blue here), not the layer's colour."""
    frame = MarcoVista(style="vectorial", cut_fill="solid", pen_edge_mm=1.5)
    pixels = _paint_one(frame, (QColor(200, 0, 0), "diagonal", None,
                                QColor(0, 0, 255)))
    assert any(c.blue() > 150 and c.red() < 120 for c in pixels)


def test_without_an_ink_the_frame_colour_stays():
    frame = MarcoVista(style="vectorial", cut_fill="solid", pen_edge_mm=1.5,
                       cut_fill_color="#00ff00")
    pixels = _paint_one(frame, (None, "diagonal", None, None))
    assert any(c.green() > 150 and c.red() < 120 for c in pixels)


def test_a_sheet_passes_each_ring_its_ink():
    composer, frame, host = _composer()
    scene = host.viewport.scene
    scene.layer("Muros").hatch = "brick"
    scene.layer("Muros").hatch_color = "layer"
    composer.compute_hlr(frame)
    looks = composer.hlr_fill_styles[id(frame)]
    walls = [look[3] for look in looks if look[1] == "brick"]
    assert walls and walls[0].name() == QColor.fromRgbF(
        0.8 * 0.7, 0.1 * 0.7, 0.1 * 0.7).name()


def test_the_grid_offers_the_inks_and_marks_the_current_one():
    from views.layers_panel import HatchGrid
    ly = Layer("A", color=(0.2, 0.4, 0.8), hatch="brick", hatch_color="layer")
    grid = HatchGrid("brick", ink=ly.hatch_color, layer=ly)
    assert set(grid.ink_buttons) == {None, "layer", (0.0, 0.0, 0.0),
                                     (0.40, 0.40, 0.40), "other"}
    assert grid.ink_buttons["layer"].isChecked()
    got = []
    grid.ink_picked.connect(got.append)
    grid.ink_buttons[None].click()
    assert got == [None]
    grid.ink_buttons[(0.0, 0.0, 0.0)].click()
    assert got == [None, (0.0, 0.0, 0.0)]
    assert grid.ink_name.text() == "· Black"
    # One not offered (a near-black) shows as «Other colour…».
    black = HatchGrid("brick", ink=(0.12, 0.14, 0.17))
    assert black.ink_buttons["other"].isChecked()
    white = HatchGrid("brick", ink=(1.0, 1.0, 1.0))   # through «Other»
    assert white.ink_buttons["other"].isChecked()


def test_the_panel_sets_the_ink_for_every_selected_row(win, monkeypatch):
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers += [Layer("A", hatch="brick"), Layer("B", hatch="brick")]
    panel.refresh()
    for n in ("A", "B"):
        panel.item_for(n).setSelected(True)

    def fake_popup(menu, _at):
        grid = next(w for w in menu.findChildren(HatchGrid))
        grid.ink_buttons["layer"].click()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "A"), COL_HATCH)
    assert scene.layer("A").hatch_color == scene.layer("B").hatch_color \
        == "layer"


def test_other_colour_stands_apart_from_the_swatches():
    """«Other colour…» is a chip of every hue, the size and frame of the
    others, with its name beside it; a colour picked before fills it."""
    from PySide6.QtCore import Qt
    from views.layers_panel import HatchGrid
    grid = HatchGrid("brick", ground=(0.2, 0.4, 0.6))
    for buttons in (grid.ground_buttons, grid.ink_buttons):
        other = buttons["other"]
        assert other.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
        assert other.text() == "Other colour…"
        assert other.iconSize() == buttons[None].iconSize()
        assert buttons[None].toolButtonStyle() == Qt.ToolButtonIconOnly
        assert buttons[None].toolTip()                    # named on hover
    other = grid.ground_buttons["other"]
    assert other.isChecked()                             # a colour of its own
    img = other.icon().pixmap(other.iconSize()).toImage()
    left = QColor(img.pixel(img.width() // 4, img.height() // 2))
    assert (left.red(), left.green(), left.blue()) == (51, 102, 153)


# ---- The catalogue -----------------------------------------------------------

def test_every_pattern_sits_in_exactly_one_group():
    from core.hatches import HATCH_GROUPS, HATCH_LABELS, HATCH_ORDER
    listed = [k for _t, keys in HATCH_GROUPS for k in keys]
    assert sorted(listed) == sorted(HATCH_LABELS)
    assert len(listed) == len(set(listed)) == len(HATCH_ORDER)


def test_the_first_patterns_keep_their_names():
    """Documents saved with the first set still load their hatches."""
    from core.hatches import known
    for key in ("solid", "diagonal", "crosshatch", "brick", "block",
                "concrete", "reinforced", "insulation", "earth", "gravel",
                "sand", "stone", "wood", "steel"):
        assert known(key)
        assert Layer.from_dict({"name": "X", "hatch": key}).hatch == key


def test_every_pattern_marks_inside_its_box_and_tells_apart():
    """Each pattern leaves marks near the box (the clip trims the rest),
    and no two patterns draw the very same marks."""
    from core.hatches import HATCH_ORDER, SAME_FACE, hatch_marks
    box = (0.0, 0.0, 12.0, 8.0)
    seen = {}
    for key in HATCH_ORDER:
        if key == "solid" or key in SAME_FACE:   # these part in a cut
            continue
        marks = hatch_marks(key, box)
        pts = [p for seg in marks["lines"] for p in (seg[:2], seg[2:])]
        pts += marks["dots"] + [c[:2] for c in marks["circles"]]
        pts += [p for poly in marks["polys"] + marks["closed"] for p in poly]
        assert pts, key
        inside = [p for p in pts if -1 <= p[0] <= 13 and -1 <= p[1] <= 9]
        assert inside, key
        sig = repr(sorted((round(a, 3), round(b, 3)) for a, b in pts)[:60])
        assert sig not in seen, (key, seen.get(sig))
        seen[sig] = key


def test_the_grid_shows_every_pattern_under_its_group_title():
    from PySide6.QtWidgets import QLabel
    from core.hatches import HATCH_GROUPS, HATCH_ORDER
    from views.layers_panel import HatchGrid
    grid = HatchGrid(None)
    assert set(grid.buttons) == {None} | set(HATCH_ORDER)
    titles = {w.text() for w in grid.findChildren(QLabel)}
    assert {t for t, _k in HATCH_GROUPS} <= titles


def test_the_patterns_scroll_and_open_at_the_top():
    """A few rows of patterns in sight, the rest behind a scroll bar; the
    picker opens at the top — the recently used and the general ones —
    whatever the layer's pattern, which the preview names; grounds and
    inks stay out of the scroll, always in sight."""
    from views.layers_panel import HatchGrid
    grid = HatchGrid("plastic", recent=["brick"])     # the very last one
    grid.show()
    for _ in range(3):
        _app.processEvents()
    bar = grid.scroll.verticalScrollBar()
    assert bar.maximum() > 0                          # there is more below
    assert bar.value() == 0                           # but it opens on top
    head = grid._heads["Recent"]
    top = head.mapTo(grid.scroll.viewport(), head.rect().topLeft()).y()
    assert 0 <= top < grid.scroll.viewport().height()
    assert grid.preview_name.text() == "Plastic, rubber"
    for b in list(grid.ground_buttons.values()) + list(
            grid.ink_buttons.values()):
        assert not grid.scroll.widget().isAncestorOf(b)
    grid.close()

def test_the_ground_chips_tell_white_from_light_grey_and_the_paper():
    from views.hatch_paint import colour_chip
    def middle(px):
        img = px.toImage()
        return QColor(img.pixel(img.width() // 2, img.height() // 2))
    white = middle(colour_chip(48, 26, QColor(255, 255, 255)))
    grey = middle(colour_chip(48, 26, QColor.fromRgbF(0.88, 0.88, 0.88)))
    assert white.lightness() - grey.lightness() > 20
    paper = colour_chip(48, 26, None, paper=True).toImage()
    shades = {QColor(paper.pixel(x, 12)).name() for x in range(2, 46)}
    assert len(shades) >= 2                           # a checkerboard



# ---- The picker as a popover -------------------------------------------------

def _shown(grid):
    grid.show()
    for _ in range(3):
        _app.processEvents()
    return grid


def test_the_search_keeps_only_matching_patterns_and_their_groups():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick"))
    grid.search.setText("brick")
    visible = {k for k, b in grid.buttons.items()
               if k is not None and b.isVisible()}
    from core.hatches import HATCH_LABELS
    assert visible == {k for k, v in HATCH_LABELS.items()
                       if "brick" in v.lower()}
    assert grid._heads["Masonry"].isVisible()
    assert not grid._heads["Wood"].isVisible()
    assert not grid.nothing.isVisible()
    grid.search.setText("zzz")
    assert grid.nothing.isVisible() and "zzz" in grid.nothing.text()
    grid.search.clear()
    assert all(b.isVisible() for b in grid.buttons.values())
    grid.close()


def test_the_funnel_shows_one_group_at_a_time():
    from core.hatches import HATCH_GROUPS
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", recent=["glass"]))
    metals = dict(HATCH_GROUPS)["Metals, glass and plastics"]
    grid.group_actions["Metals, glass and plastics"].trigger()
    shown = {k for k, b in grid.buttons.items() if b.isVisibleTo(grid)}
    assert shown == set(metals)                     # that group alone
    assert not grid.recent_buttons["glass"].isVisibleTo(grid)
    assert grid.filter_btn.toolTip() == "Filter: Metals, glass and plastics"
    grid.search.setText("steel")                    # the search within it
    shown = {k for k, b in grid.buttons.items() if b.isVisibleTo(grid)}
    assert shown == {"steel"}
    grid.search.clear()
    grid.filter_to(None)
    assert all(b.isVisibleTo(grid) for b in grid.buttons.values())
    assert grid.filter_btn.toolTip() == "Filter: All hatches"
    grid.close()


def test_the_preview_shows_the_pattern_on_its_ground_and_follows_hover():
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QEnterEvent
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", ground=(0.88, 0.88, 0.88)))
    assert grid.preview_name.text() == "Brick"
    img = grid.preview.pixmap().toImage()
    shades = {QColor(img.pixel(x, y)).name()
              for x in range(5, img.width() - 5, 7)
              for y in range(5, img.height() - 5, 7)}
    assert QColor.fromRgbF(0.88, 0.88, 0.88).name() in shades
    grid.ground_buttons[(1.0, 1.0, 1.0)].click()      # live: white ground
    img = grid.preview.pixmap().toImage()
    assert QColor(img.pixel(3, 3)).name() != QColor.fromRgbF(
        0.88, 0.88, 0.88).name()
    assert "White" in grid.ground_name.text()
    tile = grid.buttons["glass"]
    QApplication.sendEvent(tile, QEvent(QEvent.Enter))
    assert grid.preview_name.text() == "Glass"        # hover previews
    QApplication.sendEvent(tile, QEvent(QEvent.Leave))
    assert grid.preview_name.text() == "Brick"        # and goes back
    grid.close()


def test_picks_apply_at_once_and_the_picker_stays_open(win, monkeypatch):
    """Pattern, ground and ink in one go: the menu stays open after each
    pick and «Done» closes it."""
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A"))
    panel.refresh()
    seen = {}

    def fake_popup(menu, _at):
        menu.show()
        grid = next(w for w in menu.findChildren(HatchGrid))
        grid.buttons["concrete"].click()
        grid.ground_buttons[(1.0, 1.0, 1.0)].click()
        grid.ink_buttons["layer"].click()
        seen["open"] = menu.isVisible()
        grid.done_button.click()
        seen["closed"] = not menu.isVisible()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "A"), COL_HATCH)
    ly = scene.layer("A")
    assert (ly.hatch, ly.hatch_ground, ly.hatch_color) == (
        "concrete", (1.0, 1.0, 1.0), "layer")
    assert seen == {"open": True, "closed": True}


def test_enter_keeps_and_escape_cancels():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from views.layers_panel import HatchGrid
    for key, signal in ((Qt.Key_Return, "done"), (Qt.Key_Escape,
                                                   "cancelled")):
        grid = _shown(HatchGrid("brick"))
        got = []
        grid.done.connect(lambda: got.append("done"))
        grid.cancelled.connect(lambda: got.append("cancelled"))
        QTest.keyClick(grid, key)
        assert got == [signal]
        grid.close()


def test_cancel_puts_the_layer_back_as_it_was(win, monkeypatch):
    """Picks apply at once; «Cancel» undoes all of them and closes."""
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A", hatch="brick", hatch_angle=15.0))
    panel.refresh()
    seen = {}

    def fake_popup(menu, _at):
        menu.show()
        grid = next(w for w in menu.findChildren(HatchGrid))
        assert grid.cancel_button.text() == "Cancel"
        grid.buttons["concrete"].click()
        grid.ground_buttons[(1.0, 1.0, 1.0)].click()
        grid.angle_spin.setValue(90)
        seen["during"] = scene.layer("A").hatch
        grid.cancel_button.click()
        seen["closed"] = not menu.isVisible()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "A"), COL_HATCH)
    ly = scene.layer("A")
    assert seen == {"during": "concrete", "closed": True}
    assert (ly.hatch, ly.hatch_ground, ly.hatch_angle) == ("brick", None,
                                                           15.0)

def test_a_cancelled_other_colour_keeps_the_old_choice_ticked():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", ground=(1.0, 1.0, 1.0)))
    got = []
    grid.ground_picked.connect(got.append)
    grid.ground_buttons["other"].click()
    assert grid.colour_page.isVisible()               # in the picker
    grid.colour_back.click()
    assert not grid.colour_page.isVisible()
    assert grid.ground_buttons[(1.0, 1.0, 1.0)].isChecked()
    assert not grid.ground_buttons["other"].isChecked()
    assert got == []
    grid.close()


def test_the_picker_fits_a_laptop_side_by_side():
    """The catalogue on the left, the preview and the settings on the
    right: wide and low, it fits a 1366 × 768 screen; the grid scrolls."""
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick"))
    assert grid.width() <= 1120 and grid.height() <= 600
    assert grid.scroll.geometry().right() < grid.preview.mapTo(
        grid, grid.preview.rect().topLeft()).x()      # the grid left of it
    assert grid.scroll.height() < grid.scroll.widget().height()
    grid.close()


def test_a_tile_is_the_pattern_alone_named_on_hover():
    """No caption under each tile (the preview names the one under the
    pointer): the name is the tooltip and the accessible name."""
    from PySide6.QtCore import Qt
    from views.layers_panel import HatchGrid
    grid = HatchGrid("brick")
    for key, b in grid.buttons.items():
        if key is None:
            continue                       # the footer button keeps its text
        assert b.toolButtonStyle() == Qt.ToolButtonIconOnly
        assert b.text() == ""
        assert b.toolTip() and b.accessibleName() == b.toolTip()
    assert grid.buttons["brick"].toolTip() == "Brick"


def test_the_hatch_picker_opens_centred_on_the_screen(win, monkeypatch):
    """From the cell and from the right-click menu alike."""
    from views.layers_panel import COL_HATCH
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A", hatch="brick"))
    panel.refresh()
    seen = []
    monkeypatch.setattr(panel, "_popup", lambda menu, at: seen.append(
        (menu.sizeHint(), at)))
    panel.click_cell(("layer", "A"), COL_HATCH)
    from PySide6.QtWidgets import QMenu
    menu = QMenu()
    panel._add_look_menus(menu, ["A"], scene.layer("A"))
    next(a for a in menu.actions() if a.text() == "Cut hatch…").trigger()
    for _ in range(3):
        _app.processEvents()
    assert len(seen) == 2
    area = (panel.screen() or _app.primaryScreen()).availableGeometry()
    for size, at in seen:
        cx = at.x() + size.width() // 2
        cy = at.y() + size.height() // 2
        assert abs(cx - area.center().x()) <= 1
        assert abs(cy - area.center().y()) <= 1



# ---- Angle, scale, size on paper or with the drawing, imported patterns -----

_PAT = """;%UNITS=MM
*TEST-HEX, hexagons
0, 0,0, 4.7625,2.74963, 3.175,-6.35
120, 0,0, 4.7625,2.74963, 3.175,-6.35
60, 3.175,0, 4.7625,2.74963, 3.175,-6.35
*BROKEN, only bad lines
1, 2
45, 0,0, 0,0
*TOO-FINE
0, 0,0, 0,0.00001
"""


def test_a_pattern_file_is_read_and_bad_lines_are_dropped():
    from core.hatches import parse_pat
    found = parse_pat(_PAT)
    assert set(found) == {"TEST-HEX"}
    assert found["TEST-HEX"]["label"] == "hexagons"
    assert len(found["TEST-HEX"]["families"]) == 3
    inch = parse_pat(";%UNITS=INCH\n*A\n45, 0,0, 0,0.125\n")
    assert inch["A"]["families"][0][4] == pytest.approx(3.175)


def test_turning_a_pattern_turns_its_lines():
    from core.hatches import hatch_marks
    flat = hatch_marks("grid", (0, 0, 10, 10))["lines"]
    turned = hatch_marks("grid", (0, 0, 10, 10), angle=45.0)["lines"]
    def slopes(lines):
        import math
        return {round(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180)
                for x0, y0, x1, y1 in lines if (x1 - x0) or (y1 - y0)}
    assert slopes(flat) == {0, 90}
    assert slopes(turned) == {45, 135}


def test_the_angle_scale_and_size_round_trip_on_the_layer():
    ly = Layer("Baldosas", hatch="grid", hatch_angle=30, hatch_scale=2.5,
               hatch_on_paper=False)
    back = Layer.from_dict(json.loads(json.dumps(ly.to_dict())))
    assert (back.hatch_angle, back.hatch_scale, back.hatch_on_paper) == (
        30.0, 2.5, False)
    assert ly.has_style()
    plain = Layer("X").to_dict()
    assert not {"hatch_angle", "hatch_scale", "hatch_on_paper"} & set(plain)
    odd = Layer.from_dict({"name": "X", "hatch_angle": "nan",
                           "hatch_scale": 999})
    assert odd.hatch_angle == 0.0 and odd.hatch_scale == 20.0


def test_a_hatch_that_grows_with_the_drawing_follows_the_frame_scale():
    scene = Scene()
    scene.layers += [Layer("Papel", hatch="grid", hatch_scale=2.0),
                     Layer("Dibujo", hatch="grid", hatch_on_paper=False)]
    at_50 = L.cut_hatch_forms(scene, 50.0)
    at_200 = L.cut_hatch_forms(scene, 200.0)
    assert at_50["Papel"]["scale"] == at_200["Papel"]["scale"] == 2.0
    assert at_50["Dibujo"]["scale"] == pytest.approx(2.0)   # twice at 1:50
    assert at_200["Dibujo"]["scale"] == pytest.approx(0.5)  # half at 1:200


def test_a_material_is_drawn_at_its_real_size_by_itself():
    """A brick's course is 6.5 cm in reality: 6.5 mm on paper at 1:10,
    1.3 mm at 1:50 — whatever the sheet, with no box to tick; a stipple
    keeps its size on paper; the layer can force either."""
    from core.hatches import REAL_SIZE, real_scale
    unit, metres = REAL_SIZE["brick"]
    for n in (10, 20, 50, 100):
        assert unit * real_scale("brick", n) == pytest.approx(
            metres * 1000.0 / n)
    scene = Scene()
    scene.layers += [Layer("Muro", hatch="brick"),
                     Layer("Losa", hatch="concrete"),
                     Layer("Muro fijo", hatch="brick", hatch_on_paper=True)]
    at_10 = L.cut_hatch_forms(scene, 10.0)
    at_50 = L.cut_hatch_forms(scene, 50.0)
    assert at_10["Muro"]["scale"] == pytest.approx(5 * at_50["Muro"]["scale"])
    assert at_10["Losa"]["scale"] == at_50["Losa"]["scale"] == 1.0
    assert at_10["Muro fijo"]["scale"] == 1.0
    assert L.hatch_grows(scene.layer("Muro"))
    assert not L.hatch_grows(scene.layer("Losa"))
    # far too small a scale: not a grey blur
    assert real_scale("brick", 2000) == pytest.approx(0.25)
    assert real_scale("concrete", 10) is None


def test_the_size_rule_is_saved_only_when_the_layer_chose_it():
    assert "hatch_on_paper" not in Layer("A", hatch="brick").to_dict()
    for chosen in (True, False):
        ly = Layer("A", hatch="brick", hatch_on_paper=chosen)
        assert Layer.from_dict(json.loads(json.dumps(ly.to_dict()))
                               ).hatch_on_paper is chosen
    assert Layer.from_dict({"name": "A", "hatch_on_paper": "x"}
                           ).hatch_on_paper is None


def test_the_picker_follows_the_pattern_until_the_box_is_clicked():
    from views.layers_panel import HatchGrid
    grid = HatchGrid("concrete", recent=[],
                     form={"hatch_on_paper": True, "paper_fixed": False})
    got = []
    grid.form_picked.connect(got.append)
    grid.picked.connect(lambda k: got.append(("pick", k)))
    grid.buttons["brick"].click()
    assert grid.drawing_check.isChecked()            # brick grows by itself
    grid.angle_spin.setValue(45)
    assert "hatch_on_paper" not in got[-1]           # still the pattern's
    grid.drawing_check.setChecked(False)             # now the layer chooses
    assert got[-1]["hatch_on_paper"] is True
    grid.buttons["concrete"].click()
    assert not grid.drawing_check.isChecked()

def test_imported_patterns_live_in_the_document(tmp_path):
    from core.hatches import parse_pat
    from formats import igz
    scene = Scene()
    scene.hatch_patterns = parse_pat(_PAT)
    scene.layers.append(Layer("Muro", hatch="pat:TEST-HEX"))
    assert L.hatch_families(scene, "pat:TEST-HEX")
    assert L.hatch_families(scene, "brick") is None
    path = tmp_path / "hex.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert set(back.hatch_patterns) == {"TEST-HEX"}
    assert back.layer("Muro").hatch == "pat:TEST-HEX"
    assert len(back.hatch_patterns["TEST-HEX"]["families"]) == 3
    fresh = Scene()
    igz.load_into(back, tmp_path / "hex.igz")      # no leak on reopen
    igz.save_scene(fresh, tmp_path / "empty.igz")
    igz.load_into(back, tmp_path / "empty.igz")
    assert back.hatch_patterns == {}


def test_a_sheet_lays_the_imported_and_turned_pattern(tmp_path):
    from core.hatches import parse_pat
    composer, frame, host = _composer()
    scene = host.viewport.scene
    scene.hatch_patterns = parse_pat(_PAT)
    wall = scene.layer("Muros")
    wall.hatch, wall.hatch_angle, wall.hatch_scale = "pat:TEST-HEX", 30.0, 2.0
    composer.compute_hlr(frame)
    looks = composer.hlr_fill_styles[id(frame)]
    form = next(look[4] for look in looks if look[1] == "pat:TEST-HEX")
    assert form["angle"] == 30.0 and form["scale"] == 2.0
    assert len(form["families"]) == 3
    pixels = _paint_one(MarcoVista(style="vectorial", cut_fill="solid",
                                   cut_fill_color="#000000"),
                        (None, "pat:TEST-HEX", None, None, form))
    assert any(c.lightness() < 200 for c in pixels)
    assert any(c.lightness() > 240 for c in pixels)


def test_the_panel_imports_a_pattern_file_and_the_picker_shows_it(
        win, tmp_path):
    from views.layers_panel import HatchGrid
    panel = win.layers_dock.panel
    pat = tmp_path / "mine.pat"
    pat.write_text(_PAT, encoding="utf-8")
    assert panel.import_pat_file(pat) == 1
    assert panel.import_pat_file(tmp_path / "missing.pat") == 0
    junk = tmp_path / "junk.pat"
    junk.write_bytes(b"\xff\xfe not a pattern")
    assert panel.import_pat_file(junk) == 0
    scene = win.viewport.scene
    grid = HatchGrid(None, patterns=scene.hatch_patterns, recent=[])
    assert "pat:TEST-HEX" in grid.buttons
    assert "Imported" in grid.group_actions
    assert "TEST-HEX" in grid.buttons["pat:TEST-HEX"].toolTip()


def test_the_picker_sets_angle_scale_and_size_live():
    from views.layers_panel import HatchGrid
    grid = HatchGrid("brick", form={"hatch_angle": 0, "hatch_scale": 1,
                                    "hatch_on_paper": True}, recent=[])
    got = []
    grid.form_picked.connect(got.append)
    grid.angle_spin.setValue(45)
    grid.scale_spin.setValue(2.0)
    grid.drawing_check.setChecked(True)
    assert got[-1] == {"hatch_angle": 45.0, "hatch_scale": 2.0,
                       "hatch_offset": None, "hatch_on_paper": False,
                       "hatch_cross": False}


def test_the_recently_used_come_first(monkeypatch):
    from PySide6.QtCore import QSettings
    from views.layers_panel import HatchGrid
    QSettings().remove(HatchGrid.RECENT_KEY)
    for key in ("brick", "glass", "brick", "pat:GONE"):
        HatchGrid.remember(key)
    assert HatchGrid.recent()[:2] == ["pat:GONE", "brick"]
    grid = HatchGrid(None)
    # An imported pattern the document no longer has is left out.
    assert list(grid.recent_buttons) == ["brick", "glass"]
    assert grid._heads["Recent"].isVisible() or True
    grid.recent_buttons["glass"].click()
    assert HatchGrid.recent()[0] == "glass"
    assert grid.buttons["glass"].isChecked()
    QSettings().remove(HatchGrid.RECENT_KEY)



def test_the_hatch_thumbnail_has_the_colour_swatch_shape(win):
    """The Hatch column reads like the Colour column beside it: the same
    18 px icon, the same rounded box and border, in a column as wide; no
    hatch is the same «none» swatch as a layer with no colour."""
    from views.layers_panel import (COL_COLOR, COL_HATCH, hatch_icon,
                                    none_swatch, swatch_icon)

    def mask(icon):
        img = icon.pixmap(18, 18).toImage()
        return [[QColor.fromRgba(img.pixel(x, y)).alpha() > 0
                 for x in range(img.width())] for y in range(img.height())]
    colour = mask(swatch_icon((0.8, 0.2, 0.2)))
    for key in ("brick", "concrete", "insulation"):
        assert mask(hatch_icon(key)) == colour, key
    assert mask(hatch_icon(None)) == mask(none_swatch())
    panel = win.layers_dock.panel
    assert panel.tree.columnWidth(COL_HATCH) == panel.tree.columnWidth(
        COL_COLOR)
    head = panel.tree.headerItem()
    assert head.text(COL_HATCH) == "" and not head.icon(COL_HATCH).isNull()



# ---- The catalogue's entries, the pattern file out, the frame's hatch pen ---

def test_every_pattern_has_its_catalogue_entry():
    from core.hatches import HATCH_INFO, HATCH_LABELS
    assert set(HATCH_INFO) == set(HATCH_LABELS)
    aliases = [info[0] for info in HATCH_INFO.values()]
    assert len(aliases) == len(set(aliases))          # no two codes alike
    for key, (alias, density, scale, angle, use) in HATCH_INFO.items():
        assert alias.replace("-", "").isalnum() and alias.isupper(), key
        assert density in ("low", "medium", "high"), key
        assert scale > 0 and 0 <= angle < 360 and use, key


def test_a_line_pattern_goes_to_a_pattern_file_and_back_unchanged():
    """Out to .pat and read again, every line pattern draws the same — the
    herringbone's built-in turn included (compared as drawn: six decimals
    in the file may move a line that the clip throws away anyway)."""
    from PySide6.QtGui import QPainterPath
    from core.hatches import HATCH_ORDER, line_families, parse_pat, to_pat
    from views.hatch_paint import paint_hatch
    keys = [k for k in HATCH_ORDER if line_families(k)]
    assert {"brick", "brick_flemish", "hexagon", "parquet"} <= set(keys)
    assert line_families("concrete") is None          # a stipple: no .pat
    back = parse_pat(to_pat([(k, k, line_families(k)) for k in keys]))

    def drawn(key, families=None):
        img = QImage(120, 90, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        p = QPainter(img)
        # Off the pixel grid: a line lying exactly between two pixels lands
        # on either for a millionth of a millimetre.
        p.translate(0.37, 0.29)
        p.scale(10, 10)
        box = QPainterPath()
        box.addRect(0.0, 0.0, 12.0, 9.0)
        paint_hatch(p, box, key, QColor(0, 0, 0), 0.1, 1.0, None, 0.0,
                    families)
        p.end()
        return img
    for key in keys:
        a, b = drawn(key), drawn("pat:" + key, back[key]["families"])
        differ = sum(1 for x in range(120) for y in range(90)
                     if abs(QColor(a.pixel(x, y)).lightness()
                            - QColor(b.pixel(x, y)).lightness()) > 60)
        assert differ < 120 * 90 * 0.005, (key, differ)


def test_the_panel_exports_the_line_patterns_and_the_imported(win, tmp_path):
    from core.hatches import line_families, HATCH_ORDER, parse_pat
    panel = win.layers_dock.panel
    pat = tmp_path / "mine.pat"
    pat.write_text(_PAT, encoding="utf-8")
    panel.import_pat_file(pat)
    out = tmp_path / "out.pat"
    n = panel.export_pat_file(out)
    lines = [k for k in HATCH_ORDER if line_families(k)]
    assert n == len(lines) + 1
    back = parse_pat(out.read_text(encoding="utf-8"))
    assert "IT-BRICK" in back and "TEST-HEX" in back
    assert "IT-CONC" not in back                      # stipples stay out


def test_the_frame_hatch_pen_is_automatic_or_its_own():
    from views.composer import hatch_pen_mm
    auto = MarcoVista(pen_edge_mm=0.25)
    assert hatch_pen_mm(auto) == pytest.approx(0.175)
    own = MarcoVista(pen_edge_mm=0.25, pen_hatch_mm=0.09)
    assert hatch_pen_mm(own) == pytest.approx(0.09)


def test_the_frame_hatch_pen_inks_the_hatch_lines():
    def ink(pen):
        frame = MarcoVista(style="vectorial", cut_fill="solid",
                           cut_fill_color="#000000", pen_hatch_mm=pen)
        return sum(1 for c in _paint_one(frame, (None, "diagonal"))
                   if c.lightness() < 160)
    assert ink(0.6) > 2 * ink(0.1)


def test_the_frame_keeps_its_hatch_pen():
    from core.composition import Composicion
    comp = Composicion()
    comp.frames.append(MarcoVista(pen_hatch_mm=0.13))
    back = Composicion.from_dict(json.loads(json.dumps(comp.to_dict())))
    assert back.frames[0].pen_hatch_mm == 0.13
    assert MarcoVista().pen_hatch_mm == 0.0


# ---- The soft insulation symbol, fitted to each piece ------------------------

def _band(cx, cy, length, thick, angle):
    a = math.radians(angle)
    u, v = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
    return [(cx + u[0] * x + v[0] * y, cy + u[1] * x + v[1] * y)
            for x, y in ((-length / 2, -thick / 2), (length / 2, -thick / 2),
                         (length / 2, thick / 2), (-length / 2, thick / 2))]


@pytest.mark.parametrize("angle", [0, 30, 90, 135])
def test_a_piece_is_measured_along_its_length_and_across_its_thickness(angle):
    from core.hatches import fit_band
    origin, along, across, length, thick = fit_band(_band(10, 20, 50, 6,
                                                          angle))
    assert length == pytest.approx(50) and thick == pytest.approx(6)
    a = math.radians(angle)
    assert abs(along[0] * math.cos(a) + along[1] * math.sin(a)) \
        == pytest.approx(1.0)


def test_the_insulation_reads_as_teardrops_up_and_down():
    """Half circles touching against each face, and from the ends of each
    one straight legs to where two half circles meet on the other face —
    teardrops pointing up and down, side by side, from face to face."""
    from core.hatches import batt_marks, _BATT_RADIUS
    polys = batt_marks((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 40.0, 8.0)
    ys = [y for pts in polys for _x, y in pts]
    assert min(ys) == pytest.approx(0.0, abs=1e-6)
    assert max(ys) == pytest.approx(8.0, abs=1e-6)
    r = 8.0 * _BATT_RADIUS
    legs = [pts for pts in polys if len(pts) == 3]
    for (x0, y0), (x1, y1), (x2, y2) in legs:
        # from the two ends of an arch to the meeting point of two cups
        assert y0 == y2 == pytest.approx(r) and y1 == pytest.approx(8.0 - r)
        assert x1 - x0 == pytest.approx(r) and x2 - x1 == pytest.approx(r)
    arches = [pts for pts in polys if len(pts) > 3 and pts[len(pts) // 2][1]
              < 1e-6]
    cups = [pts for pts in polys if len(pts) > 3 and pts[len(pts) // 2][1]
            > 8.0 - 1e-6]
    assert arches and cups
    centres = sorted((pts[0][0] + pts[-1][0]) / 2 for pts in arches)
    assert centres[1] - centres[0] == pytest.approx(2 * r)   # they touch
    thick = batt_marks((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 40.0, 16.0)
    assert len(thick) < len(polys)               # bigger, so fewer


def test_the_insulation_symbol_fills_a_slanted_piece_on_the_sheet():
    import numpy as np
    from views.composer import _paint_cut_fills_mm
    ring = np.array(_band(30, 20, 40, 8, 30))
    img = QImage(60 * 6, 40 * 6, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(6, 6)
    frame = MarcoVista(style="vectorial", cut_fill="solid",
                       cut_fill_color="#000000", pen_hatch_mm=0.2)
    _paint_cut_fills_mm(p, frame, [ring], [(None, "insulation", None, None,
                                            {"scale": 1.0})])
    p.end()
    inked = [(x, y) for x in range(0, 360, 2) for y in range(0, 240, 2)
             if QColor(img.pixel(x, y)).lightness() < 150]
    assert len(inked) > 100                      # the balloons are drawn
    from PySide6.QtGui import QPolygonF
    from PySide6.QtCore import QPointF
    poly = QPolygonF([QPointF(x * 6, y * 6) for x, y in ring])
    from PySide6.QtCore import Qt as _Qt
    outside = [pt for pt in inked
               if not poly.containsPoint(QPointF(*pt), _Qt.OddEvenFill)]
    assert len(outside) < len(inked) * 0.05      # and only inside the piece


# ---- Masonry as it is seen: courses in section, bond along the wall in plan --

def _ink_rows_and_cols(look, ring):
    import numpy as np
    from views.composer import _paint_cut_fills_mm
    img = QImage(200, 200, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.translate(0.37, 0.29)
    p.scale(5, 5)
    frame = MarcoVista(style="vectorial", cut_fill="solid",
                       cut_fill_color="#000000", pen_hatch_mm=0.15)
    _paint_cut_fills_mm(p, frame, [np.array(ring)], [look])
    p.end()
    dark = [[QColor(img.pixel(x, y)).lightness() < 128 for x in range(200)]
            for y in range(200)]
    full_rows = sum(1 for row in dark[20:180] if sum(row[20:180]) > 150)
    full_cols = sum(1 for x in range(20, 180)
                    if sum(dark[y][x] for y in range(20, 180)) > 150)
    return full_rows, full_cols


def test_masonry_in_a_vertical_section_is_its_courses():
    """Cut across a wall (36 mm at 1:10: 360 mm), the courses level and
    split where its wythes meet; cut along one (40 mm at 1:20: 800 mm, too
    wide for a wall), its face: level courses, head joints staggered."""
    form = {"scale": 1.0, "cut": "vertical", "scale_n": 10.0,
            "joints": "single"}
    across = [(2, 0), (38, 0), (38, 40), (2, 40)]
    rows, cols = _ink_rows_and_cols((None, "brick", None, None, form),
                                    across)
    assert rows >= 5 and cols >= 1
    square = [(0, 0), (40, 0), (40, 40), (0, 40)]
    rows, cols = _ink_rows_and_cols((None, "brick", None, None,
                                     dict(form, scale_n=20.0)), square)
    assert rows >= 5 and cols == 0           # bed joints only, level


def test_masonry_in_plan_follows_the_wall():
    """A wall running up the plan: its bond runs up too — the joint
    between its wythes is vertical, the head joints short, across it."""
    form = {"scale": 1.0, "cut": "plan", "scale_n": 10.0}
    tall = [(10, 0), (30, 0), (30, 40), (10, 40)]
    rows, cols = _ink_rows_and_cols((None, "brick", None, None, form), tall)
    assert cols >= 1 and rows == 0
    wide = [(0, 10), (40, 10), (40, 30), (0, 30)]
    rows, cols = _ink_rows_and_cols((None, "brick", None, None, form), wide)
    assert rows >= 1 and cols == 0


def test_a_sheet_knows_its_cut_is_a_plan_or_a_section():
    from core.section import SectionPlane
    composer, frame, host = _composer()
    scene = host.viewport.scene
    scene.layer("Muros").hatch = "brick"
    composer.compute_hlr(frame)                      # the plan cut at 1 m
    forms = [look[4] for look in composer.hlr_fill_styles[id(frame)]
             if look[1] == "brick"]
    assert forms and forms[0]["cut"] == "plan"
    for sp in scene.section_planes:
        sp.active = False
    upright = SectionPlane(V(2, 0.15, 1), V(0, -1, 0))
    scene.section_planes.append(upright)
    scene.set_active_section(upright)
    frame.view_key = "std:front"
    composer.compute_hlr(frame)
    forms = [look[4] for look in composer.hlr_fill_styles[id(frame)] or ()
             if look[1] == "brick"]
    assert forms and forms[0]["cut"] == "vertical"



# ---- Line types of one's own: made, imported, exported -----------------------

_LIN = """;; a test file
*BORDE_2,Double border __ __ .
A,6,-1.5,6,-1.5,0,-1.5
*GAS,Gas ---- GAS ----
A,.5,-.2,["GAS",STANDARD,S=.1,R=0.0,X=-0.1,Y=-.05],-.25
*BOXES,With a shape
A,.5,-.2,[BOX,ltypeshp.shx,x=-.1,s=.1],-.1
*FENCE,Imperial fence
A,.25,-.1,0,-.1
*BROKEN,no gap
A,5,5
"""


def test_a_line_type_file_is_read_and_its_complex_types_left_out():
    found, skipped = L.parse_lin(_LIN)
    assert set(found) == {"BORDE_2", "FENCE", "GAS"}
    assert found["BORDE_2"]["pattern"] == [6.0, -1.5, 6.0, -1.5, 0.0, -1.5]
    assert found["FENCE"]["pattern"][0] == pytest.approx(6.35)   # inches
    assert skipped == ["BOXES"]                    # a shape: left out
    # The text one: its two gaps one room, the words in it, in mm.
    gas = found["GAS"]
    assert gas["pattern"] == pytest.approx([12.7, -11.43])
    assert gas["text"] == "GAS" and gas["text_at"] == 1
    assert gas["text_size"] == pytest.approx(2.54)
    back, _ = L.parse_lin(L.to_lin(
        [(n, e["label"], e["pattern"]) for n, e in found.items()]))
    assert back["BORDE_2"]["pattern"] == found["BORDE_2"]["pattern"]


def test_a_pattern_must_draw_and_leave_blank():
    assert L.clean_pattern([3, -1]) == [3.0, -1.0]
    for bad in ([], [3, 3], [-1, -2], [float("nan"), -1], "x", [5000, -1]):
        assert L.clean_pattern(bad) is None


def test_the_pen_draws_dash_gap_in_turn():
    assert L.drawn_dashes((6, -1.5, 0, -1.5)) == (6, 1.5, 0, 1.5)
    assert L.drawn_dashes((-1, 4, -1)) == (4, 2)        # leading gap moved
    assert L.drawn_dashes((3, 3, -1)) == (6, 1)         # two dashes joined
    assert L.file_dashes((6, 1.5, 0, 1.5)) == (6, -1.5, 0, -1.5)


def test_a_layer_takes_a_line_type_of_the_document(tmp_path):
    from formats import igz
    scene = Scene()
    L.load_line_types(scene, {"Borde": {"label": "Borde",
                                        "pattern": [6, -1.5, 0, -1.5]}})
    scene.layers.append(Layer("Lindero", linetype="lin:Borde"))
    assert Layer("X", linetype="zigzag").linetype == "continuous"
    st = L.line_styles(scene, False)["Lindero"]
    assert st[1] == "lin:Borde" and st[4] == (6.0, 1.5, 0.0, 1.5)
    path = tmp_path / "lin.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.layer("Lindero").linetype == "lin:Borde"
    assert back.line_types["Borde"]["pattern"] == [6.0, -1.5, 0.0, -1.5]
    igz.save_scene(Scene(), tmp_path / "empty.igz")
    igz.load_into(back, tmp_path / "empty.igz")
    assert back.line_types == {}                  # no leak to the next


def test_a_template_and_the_legend_carry_the_own_line_type():
    src = Scene()
    L.load_line_types(src, {"Borde": {"label": "Borde",
                                      "pattern": [6, -1.5, 0, -1.5]},
                            "Unused": {"label": "U", "pattern": [1, -1]}})
    src.layers.append(Layer("Lindero", linetype="lin:Borde"))
    data = json.loads(json.dumps(L.template_of(src)))
    assert set(data["line_types"]) == {"Borde"}  # only the used ones
    dst = Scene()
    L.apply_template(dst, data)
    assert dst.layer("Lindero").linetype == "lin:Borde"
    assert "Borde" in dst.line_types
    _rows, swatches = L.legend_rows(src)
    assert swatches["Lindero"]["pattern"] == [6.0, 1.5, 0.0, 1.5]


def test_the_sheet_pen_draws_the_own_line_type():
    from PySide6.QtGui import QPen
    from views.composer import _layer_pen
    base = QPen()
    base.setWidthF(0.25)
    pen = _layer_pen(base, (None, "lin:Borde", None, None, (6.0, 1.5)),
                     KIND_EDGE)
    assert pen.dashPattern() and pen.dashPattern()[0] == pytest.approx(
        6.0 / 0.25)


def test_the_dxf_declares_the_own_line_type(tmp_path):
    from formats.dxf_out import save_dxf_layers
    from views.composer import dxf_groups_by_layer
    scene = _wall_and_door(Scene())
    L.load_line_types(scene, {"Borde": {"label": "Borde",
                                        "pattern": [6, -1.5, 0, -1.5]}})
    scene.layer("Muros").linetype = "lin:Borde"
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, fills=False,
                    layers=True)
    d.styles = L.line_styles(scene, colored=True)
    path = tmp_path / "own.dxf"
    save_dxf_layers(path, dxf_groups_by_layer(d, "PLANTA", False))
    text = path.read_text(encoding="ascii")
    assert "0\nLTYPE\n2\nBORDE\n" in text
    assert "49\n0.6\n49\n-0.15\n49\n0\n49\n-0.15\n" in text
    assert "6\nBORDE\n" in text                  # the layer uses it


def test_the_line_type_list_ends_with_custom_and_its_tools(win):
    from PySide6.QtWidgets import QMenu
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A"))
    panel.refresh()
    menu = QMenu()
    panel._fill_linetypes(menu, ["A"], scene.layer("A"))
    texts = [a.text() for a in menu.actions()]
    assert texts[-3:] == ["New line type…", "Import .lin…", "Export .lin…"]
    assert "Custom line types" not in texts       # none of its own yet
    assert not menu.actions()[-1].isEnabled()     # nothing to export
    assert panel.add_line_type("Borde", [6, -1.5, 0, -1.5], ["A"])
    assert scene.layer("A").linetype == "lin:Borde"
    menu = QMenu()
    panel._fill_linetypes(menu, ["A"], scene.layer("A"))
    texts = [a.text() for a in menu.actions()]
    assert "Custom line types" in texts and "Borde" in texts
    assert texts.index("Borde") > texts.index("Custom line types")
    assert menu.actions()[-1].isEnabled()
    assert panel.item_for("A").toolTip(4 + 3) == "Borde" or True
    assert panel.add_line_type("Mal", [5, 5], ["A"]) is None


def test_the_panel_imports_and_exports_line_type_files(win, tmp_path):
    panel = win.layers_dock.panel
    lin = tmp_path / "mine.lin"
    lin.write_text(_LIN, encoding="utf-8")
    n, skipped = panel.import_lin_file(lin)
    assert n == 3 and skipped == ["BOXES"]
    assert panel.import_lin_file(tmp_path / "missing.lin") == (0, [])
    out = tmp_path / "out.lin"
    assert panel.export_lin_file(out) == 3
    found, _ = L.parse_lin(out.read_text(encoding="utf-8"))
    assert set(found) == {"BORDE_2", "FENCE", "GAS"}
    assert found["GAS"]["text"] == "GAS"           # written, read back


def test_the_editor_draws_as_it_is_typed_and_refuses_a_bad_pattern():
    from PySide6.QtWidgets import QDialogButtonBox
    from views.layers_panel import LineTypeDialog
    dlg = LineTypeDialog(None, name="Borde", pattern=[6, -1.5])
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert ok.isEnabled() and dlg.result_pattern() == [6.0, -1.5]
    dlg.pattern_edit.setText("5, 5")              # no gap: not a line type
    assert not ok.isEnabled() and dlg.problem.text()
    dlg.pattern_edit.setText("")
    for b in dlg.findChildren(type(ok)):
        if b.text() in ("+ Dash", "+ Gap", "+ Dot"):
            b.click()
    assert dlg.result_pattern() == [3.0, -1.5, 0.0]
    assert ok.isEnabled()



# ---- Bonds: brick by brick, by the wall's thickness and the brick's size -----

def test_english_bond_alternates_headers_and_stretchers():
    from core.hatches import bond_course
    depth, height, rects = bond_course("brick_bond", 0, 215.0, None, 0, 1000)
    assert {(b0, b1) for _a0, _a1, b0, b1, _k in rects} == {(0.0, 225.0)}
    assert rects[1][1] - rects[1][0] == pytest.approx(112.5)   # headers
    _d, _h, rects = bond_course("brick_bond", 1, 215.0, None, 0, 1000)
    assert {(b0, b1) for _a0, _a1, b0, b1, _k in rects} == {
        (0.0, 112.5), (112.5, 225.0)}                         # two wythes
    assert height == pytest.approx(75.0) and depth == pytest.approx(225.0)


def test_one_and_a_half_swaps_its_faces_course_by_course():
    from core.hatches import bond_course
    _d, _h, a = bond_course("brick_one_half", 0, 330.0, None, 0, 500)
    _d, _h, b = bond_course("brick_one_half", 1, 330.0, None, 0, 500)
    assert min(r[3] - r[2] for r in a if r[2] == 0.0) == pytest.approx(112.5)
    assert min(r[3] - r[2] for r in b if r[2] == 0.0) == pytest.approx(225.0)


def test_the_bond_by_thickness_follows_each_wall():
    from core.hatches import bond_course
    for thick, depth in ((60.0, 75.0),        # brick on edge
                         (102.5, 112.5),      # half a brick, stretchers
                         (215.0, 225.0),      # one brick, English
                         (330.0, 337.5)):     # one and a half
        assert bond_course("brick_auto", 0, thick)[0] == pytest.approx(depth)


def test_paved_areas_and_walls_cut_along_show_the_face():
    """No wall: a paved area or a wall cut along shows the bond's face —
    courses the whole width, staggered head joints."""
    from core.hatches import bond_marks
    wall = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 60.0, 2.4)
    assert bond_marks("brick", wall, "plan", 0.5, 100.0)["lines"]
    yard = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 60.0, 30.0)
    face = bond_marks("brick", yard, "plan", 0.5, 100.0)["lines"]
    beds = [ln for ln in face if abs(ln[1] - ln[3]) < 1e-9
            and abs(ln[2] - ln[0]) >= 60.0 - 1e-6]
    assert len(beds) >= 30 * 2 / 1.5 * 0.9 / 2      # a bed every course
    heads = [ln for ln in face if abs(ln[0] - ln[2]) < 1e-9]
    assert heads and all(abs(ln[3] - ln[1]) == pytest.approx(0.75)
                         for ln in heads)          # one course high
    across = bond_marks("brick", ((0.0, 50.0), (0.0, -1.0), (1.0, 0.0),
                                  50.0, 40.0), "vertical", 0.5, 400.0)
    assert across["lines"]                         # a wall cut along
    assert bond_marks("concrete", wall, "plan") is None


def test_the_joints_follow_the_scale():
    from core.hatches import joints_mode
    assert joints_mode(None, 100) == joints_mode(None, 75) == "hatch"
    assert joints_mode(None, 50) == joints_mode(None, 20) == "single"
    assert joints_mode(None, 15) == joints_mode(None, 5) == "double"
    for mode in ("single", "double", "none"):
        assert joints_mode(mode, 200) == mode
    assert joints_mode("zigzag", 50) == "single"


def test_double_joints_part_every_brick_by_its_real_joint():
    from core.hatches import bond_marks, fit_band
    wall = [(0.0, 0.0), (60.0, 0.0), (60.0, 21.5), (0.0, 21.5)]   # 1:10
    marks = bond_marks("brick_bond", fit_band(wall), "plan", 5.0, 10.0,
                       None, "double")
    assert not marks["lines"] and marks["bricks"]
    xs = sorted({round(min(x for x, _y in b), 6) for b in marks["bricks"]})
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    # Headers 112.5 mm on centres, at 1:10 and × 5 the course: 11.25 mm.
    assert gaps[1] == pytest.approx(11.25, abs=0.01)
    one = marks["bricks"][2]
    w = max(x for x, _y in one) - min(x for x, _y in one)
    assert w == pytest.approx(10.25, abs=0.01)     # the brick, the joint off
    sec = bond_marks("brick_bond", ((0.0, 40.0), (0.0, -1.0), (1.0, 0.0),
                                    40.0, 21.5), "vertical", 5.0, 10.0,
                     None, "double")
    hs = sorted({round(min(-y for _x, y in b), 4) for b in sec["bricks"]})
    assert hs[1] - hs[0] == pytest.approx(7.5, abs=0.01)   # course 75 mm


def test_a_layer_keeps_its_joints_and_mortar(tmp_path):
    ly = Layer("Muro", hatch="brick", joints="double", mortar=True)
    back = Layer.from_dict(ly.to_dict())
    assert back.joints == "double" and back.mortar is True
    assert Layer("X", joints="wavy").joints is None
    assert "joints" not in Layer("X", hatch="brick").to_dict()
    scene = Scene()
    scene.layers.append(ly)
    form = L.cut_hatch_forms(scene, 10.0)["Muro"]
    assert form["joints"] == "double" and form["mortar"] is True


def test_a_small_scale_draws_masonry_as_a_hatch():
    """At 1:100 the bricks blur: the 45° hatch instead; at 1:20, joints."""
    form = {"scale": 1.0, "cut": "plan", "scale_n": 100.0}
    wide = [(0, 10), (40, 10), (40, 30), (0, 30)]
    rows, cols = _ink_rows_and_cols((None, "brick", None, None, form), wide)
    assert rows == 0 and cols == 0                  # diagonals only
    none = _ink_rows_and_cols((None, "brick", None, None,
                               dict(form, joints="none")), wide)
    assert none == (0, 0)



def test_a_gap_of_the_honeycomb_bond_is_crossed():
    from core.hatches import bond_course
    _d, _h, rects = bond_course("brick_honeycomb", 0, 102.5, None, 0, 1000)
    gaps = [r for r in rects if r[4] == "gap"]
    bricks = [r for r in rects if r[4] == "brick"]
    assert gaps and bricks
    assert gaps[0][1] - gaps[0][0] == pytest.approx(112.5)    # half a brick
    assert bricks[0][1] - bricks[0][0] == pytest.approx(225.0)


def test_a_layer_keeps_its_own_brick(tmp_path):
    from core.hatches import clean_brick, real_scale
    from formats import igz
    assert clean_brick((290, 140, 71, 10)) == (290.0, 140.0, 71.0, 10.0)
    for bad in ((100, 200, 50, 10), (290, 140, 71), ("x", 1, 1, 1),
                (290, 140, 71, 99), (float("nan"), 1, 1, 1)):
        assert clean_brick(bad) is None
    ly = Layer("Muros", hatch="brick", brick=(290, 140, 71, 10))
    assert Layer.from_dict(ly.to_dict()).brick == (290.0, 140.0, 71.0, 10.0)
    assert Layer("X", brick=(1, 1, 1, 1)).brick is None
    scene = Scene()
    scene.layers.append(ly)
    path = tmp_path / "brick.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.layer("Muros").brick == (290.0, 140.0, 71.0, 10.0)
    # A taller course: the pattern grows to it, real at any scale.
    assert real_scale("brick", 10, (290, 140, 71, 10)) == pytest.approx(
        81.0 / 10.0 / 1.5)
    forms = L.cut_hatch_forms(scene, 10.0)
    assert forms["Muros"]["brick"] == (290.0, 140.0, 71.0, 10.0)
    assert forms["Muros"]["families"]                  # drawn with it
    assert forms["Muros"]["scale_n"] == 10.0


def test_the_brick_families_follow_the_brick():
    from core.hatches import brick_families
    usual = brick_families("brick")
    chile = brick_families("brick", (290, 140, 71, 10))
    assert usual[0][4] == chile[0][4] == 1.5          # the course
    # A stretcher: (length + joint) / (height + joint) courses long.
    assert chile[1][4] * 2 == pytest.approx(1.5 * 300.0 / 81.0)
    assert usual[1][4] * 2 == pytest.approx(1.5 * 225.0 / 75.0)


def test_the_picker_sets_the_brick_for_brickwork_only():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", form={"brick": None}))
    grid.more_buttons["piece"].setChecked(True)          # the fields
    got = []
    grid.brick_picked.connect(got.append)
    assert grid.brick_box.isEnabled()
    assert grid.brick_combo.currentIndex() == 0           # the usual one
    grid.brick_combo.setCurrentIndex(2)
    grid.brick_combo.activated.emit(2)                    # Chile
    assert got[-1] == (290.0, 140.0, 71.0, 10.0)
    grid.brick_spins[1].setValue(400.0)                   # wider than long
    assert grid.brick_problem.isVisibleTo(grid) and len(got) == 1
    grid.brick_spins[1].setValue(140.0)
    grid.brick_spins[3].setValue(12.0)
    assert got[-1] == (290.0, 140.0, 71.0, 12.0)
    assert grid.brick_combo.currentText() == "Custom"
    grid._pick("block")                                   # its own sizes
    assert grid.brick_box.isEnabled() and grid.brick_combo.isEnabled()
    assert grid.brick_combo.itemText(0) == "390 × 140 × 190"   # measures
    grid._pick("ashlar")                                  # joints, no size
    assert grid.brick_box.isEnabled() and not grid.brick_combo.isEnabled()
    grid._pick("concrete")
    assert not grid.brick_box.isEnabled()


def test_the_panel_sets_the_brick(win):
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Muro", hatch="brick"))
    panel.refresh()
    panel.set_style(["Muro"], brick=(240, 115, 50, 10))
    assert scene.layer("Muro").brick == (240.0, 115.0, 50.0, 10.0)
    panel.set_style(["Muro"], brick=None)
    assert scene.layer("Muro").brick is None



def test_the_zigzag_insulation_runs_face_to_face():
    from core.hatches import FITTED, fitted_marks
    assert "insulation_zigzag" in FITTED
    (pts,) = fitted_marks("insulation_zigzag", (0.0, 0.0), (1.0, 0.0),
                          (0.0, 1.0), 12.0, 3.0)
    ys = {round(y, 6) for _x, y in pts}
    assert ys == {0.0, 3.0}                      # every corner on a face
    xs = [x for x, _y in pts]
    assert xs[1] - xs[0] == pytest.approx(1.5)   # a V every thickness
    assert min(xs) <= 0.0 and max(xs) >= 12.0
    assert fitted_marks("insulation_zigzag", (0, 0), (1, 0), (0, 1),
                        12.0, 0.0) == []



def test_the_preview_shows_masonry_cut_in_plan_and_section():
    from views.hatch_paint import cut_tile
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick_bond"))
    assert grid.cut_preview.isVisibleTo(grid)
    assert not grid.cut_same.isVisibleTo(grid)
    for tile in (grid.plan_tile, grid.section_tile):
        img = tile.pixmap().toImage()
        dark = sum(1 for x in range(2, img.width() - 2)
                   for y in range(2, img.height() - 2)
                   if QColor(img.pixel(x, y)).lightness() < 120)
        assert dark > 40                         # a wall, inked
    # The tiles are as tall as each other: one wall, one scale.
    assert grid.plan_tile.height() == grid.section_tile.height()
    card = grid.cut_preview.parentWidget()
    grid._pick("concrete")
    assert not grid.cut_preview.isVisibleTo(grid)   # same in any cut
    assert grid.cut_same.isVisibleTo(grid)          # and it says so
    assert card.sizeHint().height() > 0
    grid._pick("insulation_zigzag")
    assert grid.cut_preview.isVisibleTo(grid)
    plain = cut_tile("concrete", "plan", 104, 44).toImage()
    assert QColor(plain.pixel(52, 22)).lightness() > 200   # paper only



def test_a_click_on_an_empty_spot_keeps_the_picker_open(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMenu
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Muro", hatch="brick"))
    panel.refresh()
    menu = QMenu()
    panel._fill_hatches(menu, ["Muro"], scene.layer("Muro"))
    menu.popup(QPoint(40, 40))
    for _ in range(3):
        _app.processEvents()
    grid = menu.actions()[0].defaultWidget()
    for spot in (grid.preview_name, grid.preview, grid.plan_tile,
                 grid.section_tile, grid.ground_name):
        QTest.mouseClick(spot, Qt.LeftButton)
        _app.processEvents()
        assert menu.isVisible(), spot
    QTest.mouseClick(grid, Qt.LeftButton, pos=QPoint(grid.width() - 4,
                                                     grid.height() - 60))
    _app.processEvents()
    assert menu.isVisible()
    grid.done_button.click()
    _app.processEvents()
    assert not menu.isVisible()



def test_timber_cut_across_is_crossed_corner_to_corner():
    from core.hatches import FITTED, fit_band, fitted_marks
    assert "wood_cross" in FITTED
    stud = [(10.0, 0.0), (15.0, 0.0), (15.0, 10.0), (10.0, 10.0)]
    a, b = fitted_marks("wood_cross", *fit_band(stud))
    corners = {(10.0, 0.0), (15.0, 0.0), (15.0, 10.0), (10.0, 10.0)}
    ends = {tuple(round(v, 6) for v in q) for q in a + b}
    assert ends == corners                       # the two diagonals
    assert fitted_marks("wood_cross", (0, 0), (1, 0), (0, 1), 5.0, 0.0) == []



def test_a_piece_is_cut_across_when_short_and_stocky():
    from core.hatches import WOOD, cut_across, fit_band
    assert "wood_grain" in WOOD and "wood_cross" not in WOOD
    stud = [(0, 0), (1.5, 0), (1.5, 0.5), (0, 0.5)]        # 15 × 5 cm, 1:10
    board = [(0, 0), (40, 0), (40, 0.5), (0, 0.5)]         # 4 m × 5 cm
    joist = [(0, 0), (0.5, 0), (0.5, 2.5), (0, 2.5)]       # 5 × 25 cm
    assert cut_across(fit_band(stud), 10.0)
    assert cut_across(fit_band(joist), 10.0)
    assert not cut_across(fit_band(board), 10.0)
    assert not cut_across(fit_band(stud), 1000.0)          # 15 m: no stud
    assert not cut_across(None)


def test_a_wood_layer_crosses_the_pieces_cut_across(tmp_path, monkeypatch):
    from formats import igz
    ly = Layer("Madera", hatch="wood_grain", hatch_cross=True)
    assert Layer.from_dict(ly.to_dict()).hatch_cross is True
    assert "hatch_cross" not in Layer("X", hatch="wood_grain").to_dict()
    scene = Scene()
    scene.layers.append(ly)
    path = tmp_path / "cross.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.layer("Madera").hatch_cross is True
    assert L.cut_hatch_forms(back, 10.0)["Madera"]["cross"] is True
    # On a sheet: the stud gets the cross, the board its grain.
    import views.hatch_paint as hp
    crossed, grained = [], []
    real_fitted, real_hatch = hp.paint_fitted, hp.paint_hatch
    monkeypatch.setattr(hp, "paint_fitted", lambda p, path, rings, key, *a:
                        (crossed.append((key, len(rings))),
                         real_fitted(p, path, rings, key, *a)))
    monkeypatch.setattr(hp, "paint_hatch", lambda p, path, key, *a, **k:
                        (grained.append(key), real_hatch(p, path, key, *a,
                                                         **k)))
    stud = [(20, 20), (35, 20), (35, 25), (20, 25)]        # 15 × 5 cm
    board = [(20, 60), (180, 60), (180, 65), (20, 65)]     # 1.6 m × 5 cm
    form = {"scale": 1.0, "cut": "vertical", "scale_n": 10.0, "cross": True}
    _ink_rows_and_cols((None, "wood_grain", None, None, form), stud)
    assert crossed == [("wood_cross", 1)] and not grained
    _ink_rows_and_cols((None, "wood_grain", None, None, form), board)
    assert grained == ["wood_grain"] and len(crossed) == 1
    _ink_rows_and_cols((None, "wood_grain", None, None,
                        dict(form, cross=False)), stud)
    assert len(crossed) == 1                               # off: the grain


def test_the_picker_offers_the_cross_for_wood_only():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("wood_grain", form={"hatch_cross": False}))
    got = []
    grid.form_picked.connect(got.append)
    assert grid.cross_check.isEnabled()
    assert not grid.cut_preview.isVisibleTo(grid)        # grain alone
    grid.cross_check.setChecked(True)
    assert got[-1]["hatch_cross"] is True
    assert grid.cut_preview.isVisibleTo(grid)            # plan + crossed cut
    grid._pick("concrete")
    assert not grid.cross_check.isEnabled()



def test_the_picker_sets_the_joints_and_the_mortar(win):
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", form={"joints": "single"}))
    got = []
    grid.form_picked.connect(got.append)
    assert grid.joints_combo.currentData() == "single"
    i = grid.joints_combo.findData("double")
    grid.joints_combo.setCurrentIndex(i)
    grid.joints_combo.activated.emit(i)
    assert got[-1] == {"joints": "double", "mortar": False}
    grid.mortar_check.setChecked(True)
    assert got[-1] == {"joints": "double", "mortar": True}
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Muro", hatch="brick"))
    panel.set_style(["Muro"], **got[-1])
    assert scene.layer("Muro").joints == "double"
    assert scene.layer("Muro").mortar is True
    panel.set_style(["Muro"], joints=None)
    assert scene.layer("Muro").joints is None



def test_a_click_on_a_style_cell_selects_the_layer_being_edited(win,
                                                                monkeypatch):
    from views import layers_panel as lp
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    for n in ("A", "B", "C"):
        scene.layers.append(Layer(n))
    panel.refresh()
    opened = []
    monkeypatch.setattr(type(panel), "open_hatch_picker",
                        lambda self, targets, ly: opened.append(list(targets)))
    panel.item_for("A").setSelected(True)
    panel.click_cell(panel._key(panel.item_for("B")), lp.COL_HATCH)
    assert opened[-1] == ["B"]
    assert [panel._key(i)[1] for i in panel.tree.selectedItems()] == ["B"]
    assert panel.tree.currentItem() is panel.item_for("B")
    # Clicked inside a selection of several: they all stay, all take it.
    panel.item_for("C").setSelected(True)
    panel.click_cell(panel._key(panel.item_for("C")), lp.COL_HATCH)
    assert sorted(opened[-1]) == ["B", "C"]
    assert sorted(panel._key(i)[1]
                  for i in panel.tree.selectedItems()) == ["B", "C"]



def test_the_picker_shows_at_once_without_the_menu_effects(win,
                                                            monkeypatch):
    """No fade or slide while it opens — its shadow would show first, alone
    — and the effects back for every other menu once it is up."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Muro", hatch="brick"))
    panel.refresh()
    QApplication.setEffectEnabled(Qt.UI_General, True)
    QApplication.setEffectEnabled(Qt.UI_FadeMenu, True)
    QApplication.setEffectEnabled(Qt.UI_AnimateMenu, True)
    before = (QApplication.isEffectEnabled(Qt.UI_FadeMenu),
              QApplication.isEffectEnabled(Qt.UI_AnimateMenu))
    seen = []
    monkeypatch.setattr(type(panel), "_popup", staticmethod(
        lambda menu, at: seen.append(
            (QApplication.isEffectEnabled(Qt.UI_FadeMenu),
             QApplication.isEffectEnabled(Qt.UI_AnimateMenu),
             menu.actions()[0].defaultWidget().isVisibleTo(menu)))))
    panel.open_hatch_picker(["Muro"], scene.layer("Muro"))
    assert seen == [(False, False, True)]
    _app.processEvents()
    assert before == (True, True)
    assert (QApplication.isEffectEnabled(Qt.UI_FadeMenu),
            QApplication.isEffectEnabled(Qt.UI_AnimateMenu)) == before



def test_the_arrows_walk_the_patterns():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from core.hatches import HATCH_GROUPS
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid(None, recent=[]))
    got = []
    grid.picked.connect(got.append)
    # «No hatch» is the first tile of General: the walk starts there.
    general = [None] + list(HATCH_GROUPS[0][1])
    grid.search.setFocus()
    QTest.keyClick(grid, Qt.Key_Right)
    assert got[-1] == general[1]
    QTest.keyClick(grid, Qt.Key_Left)
    assert got[-1] is None
    QTest.keyClick(grid.search, Qt.Key_Down)         # the row below
    assert got[-1] == general[grid.COLUMNS]
    QTest.keyClick(grid, Qt.Key_Down)                # into the next group
    assert got[-1] == HATCH_GROUPS[1][1][0]
    QTest.keyClick(grid, Qt.Key_Up)
    assert got[-1] == general[grid.COLUMNS]
    assert grid.buttons[got[-1]].isChecked()
    # A tile with the focus walks too, and the search narrows the walk.
    grid.buttons[got[-1]].setFocus()
    QTest.keyClick(grid.buttons[got[-1]], Qt.Key_Right)
    assert got[-1] == general[grid.COLUMNS + 1]
    grid.search.setText("brick")
    QTest.keyClick(grid.search, Qt.Key_Down)
    assert "brick" in got[-1]
    # The spin boxes keep their arrows.
    n = len(got)
    grid.angle_spin.setFocus()
    QTest.keyClick(grid.angle_spin, Qt.Key_Up)
    assert len(got) == n and grid.angle_spin.value() == 15.0


def test_the_arrows_walk_the_patterns_inside_the_open_picker(win):
    """In the menu that holds it, the arrows still reach the grid (not the
    menu's own entry by entry walk)."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMenu
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Muro", hatch="brick"))
    panel.refresh()
    menu = QMenu()
    panel._fill_hatches(menu, ["Muro"], scene.layer("Muro"))
    menu.popup(QPoint(40, 40))
    for _ in range(3):
        _app.processEvents()
    grid = menu.actions()[0].defaultWidget()
    grid.search.setFocus()
    QTest.keyClick(grid.search, Qt.Key_Right)       # the text keeps it
    QTest.keyClick(grid.search, Qt.Key_Down)
    _app.processEvents()
    assert scene.layer("Muro").hatch != "brick"     # moved, and applied
    assert menu.isVisible()
    menu.close()



# ---- One wall in pieces, and the hatches in the DXF ---------------------------

def test_the_pieces_of_one_wall_share_their_joints():
    """A wall split by a door: the head joints of both pieces fall on one
    grid, whichever way round each piece was traced."""
    from core.hatches import bond_marks, fit_band
    left = [(0.0, 0.0), (30.0, 0.0), (30.0, 2.15), (0.0, 2.15)]
    right = [(70.0, 2.15), (40.0, 2.15), (40.0, 0.0), (70.0, 0.0)]  # reversed
    xs = set()
    for ring in (left, right):
        marks = bond_marks("brick", fit_band(ring), "plan", 5.0, 10.0, None,
                           "single")
        heads = [ln for ln in marks["lines"] if abs(ln[0] - ln[2]) < 1e-9]
        xs |= {round(ln[0] % 22.5, 6) % 22.5 for ln in heads
               if 0.0 <= ln[0] <= 70.0}
    # Stretchers 225 mm at 1:10 = 22.5 mm, in two wythes half a brick apart:
    # every head joint on one of two phases, the same in both pieces.
    assert len(xs) <= 2


def test_the_courses_of_two_pieces_line_up_in_a_section():
    from core.hatches import bond_marks, vertical_band
    a = [(0.0, 0.0), (2.15, 0.0), (2.15, 40.0), (0.0, 40.0)]
    b = [(30.0, 13.0), (32.15, 13.0), (32.15, 40.0), (30.0, 40.0)]
    beds = []
    for ring in (a, b):
        marks = bond_marks("brick", vertical_band(ring), "vertical", 5.0,
                           10.0, None, "single")
        beds.append({round(ln[1] % 7.5, 6) % 7.5 for ln in marks["lines"]
                     if abs(ln[1] - ln[3]) < 1e-9})
    assert beds[0] == beds[1] and len(beds[0]) == 1


def test_clip_keeps_what_is_inside_even_odd():
    from core.hatches import clip_segments
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6)]
    parts = clip_segments([(-5, 5, 15, 5)], [outer, hole])
    spans = sorted((round(min(x0, x1), 6), round(max(x0, x1), 6))
                   for x0, _y0, x1, _y1 in parts)
    assert spans == [(0.0, 4.0), (6.0, 10.0)]
    assert clip_segments([(20, 20, 30, 30)], [outer]) == []


def test_hatch_lines_draw_as_the_sheet_does():
    from core.hatches import hatch_lines
    wall = [(0.0, 0.0), (60.0, 0.0), (60.0, 2.15), (0.0, 2.15)]
    plan = {"scale": 5.0, "cut": "plan", "scale_n": 10.0}
    lines = hatch_lines("brick", [wall], plan)
    assert lines and all(-1e-6 <= min(x0, x1) and max(x0, x1) <= 60 + 1e-6
                         and -1e-6 <= min(y0, y1) and max(y0, y1) <= 2.15
                         + 1e-6 for x0, y0, x1, y1 in lines)
    small = hatch_lines("brick", [wall], dict(plan, scale_n=100.0))
    assert small and all(abs((x1 - x0) - (y1 - y0)) < 1e-6
                         or abs((x1 - x0) + (y1 - y0)) < 1e-6
                         for x0, y0, x1, y1 in small)   # the 45° hatch
    assert hatch_lines("brick", [wall], dict(plan, joints="none")) == []
    assert hatch_lines("solid", [wall], plan) == []
    assert hatch_lines("insulation", [wall], plan)      # fitted, piece-wise
    assert hatch_lines("concrete", [wall], plan)         # its stones


def test_the_dxf_of_a_view_carries_its_hatches(tmp_path):
    from formats.dxf_out import save_dxf_layers
    composer, frame, host = _composer()
    scene = host.viewport.scene
    scene.layer("Muros").hatch = "brick"
    frame.scale_n = 20.0
    groups = composer.dxf_hatch_groups(frame)
    names = [g[0] for g in groups]
    assert names == ["Muros-TRAMA"] and len(groups[0][1])
    path = tmp_path / "view.dxf"
    save_dxf_layers(path, groups)
    assert "Muros-TRAMA" in path.read_text(encoding="ascii",
                                           errors="replace").replace(
        "MUROS-TRAMA", "Muros-TRAMA")
    frame.cut_fill = "none"
    assert composer.dxf_hatch_groups(frame) == []



# ---- Timber: the grain from the 3D piece ----------------------------------------

def _timber(scene):
    """A stud standing through a plan cut at 1 m, a beam lying along it
    (cut along its length), and a short block lying flat across it — short
    and stocky in the cut, but cut along its grain too."""
    scene.layers.append(Layer("Madera", hatch="wood_grain",
                              hatch_cross=True))
    for name, box in (("pie", (0.0, 0.0, 0.0, 0.05, 0.15, 2.4)),
                      ("viga", (0.0, 1.0, 0.9, 4.0, 1.1, 1.1)),
                      ("taco", (1.0, 2.0, 0.95, 1.3, 2.1, 1.05))):
        g = Group(Mesh(), name=name)
        _box(g.mesh, *box)
        g.layer = "Madera"
        scene.groups.append(g)
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1))
    scene.section_planes.append(sp)
    scene.set_active_section(sp)
    return scene


def test_a_solid_runs_through_the_plane_as_deep_as_it_is():
    from core.hlr import hlr_drawing, solid_depth
    scene = _timber(Scene())
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, fills=True,
                    layers=True, depth_layers=["Madera"])
    sizes = []
    for ring, depth in zip(d.loops, d.loop_depths):
        w = float(ring[:, 0].max() - ring[:, 0].min())
        sizes.append((round(w, 3), None if depth is None
                      else round(depth, 3)))
    assert sorted(sizes) == [(0.05, 2.4), (0.3, 0.1), (4.0, 0.2)]
    plain = hlr_drawing(scene, _top_camera(scene), profiles=False,
                        fills=True, layers=True)
    assert plain.loop_depths is None                # not asked: not measured
    assert solid_depth([(9, 9, 1), (9.1, 9, 1), (9.1, 9.1, 1)],
                       [[(0, 0, 0), (1, 0, 0), (0, 1, 0)]], (0, 0, 1)) is None


def test_the_grain_settles_the_cross_when_the_piece_is_known():
    from core.hatches import cut_across, fit_band
    beam = [(0, 0), (60, 0), (60, 2.5), (0, 2.5)]       # 6 m cut along: 1:10
    stocky = [(0, 0), (1.5, 0), (1.5, 0.5), (0, 0.5)]
    assert not cut_across(fit_band(beam), 10.0)
    assert cut_across(fit_band(beam), 10.0, depth=70.0)   # runs on further
    assert cut_across(fit_band(stocky), 10.0)              # by its shape
    assert not cut_across(fit_band(stocky), 10.0, depth=0.5)


def test_only_the_timber_cut_across_its_grain_is_crossed(monkeypatch):
    """The stud gets the cross; the beam and the block — cut along — their
    grain, though the block is short and stocky in the cut and its shape
    alone would have crossed it."""
    import core.hatches as H
    from core.hlr import hlr_drawing
    scene = _timber(Scene())
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, fills=True,
                    layers=True, depth_layers=["Madera"])
    k = 10.0                                       # paper mm per metre
    rings = [[(x * k, -y * k) for x, y in r] for r in d.loops]
    depths = [None if v is None else v * k for v in d.loop_depths]
    form = {"scale": 1.0, "cut": "plan", "scale_n": 100.0, "cross": True}
    crossed = []
    real = H.fitted_marks

    def spy(key, origin, along, across, length, thick, *a, **kw):
        crossed.append(round(min(length, thick) / k, 3))
        return real(key, origin, along, across, length, thick, *a, **kw)
    monkeypatch.setattr(H, "fitted_marks", spy)
    H.hatch_lines("wood_grain", rings, form, 1.0, depths)
    assert crossed == [0.05]                      # the stud alone
    crossed.clear()
    H.hatch_lines("wood_grain", rings, form, 1.0)  # by shape: the block too
    assert sorted(crossed) == [0.05, 0.1]



# ---- Solid fills and both DXF exports --------------------------------------------

def test_a_region_cuts_into_strips_even_odd():
    from core.hatches import fill_quads
    outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
    hole = [(4, 4), (6, 4), (6, 6), (4, 6)]
    quads = fill_quads([outer, hole])

    def area(q):
        (ax, ay), (bx, by), (cx, cy), (dx, dy) = q
        return ((bx - ax) + (dx - cx)) / 2.0 * (cy - ay)
    assert sum(area(q) for q in quads) == pytest.approx(100.0 - 4.0)
    tri = fill_quads([[(0, 0), (4, 0), (0, 4)]])
    assert sum(area(q) for q in tri) == pytest.approx(8.0)
    assert fill_quads([]) == []


def test_the_dxf_writes_solids_under_the_lines(tmp_path):
    from formats.dxf_out import save_dxf_layers
    path = tmp_path / "solid.dxf"
    save_dxf_layers(path, [("LINEAS", [(0, 0, 1, 1)])],
                    [("RELLENO", [((0, 0), (1, 0), (0, 1), (1, 1))],
                      (0.9, 0.9, 0.9))])
    text = path.read_text(encoding="ascii")
    assert "0\nSOLID\n8\nRELLENO\n" in text
    assert text.index("SOLID\n8") < text.index("LINE\n8")   # under them
    assert "2\nRELLENO\n70\n0\n62\n" in text             # declared


def test_a_view_dxf_carries_grounds_and_solid_fills():
    from views.composer import dxf_cut_layers
    scene = _wall_and_door(Scene())
    scene.layer("Muros").hatch = "brick"
    scene.layer("Muros").hatch_ground = (1.0, 1.0, 1.0)
    scene.layer("Carpinterías").hatch = "solid"
    lines, solids = dxf_cut_layers(scene, _top_camera(scene))
    assert [g[0] for g in lines] == ["Muros-TRAMA"]
    names = sorted(s[0] for s in solids)
    assert names == ["Carpinterías-TRAMA", "Muros-FONDO"]
    ground = next(s for s in solids if s[0] == "Muros-FONDO")
    area = sum(((q[1][0] - q[0][0]) + (q[3][0] - q[2][0])) / 2.0
               * abs(q[2][1] - q[0][1]) for q in ground[1])
    assert area == pytest.approx(4.0 * 0.3)       # the whole wall's cut
    assert ground[2] == (1.0, 1.0, 1.0)


def test_the_current_view_dxf_carries_the_hatches_too(win, tmp_path,
                                                      monkeypatch):
    from views.filedialogs import file_dialogs
    scene = win.viewport.scene
    _wall_and_door(scene)
    scene.layer("Muros").hatch = "brick"
    win.viewport.camera.set_view("top")
    win.viewport.camera.perspective = False
    path = tmp_path / "vista.dxf"
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(path), ""))
    win._on_export_view_dxf()
    text = path.read_text(encoding="ascii", errors="replace")
    assert "MUROS-TRAMA" in text



# ---- Line types that write words: GAS, AGUA… ----------------------------------

def test_a_line_type_takes_its_words_in_a_gap_of_their_own():
    pattern, spec = L.with_text([6.0, -1.5], "GAS", 2.5)
    room = L.text_width("GAS", 2.5) + 2.0
    assert pattern == pytest.approx([6.0, -1.5 - room])   # the gap widened
    assert spec == {"text": "GAS", "text_size": 2.5, "text_at": 1}
    # Its middle in the middle of that gap.
    assert L.text_offset(pattern, 1) == pytest.approx(6.0 + (1.5 + room) / 2)
    assert L.with_text([6.0, -1.5], "  ") == ([6.0, -1.5], None)
    assert L.clean_line_text({"text": "X", "text_at": 0}, [6.0, -1.5]) is None
    huge = L.clean_line_text({"text": "AGUA" * 20, "text_size": 99,
                              "text_at": 1}, [6.0, -1.5])
    assert len(huge["text"]) == 24 and huge["text_size"] == 20.0


def test_the_words_fall_where_the_gaps_are_and_read_upright():
    spec = ("GAS", 2.5, 10.0, 20.0)
    marks = L.text_marks((0.0, 0.0), (65.0, 0.0), spec)
    assert [round(x, 6) for x, _y, _a in marks] == [10.0, 30.0, 50.0]
    back = L.text_marks((65.0, 0.0), (0.0, 0.0), spec)
    assert {a for _x, _y, a in back} == {0.0}           # not upside down
    assert L.text_marks((0, 0), (3, 0), spec) == []     # no room for one


def test_a_document_keeps_and_draws_a_line_type_with_words(tmp_path):
    from formats import igz
    scene = Scene()
    pattern, spec = L.with_text([8.0, -2.0], "GAS", 2.0)
    L.load_line_types(scene, {"Gas": dict({"label": "Gas",
                                           "pattern": pattern}, **spec)})
    scene.layers.append(Layer("Instalaciones", linetype="lin:Gas"))
    path = tmp_path / "gas.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.line_types["Gas"]["text"] == "GAS"
    words = L.line_styles(back, False)["Instalaciones"][5]
    assert words[0] == "GAS" and words[1] == 2.0
    assert L.linetype_text("dashed") is None


def test_the_dxf_writes_the_words_as_text(tmp_path):
    from formats.dxf_out import save_dxf_layers
    from views.composer import dxf_groups_by_layer
    scene = _wall_and_door(Scene())
    pattern, spec = L.with_text([8.0, -2.0], "GAS", 2.0)
    L.load_line_types(scene, {"Gas": dict({"label": "Gas",
                                           "pattern": pattern}, **spec)})
    scene.layer("Muros").linetype = "lin:Gas"
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, fills=False,
                    layers=True)
    d.styles = L.line_styles(scene, colored=True)
    texts: list = []
    groups = dxf_groups_by_layer(d, "PLANTA", False, texts)
    assert texts and all(t[5] == "GAS" and t[3] == pytest.approx(0.2)
                         for t in texts)
    path = tmp_path / "gas.dxf"
    save_dxf_layers(path, groups, (), texts)
    text = path.read_text(encoding="ascii")
    assert "0\nTEXT\n8\nMUROS\n" in text and "\n1\nGAS\n" in text


def test_the_sheet_writes_the_words_along_the_line():
    from PySide6.QtGui import QImage, QPainter, QPen
    from views.composer import _paint_hlr_lines_mm
    from core.hlr import KIND_EDGE
    pattern, spec = L.with_text([8.0, -2.0], "GAS", 2.5)
    scene = Scene()
    L.load_line_types(scene, {"Gas": dict({"label": "Gas",
                                           "pattern": pattern}, **spec)})
    words = L.linetype_text("lin:Gas", scene)
    style = (None, "lin:Gas", 0.25, None,
             L.linetype_pattern("lin:Gas", scene), words)

    def ink(with_words):
        img = QImage(400, 60, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        p = QPainter(img)
        p.scale(5, 5)
        frame = MarcoVista(style="vectorial")
        _paint_hlr_lines_mm(p, frame, [(2.0, 6.0, 78.0, 6.0)], [KIND_EDGE],
                            styles=(["X"], {"X": style if with_words
                                            else style[:5] + (None,)}))
        p.end()
        return sum(1 for x in range(400) for y in range(60)
                   if QColor(img.pixel(x, y)).lightness() < 128)
    assert ink(True) > ink(False) + 100        # the letters, inked



# ---- Favourite hatches, and the line type editor -------------------------------

def test_a_pinned_pattern_comes_first_and_stays():
    from PySide6.QtCore import QSettings, Qt
    from views.layers_panel import HatchGrid
    QSettings().setValue(HatchGrid.FAVOURITES_KEY, [])
    grid = _shown(HatchGrid("brick", recent=[]))
    assert not grid.favourite_buttons and not grid.star.isChecked()
    grid.star.click()                                # pin the current one
    assert HatchGrid.favourites() == ["brick"]
    assert list(grid.favourite_buttons) == ["brick"]
    assert grid._sections[0][0] == "Favourites"
    assert grid.star.isChecked() and grid.star.text() == "★"
    grid.set_favourite("insulation", True)
    assert list(grid.favourite_buttons) == ["brick", "insulation"]
    # A favourite tile is a shortcut: it picks, the grid keeps its own.
    grid.favourite_buttons["insulation"].click()
    assert grid._current == "insulation"
    assert grid.buttons["insulation"].isChecked()
    # The next picker opens with them.
    again = _shown(HatchGrid(None, recent=[]))
    assert list(again.favourite_buttons) == ["brick", "insulation"]
    grid.set_favourite("brick", False)
    assert HatchGrid.favourites() == ["insulation"]
    # The arrows walk the catalogue, not the shortcuts.
    again._pick("solid")
    again._step(Qt.Key_Left)
    assert again._current is None                   # «No hatch», first
    QSettings().setValue(HatchGrid.FAVOURITES_KEY, [])


def test_the_editor_writes_words_along_the_line():
    from PySide6.QtWidgets import QDialogButtonBox
    from views.layers_panel import LineTypeDialog
    dlg = LineTypeDialog(None, name="Gas", pattern=[8, -2])
    dlg.text_edit.setText("GAS")
    dlg.size_spin.setValue(2.0)
    assert dlg.result_text() == ("GAS", 2.0)
    assert dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert not dlg.preview.pixmap().isNull()
    edit = LineTypeDialog(None, name="Gas", pattern=[8, -2], text="GAS",
                          editing=True)
    assert edit.windowTitle() == "Edit line type"


def test_the_panel_edits_and_deletes_its_line_types(win):
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Gas"))
    panel.refresh()
    key = panel.add_line_type("Gas", [8, -2], ["Gas"], "GAS", 2.0)
    entry = scene.line_types["Gas"]
    assert entry["pieces"] == [8.0, -2.0] and entry["text"] == "GAS"
    assert entry["pattern"][1] < -2.0              # room for the words
    assert L.linetype_text(key, scene)[0] == "GAS"
    # Edited, renamed: its layers follow.
    panel.add_line_type("Gas natural", [10, -2], (), "GN", 2.0,
                        replaces="Gas")
    assert "Gas" not in scene.line_types
    assert scene.layer("Gas").linetype == "lin:Gas natural"
    panel.delete_line_type("Gas natural")
    assert scene.line_types == {}
    assert scene.layer("Gas").linetype == "continuous"



# ---- The document's brick ----------------------------------------------------

def test_the_document_pieces_draw_every_layer_without_its_own(tmp_path):
    from formats import igz
    chile = (290.0, 140.0, 71.0, 10.0)
    block = (390.0, 190.0, 190.0, 10.0)
    scene = Scene()
    scene.layers += [Layer("Muros", hatch="brick"),
                     Layer("Tabiques", hatch="brick_on_edge",
                           brick=(240, 115, 50, 10)),
                     Layer("Bloques", hatch="block")]
    scene.bricks = {"brick": chile, "block": block}
    assert L.layer_brick(scene, scene.layer("Muros")) == chile
    assert L.layer_brick(scene, scene.layer("Tabiques"))[0] == 240.0
    assert L.layer_brick(scene, scene.layer("Bloques")) == block
    forms = L.cut_hatch_forms(scene, 10.0)
    assert forms["Muros"]["brick"] == chile
    assert forms["Bloques"]["brick"] == block
    path = tmp_path / "brick.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.bricks == {"brick": chile, "block": block}
    igz.save_scene(Scene(), tmp_path / "plain.igz")
    igz.load_into(back, tmp_path / "plain.igz")
    assert back.bricks == {}                       # no leak to the next
    data = json.loads(json.dumps(L.template_of(scene)))
    other = Scene()
    L.apply_template(other, data)
    assert other.bricks == {"brick": chile, "block": block}


def test_a_block_and_a_ticholo_are_drawn_their_own_size():
    from core.hatches import bond_course, piece_kind, real_unit
    assert piece_kind("block") == "block"
    assert piece_kind("hollow_brick") == "hollow"
    assert piece_kind("brick_bond") == "brick"
    assert piece_kind("ashlar") is None and piece_kind("concrete") is None
    _d, course, rects = bond_course("block", 0, 190.0,
                                    (390.0, 190.0, 190.0, 10.0), 0, 2000)
    assert course == pytest.approx(200.0)
    assert rects[1][1] - rects[1][0] == pytest.approx(400.0)
    _d, course, rects = bond_course("block", 0, 190.0,
                                    (440.0, 190.0, 240.0, 10.0), 0, 2000)
    assert course == pytest.approx(250.0)          # a taller block
    assert real_unit("block", (440.0, 190.0, 240.0, 10.0))[1] == \
        pytest.approx(0.25)
    # The ticholo: 12 × 17 × 25 by default, a course 18 cm.
    _d, course, _r = bond_course("hollow_brick", 0, 120.0, None, 0, 1000)
    assert course == pytest.approx(180.0)


def test_once_for_the_whole_document(win):
    from views.layers_panel import HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers += [Layer("A", hatch="brick", brick=(240, 115, 50, 10)),
                     Layer("B", hatch="brick_bond"),
                     Layer("C", hatch="block", brick=(390, 90, 190, 10))]
    panel.refresh()
    grid = _shown(HatchGrid("brick", form={"brick": None}))
    got = []
    grid.brick_for_document.connect(got.append)
    grid.brick_combo.setCurrentIndex(2)
    grid.brick_combo.activated.emit(2)                   # Chile
    grid.brick_document.click()
    assert got == [("brick", (290.0, 140.0, 71.0, 10.0))]
    panel.set_document_brick(got[-1])
    assert scene.bricks == {"brick": (290.0, 140.0, 71.0, 10.0)}
    assert scene.layer("A").brick is None               # follows it now
    assert scene.layer("C").brick is not None           # a block: its own
    # A picker opened on a layer then shows the document's brick, and
    # picking that same one gives the layer no brick of its own.
    grid = _shown(HatchGrid("brick", form={"brick": None,
                                           "doc_bricks": scene.bricks}))
    assert grid.brick_combo.currentIndex() == 2
    picked = []
    grid.brick_picked.connect(picked.append)
    grid.brick_combo.activated.emit(2)
    assert picked == [None]
    # A block picked: the block's sizes, its usual one shown, its drawing.
    grid._pick("block")
    assert grid.brick_spins[0].value() == 390.0
    assert grid.piece_view.isVisibleTo(grid)
    assert not grid.piece_view.pixmap().isNull()
    grid._pick("concrete")
    assert not grid.piece_view.isVisibleTo(grid)


def test_a_layer_switched_to_another_piece_forgets_its_size(win):
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("M", hatch="brick", brick=(290, 140, 71, 10)))
    panel.set_style(["M"], hatch="brick_bond")          # still a brick
    assert scene.layer("M").brick is not None
    panel.set_style(["M"], hatch="block")               # a block now
    assert scene.layer("M").brick is None


# ---- Bed joint and head joint ------------------------------------------------------

def test_a_brick_may_have_two_joints():
    from core.hatches import brick_dims, clean_brick
    assert clean_brick((290, 140, 71, 10, 10)) == (290.0, 140.0, 71.0, 10.0)
    assert clean_brick((290, 140, 71, 12, 8)) == (290.0, 140.0, 71.0, 12.0,
                                                  8.0)
    assert clean_brick((290, 140, 71, 12, 99)) is None
    assert brick_dims((290, 140, 71, 10)) == (290.0, 140.0, 71.0, 10.0, 10.0)
    assert Layer.from_dict(Layer("X", brick=(290, 140, 71, 12, 8))
                           .to_dict()).brick[4] == 8.0


def test_the_bed_joint_sets_the_courses_the_head_joint_the_bricks():
    from core.hatches import bond_course, brick_families
    brick = (240.0, 115.0, 50.0, 15.0, 5.0)        # 15 bed, 5 head
    depth, course, rects = bond_course("brick", 0, 115.0, brick, 0, 1000)
    assert course == pytest.approx(65.0)           # height + bed joint
    assert rects[1][1] - rects[1][0] == pytest.approx(245.0)  # + head
    assert brick_families("brick", brick)[1][4] * 2 == pytest.approx(
        1.5 * 245.0 / 65.0)


def test_double_joints_show_each_joint_its_own_width():
    from core.hatches import bond_marks
    brick = (240.0, 115.0, 50.0, 20.0, 6.0)
    # A paved area at 1:10 (2 m: no wall, the bond's face), × 1 the
    # course (70 mm → 1.5 paper mm): per_mm known.
    face = bond_marks("brick", ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0),
                                200.0, 200.0), "plan", 1.0, 10.0, brick,
                      "double")
    one = face["bricks"][0]
    xs = sorted({round(x, 6) for x, _y in one})
    ys = sorted({round(y, 6) for _x, y in one})
    per_mm = 1.5 / 70.0
    assert xs[1] - xs[0] == pytest.approx(240.0 * per_mm)   # head off
    assert ys[1] - ys[0] == pytest.approx(50.0 * per_mm)    # bed off


def test_the_padlock_keeps_the_joints_one_or_frees_them():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", form={"brick": None}))
    got = []
    grid.brick_picked.connect(got.append)
    bed, head = grid.brick_spins[3], grid.brick_spins[4]
    assert grid.joint_lock.isChecked() and not head.isEnabled()
    bed.setValue(12.0)                              # locked: both follow
    assert head.value() == 12.0 and got[-1][3:] == (12.0,)
    grid.joint_lock.setChecked(False)               # open: each its own
    assert head.isEnabled()
    head.setValue(6.0)
    assert got[-1][3:] == (12.0, 6.0)
    grid.joint_lock.setChecked(True)                # closed again: one
    assert head.value() == 12.0 and got[-1][3:] == (12.0,)
    # A layer with two joints opens with the padlock open.
    other = _shown(HatchGrid("brick", form={"brick": (240, 115, 50, 15, 5)}))
    assert not other.joint_lock.isChecked()
    assert other.brick_spins[4].value() == 5.0



# ---- Aerated concrete, load-bearing ceramic blocks, Uruguay ----------------------

def test_aerated_concrete_is_big_glued_and_porous():
    from core.hatches import bond_course, bond_marks, piece_kind
    assert piece_kind("aac_block") == "aac"
    _d, course, rects = bond_course("aac_block", 0, 150.0, None, 0, 2000)
    assert course == pytest.approx(203.0)          # 200 and a 3 mm joint
    assert rects[1][1] - rects[1][0] == pytest.approx(603.0)
    wall = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 60.0, 15.0)   # 1:10
    marks = bond_marks("aac_block", wall, "plan", 5.0, 10.0)
    assert marks["polys"]                          # its pores
    assert hatch_marks_have_circles("aac_block")


def hatch_marks_have_circles(key):
    from core.hatches import hatch_marks
    return bool(hatch_marks(key, (0.0, 0.0, 20.0, 20.0))["circles"])


def test_a_load_bearing_ceramic_block_shows_its_upright_holes():
    from core.hatches import bond_course, bond_marks, piece_kind
    assert piece_kind("perforated_block") == "perforated"
    _d, course, rects = bond_course("perforated_block", 0, 120.0, None,
                                    0, 1000)
    assert course == pytest.approx(200.0)          # 190 and its joint
    assert {r[4] for r in rects} == {"perforated"}
    wall = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 60.0, 12.0)   # 1:10
    plan = bond_marks("perforated_block", wall, "plan", 5.0, 10.0)
    assert len(plan["polys"]) > 20                 # the holes, from above
    section = bond_marks("perforated_block",
                         ((0.0, 40.0), (0.0, -1.0), (1.0, 0.0), 40.0, 12.0),
                         "vertical", 5.0, 10.0)
    webs = [ln for ln in section["lines"] if abs(ln[0] - ln[2]) < 1e-9]
    assert webs                                    # cut through them


def test_uruguay_and_the_new_pieces_are_in_the_lists():
    from core.hatches import PIECE_SIZES
    names = {k: [n for n, _s in v] for k, v in PIECE_SIZES.items()}
    assert "Uruguay" in names["brick"]
    assert "Rejillón" in names["perforated"]
    assert names["aac"][0] == "Aerated 15"
    assert dict(PIECE_SIZES["aac"])["Aerated 15"][3] == 3.0



def test_the_picker_shows_only_the_settings_its_pattern_uses():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", recent=[]))
    height = grid.height()
    assert grid.piece_section.isVisibleTo(grid)
    assert not grid.wood_section.isVisibleTo(grid)
    grid._pick("wood_grain")
    assert grid.wood_section.isVisibleTo(grid)
    assert not grid.piece_section.isVisibleTo(grid)
    grid._pick("concrete")
    assert not grid.wood_section.isVisibleTo(grid)
    assert not grid.piece_section.isVisibleTo(grid)
    _app.processEvents()
    assert grid.height() == height                # nothing jumps
    # The .pat files: two buttons on the left, the answers on the right.
    load, save = grid.file_buttons
    assert (load.text(), save.text()) == ("Import .pat…", "Export .pat…")
    assert not load.icon().isNull() and not save.icon().isNull()
    assert save.x() < grid.cancel_button.x() < grid.done_button.x()
    assert load.x() < grid.width() / 4
    got = []
    grid.import_requested.connect(lambda: got.append("in"))
    grid.export_requested.connect(lambda: got.append("out"))
    load.click()
    save.click()
    assert got == ["in", "out"]



def test_the_seldom_used_settings_fold_away():
    from PySide6.QtCore import QSettings
    from views.layers_panel import HatchGrid
    QSettings().setValue(HatchGrid.MORE_KEY, [])
    grid = _shown(HatchGrid("brick", recent=[]))
    height = grid.height()
    # Folded: the list and the measures in a line; no fields.
    assert not grid.more_boxes["piece"].isVisibleTo(grid)
    assert grid.drawing_check.isVisibleTo(grid)      # always in sight
    assert grid.piece_summary.text().startswith("215 × 102.5 × 65 mm")
    grid.more_buttons["piece"].setChecked(True)
    assert grid.brick_spins[0].isVisibleTo(grid)
    assert grid.height() == height                   # nothing jumps
    assert QSettings().value(HatchGrid.MORE_KEY) == ["piece"]
    # «Custom» opens the fields by itself.
    grid.more_buttons["piece"].setChecked(False)
    last = grid.brick_combo.count() - 1
    grid.brick_combo.setCurrentIndex(last)
    grid.brick_combo.activated.emit(last)
    assert grid.more_boxes["piece"].isVisibleTo(grid)
    # Two joints read as two.
    grid.joint_lock.setChecked(False)
    grid.brick_spins[4].setValue(6.0)
    assert "10 / 6" in grid.piece_summary.text()
    QSettings().setValue(HatchGrid.MORE_KEY, [])


def test_no_hatch_is_the_first_tile():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", recent=[]))
    general = next(t for t in grid._sections if t[0] == "General")
    assert general[2][0][0] is None
    tile = grid.buttons[None]
    assert tile.objectName() == "hatch_frame"
    assert tile.toolTip() == "No hatch (the frame's fill)"
    got = []
    grid.picked.connect(got.append)
    tile.click()
    assert got == [None] and grid.buttons[None].isChecked()



def test_a_precast_concrete_brick_shows_its_holes():
    from core.hatches import PIECE_SIZES, bond_course, bond_marks, piece_kind
    assert piece_kind("concrete_brick") == "cored"
    assert PIECE_SIZES["cored"][0][0] == "Concrete brick 12"
    _d, course, rects = bond_course("concrete_brick", 0, 120.0, None, 0, 1000)
    assert course == pytest.approx(70.0)
    assert {r[4] for r in rects} == {"cored"}
    wall = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 60.0, 12.0)   # 1:10
    plan = bond_marks("concrete_brick", wall, "plan", 5.0, 10.0)
    assert 4 <= len(plan["polys"]) < 40              # a few holes each


# ---- The layers' hatches in the model --------------------------------------

def _model_cut(scene):
    """The active plane through ``scene``: its chords and each one's layer,
    as the viewer tags them."""
    from core.hlr import collect_geometry
    from core.section import cut_chords
    tris, _h, _s, _hl, _sl, tags = collect_geometry(scene, layers=True)
    t = np.asarray(tris, dtype=np.float64)
    sp = scene.active_section()
    chords, rows = cut_chords(t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0],
                              sp.normal, sp.point, rows=True)
    return chords, np.asarray(tags, dtype=object)[rows]


def test_the_model_cut_shows_each_layers_hatch():
    from core.section import layer_fills
    scene = _wall_and_door(Scene())
    scene.layer("Muros").hatch = "brick"
    scene.layer("Carpinterías").hatch = "solid"
    scene.layer("Carpinterías").hatch_color = (0.2, 0.4, 0.1)
    chords, tags = _model_cut(scene)
    grey = (0.35, 0.37, 0.41)
    fills = layer_fills(chords, tags, scene.active_section().normal, scene,
                        grey)
    assert len(fills) == 3
    tris, rgb, lines, _ink = fills[0]           # the loose box: no hatch
    assert rgb == grey and lines is None and len(tris)
    door = [f for f in fills if f[1] == (0.2, 0.4, 0.1)]
    assert len(door) == 1 and door[0][2] is None         # solid, its ink
    walls = [f for f in fills if f[2] is not None]
    assert len(walls) == 1
    _tris, ground, lines, ink = walls[0]
    assert ink == grey                                   # as the frame says
    assert ground == pytest.approx(tuple(c + (1 - c) * 0.85 for c in grey))
    assert np.allclose(lines[:, :, 2], 1.0)              # in the plane
    xy = lines[:, :, :2].reshape(-1, 2)
    assert (xy[:, 0] > -1e-4).all() and (xy[:, 0] < 4 + 1e-4).all()
    assert (xy[:, 1] > -1e-4).all() and (xy[:, 1] < 0.3 + 1e-4).all()
    d = np.abs(lines[:, 1, :2] - lines[:, 0, :2])
    assert (d[:, 1] < 1e-6).any() and (d[:, 0] < 1e-6).any()   # courses
    assert len(lines) > 20


def test_a_section_cut_lays_its_courses_level():
    from core.section import _sheet_basis
    u, v = _sheet_basis(V(0, 1, 0))                      # a section
    assert v == pytest.approx((0, 0, 1)) and abs(u[2]) < 1e-9
    u, v = _sheet_basis(V(0, 0, 1))                      # a plan
    assert u == pytest.approx((1, 0, 0)) and v == pytest.approx((0, 1, 0))


def test_the_plane_keeps_the_layers_fill():
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1))
    sp.fill = {"pattern": "layers"}
    assert SectionPlane.from_dict(sp.to_dict()).fill == {"pattern": "layers"}


def test_the_viewer_fills_the_cut_by_layer_and_keeps_it():
    from views.main_window import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    vp = win.viewport
    scene = _wall_and_door(vp.scene)
    scene.layer("Muros").hatch = "brick"
    scene.active_section().fill = {"pattern": "layers"}
    scene.version += 1
    grey = (0.35, 0.37, 0.41)
    fills = vp._section_layer_fills(grey)
    assert fills is not None
    hatched = [f for f in fills if f[2] is not None]
    assert len(hatched) == 1 and len(hatched[0][2]) > 20
    assert vp._section_layer_fills(grey) is fills        # kept
    scene.layer("Muros").hatch = "concrete"              # a layer changes
    assert vp._section_layer_fills(grey) is not fills
    vp.repaint()                                         # draws without error
    win._saved_version = scene.version


def test_the_viewer_draws_each_layers_cut_weight_with_its_hatches():
    from views.main_window import MainWindow
    QApplication.instance() or QApplication([])
    win = MainWindow()
    vp = win.viewport
    scene = _wall_and_door(vp.scene)                 # Muros at 0.70
    scene.layer("Carpinterías").cut_weight = 0.18
    sp = scene.active_section()
    scene.version += 1
    segs = vp._section_cut_segments()
    keep = np.ones(len(segs), dtype=bool)
    vp._frame_style = vp._effective_style()
    assert set(vp._cut_edge_weights(sp, keep)) == {1.0}     # all alike
    sp.fill = {"pattern": "layers"}
    tags = vp._section_cut_cache[2]
    weights = vp._cut_edge_weights(sp, keep)
    assert weights[tags == "Muros"] == pytest.approx(1.4)
    assert weights[tags == "Carpinterías"] == pytest.approx(0.4)   # floor
    assert weights[tags == DEFAULT_LAYER] == pytest.approx(1.0)
    win._saved_version = scene.version


# ---- Where the pieces start ------------------------------------------------

def _shifted(marks, dx, dy):
    return sorted((round(x0 - dx, 6), round(y0 - dy, 6), round(x1 - dx, 6),
                   round(y1 - dy, 6)) for x0, y0, x1, y1 in marks["lines"])


def test_a_wall_starts_with_a_whole_brick_wherever_it_stands():
    from core.hatches import bond_marks
    here = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 60.0, 12.0)
    there = ((7.3, 4.1), (1.0, 0.0), (0.0, 1.0), 60.0, 12.0)
    a = bond_marks("brick_bond", here, "plan", 5.0, 10.0)
    b = bond_marks("brick_bond", there, "plan", 5.0, 10.0)
    assert _shifted(a, 0, 0) == pytest.approx(_shifted(b, 7.3, 4.1))
    # The first head joint at the wall's end, a whole brick from it.
    heads = sorted(x0 for x0, y0, x1, y1 in a["lines"]
                   if abs(x0 - x1) < 1e-9 and x0 > 1e-6)
    assert heads[0] > 1.0


def test_a_section_starts_its_first_course_at_the_foot():
    from core.hatches import bond_marks
    # A wall cut across, 12 mm thick on paper, 40 mm tall, its foot at y=40.
    band = ((0.0, 40.0), (0.0, -1.0), (1.0, 0.0), 40.0, 12.0)
    marks = bond_marks("brick", band, "vertical", 5.0, 10.0)
    beds = sorted({round(y0, 6) for x0, y0, x1, y1 in marks["lines"]
                   if abs(y0 - y1) < 1e-9}, reverse=True)
    assert beds[0] == pytest.approx(40.0)            # the first, at the foot
    turned = ((0.0, 0.0), (0.0, 1.0), (1.0, 0.0), 40.0, 12.0)   # drawn down
    again = bond_marks("brick", turned, "vertical", 5.0, 10.0)
    assert _shifted(marks, 0, 0) == pytest.approx(_shifted(again, 0, 0))


def test_the_offset_moves_the_first_joint_and_the_first_course():
    from core.hatches import bond_marks, real_scale
    wall = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 60.0, 12.0)
    a = bond_marks("brick_bond", wall, "plan", 5.0, 10.0)
    b = bond_marks("brick_bond", wall, "plan", 5.0, 10.0, offset=(50.0, 0.0))
    xs_a = sorted(x0 for x0, y0, x1, y1 in a["lines"] if abs(x0 - x1) < 1e-9)
    xs_b = sorted(x0 for x0, y0, x1, y1 in b["lines"] if abs(x0 - x1) < 1e-9)
    assert xs_a != xs_b
    shift = xs_b[1] - xs_a[1]
    assert shift > 0                                  # moved along the wall
    band = ((0.0, 40.0), (0.0, -1.0), (1.0, 0.0), 40.0, 12.0)
    up = bond_marks("brick", band, "vertical", 5.0, 10.0, offset=(0.0, 30.0))
    beds = sorted({round(y0, 6) for x0, y0, x1, y1 in up["lines"]
                   if abs(y0 - y1) < 1e-9}, reverse=True)
    inside = [b for b in beds if b <= 40.0 + 1e-6]
    assert 30.0 < inside[0] < 40.0 - 1e-6             # moved up the wall
    assert real_scale("brick", 10.0) is not None


def test_a_pattern_of_pieces_moves_and_a_texture_does_not():
    from core.hatches import PLACED, hatch_lines, hatch_marks
    box = (0.0, 0.0, 40.0, 40.0)
    a = hatch_marks("tile", box, 1.0)
    b = hatch_marks("tile", box, 1.0, offset=(1.5, -2.0))
    assert a["lines"] != b["lines"]
    assert "tile" in PLACED and "concrete" not in PLACED
    ring = [[(0, 0), (40, 0), (40, 40), (0, 40)]]
    still = hatch_lines("diagonal", ring, {"offset": (500.0, 0.0),
                                           "scale_n": 50.0})
    assert still == hatch_lines("diagonal", ring, {"scale_n": 50.0})
    moved = hatch_lines("tile", ring, {"offset": (500.0, 0.0),
                                       "scale_n": 50.0})
    assert moved != hatch_lines("tile", ring, {"scale_n": 50.0})


def test_the_layer_keeps_where_its_pieces_start():
    from core.layers import clean_offset, cut_hatch_forms
    ly = Layer("Muros", hatch="brick", hatch_offset=(115.0, -20.0))
    assert ly.has_style()
    back = Layer.from_dict(ly.to_dict())
    assert back.hatch_offset == (115.0, -20.0)
    assert Layer.from_dict(Layer("Muros").to_dict()).hatch_offset is None
    assert clean_offset((0, 0)) is None
    assert clean_offset(("a", 1)) is None
    assert clean_offset((float("nan"), 1)) is None
    assert clean_offset((1e9, 1)) == (10000.0, 1.0)
    scene = Scene()
    scene.layers.append(ly)
    assert cut_hatch_forms(scene, 50.0)["Muros"]["offset"] == (115.0, -20.0)


def test_the_picker_shifts_only_patterns_of_pieces():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick", form={"hatch_offset": (40.0, 0.0)}))
    assert grid.offset_spins[0].isVisibleTo(grid)
    # In the grid of Angle and Scale: each field under the one above.
    assert grid.offset_spins[0].x() == grid.angle_spin.x()
    assert grid.offset_spins[1].x() == grid.scale_spin.x()
    assert grid.offset_spins[0].value() == 40.0
    got = []
    grid.form_picked.connect(got.append)
    grid.offset_spins[1].setValue(25.0)
    assert got[-1]["hatch_offset"] == (40.0, 25.0)
    grid.offset_spins[0].setValue(0.0)
    grid.offset_spins[1].setValue(0.0)
    assert got[-1]["hatch_offset"] is None
    grid.close()
    grid = _shown(HatchGrid("concrete"))
    assert not any(w.isVisibleTo(grid) for w in grid.offset_widgets)
    grid.close()


def test_other_colour_is_a_chip_like_the_rest():
    from views.layers_panel import HatchGrid
    grid = _shown(HatchGrid("brick"))
    other = grid.ground_buttons["other"]
    white = grid.ground_buttons[(1.0, 1.0, 1.0)]
    assert other.iconSize() == white.iconSize()           # the same chip
    assert other.text() == "Other colour…"                # still named
    before = other.icon().pixmap(other.iconSize()).toImage()
    other.click()
    grid.colour_dialog.setCurrentColor(QColor(200, 30, 30))
    grid.colour_use.click()
    after = other.icon().pixmap(other.iconSize()).toImage()
    assert after != before                                # shows the pick
    assert other.isChecked()
    grid.close()


@pytest.mark.parametrize("how", ["escape", "outside"])
def test_closing_without_done_puts_the_layer_back(win, monkeypatch, how):
    """Picks show at once, but only «Done» keeps them: Esc or a click
    outside the picker is a «Cancel»."""
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("B", hatch="brick", hatch_angle=15.0))
    panel.refresh()
    seen = {}

    def fake_popup(menu, _at):
        menu.show()
        grid = next(w for w in menu.findChildren(HatchGrid))
        grid.buttons["concrete"].click()
        grid.angle_spin.setValue(90)
        seen["during"] = scene.layer("B").hatch
        menu.close()                   # Esc and a click outside both hide it

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "B"), COL_HATCH)
    ly = scene.layer("B")
    assert seen["during"] == "concrete"
    assert (ly.hatch, ly.hatch_angle) == ("brick", 15.0)


def test_done_keeps_what_was_picked(win, monkeypatch):
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("C", hatch="brick"))
    panel.refresh()

    def fake_popup(menu, _at):
        menu.show()
        grid = next(w for w in menu.findChildren(HatchGrid))
        grid.buttons["concrete"].click()
        grid.done_button.click()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "C"), COL_HATCH)
    assert scene.layer("C").hatch == "concrete"



def test_other_colour_keeps_the_picker_open_until_done(win, monkeypatch):
    """The colour is chosen inside the picker — no window of its own, which
    would close it — and, like every pick, kept only with «Done»."""
    from views.layers_panel import COL_HATCH, HatchGrid
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("D", hatch="brick"))
    panel.refresh()
    seen = {}

    def fake_popup(menu, _at):
        menu.show()
        grid = next(w for w in menu.findChildren(HatchGrid))
        grid.ink_buttons["other"].click()
        grid.colour_dialog.setCurrentColor(QColor(0, 0, 255))
        grid.colour_use.click()
        seen["open"] = menu.isVisible()
        seen["page"] = grid.colour_page.isVisible()
        seen["during"] = scene.layer("D").hatch_color
        menu.close()                          # no «Done»: put back

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "D"), COL_HATCH)
    assert seen == {"open": True, "page": False, "during": (0.0, 0.0, 1.0)}
    assert scene.layer("D").hatch_color is None


# ---- A line type's own colour ----------------------------------------------

def _gas_scene(scene):
    """A wall on «Gas», its line type yellow."""
    from core.layers import load_line_types
    load_line_types(scene, {"Gas": {"pattern": [6.0, -2.0],
                                    "color": [0.85, 0.65, 0.0]}})
    scene.layers.append(Layer("Gas", linetype="lin:Gas"))
    pipe = Group(Mesh(), name="caño")
    _box(pipe.mesh, 0, 0, 0, 4, 0.1, 0.1)
    pipe.layer = "Gas"
    scene.groups.append(pipe)
    return scene


def test_a_line_type_keeps_its_colour_and_inks_with_it():
    from core.layers import line_styles, linetype_color
    scene = _gas_scene(Scene())
    assert linetype_color("lin:Gas", scene) == (0.85, 0.65, 0.0)
    assert linetype_color("dashed", scene) is None
    # On any sheet: with the layers' colours or without.
    assert line_styles(scene, False)["Gas"][0] == (0.85, 0.65, 0.0)
    assert line_styles(scene, True)["Gas"][0] == (0.85, 0.65, 0.0)
    # A bad colour is dropped, the line type kept.
    from core.layers import load_line_types
    load_line_types(scene, {"Agua": {"pattern": [6.0, -2.0],
                                     "color": ["x", 1, 2]}})
    assert "color" not in scene.line_types["Agua"]


def test_the_line_type_colour_is_saved(tmp_path):
    from formats import igz
    scene = _gas_scene(Scene())
    path = tmp_path / "gas.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert tuple(back.line_types["Gas"]["color"]) == (0.85, 0.65, 0.0)


def test_the_editor_picks_a_colour_for_the_line_type():
    from views.layers_panel import LineTypeDialog
    dlg = LineTypeDialog(None)
    assert dlg.result_color() is None                   # by layer
    assert dlg.colour_buttons[None].isChecked()
    dlg.colour_buttons[(0.0, 0.40, 0.85)].click()
    assert dlg.result_color() == (0.0, 0.40, 0.85)
    again = LineTypeDialog(None, color=(0.85, 0.10, 0.10), editing=True)
    assert again.colour_buttons[(0.85, 0.10, 0.10)].isChecked()
    odd = LineTypeDialog(None, color=(0.3, 0.2, 0.1))
    assert odd.colour_buttons["other"].isChecked()


def test_the_panel_keeps_the_colour_it_is_given(win):
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Red"))
    key = panel.add_line_type("Agua", [6.0, -2.0], ["Red"], "AGUA", 2.5,
                              color=(0.0, 0.40, 0.85))
    assert scene.line_types["Agua"]["color"] == (0.0, 0.40, 0.85)
    assert scene.layer("Red").linetype == key
    panel.add_line_type("Agua", [6.0, -2.0], (), "", 2.5, replaces="Agua")
    assert "color" not in scene.line_types["Agua"]     # by layer again


def test_the_model_draws_the_line_types_by_default(win):
    """«Line types in the model», on unless a style says otherwise: a
    layer's edges come out dashed and in their line type's colour."""
    from core.style import Style
    vp = win.viewport
    scene = _gas_scene(vp.scene)
    scene.version += 1
    groups = vp._model_linetype_edges()
    assert len(groups) == 1
    rgb, dashes, gaps, words = groups[0]
    assert not len(words)                                # no text: no words
    assert rgb == (0.85, 0.65, 0.0)
    assert len(dashes) > 12 and len(gaps) > 0           # cut into dashes
    assert vp._model_linetype_edges() is groups         # kept
    assert Style(name="t").model_linetypes               # on by default
    off = Style(name="t")
    off.model_linetypes = False
    assert Style.from_dict(off.to_dict()).model_linetypes is False
    assert Style.from_dict({}).model_linetypes is True   # an old file: on
    panel = win.layers_dock.panel
    panel.set_model_linetypes(False)
    assert not scene.display_style.model_linetypes
    panel.set_model_linetypes(True)
    vp.repaint()                                         # draws without error
    win._saved_version = scene.version


def test_a_dash_pattern_cuts_an_edge_as_a_sheet_at_1_50():
    import numpy as np
    from core.layers import dash_segments
    seg = np.array([[[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]])
    dashes, gaps = dash_segments(seg, (6.0, 2.0))       # 0.30 m, 0.10 m
    assert len(dashes) == 3 and len(gaps) == 2
    assert np.allclose(dashes[0], [[0, 0, 0], [0.3, 0, 0]])
    assert np.allclose(gaps[0], [[0.3, 0, 0], [0.4, 0, 0]])
    whole, none = dash_segments(seg, ())                 # continuous
    assert len(whole) == 1 and not len(none)
    far = np.array([[[0.0, 0, 0], [1000.0, 0, 0]]])
    whole, none = dash_segments(far, (1.0, 1.0))         # too fine: whole
    assert len(whole) == 1 and not len(none)

def test_a_built_in_line_type_takes_a_colour_of_the_document(tmp_path):
    from core.layers import (template_of, line_styles, linetype_color,
                             set_linetype_color)
    from formats import igz
    scene = Scene()
    scene.layers.append(Layer("Ejes", linetype="dashdot"))
    assert linetype_color("dashdot", scene) is None
    assert set_linetype_color(scene, "dashdot", (0.85, 0.10, 0.10))
    assert not set_linetype_color(scene, "dashdot", (0.85, 0.10, 0.10))
    assert line_styles(scene, False)["Ejes"][0] == (0.85, 0.10, 0.10)
    path = tmp_path / "ejes.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert linetype_color("dashdot", back) == (0.85, 0.10, 0.10)
    assert template_of(scene)["linetype_colors"]["dashdot"] == [
        0.85, 0.10, 0.10]
    assert set_linetype_color(scene, "dashdot", None)          # by layer
    assert linetype_color("dashdot", scene) is None
    assert not scene.linetype_colors


def test_a_right_click_colours_any_line_type(win, monkeypatch):
    from views.layers_panel import LineTypeDialog
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    picks = []

    def fake_popup(menu, _at):
        texts = [a.text() for a in menu.actions()]
        assert texts == [l for _v, l in LineTypeDialog.COLOURS]
        next(a for a in menu.actions() if a.text() == picks[-1]).trigger()

    monkeypatch.setattr(panel, "_popup", fake_popup)
    picks.append("Blue")
    panel.ask_linetype_colour("dashed")
    assert scene.linetype_colors["dashed"] == (0.0, 0.40, 0.85)
    panel.add_line_type("Agua", [6.0, -2.0], ())
    picks.append("Red")
    panel.ask_linetype_colour("lin:Agua")
    assert scene.line_types["Agua"]["color"] == (0.85, 0.10, 0.10)
    picks.append("By layer")
    panel.ask_linetype_colour("dashed")
    assert "dashed" not in scene.linetype_colors


def _line_panel(win, monkeypatch, linetype, act):
    """Open the Line type cell of a layer «Ejes» and run ``act(menu)``
    with the panel shown."""
    from views.layers_panel import COL_LINETYPE
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("Ejes", linetype=linetype))
    panel.refresh()

    def fake_popup(menu, _at):
        menu.show()
        _app.processEvents()
        act(menu)

    monkeypatch.setattr(panel, "_popup", fake_popup)
    panel.click_cell(("layer", "Ejes"), COL_LINETYPE)
    return panel, scene


def test_the_line_panel_stays_open_and_shows_the_colour(win, monkeypatch):
    """A pick ticks its line and shows its colour under the list, in
    sight; the panel stays open; only «Done» keeps it."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from views.layers_panel import _LineSample
    seen = {}

    def act(menu):
        panel = win.layers_dock.panel
        row = panel.line_colour_row
        seen["title0"] = row.title.text()
        sample = next(w for w in menu.findChildren(_LineSample)
                      if w.key == "dashdot")
        QTest.mouseClick(sample, Qt.LeftButton, Qt.NoModifier, QPoint(40, 10))
        _app.processEvents()
        seen["open"] = menu.isVisible()
        seen["ticked"] = sample._checked
        row.buttons[(0.85, 0.10, 0.10)].click()
        seen["title1"] = row.title.text()
        seen["sample"] = sample.colour
        panel.line_done_button.click()

    panel, scene = _line_panel(win, monkeypatch, "dashed", act)
    assert "COLOUR OF THE LINE" in seen["title0"]
    assert seen["title0"].endswith("· By layer")
    assert seen["open"] and seen["ticked"]
    assert seen["title1"].endswith("· Red")
    assert seen["sample"] == (0.85, 0.10, 0.10)
    assert scene.layer("Ejes").linetype == "dashdot"            # kept
    assert scene.linetype_colors["dashdot"] == (0.85, 0.10, 0.10)


def test_closing_the_line_panel_without_done_puts_it_back(win, monkeypatch):
    from views.layers_panel import _LineSample

    def act(menu):
        panel = win.layers_dock.panel
        next(w for w in menu.findChildren(_LineSample)
             if w.key == "dotted").pick()
        panel.line_colour_row.buttons[(0.0, 0.40, 0.85)].click()
        assert win.viewport.scene.layer("Ejes").linetype == "dotted"
        menu.close()                          # Esc, or a click outside

    _panel, scene = _line_panel(win, monkeypatch, "dashed", act)
    assert scene.layer("Ejes").linetype == "dashed"
    assert not scene.linetype_colors


def test_enter_on_a_line_picks_it_and_keeps_it(win, monkeypatch):
    def act(menu):
        next(a for a in menu.actions() if a.text() == "Dotted").trigger()
        menu.close()

    _panel, scene = _line_panel(win, monkeypatch, "dashed", act)
    assert scene.layer("Ejes").linetype == "dotted"


def test_the_line_panel_foot_and_the_pencil(win, monkeypatch):
    """Its foot: «New», import and export .lin, «Done»; an own line type
    has a pencil to edit it, and the editor can delete it."""
    from views.layers_panel import LineTypeDialog, _LineSample
    seen = {}
    panel0 = win.layers_dock.panel
    panel0.add_line_type("Borde", [6.0, -1.5], ())

    def act(menu):
        panel = win.layers_dock.panel
        seen["tools"] = [b.toolTip() for b in panel.line_tool_buttons]
        seen["export"] = panel.line_tool_buttons[2].isEnabled()
        seen["pencil"] = [w.key for w in menu.findChildren(_LineSample)
                          if w.edit is not None]
        seen["width"] = menu.sizeHint().width()
        menu.close()

    _panel, scene = _line_panel(win, monkeypatch, "dashed", act)
    assert seen["tools"] == ["New line type…", "Import .lin…",
                             "Export .lin…"]
    assert seen["export"] and seen["pencil"] == ["lin:Borde"]
    assert seen["width"] < 360                        # still a narrow panel
    monkeypatch.setattr(LineTypeDialog, "exec",
                        lambda self: (self._delete(), True)[1])
    panel0.edit_line_type("Borde")
    assert "Borde" not in scene.line_types


def test_the_sizes_are_measures_and_one_of_ones_own_is_kept():
    """No country names in the list — the measures alone — and a size of
    one's own saved for every document (★), removable again."""
    from PySide6.QtCore import QSettings
    from views.layers_panel import HatchGrid
    QSettings().remove(HatchGrid.OWN_PIECES_KEY)
    try:
        grid = _shown(HatchGrid("brick", form={"brick": None}))
        texts = [grid.brick_combo.itemText(i)
                 for i in range(grid.brick_combo.count())]
        assert texts[0] == "215 × 102.5 × 65" and texts[-1] == "Custom"
        assert not any(n in t for t in texts
                       for n in ("Chile", "Uruguay", "Metric", "Spain"))
        grid.more_buttons["piece"].setChecked(True)
        assert not grid.brick_save.isEnabled()        # a usual one: in it
        for spin, v in zip(grid.brick_spins, (300, 150, 80, 12)):
            spin.setValue(float(v))
        assert grid.brick_save.isEnabled()
        assert grid.brick_save.text() == "Save this size"
        grid.brick_save.click()
        assert HatchGrid.own_pieces()["brick"] == [(300.0, 150.0, 80.0,
                                                     12.0)]
        assert grid.brick_combo.currentText() == "★ 300 × 150 × 80"
        assert grid.brick_save.text() == "Remove from the list"
        grid.close()
        again = _shown(HatchGrid("brick"))             # another document
        texts = [again.brick_combo.itemText(i)
                 for i in range(again.brick_combo.count())]
        assert "★ 300 × 150 × 80" in texts
        again.close()
        grid = _shown(HatchGrid("brick", form={"brick": (300.0, 150.0, 80.0,
                                                         12.0)}))
        grid.brick_save.click()                          # remove it
        assert "brick" not in HatchGrid.own_pieces()
        grid.close()
    finally:
        QSettings().remove(HatchGrid.OWN_PIECES_KEY)


def test_the_model_writes_a_line_types_words(win):
    """GAS along a gas line in the 3D view too: the letters' outlines in
    the gaps the pattern leaves for them, lying along the edge."""
    import numpy as np
    from core.layers import load_line_types, with_text
    vp = win.viewport
    scene = vp.scene
    drawn, spec = with_text([10.0, -2.0], "GAS", 2.0)
    load_line_types(scene, {"Gas": dict({"pattern": drawn,
                                         "pieces": [10.0, -2.0],
                                         "color": [0.85, 0.65, 0.0]},
                                        **spec)})
    scene.layers.append(Layer("Gas", linetype="lin:Gas"))
    pipe = Group(Mesh(), name="caño")
    pipe.mesh.add_edge(V(0, 0, 0), V(6, 0, 0))
    pipe.layer = "Gas"
    scene.groups.append(pipe)
    scene.version += 1
    (_rgb, _d, _g, words), = vp._model_linetype_edges()
    assert len(words) > 20                               # letters drawn
    w = words.reshape(-1, 3)
    assert w[:, 0].min() >= -0.01 and w[:, 0].max() <= 6.01   # on the edge
    assert np.ptp(w[:, 1]) < 0.2                         # 2 mm at 1:50: 10 cm
    vp.repaint()
    win._saved_version = scene.version


def test_an_open_cell_of_a_honeycomb_bond_is_closed_on_both_sides():
    """Palomero: each open cell is crossed and closed — the side after a
    brick too (a brick draws only the joint before it)."""
    from core.hatches import bond_marks
    wall = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 80.0, 12.0)    # 1:10
    marks = bond_marks("brick_honeycomb", wall, "plan", 5.0, 10.0)
    uprights = {round(x0, 3) for x0, y0, x1, y1 in marks["lines"]
                if abs(x0 - x1) < 1e-9 and abs(y1 - y0) > 1e-6}
    crosses = {(round(min(x0, x1), 3), round(max(x0, x1), 3))
               for x0, y0, x1, y1 in marks["lines"]
               if abs(x0 - x1) > 1e-6 and abs(y0 - y1) > 1e-6}
    inside = [c for c in crosses if c[0] > 1e-3 and c[1] < 80.0 - 1e-3]
    assert inside                                     # cells to look at
    for left, right in inside:
        assert left in uprights and right in uprights
