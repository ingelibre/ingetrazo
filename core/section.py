# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Section planes — slicing a model to peer inside.

A section plane is an object in the model: an origin + a unit normal. The
ACTIVE plane cuts the display — everything on the normal's side disappears
(``Reverse`` flips it). Only ONE plane can be the active cut in the model
context, the usual convention; placing a new plane makes it the active one.
Planes carry a name and a symbol shown on their frame.

A section box (:class:`SectionBox`, one per model) cuts with its six faces
at the same time, beside the active plane: only what lies inside it stays.
:func:`cut_planes` lists every plane that cuts now; :class:`CutSet` asks
them all at once.

The cut is display-only scaffolding, never topology: geometry is untouched,
the renderer clips (``gl_ClipDistance``), picks/snaps filter by the plane,
and the sheet composer's hidden-line pass clips before projecting — that is
the whole point of the track (real plans and cross-sections on the sheets).
The section box only cuts the viewport for now; the sheets follow the plane.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

_last_uid = 0

#: How a cut can be filled: solid, hatched at 45°, cross-hatched, not at
#: all, or each layer with its own hatch (``"layers"``, as the sheets draw
#: it).
FILL_PATTERNS = ("solid", "hatch", "cross", "none", "layers")
#: Hatch spacing when neither the plane nor anything else says: 5 cm in
#: the model, a wall of 20 cm reads as four lines.
DEFAULT_HATCH_SPACING = 0.05
#: The layers' hatches in the model are laid as a sheet at 1:50 lays them —
#: the usual scale of a plan or a section with its materials; bricks,
#: blocks and their joints keep their real size at any scale.
LAYER_HATCH_SCALE = 50.0
#: More hatch lines than this in one cut and the rest of its layers stay
#: solid: a pattern that fine reads as a tone anyway, and draws slowly.
LAYER_HATCH_MOST = 250000


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


def fill_to_dict(fill) -> dict:
    """A cut's own fill as the .igz writes it."""
    return {k: (list(v) if k == "color" else v) for k, v in fill.items()}


def fill_from_dict(fill):
    """A cut's own fill read back, keeping only what makes sense — or
    ``None`` (the style's fill)."""
    if not isinstance(fill, dict):
        return None
    clean = {}
    if fill.get("pattern") in FILL_PATTERNS:
        clean["pattern"] = fill["pattern"]
    if isinstance(fill.get("color"), (list, tuple)) \
            and len(fill["color"]) >= 3:
        clean["color"] = tuple(float(c) for c in fill["color"][:3])
    if isinstance(fill.get("spacing"), (int, float)) \
            and fill["spacing"] > 0:
        clean["spacing"] = float(fill["spacing"])
    return clean or None


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
            entry["fill"] = fill_to_dict(self.fill)
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "SectionPlane":
        sp = cls(QVector3D(*raw["point"]), QVector3D(*raw["normal"]),
                 name=raw.get("name", ""), symbol=raw.get("symbol", ""),
                 active=bool(raw.get("active", False)),
                 uid=raw.get("uid"), hidden=bool(raw.get("hidden", False)))
        if isinstance(raw.get("layer"), str) and raw["layer"]:
            sp.layer = raw["layer"]
        sp.fill = fill_from_dict(raw.get("fill"))
        return sp

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        state = " ACTIVE" if self.active else ""
        return f"SectionPlane({self.symbol or self.uid}{state})"


# ---- The section box ---------------------------------------------------------

#: The thinnest a section box gets along any axis: dragging a face past its
#: opposite stops here, so the box never turns inside out.
MIN_BOX_SIZE = 0.01


class BoxFace:
    """One face of a :class:`SectionBox` as a cutting plane: the same
    ``point``/``normal``/``side`` a :class:`SectionPlane` offers (the normal
    points OUT of the box — the hidden side) and the box's ``fill``.
    ``index`` is 0..5: −X, +X, −Y, +Y, −Z, +Z."""

    __slots__ = ("box", "index", "point", "normal")

    def __init__(self, box, index: int) -> None:
        self.box = box
        self.index = index
        axis, sign = divmod(index, 2)
        n = [0.0, 0.0, 0.0]
        n[axis] = 1.0 if sign else -1.0
        self.normal = QVector3D(*n)
        self.point = QVector3D(box.hi if sign else box.lo)

    @property
    def fill(self):
        return self.box.fill

    def side(self, p: QVector3D) -> float:
        return QVector3D.dotProduct(self.normal, p - self.point)


class SectionBox:
    """An axis-aligned box that keeps only what lies inside it: six cuts at
    once, beside the active section plane. ``lo``/``hi`` are its opposite
    corners; ``active`` = it cuts; ``hidden`` = its frame is not drawn.
    A model keeps any number of them (``scene.section_boxes``), named, and
    ONE cuts at a time — as with section planes: a box ready per detail,
    each scene bringing its own."""

    __slots__ = ("lo", "hi", "active", "hidden", "fill", "name", "uid")

    def __init__(self, lo: QVector3D, hi: QVector3D, active: bool = True,
                 hidden: bool = False, name: str = "",
                 uid: int | None = None) -> None:
        a, b = QVector3D(lo), QVector3D(hi)
        self.lo = QVector3D(min(a.x(), b.x()), min(a.y(), b.y()),
                            min(a.z(), b.z()))
        self.hi = QVector3D(max(a.x(), b.x()), max(a.y(), b.y()),
                            max(a.z(), b.z()))
        self.active = bool(active)
        self.hidden = bool(hidden)
        #: The cut's own fill, as on a section plane; ``None`` = the style's.
        self.fill = None
        self.name = name
        #: Stable identity for scenes — the same counter as the planes'.
        self.uid = _take_uid(uid)

    @classmethod
    def around(cls, lo: QVector3D, hi: QVector3D,
               margin: float = 0.05) -> "SectionBox":
        """A box enclosing ``lo``..``hi`` with a margin of ``margin`` of the
        largest side on every face (at least 1 cm), so nothing it is made
        for starts out cut."""
        span = max(hi.x() - lo.x(), hi.y() - lo.y(), hi.z() - lo.z(), 0.0)
        m = max(span * margin, 0.01)
        pad = QVector3D(m, m, m)
        return cls(lo - pad, hi + pad)

    def copy(self) -> "SectionBox":
        """The same box's state, as a value (it keeps the uid: a copy is
        a state to assign back, never a second box in the model)."""
        box = SectionBox.__new__(SectionBox)
        box.lo, box.hi = QVector3D(self.lo), QVector3D(self.hi)
        box.active, box.hidden = self.active, self.hidden
        box.fill = dict(self.fill) if self.fill else None
        box.name, box.uid = self.name, self.uid
        return box

    def assign(self, other: "SectionBox") -> None:
        """Take ``other``'s corners, switches and fill, staying the same
        object — what the Browser row, the selection and an undo step
        holding this box keep pointing at."""
        self.lo, self.hi = QVector3D(other.lo), QVector3D(other.hi)
        self.active, self.hidden = other.active, other.hidden
        self.fill = dict(other.fill) if other.fill else None
        self.name = other.name

    def same_as(self, other) -> bool:
        """Same corners and switches — what makes an edit a no-op."""
        return (other is not None and self.lo == other.lo
                and self.hi == other.hi and self.active == other.active
                and self.hidden == other.hidden and self.fill == other.fill
                and self.name == other.name)

    def faces(self) -> list:
        return [BoxFace(self, i) for i in range(6)]

    def corners(self) -> list:
        """The eight corners; bit 0/1/2 of the index picks hi in x/y/z."""
        lo, hi = self.lo, self.hi
        return [QVector3D(hi.x() if i & 1 else lo.x(),
                          hi.y() if i & 2 else lo.y(),
                          hi.z() if i & 4 else lo.z()) for i in range(8)]

    def face_value(self, index: int) -> float:
        """Where face ``index`` stands along its axis."""
        axis, sign = divmod(index, 2)
        p = self.hi if sign else self.lo
        return (p.x(), p.y(), p.z())[axis]

    def with_face(self, index: int, value: float) -> "SectionBox":
        """A copy with face ``index`` moved to ``value`` along its axis,
        stopped :data:`MIN_BOX_SIZE` short of the opposite face."""
        axis, sign = divmod(index, 2)
        box = self.copy()
        lo = [box.lo.x(), box.lo.y(), box.lo.z()]
        hi = [box.hi.x(), box.hi.y(), box.hi.z()]
        if sign:
            hi[axis] = max(float(value), lo[axis] + MIN_BOX_SIZE)
        else:
            lo[axis] = min(float(value), hi[axis] - MIN_BOX_SIZE)
        box.lo, box.hi = QVector3D(*lo), QVector3D(*hi)
        return box

    def side(self, p: QVector3D) -> float:
        """> 0 outside the box (hidden): the distance beyond the farthest
        face plane."""
        return max(f.side(p) for f in self.faces())

    def to_dict(self) -> dict:
        entry = {"lo": [self.lo.x(), self.lo.y(), self.lo.z()],
                 "hi": [self.hi.x(), self.hi.y(), self.hi.z()],
                 "uid": self.uid}
        if self.name:
            entry["name"] = self.name
        if not self.active:
            entry["active"] = False
        if self.hidden:
            entry["hidden"] = True
        if self.fill:
            entry["fill"] = fill_to_dict(self.fill)
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "SectionBox":
        box = cls(QVector3D(*raw["lo"]), QVector3D(*raw["hi"]),
                  active=bool(raw.get("active", True)),
                  hidden=bool(raw.get("hidden", False)),
                  name=str(raw.get("name", "") or ""), uid=raw.get("uid"))
        box.fill = fill_from_dict(raw.get("fill"))
        return box

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return f"SectionBox({self.name or self.uid}: {self.lo} .. {self.hi})"


def box_face_quad(box, index: int) -> list:
    """The four world corners of face ``index`` of ``box``, in order
    around it."""
    c = box.corners()
    axis, sign = divmod(index, 2)
    base = (1 << axis) if sign else 0
    # Walk the other two bits as a square: 00, 01, 11, 10.
    a, b = [1 << k for k in range(3) if k != axis]
    return [c[base], c[base | a], c[base | a | b], c[base | b]]


def box_face_hit(box, origin: QVector3D, direction: QVector3D):
    """``(index, t)`` of the face of ``box`` a ray meets first — the face
    in front from outside the box, the face ahead from inside it — or
    ``None`` when the ray misses the box."""
    o = (origin.x(), origin.y(), origin.z())
    d = (direction.x(), direction.y(), direction.z())
    lo = (box.lo.x(), box.lo.y(), box.lo.z())
    hi = (box.hi.x(), box.hi.y(), box.hi.z())
    best = None
    for index in range(6):
        axis, sign = divmod(index, 2)
        if abs(d[axis]) < 1e-12:
            continue
        t = ((hi if sign else lo)[axis] - o[axis]) / d[axis]
        if t <= 1e-9 or (best is not None and t >= best[1]):
            continue
        p = [o[k] + d[k] * t for k in range(3)]
        tol = 1e-7 * max(1.0, *(abs(v) for v in lo + hi))
        if all(lo[k] - tol <= p[k] <= hi[k] + tol
               for k in range(3) if k != axis):
            best = (index, t)
    return best


def box_arrows(box, length: float) -> list:
    """``(index, base, tip)`` of the six push/pull arrows of ``box``: from
    the centre of each face, ``length`` straight out of it."""
    out = []
    for index in range(6):
        q = box_face_quad(box, index)
        c = (q[0] + q[2]) * 0.5
        axis, sign = divmod(index, 2)
        n = [0.0, 0.0, 0.0]
        n[axis] = 1.0 if sign else -1.0
        out.append((index, c, c + QVector3D(*n) * length))
    return out


class CutSet:
    """Everything that cuts the model at once: the active section plane
    and the faces of an active section box. A point is HIDDEN when it lies
    on the hidden side of any of them — ``side`` is the largest signed
    distance, the same contract as :meth:`SectionPlane.side`."""

    __slots__ = ("planes",)

    def __init__(self, planes) -> None:
        self.planes = list(planes)

    def side(self, p: QVector3D) -> float:
        return max(sp.side(p) for sp in self.planes)

    def distances(self, pts):
        """(K,) largest signed distance of each of the (K, 3) points."""
        import numpy as np
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        out = np.full(len(pts), -np.inf)
        for sp in self.planes:
            n = np.array([sp.normal.x(), sp.normal.y(), sp.normal.z()])
            c = float(n @ [sp.point.x(), sp.point.y(), sp.point.z()])
            out = np.maximum(out, pts @ n - c)
        return out

    def hidden(self, pts, tol: float = 1e-6):
        """(K,) bools: which of the (K, 3) points the cut hides."""
        return self.distances(pts) > tol


def annotation_points(entity) -> list:
    """The points where an annotation stands in the model, for the section
    box to keep or leave out: a dimension's two measured points, a text's
    anchor, a guide POINT, a survey point. ``[]`` for anything else — a
    guide LINE runs through any box, and the cut takes care of geometry."""
    from core.dimension import Dimension
    from core.guide import Guide
    from core.textlabel import TextLabel
    if isinstance(entity, Dimension):
        return [entity.a, entity.b]
    if isinstance(entity, TextLabel):
        return [entity.anchor]
    if isinstance(entity, Guide):
        return [] if entity.is_line else [entity.point]
    position = getattr(entity, "position", None)
    if type(entity).__name__ == "GeoPoint" and position is not None:
        return [position]
    return []


def cut_planes(scene) -> list:
    """The planes cutting the model now, in a fixed order — the active
    section plane first, then the six faces of the active section box — or
    ``[]``. Section Cuts off cuts nothing at all."""
    if not getattr(scene, "show_section_cuts", True):
        return []
    planes = []
    active = getattr(scene, "active_section", None)
    sp = active() if callable(active) else None
    if sp is not None:
        planes.append(sp)
    active_box = getattr(scene, "active_section_box", None)
    box = active_box() if callable(active_box) else None
    if box is not None:
        planes.extend(box.faces())
    return planes


# ---- The cut, as geometry --------------------------------------------------

def plane_pair_line(a, b, chords):
    """Where two cuts meet inside the material: the stretches of the line
    ``a`` ∩ ``b`` that lie inside the closed section rings ``chords`` of
    ``a`` ((K, 2, 3), as :func:`cut_chords`), as an (M, 2, 3) float64 array
    — or ``None`` for parallel planes or no material there. No edge of the
    model runs along it: the two cuts make it, so nothing else draws it.

    Even-odd along the line: every chord that crosses it opens or closes a
    stretch, so a hollow wall gives two. One side of the line counts as
    strictly positive, so a ring's vertex on the line is counted once."""
    import numpy as np
    if chords is None or not len(chords):
        return None
    na = np.array([a.normal.x(), a.normal.y(), a.normal.z()], dtype=np.float64)
    nb = np.array([b.normal.x(), b.normal.y(), b.normal.z()], dtype=np.float64)
    d = np.cross(na, nb)
    dd = float(d @ d)
    if dd < 1e-12:
        return None
    ca = float(na @ [a.point.x(), a.point.y(), a.point.z()])
    cb = float(nb @ [b.point.x(), b.point.y(), b.point.z()])
    origin = (ca * np.cross(nb, d) + cb * np.cross(d, na)) / dd
    across = np.cross(d, na)             # in plane a, square to the line
    pts = np.asarray(chords, dtype=np.float64).reshape(-1, 2, 3)
    s0 = (pts[:, 0] - origin) @ across
    s1 = (pts[:, 1] - origin) @ across
    hit = (s0 > 0.0) != (s1 > 0.0)
    if not hit.any():
        return None
    p0, p1 = pts[hit, 0], pts[hit, 1]
    f = (s0[hit] / (s0[hit] - s1[hit]))[:, None]
    ts = np.sort(((p0 + (p1 - p0) * f) - origin) @ d)
    pairs = ts[:len(ts) // 2 * 2].reshape(-1, 2)     # an open ring: left out
    pairs = pairs[pairs[:, 1] - pairs[:, 0] > 1e-9]
    if not len(pairs):
        return None
    out = np.empty((len(pairs), 2, 3), dtype=np.float64)
    out[:, 0] = origin + pairs[:, 0, None] * d
    out[:, 1] = origin + pairs[:, 1, None] * d
    return out


def cut_chords(v0, e1, e2, normal, point, visible=None, rows=False,
               reach=None):
    """The chords the plane cuts out of triangles given as ``v0`` + edge
    vectors ``e1``/``e2`` ((N, 3) arrays, as the pick index keeps them):
    an (K, 2, 3) float32 array, or ``None`` when the plane misses them all.
    ``visible`` (N bools) leaves hidden triangles out. ``rows=True`` returns
    ``(chords, triangle index of each)`` — whose layer each chord is.
    ``reach``: a :class:`PlaneReach` of these very triangles and this
    normal, kept between calls — a plane slid along its normal (a section
    dragged by its arrow) then only measures where it now stands.

    A cut through a vertex is the ordinary case: a box face pulled level
    with a corner, a slab cut along the edge of its opening. A point ON the
    plane counts as on the kept side, the same for every triangle, so the
    rings stay closed; a strict «one end each side» test lost those chords,
    and the cut's line came in pieces and its fill not at all. The distances
    snap to zero within a hair, or the rounding of one vertex, different in
    each triangle that holds it, would put it on both sides."""
    if v0 is None or not len(v0):
        return (None, None) if rows else None
    if reach is None or not reach.fits(v0, normal, e1, e2):
        reach = PlaneReach(v0, e1, e2, normal)
    return reach.cut(point, visible, rows)


class PlaneReach:
    """The corners of a set of triangles and how far along one normal each
    stands — what every cut by a plane of that normal starts from. Sliding
    the plane only moves the offset: the triangles it crosses are found by
    comparing three arrays with it, and only those are cut.

    The chords are those :func:`cut_chords` always made, in the same order
    and to the bit: the same differences, the same side test."""

    __slots__ = ("_v0", "_e1", "_e2", "_n", "p0", "p1", "p2", "h0", "h1", "h2", "lo",
                 "hi", "_nv")

    def __init__(self, v0, e1, e2, normal) -> None:
        import numpy as np
        self._v0, self._e1, self._e2 = v0, e1, e2
        self._n = (normal.x(), normal.y(), normal.z())
        self._nv = np.array(self._n, dtype=np.float64)
        self.p0 = np.asarray(v0, dtype=np.float64)
        self.p1 = self.p0 + e1
        self.p2 = self.p0 + e2
        self.h0 = self.p0 @ self._nv
        self.h1 = self.p1 @ self._nv
        self.h2 = self.p2 @ self._nv
        self.lo = np.minimum(np.minimum(self.h0, self.h1), self.h2)
        self.hi = np.maximum(np.maximum(self.h0, self.h1), self.h2)

    def fits(self, v0, normal, e1=None, e2=None) -> bool:
        """Made from these very arrays (the pick index never writes into
        its own: a changed model is new arrays) and this normal."""
        return (v0 is self._v0
                and (e1 is None or e1 is self._e1)
                and (e2 is None or e2 is self._e2)
                and (normal.x(), normal.y(), normal.z()) == self._n)

    def cut(self, point, visible=None, rows=False):
        import numpy as np
        c = float(np.dot(self._nv, [point.x(), point.y(), point.z()]))
        hair = max(1e-5, abs(c) * 1e-6)
        # Only a triangle with corners on both sides can have an edge that
        # crosses: the rest is never cut, whatever the plane's offset. ON
        # the plane (within a hair) is the kept side (see cut_chords).
        near = np.nonzero((self.lo - c <= hair) & (self.hi - c > hair))[0]
        if visible is not None and len(near):
            near = near[np.asarray(visible)[near]]
        if not len(near):
            return (None, None) if rows else None
        p0, p1, p2 = self.p0[near], self.p1[near], self.p2[near]

        def dist(h):
            d = h[near] - c
            d[np.abs(d) < hair] = 0.0
            return d

        d0, d1, d2 = dist(self.h0), dist(self.h1), dist(self.h2)
        pts = []
        for (a, b, da, db) in ((p0, p1, d0, d1), (p1, p2, d1, d2),
                               (p2, p0, d2, d0)):
            cross = (da > 0.0) != (db > 0.0)
            t = np.zeros(len(da))
            np.divide(da, da - db, out=t, where=cross)
            pts.append((cross, a + (b - a) * t[:, None]))
        two = (pts[0][0].astype(np.int8) + pts[1][0] + pts[2][0]) == 2
        if not two.any():
            return (None, None) if rows else None
        acc = np.zeros((int(two.sum()), 2, 3))
        slot = np.zeros(int(two.sum()), dtype=np.int64)
        for cross, p in pts:
            m = cross[two]
            where = np.where(m)[0]
            acc[where, np.minimum(slot[where], 1)] = p[two][m]
            slot[where] += 1
        if rows:
            return acc.astype(np.float32), near[two]
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
    groups, _basis = _fill_groups(chords, normal)
    return _group_triangles(groups)


def _group_triangles(groups):
    """The areas of :func:`_fill_groups` as triangles ((T, 3, 3) float32)."""
    import numpy as np
    from core.triangulate import earcut
    empty = np.zeros((0, 3, 3), dtype=np.float32)
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


def _sheet_basis(normal):
    """``(u, v)`` across a cut as a sheet looks at it: a plan with x east
    and y north, a section with v straight up — so courses of brick lie
    level and a pattern keeps the turn the sheet gives it."""
    import numpy as np
    n = np.array([normal.x(), normal.y(), normal.z()], dtype=np.float64)
    n /= np.linalg.norm(n) or 1.0
    if abs(n[2]) >= 0.7:                             # a plan
        u = np.array([1.0, 0.0, 0.0]) - n * n[0]
        u /= np.linalg.norm(u) or 1.0
        return u, np.cross(n, u)
    v = np.array([0.0, 0.0, 1.0]) - n * n[2]
    v /= np.linalg.norm(v) or 1.0
    u = np.cross(v, n)
    return u / (np.linalg.norm(u) or 1.0), v


def layer_fills(chords, tags, normal, scene, color,
                scale_n: float = LAYER_HATCH_SCALE) -> list:
    """The cut filled layer by layer — each with its layer's hatch, as a
    sheet at 1:``scale_n`` draws it (bricks laid by the cut and the wall's
    thickness, timber, insulation…): a list of ``(triangles, rgb, lines,
    ink)`` — the (T, 3, 3) fill in ``rgb`` and the (L, 2, 3) hatch lines
    over it in ``ink``, world space. ``tags`` gives each chord's layer.

    A layer without a hatch, and one whose hatch sets no ink («as the
    frame says»), takes ``color`` — the plane's own fill; a hatch lies on
    its layer's ground, or on a pale tone of its ink (the paper of a
    sheet)."""
    import numpy as np
    from core.hatches import hatch_lines
    from core.hlr import closing_tags, section_loops
    from core.layers import cut_hatch_forms, cut_hatches, hatch_ground_rgb,         hatch_ink_rgb
    if chords is None or not len(chords):
        return []
    # A solid of more than one layer is filled as the layer of most of it.
    tags = np.asarray(closing_tags(chords, tags), dtype=object)
    hatches = cut_hatches(scene)
    forms = cut_hatch_forms(scene, scale_n)
    u, v = _sheet_basis(normal)
    n = np.cross(u, v)
    k = 1000.0 / float(scale_n or LAYER_HATCH_SCALE)    # paper mm per metre
    cut = "plan" if abs(normal.z()) >= 0.7 else "vertical"
    color = tuple(float(c) for c in color[:3])
    plain: list = []
    out: list = []
    budget = LAYER_HATCH_MOST
    for tag in sorted({str(t) for t in tags}):
        mine = chords[tags == tag]
        key = hatches.get(tag)
        if not key:
            plain.append(mine)
            continue
        groups, _basis = _fill_groups(mine, normal)
        tris = _group_triangles(groups)
        if not len(tris):
            continue
        ly = scene.layer(tag) if hasattr(scene, "layer") else None
        ink = tuple((hatch_ink_rgb(ly) if ly is not None else None)
                    or color)
        if key == "solid":
            out.append((tris, ink, None, ink))
            continue
        ground = hatch_ground_rgb(ly) if ly is not None else None
        ground = tuple(ground) if ground is not None else tuple(
            c + (1.0 - c) * 0.85 for c in ink)
        form = dict(forms.get(tag, {}), cut=cut)
        off = float(np.dot(groups[0][0][0][0], n)) * n
        segs: list = []
        for rings3, _rings2 in groups:
            if budget <= 0:
                break
            paper = [[(float(p @ u) * k, -float(p @ v) * k) for p in r]
                     for r in rings3]
            got = hatch_lines(key, paper, form)
            budget -= len(got)
            segs += got
        lines = None
        if segs:
            a = np.asarray(segs, dtype=np.float64) / k
            lines = np.stack([off + a[:, 0:1] * u - a[:, 1:2] * v,
                              off + a[:, 2:3] * u - a[:, 3:4] * v], axis=1)
            lines = lines.astype(np.float32)
        out.append((tris, ground, lines, ink))
    if plain:
        tris = _group_triangles(_fill_groups(np.concatenate(plain),
                                             normal)[0])
        if len(tris):
            out.insert(0, (tris, color, None, color))
    return out
