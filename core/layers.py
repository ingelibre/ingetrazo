# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Layer / tag system: visibility and locking (tags).

A layer never *owns* geometry — it is a label an entity carries (faces via
``attrs["layer"]``, edges via their ``layer`` slot, groups via ``.layer``).
Hiding a layer removes its entities from render, picking and box selection;
locking keeps them visible but unpickable. Everything unlabelled lives on the
default layer, which always exists and cannot be removed.

This is what makes the '2D that emerges' workflow real: structure / walls /
plumbing / furniture live on their own layers of one model, and a top view in
parallel projection with the right layers on IS the plan drawing.
"""
from __future__ import annotations

import re

DEFAULT_LAYER = "Layer 0"

# Where an imported photogrammetric survey lands (Track G, G6). Its own layer
# by default, not the default one: the whole point of importing a survey is to
# draw on top of it, and you need to switch it off to look at what you drew —
# which would take your model with it if they shared a layer. A plain stored
# name like DEFAULT_LAYER, not a translated one: layer names are document data
# and must not change with the interface language.
SURVEY_LAYER = "Survey"


#: Colours a layer shows until one is picked for it (the Layers panel swatch
#: and View ▸ Colour by layer). Mid-tone and told apart from one another, so
#: the model stays readable with the diffuse shading on top.
PALETTE = (
    (0.86, 0.42, 0.36), (0.36, 0.60, 0.84), (0.52, 0.74, 0.40),
    (0.92, 0.70, 0.30), (0.62, 0.48, 0.80), (0.34, 0.74, 0.72),
    (0.88, 0.52, 0.70), (0.66, 0.58, 0.44), (0.56, 0.66, 0.30),
    (0.46, 0.50, 0.70), (0.84, 0.60, 0.48), (0.40, 0.66, 0.56),
)
#: The default layer's own colour: the plain model white, so what nobody
#: sorted onto a layer reads as "not classified".
DEFAULT_LAYER_COLOR = (0.96, 0.95, 0.925)

#: Line types a layer can ink its edges with, and their dash pattern in
#: millimetres on paper (dash, gap, …; empty = continuous). The DXF names
#: are the standard ones every CAD program loads.
LINETYPES = {
    "continuous": (),
    "dashed": (3.0, 1.5),
    "dashed_short": (1.5, 0.75),          # hidden lines
    "dashed_long": (8.0, 2.0),
    "dotted": (0.5, 1.0),
    "dashdot": (6.0, 1.5, 0.5, 1.5),
    "dashdotdot": (6.0, 1.5, 0.5, 1.5, 0.5, 1.5),
    "center": (12.0, 1.5, 2.0, 1.5),      # axes, centre lines
    "phantom": (12.0, 1.5, 2.0, 1.5, 2.0, 1.5),   # limits, alternate positions
    "border": (6.0, 1.5, 6.0, 1.5, 0.5, 1.5),
}
#: Their names in a DXF: the ones every CAD program ships in its standard
#: line type file, so the file opens with them already known.
DXF_LINETYPES = {"continuous": "CONTINUOUS", "dashed": "DASHED",
                 "dashed_short": "HIDDEN", "dashed_long": "DASHEDX2",
                 "dotted": "DOT", "dashdot": "DASHDOT",
                 "dashdotdot": "DIVIDE", "center": "CENTER",
                 "phantom": "PHANTOM", "border": "BORDER"}

#: The key prefix of a line type the user made or brought in from a line
#: type file (``.lin``), kept in the document (``Scene.line_types``):
#: ``"lin:<name>"``.
CUSTOM_LINETYPE = "lin:"
#: A line type's limits — what a reasonable pattern needs; a file is data
#: from anywhere.
_MAX_PIECES = 32


def known_linetype(key) -> bool:
    """Whether ``key`` names a line type: a built-in one or a custom one."""
    return key in LINETYPES or (isinstance(key, str)
                                and key.startswith(CUSTOM_LINETYPE)
                                and len(key) > len(CUSTOM_LINETYPE))


def linetype_pattern(key, scene=None) -> tuple:
    """The dash pattern of line type ``key`` as it is drawn: paper mm,
    dash, gap, dash, gap… in turn (as :data:`LINETYPES` holds them; a dot
    is a dash of 0; empty: continuous) — a built-in one, or the document's
    own, whose stored pieces (dash > 0, gap < 0, dot 0) are turned so."""
    if key in LINETYPES:
        return tuple(LINETYPES[key])
    if isinstance(key, str) and key.startswith(CUSTOM_LINETYPE):
        entry = (getattr(scene, "line_types", None) or {}).get(
            key[len(CUSTOM_LINETYPE):])
        if isinstance(entry, dict):
            return drawn_dashes(entry.get("pattern") or ())
    return ()


#: A line type's text (``GAS``, ``AGUA``…): its longest, and its height on
#: paper in mm — the least and the most.
_MAX_TEXT = 24
_TEXT_SIZES = (0.5, 20.0)


def text_width(text: str, size: float) -> float:
    """About how wide ``text`` runs at ``size`` mm high, in mm — what a
    line type leaves free for it (a sans serif, capitals mostly)."""
    return 0.68 * float(size) * len(text)


def clean_line_text(entry, pattern) -> dict | None:
    """The text of a line type entry, read defensively: ``{"text",
    "text_size", "text_at"}`` — the words, their height (paper mm) and the
    piece of ``pattern`` they sit in, centred (a gap); ``None`` without
    one."""
    import math
    if not isinstance(entry, dict) or not pattern:
        return None
    text = entry.get("text")
    if not isinstance(text, str):
        return None
    text = "".join(c for c in text if c.isprintable()).strip()[:_MAX_TEXT]
    if not text:
        return None
    try:
        size = float(entry.get("text_size", 2.5))
        at = int(entry.get("text_at", len(pattern) - 1))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(size):
        return None
    size = min(_TEXT_SIZES[1], max(_TEXT_SIZES[0], size))
    if not 0 <= at < len(pattern) or pattern[at] >= 0:
        return None
    return {"text": text, "text_size": round(size, 3), "text_at": at}


def with_text(pattern, text: str, size: float = 2.5) -> tuple:
    """``pattern`` (pieces, dash > 0, gap < 0) with ``text`` in it: room
    as wide as the words and a margin each side, added to its last gap (or
    as a gap of its own) — the text sits centred in that gap. Returns ``(pattern, {"text", "text_size",
    "text_at"})``; the pattern alone when there is no text."""
    text = (text or "").strip()
    if not text:
        return list(pattern), None
    room = text_width(text, size) + 2.0 * max(0.6, 0.4 * float(size))
    out = list(pattern)
    if out and out[-1] < 0:
        out[-1] = round(out[-1] - room, 3)     # the last gap, widened
    else:
        out.append(-round(room, 3))
    return out, clean_line_text({"text": text, "text_size": size,
                                 "text_at": len(out) - 1}, out)


def text_offset(pattern, at: int) -> float:
    """Where along one period of the drawn pattern (:func:`drawn_dashes`,
    which moves a leading gap to the end) the middle of piece ``at`` of
    ``pattern`` falls, in mm."""
    period = sum(abs(v) for v in pattern)
    raw = sum(abs(v) for v in pattern[:at]) + abs(pattern[at]) / 2.0
    lead = 0.0
    for v in pattern:
        if v >= 0:
            break
        lead += abs(v)
    return (raw - lead) % period if period > 0 else 0.0


def linetype_text(key, scene=None):
    """The text of line type ``key`` as it is drawn: ``(text, height mm,
    where its middle falls along a period, the period)`` in paper mm;
    ``None`` for a line type without one (every built-in one)."""
    if not (isinstance(key, str) and key.startswith(CUSTOM_LINETYPE)):
        return None
    entry = (getattr(scene, "line_types", None) or {}).get(
        key[len(CUSTOM_LINETYPE):])
    pattern = entry.get("pattern") if isinstance(entry, dict) else None
    spec = clean_line_text(entry, pattern)
    if spec is None:
        return None
    period = sum(drawn_dashes(pattern))
    return (spec["text"], spec["text_size"],
            text_offset(pattern, spec["text_at"]), period)


def clean_line_colour(raw) -> tuple | None:
    """A line type's own colour as it is kept: ``(r, g, b)`` 0–1, or
    ``None`` (by layer) for none or anything else."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        rgb = tuple(min(1.0, max(0.0, float(c))) for c in raw)
    except (TypeError, ValueError):
        return None
    return rgb if all(c == c for c in rgb) else None


def linetype_color(key, scene=None) -> tuple | None:
    """The colour line type ``key`` inks its lines with whatever their
    layer — a gas line yellow, a water main blue — or ``None``: the
    layer's. A built-in one takes the colour the document gave it."""
    if key in LINETYPES:
        return clean_line_colour(
            (getattr(scene, "linetype_colors", None) or {}).get(key))
    if not (isinstance(key, str) and key.startswith(CUSTOM_LINETYPE)):
        return None
    entry = (getattr(scene, "line_types", None) or {}).get(
        key[len(CUSTOM_LINETYPE):])
    return clean_line_colour(entry.get("color")) \
        if isinstance(entry, dict) else None


def set_linetype_color(scene, key, rgb) -> bool:
    """Give line type ``key`` the colour ``rgb`` — ``None``: by layer again
    — a built-in one in the document's list, an own one in its entry.
    Returns whether anything changed."""
    rgb = clean_line_colour(rgb)
    if linetype_color(key, scene) == rgb:
        return False
    if key in LINETYPES:
        colours = dict(getattr(scene, "linetype_colors", None) or {})
        if rgb is None:
            colours.pop(key, None)
        else:
            colours[key] = rgb
        scene.linetype_colors = colours
        return True
    if not (isinstance(key, str) and key.startswith(CUSTOM_LINETYPE)):
        return False
    own = dict(getattr(scene, "line_types", None) or {})
    entry = own.get(key[len(CUSTOM_LINETYPE):])
    if not isinstance(entry, dict):
        return False
    entry = dict(entry)
    if rgb is None:
        entry.pop("color", None)
    else:
        entry["color"] = rgb
    own[key[len(CUSTOM_LINETYPE):]] = entry
    scene.line_types = own
    return True


def load_linetype_colors(scene, raw) -> None:
    """The built-in line types' colours as a file keeps them, read
    defensively: known keys and real colours only."""
    if not isinstance(raw, dict):
        return
    colours = dict(getattr(scene, "linetype_colors", None) or {})
    for key, value in raw.items():
        rgb = clean_line_colour(value)
        if key in LINETYPES and rgb is not None:
            colours[key] = rgb
    scene.linetype_colors = colours


def model_line_styles(scene) -> dict:
    """``{layer name: (rgb or None, dash pattern)}`` of the layers whose
    edges the model draws with their line type (the style's «Line types in
    the model»): dashed (the pattern in paper mm, as
    :func:`linetype_pattern` gives it), in a colour of its own, or both.
    A continuous line type by layer is not here: the model draws it as
    ever."""
    out = {}
    for ly in getattr(scene, "layers", ()):
        rgb = linetype_color(ly.linetype, scene)
        pattern = tuple(linetype_pattern(ly.linetype, scene))
        if rgb is not None or pattern:
            out[ly.name] = (rgb, pattern)
    return out


#: The model draws a line type's dashes as a sheet at 1:50 does — metres
#: of model per paper millimetre.
MODEL_DASH_SCALE = 0.05


def dash_segments(segs, pattern, unit: float = MODEL_DASH_SCALE):
    """``segs`` ((E, 2, 3) world) cut as the dash ``pattern`` (paper mm:
    dash, gap, dash…; a dot is a dash of 0) at ``unit`` metres per paper
    mm, restarting on each segment as a pen does: ``(dashes, gaps)``, two
    (K, 2, 3) float32 arrays. A dot is drawn as a short dash. Too fine a
    pattern for a long edge (over 400 periods) leaves it whole."""
    import numpy as np
    segs = np.asarray(segs, dtype=np.float64).reshape(-1, 2, 3)
    empty = np.zeros((0, 2, 3), dtype=np.float32)
    if not len(segs) or not pattern:
        return segs.astype(np.float32), empty
    lengths = [max(float(v), 0.25) * unit if i % 2 == 0
               else max(float(v), 0.0) * unit
               for i, v in enumerate(pattern)]
    if len(lengths) % 2:
        lengths.append(0.0)
    period = sum(lengths)
    dashes: list = []
    gaps: list = []
    for a, b in segs:
        d = b - a
        total = float(np.linalg.norm(d))
        if total <= 1e-12:
            continue
        if period <= 1e-12 or total / period > 400:
            dashes.append((a, b))
            continue
        u = d / total
        t = 0.0
        k = 0
        while t < total:
            step = lengths[k % len(lengths)]
            end = min(total, t + step)
            if end > t:
                (dashes if k % 2 == 0 else gaps).append((a + u * t,
                                                         a + u * end))
            t = end
            k += 1
    as_array = (lambda xs: np.asarray(xs, dtype=np.float32).reshape(-1, 2, 3)
                if xs else empty)
    return as_array(dashes), as_array(gaps)


def text_marks(p0, p1, spec) -> list:
    """Where a line type's text goes along the line ``p0``→``p1`` (paper mm,
    the pattern restarting at ``p0`` as a pen restarts it on each line):
    ``[(x, y, degrees)]``, the middle of each word that fits whole, turned
    along the line and kept reading upright. ``spec``: :func:`linetype_text`."""
    import math
    if spec is None:
        return []
    text, size, offset, period = spec
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9 or period <= 1e-9:
        return []
    half = text_width(text, size) / 2.0
    angle = math.degrees(math.atan2(dy, dx))
    if angle > 90.0:
        angle -= 180.0
    elif angle <= -90.0:
        angle += 180.0
    out = []
    t = offset
    n = 0
    while t + half <= length and n < 2000:
        if t - half >= 0.0:
            f = t / length
            out.append((p0[0] + dx * f, p0[1] + dy * f, angle))
        t += period
        n += 1
    return out


def drawn_dashes(pieces) -> tuple:
    """Pieces as a line type file has them (dash > 0, gap < 0, dot 0) as
    a pen draws them: dash, gap, dash, gap… in turn, all ≥ 0, starting with
    a dash — two pieces of a kind in a row joined, a leading gap moved to
    the end."""
    runs: list = []                    # [(drawn?, length)]
    for v in pieces:
        drawn = v >= 0
        if runs and runs[-1][0] == drawn and not (drawn and v == 0):
            runs[-1] = (drawn, runs[-1][1] + abs(v))
        else:
            runs.append((drawn, abs(v)))
    if runs and not runs[0][0]:
        runs = runs[1:] + runs[:1]
    out: list = []
    for drawn, length in runs:
        if out and (len(out) % 2 == 0) != drawn:
            out[-1] += 0.0 if drawn else length    # never two of a kind
            continue
        out.append(length)
    if len(out) % 2:
        out.append(0.0)
    return tuple(out)


def file_dashes(drawn) -> tuple:
    """:func:`drawn_dashes` the other way: dash, −gap, … for a file."""
    return tuple(v if i % 2 == 0 else -v for i, v in enumerate(drawn))


def clean_pattern(raw) -> list | None:
    """A dash pattern as typed or read from a file, kept sane: finite
    numbers in mm, at most a few dozen pieces, something drawn and
    something left blank; ``None`` when there is no such pattern."""
    import math
    if not isinstance(raw, (list, tuple)):
        return None
    out = []
    for v in raw[:_MAX_PIECES]:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(v) or abs(v) > 1000.0:
            return None
        out.append(round(v, 4))
    if not out or sum(abs(v) for v in out) < 0.05:
        return None
    if not any(v < 0 for v in out) or not any(v >= 0 for v in out):
        return None                    # all gap, or a continuous line
    return out


def parse_lin(text: str) -> tuple[dict, list]:
    """The line types of a line type file (``.lin``) — the plain text
    format of drawing programs: ``*NAME,description`` and then
    ``A,dash,-gap,0,…``. Returns ``({name: {"label", "pattern"[, "text",
    "text_size", "text_at"]}}, skipped)``: the line types in mm — with
    their text, when a piece writes one (``["GAS",STANDARD,S=2.5,…]``: the
    two gaps around it made one, the text centred in it) — and the names
    of those that carry a shape (``[NAME,file.shx,…]``), left out. The
    format has no unit: a pattern whose every piece is a fraction of a
    unit is taken as inches (the imperial files) and turned into mm."""
    found: dict = {}
    skipped: list = []
    name = label = None
    for raw in text.splitlines():
        line = raw.split(";;", 1)[0].strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("*"):
            head, _, label = line[1:].partition(",")
            name = head.strip()[:64] or None
            label = label.strip()[:120]
            continue
        if name is None:
            continue
        body = line[1:] if line[:1].upper() == "A" else line
        body = body.lstrip(",")
        words = None                   # (text, size) of a text piece
        at = None                      # the gap it sits in, once known
        nums: list = []
        bad = False
        for part in re.split(r",(?![^\[]*\])", body):
            part = part.strip()
            if not part:
                continue
            if part.startswith("["):
                inner = [v.strip() for v in part.strip("[]").split(",")]
                first = inner[0] if inner else ""
                if not (first.startswith('"') and first.endswith('"')
                        and len(first) > 2) or words is not None:
                    bad = True         # a shape, or two texts: left out
                    break
                size = 0.1
                for item in inner[1:]:
                    k, _, v = item.partition("=")
                    if k.strip().upper() == "S":
                        try:
                            size = float(v)
                        except ValueError:
                            pass
                words = (first[1:-1], size)
                # The gap before it and the one after are one room.
                at = len(nums) - 1 if nums and nums[-1] < 0 else None
                continue
            try:
                v = float(part)
            except ValueError:
                bad = True
                break
            if at is not None and len(nums) - 1 == at and v < 0:
                nums[at] += v
                at = -1                # merged: keep it where it is
                continue
            if words is not None and at is None and v < 0:
                at = len(nums)         # no gap before: the one after
            nums.append(v)
            if at == -1:
                at = None
        if bad:
            skipped.append(name)
            name = None
            continue
        inches = bool(nums) and all(abs(v) <= 1.0 for v in nums)
        if inches:
            nums = [v * 25.4 for v in nums]
        pattern = clean_pattern(nums)
        if pattern is not None:
            entry = {"label": label or name, "pattern": pattern}
            if words is not None:
                gaps = [i for i, v in enumerate(pattern) if v < 0]
                # The widest gap holds the text when its place was lost.
                where = max(gaps, key=lambda i: -pattern[i]) if gaps else None
                spec = clean_line_text(
                    {"text": words[0], "text_size":
                     words[1] * (25.4 if inches else 1.0), "text_at": where},
                    pattern)
                if spec is not None:
                    entry.update(spec)
            found[name] = entry
        name = None
    return found, skipped


def to_lin(entries) -> str:
    """A line type file (``.lin``, mm) of ``entries`` — ``[(name, label,
    pattern[, text spec])]`` — that :func:`parse_lin` and drawing programs
    read. A text goes in the middle of its gap, as the format writes one:
    ``["GAS",STANDARD,S=2.5,R=0.0,X=-…,Y=-…]`` between its two halves."""
    lines = [";; Line types exported from IngeTrazo (millimetres)", ""]
    for entry in entries:
        name, label, pattern = entry[:3]
        spec = entry[3] if len(entry) > 3 else None
        if not pattern:
            continue
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "LINE"
        lines.append(f"*{safe},{label.replace(',', ' ')}")
        pieces = [f"{v:g}" for v in pattern]
        if spec:
            at, size = spec["text_at"], spec["text_size"]
            half = pattern[at] / 2.0
            words = spec["text"].replace('"', "'")
            pieces[at:at + 1] = [
                f"{half:g}",
                f'["{words}",STANDARD,S={size:g},R=0.0,'
                f"X={-text_width(words, size) / 2.0:g},Y={-size / 2.0:g}]",
                f"{half:g}"]
        lines.append("A," + ",".join(pieces))
    return "\n".join(lines) + "\n"


#: How much a locked layer's faces wash toward white: drawn, but plainly
#: not in play.
LOCKED_FADE = 0.55


class Layer:
    """A named tag with display state.

    ``color`` is an RGB tuple (0–1) or ``None`` for the automatic one (see
    :func:`layer_color`); ``folder`` is the name of the folder the layer is
    filed under in the Layers panel, or ``None``. A folder only organises the
    list: entities still carry the layer's name and nothing else."""

    def __init__(self, name: str, visible: bool = True,
                 locked: bool = False, color=None,
                 folder: str | None = None, linetype: str = "continuous",
                 lineweight: float | None = None,
                 opacity: float = 1.0, printable: bool = True,
                 cut_weight: float | None = None,
                 hatch: str | None = None, hatch_ground=None,
                 hatch_color=None, hatch_angle: float = 0.0,
                 hatch_scale: float = 1.0,
                 hatch_on_paper: bool | None = None,
                 brick=None, hatch_cross: bool = False, joints=None,
                 mortar: bool = False, hatch_offset=None) -> None:
        self.name = name
        self.visible = visible
        self.locked = locked
        self.color = tuple(color) if color is not None else None
        self.folder = folder or None
        #: How the layer's edges are inked on a sheet and in a DXF:
        #: one of :data:`LINETYPES`.
        self.linetype = (linetype if known_linetype(linetype)
                         else "continuous")
        #: Pen width on a sheet, in millimetres (``None``: the sheet's own
        #: pen for the line's class).
        self.lineweight = lineweight
        #: Pen width of the layer's section cut on a sheet, in millimetres
        #: (``None``: the sheet's cut pen) — a wall cut heavier than the
        #: door and the window cut beside it, whatever its other lines.
        self.cut_weight = cut_weight
        #: What its section cut is filled with on a sheet: one of
        #: ``core.hatches.HATCH_LABELS`` (brick, concrete, insulation…), or
        #: ``None`` for the frame's own fill.
        from core.hatches import known
        self.hatch = hatch if hatch is not None and known(hatch) else None
        #: A solid colour under the hatch: ``None`` (the paper), ``"layer"``
        #: (the layer's own colour, light) or an RGB tuple (0–1) — white
        #: or grey under brick, say.
        self.hatch_ground = _ground(hatch_ground)
        #: The ink of the hatch's lines: ``None`` (as the frame says — its
        #: fill colour, or the layer's when it fills by layer), ``"layer"``
        #: (by layer: always the layer's colour) or an RGB tuple (a fixed
        #: colour, black say, whatever the frame).
        self.hatch_color = _ground(hatch_color)
        #: The hatch turned this many degrees, and this many times its size.
        self.hatch_angle = _finite(hatch_angle, 0.0) % 360.0
        self.hatch_scale = min(20.0, max(0.05, _finite(hatch_scale, 1.0)))
        #: Where a pattern of pieces (core.hatches.PLACED) starts: ``(x,
        #: y)`` real mm it is moved by — the first joint along a wall, the
        #: first course up it, tiles off an axis — ``None`` for none.
        self.hatch_offset = clean_offset(hatch_offset)
        #: ``True``: the hatch measures the same on paper at any scale
        #: (a drawing's convention); ``False``: it grows and shrinks with the
        #: frame's scale, like the real bricks or tiles it stands for (its
        #: own size is the one at 1:100).
        self.hatch_on_paper = (None if hatch_on_paper is None
                               else bool(hatch_on_paper))
        #: The brick its brickwork hatch is drawn with: ``(length, width,
        #: height, joint)`` in mm, ``None`` for the usual metric one.
        from core.hatches import clean_brick
        self.brick = clean_brick(brick) if brick is not None else None
        #: A wood hatch drawn with a cross from corner to corner where a
        #: piece is cut across its grain (core.hatches.cut_across): studs,
        #: joists and beams in section; the rest in the hatch.
        self.hatch_cross = bool(hatch_cross)
        #: How its masonry joints are drawn: one of core.hatches.JOINTS, or
        #: ``None`` — by the sheet's scale. ``mortar``: the double joints
        #: filled in light grey.
        from core.hatches import JOINTS
        self.joints = joints if joints in JOINTS else None
        self.mortar = bool(mortar)
        #: Face opacity, 0.1–1: a reference layer seen through.
        self.opacity = min(1.0, max(0.1, float(opacity)))
        #: ``False``: seen in the model, left out of the sheets — their
        #: views, PDF and DXF (references, construction lines, notes).
        self.printable = bool(printable)

    def to_dict(self) -> dict:
        entry: dict = {"name": self.name}
        if not self.visible:
            entry["visible"] = False
        if self.locked:
            entry["locked"] = True
        if self.color is not None:
            entry["color"] = [round(float(c), 4) for c in self.color[:3]]
        if self.folder:
            entry["folder"] = self.folder
        if self.linetype != "continuous":
            entry["linetype"] = self.linetype
        if self.lineweight is not None:
            entry["lineweight"] = round(float(self.lineweight), 3)
        if self.cut_weight is not None:
            entry["cut_weight"] = round(float(self.cut_weight), 3)
        if self.hatch:
            entry["hatch"] = self.hatch
        if self.hatch_angle:
            entry["hatch_angle"] = round(self.hatch_angle, 3)
        if abs(self.hatch_scale - 1.0) > 1e-9:
            entry["hatch_scale"] = round(self.hatch_scale, 4)
        if self.hatch_offset is not None:
            entry["hatch_offset"] = [round(v, 2) for v in self.hatch_offset]
        if self.hatch_on_paper is not None:
            entry["hatch_on_paper"] = self.hatch_on_paper
        if self.brick is not None:
            entry["brick"] = [round(v, 2) for v in self.brick]
        if self.hatch_cross:
            entry["hatch_cross"] = True
        if self.joints is not None:
            entry["joints"] = self.joints
        if self.mortar:
            entry["mortar"] = True
        for key in ("hatch_ground", "hatch_color"):
            value = getattr(self, key)
            if value is not None:
                entry[key] = (value if value == GROUND_LAYER
                              else [round(float(c), 4) for c in value])
        if self.opacity < 1.0:
            entry["opacity"] = round(float(self.opacity), 3)
        if not self.printable:
            entry["printable"] = False
        return entry

    def has_style(self) -> bool:
        """Whether anything beyond the name and visibility is set — what
        makes a document worth writing its layer list for."""
        return (self.color is not None or bool(self.folder)
                or self.linetype != "continuous"
                or self.lineweight is not None or self.opacity < 1.0
                or not self.printable or self.cut_weight is not None
                or self.hatch is not None or self.hatch_ground is not None
                or self.hatch_color is not None or bool(self.hatch_angle)
                or abs(self.hatch_scale - 1.0) > 1e-9
                or self.hatch_offset is not None
                or self.hatch_on_paper is not None
                or self.brick is not None or self.hatch_cross
                or self.joints is not None or self.mortar)

    @classmethod
    def from_dict(cls, raw: dict) -> "Layer":
        color = raw.get("color")
        if not (isinstance(color, (list, tuple)) and len(color) >= 3):
            color = None
        else:
            try:
                color = tuple(min(1.0, max(0.0, float(c))) for c in color[:3])
            except (TypeError, ValueError):
                color = None
        folder = raw.get("folder")
        weight = _pen_mm(raw.get("lineweight"))
        cut_weight = _pen_mm(raw.get("cut_weight"))
        try:
            opacity = float(raw.get("opacity", 1.0))
        except (TypeError, ValueError):
            opacity = 1.0
        return cls(raw.get("name", DEFAULT_LAYER),
                   visible=raw.get("visible", True),
                   locked=raw.get("locked", False),
                   color=color,
                   folder=folder if isinstance(folder, str) else None,
                   linetype=raw.get("linetype", "continuous"),
                   lineweight=weight, opacity=opacity,
                   printable=raw.get("printable", True) is not False,
                   cut_weight=cut_weight,
                   hatch=raw.get("hatch") if isinstance(raw.get("hatch"), str)
                   else None,
                   hatch_ground=raw.get("hatch_ground"),
                   hatch_color=raw.get("hatch_color"),
                   hatch_angle=raw.get("hatch_angle", 0.0),
                   hatch_scale=raw.get("hatch_scale", 1.0),
                   hatch_offset=raw.get("hatch_offset"),
                   hatch_on_paper=(raw.get("hatch_on_paper")
                                   if isinstance(raw.get("hatch_on_paper"),
                                                 bool) else None),
                   brick=raw.get("brick"),
                   hatch_cross=raw.get("hatch_cross") is True,
                   joints=raw.get("joints"),
                   mortar=raw.get("mortar") is True)


def _finite(raw, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    import math
    return value if math.isfinite(value) else default


#: ``Layer.hatch_ground`` / ``hatch_color`` for «the layer's own colour»
#: (light, for a ground; as it is, for the ink) — by layer.
GROUND_LAYER = "layer"


def _ground(raw):
    """A hatch ground or ink as stored: ``None``, :data:`GROUND_LAYER` or
    an RGB tuple kept to 0–1; anything else is ``None``."""
    if raw == GROUND_LAYER:
        return GROUND_LAYER
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return tuple(min(1.0, max(0.0, float(c))) for c in raw[:3])
        except (TypeError, ValueError):
            return None
    return None


def hatch_ground_rgb(ly) -> tuple | None:
    """The colour under a layer's hatch: its own pick, the layer's colour
    made light for :data:`GROUND_LAYER`, ``None`` for the paper."""
    ground = getattr(ly, "hatch_ground", None)
    if ground == GROUND_LAYER:
        return light_layer_color(ly)
    return tuple(ground) if ground is not None else None


def hatch_ink_rgb(ly) -> tuple | None:
    """The ink of a layer's hatch lines when the layer sets one: its colour
    by layer (a shade darker, so mid tones read on paper) or the fixed one;
    ``None`` — as the frame says."""
    ink = getattr(ly, "hatch_color", None)
    if ink == GROUND_LAYER:
        return tuple(c * 0.7 for c in layer_color(ly))
    return tuple(ink) if ink is not None else None


def light_layer_color(ly) -> tuple:
    """The layer's colour three quarters of the way to white — a ground a
    hatch still reads on."""
    return tuple(c + (1.0 - c) * 0.75 for c in layer_color(ly))


def _pen_mm(raw) -> float | None:
    """A stored pen width in millimetres, kept to 0.05–5; ``None`` when
    unset or unreadable."""
    try:
        return min(5.0, max(0.05, float(raw))) if raw is not None else None
    except (TypeError, ValueError):
        return None


def layer_color(layer) -> tuple:
    """The colour a layer shows: the picked one, else the default layer's
    white for the default layer, else one from :data:`PALETTE` chosen by the
    name — stable across sessions and machines, and unchanged when other
    layers are added, deleted or sorted."""
    if layer is None:
        return DEFAULT_LAYER_COLOR
    if layer.color is not None:
        return tuple(layer.color[:3])
    if layer.name == DEFAULT_LAYER:
        return DEFAULT_LAYER_COLOR
    import zlib
    return PALETTE[zlib.crc32(layer.name.encode("utf-8")) % len(PALETTE)]


def object_layer(group) -> str:
    """The layer an object's insides take their colour from: its own, else
    the top-level object's it belongs to (a nested piece of a component on
    a layer), else the default layer. ``None`` is the loose model."""
    for g in (group, getattr(group, "owner", None)):
        name = getattr(g, "layer", None) if g is not None else None
        if name:
            return name
    return DEFAULT_LAYER


def layer_paint(scene, group=None) -> dict:
    """The container paint Colour by layer bakes ``group`` with (see
    ``core.materials.effective_attrs``): every layer's colour by name, and
    the object's own layer colour for the faces that carry none."""
    table = {ly.name: layer_color(ly) for ly in getattr(scene, "layers", ())}
    color = table.get(object_layer(group), DEFAULT_LAYER_COLOR)
    return {"by_layer": table, "color": color}


def layer_fx(scene) -> dict:
    """``{name: (opacity, fade)}`` of the layers that change how their faces
    look — see-through ones and locked ones (washed out, so it shows they
    are not in play). Empty when none does: the common case costs nothing."""
    return {ly.name: (ly.opacity, LOCKED_FADE if ly.locked else 0.0)
            for ly in getattr(scene, "layers", ())
            if ly.opacity < 1.0 or ly.locked}


def layer_look(scene, group, base, fx=None):
    """``base`` (the container paint: its own, or :func:`layer_paint`) with
    the layers' look on top, or ``base`` itself when no layer has one."""
    fx = layer_fx(scene) if fx is None else fx
    if not fx:
        return base
    return {"layer_fx": fx, "fx_self": fx.get(object_layer(group)),
            "base": base}


def layer_lines_wanted(scene, style=None) -> bool:
    """Whether a sheet has to ink lines layer by layer: some layer has a
    line type, weight or cut weight of its own, or the style colours by
    layer."""
    style = style if style is not None else getattr(scene, "display_style",
                                                    None)
    if getattr(style, "color_by_layer", False):
        return True
    return any(ly.linetype != "continuous" or ly.lineweight is not None
               or getattr(ly, "cut_weight", None) is not None
               for ly in getattr(scene, "layers", ()))


def line_styles(scene, colored: bool) -> dict:
    """``{name: (rgb or None, linetype, lineweight or None, cut weight or
    None, dash pattern, text)}`` — how each layer's lines are inked on a sheet
    and written to a DXF (the pattern in paper mm, the document's own line
    types resolved). The colour
    only with Colour by layer on (a plan prints black otherwise), and never
    for the default layer, whose white would vanish on paper."""
    out = {}
    for ly in getattr(scene, "layers", ()):
        # A line type with a colour of its own inks with it, on any sheet.
        rgb = linetype_color(ly.linetype, scene) or (
            layer_color(ly) if colored and ly.name != DEFAULT_LAYER
            else None)
        out[ly.name] = (rgb, ly.linetype, ly.lineweight,
                        getattr(ly, "cut_weight", None),
                        linetype_pattern(ly.linetype, scene),
                        linetype_text(ly.linetype, scene))
    return out


def legend_rows(scene) -> tuple[list, dict]:
    """What a sheet's layer legend shows: the visible, printed layers'
    names and, for each, its swatch — colour and line type."""
    rows, swatches = [], {}
    for ly in getattr(scene, "layers", ()):
        if not ly.visible or not getattr(ly, "printable", True):
            continue
        rows.append(ly.name)
        swatches[ly.name] = {"color": [round(c, 4) for c in layer_color(ly)],
                             "linetype": ly.linetype}
        if ly.linetype.startswith(CUSTOM_LINETYPE):
            swatches[ly.name]["pattern"] = list(linetype_pattern(
                ly.linetype, scene))
        if getattr(ly, "hatch", None):
            swatches[ly.name]["hatch"] = ly.hatch
            if getattr(ly, "hatch_angle", 0.0):
                swatches[ly.name]["hatch_angle"] = ly.hatch_angle
            families = layer_hatch_families(scene, ly)
            if families:
                swatches[ly.name]["hatch_families"] = families
            for key, rgb in (("hatch_ground", hatch_ground_rgb(ly)),
                             ("hatch_color", hatch_ink_rgb(ly))):
                if rgb is not None:
                    swatches[ly.name][key] = [round(c, 4) for c in rgb]
    return rows, swatches


def cut_hatches(scene) -> dict:
    """``{name: pattern}`` of the layers whose section cut has a hatch of
    its own (see ``core.hatches``) — empty when none has."""
    return {ly.name: ly.hatch for ly in getattr(scene, "layers", ())
            if getattr(ly, "hatch", None)}


def cut_hatch_grounds(scene) -> dict:
    """``{name: rgb}`` — the solid colour under each hatched layer's
    pattern, for the layers that have one."""
    out = {}
    for ly in getattr(scene, "layers", ()):
        rgb = hatch_ground_rgb(ly) if getattr(ly, "hatch", None) else None
        if rgb is not None:
            out[ly.name] = rgb
    return out


def hatch_families(scene, key):
    """The families of an imported pattern (``pat:<name>``) kept in the
    document, ``None`` for a built-in one (or one the document lost)."""
    from core.hatches import IMPORTED
    if not (isinstance(key, str) and key.startswith(IMPORTED)):
        return None
    entry = (getattr(scene, "hatch_patterns", None) or {}).get(
        key[len(IMPORTED):])
    return entry.get("families") if isinstance(entry, dict) else None


def layer_brick(scene, ly):
    """The piece a layer's masonry hatch is drawn with: its own
    (``Layer.brick``), else the document's of that kind (``Scene.bricks``:
    brick, ticholo, block), else ``None`` — the usual one of its kind."""
    own = getattr(ly, "brick", None)
    if own is not None:
        return own
    from core.hatches import piece_kind
    kind = piece_kind(getattr(ly, "hatch", None))
    return (getattr(scene, "bricks", None) or {}).get(kind) if kind else None


def load_bricks(scene, raw) -> None:
    """The document's pieces as a file or a template stores them,
    ``{kind: size}``, read defensively into ``Scene.bricks``."""
    from core.hatches import PIECE_SIZES, clean_brick
    if not isinstance(raw, dict):
        return
    for kind, size in raw.items():
        size = clean_brick(size) if kind in PIECE_SIZES else None
        if size is not None:
            scene.bricks = dict(getattr(scene, "bricks", None) or {},
                                **{kind: size})


def layer_hatch_families(scene, ly):
    """The families a layer's hatch is drawn with when they are not the
    built-in pattern's own: an imported pattern's, or a brick pattern's
    drawn with the layer's brick (its own or the document's). ``None``
    otherwise."""
    key = getattr(ly, "hatch", None)
    families = hatch_families(scene, key)
    brick = layer_brick(scene, ly)
    if families is None and brick is not None:
        from core.hatches import BRICKS, brick_families
        if key in BRICKS:
            return [list(f[:5]) + [list(f[5])]
                    for f in brick_families(key, brick)]
    return families


def hatch_label(scene, key) -> str:
    """A pattern's name as the user knows it (untranslated): the built-in
    label, or an imported pattern's own name."""
    from core.hatches import HATCH_LABELS, IMPORTED
    if key in HATCH_LABELS:
        return HATCH_LABELS[key]
    if isinstance(key, str) and key.startswith(IMPORTED):
        return key[len(IMPORTED):]
    return ""


def hatch_grows(ly) -> bool:
    """Whether a layer's hatch grows with the drawing's scale: as the layer
    says, else as its pattern goes — a material with a real size (brick,
    tiles, boards…) does, a stipple or a generic hatch keeps its size on
    paper."""
    own = getattr(ly, "hatch_on_paper", None)
    if own is not None:
        return not own
    from core.hatches import REAL_SIZE
    return getattr(ly, "hatch", None) in REAL_SIZE


def cut_hatch_forms(scene, scale_n: float = 100.0) -> dict:
    """``{name: {"angle", "scale", "families", "brick", "scale_n"}}`` — how
    each hatched layer's pattern is laid on a sheet drawn at 1:``scale_n``:
    turned, sized (on paper; or with the drawing — a material at its real
    size, any other pattern from its size at 1:100), the families of an
    imported pattern or of the layer's own brick, and that brick."""
    out = {}
    for ly in getattr(scene, "layers", ()):
        key = getattr(ly, "hatch", None)
        if not key:
            continue
        size = float(getattr(ly, "hatch_scale", 1.0) or 1.0)
        if hatch_grows(ly):
            from core.hatches import real_scale
            real = real_scale(key, scale_n, layer_brick(scene, ly))
            size *= (real if real is not None
                     else 100.0 / max(1e-6, float(scale_n or 100.0)))
        out[ly.name] = {"angle": float(getattr(ly, "hatch_angle", 0.0) or 0.0),
                        "scale": size,
                        "families": layer_hatch_families(scene, ly),
                        "brick": layer_brick(scene, ly),
                        "cross": bool(getattr(ly, "hatch_cross", False)),
                        "joints": getattr(ly, "joints", None),
                        "mortar": bool(getattr(ly, "mortar", False)),
                        "hatch_scale": float(getattr(ly, "hatch_scale", 1.0)
                                             or 1.0),
                        "offset": getattr(ly, "hatch_offset", None),
                        "scale_n": float(scale_n or 100.0)}
    return out


def clean_offset(raw) -> tuple | None:
    """A pattern's shift as a layer keeps it: ``(x, y)`` real mm, each
    within ±10 m — ``None`` for none or for anything else."""
    import math
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return None
    try:
        x, y = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)) or (not x and not y):
        return None
    return (min(10000.0, max(-10000.0, x)),
            min(10000.0, max(-10000.0, y)))


def cut_hatch_inks(scene) -> dict:
    """``{name: rgb}`` — the ink of each hatched layer's pattern, for the
    layers that set one (by layer or fixed)."""
    out = {}
    for ly in getattr(scene, "layers", ()):
        rgb = hatch_ink_rgb(ly) if getattr(ly, "hatch", None) else None
        if rgb is not None:
            out[ly.name] = rgb
    return out


def cut_fill_colours(scene) -> dict:
    """``{name: rgb}`` a sheet fills each layer's section cut with when the
    frame asks for the layers' colours: every layer's own colour (picked or
    automatic), except the default layer, which keeps the frame's fill — its
    white would vanish on paper."""
    return {ly.name: layer_color(ly) for ly in getattr(scene, "layers", ())
            if ly.name != DEFAULT_LAYER}


def unprinted(scene) -> list:
    """The layers left out of the sheets."""
    return [ly for ly in getattr(scene, "layers", ())
            if not getattr(ly, "printable", True)]


def hide_unprinted(scene) -> None:
    """Switch off the layers that do not print — for a sheet's render, whose
    caller puts the visibility back."""
    for ly in unprinted(scene):
        ly.visible = False


def active_layer(scene) -> str:
    """Where new objects go: the document's active layer while it exists,
    is visible and is not locked — anything else falls back to the default
    layer, so nothing new is ever drawn straight into hiding."""
    name = getattr(scene, "active_layer", None)
    if not name or name == DEFAULT_LAYER:
        return DEFAULT_LAYER
    ly = scene.layer(name)
    if ly is None or not ly.visible or ly.locked:
        return DEFAULT_LAYER
    return name


def folders_of(scene) -> list[str]:
    """The folder names of the Layers panel, in order: the ones the document
    lists (empty folders included), then any a layer names that is missing
    from that list."""
    out = [f for f in getattr(scene, "layer_folders", None) or ()
           if isinstance(f, str) and f]
    for ly in getattr(scene, "layers", None) or ():
        if ly.folder and ly.folder not in out:
            out.append(ly.folder)
    return out


def unique_name(taken, base: str) -> str:
    """``base 1``, ``base 2``… — the first one not in ``taken``."""
    taken = set(taken)
    n = 1
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def folder_parent(scene, name: str) -> str | None:
    """The folder ``name`` sits in, or ``None`` at the top. A parent that
    no longer exists, or one that would make a loop, reads as the top."""
    parents = getattr(scene, "folder_parents", None) or {}
    parent = parents.get(name)
    if not parent or parent not in folders_of(scene):
        return None
    seen = {name}
    up = parent
    while up is not None:
        if up in seen:
            return None
        seen.add(up)
        up = parents.get(up) if parents.get(up) in folders_of(scene) else None
    return parent


def subfolders(scene, name: str, deep: bool = False) -> list[str]:
    """The folders directly in ``name`` — or, ``deep``, at any depth."""
    out = [f for f in folders_of(scene) if folder_parent(scene, f) == name]
    if deep:
        for f in list(out):
            out += subfolders(scene, f, deep=True)
    return out


def layers_in_folder(scene, name: str) -> list[str]:
    """Every layer in ``name`` or in a folder inside it."""
    folders = {name, *subfolders(scene, name, deep=True)}
    return [ly.name for ly in scene.layers if ly.folder in folders]


def ordered_names(scene) -> list[str]:
    """The layer names in the order the Layers tab lists them with «Sort by
    order created», folders unfolded: the default layer first, then each
    folder and every layer out of one as they were made — folders before
    layers, as the tab ranks them — with what a folder holds inside it, its
    subfolders first.

    Ordering the Browser by layer follows this list, so the rows on the
    layers of a folder stay together, in the folder's place. The model is
    not touched: this is how the tab reads it."""
    layers = list(getattr(scene, "layers", None) or ())
    folders = folders_of(scene)
    place = {ly.name: i for i, ly in enumerate(layers)}
    folder_place = {f: i for i, f in enumerate(folders)}

    def made(names, places) -> list[str]:
        return sorted(names, key=places.__getitem__)

    held: dict = {}
    for ly in layers:
        if ly.name != DEFAULT_LAYER:
            held.setdefault(ly.folder, []).append(ly.name)
    below: dict = {}
    for f in folders:
        below.setdefault(folder_parent(scene, f), []).append(f)

    def block(folder, out) -> None:
        for f in made(below.get(folder, ()), folder_place):
            block(f, out)          # what a subfolder holds comes before it
        out.extend(made(held.get(folder, ()), place))

    out = [DEFAULT_LAYER] if DEFAULT_LAYER in place else []
    block(None, out)
    return out


def add_folder(scene, base: str, parent: str | None = None) -> str:
    """A new, empty folder at the end of the list — inside ``parent``
    when given; returns its name."""
    name = unique_name(folders_of(scene), base)
    scene.layer_folders = folders_of(scene) + [name]
    if parent and parent in folders_of(scene):
        scene.folder_parents = {**(getattr(scene, "folder_parents", None)
                                   or {}), name: parent}
    return name


def move_folder(scene, name: str, parent: str | None) -> bool:
    """Put the folder ``name`` inside ``parent`` (``None``: at the top).
    Refused into itself or into a folder inside it."""
    if name not in folders_of(scene):
        return False
    if parent is not None and (parent == name or parent not in folders_of(scene)
                               or parent in subfolders(scene, name, deep=True)):
        return False
    parents = dict(getattr(scene, "folder_parents", None) or {})
    if parent:
        parents[name] = parent
    else:
        parents.pop(name, None)
    scene.folder_parents = parents
    return True


def rename_folder(scene, old: str, new: str) -> bool:
    folders = folders_of(scene)
    if old not in folders or not new or new in folders:
        return False
    scene.layer_folders = [new if f == old else f for f in folders]
    for ly in scene.layers:
        if ly.folder == old:
            ly.folder = new
    parents = getattr(scene, "folder_parents", None) or {}
    scene.folder_parents = {(new if k == old else k): (new if v == old else v)
                            for k, v in parents.items()}
    return True


def remove_folder(scene, name: str) -> None:
    """Delete a folder; what it held — layers and folders — moves up into
    the folder it sat in (or to the top)."""
    up = folder_parent(scene, name)
    for ly in scene.layers:
        if ly.folder == name:
            ly.folder = up
    parents = dict(getattr(scene, "folder_parents", None) or {})
    for f, p in list(parents.items()):
        if p == name:
            if up:
                parents[f] = up
            else:
                del parents[f]
    parents.pop(name, None)
    scene.folder_parents = parents
    scene.layer_folders = [f for f in folders_of(scene) if f != name]


def move_to_folder(scene, names, folder: str | None) -> None:
    """File the layers ``names`` under ``folder`` (``None``: out of any).
    The default layer stays out of folders: it is not a layer anyone
    files, it is where the unsorted goes."""
    if folder and folder not in folders_of(scene):
        scene.layer_folders = folders_of(scene) + [folder]
    for name in names:
        ly = scene.layer(name)
        if ly is not None and name != DEFAULT_LAYER:
            ly.folder = folder or None


def set_visible(scene, names, on: bool) -> bool:
    """Show or hide the layers ``names``. Returns True when that hid the
    active layer, which then gives way to the default layer (new objects
    must never be drawn straight into hiding)."""
    for name in names:
        ly = scene.layer(name)
        if ly is not None:
            ly.visible = bool(on)
    return _release_active(scene)


def set_locked(scene, names, on: bool) -> bool:
    """Lock or unlock the layers ``names``; like :func:`set_visible`,
    True when that locked the active layer."""
    for name in names:
        ly = scene.layer(name)
        if ly is not None:
            ly.locked = bool(on)
    return _release_active(scene)


def isolate(scene, names) -> bool:
    """Show only the layers ``names`` (and the default layer: it holds the
    insides of every object, so hiding it would empty the visible ones)."""
    keep = set(names) | {DEFAULT_LAYER}
    for ly in scene.layers:
        ly.visible = ly.name in keep
    return _release_active(scene)


def taggable(entities) -> list:
    """The entities a layer is assigned to — faces, edges, groups and
    components, dimensions, leader texts, section planes, guides and
    reference images. The one list Entity Info, the right-click, the
    Layers panel and its toolbar all ask."""
    from core.dimension import Dimension
    from core.group import Group
    from core.guide import Guide
    from core.image_plane import ImagePlane
    from core.mesh import Edge, Face
    from core.section import SectionPlane
    from core.textlabel import TextLabel
    kinds = (Face, Edge, Group, Dimension, TextLabel, SectionPlane, Guide,
             ImagePlane)
    return [e for e in entities or () if isinstance(e, kinds)]


def selection_layers(scene) -> set[str]:
    """The layers what is selected sits on (empty with nothing selected) —
    what the Layers panel and the Layers toolbar highlight."""
    return {layer_of(e) for e in taggable(getattr(scene, "selection", None))}


def is_isolated(scene, name: str) -> bool:
    """Whether ``name`` is the one layer showing — besides the default
    layer, which :func:`isolate` always keeps on."""
    ly = scene.layer(name)
    if ly is None or not ly.visible or name == DEFAULT_LAYER:
        return False
    others = [o for o in scene.layers
              if o.name not in (name, DEFAULT_LAYER)]
    return bool(others) and not any(o.visible for o in others)


def set_active(scene, name: str | None) -> None:
    """Make ``name`` the layer new objects go to — shown and unlocked, as a
    layer you are about to draw on has to be. ``None`` or the default
    layer: back to the default."""
    if not name or name == DEFAULT_LAYER or scene.layer(name) is None:
        scene.active_layer = None
        return
    ly = scene.layer(name)
    ly.visible = True
    ly.locked = False
    scene.active_layer = name


def layer_state(scene) -> dict:
    """The layers' display state — visibility, lock, the active layer — to
    come back to (:func:`apply_layer_state`)."""
    return {"layers": {ly.name: (ly.visible, ly.locked)
                       for ly in scene.layers},
            "active": getattr(scene, "active_layer", None)}


def apply_layer_state(scene, state: dict) -> None:
    """Put back a :func:`layer_state`. Layers made since keep theirs, and a
    layer deleted since is simply not there to restore."""
    for ly in scene.layers:
        saved = state.get("layers", {}).get(ly.name)
        if saved is not None:
            ly.visible, ly.locked = saved
    active = state.get("active")
    scene.active_layer = active if active and scene.layer(active) else None
    _release_active(scene)


def hide_in_scenes(scene, names, hidden: bool = True) -> int:
    """Hide (or show) the layers ``names`` in every saved scene — for a
    layer made after the plans were set up, which would otherwise turn up in
    all of them. Returns how many scenes changed."""
    names = [n for n in names if scene.layer(n) is not None]
    changed = 0
    for view in getattr(scene, "saved_views", None) or ():
        before = list(getattr(view, "hidden_layers", None) or [])
        if hidden:
            after = before + [n for n in names if n not in before]
        else:
            after = [n for n in before if n not in names]
        if after != before:
            view.hidden_layers = after
            changed += 1
    return changed


#: The key a layer template file is recognised by.
TEMPLATE_KEY = "ingetrazo_layers"


def template_of(scene) -> dict:
    """The document's layers as a template: names, colours, line types,
    weights, opacity, folders and visibility — no geometry. Saved as JSON
    and loaded into another document (:func:`apply_template`), it is an
    office standard carried from one project to the next."""
    out = {TEMPLATE_KEY: 1,
           "folders": folders_of(scene),
           "layers": [ly.to_dict() for ly in scene.layers]}
    parents = {f: folder_parent(scene, f) for f in folders_of(scene)
               if folder_parent(scene, f)}
    if parents:
        out["folder_parents"] = parents
    used = {ly.linetype[len(CUSTOM_LINETYPE):] for ly in scene.layers
            if ly.linetype.startswith(CUSTOM_LINETYPE)}
    own = {n: e for n, e in (getattr(scene, "line_types", None) or {}).items()
           if n in used}
    if own:
        out["line_types"] = own
    if getattr(scene, "linetype_colors", None):
        out["linetype_colors"] = {k: list(v)
                                  for k, v in scene.linetype_colors.items()}
    if getattr(scene, "bricks", None):
        out["bricks"] = {k: [round(float(v), 2) for v in size]
                         for k, size in scene.bricks.items()}
    return out


def apply_template(scene, data) -> tuple[int, int]:
    """Bring a template's layers into ``scene``: the missing ones are added,
    the ones with the same name take the template's look (colour, line,
    opacity, folder) and keep their visibility, and nothing is removed.
    Returns ``(added, updated)``; raises ValueError on a file that is not a
    layer template."""
    if not isinstance(data, dict) or TEMPLATE_KEY not in data \
            or not isinstance(data.get("layers"), list):
        raise ValueError("not a layer template")
    for f in data.get("folders") or ():
        if isinstance(f, str) and f and f not in folders_of(scene):
            scene.layer_folders = folders_of(scene) + [f]
    raw_parents = data.get("folder_parents")
    if isinstance(raw_parents, dict):
        for f, p in raw_parents.items():
            if isinstance(f, str) and isinstance(p, str):
                move_folder(scene, f, p)
    load_line_types(scene, data.get("line_types"))
    load_linetype_colors(scene, data.get("linetype_colors"))
    load_bricks(scene, data.get("bricks"))
    added = updated = 0
    for raw in data["layers"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) \
                or not raw["name"]:
            continue
        new = Layer.from_dict(raw)
        ly = scene.layer(new.name)
        if ly is None:
            if new.name == DEFAULT_LAYER:
                continue
            scene.layers.append(new)
            added += 1
            continue
        ly.color = new.color
        ly.linetype = new.linetype
        ly.lineweight = new.lineweight
        ly.cut_weight = new.cut_weight
        ly.hatch = new.hatch
        ly.hatch_ground = new.hatch_ground
        ly.hatch_color = new.hatch_color
        ly.hatch_angle = new.hatch_angle
        ly.hatch_scale = new.hatch_scale
        ly.hatch_offset = new.hatch_offset
        ly.hatch_on_paper = new.hatch_on_paper
        ly.brick = new.brick
        ly.hatch_cross = new.hatch_cross
        ly.joints = new.joints
        ly.mortar = new.mortar
        ly.opacity = new.opacity
        if ly.name != DEFAULT_LAYER:
            ly.folder = new.folder
        updated += 1
    _release_active(scene)
    return added, updated


def load_line_types(scene, raw) -> int:
    """Bring line types stored as ``{name: {"label", "pattern"}}`` (a file,
    a template) into the document, read defensively; returns how many."""
    if not isinstance(raw, dict):
        return 0
    own = dict(getattr(scene, "line_types", None) or {})
    n = 0
    for name, entry in list(raw.items())[:500]:
        if not (isinstance(name, str) and name and isinstance(entry, dict)):
            continue
        pattern = clean_pattern(entry.get("pattern"))
        if pattern is None:
            continue
        label = entry.get("label")
        own[name[:64]] = {"label": label[:120] if isinstance(label, str)
                          else name[:64], "pattern": pattern}
        own[name[:64]].update(clean_line_text(entry, pattern) or {})
        pieces = clean_pattern(entry.get("pieces"))
        if pieces is not None:
            own[name[:64]]["pieces"] = pieces
        colour = clean_line_colour(entry.get("color"))
        if colour is not None:
            own[name[:64]]["color"] = colour
        n += 1
    scene.line_types = own
    return n


def _release_active(scene) -> bool:
    name = getattr(scene, "active_layer", None)
    if name and active_layer(scene) == DEFAULT_LAYER:
        scene.active_layer = None
        return True
    return False


def object_ids(scene) -> set:
    """Identity of every object in the document — groups and components at
    any depth (by ``id`` and by ``uid``), dimensions, leader texts,
    guides. Compared before and after a command to find what it created
    (:func:`tag_new_objects`)."""
    from core.purge import iter_groups
    ids: set = set()
    for g in iter_groups(getattr(scene, "groups", None) or ()):
        ids.add(id(g))
        if getattr(g, "uid", None):
            ids.add(g.uid)
    for coll in ("dimensions", "text_labels", "guides"):
        ids.update(id(o) for o in getattr(scene, coll, None) or ())
    return ids


#: The layers guides, dimensions and leader texts go to by themselves while
#: no layer is active: ``(scene collection, English name)``. The name is
#: translated when the layer is made, so a Spanish document gets «Guías»,
#: «Cotas» and «Textos».
AUTO_LAYERS = (("guides", "Guides"), ("dimensions", "Dimensions"),
               ("text_labels", "Texts"))


def auto_ids(scene) -> set:
    """Identity of the guides, dimensions and texts in the document — the
    cheap «before» of a command run with no active layer
    (:func:`tag_new_objects` then only looks at those lists)."""
    ids: set = set()
    for coll, _name in AUTO_LAYERS:
        ids.update(id(o) for o in getattr(scene, coll, None) or ())
    return ids


def auto_layer(scene, english: str) -> str:
    """The automatic layer for ``english`` («Guides», «Dimensions»,
    «Texts») in the interface language, made the first time it is needed.
    One the user hid or locked hands back to the default layer: nothing
    new is ever drawn straight into hiding, as with the active layer.
    «Guides» is born not printed: guides never reach a sheet, and a printed
    layer would stand in every sheet's layer legend."""
    from core.i18n import tr
    name = tr(english)
    ly = scene.layer(name)
    if ly is None:
        scene.layers.append(Layer(name, printable=english != "Guides"))
        return name
    if not ly.visible or ly.locked:
        return DEFAULT_LAYER
    return name


def _tag_automatic(scene, before: set) -> int:
    """With no layer active, the new guides go onto «Guides», the new
    dimensions onto «Dimensions» and the new texts onto «Texts»
    (scaffolding and annotation are what is switched off all at once);
    everything else stays where it was."""
    n = 0
    for coll, english in AUTO_LAYERS:
        fresh = [o for o in getattr(scene, coll, None) or ()
                 if id(o) not in before and layer_of(o) == DEFAULT_LAYER]
        if not fresh:
            continue
        name = auto_layer(scene, english)
        if name == DEFAULT_LAYER:
            continue
        for obj in fresh:
            assign_layer(obj, name)
            n += 1
    return n


def tag_new_objects(scene, before: set) -> int:
    """Put the objects a command created on the active layer.

    A group, a component, a dimension, a leader text or a guide made while
    a layer is active goes onto it; loose lines and faces stay on the default
    layer (a layer hidden never leaves half a solid). Only the outermost
    new object is tagged: a new group's own children follow it. One that
    already carries a layer (a copy, a pasted object) keeps its own. With
    no layer active, guides, dimensions and texts go to their automatic
    layers (:data:`AUTO_LAYERS`) — ``before`` is then :func:`auto_ids`.
    Returns how many objects were tagged."""
    from core.purge import iter_groups
    name = active_layer(scene)
    if name == DEFAULT_LAYER:
        return _tag_automatic(scene, before)
    # A copy that REPLACES an object (Make Unique, Replace Component…)
    # keeps its uid: that one is not new, and keeps the layer it had.
    fresh = [g for g in iter_groups(getattr(scene, "groups", None) or ())
             if id(g) not in before
             and getattr(g, "uid", None) not in before]
    # Only the outermost new objects: a new group's own children keep
    # the default layer and follow their container.
    inner = {id(c) for g in fresh for c in getattr(g, "children", None) or ()}
    fresh = [g for g in fresh if id(g) not in inner]
    for coll in ("dimensions", "text_labels", "guides"):
        fresh += [o for o in getattr(scene, coll, None) or ()
                  if id(o) not in before]
    n = 0
    for obj in fresh:
        if layer_of(obj) == DEFAULT_LAYER:
            assign_layer(obj, name)
            n += 1
    return n


def layer_of(entity) -> str:
    """The layer name an entity carries (default when unlabelled)."""
    attrs = getattr(entity, "attrs", None)
    if attrs is not None:                          # Face
        return attrs.get("layer") or DEFAULT_LAYER
    return getattr(entity, "layer", None) or DEFAULT_LAYER


def assign_layer(entity, name: str) -> None:
    """Label an entity with a layer (default name clears the label)."""
    value = None if name == DEFAULT_LAYER else name
    attrs = getattr(entity, "attrs", None)
    if attrs is not None:                          # Face
        if value is None:
            attrs.pop("layer", None)
        else:
            attrs["layer"] = value
    elif hasattr(entity, "layer"):
        entity.layer = value


def rename_layer(scene, old_name: str, new_name: str) -> bool:
    """Rename a layer and relabel everything that carries the old name —
    geometry inside groups and kept definitions included — plus the scenes
    that hide it, so a plan scene still hides the renamed layer.

    Not an undo step: renaming is easy to redo by hand, and Ctrl+Z after
    drawing should take back the drawing, not a name typed in between.
    Returns False (and changes nothing) for the default layer, an empty or
    taken name, or a layer that does not exist."""
    from core.purge import layer_carriers
    ly = scene.layer(old_name)
    if (ly is None or old_name == DEFAULT_LAYER or not new_name
            or new_name == DEFAULT_LAYER or scene.layer(new_name) is not None):
        return False
    carriers = [e for e in layer_carriers(scene) if layer_of(e) == old_name]
    ly.name = new_name
    for e in carriers:
        assign_layer(e, new_name)
    if getattr(scene, "active_layer", None) == old_name:
        scene.active_layer = new_name
    for view in getattr(scene, "saved_views", None) or ():
        hidden = getattr(view, "hidden_layers", None)
        if hidden and old_name in hidden:
            view.hidden_layers = [new_name if n == old_name else n
                                  for n in hidden]
    return True
