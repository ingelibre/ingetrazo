# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Temporary adapter geometry must not accumulate across the whole model."""
from types import SimpleNamespace as NS

import numpy as np
import pytest

from formats import skp_openskp as adapter


def test_cache_eviction_keeps_active_geometry_and_source():
    first = NS(faces={1: "source face"})
    second = NS(faces={2: "another source face"})
    cache = adapter._GeometryCache(16)
    token = adapter._geometry_cache.set(cache)
    try:
        a = np.arange(2, dtype=np.float64)
        b = np.arange(3, dtype=np.float64)
        adapter._remember_geometry(first, "_geom", a, a.nbytes)
        assert first._geom is a
        adapter._remember_geometry(second, "_geom", b, b.nbytes)
        assert not hasattr(first, "_geom")
        assert not hasattr(second, "_geom")  # Oversize entries stay uncached.
        np.testing.assert_array_equal(a, [0, 1])
        np.testing.assert_array_equal(b, [0, 1, 2])
        assert first.faces == {1: "source face"}
        assert second.faces == {2: "another source face"}
        assert cache.size == 0
    finally:
        cache.clear()
        adapter._geometry_cache.reset(token)


def test_adaptation_cleans_cache_on_failure_and_restores_outer_context(monkeypatch):
    source = NS(faces={1: "source face"})
    outer = adapter._GeometryCache(100)
    token = adapter._geometry_cache.set(outer)
    def fail(*args):
        adapter._remember_geometry(source, "_geom", [1, 2], 16)
        raise RuntimeError("injected adaptation failure")
    monkeypatch.setattr(adapter, "_adapt_inner", fail)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            adapter._adapt(NS(), "test")
        assert adapter._geometry_cache.get() is outer
        assert not hasattr(source, "_geom")
        assert source.faces == {1: "source face"}
    finally:
        adapter._geometry_cache.reset(token)


def test_cleanup_does_not_remove_replaced_cache_value():
    source = NS()
    cache = adapter._GeometryCache(100)
    original = [1]
    source._geom = original
    cache.remember(source, "_geom", original, 8)
    replacement = [2]
    source._geom = replacement
    cache.clear()
    assert source._geom is replacement
