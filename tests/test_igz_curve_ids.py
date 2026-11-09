# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Legacy text curve labels must reopen as distinct, serializable curves."""
from __future__ import annotations

import json
import zipfile

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D

import core.mesh as mesh_module
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


def _edges(labels, offset=0):
    return [dict(a=[offset + index * 2, 0, 0],
                 b=[offset + index * 2, 1, 0], curve=label,
                 soft=index % 2 == 0, hidden=index % 3 == 0)
            for index, label in enumerate(labels)]


def _document(path, payload, members=None, container=False):
    document = json.dumps(dict(igz_format=3 if members else 2 if container else 1,
                               app_version="0.5.8", scene=payload))
    if members or container:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("document.json", document)
            for name, blob in (members or {}).items():
                archive.writestr(name, blob)
    else:
        path.write_text(document)


def _ids(mesh):
    return [edge.curve for edge in mesh.edges]


def _geometry(mesh):
    return [(edge.v0.position.toTuple(), edge.v1.position.toTuple(),
             edge.soft, edge.hidden) for edge in mesh.edges]


@pytest.mark.parametrize("container", [False, True], ids=["plain", "zip"])
@pytest.mark.parametrize("bulk", [False, True], ids=["small", "bulk"])
@pytest.mark.parametrize("binary_roundtrip", [False, True], ids=["save-json", "save-binary"])
def test_text_curves_reopen_and_roundtrip_without_merging(
        tmp_path, monkeypatch, container, bulk, binary_roundtrip):
    monkeypatch.setattr(mesh_module, "_CURVE_COUNTER", 1)
    monkeypatch.setattr(igz, "_BULK_MIN", 1 if bulk else 100_000)
    labels = ["shared", "shared", "other", 1, "1", "01", None]
    metadata = {"nested": {"edges": [{"curve": "extension-owned"}]}}
    path = tmp_path / "text-curves.igz"
    _document(path, dict(edges=_edges(labels), plugin_data=metadata),
              container=container)
    original = path.read_bytes()

    scene = Scene()
    igz.load_into(scene, path)
    ids = _ids(scene.mesh)
    assert ids[0] == ids[1]
    assert ids[3] == 1                         # Existing integer IDs survive.
    assert ids[6] is None
    assert len(set(ids[:6])) == 5             # "01", "1" and 1 stay distinct.
    assert all(type(cid) is int for cid in ids[:6])
    assert scene.plugin_data == metadata
    assert path.read_bytes() == original
    assert len(scene.mesh.curve_edges(scene.mesh.edges[0])) == 2

    fresh = Mesh.next_curve_id()
    assert fresh not in ids
    scene.mesh.add_edge(QVector3D(30, 0, 0), QVector3D(30, 1, 0)).curve = fresh
    expected_ids = _ids(scene.mesh)
    expected_geometry = _geometry(scene.mesh)
    with monkeypatch.context() as saved:
        saved.setattr(igz, "_LARGE_DOCUMENT", 0 if binary_roundtrip else 10**9)
        saved.setattr(igz, "_BULK_MIN", 1 if binary_roundtrip else 100_000)
        output = tmp_path / "roundtrip.igz"
        igz.save_scene(scene, output)
        assert zipfile.is_zipfile(output) is binary_roundtrip
        reopened = Scene()
        igz.load_into(reopened, output)
    assert _ids(reopened.mesh) == expected_ids
    assert _geometry(reopened.mesh) == expected_geometry
    assert reopened.plugin_data == metadata


def test_text_ids_share_one_document_mapping_and_reserve_later_mesh_ids(
        tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_module, "_CURVE_COUNTER", 1)
    identity = QMatrix4x4().data()
    ext = {"edges": [{"curve": "extension-owned"}]}
    payload = dict(
        edges=_edges(["shared"]),
        protos=[dict(edges=_edges(["shared", 900], 20)),
                dict(edges=_edges(["kept", 1000], 30))],
        groups=[dict(name="classic", edges=_edges(["shared", "child"], 40),
                     ext=ext, component=False,
                     children=[dict(edges=_edges(["shared", 500], 50),
                                    component=False)]),
                dict(proto=0, xform=identity, component=True)],
        kept_components=[dict(proto=1, xform=identity, component=True)],
    )
    path = tmp_path / "nested.igz"
    _document(path, payload)
    scene = Scene()
    igz.load_into(scene, path)
    classic, instance = scene.groups
    child = classic.children[0]
    kept = scene.kept_components[0]
    shared = scene.mesh.edges[0].curve
    assert shared > 1000
    assert _ids(classic.mesh)[0] == _ids(child.mesh)[0] == _ids(instance.mesh)[0] == shared
    assert _ids(child.mesh)[1] == 500
    assert _ids(instance.mesh)[1] == 900
    assert _ids(kept.mesh)[1] == 1000
    assert len({shared, _ids(classic.mesh)[1], _ids(kept.mesh)[0]}) == 3
    assert classic.ext == ext
    assert Mesh.next_curve_id() > max(shared, _ids(classic.mesh)[1], _ids(kept.mesh)[0])


@pytest.mark.parametrize("text_ids", [False, True], ids=["numeric-only", "mixed"])
def test_json_text_ids_do_not_collide_with_binary_curve_ids(
        tmp_path, monkeypatch, text_ids):
    monkeypatch.setattr(mesh_module, "_CURVE_COUNTER", 1)
    mesh = Mesh()
    mesh.add_edge(QVector3D(), QVector3D(1, 0, 0)).curve = 1
    mesh.add_edge(QVector3D(2, 0, 0), QVector3D(3, 0, 0)).curve = 1000
    members = {}
    meta = igz._pack_geometry(mesh, members)
    payload = dict(edges=_edges(["shared"] if text_ids else []),
                   protos=[dict(geom=meta)],
                   groups=[dict(proto=0, xform=QMatrix4x4().data(), component=True)])
    path = tmp_path / "mixed.igz"
    _document(path, payload, members=members)
    calls = []
    original = igz._geometry_arrays

    def geometry_arrays(*args):
        calls.append(None)
        return original(*args)

    monkeypatch.setattr(igz, "_geometry_arrays", geometry_arrays)
    scene = Scene()
    igz.load_into(scene, path)
    assert _ids(scene.groups[0].mesh) == [1, 1000]
    if text_ids:
        assert scene.mesh.edges[0].curve > 1000
    else:
        assert len(calls) == 1               # No second binary scan for normal files.
    assert Mesh.next_curve_id() > 1000
