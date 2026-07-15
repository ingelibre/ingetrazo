# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Saved XYZ sources (QGIS-style): add a named source once and it is always
in the source menu, across sessions, until explicitly removed."""
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

from core.scene import Scene  # noqa: E402
from views.tray import BaseMapPanel  # noqa: E402

URL = "https://tiles.example.com/drone/{z}/{x}/{y}.png"


class _Win:
    class viewport:
        scene = Scene()


@pytest.fixture(autouse=True)
def _isolated_settings():
    prev_org = QCoreApplication.organizationName()
    prev_app = QCoreApplication.applicationName()
    QCoreApplication.setOrganizationName("IngeTrazoTest")
    QCoreApplication.setApplicationName("basemap-prefs-test")
    QSettings().clear()
    yield
    QSettings().clear()
    QCoreApplication.setOrganizationName(prev_org)
    QCoreApplication.setApplicationName(prev_app)


def test_named_source_appears_forever_in_the_menu():
    panel = BaseMapPanel(_Win())
    assert panel.add_custom_source("Dron Yanque", URL)
    # selected right away, with its own cache-safe id
    assert panel._source.currentData() == "custom-dron-yanque"
    src = panel._current_source()
    assert src.url_template == URL and src.name == "Dron Yanque"

    fresh = BaseMapPanel(_Win())                 # "next session"
    assert fresh._source.findText("Dron Yanque") >= 0   # always in the menu
    assert fresh._source.currentData() == "custom-dron-yanque"  # remembered
    assert fresh._current_source().url_template == URL


def test_several_sources_coexist_and_upsert_by_name():
    panel = BaseMapPanel(_Win())
    assert panel.add_custom_source("Dron Yanque", URL)
    assert panel.add_custom_source("IGN Perú", "https://ign.example/{z}/{x}/{y}")
    assert panel.add_custom_source("Dron Yanque",          # same name = update
                                   "https://v2.example/{z}/{x}/{y}")
    fresh = BaseMapPanel(_Win())
    assert fresh._source.findText("Dron Yanque") >= 0
    assert fresh._source.findText("IGN Perú") >= 0
    assert fresh._custom_entries["custom-dron-yanque"]["url"] == \
        "https://v2.example/{z}/{x}/{y}"
    assert len(fresh._custom_entries) == 2               # no duplicates


def test_url_without_placeholders_is_rejected():
    panel = BaseMapPanel(_Win())
    assert not panel.add_custom_source("Mala", "https://example.com/tile.png")
    assert panel._custom_entries == {}


def test_remove_forgets_the_source():
    panel = BaseMapPanel(_Win())
    panel.add_custom_source("Dron Yanque", URL)
    panel._remove_current_custom()
    assert panel._source.findText("Dron Yanque") < 0
    fresh = BaseMapPanel(_Win())
    assert fresh._source.findText("Dron Yanque") < 0     # gone for good


def test_legacy_single_url_pref_migrates_to_a_named_source():
    QSettings().setValue("basemap/custom_url", URL)      # pre-rename pref
    panel = BaseMapPanel(_Win())
    assert panel._source.findText("XYZ personalizado") >= 0
    sid = panel._source.itemData(panel._source.findText("XYZ personalizado"))
    assert panel._custom_entries[sid]["url"] == URL
    assert QSettings().value("basemap/custom_url", "", type=str) == ""
