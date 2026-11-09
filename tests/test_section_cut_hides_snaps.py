# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What the active section cut hides does not snap — even on an edge that
crosses the cut (#384, @jonson7777).

The snap scene dropped only the edges with BOTH ends on the hidden side. A
wall's vertical, cut halfway up, crosses the plane: it stayed, and its hidden
end and its hidden stretch still drew the cursor to geometry the cut had
taken away. The cut now counts as an occluder in ``_is_occluded`` (and the
batched ``_occluded_many``), checked first and in every style, so every
candidate the snap engine weighs — endpoint, midpoint, on-edge — follows it.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.section import SectionPlane  # noqa: E402
from core.snap import compute_snap  # noqa: E402
from core.style import Style  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def _w2p(p):
    return (p.x() * 100.0, -p.z() * 100.0)       # side view, 100 px a metre


def _wall_cut_halfway(cut=True):
    """A 3 m vertical edge at (2, 2) and a cut at z = 1.5 hiding what is
    above it — the wall of the report, cut to see inside."""
    vp = Viewport(None)
    vp.scene.mesh.add_edge(V(2, 2, 0), V(2, 2, 3))
    sp = None
    if cut:
        sp = SectionPlane(V(0, 0, 1.5), V(0, 0, 1))
        vp.scene.section_planes.append(sp)
        vp.scene.set_active_section(sp)
    vp.scene.version += 1
    return vp, sp


def _snap(vp, z):
    cand = V(2.0, 2.0, z + 0.03)
    return compute_snap(cand, _w2p(cand), vp._snap_scene(), _w2p,
                        threshold_px=9.0, edge_threshold_px=14.0,
                        is_occluded=vp._is_occluded,
                        are_occluded=vp._occluded_many)


def _snapped(r):
    return r is not None and r.kind not in (None, "none")


def _lands_above_the_cut(r):
    return _snapped(r) and r.point.z() > 1.5 + 1e-6


def test_the_hidden_end_of_a_crossing_edge_does_not_snap():
    vp, _ = _wall_cut_halfway()
    assert not _lands_above_the_cut(_snap(vp, 3.0))     # the top: cut away
    assert not _lands_above_the_cut(_snap(vp, 2.5))     # its hidden stretch


def test_the_visible_part_of_the_same_edge_still_snaps():
    vp, _ = _wall_cut_halfway()
    r = _snap(vp, 0.0)
    assert r.kind == "endpoint" and abs(r.point.z()) < 1e-6
    r = _snap(vp, 1.0)
    assert r.kind in ("on_edge", "midpoint") and r.point.z() < 1.5 + 1e-6


def test_the_cut_hides_in_xray_and_wireframe_too():
    vp, _ = _wall_cut_halfway()
    for mode in ("xray", "wireframe"):
        vp.scene.display_style = Style(name=mode.title(), face_mode=mode)
        assert not _lands_above_the_cut(_snap(vp, 3.0)), mode
        assert vp._occluded_many([V(2, 2, 3), V(2, 2, 0)]) == [True, False]


def test_flipping_the_cut_brings_the_top_back():
    vp, sp = _wall_cut_halfway()
    sp.flip()
    r = _snap(vp, 3.0)
    assert r.kind == "endpoint" and abs(r.point.z() - 3.0) < 1e-6
    assert not _snapped(_snap(vp, 0.0))                # now the bottom is gone


def test_without_a_cut_nothing_changes():
    vp, _ = _wall_cut_halfway(cut=False)
    r = _snap(vp, 3.0)
    assert r.kind == "endpoint" and abs(r.point.z() - 3.0) < 1e-6
    assert vp._is_occluded(V(2, 2, 3)) is False


def test_cuts_hidden_while_section_cuts_are_switched_off():
    vp, _ = _wall_cut_halfway()
    vp.scene.show_section_cuts = False                  # cuts not shown
    r = _snap(vp, 3.0)
    assert r.kind == "endpoint" and abs(r.point.z() - 3.0) < 1e-6
