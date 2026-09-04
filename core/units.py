# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Length formatting shared by the model's dimensions and the sheet cotas.

Model lengths are metres. A dimension style (or a sheet cota) picks how
they read: metric (``m`` / ``cm`` / ``mm``), decimal imperial (``in``,
``ft``, ``ft-in``) or fractional imperial the way a carpenter writes it
(``in-frac`` → ``1 1/2"``, ``ft-in-frac`` → ``1'6 1/2"``). For the
fractional forms the precision field picks the finest denominator:
0 → whole inches, 1 → 1/4, 2 → 1/16, 3 → 1/32, 4 → 1/64.
"""
from __future__ import annotations

from fractions import Fraction

IN_M = 0.0254
FT_M = 0.3048

#: Every unit a dimension style may name, in the order the pickers show.
UNIT_CHOICES = ("m", "cm", "mm", "in", "ft", "ft-in", "in-frac", "ft-in-frac")

_FRAC_DENOMS = {0: 1, 1: 4, 2: 16, 3: 32, 4: 64}


def _frac_inches(inches: float, decimals: int) -> str:
    """``6.5`` → ``6 1/2``; ``0.75`` → ``3/4``; ``6.0`` → ``6``."""
    denom = _FRAC_DENOMS.get(max(0, min(4, int(decimals))), 16)
    total = Fraction(round(inches * denom)), denom
    q = Fraction(total[0], total[1])
    whole = int(q)
    rest = q - whole
    if rest == 0:
        return str(whole)
    if whole == 0:
        return f"{rest.numerator}/{rest.denominator}"
    return f"{whole} {rest.numerator}/{rest.denominator}"


def format_length(metres: float, units: str = "m", decimals: int = 2) -> str:
    n = max(0, min(6, int(decimals)))
    u = units or "m"
    if u == "in":
        return f"{metres / IN_M:.{n}f}\""
    if u == "ft":
        return f"{metres / FT_M:.{n}f}'"
    if u in ("ft-in", "ft-in-frac", "in-frac"):
        sign = "-" if metres < 0 else ""
        total_in = abs(metres) / IN_M
        if u == "in-frac":
            return f"{sign}{_frac_inches(total_in, n)}\""
        feet = int(total_in // 12)
        inches = total_in - feet * 12
        if u == "ft-in":
            if round(inches, n) >= 12:
                feet, inches = feet + 1, 0.0
            return f"{sign}{feet}'{inches:.{n}f}\""
        txt = _frac_inches(inches, n)
        if txt == "12":
            feet, txt = feet + 1, "0"
        return f"{sign}{feet}'{txt}\""
    factor = {"m": 1.0, "cm": 100.0, "mm": 1000.0}.get(u, 1.0)
    return f"{metres * factor:.{n}f} {u if u in ('m', 'cm', 'mm') else 'm'}"
