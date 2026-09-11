# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Insert another IngeTrazo document into the open one, as ONE component.

SketchUp's File ▸ Import of a .skp: the whole file arrives as a single
component you place with a click — a pergola, an arch, a lamp post drawn
in their own files, brought into the plaza («quiero agregar mobiliario
que ya había trabajado como pérgolas, arco, luminaria… son archivos .igz»,
Marco, 2026-09-11).

What the file holds becomes the component's tree, nothing gets baked: its
loose geometry is the container's own mesh, its groups (with their own
children and matrices) its children. A file that is exactly one group
inserts as that group. Face-me figures are left behind — a scale figure in
a furniture file is a reference, not furniture.

Materials and layers cross over by name: a material whose name is taken
by a DIFFERENT recipe registers under "name (2)" and the faces that wear
it are restamped (see :func:`core.materials.register`); layers the file
uses and the document lacks are created, visible.
"""
from __future__ import annotations

import re

from core.group import Group, iter_placements
from core.layers import DEFAULT_LAYER, Layer, layer_of
from core.materials import register

#: The name a Group gives itself when nobody named it.
_AUTO_NAME = re.compile(r"^Group \d+$")


def component_from_scene(src, name: str):
    """The component a loaded document becomes, or ``None`` when the file
    holds no geometry at all. ``src`` is consumed: its meshes and groups
    move into the component (no copies)."""
    groups = [g for g in src.groups if not getattr(g, "billboard", False)]
    mesh = src.mesh
    loose = bool(mesh.faces or mesh.edges)
    if not loose and not groups:
        return None
    if not loose and len(groups) == 1:
        comp = groups[0]
        if _AUTO_NAME.match(comp.name or ""):
            comp.name = name        # "Group 7" says nothing; the file does
        return comp
    if loose and not groups:
        return Group(mesh, name=name)
    comp = Group(mesh, name=name)
    comp.adopt(groups)          # a container is always an instance
    return comp


def _faces_of(comp):
    for g, _m in iter_placements(comp):
        yield from g.mesh.faces


def merge_materials(src_materials: dict, dst_materials: dict, comp) -> dict:
    """Register the file's materials in the document, restamping the
    component's faces where a name had to change. Returns the rename map."""
    renamed: dict = {}
    for old, mat in list(src_materials.items()):
        final = register(dst_materials, mat)
        if final != old:
            renamed[old] = final
    if renamed:
        for f in _faces_of(comp):
            a = f.attrs
            if not a:
                continue
            if a.get("mat") in renamed:
                a["mat"] = renamed[a["mat"]]
            back = a.get("back")
            if isinstance(back, dict) and back.get("mat") in renamed:
                back["mat"] = renamed[back["mat"]]
    return renamed


def ensure_layers(dst_scene, comp) -> list:
    """Create, visible, every layer the component's entities carry that
    the document does not have yet. Returns the names added."""
    have = {ly.name for ly in dst_scene.layers}
    needed: list = []

    def want(ent):
        n = layer_of(ent)
        if n != DEFAULT_LAYER and n not in have and n not in needed:
            needed.append(n)

    for g, _m in iter_placements(comp):
        want(g)
        for f in g.mesh.faces:
            want(f)
        for e in g.mesh.edges:
            want(e)
    for n in needed:
        dst_scene.layers.append(Layer(n))
    return needed


def import_document_as_component(dst_scene, src_scene, name: str):
    """The whole of ``src_scene`` as one component ready for placement in
    ``dst_scene``: materials merged, layers ensured. ``None`` = empty file."""
    comp = component_from_scene(src_scene, name)
    if comp is None:
        return None
    merge_materials(getattr(src_scene, "materials", {}) or {},
                    dst_scene.materials, comp)
    ensure_layers(dst_scene, comp)
    return comp
