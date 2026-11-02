# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Issue #952: the instanced frustum test multiplied infinite box bounds
by zero plane components, which warned (``invalid value encountered in
multiply``) on huge models and quietly dropped the box — a placement
whose extent is unknown (±inf by convention, or a NaN that crept into a
huge model's coordinates) cannot be proven outside the frustum, so it
must be kept, explicitly, like ``_bounding_spheres`` and
``_visible_spans`` already keep unknown extents."""
from __future__ import annotations

import warnings

import numpy as np

from views.viewport import Viewport

# Keep the half-spaces x <= 10 and y >= -5.
_PLANES = [(-1.0, 0.0, 0.0, 10.0), (0.0, 1.0, 0.0, 5.0)]


def _boxes():
    inf = np.inf
    lo = np.array([
        [0.0, 0.0, 0.0],        # inside both half-spaces
        [20.0, 0.0, 0.0],       # wholly past x = 10
        [-inf, -inf, -inf],     # unknown extent (a boxless placement)
        [np.nan, 0.0, 0.0],     # a NaN crept into the bounds
    ])
    hi = np.array([
        [5.0, 5.0, 5.0],
        [30.0, 5.0, 5.0],
        [inf, inf, inf],
        [5.0, 5.0, 5.0],
    ])
    return lo, hi


def test_nonfinite_boxes_are_kept_without_a_warning():
    lo, hi = _boxes()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        keep = Viewport._instances_in_frustum(lo, hi, _PLANES)
    assert keep.tolist() == [True, False, True, True]


def test_finite_boxes_match_the_plain_p_vertex_test():
    lo, hi = _boxes()
    finite = np.array([True, True, False, False])
    keep = Viewport._instances_in_frustum(lo, hi, _PLANES)
    plain = Viewport._instances_in_frustum(lo[finite], hi[finite], _PLANES)
    assert keep[finite].tolist() == plain.tolist()


def test_no_boxes_and_all_nonfinite_boxes():
    empty = np.zeros((0, 3))
    assert Viewport._instances_in_frustum(empty, empty, _PLANES).tolist() == []
    lo = np.array([[-np.inf, -np.inf, -np.inf]])
    hi = np.array([[np.inf, np.inf, np.inf]])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert Viewport._instances_in_frustum(
            lo, hi, _PLANES).tolist() == [True]
