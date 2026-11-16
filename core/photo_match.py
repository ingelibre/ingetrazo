# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Camera ▸ Camera from Photo: the camera that took a photograph.

The user lays two red lines over edges of the photo that run along the red
axis (X) and two green lines over edges along the green axis (Y) — the
courses of a facade and of the wall round the corner. Each pair meets at
a vanishing point; the two vanishing points of two perpendicular
directions give the focal length and the turn of the camera, the textbook
calibration from vanishing points. An origin dragged onto a corner of the
photo anchors the model, and a length along the blue axis (Z) from it
gives the scale. The result is an ordinary camera — eye, sight line, roll
and angle of view — that :func:`apply_to_camera` hands to the viewport, so
the model drawn over the photo lines up with it.

Coordinates
-----------
Handles are kept in PHOTO coordinates ``(u, v)``: 0..1 across the picture,
``v`` downwards, so they stay put whatever size the photo is shown at. The
maths runs in IMAGE coordinates ``(x, y)``: the centre of the photo is
``(0, 0)``, ``y`` upwards, and half the photo's height is 1 — the photo runs
from ``-aspect`` to ``aspect`` across and from -1 to 1 up. A focal length
``f`` in those units is ``1 / tan(vertical angle of view / 2)``.

The camera looks down its own ``-z``, with ``x`` to the right and ``y`` up
(the OpenGL eye space): a point ``(x, y)`` of the image is the ray
``(x, y, -f)``.

Nothing here needs a window: the module is pure maths plus the EXIF reader,
and is tested on cameras made up for the purpose (tests/test_photo_match.py).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field


# ---- Small vector helpers (3-tuples) ----------------------------------------
def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a):
    n = math.sqrt(_dot(a, a))
    if n < 1e-15 or not math.isfinite(n):
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


# ---- Defaults ---------------------------------------------------------------
#: Where the lines start on a new photo: the red pair over the right half,
#: converging to the right, the green pair over the left, converging to the
#: left — a corner seen from in front, the shot this works best with. The
#: user drags each end onto the photo's edges.
DEFAULT_X_LINES = (((0.55, 0.35), (0.90, 0.42)),
                   ((0.55, 0.70), (0.90, 0.62)))
DEFAULT_Y_LINES = (((0.10, 0.42), (0.45, 0.35)),
                   ((0.10, 0.62), (0.45, 0.70)))
DEFAULT_ORIGIN = (0.50, 0.75)

#: Where the lines start for each kind of photo (the panel's «Start
#: from»): ``(x_lines, y_lines, origin)``. OUTSIDE: a corner seen from the
#: street, both walls running away. INSIDE: the corner of a room, its walls
#: coming toward the camera, so each pair meets beyond the other wall.
#: ABOVE: a block seen from high up, the horizon over the top of the
#: picture.
PRESETS = {
    "outside": (DEFAULT_X_LINES, DEFAULT_Y_LINES, DEFAULT_ORIGIN),
    "inside": ((((0.62, 0.32), (0.95, 0.24)), ((0.62, 0.70), (0.95, 0.78))),
               (((0.05, 0.24), (0.38, 0.32)), ((0.05, 0.78), (0.38, 0.70))),
               (0.50, 0.72)),
    "above": ((((0.55, 0.55), (0.90, 0.40)), ((0.55, 0.85), (0.90, 0.62))),
              (((0.10, 0.40), (0.45, 0.55)), ((0.10, 0.62), (0.45, 0.85))),
              (0.50, 0.80)),
}
#: The blue handle starts this far above the origin, in photo heights, and
#: means this many metres — a storey — until the user says otherwise.
DEFAULT_SCALE_UP = 0.25
DEFAULT_SCALE_LENGTH = 3.0

#: A calibrated focal length further than this from the photo's own (EXIF)
#: is worth a word: the lines are probably not on parallel edges.
FOCAL_MISMATCH = 0.15


# ---- Errors -----------------------------------------------------------------
class CalibrationError(ValueError):
    """The lines as they lie give no camera. ``key`` names the reason (for
    tests); ``str()`` is the English message the tool translates."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(message)
        self.key = key


# ---- The calibration --------------------------------------------------------
@dataclass
class PhotoMatch:
    """A photo and the handles laid over it, as a scene keeps them."""

    path: str = ""
    width_px: int = 0
    height_px: int = 0
    x_lines: list = field(default_factory=lambda: [
        [list(p) for p in ln] for ln in DEFAULT_X_LINES])
    y_lines: list = field(default_factory=lambda: [
        [list(p) for p in ln] for ln in DEFAULT_Y_LINES])
    origin: list = field(default_factory=lambda: list(DEFAULT_ORIGIN))
    #: The blue handle: a point of the photo on the blue axis above the
    #: origin, and the real distance it stands for, metres.
    scale_point: list | None = None
    scale_length: float = DEFAULT_SCALE_LENGTH
    #: The photo's own focal length as its camera wrote it (EXIF), as the
    #: 35 mm equivalent, or ``None``.
    exif_focal_35: float | None = None
    #: The camera model the EXIF names, shown beside its focal length.
    exif_model: str = ""
    #: Keep the EXIF focal length instead of reading it from the lines
    #: (the lines then only turn the camera).
    use_exif_focal: bool = False
    #: How the photo shows (the panel): drawn IN FRONT of the model at
    #: ``photo_opacity`` — the default: the photo stays in sight however
    #: much of the model is drawn — and whether the model shows at all;
    #: without it the photo is seen whole, with only the lines over it.
    photo_front: bool = True
    photo_opacity: float = 0.5
    show_model: bool = True

    def __post_init__(self) -> None:
        if self.scale_point is None:
            self.scale_point = [self.origin[0],
                                self.origin[1] - DEFAULT_SCALE_UP]

    # ---- Shape ----
    @property
    def aspect(self) -> float:
        """Width over height of the photo (3:2 when its size is unknown)."""
        if self.width_px > 0 and self.height_px > 0:
            return self.width_px / self.height_px
        return 1.5

    def to_image(self, uv) -> tuple[float, float]:
        """Photo ``(u, v)`` → image ``(x, y)`` (see the module notes)."""
        return ((float(uv[0]) - 0.5) * 2.0 * self.aspect,
                (0.5 - float(uv[1])) * 2.0)

    def to_photo(self, xy) -> tuple[float, float]:
        """Image ``(x, y)`` → photo ``(u, v)``."""
        return (xy[0] / (2.0 * self.aspect) + 0.5, 0.5 - xy[1] / 2.0)

    # ---- Handles ----
    def handles(self) -> dict:
        """Every draggable point by name: ``x0a``, ``x0b``… the ends of the
        lines, ``origin`` and ``scale``."""
        out = {}
        for axis, lines in (("x", self.x_lines), ("y", self.y_lines)):
            for i, ln in enumerate(lines):
                out[f"{axis}{i}a"] = tuple(ln[0])
                out[f"{axis}{i}b"] = tuple(ln[1])
        out["origin"] = tuple(self.origin)
        out["scale"] = tuple(self.scale_point)
        return out

    def set_handle(self, name: str, uv) -> None:
        """Move the handle ``name`` to photo point ``uv``."""
        uv = [float(uv[0]), float(uv[1])]
        if name == "origin":
            # The blue handle goes with the origin: the length it measures
            # starts there.
            du = uv[0] - self.origin[0]
            dv = uv[1] - self.origin[1]
            self.origin = uv
            self.scale_point = [self.scale_point[0] + du,
                                self.scale_point[1] + dv]
            return
        if name == "scale":
            self.scale_point = uv
            return
        lines = self.x_lines if name[0] == "x" else self.y_lines
        lines[int(name[1])][0 if name[2] == "a" else 1] = uv

    # ---- Serialisation ----
    def to_dict(self) -> dict:
        """What a scene writes. The photo hangs under ``"texture"`` so the
        document embeds it like any face texture (formats/igz.py)."""
        out = {
            "texture": {"path": self.path},
            "size": [int(self.width_px), int(self.height_px)],
            "x_lines": [[list(p) for p in ln] for ln in self.x_lines],
            "y_lines": [[list(p) for p in ln] for ln in self.y_lines],
            "origin": list(self.origin),
            "scale_point": list(self.scale_point),
            "scale_length": float(self.scale_length),
        }
        if self.exif_focal_35:
            out["exif_focal_35"] = float(self.exif_focal_35)
        if self.exif_model:
            out["exif_model"] = self.exif_model
        if self.use_exif_focal:
            out["use_exif_focal"] = True
        if not self.photo_front:
            out["photo_front"] = False
        if self.photo_opacity != 0.5:
            out["photo_opacity"] = float(self.photo_opacity)
        if not self.show_model:
            out["show_model"] = False
        return out

    @classmethod
    def from_dict(cls, raw) -> "PhotoMatch | None":
        """A calibration from a scene's ``"photo"`` entry; ``None`` when the
        entry is not one. Handles that are not numbers fall back to their
        defaults, so a hand-edited document still opens."""
        if not isinstance(raw, dict):
            return None
        tex = raw.get("texture")
        path = tex.get("path", "") if isinstance(tex, dict) else ""

        def point(v, default):
            try:
                p = [float(v[0]), float(v[1])]
            except (TypeError, ValueError, IndexError, KeyError):
                return list(default)
            return p if all(math.isfinite(c) for c in p) else list(default)

        def lines(v, default):
            out = []
            for i in range(2):
                try:
                    ln = v[i] if isinstance(v, (list, tuple)) else None
                except IndexError:
                    ln = None
                if not (isinstance(ln, (list, tuple)) and len(ln) == 2):
                    ln = (None, None)
                out.append([point(ln[0], default[i][0]),
                            point(ln[1], default[i][1])])
            return out

        size = raw.get("size") or [0, 0]
        try:
            w, h = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            w, h = 0, 0
        origin = point(raw.get("origin"), DEFAULT_ORIGIN)
        try:
            length = float(raw.get("scale_length", DEFAULT_SCALE_LENGTH))
        except (TypeError, ValueError):
            length = DEFAULT_SCALE_LENGTH
        if not (math.isfinite(length) and length > 0.0):
            length = DEFAULT_SCALE_LENGTH
        focal = raw.get("exif_focal_35")
        try:
            focal = float(focal) if focal is not None else None
        except (TypeError, ValueError):
            focal = None
        return cls(path=str(path or ""), width_px=max(0, w),
                   height_px=max(0, h),
                   x_lines=lines(raw.get("x_lines"), DEFAULT_X_LINES),
                   y_lines=lines(raw.get("y_lines"), DEFAULT_Y_LINES),
                   origin=origin,
                   scale_point=point(raw.get("scale_point"),
                                     (origin[0],
                                      origin[1] - DEFAULT_SCALE_UP)),
                   scale_length=length,
                   exif_focal_35=focal if focal and focal > 0 else None,
                   exif_model=str(raw.get("exif_model", "") or ""),
                   use_exif_focal=bool(raw.get("use_exif_focal", False)),
                   photo_front=bool(raw.get("photo_front", True)),
                   photo_opacity=_opacity(raw.get("photo_opacity", 0.5)),
                   show_model=bool(raw.get("show_model", True)))

    def copy(self) -> "PhotoMatch":
        return PhotoMatch.from_dict(self.to_dict())

    # ---- What the panel and the right-click menu do ----
    def reset_lines(self, preset: str = "outside") -> None:
        """The lines, the origin and the blue handle back where they start
        for the kind of photo ``preset`` (:data:`PRESETS`). The length the
        blue handle stands for and the display options stay."""
        xs, ys, origin = PRESETS.get(preset, PRESETS["outside"])
        self.x_lines = [[list(p) for p in ln] for ln in xs]
        self.y_lines = [[list(p) for p in ln] for ln in ys]
        self.origin = list(origin)
        self.scale_point = [origin[0], origin[1] - DEFAULT_SCALE_UP]

    def swap_axes(self) -> None:
        """Red lines become green and green red: for lines laid the wrong
        way round (the model then turns a quarter about the blue axis)."""
        self.x_lines, self.y_lines = self.y_lines, self.x_lines

    def overlay_opacity(self) -> float | None:
        """How opaque the photo is drawn OVER the model, or ``None`` when
        it is only behind: whole without the model, else as set."""
        if not self.show_model:
            return 1.0
        if self.photo_front:
            return max(0.05, min(1.0, float(self.photo_opacity)))
        return None


def _opacity(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0.05, min(1.0, v)) if math.isfinite(v) else 0.5


def vanishing_point(line_a, line_b):
    """Where two image lines ``((x, y), (x, y))`` meet, as ``(x, y)``, or
    ``None`` when they are parallel in the picture (their point is at
    infinity)."""
    def homog(ln):
        (x0, y0), (x1, y1) = ln
        return _cross((x0, y0, 1.0), (x1, y1, 1.0))
    la, lb = homog(line_a), homog(line_b)
    if _norm(la) is None or _norm(lb) is None:
        return None
    p = _cross(la, lb)
    # Parallel to within a hair: the point would lie thousands of photo
    # heights away and its direction is all the noise of the drag.
    scale = max(abs(p[0]), abs(p[1]), 1e-300)
    if abs(p[2]) < 1e-9 * scale:
        return None
    return (p[0] / p[2], p[1] / p[2])


@dataclass
class Solution:
    """The camera found: what the viewport needs and what the tool shows."""

    #: Focal length in image units (half the photo's height = 1).
    focal: float
    #: World → camera rotation, as its three ROWS: the camera's right, up
    #: and back (+z) axes in world coordinates.
    right: tuple
    up: tuple
    back: tuple
    #: The eye in world coordinates, metres.
    eye: tuple
    #: The two vanishing points in image coordinates.
    vp_x: tuple
    vp_y: tuple
    #: Whether the green axis had to point the other way for blue to point
    #: up (the green lines then run toward the camera from the origin).
    flipped_y: bool = False

    @property
    def forward(self) -> tuple:
        return _mul(self.back, -1.0)

    @property
    def fov_deg(self) -> float:
        """The photo's vertical angle of view."""
        return math.degrees(2.0 * math.atan(1.0 / self.focal))

    def to_camera(self, p) -> tuple:
        """A world point in the camera's own axes."""
        d = _sub(p, self.eye)
        return (_dot(d, self.right), _dot(d, self.up), _dot(d, self.back))

    def project(self, p):
        """World point → image ``(x, y)``, or ``None`` behind the camera."""
        c = self.to_camera(p)
        if c[2] > -1e-12:
            return None
        return (-self.focal * c[0] / c[2], -self.focal * c[1] / c[2])

    def axis_image_direction(self, origin_xy, axis) -> tuple | None:
        """The direction, in the image, of the world ``axis`` (a unit
        3-tuple) leaving the point seen at ``origin_xy`` — where the blue
        handle slides."""
        cam = (_dot(axis, self.right), _dot(axis, self.up),
               _dot(axis, self.back))
        # The image of the point at infinity along the axis.
        if abs(cam[2]) > 1e-9:
            vx = -self.focal * cam[0] / cam[2]
            vy = -self.focal * cam[1] / cam[2]
            d = (vx - origin_xy[0], vy - origin_xy[1])
            if cam[2] > 0:           # the vanishing point is behind
                d = (-d[0], -d[1])
        else:
            d = (cam[0], cam[1])
        n = math.hypot(d[0], d[1])
        if n < 1e-12:
            return None
        return (d[0] / n, d[1] / n)


def solve(pm: PhotoMatch, fixed_focal: float | None = None) -> Solution:
    """The camera of ``pm``. Raises :class:`CalibrationError` when the
    lines give none. ``fixed_focal`` (image units) imposes the focal length
    instead of reading it from the two vanishing points — the photo's own,
    from its EXIF."""
    to_img = pm.to_image
    xl = [(to_img(a), to_img(b)) for a, b in pm.x_lines]
    yl = [(to_img(a), to_img(b)) for a, b in pm.y_lines]
    for ln in xl + yl:
        if math.hypot(ln[1][0] - ln[0][0], ln[1][1] - ln[0][1]) < 1e-6:
            raise CalibrationError(
                "short", "A line's two ends are on the same point.")
    vx = vanishing_point(*xl)
    if vx is None:
        raise CalibrationError(
            "parallel_x", "The two red lines are parallel: lay them on "
            "edges that meet far away, in perspective.")
    vy = vanishing_point(*yl)
    if vy is None:
        raise CalibrationError(
            "parallel_y", "The two green lines are parallel: lay them on "
            "edges that meet far away, in perspective.")
    if math.hypot(vx[0] - vy[0], vx[1] - vy[1]) < 1e-6:
        raise CalibrationError(
            "same_point", "The red and the green lines meet at the same "
            "point: they must follow two different directions.")
    if fixed_focal is not None and fixed_focal > 0.0:
        f = float(fixed_focal)
    else:
        # Two perpendicular directions: their rays through the vanishing
        # points are perpendicular, (vx, -f)·(vy, -f) = 0.
        f2 = -(vx[0] * vy[0] + vx[1] * vy[1])
        if not (f2 > 1e-9):
            raise CalibrationError(
                "focal", "The red and green lines do not meet at a right "
                "angle in this photo: their vanishing points must lie on "
                "either side of the centre, far enough apart.")
        f = math.sqrt(f2)
    dx = _norm((vx[0], vx[1], -f))
    dy = _norm((vy[0], vy[1], -f))
    if dx is None or dy is None:
        raise CalibrationError("focal", "No camera fits these lines.")
    # With a fixed focal length the two rays need not be quite square:
    # keep red and square green to it.
    dy = _norm(_sub(dy, _mul(dx, _dot(dx, dy))))
    if dy is None:
        raise CalibrationError("same_point", "No camera fits these lines.")
    dz = _cross(dx, dy)
    flipped = False
    if dz[1] < 0.0:
        # Blue must point up in the picture: the green axis goes the other
        # way, toward the camera from the origin.
        dy = _mul(dy, -1.0)
        dz = _mul(dz, -1.0)
        flipped = True
    # dx, dy, dz: the world axes in camera coordinates — the columns of
    # the world → camera rotation. Its rows are the camera's axes in world
    # coordinates.
    right = (dx[0], dy[0], dz[0])
    up = (dx[1], dy[1], dz[1])
    back = (dx[2], dy[2], dz[2])
    # Where the camera stands: the origin lies along the ray through its
    # handle, at the depth that makes the blue length come out right.
    ox, oy = to_img(pm.origin)
    sx, sy = to_img(pm.scale_point)
    r_o = (ox, oy, -f)
    r_s = (sx, sy, -f)
    a = _cross(r_o, r_s)
    b = _cross(dz, r_s)
    aa = _dot(a, a)
    if aa < 1e-18:
        raise CalibrationError(
            "scale", "Drag the blue handle away from the origin, up the "
            "blue axis.")
    # O = s·r_o, P = O + L·z must lie on the ray r_s: s·a + L·b = 0.
    s = -float(pm.scale_length) * _dot(b, a) / aa
    if not (s > 0.0 and math.isfinite(s)):
        raise CalibrationError(
            "scale", "The blue handle must be above the origin, up the "
            "blue axis.")
    o_cam = _mul(r_o, s)
    # o_cam = R·(0 − eye) → eye = −Rᵀ·o_cam.
    eye = (-(o_cam[0] * right[0] + o_cam[1] * up[0] + o_cam[2] * back[0]),
           -(o_cam[0] * right[1] + o_cam[1] * up[1] + o_cam[2] * back[1]),
           -(o_cam[0] * right[2] + o_cam[1] * up[2] + o_cam[2] * back[2]))
    return Solution(focal=f, right=right, up=up, back=back, eye=eye,
                    vp_x=vx, vp_y=vy, flipped_y=flipped)


def solve_match(pm: PhotoMatch) -> Solution:
    """:func:`solve` as the photo asks: with its EXIF focal length kept
    when it says so and has one."""
    if pm.use_exif_focal and pm.exif_focal_35:
        return solve(pm, focal_from_35mm(pm.exif_focal_35, pm.aspect))
    return solve(pm)


def grid_segments(planes, spacing: float, count: int = 12) -> list:
    """World segments of a grid on the axis planes named in ``planes``
    (``"xy"`` red-green, ``"xz"`` red-blue, ``"yz"`` green-blue), lines
    every ``spacing`` metres from the origin out to ``count`` of them on
    the positive side of each axis — where a corner's walls and floor are.
    It shows whether the photo's edges run along the axes, and how far."""
    s = float(spacing)
    if not (s > 0.0 and math.isfinite(s)):
        return []
    n = max(1, int(count))
    L = n * s
    out = []
    for plane in planes:
        a, b = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}.get(plane,
                                                             (None, None))
        if a is None:
            continue
        for k in range(n + 1):
            t = k * s
            p0 = [0.0, 0.0, 0.0]
            p1 = [0.0, 0.0, 0.0]
            p0[a], p1[a], p1[b] = t, t, L          # lines along b
            out.append((tuple(p0), tuple(p1)))
            q0 = [0.0, 0.0, 0.0]
            q1 = [0.0, 0.0, 0.0]
            q0[b], q1[b], q1[a] = t, t, L          # lines along a
            out.append((tuple(q0), tuple(q1)))
    return out


def project_segment(sol: Solution, a, b, near: float = 1e-3):
    """The segment ``a``–``b`` (world) in image coordinates, cut where it
    passes behind the camera; ``None`` when all of it is behind."""
    ca, cb = sol.to_camera(a), sol.to_camera(b)
    za, zb = -ca[2], -cb[2]                 # depth in front of the eye
    if za < near and zb < near:
        return None
    if za < near or zb < near:
        t = (near - za) / (zb - za)
        cut = tuple(ca[i] + (cb[i] - ca[i]) * t for i in range(3))
        if za < near:
            ca = cut
        else:
            cb = cut

    def img(c):
        return (-sol.focal * c[0] / c[2], -sol.focal * c[1] / c[2])
    return img(ca), img(cb)


def snap_scale_to_axis(pm: PhotoMatch, sol: Solution) -> None:
    """Put the blue handle back ON the image of the blue axis (it drifts
    off it when the lines move), keeping its distance from the origin."""
    o = pm.to_image(pm.origin)
    s = pm.to_image(pm.scale_point)
    d = sol.axis_image_direction(o, (0.0, 0.0, 1.0))
    if d is None:
        return
    t = (s[0] - o[0]) * d[0] + (s[1] - o[1]) * d[1]
    if t <= 1e-4:
        t = max(math.hypot(s[0] - o[0], s[1] - o[1]), 0.05)
    p = (o[0] + d[0] * t, o[1] + d[1] * t)
    pm.scale_point = list(pm.to_photo(p))


def horizon(sol: Solution) -> tuple:
    """The horizon as two image points: the line through both vanishing
    points (level lines all vanish on it)."""
    return (sol.vp_x, sol.vp_y)


# ---- Focal lengths in millimetres -------------------------------------------
def focal_35mm(focal: float, aspect: float) -> float:
    """A focal length in image units as the 35 mm equivalent: on the full
    frame, a picture of shape ``aspect`` uses ``sensor_picture_height`` of
    its 24 mm — the same reading the camera settings give."""
    from core.camera import FULL_FRAME, sensor_picture_height
    return focal * sensor_picture_height(FULL_FRAME, aspect) / 2.0


def focal_from_35mm(focal_mm: float, aspect: float) -> float:
    """Inverse of :func:`focal_35mm`."""
    from core.camera import FULL_FRAME, sensor_picture_height
    return 2.0 * focal_mm / sensor_picture_height(FULL_FRAME, aspect)


def focal_mismatch(pm: PhotoMatch, sol: Solution) -> float | None:
    """How far the calibrated focal length is from the photo's own, as a
    fraction (0.2 = 20 %), or ``None`` without an EXIF focal length."""
    if not pm.exif_focal_35:
        return None
    mine = focal_35mm(sol.focal, pm.aspect)
    return abs(mine - pm.exif_focal_35) / pm.exif_focal_35


# ---- The viewport's camera ----------------------------------------------------
def view_fov_deg(sol: Solution, aspect: float, view_w: float,
                 view_h: float) -> float:
    """The viewport's vertical angle of view that shows the photo's
    picture inside its frame (``core.camera.frame_rect``): when the view
    is narrower than the photo, the frame is less tall than the view and
    the view must see more."""
    from core.camera import frame_rect
    rect = frame_rect(view_w, view_h, aspect)
    ratio = 1.0 if rect is None else view_h / max(rect[3], 1e-9)
    return math.degrees(2.0 * math.atan(ratio / sol.focal))


def apply_to_camera(sol: Solution, aspect: float, camera, view_w: float,
                    view_h: float) -> None:
    """Point the orbit ``camera`` as the photo's camera: eye, sight line,
    roll, angle of view and the photo's frame. The orbit centre is put on
    the sight line at the origin's depth, so orbiting away turns about the
    model."""
    from PySide6.QtGui import QVector3D
    from core.camera import FOV_RANGE
    eye = QVector3D(*sol.eye)
    fwd = sol.forward
    depth = -sol.to_camera((0.0, 0.0, 0.0))[2]
    depth = depth if depth > 1e-3 else 10.0
    camera.perspective = True
    camera.two_point = False
    camera.shift_x = camera.shift_y = 0.0
    camera.roll_deg = 0.0
    camera.frame_aspect = float(aspect)
    camera.distance = float(depth)
    camera.look_from(eye, QVector3D(*fwd))
    # look_from keeps the pitch just off the pole; the eye stays where it is.
    # The roll: how far the photo's up is turned from the camera's level up
    # about the sight line.
    f = camera.forward()
    base = camera.up_vector()
    want = QVector3D(*sol.up)
    cr = QVector3D.crossProduct(base, want)
    roll = math.degrees(math.atan2(QVector3D.dotProduct(f, cr),
                                   QVector3D.dotProduct(base, want)))
    camera.roll_deg = roll if abs(roll) > 1e-9 else 0.0
    lo, hi = FOV_RANGE
    camera.fov_deg = max(lo, min(hi, view_fov_deg(sol, aspect, view_w,
                                                  view_h)))


def camera_signature(camera) -> tuple:
    """The camera as a value: when it changes behind the photo's back (an
    orbit, a pan, a zoom, another scene), the photo no longer matches and
    the view leaves the photo."""
    e = camera.eye()
    t = camera.target
    return (round(e.x(), 6), round(e.y(), 6), round(e.z(), 6),
            round(t.x(), 6), round(t.y(), 6), round(t.z(), 6),
            round(camera.fov_deg, 6), bool(camera.perspective),
            round(float(camera.roll_deg), 6), float(camera.shift_x),
            float(camera.shift_y), bool(getattr(camera, "two_point", False)))


# ---- EXIF --------------------------------------------------------------------
def read_exif(data: bytes) -> dict:
    """The little of a JPEG's EXIF that matters here: ``focal_mm``,
    ``focal_35`` (the 35 mm equivalent), ``model``, ``orientation``.
    Missing tags are left out; anything that is not a readable JPEG with
    EXIF gives ``{}``. Written from the EXIF 2.3 layout (a TIFF block in
    the APP1 segment), nothing else read."""
    try:
        return _read_exif(data)
    except (struct.error, IndexError, ValueError, ZeroDivisionError):
        return {}


def _read_exif(data: bytes) -> dict:
    if data[:2] != b"\xff\xd8":
        return {}
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return {}
        marker = data[i + 1]
        if marker in (0xD9, 0xDA):          # end of image / start of scan
            return {}
        size = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
            return _read_tiff(data[i + 10:i + 2 + size])
        i += 2 + size
    return {}


def _read_tiff(t: bytes) -> dict:
    order = {b"II": "<", b"MM": ">"}.get(t[:2])
    if order is None:
        return {}
    first = struct.unpack(order + "I", t[4:8])[0]
    out: dict = {}

    def entries(at):
        n = struct.unpack(order + "H", t[at:at + 2])[0]
        for k in range(n):
            e = at + 2 + 12 * k
            tag, typ, count = struct.unpack(order + "HHI", t[e:e + 8])
            yield tag, typ, count, e + 8

    def value(typ, count, at):
        sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1}
        size = sizes.get(typ, 1) * count
        where = at if size <= 4 else struct.unpack(order + "I",
                                                    t[at:at + 4])[0]
        raw = t[where:where + size]
        if typ == 2:
            return raw.split(b"\x00", 1)[0].decode("latin-1").strip()
        if typ == 3:
            return struct.unpack(order + "H", raw[:2])[0]
        if typ == 4:
            return struct.unpack(order + "I", raw[:4])[0]
        if typ == 5:
            num, den = struct.unpack(order + "II", raw[:8])
            return num / den if den else None
        return None

    exif_at = None
    for tag, typ, count, at in entries(first):
        if tag == 0x0110:
            out["model"] = value(typ, count, at)
        elif tag == 0x0112:
            out["orientation"] = value(typ, count, at)
        elif tag == 0x8769:
            exif_at = value(typ, count, at)
    if exif_at:
        for tag, typ, count, at in entries(exif_at):
            if tag == 0x920A:
                v = value(typ, count, at)
                if v:
                    out["focal_mm"] = v
            elif tag == 0xA405:
                v = value(typ, count, at)
                if v:
                    out["focal_35"] = float(v)
    return {k: v for k, v in out.items() if v not in (None, "")}


def new_photo_match(path: str, data: bytes, width_px: int,
                    height_px: int) -> PhotoMatch:
    """A calibration for a freshly loaded photo: the handles where they
    start, and the photo's own focal length when its EXIF has one."""
    exif = read_exif(data)
    return PhotoMatch(path=path, width_px=int(width_px),
                      height_px=int(height_px),
                      exif_focal_35=exif.get("focal_35"),
                      exif_model=str(exif.get("model", "") or ""))


def load_photo(path: str) -> PhotoMatch:
    """Read the photo at ``path`` into the texture cache and start its
    calibration. A photo the camera stored on its side (EXIF orientation)
    is stood upright first: the picture is drawn as the camera saw it, and
    its lines are laid on it that way up. Raises ``OSError`` when the file
    cannot be read or is not an image."""
    from pathlib import Path
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QImageIOHandler, QImageReader
    from core.texture import cache_image
    data = Path(path).read_bytes()
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise OSError(reader.errorString() or "not an image")
    name = Path(path).name
    stored = data
    upright = QImageIOHandler.Transformation.TransformationNone
    if reader.transformation() != upright:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "JPG", 92)
        buf.close()
        stored = bytes(ba)
        name = Path(path).stem + ".jpg"
    out = cache_image(stored, name, "photos")
    return new_photo_match(str(out), data, image.width(), image.height())
