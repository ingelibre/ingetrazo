# SPDX-License-Identifier: GPL-3.0-or-later
"""SnapshotImport undoes what a script changed INSIDE sheets, scenes and
layers, not only which of them exist (review of #1506).

A ``run_python`` that set a frame's scale, renamed a scene or filled in a
title block reported «changed: False», left no undo step and no dirty
flag. Undo now puts the content back into the SAME objects: the composer
holds frames (selection, render caches, the items panel) and the sheet's
item lists, and they must still be the ones on the sheet afterwards."""
from __future__ import annotations

import weakref

import pytest

from core import history as H
from core.composition import Cajetin, Composicion, MarcoVista, TextoItem
from core.history import History, SnapshotImport
from core.layers import Layer
from core.saved_views import SavedView
from core.scene import Scene


def _scene():
    scene = Scene()
    sheet = Composicion(name="Plan")
    sheet.frames.append(MarcoVista(scale_n=100.0))
    sheet.frames.append(MarcoVista(scale_n=50.0))
    sheet.cajetin = Cajetin(proyecto="House")
    scene.compositions.append(sheet)
    scene.saved_views.append(SavedView("Kitchen"))
    scene.layers.append(Layer("Walls"))
    return scene, sheet


def test_a_frame_edit_is_one_step_and_keeps_every_object():
    scene, sheet = _scene()
    frame, frames = sheet.frames[0], sheet.frames
    history = History(scene)

    def rescale(s):
        s.compositions[0].frames[0].scale_n = 20.0

    cmd = SnapshotImport(rescale)
    history.execute(cmd)
    assert cmd.changed
    assert [k for k, *_ in cmd.content_edits] == ["sheet"]
    history.undo()
    assert frame.scale_n == 100.0
    assert sheet.frames is frames and sheet.frames[0] is frame
    history.redo()
    assert frame.scale_n == 20.0 and sheet.frames[0] is frame
    history.undo()
    assert frame.scale_n == 100.0


def test_items_added_and_removed_inside_a_sheet():
    scene, sheet = _scene()
    first, second = sheet.frames
    history = History(scene)

    def edit(s):
        c = s.compositions[0]
        c.frames.remove(first)
        second.scale_n = 25.0
        c.texts.append(TextoItem(text="Küche"))

    history.execute(SnapshotImport(edit))
    added = sheet.texts[0]
    history.undo()
    assert sheet.frames == [first, second]
    assert sheet.frames[0] is first and second.scale_n == 50.0
    assert sheet.texts == []
    history.redo()
    assert sheet.frames[0] is second and second.scale_n == 25.0
    assert sheet.texts[0] is added             # the same text comes back


def test_a_list_the_script_replaced_is_put_back_as_the_same_list():
    scene, sheet = _scene()
    frames = sheet.frames
    history = History(scene)

    def replace(s):
        s.compositions[0].frames = [MarcoVista()]

    history.execute(SnapshotImport(replace))
    history.undo()
    assert sheet.frames is frames and len(frames) == 2


def test_title_block_scene_and_layer_edits():
    scene, sheet = _scene()
    block, view, layer = sheet.cajetin, scene.saved_views[0], scene.layers[0]
    history = History(scene)

    def edit(s):
        s.compositions[0].cajetin.lamina = "L-07"
        s.saved_views[0].name = "Küche"
        s.saved_views[0].hidden_layers.append("Walls")
        s.layers[0].visible = False

    cmd = SnapshotImport(edit)
    history.execute(cmd)
    assert sorted(k for k, *_ in cmd.content_edits) == [
        "layer", "scene", "sheet"]
    history.undo()
    assert sheet.cajetin is block and block.lamina == "L-01"
    assert view.name == "Kitchen" and view.hidden_layers == []
    assert layer.visible is True
    history.redo()
    assert block.lamina == "L-07" and view.name == "Küche"
    assert view.hidden_layers == ["Walls"] and layer.visible is False


def test_a_script_that_raises_leaves_the_content_as_it_was():
    scene, sheet = _scene()
    frame, layer = sheet.frames[0], scene.layers[0]

    def fail(s):
        s.layers[0].visible = False
        s.compositions[0].frames[0].scale_n = 1.0
        s.compositions[0].texts.append(TextoItem())
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        SnapshotImport(fail).do(scene)
    assert layer.visible is True
    assert frame.scale_n == 100.0 and sheet.frames[0] is frame
    assert sheet.texts == []


def test_nothing_changed_is_no_edit():
    scene, _sheet = _scene()

    def look(s):
        _ = [f.scale_n for f in s.compositions[0].frames]

    cmd = SnapshotImport(look)
    History(scene).execute(cmd)
    assert cmd.content_edits == [] and not cmd.changed


def test_an_attribute_a_script_added_to_a_layer_goes_on_undo():
    scene, _sheet = _scene()
    layer = scene.layers[0]
    history = History(scene)

    def tag(s):
        s.layers[0].note = "load-bearing"

    history.execute(SnapshotImport(tag))
    history.undo()
    assert not hasattr(layer, "note")
    history.redo()
    assert layer.note == "load-bearing"


def test_listeners_hear_which_sheets_changed():
    scene, sheet = _scene()
    other = Composicion(name="Untouched")
    scene.compositions.append(other)
    heard = []

    class Listener:
        def on(self, s, sheets):
            heard.append((s, list(sheets)))

    listener = Listener()
    H.SHEET_CONTENT_LISTENERS.append(weakref.WeakMethod(listener.on))
    try:
        history = History(scene)

        def edit(s):
            s.compositions[0].name = "Plan EG"

        history.execute(SnapshotImport(edit))
        history.undo()
        history.redo()
        assert heard == [(scene, [sheet])] * 3
        del listener                      # held weakly: gone with it
        history.undo()
        assert len(heard) == 3
    finally:
        H.SHEET_CONTENT_LISTENERS[:] = [
            r for r in H.SHEET_CONTENT_LISTENERS if r() is not None]


def test_the_composer_ends_its_item_undo_where_a_script_edits_its_sheet():
    """The rule between the two histories: a script's sheet edit is a step
    of the DOCUMENT's history. The composer's item steps for that sheet end
    there (their values predate the script); its steps on the set of sheets
    stay, and every frame is still the same object."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    from core.composition import EditItemCommand
    from tests.test_composer_canvas import _FakeViewport
    from views.composer import ComposerWindow

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.viewport = _FakeViewport()
    composer = ComposerWindow(host)
    sheet = composer.comp
    frame = sheet.frames[0]
    composer.history.execute(EditItemCommand(frame, {"scale_n": 75.0}))
    assert composer.history._undo

    scene = host.viewport.scene
    history = History(scene)
    history.execute(SnapshotImport(
        lambda s: setattr(s.compositions[0].frames[0], "scale_n", 10.0)))
    assert not any(isinstance(c, EditItemCommand)
                   for c in composer.history._undo)
    assert not composer.history.undo()   # nothing of the composer's left
    assert frame.scale_n == 10.0         # …so the script's edit stands
    history.undo()
    assert sheet.frames[0] is frame and frame.scale_n == 75.0
    app.processEvents()                  # the deferred redraw runs cleanly
    composer.close()


def test_a_script_on_another_sheet_leaves_the_composer_undo_alone():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    from core.composition import EditItemCommand
    from tests.test_composer_canvas import _FakeViewport
    from views.composer import ComposerWindow

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.viewport = _FakeViewport()
    composer = ComposerWindow(host)
    scene = host.viewport.scene
    scene.compositions.append(Composicion(name="Other"))
    composer.history.execute(
        EditItemCommand(composer.comp.frames[0], {"scale_n": 75.0}))
    History(scene).execute(SnapshotImport(
        lambda s: setattr(s.compositions[1], "name", "Renamed")))
    assert composer.history._undo
    app.processEvents()
    composer.close()
