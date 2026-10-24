# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The model's tree of groups and components, and its sheets, read for the
Browser.

Qt-free: the browser's tabs (``views/outliner.py``) ask these questions and
the tests ask them without a window. Nothing here changes the model —
renaming, hiding and opening go through the usual commands and the
viewport, so the Outliner never has a state of its own to fall out of
step with.

A node IS its :class:`~core.group.Group`. Rows are matched to groups by
``uid``, the identity that survives save, load, rename and undo (scenes
remember their hidden objects by it too), never by their place in the
tree. A sheet's view frame names its scene by name: a deleted scene
leaves an orphan frame to flag, never a broken one.
"""
from __future__ import annotations


def walk(groups, parent=None, depth: int = 0):
    """``(group, parent, depth)`` for every group, depth first, in the
    order the document holds them."""
    for g in groups:
        yield g, parent, depth
        yield from walk(getattr(g, "children", None) or (), g, depth + 1)


def parents(groups) -> dict:
    """``{id(group): parent}`` for every group (``None`` at the top)."""
    return {id(g): p for g, p, _d in walk(groups)}


def path_to(groups, target) -> list | None:
    """The containers from the top of the model down to ``target``'s
    parent — what has to be open for ``target`` to be picked — or ``None``
    when ``target`` is not in the model."""
    up = parents(groups)
    if id(target) not in up:
        return None
    path = []
    p = up[id(target)]
    while p is not None:
        path.append(p)
        p = up.get(id(p))
    path.reverse()
    return path


def structure(groups) -> tuple:
    """A fingerprint of the tree's SHAPE: which groups, under which parent,
    in which order. Equal fingerprints mean the rows can be updated in
    place; a different one means rows came or went."""
    return tuple((id(g), id(p) if p is not None else 0)
                 for g, p, _d in walk(groups))


def open_path(scene) -> list:
    """The groups open for editing, outermost first (empty at the model)."""
    return [lvl["group"] for lvl in (getattr(scene, "_edit_stack", None)
                                     or ())]


def kind(group) -> str:
    """What a node is, as a short key: ``"component"`` or ``"group"`` —
    and the more specific ``"image"`` and ``"text"`` for the containers
    the Face-me image and 3D text tools make."""
    if getattr(group, "billboard", False):
        return "image"
    if getattr(group, "text3d", None):
        return "text"
    return "component" if group.is_component() else "group"


def ifc_class(group) -> str:
    """The BIM class the group is tagged with (``IfcWall``…), or ``""``."""
    tag = getattr(group, "ifc", None)
    return str(tag.get("class") or "") if isinstance(tag, dict) else ""


def instance_counts(groups) -> dict:
    """``{id(mesh): copies}`` over the whole tree — how many placements
    draw each component definition."""
    counts: dict = {}
    for g, _p, _d in walk(groups):
        if g.is_component():
            counts[id(g.mesh)] = counts.get(id(g.mesh), 0) + 1
    return counts


def layer_name(group) -> str:
    """The layer the group is on (the default layer's name when none)."""
    from core.layers import layer_of
    return layer_of(group)


def matches(group, query: str, type_text: str = "") -> bool:
    """Whether ``query`` (already casefolded) is in the group's name, its
    type as the tree shows it, its BIM class or its layer."""
    if not query:
        return True
    return any(query in str(text).casefold() for text in (
        group.name or "", type_text, ifc_class(group), layer_name(group)))


def filter_keep(groups, query: str, type_of=lambda g: "") -> tuple:
    """``(keep, hit)``: the ids of the groups a filter by ``query`` shows —
    every match and the containers on the way down to it — and of the
    matches themselves (their containers unfold to reveal them)."""
    nodes = list(walk(groups))
    hit = {id(g) for g, _p, _d in nodes if matches(g, query, type_of(g))}
    keep = set(hit)
    for g, p, _d in reversed(nodes):        # children before their parents
        if id(g) in keep and p is not None:
            keep.add(id(p))
    return keep, hit


# ---- Sheets (the 2D side) ---------------------------------------------------

def frame_scene(frame) -> str | None:
    """The saved scene a sheet's view frame shows, by name — ``None`` when
    the frame shows a standard view or the live camera instead."""
    key = getattr(frame, "view_key", "") or ""
    return key[6:] if key.startswith("scene:") else None


def scene_names(scene) -> set:
    return {v.name for v in getattr(scene, "saved_views", None) or ()}


def is_orphan(scene, frame) -> bool:
    """A frame that names a scene the document no longer has: the sheet
    keeps it (and its place on the page), the browser flags it."""
    name = frame_scene(frame)
    return name is not None and name not in scene_names(scene)


def scene_usage(scene) -> dict:
    """``{scene name: [sheet names]}`` — where each saved scene is placed."""
    used: dict = {}
    for comp in getattr(scene, "compositions", None) or ():
        for frame in comp.frames:
            name = frame_scene(frame)
            if name is not None and comp.name not in used.get(name, []):
                used.setdefault(name, []).append(comp.name)
    return used


def sheets_shape(scene) -> tuple:
    """A fingerprint of everything the Sheets tab lists."""
    return (tuple(v.name for v in getattr(scene, "saved_views", None) or ()),
            tuple((c.name, c.paper,
                   tuple((f.view_key, f.scale_n, id(f)) for f in c.frames))
                  for c in getattr(scene, "compositions", None) or ()))


def frames_showing(scene, name: str) -> list:
    """``[(sheet, frame)]`` for every view frame that shows scene ``name``."""
    return [(comp, frame)
            for comp in getattr(scene, "compositions", None) or ()
            for frame in comp.frames if frame_scene(frame) == name]


def rename_scene(scene, view, name: str) -> bool:
    """Rename a saved scene AND every sheet frame that shows it: frames
    name their scene, so renaming only the scene left them orphans. False
    (nothing changed) when ``name`` is empty or another scene has it."""
    name = (name or "").strip()
    if not name or name == view.name:
        return False
    if any(v is not view and v.name == name
           for v in getattr(scene, "saved_views", None) or ()):
        return False
    for _comp, frame in frames_showing(scene, view.name):
        frame.view_key = f"scene:{name}"
    view.name = name
    return True


def isolate_hides(groups, keep) -> list:
    """What Isolate hides so only ``keep`` (and what holds it) shows: at
    every level on the way down to a kept group, the siblings that hold
    nothing kept. Groups already hidden are left as they are."""
    keep_ids = {id(g) for g in keep}
    up = parents(groups)
    holders = set(keep_ids)
    for g in keep:
        p = up.get(id(g))
        while p is not None:
            holders.add(id(p))
            p = up.get(id(p))
    hide = []
    for g, p, _d in walk(groups):
        if id(g) in holders or g.hidden:
            continue
        if p is None or (id(p) in holders and id(p) not in keep_ids):
            hide.append(g)
    return hide


# ---- Re-nesting -------------------------------------------------------------

def world_matrix(groups, group):
    """The matrix that takes ``group``'s own coordinates to the world, or
    ``None`` when nothing on its chain is transformed (the model itself,
    ``group=None``, is the world)."""
    if group is None:
        return None
    from core.group import iter_placements
    for top in groups:
        for placed, m in iter_placements(top):
            if placed is group:
                return m
    return None


def compose(a, b):
    """``a * b`` where ``None`` stands for the identity."""
    if a is None:
        return b
    if b is None:
        return a
    return a * b


def topmost(groups, chosen) -> list:
    """``chosen`` without the ones inside another chosen group — those
    travel with it — in document order."""
    ids = {id(g) for g in chosen}
    up = parents(groups)
    out = []
    for g, _p, _d in walk(groups):
        if id(g) not in ids:
            continue
        p = up.get(id(g))
        while p is not None and id(p) not in ids:
            p = up.get(id(p))
        if p is None:
            out.append(g)
    return out


def in_component(groups, group) -> bool:
    """Whether ``group`` is a component or sits inside one."""
    up = parents(groups)
    g = group
    while g is not None:
        if g.is_component():
            return True
        g = up.get(id(g))
    return False


def editing_inside_component(scene) -> bool:
    """Whether the open group is a component, or sits inside one: what is
    made there would change a shared definition, so Make Group and Make
    Component refuse there, as the Browser's drag and drop does. An open
    component instance has lost its matrix for the session (it edits a
    world copy), so the edit stack says it, not ``is_component``."""
    stack = getattr(scene, "_edit_stack", None) or ()
    if any(lvl.get("share") is not None or lvl.get("definition") is not None
           for lvl in stack):
        return True
    ctx = getattr(scene, "edit_group", None)
    return ctx is not None and in_component(scene.groups, ctx)


def reparent_problem(groups, chosen, target) -> str | None:
    """Why ``chosen`` cannot go into ``target`` (``None``: the model) —
    ``"cycle"``, ``"component"``, ``"locked"`` — or ``None`` when it can
    (also when there is nothing to move)."""
    up = parents(groups)
    moving = topmost(groups, chosen)
    p = target
    while p is not None:
        if any(p is g for g in moving):
            return "cycle"
        p = up.get(id(p))
    if target is not None and in_component(groups, target):
        return "component"
    for g in moving:
        old = up.get(id(g))
        if old is not None and in_component(groups, old):
            return "component"
        if getattr(g, "locked", False):
            return "locked"
    if target is not None and getattr(target, "locked", False):
        return "locked"
    return None


def needs_moving(groups, chosen, target) -> list:
    """The groups of ``chosen`` (topmost) not already directly in
    ``target``."""
    up = parents(groups)
    return [g for g in topmost(groups, chosen) if up.get(id(g)) is not target]


def locked_on_path(groups, group) -> bool:
    """Whether ``group`` or a container above it is locked."""
    up = parents(groups)
    g = group
    while g is not None:
        if getattr(g, "locked", False):
            return True
        g = up.get(id(g))
    return False


# ---- Section planes -----------------------------------------------------------

#: A plane's four modes, as ``(cut, frame)``.
SECTION_MODES = {"both": (True, True), "cut": (True, False),
                 "frame": (False, True), "off": (False, False)}


def section_mode(plane) -> str:
    """``"both"``, ``"cut"`` (cut, no frame), ``"frame"`` (frame, no cut)
    or ``"off"``."""
    cut = bool(getattr(plane, "active", False))
    frame = not getattr(plane, "hidden", False)
    return {(True, True): "both", (True, False): "cut",
            (False, True): "frame", (False, False): "off"}[(cut, frame)]


def section_label(plane) -> str:
    """How a plane reads in a list: its symbol and its name."""
    sym = getattr(plane, "symbol", "") or ""
    name = getattr(plane, "name", "") or ""
    if sym and name:
        return f"{sym} — {name}"
    return name or sym or f"#{plane.uid}"


# ---- What extensions say a group is -----------------------------------------

def custom_kind(group, providers) -> dict | None:
    """What an extension says ``group`` is — the first provider that
    answers: ``{"type": "Window", "props": [("Panes", "3 × 2"), ...]}``
    (``props`` optional). A provider that raises is logged and skipped:
    an extension cannot break the tree."""
    for fn in providers or ():
        try:
            out = fn(group)
        except Exception:                           # noqa: BLE001
            import logging
            logging.getLogger("ingetrazo.plugins").exception(
                "outliner kind provider failed")
            continue
        if isinstance(out, dict) and out.get("type"):
            props = []
            for pair in out.get("props") or ():
                try:
                    label, value = pair
                except (TypeError, ValueError):
                    continue
                props.append((str(label), str(value)))
            return {"type": str(out["type"]), "props": props}
    return None


def material_name(group) -> str:
    """The paint the container wears as a whole, as a person names it
    ('' when it has none)."""
    from core.parts import _material_label
    return _material_label(getattr(group, "material", None)) or ""


# ---- A plan of a group ----------------------------------------------------------

def world_bounds(groups, group):
    """``(lo, hi)`` world corners of ``group`` and everything it holds, as
    ``(x, y, z)`` tuples — or ``None`` when it holds no geometry."""
    import numpy as np
    from core.group import iter_placements
    up = parents(groups)
    base = world_matrix(groups, up.get(id(group)))
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for g, m in iter_placements(group, base):
        verts = getattr(g.mesh, "vertices", None) or ()
        if not verts:
            continue
        pts = [m.map(v.position) if m is not None else v.position
               for v in verts]
        arr = np.array([(p.x(), p.y(), p.z()) for p in pts])
        lo = np.minimum(lo, arr.min(axis=0))
        hi = np.maximum(hi, arr.max(axis=0))
    if not np.isfinite(lo).all():
        return None
    return tuple(lo.tolist()), tuple(hi.tolist())


def unique_name(base: str, taken) -> str:
    """``base``, or ``base 2``, ``base 3``… — the first one not taken."""
    taken = set(taken)
    if base not in taken:
        return base
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def free_slot(sheet, w_mm: float, h_mm: float, gap: float = 10.0,
              fallback: bool = True):
    """Where a ``w_mm`` × ``h_mm`` view fits on ``sheet`` without covering
    the views already there: the first free place on a grid inside the
    margins, left to right and top to bottom — or, when the page is full,
    a step down and right from the last view (``None`` instead, with
    ``fallback=False``)."""
    pw, ph = sheet.page_size_mm()
    m = float(getattr(sheet, "margin_mm", 10.0) or 0.0)
    taken = [(f.x_mm, f.y_mm, f.x_mm + f.w_mm, f.y_mm + f.h_mm)
             for f in sheet.frames]

    def free(x, y) -> bool:
        return all(x + w_mm + gap / 2 <= a or x - gap / 2 >= c
                   or y + h_mm + gap / 2 <= b or y - gap / 2 >= d
                   for a, b, c, d in taken)

    y = m + gap
    while y + h_mm <= ph - m:
        x = m + gap
        while x + w_mm <= pw - m:
            if free(x, y):
                return x, y
            x += gap
        y += gap
    if not fallback:
        return None
    if taken:
        a, b, _c, _d = taken[-1]
        return a + 2 * gap, b + 2 * gap
    return m + gap, m + gap


def unplaced_scenes(scene) -> list:
    """The saved scenes no sheet shows."""
    used = scene_usage(scene)
    return [v for v in getattr(scene, "saved_views", None) or ()
            if v.name not in used]


#: The scales a view frame is offered (1:n), smallest n first.
STANDARD_SCALES = (1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250,
                   300, 500, 750, 1000, 1250, 2000, 2500, 5000, 10000)


def fit_scale(scene, view, w_mm: float, h_mm: float,
              fill: float = 0.85) -> float:
    """The first standard scale at which the model, seen from ``view``
    (a saved scene), fits a ``w_mm`` × ``h_mm`` frame, using ``fill`` of
    it — 100 when the model is empty."""
    lo, hi = scene.bounds()
    if lo is None:
        return 100.0
    from PySide6.QtGui import QVector3D
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    cam.target = QVector3D(*view.target)
    cam.distance = view.distance
    cam.yaw, cam.pitch = view.yaw, view.pitch
    cam.perspective = False
    m = cam.view_matrix()
    xs, ys = [], []
    for x in (lo.x(), hi.x()):
        for y in (lo.y(), hi.y()):
            for z in (lo.z(), hi.z()):
                p = m.map(QVector3D(x, y, z))
                xs.append(p.x())
                ys.append(p.y())
    wide = max(xs) - min(xs)
    tall = max(ys) - min(ys)
    need = max(wide * 1000.0 / max(w_mm * fill, 1e-6),
               tall * 1000.0 / max(h_mm * fill, 1e-6))
    for n in STANDARD_SCALES:
        if n >= need:
            return float(n)
    return float(STANDARD_SCALES[-1])


def material_choices(scene, recent=()) -> list:
    """``[(label, paint)]`` for the Browser's «Material ▸» menu (#565,
    @fafecm: paint several rows from the Browser without going to the
    Materials tab): the document's materials by name, then the recent
    paints not already listed, newest first. ``paint`` is a container
    material — the keys a face's attrs use, as the Paint tool hands one to
    a group — so a texture travels as well as a colour."""
    from tools.paint import recent_key
    out: list = []
    seen: set = set()
    mats = getattr(scene, "materials", None) or {}
    for name in sorted(mats, key=lambda n: n.casefold()):
        m = mats[name]
        if m.color is None and m.texture is None:
            continue
        paint: dict = {"mat": name}
        if m.texture is not None:
            paint["texture"] = dict(m.texture)
        else:
            paint["color"] = list(m.color)
        if m.opacity is not None:
            paint["opacity"] = float(m.opacity)
        out.append((name, paint))
        seen.add(recent_key(paint))
    for entry in recent or ():
        key = recent_key(entry)
        if key in seen or not (entry.get("color") or entry.get("texture")):
            continue
        seen.add(key)
        out.append((paint_label(entry), dict(entry)))
    return out


def paint_label(paint: dict) -> str:
    """A name for a paint in a menu: its material's, the image's file name,
    or the colour as ``#RRGGBB``."""
    import os
    if paint.get("mat"):
        return str(paint["mat"])
    tex = paint.get("texture")
    if tex and tex.get("path"):
        return os.path.basename(str(tex["path"]))
    col = paint.get("color") or (0.0, 0.0, 0.0)
    return "#" + "".join(f"{max(0, min(255, round(float(c) * 255))):02X}"
                         for c in list(col)[:3])


# ---- Renaming several rows at once (#565, #87) --------------------------------

def numbered_names(count: int, base: str, start: int = 1,
                   digits: int = 2) -> list:
    """``count`` names: ``base`` and a number padded to ``digits`` —
    ``W01, W02, W03…`` from ``start``."""
    digits = max(1, int(digits))
    return [f"{base}{n:0{digits}d}" for n in range(int(start),
                                                    int(start) + count)]


def replaced_names(names, find: str, replace: str,
                   match_case: bool = False) -> list:
    """Each name with every ``find`` swapped for ``replace`` — any case
    unless ``match_case``. An empty ``find`` changes nothing."""
    import re
    if not find:
        return list(names)
    flags = 0 if match_case else re.IGNORECASE
    pattern = re.compile(re.escape(find), flags)
    return [pattern.sub(lambda _m: replace, n) for n in names]


def affixed_names(names, prefix: str = "", suffix: str = "") -> list:
    """Each name with ``prefix`` before it and ``suffix`` after it."""
    return [f"{prefix}{n}{suffix}" for n in names]
