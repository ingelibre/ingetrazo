# SPDX-License-Identifier: GPL-3.0-or-later
"""Adversarial regressions for the normal-export storey contribution."""

import pytest

from core.group import Group
from core.mesh import Mesh
from formats.ifc import save_ifc
from tests.test_ifc_storeys import _add, _export, _scene


def test_default_storey_keeps_the_original_step_entity_order(tmp_path):
    scene = _scene()
    _add(scene, "IfcWall", "Wall", 0.0)
    model = _export(tmp_path, scene)
    (building,) = model.by_type("IfcBuilding")
    (storey,) = model.by_type("IfcBuildingStorey")
    assert storey.id() == building.id() + 1


def test_an_empty_named_group_does_not_enable_the_named_storey_path(tmp_path):
    scene = _scene()
    _add(scene, "IfcWall", "Wall", 0.0)
    empty = Group(Mesh(), name="Empty")
    empty.ifc = {"class": "IfcWall", "storey": {"name": "No geometry", "elevation": 8}}
    scene.groups.append(empty)
    model = _export(tmp_path, scene)
    (building,) = model.by_type("IfcBuilding")
    (storey,) = model.by_type("IfcBuildingStorey")
    assert storey.Name == "Storey" and storey.id() == building.id() + 1


def test_only_empty_named_groups_do_not_truncate_an_existing_file(tmp_path):
    scene = _scene()
    empty = Group(Mesh(), name="Empty")
    empty.ifc = {"class": "IfcWall", "storey": {"name": "Empty floor"}}
    scene.groups.append(empty)
    path = tmp_path / "existing.ifc"
    path.write_text("existing content")
    with pytest.raises(ValueError, match="No tagged BIM objects"):
        save_ifc(scene, path)
    assert path.read_text() == "existing content"
