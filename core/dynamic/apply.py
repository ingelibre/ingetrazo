# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 moominot and IngeTrazo contributors.
# Adapted from moominot's «dc_tools» extension (GPL-3.0-or-later,
# https://github.com/moominot/ingetrazo-skp-dc-import).
"""IngeTrazo groups ⇄ the evaluator: redraw an imported dynamic component.

:func:`redraw_group` reads an imported component (``group.ext[KEY]`` on its
placements, as the importer leaves it), redraws it with :mod:`.redraw` and
returns a NEW group tree: the caller swaps it for the old one inside one
command, so undo puts the old one back whole. Meshes are shared with the old
tree, except the own faces of a part whose contents stretched (baked, as
a .skp file bakes them into the definition).

Units: IngeTrazo works in metres, the .skp dictionaries in inches.
"""
from __future__ import annotations

import copy as _copy
import re

from .evaluate import _num
from .model import Part, part_aliases, part_name
from .redraw import LEN, decompose, live_value, redraw

KEY = "skp_dc_import"
M_PER_IN = 0.0254


# ---- matrices -----------------------------------------------------------------

def _rows_from_q(q):
    """QMatrix4x4 (metres) → 4×4 row-major list (inches)."""
    d = q.data()                                   # column-major
    m = [[d[c * 4 + r] for c in range(4)] for r in range(4)]
    for r in range(3):
        m[r][3] /= M_PER_IN
    return m


def _q_from_rows(m):
    from PySide6.QtGui import QMatrix4x4
    vals = []
    for r in range(4):
        for c in range(4):
            v = m[r][c]
            if c == 3 and r < 3:
                v *= M_PER_IN
            vals.append(float(v))
    return QMatrix4x4(*vals)


# ---- the part tree -----------------------------------------------------------

def _merged(group) -> dict:
    data = (group.ext or {}).get(KEY) or {}
    attrs = dict(data.get("definition_attributes") or {})
    attrs.update(data.get("instance_attributes") or {})
    attrs["__hidden__"] = bool(getattr(group, "hidden", False))
    return attrs


def _bounds(group, visible_only: bool, start=None):
    """The group's own frame bounds (metres): its mesh and, for a part with
    sub-parts, theirs (skipping hidden ones when asked). ``start`` maps what
    the group holds into its own frame (an open group holds it in world)."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3

    def add(p):
        for i, v in enumerate((p.x(), p.y(), p.z())):
            lo[i] = min(lo[i], v)
            hi[i] = max(hi[i], v)

    def walk(g, m):
        for v in g.mesh.vertices:
            pos = getattr(v, "position", v)
            add(m.map(pos) if m is not None else pos)
        for c in g.children or ():
            if visible_only and getattr(c, "hidden", False):
                continue
            cm = c.xform if m is None else m * c.xform
            walk(c, cm)

    walk(group, start)
    if lo[0] == float("inf"):
        return (0.0, 0.0, 0.0)
    return tuple((hi[i] - lo[i]) / M_PER_IN for i in range(3))


_IDENTITY = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
             [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


def part_tree(group, parent: Part | None = None, edits: dict | None = None) -> Part:
    """The evaluator's view of ``group``'s tree. ``edits`` ({id(group): key
    changes}, see :mod:`.author`) are applied to the attributes read."""
    from .author import DELETE
    attrs = _merged(group)
    for k, v in ((edits or {}).get(id(group)) or {}).items():
        if v is DELETE:
            attrs.pop(k, None)
        else:
            attrs[k] = v
    data = (group.ext or {}).get(KEY) or {}
    part = Part(part_name(attrs, group.name), attrs, parent, [], group)
    part.aliases = part_aliases(part.name, group.name)
    # A classic group (no matrix: its mesh in its parent's frame) reads as
    # placed at the identity; it is written back as such an instance.
    part.xform = (_rows_from_q(group.xform) if group.xform is not None
                  else [row[:] for row in _IDENTITY])
    part.base = _bounds(group, visible_only=bool(group.children))
    part.definition = data.get("definition") or group.name or ""
    part.children = [part_tree(c, part, edits) for c in (group.children or ())]
    return part


def is_dynamic_root(group) -> bool:
    data = (group.ext or {}).get(KEY)
    return bool(data and (data.get("definition_attributes") or data.get("instance_attributes")))


def _strip_formulas(part: Part) -> None:
    """The part reads its CURRENT values: no formula of its own is
    evaluated again (as a redrawn part's parent behaves in .skp files)."""
    part.attrs = {k: v for k, v in part.attrs.items()
                  if not (k.startswith("_") and k.endswith("_formula"))}


def part_in_context(scene, group, edits: dict | None = None):
    """``group``'s Part, with the dynamic component around it when it is a
    part of an OPEN group that is (or sits in) a dynamic component — a
    cabinet inside an open kitchen, a shelf inside an open cabinet — so
    ``Parent!LenX`` and the names of its parent, ancestors and siblings
    resolve as they do in .skp files. Returns ``(part, frame)``: ``frame``
    is the open parent's world matrix (QMatrix4x4) that the part's local
    placement is read in and written back with; ``None`` when ``group`` is
    not in such a context (then ``part`` is plain :func:`part_tree`).

    Opening a group pushes its matrix into what it holds (the tools speak
    world coordinates), so each open level's placement is read back from
    the frame it had when it was opened. The parts around ``group`` keep
    their current values: only ``group``'s own formulas are evaluated."""
    stack = list(getattr(scene, "_edit_stack", None) or ()) if scene is not None else []
    if not stack or not any(c is group for c in (stack[-1]["group"].children or ())):
        return part_tree(group, None, edits), None
    levels = [lv["group"] for lv in stack]
    k = next((i for i, g in enumerate(levels) if is_dynamic_root(g)), None)
    if k is None:
        return part_tree(group, None, edits), None
    from PySide6.QtGui import QMatrix4x4

    def frame_of(i):
        f = stack[i].get("frame") if levels[i].xform is not None else None
        return QMatrix4x4(f) if f is not None else QMatrix4x4()

    def inverse(m):
        inv, ok = m.inverted()
        return inv if ok else QMatrix4x4()

    top = part_tree(levels[k], None, edits)
    frames = [frame_of(i) for i in range(len(levels))]
    parts = [top]
    for i in range(k + 1, len(levels)):
        parts.append(next(p for p in parts[-1].children if p.handle is levels[i]))
    for j, (part, i) in enumerate(zip(parts, range(k, len(levels)))):
        # This open level: its placement in its parent, its size in its frame.
        rel = frames[i] if i == 0 else inverse(frames[i - 1]) * frames[i]
        part.xform = _rows_from_q(rel)
        inv = inverse(frames[i])
        part.base = _bounds(levels[i], bool(levels[i].children), inv)
        # What it holds was pushed into world: back to its frame.
        nxt = parts[j + 1].handle if j + 1 < len(parts) else None
        for c in part.children:
            if c.handle is not nxt and c.handle.xform is not None:
                c.xform = _rows_from_q(inv * c.handle.xform)
    target = next(p for p in parts[-1].children if p.handle is group)
    inside = {id(p) for p in target.walk()}
    for p in top.walk():
        if id(p) not in inside:
            _strip_formulas(p)
    return target, frames[-1]


# ---- options -------------------------------------------------------------------

def resize_root(root: Part, axis: str, value_in: float) -> None:
    """LenX/LenY/LenZ typed in the options: as in the original options dialog, the
    component is scaled so its live size is the value; the redraw then lays
    out its parts for it."""
    live = live_value(root, axis)
    if not live or live <= 1e-9 or root.xform is None:
        return
    f = value_in / live
    i = LEN.index(axis)
    root.xform = [[root.xform[r][c] * (f if c == i else 1.0) for c in range(4)]
                  for r in range(4)]


# ---- back to groups --------------------------------------------------------------

def copy_name(name: str | None, copy: int) -> str | None:
    """The name of Copy ``copy`` of a part: «shelf copy 001» (.skp files tell
    copies from parts by that name)."""
    if not copy:
        return name
    base = re.sub(r" copy \d+$", "", str(name or "")).strip() or "part"
    return f"{base} copy {int(copy):03d}"


def _value_for_store(v):
    n = _num(v)
    return n if isinstance(n, float) else ("" if v is None else str(v))


def _material_attrs(scene, name):
    """The paint for a part whose Material attribute names ``name``: the
    document's material of that name (case-insensitive), else None."""
    registry = getattr(scene, "materials", None) or {}
    want = str(name).strip().lower()
    for key, mat in registry.items():
        if str(key).strip().lower() == want:
            attrs = getattr(mat, "face_attrs", None)
            return attrs() if callable(attrs) else None
    return None


def redraw_group(root_group, options: dict | None = None, scene=None, edits=None):
    """A new group tree for ``root_group`` redrawn with ``options``
    ({attribute: value}, lengths in INCHES as .skp files store them; LenX,
    LenY, LenZ resize the component). ``scene`` resolves Material values
    to the document's materials. ``edits`` ({id(group): key changes}) are
    authoring changes to parts of the tree (see :mod:`.author`), written
    into the new tree. Returns (new root group, evaluator)."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import Group, transformed_mesh

    from .author import apply_changes, new_dynamic_data
    edits = edits or {}
    root, frame = part_in_context(scene, root_group, edits)
    overrides = {}
    # A number typed in the attribute editor is an explicit geometric edit.
    # Unedited stored numbers can be stale and must still read live geometry.
    for part in root.walk():
        changes = edits.get(id(part.handle), {})
        for attr in ("x", "y", "z", *LEN):
            if attr not in changes or part.formula(attr) is not None:
                continue
            value = _num(changes[attr])
            if isinstance(value, float):
                if attr in LEN and part.children:
                    # Content stretching needs its size before this edit.
                    part.attrs[attr] = live_value(part, attr)
                overrides[(part, attr)] = value
    for k, v in (options or {}).items():
        k = k.lower()
        if k in LEN:
            n = _num(v)
            if isinstance(n, float):
                resize_root(root, k, n)
        else:
            overrides[(root, k)] = v
    placed, ev = redraw(root, overrides)
    kept_uid: set = set()

    def build(node, is_root=False):
        tmpl = node.source.handle                       # the group this part was read from
        g = Group(tmpl.mesh, name=copy_name(tmpl.name, node.copy))
        for attr in ("layer", "ifc", "billboard", "material", "axes", "locked", "text3d"):
            if hasattr(tmpl, attr):
                setattr(g, attr, _copy.deepcopy(getattr(tmpl, attr)))
        g.component = tmpl.component
        g.images = list(getattr(tmpl, "images", None) or ())
        g.source = getattr(tmpl, "source", None)
        if id(tmpl) not in kept_uid:
            # The first placement made from a part keeps its identity: a
            # scene that hides it, or the opening it cut, still finds it.
            kept_uid.add(id(tmpl))
            g.uid = tmpl.uid
        g.hidden = bool(node.hidden)
        if node.material and scene is not None:
            # A Material formula paints the part, as a .skp file paints the
            # instance: faces left with the default material show it.
            paint = _material_attrs(scene, node.material)
            if paint is not None:
                g.material = paint
        if node.xform is not None:
            g.xform = _q_from_rows(node.xform)
        cs = node.content_scale
        if any(abs(v - 1.0) > 1e-9 for v in cs):
            # The part's own faces stretch with its contents (a .skp file bakes
            # this into the definition; a private copy of the mesh here).
            s = QMatrix4x4()
            s.scale(*cs)
            g.mesh = transformed_mesh(tmpl.mesh, s)
        ext = _copy.deepcopy(tmpl.ext) if tmpl.ext else {}
        data = ext.get(KEY)
        changes = edits.get(id(tmpl))
        if changes:
            if data is None:          # a plain part gets its first attribute
                data = ext[KEY] = new_dynamic_data(tmpl.name or "")
                data["instance_attributes"].pop("_lengthunits", None)
            apply_changes(data, changes)
        if data is not None:
            inst = data.setdefault("instance_attributes", {})
            part = node.part
            for attr in _attrs_to_store(part, ev):
                inst[attr] = _value_for_store(ev.value(part, attr))
            if node.copy:
                inst["copy"] = float(node.copy)
            if part.children:
                # Laid out for its new size: that is now its nominal size.
                for a in LEN:
                    v = _num(ev.value(part, a))
                    if isinstance(v, float):
                        inst[f"_{a}_nominal"] = v
                        if a in inst:
                            inst[a] = v     # the stored size says it too
            if is_root:
                for (p, a), v in overrides.items():
                    if p is root:
                        inst[a] = _value_for_store(v)
        g.ext = ext or None
        g.adopt([build(c) for c in node.children])
        if g.xform is None and node.xform is not None:
            g.xform = _q_from_rows(node.xform)
        return g

    new = build(placed, is_root=True)
    if frame is not None and new.xform is not None:
        new.xform = frame * new.xform          # back to where the tools work
    return new, ev


def _attrs_to_store(part: Part, ev):
    """The attributes the redraw set: every one with a formula, plus the
    predefined geometric ones the part carries."""
    names = set()
    for k in part.attrs:
        if k.startswith("_") and k.endswith("_formula") and not k.startswith("_inst_"):
            if str(part.attrs[k] or "").strip():
                names.add(k[1:-8])
    return sorted(names)


# ---- making a component dynamic ---------------------------------------------------

def _clone(g):
    """A new group sharing ``g``'s mesh, with copies of its properties and
    of its sub-tree (so the swap is one clean undo step)."""
    from core.group import Group
    n = Group(g.mesh, name=g.name)
    for attr in ("layer", "ifc", "billboard", "material", "axes", "locked",
                 "text3d", "hidden", "component", "xform", "ext"):
        if hasattr(g, attr):
            v = getattr(g, attr)
            if attr == "xform" and v is not None:
                from PySide6.QtGui import QMatrix4x4
                v = QMatrix4x4(v)
            else:
                v = _copy.deepcopy(v) if attr in ("ext", "material", "ifc", "axes") else v
            setattr(n, attr, v)
    n.adopt([_clone(c) for c in (g.children or ())])
    return n


def make_dynamic_tree(group, name: str | None = None, units: str = "CENTIMETERS"):
    """A copy of ``group`` that is a dynamic component («Make dynamic»), to swap in for it. A classic group gets its axes at its
    bounding box's lower corner first, as a .skp component has them, so
    LenX/LenY/LenZ stretch it from there."""
    from PySide6.QtGui import QMatrix4x4, QVector3D
    from core.group import transformed_mesh
    from .author import new_dynamic_data
    new = _clone(group)
    lo = [float("inf")] * 3

    def walk(g, m):
        for v in g.mesh.vertices:
            p = getattr(v, "position", v)
            p = m.map(p) if m is not None else p
            for i, c in enumerate((p.x(), p.y(), p.z())):
                lo[i] = min(lo[i], c)
        for c in g.children or ():
            if c.xform is None:
                walk(c, m)
            else:
                walk(c, c.xform if m is None else m * c.xform)

    walk(group, None)                      # in the group's OWN frame
    if lo[0] != float("inf") and max(abs(v) for v in lo) > 1e-9:
        # Axes to the lower corner of what it holds (where a .skp
        # component has them), the group staying where it is in the model.
        to_corner, back = QMatrix4x4(), QMatrix4x4()
        to_corner.translate(QVector3D(*lo))
        back.translate(QVector3D(-lo[0], -lo[1], -lo[2]))
        if group.mesh.vertices:
            new.mesh = transformed_mesh(group.mesh, back)
        for c in new.children or ():
            c.xform = back * c.xform if c.xform is not None else QMatrix4x4(back)
        new.xform = (QMatrix4x4(group.xform) * to_corner) if group.xform is not None else to_corner
        new.axes = None
    ext = dict(new.ext or {})
    data = ext.get(KEY)
    if data is None:
        data = ext[KEY] = new_dynamic_data(name or group.name or "Component", units)
    elif name:
        data.setdefault("instance_attributes", {})["_name"] = name
    new.ext = ext
    return new
