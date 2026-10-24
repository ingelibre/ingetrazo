# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A guide at NaN refused the whole save (#723).

The report: «Save failed … Where: scene › guides[0] › point[0]». A guide is
scaffolding — the loader already drops one at NaN (#185) — so the save
leaves it out instead of putting the user's work at risk, and the Tape and
the Protractor never leave one behind from a degenerate pick.
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D  # noqa: E402

from core.guide import Guide  # noqa: E402
from core.history import History  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402
from tools.tape import TapeMeasureTool  # noqa: E402

NAN = math.nan


class _Vp:
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)

    def update(self):
        pass

    def flash_status(self, *a, **k):
        pass


def test_a_nan_guide_does_not_block_the_save(tmp_path):
    path = tmp_path / "guias.igz"
    scene = Scene()
    scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                         QVector3D(1, 1, 0)])
    scene.guides.append(Guide(QVector3D(NAN, 0, 0)))
    scene.guides.append(Guide(QVector3D(2, 0, 0), QVector3D(0, 1, 0)))
    igz.save_scene(scene, path)              # no NonFiniteDocumentError
    back = Scene()
    igz.load_into(back, path)
    assert len(back.faces) == 1              # the model is all there
    (g,) = back.guides                       # the good guide survives
    assert g.is_line and g.point == QVector3D(2, 0, 0)
    assert len(scene.guides) == 2            # saving changes nothing live


def test_is_finite_looks_at_every_coordinate():
    assert Guide(QVector3D(1, 2, 3), QVector3D(1, 0, 0)).is_finite()
    assert not Guide(QVector3D(NAN, 0, 0)).is_finite()
    assert not Guide(QVector3D(0, 0, 0), None,
                     QVector3D(0, math.inf, 0)).is_finite()


def test_the_tape_leaves_no_guide_from_a_nan_pick():
    scene = Scene()
    vp = _Vp(scene)
    tool = TapeMeasureTool()
    tool.start_point = QVector3D(0, 0, 0)
    tool._place_guide_point(vp, QVector3D(NAN, 1, 0), QVector3D(0, 0, 0))
    assert scene.guides == []
    assert not vp.history.undo_stack         # no empty step either
