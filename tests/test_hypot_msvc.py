# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""QVector3D's length on Windows is MSVC's three-argument ``std::hypot``,
which rounds the last bit differently from libstdc++'s in about one vector
in forty. Both copies of it — ``views.viewport._hypot3_f32(a, "msvc")``
for the rays and the native ``Hypot::Msvc`` for the face kernels — give
the bits MSVC's STL gives (``_Hypot3`` of ``special_math.cpp``, compiled
from its source on 26-10 over 3.3 M vectors: these are some where the two
libraries differ), and the Linux formula is still libstdc++'s."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from core import _native  # noqa: E402
from views import viewport as V  # noqa: E402

H = float.fromhex

#: (vector, MSVC's length, libstdc++'s length), lengths as float32 bits.
CASES = [
    ((H("0x1.0p-1"), H("-0x1.0p+0"), H("-0x1.4p+1")), 0x402f456e, 0x402f456f),
    ((H("-0x1.9983ecp-13"), H("-0x1.4e67b4p-12"), H("-0x1.208a28p-11")), 0x3a2e6c3e, 0x3a2e6c3d),
    ((H("0x1.4ac806p-2"), H("0x1.4ac806p-2"), H("0x1.011732p+0")), 0x3f8d3862, 0x3f8d3861),
    ((H("0x1.c78c78p-3"), H("-0x1.469bf4p-1"), H("-0x1.6d851ep+0")), 0x3fca2f79, 0x3fca2f7b),
    ((H("0x1.68c0f4p-8"), H("-0x1.03979ep-13"), H("-0x1.5ec1ecp-6")), 0x3cb51613, 0x3cb51614),
    ((H("0x1.353e78p-4"), H("0x1.c961e2p-1"), H("-0x1.ccaa2p-1")), 0x3fa293ec, 0x3fa293eb),
    ((H("-0x1.143c4ap+0"), H("0x1.e03cdcp+0"), H("0x1.4b714ap+1")), 0x4057faa1, 0x4057faa0),
    ((H("-0x1.4a5b36p-1"), H("0x1.29a86ep-1"), H("-0x1.8e0d8cp-1")), 0x3f9533d0, 0x3f9533cf),
    ((H("0x1.45c408p-2"), H("0x1.e4045p-4"), H("-0x1.2f509p-1")), 0x3f2ec77c, 0x3f2ec77e),
    ((H("0x1.be122p-2"), H("0x1.05b9d2p+0"), H("0x1.7cf13cp+0")), 0x3fedb9ba, 0x3fedb9bc),
    # Here the two libraries agree, but MSVC's order of the two smaller
    # ratios matters: 1 + (second)² + (third)², as its swaps leave them.
    ((H("-0x1.32751ep-22"), H("0x1.35bcd6p-19"), H("-0x1.b19f24p-20")), 0x363e01fc, 0x363e01fc),
    ((H("-0x1.21c29p-11"), H("0x1.11f2eep-13"), H("-0x1.4b4e04p-11")), 0x3a5eb7f4, 0x3a5eb7f4),
    ((H("0x1.22807ap+0"), H("0x1.78834ep+1"), H("0x1.6350d0p+0")), 0x405c7775, 0x405c7775),
    # MSVC keeps the largest when the others are below its epsilon, and
    # zero stays zero.
    ((1.0, 1e-8, 1e-8), 0x3f800000, 0x3f800000),
    ((0.0, 0.0, 0.0), 0x00000000, 0x00000000),
]


def _rows():
    a = np.array([c[0] for c in CASES], dtype=np.float32)
    msvc = np.array([c[1] for c in CASES], dtype=np.uint32)
    lib = np.array([c[2] for c in CASES], dtype=np.uint32)
    return a, msvc, lib


@pytest.mark.parametrize("kind,col", [("msvc", 1), ("libstdc++", 2)])
def test_numpy_formula_bits(kind, col):
    a, *want = _rows()
    got = V._hypot3_f32(a, kind).view(np.uint32)
    assert got.tolist() == want[col - 1].tolist()


@pytest.mark.skipif(_native.available() is None
                    or not hasattr(_native.available(), "qt_vector_probe"),
                    reason="native module not built")
@pytest.mark.parametrize("kind,col", [("msvc", 1), ("libstdc++", 2)])
def test_native_formula_bits(kind, col):
    a, *want = _rows()
    ln = _native.available().qt_vector_probe(a, kind)[0]
    got = np.asarray(ln, dtype=np.float32).view(np.uint32)
    assert got.tolist() == want[col - 1].tolist()


def test_this_qt_is_known():
    """On Linux (libstdc++) and Windows (MSVC) Qt's length is one of the
    formulas, so the vectorised rays are not lost to the slow path."""
    import sys
    want = {"linux": "libstdc++", "win32": "msvc"}.get(sys.platform)
    if want is None:
        pytest.skip("no formula for this platform's C++ library yet")
    assert V._qv_hypot3() == want
    if _native.available() is not None:
        assert _native.qt_hypot() == want
