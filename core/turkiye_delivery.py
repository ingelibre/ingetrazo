# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Opt-in, source-traceable Türkiye naming and property-field checks.

This checks the implemented field matrix, not legal applicability or the
whole delivery package. Missing technical values are never inferred.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import json
import math
import re

from core.history import Command
from core.paths import app_root

PROFILE = "TR_EK5_2026"


@lru_cache(maxsize=1)
def rules():
    path = app_root() / "resources" / "bim" / "turkiye_delivery.json"
    return json.loads(path.read_text(encoding="utf-8"))


def ui(source):
    """The data-driven profile carries its own English/Spanish/Turkish labels."""
    from core.i18n import current_language, tr
    return rules()["ui"].get(source, {}).get(current_language(), tr(source))


def metadata(obj):
    tag = obj["group"].ifc if obj.get("group") is not None else obj["faces"][0].attrs["ifc"]
    return tag.get("delivery", {})


def generated_name(cls, data):
    category = rules()["classes"].get(cls, {}).get("category")
    discipline, description = data.get("discipline", ""), data.get("description", "")
    if not category or discipline not in rules()["disciplines"] or not description:
        return ""
    mode = data.get("separator", "annex5")
    if mode not in ("annex5", "article11"):
        return ""
    separator = "_" if mode == "annex5" else "-"
    if not all(token and token.isalnum() for token in description.split(separator)):
        return ""
    return f"{discipline}-{category}-{description}"


def property_values(cls, data):
    """Yield only supported, correctly typed values; reject unknown fields."""
    spec = rules()["classes"].get(cls, {})
    for pset, values in data.get("psets", {}).items():
        if pset not in spec.get("psets", {}):
            raise ValueError(f"Unsupported property set for {cls}: {pset}")
        for name, value in values.items():
            kind = spec["psets"][pset].get(name)
            if kind is None:
                raise ValueError(f"Unsupported property: {pset}.{name}")
            if value is None or value == "":
                continue
            valid = (isinstance(value, str) if kind == "IfcLabel" else
                     type(value) is bool if kind == "IfcBoolean" else
                     type(value) in (int, float) and math.isfinite(value) and value > 0)
            if not valid:
                raise ValueError(f"Invalid {kind} value: {pset}.{name}")
            yield pset, name, kind, value



def layer_issues(data, required=False):
    layer = data.get("layer", {})
    if not layer and not required:
        return []
    if not isinstance(layer, dict):
        return ["Expected material layer fields"]
    errors = []
    for key in ("thickness", "offset"):
        value = layer.get(key)
        if type(value) not in (int, float) or not math.isfinite(value):
            errors.append(f"layer.{key}: finite length required")
        elif key == "thickness" and value < 0:
            errors.append("layer.thickness: non-negative length required")
    if layer.get("axis") not in ("AXIS1", "AXIS2", "AXIS3"):
        errors.append("layer.axis: AXIS1 / AXIS2 / AXIS3 required")
    if layer.get("sense") not in ("POSITIVE", "NEGATIVE"):
        errors.append("layer.sense: POSITIVE / NEGATIVE required")
    return errors

def object_issues(obj, schema="IFC4X3_ADD2", required=True):
    cls, data = obj["class"], metadata(obj)
    spec = rules()["classes"].get(cls)
    issues = []
    def add(field, message, severity="error"):
        issues.append({"object": obj["name"], "class": cls, "field": field,
                       "message": message, "severity": severity})
    if spec is None:
        if required:
            add("category", "No verified category for this IFC class.")
        elif data:
            add("delivery", "No verified category for this IFC class.")
        return issues
    if not isinstance(data, dict):
        add("delivery", "Expected an object")
        return issues
    for key in ("discipline", "description", "separator", "predefined_type",
                "tag", "object_type", "material"):
        if key in data and not isinstance(data[key], str):
            add(key, "Expected text")
    if issues:
        return issues
    if required:
        name = generated_name(cls, data)
        if not name or name != obj["name"]:
            add("Name", "Missing or inconsistent generated name")
    if cls == "IfcSpace":
        if data.get("material"):
            add("material", "IfcSpace cannot have a direct material association")
        if data.get("tag"):
            add("tag", "IfcSpace has no Tag attribute")
    predefined = data.get("predefined_type", "")
    if predefined and predefined not in spec["predefined_types"].get(schema, []):
        add("PredefinedType", "Unsupported predefined type for this schema")
    if required and not predefined:
        add("PredefinedType", "Missing / not entered")
    if predefined == "USERDEFINED" and not data.get("object_type", "").strip():
        add("ObjectType", "USERDEFINED requires ObjectType")
    if required and spec["tag_required"] and not data.get("tag", "").strip():
        add("Tag", "Missing / not entered")
    if required and spec["material_required"]:
        material = data.get("material", "")
        if not re.fullmatch(r"[^\s_]+(?:_[^\s_]+)+", material):
            add("IfcMaterial.Name", "Expected material_name_strength, e.g. Beton_C25")
    if spec.get("layer_required"):
        if data.get("layer") and not data.get("material", "").strip():
            add("material_layers", "Material is required for a material layer")
        for error in layer_issues(data, required=required):
            add("material_layers", error)
    elif data.get("layer"):
        add("material_layers", "Material layers are only implemented for IfcCovering")
    try:
        present = {(pset, name) for pset, name, _kind, _value in property_values(cls, data)}
    except (ValueError, TypeError, AttributeError) as exc:
        add("psets", str(exc))
        present = set()
    if required:
        for pset, fields in spec["psets"].items():
            for name in fields:
                if (pset, name) not in present:
                    add(f"{pset}.{name}", "Missing / not entered")
        if spec.get("unimplemented"):
            add("material_layers", "Material-layer or space-covering relationship not verified.")
    return issues


def check_scene(scene, objects=None):
    from core.bim import collect_objects
    objects = collect_objects(scene) if objects is None else objects
    issues = []
    project = scene.ifc_project
    for field in ("name", "project_type"):
        if not isinstance(project.get(field), str) or not project[field].strip():
            issues.append({"object": "IfcProject", "class": "IfcProject", "field": field,
                           "message": "Missing / not entered", "severity": "error"})
    if not objects:
        issues.append({"object": "", "class": "", "field": "objects",
                       "message": "No tagged BIM objects to export", "severity": "error"})
    for obj in objects:
        issues.extend(object_issues(obj))
    return {"profile": PROFILE, "checked_fields_complete": not issues,
            "regulatory_compliance": "not_assessed", "issues": issues,
            "unchecked": ["Authority-issued project code validity", "EK-2 delivery filename",
                          "EK-7 actors, organisations and coordinate reference system",
                          "Multiple layers and geometry/material alignment",
                          "Spatial container names/properties and full storey hierarchy",
                          "EK-8 geometry development level", "EK-9 delivery forms",
                          "Legal applicability and source separator discrepancy"]}


class SetDeliveryInformationCommand(Command):
    """Undoable project/object metadata edits; copy nested dictionaries."""
    def __init__(self, scene, project, obj=None, data=None):
        self.project = copy.deepcopy(project)
        self.before_project = copy.deepcopy(scene.ifc_project)
        self.targets = []
        self.before = []
        self.data = copy.deepcopy(data)
        self.name = generated_name(obj["class"], data) if obj is not None else ""
        if obj is not None:
            if obj.get("group") is not None:
                self.targets = [obj["group"]]
            else:
                owner = obj.get("owner")
                mesh = owner.mesh if owner is not None else scene.loose_mesh
                tag_id = obj["faces"][0].attrs["ifc"].get("id")
                self.targets = [f for f in mesh.faces if f.attrs.get("ifc", {}).get("id") == tag_id]
            self.before = [copy.deepcopy(self._tag(t)) for t in self.targets]

    @staticmethod
    def _tag(target):
        return target.ifc if hasattr(target, "ifc") else target.attrs["ifc"]

    @staticmethod
    def _put(target, tag):
        if hasattr(target, "ifc"):
            target.ifc = copy.deepcopy(tag)
        else:
            target.attrs["ifc"] = copy.deepcopy(tag)

    def do(self, scene):
        scene.ifc_project = copy.deepcopy(self.project)
        for target, before in zip(self.targets, self.before):
            tag = copy.deepcopy(before)
            tag["delivery"] = copy.deepcopy(self.data)
            if self.name:
                tag["name"] = self.name
            self._put(target, tag)
        self._touch(scene)

    def undo(self, scene):
        scene.ifc_project = copy.deepcopy(self.before_project)
        for target, before in zip(self.targets, self.before):
            self._put(target, before)
        self._touch(scene)

    @staticmethod
    def _touch(scene):
        from core import bim
        bim._TAG_EPOCH += 1
        scene.version += 1
