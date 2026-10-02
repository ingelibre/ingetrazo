# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""One status-bar hint at a time, for the tool and the step it is in —
the classic status bar («Select objects. Shift = Add/Subtract…»), not a
strip of every shortcut at once (Marco, 2026-09-15: «mostrarlos varios al
mismo tiempo como que no es bueno»).

:func:`hint_for` answers for a tool key and its live state. Phases are
read off the tool: ``start_point`` set means the first click is down;
the arc knows its bulge step, the fillet its sizing step. Tools not in
the table fall back to their name."""
from __future__ import annotations

from core.i18n import tr

#: Tool key → hint per phase. A plain string is the same hint always.
HINTS: dict = {
    "select": "Shift = add/remove, Ctrl = add. Double-click a group to edit it. F3 = search commands.",
    "change_axes": ("Click the new origin.",
                    "Click the red direction, then the green one."),
    "outer_shell": ("Click a solid group or component (1).",
                    "Click another solid (2) — and more to add them."),
    "solid_union": ("Click a solid group or component (1).",
                    "Click another solid (2) — and more to add them."),
    "solid_subtract": ("Click the solid that cuts (1).",
                       "Click the solid to cut (2). The first one goes away."),
    "solid_trim": ("Click the solid that cuts (1).",
                   "Click the solid to cut (2). The first one stays."),
    "solid_intersect": ("Click a solid group or component (1).",
                        "Click another solid (2): only what they share stays."),
    "solid_split": ("Click a solid group or component (1).",
                    "Click another solid (2): three pieces come out."),
    "eraser": "Drag over edges to erase them. Shift = hide instead.",
    "paint": "Click a face to paint it. Alt = sample the material under the cursor.",
    "line": ("Click the start point. Arrows lock an axis, Shift locks the inference.",
             "Click the end point, or type the length and Enter."),
    "freehand": "Press and drag to draw a freehand line.",
    "rectangle": ("Click the first corner. Arrows pick the plane; Ctrl = centre.",
                  "Click the opposite corner, or type width;height and Enter."),
    "rotated_rect": ("Click the first corner of the base edge.",
                     "Edge end, then width (or type them). Shift holds the direction."),
    "circle": ("Click the centre. Arrows pick the plane, Down = perpendicular to an edge. Type the sides first.",
               "Click the radius, or type it and Enter."),
    "polygon": ("Click the centre. Arrows pick the plane, Down = perpendicular to an edge. Type the sides first.",
                "Click the radius, or type it and Enter."),
    "arc": {
        "idle": "Click the start point — on an edge to draw a tangent arc.",
        "end": "End point. Magenta = same distance; double-click rounds.",
        "bulge": "Click the bulge, or type it. 'Nr' = radius, 'Ns' = segments. Alt keeps the corner.",
    },
    "arc3": ("Click the start point.", "Click a point the arc passes through, then the end."),
    "center_arc": ("Click the centre.", "Click the start of the arc, then its end; or type the angle."),
    "pie": ("Click the centre.", "Click the start of the wedge, then its end; or type the angle."),
        # Ctrl is not spelled out here any more: the tool's own clause carries it
    # — «Ctrl = [keep the base] / move the base» — the way the Tape's does,
    # and repeating it ate the room the instruction needs (Marco, 2026-09-17).
    "pushpull": ("Click a face and move.",
                 "Move, or type the distance and Enter. Double-click repeats the last."),
    "move": ("Click what to move (or select it first). Red + on a group = rotate it.",
             "Click the destination, or type the distance and Enter."),
    "rotate": ("Click the centre of rotation — on a face, the protractor takes its plane.",
               "Click the start of the angle, then the end; or type the degrees."),
    "scale": ("Select something, then drag a grip: corners uniform, edges along an axis.",
              "Drag, or type a factor (2) or a size (2m). Ctrl = centre, Shift = uniform."),
    "flip": "Click the plane to mirror the selection across.",
    "followme": ("Select the path, then click the profile face. Alt = sweep along the selection.",
                 "Move along the path; click to finish."),
    "offset": ("Click a face, or connected edges, to offset.",
               "Move to set the offset, or type it and Enter."),
    "fillet": {
        "idle": "Click an edge to round it (or select edges first); type the radius and Enter.",
        "sizing": "Move to set the radius, or type it and Enter; click to round. 'Ns' = segments.",
    },
    # Short on purpose: the Ctrl clause these two now carry says what they
    # leave behind, so repeating "to pull a guide" here only ate the room
    # and got the line elided (Marco, 2026-09-17). The classic hint is just
    # as terse — «Haz clic en un elemento que desees medir.» — with the
    # modifiers as their own clauses after it.
    "tape": ("Click a point or an edge to measure. Arrows lock an axis.",
             "Click the second point, or type the distance and Enter."),
    "protractor": ("Click the vertex of the angle.",
                   "Click the start of the angle, then the end; or type the degrees."),
    "dimension": ("Click the first point of the dimension.",
                  "Click the 2nd point, then place it; past an end = linear."),
    # Two phases, because after the anchor click the tool is doing
    # something else entirely — the second click sets where the label sits
    # and the wording is then asked for in a dialog. Repeating the opening
    # sentence there said nothing and left no room for the Alt clause.
    "text": ("Click a point for a label, or empty space for a screen note.",
             "Click where the label goes; the text is asked for next."),
    "geopath": "Click the points of the path; Enter or double-click finishes.",
    "section": "Click a face to place the section plane. Shift keeps the orientation.",
    "texture_position": "Drag a pin: red moves, green scales/rotates, blue shears. Enter finishes.",
    "image": "Click the first corner of the image, then the opposite one. Shift frees the aspect.",
    "paste": "Click where the copy goes. Arrows lock an axis.",
    "place_group": "Click where the component goes.",
    # The classic walkthrough hint (Marco's recording, 2026-09-18),
    # trimmed to the bar's budget.
    "position_camera": "Click where to stand, or drag toward what to look at. Type the eye height.",
    "look_around": "Drag to turn the camera. Type the eye height.",
    "walk": "Click and drag to walk. Ctrl = run, Shift = up/down or sideways, Alt = through walls.",
    "first_person": "W/A/S/D = walk, Q/E = down/up, drag = look. Shift = run, Alt = through walls.",
}

NAV_HINTS: dict = {
    "orbit": "Drag to orbit. Shift = pan. Wheel = zoom. The middle button orbits from any tool.",
    "pan": "Drag to pan. Wheel = zoom.",
    "zoom": "Drag up to zoom in, down to zoom out. Wheel zooms at the cursor.",
    "zoom_window": "Drag a box to zoom into it.",
}


def phase_of(key: str, tool) -> str:
    """Which step the tool is in: ``idle``, ``started``, or a tool-specific
    phase (the arc's ``end`` / ``bulge``, the fillet's ``sizing``)."""
    if key == "arc":
        if getattr(tool, "end_point", None) is not None:
            return "bulge"
        return "end" if getattr(tool, "start_point", None) is not None else "idle"
    if key == "fillet":
        return "sizing" if getattr(tool, "sizing", False) else "idle"
    if getattr(tool, "start_point", None) is not None:
        return "started"
    if getattr(tool, "dragging", False) or getattr(tool, "nodes", None):
        return "started"
    return "idle"


#: What each linear-inference mode reads as in the hint, the classic way of
#: saying it: the usual status bar carries «Alt = Activar/desactivar
#: "Inferencias lineales" (Ninguno activo)» while a line is being drawn —
#: the offer AND the current state, right where the hand is looking.
#:
#: Ours says «inferences», not «linear inferences», and names the state in
#: a word: the classic bar spends a whole line on this and we have half of it
#: (MESSAGE_SHARE), so the full name spent 52 characters of a 110-character
#: budget and got the end of the hint elided. The long name still shows
#: where it is not competing for room — Viewport._draw_linear_mode_label
#: paints «Inferencias: solo paralela / perpendicular (Alt)» on the canvas
#: the whole time the mode is off the default.
_LINEAR_MODES = {
    "all": "all",
    "off": "none",
    "parallel_perp": "parallel / perpendicular",
}


def alt_inference_hint(mode: str | None) -> str:
    """The «Alt = …» clause, or "" when there is nothing to offer."""
    label = _LINEAR_MODES.get(mode or "all")
    if label is None:
        return ""
    return tr('Alt = inferences ({state})', state=tr(label))


def hint_for(key: str | None, tool, nav_mode: str | None = None,
             linear_mode: str | None = None) -> str:
    """The one line the status bar shows now. With ``linear_mode`` and a
    tool mid-operation, the Alt offer is appended, the classic way."""
    if nav_mode is not None and nav_mode in NAV_HINTS:
        return tr(NAV_HINTS[nav_mode])
    entry = HINTS.get(key or "")
    if entry is None:
        name = getattr(tool, "name", None)
        return tr("{name}: Esc cancels.", name=tr(name)) if name else ""
    if isinstance(entry, str):
        return _with_alt(tr(entry), key, tool, linear_mode)
    phase = phase_of(key, tool)
    if isinstance(entry, dict):
        return _with_alt(tr(entry.get(phase) or entry.get("idle") or ""),
                         key, tool, linear_mode)
    idle, started = entry
    text = tr(started if phase != "idle" else idle)
    return _with_alt(text, key, tool, linear_mode)


def _with_alt(text: str, key, tool, linear_mode) -> str:
    """Append the tool's own clause, then the Alt one.

    The tool's stays up the whole time it is active (the classic bar keeps
    its modifiers on screen); Alt's only appears mid-operation, because that is
    the only time the key does anything (issue #26)."""
    # One modifier at a time, each in the phase where it does something —
    # the classic line carries «Ctrl = …» before the first click and
    # «Alt = …» once a line is under way, never both. Stacking them made
    # the bar elide (Marco, 2026-09-17: «no sale completo el texto»).
    if phase_of(key, tool) == "idle":
        own = getattr(tool, "status_clause", None)
        own = own() if callable(own) else ""
        return f"{text} | {own}" if own else text
    if linear_mode is None:
        return text
    # …and only where the key HAS something to do. Linear inferences reach
    # a tool through the snap engine, so a tool that does not snap — the
    # eraser, Scale, Select, Position Texture — was being offered a toggle
    # that changes nothing for it, and the dead clause was what pushed
    # those lines past the end of the bar.
    if not getattr(tool, "uses_snap", False):
        return text
    clause = alt_inference_hint(linear_mode)
    return f"{text} | {clause}" if clause else text
