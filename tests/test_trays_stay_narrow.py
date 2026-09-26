# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The right-hand trays are tabbed in one dock area, so the WIDEST tab's
minimum is everyone's minimum. A button row, a long check-box label or a
combo sized to «Esri World Imagery (satellite)» used to force the area to
about 390 px. Each tab now fits the trays' own 240 px floor: rows wrap,
long labels wrap and combos ask for a few characters, not their longest
item."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDockWidget, QScrollArea

_app = QApplication.instance() or QApplication([])

#: The trays' own floor (``views.tray._scrolled``) plus a little slack.
BUDGET = 245


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    """The application, with a throwaway QSettings so no saved layout or
    earlier test's tray widths leak in."""
    path = tmp_path / "prefs.ini"
    import PySide6.QtCore as qc
    import views.main_window as mw
    factory = lambda *a: QSettings(str(path), QSettings.IniFormat)  # noqa: E731
    monkeypatch.setattr(qc, "QSettings", factory)
    monkeypatch.setattr(mw, "QSettings", factory, raising=False)
    return _app


def _window(qapp):
    from views.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    qapp.processEvents()
    return w


def test_every_right_hand_tab_fits_the_trays_floor(qapp):
    w = _window(qapp)
    docks = {d.objectName(): d for d in w.findChildren(QDockWidget)}
    for name in ("tray_properties", "tray_bim", "tray_georef"):
        assert docks[name].minimumSizeHint().width() <= BUDGET, name
        for scroll in docks[name].findChildren(QScrollArea):
            inner = scroll.widget()
            if inner is not None and inner.isVisibleTo(docks[name]):
                assert inner.minimumSizeHint().width() <= BUDGET, (name, inner)
    w.close()


def test_the_parts_check_box_label_wraps_and_still_toggles(qapp):
    from views.tray import _wrapping_check
    check, row = _wrapping_check("Count identical parts only when the material matches too")
    row.resize(150, 80)
    assert row.minimumSizeHint().width() < 150
    assert not check.isChecked()
    from PySide6.QtWidgets import QLabel
    label = row.findChild(QLabel)
    label.mousePressEvent(None)
    assert check.isChecked()
