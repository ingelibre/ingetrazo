# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The composer's sacred math: paper mm × scale → metres of model, and the
camera settings that realise it (docs/composer-plan.md)."""
import math

import pytest

from core.composition import (Composicion, MarcoVista, apply_frame_camera,
                              mm_to_px, model_height_for_frame,
                              ortho_distance_for_height)


class TestScaleMath:
    def test_1_100_on_200mm_is_20m(self):
        assert model_height_for_frame(200.0, 100) == pytest.approx(20.0)

    def test_1_50_on_297mm(self):
        assert model_height_for_frame(297.0, 50) == pytest.approx(14.85)

    def test_invalid_inputs_raise(self):
        with pytest.raises(ValueError):
            model_height_for_frame(0, 100)
        with pytest.raises(ValueError):
            model_height_for_frame(100, -5)

    def test_ortho_distance_inverts_the_camera_projection(self):
        # OrbitCamera's parallel half-height is distance·tan(fov/2); the
        # inverse must reproduce the requested height exactly.
        for fov in (30.0, 45.0, 60.0):
            d = ortho_distance_for_height(20.0, fov)
            half_h = d * math.tan(math.radians(fov) / 2.0)
            assert 2 * half_h == pytest.approx(20.0)

    def test_mm_to_px_at_300dpi(self):
        # The DoD number: 10 mm at 300 dpi is 118 px.
        assert mm_to_px(10.0, 300) == 118
        assert mm_to_px(25.4, 300) == 300


class TestComposicion:
    def test_page_size_landscape_swaps(self):
        c = Composicion(paper="A4", landscape=False)
        assert c.page_size_mm() == (210.0, 297.0)
        c.landscape = True
        assert c.page_size_mm() == (297.0, 210.0)

    def test_default_frame_fits_margins(self):
        c = Composicion(paper="A3", landscape=True, margin_mm=10.0)
        f = c.default_frame()
        pw, ph = c.page_size_mm()
        assert f.x_mm == f.y_mm == 10.0
        assert f.w_mm == pw - 20.0
        assert f.h_mm == ph - 20.0

    def test_frame_render_px_follows_dpi(self):
        f = MarcoVista(w_mm=254.0, h_mm=127.0)
        assert f.render_px(300) == (3000, 1500)


class _FakeCamera:
    """Just enough of OrbitCamera for apply_frame_camera."""

    def __init__(self):
        self.fov_deg = 45.0
        self.perspective = True
        self.distance = 7.0
        self.aspect = 1.6
        self.applied_std = None

    def set_view(self, key):
        self.applied_std = key


class TestApplyFrameCamera:
    def test_scale_realised_through_the_camera(self):
        cam = _FakeCamera()
        f = MarcoVista(w_mm=170.0, h_mm=200.0, scale_n=100.0,
                       view_key="std:top")
        apply_frame_camera(cam, f)
        assert cam.applied_std == "top"
        assert cam.perspective is False
        half_h = cam.distance * math.tan(math.radians(cam.fov_deg) / 2.0)
        assert 2 * half_h == pytest.approx(20.0)   # 200 mm at 1:100
        w_px, h_px = f.render_px()
        assert cam.aspect == pytest.approx(w_px / h_px)


class _FakeScene:
    def __init__(self, lo, hi):
        self._b = (lo, hi)

    def bounds(self):
        return self._b


class _V3:
    """Minimal QVector3D stand-in supporting + and *."""

    def __init__(self, x, y, z):
        self.v = (x, y, z)

    def __add__(self, o):
        return _V3(*(a + b for a, b in zip(self.v, o.v)))

    def __mul__(self, k):
        return _V3(*(a * k for a in self.v))


class TestStdViewCentering:
    def test_std_view_centres_on_the_model(self):
        cam = _FakeCamera()
        cam.target = None
        scene = _FakeScene(_V3(2, 4, 0), _V3(6, 8, 2))
        f = MarcoVista(view_key="std:front", scale_n=100.0)
        apply_frame_camera(cam, f, saved_view=None, scene=scene)
        assert cam.target.v == (4.0, 6.0, 1.0)

    def test_current_view_keeps_the_user_target(self):
        cam = _FakeCamera()
        cam.target = "user-framed"
        scene = _FakeScene(_V3(0, 0, 0), _V3(10, 10, 10))
        f = MarcoVista(view_key="__current__", scale_n=100.0)
        apply_frame_camera(cam, f, saved_view=None, scene=scene)
        assert cam.target == "user-framed"


# ── C2: items, serialisation, history ───────────────────────────────────────

from core.composition import (AddItemCommand, Cajetin, ComposerHistory,
                              EditItemCommand, ImagenItem,
                              RemoveItemCommand, TextoItem, snap_mm)


def _full_comp() -> Composicion:
    c = Composicion(name="Lámina municipal", paper="A1", landscape=True,
                    margin_mm=12.0)
    c.frames = [MarcoVista(20, 20, 300, 200, 100, "std:top"),
                MarcoVista(340, 20, 200, 150, 100, "scene:Planta"),
                MarcoVista(20, 240, 200, 150, 50, "std:front"),
                MarcoVista(240, 240, 200, 150, 50, "std:right")]
    c.texts = [TextoItem(20, 400, 120, "Notas generales\nHormigón f'c=210",
                         12.0, True)]
    c.images = [ImagenItem(600, 400, 60, 40, "/tmp/logo.png")]
    c.cajetin = Cajetin(640, 780, 180, 33, "Plaza Yanque", "M. Sumari",
                        "08/08/2026", "1:100", "L-01")
    return c


class TestSerialisation:
    def test_round_trip_preserves_everything(self):
        c = _full_comp()
        c2 = Composicion.from_dict(c.to_dict())
        assert c2.to_dict() == c.to_dict()
        assert len(c2.frames) == 4
        assert c2.frames[1].view_key == "scene:Planta"
        assert c2.texts[0].bold is True
        assert c2.cajetin.proyecto == "Plaza Yanque"
        assert c2.paper == "A1"

    def test_empty_optional_blocks_are_omitted(self):
        c = Composicion()
        d = c.to_dict()
        assert "texts" not in d and "images" not in d and "cajetin" not in d


class TestComposerHistory:
    def test_add_remove_undo_redo(self):
        c = Composicion()
        h = ComposerHistory()
        f = MarcoVista()
        h.execute(AddItemCommand(c, f))
        assert c.frames == [f]
        h.execute(RemoveItemCommand(c, f))
        assert c.frames == []
        assert h.undo() and c.frames == [f]
        assert h.undo() and c.frames == []
        assert h.redo() and c.frames == [f]

    def test_cajetin_add_and_remove(self):
        c = Composicion()
        h = ComposerHistory()
        caj = Cajetin()
        h.execute(AddItemCommand(c, caj))
        assert c.cajetin is caj
        h.execute(RemoveItemCommand(c, caj))
        assert c.cajetin is None
        h.undo()
        assert c.cajetin is caj
        h.undo()
        assert c.cajetin is None

    def test_edit_captures_before_and_after(self):
        t = TextoItem(text="hola")
        h = ComposerHistory()
        h.execute(EditItemCommand(t, {"text": "chau"}))
        assert t.text == "chau"
        h.undo()
        assert t.text == "hola"

    def test_drag_edit_uses_the_press_snapshot(self):
        f = MarcoVista(x_mm=50.0)
        f.x_mm = 80.0            # the drag already moved the model
        h = ComposerHistory()
        h.execute(EditItemCommand(f, {"x_mm": 80.0}, before={"x_mm": 50.0}))
        h.undo()
        assert f.x_mm == 50.0

    def test_coalescing_merges_same_field_edits(self):
        t = TextoItem(text="")
        h = ComposerHistory()
        for txt in ("h", "ho", "hol", "hola"):
            h.execute(EditItemCommand(t, {"text": txt}),
                      notify=False, coalesce=True)
        assert t.text == "hola"
        assert h.undo()
        assert t.text == ""       # ONE undo step for the whole retype
        assert not h.undo()

    def test_redo_cleared_by_new_command(self):
        c = Composicion()
        h = ComposerHistory()
        h.execute(AddItemCommand(c, MarcoVista()))
        h.undo()
        h.execute(AddItemCommand(c, TextoItem()))
        assert not h.redo()


class TestSnap:
    def test_snaps_to_the_nearest_target(self):
        assert snap_mm(9.2, [0.0, 10.0, 148.5], 2.0) == 10.0
        assert snap_mm(147.0, [0.0, 10.0, 148.5], 2.0) == 148.5

    def test_far_values_pass_through(self):
        assert snap_mm(50.0, [0.0, 10.0], 2.0) == 50.0


class TestDefaultCajetin:
    def test_docks_bottom_right_inside_margins(self):
        c = Composicion(paper="A1", landscape=True, margin_mm=10.0)
        caj = c.default_cajetin()
        pw, ph = c.page_size_mm()
        assert caj.x_mm + caj.w_mm == pytest.approx(pw - 10.0)
        assert caj.y_mm + caj.h_mm == pytest.approx(ph - 10.0)


class TestIgzPersistence:
    def test_compositions_survive_the_igz_round_trip(self, tmp_path):
        from core.scene import Scene
        from formats.igz import load_into, save_scene
        scene = Scene()
        scene.compositions.append(_full_comp())
        scene.compositions.append(Composicion(name="Lámina 2", paper="A3"))
        path = tmp_path / "doc.igz"
        save_scene(scene, path)

        fresh = Scene()
        load_into(fresh, path)
        assert len(fresh.compositions) == 2
        a, b = fresh.compositions
        assert a.to_dict() == _full_comp().to_dict()
        assert b.name == "Lámina 2" and b.paper == "A3"

    def test_clear_drops_compositions(self):
        from core.scene import Scene
        scene = Scene()
        scene.compositions.append(Composicion())
        scene.clear()
        assert scene.compositions == []


# ── C3: technical style, scale bar, titles ──────────────────────────────────

from core.composition import BarraEscala


class TestBarraEscala:
    def test_nice_segment_lengths(self):
        # 1:100, 4 segments → target 25 mm/segment → 2.5 m → falls to 2.5
        assert BarraEscala(scale_n=100).segment_m() == 2.5
        # 1:50 → target 25 mm → 1.25 m → nice 1 m (20 mm per segment)
        assert BarraEscala(scale_n=50).segment_m() == 1.0
        # 1:1000 → 25 m → nice 25
        assert BarraEscala(scale_n=1000).segment_m() == 25.0

    def test_bar_prints_at_most_100mm(self):
        for n in (50, 100, 200, 250, 500, 1000, 2000, 5000):
            sb = BarraEscala(scale_n=n)
            assert sb.w_mm <= 100.0 + 1e-9
            assert sb.w_mm >= 30.0          # and never uselessly small

    def test_segment_mm_matches_scale(self):
        sb = BarraEscala(scale_n=100)
        # 2.5 m at 1:100 is 25 mm of paper
        assert sb.segment_mm() == pytest.approx(25.0)

    def test_commands_route_to_the_scalebars_list(self):
        c = Composicion()
        h = ComposerHistory()
        sb = BarraEscala()
        h.execute(AddItemCommand(c, sb))
        assert c.scalebars == [sb]
        h.execute(RemoveItemCommand(c, sb))
        assert c.scalebars == []
        h.undo()
        assert c.scalebars == [sb]


class TestC3Serialisation:
    def test_style_title_and_scalebar_round_trip(self):
        c = Composicion()
        c.frames = [MarcoVista(style="tecnico", show_title=True,
                               view_key="std:top", scale_n=100)]
        c.scalebars = [BarraEscala(x_mm=30, y_mm=380, scale_n=100,
                                   segments=5)]
        c2 = Composicion.from_dict(c.to_dict())
        assert c2.frames[0].style == "tecnico"
        assert c2.frames[0].show_title is True
        assert c2.scalebars[0].segments == 5
        assert c2.to_dict() == c.to_dict()

    def test_old_documents_default_to_shaded(self):
        # a C2-era dict has no style/show_title keys
        d = {"frames": [{"x_mm": 1, "y_mm": 2, "w_mm": 3, "h_mm": 4,
                         "scale_n": 100, "view_key": "std:top"}]}
        c = Composicion.from_dict(d)
        assert c.frames[0].style == "sombreado"
        assert c.frames[0].show_title is False


# ── C4: hidden-line removal ─────────────────────────────────────────────────

class TestHLR:
    """The exact kernel, on hand-checkable camera-space fixtures."""

    def _spans(self, a2, b2, az, bz, tris2, trisz, eps=1e-6):
        import numpy as np
        from core.hlr import visible_spans
        return visible_spans(np.array(a2, float), np.array(b2, float),
                             az, bz, np.array(tris2, float),
                             np.array(trisz, float), eps)

    def test_unoccluded_edge_is_whole(self):
        spans = self._spans((-1, 0), (1, 0), 0.0, 0.0,
                            [[(-0.5, 1), (0.5, 1), (0, 2)]], [[0, 0, 0]])
        assert spans == [(0.0, 1.0)]

    def test_triangle_in_front_cuts_the_middle(self):
        # edge along x at depth 10; triangle covering x∈[-0.5,0.5] at depth 5
        spans = self._spans((-1, 0), (1, 0), 10.0, 10.0,
                            [[(-0.5, -1), (0.5, -1), (0.0, 1)]],
                            [[5.0, 5.0, 5.0]])
        assert len(spans) == 2
        (a0, a1), (b0, b1) = spans
        assert a0 == 0.0 and b1 == 1.0
        # the tri's slanted sides cross y=0 at x=±0.25 → t = 0.375 / 0.625
        assert a1 == pytest.approx(0.375, abs=1e-9)
        assert b0 == pytest.approx(0.625, abs=1e-9)

    def test_triangle_behind_does_not_cut(self):
        spans = self._spans((-1, 0), (1, 0), 5.0, 5.0,
                            [[(-2, -2), (2, -2), (0, 2)]],
                            [[9.0, 9.0, 9.0]])
        assert spans == [(0.0, 1.0)]

    def test_coplanar_face_does_not_self_occlude(self):
        # the edge lies exactly in the triangle's plane (e ≈ 0 < eps)
        spans = self._spans((-1, 0), (1, 0), 3.0, 3.0,
                            [[(-2, -2), (2, -2), (0, 2)]],
                            [[3.0, 3.0, 3.0]], eps=1e-4)
        assert spans == [(0.0, 1.0)]

    def test_two_triangles_merge_their_shadow(self):
        # both cover the centre of the edge, so their shadows overlap
        tris = [[(-0.6, -1), (0.3, -1), (-0.15, 1)],
                [(-0.3, -1), (0.6, -1), (0.15, 1)]]
        spans = self._spans((-1, 0), (1, 0), 10.0, 10.0,
                            tris, [[5, 5, 5], [5, 5, 5]])
        assert len(spans) == 2       # one merged hole, not two

    def test_disjoint_shadows_leave_the_gap_visible(self):
        tris = [[(-0.6, -1), (0.1, -1), (-0.25, 1)],
                [(-0.1, -1), (0.6, -1), (0.25, 1)]]
        spans = self._spans((-1, 0), (1, 0), 10.0, 10.0,
                            tris, [[5, 5, 5], [5, 5, 5]])
        assert len(spans) == 3       # the sliver between them survives

    def test_full_occlusion_leaves_nothing(self):
        spans = self._spans((-1, 0), (1, 0), 10.0, 10.0,
                            [[(-3, -3), (3, -3), (0, 5)]],
                            [[1.0, 1.0, 1.0]])
        assert spans == []


class TestHLRScene:
    def test_box_from_top_shows_four_edges(self):
        from PySide6.QtGui import QVector3D
        from core.camera import OrbitCamera
        from core.hlr import hlr_view
        from core.scene import Scene

        scene = Scene()
        m = scene.mesh
        V = QVector3D
        # a 2×3×1 m closed box at the origin
        m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 3, 0), V(0, 3, 0)])   # floor
        m.add_face([V(0, 0, 1), V(2, 0, 1), V(2, 3, 1), V(0, 3, 1)])   # roof
        m.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 1), V(0, 0, 1)])
        m.add_face([V(0, 3, 0), V(2, 3, 0), V(2, 3, 1), V(0, 3, 1)])
        m.add_face([V(0, 0, 0), V(0, 3, 0), V(0, 3, 1), V(0, 0, 1)])
        m.add_face([V(2, 0, 0), V(2, 3, 0), V(2, 3, 1), V(2, 0, 1)])

        cam = OrbitCamera()
        # the composer's plan view: TRUE 90° (apply_frame_camera swaps the
        # up vector), so verticals vanish and nothing peeks out sideways
        f = MarcoVista(view_key="std:top", scale_n=100.0,
                       w_mm=100.0, h_mm=100.0)
        apply_frame_camera(cam, f, saved_view=None, scene=scene)
        segs = hlr_view(scene, cam)
        # From straight above only the roof's 4 edges are visible; the
        # floor's 4 are hidden and the 4 verticals are points (dropped or
        # zero-length). Some verticals may survive as degenerate slivers —
        # assert on total drawn LENGTH instead of counting.
        total = 0.0
        for x0, y0, x1, y1 in segs:
            total += math.hypot(x1 - x0, y1 - y0)
        assert total == pytest.approx(2 * (2 + 3), rel=1e-3)


class TestDxfOut:
    def test_writes_readable_r12_lines(self, tmp_path):
        from formats.dxf_out import save_dxf_lines
        path = tmp_path / "vista.dxf"
        n = save_dxf_lines(path, [(0.0, 0.0, 2.0, 0.0),
                                  (2.0, 0.0, 2.0, 3.0)], layer="Planta 1")
        text = path.read_text()
        assert n == 2
        assert text.count("0\nLINE\n") == 2
        assert "8\nPLANTA_1\n" in text          # sanitised layer name
        assert text.rstrip().endswith("EOF")
        # coordinates survive verbatim
        assert "10\n0\n" in text and "11\n2\n" in text and "21\n3\n" in text

    def test_dxf_round_trips_through_ezdxf_if_available(self, tmp_path):
        ezdxf = pytest.importorskip("ezdxf")
        from formats.dxf_out import save_dxf_lines
        path = tmp_path / "vista.dxf"
        save_dxf_lines(path, [(0.0, 0.0, 9.258, 0.0)], layer="PLANTA")
        doc = ezdxf.readfile(str(path))
        lines = list(doc.modelspace().query("LINE"))
        assert len(lines) == 1
        assert lines[0].dxf.end.x == pytest.approx(9.258)
        assert lines[0].dxf.layer == "PLANTA"


# ── C5: QGIS-parity items ───────────────────────────────────────────────────

from core.composition import CotaItem, FlechaNorte, FormaItem, Leyenda


class TestC5Items:
    def test_cota_label_is_the_real_distance(self):
        ct = CotaItem(dx_mm=80.0, dy_mm=0.0, scale_n=100.0)
        assert ct.label() == "8.00 m"
        ct = CotaItem(dx_mm=30.0, dy_mm=40.0, scale_n=1000.0)  # 50 mm paper
        assert ct.label() == "50.00 m"
        ct.text = "VER DETALLE"
        assert ct.label() == "VER DETALLE"

    def test_leyenda_height_follows_rows(self):
        le = Leyenda(rows=["A", "B", "C"])
        assert le.h_mm == pytest.approx(7.5 + 16.5)

    def test_full_c5_serialisation_round_trip(self):
        c = Composicion()
        c.frames = [MarcoVista(grid_m=2.0)]
        c.texts = [TextoItem(text="T", family="DejaVu Serif", italic=True,
                             color="#aa0000", align="center")]
        c.nortes = [FlechaNorte(size_mm=22, angle_deg=15)]
        c.leyendas = [Leyenda(title="LEY", rows=["Muros", "Puertas"])]
        c.shapes = [FormaItem(kind="flecha", invert=True, stroke_mm=0.5)]
        c.cotas = [CotaItem(dx_mm=50, dy_mm=10, scale_n=200, text="")]
        c2 = Composicion.from_dict(c.to_dict())
        assert c2.to_dict() == c.to_dict()
        assert c2.frames[0].grid_m == 2.0
        assert c2.texts[0].align == "center"
        assert c2.leyendas[0].rows == ["Muros", "Puertas"]
        assert c2.cotas[0].scale_n == 200

    def test_commands_route_all_new_types(self):
        c = Composicion()
        h = ComposerHistory()
        items = [FlechaNorte(), Leyenda(), FormaItem(), CotaItem()]
        for it in items:
            h.execute(AddItemCommand(c, it))
        assert (c.nortes and c.leyendas and c.shapes and c.cotas)
        for it in items:
            h.execute(RemoveItemCommand(c, it))
        assert not (c.nortes or c.leyendas or c.shapes or c.cotas)
        for _ in range(4):
            h.undo()
        assert (c.nortes and c.leyendas and c.shapes and c.cotas)

    def test_old_documents_still_load(self):
        d = {"frames": [{"x_mm": 1, "y_mm": 2, "w_mm": 3, "h_mm": 4,
                         "scale_n": 100, "view_key": "std:top"}],
             "texts": [{"x_mm": 1, "y_mm": 2, "w_mm": 3, "text": "hola",
                        "size_pt": 12, "bold": False}]}
        c = Composicion.from_dict(d)
        assert c.texts[0].family == "Sans Serif"     # new fields default
        assert c.frames[0].grid_m == 0.0
