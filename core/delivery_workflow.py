# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Project-specific delivery checks, with evidence rather than blanket status.

Automated model checks and a named professional's review are separate results.
The latter can never be manufactured by the exporter.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import uuid

from core.paths import app_root


@lru_cache(maxsize=1)
def specification():
    return json.loads((app_root() / "resources/bim/turkiye_workflow.json").read_text("utf-8"))


def new_node(kind):
    return {"id": uuid.uuid4().hex, "name": "", "psets": {}, "kind": kind}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def filename(project, extension="ifc", overrides=None):
    """EK-2's nine fields; do not confuse the file-type field with extension."""
    from core.turkiye_delivery import rules
    data = {**project.get("filename", {}), **(overrides or {})}
    code = re.sub("_", "", str(project.get("name", "")))
    fields = [code, data.get("building", ""), data.get("discipline", ""),
              data.get("subdiscipline", ""), data.get("kind", ""),
              data.get("type", ""), data.get("location", ""),
              data.get("sequence", ""), data.get("revision", "")]
    patterns = [r"[A-Z0-9]{6}", r"[A-Z0-9]{2}", r"[A-Z]{2}", r"[A-Z]{4}",
                r"[A-Z]{2}", r"[A-Z]{3}", r"[A-Z0-9]{3}", r"[0-9]{2}", r"[0-9]{3}"]
    if any(not isinstance(v, str) or not re.fullmatch(p, v)
           for p, v in zip(patterns, fields)):
        raise ValueError("EK-2: all nine filename fields must have the specified lengths")
    if fields[2] not in rules()["disciplines"] or fields[4] not in specification()["file_kinds"]:
        raise ValueError("EK-2: unsupported discipline or document kind")
    if fields[5] not in specification()["file_types"]:
        raise ValueError("EK-2: unsupported document type")
    if int(fields[7]) < 1:
        raise ValueError("EK-2: sequence starts at 01")
    if extension.lower() not in ("ifc", "pdf", "json", "html", "igz"):
        raise ValueError("Unsupported delivery extension")
    return "_".join(fields) + "." + extension.lower()


def spatial_fields(kind, node):
    """Canonical typed properties/quantities, including explicit exceptions."""
    for pset, fields in specification()["spatial"][kind]["psets"].items():
        for name, typ in fields.items():
            value = node.get("psets", {}).get(pset, {}).get(name)
            yield pset, name, typ, value


def valid_value(typ, value):
    if typ == "IfcBoolean":
        return type(value) is bool
    if typ == "IfcLabelList":
        return isinstance(value, list) and bool(value) and all(
            isinstance(v, str) and v.strip() for v in value)
    if typ in ("IfcLabel", "IfcIdentifier", "IfcText"):
        return isinstance(value, str) and bool(value.strip())
    return finite(value) and (value > 0 if typ == "IfcPositiveRatioMeasure" else
                             value >= 0 if typ in ("IfcAreaMeasure", "IfcRatioMeasure") else True)


def project_issues(scene, objects):
    """Required inputs and referential integrity; no implicit defaults."""
    from core.turkiye_delivery import metadata
    p = scene.ifc_project
    errors = []
    def add(field, message):
        errors.append({"object": "IfcProject", "class": "IfcProject", "field": field,
                       "message": message, "severity": "error"})
    if type(p.get("created_at")) is not int or not 0 <= p["created_at"] <= int(dt.datetime.now().timestamp()):
        add("created_at", "Recorded creation timestamp required")
    for key in ("authority_reference",):
        if not str(p.get(key, "")).strip():
            add(key, "Record the authority's project identifier / naming instructions")
    application = p.get("application", {})
    for key in ("province", "district", "neighborhood", "block", "parcel", "status"):
        if not isinstance(application.get(key), str) or not application[key].strip():
            add("application." + key, "Required application / cadastral information")
    year = application.get("year")
    if type(year) is not int or not 2000 <= year <= 9999:
        add("application.year", "Application year required")
    scope = p.get("applicability", {})
    for key in ("use", "authority_reference", "decision"):
        if not isinstance(scope.get(key), str) or not scope[key].strip():
            add("applicability." + key, "Record project scope, transition decision and its evidence")
    for key in ("area", "province_population", "municipality_population", "storeys_above_ground"):
        if not finite(scope.get(key)) or scope[key] < 0:
            add("applicability." + key, "Non-negative project-specific numeric value required")
        elif key != "area" and type(scope[key]) is not int:
            add("applicability." + key, "Whole-number value required")
    for key in ("detached", "agricultural_exempt", "preexisting_application"):
        if type(scope.get(key)) is not bool:
            add("applicability." + key, "Explicit project-specific yes/no required")
    survey = p.get("survey", {})
    if survey.get("enabled"):
        for key in ("name", "description"):
            if not str(survey.get(key, "")).strip(): add("survey." + key, "Survey reference information required")
        for key in ("x", "y", "z"):
            if not finite(survey.get(key)): add("survey." + key, "Measured model-coordinate value required")
    author = p.get("author", {})
    for key in ("person_id", "given_name", "family_name", "organization_id", "organization",
                "address", "town", "region", "country", "role", "organization_role"):
        if not isinstance(author.get(key), str) or not author[key].strip():
            add("author." + key, "Required participant information")
    for key in ("role", "organization_role"):
        if author.get(key) and author[key] not in specification()["roles"]:
            add("author." + key, "Invalid IFC actor role")
    if "USERDEFINED" in (author.get("role"), author.get("organization_role")):
        if not author.get("user_role", "").strip():
            add("author.user_role", "USERDEFINED requires the role description")
    crs = p.get("crs", {})
    for key in ("name", "geodetic_datum", "vertical_datum", "projection", "zone"):
        if not str(crs.get(key, "")).strip():
            add("crs." + key, "Required coordinate reference information")
    epsg = {f"EPSG:{5253 + i}": str(27 + i * 3) for i in range(7)}
    if crs.get("name") not in epsg or epsg.get(crs.get("name")) != str(crs.get("zone")):
        add("crs.name", "EK-7: select matching TUREF 3-degree EPSG / central meridian")
    for key in ("eastings", "northings", "height", "x_abscissa", "x_ordinate", "scale", "precision"):
        if not finite(crs.get(key)):
            add("crs." + key, "Finite numeric value required")
    if finite(crs.get("scale")) and crs["scale"] <= 0:
        add("crs.scale", "Scale must be positive")
    if finite(crs.get("precision")) and not 1e-8 <= crs["precision"] <= 1e-5:
        add("crs.precision", "EK-7 precision range is 1E-8..1E-5 metres")
    if all(finite(crs.get(k)) for k in ("x_abscissa", "x_ordinate")):
        if abs(math.hypot(crs["x_abscissa"], crs["x_ordinate"]) - 1) > 1e-8:
            add("crs.axis", "Enter a unit direction for local X")
    try:
        filename(p)
    except ValueError as exc:
        add("filename", str(exc))
    naming = p.get("filename", {})
    if naming.get("kind") != "MD":
        add("filename", "The IFC model document kind must be MD")
    if not finite(naming.get("max_size_mb")) or naming["max_size_mb"] <= 0:
        add("filename.max_size_mb", "Enter the authority's positive file-size limit in MB")
    spatial = p.get("spatial", {})
    site = spatial.get("site", {})
    buildings, storeys = spatial.get("buildings", []), spatial.get("storeys", [])
    if not buildings or not storeys:
        add("spatial", "At least one building and storey are required")
    nodes = [("site", site)] + [("building", n) for n in buildings] + [
        ("storey", n) for n in storeys]
    ids = [n.get("id") for _, n in nodes]
    if any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(ids):
        add("spatial.ids", "Spatial IDs must be present and unique")
    building_ids = {n.get("id") for n in buildings}
    storey_ids = {n.get("id") for n in storeys}
    for building in buildings:
        children = [n for n in storeys if n.get("building_id") == building.get("id")]
        if not children:
            add("spatial.buildings", "Each building requires at least one storey")
        codes = [n.get("code") for n in children]
        if len(codes) != len(set(codes)):
            add("spatial.storeys.code", "Storey codes must be unique within each building")
    conditional = specification()["conditional_fields"]
    from core.turkiye_delivery import rules
    for kind, node in nodes:
        spec = specification()["spatial"][kind]
        name = node.get("name", "")
        parts = name.split("-", 2)
        if (len(parts) != 3 or parts[0] not in rules()["disciplines"] or
                parts[1] != spec["category"] or not parts[2] or any(c.isspace() for c in name)):
            add(kind + ".Name", "EK-5: invalid spatial name")
        if kind in ("site", "building") and not node.get("long_name", "").strip():
            add(kind + ".LongName", "Long name required")
        if kind == "site" and not finite(node.get("ref_elevation")):
            add("site.RefElevation", "Reference elevation required")
        if kind == "storey":
            if node.get("building_id") not in building_ids:
                add("storey.building_id", "Unknown parent building")
            if not finite(node.get("elevation")):
                add("storey.elevation", "Storey elevation required")
            if not re.fullmatch(r"(?:K|B)[0-9]{2}|[A-Z0-9]{3}", node.get("code", "")):
                add("storey.code", "Three-character storey code required")
        for pset, key, typ, value in spatial_fields(kind, node):
            field = f"{pset}.{key}"
            reason = node.get("exceptions", {}).get(field)
            if field in conditional and value is None and isinstance(reason, str) and reason.strip():
                continue
            if not valid_value(typ, value):
                add(f"{kind}.{field}", "Required spatial value or documented conditional exception")
    spaces = {object_key(scene, o): o for o in objects if o["class"] == "IfcSpace"}
    room_numbers = set()
    for obj in objects:
        data = metadata(obj)
        if data.get("storey_id") not in storey_ids:
            add(obj["name"] + ".storey_id", "Assign the object to an existing storey")
        space_id = data.get("space_id")
        if space_id:
            if (space_id not in spaces or obj["class"] == "IfcSpace" or
                    metadata(spaces[space_id]).get("storey_id") != data.get("storey_id")):
                add(obj["name"] + ".space_id", "Space assignment must belong to the same storey")
        if obj["class"] == "IfcSpace":
            number = data.get("room_number", "")
            floor = next((n for n in storeys if n.get("id") == data.get("storey_id")), {})
            room_key = (floor.get("building_id"), number)
            if not re.fullmatch(r"[A-Z0-9]{3}_[A-Z0-9]{3}_[0-9]{3}", number):
                add(obj["name"] + ".room_number", "EK-3: floor_function_sequence required")
            elif number[-3:] == "000" or room_key in room_numbers:
                add(obj["name"] + ".room_number", "Room sequence starts at 001 and must be unique")
            room_numbers.add(room_key)
            if number[:3] != floor.get("code"):
                add(obj["name"] + ".room_number", "Room number and assigned floor differ")
    return errors


def object_key(scene, obj):
    from core.ifc_identity import object_identity, stable_guid
    return stable_guid(scene.ifc_namespace, "element", *object_identity(obj))


def bounds(obj):
    points = [(v.position.x(), v.position.y(), v.position.z()) for f in obj["faces"] for v in f.loop]
    return tuple(min(p[i] for p in points) for i in range(3)), tuple(
        max(p[i] for p in points) for i in range(3))


def geometry_checks(scene, objects):
    from core.bim import face_set_volume, class_quantities
    from core.turkiye_delivery import metadata
    results = {k: [] for k in ("duplicates", "space_closed", "space_overlap", "storeys", "areas", "materials")}
    signatures = {}
    spatial = scene.ifc_project.get("spatial", {})
    floors = {n.get("id"): n for n in spatial.get("storeys", [])}
    spaces = []
    floor_areas = {}
    for obj in objects:
        name = obj["name"]
        coords = sorted(tuple(sorted((round(v.position.x(), 7), round(v.position.y(), 7),
            round(v.position.z(), 7)) for v in f.loop)) for f in obj["faces"])
        signature = (obj["class"], repr(coords))
        if signature in signatures:
            results["duplicates"].append(f"{name} / {signatures[signature]}")
        signatures[signature] = name
        data = metadata(obj)
        floor = floors.get(data.get("storey_id"))
        low, high = bounds(obj)
        if obj["class"] == "IfcCovering" and data.get("layer"):
            layer = data["layer"]
            axis = {"AXIS1": 0, "AXIS2": 1, "AXIS3": 2}.get(layer.get("axis"))
            layers = data.get("layers") or [layer]
            thicknesses = [entry.get("thickness") for entry in layers]
            if axis is not None and all(finite(t) and t >= 0 for t in thicknesses) and finite(layer.get("offset")):
                start = layer["offset"]
                end = start + sum(thicknesses) * (-1 if layer.get("sense") == "NEGATIVE" else 1)
                expected = sorted((start, end))
                if max(abs(low[axis]-expected[0]), abs(high[axis]-expected[1])) > 1e-4:
                    results["materials"].append(name + ": material layer span differs from geometry along the declared axis")
        if floor and finite(floor.get("elevation")) and obj["class"] not in ("IfcFooting", "IfcPile"):
            above = sorted(n["elevation"] for n in floors.values()
                           if n.get("building_id") == floor.get("building_id") and
                           finite(n.get("elevation")) and n["elevation"] > floor["elevation"])
            if low[2] < floor["elevation"] - 0.05 or (above and low[2] >= above[0] + 0.05):
                results["storeys"].append(name)
        if obj["class"] == "IfcSpace":
            if not face_set_volume(obj["faces"]):
                results["space_closed"].append(name)
            else:
                spaces.append(obj)
            _q, entries, _measure = class_quantities("IfcSpace", obj["faces"])
            area = next((v for _, key, v in entries if key == "NetFloorArea"), 0)
            key = data.get("storey_id")
            floor_areas[key] = floor_areas.get(key, 0) + area
    # Bounding boxes are a broad phase; use the existing solid kernel for
    # an actual intersection, never mark touching rooms as overlapping.
    solids = {}
    def solid(obj):
        import manifold3d as m3d
        import numpy as np
        key = id(obj)
        if key not in solids:
            vertices, indices, triangles = [], {}, []
            for face in obj["faces"]:
                for tri in face.triangulate(face.normal()):
                    ids = []
                    for point in tri:
                        coord = (point.x(), point.y(), point.z())
                        if coord not in indices:
                            indices[coord] = len(vertices); vertices.append(coord)
                        ids.append(indices[coord])
                    triangles.append(ids)
            v, t = np.array(vertices, dtype=np.float64), np.array(triangles, dtype=np.uint32)
            if np.einsum("ij,ij->i", v[t[:, 0]], np.cross(v[t[:, 1]], v[t[:, 2]])).sum() < 0:
                t = t[:, ::-1].copy()
            man = m3d.Manifold(m3d.Mesh64(vert_properties=v, tri_verts=t))
            if man.status() != m3d.Error.NoError:
                raise ValueError("Room mesh cannot be checked by the solid kernel")
            solids[key] = man
        return solids[key]
    for i, a in enumerate(spaces):
        al, ah = bounds(a)
        for b in spaces[i + 1:]:
            bl, bh = bounds(b)
            if all(min(ah[k], bh[k]) - max(al[k], bl[k]) > 1e-6 for k in range(3)):
                try:
                    if (solid(a) ^ solid(b)).volume() > 1e-7:
                        results["space_overlap"].append(a["name"] + " / " + b["name"])
                except (ValueError, RuntimeError) as exc:
                    results["space_overlap"].append(str(exc))
    for uid, area in floor_areas.items():
        floor = floors.get(uid, {})
        expected = floor.get("psets", {}).get("Qto_BuildingStoreyBaseQuantities", {}).get("NetFloorArea")
        if finite(expected) and abs(expected - area) > max(0.01, area * 0.001):
            results["areas"].append(f"{floor.get('name')}: {area:g} != {expected:g}")
    return results


def model_fingerprint(scene):
    """Hash document content without review/receipts/camera (no scene mutation)."""
    from formats import igz
    with tempfile.TemporaryDirectory(prefix="ingetrazo-fingerprint-") as folder:
        path = Path(folder) / "model.igz"
        igz.save_scene(scene, path)
        data, archive = igz._read_document(path)
        try:
            payload = data["scene"]
            # A sheet referencing the live camera changes when that camera
            # moves. Standard/saved-view sheets are independent of it.
            if not any(f.view_key == "__current__" for c in scene.compositions for f in c.frames):
                payload.pop("camera", None)
            project = payload.get("ifc_project", {})
            for key in ("review", "documents", "validator"):
                project.pop(key, None)
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                                ensure_ascii=True).encode())
            if archive:
                for name in sorted(archive.namelist()):
                    if name != "document.json":
                        digest.update(name.encode()); digest.update(archive.read(name))
            return digest.hexdigest()
        finally:
            if archive:
                archive.close()


def evaluate(scene, base_report, *, file_size=None, pdfs=None, schema_evidence=None):
    """EK-9 rows, automated facts plus separately identified human review."""
    from core.bim import collect_objects
    from core.turkiye_delivery import metadata
    objects = collect_objects(scene)
    issues = base_report["issues"] + project_issues(scene, objects)
    geometry = geometry_checks(scene, objects)
    p = scene.ifc_project
    review = p.get("review", {})
    definition = specification()["quality"]["MM" if p.get("filename", {}).get("discipline") == "MM" else "OTHER"]
    rows = []
    now = dt.date.today()
    reviewer = review.get("reviewer", "").strip()
    try:
        date_ok = dt.date.fromisoformat(review.get("date", "")) <= now
    except ValueError:
        date_ok = False
    fingerprint = model_fingerprint(scene)
    bound_review = review.get("model_fingerprint") == fingerprint
    for definition_row in definition:
        key = definition_row["key"]
        row = {**definition_row, "status": "pass", "automatic": [], "review": "pending"}
        related = [i for i in issues if (
            key == "project" and i["field"].startswith(("author.", "name", "project_type", "application.", "applicability.", "authority_reference", "created_at")) or
            key == "crs" and i["field"].startswith("crs") or
            key == "filename" and i["field"] == "filename" or
            key in ("hierarchy", "storeys") and ("spatial" in i["field"] or "storey" in i["field"]) or
            key == "space_names" and "room_number" in i["field"] or
            key in ("properties", "psets", "predefined", "object_names", "classes") and
                i["class"] != "IfcProject")]
        row["automatic"] = related + geometry.get(key, [])
        if key == "properties": row["automatic"] += geometry["materials"]
        if key == "spaces_present" and not any(o["class"] == "IfcSpace" for o in objects):
            row["automatic"].append("Architectural model requires at least one space")
        if key == "file_size":
            limit = p.get("filename", {}).get("max_size_mb")
            if file_size is None or not finite(limit) or limit <= 0:
                row["automatic"].append("File-size limit / actual exported file size required")
            elif file_size > limit * 1024 * 1024:
                row["automatic"].append("File exceeds the entered delivery limit")
        if key == "schema" and not schema_evidence:
            row["automatic"].append("Independent IFC schema validation required")
        if key == "version" and p.get("delivery_version") != 2:
            row["automatic"].append("IFC4X3_ADD2 delivery workflow required")
        if key == "pdf_model":
            if not pdfs or any(not d.get("verified") for d in pdfs):
                row["automatic"].append("Current-model PDF/A sheets required")
        answer = review.get("answers", {}).get(key, {})
        if answer.get("answer") == "yes" and answer.get("evidence", "").strip() and reviewer and date_ok and bound_review:
            row["review"] = "confirmed"
        elif answer.get("answer") == "no":
            row["review"] = "rejected"
        elif answer.get("answer") == "na" and answer.get("evidence", "").strip() and reviewer and date_ok and bound_review:
            # Geometry/identity/IFC requirements cannot be waived by a checkbox.
            if key in ("areas",):
                row["review"] = "not_applicable"
        waiting = (key == "schema" and schema_evidence is None or
                   key == "pdf_model" and pdfs is None or key == "file_size" and file_size is None)
        if row["review"] == "rejected":
            row["status"] = "fail"
        elif row["automatic"] and waiting:
            row["status"] = "pending"
        elif row["automatic"]:
            row["status"] = "fail"
        elif row["review"] == "pending":
            row["status"] = "pending"
        row["reviewer"] = reviewer
        row["review_date"] = review.get("date", "")
        row["evidence"] = answer.get("evidence", "")
        rows.append(row)
    return {"profile": "TR_DELIVERY_2026_V2", "issues": issues, "checks": rows,
            "release_ready": not issues and all(r["status"] == "pass" for r in rows),
            "model_fingerprint": fingerprint, "checked_fields_complete": not issues,
            "scope": "Current model, recorded source edition and identified reviewer evidence"}
