# SPDX-License-Identifier: GPL-3.0-or-later
import math
from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D

from core import maker
from core.group import placement_points
from core.solids import solid_report
from core.scene import Scene
from core.history import History, InsertGroupCommand
from tools.place_group import PlaceGroupTool


@pytest.mark.parametrize("form", ["bolt", "rod", "nut"])
def test_threads_are_closed_and_correctly_scaled(form):
    group = maker.thread(form=form, length=4, sides=24)
    closed, volume = solid_report(group.mesh)
    assert closed and volume > 0
    points = placement_points(group)
    assert points[:, 2].max() == pytest.approx(.004)
    assert points[:, 2].min() == pytest.approx(-.004 if form == "bolt" else 0)
    # Detailed parts keep their mesh in mm but placement previews in metres.
    tool = PlaceGroupTool(group)
    assert max(p.length() for pair in tool._segments for p in pair) < .02
    scene = Scene()
    history = History(scene)
    history.execute(InsertGroupCommand(group))
    assert len(scene.groups) == 1
    history.undo()
    assert not scene.groups
    history.redo()
    assert len(scene.groups) == 1


def test_thread_handedness_preserves_volume():
    a = maker.thread(form="rod", length=3, sides=24)
    b = maker.thread(form="rod", length=3, sides=24, left_hand=True)
    assert solid_report(a.mesh)[1] == pytest.approx(solid_report(b.mesh)[1])
    # Reflection in Y changes a helix's handedness.
    def positions(group, flip=1):
        return {(round(v.x(), 4), round(flip*v.y(), 4), round(v.z(), 4))
                for f in group.mesh.faces for v in f.vertices}
    assert positions(a) == positions(b, -1)


def test_gear_tooth_count_bore_and_size():
    group = maker.gear(teeth=24, module=1, bore=5)
    assert solid_report(group.mesh)[0]
    points = placement_points(group)
    radii = (points[:, 0]**2 + points[:, 1]**2)**.5
    assert radii.max() == pytest.approx(.013)
    assert radii.min() == pytest.approx(.0025)
    assert points[:, 2].max() == pytest.approx(.005)
    # Each tooth's tip occupies a distinct angular sector.
    tips = points[abs(radii - .013) < 1e-7]
    sectors = {round(math.atan2(p[1], p[0]) * 24 / (2*math.pi)) % 24 for p in tips}
    assert len(sectors) == 24


def test_naca_symmetric_thickness_and_span():
    group = maker.aerofoil(code="0012", chord=100, span=200)
    assert solid_report(group.mesh)[0]
    pts = placement_points(group)
    assert pts[:, 0].max() - pts[:, 0].min() == pytest.approx(.1)
    assert pts[:, 1].max() - pts[:, 1].min() == pytest.approx(.2)
    assert pts[:, 2].max() == pytest.approx(-pts[:, 2].min(), abs=1e-6)
    assert pts[:, 2].max() - pts[:, 2].min() == pytest.approx(.012, abs=1e-4)


@pytest.mark.parametrize("fn,values", [
    (maker.thread, dict(pitch=20)),
    (maker.thread, dict(length=10000)),
    (maker.thread, dict(form="nut", across_flats=5)),
    (maker.gear, dict(teeth=8)),
    (maker.gear, dict(bore=100)),
    (maker.aerofoil, dict(code="1012")),
    (maker.aerofoil, dict(code="abcd")),
    (maker.aerofoil, dict(chord=float("nan"))),
])
def test_bad_parameters_fail_before_insertion(fn, values):
    with pytest.raises(ValueError):
        fn(**values)


def test_plugin_exposes_three_generators():
    from core.extensions import _import_by_path
    module = _import_by_path("maker_tools", Path(__file__).parents[1] / "plugins/maker_tools.py")
    assert [cls().name for cls in (module.ThreadMaker, module.GearMaker, module.AerofoilMaker)] == [
        "Thread / Bolt / Nut", "Spur Gear", "Aerofoil / Wing Section"]


@pytest.mark.parametrize("kind", ["thread", "gear", "aerofoil"])
def test_generator_dialog_builds_part_before_placement(kind, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QDialog, QWidget
    from plugins import maker_tools
    made = []
    window = QWidget()
    window._start_place = made.append
    viewport = SimpleNamespace(window=lambda: window, setFocus=lambda: None)
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.Accepted)
    maker_tools._run(viewport, kind, kind)
    assert len(made) == 1
    assert solid_report(made[0].mesh)[0]


@pytest.mark.parametrize("preset", maker.AEROFOIL_PRESETS)
def test_aerofoil_presets_are_closed_and_scaled(preset):
    group = maker.aerofoil(preset=preset, chord=100, span=200)
    closed, volume = solid_report(group.mesh)
    assert closed and volume > 0
    pts = placement_points(group)
    assert (pts[:, 1].max() - pts[:, 1].min()) == pytest.approx(.2)
    assert (pts[:, 0].max() - pts[:, 0].min()) == pytest.approx(.1, abs=.001)


def test_clark_y_preserves_flat_aft_underside():
    import numpy as np
    outline = maker._stored_aerofoil("clarky", 60)
    lower = outline[np.argmin(outline[:, 0]):]
    aft = lower[lower[:, 0] > .4]
    fit = np.polyfit(aft[:, 0], aft[:, 1], 1)
    assert np.max(np.abs(np.polyval(fit, aft[:, 0]) - aft[:, 1])) < 1e-5


def test_aerofoil_preset_dialog_preserves_custom_code(monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QWidget
    from plugins import maker_tools
    window = QWidget()
    def interact(dialog):
        preset = dialog.findChild(QComboBox, "aerofoil_preset")
        code = dialog.findChild(QLineEdit, "naca_code")
        preset.setCurrentIndex(preset.findData("custom"))
        assert code.isEnabled() and code.text() == "2412"
        code.setText("4418")
        code.textEdited.emit("4418")
        preset.setCurrentIndex(preset.findData("flat_bottom"))
        assert not code.isEnabled()
        preset.setCurrentIndex(preset.findData("custom"))
        assert code.text() == "4418"
        return QDialog.Rejected
    monkeypatch.setattr(QDialog, "exec", interact)
    maker_tools._run(SimpleNamespace(window=lambda: window), "Aerofoil", "aerofoil")
