# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Linear dimension — a measured annotation between two world points.

A ``Dimension`` records two endpoints ``a``/``b`` and an ``offset`` vector
giving where the dimension line sits relative to the measured segment.

An endpoint placed ON a vertex is **anchored** to it (a dimension belongs to
the geometry it measures): the endpoint reads the vertex's
position live, so scaling, moving or stretching the drawing takes the
dimension along and re-measures it — the first thing a user of DriveMeca's
video missed (2026-09-20, Marco: «dibujamos algo, lo acotamos, después lo
escalamos y la acotación se queda allí, no se redimensiona con el dibujo
y no se actualiza la nueva medición»). A vertex inside a component reads
through its placement's transform, so moving the instance moves the
dimension too. When the vertex is gone (erased, welded away) the endpoint
freezes where it last was. An endpoint snapped to a midpoint, an edge or a
face has no vertex to hold and stays static.

It is an annotation, not geometry: it lives in ``Scene.dimensions`` and is
drawn as a screen-space overlay (extension lines + dimension line + value
label), not in the mesh.

Two kinds, the usual convention: **aligned** (``axis`` is None) — the dimension
line parallel to a–b, measuring its length — and **linear** (``axis`` is
``"x"``/``"y"``/``"z"``) — the dimension line parallel to that axis,
measuring the segment's extent along it, the extension lines square to the
axis. A slanted line dimensioned by pulling the cursor to its SIDE gives
the vertical extent, pulling ABOVE gives the horizontal one, pulling square
off the line gives the aligned length (@pacaeiro, issue #50: «the Dimension
tool should be able to measure aligned (as it does now), but also linear»).
"""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D


#: Holds an endpoint remembers (see Dimension._live).
_MAX_HOLDS = 8


class VertexAnchor:
    """A hold on one mesh vertex: the vertex, the mesh that registers it
    (to notice when it is gone) and the chain of groups whose transforms
    place it in the world — empty for loose geometry, ``[group]`` for a
    classic group, ``[component, child, …]`` down a nested placement."""

    __slots__ = ("vertex", "mesh", "chain")

    def __init__(self, vertex, mesh, chain=()) -> None:
        self.vertex = vertex
        self.mesh = mesh
        self.chain = tuple(chain)

    def matrix(self):
        """The composed placement transform, or ``None`` when every group
        on the chain keeps its geometry in world coordinates."""
        m = None
        for g in self.chain:
            x = getattr(g, "xform", None)
            if x is None:
                continue
            m = QMatrix4x4(x) if m is None else m * x
        return m

    def alive(self, scene=None) -> bool:
        """Whether the hold still means something: the mesh registers this
        very vertex (not erased, not welded into another one), something
        references it, and — given the scene — the mesh is still part of
        the model: the loose mesh, or a group the scene still lists. A
        group exploded, or grouped into another, leaves its old mesh
        behind with the vertex in it, positions frozen for ever."""
        v = self.vertex
        try:
            if self.mesh.vertex_at(v.position) is not v or not v.edges:
                return False
        except Exception:  # noqa: BLE001 — a mesh that cannot answer
            return False
        if scene is None:
            return True
        if not self.chain:
            return self.mesh is getattr(scene, "loose_mesh", scene.mesh)
        if self.mesh is not getattr(self.chain[-1], "mesh", None):
            # The group holds another mesh now: entering a component swaps
            # the instance onto a world copy of its definition (placement
            # cleared), leaving swaps it back. Read through the chain, the
            # old mesh would land a placement off (#621).
            return False
        return self.chain[0] in (getattr(scene, "groups", None) or ())

    def position(self, scene=None):
        """The vertex's world position now — ``None`` once the hold is no
        longer :meth:`alive`, which is the anchor's cue to let go."""
        if not self.alive(scene):
            return None
        v = self.vertex
        m = self.matrix()
        return m.map(QVector3D(v.position)) if m is not None \
            else QVector3D(v.position)


def resolve_vertex_anchor(scene, point: QVector3D, tol: float = 1e-4):
    """The vertex sitting at *point* (world), as a :class:`VertexAnchor`,
    or ``None``. Loose geometry first, then every group placement, the
    point taken back into each placement's local coordinates — O(1) per
    mesh through the vertex registry, so a click costs nothing on a big
    model. ``tol`` is the registry's own weld resolution (0.1 mm): a
    point that came through a placement's float32 matrix and back lands
    within a micron of the vertex, which a tighter tolerance rejected on
    far-out coordinates."""
    from core.group import iter_placements

    def hit(mesh, local, chain):
        v = mesh.vertex_at(local)
        if v is None or (v.position - local).length() > tol:
            return None
        if not v.edges:
            # An orphan: a vertex nothing references any more. Make Group
            # moves the geometry into the group's mesh and leaves these
            # behind in the loose one, at the very same spots — so a
            # dimension on a fresh group anchored to the ghost, and the
            # group scaled away from under it (Marco, 2026-09-20: «faltaba
            # en grupo»). A point held by nothing holds nothing.
            return None
        return VertexAnchor(v, mesh, chain)

    # The LOOSE mesh, not ``scene.mesh``: inside a group edit that is the
    # open group's, which the loop below finds with its chain — held as
    # loose, the anchor was dead from birth (#621).
    found = hit(getattr(scene, "loose_mesh", scene.mesh), QVector3D(point), ())
    if found is not None:
        return found
    for g in getattr(scene, "groups", None) or ():
        if getattr(g, "billboard", False):
            continue
        for placed, m in iter_placements(g):
            local = QVector3D(point)
            chain = _chain_to(g, placed)
            if m is not None:
                inv, ok = m.inverted()
                if not ok:
                    continue
                local = inv.map(local)
            found = hit(placed.mesh, local, chain)
            if found is not None:
                return found
    return None


def _chain_to(root, target) -> tuple:
    """The groups from *root* down to *target* (inclusive) — the transforms
    an anchor composes. Depth-first, like ``iter_placements``."""
    if root is target:
        return (root,)
    for child in getattr(root, "children", None) or ():
        below = _chain_to(child, target)
        if below:
            return (root,) + below
    return ()


_AXIS_VECTORS = {
    "x": QVector3D(1.0, 0.0, 0.0),
    "y": QVector3D(0.0, 1.0, 0.0),
    "z": QVector3D(0.0, 0.0, 1.0),
}

#: A linear dimension is offered only when the segment makes at least this
#: angle with the axis (a near-parallel one reads the same as the aligned
#: dimension) and at most its complement (a near-square one measures
#: nothing). Between those, the two kinds say different things.
_LINEAR_MIN_DEG = 15.0

#: The cursor pulled square off the segment — within this angle of its
#: perpendicular, measured from the midpoint — always asks for the aligned
#: dimension, however far it goes: on a steep line a square pull soon
#: passes the lower endpoint's column, and without this corridor it would
#: turn into the vertical linear one under the drafter's hand.
_ALIGNED_CONE_DEG = 20.0


def _linear_frame(a: QVector3D, b: QVector3D, axis: str | None):
    """``(u, e)`` for a linear dimension along ``axis``: ``u`` the axis and
    ``e`` the extension-line direction — square to ``u``, in the plane of
    the axis and the segment. ``None`` for an aligned dimension, a
    degenerate segment, or a segment that runs along the axis (nothing to
    project; the dimension falls back to aligned)."""
    u = _AXIS_VECTORS.get(axis)
    if u is None:
        return None
    ab = b - a
    length = ab.length()
    if length < 1e-9:
        return None
    d = ab / length
    e = d - u * QVector3D.dotProduct(d, u)
    if e.length() < 1e-6:
        return None
    return u, e / e.length()


class Dimension:
    """See the module docstring. ``a`` and ``b`` read live through their
    anchors; assigning them sets the frozen position (what a rigid
    transform of the whole model does) and keeps the anchor."""

    def __init__(self, a: QVector3D, b: QVector3D, offset: QVector3D,
                 layer: str | None = None, text: str | None = None,
                 axis: str | None = None) -> None:
        self._a = QVector3D(a)
        self._b = QVector3D(b)
        #: displacement from the a–b segment to the dimension line
        self.offset = QVector3D(offset)
        #: ``None`` = aligned; ``"x"``/``"y"``/``"z"`` = linear along that
        #: world axis (see the module docstring).
        self.axis = axis if axis in _AXIS_VECTORS else None
        #: Layer (tag) the annotation lives on; ``None`` = default
        #: layer. Scenes hide layers, so a plan scene can show a clean model
        #: and an "Anotaciones" layer can carry the cotas and leader texts.
        self.layer = layer
        #: Custom text (double-click the value to edit it);
        #: ``None`` shows the measured value, and ``<>`` inside the text
        #: stands for it.
        self.text = text
        self.anchor_a: VertexAnchor | None = None
        self.anchor_b: VertexAnchor | None = None
        #: Every hold each endpoint has had, oldest first (see _live).
        self._holds: dict = {"a": [], "b": []}
        self._scene = None                   # set by bind(); re-binding

    # ---- endpoints ----------------------------------------------------------
    def _hold(self, which: str, anchor) -> None:
        """Make ``anchor`` the endpoint's hold and remember it."""
        setattr(self, "anchor_" + which, anchor)
        if anchor is None:
            return
        holds = self._holds_of(which)
        if not any(h.vertex is anchor.vertex and h.mesh is anchor.mesh
                   for h in holds):
            holds.append(anchor)
            del holds[:-_MAX_HOLDS]

    def _holds_of(self, which: str) -> list:
        holds = getattr(self, "_holds", None)
        if holds is None:
            holds = self._holds = {"a": [], "b": []}
        return holds[which]

    def _live(self, which: str) -> QVector3D:
        holds = self._holds_of(which)
        anchor = getattr(self, "anchor_" + which)
        if anchor is None and not holds:
            return getattr(self, "_" + which)
        scene = self._scene
        # The OLDEST hold still alive wins. A push collapsing the measured
        # edge welds its vertex into the one below, and the endpoint takes
        # that one; undo — or the next preview frame of the same drag —
        # brings the first vertex back, and the dimension must go back to
        # it, not stay on the one it fell onto (#254).
        for h in holds:
            p = h.position(scene)
            if p is not None:
                setattr(self, "anchor_" + which, h)
                setattr(self, "_" + which, p)
                return p
        if anchor is not None and anchor not in holds:
            p = anchor.position(scene)
            if p is not None:
                setattr(self, "_" + which, p)
                return p
        # The hold is gone — but the geometry may just have changed
        # hands: Make Group puts new vertices in the group's mesh at
        # the very spots the loose ones stood, Explode the other way
        # round (Marco, 2026-09-20: a cube dimensioned, then cube AND
        # dimension grouped, then scaled — «la cota no sigue»). Look
        # again where the endpoint last was; freeze only when nothing
        # stands there any more.
        frozen = getattr(self, "_" + which)
        again = (resolve_vertex_anchor(scene, frozen)
                 if scene is not None else None)
        p = again.position(scene) if again is not None else None
        if p is None:
            setattr(self, "anchor_" + which, None)
            return frozen
        self._hold(which, again)
        setattr(self, "_" + which, p)
        return p

    @property
    def a(self) -> QVector3D:
        return self._live("a")

    @a.setter
    def a(self, value: QVector3D) -> None:
        self._a = QVector3D(value)

    @property
    def b(self) -> QVector3D:
        return self._live("b")

    @b.setter
    def b(self, value: QVector3D) -> None:
        self._b = QVector3D(value)

    def bind(self, scene) -> None:
        """Anchor each endpoint to the vertex under it, if there is one —
        at placement, and again when a document is opened (the .igz keeps
        positions, and the vertex at that very position is the one the
        drafter snapped to)."""
        self._scene = scene
        self._holds = {"a": [], "b": []}
        self._hold("a", resolve_vertex_anchor(scene, self._a))
        self._hold("b", resolve_vertex_anchor(scene, self._b))

    def refresh_anchors(self, scene) -> None:
        """Re-take a hold that died — the vertex changed meshes — from the
        vertex now standing at the endpoint; the history calls this after
        every command, so a group made and scaled in one breath still
        carries its dimension. An endpoint never anchored stays static."""
        self._scene = scene
        for which in ("a", "b"):
            anchor = getattr(self, "anchor_" + which)
            if anchor is None and not self._holds_of(which):
                continue
            if any(h.alive(scene) for h in self._holds_of(which)):
                continue
            if anchor is not None and anchor.alive(scene):
                continue
            self._hold(which, resolve_vertex_anchor(
                scene, getattr(self, "_" + which)))

    @property
    def anchored(self) -> bool:
        """Both endpoints held by vertices."""
        return self.anchor_a is not None and self.anchor_b is not None

    def anchor_points(self) -> list:
        """The world positions of the anchored endpoints (0, 1 or 2)."""
        return [p for p, an in ((self.a, self.anchor_a), (self.b, self.anchor_b))
                if an is not None]

    # ---- geometry -----------------------------------------------------------
    def display_text(self, measured: str) -> str:
        """What the annotation shows: the custom text with ``<>`` swapped
        for the formatted measurement, or the measurement itself."""
        if self.text:
            return self.text.replace("<>", measured)
        return measured

    def value(self) -> float:
        """Measured length (metres): the segment's, or — linear — its extent
        along the axis."""
        frame = _linear_frame(self.a, self.b, self.axis)
        if frame is not None:
            return abs(QVector3D.dotProduct(self.b - self.a, frame[0]))
        return (self.b - self.a).length()

    def label(self) -> str:
        from core.units import fmt_len
        return fmt_len(self.value())

    def perpendicular_offset(self) -> QVector3D:
        """The offset with any component ALONG the measured segment
        removed: the geometry may have turned under an anchored dimension
        since it was placed, and the extension lines must stay square to
        the line (the line itself is parallel to a–b whatever the offset)."""
        frame = _linear_frame(self.a, self.b, self.axis)
        if frame is not None:
            # Linear: only the pull along the extension direction counts.
            e = frame[1]
            return e * QVector3D.dotProduct(self.offset, e)
        ab = self.b - self.a
        length = ab.length()
        if length < 1e-9:
            return QVector3D(self.offset)
        dir_ = ab / length
        along = QVector3D.dotProduct(self.offset, dir_)
        return self.offset - dir_ * along

    def line_points(self) -> tuple[QVector3D, QVector3D]:
        """The dimension line's endpoints. Aligned: ``a``/``b`` shifted by
        the offset. Linear: each endpoint pushed along the extension
        direction until both sit on one line parallel to the axis — the one
        through ``a + offset``."""
        frame = _linear_frame(self.a, self.b, self.axis)
        if frame is not None:
            _u, e = frame
            t_a = QVector3D.dotProduct(self.offset, e)
            t_b = t_a - QVector3D.dotProduct(self.b - self.a, e)
            return self.a + e * t_a, self.b + e * t_b
        off = self.perpendicular_offset()
        return self.a + off, self.b + off

    def midpoint(self) -> QVector3D:
        ap, bp = self.line_points()
        return (ap + bp) * 0.5

    def ends_riding(self, group_ids) -> tuple:
        """Which endpoints (``"a"``, ``"b"``) hold a vertex placed by one of
        the groups whose ``id`` is in *group_ids* — the ones a transform of
        those groups carries along."""
        return tuple(
            which for which in ("a", "b")
            if (an := getattr(self, "anchor_" + which)) is not None
            and any(id(g) in group_ids for g in an.chain))

    def carried(self, m: QMatrix4x4, ends) -> "Dimension":
        """A frozen copy with the endpoints in *ends* taken through *m*:
        what the dimension will read once a groups transform previewed
        through *m* is committed (#621). The offset stays, as the commit
        leaves it; :meth:`line_points` squares it to the new segment."""
        import copy
        c = copy.copy(self)
        a, b = self.a, self.b
        c._a = m.map(a) if "a" in ends else QVector3D(a)
        c._b = m.map(b) if "b" in ends else QVector3D(b)
        c.offset = QVector3D(self.offset)
        c.anchor_a = c.anchor_b = None
        c._holds = {"a": [], "b": []}
        c._scene = None
        return c

    @staticmethod
    def offset_for_cursor(a: QVector3D, b: QVector3D,
                          cursor: QVector3D) -> QVector3D:
        """Offset placing the dimension line through ``cursor`` while staying
        parallel to ``a``–``b``: the component of ``cursor − a`` perpendicular
        to the segment direction."""
        ab = b - a
        length = ab.length()
        if length < 1e-9:
            return cursor - a
        dir_ = ab / length
        to_cursor = cursor - a
        along = QVector3D.dotProduct(to_cursor, dir_)
        return to_cursor - dir_ * along

    @staticmethod
    def placement_for_cursor(a: QVector3D, b: QVector3D,
                             cursor: QVector3D) -> tuple[QVector3D, str | None]:
        """``(offset, axis)`` for the cursor's position — which dimension
        the drafter is asking for, and where its line goes. The usual
        reading: the cursor pulled PAST both endpoints along an axis's
        extension direction asks for the linear dimension along that axis
        (to the side of a slanted line → its vertical extent; above it →
        the horizontal one); pulled square off the segment, anywhere else,
        or past both endpoints in two directions at once (the corner), the
        aligned one. An axis within
        ``_LINEAR_MIN_DEG`` of the segment, or of square to it, is never
        offered: the linear reading would only duplicate or annul the
        aligned one."""
        import math
        ab = b - a
        length = ab.length()
        if length < 1e-9:
            return cursor - a, None
        d = ab / length
        aligned = Dimension.offset_for_cursor(a, b, cursor)
        w = cursor - (a + b) * 0.5
        along = abs(QVector3D.dotProduct(w, d))
        perp = (w - d * QVector3D.dotProduct(w, d)).length()
        if along <= math.tan(math.radians(_ALIGNED_CONE_DEG)) * perp:
            return aligned, None
        lo = math.sin(math.radians(_LINEAR_MIN_DEG))
        hi = math.cos(math.radians(_LINEAR_MIN_DEG))
        best = None                          # (overshoot, axis, offset)
        beyond = 0
        for name in ("x", "y", "z"):
            frame = _linear_frame(a, b, name)
            if frame is None:
                continue
            u, e = frame
            along = abs(QVector3D.dotProduct(d, u))
            if along < lo or along > hi:
                continue
            t = QVector3D.dotProduct(cursor - a, e)
            span = QVector3D.dotProduct(ab, e)
            low, high = min(0.0, span), max(0.0, span)
            over = (low - t) if t < low else (t - high) if t > high else 0.0
            if over <= 1e-9:
                continue
            beyond += 1
            if best is None or over > best[0]:
                best = (over, name, e * t)
        if best is None or beyond > 1:
            return aligned, None
        return best[2], best[1]
