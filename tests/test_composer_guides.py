# SPDX-License-Identifier: GPL-3.0-or-later
"""QGIS's rulers and guides in the composer (Marco, 2026-09-08: «en QGIS
muestran como unas guías… sería bueno implementar eso en composición»)."""
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QWidget

from core.composition import Composicion, FormaItem
from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow, GuideItem

_app = QApplication.instance() or QApplication([])


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    return host, ComposerWindow(host)


def test_guides_round_trip_in_the_sheet():
    comp = Composicion()
    comp.guides_v = [100.0, 40.5]
    comp.guides_h = [30.0]
    again = Composicion.from_dict(comp.to_dict())
    assert (again.guides_v, again.guides_h) == ([100.0, 40.5], [30.0])
    assert Composicion.from_dict({"name": "x"}).guides_v == []   # old .igz


def test_add_move_remove_guides_with_undo_and_snapping():
    host, composer = _composer()
    composer.add_guide("v", 100.0)
    composer.add_guide("h", 30.0)
    assert composer.comp.guides_v == [100.0] and composer.comp.guides_h == [30.0]
    guides = [it for it in composer.canvas.items() if isinstance(it, GuideItem)]
    assert {(g.axis, g.mm) for g in guides} == {("v", 100.0), ("h", 30.0)}
    assert 100.0 in composer.snap_targets_x() and 30.0 in composer.snap_targets_y()
    composer.move_guide("v", 100.0, 120.0)
    assert composer.comp.guides_v == [120.0]
    composer.remove_guide("h", 30.0)
    assert composer.comp.guides_h == []
    assert composer.history.undo() and composer.comp.guides_h == [30.0]
    assert composer.history.undo() and composer.comp.guides_v == [100.0]
    composer.clear_guides()
    assert composer.comp.guides_v == [] and composer.comp.guides_h == []
    assert composer.history.undo() and composer.comp.guides_v == [100.0]
    # a rebuild keeps them
    composer._rebuild_canvas()
    assert [g.mm for g in composer.canvas.items() if isinstance(g, GuideItem)] == [100.0, 30.0] or \
        sorted(g.mm for g in composer.canvas.items() if isinstance(g, GuideItem)) == [30.0, 100.0]


def test_a_guide_slides_along_its_axis_only_and_delete_removes_it():
    host, composer = _composer()
    composer.add_guide("v", 50.0)
    g = next(it for it in composer.canvas.items() if isinstance(it, GuideItem))
    g.setPos(QPointF(60.0, 25.0))                    # a drag with a slant
    assert (g.pos().x(), g.pos().y()) == (60.0, 0.0)  # y clamped
    g.setSelected(True)
    composer._on_delete_item()
    assert composer.comp.guides_v == []


def test_rulers_map_millimetres_to_pixels_with_the_view():
    host, composer = _composer()          # never shown: offscreen show() crashes
    rh, rv = composer.ruler_h, composer.ruler_v
    a, b = rh.mm_to_px(0.0), rh.mm_to_px(100.0)
    s = composer._view.transform().m11()
    assert abs((b - a) - 100.0 * s) < 1e-6
    assert abs(rh.px_to_mm(b) - 100.0) < 1e-6
    assert abs(rv.px_to_mm(rv.mm_to_px(42.0)) - 42.0) < 1e-6
    composer.update_cursor_label(12.0, 34.0)
    assert (rh._cursor_mm, rv._cursor_mm) == (12.0, 34.0)
