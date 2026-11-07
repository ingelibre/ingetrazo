# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Component definitions the document keeps with no copy placed.

A component lives in its copies: delete the last one, or replace it with
another, and its definition was gone from the file. Marking it «Keep in
File» stores a TEMPLATE in ``scene.kept_components`` — a placement-free
instance (identity ``xform``) that shares the prototype mesh and the
subgroups with the copies still in the model, so an edit to the definition
reaches it as it reaches them. It never draws, picks or exports; the tray's
«In model» list shows it, with its copy count, ready to be placed again or
to replace other copies. A small in-file library.
"""
from __future__ import annotations


def kept_template(scene, mesh):
    """The template kept for the definition whose prototype is ``mesh``,
    or ``None``."""
    for t in getattr(scene, "kept_components", None) or ():
        if t.mesh is mesh:
            return t
    return None


def make_template(instance):
    """A placement-free copy of ``instance``'s definition: same prototype
    and shared subgroups, name, axes and what was generated or tagged with
    it — none of what belongs to that one copy (place, layer, paint,
    visibility)."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import copy_group
    t = copy_group(instance)
    t.xform = QMatrix4x4()
    t.layer = None
    t.material = None
    t.hidden = False
    t.explode_offset = None
    t.component = True
    return t


def place_copy(template, matrix=None):
    """A new instance of a kept definition, at ``matrix`` (identity = where
    the definition's own origin sits)."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import copy_group
    g = copy_group(template)
    g.xform = QMatrix4x4(matrix) if matrix is not None else QMatrix4x4()
    return g


def copies_of(scene, mesh) -> list:
    """Every placed copy of the definition whose prototype is ``mesh`` —
    at the top level and nested inside other groups, never the kept
    template."""
    from core.purge import iter_groups
    return [g for g in iter_groups(getattr(scene, "groups", None))
            if g.mesh is mesh and g.is_component()]


def orphaned_by(scene, targets) -> list:
    """The definitions that would be left with no copy at all if
    ``targets`` stopped using them, and are not kept: one instance standing
    for each. What Replace Component asks about before it lets them go."""
    out: list = []
    seen: set = set()
    leaving = {id(g) for g in targets}
    for g in targets:
        if id(g.mesh) in seen or not g.is_component():
            continue
        seen.add(id(g.mesh))
        if kept_template(scene, g.mesh) is not None:
            continue
        if all(id(c) in leaving for c in copies_of(scene, g.mesh)):
            out.append(g)
    return out


def definitions_of(scene) -> list:
    """One template per component definition ``scene`` holds — placed or
    kept — leaving out face-me cutouts and the app's own scale figure.
    What «Components from File…» brings in from another document."""
    from core.insert import is_scale_figure
    out: list = []
    seen: set = set()
    for g in (list(getattr(scene, "groups", None) or ())
              + list(getattr(scene, "kept_components", None) or ())):
        if (not g.is_component() or getattr(g, "billboard", False)
                or is_scale_figure(g) or id(g.mesh) in seen):
            continue
        seen.add(id(g.mesh))
        out.append(make_template(g))
    return out


def names_in_use(scene, skip=None) -> set:
    """The names of every group and component in the model — nested ones
    and the kept templates too — but ``skip``'s own."""
    from core.purge import iter_groups
    groups = list(iter_groups(getattr(scene, "groups", None)))
    groups += list(getattr(scene, "kept_components", None) or ())
    return {g.name for g in groups if g is not skip and g.name}


def numbered_name(name: str, taken) -> str:
    """``name`` made free with a number: «Silla» → «Silla #2», and a name
    that already ends in one counts on from it — «Puerta #3» → «Puerta #4»
    — skipping every name in ``taken`` (#620, @ibsgroupdubai-netizen: Make
    Unique left two objects with the same name)."""
    import re
    m = re.match(r"^(.*?)\s*#(\d+)$", name)
    base, n = (m.group(1), int(m.group(2)) + 1) if m else (name, 2)
    taken = set(taken)
    while f"{base} #{n}" in taken:
        n += 1
    return f"{base} #{n}"
