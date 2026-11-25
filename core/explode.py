# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Exploded view: a component's parts pulled apart, and put back.

Each part moves away from the assembly's centre in proportion to how far it
already sits from it — the classic exploded drawing, where the seat stays
put and the legs spread out around it — either in every direction
(``outward``) or along one axis only (``x``, ``y``, ``z``: a stack pulled
apart vertically reads best along blue).

The parts really move, inside their component, through an undoable command:
so everything that draws or reads the model — the viewport, section cuts,
sheets, snaps, exports — shows the exploded state with no special case.
What makes it reversible is that each part remembers the translation the
explosion gave it (``Group.explode_offset``) and the component remembers
the setting (``Group.exploded``). Changing the amount swaps the old offset
for the new one; Reassemble takes it off. A part moved by hand in between
keeps that move, because only the explosion's own share is ever undone.
"""
from __future__ import annotations

MODES = ("outward", "x", "y", "z")


def _offset_of(part):
    from PySide6.QtGui import QVector3D
    o = getattr(part, "explode_offset", None)
    return QVector3D(*o) if o else QVector3D()


def assembled_centres(container) -> list:
    """Each part's centre (the middle of its box, in the container's frame)
    where it sits assembled — its current centre minus the explosion's
    offset."""
    from PySide6.QtGui import QVector3D
    from core.parts import part_points
    out = []
    for kid in container.children:
        pts = part_points(kid)
        if len(pts) == 0:
            c = QVector3D()
        else:
            lo, hi = pts.min(axis=0), pts.max(axis=0)
            c = QVector3D(*((lo + hi) / 2.0).tolist())
        out.append(c - _offset_of(kid))
    return out


def explode_offsets(centres, factor: float, mode: str = "outward") -> list:
    """The translation each part takes at ``factor`` (0 = assembled, 1 =
    every part twice as far from the centre as it was). The centre is the
    middle of the parts' centres' box, so a symmetric model explodes
    symmetrically."""
    from PySide6.QtGui import QVector3D
    if not centres:
        return []
    xs = [c.x() for c in centres]
    ys = [c.y() for c in centres]
    zs = [c.z() for c in centres]
    mid = QVector3D((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2,
                    (min(zs) + max(zs)) / 2)
    keep = {"outward": (1, 1, 1), "x": (1, 0, 0), "y": (0, 1, 0),
            "z": (0, 0, 1)}.get(mode, (1, 1, 1))
    out = []
    for c in centres:
        d = (c - mid) * float(factor)
        out.append(QVector3D(d.x() * keep[0], d.y() * keep[1],
                             d.z() * keep[2]))
    return out


def apply_explode(container, factor: float, mode: str = "outward",
                  centres=None) -> None:
    """Pull ``container``'s parts apart to ``factor`` (``0`` reassembles),
    in place. ``centres`` (from :func:`assembled_centres`) lets a slider drag
    measure once and apply many times. The command is
    :class:`ExplodeViewCommand`; this is its body."""
    from PySide6.QtGui import QMatrix4x4
    kids = list(getattr(container, "children", None) or ())
    if not kids:
        return
    if centres is None:
        centres = assembled_centres(container)
    factor = max(0.0, float(factor))
    new = (explode_offsets(centres, factor, mode) if factor > 0
           else [None] * len(kids))
    for kid, target in zip(kids, new):
        old = _offset_of(kid)
        step = QMatrix4x4()
        step.translate(target - old if target is not None else old * -1.0)
        if kid.xform is None:
            # A plain group moves by a matrix of its own from now on, and a
            # group with a matrix reads as a component unless it says it is
            # not: every wall of an exploded building came back a component,
            # whose parts can no longer be grouped or exploded (#1375).
            kid.component = False
        kid.xform = step * (kid.xform if kid.xform is not None
                            else QMatrix4x4())
        kid.explode_offset = ((target.x(), target.y(), target.z())
                              if target is not None and not target.isNull()
                              else None)
    container.exploded = ({"factor": factor, "mode": mode} if factor > 0
                          else None)


def rotate_offsets(container, xform) -> None:
    """Re-express the parts' offsets after ``xform`` was pushed down into
    them (entering a container for editing bakes its matrix into its
    children, see ``Scene._bake_container_xform``): an offset is a vector
    in the container's frame, so it turns — and scales — with that frame."""
    from PySide6.QtGui import QVector3D
    for kid in getattr(container, "children", None) or ():
        o = getattr(kid, "explode_offset", None)
        if not o:
            continue
        v = xform.mapVector(QVector3D(*o))
        kid.explode_offset = (v.x(), v.y(), v.z())


def snapshot(container) -> tuple:
    """Everything an explosion changes, to put back exactly (undo, and the
    slider's live preview)."""
    from PySide6.QtGui import QMatrix4x4
    kids = list(container.children)
    return (dict(container.exploded) if container.exploded else None,
            [(k, QMatrix4x4(k.xform) if k.xform is not None else None,
              k.explode_offset) for k in kids])


def restore(container, snap) -> None:
    state, kids = snap
    container.exploded = dict(state) if state else None
    for kid, xform, offset in kids:
        kid.xform = xform
        kid.explode_offset = offset
