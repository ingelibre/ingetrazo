# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Continuous line types of the document's own, and «Duplicate…» (#1465).

A line type's colour belongs to the line type, so every layer on «Continuous»
shared one colour: a black continuous line on one layer and a blue one on
another could not be had. The editor refused a line with no gap, and the
nearest one (1000, -0.05) left a tiny break every metre. Now a line type of
the document's own may be continuous — empty pieces, or drawn pieces only —
and any line type can be duplicated to give the copy a colour of its own."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])

from core import layers as L
from core.group import Group
from core.layers import Layer
from core.mesh import Mesh
from core.scene import Scene

V = QVector3D
BLACK = (0.0, 0.0, 0.0)
BLUE = (0.0, 0.40, 0.85)


def _square(mesh, x0=0.0):
    return mesh.add_face([V(x0, 0, 0), V(x0 + 1, 0, 0),
                          V(x0 + 1, 1, 0), V(x0, 1, 0)])


def _two_continuous_scene():
    """Two layers, each on a continuous line of the document's own: one
    black, one blue — the case of the issue."""
    scene = Scene()
    L.load_line_types(scene, {
        "Continua negra": {"pattern": [], "color": list(BLACK)},
        "Continua azul": {"pattern": [], "pieces": [], "color": list(BLUE)}})
    scene.layers += [Layer("Capa 0", linetype="lin:Continua negra"),
                     Layer("Capa 1", linetype="lin:Continua azul")]
    for i, name in enumerate(("Capa 0", "Capa 1")):
        g = Group(Mesh(), name=name)
        _square(g.mesh, x0=3.0 * i)
        g.layer = name
        scene.groups.append(g)
    return scene


def _top_camera(scene):
    from core.camera import OrbitCamera
    from core.composition import MarcoVista, apply_frame_camera
    cam = OrbitCamera()
    f = MarcoVista(view_key="std:top", scale_n=100.0, w_mm=100.0, h_mm=100.0)
    apply_frame_camera(cam, f, saved_view=None, scene=scene)
    return cam


# ---- The core ---------------------------------------------------------------

@pytest.mark.parametrize("raw", [[], [5], [5, 0, 2]])
def test_a_line_with_no_gap_is_a_continuous_line_of_its_own(raw):
    assert L.clean_pattern(raw, continuous=True) == []
    # A built-in pattern or a .lin file still needs a dash and a gap.
    assert L.clean_pattern(raw) is None


def test_all_gap_or_bad_numbers_are_never_a_line():
    assert L.clean_pattern([-2, -1], continuous=True) is None
    assert L.clean_pattern([float("nan")], continuous=True) is None
    assert L.clean_pattern([5000], continuous=True) is None
    assert L.clean_pattern("5", continuous=True) is None
    # A dashed one is as before.
    assert L.clean_pattern([6, -1.5], continuous=True) == [6.0, -1.5]


def test_two_continuous_layers_ink_each_in_its_own_colour():
    scene = _two_continuous_scene()
    assert set(scene.line_types) == {"Continua negra", "Continua azul"}
    st = L.line_styles(scene, colored=False)
    assert st["Capa 0"][0] == BLACK and st["Capa 1"][0] == BLUE
    # Drawn solid: no dashes, no text — as the built-in Continuous.
    assert st["Capa 0"][4] == () and st["Capa 1"][4] == ()
    assert st["Capa 0"][5] is None
    # The model draws them in their colours, solid.
    model = L.model_line_styles(scene)
    assert model["Capa 0"] == (BLACK, ()) and model["Capa 1"] == (BLUE, ())
    # The legend shows a solid line.
    assert L.layer_swatch(scene, scene.layer("Capa 1"))["pattern"] == []


def test_a_continuous_line_of_its_own_is_saved_and_read_back(tmp_path):
    from formats import igz
    scene = _two_continuous_scene()
    path = tmp_path / "continuas.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    assert back.line_types["Continua azul"]["pattern"] == []
    assert tuple(back.line_types["Continua azul"]["color"]) == BLUE
    assert back.layer("Capa 1").linetype == "lin:Continua azul"
    assert L.line_styles(back, False)["Capa 1"][0] == BLUE


def test_a_template_carries_the_continuous_line_of_its_own():
    src = _two_continuous_scene()
    data = L.template_of(src)
    dst = Scene()
    L.apply_template(dst, data)
    assert dst.line_types["Continua azul"]["pattern"] == []
    assert dst.layer("Capa 1").linetype == "lin:Continua azul"


def test_words_on_a_continuous_line_break_it_only_for_them():
    drawn, spec = L.with_text([], "GAS", 2.5)
    assert drawn[0] == L.CONTINUOUS_TEXT_RUN and drawn[1] < 0
    assert spec is not None and spec["text_at"] == 1
    assert L.clean_pattern(drawn, continuous=True) == drawn


def test_the_dxf_writes_a_continuous_line_of_its_own_as_continuous(tmp_path):
    from core.hlr import hlr_drawing
    from formats.dxf_out import save_dxf_layers
    from views.composer import dxf_groups_by_layer
    scene = _two_continuous_scene()
    d = hlr_drawing(scene, _top_camera(scene), profiles=False, layers=True)
    d.styles = L.line_styles(scene, colored=False)
    path = tmp_path / "continuas.dxf"
    save_dxf_layers(path, dxf_groups_by_layer(d, "PLANTA",
                                              hidden_lines=False))
    text = path.read_text(encoding="ascii")
    import re
    # Each layer on CONTINUOUS, in its own colour (blue is not black's 7).
    found = dict(re.findall(r"0\nLAYER\n2\n(CAPA_[01]|Capa [01]|[^\n]*)\n"
                            r"70\n0\n62\n\d+\n6\n([^\n]+)\n", text))
    assert found and set(found.values()) == {"CONTINUOUS"}
    # No layer points at a line type the file does not declare.
    assert "CONTINUA_AZUL" not in text and "CONTINUA_NEGRA" not in text


# ---- The editor ---------------------------------------------------------------

def test_the_editor_takes_empty_pieces_as_a_continuous_line():
    from PySide6.QtWidgets import QDialogButtonBox
    from views.layers_panel import LineTypeDialog
    dlg = LineTypeDialog(None, name="Continua azul", pattern=[6, -1.5])
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    dlg.pattern_edit.setText("")
    assert ok.isEnabled() and dlg.result_pattern() == []
    assert dlg.problem.text() == "A continuous line, with no gaps"
    dlg.pattern_edit.setText("5")                  # drawn only: continuous
    assert ok.isEnabled() and dlg.result_pattern() == []
    dlg.pattern_edit.setText("-5, -2")             # all gap: refused
    assert not ok.isEnabled() and dlg.result_pattern() is None
    assert "at least one piece drawn" in dlg.problem.text()
    dlg.pattern_edit.setText("6, -1.5")
    assert ok.isEnabled() and not dlg.problem.text()


def test_editing_a_continuous_line_shows_it_empty_not_the_default():
    from views.layers_panel import LineTypeDialog
    dlg = LineTypeDialog(None, name="Continua azul", pattern=[],
                         editing=True, color=BLUE)
    assert dlg.pattern_edit.text() == ""
    assert dlg.result_pattern() == []
    # A new line type still starts from an example pattern.
    assert LineTypeDialog(None).pattern_edit.text() == "6, -1.5, 0, -1.5"


# ---- The panel ----------------------------------------------------------------

@pytest.fixture
def win():
    from PySide6.QtCore import QSettings
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    _app.processEvents()
    yield w
    w._saved_version = w.viewport.scene.version
    w.close()
    QSettings().remove("ui/window_state")      # see test_layers_panel.win
    QSettings().remove("ui/window_geometry")


def _answer_dialog(monkeypatch, colour=None, name=None):
    """The line type editor answers OK at once — with ``colour`` picked and
    ``name`` typed, if given; returns what it was opened with."""
    from views.layers_panel import LineTypeDialog
    seen = {}

    def exec_(self):
        seen["name"] = self.name()
        seen["pieces"] = self.pattern_edit.text()
        seen["colour"] = self.result_color()
        if colour is not None:
            self._colour = colour
        if name is not None:
            self.name_edit.setText(name)
        return True
    monkeypatch.setattr(LineTypeDialog, "exec", exec_)
    return seen


def test_the_panel_adds_a_continuous_line_of_its_own(win):
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A"))
    key = panel.add_line_type("Continua azul", [], ["A"], color=BLUE)
    assert key == "lin:Continua azul"
    assert scene.line_types["Continua azul"]["pattern"] == []
    assert scene.layer("A").linetype == key
    assert L.line_styles(scene, False)["A"][0] == BLUE


def test_duplicating_continuous_gives_the_layer_a_blue_one(win, monkeypatch):
    """The issue: Layer 0 continuous in black, Layer 1 continuous in blue."""
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers += [Layer("Capa 0"), Layer("Capa 1")]
    panel.set_linetype_colour("continuous", BLACK)
    seen = _answer_dialog(monkeypatch, colour=BLUE)
    panel.duplicate_line_type("continuous", ["Capa 1"])
    # Opened as a copy: a free name, no pieces, the original's colour.
    assert seen == {"name": "Continuous 2", "pieces": "", "colour": BLACK}
    assert scene.layer("Capa 1").linetype == "lin:Continuous 2"
    assert scene.line_types["Continuous 2"]["pattern"] == []
    st = L.line_styles(scene, colored=False)
    assert st["Capa 0"][0] == BLACK and st["Capa 1"][0] == BLUE
    assert scene.layer("Capa 0").linetype == "continuous"
    # Again: the next free name.
    _answer_dialog(monkeypatch)
    panel.duplicate_line_type("continuous", ())
    assert "Continuous 3" in scene.line_types


def test_duplicating_a_dashed_or_own_line_copies_its_pieces(win,
                                                            monkeypatch):
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A"))
    seen = _answer_dialog(monkeypatch)
    panel.duplicate_line_type("dashdot", ["A"])
    assert seen["pieces"] == "6, -1.5, 0.5, -1.5"
    assert L.linetype_pattern("lin:Dash dot 2", scene) == \
        L.LINETYPES["dashdot"] or scene.layer("A").linetype.startswith("lin:")
    assert L.linetype_pattern(scene.layer("A").linetype, scene) == \
        L.LINETYPES["dashdot"]
    panel.add_line_type("Gas", [8, -2], (), "GAS", 2.0, color=(0.85, 0.65, 0))
    seen = _answer_dialog(monkeypatch)
    panel.duplicate_line_type("lin:Gas", ["A"])
    assert seen["name"] == "Gas 2" and seen["pieces"] == "8, -2"
    copy = scene.line_types["Gas 2"]
    assert copy["text"] == "GAS" and tuple(copy["color"]) == (0.85, 0.65, 0)
    assert scene.layer("A").linetype == "lin:Gas 2"


def test_a_cancelled_duplicate_changes_nothing(win, monkeypatch):
    from views.layers_panel import LineTypeDialog
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A"))
    monkeypatch.setattr(LineTypeDialog, "exec", lambda self: False)
    panel.duplicate_line_type("continuous", ["A"])
    assert not scene.line_types and scene.layer("A").linetype == "continuous"


def test_every_line_type_offers_duplicate_on_a_right_click(win):
    from PySide6.QtWidgets import QMenu
    from views.layers_panel import _LineSample
    panel = win.layers_dock.panel
    scene = win.viewport.scene
    scene.layers.append(Layer("A"))
    panel.add_line_type("Gas", [8, -2], ())
    for picker in (False, True):
        menu = QMenu()
        panel._fill_linetypes(menu, ["A"], scene.layer("A"), picker=picker)
        samples = {s.key: s for s in menu.findChildren(_LineSample)}
        for key in ("continuous", "dashed", "lin:Gas"):
            labels = [label for label, _cb in samples[key].actions]
            assert "Duplicate…" in labels, (key, labels)


def test_the_continuous_button_makes_a_continuous_line():
    """The editor's «Continuous» (it was «Clear»): empty pieces are a
    continuous line, so the button that empties them is named for it."""
    from PySide6.QtWidgets import QDialogButtonBox, QPushButton
    from views.layers_panel import LineTypeDialog
    dlg = LineTypeDialog(None, name="Continua azul", pattern=[6, -1.5])
    texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "Continuous" in texts and "Clear" not in texts
    assert dlg.continuous_button.toolTip()
    dlg.continuous_button.click()
    assert dlg.pattern_edit.text() == "" and dlg.result_pattern() == []
    assert dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert dlg.problem.text() == "A continuous line, with no gaps"
    # A pattern typed after it is dashed again.
    dlg.pattern_edit.setText("3, -1.5")
    assert dlg.result_pattern() == [3.0, -1.5]


def test_the_button_reads_in_spanish():
    import json
    from core.i18n import _I18N_DIR
    es = json.loads((_I18N_DIR / "es.json").read_text(encoding="utf-8"))
    assert es["Continuous"] == "Continua"
    assert es["A continuous line, with no gaps (empties the pieces)"]
