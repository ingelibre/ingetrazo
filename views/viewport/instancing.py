# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Instanced component drawing: placements, prototype draw entries, recorded GL passes."""
from __future__ import annotations

from PySide6.QtGui import QVector2D, QVector3D, QVector4D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLVertexArrayObject
from core.group import Group
from core.style import effective_back_color
from core.materials import material_sig as _material_sig
from views.viewport._support import (_NO_INSTANCING, _NO_BACK_TINT, GL_FLOAT, GL_LINES,
                                     GL_TRIANGLES, GL_POLYGON_OFFSET_FILL, GL_CULL_FACE, GL_CW,
                                     GL_CCW, GL_FRONT, GL_LEQUAL, GL_GREATER, GL_FALSE, GL_TRUE,
                                     _lean_instanced, _LEAN_NATIVE_REPLAY, _GlTape, _TAPE_FUNCS,
                                     _InstanceBatch, _proto_wrapper, _cache_ver, EDIT_REST_FADE,
                                     XRAY_FACE_OPACITY)


class InstancingMixin:
    """Instanced component drawing: placements, prototype draw entries, recorded GL passes."""

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
        # A MIRRORED placement turns the prototype's triangles inside out
        # for GL (front becomes back). It used to fall back to the
        # consolidated path, one baked copy per placement — «mirrors are
        # rare», until an industrial model brought 6 203 of them, 4.2
        # million faces baked one by one (issue #158). It draws instanced
        # now, in batches of its own under a clockwise front face
        # (``_front_face``).
        from core.group import effective_material
        paint = effective_material(g)
        # The answer is the prototype's (and its paint's), which the
        # placements epoch covers: once per prototype, not per placement
        # (64 000 calls per rebuild on the plant of #158, ~1.5 s an undo).
        epoch_of = getattr(self, "_placements_epoch", None)
        memo = None
        # Not the mesh open for editing: the epoch leaves its changes out
        # (they are the per-frame half), and a paint inside could turn it
        # translucent under the same epoch.
        if epoch_of is not None and g.mesh is not self.scene.mesh:
            epoch = epoch_of()
            memo = getattr(self, "_elig_memo", None)
            if memo is None or memo[0] != epoch:
                memo = self._elig_memo = (epoch, {})
            mkey = (id(g.mesh), _material_sig(paint))
            hit = memo[1].get(mkey)
            if hit is not None and hit[0] is g.mesh:
                return hit[1]
        base = self._proto_base_chunk(g.mesh, paint)
        # Translucent / back-side / glass content still rides the
        # consolidated passes (they need global draw ordering).
        ok = not (base.get("tcol") or base.get("ttex")
                  or base.get("back_vcol") or base.get("back_tex")
                  or base.get("back_tcol") or base.get("back_ttex")
                  or base.get("fvcol"))
        if memo is not None:
            memo[1][mkey] = (g.mesh, ok)
        return ok

    def _proto_base_chunk(self, mesh, paint=None):
        """The prototype's chunk in LOCAL coordinates (the same wrapper
        ``_instance_chunk`` derives from). ``paint`` is the container
        material the variant is baked in (issue #47): a painted instance
        has its own bake of the prototype, unpainted siblings share the
        plain one."""
        return self._group_chunk(_proto_wrapper(self, mesh, paint))

    def _placements_epoch(self):
        """A signature of everything the per-frame placement passes read:
        the group tree (ids, matrices, mesh mutation serials, tags), the
        layer states, the open context and the preview. Passes that used
        to key on the scene version — which every frame of a loose-mesh
        drag bumps — key on this instead, so moving a face beside 1 300
        placements no longer re-gathers, re-signs and re-syncs them all
        (~30 ms a frame on the plaza, 2026-09-14). One walk (~2 ms),
        memoised per tick (a paint or a hover) and scene version."""
        sc = self.scene
        tick = getattr(self, "_tick", 0)
        memo = getattr(self, "_epoch_memo", None)
        if memo is not None and memo[0] == (tick, _cache_ver(self)):
            return memo[1]
        # Across ticks: while the version is live (not frozen by a groups
        # preview, whose matrices move without a version bump) and none of
        # the cheap switches moved, nothing the walk reads can have changed
        # — every edit of a group goes through a command that bumps the
        # version. Orbiting a model of 21 406 placements walked them all on
        # every frame, ~55 ms (issue #158).
        cheap = (sc.version, id(sc.edit_group), id(sc.mesh),
                 getattr(self, "_preview_epoch", 0),
                 bool(getattr(self, "_preview_groups", None)),
                 getattr(self, "_edit_rest_mode", None),
                 bool(getattr(sc, "show_hidden_objects", False)),
                 bool(getattr(sc, "show_hidden_geometry", False)),
                 tuple((ly.name, ly.visible, ly.locked) for ly in sc.layers),
                 len(sc.groups))
        live = getattr(self, "_frozen_cache_version", None) is None
        same = getattr(self, "_epoch_same", None)
        if live and same is not None and same[0] == cheap:
            self._epoch_memo = ((tick, _cache_ver(self)), same[1])
            return same[1]
        parts: list = [id(sc.edit_group), id(sc.mesh),
                       getattr(self, "_preview_epoch", 0),
                       bool(getattr(self, "_preview_groups", None)),
                       getattr(self, "_edit_rest_mode", None),
                       # View ▸ Hidden Objects / Geometry decide which
                       # placements the pick block lists as selectable. The
                       # per-group ``hidden`` below was in the key, the two
                       # switches were not: Hide rebuilt the block without
                       # the object, and turning the view on left that
                       # block in place — the ghost was drawn and could not
                       # be clicked, only window-selected (issue #53,
                       # @pacaeiro).
                       bool(getattr(sc, "show_hidden_objects", False)),
                       bool(getattr(sc, "show_hidden_geometry", False)),
                       # Hide Similar Components drops placements too.
                       bool(getattr(sc, "hide_similar_components", False)),
                       tuple((ly.name, ly.visible, ly.locked) for ly in sc.layers)]

        loose = sc.mesh

        def part(g):
            m = g.mesh
            xf = g.xform
            # The mesh open for editing IS the loose mesh: its content is
            # the version-keyed half (rebuilt per frame of a drag), not the
            # placements half — counting its serial here re-keyed every
            # cache on every drag frame (81 ms a frame instead of 56).
            serial = (getattr(m, "_mut_serial", None)
                      if m is not None and m is not loose else None)
            # ``locked`` too: the pick block lists a group as selectable or
            # not, and a padlock that did not re-key it left the group
            # movable and openable from the view.
            return (id(g), id(m), serial,
                    tuple(xf.data()) if xf is not None else None,
                    g.layer, bool(g.billboard), bool(g.hidden),
                    bool(getattr(g, "locked", False)),
                    _material_sig(getattr(g, "material", None)))

        pv = getattr(self, "_preview_groups", None) or ()
        base = getattr(self, "_epoch_frozen_base", None)
        if (not live and pv and base is not None and base[0] == cheap
                and base[1] == parts):
            # A frozen preview (a drag): only the previewed groups can
            # move, so only their parts are made again — the walk over
            # every placement ran on every frame (21 406 of them, #158).
            # The same parts in the same order: the very same epoch.
            whole = base[2]
            for i, g in base[3]:
                whole[i] = part(g)
            epoch = hash(tuple(whole))
            self._epoch_memo = ((tick, _cache_ver(self)), epoch)
            self._epoch_same = None
            return epoch
        movers: list = []
        head = len(parts)

        def walk(g):
            if id(g) in pv:
                movers.append((len(parts), g))
            parts.append(part(g))
            for c in (g.children or ()):
                walk(c)
        for g in sc.groups:
            walk(g)
        epoch = hash(tuple(parts))
        # (cheap key, the parts before the walk, every part, the movers'
        # slots) — what the next frozen frame starts from.
        self._epoch_frozen_base = ((cheap, parts[:head], list(parts), movers)
                                   if not live and pv else None)
        self._epoch_memo = ((tick, _cache_ver(self)), epoch)
        self._epoch_same = (cheap, epoch) if live else None
        return epoch

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
        ctx = self.scene.edit_group
        # The expansion only changes with the placements (their matrices
        # included, in the epoch): rebuilt twice a frame it cost ~65 ms on
        # a model of 21 406 placements (issue #158).
        epoch_of = getattr(self, "_placements_epoch", None)
        key = (epoch_of(), id(groups), len(groups)) if epoch_of else None
        memo = getattr(self, "_placements_memo", None)
        if key is not None and memo is not None and memo[0] == key:
            return memo[1]
        anidado = ctx is not None and getattr(ctx, "children", None)
        if not anidado and not any(getattr(g, "children", None) for g in groups):
            self._placements_memo = (key, groups)
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
        self._placements_memo = (key, out)
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

        ctx = self.scene.edit_group

        def walk(node, world, dentro=None, hidden=False):
            """``dentro`` = the first-level child of the open context this
            subtree hangs from, or ``None`` outside it.

            INSIDE a group its children are the first-class objects: `owner`
            points at the child, so a click selects the bench and not the
            plaza, and `context` marks them as the subject so the draw
            passes do not fade the very thing being edited. It has to work
            at ANY depth — entering a group inside a group is the whole
            point (Marco, 2026-09-11: «eso igual debe ser para grupos
            anidados»).
            """
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
                # parent's (the .skp convention); and when the parent's tag is hidden or
                # locked the whole instance goes with it, whatever its
                # children are tagged.
                proxy.layer = forced or child.layer or node.layer
                proxy.billboard = child.billboard
                # Hide on an object takes its whole subtree along, and a
                # hidden child stays hidden inside a visible parent.
                proxy.hidden = hidden or bool(child.hidden)
                proxy.material = getattr(child, "material", None)
                if child is ctx:
                    # The group being edited, reached as a nested placement:
                    # it is the SUBJECT, not surroundings. Comparing by
                    # identity against `scene.edit_group` misses here, because
                    # what the draw list holds is this proxy.
                    proxy.owner, proxy.context = child, ctx
                elif ctx is not None and node is ctx:
                    proxy.owner, proxy.context = child, ctx
                elif dentro is not None:
                    proxy.owner, proxy.context = dentro, ctx
                else:
                    proxy.owner, proxy.context = group, None
                proxy.xform = m
                out.append(proxy)
                if child.children:
                    walk(child, m,
                         child if (ctx is not None and node is ctx) else dentro,
                         proxy.hidden)

        walk(group, getattr(group, "xform", None), hidden=bool(group.hidden))
        return out

    def prepare_drawing(self, progress=None) -> None:
        """Build the drawing data of every group and prototype now, with
        ``progress(fraction, text)`` called a few times a second — what the
        first paint would otherwise do in one go: 55 s on a model of 21 406
        placements, long enough for the desktop to call IngeTrazo «not
        responding» (Marco, 01-10, #158). Pure NumPy, no GL needed."""
        import time
        from core.group import effective_material
        groups = self._placements()
        n = max(1, len(groups))
        from views import array_bake
        array_bake.prefetch(g.mesh for g in groups)
        last = time.monotonic()
        done: set = set()
        for i, g in enumerate(groups):
            if getattr(g, "billboard", False):
                continue
            try:
                if getattr(g, "xform", None) is not None:
                    key = (id(g.mesh), _material_sig(effective_material(g)))
                    if key not in done:
                        done.add(key)
                        self._proto_base_chunk(g.mesh, effective_material(g))
                    if not self._instanced_eligible(g):
                        self._group_chunk(g)
                else:
                    self._group_chunk(g)
            except Exception:                  # noqa: BLE001 - paint retries
                pass
            now = time.monotonic()
            if progress is not None and now - last > 0.25:
                progress(i / n, "Preparing the drawing…")
                last = now

    def _placement_bbox(self, g):
        """World AABB of an instanced placement from its PROTOTYPE's local
        box and the placement matrix — eight corners, no bake. Reading it
        off ``_group_chunk(g)`` baked the whole placement to world
        coordinates only to take its box: on the model of issue #158 that
        was 21 000 baked copies of geometry the instanced pass never uses."""
        return self._placement_frame(g)[0]

    def _placement_frame(self, g):
        """``(world bbox, inverse matrix)`` of an instanced placement,
        cached per placement and keyed on its matrix and its prototype's
        bake: the silhouette pass asks for both for every placement at up
        to 12 Hz, and working them out in Python each time cost ~7 ms a
        pass on the plaza's 1 359 placements (release check, 30-09)."""
        from core.group import effective_material
        base = self._proto_base_chunk(g.mesh, effective_material(g))
        m = g.xform
        key = (base.get("uid"), tuple(m.data()))
        cache = getattr(self, "_placement_frames", None)
        if cache is None:
            cache = self._placement_frames = {}
        hit = cache.get(id(g))
        if hit is not None and hit[0] == key:
            return hit[1]
        bb = base.get("bbox")
        box = None
        if bb:
            (x0, y0, z0), (x1, y1, z1) = bb
            pts = [m.map(QVector3D(x, y, z))
                   for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
            box = ((min(p.x() for p in pts), min(p.y() for p in pts),
                    min(p.z() for p in pts)),
                   (max(p.x() for p in pts), max(p.y() for p in pts),
                    max(p.z() for p in pts)))
        inv, ok = m.inverted()
        if len(cache) > 4 * max(64, len(getattr(self, "_inst_pool", (0, ()))[1]
                                         if getattr(self, "_inst_pool", None)
                                         else ())):
            cache.clear()                  # ids of placements long gone
        val = (box, inv if ok else None)
        cache[id(g)] = (key, val)
        return val

    def _front_face(self, mirrored: bool) -> None:
        """Clockwise front faces for a MIRRORED batch — the mirror flips the
        winding of every prototype triangle, and GL decides front and back
        (``gl_FrontFacing``, the culled back-tint pass) by winding."""
        self._gl.glFrontFace(GL_CW if mirrored else GL_CCW)

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
        key = (self._placements_epoch(), id(self.scene.mesh),
               getattr(self, "_preview_epoch", 0),
               getattr(self, "_frozen_cache_version", None))
        pool = getattr(self, "_inst_pool", None)
        if pool is None or pool[0] != key:
            from core.group import effective_material
            groups: list = []
            boxes: list = []
            codes: list = []
            protos: list = []             # code → (mesh, paint, mirrored)
            code_of: dict = {}
            for g in self._placements():
                if id(g) in pv or not self.scene.entity_visible(g):
                    continue
                if not self._instanced_eligible(g):
                    continue
                groups.append(g)
                boxes.append(self._placement_bbox(g))
                # Which pool (prototype, container paint, mirror) it draws
                # in, and its matrix: fixed while the placements are, so
                # not worked out again per frame (#158: 21 406 placements).
                paint = effective_material(g)
                mirrored = g.xform.determinant() < 0.0
                pk = (id(g.mesh), _material_sig(paint), mirrored)
                c = code_of.get(pk)
                if c is None:
                    c = code_of[pk] = len(protos)
                    protos.append((g.mesh, paint, mirrored))
                codes.append(c)
            # Boxless chunks (unknown extents) always draw: give them an
            # infinite box so the vectorised test keeps them.
            lo = np.array([b[0] if b else (-np.inf,) * 3 for b in boxes],
                          dtype=np.float64).reshape(-1, 3)
            hi = np.array([b[1] if b else (np.inf,) * 3 for b in boxes],
                          dtype=np.float64).reshape(-1, 3)
            codes_a = np.asarray(codes, dtype=np.int64)
            mats = np.array([g.xform.data() for g in groups],
                            dtype=np.float32).reshape(-1, 16)
            by_code = np.argsort(codes_a, kind="stable")
            pool = self._inst_pool = (key, groups, lo, hi, codes_a, protos,
                                      mats, by_code)
        _k, groups, lo, hi, codes_a, protos, mats, by_code = pool
        out: dict = {}
        if not groups:
            self._frame_instanced = out
            return out
        if planes is None:
            keep = np.ones(len(groups), dtype=bool)
        else:
            # Same p-vertex test as ``_aabb_visible``, all boxes at once —
            # a plane at a time on the box columns (the (planes, boxes, 3)
            # array it used to build was most of a frame's gather, #158);
            # the same products and sums, in the same order.
            keep = np.ones(len(groups), dtype=bool)
            for pl in planes:
                nx, ny, nz, d = (float(c) for c in pl)
                px = hi[:, 0] if nx >= 0.0 else lo[:, 0]
                py = hi[:, 1] if ny >= 0.0 else lo[:, 1]
                pz = hi[:, 2] if nz >= 0.0 else lo[:, 2]
                keep &= ((px * nx + py * ny) + pz * nz) + d >= 0.0
        # One pool per (prototype, container paint): a painted instance
        # (issue #47) draws its own bake of the prototype, not the plain
        # one its siblings share — pooled by mesh alone it kept showing
        # unpainted from outside while its inside (the loose bake) was
        # painted (Marco, 2026-09-21, bench test 21).
        # The same placements in view as last frame (an orbit mostly keeps
        # them): the same batches, so the matrix buffers need no look.
        memos = getattr(self, "_inst_frame_memo", None)
        if memos is None:
            memos = self._inst_frame_memo = {}
        last = memos.get(planes is None)       # the camera's, the shadows'
        if (last is not None and last[0] is pool
                and np.array_equal(last[1], keep)):
            self._frame_instanced = last[2]
            return last[2]
        # The kept placements of each pool, in placement order, the pools
        # in the order their first kept placement comes (the face-by-face
        # dict this replaces filled them so).
        kept = by_code[keep[by_code]]
        if not len(kept):
            self._frame_instanced = out
            return out
        kc = codes_a[kept]
        cuts = np.flatnonzero(np.diff(kc)) + 1
        starts = np.concatenate([[0], cuts])
        ends = np.concatenate([cuts, [len(kept)]])
        firsts = kept[starts]
        for j in np.argsort(firsts, kind="stable").tolist():
            idx = kept[starts[j]:ends[j]]
            mesh, paint, mirrored = protos[int(kc[starts[j]])]
            batch = _InstanceBatch(groups[i] for i in idx.tolist())
            batch.idx = idx
            batch.mats = mats
            out[(id(mesh), _material_sig(paint), mirrored)] = (
                mesh, paint, batch, mirrored)
        memos[planes is None] = (pool, keep, out)
        self._frame_instanced = out
        return out

    def _ensure_proto_draw(self, mesh, paint=None):
        """Static draw entry of one prototype: vcol/edges/texture VBOs from
        the LOCAL base chunk, three VAOs wiring them to the shared
        per-instance matrix buffer (divisor 1), built once per proto rev —
        and per container paint (issue #47)."""
        cache = getattr(self, "_proto_draw", None)
        if cache is None:
            cache = self._proto_draw = {}
        # While the placements (and so every prototype's bake) are as they
        # were, the entry is the one already made: re-deriving the base
        # chunk's fingerprint per prototype, per pass, per frame was a large
        # part of drawing 2 722 prototypes (live profile, #158).
        ckey = (id(mesh), _material_sig(paint))
        epoch = self._placements_epoch()
        fast = getattr(self, "_proto_draw_fast", None)
        if fast is None or fast[0] != epoch:
            fast = self._proto_draw_fast = (epoch, {})
        hit = fast[1].get(ckey)
        if hit is not None and cache.get(ckey) is hit:
            return hit
        entry = self._ensure_proto_draw_slow(mesh, paint, cache)
        fast[1][ckey] = entry
        return entry

    def _ensure_proto_draw_slow(self, mesh, paint, cache):
        base = self._proto_base_chunk(mesh, paint)
        key = (base["uid"], base.get("rev"))
        ckey = (id(mesh), _material_sig(paint))
        entry = cache.get(ckey)
        if entry is not None and entry["key"] == key:
            return entry
        if entry is not None:
            # The prototype changed: its GPU objects go back to the driver.
            # Replacing the entry alone kept 4 VAOs and 5 buffers alive per
            # edit of a component, for the whole session.
            self._destroy_proto_draw_entry(entry)

        def static_vbo(raw):
            vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            vbo.setUsagePattern(QOpenGLBuffer.StaticDraw)
            vbo.create()
            vbo.bind()
            vbo.allocate(raw or b"\0" * 4, max(len(raw), 4))
            vbo.release()
            return vbo

        self._program.bind()
        vcol_raw = base["vcol"]
        edges_raw = base["edges"]
        dback_raw = base.get("dback", b"")
        # textures: pos(3)+uv(2), one run per (path, shade)
        tex_parts = []
        tex_runs = []
        start = 0
        for tkey, raw in base["by_texture"].items():
            tex_parts.append(raw)
            n = len(raw) // 20
            tex_runs.append((tkey, start, n))
            start += n
        entry = {"key": key,
                 "vcol_vbo": static_vbo(vcol_raw),
                 "vcol_count": len(vcol_raw) // 24,
                 "edges_vbo": static_vbo(edges_raw),
                 "edge_count": len(edges_raw) // 12,
                 "dback_vbo": static_vbo(dback_raw),
                 "dback_count": len(dback_raw) // 12,
                 "tex_vbo": static_vbo(b"".join(tex_parts)),
                 "tex_runs": tex_runs}
        entry.update(self._wire_proto_vaos(entry))
        # The main program stays BOUND. This is built mid-frame, from a pass
        # that is drawing with it, and releasing it here left every draw
        # call after this point without a shader: the first frame after a
        # prototype changed showed nothing from here on — the edited group,
        # its instanced neighbours, the axes, the figure. Inside a nested
        # group every edit changes a prototype, so every edit blanked the
        # group for a frame («por un segundo el grupo desaparece, pensé que
        # se había eliminado», Marco, 2026-09-11). With shadows on it never
        # showed: the shadow pass builds the entry first and rebinds its own
        # depth program afterwards.
        cache[ckey] = entry
        return entry

    def _wire_proto_vaos(self, statics) -> dict:
        """A per-instance matrix buffer and the four VAOs that draw the
        prototype's static buffers (``statics``: vcol/edges/dback/tex
        ``_vbo``) with it, divisor 1 — ``mat_sig`` empty. Program bound."""
        extra = self.context().extraFunctions()
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

        def vao(vbo, attrs, stride):
            v = QOpenGLVertexArrayObject(self)
            v.create()
            v.bind()
            vbo.bind()
            for loc, offset, size in attrs:
                self._program.enableAttributeArray(loc)
                self._program.setAttributeBuffer(loc, GL_FLOAT, offset, size,
                                                 stride)
            vbo.release()
            wire_matrix()
            v.release()
            return v
        pos = (self._loc_pos, 0, 3)
        return {"mat_vbo": mat_vbo, "mat_sig": None,
                # vcol: pos(3)+rgb(3); edges, default-back tint: pos(3);
                # textures: pos(3)+uv(2)
                "vcol_vao": vao(statics["vcol_vbo"],
                                (pos, (self._loc_vcolor, 12, 3)), 24),
                "edges_vao": vao(statics["edges_vbo"], (pos,), 12),
                "dback_vao": vao(statics["dback_vbo"], (pos,), 12),
                "tex_vao": vao(statics["tex_vbo"],
                               (pos, (self._loc_uv, 12, 2)), 20)}

    def _proto_view(self, entry, mirrored: bool) -> dict:
        """The draw entry a batch of ``mirrored`` placements uses: the
        prototype's own, or its mirror view — the same static buffers with
        a matrix buffer and VAOs of its own, so a prototype placed both
        ways no longer refills one matrix buffer twice per pass, every
        frame (6 203 mirrored copies in #158)."""
        if not mirrored:
            return entry
        view = entry.get("mirror")
        if view is None:
            self._program.bind()
            view = dict(entry)
            view.pop("mirror", None)
            view.update(self._wire_proto_vaos(entry))
            view["mat_batch"] = None
            view["shared"] = True
            entry["mirror"] = view
        return view

    @staticmethod
    def _destroy_proto_draw_entry(entry) -> None:
        """Free one prototype draw entry's VAOs and buffers (GL context
        current) — and its mirror view's own (the static buffers are the
        entry's)."""
        mirror = entry.pop("mirror", None)
        if mirror is not None:
            for k in ("mat_vbo", "vcol_vao", "edges_vao", "dback_vao",
                      "tex_vao"):
                obj = mirror.get(k)
                try:
                    obj.destroy()
                    if k.endswith("_vao"):
                        obj.deleteLater()
                except (RuntimeError, AttributeError):
                    pass
        for k, obj in entry.items():
            if k.endswith("_vao") or k.endswith("_vbo"):
                try:
                    obj.destroy()
                    if k.endswith("_vao"):
                        obj.deleteLater()      # a QObject child of the viewport
                except RuntimeError:           # already gone with the context
                    pass

    def _update_inst_matrices(self, entry, groups) -> int:
        # The placements' matrices are in the epoch: with it and the ids,
        # nothing has to read sixteen numbers per placement per pass
        # (~20 ms a frame for 21 406 placements, issue #158). A groups
        # preview moves matrices under a frozen version; the epoch is
        # walked every tick then, so it still sees them.
        epoch_of = getattr(self, "_placements_epoch", None)
        if isinstance(groups, _InstanceBatch) and epoch_of is not None:
            # A frame's pool: its pool indices say which placements, and
            # the pool holds their matrices already.
            if entry.get("mat_batch") is groups:
                return len(groups)          # this very batch is in
            import numpy as np
            sig = (epoch_of(), id(groups.mats), len(groups.idx))
            old = entry["mat_sig"]
            if (old is not None and old[0] == sig
                    and np.array_equal(old[1], groups.idx)):
                entry["mat_batch"] = groups
                return len(groups)
            raw = groups.mats[groups.idx].tobytes()
            entry["mat_vbo"].bind()
            entry["mat_vbo"].allocate(raw, len(raw))
            entry["mat_vbo"].release()
            entry["mat_sig"] = (sig, groups.idx)
            entry["mat_batch"] = groups
            return len(groups)
        if epoch_of is not None:
            sig = (epoch_of(), tuple(map(id, groups)))
        else:
            sig = tuple((id(g), tuple(g.xform.data())) for g in groups)
        if entry["mat_sig"] != sig:
            import numpy as np
            raw = np.asarray([list(g.xform.data()) for g in groups],
                             dtype=np.float32).tobytes()
            entry["mat_vbo"].bind()
            entry["mat_vbo"].allocate(raw, len(raw))
            entry["mat_vbo"].release()
            entry["mat_sig"] = sig
            entry["mat_batch"] = None
        return len(groups)

    def _instanced_batches(self, groups):
        """``[(placements, fade)]`` for one prototype, split by the edit
        context.

        The instanced path is a SEPARATE draw call, so the fade split the
        chunk buffers carry means nothing to it: while you were inside a
        group, every instanced placement kept drawing at full strength and
        the rest of the model did not dim at all («hago doble clic y lo demás
        no se atenúa», Marco, 2026-09-11 — his plaza had just become a
        container, which made its children instanced). Hiding works the same
        way: `hide` drops the surroundings instead of washing them.
        """
        if self.scene.edit_group is None:
            return [(groups, 0.0)]
        fuera = [g for g in groups if self._draws_in_edit_context(g)]
        dentro = [g for g in groups if not self._draws_in_edit_context(g)]
        if self._edit_rest_mode == "hide":
            return [(dentro, 0.0)]
        if self._edit_rest_mode != "fade":
            return [(groups, 0.0)]
        return [(fuera, EDIT_REST_FADE), (dentro, 0.0)]

    def _draw_instanced_faces_lean(self, by_proto, mode, extra) -> None:
        """The instanced faces pass of the shaded and textured styles: the
        very draws of the general loop below, in the same order, but each
        piece of GL state set only when it changes — on a plant of 2 000
        prototypes the per-batch uniform/cull/bind churn WAS the frame
        (#158). The calls are recorded; the next frame with the same
        batches (an orbit mostly keeps them) replays the list as is."""
        prog = self._program
        gl = self._gl
        # Hand the frame's work so far to the driver first. Fed thousands
        # of draws back to back, Mesa's Intel driver let an edge pixel
        # beside a face come out either way from one frame to the next
        # (1 pixel in ~7 frames on the plant of #158); the general loop's
        # pace hid it, and a flush here — which does not wait for the GPU —
        # makes every frame the same as that loop's.
        gl.glFlush()
        back_rgb = effective_back_color(
            getattr(self.scene, "display_style", None), self.scene)
        key = (mode, tuple(back_rgb), id(getattr(self, "_tex_cache", None)),
               id(self._program))
        rec = getattr(self, "_lean_faces_rec", None)
        if (rec is not None and rec[0] == key and rec[1] is by_proto
                and all(e.get("mat_batch") is b for e, b in rec[2])):
            rec[3].replay(self._gl_replay())
            return
        tape = _GlTape()
        pairs: list = []
        back_vec = QVector4D(back_rgb[0], back_rgb[1], back_rgb[2], 1.0)
        # What the general loop never relies on is unknown on entry (None:
        # the first use sets it); the cull and textures switches are off
        # between passes, as that loop assumes too.
        state = {"fade": None, "vcol": None, "back": False, "cull": False,
                 "front": None, "tex": 0, "shade": None, "cut": None}

        def need(key_, value, apply):
            if state[key_] != value:
                apply(value)
                state[key_] = value

        def set_vcol(v):
            tape.uniform_i(prog, self._loc_use_vcolor, v)

        def set_cull(on):
            if on:
                tape.gl(gl.glEnable, tape.ENABLE, GL_CULL_FACE)
                tape.gl(gl.glCullFace, tape.CULL, GL_FRONT)
            else:
                tape.gl(gl.glDisable, tape.DISABLE, GL_CULL_FACE)

        def set_shade(v):
            tape.uniform_f(prog, self._loc_shade, float(v))

        def set_tex(v):
            tape.uniform_i(prog, self._loc_use_tex, v)

        def set_cut(v):
            tape.uniform_i(prog, self._loc_hard_cutout, v)

        def set_front(mirrored):
            tape.gl(gl.glFrontFace, tape.FRONT, GL_CW if mirrored else GL_CCW)

        def set_fade(v):
            tape.uniform_f(prog, self._loc_fade, v)

        def set_color(r, g, b):
            # _set_color: the colour, and the back kept in step.
            v = QVector4D(r, g, b, 1.0)
            tape.uniform_4f(prog, self._loc_color, v)
            tape.uniform_4f(prog, self._loc_back_color, v)
        bound = None
        back_tint = not _NO_BACK_TINT
        cacheable = True
        draw = extra.glDrawArraysInstanced
        for mesh, paint, groups, mirrored in by_proto.values():
            entry = self._proto_view(self._ensure_proto_draw(mesh, paint),
                                     mirrored)
            need("front", mirrored, set_front)
            for lote, fade in self._instanced_batches(groups):
                if not lote:
                    continue
                n = self._update_inst_matrices(entry, lote)
                if entry.get("mat_batch") is lote:
                    pairs.append((entry, lote))
                else:
                    cacheable = False          # an edit-context split
                need("fade", fade, set_fade)
                if entry["vcol_count"]:
                    need("cull", False, set_cull)
                    need("vcol", 1, set_vcol)
                    if not state["back"]:
                        tape.uniform_4f(prog, self._loc_back_color, back_vec)
                        state["back"] = True
                    bound = entry["vcol_vao"]
                    tape.bind_vao(bound)
                    tape.draw(draw, GL_TRIANGLES, 0, entry["vcol_count"], n)
                if entry["tex_runs"]:
                    need("cull", False, set_cull)
                    need("vcol", 0, set_vcol)
                    bound = entry["tex_vao"]
                    tape.bind_vao(bound)
                    if mode == "shaded":
                        for (path, shade), s0, cnt in entry["tex_runs"]:
                            r, g, b = self._texture_avg_color(path)
                            need("shade", float(shade), set_shade)
                            set_color(r, g, b)
                            state["back"] = False
                            tape.draw(draw, GL_TRIANGLES, s0, cnt, n)
                    else:
                        need("tex", 1, set_tex)
                        for (path, shade), s0, cnt in entry["tex_runs"]:
                            tex = self._get_texture(path)
                            if tex is None:
                                continue
                            need("shade", float(shade), set_shade)
                            need("cut", 1 if getattr(tex, "_cutout", False)
                                 else 0, set_cut)
                            tape.tex_bind(tex, 0)
                            tape.draw(draw, GL_TRIANGLES, s0, cnt, n)
                            tape.tex_release(tex, 0)
                        need("cut", 0, set_cut)
                        need("tex", 0, set_tex)
                    need("shade", 1.0, set_shade)
                if entry.get("dback_count") and back_tint:
                    need("cull", True, set_cull)
                    need("vcol", 0, set_vcol)
                    bound = entry["dback_vao"]
                    tape.bind_vao(bound)
                    tape.draw(draw, GL_TRIANGLES, 0, entry["dback_count"], n)
        if bound is not None:
            tape.release_vao(bound)
        need("cull", False, set_cull)
        if state["vcol"] is not None:
            need("vcol", 0, set_vcol)
        if state["shade"] is not None:
            need("shade", 1.0, set_shade)
        if state["front"] is not None:
            need("front", False, set_front)
        self._lean_faces_rec = ((key, by_proto, pairs, tape) if cacheable
                                else None)

    def _draw_instanced_faces(self, mode, style) -> None:
        by_proto = self._gather_instanced()
        if not by_proto or mode == "wireframe":
            return
        extra = self.context().extraFunctions()
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        if mode == "xray":
            self._program.setUniformValue1f(self._loc_opacity,
                                            XRAY_FACE_OPACITY)
            self._gl.glDepthMask(GL_FALSE)
        # The prototype's tones were baked for ITS orientation (#482).
        self._program.setUniformValue(self._loc_reshade, 1)
        if mode in ("shaded", "textures") and _lean_instanced():
            self._draw_instanced_faces_lean(by_proto, mode, extra)
            by_proto = {}
        for mesh, paint, groups, mirrored in by_proto.values():
            entry = self._proto_view(self._ensure_proto_draw(mesh, paint),
                                     mirrored)
            self._front_face(mirrored)
            for lote, fade in self._instanced_batches(groups):
                if not lote:
                    continue
                n = self._update_inst_matrices(entry, lote)
                self._program.setUniformValue1f(self._loc_fade, fade)
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
                if (entry.get("dback_count") and not _NO_BACK_TINT
                        and mode in ("textures", "shaded")):
                    # The default back, as the consolidated pass draws it.
                    self._gl.glEnable(GL_CULL_FACE)
                    self._gl.glCullFace(GL_FRONT)
                    self._program.setUniformValue(self._loc_use_vcolor, 0)
                    entry["dback_vao"].bind()
                    extra.glDrawArraysInstanced(
                        GL_TRIANGLES, 0, entry["dback_count"], n)
                    entry["dback_vao"].release()
                    self._gl.glDisable(GL_CULL_FACE)
        self._front_face(False)
        self._program.setUniformValue(self._loc_reshade, 0)
        self._program.setUniformValue1f(self._loc_fade, 0.0)
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
        for mesh, paint, groups, mirrored in by_proto.values():
            entry = self._proto_view(self._ensure_proto_draw(mesh, paint),
                                     mirrored)
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

    def _draw_back_edges(self, color, w: int, h: int) -> None:
        """Back Edges (K, issue #234): the edges a face hides, dashed, over
        the opaque model — where a bar or a frame member continues behind
        a face in a shop drawing. The faces already wrote their depth
        (pushed back by the polygon offset, so an edge lying ON a face is
        not «behind» it): what fails that test is drawn with GL_GREATER and
        a dash measured along each line, without writing depth."""
        dpr = max(1.0, float(self.devicePixelRatioF()))
        self._program.setUniformValue(self._loc_viewport_px,
                                      QVector2D(float(w), float(h)))
        self._program.setUniformValue1f(self._loc_dash_px, 4.0 * dpr)
        self._program.setUniformValue(self._loc_stipple, 4)
        self._gl.glDepthFunc(GL_GREATER)
        self._gl.glDepthMask(GL_FALSE)
        self._set_color(*color, 1.0)
        if self._edges_count > 0:
            self._edges_vao.bind()
            for _vs, _vc in getattr(self, "_frame_edge_spans",
                                    ((0, self._edges_count),)):
                self._gl.glDrawArrays(GL_LINES, _vs, _vc)
            self._edges_vao.release()
        self._draw_instanced_edges()
        self._gl.glDepthFunc(GL_LEQUAL)
        self._gl.glDepthMask(GL_TRUE)
        self._program.setUniformValue(self._loc_stipple, 0)

    def _xray_face_depth(self) -> None:
        """Write every face's depth and no colour — X-ray's translucent
        face pass leaves the depth buffer without them. Same polygon offset
        as the faces, so an edge lying ON a face still counts as in front."""
        self._gl.glColorMask(False, False, False, False)
        self._gl.glEnable(GL_POLYGON_OFFSET_FILL)
        self._gl.glPolygonOffset(1.0, 1.0)
        if self._faces_count > 0:
            self._faces_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._faces_count)
            self._faces_vao.release()
        if self._tex_faces_count > 0:
            self._tex_faces_vao.bind()
            self._gl.glDrawArrays(GL_TRIANGLES, 0, self._tex_faces_count)
            self._tex_faces_vao.release()
        self._draw_instanced_raw()
        self._gl.glDisable(GL_POLYGON_OFFSET_FILL)
        self._gl.glColorMask(True, True, True, True)

    def _draw_instanced_edges_lean(self, by_proto, extra) -> None:
        """:meth:`_draw_instanced_edges`'s draws, the fade set only when it
        changes, recorded and replayed while the batches stay (see
        :meth:`_draw_instanced_faces_lean`)."""
        prog = self._program
        key = id(self._program)
        rec = getattr(self, "_lean_edges_rec", None)
        if (rec is not None and rec[0] == key and rec[1] is by_proto
                and all(e.get("mat_batch") is b for e, b in rec[2])):
            rec[3].replay(self._gl_replay())
            return
        tape = _GlTape()
        pairs: list = []
        cacheable = True
        fade_now = None
        bound = None
        draw = extra.glDrawArraysInstanced
        for mesh, paint, groups, mirrored in by_proto.values():
            entry = self._proto_view(self._ensure_proto_draw(mesh, paint),
                                     mirrored)
            if not entry["edge_count"]:
                continue
            for lote, fade in self._instanced_batches(groups):
                if not lote:
                    continue
                n = self._update_inst_matrices(entry, lote)
                if entry.get("mat_batch") is lote:
                    pairs.append((entry, lote))
                else:
                    cacheable = False
                if fade != fade_now:
                    tape.uniform_f(prog, self._loc_fade, fade)
                    fade_now = fade
                bound = entry["edges_vao"]
                tape.bind_vao(bound)
                tape.draw(draw, GL_LINES, 0, entry["edge_count"], n)
        if bound is not None:
            tape.release_vao(bound)
        tape.uniform_f(prog, self._loc_fade, 0.0)
        self._lean_edges_rec = ((key, by_proto, pairs, tape) if cacheable
                                else None)

    def _gl_replay(self):
        """core._native's GlReplay for this viewport's GL context (the
        experimental engine), or ``None``: tapes then replay through the
        PySide wrappers."""
        if not _LEAN_NATIVE_REPLAY:
            return None
        ctx = self.context()
        memo = getattr(self, "_gl_replay_memo", None)
        if memo is not None and memo[0] is ctx:
            return memo[1]
        replay = None
        from core import _native
        mod = _native.native
        if mod is not None and hasattr(mod, "GlReplay") and ctx is not None:
            try:
                replay = mod.GlReplay([int(ctx.getProcAddress(n) or 0)
                                       for n in _TAPE_FUNCS])
            except Exception:  # noqa: BLE001 — a missing entry: Python
                replay = None
        self._gl_replay_memo = (ctx, replay)
        return replay

    def _draw_instanced_edges(self) -> None:
        by_proto = getattr(self, "_frame_instanced", None)
        if not by_proto:
            return
        extra = self.context().extraFunctions()
        if _lean_instanced():
            self._draw_instanced_edges_lean(by_proto, extra)
            return
        for mesh, paint, groups, mirrored in by_proto.values():
            entry = self._proto_view(self._ensure_proto_draw(mesh, paint),
                                     mirrored)
            if not entry["edge_count"]:
                continue
            for lote, fade in self._instanced_batches(groups):
                if not lote:
                    continue
                n = self._update_inst_matrices(entry, lote)
                self._program.setUniformValue1f(self._loc_fade, fade)
                entry["edges_vao"].bind()
                extra.glDrawArraysInstanced(GL_LINES, 0,
                                            entry["edge_count"], n)
                entry["edges_vao"].release()
        self._program.setUniformValue1f(self._loc_fade, 0.0)
