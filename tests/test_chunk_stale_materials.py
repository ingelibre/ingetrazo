# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A repaint must not be lost inside a group's translation fast path.

Marco, modelling Plaza Yanque (2026-09-10): inside the group the flagstone
corner showed its tan paving, and the moment he left the group it wore its
neighbour's grey. The face data was right both times — what was wrong was
the cached group chunk. ``_translation_probe`` judges GEOMETRY only, and
``_shift_chunk`` reuses the cached texture buckets as they are, so a repaint
that happened in the same breath as a move rode along invisibly.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage, QVector3D

from core.group import Group
from core.history import History, MoveGroupCommand, SetFaceTextureCommand
from core.mesh import Mesh
from core.scene import Scene
from views.viewport import Viewport


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


class _VP:
    def __init__(self, scene):
        self.scene = scene

    def width(self):
        return 100

    def height(self):
        return 100


def _stub(scene):
    """A Viewport with no GL: every plain method bound, no chunk disk cache."""
    vp = _VP(scene)
    for name in dir(Viewport):
        if name.startswith("__") or hasattr(vp, name):
            continue
        attr = Viewport.__dict__.get(name)
        if isinstance(attr, types.FunctionType):
            setattr(vp, name, attr.__get__(vp))
        elif isinstance(attr, staticmethod):
            setattr(vp, name, attr.__func__)
        elif not callable(attr) and attr is not None:
            setattr(vp, name, attr)
    vp.active_tool = None
    vp._chunk_cache_load = None
    vp._chunk_cache_store = None
    return vp


@pytest.fixture
def images(tmp_path):
    out = {}
    for name, col in (("tan", QColor(200, 160, 110)),
                      ("gray", QColor(170, 170, 175))):
        img = QImage(8, 8, QImage.Format.Format_RGBA8888)
        img.fill(col)
        p = tmp_path / f"{name}.png"
        img.save(str(p))
        out[name] = str(p)
    return out


def _paths(chunk):
    return sorted(Path(k[0]).name for k in chunk["by_texture"])


def _strip(scene, images):
    mesh = Mesh()
    corner = mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    neighbour = mesh.add_face([V(2, 0), V(4, 0), V(4, 2), V(2, 2)])
    corner.attrs["texture"] = {"path": images["tan"], "sw": 1.0, "sh": 1.0}
    neighbour.attrs["texture"] = {"path": images["gray"], "sw": 1.0, "sh": 1.0}
    g = Group(mesh, name="Franja")
    scene.groups.append(g)
    return g, corner


def test_repaint_survives_a_move_of_the_same_group(images):
    scene = Scene()
    g, corner = _strip(scene, images)
    vp = _stub(scene)
    assert _paths(vp._group_chunk(g)) == ["gray.png", "tan.png"]

    history = History(scene)
    history.execute(SetFaceTextureCommand(
        [corner], {"path": images["gray"], "sw": 1.0, "sh": 1.0}))
    history.execute(MoveGroupCommand(g, V(5.0, 0.0, 0.0)))
    assert _paths(vp._group_chunk(g)) == ["gray.png"], \
        "the moved chunk kept the corner's old texture"


def test_a_plain_move_still_takes_the_fast_path(images):
    """The guard must not cost the drag its O(1) shift."""
    scene = Scene()
    g, _corner = _strip(scene, images)
    vp = _stub(scene)
    entry = vp._group_chunk(g)
    rev = entry["rev"]
    History(scene).execute(MoveGroupCommand(g, V(5.0, 0.0, 0.0)))
    again = vp._group_chunk(g)
    assert again is entry, "a pure translation rebuilt the chunk"
    assert again["rev"] == rev + 1


def test_repaint_alone_is_picked_up_too(images):
    scene = Scene()
    g, corner = _strip(scene, images)
    vp = _stub(scene)
    vp._group_chunk(g)
    History(scene).execute(SetFaceTextureCommand(
        [corner], {"path": images["gray"], "sw": 1.0, "sh": 1.0}))
    assert _paths(vp._group_chunk(g)) == ["gray.png"]


def test_the_flag_reaches_nested_placements(images):
    """A nested placement's mesh renders as part of its parent, so it needs
    the same signal — scene.groups as a flat list never reached it."""
    from PySide6.QtGui import QMatrix4x4
    from core.history import _dirty_group_chunks
    scene = Scene()
    deep = Mesh()
    deep.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    child = Group(deep, name="Tabla")
    child.xform = QMatrix4x4()
    parent = Group(Mesh(), name="Banca")
    parent.adopt([child])
    scene.groups.append(parent)
    deep._attrs_dirty = False
    _dirty_group_chunks(scene)
    assert getattr(deep, "_attrs_dirty", False), "the nested mesh was missed"


def test_the_per_face_memo_stays_only_on_the_mesh_being_edited():
    """The per-face geometry memo makes a stroke inside a big group cheap,
    but kept on every mesh it cost +140 MB on the Plaza (release_check
    10-10): a closed group's chunk lets it go once built."""
    scene = Scene()
    m = Mesh()
    m.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    g = Group(m, "cerrado")
    scene.groups.append(g)
    vp = _stub(scene)
    vp._group_chunk(g)
    assert "_face_geom_memo" not in m.__dict__
    # open for editing (its mesh is the edit context's): the memo stays
    vp._editing_meshes = lambda: {id(m)}
    m.add_face([V(2, 0), V(3, 0), V(3, 1), V(2, 1)])      # a stroke inside
    scene.version += 1
    vp._group_chunk(g)
    assert "_face_geom_memo" in m.__dict__
