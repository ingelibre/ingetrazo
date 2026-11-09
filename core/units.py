# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Units: how a stored value is shown and how a typed one is read.

The model stores metres (and square metres, cubic metres, radians); the
units only change what is SHOWN and what a bare typed number MEANS, never
a stored value. One table (``UNITS``) holds every unit, ``format_*`` turn
a base value into text, ``parse`` turns text into a base value or a
message, and ``convert`` moves a number between units of one kind.

Model lengths are metres. A dimension style (or a sheet cota) picks how
they read: metric (``m`` / ``cm`` / ``mm``), decimal imperial (``in``,
``ft``, ``ft-in``) or fractional imperial the way a carpenter writes it
(``in-frac`` → ``1 1/2"``, ``ft-in-frac`` → ``1'6 1/2"``). For the
fractional forms the precision field picks the finest denominator:
0 → whole inches, 1 → 1/4, 2 → 1/16, 3 → 1/32, 4 → 1/64.
"""
from __future__ import annotations

import math
import re
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction

IN_M = 0.0254
FT_M = 0.3048

#: Every unit a dimension style may name, in the order the pickers show.
UNIT_CHOICES = ("m", "cm", "mm", "in", "ft", "ft-in", "in-frac", "ft-in-frac")

_FRAC_DENOMS = {0: 1, 1: 4, 2: 16, 3: 32, 4: 64}


# ---- The table of units -------------------------------------------------------
#
# One row per unit: what it measures, how many BASE units one of it is
# (metre, square metre, cubic metre, radian), the symbol it is shown with
# and the words it is typed as. Adding a unit is one row here; no tool
# carries a conversion factor of its own. The inch and the foot are exact
# by definition; the US survey foot (1200/3937 m, about 2 parts per million
# longer) is a separate row, for survey files only.

@dataclass(frozen=True)
class Unit:
    code: str
    kind: str          # "length" | "area" | "volume" | "angle"
    factor: float      # base units per one of this unit
    symbol: str
    aliases: tuple = ()


_TABLE = (
    # length — base: metre
    ("mm", "length", 1e-3, "mm",
     ("mm", "millimetre", "millimetres", "millimeter", "millimeters",
      "milímetro", "milímetros", "milimetro", "milimetros")),
    ("cm", "length", 1e-2, "cm",
     ("cm", "centimetre", "centimetres", "centimeter", "centimeters",
      "centímetro", "centímetros", "centimetro", "centimetros")),
    ("m", "length", 1.0, "m",
     ("m", "metre", "metres", "meter", "meters", "metro", "metros")),
    ("km", "length", 1e3, "km",
     ("km", "kilometre", "kilometres", "kilometer", "kilometers",
      "kilómetro", "kilómetros", "kilometro", "kilometros")),
    ("in", "length", IN_M, '"',
     ('"', "in", "inch", "inches", "pulgada", "pulgadas")),
    ("ft", "length", FT_M, "'",
     ("'", "ft", "foot", "feet", "pie", "pies")),
    ("yd", "length", 0.9144, "yd", ("yd", "yard", "yards", "yarda", "yardas")),
    ("mi", "length", 1609.344, "mi", ("mi", "mile", "miles", "milla", "millas")),
    ("us-ft", "length", 1200.0 / 3937.0, "ft (US)", ("us-ft", "usft", "survey-ft")),
    # area — base: square metre
    ("mm2", "area", 1e-6, "mm²", ("mm2", "mm²", "mm^2")),
    ("cm2", "area", 1e-4, "cm²", ("cm2", "cm²", "cm^2")),
    ("m2", "area", 1.0, "m²", ("m2", "m²", "m^2")),
    ("ha", "area", 1e4, "ha", ("ha", "hectare", "hectares", "hectárea", "hectáreas",
                               "hectarea", "hectareas")),
    ("in2", "area", IN_M ** 2, "in²", ("in2", "in²", "in^2")),
    ("ft2", "area", FT_M ** 2, "ft²", ("ft2", "ft²", "ft^2")),
    ("yd2", "area", 0.9144 ** 2, "yd²", ("yd2", "yd²", "yd^2")),
    ("acre", "area", 4046.8564224, "acre", ("acre", "acres", "ac")),
    # volume — base: cubic metre
    ("cm3", "volume", 1e-6, "cm³", ("cm3", "cm³", "cm^3", "cc")),
    ("l", "volume", 1e-3, "L", ("l", "litre", "litres", "liter", "liters",
                                "litro", "litros")),
    ("m3", "volume", 1.0, "m³", ("m3", "m³", "m^3")),
    ("in3", "volume", IN_M ** 3, "in³", ("in3", "in³", "in^3")),
    ("ft3", "volume", FT_M ** 3, "ft³", ("ft3", "ft³", "ft^3")),
    ("yd3", "volume", 0.9144 ** 3, "yd³", ("yd3", "yd³", "yd^3")),
    ("gal", "volume", 3.785411784e-3, "gal", ("gal", "gallon", "gallons",
                                              "galón", "galones", "galon")),
    # angle — base: radian
    ("deg", "angle", math.pi / 180.0, "°", ("°", "deg", "degree", "degrees",
                                            "grado", "grados")),
    ("rad", "angle", 1.0, "rad", ("rad", "radian", "radians", "radián",
                                  "radianes")),
    ("grad", "angle", math.pi / 200.0, "gon", ("gon", "grad", "gradian",
                                               "gradians")),
)

#: ``code`` → :class:`Unit`.
UNITS = {row[0]: Unit(*row) for row in _TABLE}

#: Every typed word (lower case) → its unit.
_ALIASES = {a.lower(): UNITS[row[0]] for row in _TABLE for a in row[4]}

#: The base unit of each kind, the one the model stores.
BASE_UNIT = {"length": "m", "area": "m2", "volume": "m3", "angle": "rad"}


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """``value`` in ``from_unit``, expressed in ``to_unit`` (codes of the
    table). Units of different kinds raise ``ValueError``: a length is
    never an area."""
    a, b = UNITS[from_unit], UNITS[to_unit]
    if a.kind != b.kind:
        raise ValueError(f"cannot convert {a.kind} to {b.kind}")
    if a.code == b.code:
        return float(value)
    return float(value) * a.factor / b.factor


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


def _fixed(value: float, n: int) -> str:
    """``value`` to ``n`` decimals the way a person rounds it: half up on
    the number as written (1.2345 m is 123.45 cm, shown to one decimal
    «123.5 cm», not the «123.4» of its binary 123.4499…), and never
    «-0.00»: a value that rounds to zero has no sign to show."""
    from decimal import ROUND_HALF_UP, Decimal
    if not math.isfinite(value):
        return f"{value}"
    exact = Decimal(f"{value:.12g}")
    txt = f"{exact.quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP):f}"
    return txt[1:] if txt.startswith("-") and float(txt) == 0 else txt


def format_length(metres: float, units: str = "m", decimals: int = 2,
                  show_unit: bool = True) -> str:
    """``metres`` in ``units`` to ``decimals``. ``show_unit=False`` leaves
    the bare number — «1.30», not «1.30 m» — for drawings that state the
    unit once, in the title block or a note (#374, #637). Feet and inches
    together keep their marks: without them 5'3" reads «5 3»."""
    n = max(0, min(6, int(decimals)))
    u = units or "m"
    metres = float(metres)
    if not math.isfinite(metres):
        return "—"                       # never «nan m», never a crash
    if u == "in":
        return f"{_fixed(metres / IN_M, n)}" + ('"' if show_unit else "")
    if u == "ft":
        return f"{_fixed(metres / FT_M, n)}" + ("'" if show_unit else "")
    if u in ("ft-in", "ft-in-frac", "in-frac"):
        sign = "-" if metres < 0 else ""
        total_in = abs(metres) / IN_M
        if u == "in-frac":
            txt = _frac_inches(total_in, n)
            return (f"{sign if txt != '0' else ''}{txt}"
                    + ('"' if show_unit else ""))
        feet = int(total_in // 12)
        inches = total_in - feet * 12
        if u == "ft-in":
            if round(inches, n) >= 12:
                feet, inches = feet + 1, 0.0
            txt = f"{inches:.{n}f}"
            zero = feet == 0 and float(txt) == 0
            return f"{'' if zero else sign}{feet}'{txt}\""
        txt = _frac_inches(inches, n)
        if txt == "12":
            feet, txt = feet + 1, "0"
        zero = feet == 0 and txt == "0"
        return f"{'' if zero else sign}{feet}'{txt}\""
    row = UNITS.get(u)
    if row is not None and row.kind == "length" and u not in ("in", "ft"):
        number = _fixed(metres / row.factor, n)
        return f"{number} {row.symbol}" if show_unit else number
    return f"{_fixed(metres, n)} m" if show_unit else _fixed(metres, n)


def _length_per_metre(units: str) -> float:
    """How many of ``units`` are in one metre. Feet-and-inches and
    fractional feet count as decimal feet; fractional inches as decimal
    inches — a spinbox has one number, and the sheet text keeps the
    carpenter form."""
    u = units or "m"
    if u in ("in", "in-frac"):
        return 1.0 / IN_M
    if u in ("ft", "ft-in", "ft-in-frac"):
        return 1.0 / FT_M
    return {"m": 1.0, "cm": 100.0, "mm": 1000.0}.get(u, 1.0)


def length_number(metres: float, units: str = "m") -> float:
    """The number a length spinbox shows for a value stored in metres."""
    return float(metres) * _length_per_metre(units)


def metres_from_number(number: float, units: str = "m") -> float:
    """The metres a length spinbox's number stands for."""
    return float(number) / _length_per_metre(units)


def length_suffix(units: str = "m") -> str:
    """The suffix on that spinbox."""
    u = units or "m"
    if u in ("in", "in-frac"):
        return '"'
    if u in ("ft", "ft-in", "ft-in-frac"):
        return "'"
    if u == "cm":
        return " cm"
    if u == "mm":
        return " mm"
    return " m"


def format_signed_level(metres: float, units: str = "m",
                        decimals: int = 2) -> str:
    """A level mark's number. Metres stay «+0.15» / «-0.30» / «±0.00» —
    the text already printed on every sheet. Any other unit is that same
    sign in front of :func:`format_length` («+0'5.91"», «±0.00 cm»)."""
    u = units or "m"
    d = max(0, int(decimals))
    v = float(metres)
    if u == "m":
        if round(v, d) == 0:
            return "±" + f"{0.0:.{d}f}"
        return f"{v:+.{d}f}"
    shown = format_length(abs(v), u, d)
    if shown == format_length(0.0, u, d):
        return "±" + shown
    if v < 0:
        return format_length(v, u, d)
    return "+" + shown


# ---- The model's units (issue #33, @pacaeiro) -------------------------------
#
# «Myself, when doing architecture I work in meters and with mechanical
# pieces all the work is in millimeters.» The document carries the unit a
# bare number is typed in and every readout is shown in (``Scene.units``);
# the live scene is bound here once so tools and panels — which mostly have
# no scene at hand — format through ``fmt_len``/``fmt_area``.

DEFAULT_MODEL_UNITS = {"length": "m", "precision": 2}

# English source strings, translated where they are shown (issue #65: the
# labels were written in Spanish, so an English UI showed Spanish).
UNIT_LABELS = {
    "m": "Metres (m)", "cm": "Centimetres (cm)", "mm": "Millimetres (mm)",
    "in": "Decimal inches (in)", "ft": "Decimal feet (ft)",
    "ft-in": "Feet and inches (1\'6\")", "in-frac": "Fractional inches",
    "ft-in-frac": "Fractional feet and inches",
}

#: Metres per typed unit when the number carries no unit of its own.
_BARE_SCALE = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": IN_M, "ft": FT_M,
               "ft-in": IN_M, "in-frac": IN_M, "ft-in-frac": IN_M}

_SCENE = None


def bind_scene(scene) -> None:
    """The scene whose ``units`` the formatters read (the viewport's; a
    document loads INTO that object, so one binding lasts the session)."""
    global _SCENE
    _SCENE = scene


def model_units_of(scene) -> dict:
    """The validated units of a scene — or of a raw document payload (a
    dict), which is how the .igz loader reads them."""
    if isinstance(scene, dict):
        u = scene.get("units")
    else:
        u = getattr(scene, "units", None) if scene is not None else None
    if isinstance(u, dict) and u.get("length") in _BARE_SCALE:
        out = {"length": u["length"], "precision": _precision(u.get("precision"), 2)}
        for key, ok in _OPTIONAL.items():
            if key in u and ok(u[key]) and u[key] != _OPTIONAL_DEFAULTS[key]:
                out[key] = int(u[key]) if key.endswith("precision") else u[key]
        return out
    return dict(DEFAULT_MODEL_UNITS)


def _precision(value, default: int) -> int:
    try:
        return max(0, min(6, int(value)))
    except (TypeError, ValueError):
        return default


def _is_precision(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 6


def _of_kind(kind: str):
    return lambda code: code == "auto" or (
        isinstance(code, str) and code in UNITS and UNITS[code].kind == kind)


#: The units panel's settings beyond the length (issue #33's two keys): each
#: optional, absent = its default, so a document that never touched them —
#: and every .igz written before them — reads exactly as it always did.
#: ``area``/``volume`` "auto" follow the length (mm → mm², ft → ft²);
#: ``area_precision`` None follows its precision, as areas always have.
#: Volumes kept the three decimals they were always shown with.
_OPTIONAL_DEFAULTS = {"area": "auto", "area_precision": None,
                      "volume": "auto", "volume_precision": 3,
                      "angle": "deg", "angle_precision": 1, "decimal": "."}
_OPTIONAL = {
    "area": _of_kind("area"), "area_precision": _is_precision,
    "volume": _of_kind("volume"), "volume_precision": _is_precision,
    "angle": lambda c: c in ("deg", "rad", "grad"),
    "angle_precision": _is_precision,
    "decimal": lambda c: c in (".", ","),
}


def unit_setting(key: str, settings: dict | None = None):
    """One setting of ``settings`` (default: the document's), its default
    when absent."""
    u = model_units() if settings is None else settings
    if key in u:
        return u[key]
    if key == "area_precision":
        return u.get("precision", 2)
    return _OPTIONAL_DEFAULTS[key]


#: QSettings key of the units a NEW document starts with (issue #121: «I
#: model every part in millimetres» — the unit was lost with each new file).
NEW_DOCUMENT_KEY = "units/new_document"


def new_document_units() -> dict:
    """The units a new, empty document starts with: the ones the user last
    chose «for new documents» in Preferences, or metres. Opening a file never
    reads this — a document keeps its own units (an old .igz without them is
    in metres, as it was drawn)."""
    import json

    from PySide6.QtCore import QSettings
    try:
        raw = QSettings().value(NEW_DOCUMENT_KEY)
        return model_units_of({"units": json.loads(raw)} if raw else {})
    except (TypeError, ValueError):
        return dict(DEFAULT_MODEL_UNITS)


def remember_new_document_units(units: dict) -> None:
    import json

    from PySide6.QtCore import QSettings
    st = QSettings()
    st.setValue(NEW_DOCUMENT_KEY, json.dumps(model_units_of({"units": units})))
    st.sync()


def apply_units(scene, units: dict) -> None:
    """Give ``scene`` these units; the dimension style follows them, as the
    Preferences dialog has always done."""
    chosen = model_units_of({"units": units})
    scene.units = chosen
    style = getattr(scene, "dimension_style", None)
    if isinstance(style, dict):
        style["units"] = chosen["length"]
        style["decimals"] = chosen["precision"]


def model_units() -> dict:
    return model_units_of(_SCENE)


def model_unit() -> str:
    return model_units()["length"]


def model_precision() -> int:
    return model_units()["precision"]


def unit_label(code: str) -> str:
    from core.i18n import tr
    if code in UNIT_LABELS:
        return tr(UNIT_LABELS[code])
    if code in KIND_UNIT_NAMES:
        return f"{tr(KIND_UNIT_NAMES[code])} ({UNITS[code].symbol})"
    return code


#: The area, volume and angle units the units panel offers, in its order,
#: with their names (English source strings, translated where shown).
KIND_UNIT_NAMES = {
    "mm2": "Square millimetres", "cm2": "Square centimetres",
    "m2": "Square metres", "ha": "Hectares", "in2": "Square inches",
    "ft2": "Square feet", "yd2": "Square yards", "acre": "Acres",
    "cm3": "Cubic centimetres", "l": "Litres", "m3": "Cubic metres",
    "in3": "Cubic inches", "ft3": "Cubic feet", "yd3": "Cubic yards",
    "gal": "US gallons",
    "deg": "Degrees", "rad": "Radians", "grad": "Gradians",
}
AREA_CHOICES = ("mm2", "cm2", "m2", "ha", "in2", "ft2", "yd2", "acre")
VOLUME_CHOICES = ("cm3", "l", "m3", "in3", "ft3", "yd3", "gal")
ANGLE_CHOICES = ("deg", "rad", "grad")

#: The smallest fraction of an inch each precision step shows, for the
#: fractional forms (``in-frac``, ``ft-in-frac``).
FRACTION_LABELS = ('1"', '1/4"', '1/16"', '1/32"', '1/64"')

#: One click sets the whole panel. A profile names the length and its
#: precision; everything else goes back to following the length (areas
#: in its square, volumes in its cube, angles in degrees). The decimal
#: separator is the reader's, not the profile's, and stays as it is.
PROFILES = {
    "metric": {"length": "m", "precision": 2},
    "millimetric": {"length": "mm", "precision": 0},
    "imperial": {"length": "ft-in-frac", "precision": 2},
}
PROFILE_LABELS = {"metric": "Metric (m, cm)", "millimetric": "Millimetric (mm)",
                  "imperial": "Imperial (ft-in)", "custom": "Custom"}


def profile_of(settings: dict) -> str:
    """The profile ``settings`` match, or ``"custom"``."""
    clean = {k: v for k, v in model_units_of({"units": settings}).items()
             if k != "decimal"}
    for name, units in PROFILES.items():
        if clean == units:
            return name
    return "custom"


def with_profile(settings: dict, name: str) -> dict:
    """``settings`` switched to the profile ``name`` (its decimal separator
    kept)."""
    out = dict(PROFILES[name])
    sep = unit_setting("decimal", model_units_of({"units": settings}))
    if sep != ".":
        out["decimal"] = sep
    return out


#: Set while the value being read is not a length (see ``unitless_numbers``).
_UNITLESS = False


def bare_number_scale() -> float:
    """Metres per unit for a number typed without a unit: ``2`` is 2 m in
    a metric document and 2 mm in a millimetre one -- and 1 while
    ``unitless_numbers`` holds, when the number is not a length."""
    if _UNITLESS:
        return 1.0
    return _BARE_SCALE.get(model_unit(), 1.0)


@contextmanager
def unitless_numbers():
    """Read typed numbers as they are: an angle, a scale factor or a side
    count has no unit, so the document's must not touch it -- «45» in a
    millimetre model was a turn of 0.045° (#176). A field that does carry
    a unit («2m») still converts."""
    global _UNITLESS
    before, _UNITLESS = _UNITLESS, True
    try:
        yield
    finally:
        _UNITLESS = before


def localized(text: str, settings: dict | None = None) -> str:
    """``text`` with the document's decimal separator (``1,25 m`` when the
    document reads with a comma). Typing takes both, always."""
    if unit_setting("decimal", settings) == ",":
        return text.replace(".", ",")
    return text


def fmt_len(metres: float) -> str:
    """A length in the model's units and precision — the one formatter
    every readout uses (tool labels, Entity Info, status bar)."""
    return localized(format_length(float(metres), model_unit(),
                                    model_precision()))


#: The mark a bare typed number gets in each unit: what the number MEANS
#: (``bare_number_scale``), shown while it is typed.
_TYPED_MARK = {"m": " m", "cm": " cm", "mm": " mm", "in": '"', "ft": "'",
               "ft-in": '"', "in-frac": '"', "ft-in-frac": '"'}


def typed_value_text(buffer: str) -> str:
    """What the user is typing in the VCB, as the canvas shows it: a bare
    number (or a ``a,b`` / ``a;b`` list of them) gets the model's unit, the
    one it will be read in -- «500» in a millimetre document is 500 mm, and
    showing «500 m» told the user the opposite (issue #149). Anything that
    already carries a unit or a mark is shown as typed."""
    import re

    text = (buffer or "").strip()
    if text and re.fullmatch(r"[-+]?[\d.]+(\s*[,;]\s*[-+]?[\d.]+)*", text):
        return text + _TYPED_MARK.get(model_unit(), " m")
    return text


def fmt_num(metres: float) -> str:
    """The number alone, for ``a × b`` pairs; imperial forms keep their
    marks because the mark IS the unit."""
    u = model_unit()
    if u in ("m", "cm", "mm"):
        factor = {"m": 1.0, "cm": 100.0, "mm": 1000.0}[u]
        return localized(_fixed(float(metres) * factor, model_precision()))
    return fmt_len(metres)


def fmt_pair(a: float, b: float) -> str:
    """``3.00 × 2.00 m`` (metric: one unit at the end) or
    ``3'0" × 2'0"`` (imperial: each number carries its mark)."""
    u = model_unit()
    if u in ("m", "cm", "mm"):
        return f"{fmt_num(a)} × {fmt_len(b)}"
    return f"{fmt_len(a)} × {fmt_len(b)}"


#: The fewest decimals that still resolve a millimetre (or 1/16") in each
#: unit — what a parts list needs whatever the document's display
#: precision is: a 4 mm hinge leaf in a document shown to the centimetre
#: read «0.00 m» and looked like a sheet with no thickness at all.
_FINE_DECIMALS = {"m": 3, "cm": 1, "mm": 0, "in": 2, "ft": 3,
                  "ft-in": 2, "in-frac": 2, "ft-in-frac": 2}


def fine_precision() -> int:
    """The document's precision, raised to millimetre resolution."""
    return max(model_precision(), _FINE_DECIMALS.get(model_unit(), 3))


def fmt_len_fine(metres: float) -> str:
    """:func:`fmt_len` at least to the millimetre — for part sizes and cut
    lists, where a thickness is the number that matters."""
    return localized(format_length(float(metres), model_unit(),
                                    fine_precision()))


def fmt_triple(a: float, b: float, c: float, fine: bool = False) -> str:
    """``0.58 × 0.45 × 0.04 m`` — a part's length × width × thickness, in
    the same idiom as :func:`fmt_pair`. ``fine`` resolves the millimetre
    (:func:`fmt_len_fine`)."""
    u = model_unit()
    n = fine_precision() if fine else model_precision()
    if u in ("m", "cm", "mm"):
        factor = {"m": 1.0, "cm": 100.0, "mm": 1000.0}[u]
        a_, b_ = (_fixed(float(v) * factor, n) for v in (a, b))
        return localized(f"{a_} × {b_} × {format_length(float(c), u, n)}")
    return localized(" × ".join(format_length(float(v), u, n)
                                 for v in (a, b, c)))


def fmt_area(square_metres: float) -> str:
    """An area in the document's area unit — by default its length unit
    squared."""
    return fmt_area_with(square_metres, model_units())


def fmt_area_with(square_metres: float, settings: dict) -> str:
    unit = unit_setting("area", settings)
    n = unit_setting("area_precision", settings)
    if unit != "auto":
        return localized(format_area(square_metres, unit, n), settings)
    u = settings.get("length", "m")
    if u in ("m", "cm", "mm"):
        factor = {"m": 1.0, "cm": 1e4, "mm": 1e6}[u]
        txt = f"{_fixed(float(square_metres) * factor, n)} {u}²"
    elif u.startswith("ft"):
        txt = f"{_fixed(float(square_metres) / (FT_M * FT_M), n)} ft²"
    else:
        txt = f"{_fixed(float(square_metres) / (IN_M * IN_M), n)} in²"
    return localized(txt, settings)


# ---- Any quantity, shown and typed -------------------------------------------
#
# ``format_value`` and ``parse`` are the one place where text and numbers
# meet: a field, a panel or a plugin hands them the base value (metres,
# square metres, cubic metres, radians) or the text, never a factor.

def format_value(value: float, unit: str, decimals: int = 2,
                 symbol: bool = True) -> str:
    """``value`` (in the BASE unit of its kind) shown in ``unit`` — a code
    of the table, or one of the length forms of :data:`UNIT_CHOICES`.
    Rounding is for the eye only: the value itself is never changed."""
    if unit in _BARE_SCALE and unit not in ("m", "cm", "mm"):
        return format_length(value, unit, decimals)     # the imperial forms
    row = UNITS[unit]
    value = float(value)
    if not math.isfinite(value):
        return "—"
    n = max(0, min(6, int(decimals)))
    txt = _fixed(value / row.factor, n)
    if not symbol:
        return txt
    glue = "" if row.symbol in ("°", '"', "'") else " "
    return f"{txt}{glue}{row.symbol}"


def format_area(square_metres: float, unit: str, decimals: int = 2) -> str:
    """An area in ``unit`` (``m2``, ``cm2``, ``ha``, ``ft2``, ``acre``…)."""
    return format_value(square_metres, unit, decimals)


def format_volume(cubic_metres: float, unit: str, decimals: int = 2) -> str:
    """A volume in ``unit`` (``m3``, ``l``, ``ft3``, ``gal``…)."""
    return format_value(cubic_metres, unit, decimals)


def format_angle(radians: float, unit: str = "deg", decimals: int = 1) -> str:
    """An angle in ``unit`` (``deg``, ``rad`` or ``grad``)."""
    return format_value(radians, unit, decimals)


#: The area and volume units that go with each length form, for a
#: document that shows its areas «in the length's unit squared».
_SQUARE_OF = {"m": "m2", "cm": "cm2", "mm": "mm2", "km": "m2", "in": "in2",
              "in-frac": "in2", "ft": "ft2", "ft-in": "ft2", "ft-in-frac": "ft2",
              "yd": "yd2", "mi": "acre"}
_CUBE_OF = {"m": "m3", "cm": "cm3", "mm": "cm3", "km": "m3", "in": "in3",
            "in-frac": "in3", "ft": "ft3", "ft-in": "ft3", "ft-in-frac": "ft3",
            "yd": "yd3", "mi": "yd3"}


def area_unit_for(length_unit: str) -> str:
    return _SQUARE_OF.get(length_unit, "m2")


def volume_unit_for(length_unit: str) -> str:
    return _CUBE_OF.get(length_unit, "m3")


def fmt_volume(cubic_metres: float) -> str:
    """A volume in the document's volume unit — by default its length unit
    cubed (a millimetre model, which would read billions of mm³, shows
    cm³)."""
    return fmt_volume_with(cubic_metres, model_units())


def fmt_volume_with(cubic_metres: float, settings: dict) -> str:
    unit = unit_setting("volume", settings)
    if unit == "auto":
        unit = volume_unit_for(settings.get("length", "m"))
    return localized(format_volume(cubic_metres, unit,
                                    unit_setting("volume_precision", settings)),
                      settings)


def fmt_angle(radians: float, signed: bool = False) -> str:
    """An angle in the document's angle unit and precision — what the
    Rotate, Protractor and Arc tools show (``+45.0°`` by default)."""
    return fmt_angle_with(radians, model_units(), signed)


def fmt_angle_deg(degrees: float, signed: bool = False) -> str:
    """:func:`fmt_angle` for the tools that measure in degrees."""
    return fmt_angle(math.radians(float(degrees)), signed)


def fmt_angle_with(radians: float, settings: dict, signed: bool = False) -> str:
    txt = format_angle(radians, unit_setting("angle", settings),
                       unit_setting("angle_precision", settings))
    if signed and not txt.startswith(("-", "—")):
        txt = "+" + txt
    return localized(txt, settings)


def fmt_len_with(metres: float, settings: dict) -> str:
    return localized(format_length(metres, settings.get("length", "m"),
                                    settings.get("precision", 2)), settings)


#: The value the units panel shows its preview with: 1.2345 m (and m², m³,
#: rad), long enough to show what the precision does.
PREVIEW_VALUE = 1.2345


#: The largest number a field takes (in whatever unit it is typed): a UTM
#: northing is ~1e7 m, a kilometre in millimetres 1e6. Beyond it, and for
#: a number too long for a float (inf, then NaN a few steps later, #185),
#: the text is refused.
MAX_TYPED = 1e9

_IMPERIAL_FORMS = {"in", "ft", "ft-in", "in-frac", "ft-in-frac", "yd", "mi"}

#: Error messages: English source strings, translated where they are shown.
_EXPECTED = {"length": "Expected a length", "area": "Expected an area",
             "volume": "Expected a volume", "angle": "Expected an angle"}


@dataclass(frozen=True)
class Parsed:
    """What :func:`parse` read: the value in the base unit, or an error
    with the place in the text where it starts. Never an exception."""
    value: float | None = None
    error: str = ""
    position: int = 0
    word: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None

    def message(self) -> str:
        """The error, in the interface language."""
        from core.i18n import tr
        if not self.error:
            return ""
        if "{unit}" in self.error:
            return tr(self.error, unit=self.word)
        return tr(self.error)


#: A number as it is typed: ``2``, ``2.5``, ``.5``, ``3/4``, and a mixed
#: number ``1 1/2`` or ``1-1/2``.
_QTY = r"(?:\d+[ -]+\d+/\d+|\d+/\d+|\d+(?:\.\d*)?|\.\d+)"
#: A unit word: letters (``mm``, ``pies``, ``m²``, ``m2``, ``m^2``) or a mark.
_WORD = r"(?:[^\W\d_]+(?:\^?[23](?![\d./]))?|[°'\"])"
_TERM = re.compile(rf"({_QTY})\s*({_WORD})?\s*")
_FEET_INCHES = re.compile(
    rf"(?P<ft>{_QTY})\s*(?:'|ft|feet|foot|pies?)\s*(?:-\s*)?"
    rf"(?:(?P<inch>{_QTY})\s*(?:\"|in|inch|inches|pulgadas?)?)?")
_HYPHEN_FEET = re.compile(
    r"(?P<ft>\d+)-(?P<inch>\d+(?:\.\d+)?(?:[ -]+\d+/\d+)?)")


def _number(text: str):
    """The value of a :data:`_QTY` match, or None (a zero denominator, a
    number too big for a model)."""
    m = re.fullmatch(r"(?:(\d+)[ -]+)?(?:(\d+)/(\d+)|(\d+(?:\.\d*)?|\.\d+))",
                     text.strip())
    if m is None:
        return None
    if m.group(2) is not None:
        if int(m.group(3)) == 0:
            return None
        v = int(m.group(2)) / int(m.group(3))
    else:
        if m.group(1) is not None:
            return None                  # «1-2» is two numbers, not one
        v = float(m.group(4))
    if m.group(1) is not None:
        v += int(m.group(1))
    return v if math.isfinite(v) and abs(v) <= MAX_TYPED else None


def _bare_factor(kind: str, unit: str | None) -> float:
    """Base units per bare number: the field's ``unit`` if it names one,
    else the document's (a length), else the kind's usual unit."""
    if kind == "length":
        if unit is None:
            return bare_number_scale()
        return _BARE_SCALE.get(unit) or UNITS[unit].factor
    if unit is None:
        unit = {"area": area_unit_for(model_unit()),
                "volume": volume_unit_for(model_unit()),
                "angle": "deg"}[kind]
    return UNITS[unit].factor


#: After a whole unit, a bare number is the next one down: «1m 20» is
#: 1.20 m, «5ft 3» is 5'3".
_NEXT_DOWN = {"m": "cm", "ft": "in"}

#: Typographic marks people paste from documents — or that a keyboard with
#: smart quotes types (issue #189: «1 ⅜", 1 3/16”» on a Mac) — read as the
#: plain ones.
_TYPOGRAPHIC = {"″": '"', "”": '"', "“": '"', "′": "'", "’": "'", "‘": "'"}
_MARKS = str.maketrans({",": ".", **_TYPOGRAPHIC})

#: The fraction characters (½, ⅜…) as the digits a field reads.
VULGAR_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6", "⅚": "5/6",
    "⅐": "1/7", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "⅑": "1/9",
    "⅒": "1/10",
}


def plain_marks(text: str) -> str:
    """``text`` with typographic quotes as ``"`` / ``'`` and fraction
    characters as digits: ``1⅜”`` → ``1 3/8"`` (a whole number before the
    fraction keeps it apart, as a mixed number)."""
    out = []
    for ch in text:
        frac = VULGAR_FRACTIONS.get(ch)
        if frac is not None:
            if out and out[-1][-1:].isdigit():
                out.append(" ")
            out.append(frac)
        else:
            out.append(_TYPOGRAPHIC.get(ch, ch))
    return "".join(out)


def parse(text: str, kind: str = "length", unit: str | None = None) -> Parsed:
    """Read a typed ``kind`` (length, area, volume, angle) → its value in
    the base unit, or an error.

    Tolerant the way people type: ``1,20`` and ``1.20`` mean the same,
    spaces are free (``  5 cm ``), units in Spanish or English (``120cm``,
    ``2 metros``, ``3 pies``), ``1m 20`` is 1.20 m, and the imperial
    marks: ``5'``, ``5'3``, ``5' 3 1/2"``, ``3'-6 1/2"``, ``63"`` — plus
    ``5-3 1/2`` (feet-inches) when the field is imperial. A number without
    a unit is in ``unit`` (a code of the table or a form of
    :data:`UNIT_CHOICES`), or the document's when ``unit`` is None. A unit
    of another kind is refused with a message: ``5 m²`` is not a length."""
    raw = plain_marks(text) if isinstance(text, str) else ""
    offset = len(raw) - len(raw.lstrip())
    t = re.sub(r"\s+", " ", raw.strip().lower().translate(_MARKS))
    if not t:
        return Parsed(error="Type a value")
    sign = 1.0
    if t[0] in "+-":
        sign = -1.0 if t[0] == "-" else 1.0
        t = t[1:].lstrip()
        offset += 1
    if not t:
        return Parsed(error="Type a number", position=offset)

    def done(v):
        if v is None:
            return Parsed(error="Not a number", position=offset)
        return Parsed(value=sign * v)

    if kind == "length":
        m = _FEET_INCHES.fullmatch(t)
        if m is not None:
            ft = _number(m.group("ft"))
            inch = _number(m.group("inch")) if m.group("inch") else 0.0
            if ft is None or inch is None:
                return done(None)
            return done(ft * FT_M + inch * IN_M)
        m = _HYPHEN_FEET.fullmatch(t)
        if m is not None and (unit or model_unit()) in _IMPERIAL_FORMS:
            ft, inch = _number(m.group("ft")), _number(m.group("inch"))
            return done(None if ft is None or inch is None
                        else ft * FT_M + inch * IN_M)

    terms = []
    pos = 0
    while pos < len(t):
        m = _TERM.match(t, pos)
        if m is None or m.end() == pos:
            return Parsed(error="Not a number", position=offset + pos)
        where = m.start(2) if m.group(2) else m.start(1)
        terms.append((m.group(1), m.group(2), offset + where))
        pos = m.end()

    total = 0.0
    previous = None
    for i, (num_txt, word, where) in enumerate(terms):
        num = _number(num_txt)
        if num is None:
            return Parsed(error="Not a number", position=where)
        if word is None:
            if len(terms) == 1:
                return done(num * _bare_factor(kind, unit))
            down = _NEXT_DOWN.get(previous)
            if i != len(terms) - 1 or down is None:
                return Parsed(error="Type one value", position=where)
            total += num * UNITS[down].factor
            break
        row = _ALIASES.get(word)
        if row is None:
            return Parsed(error="Unknown unit: {unit}", position=where,
                          word=word)
        if row.kind != kind:
            return Parsed(error=_EXPECTED[kind], position=where, word=word)
        total += num * row.factor
        previous = row.code
    return Parsed(value=sign * total)


def parse_length_field(field: str):
    """One typed length in metres, or None — the value box's reading of a
    field (see :func:`parse`)."""
    r = parse(field, "length")
    return r.value if r.ok else None


def display_step(unit: str | None = None, decimals: int | None = None) -> float:
    """The length, in metres, of one step of the shown precision — what an
    arrow key adds in a length field: 1 mm in a millimetre document, 1 cm
    in a metre one to two decimals, 1/16" in fractional inches."""
    u = unit or model_unit()
    n = model_precision() if decimals is None else int(decimals)
    if u in ("in-frac", "ft-in-frac"):
        return IN_M / _FRAC_DENOMS.get(max(0, min(4, n)), 16)
    return 10.0 ** -max(0, n) * _bare_factor("length", u)
