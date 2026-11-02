# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A component holding other components keeps them (#866, @DarkBiscuits).

The report's repro: «Asm» places «PartA» and «PartB» once each, and the
model places «Asm» once. It arrived as one 12-face mesh named «Asm», the
parts nowhere — for a shop model, the whole cut list gone. The parts now
come in as Asm's children, each with its own name and geometry."""
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

_ID = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]


def _box(did, name, x, y, z):
    """A closed box ``x × y × z`` inches, outward faces."""
    p = {1: (0, 0, 0), 2: (x, 0, 0), 3: (x, y, 0), 4: (0, y, 0),
         5: (0, 0, z), 6: (x, 0, z), 7: (x, y, z), 8: (0, y, z)}
    quads = [(1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5), (2, 3, 7, 6),
             (3, 4, 8, 7), (4, 1, 5, 8)]
    edges, faces, eid = {}, {}, 100
    key = {}
    for fi, q in enumerate(quads):
        loop = []
        for a, b in zip(q, q[1:] + q[:1]):
            k = (min(a, b), max(a, b))
            if k not in key:
                key[k] = eid
                edges[eid] = NS(id=eid, v1_id=k[0], v2_id=k[1])
                eid += 1
            e = edges[key[k]]
            loop.append((e.id, 1 if (e.v1_id, e.v2_id) == (a, b) else 0))
        faces[200 + fi] = NS(id=200 + fi, loops=[loop], normal=None,
                             material_id=None)
    return NS(id=did, name=name, faces=faces, edges=edges, instances=[],
              vertices={i: NS(id=i, x=c[0], y=c[1], z=c[2])
                        for i, c in p.items()})


def _model():
    a = _box(5, "PartA", 1, 2, 3)
    b = _box(6, "PartB", 2, 2, 1)
    asm = NS(id=7, name="Asm", vertices={}, edges={}, faces={}, instances=[
        NS(ref_idx=5, matrix=_ID),
        NS(ref_idx=6, matrix=_ID[:9] + [3, 0, 0, 1])])
    root = NS(id=0, name="ROOT_MODEL", vertices={}, edges={}, faces={},
              instances=[NS(ref_idx=7, matrix=_ID)])
    return NS(definitions={d.id: d for d in (root, a, b, asm)})


def test_the_parts_of_an_assembly_stay_its_children():
    scene = Scene()
    skp.apply_payload(scene, skp_openskp._adapt(_model(), "repro_nested"))
    [asm] = scene.groups
    assert asm.name == "Asm"
    assert not asm.mesh.faces                       # nothing merged into it
    assert sorted(c.name for c in asm.children) == ["PartA", "PartB"]
    assert all(len(c.mesh.faces) == 6 for c in asm.children)
