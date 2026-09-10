# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Offset (F) must not strip the face's paint.

Both halves keep the material, the layer and the BIM tag — SketchUp's Offset
does. Losing them turned a textured flagstone slab into two blank faces,
which on a finished drawing reads as "it created a face on top" (Marco,
2026-09-10). Make Group learned this same lesson earlier; the tool didn't.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.offset import OffsetTool


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


class _VP:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass


def _slab(scene):
    return scene.mesh.add_face([V(0, 0), V(10, 0), V(10, 6), V(0, 6)])


def _offset(vp, face, distance):
    tool = OffsetTool()
    tool.base_face = face
    tool._loop = [QVector3D(v) for v in face.vertices]
    tool._normal = face.normal()
    tool.distance = distance
    tool._commit(vp)


def test_both_halves_keep_the_material():
    scene = Scene()
    face = _slab(scene)
    face.attrs.update({"mat": "Piedra laja",
                       "texture": {"path": "/tmp/laja.png", "sw": 1.0,
                                   "sh": 1.0},
                       "layer": "Pisos"})
    vp = _VP(scene)
    _offset(vp, face, 1.0)
    assert len(scene.mesh.faces) == 2
    for f in scene.mesh.faces:
        assert f.attrs.get("mat") == "Piedra laja"
        assert f.attrs.get("texture", {}).get("path") == "/tmp/laja.png"
        assert f.attrs.get("layer") == "Pisos"


def test_the_two_halves_do_not_share_one_attrs_dict():
    """Painting one half afterwards must not repaint the other."""
    scene = Scene()
    face = _slab(scene)
    face.attrs["color"] = (0.5, 0.5, 0.5)
    vp = _VP(scene)
    _offset(vp, face, 1.0)
    ring, inner = scene.mesh.faces
    inner.attrs["color"] = (0.9, 0.2, 0.1)
    assert ring.attrs["color"] == (0.5, 0.5, 0.5)


def test_an_unpainted_face_still_offsets():
    scene = Scene()
    face = _slab(scene)
    vp = _VP(scene)
    _offset(vp, face, 1.0)
    assert len(scene.mesh.faces) == 2
    assert all(f.attrs == {} for f in scene.mesh.faces)


def test_the_base_face_is_gone_not_left_underneath():
    scene = Scene()
    face = _slab(scene)
    vp = _VP(scene)
    _offset(vp, face, 1.0)
    assert face not in scene.mesh.faces
    ring = next(f for f in scene.mesh.faces if f.holes)
    inner = next(f for f in scene.mesh.faces if not f.holes)
    # Ring + inner tile the original exactly: no overlap, nothing missing.
    from core.bim import face_net_area
    assert round(face_net_area(ring) + face_net_area(inner), 6) == 60.0


def test_undo_puts_the_painted_face_back():
    scene = Scene()
    face = _slab(scene)
    face.attrs["color"] = (0.5, 0.5, 0.5)
    vp = _VP(scene)
    _offset(vp, face, 1.0)
    vp.history.undo()
    assert len(scene.mesh.faces) == 1
    assert scene.mesh.faces[0].attrs.get("color") == (0.5, 0.5, 0.5)


# ---- A refusal must say why -------------------------------------------------
#
# Marco, 2026-09-10: "quiero hacer equidistancia en esa cara pero no hace".
# The tool was right to refuse — his paved slab has a 4.6 cm side, so a 10 cm
# inward offset inverts it, and his 20 cm kerbs close exactly at 10 cm. What
# was wrong is that `if off is None: return` said nothing at all.

class _LoudVP(_VP):
    def __init__(self, scene):
        super().__init__(scene)
        self.said = []

    def flash_status(self, text, msec=2500):
        self.said.append(text)


def _kerb(scene, width=0.2):
    """A 2.4 m x `width` strip: 10 cm inward closes a 20 cm one exactly."""
    return scene.mesh.add_face([V(0, 0), V(2.4, 0), V(2.4, width), V(0, width)])


def test_an_impossible_offset_says_so_instead_of_going_silent():
    scene = Scene()
    face = _kerb(scene)
    vp = _LoudVP(scene)
    _offset(vp, face, 0.10)
    assert len(scene.mesh.faces) == 1, "nothing should have been built"
    assert vp.said, "the tool refused without a word"


def test_the_message_names_the_room_that_is_left():
    from core.topology import max_offset_distance
    scene = Scene()
    face = _kerb(scene, width=0.5)
    room = max_offset_distance([QVector3D(v) for v in face.vertices],
                               face.normal(), 1.0)
    assert 0.2 < room < 0.26, room          # half of 0.5, minus the tolerance
    vp = _LoudVP(scene)
    _offset(vp, face, 0.40)
    assert vp.said and "0.2" in vp.said[0], vp.said


def test_a_feasible_offset_stays_quiet_and_builds():
    scene = Scene()
    face = _kerb(scene, width=1.0)
    vp = _LoudVP(scene)
    _offset(vp, face, 0.10)
    assert len(scene.mesh.faces) == 2
    assert not vp.said
