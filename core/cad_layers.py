# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""CAD layers for 2D views — which layer, which pen, per line.

The hidden-line pass (``core.hlr.hlr_drawing`` with ``owners``) says, per
segment, which object it came from and whether it is cut, seen or hidden.
This module turns that into what a CAD office expects to receive: every
line on a discipline layer named the AIA / US National CAD Standard way
(``A-WALL``, ``S-COLS``, ``M-DUCT``…) with the line class as a suffix
(``A-WALL-CUT``, ``A-WALL-PROJ``, ``A-WALL-HIDN``), and a pen per layer —
thick for what the plane cuts, thin for what lies beyond, dashed for what
is hidden, a colour per discipline.

Where the layer comes from, first match wins:

1. the object's IFC class (``core.bim``) — the semantic truth;
2. its IngeTrazo layer when it already reads like a CAD layer
   (``M-HVAC``, ``E-Power``, ``S-Frame``), upper-cased and otherwise kept;
3. its name: a discipline prefix (``MEP · Cold water``, ``STR · Beam``) or
   a keyword (pipe, duct, column…);
4. ``A-GENM`` — general architecture — for everything else.

Headless (no Qt): tested without a display.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.hlr import KIND_CUT, KIND_HIDDEN

#: Discipline letters of the US National CAD Standard, with what they hold.
DISCIPLINES = {
    "A": "Architectural",
    "S": "Structural",
    "M": "Mechanical",
    "P": "Plumbing",
    "E": "Electrical",
    "F": "Fire protection",
    "I": "Interiors",
    "C": "Civil",
    "G": "General",
}

#: The view's discipline filter: which letters each choice keeps.
DISCIPLINE_FILTERS = {
    "all": None,
    "architectural": {"A", "I", "G"},
    "structural": {"S"},
    "mep": {"M", "P", "E", "F"},
}

#: IFC class → base layer.
IFC_LAYERS = {
    "IfcWall": "A-WALL",
    "IfcWallStandardCase": "A-WALL",
    "IfcCurtainWall": "A-GLAZ",
    "IfcDoor": "A-DOOR",
    "IfcWindow": "A-GLAZ",
    "IfcRoof": "A-ROOF",
    "IfcStair": "A-FLOR-STRS",
    "IfcStairFlight": "A-FLOR-STRS",
    "IfcRamp": "A-FLOR-RAMP",
    "IfcRailing": "A-FLOR-HRAL",
    "IfcCovering": "A-CLNG",
    "IfcSpace": "A-AREA",
    "IfcBuildingElementProxy": "A-GENM",
    "IfcSlab": "S-SLAB",
    "IfcColumn": "S-COLS",
    "IfcBeam": "S-BEAM",
    "IfcMember": "S-FRAM",
    "IfcFooting": "S-FNDN",
    "IfcPile": "S-FNDN-PILE",
    "IfcPlate": "S-FRAM",
    "IfcReinforcingBar": "S-REIN",
    "IfcDuctSegment": "M-DUCT",
    "IfcDuctFitting": "M-DUCT",
    "IfcAirTerminal": "M-DUCT-DIFF",
    "IfcUnitaryEquipment": "M-EQPM",
    "IfcFlowTerminal": "M-EQPM",
    "IfcPipeSegment": "P-PIPE",
    "IfcPipeFitting": "P-PIPE",
    "IfcSanitaryTerminal": "P-FIXT",
    "IfcFireSuppressionTerminal": "F-SPRN",
    "IfcCableCarrierSegment": "E-CABL-TRAY",
    "IfcCableCarrierFitting": "E-CABL-TRAY",
    "IfcLightFixture": "E-LITE",
    "IfcOutlet": "E-POWR",
    "IfcElectricDistributionBoard": "E-POWR-PANL",
    "IfcSensor": "E-INST",
    "IfcFurniture": "I-FURN",
    "IfcFurnishingElement": "I-FURN",
}

#: Discipline words that start a group name («MEP · Cold water (PPR)»).
NAME_PREFIXES = {
    "ARC": "A-GENM", "ARCH": "A-GENM", "A": "A-GENM",
    "STR": "S-FRAM", "S": "S-FRAM",
    "MEP": "M-GENM", "HVAC": "M-HVAC", "M": "M-GENM",
    "PLB": "P-PIPE", "PLU": "P-PIPE", "P": "P-PIPE",
    "ELE": "E-POWR", "ELEC": "E-POWR", "E": "E-POWR",
    "FIRE": "F-PROT", "FPS": "F-PROT", "F": "F-PROT",
    "FUR": "I-FURN", "INT": "I-FURN", "I": "I-FURN",
    "CIV": "C-TOPO", "SITE": "C-TOPO",
    "INS": "E-INST",
}

#: Keywords anywhere in a name, checked in order (word starts, any case).
NAME_KEYWORDS = (
    ("duct", "M-DUCT"), ("hvac", "M-HVAC"), ("diffuser", "M-DUCT-DIFF"),
    ("drain", "P-SANR"), ("sewer", "P-SANR"), ("water", "P-DOMW"),
    ("pipe", "P-PIPE"), ("sprinkler", "F-SPRN"),
    ("tray", "E-CABL-TRAY"), ("conduit", "E-CABL"), ("cable", "E-CABL"),
    ("light", "E-LITE"), ("lamp", "E-LITE"), ("socket", "E-POWR"),
    ("column", "S-COLS"), ("beam", "S-BEAM"), ("footing", "S-FNDN"),
    ("slab", "S-SLAB"), ("pile", "S-FNDN-PILE"),
    ("wall", "A-WALL"), ("door", "A-DOOR"), ("window", "A-GLAZ"),
    ("roof", "A-ROOF"), ("stair", "A-FLOR-STRS"), ("railing", "A-FLOR-HRAL"),
    ("ceiling", "A-CLNG"), ("furniture", "I-FURN"), ("chair", "I-FURN"),
    ("table", "I-FURN"),
)

DEFAULT_LAYER = "A-GENM"

#: Suffix per line class.
SUFFIX_CUT = "CUT"
SUFFIX_PROJ = "PROJ"
SUFFIX_HIDDEN = "HIDN"

#: AutoCAD Colour Index per discipline (the CAD's pen table may remap).
DISCIPLINE_COLORS = {"A": 7, "S": 4, "M": 3, "P": 6, "E": 2, "F": 1,
                     "I": 8, "C": 32, "G": 8}

#: Lineweights, DXF units (hundredths of a millimetre).
LW_CUT_HEAVY = 50     # walls, columns, slabs, beams: what the cut is about
LW_CUT = 35
LW_PROJ = 18
LW_HIDDEN = 13

_HEAVY_CUT = ("A-WALL", "S-COLS", "S-SLAB", "S-BEAM", "S-FNDN", "S-FRAM")

_CAD_LAYER_RE = re.compile(r"^[ASMPEFICG](?:-[A-Za-z0-9]+)+$")
_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{1,5})\s*[·:|\-]\s*")


def base_layer(owner) -> str:
    """The discipline layer of an :class:`core.hlr.Owner` (no suffix)."""
    if owner is None:
        return DEFAULT_LAYER
    ifc = getattr(owner, "ifc", None)
    if ifc and ifc in IFC_LAYERS:
        return IFC_LAYERS[ifc]
    layer = getattr(owner, "layer", None) or ""
    if _CAD_LAYER_RE.match(layer):
        return layer.upper()            # the office's own name, kept whole
    name = getattr(owner, "name", None) or ""
    by_keyword = _keyword_layer(name)
    m = _PREFIX_RE.match(name)
    if m and m.group(1).upper() in NAME_PREFIXES:
        prefix = NAME_PREFIXES[m.group(1).upper()]
        # «MEP · Cold water» is plumbing, not generic mechanical: a keyword
        # of the same broad family refines the prefix.
        if by_keyword and _family(by_keyword) == _family(prefix):
            return by_keyword
        return prefix
    return by_keyword or DEFAULT_LAYER


def _keyword_layer(name: str):
    low = name.lower()
    for word, layer in NAME_KEYWORDS:
        if re.search(r"(?<![a-z])" + word, low):
            return layer
    return None


def _family(layer: str) -> str:
    """MEP is one family (a «MEP ·» prefix may hold pipes or ducts)."""
    d = layer[:1]
    return "MEP" if d in "MPEF" else d


def suffix_for(kind: int) -> str:
    if kind == KIND_CUT:
        return SUFFIX_CUT
    if kind == KIND_HIDDEN:
        return SUFFIX_HIDDEN
    return SUFFIX_PROJ


def layer_name(base: str, kind: int) -> str:
    return f"{base}-{suffix_for(kind)}"


@dataclass(frozen=True)
class Pen:
    color: int          #: ACI
    lineweight: int     #: hundredths of a mm (DXF enum)
    linetype: str       #: "CONTINUOUS" / "DASHED"


def pen_for(layer: str) -> Pen:
    """The pen of a full layer name (``A-WALL-CUT``)."""
    color = DISCIPLINE_COLORS.get(layer[:1], 7)
    if layer.endswith("-" + SUFFIX_CUT):
        base = layer[: -len(SUFFIX_CUT) - 1]
        heavy = any(base.startswith(h) for h in _HEAVY_CUT)
        return Pen(color, LW_CUT_HEAVY if heavy else LW_CUT, "CONTINUOUS")
    if layer.endswith("-" + SUFFIX_HIDDEN):
        return Pen(color, LW_HIDDEN, "DASHED")
    return Pen(color, LW_PROJ, "CONTINUOUS")


@dataclass
class CadLayer:
    """One layer of a 2D view: its lines (x0, y0, x1, y1) and the closed
    rings (M,2) of the cut to hatch."""
    name: str
    pen: Pen
    segments: list = field(default_factory=list)
    fills: list = field(default_factory=list)


def split_drawing(drawing, table, disciplines=None) -> dict:
    """``{layer name: CadLayer}`` for an :class:`core.hlr.HlrDrawing`
    drawn with owners; ``table`` is the owner table those indices point
    into. ``disciplines`` — a set of discipline letters (see
    :data:`DISCIPLINE_FILTERS`) — keeps only those; ``None`` keeps all.
    Layers come back sorted by name, so a file diff stays readable."""
    if drawing.owners is None:
        raise ValueError("the drawing was made without owners")
    bases: dict = {}

    def base_of(i: int) -> str:
        if i not in bases:
            bases[i] = base_layer(table[i] if 0 <= i < len(table) else None)
        return bases[i]

    layers: dict = {}

    def get(name: str) -> CadLayer:
        lay = layers.get(name)
        if lay is None:
            lay = layers[name] = CadLayer(name, pen_for(name))
        return lay

    for seg, kind, own in zip(drawing.segs, drawing.kinds, drawing.owners):
        base = base_of(int(own))
        if disciplines is not None and base[:1] not in disciplines:
            continue
        get(layer_name(base, int(kind))).segments.append(
            tuple(float(v) for v in seg))
    for ring, own in zip(drawing.loops or (), drawing.loop_owners or ()):
        base = base_of(int(own))
        if disciplines is not None and base[:1] not in disciplines:
            continue
        get(layer_name(base, KIND_CUT)).fills.append(ring)
    return dict(sorted(layers.items()))
