# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Layers panel counts what each layer carries without building the
group meshes the loader left lazy (release_check 0.5.11: counting through
``mesh.faces`` built all 888 of plaza's, 95 MB more on every open). The
count read from a lazy mesh's source is the count of the built mesh."""
from __future__ import annotations

import random
from collections import Counter

import pytest

import core._native as _native
from core import mesh as M
from core.layers import DEFAULT_LAYER, layer_of
from core.purge import layer_carriers, layer_counts, used_layers
from core.scene import Scene
from formats import igz
from tests.test_deferred_mesh import _meshes, _random_scene


@pytest.fixture
def binary(monkeypatch):
    monkeypatch.setattr(igz, "_LARGE_DOCUMENT", 0)
    monkeypatch.setattr(igz, "_BULK_MIN", 1)
    monkeypatch.setattr(_native, "wanted", lambda: True)


def _labelled(rng) -> Scene:
    scene = _random_scene(rng)
    names = ("Muros", "Losa", "Mobiliario")
    for m in _meshes(scene):
        for f in m.faces:
            if rng.random() < 0.5:
                f.attrs["layer"] = rng.choice(names)
        for e in m.edges:
            if rng.random() < 0.4:
                e.layer = rng.choice(names)
    for g in scene.groups:
        if rng.random() < 0.5:
            g.layer = rng.choice(names)
    return scene


@pytest.mark.parametrize("seed", range(6))
def test_counting_a_lazy_document_builds_nothing_and_counts_the_same(
        binary, tmp_path, seed):
    path = tmp_path / "doc.igz"
    igz.save_scene(_labelled(random.Random(seed)), path)
    scene = Scene()
    igz.load_into(scene, path)
    lazy = [m for m in _meshes(scene) if type(m) is M.DeferredMesh]
    assert lazy, "the fixture must leave group meshes lazy"

    got = layer_counts(scene)
    used = used_layers(scene)

    assert all(type(m) is M.DeferredMesh for m in lazy)
    built = Counter(layer_of(e) for e in layer_carriers(scene))
    assert got == dict(built)
    assert used == {DEFAULT_LAYER} | set(built)


def test_an_eager_document_counts_as_before(tmp_path):
    scene = _labelled(random.Random(7))
    built = Counter(layer_of(e) for e in layer_carriers(scene))
    assert layer_counts(scene) == dict(built)
