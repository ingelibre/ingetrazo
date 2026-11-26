# SPDX-License-Identifier: GPL-3.0-or-later
"""One IfcBuildingStorey per storey the tags name (normal export).

A tag may say which storey its object belongs to, ``"storey": {"name",
"elevation", "id"}`` — the same key the extensions already write. The export
used to put everything in one "Storey" at 0 m, so a three-storey building came
out flat. Now each named storey is written once, lowest first, at its
elevation; elements are contained in theirs and spaces decompose theirs.
Without any storey named, the file is exactly what it was.
"""
import datetime
import re
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.util.element as element_util
import ifcopenshell.validate

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import ifc
from formats.ifc import save_ifc

#: One project: GlobalIds are stable within a document's namespace (#1236).
NAMESPACE = "6f1c2b3a-0d4e-4f5a-9b8c-7d6e5f4a3b2c"

GROUND = {"name": "Ground floor", "elevation": 0.0, "id": "L0"}
FIRST = {"name": "First floor", "elevation": 3.2, "id": "L1"}


def _box(x0, y0, x1, y1, z0, z1):
    mesh = Mesh()
    p = [QVector3D(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    for a, b, c, d in [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                       (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]:
        mesh.add_face([p[a], p[b], p[c], p[d]])
    return mesh


def _add(scene, cls, name, z0, storey=None, box=(0, 0, 4, .3)):
    group = Group(_box(*box, z0, z0 + 2.7), name=name)
    group.ifc = {"class": cls, "name": name}
    if storey is not None:
        group.ifc["storey"] = storey
    scene.groups.append(group)
    return group


def _scene():
    scene = Scene()
    scene.ifc_namespace = NAMESPACE
    return scene


def _building(ground=GROUND, first=FIRST):
    """Ground floor (wall + space) and first floor (wall) at 3.2 m."""
    scene = _scene()
    _add(scene, "IfcWall", "W0", 0.0, ground)
    _add(scene, "IfcSpace", "Room", 0.0, ground, box=(10, 0, 13, 2.5))
    _add(scene, "IfcWall", "W1", 3.2, first)
    return scene


def _export(tmp_path, scene, name="storeys.ifc"):
    path = tmp_path / name
    save_ifc(scene, path)
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(str(path), logger, express_rules=True)
    assert logger.statements == []
    return ifcopenshell.open(str(path))


def test_one_storey_per_name_lowest_first_at_its_elevation(tmp_path):
    model = _export(tmp_path, _building())
    storeys = model.by_type("IfcBuildingStorey")
    assert [(s.Name, s.Elevation) for s in storeys] == [
        ("Ground floor", 0.0), ("First floor", pytest.approx(3.2))]
    upper = storeys[1].ObjectPlacement.RelativePlacement.Location.Coordinates
    assert upper[2] == pytest.approx(3.2)
    (building,) = model.by_type("IfcBuilding")
    assert set(element_util.get_decomposition(building)) >= set(storeys)


def test_elements_are_contained_and_spaces_decompose_their_storey(tmp_path):
    model = _export(tmp_path, _building())
    walls = {w.Name: w for w in model.by_type("IfcWall")}
    assert element_util.get_container(walls["W0"]).Name == "Ground floor"
    assert element_util.get_container(walls["W1"]).Name == "First floor"
    (space,) = model.by_type("IfcSpace")
    assert element_util.get_aggregate(space).Name == "Ground floor"
    assert not [r for r in model.by_type("IfcRelContainedInSpatialStructure")
                if space in r.RelatedElements]


def test_geometry_stays_in_world_space(tmp_path):
    import ifcopenshell.geom
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    model = _export(tmp_path, _building())
    upper = next(w for w in model.by_type("IfcWall") if w.Name == "W1")
    verts = ifcopenshell.geom.create_shape(settings, upper).geometry.verts
    assert min(verts[2::3]) == pytest.approx(3.2)


def test_untagged_objects_go_to_the_default_storey(tmp_path):
    scene = _building()
    _add(scene, "IfcColumn", "C1", 0.0, box=(20, 0, 20.3, .3))
    model = _export(tmp_path, scene)
    assert [s.Name for s in model.by_type("IfcBuildingStorey")] == [
        "Ground floor", "Storey", "First floor"]            # by elevation, then name
    column = model.by_type("IfcColumn")[0]
    assert element_util.get_container(column).Name == "Storey"


def test_storey_globalids_are_stable_and_follow_the_id(tmp_path):
    first = _export(tmp_path, _building(), "a.ifc")
    again = _export(tmp_path, _building(), "b.ifc")
    renamed = _export(tmp_path, _building(first={**FIRST, "name": "Level 1"}), "c.ifc")
    ids = [[s.GlobalId for s in m.by_type("IfcBuildingStorey")]
           for m in (first, again, renamed)]
    assert ids[0] == ids[1] == ids[2]
    assert len(set(ids[0])) == 2


def test_one_id_on_two_different_storeys_gives_two_globalids(tmp_path):
    clash = {"name": "Other", "elevation": 6.4, "id": "L1"}
    scene = _building()
    _add(scene, "IfcWall", "W2", 6.4, clash)
    model = _export(tmp_path, scene)
    guids = [s.GlobalId for s in model.by_type("IfcBuildingStorey")]
    assert len(guids) == 3 and len(set(guids)) == 3


@pytest.mark.parametrize("storey", [None, "Ground", {}, {"name": ""}, {"name": "   "},
                                    {"name": 7}, {"elevation": 3.0}])
def test_without_a_valid_storey_name_the_file_is_unchanged(tmp_path, monkeypatch, storey):
    class Frozen(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 23, 12, 0, 0)

    monkeypatch.setattr(ifc, "datetime", SimpleNamespace(datetime=Frozen))
    outputs = []
    scene = _scene()
    group = _add(scene, "IfcWall", "W", 0.0)
    _add(scene, "IfcSpace", "Room", 0.0, box=(10, 0, 13, 2.5))
    for extra in ({}, {"storey": storey}):
        group.ifc.update(extra)                    # the same objects, then a bad storey
        path = tmp_path / f"{len(outputs)}.ifc"
        save_ifc(scene, path)
        outputs.append(re.sub(r"FILE_NAME\('[^']*'", "FILE_NAME(''", path.read_text()))
    assert outputs[0] == outputs[1]
    assert outputs[0].count("IFCBUILDINGSTOREY(") == 1 and "'Storey'" in outputs[0]


@pytest.mark.parametrize("elevation", [float("nan"), float("inf"), True, "3.2", None])
def test_a_bad_elevation_is_zero(tmp_path, elevation):
    scene = _scene()
    _add(scene, "IfcWall", "W", 0.0, {"name": "Odd", "elevation": elevation})
    model = _export(tmp_path, scene)
    (storey,) = model.by_type("IfcBuildingStorey")
    assert (storey.Name, storey.Elevation) == ("Odd", 0.0)
