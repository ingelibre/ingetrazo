# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""#1533: a deferred format-3 mesh opened with a progress callback keeps
its faces. load_into empties the parsed document tree in place
(_release_in_steps) once it is read; the deferred mesh borrowed its
face-attribute table from that tree, so the first touch after the release
raised IndexError and the mesh came back empty."""
from __future__ import annotations

import pytest
from PySide6.QtGui import QVector3D as V

import core._native as _native
from core.group import Group
from core.mesh import Mesh
from core.scene import Scene
from formats import igz


@pytest.fixture
def binary(monkeypatch):
    """Every document counts as large and every mesh goes binary."""
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)


def test_a_deferred_mesh_keeps_its_faces_after_a_progress_open(
        tmp_path, binary, monkeypatch):
    monkeypatch.setattr(_native, "wanted", lambda: True)
    scene = Scene()
    for i in range(80):  # more than 64 groups: the tree is released in steps
        m = Mesh()
        m.add_face([V(i, 0, 0), V(i + .5, 0, 0), V(i + .5, .5, 0)])
        scene.groups.append(Group(m, name=f"G{i}"))
    for i in range(400):  # face_attrs past 64 entries: the table is emptied
        f = scene.loose_mesh.add_face([V(i, 2, 0), V(i + .5, 2, 0),
                                       V(i + .5, 2.5, 0)])
        f.attrs["color"] = (i / 400, 0.5, 0.5, 1.0)
    path = tmp_path / "repro.igz"
    igz.save_scene(scene, path)

    opened = Scene()
    igz.load_into(opened, path, progress=lambda *args: None)
    assert len(opened.loose_mesh.faces) == 400
    assert list(opened.loose_mesh.faces[0].attrs["color"]) == \
        [0.0, 0.5, 0.5, 1.0]
    # Saving the untouched mesh must keep the faces too.
    again = tmp_path / "again.igz"
    igz.save_scene(opened, again)
    reopened = Scene()
    igz.load_into(reopened, again)
    assert len(reopened.loose_mesh.faces) == 400
