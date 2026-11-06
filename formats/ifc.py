# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IFC4 / IFC4.3 ADD2 export — tagged BIM objects to a STEP Physical File.

Only what the thesis needs, written without dependencies: IFC4 is a text
format (ISO 10303-21) and our export scope is narrow — the spatial skeleton
(project → site → building → storey), one element per tagged BIM object with
its REAL IFC class, faceted-BRep geometry in world metres, and BaseQuantities
(area, and volume when the object is watertight) so downstream takeoff tools
read the numbers straight from the file. Untagged geometry is not exported —
the tag IS the opt-in, per the project's freeform-first principle.

ifcopenshell stays out deliberately: heavy native wheels lag Python releases
(the ARM/3.14 risk noted in CLAUDE.md), and import can be added later without
it constraining the writer.
"""
from __future__ import annotations

import datetime
import math
import uuid
from pathlib import Path

from core.bim import class_quantities, collect_objects, face_set_volume
from core.ifc_identity import compressed_guid, object_identity, stable_guid

SUPPORTED_SCHEMAS = ("IFC4", "IFC4X3_ADD2")

#: Attribute counts shared by IFC4 and IFC4X3_ADD2. The first 8 are the
#: common GlobalId..Tag layout; the rest are padded with ``$``. Classes with quirky
#: layouts (doors/windows carry OverallHeight/Width…, IfcSpace has LongName
#: where others have Tag) just get the right pad width.
_ATTR_COUNT = {"IfcPile": 10, "IfcDoor": 13, "IfcWindow": 13, "IfcSpace": 11,
               "IfcReinforcingBar": 14}
_DEFAULT_ATTRS = 9


def ifc_guid() -> str:
    """A 22-character IFC compressed GUID (base-64 over the IFC alphabet)."""
    return compressed_guid(uuid.uuid4())


def _s(text: str) -> str:
    """IFC string literal: apostrophes doubled, non-ASCII as STEP X2/X4 escapes."""
    out = []
    run: list[str] = []

    def flush():
        if run:
            out.append("\\X2\\" + "".join(f"{ord(c):04X}" for c in run)
                       + "\\X0\\")
            run.clear()

    for ch in text or "":
        if ord(ch) < 128:
            flush()
            out.append("''" if ch == "'" else ch)
        elif ord(ch) > 0xFFFF:
            flush()
            out.append("\\X4\\" + f"{ord(ch):08X}" + "\\X0\\")
        else:
            run.append(ch)
    flush()
    return "'" + "".join(out) + "'"


def _f(v: float) -> str:
    return f"{v:.6f}"


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._next = 1

    def add(self, entity: str, *attrs) -> int:
        eid = self._next
        self._next += 1
        self.lines.append(f"#{eid}={entity}({','.join(attrs)});")
        return eid


def _brep(w: _Writer, faces, context_id: int) -> int:
    """Faceted geometry for a face set → IfcShapeRepresentation id. Closed
    sets become an IfcFacetedBrep; open ones an IfcShellBasedSurfaceModel."""
    point_ids: dict = {}

    def pt(v) -> int:
        key = (round(v.x(), 6), round(v.y(), 6), round(v.z(), 6))
        pid = point_ids.get(key)
        if pid is None:
            pid = w.add("IFCCARTESIANPOINT",
                        f"({_f(key[0])},{_f(key[1])},{_f(key[2])})")
            point_ids[key] = pid
        return pid

    face_ids = []
    for f in faces:
        bounds = []
        outer = w.add("IFCPOLYLOOP",
                      "(" + ",".join(f"#{pt(v.position)}" for v in f.loop)
                      + ")")
        bounds.append(f"#{w.add('IFCFACEOUTERBOUND', f'#{outer}', '.T.')}")
        for h in f.hole_loops:
            loop = w.add("IFCPOLYLOOP",
                         "(" + ",".join(f"#{pt(v.position)}" for v in h) + ")")
            bounds.append(f"#{w.add('IFCFACEBOUND', f'#{loop}', '.T.')}")
        face_ids.append(w.add("IFCFACE", "(" + ",".join(bounds) + ")"))

    face_list = "(" + ",".join(f"#{i}" for i in face_ids) + ")"
    closed = face_set_volume(faces) is not None
    if closed:
        shell = w.add("IFCCLOSEDSHELL", face_list)
        item = w.add("IFCFACETEDBREP", f"#{shell}")
        rep_type = "'Brep'"
    else:
        shell = w.add("IFCOPENSHELL", face_list)
        item = w.add("IFCSHELLBASEDSURFACEMODEL", f"(#{shell})")
        rep_type = "'SurfaceModel'"
    return w.add("IFCSHAPEREPRESENTATION", f"#{context_id}", "'Body'",
                 rep_type, f"(#{item})")



def _properties(w, owner, guid, owner_guid, values):
    sets = {}
    for pset, name, kind, value in values:
        encoded = (".T." if value else ".F.") if kind == "IfcBoolean" else (
            _s(value) if kind == "IfcLabel" else format(value, ".15E"))
        prop = w.add("IFCPROPERTYSINGLEVALUE", _s(name), "$",
                     f"{kind.upper()}({encoded})", "$")
        sets.setdefault(pset, []).append(prop)
    for name, props in sets.items():
        pid = w.add("IFCPROPERTYSET", _s(guid("pset", owner_guid, name)), "$",
                    _s(name), "$", "(" + ",".join(f"#{p}" for p in props) + ")")
        w.add("IFCRELDEFINESBYPROPERTIES", _s(guid("pset-relation", owner_guid, name)),
              "$", "$", "$", f"(#{owner})", f"#{pid}")


def save_ifc(scene, path, project_name: str = "IngeTrazo project", *,
             schema: str = "IFC4", delivery_profile: str | None = None) -> int:
    """Write tagged objects as IFC4 (default) or IFC4X3_ADD2.

    Returns the exported element count. Unsupported schemas and an empty
    tagged model raise ValueError before the output file is written.
    The supported classes use the same attribute layout in both schemas.
    """
    if schema not in SUPPORTED_SCHEMAS:
        raise ValueError(f"Unsupported IFC schema: {schema!r}")
    objects = collect_objects(scene)
    if not objects:
        raise ValueError("No tagged BIM objects to export")

    from core.turkiye_delivery import PROFILE, check_scene, metadata, object_issues
    if delivery_profile not in (None, PROFILE):
        raise ValueError(f"Unsupported delivery profile: {delivery_profile!r}")
    if delivery_profile is not None:
        if schema != "IFC4X3_ADD2":
            raise ValueError("Türkiye delivery profile requires IFC4X3_ADD2")
        report = check_scene(scene, objects)
        if report["issues"]:
            raise ValueError("\n".join(
                f"{i['object']}: {i['field']} — {i['message']}" for i in report["issues"][:12])
                + f"\n({len(report['issues'])} issues; see Türkiye delivery information)")
    project_data = scene.ifc_project
    if any(not isinstance(v, str) for v in project_data.values()):
        raise ValueError("Project information must contain text values")
    for obj in objects:
        issues = object_issues(obj, schema, required=False)
        if issues:
            raise ValueError(str(issues))

    def guid(*parts):
        return stable_guid(scene.ifc_namespace, *parts)

    # Reject identity collisions rather than publish an ambiguous IFC file.
    identities = [object_identity(obj) for obj in objects]
    element_guids = [guid("element", *key) for key in identities]
    if len(set(element_guids)) != len(element_guids):
        raise ValueError("Duplicate BIM object identity; copy or retag the objects")

    w = _Writer()
    origin = w.add("IFCCARTESIANPOINT", "(0.,0.,0.)")
    axis = w.add("IFCAXIS2PLACEMENT3D", f"#{origin}", "$", "$")
    context = w.add("IFCGEOMETRICREPRESENTATIONCONTEXT",
                    "$", "'Model'", "3", "1.E-5", f"#{axis}", "$")
    units = [
        w.add("IFCSIUNIT", "*", ".LENGTHUNIT.", "$", ".METRE."),
        w.add("IFCSIUNIT", "*", ".AREAUNIT.", "$", ".SQUARE_METRE."),
        w.add("IFCSIUNIT", "*", ".VOLUMEUNIT.", "$", ".CUBIC_METRE."),
    ]
    unit_assign = w.add("IFCUNITASSIGNMENT",
                        "(" + ",".join(f"#{u}" for u in units) + ")")
    if project_name == "IngeTrazo project":
        project_name = project_data.get("name") or project_name
    project = w.add("IFCPROJECT", _s(guid("project")), "$", _s(project_name),
                    _s(project_data["description"]) if project_data.get("description") else "$",
                    "$", "$", "$", f"(#{context})", f"#{unit_assign}")
    if project_data.get("project_type"):
        _properties(w, project, guid, guid("project"), [
            ("Pset_ProjectCommon", "ProjectType", "IfcLabel", project_data["project_type"])])
    placement = w.add("IFCLOCALPLACEMENT", "$", f"#{axis}")
    site = w.add("IFCSITE", _s(guid("site")), "$", "'Site'", "$", "$",
                 f"#{placement}", "$", "$", ".ELEMENT.",
                 "$", "$", "$", "$", "$")
    building = w.add("IFCBUILDING", _s(guid("building")), "$", "'Building'", "$",
                     "$", f"#{placement}", "$", "$", ".ELEMENT.",
                     "$", "$", "$")
    storey = w.add("IFCBUILDINGSTOREY", _s(guid("storey")), "$", "'Storey'", "$",
                   "$", f"#{placement}", "$", "$", ".ELEMENT.", "0.")
    w.add("IFCRELAGGREGATES", _s(guid("project-site")), "$", "$", "$",
          f"#{project}", f"(#{site})")
    w.add("IFCRELAGGREGATES", _s(guid("site-building")), "$", "$", "$",
          f"#{site}", f"(#{building})")
    w.add("IFCRELAGGREGATES", _s(guid("building-storey")), "$", "$", "$",
          f"#{building}", f"(#{storey})")

    element_ids = []
    space_ids = []
    for obj, element_guid in zip(objects, element_guids):
        faces = obj.get("faces") or list(obj["group"].mesh.faces)
        if not faces:
            continue
        rep = _brep(w, faces, context)
        pds = w.add("IFCPRODUCTDEFINITIONSHAPE", "$", "$", f"(#{rep})")
        from core.bim import IFC_CLASSES
        cls = obj["class"] if obj["class"] in IFC_CLASSES \
            else "IfcBuildingElementProxy"
        qset_name, qentries, _metrado = class_quantities(obj["class"], faces)
        total = _ATTR_COUNT.get(cls, _DEFAULT_ATTRS)
        attrs = [_s(element_guid), "$", _s(obj["name"] or cls), "$", "$",
                 f"#{placement}", f"#{pds}", "'IngeTrazo'"]
        if cls in ("IfcDoor", "IfcWindow"):
            # Attributes 9/10 are OverallHeight/OverallWidth — viewers and
            # schedules read the leaf dimensions from here.
            dims = {name: val for kind, name, val in qentries
                    if kind == "length"}
            attrs.append(_f(dims["Height"]) if "Height" in dims else "$")
            attrs.append(_f(dims["Width"]) if "Width" in dims else "$")
        if cls == "IfcReinforcingBar":
            # Tag, SteelGrade, then NominalDiameter, CrossSectionArea and
            # BarLength: what a bar schedule reads (#495).
            dims = {name: val for kind, name, val in qentries
                    if kind == "length"}
            d = dims.get("NominalDiameter")
            attrs += ["$",
                      _f(d) if d is not None else "$",
                      _f(math.pi * d * d / 4.0) if d is not None else "$",
                      _f(dims["Length"]) if "Length" in dims else "$",
                      ".NOTDEFINED."]
        attrs += ["$"] * (total - len(attrs))
        data = metadata(obj)
        if data.get("object_type"):
            attrs[4] = _s(data["object_type"])
        if data.get("tag") and cls != "IfcSpace":
            attrs[7] = _s(data["tag"])
        if data.get("predefined_type"):
            index = 10 if cls in ("IfcDoor", "IfcWindow") else 9 if cls == "IfcSpace" else 8
            attrs[index] = f".{data['predefined_type']}."
        elem = w.add(cls.upper(), *attrs)
        from core.turkiye_delivery import property_values
        _properties(w, elem, guid, element_guid, property_values(cls, data))
        if data.get("material"):
            material = w.add("IFCMATERIAL", _s(data["material"]), "$", "$")
            if data.get("layer"):
                layer = data["layer"]
                mid = w.add("IFCMATERIALLAYER", f"#{material}",
                            format(layer["thickness"], ".15E"), "$", "$", "$", "$", "$")
                mid = w.add("IFCMATERIALLAYERSET", f"(#{mid})", "$", "$")
                material = w.add("IFCMATERIALLAYERSETUSAGE", f"#{mid}",
                                 f".{layer['axis']}.", f".{layer['sense']}.",
                                 format(layer["offset"], ".15E"), "$")
            w.add("IFCRELASSOCIATESMATERIAL", _s(guid("material", element_guid)),
                  "$", "$", "$", f"(#{elem})", f"#{material}")
        (space_ids if cls == "IfcSpace" else element_ids).append(elem)

        # Per-class BaseQuantities (Qto_* naming): the takeoff numbers in
        # the budget's own measures, straight in the file.
        _Q_ENTITY = {"area": "IFCQUANTITYAREA", "volume": "IFCQUANTITYVOLUME",
                     "length": "IFCQUANTITYLENGTH",
                     "weight": "IFCQUANTITYWEIGHT"}
        quantities = [
            f"#{w.add(_Q_ENTITY[kind], _s(name), '$', '$', _f(val), '$')}"
            for kind, name, val in qentries
        ]
        if quantities:
            eq = w.add("IFCELEMENTQUANTITY", _s(guid("quantities", element_guid)), "$",
                       _s(qset_name), "$", "$",
                       "(" + ",".join(quantities) + ")")
            w.add("IFCRELDEFINESBYPROPERTIES",
                  _s(guid("quantity-relation", element_guid)), "$", "$", "$",
                  f"(#{elem})", f"#{eq}")

    if not element_ids and not space_ids:
        raise ValueError("No tagged BIM objects to export")
    if element_ids:
        w.add("IFCRELCONTAINEDINSPATIALSTRUCTURE",
              _s(guid("storey-containment")), "$", "$", "$",
              "(" + ",".join(f"#{e}" for e in element_ids) + ")", f"#{storey}")
    if space_ids:
        # Spaces are spatial structure: decompose the storey, never put
        # them in RelatedElements (IfcRelContainedInSpatialStructure.WR31).
        w.add("IFCRELAGGREGATES", _s(guid("storey-spaces")), "$", "$", "$",
              f"#{storey}", "(" + ",".join(f"#{e}" for e in space_ids) + ")")

    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    name = _s(Path(path).name)
    header = (
        "ISO-10303-21;\n"
        "HEADER;\n"
        "FILE_DESCRIPTION((''),'2;1');\n"
        f"FILE_NAME({name},'{stamp}',('IngeTrazo'),('IngeTrazo'),"
        "'IngeTrazo','IngeTrazo','');\n"
        f"FILE_SCHEMA(('{schema}'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    Path(path).write_text(header + "\n".join(w.lines) + "\n" + footer,
                          encoding="ascii")
    return len(element_ids) + len(space_ids)
