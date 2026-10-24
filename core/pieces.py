# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Split a group into its physical pieces: the solids that do not touch.

What a model file calls its parts is often not what a person would. A Sweet
Home 3D bar stool is 43 groups in its OBJ, and they are surface fragments —
cut wherever the material changes — while the stool itself is five things
you could pick up: the seat with its back, a footrest, a front frame and two
side legs. And a kitchen cabinet is the opposite case: its carcase boards
are separate closed boxes that TOUCH, and once the import welds coincident
corners, plain connectivity reads the whole carcase as one piece.

So a piece is found in two passes (:func:`solid_parts`). First the solids:
around every edge, each face is paired with the face it meets turning into
the material behind it (:func:`_edge_partners`) — on an ordinary edge that
is simply the other face, and where two boards meet (four faces, or six at
a corner) it is the face of the same board, never the neighbour's. A result
counts as a solid when it closes, has thickness and at least four faces. Then the fragments (open patches, zero-thickness strips,
what a file cut by material leaves) cluster through shared vertices and
join the one solid most of their corners lie on; a fragment that only
brushes a solid at a corner or two — a counter top resting on the carcase —
stays a piece of its own. A fragment never bridges two solids.
"""
from __future__ import annotations

from core.mesh import Mesh, edge_flags, stamp_edge_flags


def connected_parts(mesh: Mesh) -> list:
    """``mesh`` cut into its connected pieces, each a ``(faces, edges)``
    pair, largest first (by face count, a loose wire after every solid).

    Two faces are one piece when they share a vertex; a loose edge joins
    whatever its ends touch, so a wire hanging off a solid stays with it."""
    parent: dict = {}

    def find(x):
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(x, x) != root:        # flatten the path behind us
            parent[x], x = root, parent[x]
        return root

    def join(vs) -> None:
        r = find(id(vs[0]))
        for v in vs[1:]:
            k = find(id(v))
            if k != r:
                parent[k] = r

    for f in mesh.faces:
        join(list(f.loop) + [v for h in f.hole_loops for v in h])
    for e in mesh.edges:
        join([e.v0, e.v1])

    parts: dict = {}
    for f in mesh.faces:
        parts.setdefault(find(id(f.loop[0])), ([], []))[0].append(f)
    for e in mesh.edges:
        parts.setdefault(find(id(e.v0)), ([], []))[1].append(e)
    return sorted(parts.values(), key=lambda p: (-len(p[0]), -len(p[1])))


#: A result thinner than this is a sheet, not a board (metres).
MIN_THICKNESS = 0.001
#: A fragment joins a solid when at least this share of its corners lie on it.
ATTACH_SHARE = 0.5


def _rings(face):
    yield face.loop
    yield from face.hole_loops


def _is_solid(faces) -> bool:
    """Closed (every edge used an even number of times by these faces), at
    least four faces, and thicker than :data:`MIN_THICKNESS` along every
    axis — a double-sided strip passes the first test and fails this one."""
    if len(faces) < 4:
        return False
    uses: dict = {}
    for f in faces:
        for ring in _rings(f):
            n = len(ring)
            for i in range(n):
                a, b = id(ring[i]), id(ring[(i + 1) % n])
                key = (a, b) if a < b else (b, a)
                uses[key] = uses.get(key, 0) + 1
    if any(c % 2 for c in uses.values()):
        return False
    xs, ys, zs = [], [], []
    for f in faces:
        for v in f.loop:
            p = v.position
            xs.append(p.x())
            ys.append(p.y())
            zs.append(p.z())
    return min(max(xs) - min(xs), max(ys) - min(ys),
               max(zs) - min(zs)) >= MIN_THICKNESS


#: Faces closer than this in angle about an edge are the same plane (rad).
_COINCIDENT = 1e-3


def _edge_partners(edge) -> list:
    """``(face, partner)`` pairs around ``edge``: for each face, the face
    reached by turning about the edge from it INTO the material behind it
    (against its outward normal). On a two-face edge that is the other face;
    where solids meet it is the next face of the same solid, which is what
    keeps two boards welded at a shared edge apart. A face coinciding with
    another (two boards pressed face to face) is a full turn away from it,
    not zero — the neighbour's face is never the partner."""
    import math
    faces = list(edge.faces)
    if len(faces) < 3:
        return [(faces[0], faces[1])] if len(faces) == 2 else []
    a, b = edge.v0, edge.v1
    axis = b.position - a.position
    if axis.lengthSquared() == 0:
        return []
    axis.normalize()
    ref_u = None
    info = []
    for f in faces:
        n = f.normal()
        if n.isNull():
            continue
        w = _inward(f, a, b, n)
        if w is None:
            continue
        if ref_u is None:
            ref_u = w
            ref_v = type(w).crossProduct(axis, w)
        theta = math.atan2(type(w).dotProduct(w, ref_v),
                           type(w).dotProduct(w, ref_u))
        # Which way round is "into the material": the side -n is on.
        spin = type(w).dotProduct(type(w).crossProduct(axis, w), n)
        info.append((f, theta, -1.0 if spin > 0 else 1.0, w, n))
    pairs = []
    two_pi = 2.0 * math.pi
    for f, theta, s, w_f, _n in info:
        best, best_key = None, None
        for g, phi, _s, _w, n_g in info:
            if g is f:
                continue
            d = ((phi - theta) * s) % two_pi
            if d < _COINCIDENT or two_pi - d < _COINCIDENT:
                # Coincident: the far side. The tolerance is float32's —
                # welded boards pressed face to face come out 1e-5 rad
                # apart, and at a hair past zero the neighbour's face
                # looked like the nearest one.
                d = two_pi
            # Two faces at the same angle are two boards pressed together;
            # the partner is the one whose material faces back toward f
            # (its normal points away from f's side).
            facing = 0 if type(w_f).dotProduct(n_g, w_f) < 0 else 1
            key = (round(d / _COINCIDENT), facing)
            if best_key is None or key < best_key:
                best, best_key = g, key
        if best is not None:
            pairs.append((f, best))
    return pairs


def _inward(face, a, b, n):
    """The unit vector in ``face``'s plane, square to edge ``a``–``b``,
    pointing into the face. A ring's interior lies to the left of its walk
    for the outer loop (the normal is that loop's own Newell normal) and to
    the right for a hole wound the same way."""
    from PySide6.QtGui import QVector3D
    for k, ring in enumerate(_rings(face)):
        m = len(ring)
        for i in range(m):
            p, q = ring[i], ring[(i + 1) % m]
            if (p is a and q is b) or (p is b and q is a):
                w = QVector3D.crossProduct(n, q.position - p.position)
                if k > 0:
                    hn = _newell([v.position for v in ring])
                    if QVector3D.dotProduct(hn, n) > 0:
                        w = w * -1.0
                if w.lengthSquared() == 0:
                    return None
                return w.normalized()
    return None


def _newell(points):
    from PySide6.QtGui import QVector3D
    nx = ny = nz = 0.0
    m = len(points)
    for i in range(m):
        p, q = points[i], points[(i + 1) % m]
        nx += (p.y() - q.y()) * (p.z() + q.z())
        ny += (p.z() - q.z()) * (p.x() + q.x())
        nz += (p.x() - q.x()) * (p.y() + q.y())
    return QVector3D(nx, ny, nz)


def solid_parts(mesh: Mesh) -> list:
    """``mesh`` cut into its physical pieces (see the module docstring),
    each a ``(faces, edges)`` pair, largest first. A loose edge goes with
    the piece its ends touch; one touching nothing is a wire of its own."""
    parent: dict = {}

    def find(x):
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(x, x) != root:
            parent[x], x = root, parent[x]
        return root

    def join(a, b) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for e in mesh.edges:
        pairs = _edge_partners(e)
        if len(e.faces) > 2:
            # Where solids meet, trust a pairing only when it is mutual: a
            # face wound the wrong way turns into the neighbour's material
            # and picks the neighbour, but the neighbour does not pick it.
            chosen = {id(f): g for f, g in pairs}
            pairs = [(f, g) for f, g in pairs if chosen.get(id(g)) is f]
        for f, g in pairs:
            join(id(f), id(g))
    groups: dict = {}
    for f in mesh.faces:
        groups.setdefault(find(id(f)), []).append(f)
    comps = list(groups.values())
    solid = [_is_solid(c) for c in comps]

    owner: dict = {}                      # vertex -> the solid it lies on
    for i, c in enumerate(comps):
        if solid[i]:
            for f in c:
                for ring in _rings(f):
                    for v in ring:
                        owner.setdefault(id(v), i)

    # Fragments cluster through shared vertices — among themselves only.
    parent.clear()
    for i, c in enumerate(comps):
        if solid[i]:
            continue
        for f in c:
            for ring in _rings(f):
                for v in ring:
                    join(("v", id(v)), ("c", i))
    clusters: dict = {}
    for i, c in enumerate(comps):
        if not solid[i]:
            clusters.setdefault(find(("c", i)), []).append(i)

    pieces: dict = {i: list(c) for i, c in enumerate(comps) if solid[i]}
    for members in clusters.values():
        fs = [f for i in members for f in comps[i]]
        corners = {id(v) for f in fs for ring in _rings(f) for v in ring}
        votes: dict = {}
        for vid in corners:
            k = owner.get(vid)
            if k is not None:
                votes[k] = votes.get(k, 0) + 1
        best = max(votes.items(), key=lambda kv: kv[1]) if votes else None
        if best is not None and best[1] >= ATTACH_SHARE * len(corners):
            pieces[best[0]].extend(fs)
        else:
            pieces[("fragment", members[0])] = fs

    keys = list(pieces)
    face_piece = {id(f): n for n, k in enumerate(keys) for f in pieces[k]}
    vertex_piece = {}
    for n, k in enumerate(keys):
        for f in pieces[k]:
            for ring in _rings(f):
                for v in ring:
                    vertex_piece.setdefault(id(v), n)
    out = [(pieces[k], []) for k in keys]
    wires: dict = {}
    for e in mesh.edges:
        if e.faces:
            # An edge goes with every piece whose faces it bounds — never
            # with a piece that merely shares one of its corners (that
            # dragged a neighbour's edges along and stretched the piece's
            # box to the neighbour's far end).
            for n in {face_piece[id(f)] for f in e.faces
                      if id(f) in face_piece}:
                out[n][1].append(e)
            continue
        n = vertex_piece.get(id(e.v0), vertex_piece.get(id(e.v1)))
        if n is not None:
            out[n][1].append(e)            # a loose wire hanging off a piece
        else:
            wires.setdefault("all", []).append(e)
    if wires:
        # Loose wire touching no face: its own connected runs, as before.
        wire_mesh_parts = connected_parts(_edges_only(wires["all"]))
        out.extend(([], edges) for _faces, edges in wire_mesh_parts)
    return sorted(out, key=lambda p: (-len(p[0]), -len(p[1])))


def _edges_only(edges):
    """A throwaway view of ``edges`` that :func:`connected_parts` can walk."""
    class _View:
        faces: list = []
    view = _View()
    view.edges = edges
    return view


def copy_part(faces, edges) -> Mesh:
    """A new mesh holding a deep copy of ``faces`` and ``edges`` — attrs,
    holes and every edge flag included — in one vectorized weld. Splitting
    deliberately joins coincident fragment corners; ordinary placement
    materialization preserves vertex identity instead."""
    import numpy as np
    from core.topology import _maximal_holes

    new = Mesh()
    flat: list = []
    for e in edges:
        flat.append((e.a.x(), e.a.y(), e.a.z()))
        flat.append((e.b.x(), e.b.y(), e.b.z()))
    n_edge_pts = len(flat)
    ring_sizes: list = []
    ring_counts: list = []
    attrs_list: list = []
    for f in faces:
        holes = f.holes or []
        if len(holes) > 1:
            holes = _maximal_holes([list(h) for h in holes])
        ring_counts.append(1 + len(holes))
        ring_sizes.append(len(f.vertices))
        flat.extend((v.x(), v.y(), v.z()) for v in f.vertices)
        for h in holes:
            ring_sizes.append(len(h))
            flat.extend((v.x(), v.y(), v.z()) for v in h)
        attrs_list.append(dict(f.attrs) if f.attrs else None)
    if not flat:
        return new
    vobjs, inverse = new.bulk_weld(np.array(flat, dtype=np.float64))
    emap = None
    if edges:
        ia = inverse[0:n_edge_pts:2]
        ib = inverse[1:n_edge_pts:2]
        emap = new.add_edges_welded(
            vobjs, ia, ib, [(e.soft, e.curve, e.layer) for e in edges])
        # ``add_edges_welded`` carries three of the flags; stamp them all,
        # so a hidden edge stays hidden (see core.mesh.EDGE_FLAG_NAMES).
        u = len(vobjs)
        for e, a, b in zip(edges, ia.tolist(), ib.tolist()):
            ne = emap.get(a * u + b if a <= b else b * u + a)
            if ne is not None:
                stamp_edge_flags(ne, edge_flags(e))
    if ring_counts:
        new.add_faces_welded(vobjs, inverse[n_edge_pts:], ring_sizes,
                             ring_counts, attrs_list, edge_map=emap)
    new.resplit_curves()
    return new


def split_into_pieces(group) -> list:
    """The pieces ``group`` comes apart into, as new groups in the group's
    own coordinates (identity placements, ready to :meth:`Group.adopt`), or
    ``[]`` when there is nothing to split — one piece and no children, which
    is exactly what the group already is.

    Everything the group holds is read together, its own mesh and every
    nested placement through its matrix, so fragments the file kept apart
    (a seat in three materials) join into the one piece they are. The group
    itself is never touched; the caller swaps the result in through a
    command, which is what makes the split undoable."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group, world_mesh
    from core.i18n import tr

    # Read the contents in the group's frame, not the world's: the pieces
    # live inside it, and its own matrix keeps placing them.
    frame = Group(group.mesh)
    frame.children = list(group.children)
    local = world_mesh(frame)
    if group.children:
        # Materialization keeps placements isolated. Split analysis instead
        # joins material-cut fragments across children, on a private mesh:
        # neither the prototypes nor ordinary world_mesh callers are welded.
        local = copy_part(local.faces, local.edges)
    parts = solid_parts(local)
    if len(parts) <= 1 and not group.children:
        return []
    kids = group.children
    if (not group.mesh.faces and len(parts) == len(kids)
            and all(not k.children and len(solid_parts(k.mesh)) == 1
                    for k in kids)):
        return []                  # already split: one piece per child
    names = _inherited_names(group, parts)
    pieces = []
    for n, (faces, edges) in enumerate(parts, start=1):
        piece = Group(copy_part(faces, edges),
                      name=names[n - 1] or tr("Piece {n}", n=n))
        piece.xform = QMatrix4x4()
        piece.component = False     # its own geometry: a group (issue #90)
        pieces.append(piece)
    return pieces


def _inherited_names(group, parts) -> list:
    """For each part, the name of the child of ``group`` it came from — when
    it came from exactly one, and that child has a name of its own (a file
    that names its objects, «Base-unit-Box-Right», is worth keeping; a
    «Part 7» the importer numbered, or a «Piece 3» a previous split gave,
    is not). ``None`` where the part spans several children or none. A
    name two parts would share gets a number: «Leg», «Leg 2»."""
    import re
    kids = list(getattr(group, "children", None) or ())
    if not kids:
        return [None] * len(parts)
    generic = re.compile(r"^(part|parte|piece|pieza) \d+$", re.IGNORECASE)
    from core.parts import part_points

    def key(x, y, z):
        return (round(x, 5), round(y, 5), round(z, 5))

    where: dict = {}
    for i, kid in enumerate(kids):
        for x, y, z in part_points(kid).tolist():
            where.setdefault(key(x, y, z), set()).add(i)
    out = []
    used: dict = {}
    for faces, _edges in parts:
        owners = None
        for f in faces:
            for v in f.loop:
                p = v.position
                here = where.get(key(p.x(), p.y(), p.z()), set())
                owners = set(here) if owners is None else owners & here
                if not owners:
                    break
            if not owners:
                break
        name = None
        if owners and len(owners) == 1:
            name = kids[next(iter(owners))].name.strip()
            if not name or generic.match(name):
                name = None
        if name:
            used[name] = used.get(name, 0) + 1
            if used[name] > 1:
                name = f"{name} {used[name]}"
        out.append(name)
    return out
