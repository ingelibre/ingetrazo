# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 moominot and IngeTrazo contributors.
# Adapted from moominot's «dc_tools» extension (GPL-3.0-or-later,
# https://github.com/moominot/ingetrazo-skp-dc-import).
"""Evaluate dynamic component formulas over a :class:`Part` tree.

Values are kept the way .skp files store them: lengths in inches, angles in
degrees. A formula sees lengths in its component's ``_lengthunits`` and its
result is converted back (a formula «4» in a CENTIMETERS component is 4 cm).
"""
from __future__ import annotations

from . import formula as F
from .model import INCH, Part

_MISSING = object()


class EvalError(Exception):
    pass


def _num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return v


class Evaluator:
    """``value(part, attr)`` → the attribute's value, formulas evaluated.

    ``use_stored=True`` makes references read the STORED values instead of
    re-evaluating them (each formula checked on its own)."""

    def __init__(self, root: Part, overrides: dict | None = None,
                 use_stored: bool = False):
        self.root = root
        self.overrides = overrides or {}       # {(id(part), attr): native value}
        self.use_stored = use_stored
        self.memo: dict = {}
        self.active: set = set()
        self.errors: list = []
        self._parsed: dict = {}

    # -- names -----------------------------------------------------------------
    def resolve(self, part: Part, owner: str) -> Part | None:
        owner = owner.lower()
        if owner == "self":
            return part
        if owner == "parent":
            return part.parent
        # A part's own name first; then, in the same scope, the placement
        # name it carries besides (see Part.aliases): «MUNT07» still finds
        # the part named so before another placed as «MUNT1» of the same
        # definition.
        for named in (lambda p: p is not None and p.name.lower() == owner,
                      lambda p: p is not None and owner in p.aliases):
            if named(part):
                return part
            p = part.parent
            while p is not None:                    # ancestors
                if named(p):
                    return p
                p = p.parent
            if part.parent is not None:             # siblings
                for s in part.parent.children:
                    if named(s):
                        return s
            for c in part.children:                 # children
                if named(c):
                    return c
        # Nothing further: a name out of this scope fails in .skp files too
        # («failed to parse march sup!leny inside Group.leny») and leaves the
        # attribute as it was.
        return None

    # -- units -----------------------------------------------------------------
    def to_formula(self, viewer: Part, target: Part, attr: str, v):
        """A native value as ``viewer``'s formulas see it."""
        if target.units(attr) == "LENGTH":
            n = _num(v)
            if isinstance(n, float):
                return n / INCH[viewer.length_unit()]
        return v

    def from_formula(self, part: Part, attr: str, v):
        u = part.units(attr)
        if u == "LENGTH":
            n = _num(v)
            if isinstance(n, float):
                return n * INCH[part.length_unit()]
        if u == "INTEGER":
            n = _num(v)
            if isinstance(n, float):
                return float(int(n))
        return v

    # -- values ----------------------------------------------------------------
    def parsed(self, text: str):
        f = self._parsed.get(text)
        if f is None:
            f = self._parsed[text] = F.parse(text)
        return f

    def stored(self, part: Part, attr: str):
        key = (id(part), attr)
        if key in self.overrides:
            return self.overrides[key]
        v = part.stored(attr)
        if v is None and attr in ("copy", "copies", "rotx", "roty", "rotz", "x", "y", "z"):
            return 0.0
        return v

    def fallback(self, part: Part, attr: str):
        """The value of an attribute whose formula failed: what it was."""
        return self.stored(part, attr)

    def value(self, part: Part, attr: str):
        attr = attr.lower()
        key = (id(part), attr)
        if key in self.memo:
            return self.memo[key]
        if key in self.overrides:
            return self.overrides[key]
        text = part.formula(attr)
        if text is None or key in self.active:
            return self.stored(part, attr)
        self.active.add(key)
        try:
            result = F.evaluate(self.parsed(text), self._lookup(part))
            v = self.from_formula(part, attr, result)
        except F.FormulaError as exc:
            self.errors.append((part, attr, text, str(getattr(exc, "msg", exc))))
            v = self.fallback(part, attr)
        except EvalError as exc:
            self.errors.append((part, attr, text, str(exc)))
            v = self.fallback(part, attr)
        finally:
            self.active.discard(key)
        self.memo[key] = v
        return v

    def _lookup(self, part: Part):
        def lookup(owner, attr):
            target = self.resolve(part, owner)
            if target is None:
                raise EvalError(f"no part named {owner!r}")
            if self.use_stored and target is not part or (self.use_stored and attr != "copy"):
                v = self.stored(target, attr)
            else:
                v = self.value(target, attr)
            if v is None:
                v = 0.0
            return self.to_formula(part, target, attr, _num(v) if attr != "name" else v)
        return lookup
