# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A deferred mesh's shape as arrays: what building it WOULD make, without
making a single Python object (the experimental engine's lazy meshes).

:func:`plan` replays :meth:`Mesh.bulk_weld`, :meth:`Mesh.add_edges_welded`
and :meth:`Mesh.add_faces_welded` on an empty mesh in NumPy: the vertex
positions in ``mesh.vertices`` order, the edges in ``mesh.edges`` order
with their flags, the faces' corners as vertex indices and each edge's
incident faces in ``edge.faces`` order. tests/test_lazy_mesh_plan.py holds
it to the built mesh, index for index."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core import mesh as _mesh


@dataclass
class Plan:
    pos: np.ndarray            # (V, 3) float64 holding float32 values
    edges: np.ndarray          # (E, 2) int64 vertex indices, v0 → v1
    soft: np.ndarray           # (E,) bool
    hidden: np.ndarray         # (E,) bool
    curve: list                # (E,) int or None
    layer: list                # (E,) str or None
    corners: np.ndarray        # every ring corner, vertex index
    ring_sizes: np.ndarray
    ring_counts: np.ndarray    # rings per face
    ef_start: np.ndarray       # (E + 1,) CSR into ef_face
    ef_face: np.ndarray        # incident face index, edge.faces order
    extra: dict = field(default_factory=dict)

    @property
    def nfaces(self) -> int:
        return len(self.ring_counts)


def weld(pos: np.ndarray, sequential: bool = False):
    """``(vpos, point_ids)``: what :meth:`Mesh.bulk_weld` returns on an EMPTY
    mesh, as positions instead of vertices (same order: the vertex list).
    ``sequential``: in the order :meth:`Mesh.vertex` called point by point
    makes them instead — the same vertices, each where its point comes."""
    vpos, ids, origin = _weld(pos)
    if sequential and len(vpos):
        order = np.argsort(origin, kind="stable")
        rank = np.empty_like(order)
        rank[order] = np.arange(len(order))
        vpos, ids = vpos[order], rank[ids]
    return vpos, ids


def _weld(pos: np.ndarray):
    """``(vpos, point_ids, origin)`` — the weld, and the input point each
    vertex was made at."""
    pos = np.ascontiguousarray(pos, dtype=np.float32).astype(np.float64)
    if not len(pos):
        return (np.zeros((0, 3)), np.empty(0, dtype=np.int64),
                np.empty(0, dtype=np.int64))
    import core._native as _native
    if _native.native is not None and hasattr(_native.native,
                                              "weld_points"):
        vpos, ids, origin = _native.native.weld_points(
            pos.astype(np.float32), _mesh._KEY_SCALE,
            (10.0 ** -_mesh._KEY_DECIMALS) ** 2)
        return vpos.astype(np.float64), ids, origin
    keys = np.round(pos * _mesh._KEY_SCALE).astype(np.int64)
    view = np.ascontiguousarray(keys).view(
        [("x", "<i8"), ("y", "<i8"), ("z", "<i8")]).reshape(-1)
    _u, first, inverse = np.unique(view, return_index=True,
                                   return_inverse=True)
    order = np.argsort(first, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    inverse = rank[inverse.reshape(-1)]
    first = first[order]
    ukeys = keys[first]
    nu = len(first)
    ax = [np.unique(ukeys[:, c]) for c in range(3)]
    nx, ny, nz = (len(a) + 2 for a in ax)

    def pack(k3):
        ok = np.ones(len(k3), dtype=bool)
        acc = np.zeros(len(k3), dtype=np.int64)
        for c, n in ((0, nx), (1, ny), (2, nz)):
            i = np.searchsorted(ax[c], k3[:, c])
            i_clip = np.minimum(i, len(ax[c]) - 1)
            ok &= (i < len(ax[c])) & (ax[c][i_clip] == k3[:, c])
            acc = acc * n + i_clip
        return acc, ok
    upacked, _ = pack(ukeys)
    usorted = np.sort(upacked)
    candidate = np.zeros(nu, dtype=bool)
    shifted = np.empty_like(ukeys)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                shifted[:, 0] = ukeys[:, 0] + dx
                shifted[:, 1] = ukeys[:, 1] + dy
                shifted[:, 2] = ukeys[:, 2] + dz
                q, ok = pack(shifted)
                i = np.minimum(np.searchsorted(usorted, q), nu - 1)
                candidate |= ok & (usorted[i] == q)
    # Creation order: the cells with no neighbour first (one vertex at the
    # cell's first point), then the candidate points replayed in input
    # order — bulk_weld appends to the vertex list in that very order.
    cand_pt = candidate[inverse]
    nc_cells = np.flatnonzero(~candidate)
    cell_vid = np.full(nu, -1, dtype=np.int64)
    cell_vid[nc_cells] = np.arange(len(nc_cells))
    point_ids = np.empty(len(pos), dtype=np.int64)
    ncp = ~cand_pt
    point_ids[ncp] = cell_vid[inverse[ncp]]
    vpos = [pos[first[nc_cells]]]
    origin = [first[nc_cells]]
    made: list = []
    cp = np.flatnonzero(cand_pt)
    if len(cp):
        registry: dict = {}
        for c, vid in zip(ukeys[nc_cells].tolist(), range(len(nc_cells))):
            registry[(c[0], c[1], c[2])] = vid
        f32 = np.float32
        tol2 = (10.0 ** -_mesh._KEY_DECIMALS) ** 2
        extra = []
        allpos32 = [vpos[0].astype(np.float32)]
        base = len(nc_cells)

        def position(vid):
            if vid < base:
                return allpos32[0][vid]
            return extra[vid - base]
        cp_keys = keys[cp].tolist()
        p32 = pos[cp].astype(np.float32)
        for j, i in enumerate(cp.tolist()):
            k3 = cp_keys[j]
            k = (k3[0], k3[1], k3[2])
            vid = registry.get(k)
            if vid is None:
                p = p32[j]
                for ddx in (-1, 0, 1):
                    for ddy in (-1, 0, 1):
                        for ddz in (-1, 0, 1):
                            if ddx == 0 and ddy == 0 and ddz == 0:
                                continue
                            n = registry.get((k[0] + ddx, k[1] + ddy,
                                              k[2] + ddz))
                            if n is None:
                                continue
                            d = position(n) - p        # float32, as Qt
                            if float(f32(d[0] * d[0] + d[1] * d[1]
                                         + d[2] * d[2])) < tol2:
                                vid = n
                                break
                        if vid is not None:
                            break
                    if vid is not None:
                        break
                if vid is None:
                    vid = base + len(extra)
                    extra.append(p)
                    made.append(i)
                    registry[k] = vid
            point_ids[i] = vid
        if extra:
            vpos.append(np.asarray(extra, dtype=np.float32)
                        .astype(np.float64))
    if made:
        origin.append(np.asarray(made, dtype=np.int64))
    return np.concatenate(vpos), point_ids, np.concatenate(origin)


def plan(pos, edges, flags, curves, layers, layer_names, rings, sizes,
         counts, sequential=False) -> Plan:
    """The built mesh of a format-3 block (already cleared of non-finite
    points), as :class:`Plan`. ``sequential``: built by the per-entity
    walk (vertices in the order each one's point comes)."""
    vpos, inverse = weld(pos, sequential)
    u = len(vpos)
    ia = inverse[edges[:, 0]] if len(edges) else np.empty(0, np.int64)
    ib = inverse[edges[:, 1]] if len(edges) else np.empty(0, np.int64)
    # add_edges_welded: skip welded-shut pairs, first occurrence wins the
    # orientation, flags accumulate (soft/hidden any, curve/layer last).
    keep = ia != ib
    idx = np.flatnonzero(keep)
    a, b = ia[idx], ib[idx]
    key = np.minimum(a, b) * u + np.maximum(a, b)
    ukey, efirst, einv = np.unique(key, return_index=True,
                                   return_inverse=True)
    order = np.argsort(efirst, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    einv = rank[einv.reshape(-1)]
    efirst = efirst[order]
    ukey = ukey[order]
    ne1 = len(ukey)
    e_ab = np.stack([a[efirst], b[efirst]], axis=1) if ne1 else \
        np.zeros((0, 2), np.int64)
    soft = np.zeros(ne1, dtype=bool)
    hidden = np.zeros(ne1, dtype=bool)
    curve = [None] * ne1
    layer = [None] * ne1
    if flags is not None and len(idx):
        f = flags[idx]
        np.logical_or.at(soft, einv, (f & 1).astype(bool))
        np.logical_or.at(hidden, einv, (f & 2).astype(bool))
        if curves is not None:
            for e, c in zip(einv.tolist(), curves[idx].tolist()):
                if c >= 0:
                    curve[e] = c
        if layers is not None:
            for e, l in zip(einv.tolist(), layers[idx].tolist()):
                if l >= 0:
                    layer[e] = layer_names[l]
    # add_faces_welded: every ring segment, the boundary edges it lacks
    # appended in first-occurrence order and orientation.
    corners = inverse[rings] if len(rings) else np.empty(0, np.int64)
    sizes = np.asarray(sizes, dtype=np.int64)
    counts = np.asarray(counts, dtype=np.int64)
    ef_start = np.zeros(ne1 + 1, dtype=np.int64)
    ef_face = np.empty(0, dtype=np.int64)
    all_edges = e_ab
    if len(counts):
        ring_ends = np.cumsum(sizes)
        ring_starts = ring_ends - sizes
        total = int(ring_ends[-1])
        nxt = np.arange(1, total + 1, dtype=np.int64)
        nxt[ring_ends - 1] = ring_starts
        sa, sb = corners, corners[nxt]
        packed = np.minimum(sa, sb) * u + np.maximum(sa, sb)
        upk, sfirst, sinv = np.unique(packed, return_index=True,
                                      return_inverse=True)
        sorder = np.argsort(sfirst, kind="stable")
        srank = np.empty_like(sorder)
        srank[sorder] = np.arange(len(sorder))
        sinv = srank[sinv.reshape(-1)]
        upk = upk[sorder]
        sfirst = sfirst[sorder]
        # Which segment keys are existing edges, and which edge.
        pos_in = np.searchsorted(np.sort(ukey), upk) if ne1 else \
            np.zeros(len(upk), np.int64)
        sorted_key_order = np.argsort(ukey, kind="stable")
        exists = np.zeros(len(upk), dtype=bool)
        edge_of = np.empty(len(upk), dtype=np.int64)
        if ne1:
            pc = np.minimum(pos_in, ne1 - 1)
            exists = ukey[sorted_key_order[pc]] == upk
            edge_of[exists] = sorted_key_order[pc[exists]]
        new = np.flatnonzero(~exists)
        edge_of[new] = ne1 + np.arange(len(new))
        new_ab = np.stack([sa[sfirst[new]], sb[sfirst[new]]], axis=1) \
            if len(new) else np.zeros((0, 2), np.int64)
        all_edges = np.concatenate([e_ab, new_ab])
        nn = len(new)
        soft = np.concatenate([soft, np.zeros(nn, dtype=bool)])
        hidden = np.concatenate([hidden, np.zeros(nn, dtype=bool)])
        curve = curve + [None] * nn
        layer = layer + [None] * nn
        # edge.faces: per edge, its segments' faces in global segment order.
        seg_face = np.repeat(np.arange(len(counts), dtype=np.int64),
                             np.add.reduceat(sizes, np.cumsum(counts)
                                             - counts))
        seg_edge = edge_of[sinv]
        o = np.argsort(seg_edge, kind="stable")
        ef_face = seg_face[o]
        ef_start = np.zeros(len(all_edges) + 1, dtype=np.int64)
        np.cumsum(np.bincount(seg_edge, minlength=len(all_edges)),
                  out=ef_start[1:])
    return Plan(vpos, all_edges, soft, hidden, curve, layer, corners,
                sizes, counts, ef_start, ef_face)


def plan_of(mesh) -> Plan | None:
    """The :class:`Plan` of a still-deferred mesh (memoised on it), or
    ``None`` once it is built or when it was never deferred."""
    if type(mesh) is not _mesh.DeferredMesh:
        return None
    d = mesh.__dict__
    hit = d.get("_deferred_plan")
    if hit is None:
        s = d["_deferred_source"]
        hit = d["_deferred_plan"] = plan(
            s["pos"], s["edges"], s["flags"], s["curves"], s["layers"],
            s["meta"].get("edge_layers") or [], s["rings"], s["sizes"],
            s["counts"], s.get("sequential", False))
    return hit


def entity_count(mesh) -> int:
    """``len(mesh.faces) + len(mesh.edges)``, a lazy mesh left unbuilt."""
    plan = plan_of(mesh)
    if plan is not None:
        return plan.nfaces + len(plan.edges)
    return len(mesh.faces) + len(mesh.edges)


class PlannedVertices:
    """``mesh.vertices`` of a lazy mesh for code that only reads their
    positions: ``pv[i].position`` is the i-th planned vertex's position (a
    fresh QVector3D), ``len(pv)`` their count — nothing built."""

    __slots__ = ("pos",)

    class _V:
        __slots__ = ("position",)

        def __init__(self, p):
            from PySide6.QtGui import QVector3D
            self.position = QVector3D(float(p[0]), float(p[1]), float(p[2]))

    def __init__(self, pos):
        self.pos = pos

    def __len__(self):
        return len(self.pos)

    def __getitem__(self, i):
        return PlannedVertices._V(self.pos[int(i)])
