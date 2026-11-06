# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Explicit field editing must preserve identity, units and missing values."""
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.bim import collect_objects, tag_faces, tag_group
from core.group import Group, copy_group
from core.history import History
from core.scene import Scene
from core.turkiye_delivery import (PROFILE, SetDeliveryInformationCommand,
    check_scene, generated_name, metadata, object_issues, property_values, rules, ui)
from formats import igz
from formats.ifc import save_ifc


def example(cls="IfcWall", grouped=False):
    scene = Scene()
    mesh = Group().mesh if grouped else scene.mesh
    mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 0, 2.6), V(0, 0, 2.6)])
    if grouped:
        group = Group(mesh)
        group.xform = QMatrix4x4()
        tag_group(group, cls, "Original")
        scene.groups.append(group)
    else:
        tag_faces(mesh.faces, cls, "Original", 1)
    return scene


def complete_data(cls):
    spec = rules()["classes"][cls]
    return {"discipline": "MM", "description": "Aks_A", "separator": "annex5",
            "predefined_type": spec["predefined_types"]["IFC4X3_ADD2"][0],
            **({"layer": {"thickness": 0.02, "axis": "AXIS3", "sense": "POSITIVE", "offset": 0.0}}
               if spec.get("layer_required") else {}),
            **({"tag": "A-01"} if spec["tag_required"] else {}),
            **({"material": "Beton_C25"} if spec["material_required"] else {}), "psets": {
                p: {k: False if t == "IfcBoolean" else 0.02 if t == "IfcPositiveLengthMeasure"
                    else "REI60" for k, t in fields.items()}
                for p, fields in spec["psets"].items()}}


def apply(scene, data, history=None):
    obj = collect_objects(scene)[0]
    command = SetDeliveryInformationCommand(scene, {
        "name": "26_0001", "project_type": "Konut", "description": "Örnek proje"}, obj, data)
    (history or History(scene)).execute(command)


@pytest.mark.parametrize("cls", list(rules()["classes"]))
def test_verified_matrix_fields_export_with_real_types(cls, tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.util.element
    import ifcopenshell.validate
    scene = example(cls)
    data = complete_data(cls)
    apply(scene, data)
    report = check_scene(scene)
    assert report["regulatory_compliance"] == "not_assessed"
    assert report["checked_fields_complete"] is True
    path = tmp_path / "delivery.ifc"
    profile = PROFILE
    assert save_ifc(scene, path, schema="IFC4X3_ADD2", delivery_profile=profile) == 1
    model = ifcopenshell.open(str(path))
    element = model.by_type(cls)[0]
    assert element.Name == generated_name(cls, data)
    assert element.PredefinedType == data["predefined_type"]
    if cls != "IfcSpace":
        assert element.Tag == "A-01"
    got = ifcopenshell.util.element.get_psets(element, psets_only=True)
    for pset, name, kind, value in property_values(cls, data):
        assert got[pset][name] == value
        p = next(p for p in model.by_type("IfcPropertySingleValue") if p.Name == name)
        assert p.NominalValue.is_a() == kind
    material = ifcopenshell.util.element.get_material(element)
    if cls == "IfcCovering":
        assert material.is_a("IfcMaterialLayerSetUsage")
        assert material.ForLayerSet.MaterialLayers[0].Material.Name == "Beton_C25"
        assert material.ForLayerSet.MaterialLayers[0].LayerThickness == 0.02
        assert material.LayerSetDirection == "AXIS3"
        assert material.OffsetFromReferenceLine == 0.0
    elif rules()["classes"][cls]["material_required"]:
        assert material.Name == "Beton_C25"
    else:
        assert material is None
    project = model.by_type("IfcProject")[0]
    assert project.Name == "26_0001" and project.Description == "Örnek proje"
    assert ifcopenshell.util.element.get_psets(project)["Pset_ProjectCommon"]["ProjectType"] == "Konut"
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, log, express_rules=True)
    assert log.statements == []


@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("binary", [False, True])
def test_metadata_undo_redo_and_igz_roundtrip(grouped, binary, tmp_path, monkeypatch):
    if binary:
        monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
        monkeypatch.setattr(igz, "_BULK_MIN", 1)
    scene = example(grouped=grouped)
    history = History(scene)
    before_name = collect_objects(scene)[0]["name"]
    data = complete_data("IfcWall")
    apply(scene, data, history)
    assert metadata(collect_objects(scene)[0]) == data
    history.undo()
    assert scene.ifc_project == {}
    assert not metadata(collect_objects(scene)[0])
    assert collect_objects(scene)[0]["name"] == before_name
    history.redo()
    p = tmp_path / "saved.igz"
    igz.save_scene(scene, p)
    loaded = Scene()
    igz.load_into(loaded, p)
    assert loaded.ifc_project == scene.ifc_project
    assert metadata(collect_objects(loaded)[0]) == data


def test_component_face_metadata_uses_original_not_transformed_faces():
    scene = example()
    group = Group(scene.mesh)
    group.xform = QMatrix4x4()
    group.xform.translate(8, 0, 0)
    scene.groups.append(group)
    from core.mesh import Mesh
    scene.mesh = Mesh()
    apply(scene, complete_data("IfcWall"))
    assert group.mesh.faces[0].attrs["ifc"]["delivery"]["material"] == "Beton_C25"


def test_copy_and_retag_keep_metadata_without_aliasing():
    scene = example(grouped=True)
    apply(scene, complete_data("IfcWall"))
    original = scene.groups[0]
    duplicate = copy_group(original, V(6, 0, 0))
    scene.groups.append(duplicate)
    tag_group(duplicate, "IfcWall", "Renamed")
    duplicate.ifc["delivery"]["material"] = "Çelik_S355"
    assert original.ifc["delivery"]["material"] == "Beton_C25"
    scene2 = example()
    apply(scene2, complete_data("IfcWall"))
    tag_faces(scene2.mesh.faces, "IfcWall", "Renamed", 1)
    assert scene2.mesh.faces[0].attrs["ifc"]["delivery"]["material"] == "Beton_C25"


@pytest.mark.parametrize("value", ["false", 0, 1, [], float("nan")])
def test_wrong_boolean_types_are_rejected(value):
    data = complete_data("IfcWall")
    data["psets"]["Pset_WallCommon"]["IsExternal"] = value
    with pytest.raises(ValueError):
        list(property_values("IfcWall", data))


def test_false_is_supplied_and_missing_is_not_fabricated(tmp_path):
    scene = example()
    data = complete_data("IfcWall")
    apply(scene, data)
    assert not check_scene(scene)["issues"]
    data["psets"]["Pset_WallCommon"].pop("IsExternal")
    apply(scene, data)
    assert any(i["field"].endswith("IsExternal") for i in check_scene(scene)["issues"])
    path = tmp_path / "existing.ifc"
    path.write_text("original")
    with pytest.raises(ValueError):
        save_ifc(scene, path, schema="IFC4X3_ADD2", delivery_profile=PROFILE)
    assert path.read_text() == "original"


@pytest.mark.parametrize("description", ["Aks A", "Aks-A", "_A", "A__B", "A'B", ""])
def test_annex_name_rejects_unapproved_tokens(description):
    data = complete_data("IfcWall")
    data["description"] = description
    assert generated_name("IfcWall", data) == ""


def test_source_separator_interpretation_is_explicit():
    data = complete_data("IfcWall")
    assert generated_name("IfcWall", data) == "MM-DVR-Aks_A"
    data.update(separator="article11", description="Aks-A")
    assert generated_name("IfcWall", data) == "MM-DVR-Aks-A"


def test_rebar_is_not_given_an_invented_category():
    scene = example("IfcReinforcingBar")
    assert any(i["field"] == "category" for i in check_scene(scene)["issues"])


def test_profile_requires_ifc43(tmp_path):
    scene = example()
    apply(scene, complete_data("IfcWall"))
    with pytest.raises(ValueError, match="requires IFC4X3_ADD2"):
        save_ifc(scene, tmp_path / "wrong.ifc", delivery_profile=PROFILE)


def test_project_metadata_does_not_leak_when_opening_old_files(tmp_path):
    p = tmp_path / "legacy.igz"
    igz.save_scene(example(), p)
    scene = example()
    apply(scene, complete_data("IfcWall"))
    igz.load_into(scene, p)
    assert scene.ifc_project == {}
    scene.ifc_project = {"name": "old"}
    scene.clear()
    assert scene.ifc_project == {}


def test_profile_rejects_invalid_schema_enum_before_overwriting(tmp_path):
    scene = example()
    data = complete_data("IfcWall")
    data["predefined_type"] = "ROOF'INJECTION"
    apply(scene, data)
    path = tmp_path / "existing.ifc"
    path.write_text("original")
    with pytest.raises(ValueError):
        save_ifc(scene, path, schema="IFC4X3_ADD2")
    assert path.read_text() == "original"


def test_property_updates_keep_global_ids(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    scene = example()
    data = complete_data("IfcWall")
    apply(scene, data)
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    save_ifc(scene, a, schema="IFC4X3_ADD2")
    data["psets"]["Pset_WallCommon"]["FireRating"] = "REI120"
    apply(scene, data)
    save_ifc(scene, b, schema="IFC4X3_ADD2")
    def ids(path):
        return {e.GlobalId for e in ifcopenshell.open(str(path)).by_type("IfcRoot")}
    assert ids(a) == ids(b)


def test_unicode_filename_text_and_small_length_remain_readable(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.util.element
    scene = example("IfcSpace")
    data = complete_data("IfcSpace")
    data["psets"]["Pset_SpaceCoveringRequirements"]["FloorCovering"] = "Kaplama 😀"
    data["psets"]["Pset_SpaceCoveringRequirements"]["FloorCoveringThickness"] = 1e-8
    apply(scene, data)
    path = tmp_path / "Örnek-Çığ.ifc"
    save_ifc(scene, path, schema="IFC4X3_ADD2", delivery_profile=PROFILE)
    model = ifcopenshell.open(str(path))
    assert model.header.file_name.name == path.name
    props = ifcopenshell.util.element.get_psets(model.by_type("IfcSpace")[0])
    assert props["Pset_SpaceCoveringRequirements"]["FloorCovering"] == "Kaplama 😀"
    assert props["Pset_SpaceCoveringRequirements"]["FloorCoveringThickness"] == 1e-8


def test_shared_metadata_is_readable_in_both_schemas(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.validate
    scene = example()
    apply(scene, complete_data("IfcWall"))
    roots = []
    for schema in ("IFC4", "IFC4X3_ADD2"):
        path = tmp_path / (schema + ".ifc")
        save_ifc(scene, path, schema=schema)
        model = ifcopenshell.open(str(path))
        roots.append({r.GlobalId for r in model.by_type("IfcRoot")})
        log = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(model, log, express_rules=True)
        assert not log.statements
    assert roots[0] == roots[1]


@pytest.mark.parametrize("key,value", [
    ("thickness", -0.1), ("thickness", float("nan")), ("offset", float("inf")),
    ("axis", "AXIS4"), ("sense", "POSITIVE'INJECTION")])
def test_invalid_material_layer_does_not_overwrite_output(key, value, tmp_path):
    scene = example("IfcCovering")
    data = complete_data("IfcCovering")
    data["layer"][key] = value
    apply(scene, data)
    path = tmp_path / "existing.ifc"
    path.write_text("original")
    with pytest.raises(ValueError):
        save_ifc(scene, path, schema="IFC4X3_ADD2")
    assert path.read_text() == "original"


def test_material_layer_usage_is_readable_in_both_schemas(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.util.element
    import ifcopenshell.validate
    scene = example("IfcCovering")
    data = complete_data("IfcCovering")
    data["layer"].update(axis="AXIS2", sense="NEGATIVE", offset=-0.04)
    apply(scene, data)
    for schema in ("IFC4", "IFC4X3_ADD2"):
        path = tmp_path / f"{schema}.ifc"
        save_ifc(scene, path, schema=schema)
        model = ifcopenshell.open(str(path))
        usage = ifcopenshell.util.element.get_material(model.by_type("IfcCovering")[0])
        assert usage.LayerSetDirection == "AXIS2" and usage.DirectionSense == "NEGATIVE"
        assert usage.OffsetFromReferenceLine == -0.04
        log = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(model, log, express_rules=True)
        assert not log.statements


@pytest.mark.parametrize("language", ["en", "tr"])
def test_dialog_preview_apply_undo_and_cancel(language):
    from core import i18n
    from views.main_window import MainWindow
    from views.turkiye_delivery import DeliveryDialog
    previous = i18n.current_language()
    i18n.set_language(language)
    win = MainWindow()
    dialog = None
    try:
        scene = win.viewport.scene
        scene.clear()
        f = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 0, 1)])
        tag_faces([f], "IfcWall", "Original", 1)
        dialog = DeliveryDialog(win)
        assert dialog.windowTitle() == ui("Türkiye delivery information")
        dialog.project_name.setText("26_0001")
        dialog.project_type.setText("Konut")
        dialog.object_box.setCurrentIndex(1)
        dialog.fields["discipline"].setCurrentIndex(dialog.fields["discipline"].findData("MM"))
        dialog.fields["description"].setText("Aks_A")
        assert dialog.preview.text() == "MM-DVR-Aks_A"
        dialog.fields["predefined_type"].setCurrentIndex(1)
        dialog.fields["tag"].setText("D01")
        dialog.fields["material"].setText("Beton_C25")
        dialog.property_fields[("Pset_WallCommon", "IsExternal")][0].setCurrentIndex(2)
        dialog.property_fields[("Pset_WallCommon", "FireRating")][0].setText("REI60")
        dialog.apply_data()
        assert not check_scene(scene)["issues"]
        assert f.attrs["ifc"]["delivery"]["psets"]["Pset_WallCommon"]["IsExternal"] is False
        win.viewport.history.undo()
        assert f.attrs["ifc"]["name"] == "Original"
        assert scene.ifc_project == {}
        dialog.reject()
        assert scene.ifc_project == {}
    finally:
        if dialog:
            dialog.close()
        win._saved_version = win.viewport.scene.version
        win.close()
        i18n.set_language(previous)


@pytest.mark.parametrize("complete", [False, True])
def test_profile_save_dialog_enforces_fields(tmp_path, monkeypatch, complete):
    from views import main_window as mw
    win = mw.MainWindow()
    try:
        win.viewport.scene.clear()
        scene = win.viewport.scene
        face = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
        tag_faces([face], "IfcWall", "Original", 1)
        if complete:
            apply(scene, complete_data("IfcWall"))
        path = tmp_path / "from-dialog.ifc"
        path.write_text("existing file")
        errors = []
        monkeypatch.setattr(mw.QMessageBox, "critical", lambda *args: errors.append(args))
        monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
            lambda _p, _c, _n, filters: (str(path), filters.split(";;")[2]))
        win._on_export_ifc()
        if complete:
            assert not errors
            assert "FILE_SCHEMA(('IFC4X3_ADD2'));" in path.read_text()
        else:
            assert errors
            assert path.read_text() == "existing file"
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
