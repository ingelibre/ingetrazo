# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section planes — slicing a model to peer inside.

A section plane is an object in the model: an origin + a unit normal. The
ACTIVE plane cuts the display — everything on the normal's side disappears
(``Reverse`` flips it). Only ONE plane can be the active cut in the model
context, the usual convention; placing a new plane makes it the active one.
Planes carry a name and a symbol shown on their frame.

The cut is display-only scaffolding, never topology: geometry is untouched,
the renderer clips (``gl_ClipDistance``), picks/snaps filter by the plane,
and the sheet composer's hidden-line pass clips before projecting — that is
the whole point of the track (real plans and cross-sections on the sheets).
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

_last_uid = 0

#: How a cut can be filled: solid, hatched at 45°, cross-hatched, or not.
FILL_PATTERNS = ("solid", "hatch", "cross", "none")
#: Hatch spacing when neither the plane nor anything else says: 5 cm in
#: the model, a wall of 20 cm reads as four lines.
DEFAULT_HATCH_SPACING = 0.05


def effective_fill(plane, style) -> tuple:
    """``(pattern, (r, g, b), spacing)`` the cut of ``plane`` is filled
    with: the plane's own settings over the style's. The style's Section
    Fill switch is the master — off, nothing is filled."""
    own = getattr(plane, "fill", None) or {}
    if not getattr(style, "section_fill", True):
        pattern = "none"
    else:
        pattern = own.get("pattern", "solid")
    color = tuple(own.get("color") or getattr(
        style, "section_fill_color", (0.35, 0.37, 0.41)))
    spacing = float(own.get("spacing") or DEFAULT_HATCH_SPACING)
    return pattern, color, spacing


def _take_uid(wanted: int | None) -> int:
    """A fresh uid, or ``wanted`` (from a loaded file) while keeping the
    counter ahead so later fresh uids never collide."""
    global _last_uid
    if wanted is None:
        _last_uid += 1
        return _last_uid
    wanted = int(wanted)
    if wanted > _last_uid:
        _last_uid = wanted
    return wanted


def next_symbol(planes) -> str:
    """The letter the next section plane takes: A, B, C… then AA, AB.

    Sections are named by letter and the mark reads «A … A» across the
    plan — «las secciones se nombran así, no suele ser un 1, sino A-A,
    B-B» (Rafael, 2026-09-16, 50:45). They used to be numbered, so his
    sheets said «1 … 1» and he could not find where to change it.
    """
    taken = {str(getattr(p, "symbol", "") or "").strip().upper()
             for p in (planes or [])}
    i = 0
    while True:
        n, label = i, ""
        while True:
            label = chr(ord("A") + n % 26) + label
            n = n // 26 - 1
            if n < 0:
                break
        if label not in taken:
            return label
        i += 1


class SectionPlane:
    """Origin + unit normal (+ name/symbol). ``active`` = the cutting one;
    ``hidden`` = its frame is not drawn (nor picked) — the cut, if it is
    the active one, stays. Hidden and inactive is a plane switched off."""

    __slots__ = ("point", "normal", "name", "symbol", "active", "uid",
                 "hidden", "fill", "layer")

    def __init__(self, point: QVector3D, normal: QVector3D,
                 name: str = "", symbol: str = "",
                 active: bool = False, uid: int | None = None,
                 hidden: bool = False) -> None:
        self.point = QVector3D(point)
        n = QVector3D(normal)
        if n.length() < 1e-12:
            n = QVector3D(0.0, 0.0, 1.0)
        self.normal = n.normalized()
        self.name = name
        self.symbol = symbol
        self.active = bool(active)
        self.hidden = bool(hidden)
        #: This cut's own fill, over the display style's: ``{"pattern":
        #: "solid" | "hatch" | "cross" | "none", "color": (r, g, b),
        #: "spacing": metres}``, each key optional — what is missing comes
        #: from the style. ``None``: the style's fill as it is.
        self.fill = None
        #: Layer name (None = the default layer). A hidden layer takes the
        #: plane away and switches its cut off; a scene that hides it does
        #: the same (#316).
        self.layer = None
        #: Stable identity for scenes (.igz SavedView references) — survives
        #: reordering and deletion of OTHER planes.
        self.uid = _take_uid(uid)

    def flip(self) -> None:
        """Reverse: the cut hides the other side."""
        self.normal = -self.normal

    def side(self, p: QVector3D) -> float:
        """Signed distance: > 0 is the HIDDEN side (the normal's side)."""
        return QVector3D.dotProduct(self.normal, p - self.point)

    # ---- Serialisation (.igz) ------------------------------------------------
    def to_dict(self) -> dict:
        entry = {
            "point": [self.point.x(), self.point.y(), self.point.z()],
            "normal": [self.normal.x(), self.normal.y(), self.normal.z()],
            "uid": self.uid,
        }
        if self.name:
            entry["name"] = self.name
        if self.symbol:
            entry["symbol"] = self.symbol
        if self.active:
            entry["active"] = True
        if self.hidden:
            entry["hidden"] = True          # older readers ignore it
        if self.layer:
            entry["layer"] = self.layer   # older readers ignore it
        if self.fill:
            entry["fill"] = {k: (list(v) if k == "color" else v)
                             for k, v in self.fill.items()}
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "SectionPlane":
        sp = cls(QVector3D(*raw["point"]), QVector3D(*raw["normal"]),
                 name=raw.get("name", ""), symbol=raw.get("symbol", ""),
                 active=bool(raw.get("active", False)),
                 uid=raw.get("uid"), hidden=bool(raw.get("hidden", False)))
        if isinstance(raw.get("layer"), str) and raw["layer"]:
            sp.layer = raw["layer"]
        fill = raw.get("fill")
        if isinstance(fill, dict):
            clean = {}
            if fill.get("pattern") in FILL_PATTERNS:
                clean["pattern"] = fill["pattern"]
            if isinstance(fill.get("color"), (list, tuple)) \
                    and len(fill["color"]) >= 3:
                clean["color"] = tuple(float(c) for c in fill["color"][:3])
            if isinstance(fill.get("spacing"), (int, float)) \
                    and fill["spacing"] > 0:
                clean["spacing"] = float(fill["spacing"])
            sp.fill = clean or None
        return sp

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        state = " ACTIVE" if self.active else ""
        return f"SectionPlane({self.symbol or self.uid}{state})"


# ---- The cut, as geometry --------------------------------------------------

def cut_chords(v0, e1, e2, normal, point, visible=None):
    """The chords the plane cuts out of triangles given as ``v0`` + edge
    vectors ``e1``/``e2`` ((N, 3) arrays, as the pick index keeps them):
    an (K, 2, 3) float32 array, or ``None`` when the plane misses them all.
    ``visible`` (N bools) leaves hidden triangles out."""
    import numpy as np
    if v0 is None or not len(v0):
        return None
    nv = np.array([normal.x(), normal.y(), normal.z()], dtype=np.float64)
    c = float(np.dot(nv, [point.x(), point.y(), point.z()]))
    p0 = np.asarray(v0, dtype=np.float64)
    p1 = p0 + e1
    p2 = p0 + e2
    d0 = p0 @ nv - c
    d1 = p1 @ nv - c
    d2 = p2 @ nv - c
    pts = []
    for (a, b, da, db) in ((p0, p1, d0, d1), (p1, p2, d1, d2),
                           (p2, p0, d2, d0)):
        cross = (da * db) < 0
        t = np.zeros(len(da))
        np.divide(da, da - db, out=t, where=cross)
        pts.append((cross, a + (b - a) * t[:, None]))
    two = (pts[0][0].astype(np.int8) + pts[1][0] + pts[2][0]) == 2
    if visible is not None:
        two &= visible
    if not two.any():
        return None
    acc = np.zeros((int(two.sum()), 2, 3))
    slot = np.zeros(int(two.sum()), dtype=np.int64)
    for cross, p in pts:
        m = cross[two]
        where = np.where(m)[0]
        acc[where, np.minimum(slot[where], 1)] = p[two][m]
        slot[where] += 1
    return acc.astype(np.float32)


def _plane_basis(normal):
    import numpy as np
    n = np.array([normal.x(), normal.y(), normal.z()], dtype=np.float64)
    n /= np.linalg.norm(n) or 1.0
    helper = (np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9
              else np.array([0.0, 1.0, 0.0]))
    u = np.cross(n, helper)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def _inside(points, poly):
    """Even-odd point-in-polygon for many points: (K,) bools."""
    import numpy as np
    x = points[:, 0][:, None]
    y = points[:, 1][:, None]
    x1, y1 = poly[:, 0][None, :], poly[:, 1][None, :]
    x2 = np.roll(poly[:, 0], -1)[None, :]
    y2 = np.roll(poly[:, 1], -1)[None, :]
    straddle = (y1 > y) != (y2 > y)
    dy = np.where(y2 == y1, 1.0, y2 - y1)
    xint = x1 + (y - y1) * (x2 - x1) / dy
    return ((straddle & (x < xint)).sum(axis=1) % 2) == 1


def _fill_groups(chords, normal):
    """The filled areas of a cut: ``([(rings3d, rings2d)], (u, v))`` —
    each area an outer ring followed by its holes, in world and in plane
    coordinates — or ``([], None)``. See :func:`fill_triangles` for the
    rule."""
    import numpy as np
    from core.hlr import section_loops
    if chords is None or not len(chords):
        return [], None
    rings = section_loops(chords)
    if not rings:
        return [], None
    u, v = _plane_basis(normal)
    flat = [np.stack([r @ u, r @ v], axis=1) for r in rings]
    area = np.array([abs(0.5 * float(np.dot(f[:, 0], np.roll(f[:, 1], -1))
                                     - np.dot(f[:, 1], np.roll(f[:, 0], -1))))
                     for f in flat])
    lo = np.array([f.min(axis=0) for f in flat])
    hi = np.array([f.max(axis=0) for f in flat])
    count = len(rings)
    # Which rings hold ring i: a larger ring whose box holds i's box (one
    # vectorised pass over all of them), then i's vertices inside it — a
    # ring touching another only along a wall face is not nested in it.
    holders: list = [[] for _ in range(count)]
    for i in range(count):
        cand = np.nonzero((area > area[i]) & (lo <= lo[i]).all(axis=1)
                          & (hi >= hi[i]).all(axis=1))[0]
        for j in cand:
            if _inside(flat[i], flat[j]).mean() >= 0.9:
                holders[i].append(int(j))
    depth = [len(h) for h in holders]
    parent = [min(h, key=lambda j: area[j]) if h else None for h in holders]
    holes_of: dict = {}
    for k in range(count):
        if depth[k] % 2 and parent[k] is not None:
            holes_of.setdefault(parent[k], []).append(k)
    groups = []
    for i in range(count):
        if depth[i] % 2:
            continue                        # a hole, cut out of its parent
        members = [i] + holes_of.get(i, [])
        groups.append(([rings[k] for k in members],
                       [flat[k] for k in members]))
    return groups, (u, v)


def fill_triangles(chords, normal):
    """The section fill as triangles ((T, 3, 3) float32): ONLY the cut
    geometry — the closed outlines the plane slices out of solids, with
    their holes left open (a hollow wall, a ring of walls around a room).

    Built like the composer's poché (``core.hlr.section_loops``): chords
    chained into closed rings, an open chain (a lone face, an open surface)
    dropped instead of filled. A ring inside another is a hole, and one
    inside that hole is solid again; rings that merely overlap (two walls
    crossing at a corner) are both filled — their union."""
    import numpy as np
    from core.triangulate import earcut
    empty = np.zeros((0, 3, 3), dtype=np.float32)
    groups, _basis = _fill_groups(chords, normal)
    parts: list = []
    for rings3, rings2 in groups:
        pts2: list = []
        starts: list = []
        for k, f in enumerate(rings2):
            if k:
                starts.append(len(pts2))
            pts2.extend(f.tolist())
        idx = earcut(pts2, starts)
        if idx:
            parts.append(np.concatenate(rings3)[np.asarray(idx)])
    if not parts:
        return empty
    return np.concatenate(parts).astype(np.float32)


def hatch_segments(chords, normal, spacing: float, cross: bool = False):
    """Hatching for the cut: (L, 2, 3) float32 world segments at 45° in the
    plane (and at 135° too when ``cross``), ``spacing`` apart, clipped to
    the same areas :func:`fill_triangles` fills — each with its holes,
    even-odd, so the lines stop at a hollow and at the room."""
    import numpy as np
    empty = np.zeros((0, 2, 3), dtype=np.float32)
    groups, basis = _fill_groups(chords, normal)
    if not groups or spacing <= 0:
        return empty
    u, v = basis
    n = np.cross(u, v)
    # Every ring point lies in the plane: they share their offset along n.
    off = float(np.dot(groups[0][0][0][0], n)) * n
    out: list = []
    for ang in ((45.0, 135.0) if cross else (45.0,)):
        t = np.radians(ang)
        d = np.array([np.cos(t), np.sin(t)])         # along a line
        m = np.array([-d[1], d[0]])                  # across, line to line
        for _rings3, rings2 in groups:
            # Lines at multiples of ``spacing`` from the plane's origin:
            # neighbouring areas hatch as one pattern.
            s_all = np.concatenate(rings2) @ m
            k0 = int(np.ceil(s_all.min() / spacing))
            k1 = int(np.floor(s_all.max() / spacing))
            if k1 - k0 > 20000:
                continue                     # too fine to mean anything
            edges = [(f, np.roll(f, -1, axis=0)) for f in rings2]
            for k in range(k0, k1 + 1):
                s = k * spacing
                hits: list = []
                for a, b in edges:
                    sa, sb = a @ m - s, b @ m - s
                    crossing = (sa > 0) != (sb > 0)
                    if not crossing.any():
                        continue
                    tt = sa[crossing] / (sa[crossing] - sb[crossing])
                    p = a[crossing] + (b[crossing] - a[crossing]) * tt[:, None]
                    hits.extend((p @ d).tolist())
                hits.sort()
                for j in range(0, len(hits) - 1, 2):
                    p0 = d * hits[j] + m * s
                    p1 = d * hits[j + 1] + m * s
                    out.append((p0[0] * u + p0[1] * v + off,
                                p1[0] * u + p1[1] * v + off))
    if not out:
        return empty
    return np.asarray(out, dtype=np.float32)
