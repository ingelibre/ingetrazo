# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Both schema choices produce readable geometry, quantities and stable IDs."""
import re

import pytest
from PySide6.QtGui import QVector3D as V

from core.bim import IFC_CLASSES, tag_faces
from core.scene import Scene
from formats import igz
from formats.ifc import SUPPORTED_SCHEMAS, save_ifc


def _box_scene(cls="IfcWall"):
    scene = Scene()
    corners = [V(x * 4, y * 0.25, z * 2.6)
               for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    for indices in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                    (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)):
        scene.mesh.add_face([corners[i] for i in indices])
    tag_faces(scene.mesh.faces, cls, "Aks duvarı — Çığ", 1)
    return scene


@pytest.mark.parametrize("schema", SUPPORTED_SCHEMAS)
@pytest.mark.parametrize("cls", IFC_CLASSES)
def test_all_supported_classes_validate_and_tessellate(schema, cls, tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom
    import ifcopenshell.util.shape
    import ifcopenshell.validate
    path = tmp_path / "model.ifc"
    assert save_ifc(_box_scene(cls), path, schema=schema) == 1
    model = ifcopenshell.open(str(path))
    assert model.schema_identifier == schema
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert logger.statements == []
    (element,) = model.by_type(cls)
    assert element.Name == "Aks duvarı — Çığ"
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), element)
    assert ifcopenshell.util.shape.get_volume(shape.geometry) == pytest.approx(2.6)


def test_schema_switch_and_document_roundtrip_keep_global_ids(tmp_path):
    scene = _box_scene()
    version = scene.version
    p = tmp_path / "model.igz"
    igz.save_scene(scene, p)
    reopened = Scene()
    igz.load_into(reopened, p)
    ids = []
    for i, (source, schema) in enumerate((
            (scene, "IFC4"), (scene, "IFC4X3_ADD2"),
            (reopened, "IFC4X3_ADD2"), (reopened, "IFC4"))):
        path = tmp_path / f"revision-{i}.ifc"
        save_ifc(source, path, schema=schema)
        text = path.read_text(encoding="ascii")
        assert f"FILE_SCHEMA(('{schema}'));" in text
        ids.append(re.findall(r"#\d+=IFC\w+\('([0-3][\w$]{21})',", text))
    assert len(ids[0]) == 11
    assert all(row == ids[0] for row in ids)
    assert scene.version == version


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4X3", "IFC4.3", "bad'", None])
def test_unsupported_schema_does_not_overwrite_output(schema, tmp_path):
    path = tmp_path / "existing.ifc"
    path.write_text("preserve existing file")
    with pytest.raises(ValueError, match="Unsupported IFC schema"):
        save_ifc(_box_scene(), path, schema=schema)
    assert path.read_text() == "preserve existing file"


@pytest.mark.parametrize("schema", SUPPORTED_SCHEMAS)
def test_quantities_units_and_open_surface_survive(schema, tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.util.element
    scene = _box_scene()
    face = scene.mesh.add_face([V(6, 0, 0), V(9, 0, 0), V(9, 2, 0), V(6, 2, 0)])
    tag_faces([face], "IfcSlab", "Döşeme", 2)
    path = tmp_path / "quantities.ifc"
    assert save_ifc(scene, path, "Örnek proje", schema=schema) == 2
    model = ifcopenshell.open(str(path))
    wall = model.by_type("IfcWall")[0]
    q = ifcopenshell.util.element.get_psets(wall, qtos_only=True)["Qto_WallBaseQuantities"]
    assert q["GrossVolume"] == pytest.approx(2.6)
    assert q["NetSideArea"] == pytest.approx(10.4)
    assert q["Width"] == pytest.approx(0.25)
    assert model.by_type("IfcProject")[0].Name == "Örnek proje"
    assert {(u.UnitType, u.Name) for u in model.by_type("IfcSIUnit")} == {
        ("LENGTHUNIT", "METRE"), ("AREAUNIT", "SQUARE_METRE"),
        ("VOLUMEUNIT", "CUBIC_METRE")}
    slab = model.by_type("IfcSlab")[0]
    assert slab.Representation.Representations[0].RepresentationType == "SurfaceModel"
    q = ifcopenshell.util.element.get_psets(slab, qtos_only=True)["Qto_SlabBaseQuantities"]
    assert q["GrossArea"] == pytest.approx(6)
    assert "GrossVolume" not in q
    assert ifcopenshell.util.element.get_container(wall).is_a("IfcBuildingStorey")


@pytest.mark.parametrize("schema", SUPPORTED_SCHEMAS)
def test_spaces_decompose_storey_while_elements_are_contained(schema, tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.validate
    scene = _box_scene("IfcSpace")
    face = scene.mesh.add_face([V(6, 0, 0), V(7, 0, 0), V(7, 0, 2), V(6, 0, 2)])
    tag_faces([face], "IfcDoor", "Kapı", 2)
    path = tmp_path / "spatial.ifc"
    assert save_ifc(scene, path, schema=schema) == 2
    model = ifcopenshell.open(str(path))
    (space,) = model.by_type("IfcSpace")
    (storey,) = model.by_type("IfcBuildingStorey")
    assert space.Decomposes[0].RelatingObject == storey
    (relation,) = model.by_type("IfcRelContainedInSpatialStructure")
    assert relation.RelatingStructure == storey
    assert relation.RelatedElements == tuple(model.by_type("IfcDoor"))
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert not logger.statements


@pytest.mark.parametrize("schema", SUPPORTED_SCHEMAS)
def test_unknown_class_still_exports_as_proxy(schema, tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    path = tmp_path / "proxy.ifc"
    save_ifc(_box_scene("IfcUnsupported"), path, schema=schema)
    assert len(ifcopenshell.open(str(path)).by_type("IfcBuildingElementProxy")) == 1


@pytest.mark.parametrize("schema", SUPPORTED_SCHEMAS)
@pytest.mark.parametrize("cls", ["IfcDoor", "IfcWindow"])
def test_opening_dimensions_keep_correct_attribute_positions(schema, cls, tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    scene = Scene()
    face = scene.mesh.add_face([V(0, 0, 0), V(0.9, 0, 0),
                                V(0.9, 0, 2.1), V(0, 0, 2.1)])
    tag_faces([face], cls, "Açıklık", 1)
    path = tmp_path / "opening.ifc"
    save_ifc(scene, path, schema=schema)
    element = ifcopenshell.open(str(path)).by_type(cls)[0]
    assert element.OverallHeight == pytest.approx(2.1)
    assert element.OverallWidth == pytest.approx(0.9)


@pytest.mark.parametrize("choice, schema", [
    (0, "IFC4"), (1, "IFC4X3_ADD2"), (2, "IFC4"), (None, None)])
def test_export_dialog_uses_selected_schema(choice, schema, tmp_path, monkeypatch):
    from views import main_window as mw
    win = mw.MainWindow()
    try:
        scene = win.viewport.scene
        scene.clear()
        face = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0)])
        tag_faces([face], "IfcSlab", "Döşeme", 1)
        path = tmp_path / "selected.ifc"

        def choose(_parent, _caption, _path, filters):
            options = filters.split(";;")
            assert len(options) == 3
            assert options[0].startswith("IFC4 ")
            assert options[1] == "IFC4.3 ADD2 (*.ifc)"
            return ("", "") if choice is None else (str(path), options[choice])

        monkeypatch.setattr(mw.file_dialogs, "getSaveFileName", choose)
        win._on_export_ifc()
        if schema is None:
            assert not path.exists()
        else:
            assert f"FILE_SCHEMA(('{schema}'));" in path.read_text()
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
