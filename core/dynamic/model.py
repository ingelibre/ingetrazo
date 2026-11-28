# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 moominot and IngeTrazo contributors.
# Adapted from moominot's «dc_tools» extension (GPL-3.0-or-later,
# https://github.com/moominot/ingetrazo-skp-dc-import).
"""The parts of a dynamic component, as the evaluator sees them.

A :class:`Part` is one placement (group or component instance) with the
``dynamic_attributes`` stored for it: the definition's dictionary
merged with the instance's own (the instance wins), as .skp files read
them. The tree mirrors the file's nesting.

Lengths in these dictionaries are always INCHES, whatever the component's
``_lengthunits`` says; that only sets the unit formulas are written in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Attributes every part has (the "predefined" attributes).
LENGTHS = ("x", "y", "z", "lenx", "leny", "lenz")
ANGLES = ("rotx", "roty", "rotz")
PREDEFINED = LENGTHS + ANGLES + ("hidden", "material", "copies", "copy", "name",
                                 "summary", "description", "itemcode", "imageurl",
                                 "dialogwidth", "dialogheight", "scaletool",
                                 "onclick")

INCH = {"INCHES": 1.0, "FEET": 12.0, "MILLIMETERS": 1 / 25.4,
        "CENTIMETERS": 1 / 2.54, "METERS": 100 / 2.54}


@dataclass(eq=False)          # identity: parts are dictionary keys
class Part:
    name: str                                 # _name, else the placement's name
    attrs: dict                               # merged def + instance dictionary
    parent: "Part | None" = None
    children: list = field(default_factory=list)
    handle: object = None                     # what the caller maps it back to
    xform: list | None = None                 # local transform, 4×4 row-major, inches
    base: tuple | None = None                 # the definition's natural size, inches
    definition: str = ""                      # the definition's name (tells copies apart)
    source: "Part | None" = None              # for an evaluation twin: the file's part
    #: Other names formulas reach this part by: the placement's own name
    #: when ``_name`` says something else (a part placed as «MUNT1» whose
    #: definition is named «MUNT07» answers to both, as in .skp files).
    aliases: tuple = ()

    # -- the dictionary ----------------------------------------------------
    def stored(self, attr: str):
        """The value stored for ``attr`` (lengths in inches)."""
        return self.attrs.get(attr)

    def formula(self, attr: str) -> str | None:
        """The formula driving ``attr`` (empty text means none).

        Only ``_<attr>_formula`` counts, the instance's own over the
        definition's (they are merged that way). The definition's
        ``_inst__<attr>_formula`` keys are the TEMPLATE for new
        placements, not a formula of any placement: a window's second guide
        whose instance has no X formula stays where it is, though its
        definition still carries ``_inst__x_formula``."""
        text = self.attrs.get(f"_{attr}_formula")
        if text is not None and str(text).strip():
            return str(text)
        return None

    def units(self, attr: str) -> str:
        """How ``attr``'s value is measured: a length unit, or DEGREES,
        STRING, INTEGER, FLOAT, BOOLEAN, PERCENT, DEFAULT."""
        if attr in LENGTHS:
            return "LENGTH"
        if attr in ANGLES:
            return "DEGREES"
        for key in (f"_{attr}_formulaunits", f"_{attr}_units"):
            u = self.attrs.get(key)
            if u:
                u = str(u).upper()
                return "LENGTH" if u in INCH else u
        return "DEFAULT"

    def length_unit(self) -> str:
        """The unit this part's formulas are written in: its OWN
        ``_lengthunits``, else inches. Not inherited: in .skp files a part
        without it reads «1.8» as inches inside a CENTIMETERS component (its
        attribute window writes the units on every part it edits)."""
        u = self.attrs.get("_lengthunits")
        if u and str(u).upper() in INCH:
            return str(u).upper()
        return "INCHES"

    # -- the tree ------------------------------------------------------------
    def root(self) -> "Part":
        p = self
        while p.parent is not None:
            p = p.parent
        return p

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def __repr__(self) -> str:  # pragma: no cover
        return f"Part({self.name!r}, {len(self.children)} children)"


def part_name(attrs: dict, fallback: str) -> str:
    return str(attrs.get("_name") or fallback or "")


def part_aliases(name: str, placement_name: str | None) -> tuple:
    """The placement's own name (without the « copy NNN» suffix), when it
    differs from the part's name."""
    own = re.sub(r" copy \d+$", "", str(placement_name or "")).strip()
    return (own.lower(),) if own and own.lower() != str(name).lower() else ()


def build(node, attrs_of, name_of, children_of, parent=None) -> Part:
    """A Part tree from any tree (.skp dump, IngeTrazo groups):
    ``attrs_of(node)`` gives the merged dictionary, ``name_of(node)`` the
    placement's own name, ``children_of(node)`` its sub-placements."""
    attrs = attrs_of(node)
    part = Part(part_name(attrs, name_of(node)), attrs, parent, [], node)
    part.aliases = part_aliases(part.name, name_of(node))
    part.children = [build(c, attrs_of, name_of, children_of, part)
                     for c in children_of(node)]
    return part
