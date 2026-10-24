# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""3D viewport: orbital camera, grid, XYZ axes, tools, snapping and overlays.

Uses PySide6's bundled QOpenGL* helper classes (QOpenGLShaderProgram,
QOpenGLBuffer, QOpenGLVertexArrayObject) — no external GL bindings yet.
moderngl lands when we start dealing with real meshes.

Wayland requires every frame to be drawn explicitly: ``paintGL`` always
calls ``glClear`` first to avoid showing stale GPU memory.

Navigation:
- Middle-button drag: orbit
- Shift + Middle-button drag: pan
- Wheel: zoom
- P: toggle perspective / parallel projection

Axis lock (active while drawing):
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

from typing import Optional
from PySide6.QtCore import Qt, QPointF, Signal
from PySide6.QtGui import QOpenGLFunctions, QSurfaceFormat, QVector3D
from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLShaderProgram
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from core.camera import OrbitCamera
from core.history import History
from core.scene import Scene
from tools.base import Tool
from core.inference import InferenceEngine
from views.viewport._support import (_load_edit_rest_mode, _load_hide_similar, _load_invert_wheel,
                                     _load_invert_orbit_y, _load_msaa, _AltWatch)

# Re-exported: other modules and the tests import these from views.viewport.
from core.materials import material_sig as _material_sig
from views.viewport._support import (_active_cut, _SnapEdge, _split_chunk_spans, EDIT_REST_MODES,
                                     EDIT_REST_FADE, edit_fade_color, SELECTION_DOT_COLOR,
                                     SELECTION_DOT_ALT_COLOR, selection_dot_color, _axes_vertices,
                                     _box_edge_vertices, _guide_vertices, _parse_number,
                                     _parse_length_field, _face_geometry)

from views.viewport.interaction import InteractionMixin
from views.viewport.value_input import ValueInputMixin
from views.viewport.snapping import SnappingMixin
from views.viewport.picking import PickingMixin
from views.viewport.occlusion import OcclusionMixin
from views.viewport.projection import ProjectionMixin
from views.viewport.group_edit import GroupEditMixin
from views.viewport.clipboard import ClipboardMixin
from views.viewport.overlay import OverlayMixin
from views.viewport.sections import SectionPlaneMixin
from views.viewport.render import RenderMixin
from views.viewport.instancing import InstancingMixin
from views.viewport.billboards import BillboardMixin
from views.viewport.chunks import ChunkCacheMixin
from views.viewport.image_planes import ImagePlaneMixin
from views.viewport.geo import GeoMixin
from views.viewport.shadows import ShadowMixin
from views.viewport.gl_setup import GLSetupMixin


class Viewport(InteractionMixin, ValueInputMixin, SnappingMixin, PickingMixin, OcclusionMixin,
               ProjectionMixin, GroupEditMixin, ClipboardMixin, OverlayMixin, SectionPlaneMixin,
               RenderMixin, InstancingMixin, BillboardMixin, ChunkCacheMixin, ImagePlaneMixin,
               GeoMixin, ShadowMixin, GLSetupMixin, QOpenGLWidget):
    """OpenGL viewport with orbital camera, grid, XYZ axes, tools and snapping."""

    valueBufferChanged = Signal(str)
    sceneVersionChanged = Signal(int)
    # Live measurement for the VCB box (e.g. "5.00 m", "3.00 × 2.00 m").
    measurementChanged = Signal(str)
    glReady = Signal(dict)          # vendor/renderer/version once the context is up
    # A base-map tile finished downloading (Track G) — lets the 3D terrain
    # rebuild its mosaic as imagery arrives.
    tilesChanged = Signal()
    # UTM coordinate under the cursor, for the status bar readout (Track G).
    coordinateChanged = Signal(str)
    # The camera's projection changed ("parallel" / "perspective" /
    # "two_point"), whoever changed it — the View toolbar's quick buttons
    # follow it.
    projectionChanged = Signal(str)

    # Soft warm white painted on faces with no material colour — like the matte
    # cardstock of an architecture model (a near-white default).
    DEFAULT_FACE_COLOR = (0.96, 0.95, 0.925)
    # Fixed world light (from above, slightly front-right) for the subtle diffuse
    # face shading. World-fixed so shading is stable while orbiting.
    _LIGHT = QVector3D(0.35, 0.25, 1.0).normalized()

    # Tooltip text shown next to the snap marker. English source
    # strings; translated at draw time via ``tr`` (see i18n/es.json).
    #: How close (px) the cursor must come to an acquired circle centre
    #: for its green dot to show — beyond that the reference stays silent.
    #: The real radius is a share of the circle's size on screen, capped
    #: here (see ``_center_hint_px``).
    CENTER_HINT_PX = 40.0
    #: A circle smaller than this on screen offers no centre at all.
    CENTER_MIN_RADIUS_PX = 12.0

    #: How long the cursor must rest on a point to encourage it (ms).
    ENCOURAGE_MS = 250
    #: Snap kinds whose point can be encouraged (a definite point, not a
    #: place along an edge or on a face).
    _ENCOURAGING_KINDS = frozenset((
        "endpoint", "midpoint", "arc_midpoint", "center", "component_origin",
        "origin", "intersection", "close"))

    _SNAP_LABELS = {
        "endpoint": "Endpoint",
        "midpoint": "Midpoint",
        "arc_midpoint": "Arc midpoint",
        "component_origin": "Component origin",
        "on_line": "On line",
        "on_axis": "On axis",
        "tangent": "Tangent at vertex",
        "on_edge": "On edge",
        "on_face": "On face",
        "origin": "Origin",
        "extension": "Extension",
        "intersection": "Intersection",
        "from_point": "From point",
        # The axis PLANE through an encouraged point cut by the face under
        # the cursor (rule 8e): "Level with point" when it is the horizontal
        # one, see ``_draw_snap_indicator``.
        "aligned": "In line with point",
        "through_point": "Through point",
        "perp_face": "Perpendicular to face",
        "center": "Center",
        "guide_point": "Guide point",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Hidden-line removal needs a real depth buffer. setDefaultFormat() in
        # main.py is best-effort; many platforms ignore it for QOpenGLWidget
        # and hand us a 0-bit depth context. Forcing the format here is the
        # only reliable way.
        #
        # Start from the default format rather than from nothing, though:
        # core.gl_fallback may have just dropped the stencil buffer to get a
        # context AT ALL on this driver, and building a fresh format here
        # would ask for it right back and undo the recovery. Depth and
        # samples we still state outright — those two are ours to decide.
        fmt = QSurfaceFormat(QSurfaceFormat.defaultFormat())
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setSamples(0)
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
        from core import units as _units
        _units.bind_scene(self.scene)   # readouts format in the model's units
        self.history = History(self.scene)
        # Snapping inference state (hover / acquired edges and points,
        # the encouraged points, the axis and reference locks, the last
        # snap) gathered in its own collaborator. The delegating
        # properties further down keep the old attribute names reading
        # and writing through to it.
        self.inference = InferenceEngine(self)
        self.active_tool: Optional[Tool] = None
        # Extensions' overlays and snap providers (views.extension_api).
        self._ext_overlays: list = []
        self._ext_snap_providers: list = []
        # Copy/paste clipboard: copied geometry (faces + edges as positions,
        # groups as snapshot copies) plus a reference corner so Paste can
        # place it under the cursor.
        self.clipboard: Optional[dict] = None

        # Linear-inference toggle (Alt): "all" | "off" | "parallel_perp".
        self.linear_inference_mode = "all"
        #: A bare Alt is down and nothing else has happened since — the tap
        #: that cycles the mode on release (issue #26).
        self._alt_tap = False
        self._alt_down = False
        _AltWatch.watch(self)
        self._last_mouse_pos: Optional[QPointF] = None

        # Pixel radius for point snaps (endpoint, origin, close). 12 px felt
        # mushy when the cursor was running along an existing edge: as long
        # as the cursor was within 12 px of either end of a short edge,
        # endpoint snap kept firing. It must be tighter — the green dot
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
        self._guides_vbo = None

        self._edges_vao = None
        self._edges_vbo = None
        # Default-back tint: the triangles of every face whose back is
        # unpainted, drawn once more with front culling in the style's back
        # colour (see ``core.materials.back_is_default``).
        self._dback_vao = None
        self._dback_vbo = None
        self._dback_count = 0
        self._dback_spans: list = []
        self._edges_count = 0
        self._selected_vao = None
        self._selected_vbo = None
        self._selected_count = 0
        self._sel_faces_vao = None
        self._sel_faces_vbo = None
        self._sel_faces_count = 0
        # [(front_rgb, back_rgb, first_vertex, count)] — one run per dot
        # colour pair inside the selected-faces buffer.
        self._sel_faces_spans = []
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
        # (Model Info ▸ Components). "fade" keeps the context
        # visible but out of the way, "hide" drops it from the frame
        # entirely — on a heavy import that is also the fastest, since a
        # hidden group never reaches the VBOs. See `edit_rest_mode`.
        self._edit_rest_mode = _load_edit_rest_mode()
        self.scene.hide_similar_components = _load_hide_similar()
        self._invert_wheel = _load_invert_wheel()
        self._invert_orbit_y = _load_invert_orbit_y()
        self._msaa = _load_msaa()

        # Hover highlight (Select tool). Not version-tracked — it changes with
        # the cursor, not with scene mutations — so it's uploaded per paint.
        self._hover_entity = None  # None | Edge | Face under the cursor
        #: The placement a hovered face is reached THROUGH (a part inside a
        #: component): its matrix puts the face's own coordinates in the
        #: world. ``None`` for a loose face, which is already there.
        self._hover_placement = None
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
        #: Pen widths in PIXELS for the next export render (edges and
        #: profiles); 1 = the plain GL hairline. See ``_line_jitter``.
        self._export_edge_px = 1
        self._export_profile_px = 1
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
        self._middle_drag_active = False
        #: where the current orbit gesture turns (#164); None = the target
        self._orbit_pivot = None
        # A mouse-look drag for a tool with ``on_look`` (First Person):
        # (button, last local point) while a button is held, else None.
        self._look_drag = None
        # Navigation mode for trackpad users with no middle
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
        # A paint must only draw.  In particular, creating Qt's native HTTPS
        # backend while an OpenGL context is current crashed in ntdll on an
        # AMD Windows driver (#327).  Missing tiles schedule one event-loop
        # callback; that callback starts the network work after paintGL has
        # returned and the context is no longer inside a driver callback.
        self._tile_requests_scheduled = False
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

    # ---- Dynamic uploads ----------------------------------------------------
    def notify_scene_changed(self) -> None:
        """Force a redraw and emit the version-changed signal.

        Use this when an outside system (load, undo, redo) has mutated the
        scene and wants subscribers (title-bar dirty flag, etc.) to react
        without waiting for the next paint.
        """
        self.sceneVersionChanged.emit(self.scene.version)
        self.update()

    def set_hover(self, entity, placement=None) -> None:
        """Set the entity (edge/face) highlighted under the cursor and repaint
        if it changed. ``None`` clears the highlight. ``placement`` is the
        component placement a face inside a component was picked through
        (see :meth:`pick_face_placement`): it is what puts the marking on the
        part."""
        if entity is self._hover_entity and placement is self._hover_placement:
            return
        self._hover_entity = entity
        self._hover_placement = placement
        self.update()

    def flash_status(self, text: str, msec: int = 2500) -> None:
        """Briefly show ``text`` in the main window's status bar (e.g. Push/Pull
        saying how far the solid lets it go). No-op if there is no status bar
        yet."""
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

    def set_document(self, scene, history) -> tuple:
        """Show another document: ``scene`` with its own undo ``history``
        (for an extension's workspace, ``ExtensionApp.enter_workspace``).
        Returns the ``(scene, history)`` pair it replaces, untouched, to be
        handed back later — the parked document keeps its undo steps and its
        selection.

        A document boundary like New / Open: the id()-keyed chunk caches
        are reset (:meth:`reset_document_caches`), and since the other
        render caches remember the scene VERSION they were built for, not
        which scene it was, the incoming scene is moved past every version
        this viewport has shown before it is drawn."""
        self.end_group_edit()
        old = (self.scene, self.history)
        self.inference.reset()
        self.reset_document_caches()
        seen = max(getattr(self, "_versions_seen", 0), self.scene.version, scene.version)
        scene.version = self._versions_seen = seen + 1
        # A view preference, not document content: it follows the viewport.
        scene.hide_similar_components = bool(
            getattr(self.scene, "hide_similar_components", False))
        self.scene = scene
        self.history = history
        from core import units as _units
        _units.bind_scene(scene)
        self._edges_version = -1
        self._hover_entity = None
        self._hover_edge = None
        self.last_snap = None
        self.reference_edge = None
        self.reference_mode = None
        self.notify_scene_changed()
        return old

    def refresh_status_hint(self) -> None:
        """Redraw the status bar's base line now. The hint otherwise rides
        the 12 Hz text timer, which only ticks on mouse movement — a tool
        that changes mode on a KEY needs to say so without waiting for the
        hand to move (the Tape's Ctrl, issue #29)."""
        win = self.window()
        fn = getattr(win, "_update_status_hint", None)
        if fn is not None:
            fn()

    def toggle_projection(self) -> None:
        self.camera.toggle_projection()
        self._sync_projection()
        self.update()

    def toggle_two_point(self) -> None:
        self.camera.toggle_two_point()
        self._sync_projection()
        self.update()

    def set_projection(self, mode: str) -> None:
        """Parallel, perspective or two-point (the View toolbar's buttons)."""
        self.camera.set_projection(mode)
        self._sync_projection()
        self.update()
