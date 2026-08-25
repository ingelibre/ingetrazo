# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Paste tool: drop a copied set of geometry, placing it with the cursor.

After Copy/Cut fills ``viewport.clipboard``, Paste activates this tool: the copied
faces, edges and groups follow the cursor as a live preview (snapping like any
draw), and a click stamps them into the scene ONCE and returns to Select
(SketchUp). The clipboard is kept — paste again for another copy.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QVector3D

from core.geometry import Face as PreviewFace
from core.group import copy_group, translated_attrs
from core.triangulate import plane_axes


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
        u, v = plane_axes(face.normal())
        rot = float(t.get("rot", 0.0))
        if rot:
            a = math.radians(rot)
            ca, sa = math.cos(a), math.sin(a)
            u, v = (u * ca + v * sa, v * ca - u * sa)
        sw = t.get("sw", 1.0) or 1.0
        sh = t.get("sh", 1.0) or 1.0
        uvw = [u.x() / sw, u.y() / sw, u.z() / sw, 0.0,
               v.x() / sh, v.y() / sh, v.z() / sh, 0.0]
        attrs = {**attrs, "texture": {**t, "uvw": uvw}}
    return translated_attrs(attrs, off)
from core.history import (AddEdgeCommand, AddFaceCommand, CompoundCommand,
                          InsertGroupCommand)
from tools.base import Tool, ToolContext


class PasteTool(Tool):
    name = "Paste"
    uses_snap = True  # place exactly on a vertex / edge / face
    wireframe_color = (0.13, 0.17, 0.23, 1.0)
    wireframe_depth_tested = True

    def __init__(self) -> None:
        self._clip = None
        self._offset = QVector3D(0.0, 0.0, 0.0)
        self._preview_on = False

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
        off = ctx.world - self._clip["ref"]
        commands: list = []
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
        if not commands:
            return
        # The scratch preview ends BEFORE the stamp: the pasted groups enter
        # the consolidated VBOs on the version bump like any other insert.
        self._end_preview(ctx.viewport)
        cmd = commands[0] if len(commands) == 1 else CompoundCommand(commands)
        ctx.viewport.history.execute(cmd)
        if pasted_groups:
            # InsertGroupCommand selects only the last one — select them all.
            ctx.viewport.scene.select(pasted_groups)
        # One stamp per paste (SketchUp): hand back to Select. The clipboard
        # survives, so Ctrl+V stamps another copy.
        window = getattr(ctx.viewport, "window", None)
        window = window() if callable(window) else None
        if window is not None and hasattr(window, "_activate_tool"):
            window._activate_tool("select")
        ctx.viewport.update()

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
