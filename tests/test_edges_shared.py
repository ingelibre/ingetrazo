# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""In one input event the cursor's own group edge (``pick_edge_any``) and
the snap's (``_nearby_group_edges``) are read off one search of the lazy
placements' edges (#158, ``Viewport._nearby_edges_unbaked``): what each
gets must be what its own search gives — the same edges at the same
distances, in the same order, for any radius and cap up to the snap's —
in either order, fresh objects for each, and an event, a pixel or a
model that changes searches again. Skipped without the engine."""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QMatrix4x4

import views.viewport as viewport_mod
from tests.test_lazy_native_snap import (  # noqa: F401
    VIEWS, _close, _edge_key, _set_view, _window, pytestmark)

pytestmark = pytestmark


@pytest.fixture
def win():
    w, vp = _window(lazy=True)
    try:
        yield vp
    finally:
        _close(w)


def _fresh(vp, x, y, r, cap, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(viewport_mod, "_EDGES_SHARED", False)
        return vp._nearby_edges_unbaked(x, y, r, cap, vp._lazy_native(),
                                        with_d=True)


def _keys(out):
    return [(d, _edge_key(e)) for d, e in out]


def test_each_gets_what_its_own_search_gives(win, monkeypatch):
    vp = win
    searches = []
    real = type(vp)._nearby_edges_found
    monkeypatch.setattr(type(vp), "_nearby_edges_found",
                        lambda self, *a: (searches.append(a[2:4]),
                                          real(self, *a))[1])
    rng = np.random.default_rng(23)
    seen = cut = 0
    serial = 0
    for view in VIEWS:
        _set_view(vp, view)
        for _ in range(60):
            x = float(rng.uniform(0, 900))
            y = float(rng.uniform(0, 640))
            asks = [(float(rng.choice([2.0, 8.0, 20.0, 48.0])),
                     int(rng.choice([1, 3, 48])))
                    for _ in range(3)]
            want = [_keys(_fresh(vp, x, y, r, c, monkeypatch))
                    for r, c in asks]
            serial += 1
            vp._input_serial = serial
            searches.clear()
            got = []
            for r, c in asks:
                out = vp._nearby_edges_unbaked(x, y, r, c, vp._lazy_native(),
                                               with_d=True)
                got.append(out)
                bare = vp._nearby_edges_unbaked(x, y, r, c,
                                                vp._lazy_native())
                assert list(map(_edge_key, bare)) == [
                    _edge_key(e) for _d, e in out]
            assert [_keys(o) for o in got] == want, (view, x, y, asks)
            assert len(searches) == 1                # one search of all
            ids = [id(e) for o in got for _d, e in o]
            assert len(ids) == len(set(ids))         # none shared
            seen += sum(len(w) for w in want)
            cut += any(len(w) == c for w, (_r, c) in zip(want, asks))
    assert seen > 100 and cut > 20


def test_what_changes_searches_again(win, monkeypatch):
    vp = win
    searches = []
    real = type(vp)._nearby_edges_found
    monkeypatch.setattr(type(vp), "_nearby_edges_found",
                        lambda self, *a: (searches.append(1),
                                          real(self, *a))[1])
    _set_view(vp, VIEWS[0])
    x, y = 450.0, 320.0
    vp._input_serial = 1
    vp._nearby_edges_unbaked(x, y, 8.0, 1, vp._lazy_native())
    copies = [g for g in vp.scene.groups if g.name.startswith("C")]

    def move():
        for g in copies[::2]:
            m = QMatrix4x4(g.xform)
            m.translate(0.4, 0.0, 0.0)
            g.xform = m
        vp.scene.version += 1

    def turn():
        _set_view(vp, VIEWS[1])

    steps = [("event", lambda: setattr(vp, "_input_serial", 2)),
             ("pixel", None), ("move", move), ("turn", turn)]
    for name, change in steps:
        if change is not None:
            change()
        else:
            x += 3.0
        n = len(searches)
        got = vp._nearby_edges_unbaked(x, y, 48.0, 48, vp._lazy_native(),
                                       with_d=True)
        assert len(searches) == n + 1, name
        assert _keys(got) == _keys(_fresh(vp, x, y, 48.0, 48, monkeypatch))
