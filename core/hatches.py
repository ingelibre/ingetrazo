# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Hatch patterns for the section cut on a sheet: what a cut layer is made
of, told by its drawing — brick courses, the stipple of concrete, the waves
of insulation, the dashes of earth.

A pattern is described the way technical drawing has always described one:
families of parallel lines, each at an angle, through an origin, the next
line of the family shifted along itself and across, drawn whole or as a run
of dashes, gaps and dots — all in paper millimetres. A few materials are not
lines (gravel, sand, the stipple of concrete, stones, roof tiles, grass, the
rings of end grain, the waves of insulation and wood): those are generated,
scattered by a hash of their cell on the paper.

The set follows the conventions of architectural and technical sections:
45° hatching for anything generic, the material symbols of the drafting
standards for metals, glass and plastics, and the usual architectural ones
for masonry, concrete, ground, insulation, wood and finishes. Every pattern
here is drawn from those conventions, not taken from any program's file.

Everything is locked to the paper, not to the ring it fills, so a pattern
runs on unbroken across two pieces of the same wall and stays put when the
frame moves. Nothing here draws: :func:`hatch_marks` returns the marks
inside a box and ``views.composer`` clips and inks them.
"""
from __future__ import annotations

import math
import re

#: The picker's groups: ``(title, patterns)``, in the order shown. ``None``
#: is not in them: it means «the frame's fill» (solid or 45°, as the frame
#: says) and the picker puts it first.
HATCH_GROUPS = (
    ("General", ("solid", "diagonal", "dashed_diagonal", "double_diagonal",
                 "crosshatch", "grid", "dots", "plus", "hexagon")),
    ("Masonry", ("brick_auto", "brick", "brick_header", "brick_bond",
                 "brick_cross", "brick_flemish", "brick_dutch",
                 "brick_one_half", "brick_on_edge", "brick_rowlock",
                 "brick_honeycomb", "hollow_brick", "perforated_block",
                 "concrete_brick",
                 "fire_brick", "block", "aac_block", "ashlar", "stone",
                 "rubble", "rammed_earth", "tile")),
    ("Concrete and ground", ("concrete", "reinforced", "lean_concrete",
                             "sand", "gravel", "earth", "fill", "clay",
                             "rock")),
    ("Insulation and finishes", ("insulation", "insulation_zigzag",
                                 "rigid_insulation",
                                 "waterproofing", "plaster", "acoustic",
                                 "roof_tile")),
    ("Wood", ("wood", "wood_grain", "wood_open", "wood_flame",
              "wood_diagonal", "wood_boards", "wood_end", "plywood", "osb",
              "clt", "parquet", "wood_herringbone", "wood_cross")),
    ("Metals, glass and plastics", ("steel", "aluminium", "bronze", "lead",
                                    "mesh", "chequer_plate", "glass",
                                    "plastic")),
    ("Vegetation and water", ("grass", "shrubs", "canopy", "crops",
                              "wetland", "water")),
    ("Paving and urban", ("herringbone", "cobblestone", "asphalt",
                          "tactile")),
)

#: Every pattern, in the picker's order.
HATCH_ORDER = tuple(k for _t, keys in HATCH_GROUPS for k in keys)

#: Their names, as the interface shows them (translated by the caller).
HATCH_LABELS = {
    "solid": "Solid",
    "diagonal": "Diagonal hatching",
    "double_diagonal": "Double hatching",
    "crosshatch": "Cross-hatching",
    "grid": "Square grid",
    "dots": "Dots",
    "brick": "Brick",
    "brick_bond": "Brick, English bond",
    "brick_auto": "Brick, bond by wall thickness",
    "brick_header": "Brick, header bond",
    "brick_cross": "Brick, English cross bond",
    "brick_dutch": "Brick, Dutch bond",
    "brick_one_half": "Brick, one and a half bricks thick",
    "brick_on_edge": "Brick on edge, partition",
    "brick_rowlock": "Brick on edge, rowlock",
    "brick_honeycomb": "Brick, honeycomb bond",
    "fire_brick": "Fire brick",
    "block": "Concrete block",
    "aac_block": "Aerated concrete block",
    "perforated_block": "Load-bearing ceramic block (rejillón)",
    "concrete_brick": "Precast concrete brick with holes",
    "stone": "Stone",
    "rubble": "Rubble masonry",
    "tile": "Ceramic tiles",
    "concrete": "Concrete",
    "reinforced": "Reinforced concrete",
    "sand": "Sand, mortar",
    "gravel": "Gravel",
    "earth": "Earth",
    "fill": "Compacted fill",
    "insulation": "Insulation",
    "insulation_zigzag": "Insulation, zigzag",
    "rigid_insulation": "Rigid insulation",
    "roof_tile": "Roof tiles",
    "water": "Water",
    "grass": "Grass",
    "wood": "Wood",
    "wood_end": "Wood, end grain",
    "plywood": "Plywood",
    "parquet": "Parquet",
    "steel": "Steel",
    "aluminium": "Aluminium",
    "bronze": "Bronze, brass",
    "lead": "Lead, zinc",
    "glass": "Glass",
    "plastic": "Plastic, rubber",
    "dashed_diagonal": "Dashed hatching",
    "plus": "Crosses",
    "hexagon": "Hexagons",
    "brick_flemish": "Brick, Flemish bond",
    "hollow_brick": "Hollow brick",
    "ashlar": "Ashlar",
    "rammed_earth": "Rammed earth",
    "lean_concrete": "Lean concrete",
    "clay": "Clay",
    "rock": "Rock",
    "waterproofing": "Waterproofing membrane",
    "plaster": "Plaster",
    "acoustic": "Acoustic panel",
    "osb": "Oriented strand board",
    "clt": "Cross-laminated timber",
    "mesh": "Expanded metal",
    "chequer_plate": "Chequer plate",
    "shrubs": "Shrubs",
    "canopy": "Tree canopy",
    "crops": "Crops",
    "wetland": "Wetland",
    "herringbone": "Herringbone paving",
    "cobblestone": "Cobblestones",
    "asphalt": "Asphalt",
    "tactile": "Tactile paving",
    "wood_grain": "Wood, natural grain",
    "wood_herringbone": "Wood, herringbone",
    "wood_cross": "Timber cut across (cross)",
    "wood_open": "Wood, open grain",
    "wood_flame": "Wood, flame grain",
    "wood_diagonal": "Wood, diagonal grain",
    "wood_boards": "Wood, boards",
}

#: What each pattern is for, for the catalogue (docs/hatches.md) and the
#: pattern file it exports to: ``(alias, density, scale, angle, use)`` — a
#: short code, how dense it reads (``low`` / ``medium`` / ``high``), the
#: scale and the angle that suit it best, and its usual use.
HATCH_INFO = {
    "solid": ("SOLID", "high", 1.0, 0, "Thin cut elements, steel at small scale, poché"),
    "diagonal": ("DIAG", "medium", 1.0, 0, "Any material, the generic section hatch"),
    "dashed_diagonal": ("DIAG-DASH", "low", 1.0, 0, "To demolish, provisional or projected parts"),
    "double_diagonal": ("DIAG-2", "medium", 1.0, 0, "A second generic material beside the first"),
    "crosshatch": ("CROSS", "high", 1.0, 0, "Generic dense material, details"),
    "grid": ("GRID", "medium", 1.0, 0, "Grid floors, square tiling, reference areas"),
    "dots": ("DOTS", "low", 1.0, 0, "Light fills, zones, soft materials"),
    "plus": ("PLUS", "low", 1.0, 0, "Zoning: areas to keep, protected or reserved"),
    "hexagon": ("HEX", "low", 1.0, 0, "Hexagonal tiles, honeycomb panels, zoning"),
    "brick": ("BRICK", "medium", 1.0, 0, "Brick walls, stretcher bond"),
    "brick_bond": ("BRICK-EN", "medium", 1.0, 0, "Brick walls, English bond (one brick thick)"),
    "brick_flemish": ("BRICK-FL", "medium", 1.0, 0, "Brick walls and facings, Flemish (Gothic) bond, one brick thick"),
    "brick_auto": ("BRICK-AUTO", "medium", 1.0, 0, "Brick walls of any thickness: the bond follows each wall (partition, half brick, one, one and a half)"),
    "brick_header": ("BRICK-HD", "medium", 1.0, 0, "Load-bearing brick walls one brick thick, headers on the face"),
    "brick_cross": ("BRICK-X", "medium", 1.0, 0, "Load-bearing walls, English cross bond: the stretcher courses shift half a brick"),
    "brick_dutch": ("BRICK-NL", "medium", 1.0, 0, "Facings, Dutch bond: Flemish courses between header courses"),
    "brick_one_half": ("BRICK-1H", "medium", 1.0, 0, "Brick walls one and a half bricks thick"),
    "brick_on_edge": ("BRICK-EDGE", "low", 1.0, 0, "Partitions of brick on edge, carrying only themselves"),
    "brick_rowlock": ("BRICK-ROW", "medium", 1.0, 0, "Rowlocks: steps, sills, copings, lintels"),
    "brick_honeycomb": ("BRICK-HC", "low", 1.0, 0, "Honeycomb walls with gaps for air: screens, vents"),
    "hollow_brick": ("BRICK-HOL", "medium", 1.0, 0, "Hollow or perforated brick partitions"),
    "fire_brick": ("FIREBRICK", "medium", 1.0, 0, "Refractory linings: chimneys, ovens"),
    "block": ("BLOCK", "medium", 1.0, 0, "Concrete block walls"),
    "aac_block": ("AAC", "low", 1.0, 0, "Aerated (cellular) concrete blocks: large, light, laid with a thin glued joint"),
    "perforated_block": ("CERAMIC-LB", "medium", 1.0, 0, "Load-bearing ceramic blocks and perforated bricks (rejillón): holes running upright"),
    "concrete_brick": ("CONC-BRICK", "medium", 1.0, 0, "Precast concrete bricks with a few large holes running upright"),
    "ashlar": ("ASHLAR", "low", 1.0, 0, "Dressed stone walls in regular courses"),
    "stone": ("STONE", "medium", 1.0, 0, "Stone walls, cladding"),
    "rubble": ("RUBBLE", "medium", 1.0, 0, "Rubble masonry, old walls, gabions"),
    "rammed_earth": ("RAMMED", "low", 1.0, 0, "Rammed earth and adobe walls"),
    "tile": ("TILE", "medium", 1.0, 0, "Ceramic tiling, wall and floor finishes"),
    "concrete": ("CONC", "medium", 1.0, 0, "Plain concrete"),
    "reinforced": ("CONC-R", "medium", 1.0, 0, "Reinforced concrete: slabs, beams, columns"),
    "lean_concrete": ("CONC-LEAN", "low", 1.0, 0, "Blinding and lean concrete under foundations"),
    "sand": ("SAND", "high", 1.0, 0, "Sand, mortar beds, screeds"),
    "gravel": ("GRAVEL", "medium", 1.0, 0, "Gravel, hardcore, drainage layers"),
    "earth": ("EARTH", "medium", 1.0, 0, "Natural ground in section"),
    "fill": ("FILL", "medium", 1.0, 0, "Made ground, compacted fill"),
    "clay": ("CLAY", "medium", 1.0, 0, "Clay and silt layers in ground sections"),
    "rock": ("ROCK", "low", 1.0, 0, "Bedrock and rock in ground sections"),
    "insulation": ("INSUL", "medium", 1.0, 0, "Soft insulation: mineral wool, batts — fitted to the layer's thickness"),
    "insulation_zigzag": ("INSUL-ZZ", "low", 1.0, 0, "Insulation in thin layers: boards, panels, cavities — one zigzag from face to face"),
    "rigid_insulation": ("INSUL-R", "medium", 1.0, 0, "Rigid insulation boards: EPS, XPS, PIR"),
    "waterproofing": ("WATERPROOF", "high", 1.0, 0, "Waterproofing and vapour membranes"),
    "plaster": ("PLASTER", "low", 1.0, 0, "Plaster, render, gypsum board"),
    "acoustic": ("ACOUSTIC", "low", 1.0, 0, "Acoustic and perforated panels"),
    "roof_tile": ("ROOF-TILE", "medium", 1.0, 0, "Roof tiles in section or elevation"),
    "wood": ("WOOD", "low", 1.0, 0, "Timber along the grain"),
    "wood_end": ("WOOD-END", "low", 1.0, 0, "Timber cut across the grain"),
    "plywood": ("PLY", "medium", 1.0, 0, "Plywood and laminated boards"),
    "osb": ("OSB", "medium", 1.0, 0, "Oriented strand board, chipboard"),
    "clt": ("CLT", "medium", 1.0, 0, "Cross-laminated timber panels"),
    "parquet": ("PARQUET", "medium", 1.0, 0, "Wooden floors, parquet in plan"),
    "steel": ("STEEL", "high", 1.0, 0, "Steel sections"),
    "aluminium": ("ALU", "medium", 1.0, 0, "Aluminium sections, frames"),
    "bronze": ("BRONZE", "medium", 1.0, 0, "Bronze, brass, copper"),
    "lead": ("LEAD", "high", 1.0, 0, "Lead, zinc, flashings"),
    "mesh": ("MESH", "medium", 1.0, 0, "Expanded metal, gratings, meshes"),
    "chequer_plate": ("CHEQUER", "medium", 1.0, 0, "Chequer plate floors, stair treads"),
    "glass": ("GLASS", "low", 1.0, 0, "Glass in section"),
    "plastic": ("PLASTIC", "medium", 1.0, 0, "Plastics, rubber, seals"),
    "grass": ("GRASS", "low", 1.0, 0, "Lawn, grass areas"),
    "shrubs": ("SHRUB", "low", 1.0, 0, "Shrub and hedge planting"),
    "canopy": ("TREES", "low", 1.0, 0, "Tree groups, woodland in plan"),
    "crops": ("CROPS", "low", 1.0, 0, "Crops, planted beds, rows"),
    "wetland": ("WETLAND", "low", 1.0, 0, "Marsh, wet meadow, rain gardens"),
    "water": ("WATER", "low", 1.0, 0, "Water: ponds, pools, rivers"),
    "herringbone": ("HERRING", "medium", 1.0, 0, "Herringbone paving, brick or wood"),
    "cobblestone": ("COBBLE", "medium", 1.0, 0, "Cobbled and setts paving"),
    "asphalt": ("ASPHALT", "high", 1.0, 0, "Asphalt, roads, parking"),
    "tactile": ("TACTILE", "low", 1.0, 0, "Tactile warning paving"),
    "wood_grain": ("WOOD-GRAIN", "low", 1.0, 0, "Natural timber seen along the grain, with its knots: boards, beams, cladding"),
    "wood_herringbone": ("WOOD-HERRING", "medium", 1.0, 0, "Herringbone wooden floors: long narrow boards"),
    "wood_cross": ("WOOD-X", "low", 1.0, 0, "Timber cut across its grain: studs, joists, beams, battens — a cross from corner to corner of each piece"),
    "wood_open": ("WOOD-OPEN", "low", 1.0, 0, "Timber in elevation, light: a few long grain lines"),
    "wood_flame": ("WOOD-FLAME", "high", 1.0, 0, "Flat-sawn boards: flame grain round the knots, veneers"),
    "wood_diagonal": ("WOOD-DIAG", "medium", 1.0, 0, "Timber with the grain running across: cladding, battens"),
    "wood_boards": ("WOOD-BOARDS", "medium", 1.0, 0, "Boarded floors and decks, timber cut lengthwise"),
}


def _basket() -> list:
    """Parquet in a basket weave: 3 mm squares, each of three strips, the
    strips turning a quarter from one square to the next."""
    fams = [(0.0, 0.0, 0.0, 0.0, 3.0, ()), (90.0, 0.0, 0.0, 0.0, 3.0, ())]
    for y in (1.0, 2.0):
        fams.append((0.0, 0.0, y, 0.0, 6.0, (3.0, -3.0)))
        fams.append((0.0, 3.0, 3.0 + y, 0.0, 6.0, (3.0, -3.0)))
    for x in (1.0, 2.0):
        fams.append((90.0, 3.0 + x, 0.0, 0.0, 6.0, (3.0, -3.0)))
        fams.append((90.0, x, 3.0, 0.0, 6.0, (3.0, -3.0)))
    return fams


#: Line families: ``(angle°, x0, y0, shift along, spacing across, dashes[,
#: offset across])`` in paper mm at scale 1. Dashes: positive draws,
#: negative is a gap, 0 a dot; empty: a whole line. The offset moves the
#: family across itself — the second line of a pair.
#: The brick patterns are not here: :func:`brick_families` draws them from
#: the brick's size.
_FAMILIES = {
    "diagonal": [(45.0, 0.0, 0.0, 0.0, 1.5, ())],
    "double_diagonal": [(45.0, 0.0, 0.0, 0.0, 2.0, ()),
                        (45.0, 0.0, 0.0, 0.0, 2.0, (), 0.35)],
    "crosshatch": [(45.0, 0.0, 0.0, 0.0, 1.5, ()),
                   (135.0, 0.0, 0.0, 0.0, 1.5, ())],
    "grid": [(0.0, 0.0, 0.0, 0.0, 1.5, ()), (90.0, 0.0, 0.0, 0.0, 1.5, ())],
    "dots": [(0.0, 0.0, 0.0, 0.5, 1.0, (0.0, -1.0))],
    "fire_brick": [(45.0, 0.0, 0.0, 0.0, 1.5, ()),
                   (135.0, 0.0, 0.0, 0.0, 3.0, (1.5, -1.5))],
    # Blocks 4 × 2 mm, half a block on, with a hollow line through each.
    # Aerated concrete: big blocks, half bond, the pores scattered.
    "aac_block": [(0.0, 0.0, 0.0, 0.0, 2.0, ()),
                  (90.0, 0.0, 0.0, 2.0, 3.0, (2.0, -2.0))],
    "block": [(0.0, 0.0, 0.0, 0.0, 2.0, ()),
              (90.0, 0.0, 0.0, 2.0, 4.0, (2.0, -2.0)),
              (0.0, 1.0, 1.0, 4.0, 2.0, (2.0, -6.0))],
    # Square tiles with a joint of two lines.
    "tile": [(0.0, 0.0, 0.0, 0.0, 3.0, ()), (0.0, 0.0, 0.0, 0.0, 3.0, (), 0.25),
             (90.0, 0.0, 0.0, 0.0, 3.0, ()),
             (90.0, 0.0, 0.0, 0.0, 3.0, (), 0.25)],
    "reinforced": [(45.0, 0.0, 0.0, 0.0, 2.4, ())],
    # Groups of three lines, then a gap — the classic earth section.
    "earth": [(45.0, 0.0, 0.0, 1.0, 3.0, (2.0, -1.0)),
              (45.0, 0.0, 0.0, 1.0, 3.0, (2.0, -1.0), 0.45),
              (45.0, 0.0, 0.0, 1.0, 3.0, (2.0, -1.0), 0.9)],
    # Made ground: broken lines the other way over a sand stipple.
    "fill": [(135.0, 0.0, 0.0, 0.7, 2.0, (1.0, -1.0))],
    # Boards of rigid insulation: rectangles crossed corner to corner.
    "rigid_insulation": [(0.0, 0.0, 0.0, 0.0, 2.0, ()),
                         (90.0, 0.0, 0.0, 0.0, 4.0, ()),
                         (math.degrees(math.atan2(1.0, 2.0)), 0.0, 0.0, 0.0,
                          2.0 * math.cos(math.atan2(1.0, 2.0)), ()),
                         (180.0 - math.degrees(math.atan2(1.0, 2.0)), 0.0,
                          0.0, 0.0, 2.0 * math.cos(math.atan2(1.0, 2.0)), ())],
    # Still water: short dashes in staggered rows.
    "water": [(0.0, 0.0, 0.0, 1.8, 1.4, (2.0, -1.6)),
              (0.0, 2.2, 0.0, 1.8, 1.4, (0.8, -2.8), 0.45)],
    # Plies and their grain.
    "plywood": [(0.0, 0.0, 0.0, 0.0, 1.0, ()),
                (0.0, 0.0, 0.0, 1.7, 2.0, (2.5, -1.0), 0.5)],
    "parquet": _basket(),
    "dashed_diagonal": [(45.0, 0.0, 0.0, 0.75, 1.5, (1.0, -0.5))],
    # A cross at every node of a 3.5 mm grid.
    "plus": [(0.0, -0.8, 0.0, 0.0, 3.5, (1.6, -1.9)),
             (90.0, 0.0, -0.8, 0.0, 3.5, (1.6, -1.9))],
    # Honeycomb of 1.2 mm sides: three families, a side drawn, two skipped.
    "hexagon": [(0.0, 0.0, 0.0, 1.8, 1.2 * math.sqrt(3) / 2, (1.2, -2.4)),
                (120.0, 0.0, 0.0, 1.8, 1.2 * math.sqrt(3) / 2, (1.2, -2.4)),
                (60.0, 1.2, 0.0, 1.8, 1.2 * math.sqrt(3) / 2, (1.2, -2.4))],
    # Dressed stone: courses 3 mm high, blocks 8 mm long.
    "ashlar": [(0.0, 0.0, 0.0, 0.0, 3.0, ()),
               (90.0, 0.0, 0.0, 3.0, 4.0, (3.0, -3.0))],
    # Lifts of rammed earth over a light stipple.
    "rammed_earth": [(0.0, 0.0, 0.0, 0.0, 2.5, ())],
    # Clay: broken horizontal lines with a dot between.
    "clay": [(0.0, 0.0, 0.0, 1.3, 1.2, (2.0, -0.6)),
             (0.0, 2.3, 0.6, 1.3, 1.2, (0.0, -2.6))],
    # A membrane: a dense dash-dot line.
    "waterproofing": [(0.0, 0.0, 0.0, 0.8, 0.7, (1.5, -0.4, 0.0, -0.4))],
    # Cross-laminated timber: plies of grain along and across in turn.
    "clt": [(0.0, 0.0, 0.0, 0.0, 2.0, ()),
            (90.0, 0.0, 0.0, 0.0, 0.6, (2.0, -2.0)),
            (0.0, 0.0, 3.0, 0.8, 4.0, (1.6, -0.6))],
    # Diamonds of expanded metal.
    "mesh": [(60.0, 0.0, 0.0, 0.0, 1.4, ()), (120.0, 0.0, 0.0, 0.0, 1.4, ())],
    # Rows of ticks: crops, planted beds.
    "crops": [(90.0, 0.0, 0.0, 0.0, 1.6, (0.8, -1.4))],
    # Wetland: water's dashes; tufts are scattered over them.
    "wetland": [(0.0, 0.0, 0.0, 1.8, 1.4, (2.0, -1.6))],
    # Thin lines in close pairs.
    "steel": [(45.0, 0.0, 0.0, 0.0, 1.2, ()),
              (45.0, 0.0, 0.0, 0.0, 1.2, (), 0.3)],
    # A line and a dashed line beside it.
    "aluminium": [(45.0, 0.0, 0.0, 0.0, 2.0, ()),
                  (45.0, 0.0, 0.0, 0.0, 2.0, (1.0, -0.6), 0.5)],
    # A line and a dash-dot line between.
    "bronze": [(45.0, 0.0, 0.0, 0.0, 2.0, ()),
               (45.0, 0.0, 0.0, 0.0, 2.0, (2.0, -0.5, 0.0, -0.5), 1.0)],
    # Crossed pairs.
    "lead": [(45.0, 0.0, 0.0, 0.0, 2.0, ()),
             (45.0, 0.0, 0.0, 0.0, 2.0, (), 0.35),
             (135.0, 0.0, 0.0, 0.0, 2.0, ()),
             (135.0, 0.0, 0.0, 0.0, 2.0, (), 0.35)],
    # Long and short dashes, in pairs.
    "glass": [(45.0, 0.0, 0.0, 0.0, 2.4, (4.0, -1.5)),
              (45.0, 0.0, 0.0, 2.0, 2.4, (1.5, -4.0), 0.5)],
    # Pairs of lines with a broken one between them.
    "plastic": [(45.0, 0.0, 0.0, 0.0, 3.0, ()),
                (45.0, 0.0, 0.0, 0.0, 3.0, (), 0.5),
                (45.0, 0.0, 0.0, 0.0, 3.0, (0.8, -0.8), 1.6)],
}

#: Generated patterns: ``(kind, cell size in mm)``.
_SCATTERED = {"aac_block": ("pores", 1.1), "concrete": ("concrete", 2.0), "reinforced": ("concrete", 2.0),
              "gravel": ("gravel", 1.6), "sand": ("sand", 0.9),
              "fill": ("sand", 1.3), "stone": ("stone", 3.0),
              "rubble": ("rubble", 2.6), "roof_tile": ("scales", 3.0),
              "grass": ("grass", 2.4), "wood_end": ("rings", 5.0),
              "rammed_earth": ("plaster", 1.8), "lean_concrete": ("concrete", 3.4),
              "rock": ("rock", 3.5), "plaster": ("plaster", 1.2),
              "acoustic": ("studs", 1.5), "tactile": ("studs", 2.5),
              "osb": ("strands", 1.6), "chequer_plate": ("chequer", 2.0),
              "shrubs": ("shrubs", 3.0), "canopy": ("canopy", 5.0),
              "wetland": ("grass", 3.2), "cobblestone": ("cobbles", 2.4),
              "asphalt": ("asphalt", 0.7),
              "wood_grain": ("grain", 1.0), "wood_herringbone": ("herring5", 0.9),
              "herringbone": ("herring2", 1.6),
              "wood_open": ("grain_open", 2.0), "wood_flame": ("grain_flame", 0.85),
              "wood_boards": ("ticks", 1.5)}
#: The materials a pattern draws at their real size: ``(unit, metres)`` —
#: the pattern's own measure on paper (a brick's course, a tile, a board's
#: width, in mm at scale 1) and what it stands for in reality. Such a
#: pattern grows and shrinks with the frame's scale, unless the layer says
#: otherwise; stipples and generic hatches keep their size on paper, the
#: drawing convention (shrunk to real size they would not read).
REAL_SIZE = {
    "block": (2.0, 0.20), "aac_block": (2.0, 0.203),
    "ashlar": (3.0, 0.40), "tile": (3.0, 0.30),
    "roof_tile": (3.0, 0.25), "parquet": (3.0, 0.24),
    "herringbone": (1.6, 0.10), "wood_herringbone": (0.9, 0.07),
    "wood_boards": (1.5, 0.14), "cobblestone": (2.4, 0.12),
    "tactile": (2.5, 0.06),
}
#: The brickwork patterns: drawn from the size of the brick (a layer may
#: set its own, ``Layer.brick``) and from the bond — how stretchers (the
#: long side on the face) and headers (the short end on the face) are laid
#: course by course.
BRICKS = ("brick_auto", "brick", "brick_header", "brick_bond", "brick_cross",
          "brick_flemish", "brick_dutch", "brick_one_half", "brick_on_edge",
          "brick_rowlock", "brick_honeycomb", "hollow_brick",
          "perforated_block", "concrete_brick")
#: A brick: ``(length, width, height, joint)`` in mm. The one the patterns
#: are drawn with unless a layer says otherwise, and the usual sizes of a
#: few places (``(name, size)``), offered by the picker.
BRICK_DEFAULT = (215.0, 102.5, 65.0, 10.0)
BRICK_SIZES = (("Metric", BRICK_DEFAULT),
               ("Spain", (240.0, 115.0, 50.0, 10.0)),
               ("Chile", (290.0, 140.0, 71.0, 10.0)),
               ("Argentina", (260.0, 125.0, 55.0, 10.0)),
               ("Mexico", (280.0, 140.0, 70.0, 10.0)),
               ("Uruguay", (250.0, 120.0, 55.0, 10.0)))
#: The masonry pieces a layer sizes, by pattern: a brick, a hollow
#: ceramic block (a «ticholo») and a concrete block — each with its usual
#: sizes ``(name, (length, width, height, joint))`` in mm, the first the
#: one drawn unless the layer or the document says otherwise. (Dressed
#: stone keeps its own: no two stones alike.)
PIECE_SIZES = {
    "brick": BRICK_SIZES,
    "hollow": (("Ticholo 12", (250.0, 120.0, 170.0, 10.0)),
               ("Ticholo 8", (250.0, 80.0, 170.0, 10.0)),
               ("Hollow brick 12", (330.0, 120.0, 180.0, 10.0)),
               ("Hollow brick 18", (330.0, 180.0, 180.0, 10.0))),
    "perforated": (("Load-bearing 12", (250.0, 120.0, 190.0, 10.0)),
                   ("Load-bearing 18", (330.0, 180.0, 190.0, 10.0)),
                   ("Rejillón", (250.0, 120.0, 100.0, 10.0))),
    "cored": (("Concrete brick 12", (250.0, 120.0, 60.0, 10.0)),
              ("Concrete brick 14", (290.0, 140.0, 90.0, 10.0))),
    "block": (("Block 15", (390.0, 140.0, 190.0, 10.0)),
              ("Block 10", (390.0, 90.0, 190.0, 10.0)),
              ("Block 20", (390.0, 190.0, 190.0, 10.0))),
    # Glued: a joint of a few millimetres.
    "aac": (("Aerated 15", (600.0, 150.0, 200.0, 3.0)),
            ("Aerated 10", (600.0, 100.0, 200.0, 3.0)),
            ("Aerated 20", (600.0, 200.0, 200.0, 3.0)),
            ("Aerated 25", (600.0, 250.0, 200.0, 3.0))),
}
PIECE_DEFAULT = {kind: sizes[0][1] for kind, sizes in PIECE_SIZES.items()}


def piece_kind(key) -> str | None:
    """Which piece pattern ``key`` is made of — ``"brick"``, ``"hollow"``
    (a ticholo), ``"perforated"`` (a load-bearing ceramic block, a
    rejillón), ``"cored"`` (a precast concrete brick with holes),
    ``"block"``, ``"aac"`` (aerated concrete) — or ``None`` for
    one with no size to set."""
    if key == "block":
        return "block"
    if key == "aac_block":
        return "aac"
    if key == "hollow_brick":
        return "hollow"
    if key == "perforated_block":
        return "perforated"
    if key == "concrete_brick":
        return "cored"
    return "brick" if key in BRICKS else None


#: What a brick size may be, in mm: ``(least, most)`` of its length, width,
#: height and joint.
_BRICK_LIMITS = ((60.0, 600.0), (30.0, 400.0), (20.0, 400.0), (0.0, 40.0))
for _key in BRICKS:
    REAL_SIZE[_key] = (1.5, (BRICK_DEFAULT[2] + BRICK_DEFAULT[3]) / 1000.0)

#: Masonry laid in courses: drawn as it is built — in a plan, the top of a
#: course, brick by brick along each wall; in a vertical section through a
#: wall, the courses stacked and each split where its bricks meet; cut along
#: a wall, its face (see :func:`bond_marks`).
COURSED = frozenset(BRICKS) | {"block", "aac_block", "ashlar"}
#: The patterns made of pieces — bricks, blocks, stones, tiles, boards,
#: pavers — where it shows where the first joint falls, so a layer can
#: shift them (``Layer.hatch_offset``). Lines and textures read the same
#: wherever they start.
PLACED = COURSED | {"fire_brick", "stone", "tile", "roof_tile", "wood_boards",
                    "parquet", "wood_herringbone", "clt", "herringbone",
                    "cobblestone", "tactile", "chequer_plate", "grid"}
#: The thickest piece, in real mm, still drawn brick by brick: in a plan, a
#: wall (thicker, a paved area); in a vertical section, a wall cut across
#: (wider, one cut along: its face).
_BOND_THICKEST = {"plan": 1500.0, "vertical": 700.0}
#: Bonds whose face is another's: they part in a plan or a section (by
#: thickness: the bond each wall takes; one and a half: a header on one
#: face, a stretcher on the other).
SAME_FACE = {"brick_auto": "brick", "brick_one_half": "brick_bond"}
#: Dressed stone: ``(length, course height)`` in mm.
_UNITS = {"ashlar": (800.0, 400.0)}

#: However large or small the scale, a real-size pattern is drawn between
#: these many times its own size: smaller is a grey blur, larger a few
#: lines lost in the cut.
_REAL_LIMITS = (0.25, 12.0)


def clean_brick(raw) -> tuple | None:
    """A brick size as a layer stores it, read back defensively: ``(length,
    width, height, joint)`` in mm within reason, the width no more than the
    length — or ``(length, width, height, bed joint, head joint)`` when the
    horizontal joint (the bed, under each course) and the vertical one (the
    head, between two bricks) differ; ``None`` for anything else. Equal
    joints come back as one."""
    try:
        size = tuple(float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if len(size) not in (4, 5) or not all(math.isfinite(v) for v in size):
        return None
    limits = _BRICK_LIMITS + (_BRICK_LIMITS[3],)
    if any(not lo <= v <= hi for v, (lo, hi) in zip(size, limits)):
        return None
    if size[1] > size[0]:
        return None
    if len(size) == 5 and abs(size[3] - size[4]) < 1e-9:
        size = size[:4]
    return size


def brick_dims(brick=None, kind: str = "brick") -> tuple:
    """``(length, width, height, bed joint, head joint)`` of ``brick`` (a
    layer's, the document's) in mm — the usual piece of ``kind`` when it
    has none: the bed joint lies under each course, the head joint stands
    between two pieces of a course and between the wythes of a wall."""
    size = clean_brick(brick) or PIECE_DEFAULT.get(kind, BRICK_DEFAULT)
    return size if len(size) == 5 else size + (size[3],)


def real_unit(key, brick=None) -> tuple | None:
    """``(unit, metres)`` of a real-size pattern — REAL_SIZE's, a brick
    pattern's from ``brick`` (its course: height and joint)."""
    if key in BRICKS:
        b = brick_dims(brick, piece_kind(key))
        return 1.5, (b[2] + b[3]) / 1000.0     # height and bed joint
    if key in ("block", "aac_block"):
        b = brick_dims(brick, piece_kind(key))
        return REAL_SIZE[key][0], (b[2] + b[3]) / 1000.0
    return REAL_SIZE.get(key)


def real_scale(key, scale_n: float, brick=None) -> float | None:
    """How many times its own size pattern ``key`` is drawn on a sheet at
    1:``scale_n`` to show the material at its real size (kept within
    readable limits); ``None`` for a pattern with no real size. A brick
    pattern measures its course with ``brick`` (``Layer.brick``)."""
    if key not in REAL_SIZE:
        return None
    unit, metres = real_unit(key, brick)
    factor = metres * 1000.0 / max(1e-6, float(scale_n or 100.0)) / unit
    return min(_REAL_LIMITS[1], max(_REAL_LIMITS[0], factor))


#: Patterns drawn turned from their families (degrees).
_TURN = {"herringbone": 45.0, "wood_herringbone": 45.0,
         "wood_flame": 25.0, "wood_diagonal": 35.0}

#: Waves: ``(band height, period, amplitude)`` in mm.
_WAVES = {"wood": (1.0, 7.0, 0.35), "wood_diagonal": (1.7, 14.0, 0.35)}
#: Patterns fitted to each cut piece instead of laid on the paper: the
#: soft insulation symbol spans the layer's thickness, whatever it is and
#: whichever way the layer runs. Laid on the paper (swatches, legends), it
#: comes in bands of this thickness, in mm.
FITTED = {"insulation": 3.0, "insulation_zigzag": 3.0, "wood_cross": 3.0}
#: The insulation symbol: the radius of its half loops, as a share of the
#: layer's thickness — arches against one face and cups against the other,
#: each touching the next on its face.
_BATT_RADIUS = 0.22


#: The key prefix of a pattern brought in from a pattern file (``.pat``) and
#: kept in the document (``Scene.hatch_patterns``): ``"pat:<name>"``.
IMPORTED = "pat:"
#: A pattern file's limits: what a reasonable pattern needs, and no more —
#: a file is data from anywhere.
_MAX_FAMILIES = 64
_MAX_DASHES = 32
#: The fewest millimetres between two lines of a family: closer, and a big
#: cut would be inked with hundreds of thousands of lines.
_MIN_SPACING = 0.05


def brick_families(key, brick=None) -> list:
    """The families of brick pattern ``key`` seen on the face of the wall,
    from ``brick`` (``(length, width, height, joint)`` mm; the default one
    when ``None``): the course 1.5 mm high, the rest in proportion — a
    stretcher as long as the brick, a header as wide."""
    length, width, height, bed_joint, head = brick_dims(brick,
                                                       piece_kind(key))
    u = 1.5 / (height + bed_joint)
    ls, ws, hs = (length + head) * u, (width + head) * u, 1.5
    bed = [(0.0, 0.0, 0.0, 0.0, hs, ())]

    def stretchers(h):
        # Every course half a brick on from the one below.
        return [(0.0, 0.0, 0.0, 0.0, h, ()),
                (90.0, 0.0, 0.0, h, ls / 2.0, (h, -h))]
    if key == "brick_on_edge":         # on edge: the course as high as wide
        return stretchers((width + bed_joint) * u)
    if key == "brick_rowlock":         # standing ends, side by side
        return [(0.0, 0.0, 0.0, 0.0, (width + bed_joint) * u, ()),
                (90.0, 0.0, 0.0, 0.0, (height + head) * u, ())]
    if key == "brick_header":
        return bed + [(90.0, 0.0, 0.0, hs, ws / 2.0, (hs, -hs))]
    if key in ("brick_bond", "brick_one_half"):
        # A course of stretchers, a course of headers over their joints.
        return bed + [(90.0, 0.0, 0.0, 0.0, ls, (hs, -hs)),
                      (90.0, ws / 2.0, hs, 0.0, ws, (hs, -hs))]
    if key == "brick_cross":
        # English, every second course of stretchers half a brick on.
        return bed + [(90.0, 0.0, 0.0, 0.0, ls, (hs, -3.0 * hs)),
                      (90.0, ls / 2.0, 2.0 * hs, 0.0, ls, (hs, -3.0 * hs)),
                      (90.0, ws / 2.0, hs, 0.0, ws, (hs, -hs))]
    if key in ("brick_flemish", "brick_dutch"):
        # A stretcher and a header in turn along the course; Flemish: the
        # header centred on the stretcher below; Dutch: a course of
        # headers between.
        p = ls + ws
        fams = bed + [(90.0, 0.0, 0.0, 0.0, p, (hs, -hs)),
                      (90.0, ls, 0.0, 0.0, p, (hs, -hs))]
        if key == "brick_dutch":
            return fams + [(90.0, ws / 2.0, hs, 0.0, ws, (hs, -hs))]
        return fams + [(90.0, ls / 2.0 - ws / 2.0, hs, 0.0, p, (hs, -hs)),
                       (90.0, ls / 2.0 + ws / 2.0, hs, 0.0, p, (hs, -hs))]
    if key == "brick_honeycomb":
        # Stretchers with a gap of half a brick between, staggered.
        gap = ls / 2.0
        half = (ls + gap) / 2.0
        return bed + [(90.0, 0.0, 0.0, hs, half, (hs, -hs)),
                      (90.0, gap, 0.0, hs, half, (hs, -hs))]
    fams = stretchers(hs)              # stretcher bond, by thickness, hollow
    if key == "hollow_brick":
        k = ls / 6.0                   # the holes as short dashes
        fams.append((0.0, 0.6 * k, hs / 2.0, ls / 2.0, hs,
                     tuple(d * k for d in (0.9, -0.4, 0.9, -0.4, 0.9, -2.5))))
    return fams


for _key in BRICKS:
    _FAMILIES[_key] = brick_families(_key)


def vertical_band(ring) -> tuple | None:
    """A piece of a vertical section as :func:`fit_band` gives one, but
    upright whatever its shape: along the paper's up (courses are
    horizontal), across its width."""
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    if len(xs) < 3:
        return None
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w <= 1e-9 or h <= 1e-9:
        return None
    return (min(xs), max(ys)), (0.0, -1.0), (1.0, 0.0), h, w


def _english(k: int, n: int) -> list:
    """The wythes across a wall ``n`` half bricks thick in course ``k`` of
    English bond (``"S"`` a stretcher, ``"H"`` a header), from the near
    face: a course of headers (and a stretcher on one face, when the wall
    has an odd half), then the other way round — one and a half bricks is
    a stretcher on one face and a header on the other, swapped course by
    course."""
    if n <= 1:
        return ["S"]
    heads, odd = n // 2, n % 2
    if k % 2 == 0:
        return (["S"] if odd else []) + ["H"] * heads
    if odd:
        return ["H"] * heads + ["S"]
    return ["S"] + ["H"] * ((n - 2) // 2) + ["S"]


def _row(rects, b0, b1, length, offset, lo, hi, kind="brick") -> None:
    i0 = math.floor((lo - offset) / length) - 1
    i1 = math.ceil((hi - offset) / length) + 1
    if i1 - i0 > 4000:
        return
    for i in range(i0, i1 + 1):
        a0 = offset + i * length
        rects.append((a0, a0 + length, b0, b1, kind))


def bond_course(key, k: int, thick: float, brick=None, lo: float = 0.0,
                hi: float = 0.0) -> tuple:
    """Course ``k`` of masonry pattern ``key`` in a wall ``thick`` mm thick,
    as built: ``(depth, height, pieces)`` — the course's depth across the
    wall (its pieces fill it), its height, and its pieces between ``lo`` and
    ``hi`` along the wall: ``(a0, a1, b0, b1, kind)`` in mm, ``kind`` one
    of ``"brick"``, ``"hollow"``, ``"block"``, ``"gap"`` (an open one)."""
    length, width, height, bed, head = brick_dims(brick, piece_kind(key))
    # Along the course and across the wall, a brick and a head joint; up
    # the wall, a brick and a bed joint.
    ls, ws, hs = length + head, width + head, height + bed
    rects: list = []
    if key in ("block", "aac_block"):  # one through the wall, half bond
        _row(rects, 0.0, thick, ls, (k % 2) * ls / 2.0, lo, hi,
             "block" if key == "block" else "aac")
        return thick, hs, rects
    if key in _UNITS:
        unit, course = _UNITS[key]
        _row(rects, 0.0, thick, unit, (k % 2) * unit / 2.0, lo, hi)
        return thick, course, rects
    n = max(1, round((thick + head) / ws))
    if key == "brick_auto":
        key = ("brick_on_edge" if thick < (width + height) / 2.0
               else "brick" if n == 1 else "brick_bond")
    if key == "brick_on_edge":
        _row(rects, 0.0, height + head, ls, (k % 2) * ls / 2.0, lo, hi)
        return height + head, width + bed, rects
    if key == "brick_rowlock":
        _row(rects, 0.0, ls, height + head, 0.0, lo, hi)
        return ls, width + bed, rects
    if key == "brick_honeycomb":
        gap = ls / 2.0
        p = ls + gap
        off = (k % 2) * p / 2.0
        _row(rects, 0.0, ws, p, off, lo, hi, "gap")
        _row(rects, 0.0, ws, p, off + gap, lo, hi)
        # Each piece as long as itself: a gap, then a brick.
        rects = [(a0, a0 + (gap if kind == "gap" else ls), b0, b1, kind)
                 for a0, a1, b0, b1, kind in rects]
        return ws, hs, rects
    if key == "brick_header":
        m = max(1, round((thick + head) / ls))
        for w in range(m):
            _row(rects, w * ls, (w + 1) * ls, ws, (k % 2) * ws / 2.0, lo, hi)
        return m * ls, hs, rects
    if key in ("brick", "hollow_brick", "perforated_block",
               "concrete_brick"):
        kind = {"hollow_brick": "hollow", "perforated_block": "perforated",
                "concrete_brick": "cored"}.get(key, "brick")
        for w in range(n):
            _row(rects, w * ws, (w + 1) * ws, ls, ((k + w) % 2) * ls / 2.0,
                 lo, hi, kind)
        return n * ws, hs, rects
    if key == "brick_flemish" or (key == "brick_dutch" and k % 2 == 0):
        # A pair of stretchers, a header through the wall, in turn.
        p = ls + ws
        off = ((k if key == "brick_flemish" else k // 2) % 2) * p / 2.0
        i0 = math.floor((lo - off) / p) - 1
        i1 = math.ceil((hi - off) / p) + 1
        for i in range(i0, min(i1, i0 + 4000) + 1):
            a = off + i * p
            rects += [(a, a + ls, 0.0, ws, "brick"),
                      (a, a + ls, ws, 2 * ws, "brick"),
                      (a + ls, a + p, 0.0, 2 * ws, "brick")]
        return 2 * ws, hs, rects
    if key == "brick_dutch":           # its header courses
        _row(rects, 0.0, ls, ws, ws / 2.0, lo, hi)
        return ls, hs, rects
    # English and its kin: headers over the stretchers' joints.
    if key == "brick_one_half":
        n = 3
    n = max(2, min(8, n))
    shift = (((k // 2) % 2) * ls / 2.0 if key == "brick_cross" else 0.0)
    b = 0.0
    for w in _english(k, n):
        if w == "S":
            _row(rects, b, b + ws, ls, shift, lo, hi)
            b += ws
        else:
            _row(rects, b, b + ls, ws, ws / 2.0, lo, hi)
            b += ls
    return b, hs, rects


#: How masonry joints are drawn: as one line, as two (the joint's real
#: thickness), not at all (the outline only); ``None`` — by the sheet's
#: scale (:func:`joints_mode`).
JOINTS = ("single", "double", "none")
#: The automatic joints: a 45° hatch at 1:``[1]`` and smaller (a brick is
#: a couple of millimetres: drawn, it is a grey blur), single lines down to
#: 1:``[0]``, the joint's real thickness from there on (1 cm: 1 mm at 1:10).
JOINTS_AUTO = (15.0, 75.0)


def joints_mode(joints, scale_n: float = 100.0) -> str:
    """How a sheet at 1:``scale_n`` draws masonry joints: ``"single"``,
    ``"double"``, ``"none"`` or ``"hatch"`` (no bricks: the 45° hatch) — as
    the layer says (``Layer.joints``), else by the scale."""
    if joints in JOINTS:
        return joints
    n = float(scale_n or 100.0)
    if n >= JOINTS_AUTO[1]:
        return "hatch"
    return "double" if n <= JOINTS_AUTO[0] else "single"


def _face_thick(key, brick) -> float:
    """The wall a bond's face is taken from, in mm: the thickness the bond
    is laid in."""
    length, width, height, _bed, head = brick_dims(brick, piece_kind(key))
    if key in ("brick", "hollow_brick", "brick_honeycomb", "block",
               "aac_block", "perforated_block", "concrete_brick"):
        return width
    if key == "brick_on_edge":
        return height
    if key == "brick_one_half":
        return length + width + head
    return length


def bond_marks(key, band, cut: str, scale: float = 1.0,
               scale_n: float = 100.0, brick=None,
               joints: str = "single", offset=None) -> dict | None:
    """Masonry drawn as it is built in one cut piece ``band`` (``(origin,
    along, across, length, thick)`` in paper mm, as :func:`fit_band` or
    :func:`vertical_band` give it): in a ``"plan"``, the top of a course,
    brick by brick along the wall; in a ``"vertical"`` section, the courses
    stacked along ``along`` (up), each split across where its bricks meet.
    The pieces fill the thickness; along the wall they measure their size
    ``scale`` times (as the pattern's: real at 1:``scale_n``, or on paper),
    the bond chosen from the wall's real thickness. A piece too thick for a
    wall (a paved area, a wall cut along) shows the bond's face, brick by
    brick. ``joints``: ``"single"`` — a line at every joint; ``"double"`` —
    each brick its own outline, the joint's real thickness between.
    ``{"lines", "polys", "bricks"}`` in paper mm (``bricks``: the closed
    outlines of the double joints, to fill and ink); ``None`` for no
    masonry or no piece.

    Each piece starts as a wall is built: a whole brick at its end (the
    left one, or the top one on the paper) in a plan, the first course at
    its foot in a section. ``offset`` — ``(x, y)`` in real mm — moves the
    first joint along the wall (``x``, a plan) and the first course up it
    (``y``, a section); a paved area or a wall's face moves both ways."""
    if key not in COURSED or band is None or cut not in _BOND_THICKEST:
        return None
    origin, along, across, length, thick = band
    if thick <= 1e-6 or length <= 1e-6:
        return None
    unit, metres = real_unit(key, brick)
    per_mm = max(1e-6, float(scale)) * unit / (metres * 1000.0)
    real = thick * max(1e-6, float(scale_n or 100.0))
    out: dict = {"lines": [], "polys": [], "bricks": []}
    ox, oy = (float(offset[0]), float(offset[1])) if offset else (0.0, 0.0)
    # One way round for every piece — along a plan's wall rightwards (or
    # down the paper), up a section — across it to its left — so the
    # pieces of one wall agree.
    if cut == "vertical":
        flip = along[1] > 1e-9 or (abs(along[1]) <= 1e-9 and along[0] < 0)
    else:
        flip = along[0] < -1e-9 or (abs(along[0]) <= 1e-9 and along[1] < 0)
    if flip:
        origin = (origin[0] + along[0] * length, origin[1] + along[1] * length)
        along = (-along[0], -along[1])
    left = (-along[1], along[0])
    if across[0] * left[0] + across[1] * left[1] < 0:
        origin = (origin[0] + across[0] * thick, origin[1] + across[1] * thick)
    across = left
    # Where along the bond the piece begins, in real mm: at its own end,
    # as a wall is laid — a whole brick at a corner or a jamb, the first
    # course at the foot — then where the layer moves it.
    start = -(oy if cut == "vertical" else ox)
    length_, width, height, bed, head = brick_dims(brick, piece_kind(key))
    if key in _UNITS:
        bed = head = 10.0
    double = joints == "double"
    # Half a joint each side of a brick: the head joint along the course
    # and across the wall, the bed joint up it.
    half_b, half_h = bed / 2.0, head / 2.0

    def piece(at, a0, a1, b0, b1, depth, kind, cells=None,
              ha=None) -> None:
        """One brick: its outline inset by half a joint (double; not on the
        wall's faces) — ``ha`` along ``a`` (the head joint's by default),
        the head joint's across — or the joint before it and under it
        (single)."""
        ha = half_h if ha is None else ha
        if kind == "gap":              # an open gap: crossed, and closed
            out["lines"].append(at(a0, b0) + at(a1, b1))
            out["lines"].append(at(a0, b1) + at(a1, b0))
            # Both its sides: a brick draws only the joint before it, so the
            # side of a gap that follows a brick was left open.
            out["lines"].append(at(a0, b0) + at(a0, b1))
            out["lines"].append(at(a1, b0) + at(a1, b1))
            return
        if double:
            c0 = b0 + (half_h if b0 > 1e-6 else 0.0)
            c1 = b1 - (half_h if b1 < depth - 1e-6 else 0.0)
            if a1 - a0 > 2.0 * ha and c1 > c0:
                out["bricks"].append([at(a0 + ha, c0), at(a1 - ha, c0),
                                      at(a1 - ha, c1), at(a0 + ha, c1),
                                      at(a0 + ha, c0)])
        else:
            out["lines"].append(at(a0, b0) + at(a0, b1))
            if b0 > 1e-6:
                out["lines"].append(at(a0, b0) + at(a1, b0))
        if cells is not None:
            cells()

    span = length / per_mm             # the piece's length, in real mm
    if real > _BOND_THICKEST[cut]:
        # No wall: the face of the bond, its courses up the paper (a wall
        # cut along) or across the piece (a paved area).
        if cut == "vertical":
            # Upright whatever the piece: along the paper, courses up it.
            u_ax, v_ax = (1.0, 0.0), (0.0, -1.0)
            xs = (origin[0], origin[0] + across[0] * thick
                  + along[0] * length)
            ys = (origin[1], origin[1] + across[1] * thick
                  + along[1] * length)
            u_len, v_len = abs(xs[1] - xs[0]), abs(ys[1] - ys[0])
            corner = (min(xs), max(ys))
        else:
            u_ax, v_ax, u_len, v_len = along, across, length, thick
            corner = origin
        # Locked to the paper (a paved area runs on under a wall), then
        # moved as the layer says.
        u0 = (corner[0] * u_ax[0] + corner[1] * u_ax[1]) / per_mm - ox
        v0 = (corner[0] * v_ax[0] + corner[1] * v_ax[1]) / per_mm - oy

        def at(u, v):
            # (u, v) on the paper's own grid, in real mm.
            return (corner[0] + (u_ax[0] * (u - u0) + v_ax[0] * (v - v0))
                    * per_mm,
                    corner[1] + (u_ax[1] * (u - u0) + v_ax[1] * (v - v0))
                    * per_mm)
        _d, course, _r = bond_course(key, 0, 0.0, brick, 0.0, 0.0)
        u_real, v_real = u_len / per_mm, v_len / per_mm
        k0 = math.floor(v0 / course)
        courses = int(math.ceil((v0 + v_real) / course)) - k0 + 1
        if courses * max(1.0, u_real / max(1.0, width)) > 20000:
            return None
        face = _face_thick(key, brick)
        for k in range(k0, k0 + courses):
            c0, c1 = k * course, (k + 1) * course
            _d, _h, rects = bond_course(key, k, face, brick, u0, u0 + u_real)
            if not double:
                out["lines"].append(at(u0, c0) + at(u0 + u_real, c0))
            for a0, a1, b0, _b1, kind in rects:
                if b0 > 1e-6:          # only the wythe on the face
                    continue
                if kind == "gap":
                    piece(lambda u, v: at(u, v), a0, a1, c0, c1, 1e9, kind)
                elif double:
                    out["bricks"].append([at(a0 + half_h, c0 + half_b),
                                          at(a1 - half_h, c0 + half_b),
                                          at(a1 - half_h, c1 - half_b),
                                          at(a0 + half_h, c1 - half_b),
                                          at(a0 + half_h, c0 + half_b)])
                else:
                    out["lines"].append(at(a0, c0) + at(a0, c1))
        return out

    def fitted(depth):
        def at(a, b):
            aa, bb = (a - start) * per_mm, b * thick / depth
            return (origin[0] + along[0] * aa + across[0] * bb,
                    origin[1] + along[1] * aa + across[1] * bb)
        return at

    if cut == "plan":
        depth, _h, rects = bond_course(key, 0, real, brick, start,
                                       start + span)
        if len(rects) > 4000:
            return None
        at = fitted(depth)
        for a0, a1, b0, b1, kind in rects:
            cells = None
            if kind == "block":
                cells = (lambda a0=a0, a1=a1, b0=b0, b1=b1:
                         _block_cells(out, lambda a, b, _d: at(a, b), a0, a1,
                                      b0, b1, depth))
            elif kind == "perforated":
                cells = (lambda a0=a0, a1=a1, b0=b0, b1=b1:
                         _upright_holes(out, at, a0 + half_h, a1 - half_h,
                                        b0, b1))
            elif kind == "aac":
                cells = (lambda a0=a0, a1=a1, b0=b0, b1=b1:
                         _pores(out, at, a0, a1, b0, b1))
            elif kind == "cored":
                cells = (lambda a0=a0, a1=a1, b0=b0, b1=b1:
                         _cores(out, at, a0 + half_h, a1 - half_h, b0, b1))
            piece(at, a0, a1, b0, b1, depth, kind, cells)
        return out
    # A vertical section across the wall.
    _d, course, _r = bond_course(key, 0, real, brick, 0.0, 0.0)
    k0 = math.floor(start / course)
    courses = int(math.ceil((start + span) / course)) - k0 + 1
    if courses > 2000:
        return None
    probe = 0.6 * (width + head)       # where the section cuts each course
    for k in range(k0, k0 + courses):
        a0, a1 = k * course, (k + 1) * course
        depth, _h, rects = bond_course(key, k, real, brick, probe, probe)
        at = fitted(depth)
        if not double:
            out["lines"].append(at(a0, 0.0) + at(a0, depth))  # bed joint
        for r0, r1, b0, b1, kind in rects:
            if not r0 < probe < r1:
                continue
            cells = None
            if kind == "hollow":
                cells = (lambda a0=a0, a1=a1, b0=b0, b1=b1, at=at, d=depth:
                         _hollow_cells(out, lambda a, b, _d: at(a, b),
                                       a0 + (half_b if double else 0),
                                       a0 + (a1 - a0) * height
                                       / (height + bed), b0, b1, d, width))
            elif kind == "perforated":
                def cells(a0=a0, a1=a1, b0=b0, b1=b1, at=at):
                    # Cut through its upright holes: the webs between
                    # them, the height of the piece.
                    top = a0 + (a1 - a0) * height / (height + bed)
                    cols = max(2, round((b1 - b0) / 30.0))
                    for i in range(1, cols):
                        b = b0 + (b1 - b0) * i / cols
                        out["lines"].append(at(a0, b) + at(top, b))
            elif kind == "aac":
                def cells(a0=a0, a1=a1, b0=b0, b1=b1, at=at):
                    _pores(out, at, a0, a1, b0, b1)
            elif kind == "cored":
                def cells(a0=a0, a1=a1, b0=b0, b1=b1, at=at):
                    # Cut through one of its holes: its two sides, the
                    # height of the piece.
                    top = a0 + (a1 - a0) * height / (height + bed)
                    for f in (0.25, 0.75):
                        b = b0 + (b1 - b0) * f
                        out["lines"].append(at(a0, b) + at(top, b))
            elif kind == "block":
                def cells(a0=a0, a1=a1, b0=b0, b1=b1, at=at):
                    shell = min(32.0, 0.25 * (b1 - b0))
                    out["lines"].append(at(a0, b0 + shell)
                                        + at(a1, b0 + shell))
                    out["lines"].append(at(a0, b1 - shell)
                                        + at(a1, b1 - shell))
            if double:
                # Up the section, a course: the bed joint above and below.
                piece(at, a0, a1, b0, b1, depth, kind, cells, ha=half_b)
            else:
                # The bed joint is drawn whole above: only where two
                # bricks of the course meet.
                if kind == "gap":
                    piece(at, a0, a1, b0, b1, depth, kind)
                    continue
                if b0 > 1e-6:
                    out["lines"].append(at(a0, b0) + at(a1, b0))
                if cells is not None:
                    cells()
    return out


def paper_offset(form) -> tuple | None:
    """A layer's shift of its pattern (``form["offset"]``, real mm, y up)
    on a sheet at 1:``form["scale_n"]``: paper mm, y down — or ``None``."""
    off = (form or {}).get("offset")
    if not off or not (off[0] or off[1]):
        return None
    n = max(1e-6, float((form or {}).get("scale_n", 100.0) or 100.0))
    return float(off[0]) / n, -float(off[1]) / n


def shift_marks(marks, dx: float, dy: float) -> dict:
    """``marks`` (as :func:`hatch_marks` gives them) moved by ``(dx,
    dy)``."""
    out = dict(marks)
    out["lines"] = [(x0 + dx, y0 + dy, x1 + dx, y1 + dy)
                    for x0, y0, x1, y1 in marks.get("lines", ())]
    out["dots"] = [(x + dx, y + dy) for x, y in marks.get("dots", ())]
    out["circles"] = [(x + dx, y + dy, r)
                      for x, y, r in marks.get("circles", ())]
    for key in ("polys", "closed", "bricks"):
        if key in marks:
            out[key] = [[(x + dx, y + dy) for x, y in pts]
                        for pts in marks[key]]
    return out


def _segments(marks) -> list:
    """Every mark as straight segments ``(x0, y0, x1, y1)``: lines as they
    are, polylines and outlines edge by edge, circles as 16-sided rounds;
    dots, which a line drawing cannot hold, left out."""
    out = list(marks.get("lines", ()))
    for key in ("polys", "closed", "bricks"):
        for pts in marks.get(key, ()):
            pts = list(pts)
            if key == "closed" and len(pts) > 2:
                pts.append(pts[0])
            out += [(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])]
    for x, y, r in marks.get("circles", ()):
        ring = [(x + r * math.cos(2 * math.pi * i / 16),
                 y + r * math.sin(2 * math.pi * i / 16)) for i in range(17)]
        out += [(a[0], a[1], b[0], b[1]) for a, b in zip(ring, ring[1:])]
    return out


def clip_segments(lines, rings) -> list:
    """The parts of ``lines`` (``(x0, y0, x1, y1)``) inside ``rings``,
    even-odd — a hollow wall stays hollow — as segments."""
    rings = [[(float(x), float(y)) for x, y in r] for r in rings
             if len(r) >= 3]
    boxes = [(min(p[0] for p in r), min(p[1] for p in r),
              max(p[0] for p in r), max(p[1] for p in r)) for r in rings]

    def inside(x, y) -> bool:
        hit = False
        for r, b in zip(rings, boxes):
            if not (b[0] <= x <= b[2] and b[1] <= y <= b[3]):
                continue
            for (ax, ay), (bx, by) in zip(r, r[1:] + r[:1]):
                if (ay > y) != (by > y) and \
                        x < ax + (y - ay) * (bx - ax) / (by - ay):
                    hit = not hit
        return hit
    out = []
    for x0, y0, x1, y1 in lines:
        dx, dy = x1 - x0, y1 - y0
        lo = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        ts = [0.0, 1.0]
        for r, b in zip(rings, boxes):
            if b[0] > lo[2] or b[2] < lo[0] or b[1] > lo[3] or b[3] < lo[1]:
                continue
            for (ax, ay), (bx, by) in zip(r, r[1:] + r[:1]):
                ex, ey = bx - ax, by - ay
                den = dx * ey - dy * ex
                if abs(den) < 1e-12:
                    continue
                t = ((ax - x0) * ey - (ay - y0) * ex) / den
                u = ((ax - x0) * dy - (ay - y0) * dx) / den
                if 0.0 < t < 1.0 and -1e-9 <= u <= 1.0 + 1e-9:
                    ts.append(t)
        ts.sort()
        for t0, t1 in zip(ts, ts[1:]):
            if t1 - t0 < 1e-9:
                continue
            tm = (t0 + t1) / 2.0
            if inside(x0 + dx * tm, y0 + dy * tm):
                out.append((x0 + dx * t0, y0 + dy * t0,
                            x0 + dx * t1, y0 + dy * t1))
    return out


def fill_quads(rings) -> list:
    """The region inside ``rings`` (even-odd: a hollow wall stays hollow)
    cut into horizontal strips, each a quadrilateral ``((x, y) bottom left,
    bottom right, top left, top right)`` — what a DXF R12 SOLID holds (it
    has no hatch), so a solid fill reaches any CAD as it is."""
    rings = [[(float(x), float(y)) for x, y in r] for r in rings
             if len(r) >= 3]
    edges = [(a, b) for r in rings for a, b in zip(r, r[1:] + r[:1])
             if abs(a[1] - b[1]) > 1e-12]
    ys = sorted({p[1] for r in rings for p in r})
    out = []

    def x_at(edge, y):
        (ax, ay), (bx, by) = edge
        return ax + (y - ay) * (bx - ax) / (by - ay)
    for y0, y1 in zip(ys, ys[1:]):
        if y1 - y0 < 1e-12:
            continue
        ym = (y0 + y1) / 2.0
        live = sorted((e for e in edges
                       if min(e[0][1], e[1][1]) < ym < max(e[0][1], e[1][1])),
                      key=lambda e: x_at(e, ym))
        for left, right in zip(live[0::2], live[1::2]):
            out.append(((x_at(left, y0), y0), (x_at(right, y0), y0),
                        (x_at(left, y1), y1), (x_at(right, y1), y1)))
    return out


def hatch_lines(key, rings, form=None, frame_scale: float = 1.0,
                depths=None) -> list:
    """Pattern ``key`` over the cut ``rings`` (paper mm, y down) as a
    sheet draws it — turned, sized, masonry as it is built, fitted
    patterns piece by piece, wood crossed where it is cut across — but as
    straight segments clipped to the rings: what a DXF can hold. ``form``
    as core.layers.cut_hatch_forms gives it (plus ``"cut"``); ``frame_scale``
    the frame's own hatch size (its spacing / 1.5); ``depths`` how far each
    ring's solid runs through the plane (paper mm, ``None`` unknown) — the
    grain of timber. Solid fills and the dots of stipples have no line form
    and stay out."""
    form = form or {}
    rings = [[(float(x), float(y)) for x, y in r] for r in rings
             if len(r) >= 3]
    if not rings or key in (None, "solid"):
        return []
    cut = form.get("cut")
    n = float(form.get("scale_n", 100.0) or 100.0)
    scale = frame_scale * float(form.get("scale", 1.0) or 1.0)
    out = []
    if key in WOOD and form.get("cross") and cut:
        rest = []
        depths = list(depths) if depths is not None else [None] * len(rings)
        for r, depth in zip(rings, depths):
            band = fit_band(r)
            if cut_across(band, n, depth):
                out += clip_segments(_segments(
                    {"polys": fitted_marks("wood_cross", *band)}), [r])
            else:
                rest.append(r)
        rings = rest
        if not rings:
            return out
    if key in COURSED and cut in ("plan", "vertical"):
        mode = joints_mode(form.get("joints"), n)
        if mode == "none":
            return out
        if mode == "hatch":
            key, scale = "diagonal", frame_scale * float(
                form.get("hatch_scale", 1.0) or 1.0)
        else:
            for r in rings:
                band = fit_band(r) if cut == "plan" else vertical_band(r)
                marks = bond_marks(key, band, cut, scale, n,
                                   form.get("brick"), mode,
                                   form.get("offset"))
                if marks is not None:
                    out += clip_segments(_segments(marks), [r])
            return out
    if key in FITTED:
        for r in rings:
            band = fit_band(r)
            if band is not None:
                out += clip_segments(_segments(
                    {"polys": fitted_marks(key, *band)}), [r])
        return out
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    marks = hatch_marks(key, (min(xs), min(ys), max(xs), max(ys)), scale,
                        float(form.get("angle", 0.0) or 0.0),
                        form.get("families") if key not in COURSED
                        or key in BRICKS else None,
                        paper_offset(form) if key in PLACED else None)
    return out + clip_segments(_segments(marks), rings)


def _upright_holes(out, at, a0, a1, b0, b1) -> None:
    """A load-bearing ceramic block (a rejillón) seen from above: the grid
    of its upright holes, about 3 cm each way."""
    if a1 <= a0 or b1 <= b0:
        return
    cols = max(3, round((a1 - a0) / 32.0))
    rows = max(2, round((b1 - b0) / 32.0))
    if cols * rows > 400:
        return
    cw, ch = (a1 - a0) / cols, (b1 - b0) / rows
    for i in range(cols):
        for j in range(rows):
            x0, x1 = a0 + i * cw + 0.22 * cw, a0 + (i + 1) * cw - 0.22 * cw
            y0, y1 = b0 + j * ch + 0.22 * ch, b0 + (j + 1) * ch - 0.22 * ch
            out["polys"].append([at(x0, y0), at(x1, y0), at(x1, y1),
                                 at(x0, y1), at(x0, y0)])


def _cores(out, at, a0, a1, b0, b1) -> None:
    """A precast concrete brick seen from above: its few large holes in a
    row along it, half its width wide."""
    if a1 <= a0 or b1 <= b0:
        return
    n = max(2, min(4, round((a1 - a0) / 80.0)))
    cell = (a1 - a0) / n
    for i in range(n):
        x0, x1 = a0 + i * cell + 0.2 * cell, a0 + (i + 1) * cell - 0.2 * cell
        y0, y1 = b0 + 0.25 * (b1 - b0), b1 - 0.25 * (b1 - b0)
        out["polys"].append([at(x0, y0), at(x1, y0), at(x1, y1), at(x0, y1),
                             at(x0, y0)])


def _pores(out, at, a0, a1, b0, b1) -> None:
    """The pores of aerated concrete in a piece: small rounds scattered a
    few centimetres apart, the same wherever the piece is drawn (hashed by
    their place along and across)."""
    step = 28.0
    i0, i1 = math.floor(a0 / step), math.ceil(a1 / step)
    j0, j1 = math.floor(b0 / step), math.ceil(b1 / step)
    if (i1 - i0) * (j1 - j0) > 3000:
        return
    for i in range(i0, i1):
        for j in range(j0, j1):
            x = (i + 0.15 + 0.7 * _rand(i, j, 7)) * step
            y = (j + 0.15 + 0.7 * _rand(i, j, 11)) * step
            r = 2.0 + 3.0 * _rand(i, j, 13)
            if not (a0 + r < x < a1 - r and b0 + r < y < b1 - r):
                continue
            out["polys"].append([at(x + r * math.cos(t * math.pi / 4),
                                    y + r * math.sin(t * math.pi / 4))
                                 for t in range(9)])


def _block_cells(out, at, a0, a1, b0, b1, depth) -> None:
    """A hollow block's two cells, seen from above."""
    shell = min(32.0, 0.25 * (b1 - b0))
    mid = (a0 + a1) / 2.0
    for c0, c1 in ((a0 + shell, mid - shell / 2.0),
                   (mid + shell / 2.0, a1 - shell)):
        if c1 > c0:
            out["polys"].append([at(c0, b0 + shell, depth),
                                 at(c1, b0 + shell, depth),
                                 at(c1, b1 - shell, depth),
                                 at(c0, b1 - shell, depth),
                                 at(c0, b0 + shell, depth)])


def _hollow_cells(out, at, a0, a1, b0, b1, depth, width) -> None:
    """The holes of a hollow brick cut across: two rows of cells."""
    cols = max(2, round((b1 - b0) / (width / 3.0)))
    cw, ch = (b1 - b0) / cols, (a1 - a0) / 2.0
    for r in range(2):
        for c in range(cols):
            x0, x1 = b0 + c * cw + 0.2 * cw, b0 + (c + 1) * cw - 0.2 * cw
            y0, y1 = a0 + r * ch + 0.22 * ch, a0 + (r + 1) * ch - 0.22 * ch
            out["polys"].append([at(y0, x0, depth), at(y0, x1, depth),
                                 at(y1, x1, depth), at(y1, x0, depth),
                                 at(y0, x0, depth)])


def known(key) -> bool:
    """Whether ``key`` names a pattern (``None`` — the frame's fill — too):
    one of the built-in ones, or an imported one (``pat:<name>``)."""
    return (key is None or key in HATCH_LABELS
            or (isinstance(key, str) and key.startswith(IMPORTED)
                and len(key) > len(IMPORTED)))


def parse_pat(text: str) -> dict:
    """The patterns of a pattern file (``.pat``) — the plain text format of
    technical drawing: ``*NAME, description`` and then one line per family,
    ``angle, x0, y0, shift along, spacing across[, dash, …]`` (positive
    draws, negative is a gap, 0 a dot). Returns ``{name: {"label": …,
    "families": [[angle, x0, y0, along, across, [dashes]], …]}}`` in
    millimetres: a file that says ``;%UNITS=INCH`` is turned from inches.
    Lines that cannot be read are skipped; a pattern with no family left is
    dropped."""
    factor = 25.4 if re.search(r";\s*%\s*UNITS\s*=\s*INCH", text,
                               re.IGNORECASE) else 1.0
    out: dict = {}
    current = None
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("*"):
            name, _, label = line[1:].partition(",")
            name = name.strip()[:64]
            if not name:
                current = None
                continue
            current = out.setdefault(name, {"label": label.strip()[:120]
                                            or name, "families": []})
            continue
        if current is None or len(current["families"]) >= _MAX_FAMILIES:
            continue
        try:
            nums = [float(v) for v in line.split(",") if v.strip()]
        except ValueError:
            continue
        if len(nums) < 5 or not all(math.isfinite(v) for v in nums):
            continue
        angle, x0, y0, along, across = nums[:5]
        if abs(across * factor) < _MIN_SPACING:
            continue
        dashes = [d * factor for d in nums[5:5 + _MAX_DASHES]]
        current["families"].append([angle % 360.0, x0 * factor, y0 * factor,
                                    along * factor, across * factor, dashes])
    return {n: p for n, p in out.items() if p["families"]}


def line_families(key) -> list | None:
    """The families of a built-in pattern drawn only with lines, as a
    pattern file writes them (``[angle, x0, y0, along, across, [dashes]]``,
    the offset across folded into the origin, the built-in turn applied);
    ``None`` for one generated (stipples, stones, rounds, waves), which no
    pattern file can describe."""
    if key not in _FAMILIES or key in _SCATTERED or key in _WAVES:
        return None
    turn = _TURN.get(key, 0.0)
    t = math.radians(turn)
    out = []
    for fam in _FAMILIES[key]:
        angle, x0, y0, along, across, dashes = fam[:6]
        off = fam[6] if len(fam) > 6 else 0.0
        if off:
            a = math.radians(angle)
            x0 -= math.sin(a) * off
            y0 += math.cos(a) * off
        if turn:
            x0, y0 = (x0 * math.cos(t) - y0 * math.sin(t),
                      x0 * math.sin(t) + y0 * math.cos(t))
        out.append([(angle + turn) % 360.0, x0, y0, along, across,
                    list(dashes)])
    return out


def to_pat(patterns) -> str:
    """A pattern file (``.pat``, millimetres) of ``patterns`` — ``[(name,
    label, families)]`` — the plain text format :func:`parse_pat` reads and
    the drawing programs share."""
    lines = [";; Hatch patterns exported from IngeTrazo",
             ";%UNITS=MM", ""]

    def num(v):
        text = f"{v:.6f}".rstrip("0").rstrip(".")
        return "0" if text in ("-0", "") else text
    for name, label, families in patterns:
        if not families:
            continue
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "PATTERN"
        lines.append(f"*{safe}, {label.replace(',', ' ')}")
        for fam in families:
            nums = [num(v) for v in fam[:5]] + [num(d) for d in fam[5]]
            lines.append(", ".join(nums))
    return "\n".join(lines) + "\n"


def clean_families(raw) -> list:
    """Families as a document stores them, read back defensively (the file
    may come from anywhere): ``[[angle, x0, y0, along, across, [dashes]]]``
    with every number finite and every spacing wide enough."""
    out = []
    for fam in raw if isinstance(raw, list) else ():
        try:
            angle, x0, y0, along, across = (float(v) for v in fam[:5])
            dashes = [float(d) for d in (fam[5] if len(fam) > 5 else [])
                      ][:_MAX_DASHES]
        except (TypeError, ValueError, IndexError):
            continue
        nums = [angle, x0, y0, along, across] + dashes
        if not all(math.isfinite(v) for v in nums) \
                or abs(across) < _MIN_SPACING:
            continue
        out.append([angle, x0, y0, along, across, dashes])
        if len(out) >= _MAX_FAMILIES:
            break
    return out


def hatch_marks(key: str, box, scale: float = 1.0, angle: float = 0.0,
                families=None, offset=None) -> dict:
    """The marks of pattern ``key`` over ``box`` = ``(x0, y0, x1, y1)`` in
    paper mm, ``scale`` times its size and turned ``angle`` degrees about
    the paper's origin: ``{"lines": [(x0, y0, x1, y1)], "dots": [(x, y)],
    "circles": [(x, y, r)], "polys": [[(x, y), …]], "closed": [[(x, y),
    …]]}`` — the caller clips them to the cut. ``families`` draws an
    imported pattern (its families, as :func:`parse_pat` gives them). A
    solid pattern has no marks: the caller fills. ``offset`` — ``(dx,
    dy)`` paper mm — moves the whole pattern."""
    if offset and (offset[0] or offset[1]):
        dx, dy = float(offset[0]), float(offset[1])
        return shift_marks(hatch_marks(
            key, (box[0] - dx, box[1] - dy, box[2] - dx, box[3] - dy),
            scale, angle, families), dx, dy)
    turn = (float(angle or 0.0) + (_TURN.get(key, 0.0) if families is None
                                   else 0.0)) % 360.0
    if abs(turn) < 1e-9:
        return _marks(key, box, scale, families)
    a = math.radians(turn)
    c, sn = math.cos(a), math.sin(a)
    corners = ((box[0], box[1]), (box[2], box[1]),
               (box[0], box[3]), (box[2], box[3]))
    # The box seen from the turned pattern, marked there, then turned back.
    back = [(x * c + y * sn, -x * sn + y * c) for x, y in corners]
    xs, ys = [q[0] for q in back], [q[1] for q in back]
    out = _marks(key, (min(xs), min(ys), max(xs), max(ys)), scale, families)

    def rot(x, y):
        return x * c - y * sn, x * sn + y * c
    out["lines"] = [rot(x0, y0) + rot(x1, y1)
                    for x0, y0, x1, y1 in out["lines"]]
    out["dots"] = [rot(x, y) for x, y in out["dots"]]
    out["circles"] = [rot(x, y) + (r,) for x, y, r in out["circles"]]
    out["polys"] = [[rot(x, y) for x, y in pts] for pts in out["polys"]]
    out["closed"] = [[rot(x, y) for x, y in pts] for pts in out["closed"]]
    return out


def _marks(key, box, scale, families) -> dict:
    out: dict = {"lines": [], "dots": [], "circles": [], "polys": [],
                 "closed": []}
    s = max(0.05, float(scale))
    if families is not None:
        for fam in clean_families(families):
            angle, x0, y0, along, across, dashes = fam
            _family(out, box, angle, x0 * s, y0 * s, along * s, across * s,
                    tuple(d * s for d in dashes))
        return out
    if key not in HATCH_LABELS or key == "solid":
        return out
    for fam in _FAMILIES.get(key, ()):
        angle, x0, y0, along, across, dashes = fam[:6]
        off = fam[6] if len(fam) > 6 else 0.0
        if off:
            a = math.radians(angle)
            x0 -= math.sin(a) * off
            y0 += math.cos(a) * off
        _family(out, box, angle, x0 * s, y0 * s, along * s, across * s,
                tuple(d * s for d in dashes))
    if key in _SCATTERED:
        kind, cell = _SCATTERED[key]
        _scatter(out, box, kind, cell * s)
    if key in _WAVES:
        band, period, amp = _WAVES[key]
        _waves(out, box, band * s, period * s, amp * s)
    if key == "wood_cross":
        # Laid on the paper: pieces side by side, each with its cross.
        band = FITTED[key] * s
        w = 1.5 * band
        rows = range(math.floor(box[1] / band) - 1, math.ceil(box[3] / band) + 1)
        cols = range(math.floor(box[0] / w) - 1, math.ceil(box[2] / w) + 1)
        if len(rows) * len(cols) <= 20000:
            for k in rows:
                for i in cols:
                    x0, y0 = i * w + (k % 2) * w / 2.0, k * band
                    out["polys"].append([(x0, y0), (x0 + w, y0),
                                         (x0 + w, y0 + band), (x0, y0 + band),
                                         (x0, y0)])
                    out["polys"] += fitted_marks(key, (x0, y0), (1.0, 0.0),
                                                 (0.0, 1.0), w, band)
        return out
    if key in FITTED:
        band = FITTED[key] * s
        for k in range(math.floor(box[1] / band) - 1,
                       math.ceil(box[3] / band) + 1):
            out["polys"] += fitted_marks(key, (box[0] - band, k * band),
                                       (1.0, 0.0), (0.0, 1.0),
                                       box[2] - box[0] + 2 * band, band)
    return out


def fitted_marks(key, origin, along, across, length: float, thick: float,
                 density: float = 1.0) -> list:
    """The marks of fitted pattern ``key`` (:data:`FITTED`) over one band,
    as :func:`batt_marks` takes it: polylines in the paper's coordinates."""
    if key == "insulation_zigzag":
        return zigzag_marks(origin, along, across, length, thick, density)
    if key == "wood_cross":
        return cross_marks(origin, along, across, length, thick)
    return batt_marks(origin, along, across, length, thick, density)


#: The wood patterns, which a layer may draw with a cross where a piece is
#: cut across its grain (``Layer.hatch_cross``).
WOOD = tuple(k for t, keys in HATCH_GROUPS if t == "Wood" for k in keys
             if k != "wood_cross")
#: A piece is taken as cut across its grain — a stud, a joist, a beam in
#: section — when it is no longer than this, in real mm, and no more than
#: :data:`_ACROSS_RATIO` times as long as it is thick; longer, it is a
#: board or a beam cut along.
_ACROSS_LONGEST = 600.0
_ACROSS_RATIO = 6.0


def cut_across(band, scale_n: float = 100.0, depth=None) -> bool:
    """Whether a cut piece (``fit_band``'s band, paper mm, a sheet at
    1:``scale_n``) is a piece of timber cut across its grain. ``depth`` —
    how far the piece runs through the plane, square to it, paper mm (see
    core.hlr.solid_depth) — settles it from the 3D piece: timber runs the
    way it is longest, so a piece that goes on further through the plane
    than within it is cut across (a stud in a plan, a joist in a section),
    one longer within it is cut along. Without it, the cut's own shape
    guesses: short and stocky is across."""
    if band is None:
        return False
    length, thick = band[3], band[4]
    if thick <= 1e-9:
        return False
    if depth is not None:
        return float(depth) >= length
    real = length * max(1e-6, float(scale_n or 100.0))
    return real <= _ACROSS_LONGEST and length <= _ACROSS_RATIO * thick


def cross_marks(origin, along, across, length: float,
                thick: float) -> list:
    """A piece of timber cut across its grain: its two diagonals, from
    corner to corner of the rectangle ``length`` by ``thick``."""
    if thick <= 1e-6 or length <= 1e-6:
        return []

    def at(a, b):
        return (origin[0] + along[0] * a + across[0] * b,
                origin[1] + along[1] * a + across[1] * b)
    return [[at(0.0, 0.0), at(length, thick)],
            [at(0.0, thick), at(length, 0.0)]]


def zigzag_marks(origin, along, across, length: float, thick: float,
                 density: float = 1.0) -> list:
    """One zigzag from face to face over a band ``length`` long and
    ``thick`` thick: a corner on each face every ``thick`` along (smaller
    with ``density`` > 1) — the symbol of insulation in thin layers."""
    if thick <= 1e-6 or length <= 1e-6:
        return []
    step = thick / max(0.2, float(density)) / 2.0   # face to face
    n = int(length / step) + 3
    if n > 40000:
        return []
    pts = []
    for k in range(-1, n):
        a, b = k * step, (thick if k % 2 else 0.0)
        pts.append((origin[0] + along[0] * a + across[0] * b,
                    origin[1] + along[1] * a + across[1] * b))
    return [pts]


def batt_marks(origin, along, across, length: float, thick: float,
               density: float = 1.0) -> list:
    """The soft insulation symbol over a band ``length`` long and ``thick``
    thick, from ``origin`` along the unit vector ``along``, ``across``
    pointing into the band: teardrops pointing one way and the other, side
    by side — a row of half circles against each face, each touching the
    next, and from the two ends of every half circle a straight leg to the
    point on the other face where two half circles meet. ``density`` > 1
    makes them smaller and closer. Returns polylines in the paper's
    coordinates."""
    if thick <= 1e-6 or length <= 1e-6:
        return []
    r = thick * _BATT_RADIUS / max(0.2, float(density))
    r = min(r, thick * 0.45)
    n = int(length / (2.0 * r)) + 3
    if n > 20000:                      # loops far too small for the band
        return []
    arc = 18
    out = []

    def place(pts):
        out.append([(origin[0] + along[0] * a + across[0] * b,
                     origin[1] + along[1] * a + across[1] * b)
                    for a, b in pts])
    far = thick - r
    for k in range(-1, n):
        near_c = 2.0 * r * k               # an arch against the near face
        far_c = near_c + r                 # a cup against the far one
        place([(near_c + r * math.cos(t), r - r * math.sin(t))
               for t in (math.pi * j / arc for j in range(arc + 1))])
        place([(far_c + r * math.cos(t), far + r * math.sin(t))
               for t in (math.pi * j / arc for j in range(arc + 1))])
        # The arch's legs meet where two cups meet; the cup's, where two
        # arches meet. Together they draw the zigzag between the faces.
        place([(near_c - r, r), (near_c, far), (near_c + r, r)])
    return out


def fit_band(ring) -> tuple | None:
    """How a cut piece runs: ``(origin, along, across, length, thick)`` of
    the smallest rectangle around ``ring`` (``[(x, y), …]``) — the side it
    is longest along, and its thickness across. ``None`` for a degenerate
    ring."""
    pts = [(float(x), float(y)) for x, y in ring]
    hull = _hull(pts)
    if len(hull) < 3:
        return None
    best = None
    for i in range(len(hull)):
        (x0, y0), (x1, y1) = hull[i], hull[(i + 1) % len(hull)]
        ex, ey = x1 - x0, y1 - y0
        n = math.hypot(ex, ey)
        if n < 1e-9:
            continue
        ux, uy = ex / n, ey / n
        a = [px * ux + py * uy for px, py in hull]
        b = [-px * uy + py * ux for px, py in hull]
        area = (max(a) - min(a)) * (max(b) - min(b))
        if best is None or area < best[0]:
            best = (area, ux, uy, min(a), max(a), min(b), max(b))
    if best is None:
        return None
    _area, ux, uy, a0, a1, b0, b1 = best
    la, lb = a1 - a0, b1 - b0
    if la >= lb:
        along, across = (ux, uy), (-uy, ux)
        origin = (ux * a0 - uy * b0, uy * a0 + ux * b0)
        return origin, along, across, la, lb
    along, across = (-uy, ux), (ux, uy)
    origin = (ux * a0 - uy * b0, uy * a0 + ux * b0)
    return origin, along, across, lb, la


def _hull(pts):
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _family(out, box, angle, ox, oy, along, across, dashes) -> None:
    a = math.radians(angle)
    ux, uy = math.cos(a), math.sin(a)
    nx, ny = -uy, ux
    corners = ((box[0], box[1]), (box[2], box[1]),
               (box[0], box[3]), (box[2], box[3]))
    if abs(across) <= 1e-9:
        return
    if across < 0:                     # a pattern file may count the other way
        across, along = -across, -along
    ss = [(x - ox) * nx + (y - oy) * ny for x, y in corners]
    k0 = math.floor(min(ss) / across) - 1
    k1 = math.ceil(max(ss) / across) + 1
    if k1 - k0 > 20000:                # far too fine for this box: skip it
        return
    period = sum(abs(d) for d in dashes)
    for k in range(k0, k1 + 1):
        bx = ox + k * (along * ux + across * nx)
        by = oy + k * (along * uy + across * ny)
        ts = [(x - bx) * ux + (y - by) * uy for x, y in corners]
        t0, t1 = min(ts), max(ts)
        if not dashes or period <= 1e-9:
            out["lines"].append((bx + ux * t0, by + uy * t0,
                                 bx + ux * t1, by + uy * t1))
            continue
        t = math.floor(t0 / period) * period
        if (t1 - t) / period * len(dashes) > 20000:
            continue
        while t < t1:
            for d in dashes:
                if d > 0:
                    a0, a1 = max(t, t0), min(t + d, t1)
                    if a1 > a0:
                        out["lines"].append((bx + ux * a0, by + uy * a0,
                                             bx + ux * a1, by + uy * a1))
                elif d == 0 and t0 <= t <= t1:
                    out["dots"].append((bx + ux * t, by + uy * t))
                t += abs(d)


def _rand(ix: int, iy: int, n: int) -> float:
    """A number in [0, 1) fixed by the cell and the draw — the same on every
    redraw and every machine."""
    h = (ix * 73856093) ^ (iy * 19349663) ^ (n * 83492791)
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0x1000000)


def _cells(box, cell, high=None):
    high = high or cell
    for ix in range(math.floor(box[0] / cell) - 1,
                    math.ceil(box[2] / cell) + 1):
        for iy in range(math.floor(box[1] / high) - 1,
                        math.ceil(box[3] / high) + 1):
            yield ix, iy


def _scatter(out, box, kind, cell) -> None:
    if kind == "pores":
        # Aerated concrete: small rounds, few and far between.
        for ix, iy in _cells(box, cell):
            if _rand(ix, iy, 3) < 0.45:
                continue
            out["circles"].append(((ix + 0.2 + 0.6 * _rand(ix, iy, 5)) * cell,
                                   (iy + 0.2 + 0.6 * _rand(ix, iy, 9)) * cell,
                                   cell * (0.08 + 0.1 * _rand(ix, iy, 4))))
        return
    if kind == "rubble":
        _rubble(out, box, cell)
        return
    if kind == "scales":
        _scales(out, box, cell)
        return
    if kind == "rings":
        _rings(out, box, cell)
        return
    if kind == "rock":
        _rock(out, box, cell)
        return
    if kind == "cobbles":
        _cobbles(out, box, cell)
        return
    if kind == "grain":
        _grain(out, box, cell)
        return
    if kind == "grain_open":
        # Few long lines far apart, no knots, a thin split now and then.
        _grain(out, box, cell, knots=0.0, wave=2.2, period=14.0,
               splits=True)
        return
    if kind == "grain_flame":
        # Dense grain flowing round eye-shaped knots.
        _grain(out, box, cell, knots=0.3, wave=2.5, period=6.0, eyes=True)
        return
    if kind == "ticks":
        _ticks(out, box, cell)
        return
    if kind.startswith("herring"):
        # Herringbone of boards this many times longer than they are wide.
        _herring(out, box, cell, cell * float(kind[len("herring"):]))
        return
    if kind in ("studs", "canopy"):
        _studs(out, box, cell, kind)
        return
    for ix, iy in _cells(box, cell):
        px = (ix + _rand(ix, iy, 1)) * cell
        py = (iy + _rand(ix, iy, 2)) * cell
        if kind == "sand":
            out["dots"].append((px, py))
            if _rand(ix, iy, 3) < 0.5:
                out["dots"].append(((ix + _rand(ix, iy, 4)) * cell,
                                    (iy + _rand(ix, iy, 5)) * cell))
        elif kind == "gravel":
            r = cell * (0.16 + 0.14 * _rand(ix, iy, 3))
            out["circles"].append((px, py, r))
        elif kind == "plaster":
            if _rand(ix, iy, 3) < 0.6:
                out["dots"].append((px, py))
        elif kind == "asphalt":
            out["dots"].append((px, py))
            if _rand(ix, iy, 3) < 0.12:
                out["circles"].append((px, py, cell * 0.22))
        elif kind == "strands":
            # Strands of a board: short flakes at every angle.
            for n in (0, 1):
                a = _rand(ix, iy, 10 + n) * math.pi
                cx = (ix + _rand(ix, iy, 20 + n)) * cell
                cy = (iy + _rand(ix, iy, 30 + n)) * cell
                half = cell * 0.3
                out["lines"].append((cx - half * math.cos(a),
                                     cy - half * math.sin(a),
                                     cx + half * math.cos(a),
                                     cy + half * math.sin(a)))
        elif kind == "chequer":
            # Raised bars of a chequer plate, turning a quarter in turn.
            cx, cy = (ix + 0.5) * cell, (iy + 0.5) * cell
            half = cell * 0.28
            sign = 1.0 if (ix + iy) % 2 else -1.0
            out["lines"].append((cx - half, cy - sign * half,
                                 cx + half, cy + sign * half))
        elif kind == "shrubs":
            # A shrub: a small cloud of overlapping rounds.
            if _rand(ix, iy, 3) < 0.8:
                for n in range(4):
                    a = n * math.pi / 2 + _rand(ix, iy, 40 + n)
                    out["circles"].append((px + cell * 0.18 * math.cos(a),
                                           py + cell * 0.18 * math.sin(a),
                                           cell * (0.14 + 0.06
                                                   * _rand(ix, iy, 50 + n))))
        elif kind == "grass":
            # A tuft: three blades fanned up from one root.
            if _rand(ix, iy, 3) < 0.7:
                blade = cell * 0.45
                for lean in (-0.45, 0.0, 0.45):
                    out["lines"].append((px, py,
                                         px + blade * math.sin(lean),
                                         py - blade * math.cos(lean)))
        elif kind == "concrete":
            # Aggregate: a small triangle now and then, sand between.
            out["dots"].append((px, py))
            out["dots"].append(((ix + _rand(ix, iy, 4)) * cell,
                                (iy + _rand(ix, iy, 5)) * cell))
            if _rand(ix, iy, 6) < 0.5:
                r = cell * (0.22 + 0.14 * _rand(ix, iy, 7))
                spin = _rand(ix, iy, 8) * 2.0 * math.pi
                cx = (ix + 0.5) * cell
                cy = (iy + 0.5) * cell
                out["closed"].append([
                    (cx + r * math.cos(spin + j * 2.0944),
                     cy + r * math.sin(spin + j * 2.0944))
                    for j in range(3)])
        elif kind == "stone":
            # Irregular blocks: a jittered grid, each cell a closed outline.
            def corner(cx, cy):
                return ((cx + 0.45 * (_rand(cx, cy, 9) - 0.5)) * cell,
                        (cy + 0.45 * (_rand(cx, cy, 10) - 0.5)) * cell)
            out["closed"].append([corner(ix, iy), corner(ix + 1, iy),
                                  corner(ix + 1, iy + 1), corner(ix, iy + 1)])


def _rubble(out, box, cell) -> None:
    """Rubble masonry: stones of irregular outline in staggered courses,
    with the mortar joint between them."""
    high = cell * 0.62
    for ix, iy in _cells(box, cell, high):
        cx = (ix + 0.5 + 0.5 * (iy % 2)) * cell
        cy = (iy + 0.5) * high
        rx, ry = cell * 0.42, high * 0.40
        n = 6 + int(_rand(ix, iy, 11) * 2)
        spin = _rand(ix, iy, 12) * math.pi
        out["closed"].append([
            (cx + rx * (0.78 + 0.22 * _rand(ix, iy, 20 + j))
             * math.cos(spin + j * 2.0 * math.pi / n),
             cy + ry * (0.78 + 0.22 * _rand(ix, iy, 40 + j))
             * math.sin(spin + j * 2.0 * math.pi / n))
            for j in range(n)])


def _rock(out, box, cell) -> None:
    """Rock: a jittered grid split corner to corner, every cell two angular
    pieces — the cracks of bedrock."""
    def corner(cx, cy):
        return ((cx + 0.5 * (_rand(cx, cy, 13) - 0.5)) * cell,
                (cy + 0.5 * (_rand(cx, cy, 14) - 0.5)) * cell)
    for ix, iy in _cells(box, cell):
        a, b = corner(ix, iy), corner(ix + 1, iy)
        c, d = corner(ix + 1, iy + 1), corner(ix, iy + 1)
        if _rand(ix, iy, 15) < 0.5:
            out["closed"] += [[a, b, c], [a, c, d]]
        else:
            out["closed"] += [[a, b, d], [b, c, d]]


def _cobbles(out, box, cell) -> None:
    """Cobbles: rounded stones close together, a joint between."""
    for ix, iy in _cells(box, cell):
        cx = (ix + 0.5 + 0.3 * (_rand(ix, iy, 16) - 0.5)) * cell
        cy = (iy + 0.5 + 0.3 * (_rand(ix, iy, 17) - 0.5)) * cell
        r = cell * 0.36
        out["closed"].append([
            (cx + r * (0.85 + 0.15 * _rand(ix, iy, 60 + j))
             * math.cos(j * math.pi / 4),
             cy + r * (0.85 + 0.15 * _rand(ix, iy, 70 + j))
             * math.sin(j * math.pi / 4)) for j in range(8)])


def _studs(out, box, cell, kind) -> None:
    """Round marks on a staggered grid: the studs of tactile paving, the
    holes of an acoustic panel, the crowns of trees seen from above."""
    high = cell * 0.87
    for ix, iy in _cells(box, cell, high):
        cx = (ix + 0.5 * (iy % 2)) * cell
        cy = iy * high
        if kind == "canopy":
            out["circles"].append((cx, cy, cell * 0.32))
            out["dots"].append((cx, cy))
        else:
            out["circles"].append((cx, cy, cell * 0.2))


def _grain(out, box, gap, knots: float = 0.35, wave: float = 1.0,
           period: float = 9.0, splits: bool = False,
           eyes: bool = False) -> None:
    """Natural wood along the grain: lines ``gap`` apart, wandering a little
    each its own way (``wave`` times as much, a sway every ``period`` gaps),
    bending round the knots scattered among them (a share ``knots`` of the
    cells has one): each knot a pair of small rings — or, with ``eyes``, a
    set of nested lens shapes. ``splits``: a thin lens-shaped split now and
    then between two lines."""
    knot_w, knot_h = gap * 18.0, gap * 9.0
    found = []
    for ix, iy in _cells(box, knot_w, knot_h):
        if _rand(ix, iy, 81) < knots:
            found.append(((ix + _rand(ix, iy, 82)) * knot_w,
                          (iy + _rand(ix, iy, 83)) * knot_h,
                          gap * (0.9 + 0.7 * _rand(ix, iy, 84))
                          * (1.6 if eyes else 1.0)))
    knots = found
    for kx, ky, kr in knots:
        for scale in ((0.3, 0.55, 0.8, 1.0) if eyes else (0.55, 1.0)):
            if eyes:
                # A lens: pointed at both ends, like the eye of a flame grain.
                out["closed"].append(
                    [(kx + kr * 2.0 * scale * math.cos(t),
                      ky + kr * 0.6 * scale * math.sin(t)
                      * abs(math.sin(t)) ** 0.0 * (1.0 - 0.35 * math.cos(t)
                                                   ** 2))
                     for t in (j * math.pi / 12 for j in range(24))])
            else:
                out["closed"].append([(kx + kr * 1.6 * scale * math.cos(t),
                                       ky + kr * 0.8 * scale * math.sin(t))
                                      for t in (j * math.pi / 10
                                                for j in range(20))])
    if splits:
        for ix, iy in _cells(box, gap * 12.0, gap):
            if _rand(ix, iy, 88) < 0.05:
                cx = (ix + _rand(ix, iy, 89)) * gap * 12.0
                cy = (iy + 0.5) * gap
                half = gap * (2.0 + 2.0 * _rand(ix, iy, 90))
                out["closed"].append([(cx + half * math.cos(t),
                                       cy + gap * 0.28 * math.sin(t))
                                      for t in (j * math.pi / 10
                                                for j in range(20))])
    step = gap * 0.4
    x0 = math.floor(box[0] / step) * step - 2 * knot_w
    x1 = box[2] + 2 * knot_w
    for k in range(math.floor(box[1] / gap) - 3,
                   math.ceil(box[3] / gap) + 4):
        base = k * gap + gap * 0.3 * (_rand(k, 0, 85) - 0.5)
        phase = _rand(k, 0, 86) * 2.0 * math.pi
        sway = gap * wave * (0.15 + 0.15 * _rand(k, 0, 87))
        pts = []
        x = x0
        while x <= x1:
            y = base + sway * math.sin(x / (gap * period) + phase)
            for kx, ky, kr in knots:
                d = base - ky
                if abs(d) < kr * 4.0 and abs(x - kx) < kr * 6.0:
                    # Bend round the knot: pushed away from its centre, the
                    # more the closer the line runs to it.
                    push = kr * 1.15 * math.exp(-((x - kx) / (kr * 2.2)) ** 2)
                    push *= math.exp(-(d / (kr * 2.2)) ** 2)
                    y += push if d >= 0 else -push
            pts.append((x, y))
            x += step
        out["polys"].append(pts)


def _ticks(out, box, gap) -> None:
    """Boards cut lengthwise: long lines ``gap`` apart, and between each two
    a short slanted tick now and then, staggered from one board to the
    next."""
    for k in range(math.floor(box[1] / gap) - 1, math.ceil(box[3] / gap) + 2):
        y = k * gap
        out["lines"].append((box[0] - gap, y, box[2] + gap, y))
    every = gap * 5.0
    for ix, iy in _cells(box, every, gap):
        x = (ix + 0.5 * (iy % 2) + 0.2 * (_rand(ix, iy, 91) - 0.5)) * every
        y = iy * gap
        out["lines"].append((x, y + gap * 0.15, x + gap * 0.55,
                             y + gap * 0.85))


def _herring(out, box, wide, long) -> None:
    """Herringbone boards ``long`` × ``wide``, in the staircase they make
    before the 45° turn: one board lying, one standing at its end, the pair
    repeated a board's width up and along, and a board's length across."""
    def board(x, y, w, h):
        out["closed"].append([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    # Repeats: (wide, wide) and (long, −long) — every point is i·t1 + j·t2.
    corners = ((box[0], box[1]), (box[2], box[1]),
               (box[0], box[3]), (box[2], box[3]))
    us = [(x + y) / (2.0 * wide) for x, y in corners]
    vs = [(x - y) / (2.0 * long) for x, y in corners]
    for i in range(math.floor(min(us)) - 2, math.ceil(max(us)) + 2):
        for j in range(math.floor(min(vs)) - 2, math.ceil(max(vs)) + 2):
            x = i * wide + j * long
            y = i * wide - j * long
            board(x, y, long, wide)                       # lying
            board(x + long, y + wide - long, wide, long)  # standing at its end


def _scales(out, box, cell) -> None:
    """Roof tiles: rows of round-ended tiles, each row half a tile on."""
    high = cell * 0.6
    r = cell / 2.0
    for ix, iy in _cells(box, cell, high):
        cx = (ix + 0.5 + 0.5 * (iy % 2)) * cell
        cy = iy * high
        out["polys"].append([(cx + r * math.cos(t * math.pi / 10),
                              cy + r * 0.8 * math.sin(t * math.pi / 10))
                             for t in range(11)])


def _rings(out, box, cell) -> None:
    """End grain: the growth rings of each piece, in staggered rows."""
    high = cell * 0.87
    for ix, iy in _cells(box, cell, high):
        cx = (ix + 0.5 * (iy % 2)) * cell
        cy = iy * high
        for k in (0.12, 0.24, 0.36):
            out["circles"].append((cx, cy, cell * k))


def _waves(out, box, band, period, amp) -> None:
    steps = 12
    x0 = math.floor(box[0] / period) * period
    n = max(1, int(math.ceil((box[2] - x0) / period)))
    for k in range(math.floor(box[1] / band) - 1,
                   math.ceil(box[3] / band) + 1):
        mid = (k + 0.5) * band
        pts = []
        for i in range(n * steps + 1):
            x = x0 + i * period / steps
            pts.append((x, mid + amp * math.sin(2.0 * math.pi
                                                 * (x / period))))
        out["polys"].append(pts)
