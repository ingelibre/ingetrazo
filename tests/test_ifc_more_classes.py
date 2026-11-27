# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""The wider IFC class list (#1293): layouts match the schema, and a class
that is still not supported keeps its name on the proxy."""
from __future__ import annotations

import logging

import pytest
from PySide6.QtGui import QVector3D as V

from core.bim import IFC_CLASSES, tag_faces
from core.scene import Scene
from formats.ifc import (_ATTR_COUNT, _DEFAULT_ATTRS, _PREDEFINED_INDEX,
                         SUPPORTED_SCHEMAS, save_ifc)


def _scene(cls):
    scene = Scene()
    face = scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 3), V(0, 0, 3)])
    tag_faces([face], cls, "Element", 1)
    return scene


def test_classes_are_unique_and_include_building_services():
    assert len(IFC_CLASSES) == len(set(IFC_CLASSES))
    for cls in ("IfcPlate", "IfcChimney", "IfcFurniture", "IfcPipeSegment",
                "IfcSolarDevice", "IfcElectricDistributionBoard",
                "IfcGeographicElement", "IfcBuildingElementProxy"):
        assert cls in IFC_CLASSES


@pytest.mark.parametrize("schema", SUPPORTED_SCHEMAS)
def test_attribute_layout_matches_the_schema(schema):
    """Attribute count and PredefinedType slot of every class, checked
    against ifcopenshell's own schema: a wrong pad would shift attributes."""
    ifcopenshell = pytest.importorskip("ifcopenshell")
    wrapper = ifcopenshell.ifcopenshell_wrapper
    declarations = wrapper.schema_by_name(schema)
    for cls in IFC_CLASSES:
        entity = declarations.declaration_by_name(cls)
        assert not entity.is_abstract(), cls
        names = [a.name() for a in entity.all_attributes()]
        assert len(names) == _ATTR_COUNT.get(cls, _DEFAULT_ATTRS), cls
        if "PredefinedType" in names:
            assert names.index("PredefinedType") == _PREDEFINED_INDEX.get(cls, 8), cls


def test_unsupported_class_keeps_its_name_in_object_type(tmp_path, caplog):
    path = tmp_path / "proxy.ifc"
    with caplog.at_level(logging.WARNING, logger="formats.ifc"):
        save_ifc(_scene("IfcVibrationIsolator"), path)
    text = path.read_text()
    assert "IFCBUILDINGELEMENTPROXY(" in text
    assert "'IfcVibrationIsolator'" in text        # ObjectType
    assert "IfcVibrationIsolator is not a supported class" in caplog.text


def test_supported_class_is_written_as_itself(tmp_path):
    path = tmp_path / "pipe.ifc"
    save_ifc(_scene("IfcPipeSegment"), path)
    text = path.read_text()
    assert "IFCPIPESEGMENT(" in text
    assert "IFCBUILDINGELEMENTPROXY(" not in text
