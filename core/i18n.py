# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Lightweight JSON-based UI translation.

English is the *source* language: the keys passed to :func:`tr` are the English
strings themselves, so any untranslated string falls back to readable English
instead of a cryptic key. Other languages live as flat ``{english: translation}``
maps in ``i18n/<lang>.json`` (``i18n/en.json`` is the identity map, kept empty).

This deliberately avoids Qt's ``.ts``/``.qm`` + Linguist toolchain to stay
dependency-free, matching the project's minimal stack.

Usage::

    from core.i18n import tr
    label = tr("File")                       # -> "Archivo" in Spanish
    msg = tr("Imported {name}", name="a.obj")  # interpolates after lookup
"""
from __future__ import annotations

import json
from pathlib import Path

from core.paths import app_root

_I18N_DIR = app_root() / "i18n"

#: How each language names itself in the Language menu and Preferences.
LANGUAGE_NAMES = {"en": "English", "es": "Español",
                  "pt-BR": "Português (Brasil)", "zh-CN": "简体中文"}

_catalog: dict[str, str] = {}
_lang = "en"


def available_languages() -> list[str]:
    """Language codes with a JSON file in ``i18n/`` (e.g. ``["en", "es"]``)."""
    if not _I18N_DIR.is_dir():
        return ["en"]
    return sorted(p.stem for p in _I18N_DIR.glob("*.json"))


def set_language(lang: str) -> None:
    """Activate ``lang`` for subsequent :func:`tr` calls.

    English (or a missing/broken file) loads an empty catalog, so ``tr`` returns
    the source string unchanged.
    """
    global _catalog, _lang
    _lang = lang or "en"
    path = _I18N_DIR / f"{_lang}.json"
    if _lang == "en" or not path.exists():
        _catalog = {}
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _catalog = {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError):
        _catalog = {}


def current_language() -> str:
    return _lang


_reverse: dict[str, str] | None = None
_reverse_of: dict | None = None


def source_of(text: str) -> str:
    """The English source of a string ``tr`` produced — for a key that
    must not change with the language (a remembered keyboard shortcut).
    Text that is not a translation comes back as it is."""
    global _reverse, _reverse_of
    if _reverse_of is not _catalog:
        _reverse = {v: k for k, v in _catalog.items()}
        _reverse_of = _catalog
    return _reverse.get(text, text)


def tr(text: str, /, **kwargs) -> str:
    """Translate ``text`` into the active language; interpolate ``kwargs``.

    ``.format`` runs only when keyword arguments are given, so source strings
    that contain literal braces are safe when called without kwargs.
    """
    out = _catalog.get(text, text)
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            out = text.format(**kwargs)
    return out
