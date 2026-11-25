# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 moominot and IngeTrazo contributors.
# Adapted from moominot's «dc_tools» extension (GPL-3.0-or-later,
# https://github.com/moominot/ingetrazo-skp-dc-import).
""".skp dynamic components «redraw»: values → placements.

Given a :class:`~.model.Part` tree whose parts know their current local
transform (``part.xform``: 4×4 row-major, translation in INCHES) and their
definition's natural size (``part.base``: 3 lengths in inches, the visible
bounding box of the definition), :func:`redraw` evaluates every formula and
returns the placements the component should have now: one :class:`Placed` per
part and per COPY, with its new local transform, visibility and material.

The rules, checked against components saved in .skp files:

* X/Y/Z, LenX/LenY/LenZ and RotX/RotY/RotZ are «live»: without an attribute
  or formula of their own, a part keeps what its transform already says
  (the author's own moves, turns and mirrors stay).
* A part's size comes from scaling its transform, but only for a part with
  no sub-parts (a leaf); a part WITH sub-parts keeps its scale and its LenX
  only reaches its sub-parts' formulas. Its live LenX is
  ``_lenx_nominal`` × its scale when the file saved a nominal size.
* A scale never goes below 0.001 (a length of 0 is drawn 1/1000 thick).
* Rotations turn about X, then Y, then Z, right-handed, in degrees.
* ``Copies = N`` gives N extra placements of a part, each with ``Copy`` =
  1…N (the original is Copy 0); the copies already in the file are dropped
  and made again from the original.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .evaluate import Evaluator, _num
from .model import Part

MIN_SCALE = 0.001
LEN = ("lenx", "leny", "lenz")
POS = ("x", "y", "z")
ROT = ("rotx", "roty", "rotz")


# ---- small 3×3 / 4×4 helpers (row-major lists) ------------------------------

def _matmul3(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _rot(axis: str, deg: float):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    if abs(c) < 1e-12:
        c = 0.0
    if abs(s) < 1e-12:
        s = 0.0
    if axis == "x":
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if axis == "y":
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def decompose(m):
    """``m`` (4×4 row-major) → (rotation 3×3 with mirror folded in,
    absolute scales, translation). Columns are the part's axes."""
    cols = [[m[r][c] for r in range(3)] for c in range(3)]
    scale = [math.sqrt(sum(v * v for v in col)) or 1.0 for col in cols]
    rot = [[m[r][c] / scale[c] for c in range(3)] for r in range(3)]
    return rot, scale, [m[0][3], m[1][3], m[2][3]]


def compose(rot, scale, pos):
    out = [[rot[r][c] * scale[c] for c in range(3)] + [pos[r]] for r in range(3)]
    out.append([0.0, 0.0, 0.0, 1.0])
    return out


def _det3(m):
    return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))


# ---- copies ------------------------------------------------------------------

def _copy_index(part: Part) -> int:
    v = _num(part.attrs.get("copy"))
    return int(v) if isinstance(v, float) else 0


def families(parent: Part):
    """The parent's sub-parts grouped as (original, [copies in the file]):
    a copy is a sibling with the same name and a Copy > 0. (Not the same
    definition: every copy of a GROUP gets a definition of its own.)"""
    originals, copies = [], []
    for c in parent.children:
        (copies if _copy_index(c) > 0 else originals).append(c)
    out = []
    taken: set = set()
    for o in originals:
        mine = [c for c in copies if c.name == o.name and id(c) not in taken]
        taken.update(id(c) for c in mine)
        out.append((o, mine))
    claimed = {id(c) for _, mine in out for c in mine}
    for c in copies:                      # a copy whose original is gone
        if id(c) not in claimed:
            out.append((c, []))
    return out


def clone(part: Part, parent: Part | None, copy: int) -> Part:
    """An evaluation twin of ``part`` (and its sub-tree) as Copy ``copy``."""
    attrs = dict(part.attrs)
    attrs["copy"] = float(copy)
    twin = Part(part.name, attrs, parent, [], part.handle)
    twin.xform, twin.base, twin.definition = part.xform, part.base, part.definition
    twin.aliases = part.aliases
    twin.source = part.source or part
    twin.children = [clone(c, twin, _copy_index(c)) for c in part.children]
    return twin


# ---- the redraw ----------------------------------------------------------------

@dataclass
class Placed:
    part: Part                     # the part this placement evaluates (a twin for copies)
    source: Part                   # the part in the file it is made from
    copy: int
    xform: list                    # new local transform, 4×4 row-major, inches
    hidden: bool
    material: str | None
    children: list = field(default_factory=list)
    # How this part's OWN faces stretch (a part with sub-parts that changed
    # size); its sub-parts' transforms already include it.
    content_scale: tuple = (1.0, 1.0, 1.0)


class _LiveEvaluator(Evaluator):
    """Live values: a geometric attribute with no formula of its own reads
    the part's current transform, not the (possibly stale) stored number."""

    def stored(self, part, attr):
        key = (id(part), attr)
        if key in self.overrides:
            return self.overrides[key]
        live = live_value(part, attr)
        if live is not None and part.formula(attr) is None:
            return live
        return super().stored(part, attr)

    def fallback(self, part, attr):
        # A formula that cannot be evaluated leaves the part as it is.
        live = live_value(part, attr)
        return live if live is not None else super().stored(part, attr)


def live_value(part: Part, attr: str):
    xform = getattr(part, "xform", None)
    if xform is None:
        return None
    if attr in POS:
        return float(xform[POS.index(attr)][3])
    if attr in LEN:
        i = LEN.index(attr)
        _rot_, scale, _ = decompose(xform)
        nominal = _num(part.attrs.get(f"_{attr}_nominal"))
        base = nominal if isinstance(nominal, float) else (part.base or (0, 0, 0))[i]
        return float(base) * scale[i]
    return None


def _present(part: Part, attr: str) -> bool:
    return part.formula(attr) is not None or part.attrs.get(attr) is not None


def redraw(root: Part, overrides: dict | None = None):
    """Evaluate ``root`` (with ``overrides``: {(part, attr): value in
    the stored units}) → (the root's :class:`Placed`, evaluator)."""
    ov = {(id(p), a.lower()): v for (p, a), v in (overrides or {}).items()}
    # A part redrawn inside its component keeps its parent: Parent!LenX
    # and its ancestors' and siblings' names resolve (see part_in_context).
    root_twin = clone(root, root.parent, _copy_index(root))
    # Overrides were given on the file's parts: carry them to the twins.
    by_source = {}
    for t in root_twin.walk():
        by_source.setdefault(id(t.source), t)
    ev = _LiveEvaluator(root_twin, {(id(by_source[pid]), a): v for (pid, a), v in ov.items()
                                    if pid in by_source})

    def place(part: Part, copy: int) -> Placed:
        hidden = ev.value(part, "hidden") if _present(part, "hidden") else None
        hidden = bool(_truth(hidden)) if hidden is not None else bool(part.attrs.get("__hidden__"))
        material = ev.value(part, "material") if _present(part, "material") else None
        node = Placed(part, part.source, copy, _new_xform(ev, part), hidden,
                      str(material) if material not in (None, "") else None)
        # A part with sub-parts that changes size stretches its CONTENTS
        # (its own faces and every sub-part) by new/old size; sub-parts'
        # own formulas then set their position and size over that.
        r = _content_ratio(ev, part)
        node.content_scale = r
        # Sub-parts, copies regenerated from each original: the file's own
        # copies leave the tree first, so a name finds the original.
        fams = families(part)
        part.children = [o for o, _ in fams]
        for original, _fc in fams:
            _stretch(original, r)
        for original, file_copies in fams:
            n = 0
            if _present(original, "copies"):
                c = _num(ev.value(original, "copies"))
                n = max(0, int(c)) if isinstance(c, float) else 0
            node.children.append(place(original, 0))
            # A copy the file already has is redrawn from ITSELF (its own
            # sub-parts may differ from the original's); only new copies
            # are made from the original.
            existing = {_copy_index(c): c for c in file_copies}
            for i in range(1, n + 1):
                twin = clone((existing.get(i) or original).source
                             or existing.get(i) or original, part, i)
                _stretch(twin, r)
                part.children.append(twin)
                node.children.append(place(twin, i))
        return node

    return place(root_twin, _copy_index(root_twin)), ev


def _content_ratio(ev: Evaluator, part: Part):
    """(rx, ry, rz): how much a part with sub-parts grows, new LenX over
    its live LenX before the redraw; 1 for a leaf or an unchanged size."""
    if not part.children or part.xform is None:
        return (1.0, 1.0, 1.0)
    if _copy_index(part) > 0:
        # A COPY is redrawn without stretching its contents (as in .skp files:
        # widening a stair flight stretched the original's base board and
        # left each copy's board as it was).
        return (1.0, 1.0, 1.0)
    out = []
    for a in LEN:
        # «Old» is the size the contents were last laid out for: the
        # nominal size (the size at scale 1), else the attribute's value —
        # never the size measured off the geometry (a part whose formula
        # never matched its contents is not stretched). «New» is the
        # formula's value, or the live size: a part the user scaled (the
        # Scale tool, or LenX typed in the options) stretches by its scale.
        driven = part.formula(a) is not None or (id(part), a) in ev.overrides
        keys = (a, f"_{a}_nominal") if driven else (f"_{a}_nominal", a)
        old = None
        for k in keys:
            old = _num(part.attrs.get(k))
            if isinstance(old, float):
                break
        if not isinstance(old, float):
            old = live_value(part, a)
        new = _num(ev.value(part, a))
        ok = isinstance(old, float) and old > 1e-9 and isinstance(new, float) and new > 0
        out.append(new / old if ok else 1.0)
    return tuple(out)


def _stretch(part: Part, r) -> None:
    """Scale ``part``'s placement in its parent's frame by ``r``."""
    if part.xform is None or all(abs(v - 1.0) < 1e-12 for v in r):
        return
    part.xform = [[part.xform[i][j] * (r[i] if i < 3 else 1.0) for j in range(4)]
                  for i in range(4)]


def _truth(v) -> bool:
    if isinstance(v, bool):
        return v
    n = _num(v)
    if isinstance(n, float):
        return n > 0
    return str(v).strip().lower() == "true"


def _new_xform(ev: Evaluator, part: Part):
    current = part.xform
    if current is None:
        return None
    rot, scale, pos = decompose(current)
    # Position.
    for i, a in enumerate(POS):
        if _present(part, a):
            v = _num(ev.value(part, a))
            if isinstance(v, float):
                pos[i] = v
    # Rotation: rebuilt only when the part has a rotation attribute; the
    # transform's own mirror (a negative determinant) is kept.
    if any(_present(part, a) for a in ROT):
        angles = []
        for a in ROT:
            v = _num(ev.value(part, a)) if _present(part, a) else 0.0
            angles.append(v if isinstance(v, float) else 0.0)
        r = _matmul3(_rot("z", angles[2]), _matmul3(_rot("y", angles[1]), _rot("x", angles[0])))
        if _det3(rot) < 0:
            r = [[r[i][0], r[i][1], -r[i][2]] for i in range(3)]
        rot = r
    # Size: only a leaf scales. A part WITH sub-parts is redrawn at scale 1
    # (it is reset and leaves its own faces as they are: its LenX
    # only reaches its sub-parts).
    if part.children:
        scale = [1.0, 1.0, 1.0]
    else:
        base = part.base or (0.0, 0.0, 0.0)
        for i, a in enumerate(LEN):
            if _present(part, a) and base[i] > 1e-9:
                v = _num(ev.value(part, a))
                if isinstance(v, float):
                    scale[i] = max(v / base[i], MIN_SCALE)
    return compose(rot, scale, pos)
