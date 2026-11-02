# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Paste tool: drop a copied set of geometry, placing it with the cursor.

After Copy/Cut fills ``viewport.clipboard``, Paste activates this tool: the copied
faces, edges and groups follow the cursor as a live preview (snapping like any
draw), and a click stamps them into the scene ONCE and returns to Select.
The clipboard is kept — paste again for another copy.
"""
from __future__ import annotations


from PySide6.QtGui import QVector3D

from core.geometry import Face as PreviewFace
from core.group import copy_group, translated_attrs
from core.texture import face_uv_axes


def _preview_attrs(attrs, off, face):
    """Attrs for a preview face at the cursor offset. A POSITIONED texture's
    world-anchored uvw map is shifted to follow the drag. A PLANAR texture
    (no uvw — hand-painted faces, billboard figures) would be re-projected
    at every cursor position and the image SWIMS through the model; the
    renderer's planar projection is baked into a uvw here (same axes, rot,
    sw/sh) so the image rides with the drag looking exactly as it did at
    the original spot."""
    if not attrs:
        return None
    t = attrs.get("texture")
    if t and t.get("path") and not t.get("uvw"):
        gu, cu, gv, cv = face_uv_axes(t, face.normal())   # the renderer's map
        uvw = [gu.x(), gu.y(), gu.z(), cu, gv.x(), gv.y(), gv.z(), cv]
        attrs = {**attrs, "texture": {**t, "uvw": uvw}}
    return translated_attrs(attrs, off)
from core.history import (AddEdgeCommand, AddFaceCommand, Command,
                          CompoundCommand, InsertGroupCommand)
from tools.base import Tool, ToolContext


class _PruneOnUndo(Command):
    """First in a stamp's compound, so its UNDO runs last: after the stamp's
    faces and edges are gone, the vertices nothing uses any more go too.
    ``remove_edge`` only detaches, and the leftovers kept the edit box of a
    group (which wraps its vertices) at the pasted size after Ctrl+Z. Redo
    puts them back before the geometry is relinked onto them."""

    keeps_groups = True        # only vertices nothing uses

    def __init__(self) -> None:
        self._gone: list = []

    def do(self, scene) -> None:
        from core.mesh import _key
        m = scene.mesh
        for v in self._gone:
            m.vertices.append(v)
            m._registry.setdefault(_key(v.position), v)
        if self._gone:
            m._chunk_dirty = True
            m._mut_serial += 1     # box / chunk caches key on it
        self._gone = []

    def undo(self, scene) -> None:
        m = scene.mesh
        before = {id(v): v for v in m.vertices}
        m.prune_orphan_vertices()
        kept = {id(v) for v in m.vertices}
        self._gone = [v for k, v in before.items() if k not in kept]
        scene.version += 1


class PasteTool(Tool):
    name = "Paste"
    uses_snap = True  # place exactly on a vertex / edge / face
    wireframe_color = (0.13, 0.17, 0.23, 1.0)
    wireframe_depth_tested = True

    def __init__(self) -> None:
        self._clip = None
        self._offset = QVector3D(0.0, 0.0, 0.0)
        self._preview_on = False

    @property
    def start_point(self):
        """The clipboard's reference point, as the viewport's "start": the
        cursor then lands on the plane THROUGH that point (level with the
        cut slat, or vertical near the horizon) instead of on the ground or
        on whatever face happens to lie under it — which is what pinned a
        cut slat to the bench and dropped it to the floor everywhere else
        (Marco, 2026-09-14: «quiero colocarlo a un metro pero no me deja»).
        The axis inferences from that point come along for free."""
        return self._clip["ref"] if self._clip else None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._clip = getattr(viewport, "clipboard", None)
        self._offset = QVector3D(0.0, 0.0, 0.0)
        self._preview_on = False
        groups = (self._clip or {}).get("groups") or ()
        begin = getattr(viewport, "begin_groups_preview", None)
        if groups and callable(begin):
            # Copied groups preview through the frozen-scratch pipeline
            # (chunk arrays upload ONCE; each hover frame is one translated
            # MVP): the FULL model — colours, textures, every face — follows
            # the cursor at zero per-frame cost. The old path rebuilt a
            # Python wireframe of every group edge per paint; a 17k-face
            # plant froze the app for seconds per frame (piscina report).
            begin(groups, external=True)
            self._preview_on = True

    def _end_preview(self, viewport) -> None:
        if self._preview_on:
            end = getattr(viewport, "end_groups_preview", None)
            if callable(end):
                end()
            self._preview_on = False

    def on_deactivate(self, viewport) -> None:
        self._end_preview(viewport)
        self._clip = None

    # ---- Spatial input ------------------------------------------------------
    def on_hover(self, ctx: ToolContext) -> None:
        if self._clip is None:
            return
        self._offset = ctx.world - self._clip["ref"]
        if self._preview_on:
            ctx.viewport.set_groups_preview_offset(self._offset)
        else:
            ctx.viewport.update()

    def on_click(self, ctx: ToolContext) -> None:
        if self._clip is None:
            return
        if not self.stamp(ctx.viewport, ctx.world - self._clip["ref"]):
            return
        # One stamp per paste: hand back to Select. The clipboard
        # survives, so Ctrl+V stamps another copy.
        window = getattr(ctx.viewport, "window", None)
        window = window() if callable(window) else None
        if window is not None and hasattr(window, "_activate_tool"):
            window._activate_tool("select")
        ctx.viewport.update()

    @classmethod
    def in_place(cls, viewport) -> bool:
        """Paste in Place: stamp the clipboard at the exact
        coordinates it was copied from, no cursor placement. The tools work
        in world coordinates inside an open group too, so copying in one
        context and pasting in place in another moves geometry into or out
        of groups without shifting it. Everything pasted ends up selected."""
        clip = getattr(viewport, "clipboard", None)
        if not clip:
            return False
        tool = cls()
        tool._clip = clip
        ok = tool.stamp(viewport, QVector3D(0.0, 0.0, 0.0), select_all=True)
        viewport.update()
        return ok

    def stamp(self, viewport, off, select_all: bool = False) -> bool:
        """Stamp the clipboard displaced by ``off`` as ONE undoable step;
        False when there was nothing to stamp. ``select_all`` leaves the
        loose faces and edges selected too (groups always are)."""
        commands: list = [_PruneOnUndo()]
        # A face's boundary edges are created BY the face; undoing the face
        # alone leaves them behind as loose edges (inside a group they read
        # as debris). Adding them first, as commands of their own, makes the
        # stamp own them: undo removes the faces, then exactly the edges it
        # created — an edge that already existed is never touched.
        for loop, holes, *_r in self._clip["faces"]:
            for lp in (loop, *holes):
                n = len(lp)
                for i in range(n):
                    commands.append(AddEdgeCommand(
                        lp[i] + off, lp[(i + 1) % n] + off))
        for loop, holes, *rest in self._clip["faces"]:
            # Copied attrs travel onto the pasted face; a positioned texture's
            # world-anchored UV map is re-fitted to the paste offset.
            attrs = translated_attrs(rest[0], off) if rest and rest[0] else None
            commands.append(AddFaceCommand(
                [p + off for p in loop],
                holes=[[p + off for p in h] for h in holes] or None,
                auto=False,
                attrs=attrs,
            ))
        # A face pasted onto a plane that already carries faces merges with
        # them, as a rectangle drawn there does: overlapping ones split into
        # their regions instead of lying one on top of the other (issue #73,
        # @pacaeiro: «if you copy a rectangle on top of the previous one,
        # the engine is not activated»).
        commands.extend(_plane_merges(viewport.scene, [
            [p + off for p in loop] for loop, _holes, *_r in self._clip["faces"]]))
        # Soft/curve flags travel with the copy; curve ids are remapped to
        # FRESH ones so each pasted circle/arc is its own selectable contour
        # (never entangled with the original's).
        from core.mesh import Mesh
        id_map: dict[int, int] = {}
        for a, b, soft, curve in self._clip["edges"]:
            if curve is not None and curve not in id_map:
                id_map[curve] = Mesh.next_curve_id()
            commands.append(AddEdgeCommand(
                a + off, b + off, soft=soft or None,
                curve=id_map.get(curve)))
        # Each stamp builds FRESH group copies from the clipboard templates
        # (instances stay siblings of the same prototype).
        pasted_groups = [copy_group(g, off)
                         for g in self._clip.get("groups", ())]
        commands.extend(InsertGroupCommand(g) for g in pasted_groups)
        if len(commands) == 1:
            return False        # only the prune guard: nothing to stamp
        # The scratch preview ends BEFORE the stamp: the pasted groups enter
        # the consolidated VBOs on the version bump like any other insert.
        self._end_preview(viewport)
        viewport.history.execute(CompoundCommand(commands))
        picked = list(pasted_groups)
        if select_all:
            live = set(map(id, viewport.scene.mesh.faces))
            picked += [c.face for c in commands
                       if isinstance(c, AddFaceCommand)
                       and c.face is not None and id(c.face) in live]
            # The copied edges themselves (looked up by position: a copy
            # pasted in place welds onto the original's edges, so the
            # command may own none of them).
            mesh = viewport.scene.mesh
            for a, b, _s, _c in self._clip["edges"]:
                v0, v1 = mesh.vertex_at(a + off), mesh.vertex_at(b + off)
                e = mesh.find_edge(v0, v1) if v0 and v1 else None
                if e is not None:
                    picked.append(e)
        if picked:
            # InsertGroupCommand selects only the last one — select them all.
            viewport.scene.select(picked)
        return True

    def on_cancel(self, viewport) -> None:
        self._end_preview(viewport)
        self._clip = None
        viewport.update()

    # ---- Visual preview -----------------------------------------------------
    # Copied GROUPS preview via the viewport's frozen-scratch VBOs (set up in
    # ``on_activate``); only the LOOSE faces/edges of the clipboard go through
    # the per-frame paths below — those sets are small.
    def rubber_band_lines(self):
        if self._clip is None:
            return []
        off = self._offset
        segments = []
        for loop, holes, *_ in self._clip["faces"]:
            for lp in (loop, *holes):
                n = len(lp)
                for i in range(n):
                    segments.append((lp[i] + off, lp[(i + 1) % n] + off))
        for a, b, _, _ in self._clip["edges"]:
            segments.append((a + off, b + off))
        return segments

    def preview_faces(self):
        if self._clip is None:
            return []
        off = self._offset
        faces = []
        entries = [(loop, holes, rest[0] if rest else None)
                   for loop, holes, *rest in self._clip["faces"]]
        for loop, holes, attrs in entries:
            face = PreviewFace([p + off for p in loop],
                               [[p + off for p in h] for h in holes])
            face.attrs = _preview_attrs(attrs, off, face)
            faces.append(face)
        return faces


#: More distinct planes than this in one paste is 3D geometry being moved
#: about, not a flat drawing laid over another: no merge is attempted.
_MERGE_PLANES_CAP = 24


def _plane_merges(scene, loops) -> list:
    """Scoped plane rebuilds for the planes of the pasted ``loops`` that
    already carry faces of the target mesh (the drawing tools' own
    ``RebuildPlaneFacesCommand``). Runs after the faces are added, so the
    pasted faces cover their own regions."""
    from core.history import RebuildPlaneFacesCommand
    from core.triangulate import _newell
    planes: dict = {}
    for loop in loops:
        if len(loop) < 3:
            continue
        n = _newell(loop)
        length = n.length() if n is not None else 0.0
        if length < 1e-9:
            continue
        n = n / length
        if n.z() < 0 or (n.z() == 0 and (n.y() < 0 or (n.y() == 0 and n.x() < 0))):
            n = -n
        d = QVector3D.dotProduct(n, loop[0])
        key = (round(n.x(), 4), round(n.y(), 4), round(n.z(), 4), round(d, 4))
        entry = planes.setdefault(key, [QVector3D(loop[0]), n, None, None])
        for p in loop:
            xyz = (p.x(), p.y(), p.z())
            entry[2] = xyz if entry[2] is None else tuple(map(min, entry[2], xyz))
            entry[3] = xyz if entry[3] is None else tuple(map(max, entry[3], xyz))
        if len(planes) > _MERGE_PLANES_CAP:
            return []
    if not planes or not scene.mesh.faces:
        return []
    # Which planes already hold geometry: one vectorised pass over the
    # mesh's vertices (a paste beside a big model must stay instant); only
    # then the faces, and only those on that plane whose box meets the
    # pasted one — a face pasted BESIDE another leaves it alone.
    import numpy as np
    pts = np.array([[v.position.x(), v.position.y(), v.position.z()]
                    for v in scene.mesh.vertices], dtype=np.float64)
    out = []
    tol = 1e-4
    for origin, n, lo, hi in planes.values():
        nv = np.array([n.x(), n.y(), n.z()])
        d = float(np.dot(nv, [origin.x(), origin.y(), origin.z()]))
        if np.count_nonzero(np.abs(pts @ nv - d) < tol) < 3:
            continue
        for f in scene.mesh.faces:
            vs = f.vertices
            if any(abs(QVector3D.dotProduct(v - origin, n)) > tol for v in vs):
                continue
            flo = [min(v.x() for v in vs), min(v.y() for v in vs), min(v.z() for v in vs)]
            fhi = [max(v.x() for v in vs), max(v.y() for v in vs), max(v.z() for v in vs)]
            if all(flo[i] < hi[i] - tol and lo[i] < fhi[i] - tol
                   or abs(fhi[i] - flo[i]) < tol and abs(hi[i] - lo[i]) < tol
                   for i in range(3)):
                out.append(RebuildPlaneFacesCommand(origin, n))
                break
    return out
