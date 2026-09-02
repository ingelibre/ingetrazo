# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Text annotations (leader labels) and 3D Text geometry."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication, QVector3D

_app = QGuiApplication.instance() or QGuiApplication([])

from core.history import (AddTextLabelCommand, DeleteTextLabelsCommand,
                          History)
from core.scene import Scene
from core.text3d import build_text_mesh
from core.textlabel import TextLabel
from formats import igz


def _closed(mesh) -> bool:
    counts: dict = {}
    for f in mesh.faces:
        for lp in (f.loop, *f.hole_loops):
            n = len(lp)
            for i in range(n):
                k = frozenset((id(lp[i]), id(lp[(i + 1) % n])))
                counts[k] = counts.get(k, 0) + 1
    return bool(counts) and all(c == 2 for c in counts.values())


# ---- 3D Text ----------------------------------------------------------------

def test_3d_text_builds_watertight_letters_with_holes():
    mesh = build_text_mesh("O", "Sans", height=0.5, thickness=0.1)
    assert mesh.faces
    assert _closed(mesh)                            # solid ring, hole intact
    from core.orient import signed_volume
    assert signed_volume(mesh) > 0
    # the front face carries the counter of the O as a hole
    assert any(f.hole_loops for f in mesh.faces)


def test_3d_text_height_is_the_real_block_height():
    mesh = build_text_mesh("AB", "Sans", height=0.5, thickness=0.05)
    zs = [v.position.z() for v in mesh.vertices]
    assert abs((max(zs) - min(zs)) - 0.5) < 1e-6    # exactly what was asked
    assert abs(min(zs)) < 1e-9                      # base ON the ground


def test_3d_text_flat_when_thickness_zero():
    mesh = build_text_mesh("I", "Sans", height=0.3, thickness=0.0)
    assert mesh.faces
    ys = [v.position.y() for v in mesh.vertices]
    assert abs(max(ys) - min(ys)) < 1e-9            # a flat sheet


def test_3d_text_empty_string_builds_nothing():
    assert not build_text_mesh("", "Sans").faces
    assert not build_text_mesh("   ", "Sans").faces


def test_3d_text_curve_seams_are_soft():
    # The O's curved thickness must read smooth: wall-to-wall seams at a
    # shallow dihedral are softened, while the front/back outlines stay hard.
    mesh = build_text_mesh("O", "Sans", height=0.5, thickness=0.1)
    soft = [e for e in mesh.edges if e.soft]
    assert soft                                     # curved seams hidden
    for e in soft:                                  # only wall-wall seams
        for f in e.faces:
            assert abs(f.normal().y()) < 0.5
    # outline edges (front face <-> wall, ~90 deg) never soften
    hard_outline = [
        e for e in mesh.edges
        if len(e.faces) == 2 and not e.soft
        and any(abs(f.normal().y()) > 0.5 for f in e.faces)]
    assert hard_outline


def test_place_face_frame_maps_walls_and_floors():
    from PySide6.QtGui import QVector3D
    from tools.place_group import PlaceGroupTool
    # wall facing -Y: sign stands upright, reading along +X
    right, y_axis, up = PlaceGroupTool._face_frame(QVector3D(0, -1, 0))
    assert (right - QVector3D(1, 0, 0)).length() < 1e-6
    assert (up - QVector3D(0, 0, 1)).length() < 1e-6
    assert (y_axis - QVector3D(0, 1, 0)).length() < 1e-6   # front -> -Y = normal
    # floor facing +Z: text lies flat, its up pointing north
    right, y_axis, up = PlaceGroupTool._face_frame(QVector3D(0, 0, 1))
    assert (right - QVector3D(1, 0, 0)).length() < 1e-6
    assert (up - QVector3D(0, 1, 0)).length() < 1e-6
    assert (y_axis - QVector3D(0, 0, -1)).length() < 1e-6  # front faces up


# ---- Leader text labels -------------------------------------------------------

def test_label_commands_undo_redo():
    scene = Scene()
    history = History(scene)
    lab = TextLabel(QVector3D(1, 2, 0), QVector3D(0.5, 0, 1), "Muro eje A")
    history.execute(AddTextLabelCommand(lab))
    assert scene.text_labels == [lab]
    history.undo()
    assert scene.text_labels == []
    history.redo()
    assert scene.text_labels == [lab]
    history.execute(DeleteTextLabelsCommand([lab]))
    assert scene.text_labels == []
    history.undo()
    assert scene.text_labels == [lab]


def test_label_edit_command_undo_redo():
    from core.history import EditTextLabelCommand
    scene = Scene()
    history = History(scene)
    lab = TextLabel(QVector3D(1, 2, 0), QVector3D(0.5, 0, 1), "Muro eje A")
    scene.text_labels.append(lab)
    history.execute(EditTextLabelCommand(lab, "Muro eje B"))
    assert lab.text == "Muro eje B"
    history.undo()
    assert lab.text == "Muro eje A"
    history.redo()
    assert lab.text == "Muro eje B"


def test_select_double_click_edits_label(monkeypatch):
    """Double-clicking a leader text with Select opens the edit dialog
    (SketchUp-style) and commits the new text as one undoable command."""
    from types import SimpleNamespace
    from PySide6.QtWidgets import QInputDialog
    from tools.select import SelectTool

    scene = Scene()
    history = History(scene)
    lab = TextLabel(QVector3D(1, 2, 0), QVector3D(0.5, 0, 1), "Muro eje A")
    scene.text_labels.append(lab)

    viewport = SimpleNamespace(
        scene=scene, history=history,
        pick_group=lambda x, y: None, pick_edge=lambda x, y: None,
        pick_dimension=lambda x, y: None,
        pick_text_label=lambda x, y, rect_only=False: lab,
        pick_geopath=lambda x, y: None, pick_face=lambda x, y: None,
        window=lambda: None, update=lambda: None)
    ctx = SimpleNamespace(viewport=viewport,
                          screen=SimpleNamespace(x=lambda: 0, y=lambda: 0),
                          modifiers=0)

    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("Muro eje B", True)))
    SelectTool().on_double_click(ctx)
    assert lab.text == "Muro eje B"
    history.undo()
    assert lab.text == "Muro eje A"

    # cancelling the dialog leaves the label untouched (and no undo entry)
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("cualquier", False)))
    SelectTool().on_double_click(ctx)
    assert lab.text == "Muro eje A"


def test_label_move_command_shifts_offset_only():
    from core.history import MoveTextLabelsCommand
    scene = Scene()
    history = History(scene)
    lab = TextLabel(QVector3D(1, 2, 0), QVector3D(0.5, 0, 1), "Muro eje A")
    scene.text_labels.append(lab)
    history.execute(MoveTextLabelsCommand([lab], QVector3D(1, 0, 2)))
    assert (lab.anchor - QVector3D(1, 2, 0)).length() < 1e-9   # pinned
    assert (lab.offset - QVector3D(1.5, 0, 3)).length() < 1e-9
    history.undo()
    assert (lab.offset - QVector3D(0.5, 0, 1)).length() < 1e-9


def test_move_tool_drags_selected_label():
    """Move with a leader text selected translates its label end (one
    undoable command), leaving the anchor pinned."""
    from types import SimpleNamespace
    from tools.move import MoveTool

    scene = Scene()
    history = History(scene)
    lab = TextLabel(QVector3D(1, 2, 0), QVector3D(0.5, 0, 1), "Muro eje A")
    scene.text_labels.append(lab)
    scene.select([lab])

    viewport = SimpleNamespace(
        scene=scene, history=history,
        pick_group=lambda x, y: None, pick_edge=lambda x, y: None,
        pick_face=lambda x, y: None,
        pick_text_label=lambda x, y, rect_only=False: None,
        update=lambda: None)
    screen = SimpleNamespace(x=lambda: 0, y=lambda: 0)
    tool = MoveTool()
    tool.on_click(SimpleNamespace(viewport=viewport, screen=screen,
                                  world=QVector3D(0, 0, 0), modifiers=0))
    assert tool._labels == [lab]
    tool.on_click(SimpleNamespace(viewport=viewport, screen=screen,
                                  world=QVector3D(2, 0, 1), modifiers=0))
    assert (lab.anchor - QVector3D(1, 2, 0)).length() < 1e-9
    assert (lab.offset - QVector3D(2.5, 0, 2)).length() < 1e-9
    history.undo()
    assert (lab.offset - QVector3D(0.5, 0, 1)).length() < 1e-9


def test_select_delete_key_removes_label():
    """Supr with a leader text selected deletes it (the import of
    DeleteTextLabelsCommand was missing and only NameError'd at press
    time — regression guard)."""
    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from tools.select import SelectTool

    scene = Scene()
    history = History(scene)
    lab = TextLabel(QVector3D(1, 2, 0), QVector3D(0.5, 0, 1), "Muro eje A")
    scene.text_labels.append(lab)
    scene.select([lab])
    viewport = SimpleNamespace(scene=scene, history=history,
                               update=lambda: None)
    assert SelectTool().on_key(viewport, Qt.Key_Delete,
                               Qt.KeyboardModifier.NoModifier)
    assert scene.text_labels == []
    assert not scene.selection
    history.undo()
    assert scene.text_labels == [lab]


def test_label_igz_round_trip(tmp_path):
    scene = Scene()
    scene.text_labels.append(TextLabel(
        QVector3D(1, 2, 3), QVector3D(0, 0, 1), "Cisterna\n10 m³"))
    p = tmp_path / "texto.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    assert len(scene2.text_labels) == 1
    lab = scene2.text_labels[0]
    assert lab.text == "Cisterna\n10 m³"
    assert (lab.position() - QVector3D(1, 2, 4)).length() < 1e-6
    scene2.clear()
    assert scene2.text_labels == []


def test_text_block_sits_away_from_the_anchor():
    """SketchUp: the leader ends at the NEAR edge of the text block, so the
    block goes right when the anchor is on the left and LEFT when the
    leader arrives from the right — never under the words."""
    from views.viewport import Viewport
    x = Viewport._text_block_x
    assert x((100.0, 50.0), (20.0, 50.0), 80.0) == 106.0      # anchor left
    assert x((100.0, 50.0), (300.0, 50.0), 80.0) == 14.0      # anchor right
    assert x((100.0, 50.0), None, 80.0) == 106.0              # no anchor


def test_pick_text_label_hits_the_drawn_block():
    """The hit box follows the drawn block: with the anchor to the right the
    words are LEFT of the leader end, and a click there (not to the right,
    where the block used to be) picks the label."""
    from PySide6.QtGui import QFont, QFontMetrics
    from views.viewport import Viewport

    scene = Scene()
    lab = TextLabel(QVector3D(3, 0, 0), QVector3D(-2, 0, 0), "Pileta")
    scene.text_labels.append(lab)
    font = QFont()
    font.setPointSize(9)
    font.setBold(True)
    w = QFontMetrics(font).horizontalAdvance("Pileta")

    class _VP:
        pick_threshold_px = 8.0
        _text_block_x = staticmethod(Viewport._text_block_x)

        def _world_to_pixel(self, p):
            return {3.0: (300.0, 100.0), 1.0: (100.0, 100.0)}[round(p.x(), 6)]

    vp = _VP()
    vp.scene = scene
    pick = Viewport.pick_text_label.__get__(vp)
    assert pick(100 - 6 - w / 2, 96, rect_only=True) is lab    # inside block
    assert pick(100 + 6 + w / 2, 96, rect_only=True) is None   # old side
