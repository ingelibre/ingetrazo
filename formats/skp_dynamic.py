# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
# Dynamic attribute layout and placement rules adapted from moominot's
# skp_dc_import (GPL-3.0-or-later), https://github.com/moominot/ingetrazo-skp-dc-import.
"""Keep dynamic SKP trees in the ordinary parse/apply payload boundary.

Geometry remains shared by definition; attributes, hidden state and paint
belong to each placement. Parsing constructs no Scene or Mesh objects.
"""
from __future__ import annotations

import copy
import math

KEY = "skp_dc_import"


def attributes(entity):
    return (getattr(entity, "attribute_dictionaries", None) or {}).get(
        "dynamic_attributes", {}) or {}


def has_dynamic(model):
    definitions = list((getattr(model, "definitions", None) or {}).values())
    root = getattr(model, "root", None)
    return any(attributes(d) or any(attributes(i) for i in d.instances)
               for d in [model, *definitions, *([root] if root else [])]
               if hasattr(d, "instances")) or bool(attributes(model))


def _safe(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return str(value)


def adapt(model, name, attr_map):
    """Return geometry prototypes and placement records, without flattening."""
    from PySide6.QtGui import QMatrix4x4
    from formats import skp_openskp as so
    from formats.skp_consumption import SoftSegments

    definitions = getattr(model, "definitions", {}) or {}
    by_id = {d.id: d for d in definitions.values()}
    root = getattr(model, "root", None)
    protos, proto_of = [], {}
    count = 0

    def prototype(d):
        if d.id in proto_of:
            return proto_of[d.id]
        idx = proto_of[d.id] = len(protos)
        faces, loose, soft = [], [], SoftSegments()
        # No child lookup: each child is placed separately, including small
        # or hidden parts that the static import may otherwise flatten.
        so._collect(d, QMatrix4x4(), {}, attr_map, faces, 0, set())
        so._soft_edge_segments(d, QMatrix4x4(), soft)
        so._loose_edge_segments(d, QMatrix4x4(), loose)
        protos.append({"name": d.name or name, "faces": faces,
                       "loose_edges": loose, "soft_edges": soft,
                       "instances": [], "children": [],
                       "component": not getattr(d, "is_group", False)})
        return idx

    def placement(d, inst=None, ancestors=frozenset()):
        nonlocal count
        count += 1
        if count > 100_000 or len(ancestors) > 32 or d.id in ancestors:
            raise ValueError("Dynamic component tree is too large or recursive")
        definition_da, instance_da = attributes(d), attributes(inst)
        entry = {"proto": prototype(d),
                 "xform": so._matrix(inst.matrix) if inst else QMatrix4x4(),
                 "name": getattr(inst, "name", "") or d.name or name,
                 "hidden": bool(getattr(inst, "hidden", False)),
                 "layer": getattr(inst, "layer", None),
                 "children": []}
        material = attr_map.get(getattr(inst, "material_id", None))
        if material:
            entry["material"] = copy.deepcopy(material)
        if definition_da or instance_da:
            entry["ext"] = {KEY: {
                "definition": d.name or name,
                "definition_guid": getattr(d, "guid", ""),
                "instance_guid": getattr(inst, "guid", ""),
                "is_group": bool(getattr(d, "is_group", False)),
                "definition_attributes": _safe(definition_da),
                "instance_attributes": _safe(instance_da)}}
        for child in d.instances:
            target = by_id.get(child.ref_idx)
            if target is not None:
                entry["children"].append(placement(target, child, ancestors | {d.id}))
        return entry

    if root is None:
        raise ValueError("Dynamic SKP model has no root")
    # A component saved to its own file stores its definition dictionary
    # on the model itself, rather than on a placed component definition.
    if attributes(model):
        tree = placement(root)
        tree["name"] = str(attributes(model).get("_name") or name)
        tree["ext"] = {KEY: {"definition": name,
                              "definition_attributes": _safe(attributes(model)),
                              "instance_attributes": {}}}
        roots = [tree]
    else:
        roots = []
        if root.faces or root.edges:
            roots.append({"proto": prototype(root), "xform": QMatrix4x4(),
                          "name": name, "children": []})
        for inst in root.instances:
            if inst.ref_idx in by_id:
                roots.append(placement(by_id[inst.ref_idx], inst))
    return {"backend": "openskp", "groups": [], "protos": protos,
            "placements": roots}
