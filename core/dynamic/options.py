# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 moominot and IngeTrazo contributors.
# Adapted from moominot's «dc_tools» extension (GPL-3.0-or-later,
# https://github.com/moominot/ingetrazo-skp-dc-import).
"""The options a dynamic component shows its users (a «Component
Options» dialog): which attributes, how they read, and how what the user
types becomes the value a .skp file would store.

Pure Python, no Qt: the panel (``views/dynamic_panel.py``) only draws what this returns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, unquote_to_bytes

from .evaluate import _num
from .model import INCH

UNIT_SUFFIX = {"INCHES": "in", "FEET": "ft", "MILLIMETERS": "mm",
               "CENTIMETERS": "cm", "METERS": "m"}


@dataclass
class Option:
    name: str                       # attribute name (lower case)
    label: str
    access: str                     # TEXTBOX, LIST, VIEW
    units: str                      # a length unit, DEGREES, PERCENT, INTEGER, FLOAT, STRING
    value: object                   # stored value (lengths in inches)
    choices: list = field(default_factory=list)    # [(label, raw value text)]


def _decode(text: str) -> str:
    """.skp files percent-encode option text in Latin-1 («Separaci%F3»)."""
    try:
        return unquote_to_bytes(text).decode("utf-8")
    except UnicodeDecodeError:
        return unquote(text, encoding="latin-1")


def parse_choices(options_text) -> list:
    """«&CORRERERA=1&PRACTICABLE=0&» → [("CORRERERA", "1"), …]. A value may
    be a formula («=e3_angle»)."""
    out = []
    for chunk in str(options_text or "").split("&"):
        if not chunk or "=" not in chunk:
            continue
        label, value = chunk.split("=", 1)
        out.append((_decode(label), _decode(value)))
    return out


def option_units(attrs: dict, name: str) -> str:
    u = str(attrs.get(f"_{name}_units") or "").upper()
    if name in ("lenx", "leny", "lenz", "x", "y", "z") and u in ("", "DEFAULT"):
        u = str(attrs.get("_lengthunits") or "CENTIMETERS").upper()
    if u in ("", "DEFAULT"):
        fu = str(attrs.get(f"_{name}_formulaunits") or "").upper()
        u = fu if fu in INCH else (u or "STRING")
    return u or "STRING"


# The order of the «add attribute» list: the predefined attributes
# first, in these groups; every custom one after them, alphanumerically.
PREDEFINED_ORDER = (
    "name", "summary", "description", "itemcode",            # Component Info
    "x", "y", "z",                                           # Position
    "lenx", "leny", "lenz",                                  # Size
    "rotx", "roty", "rotz",                                  # Rotation
    "material", "scaletool", "hidden", "onclick", "copies",  # Behaviors
    "imageurl", "dialogwidth", "dialogheight",               # Form Design
)


def _natural(text: str) -> list:
    """«b2» before «b10»: digits compare as numbers, case is ignored."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text.lower())]


def option_sort_key(name: str) -> tuple:
    n = name.lower()
    if n in PREDEFINED_ORDER:
        return (0, PREDEFINED_ORDER.index(n), [])
    return (1, 0, _natural(name))


def options_of(attrs: dict) -> list:
    """The root's user-facing options, in the format's order: the predefined
    attributes (Name, Summary, Description, ItemCode, X…, LenX…, RotX…,
    Material, ScaleTool, Hidden, onClick, Copies, ImageURL…) as its list
    shows them, then the custom ones alphanumerically (authors prefix them
    «a_», «b_» to sort them)."""
    out = []
    for key in sorted(attrs):
        if not (key.startswith("_") and key.endswith("_access")) or key.startswith("_inst_"):
            continue
        access = str(attrs.get(key) or "").upper()
        if access not in ("TEXTBOX", "LIST", "VIEW"):
            continue
        name = key[1:-len("_access")]
        if not name or name.startswith("_"):
            continue
        label = attrs.get(f"_{name}_formlabel") or attrs.get(f"_{name}_label") or name
        out.append(Option(name, str(label), access, option_units(attrs, name),
                          attrs.get(name), parse_choices(attrs.get(f"_{name}_options"))
                          if access == "LIST" else []))
    out.sort(key=lambda o: option_sort_key(o.name))
    return out


# ---- stored value ⇄ what the user reads and types -----------------------------

def _fmt(n: float) -> str:
    text = f"{n:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def display(opt: Option, value=None) -> str:
    v = opt.value if value is None else value
    n = _num(v)
    if opt.units in INCH and isinstance(n, float):
        return f"{_fmt(n / INCH[opt.units])} {UNIT_SUFFIX[opt.units]}"
    if opt.units == "PERCENT" and isinstance(n, float):
        return f"{_fmt(n * 100)} %"
    if opt.units == "DEGREES" and isinstance(n, float):
        return f"{_fmt(n)}°"
    if isinstance(n, float):
        return _fmt(n)
    return "" if v is None else str(v)


def parse(opt: Option, text: str):
    """What the user typed → the value to store (lengths in inches).
    Raises ValueError for a number that does not read."""
    t = str(text).strip().replace(",", ".")
    for suffix in ("mm", "cm", "in", "ft", "m", "%", "°"):
        if t.lower().endswith(suffix):
            unit_typed = suffix
            t = t[: -len(suffix)].strip()
            break
    else:
        unit_typed = None
    if opt.units in INCH:
        n = float(t)
        typed = {"mm": "MILLIMETERS", "cm": "CENTIMETERS", "m": "METERS",
                 "in": "INCHES", "ft": "FEET"}.get(unit_typed or "", opt.units)
        return n * INCH[typed]
    if opt.units == "PERCENT":
        return float(t) / 100.0
    if opt.units in ("DEGREES", "FLOAT"):
        return float(t)
    if opt.units == "INTEGER":
        return float(int(round(float(t))))
    return str(text)


def current_choice(opt: Option) -> int:
    """Index of the choice matching the stored value (-1 when none does)."""
    v = opt.value
    n = _num(v)
    for i, (_label, raw) in enumerate(opt.choices):
        if str(raw) == str(v):
            return i
        rn = _num(raw)
        if isinstance(n, float) and isinstance(rn, float) and abs(n - rn) < 1e-9:
            return i
    return -1
