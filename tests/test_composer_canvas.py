# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Two-point placement on the composer canvas: the sheet tools accept BOTH a
drag and click-move-click (the model's dimension-tool habit), snapping every
point. The dimension tool adds a THIRD click that pulls the dimension line
away from the measured points (LayOut-style ``sep_mm``). A bare click with a
two-point tool must NOT place a zero-size item — that was 'the second point
never snaps': the first release placed a zero cota and silently disarmed the
tool."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.composition import (Cajetin, Composicion, CotaItem,   # noqa: E402
                              FormaItem, MarcoVista)
from views.composer import ComposerCanvasView, ComposerWindow   # noqa: E402


class _StubComposer:
    """Just enough of ComposerWindow for the canvas view: a tool mode, a
    snap oracle, and a recorder for place_tool."""
    TOOLS = ComposerWindow.TOOLS

    def __init__(self, mode="linea"):
        self.tool_mode = mode
        self.placed = []
        self.anchors = []
        self.snap_at = None    # full (x, y, world, frame) hit, or None

    def nearest_snap_point(self, x, y, thr):
        return self.snap_at

    def update_cursor_label(self, x, y):
        pass

    def place_tool(self, x0, y0, x1, y1, sep_mm=0.0, anchors=None):
        self.placed.append((x0, y0, x1, y1, sep_mm))
        self.anchors.append(anchors)
        self.tool_mode = "select"


def _view(mode="linea"):
    composer = _StubComposer(mode)
    canvas = QGraphicsScene()
    view = ComposerCanvasView(canvas, composer)
    view._canvas_ref = canvas          # the view does not own the scene
    view.resize(400, 300)
    return view, composer


def _mouse(view, etype, px, py, button=Qt.LeftButton,
           buttons=Qt.NoButton, mods=Qt.NoModifier):
    pos = QPointF(px, py)
    ev = QMouseEvent(etype, pos, pos, button, buttons, mods)
    if etype == QEvent.MouseButtonPress:
        view.mousePressEvent(ev)
    elif etype == QEvent.MouseMove:
        view.mouseMoveEvent(ev)
    else:
        view.mouseReleaseEvent(ev)


def _click(view, px, py):
    _mouse(view, QEvent.MouseButtonPress, px, py)
    _mouse(view, QEvent.MouseButtonRelease, px, py)


def _scene_xy(view, px, py):
    p = view.mapToScene(QPoint(px, py))
    return p.x(), p.y()


class TestClickMoveClick:
    def test_two_clicks_place_one_item(self):
        view, comp = _view()
        _mouse(view, QEvent.MouseButtonPress, 50, 50)
        _mouse(view, QEvent.MouseButtonRelease, 51, 50)      # same spot: click
        assert comp.placed == []                             # still armed
        _mouse(view, QEvent.MouseMove, 100, 80)
        _mouse(view, QEvent.MouseButtonPress, 150, 90)
        assert len(comp.placed) == 1
        x0, y0, x1, y1, _sep = comp.placed[0]
        assert (x0, y0) == pytest.approx(_scene_xy(view, 50, 50))
        assert (x1, y1) == pytest.approx(_scene_xy(view, 150, 90))
        # the release of the finishing click must not start a new placement
        _mouse(view, QEvent.MouseButtonRelease, 150, 90)
        assert len(comp.placed) == 1

    def test_drag_still_places(self):
        view, comp = _view()
        _mouse(view, QEvent.MouseButtonPress, 40, 40)
        _mouse(view, QEvent.MouseMove, 120, 60, buttons=Qt.LeftButton)
        _mouse(view, QEvent.MouseButtonRelease, 120, 60)
        assert len(comp.placed) == 1
        x0, y0, x1, y1, _sep = comp.placed[0]
        assert (x0, y0) == pytest.approx(_scene_xy(view, 40, 40))
        assert (x1, y1) == pytest.approx(_scene_xy(view, 120, 60))

    def test_second_click_on_the_first_point_keeps_waiting(self):
        view, comp = _view()
        _click(view, 50, 50)
        _click(view, 51, 51)                                 # < 4 px away
        assert comp.placed == []                             # no zero-size item

    def test_snap_applies_to_both_points(self):
        view, comp = _view()
        comp.snap_at = (10.0, 20.0)
        _click(view, 50, 50)
        comp.snap_at = (90.0, 20.0)
        _mouse(view, QEvent.MouseButtonPress, 150, 90)
        assert comp.placed[0][:4] == (10.0, 20.0, 90.0, 20.0)

    def test_escape_cancels_the_pending_placement(self):
        view, comp = _view()
        _click(view, 50, 50)
        view.cancel_placement()
        _click(view, 150, 90)                                # a fresh first click
        assert comp.placed == []                             # armed, waiting

    def test_point_tools_place_on_a_single_click(self):
        view, comp = _view("texto")
        _click(view, 70, 70)
        assert len(comp.placed) == 1


class TestCotaSepPhase:
    def test_third_click_sets_the_separation(self):
        view, comp = _view("cota")
        _click(view, 50, 50)                                 # first point
        _click(view, 150, 50)                                # second point
        assert comp.placed == []                             # sep phase now
        _mouse(view, QEvent.MouseMove, 100, 90)
        _mouse(view, QEvent.MouseButtonPress, 100, 80)       # third click
        assert len(comp.placed) == 1
        x0, y0, x1, y1, sep = comp.placed[0]
        assert (x0, y0) == pytest.approx(_scene_xy(view, 50, 50))
        assert (x1, y1) == pytest.approx(_scene_xy(view, 150, 50))
        assert sep == pytest.approx(30.0)                    # 80 - 50, along +n
        _mouse(view, QEvent.MouseButtonRelease, 100, 80)
        assert len(comp.placed) == 1

    def test_drag_then_click_also_works(self):
        view, comp = _view("cota")
        _mouse(view, QEvent.MouseButtonPress, 50, 50)
        _mouse(view, QEvent.MouseMove, 150, 50, buttons=Qt.LeftButton)
        _mouse(view, QEvent.MouseButtonRelease, 150, 50)     # points fixed
        assert comp.placed == []
        _mouse(view, QEvent.MouseButtonPress, 100, 20)       # pull the line up
        assert len(comp.placed) == 1
        assert comp.placed[0][4] == pytest.approx(-30.0)

    def test_sep_phase_ignores_snapping(self):
        view, comp = _view("cota")
        _click(view, 50, 50)
        _click(view, 150, 50)
        comp.snap_at = (999.0, 999.0)                        # must NOT bite
        _mouse(view, QEvent.MouseButtonPress, 100, 75)
        assert comp.placed[0][4] == pytest.approx(25.0)

    def test_escape_cancels_the_sep_phase(self):
        view, comp = _view("cota")
        _click(view, 50, 50)
        _click(view, 150, 50)
        view.cancel_placement()
        _click(view, 100, 80)                                # fresh first click
        assert comp.placed == []


class TestCotaAnchoring:
    def test_both_points_snapped_same_frame_anchor_the_cota(self):
        view, comp = _view("cota")
        frame = MarcoVista(scale_n=100.0)
        comp.snap_at = (30.0, 40.0, (0.0, 0.0, 0.0), frame)
        _click(view, 50, 50)
        comp.snap_at = (90.0, 40.0, (6.0, 0.0, 0.0), frame)
        _click(view, 150, 50)
        comp.snap_at = None
        _mouse(view, QEvent.MouseButtonPress, 100, 80)       # sep click
        assert comp.anchors == [((frame, (0.0, 0.0, 0.0), (6.0, 0.0, 0.0)))]

    def test_points_on_different_frames_do_not_anchor(self):
        view, comp = _view("cota")
        comp.snap_at = (30.0, 40.0, (0.0, 0.0, 0.0), MarcoVista())
        _click(view, 50, 50)
        comp.snap_at = (90.0, 40.0, (6.0, 0.0, 0.0), MarcoVista())
        _click(view, 150, 50)
        comp.snap_at = None
        _mouse(view, QEvent.MouseButtonPress, 100, 80)
        assert comp.anchors == [None]

    def test_unsnapped_points_do_not_anchor(self):
        view, comp = _view("cota")
        _click(view, 50, 50)
        _click(view, 150, 50)
        _mouse(view, QEvent.MouseButtonPress, 100, 80)
        assert comp.anchors == [None]


class _FakeReprojector:
    """The reprojection logic with a hand-made front-view page mapping
    (world x → page x, world z → page y) — no GL, no MainWindow."""

    def __init__(self, comp, world_pts):
        import numpy as np
        self.comp = comp
        self._world = np.asarray(world_pts, dtype=float)

    def frame_snap_points(self, frame):
        import numpy as np
        return np.empty((0, 2)), self._world

    def _frame_world_to_page(self, frame, pts):
        from core.composition import model_height_for_frame
        model_h = model_height_for_frame(frame.h_mm, frame.scale_n)
        k = frame.h_mm / model_h
        half_h = model_h / 2.0
        half_w = half_h * (frame.w_mm / frame.h_mm)
        return [(frame.x_mm + (x + half_w) * k,
                 frame.y_mm + (half_h - z) * k) for x, _y, z in pts]

    def reproject(self):
        ComposerWindow._reproject_anchored_cotas(self)


class TestReprojection:
    def _setup(self, moved_to):
        comp = Composicion()
        frame = MarcoVista(x_mm=10.0, y_mm=10.0, w_mm=200.0, h_mm=150.0,
                           scale_n=100.0, uid="f1")
        comp.frames = [frame]
        ct = CotaItem(scale_n=100.0, anchor_uid="f1",
                      a_world=[0.0, 0.0, 0.0], b_world=[6.0, 0.0, 0.0])
        comp.cotas = [ct]
        fake = _FakeReprojector(comp, [[0.0, 0.0, 0.0], list(moved_to)])
        fake.reproject()
        return frame, ct

    def test_moved_vertex_within_tolerance_drags_the_cota(self):
        # the wall corner moved 6.00 → 6.10 m; tolerance at 1:100 is 0.25 m
        _frame, ct = self._setup((6.1, 0.0, 0.0))
        assert ct.b_world == pytest.approx([6.1, 0.0, 0.0])
        assert ct.real_distance_m() == pytest.approx(6.1)
        assert ct.dx_mm == pytest.approx(61.0)               # 6.1 m at 1:100

    def test_far_vertex_keeps_the_stored_anchor(self):
        _frame, ct = self._setup((9.0, 0.0, 0.0))            # 3 m away
        assert ct.b_world == pytest.approx([6.0, 0.0, 0.0])
        assert ct.real_distance_m() == pytest.approx(6.0)

    def test_page_position_follows_the_frame(self):
        frame, ct = self._setup((6.0, 0.0, 0.0))
        x0 = ct.x_mm
        frame.x_mm += 25.0                                   # frame dragged
        comp = Composicion()
        comp.frames = [frame]
        comp.cotas = [ct]
        _FakeReprojector(comp, [[0.0, 0.0, 0.0],
                                [6.0, 0.0, 0.0]]).reproject()
        assert ct.x_mm == pytest.approx(x0 + 25.0)

    def test_anchor_fields_survive_the_dict_round_trip(self):
        comp = Composicion()
        comp.frames = [MarcoVista(uid="f9")]
        comp.cotas = [CotaItem(anchor_uid="f9",
                               a_world=[1.0, 2.0, 3.0],
                               b_world=[4.0, 5.0, 6.0])]
        again = Composicion.from_dict(comp.to_dict())
        ct = again.cotas[0]
        assert again.frames[0].uid == "f9"
        assert ct.anchor_uid == "f9"
        assert ct.a_world == [1.0, 2.0, 3.0]
        assert ct.anchored


class _FakeViewport:
    """A GL-free stand-in: the composer only needs scene, camera, update."""

    def __init__(self):
        from core.camera import OrbitCamera
        from core.scene import Scene
        self.scene = Scene()
        self.camera = OrbitCamera()

    def update(self):
        pass


class TestAnchoredEndToEnd:
    """Real ComposerWindow + real Scene + real HLR: an anchored cota follows
    an edited wall through the whole pipeline (snap → anchor → reproject)."""

    def _composer(self):
        from PySide6.QtGui import QVector3D
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        host.viewport = _FakeViewport()
        V = QVector3D
        # a 6×3 m façade in the XZ plane (what std:front looks at)
        host.viewport.scene.mesh.add_face(
            [V(0, 0, 0), V(6, 0, 0), V(6, 0, 3), V(0, 0, 3)])
        composer = ComposerWindow(host)
        frame = composer.comp.frames[0]
        frame.view_key = "std:front"
        frame.scale_n = 100.0
        composer.snap_cache.clear()
        self._host = host              # keep the parent alive
        return composer, frame

    def test_cota_follows_the_edited_wall(self):
        composer, frame = self._composer()
        _pts, wpts = composer.frame_snap_points(frame)
        assert len(wpts) > 0           # the façade is visible to the snapper
        composer.tool_mode = "cota"
        composer.place_tool(30.0, 100.0, 90.0, 100.0, sep_mm=6.0,
                            anchors=(frame, (0.0, 0.0, 0.0),
                                     (6.0, 0.0, 0.0)))
        ct = composer.comp.cotas[0]
        assert ct.anchored and frame.uid
        assert ct.real_distance_m() == pytest.approx(6.0)

        # stretch the wall: every vertex at x=6 moves to x=6.2 (within the
        # 0.25 m re-snap tolerance at 1:100)
        for v in composer._scene().mesh.vertices:
            if abs(v.position.x() - 6.0) < 1e-9:
                v.position.setX(6.2)
        # the cota follows when the drawing does: refreshing the frames
        # drops the geometry caches; the rebuild then reprojects
        composer._invalidate_geometry_caches()
        composer._rebuild_canvas()

        assert ct.b_world[0] == pytest.approx(6.2)
        assert ct.real_distance_m() == pytest.approx(6.2)
        assert ct.label() == "6.20 m"
        # and on paper the cota grew with it: 6.2 m at 1:100 = 62 mm
        import math
        assert math.hypot(ct.dx_mm, ct.dy_mm) == pytest.approx(62.0)

    def test_free_cota_is_left_alone(self):
        composer, frame = self._composer()
        composer.tool_mode = "cota"
        composer.place_tool(30.0, 100.0, 90.0, 100.0)        # no anchors
        ct = composer.comp.cotas[0]
        before = (ct.x_mm, ct.y_mm, ct.dx_mm, ct.dy_mm)
        composer._rebuild_canvas()
        assert (ct.x_mm, ct.y_mm, ct.dx_mm, ct.dy_mm) == before
        assert not ct.anchored


class TestArrangeAndLock:
    """QGIS-style stacking and locking: a border rectangle goes to the
    back, the legend rides on top, and a locked item cannot be dragged."""

    def _composer(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        self._host = host
        return composer

    @staticmethod
    def _handle(model):
        import types
        return types.SimpleNamespace(model=model)

    def _order(self, composer):
        return sorted(composer.comp.all_items(),
                      key=lambda m: getattr(m, "z", 0.0))

    def test_new_items_land_on_top(self):
        composer = self._composer()
        composer.tool_mode = "rect"
        composer.place_tool(10, 10, 100, 80)
        composer.tool_mode = "texto"
        composer.place_tool(20, 20, 20, 20)
        rect, text = composer.comp.shapes[0], composer.comp.texts[0]
        frame = composer.comp.frames[0]
        assert frame.z < rect.z < text.z

    def test_send_to_back_and_bring_to_front(self):
        composer = self._composer()
        composer.tool_mode = "rect"
        composer.place_tool(10, 10, 100, 80)         # the page border
        composer.tool_mode = "texto"
        composer.place_tool(20, 20, 20, 20)
        rect = composer.comp.shapes[0]
        composer.z_shift(self._handle(rect), "back")
        assert self._order(composer)[0] is rect      # under the frame too
        composer.z_shift(self._handle(rect), "front")
        assert self._order(composer)[-1] is rect
        composer.history.undo()
        composer.history.undo()
        assert self._order(composer)[1] is rect      # back where it started

    def test_raise_and_lower_are_single_steps(self):
        composer = self._composer()
        for i in range(3):
            composer.tool_mode = "rect"
            composer.place_tool(10 + i, 10, 50, 50)
        a, b, c = composer.comp.shapes
        composer.z_shift(self._handle(a), "raise")   # a jumps over b only
        order = self._order(composer)
        assert order.index(b) < order.index(a) < order.index(c)
        composer.z_shift(self._handle(a), "lower")
        order = self._order(composer)
        assert order.index(a) < order.index(b) < order.index(c)

    def test_lock_freezes_the_canvas_item(self):
        from PySide6.QtWidgets import QGraphicsItem
        composer = self._composer()
        composer.tool_mode = "rect"
        composer.place_tool(10, 10, 100, 80)
        rect = composer.comp.shapes[0]
        composer.toggle_lock(self._handle(rect))
        assert rect.locked
        composer._rebuild_canvas()
        it = next(i for i in composer.canvas.items()
                  if getattr(i, "model", None) is rect)
        assert not (it.flags() & QGraphicsItem.ItemIsMovable)
        # locked = out of the mouse's reach on the canvas (2026-09-07); the
        # panel's Items list is the door, through force_select
        from PySide6.QtCore import Qt as _Qt
        assert not (it.flags() & QGraphicsItem.ItemIsSelectable)
        assert it.acceptedMouseButtons() == _Qt.NoButton
        it.force_select()
        assert it.isSelected()
        composer.toggle_lock(self._handle(rect))
        assert not rect.locked

    def test_z_and_locked_survive_the_dict_round_trip(self):
        comp = Composicion()
        comp.shapes = [FormaItem(z=-1.0, locked=True)]
        again = Composicion.from_dict(comp.to_dict())
        assert again.shapes[0].z == -1.0
        assert again.shapes[0].locked is True


class TestShapesAndCajetin:
    def test_polygon_places_with_default_sides(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        composer.tool_mode = "poligono"
        composer.place_tool(10, 10, 60, 60)
        self._host = host
        f = composer.comp.shapes[0]
        assert f.kind == "poligono" and f.sides == 6

    def test_forma_style_fields_round_trip(self):
        comp = Composicion()
        comp.shapes = [FormaItem(kind="rect", radius_mm=4.0, fill=True,
                                 fill_color="#ffcc00", color="#c6262e",
                                 sides=8)]
        again = Composicion.from_dict(comp.to_dict())
        f = again.shapes[0]
        assert (f.radius_mm, f.fill_color, f.color, f.sides) == \
            (4.0, "#ffcc00", "#c6262e", 8)

    def test_old_cajetin_migrates_to_campos(self):
        c = Cajetin(**{"x_mm": 1.0, "y_mm": 2.0, "w_mm": 180.0,
                       "h_mm": 33.0, "proyecto": "Plaza", "autor": "Marco",
                       "fecha": "", "escala": "1:100", "lamina": "L-01"})
        assert ["PROYECTO", "Plaza"] in c.campos
        assert ["ESCALA", "1:100"] in c.campos
        assert len(c.campos) == 5

    def test_cajetin_set_field_and_new_rows(self):
        c = Cajetin()
        c.set_field("LÁMINA", "L-07")
        assert ["LÁMINA", "L-07"] in c.campos
        c.set_field("DISTRITO", "Yanque")          # a NEW custom row
        assert c.campos[-1] == ["DISTRITO", "Yanque"]
        from dataclasses import asdict
        again = Cajetin(**asdict(c))
        assert ["DISTRITO", "Yanque"] in again.campos
        assert again.border_mm == 0.5 and again.line_mm == 0.2

    def test_long_values_wrap_and_shrink_to_their_cell(self):
        from PySide6.QtCore import QRectF
        from views.composer import _fit_text_size_mm
        cell = QRectF(0, 0, 100.0, 5.6)          # one 180×33 cajetin row
        short = _fit_text_size_mm("Casa Quinta", cell, 3.4)
        assert short == pytest.approx(3.4)        # fits at base size
        long_name = ("MEJORAMIENTO Y AMPLIACIÓN DEL SERVICIO DE AGUA "
                     "POTABLE Y SANEAMIENTO EN LA LOCALIDAD DE YANQUE, "
                     "DISTRITO DE YANQUE, PROVINCIA DE CAYLLOMA")
        fitted = _fit_text_size_mm(long_name, cell, 3.4)
        assert 1.0 <= fitted < 3.4                # wrapped + shrunk, no clip
        one_word = "PALABRALARGUISIMASINESPACIOSQUEDEBEENCOGERSE"
        narrow = QRectF(0, 0, 40.0, 5.6)         # narrow cell: must shrink
        assert _fit_text_size_mm(one_word, narrow, 3.4) < 3.4

    def test_cajetin_paint_smoke_all_layouts(self):
        from PySide6.QtGui import QImage, QPainter
        from views.composer import paint_cajetin_mm, paint_forma_mm
        img = QImage(400, 300, QImage.Format_RGB32)
        p = QPainter(img)
        c = Cajetin(columns=2, border_mm=1.0, line_mm=0.1)
        c.set_field("DISTRITO", "Yanque")
        paint_cajetin_mm(p, c)
        for f in (FormaItem(kind="rect", radius_mm=5.0, fill=True),
                  FormaItem(kind="poligono", sides=8, fill=True),
                  FormaItem(kind="poligono", sides=3)):
            paint_forma_mm(p, f)
        p.end()


class TestCajetinResize:
    def test_panel_width_height_resize_the_title_block(self):
        from PySide6.QtWidgets import QWidget
        from views.composer import CajetinItem
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        composer._on_add_cajetin()
        composer._rebuild_canvas()
        it = next(i for i in composer.canvas.items()
                  if isinstance(i, CajetinItem))
        it.setSelected(True)                     # panel adopts the cajetin
        composer.caj_w.setValue(220.0)
        composer.caj_h.setValue(50.0)
        c = composer.comp.cajetin
        assert (c.w_mm, c.h_mm) == (220.0, 50.0)
        composer.history.undo()
        assert c.w_mm != 220.0 or c.h_mm != 50.0
        self._host = host

    def test_corner_handle_still_resizes_by_drag(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtWidgets import QWidget
        from views.composer import CajetinItem
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        composer._on_add_cajetin()
        composer._rebuild_canvas()
        it = next(i for i in composer.canvas.items()
                  if isinstance(i, CajetinItem))
        m = it.model
        assert it._on_resize_handle(QPointF(m.w_mm, m.h_mm))
        self._host = host


class TestZoomCombo:
    """The QGIS-style zoom combo: fit modes, presets and typed percents."""

    def _composer(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        composer.resize(1000, 700)
        composer._view.resize(800, 600)
        self._host = host
        return composer

    def test_set_zoom_and_readback(self):
        composer = self._composer()
        composer.set_zoom(100.0)
        assert composer.zoom_percent() == pytest.approx(100.0)
        assert composer._zoom_combo.currentText() == "100.0%"
        composer.set_zoom(12.5)
        assert composer.zoom_percent() == pytest.approx(12.5)

    def test_typed_percentage_applies(self):
        composer = self._composer()
        composer._zoom_combo.lineEdit().setText("37%")
        composer._on_zoom_typed()
        assert composer.zoom_percent() == pytest.approx(37.0)

    def test_fit_width_fills_the_viewport(self):
        composer = self._composer()
        composer.zoom_fit_width()
        pw, _ph = composer.comp.page_size_mm()
        scale = composer._view.transform().m11()
        vw = composer._view.viewport().width()
        assert scale * (pw + 10.0) == pytest.approx(vw, rel=0.02)

    def test_fit_page_shows_the_whole_page(self):
        composer = self._composer()
        composer.set_zoom(400.0)
        composer.zoom_fit_page()
        pw, ph = composer.comp.page_size_mm()
        vp = composer._view.viewport()
        m11 = composer._view.transform().m11()
        # the visible span covers the whole page in both axes (absolute
        # centring is unreliable in offscreen layouts — span is what counts)
        assert vp.width() / m11 >= pw
        assert vp.height() / m11 >= ph

    def test_garbage_input_keeps_the_current_zoom(self):
        composer = self._composer()
        composer.set_zoom(50.0)
        composer._zoom_combo.lineEdit().setText("hola")
        composer._on_zoom_typed()
        assert composer.zoom_percent() == pytest.approx(50.0)


class TestReleaseReviewRegressions:
    """The five verified findings of the 0.3 pre-release review."""

    def test_rebuild_mid_placement_does_not_crash(self):
        # Undo (or any canvas rebuild) between the two clicks used to leave
        # the view holding DELETED preview/marker items → RuntimeError on
        # the next mouse move.
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        view = composer._view
        composer.tool_mode = "rect"
        _mouse(view, QEvent.MouseButtonPress, 100, 100)
        _mouse(view, QEvent.MouseButtonRelease, 100, 100)    # click mode
        _mouse(view, QEvent.MouseMove, 150, 130)             # preview born
        assert view._preview is not None
        composer._rebuild_canvas()                           # undo etc.
        assert view._drag_start is None                      # cancelled
        _mouse(view, QEvent.MouseMove, 160, 140)             # must not raise
        self._host = host

    def test_second_click_threshold_is_scene_space(self):
        # Pan/zoom between the clicks must not confuse the click-vs-drag
        # guard: the test runs in scene mm at the current zoom (identity
        # here → 4 mm), not against the first press's viewport pixels.
        view, comp = _view("linea")
        _click(view, 50, 50)
        _mouse(view, QEvent.MouseButtonPress, 52, 50)        # 2 mm: waiting
        assert comp.placed == []
        _mouse(view, QEvent.MouseButtonRelease, 52, 50)
        _mouse(view, QEvent.MouseButtonPress, 60, 50)        # 10 mm: places
        assert len(comp.placed) == 1

    def test_snapped_axis_aligned_line_stays_straight(self):
        view, comp = _view()  # unused; place through a real composer
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        composer.tool_mode = "linea"
        composer.place_tool(30.0, 100.0, 90.0, 100.0)        # horizontal
        f = composer.comp.shapes[0]
        assert f.h_mm == 0.0                                 # no 2 mm tilt
        composer.tool_mode = "rect"
        composer.place_tool(30.0, 100.0, 90.0, 100.0)
        assert composer.comp.shapes[1].h_mm == 2.0           # rects clamp
        self._host = host

    def test_clipped_anchor_is_not_captured_by_another_vertex(self):
        comp = Composicion()
        frame = MarcoVista(x_mm=10.0, y_mm=10.0, w_mm=200.0, h_mm=150.0,
                           scale_n=100.0, uid="f1")
        comp.frames = [frame]
        # b anchors at x=100 m → projects at x_mm = 10 + (100+10)... far
        # outside the 200 mm frame; a nearby visible point (100.1) exists
        ct = CotaItem(scale_n=100.0, anchor_uid="f1",
                      a_world=[0.0, 0.0, 0.0], b_world=[100.0, 0.0, 0.0])
        comp.cotas = [ct]
        _FakeReprojector(comp, [[0.0, 0.0, 0.0],
                                [100.1, 0.0, 0.0]]).reproject()
        assert ct.b_world == pytest.approx([100.0, 0.0, 0.0])  # untouched

    def test_resnap_tolerance_is_capped_at_half_a_metre(self):
        comp = Composicion()
        frame = MarcoVista(x_mm=10.0, y_mm=10.0, w_mm=200.0, h_mm=150.0,
                           scale_n=1000.0, uid="f1")     # 1:1000 → uncapped
        comp.frames = [frame]                            # tol would be 2.5 m
        ct = CotaItem(scale_n=1000.0, anchor_uid="f1",
                      a_world=[0.0, 0.0, 0.0], b_world=[6.0, 0.0, 0.0])
        comp.cotas = [ct]
        _FakeReprojector(comp, [[0.0, 0.0, 0.0],
                                [7.0, 0.0, 0.0]]).reproject()   # 1 m away
        assert ct.b_world == pytest.approx([6.0, 0.0, 0.0])     # not captured


class TestCotaModel:
    def test_normal_is_perpendicular_and_unit(self):
        ct = CotaItem(dx_mm=30.0, dy_mm=40.0)
        nx, ny = ct.normal()
        assert nx * 30.0 + ny * 40.0 == pytest.approx(0.0)
        assert nx * nx + ny * ny == pytest.approx(1.0)

    def test_label_honours_decimals(self):
        ct = CotaItem(dx_mm=34.56, dy_mm=0.0, scale_n=100.0, decimals=1)
        assert ct.label() == "3.5 m"
        ct.decimals = 3
        assert ct.label() == "3.456 m"

    def test_old_documents_load_without_the_new_fields(self):
        ct = CotaItem(**{"x_mm": 5.0, "y_mm": 6.0, "dx_mm": 40.0,
                         "dy_mm": 0.0, "scale_n": 50.0, "offset_mm": 4.0,
                         "text": ""})
        assert ct.sep_mm == 0.0                              # line on the points
        assert ct.ends == "tick"
        assert ct.text_mm == pytest.approx(2.8)


class TestGroundLine:
    """The ground line of an elevation (Marco, 2026-09-08, the Yanque arch:
    «de esta línea para abajo es el terreno»): a line with earth ticks, a
    hatched band or a filled band hanging UNDER it."""

    def test_ground_fields_round_trip_and_default_to_ticks(self):
        comp = Composicion()
        comp.shapes = [FormaItem(kind="terreno", ground="hatch", tick_mm=4.0,
                                 tick_step_mm=2.0, band_mm=9.0)]
        again = Composicion.from_dict(comp.to_dict())
        f = again.shapes[0]
        assert (f.ground, f.tick_mm, f.tick_step_mm, f.band_mm) == \
            ("hatch", 4.0, 2.0, 9.0)
        # an old .igz without the fields: the classic ticks
        old = FormaItem(**{"kind": "terreno", "w_mm": 50.0, "h_mm": 0.0})
        assert old.ground == "ticks"

    def test_tool_places_a_heavier_line_and_remembers_the_look(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        composer.tool_mode = "terreno"
        composer.place_tool(30.0, 100.0, 90.0, 100.0)
        f = composer.comp.shapes[0]
        assert f.kind == "terreno" and f.h_mm == 0.0 and f.stroke_mm == 0.5
        # pick it, switch to a hatched band from the panel → the next one
        # starts hatched too
        composer._rebuild_canvas()                 # the deferred rebuild
        item = next(i for i in composer.canvas.items()
                    if getattr(i, "model", None) is f)
        item.setSelected(True)
        composer.on_selection_changed()
        composer.forma_ground.setCurrentIndex(
            composer.forma_ground.findData("hatch"))
        assert f.ground == "hatch"
        composer.tool_mode = "terreno"
        composer.place_tool(30.0, 120.0, 90.0, 120.0)
        assert composer.comp.shapes[1].ground == "hatch"
        self._host = host

    def test_the_ground_hangs_under_the_line_whichever_way_it_slopes(self):
        from PySide6.QtGui import QImage, QPainter
        from views.composer import paint_forma_mm

        def ink_below_and_above(f):
            img = QImage(200, 120, QImage.Format_RGB32)
            img.fill(0xFFFFFFFF)
            p = QPainter(img)
            p.scale(2.0, 2.0)                       # 2 px per mm
            p.translate(10, 30)
            paint_forma_mm(p, f)
            p.end()
            # a horizontal line at y=30 mm → row 60 px; count dark pixels
            # in the bands just under and just over it
            def dark(rows):
                return sum(1 for y in rows for x in range(20, 180)
                           if (img.pixel(x, y) & 0xFF) < 200)
            return dark(range(62, 76)), dark(range(40, 57))

        for mode in ("ticks", "hatch", "band"):
            f = FormaItem(kind="terreno", w_mm=80.0, h_mm=0.0, ground=mode,
                          tick_mm=6.0, fill_color="#806040")   # earth band
            below, above = ink_below_and_above(f)
            assert below > 0 and above == 0, mode
        # a sloping line drawn right-to-left (invert) still buries the
        # side of positive y: nothing above its highest point
        f = FormaItem(kind="terreno", w_mm=80.0, h_mm=10.0, invert=True)
        img = QImage(240, 160, QImage.Format_RGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        p.scale(2.0, 2.0)
        p.translate(10, 30)
        paint_forma_mm(p, f)
        p.end()
        assert not any((img.pixel(x, y) & 0xFF) < 200
                       for y in range(0, 56) for x in range(0, 240))


class TestShiftOrtho:
    """Shift locks the second point of a segment to the horizontal or the
    vertical through the first (Marco, 2026-09-08: «cuando acote para
    sacar una distancia me gustaría que apretando Shift me restrinja de
    forma ortogonal»)."""

    def test_a_cota_drawn_with_shift_comes_out_horizontal(self):
        view, comp = _view("cota")
        _click(view, 50, 100)                                # first point
        _mouse(view, QEvent.MouseMove, 150, 112, mods=Qt.ShiftModifier)
        _mouse(view, QEvent.MouseButtonPress, 150, 112, mods=Qt.ShiftModifier)
        _mouse(view, QEvent.MouseButtonRelease, 150, 112, mods=Qt.ShiftModifier)
        ax, ay = _scene_xy(view, 50, 100)
        assert view._second_pt is not None
        assert abs(view._second_pt.y() - ay) < 1e-6           # locked flat
        assert view._second_pt.x() > ax + 50
        _click(view, 150, 130)                               # the offset
        x0, y0, x1, y1, _sep = comp.placed[0]
        assert abs(y1 - y0) < 1e-6 and x1 > x0

    def test_the_closer_axis_wins_and_no_shift_stays_free(self):
        view, comp = _view("linea")
        _click(view, 50, 50)
        _mouse(view, QEvent.MouseButtonPress, 58, 150, mods=Qt.ShiftModifier)
        x0, y0, x1, y1, _sep = comp.placed[0]
        assert abs(x1 - x0) < 1e-6 and y1 > y0               # vertical
        view, comp = _view("linea")
        _click(view, 50, 50)
        _mouse(view, QEvent.MouseButtonPress, 58, 150)
        x0, y0, x1, y1, _sep = comp.placed[0]
        assert abs(x1 - x0) > 5                              # free

    def test_a_drag_with_shift_locks_too_and_the_offset_click_does_not(self):
        view, comp = _view("cota")
        _mouse(view, QEvent.MouseButtonPress, 50, 100)
        _mouse(view, QEvent.MouseMove, 150, 108, buttons=Qt.LeftButton,
               mods=Qt.ShiftModifier)
        _mouse(view, QEvent.MouseButtonRelease, 150, 108,
               mods=Qt.ShiftModifier)
        ax, ay = _scene_xy(view, 50, 100)
        assert abs(view._second_pt.y() - ay) < 1e-6
        # the third click (the dimension line's offset) is never locked:
        # Shift there must not pull the separation to zero
        _mouse(view, QEvent.MouseButtonPress, 150, 130, mods=Qt.ShiftModifier)
        assert comp.placed and abs(comp.placed[0][4]) > 5

    def test_chain_next_point_locks_after_the_offset_is_fixed(self):
        from unittest import mock
        view, comp = _view("cota_cadena")
        comp.place_chain_cota = mock.Mock(return_value=object())
        _click(view, 50, 100)
        _click(view, 120, 100)
        _click(view, 120, 120)                               # the offset
        _mouse(view, QEvent.MouseButtonPress, 200, 109, mods=Qt.ShiftModifier)
        _mouse(view, QEvent.MouseButtonRelease, 200, 109, mods=Qt.ShiftModifier)
        args = comp.place_chain_cota.call_args_list[-1][0]
        (px, py), (qx, qy) = args[0], args[1]
        assert abs(qy - py) < 1e-6 and qx > px

    def test_pressing_shift_replays_the_rubber_band_where_the_cursor_is(self):
        from PySide6.QtGui import QKeyEvent
        view, comp = _view("linea")
        _click(view, 50, 50)
        _mouse(view, QEvent.MouseMove, 150, 62)
        free = view._preview.rect()
        assert free.height() > 5
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Shift,
                                     Qt.ShiftModifier))
        assert view._preview.rect().height() < 1e-6          # locked flat
        view.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, Qt.Key_Shift,
                                       Qt.NoModifier))
        assert view._preview.rect().height() > 5             # free again


class TestStickyTools:
    """A drawing tool stays armed after placing (Marco, 2026-09-08: «quiero
    seguir acotando… que siga activo ese comando a no ser que apriete Esc
    o haga clic en el icono del cursor»); the one-of-a-kind items hand
    back to Select; Esc leaves the tool once nothing is in progress."""

    def _composer(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        self._host = host
        return composer

    def test_cotas_stay_armed_every_other_tool_does_not(self):
        composer = self._composer()
        composer._tool_actions["cota"].trigger()
        composer.place_tool(10.0, 10.0, 60.0, 10.0, sep_mm=5.0)
        composer.place_tool(10.0, 30.0, 60.0, 30.0, sep_mm=5.0)
        assert len(composer.comp.cotas) == 2
        assert composer.tool_mode == "cota"
        assert composer._tool_actions["cota"].isChecked()
        # a line hands back to Select after one (Marco tried the sticky
        # version on every tool: «tal vez eso solo para lo que es acotar»)
        composer._tool_actions["linea"].trigger()
        composer.place_tool(10.0, 50.0, 60.0, 50.0)
        assert composer.tool_mode == "select"
        assert composer._tool_actions["select"].isChecked()
        composer._tool_actions["escala"].trigger()
        composer.place_tool(10.0, 70.0, 10.0, 70.0)
        assert composer.tool_mode == "select"

    def test_esc_cancels_the_placement_first_then_leaves_the_tool(self):
        from PySide6.QtGui import QKeyEvent
        composer = self._composer()
        composer._tool_actions["cota"].trigger()
        view = composer._view
        view._drag_start = QPointF(10.0, 10.0)                # first click
        esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        view.keyPressEvent(esc)
        assert view._drag_start is None and composer.tool_mode == "cota"
        view.keyPressEvent(esc)
        assert composer.tool_mode == "select"
        assert composer._tool_actions["select"].isChecked()


class TestArrowNudge:
    """Arrow keys move the selection by 1 mm (Shift: 10 mm), one undo step
    (Marco, 2026-09-08: «una vez seleccionado debería mover con las teclas
    de desplazamiento, así como lo hace QGIS»)."""

    def _composer(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        host.viewport = _FakeViewport()
        composer = ComposerWindow(host)
        self._host = host
        return composer

    def test_arrows_nudge_the_selected_items_and_undo_as_one_step(self):
        from PySide6.QtGui import QKeyEvent
        composer = self._composer()
        a = FormaItem(kind="rect", x_mm=10.0, y_mm=10.0)
        b = FormaItem(kind="rect", x_mm=50.0, y_mm=10.0)
        locked = FormaItem(kind="rect", x_mm=90.0, y_mm=10.0, locked=True)
        composer.comp.shapes = [a, b, locked]
        composer._rebuild_canvas()
        for it in composer.canvas.items():
            if getattr(it, "model", None) in (a, b):
                it.setSelected(True)
            if getattr(it, "model", None) is locked:
                it.force_select()
        view = composer._view
        key = lambda k, m=Qt.NoModifier: view.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, k, m))
        key(Qt.Key_Right)
        assert (a.x_mm, b.x_mm) == (11.0, 51.0)
        key(Qt.Key_Down, Qt.ShiftModifier)
        assert (a.y_mm, b.y_mm) == (20.0, 20.0)
        assert (locked.x_mm, locked.y_mm) == (90.0, 10.0)   # never
        # the canvas items slid along without a rebuild
        pos = {id(it.model): it.pos() for it in composer.canvas.items()
               if getattr(it, "model", None) in (a, b)}
        assert pos[id(a)] == QPointF(11.0, 20.0)
        assert composer.history.undo() and (a.y_mm, b.y_mm) == (10.0, 10.0)
        assert composer.history.undo() and (a.x_mm, b.x_mm) == (10.0, 50.0)

    def test_arrows_do_nothing_without_a_selection_or_mid_placement(self):
        from PySide6.QtGui import QKeyEvent
        composer = self._composer()
        a = FormaItem(kind="rect", x_mm=10.0, y_mm=10.0)
        composer.comp.shapes = [a]
        composer._rebuild_canvas()
        view = composer._view
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert a.x_mm == 10.0
        next(it for it in composer.canvas.items()
             if getattr(it, "model", None) is a).setSelected(True)
        view._drag_start = QPointF(1.0, 1.0)          # a line half drawn
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert a.x_mm == 10.0
        view._drag_start = None
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.AltModifier))
        assert abs(a.x_mm - 9.9) < 1e-9
