# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Tape Measure resize: measure two points, type the length that distance
should have, confirm — and the open context scales so it does.

Inside a group or component its content scales about the context's own
origin; at the top level the whole model scales about the world origin,
except the components loaded from an external file, which keep their size
and only move (``Group.source``). See core/resize.py.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.dimension import Dimension
from core.group import Group, copy_group, world_mesh
from core.guide import Guide
from core.history import History
from core.image_plane import ImagePlane
from core.mesh import Mesh
from core.resize import ResizeCommand, resize_anchor, resize_factor
from core.scene import Scene
from core.section import SectionPlane
from core.snap import SnapResult
from core.textlabel import TextLabel
from tools.base import ToolContext
from tools.tape import TapeMeasureTool


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _close(p, q, tol=1e-5):
    return (p - q).length() < tol


def _square(mesh, x0=0.0, y0=0.0, size=1.0, z=0.0):
    return mesh.add_face([V(x0, y0, z), V(x0 + size, y0, z),
                          V(x0 + size, y0 + size, z), V(x0, y0 + size, z)])


def _xs(mesh):
    return sorted({round(v.position.x(), 4) for v in mesh.vertices})


class _Vp:
    """The viewport surface the Tape uses."""

    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.flashes = []

    def update(self):
        pass

    def flash_status(self, text, *a, **k):
        self.flashes.append(text)

    def pick_edge(self, x, y):
        return None

    def pick_guide(self, x, y):
        return None


def _ctx(vp, p, kind="endpoint"):
    snap = SnapResult(p, kind, (0, 0, 0)) if kind else None
    return ToolContext(viewport=vp, world=p, screen=QPointF(0, 0),
                       modifiers=Qt.NoModifier, snap=snap)


def _measure(vp, a, b, answer=True, monkeypatch=None):
    tool = TapeMeasureTool()
    tool.on_activate(vp)
    asked = []

    def confirm(_vp, question):
        asked.append(question)
        return answer
    monkeypatch.setattr(TapeMeasureTool, "_confirm_resize",
                        staticmethod(confirm))
    tool.on_click(_ctx(vp, a))
    tool.on_click(_ctx(vp, b))
    return tool, asked


# ---- The factor ---------------------------------------------------------------

def test_the_factor_turns_the_measured_length_into_the_typed_one():
    assert resize_factor(2.0, 5.0) == 2.5
    assert resize_factor(4.0, 1.0) == 0.25
    assert resize_factor(0.0, 1.0) is None
    assert resize_factor(1.0, 0.0) is None
    assert resize_factor(1.0, -3.0) is None


# ---- The tool -------------------------------------------------------------------

def test_typing_after_a_measurement_resizes_the_model(monkeypatch):
    scene = Scene()
    _square(scene.mesh, 1.0, 0.0, 2.0)                  # x from 1 to 3
    vp = _Vp(scene)
    tool, asked = _measure(vp, V(1, 0), V(3, 0), monkeypatch=monkeypatch)
    assert tool.value_label()[0] and tool.value_label()[1] is None
    assert tool.on_value(vp, 5.0) is True               # 2 m → 5 m: × 2.5
    assert len(asked) == 1 and "model" in asked[0]
    assert "external files" in asked[0]
    assert _xs(scene.mesh) == [2.5, 7.5]                # about the origin
    a, b = tool._measure_ends
    assert abs((b - a).length() - 5.0) < 1e-5           # the new reading
    assert vp.history.undo()
    assert _xs(scene.mesh) == [1.0, 3.0]
    assert vp.history.redo()
    assert _xs(scene.mesh) == [2.5, 7.5]


def test_answering_no_changes_nothing(monkeypatch):
    scene = Scene()
    _square(scene.mesh, 0.0, 0.0, 2.0)
    vp = _Vp(scene)
    tool, asked = _measure(vp, V(0, 0), V(2, 0), answer=False,
                           monkeypatch=monkeypatch)
    assert tool.on_value(vp, 4.0) is True
    assert len(asked) == 1
    assert _xs(scene.mesh) == [0.0, 2.0]
    assert not vp.history.undo_stack


def test_without_a_measurement_a_typed_value_does_nothing(monkeypatch):
    scene = Scene()
    _square(scene.mesh, 0.0, 0.0, 2.0)
    vp = _Vp(scene)
    tool = TapeMeasureTool()
    tool.on_activate(vp)
    monkeypatch.setattr(TapeMeasureTool, "_confirm_resize",
                        staticmethod(lambda *_a: True))
    assert tool.on_value(vp, 4.0) is False
    # Esc after measuring forgets the measurement.
    tool.on_click(_ctx(vp, V(0, 0)))
    tool.on_click(_ctx(vp, V(2, 0)))
    tool.on_cancel(vp)
    assert tool.on_value(vp, 4.0) is False
    assert _xs(scene.mesh) == [0.0, 2.0]


def test_the_same_length_asks_nothing(monkeypatch):
    scene = Scene()
    _square(scene.mesh, 0.0, 0.0, 2.0)
    vp = _Vp(scene)
    tool, asked = _measure(vp, V(0, 0), V(2, 0), monkeypatch=monkeypatch)
    assert tool.on_value(vp, 2.0) is True
    assert not asked and not vp.history.undo_stack


# ---- The model ----------------------------------------------------------------

def test_a_model_resize_takes_every_kind_of_content_along():
    scene = Scene()
    _square(scene.mesh, 1.0, 0.0)
    g = Group(Mesh(), name="g")
    _square(g.mesh, 4.0, 0.0)
    proto = Mesh()
    _square(proto)
    inst = Group(proto, name="inst")
    t = QMatrix4x4()
    t.translate(6.0, 0.0, 0.0)
    inst.xform = t
    scene.groups.extend([g, inst])
    im = ImagePlane("plan.png", V(1, 1), V(2, 0), V(0, 1))
    scene.image_planes.append(im)
    gd = Guide(V(1, 2), V(1, 0))
    pt = Guide(V(3, 3), None, V(1, 1))
    scene.guides.extend([gd, pt])
    sp = SectionPlane(V(0, 0, 1), V(0, 0, 1))
    scene.section_planes.append(sp)
    free = Dimension(V(10, 0), V(12, 0), V(0, 1))
    held = Dimension(V(1, 0), V(2, 0), V(0, -1))
    scene.dimensions.extend([free, held])
    free.bind(scene)
    held.bind(scene)
    assert held.anchored and free.anchor_a is None
    lbl = TextLabel(V(1, 1), V(1, 0), "x")
    scene.text_labels.append(lbl)

    hist = History(scene)
    hist.execute(ResizeCommand(scene, 2.0))
    assert _xs(scene.mesh) == [2.0, 4.0]
    assert _xs(g.mesh) == [8.0, 10.0]
    assert _xs(world_mesh(inst)) == [12.0, 14.0]
    assert _close(im.origin, V(2, 2)) and _close(im.u, V(4, 0))
    assert _close(gd.point, V(2, 4)) and _close(gd.direction, V(1, 0))
    assert _close(pt.point, V(6, 6)) and _close(pt.origin, V(2, 2))
    assert _close(sp.point, V(0, 0, 2))
    assert _close(free.a, V(20, 0)) and _close(free.b, V(24, 0))
    assert _close(free.offset, V(0, 2))
    assert _close(held.a, V(2, 0)) and _close(held.b, V(4, 0))
    assert _close(lbl.anchor, V(2, 2)) and _close(lbl.offset, V(2, 0))

    assert hist.undo()
    assert _xs(scene.mesh) == [1.0, 2.0] and _xs(g.mesh) == [4.0, 5.0]
    assert _xs(world_mesh(inst)) == [6.0, 7.0]
    assert _close(im.origin, V(1, 1)) and _close(im.u, V(2, 0))
    assert _close(pt.origin, V(1, 1)) and _close(sp.point, V(0, 0, 1))
    assert _close(free.a, V(10, 0)) and _close(held.b, V(2, 0))
    assert _close(lbl.anchor, V(1, 1)) and _close(lbl.offset, V(1, 0))


def test_a_component_from_an_external_file_keeps_its_size_and_moves():
    scene = Scene()
    _square(scene.mesh, 0.0, 0.0, 2.0)
    proto = Mesh()
    _square(proto, size=0.5)                            # a 50 cm chair
    chair = Group(proto, name="chair")
    t = QMatrix4x4()
    t.translate(3.0, 0.0, 0.0)
    chair.xform = t
    chair.source = "chair.igz"
    lamp = Group(Mesh(), name="lamp")                   # a classic group
    _square(lamp.mesh, 4.0, 0.0, 0.5)
    lamp.source = "lamp.obj"
    scene.groups.extend([chair, lamp])
    hist = History(scene)
    hist.execute(ResizeCommand(scene, 2.0))
    assert _xs(scene.mesh) == [0.0, 4.0]
    assert _xs(world_mesh(chair)) == [6.0, 6.5]         # origin 3 → 6
    # The classic one's base centre (4.25, 0.25) goes to (8.5, 0.5).
    assert _xs(lamp.mesh) == [8.25, 8.75]
    assert hist.undo()
    assert _xs(world_mesh(chair)) == [3.0, 3.5]
    assert _xs(lamp.mesh) == [4.0, 4.5]


def test_the_registry_finds_every_vertex_after_a_resize():
    """Vertices walked one at a time land on spots their neighbours have
    not left yet (×2 sends x=1 onto x=2): the position registry must
    still find each one where it now stands."""
    scene = Scene()
    for i in range(4):
        scene.mesh.add_edge(V(i, 0), V(i + 1, 0))
    History(scene).execute(ResizeCommand(scene, 2.0))
    for v in scene.mesh.vertices:
        assert scene.mesh.vertex_at(v.position) is v
    assert _xs(scene.mesh) == [0.0, 2.0, 4.0, 6.0, 8.0]


# ---- Inside a group or component --------------------------------------------

def test_inside_a_group_only_the_group_scales_about_its_corner(monkeypatch):
    scene = Scene()
    _square(scene.mesh, 0.0, 0.0)                       # stays as it is
    g = Group(Mesh(), name="g")
    _square(g.mesh, 5.0, 0.0, 2.0)
    scene.groups.append(g)
    scene.begin_group_edit(g)
    assert _close(resize_anchor(scene), V(5, 0))        # its lowest corner
    vp = _Vp(scene)
    tool, asked = _measure(vp, V(5, 0), V(7, 0), monkeypatch=monkeypatch)
    tool.on_value(vp, 3.0)
    assert "active group" in asked[0]
    assert _xs(g.mesh) == [5.0, 8.0]                    # grew in place
    scene.end_group_edit()
    assert _xs(scene.mesh) == [0.0, 1.0]


def test_inside_a_component_every_copy_takes_the_resize(monkeypatch):
    scene = Scene()
    proto = Mesh()
    _square(proto, size=2.0)
    a, b = Group(proto, name="a"), Group(proto, name="b")
    t = QMatrix4x4()
    t.translate(10.0, 0.0, 0.0)
    a.xform, b.xform = QMatrix4x4(), t
    scene.groups.extend([a, b])
    scene.begin_group_edit(b)
    assert _close(resize_anchor(scene), V(10, 0))       # its origin
    vp = _Vp(scene)
    tool, asked = _measure(vp, V(10, 0), V(12, 0), monkeypatch=monkeypatch)
    tool.on_value(vp, 1.0)
    assert "active component" in asked[0]
    scene.end_group_edit()
    assert _xs(proto) == [0.0, 1.0]                     # the definition
    assert _xs(world_mesh(a)) == [0.0, 1.0]
    assert _xs(world_mesh(b)) == [10.0, 11.0]


def test_inside_a_turned_group_it_scales_about_the_group_origin():
    scene = Scene()
    g = Group(Mesh(), name="g")
    _square(g.mesh, 2.0, 2.0, 2.0)
    axes = QMatrix4x4()
    axes.translate(1.0, 1.0, 0.0)
    g.axes = axes                                       # origin at (1, 1)
    scene.groups.append(g)
    scene.begin_group_edit(g)
    assert _close(resize_anchor(scene), V(1, 1))
    History(scene).execute(ResizeCommand(scene, 2.0))
    assert _xs(g.mesh) == [3.0, 7.0]


# ---- Where the flag comes from and goes --------------------------------------

def test_the_source_rides_along_on_copies_and_through_the_file(tmp_path):
    from formats import igz
    scene = Scene()
    proto = Mesh()
    _square(proto)
    comp = Group(proto, name="pergola")
    comp.xform = QMatrix4x4()
    comp.source = "pergola.igz"
    plain = Group(proto, name="mine")
    plain.xform = QMatrix4x4()
    scene.groups.extend([comp, plain])
    assert copy_group(comp).source == "pergola.igz"
    assert copy_group(plain).source is None
    path = tmp_path / "doc.igz"
    igz.save_scene(scene, path)
    back = Scene()
    igz.load_into(back, path)
    by_name = {g.name: g for g in back.groups}
    assert by_name["pergola"].source == "pergola.igz"
    assert by_name["mine"].source is None


# ---- The status bar ----------------------------------------------------------

def test_the_hint_offers_the_resize_once_measured(monkeypatch):
    from views.status_hints import hint_for
    scene = Scene()
    vp = _Vp(scene)
    tool, _asked = _measure(vp, V(0, 0), V(2, 0), monkeypatch=monkeypatch)
    text = hint_for("tape", tool, None, "all")
    assert "resize" in text and "Ctrl" in text
    tool.on_cancel(vp)
    assert "resize" not in hint_for("tape", tool, None, "all")


def test_the_resize_hint_fits_the_bar_in_every_language(monkeypatch):
    """The same character budget as test_status_hints_fit, which only
    drives the tools' plain started phase, not this one."""
    from core.i18n import available_languages, set_language
    from views.status_hints import hint_for
    vp = _Vp(Scene())
    tool, _asked = _measure(vp, V(0, 0), V(2, 0), monkeypatch=monkeypatch)
    try:
        for lang in available_languages():
            set_language(lang)
            text = hint_for("tape", tool, None, "parallel_perp")
            assert len(text) <= 112, f"{lang}: {text}"
    finally:
        set_language("en")
