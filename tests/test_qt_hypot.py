# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Probe regressions must fail, rather than skip, on supported native builds."""
import platform
import sys

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

from core import _native
from core.mesh import DeferredMesh, Mesh
from views import array_bake


def _deferred():
    mesh = Mesh()
    assert DeferredMesh.defer(mesh, lambda mesh: None, 0)
    return mesh


@pytest.mark.skipif(sys.platform != "darwin" or platform.machine() != "arm64",
                    reason="Apple arm64 Qt arithmetic regression")
def test_apple_qt_probe_enables_array_bake(monkeypatch):
    mod = _native.available()
    if mod is None:
        pytest.skip("native module not built")
    monkeypatch.setattr(_native, "native", mod)
    monkeypatch.setattr(_native, "_hypot", _native._UNSET)
    assert _native.qt_hypot() == "libc++"
    assert array_bake.can_bake(_deferred())
    # Outside the startup sample's range: the wheel uses the older unscaled
    # libc++ implementation, not the current SDK's power-of-two scaling.
    rows = np.array([[1e30, -2e30, 3e30], [1e-30, -2e-30, 3e-30],
                     [0, -0.0, 0], [1, 2, 3]], dtype=np.float32)
    lengths, normals, _, _ = mod.qt_vector_probe(rows, "libc++")
    vectors = [QVector3D(*row) for row in rows.tolist()]
    assert lengths.tolist() == [v.length() for v in vectors]
    assert normals.tolist() == [list(v.normalized().toTuple()) for v in vectors]


def test_array_bake_requires_native_module(monkeypatch):
    monkeypatch.setattr(_native, "native", None)
    assert not array_bake.can_bake(_deferred())


def test_array_bake_requires_matching_probe(monkeypatch):
    monkeypatch.setattr(_native, "native", object())
    monkeypatch.setattr(_native, "_hypot", None)
    assert not array_bake.can_bake(_deferred())


def test_native_dot_rows_matches_qt(monkeypatch):
    mod = _native.available()
    if mod is None:
        pytest.skip("native module not built")
    formula = _native.qt_hypot()
    if formula is None:
        pytest.skip("this Qt arithmetic is not supported")
    monkeypatch.setattr(_native, "native", mod)
    rng = np.random.default_rng(400)
    a = rng.normal(size=(2000, 3)).astype(np.float32)
    b = rng.normal(size=(2000, 3)).astype(np.float32)
    expected = [QVector3D.dotProduct(QVector3D(*x), QVector3D(*y))
                for x, y in zip(a.tolist(), b.tolist())]
    assert mod.qt_dot_rows(a, b, formula).tolist() == expected
    assert array_bake._dot_rows(a, b).tolist() == expected
    broadcast = array_bake._dot_rows(a.reshape(20, 100, 3), b[0])
    assert broadcast.shape == (20, 100)
    assert broadcast.ravel().tolist() == [
        QVector3D.dotProduct(QVector3D(*x), QVector3D(*b[0].tolist()))
        for x in a.tolist()]
    with pytest.raises(ValueError, match="matching"):
        mod.qt_dot_rows(a, b[:1], formula)
