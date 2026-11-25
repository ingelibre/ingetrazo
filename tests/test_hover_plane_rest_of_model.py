# SPDX-License-Identifier: GPL-3.0-or-later
"""A face of the rest of the model, hovered from inside an open group, is a
plane to draw on: its unhashable wrapper must not stop the lookup."""
from types import SimpleNamespace

import core.snap
from views.viewport import Viewport


def _fake(grp, selection):
    face = object()
    return face, SimpleNamespace(
        pick_face_inference=lambda x, y: (face, grp),
        scene=SimpleNamespace(selection=selection),
        _owner_of=lambda g: getattr(g, "owner", None) or g,
        active_tool=None)


def test_the_rest_of_the_model_gives_its_plane(monkeypatch):
    monkeypatch.setattr(core.snap, "face_plane_world",
                        lambda face, xform: ("plane", face, xform))
    rest = SimpleNamespace(mesh=object(), xform=None)
    face, vp = _fake(rest, {object()})
    assert Viewport._hover_face_plane(vp, (5, 5)) == ("plane", face, None)


def test_a_selected_group_is_still_not_a_plane(monkeypatch):
    monkeypatch.setattr(core.snap, "face_plane_world",
                        lambda face, xform: ("plane", face, xform))

    class Group:
        xform = None
    g = Group()
    _face, vp = _fake(g, {g})
    assert Viewport._hover_face_plane(vp, (5, 5)) is None
