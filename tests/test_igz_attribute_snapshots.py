# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Attribute identity is only a hint; mutable contents must be checked."""
from types import SimpleNamespace

import json
from PySide6.QtGui import QVector3D

from core.mesh import Mesh
from formats import igz
from formats.igz_attributes import AttributeTable


_key = json.JSONEncoder(sort_keys=True, separators=(",", ":")).encode


def _table():
    return AttributeTable(igz._face_attrs_json, _key)


def _reference(faces):
    entries, indices, lookup = [], [], {}
    for face in faces:
        js = igz._face_attrs_json(face) if face.attrs else None
        if not js:
            indices.append(-1)
            continue
        key = _key(js)
        if key not in lookup:
            lookup[key] = len(entries)
            entries.append(js)
        indices.append(lookup[key])
    return indices, entries


def test_snapshot_checks_mutation_types_signed_zero_and_retains_old_values():
    color = [0., 1., 2.]
    face = SimpleNamespace(attrs={'color': color, 'mat': 'm', 'back': True})
    table = _table()
    faces, indices = [], []
    for value in [0., -0., 0, False, 1, 1., True, '1']:
        color[0] = value
        faces.append(SimpleNamespace(attrs={**face.attrs, 'color': list(color)}))
        indices.append(table.add(face))
        assert table.add(face) == indices[-1]
    expected, entries = _reference(faces)
    assert indices == expected
    assert _key(table.entries) == _key(entries)
    assert len(set(indices)) == 8
    color.append(9.)
    assert table.add(face) == len(entries)
    color.pop()
    assert table.add(face) == indices[-1]
    face.attrs['layer'] = 'new'
    assert table.add(face) != indices[-1]


def test_nested_custom_and_unknown_recipes_keep_projection_semantics():
    class Float(float):
        pass
    class Color(list):
        pass
    recipes = [None, {}, {'color': Color([0, 1, 2])},
               {'color': [Float(1), 2, 3]}, {'opacity': '0.5'},
               {'texture': {'path': 'é.png', 'uvw': [0., -0., 2.]}},
               {'back': {'color': [0, 1, 2], 'texture': {'path': 'b.png'}}},
               {'ifc': {'x': 'value'}}, {'unserialized': object()},
               {'hidden': True}, {'mat': 1}, {'color': (0, 1, 2)}]
    faces = [SimpleNamespace(attrs=r) for r in recipes] * 2
    table = _table()
    actual = [table.add(f) for f in faces]
    expected, entries = _reference(faces)
    assert actual == expected
    assert _key(table.entries) == _key(entries)


def test_custom_scalar_hooks_are_never_memoized():
    class Name(str):
        calls = 0
        def __bool__(self):
            self.calls += 1
            return True
    name = Name('name')
    table = _table()
    face = SimpleNamespace(attrs={'mat': name})
    table.add(face)
    first = name.calls
    table.add(face)
    assert name.calls > first
    assert not table.recipes


def test_geometry_arrays_and_table_bytes_equal_reference(monkeypatch):
    mesh = Mesh()
    color = [.25, .5, .75]
    for i in range(400):
        face = mesh.add_face([QVector3D(i, 0, 0), QVector3D(i + .7, 0, 0), QVector3D(i, 1, 0)])
        face.attrs.update(color=color, mat='shared', layer='L')
    expected_sink, actual_sink = {}, {}
    with monkeypatch.context() as mp:
        original = AttributeTable.add
        def uncached(self, face):
            self.recipes.clear()
            return original(self, face)
        mp.setattr(AttributeTable, 'add', uncached)
        expected = igz._pack_geometry(mesh, expected_sink)
    actual = igz._pack_geometry(mesh, actual_sink)
    assert actual_sink == expected_sink
    assert _key(actual) == _key(expected)
    color[0] = -0.
    again = igz._pack_geometry(mesh, {})
    assert _key(again) != _key(actual)
