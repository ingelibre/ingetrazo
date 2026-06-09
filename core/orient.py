"""Consistent outward orientation for closed solids in the non-manifold mesh.

Root-fix groundwork. The 3D push/pull currently leans on two crutches that hide
a missing invariant — the mesh has no globally consistent winding:

- the coplanar merge accepts faces ``abs(dot) > 0.999`` (winding sign ignored),
  because a pushed strip can come out wound backwards relative to its coplanar
  neighbour;
- ``cap_boundary_loops`` patches cracks after the fact.

The fix is to give the mesh a consistent orientation: every face of a closed
solid wound so its normal points *outward* from the enclosed volume. Then two
coplanar faces of one surface share the *same* normal (dot ≈ +1), the merge can
drop ``abs()``, and the "flipped fragment" class of bug disappears.

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

# Ray/triangle hit tolerance and the small offset used to lift the sample point
# off the face it sits on.
_EPS = 1e-7
_T_MIN = 1e-6
# Number of jittered rays voted over to step around degenerate hits (a ray that
# grazes a shared edge or vertex would be counted 0 or 2 times). The face normal
# is one of them; the rest are small angular perturbations.
_RAYS = 7
_JITTER = 0.08


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


def _normal_points_outward(face, tris_by_face: dict, rng: random.Random) -> Optional[bool]:
    """Whether ``face``'s current normal points out of the solid, by parity ray
    casting from its centroid. ``None`` when the votes don't agree (degenerate —
    leave the face as is)."""
    n = face.normal()
    if n.length() < 1e-9:
        return None
    n = n.normalized()
    origin = face.centroid()
    others = [(f, t) for f, t in tris_by_face.items() if f is not face]

    u, v = _basis(n)
    outward_votes = 0
    inward_votes = 0
    for r in range(_RAYS):
        if r == 0:
            d = n
        else:
            d = (n
                 + u * rng.uniform(-_JITTER, _JITTER)
                 + v * rng.uniform(-_JITTER, _JITTER)).normalized()
        crossings = 0
        for _f, tlist in others:
            for tri in tlist:
                if _ray_triangle(origin, d, tri) is not None:
                    crossings += 1
        # Even crossings ahead → the region just past the centroid along the
        # normal is outside (infinity is outside; each crossing flips) → outward.
        if crossings % 2 == 0:
            outward_votes += 1
        else:
            inward_votes += 1
    if outward_votes == inward_votes:
        return None
    return outward_votes > inward_votes


# ---- Public API ------------------------------------------------------------

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
    meaningless value — use it only to confirm consistency."""
    total = 0.0
    for f in mesh.faces:
        for a, b, c in f.triangulate():
            total += QVector3D.dotProduct(a, QVector3D.crossProduct(b, c)) / 6.0
    return total


def orient_outward(mesh, seed: int = 12345) -> list:
    """Flip the faces of a closed solid so every normal points outward. Returns
    the faces that were flipped.

    No-op (returns ``[]``) on a mesh that isn't closed — an open sheet or flat
    drawing has no outside, so there is nothing to orient. Decided per face by
    parity ray casting (see module docstring), so it tolerates the non-manifold
    edges of architecture (an interior wall shared by two rooms is *not* part of
    a single closed shell and is left as is by the closedness gate).
    """
    if not is_closed(mesh):
        return []
    rng = random.Random(seed)
    tris_by_face = _face_triangles(mesh)
    to_flip = []
    for f in mesh.faces:
        outward = _normal_points_outward(f, tris_by_face, rng)
        if outward is False:
            to_flip.append(f)

    for f in to_flip:
        # Flip in place: reversing the loops reverses the winding (so the normal
        # flips) while keeping the *same* Face object and its shared edges/
        # incidence. Identity is preserved — a freshly extruded box keeps its
        # base face object, and snapshot undo stays valid.
        f.loop.reverse()
        for h in f.hole_loops:
            h.reverse()
    return to_flip
