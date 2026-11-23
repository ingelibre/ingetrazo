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

from core.bim import (IFC_CLASSES, class_quantities, collect_objects,
                      face_set_volume, object_faces)
from core.ifc_identity import compressed_guid, element_guids, stable_guid
from core.ifc_identity import _CHARS as _GUID_CHARS
from core.sun import north_vector_xy, scene_north_deg
from core.version import __version__

#: The model view the file declares in its header (ISO 16739 conformance is
#: per view; see docs/iso16739-plan.md).
VIEW_DEFINITION = "ReferenceView_V1.2"

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


def _is_guid(value) -> bool:
    """A well-formed compressed GlobalId: 22 characters of the IFC
    alphabet, the first one 0-3 (128 bits)."""
    return (isinstance(value, str) and len(value) == 22
            and value[0] in "0123" and all(c in _GUID_CHARS for c in value))


#: IfcRoot subtypes written by name (elements, their types and the
#: relationships are recognised by pattern in :func:`_is_rooted`)
_ROOTED = frozenset((
    "IFCPROJECT", "IFCSITE", "IFCBUILDING", "IFCBUILDINGSTOREY", "IFCSPACE",
    "IFCPROPERTYSET", "IFCELEMENTQUANTITY", "IFCOPENINGELEMENT",
    "IFCVIRTUALELEMENT", "IFCEXTERNALSPATIALELEMENT", "IFCBUILDINGELEMENTPROXY",
    # the delivery profile's project actor and survey annotation (#1236)
    "IFCACTOR", "IFCANNOTATION",
))


def _is_rooted(entity: str, attrs) -> bool:
    """True for an IfcRoot entity whose OwnerHistory (second attribute) is
    left unset: its first attribute is a GlobalId and the entity is a
    spatial element, a building element, a type, a property set or a
    relationship."""
    if len(attrs) < 2 or attrs[1] != "$":
        return False
    first = attrs[0]
    if not (first[:1] == "'" and first[-1:] == "'" and _is_guid(first[1:-1])):
        return False
    from core.bim import IFC_CLASSES
    return (entity in _ROOTED or entity.startswith("IFCREL")
            or entity.endswith("TYPE")
            or entity in {name.upper() for name in IFC_CLASSES})


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._next = 1
        # Reference to the IfcOwnerHistory every rooted entity points to,
        # once written ("$" until then): some importers require the owning
        # application even though IFC4 makes the attribute optional. The
        # plain export writes an anonymous one (_write_owner_history); the
        # full delivery profile writes its own with the project's actor
        # (formats.ifc_delivery.participants), never both.
        self.owner = "$"

    def _owned(self, entity: str, attrs) -> tuple:
        if self.owner != "$" and _is_rooted(entity, attrs):
            return (attrs[0], self.owner) + tuple(attrs[2:])
        return attrs

    def add(self, entity: str, *attrs) -> int:
        eid = self._next
        self._next += 1
        attrs = self._owned(entity, attrs)
        self.lines.append(f"#{eid}={entity}({','.join(attrs)});")
        return eid


def _header(path, stamp: str, schema: str = "IFC4") -> str:
    """The ISO 10303-21 HEADER: the declared view and who wrote the file."""
    name = _s(Path(path).name)
    app = _s(f"IngeTrazo {__version__}")
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(('ViewDefinition [{VIEW_DEFINITION}]'),'2;1');\n"
        f"FILE_NAME({name},'{stamp}',(''),(''),{app},{app},'');\n"
        f"FILE_SCHEMA(('{schema}'));\n"
        "ENDSEC;\n"
        "DATA;\n"
    )


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


def _compound_angle(deg):
    """IfcCompoundPlaneAngleMeasure: (degrees, minutes, seconds, millionths),
    all with the sign of the angle."""
    sign = -1 if deg < 0 else 1
    micro = round(abs(float(deg)) * 3600 * 1_000_000)
    d, rest = divmod(micro, 3600 * 1_000_000)
    m, rest = divmod(rest, 60 * 1_000_000)
    sec, mil = divmod(rest, 1_000_000)
    return "(" + ",".join(str(sign * v) for v in (d, m, sec, mil)) + ")"


def _write_owner_history(w: _Writer, stamp) -> int:
    """IfcOwnerHistory naming IngeTrazo as the owning application.

    IFC4 makes OwnerHistory optional, but importers read the application
    that wrote a file from it; one importer stops with a null-instance
    assertion when no IfcApplication exists. The person is anonymous: the
    file does not record who exported it."""
    from core.version import __version__
    person = w.add("IFCPERSON", "$", "'unknown'", "$", "$", "$", "$", "$", "$")
    organization = w.add("IFCORGANIZATION", "$", "'IngeTrazo'", "$", "$", "$")
    owner = w.add("IFCPERSONANDORGANIZATION", f"#{person}", f"#{organization}", "$")
    application = w.add("IFCAPPLICATION", f"#{organization}", _s(__version__),
                        "'IngeTrazo'", "'IngeTrazo'")
    return w.add("IFCOWNERHISTORY", f"#{owner}", f"#{application}", "$",
                 ".NOTDEFINED.", "$", "$", "$", str(int(stamp.timestamp())))


def _properties(w, owner, guid, owner_guid, values):
    sets = {}
    for pset, name, kind, value in values:
        if kind == "IfcLabelList":
            vals = "(" + ",".join(f"IFCLABEL({_s(v)})" for v in value) + ")"
            prop = w.add("IFCPROPERTYLISTVALUE", _s(name), "$", vals, "$")
        else:
            encoded = (".T." if value else ".F.") if kind == "IfcBoolean" else (
                _s(value) if kind in ("IfcLabel", "IfcIdentifier", "IfcText") else format(value, ".15E"))
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
    full_delivery = project_data.get("delivery_version") == 2
    if full_delivery:
        from core.delivery_workflow import project_issues
        errors = project_issues(scene, objects)
        if errors:
            raise ValueError(str(errors))
    if any(not isinstance(project_data.get(k, ""), str) for k in ("name", "description", "project_type")):
        raise ValueError("Project information must contain text values")
    for obj in objects:
        issues = object_issues(obj, schema, required=False)
        if issues:
            raise ValueError(str(issues))

    def guid(*parts):
        return stable_guid(scene.ifc_namespace, *parts)

    # Reject identity collisions rather than publish an ambiguous IFC file.
    guids = element_guids(scene, objects)

    stamp = datetime.datetime.now()
    w = _Writer()
    participant = None
    if full_delivery:
        from formats.ifc_delivery import participants
        participant = participants(w, project_data, guid)
    else:
        w.owner = f"#{_write_owner_history(w, stamp)}"
    origin = w.add("IFCCARTESIANPOINT", "(0.,0.,0.)")
    axis = w.add("IFCAXIS2PLACEMENT3D", f"#{origin}", "$", "$")
    precision = format(project_data["crs"]["precision"], ".15E") if full_delivery else "1.E-5"
    # Tools > North: always written, so 0 degrees is +Y as in the scene.
    nx, ny = north_vector_xy(scene_north_deg(scene))
    true_north = w.add("IFCDIRECTION", f"({nx:.12f},{ny:.12f})")
    context = w.add("IFCGEOMETRICREPRESENTATIONCONTEXT",
                    "$", "'Model'", "3", precision, f"#{axis}", f"#{true_north}")
    # Shapes hang off the Body sub-context, as the Reference View wants;
    # the starred attributes are derived from the parent context.
    body = w.add("IFCGEOMETRICREPRESENTATIONSUBCONTEXT", "'Body'", "'Model'",
                 "*", "*", "*", "*", f"#{context}", "$", ".MODEL_VIEW.", "$")
    units = [
        w.add("IFCSIUNIT", "*", ".LENGTHUNIT.", "$", ".METRE."),
        w.add("IFCSIUNIT", "*", ".AREAUNIT.", "$", ".SQUARE_METRE."),
        w.add("IFCSIUNIT", "*", ".VOLUMEUNIT.", "$", ".CUBIC_METRE."),
        # The rebar Weight quantity is in kilograms (#495).
        w.add("IFCSIUNIT", "*", ".MASSUNIT.", ".KILO.", ".GRAM."),
        w.add("IFCSIUNIT", "*", ".PLANEANGLEUNIT.", "$", ".RADIAN."),
    ]
    unit_assign = w.add("IFCUNITASSIGNMENT",
                        "(" + ",".join(f"#{u}" for u in units) + ")")
    if project_name == "IngeTrazo project":
        project_name = project_data.get("name") or project_name
    project = w.add("IFCPROJECT", _s(guid("project")), "$", _s(project_name),
                    _s(project_data["description"]) if project_data.get("description") else "$",
                    "$", _s(project_data["long_name"]) if project_data.get("long_name") else "$",
                    _s(project_data["phase"]) if project_data.get("phase") else "$", f"(#{context})", f"#{unit_assign}")
    if project_data.get("project_type"):
        _properties(w, project, guid, guid("project"), [
            ("Pset_ProjectCommon", "ProjectType", "IfcLabel", project_data["project_type"])])
    placement = w.add("IFCLOCALPLACEMENT", "$", f"#{axis}")
    spatial_export = None
    if full_delivery:
        from formats.ifc_delivery import actor_assignment, georeference, SpatialExport
        actor_assignment(w, project, participant, guid)
        georeference(w, context, units[0], project_data)
        spatial_export = SpatialExport(w, project, placement, project_data, guid)
        from formats.ifc_delivery import survey_annotation
        survey_annotation(w, context, placement, spatial_export.site, project_data, guid, schema)
    if not full_delivery:
        lat = lon = elev = "$"
        datum = getattr(scene, "georef", None)       # the location, if any
        if datum is not None:
            lat, lon = _compound_angle(datum.lat), _compound_angle(datum.lon)
            elev = f"{float(datum.alt):.3f}"
        site = w.add("IFCSITE", _s(guid("site")), "$", "'Site'", "$", "$",
                     f"#{placement}", "$", "$", ".ELEMENT.",
                     lat, lon, elev, "$", "$")
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
    for obj, element_guid in zip(objects, guids):
        # World space: a moved group or a component instance lands where it
        # is drawn, not at its definition's origin (#984).
        faces = object_faces(obj)
        if not faces:
            continue
        rep = _brep(w, faces, body)
        pds = w.add("IFCPRODUCTDEFINITIONSHAPE", "$", "$", f"(#{rep})")
        cls = obj["class"] if obj["class"] in IFC_CLASSES \
            else "IfcBuildingElementProxy"
        qset_name, qentries, _metrado = class_quantities(obj["class"], faces)
        total = _ATTR_COUNT.get(cls, _DEFAULT_ATTRS)
        # Slot 8 is the element's own mark (Tag; LongName on IfcSpace):
        # left empty until the user can give one.
        element_placement = spatial_export.placement(obj) if spatial_export else placement
        attrs = [_s(element_guid), "$", _s(obj["name"] or cls), "$", "$",
                 f"#{element_placement}", f"#{pds}", "$"]
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
        if cls == "IfcSpace" and data.get("room_number"):
            attrs[7] = _s(data["room_number"])
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
                layer_ids = []
                for item in data.get("layers") or [{"material": data["material"],
                                                    "thickness": layer["thickness"]}]:
                    mat = w.add("IFCMATERIAL", _s(item["material"]), "$", "$")
                    layer_ids.append(w.add("IFCMATERIALLAYER", f"#{mat}",
                        format(item["thickness"], ".15E"), "$", "$", "$", "$", "$"))
                mid = w.add("IFCMATERIALLAYERSET", "(" + ",".join(f"#{i}" for i in layer_ids) + ")", "$", "$")
                material = w.add("IFCMATERIALLAYERSETUSAGE", f"#{mid}",
                                 f".{layer['axis']}.", f".{layer['sense']}.",
                                 format(layer["offset"], ".15E"), "$")
            w.add("IFCRELASSOCIATESMATERIAL", _s(guid("material", element_guid)),
                  "$", "$", "$", f"(#{elem})", f"#{material}")
        if spatial_export:
            spatial_export.register(obj, elem, element_guid)
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
    if spatial_export:
        spatial_export.finish()
    if element_ids and not spatial_export:
        w.add("IFCRELCONTAINEDINSPATIALSTRUCTURE",
              _s(guid("storey-containment")), "$", "$", "$",
              "(" + ",".join(f"#{e}" for e in element_ids) + ")", f"#{storey}")
    if space_ids and not spatial_export:
        # Spaces are spatial structure: decompose the storey, never put
        # them in RelatedElements (IfcRelContainedInSpatialStructure.WR31).
        w.add("IFCRELAGGREGATES", _s(guid("storey-spaces")), "$", "$", "$",
              f"#{storey}", "(" + ",".join(f"#{e}" for e in space_ids) + ")")

    stamp = stamp.strftime("%Y-%m-%dT%H:%M:%S")
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    Path(path).write_text(_header(path, stamp, schema) + "\n".join(w.lines)
                          + "\n" + footer, encoding="ascii")
    return len(element_ids) + len(space_ids)
