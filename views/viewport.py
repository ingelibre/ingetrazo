# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""3D viewport: orbital camera, grid, XYZ axes, tools, snapping and overlays.

Uses PySide6's bundled QOpenGL* helper classes (QOpenGLShaderProgram,
QOpenGLBuffer, QOpenGLVertexArrayObject) — no external GL bindings yet.
moderngl lands when we start dealing with real meshes.

Wayland requires every frame to be drawn explicitly: ``paintGL`` always
calls ``glClear`` first to avoid showing stale GPU memory.

Navigation (SketchUp-like):
- Middle-button drag: orbit
- Shift + Middle-button drag: pan
- Wheel: zoom
- P: toggle perspective / parallel projection

Axis lock (active while drawing) — SketchUp-style:
- Right arrow: toggle lock to X (red)
- Left arrow:  toggle lock to Y (green)
- Up arrow:    toggle lock to Z (blue)
- Down arrow:  toggle parallel / perpendicular lock to the edge under cursor
- Shift held:  contextual lock — locks whatever inference is active at the
               moment (auto-axis or reference). Hold to lock, release to free.

While drawing, the rubber band also auto-aligns to axes within ~3° (soft
inference, visual cue only). Press Shift while the rubber band turns an
axis colour to lock that direction.

Tool input (when a tool is active):
- Left click: ``tool.on_click(ToolContext)``
- Mouse move: ``tool.on_hover(ToolContext)``
- Esc:        ``tool.on_cancel(viewport)``
- Other keys: tool gets first shot via ``tool.on_key(...)``
"""
from __future__ import annotations

import copy
import math
import os
import re
import time as _time_mod
from array import array
from pathlib import Path
from typing import Optional

# Perf telemetry (INGETRAZO_PERF=1): every operation slower than 50 ms and a
# once-per-second frame summary land in ~/ingetrazo-perf.log — the tool for
# "it feels slow" reports from real sessions, where synthetic benchmarks lie.
_PERF = bool(os.environ.get("INGETRAZO_PERF"))
# Kill-switch for the instanced component pass (P2): set to 1 to draw
# every instance through the consolidated VBOs like before.
_NO_INSTANCING = os.environ.get("INGETRAZO_NO_INSTANCING", "") == "1"
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

from PySide6.QtCore import QEvent, Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QMatrix4x4,
    QOpenGLFunctions,
    QPainter,
    QPen,
    QPolygonF,
    QSurfaceFormat,
    QVector3D,
    QVector4D,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from core.camera import OrbitCamera
from core.i18n import tr
from core.group import Group, copy_group, world_mesh
from core.mesh import Edge, Face
from core.history import EraseSelectionCommand, History
from core.scene import Scene
from core.snap import SnapResult, compute_snap
from core.triangulate import plane_axes
from tools.base import Tool, ToolContext


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
    snappable (SketchUp)."""
    if not getattr(scene, "show_section_cuts", True):
        return None
    active = getattr(scene, "active_section", None)
    return active() if callable(active) else None


class _SnapEdge:
    """Lightweight edge stand-in fed to the snap engine for group geometry —
    ``compute_snap`` only reads ``.a``/``.b`` (world endpoints)."""

    __slots__ = ("a", "b")

    def __init__(self, a, b) -> None:
        self.a = a
        self.b = b


# OpenGL constants — kept as literals so we don't depend on PyOpenGL.
GL_FLOAT = 0x1406
GL_LINES = 0x0001
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
GL_FRONT = 0x0404
GL_BACK = 0x0405
GL_LEQUAL = 0x0203
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


from core.paths import app_root

SHADER_DIR = app_root() / "resources" / "shaders"


# ---- Geometry helpers ------------------------------------------------------

#: Beyond this many loose edges the snap engine gets a near-cursor subset
#: instead of the whole mesh: compute_snap walks its edge list in Python
#: ~a dozen times per hover, and an exploded medium import (9k faces =
#: ~20k edges) froze every mouse move (user report, piscina.igz).
_LOOSE_SNAP_CAP = 3000


def _ray_aabb(o, d, lo, hi) -> bool:
    """Slab test: does the forward ray (t >= 0) touch the AABB? Plain
    floats — the pick prefilter tests ~tens of chunk boxes per ray."""
    tmin = 0.0
    tmax = float("inf")
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


def _cache_ver(vp):
    """The scene version the per-version caches key on — frozen during a
    groups-only transform preview (see Viewport.begin_groups_preview).
    Module-level so the stub viewports in tests hit it too."""
    frozen = getattr(vp, "_frozen_cache_version", None)
    return frozen if frozen is not None else vp.scene.version


#: How the rest of the model reads while a group is open for editing.
#: ``normal`` draws it as always, ``fade`` washes it out behind the group
#: being edited (SketchUp's default), ``hide`` leaves it out of the frame.
EDIT_REST_MODES = ("normal", "fade", "hide")
#: How far the context is mixed TOWARD the background (0 = untouched, 1 =
#: gone). It is a wash, not an opacity: the context keeps writing depth, so it
#: still occludes itself and never turns the model into glass. Enough to place
#: the group in its surroundings, faint enough that what you are editing reads
#: as the subject.
EDIT_REST_FADE = 0.75


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


def _load_invert_wheel() -> bool:
    from PySide6.QtCore import QSettings
    return str(QSettings().value("nav/invert_wheel", "0")) != "0"


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
    """SketchUp-style axes: a long solid line in the positive direction and an
    **evenly-spaced** dashed line in the negative (constant world ``spacing``, so
    the dashes converge toward the horizon by perspective — like SketchUp, not
    spreading apart). ``spacing`` scales with the camera distance so the on-screen
    density stays stable across zoom. Returns ``(coords, spans)`` where ``spans``
    maps ``'x'|'y'|'z'`` → ``(first_vertex, vertex_count)`` for a per-axis draw."""
    coords = array("f")
    spans: dict[str, tuple[int, int]] = {}
    spacing = max(spacing, 1e-4)
    # Short dots, not half-duty dashes: GL lines are stuck at 1px (Mesa
    # clamps glLineWidth), so the dash LENGTH is what sets the perceived
    # weight — SketchUp's negative axes read as fine dotted lines.
    dash = spacing * 0.18
    n = 520                          # dashes → reach = spacing*n past the model
    for name, (dx, dy, dz) in _AXIS_DIRS.items():
        start = len(coords) // 3
        coords.extend([0.0, 0.0, 0.0, dx * pos_len, dy * pos_len, dz * pos_len])
        for k in range(n):
            t0 = k * spacing
            t1 = t0 + dash
            coords.extend([-dx * t0, -dy * t0, -dz * t0,
                           -dx * t1, -dy * t1, -dz * t1])
        spans[name] = (start, len(coords) // 3 - start)
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

_IMPERIAL_UNITS = {"in": 0.0254, '"': 0.0254, "ft": 0.3048, "'": 0.3048}
_METRIC_UNITS = {"": 1.0, "m": 1.0, "cm": 0.01, "mm": 0.001}


def _parse_number(tok: str):
    """``2``, ``2.5``, ``.5``, ``3/4`` (a fraction), ``1-1/2`` (a mixed
    number, the hyphen form) → float, else None."""
    m = re.fullmatch(r"(?:(\d+)-)?(\d+\.?\d*|\.\d+)(?:/(\d+\.?\d*))?", tok)
    if m is None:
        return None
    v = float(m.group(2))
    if m.group(3):
        d = float(m.group(3))
        if d == 0:
            return None
        v /= d
    elif m.group(1):
        return None                      # "1-2" without a fraction: not ours
    if m.group(1):
        v += float(m.group(1))
    return v


def _merge_mixed_numbers(fields: list) -> list:
    """SketchUp's ``1 1/2"``: a whole number followed by a fraction field is
    ONE mixed number, not two fields — joined with the hyphen form."""
    out = []
    i = 0
    while i < len(fields):
        f = fields[i]
        nxt = fields[i + 1] if i + 1 < len(fields) else None
        if (nxt is not None
                and re.fullmatch(r"-?\d+(?:'\d*)?", f)
                and re.fullmatch(r"\d+/\d+(?:mm|cm|m|in|ft|\"|')?", nxt.lower())):
            # 1 1/2" → 1-1/2"; 1'6 1/2" → 1'6-1/2"; 1' 1/2" → 1'1/2"
            joint = "" if f.endswith("'") else "-"
            out.append(f"{f}{joint}{nxt}")
            i += 2
            continue
        out.append(f)
        i += 1
    return out


def _parse_length_field(field: str):
    """One typed length in metres: metric or imperial, SketchUp's forms.

    ``2`` (metres) · ``30cm`` · ``1500mm`` · ``2"`` / ``2in`` · ``1'`` /
    ``1ft`` · ``1'6"`` · ``3/4"`` · ``1'3/4"``. A leading minus is kept.
    Returns None when the field is not a length."""
    f = field.strip().lower()
    sign = 1.0
    if f.startswith("-"):
        sign, f = -1.0, f[1:]
    if not f:
        return None
    # feet-and-inches: <feet>'<inches>" (inches optional, may be a fraction)
    m = re.fullmatch(r"([^'\"]+)'([^'\"]*)\"?", f)
    if m is not None and m.group(2):
        # 1'6 1/2" arrives from the buffer merge as 1'6-1/2"
        feet = _parse_number(m.group(1))
        inches = _parse_number(m.group(2))
        if feet is None or inches is None:
            return None
        return sign * (feet * 0.3048 + inches * 0.0254)
    m = re.fullmatch(r"(.+?)(mm|cm|m|in|ft|\"|')?", f)
    if m is None:
        return None
    num = _parse_number(m.group(1))
    if num is None:
        return None
    unit = m.group(2) or ""
    scale = _METRIC_UNITS.get(unit)
    if scale is None:
        scale = _IMPERIAL_UNITS.get(unit)
    if scale is None:
        return None
    return sign * num * scale


class Viewport(QOpenGLWidget):
    """OpenGL viewport with orbital camera, grid, XYZ axes, tools and snapping."""

    valueBufferChanged = Signal(str)
    sceneVersionChanged = Signal(int)
    # Live measurement for the VCB box (e.g. "5.00 m", "3.00 × 2.00 m").
    measurementChanged = Signal(str)
    # A base-map tile finished downloading (Track G) — lets the 3D terrain
    # rebuild its mosaic as imagery arrives.
    tilesChanged = Signal()
    # UTM coordinate under the cursor, for the status bar readout (Track G).
    coordinateChanged = Signal(str)

    # Soft warm white painted on faces with no material colour — like the matte
    # cardstock of an architecture model (SketchUp's near-white default).
    DEFAULT_FACE_COLOR = (0.96, 0.95, 0.925)
    # Fixed world light (from above, slightly front-right) for the subtle diffuse
    # face shading. World-fixed so shading is stable while orbiting, like SketchUp.
    _LIGHT = QVector3D(0.35, 0.25, 1.0).normalized()

    # Tooltip text shown next to the snap marker, SketchUp-style. English source
    # strings; translated at draw time via ``tr`` (see i18n/es.json).
    _SNAP_LABELS = {
        "endpoint": "Endpoint",
        "midpoint": "Midpoint",
        "on_edge": "On edge",
        "on_face": "On face",
        "origin": "Origin",
        "extension": "Extension",
        "intersection": "Intersection",
        "from_point": "From point",
        "through_point": "Through point",
        "perp_face": "Perpendicular to face",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Hidden-line removal needs a real depth buffer. setDefaultFormat() in
        # main.py is best-effort; many platforms ignore it for QOpenGLWidget
        # and hand us a 0-bit depth context. Forcing the format here is the
        # only reliable way.
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        # NO samples on the widget surface: the scene renders into our own
        # multisampled FBO (_ensure_scene_fbo) and the blit resolves it. A
        # multisampled widget FBO adds a second resolve that interleaves stale
        # frames on Wayland (ghost frames during fast zoom) and cannot smooth
        # the already-resolved pixels we blit into it.
        self.setFormat(fmt)
        self.setMinimumSize(640, 480)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

        self.camera = OrbitCamera()
        self.scene = Scene()
        self.history = History(self.scene)
        self.active_tool: Optional[Tool] = None
        self.axis_lock: Optional[str] = None  # None | "x" | "y" | "z"
        self.last_snap: Optional[SnapResult] = None
        # Copy/paste clipboard: copied geometry (faces + edges as positions,
        # groups as snapshot copies) plus a reference corner so Paste can
        # place it under the cursor.
        self.clipboard: Optional[dict] = None

        # Reference-edge state (Down arrow → parallel / perpendicular).
        self.reference_edge = None
        self.reference_mode: Optional[str] = None  # None | "parallel" | "perpendicular"
        # Linear-inference toggle (SketchUp's Alt): "all" | "off" | "parallel_perp".
        self.linear_inference_mode = "all"
        # Sticky inference lock (Shift): (direction, color) captured from the
        # active inference, held until Shift is released.
        self._shift_lock: Optional[tuple] = None
        self._hover_edge = None  # last edge under cursor (candidate for capture)
        # Edge/corner/face hovered while drawing, held as soft references
        # (SketchUp "from point" / "through point" / "perpendicular to face"
        # acquisition). Cleared when no segment is in progress.
        self._acquired_edge = None
        self._acquired_point = None
        self._acquired_face_normal = None
        self._last_mouse_pos: Optional[QPointF] = None

        # Pixel radius for point snaps (endpoint, origin, close). 12 px felt
        # mushy when the cursor was running along an existing edge: as long
        # as the cursor was within 12 px of either end of a short edge,
        # endpoint snap kept firing. SketchUp is tighter — the green dot
        # only lights up right at the vertex.
        self.snap_threshold_px = 9.0
        # On-edge snap gets a bigger radius than point snaps: an edge is a large
        # linear target, so resting a corner on it (e.g. a door on the floor
        # line) should be forgiving and not slip just outside the face.
        self.edge_snap_threshold_px = 14.0
        self.pick_threshold_px = 8.0
        self.inference_angle_deg = 3.0

        self._gl: Optional[QOpenGLFunctions] = None
        self._program: Optional[QOpenGLShaderProgram] = None
        self._loc_mvp = -1
        self._loc_color = -1
        self._loc_pos = -1

        self._axes_vao = None
        self._axes_vbo = None

        self._edges_vao = None
        self._edges_vbo = None
        self._edges_count = 0
        self._selected_vao = None
        self._selected_vbo = None
        self._selected_count = 0
        self._sel_faces_vao = None
        self._sel_faces_vbo = None
        self._sel_faces_count = 0
        self._faces_vao = None
        self._faces_vbo = None
        self._faces_count = 0
        # Solid-colour faces share ONE interleaved pos+rgb VBO drawn in a
        # single call (the shaded material colour rides per vertex).
        # Textured faces (pos+uv VBO) grouped by image path: [(path, start, count)].
        self._tex_faces_count = 0
        self._tex_opaque_count = 0
        self._tex_runs: list = []
        self._back_vcol_run: tuple = (0, 0)
        self._back_tex_runs: list = []
        self._back_tcol_runs: list = []
        self._back_ttex_runs: list = []
        self._fvcol_run: tuple = (0, 0)
        self._tcol_runs: list = []
        self._ttex_runs: list = []
        self._tex_cache: dict = {}
        self._edges_version = -1
        #: Per consolidated VBO: the byte parts last uploaded and the buffer's
        #: allocated capacity, so a resync re-sends only what changed.
        self._vbo_parts: dict = {}

        # How the rest of the model reads while you are INSIDE a group
        # (SketchUp's Model Info ▸ Components). "fade" keeps the context
        # visible but out of the way, "hide" drops it from the frame
        # entirely — on a heavy import that is also the fastest, since a
        # hidden group never reaches the VBOs. See `edit_rest_mode`.
        self._edit_rest_mode = _load_edit_rest_mode()
        self._invert_wheel = _load_invert_wheel()
        self._msaa = _load_msaa()

        # Hover highlight (Select tool). Not version-tracked — it changes with
        # the cursor, not with scene mutations — so it's uploaded per paint.
        self._hover_entity = None  # None | Edge | Face under the cursor
        self._last_double = None   # (timestamp, pos) of the last double-click
        self._hover_faces_vao = None
        self._hover_faces_vbo = None
        self._hover_edges_vao = None
        self._hover_edges_vbo = None

        self._rubber_vao = None
        self._rubber_vbo = None

        # Shaded solid preview (Push/Pull): the forming box's faces, uploaded
        # per paint while the tool drags.
        self._preview_faces_vao = None
        self._preview_faces_vbo = None
        self._preview_tex_vao = None
        self._preview_tex_vbo = None
        self._section_vao = None
        self._section_vbo = None

        # Faces hidden from the normal pass while a tool previews — Push/Pull
        # hides the flat inner face it's pushing in (a window/door) so the recess
        # forming behind it is visible instead of covered. Keyed by identity.
        self._suppressed_faces: set = set()

        # Offscreen FBO with depth attachment. QOpenGLWidget's default target
        # on some Mesa/Wayland stacks has no depth buffer, which silently
        # breaks hidden-line removal. Rendering into our own FBO and blitting
        # color out guarantees a real depth buffer is present.
        self._scene_fbo: Optional[QOpenGLFramebufferObject] = None
        # When set, paintGL renders at this framebuffer size into the scene
        # FBO and stops there (no blit, no widget overlay) — the hi-res image
        # export path (render_image) reads the FBO back instead.
        self._export_size: Optional[tuple[int, int]] = None
        # Sheet-composer technical style: None (shaded), "tecnico" (white
        # faces + dark edges on white, no axes/sky) or "lineas" (edges only).
        # Set around a composer render; never persists across frames.
        self.plano_style: Optional[str] = None
        # Full Style override for a composer frame ("style:<name>"): wins
        # over the scene's display style for that render; axes are skipped
        # (a frame is a document, not the workspace). Never persists.
        self.style_override = None
        self._fbo_size = (0, 0)

        # Camera navigation state (middle button)
        self._last_pos = None
        self._pan_mode = False
        # SketchUp-style navigation mode for trackpad users with no middle
        # mouse button: when set ("orbit" / "pan"), a left-drag drives the
        # camera instead of the active tool. None means a drawing tool is in
        # charge of the left button.
        self.nav_mode: Optional[str] = None

        # Preview line for the "always on top" tools, stashed during GL render
        # and drawn in the QPainter overlay (thick, reliable pen).
        self._overlay_rubber: Optional[tuple] = None

        # Rubber-band box selection (left-drag with a box_select tool).
        self._box_active = False
        self._box_start: Optional[QPointF] = None
        self._box_cur: Optional[QPointF] = None

        # Zoom Window rubber-band (nav_mode == "zoom_window").
        self._zoom_box_active = False
        self._zoom_box_start: Optional[QPointF] = None
        self._zoom_box_cur: Optional[QPointF] = None

        # Numeric value buffer (VCB-style typed length).
        self._value_buffer = ""

        # Base-map tiles (Track G, G1). The fetcher is created lazily (needs a
        # running app); GL textures are cached per tile, keyed by (source, x,y,z).
        self._tile_fetcher = None
        self._tile_textures: dict = {}
        self._last_coordinate = ""      # so the label only repaints on change
        self._tile_quad_vao = None
        self._tile_quad_vbo = None
        # Cached base-map tile geometry (built once per capture, not per frame).
        self._tile_geom = None
        # Per-frame GL-texture-creation budget (spreads big captures over frames).
        self._tex_budget = 0
        self._tex_deferred = False

        # Georef path node being hovered ``(path, index)`` — for the drag handle
        # highlight (Track G, GeoPath node editing).
        self._hover_geo_node = None
        # World point on the profiled route to mark (profile→plan link), or None.
        self._route_marker = None

        # 3D draped terrain (Track G, G2 full).
        self._terrain_vao = None
        self._terrain_vbo = None
        self._terrain_count = 0
        self._terrain_texture = None
        # Photogrammetric survey (Track G, G6). One VBO for the whole mesh and
        # one texture per ODM atlas; ``_photo_ranges`` says which slice of the
        # VBO each atlas covers, so the draw is ~20 calls, not one per triangle.
        self._photo_vao = None
        self._photo_vbo = None
        self._photo_count = 0
        self._photo_textures = []
        self._photo_ranges = []

    # ---- GL lifecycle -------------------------------------------------------
    def initializeGL(self) -> None:
        self._gl = QOpenGLFunctions(self.context())
        self._gl.initializeOpenGLFunctions()
        # GL cleanup has exactly one legal moment: the context's own farewell.
        # (initializeGL re-runs if the context is ever recreated; each context
        # gets its own connection, which is precisely what we want.)
        self.context().aboutToBeDestroyed.connect(self.release_gl_textures)
        self._gl.glClearColor(0.93, 0.94, 0.96, 1.0)
        self._gl.glClearDepthf(1.0)
        self._gl.glEnable(GL_DEPTH_TEST)
        # LEQUAL (instead of the default LESS) lets a fragment win when its
        # depth equals the existing one — important for edges drawn on top of
        # coincident faces, which can rasterize to bit-identical depths.
        self._gl.glDepthFunc(GL_LEQUAL)
        self._gl.glEnable(GL_BLEND)
        self._gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        self._program = self._compile_program()
        self._loc_mvp = self._program.uniformLocation("u_mvp")
        self._loc_color = self._program.uniformLocation("u_color")
        self._loc_back_color = self._program.uniformLocation("u_back_color")
        self._loc_fade = self._program.uniformLocation("u_fade")
        self._loc_fade_color = self._program.uniformLocation("u_fade_color")
        self._loc_pos = self._program.attributeLocation("a_pos")
        self._loc_uv = self._program.attributeLocation("a_uv")
        self._loc_use_tex = self._program.uniformLocation("u_use_texture")
        self._loc_tex = self._program.uniformLocation("u_tex")
        self._loc_vcolor = self._program.attributeLocation("a_color")
        self._loc_use_vcolor = self._program.uniformLocation("u_use_vcolor")
        self._loc_opacity = self._program.uniformLocation("u_opacity")
        self._loc_hard_cutout = self._program.uniformLocation("u_hard_cutout")
        self._loc_shade = self._program.uniformLocation("u_shade")
        # Per-instance model matrix columns (P2 instanced components).
        self._loc_inst = [self._program.attributeLocation(f"a_inst{i}")
                          for i in range(4)]
        self._loc_clip_plane = self._program.uniformLocation("u_clip_plane")
        self._loc_clip_enable = self._program.uniformLocation("u_clip_enable")
        # Sun shadows (core/sun.py): sampling uniforms on the main program,
        # plus the tiny depth-only program the shadow map renders with.
        self._loc_shadow_enable = self._program.uniformLocation(
            "u_shadow_enable")
        self._loc_shadow_map = self._program.uniformLocation("u_shadow_map")
        self._loc_light_vp = self._program.uniformLocation("u_light_vp")
        self._loc_shadow_dark = self._program.uniformLocation("u_shadow_dark")
        self._loc_shadow_bias = self._program.uniformLocation("u_shadow_bias")
        self._loc_sun_dir = self._program.uniformLocation("u_sun_dir")
        self._loc_shadow_overlay = self._program.uniformLocation(
            "u_shadow_overlay")
        self._depth_program = self._compile_depth_program()
        self._loc_d_mvp = self._depth_program.uniformLocation("u_mvp")
        self._loc_d_clip_plane = self._depth_program.uniformLocation(
            "u_clip_plane")
        self._loc_d_clip_enable = self._depth_program.uniformLocation(
            "u_clip_enable")
        self._loc_d_use_tex = self._depth_program.uniformLocation(
            "u_use_texture")
        self._loc_d_tex = self._depth_program.uniformLocation("u_tex")
        self._shadow_fbo = None
        self._shadow_key = None
        self._shadow_vp = None

        # Axes rebuilt per frame (dash spacing scales with zoom), so dynamic.
        self._axes_vao, self._axes_vbo = self._create_dynamic()
        self._axes_spans: dict = {}

        self._sky_vao, self._sky_vbo = self._create_dynamic()
        self._sky_grad_vao, self._sky_grad_vbo = self._create_dynamic_color()
        self._ground_vao, self._ground_vbo = self._create_dynamic()
        self._shadow_bb_vao, self._shadow_bb_vbo = self._create_dynamic_uv()
        self._edges_vao, self._edges_vbo = self._create_dynamic()
        self._selected_vao, self._selected_vbo = self._create_dynamic()
        self._sel_faces_vao, self._sel_faces_vbo = self._create_dynamic()
        self._faces_vao, self._faces_vbo = self._create_dynamic_vcol()
        self._tex_faces_vao, self._tex_faces_vbo = self._create_dynamic_uv()
        self._billboard_vao, self._billboard_vbo = self._create_dynamic_uv()
        self._bb_sel_vao, self._bb_sel_vbo = self._create_dynamic()
        self._hover_faces_vao, self._hover_faces_vbo = self._create_dynamic()
        self._hover_edges_vao, self._hover_edges_vbo = self._create_dynamic()
        self._silhouette_vao, self._silhouette_vbo = self._create_dynamic()
        self._rubber_vao, self._rubber_vbo = self._create_dynamic()
        self._preview_faces_vao, self._preview_faces_vbo = self._create_dynamic()
        self._preview_tex_vao, self._preview_tex_vbo = self._create_dynamic_uv()
        self._section_vao, self._section_vbo = self._create_dynamic()
        self._tile_quad_vao, self._tile_quad_vbo = self._create_dynamic_uv()
        self._terrain_vao, self._terrain_vbo = self._create_dynamic_uv()
        self._photo_vao, self._photo_vbo = self._create_dynamic_uv()

    def resizeGL(self, w: int, h: int) -> None:
        # Qt passes framebuffer-pixel sizes here (already scaled by DPR), so
        # this is the authoritative source for FBO and viewport dimensions.
        if self._gl is None:
            return
        self._gl.glViewport(0, 0, w, h)
        self.camera.set_aspect(w, h)
        self._ensure_scene_fbo(w, h)

    def _fb_size(self) -> tuple[int, int]:
        """Framebuffer pixel size (logical size × device pixel ratio)."""
        dpr = self.devicePixelRatioF()
        return max(int(round(self.width() * dpr)), 1), max(int(round(self.height() * dpr)), 1)

    def _ensure_scene_fbo(self, w: int, h: int) -> None:
        """Create or resize the offscreen FBO used for depth-tested rendering."""
        size = (max(w, 1), max(h, 1))
        if self._scene_fbo is not None and self._fbo_size == size:
            return
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        # Real MSAA happens HERE, where the scene actually renders; the blit
        # to the widget's single-sample FBO is the resolve (MSAA read → plain
        # draw is the legal direction). The widget surface itself stays
        # single-sample — see __init__. Sample count from Preferences
        # (Graphics in SketchUp); changing it just voids _fbo_size.
        fmt.setSamples(getattr(self, "_msaa", 4))
        self._scene_fbo = QOpenGLFramebufferObject(size[0], size[1], fmt)
        if fmt.samples() and self._scene_fbo.format().samples() == 0:
            # Driver refused multisampling — retry single-sample but KEEP the
            # depth/stencil attachment (the Wayland depth workaround).
            fmt.setSamples(0)
            self._scene_fbo = QOpenGLFramebufferObject(size[0], size[1], fmt)
        self._fbo_size = size

    def render_image(self, width_px: int, height_px: Optional[int] = None,
                     overlays: bool = True,
                     annotations_only: bool = False) -> Optional["QImage"]:
        """Render the current view at ``width_px`` wide (height follows the
        viewport's aspect) and return it as a ``QImage`` — the hi-res 2D
        export. Reuses the exact ``paintGL`` pipeline against a temporary
        FBO, then paints the presentation overlays (dimensions, geo paths,
        survey points, guides) on top with a scaled QPainter; interactive
        artifacts (snap marker, hover, rubber band) are naturally absent.

        The sheet composer passes an explicit ``height_px`` (its frames have
        their own aspect — the caller is responsible for pointing the camera
        and setting its aspect to match) and ``overlays=False``: the overlay
        painters are calibrated to the live widget's aspect and would land
        misplaced under a composer camera."""
        if self._gl is None or self._program is None:
            return None
        lw = max(self.width(), 1)
        lh = max(self.height(), 1)
        width_px = max(int(width_px), 64)
        if height_px is None:
            height_px = max(int(round(width_px * lh / lw)), 64)
        else:
            height_px = max(int(height_px), 64)

        prev_fbo = self._scene_fbo
        prev_size = self._fbo_size
        self.makeCurrent()
        try:
            self._export_size = (width_px, height_px)
            try:
                self.paintGL()
                image = self._scene_fbo.toImage()   # resolves MSAA itself
            finally:
                self._export_size = None
                # Drop the big export FBO (destroyed here, context current)
                # and put the on-screen one back.
                self._scene_fbo = prev_fbo
                self._fbo_size = prev_size
        finally:
            self.doneCurrent()

        if overlays:
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            # Overlay drawing works in logical widget pixels
            # (_world_to_pixel); the scale maps it onto the hi-res image,
            # thickening lines and text proportionally.
            painter.scale(width_px / lw, height_px / lh)
            if not annotations_only:
                # A sheet frame wants the model's annotations (LayOut shows
                # SketchUp's dimensions and texts) but never the guides or
                # the section-plane frames.
                self._draw_guides(painter)
                self._draw_section_planes(painter)
                self._draw_geo_surfaces(painter)
                self._draw_geo_paths(painter)
                self._draw_geo_points(painter)
            self._draw_dimensions(painter)
            self._draw_text_labels(painter)
            painter.end()
        self.update()                               # repaint the widget
        return image

    def paintGL(self) -> None:
        if self._gl is None or self._program is None:
            return
        _pt0 = _time_mod.perf_counter() if _PERF else 0.0

        # Render the 3D scene into our own FBO (which has a real depth buffer)
        # then blit the colour to the widget's default framebuffer. Sizes are
        # in framebuffer pixels — using logical (self.width/height) here would
        # blit into a fraction of the widget on HiDPI displays and shift the
        # rendered scene away from the mouse cursor.
        w, h = self._export_size or self._fb_size()
        self._ensure_scene_fbo(w, h)
        default_fbo = self.defaultFramebufferObject()
        self._scene_fbo.bind()
        self._gl.glViewport(0, 0, w, h)

        # Re-establish GL state every frame. QPainter (used for the 2D overlay)
        # leaves GL state in an undefined shape — in particular it tends to
        # disable depth test — so we can't trust state to persist across
        # paintGL calls.
        self._gl.glEnable(GL_DEPTH_TEST)
        self._gl.glDepthFunc(GL_LEQUAL)
        self._gl.glDepthMask(GL_TRUE)
        self._gl.glEnable(GL_BLEND)
        self._gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self._gl.glDisable(GL_CULL_FACE)

        # Effective display style (SketchUp Styles): the composer's
        # plano_style override maps onto the same face modes; otherwise the
        # scene's active style drives faces, edges and background.
        style = self._effective_style()
        mode = style.face_mode
        self._frame_style = style

        # Active section cut (SketchUp): ONE world-space plane; the kept
        # side is where dot(n, p - origin) <= 0. Applies to model geometry
        # only — sky, axes, terrain, previews and overlays stay uncut.
        self._clip_vec = None
        sp = (self.scene.active_section()
              if getattr(self.scene, "show_section_cuts", True) else None)
        if sp is not None:
            n, o = sp.normal, sp.point
            self._clip_vec = QVector4D(
                -n.x(), -n.y(), -n.z(), QVector3D.dotProduct(n, o))

        self._gl.glClearDepthf(1.0)
        bg = style.background
        self._gl.glClearColor(bg[0], bg[1], bg[2], 1.0)
        self._gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        # Frustum planes for chunk culling — also consumed by the
        # silhouette pass (skip whole chunks that are off screen).
        self._frame_planes = self._frustum_planes(mvp)
        # P0 frame telemetry: coarse per-section CPU times, logged with the
        # cull counters when the frame is slow (INGETRAZO_PERF=1).
        _fseg: dict = {}
        _fprev = _pt0

        def _fmark(name: str) -> None:
            nonlocal _fprev
            if _PERF:
                now = _time_mod.perf_counter()
                _fseg[name] = _fseg.get(name, 0.0) + (now - _fprev) * 1000.0
                _fprev = now

        self._program.bind()
        self._program.setUniformValue(self._loc_mvp, mvp)
        # Instanced-matrix attributes default to IDENTITY for every
        # non-instanced draw (the GL default (0,0,0,1) collapses geometry,
        # and QPainter may clobber generic attribute state — reset per frame).
        li = getattr(self, "_loc_inst", None)
        if li and li[0] >= 0:
            self._gl.glVertexAttrib4f(li[0], 1.0, 0.0, 0.0, 0.0)
            self._gl.glVertexAttrib4f(li[1], 0.0, 1.0, 0.0, 0.0)
            self._gl.glVertexAttrib4f(li[2], 0.0, 0.0, 1.0, 0.0)
            self._gl.glVertexAttrib4f(li[3], 0.0, 0.0, 0.0, 1.0)
        # Solid-colour by default; the textured-face pass flips this on.
        self._program.setUniformValue(self._loc_use_tex, 0)
        self._program.setUniformValue(self._loc_tex, 0)  # sampler → unit 0
        self._program.setUniformValue(self._loc_use_vcolor, 0)
        self._program.setUniformValue1f(self._loc_opacity, 1.0)
        self._program.setUniformValue1f(self._loc_shade, 1.0)
        self._program.setUniformValue(self._loc_hard_cutout, 0)
        self._program.setUniformValue1f(self._loc_fade, 0.0)

        # Sky / ground backdrop with a horizon anchored to the camera pitch —
        # premium SketchUp feel. Fixed on zoom (it's the point at infinity),
        # moves only on orbit. Skipped over the base map / terrain (which supply
        # their own ground).
        if (self.plano_style is None and style.sky
                and not self._base_map_showing()
                and not self._terrain_showing()
                and not self._photo_showing()):
            self._draw_sky(mvp)
            self._program.setUniformValue(self._loc_mvp, mvp)

        # Base-map tiles (Track G) — the ground image, drawn before the grid so
        # the grid lines read on top of the imagery. Depth-write OFF: it's a
        # backdrop, geometry always draws over it.
        self._render_tiles()

        # 3D draped terrain (Track G, G2 full) — real depth-tested relief that
        # replaces the flat map when enabled.
        self._render_terrain()

        # Photogrammetric survey (Track G, G6) — the user's own flight, drawn
        # after the DEM terrain so the real capture wins where both exist.
        self._render_photo_mesh()

        # Imported reference images (a scanned plan, a facade photo). Last of
        # the reference layers and before any model geometry: they are what
        # the user draws ON TOP of.
        self._draw_image_planes()
        _fmark("ground")

        # No grid — the infinite axes are the spatial reference (SketchUp).

        # Persistent edges + faces
        self._sync_edges()
        _fmark("sync")

        # Sun shadow map — AFTER the sync, so the consolidated VBOs hold
        # THIS frame's geometry; cached across frames by geometry+sun (it is
        # camera-independent: orbit and zoom reuse it). The pass borrows the
        # FBO/program bindings; this block restores them and binds the map
        # on texture unit 1 for the geometry passes to sample.
        self._frame_shadow = (self._ensure_shadow_map()
                              if mode in ("textures", "shaded",
                                          "hidden_line", "monochrome")
                              else None)
        if self._frame_shadow is not None:
            self._scene_fbo.bind()
            self._gl.glViewport(0, 0, w, h)
            self._program.bind()
            self._gl.glActiveTexture(GL_TEXTURE1)
            self._gl.glBindTexture(GL_TEXTURE_2D,
                                   self._frame_shadow.texture())
            self._gl.glActiveTexture(GL_TEXTURE0)
            self._program.setUniformValue(self._loc_shadow_map, 1)
            self._program.setUniformValue(self._loc_light_vp,
                                          self._shadow_vp)
            sh = getattr(self.scene, "shadows", None)
            self._program.setUniformValue1f(
                self._loc_shadow_dark,
                float(getattr(sh, "darkness", 0.55)))
            # Small constant margin on the receiver; the heavy lifting is
            # the slope-scaled bias the CASTER writes (depth.frag) — a
            # constant big enough to silence grazing faces peeled every
            # shadow off its base instead.
            self._program.setUniformValue1f(self._loc_shadow_bias, 0.0006)
            sun = getattr(self, "_frame_sun", None) or (0.0, 0.0, 1.0)
            self._program.setUniformValue(
                self._loc_sun_dir, QVector3D(sun[0], sun[1], sun[2]))
        self._program.setUniformValue(self._loc_shadow_enable, 0)
        self._program.setUniformValue(self._loc_shadow_overlay, 0)
        _fmark("shadowmap")

        # Frustum culling (P1): the consolidated VBOs carry per-chunk draw
        # spans; only spans whose chunk AABB touches the frustum are
        # submitted. Conservative — a missing bbox always draws.
        planes = self._frame_planes
        # Inside a group with the context faded, the buffers hold the
        # surroundings first and the edited group last; the split keeps the
        # two apart so each is drawn with its own opacity.
        # Both splits or neither: a frame that faded the context's edges but
        # not its faces would read as a glitch rather than a mode.
        fading = (self.scene.edit_group is not None
                  and self._edit_rest_mode == "fade"
                  and getattr(self, "_edit_split_e", None) is not None
                  and getattr(self, "_edit_split_f", None) is not None)
        split_f = self._edit_split_f if fading else None
        split_e = self._edit_split_e if fading else None
        if fading:
            bg = style.background
            self._program.setUniformValue(
                self._loc_fade_color, QVector3D(bg[0], bg[1], bg[2]))
        spans = getattr(self, "_face_spans", None)
        if spans:
            face_spans, culled_fv = self._visible_spans(spans, planes, split_f)
        else:
            face_spans, culled_fv = [(0, self._faces_count)], 0
        espans = getattr(self, "_edge_spans", None)
        if espans:
            edge_spans, culled_ev = self._visible_spans(espans, planes, split_e)
        else:
            edge_spans, culled_ev = [(0, self._edges_count)], 0
        self._frame_edge_spans = edge_spans
        self._cull_stats = (culled_fv // 3, self._faces_count // 3,
                            culled_ev // 2)

        # Faces — drawn before edges, with polygon offset so coincident
        # boundary edges sit cleanly on top instead of z-fighting.
        self._set_section_clip(True)
        if getattr(self, "_frame_shadow", None) is not None:
            self._draw_shadow_ground(style)
            self._program.setUniformValue(self._loc_shadow_enable, 1)
        if self._faces_count > 0 and mode != "wireframe":
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            if mode == "hidden_line":
                # Plan style: every face flat in the style's front colour, no
                # rebatch needed — per-vertex colours simply not consulted.
                self._program.setUniformValue(self._loc_use_vcolor, 0)
                fr = style.front_color
                self._set_color(fr[0], fr[1], fr[2], 1.0)
                self._program.setUniformValue(
                    self._loc_back_color, QVector4D(fr[0], fr[1], fr[2], 1.0))
            elif mode == "monochrome":
                # Flat default front colour + the back tint — the classic
                # reversed-face checker (SketchUp Monochrome).
                self._program.setUniformValue(self._loc_use_vcolor, 0)
                fr = style.front_color
                self._set_color(fr[0], fr[1], fr[2], 1.0)
                self._set_back_face_color()
            else:
                # Every colour run in ONE draw call: the shaded material
                # colour rides per vertex (a_color). An imported model with
                # hundreds of colour×shade runs paid ~2000 uniform/draw
                # calls per frame.
                self._program.setUniformValue(self._loc_use_vcolor, 1)
                self._set_back_face_color()
            if mode == "xray":
                # X-ray: translucent faces that do not occlude — edges stay
                # fully visible because nothing writes depth.
                self._program.setUniformValue1f(self._loc_opacity, 0.55)
                self._gl.glDepthMask(GL_FALSE)
            self._faces_vao.bind()
            if split_f is None:
                for _vs, _vc in face_spans:
                    self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            else:
                # Context first, washed toward the background but fully
                # opaque and still writing depth (SketchUp's faded rest of
                # model reads as haze, not as glass); then the group itself
                # at full strength.
                self._program.setUniformValue1f(self._loc_fade,
                                                EDIT_REST_FADE)
                for _vs, _vc in face_spans:
                    if _vs < split_f:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
                self._program.setUniformValue1f(self._loc_fade, 0.0)
                for _vs, _vc in face_spans:
                    if _vs >= split_f:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            fstart, fcount = self._fvcol_run
            if fcount:
                # opaque front copies of glass-backed faces: visible only
                # from the front (the translucent back pass owns the rear)
                self._gl.glEnable(GL_CULL_FACE)
                self._gl.glCullFace(GL_BACK)
                self._gl.glDrawArrays(GL_TRIANGLES, fstart, fcount)
                self._gl.glDisable(GL_CULL_FACE)
            self._faces_vao.release()
            if mode == "xray":
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
                self._gl.glDepthMask(GL_TRUE)
            self._program.setUniformValue(self._loc_use_vcolor, 0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

        # Textured faces — same depth/offset treatment, sampling each face's
        # image. One draw per texture (its GL texture bound to unit 0).
        if self._tex_faces_count > 0 and mode in ("hidden_line", "monochrome"):
            # Plan styles: textured faces draw flat like the rest.
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            fr = style.front_color
            self._set_color(fr[0], fr[1], fr[2], 1.0)
            self._tex_faces_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._tex_faces_count)
            self._tex_faces_vao.release()
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        elif self._tex_faces_count > 0 and mode == "shaded":
            # SketchUp "Shaded": textured faces draw in their texture's
            # AVERAGE colour (the material colour), keeping the run shading.
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            self._tex_faces_vao.bind()
            run_parts = getattr(self, "_tex_run_parts", None)
            for ri, ((path, shade), start, count) in enumerate(self._tex_runs):
                if not run_parts:
                    vis, subj = [(start, count)], []
                else:
                    vis, subj = self._tex_run_spans(run_parts[ri], planes,
                                                    fading)
                if not vis and not subj:
                    continue
                r, g, b = self._texture_avg_color(path)
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                self._set_color(r, g, b, 1.0)
                for fade, spans in ((EDIT_REST_FADE, vis), (0.0, subj)) \
                        if fading else ((0.0, vis),):
                    if not spans:
                        continue
                    self._program.setUniformValue1f(self._loc_fade, fade)
                    for _vs, _vc in spans:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
            self._program.setUniformValue1f(self._loc_fade, 0.0)
            self._tex_faces_vao.release()
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        elif self._tex_faces_count > 0 and mode in ("textures", "xray"):
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            self._program.setUniformValue(self._loc_use_tex, 1)
            if mode == "xray":
                self._program.setUniformValue1f(self._loc_opacity, 0.55)
                self._gl.glDepthMask(GL_FALSE)
            self._tex_faces_vao.bind()
            run_parts = getattr(self, "_tex_run_parts", None)
            for ri, ((path, shade), start, count) in enumerate(self._tex_runs):
                if not run_parts:
                    vis, subj = [(start, count)], []
                else:
                    vis, subj = self._tex_run_spans(run_parts[ri], planes,
                                                    fading)
                if not vis and not subj:
                    continue
                tex = self._get_texture(path)
                if tex is None:
                    continue
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                self._program.setUniformValue(
                    self._loc_hard_cutout,
                    1 if getattr(tex, "_cutout", False) else 0)
                tex.bind(0)
                for fade, spans in ((EDIT_REST_FADE, vis), (0.0, subj)) \
                        if fading else ((0.0, vis),):
                    if not spans:
                        continue
                    self._program.setUniformValue1f(self._loc_fade, fade)
                    for _vs, _vc in spans:
                        self._gl.glDrawArrays(GL_TRIANGLES, _vs, _vc)
                tex.release(0)
            self._program.setUniformValue1f(self._loc_fade, 0.0)
            self._program.setUniformValue(self._loc_hard_cutout, 0)
            self._tex_faces_vao.release()
            if mode == "xray":
                self._program.setUniformValue1f(self._loc_opacity, 1.0)
                self._gl.glDepthMask(GL_TRUE)
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._program.setUniformValue(self._loc_use_tex, 0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

        # Instanced components (P2): eligible instances draw from their
        # prototype's local VBOs with per-instance matrices — the
        # consolidated passes above excluded them in _sync_edges.
        self._draw_instanced_faces(mode, style)
        # Shadows stop at the face passes: edges, overlays, previews and
        # billboards stay unlit (v1 scope).
        if getattr(self, "_frame_shadow", None) is not None:
            self._program.setUniformValue(self._loc_shadow_enable, 0)

        # Back-side material overrides (faces painted DIFFERENTLY per side,
        # SketchUp two-sided paint): drawn with front-face culling so they
        # only show from behind, without the face passes' polygon offset so
        # they win the depth test over the front copy there.
        if (self._back_vcol_run[1] > 0 or self._back_tex_runs) \
                and mode in ("textures", "shaded", "xray"):
            self._gl.glEnable(GL_CULL_FACE)
            self._gl.glCullFace(GL_FRONT)
            bstart, bcount = self._back_vcol_run
            if bcount:
                self._program.setUniformValue(self._loc_use_vcolor, 1)
                self._faces_vao.bind()
                self._gl.glDrawArrays(GL_TRIANGLES, bstart, bcount)
                self._faces_vao.release()
                self._program.setUniformValue(self._loc_use_vcolor, 0)
            if self._back_tex_runs:
                self._program.setUniformValue(self._loc_use_tex, 1)
                self._tex_faces_vao.bind()
                for (path, shade), start, count in self._back_tex_runs:
                    tex = self._get_texture(path)
                    if tex is None:
                        continue
                    self._program.setUniformValue1f(self._loc_shade, float(shade))
                    self._program.setUniformValue(
                        self._loc_hard_cutout,
                        1 if getattr(tex, "_cutout", False) else 0)
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    tex.release(0)
                self._program.setUniformValue(self._loc_hard_cutout, 0)
                self._tex_faces_vao.release()
                self._program.setUniformValue1f(self._loc_shade, 1.0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            self._gl.glDisable(GL_CULL_FACE)

        self._draw_section_fill(mode, style)

        # Translucent material runs (SketchUp trans with useTrans): drawn
        # after everything opaque, blended, depth-tested but not depth-
        # written, so glass/mesh screens show what's behind them.
        if (self._tcol_runs or self._ttex_runs
                or self._back_tcol_runs or self._back_ttex_runs) \
                and mode in ("textures", "shaded", "xray"):
            self._gl.glDepthMask(GL_FALSE)
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            if self._tcol_runs or self._back_tcol_runs:
                self._program.setUniformValue(self._loc_use_vcolor, 1)
                self._faces_vao.bind()
                for a, fc, start, count in self._tcol_runs:
                    self._program.setUniformValue1f(self._loc_opacity, float(a))
                    if fc:
                        # glass-backed front copy: front side only
                        self._gl.glEnable(GL_CULL_FACE)
                        self._gl.glCullFace(GL_BACK)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    if fc:
                        self._gl.glDisable(GL_CULL_FACE)
                if self._back_tcol_runs:
                    # translucent BACK overrides: back side only
                    self._gl.glEnable(GL_CULL_FACE)
                    self._gl.glCullFace(GL_FRONT)
                    for a, start, count in self._back_tcol_runs:
                        self._program.setUniformValue1f(self._loc_opacity, float(a))
                        self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    self._gl.glDisable(GL_CULL_FACE)
                self._faces_vao.release()
                self._program.setUniformValue(self._loc_use_vcolor, 0)
            if self._ttex_runs or self._back_ttex_runs:
                self._program.setUniformValue(self._loc_use_tex, 1)
                self._tex_faces_vao.bind()
                for (path, shade), a, fc, start, count in self._ttex_runs:
                    tex = self._get_texture(path)
                    if tex is None:
                        continue
                    self._program.setUniformValue1f(self._loc_opacity, float(a))
                    self._program.setUniformValue1f(self._loc_shade, float(shade))
                    if fc:
                        self._gl.glEnable(GL_CULL_FACE)
                        self._gl.glCullFace(GL_BACK)
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    tex.release(0)
                    if fc:
                        self._gl.glDisable(GL_CULL_FACE)
                if self._back_ttex_runs:
                    self._gl.glEnable(GL_CULL_FACE)
                    self._gl.glCullFace(GL_FRONT)
                    for (path, shade), a, start, count in self._back_ttex_runs:
                        tex = self._get_texture(path)
                        if tex is None:
                            continue
                        self._program.setUniformValue1f(self._loc_opacity, float(a))
                        self._program.setUniformValue1f(self._loc_shade, float(shade))
                        tex.bind(0)
                        self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                        tex.release(0)
                    self._gl.glDisable(GL_CULL_FACE)
                self._tex_faces_vao.release()
                self._program.setUniformValue1f(self._loc_shade, 1.0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            self._program.setUniformValue1f(self._loc_opacity, 1.0)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
            self._gl.glDepthMask(GL_TRUE)

        # Face-me billboards (SketchUp 2D people): per-frame textured cutout
        # — skipped on plan sheets and line styles: a coloured cutout person
        # on a technical drawing gives the raster away; scale figures belong
        # to the shaded looks only.
        if self.plano_style is None and mode in ("textures", "shaded", "xray"):
            self._draw_billboards()
            self._draw_billboard_outlines()

        # Face highlights (selection + hover) — translucent overlays drawn on
        # top of the cream faces. Same polygon offset as the faces so they sit
        # at matching depth (LEQUAL lets this later draw win); depth-write OFF
        # so the overlay tints without blocking the edges drawn afterwards.
        if self._sel_faces_count > 0 or self._hover_entity is not None:
            self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
            self._gl.glPolygonOffset(1.0, 1.0)
            self._gl.glDepthMask(GL_FALSE)
            if self._sel_faces_count > 0:
                self._set_color(0.95, 0.45, 0.16, 0.35)  # selection orange tint
                self._sel_faces_vao.bind()
                self._gl.glDrawArrays(GL_TRIANGLES, 0, self._sel_faces_count)
                self._sel_faces_vao.release()
            if isinstance(self._hover_entity, Face):
                hover_count = self._upload_hover_face(self._hover_entity)
                if hover_count > 0:
                    self._set_color(0.30, 0.55, 0.95, 0.28)  # hover blue tint
                    self._hover_faces_vao.bind()
                    self._gl.glDrawArrays(GL_TRIANGLES, 0, hover_count)
                    self._hover_faces_vao.release()
            self._gl.glDepthMask(GL_TRUE)
            self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

        _fmark("faces")
        # Shaded solid preview (Push/Pull box forming as you drag). Drawn after
        # the persistent faces, depth-tested so it occludes geometry behind it
        # and reads as a real solid; its wireframe goes on top via the rubber
        # band below.
        self._set_section_clip(False)
        self._draw_preview_faces()
        self._draw_groups_preview(mvp)

        # Axes — long solid positive + evenly-dashed negative per axis (SketchUp).
        # Dash spacing scales with the camera distance so the on-screen density
        # stays stable across zoom. Depth-write OFF so the ground axes don't cull
        # geometry sitting on z=0; drawn BEFORE user edges so an edge along an
        # axis wins the LEQUAL depth test. Rubber-band stays on top (drawn last).
        if self.plano_style is None and self.style_override is None:
            # No axes on a plan sheet / styled composer frame.
            spacing = max(self.camera.distance * 0.008, 1e-4)
            axes_coords, self._axes_spans = _axes_vertices(spacing)
            data = axes_coords.tobytes()
            self._axes_vbo.bind()
            self._axes_vbo.allocate(data, len(data))
            self._axes_vbo.release()
            self._axes_vao.bind()
            self._gl.glDepthMask(GL_FALSE)
            for name, rgb in (("x", (0.86, 0.22, 0.27)),   # red
                              ("y", (0.16, 0.62, 0.36)),   # green
                              ("z", (0.20, 0.40, 0.78))):  # blue
                start, count = self._axes_spans[name]
                self._set_color(*rgb, 1.0)
                self._gl.glDrawArrays(GL_LINES, start, count)
            self._gl.glDepthMask(GL_TRUE)
            self._axes_vao.release()

        self._set_section_clip(True)
        show_edges = style.edges or mode == "wireframe"
        ec = style.edge_color
        if self._edges_count > 0 and show_edges:
            self._set_color(ec[0], ec[1], ec[2], 1.0)
            self._edges_vao.bind()
            _espans = getattr(self, "_frame_edge_spans",
                              ((0, self._edges_count),))
            if split_e is None:
                for _vs, _vc in _espans:
                    self._gl.glDrawArrays(GL_LINES, _vs, _vc)
            else:
                # Same two-tier draw as the faces: washed-out surroundings,
                # then the edited group's own edges at full strength.
                self._program.setUniformValue1f(self._loc_fade,
                                                EDIT_REST_FADE)
                for _vs, _vc in _espans:
                    if _vs < split_e:
                        self._gl.glDrawArrays(GL_LINES, _vs, _vc)
                self._program.setUniformValue1f(self._loc_fade, 0.0)
                for _vs, _vc in _espans:
                    if _vs >= split_e:
                        self._gl.glDrawArrays(GL_LINES, _vs, _vc)
            self._edges_vao.release()
        if show_edges:
            self._set_color(ec[0], ec[1], ec[2], 1.0)
            self._draw_instanced_edges()

        # Profile (silhouette) edges: soft seams of a curved surface are hidden,
        # except where the surface turns away from the viewer — the cylinder's
        # outline. View-dependent, so rebuilt every frame, SketchUp-style.
        if show_edges and style.profiles:
            sil_count = self._upload_silhouette_edges()
            if sil_count > 0:
                self._set_color(ec[0], ec[1], ec[2], 1.0)
                self._silhouette_vao.bind()
                self._gl.glDrawArrays(GL_LINES, 0, sil_count)
                self._silhouette_vao.release()
        _fmark("edges")

        # Selected edges (drawn on top, highlighted)
        if self._selected_count > 0:
            self._set_color(0.95, 0.45, 0.16, 1.0)
            self._selected_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, self._selected_count)
            self._selected_vao.release()

        # Hovered edge — light blue, on top of everything else so it reads as
        # the pick candidate even when it overlaps a selected (orange) edge.
        # A curve segment highlights its whole contour (what a click selects).
        if isinstance(self._hover_entity, Edge):
            hover_count = self._upload_hover_edge(self._hover_entity)
            self._set_color(0.30, 0.55, 0.95, 1.0)
            self._hover_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, hover_count)
            self._hover_edges_vao.release()
        self._set_section_clip(False)
        self._draw_section_cut_edges()   # ON the plane — drawn unclipped

        # Rubber band preview. Loose drawing tools float it on top (depth test
        # off, so it never z-fights with coincident axes). Push/Pull's solid
        # preview keeps depth testing on, so the forming box's back edges are
        # hidden behind its faces — SketchUp-style hidden-line removal.
        depth_wire = (
            getattr(self.active_tool, "wireframe_depth_tested", False)
            if self.active_tool is not None
            else False
        )
        if not depth_wire:
            self._gl.glDisable(GL_DEPTH_TEST)
        self._draw_rubber_band()
        if not depth_wire:
            self._gl.glEnable(GL_DEPTH_TEST)

        self._program.release()

        if self._export_size is not None:
            # Hi-res export: the scene stays in the FBO for render_image to
            # read back; the widget blit and its QPainter overlay don't apply.
            self._scene_fbo.release()
            return

        # Blit colour from our scene FBO to the widget's default framebuffer.
        # We can't use QOpenGLFramebufferObject.blitFramebuffer(None, src) here
        # because in QOpenGLWidget the "default" framebuffer the widget shows
        # is its own internal FBO (returned by defaultFramebufferObject()),
        # NOT the system framebuffer 0. So we bind the read/draw targets by id
        # and call glBlitFramebuffer directly via the GL3+ extra functions.
        extra = self.context().extraFunctions()
        self._gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, self._scene_fbo.handle())
        self._gl.glBindFramebuffer(GL_DRAW_FRAMEBUFFER, default_fbo)
        extra.glBlitFramebuffer(
            0, 0, w, h, 0, 0, w, h, GL_COLOR_BUFFER_BIT, GL_NEAREST
        )
        self._gl.glBindFramebuffer(GL_FRAMEBUFFER, default_fbo)
        if _PERF:
            _plog("paintGL.gl+blit",
                  (_time_mod.perf_counter() - _pt0) * 1000.0, floor=30.0)
            _ov0 = _time_mod.perf_counter()

        # 2D overlays on top of the OpenGL framebuffer.
        self._draw_overlay()

        if _PERF:
            _plog("paintGL.overlay",
                  (_time_mod.perf_counter() - _ov0) * 1000.0, floor=30.0)
            _dt = (_time_mod.perf_counter() - _pt0) * 1000.0
            _plog("paintGL", _dt)
            # P0 breakdown: per-section CPU ms + cull counters + the
            # input→paint latency of the gesture that triggered this frame.
            if _dt >= 25.0:
                cf, tf, ce = getattr(self, "_cull_stats", (0, 0, 0))
                it = getattr(self, "_input_t", None)
                lat = (f" lat={( _time_mod.monotonic() - it) * 1000.0:.0f}ms"
                       if it is not None else "")
                segs = " ".join(f"{k}={v:.0f}ms" for k, v in _fseg.items())
                _plog("frame", _dt,
                      extra=f"{segs} cull={cf//1000}k/{tf//1000}k"
                            f" tris +{ce//1000}k edges{lat}", floor=0.0)
            self._input_t = None
            st = getattr(self, "_perf_stat", None) or \
                [_time_mod.perf_counter(), 0, 0.0]
            st[1] += 1
            st[2] += _dt
            now = _time_mod.perf_counter()
            if now - st[0] >= 1.0:
                _plog("frames/s", st[2] / max(st[1], 1),
                      extra=f"{st[1]} paints en {now-st[0]:.1f}s (avg ms)",
                      floor=0.0)
                st = [now, 0, 0.0]
            self._perf_stat = st

    # ---- Setup helpers ------------------------------------------------------
    def _compile_program(self) -> QOpenGLShaderProgram:
        prog = QOpenGLShaderProgram(self)
        ok_v = prog.addShaderFromSourceFile(
            QOpenGLShader.Vertex, str(SHADER_DIR / "basic.vert")
        )
        ok_f = prog.addShaderFromSourceFile(
            QOpenGLShader.Fragment, str(SHADER_DIR / "basic.frag")
        )
        if not (ok_v and ok_f and prog.link()):
            raise RuntimeError("shader compile/link failed:\n" + prog.log())
        return prog

    def _compile_depth_program(self) -> QOpenGLShaderProgram:
        prog = QOpenGLShaderProgram(self)
        ok_v = prog.addShaderFromSourceFile(
            QOpenGLShader.Vertex, str(SHADER_DIR / "depth.vert")
        )
        ok_f = prog.addShaderFromSourceFile(
            QOpenGLShader.Fragment, str(SHADER_DIR / "depth.frag")
        )
        if not (ok_v and ok_f and prog.link()):
            raise RuntimeError(
                "depth shader compile/link failed:\n" + prog.log())
        return prog

    def _upload_static(self, data: array):
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.create()
        vbo.bind()
        raw = data.tobytes()
        vbo.allocate(raw, len(raw))
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo, len(data) // 3

    def _create_dynamic(self):
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(24)  # 2 vertices × 3 floats × 4 bytes
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    def _create_dynamic_color(self):
        """A dynamic VAO/VBO interleaving position (3f) + RGB (3f) per
        vertex — the sky-gradient backdrop (drawn with ``u_use_vcolor``)."""
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(48)  # 2 vertices × 6 floats × 4 bytes
        stride = 6 * 4
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, stride)
        self._program.enableAttributeArray(self._loc_vcolor)
        self._program.setAttributeBuffer(self._loc_vcolor, GL_FLOAT, 12, 3,
                                         stride)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    def _create_dynamic_uv(self):
        """A dynamic VAO/VBO interleaving position (3f) + UV (2f) per vertex —
        for textured faces."""
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(40)  # 2 vertices × 5 floats × 4 bytes
        stride = 5 * 4
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, stride)
        self._program.enableAttributeArray(self._loc_uv)
        self._program.setAttributeBuffer(self._loc_uv, GL_FLOAT, 3 * 4, 2, stride)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    def _create_dynamic_vcol(self):
        """A dynamic VAO/VBO interleaving position (3f) + RGB (3f) per vertex —
        the batched face pass (one draw call for every colour run)."""
        vao = QOpenGLVertexArrayObject(self)
        vao.create()
        vao.bind()
        vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        vbo.create()
        vbo.bind()
        vbo.allocate(48)  # 2 vertices × 6 floats × 4 bytes
        stride = 6 * 4
        self._program.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, stride)
        self._program.enableAttributeArray(self._loc_vcolor)
        self._program.setAttributeBuffer(self._loc_vcolor, GL_FLOAT, 3 * 4, 3,
                                         stride)
        self._program.release()
        vbo.release()
        vao.release()
        return vao, vbo

    # ---- Instanced components (P2) ------------------------------------------
    # Component instances draw from ONE static proto VBO (local coords) plus
    # a per-instance matrix buffer (divisor 1): N hedges cost one upload and
    # one draw per proto run. Instances keep their baked chunks for picks,
    # silhouettes, selection and the drag preview; only the CONSOLIDATED
    # draw excludes them. INGETRAZO_NO_INSTANCING=1 reverts to the old path.

    def _instanced_eligible(self, g) -> bool:
        if (_NO_INSTANCING or getattr(g, "xform", None) is None
                or getattr(g, "billboard", False)):
            return False
        base = self._proto_base_chunk(g.mesh)
        # Translucent / back-side / glass content still rides the
        # consolidated passes (they need global draw ordering).
        return not (base.get("tcol") or base.get("ttex")
                    or base.get("back_vcol") or base.get("back_tex")
                    or base.get("back_tcol") or base.get("back_ttex")
                    or base.get("fvcol"))

    def _proto_base_chunk(self, mesh):
        """The prototype's chunk in LOCAL coordinates (the same wrapper
        ``_instance_chunk`` derives from)."""
        wrappers = getattr(self, "_proto_wrappers", None)
        if wrappers is None:
            wrappers = self._proto_wrappers = {}
        w = wrappers.get(id(mesh))
        if w is None:
            from types import SimpleNamespace
            w = wrappers[id(mesh)] = SimpleNamespace(mesh=mesh, xform=None)
        return self._group_chunk(w)

    def _placements(self):
        """``scene.groups`` with every nested placement expanded into a proxy
        group carrying its composed world matrix.

        Drawing and picking want one entry per PLACEMENT — each renders its
        own prototype through its own matrix, which is the whole point of
        keeping a component's internal sharing. The USER wants one entry per
        top-level object. The proxies bridge that: they look exactly like
        ordinary component instances, so no draw or pick path needs a special
        case, and ``owner`` maps a hit back to the group in ``scene.groups``.

        Proxies are cached per child object and mutated in place: a fresh
        object per frame would miss ``_instance_chunk``'s cache (keyed on
        ``id(group)``) and re-transform every instance's arrays every frame.
        A scene with no nested placements returns ``scene.groups`` itself."""
        groups = self.scene.groups
        if not any(getattr(g, "children", None) for g in groups):
            return groups                      # unchanged for flat scenes
        cache = getattr(self, "_placement_proxies", None)
        if cache is None:
            cache = self._placement_proxies = {}
        out: list = []
        seen: set = set()
        for g in groups:
            self._expand_placements(g, out, seen)
        # Proxies are pinned while a preview is running: the movers' ids are
        # what the draw passes skip on, and dropping one mid-drag would make
        # a fresh object (chunk cache miss) that the preview no longer knows.
        if len(cache) > len(seen) and not getattr(self, "_preview_groups",
                                                  None):
            for k in [k for k in cache if k not in seen]:
                cache.pop(k, None)
        return out

    def _expand_placements(self, group, out=None, seen=None):
        """``group`` followed by its nested placements, as stable proxies.

        Used both for the whole scene (``_placements``) and for ONE group's
        subtree — a caller that used to treat a group as "its mesh" has to
        take the subtree instead, or a component drags an empty ghost while
        its children sit frozen at the old spot."""
        if out is None:
            out = []
        cache = getattr(self, "_placement_proxies", None)
        if cache is None:
            cache = self._placement_proxies = {}
        out.append(group)
        kids = getattr(group, "children", None)
        if not kids:
            return out
        vis, locked = self.scene._layer_state(group)
        forced = group.layer if (not vis or locked) else None

        def walk(node, world):
            for child in node.children:
                m = (child.xform if world is None
                     else (world * child.xform if child.xform is not None
                           else world))
                proxy = cache.get(id(child))
                if proxy is None:
                    proxy = cache[id(child)] = Group(child.mesh,
                                                     name=child.name)
                if seen is not None:
                    seen.add(id(child))
                proxy.mesh = child.mesh
                # A nested entity with no tag of its own inherits the
                # parent's (SketchUp); and when the parent's tag is hidden or
                # locked the whole instance goes with it, whatever its
                # children are tagged.
                proxy.layer = forced or child.layer or node.layer
                proxy.billboard = child.billboard
                proxy.owner = group
                proxy.xform = m
                out.append(proxy)
                if child.children:
                    walk(child, m)

        walk(group, getattr(group, "xform", None))
        return out

    def _gather_instanced(self):
        """Visible, eligible instances grouped by prototype mesh — computed
        once per frame (faces pass), reused by the edges pass. Instances are
        frustum-culled by their baked chunk's world AABB.

        WHICH placements are eligible changes only with the scene; only the
        frustum test is per frame. Keeping a component's internal sharing
        multiplied the candidates (89 groups -> 411 placements on Marco's
        pool) and re-deriving eligibility every frame cost 2.5 ms of pure
        Python per zoom notch against 0.4 ms before — the wheel felt heavier.
        The pool is cached per scene version and the cull is one NumPy pass
        over every box at once."""
        import numpy as np
        pv = getattr(self, "_preview_groups", None) or ()
        planes = getattr(self, "_frame_planes", None)
        key = (self.scene.version, id(self.scene.mesh),
               getattr(self, "_preview_epoch", 0),
               getattr(self, "_frozen_cache_version", None))
        pool = getattr(self, "_inst_pool", None)
        if pool is None or pool[0] != key:
            groups: list = []
            boxes: list = []
            for g in self._placements():
                if id(g) in pv or not self.scene.entity_visible(g):
                    continue
                if not self._instanced_eligible(g):
                    continue
                groups.append(g)
                boxes.append(self._group_chunk(g).get("bbox"))
            # Boxless chunks (unknown extents) always draw: give them an
            # infinite box so the vectorised test keeps them.
            lo = np.array([b[0] if b else (-np.inf,) * 3 for b in boxes],
                          dtype=np.float64).reshape(-1, 3)
            hi = np.array([b[1] if b else (np.inf,) * 3 for b in boxes],
                          dtype=np.float64).reshape(-1, 3)
            pool = self._inst_pool = (key, groups, lo, hi)
        _k, groups, lo, hi = pool
        out: dict = {}
        if not groups:
            self._frame_instanced = out
            return out
        if planes is None:
            keep = np.ones(len(groups), dtype=bool)
        else:
            # Same p-vertex test as ``_aabb_visible``, all boxes at once.
            pl = np.asarray(planes, dtype=np.float64)
            n = pl[:, :3]
            pick = np.where(n[:, None, :] >= 0.0, hi[None, :, :],
                            lo[None, :, :])
            keep = ((pick * n[:, None, :]).sum(axis=2)
                    + pl[:, 3][:, None] >= 0.0).all(axis=0)
        for i in np.flatnonzero(keep):
            g = groups[i]
            out.setdefault(id(g.mesh), (g.mesh, []))[1].append(g)
        self._frame_instanced = out
        return out

    def _ensure_proto_draw(self, mesh):
        """Static draw entry of one prototype: vcol/edges/texture VBOs from
        the LOCAL base chunk, three VAOs wiring them to the shared
        per-instance matrix buffer (divisor 1), built once per proto rev."""
        cache = getattr(self, "_proto_draw", None)
        if cache is None:
            cache = self._proto_draw = {}
        base = self._proto_base_chunk(mesh)
        key = (id(base), base.get("rev"))
        entry = cache.get(id(mesh))
        if entry is not None and entry["key"] == key:
            return entry
        extra = self.context().extraFunctions()

        def static_vbo(raw):
            vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            vbo.setUsagePattern(QOpenGLBuffer.StaticDraw)
            vbo.create()
            vbo.bind()
            vbo.allocate(raw or b"\0" * 4, max(len(raw), 4))
            vbo.release()
            return vbo

        mat_vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        mat_vbo.setUsagePattern(QOpenGLBuffer.DynamicDraw)
        mat_vbo.create()
        mat_vbo.bind()
        mat_vbo.allocate(64)
        mat_vbo.release()

        def wire_matrix():
            # Caller keeps the VAO bound; attach the matrix columns.
            mat_vbo.bind()
            for i, loc in enumerate(self._loc_inst):
                self._program.enableAttributeArray(loc)
                self._program.setAttributeBuffer(loc, GL_FLOAT, i * 16, 4, 64)
                extra.glVertexAttribDivisor(loc, 1)
            mat_vbo.release()

        self._program.bind()
        # vcol: pos(3)+rgb(3)
        vcol_raw = base["vcol"]
        vcol_vbo = static_vbo(vcol_raw)
        vcol_vao = QOpenGLVertexArrayObject(self)
        vcol_vao.create()
        vcol_vao.bind()
        vcol_vbo.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, 24)
        self._program.enableAttributeArray(self._loc_vcolor)
        self._program.setAttributeBuffer(self._loc_vcolor, GL_FLOAT, 12, 3, 24)
        vcol_vbo.release()
        wire_matrix()
        vcol_vao.release()
        # edges: pos(3)
        edges_raw = base["edges"]
        edges_vbo = static_vbo(edges_raw)
        edges_vao = QOpenGLVertexArrayObject(self)
        edges_vao.create()
        edges_vao.bind()
        edges_vbo.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, 12)
        edges_vbo.release()
        wire_matrix()
        edges_vao.release()
        # textures: pos(3)+uv(2), one run per (path, shade)
        tex_parts = []
        tex_runs = []
        start = 0
        for tkey, raw in base["by_texture"].items():
            tex_parts.append(raw)
            n = len(raw) // 20
            tex_runs.append((tkey, start, n))
            start += n
        tex_raw = b"".join(tex_parts)
        tex_vbo = static_vbo(tex_raw)
        tex_vao = QOpenGLVertexArrayObject(self)
        tex_vao.create()
        tex_vao.bind()
        tex_vbo.bind()
        self._program.enableAttributeArray(self._loc_pos)
        self._program.setAttributeBuffer(self._loc_pos, GL_FLOAT, 0, 3, 20)
        self._program.enableAttributeArray(self._loc_uv)
        self._program.setAttributeBuffer(self._loc_uv, GL_FLOAT, 12, 2, 20)
        tex_vbo.release()
        wire_matrix()
        tex_vao.release()
        self._program.release()
        entry = {"key": key, "mat_sig": None, "mat_vbo": mat_vbo,
                 "vcol_vao": vcol_vao, "vcol_vbo": vcol_vbo,
                 "vcol_count": len(vcol_raw) // 24,
                 "edges_vao": edges_vao, "edges_vbo": edges_vbo,
                 "edge_count": len(edges_raw) // 12,
                 "tex_vao": tex_vao, "tex_vbo": tex_vbo,
                 "tex_runs": tex_runs}
        cache[id(mesh)] = entry
        return entry

    def _update_inst_matrices(self, entry, groups) -> int:
        sig = tuple((id(g), tuple(g.xform.data())) for g in groups)
        if entry["mat_sig"] != sig:
            import numpy as np
            raw = np.asarray([list(g.xform.data()) for g in groups],
                             dtype=np.float32).tobytes()
            entry["mat_vbo"].bind()
            entry["mat_vbo"].allocate(raw, len(raw))
            entry["mat_vbo"].release()
            entry["mat_sig"] = sig
        return len(groups)

    def _draw_instanced_faces(self, mode, style) -> None:
        by_proto = self._gather_instanced()
        if not by_proto or mode == "wireframe":
            return
        extra = self.context().extraFunctions()
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        if mode == "xray":
            self._program.setUniformValue1f(self._loc_opacity, 0.55)
            self._gl.glDepthMask(GL_FALSE)
        for mesh, groups in by_proto.values():
            entry = self._ensure_proto_draw(mesh)
            n = self._update_inst_matrices(entry, groups)
            if entry["vcol_count"]:
                if mode in ("hidden_line", "monochrome"):
                    self._program.setUniformValue(self._loc_use_vcolor, 0)
                    fr = style.front_color
                    self._set_color(fr[0], fr[1], fr[2], 1.0)
                    if mode == "hidden_line":
                        self._program.setUniformValue(
                            self._loc_back_color,
                            QVector4D(fr[0], fr[1], fr[2], 1.0))
                    else:
                        self._set_back_face_color()
                else:
                    self._program.setUniformValue(self._loc_use_vcolor, 1)
                    self._set_back_face_color()
                entry["vcol_vao"].bind()
                extra.glDrawArraysInstanced(
                    GL_TRIANGLES, 0, entry["vcol_count"], n)
                entry["vcol_vao"].release()
                self._program.setUniformValue(self._loc_use_vcolor, 0)
            if entry["tex_runs"]:
                if mode in ("hidden_line", "monochrome"):
                    fr = style.front_color
                    self._set_color(fr[0], fr[1], fr[2], 1.0)
                    entry["tex_vao"].bind()
                    for _tk, s0, cnt in entry["tex_runs"]:
                        extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                    entry["tex_vao"].release()
                elif mode == "shaded":
                    entry["tex_vao"].bind()
                    for (path, shade), s0, cnt in entry["tex_runs"]:
                        r, g, b = self._texture_avg_color(path)
                        self._program.setUniformValue1f(
                            self._loc_shade, float(shade))
                        self._set_color(r, g, b, 1.0)
                        extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                    entry["tex_vao"].release()
                    self._program.setUniformValue1f(self._loc_shade, 1.0)
                else:            # textures / xray
                    self._program.setUniformValue(self._loc_use_tex, 1)
                    entry["tex_vao"].bind()
                    for (path, shade), s0, cnt in entry["tex_runs"]:
                        tex = self._get_texture(path)
                        if tex is None:
                            continue
                        self._program.setUniformValue1f(
                            self._loc_shade, float(shade))
                        self._program.setUniformValue(
                            self._loc_hard_cutout,
                            1 if getattr(tex, "_cutout", False) else 0)
                        tex.bind(0)
                        extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                        tex.release(0)
                    entry["tex_vao"].release()
                    self._program.setUniformValue(self._loc_hard_cutout, 0)
                    self._program.setUniformValue1f(self._loc_shade, 1.0)
                    self._program.setUniformValue(self._loc_use_tex, 0)
        if mode == "xray":
            self._program.setUniformValue1f(self._loc_opacity, 1.0)
            self._gl.glDepthMask(GL_TRUE)
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

    def _draw_instanced_raw(self) -> None:
        """Geometry-only instanced draw — the section-fill stencil pass."""
        by_proto = getattr(self, "_frame_instanced", None)
        if not by_proto:
            return
        extra = self.context().extraFunctions()
        for mesh, groups in by_proto.values():
            entry = self._ensure_proto_draw(mesh)
            n = self._update_inst_matrices(entry, groups)
            if entry["vcol_count"]:
                entry["vcol_vao"].bind()
                extra.glDrawArraysInstanced(
                    GL_TRIANGLES, 0, entry["vcol_count"], n)
                entry["vcol_vao"].release()
            if entry["tex_runs"]:
                entry["tex_vao"].bind()
                for _tk, s0, cnt in entry["tex_runs"]:
                    extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                entry["tex_vao"].release()

    def _draw_instanced_edges(self) -> None:
        by_proto = getattr(self, "_frame_instanced", None)
        if not by_proto:
            return
        extra = self.context().extraFunctions()
        for mesh, groups in by_proto.values():
            entry = self._ensure_proto_draw(mesh)
            if not entry["edge_count"]:
                continue
            n = self._update_inst_matrices(entry, groups)
            entry["edges_vao"].bind()
            extra.glDrawArraysInstanced(GL_LINES, 0, entry["edge_count"], n)
            entry["edges_vao"].release()

    def _draw_image_planes(self) -> None:
        """Reference images, as textured quads under the model.

        Depth **test** on, depth **write** off — the same treatment the base
        map gets, and here it is what makes tracing work: the picture is
        occluded by anything already in front of it, but writes no depth of
        its own, so a line drawn exactly ON the image still wins the depth
        test and appears over it instead of z-fighting into invisibility.

        Shading is pinned to 1.0: a reference scan has to read at its true
        tones, not dimmed by the face lighting.
        """
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return
        import struct
        vao = getattr(self, "_img_vao", None)
        if vao is None:
            self._img_vao, self._img_vbo = self._create_dynamic_uv()
            vao = self._img_vao
        drawn = []
        for im in images:
            if not self.scene.entity_visible(im):
                continue
            tex = self._get_texture(im.path)
            if tex is None:
                continue
            drawn.append((im, tex))
        if not drawn:
            return
        self._program.setUniformValue(self._loc_use_tex, 1)
        self._program.setUniformValue(self._loc_use_vcolor, 0)
        self._program.setUniformValue1f(self._loc_shade, 1.0)
        # The reference layers before us may leave the foliage cutout on; a
        # scan with soft edges would come out with its alpha chopped.
        self._program.setUniformValue(self._loc_hard_cutout, 0)
        self._gl.glDepthMask(GL_FALSE)
        blending = False
        for im, tex in drawn:
            c = im.corners()
            # Two triangles, UV (0,0) at ``origin``: _get_texture uploads the
            # image mirrored (bottom-up V), so v grows with the plane's "up"
            # axis and the picture stands upright.
            quad = ((c[0], 0.0, 0.0), (c[1], 1.0, 0.0), (c[2], 1.0, 1.0),
                    (c[0], 0.0, 0.0), (c[2], 1.0, 1.0), (c[3], 0.0, 1.0))
            raw = b"".join(struct.pack("<5f", v.x(), v.y(), v.z(), u, w)
                           for v, u, w in quad)
            opacity = max(0.0, min(1.0, float(getattr(im, "opacity", 1.0))))
            if opacity < 1.0 and not blending:
                self._gl.glEnable(GL_BLEND)
                self._gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                blending = True
            self._program.setUniformValue1f(self._loc_opacity, opacity)
            self._img_vbo.bind()
            self._img_vbo.allocate(raw, len(raw))
            self._img_vbo.release()
            vao.bind()
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
            tex.release(0)
            vao.release()
        if blending:
            self._gl.glDisable(GL_BLEND)
        self._program.setUniformValue1f(self._loc_opacity, 1.0)
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue(self._loc_use_tex, 0)

    def image_plane_at(self, screen_x: float, screen_y: float,
                       selectable_only: bool = False):
        """The topmost reference image under the cursor, or ``None``.

        Casts the pixel ray at each image's plane and keeps the hit whose
        ``(u, v)`` falls inside the rectangle, nearest first. Later images win
        ties, matching the order they are painted in.

        ``selectable_only`` is what separates the two callers. Picking honours
        the image's own lock; the work-plane inference does NOT — a locked
        scan is exactly the one you have finished aligning and now want to
        draw on, so it must keep offering its plane while refusing clicks.
        """
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return None
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        best, best_t = None, float("inf")
        for im in images:
            if not self.scene.entity_visible(im):
                continue
            if selectable_only and (getattr(im, "locked", False)
                                    or not self.scene.entity_selectable(im)):
                continue
            n = im.normal()
            denom = QVector3D.dotProduct(n, direction)
            if abs(denom) < 1e-9:
                continue
            t = QVector3D.dotProduct(n, im.center() - origin) / denom
            if t < 0.0 or t > best_t:
                continue
            fu, fv = im.project(origin + direction * t)
            if im.contains_uv(fu, fv):
                best, best_t = im, t
        return best

    def pick_image_plane(self, screen_x: float, screen_y: float):
        """Selection entry point: like :meth:`image_plane_at` but skipping
        locked images, so a click on an aligned scan falls through to the
        geometry being drawn on it."""
        return self.image_plane_at(screen_x, screen_y, selectable_only=True)

    def _draw_image_outlines(self, painter: QPainter) -> None:
        """Border of each reference image: faint normally, selection orange
        when picked, so an image lying flat on the ground is still findable."""
        images = getattr(self.scene, "image_planes", None)
        if not images:
            return
        pen = QPen(QColor(120, 140, 165), 1, Qt.DashLine)
        sel_pen = QPen(QColor(243, 115, 41), 2)      # selection orange
        selection = self.scene.selection
        for im in images:
            if not self.scene.entity_visible(im):
                continue
            painter.setPen(sel_pen if im in selection else pen)
            for a, b in im.border_edges():
                seg = self._clip_segment_front(a, b)
                if seg is None:
                    continue
                pa = self._world_to_pixel(seg[0])
                pb = self._world_to_pixel(seg[1])
                if pa is not None and pb is not None:
                    painter.drawLine(QPointF(*pa), QPointF(*pb))

    def finish_image_placement(self) -> None:
        """Called by the Image tool once a picture is placed: drop back to
        Select, the way SketchUp does after a one-shot placement."""
        win = self.window()
        if hasattr(win, "activate_select_tool"):
            win.activate_select_tool()

    def _get_texture(self, path: str):
        """GL texture for an image ``path``, cached on the viewport. Returns the
        :class:`QOpenGLTexture` (Repeat wrap, linear+mipmap) or ``None`` if the
        image can't be loaded."""
        cache = getattr(self, "_tex_cache", None)
        if cache is None:
            cache = self._tex_cache = {}
        if path in cache:
            return cache[path]
        img = QImage(path)
        tex = None
        if not img.isNull():
            tex = QOpenGLTexture(img.mirrored())  # OBJ/SketchUp V is bottom-up
            tex.setWrapMode(QOpenGLTexture.Repeat)
            tex.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
            tex.setMagnificationFilter(QOpenGLTexture.Linear)
            # Foliage cutouts (low alpha coverage): mip-averaged alpha plus
            # atlas bleed erase or darken the leaves at distance, and the
            # Bayer dither turns the rest into ghost speckle. Tag them: the
            # textured passes sample the top level only and cut hard at 0.5
            # — crisp SketchUp-style vegetation at every zoom.
            if img.hasAlphaChannel():
                small = img.scaled(64, 64).convertToFormat(
                    QImage.Format_Alpha8)
                import numpy as _np
                al = _np.frombuffer(small.constBits(), _np.uint8,
                                    count=small.height()
                                    * small.bytesPerLine())
                cov = float((al > 128).mean()) if len(al) else 1.0
                if cov < 0.6:
                    tex.setMinificationFilter(QOpenGLTexture.Linear)
                    tex._cutout = True
        cache[path] = tex
        return tex

    def _texture_avg_color(self, path: str) -> tuple[float, float, float]:
        """Average colour of a texture image — SketchUp's "Shaded" face style
        shows the material COLOUR instead of its texture. Cached per path."""
        cache = getattr(self, "_tex_avg_cache", None)
        if cache is None:
            cache = self._tex_avg_cache = {}
        c = cache.get(path)
        if c is None:
            img = QImage(path)
            if img.isNull():
                c = (0.78, 0.78, 0.78)
            else:
                small = img.scaled(4, 4, Qt.IgnoreAspectRatio,
                                   Qt.SmoothTransformation)
                rs = gs = bs = n = 0
                for yy in range(small.height()):
                    for xx in range(small.width()):
                        px = small.pixelColor(xx, yy)
                        rs += px.red()
                        gs += px.green()
                        bs += px.blue()
                        n += 1
                c = ((rs / (255.0 * n), gs / (255.0 * n), bs / (255.0 * n))
                     if n else (0.78, 0.78, 0.78))
            cache[path] = c
        return c

    #: Back-face colour, SketchUp's blue-grey: a visible back face means
    #: "you are looking at the inside" (or at a genuinely inverted face) —
    #: honest feedback the winding-proof shading used to hide.
    BACK_FACE_COLOR = (0.62, 0.70, 0.78)

    def _set_color(self, r: float, g: float, b: float, a: float) -> None:
        self._program.setUniformValue(self._loc_color, QVector4D(r, g, b, a))
        # Keep the back colour in sync by default so lines and highlights
        # (where gl_FrontFacing is meaningless) render one colour; the face
        # passes override it just before their draws.
        self._program.setUniformValue(self._loc_back_color,
                                      QVector4D(r, g, b, a))

    def _set_back_face_color(self) -> None:
        # A scene may override the tint (adopted from an imported .skp's
        # style, so unpainted faces read like they did for the author).
        r, g, b = (getattr(self.scene, "back_face_color", None)
                   or self.BACK_FACE_COLOR)
        self._program.setUniformValue(self._loc_back_color,
                                      QVector4D(r, g, b, 1.0))

    def _shade_factor(self, normal) -> float:
        """Diffuse factor (0.62..1.0) of a face normal against the fixed
        world light — quantised to 1/32 so it can key texture draw runs
        without exploding the run count on curved surfaces."""
        if normal.length() < 1e-9:
            return 0.84375
        # abs(): shading depends on the face's plane, not its winding — a
        # flat plan whose faces happen to wind downward still reads bright,
        # while a solid keeps its top-bright / sides-toned maquette look.
        # The 0.62..1.0 range matches SketchUp's default-style contrast
        # (measured on user models: its shaded walls sit near 0.65 of the
        # lit tone) — the previous 0.80..1.0 read as "unshaded"/wrong
        # colour next to a SketchUp render of the same building.
        d = abs(QVector3D.dotProduct(normal.normalized(), self._LIGHT))
        return round((0.62 + 0.38 * d) * 32.0) / 32.0

    def _shaded_color(self, base, normal):
        """Multiply ``base`` RGB by a subtle diffuse term from the face normal vs
        the fixed world light — the matte-model shading. Returns a clamped RGB
        tuple used as the render key (identical normals/colours group together)."""
        shade = self._shade_factor(normal)
        # Quantise to 1/64 steps: the tuple is the DRAW-RUN key, and a model
        # with thousands of distinct normals (imported trees, curved detail)
        # otherwise explodes into one draw call per unique shade — 63k draw
        # calls per frame on a real 100k-face project. 1/64 banding is
        # invisible; the run count collapses to a few hundred.
        return (round(min(1.0, base[0] * shade) * 64.0) / 64.0,
                round(min(1.0, base[1] * shade) * 64.0) / 64.0,
                round(min(1.0, base[2] * shade) * 64.0) / 64.0)

    # ---- Base-map tiles (Track G) -------------------------------------------
    def _base_map_showing(self) -> bool:
        """True when a georeferenced base map is currently visible."""
        layer = getattr(self.scene, "tile_layer", None)
        return (layer is not None and getattr(layer, "visible", False)
                and getattr(self.scene, "georef", None) is not None)

    def _ensure_tile_fetcher(self):
        """Create the tile fetcher on first use (needs a running app)."""
        if self._tile_fetcher is None:
            from georef.tile_fetcher import TileFetcher
            self._tile_fetcher = TileFetcher(parent=self)
            self._tile_fetcher.tileReady.connect(self._on_tile_ready)
        return self._tile_fetcher

    def _on_tile_ready(self, source_id, x, y, z, image) -> None:
        """A downloaded tile arrived: stash its image and schedule a repaint."""
        layer = getattr(self.scene, "tile_layer", None)
        if (layer is not None and layer.source.id == source_id
                and z == layer.zoom):
            layer.images[(x, y, z)] = image
            self.tilesChanged.emit()
            self.update()

    def reset_texture_cache(self) -> None:
        """Return the document's cached GL textures to the driver.

        ``_get_texture`` uploads lazily and remembers forever, which is right
        WITHIN a document — but nothing ever emptied it, so a long session of
        opening textured models only ever grew VRAM (the same class of leak
        CLAUDE.md measured at 0.42 GB for one survey's tile atlases).
        File ▸ New / Open call this at the document boundary: the old
        document's pictures go back to the driver, and whatever the new one
        actually shows re-uploads on demand at first paint."""
        cache = getattr(self, "_tex_cache", None)
        if not cache:
            return
        # Same contract as reset_tiles: destroying GL textures needs the
        # context current — this runs from menu handlers, not paintGL.
        self.makeCurrent()
        try:
            for tex in cache.values():
                if tex is not None:
                    tex.destroy()
        finally:
            self.doneCurrent()
        cache.clear()
        self.update()

    def release_gl_textures(self) -> None:
        """Free every GL texture while the context can still take them back.

        Connected to the context's ``aboutToBeDestroyed`` — the one moment
        Qt guarantees for GL cleanup. Without it every texture alive at exit
        leaked with a "Texture has not been destroyed" warning each (harmless
        at process exit, real if the context is ever torn down and recreated
        mid-session, e.g. on reparenting)."""
        self.makeCurrent()
        try:
            cache = getattr(self, "_tex_cache", None)
            if cache:
                for tex in cache.values():
                    if tex is not None:
                        tex.destroy()
                cache.clear()
            tiles = getattr(self, "_tile_textures", None)
            if tiles:
                for tex in tiles.values():
                    if tex is not None:
                        tex.destroy()
                tiles.clear()
            terrain = getattr(self, "_terrain_texture", None)
            if terrain is not None:
                terrain.destroy()
                self._terrain_texture = None
            self._release_photo_textures_unsafe()
        finally:
            self.doneCurrent()

    def reset_tiles(self) -> None:
        """Drop cached GL textures + pending images (source/datum changed)."""
        if self._tile_textures:
            # Destroying GL textures needs the context current — this runs from
            # the Tray, not paintGL.
            self.makeCurrent()
            try:
                for tex in self._tile_textures.values():
                    if tex is not None:
                        tex.destroy()
            finally:
                self.doneCurrent()
        self._tile_textures.clear()
        self._tile_geom = None       # capture patches / datum may have changed
        if self._tile_fetcher is not None:
            self._tile_fetcher.cancel_all()
        layer = getattr(self.scene, "tile_layer", None)
        if layer is not None:
            layer.images.clear()
        self.update()

    # Max NEW GL textures created per frame. Uploading hundreds at once (a big
    # capture) overwhelms Mesa and reads back as garbage (black/green tears at
    # the far edge); creating a few per frame spreads it — the map fills in over
    # a second and repaints itself until done.
    # P4: 6 uploads (each with mipmap generation, ~5-15 ms on the iGPU)
    # stacked into one frame was the ~100 ms hitch while zooming over the
    # base map. 2 per frame keeps every frame under the 33 ms gate; the
    # deferred-repaint loop below spreads the rest across frames.
    _TEX_PER_FRAME = 2

    def _tile_texture(self, layer, x, y):
        """GL texture for tile ``(x, y)`` of ``layer``, or ``None`` if not yet
        available (a download is kicked off and the frame repaints on arrival)."""
        z = layer.zoom
        key = (layer.source.id, x, y, z)
        if key in self._tile_textures:
            return self._tile_textures[key]
        img = layer.images.get((x, y, z))
        if img is None:
            # Cache hit returns the image synchronously; a miss returns None and
            # starts an async download (see _on_tile_ready).
            img = self._ensure_tile_fetcher().request(layer.source, x, y, z)
            if img is None:
                return None
            layer.images[(x, y, z)] = img
        if self._tex_budget <= 0:
            self._tex_deferred = True     # too many this frame — next frame
            return None
        self._tex_budget -= 1
        tex = QOpenGLTexture(img)  # QImage is top-down; our UVs map north→v=0
        tex.setWrapMode(QOpenGLTexture.ClampToEdge)
        tex.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
        tex.setMagnificationFilter(QOpenGLTexture.Linear)
        self._tile_textures[key] = tex
        return tex

    def _terrain_showing(self) -> bool:
        t = getattr(self.scene, "terrain", None)
        return t is not None and getattr(t, "visible", False)

    def prefetch_tiles(self, source, tile_list, zoom) -> None:
        """Request the given tiles so their images populate ``tile_layer.images``
        (used to build the 3D terrain mosaic even when the flat map is hidden)."""
        layer = getattr(self.scene, "tile_layer", None)
        if layer is None:
            return
        fetcher = self._ensure_tile_fetcher()
        for (x, y) in tile_list:
            img = fetcher.request(source, x, y, zoom)
            if img is not None:
                layer.images[(x, y, zoom)] = img

    def upload_terrain(self, terrain) -> None:
        """Build the terrain VBO (pos+uv) and its mosaic texture from a
        :class:`~georef.terrain.TerrainObject`."""
        if terrain is None or not terrain.vertices or not terrain.triangles:
            self._terrain_count = 0
            return
        self.makeCurrent()
        try:
            raw = array("f")
            verts, uvs = terrain.vertices, terrain.uvs
            for (i, j, k) in terrain.triangles:
                for idx in (i, j, k):
                    v = verts[idx]
                    u, w = uvs[idx]
                    raw.extend([v.x(), v.y(), v.z(), u, w])
            data = raw.tobytes()
            self._terrain_vbo.bind()
            self._terrain_vbo.allocate(data, len(data))
            self._terrain_vbo.release()
            self._terrain_count = len(raw) // 5
            if self._terrain_texture is not None:
                self._terrain_texture.destroy()
                self._terrain_texture = None
            img = terrain.texture_image
            if img is not None and not img.isNull():
                self._terrain_texture = QOpenGLTexture(img)
                self._terrain_texture.setWrapMode(QOpenGLTexture.ClampToEdge)
                self._terrain_texture.setMinificationFilter(
                    QOpenGLTexture.LinearMipMapLinear)
                self._terrain_texture.setMagnificationFilter(QOpenGLTexture.Linear)
        finally:
            self.doneCurrent()
        self.update()

    def _render_terrain(self) -> None:
        if not self._terrain_showing() or self._terrain_count == 0:
            return
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        self._terrain_vao.bind()
        if self._terrain_texture is not None:
            self._program.setUniformValue(self._loc_use_tex, 1)
            self._terrain_texture.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._terrain_count)
            self._terrain_texture.release(0)
            self._program.setUniformValue(self._loc_use_tex, 0)
        else:
            self._set_color(0.55, 0.60, 0.52, 1.0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._terrain_count)
        self._terrain_vao.release()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

    # ---- Photogrammetric survey (Track G, G6) ------------------------------

    def _photo_showing(self) -> bool:
        m = getattr(self.scene, "photo_mesh", None)
        if m is None or not getattr(m, "visible", False) or self._photo_count == 0:
            return False
        # Its own switch AND its layer, the way a Group works: an entity can be
        # hidden individually or by the layer it carries.
        return self.scene.entity_visible(m)

    def max_texture_size(self) -> int:
        """The driver's ``GL_MAX_TEXTURE_SIZE`` — the hard ceiling for an atlas.

        Queried rather than assumed: ODM routinely emits 24576px sheets, which
        no current GPU accepts (this machine's Radeon 780M reports 16384), and
        an oversized upload fails outright instead of degrading.
        """
        if self._gl is None:
            return 4096                      # conservative until GL is up
        self.makeCurrent()
        try:
            value = self._gl.glGetIntegerv(GL_MAX_TEXTURE_SIZE)
        finally:
            self.doneCurrent()
        try:
            value = int(value[0] if hasattr(value, "__len__") else value)
        except (TypeError, ValueError):
            return 4096
        return value if value > 0 else 4096

    def upload_photo_mesh(self, mesh, images=None) -> None:
        """Upload a :class:`~georef.photomesh.PhotoMesh` and its atlases.

        ``images`` maps a material index → already-loaded ``QImage`` (the reader
        is slow enough that the caller does it off the GUI thread); anything
        missing simply draws untextured rather than blocking here.
        """
        if mesh is None or mesh.triangle_count == 0:
            self.release_photo_textures()
            self._photo_count = 0
            self.update()
            return

        import numpy as np

        self.makeCurrent()
        try:
            # Inside makeCurrent: destroying a QOpenGLTexture without a current
            # context leaks it and prints "Texture has not been destroyed".
            self._release_photo_textures_unsafe()
            # Expand indexed triangles to the flat pos+uv layout the shared
            # VAO expects. Vectorised: the terrain's per-vertex Python loop is
            # fine for a 180x180 grid and hopeless for 362k triangles.
            tri = mesh.triangles
            pos = mesh.vertices[tri]                     # (M, 3, 3)
            uv = mesh.uvs[tri]                           # (M, 3, 2)
            data = np.concatenate([pos, uv], axis=2).astype(np.float32).tobytes()
            self._photo_vbo.bind()
            self._photo_vbo.allocate(data, len(data))
            self._photo_vbo.release()
            self._photo_count = int(tri.shape[0]) * 3

            # Materials are contiguous triangle runs, so each becomes one
            # glDrawArrays over its slice of the same buffer.
            images = images or {}
            for index, material in enumerate(mesh.materials):
                texture = None
                image = images.get(index)
                if image is not None and not image.isNull():
                    texture = QOpenGLTexture(image)
                    texture.setWrapMode(QOpenGLTexture.ClampToEdge)
                    texture.setMinificationFilter(QOpenGLTexture.LinearMipMapLinear)
                    texture.setMagnificationFilter(QOpenGLTexture.Linear)
                self._photo_textures.append(texture)
                self._photo_ranges.append(
                    (material.start * 3, material.count * 3, texture))
        finally:
            self.doneCurrent()
        self.update()

    def release_photo_textures(self) -> None:
        """Drop the survey's atlases (closing a document, or importing another).

        Half a gigabyte of VRAM is worth freeing eagerly rather than waiting for
        Qt to notice at teardown — when there is no current context left and the
        textures leak with a warning instead.
        """
        if not self._photo_textures:
            self._photo_ranges = []
            return
        self.makeCurrent()
        try:
            self._release_photo_textures_unsafe()
        finally:
            self.doneCurrent()

    def _release_photo_textures_unsafe(self) -> None:
        """Destroy the atlases. The caller must hold a current GL context."""
        for texture in self._photo_textures:
            if texture is not None:
                texture.destroy()
        self._photo_textures = []
        self._photo_ranges = []

    def _render_photo_mesh(self) -> None:
        if not self._photo_showing():
            return
        # Same polygon offset as the terrain: the survey is the ground, and
        # traced lines drawn on it must win the depth fight.
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        self._photo_vao.bind()
        for first, count, texture in self._photo_ranges:
            if count <= 0:
                continue
            if texture is not None:
                self._program.setUniformValue(self._loc_use_tex, 1)
                texture.bind(0)
                self._gl.glDrawArrays(GL_TRIANGLES, first, count)
                texture.release(0)
                self._program.setUniformValue(self._loc_use_tex, 0)
            else:
                # Untextured run (atlas missing or still loading): neutral clay
                # so it reads as "there is geometry here", not as a hole.
                self._set_color(0.62, 0.60, 0.56, 1.0)
                self._gl.glDrawArrays(GL_TRIANGLES, first, count)
        self._photo_vao.release()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

    def _ensure_tile_geometry(self, layer, datum):
        """Build the base-map tile quad VBO **once** for the current capture
        patches (not per frame), returning ``[(x, y, vert_start), ...]``. The
        capture is static, so a strip of many tiles still draws fast — each
        frame just binds textures and draws slices; no per-tile re-allocation."""
        key = (id(datum), tuple(layer.patches), layer.zoom, layer.source.id)
        cache = getattr(self, "_tile_geom", None)
        if cache is not None and cache[0] == key:
            return cache[1]
        raw = array("f")
        runs = []
        for (x, y) in layer.flat_tiles(datum):
            start = len(raw) // 5
            for pos, (u, v) in layer.quad_local(datum, x, y):
                raw.extend([pos.x(), pos.y(), pos.z(), u, v])
            runs.append((x, y, start))
        self._tile_quad_vbo.bind()
        self._tile_quad_vbo.allocate(raw.tobytes(), len(raw) * 4 or 4)
        self._tile_quad_vbo.release()
        self._tile_geom = (key, runs)
        return runs

    # Sky (top) and ground (bottom) backdrop colours — subtle two-tone, SketchUp.
    _SKY_RGB = (0.925, 0.935, 0.945)
    _GROUND_RGB = (0.815, 0.820, 0.815)

    def _horizon_ndc_y(self, mvp) -> float:
        """Screen-space NDC y of the horizon (the ground plane at infinity),
        from the camera orientation. Returns a value that may exceed ±1 when the
        horizon is off-screen (looking straight down = all ground)."""
        eye = self.camera.eye()
        fwd = self.camera.target - eye
        # Horizontal component of the view direction → its vanishing point.
        dh = QVector3D(fwd.x(), fwd.y(), 0.0)
        if dh.length() < 1e-5:
            # Looking straight down/up: no horizon on screen.
            return 2.0 if fwd.z() < 0 else -2.0
        dh = dh.normalized()
        # A point very far along the horizontal heading, at eye height: as the
        # distance → ∞ it converges to the horizon, so it stays put on zoom.
        far = eye + dh * 1.0e6
        clip = mvp.map(QVector4D(far.x(), far.y(), far.z(), 1.0))
        if abs(clip.w()) < 1e-9:
            return 2.0 if fwd.z() < 0 else -2.0
        return clip.y() / clip.w()

    #: NDC span over which each half of the backdrop completes its ramp.
    _SKY_GRAD_SPAN = 1.4
    _GROUND_GRAD_SPAN = 0.9

    @staticmethod
    def _sky_gradient(sky_rgb, ground_rgb, hy):
        """Corner colours of the backdrop gradient: the style's sky tone at
        the zenith and ground tone underfoot, both hazed toward white at the
        horizon (atmosphere — the one-colour input stays the one the user
        picked). Computed against the UNCLAMPED horizon ``hy``, so a pitched
        camera sees the right slice of the ramp (all zenith when looking up,
        all ground when looking down). Returns ``(sky_bottom, sky_top,
        ground_top, ground_bottom, horizon_line)``; the ramps are linear in
        NDC y, so colouring only the quad corners is exact."""
        def mix(a, b, t):
            return (a[0] + (b[0] - a[0]) * t,
                    a[1] + (b[1] - a[1]) * t,
                    a[2] + (b[2] - a[2]) * t)

        white = (1.0, 1.0, 1.0)
        sky_h = mix(sky_rgb, white, 0.55)
        gnd_h = mix(ground_rgb, white, 0.30)

        def sky_at(y):
            t = min(1.0, max(0.0, (y - hy) / Viewport._SKY_GRAD_SPAN))
            return mix(sky_h, sky_rgb, t)

        def gnd_at(y):
            t = min(1.0, max(0.0, (hy - y) / Viewport._GROUND_GRAD_SPAN))
            return mix(gnd_h, ground_rgb, t)

        y0 = max(-1.0, min(1.0, hy))
        line = mix(mix(sky_h, gnd_h, 0.5), (0.0, 0.0, 0.0), 0.12)
        return sky_at(y0), sky_at(1.0), gnd_at(y0), gnd_at(-1.0), line

    def _draw_sky(self, mvp) -> None:
        """Sky above the horizon and ground below, each a vertical gradient
        (style tones hazed toward the horizon — see ``_sky_gradient``), with
        a subtle horizon line where they meet. Per-vertex colours; GL
        interpolates per pixel. The class constants ``_SKY_RGB`` /
        ``_GROUND_RGB`` are the historical defaults, kept as fallbacks."""
        style = getattr(self, "_frame_style", None)
        sky_rgb = tuple(getattr(style, "sky_color", None)
                        or self._SKY_RGB)[:3]
        ground_rgb = tuple(getattr(style, "ground_color", None)
                           or self._GROUND_RGB)[:3]
        hy_raw = self._horizon_ndc_y(mvp)
        hy = max(-1.0, min(1.0, hy_raw))
        c_sky0, c_sky1, c_gnd0, c_gnd1, c_line = self._sky_gradient(
            sky_rgb, ground_rgb, hy_raw)
        self._program.setUniformValue(self._loc_mvp, QMatrix4x4())  # identity/NDC
        self._gl.glDisable(GL_DEPTH_TEST)
        self._gl.glDepthMask(GL_FALSE)

        def gquad(y0, y1, c0, c1):
            data = array("f", [-1, y0, 0, *c0, 1, y0, 0, *c0, 1, y1, 0, *c1,
                               -1, y0, 0, *c0, 1, y1, 0, *c1, -1, y1, 0, *c1])
            self._sky_grad_vbo.bind()
            self._sky_grad_vbo.allocate(data.tobytes(), len(data) * 4)
            self._sky_grad_vbo.release()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)

        self._sky_grad_vao.bind()
        self._program.setUniformValue(self._loc_use_vcolor, 1)
        if hy < 1.0:
            gquad(hy, 1.0, c_sky0, c_sky1)
        if hy > -1.0:
            gquad(-1.0, hy, c_gnd1, c_gnd0)
        self._program.setUniformValue(self._loc_use_vcolor, 0)
        self._sky_grad_vao.release()
        # A subtle horizon line where sky meets ground (SketchUp), in a tone
        # derived from the two haze colours so custom skies keep it legible.
        if -1.0 < hy < 1.0:
            line = array("f", [-1.0, hy, 0.0, 1.0, hy, 0.0])
            self._sky_vao.bind()
            self._sky_vbo.bind()
            self._sky_vbo.allocate(line.tobytes(), len(line) * 4)
            self._sky_vbo.release()
            self._set_color(*c_line, 1.0)
            self._gl.glDrawArrays(GL_LINES, 0, 2)
            self._sky_vao.release()
        self._gl.glEnable(GL_DEPTH_TEST)
        self._gl.glDepthMask(GL_TRUE)

    # ---- Sun shadows (core/sun.py) ------------------------------------------
    _SHADOW_MAP_SIZE = 2048
    #: SketchUp's documented rule: materials under 70 % opacity cast no
    #: shadow — the sun passes through glass.
    _SHADOW_OPACITY_MIN = 0.7

    def _sun_dir_now(self):
        """Unit vector toward the sun for the scene's shadow settings —
        ``None`` when there is nothing to cast (shadows off, kill switch
        ``INGETRAZO_NO_SHADOWS``, a sheet plan style, night, or a date that
        does not exist in a hand-edited file)."""
        import os
        if os.environ.get("INGETRAZO_NO_SHADOWS"):
            return None
        if self.plano_style is not None:
            return None
        sh = getattr(self.scene, "shadows", None)
        if sh is None or not getattr(sh, "enabled", False):
            return None
        import datetime as _dt
        from core import sun
        datum = getattr(self.scene, "georef", None)
        lat = getattr(datum, "lat", None)
        lon = getattr(datum, "lon", None)
        if lat is None or lon is None:
            lat, lon = sun.DEFAULT_LAT, sun.DEFAULT_LON
        try:
            when = sh.when_utc(lon, year=_dt.date.today().year)
        except ValueError:
            return None
        return sun.sun_direction(lat, lon, when)

    @staticmethod
    def _light_vp(d, lo, hi):
        """The sun's orthographic view-projection fitted around the model —
        and around the z=0 ground patch that receives. Ortho keeps the
        packed depth linear."""
        cx = (lo.x() + hi.x()) / 2.0
        cy = (lo.y() + hi.y()) / 2.0
        loz = min(lo.z(), 0.0)
        cz = (loz + hi.z()) / 2.0
        # Half-diagonal of the dominant extent (≤ 0.87×max side), with
        # margin so rims never clip against the map's edge.
        r = max(hi.x() - lo.x(), hi.y() - lo.y(), hi.z() - loz, 2.0) * 0.87
        r *= 1.25
        center = QVector3D(cx, cy, cz)
        eye = center + QVector3D(d[0], d[1], d[2]) * (r * 2.0)
        up = (QVector3D(0.0, 0.0, 1.0) if abs(d[2]) < 0.95
              else QVector3D(0.0, 1.0, 0.0))
        view = QMatrix4x4()
        view.lookAt(eye, center, up)
        proj = QMatrix4x4()
        # Eye sits 2r from center; everything lives within r of it.
        proj.ortho(-r, r, -r, r, r * 0.5, r * 3.5)
        return proj * view

    def _ensure_shadow_map(self):
        """Build or reuse the packed-depth shadow map. Camera-independent:
        keyed by geometry version + sun + cut + bounds, so orbit and zoom
        REUSE it — only an edit, the clock or the section rebuilds."""
        d = self._sun_dir_now()
        self._frame_sun = d
        if d is None:
            self._shadow_vp = None
            return None
        lo, hi = self.scene.bounds()
        if lo is None:
            self._shadow_vp = None
            return None
        clip = getattr(self, "_clip_vec", None)
        key = (self.scene.version, id(self.scene.mesh),
               getattr(self, "_preview_epoch", 0),
               tuple(round(v, 4) for v in d),
               None if clip is None else (round(clip.x(), 4),
                                          round(clip.y(), 4),
                                          round(clip.z(), 4),
                                          round(clip.w(), 4)),
               round(lo.x(), 2), round(lo.y(), 2), round(lo.z(), 2),
               round(hi.x(), 2), round(hi.y(), 2), round(hi.z(), 2))
        if self._shadow_fbo is not None and self._shadow_key == key:
            return self._shadow_fbo
        if self._shadow_fbo is None:
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            self._shadow_fbo = QOpenGLFramebufferObject(
                self._SHADOW_MAP_SIZE, self._SHADOW_MAP_SIZE, fmt)
        vp = self._light_vp(d, lo, hi)
        self._render_shadow_map(vp)
        self._shadow_key = key
        self._shadow_vp = vp
        return self._shadow_fbo

    def _render_shadow_map(self, light_vp) -> None:
        """Depth-from-the-sun pass: every caster — the consolidated face
        VBOs plus ALL instanced components (no camera culling here: an
        off-screen tree still throws its shadow into the frame) — drawn
        with the depth program into the packed-depth FBO. The active
        section cut applies, so severed geometry does not cast. The caller
        restores the scene FBO/program bindings this pass borrows."""
        size = self._SHADOW_MAP_SIZE
        fbo = self._shadow_fbo
        fbo.bind()
        self._gl.glViewport(0, 0, size, size)
        self._gl.glClearColor(1.0, 1.0, 1.0, 1.0)
        self._gl.glClearDepthf(1.0)
        self._gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self._gl.glEnable(GL_DEPTH_TEST)
        self._gl.glDepthFunc(GL_LEQUAL)
        self._gl.glDepthMask(GL_TRUE)
        self._gl.glDisable(GL_BLEND)
        prog = self._depth_program
        prog.bind()
        prog.setUniformValue(self._loc_d_mvp, light_vp)
        prog.setUniformValue(self._loc_d_use_tex, 0)
        clip = getattr(self, "_clip_vec", None)
        if clip is not None:
            prog.setUniformValue(self._loc_d_clip_plane, clip)
            prog.setUniformValue(self._loc_d_clip_enable, 1)
            self._gl.glEnable(GL_CLIP_DISTANCE0)
        else:
            prog.setUniformValue(self._loc_d_clip_enable, 0)
        # Identity on the instanced-matrix generic attributes for the
        # non-instanced draws (same reset the main pass does per frame).
        for i, row in enumerate(((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0),
                                 (0.0, 0.0, 1.0, 0.0),
                                 (0.0, 0.0, 0.0, 1.0))):
            self._gl.glVertexAttrib4f(3 + i, *row)
        if self._faces_count > 0 or self._tcol_runs:
            self._faces_vao.bind()
            if self._faces_count > 0:
                self._gl.glDrawArrays(GL_TRIANGLES, 0, self._faces_count)
            # SketchUp's translucency rule: under 70 % opacity a material
            # casts NO shadow (glass lets the sun through); at or above it,
            # it casts like a solid.
            for a, _fc, start, count in self._tcol_runs:
                if a >= self._SHADOW_OPACITY_MIN:
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
            self._faces_vao.release()
        if self._tex_runs or self._ttex_runs:
            # Textured faces cast with their ALPHA CUTOUT: a chain-link
            # fence throws its weave, a leaf card its silhouette (texture
            # unavailable = solid fallback). Translucent runs follow the
            # 70 % rule above.
            self._tex_faces_vao.bind()
            prog.setUniformValue(self._loc_d_tex, 0)

            def _cast_run(path, start, count):
                tex = self._get_texture(path)
                if tex is not None:
                    prog.setUniformValue(self._loc_d_use_tex, 1)
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                    tex.release(0)
                else:
                    prog.setUniformValue(self._loc_d_use_tex, 0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, count)

            for (path, _shade), start, count in self._tex_runs:
                _cast_run(path, start, count)
            for (path, _shade), a, _fc, start, count in self._ttex_runs:
                if a >= self._SHADOW_OPACITY_MIN:
                    _cast_run(path, start, count)
            prog.setUniformValue(self._loc_d_use_tex, 0)
            self._tex_faces_vao.release()
        saved = getattr(self, "_frame_planes", None)
        self._frame_planes = None      # gather WITHOUT camera culling
        try:
            by_proto = self._gather_instanced()
        finally:
            self._frame_planes = saved
        extra = self.context().extraFunctions()
        for mesh, groups in by_proto.values():
            entry = self._ensure_proto_draw(mesh)
            n = self._update_inst_matrices(entry, groups)
            prog.bind()                # entry building binds the main program
            if entry["vcol_count"]:
                entry["vcol_vao"].bind()
                extra.glDrawArraysInstanced(
                    GL_TRIANGLES, 0, entry["vcol_count"], n)
                entry["vcol_vao"].release()
            if entry["tex_runs"]:
                # Alpha-cutout casting for instances too — the hedge's
                # leaves dapple instead of throwing solid slabs.
                entry["tex_vao"].bind()
                prog.setUniformValue(self._loc_d_tex, 0)
                for (path, _shade), s0, cnt in entry["tex_runs"]:
                    tex = self._get_texture(path)
                    if tex is not None:
                        prog.setUniformValue(self._loc_d_use_tex, 1)
                        tex.bind(0)
                        extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                        tex.release(0)
                    else:
                        prog.setUniformValue(self._loc_d_use_tex, 0)
                        extra.glDrawArraysInstanced(GL_TRIANGLES, s0, cnt, n)
                prog.setUniformValue(self._loc_d_use_tex, 0)
                entry["tex_vao"].release()
        # Billboard people cast their SILHOUETTE, as a quad turned toward
        # the sun — a camera-facing caster would swing its shadow while the
        # camera orbits (SketchUp's face-me "shadows face sun"). Vector-art
        # and mesh face-me stay non-casting (documented deferral).
        sun = getattr(self, "_frame_sun", None)
        bbs = [g for g in self._placements()
               if getattr(g, "billboard", False) is True
               and self.scene.entity_visible(g)]
        if sun is not None and bbs:
            face = QVector3D(sun[0], sun[1], 0.0)
            data = array("f")
            draws = []
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            for g in bbs:
                quad = self._billboard_quad(g, face_dir=face)
                if quad is None or not quad[1]:
                    continue
                corners, path = quad
                start = len(data) // 5
                for idx in (0, 1, 2, 0, 2, 3):
                    c = corners[idx]
                    u, v = uvs[idx]
                    data.extend([c.x(), c.y(), c.z(), u, v])
                draws.append((path, start))
            if draws:
                raw = data.tobytes()
                self._shadow_bb_vbo.bind()
                self._shadow_bb_vbo.allocate(raw, len(raw))
                self._shadow_bb_vbo.release()
                prog.bind()
                prog.setUniformValue(self._loc_d_use_tex, 1)
                prog.setUniformValue(self._loc_d_tex, 0)
                self._shadow_bb_vao.bind()
                for path, start in draws:
                    tex = self._get_texture(path)
                    if tex is None:
                        continue
                    tex.bind(0)
                    self._gl.glDrawArrays(GL_TRIANGLES, start, 6)
                    tex.release(0)
                self._shadow_bb_vao.release()
                prog.setUniformValue(self._loc_d_use_tex, 0)
        if clip is not None:
            self._gl.glDisable(GL_CLIP_DISTANCE0)
        prog.release()
        fbo.release()
        self._gl.glEnable(GL_BLEND)

    def _draw_shadow_ground(self, style) -> None:
        """The on-ground shadow catcher: a world plane just under z=0 that
        draws ONLY the shadow — translucent black where the sun is blocked,
        fully transparent where it is not, so the plane itself has no
        visible colour or edges (SketchUp's on-ground shadows). Skipped
        over the map, terrain and photo mesh, which bring their own ground;
        depth writes OFF so below-ground geometry still draws over it and a
        real floor AT z=0 never z-fights."""
        if (self._base_map_showing() or self._terrain_showing()
                or self._photo_showing()):
            return
        lo, hi = self.scene.bounds()
        if lo is None:
            return
        cx = (lo.x() + hi.x()) / 2.0
        cy = (lo.y() + hi.y()) / 2.0
        r = max(hi.x() - lo.x(), hi.y() - lo.y(), 20.0) * 1.5
        z = -0.005
        x0, x1, y0, y1 = cx - r, cx + r, cy - r, cy + r
        data = array("f", [x0, y0, z, x1, y0, z, x1, y1, z,
                           x0, y0, z, x1, y1, z, x0, y1, z])
        self._ground_vbo.bind()
        self._ground_vbo.allocate(data.tobytes(), len(data) * 4)
        self._ground_vbo.release()
        self._program.setUniformValue(self._loc_shadow_enable, 1)
        self._program.setUniformValue(self._loc_shadow_overlay, 1)
        self._gl.glDepthMask(GL_FALSE)
        self._ground_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
        self._ground_vao.release()
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue(self._loc_shadow_overlay, 0)

    def _render_tiles(self) -> None:
        if self._terrain_showing():
            return  # the 3D terrain replaces the flat map
        layer = getattr(self.scene, "tile_layer", None)
        datum = getattr(self.scene, "georef", None)
        if layer is None or datum is None or not getattr(layer, "visible", False):
            return
        try:
            runs = self._ensure_tile_geometry(layer, datum)
        except Exception:
            return
        if not runs:
            return
        # Budget new texture uploads this frame (see _tile_texture).
        self._tex_budget = self._TEX_PER_FRAME
        self._tex_deferred = False
        self._program.setUniformValue(self._loc_use_tex, 1)
        self._gl.glDepthMask(GL_FALSE)
        self._tile_quad_vao.bind()
        for (x, y, start) in runs:
            tex = self._tile_texture(layer, x, y)
            if tex is None:
                continue
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, start, 6)
            tex.release(0)
        self._tile_quad_vao.release()
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue(self._loc_use_tex, 0)
        if self._tex_deferred:            # more tiles to upload — schedule a frame
            self.update()

    # ---- Dynamic uploads ----------------------------------------------------
    def notify_scene_changed(self) -> None:
        """Force a redraw and emit the version-changed signal.

        Use this when an outside system (load, undo, redo) has mutated the
        scene and wants subscribers (title-bar dirty flag, etc.) to react
        without waiting for the next paint.
        """
        self.sceneVersionChanged.emit(self.scene.version)
        self.update()

    def begin_groups_preview(self, groups=(), external: bool = False) -> None:
        """Enter a groups-only transform preview: the per-version caches
        freeze, the moving groups leave the consolidated VBOs (one resync)
        and their chunk arrays upload ONCE to scratch VBOs that paintGL
        draws with a translated MVP — a drag frame touches no arrays at
        all. SketchUp-grade group dragging on a 230k-face group.

        ``external=True`` previews OFF-scene template groups (Paste's
        clipboard): same scratch upload, but nothing leaves the consolidated
        VBOs and the caches stay live — no freeze, no resyncs."""
        # A component keeps placements inside itself, and THOSE hold the
        # geometry: previewing only the top-level group uploaded an empty
        # scratch copy while the children kept drawing, frozen, at the old
        # spot — the hedge stood still through the whole drag and teleported
        # on release (Marco: "cuando roto o muevo tiene laj bastante").
        movers: list = []
        for g in groups:
            self._expand_placements(g, movers)
        groups = movers
        self._preview_external = external
        if not external:
            self._frozen_cache_version = self.scene.version
            self._edges_version = -1      # one resync WITHOUT the movers
        self._preview_groups = set(map(id, groups))
        self._preview_epoch = getattr(self, "_preview_epoch", 0) + 1
        self._preview_offset = QVector3D(0.0, 0.0, 0.0)
        if not self._preview_groups:
            return
        self.makeCurrent()
        try:
            if getattr(self, "_pv_edges_vao", None) is None:
                self._pv_edges_vao, self._pv_edges_vbo = self._create_dynamic()
                self._pv_vcol_vao, self._pv_vcol_vbo = \
                    self._create_dynamic_vcol()
                self._pv_tex_vao, self._pv_tex_vbo = self._create_dynamic_uv()
            edge_parts: list = []
            vcol_parts: list = []
            tex_parts: dict = {}
            for g in groups:
                if getattr(g, "billboard", False):
                    # Face-me figures preview through their OWN pass (the
                    # anchor rides the preview transform): their raw mesh
                    # quad in the scratch VBOs showed a swimming texture.
                    continue
                ch = self._group_chunk(g)
                if ch["edges"]:
                    edge_parts.append(ch["edges"])
                if ch["vcol"]:
                    vcol_parts.append(ch["vcol"])
                for path, raw in ch["by_texture"].items():
                    tex_parts.setdefault(path, []).append(raw)
            raw = b"".join(edge_parts)
            self._pv_edges_vbo.bind()
            self._pv_edges_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
            self._pv_edges_vbo.release()
            self._pv_edges_count = len(raw) // 12
            raw = b"".join(vcol_parts)
            self._pv_vcol_vbo.bind()
            self._pv_vcol_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
            self._pv_vcol_vbo.release()
            self._pv_vcol_count = len(raw) // 24
            runs: list = []
            blobs: list = []
            off = 0
            for path, parts in tex_parts.items():
                blob = b"".join(parts)
                runs.append((path, off // 20, len(blob) // 20))
                blobs.append(blob)
                off += len(blob)
            raw = b"".join(blobs)
            self._pv_tex_vbo.bind()
            self._pv_tex_vbo.allocate(raw or b"\0" * 24, max(len(raw), 24))
            self._pv_tex_vbo.release()
            self._pv_tex_runs = runs
        finally:
            self.doneCurrent()

    def end_groups_preview(self) -> None:
        if not getattr(self, "_preview_external", False):
            self._frozen_cache_version = None
            self._edges_version = -1      # resync with the movers back in
        else:
            # Off-scene templates never left the consolidated VBOs (nothing
            # to resync) and their scratch chunks are one-shot — drop them
            # so a big clipboard doesn't pin megabytes of arrays.
            scene_ids = {id(g) for g in self._placements()}
            for cache_name in ("_group_chunks", "_inst_chunks"):
                cache = getattr(self, cache_name, None)
                if cache:
                    for gid in self._preview_groups - scene_ids:
                        cache.pop(gid, None)
        self._preview_external = False
        self._preview_groups = set()
        self._preview_epoch = getattr(self, "_preview_epoch", 0) + 1
        self._preview_offset = QVector3D(0.0, 0.0, 0.0)
        self._preview_matrix = None
        self._pv_edges_count = 0
        self._pv_vcol_count = 0
        self._pv_tex_runs = []

    def set_groups_preview_offset(self, delta: QVector3D) -> None:
        self._preview_offset = QVector3D(delta)
        self._preview_matrix = None
        self.update()

    def set_groups_preview_matrix(self, m) -> None:
        """Full-matrix variant (Rotate/Scale previews): the scratch copies
        draw through ``m`` — same zero-churn frame as the translation."""
        self._preview_matrix = QMatrix4x4(m)
        self.update()

    def _draw_groups_preview(self, mvp) -> None:
        """Draw the frozen scratch copies of the moving groups at the
        current preview offset: one translated MVP, zero array churn."""
        if not getattr(self, "_preview_groups", None):
            return
        m = getattr(self, "_preview_matrix", None)
        if m is None:
            m = QMatrix4x4()
            off = getattr(self, "_preview_offset", None)
            if off is not None:
                m.translate(off)
        self._program.setUniformValue(self._loc_mvp, mvp * m)
        n = getattr(self, "_pv_vcol_count", 0)
        if n:
            self._program.setUniformValue(self._loc_use_vcolor, 1)
            self._pv_vcol_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, n)
            self._pv_vcol_vao.release()
            self._program.setUniformValue(self._loc_use_vcolor, 0)
        runs = getattr(self, "_pv_tex_runs", None)
        if runs:
            self._program.setUniformValue(self._loc_use_tex, 1)
            self._pv_tex_vao.bind()
            for key, start, count in runs:
                # Chunk texture runs key by (path, shade) tuples (bare path
                # when unshaded) — passing the tuple to QImage raised inside
                # paintGL and KILLED the whole preview frame ("moving shows
                # nothing until release", flatpak report).
                path, shade = key if isinstance(key, tuple) else (key, 1.0)
                tex = self._get_texture(path)
                if tex is None:
                    continue
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                self._program.setUniformValue(
                    self._loc_hard_cutout,
                    1 if getattr(tex, "_cutout", False) else 0)
                tex.bind(0)
                self._gl.glDrawArrays(GL_TRIANGLES, start, count)
                tex.release(0)
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._program.setUniformValue(self._loc_hard_cutout, 0)
            self._pv_tex_vao.release()
            self._program.setUniformValue(self._loc_use_tex, 0)
        n = getattr(self, "_pv_edges_count", 0)
        if n:
            self._set_color(1.0, 0.45, 0.0, 1.0)   # selection orange: moving
            self._pv_edges_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, n)
            self._pv_edges_vao.release()
        self._program.setUniformValue(self._loc_mvp, mvp)

    def _newell_of(self, face):
        """The face's raw Newell vector, memoised per scene version — ONE
        computation feeds normal, area and triangulation (each used to pay
        its own on an exploded import's edit frame)."""
        memo = getattr(self, "_newell_memo", None)
        if memo is None or memo[0] != _cache_ver(self):
            memo = self._newell_memo = (_cache_ver(self), {})
        hit = memo[1].get(id(face))
        if hit is None or hit[0] is not face:
            hit = memo[1][id(face)] = (face, face._newell())
        return hit[1]

    def _area_of(self, face) -> float:
        if not hasattr(face, "loop"):
            return face.area()          # preview face (core.geometry)
        if len(face.loop) < 3:
            return 0.0
        return 0.5 * self._newell_of(face).length()

    def _tris_of(self, face):
        """``face.triangulate()`` memoised per scene version: one edit frame
        triangulates every loose face for the colour VBOs, the textured
        VBOs AND the pick index — 3x the earcut/_newell cost on an exploded
        import. The memo holds the face itself so a recycled id() can never
        alias, and drops wholesale on the next version bump."""
        if not hasattr(face, "loop"):
            return face.triangulate()   # preview face: own earcut, no memo
        memo = getattr(self, "_tri_memo", None)
        if memo is None or memo[0] != _cache_ver(self):
            memo = self._tri_memo = (_cache_ver(self), {})
        hit = memo[1].get(id(face))
        if hit is None or hit[0] is not face:
            hit = memo[1][id(face)] = (
                face, face.triangulate(self._normal_of(face)))
        return hit[1]

    def _normal_of(self, face):
        """``face.normal()`` memoised per scene version (see _tris_of):
        the shading of every loose face recomputes the Newell normal 3-4
        times per edit frame otherwise. Tool PREVIEW faces (core.geometry,
        no ``loop``) take their own methods unmemoised — fresh objects every
        frame; treating them as mesh faces crashed EVERY paint of a loose
        paste preview (nothing followed the cursor)."""
        if not hasattr(face, "loop"):
            return face.normal()
        if len(face.loop) < 3:
            return QVector3D(0.0, 0.0, 1.0)
        n = self._newell_of(face)
        return (n.normalized() if n.length() > 1e-9
                else QVector3D(0.0, 0.0, 1.0))

    def _upload_vbo(self, vbo, slot: str, parts, empty: int = 24) -> int:
        """Put ``b"".join(parts)`` in ``vbo``, re-sending only the tail that
        actually changed. Returns the total byte length.

        Every scene-version bump re-uploaded each buffer whole, so an edit
        inside one group re-sent the entire model each drag frame — on
        piscina.igz that is ~25 MB of edges plus more of faces, and the
        telemetry read ``sync=197ms`` against ``faces=11ms edges=7ms``: the
        frame was the upload, not the drawing.

        Parts that compare equal form a prefix the GPU already holds. Chunk
        buffers are cached objects, so that comparison is an identity hit for
        every group that did not change; the freshly built loose block falls
        back to a bytes compare, which is memcmp and still an order of
        magnitude under the transfer it saves. The buffer is over-allocated so
        a growing tail usually fits without a reallocation (which would
        discard the prefix along with everything else)."""
        raw = b"".join(parts)
        total = len(raw)
        prev = self._vbo_parts.get(slot)
        keep = 0
        cap = prev[1] if prev is not None else 0
        if prev is not None and total <= cap:
            for a, b in zip(parts, prev[0]):
                if a is b or a == b:
                    keep += len(a)
                else:
                    break
            keep = min(keep, total)
        vbo.bind()
        if total > cap:
            cap = max(int(total * 1.25) + 4096, empty)
            vbo.allocate(cap)      # reserve; a realloc keeps no contents
            keep = 0
        if total > keep:
            vbo.write(keep, raw[keep:], total - keep)
        vbo.release()
        self._vbo_parts[slot] = (list(parts), cap)
        return total

    def _sync_edges(self) -> None:
        if _cache_ver(self) == self._edges_version:
            return
        _st0 = _time_mod.perf_counter() if _PERF else 0.0

        # The scene changed: purge hover/selection references to entities that
        # no longer exist, or deleted geometry keeps ghost-rendering (blue
        # hover / orange selection) until the mouse moves or a click replaces
        # the selection. Renderer-level guarantee — holds no matter which
        # command forgot to discard. Membership is checked per candidate
        # (identity scans in C) instead of materialising 300k-entity sets;
        # a huge candidate list falls back to the set walk.
        hover = self._hover_entity
        cands = [hover] if isinstance(hover, (Edge, Face)) else []
        cands += [s for s in self.scene.selection
                  if isinstance(s, (Edge, Face))]
        if cands:
            if len(cands) > 64:
                # Selected/hovered Edge/Face refs only ever point into the
                # active mesh (loose, or the group being edited) — the old
                # render_edges()/render_faces() sets walked EVERY group's
                # entities (~283k) per edit frame after an explode.
                alive_e: set = set(map(id, self.scene.mesh.edges))
                alive_f: set = set(map(id, self.scene.mesh.faces))

                def alive(ent):
                    return id(ent) in (alive_e if isinstance(ent, Edge)
                                       else alive_f)
            else:
                gmeshes = [g.mesh for g in self._placements()
                           if self.scene.entity_visible(g)
                           and not getattr(g, "billboard", False)]

                def alive(ent):
                    if isinstance(ent, Edge):
                        if ent in self.scene.loose_mesh.edges:
                            return self.scene.entity_visible(ent)
                        return any(ent in gm.edges for gm in gmeshes)
                    if ent in self.scene.loose_mesh.faces:
                        return self.scene.entity_visible(ent)
                    return any(ent in gm.faces for gm in gmeshes)

            if isinstance(hover, (Edge, Face)) and not alive(hover):
                self._hover_entity = None
            for s in [s for s in self.scene.selection
                      if isinstance(s, (Edge, Face)) and not alive(s)]:
                self.scene.selection.discard(s)

        # Inside a group, the surroundings can fade out or leave the frame
        # altogether (SketchUp's Model Info ▸ Components). Hidden means gone
        # from the VBOs, not merely skipped at draw time — that is what makes
        # it the fast mode on a heavy import.
        hide_rest = self._rest_is_hidden()
        # Vertex offset where the edited group's own block starts; everything
        # before it is context. ``None`` = no subject (not editing, or the
        # context is hidden and there is nothing to separate it from).
        self._edit_split_e = None
        self._edit_split_f = None
        # Hard edges: loose ones rebuilt fresh, group ones from cached chunks
        # (composition mirrors scene.render_edges()).
        all_loose = array("f")
        if not hide_rest:
            for e in self.scene.loose_mesh.edges:
                if (not self.scene.entity_visible(e)
                        or getattr(e, "soft", False)
                        or getattr(e, "hidden", False)):
                    continue  # hidden layer / curve segment (reads smooth)
                all_loose.extend([
                    e.a.x(), e.a.y(), e.a.z(),
                    e.b.x(), e.b.y(), e.b.z(),
                ])
        edge_parts = [all_loose.tobytes()]
        # Per-chunk draw spans (vertices) for frustum culling: the loose
        # block always draws (bbox None); each group's block carries its
        # chunk's world AABB.
        edge_spans = [(None, 0, len(all_loose) // 3)]
        estart = len(all_loose) // 3
        pv = getattr(self, "_preview_groups", None) or ()
        # The group being edited goes LAST, so the surroundings occupy a
        # contiguous head the fade pass can draw in one go (and, since
        # nothing outside the group can change while you are in it, a head
        # that stays put in the buffer).
        placements = self._placements()
        draw_groups = [g for g in placements
                       if not self._draws_in_edit_context(g)]
        if not hide_rest:
            draw_groups = [g for g in placements
                           if self._draws_in_edit_context(g)] + draw_groups
        for g in draw_groups:
            if (self.scene.entity_visible(g) and id(g) not in pv
                    and not getattr(g, "billboard", False)
                    and not self._instanced_eligible(g)):
                if g is self.scene.edit_group:
                    self._edit_split_e = estart
                ch = self._group_chunk(g)
                edge_parts.append(ch["edges"])
                n = len(ch["edges"]) // 12
                edge_spans.append((ch.get("bbox"), estart, n))
                estart += n
        self._edge_spans = edge_spans
        self._edges_count = self._upload_vbo(
            self._edges_vbo, "edges", edge_parts) // 12

        # The selection set is heterogeneous (edges, faces and/or whole
        # groups). A selected GROUP highlights via its cached chunk — walking
        # + re-triangulating a 100k-face imported group froze the app the
        # moment the user clicked it.
        sel_loose = array("f")
        sel_edge_parts = []
        for ent in self.scene.selection:
            if isinstance(ent, Edge):
                sel_loose.extend([ent.a.x(), ent.a.y(), ent.a.z(),
                                  ent.b.x(), ent.b.y(), ent.b.z()])
            elif isinstance(ent, Group):
                if getattr(ent, "billboard", False):
                    # A face-me billboard's mesh quad is NOT what's on screen
                    # (the drawn quad rotates to face the camera every frame)
                    # — tinting it painted a stray plane through the figure.
                    # Its selection cue is the per-frame outline drawn in
                    # _draw_billboard_outlines instead.
                    continue
                if id(ent) in pv:
                    # Mid Move/Rotate drag: the scratch preview draws the
                    # mover WITH its own orange cue at the cursor — tinting
                    # the chunk here left an orange GHOST at the origin
                    # until the commit (user report).
                    continue
                # A selected group reads as its BOUNDING BOX, the way
                # SketchUp shows one — twelve segments instead of the whole
                # object. Highlighting the geometry meant uploading every
                # edge AND a triangle copy of every face on each click: the
                # 230k-face hedge in piscina.igz pushed 416k edges through
                # the selection buffers just to say "this is selected". The
                # box also reads better on a dense group, where an all-orange
                # mass says less than an outline does.
                sel_edge_parts.append(_box_edges(*self._group_obb(ent)))
        self._selected_count = self._upload_vbo(
            self._selected_vbo, "sel_edges",
            [sel_loose.tobytes()] + sel_edge_parts) // 12

        sel_face_loose = array("f")
        for ent in self.scene.selection:
            if isinstance(ent, Face):
                for t0, t1, t2 in ent.triangulate():
                    sel_face_loose.extend([
                        t0.x(), t0.y(), t0.z(),
                        t1.x(), t1.y(), t1.z(),
                        t2.x(), t2.y(), t2.z(),
                    ])
        self._sel_faces_count = self._upload_vbo(
            self._sel_faces_vbo, "sel_faces",
            [sel_face_loose.tobytes()]) // 12

        # Faces: triangulate each face (fan when simple, hole-aware when the
        # face has been divided) into one VBO, but grouped by material colour
        # (attrs["color"], default cream) so each colour is a single draw call
        # with its own uniform. Loose faces rebuild fresh; untouched groups
        # contribute their cached chunk buffers (a 17k-face reference model
        # made every stroke pay a ~1 s re-triangulation otherwise).
        suppressed_faces = self._suppressed_faces
        vcol = array("f")            # loose faces, interleaved pos(3)+rgb(3)
        by_texture: dict = {}        # image path -> interleaved pos+uv array
        # A group with SUPPRESSED faces (a push preview hides the face being
        # extruded) cannot use its cached chunk, so its faces are bucketed one
        # by one — and that output must not land in the loose block at the
        # HEAD of the buffer. There it would be on the context side of the
        # fade split, washing out the very geometry being edited, and it would
        # break the stable prefix the incremental upload rides on. It goes to
        # its own block at the tail instead; ``sink`` is what bucket_face
        # writes through.
        subj_vcol = array("f")
        subj_by_texture: dict = {}
        sink = {"vcol": vcol, "tex": by_texture}
        group_texture: dict = {}     # chunk byte-parts per image path
        face_parts: list = []        # interleaved vcol byte chunks

        tcol_runs: dict = {}         # opacity -> [byte parts] (translucent colour)
        ttex_runs: dict = {}         # (path, opacity) -> [byte parts]
        back_vcol_parts: list = []   # back-side colour override triangles
        back_tex_runs: dict = {}     # (path, shade) -> [byte parts] (back side)
        back_tcol_runs: dict = {}    # opacity -> [parts] (translucent back)
        back_ttex_runs: dict = {}    # ((path, shade), op) -> [parts]
        fcull_vcol_parts: list = []  # front copies culled to the front side

        def bucket_back(face):
            # attrs["back"]: the face is painted DIFFERENTLY on its back side
            # (SketchUp two-sided paint). Emit an override copy that a culled
            # pass shows only from behind. Returns True when the back is
            # TRANSLUCENT — then the front copy must not show from behind
            # (it gets back-face culling), or the two sides would blend.
            back = face.attrs.get("back")
            if not isinstance(back, dict):
                return False
            kind, payload = self._bucket_back_face(face, back)
            if kind == "bvcol":
                back_vcol_parts.append(payload)
            elif kind == "btex":
                back_tex_runs.setdefault(payload[0], []).append(payload[1])
            elif kind == "btcol":
                back_tcol_runs.setdefault(payload[0], []).append(payload[1])
            elif kind == "bttex":
                back_ttex_runs.setdefault(payload[0], []).append(payload[1])
            return kind in ("btcol", "bttex")

        def bucket_face(face):
            if face in suppressed_faces:
                return
            fcull = bucket_back(face)
            tex = face.attrs.get("texture")
            op = float(face.attrs.get("opacity", 1.0))
            if tex is not None and tex.get("path"):
                if op < 0.999:
                    tmp: dict = {}
                    self._append_textured_face(tmp, face, tex)
                    for pth, arr in tmp.items():
                        ttex_runs.setdefault((pth, round(op, 3), fcull),
                                             []).append(arr.tobytes())
                    return
                # (textured opaque fronts of glass-backed faces keep the
                # plain double-sided path — the opaque back pass covers
                # opaque backs, and this combination is vanishing rare)
                self._append_textured_face(sink["tex"], face, tex)
                return
            col = face.attrs.get("color")
            base = tuple(col) if col is not None else self.DEFAULT_FACE_COLOR
            # Bake a subtle diffuse shade from the face normal against a fixed
            # world light — the matte-model look of SketchUp. World-fixed, so
            # it doesn't change as you orbit. The shaded colour rides per
            # vertex, so the whole pass is ONE draw call.
            r, g, b = self._shaded_color(base, self._normal_of(face))
            buf = array("f")
            for t0, t1, t2 in self._tris_of(face):
                buf.extend([
                    t0.x(), t0.y(), t0.z(), r, g, b,
                    t1.x(), t1.y(), t1.z(), r, g, b,
                    t2.x(), t2.y(), t2.z(), r, g, b,
                ])
            if op < 0.999:
                tcol_runs.setdefault((round(op, 3), fcull),
                                     []).append(buf.tobytes())
            elif fcull:
                fcull_vcol_parts.append(buf.tobytes())
            else:
                sink["vcol"].extend(buf)

        if not hide_rest:
            for face in self.scene.loose_mesh.faces:
                if self.scene.entity_visible(face):
                    bucket_face(face)
        group_face_spans: list = []   # (bbox, start-within-groups, count)
        gface_start = 0
        subject_bucketed = False
        pv_faces = getattr(self, "_preview_groups", None) or ()
        for g in draw_groups:         # context first, edited group last
            if (not self.scene.entity_visible(g)
                    or getattr(g, "billboard", False)
                    or id(g) in pv_faces
                    or self._instanced_eligible(g)):
                continue
            if g is self.scene.edit_group:
                self._edit_split_f = gface_start   # made absolute below
            if suppressed_faces and any(f in suppressed_faces
                                        for f in g.mesh.faces):
                # Bucketed into the SUBJECT block at the tail, not the loose
                # head — see ``sink``. The chunk is unusable while a face of
                # it is hidden.
                sink["vcol"], sink["tex"] = subj_vcol, subj_by_texture
                for face in g.mesh.faces:
                    bucket_face(face)   # push/pull preview suppresses faces
                sink["vcol"], sink["tex"] = vcol, by_texture
                subject_bucketed = True
                continue
            chunk = self._group_chunk(g)
            face_parts.append(chunk["vcol"])
            group_face_spans.append((chunk.get("bbox"), gface_start,
                                     len(chunk["vcol"]) // 24))
            gface_start += len(chunk["vcol"]) // 24
            subj = g is self.scene.edit_group
            for path, raw in chunk["by_texture"].items():
                group_texture.setdefault(path, []).append(
                    (raw, chunk.get("bbox"), subj))
            for a, raw in chunk.get("tcol", {}).items():
                tcol_runs.setdefault(a, []).append(raw)
            for key, raw in chunk.get("ttex", {}).items():
                ttex_runs.setdefault(key, []).append(raw)
            if chunk.get("back_vcol"):
                back_vcol_parts.append(chunk["back_vcol"])
            for key, raw in chunk.get("back_tex", {}).items():
                back_tex_runs.setdefault(key, []).append(raw)
            for key, raw in chunk.get("back_tcol", {}).items():
                back_tcol_runs.setdefault(key, []).append(raw)
            for key, raw in chunk.get("back_ttex", {}).items():
                back_ttex_runs.setdefault(key, []).append(raw)
            if chunk.get("fvcol"):
                fcull_vcol_parts.append(chunk["fvcol"])

        # Kept as a part LIST (not one concatenated blob) so the upload can
        # tell which pieces changed; the trailing runs below append to it.
        subj_raw = subj_vcol.tobytes()
        all_face_parts = [vcol.tobytes()] + face_parts + [subj_raw]
        self._faces_count = sum(len(p) for p in all_face_parts) // 24
        # Loose faces sit at the front of the VBO and always draw; group spans
        # follow them, and a bucketed subject block closes the buffer.
        loose_n = len(vcol) // 6
        self._face_spans = ([(None, 0, loose_n)]
                            + [(bb, loose_n + s, n)
                               for bb, s, n in group_face_spans])
        if self._edit_split_f is not None:
            self._edit_split_f += loose_n   # was relative to the group block
        if subj_raw:
            subj_start = loose_n + gface_start
            self._face_spans.append((None, subj_start, len(subj_raw) // 24))
            if subject_bucketed and self.scene.edit_group is not None:
                # The bucketed block IS the subject, and it is last: the fade
                # split moves to its start so the context still fades.
                self._edit_split_f = subj_start
        # Translucent colour runs live in the SAME VBO, after the opaque
        # batch; drawn in their own blended pass (depth-write off).
        self._tcol_runs = []
        start = self._faces_count
        for key in sorted(tcol_runs):
            a, fc = key
            raw = b"".join(tcol_runs[key])
            all_face_parts.append(raw)
            count = len(raw) // 24
            self._tcol_runs.append((a, fc, start, count))
            start += count
        back_vcol_raw = b"".join(back_vcol_parts)
        self._back_vcol_run = (start, len(back_vcol_raw) // 24)
        all_face_parts.append(back_vcol_raw)
        start += self._back_vcol_run[1]
        fvcol_raw = b"".join(fcull_vcol_parts)
        self._fvcol_run = (start, len(fvcol_raw) // 24)
        all_face_parts.append(fvcol_raw)
        start += self._fvcol_run[1]
        self._back_tcol_runs = []
        for a in sorted(back_tcol_runs):
            raw = b"".join(back_tcol_runs[a])
            all_face_parts.append(raw)
            count = len(raw) // 24
            self._back_tcol_runs.append((a, start, count))
            start += count
        self._upload_vbo(self._faces_vbo, "faces", all_face_parts, empty=48)

        # Textured faces: one interleaved (pos+uv) VBO, a run per image path.
        tex_parts = []
        self._tex_runs = []
        # per run: [(bbox, start, count, is_subject)] — the flag lets the fade
        # pass tell the edited group's textured faces from its surroundings,
        # which a single buffer offset cannot (runs interleave by image).
        self._tex_run_parts = []
        start = 0
        for key in dict.fromkeys(list(by_texture) + list(group_texture)
                                 + list(subj_by_texture)):
            run_start = start
            run_parts: list = []
            parts = ([(by_texture[key].tobytes(), None, False)]
                     if key in by_texture else [])
            parts += group_texture.get(key, [])
            # A bucketed subject's textured faces are the subject too, so the
            # fade pass must not wash them out with the surroundings.
            if key in subj_by_texture:
                parts.append((subj_by_texture[key].tobytes(), None, True))
            for raw, bb, subj in parts:
                tex_parts.append(raw)
                n = len(raw) // 20
                run_parts.append((bb, start, n, subj))
                start += n
            self._tex_runs.append((key, run_start, start - run_start))
            self._tex_run_parts.append(run_parts)
        # Where the OPAQUE textured block ends: the shadow depth pass draws
        # up to here, then adds only the translucent runs SketchUp says cast
        # (opacity ≥ 70 %) — glass must let the sun through.
        self._tex_opaque_count = start
        self._ttex_runs = []
        for full in sorted(ttex_runs):
            key, a, fc = full
            raw = b"".join(ttex_runs[full])
            tex_parts.append(raw)
            count = len(raw) // 20
            self._ttex_runs.append((key, a, fc, start, count))
            start += count
        self._back_tex_runs = []
        for key in sorted(back_tex_runs):
            raw = b"".join(back_tex_runs[key])
            tex_parts.append(raw)
            count = len(raw) // 20
            self._back_tex_runs.append((key, start, count))
            start += count
        self._back_ttex_runs = []
        for full in sorted(back_ttex_runs):
            key, a = full
            raw = b"".join(back_ttex_runs[full])
            tex_parts.append(raw)
            count = len(raw) // 20
            self._back_ttex_runs.append((key, a, start, count))
            start += count
        self._tex_faces_count = self._upload_vbo(
            self._tex_faces_vbo, "tex", tex_parts, empty=40) // 20

        if _PERF:
            _plog("sync_edges", (_time_mod.perf_counter() - _st0) * 1000.0)
        self._edges_version = _cache_ver(self)
        self.sceneVersionChanged.emit(self._edges_version)

    def _bucket_back_face(self, face, back):
        """Build the back-side override copy of a two-side-painted face.
        Returns ``(kind, payload)`` — ``("bvcol", bytes)`` /
        ``("btex", (key, bytes))`` for opaque overrides (culled opaque back
        pass), or ``("btcol", (op, bytes))`` / ``("bttex", ((key, op),
        bytes))`` for translucent ones (culled blended pass). ``(None,
        None)`` when the back carries nothing drawable."""
        op = float(back.get("opacity", 1.0))
        tex = back.get("texture")
        if tex is not None and tex.get("path"):
            tmp: dict = {}
            self._append_textured_face(tmp, face, tex)
            for key, arr in tmp.items():
                if op < 0.999:
                    return "bttex", ((key, round(op, 3)), arr.tobytes())
                return "btex", (key, arr.tobytes())
            return None, None
        col = back.get("color")
        if col is None:
            return None, None
        r, g, b = self._shaded_color(tuple(col), self._normal_of(face))
        buf = array("f")
        for t0, t1, t2 in self._tris_of(face):
            buf.extend([
                t0.x(), t0.y(), t0.z(), r, g, b,
                t1.x(), t1.y(), t1.z(), r, g, b,
                t2.x(), t2.y(), t2.z(), r, g, b,
            ])
        if op < 0.999:
            return "btcol", (round(op, 3), buf.tobytes())
        return "bvcol", buf.tobytes()

    def _append_textured_face(self, by_texture: dict, face, tex: dict) -> None:
        """Triangulate ``face`` into ``by_texture[(path, shade)]`` as
        interleaved ``pos(3) + uv(2)`` floats — the quantised diffuse shade
        keys the draw run (the run sets ``u_shade``, so textures get the same
        matte face shading as colour faces). UVs come from the face's fitted
        world→UV affine map when present (``uvw`` — a DAE/OBJ import carrying
        its own texture coordinates), else from the SketchUp-style planar
        projection of each vertex's world position (so coplanar faces tile
        seamlessly)."""
        key = (tex["path"], self._shade_factor(self._normal_of(face)))
        buf = by_texture.get(key)
        if buf is None:
            buf = by_texture[key] = array("f")
        uvw = tex.get("uvw")
        if uvw:
            gu = QVector3D(uvw[0], uvw[1], uvw[2])
            gv = QVector3D(uvw[4], uvw[5], uvw[6])
            for tri in self._tris_of(face):
                for p in tri:
                    buf.extend([
                        p.x(), p.y(), p.z(),
                        QVector3D.dotProduct(gu, p) + uvw[3],
                        QVector3D.dotProduct(gv, p) + uvw[7],
                    ])
            return
        n = face.normal().normalized()
        u_axis, v_axis = plane_axes(n)
        rot = float(tex.get("rot", 0.0))
        if rot:
            a = math.radians(rot)
            cos_a, sin_a = math.cos(a), math.sin(a)
            u_axis, v_axis = (u_axis * cos_a + v_axis * sin_a,
                              v_axis * cos_a - u_axis * sin_a)
        sw = tex.get("sw", 1.0) or 1.0
        sh = tex.get("sh", 1.0) or 1.0
        for tri in self._tris_of(face):
            for p in tri:
                buf.extend([
                    p.x(), p.y(), p.z(),
                    QVector3D.dotProduct(p, u_axis) / sw,
                    QVector3D.dotProduct(p, v_axis) / sh,
                ])

    def _faceme_dir(self, anchor: QVector3D) -> QVector3D:
        """Direction a face-me sprite at ``anchor`` turns toward (not yet
        flattened or normalised). Perspective: toward the eye, so figures
        left and right of centre turn slightly, like SketchUp. Parallel: the
        VIEW direction for every sprite — a parallel camera has no real eye,
        and using the fictitious one made a figure far from the orbit target
        turn 45° away when zoomed in (Marco: "Sumari no se ve bien en vista
        frontal", 2026-09-02)."""
        cam = self.camera
        if cam.perspective:
            return cam.eye() - anchor
        return cam.eye() - cam.target

    def _billboard_quad(self, group, face_dir=None):
        """The face-me quad of a billboard group, rotated around its vertical
        anchor axis to face the camera NOW (or ``face_dir`` when given).
        Returns (corners[4], tex_path) or ``None``. Shared by the render
        pass, picking and the shadow casters."""
        verts = group.mesh.vertices
        if not verts:
            return None
        xs = [v.position.x() for v in verts]
        ys = [v.position.y() for v in verts]
        zs = [v.position.z() for v in verts]
        anchor = QVector3D((min(xs) + max(xs)) / 2,
                           (min(ys) + max(ys)) / 2, min(zs))
        # A billboard being Move/Rotate-dragged previews through THIS pass
        # (its raw mesh quad in the scratch VBOs showed the texture swimming
        # and ignored the face-me turn): carry the preview transform on the
        # anchor so the figure follows the cursor, camera-facing, fixed UVs.
        if id(group) in (getattr(self, "_preview_groups", None) or ()):
            m = getattr(self, "_preview_matrix", None)
            if m is not None:
                anchor = m.map(anchor)
            else:
                off = getattr(self, "_preview_offset", None)
                if off is not None:
                    anchor = anchor + off
        # Planar width: hypot handles a sprite plane at any yaw (an imported
        # face-me sits wherever its baked transform left it); an axis-aligned
        # quad gives the same value as before.
        w = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        h = max(zs) - min(zs)
        tex = None
        for f in group.mesh.faces:
            t = f.attrs.get("texture")
            if t and t.get("path"):
                tex = t["path"]
                break
        # tex may stay None for a vector-art face-me (solid-colour faces,
        # e.g. SketchUp's 2D person): picking/outline/snap still need the
        # quad; the legacy textured-quad render skips texture-less groups.
        if w < 1e-9 or h < 1e-9:
            return None
        # Facing: the camera by default; the shadow pass passes the SUN so a
        # figure's cast silhouette holds still while the camera orbits
        # (SketchUp's face-me "shadows face sun").
        d = face_dir if face_dir is not None else self._faceme_dir(anchor)
        d = QVector3D(d.x(), d.y(), 0.0)
        if d.length() < 1e-6:
            d = QVector3D(1.0, 0.0, 0.0)
        d = d.normalized()
        r = QVector3D(-d.y(), d.x(), 0.0)
        up = QVector3D(0.0, 0.0, 1.0)
        c0 = anchor - r * (w / 2)
        c1 = anchor + r * (w / 2)
        return ([c0, c1, c1 + up * h, c0 + up * h], tex)

    def _draw_billboards(self) -> None:
        """Per-frame pass: each face-me billboard is a textured cutout quad
        turned toward the camera (SketchUp's 2D people). Depth-tested, so it
        hides behind walls correctly; the shader discards transparent texels."""
        groups = [g for g in self._placements()
                  if getattr(g, "billboard", False)
                  and self.scene.entity_visible(g)]
        if not groups:
            return
        self._program.setUniformValue(self._loc_use_tex, 1)
        # Hard alpha cut for face-me figures: their mipmapped edge alpha
        # under the Bayer dither would stipple dots around the silhouette
        # (user report); scene cutouts keep the dither (distant fences).
        self._program.setUniformValue(self._loc_hard_cutout, 1)
        self._billboard_vao.bind()
        for g in groups:
            if getattr(g, "billboard", False) == "mesh":
                # Imported face-me silhouette: its REAL geometry (a cut
                # outline, not a rectangle) turns toward the camera.
                self._draw_faceme_mesh(g)
                continue
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            corners, path = quad
            tex = self._get_texture(path)
            if tex is None:
                continue
            data = array("f")
            uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
            for idx in (0, 1, 2, 0, 2, 3):
                c = corners[idx]
                u, v = uvs[idx]
                data.extend([c.x(), c.y(), c.z(), u, v])
            raw = data.tobytes()
            self._billboard_vbo.bind()
            self._billboard_vbo.allocate(raw, len(raw))
            self._billboard_vbo.release()
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
            if g in self.scene.selection:
                # Selection cue: repaint with the highlight colour untextured.
                pass
        self._billboard_vao.release()
        self._program.setUniformValue(self._loc_hard_cutout, 0)
        self._program.setUniformValue(self._loc_use_tex, 0)

    def _draw_billboard_outlines(self) -> None:
        """Selection cue for face-me billboards: an orange outline around the
        quad AS DRAWN this frame (it rotates toward the camera). Tinting the
        group's static mesh painted a stray plane through the figure —
        SketchUp shows a selected 2D person as an outlined box too."""
        sel = [g for g in self.scene.selection
               if isinstance(g, Group) and getattr(g, "billboard", False)
               and self.scene.entity_visible(g)]
        if not sel:
            return
        data = array("f")
        for g in sel:
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            c = quad[0]
            for i, j in ((0, 1), (1, 2), (2, 3), (3, 0)):
                data.extend([c[i].x(), c[i].y(), c[i].z(),
                             c[j].x(), c[j].y(), c[j].z()])
        if not data:
            return
        raw = data.tobytes()
        self._bb_sel_vbo.bind()
        self._bb_sel_vbo.allocate(raw, len(raw))
        self._bb_sel_vbo.release()
        self._set_color(0.95, 0.45, 0.16, 1.0)  # selection orange
        self._bb_sel_vao.bind()
        self._gl.glDrawArrays(GL_LINES, 0, len(data) // 3)
        self._bb_sel_vao.release()

    def _faceme_base(self, g):
        """Cached base data of a mesh face-me billboard: interleaved pos+uv
        arrays per image, the vertical anchor axis and the horizontal base
        normal. Rebuilt when the scene changes (sprites are tiny)."""
        cache = getattr(self, "_faceme_cache", None)
        if cache is None:
            cache = self._faceme_cache = {}
        key = (self.scene.version, id(self.scene.mesh))
        cur = cache.get(id(g))
        if cur is not None and cur[0] == key:
            return cur[1]
        import numpy as np
        by_tex: dict = {}
        by_color: dict = {}      # rgb tuple -> interleaved pos+uv (uv unused)
        n0 = None
        best_area = 0.0
        for f in g.mesh.faces:
            area = f.area() if hasattr(f, "area") else 0.0
            if n0 is None or area > best_area:
                n0 = f.normal()
                best_area = area
            tex = f.attrs.get("texture")
            if tex is not None and tex.get("path"):
                self._append_textured_face(by_tex, f, tex)
                continue
            # Solid-colour face (a vector-art person like SketchUp's Susan):
            # same interleaved layout, uv ignored, drawn with u_color.
            col = tuple(f.attrs.get("color") or (0.96, 0.95, 0.925))
            buf = by_color.setdefault(col, array("f"))
            for t0, t1, t2 in self._tris_of(f):
                for p in (t0, t1, t2):
                    buf.extend([p.x(), p.y(), p.z(), 0.0, 0.0])
        verts = g.mesh.vertices
        entry = None
        if n0 is not None and verts and (by_tex or by_color):
            xs = [v.position.x() for v in verts]
            ys = [v.position.y() for v in verts]
            anchor = np.array([(min(xs) + max(xs)) / 2,
                               (min(ys) + max(ys)) / 2])
            nh = np.array([n0.x(), n0.y()])
            ln = float(np.hypot(nh[0], nh[1]))
            if ln > 1e-9:
                nh = nh / ln
                arrays = {p: np.frombuffer(buf.tobytes(),
                                           dtype=np.float32).reshape(-1, 5)
                          for p, buf in by_tex.items()}
                colors = {c: np.frombuffer(buf.tobytes(),
                                           dtype=np.float32).reshape(-1, 5)
                          for c, buf in by_color.items()}
                entry = (arrays, colors, anchor, nh)
        cache[id(g)] = (key, entry)
        return entry

    def _draw_faceme_mesh(self, g) -> None:
        """Draw a mesh face-me billboard: rotate its geometry around the
        vertical axis through its anchor so its plane faces the camera NOW.
        Runs inside the billboard pass (textured, billboard VAO bound)."""
        base = self._faceme_base(g)
        if base is None:
            return
        arrays, colors, anchor, nh = base
        import numpy as np
        # Preview transform (Move/Rotate drag): the figure follows the
        # cursor through THIS pass, camera-facing with its baked UVs —
        # see _billboard_quad for the simple-quad twin.
        ox = oy = oz = 0.0
        if id(g) in (getattr(self, "_preview_groups", None) or ()):
            m = getattr(self, "_preview_matrix", None)
            if m is not None:
                p = m.map(QVector3D(anchor[0], anchor[1], anchor[2]))
                ox, oy, oz = (p.x() - anchor[0], p.y() - anchor[1],
                              p.z() - anchor[2])
            else:
                off = getattr(self, "_preview_offset", None)
                if off is not None:
                    ox, oy, oz = off.x(), off.y(), off.z()
        fd = self._faceme_dir(QVector3D(anchor[0] + ox, anchor[1] + oy,
                                        anchor[2] + oz))
        d = np.array([fd.x(), fd.y()])
        ln = float(np.hypot(d[0], d[1]))
        d = nh if ln < 1e-9 else d / ln
        cos = float(nh[0] * d[0] + nh[1] * d[1])
        sin = float(nh[0] * d[1] - nh[1] * d[0])

        def _rotated(arr):
            a = arr.copy()
            x = a[:, 0] - anchor[0]
            y = a[:, 1] - anchor[1]
            a[:, 0] = anchor[0] + cos * x - sin * y + ox
            a[:, 1] = anchor[1] + sin * x + cos * y + oy
            if oz:
                a[:, 2] += oz
            return a

        for (path, _shade), arr in arrays.items():
            # billboards turn toward the camera: no fixed-normal shade
            tex = self._get_texture(path)
            if tex is None:
                continue
            a = _rotated(arr)
            raw = a.tobytes()
            self._billboard_vbo.bind()
            self._billboard_vbo.allocate(raw, len(raw))
            self._billboard_vbo.release()
            tex.bind(0)
            self._gl.glDrawArrays(GL_TRIANGLES, 0, len(a))
        if colors:
            # Solid-colour runs (vector-art face-me like Susan): same VAO,
            # texture sampling off, u_color per run; restore for the pass.
            self._program.setUniformValue(self._loc_use_tex, 0)
            for col, arr in colors.items():
                r, gc, b = col[0], col[1], col[2]
                self._program.setUniformValue(
                    self._loc_color, QVector4D(r, gc, b, 1.0))
                self._program.setUniformValue(
                    self._loc_back_color, QVector4D(r, gc, b, 1.0))
                a = _rotated(arr)
                raw = a.tobytes()
                self._billboard_vbo.bind()
                self._billboard_vbo.allocate(raw, len(raw))
                self._billboard_vbo.release()
                self._gl.glDrawArrays(GL_TRIANGLES, 0, len(a))
            self._program.setUniformValue(self._loc_use_tex, 1)

    def _upload_hover_face(self, face: Face) -> int:
        """Triangulate ``face`` into the hover-faces VBO. Returns vertex count."""
        data = array("f")
        for t0, t1, t2 in face.triangulate():
            data.extend([
                t0.x(), t0.y(), t0.z(),
                t1.x(), t1.y(), t1.z(),
                t2.x(), t2.y(), t2.z(),
            ])
        self._hover_faces_vbo.bind()
        if data:
            raw = data.tobytes()
            self._hover_faces_vbo.allocate(raw, len(raw))
        else:
            self._hover_faces_vbo.allocate(24)
        self._hover_faces_vbo.release()
        return len(data) // 3

    def _upload_silhouette_edges(self) -> int:
        """Upload the *profile* edges into the silhouette VBO and return the
        vertex count. A soft (hidden) edge is drawn when it lies on the
        silhouette — its two faces straddle the view, one turned toward the
        camera and one away — so a curved surface shows its outline. A soft
        edge with a single face is always a profile (a boundary). View-dependent,
        called each frame."""
        # Throttle: the silhouette is view-dependent but re-deriving it at
        # most ~12×/s is visually indistinguishable, and at 100k soft edges
        # the NumPy pass still costs ~4 ms a frame during orbits.
        import time as _time
        now = _time.monotonic()
        key = (_cache_ver(self), id(self.scene.mesh))
        last = getattr(self, "_sil_last", None)
        if last is not None and last[0] == key and now - last[1] < 0.08:
            return last[2]        # VBO still holds the last upload

        # Loose soft edges run the SAME vectorised view test as group
        # chunks: per-edge Python here froze orbits after an explode dumped
        # a group's curved surfaces into the loose mesh (38k soft edges =
        # ~600 ms EVERY frame, piscina.igz user report). The cache bakes
        # endpoints + face normals/centroids once per edit; each frame is
        # one einsum.
        import numpy as np
        cached = getattr(self, "_soft_edges_cache", None)
        if cached is None or cached[0] != key:
            softs = [e for e in self.scene.loose_mesh.edges
                     if getattr(e, "soft", False)
                     and not getattr(e, "hidden", False)
                     and self.scene.entity_visible(e) and e.faces]
            if softs:
                pts = np.empty((len(softs), 6))
                single = np.empty(len(softs), dtype=bool)
                # Face planes via one vectorized cross product instead of
                # per-face Python normal()/centroid() (_newell dominated the
                # edit frame at 25k+ faces). For the view-side sign test any
                # point ON the plane works, so the first loop vertex serves
                # as the anchor; the plane normal comes from the first two
                # loop edges (faces are planar).
                tri0 = np.empty((len(softs), 3, 3))
                tri1 = np.empty((len(softs), 3, 3))
                for i, e in enumerate(softs):
                    pts[i] = (e.a.x(), e.a.y(), e.a.z(),
                              e.b.x(), e.b.y(), e.b.z())
                    v = e.faces[0].vertices
                    tri0[i] = ((v[0].x(), v[0].y(), v[0].z()),
                               (v[1].x(), v[1].y(), v[1].z()),
                               (v[2].x(), v[2].y(), v[2].z()))
                    # A 1-face soft edge is an open-surface boundary (always
                    # a profile); a 2-face one straddles the view or hides.
                    single[i] = len(e.faces) != 2
                    v = (e.faces[1] if len(e.faces) == 2 else e.faces[0]).vertices
                    tri1[i] = ((v[0].x(), v[0].y(), v[0].z()),
                               (v[1].x(), v[1].y(), v[1].z()),
                               (v[2].x(), v[2].y(), v[2].z()))
                n0 = np.cross(tri0[:, 1] - tri0[:, 0], tri0[:, 2] - tri0[:, 0])
                n1 = np.cross(tri1[:, 1] - tri1[:, 0], tri1[:, 2] - tri1[:, 0])
                c0 = tri0[:, 0]
                c1 = tri1[:, 0]
                arrays = (pts.astype(np.float32), n0, c0, n1, c1, single)
            else:
                arrays = None
            cached = (key, arrays)
            self._soft_edges_cache = cached
        eye = self.camera.eye()
        chunks: list = []
        if cached[1] is not None:
            pts, n0, c0, n1, c1, single = cached[1]
            e_np = np.array([eye.x(), eye.y(), eye.z()])
            s0 = np.einsum("ij,ij->i", n0, c0 - e_np)
            s1 = np.einsum("ij,ij->i", n1, c1 - e_np)
            mask = single | ((s0 < 0) != (s1 < 0))
            chunks.append(pts[mask].tobytes())
        else:
            chunks.append(b"")
        pv_sil = getattr(self, "_preview_groups", None) or ()
        # Silhouettes are a full-strength black outline; drawing them over a
        # faded (or hidden) context would put the heaviest line in the frame
        # on exactly the geometry meant to recede. Only the subject profiles.
        skip_context = (self.scene.edit_group is not None
                        and self._edit_rest_mode in ("fade", "hide"))
        groups = [g for g in self._placements()
                  if self.scene.entity_visible(g)
                  and id(g) not in pv_sil
                  and not getattr(g, "billboard", False)
                  and not (skip_context and self._draws_in_edit_context(g))]
        if groups:
            import numpy as np
            e_np = np.array([eye.x(), eye.y(), eye.z()])
            planes = getattr(self, "_frame_planes", None)
            for g in groups:
                ch = self._group_chunk(g)
                if ch["soft_pts"] is None:
                    continue
                bb = ch.get("bbox")
                if (planes is not None and bb is not None
                        and not self._aabb_visible(planes, bb[0], bb[1])):
                    continue        # whole chunk off screen: skip the einsum
                s0 = np.einsum("ij,ij->i", ch["soft_n0"],
                               ch["soft_c0"] - e_np)
                s1 = np.einsum("ij,ij->i", ch["soft_n1"],
                               ch["soft_c1"] - e_np)
                mask = ch["soft_single"] | ((s0 < 0) != (s1 < 0))
                if mask.any():
                    chunks.append(ch["soft_pts"][mask].tobytes())
        raw = b"".join(chunks)
        self._silhouette_vbo.bind()
        if raw:
            self._silhouette_vbo.allocate(raw, len(raw))
        else:
            self._silhouette_vbo.allocate(24)
        self._silhouette_vbo.release()
        count = len(raw) // 12
        self._sil_last = (key, now, count)
        return count

    def _upload_hover_edge(self, edge: Edge) -> int:
        """Upload the hovered edge — or, for a curve segment, its whole contour
        (what a click would select) — into the hover-edges VBO. Returns the
        vertex count to draw."""
        edges = (self.scene.mesh.curve_edges(edge)
                 if getattr(edge, "curve", None) is not None else [edge])
        if edge not in edges:      # e.g. a group's edge — not in the main mesh
            edges = [edge]
        data = array("f")
        for e in edges:
            data.extend([e.a.x(), e.a.y(), e.a.z(),
                         e.b.x(), e.b.y(), e.b.z()])
        self._hover_edges_vbo.bind()
        raw = data.tobytes()
        self._hover_edges_vbo.allocate(raw, len(raw))
        self._hover_edges_vbo.release()
        return len(data) // 3

    def set_hover(self, entity) -> None:
        """Set the entity (edge/face) highlighted under the cursor and repaint
        if it changed. ``None`` clears the highlight."""
        if entity is self._hover_entity:
            return
        self._hover_entity = entity
        self.update()

    def flash_status(self, text: str, msec: int = 2500) -> None:
        """Briefly show ``text`` in the main window's status bar (e.g. Push/Pull's
        "Offset limited to X m"). No-op if there is no status bar yet."""
        window = self.window()
        bar = window.statusBar() if window is not None else None
        if bar is not None:
            bar.showMessage(text, msec)

    def set_suppressed_faces(self, faces) -> None:
        """Hide a set of scene faces from the normal pass (e.g. the flat inner
        face a Push/Pull is recessing). Identity-keyed; empty set restores.
        No-op when unchanged so the drag doesn't rebuild every frame."""
        faces = set(faces)
        if faces == self._suppressed_faces:
            return
        self._suppressed_faces = faces
        self._edges_version = -1  # the faces VBO is rebuilt by _sync_edges
        self.update()

    def _draw_preview_faces(self) -> None:
        """Triangulate and draw the active tool's solid preview faces (if any).
        A face carrying attrs shows its REAL look — painted colour, or its
        texture (the tool re-anchors the uvw map to the drag) — so a paste
        drags the actual model; bare faces keep the warm cream of the
        push/pull preview. Depth-tested with a polygon offset so the
        wireframe sits cleanly on top."""
        tool = self.active_tool
        provider = getattr(tool, "preview_faces", None) if tool is not None else None
        if not callable(provider):
            return
        faces = provider()
        if not faces:
            return
        data = array("f")
        runs = []                        # (shaded_rgb, start_vertex, count)
        by_texture: dict = {}            # (path, shade) -> interleaved pos+uv
        for face in faces:
            attrs = getattr(face, "attrs", None) or {}
            tex = attrs.get("texture")
            if tex and tex.get("path"):
                self._append_textured_face(by_texture, face, tex)
                continue
            color = attrs.get("color") or self.DEFAULT_FACE_COLOR
            start = len(data) // 3
            for t0, t1, t2 in self._tris_of(face):
                data.extend([
                    t0.x(), t0.y(), t0.z(),
                    t1.x(), t1.y(), t1.z(),
                    t2.x(), t2.y(), t2.z(),
                ])
            runs.append((self._shaded_color(tuple(color[:3]), self._normal_of(face)),
                         start, len(data) // 3 - start))
        if not data and not by_texture:
            return
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        if data:
            self._preview_faces_vbo.bind()
            raw = data.tobytes()
            self._preview_faces_vbo.allocate(raw, len(raw))
            self._preview_faces_vbo.release()
            self._preview_faces_vao.bind()
            for (r, g, b), start, count in runs:
                self._set_color(r, g, b, 1.0)
                # A preview has no back: it is an overlay, not a solid with an
                # inside. Its walls are wound however the sweep produced them
                # and nothing surrounds them to hide the ones turned away, so
                # the real back-face tint painted the pocket of a push-in blue
                # over the shape being formed (Marco, 2026-08-27). Both sides
                # take the face's own colour.
                self._program.setUniformValue(self._loc_back_color,
                                              QVector4D(r, g, b, 1.0))
                self._gl.glDrawArrays(GL_TRIANGLES, start, count)
            self._preview_faces_vao.release()
            self._set_back_face_color()          # leave the real tint behind
        if by_texture:
            self._program.setUniformValue(self._loc_use_tex, 1)
            self._preview_tex_vao.bind()
            for key, buf in by_texture.items():
                path, shade = key if isinstance(key, tuple) else (key, 1.0)
                tex_obj = self._get_texture(path)
                if tex_obj is None:
                    continue
                raw = buf.tobytes()
                self._preview_tex_vbo.bind()
                self._preview_tex_vbo.allocate(raw, len(raw))
                self._preview_tex_vbo.release()
                self._program.setUniformValue1f(self._loc_shade, float(shade))
                tex_obj.bind(0)
                self._gl.glDrawArrays(GL_TRIANGLES, 0, len(buf) // 5)
                tex_obj.release(0)
            self._preview_tex_vao.release()
            self._program.setUniformValue1f(self._loc_shade, 1.0)
            self._program.setUniformValue(self._loc_use_tex, 0)
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)

    def _draw_rubber_band(self) -> None:
        self._overlay_rubber = None
        tool = self.active_tool
        if tool is None:
            return
        segments = tool.rubber_band_lines()
        if not segments:
            return

        # A tool can force its preview-line colour (Push/Pull uses the normal
        # edge colour so its forming box reads like real geometry, not a loose
        # orange rubber band).
        forced = getattr(tool, "wireframe_color", None)
        snap = self.last_snap
        # Axis / reference / extension cues read as "projection lines": draw them
        # a touch thicker so the alignment is easy to spot while drawing.
        inference = (
            forced is None
            and snap is not None
            and snap.kind in ("axis", "axis_inference", "reference", "extension",
                              "through_point", "perp_face")
        )
        if forced is not None:
            color = forced
        elif snap is not None and snap.kind == "axis":
            r, g, b = snap.color
            color = (r, g, b, 1.0)
        elif snap is not None and snap.kind == "axis_inference":
            r, g, b = snap.color
            color = (r, g, b, 0.50)
        elif snap is not None and snap.kind in ("reference", "through_point", "perp_face"):
            r, g, b = snap.color
            color = (r, g, b, 1.0)
        elif snap is not None and snap.kind == "close":
            color = (0.20, 0.40, 0.78, 0.95)
        else:
            color = (0.95, 0.45, 0.16, 0.85)

        # Depth-tested previews (Push/Pull, Offset, Paste) read like real
        # geometry and need GL hidden-line removal — draw them via GL. The
        # "always on top" previews (Line/Rectangle/Move) are stashed for the
        # QPainter overlay instead, where a thick pen is reliable (Core-profile
        # glLineWidth often clamps to 1px on Mesa, so GL can't thicken them).
        if getattr(tool, "wireframe_depth_tested", False):
            data = array("f")
            for a, b in segments:
                data.extend([a.x(), a.y(), a.z(), b.x(), b.y(), b.z()])
            raw = data.tobytes()
            self._rubber_vbo.bind()
            self._rubber_vbo.allocate(raw, len(raw))
            self._rubber_vbo.release()

            self._set_color(*color)
            self._rubber_vao.bind()
            self._gl.glDrawArrays(GL_LINES, 0, len(data) // 3)
            self._rubber_vao.release()
        else:
            self._overlay_rubber = (segments, color, 2.5 if inference else 2.0)

    def _draw_rubber_band_overlay(self, painter: QPainter) -> None:
        if self._overlay_rubber is None:
            return
        segments, color, width = self._overlay_rubber
        r, g, b = color[0], color[1], color[2]
        a = color[3] if len(color) > 3 else 1.0
        pen = QPen(QColor.fromRgbF(r, g, b, a), width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        for p0, p1 in segments:
            q0 = self._world_to_pixel(p0)
            q1 = self._world_to_pixel(p1)
            if q0 is not None and q1 is not None:
                painter.drawLine(QPointF(*q0), QPointF(*q1))

    # ---- 2D overlay (QPainter on top of OpenGL) -----------------------------
    def _draw_overlay(self) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        # Rubber band for the "always on top" tools (Line/Rectangle/Move),
        # drawn here with a thick, reliable pen.
        self._draw_rubber_band_overlay(painter)

        # Snap indicator
        if (
            self.active_tool is not None
            and self.last_snap is not None
            and self.last_snap.kind != "none"
        ):
            self._draw_snap_indicator(painter, self.last_snap)

        # Push/Pull distance-inference marker (a green square on the corner/face
        # the extrusion is snapping level with).
        self._draw_inference_marker(painter)

        # Construction guides (Tape Measure) — fine dashed scaffolding lines.
        self._draw_guides(painter)

        # Borders of the reference images, so one lying flat is still findable.
        self._draw_image_outlines(painter)

        # The Scale tool's grip box (SketchUp's yellow box with green grips).
        self._draw_scale_box(painter)
        self._draw_section_planes(painter)
        # Tool-owned overlay (the Flip planes; the future Axes gizmo): a tool
        # exposing ``draw_overlay(viewport, painter)`` paints after the
        # document annotations, before the edit-group frame.
        hook = getattr(self.active_tool, "draw_overlay", None)
        if callable(hook):
            hook(self, painter)
        self._draw_edit_group_box(painter)

        # Terrain-surface fills (draped / flat) under the georef paths — Track G.
        self._draw_geo_surfaces(painter)

        # Traced georef paths (roads / boundaries) — Track G.
        self._draw_geo_paths(painter)

        # Imported survey points (GPS / total station) — Track G.
        self._draw_geo_points(painter)

        # Profile→plan marker: the route point at the station hovered in the
        # profile panel (Track G).
        if self._route_marker is not None:
            q = self._world_to_pixel(self.drape(self._route_marker))
            if q is not None:
                painter.setBrush(QColor(243, 115, 41))
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.drawEllipse(QPointF(*q), 6, 6)
                painter.setBrush(Qt.NoBrush)

        # Persistent dimension annotations
        self._draw_dimensions(painter)

        # Leader-text annotations
        self._draw_text_labels(painter)

        # Length measurement near rubber band
        self._draw_length_label(painter)

        # Labels in the top-left. Reference > explicit axis lock > soft inference.
        if self.reference_mode is not None:
            self._draw_reference_label(painter)
        elif self.axis_lock is not None:
            self._draw_axis_lock_label(painter)
        else:
            self._draw_inference_label(painter)

        # Linear-inference toggle state (Alt), shown while not on the default.
        if self.linear_inference_mode != "all":
            self._draw_linear_mode_label(painter)

        # Rubber-band selection box.
        self._draw_selection_box(painter)
        self._draw_zoom_box(painter)

        painter.end()

    def _draw_linear_mode_label(self, painter: QPainter) -> None:
        text = {
            "off": "Inferencias lineales: OFF (Alt)",
            "parallel_perp": "Inferencias: solo paralela / perpendicular (Alt)",
        }.get(self.linear_inference_mode)
        if not text:
            return
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        painter.setPen(QPen(QColor(210, 150, 40)))
        painter.drawText(QPointF(14, self.height() - 16), text)

    def _draw_selection_box(self, painter: QPainter) -> None:
        if not self._box_active or self._box_start is None or self._box_cur is None:
            return
        s, c = self._box_start, self._box_cur
        if math.hypot(c.x() - s.x(), c.y() - s.y()) < self.BOX_DRAG_THRESHOLD_PX:
            return
        rect = QRectF(
            min(s.x(), c.x()), min(s.y(), c.y()),
            abs(c.x() - s.x()), abs(c.y() - s.y()),
        )
        crossing = (c.x() - s.x()) < 0
        if crossing:
            # Crossing: dashed green, selects anything it touches.
            pen = QPen(QColor(40, 158, 92), 1.5, Qt.DashLine)
            fill = QColor(40, 158, 92, 28)
        else:
            # Window: solid blue, selects only fully enclosed.
            pen = QPen(QColor(51, 102, 199), 1.5, Qt.SolidLine)
            fill = QColor(51, 102, 199, 28)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRect(rect)

    def _draw_zoom_box(self, painter: QPainter) -> None:
        if (not self._zoom_box_active or self._zoom_box_start is None
                or self._zoom_box_cur is None):
            return
        s, c = self._zoom_box_start, self._zoom_box_cur
        rect = QRectF(
            min(s.x(), c.x()), min(s.y(), c.y()),
            abs(c.x() - s.x()), abs(c.y() - s.y()),
        )
        painter.setPen(QPen(QColor(243, 115, 41), 1.5, Qt.DashLine))
        painter.setBrush(QColor(243, 115, 41, 26))
        painter.drawRect(rect)

    def _zoom_to_box(self, start: QPointF, end: QPointF) -> None:
        """Zoom the camera so the dragged screen rectangle fills the view
        (Zoom Window). Re-centres on the box's centre and scales the distance
        by the fraction of the viewport the box covers."""
        bw, bh = abs(end.x() - start.x()), abs(end.y() - start.y())
        if bw < 6 or bh < 6:          # a click, not a real box → ignore
            return
        cx, cy = (start.x() + end.x()) / 2.0, (start.y() + end.y()) / 2.0
        focus = self._world_under_cursor(cx, cy)
        if focus is not None:
            self.camera.target = focus
        frac = max(bw / max(self.width(), 1), bh / max(self.height(), 1))
        frac = max(frac, 0.04)        # don't zoom past a sane limit in one go
        from core.camera import MAX_DISTANCE, MIN_DISTANCE
        self.camera.distance = max(
            MIN_DISTANCE, min(self.camera.distance * frac, MAX_DISTANCE))
        self.update()

    def _draw_snap_indicator(self, painter: QPainter, snap: SnapResult) -> None:
        # Axis-lock and inference state is conveyed by the coloured rubber
        # band; no badge follows the cursor along the lock line. Only the
        # discrete point snaps get a marker.
        if snap.kind in ("axis_inference", "axis"):
            return
        pixel = self._world_to_pixel(snap.point)
        if pixel is None:
            return
        r, g, b = snap.color
        color = QColor.fromRgbF(r, g, b, 1.0)
        # Dashed guide line (the extension inference shows the edge's dashed
        # continuation to the cursor).
        if snap.guide is not None:
            gp0 = self._world_to_pixel(snap.guide[0])
            gp1 = self._world_to_pixel(snap.guide[1])
            if gp0 is not None and gp1 is not None:
                # A snap can colour its guide differently from the marker (the
                # 'from point' guide is axis-coloured while the point is green).
                gc = snap.guide_color if snap.guide_color is not None else (r, g, b)
                dash = QPen(QColor.fromRgbF(gc[0], gc[1], gc[2], 0.9), 2.0, Qt.DashLine)
                painter.setPen(dash)
                painter.drawLine(QPointF(*gp0), QPointF(*gp1))
        # A white halo under the marker lifts it off busy geometry, then
        # the coloured marker on top — bigger and bolder than before so the
        # snap point reads at a glance (a common request: the dots were too
        # small to aim with).
        halo = QPen(QColor(255, 255, 255, 230), 4.5)
        mark = QPen(color, 2.6)
        painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
        px, py = pixel
        if snap.kind == "intersection":
            # X marker at the crossing (drawn line × projected guide).
            for pen in (halo, mark):
                painter.setPen(pen)
                painter.drawLine(QPointF(px - 8, py - 8), QPointF(px + 8, py + 8))
                painter.drawLine(QPointF(px - 8, py + 8), QPointF(px + 8, py - 8))
        elif snap.kind in ("endpoint", "origin", "on_edge", "extension", "from_point"):
            rect = QRectF(px - 7, py - 7, 14, 14)
            painter.setPen(halo)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            painter.setPen(mark)
            painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
            painter.drawRect(rect)
        elif snap.kind == "midpoint":
            # Cyan diamond, SketchUp-style.
            diamond = QPolygonF([
                QPointF(px, py - 9), QPointF(px + 9, py),
                QPointF(px, py + 9), QPointF(px - 9, py),
            ])
            painter.setPen(halo)
            painter.setBrush(Qt.NoBrush)
            painter.drawPolygon(diamond)
            painter.setPen(mark)
            painter.setBrush(QColor.fromRgbF(r, g, b, 0.30))
            painter.drawPolygon(diamond)
        elif snap.kind == "on_face":
            painter.setPen(halo)
            painter.drawEllipse(QPointF(px, py), 5.5, 5.5)
            painter.setPen(mark)
            painter.drawEllipse(QPointF(px, py), 5.5, 5.5)
        elif snap.kind == "close":
            painter.setPen(halo)
            painter.drawEllipse(QPointF(px, py), 9.0, 9.0)
            painter.setPen(mark)
            painter.drawEllipse(QPointF(px, py), 9.0, 9.0)
        elif snap.kind in ("reference", "through_point", "perp_face"):
            painter.setPen(halo)
            painter.drawEllipse(QPointF(px, py), 6.5, 6.5)
            painter.setPen(mark)
            painter.drawEllipse(QPointF(px, py), 6.5, 6.5)

        # Tooltip text next to the marker (SketchUp shows "On Edge", etc.).
        label = self._SNAP_LABELS.get(snap.kind)
        if label:
            label = tr(label)
            font = QFont()
            font.setPointSize(9)
            painter.setFont(font)
            painter.setPen(QPen(QColor(255, 255, 255, 220)))
            painter.drawText(QPointF(px + 11, py + 17), label)
            painter.setPen(QPen(color))
            painter.drawText(QPointF(px + 10, py + 16), label)

    def _draw_edit_group_box(self, painter: QPainter) -> None:
        """Dashed bounding box around the group being edited — the visual cue
        that you are INSIDE it (SketchUp draws the same box)."""
        group = self.scene.edit_group
        if group is None or not group.mesh.vertices:
            return
        # In the group's OWN axes, like the selection cue: on a rotated
        # object a world-aligned box reads as skewed and wraps mostly air.
        from core.group import oriented_box_corners
        corners = oriented_box_corners(*self._group_obb(group))
        pix = [self._world_to_pixel(c) for c in corners]
        if any(p is None for p in pix):
            return
        pen = QPen(QColor(90, 110, 140), 1, Qt.DashLine)
        painter.setPen(pen)
        # Box edges: corner indices differing in exactly one axis bit.
        for i in range(8):
            for bit in (1, 2, 4):
                j = i | bit
                if j != i:
                    painter.drawLine(int(pix[i][0]), int(pix[i][1]),
                                     int(pix[j][0]), int(pix[j][1]))

    # ---- Section planes (SketchUp sections) ----------------------------------
    def _set_section_clip(self, on: bool) -> None:
        """Enable/disable the active section cut around a model-geometry pass
        (``gl_ClipDistance`` in basic.vert). No-op when no cut is active."""
        if getattr(self, "_clip_vec", None) is None:
            return
        if on:
            self._program.setUniformValue(self._loc_clip_plane, self._clip_vec)
            self._program.setUniformValue(self._loc_clip_enable, 1)
            self._gl.glEnable(GL_CLIP_DISTANCE0)
        else:
            self._program.setUniformValue(self._loc_clip_enable, 0)
            self._gl.glDisable(GL_CLIP_DISTANCE0)

    def _section_cut_active(self):
        return _active_cut(self.scene)

    def section_plane_frame(self, sp) -> list:
        """Four world corners of the plane's drawn frame: the model's bounds
        projected onto the plane, with a margin (SketchUp sizes the plane
        object to the model)."""
        u, v = plane_axes(sp.normal)
        lo, hi = self.scene.bounds()
        if lo is None:
            half_u = half_v = 1.5
            cu = cv = 0.0
        else:
            corners = [QVector3D(x, y, z)
                       for x in (lo.x(), hi.x())
                       for y in (lo.y(), hi.y())
                       for z in (lo.z(), hi.z())]
            us = [QVector3D.dotProduct(c - sp.point, u) for c in corners]
            vs = [QVector3D.dotProduct(c - sp.point, v) for c in corners]
            cu, cv = (min(us) + max(us)) * 0.5, (min(vs) + max(vs)) * 0.5
            half_u = (max(us) - min(us)) * 0.56 + 0.2
            half_v = (max(vs) - min(vs)) * 0.56 + 0.2
        c = sp.point + u * cu + v * cv
        return [c - u * half_u - v * half_v, c + u * half_u - v * half_v,
                c + u * half_u + v * half_v, c - u * half_u + v * half_v]

    def _draw_section_planes(self, painter: QPainter) -> None:
        """The section plane OBJECTS (frame + corner brackets + symbol),
        SketchUp-style: grey when inactive, ink when active, selection
        orange when selected. Hidden by View ▸ Section Planes."""
        planes = getattr(self.scene, "section_planes", None)
        if not planes or not getattr(self.scene, "show_section_planes", True):
            return
        selection = self.scene.selection
        for sp in planes:
            corners = self.section_plane_frame(sp)
            px = []
            ok = True
            for i in range(4):
                seg = self._clip_segment_front(corners[i],
                                               corners[(i + 1) % 4])
                if seg is None:
                    ok = False
                    break
                a = self._world_to_pixel(seg[0])
                b = self._world_to_pixel(seg[1])
                if a is None or b is None:
                    ok = False
                    break
                px.append((a, b))
            if not ok:
                continue
            if sp in selection:
                col = QColor(243, 115, 41)
                width = 2
            elif sp.active:
                col = QColor(45, 55, 75)
                width = 2
            else:
                col = QColor(150, 155, 162)
                width = 1.4
            # SketchUp draws the frame edges dashed.
            pen = QPen(col, width, Qt.DashLine)
            painter.setPen(pen)
            for a, b in px:
                painter.drawLine(QPointF(*a), QPointF(*b))
            # Corner brackets: short SOLID ticks into the frame.
            painter.setPen(QPen(col, width))
            for i in range(4):
                c = self._world_to_pixel(corners[i])
                n1 = self._world_to_pixel(corners[(i + 1) % 4])
                n2 = self._world_to_pixel(corners[(i + 3) % 4])
                if c is None or n1 is None or n2 is None:
                    continue
                for n_ in (n1, n2):
                    dx, dy = n_[0] - c[0], n_[1] - c[1]
                    ln = math.hypot(dx, dy) or 1.0
                    k = min(14.0, ln * 0.18) / ln
                    painter.drawLine(QPointF(c[0], c[1]),
                                     QPointF(c[0] + dx * k, c[1] + dy * k))
            # SketchUp: the section SYMBOL rides in a little balloon at EVERY
            # corner of the frame.
            symbol = (sp.symbol or "").strip()
            if symbol:
                painter.save()
                font = painter.font()
                font.setPointSizeF(8.5)
                font.setBold(True)
                painter.setFont(font)
                r = 9.0
                for i in range(4):
                    c = self._world_to_pixel(corners[i])
                    if c is None:
                        continue
                    centre = QPointF(c[0], c[1])
                    painter.setBrush(QColor(255, 255, 255, 220))
                    painter.setPen(QPen(col, width))
                    painter.drawEllipse(centre, r, r)
                    painter.setPen(QPen(col, 1))
                    painter.drawText(
                        QRectF(c[0] - r, c[1] - r, 2 * r, 2 * r),
                        Qt.AlignCenter, symbol[:3])
                painter.restore()

    def pick_section_plane(self, screen_x: float, screen_y: float):
        """The section plane whose frame is nearest the cursor within the
        pick threshold, or ``None`` (Select / context menu / Eraser)."""
        planes = getattr(self.scene, "section_planes", None)
        if not planes or not getattr(self.scene, "show_section_planes", True):
            return None
        best, best_d = None, self.pick_threshold_px
        for sp in planes:
            corners = self.section_plane_frame(sp)
            for i in range(4):
                seg = self._clip_segment_front(corners[i],
                                               corners[(i + 1) % 4])
                if seg is None:
                    continue
                a = self._world_to_pixel(seg[0])
                b = self._world_to_pixel(seg[1])
                if a is None or b is None:
                    continue
                d = _point_to_segment_distance_2d((screen_x, screen_y), a, b)
                if d < best_d:
                    best_d = d
                    best = sp
        return best

    def _section_cut_segments(self):
        """World-space cut segments: the active plane ∩ every visible model
        triangle, vectorized over the pick index's (v0, e1, e2) arrays.
        Cached per (scene version, plane pose)."""
        sp = self.scene.active_section()
        if sp is None:
            return None
        import numpy as np
        n, o = sp.normal, sp.point
        key = (self.scene.version, round(n.x(), 9), round(n.y(), 9),
               round(n.z(), 9), round(o.x(), 6), round(o.y(), 6),
               round(o.z(), 6))
        cached = getattr(self, "_section_cut_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        idx = self._pick_index()
        segs = None
        if idx.tri_v0 is not None and len(idx.tri_v0):
            nv = np.array([n.x(), n.y(), n.z()], dtype=np.float64)
            c = float(np.dot(nv, [o.x(), o.y(), o.z()]))
            p0 = idx.tri_v0
            p1 = idx.tri_v0 + idx.tri_e1
            p2 = idx.tri_v0 + idx.tri_e2
            vis = idx.ent_vis[idx.tri_ent]
            d0 = p0 @ nv - c
            d1 = p1 @ nv - c
            d2 = p2 @ nv - c
            pts = []
            for (a, b, da, db) in ((p0, p1, d0, d1), (p1, p2, d1, d2),
                                   (p2, p0, d2, d0)):
                cross = (da * db) < 0
                t = np.zeros(len(da))
                np.divide(da, da - db, out=t, where=cross)
                pts.append((cross, a + (b - a) * t[:, None]))
            two = (pts[0][0].astype(np.int8) + pts[1][0] + pts[2][0]) == 2
            two &= vis
            if two.any():
                acc = np.zeros((int(two.sum()), 2, 3))
                slot = np.zeros(int(two.sum()), dtype=np.int64)
                for cross, p in pts:
                    m = cross[two]
                    where = np.where(m)[0]
                    acc[where, np.minimum(slot[where], 1)] = p[two][m]
                    slot[where] += 1
                segs = acc.astype(np.float32)
        self._section_cut_cache = (key, segs)
        return segs

    def _draw_section_fill(self, mode, style) -> None:
        """SketchUp 2018+ Section Fill: paint the areas where the active cut
        slices THROUGH a solid. Per-pixel GL capping — wherever the visible
        surface is a BACK face, the eye is looking at the inside of a solid
        opened by the clip, so the plane fills it. Open (non-watertight)
        surfaces can leak the fill, exactly SketchUp's own troubleshoot
        case. Lives in the style (style.section_fill), like SketchUp."""
        if getattr(self, "_clip_vec", None) is None:
            return
        if not getattr(style, "section_fill", True):
            return
        if mode in ("wireframe", "xray"):
            return
        sp = self.scene.active_section()
        if sp is None:
            return
        # Pass 1 — stencil the pixels whose visible surface is a back face.
        self._gl.glStencilMask(0xFF)
        self._gl.glClear(GL_STENCIL_BUFFER_BIT)
        self._gl.glEnable(GL_STENCIL_TEST)
        self._gl.glStencilFunc(GL_ALWAYS, 1, 0xFF)
        self._gl.glStencilOp(GL_KEEP, GL_KEEP, GL_REPLACE)
        self._gl.glColorMask(False, False, False, False)
        self._gl.glDepthMask(GL_FALSE)
        self._gl.glEnable(GL_CULL_FACE)
        self._gl.glCullFace(GL_FRONT)          # rasterize BACK faces only
        if self._faces_count > 0:
            self._faces_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._faces_count)
            self._faces_vao.release()
        if self._tex_faces_count > 0:
            self._tex_faces_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._tex_faces_count)
            self._tex_faces_vao.release()
        self._draw_instanced_raw()   # instanced components join the stencil
        self._gl.glDisable(GL_CULL_FACE)
        self._gl.glColorMask(True, True, True, True)
        self._gl.glDepthMask(GL_TRUE)
        # Pass 2 — the plane quad, only through the stencil, nudged a hair
        # behind so the thick cut lines drawn later win the depth test.
        self._gl.glStencilFunc(GL_EQUAL, 1, 0xFF)
        self._gl.glStencilMask(0x00)
        self._set_section_clip(False)
        import numpy as np
        corners = self.section_plane_frame(sp)
        c = [np.array([q.x(), q.y(), q.z()], dtype=np.float32)
             for q in corners]
        tris = np.concatenate([c[0], c[1], c[2], c[0], c[2], c[3]])
        raw = tris.astype(np.float32).tobytes()
        self._section_vbo.bind()
        self._section_vbo.allocate(raw, len(raw))
        self._section_vbo.release()
        fc = getattr(style, "section_fill_color", (0.35, 0.37, 0.41))
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(2.0, 2.0)
        self._set_color(fc[0], fc[1], fc[2], 1.0)
        self._program.setUniformValue(
            self._loc_back_color, QVector4D(fc[0], fc[1], fc[2], 1.0))
        self._section_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, 6)
        self._section_vao.release()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        self._gl.glStencilMask(0xFF)
        self._gl.glDisable(GL_STENCIL_TEST)
        self._set_section_clip(True)

    def _draw_section_cut_edges(self) -> None:
        """SketchUp's thick section-cut lines: quads in the cut plane, sized
        ~2.5 px, nudged toward the CLIPPED side so they never z-fight the
        remaining geometry. Skipped when cuts are hidden."""
        if getattr(self, "_clip_vec", None) is None:
            return
        segs = self._section_cut_segments()
        if segs is None or not len(segs):
            return
        import numpy as np
        sp = self.scene.active_section()
        n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()],
                     dtype=np.float64)
        a = segs[:, 0].astype(np.float64)
        b = segs[:, 1].astype(np.float64)
        t = b - a
        ln = np.linalg.norm(t, axis=1)
        keep = ln > 1e-9
        if not keep.any():
            return
        a, b, t, ln = a[keep], b[keep], t[keep], ln[keep]
        t /= ln[:, None]
        side = np.cross(np.broadcast_to(n, t.shape), t)
        # ~2.5 px of world width at each segment's distance from the eye.
        eye = self.camera.eye()
        eyev = np.array([eye.x(), eye.y(), eye.z()], dtype=np.float64)
        mid = (a + b) * 0.5
        dist = np.linalg.norm(mid - eyev, axis=1)
        h = max(1.0, self.height())
        fov = math.radians(getattr(self.camera, "fov_deg", 45.0))
        wpp = np.maximum(dist * math.tan(fov * 0.5) * 2.0 / h, 1e-6)
        w = (wpp * 1.25)[:, None]
        lift = n * 0.6
        off = side * w
        q0 = a - off + lift * w
        q1 = b - off + lift * w
        q2 = b + off + lift * w
        q3 = a + off + lift * w
        tris = np.empty((len(a) * 2, 9), dtype=np.float32)
        tris[0::2, 0:3] = q0
        tris[0::2, 3:6] = q1
        tris[0::2, 6:9] = q2
        tris[1::2, 0:3] = q0
        tris[1::2, 3:6] = q2
        tris[1::2, 6:9] = q3
        raw = tris.tobytes()
        self._section_vbo.bind()
        self._section_vbo.allocate(raw, len(raw))
        self._section_vbo.release()
        ec = self._frame_style.edge_color
        self._set_color(ec[0], ec[1], ec[2], 1.0)
        self._section_vao.bind()
        self._gl.glDrawArrays(GL_TRIANGLES, 0, len(a) * 6)
        self._section_vao.release()

    def _clip_segment_front(
        self, a: QVector3D, b: QVector3D
    ) -> Optional[tuple[QVector3D, QVector3D]]:
        """Clip a world segment to the part in FRONT of the camera. The long
        'infinite' guide segments (±10 km) routinely have an endpoint behind
        the eye, where ``_world_to_pixel`` returns None — which used to make
        the whole guide vanish from render, snap and pick in ordinary 3D
        views. Returns the visible sub-segment, or ``None``."""
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        wa = mvp.map(QVector4D(a.x(), a.y(), a.z(), 1.0)).w()
        wb = mvp.map(QVector4D(b.x(), b.y(), b.z(), 1.0)).w()
        eps = 1e-3
        if wa <= eps and wb <= eps:
            return None
        if wa <= eps or wb <= eps:
            t = (eps - wa) / (wb - wa)   # w is linear along the segment
            cut = a + (b - a) * t
            return (cut, QVector3D(b)) if wa <= eps else (QVector3D(a), cut)
        return (QVector3D(a), QVector3D(b))

    def _draw_scale_box(self, painter: QPainter) -> None:
        """SketchUp's scaling box: yellow edges, green grips, the grabbed grip
        and its anchor in red. Drawn from whatever the active tool reports via
        ``scale_box_state()`` (duck-typed, so this file needs no tool import);
        while an operation is live the box rides the same matrix the geometry
        is being scaled by."""
        tool = self.active_tool
        state_fn = getattr(tool, "scale_box_state", None)
        if state_fn is None:
            return
        state = state_fn()
        if state is None:
            return
        box_pen = QPen(QColor(214, 174, 0), 1)          # SketchUp yellow
        painter.setPen(box_pen)
        for a, b in state["segments"]:
            seg = self._clip_segment_front(a, b)
            if seg is None:
                continue
            pa = self._world_to_pixel(seg[0])
            pb = self._world_to_pixel(seg[1])
            if pa is not None and pb is not None:
                painter.drawLine(QPointF(*pa), QPointF(*pb))
        green = QColor(60, 160, 60)
        red = QColor(220, 40, 40)
        for pos, role in state["grips"]:
            px = self._world_to_pixel(pos)
            if px is None:
                continue
            half = 5.0 if role in ("hover", "active", "anchor") else 4.0
            color = green if role == "idle" else red
            painter.fillRect(QRectF(px[0] - half, px[1] - half,
                                    half * 2, half * 2), color)
            painter.setPen(QPen(QColor(30, 30, 30), 1))
            painter.drawRect(QRectF(px[0] - half, px[1] - half,
                                    half * 2, half * 2))
        painter.setPen(box_pen)

    def _draw_guides(self, painter: QPainter) -> None:
        """Draw construction guides: fine dashed lines (and small crosses for
        guide points), SketchUp-style scaffolding."""
        guides = getattr(self.scene, "guides", None)
        if not guides:
            return
        pen = QPen(QColor(70, 90, 120), 1, Qt.DashLine)
        sel_pen = QPen(QColor(243, 115, 41), 2, Qt.DashLine)  # selection orange
        selection = self.scene.selection
        for g in guides:
            painter.setPen(sel_pen if g in selection else pen)
            if g.is_line:
                seg = self._clip_segment_front(*g.segment())
                if seg is None:
                    continue
                pa = self._world_to_pixel(seg[0])
                pb = self._world_to_pixel(seg[1])
                if pa is not None and pb is not None:
                    painter.drawLine(QPointF(*pa), QPointF(*pb))
            else:
                q = self._world_to_pixel(g.point)
                if q is not None:
                    painter.drawLine(QPointF(q[0] - 5, q[1]), QPointF(q[0] + 5, q[1]))
                    painter.drawLine(QPointF(q[0], q[1] - 5), QPointF(q[0], q[1] + 5))

    def _draw_geo_surfaces(self, painter: QPainter) -> None:
        """Draw terrain-surface fills as shaded, back-to-front triangles so the
        relief reads in 3D (Track G). Semi-transparent, so the base map shows."""
        paths = getattr(self.scene, "geo_paths", None)
        if not paths:
            return
        eye = self.camera.eye()
        light = QVector3D(0.3, 0.4, 0.85)
        light = light.normalized()
        for path in paths:
            tris = getattr(path, "_surface_tris", None)
            if not tris:
                continue
            flat = getattr(path, "surface", None) == "flat"
            # Painter's algorithm: far triangles first.
            ordered = sorted(
                tris, key=lambda t: -((t[0] + t[1] + t[2]) - eye * 3.0).lengthSquared())
            painter.setPen(Qt.NoPen)
            for v0, v1, v2 in ordered:
                p0 = self._world_to_pixel(v0)
                p1 = self._world_to_pixel(v1)
                p2 = self._world_to_pixel(v2)
                if p0 is None or p1 is None or p2 is None:
                    continue
                # Flat shading from the face normal (relief legibility).
                n = QVector3D.crossProduct(v1 - v0, v2 - v0)
                if n.length() > 1e-9:
                    n = n.normalized()
                shade = 0.55 + 0.45 * max(0.0, abs(QVector3D.dotProduct(n, light)))
                if flat:
                    col = QColor(int(90 * shade), int(120 * shade), int(200 * shade), 150)
                else:
                    col = QColor(int(120 * shade), int(160 * shade), int(90 * shade), 150)
                painter.setBrush(col)
                painter.drawPolygon(QPolygonF([QPointF(*p0), QPointF(*p1), QPointF(*p2)]))
            painter.setBrush(Qt.NoBrush)

    def ground_height(self, x: float, y: float) -> float | None:
        """Ground elevation at a plan position, or ``None`` where none is known.

        One place to ask, so the survey-beats-DEM precedence lives here instead
        of being re-decided by every caller (drape, the elevation readout, the
        profile sampler chooser).
        """
        survey = getattr(self.scene, "photo_mesh", None)
        if survey is not None and getattr(survey, "visible", False):
            z = survey.height_at(x, y)
            if z is not None:
                return z
        t = getattr(self.scene, "terrain", None)
        if t is not None and getattr(t, "visible", False):
            return t.height_at(x, y)
        return None

    def _emit_coordinate(self, ev) -> None:
        """Publish the UTM coordinate under the cursor for the status bar.

        Rides the coalesced hover rather than every mouse event: the readout is
        for reading, and 16 updates a second is already more than an eye can
        follow. Silent without a datum — local scene metres are not a
        coordinate anybody can use.
        """
        datum = getattr(self.scene, "georef", None)
        if datum is None:
            if self._last_coordinate:
                self._last_coordinate = ""
                self.coordinateChanged.emit("")
            return
        p = ev.position().toPoint()
        world = self._world_from_pixel(p.x(), p.y())
        if world is None:
            return
        east, north, _ = datum.local_to_utm(world)
        text = (f"E {east:,.2f}  N {north:,.2f}  "
                f"{datum.zone}{datum.hemisphere}")
        z = self.ground_elevation(world.x(), world.y())
        if z is not None:
            text += f"  ·  {z:,.2f} m"
        if text != self._last_coordinate:
            self._last_coordinate = text
            self.coordinateChanged.emit(text)

    def ground_elevation(self, x: float, y: float) -> float | None:
        """Ground elevation as a REAL altitude, not a local offset.

        ``ground_height`` answers in scene metres, which is what geometry
        needs; this adds the datum's altitude back so what reaches the user is
        the number they would read off a level — 1783.19, not 37.19. Anything
        shown to a person goes through here.
        """
        z = self.ground_height(x, y)
        if z is None:
            return None
        datum = getattr(self.scene, "georef", None)
        return z + float(getattr(datum, "alt", 0.0) or 0.0)

    def vertical_reference(self) -> str:
        """Token naming what the scene's elevations are measured against, for
        labelling. See :mod:`georef.photomesh` for the meanings."""
        from georef.photomesh import VERTICAL_DEM, VERTICAL_LOCAL, VERTICAL_ODM
        survey = getattr(self.scene, "photo_mesh", None)
        if survey is not None and getattr(survey, "visible", False):
            return getattr(survey, "vertical_reference", VERTICAL_ODM)
        t = getattr(self.scene, "terrain", None)
        if t is not None and getattr(t, "visible", False):
            return VERTICAL_DEM
        return VERTICAL_LOCAL

    def has_ground_surface(self) -> bool:
        """Whether anything is showing that a trace could be draped onto."""
        for name in ("photo_mesh", "terrain"):
            obj = getattr(self.scene, name, None)
            if obj is not None and getattr(obj, "visible", False):
                return True
        return False

    def drape(self, v: QVector3D) -> QVector3D:
        """Lift a Z=0 georef point onto the ground (its relief height) when a
        ground surface is showing, so routes/markers sit on it instead of
        floating at the Z=0 reference plane. A no-op otherwise.

        The **survey wins over the DEM terrain** where both are present: it is
        the user's own flight at centimetres per pixel against 30 m global
        cells, so a trace should follow what was actually captured.
        """
        z = self.ground_height(v.x(), v.y())
        return QVector3D(v.x(), v.y(), z) if z is not None else v

    def _draw_geo_points(self, painter: QPainter) -> None:
        """Draw imported survey points (GPS / total station): a small cross
        marker with the point's name — the surveyed skeleton the user traces
        over. Reference-only; they carry their own elevation (no draping)."""
        points = getattr(self.scene, "geo_points", None)
        if not points:
            return
        ink = QColor(206, 66, 87)               # survey red — distinct from
        painter.setPen(QPen(ink, 1.6))          # cyan paths / orange selection
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        for gp in points:
            q = self._world_to_pixel(gp.position)
            if q is None:
                continue
            x, y = q
            painter.setPen(QPen(ink, 1.6))
            painter.drawLine(QPointF(x - 5, y), QPointF(x + 5, y))
            painter.drawLine(QPointF(x, y - 5), QPointF(x, y + 5))
            if gp.name:
                painter.setPen(QColor(120, 34, 48))
                painter.drawText(QPointF(x + 7, y - 4), gp.name)

    def _draw_geo_paths(self, painter: QPainter) -> None:
        """Draw committed georef paths (roads / boundaries): a coloured polyline
        with node handles. Selected paths and the hovered node highlight."""
        paths = getattr(self.scene, "geo_paths", None)
        if not paths:
            return
        base_ink = QColor(0, 190, 210)          # cyan — reads over terrain
        sel_ink = QColor(243, 115, 41)          # selection orange
        selection = self.scene.selection
        hover_node = getattr(self, "_hover_geo_node", None)
        for path in paths:
            ink = sel_ink if path in selection else base_ink
            pix = [self._world_to_pixel(self.drape(p)) for p in path.points]
            painter.setPen(QPen(ink, 2.5))
            for a, b in zip(pix, pix[1:]):
                if a is not None and b is not None:
                    painter.drawLine(QPointF(*a), QPointF(*b))
            if path.closed and len(pix) > 2 and pix[0] and pix[-1]:
                painter.drawLine(QPointF(*pix[-1]), QPointF(*pix[0]))
            # Node handles.
            painter.setBrush(ink)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            for i, q in enumerate(pix):
                if q is None:
                    continue
                r = 5.0 if (hover_node == (path, i)) else 3.5
                painter.drawEllipse(QPointF(*q), r, r)
            painter.setBrush(Qt.NoBrush)
            # Area + perimeter label at the centroid of a selected polygon.
            if path in selection and path.closed and len(path.points) >= 3:
                self._draw_geo_path_label(painter, path)

    def _draw_geo_path_label(self, painter: QPainter, path) -> None:
        n = len(path.points)
        cx = sum(p.x() for p in path.points) / n
        cy = sum(p.y() for p in path.points) / n
        cz = sum(p.z() for p in path.points) / n
        q = self._world_to_pixel(self.drape(QVector3D(cx, cy, cz)))
        if q is None:
            return
        area = path.area()
        text = f"{tr('Area')}: {area:.1f} m²  ({area / 10000:.3f} ha)\n" \
               f"{tr('Perimeter')}: {path.perimeter():.1f} m"
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        lines = text.split("\n")
        tw = max(fm.horizontalAdvance(ln) for ln in lines)
        th = fm.height() * len(lines)
        x, y = q[0] - tw / 2, q[1] - th / 2
        painter.fillRect(int(x) - 5, int(y) - 3, tw + 10, th + 6,
                         QColor(20, 24, 30, 190))
        painter.setPen(QColor(255, 255, 255))
        for i, ln in enumerate(lines):
            painter.drawText(QPointF(x, y + fm.ascent() + i * fm.height()), ln)

    @staticmethod
    def _text_block_x(p_pos, p_anchor, block_w: float) -> float:
        """Left edge of a leader-text block whose leader ends at ``p_pos``.

        The block sits on the side of the leader end AWAY from the anchor
        (SketchUp): to the right when the anchor is left of the label, to the
        LEFT when the leader arrives from the right — otherwise the leader
        runs straight through the words (Marco's "Pileta de piedra basalto"
        label, 2026-09-02). Shared by the paint pass and the text pick so
        the hit box is the drawn box."""
        if p_anchor is not None and p_pos[0] < p_anchor[0]:
            return p_pos[0] - 6 - block_w
        return p_pos[0] + 6

    def _draw_text_labels(self, painter: QPainter) -> None:
        """Draw every leader-text annotation: a leader line from the anchor
        (hidden where geometry occludes it, like dimensions) up to the label,
        an anchor dot, and the multi-line text with a white halo."""
        labels = getattr(self.scene, "text_labels", None)
        if not labels:
            return
        style = getattr(self.scene, "dimension_style", {})
        col = style.get("color", [45, 55, 75])
        default_ink = QColor(col[0], col[1], col[2])
        sel_ink = QColor(243, 115, 41)
        selection = self.scene.selection
        font = QFont()
        font.setPointSize(int(style.get("font_size", 9)))
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        for lab in labels:
            if not self.scene.entity_visible(lab):      # hidden layer
                continue
            ink = (sel_ink if (lab in selection or lab is self._hover_entity)
                   else default_ink)
            pos = lab.position()
            p_anchor = self._world_to_pixel(lab.anchor)
            p_pos = self._world_to_pixel(pos)
            if p_pos is None:
                continue
            painter.setPen(QPen(ink, 1.2))
            self._draw_occluded_segment(painter, lab.anchor, pos)   # leader
            if p_anchor is not None and not self._is_occluded(lab.anchor):
                painter.setBrush(ink)
                painter.drawEllipse(QPointF(*p_anchor), 2.5, 2.5)
                painter.setBrush(Qt.NoBrush)
            lines = lab.text.splitlines() or [""]
            x = self._text_block_x(
                p_pos, p_anchor, max(fm.horizontalAdvance(ln) for ln in lines))
            for i, line in enumerate(lines):
                y = p_pos[1] - 4 + i * fm.height()
                painter.setPen(QPen(QColor(255, 255, 255, 230)))
                painter.drawText(QPointF(x + 1, y + 1), line)
                painter.setPen(QPen(ink))
                painter.drawText(QPointF(x, y), line)

    def _draw_dimensions(self, painter: QPainter) -> None:
        """Draw every committed static dimension: extension lines from the
        measured endpoints out to the dimension line, the dimension line with
        end ticks, and the value label at its midpoint."""
        dims = getattr(self.scene, "dimensions", None)
        if not dims:
            return
        style = getattr(self.scene, "dimension_style", {})
        col = style.get("color", [45, 55, 75])
        default_ink = QColor(col[0], col[1], col[2])
        sel_ink = QColor(243, 115, 41)  # selection orange
        selection = self.scene.selection
        font = QFont()
        font.setPointSize(int(style.get("font_size", 9)))
        font.setBold(True)
        for dim in dims:
            if not self.scene.entity_visible(dim):      # hidden layer
                continue
            ink = (sel_ink if (dim in selection or dim is self._hover_entity)
                   else default_ink)
            ap, bp = dim.line_points()
            pap = self._world_to_pixel(ap)
            pbp = self._world_to_pixel(bp)
            if pap is None or pbp is None:
                continue
            # Lines are hidden where solid geometry sits in front of them, so a
            # dimension reads as part of the model instead of floating over it.
            # Each 3D segment is sampled and only its visible runs are drawn.
            painter.setPen(QPen(ink, 1.0))
            self._draw_occluded_segment(painter, dim.a, ap)      # extension
            self._draw_occluded_segment(painter, dim.b, bp)
            painter.setPen(QPen(ink, 1.5))
            self._draw_occluded_segment(painter, ap, bp)         # dimension line
            # End ticks: short screen-space perpendiculars at each end (drawn
            # only when the end point itself is visible).
            dx, dy = pbp[0] - pap[0], pbp[1] - pap[1]
            ln = math.hypot(dx, dy)
            if ln > 1e-6:
                ox, oy = -dy / ln * 4.0, dx / ln * 4.0
                for (cx, cy), w in ((pap, ap), (pbp, bp)):
                    if not self._is_occluded(w):
                        painter.drawLine(QPointF(cx - ox, cy - oy),
                                         QPointF(cx + ox, cy + oy))
            # Value label at the dimension line's midpoint — hidden if that
            # point is behind the solid.
            mid_world = dim.midpoint()
            mid = self._world_to_pixel(mid_world)
            if mid is not None and not self._is_occluded(mid_world):
                text = dim.display_text(
                    self._format_dim_value(dim.value(), style))
                painter.setFont(font)
                painter.setPen(QPen(QColor(255, 255, 255, 230)))
                painter.drawText(QPointF(mid[0] + 5, mid[1] - 4), text)
                painter.setPen(QPen(ink))
                painter.drawText(QPointF(mid[0] + 4, mid[1] - 5), text)

    @staticmethod
    def _format_dim_value(metres: float, style: dict) -> str:
        """Format a length (metres) per the dimension style: unit + precision
        (see :mod:`core.units` — metric, decimal or fractional imperial)."""
        from core.units import format_length
        return format_length(metres, style.get("units", "m"),
                             int(style.get("decimals", 2)))

    def _draw_occluded_segment(self, painter: QPainter, p3a: QVector3D,
                               p3b: QVector3D, samples: int = 16) -> None:
        """Draw the 3D segment ``p3a``–``p3b`` in screen space, skipping the
        parts hidden behind solid geometry (CPU occlusion sample). A sub-segment
        is drawn only when both its sampled ends are visible, so the line never
        bleeds over the solid; the silhouette gap is sub-pixel at this density."""
        prev_px = None
        prev_vis = False
        for i in range(samples + 1):
            t = i / samples
            w = p3a + (p3b - p3a) * t
            px = self._world_to_pixel(w)
            vis = px is not None and not self._is_occluded(w)
            if prev_px is not None and px is not None and prev_vis and vis:
                painter.drawLine(QPointF(*prev_px), QPointF(*px))
            prev_px, prev_vis = px, vis

    def _draw_inference_marker(self, painter: QPainter) -> None:
        """Green endpoint-style square where the active tool's distance
        inference is engaged (Push/Pull snapping level with a corner or face)."""
        tool = self.active_tool
        provider = getattr(tool, "inference_marker", None) if tool is not None else None
        if not callable(provider):
            return
        result = provider()
        if result is None:
            return
        world, _kind = result
        pixel = self._world_to_pixel(world)
        if pixel is None:
            return
        px, py = pixel
        color = QColor.fromRgbF(0.16, 0.62, 0.36, 1.0)  # SketchUp endpoint green
        painter.setPen(QPen(color, 2.0))
        painter.setBrush(QColor.fromRgbF(0.16, 0.62, 0.36, 0.25))
        painter.drawRect(QRectF(px - 5, py - 5, 10, 10))

    def _draw_length_label(self, painter: QPainter) -> None:
        tool = self.active_tool
        if tool is None:
            return

        # Tool-provided label takes priority (e.g. PushPullTool's signed
        # extrusion distance). Otherwise fall back to the single-segment
        # length used by LineTool.
        label_provider = getattr(tool, "value_label", None)
        if callable(label_provider):
            result = label_provider()
            if result is None:
                return
            text, mid_world = result
        else:
            segments = tool.rubber_band_lines()
            if len(segments) != 1:
                return
            start, hover = segments[0]
            text = f"{(hover - start).length():.2f} m"
            mid_world = QVector3D(
                (start.x() + hover.x()) * 0.5,
                (start.y() + hover.y()) * 0.5,
                (start.z() + hover.z()) * 0.5,
            )
        pixel = self._world_to_pixel(mid_world)
        if pixel is None:
            return
        if self._value_buffer:
            text = f"{self._value_buffer} m"
            fg = QColor("#0F141B")
            shadow = QColor(255, 220, 130, 235)  # warm tint while typing
        else:
            fg = QColor("#0F141B")
            shadow = QColor(255, 255, 255, 220)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(shadow))
        painter.drawText(QPointF(pixel[0] + 12, pixel[1] - 7), text)
        painter.setPen(QPen(fg))
        painter.drawText(QPointF(pixel[0] + 11, pixel[1] - 8), text)

    def _measurement_text(self) -> str:
        """Live measurement string for the VCB box: the active tool's
        ``value_label`` text (rectangle dimensions, push distance, …) or the
        single-segment length a line is drawing. Empty when nothing applies."""
        tool = self.active_tool
        if tool is None:
            return ""
        provider = getattr(tool, "value_label", None)
        if callable(provider):
            result = provider()
            if result is not None:
                return result[0]
        segments = tool.rubber_band_lines()
        if len(segments) == 1:
            start, hover = segments[0]
            return f"{(hover - start).length():.2f} m"
        return ""

    def _draw_axis_lock_label(self, painter: QPainter) -> None:
        label = {
            "x": ("X", QColor(220, 56, 69)),
            "y": ("Y", QColor(40, 158, 92)),
            "z": ("Z", QColor(51, 102, 199)),
        }[self.axis_lock]
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(label[1]))
        painter.drawText(QPointF(14, 24), f"{label[0]} axis locked")

    def _draw_inference_label(self, painter: QPainter) -> None:
        """Show 'On Red Axis' style label when soft inference is active."""
        snap = self.last_snap
        if snap is None or snap.kind != "axis_inference":
            return
        names = {"x": "Red", "y": "Green", "z": "Blue"}
        name = names.get(snap.axis or "", "?")
        r, g, b = snap.color
        font = QFont()
        font.setPointSize(10)
        font.setItalic(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor.fromRgbF(r, g, b, 0.95)))
        painter.drawText(QPointF(14, 44), f"On {name} Axis (hold Shift to lock)")

    def _draw_reference_label(self, painter: QPainter) -> None:
        if self.reference_mode is None or self.reference_edge is None:
            return
        r, g, b = (0.85, 0.30, 0.80)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor.fromRgbF(r, g, b, 1.0)))
        word = "Parallel" if self.reference_mode == "parallel" else "Perpendicular"
        painter.drawText(QPointF(14, 24), f"{word} to reference edge")

    # ---- Pixel ↔ world ------------------------------------------------------
    def _pixel_to_ray(
        self, x: float, y: float
    ) -> tuple[Optional[QVector3D], Optional[QVector3D]]:
        """Camera ray (origin, unit direction) through the given pixel."""
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        ndc_x = 2.0 * x / w - 1.0
        ndc_y = 1.0 - 2.0 * y / h
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        inv, ok = mvp.inverted()
        if not ok:
            return None, None
        p_near = inv.map(QVector3D(ndc_x, ndc_y, -1.0))
        p_far = inv.map(QVector3D(ndc_x, ndc_y, 1.0))
        direction = p_far - p_near
        if direction.length() < 1e-9:
            return None, None
        return p_near, direction.normalized()

    def _world_from_pixel(self, x: int, y: int) -> Optional[QVector3D]:
        """Pixel → world hit on the *current* work plane.

        Plane choice priority:
        1. ``tool.work_plane``, captured at first click when the user clicked
           on a face — keeps the rest of the chain coplanar with that face.
        2. If a tool has a ``start_point``, the plane goes through it; its
           orientation is horizontal for most camera tilts and vertical only
           near the horizon (so dragging up/down can move in Z).
        3. If no ``start_point`` yet and the cursor is over an existing
           face, that face's plane (this is what lets the user draw a new
           polygon *inside* an existing one — e.g. on top of a box).
        4. Ground (Z=0).
        """
        origin, direction = self._pixel_to_ray(x, y)
        if origin is None or direction is None:
            return None
        plane_point, plane_normal = self._current_work_plane(cursor=(x, y))
        denom = QVector3D.dotProduct(plane_normal, direction)
        if abs(denom) < 1e-6:
            return None
        t = QVector3D.dotProduct(plane_normal, plane_point - origin) / denom
        if t < 0:
            return None
        return origin + direction * t

    # When the camera is at least this tilted off the horizon, the work plane
    # stays horizontal (XY) — that covers top, iso, and most architectural
    # angles. Only at near-horizon views does it switch to a vertical plane,
    # which is the only orientation where cursor-to-ground is ambiguous.
    HORIZON_PITCH_THRESHOLD_DEG = 15.0

    def _current_work_plane(
        self, cursor: Optional[tuple[float, float]] = None
    ) -> tuple[QVector3D, QVector3D]:
        """Return ``(point, normal)`` of the current drawing plane.

        Priority: tool-captured plane > camera-aware plane through the active
        ``start_point`` > face under cursor (face-plane inference) > ground.
        """
        tool = self.active_tool
        captured = getattr(tool, "work_plane", None) if tool is not None else None
        if captured is not None:
            # SketchUp's escape hatch: orbiting down to the horizon means "I
            # want to draw UPWARD now". A first click on a horizontal face
            # (the ground, a slab) captures its plane and would pin the whole
            # chain flat forever; at near-horizon views, where the horizontal
            # plane is unreadable anyway, a HORIZONTAL captured plane yields
            # to the vertical plane through the start point so the line can
            # rise in Z. Vertical captured planes (walls) already allow it.
            start = (getattr(tool, "start_point", None)
                     if tool is not None else None)
            if start is not None and abs(
                    captured[1].normalized().z()) > 0.94:
                vertical = self._near_horizon_vertical(start)
                if vertical is not None:
                    return vertical
            return captured

        start = getattr(tool, "start_point", None) if tool is not None else None
        if start is None:
            # First-click hover: if the cursor is over an existing face —
            # loose OR a group's (drawing/measuring on top of an imported
            # reference model) — use that face's plane so a new polygon
            # drawn "inside" it lands on the face instead of the ground.
            if cursor is not None and tool is not None:
                face, grp = self.pick_face_any(cursor[0], cursor[1])
                if face is not None:
                    from core.snap import face_plane_world
                    return face_plane_world(face, getattr(grp, "xform", None))
                # No geometry under the cursor, but maybe a reference image:
                # its plane becomes the drawing plane, which is the whole
                # point of importing a scan — you trace ON it, at its own
                # tilt, not on the ground underneath.
                image = self.image_plane_at(cursor[0], cursor[1])
                if image is not None:
                    return image.plane()
            # In an axis-aligned (standard) view, an unsnapped first point
            # belongs on the plane FACING the camera through the model
            # centre — so measuring/drawing in a front view stays in the
            # frontal plane instead of dropping to the ground. Oblique
            # orbit views keep the ground fallback (freehand unchanged).
            from core.snap import first_point_work_plane
            forward = self.camera.target - self.camera.eye()
            lo, hi = self.scene.bounds()
            center = ((lo + hi) * 0.5 if lo is not None
                      else QVector3D(0.0, 0.0, 0.0))
            plane = first_point_work_plane(forward, center)
            if plane is not None:
                return plane
            return QVector3D(0.0, 0.0, 0.0), QVector3D(0.0, 0.0, 1.0)

        base = self._start_point_plane(tool, start)
        if cursor is not None and self.axis_lock is None:
            # SketchUp's On Face for the SECOND point (Move's target, the
            # tape's far end, a line's end): the cursor over another face
            # lands ON that face. The axis inference still wins — a line
            # drawn straight up over a slab keeps rising instead of dropping
            # onto it — and the geometry being moved never offers its own
            # (already vacated) faces.
            fp = self._hover_face_plane(cursor)
            if fp is not None:
                cand = self._ray_hit_plane(cursor, base)
                angle = (getattr(tool, "magnetic_axis_deg", None)
                         or self.inference_angle_deg)
                from core.snap import _detect_axis_alignment
                if cand is None or _detect_axis_alignment(
                        start, cand, angle) is None:
                    return fp
        return base

    def _hover_face_plane(self, cursor):
        """World plane of an unselected face under the cursor, or None."""
        face, grp = self.pick_face_any(cursor[0], cursor[1])
        if face is None:
            return None
        sel = self.scene.selection
        if (grp is not None and grp in sel) or (grp is None and face in sel):
            return None
        from core.snap import face_plane_world
        return face_plane_world(face, getattr(grp, "xform", None))

    def _ray_hit_plane(self, cursor, plane):
        origin, direction = self._pixel_to_ray(cursor[0], cursor[1])
        if origin is None or direction is None:
            return None
        point, normal = plane
        denom = QVector3D.dotProduct(normal, direction)
        if abs(denom) < 1e-6:
            return None
        t = QVector3D.dotProduct(normal, point - origin) / denom
        return None if t < 0 else origin + direction * t

    def _start_point_plane(self, tool, start):
        """The camera-aware plane through the active start point."""
        forward = (self.camera.target - self.camera.eye())
        if forward.length() < 1e-9:
            return start, QVector3D(0.0, 0.0, 1.0)
        forward = forward.normalized()
        # Tools that drag geometry up and down (Move) use a camera-facing
        # vertical plane through the grab point, so pulling the mouse up raises
        # the geometry rigidly instead of sliding it across the ground (which
        # shears connected faces and looks disordered). The plane contains the
        # world Z axis; its normal is the camera's horizontal heading. Only when
        # looking nearly straight down — where height is unreadable anyway — does
        # it fall back to the horizontal plane.
        if getattr(tool, "prefers_vertical_drag", False):
            horiz = QVector3D(forward.x(), forward.y(), 0.0)
            if horiz.length() >= math.sin(math.radians(self.HORIZON_PITCH_THRESHOLD_DEG)):
                return start, horiz.normalized()
            return start, QVector3D(0.0, 0.0, 1.0)
        # |forward.z| ≈ sin(pitch). Anything tilted more than the threshold
        # keeps the horizontal plane.
        vertical = self._near_horizon_vertical(start)
        if vertical is not None:
            return vertical
        return start, QVector3D(0.0, 0.0, 1.0)

    def _near_horizon_vertical(
        self, start: QVector3D
    ) -> Optional[tuple[QVector3D, QVector3D]]:
        """The vertical work plane through ``start`` when the camera sits near
        the horizon — the only orientation where cursor→ground is ambiguous
        and dragging up must move in Z. ``None`` at steeper tilts."""
        forward = (self.camera.target - self.camera.eye())
        if forward.length() < 1e-9:
            return None
        forward = forward.normalized()
        if abs(forward.z()) >= math.sin(
                math.radians(self.HORIZON_PITCH_THRESHOLD_DEG)):
            return None
        # Pick the vertical plane whose normal is more end-on to the camera
        # so cursor motion maps cleanly to it.
        if abs(forward.x()) >= abs(forward.y()):
            return start, QVector3D(1.0, 0.0, 0.0)
        return start, QVector3D(0.0, 1.0, 0.0)

    def _project_to_lock_line(
        self,
        start: QVector3D,
        lock_dir: QVector3D,
        pixel_x: float,
        pixel_y: float,
    ) -> QVector3D:
        """Closest point on the lock line (``start``, ``lock_dir``) to the
        camera ray that passes through ``(pixel_x, pixel_y)``.

        This is what makes Z-axis locks actually let you draw vertical
        lines — moving the mouse up/down on screen slides the projected
        point along the Z line.
        """
        ray_origin, ray_dir = self._pixel_to_ray(pixel_x, pixel_y)
        if ray_origin is None or ray_dir is None:
            return start
        d1 = lock_dir.normalized()
        d2 = ray_dir
        r = start - ray_origin
        b = QVector3D.dotProduct(d1, d2)
        d = QVector3D.dotProduct(d1, r)
        e = QVector3D.dotProduct(d2, r)
        denom = 1.0 - b * b
        if abs(denom) < 1e-6:
            # Lock line is parallel to the camera ray — project the ray
            # origin onto the lock line as a stable fallback.
            t = -d
        else:
            t = (b * e - d) / denom
        return start + d1 * t

    def _world_to_pixel(self, world: QVector3D) -> Optional[tuple[float, float]]:
        """World point → screen pixel (or None if behind the camera)."""
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        clip = mvp.map(QVector4D(world.x(), world.y(), world.z(), 1.0))
        if clip.w() <= 0:
            return None
        ndc_x = clip.x() / clip.w()
        ndc_y = clip.y() / clip.w()
        px = (ndc_x * 0.5 + 0.5) * self.width()
        py = (1.0 - (ndc_y * 0.5 + 0.5)) * self.height()
        return (px, py)

    @staticmethod
    def _mesh_fingerprint(mesh):
        """Cheap content fingerprint of a group's mesh — counts, a coordinate
        checksum, render-relevant attrs and soft flags. Self-healing cache key
        (no dirty-flag invariant to maintain): any geometry/paint change on
        the group produces a new value; ~20 ms on a 17k-face mesh versus the
        ~1.5 s rebuild it lets untouched groups skip."""
        s = 0.0
        for v in mesh.vertices:
            p = v.position
            s += p.x() + p.y() * 1.000003 + p.z() * 1.000007
        a = 0
        for i, f in enumerate(mesh.faces):
            if f.attrs:
                c = f.attrs.get("color")
                t = f.attrs.get("texture")
                a ^= hash((i,
                           None if c is None else tuple(c),
                           None if not t else (t.get("path"), t.get("sw"),
                                               t.get("sh"), t.get("rot", 0)),
                           f.attrs.get("layer")))
        soft = 0
        hid = 0
        for i, e in enumerate(mesh.edges):
            if getattr(e, "soft", False):
                soft += 1
            if getattr(e, "hidden", False):
                # Index-sensitive (not a count): Hide edge A + undo + hide
                # edge B leaves the count equal while the baked edge VBO
                # differs. Deterministic mix, no hash() — the disk digest
                # reuses this term across runs.
                hid ^= ((i + 1) * 2654435761) & 0xFFFFFFFF
        return (len(mesh.vertices), len(mesh.edges), len(mesh.faces),
                round(s, 4), a, soft, hid)

    def _group_fp(self, group):
        """Fingerprint of a group's mesh, memoised per scene version — the
        chunk is consulted several times per frame/stroke (faces, edges,
        silhouette, pick index) and the fingerprint walk over a 130k-vertex
        reference model costs ~200 ms."""
        key = (id(group), self.scene.version, id(self.scene.mesh))
        memo = getattr(self, "_fp_memo", None)
        if memo is None:
            memo = self._fp_memo = {}
        fp = memo.get(key)
        if fp is None:
            if len(memo) > 64:
                memo.clear()
            _f0 = _time_mod.perf_counter() if _PERF else 0.0
            fp = memo[key] = self._mesh_fingerprint(group.mesh)
            if _PERF:
                _plog("fingerprint", (_time_mod.perf_counter() - _f0) * 1000.0,
                      extra=f"nv={fp[0]}")
        return fp

    @staticmethod
    def _translation_probe(entry, mesh):
        """When the group's mesh is the chunk, purely TRANSLATED, return the
        delta; else ``None``. Counts must match and every sampled vertex must
        have moved by the same vector. This is what keeps dragging a 100k-face
        reference group interactive: Move live-deforms the mesh per frame, and
        a full chunk rebuild at that scale takes ~15 s."""
        verts = mesh.vertices
        if (len(verts) != entry["nv"] or len(mesh.edges) != entry["ne"]
                or len(mesh.faces) != entry["nf"] or not entry["samples"]):
            return None
        i0, p0 = entry["samples"][0]
        d = verts[i0].position - QVector3D(*p0)
        if d.length() < 1e-9:
            return None                   # unchanged, or a non-geometric edit
        for i, p in entry["samples"][1:]:
            # float32 storage rounds each translated vertex differently (up
            # to ~1e-5 at building-scale coordinates); a real rotation moves
            # samples apart by millimetres — no ambiguity at this tolerance.
            if ((verts[i].position - QVector3D(*p)) - d).length() > 2e-4:
                return None
        return d

    @staticmethod
    def _samples_match(entry, mesh) -> bool:
        verts = mesh.vertices
        if len(verts) != entry["nv"]:
            return False
        for i, p in entry["samples"]:
            if (verts[i].position - QVector3D(*p)).length() > 1e-6:
                return False
        return True

    @staticmethod
    def _shift_obb(entry, d) -> None:
        """Carry the cached selection box along a pure translation.

        The box is world-space geometry cached ON the chunk, and the shift
        fast paths moved every array except this one — so moving a component
        left its selection box behind, drawing a ghost rectangle where the
        object used to be (Marco, on the hedge). ``lo``/``hi`` are the
        extents along the box's own axes, so a translation moves them by the
        projection of ``d`` on each axis; the frame itself never turns."""
        obb = entry.get("obb")
        if obb is None:
            return
        frame, lo, hi = obb
        off = [a.x() * d.x() + a.y() * d.y() + a.z() * d.z() for a in frame]
        entry["obb"] = (frame,
                        tuple(c + o for c, o in zip(lo, off)),
                        tuple(c + o for c, o in zip(hi, off)))

    def _shift_chunk(self, entry, d, mesh) -> None:
        """Translate every cached array of ``entry`` by ``d`` in place —
        NumPy adds instead of a rebuild — and refresh samples + fingerprint
        analytically."""
        import numpy as np
        dx = np.array([d.x(), d.y(), d.z()])
        self._shift_obb(entry, d)
        bb = entry.get("bbox")
        if bb is not None:
            entry["bbox"] = (
                (bb[0][0] + d.x(), bb[0][1] + d.y(), bb[0][2] + d.z()),
                (bb[1][0] + d.x(), bb[1][1] + d.y(), bb[1][2] + d.z()))

        def flat3(b):
            a = np.frombuffer(b, dtype=np.float32).reshape(-1, 3).copy()
            a += dx
            return a.astype(np.float32).tobytes()

        entry["edges"] = flat3(entry["edges"])
        vc = np.frombuffer(entry["vcol"], dtype=np.float32).reshape(-1, 6).copy()
        vc[:, :3] += dx
        entry["vcol"] = vc.astype(np.float32).tobytes()
        tex = {}
        for k, v in entry["by_texture"].items():
            a = np.frombuffer(v, dtype=np.float32).reshape(-1, 5).copy()
            a[:, :3] += dx
            tex[k] = a.astype(np.float32).tobytes()
        entry["by_texture"] = tex
        tc = {}
        for k, v in entry.get("tcol", {}).items():
            a = np.frombuffer(v, dtype=np.float32).reshape(-1, 6).copy()
            a[:, :3] += dx
            tc[k] = a.astype(np.float32).tobytes()
        entry["tcol"] = tc
        tt = {}
        for k, v in entry.get("ttex", {}).items():
            a = np.frombuffer(v, dtype=np.float32).reshape(-1, 5).copy()
            a[:, :3] += dx
            tt[k] = a.astype(np.float32).tobytes()
        entry["ttex"] = tt
        if entry.get("back_vcol"):
            a = np.frombuffer(entry["back_vcol"], dtype=np.float32).reshape(-1, 6).copy()
            a[:, :3] += dx
            entry["back_vcol"] = a.astype(np.float32).tobytes()
        bt = {}
        for k, v in entry.get("back_tex", {}).items():
            a = np.frombuffer(v, dtype=np.float32).reshape(-1, 5).copy()
            a[:, :3] += dx
            bt[k] = a.astype(np.float32).tobytes()
        entry["back_tex"] = bt
        btt = {}
        for k, v in entry.get("back_ttex", {}).items():
            a = np.frombuffer(v, dtype=np.float32).reshape(-1, 5).copy()
            a[:, :3] += dx
            btt[k] = a.astype(np.float32).tobytes()
        entry["back_ttex"] = btt
        btc = {}
        for k, v in entry.get("back_tcol", {}).items():
            a = np.frombuffer(v, dtype=np.float32).reshape(-1, 6).copy()
            a[:, :3] += dx
            btc[k] = a.astype(np.float32).tobytes()
        entry["back_tcol"] = btc
        if entry.get("fvcol"):
            a = np.frombuffer(entry["fvcol"], dtype=np.float32).reshape(-1, 6).copy()
            a[:, :3] += dx
            entry["fvcol"] = a.astype(np.float32).tobytes()
        if entry["v0"] is not None:
            entry["v0"] = entry["v0"] + dx
        for kk in ("soft_c0", "soft_c1"):
            if len(entry[kk]):
                entry[kk] = entry[kk] + dx
        if entry["soft_pts"] is not None:
            sp = entry["soft_pts"].reshape(-1, 3) + dx
            entry["soft_pts"] = sp.astype(np.float32).reshape(-1, 6)
        entry["samples"] = [(i, (mesh.vertices[i].position.x(),
                                 mesh.vertices[i].position.y(),
                                 mesh.vertices[i].position.z()))
                            for i, _p in entry["samples"]]
        entry["coordsum"] += entry["nv"] * (
            d.x() + d.y() * 1.000003 + d.z() * 1.000007)
        fp = entry["fp"]
        entry["fp"] = ((fp[0], fp[1], fp[2], round(entry["coordsum"], 4))
                       + fp[4:])
        # float32 vertex storage makes the analytic checksum drift from a
        # fresh walk — mark it approximate so the next full comparison
        # verifies by samples instead of rebuilding 100k faces for nothing.
        entry["fp_approx"] = True


    def _instance_chunk(self, group):
        """Chunk of a component INSTANCE: the shared prototype's chunk (built
        once per prototype mesh, in local coordinates) transformed to world by
        ``group.xform``. Cached per instance and re-derived only when the
        transform or the prototype changes; a pure translation delta shifts
        the cached arrays instead of re-transforming."""
        import numpy as np
        mesh = group.mesh
        wrappers = getattr(self, "_proto_wrappers", None)
        if wrappers is None:
            wrappers = self._proto_wrappers = {}
        w = wrappers.get(id(mesh))
        if w is None:
            from types import SimpleNamespace
            w = wrappers[id(mesh)] = SimpleNamespace(mesh=mesh, xform=None)
        base = self._group_chunk(w)
        xf = group.xform
        key = (id(base), tuple(xf.data()))
        cache = getattr(self, "_inst_chunks", None)
        if cache is None:
            cache = self._inst_chunks = {}
        cur = cache.get(id(group))
        if cur is not None and cur["ikey"] == key:
            return cur
        if cur is not None and cur["ikey"][0] == id(base):
            old, new = cur["ikey"][1], key[1]
            # QMatrix4x4.data() is column-major: translation at 12/13/14.
            lin = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 15)
            if all(abs(old[i] - new[i]) < 1e-12 for i in lin):
                d = QVector3D(new[12] - old[12], new[13] - old[13],
                              new[14] - old[14])
                self._shift_instance_entry(cur, d)
                cur["ikey"] = key
                cur["rev"] += 1
                return cur
        m = np.array(xf.data(), dtype=np.float64).reshape(4, 4, order="F")
        L, t = m[:3, :3], m[:3, 3]

        def tp(a):                       # positions
            return a @ L.T + t

        def tv(a):                       # direction vectors (no translation)
            return a @ L.T

        def tp32(raw, stride, cols=3):
            a = np.frombuffer(raw, np.float32).reshape(-1, stride).copy()
            a[:, :cols] = tp(a[:, :cols].astype(np.float64)).astype(np.float32)
            return a.tobytes()

        det = float(np.linalg.det(L))
        try:
            n_mat = np.linalg.inv(L).T
        except np.linalg.LinAlgError:
            n_mat = np.eye(3)

        def tn(a):                       # unit normals
            if not len(a):
                return a
            out = a @ n_mat.T
            ln = np.linalg.norm(out, axis=1, keepdims=True)
            return out / np.where(ln > 1e-12, ln, 1.0)

        sp = base["soft_pts"]
        if sp is not None:
            s6 = sp.reshape(-1, 6).astype(np.float64)
            s6[:, 0:3] = tp(s6[:, 0:3])
            s6[:, 3:6] = tp(s6[:, 3:6])
            sp = s6.astype(np.float32)
        entry = {
            "ikey": key,
            "rev": (cur["rev"] + 1) if cur is not None else 0,
            "nv": base["nv"], "ne": base["ne"], "nf": base["nf"],
            "edges": tp32(base["edges"], 3),
            "vcol": tp32(base["vcol"], 6),
            "by_texture": {p: tp32(raw, 5)
                           for p, raw in base["by_texture"].items()},
            "tcol": {a: tp32(raw, 6)
                     for a, raw in base.get("tcol", {}).items()},
            "ttex": {k: tp32(raw, 5)
                     for k, raw in base.get("ttex", {}).items()},
            "back_vcol": tp32(base.get("back_vcol", b""), 6),
            "back_tex": {k: tp32(raw, 5)
                         for k, raw in base.get("back_tex", {}).items()},
            "back_tcol": {k: tp32(raw, 6)
                          for k, raw in base.get("back_tcol", {}).items()},
            "back_ttex": {k: tp32(raw, 5)
                          for k, raw in base.get("back_ttex", {}).items()},
            "fvcol": tp32(base.get("fvcol", b""), 6),
            "faces": base["faces"],
            "areas": base["areas"] * (abs(det) ** (2.0 / 3.0)),
            "v0": tp(base["v0"]) if base["v0"] is not None else None,
            "e1": tv(base["e1"]) if base["e1"] is not None else None,
            "e2": tv(base["e2"]) if base["e2"] is not None else None,
            "tri_ent": base["tri_ent"],
            "soft_pts": sp,
            "soft_n0": tn(base["soft_n0"]),
            "soft_c0": (tp(base["soft_c0"]) if len(base["soft_c0"])
                        else base["soft_c0"]),
            "soft_n1": tn(base["soft_n1"]),
            "soft_c1": (tp(base["soft_c1"]) if len(base["soft_c1"])
                        else base["soft_c1"]),
            "soft_single": base["soft_single"],
        }
        bb = base.get("bbox")
        if bb is not None:
            corners = np.array([(x, y, z)
                                for x in (bb[0][0], bb[1][0])
                                for y in (bb[0][1], bb[1][1])
                                for z in (bb[0][2], bb[1][2])])
            tc = tp(corners)
            entry["bbox"] = (tuple(float(v) for v in tc.min(axis=0)),
                             tuple(float(v) for v in tc.max(axis=0)))
        else:
            entry["bbox"] = None
        cache[id(group)] = entry
        return entry

    def _shift_instance_entry(self, entry, d: QVector3D) -> None:
        """Translate a cached instance chunk in place (Move drag fast path)."""
        import numpy as np
        dx = np.array([d.x(), d.y(), d.z()])
        self._shift_obb(entry, d)
        bb = entry.get("bbox")
        if bb is not None:
            entry["bbox"] = (
                (bb[0][0] + d.x(), bb[0][1] + d.y(), bb[0][2] + d.z()),
                (bb[1][0] + d.x(), bb[1][1] + d.y(), bb[1][2] + d.z()))

        def shift(raw, stride):
            a = np.frombuffer(raw, np.float32).reshape(-1, stride).copy()
            a[:, :3] += dx
            return a.tobytes()

        entry["edges"] = shift(entry["edges"], 3)
        entry["vcol"] = shift(entry["vcol"], 6)
        entry["by_texture"] = {p: shift(raw, 5)
                               for p, raw in entry["by_texture"].items()}
        entry["tcol"] = {a: shift(raw, 6)
                         for a, raw in entry.get("tcol", {}).items()}
        entry["ttex"] = {k: shift(raw, 5)
                         for k, raw in entry.get("ttex", {}).items()}
        if entry.get("back_vcol"):
            entry["back_vcol"] = shift(entry["back_vcol"], 6)
        entry["back_tex"] = {k: shift(raw, 5)
                             for k, raw in entry.get("back_tex", {}).items()}
        entry["back_tcol"] = {k: shift(raw, 6)
                              for k, raw in entry.get("back_tcol", {}).items()}
        entry["back_ttex"] = {k: shift(raw, 5)
                              for k, raw in entry.get("back_ttex", {}).items()}
        if entry.get("fvcol"):
            entry["fvcol"] = shift(entry["fvcol"], 6)
        if entry["v0"] is not None:
            entry["v0"] = entry["v0"] + dx
        if entry["soft_pts"] is not None:
            s6 = entry["soft_pts"].reshape(-1, 6).copy()
            s6[:, 0:3] += dx
            s6[:, 3:6] += dx
            entry["soft_pts"] = s6.astype(np.float32)
        for kk in ("soft_c0", "soft_c1"):
            if len(entry[kk]):
                entry[kk] = entry[kk] + dx

    def _group_chunk(self, group):
        """Cached render + pick payload of one group, keyed by its content
        fingerprint. A big imported reference model (17k faces) made EVERY
        stroke beside it pay a full VBO + pick-index rebuild (~1.5 s); with
        the chunk, untouched groups just re-concatenate, and a pure
        translation (Move drag) shifts the arrays instead of rebuilding.
        Component instances resolve to their prototype's chunk transformed
        by the instance matrix."""
        if getattr(group, "xform", None) is not None:
            return self._instance_chunk(group)
        cache = getattr(self, "_group_chunks", None)
        if cache is None:
            cache = self._group_chunks = {}
        entry = cache.get(id(group))
        vkey = (self.scene.version, id(self.scene.mesh))
        mesh = group.mesh
        if entry is not None:
            if entry.get("vkey") == vkey:
                return entry
            d = self._translation_probe(entry, mesh)
            if d is not None:
                self._shift_chunk(entry, d, mesh)
                entry["vkey"] = vkey
                entry["rev"] += 1
                return entry
            # Clean fast path: no mutation primitive touched this mesh since
            # the last validation (O(1) dirty flag) and the samples agree —
            # skip the 100 ms fingerprint walk that used to run on EVERY
            # scene change (each stroke/drag frame beside a big import).
            if (not getattr(mesh, "_chunk_dirty", True)
                    and len(mesh.vertices) == entry["nv"]
                    and len(mesh.edges) == entry["ne"]
                    and len(mesh.faces) == entry["nf"]
                    and self._samples_match(entry, mesh)):
                entry["vkey"] = vkey
                return entry
        fp = self._group_fp(group)
        if entry is not None:
            same = entry["fp"] == fp
            if not same and entry.get("fp_approx"):
                # Post-shift: the checksum is approximate (float32 drift).
                # Counts/attrs/soft equal + every sampled vertex in place is
                # the real test; heal the stored fingerprint on acceptance.
                same = (entry["fp"][:3] == fp[:3]
                        and entry["fp"][4:] == fp[4:]
                        and self._samples_match(entry, group.mesh))
            if same:
                entry["fp"] = fp
                entry["fp_approx"] = False
                entry["vkey"] = vkey
                mesh._chunk_dirty = False
                return entry
        _c0 = _time_mod.perf_counter() if _PERF else 0.0
        # P4: before the expensive rebuild, try the on-disk chunk cache —
        # the arrays are deterministic from the mesh content, so a cold
        # open loads the 230k-face hedge in ~0.3 s instead of building it
        # for ~6 s. Keyed by a STABLE content digest (the in-session
        # fingerprint uses process-salted hash()).
        _loader = getattr(self, "_chunk_cache_load", None)   # stub VPs in tests
        disk = _loader(group, fp, vkey) if callable(_loader) else None
        if disk is not None:
            cache[id(group)] = disk
            mesh._chunk_dirty = False
            if _PERF:
                _plog("chunk_from_disk",
                      (_time_mod.perf_counter() - _c0) * 1000.0,
                      extra=f"faces={disk['nf']}", floor=0.0)
            return disk
        import numpy as np
        mesh = group.mesh
        edges_data = array("f")
        # Soft-edge silhouette source data: per-frame the view test runs
        # vectorised over these (99k soft edges walked in Python per frame
        # made orbiting a full imported project a 4-second slide show).
        soft_pts: list = []
        soft_n0: list = []
        soft_c0: list = []
        soft_n1: list = []
        soft_c1: list = []
        soft_single: list = []
        fprops: dict = {}

        # Faces first: one Newell walk per face yields normal + area, and the
        # normal feeds triangulate(), the shaded colour AND the soft-edge
        # props below (the naive per-call chain re-ran Newell ~3.6× per face —
        # a third of the whole build on a 160k-face import).
        from core.triangulate import triangulate as _triangulate
        vcol = array("f")             # interleaved pos(3)+rgb(3) per vertex
        by_texture: dict = {}
        tcol: dict = {}               # opacity -> interleaved pos+rgb (translucent)
        by_ttexture: dict = {}        # (op, fcull) -> {path: pos+uv}
        back_vcol_parts: list = []    # back-side colour overrides
        back_tex: dict = {}           # (path, shade) -> [byte parts]
        back_tcol: dict = {}          # opacity -> [parts] (translucent back)
        back_ttex: dict = {}          # ((path, shade), op) -> [parts]
        fcull_vcol_parts: list = []   # front copies culled to the front side
        faces: list = []
        areas: list = []
        tris: list = []
        tri_ent: list = []
        for f in mesh.faces:
            i = len(faces)
            faces.append(f)
            if len(f.loop) < 3:
                normal = QVector3D(0.0, 0.0, 1.0)
                areas.append(0.0)
                tri_list = []
            else:
                n_raw = f._newell()
                ln = n_raw.length()
                normal = n_raw / ln if ln > 1e-9 else QVector3D(0.0, 0.0, 1.0)
                areas.append(0.5 * ln)
                tri_list = _triangulate(f.vertices, f.holes, normal)
            fprops[id(f)] = normal
            back = f.attrs.get("back")
            fcull = 0
            if isinstance(back, dict):
                kind, payload = self._bucket_back_face(f, back)
                if kind == "bvcol":
                    back_vcol_parts.append(payload)
                elif kind == "btex":
                    back_tex.setdefault(payload[0], []).append(payload[1])
                elif kind == "btcol":
                    back_tcol.setdefault(payload[0], []).append(payload[1])
                elif kind == "bttex":
                    back_ttex.setdefault(payload[0], []).append(payload[1])
                if kind in ("btcol", "bttex"):
                    fcull = 1
            tex = f.attrs.get("texture")
            op = float(f.attrs.get("opacity", 1.0))
            if tex is not None and tex.get("path"):
                if op < 0.999:
                    self._append_textured_face(
                        by_ttexture.setdefault((round(op, 3), fcull), {}),
                        f, tex)
                else:
                    self._append_textured_face(by_texture, f, tex)
            else:
                col = f.attrs.get("color")
                base = tuple(col) if col is not None else self.DEFAULT_FACE_COLOR
                r, g, b = self._shaded_color(base, normal)
                if op < 0.999:
                    dest = tcol.setdefault((round(op, 3), fcull), array("f"))
                elif fcull:
                    dest = None
                else:
                    dest = vcol
                if dest is None:
                    buf = array("f")
                    for t0, t1, t2 in tri_list:
                        buf.extend([t0.x(), t0.y(), t0.z(), r, g, b,
                                    t1.x(), t1.y(), t1.z(), r, g, b,
                                    t2.x(), t2.y(), t2.z(), r, g, b])
                    fcull_vcol_parts.append(buf.tobytes())
                    dest = array("f")   # discarded sink for the shared loop
                for t0, t1, t2 in tri_list:
                    dest.extend([t0.x(), t0.y(), t0.z(), r, g, b,
                                 t1.x(), t1.y(), t1.z(), r, g, b,
                                 t2.x(), t2.y(), t2.z(), r, g, b])
            for t0, t1, t2 in tri_list:
                tris.append([[t0.x(), t0.y(), t0.z()],
                             [t1.x(), t1.y(), t1.z()],
                             [t2.x(), t2.y(), t2.z()]])
                tri_ent.append(i)

        sprops: dict = {}

        def props(f):
            r = sprops.get(id(f))
            if r is None:
                n = fprops.get(id(f))
                if n is None:
                    n = f.normal()
                c = f.centroid()
                r = sprops[id(f)] = ((n.x(), n.y(), n.z()),
                                     (c.x(), c.y(), c.z()))
            return r

        for e in mesh.edges:
            if getattr(e, "hidden", False):
                continue                  # invisible: no line, no profile
            if not getattr(e, "soft", False):
                edges_data.extend([e.a.x(), e.a.y(), e.a.z(),
                                   e.b.x(), e.b.y(), e.b.z()])
                continue
            fs = e.faces
            if len(fs) not in (1, 2):
                continue                  # dangling / non-manifold: not drawn
            soft_pts.append([e.a.x(), e.a.y(), e.a.z(),
                             e.b.x(), e.b.y(), e.b.z()])
            n0, c0 = props(fs[0])
            soft_n0.append(n0)
            soft_c0.append(c0)
            if len(fs) == 2:
                n1, c1 = props(fs[1])
                soft_single.append(False)
            else:
                n1, c1 = n0, c0
                soft_single.append(True)
            soft_n1.append(n1)
            soft_c1.append(c1)
        if tris:
            t = np.asarray(tris, dtype=np.float64)
            v0, e1, e2 = t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
            tri_ent_a = np.asarray(tri_ent, dtype=np.int64)
        else:
            v0 = e1 = e2 = tri_ent_a = None
        # World AABB of the chunk (frustum culling): triangle corners cover
        # every face; hard-edge endpoints cover edge-only content.
        blo = bhi = None
        if v0 is not None:
            allv = np.concatenate((v0, v0 + e1, v0 + e2))
            blo, bhi = allv.min(axis=0), allv.max(axis=0)
        if len(edges_data):
            ea = np.frombuffer(edges_data.tobytes(),
                               dtype=np.float32).reshape(-1, 3)
            elo, ehi = ea.min(axis=0), ea.max(axis=0)
            blo = elo if blo is None else np.minimum(blo, elo)
            bhi = ehi if bhi is None else np.maximum(bhi, ehi)
        bbox = (((float(blo[0]), float(blo[1]), float(blo[2])),
                 (float(bhi[0]), float(bhi[1]), float(bhi[2])))
                if blo is not None else None)
        verts = mesh.vertices
        nv = len(verts)
        coordsum = 0.0
        for v in verts:
            p = v.position
            coordsum += p.x() + p.y() * 1.000003 + p.z() * 1.000007
        idxs = sorted({k * max(nv - 1, 0) // 31 for k in range(32)}) if nv else []
        samples = [(i, (verts[i].position.x(), verts[i].position.y(),
                        verts[i].position.z())) for i in idxs]
        entry = {"fp": fp, "vkey": vkey, "rev": 0,
                 "nv": nv, "ne": len(mesh.edges), "nf": len(mesh.faces),
                 "samples": samples, "coordsum": coordsum, "bbox": bbox,
                 # Lazily filled by ``_group_obb``: the box in the group's own
                 # axes, which is the one the selection cue draws.
                 "obb": None,
                 "edges": edges_data.tobytes(),
                 "vcol": vcol.tobytes(),
                 "by_texture": {k: v.tobytes() for k, v in by_texture.items()},
                 "tcol": {a: v.tobytes() for a, v in tcol.items()},
                 "ttex": {(pth, a, fc): v.tobytes()
                          for (a, fc), d in by_ttexture.items()
                          for pth, v in d.items()},
                 "back_vcol": b"".join(back_vcol_parts),
                 "back_tex": {k: b"".join(v) for k, v in back_tex.items()},
                 "back_tcol": {k: b"".join(v) for k, v in back_tcol.items()},
                 "back_ttex": {k: b"".join(v) for k, v in back_ttex.items()},
                 "fvcol": b"".join(fcull_vcol_parts),
                 "faces": faces,
                 "areas": np.asarray(areas, dtype=np.float64),
                 "v0": v0, "e1": e1, "e2": e2, "tri_ent": tri_ent_a,
                      "soft_pts": (np.asarray(soft_pts, dtype=np.float32)
                              if soft_pts else None),
                 "soft_n0": np.asarray(soft_n0, dtype=np.float64),
                 "soft_c0": np.asarray(soft_c0, dtype=np.float64),
                 "soft_n1": np.asarray(soft_n1, dtype=np.float64),
                 "soft_c1": np.asarray(soft_c1, dtype=np.float64),
                 "soft_single": np.asarray(soft_single, dtype=bool)}
        if _PERF:
            _plog("chunk_rebuild", (_time_mod.perf_counter() - _c0) * 1000.0,
                  extra=f"faces={len(faces)}")
        mesh._chunk_dirty = False
        cache[id(group)] = entry
        _store = getattr(self, "_chunk_cache_store", None)   # stub VPs in tests
        if callable(_store):
            _store(mesh, entry)
        return entry

    # ---- On-disk chunk cache (P4: fast cold start) --------------------------
    # Chunk arrays are a pure function of the mesh content; persisting them
    # turns the multi-second cold build of a big group into a disk read.
    # Lives in the app's own cache dir (like extracted textures) and is
    # keyed by a STABLE sha1 content digest — a stale entry can only miss.

    _CHUNK_CACHE_MIN_FACES = 5000       # small groups rebuild faster than IO
    _CHUNK_CACHE_KEEP = 120             # files kept; oldest pruned at save

    @staticmethod
    def _chunk_cache_dir():
        from core.texture import texture_cache_root
        d = texture_cache_root().parent / "chunks"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _chunk_cache_key(mesh, fp) -> str:
        """Stable content digest: the fingerprint's counts/coordsum/soft
        plus a per-face attrs walk covering everything the chunk bakes
        (colour, texture path/uvw/scale/rot, opacity, back side). The
        session fingerprint's attrs term uses salted hash() — useless
        across runs."""
        import hashlib
        h = hashlib.sha1()
        h.update(repr((fp[0], fp[1], fp[2], fp[3], fp[5])).encode())
        if fp[6]:
            # Hidden-edge term, only when some edge IS hidden: meshes without
            # any (the overwhelming majority) keep their pre-existing digests,
            # so adding the term didn't cold-invalidate the whole cache.
            h.update(repr(("ehidden", fp[6])).encode())
        for i, f in enumerate(mesh.faces):
            a = f.attrs
            if not a:
                continue
            t = a.get("texture")
            h.update(repr((
                i, a.get("color") and tuple(a["color"]),
                None if not t else (t.get("path"), t.get("sw"), t.get("sh"),
                                    t.get("rot", 0),
                                    tuple(t.get("uvw") or ())),
                a.get("opacity"), repr(a.get("back")) if a.get("back")
                else None, a.get("layer"))).encode())
        return h.hexdigest()

    _CHUNK_CACHE_FIELDS = (
        "edges", "vcol", "by_texture", "tcol", "ttex", "back_vcol",
        "back_tex", "back_tcol", "back_ttex", "fvcol", "areas",
        "v0", "e1", "e2", "tri_ent", "soft_pts", "soft_n0", "soft_c0",
        "soft_n1", "soft_c1", "soft_single", "bbox", "coordsum",
        "nv", "ne", "nf", "samples")

    def _chunk_cache_load(self, group, fp, vkey):
        mesh = group.mesh
        if len(mesh.faces) < self._CHUNK_CACHE_MIN_FACES:
            return None
        import pickle
        try:
            path = self._chunk_cache_dir() / \
                (self._chunk_cache_key(mesh, fp) + ".chunk")
            if not path.is_file():
                return None
            with open(path, "rb") as fh:
                stored = pickle.load(fh)     # our own cache dir only
            if stored.get("nf") != len(mesh.faces):
                return None
            entry = dict(stored)
            entry.update(fp=fp, vkey=vkey, rev=0,
                         faces=list(mesh.faces))
            path.touch()                     # LRU freshness
            return entry
        except Exception:                    # noqa: BLE001 — a cache can only miss
            return None

    def _chunk_cache_store(self, mesh, entry) -> None:
        if entry["nf"] < self._CHUNK_CACHE_MIN_FACES:
            return
        import pickle
        import threading
        try:
            key = self._chunk_cache_key(mesh, entry["fp"])
            payload = {k: entry[k] for k in self._CHUNK_CACHE_FIELDS}
            cdir = self._chunk_cache_dir()
        except Exception:                    # noqa: BLE001
            return

        def write():
            try:
                path = cdir / (key + ".chunk")
                tmp = path.with_suffix(".part")
                with open(tmp, "wb") as fh:
                    pickle.dump(payload, fh, protocol=5)
                tmp.replace(path)
                files = sorted(cdir.glob("*.chunk"),
                               key=lambda p: p.stat().st_mtime)
                for old in files[:-self._CHUNK_CACHE_KEEP]:
                    old.unlink(missing_ok=True)
            except Exception:                # noqa: BLE001
                pass

        threading.Thread(target=write, daemon=True).start()

    def _np_mvp(self):
        """Current MVP as a (4, 4) float64 NumPy matrix (row-major indexing).
        ``QMatrix4x4.data()`` is column-major, hence the Fortran reshape."""
        import numpy as np
        m = self.camera.projection_matrix() * self.camera.view_matrix()
        return np.array(m.data(), dtype=np.float64).reshape(4, 4, order="F")

    def _project_px(self, pts):
        """Batch world points (N, 3) → ``(px, py, in_front)`` arrays — the
        exact math of :meth:`_world_to_pixel`, vectorised."""
        import numpy as np
        M = self._np_mvp()
        clip = pts @ M[:, :3].T + M[:, 3]
        w = clip[:, 3]
        ok = w > 0
        safe = np.where(ok, w, 1.0)
        px = (clip[:, 0] / safe * 0.5 + 0.5) * self.width()
        py = (1.0 - (clip[:, 1] / safe * 0.5 + 0.5)) * self.height()
        return px, py, ok

    @staticmethod
    def _frustum_planes(mvp):
        """The six view-frustum planes of ``mvp`` as (nx, ny, nz, d) tuples
        (Gribb–Hartmann rows); a point is inside when n·p + d ≥ 0 for all
        six. Plain floats — the per-frame consumer tests ~tens of chunk
        boxes, where NumPy overhead would dominate."""
        m = mvp.data()                    # column-major
        rows = [(m[i], m[i + 4], m[i + 8], m[i + 12]) for i in range(4)]
        r3 = rows[3]
        planes = []
        for row in rows[:3]:
            planes.append(tuple(r3[i] + row[i] for i in range(4)))
            planes.append(tuple(r3[i] - row[i] for i in range(4)))
        return planes

    @staticmethod
    def _aabb_visible(planes, lo, hi) -> bool:
        """Conservative AABB-vs-frustum p-vertex test: culled only when the
        box lies fully outside one plane (never drops visible geometry)."""
        lx, ly, lz = lo
        hx, hy, hz = hi
        for nx, ny, nz, d in planes:
            px = hx if nx >= 0.0 else lx
            py = hy if ny >= 0.0 else ly
            pz = hz if nz >= 0.0 else lz
            if nx * px + ny * py + nz * pz + d < 0.0:
                return False
        return True

    def _visible_spans(self, spans, planes, split=None):
        """Filter draw spans ``[(bbox, start, count)]`` by the frustum and
        merge adjacent survivors: returns ``([(start, count)], culled)``.
        ``bbox None`` = always drawn (loose geometry, unknown extents).

        ``split`` (a vertex offset) is a boundary merging never crosses, so
        the caller can still tell the two sides apart — the faded context
        before it, the group being edited from it on."""
        out: list = []
        culled = 0
        for bbox, start, count in spans:
            if not count:
                continue
            if bbox is not None and not self._aabb_visible(
                    planes, bbox[0], bbox[1]):
                culled += count
                continue
            if (out and out[-1][0] + out[-1][1] == start
                    and not (split is not None
                             and out[-1][0] < split <= start)):
                out[-1] = (out[-1][0], out[-1][1] + count)
            else:
                out.append((start, count))
        return out, culled

    def _tex_run_spans(self, parts, planes, fading: bool):
        """Frustum-culled draw spans of one texture run, split into
        ``(context, subject)`` when the edited group's surroundings are
        fading. Without a fade everything is context and ``subject`` is
        empty, so callers draw one list either way."""
        if not fading:
            return self._visible_spans(
                [(bb, s, n) for bb, s, n, _ in parts], planes)[0], []
        ctx = self._visible_spans(
            [(bb, s, n) for bb, s, n, sub in parts if not sub], planes)[0]
        subj = self._visible_spans(
            [(bb, s, n) for bb, s, n, sub in parts if sub], planes)[0]
        return ctx, subj

    def _pick_index(self):
        """Flat NumPy pick index of the scene — triangles of every loose and
        group face (with visibility/selectability masks and areas) plus the
        loose edges — rebuilt when the scene changes.

        Every mouse-move pick used to walk the mesh in Python re-running
        earcut per face (~1–2 s per move against an imported 17k-triangle
        building — the app read as frozen); batched over this index a pick
        is a couple of milliseconds."""
        key = (_cache_ver(self), id(self.scene.mesh))
        cached = getattr(self, "_pick_index_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        _p0 = _time_mod.perf_counter() if _PERF else 0.0
        import numpy as np
        from types import SimpleNamespace
        scene = self.scene
        entities: list = []           # (face, group_or_None)
        ent_area: list = []
        ent_sel: list = []
        ent_vis: list = []
        ent_loose: list = []
        tris: list = []
        tri_ent: list = []

        # Stub viewports in tests call this unbound — fall back to the
        # uncached face methods when the memo helpers aren't there.
        area_of = getattr(self, "_area_of", None) or (lambda f: f.area())
        tris_of = getattr(self, "_tris_of", None) or \
            (lambda f: f.triangulate())

        def add_face(f, grp, vis, sel):
            i = len(entities)
            entities.append((f, grp))
            ent_area.append(area_of(f))
            ent_vis.append(vis)
            ent_sel.append(sel)
            ent_loose.append(grp is None)
            for t0, t1, t2 in tris_of(f):
                tris.append((t0.x(), t0.y(), t0.z(),
                             t1.x(), t1.y(), t1.z(),
                             t2.x(), t2.y(), t2.z()))
                tri_ent.append(i)

        for f in scene.faces:
            add_face(f, None, scene.entity_visible(f),
                     scene.entity_selectable(f))

        # Loose part → arrays; groups append their cached chunk arrays.
        if tris:
            t = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
            v0s = [t[:, 0]]
            e1s = [t[:, 1] - t[:, 0]]
            e2s = [t[:, 2] - t[:, 0]]
            tents = [np.asarray(tri_ent, dtype=np.int64)]
        else:
            v0s, e1s, e2s, tents = [], [], [], []
        areas = [np.asarray(ent_area, dtype=np.float64)]
        vis_parts = [np.asarray(ent_vis, dtype=bool)]
        sel_parts = [np.asarray(ent_sel, dtype=bool)]
        loose_parts = [np.asarray(ent_loose, dtype=bool)]

        # Per-chunk triangle spans (P3): a hover/zoom ray prefilters chunks
        # by AABB and runs Möller-Trumbore only on the spans it crosses.
        tri_spans: list = [(None, 0, len(tris))] if tris else []
        if scene.edit_group is None:
            # The group block is cached across versions (keyed by each
            # chunk's identity + rev + flags): re-deriving per-face masks and
            # re-offsetting 300k triangle rows per scene change cost ~130 ms
            # per stroke/drag frame beside a big import.
            sig = []
            chunks = []
            for g in self._placements():
                if getattr(g, "billboard", False):
                    continue          # per-frame quad; picked separately
                gvis = scene.entity_visible(g)
                gsel = scene.entity_selectable(g)
                if not (gvis or gsel):
                    continue
                chunk = self._group_chunk(g)
                if not chunk["faces"]:
                    continue
                sig.append((id(g), id(chunk), chunk["rev"], gvis, gsel))
                chunks.append((g, chunk, gvis, gsel))
            blk = getattr(self, "_pick_block", None)
            frozen = getattr(self, "_frozen_cache_version", None) is not None
            if blk is None or (blk[0] != tuple(sig) and not frozen):
                b_entities: list = []
                b_v0, b_e1, b_e2, b_te = [], [], [], []
                b_area, b_vis, b_sel = [], [], []
                b_spans: list = []    # (bbox, tri start, count) per chunk
                b_tri_off = 0
                # Group hard edges, flat — pick_group's fallback (cursor over
                # empty space / lines-only group) walked every group edge in
                # Python (~300 ms per mouse move against a 300k-edge import).
                b_gea, b_geb, b_ggi = [], [], []
                b_ggroups: list = []
                for g, chunk, gvis, gsel in chunks:
                    n = len(chunk["faces"])
                    off = len(b_entities)
                    owner = self._owner_of(g)
                    b_entities.extend((f, owner) for f in chunk["faces"])
                    b_area.append(chunk["areas"])
                    b_vis.append(np.full(n, gvis, dtype=bool))
                    b_sel.append(np.full(n, gsel, dtype=bool))
                    if chunk["v0"] is not None:
                        b_v0.append(chunk["v0"])
                        b_e1.append(chunk["e1"])
                        b_e2.append(chunk["e2"])
                        b_te.append(chunk["tri_ent"] + off)
                        b_spans.append((chunk.get("bbox"), b_tri_off,
                                        len(chunk["v0"])))
                        b_tri_off += len(chunk["v0"])
                    if gsel and chunk["edges"]:
                        ge = np.frombuffer(chunk["edges"], dtype=np.float32)
                        ge = ge.reshape(-1, 2, 3).astype(np.float64)
                        b_gea.append(ge[:, 0])
                        b_geb.append(ge[:, 1])
                        b_ggi.append(np.full(len(ge), len(b_ggroups),
                                             dtype=np.int64))
                        b_ggroups.append(owner)
                blk = (tuple(sig), {
                    "entities": b_entities,
                    "areas": (np.concatenate(b_area) if b_area
                              else np.empty(0)),
                    "vis": (np.concatenate(b_vis) if b_vis
                            else np.empty(0, bool)),
                    "sel": (np.concatenate(b_sel) if b_sel
                            else np.empty(0, bool)),
                    "v0": np.concatenate(b_v0) if b_v0 else None,
                    "e1": np.concatenate(b_e1) if b_v0 else None,
                    "e2": np.concatenate(b_e2) if b_v0 else None,
                    "te": np.concatenate(b_te) if b_v0 else None,
                    "gedge_a": np.concatenate(b_gea) if b_gea else None,
                    "gedge_b": np.concatenate(b_geb) if b_gea else None,
                    "gedge_gi": np.concatenate(b_ggi) if b_gea else None,
                    "gedge_groups": b_ggroups,
                    "spans": b_spans,
                })
                self._pick_block = blk
            block = blk[1]
            if block["entities"]:
                offset = len(entities)
                entities.extend(block["entities"])
                areas.append(block["areas"])
                vis_parts.append(block["vis"])
                sel_parts.append(block["sel"])
                loose_parts.append(
                    np.zeros(len(block["entities"]), dtype=bool))
                if block["v0"] is not None:
                    v0s.append(block["v0"])
                    e1s.append(block["e1"])
                    e2s.append(block["e2"])
                    tents.append(block["te"] + offset)
                    tri_spans += [(bb, len(tris) + s, n)
                                  for bb, s, n in block.get("spans", ())]

        gedge_a = gedge_b = gedge_gi = None
        gedge_groups: list = []
        if scene.edit_group is None:
            block = self._pick_block[1] if getattr(self, "_pick_block", None) \
                else {}
            gedge_a = block.get("gedge_a")
            gedge_b = block.get("gedge_b")
            gedge_gi = block.get("gedge_gi")
            gedge_groups = block.get("gedge_groups", [])

        edges: list = []
        ea: list = []
        eb: list = []
        esel: list = []
        for e in scene.edges:
            edges.append(e)
            ea.append([e.a.x(), e.a.y(), e.a.z()])
            eb.append([e.b.x(), e.b.y(), e.b.z()])
            esel.append(scene.entity_selectable(e))

        idx = SimpleNamespace(
            entities=entities,
            ent_area=np.concatenate(areas) if entities else np.empty(0),
            ent_sel=np.concatenate(sel_parts) if entities else np.empty(0, bool),
            ent_vis=np.concatenate(vis_parts) if entities else np.empty(0, bool),
            ent_loose=(np.concatenate(loose_parts) if entities
                       else np.empty(0, bool)),
            tri_v0=np.concatenate(v0s) if v0s else None,
            tri_e1=np.concatenate(e1s) if v0s else None,
            tri_e2=np.concatenate(e2s) if v0s else None,
            tri_ent=np.concatenate(tents) if v0s else None,
            edges=edges,
            edge_a=np.asarray(ea, dtype=np.float64) if edges else None,
            edge_b=np.asarray(eb, dtype=np.float64) if edges else None,
            edge_sel=np.asarray(esel, dtype=bool) if edges else None,
            gedge_a=gedge_a,
            gedge_b=gedge_b,
            gedge_gi=gedge_gi,
            gedge_groups=gedge_groups,
            tri_spans=None,
        )
        # Spans must tile the triangle array exactly, or the prefilter would
        # silently drop triangles (a stale cached block predating spans).
        total_tris = len(idx.tri_v0) if idx.tri_v0 is not None else 0
        if tri_spans and sum(n for _, _, n in tri_spans) == total_tris:
            idx.tri_spans = tri_spans
        if _PERF:
            _plog("pick_index", (_time_mod.perf_counter() - _p0) * 1000.0)
        self._pick_index_cache = (key, idx)
        return idx

    def _ray_hits(self, idx, origin, direction, ent_mask,
                  reduce_global: bool = False):
        """Per-entity nearest ray parameter over the index triangles whose
        entity passes ``ent_mask``. Returns an (E,) array of t (``inf`` = no
        hit), the single nearest t as a float when ``reduce_global``, or
        ``None`` when the index has no triangles. Same acceptance
        thresholds as :func:`_ray_triangle`.

        P3: the Möller–Trumbore pass runs per chunk SPAN on array views,
        after a ray-vs-AABB prefilter — a hover/zoom ray only pays for the
        chunks it actually crosses (the full 700k-row pass cost 25–45 ms
        per pick against the piscina scene)."""
        import numpy as np
        if idx.tri_v0 is None:
            return None
        o = np.array([origin.x(), origin.y(), origin.z()])
        d = np.array([direction.x(), direction.y(), direction.z()])
        spans = getattr(idx, "tri_spans", None) or [(None, 0, len(idx.tri_v0))]
        o3 = (float(o[0]), float(o[1]), float(o[2]))
        d3 = (float(d[0]), float(d[1]), float(d[2]))
        best = float("inf")
        face_t = None if reduce_global else np.full(len(idx.entities), np.inf)
        for bb, s0, n in spans:
            if not n:
                continue
            if bb is not None and not _ray_aabb(o3, d3, bb[0], bb[1]):
                continue
            v0 = idx.tri_v0[s0:s0 + n]
            e1 = idx.tri_e1[s0:s0 + n]
            e2 = idx.tri_e2[s0:s0 + n]
            te = idx.tri_ent[s0:s0 + n]
            p = np.cross(d, e2)
            det = np.einsum("ij,ij->i", e1, p)
            ok = np.abs(det) > 1e-6
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            s = o - v0
            u = np.einsum("ij,ij->i", s, p) * inv
            q = np.cross(s, e1)
            v = (q @ d) * inv
            t = np.einsum("ij,ij->i", e2, q) * inv
            hit = (ok & (u >= 0.0) & (u <= 1.0) & (v >= 0.0) & (u + v <= 1.0)
                   & (t > 1e-6) & ent_mask[te])
            if reduce_global:
                # Zoom focus wants ONE nearest t, not per-entity buckets.
                th = t[hit]
                if len(th):
                    tm = float(th.min())
                    if tm < best:
                        best = tm
            else:
                hit_rows = np.where(hit)[0]
                if len(hit_rows):
                    # minimum.at only over the triangles the ray actually
                    # hits (a handful) — over the full array it alone cost
                    # ~100 ms per snap hover.
                    np.minimum.at(face_t, te[hit_rows], t[hit_rows])
        return best if reduce_global else face_t

    def _hover_face_t(self, idx, origin, direction):
        """Per-entity nearest-hit ``t`` against every *selectable* entity,
        memoised for the current cursor ray. One SelectTool hover fires
        pick_group + pick_face on the same mouse move, and each used to re-run
        the full Möller–Trumbore pass (~20 ms over a 260k-triangle import);
        they now share one pass and post-mask by loose/group."""
        key = (self.scene.version, id(self.scene.mesh),
               origin.x(), origin.y(), origin.z(),
               direction.x(), direction.y(), direction.z())
        cached = getattr(self, "_hover_hits_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        face_t = self._ray_hits(idx, origin, direction, idx.ent_sel)
        sp = _active_cut(self.scene)
        if sp is not None and face_t is not None:
            # Hits beyond the active cut are on clipped-away geometry.
            import numpy as np
            finite = np.isfinite(face_t)
            if finite.any():
                o = np.array([origin.x(), origin.y(), origin.z()])
                d = np.array([direction.x(), direction.y(), direction.z()])
                n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()])
                c = float(n @ [sp.point.x(), sp.point.y(), sp.point.z()])
                pts = o + d * face_t[finite, None]
                hidden = (pts @ n - c) > 1e-6
                vals = face_t[finite]
                vals[hidden] = np.inf
                face_t[finite] = vals
        self._hover_hits_cache = (key, face_t)
        return face_t

    def pick_edge(self, screen_x: float, screen_y: float):
        """Return the edge closest to ``(screen_x, screen_y)`` within threshold."""
        import numpy as np
        idx = self._pick_index()
        if idx.edge_a is None:
            return None
        ax, ay, oka = self._project_px(idx.edge_a)
        bx, by, okb = self._project_px(idx.edge_b)
        ok = oka & okb & idx.edge_sel
        sp = _active_cut(self.scene)
        if sp is not None:
            n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()])
            c = float(n @ [sp.point.x(), sp.point.y(), sp.point.z()])
            da = idx.edge_a @ n - c
            db = idx.edge_b @ n - c
            ok &= ~((da > 1e-6) & (db > 1e-6))
        if not ok.any():
            return None
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        safe = np.where(l2 > 1e-12, l2, 1.0)
        t = np.clip(((screen_x - ax) * dx + (screen_y - ay) * dy) / safe,
                    0.0, 1.0)
        d = np.hypot(ax + t * dx - screen_x, ay + t * dy - screen_y)
        d = np.where(ok, d, np.inf)
        i = int(np.argmin(d))
        return idx.edges[i] if d[i] < self.pick_threshold_px else None

    def pick_dimension(self, screen_x: float, screen_y: float):
        """Return the dimension whose lines (extension + dimension line) are
        closest to the cursor within the pick threshold, or ``None``."""
        dims = getattr(self.scene, "dimensions", None)
        if not dims:
            return None
        best = None
        best_d = self.pick_threshold_px
        for dim in dims:
            if not self.scene.entity_selectable(dim):   # hidden / locked
                continue
            ap, bp = dim.line_points()
            for s, e in ((dim.a, ap), (dim.b, bp), (ap, bp)):
                ps = self._world_to_pixel(s)
                pe = self._world_to_pixel(e)
                if ps is None or pe is None:
                    continue
                d = _point_to_segment_distance_2d((screen_x, screen_y), ps, pe)
                if d < best_d:
                    best_d = d
                    best = dim
        return best

    def pick_text_label(self, screen_x: float, screen_y: float,
                        rect_only: bool = False):
        """Return the leader-text label under the cursor, or ``None``.

        A click anywhere on the drawn text block (same font-metrics layout
        as ``_draw_text_labels``) is a hit — the glyphs are what the user
        aims at. Failing that, the label position and the leader line count
        within the pick threshold. ``rect_only`` restricts to the text
        block: the block overdraws all geometry, so that hit outranks edge
        and face picks, while the (thin) leader keeps normal priority."""
        labels = getattr(self.scene, "text_labels", None)
        if not labels:
            return None
        style = getattr(self.scene, "dimension_style", {})
        font = QFont()
        font.setPointSize(int(style.get("font_size", 9)))
        font.setBold(True)
        fm = QFontMetrics(font)
        best, best_d = None, self.pick_threshold_px * 2.0
        for lab in labels:
            if not self.scene.entity_selectable(lab):   # hidden / locked
                continue
            pp = self._world_to_pixel(lab.position())
            if pp is None:
                continue
            pa = self._world_to_pixel(lab.anchor)
            # The text block: lines start at _text_block_x(...), first
            # baseline at pp.y - 4, one fm.height() apart (mirror of
            # _draw_text_labels).
            lines = lab.text.splitlines() or [""]
            x0 = self._text_block_x(
                pp, pa, max(fm.horizontalAdvance(ln) for ln in lines))
            for i, line in enumerate(lines):
                base = pp[1] - 4 + i * fm.height()
                if (x0 - 3 <= screen_x <= x0 + fm.horizontalAdvance(line) + 3
                        and base - fm.ascent() - 3 <= screen_y
                        <= base + fm.descent() + 3):
                    return lab
            if rect_only:
                continue
            d = math.hypot(pp[0] - screen_x, pp[1] - screen_y)
            if pa is not None:
                d = min(d, _point_to_segment_distance_2d(
                    (screen_x, screen_y), pa, pp))
            if d < best_d:
                best_d = d
                best = lab
        return None if rect_only else best

    def pick_geopath(self, screen_x: float, screen_y: float):
        """Return the georef path whose polyline is closest to the cursor within
        the pick threshold, or ``None`` (Track G)."""
        paths = getattr(self.scene, "geo_paths", None)
        if not paths:
            return None
        best, best_d = None, self.pick_threshold_px
        for path in paths:
            for a, b in path.segments():
                pa = self._world_to_pixel(self.drape(a))
                pb = self._world_to_pixel(self.drape(b))
                if pa is None or pb is None:
                    continue
                d = _point_to_segment_distance_2d((screen_x, screen_y), pa, pb)
                if d < best_d:
                    best_d = d
                    best = path
        return best

    @staticmethod
    def _tool_busy(tool) -> bool:
        """Whether the active tool has an operation in progress that Esc should
        cancel before falling through to clearing the selection: an unfinished
        chain (start_point / nodes), a drag (dragging / grab / node edit), or
        an eraser stroke."""
        for attr in ("start_point", "dragging", "grab", "_drag"):
            if getattr(tool, attr, None):
                return True
        if getattr(tool, "nodes", None):
            return True
        if getattr(tool, "_stroke", False):
            return True
        return False

    def _gedge_screen(self):
        """Screen-projected endpoints of every group hard edge —
        ``(ax, ay, bx, by, ok)`` arrays, cached until the scene or the
        camera moves. Shared by pick_group's edge fallback and the snap
        prefilter (during a drawing hover the camera is still, so the two
        big projections run once, not per mouse move)."""
        idx = self._pick_index()
        if idx.gedge_a is None or not len(idx.gedge_a):
            return None
        M = self._np_mvp()
        key = (self.scene.version, id(self.scene.mesh), M.tobytes(),
               self.width(), self.height())
        cached = getattr(self, "_gedge_px_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        ax, ay, oka = self._project_px(idx.gedge_a)
        bx, by, okb = self._project_px(idx.gedge_b)
        data = (ax, ay, bx, by, oka & okb)
        self._gedge_px_cache = (key, data)
        return data

    def _ledge_screen(self):
        """Screen-projected endpoints of every LOOSE edge — the
        ``_gedge_screen`` twin for the snap prefilter after an explode
        leaves a big loose mesh. Cached until the scene/camera moves."""
        idx = self._pick_index()
        if idx.edge_a is None or not len(idx.edge_a):
            return None
        M = self._np_mvp()
        key = (self.scene.version, id(self.scene.mesh), M.tobytes(),
               self.width(), self.height())
        cached = getattr(self, "_ledge_px_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        ax, ay, oka = self._project_px(idx.edge_a)
        bx, by, okb = self._project_px(idx.edge_b)
        data = (ax, ay, bx, by, oka & okb)
        self._ledge_px_cache = (key, data)
        return data

    def _nearby_loose_edges(self, px: float, py: float,
                            radius_px: float = 64.0, cap: int = 400) -> list:
        """The loose edges whose screen segment passes near the cursor —
        real Edge objects, nearest first, at most ``cap``."""
        proj = self._ledge_screen()
        if proj is None:
            return []
        import numpy as np
        ax, ay, bx, by, ok = proj
        if not ok.any():
            return []
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        safe = np.where(l2 > 1e-12, l2, 1.0)
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / safe, 0.0, 1.0)
        d = np.hypot(ax + t * dx - px, ay + t * dy - py)
        d = np.where(ok, d, np.inf)
        cand = np.where(d < radius_px)[0]
        if len(cand) > cap:
            cand = cand[np.argsort(d[cand])[:cap]]
        idx = self._pick_index()
        edges = idx.edges
        n = len(edges)
        return [edges[int(i)] for i in cand if int(i) < n]

    def _nearby_group_edges(self, px: float, py: float,
                            radius_px: float = 48.0, cap: int = 48) -> list:
        """Group hard edges whose screen-space segment passes within
        ``radius_px`` of the cursor, as :class:`_SnapEdge` pseudo-edges —
        at most ``cap``, nearest first. Vectorised prefilter:
        ``compute_snap`` walks its edge list in Python several times per
        hover, so feeding it ALL 160k edges of an import would freeze every
        mouse move; the ~dozens near the cursor cover the point/edge snaps
        the user can actually see."""
        proj = self._gedge_screen()
        if proj is None:
            return []
        import numpy as np
        ax, ay, bx, by, ok = proj
        if not ok.any():
            return []
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        safe = np.where(l2 > 1e-12, l2, 1.0)
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / safe, 0.0, 1.0)
        d = np.hypot(ax + t * dx - px, ay + t * dy - py)
        d = np.where(ok, d, np.inf)
        cand = np.where(d < radius_px)[0]
        if len(cand) > cap:
            cand = cand[np.argsort(d[cand])[:cap]]
        idx = self._pick_index()
        ga, gb = idx.gedge_a, idx.gedge_b
        return [_SnapEdge(QVector3D(*ga[i]), QVector3D(*gb[i]))
                for i in cand]

    def _billboard_snap_edges(self) -> list:
        """Pseudo-edges for face-me billboards: the base edge and the vertical
        centre axis of the quad AS DRAWN this frame — so a figure's feet (its
        anchor point), base corners and head snap like real geometry when
        placing or measuring against it. The group a transform tool is
        currently dragging is excluded (it would snap to itself)."""
        moving = getattr(self.active_tool, "_group", None)
        out: list = []
        for g in self._placements():
            if not getattr(g, "billboard", False) or g is moving:
                continue
            if not self.scene.entity_selectable(g):
                continue
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            c = quad[0]
            base_mid = (c[0] + c[1]) * 0.5
            top_mid = (c[2] + c[3]) * 0.5
            out.append(_SnapEdge(QVector3D(c[0]), QVector3D(c[1])))
            out.append(_SnapEdge(base_mid, top_mid))
        return out

    def _snap_scene(self, px: Optional[float] = None,
                    py: Optional[float] = None):
        """The scene the snap engine sees: loose edges, construction guides as
        pseudo-edges (``Guide.a/.b`` span the long segment), and — when the
        cursor position is given — the group edges near it plus the face-me
        billboard anchors, so drawing and dimensioning over an imported
        reference model snaps to its corners and edges."""
        # Guide lines are clipped to the part in front of the camera so the
        # snap engine gets projectable endpoints (an endpoint behind the eye
        # used to kill on-line snapping in ordinary 3D views); guide POINTS
        # snap as degenerate pseudo-edges, exactly like survey points.
        lines = []
        for g in getattr(self.scene, "guides", None) or []:
            if g.is_line:
                seg = self._clip_segment_front(*g.segment())
                if seg is not None:
                    lines.append(_SnapEdge(*seg))
            else:
                lines.append(_SnapEdge(QVector3D(g.point), QVector3D(g.point)))
        # Reference-image borders snap like guides: aligning a scan against
        # real geometry (or drawing to its edge) is what tracing needs.
        for im in getattr(self.scene, "image_planes", None) or []:
            if getattr(im, "locked", False) or not self.scene.entity_selectable(im):
                continue
            for a, b in im.border_edges():
                seg = self._clip_segment_front(a, b)
                if seg is not None:
                    lines.append(_SnapEdge(*seg))
        near = self._nearby_group_edges(px, py) if px is not None else []
        if px is not None:
            near += self._billboard_snap_edges()
        near += self._selection_box_points()
        sp = _active_cut(self.scene)
        if sp is not None:
            # What the cut hides must not attract snaps (SketchUp): drop
            # edges whose BOTH endpoints are on the hidden side.
            def _kept(e):
                return not (sp.side(e.a) > 1e-6 and sp.side(e.b) > 1e-6)
            near = [e for e in near if _kept(e)]
        # Survey points snap as degenerate pseudo-edges: the endpoint snap
        # lands EXACTLY on the surveyed coordinate (the municipal flow's whole
        # point); direction-based inferences skip zero-length edges safely.
        for gp in getattr(self.scene, "geo_points", None) or []:
            near.append(_SnapEdge(QVector3D(gp.position),
                                  QVector3D(gp.position)))
        big = (px is not None
               and len(self.scene.edges) > _LOOSE_SNAP_CAP)
        if not lines and not near and sp is None and not big:
            return self.scene
        if big:
            loose = self._nearby_loose_edges(px, py)
        else:
            loose = list(self.scene.edges)
        loose = [e for e in loose if not getattr(e, "hidden", False)]
        if sp is not None:
            loose = [e for e in loose if _kept(e)]
        from types import SimpleNamespace
        return SimpleNamespace(edges=loose + lines + near)

    def _group_obb(self, group):
        """``(frame, lo, hi)`` of the group in its OWN axes, cached on its
        chunk. A world-aligned box on a rotated object reads as skewed and
        wraps far more air than object — and its corners, which are the
        handles you grab, end up nowhere near the thing."""
        entry = self._group_chunk(group)
        obb = entry.get("obb")
        if obb is not None:
            return obb
        from core.group import (frame_from_points, oriented_bounds,
                                placement_points)
        # The corners come from the POINTS — never from a merged copy of the
        # component (see ``placement_points``).
        pos = placement_points(group)
        world = oriented_bounds(None, points=pos)         # world axes
        own = oriented_bounds(None, frame_from_points(pos if len(pos) else None),
                              points=pos)

        def volume(b):
            _f, lo, hi = b
            # A flat group has zero volume; rank those by their largest face.
            side = sorted(hi[i] - lo[i] for i in range(3))
            return side[1] * side[2] * max(side[0], 1e-6)

        # Derived axes are meaningless on organic geometry — a hedge has no
        # dominant plane, and its "own" box came out 25% LARGER than the world
        # one. Keep the derived frame only when it earns its place.
        obb = own if volume(own) < 0.9 * volume(world) else world
        entry["obb"] = obb
        return obb

    def _selection_box_points(self) -> list:
        """The corners of a selected group's bounding box, as degenerate
        pseudo-edges so the snap engine offers them as endpoints.

        SketchUp makes those corners grabbable: with a group selected they are
        what you take hold of to move it somewhere exact, and the green dot
        tells you the grab landed. The box is the group's selection cue here
        too (see ``_sync_edges``), so the corners were already on screen —
        they just were not snap targets. Costs nothing: the chunk's bbox is
        already cached, so a 230k-face group contributes eight points."""
        pts: list = []
        for ent in self.scene.selection:
            if not isinstance(ent, Group) or getattr(ent, "billboard", False):
                continue
            from core.group import oriented_box_corners
            for p in oriented_box_corners(*self._group_obb(ent)):
                pts.append(_SnapEdge(p, QVector3D(p)))
        return pts

    def pick_guide(self, screen_x: float, screen_y: float):
        """Return the construction guide nearest the cursor within the pick
        threshold, or ``None`` (for the Eraser)."""
        guides = getattr(self.scene, "guides", None)
        if not guides:
            return None
        best, best_d = None, self.pick_threshold_px
        for g in guides:
            seg = self._clip_segment_front(*g.segment())
            if seg is None:
                continue
            pa = self._world_to_pixel(seg[0])
            pb = self._world_to_pixel(seg[1])
            if pa is None or pb is None:
                continue
            d = _point_to_segment_distance_2d((screen_x, screen_y), pa, pb)
            if d < best_d:
                best_d = d
                best = g
        return best

    def pick_vertex(self, screen_x: float, screen_y: float):
        """Return the scene vertex (corner) closest to the cursor within the
        pick threshold, or ``None``. Used to acquire a corner as a 'from point'
        reference while drawing. Occluded vertices are ignored (tested in
        ascending screen distance, so the nearest visible corner wins — the
        same answer the old per-edge scan produced)."""
        import numpy as np
        idx = self._pick_index()
        parts = []
        n = 0
        if idx.edge_a is not None:
            parts += [idx.edge_a, idx.edge_b]
            n = len(idx.edges)
        m = 0
        if idx.gedge_a is not None and len(idx.gedge_a):
            # Group corners too — dimensioning/drawing over an imported
            # reference model needs its vertices as 'from points'.
            parts += [idx.gedge_a, idx.gedge_b]
            m = len(idx.gedge_a)
        if not parts:
            return None
        pts = np.concatenate(parts)
        px, py, ok = self._project_px(pts)
        d = np.where(ok, np.hypot(px - screen_x, py - screen_y), np.inf)
        cand = np.where(d < self.pick_threshold_px)[0]
        for i in cand[np.argsort(d[cand])]:
            if i < 2 * n:
                e = idx.edges[int(i) % n]
                vertex = e.a if i < n else e.b
            else:
                j = int(i) - 2 * n
                arr = idx.gedge_a if j < m else idx.gedge_b
                p = arr[j % m]
                vertex = QVector3D(p[0], p[1], p[2])
            if not self._is_occluded(vertex):
                return vertex
        return None

    def hlr_geometry(self):
        """World-space geometry for the hidden-line pass (core.hlr) as
        arrays, straight from the caches the viewport already keeps: the
        pick index's triangles, every placement chunk's hard edges and soft
        edges with their two face normals, plus the loose mesh's edges.
        ``collect_geometry``'s per-face Python walk took 5 s on the fountain
        (106k triangles) — and the composer paid it on every "Update view"
        and on every frame added; this is tens of milliseconds.

        Returns ``(tris (T,3,3), hard (E,2,3), soft (S,2,3), soft_n
        (S,2,3))``; ``soft_n[:, 1]`` is NaN where a soft edge bounds an
        open surface (no second face)."""
        import numpy as np
        scene = self.scene
        idx = self._pick_index()
        if getattr(idx, "tri_v0", None) is not None and len(idx.tri_v0):
            keep = idx.ent_vis[idx.tri_ent]
            v0 = idx.tri_v0[keep]
            tris = np.stack([v0, v0 + idx.tri_e1[keep],
                             v0 + idx.tri_e2[keep]], axis=1)
            tris = tris.astype(np.float64)
        else:
            tris = np.empty((0, 3, 3))
        hard_parts: list = []
        if getattr(idx, "gedge_a", None) is not None and len(idx.gedge_a):
            gvis = np.array([scene.entity_visible(g)
                             and not getattr(g, "billboard", False)
                             for g in idx.gedge_groups], dtype=bool)
            m = (gvis[idx.gedge_gi] if len(gvis)
                 else np.zeros(len(idx.gedge_a), dtype=bool))
            hard_parts.append(np.stack([idx.gedge_a[m], idx.gedge_b[m]],
                                       axis=1).astype(np.float64))
        soft_parts: list = []
        n_parts: list = []
        nan3 = (float("nan"),) * 3
        lh: list = []
        ls: list = []
        ln: list = []
        for e in scene.loose_mesh.edges:
            if getattr(e, "hidden", False) or not scene.entity_visible(e):
                continue
            p0 = (e.v0.position.x(), e.v0.position.y(), e.v0.position.z())
            p1 = (e.v1.position.x(), e.v1.position.y(), e.v1.position.z())
            if getattr(e, "soft", False):
                fs = [f for f in e.faces if scene.entity_visible(f)]
                if not fs:
                    continue
                na = fs[0].normal()
                nb = fs[1].normal() if len(fs) > 1 else None
                ls.append((p0, p1))
                ln.append(((na.x(), na.y(), na.z()),
                           nan3 if nb is None else (nb.x(), nb.y(), nb.z())))
            else:
                lh.append((p0, p1))
        if lh:
            hard_parts.append(np.asarray(lh, dtype=np.float64))
        if ls:
            soft_parts.append(np.asarray(ls, dtype=np.float64))
            n_parts.append(np.asarray(ln, dtype=np.float64))
        for g in self._placements():
            if (getattr(g, "billboard", False)
                    or not scene.entity_visible(g)):
                continue
            ch = self._group_chunk(g)
            sp = ch.get("soft_pts")
            if sp is None or not len(sp):
                continue
            soft_parts.append(
                np.asarray(sp, dtype=np.float64).reshape(-1, 2, 3))
            n1 = np.where(np.asarray(ch["soft_single"])[:, None], np.nan,
                          np.asarray(ch["soft_n1"], dtype=np.float64))
            n_parts.append(np.stack(
                [np.asarray(ch["soft_n0"], dtype=np.float64), n1], axis=1))
        hard = (np.concatenate(hard_parts) if hard_parts
                else np.empty((0, 2, 3)))
        soft = (np.concatenate(soft_parts) if soft_parts
                else np.empty((0, 2, 3)))
        soft_n = (np.concatenate(n_parts) if n_parts
                  else np.empty((0, 2, 3)))
        return tris, hard, soft, soft_n

    def _effective_style(self):
        """The display style this frame draws with (SketchUp Styles): the
        composer's ``plano_style`` override maps onto the same face modes,
        then a ``style_override``, else the scene's active style. Shared by
        the paint pass and the snap engine so what the eye sees and what
        the cursor may grab never disagree."""
        from core.style import Style
        if self.plano_style == "tecnico":
            return Style(name="tecnico", face_mode="hidden_line", sky=False,
                         background=(1.0, 1.0, 1.0))
        if self.plano_style == "lineas":
            return Style(name="lineas", face_mode="wireframe", sky=False,
                         background=(1.0, 1.0, 1.0))
        if self.style_override is not None:
            return self.style_override
        return getattr(self.scene, "display_style", None) or Style()

    def _is_occluded(self, world: QVector3D) -> bool:
        """Whether geometry sits between the camera and ``world`` — i.e. the
        point is hidden from the current view. Used to keep snaps from firing
        on edges and vertices the user cannot see.

        Asks the PICK INDEX, which is the only place that knows the whole
        model: it holds the loose mesh AND every group's cached triangles, in
        world space, with per-chunk boxes to prefilter the ray. The old pass
        triangulated ``scene.faces`` alone — the loose mesh — so nothing
        inside a group ever hid anything, and drawing on a box snapped
        straight through it to the edge on the far side (Marco, 2026-08-27).
        Sharing the index also means occlusion and picking can never disagree
        about what is in front.

        Only VISIBLE geometry occludes (``ent_vis``, not ``ent_sel``): an
        object on a locked layer is still solid to the eye, while one on a
        hidden layer must not hide anything. A small epsilon on the far end
        keeps a point lying ON a face — an edge on that face's boundary —
        from being reported as occluded by its own face.

        X-ray and wireframe show everything, so nothing hides a snap there
        (SketchUp: switch to X-ray to dimension the floor of a pool through
        its water). Hidden-line and shaded keep the visible-only rule.
        """
        if self._effective_style().face_mode in ("xray", "wireframe"):
            return False
        idx = self._pick_index()
        if getattr(idx, "tri_v0", None) is None:
            return False
        origin = self.camera.eye()
        delta = world - origin
        dist = delta.length()
        if dist < 1e-9:
            return False
        d = delta / dist
        sp = _active_cut(self.scene)
        if sp is None:
            # Nothing to sort out per face: the single nearest hit decides,
            # and asking for it skips allocating a per-face array on every
            # query (this fires dozens of times a frame).
            nearest = self._ray_hits(idx, origin, d, idx.ent_vis,
                                     reduce_global=True)
            return nearest is not None and nearest < dist - 1e-3
        face_t = self._ray_hits(idx, origin, d, idx.ent_vis)
        if face_t is None:
            return False
        import numpy as np
        hit = np.isfinite(face_t) & (face_t < dist - 1e-3)
        if not hit.any():
            return False
        # An active cut removes what it hides, so a hit on the clipped-away
        # side is not an occluder. A ray meets a planar face at most once, so
        # the per-face nearest hit IS the hit — testing it is exact.
        eye = np.array([origin.x(), origin.y(), origin.z()])
        dv = np.array([d.x(), d.y(), d.z()])
        n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()])
        c = float(n @ [sp.point.x(), sp.point.y(), sp.point.z()])
        pts = eye + dv * face_t[hit][:, None]
        return bool(((pts @ n - c) <= 1e-6).any())

    def pick_face(self, screen_x: float, screen_y: float):
        """Return the face the cursor ray hits, or ``None``.

        Normally that's the front-most face. But when several *coplanar* faces
        overlap at the cursor — e.g. a small rectangle drawn on a larger face
        that didn't subdivide it — the ray hits them at the same depth. In that
        case prefer the smallest one, so push/pull and select grab the inner
        face the user is pointing at instead of the big face behind it (the
        old behaviour silently pushed the whole face)."""
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is None or direction is None:
            return None
        import numpy as np
        idx = self._pick_index()
        if not idx.entities:
            return None
        face_t = self._hover_face_t(idx, origin, direction)
        if face_t is None:
            return None
        face_t = np.where(idx.ent_loose, face_t, np.inf)
        best_t = face_t.min()
        if not np.isfinite(best_t):
            return None
        eps = max(1e-4, best_t * 1e-4)
        cand = np.where(face_t <= best_t + eps)[0]
        if len(cand) == 1:
            return idx.entities[int(cand[0])][0]
        return idx.entities[int(cand[np.argmin(idx.ent_area[cand])])][0]

    def pick_face_any(self, screen_x: float, screen_y: float):
        """Front-most face under the cursor across the loose mesh **and** every
        group: returns ``(face, group_or_None)``. Same coplanar tiebreak as
        :meth:`pick_face` (the smallest of the overlapping faces wins). Lets
        Push/Pull act on a group's face directly — no "enter the group" step.

        Memoised per cursor position and view: a hover asks up to three
        times (work plane, acquisition, on-face flag) for the same answer."""
        idx = self._pick_index()
        try:
            cam = self.camera
            key = (round(screen_x, 2), round(screen_y, 2), id(idx),
                   cam.yaw, cam.pitch, cam.distance, cam.perspective,
                   cam.target.x(), cam.target.y(), cam.target.z(),
                   self.width(), self.height())
        except AttributeError:            # a bare stand-in (tests): no memo
            key = None
        cached = getattr(self, "_face_any_memo", None)
        if key is not None and cached is not None and cached[0] == key:
            return cached[1]
        result = (None, None)
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is not None and direction is not None and idx.entities:
            import numpy as np
            face_t = self._hover_face_t(idx, origin, direction)
            if face_t is not None:
                best_t = face_t.min()
                if np.isfinite(best_t):
                    eps = max(1e-4, best_t * 1e-4)
                    cand = np.where(face_t <= best_t + eps)[0]
                    if len(cand) == 1:
                        result = idx.entities[int(cand[0])]
                    else:
                        result = idx.entities[
                            int(cand[np.argmin(idx.ent_area[cand])])]
        if key is not None:
            self._face_any_memo = (key, result)
        return result

    def pick_group(self, screen_x: float, screen_y: float):
        """The group whose geometry the cursor hits (front-most face, or nearest
        edge for a group that's only lines), or ``None``."""
        if self.scene.edit_group is not None:
            return None                     # inside a group: pick content
        origin, direction = self._pixel_to_ray(screen_x, screen_y)
        if origin is not None and direction is not None:
            import numpy as np
            best = None  # (t, group)
            idx = self._pick_index()
            if idx.entities:
                face_t = self._hover_face_t(idx, origin, direction)
                if face_t is not None:
                    face_t = np.where(idx.ent_loose, np.inf, face_t)
                    i = int(np.argmin(face_t))
                    if np.isfinite(face_t[i]):
                        best = (float(face_t[i]), idx.entities[i][1])
            for g in self._placements():
                if not self.scene.entity_selectable(g):
                    continue                    # hidden or locked layer
                if getattr(g, "billboard", False):
                    quad = self._billboard_quad(g)
                    if quad is not None:
                        c = quad[0]
                        for tri in ((c[0], c[1], c[2]), (c[0], c[2], c[3])):
                            t = _ray_triangle(origin, direction, *tri)
                            if t is not None and (best is None or t < best[0]):
                                best = (t, self._owner_of(g))
            if best is not None:
                return best[1]
        # Edge fallback (cursor over empty space, or a lines-only group):
        # screen-space distance to every group hard edge, batched over the
        # cached projected arrays — the Python per-edge walk took ~300 ms per
        # mouse move against a 300k-edge imported model.
        import numpy as np
        best_d = self.pick_threshold_px
        best_g = None
        proj = self._gedge_screen()
        if proj is not None:
            ax, ay, bx, by, ok = proj
            if ok.any():
                dx, dy = bx - ax, by - ay
                l2 = dx * dx + dy * dy
                safe = np.where(l2 > 1e-12, l2, 1.0)
                t = np.clip(((screen_x - ax) * dx
                             + (screen_y - ay) * dy) / safe, 0.0, 1.0)
                d = np.hypot(ax + t * dx - screen_x,
                             ay + t * dy - screen_y)
                d = np.where(ok, d, np.inf)
                i = int(np.argmin(d))
                if d[i] < best_d:
                    idx = self._pick_index()
                    best_d = float(d[i])
                    best_g = idx.gedge_groups[int(idx.gedge_gi[i])]
        # Billboard outlines: clicking a figure exactly on its snapped feet
        # point lands ON the quad's boundary, which the ray-triangle test
        # rejects — the outline proximity test catches it.
        for g in self._placements():
            if not getattr(g, "billboard", False):
                continue
            if not self.scene.entity_selectable(g):
                continue
            quad = self._billboard_quad(g)
            if quad is None:
                continue
            c = quad[0]
            for i, j in ((0, 1), (1, 2), (2, 3), (3, 0)):
                pa = self._world_to_pixel(c[i])
                pb = self._world_to_pixel(c[j])
                if pa is None or pb is None:
                    continue
                d2 = _point_to_segment_distance_2d(
                    (screen_x, screen_y), pa, pb)
                if d2 < best_d:
                    best_d = d2
                    best_g = self._owner_of(g)
        return best_g

    # ---- Tool management ----------------------------------------------------
    def set_active_tool(self, tool: Optional[Tool]) -> None:
        if self.active_tool is tool and self.nav_mode is None:
            return
        # Picking a drawing tool always leaves camera-navigation mode.
        self.nav_mode = None
        self.unsetCursor()
        if self.active_tool is not None:
            self.active_tool.on_deactivate(self)
        self.active_tool = tool
        self._hover_entity = None  # stale highlight from the previous tool
        self.last_snap = None      # stale snap marker from the previous tool
        self._acquired_edge = None  # drop any held parallel reference
        self._acquired_point = None
        self._acquired_face_normal = None
        if tool is not None:
            tool.on_activate(self)
        self._apply_tool_cursor()
        self.measurementChanged.emit(self._measurement_text())
        self.update()

    def _apply_tool_cursor(self) -> None:
        """The pointer becomes the active tool's icon (SketchUp); Select and
        unknown tools keep the standard arrow.

        A tool that does something else under a modifier says so with the
        pointer: Paint holds Alt to SAMPLE a face's material instead of
        painting it, and SketchUp swaps the bucket for an eyedropper while
        it is down."""
        from PySide6.QtWidgets import QApplication
        from views.icons import tool_cursor
        icon = getattr(self.active_tool, "icon", None)
        if icon == "paint":
            from tools.paint import PaintTool
            if (PaintTool.sample_armed
                    or QApplication.keyboardModifiers() & Qt.AltModifier):
                icon = "eyedropper"
        cur = (tool_cursor(icon)
               if self.active_tool is not None else None)
        if cur is not None:
            self.setCursor(cur)
        else:
            self.unsetCursor()

    def _apply_nav_cursor(self) -> None:
        """The pointer for a camera nav mode: orbit / pan / the magnifier
        (SketchUp shows each navigation tool's own icon)."""
        from views.icons import tool_cursor
        if self.nav_mode in ("orbit", "pan", "zoom", "zoom_window"):
            cur = tool_cursor(self.nav_mode)
            if cur is not None:
                self.setCursor(cur)
                return
            self.setCursor(Qt.CrossCursor
                           if self.nav_mode in ("zoom", "zoom_window")
                           else Qt.OpenHandCursor)

    # ---- Copy / paste -------------------------------------------------------
    def copy_selection(self) -> bool:
        """Copy the selected faces, edges and groups into the clipboard (as
        positions, with a reference corner). Returns False if nothing is
        selected."""
        faces = [f for f in self.scene.selection if isinstance(f, Face)]
        edges = [e for e in self.scene.selection if isinstance(e, Edge)]
        groups = [g for g in self.scene.selection if isinstance(g, Group)]
        if not faces and not edges and not groups:
            return False
        # Attrs (colour, texture, layer, BIM tag) travel with each face — a
        # deep copy, so later re-paints of the original never touch the
        # clipboard snapshot.
        face_data = [
            ([QVector3D(v) for v in f.vertices],
             [[QVector3D(v) for v in h] for h in f.holes],
             copy.deepcopy(f.attrs) if f.attrs else {})
            for f in faces
        ]
        # Keep soft/curve flags so a pasted circle stays ONE selectable curve
        # (ids are remapped to fresh ones at paste time).
        edge_data = [(QVector3D(e.a), QVector3D(e.b), e.soft, e.curve)
                     for e in edges]
        # Groups are snapshotted NOW (instances keep sharing their prototype;
        # classic groups deep-copy) so editing or deleting the original later
        # never changes what Paste stamps. No preview wireframe is built here
        # any more: Paste previews the groups through the frozen-scratch VBO
        # pipeline (the old per-edge tuple walk took seconds on a leafy
        # plant, and again on EVERY preview frame — the piscina hang).
        group_data = [copy_group(g) for g in groups]
        # A classic group's snapshot becomes an identity INSTANCE of its
        # fresh mesh: every stamp is an O(1) sibling of the clipboard
        # prototype instead of a full deep copy per paste (the 230k-face
        # hedge took seconds per stamp). SketchUp semantics hold: pasted
        # copies share the definition until edited — begin_group_edit
        # already materializes instances on entry. The prototype's chunk is
        # pre-seeded from the SOURCE group's cached entry (content-identical
        # deep copy), so preview and stamps skip the from-scratch rebuild.
        old_clip = getattr(self, "clipboard", None)
        seed = getattr(self, "_seed_proto_chunk", None)
        for src, tpl in zip(groups, group_data):
            if tpl.xform is None:
                tpl.xform = QMatrix4x4()
                if callable(seed):
                    seed(tpl.mesh, src)
        # Reference corner (what the cursor holds the set by): min corner of
        # everything copied, via NumPy — one pass over vertices instead of
        # four Python min() scans over every edge endpoint.
        import numpy as np
        from core.group import np_affine
        lo = None
        pts = [p for loop, holes, _a in face_data for p in loop]
        pts += [p for _, holes, _a in face_data for h in holes for p in h]
        pts += [p for a, b, _, _ in edge_data for p in (a, b)]
        if pts:
            lo = np.array([[p.x(), p.y(), p.z()] for p in pts]).min(axis=0)
        for g in group_data:
            verts = g.mesh.vertices
            if not verts:
                continue
            arr = np.array([[v.position.x(), v.position.y(), v.position.z()]
                            for v in verts])
            if g.xform is not None:
                rot, trans = np_affine(g.xform)
                arr = arr @ rot.T + trans
            gmin = arr.min(axis=0)
            lo = gmin if lo is None else np.minimum(lo, gmin)
        if lo is None:
            return False
        ref = QVector3D(float(lo[0]), float(lo[1]), float(lo[2]))
        drop = getattr(self, "_drop_clip_protos", None)
        if old_clip and callable(drop):
            drop(old_clip)
        self.clipboard = {"faces": face_data, "edges": edge_data,
                          "groups": group_data, "ref": ref}
        return True

    def _seed_proto_chunk(self, mesh, src_group) -> None:
        """Pre-seed the prototype-chunk cache of a clipboard snapshot with
        its SOURCE group's cached chunk. The snapshot is a content-identical
        deep copy, so the seeded entry revalidates through the fingerprint
        self-heal (~120 ms) instead of a from-scratch rebuild (~7 s on the
        230k-face hedge). A wrong guess is harmless: a fingerprint mismatch
        just rebuilds."""
        cache = getattr(self, "_group_chunks", None)
        if not cache or getattr(src_group, "xform", None) is not None:
            return
        src_entry = cache.get(id(src_group))
        if src_entry is None:
            return
        from types import SimpleNamespace
        wrappers = getattr(self, "_proto_wrappers", None)
        if wrappers is None:
            wrappers = self._proto_wrappers = {}
        w = wrappers.get(id(mesh))
        if w is None:
            w = wrappers[id(mesh)] = SimpleNamespace(mesh=mesh, xform=None)
        cache[id(w)] = dict(src_entry)

    def _drop_clip_protos(self, clip) -> None:
        """A replaced clipboard's prototype chunks are dead weight (hundreds
        of MB for a big copy) — drop them unless a stamped sibling in the
        scene still shares the mesh."""
        wrappers = getattr(self, "_proto_wrappers", None)
        cache = getattr(self, "_group_chunks", None)
        if not wrappers:
            return
        from core.group import iter_placements
        live = {id(pg.mesh) for g in self.scene.groups
                for pg, _ in iter_placements(g)}
        for g in clip.get("groups", ()):
            mid = id(g.mesh)
            if mid in live:
                continue
            w = wrappers.pop(mid, None)
            if w is not None and cache:
                cache.pop(id(w), None)

    def cut_selection(self) -> bool:
        """Copy the selection, then erase it (one undoable step)."""
        if not self.copy_selection():
            return False
        from core.history import CompoundCommand, DeleteGroupCommand
        faces = [f for f in self.scene.selection if isinstance(f, Face)]
        edges = [e for e in self.scene.selection if isinstance(e, Edge)]
        groups = [g for g in self.scene.selection if isinstance(g, Group)]
        cmds: list = []
        if edges or faces:
            cmds.append(EraseSelectionCommand(edges, faces))
        cmds.extend(DeleteGroupCommand(g) for g in groups)
        if cmds:
            self.history.execute(
                cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
        self.update()
        return True

    # ---- Group-edit context (Groups v2) --------------------------------------
    def begin_group_edit(self, group) -> None:
        """Enter a group for editing (SketchUp double-click-into-group). A
        component instance opens on a world copy of its definition; the
        session's commands are remembered so leaving can fold them into ONE
        undoable share-back."""
        was_instance = (getattr(group, "xform", None) is not None
                        and not getattr(group, "children", None))
        self.scene.begin_group_edit(group)
        self._edit_undo_mark = len(self.history.undo_stack)
        self._hover_entity = None
        self._edges_version = -1     # the rest may fade out or leave the VBOs
        share = getattr(self.scene, "_edit_share", None)
        if was_instance and share is not None:
            copies = sum(1 for g in self.scene.groups if g.mesh is share[1]) + 1
            self.flash_status(tr(
                "Editing component '{name}' — the change reaches its {n} "
                "copies when you leave (Esc); Make Unique first to edit "
                "one copy only", name=group.name, n=copies), 6000)
        else:
            self.flash_status(tr(
                "Editing group '{name}' — Esc or click outside to leave",
                name=group.name), 4000)
        self.update()

    def end_group_edit(self) -> None:
        if self.scene.edit_group is None:
            return
        share = self.scene.take_edit_share()
        self.scene.end_group_edit()
        self._hover_entity = None
        self._edges_version = -1     # the rest comes back
        if share is not None:
            group, proto, xform, state0 = share
            edited = group.mesh
            if edited.capture_state() == state0:
                self.scene.restore_sharing(group, proto, xform)
                self.flash_status(tr("Left the group"), 2000)
            else:
                from core.history import ReshareInstanceCommand
                mark = getattr(self, "_edit_undo_mark",
                               len(self.history.undo_stack))
                inner = self.history.undo_stack[mark:]
                del self.history.undo_stack[mark:]
                self.history.execute(ReshareInstanceCommand(
                    group, proto, xform, edited, inner))
                copies = sum(1 for g in self.scene.groups if g.mesh is proto)
                self.flash_status(tr(
                    "Component '{name}' updated on its {n} copies",
                    name=group.name, n=copies), 4000)
        else:
            self.flash_status(tr("Left the group"), 2000)
        self.update()

    # ---- Rest-of-model context while editing a group -------------------------
    @property
    def edit_rest_mode(self) -> str:
        """``normal`` / ``fade`` / ``hide`` — how the model outside the group
        being edited reads. See :data:`EDIT_REST_MODES`."""
        return self._edit_rest_mode

    def set_edit_rest_mode(self, mode: str) -> None:
        if mode not in EDIT_REST_MODES or mode == self._edit_rest_mode:
            return
        self._edit_rest_mode = mode
        from PySide6.QtCore import QSettings
        QSettings().setValue("display/edit_rest_mode", mode)
        # "hide" keeps the rest out of the VBOs entirely, so switching to or
        # from it changes what is uploaded, not just how it is drawn.
        self._edges_version = -1
        self.update()

    def _rest_is_hidden(self) -> bool:
        """Whether the model outside the edited group is out of this frame."""
        return (self.scene.edit_group is not None
                and self._edit_rest_mode == "hide")

    def _owner_of(self, group):
        """The object a click on ``group`` must select: a nested placement
        proxy stands for the top-level group that owns it."""
        return getattr(group, "owner", None) or group

    def _draws_in_edit_context(self, group) -> bool:
        """Whether ``group`` is part of the surroundings of the group being
        edited (so it fades or hides), rather than the subject itself."""
        return (self.scene.edit_group is not None
                and self._owner_of(group) is not self.scene.edit_group)

    def set_nav_mode(self, mode: Optional[str]) -> None:
        """Enter a SketchUp-style camera navigation mode ("orbit" / "pan").

        For trackpad users with no middle mouse button: while a nav mode is
        active the left-drag drives the camera (orbit or pan). The active
        drawing tool is suspended; return to drawing by picking any tool or
        pressing Space (Select). ``None`` clears the nav mode.
        """
        if self.active_tool is not None:
            self.active_tool.on_deactivate(self)
            self.active_tool = None
        self._hover_entity = None
        self.last_snap = None
        self.nav_mode = mode
        if mode is not None:
            self._apply_nav_cursor()      # orbit / pan / magnifier icons
        else:
            self.unsetCursor()
        self.update()

    def leaveEvent(self, ev) -> None:
        if self._hover_entity is not None:
            self._hover_entity = None
            self.update()
        super().leaveEvent(ev)

    # ---- Input --------------------------------------------------------------
    def contextMenuEvent(self, ev) -> None:
        """Right-click: select what's under the cursor (SketchUp-style) and open
        a context menu of actions relevant to the current selection."""
        win = self.window()
        if not hasattr(win, "show_viewport_context_menu"):
            return
        x, y = ev.pos().x(), ev.pos().y()
        picked = (self.pick_text_label(x, y, rect_only=True)
                  or self.pick_group(x, y) or self.pick_edge(x, y)
                  or self.pick_geopath(x, y) or self.pick_dimension(x, y)
                  or self.pick_text_label(x, y)
                  or self.pick_section_plane(x, y)
                  or self.pick_guide(x, y)
                  or self.pick_face(x, y)
                  or self.pick_image_plane(x, y))
        if picked is not None and picked not in self.scene.selection:
            self.scene.select([picked])
            self.update()
        win.show_viewport_context_menu(ev.globalPos())

    def mousePressEvent(self, ev) -> None:
        self._input_t = _time_mod.monotonic()   # P0: input→paint latency
        if ev.button() == Qt.MiddleButton:
            self._last_pos = ev.position().toPoint()
            self._pan_mode = bool(ev.modifiers() & Qt.ShiftModifier)
            # SketchUp: while the wheel-drag lasts, the pointer becomes the
            # orbit (or pan) icon; the tool cursor comes back on release.
            from views.icons import tool_cursor
            cur = tool_cursor("pan" if self._pan_mode else "orbit")
            if cur is not None:
                self.setCursor(cur)
            return
        # SketchUp-style nav buttons: left-drag orbits/pans the camera.
        # Hold Shift while orbiting to pan temporarily (matches MMB+Shift).
        if ev.button() == Qt.LeftButton and self.nav_mode is not None:
            if self.nav_mode == "zoom_window":
                # Drag a rectangle; the camera zooms to it on release.
                self._zoom_box_active = True
                self._zoom_box_start = ev.position()
                self._zoom_box_cur = ev.position()
                return
            self._last_pos = ev.position().toPoint()
            self._pan_mode = (
                self.nav_mode == "pan"
                or bool(ev.modifiers() & Qt.ShiftModifier)
            )
            # The orbit/pan icon stays through the drag (SketchUp).
            self._apply_nav_cursor()
            return
        if ev.button() == Qt.LeftButton and self.active_tool is not None:
            # Triple click: a press landing right after a double-click at the
            # same spot (Qt has no native triple event). SketchUp: select all
            # connected.
            if self._is_triple_click(ev):
                self._last_double = None
                ctx = self._build_ctx(ev)
                if ctx is not None:
                    self.active_tool.on_triple_click(ctx)
                    self.update()
                return
            # Box-select tools defer the decision to release: a tiny drag is a
            # click, a real drag is a rubber-band box.
            if self.active_tool.box_select:
                self._box_active = True
                self._box_start = ev.position()
                self._box_cur = ev.position()
                return
            self._dispatch_tool_click(ev)

    def _is_triple_click(self, ev) -> bool:
        from PySide6.QtWidgets import QApplication
        last = self._last_double
        if last is None:
            return False
        t, pos = last
        return (ev.timestamp() - t
                <= QApplication.doubleClickInterval()
                and (ev.position() - pos).manhattanLength() < 8)

    def _dispatch_tool_click(self, ev, double: bool = False) -> None:
        """Forward a (double-)click to the active tool, then run the shared
        follow-ups: lock the chain to a clicked face's plane, clear the VCB."""
        had_start = getattr(self.active_tool, "start_point", None) is not None
        had_plane = getattr(self.active_tool, "work_plane", None) is not None
        face_at_click = None
        if not had_start and not had_plane:
            face_at_click, _g = self.pick_face_any(ev.position().x(),
                                                   ev.position().y())
        ctx = self._build_ctx(ev)
        if ctx is not None:
            if double:
                self.active_tool.on_double_click(ctx)
            else:
                self.active_tool.on_click(ctx)
            # If the click established a new start point on top of an
            # existing face, lock the rest of the chain to that face's
            # plane so subsequent clicks stay coplanar.
            now_start = getattr(self.active_tool, "start_point", None)
            if (
                not had_start
                and now_start is not None
                and face_at_click is not None
                and hasattr(self.active_tool, "work_plane")
            ):
                self.active_tool.work_plane = (
                    face_at_click.centroid(),
                    face_at_click.normal(),
                )
            # Any pending typed value is invalidated once the user
            # commits a point with the mouse.
            self._set_value_buffer("")
            # A command that failed was rolled back (History is
            # transactional) — surface it instead of failing silently.
            if self.history.last_error:
                self.flash_status(
                    tr("Operation failed and was undone: {err}",
                       err=self.history.last_error), 8000)
            self.update()

    def mouseDoubleClickEvent(self, ev) -> None:
        """Qt replaces the second press of a double-click with this event, so
        route it to ``tool.on_double_click`` — whose default re-runs
        ``on_click``, keeping fast click-click rhythms working for drawing
        tools while Push/Pull overrides it to repeat its last distance.

        Box-select tools (Select) get the double-click DIRECTLY (no drag box
        starts on a double), and the event is remembered so the next press in
        place counts as a triple click."""
        if ev.button() != Qt.LeftButton or self.active_tool is None \
                or self.nav_mode is not None:
            self.mousePressEvent(ev)
            return
        self._last_double = (ev.timestamp(), ev.position())
        if self.active_tool.box_select:
            ctx = self._build_ctx(ev)
            if ctx is not None:
                self.active_tool.on_double_click(ctx)
                self.update()
            return
        self._dispatch_tool_click(ev, double=True)

    def mouseMoveEvent(self, ev) -> None:
        self._input_t = _time_mod.monotonic()   # P0: input→paint latency
        if self._last_pos is not None:
            p = ev.position().toPoint()
            dx = p.x() - self._last_pos.x()
            dy = p.y() - self._last_pos.y()
            self._last_pos = p
            if self.nav_mode == "zoom":
                self.camera.zoom(-dy * 0.035)        # drag up = zoom in
            elif self._pan_mode:
                self.camera.pan(dx, dy, self.height())
            else:
                self.camera.orbit(dx, dy, self.height())
            self.update()
            return

        if self._box_active:
            self._box_cur = ev.position()
            self.update()
            return

        if self._zoom_box_active:
            self._zoom_box_cur = ev.position()
            self.update()
            return

        # Adaptive hover coalescing: against a big imported model one hover
        # costs ~25-30 ms (picks + snap) while the mouse delivers 60-125
        # events/s — processing every event backlogs the queue and the whole
        # app reads as frozen. Gate by the measured cost of the LAST hover
        # (a small model gates at ~0 → immediate), and let a trailing-edge
        # timer process the final position so the highlight never sticks.
        self._pending_hover = (ev.position(), ev.modifiers())
        now = _time_mod.monotonic()
        gate = min(0.06, getattr(self, "_hover_cost", 0.0) * 1.5)
        elapsed = now - getattr(self, "_hover_last_t", 0.0)
        if elapsed < gate:
            timer = getattr(self, "_hover_timer", None)
            if timer is None:
                from PySide6.QtCore import QTimer
                timer = self._hover_timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._run_pending_hover)
            if not timer.isActive():
                timer.start(max(1, int((gate - elapsed) * 1000) + 1))
            return
        self._run_pending_hover()

    def _run_pending_hover(self) -> None:
        pending = getattr(self, "_pending_hover", None)
        if pending is None:
            return
        self._pending_hover = None
        pos, modifiers = pending
        t0 = _time_mod.monotonic()
        self._process_hover(pos, modifiers)
        self._hover_last_t = _time_mod.monotonic()
        self._hover_cost = self._hover_last_t - t0
        if _PERF:
            # A per-move cost near ~100 ms starves paints during a tool drag
            # (the push "sticks"): name it in the log instead of hiding
            # under the frame telemetry's floor.
            _plog("hover.move", self._hover_cost * 1000.0, floor=80.0)

    def _process_hover(self, pos, modifiers) -> None:
        if self._last_pos is not None or self._box_active:
            return          # a camera drag / box select started meanwhile
        ev = _HoverEvent(pos, modifiers)
        _hp0 = _time_mod.perf_counter() if _PERF else 0.0

        def _hmark(name):
            nonlocal _hp0
            if _PERF:
                now = _time_mod.perf_counter()
                _plog(f"hover.{name}", (now - _hp0) * 1000.0, floor=200.0)
                _hp0 = now

        # Track cursor + hover edge so Down can capture a reference edge.
        self._last_mouse_pos = ev.position()
        self._emit_coordinate(ev)
        _hmark("coord")
        # Plan↔profile link (Track G): let an open profile mark the station of
        # the route point under the cursor.
        win = self.window()
        if hasattr(win, "on_viewport_hover"):
            win.on_viewport_hover(ev.position().x(), ev.position().y())
        self._hover_edge = self.pick_edge(ev.position().x(), ev.position().y())
        _hmark("pickedge")

        # While a segment is being drawn, hovering an edge acquires it as a soft
        # parallel reference; the acquisition is dropped once nothing is in
        # progress, so it never goes stale across separate draws.
        drawing = (
            self.active_tool is not None
            and getattr(self.active_tool, "start_point", None) is not None
        )
        if not drawing:
            self._acquired_edge = None
            self._acquired_point = None
            self._acquired_face_normal = None
        else:
            if self._hover_edge is not None:
                self._acquired_edge = self._hover_edge
            corner = self.pick_vertex(ev.position().x(), ev.position().y())
            if corner is not None:
                self._acquired_point = corner
            face, _g = self.pick_face_any(ev.position().x(), ev.position().y())
            if face is not None:
                from core.snap import face_plane_world
                self._acquired_face_normal = face_plane_world(
                    face, getattr(_g, "xform", None))[1]

        if self.active_tool is None:
            return
        _hmark("acquire")
        ctx = self._build_ctx(ev)
        _hmark("ctx")
        if ctx is None:
            return
        self.last_snap = ctx.snap
        self.active_tool.on_hover(ctx)
        _hmark("tool")
        self.measurementChanged.emit(self._measurement_text())
        _hmark("measure")
        self.update()

    # Below this many pixels of drag, a left press/release is a click, not a box.
    BOX_DRAG_THRESHOLD_PX = 4.0

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MiddleButton:
            self._last_pos = None
            self._pan_mode = False
            if self.nav_mode is not None:
                self._apply_nav_cursor()
            else:
                self._apply_tool_cursor()
            return

        if ev.button() == Qt.LeftButton and self._zoom_box_active:
            self._zoom_box_active = False
            start, end = self._zoom_box_start, self._zoom_box_cur
            self._zoom_box_start = None
            self._zoom_box_cur = None
            if start is not None and end is not None:
                self._zoom_to_box(start, end)
            self.update()
            return

        if ev.button() == Qt.LeftButton and self.nav_mode is not None:
            self._last_pos = None
            self._pan_mode = False
            self._apply_nav_cursor()
            return

        # Stroke tools (the Eraser): notify the release so a press-drag-release
        # stroke can commit as one step. No-op default on other tools.
        if (ev.button() == Qt.LeftButton and self.active_tool is not None
                and not self._box_active and self.nav_mode is None):
            self.active_tool.on_release(self)

        if ev.button() == Qt.LeftButton and self._box_active:
            self._box_active = False
            start = self._box_start
            end = ev.position()
            self._box_start = None
            self._box_cur = None
            tool = self.active_tool
            if tool is None or start is None:
                self.update()
                return
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            additive = bool(ev.modifiers() & Qt.ShiftModifier)
            if math.hypot(dx, dy) < self.BOX_DRAG_THRESHOLD_PX:
                # A click: pick the single entity under the cursor.
                ctx = self._build_ctx(ev)
                if ctx is not None:
                    tool.on_click(ctx)
            else:
                rect = (
                    min(start.x(), end.x()), min(start.y(), end.y()),
                    max(start.x(), end.x()), max(start.y(), end.y()),
                )
                crossing = dx < 0  # right-to-left drag = crossing selection
                tool.on_box_select(self, rect, crossing, additive)
            self.update()

    def _world_under_cursor(self, x: float, y: float) -> Optional[QVector3D]:
        """The world point the cursor points at: nearest geometry hit, else the
        ground plane (Z=0), else the focal plane through the target."""
        origin, direction = self._pixel_to_ray(x, y)
        if origin is None or direction is None:
            return None
        best_t = None
        idx = self._pick_index()
        if idx.entities:
            import numpy as np
            t = self._ray_hits(idx, origin, direction, idx.ent_vis,
                               reduce_global=True)
            if t is not None and np.isfinite(t):
                best_t = float(t)
        if best_t is not None:
            return origin + direction * best_t
        if abs(direction.z()) > 1e-6:
            t = -origin.z() / direction.z()
            if t > 0:
                return origin + direction * t
        view = (self.camera.target - self.camera.eye())
        if view.length() > 1e-9:
            view = view.normalized()
            denom = QVector3D.dotProduct(direction, view)
            if abs(denom) > 1e-6:
                t = QVector3D.dotProduct(self.camera.target - origin, view) / denom
                if t > 0:
                    return origin + direction * t
        return None

    def wheelEvent(self, ev) -> None:
        self._input_t = _time_mod.monotonic()   # P0: input→paint latency
        # Zoom toward the cursor (SketchUp-style): keep the point under the
        # pointer fixed on screen, not the origin. During a wheel burst the
        # focus is CACHED: zoom_to pins that world point, so re-picking every
        # tick both wasted ~25 ms/tick against a big model (the zoom felt
        # heavy) and let float error drift the pinned point.
        import time as _time
        steps = ev.angleDelta().y() / 120.0
        if self._invert_wheel:          # Preferences ▸ General (SketchUp's
            steps = -steps              # Compatibility ▸ invert wheel)
        pos = ev.position()
        now = _time.monotonic()

        def pose():
            c = self.camera
            t = c.target
            return (round(c.yaw, 9), round(c.pitch, 9),
                    round(c.distance, 6),
                    round(t.x(), 6), round(t.y(), 6), round(t.z(), 6))

        # The pin is anchored to the CAMERA POSE, not a time window:
        # zoom_to keeps the focus fixed on screen by construction, so slow
        # one-notch-per-second zooming reuses it indefinitely (a 1 s window
        # expired between deliberate notches and re-picked 280k triangles
        # per notch — the zoom jank). Orbit/pan or an edit changes the pose
        # or the version and honestly invalidates it.
        cached = getattr(self, "_zoom_focus", None)
        reused = (cached is not None and cached[0] == pose()
                  and abs(pos.x() - cached[1]) < 24.0
                  and abs(pos.y() - cached[2]) < 24.0
                  and self.scene.version == cached[3])
        reproj = False
        if reused:
            focus = cached[4]
        else:
            focus = None
            if (cached is not None and cached[4] is not None
                    and self.scene.version == cached[3]):
                # Orbit/pan changed the pose, but the cursor usually still
                # rests on the SAME world point (zoom → orbit a touch → zoom
                # again, the modeling rhythm). Re-validate the pin by
                # projecting it with the current camera: one matrix map
                # instead of a ~25 ms re-pick of the whole model per notch.
                p = self._world_to_pixel(cached[4])
                if (p is not None and abs(p[0] - pos.x()) < 24.0
                        and abs(p[1] - pos.y()) < 24.0):
                    focus = cached[4]
                    reproj = True
            if focus is None:
                focus = self._world_under_cursor(pos.x(), pos.y())
        if focus is not None:
            self.camera.zoom_to(steps, focus)
        else:
            self.camera.zoom(steps)
        self._zoom_focus = (pose(), pos.x(), pos.y(),
                            self.scene.version, focus)
        if _PERF:
            _plog("wheel", (_time_mod.monotonic() - now) * 1000.0,
                  extra=f"reused={'proj' if reproj else reused}", floor=10.0)
        self.update()

    def event(self, ev) -> bool:
        # With a VCB buffer in progress, claim keys that continue it (unit
        # suffixes m/cm/mm, separators, sign) before the window's QAction
        # shortcuts swallow them — otherwise typing "2m" would fire the Move
        # tool instead of finishing the length. Bare letters with no buffer
        # still reach the shortcuts.
        if ev.type() == QEvent.ShortcutOverride and self._value_buffer:
            t = ev.text().lower()
            if t and (t.isdigit() or t in (".", ",", ";", " ", "-", ":",
                                           "m", "c", "r")):
                ev.accept()
                return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:
        # 0. Shift state change → refresh snap immediately so the user sees
        #    the contextual lock take effect without moving the mouse.
        if ev.key() == Qt.Key_Shift and not ev.isAutoRepeat():
            self._capture_shift_lock()
            self._refresh_snap()
            # Do not return — Shift is a modifier; let the rest fall through.
        # 0b. Alt turns Paint into the eyedropper: show it on the pointer the
        #     moment the key goes down, not after the next mouse move.
        if ev.key() == Qt.Key_Alt and not ev.isAutoRepeat():
            self._apply_alt_cursor()

        # 1. Numeric value buffer (VCB-style length input).
        if self._handle_value_key(ev):
            return

        # 2. Active tool gets first shot at the key.
        if self.active_tool is not None:
            if self.active_tool.on_key(self, ev.key(), ev.modifiers()):
                return

        # 3. Esc, escalating (standard CAD): first clear the typed value buffer,
        #    then cancel the tool's in-progress action (an unfinished chain, a
        #    drag), and finally — nothing in progress — clear the selection.
        if ev.key() == Qt.Key_Escape:
            if self._value_buffer:
                self._set_value_buffer("")
                return
            if self.release_constraints():
                return
            if self.active_tool is not None and self._tool_busy(self.active_tool):
                self.active_tool.on_cancel(self)
                return
            if self.scene.selection:
                self.scene.clear_selection()
                self.update()
                return
            if self.scene.edit_group is not None:
                self.end_group_edit()           # step out of the group
                return
            if self.active_tool is not None:
                self.active_tool.on_cancel(self)
                return

        # 3. Projection toggle.
        if ev.key() == Qt.Key_P:
            self.toggle_projection()
            return

        # 3b. Alt: cycle linear inferences (SketchUp) — all → off → parallel/perp.
        if ev.key() == Qt.Key_Alt and not ev.isAutoRepeat():
            self._cycle_linear_inference_mode()
            return

        # 4. Axis lock (arrow keys). Pressing the same arrow toggles it off.
        if ev.key() == Qt.Key_Right:
            self.axis_lock = None if self.axis_lock == "x" else "x"
            self._refresh_snap()
            return
        if ev.key() == Qt.Key_Left:
            self.axis_lock = None if self.axis_lock == "y" else "y"
            self._refresh_snap()
            return
        if ev.key() == Qt.Key_Up:
            self.axis_lock = None if self.axis_lock == "z" else "z"
            self._refresh_snap()
            return

        # 5. Reference edge — Down cycles None → parallel → perpendicular → None.
        if ev.key() == Qt.Key_Down:
            self._cycle_reference_mode()
            self._refresh_snap()
            return

        super().keyPressEvent(ev)

    def _cycle_linear_inference_mode(self) -> None:
        """Alt: cycle linear inferences all → off → parallel/perp → all
        (SketchUp's Alt toggle). Point snaps (endpoint, midpoint, …) stay on;
        explicit locks (arrow keys, Down reference) keep working in every mode."""
        order = {"all": "off", "off": "parallel_perp", "parallel_perp": "all"}
        self.linear_inference_mode = order[self.linear_inference_mode]
        label = {
            "all": "Linear inferences: all on",
            "off": "Linear inferences: off",
            "parallel_perp": "Linear inferences: parallel / perpendicular only",
        }[self.linear_inference_mode]
        self.measurementChanged.emit(label)
        self._refresh_snap()

    def release_constraints(self) -> bool:
        """Drop the sticky drawing constraints — the arrow-key axis lock and
        the Down-arrow parallel/perpendicular reference. First stop of the
        Esc cascade: returns True if there was one to release (that Esc press
        is consumed; the next one cancels the tool action as before)."""
        if self.axis_lock is None and self.reference_mode is None:
            return False
        self.axis_lock = None
        self.reference_edge = None
        self.reference_mode = None
        self._refresh_snap()
        return True

    def _cycle_reference_mode(self) -> None:
        """Down arrow: cycle None → parallel → perpendicular → None.

        Captures whichever edge is currently under the cursor on entry to
        parallel mode. If no edge is under the cursor when starting, do
        nothing — there is nothing to be parallel/perpendicular to.
        """
        if self.reference_mode is None:
            if self._hover_edge is None:
                return  # nothing to capture
            self.reference_edge = self._hover_edge
            self.reference_mode = "parallel"
        elif self.reference_mode == "parallel":
            self.reference_mode = "perpendicular"
        else:
            self.reference_edge = None
            self.reference_mode = None

    def _refresh_snap(self) -> None:
        """Re-run snap with the last known cursor position. Used when modifier
        state changes (axis lock, reference mode, Shift) without mouse motion."""
        self.update()
        if (
            self._last_mouse_pos is None
            or self.active_tool is None
            or not self.active_tool.uses_snap
        ):
            return
        from PySide6.QtGui import QGuiApplication

        p = self._last_mouse_pos.toPoint()
        px_x, px_y = p.x(), p.y()
        world_raw = self._world_from_pixel(px_x, px_y)
        if world_raw is None:
            return
        modifiers = QGuiApplication.keyboardModifiers()
        chain_first = getattr(self.active_tool, "chain_first_point", None)
        start_pt = getattr(self.active_tool, "start_point", None)
        snap = compute_snap(
            candidate_world=world_raw,
            candidate_pixel=(px_x, px_y),
            scene=self._snap_scene(px_x, px_y),
            world_to_pixel=self._world_to_pixel,
            threshold_px=self.snap_threshold_px,
            project_onto_line=lambda s, d: self._project_to_lock_line(s, d, px_x, px_y),
            chain_first_point=chain_first,
            start_point=start_pt,
            axis_lock=self.axis_lock,
            shift_held=bool(modifiers & Qt.ShiftModifier),
            reference_edge=self.reference_edge,
            reference_mode=self.reference_mode,
            inference_angle_deg=self.inference_angle_deg,
            is_occluded=self._is_occluded,
            face_under_cursor=self.pick_face_any(px_x, px_y)[0] is not None,
            edge_threshold_px=self.edge_snap_threshold_px,
            magnetic_axis_deg=getattr(self.active_tool, "magnetic_axis_deg", None),
            acquired_edge=self._acquired_edge,
            acquired_point=self._acquired_point,
            acquired_face_normal=self._acquired_face_normal,
            shift_lock_dir=self._shift_lock[0] if self._shift_lock else None,
            shift_lock_color=self._shift_lock[1] if self._shift_lock else None,
            linear_mode=self.linear_inference_mode,
        )
        self.last_snap = snap
        ctx = ToolContext(
            viewport=self,
            world=snap.point,
            screen=self._last_mouse_pos,
            modifiers=modifiers,
            snap=snap,
        )
        self.active_tool.on_hover(ctx)
        self.measurementChanged.emit(self._measurement_text())

    def _apply_alt_cursor(self) -> None:
        """Refresh the pointer for an Alt state change (Paint <-> eyedropper);
        no-op while a camera nav mode owns the cursor."""
        if self.nav_mode is None and getattr(
                self.active_tool, "icon", None) == "paint":
            self._apply_tool_cursor()

    def keyReleaseEvent(self, ev) -> None:
        if ev.key() == Qt.Key_Alt and not ev.isAutoRepeat():
            self._apply_alt_cursor()
        if ev.key() == Qt.Key_Shift and not ev.isAutoRepeat():
            self._shift_lock = None
            self._refresh_snap()
        super().keyReleaseEvent(ev)

    # Inferences whose direction can be captured by a Shift lock.
    _SHIFT_LOCKABLE = frozenset({
        "axis", "axis_inference", "reference", "through_point", "perp_face",
        "extension",
    })

    def _capture_shift_lock(self) -> None:
        """On Shift press, freeze the active inference's direction so it holds
        even as the cursor wanders off it (SketchUp's inference lock)."""
        self._shift_lock = None
        snap = self.last_snap
        tool = self.active_tool
        start = getattr(tool, "start_point", None) if tool is not None else None
        if snap is None or start is None or snap.kind not in self._SHIFT_LOCKABLE:
            return
        d = snap.point - start
        if d.length() > 1e-6:
            self._shift_lock = (d.normalized(), snap.color)

    # ---- Numeric value buffer (VCB-style) ----------------------------------
    def _handle_value_key(self, ev) -> bool:
        """Buffer digit / dot / comma / semicolon / space / backspace.

        Enter applies the buffer via ``active_tool.on_value(...)``.

        Input forms:
        - ``"5"`` or ``"5,3"`` or ``"5.3"`` → single length (float).
        - ``"3;4;5"`` or ``"3 4 5"``       → 3D delta from the start point
                                              (passed as a ``(dx, dy, dz)`` tuple).
        - ``"-2"``                          → negative value (tools that take a
                                              direction flip it, SketchUp-style).
        - ``"30cm"`` / ``"1500mm"`` / ``"2m"`` → unit suffix per field; bare
                                              numbers are metres (project unit).
        Comma is always the decimal separator; ``;`` and space are field
        separators (SketchUp convention adapted to our locale).
        """
        if self.active_tool is None:
            return False

        text = ev.text()
        key = ev.key()

        if key in (Qt.Key_Return, Qt.Key_Enter):
            if not self._value_buffer:
                return False
            value = self._parse_value_buffer(self._value_buffer)
            if value is None:
                self._set_value_buffer("")
                return True
            if isinstance(value, tuple) and value and value[0] == "ratio":
                # A slope typed as rise:run (SketchUp "3:12") — only angle
                # tools understand it; it reaches them as plain degrees.
                if getattr(self.active_tool, "accepts_angle_ratio", False):
                    self.active_tool.on_value(self, value[1])
                self._set_value_buffer("")
                return True
            if isinstance(value, tuple) and value and value[0] == "radius":
                # SketchUp's "2r": the 2-point arc takes a RADIUS instead
                # of the bulge. Only tools that declare it understand.
                handler = getattr(self.active_tool, "on_radius_value", None)
                if handler is not None:
                    handler(self, value[1])
                self._set_value_buffer("")
                return True
            if getattr(self.active_tool, "accepts_absolute_length", False):
                # SketchUp's Scale reads "2" as a factor but "2m" as the new
                # absolute size; the parser collapses both to metres, so the
                # unit's presence is re-detected here and tagged, the same
                # pattern as the arc's "2r" radius suffix.
                import re as _re
                if _re.search(r"[\d\"']\s*(mm|cm|m|in|ft)\b|\d\s*[\"']",
                              self._value_buffer.lower()):
                    value = ("abs_len", value)
            self.active_tool.on_value(self, value)
            self._set_value_buffer("")
            return True

        if key == Qt.Key_Backspace:
            if not self._value_buffer:
                return False
            self._set_value_buffer(self._value_buffer[:-1])
            return True

        if text and (text.isdigit()
                     or text in (".", ",", ";", " ", "-", ":", "\"", "'", "/")
                     or text.lower() in ("m", "c", "r", "i", "n", "f", "t")):
            # A field separator (space / ;) with an empty buffer isn't VCB
            # input — let it fall through so Space can act as the Select
            # shortcut (SketchUp-style). It only separates fields mid-number.
            if text in (";", " ") and not self._value_buffer:
                return False
            # A unit letter with an empty buffer is a tool shortcut (M = Move,
            # C = Circle, R = Rectangle), not VCB input — only buffer it
            # after a digit. "r" is SketchUp's radius suffix for arcs (2r).
            if (text.lower() in ("m", "c", "r", "i", "n", "f", "t")
                    and not self._current_token_tail()):
                return False
            # Imperial marks and the fraction bar belong after a digit too:
            # 2", 1'6", 3/4" (bare they are nothing a tool wants).
            if text in ("\"", "'", "/") and not self._current_token_tail():
                return True
            # Minus only opens a token (a sign, not an operator).
            if text == "-" and self._current_token_tail():
                return True
            # Colon (slope rise:run, SketchUp "3:12"): mid-token only, once.
            if text == ":":
                tail = self._current_token_tail()
                if not tail or ":" in self._value_buffer:
                    return True
            # Forbid two decimal separators in the current numeric token.
            if text in (".", ","):
                tail = self._current_token_tail()
                if "." in tail or "," in tail:
                    return True
            self._set_value_buffer(self._value_buffer + text)
            return True

        return False

    @staticmethod
    def _parse_value_buffer(buffer: str):
        """Return a float, a 2-tuple ``(w, h)`` (rectangle dimensions), a
        3-tuple ``(dx, dy, dz)`` (delta), or ``None`` on parse error. Each tool's
        ``on_value`` accepts the arity it understands and ignores the rest.
        Fields may carry a unit suffix — ``m``/``cm``/``mm``, and imperial
        ``in`` or ``"``, ``ft`` or ``'``, feet-and-inches ``1'6"``, fractions
        ``3/4"`` (SketchUp's forms, so a 2×4 is typed ``2";4"`` while the
        span stays ``3.2``). Bare numbers are metres, and a leading minus is
        kept (direction tools flip on it)."""
        normalized = buffer.replace(",", ".").replace(";", " ")
        stripped = normalized.strip()
        if stripped.lower().endswith("r") and ":" not in stripped:
            import re as _re
            m = _re.fullmatch(r"(\d+\.?\d*|\.\d+)r", stripped.lower())
            if m is None:
                return None
            return ("radius", float(m.group(1)))
        if ":" in normalized:
            # Slope as rise:run (SketchUp "3:12", "1:6") → ("ratio", degrees).
            m = re.fullmatch(
                r"\s*(-?(?:\d+\.?\d*|\.\d+)):(\d+\.?\d*|\.\d+)\s*", normalized)
            if m is None:
                return None
            rise, run = float(m.group(1)), float(m.group(2))
            if run <= 0:
                return None
            return ("ratio", math.degrees(math.atan2(rise, run)))
        nums = []
        for p in _merge_mixed_numbers(normalized.split()):
            v = _parse_length_field(p)
            if v is None:
                return None
            nums.append(v)
        if len(nums) == 1:
            return nums[0]
        if len(nums) in (2, 3):
            return tuple(nums)
        return None

    def _current_token_tail(self) -> str:
        """The portion of the buffer after the last ``;`` or space."""
        normalized = self._value_buffer.replace(";", " ")
        idx = normalized.rfind(" ")
        if idx < 0:
            return self._value_buffer
        return self._value_buffer[idx + 1 :]

    def _set_value_buffer(self, text: str) -> None:
        if text == self._value_buffer:
            return
        self._value_buffer = text
        self.valueBufferChanged.emit(text)
        self.update()

    def toggle_projection(self) -> None:
        self.camera.toggle_projection()
        self.update()

    # ---- Helpers ------------------------------------------------------------
    def _build_ctx(self, ev) -> Optional[ToolContext]:
        p = ev.position().toPoint()
        px_x, px_y = p.x(), p.y()
        world_raw = self._world_from_pixel(px_x, px_y)
        if world_raw is None:
            return None
        # Tools that don't snap (Select, Push/Pull) skip the snap engine and its
        # occlusion raycasts entirely, and show no snap marker.
        if self.active_tool is not None and not self.active_tool.uses_snap:
            snap = SnapResult(world_raw, "none")
            return ToolContext(
                viewport=self,
                world=world_raw,
                screen=ev.position(),
                modifiers=ev.modifiers(),
                snap=snap,
            )
        chain_first = None
        start_pt = None
        if self.active_tool is not None:
            chain_first = getattr(self.active_tool, "chain_first_point", None)
            start_pt = getattr(self.active_tool, "start_point", None)
        shift_held = bool(ev.modifiers() & Qt.ShiftModifier)
        snap = compute_snap(
            candidate_world=world_raw,
            candidate_pixel=(px_x, px_y),
            scene=self._snap_scene(px_x, px_y),
            world_to_pixel=self._world_to_pixel,
            threshold_px=self.snap_threshold_px,
            project_onto_line=lambda s, d: self._project_to_lock_line(s, d, px_x, px_y),
            chain_first_point=chain_first,
            start_point=start_pt,
            axis_lock=self.axis_lock,
            shift_held=shift_held,
            reference_edge=self.reference_edge,
            reference_mode=self.reference_mode,
            inference_angle_deg=self.inference_angle_deg,
            is_occluded=self._is_occluded,
            face_under_cursor=self.pick_face_any(px_x, px_y)[0] is not None,
            edge_threshold_px=self.edge_snap_threshold_px,
            magnetic_axis_deg=getattr(self.active_tool, "magnetic_axis_deg", None),
            acquired_edge=self._acquired_edge,
            acquired_point=self._acquired_point,
            acquired_face_normal=self._acquired_face_normal,
            shift_lock_dir=self._shift_lock[0] if self._shift_lock else None,
            shift_lock_color=self._shift_lock[1] if self._shift_lock else None,
            linear_mode=self.linear_inference_mode,
        )
        return ToolContext(
            viewport=self,
            world=snap.point,
            screen=ev.position(),
            modifiers=ev.modifiers(),
            snap=snap,
        )
