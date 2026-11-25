# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Batch placement boxes match Qt after their local corners round to float32."""
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D

from core import _native


@pytest.fixture
def kernel():
    native = getattr(_native.native, "qt_world_boxes", None)
    if native is None:
        pytest.skip("native world-box kernel was not built")
    return native


def test_world_boxes_match_qt_with_strided_affine_inputs(kernel):
    identity = QMatrix4x4()
    mirrored = QMatrix4x4()
    mirrored.translate(10., -12., 18.)
    mirrored.scale(-1.25, .5, 2.)
    rotated = QMatrix4x4()
    rotated.rotate(90., 0., 0., 1.)
    general = QMatrix4x4(*rotated.copyDataTo())
    singular = QMatrix4x4(mirrored)
    singular.scale(0., 1., 1.)
    matrices = [identity, mirrored, rotated, general, singular]
    local = np.tile(np.array([1., 2., 3., 4., 5., 6.], np.float32), (len(matrices), 1))
    mats = np.asarray([m.data() for m in matrices], dtype=np.float32)
    expected = []
    for m in matrices:
        corners = (m.map(QVector3D(x, y, z)).toTuple()
                   for x in (1., 4.) for y in (2., 5.) for z in (3., 6.))
        axes = tuple(zip(*corners))
        expected.append((*map(min, axes), *map(max, axes)))
    expected = np.asarray(expected, dtype=np.float32)

    for boxes, rows, want in ((local, mats, expected),
                              (np.asfortranarray(local), np.asfortranarray(mats), expected),
                              (local[::-2], mats[::-2], expected[::-2])):
        actual, supported = kernel(boxes, rows)
        assert actual.dtype == np.float32 and supported.dtype == np.bool_
        assert supported.tolist() == [True] * len(rows)
        assert actual.tobytes() == want.tobytes()


def test_world_boxes_refuse_ambiguous_rows(kernel):
    local = np.tile(np.array([1., 2., 3., 4., 5., 6.], np.float32), (8, 1))
    mats = np.tile(np.eye(4, dtype=np.float32).ravel(), (8, 1))
    local[0, (0, 3)] = (-0., 0.)
    local[1, 0] = np.nan
    local[2, 5] = np.inf
    mats[3, 3] = .25
    local[4, 0] = 5.
    local[5, (0, 3)] = np.finfo(np.float32).max
    mats[5, 0] = 2.
    mats[6, 5] = -np.inf
    out, supported = kernel(local, mats)
    assert supported.tolist() == [False] * 7 + [True]
    assert out[7].tobytes() == local[7].tobytes()


def test_world_box_shapes(kernel):
    empty, supported = kernel(np.empty((0, 6), np.float32), np.empty((0, 16), np.float32))
    assert empty.shape == (0, 6) and supported.shape == (0,)
    for local_shape, mat_shape in (((0, 5), (0, 16)), ((2, 6), (1, 16)), ((1, 6), (1, 15))):
        with pytest.raises(ValueError, match="shape"):
            kernel(np.empty(local_shape, np.float32), np.empty(mat_shape, np.float32))


def test_world_box_probe_disables_a_mismatched_or_missing_kernel(monkeypatch):
    calls = []

    def mismatched(local, mats):
        calls.append(len(local))
        supported = (local[:, 0] != 0.) & (mats[:, 15] == 1.)
        return np.zeros_like(local), supported

    monkeypatch.setattr(_native, "_world_boxes", None)
    monkeypatch.setattr(_native, "native", SimpleNamespace(qt_world_boxes=mismatched))
    assert _native.qt_world_boxes() is None
    assert _native.qt_world_boxes() is None and len(calls) == 1
    monkeypatch.setattr(_native, "native", SimpleNamespace())
    assert _native.qt_world_boxes() is None
