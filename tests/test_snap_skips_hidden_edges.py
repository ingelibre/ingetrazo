# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An edge the model says is not there does not snap.

Hide an edge with the eraser (or draw a smoothed surface, whose seams are
soft edges, or put a line on a layer you hide) and the draw passes stop
drawing it: no line, no profile, nothing to see. The snap engine did not
ask — it walked the loose mesh as it is — so the cursor lit up on a line
that was not on screen and a new line clicked to it ended exactly there,
cutting the face underneath at a point nobody could see. That is the seam
and the phantom corner of the report.

``Scene.edge_snappable`` is the same rule render, pick and ``bounds()``
follow; ``Viewport._snap_scene`` applies it to the loose edges on both of
its paths (the whole mesh, and the handful near the cursor on a big model).
A visible edge behaves exactly as before.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

if QApplication.instance() is None:
    QApplication([])

from core.snap import compute_snap  # noqa: E402
from views import viewport as viewport_mod  # noqa: E402
from views.viewport import Viewport  # noqa: E402


def _w2p(p):
    return (p.x() * 100.0, -p.z() * 100.0)       # side view, 100 px a metre


def _snap(vp, point):
    cand = V(point.x() + 0.03, point.y(), point.z())
    return compute_snap(cand, _w2p(cand), vp._snap_scene(), _w2p,
                        threshold_px=9.0, edge_threshold_px=14.0,
                        is_occluded=vp._is_occluded,
                        are_occluded=vp._occluded_many)


def _lands_on(r, point):
    return (r is not None and r.kind not in (None, "none")
            and (r.point - point).length() < 1e-4)


def _vp_with_two_edges():
    """A visible vertical edge at (0, 0) and its twin at (2, 2), hidden."""
    vp = Viewport(None)
    visible = vp.scene.mesh.add_edge(V(0, 0, 0), V(0, 0, 3))
    hidden = vp.scene.mesh.add_edge(V(2, 2, 0), V(2, 2, 3))
    hidden.hidden = True
    vp.scene.version += 1
    return vp, visible, hidden


def test_the_hidden_edge_is_not_in_the_snap_scene():
    vp, visible, hidden = _vp_with_two_edges()
    edges = list(vp._snap_scene().edges)
    assert hidden not in edges
    assert visible in edges


def test_a_hidden_endpoint_does_not_snap():
    vp, _visible, _hidden = _vp_with_two_edges()
    assert not _lands_on(_snap(vp, V(2, 2, 3)), V(2, 2, 3))
    assert not _lands_on(_snap(vp, V(2, 2, 0)), V(2, 2, 0))


def test_a_hidden_edge_offers_no_line_to_ride_on():
    """On-edge inference is the one that cuts a face: the point is anywhere
    along the edge. Halfway up the hidden edge, nothing is offered."""
    vp, _visible, _hidden = _vp_with_two_edges()
    r = _snap(vp, V(2, 2, 1.5))
    assert r is None or r.kind in (None, "none")


def test_the_visible_edge_still_snaps():
    vp, _visible, _hidden = _vp_with_two_edges()
    assert _lands_on(_snap(vp, V(0, 0, 3)), V(0, 0, 3))
    r = _snap(vp, V(0, 0, 1.5))
    assert r is not None and r.kind in ("on_edge", "midpoint")


def test_unhiding_brings_the_edge_back():
    """The drop set follows the scene version (every command that hides or
    moves bumps it), so the next hover after an unhide is right."""
    vp, _visible, hidden = _vp_with_two_edges()
    assert hidden not in list(vp._snap_scene().edges)
    hidden.hidden = False
    vp.scene.version += 1
    assert hidden in list(vp._snap_scene().edges)
    assert _lands_on(_snap(vp, V(2, 2, 3)), V(2, 2, 3))


def test_an_edge_on_a_hidden_layer_does_not_snap():
    """Hiding the layer takes the lines with it; they must not keep snapping
    either — the layer panel is how a whole drawing is put aside."""
    vp, visible, hidden = _vp_with_two_edges()
    hidden.hidden = False
    from core.layers import Layer, assign_layer
    vp.scene.layers.append(Layer("Anotaciones"))
    assign_layer(hidden, "Anotaciones")
    vp.scene.layer("Anotaciones").visible = False
    vp.scene.version += 1
    assert hidden not in list(vp._snap_scene().edges)
    assert visible in list(vp._snap_scene().edges)
    assert not _lands_on(_snap(vp, V(2, 2, 3)), V(2, 2, 3))


def test_hidden_geometry_on_brings_the_snaps_back():
    """Camera ▸ Hidden Geometry is what draws hidden things as ghosts and
    makes them selectable; the inference follows the same switch rather than
    inventing its own."""
    vp, _visible, _hidden = _vp_with_two_edges()
    vp.scene.show_hidden_geometry = True
    vp.scene.version += 1
    assert _lands_on(_snap(vp, V(2, 2, 3)), V(2, 2, 3))


def test_the_nearby_path_filters_hidden_edges_too(monkeypatch):
    """On a big model the snap only sees the edges near the cursor: that
    path must apply the same rule (it used to be the ONLY one that did)."""
    vp, visible, hidden = _vp_with_two_edges()
    vp._nearby_loose_edges = lambda px, py: [visible, hidden]
    vp._nearby_group_edges = lambda px, py: []
    monkeypatch.setattr(viewport_mod, "_LOOSE_SNAP_CAP", 0)
    edges = list(vp._snap_scene(10.0, 10.0).edges)
    assert hidden not in edges
    assert visible in edges


def _top_view(visible, hidden):
    """A real viewport looking straight down, so a corner is a pixel."""
    import numpy as np
    from core.camera import OrbitCamera
    vp = Viewport(None)
    vp.resize(800, 600)
    vp.camera = OrbitCamera()
    vp.camera.set_view("top")
    vp.camera.fit_to(V(-4, -4, 0), V(4, 4, 0))
    vp.scene.mesh.add_edge(*visible)
    vp.scene.mesh.add_edge(*hidden).hidden = True
    vp.scene.version += 1
    corners = visible + hidden
    px, py, ok = vp._project_px(np.array([v.toTuple() for v in corners]))
    assert all(ok)
    return vp, list(zip(px, py))


def test_a_corner_only_a_hidden_edge_holds_is_not_acquired():
    """The from-point of the next line: acquiring a corner nobody can see
    is how the phantom point gets into the drawing in the first place."""
    vp, px = _top_view((V(0, 0, 0), V(0, 2, 0)),
                       (V(2, 2, 0), V(2, 4, 0)))
    assert vp.pick_vertex(float(px[0][0]), float(px[0][1])) is not None
    assert vp.pick_vertex(float(px[2][0]), float(px[2][1])) is None
    assert vp.pick_vertex(float(px[3][0]), float(px[3][1])) is None
