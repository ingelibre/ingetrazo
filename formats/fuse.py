# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fast coplanar fusion for imported triangle soups.

A 3D-Warehouse building arrives as ~17k triangles; SketchUp's importer merges
the coplanar ones back into clean facade-sized faces (and that is why the
same model is fluid there). The engine's generic coplanar merge is O(F²) and
melts at that scale, so imports get this dedicated O(F) pass instead:

- bucket loops by (plane, material) with rounded keys,
- union-find the loops of a bucket into connected regions via shared edges,
- a region's boundary is the edges used exactly once — trace them into
  closed loops; the largest is the outer contour, the rest are holes.

Anything irregular (non-manifold edge use, boundary vertex of degree ≠ 2,
open walks) bails out to the original loops for that region — the pass only
ever merges what it can prove clean.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D


def _key(p: QVector3D):
    return (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))


def _newell(pts) -> QVector3D:
    n = QVector3D(0.0, 0.0, 0.0)
    m = len(pts)
    for i in range(m):
        a, b = pts[i], pts[(i + 1) % m]
        n += QVector3D((a.y() - b.y()) * (a.z() + b.z()),
                       (a.z() - b.z()) * (a.x() + b.x()),
                       (a.x() - b.x()) * (a.y() + b.y()))
    return n


def _attrs_sig(attrs):
    if not attrs:
        return None
    c = attrs.get("color")
    t = attrs.get("texture")
    tsig = None
    if t:
        uvw = t.get("uvw")
        # The fitted world→UV map is exact per polygon; rounding merges the
        # float noise between triangles of the SAME original textured face
        # while keeping differently-mapped faces apart.
        tsig = (t.get("path"), t.get("sw"), t.get("sh"), t.get("rot", 0),
                None if not uvw else tuple(round(x, 4) for x in uvw))
    return (None if c is None else tuple(c), tsig)


def _sig_rank(sig) -> int:
    """Preference between coincident duplicate copies (SketchUp's two-sided
    export): a textured copy beats a colour-only copy beats a bare one."""
    if sig is None:
        return 0
    return 2 if sig[1] is not None else 1


def fuse_coplanar_loops(loops, cos_tol: float = 0.99999):
    """``loops``: list of ``(pts, attrs_dict_or_None)`` polygons (triangles or
    n-gons). Returns a list of ``(outer_pts, holes, attrs, originals)`` —
    coplanar same-material connected regions merged into one polygon (holes
    included), everything else passed through unchanged. ``originals`` holds
    the source loops of the region so a caller whose ``add_face`` rejects the
    fused polygon can fall back to them (no geometry is ever lost).

    Regions grow by *pairwise* edge tests — two faces merge when they share a
    welded edge, the same material, and near-identical normals — so there is
    no global plane quantisation to split a facade at a rounding cliff. The
    drift guard compares each union against the region's root normal, so a
    faceted curve (real dihedral steps) never chain-merges into a non-planar
    blob."""
    faces: list = []
    # Coincident duplicates (SketchUp's two-sided export writes every
    # triangle twice, front + reversed back): keep ONE copy — they z-fight
    # in the render (the mottled front/back patchwork) and their 4-faces
    # edges block every merge. The copy carrying a material wins.
    seen_tris: dict = {}
    for pts, attrs in loops:
        if len(pts) < 3:
            continue
        n = _newell(pts)
        ln = n.length()
        if ln < 1e-10:
            continue                      # degenerate sliver
        entry = (pts, attrs, n / ln, _attrs_sig(attrs))
        if len(pts) == 3:
            tkey = frozenset(_key(p) for p in pts)
            prev = seen_tris.get(tkey)
            if prev is None:
                seen_tris[tkey] = len(faces)
                faces.append(entry)
            elif _sig_rank(entry[3]) > _sig_rank(faces[prev][3]):
                faces[prev] = entry   # textured > coloured > bare copy
            continue
        faces.append(entry)

    parent = list(range(len(faces)))
    root_n = [f[2] for f in faces]

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edge_map: dict = {}
    for i, (pts, _a, _n, _s) in enumerate(faces):
        m = len(pts)
        for k in range(m):
            e = frozenset((_key(pts[k]), _key(pts[(k + 1) % m])))
            if len(e) == 2:
                edge_map.setdefault(e, []).append(i)

    for idxs in edge_map.values():
        if len(idxs) != 2:
            continue                      # boundary or non-manifold junction
        i, j = idxs
        if faces[i][3] != faces[j][3]:
            continue                      # different material
        if abs(QVector3D.dotProduct(faces[i][2], faces[j][2])) < cos_tol:
            continue                      # a real crease
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        if abs(QVector3D.dotProduct(root_n[ri], root_n[rj])) < cos_tol:
            continue                      # drift guard: stay planar
        parent[rj] = ri

    regions: dict = {}
    for i in range(len(faces)):
        regions.setdefault(find(i), []).append(faces[i][:3])

    out: list = []
    for region in regions.values():
        fused = _trace_region(region)
        if fused is not None:
            out.append(fused)
        else:
            out.extend((pts, [], attrs, [pts]) for pts, attrs, _n in region)
    return out


def _trace_region(loops):
    """One connected coplanar region → ``(outer, holes, attrs)`` or ``None``
    when its boundary isn't cleanly traceable."""
    if len(loops) == 1:
        pts, attrs, _n = loops[0]
        return (pts, [], attrs, [pts])
    # Boundary edges appear exactly once across the region's loops.
    count: dict = {}
    pos: dict = {}
    for pts, _a, _n in loops:
        m = len(pts)
        for k in range(m):
            ka, kb = _key(pts[k]), _key(pts[(k + 1) % m])
            if ka == kb:
                continue
            e = frozenset((ka, kb))
            count[e] = count.get(e, 0) + 1
            pos.setdefault(ka, pts[k])
            pos.setdefault(kb, pts[(k + 1) % m])
    boundary = [e for e, c in count.items() if c == 1]
    if not boundary or any(c > 2 for c in count.values()):
        return None                       # non-manifold inside the plane
    adj: dict = {}
    for e in boundary:
        a, b = tuple(e)
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if any(len(v) != 2 for v in adj.values()):
        return None                       # touching contours — keep triangles
    # Walk the boundary into closed loops.
    unvisited = set(boundary)
    traced: list = []
    while unvisited:
        e0 = next(iter(unvisited))
        start, cur = tuple(e0)
        unvisited.discard(e0)
        walk = [start, cur]
        while True:
            a, b = adj[cur]
            nxt = b if a == walk[-2] else a
            edge = frozenset((cur, nxt))
            if edge not in unvisited:
                break
            unvisited.discard(edge)
            if nxt == start:
                break
            walk.append(nxt)
            cur = nxt
        if walk[-1] == start:
            walk.pop()
        if len(walk) < 3:
            return None
        traced.append([QVector3D(pos[k]) for k in walk])
    # Largest loop is the outer contour; orient it with the region's normal,
    # holes against it (the triangulator's convention for nested loops).
    n_ref = loops[0][2]
    areas = [(_newell(lp), lp) for lp in traced]
    areas.sort(key=lambda t: t[0].length(), reverse=True)
    outer_n, outer = areas[0]
    if QVector3D.dotProduct(outer_n, n_ref) < 0:
        outer = list(reversed(outer))
    holes = []
    for hn, lp in areas[1:]:
        if QVector3D.dotProduct(hn, n_ref) > 0:
            lp = list(reversed(lp))
        holes.append(lp)
    return (outer, holes, loops[0][1], [pts for pts, _a, _n in loops])


def soften_smooth_edges(mesh, cos_threshold: float = 0.85) -> None:
    """Mark edges between two same-material faces meeting at a shallow
    dihedral as soft (hidden in the render) — SketchUp's import smoothing.
    Curved facades read smooth, plane-bucket seams disappear, while real
    corners (90° walls) and material boundaries stay visible."""
    normals = {}
    for e in mesh.edges:
        if len(e.faces) != 2:
            continue
        f0, f1 = e.faces
        if f0 is f1:
            continue
        if _attrs_sig(f0.attrs) != _attrs_sig(f1.attrs):
            continue                      # material boundary: keep the line
        n0 = normals.get(id(f0))
        if n0 is None:
            n0 = normals[id(f0)] = f0.normal()
        n1 = normals.get(id(f1))
        if n1 is None:
            n1 = normals[id(f1)] = f1.normal()
        if abs(QVector3D.dotProduct(n0, n1)) > cos_threshold:
            e.soft = True
