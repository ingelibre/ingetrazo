# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ibrahim Halim Gokbulut (h-skycloud).
"""Human-facing IFC labels. Stored tags and exports always use the code."""
from core.i18n import tr


def class_label(code: str) -> str:
    return tr(code)


def short_class_label(code: str) -> str:
    """The BIM tree's column: the translated label where the language has
    one (Turkish: "IfcWall — Duvar"), else the code without its "Ifc"
    prefix, as the tree always showed ("Wall")."""
    label = tr(code)
    return code.removeprefix("Ifc") if label == code else label
