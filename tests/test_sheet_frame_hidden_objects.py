# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A sheet frame bound to a scene that hides objects shows that scene's
objects while it renders, and the live model gets ALL of its own back —
nested groups and the «show hidden» switch included (16/19-11, the final
plaza: a detail sheet left 3 402 groups hidden, the next sheet drew the
pergola over a missing fountain, the model tab lost the plaza while
orbiting). What is drawn and collected sees the frame's state: the
version moves (a view-only bump) and the frame's lines are its own."""
from __future__ import annotations

from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.mesh import Mesh


def _box(name, x):
    m = Mesh()
    m.add_face([V(x, 0, 0), V(x + 1, 0, 0), V(x + 1, 1, 0), V(x, 1, 0)])
    return Group(m, name=name)


def _plaza(scene):
    fountain, pergola, post = _box("Fountain", 0), _box("Pergola", 3), \
        _box("Post", 6)
    water = _box("Water", 0.2)
    fountain.adopt([water])                 # nested: the fountain's water
    scene.groups.extend([fountain, pergola, post])
    scene.version += 1
    return fountain, water, pergola, post


def _hidden(scene):
    """Every group's state (the new document's figure too)."""
    return {g.name: bool(g.hidden) for g in scene.groups_by_uid().values()}


_OURS = ("Fountain", "Water", "Pergola", "Post")


def test_a_detail_frame_hides_its_objects_and_gives_the_model_back():
    from core.composition import MarcoVista
    from core.saved_views import SavedView
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        sc = win.viewport.scene
        fountain, water, pergola, post = _plaza(sc)
        cam = win.viewport.camera
        # The pergola's detail: only the pergola shows.
        fountain.hidden = post.hidden = True
        sc.saved_views.append(SavedView.capture("Pergola", sc, cam))
        # The fountain's detail: the fountain and its water, nothing else.
        fountain.hidden = post.hidden = False
        pergola.hidden = post.hidden = True
        sc.saved_views.append(SavedView.capture("Fountain", sc, cam))
        # The live model: only the post is hidden, the «show hidden» off.
        pergola.hidden = False
        water.hidden = False
        sc.show_hidden_objects = False
        live = _hidden(sc)
        comp = ComposerWindow(win)
        dirty = win.viewport.scene.version
        seen = []
        for name in ("Pergola", "Fountain", "Pergola", "Fountain"):
            frame = MarcoVista(view_key="scene:" + name, style="vectorial")
            v0 = sc.version
            state = comp._with_frame_camera(
                frame, lambda: (_hidden(sc), sc.version, comp._visibility_sig()))
            seen.append((name, state[0]))
            assert state[1] > v0, "the frame's caches did not see the change"
            assert _hidden(sc) == live, f"{name} left its objects hidden"
            assert state[2] != comp._visibility_sig(), \
                "the frame's lines are the live model's"
        want = {"Pergola": {"Fountain": True, "Water": False, "Pergola": False,
                            "Post": True},
                "Fountain": {"Fountain": False, "Water": False,
                             "Pergola": True, "Post": True}}
        for name, state in seen:
            assert {k: state[k] for k in _OURS} == want[name], name
        assert sc.version > dirty
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_frame_of_the_live_view_leaves_the_version_alone():
    """A scene that hides what the model already hides changes nothing:
    no bump, the caches keep what they have."""
    from core.composition import MarcoVista
    from core.saved_views import SavedView
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        sc = win.viewport.scene
        _fountain, _water, _pergola, post = _plaza(sc)
        post.hidden = True
        sc.saved_views.append(SavedView.capture("Same", sc, win.viewport.camera))
        comp = ComposerWindow(win)
        frame = MarcoVista(view_key="scene:Same", style="vectorial")
        v0 = sc.version
        inside = comp._with_frame_camera(frame, lambda: sc.version)
        assert inside == v0 and sc.version == v0
        assert post.hidden is True
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_frame_render_is_not_taken_for_a_model_change():
    """The frame's own view-only bumps are the composer's: reported back by
    the viewport they must not make the sheet stale, or the auto render
    loops — every pass bumps again (final plaza, 19-11: each sheet kept
    rendering ~1.5 s passes for as long as it was open). A real edit made
    before the render still counts."""
    from core.composition import MarcoVista
    from core.saved_views import SavedView
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        sc = win.viewport.scene
        fountain, water, pergola, post = _plaza(sc)
        cam = win.viewport.camera
        pergola.hidden = post.hidden = True
        sc.saved_views.append(SavedView.capture("Fountain", sc, cam))
        pergola.hidden = post.hidden = False
        comp = ComposerWindow(win)
        frame = MarcoVista(view_key="scene:Fountain", style="vectorial")
        comp.comp.frames.append(frame)
        comp._on_model_version(sc.version)          # the composer is up to date
        comp._stale.clear()
        for _ in range(3):
            v0 = sc.version
            seen = []
            comp._with_frame_camera(
                frame, lambda: (seen.append(sc.version),
                                comp._on_model_version(sc.version)))
            assert sc.version > v0
            comp._on_model_version(sc.version)       # the viewport's next paint
            assert not comp.is_stale(frame), "its own render made it stale"
        # A real edit, not yet reported, before the next render: it counts.
        sc.version += 1
        comp._with_frame_camera(frame, lambda: None)
        comp._on_model_version(sc.version)
        assert comp.is_stale(frame), "a model edit was swallowed by the frame"
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_what_the_model_draws_sees_the_frame_but_the_document_stays_clean():
    """The caches of what the model IS key on ``geometry_version`` (#158),
    which a view-only bump does not move: a frame that hid objects with one
    drew the previous scene's objects (a lamp-post sheet showed the flag,
    20-11). The frame's bumps move it — in and out — and leave
    ``content_version``, what «unsaved changes» compares, alone."""
    from core.composition import MarcoVista
    from core.saved_views import SavedView
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    win = MainWindow()
    comp = None
    try:
        sc = win.viewport.scene
        fountain, water, pergola, post = _plaza(sc)
        pergola.hidden = post.hidden = True
        sc.saved_views.append(SavedView.capture("Fountain", sc,
                                                win.viewport.camera))
        pergola.hidden = post.hidden = False
        comp = ComposerWindow(win)
        frame = MarcoVista(view_key="scene:Fountain", style="vectorial")
        g0, c0 = sc.geometry_version, sc.content_version
        inside = comp._with_frame_camera(
            frame, lambda: (sc.geometry_version, sc.content_version))
        assert inside[0] > g0, "the model's caches kept the live objects"
        assert sc.geometry_version > inside[0], \
            "the model's caches kept the frame's objects after it"
        assert inside[1] == c0 and sc.content_version == c0, \
            "showing a scene's objects marked the document as changed"
    finally:
        if comp is not None:
            comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def test_a_scenes_picture_without_the_composer_gives_the_model_back():
    """The Scenes tab draws its pictures through SceneThumbnailer, which
    borrows ``_with_frame_camera``: it lacked the composer's
    ``_own_view_bump``, raised half way, and every picture of a scene that
    hides objects failed — grey — with the live caches left on that scene
    (20-11). Each scene's picture is its own, and the model comes back."""
    from core.saved_views import SavedView
    from views.composer import SceneThumbnailer
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        sc = win.viewport.scene
        fountain, water, pergola, post = _plaza(sc)
        cam = win.viewport.camera
        pergola.hidden = post.hidden = True
        sc.saved_views.append(SavedView.capture("Fountain", sc, cam))
        pergola.hidden = post.hidden = False
        fountain.hidden = post.hidden = True
        sc.saved_views.append(SavedView.capture("Pergola", sc, cam))
        fountain.hidden = post.hidden = False
        live = _hidden(sc)
        th = SceneThumbnailer(win)
        frame = th.screen_frame(sc.saved_views[0])
        g0, c0 = sc.geometry_version, sc.content_version
        seen = th._with_frame_camera(frame, lambda: _hidden(sc))
        assert {k: seen[k] for k in _OURS} == {
            "Fountain": False, "Water": False, "Pergola": True, "Post": True}
        assert _hidden(sc) == live
        assert sc.geometry_version > g0 and sc.content_version == c0
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
