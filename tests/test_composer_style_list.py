# SPDX-License-Identifier: GPL-3.0-or-later
"""The frame's Style list follows the style library while the composer is
open (#1283): a style saved after the composer was built shows when a frame
is selected and when the list opens, a frame already using it shows it, and
a deleted one leaves the list — without touching the frame's own style."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import random

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

import core.style as style_mod
from core.style import Style, delete_user_style, save_user_style
from tests.test_composer_canvas import _FakeViewport
from views.composer import ComposerWindow, FrameItem

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def library(tmp_path, monkeypatch):
    """The style library in a throwaway INI file, empty to start."""
    path = tmp_path / "styles.ini"
    monkeypatch.setattr(style_mod, "_settings",
                        lambda: QSettings(str(path), QSettings.IniFormat))
    return path


def _composer():
    host = QWidget()
    host.viewport = _FakeViewport()
    composer = ComposerWindow(host)
    composer._host_keepalive = host
    return composer


def _keys(combo):
    return [combo.itemData(i) for i in range(combo.count())]


def _select(composer, frame):
    composer._rebuild_canvas()
    item = next(i for i in composer.canvas.items()
                if isinstance(i, FrameItem) and i.model is frame)
    composer.canvas.clearSelection()
    item.setSelected(True)
    composer.on_selection_changed()


def _names(seed, n):
    rng = random.Random(seed)
    return [f"Mio {rng.randrange(10 ** 6)}" for _ in range(n)]


def test_style_saved_later_shows_when_a_frame_is_selected(library):
    composer = _composer()
    frame = composer.comp.frames[0]
    names = _names(1283, 3)
    assert not any(f"style:{n}" in _keys(composer.style_combo)
                   for n in names)
    for n in names:
        save_user_style(Style(name=n, face_mode="hidden_line"))
    frame.style = f"style:{names[1]}"
    _select(composer, frame)
    keys = _keys(composer.style_combo)
    for n in names:
        assert f"style:{n}" in keys
    # the frame's own style is the one picked, and it was not rewritten
    assert composer.style_combo.currentData() == f"style:{names[1]}"
    assert frame.style == f"style:{names[1]}"
    assert keys[0] == "sombreado" and keys[-1] == "vectorial"


def test_list_refills_when_it_opens_and_keeps_the_pick(library, monkeypatch):
    composer = _composer()
    frame = composer.comp.frames[0]
    frame.style = "style:Hidden line"
    _select(composer, frame)
    fired = []
    composer.style_combo.currentIndexChanged.connect(fired.append)
    (name,) = _names(7, 1)
    save_user_style(Style(name=name))
    # open the list without showing a real popup window
    monkeypatch.setattr("PySide6.QtWidgets.QComboBox.showPopup",
                        lambda self: None)
    composer.style_combo.showPopup()
    assert f"style:{name}" in _keys(composer.style_combo)
    assert composer.style_combo.currentData() == "style:Hidden line"
    assert fired == []                       # no spurious frame edit
    assert frame.style == "style:Hidden line"
    # a deleted style leaves the list the next time it opens
    delete_user_style(name)
    composer.style_combo.showPopup()
    assert f"style:{name}" not in _keys(composer.style_combo)


def test_vector_stays_greyed_out_in_perspective_after_a_refill(library):
    composer = _composer()
    frame = composer.comp.frames[0]
    frame.perspective = True
    _select(composer, frame)
    combo = composer.style_combo
    vidx = combo.findData("vectorial")
    assert not combo.model().item(vidx).isEnabled()
    save_user_style(Style(name=_names(3, 1)[0]))
    composer._reload_style_options()
    vidx = combo.findData("vectorial")
    assert not combo.model().item(vidx).isEnabled()
