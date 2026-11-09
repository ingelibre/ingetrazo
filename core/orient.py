# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Consistent outward orientation for closed solids in the non-manifold mesh.

The root-fix invariant: every face of a closed solid is wound so its normal
points *outward* from the enclosed volume. The solid push/pull pipeline relies
on it at both ends — it orients **on entry** (hand-built or loaded meshes can
arrive with mixed winding) so the naive extrude's deterministic quad winding
and the per-plane rebuild's material-side classification (:mod:`core.
cap_rebuild`) can trust face normals, and **on exit** so every committed solid
upholds the invariant for the next edit.

The mesh is **shared-vertex, non-manifold** (an interior wall is shared by two
rooms; an edge can border three faces), so winding does *not* propagate cleanly
through half-edges — there is no single "the other face across this edge". So
orientation is decided **per face, independently**, by parity ray casting: a
point just off a face along its normal is *outside* the solid iff a ray from it
crosses the rest of the mesh an even number of times. That is robust to
non-manifold edges and needs no seed face.

Only meaningful for a **closed** component (no boundary edges). Flat drawings and
open sheets have no inside/outside, so the entry points no-op on them.
"""
from __future__ import annotations

import math
import random
from typing import Optional

from PySide6.QtGui import QVector3D

from core.mesh import turn_face_over

# Ray/triangle hit tolerance and the small offset used to lift the sample point
# off the face it sits on.
_EPS = 1e-7
_T_MIN = 1e-6
# Number of jittered rays voted over to step around degenerate hits (a ray that
# grazes a shared edge or vertex would be counted 0 or 2 times). The face normal
# is one of them; the rest are small angular perturbations. The jitter must be
# *small*: the lateral deviation grows linearly with distance, and a wide cone
# (it used to be 0.08) overshoots thin features far away — a 0.3 m belt strip
# at 4 m deviated by ±0.32 m, so most rays missed it and the vote read "no
# material" by seed luck. 3e-4 keeps the deviation ~2 cm even 60 m out while
# still dodging exact edge/vertex grazes of human-valued coordinates.
_RAYS = 7
_JITTER = 3e-4


Triangle = tuple[QVector3D, QVector3D, QVector3D]


# ---- Ray / triangle --------------------------------------------------------

def _ray_triangle(origin: QVector3D, direction: QVector3D, tri: Triangle) -> Optional[float]:
    """Möller–Trumbore. Returns the ray parameter ``t > 0`` of the intersection
    with ``tri``, or ``None`` (miss / parallel / behind)."""
    a, b, c = tri
    e1 = b - a
    e2 = c - a
    p = QVector3D.crossProduct(direction, e2)
    det = QVector3D.dotProduct(e1, p)
    if abs(det) < _EPS:
        return None  # parallel
    inv = 1.0 / det
    tvec = origin - a
    u = QVector3D.dotProduct(tvec, p) * inv
    if u < -_EPS or u > 1.0 + _EPS:
        return None
    q = QVector3D.crossProduct(tvec, e1)
    v = QVector3D.dotProduct(direction, q) * inv
    if v < -_EPS or u + v > 1.0 + _EPS:
        return None
    t = QVector3D.dotProduct(e2, q) * inv
    return t if t > _T_MIN else None


def _basis(n: QVector3D) -> tuple[QVector3D, QVector3D]:
    """Two unit vectors perpendicular to ``n`` (for jittering a ray direction)."""
    ref = QVector3D(1.0, 0.0, 0.0)
    if abs(QVector3D.dotProduct(ref, n)) > 0.9:
        ref = QVector3D(0.0, 1.0, 0.0)
    u = QVector3D.crossProduct(n, ref).normalized()
    v = QVector3D.crossProduct(n, u).normalized()
    return u, v


def _face_triangles(mesh) -> dict:
    """Triangulate every face once. Returns ``{face: [Triangle, …]}`` in world
    space (holes included via the face's own earcut triangulation)."""
    tris: dict = {}
    for f in mesh.faces:
        tris[f] = f.triangulate()
    return tris


def _face_components(mesh) -> dict:
    """Face → edge-connected component label (union-find through shared
    edges).

    Inside/outside is a property of one closed shell, so parity is decided
    against the face's *own* component: a ray from a probe outside a
    *different* closed component crosses it an even number of times (in and
    back out), so those triangles never change the verdict — and for probes
    on nested or coincident imported solids, judging each shell by itself is
    the semantically right call (a box modelled inside a room is its own
    outward solid, not "interior" of the room). The payoff is the imported
    group mesh (many welded bricks in one mesh): O(F·T) becomes Σ O(F_c·T_c)
    — the barbecue's orientation pass dropped ~7×."""
    idx = {f: i for i, f in enumerate(mesh.faces)}
    parent = list(range(len(mesh.faces)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in mesh.edges:
        it = iter(e.faces)
        first = next((idx[f] for f in it if f in idx), None)
        if first is None:
            continue
        for f in it:
            j = idx.get(f)
            if j is not None:
                ra, rb = find(first), find(j)
                if ra != rb:
                    parent[ra] = rb
    return {f: find(i) for f, i in idx.items()}


class _PackedTris:
    """Triangles flattened to NumPy arrays for batched Möller–Trumbore.

    ``a``/``e1``/``e2`` are (N, 3) float64 (vertex A and the two edge vectors);
    ``face_idx`` maps each triangle to its face's index so a query can exclude
    faces without repacking. The parity primitive used to test each ray against
    every triangle in pure Python — the O(F²·T) hot loop that froze the app as
    solids grew; one vectorised pass per ray replaces it."""

    __slots__ = ("a", "e1", "e2", "face_idx", "bvh", "native")

    def __init__(self, a, e1, e2, face_idx) -> None:
        self.a, self.e1, self.e2, self.face_idx = a, e1, e2, face_idx
        self.bvh = None             # _Clusters, built on first use
        self.native = None          # the Rust engine's copy, ditto


#: Below this many triangles a ray just tests them all.
_BVH_MIN_TRIS = 2048
#: Triangles per cluster of the ray index.
_BVH_LEAF = 32


class _Clusters:
    """A one-level ray index over a packed triangle set: triangles sorted
    along a Morton curve of their centroids, cut into clusters of
    ``_BVH_LEAF`` neighbours, each with a box grown far beyond the ray test's
    tolerances (barycentric 1e-7, t > 1e-6). A ray keeps only the clusters
    whose box it crosses; the exact Möller–Trumbore count then runs on those
    triangles alone — the same count, since every triangle the exact test
    would accept lies inside its cluster's box. Orienting one 25 797-face
    component cast ~360 000 rays against every triangle: 3 minutes for one
    push on the Plaza's terrain (09-10)."""

    def __init__(self, packed: "_PackedTris") -> None:
        import numpy as np
        a, e1, e2 = packed.a, packed.e1, packed.e2
        b, c = a + e1, a + e2
        lo = np.minimum(np.minimum(a, b), c)
        hi = np.maximum(np.maximum(a, b), c)
        cen = (lo + hi) * 0.5
        span = cen.max(axis=0) - cen.min(axis=0)
        span[span <= 0] = 1.0
        q = ((cen - cen.min(axis=0)) / span * 1023).astype(np.int64)
        code = np.zeros(len(q), dtype=np.int64)
        for bit in range(10):
            for axis in range(3):
                code |= ((q[:, axis] >> bit) & 1) << (3 * bit + axis)
        order = np.argsort(code, kind="stable")
        n = len(order)
        starts = np.arange(0, n, _BVH_LEAF)
        clo = np.minimum.reduceat(lo[order], starts, axis=0)
        chi = np.maximum.reduceat(hi[order], starts, axis=0)
        ext = (chi - clo).max(axis=1, keepdims=True)
        big = np.maximum(np.abs(clo).max(axis=1, keepdims=True),
                         np.abs(chi).max(axis=1, keepdims=True))
        margin = 1e-5 + 1e-6 * big + 1e-5 * ext
        self.lo, self.hi = clo - margin, chi + margin
        self.cen = (self.lo + self.hi) * 0.5
        self.half = np.linalg.norm(self.hi - self.lo, axis=1) * 0.5
        self.order = order
        self.counts = np.diff(np.append(starts, n))

    def rows(self, origin, direction, spread: float):
        """Rows of the triangles in a cluster any ray from ``origin`` within
        ``spread`` radians of ``direction`` can cross: ONE slab test along
        ``direction`` against each box grown by how far such a ray can stray
        before leaving it (spread × the box's farthest distance) — the
        jittered rays of one parity query differ by < 0.03°."""
        import numpy as np
        o = np.asarray(origin, dtype=np.float64)
        reach = np.linalg.norm(self.cen - o, axis=1) + self.half
        grow = (spread * reach)[:, None]
        lo, hi = self.lo - grow, self.hi + grow
        dv = np.asarray(direction, dtype=np.float64)
        dv = np.where(np.abs(dv) < 1e-30, 1e-30, dv)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            inv = 1.0 / dv
            t1 = (lo - o) * inv
            t2 = (hi - o) * inv
            tmin = np.minimum(t1, t2).max(axis=1)
            tmax = np.maximum(t1, t2).min(axis=1)
        hit = (tmax >= tmin) & (tmax >= 0.0)
        return self.order[np.repeat(hit, self.counts)]


def _pack_lists(triangle_lists, face_ids=None) -> _PackedTris:
    """Flatten ``triangle_lists`` (iterable of triangle lists) into arrays.
    ``face_ids`` gives the face index per list (defaults to the list's order)."""
    import numpy as np
    rows_a, rows_b, rows_c, idx = [], [], [], []
    for li, tlist in enumerate(triangle_lists):
        fi = face_ids[li] if face_ids is not None else li
        for (ta, tb, tc) in tlist:
            rows_a.append((ta.x(), ta.y(), ta.z()))
            rows_b.append((tb.x(), tb.y(), tb.z()))
            rows_c.append((tc.x(), tc.y(), tc.z()))
            idx.append(fi)
    if not rows_a:
        return _PackedTris(np.zeros((0, 3)), np.zeros((0, 3)),
                           np.zeros((0, 3)), np.zeros(0, dtype=np.int64))
    a = np.asarray(rows_a, dtype=np.float64)
    b = np.asarray(rows_b, dtype=np.float64)
    c = np.asarray(rows_c, dtype=np.float64)
    return _PackedTris(a, b - a, c - a, np.asarray(idx, dtype=np.int64))


def _cross_rows(a, b):
    """Row-wise cross product without np.cross's moveaxis overhead.
    ``a`` is (3,) or (N,3); ``b`` is (N,3)."""
    import numpy as np
    ax, ay, az = (a[..., 0], a[..., 1], a[..., 2])
    bx, by, bz = b[:, 0], b[:, 1], b[:, 2]
    return np.stack((ay * bz - az * by,
                     az * bx - ax * bz,
                     ax * by - ay * bx), axis=-1)


class _ParityQuery:
    """One origin, many jittered rays: everything that depends only on the
    origin (tvec, q, e2·q) is computed once; each ray then costs a couple of
    vector ops. Same eps/t-min semantics as the scalar Möller–Trumbore."""

    def __init__(self, origin: QVector3D, packed: _PackedTris, mask=None) -> None:
        import numpy as np
        self.n = packed.a.shape[0]
        if self.n == 0:
            return
        o = np.array([origin.x(), origin.y(), origin.z()], dtype=np.float64)
        self.e1, self.e2 = packed.e1, packed.e2
        self.base = np.ones(self.n, dtype=bool) if mask is None else mask
        self.tvec = o - packed.a
        self.q = _cross_rows(self.tvec, packed.e1)
        self.e2q = np.einsum("ij,ij->i", packed.e2, self.q)

    def crossings(self, d: QVector3D) -> int:
        import numpy as np
        if self.n == 0:
            return 0
        dv = np.array([d.x(), d.y(), d.z()], dtype=np.float64)
        p = _cross_rows(dv, self.e2)
        det = np.einsum("ij,ij->i", self.e1, p)
        ok = (np.abs(det) >= _EPS) & self.base
        if not ok.any():
            return 0
        inv = np.zeros(self.n)
        inv[ok] = 1.0 / det[ok]
        u = np.einsum("ij,ij->i", self.tvec, p) * inv
        ok &= (u >= -_EPS) & (u <= 1.0 + _EPS)
        v = (self.q @ dv) * inv
        ok &= (v >= -_EPS) & (u + v <= 1.0 + _EPS)
        t = self.e2q * inv
        ok &= t > _T_MIN
        return int(ok.sum())

    def crossings_many(self, dirs) -> list:
        """``crossings`` for several rays at once: the same arithmetic,
        element by element, over a (rays × triangles) block instead of one
        NumPy pass per ray (tests/test_orient_batched_rays.py checks the
        counts against ``crossings`` itself)."""
        import numpy as np
        r = len(dirs)
        if self.n == 0 or r == 0:
            return [0] * r
        D = np.array([[d.x(), d.y(), d.z()] for d in dirs], dtype=np.float64)
        ax, ay, az = D[:, 0:1], D[:, 1:2], D[:, 2:3]
        bx, by, bz = self.e2[:, 0], self.e2[:, 1], self.e2[:, 2]
        p = np.stack((ay * bz - az * by,
                      az * bx - ax * bz,
                      ax * by - ay * bx), axis=-1)          # (r, n, 3)
        det = np.einsum("ij,rij->ri", self.e1, p)
        ok = (np.abs(det) >= _EPS) & self.base
        inv = np.zeros((r, self.n))
        inv[ok] = 1.0 / det[ok]
        u = np.einsum("ij,rij->ri", self.tvec, p) * inv
        ok &= (u >= -_EPS) & (u <= 1.0 + _EPS)
        v = np.stack([self.q @ D[i] for i in range(r)]) * inv
        ok &= (v >= -_EPS) & (u + v <= 1.0 + _EPS)
        t = self.e2q * inv
        ok &= t > _T_MIN
        return [int(c) for c in ok.sum(axis=1)]


def ray_parity_outside(origin: QVector3D, direction: QVector3D,
                       triangle_lists, rng: random.Random,
                       packed: Optional[_PackedTris] = None,
                       mask=None, skip: Optional[int] = None) -> Optional[bool]:
    """Whether ``origin`` sits *outside* the volume bounded by the triangles, by
    crossing parity along jittered rays around ``direction`` (majority vote —
    a single ray can graze a shared edge and miscount). Even crossings ahead →
    outside (infinity is outside; each crossing flips). ``None`` on a tie.

    This is the engine's one volumetric primitive: orientation asks it with a
    face's centroid and normal, and the per-plane rebuild asks it from sample
    points just off a plane ("is there material on this side?") — the dirty
    overlapping coplanar faces a naive extrude leaves cancel in pairs, so the
    answer is right even mid-cleanup, in any plane order.

    Pass ``packed`` (+ optional boolean ``mask`` over its triangles) to reuse a
    prebuilt triangle set across many queries; otherwise ``triangle_lists`` is
    packed on the fly. Either way the crossing count is vectorised.
    ``skip``: a face index of ``packed`` whose triangles do not count (the
    face asking), on top of ``mask``."""
    if packed is None:
        packed = _pack_lists(triangle_lists)
        mask = None
        skip = None
    n = direction.normalized()
    u, v = _basis(n)
    # The rays first (the same draws from ``rng``, in the same order).
    rays = []
    for r in range(_RAYS):
        if r == 0:
            d = n
        else:
            d = (n
                 + u * rng.uniform(-_JITTER, _JITTER)
                 + v * rng.uniform(-_JITTER, _JITTER)).normalized()
        rays.append(d)
    from core._native import native
    if native is not None and packed.a.shape[0]:
        # The Rust engine: the same exact test over the same triangles,
        # found through its own ray index.
        import numpy as np
        if packed.native is None:
            packed.native = native.ParityTris(
                np.ascontiguousarray(packed.a, dtype=np.float64),
                np.ascontiguousarray(packed.e1, dtype=np.float64),
                np.ascontiguousarray(packed.e2, dtype=np.float64),
                np.ascontiguousarray(packed.face_idx, dtype=np.int64))
        dirs = np.array([[d.x(), d.y(), d.z()] for d in rays],
                        dtype=np.float64)
        counts = packed.native.crossings(
            (origin.x(), origin.y(), origin.z()), dirs,
            None if mask is None else np.ascontiguousarray(mask, dtype=bool),
            None if skip is None else int(skip))
    else:
        counts = _python_crossings(origin, n, rays, packed, mask, skip)
    outside_votes = 0
    inside_votes = 0
    for crossings in counts:
        if crossings % 2 == 0:
            outside_votes += 1
        else:
            inside_votes += 1
    if outside_votes == inside_votes:
        return None
    return outside_votes > inside_votes


def _python_crossings(origin, n, rays, packed, mask, skip) -> list:
    """Crossing counts of ``rays`` from ``origin`` (NumPy)."""
    if skip is not None:
        keep = packed.face_idx != skip
        mask = keep if mask is None else mask & keep
    if packed.a.shape[0] >= _BVH_MIN_TRIS:
        if packed.bvh is None:
            packed.bvh = _Clusters(packed)
        # Each jittered ray is within 2·√2·_JITTER of ``n`` (a unit vector
        # nudged by two perpendicular offsets of at most _JITTER, then
        # renormalised); the index is asked with three times that.
        rows = packed.bvh.rows((origin.x(), origin.y(), origin.z()),
                               (n.x(), n.y(), n.z()), 3.0 * 2.83 * _JITTER)
        packed = _PackedTris(packed.a[rows], packed.e1[rows],
                             packed.e2[rows], packed.face_idx[rows])
        if mask is not None:
            mask = mask[rows]
    return _ParityQuery(origin, packed, mask).crossings_many(rays)


def _face_side_state(face, tris_by_face: dict, rng: random.Random,
                     packed: Optional[_PackedTris] = None,
                     mask=None, skip: Optional[int] = None) -> Optional[str]:
    """Classify ``face`` against the volume bounded by ``tris_by_face`` (the
    current *boundary* faces): ``"outward"`` / ``"inward"`` for a boundary face
    (by which side is empty), ``"interior"`` for a partition with material on
    both sides (the slab a Ctrl-push keeps, a wall two rooms share), ``None``
    when undecidable (degenerate face, tied votes).

    ``packed``/``mask`` (triangles of the boundary set minus this face) let the
    caller reuse one packed array across every face instead of re-listing —
    the difference between O(F²·T) and O(F·T)."""
    n = face.normal()
    if n.length() < 1e-9:
        return None
    if packed is None:
        others = [t for f, t in tris_by_face.items() if f is not face]
    else:
        others = None
    # Probe from a point INSIDE the face's solid region. The loop centroid is
    # wrong for a ring face: it falls in the hole (an annular cap's centroid
    # sits in the tube's channel), and rays cast from the void misclassify
    # the cap. The largest triangle's centroid always lies on material.
    probe = _interior_probe(face)
    # The region just past the probe along the normal being outside is
    # exactly the normal pointing outward.
    ahead = ray_parity_outside(probe, n, others, rng,
                               packed=packed, mask=mask, skip=skip)
    if ahead is not False:
        return "outward" if ahead else None
    # The +normal side is inside. An inward-wound boundary face has its *other*
    # side outside; an interior partition is inside both ways.
    behind = ray_parity_outside(probe, -n, others, rng,
                                packed=packed, mask=mask, skip=skip)
    if behind is True:
        return "inward"
    return "interior" if behind is False else None


def _interior_probe(face) -> QVector3D:
    """A point on the face's solid material.

    For a HOLED face the loop centroid falls in the hole (an annular tube cap
    probes from the channel void and flips) — use the largest triangle's
    centroid instead. Hole-free faces keep the plain centroid: the fuzz
    rule-set is hardened around it, and switching those probes destabilised
    seeds (prism 151, plan 179, cube 214) for no gain."""
    if not face.hole_loops:
        c = face.centroid()
        if _on_face(face, c):
            return c
        # A NON-CONVEX face (an L, a U) can have its vertex average off its
        # own material — in the notch, where a step's pulled-up square now
        # stands — and probing from there read a boundary wall and floor as
        # interior partitions: a closed, correct solid whose volume came out
        # 2.3 m³ short (issue #94). Only then the largest triangle.
    tris = face.triangulate()
    if not tris:
        return face.centroid()
    t0, t1, t2 = max(
        tris,
        key=lambda t: QVector3D.crossProduct(t[1] - t[0],
                                             t[2] - t[0]).lengthSquared())
    return (t0 + t1 + t2) / 3.0


def _on_face(face, p: QVector3D) -> bool:
    """Whether ``p`` (on the face's plane) lies inside its outer loop."""
    from core.arrangement import _point_in_polygon, plane_basis
    n = face.normal()
    if n.length() < 1e-12:
        return True
    u, v = plane_basis(n.normalized())
    loop = [((q - p).x() * u.x() + (q - p).y() * u.y() + (q - p).z() * u.z(),
             (q - p).x() * v.x() + (q - p).y() * v.y() + (q - p).z() * v.z())
            for q in face.vertices]
    return _point_in_polygon((0.0, 0.0), loop)


# ---- Public API ------------------------------------------------------------

def _all_coplanar(mesh) -> bool:
    """Cheap flatness test: every face on one plane (a 2D drawing)."""
    first = mesh.faces[0]
    n = first.normal()
    o = first.centroid()
    for f in mesh.faces:
        fn = f.normal()
        if abs(QVector3D.dotProduct(fn, n)) < 0.999:
            return False
        if abs(QVector3D.dotProduct(f.centroid() - o, n)) > 1e-4:
            return False
    return True


def is_closed(mesh) -> bool:
    """Whether the mesh has no boundary: every edge borders at least two faces.
    A necessary condition for inside/outside (and thus orientation) to mean
    anything. Open sheets and flat drawings return ``False``."""
    if not mesh.faces:
        return False
    return all(len(e.faces) >= 2 for e in mesh.edges)


def signed_volume(mesh) -> float:
    """Signed volume of the mesh as currently wound (sum of tetrahedra from the
    origin over each triangulated face). For a consistently-oriented closed
    solid its magnitude is the real volume and its sign reports the global
    winding (positive == outward by the right-hand rule). Mixed winding gives a
    meaningless value — use it only to confirm consistency. Interior partitions
    (marked by :func:`orient_outward`) are not boundary and are skipped — their
    arbitrary winding would bias the sum."""
    total = 0.0
    for f in mesh.faces:
        if f.interior:
            continue
        for a, b, c in f.triangulate():
            total += QVector3D.dotProduct(a, QVector3D.crossProduct(b, c)) / 6.0
    return total


def orient_outward(mesh, seed: int = 12345, only=None) -> list:
    """Flip the faces of a closed solid so every boundary normal points
    outward, and mark interior partitions (``face.interior``). Returns the
    faces that were flipped.

    No-op (returns ``[]``) on a mesh that isn't closed — an open sheet or flat
    drawing has no outside, so there is nothing to orient.

    Parity ray-casting only means anything against the *boundary* faces, but an
    interior partition (the slab a Ctrl-push keeps, a wall two rooms share) is
    not boundary — a ray crossing it would flip parity without leaving the
    solid. So the partitions are peeled off iteratively: classify every face
    against the current boundary set, drop the ones that read interior,
    reclassify — to a fixpoint (typically 1 extra round; capped). Boundary
    faces judged inward are then flipped; partitions keep their winding (no
    winding of theirs is outward).

    ``only`` (faces) restricts the pass to the edge-connected components those
    faces belong to; every other face keeps its winding and its ``interior``
    mark. Since orientation is decided per component anyway, an edit that
    touched one solid has nothing to say about the others — and re-deciding
    them costs the same as deciding the edit's own. A group holding many
    welded bricks is the case that makes it matter: pushing one brick used to
    re-run parity over all of them."""
    if not mesh.faces:
        return []
    if _all_coplanar(mesh):
        # A flat drawing has no volume at all: no partitions, nothing to flip.
        for f in mesh.faces:
            f.interior = False
        return []
    import numpy as np
    all_tris = _face_triangles(mesh)
    faces = list(all_tris)
    fidx = {f: i for i, f in enumerate(faces)}
    # Pack every triangle once; per-face queries exclude by mask instead of
    # re-listing the other faces' triangles (the old O(F²·T) hot loop).
    packed = _pack_lists([all_tris[f] for f in faces])
    # Each face is judged against its own edge-connected component only (see
    # :func:`_face_components`): slice the packed rows per component up front.
    # A single-component mesh gets exactly one slice — the whole array — so
    # drawn geometry behaves bit-identically to the unsliced pass.
    comp_of = _face_components(mesh)
    comp_idx = np.asarray([comp_of[f] for f in faces], dtype=np.int64)
    row_comp = (comp_idx[packed.face_idx] if len(packed.face_idx)
                else np.zeros(0, dtype=np.int64))
    comp_rows = {int(c): np.flatnonzero(row_comp == c)
                 for c in np.unique(comp_idx)}
    sub = {c: _PackedTris(packed.a[r], packed.e1[r], packed.e2[r],
                          packed.face_idx[r])
           for c, r in comp_rows.items()}

    def _boundary_base(boundary_set):
        # ONE isin per round — rebuilding the boundary-id array and running
        # isin over every packed triangle PER FACE repeated identical work
        # F times per round (imported brick barbecue: the push click hung
        # for minutes at 195% CPU; SIGUSR1 autopsy pinned np.isin here).
        ids = np.fromiter((fidx[f] for f in boundary_set), dtype=np.int64,
                          count=len(boundary_set))
        base = np.isin(packed.face_idx, ids)
        return {c: base[r] for c, r in comp_rows.items()}

    # Faces this call decides. Out-of-scope faces stay in ``boundary`` (so the
    # in-scope components' masks are built the same way) but are never queried
    # and never re-marked.
    if only is None:
        scope = list(mesh.faces)
    else:
        live_comps = {comp_of[f] for f in only if f in comp_of}
        if not live_comps:
            return []
        scope = [f for f in mesh.faces if comp_of[f] in live_comps]

    boundary = dict(all_tris)
    for _ in range(4):
        rng = random.Random(seed)
        base_by_comp = _boundary_base(set(boundary))
        interior_now = set()
        for f in scope:
            c = comp_of[f]
            sp = sub[c]
            state = _face_side_state(
                f, boundary, rng, packed=sp, mask=base_by_comp[c],
                skip=fidx[f])
            if state == "interior":
                interior_now.add(f)
        if interior_now == {f for f in scope if f not in boundary}:
            break
        boundary = {f: t for f, t in all_tris.items() if f not in interior_now}
    for f in scope:
        f.interior = f not in boundary

    # Flipping needs a real outside, which only a closed mesh has. The marks
    # above are still computed for open meshes (a plan mixing raised rooms
    # with flat floors is open as a whole, yet its interior walls are real
    # partitions the volumetric queries must skip).
    mesh_closed = is_closed(mesh)
    if not mesh_closed:
        if only is None:
            return []
        # A scoped pass (an edit's own solids) judges closure per
        # component: one open piece elsewhere in the mesh used to stop the
        # pass for every solid, and a cube pushed beside a cube with a
        # face deleted kept its base reversed (#230). An open component
        # still has no outside, so its faces are never turned.
        open_comps = {comp_of[f] for e in mesh.edges if len(e.faces) == 1
                      for f in e.faces if f in comp_of}
        scope = [f for f in scope if comp_of[f] not in open_comps]
        if not scope:
            return []
    rng = random.Random(seed)
    base_by_comp = _boundary_base(set(boundary))
    to_flip = []
    for f in scope:
        if f not in boundary:
            continue
        c = comp_of[f]
        sp = sub[c]
        if _face_side_state(f, boundary, rng, packed=sp,
                            mask=base_by_comp[c], skip=fidx[f]) == "inward":
            to_flip.append(f)
    # Through an open mesh (the scoped path above) the flips are checked
    # before they stay: a solid whose shared edges disagree MORE after the
    # flips than before was misread by the parity rays, and keeps the
    # windings it had. Measured on plaza.igz: of five solids this path
    # would turn, four came out more consistent and one — a 51-face solid
    # consistent to begin with — would have lost 52 edges (#230).
    saved = {}
    before_bad = {}
    if not mesh_closed and to_flip:
        import copy
        for f in to_flip:
            saved[f] = (copy.deepcopy(f.attrs), list(f.loop),
                        [list(h) for h in f.hole_loops])
        members: dict = {}
        flip_comps = {comp_of[f] for f in to_flip}
        for f in scope:
            if comp_of[f] in flip_comps:
                members.setdefault(comp_of[f], []).append(f)
        before_bad = {c: _incoherent_edges(fs) for c, fs in members.items()}
    for f in to_flip:
        # Flip in place: reversing the loops reverses the winding (so the normal
        # flips) while keeping the *same* Face object and its shared edges/
        # incidence. Identity is preserved — a freshly extruded box keeps its
        # base face object, and snapshot undo stays valid. Each geometric
        # side keeps its own paint (``turn_face_over``): this pass corrects
        # windings, it must not move a brick texture indoors.
        turn_face_over(f)
    if before_bad:
        worse = {c for c, fs in members.items()
                 if _incoherent_edges(fs) > before_bad[c]}
        if worse:
            for f in to_flip:
                if comp_of[f] in worse:
                    attrs, loop, holes = saved[f]
                    f.attrs = attrs
                    f.loop[:] = loop
                    for h, old in zip(f.hole_loops, holes):
                        h[:] = old
            to_flip = [f for f in to_flip if comp_of[f] not in worse]
    return to_flip


def _incoherent_edges(faces) -> int:
    """How many edges two of ``faces`` both walk in the same direction. In
    a consistently wound solid every shared edge is walked once each way,
    so this counts the disagreements, independently of any ray."""
    uses: dict = {}
    for f in faces:
        for loop in (f.loop, *f.hole_loops):
            n = len(loop)
            for i in range(n):
                a, b = loop[i], loop[(i + 1) % n]
                uses.setdefault(frozenset((id(a), id(b))), []).append(
                    (id(a), id(b)))
    return sum(1 for u in uses.values() if len(u) == 2 and u[0] == u[1])
