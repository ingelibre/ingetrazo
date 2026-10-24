# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A rotated copy of a component is lit as placed (#482, @PESI3D).

The face tones are baked once per prototype, from ITS normals against the
fixed world light, and every copy reused them: a copy turned 40° kept the
light of the unturned one, while the same geometry as a plain group was
shaded the other way round. Both instance paths re-shade now — the CPU
chunk (copies with glass or painted backs) and the GPU instanced pass."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.group import Group, transformed_mesh  # noqa: E402
from core.mesh import Mesh  # noqa: E402


def _box():
    m = Mesh()
    p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0),
         V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)]
    for q in ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
              [2, 3, 7, 6], [3, 0, 4, 7]):
        m.add_face([p[i] for i in q])
    return m


def _turn(tx=0.0, deg=40.0):
    m = QMatrix4x4()
    m.translate(tx, 0, 0)
    m.rotate(deg, 1, 0, 0)
    return m


def _tones(raw):
    """Each triangle's centroid and colour, sorted by centroid."""
    a = np.frombuffer(raw, np.float32).reshape(-1, 3, 6).astype(float)
    rows = np.hstack([a[:, :, :3].mean(axis=1).round(4), a[:, 0, 3:6]])
    return rows[np.lexsort(rows[:, :3].T[::-1])]


def test_the_cpu_chunk_of_a_turned_copy_matches_the_plain_group():
    from views.viewport import Viewport
    vp = Viewport(None)
    proto = _box()
    inst = Group(proto, "copia")
    inst.xform = _turn()
    sibling = Group(proto, "original")
    sibling.xform = QMatrix4x4()
    plain = Group(transformed_mesh(_box(), _turn()), "grupo")
    vp.scene.groups += [inst, sibling, plain]
    vp.scene.version += 1
    got = _tones(vp._instance_chunk(inst)["vcol"])
    want = _tones(vp._group_chunk(plain)["vcol"])
    assert np.allclose(got[:, :3], want[:, :3], atol=1e-3)
    assert np.allclose(got[:, 3:], want[:, 3:], atol=1.5 / 64)
    # The unturned sibling keeps the bake byte for byte.
    assert (vp._instance_chunk(sibling)["vcol"]
            == vp._group_chunk(Group(_box(), "x"))["vcol"])


def _pixels(img: QImage):
    a = img.convertToFormat(QImage.Format_RGB32)
    buf = np.frombuffer(a.constBits(), np.uint8).reshape(
        a.height(), a.bytesPerLine())[:, :a.width() * 4]
    return buf.reshape(a.height(), a.width(), 4)[..., :3].astype(int).copy()


def test_the_gpu_pass_lights_a_turned_copy_like_the_plain_group():
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    try:
        if getattr(vp, "_gl", None) is None or not vp.isValid():
            pytest.skip("no OpenGL context on this platform")
        scene = vp.scene
        scene.groups[:] = []
        cam = vp.camera
        cam.target, cam.distance = V(0.5, 0.3, 0.6), 6.0
        cam.set_view("iso")
        proto = _box()
        far = Group(proto, "lejos")             # a sibling out of view
        far.xform = QMatrix4x4()
        far.xform.translate(0, 500, 0)
        inst = Group(proto, "copia")
        inst.xform = _turn()
        scene.groups += [far, inst]
        scene.version += 1
        assert vp._instanced_eligible(inst)
        as_copy = _pixels(vp.render_image(300, 300, overlays=False))
        scene.groups[:] = [Group(transformed_mesh(_box(), _turn()), "g")]
        scene.version += 1
        as_group = _pixels(vp.render_image(300, 300, overlays=False))
        diff = np.abs(as_copy - as_group).sum(axis=2)
        # Face interiors agree to the bake's 1/64 steps; only edge pixels
        # (anti-aliasing) may differ more.
        assert np.percentile(diff, 99) <= 12, int(np.percentile(diff, 99))
    finally:
        win._saved_version = vp.scene.version
        win.close()
