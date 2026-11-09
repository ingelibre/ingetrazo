# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Every status-bar hint has its translation in every language.

The Push/Pull hint was shortened in English and its translations kept the
old, longer key, so the Spanish status bar read «Empujar / Tirar — Click a
face and move.» (caza 2, 16-10)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from views.status_hints import HINTS

_I18N = Path(__file__).resolve().parent.parent / "i18n"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


@pytest.mark.parametrize("lang", sorted(p.stem for p in _I18N.glob("*.json")
                                         if p.stem != "en"))   # English is the key
def test_every_hint_is_translated(lang):
    table = json.loads((_I18N / f"{lang}.json").read_text(encoding="utf-8"))
    missing = sorted({s for v in HINTS.values() for s in _strings(v)
                      if s not in table})
    assert missing == [], f"{lang}: {missing}"
