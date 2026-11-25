# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 moominot and IngeTrazo contributors.
# Adapted from moominot's «dc_tools» extension (GPL-3.0-or-later,
# https://github.com/moominot/ingetrazo-skp-dc-import).
"""Authoring dynamic components in IngeTrazo, in the .skp format.

The attributes live where the .skp importer puts them: ``group.ext[KEY]``,
``definition_attributes`` + ``instance_attributes`` (the instance wins), with
the format's keys: ``name`` (value), ``_name_formula``, ``_name_label``,
``_name_access`` (NONE / TEXTBOX / LIST / VIEW), ``_name_formlabel``,
``_name_options`` («&label=value&…»), ``_name_units``. A component made
here is read by the same evaluator, by the same rules, as one from a .skp.

Nothing here touches the document: an edit is a dict of key changes that
:func:`apply.redraw_group` applies while it builds the new tree, so the
whole change is one undo step.
"""
from __future__ import annotations

from urllib.parse import quote

KEY = "skp_dc_import"
from .options import _natural

DELETE = object()                 # a key change that removes the key

#: The predefined attributes, in the order an «Add attribute» menu
#: lists them, with the units they are measured in.
GROUPS = (
    ("Component Info", (("name", "STRING"), ("summary", "STRING"),
                        ("description", "STRING"), ("itemcode", "STRING"))),
    ("Position", (("x", "LENGTH"), ("y", "LENGTH"), ("z", "LENGTH"))),
    ("Size", (("lenx", "LENGTH"), ("leny", "LENGTH"), ("lenz", "LENGTH"))),
    ("Rotation", (("rotx", "DEGREES"), ("roty", "DEGREES"), ("rotz", "DEGREES"))),
    ("Behaviors", (("material", "STRING"), ("scaletool", "STRING"), ("hidden", "BOOLEAN"),
                   ("onclick", "STRING"), ("copies", "INTEGER"))),
    ("Form Design", (("imageurl", "STRING"), ("dialogwidth", "FLOAT"),
                     ("dialogheight", "FLOAT"))),
)
PREDEFINED = tuple(item for _title, items in GROUPS for item in items)
PREDEFINED_NAMES = tuple(n for n, _ in PREDEFINED)
LABELS = {"x": "X", "y": "Y", "z": "Z", "lenx": "LenX", "leny": "LenY", "lenz": "LenZ",
          "rotx": "RotX", "roty": "RotY", "rotz": "RotZ", "hidden": "Hidden",
          "material": "Material", "copies": "Copies", "name": "Name",
          "summary": "Summary", "description": "Description", "itemcode": "ItemCode",
          "scaletool": "ScaleTool", "onclick": "onClick", "imageurl": "ImageURL",
          "dialogwidth": "DialogWidth", "dialogheight": "DialogHeight"}
ACCESS = ("NONE", "VIEW", "TEXTBOX", "LIST")
META = ("formula", "label", "access", "formlabel", "options", "units", "formulaunits", "error")


def new_dynamic_data(name: str, units: str = "CENTIMETERS") -> dict:
    """The ext record a part gets when it becomes dynamic."""
    return {"definition": name, "definition_guid": "", "instance_guid": "",
            "is_group": False,
            "definition_attributes": {},
            "instance_attributes": {"_name": name, "_lengthunits": units,
                                    "_formatversion": 1.0, "_hasbehaviors": 1.0}}


def valid_name(name: str) -> bool:
    """Attribute names: a letter first, then letters, digits, _."""
    name = str(name or "")
    return bool(name) and (name[0].isalpha()) and all(c.isalnum() or c == "_" for c in name)


def merged(group) -> dict:
    data = (group.ext or {}).get(KEY) or {}
    out = dict(data.get("definition_attributes") or {})
    out.update(data.get("instance_attributes") or {})
    return out


def attribute_names(attrs: dict) -> list:
    """The attributes a part shows in the editor: predefined ones it carries
    (the format's order), then its own, alphabetical. Internal keys (``_…``,
    ``copy``, cached nominal sizes) are not attributes."""
    present = set()
    for k in attrs:
        if k.startswith("_"):
            base = k[1:]
            for suffix in META:
                if base.endswith("_" + suffix):
                    present.add(base[: -len(suffix) - 1])
                    break
        elif k not in ("copy",):
            present.add(k)
    present = {n for n in present if n and not n.startswith("_") and not n.startswith("inst_")}
    pre = [n for n in PREDEFINED_NAMES if n in present]
    own = sorted((n for n in present if n not in PREDEFINED_NAMES), key=_natural)
    return pre + own


def set_changes(name: str, *, value=None, formula=None, label=None, access=None,
                formlabel=None, options=None, units=None) -> dict:
    """The key changes for one attribute. ``None`` leaves a field as it is;
    ``""`` clears it (a formula of ``""`` means «no formula»)."""
    name = name.lower()
    out = {}
    if value is not None:
        out[name] = value
    if formula is not None:
        f = str(formula).strip()
        if f.startswith("="):
            f = f[1:].strip()
        out[f"_{name}_formula"] = f if f else DELETE
    for field, v in (("label", label), ("access", access), ("formlabel", formlabel),
                     ("units", units)):
        if v is not None:
            out[f"_{name}_{field}"] = v if v != "" else DELETE
    if options is not None:
        out[f"_{name}_options"] = encode_options(options) if options else DELETE
    if label is None and value is not None and name in LABELS:
        out.setdefault(f"_{name}_label", LABELS[name])
    return out


def delete_changes(attrs: dict, name: str) -> dict:
    """Every key of attribute ``name`` removed."""
    name = name.lower()
    out = {}
    for k in attrs:
        if k == name or (k.startswith(f"_{name}_") and k[len(name) + 2:] in META):
            out[k] = DELETE
    return out


def encode_options(choices) -> str:
    """[(label, value), …] → «&label=value&…», percent-encoded as .skp files
    write it (UTF-8 here: the reader takes either)."""
    parts = [f"{quote(str(l), safe=' ')}={quote(str(v), safe=' =')}" for l, v in choices]
    return "&" + "&".join(parts) + "&"


def apply_changes(data: dict, changes: dict) -> None:
    """Apply key ``changes`` to an ext record in place: set in the
    instance's dictionary; DELETE removes from both."""
    inst = data.setdefault("instance_attributes", {})
    defs = data.setdefault("definition_attributes", {})
    for k, v in changes.items():
        if v is DELETE:
            inst.pop(k, None)
            defs.pop(k, None)
        else:
            inst[k] = v
