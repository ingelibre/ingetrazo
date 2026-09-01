# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Shadows as document data + the light's fitted projection + the panel.

The GL passes need a screen; what CAN be pinned headless is everything the
render derives from: the settings round-trip through the .igz, the sun's
ortho view-projection actually containing the model, and the tray panel
writing ``scene.shadows``.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.scene import Scene  # noqa: E402
from core.sun import ShadowSettings  # noqa: E402


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


def test_shadows_round_trip_through_igz(tmp_path):
    from formats import igz
    scene = Scene()
    scene.add_edge(V(0, 0, 0), V(2, 0, 0))
    scene.shadows = ShadowSettings(enabled=True, month=6, day=21,
                                   hour=15, minute=30, darkness=0.4)
    path = tmp_path / "sombras.igz"
    igz.save_scene(scene, path)

    loaded = Scene()
    igz.load_into(loaded, path)
    assert loaded.shadows == scene.shadows

    # A document saved WITHOUT shadows loads with the defaults (off).
    plain = Scene()
    plain.add_edge(V(0, 0, 0), V(1, 0, 0))
    p2 = tmp_path / "plano.igz"
    igz.save_scene(plain, p2)
    igz.load_into(loaded, p2)
    assert loaded.shadows == ShadowSettings()


def test_light_vp_contains_the_model():
    """Every corner of the model's bounds must land inside the sun's ortho
    frustum — points outside the map sample as 'lit', so a bad fit would
    silently erase shadows at the rims."""
    from views.viewport import Viewport
    lo, hi = V(-3, -2, 0), V(5, 7, 4)
    for d in ((0.3, 0.5, 0.8), (0.0, 0.0, 1.0), (-0.6, 0.2, 0.75)):
        n = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5
        d = (d[0] / n, d[1] / n, d[2] / n)
        m = Viewport._light_vp(d, lo, hi)
        for x in (lo.x(), hi.x()):
            for y in (lo.y(), hi.y()):
                for z in (lo.z(), hi.z(), 0.0):   # the ground patch too
                    p = m.map(QVector3D(x, y, z))
                    assert -1.0 < p.x() < 1.0
                    assert -1.0 < p.y() < 1.0
                    assert -1.0 < p.z() < 1.0


class _Win:
    def __init__(self):
        class _VP:
            def __init__(self):
                self.scene = Scene()

            def update(self):
                pass

        self.viewport = _VP()


def test_panel_writes_scene_shadows():
    from views.tray import ShadowsPanel
    win = _Win()
    panel = ShadowsPanel(win)
    sh = win.viewport.scene.shadows
    assert sh.enabled is False           # defaults mirrored

    panel._enable.setChecked(True)
    panel._time.setValue(15 * 60 + 30)
    panel._dark.setValue(60)
    assert sh.enabled is True
    assert (sh.hour, sh.minute) == (15, 30)
    assert sh.darkness == pytest.approx(0.4)
    assert panel._time_lbl.text() == "15:30"

    # refresh() mirrors external changes (a load, the Camera menu).
    sh.enabled = False
    sh.hour = 9
    panel.refresh()
    assert not panel._enable.isChecked()
    assert panel._time.value() == 9 * 60 + 30


def test_panel_month_bar_and_time_zone():
    """The SketchUp shadow bar: the day-of-year slider and the date field
    are two views of one date, and the time-zone combo overrides the
    by-longitude default (None = automatic)."""
    from views.tray import ShadowsPanel
    win = _Win()
    panel = ShadowsPanel(win)
    sh = win.viewport.scene.shadows
    assert panel._tz.currentData() is None          # automatic by default

    panel._doy.setValue(172)                        # Jun 21 (solstice)
    assert (sh.month, sh.day) == (6, 21)
    assert panel._date.date().month() == 6

    from PySide6.QtCore import QDate
    panel._date.setDate(QDate(2026, 12, 21))        # the other solstice
    assert (sh.month, sh.day) == (12, 21)
    assert panel._doy.value() == 355

    panel._tz.setCurrentIndex(panel._tz.findData(-4))
    assert sh.utc_offset == -4
    panel._tz.setCurrentIndex(0)                    # back to automatic
    assert sh.utc_offset is None


def test_time_slider_is_bounded_to_daylight():
    """Marco set UTC−10 with 22:39 and the shadows silently vanished — it
    was night. SketchUp never lets that happen: the slider runs sunrise to
    sunset, so a zone change drags the hour back into the sun."""
    from views.tray import ShadowsPanel
    win = _Win()
    panel = ShadowsPanel(win)
    sh = win.viewport.scene.shadows
    # Natural zone (auto, UTC−5): noon sits inside the window.
    assert panel._time.minimum() > 0                # sunrise, not 00:00
    assert panel._time.maximum() < 24 * 60 - 1      # sunset, not 23:59
    assert panel._time.minimum() <= 12 * 60 <= panel._time.maximum()
    assert panel._sunrise_lbl.text() != "" and panel._sunset_lbl.text() != ""

    # Force UTC−10: daylight shifts ~5 h earlier and 12:00 falls OUTSIDE —
    # the slider clamps and the stored hour follows it back into the sun.
    panel._tz.setCurrentIndex(panel._tz.findData(-10))
    assert panel._time.maximum() < 14 * 60          # afternoon is night now
    assert sh.hour * 60 + sh.minute == panel._time.value()
    assert panel._time.minimum() <= panel._time.value() <= panel._time.maximum()
