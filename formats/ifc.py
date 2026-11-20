# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""IFC4 export — tagged BIM objects to a STEP Physical File, by hand.

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
from core.sun import north_vector_xy, scene_north_deg
from core.version import __version__

#: The model view the file declares in its header (ISO 16739 conformance is
#: per view; see docs/iso16739-plan.md).
VIEW_DEFINITION = "ReferenceView_V1.2"

_GUID_CHARS = ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
               "abcdefghijklmnopqrstuvwxyz_$")

#: IFC4 total attribute counts per element class (the first 8 are the common
#: GlobalId..Tag layout; the rest are padded with ``$``). Classes with quirky
#: layouts (doors/windows carry OverallHeight/Width…, IfcSpace has LongName
#: where others have Tag) just get the right pad width.
_ATTR_COUNT = {"IfcPile": 10, "IfcDoor": 13, "IfcWindow": 13, "IfcSpace": 11,
               "IfcReinforcingBar": 14}
_DEFAULT_ATTRS = 9


def ifc_guid() -> str:
    """A 22-character IFC compressed GUID (base-64 over the IFC alphabet)."""
    n = uuid.uuid4().int
    return "".join(_GUID_CHARS[(n >> (6 * i)) & 63] for i in range(21, -1, -1))


def _s(text: str) -> str:
    """IFC string literal: apostrophes doubled, non-ASCII as \\X2\\…\\X0\\."""
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
        # IfcOwnerHistory every rooted entity points to, once written: some
        # importers require the owning application even though IFC4 makes
        # the attribute optional
        self.owner_history: int | None = None

    def _owned(self, entity: str, attrs) -> tuple:
        if self.owner_history is not None and _is_rooted(entity, attrs):
            return (attrs[0], f"#{self.owner_history}") + tuple(attrs[2:])
        return attrs

    def add(self, entity: str, *attrs) -> int:
        eid = self._next
        self._next += 1
        attrs = self._owned(entity, attrs)
        self.lines.append(f"#{eid}={entity}({','.join(attrs)});")
        return eid


def _header(path, stamp: str) -> str:
    """The ISO 10303-21 HEADER: the declared view and who wrote the file."""
    name = _s(Path(path).name)
    app = _s(f"IngeTrazo {__version__}")
    return (
        "ISO-10303-21;\n"
        "HEADER;\n"
        f"FILE_DESCRIPTION(('ViewDefinition [{VIEW_DEFINITION}]'),'2;1');\n"
        f"FILE_NAME({name},'{stamp}',(''),(''),{app},{app},'');\n"
        "FILE_SCHEMA(('IFC4'));\n"
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


def save_ifc(scene, path, project_name: str = "IngeTrazo project") -> int:
    """Write every tagged BIM object to ``path`` as IFC4. Returns how many
    elements were exported; raises ``ValueError`` when nothing is tagged."""
    objects = collect_objects(scene)
    if not objects:
        raise ValueError("No tagged BIM objects to export")

    stamp = datetime.datetime.now()
    w = _Writer()
    w.owner_history = _write_owner_history(w, stamp)
    origin = w.add("IFCCARTESIANPOINT", "(0.,0.,0.)")
    axis = w.add("IFCAXIS2PLACEMENT3D", f"#{origin}", "$", "$")
    # Tools > North: always written, so 0 degrees is +Y as in the scene.
    nx, ny = north_vector_xy(scene_north_deg(scene))
    true_north = w.add("IFCDIRECTION", f"({nx:.12f},{ny:.12f})")
    context = w.add("IFCGEOMETRICREPRESENTATIONCONTEXT",
                    "$", "'Model'", "3", "1.E-5", f"#{axis}", f"#{true_north}")
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
    project = w.add("IFCPROJECT", _s(ifc_guid()), "$", _s(project_name),
                    "$", "$", "$", "$", f"(#{context})", f"#{unit_assign}")
    placement = w.add("IFCLOCALPLACEMENT", "$", f"#{axis}")
    lat = lon = elev = "$"
    datum = getattr(scene, "georef", None)       # the location, if any
    if datum is not None:
        lat, lon = _compound_angle(datum.lat), _compound_angle(datum.lon)
        elev = f"{float(datum.alt):.3f}"
    site = w.add("IFCSITE", _s(ifc_guid()), "$", "'Site'", "$", "$",
                 f"#{placement}", "$", "$", ".ELEMENT.",
                 lat, lon, elev, "$", "$")
    building = w.add("IFCBUILDING", _s(ifc_guid()), "$", "'Building'", "$",
                     "$", f"#{placement}", "$", "$", ".ELEMENT.",
                     "$", "$", "$")
    storey = w.add("IFCBUILDINGSTOREY", _s(ifc_guid()), "$", "'Storey'", "$",
                   "$", f"#{placement}", "$", "$", ".ELEMENT.", "0.")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{project}", f"(#{site})")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{site}", f"(#{building})")
    w.add("IFCRELAGGREGATES", _s(ifc_guid()), "$", "$", "$",
          f"#{building}", f"(#{storey})")

    element_ids = []
    for obj in objects:
        # World space: a moved group or a component instance lands where it
        # is drawn, not at its definition's origin.
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
        attrs = [_s(ifc_guid()), "$", _s(obj["name"] or cls), "$", "$",
                 f"#{placement}", f"#{pds}", "$"]
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
        elem = w.add(cls.upper(), *attrs)
        element_ids.append(elem)

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
            eq = w.add("IFCELEMENTQUANTITY", _s(ifc_guid()), "$",
                       _s(qset_name), "$", "$",
                       "(" + ",".join(quantities) + ")")
            w.add("IFCRELDEFINESBYPROPERTIES", _s(ifc_guid()), "$", "$", "$",
                  f"(#{elem})", f"#{eq}")

    if not element_ids:
        raise ValueError("No tagged BIM objects to export")
    w.add("IFCRELCONTAINEDINSPATIALSTRUCTURE", _s(ifc_guid()), "$", "$", "$",
          "(" + ",".join(f"#{e}" for e in element_ids) + ")", f"#{storey}")

    stamp = stamp.strftime("%Y-%m-%dT%H:%M:%S")
    footer = "ENDSEC;\nEND-ISO-10303-21;\n"
    Path(path).write_text(_header(path, stamp) + "\n".join(w.lines) + "\n"
                          + footer, encoding="ascii")
    return len(element_ids)
