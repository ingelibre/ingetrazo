# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fillet (round) the edges of a solid — Rafael's «herramienta de redondeo»
(review of 2026-09-10, C3).

An edge shared by two faces is replaced by a strip of quads on the
cylinder of the given radius tangent to both faces; the faces are cut back
to the tangent lines. Where the strip ends:

* at a plain vertex with one more face (the end cap of a box edge) the
  strip is cut by that face's plane and the cap gets the arc in place of
  its corner;
* at an open end (no other face) the section is perpendicular to the edge;
* where two rounded edges meet (a chain: the rim of a slab, the rounded
  outline of a prism) both strips stop on the bisecting (mitre) plane;
* where three rounded edges meet (a box corner) each strip stops at the
  other edges' tangent distance and a spherical patch fills the corner.

Everything else — four rounded edges at a vertex, extra faces at a vertex,
a rebuilt face that would leave its plane — is refused with a reason, so
the model is never left half-cut. The result is a plan applied to the
mesh in one go (:func:`apply_fillet`), which the tool wraps in a snapshot
command. Strip seams and the tangent lines are softened so the rounding
reads as one smooth surface; the arcs on end caps are curves.

The same plan is a bevel. The size can be read four ways (``measure``):
the arc's radius, the distance cut back on each face, the width of the
new face (the chord between the two tangent lines) or its depth (from
the old edge to that chord). ``profile`` shapes the section, the
superellipse of the usual bevel: 0.5 is the circular arc, 0.25 a
straight chamfer, toward 1 it fills out to the old square edge, toward 0
it hollows into a cove. One segment is a flat chamfer whatever the
profile. ``shape`` swaps the superellipse for a drawn outline — steps, a
round with support loops, a cornice or a crown moulding, see
:mod:`core.bevel_profiles`; a box corner filled with it is the
spherical product of the outline with itself, see :func:`_corner_product`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtGui import QVector3D

from core import bevel_profiles
from core.i18n import tr
from core.mesh import stamp_edge_flags

#: Faces meeting at less than this angle (or more than 180° minus it) are
#: too flat or too sharp to round.
MIN_ANGLE_DEG = 2.0
#: Rebuilt loops may leave their face plane by this much (relative).
PLANE_TOL = 1e-4
#: How the size of a fillet is read, see :func:`_tangent_distance`.
MEASURES = ("radius", "offset", "width", "depth")
#: The profile that is the circular arc — the plain fillet.
CIRCULAR = 0.5
#: How a box corner (three edges at a vertex) is closed: a curved patch
#: that follows the profile (the usual «grid fill»), or a flat cut (the
#: usual «cutoff») — each strip end capped by a flat face, see
#: :func:`_corner_cut`.
CORNERS = ("round", "cut")


#: Two computed points closer than this are the SAME point. The mesh stores
#: float32, so a box turned and squashed off the axes reaches its corners
#: through normals that carry ~1e-6 of noise: at 1e-6 the two edges of one
#: corner disagreed by 1.0–1.2e-6 m and every corner read as «conflicting
#: cuts» (issue #74, @pacaeiro). A hundredth of a millimetre is far above
#: that noise and far below any real difference between two cuts — the
#: patch matching further down already uses it.
_SAME = 1e-5


def _same(a: QVector3D, b: QVector3D) -> bool:
    return (a - b).length() < _SAME


def _key(p: QVector3D) -> tuple[int, int, int]:
    return (round(p.x() * 1e5), round(p.y() * 1e5), round(p.z() * 1e5))


def _unit(v: QVector3D) -> QVector3D | None:
    ln = v.length()
    return None if ln < 1e-12 else v / ln


def _plane_of(face) -> tuple[QVector3D, QVector3D]:
    n = face.normal()
    return QVector3D(face.vertices[0]), (n.normalized()
                                          if n.lengthSquared() > 1e-18 else n)


def _inward(face, v0, v1) -> QVector3D | None:
    """Unit vector in ``face``'s plane, perpendicular to the edge v0–v1,
    pointing INTO the face: the loop runs counter-clockwise seen from the
    normal, so the interior is to the left of the traversal."""
    loop = face.loop
    n = len(loop)
    d = None
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        if a is v0 and b is v1:
            d = v1.position - v0.position
            break
        if a is v1 and b is v0:
            d = v0.position - v1.position
            break
    if d is None:
        for hole in face.hole_loops:
            m = len(hole)
            for i in range(m):
                a, b = hole[i], hole[(i + 1) % m]
                if a is v0 and b is v1:
                    d = v1.position - v0.position
                elif a is v1 and b is v0:
                    d = v0.position - v1.position
                else:
                    continue
                break
            if d is not None:
                break
    if d is None:
        return None
    normal = face.normal()
    w = QVector3D.crossProduct(normal, d)
    return _unit(w)


@dataclass
class _EdgeRound:
    edge: object
    f1: object
    f2: object
    d: QVector3D                 # unit, v0 → v1
    w1: QVector3D                # into f1, ⊥ edge
    w2: QVector3D                # into f2, ⊥ edge
    t: float                     # tangent distance from the edge
    c_off: QVector3D             # centre offset from a point on the edge
    offsets: list = field(default_factory=list)   # section points − edge point
    sign: float = 1.0            # +1: strip normals point away from the centre
    radius: float = 0.0          # of the circular arc this edge's size gives
    ends: dict = field(default_factory=dict)      # vertex id → section points
    end_kind: dict = field(default_factory=dict)  # vertex id → "cap"/"open"/"chain"/"corner"


@dataclass
class FilletPlan:
    radius: float                # the size, read as ``measure`` says
    segments: int
    profile: float = CIRCULAR
    measure: str = "radius"
    corners: str = "round"
    shape: str | None = None
    removed_faces: list = field(default_factory=list)
    removed_edges: list = field(default_factory=list)
    # (loop positions, [hole positions], attrs, interior) of rebuilt faces
    rebuilt: list = field(default_factory=list)
    strips: list = field(default_factory=list)     # quad position loops
    patches: list = field(default_factory=list)    # triangle position loops
    soft: list = field(default_factory=list)       # (p, q) pairs to soften
    curves: list = field(default_factory=list)     # arc polylines to tag
    face_attrs: dict = field(default_factory=dict) # attrs for new faces
    # (p, q, edge flags) carried to the edge p–q once the faces are in
    flags: list = field(default_factory=list)

    @property
    def new_faces(self) -> list:
        return self.strips + self.patches


def _section_offsets(w1, w2, radius, segments):
    """Points of the perpendicular section relative to a point on the edge:
    the arc of ``radius`` tangent to both faces, ``segments`` spans from
    the tangent point on f1 to the one on f2. Also returns ``t`` (tangent
    distance) and the centre offset."""
    cos_a = max(-1.0, min(1.0, QVector3D.dotProduct(w1, w2)))
    alpha = math.acos(cos_a)                     # angle between the faces' inward dirs
    if alpha < math.radians(MIN_ANGLE_DEG) or alpha > math.pi - math.radians(MIN_ANGLE_DEG):
        return None
    t = radius / math.tan(alpha / 2.0)
    c_off = (w1 + w2) * (radius / math.sin(alpha))
    T1 = w1 * t
    T2 = w2 * t
    a = _unit(T1 - c_off)
    rb = T2 - c_off
    b = _unit(rb - a * QVector3D.dotProduct(rb, a))
    if a is None or b is None:
        return None
    phi = math.acos(max(-1.0, min(1.0, QVector3D.dotProduct(a, _unit(rb)))))
    pts = []
    for k in range(segments + 1):
        ang = phi * k / segments
        pts.append(c_off + (a * math.cos(ang) + b * math.sin(ang)) * radius)
    return t, c_off, pts


def _tangent_distance(size: float, alpha: float, measure: str) -> float:
    """How far the cut runs back on each face (the tangent distance ``t``)
    for a size read as ``measure``; ``alpha`` is the angle between the two
    faces' inward directions (90° at a box edge). The chord between the
    tangent lines is ``2·t·sin(α/2)``, its depth below the old edge
    ``t·cos(α/2)`` and the arc's radius ``t·tan(α/2)``."""
    half = alpha / 2.0
    if measure == "offset":
        return size
    if measure == "width":
        return size / (2.0 * math.sin(half))
    if measure == "depth":
        return size / math.cos(half)
    return size / math.tan(half)


def _exponent(profile: float) -> float:
    """Superellipse exponent of a profile: 0.5 → 2 (circle), 0.25 → 1
    (straight), toward 1 → ∞ (square), toward 0 → 0 (cove). The section's
    middle point sits at √profile of the way from the centre to the old
    edge."""
    return math.log(4.0) / math.log(1.0 / profile)


def _superellipse_offsets(w1, w2, t, profile, segments):
    """The section of a non-circular profile, relative to a point on the
    edge: the superellipse ``x^r + y^r = 1`` drawn in the parallelogram of
    the two tangent points and the old edge, so it stays tangent to both
    faces whatever their angle. Returns the centre offset (the corner of
    the parallelogram opposite the edge) and the points from f1 to f2."""
    T1 = w1 * t
    T2 = w2 * t
    centre = T1 + T2
    a, b = T1 - centre, T2 - centre
    e = 2.0 / _exponent(profile)
    pts = []
    for k in range(segments + 1):
        if k == 0:
            x, y = 1.0, 0.0
        elif k == segments:
            x, y = 0.0, 1.0
        else:
            ang = math.pi / 2.0 * k / segments
            x, y = math.cos(ang) ** e, math.sin(ang) ** e
        pts.append(centre + a * x + b * y)
    return centre, pts


def _outline_offsets(w1, w2, t, points):
    """A drawn outline (unit-square points, see core.bevel_profiles) as
    section offsets, through the same parallelogram as the superellipse."""
    T1 = w1 * t
    T2 = w2 * t
    centre = T1 + T2
    a, b = T1 - centre, T2 - centre
    return centre, [centre + a * x + b * y for x, y in points]


def _cut(P: QVector3D, offsets, d: QVector3D, plane) -> list | None:
    """The strip's generators through ``P + offset`` (direction ``d``) cut
    by ``plane = (point, normal)``."""
    Q, m = plane
    denom = QVector3D.dotProduct(d, m)
    if abs(denom) < 0.05:
        return None
    out = []
    for off in offsets:
        base = P + off
        s = QVector3D.dotProduct(Q - base, m) / denom
        out.append(base + d * s)
    return out


def _line_intersection_2d(P, u, Q, v, normal):
    """Point where the coplanar lines ``P + s·u`` and ``Q + r·v`` meet."""
    w = QVector3D.crossProduct(u, v)
    den = QVector3D.dotProduct(w, normal)
    if abs(den) < 1e-12:
        return None
    s = QVector3D.dotProduct(QVector3D.crossProduct(Q - P, v), normal) / den
    return P + u * s


def plan_fillet(mesh, edges, radius: float, segments: int = 8,
                profile: float = CIRCULAR, measure: str = "radius",
                corners: str = "round", shape: str | None = None):
    """Plan the rounding of ``edges`` (of ``mesh``) to the size ``radius``,
    read as ``measure`` (one of :data:`MEASURES`), with the section shaped
    by ``profile`` and box corners closed as ``corners`` says (one of
    :data:`CORNERS`) — or, with a ``shape`` from
    :data:`core.bevel_profiles.PRESETS`, the section drawn as that
    outline. Returns a :class:`FilletPlan`, or a message (str)
    saying why it cannot be done."""
    edges = [e for e in dict.fromkeys(edges)]
    if not edges:
        return tr("Pick an edge to round.")
    if radius <= 0:
        return tr("The radius must be positive.")
    if not 0.0 < profile < 1.0:
        return tr("The profile must be between 0 and 1.")
    if measure not in MEASURES:
        measure = "radius"
    if corners not in CORNERS:
        corners = "round"
    if isinstance(shape, (list, tuple)):
        if not bevel_profiles.valid(shape):
            return tr("The drawn profile must run from one face to the other.")
        shape = tuple((float(x), float(y), bool(sm)) for x, y, sm in shape)
    elif shape not in bevel_profiles.PRESETS:
        shape = None
    if shape is not None:
        outline = bevel_profiles.sample(shape, segments)
    circular = abs(profile - CIRCULAR) < 1e-9
    segments = max(int(segments), 1)
    rounds: dict[int, _EdgeRound] = {}
    for e in edges:
        faces = list(e.faces)
        if len(faces) != 2:
            return tr("Only an edge between exactly two faces can be rounded.")
        f1, f2 = faces
        d = _unit(e.v1.position - e.v0.position)
        if d is None:
            return tr("A zero-length edge cannot be rounded.")
        w1 = _inward(f1, e.v0, e.v1)
        w2 = _inward(f2, e.v0, e.v1)
        if w1 is None or w2 is None:
            return tr("Could not read the faces around the edge.")
        alpha = math.acos(max(-1.0, min(1.0, QVector3D.dotProduct(w1, w2))))
        if (alpha < math.radians(MIN_ANGLE_DEG)
                or alpha > math.pi - math.radians(MIN_ANGLE_DEG)):
            return tr("The faces meet too flat or too sharp to round.")
        t = _tangent_distance(radius, alpha, measure)
        arc_radius = t * math.tan(alpha / 2.0)
        sec = _section_offsets(w1, w2, arc_radius, segments)
        if sec is None:
            return tr("The faces meet too flat or too sharp to round.")
        t, c_off, offsets = sec
        n1 = f1.normal()
        sign = 1.0 if QVector3D.dotProduct(n1, w1 * t - c_off) >= 0 else -1.0
        if shape is not None:
            pts = outline
            if ((isinstance(shape, tuple) or shape in bevel_profiles.ASYMMETRIC)
                    and f2.normal().normalized().z()
                    > f1.normal().normalized().z() + 1e-6):
                pts = bevel_profiles.mirrored(outline)
            c_off, offsets = _outline_offsets(w1, w2, t, pts)
        elif not circular:
            c_off, offsets = _superellipse_offsets(w1, w2, t, profile, segments)
        rounds[id(e)] = _EdgeRound(e, f1, f2, d, w1, w2, t, c_off, offsets,
                                   sign, arc_radius)

    # Which rounded edges meet at each vertex.
    at_vertex: dict[int, list] = {}
    verts: dict[int, object] = {}
    for r in rounds.values():
        for v in (r.edge.v0, r.edge.v1):
            at_vertex.setdefault(id(v), []).append(r)
            verts[id(v)] = v

    # Replacement of each (face, vertex): ordered points, filled below.
    replace: dict[tuple[int, int], list] = {}
    plan = FilletPlan(radius, segments, profile, measure, corners, shape)
    patch_corners: list = []

    from core.topology import _point_in_face_solid

    def set_replacement(face, v, pts, r=None):
        """Record the points replacing ``v`` in ``face``; False on a
        conflict, the string "outside" when a point falls off the face (the
        radius is too large for it)."""
        if r is not None and len(pts) == 1 and (face is r.f1 or face is r.f2):
            # The tangent point must be ON the face: a hair back toward the
            # edge and along it lands inside when the face reaches that far
            # (a cap's arc is not tested — a concave fillet grows the cap).
            w = r.w1 if face is r.f1 else r.w2
            mid = (r.edge.v0.position + r.edge.v1.position) * 0.5
            p = pts[0]
            q = p + ((mid - p) - w * r.t) * 1e-3
            if not _point_in_face_solid(face, q):
                return "outside"
        key = (id(face), id(v))
        cur = replace.get(key)
        if cur is None:
            replace[key] = [QVector3D(p) for p in pts]
            return True
        # Merge: the same single point is fine; a section beats a point
        # that lies on it; anything else is a conflict.
        if len(pts) == 1 and any(_same(p, pts[0]) for p in cur):
            return True
        if len(cur) == 1 and any(_same(p, cur[0]) for p in pts):
            replace[key] = [QVector3D(p) for p in pts]
            return True
        if len(cur) == len(pts) and all(_same(a, b) for a, b in zip(cur, pts)):
            return True
        return False

    for vid, group in at_vertex.items():
        v = verts[vid]
        faces_here = set(v.faces())
        if len(group) == 1:
            r = group[0]
            caps = [g for g in faces_here if g is not r.f1 and g is not r.f2]
            if len(caps) > 1:
                return tr("The corner at {p} has too many faces to round.",
                          p=_fmt(v.position))
            if caps:
                plane = _plane_of(caps[0])
                kind = "cap"
            else:
                plane = (QVector3D(v.position), r.d)
                kind = "open"
            sec = _cut(v.position, r.offsets, r.d, plane)
            if sec is None:
                return tr("The end face at {p} is too oblique to the edge.",
                          p=_fmt(v.position))
            r.ends[vid] = sec
            r.end_kind[vid] = kind
            outcome = [set_replacement(r.f1, v, [sec[0]], r),
                       set_replacement(r.f2, v, [sec[-1]], r)]
            if caps:
                outcome.append(set_replacement(caps[0], v, sec, r))
            if "outside" in outcome:
                return tr("The radius is too large for the face at {p}.",
                          p=_fmt(v.position))
            if not all(outcome):
                return tr("Conflicting cuts at {p}.", p=_fmt(v.position))
        elif len(group) == 2:
            ra, rb = group
            allowed = {id(ra.f1), id(ra.f2), id(rb.f1), id(rb.f2)}
            if any(id(g) not in allowed for g in faces_here):
                return tr("The corner at {p} has too many faces to round.",
                          p=_fmt(v.position))
            u = _unit(ra.edge.other(v).position - v.position)
            u2 = _unit(rb.edge.other(v).position - v.position)
            m = _unit(u - u2)
            if m is None:
                return tr("The two edges at {p} fold back on each other.",
                          p=_fmt(v.position))
            plane = (QVector3D(v.position), m)
            sec = _cut(v.position, ra.offsets, ra.d, plane)
            if sec is None:
                return tr("The edges at {p} meet too sharply to round.",
                          p=_fmt(v.position))
            ra.ends[vid] = sec
            ra.end_kind[vid] = "chain"
            # The neighbour stops on the same section, read from its side.
            if rb.f1 is ra.f1 or rb.f2 is ra.f2:
                sec_b = list(sec)
            elif rb.f1 is ra.f2 or rb.f2 is ra.f1:
                sec_b = list(reversed(sec))
            else:
                return tr("The edges at {p} share no face.", p=_fmt(v.position))
            rb.ends[vid] = sec_b
            rb.end_kind[vid] = "chain"
            outcome = [set_replacement(ra.f1, v, [sec[0]], ra),
                       set_replacement(ra.f2, v, [sec[-1]], ra),
                       set_replacement(rb.f1, v, [sec_b[0]], rb),
                       set_replacement(rb.f2, v, [sec_b[-1]], rb)]
            if "outside" in outcome:
                return tr("The radius is too large for the face at {p}.",
                          p=_fmt(v.position))
            if not all(outcome):
                return tr("Conflicting cuts at {p}.", p=_fmt(v.position))
        elif len(group) == 3:
            allowed = set()
            for r in group:
                allowed.add(id(r.f1))
                allowed.add(id(r.f2))
            if any(id(g) not in allowed for g in faces_here):
                return tr("The corner at {p} has too many faces to round.",
                          p=_fmt(v.position))
            sections = []
            for r in group:
                cut_pts = []
                for f, w in ((r.f1, r.w1), (r.f2, r.w2)):
                    other = [q for q in group if q is not r and (q.f1 is f or q.f2 is f)]
                    if len(other) != 1:
                        return tr("The corner at {p} is not a simple corner.",
                                  p=_fmt(v.position))
                    q = other[0]
                    wq = q.w1 if q.f1 is f else q.w2
                    normal = f.normal().normalized()
                    hit = _line_intersection_2d(v.position + w * r.t, r.d,
                                                v.position + wq * q.t, q.d, normal)
                    if hit is None:
                        return tr("The corner at {p} is not a simple corner.",
                                  p=_fmt(v.position))
                    cut_pts.append(hit)
                s1 = QVector3D.dotProduct(cut_pts[0] - v.position, r.d)
                s2 = QVector3D.dotProduct(cut_pts[1] - v.position, r.d)
                if abs(s1 - s2) > 1e-3 * max(1.0, r.t):
                    return tr("The corner at {p} is too skewed to round.",
                              p=_fmt(v.position))
                if abs(s1) > r.edge.length() * 0.5 + 1e-9:
                    return tr("The radius is too large for the edge at {p}.",
                              p=_fmt(v.position))
                P = v.position + r.d * s1
                sec = [P + off for off in r.offsets]
                r.ends[vid] = sec
                r.end_kind[vid] = "corner"
                sections.append(sec)
                outcome = [set_replacement(r.f1, v, [sec[0]], r),
                           set_replacement(r.f2, v, [sec[-1]], r)]
                if "outside" in outcome:
                    return tr("The radius is too large for the face at {p}.",
                              p=_fmt(v.position))
                if not all(outcome):
                    return tr("Conflicting cuts at {p}.", p=_fmt(v.position))
            patch_corners.append((group, sections, v))
        else:
            return tr("More than three rounded edges meet at {p}.",
                      p=_fmt(v.position))

    # Rebuild every face that loses a vertex.
    touched: dict[int, object] = {}
    for vid, v in verts.items():
        for f in v.faces():
            touched[id(f)] = f
    replaced_vertices = set(verts)

    def rebuilt_loop(face, loop):
        out = []
        n = len(loop)
        for i, x in enumerate(loop):
            if id(x) not in replaced_vertices:
                out.append(QVector3D(x.position))
                continue
            seq = replace.get((id(face), id(x)))
            if seq is None:
                return None
            if len(seq) > 1:
                prev = loop[i - 1].position
                nxt = loop[(i + 1) % n].position
                straight = (prev - seq[0]).length() + (nxt - seq[-1]).length()
                flipped = (prev - seq[-1]).length() + (nxt - seq[0]).length()
                if flipped < straight:
                    seq = list(reversed(seq))
            out.extend(QVector3D(p) for p in seq)
        # Drop consecutive duplicates.
        clean = []
        for p in out:
            if not clean or (p - clean[-1]).length() > 1e-7:
                clean.append(p)
        if len(clean) > 1 and (clean[0] - clean[-1]).length() <= 1e-7:
            clean.pop()
        return clean

    for f in touched.values():
        p0, normal = _plane_of(f)
        loop = rebuilt_loop(f, f.loop)
        if loop is None or len(loop) < 3:
            return tr("A face would collapse — the radius is too large.")
        holes = []
        for h in f.hole_loops:
            hl = rebuilt_loop(f, h)
            if hl is None or len(hl) < 3:
                return tr("A face would collapse — the radius is too large.")
            holes.append(hl)
        span = max((p - p0).length() for p in loop) or 1.0
        for p in loop:
            if abs(QVector3D.dotProduct(p - p0, normal)) > PLANE_TOL * max(1.0, span):
                return tr("Rounding would bend the face at {p}.", p=_fmt(p))
        plan.removed_faces.append(f)
        plan.rebuilt.append((loop, holes, dict(f.attrs), bool(f.interior)))

    # Strips.
    for r in rounds.values():
        a = r.ends.get(id(r.edge.v0))
        b = r.ends.get(id(r.edge.v1))
        if a is None or b is None:
            return tr("Internal error: an edge end was not resolved.")
        # Too short: the two ends cross.
        along = QVector3D.dotProduct(b[0] - a[0], r.d)
        if along <= 1e-6:
            return tr("The radius is too large for the edge at {p}.",
                      p=_fmt(r.edge.v0.position))
        n = len(a) - 1
        C_mid = (a[0] + b[0]) * 0.5 - r.w1 * r.t + r.c_off
        # One winding for the whole strip, read off the chord quad: every
        # piece is built the same way round, and the chord always faces
        # away from the centre — a step's riser need not.
        chord = [a[0], a[n], b[n], b[0]]
        flip = _oriented(chord, C_mid, r.sign)[0] is not chord[0]
        for k in range(n):
            quad = [a[k], a[k + 1], b[k + 1], b[k]]
            plan.strips.append(list(reversed(quad)) if flip else quad)
        if shape is None:
            for k in range(1, n):
                plan.soft.append((a[k], b[k]))
            plan.soft.append((a[0], b[0]))
            plan.soft.append((a[n], b[n]))
        for vid, sec in r.ends.items():
            kind = r.end_kind[vid]
            if shape is not None:
                if kind in ("cap", "open"):
                    plan.curves.append([QVector3D(p) for p in sec])
            elif kind == "chain" or (kind == "corner" and corners == "round"):
                for k in range(n):
                    plan.soft.append((sec[k], sec[k + 1]))
            else:
                plan.curves.append([QVector3D(p) for p in sec])
        plan.face_attrs.setdefault("strip", _shared_attrs(r.f1, r.f2))
        plan.removed_edges.append(r.edge)

    # Corner patches.
    for group, sections, v in patch_corners:
        if corners == "cut":
            faces = _corner_cut(group, sections, v)
            # A drawn outline whose sections share sides (a staircase) has
            # no notch to cut: its own corner closes it instead.
            if faces is not None and (shape is None or _closes(faces, sections)):
                plan.patches.extend(faces)
                continue
            if shape is None:
                return tr("Could not close the corner at {p}.",
                          p=_fmt(v.position))
        if shape is not None:
            # The outline's own corner when it closes cleanly, else the
            # blended grid, else the flat cut — never a hole.
            if shape == "steps":
                faces = _corner_steps(group, sections, outline)
            else:
                faces = _corner_product(group, sections, outline, plan.strips)
            if faces is not None and not _closes(faces, sections):
                split, splits = _split_on_sides(faces, sections)
                if _closes(split, sections, splits):
                    faces = split
                    _split_strips(plan, splits)
                else:
                    faces = None
            if faces is None:
                faces, _soft = _corner_patch(group, sections, 0.0, segments,
                                             drawn=True)
                if faces is not None:
                    faces = _wound_like(faces, plan.strips)
                if faces is not None and not _closes(faces, sections):
                    faces = None
            if faces is None:
                faces = _corner_cut(group, sections, v)
            if faces is None:
                return tr("Could not close the corner at {p}.",
                          p=_fmt(v.position))
            plan.patches.extend(faces)
            continue
        corner_radius = sum(r.radius for r in group) / len(group)
        tris, soft = _corner_patch(group, sections, corner_radius, segments,
                                   None if circular else profile)
        if tris is None:
            return tr("Could not close the corner at {p}.",
                      p=_fmt(sections[0][0]))
        plan.patches.extend(tris)
        plan.soft.extend(soft)

    if shape is not None:
        plan.soft = _smooth_seams(plan)

    # Old edges that lose an endpoint go too (their faces are rebuilt on
    # the new points); a free edge (no face) at the vertex stays.
    seen = {id(e) for e in plan.removed_edges}
    for v in verts.values():
        for e in v.edges:
            if id(e) in seen or not e.faces:
                continue
            seen.add(id(e))
            plan.removed_edges.append(e)
    return plan


def _shared_attrs(f1, f2) -> dict:
    """The new faces take the material when both neighbours share it."""
    a, b = f1.attrs or {}, f2.attrs or {}
    keys = ("color", "texture", "mat", "opacity")
    if all(a.get(k) == b.get(k) for k in keys):
        return {k: a[k] for k in keys if k in a}
    return {}


def _fmt(p: QVector3D) -> str:
    return f"({p.x():.2f}, {p.y():.2f}, {p.z():.2f})"


def _newell(pts) -> QVector3D:
    n = QVector3D()
    m = len(pts)
    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        n += QVector3D((a.y() - b.y()) * (a.z() + b.z()),
                       (a.z() - b.z()) * (a.x() + b.x()),
                       (a.x() - b.x()) * (a.y() + b.y()))
    return n


def _oriented(loop, centre: QVector3D, sign: float) -> list:
    """``loop`` wound so its normal points away from ``centre`` (times
    ``sign``): the strip's outside matches the faces it joins."""
    c = QVector3D()
    for p in loop:
        c += p
    c /= float(len(loop))
    n = _newell(loop)
    if QVector3D.dotProduct(n, c - centre) * sign < 0:
        return list(reversed(loop))
    return list(loop)


#: New edges between faces meeting at less than this read as one surface.
SMOOTH_DEG = 30.0


def _smooth_seams(plan) -> list:
    """The edges of a drawn outline's faces to soften: those whose two
    faces meet at less than :data:`SMOOTH_DEG` — the curve of a moulding
    reads smooth, a step keeps its edge."""
    normals: dict = {}
    loops = [lp for lp, _h, _a, _i in plan.rebuilt] + plan.strips + plan.patches
    for lp in loops:
        n = _unit(_newell(lp))
        if n is None:
            continue
        m = len(lp)
        for i in range(m):
            k = frozenset((_key(lp[i]), _key(lp[(i + 1) % m])))
            normals.setdefault(k, []).append((n, lp[i], lp[(i + 1) % m]))
    cos_max = math.cos(math.radians(SMOOTH_DEG))
    soft = []
    for entries in normals.values():
        if len(entries) != 2:
            continue
        (n1, p, q), (n2, _p, _q) = entries
        if QVector3D.dotProduct(n1, n2) > cos_max:
            soft.append((p, q))
    return soft


def _corner_steps(group, sections, outline) -> list | None:
    """Fill a box corner where three staircases meet: what all three keep
    is a stepped pyramid. In the corner's frame (centre ``O``, corner
    points ``cX``, ``cY``, ``cZ``) the corner is a cube of ``k³`` cells,
    ``k`` the steps; a cell stays when, for each pair of its indices,
    ``a + b < k − 1`` — the staircase of each edge seen along it. The
    faces between kept and cut cells are the corner: squares a step wide,
    so their sides meet the strips' steps one for one."""
    k = (len(outline) - 1) // 2
    if k < 1:
        return None

    def meet(sa, sb):
        for i in (0, -1):
            for j in (0, -1):
                if _same(sa[i], sb[j]):
                    return sa[i]
        return None
    s1, s2, s3 = sections
    cX, cY, cZ = meet(s2, s3), meet(s3, s1), meet(s1, s2)
    if cX is None or cY is None or cZ is None:
        return None
    centre = QVector3D()
    for r, sec in zip(group, sections):
        centre += sec[0] - r.w1 * r.t + r.c_off
    centre /= 3.0
    A, B, C = cX - centre, cY - centre, cZ - centre

    def at(a, b, c):
        return centre + A * (a / k) + B * (b / k) + C * (c / k)

    def kept(a, b, c):
        if min(a, b, c) < 0:
            return None                  # past a section: the strips' side
        if max(a, b, c) >= k:
            return False
        return a + b < k - 1 and a + c < k - 1 and b + c < k - 1
    faces = []
    for a in range(k):
        for b in range(k):
            for c in range(k):
                if not kept(a, b, c):
                    continue
                for axis in range(3):
                    n = [a, b, c]
                    n[axis] += 1
                    if kept(*n) is not False:
                        continue
                    # The cell's side toward the cut neighbour.
                    lo = [a, b, c]
                    lo[axis] += 1
                    u, w = [i for i in range(3) if i != axis]
                    quad = []
                    for du, dw in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        q = list(lo)
                        q[u] += du
                        q[w] += dw
                        quad.append(at(*q))
                    mid = at(*[x + 0.5 for x in n])
                    faces.append(_facing(quad, mid, group[0].sign))
    return faces


def _corner_product(group, sections, outline, strips) -> list | None:
    """Fill a box corner with a drawn outline: the spherical product of the
    outline with itself, the way a sphere is the product of two circles.

    In the frame of the corner's centre ``O`` and its three corner points
    ``cX``, ``cY``, ``cZ`` (where two sections meet), with the outline
    ``(x(s), y(s))`` from ``(1, 0)`` to ``(0, 1)``, a point is::

        O + (cX − O)·x(u)·x(v) + (cY − O)·x(u)·y(v) + (cZ − O)·y(u)

    Its three sides are the outline itself — ``u = 0`` runs from cX to cY,
    ``v = 0`` from cX to cZ, ``v = 1`` from cY to cZ — so it meets the
    three strip ends exactly: a round gives the sphere, steps a stepped
    pyramid of flat faces, a moulding turns the corner. Which edge is the
    pole and which way the outline reads is found by trying each
    arrangement against the real sections; None when none fits (an
    asymmetric outline set the wrong way round at this corner), and the
    caller blends the corner instead."""
    def meet(sa, sb):
        for i in (0, -1):
            for j in (0, -1):
                if _same(sa[i], sb[j]):
                    return sa[i]
        return None
    s1, s2, s3 = sections
    corner_pts = [meet(s2, s3), meet(s3, s1), meet(s1, s2)]  # opposite s1, s2, s3
    if any(c is None for c in corner_pts):
        return None
    centre = QVector3D()
    for r, sec in zip(group, sections):
        centre += sec[0] - r.w1 * r.t + r.c_off
    centre /= 3.0

    def matches(sec, pts):
        if len(sec) != len(pts):
            return False
        return (all(_same(a, b) for a, b in zip(sec, pts))
                or all(_same(a, b) for a, b in zip(sec, reversed(pts))))

    for read in (outline, bevel_profiles.mirrored(outline)):
        m = len(read) - 1
        for pole in range(3):
            cZ = corner_pts[pole]
            sides = [i for i in range(3) if i != pole]
            for swap in (False, True):
                ix, iy = (sides[1], sides[0]) if swap else (sides[0], sides[1])
                cX, cY = corner_pts[ix], corner_pts[iy]
                A, B, C = cX - centre, cY - centre, cZ - centre

                def at(u, v):
                    xu, yu = read[u]
                    xv, yv = read[v]
                    return centre + A * (xu * xv) + B * (xu * yv) + C * yu
                row0 = [at(0, v) for v in range(m + 1)]
                col0 = [at(u, 0) for u in range(m + 1)]
                colm = [at(u, m) for u in range(m + 1)]
                # The pole edge's section runs cX–cY (it is opposite cZ),
                # the one opposite cY runs cX–cZ, the one opposite cX cY–cZ.
                if not (matches(sections[pole], row0) and matches(sections[iy], col0)
                        and matches(sections[ix], colm)):
                    continue
                grid = [[at(u, v) for v in range(m + 1)] for u in range(m + 1)]
                faces = []
                for u in range(m):
                    for v in range(m):
                        quad = [grid[u][v], grid[u + 1][v],
                                grid[u + 1][v + 1], grid[u][v + 1]]
                        faces.extend(_cells(quad))
                return _wound_like(faces, strips)
    return None


def _split_on_sides(faces, sections):
    """Where an outline runs along an axis (a step's tread), corner points
    can land in the middle of another face's side: put each such point
    into the sides it lies on. Returns the faces and, for each section
    side that took points, those points in order — the strip beside the
    corner needs them too."""
    pts: dict = {}
    for f in faces:
        for q in f:
            pts.setdefault(_key(q), q)
    pts = list(pts.values())

    def inner(a, b):
        d = b - a
        ln2 = d.lengthSquared()
        if ln2 < 1e-18:
            return []
        hits = []
        for q in pts:
            t_ = QVector3D.dotProduct(q - a, d) / ln2
            if 1e-6 < t_ < 1 - 1e-6 and (a + d * t_ - q).length() < 1e-7:
                hits.append((t_, q))
        return [QVector3D(q) for _t, q in sorted(hits, key=lambda h: h[0])]

    out = []
    for f in faces:
        g = []
        m = len(f)
        for i in range(m):
            g.append(f[i])
            g.extend(inner(f[i], f[(i + 1) % m]))
        out.append(g)
    splits = {}
    for sec in sections:
        for i in range(len(sec) - 1):
            mids = inner(sec[i], sec[i + 1])
            if mids:
                splits[(_key(sec[i]), _key(sec[i + 1]))] = (sec[i], sec[i + 1], mids)
    return out, splits


def _split_strips(plan, splits) -> None:
    """Give the strips beside a corner the points its faces put on their
    shared sides."""
    if not splits:
        return
    table = {}
    for a_k, b_k in list(splits):
        a, b, mids = splits[(a_k, b_k)]
        table[(a_k, b_k)] = mids
        table[(b_k, a_k)] = list(reversed(mids))
    new = []
    for lp in plan.strips:
        g = []
        m = len(lp)
        for i in range(m):
            g.append(lp[i])
            g.extend(QVector3D(q) for q in
                     table.get((_key(lp[i]), _key(lp[(i + 1) % m])), ()))
        new.append(g)
    plan.strips = new


def _closes(faces, sections, splits=None) -> bool:
    """Whether a corner's faces close it exactly: every side they leave
    open is a side of the three sections (split where ``splits`` says),
    each such side is left open once, and no side is shared by more than
    two faces."""
    count: dict = {}
    for f in faces:
        m = len(f)
        for i in range(m):
            k = frozenset((_key(f[i]), _key(f[(i + 1) % m])))
            if len(k) < 2:
                return False
            count[k] = count.get(k, 0) + 1
    uses: dict = {}
    for sec in sections:
        for i in range(len(sec) - 1):
            run = [sec[i]] + list((splits or {}).get(
                (_key(sec[i]), _key(sec[i + 1])), (None, None, []))[2]) + [sec[i + 1]]
            for p, q in zip(run, run[1:]):
                k = frozenset((_key(p), _key(q)))
                if len(k) == 2:
                    uses[k] = uses.get(k, 0) + 1
    # A side two sections share (a step lying where two section planes
    # cross) is closed by the two strips themselves: nothing to cover.
    rim = {k for k, n in uses.items() if n == 1}
    open_sides = {k for k, n in count.items() if n == 1}
    return (all(n <= 2 for n in count.values()) and open_sides == rim
            and not any(k in count for k, n in uses.items() if n > 1))


def _cells(quad) -> list:
    """One grid cell as faces: the quad when it is flat, two triangles
    when it is not, fewer when corners coincide (near the pole, or where
    the outline runs along an axis); nothing when it has no area."""
    pts = []
    for p in quad:
        if not any(_same(p, q) for q in pts):
            pts.append(p)
    if len(pts) < 3:
        return []
    if len(pts) == 3:
        return [pts] if _newell(pts).length() > 1e-12 else []
    n = _unit(_newell(pts))
    if n is not None and all(abs(QVector3D.dotProduct(p - pts[0], n)) < 1e-7
                             for p in pts):
        return [pts]
    out = []
    for tri in ([pts[0], pts[1], pts[2]], [pts[0], pts[2], pts[3]]):
        if _newell(tri).length() > 1e-12:
            out.append(tri)
    return out


def _wound_like(faces, strips) -> list:
    """``faces`` (all wound the same way, a grid) turned to match the strips
    they meet: a side they share must run the opposite way in each."""
    strip_sides = {}
    for lp in strips:
        m = len(lp)
        for i in range(m):
            strip_sides[(_key(lp[i]), _key(lp[(i + 1) % m]))] = True
    for f in faces:
        m = len(f)
        for i in range(m):
            a, b = _key(f[i]), _key(f[(i + 1) % m])
            if (a, b) in strip_sides:
                return [list(reversed(x)) for x in faces]
            if (b, a) in strip_sides:
                return faces
    return faces


def _lerp(p: QVector3D, q: QVector3D, s: float) -> QVector3D:
    return p + (q - p) * s


def _corner_cut(group, sections, v) -> list | None:
    """The flat close of a box corner — the usual bevel's «cutoff»: each
    strip's end section is capped by one flat face reaching down into the
    solid, and where those caps do not meet in one point a centre face
    closes the gap between them.

    Under each corner point (where two sections meet) a «bottom» point is
    placed along the line where the two section planes cross, pointing
    into the solid, at the mean of the two sections' heights over √2 —
    the height being the distance from a section's centre to the old
    edge. At a box corner that lands all three on the centre of the
    corner, so the three caps meet there and no centre face is needed.
    Each bottom point lies on both section planes it is built from, so
    every cap is flat and shares its sides with its neighbours and the
    centre face: the corner stays watertight. Faces look toward the old
    tip, the side the material was taken from."""
    sign = group[0].sign
    tip = QVector3D(v.position)
    out = QVector3D()
    for f in v.faces():
        out += f.normal()
    corners: list = []                 # [point, [round, round]]
    for r, sec in zip(group, sections):
        for p in (sec[0], sec[-1]):
            for c in corners:
                if _same(c[0], p):
                    c[1].append(r)
                    break
            else:
                corners.append([QVector3D(p), [r]])
    if len(corners) != 3 or any(len(rs) != 2 for _p, rs in corners):
        return None
    bottoms = []
    for p, (ra, rb) in corners:
        down = _unit(QVector3D.crossProduct(ra.d, rb.d))
        if down is None:
            return None
        if QVector3D.dotProduct(down, out) > 0:
            down = -down
        depth = (ra.c_off.length() + rb.c_off.length()) / 2.0 / math.sqrt(2.0)
        bottoms.append(p + down * depth)

    def bottom_at(q):
        for (p, _rs), b in zip(corners, bottoms):
            if _same(p, q):
                return b
        return None
    centre = not (_same(bottoms[0], bottoms[1]) and _same(bottoms[0], bottoms[2]))
    faces = []
    for sec in sections:
        loop = [QVector3D(p) for p in sec]
        if centre:
            loop += [bottom_at(sec[-1]), bottom_at(sec[0])]
        else:
            loop.append(bottoms[0])
        faces.append(_facing(loop, tip, sign))
    if centre:
        faces.append(_facing(bottoms, tip, sign))
    return faces


def _facing(loop, target: QVector3D, sign: float) -> list:
    """``loop`` wound so its normal points toward ``target`` (times
    ``sign``: away from it at a hollow corner)."""
    c = QVector3D()
    for p in loop:
        c += p
    c /= float(len(loop))
    if QVector3D.dotProduct(_newell(loop), target - c) * sign < 0:
        return list(reversed(loop))
    return list(loop)


def _corner_patch(group, sections, radius, segments, profile=None,
                  drawn=False):
    """Triangles filling the corner between three strip ends (a spherical
    triangle for a box corner). Boundary rows ARE the strips' sections, so
    the patch is watertight; the inside is interpolated on the sphere
    about the mean centre — or, with a non-circular ``profile``, on the
    superellipsoid spanned by the centre and the three corner points, the
    same shape the sections are drawn with. A ``drawn`` outline has no
    such surface: its inside is blended from the three sections (the
    usual grid fill), each point the mean of the three straight rows
    through it, so every side follows its own outline exactly."""
    n = len(sections[0]) - 1 if drawn else segments
    if any(len(sec) != n + 1 for sec in sections):
        return None, None
    # Corner points: where two sections meet (same position).
    r1, r2, r3 = group
    s1, s2, s3 = sections

    def meet(sa, sb):
        for i in (0, -1):
            for j in (0, -1):
                if (sa[i] - sb[j]).length() < 1e-5:
                    return sa[i]
        return None
    c12, c23, c31 = meet(s1, s2), meet(s2, s3), meet(s3, s1)
    if c12 is None or c23 is None or c31 is None:
        return None, None
    # Sphere centre: the mean of the three sections' own centres.
    centre = QVector3D()
    for r, s in zip(group, sections):
        centre += s[0] - r.w1 * r.t + r.c_off
    centre /= 3.0

    def unit_from(p):
        return _unit(p - centre)
    ea, eb, ec = unit_from(c12), unit_from(c23), unit_from(c31)
    if ea is None or eb is None or ec is None:
        return None, None

    def oriented_arc(sec, start, end):
        if (sec[0] - start).length() < 1e-5 and (sec[-1] - end).length() < 1e-5:
            return list(sec)
        if (sec[-1] - start).length() < 1e-5 and (sec[0] - end).length() < 1e-5:
            return list(reversed(sec))
        return None
    # Which section runs between which corners.
    arcs = {}
    for s in (s1, s2, s3):
        for name, (p, q) in (("ab", (c12, c23)), ("bc", (c23, c31)), ("ac", (c12, c31))):
            a = oriented_arc(s, p, q)
            if a is not None and name not in arcs:
                arcs[name] = a
    if len(arcs) != 3:
        return None, None

    def f(i):
        return math.sin(i * math.pi / (2.0 * n))
    e = 2.0 / _exponent(profile) if profile is not None else 0.0
    grid: dict[tuple[int, int], QVector3D] = {}
    for i in range(n + 1):
        for j in range(n + 1 - i):
            k = n - i - j
            if k == 0:                      # A→B edge: i = n..0, j = 0..n
                grid[(i, j)] = arcs["ab"][j]
            elif i == 0:                    # B→C edge: j = n..0
                grid[(i, j)] = arcs["bc"][k]
            elif j == 0:                    # A→C edge: i = n..0
                grid[(i, j)] = arcs["ac"][k]
            elif drawn:
                ab, bc, ac = arcs["ab"], arcs["bc"], arcs["ac"]
                rows = (_lerp(ac[n - i], ab[n - i], j / (n - i)),
                        _lerp(bc[n - j], ab[j], i / (n - j)),
                        _lerp(bc[k], ac[k], i / (n - k)))
                grid[(i, j)] = (rows[0] + rows[1] + rows[2]) / 3.0
            elif profile is not None:
                wa, wb, wc = f(i), f(j), f(k)
                ln = math.sqrt(wa * wa + wb * wb + wc * wc)
                grid[(i, j)] = (centre + (c12 - centre) * (wa / ln) ** e
                                + (c23 - centre) * (wb / ln) ** e
                                + (c31 - centre) * (wc / ln) ** e)
            else:
                dirn = _unit(ea * f(i) + eb * f(j) + ec * f(k))
                grid[(i, j)] = centre + dirn * radius
    tris = []
    sign = group[0].sign
    for i in range(n):
        for j in range(n - i):
            tris.append(_oriented([grid[(i, j)], grid[(i + 1, j)], grid[(i, j + 1)]],
                                  centre, sign))
            if i + j + 1 < n:
                tris.append(_oriented([grid[(i + 1, j)], grid[(i + 1, j + 1)],
                                       grid[(i, j + 1)]], centre, sign))
    soft = []
    for (i, j), p in grid.items():
        for di, dj in ((1, 0), (0, 1), (-1, 1)):
            q = grid.get((i + di, j + dj))
            if q is not None:
                soft.append((p, q))
    return tris, soft


def apply_fillet(mesh, plan: FilletPlan) -> None:
    """Apply a plan to the mesh: remove the cut faces and edges, add the
    rebuilt faces, the strips and the patches, soften the seams, tag the
    end arcs as curves."""
    for f in plan.removed_faces:
        mesh.remove_face(f)
    for e in plan.removed_edges:
        if not e.faces:
            mesh.remove_edge(e)
    for loop, holes, attrs, interior in plan.rebuilt:
        face = mesh.add_face(loop, holes)
        face.attrs = dict(attrs)
        face.interior = interior
    attrs = plan.face_attrs.get("strip", {})
    for loop in plan.new_faces:
        face = mesh.add_face(loop)
        if attrs:
            face.attrs = dict(attrs)
    for p, q, flags in plan.flags:
        a, b = mesh.vertex_at(p), mesh.vertex_at(q)
        e = mesh.find_edge(a, b) if (a is not None and b is not None) else None
        if e is not None:
            stamp_edge_flags(e, flags)
    for p, q in plan.soft:
        a, b = mesh.vertex_at(p), mesh.vertex_at(q)
        e = mesh.find_edge(a, b) if (a is not None and b is not None) else None
        if e is not None:
            e.soft = True
    for pts in plan.curves:
        mesh.tag_curve(pts, closed=False)
