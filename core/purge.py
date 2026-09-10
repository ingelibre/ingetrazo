# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Purge unused — SketchUp's "Purgar sin usar", for layers and materials.

A layer is a LABEL an entity carries, never its owner (see core.layers), so
deleting the geometry cannot delete the tag: the layer you empty on purpose
to refill it must survive, and undo would have to resurrect it otherwise.
What every CAD offers instead is an explicit sweep, and this is ours.

It matters most right after an import. Marco brought a surveyed plaza in as
a reference, kept one flat drawing as a guide and deleted the rest — and the
document still carried the 13 layers and 47 materials of the big drawing,
invisible (the Materials panel builds its "In model" swatches from painted
faces, not from the registry) but saved into every ``.igz`` from then on.

The traversal descends into nested placements. ``Group.children`` are real
geometry that renders, picks and exports as part of its parent, so a name
used only inside one is IN USE — a sweep that walked ``scene.groups`` as a
flat list would delete a layer out from under a component's insides.
"""
from __future__ import annotations

from core.layers import DEFAULT_LAYER, layer_of


def iter_groups(groups):
    """Every group in ``groups``, nested placements included, each once.

    ``core.group.iter_placements`` is the canonical descent — unfiltered,
    which is what a sweep needs: a hidden group's layer is still in use, and
    so is a face-me billboard's (``Scene.placements`` drops both, on purpose,
    because it answers "what do I draw"). Instances share prototype meshes by
    identity, so ``seen`` keeps one from being counted twice.
    """
    from core.group import iter_placements
    seen: set[int] = set()
    for g in groups or ():
        for pg, _m in iter_placements(g):
            if id(pg) in seen:
                continue
            seen.add(id(pg))
            yield pg


def iter_meshes(scene):
    """The loose mesh plus every group's mesh, each distinct mesh once.

    ``scene.loose_mesh`` rather than ``scene.mesh``: inside an open group
    edit the two differ, and sweeping the model while the user is in a group
    must still see the geometry they left outside.
    """
    seen: set[int] = set()
    meshes = [scene.loose_mesh]
    meshes += [g.mesh for g in iter_groups(getattr(scene, "groups", None))]
    for m in meshes:
        if m is not None and id(m) not in seen:
            seen.add(id(m))
            yield m


def _annotations(scene):
    for coll in ("dimensions", "text_labels", "image_planes",
                 "section_planes"):
        yield from (getattr(scene, coll, None) or ())


def used_layers(scene) -> set[str]:
    """Every layer name something in the document carries."""
    used = {DEFAULT_LAYER}
    for mesh in iter_meshes(scene):
        for f in mesh.faces:
            used.add(layer_of(f))
        for e in mesh.edges:
            used.add(layer_of(e))
    for g in iter_groups(getattr(scene, "groups", None)):
        if getattr(g, "layer", None):
            used.add(g.layer)
    for ent in _annotations(scene):
        used.add(layer_of(ent))
    return used


def layers_held_by_scenes(scene) -> set[str]:
    """Layer names a saved view switches off.

    An empty layer a scene deliberately hides is not litter — it is part of
    that scene's meaning, and SketchUp users build plan/elevation scenes
    around tags they are about to fill. The sweep leaves them alone and says
    so, rather than quietly breaking a view.
    """
    held: set[str] = set()
    for view in getattr(scene, "saved_views", None) or ():
        held.update(getattr(view, "hidden_layers", None) or ())
    return held


def unused_layers(scene) -> list:
    """The :class:`core.layers.Layer` objects a purge would remove."""
    keep = used_layers(scene) | layers_held_by_scenes(scene)
    return [ly for ly in getattr(scene, "layers", None) or ()
            if ly.name != DEFAULT_LAYER and ly.name not in keep]


def used_materials(scene) -> set[str]:
    """Every registry material name a face wears (``attrs["mat"]``)."""
    used: set[str] = set()
    for mesh in iter_meshes(scene):
        for f in mesh.faces:
            name = f.attrs.get("mat")
            if name:
                used.add(name)
    return used


def unused_materials(scene) -> list[str]:
    """Registry material names no face wears, in registry order."""
    used = used_materials(scene)
    return [n for n in getattr(scene, "materials", None) or () if n not in used]
