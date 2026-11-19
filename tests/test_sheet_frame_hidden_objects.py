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
