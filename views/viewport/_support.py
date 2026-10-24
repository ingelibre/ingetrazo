# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Module-level helpers, constants and flags shared by the viewport mixins."""
from __future__ import annotations

import itertools
import math
import os
import re
import time as _time_mod
from array import array
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.paths import app_root

# Perf telemetry (INGETRAZO_PERF=1): every operation slower than 50 ms and a
# once-per-second frame summary land in ~/ingetrazo-perf.log — the tool for
# "it feels slow" reports from real sessions, where synthetic benchmarks lie.
_PERF = bool(os.environ.get("INGETRAZO_PERF"))
# Kill-switch for the instanced component pass (P2): set to 1 to draw
# every instance through the consolidated VBOs like before.
_NO_INSTANCING = os.environ.get("INGETRAZO_NO_INSTANCING", "") == "1"
# Kill-switch for the default-back tint pass (faces have sides, 2026-09-11):
# set to 1 to draw every paint on both sides like before — a diagnostic,
# and the escape hatch should a driver misbehave with front culling.
_NO_BACK_TINT = os.environ.get("INGETRAZO_NO_BACK_TINT", "") == "1"
# Kill-switch for the snap engine's shortcuts (edge grid, occlusion in
# batches, centre lookup through the registry): set to 1 to run every hover
# the way it ran before — one pass over all group edges, one ray per
# candidate, the rounded-position table. A diagnostic, and the escape hatch
# should a snap ever land somewhere it did not before.
_NO_SNAP_FAST = os.environ.get("INGETRAZO_NO_SNAP_FAST", "") == "1"
# Kill-switch for the pick index's span grid: set to 1 to keep one span per
# chunk however big, as before (a ray that meets the box of a 107 k-triangle
# group then tests all of its triangles).
_NO_SPAN_GRID = os.environ.get("INGETRAZO_NO_SPAN_GRID", "") == "1"
#: A chunk with more triangles than this is split into grid cells for the
#: ray prefilter (_split_chunk_spans); ~4 096 triangles a cell.
_SPAN_GRID_MIN = 8192
_SPAN_CELL_TRIS = 4096
_perf_file = None


def _plog(tag: str, ms: float, extra: str = "", floor: float = 50.0) -> None:
    """Frame telemetry (P0). Lines carry the writer's pid and honour
    ``$INGETRAZO_PERF_LOG`` — see ``core.history._plog`` for why."""
    global _perf_file
    if not _PERF or ms < floor:
        return
    if _perf_file is None:
        path = os.environ.get("INGETRAZO_PERF_LOG")
        _perf_file = open(Path(path) if path
                          else Path.home() / "ingetrazo-perf.log",
                          "a", buffering=1)
    _perf_file.write(f"{_time_mod.strftime('%H:%M:%S')} [{os.getpid()}] "
                     f"{tag} {ms:.0f}ms"
                     f"{' ' + extra if extra else ''}\n")


class _HoverEvent:
    """Minimal stand-in for a QMouseEvent inside the coalesced hover path —
    just what ``_build_ctx`` and the hover handlers read."""

    __slots__ = ("_pos", "_mods")

    def __init__(self, pos, mods) -> None:
        self._pos = pos
        self._mods = mods

    def position(self):
        return self._pos

    def modifiers(self):
        return self._mods


def _active_cut(scene):
    """The section plane actually CUTTING (cuts shown + one active), or
    None. A module function so stub viewports in tests degrade gracefully;
    picks and snaps filter by it — what the cut hides is not clickable nor
    snappable."""
    if not getattr(scene, "show_section_cuts", True):
        return None
    active = getattr(scene, "active_section", None)
    return active() if callable(active) else None


class _SnapEdge:
    """Lightweight edge stand-in fed to the snap engine for group geometry —
    ``compute_snap`` only reads ``.a``/``.b`` (world endpoints). ``center``
    marks the degenerate one that carries a circle's centre."""

    __slots__ = ("a", "b", "center", "component_origin", "arc_midpoint",
                 "guide", "in_group", "context", "group", "figure")

    def __init__(self, a, b, center: bool = False, component_origin: bool = False,
                 arc_midpoint: bool = False, guide: bool = False,
                 in_group: bool = False, context=None, group=None,
                 figure: bool = False) -> None:
        self.a = a
        self.b = b
        self.figure = figure                       # a face-me figure's feet
        self.center = center
        self.component_origin = component_origin   # a group's insertion point
        self.arc_midpoint = arc_midpoint           # the middle of an arc's sweep
        self.guide = guide                         # a construction guide: 'on line'
        self.in_group = in_group                   # magenta point inferences
        self.context = context                     # "group" / "component" for the tip
        self.group = group                         # the top-level owner, when known


def _group_pseudo_edge(idx, i: int) -> _SnapEdge:
    """The i-th group hard edge of the pick index as a world pseudo-edge
    that knows its owner and whether that is a group or a component."""
    gi = getattr(idx, "gedge_gi", None)
    groups = getattr(idx, "gedge_groups", None)
    owner = groups[int(gi[i])] if gi is not None and groups else None
    is_comp = getattr(owner, "is_instance", None)
    context = "component" if (is_comp is not None and is_comp()) else "group"
    return _SnapEdge(QVector3D(*idx.gedge_a[i]), QVector3D(*idx.gedge_b[i]),
                     in_group=True, context=context, group=owner)


# OpenGL constants — kept as literals so we don't depend on PyOpenGL.
GL_FLOAT = 0x1406
GL_LINES = 0x0001


def _shifted_mvp(mvp, dx_ndc: float, dy_ndc: float):
    """``mvp`` nudged by a clip-space offset (sub-pixel line thickening)."""
    from PySide6.QtGui import QMatrix4x4
    m = QMatrix4x4()
    m.translate(dx_ndc, dy_ndc, 0.0)
    return m * mvp
GL_TRIANGLES = 0x0004
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_DEPTH_TEST = 0x0B71
GL_CLIP_DISTANCE0 = 0x3000
GL_STENCIL_TEST = 0x0B90
GL_STENCIL_BUFFER_BIT = 0x00000400
GL_ALWAYS = 0x0207
GL_EQUAL = 0x0202
GL_KEEP = 0x1E00
GL_REPLACE = 0x1E01
GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_POLYGON_OFFSET_FILL = 0x8037
GL_CULL_FACE = 0x0B44
GL_CW = 0x0900
GL_CCW = 0x0901
GL_FRONT = 0x0404
GL_BACK = 0x0405
GL_LEQUAL = 0x0203
GL_GREATER = 0x0204
GL_FALSE = 0
GL_TRUE = 1
GL_FRAMEBUFFER = 0x8D40
GL_READ_FRAMEBUFFER = 0x8CA8
GL_DRAW_FRAMEBUFFER = 0x8CA9
GL_NEAREST = 0x2600
GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0
GL_TEXTURE1 = 0x84C1
GL_MAX_TEXTURE_SIZE = 0x0D33


SHADER_DIR = app_root() / "resources" / "shaders"


# ---- Geometry helpers ------------------------------------------------------

#: Beyond this many loose edges the snap engine gets a near-cursor subset
#: instead of the whole mesh: compute_snap walks its edge list in Python
#: ~a dozen times per hover, and an exploded medium import (9k faces =
#: ~20k edges) froze every mouse move (user report, piscina.igz).
_LOOSE_SNAP_CAP = 3000


def _split_chunk_spans(chunk, depth=0, force=False):
    """``(v0, e1, e2, tri_ent, cells)`` of a chunk for the pick index. For a
    chunk of more than ``_SPAN_GRID_MIN`` triangles: the triangles reordered
    by the cell of their centroid in a grid over the chunk (cells per axis
    in proportion to its extent there, ~``_SPAN_CELL_TRIS`` a cell), and
    ``cells = [(bbox, start, count)]``, one per non-empty cell, each box
    tight around its triangles; a cell that still holds over twice the
    target (triangles cluster) is binned again on its own, up to three
    levels. Otherwise ``cells = None`` and the arrays as they are. Cached on
    the chunk by its revision.

    One span per chunk made every ray that met the box of a big group run
    Möller–Trumbore over all of it: a 107 k-triangle sofa, 2.6 ms a ray,
    ~100 rays a hover with Line (snap occlusion), 300 ms a Move step on a
    306 k-face room. The order of the triangles inside the index is free
    (each carries its entity), so the answer does not change."""
    v0, e1, e2, te = chunk["v0"], chunk["e1"], chunk["e2"], chunk["tri_ent"]
    n = len(v0)
    if _NO_SPAN_GRID or (n <= _SPAN_GRID_MIN and not force):
        return v0, e1, e2, te, None
    memo = chunk.get("_span_grid") if not force else None
    if memo is not None and memo[0] == (chunk.get("rev"), n):
        return memo[1]
    import numpy as np
    cen = v0 + (e1 + e2) / 3.0                                  # centroids
    lo = cen.min(axis=0)
    span = np.maximum(cen.max(axis=0) - lo, 1e-9)
    # Cells per axis in proportion to the extent on it; the weights multiply
    # to 1, so their product stays near the target count.
    w = span / np.exp(np.log(span).mean())
    per_axis = np.maximum(
        1, np.round((n / _SPAN_CELL_TRIS) ** (1.0 / 3.0) * w)).astype(np.int64)
    cell = np.minimum(((cen - lo) * (per_axis / span)).astype(np.int64),
                      per_axis - 1)
    key = (cell[:, 0] * per_axis[1] + cell[:, 1]) * per_axis[2] + cell[:, 2]
    order = np.argsort(key, kind="stable")
    key = key[order]
    v0p = np.ascontiguousarray(v0[order])
    e1p = np.ascontiguousarray(e1[order])
    e2p = np.ascontiguousarray(e2[order])
    tep = np.ascontiguousarray(te[order])
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(key)]
    cells = []
    for s0, s1 in zip(starts.tolist(), ends.tolist()):
        if s1 - s0 > 2 * _SPAN_CELL_TRIS and depth < 3:
            sv0, se1, se2, ste, sub = _split_chunk_spans(
                {"v0": v0p[s0:s1], "e1": e1p[s0:s1], "e2": e2p[s0:s1],
                 "tri_ent": tep[s0:s1]}, depth + 1, force=True)
            # The sub-grid is a permutation of this range: write it back.
            v0p[s0:s1], e1p[s0:s1], e2p[s0:s1], tep[s0:s1] = sv0, se1, se2, ste
            cells += [(bb, s0 + a, c) for bb, a, c in sub]
            continue
        pts = np.concatenate([v0p[s0:s1], v0p[s0:s1] + e1p[s0:s1],
                              v0p[s0:s1] + e2p[s0:s1]])
        cells.append(((tuple(pts.min(axis=0).tolist()),
                       tuple(pts.max(axis=0).tolist())), s0, s1 - s0))
    out = (v0p, e1p, e2p, tep, cells)
    if not force:
        chunk["_span_grid"] = ((chunk.get("rev"), n), out)
    return out


def _ray_aabb_span(o, d, lo, hi):
    """``(t_in, t_out)`` of the forward ray (t >= 0) through the AABB, or
    ``None`` if it misses. Plain floats."""
    tmin, tmax = 0.0, float("inf")
    for i in range(3):
        di = d[i]
        if -1e-12 < di < 1e-12:
            if o[i] < lo[i] - 1e-9 or o[i] > hi[i] + 1e-9:
                return None
            continue
        t1 = (lo[i] - o[i]) / di
        t2 = (hi[i] - o[i]) / di
        if t1 > t2:
            t1, t2 = t2, t1
        tmin, tmax = max(tmin, t1), min(tmax, t2)
        if tmin > tmax:
            return None
    return tmin, tmax


def _ray_aabb(o, d, lo, hi, reach=float("inf")) -> bool:
    """Slab test: does the forward ray (``0 <= t <= reach``) touch the AABB?
    Plain floats — the pick prefilter tests ~tens of chunk boxes per ray."""
    tmin = 0.0
    tmax = reach
    for i in range(3):
        di = d[i]
        if -1e-12 < di < 1e-12:
            if o[i] < lo[i] - 1e-9 or o[i] > hi[i] + 1e-9:
                return False
            continue
        inv = 1.0 / di
        t1 = (lo[i] - o[i]) * inv
        t2 = (hi[i] - o[i]) * inv
        if t1 > t2:
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin = t1
        if t2 < tmax:
            tmax = t2
        if tmin > tmax:
            return False
    return True


#: Every chunk entry built (or loaded from disk) takes the next number.
#: Keys that told entries apart by ``id(entry)`` could not: the dict a
#: rebuild replaces is freed at once, and the new one may land at the same
#: address — same id, same rev 0 — so the instance arrays and the GL draw
#: entry derived from the OLD chunk were served as if nothing had changed
#: (a face painted inside a component came back unpainted one level up,
#: Marco, 2026-09-11).
_chunk_uid = itertools.count(1)


#: The recorded, state-tracking instanced passes: ``None`` follows the
#: experimental engine (on with it, off without — they change how the GPU
#: is fed, and drivers differ); True/False force them (tests draw both).
_LEAN_INSTANCED = None


def _lean_instanced() -> bool:
    if _LEAN_INSTANCED is not None:
        return _LEAN_INSTANCED
    from core import _native
    return _native.native is not None
#: The snap engine's occlusion rays go through core._native's kernel when
#: the experimental engine is on (tests compare both).
_OCCL_NATIVE = True


def _occlusion_native():
    """core._native when it can take ``_occluded_many``'s rays, else None."""
    if not _OCCL_NATIVE:
        return None
    from core import _native
    mod = _native.native
    return mod if mod is not None and hasattr(mod, "occlusion_span") else None


#: Lazy placements are filtered by core._native's spatial index before
#: being baked for a pick (the experimental engine; tests compare both).
_INSTANCE_FILTER = True
#: Span lists this long are culled with NumPy (_visible_spans_np).
_SPAN_VECTOR_MIN = 64
#: Recorded instanced passes replayed by the native engine when it is on.
_LEAN_NATIVE_REPLAY = True


class _GlTape:
    """A recorded run of GL calls: each one is made at once (through the
    PySide wrapper, as ever) and kept twice — as the wrapper call, and as
    the raw GL call that wrapper makes, for core._native's GlReplay. A
    replay runs the raw list natively when the engine is there, else the
    wrapper calls."""

    DRAW, VAO, U1I, U1F, U4F, ENABLE, DISABLE, CULL, FRONT, ACTIVE, TEX = \
        range(11)

    def __init__(self):
        self.calls: list = []
        self.ops: list = []
        self.vals: list = []
        self.arrays = None

    def _op(self, code, ints=(), floats=()):
        self.ops.append((code, *ints, *(0,) * (4 - len(ints))))
        self.vals.append((*floats, *(0.0,) * (4 - len(floats))))

    def call(self, fn, *args):
        self.calls.append((fn, args))
        fn(*args)

    def draw(self, fn, mode, first, count, n):
        self.call(fn, mode, first, count, n)
        self._op(self.DRAW, (mode, first, count, n))

    def bind_vao(self, vao):
        self.call(vao.bind)
        self._op(self.VAO, (vao.objectId(),))

    def release_vao(self, vao):
        self.call(vao.release)
        self._op(self.VAO, (0,))

    def uniform_i(self, prog, loc, v):
        self.call(prog.setUniformValue, loc, v)
        self._op(self.U1I, (loc, int(v)))

    def uniform_f(self, prog, loc, v):
        self.call(prog.setUniformValue1f, loc, v)
        self._op(self.U1F, (loc,), (float(v),))

    def uniform_4f(self, prog, loc, vec):
        self.call(prog.setUniformValue, loc, vec)
        self._op(self.U4F, (loc,), (vec.x(), vec.y(), vec.z(), vec.w()))

    def gl(self, fn, code, value):
        self.call(fn, value)
        self._op(code, (value,))

    def tex_bind(self, tex, unit):
        # QOpenGLTexture::bind(unit): active unit, then bind (not reset).
        self.call(tex.bind, unit)
        self._op(self.ACTIVE, (GL_TEXTURE0 + unit,))
        self._op(self.TEX, (tex.target().value, tex.textureId()))

    def tex_release(self, tex, unit):
        self.call(tex.release, unit)
        self._op(self.ACTIVE, (GL_TEXTURE0 + unit,))
        self._op(self.TEX, (tex.target().value, 0))

    def replay(self, native) -> None:
        if native is not None:
            if self.arrays is None:
                import numpy as np
                self.arrays = (np.asarray(self.ops, dtype=np.int64)
                               .reshape(-1, 5),
                               np.asarray(self.vals, dtype=np.float32)
                               .reshape(-1, 4))
            native.run(*self.arrays)
            return
        for fn, args in self.calls:
            fn(*args)


#: The GL entry points GlReplay calls, in _GlTape's opcode order.
_TAPE_FUNCS = (b"glDrawArraysInstanced", b"glBindVertexArray",
               b"glUniform1i", b"glUniform1f", b"glUniform4f", b"glEnable",
               b"glDisable", b"glCullFace", b"glFrontFace",
               b"glActiveTexture", b"glBindTexture")


class _InstanceBatch(list):
    """One frame's placements of an instanced pool (a plain list of them)
    with their indices in the pool and the pool's matrix rows, so the
    matrix buffer is filled by one NumPy take instead of sixteen floats
    read per placement."""

    __slots__ = ("idx", "mats")


def _proto_wrapper(vp, mesh, paint=None):
    """The stable stand-in a prototype mesh is baked through, one per
    (mesh, container paint): ``_group_chunk`` caches by the wrapper's id,
    so the same object must come back for the same mesh — and a painted
    instance (issue #47) gets a wrapper of its own. Module-level so the
    stub viewports in tests reach it too."""
    from types import SimpleNamespace
    from core.materials import material_sig
    wrappers = getattr(vp, "_proto_wrappers", None)
    if wrappers is None:
        wrappers = vp._proto_wrappers = {}
    wkey = (id(mesh), material_sig(paint))
    w = wrappers.get(wkey)
    if w is None:
        w = wrappers[wkey] = SimpleNamespace(mesh=mesh, xform=None,
                                             material=paint)
    else:
        w.material = paint
    return w


def _cache_ver(vp):
    """The scene version the per-version caches key on — frozen during a
    groups-only transform preview (see Viewport.begin_groups_preview).
    Module-level so the stub viewports in tests hit it too."""
    frozen = getattr(vp, "_frozen_cache_version", None)
    return frozen if frozen is not None else vp.scene.version


#: How the rest of the model reads while a group is open for editing.
#: ``normal`` draws it as always, ``fade`` washes it out behind the group
#: being edited (the default), ``hide`` leaves it out of the frame.
EDIT_REST_MODES = ("normal", "fade", "hide")
#: How far the context is mixed TOWARD the background (0 = untouched, 1 =
#: gone). It is a wash, not an opacity: the context keeps writing depth, so it
#: still occludes itself and never turns the model into glass. Enough to place
#: the group in its surroundings, faint enough that what you are editing reads
#: as the subject.
EDIT_REST_FADE = 0.75


def edit_fade_color(background) -> tuple:
    """What the rest of the model fades TOWARDS while a group is edited: a
    grey half way between the background and a neutral mid grey. Fading
    to the background itself left white faces on a light background
    looking the same as before — nothing said you were inside a group
    («quiero que lo demás quede gris», 14-10). Towards this grey the rest
    reads grey on a light background and dim on a dark one, and what is
    being edited keeps its colours."""
    return tuple(0.5 * float(c) + 0.5 * 0.55 for c in list(background)[:3])

#: X-ray: how opaque each translucent face layer is. Layers stack, so a face
#: seen through another reads darker and an opening (no face) stays clear.
XRAY_FACE_OPACITY = 0.6
#: X-ray: edges hidden behind a face are washed this far toward the
#: background (0 = like a visible edge, 1 = gone), so the form still reads
#: and you can tell which edges have a face in front of them.
XRAY_HIDDEN_EDGE_FADE = 0.6

#: Dot colour of a SELECTED face (the usual selection orange) and the one it
#: switches to on a surface that is itself orange/red, where orange dots
#: would vanish into the paint.
SELECTION_DOT_COLOR = (0.95, 0.45, 0.16)
SELECTION_DOT_ALT_COLOR = (0.10, 0.25, 0.85)


def selection_dot_color(surface) -> tuple:
    """The dot colour that reads on a face side painted ``surface`` (an RGB
    triple, or ``None`` when unknown, e.g. a texture): the selection orange,
    unless the surface is orange-ish or red-ish itself (hue within ~50° of
    red, with enough saturation and value to look coloured), where the dots
    turn blue so a selected face still tells itself apart."""
    if surface is None:
        return SELECTION_DOT_COLOR
    import colorsys
    h, s, v = colorsys.rgb_to_hsv(*(float(c) for c in surface[:3]))
    if s >= 0.35 and v >= 0.35 and (h <= 0.14 or h >= 0.96):
        return SELECTION_DOT_ALT_COLOR
    return SELECTION_DOT_COLOR


def _box_edges(frame, lo, hi) -> bytes:
    """The twelve segments of a box given in ``frame``'s axes, as an
    interleaved float32 line buffer — the selection cue for a whole group."""
    from core.group import oriented_box_corners
    corners = oriented_box_corners(frame, lo, hi)
    buf = array("f")
    for i in range(8):
        for bit in (1, 2, 4):      # neighbours differ in exactly one axis
            j = i | bit
            if j != i:
                for p in (corners[i], corners[j]):
                    buf.extend((p.x(), p.y(), p.z()))
    return buf.tobytes()


def _load_edit_rest_mode() -> str:
    from PySide6.QtCore import QSettings
    mode = str(QSettings().value("display/edit_rest_mode", "fade"))
    return mode if mode in EDIT_REST_MODES else "fade"


def _load_hide_similar() -> bool:
    from PySide6.QtCore import QSettings
    return str(QSettings().value("display/hide_similar_components",
                                 "0")) == "1"


def _load_invert_wheel() -> bool:
    from PySide6.QtCore import QSettings
    return str(QSettings().value("nav/invert_wheel", "0")) != "0"


def _load_invert_orbit_y() -> bool:
    """Preferences ▸ orbit with the vertical axis reversed.

    Off by default: `OrbitCamera.orbit` grabs the model in both axes, the
    classic way. This is for the hands that learned the other feel —
    including the ones that learned it from IngeTrazo before 0.3.16, when
    the vertical axis was inverted by mistake.
    """
    from PySide6.QtCore import QSettings
    return str(QSettings().value("nav/invert_orbit_y", "0")) != "0"


def _load_msaa() -> int:
    """Scene-FBO multisample count (Preferences ▸ General). 4 is the
    historical hardcoded value; the FBO still falls back to 0 on drivers
    that refuse multisampling."""
    from PySide6.QtCore import QSettings
    try:
        n = int(QSettings().value("display/msaa", 4))
    except (TypeError, ValueError):
        n = 4
    return n if n in (0, 2, 4, 8) else 4

_AXIS_DIRS = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}


def _axes_vertices(spacing: float, pos_len: float = 1.0e5):
    """Drawing axes: a long solid line in the positive direction and an
    **evenly-spaced** dashed line in the negative (constant world ``spacing``, so
    the dashes converge toward the horizon by perspective — the classic look, not
    spreading apart). ``spacing`` scales with the camera distance so the on-screen
    density stays stable across zoom. Returns ``(coords, spans)`` where ``spans``
    maps ``'x'|'y'|'z'`` → ``(first_vertex, vertex_count)`` for a per-axis draw."""
    coords = array("f")
    spans: dict[str, tuple[int, int]] = {}
    spacing = max(spacing, 1e-4)
    # Short dots, not half-duty dashes: GL lines are stuck at 1px (Mesa
    # clamps glLineWidth), so the dash LENGTH is what sets the perceived
    # weight — the negative axes should read as fine dotted lines.
    dash = spacing * 0.18
    n = 520                          # dashes → reach = spacing*n past the model
    # The DRAWING axes (core.axes): the world's at the top level, the open
    # group's own — at its origin — inside it (issue #44).
    from core import axes as _axes
    o = _axes.ORIGIN
    ox, oy, oz = o.x(), o.y(), o.z()
    for name in ("x", "y", "z"):
        if _axes.is_world():
            dx, dy, dz = _AXIS_DIRS[name]
        else:
            dx, dy, dz = _axes.as_tuple(name)
        start = len(coords) // 3
        coords.extend([ox, oy, oz, ox + dx * pos_len, oy + dy * pos_len,
                       oz + dz * pos_len])
        for k in range(n):
            t0 = k * spacing
            t1 = t0 + dash
            coords.extend([ox - dx * t0, oy - dy * t0, oz - dz * t0,
                           ox - dx * t1, oy - dy * t1, oz - dz * t1])
        spans[name] = (start, len(coords) // 3 - start)
    return coords, spans


def _box_edge_vertices(corners):
    """The twelve edges of a box (``corners`` in ``oriented_box_corners``
    order) as world-space LINES for the GL pass — so the part behind the
    geometry is hidden like any line, the way guides are (issue #23). The
    edit box used to be painted in the QPainter overlay, which has no depth:
    inside a cube its back edges showed through the faces (Marco, 23-09).

    Whole edges, not dashes: the pattern is the shader's (u_stipple 4,
    measured in window pixels, like Back Edges). Tessellating dashes here
    sized them by camera distance, and the count scaled as
    edge_length/(0.012·distance) — zooming into a large open group pushed
    it past a million segments rebuilt and re-uploaded EVERY frame (the
    «viewport dies when I zoom in close» report: 5.8 s/frame at 5 cm on a
    50 m box)."""
    coords = array("f")
    for i in range(8):
        for bit in (1, 2, 4):
            j = i | bit
            if j == i:
                continue
            a, b = corners[i], corners[j]
            if (b - a).length() < 1e-9:
                continue
            coords.extend([a.x(), a.y(), a.z(), b.x(), b.y(), b.z()])
    return coords


def _guide_vertices(guides, spacing: float, selection=(), centre=None,
                    reach: float = 0.0, eye=None):
    """Guides as world-space DASHES for the GL pass, so they are hidden by
    the geometry in front of them like any other line (issue #23,
    @pacaeiro: «guide lines are always in front of other objects, even if
    they are behind the object»).

    The QPainter overlay they used to live in has no depth buffer at all —
    it paints after the render, so a guide could only ever be on top. And
    the cheap fix does not exist: asking the pick index per sample point
    (``_is_occluded``, what the snap engine uses) measured **618 µs a ray**
    on the Plaza Yanque model, so ten guides would have cost 200 ms a
    frame. The depth buffer already knows the answer for free.

    A guide is a HALF-MILLION-METRE line (``GUIDE_HALF_LEN``), so it is not
    dashed end to end: the run is centred on the guide's closest point to
    ``centre`` (the camera target) and reaches ``reach`` metres each way,
    with ``spacing`` scaled to the camera distance — the recipe of
    ``_axes_vertices``, so the on-screen density stays put across zoom and
    the dashes converge toward the horizon in perspective. Dashing the
    whole length instead, under any sane cap, gave 27-metre dashes with
    22-metre gaps: at a 16-metre view the guide fell in a gap and vanished.

    With ``eye`` given, each guide LINE scales ``spacing`` and ``reach``
    by how much farther from the eye its looked-at stretch lies than the
    camera's own distance (never less): a guide 30 m away while the view
    sits a metre from a detail drew 3 cm dashes — under a pixel — over
    15 m, and read as faint or gone on big models (#481); and a 2 cm orbit
    distance left after a deep zoom (#579) did the same to every guide.

    Returns ``(coords, spans)``: a flat float array and
    ``[(first_vertex, count, selected)]``, one entry per guide LINE, so the
    caller can colour the selected ones without a second buffer. Guide
    points are not here — they stay screen-space crosses in the overlay.
    """
    import numpy as np
    coords = array("f")
    spans: list[tuple[int, int, bool]] = []
    spacing = max(float(spacing), 1e-6)
    reach = float(reach) if reach > 0 else spacing * 500.0
    dash = spacing * 0.5
    origin = QVector3D(centre) if centre is not None else QVector3D(0, 0, 0)
    sel = {id(g) for g in (selection or ())}
    n = max(1, min(int(2.0 * reach / spacing), 4000))
    # The camera distance the spacing was made for (eye to centre).
    base_dist = ((QVector3D(eye) - origin).length()
                 if eye is not None else 0.0)
    for g in guides or ():
        if not getattr(g, "is_line", False):
            # A guide POINT measured from a vertex draws its guide SEGMENT
            # (Rafael, Revisión 3): finite, dashed the same way, from the
            # vertex to the point. The cross itself stays in the overlay.
            o = getattr(g, "origin", None)
            p = getattr(g, "point", None)
            if o is None or p is None:
                continue
            seg = p - o
            length = seg.length()
            if length < 1e-9:
                continue
            d = seg / length
            start = len(coords) // 3
            t = 0.0
            while t < length:
                a = o + d * t
                b = o + d * min(t + dash, length)
                coords.extend([a.x(), a.y(), a.z(), b.x(), b.y(), b.z()])
                t += spacing
            count = len(coords) // 3 - start
            if count:
                spans.append((start, count, id(g) in sel))
            continue
        d = getattr(g, "direction", None)
        p = getattr(g, "point", None)
        if d is None or p is None:
            continue
        # Foot of the perpendicular from the centre: the stretch of guide
        # the camera is actually looking at.
        tf = QVector3D.dotProduct(origin - p, d)
        g_sp, g_reach, g_dash = spacing, reach, dash
        if eye is not None and base_dist > 0.0:
            k = max(1.0, (p + d * tf - eye).length() / base_dist)
            g_sp, g_reach, g_dash = spacing * k, reach * k, dash * k
        t0 = tf - g_reach
        start = len(coords) // 3
        # The n dashes in one NumPy pass: a Python loop of QVector3D maths
        # here cost ~2 ms a guide on EVERY frame, so forty guides took a
        # frame from 18 to 110 ms (#816).
        ts = t0 + np.arange(n, dtype=np.float64) * g_sp
        pv = np.array((p.x(), p.y(), p.z()), dtype=np.float64)
        dv = np.array((d.x(), d.y(), d.z()), dtype=np.float64)
        seg = np.empty((n, 2, 3), dtype=np.float32)
        seg[:, 0] = pv + ts[:, None] * dv
        seg[:, 1] = pv + (ts + g_dash)[:, None] * dv
        coords.frombytes(seg.tobytes())
        count = len(coords) // 3 - start
        if count:
            spans.append((start, count, id(g) in sel))
    return coords, spans


def _ray_triangle(
    origin: QVector3D,
    direction: QVector3D,
    v0: QVector3D,
    v1: QVector3D,
    v2: QVector3D,
) -> Optional[float]:
    """Möller–Trumbore ray / triangle intersection. Returns distance ``t``
    along the ray, or ``None`` for a miss / behind-camera hit. The triangle
    is intersected from both sides — front/back orientation does not matter
    because IngeTrazo doesn't (yet) cull back faces."""
    eps = 1e-6
    e1 = v1 - v0
    e2 = v2 - v0
    h = QVector3D.crossProduct(direction, e2)
    a = QVector3D.dotProduct(e1, h)
    if abs(a) < eps:
        return None
    f = 1.0 / a
    s = origin - v0
    u = f * QVector3D.dotProduct(s, h)
    if u < 0.0 or u > 1.0:
        return None
    q = QVector3D.crossProduct(s, e1)
    v = f * QVector3D.dotProduct(direction, q)
    if v < 0.0 or u + v > 1.0:
        return None
    t = f * QVector3D.dotProduct(e2, q)
    if t < eps:
        return None
    return t


def _point_to_segment_distance_2d(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.hypot(px - qx, py - qy)


# ---- Viewport --------------------------------------------------------------

def _parse_number(tok: str):
    """``2``, ``2.5``, ``.5``, ``3/4`` (a fraction), ``1-1/2`` (a mixed
    number, the hyphen form) → float, else None — ``core.units`` reads it,
    refusing a number too long for a float or too big for a model (#185)."""
    from core.units import _number
    return _number(tok)


def _is_chord(modifiers) -> bool:
    """Ctrl or Alt held — a shortcut, not typing. Both together is AltGr on
    Windows, which types characters, so that one still types."""
    ctrl = bool(modifiers & Qt.ControlModifier)
    alt = bool(modifiers & Qt.AltModifier)
    return (ctrl or alt or bool(modifiers & Qt.MetaModifier)) \
        and not (ctrl and alt)


def _merge_mixed_numbers(fields: list) -> list:
    """The usual ``1 1/2"``: a whole number followed by a fraction field is
    ONE mixed number, not two fields — joined with the hyphen form. And a
    feet field followed by inches that carry their mark is ONE length, the
    way it is written: ``5' 3 1/2"`` → ``5'3-1/2"`` (a 5 ft × 3 in
    rectangle is typed ``5';3"``)."""
    out = []
    i = 0
    while i < len(fields):
        f = fields[i]
        nxt = fields[i + 1] if i + 1 < len(fields) else None
        if (nxt is not None
                and re.fullmatch(r"-?\d+(?:'-?\d*)?", f)
                and re.fullmatch(r"\d+/\d+(?:mm|cm|m|in|ft|\"|')?", nxt.lower())):
            # 1 1/2" → 1-1/2"; 1'6 1/2" → 1'6-1/2"; 1' 1/2" → 1'1/2"
            joint = "" if f.endswith(("'", "-")) else "-"
            out.append(f"{f}{joint}{nxt}")
            i += 2
            continue
        out.append(f)
        i += 1
    joined = []
    for f in out:
        if (joined and re.fullmatch(r"-?[\d./-]+'", joined[-1])
                and re.fullmatch(r"[\d./-]+(?:\"|in)", f.lower())):
            joined[-1] += f
        else:
            joined.append(f)
    return joined


def _parse_length_field(field: str):
    """One typed length in metres: metric or imperial, the usual forms.

    ``2`` (the document's unit, issue #33) · ``30cm`` · ``1500mm`` ·
    ``1m20`` · ``2"`` / ``2in`` · ``1'`` / ``1ft`` · ``1'6"`` · ``3/4"`` ·
    ``1'3/4"``. A leading minus is kept. Returns None when the field is not
    a length. The reading itself lives in ``core.units.parse``, the one
    every length field shares."""
    from core.units import parse_length_field
    return parse_length_field(field)


class _AltWatch(QObject):
    """Hears Alt at APPLICATION level, without taking it, for the Paint
    tool's eyedropper pointer (@pacaeiro, #47: «press Alt and release it —
    icon changed but we're still on Paint mode»). The viewport's own key
    events miss every other tap: the first release hands keyboard focus to
    the menu bar, so the next press lands there. The function followed (it
    reads the mouse event's modifiers); only the pointer lagged.

    ONE filter for the whole application, telling every live viewport: an
    application filter runs on every event, and one per viewport made the
    test suite crawl (hundreds of viewports alive)."""

    _instance = None

    def __init__(self, app) -> None:
        super().__init__(app)
        import weakref
        self._viewports = weakref.WeakSet()
        self._clean = False       # Alt down, nothing else pressed since

    @classmethod
    def watch(cls, viewport) -> None:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        if cls._instance is None:
            cls._instance = cls(app)
            app.installEventFilter(cls._instance)
            # Off before Python tears itself down: Qt keeps delivering
            # events (deferred deletes) through an application filter while
            # the interpreter is half gone — the suite segfaulted on exit.
            import atexit
            atexit.register(cls._unwatch)
        cls._instance._viewports.add(viewport)

    @classmethod
    def _unwatch(cls) -> None:
        inst, cls._instance = cls._instance, None
        if inst is None:
            return
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        try:
            if app is not None:
                app.removeEventFilter(inst)
        except RuntimeError:
            pass

    def eventFilter(self, obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.MouseButtonPress:
            # Alt+click is a sample of its own, not a tap.
            self._clean = False
            return False
        if t != QEvent.KeyPress and t != QEvent.KeyRelease:
            return False
        if ev.isAutoRepeat():
            return False
        if ev.key() != Qt.Key_Alt:
            if t == QEvent.KeyPress:
                self._clean = False           # Alt+Tab, Alt+F… is no tap
            return False
        down = t == QEvent.KeyPress
        tap = not down and self._clean
        self._clean = down
        for vp in list(self._viewports):
            try:
                if down != vp._alt_down:
                    vp._apply_alt_cursor(down)
                if tap and vp._alt_tapped():
                    tap = False       # the eyedropper state is shared: once
            except RuntimeError:          # the C++ side already went
                pass
        return False


def _face_geometry(f, memo, triangulate):
    """``(key, normal, area, triangles, centroid)`` of a mesh face, from
    ``memo`` when every corner (holes included) is exactly where it was
    (``memo`` None: computed, not remembered).
    Triangles are ``((x, y, z), …)`` float tuples — copies, never the live
    vertex positions, which edits move in place."""
    loop = [v.position for v in f.loop]
    holes = [[v.position for v in h] for h in f.hole_loops]
    if memo is None:
        key = None                  # a closed group: nothing to remember
    else:
        key = (tuple((p.x(), p.y(), p.z()) for p in loop),
               tuple(tuple((p.x(), p.y(), p.z()) for p in h) for h in holes))
        hit = memo.get(id(f))
        if hit is not None and hit[0] == key:
            return hit
    if len(loop) < 3:
        geom = (key, QVector3D(0.0, 0.0, 1.0), 0.0, [], None, {}, (), None)
    else:
        n_raw = f._newell()
        ln = n_raw.length()
        normal = n_raw / ln if ln > 1e-9 else QVector3D(0.0, 0.0, 1.0)
        tris = [tuple((t.x(), t.y(), t.z()) for t in tri)
                for tri in triangulate(loop, holes, normal)]
        c = f.centroid()
        flat = tuple(x for tri in tris for corner in tri for x in corner)
        props = ((normal.x(), normal.y(), normal.z()), (c.x(), c.y(), c.z()))
        # 5: shaded colour per base colour · 6: triangles as 9 floats each
        # · 7: the soft-edge silhouette props (normal, centroid)
        geom = (key, normal, 0.5 * ln, tris, c, {}, flat, props)
    if memo is not None:
        memo[id(f)] = geom
    return geom


def _finite_point(p) -> bool:
    """Whether ``p`` (a QVector3D or None) is a real point."""
    import math
    return p is not None and all(
        math.isfinite(c) for c in (p.x(), p.y(), p.z()))
