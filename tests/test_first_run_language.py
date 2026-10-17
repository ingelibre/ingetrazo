# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""On first run the interface takes the system language whenever a catalog
for it ships, not only for Spanish and Portuguese: a German, French,
Italian, Polish, Russian, Indonesian or Chinese system opened in English
although its catalog was right there in ``i18n/``."""
from __future__ import annotations

import pytest

from core import i18n

SHIPPED = ["de", "en", "es", "fr", "id", "it", "pl", "pt-BR", "ru", "zh-CN"]


@pytest.mark.parametrize("locale_name, expected", [
    ("es_ES", "es"), ("es_MX", "es"),
    ("pt_BR", "pt-BR"),
    ("pt_PT", "pt-BR"),        # every Portuguese locale, until a pt-PT exists
    ("de_DE", "de"), ("de_AT", "de"), ("de_CH", "de"),
    ("fr_FR", "fr"), ("fr_CA", "fr"),
    ("it_IT", "it"), ("pl_PL", "pl"), ("ru_RU", "ru"), ("id_ID", "id"),
    ("zh_CN", "zh-CN"), ("zh_SG", "zh-CN"),
    ("zh_TW", "en"), ("zh_HK", "en"),  # Traditional: no catalog yet
    ("en_US", "en"), ("nl_NL", "en"), ("C", "en"), ("", "en"),
])
def test_the_system_locale_picks_its_catalog(locale_name, expected):
    assert i18n.language_for_locale(locale_name, SHIPPED) == expected


def test_a_language_without_a_catalog_falls_back_to_english():
    assert i18n.language_for_locale("de_DE", ["en", "es"]) == "en"


def test_first_run_on_a_german_system_opens_in_german(monkeypatch):
    import main
    from PySide6.QtCore import QLocale

    class _NoSaved:
        def value(self, _key):
            return None

    class _GermanSystem(QLocale):
        @staticmethod
        def system():
            return QLocale(QLocale.German, QLocale.Germany)

    picked = []
    monkeypatch.setattr(main, "QSettings", _NoSaved)
    monkeypatch.setattr(main, "QLocale", _GermanSystem)
    monkeypatch.setattr(main.i18n, "set_language", picked.append)
    monkeypatch.setattr(main, "_install_qt_translator", lambda _lang: None)
    main._init_language()
    assert picked == ["de"]
