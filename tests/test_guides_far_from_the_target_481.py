# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A guide far from what the camera looks at keeps visible dashes (#481).

@jonson7777: on big models a guide went faint once placed. The committed
guide is dashed in the GL pass with a spacing made for the camera's orbit
distance — a metre from a detail, a guide 30 m away got 3 cm dashes (under
a pixel) over 15 m only. Each guide now scales its dashes by how far its
looked-at stretch is from the eye."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QVector3D as V

from core.guide import Guide
from views.viewport import _guide_vertices


def _dashes(guide, eye):
    target = V(0, 0, 0)
    dist = (eye - target).length()
    coords, spans = _guide_vertices([guide], dist * 0.03, centre=target,
                                    reach=dist * 15.0, eye=eye)
    pts = np.asarray(coords, float).reshape(-1, 2, 3)
    return pts, spans


def test_a_far_guide_gets_dashes_sized_for_its_own_distance():
    eye = V(0, -1, 0)                        # a metre from a detail
    far = Guide(V(0, 30, 0), V(1, 0, 0))     # 31 m from the eye
    pts, _ = _dashes(far, eye)
    dash = np.linalg.norm(pts[0, 1] - pts[0, 0])
    span = pts[:, :, 0].max() - pts[:, :, 0].min()
    assert dash > 0.3                        # ~0.47 m at 31 m, not 1.5 cm
    assert span > 400                        # reaches ±15 distances there


def test_a_guide_through_the_target_is_dashed_as_before():
    eye = V(0, -10, 0)
    near = Guide(V(0, 0, 0), V(1, 0, 0))
    pts, _ = _dashes(near, eye)
    with_eye = np.linalg.norm(pts[0, 1] - pts[0, 0])
    coords, _ = _guide_vertices([near], 0.3, centre=V(0, 0, 0), reach=150.0)
    plain = np.asarray(coords, float).reshape(-1, 2, 3)
    assert abs(with_eye - np.linalg.norm(plain[0, 1] - plain[0, 0])) < 1e-6
