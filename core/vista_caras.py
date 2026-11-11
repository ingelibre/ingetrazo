# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The faces of a view as flat filled shapes, for the vector exports.

:func:`view_faces` walks the model as the line drawing does
(:func:`core.hlr.collect_geometry`: the same visible objects, the same
section cut), projects every face with the camera into the same plane the
lines are drawn in (metres, true size; at the target's depth in
perspective) and keeps of each one only the part nothing nearer covers.
The visible parts never overlap, so the faces can go out layer by layer
in any order and an illustration program gets no buried pieces.

Each face carries the colour the viewport paints it: its own material,
else the nearest painted container's, else IngeTrazo's warm white (tinted
by the style's Front colour); the back colour when seen from behind; and,
with ``as_view``, the viewport's matte light from the face's orientation —
the same law and rounding as ``Viewport._shaded_color``, so a wall reads
white, light grey or grey as on screen. A textured face also carries the
texture and three points that pin its UV map to the drawing.
"""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np

#: The viewport's fixed matte light (``Viewport._LIGHT``): from above,
#: slightly front-right. A test keeps the two in step.
MATTE_LIGHT = np.array([0.35, 0.25, 1.0]) / math.sqrt(0.35 ** 2 + 0.25 ** 2
                                                      + 1.0)

#: Working scale of the visibility clipping: plane metres → millimetres,
#: so the area booleans run on comfortable numbers.
_K = 1.0e3

#: A face part smaller than this many square millimetres (true size) is
#: dropped — slivers the clipping leaves along shared edges.
_MIN_AREA_MM2 = 0.01

#: Faces less opaque than this cast no shadow — the sun passes through
#: glass (``Viewport._SHADOW_OPACITY_MIN``).
SHADOW_OPACITY_MIN = 0.7

#: The layer the shadows on the bare ground (z = 0) go out on.
GROUND_LAYER = "SUELO"


@dataclass
class FaceFill:
    """One face's visible part in the line drawing's plane (metres).

    ``rings`` — closed polylines ((M, 2) arrays), outer outlines and holes
    alike, to fill even-odd. ``rgb`` the colour as drawn (0–1), ``opacity``
    0–1, ``layer`` the layer it belongs to. ``texture`` — ``None`` or
    ``{"path", "shade", "uv"}`` with ``uv`` four ``((x, y), (u, v))``
    pairs: plane points and their texture coordinates, which fix the
    projective map of the image onto the face; ``shade`` is the light
    factor the image is darkened by (1 = as is). ``back`` — seen from
    behind. ``shadow`` — the rings of the part of it the sun does not
    reach (:func:`view_faces` with ``shadows``), and ``shadow_alpha`` how
    dark that is (a black veil of that opacity: the shadow settings'
    darkness)."""
    rings: list
    rgb: tuple
    layer: str
    opacity: float = 1.0
    texture: dict | None = None
    back: bool = False
    depth: float = 0.0
    extra: dict = field(default_factory=dict)
    shadow: list | None = None
    shadow_alpha: float = 0.0


def shade_factor(normal) -> float:
    """``Viewport._shade_factor``: 0.62 facing away from the light up to 1
    facing it, in 1/32 steps."""
    n = np.asarray(normal, dtype=np.float64)
    ln = float(np.linalg.norm(n))
    if ln < 1e-12:
        return 0.84375
    d = abs(float(n @ MATTE_LIGHT)) / ln
    return round((0.62 + 0.38 * d) * 32.0) / 32.0


def shaded(rgb, factor: float) -> tuple:
    """``Viewport._shaded_color``: ``rgb`` times ``factor``, in 1/64 steps."""
    return tuple(round(min(1.0, float(c) * factor) * 64.0) / 64.0
                 for c in rgb[:3])


def texture_average(path, cache={}) -> tuple | None:
    """The mean colour of the image at ``path`` (0–1), or ``None`` when it
    cannot be read — what a textured face shows without its texture."""
    if path in cache:
        return cache[path]
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    img = QImage(str(path))
    out = None
    if not img.isNull():
        px = img.scaled(1, 1, Qt.IgnoreAspectRatio,
                        Qt.SmoothTransformation).pixelColor(0, 0)
        out = (px.redF(), px.greenF(), px.blueF())
    cache[path] = out
    return out


# ── Projection ──────────────────────────────────────────────────────────────

class _Parallel:
    def __init__(self, camera):
        from core.hlr import camera_basis
        self.eye, self.right, self.up, self.fwd = camera_basis(camera)

    def facing_back(self, normal, centre) -> bool:
        return float(np.asarray(normal) @ self.fwd) > 0.0

    def ring(self, pts):
        """World (M,3) → plane (K,2) and depths (K,); clipping-free."""
        d = pts - self.eye
        return (np.stack([d @ self.right, d @ self.up], axis=1),
                d @ self.fwd)

    def point(self, p):
        xy, _ = self.ring(np.asarray([p], dtype=np.float64))
        return xy[0]


class _Perspective:
    """The projection of :func:`core.hlr.hlr_perspective`: metres on the
    picture plane through the target, origin at the view's centre."""

    def __init__(self, camera):
        m = camera.projection_matrix() * camera.view_matrix()
        self.M = np.array(m.data(), dtype=np.float64).reshape(4, 4,
                                                              order="F")
        e = camera.eye()
        self.eye_pt = np.array([e.x(), e.y(), e.z()])
        t = camera.target
        w_t = float(self._clip(np.array([t.x(), t.y(), t.z()]))[3])
        half_h = w_t * math.tan(math.radians(camera.fov_deg) / 2.0)
        self.scale = np.array([half_h * camera.aspect, half_h])
        self.ok = w_t > 1e-9

    def _clip(self, p):
        return p @ self.M[:, :3].T + self.M[:, 3]

    def facing_back(self, normal, centre) -> bool:
        return float(np.asarray(normal) @ (centre - self.eye_pt)) > 0.0

    def ring(self, pts):
        from core.hlr import _clip_polygon
        poly = _clip_polygon(list(self._clip(pts)))
        if len(poly) < 3:
            return np.empty((0, 2)), np.empty((0,))
        c = np.asarray(poly)
        w = c[:, 3]
        return c[:, :2] / w[:, None] * self.scale, w

    def point(self, p):
        c = self._clip(np.asarray(p, dtype=np.float64))
        if c[3] <= 1e-9:
            return None
        return c[:2] / c[3] * self.scale


def _clip_ring_to_section(pts, plane):
    """Sutherland–Hodgman of a world ring against the kept side of the
    section (``plane.side(p) <= 0``)."""
    n = np.array([plane.normal.x(), plane.normal.y(), plane.normal.z()])
    c = float(n @ np.array([plane.point.x(), plane.point.y(),
                            plane.point.z()]))
    d = pts @ n - c
    if (d <= 1e-9).all():
        return pts
    if (d > 1e-9).all():
        return pts[:0]
    out = []
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        if d[i] <= 1e-9:
            out.append(pts[i])
        if (d[i] <= 1e-9) != (d[j] <= 1e-9):
            t = d[i] / (d[i] - d[j])
            out.append(pts[i] + (pts[j] - pts[i]) * t)
    return np.asarray(out).reshape(-1, 3)


# ── The walk ────────────────────────────────────────────────────────────────

def _faces_of(scene):
    """``(face, matrix, paint, layer)`` for every face the line drawing
    sees: the loose model's visible faces and every visible object's
    placements, each with the paint its default faces wear."""
    from core.group import iter_painted_placements
    from core.layers import DEFAULT_LAYER, layer_of, object_layer, layer_paint
    style = getattr(scene, "display_style", None)
    by_layer = bool(getattr(style, "color_by_layer", False))
    loose_paint = layer_paint(scene, None) if by_layer else None
    for f in scene.loose_mesh.faces:
        if scene.entity_visible(f):
            yield f, None, loose_paint, layer_of(f)
    for g in scene.groups:
        if not scene.entity_visible(g) or getattr(g, "billboard", False):
            continue
        owner = object_layer(g)
        top = layer_paint(scene, g) if by_layer else None
        for pg, m, paint in iter_painted_placements(g):
            for f in pg.mesh.faces:
                own = layer_of(f)
                yield (f, m, top if by_layer else paint,
                       own if own != DEFAULT_LAYER else owner)


def _side_paint(eff, back: bool, default_front, back_color):
    """``(rgb or None, texture or None)`` a side of a face wears."""
    from core.materials import back_is_default
    if back:
        if back_is_default(eff):
            return back_color, None
        own = eff.get("back")
        if isinstance(own, dict):
            eff = own
    rgb = eff.get("color") if eff else None
    tex = eff.get("texture") if eff else None
    if rgb is None and tex is None:
        return default_front, None
    return (tuple(rgb[:3]) if rgb is not None else None), tex


def view_faces(scene, camera, as_view: bool = True,
               textures: bool = True, materials: bool = True,
               shadows: bool = False) -> list:
    """The visible faces of ``scene`` under ``camera`` as :class:`FaceFill`,
    in the plane of :func:`core.hlr.hlr_drawing` (parallel) or
    :func:`core.hlr.hlr_perspective` — see the module notes. ``as_view``:
    the viewport's light on every colour (off: the flat material colours).
    ``textures``: textured faces carry their image (off: its mean colour).
    ``materials`` off: every face as if it wore none — IngeTrazo's default
    colour in front, the back colour behind, opaque — a clean model to
    colour in the illustration program. The style's Hidden line and
    Monochrome modes paint every face in the Front colour, as the viewport
    does.

    ``shadows``: with the sun shadows on in the document, each face also
    gets the part of it the sun does not reach (``FaceFill.shadow``) and
    the shadows on the bare ground come first, as a face of their own on
    the ground layer (:data:`GROUND_LAYER`) — see :func:`_cast_shadows`."""
    from PySide6.QtGui import QVector3D
    from core.group import transformed_attrs
    from core.materials import effective_attrs
    from core.style import DEFAULT_FACE_COLOR, effective_back_color
    from core.texture import face_uv_axes

    style = getattr(scene, "display_style", None)
    mode = getattr(style, "face_mode", "textures")
    front = tuple(float(c) for c in
                  (getattr(style, "front_color", None) or (1, 1, 1))[:3])
    flat_front = mode in ("hidden_line", "monochrome")
    default_front = (front if flat_front else
                     tuple(d * c for d, c in zip(DEFAULT_FACE_COLOR, front)))
    back_color = tuple(effective_back_color(style, scene))
    light = as_view and mode != "hidden_line"
    use_tex = textures and mode == "textures"

    proj = (_Perspective(camera) if camera.perspective
            else _Parallel(camera))
    if camera.perspective and not proj.ok:
        return []
    sp = (scene.active_section()
          if getattr(scene, "show_section_cuts", True)
          and hasattr(scene, "active_section") else None)

    raw = []
    casters = []          # world rings of every face that blocks the sun
    for face, m, paint, layer in _faces_of(scene):
        loops = [face.vertices] + list(face.holes or [])
        if m is not None:
            loops = [[m.map(QVector3D(p)) for p in ring] for ring in loops]
        world = [np.array([(p.x(), p.y(), p.z()) for p in ring],
                          dtype=np.float64) for ring in loops]
        if len(world[0]) < 3:
            continue
        normal = _newell(world[0])
        if normal is None:
            continue
        if m is not None and _mirrors(m):
            # A mirrored placement turns the loop round; its front is
            # still the side the mesh's own normal points to.
            normal = -normal
        n_q = QVector3D(*map(float, normal))
        if sp is not None:
            world = [_clip_ring_to_section(r, sp) for r in world]
            world = [r for r in world if len(r) >= 3]
            if not world or len(world[0]) < 3:
                continue
        centre = world[0].mean(axis=0)
        back = proj.facing_back(normal, centre)
        attrs = face.attrs
        if m is not None and attrs and attrs.get("texture"):
            attrs = transformed_attrs(attrs, m)
        eff = (effective_attrs(attrs, paint) or {}) if materials else {}
        if flat_front or not materials:
            rgb, tex = (back_color if back else default_front), None
        else:
            rgb, tex = _side_paint(eff, back, default_front, back_color)
        if tex is not None and not tex.get("path"):
            tex = None
        if tex is not None and rgb is None:
            rgb = texture_average(tex["path"]) or default_front
        factor = shade_factor(normal) if light else 1.0
        opacity = float(eff.get("opacity", 1.0) or 1.0)
        if opacity >= SHADOW_OPACITY_MIN:
            casters.append(world)
        rings2, depths = [], []
        for r in world:
            xy, dz = proj.ring(r)
            if len(xy) >= 3:
                rings2.append(xy)
                depths.append(dz)
        if not rings2:
            continue
        near = _nearness_plane(rings2, depths, camera.perspective)
        if near is None:
            continue                            # edge-on: nothing to fill
        texture = None
        if tex is not None and use_tex:
            gu, cu, gv, cv = face_uv_axes(tex, n_q)
            pins = _uv_pins(world[0], normal, proj, gu, cu, gv, cv)
            if pins is not None:
                texture = {"path": tex["path"], "shade": factor, "uv": pins}
        raw.append(FaceFill(
            rings=rings2, rgb=shaded(rgb, factor) if light else tuple(rgb),
            layer=layer, opacity=opacity,
            texture=texture, back=back,
            depth=float(np.concatenate(depths).mean()),
            extra={"near": near, "world": world,
                   "seen_normal": -normal if back else normal}))
    out = _visible_parts(raw)
    sun = None
    if shadows:
        from core.sun import scene_sun_direction
        sun = scene_sun_direction(scene)
    if sun is not None:
        sh = getattr(scene, "shadows", None)
        alpha = 1.0 - float(getattr(sh, "darkness", 0.55))
        ground = _cast_shadows(out, casters, np.asarray(sun, float), proj,
                               alpha)
        if ground is not None:
            out.insert(0, ground)
    return out


def view_rect(camera) -> tuple:
    """What the window shows, as ``(x0, y0, x1, y1)`` in the plane of the
    line drawing (lower left, upper right) — where a picture of the view
    goes under the vector drawing. Perspective: the drawing's plane is the
    clip space scaled, so the window is its scale either way. Parallel:
    the window's corners taken back to the world and drawn."""
    if camera.perspective:
        p = _Perspective(camera)
        sx, sy = float(p.scale[0]), float(p.scale[1])
        return (-sx, -sy, sx, sy)
    m = camera.projection_matrix() * camera.view_matrix()
    M = np.array(m.data(), dtype=np.float64).reshape(4, 4, order="F")
    inv = np.linalg.inv(M)
    par = _Parallel(camera)
    pts = []
    for nx, ny in ((-1.0, -1.0), (1.0, 1.0)):
        w = inv @ np.array([nx, ny, 0.0, 1.0])
        pts.append(par.point(w[:3] / w[3]))
    (x0, y0), (x1, y1) = pts
    return (float(x0), float(y0), float(x1), float(y1))


def _nearness_plane(rings, depths, perspective: bool):
    """How near the face is at each point of the drawing, as an affine
    ``(a, b, c)``: ``a·x + b·y + c`` grows toward the eye. A plane's depth
    is affine in the drawing in parallel; in perspective its reciprocal is
    (what perspective-correct interpolation rests on). Fitted through the
    projected corners; ``None`` for a face seen edge-on."""
    xy = np.concatenate(rings)
    dz = np.concatenate(depths)
    q = 1.0 / dz if perspective else -dz
    if abs(sum(_area(r) for r in rings[:1])) < 1e-12:
        return None
    A = np.column_stack([xy, np.ones(len(xy))])
    sol, *_ = np.linalg.lstsq(A, q, rcond=None)
    return tuple(float(v) for v in sol)


def _newell(ring):
    """The unit normal of a world ring (its loop order), or ``None``."""
    nxt = np.roll(ring, -1, axis=0)
    n = np.array([
        ((ring[:, 1] - nxt[:, 1]) * (ring[:, 2] + nxt[:, 2])).sum(),
        ((ring[:, 2] - nxt[:, 2]) * (ring[:, 0] + nxt[:, 0])).sum(),
        ((ring[:, 0] - nxt[:, 0]) * (ring[:, 1] + nxt[:, 1])).sum()])
    ln = float(np.linalg.norm(n))
    return n / ln if ln > 1e-12 else None


def _mirrors(m) -> bool:
    a = np.array(m.data(), dtype=np.float64).reshape(4, 4, order="F")
    return float(np.linalg.det(a[:3, :3])) < 0.0


def _uv_pins(ring, normal, proj, gu, cu, gv, cv):
    """Four ``((x, y), (u, v))`` pairs — points of the face's plane in the
    drawing and their texture coordinates — that fix the map from the
    texture to the drawing. Four, not three: in perspective that map is a
    projective one (a plane seen in perspective), which three points pin
    only as an affine guess — each piece of a wall then guessed its own and
    the courses of brick broke at every seam. A diamond round the face's
    centre, as wide as the face, shrunk until all four lie before the eye.
    ``None`` if the face is edge-on or wholly behind it."""
    c = ring.mean(axis=0)
    a = ring[int(np.argmax(np.linalg.norm(ring - c, axis=1)))] - c
    r = float(np.linalg.norm(a))
    if r < 1e-12:
        return None
    a = a / r
    b = np.cross(np.asarray(normal, dtype=np.float64), a)
    b /= max(float(np.linalg.norm(b)), 1e-12)
    for _try in range(12):
        pins = []
        for d in (a, b, -a, -b):
            p = c + d * r
            xy = proj.point(p)
            if xy is None:
                break
            u = gu.x() * p[0] + gu.y() * p[1] + gu.z() * p[2] + cu
            v = gv.x() * p[0] + gv.y() * p[1] + gv.z() * p[2] + cv
            pins.append((tuple(map(float, xy)), (float(u), float(v))))
        if len(pins) == 4:
            xy = np.array([q[0] for q in pins])
            area = abs(_area(xy))
            return tuple(pins) if area > 1e-14 else None
        r *= 0.5
    return None


#: How many covers are joined at a time before they are taken away.
_COVER_BATCH = 128


def _take_away(visible, covers):
    """``visible`` less the union of ``covers``, taken away a batch of
    them at a time, and no further once nothing is left.

    The ground of a plaza seen whole has thousands of faces in front of
    it: one union of 5 000 regions was nearly half a second, and 190 such
    faces were 83 s of the SVG export; batch by batch, taken from what is
    left, 2.4 s. Up to one batch it is the single union as before."""
    if not covers:
        return visible
    from manifold3d import CrossSection, OpType
    for at in range(0, len(covers), _COVER_BATCH):
        visible = visible - CrossSection.batch_boolean(
            covers[at:at + _COVER_BATCH], OpType.Add)
        if visible.is_empty():
            break
    return visible


#: How many of the biggest faces in front of a face are tried first, on
#: their own, to find it hidden.
_HIDE_TRY = 6


def _hidden_by_the_biggest(visible, in_front, box_area, region) -> bool:
    """Whether the few biggest faces wholly in front of a face already
    hide all of it (``visible``) — then all of them hide it too, and
    neither the rest nor their union is needed.

    A plaza seen whole is 90 000 faces, 61 000 of them out of sight under
    a roof, a slab, a wall: the union of everything in front of each was
    two minutes of the SVG export. A roof alone hides what it covers."""
    if not len(in_front):
        return False
    if len(in_front) > _HIDE_TRY:
        order = np.argsort(-box_area[in_front], kind="stable")
        in_front = in_front[order[:_HIDE_TRY]]
    tried = [region(j) for j in in_front.tolist()]
    if len(tried) == 1:
        cover = tried[0]
    else:
        from manifold3d import CrossSection, OpType
        cover = CrossSection.batch_boolean(tried, OpType.Add)
    return (visible - cover).is_empty()


#: Who hears how far the visible faces have come (see :func:`reporting`).
_report = None

#: Seconds between two reports.
_REPORT_EVERY = 0.1


@contextmanager
def reporting(progress):
    """Within it, working out the visible faces tells ``progress(done)``
    how far it has come — ``done`` from 0 to 1 — every tenth of a second
    or so. ``progress`` may raise to stop the work there: the exception
    leaves :func:`view_faces` as it is.

    A big model's faces take minutes: the window that exports them can
    show a bar and keep painting, and let the person give up."""
    global _report
    was, _report = _report, progress
    try:
        yield
    finally:
        _report = was


class _OverlapGrid:
    """Which opaque faces' boxes overlap a face's box in the drawing —
    the same answer as testing it against every face, from a grid of
    cells instead.

    Testing every face against every other was 90 000 × 90 000 box tests
    for a plaza seen whole: five minutes of a frozen window exporting the
    view as SVG. A face is filed under each cell its box touches; one too
    big for the grid (the ground, a roof) is kept aside and tested against
    every face, as before. Two boxes that overlap share a point, so they
    share the cell of that point: no overlap is missed."""

    #: Cells a face may cover before it counts as big.
    BIG_CELLS = 64

    def __init__(self, lo, hi, opaque) -> None:
        self.lo, self.hi, self.opaque = lo, hi, opaque
        n = len(lo)
        ext = np.maximum(hi[:, :2] - lo[:, :2], 0.0)
        side = float(np.median(np.max(ext, axis=1))) if n else 0.0
        whole = float(max(np.max(hi[:, :2]) - np.min(lo[:, :2]), 1e-12))
        # About one face per cell: the median face's size, not finer than
        # a thousandth of the drawing.
        self.cell = max(side, whole * 1e-3, 1e-12)
        self.origin = np.min(lo[:, :2], axis=0)
        self.c_lo = np.floor((lo[:, :2] - self.origin) / self.cell).astype(
            np.int64)
        self.c_hi = np.floor((hi[:, :2] - self.origin) / self.cell).astype(
            np.int64)
        count = (self.c_hi - self.c_lo + 1).prod(axis=1)
        self.is_big = count > self.BIG_CELLS
        self.big = np.flatnonzero(opaque & self.is_big)
        cells: dict = {}
        for j in np.flatnonzero(opaque & ~self.is_big):
            x0, y0 = self.c_lo[j]
            x1, y1 = self.c_hi[j]
            for cx in range(x0, x1 + 1):
                for cy in range(y0, y1 + 1):
                    cells.setdefault((cx, cy), []).append(j)
        self.cells = {k: np.array(v, dtype=np.int64)
                      for k, v in cells.items()}
        self.every = np.flatnonzero(opaque)

    def _test(self, i, cand):
        lo, hi = self.lo, self.hi
        a_lo, a_hi = lo[i], hi[i]
        keep = ((lo[cand, 0] < a_hi[0]) & (hi[cand, 0] > a_lo[0])
                & (lo[cand, 1] < a_hi[1]) & (hi[cand, 1] > a_lo[1])
                & (cand != i))
        return cand[keep]

    def overlapping(self, i):
        """The opaque faces, other than ``i``, whose boxes overlap face
        ``i``'s, in increasing order."""
        if self.is_big[i]:
            return self._test(i, self.every)
        x0, y0 = self.c_lo[i]
        x1, y1 = self.c_hi[i]
        cells = self.cells
        found = [self._test(i, self.big)]
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                there = cells.get((cx, cy))
                if there is not None:
                    found.append(self._test(i, there))
        if len(found) == 2:
            return np.sort(np.concatenate(found))
        return np.unique(np.concatenate(found))


def _visible_parts(faces):
    """Each face cut down to what nothing in front of it covers.

    Exact for flat faces, in no particular order: where another opaque
    face B overlaps A in the drawing, the line along which B passes in
    front of A is where their nearness planes (:func:`_nearness_plane`)
    cross, so the part of B that hides A is B clipped to one side of that
    line. A sorting by depth gets thin slabs, a floor under what stands on
    it and faces that cross each other wrong; this does not. Coplanar faces
    that overlap: the earlier one wins. A see-through face hides nothing.

    Faces with nothing left are dropped. The opaque ones never overlap
    after this; the see-through ones come last, far to near, so drawn in
    order they land over what they let through."""
    items = []
    for f in faces:
        mins = np.min([r.min(axis=0) for r in f.rings], axis=0)
        maxs = np.max([r.max(axis=0) for r in f.rings], axis=0)
        items.append((f, mins, maxs))
    if not items:
        return []
    lo = np.array([it[1] for it in items])
    hi = np.array([it[2] for it in items])
    opaque = np.array([it[0].opacity >= 0.999 for it in items])
    whole = [it[0].rings for it in items]     # before any is cut down
    span = float(max(np.max(hi - lo), 1e-9))
    min_area = _MIN_AREA_MM2 * 1e-6           # mm² → m²
    near_by = _OverlapGrid(lo, hi, opaque)
    nearness = np.array([it[0].extra["near"] for it in items],
                        dtype=np.float64)
    box_area = (hi[:, 0] - lo[:, 0]) * (hi[:, 1] - lo[:, 1])
    # A face whole, as a region: made once, not once per face it covers
    # (a plaza seen whole is millions of such pairs).
    regions: dict = {}

    def region(j):
        r = regions.get(j)
        if r is None:
            r = regions[j] = _section(whole[j])
        return r

    out = []
    report, n = _report, len(items)
    told = time.monotonic()
    for i, (fa, a_lo, a_hi) in enumerate(items):
        if report is not None and time.monotonic() - told >= _REPORT_EVERY:
            report(i / n)
            told = time.monotonic()
        overlap = near_by.overlapping(i)
        visible = region(i)
        qa = nearness[i]
        # Nearness differences below this are "the same plane": a
        # millionth of the drawing's size (metres in parallel, the
        # reciprocal of the distance in perspective).
        tol = 1e-6 * max(1.0, abs(qa[2]), abs(qa[0]) * span,
                         abs(qa[1]) * span)
        cx = np.array([a_lo[0], a_hi[0], a_hi[0], a_lo[0]])
        cy = np.array([a_lo[1], a_lo[1], a_hi[1], a_hi[1]])
        # Where each overlapping B stands against A at the four corners
        # of A's box, all of them at once (> 0: B nearer).
        dq = nearness[overlap] - qa
        at = (cx[None, :] * dq[:, 0:1] + cy[None, :] * dq[:, 1:2]
              + dq[:, 2:3])
        same = (np.abs(at) <= tol).all(axis=1)          # the same plane
        behind = ~same & (at <= tol).all(axis=1)        # B behind A here
        front = ~same & ~behind & (at > tol).all(axis=1)  # B in front
        kind = np.where(same, np.where(overlap > i, 0, 1),
                        np.where(behind, 0, np.where(front, 1, 2)))
        if _hidden_by_the_biggest(visible, overlap[kind == 1], box_area,
                                  region):
            continue
        covers = []
        for j, k, d in zip(overlap[kind > 0].tolist(), kind[kind > 0],
                           dq[kind > 0]):
            if k == 1:                       # B covers A whole here
                covers.append(region(j))
                continue
            # A neighbour sharing an edge clips to a sliver of no area
            # along it: nothing to take away.
            rings_b = whole[j]
            part = [c for c in (_clip_half(r, d) for r in rings_b)
                    if len(c) >= 3 and abs(_area(c)) >= min_area]
            if len(part) == len(rings_b) and all(
                    c is r for c, r in zip(part, rings_b)):
                covers.append(region(j))     # all of B: the region made
            elif part:
                covers.append(_section(part))
        visible = _take_away(visible, covers)
        rings = [np.asarray(p, dtype=np.float64) / _K
                 for p in visible.to_polygons()]
        rings = [r for r in rings if len(r) >= 3
                 and abs(_area(r)) >= min_area]
        if rings:
            fa.rings = rings
            out.append(fa)
    # Opaque first (they do not overlap: any order), then the see-through
    # ones far to near.
    out.sort(key=lambda f: (f.opacity < 0.999, -f.depth))
    return out


def _cast_shadows(faces, casters, sun, proj, alpha):
    """Cut the sun's shadows into the visible ``faces`` (sets each one's
    ``shadow``) and return the shadow on the bare ground as a face of its
    own, or ``None``.

    Exact for flat faces: a caster B darkens a receiver A where the line
    from A toward the sun meets B, so B's shadow on A is B — the part of it
    on the sun's side of A's plane — slid along the sunbeams onto that
    plane. That polygon, drawn with the view's camera, cut to A's visible
    part, is the shadow. A face turned away from the sun is in its own
    shadow whole. The ground (z = 0) takes the same with a level plane,
    less whatever face covers it in the drawing."""
    d = sun / max(float(np.linalg.norm(sun)), 1e-12)
    # Sunbeams keep the coordinates across the sun's view: a shadow lies
    # within its caster's box there — the cheap test before the exact one.
    e1 = np.cross(d, [0.0, 0.0, 1.0])
    if np.linalg.norm(e1) < 1e-9:
        e1 = np.array([1.0, 0.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(d, e1)
    E = np.stack([e1, e2], axis=1)
    c_lo = np.array([(r[0] @ E).min(axis=0) for r in casters]).reshape(-1, 2)
    c_hi = np.array([(r[0] @ E).max(axis=0) for r in casters]).reshape(-1, 2)
    min_area = _MIN_AREA_MM2 * 1e-6
    eps = 1e-6

    def slid(rings, n, p0):
        """``rings`` (world) cut to the sun's side of the plane (n, p0) and
        slid along the sunbeams onto it, drawn: plane rings, maybe none."""
        dn = float(d @ n)
        out = []
        for r in rings:
            r = _clip_ring_above(r, n, p0, eps)
            if len(r) < 3:
                continue
            t = ((r - p0) @ n) / dn
            xy, _ = proj.ring(r - np.outer(t, d))
            if len(xy) >= 3:
                out.append(xy)
        return out

    for f in faces:
        world = f.extra.get("world")
        if world is None or f.opacity < 0.999:
            continue
        n = np.asarray(f.extra["seen_normal"], dtype=np.float64)
        visible = _section(f.rings)
        if float(n @ d) <= 1e-6:
            dark = visible                          # turned from the sun
        else:
            p0 = world[0][0]
            r_lo = (world[0] @ E).min(axis=0)
            r_hi = (world[0] @ E).max(axis=0)
            near = ((c_lo[:, 0] < r_hi[0]) & (c_hi[:, 0] > r_lo[0])
                    & (c_lo[:, 1] < r_hi[1]) & (c_hi[:, 1] > r_lo[1]))
            pieces = []
            for k in np.flatnonzero(near):
                cast = casters[k]
                if cast is world:
                    continue
                rings = slid(cast, n, p0)
                if rings:
                    pieces.append(_section(rings))
            if not pieces:
                continue
            from manifold3d import CrossSection, OpType
            dark = visible ^ CrossSection.batch_boolean(pieces, OpType.Add)
        rings = [np.asarray(p, dtype=np.float64) / _K
                 for p in dark.to_polygons()]
        rings = [r for r in rings if len(r) >= 3
                 and abs(_area(r)) >= min_area]
        if rings:
            f.shadow = rings
            f.shadow_alpha = alpha

    if d[2] <= 1e-6:
        return None
    up, origin = np.array([0.0, 0.0, 1.0]), np.zeros(3)
    pieces = []
    for cast in casters:
        rings = slid(cast, up, origin)
        if rings:
            pieces.append(_section(rings))
    if not pieces:
        return None
    from manifold3d import CrossSection, OpType
    ground = CrossSection.batch_boolean(pieces, OpType.Add)
    over = [_section(f.rings) for f in faces if f.opacity >= 0.999]
    if over:
        ground = ground - CrossSection.batch_boolean(over, OpType.Add)
    rings = [np.asarray(p, dtype=np.float64) / _K
             for p in ground.to_polygons()]
    rings = [r for r in rings if len(r) >= 3 and abs(_area(r)) >= min_area]
    if not rings:
        return None
    return FaceFill(rings=rings, rgb=(0.0, 0.0, 0.0), layer=GROUND_LAYER,
                    opacity=alpha, extra={"ground_shadow": True})


def _clip_ring_above(ring, n, p0, eps):
    """The part of a world ring on the positive side of the plane through
    ``p0`` with normal ``n`` (farther than ``eps``)."""
    v = (ring - p0) @ n - eps
    keep = v > 0.0
    if keep.all():
        return ring
    if not keep.any():
        return ring[:0]
    out = []
    m = len(ring)
    for k in range(m):
        j = (k + 1) % m
        if keep[k]:
            out.append(ring[k])
        if keep[k] != keep[j]:
            t = v[k] / (v[k] - v[j])
            out.append(ring[k] + (ring[j] - ring[k]) * t)
    return np.asarray(out).reshape(-1, 3)


def _section(rings):
    """Plane rings as an even-odd 2D region, at the working scale — the
    area booleans of manifold3d (Clipper2), which keep their footing on
    the coincident edges a model is full of where Qt's path booleans
    did not (a face equal to its cover came back WHOLE)."""
    from manifold3d import CrossSection, FillRule
    return CrossSection([np.asarray(r, dtype=np.float64) * _K
                         for r in rings], FillRule.EvenOdd)


def _clip_half(ring, dq):
    """The part of the plane ring where ``dq[0]·x + dq[1]·y + dq[2] > 0``
    (Sutherland–Hodgman against one line)."""
    v = ring @ dq[:2] + dq[2]
    keep = v > 0.0
    if keep.all():
        return ring
    if not keep.any():
        return ring[:0]
    # Corner k, if kept, then where edge k → k+1 crosses the line, if it
    # does: all corners at once (millions of rings in a big model's SVG).
    nxt = np.concatenate((ring[1:], ring[:1]))
    v_n = np.concatenate((v[1:], v[:1]))
    cross = keep != np.concatenate((keep[1:], keep[:1]))
    t = v[cross] / (v[cross] - v_n[cross])
    here = ring[cross]
    cut = here + (nxt[cross] - here) * t[:, None]
    count = keep.astype(np.intp) + cross
    start = np.cumsum(count) - count
    out = np.empty((int(count.sum()), ring.shape[1]), dtype=np.float64)
    out[start[keep]] = ring[keep]
    out[start[cross] + keep[cross]] = cut
    return out


def _area(r) -> float:
    x, y = r[:, 0], r[:, 1]
    # The arrays np.roll would give, without its Python-level checks: it
    # was a fifth of the SVG export of a big model, called millions of
    # times on rings of four corners.
    return 0.5 * float(x @ np.concatenate((y[1:], y[:1]))
                       - y @ np.concatenate((x[1:], x[:1])))
