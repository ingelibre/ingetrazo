# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A face painted inside a component shows on every copy, whatever paint the
copy wears as a whole (#1129).

Each paint a copy wears has its own bake of the shared definition. The flag
that says «a material changed» lives on the mesh and the first bake to see it
cleared it, so a copy painted as a whole went on drawing its old bake: the
yellow face came and went with the colour of the container."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group  # noqa: E402
from core.history import SetFaceColorCommand, SetGroupMaterialCommand  # noqa: E402
from core.mesh import Mesh  # noqa: E402

BLUE = {"color": [0.0, 0.0, 1.0]}
GREEN = {"color": [0.0, 1.0, 0.0]}
YELLOW = (1.0, 1.0, 0.0)


def _box():
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for q in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
              [2, 3, 7, 6], [3, 0, 4, 7]):
        m.add_face([p[i] for i in q])
    return m


def _copies(scene):
    proto = _box()
    copies = []
    for name, dx in (("part 1", 0.0), ("part 2", 3.0)):
        g = Group(proto, name)
        g.component = True
        xf = QMatrix4x4()
        xf.translate(dx, 0, 0)
        g.xform = xf
        scene.groups.append(g)
        copies.append(g)
    scene.version += 1
    return copies


def _shows_yellow(vp, group):
    """Whether the bake a placement draws has a yellow face (any shade)."""
    import numpy as np
    chunk = vp._group_chunk(group)
    raw = chunk["vcol"]
    arr = np.frombuffer(raw if isinstance(raw, (bytes, bytearray))
                        else raw.tobytes(), dtype=np.float32).reshape(-1, 6)
    rgb = arr[:, 3:6]
    return bool(((rgb[:, 0] > 0.3) & (rgb[:, 1] > 0.3) & (rgb[:, 2] < 0.05)).any())


@pytest.fixture
def win():
    from views.main_window import MainWindow
    w = MainWindow()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()


@pytest.mark.parametrize("first", [0, 1], ids=["plain copy first", "painted first"])
def test_a_face_painted_inside_shows_on_every_copy(win, first):
    vp = win.viewport
    scene = vp.scene
    part1, part2 = _copies(scene)
    vp.history.execute(SetGroupMaterialCommand(part2, BLUE))
    assert not _shows_yellow(vp, part1) and not _shows_yellow(vp, part2)

    vp.begin_group_edit(part2)
    face = scene.mesh.faces[2]
    vp.history.execute(SetFaceColorCommand([face], YELLOW))
    vp.end_one_group_edit()

    order = (part1, part2) if first == 0 else (part2, part1)
    for g in order:
        assert _shows_yellow(vp, g), g.name


def test_each_later_coat_keeps_the_yellow_face(win):
    """The rest of the video: blue had been baked before the yellow face and
    showed none; green and the like, baked after it, showed it."""
    vp = win.viewport
    scene = vp.scene
    part1, part2 = _copies(scene)
    vp.history.execute(SetGroupMaterialCommand(part2, BLUE))
    _shows_yellow(vp, part1), _shows_yellow(vp, part2)
    vp.begin_group_edit(part2)
    vp.history.execute(SetFaceColorCommand([scene.mesh.faces[2]], YELLOW))
    vp.end_one_group_edit()
    assert _shows_yellow(vp, part1)
    for coat in (GREEN, BLUE, GREEN):
        vp.history.execute(SetGroupMaterialCommand(part2, coat))
        assert _shows_yellow(vp, part2), coat


def test_an_edit_no_sample_sees_reaches_every_paint_too(win):
    """The same flags answer for geometry: past the sampled vertices only the
    fingerprint can tell, and only the first bake was asked for it."""
    import numpy as np
    vp = win.viewport
    scene = vp.scene
    proto = Mesh()
    for i in range(30):
        for j in range(3):
            proto.add_face([V(i, j, 0), V(i + 1, j, 0),
                            V(i + 1, j + 1, 0), V(i, j + 1, 0)])
    a, b = Group(proto, "a"), Group(proto, "b")
    for g, dy in ((a, 0.0), (b, 9.0)):
        g.component = True
        xf = QMatrix4x4()
        xf.translate(0, dy, 0)
        g.xform = xf
        scene.groups.append(g)
    b.material = dict(BLUE)
    scene.version += 1
    base = vp._group_chunk(_wrapper(vp, proto, b.material))
    vp._group_chunk(a), vp._group_chunk(b)
    sampled = {i for i, _p in base["samples"]}
    moved = next(i for i in range(len(proto.vertices)) if i not in sampled)
    proto.vertices[moved].position = (proto.vertices[moved].position
                                      + V(0, 0, 0.25))
    proto._chunk_dirty = True
    proto._mut_serial = getattr(proto, "_mut_serial", 0) + 1
    scene.version += 1
    vp._group_chunk(a)
    arr = np.frombuffer(vp._group_chunk(_wrapper(vp, proto, b.material))["vcol"],
                        dtype=np.float32).reshape(-1, 6)
    assert np.isclose(arr[:, 2], 0.25).any()


def _wrapper(vp, mesh, paint):
    from views.viewport import _proto_wrapper
    return _proto_wrapper(vp, mesh, paint)
