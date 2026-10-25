# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Packed import coordinates preserve list values without per-corner objects."""
import pickle
import tracemalloc

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4

from formats import skp_openskp as adapter


def _original_points(points, transform):
    if transform.isIdentity():
        world = points
    else:
        matrix = np.array(transform.data(), dtype=np.float64).reshape(4, 4, order="F")
        world = points @ matrix[:3, :3].T + matrix[:3, 3]
    return world.astype(np.float32).astype(np.float64).tolist()


@pytest.mark.parametrize("transformed", [False, True])
def test_packed_rows_keep_exact_values_slices_repr_and_pickle(transformed):
    points = np.array([[0., -0., 1.e-42], [1.00000001, -2.3, 4.7],
                       [100000001., -1.e-42, .00011]], dtype=np.float64)
    transform = QMatrix4x4()
    if transformed:
        transform.translate(1.25, -2., 3.)
        transform.rotate(31., 0., 0., 1.)
        transform.scale(1.7, .3, -2.)
    expected = _original_points(points, transform)
    rows = adapter._world_points(points, transform)
    for actual in (rows, pickle.loads(pickle.dumps(rows))):
        np.testing.assert_array_equal(np.array(actual).view(np.uint64),
                                      np.array(expected).view(np.uint64))
        assert repr(actual) == repr(expected)
        assert actual == expected
        assert expected == actual
        assert actual[-1] == expected[-1]
        for section in (slice(None), slice(None, None, -1), slice(1, 1), slice(1, 3)):
            assert actual[section] == expected[section]
            assert repr(actual[section]) == repr(expected[section])
        assert not actual[1:1]
        with pytest.raises(IndexError):
            actual[len(actual)]


def test_retained_coordinate_storage_is_bounded():
    points = np.arange(150_000, dtype=np.float64).reshape(-1, 3)
    tracemalloc.start()
    try:
        rows = adapter._world_points(points, QMatrix4x4())
        retained, _peak = tracemalloc.get_traced_memory()
        # Former list-of-lists uses over 150 bytes per coordinate row.
        # Allow over twice the packed 12-byte row cost, including bookkeeping.
        assert retained < 32 * len(points)
        assert len(rows) == len(points)
    finally:
        tracemalloc.stop()


def test_prototype_comparison_keeps_all_coordinates():
    a = np.arange(6000, dtype=np.float64).reshape(-1, 3)
    b = a.copy()
    b[1000, 1] += .25  # Hidden by NumPy's abbreviated array repr.
    def proto(points):
        return dict(name="mesh", faces=[(points, [], None)], soft_edges=[],
                    children=[], instances=[])
    pa = adapter._world_points(a, QMatrix4x4())
    pb = adapter._world_points(b, QMatrix4x4())
    protos = [proto(pa), proto(pb), proto(_original_points(a, QMatrix4x4()))]
    merged = adapter._merge_equal_protos(protos)
    assert len(merged) == 2
    assert merged[0]["faces"][0][0] == pa
    assert merged[1]["faces"][0][0] == pb
