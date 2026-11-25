# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Sheets: a copied frame shows ITS scene's layers, on screen and on export.

GitHub #1450 — in Sheets, copying a view portal and changing the copy's
assigned scene left it showing the ORIGINAL portal's layer visibility; the
picture looked right at first and reverted on PDF export. Two caches were
to blame, both keyed without the visibility: the composer's shared
geometry (``_scene_geometry``) was built once under the live layers and
served again after the live layers moved, and the pick index behind it
omits hidden layers outright. The shared geometry is now keyed on the
visibility and re-collected from the layers as they are switched when it
moved; a frame's scene also no longer leaks its hidden objects into the
live model.
"""
import copy
import uuid

import numpy as np
import pytest
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QWidget

from core.group import Group
from core.layers import Layer
from core.mesh import Mesh
from core.scene import Scene
from core.saved_views import SavedView, visibility_sig
from views.composer import ComposerWindow
from views.viewport import Viewport


def _box(m, x0, y0, z0, x1, y1, z1):
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0)])
    m.add_face([V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x1, y0, z0), V(x1, y0, z1), V(x0, y0, z1)])
    m.add_face([V(x0, y1, z0), V(x1, y1, z0), V(x1, y1, z1), V(x0, y1, z1)])
    m.add_face([V(x0, y0, z0), V(x0, y1, z0), V(x0, y1, z1), V(x0, y0, z1)])
    m.add_face([V(x1, y0, z0), V(x1, y1, z0), V(x1, y1, z1), V(x1, y0, z1)])


def _build_scene(only=None, hide_b_in_s2=True):
    """Two layers, one box on each (different world-x); S1 hides B, S2
    hides A. ``only`` builds a single-box control scene."""
    scene = Scene()
    scene.layers += [Layer("A", color=(1.0, 0.0, 0.0)),
                     Layer("B", color=(0.0, 0.0, 1.0))]
    if only != "B":
        ga = Group(Mesh(), name="BoxA")
        ga.layer = "A"
        _box(ga.mesh, 0, 0, 0, 2, 2, 2)
        scene.groups.append(ga)
    if only != "A":
        gb = Group(Mesh(), name="BoxB")
        gb.layer = "B"
        _box(gb.mesh, 10, 0, 0, 12, 2, 2)
        scene.groups.append(gb)
    kw = dict(target=(6.0, 1.0, 1.0), distance=20.0,
              yaw=-0.7853981633974483, pitch=0.5235987755982988,
              perspective=False)
    s1 = SavedView("S1", hidden_layers=["B"], **kw)
    s2 = SavedView("S2", hidden_layers=["A"] if hide_b_in_s2 else [],
                   **kw)
    scene.saved_views = [s1, s2]
    return scene, s1, s2


def _make_composer(scene):
    vp = Viewport(None)
    vp.scene = scene
    from core.camera import OrbitCamera
    vp.camera = OrbitCamera()
    host = QWidget()
    host.viewport = vp
    composer = ComposerWindow(host)
    return composer, host


def _prep_frame(frame, view_key):
    frame.view_key = view_key
    frame.style = "vectorial"
    frame.scale_n = 100.0
    frame.w_mm, frame.h_mm = 200.0, 100.0


def _segs(composer, frame):
    composer.compute_hlr(frame)
    out = composer.hlr_cache.get(id(frame))
    return None if out is None else np.asarray(out, dtype=float)


def _same(a, b):
    if a is None or b is None:
        return a is b
    if a.shape != b.shape:
        return False
    return bool(np.allclose(np.sort(a.ravel()), np.sort(b.ravel())))


def _control_segs(only, view_key):
    scene, s1, s2 = _build_scene(only=only)
    (s1 if view_key == "scene:S1" else s2).apply_state(scene)
    composer, host = _make_composer(scene)
    frame = composer.comp.frames[0]
    _prep_frame(frame, view_key)
    return _segs(composer, frame)


def test_copied_frame_keeps_its_scene_layers_on_export():
    segs_a = _control_segs("A", "scene:S1")
    segs_b = _control_segs("B", "scene:S2")
    assert not _same(segs_a, segs_b)

    scene, s1, s2 = _build_scene()
    s1.apply_state(scene)  # live = S1: A on, B off
    composer, host = _make_composer(scene)
    f1 = composer.comp.frames[0]
    _prep_frame(f1, "scene:S1")
    assert _same(_segs(composer, f1), segs_a)

    # Copy/paste the portal, then change the copy's assigned scene.
    f2 = copy.deepcopy(f1)
    f2.uid = uuid.uuid4().hex
    f2.view_key = "scene:S2"
    composer.comp.frames.append(f2)
    composer._forget_frame(f2)
    assert _same(_segs(composer, f2), segs_b)  # right after the change

    # Export re-renders every frame, original first, live still S1.
    composer.render_frame(f1)
    composer.render_frame(f2)
    got = np.asarray(composer.hlr_cache.get(id(f2)), dtype=float)
    assert _same(got, segs_b)

    # The live model is recalled to the copy's scene — without a version
    # bump reaching the composer yet (the signal is queued after paint) —
    # and the export re-renders again: the copy must still show ITS scene.
    s2.apply_state(scene)
    composer.render_frame(f1)
    composer.render_frame(f2)
    got = np.asarray(composer.hlr_cache.get(id(f2)), dtype=float)
    assert _same(got, segs_b)
    got1 = np.asarray(composer.hlr_cache.get(id(f1)), dtype=float)
    assert _same(got1, segs_a)


def test_scene_geometry_rebuilds_when_live_layers_move():
    scene, s1, s2 = _build_scene()
    s1.apply_state(scene)
    composer, host = _make_composer(scene)
    tris, _, _, _ = composer._scene_geometry()
    assert len(tris) and float(tris[:, :, 0].max()) == pytest.approx(2.0)
    # Live recalled to S2 with no version bump: the shared collection
    # must follow the layers, not serve the S1 build.
    s2.apply_state(scene)
    tris, _, _, _ = composer._scene_geometry()
    assert len(tris) and float(tris[:, :, 0].min()) == pytest.approx(10.0)


def test_frame_scene_does_not_leak_hidden_objects():
    scene, s1, s2 = _build_scene()
    gb = next(g for g in scene.groups if g.name == "BoxB")
    s2.hidden_objects = [gb.uid]
    s1.apply_state(scene)
    assert not gb.hidden
    composer, host = _make_composer(scene)
    f2 = composer.comp.frames[0]
    _prep_frame(f2, "scene:S2")
    composer.compute_hlr(f2)
    # The frame rendered with BoxB hidden; the live model must not keep it.
    assert not gb.hidden
    assert [ly.visible for ly in scene.layers] == [True, True, False]


def test_visibility_sig_moves_with_layers_and_hidden_objects():
    scene, s1, s2 = _build_scene()
    base = visibility_sig(scene)
    scene.layer("B").visible = False
    assert visibility_sig(scene) != base
    scene.layer("B").visible = True
    assert visibility_sig(scene) == base
    gb = next(g for g in scene.groups if g.name == "BoxB")
    gb.hidden = True
    assert visibility_sig(scene) != base
    gb.hidden = False
    assert visibility_sig(scene) == base
