# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Work bounds of two passes 0.6.3 added to every frame or every undo.

* The photos held by groups (c60973b0) were found by walking every
  placement three times a frame — ~2 ms of each orbit or zoom frame on
  Marco's plaza (3 400 groups, no grouped photo at all) and ~40 ms of the
  first frame after an undo. The walk now runs once per scene version.
* ``_remap_uvws`` read the two matrices into numpy once per textured face
  since #1405; once per mesh is enough (and gives the same floats)."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.history import History
from core.mesh import Mesh
from core.scene import Scene


def _image(name="facade.png"):
    from core.image_plane import ImagePlane
    return ImagePlane(name, V(0, 0, 0), V(4, 0, 0), V(0, 3, 0), aspect=0.75)


class _CountingList(list):
    """The placements list, counting the walks over it."""
    walks = 0

    def __iter__(self):
        type(self).walks += 1
        return super().__iter__()


def _fake(scene):
    from views.viewport import Viewport
    groups = _CountingList(scene.groups)
    _CountingList.walks = 0
    fake = SimpleNamespace(scene=scene, _placements=lambda: groups,
                           _owner_of=lambda g: g)
    fake._grouped_image_rows = (
        lambda: Viewport._grouped_image_rows(fake))
    return fake, groups, Viewport


def test_frames_without_a_change_walk_the_placements_once():
    from core.history import MakeImageGroupCommand
    scene = Scene()
    hist = History(scene)
    image = _image()
    scene.image_planes.append(image)
    hist.execute(MakeImageGroupCommand([image]))
    group = scene.groups[0]
    for k in range(50):                         # plain groups, no photo
        scene.groups.append(Group(Mesh(), name=f"g{k}"))
    fake, _groups, Viewport = _fake(scene)
    first = list(Viewport._placed_image_planes(fake))
    assert first == [(image, group.xform, group)]
    assert _CountingList.walks == 1
    for _frame in range(30):                    # an orbit: no version bump
        assert list(Viewport._placed_image_planes(fake)) == first
    assert _CountingList.walks == 1, "the placements were walked again"
    scene.version += 1                          # an edit: one walk more
    assert list(Viewport._placed_image_planes(fake)) == first
    assert _CountingList.walks == 2


def test_a_hidden_photo_group_leaves_at_the_next_version():
    from core.history import MakeImageGroupCommand
    scene = Scene()
    hist = History(scene)
    image = _image()
    scene.image_planes.append(image)
    hist.execute(MakeImageGroupCommand([image]))
    group = scene.groups[0]
    fake, _groups, Viewport = _fake(scene)
    assert len(list(Viewport._placed_image_planes(fake))) == 1
    group.hidden = True
    scene.version += 1                          # what Hide's command does
    assert list(Viewport._placed_image_planes(fake)) == []


def test_the_matrix_is_read_live_during_a_frozen_preview():
    """A groups preview moves the placements without a version bump: the
    photo must follow the matrix of this frame, not the cached one."""
    from core.history import MakeImageGroupCommand
    scene = Scene()
    hist = History(scene)
    image = _image()
    scene.image_planes.append(image)
    hist.execute(MakeImageGroupCommand([image]))
    group = scene.groups[0]
    fake, _groups, Viewport = _fake(scene)
    list(Viewport._placed_image_planes(fake))
    moved = QMatrix4x4()
    moved.translate(5, 0, 0)
    group.xform = moved
    (_im, matrix, _owner), = Viewport._placed_image_planes(fake)
    assert matrix is moved


def _textured_mesh(n):
    m = Mesh()
    for k in range(n):
        f = m.add_face([V(k, 0, 0), V(k + 1, 0, 0), V(k + 1, 1, 0),
                        V(k, 1, 0)])
        f.attrs["texture"] = {"path": "wood.png",
                              "uvw": [1.0, 0.0, 0.0, 0.1 * k,
                                      0.0, 1.0, 0.0, 0.2]}
    return m


def test_remap_uvws_reads_the_matrices_once_per_mesh(monkeypatch):
    import core.group as G
    m = QMatrix4x4()
    m.translate(3, 4, 5)
    m.rotate(30, 0, 0, 1)
    ref = _textured_mesh(40)
    minv, _ok = m.inverted()
    expected = [G._remapped_uvw(f.attrs["texture"]["uvw"], m, minv)
                for f in ref.faces]
    mesh = _textured_mesh(40)
    calls = []
    real = G.np_affine

    def spy(mat):
        calls.append(1)
        return real(mat)
    monkeypatch.setattr(G, "np_affine", spy)
    G._remap_uvws(mesh, m)
    assert len(calls) <= 2, len(calls)
    # Bit for bit what the per-face reading gave.
    assert [f.attrs["texture"]["uvw"] for f in mesh.faces] == expected
