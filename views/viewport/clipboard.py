# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Copy, cut and the prototype chunks a clip carries."""
from __future__ import annotations

import copy
from PySide6.QtGui import QMatrix4x4, QVector3D
from core.group import Group, copy_group
from core.mesh import Edge, Face
from core.history import EraseSelectionCommand


class ClipboardMixin:
    """Copy, cut and the prototype chunks a clip carries."""

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
        # hedge took seconds per stamp). Component semantics hold: pasted
        # copies share the definition until edited — begin_group_edit
        # already materializes instances on entry. The prototype's chunk is
        # pre-seeded from the SOURCE group's cached entry (content-identical
        # deep copy), so preview and stamps skip the from-scratch rebuild.
        old_clip = getattr(self, "clipboard", None)
        seed = getattr(self, "_seed_proto_chunk", None)
        for src, tpl in zip(groups, group_data):
            if tpl.xform is None:
                tpl.xform = QMatrix4x4()
                # Still a GROUP: the matrix is only how the stamps share
                # until one is edited (issue #90).
                tpl.component = False
                if callable(seed):
                    seed(tpl.mesh, src)
        # Reference corner (what the cursor holds the set by): min corner of
        # everything copied, via NumPy — one pass over vertices instead of
        # four Python min() scans over every edge endpoint.
        import numpy as np
        from core.group import placement_points
        lo = None
        pts = [p for loop, holes, _a in face_data for p in loop]
        pts += [p for _, holes, _a in face_data for h in holes for p in h]
        pts += [p for a, b, _, _ in edge_data for p in (a, b)]
        if pts:
            lo = np.array([[p.x(), p.y(), p.z()] for p in pts]).min(axis=0)
        for g in group_data:
            # The whole placement, children included: a container's own
            # mesh is usually empty, and reading only that found nothing to
            # copy — Ctrl+C on an imported lamp post silently left the
            # previous clipboard in place, and Ctrl+V pasted the pergola
            # (Marco, 2026-09-11).
            arr = placement_points(g)
            if not len(arr):
                continue
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
        # Also on the system clipboard, so another IngeTrazo window can
        # paste it (issue #76); encoded only if that window asks.
        from formats import clip as clip_transfer
        clip_transfer.publish(self.clipboard)
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
