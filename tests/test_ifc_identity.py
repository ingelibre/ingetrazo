# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""GlobalIds survive document edits and round trips; copies stay distinct."""
import json
import re
import shutil
import uuid

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.bim import tag_faces, tag_group, untag_faces
from core.group import Group, copy_group, _independent_copy
from core.insert import import_document_as_component
from core.scene import Scene
from formats import igz
from formats.ifc import ifc_guid, save_ifc


def _scene(kind="faces"):
    scene = Scene()
    mesh = scene.mesh if kind == "faces" else Group().mesh
    face = mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 3), V(0, 0, 3)])
    if kind == "faces":
        tag_faces([face], "IfcWall", "Wall", 1)
    else:
        group = Group(mesh)
        group.xform = QMatrix4x4()
        if kind == "group":
            tag_group(group, "IfcWall", "Wall")
        else:
            tag_faces([face], "IfcWall", "Wall", 1)
        scene.groups.append(group)
    return scene


def _roots(scene, path):
    save_ifc(scene, path)
    # Every IfcRoot written here begins with its compressed GlobalId.
    rows = re.findall(r"#\d+=(IFC\w+)\('([0-3][\w$]{21})',", path.read_text())
    assert rows
    assert len({gid for _cls, gid in rows}) == len(rows)
    return rows


@pytest.mark.parametrize("kind", ["faces", "group", "group-faces"])
def test_repeat_export_and_igz_roundtrip_preserve_all_root_ids(kind, tmp_path):
    scene = _scene(kind)
    version, namespace = scene.version, scene.ifc_namespace
    before = _roots(scene, tmp_path / "one.ifc")
    assert _roots(scene, tmp_path / "other-name.ifc") == before
    assert (scene.version, scene.ifc_namespace) == (version, namespace)
    path = tmp_path / "model.igz"
    igz.save_scene(scene, path)
    reopened = Scene()
    igz.load_into(reopened, path)
    assert reopened.ifc_namespace == namespace
    assert _roots(reopened, tmp_path / "reopened.ifc") == before


@pytest.mark.parametrize("binary", [False, True])
def test_component_copies_stay_distinct_after_roundtrip(binary, monkeypatch, tmp_path):
    if binary:
        monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
        monkeypatch.setattr(igz, "_BULK_MIN", 1)
    scene = _scene("group-faces")
    scene.groups.append(copy_group(scene.groups[0], V(5, 0, 0)))
    before = _roots(scene, tmp_path / "copies.ifc")
    assert len([gid for cls, gid in before if cls == "IFCWALL"]) == 2
    igz.save_scene(scene, tmp_path / "copies.igz")
    reopened = Scene()
    igz.load_into(reopened, tmp_path / "copies.igz")
    assert _roots(reopened, tmp_path / "reopened.ifc") == before


def test_group_edits_make_unique_and_nesting_preserve_identity(tmp_path):
    scene = _scene("group")
    before = _roots(scene, tmp_path / "one.ifc")
    g = _independent_copy(scene.groups[0])
    g.xform.translate(5, 2, 0)
    tag_group(g, "IfcSlab", "Renamed")
    container = Group()
    container.adopt([g])
    scene.groups[:] = [container]
    after = _roots(scene, tmp_path / "changed.ifc")
    assert [gid for _cls, gid in after] == [gid for _cls, gid in before]


def test_face_metadata_edit_preserves_identity_but_new_tag_does_not(tmp_path):
    scene = _scene()
    before = _roots(scene, tmp_path / "one.ifc")
    tag_faces(scene.mesh.faces, "IfcSlab", "Renamed", 1)
    assert [gid for _cls, gid in _roots(scene, tmp_path / "edit.ifc")] == [
        gid for _cls, gid in before]
    untag_faces(scene.mesh.faces)
    tag_faces(scene.mesh.faces, "IfcSlab", "Replacement", 1)
    after = _roots(scene, tmp_path / "new.ifc")
    assert next(gid for cls, gid in after if cls == "IFCSLAB") != next(
        gid for cls, gid in before if cls == "IFCWALL")


def test_new_documents_do_not_share_global_ids(tmp_path):
    first = {gid for _cls, gid in _roots(_scene(), tmp_path / "one.ifc")}
    second = {gid for _cls, gid in _roots(_scene(), tmp_path / "two.ifc")}
    assert first.isdisjoint(second)


def test_unrelated_addition_and_group_reordering_preserve_existing_ids(tmp_path):
    scene = _scene("group")
    before = next(gid for cls, gid in _roots(scene, tmp_path / "one.ifc")
                  if cls == "IFCWALL")
    other = copy_group(scene.groups[0], V(5, 0, 0))
    tag_group(other, "IfcColumn", "Column")
    scene.groups.insert(0, other)
    after = _roots(scene, tmp_path / "added.ifc")
    assert next(gid for cls, gid in after if cls == "IFCWALL") == before


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
def test_panel_retags_whole_object_but_splits_partial_selection(partial, legacy, tmp_path):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        scene = win.viewport.scene
        scene.clear()
        first = scene.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
        second = scene.mesh.add_face([V(2, 0, 0), V(3, 0, 0), V(3, 1, 0), V(2, 1, 0)])
        tag_faces([first, second], "IfcWall", "Old", 1)
        if legacy:
            for f in (first, second):
                f.attrs["ifc"].pop("uid")
        before = next(gid for cls, gid in _roots(scene, tmp_path / "before.ifc")
                      if cls == "IFCWALL")
        scene.selection = {first} if partial else {first, second}
        panel = win.bim_tray.bim
        panel.class_box.setCurrentText("IfcSlab")
        panel.name_edit.setText("Renamed")
        panel._on_tag()
        after = _roots(scene, tmp_path / "after.ifc")
        slab = next(gid for cls, gid in after if cls == "IFCSLAB")
        if partial:
            assert slab != before
            assert next(gid for cls, gid in after if cls == "IFCWALL") == before
        else:
            assert slab == before
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_new_document_resets_namespace_even_when_empty():
    scene = Scene()
    previous = scene.ifc_namespace
    scene.clear()
    assert scene.ifc_namespace != previous


@pytest.mark.parametrize("namespace", [None, "broken"])
def test_legacy_file_reopens_and_migrates_deterministically(namespace, tmp_path):
    scene = _scene("group")
    p = tmp_path / "modern.igz"
    igz.save_scene(scene, p)
    data = json.loads(p.read_text(encoding="utf-8"))
    payload = data["scene"]
    payload.pop("ifc_namespace", None)
    payload["groups"][0].pop("uid", None)
    if namespace is not None:
        payload["ifc_namespace"] = namespace
    old = tmp_path / "old.igz"
    old.write_text(json.dumps(data), encoding="utf-8")
    moved = tmp_path / "renamed.igz"
    shutil.copyfile(old, moved)
    a, b = Scene(), Scene()
    igz.load_into(a, old)
    igz.load_into(b, moved)
    before = _roots(a, tmp_path / "a.ifc")
    assert _roots(b, tmp_path / "b.ifc") == before
    igz.save_scene(a, p)
    igz.load_into(b, p)
    assert _roots(b, tmp_path / "migrated.ifc") == before


def test_inserting_same_document_twice_allocates_new_placement_ids(tmp_path):
    source = _scene("group")
    path = tmp_path / "source.igz"
    igz.save_scene(source, path)
    dest = Scene()
    for _ in range(2):
        loaded = Scene()
        igz.load_into(loaded, path)
        dest.groups.append(import_document_as_component(dest, loaded, "Imported"))
    rows = _roots(dest, tmp_path / "inserted.ifc")
    assert len([gid for cls, gid in rows if cls == "IFCWALL"]) == 2


def test_duplicate_identity_fails_without_overwriting_file(tmp_path):
    scene = _scene("group")
    duplicate = copy_group(scene.groups[0], V(5, 0, 0))
    duplicate.uid = scene.groups[0].uid
    scene.groups.append(duplicate)
    path = tmp_path / "existing.ifc"
    path.write_text("keep me")
    with pytest.raises(ValueError, match="Duplicate BIM object identity"):
        save_ifc(scene, path)
    assert path.read_text() == "keep me"


def test_compressed_ids_roundtrip_with_independent_ifc_implementation(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from ifcopenshell import guid
    from core.ifc_identity import compressed_guid
    value = uuid.UUID("00112233-4455-6677-8899-aabbccddeeff")
    assert compressed_guid(value) == guid.compress(value.hex)
    assert guid.expand(ifc_guid())
    scene = _scene("group-faces")
    scene.groups.append(copy_group(scene.groups[0], V(5, 0, 0)))
    path = tmp_path / "model.ifc"
    _roots(scene, path)
    model = ifcopenshell.open(str(path))
    assert len(model.by_type("IfcWall")) == 2
    for root in model.by_type("IfcRoot"):
        assert len(guid.expand(root.GlobalId)) == 32
