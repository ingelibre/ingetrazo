# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Rust engine's visible faces are the Python pass's.

The SVG export of a 1 035-object plaza seen whole took 127 s finding what
each of its 90 000 faces shows, face by face in Python; a furnished villa,
13 minutes. The Rust engine does the same pass — the same rules, the same
rings, the faces in parallel — and this holds it to the Python one: the
same faces, in the same order, each with the same area."""
from __future__ import annotations

import numpy as np
import pytest

from core import _native, progress as P
from core import vista_caras as VC
from core.vista_caras import FaceFill
from tests.test_view_faces_cost import _scene, _square

native = _native.available()
pytestmark = pytest.mark.skipif(
    native is None or not hasattr(native, "visible_parts"),
    reason="Rust engine without visible_parts")

#: Areas agree to this (m²): both passes round to a grid of 1e-11 of the
#: drawing's unit, so a face's area moves by that times its perimeter — a
#: tenth of the smallest ring kept (0.01 mm²) is far above it.
AREA_TOL = 1e-9


def _faces(rng, n, **kw):
    return [FaceFill(**vars(f)) for f in _scene(rng, n, **kw)]


def _net(f):
    """The face's drawn area: its rings' signed areas added — a hole counts
    against its outer ring, and a region the booleans hand back as one
    ring touching itself where a cover grazed a hole's corner counts the
    same as the outer ring and the hole apart."""
    return sum(VC._area(r) for r in f.rings)


def _canon(out):
    return [(round(f.depth, 9), round(abs(_net(f)), 11), f.opacity < 0.999)
            for f in out]


def _both(faces):
    rust = VC._visible_parts_native([FaceFill(**vars(f)) for f in faces],
                                    native)
    py = VC._visible_parts_py([FaceFill(**vars(f)) for f in faces])
    return rust, py


def test_the_same_faces_in_the_same_order_with_the_same_area():
    rust, py = _both(_faces(np.random.default_rng(33), 400))
    assert len(py) > 50
    assert [c[0] for c in _canon(rust)] == [c[0] for c in _canon(py)]
    for a, b in zip(_canon(rust), _canon(py)):
        assert abs(a[1] - b[1]) < AREA_TOL, (a, b)
    assert [c[2] for c in _canon(rust)] == [c[2] for c in _canon(py)]


def test_faces_with_holes_and_see_through_ones():
    rng = np.random.default_rng(8)
    faces = _faces(rng, 120)
    # A slab with a hole, over the tiles: what shows through the hole stays.
    outer = _square(2, 2, 4)
    hole = _square(3, 3, 2)[::-1].copy()
    faces.append(FaceFill(rings=[outer, hole], rgb=(0.5, 0.5, 0.5),
                          layer="0", depth=-2.5,
                          extra={"near": (0.0, 0.0, 2.5)}))
    # A glass pane in front of everything hides nothing.
    faces.append(FaceFill(rings=[_square(0, 0, 10)], rgb=(0.5, 0.5, 0.5),
                          layer="0", depth=-4.0, opacity=0.5,
                          extra={"near": (0.0, 0.0, 4.0)}))
    rust, py = _both(faces)
    assert _canon(rust) and [c[0] for c in _canon(rust)] == \
        [c[0] for c in _canon(py)]
    for a, b in zip(_canon(rust), _canon(py)):
        assert abs(a[1] - b[1]) < AREA_TOL, (a, b)
    # The glass came last, whole.
    assert rust[-1].opacity == 0.5 and abs(
        sum(abs(VC._area(r)) for r in rust[-1].rings) - 100.0) < 1e-9


def test_a_cover_grazing_a_holes_corner_leaves_the_same_region():
    """A box standing on a slab, its corner on the corner of the slab's
    hole: the booleans may hand the remainder back as one ring touching
    itself there, or as a ring and a hole — the same region either way."""
    slab = FaceFill(rings=[_square(0, 0, 6), _square(2, 2, 2)[::-1].copy()],
                    rgb=(0, 0, 0), layer="0", depth=0.0,
                    extra={"near": (0.0, 0.0, 0.0)})
    box = FaceFill(rings=[_square(1, 1, 1)], rgb=(0, 0, 0), layer="0",
                   depth=-1.0, extra={"near": (0.0, 0.0, 1.0)})
    rust, py = _both([slab, box])
    assert [c[:2] for c in _canon(rust)] == [c[:2] for c in _canon(py)]
    assert abs(_net(rust[0])) == pytest.approx(36 - 4 - 1, abs=1e-9)


def test_coplanar_faces_the_earlier_wins():
    a = FaceFill(rings=[_square(0, 0, 2)], rgb=(0, 0, 0), layer="0",
                 depth=-1.0, extra={"near": (0.0, 0.0, 1.0)})
    b = FaceFill(rings=[_square(1, 1, 2)], rgb=(0, 0, 0), layer="0",
                 depth=-1.0, extra={"near": (0.0, 0.0, 1.0)})
    rust, py = _both([a, b])
    areas = [sum(abs(VC._area(r)) for r in f.rings) for f in rust]
    assert [round(v, 9) for v in areas] == [4.0, 3.0]
    assert _canon(rust) == _canon(py)


def test_the_pass_reports_how_far_it_has_come_and_stops_when_told(monkeypatch):
    monkeypatch.setattr(P, "REPORT_EVERY", 0.0)
    told = []
    faces = _faces(np.random.default_rng(5), 300)
    with P.reporting(told.append):
        VC._visible_parts_native([FaceFill(**vars(f)) for f in faces], native)
    assert len(told) >= 4 and told == sorted(told)
    assert told[0] == 0.0 and told[-1] < 1.0

    class Enough(Exception):
        pass

    def stop(done):
        if done > 0.3:
            raise Enough()

    with pytest.raises(Enough):
        with P.reporting(stop):
            VC._visible_parts_native([FaceFill(**vars(f)) for f in faces],
                                     native)


def test_view_faces_goes_through_the_engine_when_it_is_on(monkeypatch):
    called = []
    real = VC._visible_parts_native

    def spy(faces, mod):
        called.append(len(faces))
        return real(faces, mod)

    monkeypatch.setattr(VC, "_visible_parts_native", spy)
    monkeypatch.setattr(_native, "native", native)
    VC._visible_parts(_faces(np.random.default_rng(1), 20))
    assert called == [22]                  # 20 tiles, the floor, the roof
    monkeypatch.setattr(_native, "native", None)
    VC._visible_parts(_faces(np.random.default_rng(1), 20))
    assert called == [22]


def test_a_hair_is_nothing_to_the_engine():
    """A face seen all but edge on — a cylinder's wall from above, a few
    hundred points back and forth along one line, 0.3 mm² over half a
    metre — is a hair: nothing a drawing can hold. The Python pass kept
    those above its least area and drew a hairline; as covers, their
    overlapping segments took the Rust booleans seconds each (a face of
    the plaza under a few of them, twenty minutes). The engine drops a
    hair, as a face and as a cover; everything else is as Python's."""
    rng = np.random.default_rng(2)
    faces = _faces(rng, 60)
    # A hair 1 m long and 0.2 µm thick, in front of the tiles, zigzagging.
    t = np.linspace(0, 1, 200)
    hair = np.column_stack([3 + t, 5 + 1e-7 * (t * 2e6 % 2)])
    hair = np.vstack([hair, hair[::-1] + [0, 2e-7]])
    assert 0.01e-6 < abs(VC._area(hair)) < 1e-6          # above the least area
    faces.append(FaceFill(rings=[hair], rgb=(0, 0, 0), layer="0", depth=-5.0,
                          extra={"near": (0.0, 0.0, 5.0)}))
    rust = VC._visible_parts_native([FaceFill(**vars(f)) for f in faces],
                                    native)
    py = VC._visible_parts_py([FaceFill(**vars(f)) for f in faces])
    # Python kept the hair (last, nearest); the engine did not …
    assert any(f.depth == -5.0 for f in py)
    assert not any(f.depth == -5.0 for f in rust)
    # … and took nothing away for it: the rest is the same.
    rest = [c for c in _canon(py) if c[0] != -5.0]
    assert [c[0] for c in _canon(rust)] == [c[0] for c in rest]
    for a, b in zip(_canon(rust), rest):
        assert abs(a[1] - b[1]) < AREA_TOL + 1e-6, (a, b)   # less a hairline
