# SPDX-License-Identifier: GPL-3.0-or-later
"""Image broad-phase rejection must preserve the exact attachment decision."""
from types import SimpleNamespace as NS

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

from formats import skp_openskp as adapter


def panel(ident=1, offset=0.):
    points = [(offset-10, -10, 0), (offset+10, -10, 0),
              (offset+10, 10, 0), (offset-10, 10, 0)]
    return NS(id=ident, vertices={i: NS(x=x,y=y,z=z) for i,(x,y,z) in enumerate(points)},
              edges={i: NS(v1_id=i,v2_id=(i+1)%4) for i in range(4)},
              faces={0: NS(loops=[[(i,1) for i in range(4)]])}, instances=[])


def quad(x=0., z=0.):
    return [QVector3D(x+u, v, z) for u,v in [(-.05,-.05),(.05,-.05),(.05,.05),(-.05,.05)]]


def without_broadphase(monkeypatch, roots, by_id, points):
    with monkeypatch.context() as patch:
        patch.setattr(adapter, '_image_geometry_bounds', lambda d: None)
        return adapter._rests_on_a_face(roots, by_id, points)


def test_distant_geometry_does_not_resolve_rings(monkeypatch):
    d=panel()
    def unexpected(*args):
        pytest.fail('distant definition resolved its face rings')
    monkeypatch.setattr(adapter, '_face_boxes', unexpected)
    assert not adapter._rests_on_a_face([d], {1:d}, quad(100.))


@pytest.mark.parametrize('scale', [.001, .2, 1., 3., -2.])
@pytest.mark.parametrize('height', [0., .009, .010001, .5])
def test_scaled_and_mirrored_attachment_matches_exact_path(monkeypatch, scale, height):
    d=panel()
    # Nonuniform scale + shear; translation is in inches on the source matrix.
    matrix=[scale, .1*scale, 0, 0, scale*.8, 0, 0, 0, scale*1.3, 20, 30, 0, 1]
    root=NS(vertices={}, edges={}, faces={}, instances=[NS(ref_idx=1,matrix=matrix)])
    q=quad(20*adapter._INCH,height)
    q=[QVector3D(p.x(),p.y()+30*adapter._INCH,p.z()) for p in q]
    actual=adapter._rests_on_a_face([root],{1:d},q)
    assert actual == without_broadphase(monkeypatch,[root],{1:d},q)


def test_rejected_parent_still_visits_nearby_child():
    parent,child=panel(1,10000.),panel(2)
    parent.instances=[NS(ref_idx=2,matrix=[1,0,0,0,1,0,0,0,1,0,0,0,1])]
    assert adapter._rests_on_a_face([parent],{1:parent,2:child},quad())


@pytest.mark.parametrize('coordinate', [float('nan'),float('inf'),'invalid'])
def test_invalid_unused_vertex_falls_back(monkeypatch,coordinate):
    d=panel();d.vertices[99]=NS(x=coordinate,y=0,z=0)
    assert adapter._image_geometry_bounds(d) is None
    assert adapter._rests_on_a_face([d],{1:d},quad())
    assert without_broadphase(monkeypatch,[d],{1:d},quad())


def test_singular_empty_resolved_geometry_keeps_old_behavior(monkeypatch):
    d=panel();d.faces[0].loops=[]
    root=NS(vertices={},edges={},faces={},instances=[NS(ref_idx=1,matrix=[0]*12+[1])])
    assert not adapter._rests_on_a_face([root],{1:d},quad())
    assert not without_broadphase(monkeypatch,[root],{1:d},quad())


def test_bounds_cache_is_local_to_query():
    d=panel()
    assert adapter._rests_on_a_face([d],{1:d},quad())
    # A fresh later query cannot reuse a stale broad-phase box.
    for v in d.vertices.values(): v.x += 10000.
    for attr in ('_geom','_face_boxes'):
        if hasattr(d,attr): delattr(d,attr)
    assert adapter._rests_on_a_face([d],{1:d},quad(254.))
