# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The stationing example extension (``examples/extensions/progresivas.py``,
in the catalog as «Progresivas»), without a window."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "progresivas_example",
    Path(__file__).resolve().parents[1] / "examples" / "extensions"
    / "progresivas.py")
pg = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pg)


def test_stations_are_written_as_km_plus_metres():
    assert pg.fmt_station(0) == "0+000"
    assert pg.fmt_station(20) == "0+020"
    assert pg.fmt_station(12350) == "12+350"
    assert pg.fmt_station(999.6) == "1+000"
    assert pg.fmt_station(8936.72, 2) == "8+936.72"
    assert pg.fmt_station(999.999, 2) == "1+000.00"


def test_only_the_odd_station_shows_its_centimetres():
    assert pg.label(3200.0) == "3+200"
    assert pg.label(8936.726) == "8+936.73"


def test_a_station_is_read_back():
    assert pg.parse_station("12+350") == 12350.0
    assert pg.parse_station(" 0+020,5 ") == 20.5
    assert pg.parse_station("1500") == 1500.0
    with pytest.raises(ValueError):
        pg.parse_station("km 3")


def test_a_straight_route_gets_a_station_every_interval_and_its_end():
    axis = [(0, 0, 0), (50, 0, 0)]
    marks = pg.stations(axis, 0.0, 20.0)
    assert [m[0] for m in marks] == [0.0, 20.0, 40.0, 50.0]
    assert [m[1][0] for m in marks] == pytest.approx([0, 20, 40, 50])
    assert all(m[2] == pytest.approx((1.0, 0.0)) for m in marks)


def test_marks_fall_on_round_stations_whatever_the_start():
    axis = [(0, 0, 0), (50, 0, 0)]
    marks = pg.stations(axis, 12350.0 + 7.0, 20.0)      # 12+357
    assert [m[0] for m in marks] == pytest.approx(
        [12357.0, 12360.0, 12380.0, 12400.0, 12407.0])
    assert marks[1][1][0] == pytest.approx(3.0)


def test_distance_runs_round_the_corners_and_is_horizontal():
    # 30 east, then 40 north climbing 100 m: the slope adds no station
    axis = [(0, 0, 0), (30, 0, 0), (30, 40, 100)]
    marks = pg.stations(axis, 0.0, 25.0)
    assert [m[0] for m in marks] == pytest.approx([0, 25, 50, 70])
    assert marks[2][1] == pytest.approx((30.0, 20.0, 50.0))
    assert marks[2][2] == pytest.approx((0.0, 1.0))
    assert pg.axis_length(axis) == pytest.approx(70.0)


def test_a_route_ending_on_a_round_station_is_not_marked_twice():
    marks = pg.stations([(0, 0, 0), (40, 0, 0)], 0.0, 20.0)
    assert [m[0] for m in marks] == pytest.approx([0, 20, 40])


def test_loose_edges_are_put_in_order():
    segments = [((10, 0, 0), (20, 0, 0)), ((0, 0, 0), (10, 0, 0)),
                ((30, 5, 0), (20, 0, 0))]
    assert pg.chain_edges(segments) == [
        (0, 0, 0), (10, 0, 0), (20, 0, 0), (30, 5, 0)]


def test_a_fork_a_ring_or_two_pieces_are_refused():
    fork = [((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (2, 0, 0)),
            ((1, 0, 0), (1, 1, 0))]
    ring = [((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (1, 1, 0)),
            ((1, 1, 0), (0, 0, 0))]
    two = [((0, 0, 0), (1, 0, 0)), ((5, 0, 0), (6, 0, 0))]
    for bad in (fork, ring, two):
        with pytest.raises(ValueError):
            pg.chain_edges(bad)


def _scene_with_path(points):
    from core.scene import Scene
    from georef.geopath import GeoPath
    from PySide6.QtGui import QVector3D

    scene = Scene()
    scene.geo_paths.append(GeoPath([QVector3D(*p) for p in points]))
    return scene


def _own(scene):
    return [g for g in scene.groups if pg.KEY in (g.ext or {})]


def test_the_document_gets_one_group_with_its_labels_and_they_are_replaced():
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    marks = pg.build(scene, axis, {"interval": 20.0, "label_every": 100.0})
    assert len(marks) == 14                       # 0, 20 … 240, 250

    (group,) = _own(scene)
    assert group.name == "Progresivas" and group.layer == "Progresivas"
    assert len(group.mesh.edges) == 14 and not group.mesh.faces
    assert scene.layer("Progresivas") is not None
    labels = group.ext[pg.KEY]["labels"]
    assert [row[3] for row in labels] == ["0+000", "0+100", "0+200", "0+250"]
    # nothing of it outside the group: no loose geometry, no annotations
    assert len(scene.loose_mesh.edges) == 0 and not scene.text_labels

    # long ticks at the labelled stations, short ones between
    lengths = sorted(round(e.length(), 6) for e in group.mesh.edges)
    assert lengths[0] == pytest.approx(4.0) and lengths[-1] == pytest.approx(8.0)

    # again, from 5+000 and reversed: replaced, not piled up
    pg.build(scene, axis, {"start": 5000.0, "reverse": True, "prefix": "Km "})
    (group,) = _own(scene)
    first = group.ext[pg.KEY]["labels"][0]
    assert first[3] == "Km 5+000" and first[0] == pytest.approx(250.0)
    assert pg.stored_params(scene)["start"] == 5000.0

    assert pg.remove(scene)
    assert not _own(scene)


def test_the_style_of_the_labels_is_kept_with_the_group():
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"text_size": 14, "text_color": [255, 0, 0],
                           "text_bg": None})
    kept = pg.stored_params(scene)
    assert (kept["text_size"], kept["text_color"], kept["text_bg"]) == (
        14, [255, 0, 0], None)
    import json
    json.dumps(_own(scene)[0].ext)                # saved in the .igz as it is


def test_the_road_is_a_band_of_its_width_and_colour_in_the_group():
    scene = _scene_with_path([(0, 0, 0), (100, 0, 0), (100, 80, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"road": True, "road_width": 6.0,
                           "road_color": [255, 128, 0]})
    (group,) = _own(scene)
    faces = group.mesh.faces
    assert len(faces) == 2
    assert all(f.attrs["color"] == pytest.approx((1.0, 128 / 255, 0.0))
               for f in faces)
    left, right = pg.ribbon(axis, 6.0)
    assert left[0] == pytest.approx((0.0, 3.0))
    assert right[0] == pytest.approx((0.0, -3.0))
    # the corner is mitred: both sides meet on the bisector
    assert left[1] == pytest.approx((97.0, 3.0))
    assert right[1] == pytest.approx((103.0, -3.0))
    # ticks reach past the road's edge
    tick = max(e.length() for e in group.mesh.edges if not e.faces)
    assert tick == pytest.approx(6.0 + 8.0)
    # the joint between the two pieces is not drawn
    assert sum(1 for e in group.mesh.edges if e.soft) == 1


def test_the_route_is_kept_when_the_road_takes_the_path_s_place():
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"road": True})
    scene.geo_paths.clear()                       # the path gave way
    again, name = pg.find_axis(scene)
    assert again == [(0.0, 0.0, 0.0), (250.0, 0.0, 0.0)]
    marks = pg.build(scene, again, {"interval": 50.0})
    assert len(marks) == 6 and len(_own(scene)) == 1


def test_crowded_labels_give_way_to_the_round_ones():
    boxes = [(0, 0, 50, 10), (40, 0, 50, 10), (80, 0, 50, 10), (200, 0, 50, 10)]
    ranks = [pg.rank(100.0), pg.rank(1000.0), pg.rank(1100.0), pg.rank(1300.0)]
    assert sorted(pg.thin_out(boxes, ranks)) == [1, 3]
    assert [pg.rank(s) for s in (3000, 3500, 3200, 3220)] == [0, 1, 2, 3]


def test_the_csv_lists_every_station():
    from core.scene import Scene

    marks = pg.stations([(0, 0, 0), (40, 0, 0)], 0.0, 20.0)
    rows = pg.csv_rows(Scene(), marks)
    assert len(rows) == 4 and rows[1][0] == "0+000" and rows[3][0] == "0+040"
    assert math.isclose(float(rows[2][2]), 20.0)


# ---- stations edited one by one ---------------------------------------------

def _labels(scene):
    return {row[6]: row for row in _own(scene)[0].ext[pg.KEY]["labels"]}


def test_one_station_takes_a_text_a_colour_and_loses_its_stake():
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"overrides": {
        "100.000": {"text": "Bridge", "text_color": [200, 0, 0]},
        "40.000": {"label": True},                  # a minor one, shown
        "200.000": {"label": False},                # a major one, hidden
        "60.000": {"stake": False},
        "80.000": {"tick": 10.0}}})
    labels = _labels(scene)
    assert labels["100.000"][3] == "Bridge"
    assert labels["100.000"][5] == {"text_color": [200, 0, 0]}
    assert labels["100.000"][4] == -1               # the last to give way
    assert labels["40.000"][3] == "0+040" and labels["40.000"][5] is None
    assert "200.000" not in labels
    (group,) = _own(scene)
    assert len(group.mesh.edges) == 13              # 14 stations, one bare
    assert max(e.length() for e in group.mesh.edges) == pytest.approx(20.0)


def test_a_stake_of_colour_is_a_bar_with_no_outline():
    scene = _scene_with_path([(0, 0, 0), (40, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"stake_width": 1.0, "overrides": {
        "20.000": {"stake_color": [255, 0, 0]}}})
    (group,) = _own(scene)
    (bar,) = group.mesh.faces
    assert bar.attrs["color"] == pytest.approx((1.0, 0.0, 0.0))
    assert sorted(e.hidden for e in group.mesh.edges) == [False] * 3 + [True] * 4
    # every stake of that colour when it is the general setting
    pg.build(scene, axis, {"stake_color": [0, 0, 255], "overrides": {}})
    assert len(_own(scene)[0].mesh.faces) == 3


def test_edits_outlive_a_new_generation_until_they_are_dropped():
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"overrides": {"100.000": {"text": "Bridge"}}})
    pg.build(scene, axis, {"text_size": 14})        # the dialog, again
    assert _labels(scene)["100.000"][3] == "Bridge"
    assert pg.stored_overrides(scene) == {"100.000": {"text": "Bridge"}}
    pg.build(scene, axis, {"overrides": {}})
    assert _labels(scene)["100.000"][3] == "0+100"


class _FakeViewport:
    def __init__(self, scene):
        from core.history import History
        self.scene = scene
        self.history = History(scene)
        self.changed = []

    def notify_scene_changed(self):
        for fn in self.changed:
            fn()

    def update(self):
        pass


class _FakeApp:
    def __init__(self, viewport):
        self.viewport = viewport
        self.shown = 0

    @property
    def scene(self):
        return self.viewport.scene

    def show_panel(self, dock):
        self.shown += 1


@pytest.fixture
def panel():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {})
    viewport = _FakeViewport(scene)
    panel = pg._Panel(_FakeApp(viewport))
    panel.dock = object()
    viewport.changed.append(panel.refresh)
    return panel


def _pick(panel, *keys):
    panel.table.clearSelection()
    for n in range(panel.table.rowCount()):
        if panel.table.item(n, 0).data(0x0100) in keys:
            panel._add_row_to_selection(n)


def test_the_panel_lists_the_stations_and_edits_the_picked_ones(panel):
    scene = panel.app.scene
    assert panel.table.rowCount() == 14
    assert panel.table.item(5, 1).text() == "0+100"
    assert panel.table.item(1, 1).text() == "—"
    assert not panel.box.isEnabled()

    _pick(panel, "100.000")
    assert panel.box.isEnabled() and panel.show_label.isChecked()
    assert panel.highlight == [pytest.approx((100.0, 0.0, pg.TICK_LIFT))]
    panel.text.setText("Bridge")
    panel._text_edited()
    assert _labels(scene)["100.000"][3] == "Bridge"
    # the list follows, and the station stays picked for the next edit
    assert panel.table.item(5, 1).text() == "Bridge"
    assert panel._keys() == ["100.000"] and panel.text.text() == "Bridge"
    panel.text_color.changed.emit([255, 0, 0])
    assert _labels(scene)["100.000"][5] == {"text_color": [255, 0, 0]}

    # a text typed on a station without label shows that label
    _pick(panel, "20.000")
    assert not panel.show_label.isChecked()
    panel.text.setText("Culvert")
    panel._text_edited()
    assert _labels(scene)["20.000"][3] == "Culvert"

    # several at once
    _pick(panel, "40.000", "60.000")
    panel._stake_toggled(False)
    assert len(_own(scene)[0].mesh.edges) == 12
    assert pg.stored_overrides(scene)["60.000"] == {"stake": False}

    # showing a label that shows by itself is no edit
    _pick(panel, "200.000")
    panel._label_toggled(False)
    assert "200.000" not in _labels(scene)
    panel._label_toggled(True)
    assert "200.000" not in pg.stored_overrides(scene)

    # each edit is one undo step
    panel.app.viewport.history.undo()
    panel.refresh()
    assert "200.000" not in _labels(scene)

    panel.only.setChecked(True)
    assert panel.table.rowCount() == 7       # 0 20 40 60 100 200 250
    panel._restore_all()
    assert pg.stored_overrides(scene) == {}
    assert _labels(scene)["100.000"][3] == "0+100"


def test_a_label_clicked_in_the_view_picks_its_station(panel):
    from PySide6.QtCore import QRectF

    viewport = panel.app.viewport
    pg._drawn[id(viewport)] = [(QRectF(10, 10, 50, 20), "100.000")]
    assert pg.pick_label(viewport, 30, 20) == "100.000"
    assert pg.pick_label(viewport, 300, 20) is None
    panel.select_key("100.000")
    assert panel._keys() == ["100.000"] and panel.app.shown == 1
    panel.select_key(None)                   # let go: the editor stays on it
    assert panel._keys() == ["100.000"]
    # Supr on it hides the label, the stake stays
    pg.apply_overrides(viewport, {"100.000": {"label": False}})
    assert "100.000" not in _labels(panel.app.scene)
    assert len(_own(panel.app.scene)[0].mesh.edges) == 14


def test_a_label_is_written_in_its_cell_and_a_stake_unticked_in_the_list(panel):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    scene = panel.app.scene
    panel.table.item(1, 1).setText("Culvert")        # 0+020 had no label
    QApplication.processEvents()
    assert _labels(scene)["20.000"][3] == "Culvert"
    assert panel.table.item(1, 1).text() == "Culvert"
    panel.table.item(1, 1).setText("")               # emptied: gone again
    QApplication.processEvents()
    assert "20.000" not in _labels(scene)
    assert pg.stored_overrides(scene) == {}
    panel.table.item(5, 1).setText("")               # 0+100 shows by itself
    QApplication.processEvents()
    assert "100.000" not in _labels(scene)
    panel.table.item(5, 1).setText("0+100")          # written back: no edit
    QApplication.processEvents()
    assert pg.stored_overrides(scene) == {}

    panel.table.item(2, 2).setCheckState(Qt.Unchecked)
    QApplication.processEvents()
    assert pg.stored_overrides(scene) == {"40.000": {"stake": False}}
    assert len(_own(scene)[0].mesh.edges) == 13
    assert panel.table.item(2, 2).checkState() == Qt.Unchecked


def test_labels_written_on_the_ground_are_geometry_of_the_group():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])     # fonts need it

    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"ground_text": True, "ground_text_height": 8.0,
                           "text_color": [255, 0, 0], "text_bg": None,
                           "tick": 4.0})
    (group,) = _own(scene)
    faces = group.mesh.faces
    assert len(faces) >= 4 * 5                      # four labels, five signs
    assert all(f.attrs["color"] == pytest.approx((1.0, 0.0, 0.0))
               for f in faces)
    assert all(f.normal().z() > 0.99 for f in faces)     # they face up
    # only the 14 stakes are drawn as lines: letters are colour alone
    assert sum(1 for e in group.mesh.edges if not e.hidden) == 14
    # the first label: on the left of the route (north), clear of the stake,
    # 8 m tall, read from below (bottom to top on a north-up plan)
    ys = [v.y() for f in faces for v in f.outer_positions()] \
        if hasattr(faces[0], "outer_positions") else \
        [e.v0.position.y() for e in group.mesh.edges if e.hidden]
    assert min(ys) > 4.0
    xs = [e.v0.position.x() for e in group.mesh.edges
          if e.hidden and e.v0.position.x() < 50]
    assert max(xs) - min(xs) == pytest.approx(8.0, abs=0.01)

    # with a background, one more face under each label
    pg.build(scene, axis, {"ground_text": True, "text_bg": [255, 255, 255]})
    assert len(_own(scene)[0].mesh.faces) == len(faces) + 4


class _FlatView:
    """A plan view, north up: one metre is one pixel, y grows downwards."""

    def __init__(self, scene):
        self.scene = scene

    def width(self):
        return 1000

    def height(self):
        return 1000

    def world_to_pixels(self, points):
        import numpy as np
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        return pts[:, 0] + 100.0, 500.0 - pts[:, 1], np.ones(len(pts), bool)


def _painted(scene, **params):
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"label_every": 1000.0, "tick": 10.0, **params})
    view = _FlatView(scene)
    image = QImage(1000, 1000, QImage.Format_ARGB32)
    painter = QPainter(image)
    pg.draw_labels(view, painter)
    painter.end()
    return {key: rect for rect, key in pg._drawn[id(view)]}


def test_a_label_lies_in_line_with_its_stake_along_the_road_or_level():
    # a route running east: stakes run north-south, labels go on the north
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    stake = _painted(scene, label_align="stake")["0.000"]
    # standing: taller than wide, centred on the stake, starting past its end
    assert stake.height() > stake.width() * 1.5
    assert stake.center().x() == pytest.approx(100.0, abs=0.5)
    assert stake.bottom() == pytest.approx(500.0 - 15.0, abs=0.5)
    road = _painted(scene, label_align="road")["0.000"]
    assert road.width() > road.height() * 1.5
    assert road.center().y() == pytest.approx(500.0 - 15.0, abs=0.5)
    level = _painted(scene, label_align="horizontal")["0.000"]
    assert level.width() == pytest.approx(road.width())
    # labels on the other side hang from the stake's other end
    below = _painted(scene, label_align="stake", side="right")["0.000"]
    assert below.top() == pytest.approx(500.0 + 15.0, abs=0.5)


def test_ground_labels_follow_the_same_choice():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)

    def extent(align):
        pg.build(scene, axis, {"ground_text": True, "text_bg": None,
                               "label_every": 1000.0, "label_align": align})
        pts = [e.v0.position for e in _own(scene)[0].mesh.edges
               if e.hidden and e.v0.position.x() < 100]
        return (max(p.x() for p in pts) - min(p.x() for p in pts),
                max(p.y() for p in pts) - min(p.y() for p in pts))

    wide, tall = extent("stake")
    assert wide == pytest.approx(8.0, abs=0.01) and tall > 12.0
    wide, tall = extent("road")
    assert tall == pytest.approx(8.0, abs=0.01) and wide > 12.0


def test_the_sheets_get_the_labels_as_on_screen():
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"text_bg": [255, 255, 0], "text_bg_opacity": 40,
                           "sheet_text_mm": 3.0, "label_align": "stake"})
    items = pg.sheet_labels(scene, None)
    labels = _own(scene)[0].ext[pg.KEY]["labels"]
    assert [it["text"] for it in items] == [row[3] for row in labels]
    first = items[0]
    assert first["at"] == tuple(labels[0][:3]) and first["size_mm"] == 3.0
    assert first["background"] == (255, 255, 0)
    assert first["background_opacity"] == 40
    assert first["anchor"] == "start"
    # it runs out along the stake, away from the route (north, on the left)
    assert first["toward"][1] > first["at"][1]
    assert first["toward"][0] == pytest.approx(first["at"][0])
    # the same order of giving way as on screen
    assert [it["priority"] for it in items] == [row[4] for row in labels]

    pg.build(scene, axis, {"label_align": "horizontal", "text_bg": None})
    items = pg.sheet_labels(scene, None)
    assert all("toward" not in it and "background" not in it for it in items)


def test_labels_on_the_ground_are_not_printed_twice():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])     # fonts need it
    scene = _scene_with_path([(0, 0, 0), (250, 0, 0)])
    axis, _name = pg.find_axis(scene)
    pg.build(scene, axis, {"ground_text": True})
    assert pg.sheet_labels(scene, None) == []
