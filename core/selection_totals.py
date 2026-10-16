# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What a selection adds up to: how many of each kind, and their quantities.

One pass over the selection counts every kind and sums its own measure —
the faces' area, the edges' length, the solid groups' volume — whatever
else is selected alongside. The readouts decide what to show from it:
Entity Info only a quantity whose kind is the whole selection, Right-click
▸ Area ▸ Selection the faces' area alone.

Only what is selected counts: a face inside a selected group is part of
that group's volume, not of the selected area.
"""
from __future__ import annotations

from typing import Callable, Iterable

from core.dimension import Dimension
from core.group import Group
from core.mesh import Edge, Face

_KINDS = ("faces", "edges", "groups", "dimensions", "others")


class SelectionTotals:
    """Counts and quantities of one selection.

    ``faces``/``area`` (m²), ``edges``/``length`` (m), ``groups`` (groups
    and components) with ``solids``/``volume`` (m³, the solids among them),
    ``dimensions`` and ``others`` (texts, paths, images, ...). The volume
    is measured on first use: it walks every group's mesh, and the panels
    that refresh on each edit seldom need it.
    """

    def __init__(self, volume_of: Callable | None = None) -> None:
        self.faces = 0
        self.area = 0.0
        self.edges = 0
        self.length = 0.0
        self.groups = 0
        self.dimensions = 0
        self.others = 0
        self._group_list: list = []
        self._volume_of = volume_of
        self._measured: tuple[int, float] | None = None

    def _measure(self) -> tuple[int, float]:
        if self._measured is None:
            volume_of = self._volume_of
            if volume_of is None:
                from core.solids import solid_volume as volume_of
            solids, volume = 0, 0.0
            for g in self._group_list:
                vol = volume_of(g)
                if vol is not None:
                    solids += 1
                    volume += vol
            self._measured = (solids, volume)
        return self._measured

    @property
    def solids(self) -> int:
        """How many of the selected groups are closed solids."""
        return self._measure()[0]

    @property
    def volume(self) -> float:
        """The solids' volume, m³."""
        return self._measure()[1]

    @property
    def volume_complete(self) -> bool:
        """Every selected group is a solid, so ``volume`` is their whole
        volume — not a partial sum that would read as the whole."""
        return self.groups > 0 and self.solids == self.groups

    def kinds(self) -> set[str]:
        """The kinds present, among ``faces``, ``edges``, ``groups``,
        ``dimensions`` and ``others``."""
        return {k for k in _KINDS if getattr(self, k)}

    def only(self, kind: str) -> bool:
        """True when ``kind`` is all the selection holds."""
        return self.kinds() == {kind}


def selection_totals(selection: Iterable,
                     volume_of: Callable | None = None) -> SelectionTotals:
    """Count ``selection`` and add up its quantities.

    ``volume_of(group)`` gives a group's volume, or ``None`` when it is not
    a solid; :func:`core.solids.solid_volume` by default. A caller that
    refreshes often passes a cached one.
    """
    t = SelectionTotals(volume_of)
    for e in selection:
        if isinstance(e, Face):
            t.faces += 1
            t.area += e.area()
        elif isinstance(e, Edge):
            t.edges += 1
            t.length += (e.b - e.a).length()
        elif isinstance(e, Group):
            t.groups += 1
            t._group_list.append(e)
        elif isinstance(e, Dimension):
            t.dimensions += 1
        else:
            t.others += 1
    return t


def selected_area(selection: Iterable) -> float:
    """The area of the selected faces alone, in m² — whatever else is
    selected, and not the faces inside selected groups (Right-click ▸
    Area ▸ Selection)."""
    return sum(e.area() for e in selection if isinstance(e, Face))
