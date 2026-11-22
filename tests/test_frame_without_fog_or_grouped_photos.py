# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What a model does not use costs its frames nothing.

* No group holds a photo (Marco's plaza: 3 400 groups, none): once a walk
  has found none, the frames stop asking for the placements — their
  expansion and their epoch, three times a frame (the photos, their
  outlines, the snap) — until the scene's version changes.
* A style without fog: the backdrop and the sky's colours are the
  style's own, without the fog colour being worked out each frame — and
  they are the same colours as before."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtGui import QVector3D as V

from core.group import Group
from core.history import History
from core.mesh import Mesh
from core.scene import Scene
from core.style import Style


def _fake(scene):
    from views.viewport import Viewport
    asked = []

    def placements():
        asked.append(1)
        return scene.groups
    fake = SimpleNamespace(scene=scene, _placements=placements,
                           _owner_of=lambda g: g)
    fake._grouped_image_rows = (
        lambda: Viewport._grouped_image_rows(fake))
    return fake, asked, Viewport


def test_frames_of_a_model_without_grouped_photos_ask_nothing():
    scene = Scene()
    for k in range(40):
        scene.groups.append(Group(Mesh(), name=f"g{k}"))
    fake, asked, Viewport = _fake(scene)
    assert list(Viewport._placed_image_planes(fake)) == []
    assert len(asked) == 1
    for _frame in range(30):                    # an orbit
        for _pass in range(3):                  # draw, outlines, snap
            assert list(Viewport._placed_image_planes(fake)) == []
    assert len(asked) == 1, "the placements were asked for again"
    scene.version += 1                          # an edit: asked once more
    assert list(Viewport._placed_image_planes(fake)) == []
    assert len(asked) == 2


def test_a_photo_put_in_a_group_shows_at_its_command():
    from core.history import MakeImageGroupCommand
    from core.image_plane import ImagePlane
    scene = Scene()
    hist = History(scene)
    for k in range(5):
        scene.groups.append(Group(Mesh(), name=f"g{k}"))
    fake, _asked, Viewport = _fake(scene)
    assert list(Viewport._placed_image_planes(fake)) == []
    image = ImagePlane("facade.png", V(0, 0, 0), V(4, 0, 0), V(0, 3, 0),
                       aspect=0.75)
    scene.image_planes.append(image)
    hist.execute(MakeImageGroupCommand([image]))
    group = next(g for g in scene.groups if getattr(g, "images", None))
    assert list(Viewport._placed_image_planes(fake)) == [
        (image, group.xform, group)]
    hist.undo()
    assert [im for im, _m, _o in Viewport._placed_image_planes(fake)] \
        == [image]                              # loose again


def _reference_backdrop(style):
    """fog_backdrop and fog_sky_colors as they were, mixing toward the
    fog colour whatever its strength."""
    from views.viewport import _support as s
    base = s._safe_rgb(getattr(style, "background", (0.9, 0.91, 0.92)),
                       (0.9, 0.91, 0.92))
    strength = s.fog_backdrop_strength(style)
    fog = s.effective_fog_color(style)
    clear = s._toward_fog(base, fog, strength)
    colors = (
        s._safe_rgb(getattr(style, "sky_color", (0.925, 0.935, 0.945)),
                    (0.925, 0.935, 0.945)),
        s._safe_rgb(getattr(style, "horizon_color", (1.0, 1.0, 1.0)),
                    (1.0, 1.0, 1.0)),
        s._safe_rgb(getattr(style, "ground_color", (0.815, 0.820, 0.815)),
                    (0.815, 0.820, 0.815)))
    horizon = (s._toward_fog(colors[1], fog, strength)
               if strength > 0.0
               or getattr(style, "horizon_color", None) is not None
               else None)
    sky = (s._toward_fog(colors[0], fog, strength), horizon,
           s._toward_fog(colors[2], fog, strength * 0.15))
    return (clear, bool(getattr(style, "sky", False))), sky


def test_a_style_without_fog_skips_the_fog_colour(monkeypatch):
    from views.viewport import _support as s
    styles = []
    for horizon in (None, (0.7, 0.8, 0.9)):
        for bg in ((0.9, 0.91, 0.92), (0.0, 0.0, 0.0), (1.0, 0.2, 0.3)):
            st = Style()
            st.background = bg
            if horizon is not None:
                st.horizon_color = horizon
            styles.append(st)
    for st in styles:                           # same colours as before
        assert (s.fog_backdrop(st), s.fog_sky_colors(st)) \
            == _reference_backdrop(st)
    worked = []
    real = s.effective_fog_color
    monkeypatch.setattr(s, "effective_fog_color",
                        lambda style: worked.append(1) or real(style))
    for st in styles:
        s.fog_backdrop(st)
        s.fog_sky_colors(st)
    assert worked == [], "the fog colour was worked out without fog"
    fogged = Style()
    fogged.fog_enabled = True
    s.fog_backdrop(fogged)
    assert worked, "with fog it is"
