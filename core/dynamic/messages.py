# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 d1rty-pixel, moominot and IngeTrazo contributors.
# From d1rty-pixel's «Dynamic Components for IngeTrazo» (GPL-3.0,
# https://github.com/d1rty-pixel/ingetrazo-dynamic-components), unchanged.
"""Translatable messages for the pure modules (no Qt, no IngeTrazo).

A :class:`Msg` *is* the English text (``str()``, ``==`` and ``in`` see that), and
it also remembers the template and the values it was made from, so the UI can
translate it later (:func:`tr_msg`). Values may be messages themselves:
``Msg("Copy {index}: {error}", index=3, error=Msg("Division by zero"))``.
"""
from __future__ import annotations

_JSON_SCALARS = (str, int, float, bool, type(None))


class Msg(str):
    template: str
    params: dict

    def __new__(cls, template: str, **params):
        try:
            text = template.format(**params) if params else template
        except (KeyError, IndexError, ValueError):
            text = template
        obj = super().__new__(cls, text)
        obj.template = template
        obj.params = params
        return obj

    def __reduce__(self):  # copy/deepcopy/pickle keep the template
        return (_rebuild, (self.template, self.params))

    def to_json(self) -> dict:
        params = {}
        for key, value in self.params.items():
            if isinstance(value, Msg):
                params[key] = value.to_json()
            elif isinstance(value, _JSON_SCALARS):
                params[key] = value
            else:
                params[key] = str(value)
        return {"t": self.template, "p": params}

    @classmethod
    def from_json(cls, data, _depth: int = 0):
        """A message stored by :meth:`to_json`; None for anything malformed
        (stored data comes from documents we did not write)."""
        if _depth > 8 or not isinstance(data, dict):
            return None
        template = data.get("t")
        params = data.get("p", {})
        if params is None:
            params = {}
        if not isinstance(template, str) or len(template) > 4096 \
                or not isinstance(params, dict) or len(params) > 32:
            return None
        clean = {}
        for key, value in params.items():
            if not isinstance(key, str) or not key.isidentifier():
                return None
            if isinstance(value, dict):
                value = cls.from_json(value, _depth + 1)
                if value is None:
                    return None
            elif not isinstance(value, _JSON_SCALARS):
                return None
            elif isinstance(value, str) and len(value) > 4096:
                value = value[:4096]
            clean[key] = value
        return cls(template, **clean)


def _rebuild(template, params):
    return Msg(template, **params)


def text_of(exc) -> str:
    """The message of an exception: its ``msg`` when it carries one."""
    msg = getattr(exc, "msg", None)
    return msg if isinstance(msg, str) else str(exc)


class MessageError(Exception):
    """Base for errors that carry a :class:`Msg` as ``.msg``."""

    def __init__(self, msg="", *args):
        if not isinstance(msg, Msg):
            msg = Msg(str(msg))      # no params: the text is not formatted
        super().__init__(msg, *args)
        self.msg = msg

    def __str__(self) -> str:
        return str.__str__(self.msg)


def N_(text: str) -> str:
    """Marks a constant for the translation catalogs; returns it unchanged.
    Message parameters that are such words are translated with the message."""
    _MARKED.add(text)
    return text


#: The words :func:`N_` marked: message parameters translated with it.
_MARKED: set = set()


def tr_msg(msg) -> str:
    """``msg`` in the interface language: its template looked up in the
    catalogue, its parameters filled in — a nested message, or a word
    :func:`N_` marked, translated too; any other value as it is (a part's
    name is not a word to translate)."""
    from core.i18n import tr
    if not isinstance(msg, Msg):
        return str(msg)
    params = {}
    for key, value in msg.params.items():
        if isinstance(value, Msg):
            params[key] = tr_msg(value)
        elif isinstance(value, str) and value in _MARKED:
            params[key] = tr(value)
        else:
            params[key] = value
    return tr(msg.template, **params)
