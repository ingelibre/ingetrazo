# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Select tool: pick edges and faces and delete them.

Behavior:
- Left click on / near an edge: select that edge. Click on a face interior
  (when no edge is closer): select the face. Edges win ties because they sit
  on top of faces, matching SketchUp.
- Shift-click adds to the current selection; plain click replaces it.
- Left click on empty space: clear the selection.
- Hover highlights whatever the click would pick, so the user sees the target
  before committing.
- Delete / Backspace: remove the selected edges and faces from the scene.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from core.dimension import Dimension
from core.textlabel import TextLabel
from core.group import Group
from core.mesh import Edge, Face
from core.guide import Guide
from core.section import SectionPlane
from core.history import (
    CompoundCommand,
    DeleteDimensionsCommand,
    DeleteGeoPathsCommand,
    DeleteGroupCommand,
    DeleteGuidesCommand,
    DeleteSectionPlanesCommand,
    DeleteTextLabelsCommand,
    SetActiveSectionCommand,
    EditTextLabelCommand,
    EraseSelectionCommand,
)
from georef.geopath import GeoPath
from tools.base import Tool, ToolContext



def _seg_rect_mask(ax, ay, bx, by, ok, rect, crossing):
    """Vectorized rect test for N screen segments: window mode = both
    endpoints inside; crossing mode = an endpoint inside or the segment
    intersecting one of the four borders. NumPy twin of _pt_in_rect /
    _seg_rect_overlap for import-scale meshes."""
    import numpy as np
    x0, y0, x1, y1 = rect
    in_a = ok & (ax >= x0) & (ax <= x1) & (ay >= y0) & (ay <= y1)
    in_b = ok & (bx >= x0) & (bx <= x1) & (by >= y0) & (by <= y1)
    if not crossing:
        return in_a & in_b
    cross = in_a | in_b
    todo = ok & ~cross
    if todo.any():
        for px, py, qx, qy in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                               (x1, y1, x0, y1), (x0, y1, x0, y0)):
            d1 = (qx - px) * (ay - py) - (qy - py) * (ax - px)
            d2 = (qx - px) * (by - py) - (qy - py) * (bx - px)
            d3 = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
            d4 = (bx - ax) * (qy - ay) - (by - ay) * (qx - ax)
            hit = todo & (d1 * d2 < 0) & (d3 * d4 < 0)
            cross |= hit
            todo &= ~hit
            if not todo.any():
                break
    return cross


def _box_loose_fast(viewport, rect, crossing):
    """Vectorized box select over the loose mesh: edges via the cached
    screen projection, faces derived from their boundary edges. Returns
    (edges, faces) or None to fall back to the per-entity walk (stub
    viewports in tests, or a viewport without the caches)."""
    if (getattr(viewport, "_ledge_screen", None) is None
            or getattr(viewport, "_pick_index", None) is None):
        return None
    try:
        proj = viewport._ledge_screen()
        idx = viewport._pick_index()
    except Exception:  # noqa: BLE001 — any stub oddity: python path
        return None
    if proj is None or idx.edge_a is None:
        return None
    import numpy as np
    ax, ay, bx, by, ok = proj
    edges_all = idx.edges
    if len(edges_all) != len(ax):
        return None
    mask = _seg_rect_mask(ax, ay, bx, by, ok, rect, crossing)
    sel = viewport.scene.entity_selectable
    hit_idx = np.where(mask)[0]
    edges = [edges_all[int(i)] for i in hit_idx
             if sel(edges_all[int(i)])
             and not getattr(edges_all[int(i)], "hidden", False)]
    faces = []
    if crossing:
        seen = set()
        for i in hit_idx:
            for f in edges_all[int(i)].faces:
                if id(f) not in seen:
                    seen.add(id(f))
                    if sel(f):
                        faces.append(f)
    else:
        hit_ids = {id(edges_all[int(i)]) for i in hit_idx}
        face_edges: dict = {}
        for e in edges_all:
            for f in e.faces:
                face_edges.setdefault(id(f), []).append(e)
        for f in viewport.scene.faces:
            es = face_edges.get(id(f))
            if es and all(id(e) in hit_ids for e in es) and sel(f):
                faces.append(f)
    return edges, faces


def _box_group_fast(viewport, group, rect, crossing):
    """Vectorized box test for one (non-billboard) group via its chunk
    arrays. True/False, or None to fall back to the per-vertex walk."""
    if (getattr(group, "billboard", False)
            or getattr(viewport, "_group_chunk", None) is None
            or getattr(viewport, "_project_px", None) is None):
        return None
    import numpy as np
    try:
        ch = viewport._group_chunk(group)
        pairs = np.frombuffer(ch["edges"], np.float32).reshape(-1, 3)
        v0, e1, e2 = ch["v0"], ch["e1"], ch["e2"]
    except Exception:  # noqa: BLE001
        return None
    corners = [] if v0 is None else [v0, v0 + e1, v0 + e2]
    if len(pairs):
        corners.append(pairs.astype(np.float64))
    if not corners:
        return None
    pts = np.concatenate(corners, axis=0)
    xs, ys, ok = viewport._project_px(pts)
    x0, y0, x1, y1 = rect
    inside = ok & (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
    if crossing:
        if inside.any():
            return True
        if len(pairs):
            exs, eys, eok = xs[-len(pairs):], ys[-len(pairs):], ok[-len(pairs):]
            m = _seg_rect_mask(exs[0::2], eys[0::2], exs[1::2], eys[1::2],
                               eok[0::2] & eok[1::2], rect, True)
            return bool(m.any())
        return False
    return bool(ok.all() and inside.all())


def _pt_in_rect(p, rect) -> bool:
    return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def _seg_seg_2d(p1, p2, p3, p4) -> bool:
    """Whether 2D segments ``p1-p2`` and ``p3-p4`` properly cross."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def _seg_rect_overlap(a, b, rect) -> bool:
    """Whether segment ``a-b`` touches the rectangle (endpoint inside or an
    edge crossing) — the crossing-selection test."""
    if _pt_in_rect(a, rect) or _pt_in_rect(b, rect):
        return True
    x0, y0, x1, y1 = rect
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return any(_seg_seg_2d(a, b, corners[i], corners[(i + 1) % 4]) for i in range(4))


class SelectTool(Tool):
    name = "Select"
    shortcut = ""  # Space, bound in main_window; "S" is Scale
    uses_snap = False  # selecting picks geometry; no snap markers
    box_select = True   # supports the rubber-band window / crossing box

    def on_activate(self, viewport) -> None:
        pass

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)

    def _pick(self, viewport, screen_x: float, screen_y: float):
        """A group (picked as a unit) takes priority; then the edge under the
        cursor (screen-space priority), then a dimension annotation, then the
        front face."""
        pick_label = getattr(viewport, "pick_text_label", None)
        if pick_label is not None:
            # The text block overdraws all geometry, so a click on the glyphs
            # is unambiguous — it outranks every 3D pick. The label's thin
            # leader line keeps its normal (post-edge) priority below.
            label = pick_label(screen_x, screen_y, rect_only=True)
            if label is not None:
                return label
        group = viewport.pick_group(screen_x, screen_y)
        if group is not None:
            return group
        edge = viewport.pick_edge(screen_x, screen_y)
        if edge is not None:
            return edge
        dim = viewport.pick_dimension(screen_x, screen_y)
        if dim is not None:
            return dim
        pick_label = getattr(viewport, "pick_text_label", None)
        label = pick_label(screen_x, screen_y) if pick_label else None
        if label is not None:
            return label
        path = viewport.pick_geopath(screen_x, screen_y)
        if path is not None:
            return path
        # Section planes pick by their frame (SketchUp), above guides.
        pick_sec = getattr(viewport, "pick_section_plane", None)
        sec = pick_sec(screen_x, screen_y) if pick_sec else None
        if sec is not None:
            return sec
        # Guides select like in SketchUp (click + Delete / right-click). Real
        # geometry outranks them; a guide crossing a face still beats the face
        # (a thin line is the more deliberate target).
        pick_guide = getattr(viewport, "pick_guide", None)
        guide = pick_guide(screen_x, screen_y) if pick_guide else None
        if guide is not None:
            return guide
        return viewport.pick_face(screen_x, screen_y)

    def on_click(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        additive = bool(ctx.modifiers & Qt.ShiftModifier)
        if entity is None:
            if viewport.scene.edit_group is not None and not additive \
                    and not viewport.scene.selection:
                viewport.end_group_edit()       # click outside leaves the group
                return
            if not additive:
                viewport.scene.clear_selection()
        else:
            picked = self._expand(viewport, entity)
            viewport.scene.select(picked, additive=additive)
        viewport.update()

    @staticmethod
    def _expand(viewport, entity):
        """Grow a pick to its natural whole: a curved surface (faces joined by
        soft edges) for a face, or the whole drawn curve (circle/arc) for one of
        its segments — SketchUp-style. Plain entities select alone."""
        if isinstance(entity, Face):
            return viewport.scene.mesh.surface_of(entity)
        if isinstance(entity, Edge) and getattr(entity, "curve", None) is not None:
            return viewport.scene.mesh.curve_edges(entity)
        return [entity]

    def on_double_click(self, ctx: ToolContext) -> None:
        """SketchUp double click: a face selects itself plus its bounding
        edges; an edge selects itself plus its faces — and a GROUP opens for
        editing (Groups v2: draw, push, erase inside it)."""
        viewport = ctx.viewport
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        if isinstance(entity, Group):
            viewport.begin_group_edit(entity)
            return
        if isinstance(entity, SectionPlane):
            # SketchUp: double-clicking a section plane toggles the active cut.
            viewport.history.execute(SetActiveSectionCommand(
                None if entity.active else entity))
            viewport.scene.select([entity])
            viewport.update()
            return
        if isinstance(entity, TextLabel):
            # SketchUp-style: double-clicking a leader text edits its text.
            from PySide6.QtWidgets import QInputDialog
            from core.i18n import tr
            text, ok = QInputDialog.getMultiLineText(
                viewport.window(), tr("Text"), tr("Label text:"),
                entity.text)
            if ok and text.strip() and text.strip() != entity.text:
                viewport.history.execute(
                    EditTextLabelCommand(entity, text.strip()))
            viewport.update()
            return
        if not isinstance(entity, (Face, Edge)):
            self.on_click(ctx)
            return
        mesh = viewport.scene.mesh
        picked = list(self._expand(viewport, entity))
        if isinstance(entity, Face):
            for f in list(picked):
                if not isinstance(f, Face):
                    continue
                for lp in (f.loop, *f.hole_loops):
                    n = len(lp)
                    for i in range(n):
                        e = mesh.find_edge(lp[i], lp[(i + 1) % n])
                        if e is not None:
                            picked.append(e)
        else:
            for e in list(picked):
                if isinstance(e, Edge):
                    picked.extend(e.faces)
        additive = bool(ctx.modifiers & Qt.ShiftModifier)
        viewport.scene.select(picked, additive=additive)
        viewport.update()

    def on_triple_click(self, ctx: ToolContext) -> None:
        """SketchUp triple click: everything physically connected to the
        picked entity (the whole solid), walked through shared vertices."""
        viewport = ctx.viewport
        entity = self._pick(viewport, ctx.screen.x(), ctx.screen.y())
        if not isinstance(entity, (Face, Edge)):
            self.on_click(ctx)
            return
        if isinstance(entity, Face):
            seeds = list(entity.loop) + [v for h in entity.hole_loops
                                         for v in h]
        else:
            seeds = [entity.v0, entity.v1]
        seen_v = set(seeds)
        edges: set = set()
        faces: set = set()
        stack = list(seeds)
        while stack:
            v = stack.pop()
            for e in v.edges:
                if e in edges:
                    continue
                edges.add(e)
                for f in e.faces:
                    if f in faces:
                        continue
                    faces.add(f)
                    for lp in (f.loop, *f.hole_loops):
                        for w in lp:
                            if w not in seen_v:
                                seen_v.add(w)
                                stack.append(w)
                w = e.other(v)
                if w not in seen_v:
                    seen_v.add(w)
                    stack.append(w)
        additive = bool(ctx.modifiers & Qt.ShiftModifier)
        viewport.scene.select(list(edges) + list(faces), additive=additive)
        viewport.update()

    def on_hover(self, ctx: ToolContext) -> None:
        viewport = ctx.viewport
        viewport.set_hover(self._pick(viewport, ctx.screen.x(), ctx.screen.y()))

    def on_box_select(self, viewport, rect, crossing: bool, additive: bool) -> None:
        w2p = viewport._world_to_pixel
        picked = []
        fast = _box_loose_fast(viewport, rect, crossing)
        if fast is not None:
            picked.extend(fast[0])
            picked.extend(fast[1])
        loose_iter = ((), ()) if fast is not None else (
            viewport.scene.edges, viewport.scene.faces)
        for edge in loose_iter[0]:
            if not viewport.scene.entity_selectable(edge):
                continue                        # hidden or locked layer
            pa = w2p(edge.a)
            pb = w2p(edge.b)
            if pa is None or pb is None:
                continue
            if crossing:
                if _seg_rect_overlap(pa, pb, rect):
                    picked.append(edge)
            elif _pt_in_rect(pa, rect) and _pt_in_rect(pb, rect):
                picked.append(edge)
        for face in loose_iter[1]:
            if not viewport.scene.entity_selectable(face):
                continue                        # hidden or locked layer
            pts = [w2p(v) for v in face.vertices]
            if any(p is None for p in pts):
                continue
            if crossing:
                n = len(pts)
                touches = any(_pt_in_rect(p, rect) for p in pts) or any(
                    _seg_rect_overlap(pts[i], pts[(i + 1) % n], rect) for i in range(n)
                )
                if touches:
                    picked.append(face)
            elif all(_pt_in_rect(p, rect) for p in pts):
                picked.append(face)
        # Groups and component instances (the "box select skips groups"
        # report). Window mode: every vertex inside. Crossing mode: any vertex
        # inside, else any wireframe edge touching the box. Early exits keep
        # the common reject cheap; inside a group-edit context the box works
        # on the open group's internals only (SketchUp), so skip.
        if viewport.scene.edit_group is None:
            for group in getattr(viewport.scene, "groups", []):
                if not viewport.scene.entity_selectable(group):
                    continue
                verdict = _box_group_fast(viewport, group, rect, crossing)
                if verdict is not None:
                    if verdict:
                        picked.append(group)
                    continue
                xf = getattr(group, "xform", None)

                def gw2p(p):
                    return w2p(xf.map(p) if xf is not None else p)

                verts = group.mesh.vertices
                if not verts:
                    continue
                if crossing:
                    hit = False
                    for v in verts:
                        p = gw2p(v.position)
                        if p is not None and _pt_in_rect(p, rect):
                            hit = True
                            break
                    if not hit:
                        for e in group.mesh.edges:
                            pa, pb = gw2p(e.a), gw2p(e.b)
                            if (pa is not None and pb is not None
                                    and _seg_rect_overlap(pa, pb, rect)):
                                hit = True
                                break
                    if hit:
                        picked.append(group)
                else:
                    inside = True
                    for v in verts:
                        p = gw2p(v.position)
                        if p is None or not _pt_in_rect(p, rect):
                            inside = False
                            break
                    if inside:
                        picked.append(group)
        # Guides: an infinite line can never be fully enclosed, so a window
        # box skips it and only a crossing box takes it (SketchUp). Guide
        # points behave like any point. The line is clipped to the part in
        # front of the camera before projecting (as render/snap do).
        for g in getattr(viewport.scene, "guides", []):
            if not viewport.scene.entity_selectable(g):
                continue
            if g.is_line:
                if not crossing:
                    continue
                clip = getattr(viewport, "_clip_segment_front", None)
                seg = clip(*g.segment()) if clip else g.segment()
                if seg is None:
                    continue
                pa, pb = w2p(seg[0]), w2p(seg[1])
                if (pa is not None and pb is not None
                        and _seg_rect_overlap(pa, pb, rect)):
                    picked.append(g)
            else:
                p = w2p(g.point)
                if p is not None and _pt_in_rect(p, rect):
                    picked.append(g)
        for dim in getattr(viewport.scene, "dimensions", []):
            ap, bp = dim.line_points()
            pa, pb = w2p(ap), w2p(bp)
            if pa is None or pb is None:
                continue
            if crossing:
                if _seg_rect_overlap(pa, pb, rect):
                    picked.append(dim)
            elif _pt_in_rect(pa, rect) and _pt_in_rect(pb, rect):
                picked.append(dim)
        for lab in getattr(viewport.scene, "text_labels", []):
            pa, pp = w2p(lab.anchor), w2p(lab.position())
            if pp is None:
                continue
            if crossing:
                if _pt_in_rect(pp, rect) or (
                        pa is not None and _seg_rect_overlap(pa, pp, rect)):
                    picked.append(lab)
            elif _pt_in_rect(pp, rect) and (
                    pa is None or _pt_in_rect(pa, rect)):
                picked.append(lab)
        viewport.scene.select(picked, additive=additive)
        viewport.update()

    def on_key(self, viewport, key: int, modifiers: Qt.KeyboardModifiers) -> bool:
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            selection = viewport.scene.selection
            if selection:
                edges = [e for e in selection if isinstance(e, Edge)]
                faces = [f for f in selection if isinstance(f, Face)]
                groups = [g for g in selection if isinstance(g, Group)]
                dims = [d for d in selection if isinstance(d, Dimension)]
                labels = [t for t in selection if isinstance(t, TextLabel)]
                paths = [p for p in selection if isinstance(p, GeoPath)]
                guides = [g for g in selection if isinstance(g, Guide)]
                splanes = [p for p in selection
                           if isinstance(p, SectionPlane)]
                commands = []
                if edges or faces:
                    # Erasing an edge between two coplanar faces merges them back
                    # into one (SketchUp); any other erased edge takes its faces.
                    commands.append(EraseSelectionCommand(edges, faces))
                commands.extend(DeleteGroupCommand(g) for g in groups)
                if guides:
                    commands.append(DeleteGuidesCommand(guides))
                if splanes:
                    commands.append(DeleteSectionPlanesCommand(splanes))
                if dims:
                    commands.append(DeleteDimensionsCommand(dims))
                if labels:
                    commands.append(DeleteTextLabelsCommand(labels))
                if paths:
                    commands.append(DeleteGeoPathsCommand(paths))
                if commands:
                    cmd = (commands[0] if len(commands) == 1
                           else CompoundCommand(commands))
                    viewport.history.execute(cmd)
                    viewport.update()
            return True
        return False
