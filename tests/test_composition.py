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
