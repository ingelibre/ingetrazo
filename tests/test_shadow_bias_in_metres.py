# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The shadow margins are tuned in the map's depth units, which a deep map
stretches: a plaza with its orthophoto (~1 300 m along the sun) turned
them into metres and every shadow began away from its base (the arch's
1.5 m off its columns, the figure's off its feet: Marco, 16-11, sheet
L-08). They are now capped in metres; a model a few tens of metres deep
keeps the values as tuned."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from views.viewport import Viewport

_app = QApplication.instance() or QApplication([])

SUN = (-0.712, 0.197, 0.674)


def _metres(light_vp):
    depth = Viewport._shadow_footprint(light_vp)[1]
    return [b * depth for b in Viewport._shadow_biases(light_vp)], depth


def test_a_house_keeps_the_tuned_margins():
    vp = Viewport._light_vp(SUN, V(0, 0, 0), V(10, 8, 6))
    assert Viewport._shadow_biases(vp) == Viewport._SHADOW_BIAS_TUNED


@pytest.mark.parametrize("side", [200.0, 600.0, 1200.0])
def test_a_deep_map_keeps_its_margins_to_centimetres(side):
    vp = Viewport._light_vp(SUN, V(-side / 2, -side / 2, -5), V(side / 2, side / 2, 30))
    metres, depth = _metres(vp)
    assert depth > 500.0
    const, slope_max, recv = metres
    caps = Viewport._SHADOW_BIAS_MAX_M
    assert const == pytest.approx(caps[0]) and recv == pytest.approx(caps[2])
    assert slope_max == pytest.approx(caps[1])
    # The shadow of a post's base begins within a few centimetres of it.
    sun_elev = 0.674 / (0.712 ** 2 + 0.197 ** 2) ** 0.5
    assert (const + recv) / sun_elev < 0.05


def test_the_margins_never_exceed_the_tuned_ones():
    for side in (2.0, 20.0, 40.0, 80.0, 400.0, 4000.0):
        vp = Viewport._light_vp(SUN, V(0, 0, 0), V(side, side, 3))
        for b, t in zip(Viewport._shadow_biases(vp), Viewport._SHADOW_BIAS_TUNED):
            assert 0.0 < b <= t


def test_no_light_matrix_gives_the_tuned_margins():
    assert Viewport._shadow_biases(None) == Viewport._SHADOW_BIAS_TUNED
