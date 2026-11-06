# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""IFC project participants, map conversion and persistent spatial structure."""
from core.delivery_workflow import spatial_fields


def participants(w, project_data, guid):
    from formats.ifc import _s
    a = project_data["author"]
    def role(value):
        return w.add("IFCACTORROLE", f".{value}.",
                     _s(a["user_role"]) if value == "USERDEFINED" else "$", "$")
    person_role, org_role = role(a["role"]), role(a["organization_role"])
    lines = "(" + ",".join(_s(s) for s in a["address"].splitlines() if s.strip()) + ")"
    address = w.add("IFCPOSTALADDRESS", ".OFFICE.", "$", "$", "$", lines, "$",
                    _s(a["town"]), _s(a["region"]),
                    _s(a["postal_code"]) if a.get("postal_code") else "$", _s(a["country"]))
    organisation = w.add("IFCORGANIZATION", _s(a["organization_id"]), _s(a["organization"]),
                         "$", f"(#{org_role})", f"(#{address})")
    person = w.add("IFCPERSON", _s(a["person_id"]), _s(a["family_name"]),
                   _s(a["given_name"]), "$", "$", "$", f"(#{person_role})", f"(#{address})")
    actor = w.add("IFCPERSONANDORGANIZATION", f"#{person}", f"#{organisation}",
                  f"(#{person_role})")
    app_org = w.add("IFCORGANIZATION", "$", "'IngeTrazo contributors'", "$", "$", "$")
    app = w.add("IFCAPPLICATION", f"#{app_org}", "'0.6'", "'IngeTrazo'", "'IngeTrazo'")
    # This timestamp is recorded when the user applies project information,
    # not regenerated at export. The data remain attributable on every root.
    created = int(project_data["created_at"])
    owner = w.add("IFCOWNERHISTORY", f"#{actor}", f"#{app}", "$", ".ADDED.",
                  str(created), f"#{actor}", f"#{app}", str(created))
    w.owner = f"#{owner}"
    return actor, person_role


def actor_assignment(w, project, participant, guid):
    from formats.ifc import _s
    actor, role = participant
    root = w.add("IFCACTOR", _s(guid("project-actor")), "$", "$", "$", "$", f"#{actor}")
    w.add("IFCRELASSIGNSTOACTOR", _s(guid("project-actor-role")), "$", "$", "$",
          f"(#{project})", "$", f"#{root}", f"#{role}")


def georeference(w, context, length_unit, data):
    from formats.ifc import _s
    c = data["crs"]
    target = w.add("IFCPROJECTEDCRS", _s(c["name"]),
                   _s(c["description"]) if c.get("description") else "$",
                   _s(c["geodetic_datum"]), _s(c["vertical_datum"]),
                   _s(c["projection"]), _s(str(c["zone"])), f"#{length_unit}")
    w.add("IFCMAPCONVERSION", f"#{context}", f"#{target}",
          *(format(c[key], ".15E") for key in
            ("eastings", "northings", "height", "x_abscissa", "x_ordinate", "scale")))


def survey_annotation(w, context, placement, site, data, guid, schema):
    """An explicitly entered survey point; never invent a measured origin."""
    from formats.ifc import _s
    survey = data.get("survey", {})
    if not survey.get("enabled"):
        return
    point = w.add("IFCCARTESIANPOINT", "(" + ",".join(format(survey[k], ".15E") for k in ("x", "y", "z")) + ")")
    geometry = w.add("IFCGEOMETRICSET", f"(#{point})")
    rep = w.add("IFCSHAPEREPRESENTATION", f"#{context}", "'Annotation'", "'GeometricSet'", f"(#{geometry})")
    shape = w.add("IFCPRODUCTDEFINITIONSHAPE", "$", "$", f"(#{rep})")
    attrs = [_s(guid("survey-annotation")), "$", _s(survey["name"]), _s(survey["description"]),
             "'SURVEY'", f"#{placement}", f"#{shape}"]
    if schema == "IFC4X3_ADD2": attrs.append(".SURVEY.")
    annotation = w.add("IFCANNOTATION", *attrs)
    w.add("IFCRELCONTAINEDINSPATIALSTRUCTURE", _s(guid("survey-containment")), "$", "$", "$", f"(#{annotation})", f"#{site}")


class SpatialExport:
    def __init__(self, w, project, placement, data, guid):
        from formats.ifc import _s, _properties
        self.w, self.guid = w, guid
        self.storeys = {}
        self.buildings = {}
        self.spaces = {}
        self.containment = {}
        self.room_groups = {}
        self.identity = {}
        spatial = data["spatial"]
        self.site = self._node("site", spatial["site"], placement)
        self._aggregate("project-site-v2", project, [self.site])
        for b in spatial["buildings"]:
            self.buildings[b["id"]] = self._node("building", b, placement)
        self._aggregate("site-buildings-v2", self.site, list(self.buildings.values()))
        for floor in spatial["storeys"]:
            origin = w.add("IFCCARTESIANPOINT", f"(0.,0.,{format(floor['elevation'], '.15E')})")
            axis = w.add("IFCAXIS2PLACEMENT3D", f"#{origin}", "$", "$")
            level_place = w.add("IFCLOCALPLACEMENT", f"#{placement}", f"#{axis}")
            node = self._node("storey", floor, level_place)
            # Geometry is already in model coordinates. Cancel the level
            # translation in the relative product placement, preserving it.
            point = w.add("IFCCARTESIANPOINT", f"(0.,0.,{format(-floor['elevation'], '.15E')})")
            axis = w.add("IFCAXIS2PLACEMENT3D", f"#{point}", "$", "$")
            product_place = w.add("IFCLOCALPLACEMENT", f"#{level_place}", f"#{axis}")
            self.storeys[floor["id"]] = (node, product_place)
        for b in spatial["buildings"]:
            ids = [self.storeys[f["id"]][0] for f in spatial["storeys"] if f["building_id"] == b["id"]]
            self._aggregate("building-storeys-" + b["id"], self.buildings[b["id"]], ids)

    def _aggregate(self, key, parent, children):
        from formats.ifc import _s
        if children:
            self.w.add("IFCRELAGGREGATES", _s(self.guid(key)), "$", "$", "$",
                       f"#{parent}", "(" + ",".join(f"#{c}" for c in children) + ")")

    def _node(self, kind, record, placement):
        from formats.ifc import _s, _properties
        w, guid = self.w, self.guid
        g = guid("spatial", record["id"])
        attrs = [_s(g), "$", _s(record["name"]), "$",
                 _s(record["object_type"]) if record.get("object_type") else "$",
                 f"#{placement}", "$", _s(record["long_name"]) if record.get("long_name") else "$",
                 ".ELEMENT."]
        if kind == "site":
            entity = "IFCSITE"
            attrs += ["$", "$", format(record["ref_elevation"], ".15E"), "$", "$"]
        elif kind == "building":
            entity = "IFCBUILDING"; attrs += ["$", "$", "$"]
        else:
            entity = "IFCBUILDINGSTOREY"; attrs += [format(record["elevation"], ".15E")]
        node = w.add(entity, *attrs)
        properties, quantities = [], {}
        for pset, key, typ, value in spatial_fields(kind, record):
            if value is None:
                continue
            if pset.startswith("Qto_"):
                quantities.setdefault(pset, []).append((key, typ, value))
            else:
                properties.append((pset, key, typ, value))
        _properties(w, node, guid, g, properties)
        for name, values in quantities.items():
            ids = []
            for key, typ, value in values:
                entity = "IFCQUANTITYAREA" if typ == "IfcAreaMeasure" else "IFCQUANTITYLENGTH"
                ids.append(w.add(entity, _s(key), "$", "$", format(value, ".15E"), "$"))
            q = w.add("IFCELEMENTQUANTITY", _s(guid("spatial-qto", g, name)), "$",
                      _s(name), "$", "$", "(" + ",".join(f"#{v}" for v in ids) + ")")
            w.add("IFCRELDEFINESBYPROPERTIES", _s(guid("spatial-qto-rel", g, name)),
                  "$", "$", "$", f"(#{node})", f"#{q}")
        return node

    def placement(self, obj):
        from core.turkiye_delivery import metadata
        return self.storeys[metadata(obj)["storey_id"]][1]

    def register(self, obj, element, global_id):
        from core.turkiye_delivery import metadata
        data = metadata(obj)
        if obj["class"] == "IfcSpace":
            self.spaces[global_id] = element
            self.room_groups.setdefault(data["storey_id"], []).append(element)
        else:
            key = ("space", data["space_id"]) if data.get("space_id") else ("storey", data["storey_id"])
            self.containment.setdefault(key, []).append(element)

    def finish(self):
        from formats.ifc import _s
        for uid, children in self.room_groups.items():
            self._aggregate("storey-spaces-" + uid, self.storeys[uid][0], children)
        for (kind, uid), children in self.containment.items():
            container = self.spaces[uid] if kind == "space" else self.storeys[uid][0]
            self.w.add("IFCRELCONTAINEDINSPATIALSTRUCTURE",
                       _s(self.guid("containment", kind, uid)), "$", "$", "$",
                       "(" + ",".join(f"#{e}" for e in children) + ")", f"#{container}")
