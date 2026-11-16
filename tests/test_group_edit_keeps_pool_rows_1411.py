# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An edit inside one group keeps the instanced rows of its siblings (#1411).

The plaza's planting is ONE top-level object holding 2 843 placements. The
instanced pool kept the rows of the top-level objects an edit did not touch,
but a paint, a stroke or a hide on one small group inside the planting made
all 2 843 rows again — the first frame after every edit stalled. The pool
now keeps the row of every placement whose own part and whose containers'
parts read the same. Each kept pool is compared, row by row, with one made
afresh, after every step of a long series of edits and their undo."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _box(s=1.0):
    from core.mesh import Mesh
    m = Mesh()
    p = [V(0, 0, 0), V(s, 0, 0), V(s, s, 0), V(0, s, 0),
         V(0, 0, s), V(s, 0, s), V(s, s, s), V(0, s, s)]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7)):
        m.add_face([p[i] for i in q])
    return m


def _placed(mesh, name, x, y, turn=0.0):
    from core.group import Group
    g = Group(mesh, name=name)
    xf = QMatrix4x4()
    xf.translate(x, y, 0.0)
    xf.rotate(turn, 0.0, 0.0, 1.0)
    g.xform = xf
    return g


@pytest.fixture
def vp():
    """A planting (one top-level object) of six beds, each holding four
    copies of a shrub component and a lamp of its own; beside it, loose
    copies of a post and a plain group with a child."""
    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    v = win.viewport
    sc = v.scene
    sc.guides.clear()
    shrub, post = _box(0.3), _box(1.0)
    plaza = _placed(None, "plaza", 0.0, 0.0)
    for b in range(6):
        bed = _placed(None, f"bed{b}", 4.0 * b, 0.0, 10.0 * b)
        bed.children = [_placed(shrub, f"s{b}{k}", 0.6 * k, 0.5, 15.0 * k)
                        for k in range(4)]
        bed.children.append(_placed(_box(0.2), f"lamp{b}", 0.0, 2.0))
        plaza.children.append(bed)
    sc.groups.append(plaza)
    for k in range(3):
        sc.groups.append(_placed(post, f"post{k}", 3.0 * k, -5.0))
    room = Group(_box(2.0), name="room")
    room.children = [_placed(post, "inner", 0.5, 0.5)]
    sc.groups.append(room)
    sc.version += 1
    try:
        yield v
    finally:
        win._saved_version = sc.version
        win.close()


def _pool(vp):
    vp._tick = getattr(vp, "_tick", 0) + 1
    vp._placements()
    vp._gather_instanced()
    _k, groups, lo, hi, codes, protos, mats, by_code = vp._inst_pool
    from core.materials import material_sig
    return ([id(g) for g in groups], lo.tolist(), hi.tolist(),
            [(id(protos[c][0]), material_sig(protos[c][1]), protos[c][2])
             for c in codes.tolist()],
            mats.tolist(), by_code.tolist())


def _fresh(vp):
    keep = vp._inst_pool
    vp._inst_pool = None
    try:
        return _pool(vp)
    finally:
        vp._inst_pool = keep


def _named(sc, name):
    from core.group import iter_placements
    for top in sc.groups:
        for g, _m in iter_placements(top):
            if g.name == name:
                return g
    raise KeyError(name)


def _boxes(vp, monkeypatch):
    """The placements whose row the pool works out (box, paint, batch)."""
    calls = []
    real = type(vp)._placement_bbox

    def spy(self, g):
        calls.append(g.name)
        return real(self, g)
    monkeypatch.setattr(type(vp), "_placement_bbox", spy)
    return calls


def test_an_edit_inside_one_group_works_out_only_its_rows(vp, monkeypatch):
    from core.history import SetGroupMaterialCommand
    sc = vp.scene
    _pool(vp)
    rows = len(vp._inst_pool[1])
    assert rows >= 30
    calls = _boxes(vp, monkeypatch)
    # One shrub painted, deep inside the planting: its row, not the 30.
    vp.history.execute(SetGroupMaterialCommand(_named(sc, "s23"),
                                               {"color": [0.8, 0.1, 0.1]}))
    got = _pool(vp)
    assert calls == ["s23"]
    assert got == _fresh(vp)
    # One bed painted: its own placement and its five, not its siblings'.
    calls.clear()
    vp.history.execute(SetGroupMaterialCommand(_named(sc, "bed4"),
                                               {"color": [0.1, 0.8, 0.1]}))
    got = _pool(vp)
    assert sorted(calls) == ["bed4", "lamp4", "s40", "s41", "s42", "s43"]
    assert got == _fresh(vp)
    # Hidden and shown again: nothing to work out hiding it, its six
    # rows showing it.
    calls.clear()
    bed = _named(sc, "bed1")
    bed.hidden = True
    sc.version += 1
    got = _pool(vp)
    assert calls == [] and len(got[0]) == rows - 6
    assert got == _fresh(vp)
    calls.clear()                  # the fresh pool's own
    bed.hidden = False
    sc.version += 1
    got = _pool(vp)
    assert len(calls) == 6 and got == _fresh(vp)


def test_the_pool_kept_row_by_row_reads_as_made_afresh(vp):
    from core.group import Group
    from core.history import (AssignLayerCommand, CompoundCommand,
                              MoveGroupCommand, RotateGroupCommand,
                              SetFaceOpacityCommand, SetGroupMaterialCommand)
    sc = vp.scene
    h = vp.history
    _pool(vp)
    n_cmds = 0

    def check(what):
        assert _pool(vp) == _fresh(vp), what

    def run(cmd, what):
        nonlocal n_cmds
        h.execute(cmd)
        n_cmds += 1
        check(what)

    def poke(fn, what):
        fn()
        sc.version += 1
        check(what)

    shrub = _named(sc, "s00").mesh
    lamp2 = _named(sc, "lamp2")
    run(SetGroupMaterialCommand(_named(sc, "s11"), {"color": [1, 0, 0]}),
        "paint a nested copy")
    run(SetGroupMaterialCommand(_named(sc, "bed2"), {"color": [0, 0, 1]}),
        "paint a bed: its children wear it")
    run(SetGroupMaterialCommand(_named(sc, "plaza"), {"color": [0, 1, 0]}),
        "paint the planting: every unpainted piece wears it")
    run(SetGroupMaterialCommand(_named(sc, "plaza"), None), "unpaint it")
    # The component's mesh edited: all 24 copies, in every bed.
    poke(lambda: shrub.add_face([V(0, 0, 0.5), V(0.3, 0, 0.5),
                                 V(0.3, 0.3, 0.5)]), "edit the shared mesh")
    poke(lambda: lamp2.mesh.add_face([V(0, 0, 0.4), V(0.2, 0, 0.4),
                                      V(0.2, 0.2, 0.4)]),
         "edit one lamp's own mesh")
    poke(lambda: setattr(_named(sc, "bed3"), "hidden", True), "hide a bed")
    poke(lambda: setattr(_named(sc, "s32"), "hidden", True),
         "hide a copy inside the hidden bed")
    poke(lambda: setattr(_named(sc, "bed3"), "hidden", False),
         "show the bed: one copy stays hidden")
    run(AssignLayerCommand([_named(sc, "bed5")], "Arbustos"),
        "a bed on a tag of its own")
    layer = sc.layer("Arbustos")
    poke(lambda: setattr(layer, "visible", False), "hide the tag")
    poke(lambda: setattr(layer, "visible", True), "show the tag")
    run(AssignLayerCommand([_named(sc, "s51")], "Arbustos"),
        "a copy on the tag inside the bed")
    # Structure: a copy added to a bed, one taken out, one moved to
    # another bed (its own part and its new bed's are the same: its
    # matrix in the world is not).
    bed0, bed1 = _named(sc, "bed0"), _named(sc, "bed1")
    extra = _placed(shrub, "extra", 1.0, 1.0, 33.0)
    poke(lambda: bed0.children.append(extra), "a copy added")
    poke(lambda: bed0.children.remove(_named(sc, "s01")), "a copy removed")
    moving = _named(sc, "s02")

    def reparent():
        bed0.children.remove(moving)
        bed1.children.append(moving)
    poke(reparent, "a copy moved to another bed")
    poke(lambda: bed1.children.reverse(), "a bed's children reordered")
    run(MoveGroupCommand(bed1, V(0.5, 0.2, 0.0)), "a bed moved")
    run(RotateGroupCommand(_named(sc, "s13"), V(0, 0, 0), V(0, 0, 1), 25.0),
        "a copy turned")

    def mirror():
        m = QMatrix4x4(_named(sc, "s40").xform)
        m.scale(-1.0, 1.0, 1.0)
        _named(sc, "s40").xform = m
    poke(mirror, "a copy mirrored: another batch")
    # A lamp made translucent in the same step as a paint elsewhere: the
    # opacity bumps no mesh serial, yet the lamp leaves the instanced pool.
    run(CompoundCommand([
        SetFaceOpacityCommand(list(lamp2.mesh.faces), 0.4),
        SetGroupMaterialCommand(_named(sc, "s50"), {"color": [1, 1, 0]})]),
        "a lamp turned to glass")
    assert "lamp2" not in {g.name for g in vp._inst_pool[1]}
    # A new top-level object, and a top-level one painted.
    top = Group(None, name="new")
    top.xform = QMatrix4x4()
    top.children = [_placed(shrub, "nt", 0.0, 9.0)]
    poke(lambda: sc.groups.append(top), "a new object")
    run(SetGroupMaterialCommand(_named(sc, "post1"), {"color": [0, 1, 1]}),
        "a top-level copy painted")
    # Inside the planting, then inside one bed: the same edits.
    vp.begin_group_edit(_named(sc, "plaza"))
    check("planting open")
    run(SetGroupMaterialCommand(_named(sc, "bed4"), {"color": [1, 0, 1]}),
        "paint a bed from inside the planting")
    run(MoveGroupCommand(_named(sc, "bed2"), V(0.0, 0.3, 0.0)),
        "move a bed from inside the planting")
    vp.begin_group_edit(_named(sc, "bed4"))
    check("bed open")
    run(SetGroupMaterialCommand(_named(sc, "s42"), {"color": [0.5, 0.5, 0]}),
        "paint a copy from inside its bed")
    poke(lambda: setattr(_named(sc, "s43"), "hidden", True),
         "hide a copy from inside its bed")
    vp.end_group_edit()
    check("bed closed")
    vp.end_group_edit()
    check("planting closed")
    # Undo every command, then redo them all.
    for k in range(n_cmds):
        h.undo()
        check(f"undo {k}")
    for k in range(n_cmds):
        h.redo()
        check(f"redo {k}")


def test_a_group_moved_to_another_container_is_not_kept(vp):
    """Its part and its new container's part read as before; its world
    matrix does not — the chain of containers tells them apart."""
    sc = vp.scene
    old = vp._placements_epoch()
    _pool(vp)
    bed0, bed1 = _named(sc, "bed0"), _named(sc, "bed1")
    s = _named(sc, "s02")
    bed0.children.remove(s)
    bed1.children.append(s)
    sc.version += 1
    kept = vp._epoch_kept_placements(old)
    assert kept is not None
    assert id(s) not in kept
    assert id(_named(sc, "s03")) in kept and id(bed1) in kept
    assert _pool(vp) == _fresh(vp)
