# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A group lifted out by Explode is drawn where it IS (issue #134, @fafecm).

A box group, two copies with Move+Ctrl, the three grouped, the container
moved, then exploded: one box was drawn where it stood before it was grouped
and moved, while its selection box showed the right place; painting it put
it back. Explode gives each lifted child a NEW mesh, and a copy's mesh built
the same way has the same mutation serial and counts — the chunk cache took
the new mesh for the old one."""
from __future__ import annotations

import sys

import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D as V
from PySide6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication(sys.argv[:1])


def _box(scene, hist):
    from core.edits import build_add_edges
    from core.history import MakeGroupCommand
    from tests import test_pushpull_ux as T
    T._cube(scene, hist, size=1.0, height=1.0)
    faces = list(scene.mesh.faces)
    hist.execute(MakeGroupCommand(faces, list(scene.mesh.edges)))
    return scene.groups[-1]


def _drawn_bbox(entry):
    v0 = np.asarray(entry["v0"], dtype=np.float64).reshape(-1, 3)
    return v0.min(0), v0.max(0)


def _mesh_bbox(group):
    pts = np.array([[v.position.x(), v.position.y(), v.position.z()]
                    for v in group.mesh.vertices])
    return pts.min(0), pts.max(0)


def test_exploded_copies_are_drawn_where_they_are():
    from core.group import copy_group
    from core.history import (ExplodeGroupCommand, InsertGroupCommand,
                              MakeNestedGroupCommand)
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    try:
        scene, hist = vp.scene, vp.history
        scene.groups[:] = []                       # no scale figure
        box = _box(scene, hist)
        for dx in (2.0, 4.0):                      # Move + Ctrl copies
            hist.execute(InsertGroupCommand(copy_group(box, V(dx, 0, 0))))
        boxes = list(scene.groups)
        for g in boxes:
            vp._group_chunk(g)                     # drawn once, top level
        hist.execute(MakeNestedGroupCommand([], [], boxes, name="Fila"))
        row = scene.groups[-1]
        m = QMatrix4x4()
        m.translate(0, 3, 1)
        row.xform = m * row.xform                  # the container moved
        scene.version += 1
        vp._placements()                           # drawn nested
        hist.execute(ExplodeGroupCommand(row))
        for g in boxes:
            entry = vp._group_chunk(g) if g.xform is None else None
            if entry is None:
                continue
            lo, hi = _drawn_bbox(entry)
            mlo, mhi = _mesh_bbox(g)
            assert np.allclose(lo, mlo, atol=1e-5), (g.name, lo, mlo)
            assert np.allclose(hi, mhi, atol=1e-5), (g.name, hi, mhi)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
