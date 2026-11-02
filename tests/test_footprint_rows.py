# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The snap's footprint over the lazy placements (#158) cuts the boxes
near the cursor by how far they lie from the eye and by their size on
screen, both kept for the view (``Viewport._footprint_rows``). The rows
must be the ones cut afresh from the boxes near the cursor, row for row
— for any pixel, margin, depth limit and pixel floor — and a view, an
eye or a placement that changes must not reuse the old cuts."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4

from tests.test_lazy_native_snap import (  # noqa: F401
    VIEWS, _close, _set_view, _window)


@pytest.fixture
def win():
    w, vp = _window(lazy=True)
    try:
        yield vp
    finally:
        _close(w)


def _fresh(vp, table, x, y, r, far):
    """_footprint_need's cuts as they were: on the near rows alone."""
    lo, hi = table[1], table[2]
    r = max(r, vp._PICK_NEAR_PX)
    need = vp._placements_under_px(lo, hi, x, y, r)
    if far is not None and len(need):
        e = vp.camera.eye()
        e = np.array([e.x(), e.y(), e.z()])
        near_pt = np.clip(e, lo[need], hi[need])
        dist = np.linalg.norm(near_pt - e, axis=1)
        need = need[dist <= far]
    if len(need) and vp._PICK_MIN_PX > 0.0:
        ctr, rad = vp._bounding_spheres(lo[need], hi[need])
        need = need[~vp._spheres_below_a_pixel(ctr, rad, vp._PICK_MIN_PX)]
    return need


def _cut(vp, table, x, y, r, far, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(type(vp), "_visible_depth_limit", lambda self, a, b: far)
        m.setattr(type(vp), "_pick_instance_set", lambda self, t: None)
        vp._pick_near_memo = vp._edge_near_memo = None
        return vp._footprint_need(table, x, y, r)


def test_the_kept_cuts_are_the_ones_made_afresh(win, monkeypatch):
    vp = win
    rng = np.random.default_rng(31)
    cut_far = cut_small = 0
    for floor in (0.0, 1.0, 40.0, 120.0):
        monkeypatch.setattr(type(vp), "_PICK_MIN_PX", floor)
        for view in VIEWS:
            _set_view(vp, view)
            table = vp._pick_lazy_table()
            assert table is not None
            e = vp.camera.eye()
            for _ in range(25):
                x, y = rng.uniform(0, 900), rng.uniform(0, 640)
                r = float(rng.choice([8.0, 48.0]))
                far = rng.choice([None, float(rng.uniform(0.3, 1.2))
                                  * e.length()])
                want = _fresh(vp, table, x, y, r, far)
                got = _cut(vp, table, x, y, r, far, monkeypatch)
                assert np.array_equal(np.asarray(got), want), (view, x, y)
                base = _fresh(vp, table, x, y, r, None)
                near = len(vp._placements_under_px(
                    table[1], table[2], x, y, max(r, vp._PICK_NEAR_PX)))
                cut_far += far is not None and len(want) < len(base)
                cut_small += floor > 1.0 and len(base) < near
    assert cut_far > 10 and cut_small > 10      # both cuts really cut


def test_what_changes_the_cuts_makes_them_again(win, monkeypatch):
    vp = win
    monkeypatch.setattr(type(vp), "_PICK_MIN_PX", 40.0)
    _set_view(vp, VIEWS[0])
    x, y = 450.0, 320.0

    def check():
        table = vp._pick_lazy_table()
        far = 0.9 * vp.camera.eye().length()
        assert np.array_equal(
            np.asarray(_cut(vp, table, x, y, 48.0, far, monkeypatch)),
            _fresh(vp, table, x, y, 48.0, far))
        return vp._footprint_rows(table)

    first = check()
    copies = [g for g in vp.scene.groups if g.name.startswith("C")]

    def move():
        for g in copies[::2]:
            m = QMatrix4x4(g.xform)
            m.translate(0.0, 0.0, 6.0)
            g.xform = m
        vp.scene.version += 1

    def nearer():
        vp.camera.distance *= 0.4
        vp._tick += 1

    def other_view():
        _set_view(vp, VIEWS[2])

    def floor():
        monkeypatch.setattr(type(vp), "_PICK_MIN_PX", 90.0)

    for change in (move, nearer, other_view, floor):
        change()
        now = check()
        assert not (np.array_equal(now[0], first[0])
                    and np.array_equal(now[1], first[1])), change.__name__
        first = now
