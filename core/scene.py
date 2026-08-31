# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Scene container, backed by a shared-vertex :class:`~core.mesh.Mesh`.

``edges`` and ``faces`` are read-only views onto the mesh (lists of
``mesh.Edge`` / ``mesh.Face``), so render, bounds and ``.igz`` save consume them
unchanged. Every mutation goes through mesh methods (via the ``Command`` layer),
which keep shared-vertex connectivity and incidence in sync — no more
position-matching to rediscover topology.

``version`` bumps on every mutation so the viewport can cheaply decide whether
to rebuild its dynamic VBOs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from PySide6.QtGui import QVector3D

from core.mesh import Edge, Face, Mesh


def _make_style():
    from core.style import Style
    return Style()


@dataclass
class Scene:
    mesh: Mesh = field(default_factory=Mesh)
    selection: set = field(default_factory=set)
    version: int = 0
    # Encapsulated chunks (own meshes), isolated from the main mesh's welding.
    groups: list = field(default_factory=list)
    # Annotation entities (static dimensions) — not geometry, drawn as overlays.
    dimensions: list = field(default_factory=list)
    # Leader-text annotations (SketchUp's Text tool) — same overlay treatment.
    text_labels: list = field(default_factory=list)
    # Georef traced paths (roads / boundaries / alignments) — first-class georef
    # entities, kept out of the topology mesh entirely (Track G).
    geo_paths: list = field(default_factory=list)
    # Imported survey points (GPS / total station, UTM CSV) — reference markers
    # the trace snaps to; never part of the mesh (Track G, municipal flow).
    geo_points: list = field(default_factory=list)
    # Construction guides (Tape Measure): infinite dashed lines / points used to
    # align real drawing. Scaffolding, never part of the mesh.
    guides: list = field(default_factory=list)
    # Imported reference images (core.image_plane.ImagePlane) — a scanned plan
    # or photo you trace over. Display-only like the terrain and for the same
    # reason (invariant #4): reference to draw on top of, never topology.
    image_planes: list = field(default_factory=list)
    # Layers / tags (SketchUp): labels with visibility + lock. The default
    # layer always exists; entities reference layers by name.
    layers: list = field(default_factory=lambda: [
        __import__("core.layers", fromlist=["Layer"]).Layer(
            __import__("core.layers", fromlist=["DEFAULT_LAYER"]).DEFAULT_LAYER)
    ])
    # Named materials (core.materials.Material), name → Material. The
    # registry gives identity to paint recipes; faces keep their baked
    # attrs (color/texture) as the render truth and optionally carry
    # attrs["mat"] = name. See core/materials.py.
    materials: dict = field(default_factory=dict)
    # Saved views (SketchUp's "Scenes"): named camera + layer-visibility
    # snapshots (core.saved_views.SavedView). Presentation state, no geometry.
    saved_views: list = field(default_factory=list)
    # Sheet compositions (core.composition.Composicion) — the print layouts.
    compositions: list = field(default_factory=list)
    # Display style for dimension annotations (edited from the Tray).
    dimension_style: dict = field(default_factory=lambda: {
        "decimals": 2, "units": "m", "font_size": 9, "color": [45, 55, 75]})
    # Back-face tint override (RGB 0..1), e.g. adopted from an imported
    # .skp's style so unpainted faces read like they did for the author.
    # ``None`` = the viewport's default SketchUp blue-grey.
    back_face_color: tuple | None = None
    # Active display style (SketchUp Styles): face mode, edges, background.
    # The viewport reads it every frame; scenes snapshot it (core/style.py).
    display_style: object = field(default_factory=lambda: _make_style())
    # Section planes (SketchUp sections, core/section.py). At most ONE is
    # ``active`` (the cut) in the model context; the two flags mirror
    # SketchUp's View ▸ Section Planes / Section Cuts toggles.
    section_planes: list = field(default_factory=list)
    show_section_planes: bool = True
    show_section_cuts: bool = True
    # Georeferencing anchor (Track G). ``None`` until the user sets a datum;
    # once set, geodetic ↔ local-metre conversion goes through it. Terrain and
    # tiles are separate display-only objects added in later phases.
    georef: object | None = None
    # Base-map tile layer (Track G, G1) — display-only, never welded into the
    # mesh. Runtime state (not serialised as geometry); requires ``georef``.
    tile_layer: object | None = None
    # 3D draped terrain (Track G, G2 full) — display-only relief mesh, runtime.
    terrain: object | None = None
    # Photogrammetric survey (Track G, G6) — the drone flight's own textured
    # mesh from WebODM/ODM. Display-only like the terrain, and for the same
    # reason: hundreds of thousands of reconstruction triangles are reference
    # geometry to trace over, never topology-engine geometry (invariant #4).
    photo_mesh: object | None = None
    # BIM "active class" (tag-as-you-draw): while set, faces created by the
    # drawing tools are stamped with this tag ({"id", "class", "name"}) at
    # commit time. Runtime UI mode — never serialised.
    active_ifc: object | None = None
    # Group-edit context (Groups v2): while set, ``mesh`` POINTS AT the edited
    # group's mesh so every tool/command works inside the group transparently;
    # ``_loose_mesh`` keeps the real loose mesh for render and restore.
    edit_group: object | None = None
    _loose_mesh: object | None = None

    # ---- Geometry views (read-only over the *loose* mesh) -------------------
    # Tools, edits and topology operate on this (the loose geometry); groups are
    # walled off so drawing never welds to them.
    @property
    def edges(self) -> list[Edge]:
        return self.mesh.edges

    @property
    def faces(self) -> list[Face]:
        return self.mesh.faces

    # ---- Layers --------------------------------------------------------------
    def layer(self, name: str):
        for ly in self.layers:
            if ly.name == name:
                return ly
        return None

    def _layer_state(self, entity) -> tuple[bool, bool]:
        """(visible, locked) of the layer ``entity`` carries; unknown layer
        names read as the default (visible, unlocked)."""
        from core.layers import layer_of
        ly = self.layer(layer_of(entity))
        if ly is None:
            return True, False
        return ly.visible, ly.locked

    def entity_visible(self, entity) -> bool:
        return self._layer_state(entity)[0]

    def entity_selectable(self, entity) -> bool:
        visible, locked = self._layer_state(entity)
        return visible and not locked

    # ---- Sections (SketchUp section planes) ----------------------------------
    def active_section(self):
        """The section plane currently cutting the model, or ``None``."""
        for sp in self.section_planes:
            if sp.active:
                return sp
        return None

    def set_active_section(self, plane) -> None:
        """Make ``plane`` the ONE active cut (None deactivates all) —
        SketchUp: one active cut per context."""
        for sp in self.section_planes:
            sp.active = sp is plane

    # ---- Group-edit context (Groups v2) --------------------------------------
    def begin_group_edit(self, group) -> None:
        """Enter a group: tools and commands now edit ITS mesh (SketchUp's
        double-click-into-group). Nested groups are not supported yet.
        Entering a component INSTANCE first makes it unique (materialize) —
        its prototype mesh is shared with siblings and holds local coords."""
        if self.edit_group is not None:
            self.end_group_edit()
        if (getattr(group, "xform", None) is not None
                or getattr(group, "children", None)):
            # Nested placements bake in too: inside the group you edit real
            # geometry, so its internal sharing has to become real faces
            # first (SketchUp does the same when you edit into a component).
            group.materialize()
        self._loose_mesh = self.mesh
        self.mesh = group.mesh
        self.edit_group = group
        self.selection.clear()
        self.version += 1

    def end_group_edit(self) -> None:
        """Leave the group-edit context, restoring the loose mesh."""
        if self.edit_group is None:
            return
        self.mesh = self._loose_mesh
        self._loose_mesh = None
        self.edit_group = None
        self.selection.clear()
        self.version += 1

    @property
    def loose_mesh(self):
        """The real loose mesh regardless of the edit context."""
        return self._loose_mesh if self.edit_group is not None else self.mesh

    # ---- Render views (loose + every group) ---------------------------------
    def placements(self):
        """Every visible placement in the scene: each group and, below it,
        the nested ones a component keeps inside itself, as
        ``(group, world_matrix_or_None)``.

        Face-me billboards are left out (they are drawn per frame, not from
        their mesh). Consumers that used to walk ``self.groups`` and read
        ``g.mesh`` want this — otherwise the geometry a component places
        inside itself is simply invisible to them."""
        from core.group import iter_placements
        for g in self.groups:
            if not self.entity_visible(g) or getattr(g, "billboard", False):
                continue
            for pg, m in iter_placements(g):
                if pg is not g and (getattr(pg, "billboard", False)
                                    or not self.entity_visible(pg)):
                    continue
                yield pg, m

    def render_edges(self):
        for e in self.loose_mesh.edges:
            if self.entity_visible(e):
                yield e
        for g, _m in self.placements():
            yield from g.mesh.edges

    def render_faces(self):
        for f in self.loose_mesh.faces:
            if self.entity_visible(f):
                yield f
        for g, _m in self.placements():
            yield from g.mesh.faces

    # ---- Mutations ----------------------------------------------------------
    def add_edge(self, a: QVector3D, b: QVector3D) -> Edge:
        edge = self.mesh.add_edge(a, b)
        self.version += 1
        return edge

    def select(self, edges: Iterable, additive: bool = False) -> None:
        if not additive:
            self.selection.clear()
        self.selection.update(edges)
        self.version += 1

    def clear_selection(self) -> None:
        if self.selection:
            self.selection.clear()
            self.version += 1

    def delete_selection(self) -> None:
        if not self.selection:
            return
        for ent in list(self.selection):
            if isinstance(ent, Edge):
                self.mesh.remove_edge(ent)
            elif isinstance(ent, Face):
                self.mesh.remove_face(ent)
        self.selection.clear()
        self.version += 1

    def clear(self) -> None:
        self.end_group_edit()
        if (self.mesh.edges or self.mesh.faces or self.selection
                or self.groups or self.dimensions or self.georef
                or self.tile_layer or self.geo_paths or self.terrain
                or self.guides or self.geo_points or self.text_labels
                or self.saved_views or self.compositions
                or self.image_planes):
            self.mesh.clear()
            self.groups.clear()
            self.dimensions.clear()
            self.text_labels.clear()
            self.geo_paths.clear()
            self.geo_points.clear()
            self.guides.clear()
            self.image_planes.clear()
            self.saved_views.clear()
            self.compositions.clear()
            self.selection.clear()
            from core.layers import DEFAULT_LAYER, Layer
            self.layers = [Layer(DEFAULT_LAYER)]
            self.georef = None
            self.tile_layer = None
            self.terrain = None
            self.back_face_color = None
            self.active_ifc = None
            self.display_style = _make_style()
            self.section_planes.clear()
            self.show_section_planes = True
            self.show_section_cuts = True
            self.version += 1

    # ---- Queries ------------------------------------------------------------
    def iter_world_faces(self):
        """Every visible face with the matrix that maps it to WORLD space:
        ``(face, matrix_or_None)``. Instance groups share a prototype mesh in
        local coordinates — exporters and geometry consumers must apply the
        matrix; classic faces come with ``None``."""
        for f in self.loose_mesh.faces:
            if self.entity_visible(f):
                yield f, None
        for g, m in self.placements():
            for f in g.mesh.faces:
                yield f, m

    def bounds(self) -> tuple[QVector3D, QVector3D] | tuple[None, None]:
        """Axis-aligned bounding box of all geometry. ``(None, None)`` if empty.

        CACHED per ``version`` — hovering over empty space derives the work
        plane (and the status-bar coordinate) from the model centre, so this
        runs on EVERY mouse move across sky or base map. The old per-corner
        Python walk cost ~1.7 s per call against piscina's 230k-face merged
        group, twice per hover: the event loop starved and GNOME declared
        the app dead (the paste "no responde" hang). Every mutation —
        commands, layer toggles — bumps ``version``, the same invariant the
        viewport's chunk caches key on.

        Group bounds are vectorized over each mesh's welded vertex list
        (as the instance branch always was), so an orphaned vertex left by
        a deletion may pad them slightly until the weld reuses it; loose
        entities keep the exact per-entity visibility walk."""
        cached = getattr(self, "_bounds_cache", None)
        if cached is not None and cached[0] == self.version:
            lo, hi = cached[1]
            if lo is None:
                return None, None
            return QVector3D(*lo), QVector3D(*hi)
        import numpy as np
        inf = float("inf")
        minx = miny = minz = inf
        maxx = maxy = maxz = -inf
        seen = False

        def absorb(v: QVector3D) -> None:
            nonlocal minx, miny, minz, maxx, maxy, maxz, seen
            seen = True
            x, y, z = v.x(), v.y(), v.z()
            if x < minx: minx = x
            if y < miny: miny = y
            if z < minz: minz = z
            if x > maxx: maxx = x
            if y > maxy: maxy = y
            if z > maxz: maxz = z

        for edge in self.loose_mesh.edges:
            if self.entity_visible(edge):
                absorb(edge.a)
                absorb(edge.b)
        for face in self.loose_mesh.faces:
            if self.entity_visible(face):
                for v in face.vertices:
                    absorb(v)
        for g, m in self.placements():
            verts = g.mesh.vertices
            if not verts:
                continue
            arr = np.array([[v.position.x(), v.position.y(), v.position.z()]
                            for v in verts])
            if m is not None:
                d = m.data()          # column-major
                rot = np.array([[d[0], d[4], d[8]],
                                [d[1], d[5], d[9]],
                                [d[2], d[6], d[10]]])
                arr = arr @ rot.T + np.array([d[12], d[13], d[14]])
            glo, ghi = arr.min(axis=0), arr.max(axis=0)
            seen = True
            minx = min(minx, glo[0]); miny = min(miny, glo[1])
            minz = min(minz, glo[2])
            maxx = max(maxx, ghi[0]); maxy = max(maxy, ghi[1])
            maxz = max(maxz, ghi[2])
        if not seen:
            self._bounds_cache = (self.version, (None, None))
            return None, None
        self._bounds_cache = (self.version, ((minx, miny, minz),
                                             (maxx, maxy, maxz)))
        return QVector3D(minx, miny, minz), QVector3D(maxx, maxy, maxz)
