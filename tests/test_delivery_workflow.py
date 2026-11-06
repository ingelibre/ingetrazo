# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Real IFC readers verify project information and spatial assignment."""
import copy
import datetime as dt
from pathlib import Path
import time

import pytest
from PySide6.QtGui import QMatrix4x4

from core.bim import collect_objects, tag_group
from core.delivery_workflow import (specification, new_node, filename, object_key,
                                    project_issues, geometry_checks, model_fingerprint)
from core.group import Group
from core.history import History
from core.turkiye_delivery import SetDeliveryInformationCommand, PROFILE, check_scene
from formats import ifc, igz
from tests.test_ifc43_export import _box_scene
from tests.test_turkiye_delivery import complete_data


def full_scene():
    scene = _box_scene("IfcSpace")
    site, building, floor = new_node("site"), new_node("building"), new_node("storey")
    for node, kind, name in [(site, "site", "MM-SAH-Parsel"),
                             (building, "building", "MM-BNA-A"), (floor, "storey", "MM-BNK-Zemin")]:
        node["name"] = name
        node.update(long_name="Software test fixture", ref_elevation=100.0)
        for pset, fields in specification()["spatial"][kind]["psets"].items():
            node["psets"][pset] = {key: False if typ == "IfcBoolean" else ["Test address"]
                if typ == "IfcLabelList" else "Fixture" if typ in ("IfcLabel", "IfcIdentifier")
                else 1.0 for key, typ in fields.items()}
    floor.update(elevation=0.0, code="K00", building_id=building["id"])
    p = {"name": "260001", "project_type": "Konut", "description": "Fictitious test data",
         "delivery_version": 2, "created_at": int(time.time()),
         "authority_reference": "Fictitious authority instruction for software testing",
         "application": {"year": 2026, "province": "Test", "district": "Test", "neighborhood": "Test",
                         "block": "1", "parcel": "1", "status": "Test application"},
         "applicability": {"use": "Test residential", "authority_reference": "Test scope evaluation",
                           "decision": "Voluntary software test; no permit submission", "area": 1.,
                           "province_population": 1000000, "municipality_population": 100000,
                           "storeys_above_ground": 1, "detached": False,
                           "agricultural_exempt": False, "preexisting_application": False},
         "author": {"person_id": "TEST-REGISTRATION", "given_name": "Test", "family_name": "Author",
                    "organization_id": "0000000000", "organization": "Test organisation",
                    "address": "Test street", "town": "Test city", "region": "Test district",
                    "country": "TR", "role": "ARCHITECT", "organization_role": "CONSULTANT"},
         "crs": {"name": "EPSG:5253", "geodetic_datum": "ITRF96", "vertical_datum": "TUDKA99",
                 "projection": "Transverse Mercator", "zone": "27", "eastings": 500000.,
                 "northings": 4500000., "height": 100., "x_abscissa": 1., "x_ordinate": 0.,
                 "scale": 1., "precision": 1e-5},
         "spatial": {"site": site, "buildings": [building], "storeys": [floor]},
         "filename": {"building": "00", "discipline": "MM", "subdiscipline": "XXXX",
                      "kind": "MD", "type": "XXX", "location": "NNN", "sequence": "01",
                      "revision": "000", "max_size_mb": 100.},
         "review": {"reviewer": "Test reviewer", "date": dt.date.today().isoformat(),
                    "answers": {r["key"]: {"answer": "yes", "evidence": "Software test fixture"}
                                for r in specification()["quality"]["MM"]}}}
    data = complete_data("IfcSpace")
    data.update(storey_id=floor["id"], room_number="K00_KNT_001")
    History(scene).execute(SetDeliveryInformationCommand(scene, p, collect_objects(scene)[0], data))
    return scene


def test_full_project_exports_real_participants_crs_and_storeys(tmp_path):
    ios = pytest.importorskip("ifcopenshell")
    import ifcopenshell.validate
    import ifcopenshell.util.element
    import ifcopenshell.util.geolocation
    scene = full_scene()
    assert project_issues(scene, collect_objects(scene)) == []
    path = tmp_path / filename(scene.ifc_project)
    assert ifc.save_ifc(scene, path, schema="IFC4X3_ADD2", delivery_profile=PROFILE) == 1
    model = ios.open(str(path))
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, log, express_rules=True)
    assert not log.statements
    assert model.by_type("IfcPerson")[0].GivenName == "Test"
    assert model.by_type("IfcProject")[0].OwnerHistory.OwningUser.TheOrganization.Name == "Test organisation"
    assert model.by_type("IfcProjectedCRS")[0].Name == "EPSG:5253"
    conversion = model.by_type("IfcMapConversion")[0]
    assert (conversion.Eastings, conversion.Northings, conversion.OrthogonalHeight) == (500000, 4500000, 100)
    assert ifcopenshell.util.geolocation.auto_xyz2enh(model, 1, 2, 3) == pytest.approx((500001, 4500002, 103))
    space = model.by_type("IfcSpace")[0]
    assert space.Decomposes[0].RelatingObject == model.by_type("IfcBuildingStorey")[0]
    assert space.LongName == "K00_KNT_001"
    assert all(root.OwnerHistory is not None for root in model.by_type("IfcRoot"))


def test_assignments_roundtrip_and_fingerprint_ignore_review(tmp_path):
    scene = full_scene()
    before = model_fingerprint(scene)
    scene.ifc_project["review"]["reviewer"] = "Changed reviewer"
    assert model_fingerprint(scene) == before
    p = tmp_path / "saved.igz"
    igz.save_scene(scene, p)
    loaded = _box_scene()
    igz.load_into(loaded, p)
    assert model_fingerprint(loaded) == before
    loaded.ifc_project["spatial"]["storeys"][0]["elevation"] = 3.
    assert model_fingerprint(loaded) != before


def test_nine_field_filename_and_rejection():
    p = full_scene().ifc_project
    assert filename(p) == "260001_00_MM_XXXX_MD_XXX_NNN_01_000.ifc"
    with pytest.raises(ValueError):
        filename(p, overrides={"subdiscipline": "../x"})


def test_project_errors_are_specific():
    scene = full_scene()
    scene.ifc_project["crs"]["zone"] = "30"
    scene.ifc_project["spatial"]["storeys"][0]["building_id"] = "missing"
    errors = project_issues(scene, collect_objects(scene))
    assert any(e["field"] == "crs.name" for e in errors)
    assert any(e["field"] == "storey.building_id" for e in errors)


def test_quality_rows_are_not_all_pass_without_export_evidence():
    report = check_scene(full_scene())
    assert len(report["checks"]) == 21
    assert not report["release_ready"]
    assert next(r for r in report["checks"] if r["key"] == "schema")["status"] == "pending"
    assert next(r for r in report["checks"] if r["key"] == "pdf_model")["status"] == "pending"


def add_room(scene, *, x=0., z=0., floor=None):
    group = Group(_box_scene("IfcSpace").mesh)
    group.xform = QMatrix4x4(); group.xform.translate(x, 0, z)
    tag_group(group, "IfcSpace", "Room")
    scene.groups.append(group)
    data = complete_data("IfcSpace")
    floor = floor or scene.ifc_project["spatial"]["storeys"][0]
    data.update(storey_id=floor["id"], room_number=floor["code"] + "_KNT_002")
    obj = next(o for o in collect_objects(scene) if o.get("group") is group)
    History(scene).execute(SetDeliveryInformationCommand(scene, scene.ifc_project, obj, data))
    return group


@pytest.mark.parametrize("x,overlap", [(0., True), (2., True), (4., False), (5., False)])
def test_room_intersections_distinguish_touching_from_overlap(x, overlap):
    scene = full_scene()
    add_room(scene, x=x)
    checks = geometry_checks(scene, collect_objects(scene))
    assert bool(checks["space_overlap"]) == overlap
    assert bool(checks["duplicates"]) == (x == 0.)


def test_multiple_storeys_preserve_world_geometry_and_containment(tmp_path):
    ios = pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom
    import ifcopenshell.util.shape
    from formats.delivery_package import validate_ifc
    scene = full_scene()
    floor = copy.deepcopy(scene.ifc_project["spatial"]["storeys"][0])
    floor.update(id=new_node("storey")["id"], name="MM-BNK-Bir", code="K01", elevation=3.)
    scene.ifc_project["spatial"]["storeys"].append(floor)
    add_room(scene, z=3., floor=floor)
    assert project_issues(scene, collect_objects(scene)) == []
    assert not geometry_checks(scene, collect_objects(scene))["storeys"]
    path = tmp_path / "floors.ifc"
    ifc.save_ifc(scene, path, schema="IFC4X3_ADD2")
    assert validate_ifc(path)["findings"] == []
    model = ios.open(str(path))
    settings = ifcopenshell.geom.settings(); settings.set(settings.USE_WORLD_COORDS, True)
    room = next(o for o in model.by_type("IfcSpace") if o.LongName.startswith("K01"))
    assert room.Decomposes[0].RelatingObject.Elevation == 3.
    verts = ifcopenshell.util.shape.get_vertices(ifcopenshell.geom.create_shape(settings, room).geometry)
    assert min(verts[:, 2]) == pytest.approx(3.)
    assert max(verts[:, 2]) == pytest.approx(5.6)


def test_explicit_survey_point_validates_in_both_schemas(tmp_path):
    ios = pytest.importorskip("ifcopenshell")
    import ifcopenshell.validate
    scene = full_scene()
    scene.ifc_project["survey"] = {"enabled": True, "name": "Test survey", "description": "Fictitious measurement",
                                   "x": 12., "y": 34., "z": 0.5}
    for schema in ("IFC4", "IFC4X3_ADD2"):
        path = tmp_path / (schema + ".ifc")
        ifc.save_ifc(scene, path, schema=schema)
        model = ios.open(str(path))
        annotation, = model.by_type("IfcAnnotation")
        assert annotation.ObjectType == "SURVEY"
        if schema == "IFC4X3_ADD2": assert annotation.PredefinedType == "SURVEY"
        logger = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(model, logger, express_rules=True)
        assert logger.statements == []


def test_multiple_material_layers_are_exported_and_checked_against_geometry(tmp_path):
    ios = pytest.importorskip("ifcopenshell")
    scene = full_scene()
    obj = collect_objects(scene)[0]
    # The test box is 0.25 m wide along Y.
    from core.bim import tag_faces
    tag_faces(scene.mesh.faces, "IfcCovering", "Covering", 2)
    obj = collect_objects(scene)[0]
    data = complete_data("IfcCovering")
    data.update(storey_id=scene.ifc_project["spatial"]["storeys"][0]["id"],
                layers=[{"material": "Test_A", "thickness": 0.1}, {"material": "Test_B", "thickness": 0.15}],
                layer={"axis": "AXIS2", "sense": "POSITIVE", "offset": 0.})
    History(scene).execute(SetDeliveryInformationCommand(scene, scene.ifc_project, obj, data))
    assert not geometry_checks(scene, collect_objects(scene))["materials"]
    path = tmp_path / "layers.ifc"; ifc.save_ifc(scene, path, schema="IFC4X3_ADD2")
    model = ios.open(str(path))
    assert [l.LayerThickness for l in model.by_type("IfcMaterialLayer")] == pytest.approx([0.1, 0.15])
    data["layers"][1]["thickness"] = 0.2
    History(scene).execute(SetDeliveryInformationCommand(scene, scene.ifc_project, collect_objects(scene)[0], data))
    assert geometry_checks(scene, collect_objects(scene))["materials"]
