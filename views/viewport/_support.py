# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Module-level helpers, constants and flags shared by the viewport mixins."""
from __future__ import annotations

import importlib
import itertools
import logging
import math
import os
import re
import sys
import time as _time_mod

#: When the hand last moved the mouse, pressed a button or a key over a
#: view (monotonic seconds). Background work that blocks the window for a
#: while (a scene's picture is a whole render) waits for the hand to rest.
LAST_HAND = [0.0]


#: When a key was last pressed over a view, a menu's shortcut included
#: (Ctrl+Z reaches the view only as a ShortcutOverride): the «In model»
#: pictures wait for it too, not to land inside the undo just asked for.
LAST_KEY = [0.0]


def hand_rested(seconds: float) -> bool:
    """Whether nothing has been done over a view for ``seconds`` — and no
    menu is open nor a dialog waiting for an answer. The hand over a menu
    or a dialog never reaches a view: a scene's picture drawn then froze
    the menus and the extension manager for 0.3–0.7 s each (final plaza,
    22-11). Its rest starts again once they close."""
    from PySide6.QtWidgets import QApplication
    if (QApplication.activePopupWidget() is not None
            or QApplication.activeModalWidget() is not None):
        LAST_HAND[0] = _time_mod.monotonic()
        return False
    return _time_mod.monotonic() - LAST_HAND[0] >= seconds
import types
from array import array
from pathlib import Path
from typing import Optional
from core.units import fmt_len as _fmt_len

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

from PySide6.QtCore import QEvent, QObject, Qt, QPointF, QRectF

_HAND_EVENTS = frozenset((QEvent.MouseMove, QEvent.MouseButtonPress,
                          QEvent.MouseButtonRelease, QEvent.KeyPress,
                          QEvent.Wheel))
from PySide6.QtGui import QColor, QImage, QMatrix4x4, QPainter, QVector3D

from core.group import Group, effective_material
from core import layers as _layers
from core.scene import Scene
from core.style import (DEFAULT_FACE_COLOR, FOG_DISTANCE_RANGE,
                        FOG_THICKNESS_RANGE)
from core.materials import material_sig as _material_sig
from core.triangulate import plane_axes


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


def label_clear_of(text: QRectF, avoid: QRectF, bounds: QRectF,
                   gap: float = 4.0) -> QRectF:
    """Where to draw a live value label ``text`` so the pointer (``avoid``)
    does not cover it (#1262): where it is when they do not touch; else
    just right of the pointer, at the same height; else, at the view's
    right edge, just below it; else just above it. All in widget pixels;
    ``bounds`` is the view."""
    if not text.intersects(avoid):
        return QRectF(text)
    right = QRectF(text)
    right.moveLeft(avoid.right() + gap)
    if right.right() <= bounds.right():
        return right
    x = min(text.left(), bounds.right() - text.width())
    below = QRectF(text)
    below.moveTopLeft(QPointF(x, avoid.bottom() + gap))
    if below.bottom() <= bounds.bottom():
        return below
    above = QRectF(text)
    above.moveTopLeft(QPointF(x, avoid.top() - gap - text.height()))
    return above


def _active_cut(scene):
    """What actually CUTS the model now (cuts shown): the active section
    plane and the faces of an active section box, as one
    ``core.section.CutSet`` whose ``side``/``hidden`` ask them all — or
    None. A module function so stub viewports in tests degrade gracefully;
    picks and snaps filter by it — what the cut hides is not clickable nor
    snappable."""
    from core.section import CutSet, cut_planes
    planes = cut_planes(scene)
    return CutSet(planes) if planes else None


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


def _copy_snap_edge(e: _SnapEdge) -> _SnapEdge:
    """A fresh ``_SnapEdge`` like ``e``: one search's edges handed to two
    callers (see Viewport._nearby_edges_unbaked) are not shared."""
    c = _SnapEdge.__new__(_SnapEdge)
    for k in _SnapEdge.__slots__:
        v = getattr(e, k)
        setattr(c, k, QVector3D(v) if isinstance(v, QVector3D) else v)
    return c


def _snap_context_of(vp, place):
    """What the ScreenTip says the snapped geometry belongs to.

    ``None`` for the open context's own loose geometry (and at the root);
    ``"outside"`` for everything drawn around an open group / component —
    its loose mesh, another component, the rest of the model — so the tip
    can say the point is not in the thing being edited; otherwise
    ``"group"`` / ``"component"`` for the placement it was reached through.
    """
    if place is None:
        return None
    scene = getattr(vp, "scene", None)
    ctx = getattr(scene, "edit_group", None)
    if ctx is not None and place is not ctx \
            and getattr(place, "context", None) is not ctx:
        return "outside"
    owner = getattr(place, "owner", None) or place
    is_comp = getattr(owner, "is_instance", None)
    return "component" if (is_comp is not None and is_comp()) else "group"


def _group_pseudo_edge(idx, i: int) -> _SnapEdge:
    """The i-th group hard edge of the pick index as a world pseudo-edge
    that knows its owner and whether that is a group or a component — or
    the rest of the model around an open context ("outside")."""
    gi = getattr(idx, "gedge_gi", None)
    groups = getattr(idx, "gedge_groups", None)
    g = int(gi[i]) if gi is not None and groups else 0
    owner = groups[g] if gi is not None and groups else None
    ctxs = getattr(idx, "gedge_ctx", None)
    if ctxs is not None and g < len(ctxs):
        context = ctxs[g]
    else:
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
#: Clip planes the shaders take: the active section plane and the six faces
#: of the section box (``u_clip_planes`` in basic.vert / depth.vert).
_MAX_CUT_PLANES = 7
GL_STENCIL_TEST = 0x0B90
GL_STENCIL_BUFFER_BIT = 0x00000400
GL_ALWAYS = 0x0207
GL_EQUAL = 0x0202
GL_KEEP = 0x1E00
GL_REPLACE = 0x1E01
#: Stencil bit the foliage cutouts leave, so the ambient occlusion (#954)
#: skips the leaves: a crown of crossed cards reads as one dark corner.
AO_FOLIAGE_BIT = 0x80
GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_ONE = 1
GL_POLYGON_OFFSET_FILL = 0x8037
GL_CULL_FACE = 0x0B44
GL_CW = 0x0900
GL_CCW = 0x0901
GL_FRONT = 0x0404
GL_BACK = 0x0405
GL_LESS = 0x0201
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
GL_TEXTURE2 = 0x84C2
GL_MAX_TEXTURE_SIZE = 0x0D33


from core.paths import app_root

SHADER_DIR = app_root() / "resources" / "shaders"


# ---- Geometry helpers ------------------------------------------------------

#: Beyond this many loose edges the snap engine gets a near-cursor subset
#: instead of the whole mesh: compute_snap walks its edge list in Python
#: ~a dozen times per hover, and an exploded medium import (9k faces =
#: ~20k edges) froze every mouse move (user report, piscina.igz).
_LOOSE_SNAP_CAP = 3000


def _inst_proto_of(mod, base):
    """core._native's InstanceProto of a prototype's local bake."""
    import numpy as np
    z = np.zeros((0, 3))
    v0 = base.get("v0")
    edges = (np.frombuffer(base["edges"], dtype=np.float32)
             .reshape(-1, 6).astype(np.float64)
             if base.get("edges") else np.zeros((0, 6)))
    return mod.InstanceProto(
        np.ascontiguousarray(v0) if v0 is not None else z,
        np.ascontiguousarray(base["e1"]) if v0 is not None else z,
        np.ascontiguousarray(base["e2"]) if v0 is not None else z, edges)


class _PickWarm:
    """The pick index's heavy pure parts, worked out behind the document just
    opened (Viewport.start_pick_warmup): threads that touch nothing but their
    own copies of the arrays' references. What they made reaches the viewport
    in _pick_warm_take, on the GUI thread, and only if it still applies."""

    def __init__(self, mod, protos, grids, bounds=()):
        import queue
        import threading
        from tools.select import _local_bounds as local_bounds
        self.protos: dict = {}
        self.grids: list = []
        self.bounds: list = []
        jobs: queue.SimpleQueue = queue.SimpleQueue()
        for ckey, base in protos:
            jobs.put(("proto", ckey, base))
        for chunk in grids:
            jobs.put(("grid", chunk, {
                "v0": chunk["v0"], "e1": chunk["e1"], "e2": chunk["e2"],
                "tri_ent": chunk["tri_ent"], "rev": chunk.get("rev")}))
        for chunk in bounds:
            jobs.put(("bounds", chunk, {
                "v0": chunk["v0"], "e1": chunk["e1"], "e2": chunk["e2"],
                "edges": chunk["edges"]}))

        def work():
            while True:
                try:
                    kind, a, b = jobs.get_nowait()
                except queue.Empty:
                    with lock:
                        left[0] -= 1
                        last = left[0] == 0
                    if last:
                        # The sorting and copying leave ~1.6 GB of freed heap
                        # on a 5 M face model, which glibc keeps (#1092).
                        from core import malloc_arenas
                        malloc_arenas.trim()
                    return
                try:
                    if kind == "proto":
                        self.protos[a] = _inst_proto_of(mod, b)
                    elif kind == "grid":
                        _split_chunk_spans(b)
                        self.grids.append((a, b))
                    else:
                        local_bounds(b)
                        self.bounds.append((a, b))
                except Exception:      # noqa: BLE001 — the hover will retry
                    pass
        # Daemons: closing the window does not wait for them.
        self.threads = [threading.Thread(target=work, daemon=True)
                        for _ in range(min(8, os.cpu_count() or 2))]
        lock = threading.Lock()
        left = [len(self.threads)]
        for t in self.threads:
            t.start()

    def join(self):
        for t in self.threads:
            t.join()


def _pick_warm_take(vp) -> None:
    """Wait for what the warm-up has left and take it: its prototypes for the
    next InstanceSet, its grids for the chunks that have not moved since."""
    warm = getattr(vp, "_pick_warm", None)
    if warm is None:
        return
    vp._pick_warm = None
    warm.join()
    cache = getattr(vp, "_inst_proto_cache", None)
    if cache is None:
        cache = vp._inst_proto_cache = {}
    cache.update(warm.protos)
    for chunk, snap in warm.grids:
        if ("_span_grid" not in chunk and chunk.get("rev") == snap["rev"]
                and chunk["v0"] is snap["v0"]):
            chunk["_span_grid"] = snap["_span_grid"]
    # (Keyed on the very arrays: a chunk that has moved on just misses it.)
    for chunk, snap in warm.bounds:
        if "_box_bounds" not in chunk:
            chunk["_box_bounds"] = snap["_box_bounds"]


def _entity_owner(entities, i):
    """The owner half of pick-index entity ``i``: a lazy piece of the index
    answers it without building its faces (see views.array_bake)."""
    at = getattr(entities, "owner_at", None)
    return at(i) if at is not None else entities[i][1]


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


#: The hover picks' own kernels in the native engine (pick.rs, Bloque 6a):
#: a ray's test of every span box and the edge grid's gather. Both answer
#: with NumPy's very indices; INGETRAZO_PICK_NATIVE=0 keeps NumPy (for
#: measuring and for the tests that compare both).
_PICK_NATIVE = os.environ.get("INGETRAZO_PICK_NATIVE", "1") != "0"


def _pick_native(name):
    """core._native when the pick kernels are on and it has ``name``."""
    if not _PICK_NATIVE:
        return None
    from core import _native
    mod = _native.native
    return mod if mod is not None and hasattr(mod, name) else None


def _boxes_meet_numpy(o, d, blo, bhi, reach=None):
    """The indices of the boxes ``blo``/``bhi`` (B, 3) the forward ray from
    ``o`` along ``d`` (NumPy (3,) arrays) meets, not past ``reach``: the
    vectorised slab test of ``Viewport._ray_hits_np`` over thousands of
    span boxes at once (its tiny direction components read as 1e-12)."""
    import numpy as np
    with np.errstate(divide="ignore", invalid="ignore"):
        inv_d = 1.0 / np.where(np.abs(d) > 1e-12, d, 1e-12)
        t1 = (blo - o) * inv_d
        t2 = (bhi - o) * inv_d
    tmin = _slab_far(np.minimum(t1, t2))
    tmax = _slab_near(np.maximum(t1, t2))
    meet = tmax >= np.maximum(tmin, 0.0)
    if reach is not None:
        meet &= tmin <= reach
    return np.flatnonzero(meet)


def _boxes_meet_native(o, d, blo, bhi, reach=None):
    """The indices of the boxes ``blo``/``bhi`` (B, 3) the forward ray from
    ``o`` along ``d`` meets (not past ``reach``), from the native engine —
    ``Viewport._ray_hits_np``'s slab test value by value — or None without
    it (the caller runs :func:`_boxes_meet_numpy`)."""
    import numpy as np
    mod = _pick_native("ray_boxes_meet")
    if mod is None or not (isinstance(blo, np.ndarray)
                           and isinstance(bhi, np.ndarray)
                           and blo.dtype == np.float64
                           and bhi.dtype == np.float64
                           and blo.ndim == 2 and blo.shape == bhi.shape
                           and blo.shape[1] == 3):
        return None
    try:
        return mod.ray_boxes_meet(
            (float(o[0]), float(o[1]), float(o[2])),
            (float(d[0]), float(d[1]), float(d[2])),
            np.ascontiguousarray(blo), np.ascontiguousarray(bhi),
            None if reach is None else float(reach))
    except (TypeError, ValueError):
        return None


#: Every chunk entry built (or loaded from disk) takes the next number.
#: Keys that told entries apart by ``id(entry)`` could not: the dict a
#: rebuild replaces is freed at once, and the new one may land at the same
#: address — same id, same rev 0 — so the instance arrays and the GL draw
#: entry derived from the OLD chunk were served as if nothing had changed
#: (a face painted inside a component came back unpainted one level up,
#: Marco, 2026-09-11).
_chunk_uid = itertools.count(1)


def _pv_hole(raw):
    """Zeros the size of ``raw``: a moving group's place in the static
    buffers while its preview draws it elsewhere. All-zero triangles and
    lines have no area and no length, so they draw nothing in any pass."""
    return bytes(len(raw))


_ZEROS: dict = {}


def _zeros(n: int) -> bytes:
    """``n`` zero bytes, the same object for the same size: a gone
    object's place (``_static_slots``) is passed over by identity on the
    next upload, not compared byte by byte."""
    z = _ZEROS.get(n)
    if z is None:
        if len(_ZEROS) > 256:
            _ZEROS.clear()
        z = _ZEROS[n] = bytes(n)
    return z


class _Slot:
    """One object's place in the static buffers (``_static_slots``): the
    object, and the byte sizes it took the last time it was laid out, per
    buffer — what its zeros take once it is gone."""

    __slots__ = ("g", "sizes")

    def __init__(self, g) -> None:
        self.g = g
        self.sizes: dict = {}


class _LazyChunk(dict):
    """A chunk whose draw-only fields are computed on first use: a component
    placement baked for the pick index (#158's lazy placements, hundreds per
    pointer move) needs its triangles, edges and box, never its colours,
    texture runs and re-shading — the dearer two thirds of the bake. Each
    field comes from the same function on the same inputs whenever it is
    asked for, so what is drawn is what the eager bake gave."""
    __slots__ = ("_later",)

    def __init__(self, data, later):
        super().__init__(data)
        self._later = later              # field -> callable making it

    def __missing__(self, key):
        make = self._later.pop(key, None)
        if make is None:
            raise KeyError(key)
        value = make()
        dict.__setitem__(self, key, value)
        return value

    def __setitem__(self, key, value):
        self._later.pop(key, None)
        dict.__setitem__(self, key, value)

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self._later

    def get(self, key, default=None):
        return self[key] if key in self else default

    def _made(self):
        for key in list(self._later):
            self[key]                    # noqa: B018 — makes it
        return self

    def keys(self):
        return dict.keys(self._made())

    def items(self):
        return dict.items(self._made())

    def values(self):
        return dict.values(self._made())

    def __iter__(self):
        return dict.__iter__(self._made())

    def __len__(self):
        return dict.__len__(self._made())

    def copy(self):
        return dict(self.items())


#: The recorded, state-tracking instanced passes: ``None`` follows the
#: experimental engine (on with it, off without — they change how the GPU
#: is fed, and drivers differ); True/False force them (tests draw both).
_LEAN_INSTANCED = None


def _lean_instanced() -> bool:
    if _LEAN_INSTANCED is not None:
        return _LEAN_INSTANCED
    from core import _native
    return _native.native is not None
#: From this many loose edges the snap prefilter's distances go to the
#: engine (10 000: 0.44 ms in NumPy, 0.12 ms native; 2 000: the same).
_LOOSE_NATIVE_MIN = 4096
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
#: The engine answers the corner and occlusion queries for the lazy
#: placements without baking them (tests compare both ways).
_LAZY_NATIVE = True
#: A big document's pick index starts behind it as soon as it opens (see
#: Viewport.start_pick_warmup; the switch is for measuring and for tests).
_PICK_WARM = os.environ.get("INGETRAZO_NO_PICK_WARM", "") != "1"
#: A pointer move over a still view reuses the model as the last frame
#: drew it (Viewport._frame_cache_key); INGETRAZO_FRAME_CACHE=0 turns it
#: off, and every frame draws everything as before.
_FRAME_CACHE = os.environ.get("INGETRAZO_FRAME_CACHE", "1") != "0"
#: Occlusion answers kept a view (Viewport._occluded_many);
#: INGETRAZO_OCCLUSION_MEMO=0 asks every point again.
_OCCLUSION_MEMO = os.environ.get("INGETRAZO_OCCLUSION_MEMO",
                                 "1") != "0"
#: The first corner in sight asked of the native engine in one call
#: (Viewport._first_clear); INGETRAZO_FIRST_CLEAR=0 asks in batches.
_FIRST_CLEAR = os.environ.get("INGETRAZO_FIRST_CLEAR", "1") != "0"
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

    DRAW, VAO, U1I, U1F, U4F, ENABLE, DISABLE, CULL, FRONT, ACTIVE, TEX, \
        STENCIL = range(12)

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

    def stencil_func(self, fn, func, ref, mask):
        self.call(fn, func, ref, mask)
        self._op(self.STENCIL, (func, ref, mask))

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


def _callable_proc(addr: int) -> bool:
    """Whether a context's ``getProcAddress`` answer can be called: some
    Windows drivers' wglGetProcAddress hand back 1, 2, 3 or -1 for an entry
    they do not have, instead of null — none of which GlReplay may jump to
    (the tapes then replay through the PySide wrappers)."""
    return 0x10000 <= addr < 1 << 63


#: The GL entry points GlReplay calls, in _GlTape's opcode order.
_TAPE_FUNCS = (b"glDrawArraysInstanced", b"glBindVertexArray",
               b"glUniform1i", b"glUniform1f", b"glUniform4f", b"glEnable",
               b"glDisable", b"glCullFace", b"glFrontFace",
               b"glActiveTexture", b"glBindTexture", b"glStencilFunc")


class _InstanceBatch(list):
    """One frame's placements of an instanced pool (a plain list of them)
    with their indices in the pool and the pool's matrix rows, so the
    matrix buffer is filled by one NumPy take instead of sixteen floats
    read per placement. ``split``: which of them are the surroundings of
    the open group (``InstancingMixin._instanced_batches``)."""

    __slots__ = ("idx", "mats", "split")


#: The CPU side of a document's bakes — the render/pick chunks of its
#: groups, the instances' derived chunks, the fingerprints and the
#: prototypes' stand-ins — one store per Scene, shared by every viewport
#: that shows it. Four views of the plaza (1 035 objects) baked the model
#: four times over, 16.7 s on the first split; the arrays do not depend on
#: the view, only their upload to each view's own GL context does.
import weakref
#: ``id(scene)`` → ``(weakref to the scene, its store)``. By id, not by the
#: scene itself: a Scene compares by value and has no hash. The weak
#: reference tells a dead scene's id from a new scene born at the same
#: address, and a finalizer drops the store when the scene goes.
_BAKE_STORES: dict = {}
_SHARED_BAKES = ("_group_chunks", "_inst_chunks", "_fp_memo",
                 "_proto_wrappers")


def _bake_store_of(scene) -> dict:
    """The shared store of ``scene``, made on first use; ``None`` for a
    stand-in that cannot be weakly referenced."""
    key = id(scene)
    hit = _BAKE_STORES.get(key)
    if hit is not None and hit[0]() is scene:
        return hit[1]
    try:
        ref = weakref.ref(scene)
    except TypeError:
        return None
    store: dict = {}
    _BAKE_STORES[key] = (ref, store)
    weakref.finalize(scene, _drop_bake_store, key, ref)
    return store


def _drop_bake_store(key, ref) -> None:
    hit = _BAKE_STORES.get(key)
    if hit is not None and hit[0] is ref:
        del _BAKE_STORES[key]


def _bind_bake_store(vp) -> None:
    """Point ``vp``'s shared caches at its scene's store (made on first
    use); another scene, another store. A stub without a scene keeps
    dicts of its own."""
    store = _bake_store_of(getattr(vp, "scene", None))
    if store is None:
        store = {}
    for name in _SHARED_BAKES:
        setattr(vp, name, store.setdefault(name, {}))
    try:
        _LIVE_VIEWS.add(vp)
    except TypeError:
        pass


#: Every viewport made, weakly: the decoded textures are kept only while
#: more than one of them is on screen (:func:`_several_views_shown`).
_LIVE_VIEWS: "weakref.WeakSet" = weakref.WeakSet()


def _several_views_shown() -> bool:
    shown = 0
    for vp in list(_LIVE_VIEWS):
        try:
            if vp.isVisible():
                shown += 1
        except RuntimeError:              # its C++ side already gone
            continue
        if shown > 1:
            return True
    return False


#: Texture images decoded once per file, for every GL context that
#: uploads them: ``path`` → ``(mtime, size, mirrored QImage, cutout)``,
#: the newest last, held to a budget of bytes. Three views joining the
#: plaza's decoded its textures again each (1.6 s of the 3.8 s); the GL
#: texture itself belongs to each context and is made from this.
_DECODED_TEXTURES: dict = {}
_DECODED_BUDGET = 256 * 1024 * 1024


def _decoded_texture(path: str):
    """``(QImage mirrored for GL, cutout)`` of the image at ``path`` — the
    file's current version — or ``None`` when it cannot be loaded.
    ``cutout``: a foliage card of low alpha coverage (mip-averaged alpha
    plus atlas bleed erase or darken the leaves at distance, and the Bayer
    dither turns the rest into ghost speckle: the textured passes sample
    the top level only and cut hard at 0.5)."""
    import os
    try:
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    hit = _DECODED_TEXTURES.get(path)
    if hit is not None and hit[0] == stamp:
        _DECODED_TEXTURES[path] = _DECODED_TEXTURES.pop(path)   # newest last
        return hit[1]
    img = QImage(path)
    if img.isNull():
        _DECODED_TEXTURES.pop(path, None)
        return None
    cutout = False
    if img.hasAlphaChannel():
        small = img.scaled(64, 64).convertToFormat(QImage.Format_Alpha8)
        import numpy as _np
        al = _np.frombuffer(small.constBits(), _np.uint8,
                            count=small.height() * small.bytesPerLine())
        cutout = (float((al > 128).mean()) if len(al) else 1.0) < 0.6
    out = (img.mirrored(), cutout)          # OBJ/.skp V is bottom-up
    _DECODED_TEXTURES.pop(path, None)
    if not _several_views_shown():
        # One view uploads each texture once: keeping the decoded images
        # only held their memory — ~65 MB on the plaza, all the time
        # (release check, 14-11). A view that joins decodes again, once,
        # and from then on the views share the decodings.
        _DECODED_TEXTURES.clear()
        return out
    _DECODED_TEXTURES[path] = (stamp, out)
    total = sum(v[1][0].sizeInBytes() for v in _DECODED_TEXTURES.values())
    for old in list(_DECODED_TEXTURES):
        if total <= _DECODED_BUDGET or old == path:
            break
        total -= _DECODED_TEXTURES.pop(old)[1][0].sizeInBytes()
    return out


def _array_bake():
    """views.array_bake, which imports back here (its import statement ran
    per placement, per frame pass)."""
    return sys.modules.get("views.array_bake") or importlib.import_module(
        "views.array_bake")


def _proto_wrapper(vp, mesh, paint=None):
    """The stable stand-in a prototype mesh is baked through, one per
    (mesh, container paint): ``_group_chunk`` caches by the wrapper's id,
    so the same object must come back for the same mesh — and a painted
    instance (issue #47) gets a wrapper of its own. Module-level so the
    stub viewports in tests reach it too."""
    wrappers = getattr(vp, "_proto_wrappers", None)
    if wrappers is None:
        wrappers = vp._proto_wrappers = {}
    wkey = (id(mesh), _material_sig(paint))
    w = wrappers.get(wkey)
    if w is None:
        w = wrappers[wkey] = types.SimpleNamespace(mesh=mesh, xform=None,
                                                   material=paint)
    else:
        w.material = paint
    return w


def _fp_winding(fp) -> int:
    """The flip count a chunk fingerprint was taken at, 0 when it has no such
    term (see ``_mesh_fingerprint``). Module-level for the same reason as
    :func:`_proto_wrapper`."""
    return fp[7][1] if len(fp) > 7 and fp[7][0] == "winding" else 0


def _flags_read(mesh, entry: dict) -> None:
    """``entry`` has answered for what the mesh's dirty flags announced: they
    clear, and any other bake of this mesh is left behind (``flags_gen``)."""
    if getattr(mesh, "_chunk_dirty", True) or getattr(mesh, "_attrs_dirty", False):
        mesh._flags_gen = getattr(mesh, "_flags_gen", 0) + 1
    mesh._chunk_dirty = False
    mesh._attrs_dirty = False
    entry["flags_gen"] = getattr(mesh, "_flags_gen", 0)


def _scene_blend(gl) -> None:
    """The scene's blending: «over» for the colour and for the alpha. With
    the plain SRC_ALPHA, ONE_MINUS_SRC_ALPHA on both, a pane of 30 % left
    alpha 0.79 on an opaque background (0.3 * 0.3 + 0.7) and two of them
    0.64, so every exported picture came out with holes behind the glass."""
    gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                           GL_ONE, GL_ONE_MINUS_SRC_ALPHA)


#: The face modes Colour by layer applies to: the ones that draw the
#: per-vertex colour. Hidden line, monochrome and wireframe keep their own
#: flat look.
_BY_LAYER_MODES = ("textures", "shaded", "xray")


def _layer_look_sig(scene, style=None) -> tuple:
    """What of the layers changes the paint objects are drawn in: Colour by
    layer, and each layer's colour and transparency — and the style's Front
    color, which dresses the faces that wear no material. ``style``: the one
    the view draws with (a view of several has its own); else the scene's."""
    if style is None:
        style = getattr(scene, "display_style", None)
    by_layer = bool(getattr(style, "color_by_layer", False))
    return (by_layer, getattr(style, "face_mode", None) if by_layer else None,
            tuple((ly.name, ly.color, ly.opacity)
                  for ly in getattr(scene, "layers", ())),
            _front_tint(style))


#: The face modes that draw the per-vertex colour, where the style's Front
#: color reaches the default faces through their bake. Hidden line and
#: Monochrome paint every face flat in it with a uniform instead.
_VCOLOR_MODES = ("textures", "shaded", "xray")


def _front_tint(style):
    """The colour the faces wearing no material bake to under ``style``
    when its Front color is not the stock white, else ``None`` (the
    warm-white default, unchanged). The default is TINTED by the pick
    rather than replaced, so the stock white keeps the stock look and a
    picked colour shows as itself (issue #776: the Front color only
    showed in Hidden line and Monochrome)."""
    if style is None or getattr(style, "face_mode", None) not in _VCOLOR_MODES:
        return None
    front = tuple(float(c) for c in
                  (getattr(style, "front_color", None) or (1.0, 1.0, 1.0))[:3])
    if all(c >= 0.999 for c in front):
        return None
    from core.style import DEFAULT_FACE_COLOR
    return tuple(round(d * c, 4) for d, c in zip(DEFAULT_FACE_COLOR, front))


def _with_front_tint(paint, style):
    """``paint`` with the style's Front color standing in for the default
    material when there is no container paint: a front-only paint, so the
    back faces keep the back tint."""
    if paint:
        return paint
    tint = _front_tint(style)
    if tint is None:
        return paint
    return {"color": tint, "front_only": True}


def _paint_of(vp, group):
    """The container paint faces are baked with: the object's own paint
    (issue #47), or — with Colour by layer on — the layer colours
    (core.layers.layer_paint). ``group`` None is the loose model; a
    prototype stand-in (``_proto_wrapper``) already carries its paint.
    Module-level, like ``_proto_wrapper``, so stub viewports reach it.
    (Its names are the module's: asked 240 000 times to open the plant of
    #158, an import statement each time was a second of it.)"""
    if group is not None and not isinstance(group, Group):
        return effective_material(group)
    scene = getattr(vp, "scene", None)
    worn = effective_material(group)
    if group is not None and group is getattr(scene, "edit_group", None):
        # Open, its faces draw as the loose mesh and keep what they wore
        # closed: the nearest painted container's, not only its own (#1101).
        worn = scene.open_group_paint()
    if scene is None or getattr(vp, "plano_style", None) is not None:
        return worn                            # a sheet's technical look
    style = (getattr(vp, "style_override", None)
             or getattr(vp, "view_style", None)
             or getattr(scene, "display_style", None))
    by_layer = bool(getattr(style, "color_by_layer", False)
                    and style.face_mode in _BY_LAYER_MODES)
    memo = getattr(vp, "_layer_paints", None)
    if memo is None or memo[0] != scene.version:
        memo = vp._layer_paints = (scene.version, {}, _layers.layer_fx(scene))
    fx = memo[2]
    if not by_layer and not fx:
        return _with_front_tint(worn, style)
    own = None if by_layer else _with_front_tint(worn, style)
    key = (by_layer, _layers.object_layer(group), _material_sig(own))
    paint = memo[1].get(key)
    if paint is None:
        base = _layers.layer_paint(scene, group) if by_layer else own
        paint = memo[1][key] = _layers.layer_look(scene, group, base, fx)
    return paint


def _ghost_edge_points(scene) -> array:
    """The ends of the edges of the mesh being edited that View ▸ Hidden
    Geometry draws dotted, on layers that are shown: the hidden ones, and
    the soft ones a curved surface or a bevel reads smooth with (#1361).
    The pick already takes soft edges while the view is on; drawn, they
    are no longer clicked blind.

    Module-level, like :func:`_cache_ver`, so tests reach it without a GL
    context."""
    points = array("f")
    for e in scene.mesh.edges:
        if ((getattr(e, "hidden", False) or getattr(e, "soft", False))
                and scene._layer_state(e)[0]):
            points.extend([e.a.x(), e.a.y(), e.a.z(),
                           e.b.x(), e.b.y(), e.b.z()])
    return points


def _cache_ver(vp):
    """The scene version the per-version caches key on — frozen during a
    groups-only transform preview (see Viewport.begin_groups_preview).
    Module-level so the stub viewports in tests hit it too."""
    frozen = getattr(vp, "_frozen_cache_version", None)
    return frozen if frozen is not None else vp.scene.version


def _content_ver(vp):
    """``_cache_ver`` without the view-only bumps (a selection, a group
    opened: ``Scene.bump_view``) — for caches of what the model IS, which a
    click must not throw away: on the plant of #158 every click re-walked
    21 406 placements and rebuilt every edge and outline (~1 s)."""
    frozen = getattr(vp, "_frozen_cache_version", None)
    if frozen is not None:
        return ("frozen", frozen)
    sc = vp.scene
    # Nor the section planes' own bumps: a plane moved changes no face.
    return getattr(sc, "geometry_version",
                   getattr(sc, "content_version", sc.version))


def _plan_curved_edges(plan):
    """The indices of a lazy plan's curve edges, in edge order (memoised
    on the plan, which cannot change while the mesh stays lazy)."""
    curved = plan.extra.get("curved_edges")
    if curved is None:
        import numpy as np
        ids = plan.curve
        # Most meshes have no curve at all: ``count`` tells in C.
        curved = plan.extra["curved_edges"] = (
            np.empty(0, dtype=np.int64) if ids.count(None) == len(ids)
            else np.array([i for i, c in enumerate(ids) if c is not None],
                          dtype=np.int64))
    return curved


def _lazy_edge_may_be_curve(mesh, a, b, tol=1e-3) -> bool:
    """Whether the edge of ``mesh`` from ``a`` to ``b`` (its own space) may
    be a curve's, asked of a still-lazy mesh's plan without building it.
    False only when no edge with both ends within ``tol`` of the two points
    — far wider than the weld lookups that find the real edge — carries a
    curve; a built (or never lazy) mesh always answers True."""
    from core.lazy_mesh import plan_of
    plan = plan_of(mesh)
    if plan is None:
        return True
    if not len(plan.edges):
        return False
    curved = _plan_curved_edges(plan)
    if not len(curved):
        return False
    import numpy as np
    ends = plan.edges[curved]
    p0, p1 = plan.pos[ends[:, 0]], plan.pos[ends[:, 1]]
    pa = np.array((a.x(), a.y(), a.z()))
    pb = np.array((b.x(), b.y(), b.z()))

    def near(p, q):
        return (np.abs(p - q) <= tol).all(axis=1)
    return bool(((near(p0, pa) & near(p1, pb))
                 | (near(p0, pb) & near(p1, pa))).any())


def _snap_dropped_loose(vp):
    """Ids of the loose edges the inference must not land on, cached per scene
    version. An EMPTY set means ``Viewport._snap_scene`` may hand the raw
    scene over, with no list to build on a hover.

    The engine walked the loose mesh as it is, so an edge hidden on its own —
    Hide with the eraser, the seam of a smoothed surface, an edge on a hidden
    layer — still offered its endpoints and its line. The cursor lit up on
    geometry that draws nothing, and a line drawn to that spot cut the face
    underneath at a point the user could not see: the "phantom corner" that
    segmented a fresh face out of nowhere. Render, pick and ``bounds()``
    already skip those edges; this asks the same rule
    (:meth:`Scene.edge_snappable`) once per change instead of once per edge
    per hover.

    Module-level, like :func:`_cache_ver`, so the stub viewports in tests hit
    it too."""
    scene = vp.scene
    key = (_cache_ver(vp), id(scene.mesh), len(scene.mesh.edges),
           bool(getattr(scene, "show_hidden_geometry", False)))
    memo = getattr(vp, "_loose_snap_drops_cache", None)
    if memo is not None and memo[0] == key:
        return memo[1]
    edges = scene.edges
    drops = {id(e) for e, ok in zip(edges, _edges_snappable(scene, edges))
             if not ok}
    vp._loose_snap_drops_cache = (key, drops)
    return drops


def _edges_snappable(scene, edges):
    """``[scene.edge_snappable(e) for e in edges]``, a plain
    ``core.mesh.Edge`` read by its layer: where the scene keeps its own
    rules (:func:`_plain_edge_rules`), such an edge has no children, no
    attrs, no owner and is no annotation, so ``edge_snappable`` comes down
    to «its layer is visible, and it is not hidden unless the hidden view
    is on» — the layer being its own, or, on the default layer inside an
    open group, the one ``Scene._open_group_layer`` gives it. Each layer
    is looked up once. Asked edge by edge, the rest of the model's 3 700
    loose edges were most of a hover inside an open group (21-11)."""
    if not _plain_edge_rules(scene):
        return [scene.edge_snappable(e) for e in edges]
    from core.mesh import Edge as _Edge
    default = _layers.DEFAULT_LAYER
    show_hidden = bool(getattr(scene, "show_hidden_geometry", False))
    # What _open_group_layer walks the stack for: None for every edge
    # when no open level carries a layer.
    group_layer = None
    for level in reversed(scene._edit_stack or ()):
        group_layer = getattr(level["group"], "layer", None)
        if group_layer:
            break
    visible: dict = {}
    out = []
    for e in edges:
        if type(e) is not _Edge:
            out.append(scene.edge_snappable(e))
            continue
        name = getattr(e, "layer", None) or default
        if name == default and group_layer:
            name = scene._open_group_layer(e) or name
        vis = visible.get(name)
        if vis is None:
            ly = scene.layer(name)
            vis = visible[name] = True if ly is None else bool(ly.visible)
        out.append(vis and (not getattr(e, "hidden", False) or show_hidden))
    return out


def _plain_edge_rules(scene):
    """Whether the pick index may read a plain edge of
    ``scene.edges`` by its layer alone: the scene is a :class:`Scene` that
    keeps its own rules. For a ``core.mesh.Edge`` — no children, no attrs,
    no owner, never an annotation, and in the open mesh — selectable is
    then «layer visible and unlocked», snappable «layer visible», and both
    also want the edge not hidden unless the hidden-geometry view is on;
    the layer state only depends on the edge's layer name."""
    cls = type(scene)
    if not isinstance(scene, Scene):
        return False
    for name in ("entity_selectable", "edge_snappable", "entity_visible",
                 "entity_visible_but_for_layer", "entity_layer",
                 "_layer_state", "_open_group_layer", "similar_hidden",
                 "outside_section_box", "entity_locked", "entity_hidden"):
        if (getattr(cls, name, None) is not getattr(Scene, name, None)
                or name in getattr(scene, "__dict__", {})):
            return False
    return scene.edges is scene.mesh.edges


def _edge_rows(head, k, tail, edges):
    """One of the pick index's edge arrays: the open mesh's part read in
    flat passes (``head[k]``, or none) followed by the ``tail`` rows asked
    edge by edge — or ``None`` with no edges at all."""
    if not edges:
        return None
    import numpy as np
    dtype = np.float64 if k < 2 else bool
    rest = np.asarray(tail, dtype=dtype)
    if head is None:
        return rest
    if k < 2:
        rest = rest.reshape(-1, 3)
    return np.concatenate([head[k], rest]) if len(rest) else head[k]


def wait_for_still_view(vp, timer, ms: int = 120, keys: bool = False) -> bool:
    """For a panel's deferred refresh: ``True`` when it may run now;
    otherwise ``timer`` is started again (``ms``) and the caller returns —
    so the refresh lands once the user stops moving the view. With
    ``keys`` a key pressed over the view in the last moment (``LAST_KEY``)
    keeps it waiting as well."""
    busy = getattr(vp, "view_busy", None)
    now = _time_mod.monotonic()
    try:
        if ((busy is not None and busy())
                or (keys and now - LAST_KEY[0]
                    < getattr(vp, "VIEW_STILL_S", 0.3))):
            # Never starved: after WAIT_MAX_S of waiting it runs anyway.
            first = getattr(timer, "_waiting_since", None)
            if first is None:
                timer._waiting_since = first = now
            if now - first < WAIT_MAX_S:
                timer.start(ms)
                return False
    except RuntimeError:                # a widget being torn down
        pass
    try:
        timer._waiting_since = None
    except (AttributeError, RuntimeError):
        pass
    return True


#: The longest a panel's refresh waits for the view to settle.
WAIT_MAX_S = 5.0


def _ctx_changed(vp, before):
    """``History.context_changed`` (stub viewports in tests have no
    history, or one without it)."""
    cc = getattr(getattr(vp, "history", None), "context_changed", None)
    if cc is not None:
        cc(before)


def _px_near(x, y, ok, px, py, thr, pts=None, seen=None):
    """The projected points ``(x, y)`` in front (``ok``) within ``thr`` px of
    ``(px, py)``: their indices in order and distances, as one ``np.hypot``
    pass over all of them gives them. The native engine finds the
    candidates (the 650 000 corners of the plant of #158 took 12 ms a
    pointer move in NumPy) a hair wider than ``thr``, and those are measured
    here the same way. With the points ``pts`` and the frame's limits
    ``seen`` (see Viewport._depth_limits), those the frame hides are left
    out as well, as Viewport._depth_hidden leaves them out."""
    import numpy as np
    from core import _native
    mod = _native.native
    if mod is not None and hasattr(mod, "points_near_px") and len(x) > 4096:
        args = (np.ascontiguousarray(x, dtype=np.float64),
                np.ascontiguousarray(y, dtype=np.float64),
                np.ascontiguousarray(ok, dtype=bool),
                float(px), float(py), float(thr) * (1.0 + 1e-6) + 1e-6)
        hidden = None
        if seen is not None and _NEAR_SEEN_NATIVE:
            try:
                k = mod.points_near_px(
                    *args, np.ascontiguousarray(pts, dtype=np.float64), seen)
            except TypeError:               # an older module
                k = mod.points_near_px(*args)
                hidden = True
        else:
            k = mod.points_near_px(*args)
            hidden = seen is not None or None
        d = np.hypot(x[k] - px, y[k] - py)
        near = d < thr
        k, d = k[near], d[near]
    else:
        d = np.where(ok, np.hypot(x - px, y - py), np.inf)
        k = np.flatnonzero(d < thr)
        d = d[k]
        hidden = seen is not None or None
    if hidden and len(k):
        keep = ~Viewport._depth_hidden(seen, pts[k], x[k], y[k])
        k, d = k[keep], d[keep]
    return k, d


def _nearest_order(d, thr):
    """``np.argsort(d)`` as far as the entries under ``thr`` go: the same
    indices in the same order, then one entry past them (or none). Only
    the few under the threshold are sorted when their distances are all
    different — a sort's order is then the only one; with a tie the whole
    array is sorted, as before, so a tie breaks the same way (a full sort
    of the open group's edges on every hover with Line, ~0.5 ms in the
    Plaza, 19-11)."""
    import numpy as np
    cand = np.flatnonzero(d < thr)
    dc = d[cand]
    if len(cand) > 1 and len(np.unique(dc)) != len(dc):
        return np.argsort(d)
    order = cand[np.argsort(dc)]
    if len(cand) < len(d):
        # Any entry not under the threshold: what stops the caller.
        rest = np.flatnonzero(~(d < thr))
        order = np.append(order, rest[0])
    return order


def _nearest_within(d, radius, cap):
    """The indices of ``d`` under ``radius``: all of them in order, or past
    ``cap`` the nearest ``cap`` by distance and then index. The native
    engine picks those in one pass (475 000 fixed group edges lay within
    the radius over the plant of #158: ~4 ms of NumPy, twice a move); the
    same ones, by distance and index, whose order a stable sort by
    distance keeps."""
    import numpy as np
    from core import _native
    mod = _native.native
    if (_NEAREST_NATIVE and cap > 0 and len(d) > 4096 and mod is not None
            and hasattr(mod, "nearest_within")):
        return np.asarray(mod.nearest_within(
            np.ascontiguousarray(d, dtype=np.float64), float(radius),
            int(cap)), dtype=np.int64)
    cand = np.flatnonzero(d < radius)
    if len(cand) > cap:
        dc = d[cand]
        if len(cand) > 4 * cap:
            part = np.argpartition(dc, cap - 1)[:cap]
            cand, dc = cand[part], dc[part]
        cand = cand[np.lexsort((cand, dc))[:cap]]
    return cand


#: The cursor's edge and the snap's read off one search in an event
#: (INGETRAZO_EDGES_SHARED=0: two searches, as before).
_EDGES_SHARED = os.environ.get("INGETRAZO_EDGES_SHARED", "1") != "0"


#: The front face at a pixel without gathering every face the ray meets
#: (INGETRAZO_FRONT_LEAN=0: through _face_hits, as before).
_FRONT_LEAN = os.environ.get("INGETRAZO_FRONT_LEAN", "1") != "0"


#: The nearest group edges picked in the native engine
#: (INGETRAZO_NEAREST=0: in NumPy, as before).
_NEAREST_NATIVE = os.environ.get("INGETRAZO_NEAREST", "1") != "0"


#: The depth test of the corners near the cursor in the native engine
#: (INGETRAZO_NEAR_SEEN=0: in NumPy, as before).
_NEAR_SEEN_NATIVE = os.environ.get("INGETRAZO_NEAR_SEEN", "1") != "0"


#: Which three-argument hypot QVector3D's length here is, of those
#: _unit_rays reproduces ("": none; None: not checked yet).
_QV_HYPOT3 = None
#: The C++ libraries whose ``std::hypot(x, y, z)`` _hypot3_f32 knows.
_QV_HYPOTS = ("libstdc++", "msvc", "libc++")


def _hypot3_f32(a, kind="libstdc++"):
    """The three-argument ``std::hypot`` in float of the C++ library
    ``kind``, row by row of ``a`` (N, 3) float32, as Qt's
    ``QVector3D::length`` computes it: libstdc++ scales the largest
    magnitude out; MSVC's STL (Qt on Windows) swaps it to the front, keeps
    it when the other two are below its epsilon and adds the other two
    ratios' squares to 1 in the order the swaps left them."""
    import numpy as np
    if kind == "libc++":
        # Apple libc++ as Clang contracts it: fma(z, z, fma(x, x, y*y)),
        # unscaled (Qt on macOS). The product of two floats is exact in a
        # double; the sum rounds to a double before the float, which could
        # differ from one fused rounding only on an exact tie — none in
        # 200 000 random vectors, and the probe above still decides.
        a = np.asarray(a, dtype=np.float32)
        x, y, z = (a[:, i].astype(np.float64) for i in range(3))
        yy = (y * y).astype(np.float32).astype(np.float64)
        t = (x * x + yy).astype(np.float32).astype(np.float64)
        with np.errstate(over="ignore", invalid="ignore"):
            return np.sqrt((z * z + t).astype(np.float32))
    a = np.abs(a)
    if kind == "msvc":
        x, y, z = a[:, 0], a[:, 1], a[:, 2]
        s = y > x
        x, y = np.where(s, y, x), np.where(s, x, y)
        s = z > x
        x, z = np.where(s, z, x), np.where(s, x, z)
        e = x * np.float32(np.finfo(np.float32).eps)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            p, q = y / x, z / x
            r = x * np.sqrt((np.float32(1) + p * p) + q * q)
        r = np.where((e >= y) & (e >= z), x, r)
        return np.where(np.isinf(a).any(axis=1), np.float32(np.inf),
                        r).astype(np.float32)
    m = a.max(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        q = a / m[:, None]
        s = (q[:, 0] * q[:, 0] + q[:, 1] * q[:, 1]) + q[:, 2] * q[:, 2]
        return np.where(m > 0, m * np.sqrt(s), np.float32(0)).astype(np.float32)


def _qv_hypot3():
    """The library of _QV_HYPOTS whose length is QVector3D's here, or None
    — checked once against QVector3D itself, on vectors from a millimetre
    to tens of kilometres: another C++ library may round the last bit
    differently, and then the rays are built point by point as before."""
    global _QV_HYPOT3
    if _QV_HYPOT3 is None:
        import numpy as np
        rng = np.random.default_rng(158)
        a = (rng.normal(size=(512, 3))
             * 10.0 ** rng.uniform(-3, 4.5, (512, 1))).astype(np.float32)
        a[:8, rng.integers(0, 3, 8)] = 0.0
        want = np.array([QVector3D(*r).length() for r in a.tolist()],
                        dtype=np.float32)
        _QV_HYPOT3 = next((k for k in _QV_HYPOTS
                           if (_hypot3_f32(a, k) == want).all()), "")
    return _QV_HYPOT3 or None


def _unit_rays(eye, pts):
    """The rays ``_is_occluded`` casts from ``eye`` to each of ``pts`` (N, 3),
    bit for bit as QVector3D builds them (float coordinates, its length,
    its division) without making one per point — a pointer move over the
    plant of #158 asks tens of thousands of hidden corners. Returns
    ``(rows, D, dists)``: the points not on the eye, their unit directions
    and distances (float64 of the float values), or None where this
    library's length cannot be reproduced."""
    import numpy as np
    kind = _qv_hypot3()
    if not kind:
        return None
    w = np.asarray(pts, dtype=np.float32).reshape(-1, 3)
    dl = w - np.array([eye.x(), eye.y(), eye.z()], dtype=np.float32)
    L = _hypot3_f32(dl, kind)
    rows = np.flatnonzero(L.astype(np.float64) >= 1e-9)
    D = (dl[rows] / L[rows, None]).astype(np.float64)
    return rows, D, L[rows].astype(np.float64)


def _occlusion_block(o, d, v0, e1, e2):
    """``Viewport._occluded_many``'s NumPy block: the nearest accepted hit
    of each ray ``d`` (r,3) from ``o`` on the triangles (inf: none)."""
    import numpy as np
    if not len(v0):
        return np.full(len(d), np.inf)
    s = o - v0
    q = np.cross(s, e1)
    uq = np.einsum("ij,ij->i", e2, q)
    p = np.cross(d[:, None, :], e2[None, :, :])
    det = np.einsum("nj,rnj->rn", e1, p)
    ok = _occlusion_det_ok(det, d, e1, e2)
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    u = np.einsum("nj,rnj->rn", s, p) * inv
    v = (d @ q.T) * inv
    t = uq[None, :] * inv
    hit = (ok & (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (u + v <= 1.0)
           & (t > 1e-6))
    return np.where(hit, t, np.inf).min(axis=1)


def _occlusion_det_ok(det, d, e1, e2):
    """Which (ray, triangle) pairs of the occlusion block are not grazing:
    ``|det| > 1e-6``, and a smaller det read against the triangle's own
    size, as :func:`_moller_trumbore` reads it (#1294) — det is
    (e1 × e2)·d, so a 1 mm square met head-on (det ≈ 6e-7) hid nothing.
    ``det`` (r, n) of rays ``d`` (r, 3) on triangles ``e1``, ``e2`` (n, 3);
    core/occlusion.rs reads it the same way."""
    import numpy as np
    ok = np.abs(det) > 1e-6
    small = ~ok & (det != 0.0)
    if small.any():
        rr, nn = np.nonzero(small)
        scale = (np.linalg.norm(np.cross(e1[nn], e2[nn]), axis=1)
                 * np.linalg.norm(d[rr], axis=1))
        # A triangle of no area (its cross product nought) hides nothing.
        ok[rr, nn] = (np.abs(det[rr, nn]) > 1e-6 * scale) & (scale > 0.0)
    return ok


def _placed_maps(xf):
    """``(L, tv, tp)`` of a placement matrix (QMatrix4x4): its linear part
    and the maps a component bake puts local directions and positions
    through. Term by term, not ``a @ L.T``: a BLAS product sums in an order
    of its own (fused, blocked), and the native engine must find the very
    same world triangles and corners without baking them (#158) —
    ((x·L0 + y·L1) + z·L2) + t, as core/instances.rs writes it."""
    import numpy as np
    m = np.array(xf.data(), dtype=np.float64).reshape(4, 4, order="F")
    L, t = m[:3, :3], m[:3, 3]

    def tv(a):                           # direction vectors (no translation)
        return (a[:, 0:1] * L[:, 0] + a[:, 1:2] * L[:, 1]
                + a[:, 2:3] * L[:, 2])

    def tp(a):                           # positions
        return tv(a) + t
    return L, tv, tp


def _batch_instances(base, xfs, tri_parts, hard_parts, soft_parts,
                     n_parts) -> None:
    """The world triangles, hard and soft edges (with normals) of every
    copy of prototype chunk ``base`` placed by the matrices ``xfs``, added
    to the lists :meth:`Viewport.hlr_geometry_now` joins. The maps of
    :func:`_placed_maps`, term by term, over all the copies at once."""
    import numpy as np
    m = np.stack([np.array(x.data(), dtype=np.float64).reshape(4, 4, order="F")
                  for x in xfs])
    L, t = m[:, :3, :3], m[:, :3, 3]            # (k, 3, 3), (k, 3)

    def tv(a):                                   # (n, 3) → (k, n, 3)
        return (a[None, :, 0:1] * L[:, None, :, 0]
                + a[None, :, 1:2] * L[:, None, :, 1]
                + a[None, :, 2:3] * L[:, None, :, 2])

    def tp(a):
        return tv(a) + t[:, None, :]

    v0 = base.get("v0")
    if v0 is not None and len(v0):
        w0 = tp(np.asarray(v0, dtype=np.float64))
        w1 = tv(np.asarray(base["e1"], dtype=np.float64))
        w2 = tv(np.asarray(base["e2"], dtype=np.float64))
        tri_parts.append(np.stack([w0, w0 + w1, w0 + w2],
                                  axis=2).reshape(-1, 3, 3))
    if base.get("edges"):
        a = np.frombuffer(base["edges"], np.float32).reshape(-1, 3)
        we = tp(a.astype(np.float64)).astype(np.float32)
        hard_parts.append(we.reshape(-1, 2, 3).astype(np.float64))
    sp = base.get("soft_pts")
    if sp is not None and len(sp):
        s6 = np.asarray(sp).reshape(-1, 6).astype(np.float64)
        a0 = tp(s6[:, 0:3]).astype(np.float32).astype(np.float64)
        a1 = tp(s6[:, 3:6]).astype(np.float32).astype(np.float64)
        soft_parts.append(np.stack([a0, a1], axis=2).reshape(-1, 2, 3))
        inv = np.empty_like(L)
        for i in range(len(L)):
            try:
                inv[i] = np.linalg.inv(L[i])
            except np.linalg.LinAlgError:
                inv[i] = np.eye(3)

        def tn(a):                                # unit normals
            a = np.asarray(a, dtype=np.float64)
            out = np.matmul(a[None], inv)         # a @ inv(L) = a @ n_mat.T
            ln = np.linalg.norm(out, axis=2, keepdims=True)
            return out / np.where(ln > 1e-12, ln, 1.0)
        n0 = tn(base["soft_n0"])
        n1 = np.where(np.asarray(base["soft_single"])[None, :, None],
                      np.nan, tn(base["soft_n1"]))
        n_parts.append(np.stack([n0, n1], axis=2).reshape(-1, 2, 3))


def _cat_kept(vp, slot, parts):
    """``np.concatenate(parts)``, the same array again while the parts are
    the same objects: the pick index is rebuilt on each change of its lazy
    set (#158), and joined its static triangles anew — 1.4 million rows,
    ~100 MB, a few times a pointer move over the plant of #158. Nothing
    writes into these arrays."""
    import numpy as np
    memo = getattr(vp, "_pick_cat_memo", None)
    if memo is None:
        memo = {}
        try:
            vp._pick_cat_memo = memo
        except AttributeError:
            pass
    m = memo.get(slot)
    if m is not None and len(m[0]) == len(parts) and all(
            a is b for a, b in zip(m[0], parts)):
        return m[1]
    out = parts[0] if len(parts) == 1 else np.concatenate(parts)
    memo[slot] = (list(parts), out)
    return out


def _offset_kept(vp, te, offset):
    """``te + offset``, the same array again for the same ``te`` and
    offset (see :func:`_cat_kept`)."""
    if not offset:
        return te
    m = getattr(vp, "_pick_te_memo", None)
    if m is not None and m[0] is te and m[1] == offset:
        return m[2]
    out = te + offset
    try:
        vp._pick_te_memo = (te, offset, out)
    except AttributeError:
        pass
    return out


#: From this many points up, _project_px goes to the native engine.
_PROJECT_NATIVE_MIN = 2048


def _project_px_numpy(pts, M, width, height):
    """``Viewport._project_px`` in NumPy, with the MVP ``M`` (4, 4) and the
    widget's size: the reference the native ``project_px`` matches."""
    import numpy as np
    # Term by term, as _instance_chunk bakes (and core/instances.rs
    # projects the corners it does not bake): a BLAS product sums in an
    # order of its own.
    clip = (pts[:, 0:1] * M[:, 0] + pts[:, 1:2] * M[:, 1]
            + pts[:, 2:3] * M[:, 2] + M[:, 3])
    w = clip[:, 3]
    ok = w > 0
    safe = np.where(ok, w, 1.0)
    px = (clip[:, 0] / safe * 0.5 + 0.5) * width
    py = (1.0 - (clip[:, 1] / safe * 0.5 + 0.5)) * height
    return px, py, ok


def _slab_far(t):
    """``nanmax`` over the last (x, y, z) axis of a slab test, column by
    column: a reduction along an axis of three was ~4x slower, and the
    lazy pick index runs one per ray query (25 a mouse move with Line over
    the plant of #158)."""
    import numpy as np
    return np.fmax(np.fmax(t[..., 0], t[..., 1]), t[..., 2])


def _slab_near(t):
    """``nanmin`` twin of :func:`_slab_far`."""
    import numpy as np
    return np.fmin(np.fmin(t[..., 0], t[..., 1]), t[..., 2])


def _moller_trumbore(o, d, v0, e1, e2):
    """Möller–Trumbore of the ray ``o`` + t·``d`` against triangles (v0, e1,
    e2) (N, 3): ``(t, hit)``, with the thresholds of :func:`_ray_triangle`.
    The pick index's pass and the lazy placements' (#158) run this one, so
    the same triangle gives the same t whichever holds it. Through the
    native engine when it reproduces this NumPy (:func:`_mt_native`)."""
    nat = _mt_native()
    if nat is not None and _mt_arrays_ok(v0, e1, e2):
        mod, modes = nat
        o3 = (float(o[0]), float(o[1]), float(o[2]))
        d3 = (float(d[0]), float(d[1]), float(d[2]))
        try:
            t, hit = mod.ray_tris(o3, d3, v0, e1, e2, modes)
        except (ValueError, TypeError):
            return _moller_trumbore_py(o, d, v0, e1, e2)
        if _MT_SHADOW[0] > 0:
            # Still on trial: NumPy answers, the engine is compared.
            tp, hp = _moller_trumbore_py(o, d, v0, e1, e2)
            _mt_judge(_mt_same(t, tp) and bool((hit == hp).all()))
            return tp, hp
        return t, hit
    return _moller_trumbore_py(o, d, v0, e1, e2)


#: The ray pass in the native engine (core/rays.rs) once it was found to
#: give this NumPy's very bits: (module, dot-product modes), False when it
#: does not (Python for the session), None until first asked. The pass was
#: ~4 ms of a slow Line frame in the Plaza's 9 674-face group and ~4.4 ms
#: of Push/Pull's distance inference (19-11), most of it NumPy calls on a
#: few thousand rows and the row gathers before them.
_MT_NATIVE = None
#: How many live passes are still answered by NumPy and compared with the
#: engine before the engine answers alone (any difference: NumPy for good):
#: 64, about a second of hovering — 200 outlasted a whole bench of three
#: gestures in the Plaza, every pass the same bits (19-11);
#: INGETRAZO_RAYS_SHADOW sets it (0: the engine alone at once, to measure).
_MT_SHADOW = [int(os.environ.get("INGETRAZO_RAYS_SHADOW", "64"))]
#: What a native ray pass that could not run stands in for.
_MT_FAILED = object()
#: The switch, for measuring and for the tests that compare both.
_MT_NATIVE_ON = os.environ.get("INGETRAZO_RAYS_NATIVE", "1") != "0"


def _mt_set(value):
    global _MT_NATIVE
    _MT_NATIVE = value


def _mt_judge(same: bool):
    """One live pass compared: one fewer to go, or NumPy for good."""
    if same:
        _MT_SHADOW[0] -= 1
        if _MT_SHADOW[0] == 0:
            logging.getLogger(__name__).info(
                "Native ray pass matched NumPy on its live trial")
    else:
        _MT_SHADOW[0] = 0
        _mt_set(False)
        logging.getLogger(__name__).warning(
            "Native ray pass differs from NumPy on a live ray; using Python")


def _mt_same(a, b) -> bool:
    """Whether two float arrays hold the same bits (any NaN for any NaN:
    a NaN row is never a hit, and its payload is the CPU's)."""
    import numpy as np
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        return False
    same = a.view(np.int64) == b.view(np.int64)
    return bool((same | (np.isnan(a) & np.isnan(b))).all())


def _mt_arrays_ok(*arrs) -> bool:
    """Whether the engine can read ``arrs`` as they are: (N, 3) float64
    rows, C-contiguous (else the call stays in NumPy)."""
    import numpy as np
    for a in arrs:
        if not (isinstance(a, np.ndarray) and a.dtype == np.float64
                and a.ndim == 2 and a.shape[1] == 3
                and a.flags.c_contiguous):
            return False
    return True


def _mt_native():
    """``(core._native module, modes)`` when the engine's ray pass gives
    :func:`_moller_trumbore_py`'s bits here, else None. NumPy sums the
    pass's dot products through ``einsum``, a BLAS ``gemv`` (``q @ d``) and
    ``norm``: each in an order of its own, fused or not, which hangs on the
    CPU and the BLAS build (on this machine, 19-11: ``einsum`` sums
    (x0·y0 + x2·y2) + x1·y1 unfused, ``q @ d`` fma(x2, y2, fma(x0, y0,
    x1·y1)) and, over a single row, fma(x2, y2, fma(x1, y1, x0·y0))). So
    the first use tries the engine's 24 ways of summing three products
    against each and keeps the one that matches on a fixed sample, then
    holds the whole pass against NumPy on a second sample (grazing, tiny
    and degenerate triangles, NaN and infinity, one row and many); the
    first live passes are still answered by NumPy and compared
    (``_MT_SHADOW``). No mode or any difference: Python for the session,
    as :func:`core.snap._native_hits` does."""
    if _MT_NATIVE is not None:
        return _MT_NATIVE or None
    if not _MT_NATIVE_ON:
        return None
    from core import _native
    mod = _native.native
    if mod is None or not (hasattr(mod, "ray_tris")
                           and hasattr(mod, "ray_face_min")
                           and hasattr(mod, "ray_dot3_probe")):
        return None                   # not cached: the switch may change
    _mt_set(False)
    try:
        modes = _mt_modes(mod)
        if modes is not None and _mt_sample_match(mod, modes):
            _mt_set((mod, modes))
        else:
            logging.getLogger(__name__).info(
                "Native ray pass does not match this NumPy; using Python")
    except Exception as exc:  # noqa: BLE001 — then Python
        logging.getLogger(__name__).warning(
            "Native ray pass probe failed, using Python: %s", exc)
    return _MT_NATIVE or None


def _mt_dot_sample(seed: int, n: int):
    """(a, b) (n, 3) rows whose dot products round differently in each
    summation order: mixed magnitudes, one term cancelling the other two,
    zeros, signed zeros (all three products -0 too) and subnormals."""
    import numpy as np
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(n, 3)) * 10.0 ** rng.uniform(-4, 4, (n, 1))
    b = rng.normal(size=(n, 3)) * 10.0 ** rng.uniform(-4, 4, (n, 1))
    k = rng.integers(0, 3, n)
    rows = np.arange(n)
    o1, o2 = (k + 1) % 3, (k + 2) % 3
    part = a[rows, o1] * b[rows, o1] + a[rows, o2] * b[rows, o2]
    bk = np.where(b[rows, k] == 0.0, 1.0, b[rows, k])
    cancel = rows % 3 != 0
    a[rows[cancel], k[cancel]] = (-(part / bk)
                                  * (1.0 + rng.normal(size=n) * 1e-9))[cancel]
    a[rows % 17 == 5, 1] = 0.0
    a[rows % 19 == 7, 2] = -0.0
    a[rows % 23 == 11] *= 1e-160
    zero = rows % 13 == 4
    a[zero] = np.where(rng.random((int(zero.sum()), 3)) < 0.5, -0.0, 0.0)
    if n > 1:
        a[0] = -0.0                       # every product -0 (b[0] != 0)
    return a, b


def _mt_pick_mode(mod, cases, root: bool = False):
    """The first of the engine's dot-product modes that gives ``want`` for
    every ``(a, b, want)`` of ``cases`` (with ``root``, the square root of
    ``a``·``a`` does), or None."""
    import numpy as np
    for mode in range(48):
        if all(_mt_same(np.sqrt(mod.ray_dot3_probe(a, a, mode)) if root
                        else mod.ray_dot3_probe(a, b, mode), want)
               for a, b, want in cases):
            return mode
    return None


def _mt_modes(mod):
    """``(einsum, gemv, gemv of one row, ray norm, row norms)`` modes that
    reproduce this NumPy on a fixed sample (see :func:`_mt_native`), or
    None."""
    import numpy as np
    sizes = (1, 2, 3, 4, 5, 7, 8, 9, 16, 17, 33, 64, 257, 1000, 5003)
    es, mm, mm1, dd, sq = [], [], [], [], []
    for i, n in enumerate(sizes):
        a, b = _mt_dot_sample(1294 + i, n)
        if i % 2:
            # Rows a pass reads in place start anywhere in the index: 8
            # bytes off a vector boundary too (the same sums here, 19-11).
            room = np.empty((n + 1, 3))
            room[1:] = a
            a = room[1:]
        es.append((a, b, np.einsum("ij,ij->i", a, b)))
        d = np.ascontiguousarray(b[-1])
        dm = np.ascontiguousarray(np.broadcast_to(d, a.shape))
        if n > 1:
            mm.append((a, dm, a @ d))
        # One row: NumPy asks BLAS for a dot, not a gemv.
        k = min(n, 40)
        mm1.append((a[:k], dm[:k], np.array(
            [(a[r:r + 1] @ d)[0] for r in range(k)])))
        # ``np.linalg.norm`` of the ray (a BLAS dot) and of rows (a
        # reduction), compared as the roots the pass takes.
        dd.append((a[:k], None, np.array(
            [float(np.linalg.norm(a[r])) for r in range(k)])))
        sq.append((a, None, np.linalg.norm(a, axis=1)))
    out = (_mt_pick_mode(mod, es), _mt_pick_mode(mod, mm),
           _mt_pick_mode(mod, mm1), _mt_pick_mode(mod, dd, root=True),
           _mt_pick_mode(mod, sq, root=True))
    return None if None in out else out


def _mt_tri_sample(seed: int = 1462, n: int = 3000):
    """A ray and triangles (v0, e1, e2) for :func:`_mt_sample_match`: hits
    and misses near every edge, grazing and tiny triangles (the small-det
    reading of #1294), degenerate ones, triangles behind the ray, and NaN
    and infinity."""
    import numpy as np
    rng = np.random.default_rng(seed)
    o = rng.normal(size=3) * 10.0
    d = rng.normal(size=3)
    d /= np.linalg.norm(d)
    size = 10.0 ** rng.uniform(-4, 2, (n, 1))
    e1 = rng.normal(size=(n, 3)) * size
    e2 = rng.normal(size=(n, 3)) * size
    # Aim most of them at the ray: v0 so that o + t·d lands at (u, v),
    # some right on an edge or a corner.
    t = rng.uniform(-2.0, 50.0, (n, 1))
    u = rng.uniform(-0.1, 1.1, (n, 1))
    v = rng.uniform(-0.1, 1.1, (n, 1)) * (1.0 - u)
    u[::7] = 0.0
    v[3::7] = 0.0
    v[5::7] = 1.0 - u[5::7]
    v0 = o + t * d - u * e1 - v * e2
    k = n // 10
    e2[:k] = e1[:k] * rng.uniform(-2, 2, (k, 1)) + np.cross(
        e1[:k], d) * 1e-9                                  # grazing
    e1[k:k + 20] = 0.0                                     # degenerate
    e2[k + 20:k + 40] = e1[k + 20:k + 40] * 3.0            # collinear
    sq = 1e-3 * np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    e1[k + 40:k + 80], e2[k + 40:k + 80] = sq[0], sq[1]    # 1 mm, head-on
    v0[k + 80:k + 85, 0] = (np.nan, np.inf, -np.inf, 1e300, -1e300)
    e2[k + 85:k + 90, 1] = (np.nan, np.inf, -np.inf, 1e300, 0.0)
    return o, d, np.ascontiguousarray(v0), e1, e2


def _mt_sample_match(mod, modes) -> bool:
    """Whether the engine's pass is :func:`_moller_trumbore_py` on a fixed
    sample, bit for bit: the per-row answer over several row counts (a
    head-on ray too, for the small-det reading), and the per-entity and
    global minima of :meth:`Viewport._ray_hits`."""
    import numpy as np
    o, d, v0, e1, e2 = _mt_tri_sample()
    rays = [(o, d), (o, np.array([0.0, 0.0, -1.0])),
            (np.array([3e-4, 2e-4, 1.0]), np.array([0.0, 0.0, -1.0]))]
    v0h = v0.copy()
    v0h[-200:] = np.array([0.0, 0.0, 0.0])             # under the third ray
    e1h = e1.copy()
    e2h = e2.copy()
    e1h[-200:] = np.array([1e-3, 0.0, 0.0])
    e2h[-200:] = np.array([0.0, 1e-3, 0.0])
    with np.errstate(all="ignore"):
        for ro, rd in rays:
            o3, d3 = tuple(ro.tolist()), tuple(rd.tolist())
            for lo, hi in ((0, 1), (5, 6), (0, 2), (0, 3), (0, 17),
                           (100, 1100), (0, len(v0))):
                for a, b, c in ((v0, e1, e2), (v0h, e1h, e2h)):
                    a, b, c = (np.ascontiguousarray(x[lo:hi])
                               for x in (a, b, c))
                    tp, hp = _moller_trumbore_py(ro, rd, a, b, c)
                    t, hit = mod.ray_tris(o3, d3, a, b, c, modes)
                    if not (_mt_same(t, tp) and (hit == hp).all()):
                        return False
            te = (np.arange(len(v0)) // 3).astype(np.int64)
            mask = np.ones(te[-1] + 1, dtype=bool)
            mask[::4] = False
            for a, b, c in ((v0, e1, e2), (v0h, e1h, e2h)):
                tp, hp = _moller_trumbore_py(ro, rd, a, b, c)
                hp = hp & mask[te]
                want = np.full(len(mask), np.inf)
                rows = np.flatnonzero(hp)
                np.minimum.at(want, te[rows], tp[rows])
                got = np.full(len(mask), np.inf)
                mod.ray_face_min(o3, d3, a, b, c, te, 0, mask, modes,
                                 face_t=got)
                if not _mt_same(got, want):
                    return False
                g = mod.ray_face_min(o3, d3, a, b, c, te, 0, mask, modes)
                wg = float(tp[hp].min()) if hp.any() else float("inf")
                if g != wg:
                    return False
    return True


def _moller_trumbore_py(o, d, v0, e1, e2):
    """:func:`_moller_trumbore` in NumPy: the reference the native pass is
    held to, and the pass wherever the engine is off or does not match."""
    import numpy as np
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-6
    small = ~ok & (det != 0.0)
    if small.any():
        # det is (e1 × e2)·d: it shrinks with the triangle's area, so a
        # 1 mm square met head-on fell under the 1e-6 meant for grazing
        # rays and could not be picked (#1294). Read those as the angle
        # between the ray and the triangle's plane instead.
        at = np.nonzero(small)[0]
        scale = (np.linalg.norm(np.cross(e1[at], e2[at]), axis=1)
                 * float(np.linalg.norm(d)))
        ok[at] = np.abs(det[at]) > 1e-6 * scale
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = o - v0
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    v = (q @ d) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = (ok & (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (u + v <= 1.0)
           & (t > 1e-6))
    return t, hit


#: How the rest of the model reads while a group is open for editing.
#: ``normal`` draws it as always, ``fade`` washes it out behind the group
#: being edited (the default), ``hide`` leaves it out of the frame.
EDIT_REST_MODES = ("normal", "fade", "hide")
#: Default for how far the context is mixed TOWARD grey (0 = untouched, 1 =
#: fully washed). It is a wash, not transparency: the context keeps writing
#: depth, so it still occludes itself and never turns the model into glass.
#: The user-adjustable value lives on :class:`Viewport`; this constant remains
#: the default and the fallback for the small viewport stubs used by tools and
#: tests.
EDIT_REST_FADE = 0.75

#: The edit box must sit clear of the geometry. A tight box disappears on a
#: cuboid because every dotted segment lands exactly on a model edge. Keep a
#: small screen-space gutter, allowed to grow a little with a large object but
#: capped so a long beam does not acquire a huge empty envelope.
EDIT_BOX_PAD_MIN_PX = 8.0
EDIT_BOX_PAD_MAX_PX = 32.0
EDIT_BOX_PAD_RATIO = 0.05


def edit_fade_color(background) -> tuple:
    """What the rest of the model fades TOWARDS while a group is edited: a
    grey half way between the background and a neutral mid grey. Fading
    to the background itself left white faces on a light background
    looking the same as before — nothing said you were inside a group
    («quiero que lo demás quede gris», 14-10). Towards this grey the rest
    reads grey on a light background and dim on a dark one, and what is
    being edited keeps its colours."""
    return tuple(0.5 * float(c) + 0.5 * 0.55 for c in list(background)[:3])


def fog_depth_range(distance: float, thickness: float) -> tuple[float, float]:
    """Absolute axial fog start/end distances, in model units (metres).

    They deliberately depend on neither the camera orbit distance nor scene
    bounds: moving the camera changes which surfaces cross these fixed depths,
    but never silently rescales the user's settings.
    """
    def finite_clamped(value, default: float, bounds: tuple,
                       floor: float = 0.0) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(value):
            return default
        lo, hi = float(bounds[0]), float(bounds[1])
        return min(hi, max(max(lo, floor), value))

    start = finite_clamped(
        distance, 10.0, FOG_DISTANCE_RANGE)
    minimum = max(float(FOG_THICKNESS_RANGE[0]), 1e-6)
    width = finite_clamped(
        thickness, 10.0, FOG_THICKNESS_RANGE, minimum)
    return start, start + width


def _safe_rgb(raw, fallback) -> tuple[float, float, float]:
    """A finite RGB triple clamped to the range accepted by OpenGL."""
    try:
        rgb = tuple(float(c) for c in raw)
    except (TypeError, ValueError):
        return tuple(fallback)
    if len(rgb) < 3 or not all(math.isfinite(c) for c in rgb[:3]):
        return tuple(fallback)
    return tuple(min(1.0, max(0.0, c)) for c in rgb[:3])


def effective_fog_color(style) -> tuple[float, float, float]:
    """The finite, clamped RGB used by geometry and backdrop fog."""
    use_background = bool(getattr(style, "fog_use_background", False))
    fallback = ((0.9, 0.91, 0.92) if use_background
                else (0.74, 0.76, 0.78))
    raw = (getattr(style, "background", fallback) if use_background
           else getattr(style, "fog_color", fallback))
    return _safe_rgb(raw, fallback)


def fog_backdrop_strength(style) -> float:
    """Fog strength for the environment at the back of the scene.

    As is usual in modellers, the environment represents zero visibility beyond the
    right handle, so normal fog ranges make it the fog colour. The final ten
    percent of the logarithmic range progressively restores the styled sky;
    with the right handle at its farthest stop the environment is untouched.
    """
    if not bool(getattr(style, "fog_enabled", False)):
        return 0.0
    _start, end = fog_depth_range(
        getattr(style, "fog_distance", 10.0),
        getattr(style, "fog_thickness", 10.0))
    lo, hi = (float(v) for v in FOG_DISTANCE_RANGE)
    scale = 0.01  # Same useful near-camera resolution as the range widget.
    end = min(hi, max(lo, end))
    position = (math.log1p((end - lo) / scale)
                / math.log1p((hi - lo) / scale)) if hi > lo else 1.0
    clear = min(1.0, max(0.0, (position - 0.90) / 0.10))
    clear = clear * clear * (3.0 - 2.0 * clear)
    return 1.0 - clear


def _toward_fog(rgb, fog, strength: float) -> tuple[float, float, float]:
    """Mix one safe RGB triple toward fog without changing its alpha."""
    return tuple(a + (b - a) * strength for a, b in zip(rgb, fog))


def fog_backdrop(style) -> tuple[tuple[float, float, float], bool]:
    """Return ``(clear_colour, draw_sky)`` for a display style.

    Both a flat background and the styled environment use the same far-depth
    strength, preventing a clear sky behind fogged geometry.
    """
    base = _safe_rgb(getattr(style, "background", (0.9, 0.91, 0.92)),
                     (0.9, 0.91, 0.92))
    strength = fog_backdrop_strength(style)
    # No fog: nothing moves toward it (a + (b - a) * 0 is a), and the fog
    # colour is not worked out on every frame of a style without fog.
    color = (base if strength == 0.0
             else _toward_fog(base, effective_fog_color(style), strength))
    return color, bool(getattr(style, "sky", False))


def fog_sky_colors(style) -> tuple[tuple[float, float, float], ...]:
    """Conventionally fogged ``(sky, horizon, ground)`` colours.

    Sky and horizon reach the fog colour at zero visibility. The ground keeps
    most of its foreground tone; :meth:`Viewport._sky_gradient` then fades it
    to the fog-coloured horizon, producing depth instead of a flat grey card.
    """
    colors = (
        _safe_rgb(getattr(style, "sky_color", (0.925, 0.935, 0.945)),
                  (0.925, 0.935, 0.945)),
        _safe_rgb(getattr(style, "horizon_color", (1.0, 1.0, 1.0)),
                  (1.0, 1.0, 1.0)),
        _safe_rgb(getattr(style, "ground_color", (0.815, 0.820, 0.815)),
                  (0.815, 0.820, 0.815)),
    )
    strength = fog_backdrop_strength(style)
    picked_horizon = getattr(style, "horizon_color", None) is not None
    if strength == 0.0:
        # No fog: the colours as they are (see fog_backdrop).
        return (colors[0], colors[1] if picked_horizon else None, colors[2])
    fog = effective_fog_color(style)
    horizon = (_toward_fog(colors[1], fog, strength)
               if strength > 0.0 or picked_horizon
               else None)
    return (_toward_fog(colors[0], fog, strength), horizon,
            _toward_fog(colors[2], fog, strength * 0.15))

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


def _load_edit_rest_fade() -> float:
    """Saved strength of the grey edit context, safely clamped to 0..1."""
    from PySide6.QtCore import QSettings
    try:
        value = float(QSettings().value("display/edit_rest_fade",
                                        EDIT_REST_FADE))
    except (TypeError, ValueError):
        value = EDIT_REST_FADE
    return max(0.0, min(1.0, value))


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


def _load_middle_drag_pans() -> bool:
    """Preferences ▸ middle-button drag pans, Shift + middle-drag orbits.

    Off by default: the bare wheel-drag orbits, the classic way. This is
    for the hands that learned the other convention in other modelers,
    where the wheel-drag moves the view and a modifier turns it.
    """
    from PySide6.QtCore import QSettings
    return str(QSettings().value("nav/middle_drag_pans", "0")) != "0"


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

#: Soft sun shadows (#1281), Preferences ▸ General: off (0) or a level, and
#: how fast the penumbra widens with the distance from what casts it, in
#: world width per world distance. The real sun is about 0.009; the levels
#: are broader, as a picture of soft daylight asks.
SOFT_SHADOW_SPREAD = {1: 0.012, 2: 0.03, 3: 0.06}


def _load_soft_shadows() -> int:
    """The soft shadows level (Preferences ▸ General): 0 = off, the
    default, since it costs the graphics card more while the sun is on."""
    from PySide6.QtCore import QSettings
    try:
        n = int(QSettings().value("display/soft_shadows", 0))
    except (TypeError, ValueError):
        n = 0
    return n if n in SOFT_SHADOW_SPREAD else 0


def _build_hard_shadow_image(scene, camera, width: int, height: int):
    """Rasterize the exact projected shadow polygons into a transparent image."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QImage
    from core.vista_caras import view_faces, view_rect

    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    rect = view_rect(camera)
    x0, y0, x1, y1 = rect
    if abs(x1 - x0) < 1e-12 or abs(y1 - y0) < 1e-12:
        return image
    faces = view_faces(scene, camera, as_view=True, textures=False,
                       materials=True, shadows=True)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    for face in faces:
        rings = face.shadow
        alpha = float(face.shadow_alpha)
        if getattr(face, "extra", {}).get("ground_shadow"):
            rings = face.rings
            alpha = float(face.opacity)
        if not rings or alpha <= 0.0:
            continue
        path = QPainterPath()
        path.setFillRule(Qt.OddEvenFill)
        for ring in rings:
            if len(ring) < 3:
                continue
            px = (float(ring[0][0]) - x0) * width / (x1 - x0)
            py = (y1 - float(ring[0][1])) * height / (y1 - y0)
            path.moveTo(px, py)
            for point in ring[1:]:
                px = (float(point[0]) - x0) * width / (x1 - x0)
                py = (y1 - float(point[1])) * height / (y1 - y0)
                path.lineTo(px, py)
            path.closeSubpath()
        painter.fillPath(path, QColor(0, 0, 0,
                                      max(0, min(255, round(alpha * 255)))))
    painter.end()
    return image


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
    # The dashes of an axis at once in numpy (~1 ms a frame of a zoom as a
    # Python loop): the same double operations in the same order, k*spacing,
    # then + dash, then o - d*t, rounded to float32 once as array("f") did,
    # so the bytes are the ones the loop wrote.
    import numpy as np
    t0 = np.arange(n, dtype=np.float64) * spacing
    t1 = t0 + dash
    dashes = np.empty((n, 6), dtype=np.float64)
    for name in ("x", "y", "z"):
        if _axes.is_world():
            dx, dy, dz = _AXIS_DIRS[name]
        else:
            dx, dy, dz = _axes.as_tuple(name)
        start = len(coords) // 3
        coords.extend([ox, oy, oz, ox + dx * pos_len, oy + dy * pos_len,
                       oz + dz * pos_len])
        dashes[:, 0] = ox - dx * t0
        dashes[:, 1] = oy - dy * t0
        dashes[:, 2] = oz - dz * t0
        dashes[:, 3] = ox - dx * t1
        dashes[:, 4] = oy - dy * t1
        dashes[:, 5] = oz - dz * t1
        coords.frombytes(dashes.astype(np.float32).tobytes())
        spans[name] = (start, len(coords) // 3 - start)
    return coords, spans


def _axes_vertices_key(spacing: float) -> tuple:
    """What :func:`_axes_vertices` draws from: the dash spacing and the
    drawing axes (origin and directions) — equal keys, equal vertices."""
    from core import axes as _axes
    o = _axes.ORIGIN
    dirs = (None if _axes.is_world()
            else tuple(_axes.as_tuple(n) for n in ("x", "y", "z")))
    return (max(spacing, 1e-4), o.x(), o.y(), o.z(), dirs)


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


def shown_guides(scene) -> list:
    """The guides on screen: the ones whose layer is visible (a guide is
    scaffolding on a layer like any dimension, so switching the layer off
    takes its guides off the screen and out of the snap). A function of the
    scene, so the snap of a stand-in viewport (tests) asks it too."""
    if not getattr(getattr(scene, "display_style", None), "show_guides", True):
        return []
    guides = getattr(scene, "guides", None) or ()
    visible = getattr(scene, "entity_visible", None)
    if visible is None:
        return list(guides)
    return [g for g in guides if visible(g)]


def _point_in_screen_hull(x: float, y: float, points,
                          tolerance_px: float = 1.5) -> bool:
    """Whether a screen point lies in the convex hull of ``points``.

    The projection of a 3D box is a convex polygon (usually a hexagon), not
    its axis-aligned screen rectangle. Testing that hull makes the visible
    dotted frame the honest boundary for leaving group edit: its empty corner
    triangles do not silently count as inside. The small tolerance keeps a
    click directly on a one-pixel dotted edge inside the context.
    """
    pts = sorted({(float(px), float(py)) for px, py in points
                  if math.isfinite(px) and math.isfinite(py)})
    if not pts:
        return False

    def cross(a, b, p):
        return ((b[0] - a[0]) * (p[1] - a[1])
                - (b[1] - a[1]) * (p[0] - a[0]))

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], p) <= 0.0:
                out.pop()
            out.append(p)
        return out

    if len(pts) == 1:
        return math.hypot(x - pts[0][0], y - pts[0][1]) <= tolerance_px
    lower, upper = half(pts), half(reversed(pts))
    hull = lower[:-1] + upper[:-1]
    if len(hull) == 2:
        a, b = hull
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = (0.0 if length2 <= 1e-12 else
             max(0.0, min(1.0, ((x - a[0]) * dx + (y - a[1]) * dy)
                              / length2)))
        return math.hypot(x - (a[0] + t * dx),
                          y - (a[1] + t * dy)) <= tolerance_px
    point = (float(x), float(y))
    for i, a in enumerate(hull):
        b = hull[(i + 1) % len(hull)]
        edge_len = math.hypot(b[0] - a[0], b[1] - a[1])
        if cross(a, b, point) < -tolerance_px * max(edge_len, 1.0):
            return False
    return True


#: Fewest dashes a guide circle is ever cut into: below this a circle too
#: small for the camera's dash spacing would collapse into a single dash
#: and stop reading as a dashed circle.
_MIN_CIRCLE_DASHES = 12


def _circle_guide_dashes(g, spacing: float, eye=None,
                         base_dist: float = 0.0) -> list:
    """World-space dashes along one guide circle, as a flat
    ``[x,y,z, x,y,z, …]`` float list for the GL vertex stream.

    The circle is analytic; only this display tessellation is polygonal,
    and only into the few chords that keep a dash reading round on screen.
    The dash period follows the camera's spacing like a guide line, but a
    circle too small for that spacing gets proportionally smaller dashes
    (never fewer than ``_MIN_CIRCLE_DASHES``) so it stays visibly dashed.
    """
    r = float(g.radius)
    if r <= 0.0:
        return []
    from core.axes import plane_axes
    u, v = plane_axes(g.normal)
    k = 1.0
    if eye is not None and base_dist > 0.0:
        k = max(1.0, (QVector3D(g.center) - QVector3D(eye)).length()
                / base_dist)
    sp = max(float(spacing), 1e-6) * k
    circ = 2.0 * math.pi * r
    n = min(max(int(circ / sp), _MIN_CIRCLE_DASHES), 4000)
    # Half of each angular period is drawn, half is a gap — the same 1:1
    # dash/gap ratio the guide lines use.
    dash_angle = math.pi / n
    chords = max(1, int(math.ceil(dash_angle / 0.15)))
    out: list = []
    c = QVector3D(g.center)
    for i in range(n):
        t0 = 2.0 * math.pi * i / n
        step = dash_angle / chords
        for j in range(chords):
            a0 = t0 + step * j
            a1 = a0 + step
            pa = c + u * (r * math.cos(a0)) + v * (r * math.sin(a0))
            pb = c + u * (r * math.cos(a1)) + v * (r * math.sin(a1))
            out.extend([pa.x(), pa.y(), pa.z(), pb.x(), pb.y(), pb.z()])
    return out


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
        if getattr(g, "is_circle", False):
            flat = _circle_guide_dashes(g, spacing, eye, base_dist)
            if flat:
                start = len(coords) // 3
                coords.extend(flat)
                count = len(coords) // 3 - start
                if count:
                    spans.append((start, count, id(g) in sel))
            continue
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
    # The same reading as _moller_trumbore: a small det of a small triangle
    # is measured against its own size, not against 1e-6 (#1294).
    if abs(a) < eps and (a == 0.0 or abs(a) <= eps * QVector3D.crossProduct(
            e1, e2).length() * direction.length()):
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


def _expression_fields(buffer: str) -> list:
    """The ``;`` fields of a calculation typed in the value box, each one
    starting with ``=`` (#630): ``=3/2;1+0,5`` → ``["=3/2", "=1+0,5"]``.
    A comma followed by a space separates too, as everywhere in the box."""
    fields = re.split(r";|,\s+", buffer.strip())
    return ["=" + f.strip().lstrip("=") for f in fields]


def _expression_result_text(value, plain: bool) -> str:
    """What a calculation drew, for the value box: ``3.725 m``, or the
    number alone for an angle or a factor (``plain``)."""
    from core.units import localized

    def one(v):
        if plain:
            return localized(f"{v:.6g}")
        return _fmt_len(v)

    if isinstance(value, tuple) and value and value[0] == "abs_len":
        return _fmt_len(value[1])
    if isinstance(value, tuple):
        return "; ".join(one(v) for v in value)
    return one(value)


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


def _baked_bytes(baked):
    """A preview bake (``Viewport._bake_preview_faces_py``) as plain bytes
    and tuples in draw order, to compare two of them bit for bit."""
    if baked is None:
        return None
    data, runs, by_texture = baked
    return (data.tobytes(), list(runs),
            [(k, v.tobytes()) for k, v in by_texture.items()])


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
        if hit is not None:
            moved = _translated_geometry(hit, key)
            if moved is not None:
                memo[id(f)] = moved
                return moved
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



#: "Not given" for an argument that may be None.
_NO_PAINT = object()


def _translated_geometry(hit, key):
    """``hit`` (a :func:`_face_geometry` entry) carried to the corners
    ``key`` when those are its own corners all moved by one same offset —
    what Move does to a whole selection — else None. Normal, area and the
    triangulation stay; points move by the offset. A Move of every face of
    a 15 799-face group made the open bake, the pick index and the
    highlight walk earcut for every face again (night of 18-11). Positions
    are single floats, so the corners land a few 1e-7 apart: 0.01 mm is
    far below the welding tolerance."""
    old = hit[0]
    if old is None or hit[4] is None or not key[0]:
        return None
    if (len(old[0]) != len(key[0]) or len(old[1]) != len(key[1])
            or any(len(a) != len(b) for a, b in zip(old[1], key[1]))):
        return None
    o0, k0 = old[0][0], key[0][0]
    dx, dy, dz = k0[0] - o0[0], k0[1] - o0[1], k0[2] - o0[2]
    tol = 1e-5
    for ko, kn in zip((old[0], *old[1]), (key[0], *key[1])):
        for a, b in zip(ko, kn):
            if (abs(b[0] - a[0] - dx) > tol or abs(b[1] - a[1] - dy) > tol
                    or abs(b[2] - a[2] - dz) > tol):
                return None
    tris = [tuple((p[0] + dx, p[1] + dy, p[2] + dz) for p in tri)
            for tri in hit[3]]
    c = hit[4] + QVector3D(dx, dy, dz)
    flat = tuple(x for tri in tris for corner in tri for x in corner)
    props = (hit[7][0], (c.x(), c.y(), c.z())) if hit[7] is not None else None
    return (key, hit[1], hit[2], tris, c, hit[5], flat, props)


def _finite_point(p) -> bool:
    """Whether ``p`` (a QVector3D or None) is a real point."""
    import math
    return p is not None and all(
        math.isfinite(c) for c in (p.x(), p.y(), p.z()))


def _curved_faces(mesh) -> set:
    """The faces of ``mesh`` on a curved surface: those a soft edge
    joins to another face. Only these can have a smooth corner, so
    every other face keeps its one flat colour and costs nothing."""
    out: set = set()
    for e in mesh.edges:
        if getattr(e, "soft", False) and len(e.faces) > 1:
            out.update(e.faces)
    return out


def _smooth_vcol(face, base, flat_rgb, smoother, tris, light) -> list:
    """``pos(3) + rgb(3)`` floats of ``face``'s triangles (corners as
    float tuples), each corner on a curved surface shaded against
    ``light`` by the SURFACE's normal there
    (:class:`formats.meshexport.SmoothNormals`, the one the exports
    write) instead of the face's own: the vertex colours blend across
    the triangles and a sphere reads round, not faceted (#131). Hard
    edges split the surface, so a cylinder keeps its crease against its
    caps.

    Unquantised, unlike ``Viewport._shaded_color``: the face pass is one
    draw call whatever its colours, and the 1/32 shade steps would show
    as rings across a sphere. A corner whose surface normal IS the
    face's (coplanar faces joined by a soft diagonal) keeps the flat
    colour, so a flat patch never shows a seam against its neighbour."""
    corners = smoother.corners(face)
    flat = smoother.flat(face)
    rgb_at: dict = {}
    out: list = []
    for tri in tris:
        for p in tri:
            rgb = rgb_at.get(p)
            if rgb is None:
                n = corners.get(p)
                if n is None or QVector3D.dotProduct(n, flat) > 0.99999:
                    rgb = flat_rgb
                else:
                    d = abs(QVector3D.dotProduct(n, light))
                    s = 0.62 + 0.38 * d
                    rgb = (min(1.0, base[0] * s), min(1.0, base[1] * s),
                           min(1.0, base[2] * s))
                rgb_at[p] = rgb
            out.extend((*p, *rgb))
    return out

#: The Viewport class, set by views/viewport/__init__.py once it exists: a
#: function here that names ``Viewport.X`` reads (and writes) the class itself.
Viewport = None
