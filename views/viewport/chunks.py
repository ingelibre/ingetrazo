# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Mesh-to-GPU chunk caches: edge and face sync, fingerprints, on-disk cache, culling spans."""
from __future__ import annotations

import time as _time_mod
from array import array
from PySide6.QtGui import QVector3D
from core.group import Group
from core.mesh import Edge, Face
from core.texture import face_uv_axes
from views.viewport._support import (_PERF, _plog, _chunk_uid, _SPAN_VECTOR_MIN, _proto_wrapper,
                                     _cache_ver, _box_edges, _face_geometry)


class ChunkCacheMixin:
    """Mesh-to-GPU chunk caches: edge and face sync, fingerprints, on-disk cache, culling spans."""

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

                # A hidden face/edge the hidden view shows is selectable,
                # and a selection it took must not be dropped here: a
                # single click on a ghost face looked like nothing (only
                # a double click, which selected its visible edges too,
                # seemed to work — Marco, 2026-09-21, issue #53).
                def shown(ent):
                    return (self.scene.entity_visible(ent)
                            or self.scene.entity_selectable(ent))

                def alive(ent):
                    if isinstance(ent, Edge):
                        if ent in self.scene.loose_mesh.edges:
                            return shown(ent)
                        return any(ent in gm.edges for gm in gmeshes)
                    if ent in self.scene.loose_mesh.faces:
                        return shown(ent)
                    return any(ent in gm.faces for gm in gmeshes)

            if isinstance(hover, (Edge, Face)) and not alive(hover):
                self._hover_entity = None
            for s in [s for s in self.scene.selection
                      if isinstance(s, (Edge, Face)) and not alive(s)]:
                self.scene.selection.discard(s)

        # Inside a group, the surroundings can fade out or leave the frame
        # altogether (Model Info ▸ Components). Hidden means gone
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
        loose_n = len(all_loose) // 3
        edge_spans = [(None, 0, loose_n)]
        pv = getattr(self, "_preview_groups", None) or ()
        # The group half (every placement's hard edges, in draw order) is
        # keyed on the placements epoch: a loose edit — every frame of a
        # Move drag — re-uses it whole instead of walking 1 300 chunks.
        epoch_of = getattr(self, "_placements_epoch", None)     # stub VPs in tests
        gkey = (epoch_of() if epoch_of is not None else _cache_ver(self),
                hide_rest, tuple(sorted(pv)))
        # The group being edited goes LAST, so the surroundings occupy a
        # contiguous head the fade pass can draw in one go (and, since
        # nothing outside the group can change while you are in it, a head
        # that stays put in the buffer). The order is also what the passes
        # below walk.
        placements = self._placements()
        draw_groups = [g for g in placements
                       if not self._draws_in_edit_context(g)]
        if not hide_rest:
            draw_groups = [g for g in placements
                           if self._draws_in_edit_context(g)] + draw_groups
        # While a group is open, only the SURROUNDINGS are cached on the
        # epoch. The epoch leaves the open mesh's serial out on purpose (it
        # is the loose mesh, and counting it re-keyed every cache on every
        # drag frame), so a cached subject never saw its own edits: what
        # you drew inside a group or component was not drawn until you
        # left it (Rafael, revision 4: «no se ven las líneas»). The subject
        # is re-read each sync instead — its chunk is cached per group and
        # revalidated by the mesh serial, so that is a lookup, not a build.
        editing = self.scene.edit_group is not None
        head = ([g for g in draw_groups if self._draws_in_edit_context(g)]
                if editing else draw_groups)
        subject = ([g for g in draw_groups
                    if not self._draws_in_edit_context(g)]
                   if editing else [])

        def _collect(groups, rel):
            parts: list = []
            spans: list = []                  # (bbox, start RELATIVE, n)
            for g in groups:
                if (self.scene.entity_visible(g) and id(g) not in pv
                        and not getattr(g, "billboard", False)
                        and not self._instanced_eligible(g)):
                    ch = self._group_chunk(g)
                    parts.append(ch["edges"])
                    n = len(ch["edges"]) // 12
                    spans.append((ch.get("bbox"), rel, n))
                    rel += n
            return parts, spans, rel

        gcache = getattr(self, "_edge_groups_cache", None)
        if gcache is None or gcache[0] != gkey:
            head_parts, head_spans, head_n = _collect(head, 0)
            gcache = self._edge_groups_cache = (gkey, head_parts, head_spans,
                                                head_n)
        _gk, head_parts, head_spans, head_n = gcache
        # Where the surroundings end and the subject begins. This used to
        # key on `g is scene.edit_group`, which never matched when the group
        # being edited was a nested placement (the list holds its proxy) —
        # and with no split, NOTHING faded.
        split_rel = head_n if editing else None
        subj_parts, subj_spans, _n = _collect(subject, head_n)
        group_parts = head_parts + subj_parts
        group_spans = head_spans + subj_spans
        edge_parts += group_parts
        edge_spans += [(bb, loose_n + start, n) for bb, start, n in group_spans]
        if self._edit_split_e is None and split_rel is not None:
            self._edit_split_e = loose_n + split_rel
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
                # modellers usually show one — twelve segments instead of the whole
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

        sel_face_runs: dict = {}     # (front_dot, back_dot) -> array
        for ent in self.scene.selection:
            if isinstance(ent, Face):
                buf = sel_face_runs.setdefault(
                    self._selection_dot_colors(ent), array("f"))
                for t0, t1, t2 in ent.triangulate():
                    buf.extend([
                        t0.x(), t0.y(), t0.z(),
                        t1.x(), t1.y(), t1.z(),
                        t2.x(), t2.y(), t2.z(),
                    ])
        self._sel_faces_spans = []
        first = 0
        for (front, back), buf in sel_face_runs.items():
            n = len(buf) // 3
            self._sel_faces_spans.append((front, back, first, n))
            first += n
        self._sel_faces_count = self._upload_vbo(
            self._sel_faces_vbo, "sel_faces",
            [buf.tobytes() for buf in sel_face_runs.values()]) // 12

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
        # Default-back tint (pos-only triangles; see ``back_is_default``):
        # the loose block, then one part per group chunk, subject last.
        dback_loose = array("f")
        subj_dback = array("f")
        sink = {"vcol": vcol, "tex": by_texture, "dback": dback_loose}
        from core.materials import back_is_default
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
            # (.skp two-sided paint). Emit an override copy that a culled
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

        # Inside an open group its faces are the loose mesh, and the
        # group's own paint (issue #47) must still dress the default ones.
        from core.group import effective_material as _eff_mat
        from core.materials import effective_attrs as _eff_attrs
        ctx_paint = _eff_mat(self.scene.edit_group)

        def bucket_face(face):
            if face in suppressed_faces:
                return
            attrs = _eff_attrs(face.attrs, ctx_paint)
            fcull = bucket_back(face)
            if back_is_default(attrs):
                db = sink["dback"]
                for t0, t1, t2 in self._tris_of(face):
                    db.extend([t0.x(), t0.y(), t0.z(),
                               t1.x(), t1.y(), t1.z(),
                               t2.x(), t2.y(), t2.z()])
            tex = attrs.get("texture")
            op = float(attrs.get("opacity", 1.0))
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
            col = attrs.get("color")
            base = tuple(col) if col is not None else self.DEFAULT_FACE_COLOR
            # Bake a subtle diffuse shade from the face normal against a fixed
            # world light — the matte-model look. World-fixed, so
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
        dback_parts: list = []        # default-back tint, per group chunk
        dback_spans: list = []        # (bbox, start-within-groups, count)
        dback_start = 0
        self._edit_split_db = None
        subject_bucketed = False
        pv_faces = getattr(self, "_preview_groups", None) or ()
        for g in draw_groups:         # context first, edited group last
            if (self._edit_split_f is None
                    and self.scene.edit_group is not None
                    and not self._draws_in_edit_context(g)):
                # BEFORE the skips, on purpose. The subject may well draw by
                # another path — an instanced placement does — and if the
                # boundary is only recorded for chunks that land in THIS
                # buffer, entering such a group left the split unset and
                # nothing faded at all (Marco, 2026-09-11, second level).
                self._edit_split_f = gface_start   # made absolute below
                self._edit_split_db = dback_start  # same rule, same moment
            if (not self.scene.entity_visible(g)
                    or getattr(g, "billboard", False)
                    or id(g) in pv_faces
                    or self._instanced_eligible(g)):
                continue
            if suppressed_faces and any(f in suppressed_faces
                                        for f in g.mesh.faces):
                # Bucketed into the SUBJECT block at the tail, not the loose
                # head — see ``sink``. The chunk is unusable while a face of
                # it is hidden.
                sink["vcol"], sink["tex"] = subj_vcol, subj_by_texture
                sink["dback"] = subj_dback
                for face in g.mesh.faces:
                    bucket_face(face)   # push/pull preview suppresses faces
                sink["vcol"], sink["tex"] = vcol, by_texture
                sink["dback"] = dback_loose
                subject_bucketed = True
                continue
            chunk = self._group_chunk(g)
            if chunk.get("dback"):
                dback_parts.append(chunk["dback"])
                dback_spans.append((chunk.get("bbox"), dback_start,
                                    len(chunk["dback"]) // 12))
                dback_start += len(chunk["dback"]) // 12
            face_parts.append(chunk["vcol"])
            group_face_spans.append((chunk.get("bbox"), gface_start,
                                     len(chunk["vcol"]) // 24))
            gface_start += len(chunk["vcol"]) // 24
            # The SUBJECT of the edit, for the textured pass — which draws
            # in its own runs and decides the fade with this flag, not with
            # the positional split. Comparing by identity against
            # `scene.edit_group` misses a nested group, because the draw list
            # holds a proxy of it: Marco's whole plaza came out washed, the
            # group he was editing included, because every textured face was
            # marked as surroundings (2026-09-11).
            subj = not self._draws_in_edit_context(g)
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

        # Default-back tint buffer: loose head, group chunks, bucketed
        # subject tail — the same shape as the faces buffer, so the fade
        # split and the frustum spans read the same way.
        db_loose_raw = dback_loose.tobytes()
        db_loose_n = len(db_loose_raw) // 12
        db_subj_raw = subj_dback.tobytes()
        db_parts = [db_loose_raw] + dback_parts + [db_subj_raw]
        self._dback_spans = ([(None, 0, db_loose_n)]
                             + [(bb, db_loose_n + st, n)
                                for bb, st, n in dback_spans])
        if self._edit_split_db is not None:
            self._edit_split_db += db_loose_n
        if db_subj_raw:
            db_subj_start = db_loose_n + dback_start
            self._dback_spans.append((None, db_subj_start,
                                      len(db_subj_raw) // 12))
            if subject_bucketed and self.scene.edit_group is not None:
                self._edit_split_db = db_subj_start
        self._dback_count = self._upload_vbo(
            self._dback_vbo, "dback", db_parts) // 12

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
        # up to here, then adds only the translucent runs that .skp rules cast
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
        matte face shading as colour faces). UVs come from
        ``core.texture.face_uv_axes`` — the face's fitted world→UV affine
        map when present (``uvw`` — an import carrying its own texture
        coordinates), else the .skp planar projection of each vertex's
        world position. The SAME function the .skp exporter writes from, so
        the viewport cannot drift from what the .skp file will show (it did: a
        private copy of the projection here used a different basis)."""
        key = (tex["path"], self._shade_factor(self._normal_of(face)))
        buf = by_texture.get(key)
        if buf is None:
            buf = by_texture[key] = array("f")
        gu, cu, gv, cv = face_uv_axes(tex, face.normal())
        for tri in self._tris_of(face):
            for p in tri:
                buf.extend([
                    p.x(), p.y(), p.z(),
                    QVector3D.dotProduct(gu, p) + cu,
                    QVector3D.dotProduct(gv, p) + cv,
                ])

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
                # Everything the chunk bakes, or a repaint that changes
                # only that term serves the stale chunk: the back side, the
                # translucency and a positioned map were missing here, so
                # painting the BACK of a face inside a group changed
                # nothing on screen (Marco, 2026-09-11, the first thing he
                # tried with two-sided paint). The disk digest already
                # walked all of them.
                back = f.attrs.get("back")
                a ^= hash((i,
                           None if c is None else tuple(c),
                           None if not t else (t.get("path"), t.get("sw"),
                                               t.get("sh"), t.get("rot", 0),
                                               tuple(t.get("uvw") or ())),
                           f.attrs.get("layer"),
                           f.attrs.get("opacity"),
                           repr(back) if back else None,
                           bool(f.attrs.get("hidden"))))
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
        fp = (len(mesh.vertices), len(mesh.edges), len(mesh.faces),
              round(s, 4), a, soft, hid)
        # Reverse Faces changes none of the above (#197): the mesh counts
        # its flips, and only a flipped mesh carries the extra term.
        wr = getattr(mesh, "_winding_rev", 0)
        return fp + (("winding", wr),) if wr else fp

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
        if entry.get("dback"):
            entry["dback"] = flat3(entry["dback"])
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
        from core.group import effective_material
        # A painted instance (issue #47) bakes its own variant of the
        # prototype: default faces in the container's paint. Unpainted
        # siblings keep sharing the plain bake.
        base = self._group_chunk(
            _proto_wrapper(self, mesh, effective_material(group)))
        xf = group.xform
        key = (base["uid"], tuple(xf.data()))
        cache = getattr(self, "_inst_chunks", None)
        if cache is None:
            cache = self._inst_chunks = {}
        cur = cache.get(id(group))
        if cur is not None and cur["ikey"] == key:
            return cur
        if cur is not None and cur["ikey"][0] == base["uid"]:
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

        det = float(np.linalg.det(L))
        mirrored = det < 0.0

        def tp32(raw, stride, cols=3, tris=True):
            a = np.frombuffer(raw, np.float32).reshape(-1, stride).copy()
            a[:, :cols] = tp(a[:, :cols].astype(np.float64)).astype(np.float32)
            if mirrored and tris and len(a) % 3 == 0:
                # A mirror turns every triangle inside out: what wound
                # counter-clockwise now winds clockwise, and GL would call
                # the painted side the BACK — the flipped lamp post came
                # out in the style's back colour, its yellow base and blue
                # panels gone («hice mirror a un componente y sus texturas
                # desaparecen», Marco, 2026-09-11). Swapping two corners of
                # each triangle keeps the front the front.
                a = a.reshape(-1, 3, stride)[:, [0, 2, 1], :].reshape(-1, stride)
            return a.tobytes()
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

        # The prototype's tones were baked from ITS normals against the fixed
        # world light: a rotated copy re-shades them for the faces as placed
        # (#482), with the bake's own law (``_shade_factor``) per triangle.
        light = np.array([self._LIGHT.x(), self._LIGHT.y(), self._LIGHT.z()])

        # Only a turn (or a mirror, or an uneven scale) changes the light; a
        # copy that is just moved or evenly scaled keeps the bake as it is.
        diag = np.diag(L)
        turned = not (np.allclose(L, np.diag(diag), atol=1e-9)
                      and diag[0] > 0.0 and np.allclose(diag, diag[0]))

        def matte(tri, quantise=False):  # (n, 3, 3) corners → shade (n,)
            n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            ln = np.linalg.norm(n, axis=1)
            d = np.abs(n @ light) / np.where(ln > 1e-9, ln, 1.0)
            f = 0.62 + 0.38 * d
            if quantise:                 # a texture run's key, as baked
                f = np.round(f * 32.0) / 32.0
            return np.where(ln > 1e-9, f, 0.84375)

        def tri_pos(raw, stride):
            a = np.frombuffer(raw, np.float32).reshape(-1, 3, stride)
            return a[:, :, :3].astype(np.float64)

        def reshade6(raw, placed):      # pos(3)+rgb(3), local → placed
            if (not turned or not raw or len(raw) % 72
                    or len(placed) != len(raw)):
                return placed
            k = (matte(tri_pos(placed, 6), quantise=True)
                 / matte(tri_pos(raw, 6), quantise=True))
            a = np.frombuffer(placed, np.float32).reshape(-1, 3, 6).copy()
            rgb = a[:, :, 3:6].astype(np.float64) * k[:, None, None]
            a[:, :, 3:6] = np.round(np.minimum(rgb, 1.0) * 64.0) / 64.0
            return a.tobytes()

        def with_shade(key, s):
            # The shade sits in the (path, shade) pair, at the front of
            # the key or as its first element.
            if isinstance(key[0], str):
                return (key[0], s) + tuple(key[2:])
            return ((key[0][0], s),) + tuple(key[1:])

        def rekey5(placed):             # {key: pos(3)+uv(2)} by new shade
            if not turned:
                return placed
            out: dict = {}
            for key, raw in placed.items():
                if not raw or len(raw) % 60:
                    out[key] = out.get(key, b"") + raw
                    continue
                f = matte(tri_pos(raw, 5), quantise=True)
                a = np.frombuffer(raw, np.float32).reshape(-1, 15)
                for s in np.unique(f):
                    nk = with_shade(key, float(s))
                    out[nk] = out.get(nk, b"") + a[f == s].tobytes()
            return out

        sp = base["soft_pts"]
        if sp is not None:
            s6 = sp.reshape(-1, 6).astype(np.float64)
            s6[:, 0:3] = tp(s6[:, 0:3])
            s6[:, 3:6] = tp(s6[:, 3:6])
            sp = s6.astype(np.float32)
        entry = {
            "ikey": key,
            "uid": next(_chunk_uid),
            "rev": (cur["rev"] + 1) if cur is not None else 0,
            "nv": base["nv"], "ne": base["ne"], "nf": base["nf"],
            "edges": tp32(base["edges"], 3, tris=False),
            "dback": tp32(base.get("dback", b""), 3),
            "vcol": reshade6(base["vcol"], tp32(base["vcol"], 6)),
            "by_texture": rekey5({p: tp32(raw, 5)
                                  for p, raw in base["by_texture"].items()}),
            "tcol": {a: reshade6(raw, tp32(raw, 6))
                     for a, raw in base.get("tcol", {}).items()},
            "ttex": rekey5({k: tp32(raw, 5)
                            for k, raw in base.get("ttex", {}).items()}),
            "back_vcol": reshade6(base.get("back_vcol", b""),
                                  tp32(base.get("back_vcol", b""), 6)),
            "back_tex": rekey5({k: tp32(raw, 5) for k, raw
                                in base.get("back_tex", {}).items()}),
            "back_tcol": {k: reshade6(raw, tp32(raw, 6))
                          for k, raw in base.get("back_tcol", {}).items()},
            "back_ttex": rekey5({k: tp32(raw, 5) for k, raw
                                 in base.get("back_ttex", {}).items()}),
            "fvcol": reshade6(base.get("fvcol", b""),
                              tp32(base.get("fvcol", b""), 6)),
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
        if entry.get("dback"):
            # The back-tint triangles ride along too — left behind, they
            # drew a white ghost of the arch where it stood before the
            # move (Marco, 2026-09-11, «roté el componente, moví y quedó
            # eso fantasma»).
            entry["dback"] = shift(entry["dback"], 3)
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
        # The container's paint (issue #47) changes what default faces
        # bake to without touching the mesh, so no serial or sample can
        # notice it: it is part of the entry's identity instead.
        from core.group import effective_material
        from core.materials import effective_attrs, material_sig
        paint = effective_material(group)
        msig = material_sig(paint)
        if entry is not None and entry.get("msig") != msig:
            entry = None
        # The entry answers for ONE mesh object. Explode hands every lifted
        # child a NEW mesh (moved by the container's matrix), and a copy's
        # mesh built the same way has the same mutation serial and counts:
        # the O(1) check below took the new mesh for the old one and drew
        # the group where it stood before it was grouped and moved, while
        # its selection box showed where it is (issue #134, @fafecm).
        if entry is not None and entry.get("mesh") is not mesh:
            entry = None
        from views import array_bake
        if array_bake.can_bake(mesh):
            # A lazy mesh (experimental engine) is baked from its arrays,
            # and stays unbuilt; while it is, it cannot have changed.
            if entry is None:
                entry = array_bake.bake(self, mesh, paint, msig, vkey,
                                        next(_chunk_uid))
                if msig is not None:
                    entry["fp"] = entry["fp"] + (("paint",) + msig,)
                cache[id(group)] = entry
            entry["vkey"] = vkey
            return entry
        if entry is not None:
            if entry.get("vkey") == vkey:
                return entry
            # Untouched since it was built or last accepted: no mutation
            # primitive bumped the mesh's serial and the counts agree — an
            # O(1) yes. A scene-version bump (any edit anywhere) used to send
            # EVERY placement's chunk through the probe and the samples on
            # the next paint: ~3300 validations, 15 ms per edit on the plaza
            # (2026-09-14).
            if (entry.get("serial") is not None
                    and entry["serial"] == getattr(mesh, "_mut_serial", None)
                    and not getattr(mesh, "_attrs_dirty", False)
                    and len(mesh.vertices) == entry["nv"]
                    and len(mesh.edges) == entry["ne"]
                    and len(mesh.faces) == entry["nf"]):
                entry["vkey"] = vkey
                return entry
            # The probe judges GEOMETRY only, and _shift_chunk reuses the
            # cached texture buckets as they are — so a repaint must not be
            # allowed to ride along inside a translation.
            if not getattr(mesh, "_attrs_dirty", False):
                d = self._translation_probe(entry, mesh)
                if d is not None:
                    self._shift_chunk(entry, d, mesh)
                    entry["vkey"] = vkey
                    entry["rev"] += 1
                    entry["serial"] = getattr(mesh, "_mut_serial", None)
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
                entry["serial"] = getattr(mesh, "_mut_serial", None)
                return entry
        fp = self._group_fp(group)
        if msig is not None:
            fp = fp + (("paint",) + msig,)   # past [:3]/[4:]: the disk key too
        if entry is not None:
            # The fingerprint's checksum is a SUM of coordinates, and a turn
            # about the centroid keeps the sum: Move's rotation grips turn a
            # group about its box centre every time, and the viewport went
            # on drawing the group where it was while its box showed where
            # it is (Marco, 25-09, «imagen fantasma»). The sampled vertices
            # settle it — up to 32 lookups.
            same = entry["fp"] == fp and self._samples_match(entry, mesh)
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
                entry["serial"] = getattr(mesh, "_mut_serial", None)
                mesh._chunk_dirty = False
                mesh._attrs_dirty = False
                return entry
        _c0 = _time_mod.perf_counter() if _PERF else 0.0
        # P4: before the expensive rebuild, try the on-disk chunk cache —
        # the arrays are deterministic from the mesh content, so a cold
        # open loads the 230k-face hedge in ~0.3 s instead of building it
        # for ~6 s. Keyed by a STABLE content digest (the in-session
        # fingerprint uses process-salted hash()).
        _loader = getattr(self, "_chunk_cache_load", None)   # stub VPs in tests
        disk = _loader(group, fp, vkey) if callable(_loader) else None
        if disk is not None and not self._samples_match(disk, mesh):
            disk = None      # same digest, turned geometry (see above)
        if disk is not None:
            cache[id(group)] = disk
            disk["msig"] = msig
            disk["mesh"] = mesh
            disk["serial"] = getattr(mesh, "_mut_serial", None)
            mesh._chunk_dirty = False
            mesh._attrs_dirty = False
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
        dback_faces: list = []        # face index → its back is the default
        faces: list = []
        areas: list = []
        tris = array("d")             # 9 doubles per triangle
        tri_ent: list = []
        from core.materials import back_is_default
        # Per-face geometry memo (normal, area, triangles as floats, centroid)
        # keyed on the face's exact vertex positions: an edit inside a big
        # group touches a few faces, and every other face's Newell walk and
        # triangulation was redone on each edit — ~1 s per stroke inside the
        # Plaza's 25 797-face group (09-10). Reused only when every corner is
        # where it was, so the chunk is the one a full rebuild makes.
        editing_now = getattr(self, "_editing_meshes", None)
        if callable(editing_now) and id(mesh) not in editing_now():
            memo = None             # see below: only the edited mesh keeps one
            built: dict = {}        # this build's geometry, never kept
        else:
            memo = mesh.__dict__.get("_face_geom_memo")
            if memo is None or len(memo) > 2 * len(mesh.faces) + 64:
                memo = mesh.__dict__["_face_geom_memo"] = {}
            built = memo
        for f in mesh.faces:
            if f.attrs.get("hidden"):
                # Hide on a face: out of the chunk entirely — not
                # drawn, not picked, not snapped. Its edges stay (below).
                continue
            fattrs = effective_attrs(f.attrs, paint)
            i = len(faces)
            faces.append(f)
            geom = _face_geometry(f, memo, _triangulate)
            if memo is None:
                built[id(f)] = geom     # this build's, for the soft edges
            normal, area, tri_list = geom[1], geom[2], geom[3]
            areas.append(area)
            fprops[id(f)] = normal
            back = fattrs.get("back")
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
            tex = fattrs.get("texture")
            op = float(fattrs.get("opacity", 1.0))
            if tex is not None and tex.get("path"):
                if op < 0.999:
                    self._append_textured_face(
                        by_ttexture.setdefault((round(op, 3), fcull), {}),
                        f, tex)
                else:
                    self._append_textured_face(by_texture, f, tex)
            else:
                col = fattrs.get("color")
                base = tuple(col) if col is not None else self.DEFAULT_FACE_COLOR
                shade = geom[5]
                rgb = shade.get(base)
                if rgb is None:
                    rgb = shade[base] = self._shaded_color(base, normal)
                r, g, b = rgb
                if op < 0.999:
                    dest = tcol.setdefault((round(op, 3), fcull), array("f"))
                elif fcull:
                    dest = None
                else:
                    dest = vcol
                if dest is None:
                    buf = array("f")
                    for t0, t1, t2 in tri_list:
                        buf.extend([*t0, r, g, b, *t1, r, g, b, *t2, r, g, b])
                    fcull_vcol_parts.append(buf.tobytes())
                    dest = array("f")   # discarded sink for the shared loop
                for t0, t1, t2 in tri_list:
                    dest.extend([*t0, r, g, b, *t1, r, g, b, *t2, r, g, b])
            tris.extend(geom[6])
            tri_ent.extend([i] * len(tri_list))
            if tri_list and back_is_default(fattrs):
                dback_faces.append(i)

        sprops: dict = {}

        def props(f):
            r = sprops.get(id(f))
            if r is None:
                hit = built.get(id(f))
                if hit is not None and hit[7] is not None:
                    r = sprops[id(f)] = hit[7]
                    return r
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
            t = np.frombuffer(tris.tobytes(), dtype=np.float64).reshape(-1, 3, 3)
            v0, e1, e2 = t[:, 0], t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]
            tri_ent_a = np.asarray(tri_ent, dtype=np.int64)
            # The default-back tint triangles, cut from the pick triangles
            # already assembled instead of re-walked per face in Python
            # (that walk cost the chunk build a fifth on the plaza).
            if dback_faces:
                keep = np.zeros(len(faces), dtype=bool)
                keep[dback_faces] = True
                dback_raw = t[keep[tri_ent_a]].astype(np.float32).tobytes()
            else:
                dback_raw = b""
        else:
            v0 = e1 = e2 = tri_ent_a = None
            dback_raw = b""
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
        entry = {"fp": fp, "vkey": vkey, "rev": 0, "uid": next(_chunk_uid),
                 "msig": msig,
                 "serial": getattr(mesh, "_mut_serial", None),
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
                 "dback": dback_raw,
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
        mesh._attrs_dirty = False
        entry["mesh"] = mesh
        cache[id(group)] = entry
        _store = getattr(self, "_chunk_cache_store", None)   # stub VPs in tests
        editing = getattr(self, "_editing_meshes", None)
        if not (callable(editing) and id(mesh) in editing()):
            # The per-face memo only pays off for the mesh being edited
            # (each stroke rebuilds its chunk); kept for every mesh it cost
            # +140 MB on the Plaza (release_check 10-10). Entering a group
            # rebuilds it on the first stroke, as before the memo existed.
            mesh.__dict__.pop("_face_geom_memo", None)
        # Not while the group is open: each stroke inside it rebuilds this
        # chunk, and pickling 25 000 faces after every one held the GIL
        # ~350 ms beside the UI (Plaza, 09-10) for an entry the next stroke
        # made stale. The cold build on opening still lands on disk.
        if callable(_store) and not (callable(editing)
                                     and id(mesh) in editing()):
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
        if len(fp) > 7 and fp[7][0] == "winding":
            # Flipped this session (#197): never the digest of the same
            # mesh before the flip, which would serve its old winding.
            h.update(repr(fp[7]).encode())
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
            if a.get("hidden"):
                # Only when hidden, so meshes without one keep their
                # pre-existing digests (same reason as the edge term).
                h.update(repr(("fhidden", i)).encode())
        return h.hexdigest()

    _CHUNK_CACHE_FIELDS = (
        "edges", "vcol", "by_texture", "tcol", "ttex", "back_vcol",
        "back_tex", "back_tcol", "back_ttex", "fvcol", "dback", "areas",
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
            if stored.get("nf") != len(mesh.faces) or "dback" not in stored:
                return None          # a cache predating the back-side tint
            entry = dict(stored)
            entry.update(fp=fp, vkey=vkey, rev=0, uid=next(_chunk_uid),
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
        if len(spans) >= _SPAN_VECTOR_MIN and planes:
            return self._visible_spans_np(spans, planes, split)
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

    def _visible_spans_np(self, spans, planes, split=None):
        """:meth:`_visible_spans` over many spans at once: the same p-vertex
        test, float op for float op, on arrays kept per span list (a model
        of 21 406 placements tested ~4 800 boxes one by one per frame)."""
        import numpy as np
        memo = getattr(self, "_span_arrays", None)
        if memo is None:
            memo = self._span_arrays = {}
        hit = memo.get(id(spans))
        if hit is None or hit[0] is not spans:
            if len(memo) > 16:
                memo.clear()
            n = len(spans)
            has = np.zeros(n, dtype=bool)
            lo = np.zeros((n, 3))
            hi = np.zeros((n, 3))
            start = np.empty(n, dtype=np.int64)
            count = np.empty(n, dtype=np.int64)
            for i, (bbox, s0, c0) in enumerate(spans):
                start[i] = s0
                count[i] = c0
                if bbox is not None:
                    has[i] = True
                    lo[i], hi[i] = bbox[0], bbox[1]
            hit = memo[id(spans)] = (spans, has, lo, hi, start, count)
        _s, has, lo, hi, start, count = hit
        vis = np.ones(len(start), dtype=bool)
        for nx, ny, nz, d in planes:
            px = hi[:, 0] if nx >= 0.0 else lo[:, 0]
            py = hi[:, 1] if ny >= 0.0 else lo[:, 1]
            pz = hi[:, 2] if nz >= 0.0 else lo[:, 2]
            vis &= ~(((nx * px + ny * py) + nz * pz) + d < 0.0)
        live = count > 0
        drawn = live & (vis | ~has)
        culled = int(count[live & ~drawn].sum())
        idx = np.flatnonzero(drawn)
        if not len(idx):
            return [], culled
        st = start[idx]
        ct = count[idx]
        brk = np.ones(len(idx), dtype=bool)
        brk[1:] = st[1:] != st[:-1] + ct[:-1]
        if split is not None:
            # A run never crosses the split (see _visible_spans).
            brk[1:] |= (st[:-1] < split) & (split <= st[1:])
        heads = np.flatnonzero(brk)
        sums = np.add.reduceat(ct, heads)
        return list(zip(st[heads].tolist(), sums.tolist())), culled

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
