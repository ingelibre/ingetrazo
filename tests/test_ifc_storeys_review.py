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


@pytest.mark.parametrize("elevation", [10**400, -(10**400)], ids=["huge-positive", "huge-negative"])
def test_an_integer_elevation_outside_float_range_falls_back_to_zero(tmp_path, elevation):
    scene = _scene()
    _add(scene, "IfcWall", "Wall", 0.0, {"name": "Ground", "elevation": elevation})
    model = _export(tmp_path, scene)
    assert model.by_type("IfcBuildingStorey")[0].Elevation == 0.0


def test_a_storey_id_and_another_storeys_name_have_distinct_identity_domains(tmp_path):
    def building(name):
        scene = _scene()
        _add(scene, "IfcWall", "By id", 0.0, {"name": name, "elevation": 0, "id": "Level"})
        _add(scene, "IfcWall", "By name", 0.0, {"name": "Level", "elevation": 0})
        return scene

    original = _export(tmp_path, building("A"), "original.ifc")
    renamed = _export(tmp_path, building("Z"), "renamed.ifc")
    before = next(s for s in original.by_type("IfcBuildingStorey") if s.Name == "A")
    after = next(s for s in renamed.by_type("IfcBuildingStorey") if s.Name == "Z")
    assert before.GlobalId == after.GlobalId


def test_named_and_unnamed_spaces_aggregate_without_guid_collisions(tmp_path):
    from ifcopenshell.util.element import get_aggregate

    scene = _scene()
    _add(scene, "IfcSpace", "Default room", 0)
    upper = _add(
        scene,
        "IfcSpace",
        "Upper room",
        3.2,
        {"name": "Upper", "elevation": 3.2, "id": "same-as-group"},
    )
    upper.uid = "same-as-group"
    model = _export(tmp_path, scene)
    rooms = {s.Name: s for s in model.by_type("IfcSpace")}
    assert get_aggregate(rooms["Default room"]).Name == "Storey"
    assert get_aggregate(rooms["Upper room"]).Name == "Upper"
    identifiers = [root.GlobalId for root in model.by_type("IfcRoot")]
    assert len(identifiers) == len(set(identifiers))
