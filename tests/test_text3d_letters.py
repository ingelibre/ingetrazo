# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""3D Text the classic way: one group per letter, and the text stays
editable afterwards (Rafael's review, 2026-09-16)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QMatrix4x4, QVector3D

_app = QGuiApplication.instance() or QGuiApplication([])

from core.group import Group, copy_group, iter_placements
from core.history import EditText3DCommand, History
from core.scene import Scene
from core.text3d import (build_text_letters, build_text_mesh,
                         make_text_group, rebuild_text_group, text_params)
from formats import igz


def _extent(meshes):
    pts = [v.position for m in meshes for v in m.vertices]
    return (min(p.x() for p in pts), max(p.x() for p in pts),
            min(p.z() for p in pts), max(p.z() for p in pts))


# TODO(MAC-07): Baseline macOS separate-letter text is approximately 0.0055014 m wider.
# See docs/macos-test-failures.md; confirmed on the baseline commit, not fixed yet.
def test_letters_lay_out_exactly_like_the_one_piece_text():
    """Splitting into letters changes the STRUCTURE, never the geometry:
    same faces, same block extent, same baseline."""
    whole = build_text_mesh("IngeTrazo", "Sans", True, False, 0.25, 0.05)
    letters = build_text_letters("IngeTrazo", "Sans", True, False, 0.25, 0.05)
    assert [c for c, _m in letters] == list("IngeTrazo")
    assert sum(len(m.faces) for _c, m in letters) == len(whole.faces)
    a = _extent([whole])
    b = _extent([m for _c, m in letters])
    assert all(abs(x - y) < 1e-6 for x, y in zip(a, b))
    # letters sit in reading order, each to the right of the previous
    lefts = [min(v.position.x() for v in m.vertices) for _c, m in letters]
    assert lefts == sorted(lefts)


def test_spaces_make_no_letter_group():
    letters = build_text_letters("Ab c", "Sans")
    assert [c for c, _m in letters] == ["A", "b", "c"]


def test_text_group_is_a_container_of_letter_groups():
    g = make_text_group(text_params("Plaza", "Sans", height=0.4))
    assert g is not None
    assert g.is_instance()                    # a container is always one
    assert not g.mesh.faces                   # geometry lives in the letters
    assert [k.name for k in g.children] == list("Plaza")
    assert all(k.is_instance() and k.mesh.faces for k in g.children)
    assert g.text3d["text"] == "Plaza" and g.text3d["height"] == 0.4
    assert make_text_group(text_params("   ", "Sans")) is None


def test_text_group_round_trips_through_igz(tmp_path):
    scene = Scene()
    scene.groups.append(make_text_group(text_params("Yanque", "Sans")))
    p = tmp_path / "texto3d.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    g = scene2.groups[0]
    assert g.text3d == scene.groups[0].text3d
    assert [k.name for k in g.children] == list("Yanque")


def test_copy_group_keeps_the_text_parameters():
    g = make_text_group(text_params("Ab", "Sans"))
    c = copy_group(g)
    assert c.text3d == g.text3d and c.text3d is not g.text3d


def test_edit_command_relays_the_letters_where_the_text_stands():
    """Editing keeps the pose: the new letters take the frame the old ones
    shared (the container's matrix gets pushed down into the children when
    the group is entered, so the frame is read off the letters)."""
    scene = Scene()
    history = History(scene)
    g = make_text_group(text_params("Ab", "Sans"))
    pose = QMatrix4x4()
    pose.translate(QVector3D(10.0, 5.0, 0.0))
    pose.rotate(90.0, QVector3D(0, 0, 1))
    for k in g.children:                      # as begin_group_edit leaves them
        k.xform = pose * k.xform
    scene.groups.append(g)
    old_children = g.children

    history.execute(EditText3DCommand(g, text_params("Hola", "Sans")))
    assert [k.name for k in g.children] == list("Hola")
    assert g.name == "Hola" and g.text3d["text"] == "Hola"
    for k in g.children:
        assert k.xform == pose
    # ...so the new text stands at the same spot: rotated 90° about Z, its
    # thickness (+Y local) runs along -X and its width along +Y (the left
    # bearing of the "H" at 25 cm tall is under 5 cm).
    pts = [m.map(v.position) if m is not None else v.position
           for gg, m in iter_placements(g) for v in gg.mesh.vertices]
    assert abs(min(p.x() for p in pts) - (10.0 - 0.05)) < 1e-6
    assert abs(min(p.y() for p in pts) - 5.0) < 0.05

    history.undo()
    assert g.children is old_children
    assert g.text3d["text"] == "Ab" and g.name == "Ab"
    history.redo()
    assert [k.name for k in g.children] == list("Hola")


def test_rebuild_from_a_container_without_letters_uses_identity():
    g = make_text_group(text_params("A", "Sans"))
    g.children = []
    kids = rebuild_text_group(g, text_params("B", "Sans"))
    assert [k.name for k in kids] == ["B"]
    assert kids[0].xform == QMatrix4x4()


def test_select_double_click_on_a_text_enters_it_like_any_group():
    """Double-click keeps its usual meaning — it ENTERS the group, whose
    children are the letters (Marco, 2026-09-18: «no hay opción de editar
    texto»). Re-editing the text is the right-click's job."""
    from types import SimpleNamespace
    from tools.select import SelectTool

    scene = Scene()
    text = make_text_group(text_params("Ab", "Sans"))
    calls = []
    window = SimpleNamespace(_on_edit_3d_text=lambda g: calls.append(("edit", g)))
    vp = SimpleNamespace(
        scene=scene, history=History(scene),
        pick_group=lambda x, y: text, pick_edge=lambda x, y: None,
        pick_dimension=lambda x, y: None,
        pick_text_label=lambda x, y, rect_only=False: None,
        pick_geopath=lambda x, y: None, pick_face=lambda x, y: None,
        pick_section_plane=lambda x, y: None,
        pick_image_plane=lambda x, y: None,
        pick_guide=lambda x, y: None,
        begin_group_edit=lambda g: calls.append(("enter", g)),
        window=lambda: window, update=lambda: None)
    ctx = SimpleNamespace(viewport=vp,
                          screen=SimpleNamespace(x=lambda: 0, y=lambda: 0),
                          modifiers=0)
    SelectTool().on_double_click(ctx)
    assert calls == [("enter", text)]


def test_edit_3d_text_reaches_the_container_from_a_letter_inside():
    """Right-click on a letter while inside the text offers to edit the
    TEXT: the container is what carries the parameters."""
    from types import SimpleNamespace
    from views.main_window import MainWindow

    scene = Scene()
    text = make_text_group(text_params("Ab", "Sans"))
    scene.groups.append(text)
    scene.edit_group = text
    scene.select([text.children[1]])
    win = SimpleNamespace(viewport=SimpleNamespace(scene=scene))
    assert MainWindow._selected_text3d(win) is text
    scene.edit_group = None
    scene.select([text])
    assert MainWindow._selected_text3d(win) is text
    scene.select([Group(name="caja")])
    assert MainWindow._selected_text3d(win) is None


def test_place_tool_previews_the_letter_outlines():
    """A 3D text is a container, but its outlines are what the cursor should
    carry — not the box that big imported documents fall back to."""
    from tools.place_group import PlaceGroupTool
    g = make_text_group(text_params("Ab", "Sans"))
    tool = PlaceGroupTool(g, align_to_face=True)
    edges = sum(len(k.mesh.edges) for k in g.children)
    assert len(tool._segments) == edges and edges > 12


# ---- Letters touched by hand -------------------------------------------------

def _touch_vertex(letter):
    v = letter.mesh.vertices[0]
    letter.mesh.move_vertex(v, QVector3D(0.0, 0.0, 0.01))


def test_a_fresh_text_is_pristine_and_stays_so_through_igz(tmp_path):
    from core.text3d import text_is_pristine
    scene = Scene()
    g = make_text_group(text_params("Yanque", "Sans"))
    scene.groups.append(g)
    assert g.text3d["hash"] and text_is_pristine(g)
    p = tmp_path / "t.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    assert text_is_pristine(scene2.groups[0])


def test_a_letter_pushed_painted_erased_or_moved_makes_the_text_plain():
    """Marco, 2026-09-18: once a letter is edited by hand, «Edit 3D Text…»
    must stop regenerating — it would throw the hand work away."""
    from core.text3d import text_is_pristine

    g = make_text_group(text_params("Ab", "Sans"))
    _touch_vertex(g.children[0])                       # pushed / reshaped
    assert not text_is_pristine(g)

    g = make_text_group(text_params("Ab", "Sans"))
    g.children[1].mesh.faces[0].attrs["color"] = [1.0, 0.0, 0.0]   # painted
    assert not text_is_pristine(g)

    g = make_text_group(text_params("Ab", "Sans"))
    g.children.pop()                                   # a letter erased
    assert not text_is_pristine(g)

    g = make_text_group(text_params("Ab", "Sans"))
    g.children[0].xform.translate(QVector3D(0.3, 0, 0))   # moved alone
    assert not text_is_pristine(g)

    # ...but moving/rotating the WHOLE text (the container's matrix pushed
    # down into every letter alike) keeps it text.
    g = make_text_group(text_params("Ab", "Sans"))
    pose = QMatrix4x4()
    pose.rotate(30.0, QVector3D(0, 0, 1))
    pose.translate(QVector3D(5, 5, 0))
    for k in g.children:
        k.xform = pose * k.xform
    assert text_is_pristine(g)


def test_an_edit_command_leaves_the_new_letters_pristine():
    from core.text3d import text_is_pristine
    scene = Scene()
    history = History(scene)
    g = make_text_group(text_params("Ab", "Sans"))
    scene.groups.append(g)
    history.execute(EditText3DCommand(g, text_params("Hola", "Sans")))
    assert text_is_pristine(g)
    _touch_vertex(g.children[0])
    assert not text_is_pristine(g)
    history.undo()
    assert text_is_pristine(g)                # the old letters come back intact


def test_edit_3d_text_refuses_a_text_edited_by_hand():
    from types import SimpleNamespace
    from views.main_window import MainWindow

    scene = Scene()
    g = make_text_group(text_params("Ab", "Sans"))
    scene.groups.append(g)
    _touch_vertex(g.children[0])
    flashed = []
    opened = []
    win = SimpleNamespace(
        viewport=SimpleNamespace(
            scene=scene, history=History(scene),
            flash_status=lambda msg, ms=0: flashed.append(msg)),
        _selected_text3d=lambda: g,
        _text3d_dialog=lambda params=None: opened.append(params) or None)
    MainWindow._on_edit_3d_text(win, g)
    assert flashed and not opened
