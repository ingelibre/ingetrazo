# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ibrahim Halim Gokbulut (h-skycloud).
"""Human-facing IFC labels. Stored tags and exports always use the code."""
from core.i18n import tr


def _plain_name(code: str) -> str | None:
    """The translated plain noun behind an IFC code, if the language has
    one (German: ``"Wand"`` for ``"IfcWall"``) — else ``None``."""
    noun = code.removeprefix("Ifc")
    name = tr(noun)
    return name if name != noun else None


def class_label(code: str) -> str:
    """The class dropdown's label: the IFC code plus its translated name
    (``"IfcWall (Wand)"`` in German). A language that translates the code
    itself keeps its own label (Turkish: ``"IfcWall — Duvar"``)."""
    label = tr(code)
    if label != code:
        return label
    name = _plain_name(code)
    return f"{code} ({name})" if name else code


def short_class_label(code: str) -> str:
    """The BIM tree's column: the translated name where the language has
    one (Turkish: "IfcWall — Duvar", German: "Wand"), else the code without
    its "Ifc" prefix, as the tree always showed ("Wall")."""
    label = tr(code)
    if label != code:
        return label
    name = _plain_name(code)
    return name if name else code.removeprefix("Ifc")
