# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Camera from Photo (core/photo_match.py).

Every photo here is made up: a camera is chosen, the edges of a box are
projected with it, and the handles are put where those edges land. The
calibration must then give back the camera it was made with — focal
length, turn and eye — and the viewport's camera built from it must draw
the box where the "photo" shows it.
"""
import math
import struct

import pytest

from core import photo_match as PM


# ---- A made-up camera --------------------------------------------------------
def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


class FakeCamera:
    """A pinhole camera at ``eye`` looking at ``target``, turned ``roll``
    degrees about the sight line, with a vertical angle of view ``fov``."""

    def __init__(self, eye, target, fov=50.0, roll=0.0, aspect=1.5):
        self.eye = eye
        self.aspect = aspect
        self.f = 1.0 / math.tan(math.radians(fov) / 2.0)
        fwd = _norm(tuple(t - e for t, e in zip(target, eye)))
        right = _norm(_cross(fwd, (0.0, 0.0, 1.0)))
        up = _cross(right, fwd)
        r = math.radians(roll)
        c, s = math.cos(r), math.sin(r)
        self.right = tuple(c * a + s * b for a, b in zip(right, up))
        self.up = tuple(-s * a + c * b for a, b in zip(right, up))
        self.back = tuple(-x for x in fwd)

    def uv(self, p):
        d = tuple(a - b for a, b in zip(p, self.eye))
        cx = sum(a * b for a, b in zip(d, self.right))
        cy = sum(a * b for a, b in zip(d, self.up))
        cz = sum(a * b for a, b in zip(d, self.back))
        assert cz < 0, "point behind the made-up camera"
        x, y = -self.f * cx / cz, -self.f * cy / cz
        return (x / (2.0 * self.aspect) + 0.5, 0.5 - y / 2.0)


def _photo(cam, height=3.0, x_len=6.0, y_len=5.0):
    """The handles of a box corner at the origin, seen by ``cam``."""
    pm = PM.PhotoMatch(path="", width_px=int(1000 * cam.aspect),
                       height_px=1000)
    pm.x_lines = [[list(cam.uv((1, 0, 0))), list(cam.uv((x_len, 0, 0)))],
                  [list(cam.uv((1, 0, height))),
                   list(cam.uv((x_len, 0, height)))]]
    pm.y_lines = [[list(cam.uv((0, 1, 0))), list(cam.uv((0, y_len, 0)))],
                  [list(cam.uv((0, 1, height))),
                   list(cam.uv((0, y_len, height)))]]
    pm.origin = list(cam.uv((0, 0, 0)))
    pm.scale_point = list(cam.uv((0, 0, height)))
    pm.scale_length = height
    return pm


CAMERAS = [
    # A corner from the street, eye height, slightly up the facade.
    dict(eye=(-8.0, -10.0, 1.6), target=(2.0, 3.0, 2.5), fov=50.0),
    # Wide lens, from above, rolled a little (hand-held).
    dict(eye=(-15.0, -6.0, 9.0), target=(3.0, 2.0, 0.0), fov=75.0,
         roll=4.0),
    # Long lens far away.
    dict(eye=(-40.0, -55.0, 3.0), target=(1.0, 1.0, 2.0), fov=22.0,
         roll=-2.0),
]


@pytest.mark.parametrize("spec", CAMERAS)
def test_the_camera_comes_back(spec):
    cam = FakeCamera(**spec)
    sol = PM.solve(_photo(cam))
    assert sol.focal == pytest.approx(cam.f, rel=1e-6)
    for got, want in ((sol.right, cam.right), (sol.up, cam.up),
                      (sol.back, cam.back)):
        assert got == pytest.approx(want, abs=1e-6)
    assert sol.eye == pytest.approx(spec["eye"], abs=1e-5)
    assert not sol.flipped_y


def test_vanishing_point_of_two_lines():
    vp = PM.vanishing_point(((0, 0), (1, 1)), ((0, 2), (1, 1.5)))
    assert vp == pytest.approx((4.0 / 3.0, 4.0 / 3.0))
    assert PM.vanishing_point(((0, 0), (1, 0)), ((0, 1), (1, 1))) is None


def test_the_scale_sets_the_distance():
    """Twice the length on the blue handle: the same picture from twice as
    far — the model is twice as big for it."""
    cam = FakeCamera(**CAMERAS[0])
    pm = _photo(cam)
    one = PM.solve(pm)
    pm.scale_length *= 2.0
    two = PM.solve(pm)
    assert two.eye == pytest.approx(tuple(2 * c for c in one.eye), abs=1e-6)


def test_green_toward_the_camera_flips_it_so_blue_points_up():
    """Red on the LEFT wall and green on the right: red and green both
    toward their vanishing points would put blue down; green turns round
    instead (it runs toward the camera from the origin)."""
    cam = FakeCamera(**CAMERAS[0])
    pm = _photo(cam)
    pm.x_lines, pm.y_lines = pm.y_lines, pm.x_lines
    sol = PM.solve(pm)
    assert sol.flipped_y
    assert sol.up[2] > 0.5          # the camera stands up
    # The box's corner still lands where the photo shows it.
    assert sol.project((0, 0, 3.0)) == pytest.approx(
        pm.to_image(pm.scale_point), abs=1e-6)


@pytest.mark.parametrize("change, key", [
    (lambda pm: pm.x_lines.__setitem__(1, [[0.1, 0.5], [0.4, 0.5]])
     or pm.x_lines.__setitem__(0, [[0.1, 0.2], [0.4, 0.2]]), "parallel_x"),
    (lambda pm: pm.y_lines.__setitem__(1, [[0.1, 0.8], [0.4, 0.8]])
     or pm.y_lines.__setitem__(0, [[0.1, 0.3], [0.4, 0.3]]), "parallel_y"),
    (lambda pm: pm.x_lines.__setitem__(0, [[0.3, 0.3], [0.3, 0.3]]),
     "short"),
    (lambda pm: setattr(pm, "scale_point", list(pm.origin)), "scale"),
])
def test_lines_that_give_no_camera_say_why(change, key):
    pm = _photo(FakeCamera(**CAMERAS[0]))
    change(pm)
    with pytest.raises(PM.CalibrationError) as err:
        PM.solve(pm)
    assert err.value.key == key


def test_both_vanishing_points_on_one_side_give_no_focal():
    """The red and green pairs both meeting to the right: no right angle
    fits, and the user is told instead of shown a camera at random."""
    pm = PM.PhotoMatch(width_px=1500, height_px=1000)
    pm.x_lines = [[[0.5, 0.3], [0.9, 0.4]], [[0.5, 0.7], [0.9, 0.6]]]
    pm.y_lines = [[[0.5, 0.45], [0.9, 0.47]], [[0.5, 0.55], [0.9, 0.53]]]
    with pytest.raises(PM.CalibrationError) as err:
        PM.solve(pm)
    assert err.value.key == "focal"


def test_scale_below_the_origin_is_refused():
    pm = _photo(FakeCamera(**CAMERAS[0]))
    o = pm.origin
    pm.scale_point = [o[0], o[1] + 0.2]
    with pytest.raises(PM.CalibrationError) as err:
        PM.solve(pm)
    assert err.value.key == "scale"


def test_the_default_handles_give_a_camera():
    """A new photo starts with the handles where they solve: the user sees
    a camera from the first moment and corrects it."""
    sol = PM.solve(PM.PhotoMatch(width_px=1500, height_px=1000))
    assert 20.0 < sol.fov_deg < 80.0
    assert sol.up[2] > 0.9
    assert sol.eye[2] > 0.0         # above the ground


def test_a_fixed_focal_length_is_kept():
    cam = FakeCamera(**CAMERAS[0])
    pm = _photo(cam)
    sol = PM.solve(pm, fixed_focal=cam.f * 1.1)
    assert sol.focal == pytest.approx(cam.f * 1.1)
    # The turn is still a rotation.
    for a in (sol.right, sol.up, sol.back):
        assert sum(c * c for c in a) == pytest.approx(1.0)


def test_scale_handle_snaps_back_onto_the_blue_axis():
    cam = FakeCamera(**CAMERAS[0])
    pm = _photo(cam)
    want = list(pm.scale_point)
    pm.scale_point = [want[0] + 0.03, want[1]]          # nudged sideways
    sol = PM.solve(pm)
    PM.snap_scale_to_axis(pm, sol)
    o = pm.to_image(pm.origin)
    s = pm.to_image(pm.scale_point)
    w = pm.to_image(want)
    # On the line from the origin to the true top of the corner.
    assert ((s[0] - o[0]) * (w[1] - o[1])
            - (s[1] - o[1]) * (w[0] - o[0])) == pytest.approx(0.0, abs=1e-9)


def test_moving_the_origin_takes_the_blue_handle_along():
    pm = PM.PhotoMatch(width_px=1500, height_px=1000)
    before = list(pm.scale_point)
    pm.set_handle("origin", (pm.origin[0] + 0.1, pm.origin[1] - 0.05))
    assert pm.scale_point == pytest.approx([before[0] + 0.1,
                                            before[1] - 0.05])


def test_round_trip_through_a_dict():
    pm = _photo(FakeCamera(**CAMERAS[1]))
    pm.path = "C:/fotos/esquina.jpg"
    pm.exif_focal_35 = 28.0
    pm.exif_model = "Camera X"
    back = PM.PhotoMatch.from_dict(pm.to_dict())
    assert back.to_dict() == pm.to_dict()
    assert pm.to_dict()["texture"] == {"path": "C:/fotos/esquina.jpg"}


def test_a_broken_entry_falls_back_to_the_defaults():
    pm = PM.PhotoMatch.from_dict({"texture": {"path": "x.jpg"},
                                  "x_lines": "nonsense", "origin": [1],
                                  "scale_length": -3})
    assert pm.path == "x.jpg"
    assert pm.x_lines == [[list(p) for p in ln] for ln in PM.DEFAULT_X_LINES]
    assert pm.origin == list(PM.DEFAULT_ORIGIN)
    assert pm.scale_length == PM.DEFAULT_SCALE_LENGTH
    assert PM.PhotoMatch.from_dict("nope") is None


def test_focal_in_millimetres_matches_the_camera_settings():
    """A 3:2 photo on the full frame: 24 mm tall, so an angle of view of
    2·atan(12/f) for a lens of f mm."""
    f_mm = 35.0
    fov = 2 * math.atan(12.0 / f_mm)
    focal = 1.0 / math.tan(fov / 2)
    assert PM.focal_35mm(focal, 1.5) == pytest.approx(f_mm)
    assert PM.focal_from_35mm(f_mm, 1.5) == pytest.approx(focal)


def test_mismatch_with_the_exif_focal_length():
    cam = FakeCamera(**CAMERAS[0])
    pm = _photo(cam)
    sol = PM.solve(pm)
    pm.exif_focal_35 = PM.focal_35mm(sol.focal, pm.aspect) * 1.5
    assert PM.focal_mismatch(pm, sol) == pytest.approx(1 / 3, rel=1e-6)
    pm.exif_focal_35 = None
    assert PM.focal_mismatch(pm, sol) is None


# ---- EXIF --------------------------------------------------------------------
def _jpeg_with_exif(focal=(240, 10), focal_35=36, model=b"Camera X\x00",
                    order="<"):
    """A JPEG start with an APP1 EXIF block written by hand."""
    bo = b"II" if order == "<" else b"MM"
    # IFD0: Model, Orientation, ExifIFD pointer. Offsets from TIFF start.
    ifd0_at = 8
    n0 = 3
    ifd0_size = 2 + 12 * n0 + 4
    model_at = ifd0_at + ifd0_size
    exif_at = model_at + len(model)
    n1 = 2
    exif_size = 2 + 12 * n1 + 4
    rational_at = exif_at + exif_size
    p = lambda fmt, *v: struct.pack(order + fmt, *v)
    tiff = bo + p("H", 42) + p("I", ifd0_at)
    tiff += p("H", n0)
    tiff += p("HHI", 0x0110, 2, len(model)) + p("I", model_at)
    tiff += p("HHI", 0x0112, 3, 1) + p("H", 1) + b"\x00\x00"
    tiff += p("HHI", 0x8769, 4, 1) + p("I", exif_at)
    tiff += p("I", 0)
    tiff += model
    tiff += p("H", n1)
    tiff += p("HHI", 0x920A, 5, 1) + p("I", rational_at)
    tiff += p("HHI", 0xA405, 3, 1) + p("H", focal_35) + b"\x00\x00"
    tiff += p("I", 0)
    tiff += p("II", *focal)
    app1 = b"Exif\x00\x00" + tiff
    return (b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2)
            + app1 + b"\xff\xd9")


@pytest.mark.parametrize("order", ["<", ">"])
def test_exif_focal_length_and_model(order):
    exif = PM.read_exif(_jpeg_with_exif(order=order))
    assert exif["focal_mm"] == pytest.approx(24.0)
    assert exif["focal_35"] == 36.0
    assert exif["model"] == "Camera X"
    assert exif["orientation"] == 1


def test_exif_of_something_else_is_empty():
    assert PM.read_exif(b"\x89PNG\r\n\x1a\n...") == {}
    assert PM.read_exif(b"\xff\xd8\xff\xe1\x00") == {}
    assert PM.read_exif(b"") == {}


def test_a_new_photo_takes_its_exif_focal_length():
    pm = PM.new_photo_match("a.jpg", _jpeg_with_exif(), 1500, 1000)
    assert pm.exif_focal_35 == 36.0
    assert pm.exif_model == "Camera X"
    assert (pm.width_px, pm.height_px) == (1500, 1000)


# ---- The viewport's camera ----------------------------------------------------
def _screen_point(camera, p, w, h):
    from PySide6.QtGui import QVector3D, QVector4D
    mvp = camera.projection_matrix() * camera.view_matrix()
    c = mvp.map(QVector4D(QVector3D(*p), 1.0))
    x, y = c.x() / c.w(), c.y() / c.w()
    return ((x + 1.0) / 2.0 * w, (1.0 - y) / 2.0 * h)


@pytest.mark.parametrize("spec", CAMERAS)
@pytest.mark.parametrize("view", [(1200, 800), (900, 900), (1600, 700)])
def test_the_viewport_draws_the_box_where_the_photo_shows_it(spec, view):
    """The orbit camera built from the calibration, in views wider and
    narrower than the photo: every corner of the box lands on its pixel of
    the photo, inside the photo's frame."""
    from core.camera import OrbitCamera, frame_rect
    w, h = view
    cam = FakeCamera(**spec)
    pm = _photo(cam)
    sol = PM.solve(pm)
    oc = OrbitCamera()
    oc.aspect = w / h
    PM.apply_to_camera(sol, pm.aspect, oc, w, h)
    fx, fy, fw, fh = frame_rect(w, h, pm.aspect)
    for p in [(0, 0, 0), (6, 0, 0), (0, 5, 3), (6, 0, 3), (2, 0, 1.5)]:
        u, v = cam.uv(p)
        want = (fx + u * fw, fy + v * fh)
        assert _screen_point(oc, p, w, h) == pytest.approx(want, abs=1e-2)


def test_the_signature_follows_the_camera():
    from core.camera import OrbitCamera
    oc = OrbitCamera()
    before = PM.camera_signature(oc)
    assert PM.camera_signature(oc) == before
    oc.orbit(10, 0, 800) if hasattr(oc, "orbit") else None
    oc.yaw += 0.1
    assert PM.camera_signature(oc) != before


# ---- What the panel and the right-click menu do -----------------------------
@pytest.mark.parametrize("preset", sorted(PM.PRESETS))
def test_every_start_gives_a_camera_standing_up(preset):
    pm = PM.PhotoMatch(width_px=1500, height_px=1000)
    pm.scale_length = 4.0
    pm.reset_lines(preset)
    sol = PM.solve(pm)
    assert 15.0 < sol.fov_deg < 80.0
    assert sol.up[2] > 0.9
    assert pm.scale_length == 4.0            # the scale stays
    assert pm.origin == list(PM.PRESETS[preset][2])


def test_swapping_red_and_green_turns_the_model_a_quarter():
    cam = FakeCamera(**CAMERAS[0])
    pm = _photo(cam)
    before = PM.solve(pm)
    pm.swap_axes()
    after = PM.solve(pm)
    # The camera's own axes in world terms: red and green traded places,
    # blue the same.
    assert after.focal == pytest.approx(before.focal)
    assert after.eye[2] == pytest.approx(before.eye[2], abs=1e-6)
    assert abs(after.right[0]) == pytest.approx(abs(before.right[1]),
                                                abs=1e-6)
    pm.swap_axes()
    assert PM.solve(pm).eye == pytest.approx(before.eye)


def test_how_the_photo_is_drawn_over_the_model():
    pm = PM.PhotoMatch()
    # In front by default, half opaque: the photo stays in sight.
    assert pm.photo_front
    assert pm.overlay_opacity() == pytest.approx(0.5)
    assert "photo_front" not in pm.to_dict()
    pm.photo_front = False
    assert pm.overlay_opacity() is None          # behind only
    assert PM.PhotoMatch.from_dict(pm.to_dict()).photo_front is False
    pm.photo_front = True
    pm.photo_opacity = 0.3
    assert pm.overlay_opacity() == pytest.approx(0.3)
    pm.show_model = False
    assert pm.overlay_opacity() == 1.0           # model hidden: whole
    back = PM.PhotoMatch.from_dict(pm.to_dict())
    assert (back.photo_front, back.photo_opacity, back.show_model) == (
        True, pytest.approx(0.3), False)
    assert PM.PhotoMatch.from_dict({"photo_opacity": "x"}).photo_opacity \
        == 0.5


def test_grid_lines_lie_on_the_planes_asked():
    segs = PM.grid_segments(["xy"], 1.0, count=4)
    assert len(segs) == 2 * 5
    assert all(a[2] == 0.0 and b[2] == 0.0 for a, b in segs)
    assert max(max(a[0], b[0]) for a, b in segs) == pytest.approx(4.0)
    both = PM.grid_segments(["xy", "yz"], 0.5, count=2)
    assert any(a[0] == 0.0 and b[0] == 0.0 and b[2] > 0 for a, b in both)
    assert PM.grid_segments(["xy"], 0.0) == []
    assert PM.grid_segments(["nope"], 1.0) == []


def test_a_segment_behind_the_camera_is_cut_where_it_passes():
    cam = FakeCamera(**CAMERAS[0])
    sol = PM.solve(_photo(cam))
    # Wholly in front: the photo's own projection.
    seg = PM.project_segment(sol, (0, 0, 0), (6, 0, 0))
    assert seg[0] == pytest.approx(sol.project((0, 0, 0)))
    assert seg[1] == pytest.approx(sol.project((6, 0, 0)))
    # From the box to far behind the eye: cut, never flipped through it.
    behind = tuple(e - 50 * f for e, f in zip(sol.eye, sol.forward))
    seg = PM.project_segment(sol, (0, 0, 0), behind)
    assert seg is not None
    assert seg[0] == pytest.approx(sol.project((0, 0, 0)))
    assert PM.project_segment(sol, behind, tuple(
        e - 60 * f for e, f in zip(sol.eye, sol.forward))) is None
