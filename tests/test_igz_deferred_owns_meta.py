# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A mesh left to build later owns what it is built from (#1533).

The window opens with a progress callback, and then load_into empties the
parsed document in place. A format-3 mesh deferred under the native engine
borrowed its block's ``face_attrs`` table from that document: built later it
found the table empty, raised IndexError and came back with no faces — and a
save then wrote the file without them."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D

from core.group import Group
from core.mesh import Mesh, face_attrs
from core.scene import Scene
from formats import igz

N = 400


@pytest.fixture
def path(tmp_path, monkeypatch):
    """More than 64 groups and a loose mesh with more than 64 colours: both
    tables are big enough for the loader to empty them."""
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)    # format-3 blocks
    scene = Scene()
    for i in range(80):
        m = Mesh()
        m.add_face([QVector3D(i, 0, 0), QVector3D(i + .5, 0, 0),
                    QVector3D(i + .5, .5, 0)])
        scene.groups.append(Group(m, name=f"G{i}"))
    for i in range(N):
        f = scene.loose_mesh.add_face([QVector3D(i, 2, 0),
                                       QVector3D(i + .5, 2, 0),
                                       QVector3D(i + .5, 2.5, 0)])
        f.attrs["color"] = (i / N, 0.5, 0.5, 1.0)
    out = tmp_path / "many.igz"
    igz.save_scene(scene, out)
    return out


def _open_as_the_window(path):
    scene = Scene()
    igz.load_into(scene, path, progress=lambda *a: None)
    return scene


def test_a_mesh_built_after_the_open_keeps_its_faces(path):
    scene = _open_as_the_window(path)
    faces = list(scene.loose_mesh.faces)
    assert len(faces) == N
    colours = {tuple(f.attrs.get("color")) for f in faces}
    assert len(colours) == N                    # and each its own colour


def test_saving_an_untouched_mesh_writes_its_faces(path, tmp_path):
    scene = _open_as_the_window(path)
    again = tmp_path / "again.igz"
    igz.save_scene(scene, again)
    back = Scene()
    igz.load_into(back, again)
    assert len(back.loose_mesh.faces) == N


def test_its_materials_are_listed_without_building_it(path):
    scene = _open_as_the_window(path)
    assert len(list(face_attrs(scene.loose_mesh))) >= N
