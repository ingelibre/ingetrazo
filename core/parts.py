# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The parts of a component, measured the way a cut list measures them.

A container's children are its parts (a stool split into its pieces, a
cabinet drawn board by board). For each one this module answers what the
Parts tray shows: its name, the material most of it wears, and its size as
length × width × thickness — the box a woodworker would cut it from, not
the box its axes happen to give. A leg splayed at 10° measured along the
stool's own axes is a fat diagonal; measured along its own length it is
the 4 × 4 × 58 cm stick it is.

Nothing here touches the scene: the tray reads, and every change goes
through a command.
"""
from __future__ import annotations

from pathlib import PurePath


def part_points(part, cache=None):
    """``part``'s vertex positions in its container's coordinates, as an
    ``(N, 3)`` float64 array (its nested placements included).

    ``cache`` (a dict the caller keeps for ONE pass over a container's
    parts) holds each mesh's local array, so the copies of a shared
    definition read its vertices once: a container of 300 copies of a
    3 000-face tree read them 300 times."""
    import numpy as np
    from core.group import iter_placements
    chunks = []
    for g, m in iter_placements(part):
        key = ("points", id(g.mesh))
        pos = cache.get(key) if cache is not None else None
        if pos is None:
            verts = g.mesh.vertices
            pos = (np.array([[v.position.x(), v.position.y(), v.position.z()]
                             for v in verts], dtype=np.float64)
                   if verts else np.empty((0, 3)))
            if cache is not None:
                cache[key] = pos
        if not len(pos):
            continue
        if m is not None:
            rot = np.array([[m(r, c) for c in range(3)] for r in range(3)])
            pos = pos @ rot.T + np.array([m(0, 3), m(1, 3), m(2, 3)])
        chunks.append(pos)
    if not chunks:
        return np.empty((0, 3))
    return np.concatenate(chunks)


#: How much smaller the part's own box must be to beat the model's axes.
_OWN_AXES_GAIN = 0.8


def part_size(points) -> tuple:
    """``(length, width, thickness)`` in metres, largest first: the extent
    of the tighter of two boxes — along the container's axes, or along the
    part's own principal axes. Either can win: a board lying square in a
    cabinet measures exactly on the cabinet's axes, a splayed leg only on
    its own."""
    import numpy as np
    if len(points) == 0:
        return (0.0, 0.0, 0.0)

    def extent(axes):
        proj = points @ axes.T
        return proj.max(axis=0) - proj.min(axis=0)

    best = extent(np.eye(3))
    if len(points) >= 4:
        centred = points - points.mean(axis=0)
        _w, vecs = np.linalg.eigh(centred.T @ centred)
        own = extent(vecs.T)
        # The part's own axes win only when they are MUCH tighter. A splayed
        # leg or a board lying at an angle is: its own box is a fraction of
        # the diagonal one. A stepped shape square to the model (a carcass
        # with a plinth set back) is not — a slightly tilted box happens to
        # hold it in 7 % less volume, and reads as a depth no one would cut.
        if np.prod(own) < _OWN_AXES_GAIN * np.prod(best):
            best = own
    dims = sorted((float(d) for d in best), reverse=True)
    return tuple(dims)


def _material_label(attrs) -> str | None:
    """What a face is painted with, as a person would name it: the
    registry name when the paint has one, else the texture's file name,
    else the colour. ``None`` for an unpainted face."""
    if not attrs:
        return None
    if attrs.get("mat"):
        return str(attrs["mat"])
    tex = attrs.get("texture")
    if tex and tex.get("path"):
        return PurePath(str(tex["path"])).stem
    col = attrs.get("color")
    if col is not None:
        r, g, b = (int(round(c * 255)) for c in list(col)[:3])
        return f"#{r:02x}{g:02x}{b:02x}"
    return None


def _mesh_paint_areas(mesh, cache=None):
    """``(own, default)`` for ``mesh`` in its own coordinates: the net area
    each material painted on its faces covers, and the net area of the
    faces left default (they wear their container's paint)."""
    from core.materials import has_own_material
    key = ("paint", id(mesh))
    hit = cache.get(key) if cache is not None else None
    if hit is not None:
        return hit
    own: dict = {}
    default = 0.0
    for f in mesh.faces:
        if has_own_material(f.attrs):
            label = _material_label(f.attrs)
            if label:
                own[label] = own.get(label, 0.0) + f.net_area()
        else:
            default += f.net_area()
    hit = (own, default)
    if cache is not None:
        cache[key] = hit
    return hit


def part_material(part, cache=None) -> str:
    """The material covering most of ``part``'s surface ('' when none).
    A default face shows its nearest painted container's paint, as it
    draws.

    Areas are read in each mesh's own coordinates (as they always were),
    so with a ``cache`` kept for one pass the copies of a shared
    definition are read once: 300 copies of a 3 000-face tree were
    300 × 3 000 face areas, 14 s with the container selected."""
    from core.group import iter_painted_placements
    area: dict = {}
    for g, _m, inherited in iter_painted_placements(part):
        own, default = _mesh_paint_areas(g.mesh, cache)
        for label, a in own.items():
            area[label] = area.get(label, 0.0) + a
        # Net: a face's opening covers nothing, so it must not vote for
        # the material either (#742) — _mesh_paint_areas sums net areas.
        label = _material_label(inherited)
        if label and default:
            area[label] = area.get(label, 0.0) + default
    if not area:
        return ""
    return max(area.items(), key=lambda kv: kv[1])[0]


def part_row(part, cache=None) -> dict:
    """``part``'s row: ``{"part", "name", "material", "size", "faces",
    "hidden"}``. Pass the same ``cache`` (a dict) for every part of one
    pass, so a definition several parts share is read once."""
    from core.group import iter_placements
    return {
        "part": part,
        "name": part.name,
        "material": part_material(part, cache),
        "size": part_size(part_points(part, cache)),
        "faces": sum(len(g.mesh.faces) for g, _m in iter_placements(part)),
        "hidden": bool(getattr(part, "hidden", False)),
    }


def part_rows(container) -> list:
    """One row per part of ``container``: ``{"part", "name", "material",
    "size", "faces"}``, in the container's order."""
    cache: dict = {}
    return [part_row(child, cache)
            for child in getattr(container, "children", None) or ()]


#: Thinner than this, a part is a SURFACE: a skin, a decal, a pane drawn as
#: one plane — geometry a person sees, with no thickness to cut (metres).
SURFACE_BELOW = 0.0005


def is_surface(size) -> bool:
    """Whether a part of ``size`` (length, width, thickness) has no real
    thickness. Such parts are kept — deleting them would leave a hole in
    what the model shows — but a cut list must not read them as boards."""
    return float(size[2]) < SURFACE_BELOW


def cut_list(rows, precision_mm: float = 1.0,
             by_material: bool = True) -> list:
    """Rows merged into cut-list lines: parts of the same size (to
    ``precision_mm``) — and, with ``by_material``, the same material — are
    one line with a quantity: two side legs are «2 × 58 × 45 × 4».

    ``by_material=False`` is for models whose paint says nothing about the
    wood: a Sweet Home 3D model gives every fragment its own texture image,
    so two identical legs never share a material there. Merged lines list
    every material they cover. Largest parts first."""
    lines: dict = {}
    for row in rows:
        size_key = tuple(round(d * 1000.0 / precision_mm)
                         for d in row["size"])
        key = ((row["material"],) if by_material else ()) + size_key
        line = lines.get(key)
        if line is None:
            lines[key] = {"names": [row["name"]],
                          "materials": [row["material"]],
                          "size": row["size"], "qty": 1}
        else:
            line["names"].append(row["name"])
            if row["material"] not in line["materials"]:
                line["materials"].append(row["material"])
            line["qty"] += 1
    for line in lines.values():
        line["names"].sort(key=_natural)
        line["material"] = ", ".join(m for m in line["materials"] if m)
    return sorted(lines.values(),
                  key=lambda ln: (tuple(-round(d, 6) for d in ln["size"]),
                                  _natural(ln["names"][0])))


def _natural(name: str) -> tuple:
    """Sort key that puts «Piece 2» before «Piece 10»."""
    import re
    return tuple(int(t) if t.isdigit() else t.lower()
                 for t in re.split(r"(\d+)", name))


def cut_list_text(lines, fmt_len, headers, surface: str = "surface") -> str:
    """The cut list as tab-separated text, one line per ``cut_list`` entry —
    what pastes straight into a spreadsheet. ``fmt_len`` formats a length in
    metres (the model's units); ``headers`` are the six column titles; a
    part with no thickness (:func:`is_surface`) reads ``surface`` in the
    thickness column instead of a zero."""
    out = ["\t".join(headers)]
    for ln in lines:
        length, width, thick = ln["size"]
        out.append("\t".join([str(ln["qty"]), ", ".join(ln["names"]),
                              ln["material"], fmt_len(length),
                              fmt_len(width),
                              surface if is_surface(ln["size"])
                              else fmt_len(thick)]))
    return "\n".join(out) + "\n"
