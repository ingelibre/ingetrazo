# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The quantity takeoff as data: the «inge-takeoff» JSON a budget reads.

The same objects, quantities and GlobalIds as the IFC export
(:mod:`formats.ifc`), without the geometry: a program that keeps a budget
(IngePresupuestos) reads the live model and recognises every element in the
IFC file, and the other way round. Read-only.

Two rules:

- SI units always (``m``, ``m2``, ``m3``, ``kg``, ``und``).
- A quantity that cannot be measured is ABSENT (a volume of an open set) and
  a budget measure that cannot is ``None`` — never a 0 or a 1 made up.
"""
from __future__ import annotations

import math

from core.bim import (IFC_CLASSES, class_quantities, collect_objects,
                      object_faces, object_metrado)
from core.ifc_identity import element_guid, element_guids

SCHEMA = "inge-takeoff"
VERSION = 1

#: The unit of each kind of :func:`core.bim.class_quantities` entry.
_UNITS = {"area": "m2", "volume": "m3", "length": "m", "weight": "kg"}


def exported_class(obj) -> str:
    """The IFC entity the export writes ``obj`` as."""
    return obj["class"] if obj["class"] in IFC_CLASSES \
        else "IfcBuildingElementProxy"


def _measure(value, unit) -> dict | None:
    """``{"value", "unit"}`` with the six decimals the IFC file carries, so
    the same model read both ways shows no difference; ``None`` for what is
    not a measure."""
    if value is None or not math.isfinite(value):
        return None
    value = round(float(value), 6)
    return {"value": value, "unit": unit} if value > 0.0 else None


def _own_groups(g):
    """A tagged group and its nested groups that are not objects of their
    own."""
    yield g
    for c in getattr(g, "children", None) or ():
        if not getattr(c, "ifc", None):
            yield from _own_groups(c)


def _painted(attrs, material):
    from core.materials import has_own_material
    paint = attrs if has_own_material(attrs) else material
    return (paint or {}).get("mat")


def _material(obj, data) -> str:
    """The material given in the delivery information, as the IFC says it;
    else the named material EVERY face is painted with — a mix has none."""
    if data.get("material"):
        return str(data["material"])
    from core.group import effective_material
    from core.mesh import face_attrs
    group = obj.get("group")
    if group is None:
        owner = effective_material(obj.get("owner"))
        names = {_painted(f.attrs, owner) for f in obj["faces"]}
    else:
        names = set()
        for g in _own_groups(group):
            paint = effective_material(g)
            names.update(_painted(a, paint) for a in face_attrs(g.mesh))
    name = names.pop() if len(names) == 1 else None
    return str(name) if name else ""


def _layer(obj, parents) -> str:
    """The layer the object is drawn with; "" for faces on several."""
    from core.layers import DEFAULT_LAYER, inherited_layer, layer_of
    group = obj.get("group")
    if group is not None:
        return inherited_layer(group, parents)
    names = {layer_of(f) for f in obj["faces"]}
    owner = obj.get("owner")
    if owner is not None and DEFAULT_LAYER in names:
        names.discard(DEFAULT_LAYER)
        names.add(inherited_layer(owner, parents))
    return names.pop() if len(names) == 1 else ""


def is_selected(scene, obj, parents) -> bool:
    """Whether ``obj`` is in the selection: its group (or one around it), or
    any of its faces — those of an open group included."""
    picked = scene.selection
    group = obj.get("group") or obj.get("owner")
    if group is None:
        return any(f in picked for f in obj["faces"])
    g = group
    while g is not None:
        if g in picked:
            return True
        g = parents.get(id(g))
    if scene.edit_group is not group:
        return False
    # Its faces in ``obj`` are world copies: the open mesh's are the live
    # ones (as BimPanel picks them).
    faces = group.mesh.faces
    if "owner" in obj:
        faces = (f for f in faces
                 if (f.attrs.get("ifc") or {}).get("id") == obj["tag_id"])
    return any(f in picked for f in faces)


def takeoff(scene, document: str = "", classes=None,
            selection_only: bool = False, objects: list | None = None) -> dict:
    """The takeoff of the BIM-tagged objects. ``classes`` (IFC names, as
    exported) and ``selection_only`` narrow it; ``objects`` are the model's
    :func:`core.bim.collect_objects`, when the caller has them. Raises
    ``ValueError`` where the IFC export does: two objects with one
    identity."""
    from core import outliner
    from core.turkiye_delivery import metadata
    if objects is None:
        objects = collect_objects(scene)
    objects = [o for o in objects if object_faces(o)]
    wanted = None
    if classes is not None:
        known = {c.casefold(): c for c in (
            *IFC_CLASSES, "IfcBuildingElementProxy")}
        unknown = [c for c in classes if str(c).casefold() not in known]
        if unknown:
            raise ValueError("unknown IFC class "
                             + ", ".join(repr(c) for c in unknown)
                             + "; one of " + ", ".join(known.values()))
        wanted = {known[str(c).casefold()] for c in classes}
    parents = outliner.parents(scene.groups)
    spatial = scene.ifc_project.get("spatial") or {}
    storeys = {s.get("id"): s.get("name") or ""
               for s in spatial.get("storeys") or ()}
    elements = []
    for obj, gid in zip(objects, element_guids(scene, objects)):
        cls = exported_class(obj)
        if wanted is not None and cls not in wanted:
            continue
        if selection_only and not is_selected(scene, obj, parents):
            continue
        data = metadata(obj)
        quantities = {}
        for kind, name, value in class_quantities(
                obj["class"], object_faces(obj))[1]:
            measure = _measure(value, _UNITS[kind])
            if measure is not None:
                quantities[name] = measure
        elements.append({
            "global_id": gid,
            "ifc_class": cls,
            "name": obj["name"] or cls,
            "type": data.get("object_type") or "",
            "storey": storeys.get(data.get("storey_id"), ""),
            "layer": _layer(obj, parents),
            "material": _material(obj, data),
            "quantities": quantities,
            "metrado": _measure(*object_metrado(obj)),
        })
    return {"schema": SCHEMA, "version": VERSION,
            "source": {"app": "IngeTrazo", "document": document,
                       "namespace": scene.ifc_namespace},
            "elements": elements}


def find_objects(scene, global_ids, objects: list | None = None) -> tuple:
    """``(objects, missing)``: the BIM objects the export gives those
    GlobalIds, and the GlobalIds the model does not have, in the order
    asked."""
    wanted = list(dict.fromkeys(global_ids))
    by_gid: dict = {}
    if wanted:
        for obj in collect_objects(scene) if objects is None else objects:
            if object_faces(obj):
                by_gid.setdefault(element_guid(scene, obj), []).append(obj)
    return ([o for gid in wanted for o in by_gid.get(gid, ())],
            [gid for gid in wanted if gid not in by_gid])
