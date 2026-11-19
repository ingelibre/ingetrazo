# SPDX-License-Identifier: GPL-3.0-or-later
"""Every rooted entity names IngeTrazo as its owning application.

IFC4 makes IfcRoot.OwnerHistory optional, yet an importer used to build
analytical models stops with a null-instance assertion when a file has no
IfcApplication. The export now writes one IfcOwnerHistory and points every
IfcRoot entity at it; nothing else in the file changes.
"""
import datetime
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QVector3D

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.validate

from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from core.version import __version__
from formats import ifc
from formats.ifc import _is_rooted, save_ifc


def _box(x0, y0, x1, y1, z0, z1):
    mesh = Mesh()
    p = [QVector3D(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    for a, b, c, d in [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                       (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]:
        mesh.add_face([p[a], p[b], p[c], p[d]])
    return mesh


def _scene():
    scene = Scene()
    storey = {'name': 'Ground floor', 'elevation': 0.0}
    wall = Group(_box(0, 0, 4, .3, 0, 3), name='Wall')
    wall.ifc = {'class': 'IfcWall', 'name': 'Wall', 'type': 'Facade',
                'storey': storey,
                'axis': {'start': [0, .15, 0], 'end': [4, .15, 0]},
                'material_layers': [{'material': 'Brick', 'thickness': .3}],
                'psets': {'Pset_WallCommon': {'IsExternal': True}},
                'enums': {'PredefinedType': 'USERDEFINED'}}
    door = Group(_box(1, 0, 1.9, .3, 0, 2.1), name='Door')
    door.ifc = {'class': 'IfcDoor', 'name': 'Door', 'type': 'Door 900', 'storey': storey}
    scene.groups += [wall, door]
    return scene


def test_every_rooted_entity_has_the_ingetrazo_owner_history(tmp_path):
    path = tmp_path / 'owner.ifc'
    save_ifc(_scene(), path)
    model = ifcopenshell.open(str(path))
    histories = model.by_type('IfcOwnerHistory')
    assert len(histories) == 1
    application = histories[0].OwningApplication
    assert (application.ApplicationFullName, application.Version) == ('IngeTrazo', __version__)
    assert application.ApplicationDeveloper.Name == 'IngeTrazo'
    assert histories[0].CreationDate > 0
    roots = model.by_type('IfcRoot')
    kinds = {root.is_a() for root in roots}
    assert {'IfcProject', 'IfcSite', 'IfcBuilding', 'IfcBuildingStorey', 'IfcWall',
            'IfcDoor', 'IfcElementQuantity', 'IfcRelAggregates',
            'IfcRelDefinesByProperties', 'IfcRelContainedInSpatialStructure'} <= kinds
    assert [r for r in roots if r.OwnerHistory != histories[0]] == []
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger, express_rules=True)
    assert logger.statements == []
    # The header declares the Reference View (ISO 16739 plan, M0).
    assert 'ViewDefinition [ReferenceView_V1.2]' in path.read_text(encoding='ascii')


def test_the_creation_date_is_the_export_time(tmp_path, monkeypatch):
    class FrozenDate(datetime.datetime):
        @classmethod
        def now(cls):
            return cls(2026, 11, 19, 12, 30)

    monkeypatch.setattr(ifc, 'datetime', SimpleNamespace(datetime=FrozenDate))
    path = tmp_path / 'stamp.ifc'
    save_ifc(_scene(), path)
    model = ifcopenshell.open(str(path))
    assert model.by_type('IfcOwnerHistory')[0].CreationDate == \
        int(FrozenDate(2026, 11, 19, 12, 30).timestamp())
    assert "'2026-11-19T12:30:00'" in path.read_text(encoding='ascii')


@pytest.mark.parametrize('entity, attrs, rooted', [
    ('IFCWALL', ("'0123456789012345678901'", '$'), True),
    ('IFCRELVOIDSELEMENT', ("'0123456789012345678901'", '$'), True),
    ('IFCSLABTYPE', ("'0123456789012345678901'", '$'), True),
    ('IFCOPENINGELEMENT', ("'0123456789012345678901'", '$'), True),
    ('IFCWALL', ("'0123456789012345678901'", '#7'), False),       # already owned
    ('IFCWALL', ("'not a guid'", '$'), False),
    # a property whose name happens to look like a GlobalId is not rooted
    ('IFCPROPERTYSINGLEVALUE', ("'0123456789012345678901'", '$'), False),
    ('IFCCARTESIANPOINT', ('(0.,0.,0.)',), False),
])
def test_only_rooted_entities_take_the_owner_history(entity, attrs, rooted):
    assert _is_rooted(entity, attrs) is rooted
