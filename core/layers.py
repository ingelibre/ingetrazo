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

#: How much a locked layer's faces wash toward white: drawn, but plainly
#: not in play.
LOCKED_FADE = 0.55


class Layer:
    """A named tag with display state.

    ``color`` is an RGB or RGBA tuple (0–1), or ``None`` for the automatic
    one (see :func:`layer_color`). Its alpha belongs to Colour by layer; it
    is deliberately separate from :attr:`opacity`, which affects the whole
    layer whatever face style is active. ``folder`` is the name of the
    folder the layer is filed under in the Layers panel, or ``None``. A
    folder only organises the list: entities still carry the layer's name
    and nothing else."""

    def __init__(self, name: str, visible: bool = True,
                 locked: bool = False, color=None,
                 folder: str | None = None, linetype: str = "continuous",
                 lineweight: float | None = None,
                 opacity: float = 1.0, printable: bool = True) -> None:
        self.name = name
        self.visible = visible
        self.locked = locked
        self.color = tuple(color) if color is not None else None
        self.folder = folder or None
        #: How the layer's edges are inked on a sheet and in a DXF:
        #: one of :data:`LINETYPES`.
        self.linetype = linetype if linetype in LINETYPES else "continuous"
        #: Pen width on a sheet, in millimetres (``None``: the sheet's own
        #: pen for the line's class).
        self.lineweight = lineweight
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
            # RGB stays exactly the 0.5.11 representation. A fourth value is
            # optional, so older builds simply ignore it and keep the colour
            # (opaque) instead of refusing the document.
            channels = 4 if len(self.color) > 3 \
                and float(self.color[3]) < 0.99995 else 3
            entry["color"] = [round(float(c), 4)
                              for c in self.color[:channels]]
        if self.folder:
            entry["folder"] = self.folder
        if self.linetype != "continuous":
            entry["linetype"] = self.linetype
        if self.lineweight is not None:
            entry["lineweight"] = round(float(self.lineweight), 3)
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
                or not self.printable)

    @classmethod
    def from_dict(cls, raw: dict) -> "Layer":
        color = raw.get("color")
        if not (isinstance(color, (list, tuple)) and len(color) >= 3):
            color = None
        else:
            try:
                rgb = tuple(min(1.0, max(0.0, float(c)))
                            for c in color[:3])
            except (TypeError, ValueError):
                color = None
            else:
                # A malformed optional alpha must not throw away a valid
                # colour written by another program.
                try:
                    alpha = (min(1.0, max(0.0, float(color[3])))
                             if len(color) > 3 else 1.0)
                except (TypeError, ValueError):
                    alpha = 1.0
                color = rgb + ((alpha,) if alpha < 0.99995 else ())
        folder = raw.get("folder")
        weight = raw.get("lineweight")
        try:
            weight = (min(5.0, max(0.05, float(weight)))
                      if weight is not None else None)
        except (TypeError, ValueError):
            weight = None
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
                   printable=raw.get("printable", True) is not False)


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


def layer_rgba(layer) -> tuple:
    """The layer colour with its Colour-by-layer alpha.

    :func:`layer_color` intentionally remains RGB: sheet pens and the R12
    DXF palette have no alpha channel, and keeping that boundary also makes
    the new document value harmless to existing exporters. Only a colour
    explicitly picked with transparency can have an alpha below one;
    automatic colours are opaque.
    """
    rgb = layer_color(layer)
    alpha = 1.0
    color = getattr(layer, "color", None) if layer is not None else None
    if color is not None and len(color) > 3:
        try:
            alpha = min(1.0, max(0.0, float(color[3])))
        except (TypeError, ValueError):
            pass
    return (*rgb, alpha)


def _layer_paint_color(layer) -> tuple:
    """RGB as before when opaque; RGBA only when alpha carries meaning."""
    rgba = layer_rgba(layer)
    return rgba if rgba[3] < 0.99995 else rgba[:3]


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
    ``core.materials.effective_attrs``): every layer's RGB/RGBA colour by
    name, and the object's own layer colour for the faces that carry none.
    Opaque entries remain RGB so existing paint signatures do not change."""
    table = {ly.name: _layer_paint_color(ly)
             for ly in getattr(scene, "layers", ())}
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
    line type or weight of its own, or the style colours by layer."""
    style = style if style is not None else getattr(scene, "display_style",
                                                    None)
    if getattr(style, "color_by_layer", False):
        return True
    return any(ly.linetype != "continuous" or ly.lineweight is not None
               for ly in getattr(scene, "layers", ()))


def line_styles(scene, colored: bool) -> dict:
    """``{name: (rgb or None, linetype, lineweight or None)}`` — how each
    layer's lines are inked on a sheet and written to a DXF. The colour
    only with Colour by layer on (a plan prints black otherwise), and never
    for the default layer, whose white would vanish on paper."""
    out = {}
    for ly in getattr(scene, "layers", ()):
        rgb = (layer_color(ly) if colored and ly.name != DEFAULT_LAYER
               else None)
        out[ly.name] = (rgb, ly.linetype, ly.lineweight)
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
    return rows, swatches


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
        ly.opacity = new.opacity
        if ly.name != DEFAULT_LAYER:
            ly.folder = new.folder
        updated += 1
    _release_active(scene)
    return added, updated


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
