# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A face crossing (#819) counts when one side of it on screen shows one
face and the other side the other; ``Viewport._crossing_on_screen`` stops
at the first side that cannot (each side is a ray through the model, ~2
ms over the plant of #158). The crossings found must be the ones both
sides asked gave — over a sunk box, its copies and a field of copies,
pixel by pixel — with fewer rays."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from tests.test_face_crossing_snap_819 import (  # noqa: E402
    _sunk_box_window, _sunk_copies_window)


def _both_sides(self, f, g, found):
    """The rule as it was: both sides asked, then compared."""
    f_face, f_place = f[0], f[1]
    g_face, g_place = g[0], g[1]
    x, probes = found
    sides = [self._front_face_at(*q) for q in probes]
    ids = {(id(h[0]), id(h[1])) for h in sides if h is not None}
    if ids != {(id(f_face), id(f_place)), (id(g_face), id(g_place))}:
        return None
    context = None
    for place in (f_place, g_place):
        if place is None:
            continue
        owner = self._owner_of(place)
        is_comp = getattr(owner, "is_instance", None)
        context = ("component" if is_comp is not None and is_comp()
                   else "group")
        break
    return x, context


def _field_window():
    from tests.test_lazy_native_snap import _window
    return _window(lazy=True)


def _key(c):
    return None if c is None else ((c[0].x(), c[0].y(), c[0].z()), c[1])


@pytest.mark.parametrize("make", [_sunk_box_window, _sunk_copies_window,
                                  _field_window])
def test_the_crossings_are_the_ones_both_sides_gave(make, monkeypatch):
    win, vp = make()
    try:
        rays = [0]
        real = type(vp)._front_face_at
        monkeypatch.setattr(type(vp), "_front_face_at",
                            lambda self, x, y: (rays.__setitem__(
                                0, rays[0] + 1), real(self, x, y))[1])
        w, h = vp.width(), vp.height()
        found = 0
        asked = [0, 0]
        views = [None]
        if make is _field_window:
            from tests.test_lazy_native_snap import VIEWS
            views = VIEWS
        cells = [(v, float(x), float(y)) for v in views
                 for x in np.linspace(3.3, w - 3, 41)
                 for y in np.linspace(2.9, h - 3, 29)]
        for view, x, y in cells:
            if view is not None and view != getattr(vp, "_view_now", None):
                from tests.test_lazy_native_snap import _set_view
                _set_view(vp, view)
                vp._view_now = view
            if True:
                x, y = float(x), float(y)
                rays[0] = 0
                got = vp._face_crossing_point(x, y)
                asked[0] += rays[0]
                rays[0] = 0
                with monkeypatch.context() as m:
                    m.setattr(type(vp), "_crossing_on_screen", _both_sides)
                    want = vp._face_crossing_point(x, y)
                asked[1] += rays[0]
                assert _key(got) == _key(want), (x, y)
                found += want is not None
        assert found > (0 if make is _field_window else 3)
        assert asked[0] < asked[1]
    finally:
        win._saved_version = vp.scene.version
        win.close()
