# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A component holding two copies of a sub-assembly keeps the tree (#1328).

The report's shape: «Frame» is placed once; it places «Bay» twice, and each
«Bay» places a «Board» once and a «Bracket» twice — every part small, far
below the sharing thresholds. The 0.6.1 import kept a tree only through
definitions placed ONCE, so «Bay» (placed twice) and all it holds melted
into one 30-face mesh named «Frame». Now each level stays a child of the
one that holds it, and the copies share their definition."""
from __future__ import annotations

import os
from types import SimpleNamespace as NS

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

pytest.importorskip("openskp")
_app = QApplication.instance() or QApplication([])

from core.scene import Scene  # noqa: E402
from formats import skp, skp_openskp  # noqa: E402
from tests.test_skp_nested_parts_866 import _box  # noqa: E402

_ID = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]


def _at(x, y=0, z=0):
    return _ID[:9] + [x, y, z, 1]


def _model():
    board = _box(5, "Board", 10, 1, 1)
    bracket = _box(6, "Bracket", 1, 1, 1)
    bay = NS(id=7, name="Bay", vertices={}, edges={}, faces={}, instances=[
        NS(ref_idx=5, matrix=_ID),
        NS(ref_idx=6, matrix=_at(0, 0, -1)),
        NS(ref_idx=6, matrix=_at(9, 0, -1))])
    frame = NS(id=8, name="Frame", vertices={}, edges={}, faces={},
               instances=[NS(ref_idx=7, matrix=_ID),
                          NS(ref_idx=7, matrix=_at(0, 20, 0))])
    root = NS(id=0, name="ROOT_MODEL", vertices={}, edges={}, faces={},
              instances=[NS(ref_idx=8, matrix=_ID)])
    return NS(definitions={d.id: d for d in (root, board, bracket, bay,
                                              frame)})


def _imported():
    scene = Scene()
    skp.apply_payload(scene, skp_openskp._adapt(_model(), "repro_shared"))
    return scene


def test_a_sub_assembly_copied_inside_a_component_stays_its_child():
    [frame] = _imported().groups
    assert frame.name == "Frame"
    assert not frame.mesh.faces                     # nothing melted into it
    bays = frame.children
    assert [b.name for b in bays] == ["Bay", "Bay"]
    assert all(b.component for b in bays)
    assert bays[0].mesh is bays[1].mesh             # one shared definition
    for bay in bays:
        assert not bay.mesh.faces
        assert sorted(c.name for c in bay.children) == [
            "Board", "Bracket", "Bracket"]
        assert all(len(c.mesh.faces) == 6 for c in bay.children)


def test_the_copies_keep_their_places():
    [frame] = _imported().groups
    offsets = sorted(round(b.xform.column(3).y(), 6) for b in frame.children)
    # inches → metres happens in the vertices; the placement keeps 20 in
    assert offsets[0] == 0.0 and offsets[1] > 0.0


def test_a_tiny_part_repeated_past_the_budget_still_flattens(monkeypatch):
    monkeypatch.setattr(skp_openskp, "_NESTED_KEEP_BUDGET", 2)
    [frame] = _imported().groups
    # the two «Bay» copies fit; their four brackets and two boards do not
    assert [b.name for b in frame.children] == ["Bay", "Bay"]
    assert all(not b.children and len(b.mesh.faces) == 18
               for b in frame.children)


def test_a_part_also_placed_in_a_flattened_copy_is_not_pulled_out():
    from formats import openskp_compat
    openskp_compat.reset_group_definitions()     # kinds unknown: «Loose»
    model = _model()                              # copies flatten
    loose = NS(id=9, name="Loose", vertices={}, edges={}, faces={},
               instances=[NS(ref_idx=6, matrix=_ID)])
    model.definitions[9] = loose
    model.definitions[0].instances += [NS(ref_idx=9, matrix=_at(50)),
                                       NS(ref_idx=9, matrix=_at(60))]
    scene = Scene()
    skp.apply_payload(scene, skp_openskp._adapt(model, "repro_shared"))
    by_name = {}
    for g in scene.groups:
        by_name.setdefault(g.name, []).append(g)
    assert sorted(by_name) == ["Frame", "Loose"]  # no «Bracket» pulled out
    assert all(len(g.mesh.faces) == 6 and not g.children
               for g in by_name["Loose"])
    [frame] = by_name["Frame"]
    for bay in frame.children:                    # the bracket stays in
        assert [c.name for c in bay.children] == ["Board"]
        assert len(bay.mesh.faces) == 12
