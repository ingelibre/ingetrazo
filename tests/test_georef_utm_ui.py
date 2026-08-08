# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""UTM WGS84 entry in the georef UI: the base-map panel and the project
locator accept and display the anchor in UTM (zone/E/N — the frame a drone
survey or total station reports) alongside lat/lon, always in sync. The
centre pin of the locator is explicitly the model's origin (0,0)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.scene import Scene                                     # noqa: E402
from georef.datum import utm_forward, utm_inverse                # noqa: E402
from views.tray import BaseMapPanel                              # noqa: E402

# Plaza de Yanque, Caylloma — UTM zone 19, southern hemisphere.
LAT, LON = -15.8402, -70.0219


class _Win:
    class viewport:
        scene = Scene()


@pytest.fixture(autouse=True)
def _isolated_settings():
    prev_org = QCoreApplication.organizationName()
    prev_app = QCoreApplication.applicationName()
    QCoreApplication.setOrganizationName("IngeTrazoTest")
    QCoreApplication.setApplicationName("georef-utm-test")
    QSettings().clear()
    yield
    QSettings().clear()
    QCoreApplication.setOrganizationName(prev_org)
    QCoreApplication.setApplicationName(prev_app)


class TestBaseMapPanelUtm:
    def test_lat_lon_fills_the_utm_boxes(self):
        panel = BaseMapPanel(_Win())
        panel._lat.setValue(LAT)
        panel._lon.setValue(LON)
        panel._sync_utm_from_ll()
        east, north = utm_forward(LAT, LON, 19)
        assert panel._utm_zone.value() == 19
        assert panel._utm_hemi.currentData() is False            # south
        assert panel._utm_e.value() == pytest.approx(east, abs=0.01)
        assert panel._utm_n.value() == pytest.approx(north, abs=0.01)

    def test_typing_utm_moves_lat_lon(self):
        panel = BaseMapPanel(_Win())
        east, north = utm_forward(LAT, LON, 19)
        panel._utm_zone.setValue(19)
        panel._utm_hemi.setCurrentIndex(1)                       # south
        panel._utm_e.setValue(east + 100.0)                      # 100 m east
        panel._utm_n.setValue(north)
        panel._sync_ll_from_utm()
        lat2, lon2 = utm_inverse(east + 100.0, north, 19, False)
        assert panel._lat.value() == pytest.approx(lat2, abs=1e-6)
        assert panel._lon.value() == pytest.approx(lon2, abs=1e-6)
        # ~100 m of longitude at this latitude
        assert panel._lon.value() > LON

    def test_utm_survives_a_round_trip(self):
        panel = BaseMapPanel(_Win())
        panel._lat.setValue(LAT)
        panel._lon.setValue(LON)
        panel._sync_utm_from_ll()
        panel._sync_ll_from_utm()
        assert panel._lat.value() == pytest.approx(LAT, abs=1e-6)
        assert panel._lon.value() == pytest.approx(LON, abs=1e-6)


class TestCoordModeSelector:
    """One frame at a time: the selector shows lat/lon OR UTM, never both,
    and the choice persists across panels and the locator dialog."""

    def test_geo_mode_hides_the_utm_rows(self):
        panel = BaseMapPanel(_Win())
        panel._coord_mode.setCurrentIndex(
            panel._coord_mode.findData("geo"))
        assert not panel._utm_e.isVisibleTo(panel)
        assert panel._lat.isVisibleTo(panel)

    def test_utm_mode_hides_the_geo_rows(self):
        panel = BaseMapPanel(_Win())
        panel._coord_mode.setCurrentIndex(
            panel._coord_mode.findData("utm"))
        assert panel._utm_e.isVisibleTo(panel)
        assert not panel._lat.isVisibleTo(panel)

    def test_choice_is_remembered_everywhere(self):
        panel = BaseMapPanel(_Win())
        panel._coord_mode.setCurrentIndex(
            panel._coord_mode.findData("utm"))
        fresh = BaseMapPanel(_Win())                 # "next session"
        assert fresh._coord_mode.currentData() == "utm"
        from georef.tiles import PRESETS
        from views.location_dialog import LocationDialog
        dlg = LocationDialog(PRESETS["esri_imagery"], LAT, LON)
        assert dlg._coord_mode.currentData() == "utm"
        assert dlg._utm_row.isVisibleTo(dlg)
        assert not dlg._geo_row.isVisibleTo(dlg)


class TestLocationDialogUtm:
    def _dialog(self):
        from georef.tiles import PRESETS
        from views.location_dialog import LocationDialog
        return LocationDialog(PRESETS["esri_imagery"], LAT, LON)

    def test_center_fills_both_coordinate_rows(self):
        dlg = self._dialog()
        dlg._map.set_center(LAT, LON)
        east, north = utm_forward(LAT, LON, 19)
        assert dlg._lat_box.value() == pytest.approx(LAT, abs=1e-6)
        assert dlg._zone_box.value() == 19
        assert dlg._hemi_box.currentData() is False
        assert dlg._east_box.value() == pytest.approx(east, abs=0.01)
        assert dlg._north_box.value() == pytest.approx(north, abs=0.01)

    def test_typed_utm_moves_the_pin(self):
        dlg = self._dialog()
        dlg._map.set_center(LAT, LON)
        east, north = utm_forward(LAT, LON, 19)
        dlg._east_box.setValue(east + 250.0)
        dlg._north_box.setValue(north - 250.0)
        dlg._on_utm_typed()
        lat, lon = dlg._map.center()
        exp_lat, exp_lon = utm_inverse(east + 250.0, north - 250.0, 19,
                                       False)
        assert lat == pytest.approx(exp_lat, abs=1e-6)
        assert lon == pytest.approx(exp_lon, abs=1e-6)
