# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Dynamic components: attributes and formulas on a component.

A component carries named *attributes* — its own (``ancho``, ``hojas``…)
and predefined ones (``lenx``, ``x``, ``rotz``, ``hidden``, ``copies``,
``material``…) — and each may be driven by a spreadsheet-style *formula*
(``=parent!lenx - 2*marco``). Redrawing evaluates every formula and lays
the parts out again: positions, sizes, turns, visibility, paint and copies.
The options an author exposes are what the user edits (Entity info ▸
Component options); the attributes and formulas are what the author writes
(Component attributes…).

**Format.** The data lives in ``group.ext[KEY]``, in the attribute layout
of .skp dynamic components (``definition_attributes`` +
``instance_attributes``, keys such as ``lenx``, ``_lenx_formula``,
``_lenx_access``; lengths stored in inches): a component read from a .skp
file is edited in that layout. Dynamic SKP export is not implemented;
``ext`` is saved and copied with the container in IGZ documents.

**Safety.** Formulas come from files we did not write: :mod:`.formula` is
its own interpreter — no ``eval``, bounded size, depth and work.

The engine (:mod:`.formula`, :mod:`.model`, :mod:`.evaluate`,
:mod:`.redraw`, :mod:`.options`, :mod:`.author`, :mod:`.apply`) is adapted
from two GPL-3.0-or-later extensions: d1rty-pixel's «Dynamic Components
for IngeTrazo» and moominot's «dc_tools». :mod:`.document` puts a redraw in
the document as one undo step.
"""
from __future__ import annotations

#: The ``ext`` key the attributes live under — the one the .skp import
#: extension writes, so components travel between the two unchanged.
KEY = "skp_dc_import"
