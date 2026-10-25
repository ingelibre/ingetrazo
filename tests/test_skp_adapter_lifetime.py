# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Recursive adapter helpers must not pin the parsed model until cyclic GC."""
import gc
from types import SimpleNamespace as NS
import weakref

from formats import skp_openskp


class _Definition(NS):
    pass


def test_adapter_releases_definitions_without_a_gc_sweep():
    root = _Definition(
        id=0, name="ROOT_MODEL", instances=[],
        vertices={i: NS(id=i, x=x, y=y, z=0) for i, (x, y) in enumerate(
            [(0, 0), (10, 0), (10, 10)])},
        edges={i: NS(id=i, v1_id=i, v2_id=(i + 1) % 3) for i in range(3)},
        faces={0: NS(id=0, loops=[[(2, 1), (0, 1), (1, 1)]],
                     normal=(0, 0, 1), material_id=None)},
    )
    model = NS(definitions={0: root})
    reference = weakref.ref(root)
    enabled = gc.isenabled()
    gc.collect()
    gc.disable()
    try:
        payload = skp_openskp._adapt(model, "model")
        again = skp_openskp._adapt(model, "model")
        assert model.definitions[0] is root
        assert payload == again
        assert len(payload["groups"][0]["faces"]) == 1
        del root, model
        assert reference() is None
        # The payload owns its coordinates; releasing the source cannot
        # remove its face or alter a caller's retained payload.
        assert payload == again
        assert len(payload["groups"][0]["faces"][0][0]) == 3
    finally:
        if enabled:
            gc.enable()
        gc.collect()
