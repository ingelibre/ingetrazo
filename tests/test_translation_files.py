# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every translation file loads and keeps the placeholders of its source.

Contributed catalogs arrive hand-edited: a missing comma makes the whole
file unreadable (the language silently falls back to English), and a
translated placeholder — ``{名称}`` for ``{name}`` — makes ``tr`` fall back
to English for that message. Both happened with the first Chinese file.
"""
import json
import string

import pytest

from core.i18n import _I18N_DIR, LANGUAGE_NAMES, available_languages

_FILES = sorted(_I18N_DIR.glob("*.json"))


def _fields(text):
    return sorted({f for _, f, _, _ in string.Formatter().parse(text) if f})


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.stem)
def test_file_is_valid_json_map(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in data.items())


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.stem)
def test_placeholders_survive_translation(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    bad = [k for k, v in data.items() if _fields(k) != _fields(v)]
    assert not bad, f"{len(bad)} entries change their {{placeholders}}: {bad[:3]}"


def test_every_language_has_a_menu_name():
    assert set(available_languages()) <= set(LANGUAGE_NAMES)


@pytest.mark.parametrize("path", [p for p in _FILES
                                  if p.stem not in ("en", "es")],
                         ids=lambda p: p.stem)
def test_every_language_has_every_message(path):
    """A message added in Spanish and English but in no other catalog reads
    in English there with no warning: 21 strings of Join Segments and Zoom
    Window sat untranslated in French and Polish until a review of the
    language PRs happened on them (17-10)."""
    source = json.loads((_I18N_DIR / "es.json").read_text(encoding="utf-8"))
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in source if k not in data]
    assert not missing, f"{len(missing)} messages missing: {missing[:3]}"
