# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Dynamic components: attributes and formulas on a component (core/dynamic).

A window whose leaf follows ``parent!lenx``: typing a new width in its
options redraws it as one undo step, keeps its identity, and the hole it
cut in the wall is made again at the new size — the component never
moved, only what it holds changed. The data is the attribute layout of
.skp dynamic components, so one brought from a .skp file is edited the
same way. All data here is synthetic."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402

from core import openings  # noqa: E402
from core.dynamic import KEY  # noqa: E402
from core.dynamic import apply as A  # noqa: E402
from core.dynamic import formula as F  # noqa: E402
from core.dynamic import options as O  # noqa: E402
from core.dynamic.document import (SwapGroupCommand, is_dynamic,  # noqa: E402
                                   redraw_in_document, selected_one)
from core.dynamic.messages import Msg, tr_msg  # noqa: E402
from core.group import Group  # noqa: E402
from core.history import History, InsertGroupCommand  # noqa: E402
from core.orient import orient_outward  # noqa: E402
from core.scene import Scene  # noqa: E402

IN = 0.0254          # the stored lengths are inches
ROOT = Path(__file__).resolve().parents[1]

#: A window on the wall's front (y = 0): red along the wall, green up,
#: blue out of the wall.
_ON_FRONT = QMatrix4x4(1, 0, 0, 0,
                       0, 0, -1, 0,
                       0, 1, 0, 0,
                       0, 0, 0, 1)


def _wall(mesh, length=4.0, thick=0.2, height=2.5):
    p = [V(0, 0, 0), V(length, 0, 0), V(length, thick, 0), V(0, thick, 0)]
    q = [V(x.x(), x.y(), height) for x in p]
    mesh.add_face(p)
    mesh.add_face(q)
    for i in range(4):
        j = (i + 1) % 4
        mesh.add_face([p[i], p[j], q[j], q[i]])
    orient_outward(mesh)


def _data(name, **attrs):
    inst = {"_name": name}
    inst.update(attrs)
    return {"definition": name, "definition_attributes": {},
            "instance_attributes": inst}


def _window(w=1.0, h=1.2, x=1.0, z=0.9, cut=True, copies=None):
    """A dynamic window: the root offers its width (LenX, a text box) and a
    number of leaves; the frame follows the root's size; between leaves
    stands a mullion, copied along it (none for a single leaf)."""
    root = Group(name="Ventana")
    root.component = True
    frame = Group(name="Marco")
    frame.component = True
    outer = [V(0, 0, 0), V(w, 0, 0), V(w, h, 0), V(0, h, 0)]
    inner = [V(.05, .05, 0), V(w - .05, .05, 0), V(w - .05, h - .05, 0),
             V(.05, h - .05, 0)]
    frame.mesh.add_face(outer, [inner])
    frame.xform = QMatrix4x4()
    frame.ext = {KEY: _data("Marco", _lengthunits="CENTIMETERS",
                            _lenx_formula="parent!lenx",
                            _leny_formula="parent!leny")}
    mullion = Group(name="Parteluz")
    mullion.component = True
    mullion.mesh.add_face([V(0, 0, -.02), V(.04, 0, -.02), V(.04, h, -.02),
                           V(0, h, -.02)])
    mullion.xform = QMatrix4x4()
    mullion.ext = {KEY: _data(
        "Parteluz", _lengthunits="CENTIMETERS",
        _copies_formula="MAX(parent!hojas-2, 0)",
        _hidden_formula="parent!hojas<2",
        _x_formula="parent!lenx/parent!hojas*(copy+1)")}
    root.adopt([frame, mullion])
    t = QMatrix4x4()
    t.translate(x, 0, z)
    root.xform = t * _ON_FRONT
    attrs = dict(_lengthunits="CENTIMETERS", lenx=w / IN, leny=h / IN,
                 _lenx_nominal=w / IN, _leny_nominal=h / IN,
                 _lenx_access="TEXTBOX", _lenx_label="LenX",
                 _lenx_formlabel="Ancho",
                 hojas=2.0, _hojas_access="LIST", _hojas_formlabel="Hojas",
                 _hojas_options="&1=1&2=2&3=3&", _hojas_units="INTEGER")
    if copies is not None:
        attrs["hojas"] = float(copies)
    root.ext = {KEY: _data("Ventana", **attrs)}
    if cut:
        openings.set_ext_entry(root, {"on": True})
    return root


def _xs(mesh):
    return sorted({round(v.position.x(), 3) for v in mesh.vertices})


def _state(mesh):
    r = lambda p: (round(p.x(), 4), round(p.y(), 4), round(p.z(), 4))  # noqa: E731
    return sorted((tuple(sorted(r(p) for p in f.vertices)), len(f.hole_loops))
                  for f in mesh.faces)


@pytest.fixture
def model():
    scene = Scene()
    _wall(scene.mesh)
    history = History(scene)
    win = _window()
    history.execute(InsertGroupCommand(win))
    scene.selection.clear()
    return scene, history, win


class _Viewport:
    """What the redraw needs of a viewport: the scene and its history."""

    def __init__(self, scene, history) -> None:
        self.scene = scene
        self.history = history
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


# ---- The formula language ------------------------------------------------------
def _ev(text, values=None):
    values = values or {}
    return F.evaluate(F.parse(text), lambda node, attr: values[(node, attr)])


def test_formulas_compute_like_a_spreadsheet():
    assert _ev("=2+3*4") == 14.0
    assert _ev("(2+3)*4") == 20.0
    assert _ev("IF(ancho>100, 2, 1)", {("self", "ancho"): 120.0}) == 2.0
    assert _ev("parent!lenx - 2*marco",
               {("parent", "lenx"): 100.0, ("self", "marco"): 5.0}) == 90.0
    assert _ev("ROUND(10/3, 2)") == 3.33
    assert _ev('"Hoja " & 2') == "Hoja 2"
    assert _ev("CHOOSE(2, 10, 20, 30)") == 20.0


def test_a_formula_cannot_run_code():
    """Formulas come from files we did not write: no eval, no names out of
    the attribute space, no attribute access, bounded work."""
    for text in ("__import__('os').system('x')", "().__class__",
                 "open('x')", "1;2"):
        with pytest.raises(F.FormulaError):
            _ev(text)
    with pytest.raises(F.FormulaError):
        _ev("+".join(["1"] * 3000))          # too long


def test_formula_errors_are_translatable_messages():
    with pytest.raises(F.FormulaError) as info:
        _ev("1/0")
    assert isinstance(info.value.msg, Msg)
    assert tr_msg(info.value.msg) == "Division by zero"


# ---- Redraw ---------------------------------------------------------------------
def test_the_options_are_the_ones_the_author_exposed():
    names = [o.name for o in O.options_of(A.part_tree(_window()).attrs)]
    assert names == ["lenx", "hojas"]


def test_a_wider_window_stretches_its_frame_and_keeps_its_identity():
    win = _window()
    new, ev = A.redraw_group(win, {"lenx": 1.5 / IN})
    assert not ev.errors
    assert new.uid == win.uid
    fp = openings.footprint(new)
    assert sorted({round(p.x(), 3) for p in fp}) == [1.0, 2.5]
    # The root keeps its place in the world; the length is in its options.
    data = new.ext[KEY]["instance_attributes"]
    assert data["lenx"] == pytest.approx(1.5 / IN)


def _mullions(group):
    return [(c.name, round(c.xform.map(V(0, 0, 0)).x(), 3), c.hidden)
            for c in group.children if c.name.startswith("Parteluz")]


def test_copies_and_visibility_follow_formulas():
    new, ev = A.redraw_group(_window(copies=3), {})
    assert not ev.errors
    # Three leaves: two mullions, at a third and two thirds of 1 m.
    assert _mullions(new) == [("Parteluz", 0.333, False),
                              ("Parteluz copy 001", 0.667, False)]
    # Back to two leaves: the copy goes.
    again, _e = A.redraw_group(new, {"hojas": 2.0})
    assert _mullions(again) == [("Parteluz", 0.5, False)]
    # One leaf: no mullion to show.
    one, _e = A.redraw_group(again, {"hojas": 1.0})
    assert [m[2] for m in _mullions(one)] == [True]


def test_a_failing_formula_keeps_the_value_it_had():
    win = _window()
    win.children[0].ext[KEY]["instance_attributes"]["_lenx_formula"] = "1/0"
    new, ev = A.redraw_group(win, {})
    assert ev.errors and "Division by zero" in ev.errors[0][3]
    assert sorted({round(p.x(), 3) for p in openings.footprint(new)}) == [1.0, 2.0]


def test_a_part_of_a_skp_file_reads_its_formulas_in_its_own_units():
    """A .skp component stores lengths in inches and writes its formulas
    in its ``_lengthunits``: «parent!lenx - 10» in a CENTIMETERS part is
    10 cm less than its parent."""
    win = _window()
    win.children[0].ext[KEY]["instance_attributes"]["_lenx_formula"] = \
        "parent!lenx - 10"
    new, _ev_ = A.redraw_group(win, {})
    xs = sorted({round(v.position.x(), 3) for v in new.children[0].mesh.vertices})
    frame = new.children[0].xform
    width = frame.map(V(xs[-1], 0, 0)).x() - frame.map(V(xs[0], 0, 0)).x()
    assert width == pytest.approx(0.9, abs=1e-4)


def test_make_dynamic_puts_its_axes_at_the_lower_corner():
    g = Group(name="Caja")
    g.mesh.add_face([V(2, 3, 1), V(3, 3, 1), V(3, 4, 1), V(2, 4, 1)])
    new = A.make_dynamic_tree(g, "Caja")
    assert is_dynamic(new)
    assert new.xform.map(V(0, 0, 0)).toTuple() == pytest.approx((2, 3, 1))
    assert min(v.position.x() for v in new.mesh.vertices) == pytest.approx(0)


# ---- In the document: one undo step, the hole follows --------------------------
def test_redraw_is_one_undo_step_and_the_hole_follows_the_new_width(model):
    scene, history, win = model
    assert _xs(scene.mesh) == [0.0, 1.0, 2.0, 4.0]          # 1 m hole
    before = _state(scene.mesh)
    scene.selection.add(win)
    vp = _Viewport(scene, history)
    new, problems = redraw_in_document(vp, win, {"lenx": 1.5 / IN})
    assert not problems
    assert new in scene.groups and win not in scene.groups
    assert new in scene.selection and win not in scene.selection
    assert _xs(scene.mesh) == [0.0, 1.0, 2.5, 4.0]          # 1.5 m hole
    assert all(len(e.faces) == 2 for e in scene.mesh.edges)
    history.undo()
    assert win in scene.groups and new not in scene.groups
    assert _state(scene.mesh) == before
    history.redo()
    assert new in scene.groups
    assert _xs(scene.mesh) == [0.0, 1.0, 2.5, 4.0]


def test_a_hole_follows_contents_that_change_without_moving(model):
    """The fix in core/openings.py: before it, only a moved component
    remade its hole; one whose parts changed size kept the old hole."""
    scene, history, win = model
    new, _ev_ = A.redraw_group(win, {"lenx": 2.0 / IN})
    history.execute(SwapGroupCommand(win, lambda _s: new))
    assert _xs(scene.mesh) == [0.0, 1.0, 3.0, 4.0]


def test_an_old_record_without_a_footprint_is_left_alone(model):
    """A file saved before footprints were recorded: nothing to compare,
    no hole made again on the next command."""
    scene, history, win = model
    rec = openings.made(win)
    rec.pop("fp", None)
    assert not openings.pending(scene, openings.records(scene))


def test_selected_one_is_the_one_dynamic_component_of_the_context(model):
    scene, _history, win = model
    plain = Group(name="Caja")
    scene.groups.append(plain)
    assert selected_one(scene) is None
    scene.selection.add(plain)
    assert selected_one(scene) is None
    assert selected_one(scene, dynamic_only=False) is plain
    scene.selection.add(win)
    assert selected_one(scene) is win
    assert selected_one(scene, dynamic_only=False) is None    # two


# ---- The panel ----------------------------------------------------------------
@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Window:
    def __init__(self, viewport) -> None:
        self.viewport = viewport


def test_the_options_panel_redraws_the_selected_component(qapp, model):
    from PySide6.QtWidgets import QComboBox, QLineEdit
    from views.dynamic_panel import ComponentOptionsPanel
    scene, history, win = model
    panel = ComponentOptionsPanel(_Window(_Viewport(scene, history)))
    panel.refresh()
    assert panel.group is None and not panel.apply_btn.isEnabled()
    scene.selection.add(win)
    panel.refresh()
    assert panel.group is win
    widgets = {opt.name: w for opt, w, _i in panel.rows}
    assert isinstance(widgets["lenx"], QLineEdit)
    assert widgets["lenx"].text() == "100 cm"
    assert isinstance(widgets["hojas"], QComboBox)
    widgets["lenx"].setText("150 cm")
    panel.apply()
    assert panel.group is not win and panel.group.uid == win.uid
    assert _xs(scene.mesh) == [0.0, 1.0, 2.5, 4.0]
    assert {o.name: w for o, w, _i in panel.rows}["lenx"].text() == "150 cm"


def test_the_options_panel_says_when_a_number_does_not_read(qapp, model):
    from views.dynamic_panel import ComponentOptionsPanel
    scene, history, win = model
    scene.selection.add(win)
    panel = ComponentOptionsPanel(_Window(_Viewport(scene, history)))
    panel.refresh()
    {o.name: w for o, w, _i in panel.rows}["lenx"].setText("ancho")
    panel.apply()
    assert panel.group is win                     # nothing redrawn
    assert "ancho" in panel.status.text()


def test_revert_goes_back_to_the_values_it_had_when_selected(qapp, model):
    """Revert first drops what was typed; once applied (Enter applies),
    it goes back to the options the component had when it was selected —
    one more undo step — and says so when there is nothing to undo."""
    from views.dynamic_panel import ComponentOptionsPanel
    scene, history, win = model
    scene.selection.add(win)
    panel = ComponentOptionsPanel(_Window(_Viewport(scene, history)))
    panel.refresh()

    def field(name):
        return {o.name: w for o, w, _i in panel.rows}[name]

    field("lenx").setText("170 cm")
    panel.revert()                                   # typed, not applied
    assert field("lenx").text() == "100 cm"
    assert _xs(scene.mesh) == [0.0, 1.0, 2.0, 4.0]
    field("lenx").setText("150 cm")
    panel.apply()
    field("hojas").setCurrentIndex(2)
    panel.apply()
    assert _xs(scene.mesh) == [0.0, 1.0, 2.5, 4.0]
    panel.revert()                                   # applied: back to 100 cm, 2 leaves
    assert field("lenx").text() == "100 cm"
    assert field("hojas").currentText() == "2"
    assert _xs(scene.mesh) == [0.0, 1.0, 2.0, 4.0]
    assert panel.group.uid == win.uid
    panel.revert()
    assert "Nothing to revert" in panel.status.text()
    history.undo()                                   # the revert was one step
    assert _xs(scene.mesh) == [0.0, 1.0, 2.5, 4.0]


def test_the_attributes_window_writes_a_formula(qapp, model):
    from views.dynamic_panel import AttributesDialog
    scene, history, win = model
    scene.selection.add(win)
    dlg = AttributesDialog(_Window(_Viewport(scene, history)))
    dlg.show_root(win, (0,))                       # the frame
    names = [dlg.table.item(r, 0).data(0x0100) for r in range(dlg.table.rowCount())]
    assert "lenx" in names
    row = names.index("lenx")
    dlg.table.item(row, 1).setText("=parent!lenx - 20")
    root = dlg.root
    assert root is not win and root.uid == win.uid
    frame = root.children[0].ext[KEY]["instance_attributes"]
    assert frame["_lenx_formula"] == "parent!lenx - 20"
    history.undo()
    assert win in scene.groups


# ---- Every new message is translated ----------------------------------------------
def _messages():
    src = (ROOT / "views/dynamic_panel.py").read_text(encoding="utf-8")
    pat = r'\btr\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)'
    out = {"".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)))
           for m in re.finditer(pat, src)}
    for f in (ROOT / "core/dynamic").glob("*.py"):
        t = f.read_text(encoding="utf-8")
        for fn in ("Msg", "N_"):
            for m in re.finditer(r'\b' + fn + r'\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', t):
                out.add("".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))))
    out.discard("Copy {index}: {error}")          # a docstring's example
    return sorted(s for s in out if s)


@pytest.mark.parametrize("lang", sorted(p.stem for p in (ROOT / "i18n").glob("*.json")
                                        if p.stem != "en"))
def test_every_message_is_translated(lang):
    data = json.loads((ROOT / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
    missing = [m for m in _messages() if m not in data]
    assert not missing, f"{len(missing)} missing in {lang}: {missing[:3]}"


def test_properties_shows_the_options_of_the_selected_component(qapp):
    """In the real window: Properties ▸ Component options follows the
    selection, and Apply redraws the component in the document."""
    from views.main_window import MainWindow
    w = MainWindow()
    w.show()
    try:
        vp = w.viewport
        scene = vp.scene
        _wall(scene.mesh)
        win = _window()
        vp.history.execute(InsertGroupCommand(win))
        scene.selection.clear()
        scene.selection.add(win)
        panel = w.tray.component_options
        w.tray.on_scene_changed()
        assert panel.group is win
        {o.name: x for o, x, _i in panel.rows}["lenx"].setText("130 cm")
        panel.apply()
        new = panel.group
        assert new is not win and new in scene.groups
        assert sorted({round(p.x(), 3) for p in openings.footprint(new)}) == [1.0, 2.3]
        vp.history.undo()
        assert win in scene.groups
    finally:
        w._saved_version = w.viewport.scene.version
        w.close()
