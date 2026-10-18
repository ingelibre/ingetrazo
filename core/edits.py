# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Edit operations that turn drawn segments into history commands.

This is the bridge between the pure geometry planner in :mod:`core.topology`
and the undo/redo commands in :mod:`core.history`. Tools hand it the raw
segments the user drew; it returns a single reversible command that:

- splits existing edges the new segments cross (the classic auto-split),
- breaks each new segment at those crossings,
- welds coincident edges (via ``AddEdgeCommand``'s merge), and
- optionally auto-faces any planar cycle the new sub-edges close.

Segments are processed in order against a running simulation of the scene's
edge list, so a batch (e.g. a rectangle's four edges) splits correctly even
when later segments cross edges created by earlier ones.

Kept in its own module to avoid an import cycle: ``history`` imports
``topology``, so the command-building glue can't live in either of them.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

from PySide6.QtGui import QVector3D

from core.geometry import Edge, Face
from core.history import (
    AddEdgeCommand,
    AddFaceCommand,
    Command,
    CompoundCommand,
    DeleteEdgesCommand,
    DeleteFaceCommand,
    SnapshotCompound,
)
from core.topology import (
    face_exists,
    find_chord_split,
    find_cycles_through,
    find_duplicate_edge,
    is_planar,
    plan_edge_split,
    split_edge_in_faces,
)

Segment = tuple[QVector3D, QVector3D]


def plan_edge_commands(
    scene,
    segments: Sequence[Segment],
    detect_faces: bool = True,
    eye=None,
) -> list[Command]:
    """Build the ordered command list to add ``segments`` to ``scene``.

    Mirrors what each emitted command will do to the scene in a local
    ``simulated`` edge list, so planning and execution stay in lock-step.
    Returns a flat list (callers wrap it, possibly alongside their own
    commands such as a tool-managed face, in a single ``CompoundCommand``).
    """
    commands: list[Command] = []
    simulated: list[Edge] = list(scene.edges)
    faces_snapshot: list[Face] = list(scene.faces)
    near = _Nearby(simulated, faces_snapshot)
    from core.topology import KeyMemo
    near.key = KeyMemo()            # nothing moves while a plan is made

    for a, b in segments:
        # The searches only look at what can touch the segment (a box test
        # far wider than the welding tolerance); the plan's own edits still
        # go to the full lists. Inside the Plaza's 25 797-face group every
        # stroke tested every edge and face — ~1 s each (09-10).
        new_segments, edge_cuts = plan_edge_split(
            near.edges(simulated, a, b), a, b)

        # Replace each crossed existing edge with its two sub-edges.
        for edge, point in edge_cuts.items():
            # Splitting an edge, not erasing it — the sub-edges keep any face's
            # boundary intact, so don't cascade-delete faces here.
            commands.append(DeleteEdgesCommand([edge], cascade_faces=False))
            if edge in simulated:
                simulated.remove(edge)
            # Sub-edges inherit the split edge's curve/soft flags, so cutting a
            # circle leaves its pieces selectable as the same curve entity.
            e_soft = getattr(edge, "soft", False) or None
            e_curve = getattr(edge, "curve", None)
            for sa, sb in ((edge.a, point), (point, edge.b)):
                if find_duplicate_edge(near.edges(simulated, sa, sb),
                                       sa, sb) is None:
                    commands.append(
                        AddEdgeCommand(sa, sb, soft=e_soft, curve=e_curve))
                    simulated.append(Edge(sa, sb))

            # Carry the split into faces sharing this edge — but not the face
            # the drawn segment chord-splits, which inserts the point itself.
            # This is what makes a gable wall gain the ridge apex (and fill its
            # triangular gap) when the ridge is later moved up.
            #
            # NOT gated on ``detect_faces``. That flag says "I add my own
            # faces, don't auto-close cycles for me" — it is about FACING, and
            # bundling this in with it left the mesh non-manifold: a door drawn
            # on a wall with the Rectangle tool split the wall's bottom edge in
            # three while the FLOOR kept the original long one, so the two no
            # longer shared it and the box stopped being closed (Marco's
            # cubo.igz: four edges carrying one face each, all on that line).
            # Everything volumetric then quietly stops working on it —
            # orient_outward has no volume to judge windings against, the
            # push's recess rule reads the wrong sign, the coplanar merge
            # dissolves the door back into the wall. The same door drawn with
            # three lines left the box closed, which is what gave it away.
            for f, new_verts in split_edge_in_faces(
                near.faces(faces_snapshot, edge.a, edge.b),
                edge.a, edge.b, point, skip_endpoints=(a, b)
            ):
                # Same face, one collinear vertex richer: it keeps its own
                # paint, exactly as it stands (the texture's world→UV map
                # included — the plane has not moved).
                keep = dict(f.attrs) if f.attrs else None
                commands.append(DeleteFaceCommand(f))
                commands.append(
                    AddFaceCommand(new_verts, auto=False,
                                   holes=f.holes or None, attrs=keep)
                )
                faces_snapshot[faces_snapshot.index(f)] = Face(
                    list(new_verts), [list(h) for h in f.holes],
                    attrs=keep
                )

        # Add the new segment's pieces (welding duplicates), auto-facing.
        for sa, sb in new_segments:
            already = find_duplicate_edge(near.edges(simulated, sa, sb),
                                          sa, sb)
            # Always emit the add: AddEdgeCommand welds, so a duplicate is a
            # no-op, but face detection below must still run (drawing over an
            # existing edge can still close a new face).
            commands.append(AddEdgeCommand(sa, sb))
            if already is None:
                simulated.append(Edge(sa, sb))
            if detect_faces:
                _plan_faces(commands, faces_snapshot, simulated, sa, sb, eye,
                            near)

    return commands


class _Nearby:
    """Box filter for the planner's searches. Every edge and face is boxed
    once per plan, in one NumPy array (the plan's own simulated pieces are
    boxed on first sight); a search then gets, in their original order, only
    those whose box, grown by a margin far beyond the 0.1 mm welding
    tolerance, reaches the segment. Anything that can cross, contain or
    duplicate the segment is kept, so the plan is the one the full lists
    give (tests/test_planner_box_filter.py)."""

    def __init__(self, edges, faces) -> None:
        import numpy as np
        self._np = np
        self._items: list = []
        self._row: dict = {}
        rows = []
        for e in edges:
            self._row[id(e)] = len(self._items)
            self._items.append(e)
            a, b = e.a, e.b
            ax, ay, az, bx, by, bz = a.x(), a.y(), a.z(), b.x(), b.y(), b.z()
            rows.append((min(ax, bx), min(ay, by), min(az, bz),
                         max(ax, bx), max(ay, by), max(az, bz)))
        for f in faces:
            self._row[id(f)] = len(self._items)
            self._items.append(f)
            rows.append(self._points_box(f.vertices))
        self._arr = (np.asarray(rows, dtype=np.float64) if rows
                     else np.zeros((0, 6)))
        self._extra: dict = {}

    @staticmethod
    def _points_box(pts):
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        zs = [p.z() for p in pts]
        if not xs:
            return (0.0,) * 6
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))

    def _box(self, item):
        hit = self._extra.get(id(item))
        if hit is not None and hit[0] is item:
            return hit[1]
        pts = item.vertices if hasattr(item, "vertices") else (item.a, item.b)
        box = self._points_box(pts)
        self._extra[id(item)] = (item, box)
        return box

    @staticmethod
    def _window(pts):
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        zs = [p.z() for p in pts]
        lo = (min(xs), min(ys), min(zs))
        hi = (max(xs), max(ys), max(zs))
        # 1 cm, plus a relative term for coordinates far from the origin
        # (float32 positions, segment_intersection's relative tolerance).
        m = 0.01 + 1e-6 * max(abs(c) for c in lo + hi)
        return (lo[0] - m, lo[1] - m, lo[2] - m,
                hi[0] + m, hi[1] + m, hi[2] + m)

    def _pick(self, items, pts):
        np = self._np
        w = self._window(pts)
        arr = self._arr
        mask = ((arr[:, 3] >= w[0]) & (arr[:, 0] <= w[3])
                & (arr[:, 4] >= w[1]) & (arr[:, 1] <= w[4])
                & (arr[:, 5] >= w[2]) & (arr[:, 2] <= w[5]))
        known = self._items
        # Boxed at the start (kept alive in ``known``, so an id is never
        # reused): the mask says. The plan's own new pieces are boxed here.
        # The set work runs in C; only the hits and the new pieces reach
        # Python, and the result keeps the order of ``items``.
        keep = {id(known[r]) for r in np.flatnonzero(mask)}
        ids = list(map(id, items))
        new = set(ids).difference(self._row)
        if new:
            for it in items:
                if id(it) in new:
                    x0, y0, z0, x1, y1, z1 = self._box(it)
                    if (x1 >= w[0] and x0 <= w[3] and y1 >= w[1]
                            and y0 <= w[4] and z1 >= w[2] and z0 <= w[5]):
                        keep.add(id(it))
        if not keep:
            return []
        return [it for it, i in zip(items, ids) if i in keep]

    def edges(self, edges, a, b):
        return self._pick(edges, (a, b))

    def faces(self, faces, a, b):
        return self._pick(faces, (a, b))

    def faces_around(self, faces, pts):
        return self._pick(faces, list(pts))


def _around(near, faces, loop):
    """The faces a same-vertex face can be among: an equal face has the same
    corners, hence the same box (``face_exists`` compares vertex sets)."""
    return near.faces_around(faces, loop) if near is not None else faces


def _plan_faces(commands, faces_snapshot, simulated, sa, sb, eye=None,
                near=None) -> None:
    """Emit the face commands for a freshly added edge ``sa``–``sb``.

    Two paths, mutually exclusive:

    - *Chord split* — the edge divides an existing face: replace that mother
      face with its two halves (handles "draw a diagonal across a square → two
      triangles, each pushable on its own").
    - *Auto-face* — otherwise close any new minimal cycles the edge forms.
      ``find_cycles_through`` returns both sides, so a diagonal across a
      face-less square still faces both triangles.
    """
    chord = find_chord_split(
        near.faces(faces_snapshot, sa, sb) if near is not None
        else faces_snapshot, sa, sb)
    if chord is not None:
        mother, loop_a, loop_b = chord
        # Both halves ARE the mother, cut in two: they keep her paint, and
        # keep it VERBATIM. They are coplanar with her, so carrying the
        # texture's world→UV map over is what makes the image run straight
        # across the cut instead of restarting on each half — the result users
        # of push/pull modellers expect. Without this, drawing a line across a textured face wiped
        # the texture off both halves (Marco, 2026-08-27).
        keep = dict(mother.attrs) if mother.attrs else None
        commands.append(DeleteFaceCommand(mother))
        faces_snapshot.remove(mother)
        for loop in (loop_a, loop_b):
            if is_planar(loop) and not face_exists(
                    _around(near, faces_snapshot, loop), loop):
                commands.append(AddFaceCommand(loop, attrs=keep))
                faces_snapshot.append(Face(list(loop), attrs=keep))
        return

    for cycle in find_cycles_through(
            simulated, sa, sb,
            key=getattr(near, "key", None) if near is not None else None):
        if is_planar(cycle) and not face_exists(
                _around(near, faces_snapshot, cycle), cycle):
            cycle = face_up_or_toward(cycle, eye)
            commands.append(AddFaceCommand(cycle))
            faces_snapshot.append(Face(list(cycle)))


def _scene_has_curves(scene) -> bool:
    return any(getattr(e, "curve", None) is not None for e in scene.edges)


def _append_flat_curve_rebuild(scene, commands, points) -> None:
    """Append the deterministic planar-arrangement rebuild after a draw when
    the cycle planner alone cannot produce the expected regions:

    - Whole-flat drawing WITH curves → full rebuild (every minimal region gets
      a face; a square over a circle splits into three areas).
    - Whole-flat drawing, straight edges only, faces present → SCOPED rebuild
      with coverage semantics (two overlapping rectangles split into three
      regions; regions nobody covered stay empty — no resurrecting faces the
      user deleted).
    - 3D scene whose drawing plane carries curve edges → SCOPED rebuild on
      just that plane (straight-only 3D drawing keeps its proven path).

    Dangling edges survive the rebuild (spur pruning only affects face
    tracing), so half-drawn chains are safe."""
    from core.history import RebuildPlanarFacesCommand, RebuildPlaneFacesCommand

    if any(isinstance(c, (RebuildPlanarFacesCommand, RebuildPlaneFacesCommand))
           for c in commands):
        return
    from core.arrangement import coplanar_plane

    has_curves = _scene_has_curves(scene)
    verts = [v.position for v in scene.mesh.vertices] + list(points)
    if coplanar_plane(verts) is not None:
        if has_curves:
            # Whole-flat drawing with curves: the full rebuild (every minimal
            # region gets a face — how a lone circle yields its disc).
            commands.append(RebuildPlanarFacesCommand())
        elif scene.mesh.faces:
            # Whole-flat, straight edges only, faces present: the SCOPED
            # rebuild with coverage semantics. Two overlapping rectangles must
            # split into three regions (the classic behaviour) — the planner leaves
            # the first rectangle whole over the lens (rect.igz report) — but
            # regions nobody covered stay empty (no resurrecting faces the
            # user deleted).
            origin, normal = coplanar_plane(verts)
            if scene.mesh.faces:
                normal = scene.mesh.faces[0].normal()
                origin = scene.mesh.faces[0].vertices[0]
            commands.append(RebuildPlaneFacesCommand(origin, normal))
        return
    if not has_curves:
        return
    plane = coplanar_plane(list(points))
    if plane is None:
        return
    origin, normal = plane
    tol = 1e-4

    def on_plane(p):
        return abs(QVector3D.dotProduct(p - origin, normal)) < tol

    if any(e.curve is not None and on_plane(e.a) and on_plane(e.b)
           for e in scene.mesh.edges):
        commands.append(RebuildPlaneFacesCommand(origin, normal))


def _append_face_plane_rebuild(scene, commands, points) -> None:
    """Append the scoped plane rebuild when straight edges land on a plane
    that already carries faces, in a scene the whole-flat gate can't cover.

    The naive cycle planner mishandles a chord that touches a hole boundary
    (a line across a slab top grazing an inner rectangle's edge): instead of
    subdividing the mother it stacks a duplicate, sometimes flipped, region
    face on top — and erasing any of those edges later cascade-deletes the
    whole plane instead of merging (aa.igz plaza report, 2026-07-12). The
    deterministic arrangement with coverage semantics is the machinery that
    already solves this for curves; a populated plane deserves it too."""
    from core.history import RebuildPlanarFacesCommand, RebuildPlaneFacesCommand

    if any(isinstance(c, (RebuildPlanarFacesCommand, RebuildPlaneFacesCommand))
           for c in commands):
        return
    tol = 1e-4
    for f in scene.mesh.faces:
        origin = f.vertices[0]
        normal = f.normal()
        # A degenerate normal is a WILDCARD here: dot(anything, zero) is 0,
        # so such a face would claim every line drawn anywhere in the mesh
        # and hand its "plane" to the rebuild below. Face.normal() no longer
        # produces one, but nothing downstream should depend on that.
        if normal.lengthSquared() < 0.5:
            continue
        if all(abs(QVector3D.dotProduct(p - origin, normal)) < tol
               for p in points):
            # Reference-scale guard: rebuilding a plane that carries hundreds
            # of faces (a triangulated import living loose in the mesh) runs
            # the arrangement over all of them — minutes, reads as a hang.
            # Hand-drawn planes stay far below this; past it, keep the naive
            # path (imports should live in a Group anyway).
            on_plane = sum(
                1 for g in scene.mesh.faces
                if abs(QVector3D.dotProduct(g.vertices[0] - origin,
                                            normal)) < tol
                and abs(QVector3D.dotProduct(g.normal(), normal)) > 0.999)
            if on_plane <= 400:
                commands.append(RebuildPlaneFacesCommand(origin, normal))
            return


def _append_active_tag(scene, commands) -> None:
    """Tag-as-you-draw: when the BIM active class is set, append the step that
    stamps it on the plan's own drawn faces. Inserted BEFORE the plane
    rebuilds, so a rebuild that replaces the drawn face inherits the tag
    per-region (A.3) instead of losing the reference."""
    tag = getattr(scene, "active_ifc", None)
    if not tag:
        return
    from core.history import AutoTagDrawnFacesCommand
    face_cmds = [c for c in commands
                 if isinstance(c, AddFaceCommand) and c.auto]
    if face_cmds:
        commands.append(AutoTagDrawnFacesCommand(face_cmds, tag))


def _newell(loop) -> QVector3D:
    nx = ny = nz = 0.0
    n = len(loop)
    for i in range(n):
        p, q = loop[i], loop[(i + 1) % n]
        nx += (p.y() - q.y()) * (p.z() + q.z())
        ny += (p.z() - q.z()) * (p.x() + q.x())
        nz += (p.x() - q.x()) * (p.y() + q.y())
    return QVector3D(nx, ny, nz)


def face_up_or_toward(loop, eye=None):
    """The winding a brand-new face should take (the usual rule for a face
    with no neighbour to agree with): a horizontal one shows its FRONT
    upwards, any other one faces the ``eye`` that drew it. A loop closed by
    hand with Line, or by Offset, came out either way — the order the cycle
    was traced in — and Marco read the blue back as «cara invertida»
    (2026-09-21, tests 15 and 19 of the bench). Returns the loop, reversed
    when needed; untouched when nothing decides (no eye and a vertical
    face, or a degenerate loop)."""
    pts = list(loop)
    if len(pts) < 3:
        return pts
    n = _newell(pts)
    if n.length() < 1e-12:
        return pts
    if abs(n.z()) > 0.5 * n.length():
        want = n.z() > 0
    elif eye is not None:
        c = QVector3D(0, 0, 0)
        for q in pts:
            c += q
        c /= float(len(pts))
        want = QVector3D.dotProduct(n, QVector3D(eye) - c) > 0
    else:
        return pts
    return pts if want else [pts[0]] + pts[:0:-1]


def build_add_edge(scene, a: QVector3D, b: QVector3D, detect_faces: bool = True,
                   eye=None) -> Command:
    """Single-segment convenience: one drawn edge → one atomic command."""
    commands = plan_edge_commands(scene, [(a, b)], detect_faces=detect_faces,
                                  eye=eye)
    _append_active_tag(scene, commands)
    _append_flat_curve_rebuild(scene, commands, [a, b])
    if detect_faces:
        _append_face_plane_rebuild(scene, commands, [a, b])
    # When curves exist, even a single added edge can break a circle into
    # contours (a tangent line landing on a curve vertex splits it),
    # so it must go through SnapshotCompound, which runs the contour re-split —
    # and whose undo restores the reunited curve.
    if len(commands) == 1 and not _scene_has_curves(scene):
        return commands[0]
    # Splits/welds/hole-punches don't compose into a clean per-op inverse — undo
    # via one snapshot so it reverses exactly (no orphan edges/vertices left).
    return SnapshotCompound(commands)


def build_add_edges(
    scene,
    segments: Sequence[Segment],
    detect_faces: bool = True,
    extra: Iterable[Command] = (),
    eye=None,
    plane_rebuild: bool = False,
) -> Command:
    """Batch convenience: many drawn edges (+ optional ``extra`` commands such
    as a tool-managed face) → one atomic command. ``eye`` (the camera's
    position) decides which way a new vertical face looks.

    ``plane_rebuild``: a tool that owns its face (the Rectangle) asks for
    the plane it lands on to be rebuilt, as a drawn Line has been since
    July — drawn over a ring on walls it stacked a full face on the ring
    instead of filling the hole (#538)."""
    commands = plan_edge_commands(scene, segments, detect_faces=detect_faces,
                                  eye=eye)
    commands.extend(extra)
    _append_active_tag(scene, commands)
    points = [p for seg in segments for p in seg]
    _append_flat_curve_rebuild(scene, commands, points)
    if plane_rebuild:
        _append_face_plane_rebuild(scene, commands, points)
    if len(commands) == 1 and not _scene_has_curves(scene):
        return commands[0]
    return SnapshotCompound(commands)


def divide_edges(mesh, edges, n: int) -> int:
    """Divide (issue #63, @pacaeiro): split each selected edge —
    or, for an edge of a curve, the whole curve — into ``n`` pieces of
    equal length. A straight edge gets n−1 new vertices. A curve (arc,
    circle) is measured along its chain, cut where the k/n marks fall, and
    comes out as ``n`` INDEPENDENT arcs — each piece its own curve, each
    selectable on its own, the classic behaviour (a circle divided in
    four is four quarter arcs; Marco, 2026-09-21).
    A mark that lands on an existing facet vertex cuts nothing there but
    still parts the curve. Faces the edges bound take the new vertices in
    their loops (``Mesh.split_edge``). Returns the number of cuts made."""
    from core.mesh import Mesh, edge_flags, stamp_edge_flags
    n = int(n)
    if n < 2:
        return 0
    done: set = set()
    cuts = 0
    for edge in list(edges):
        if id(edge) in done:
            continue
        is_curve = getattr(edge, "curve", None) is not None
        chain = mesh.curve_edges(edge) if is_curve else [edge]
        walk = _order_chain(chain, edge)
        for e, _, _ in walk:
            done.add(id(e))
        total = sum((vt.position - vf.position).length() for _, vf, vt in walk)
        if total < 1e-9:
            continue
        step = total / n
        # The facets of each of the n pieces, in walking order; a piece's
        # index is the k/n span its facets fall in.
        pieces: list = [[] for _ in range(n)]

        def piece_of(s0: float, s1: float) -> int:
            return max(0, min(n - 1, int(((s0 + s1) * 0.5) // step)))

        walked = 0.0
        for e, v_from, v_to in walk:
            a, b = QVector3D(v_from.position), QVector3D(v_to.position)
            ln = (b - a).length()
            if ln < 1e-12:
                continue
            flags = edge_flags(e)
            inside = [k for k in range(1, n)
                      if walked + 1e-9 < step * k < walked + ln - 1e-9]
            rest, rest_from, rest_start = e, v_from, walked
            for k in inside:
                at = step * k
                point = a + (b - a) * ((at - walked) / ln)
                e0, e1 = mesh.split_edge(rest, point)
                if e0 is e1:
                    break
                # split_edge hands the halves back in v0→v1 order of the
                # facet, which need not be the walking order: pick by the
                # vertex we came from.
                first = e0 if rest_from in (e0.v0, e0.v1) else e1
                second = e1 if first is e0 else e0
                for half in (first, second):
                    stamp_edge_flags(half, flags)
                pieces[piece_of(rest_start, at)].append(first)
                rest, rest_from, rest_start = second, first.other(rest_from), at
                cuts += 1
            pieces[piece_of(rest_start, walked + ln)].append(rest)
            walked += ln
        if is_curve:
            for facets in pieces:
                if not facets:
                    continue
                cid = Mesh.next_curve_id()
                for f in facets:
                    f.curve = cid
    return cuts


# How far a point may sit off the line through its neighbours and still go.
# A distance, not an angle: float32 coordinates tilt a 2 cm piece 300 m
# out more than a real 0.1° kink in a 10 m line, yet move the point far
# less. And it follows that precision, not a fixed figure: a few float32
# steps of the coordinates' size (~1e-7 each), so mm work near the origin
# gets a thousandth of a mm, and the first facet of a 2 mm fillet is never
# taken for part of the line it leaves. Capped at the mesh's own stitch
# tolerance (0.1 mm); beyond that the point is not on the line.
_JOIN_TOL_FLOOR = 1e-6
_JOIN_TOL_REL = 1e-6
_JOIN_TOL_MAX = 1e-4


def _off_line(p, a, b) -> tuple:
    """Distance from ``p`` to the line through ``a`` and ``b``, and the
    tolerance the size of those coordinates allows it — in double
    precision, so the test adds no float32 noise of its own."""
    p, a, b = ((q.x(), q.y(), q.z()) for q in (p, a, b))
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    cross = (ap[1] * ab[2] - ap[2] * ab[1],
             ap[2] * ab[0] - ap[0] * ab[2],
             ap[0] * ab[1] - ap[1] * ab[0])
    off = math.sqrt(sum(c * c for c in cross)) / math.sqrt(
        sum(c * c for c in ab))
    size = max(abs(c) for q in (p, a, b) for c in q)
    tol = min(_JOIN_TOL_MAX, _JOIN_TOL_FLOOR + _JOIN_TOL_REL * size)
    return off, tol


#: Why Join Segments leaves a point where it is, for its preview: the
#: points it takes away ("join") and the ones on a straight line that it
#: keeps all the same, each for its reason. A plain corner is not listed:
#: only a kink close enough to straight to be mistaken for none.
JOIN_REASONS = ("join", "kink", "branch", "flags", "curve")

# Under this angle a corner kept by Join Segments is worth pointing out:
# it looks straight but is not (a fillet's first facet, a stray click).
_JOIN_KINK_DEG = 1.0


def _kink_deg(v, a, b) -> float:
    """The turn, in degrees, a path a → v → b takes at ``v``."""
    d1, d2 = v.position - a.position, b.position - v.position
    if d1.length() == 0 or d2.length() == 0:
        return 180.0
    c = QVector3D.dotProduct(d1.normalized(), d2.normalized())
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _straight_through(v, picked) -> bool:
    """Whether two of the ``picked`` edges at ``v`` run on in one straight
    line through it — a T or a cross whose bar Join Segments must keep."""
    ends = [e.other(v) for e in v.edges if id(e) in picked]
    for i, a in enumerate(ends):
        for b in ends[i + 1:]:
            off, tol = _off_line(v.position, a.position, b.position)
            if off <= tol and _kink_deg(v, a, b) < 90.0:
                return True
    return False


def join_edges(mesh, edges, verdicts: Optional[dict] = None) -> list:
    """Join Segments, the inverse of Divide: every vertex where two of
    ``edges`` meet in a straight line, with nothing else attached to it,
    goes, and the two segments become one line. A long line drawn in
    pieces, or one left cut by a divide or by an erased crossing, comes out
    clean, its faces (if it bounds any) losing the needless corner.

    A vertex stays when a third edge meets it, when the two segments are
    not collinear, bound different faces, carry different flags (soft,
    hidden, layer), or belong to a curve: an arc's facets are not
    segments to merge. Returns the edges the selection is made of
    afterwards, the joined lines in place of their pieces.

    ``verdicts``, when given, is filled with what happened to each point
    on the way, ``{vertex: reason}`` (see :data:`JOIN_REASONS`): what
    :func:`join_preview` shows."""
    from core.mesh import edge_flags, stamp_edge_flags
    live = [e for e in edges if e in mesh.edges]
    picked = set(map(id, live))
    seen: set = set()
    candidates = []
    for e in live:
        for v in (e.v0, e.v1):
            if id(v) not in seen:
                seen.add(id(v))
                candidates.append(v)

    def keep(v, reason):
        if verdicts is not None:
            verdicts[v] = reason

    for v in candidates:
        if len(v.edges) != 2:
            if len(v.edges) > 2 and _straight_through(v, picked):
                keep(v, "branch")
            continue
        e1, e2 = list(v.edges)
        if id(e1) not in picked or id(e2) not in picked:
            continue
        a, b = e1.other(v), e2.other(v)
        off, tol = _off_line(v.position, a.position, b.position)
        if off > tol:
            if _kink_deg(v, a, b) < _JOIN_KINK_DEG:
                keep(v, "kink")
            continue
        flags = edge_flags(e1)
        if flags != edge_flags(e2):
            keep(v, "flags")
            continue
        if e1.curve is not None or e2.curve is not None:
            keep(v, "curve")
            continue
        if not mesh.collapsible_vertex(v):
            continue
        if mesh.find_edge(a, b) is not None:
            continue                     # the whole line is there already
        joined = mesh.collapse_vertex(v)["new_edge"]
        stamp_edge_flags(joined, flags)
        keep(v, "join")
        picked.discard(id(e1))
        picked.discard(id(e2))
        picked.add(id(joined))
        live.append(joined)
    return [e for e in live if id(e) in picked and e in mesh.edges]


def join_preview(mesh, edges) -> dict:
    """What Join Segments would do to ``edges``, without doing it:
    ``{vertex: reason}`` for the points it would take away and the ones on
    a straight line it would keep (see :data:`JOIN_REASONS`). A dry run of
    :func:`join_edges` itself, so the preview never disagrees with the
    command; the mesh is put back as it was, the same objects included."""
    verdicts: dict = {}
    snap = mesh.capture_state()
    try:
        join_edges(mesh, edges, verdicts)
    finally:
        mesh.restore_state(snap)
    return verdicts


def _order_chain(chain, seed):
    """The edges of a curve in walking order as ``(edge, v_from, v_to)``
    triples, starting at one end (or at ``seed.v0`` for a closed loop) so
    the k/n marks land where users expect them. The orientation matters: a
    facet's own ``v0→v1`` may run against the walk, and a mark measured
    along the wrong way lands mirrored inside the facet."""
    if len(chain) <= 1:
        e = chain[0]
        return [(e, e.v0, e.v1)]
    by_vertex: dict = {}
    for e in chain:
        for v in (e.v0, e.v1):
            by_vertex.setdefault(id(v), (v, []))[1].append(e)
    ends = [v for v, es in by_vertex.values() if len(es) == 1]
    v = ends[0] if ends else seed.v0
    ordered, seen = [], set()
    while True:
        nxt = next((e for e in by_vertex[id(v)][1] if id(e) not in seen), None)
        if nxt is None:
            break
        seen.add(id(nxt))
        w = nxt.other(v)
        ordered.append((nxt, v, w))
        v = w
        if len(ordered) == len(chain):
            break
    return ordered
