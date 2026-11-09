# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A Delete, a Paste and their undo touch the objects that came or went,
not the model (#158, «sin lag»).

On the plant of #158 deleting one object took 3.4 s and pasting one 3.5 s:
the per-placement passes made all 21 406 placements again, the static
buffers re-sent everything after the object, the Browser made its 21 405
rows again and the materials panel read 1.5 million face paints. Each
pass now keeps what belongs to the objects that did not change; every
answer here is compared with one made afresh."""
from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtGui import QMatrix4x4, QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _prisma(n=12, r=1.0, h=2.0):
    """A smooth n-sided prism: soft vertical edges, a curved side."""
    from core.mesh import Mesh
    m = Mesh()
    ring = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
            for i in range(n)]
    for i in range(n):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % n]
        m.add_face([V(x0, y0, 0), V(x1, y1, 0), V(x1, y1, h), V(x0, y0, h)])
    for e in m.edges:
        if abs(e.a.z() - e.b.z()) > 1e-9:
            e.soft = True
    return m


def _square(x0, y0, s=1.0, color=None, opacity=None):
    from core.mesh import Mesh
    m = Mesh()
    f = m.add_face([V(x0, y0, 0), V(x0 + s, y0, 0), V(x0 + s, y0 + s, 0),
                    V(x0, y0 + s, 0)])
    if f.normal().z() < 0:
        f.flip()
    if color is not None:
        f.attrs["color"] = list(color)
    if opacity is not None:
        f.attrs["opacity"] = opacity
    return m


def _placed(proto, name, x, y=0.0, turn=0.0):
    from core.group import Group
    g = Group(proto, name=name)
    m = QMatrix4x4()
    m.translate(x, y, 0.0)
    m.rotate(turn, 0.0, 0.0, 1.0)
    g.xform = m
    return g


def _scene(win):
    """Instanced prisms of two prototypes, a container holding two more
    (nested placements), and plain groups — one of them glass."""
    from core.group import Group
    vp = win.viewport
    sc = vp.scene
    sc.guides.clear()
    protos = [_prisma(12), _prisma(7, r=0.5, h=3.0)]
    gs = [_placed(protos[k % 2], f"P{k}", 3.0 * k, (k % 3) * 1.5, 17.0 * k)
          for k in range(8)]
    box = Group(None, name="caja")
    m = QMatrix4x4()
    m.translate(0.0, 9.0, 0.0)
    box.xform = m
    box.children = [_placed(protos[0], "dentro0", 0.0),
                    _placed(protos[1], "dentro1", 3.0)]
    plain = [Group(_square(-4.0, 2.0 * k, color=(0.2, 0.3 + 0.1 * k, 0.8)),
                   name=f"S{k}") for k in range(4)]
    glass = Group(_square(-7.0, 0.0, color=(0.6, 0.8, 0.9), opacity=0.4),
                  name="vidrio")
    sc.groups += gs[:4] + [plain[0], box, plain[1], glass] + gs[4:] + plain[2:]
    sc.version += 1
    return vp, gs, box, plain, glass


def _close(win):
    win._saved_version = win.viewport.scene.version
    win.close()


def _look(vp):
    cam = vp.camera
    cam.perspective = True
    cam.target = V(10, 4, 1)
    cam.distance, cam.yaw, cam.pitch = 45.0, 0.3, 0.5
    vp._frame_planes = vp._frustum_planes(
        cam.projection_matrix() * cam.view_matrix())


def _pool(vp):
    vp._gather_instanced()
    _k, groups, lo, hi, codes, protos, mats, by_code = vp._inst_pool
    return ([id(g) for g in groups], lo.tolist(), hi.tolist(),
            [(id(protos[c][0]), protos[c][2]) for c in codes.tolist()],
            mats.tolist(), by_code.tolist())


def _fresh(vp, fn, *names):
    keep = {n: getattr(vp, n, None) for n in names}
    for n in names:
        setattr(vp, n, None)
    try:
        return fn()
    finally:
        for n, v in keep.items():
            setattr(vp, n, v)


def _sil(vp, eye):
    groups = [g for g in vp._placements()
              if vp.scene.entity_visible(g)]
    raw, rest = vp._instanced_silhouettes(groups, eye, None)
    a = np.frombuffer(raw, np.float32).reshape(-1, 6)
    return sorted(map(tuple, np.round(a, 4))), [id(g) for g in rest]


def _lazy(vp):
    t = vp._pick_lazy_table()
    return ([id(g) for g in t[0]], t[1].tolist(), t[2].tolist(),
            t[3].tolist(), sorted(t[4]))


def _steps(vp, gs, box, plain):
    """Delete a placement, a container and a plain group; paste a copy of
    a placement and of the container; undo it all, one by one — yielding
    after each."""
    from core.group import copy_group
    from core.history import DeleteGroupCommand, InsertGroupCommand
    h = vp.history
    for cmd in (DeleteGroupCommand(gs[2]), DeleteGroupCommand(box),
                DeleteGroupCommand(plain[1]),
                InsertGroupCommand(copy_group(gs[5], V(0.0, -6.0, 0.0))),
                InsertGroupCommand(copy_group(gs[0], V(1.0, -9.0, 0.0)))):
        h.execute(cmd)
        yield type(cmd).__name__
    for _ in range(5):
        h.undo()
        yield "undo"


def test_the_instanced_pool_keeps_the_rows_of_what_stayed():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        _look(vp)
        _pool(vp)
        calls = []
        real = vp._placement_bbox
        vp._placement_bbox = lambda g: (calls.append(id(g)), real(g))[1]
        for what in _steps(vp, gs, box, plain):
            calls.clear()
            got = _pool(vp)
            worked = len(calls)
            assert got == _fresh(vp, lambda: _pool(vp), "_inst_pool"), what
            # Only the placements of what came or went were worked out.
            assert worked <= 3, (what, worked)
    finally:
        _close(win)


def test_the_silhouette_table_keeps_the_prototypes_that_did_not_change():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        eye = V(25, -18, 9)
        _sil(vp, eye)
        for what in _steps(vp, gs, box, plain):
            before = {t["uid"]: t for t in vp._sil_table[1]}
            got = _sil(vp, eye)
            assert got == _fresh(vp, lambda: _sil(vp, eye), "_sil_table"), what
            after = {t["uid"]: t for t in vp._sil_table[1]}
            # A prototype none of whose placements came or went keeps its
            # entry, and the outline worked out for it.
            assert after.keys() == before.keys()
    finally:
        _close(win)


def test_a_copy_deleted_and_one_pasted_at_once_reads_as_made_afresh():
    from core.group import copy_group
    from core.history import (CompoundCommand, DeleteGroupCommand,
                              InsertGroupCommand)
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        eye = V(25, -18, 9)
        _sil(vp, eye)
        vp.history.execute(CompoundCommand([
            DeleteGroupCommand(gs[0]),
            InsertGroupCommand(copy_group(gs[2], V(2.0, -7.0, 0.0)))]))
        got = _sil(vp, eye)
        assert got == _fresh(vp, lambda: _sil(vp, eye), "_sil_table")
    finally:
        _close(win)


def test_a_prototype_untouched_by_a_delete_keeps_its_entry():
    from core.history import DeleteGroupCommand
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        eye = V(25, -18, 9)
        _sil(vp, eye)
        by = {t["uid"]: t for t in vp._sil_table[1]}
        vp.history.execute(DeleteGroupCommand(gs[3]))          # a 7-sided one
        _sil(vp, eye)
        kept = [t for t in vp._sil_table[1] if by.get(t["uid"]) is t]
        assert len(kept) == 1 and gs[0].mesh is not gs[3].mesh
        assert any(g.mesh is gs[0].mesh for g in kept[0]["groups"])
    finally:
        _close(win)


def test_the_lists_and_the_lazy_table_read_as_made_afresh():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        vp._PICK_LAZY_MIN_FACES = 1
        _lazy(vp)
        placements = vp._placements()
        vp._static_draw_groups(placements)
        for what in _steps(vp, gs, box, plain):
            got = _lazy(vp)
            assert got == _fresh(vp, lambda: _lazy(vp), "_pick_lazy_memo"), what
            placements = vp._placements()
            stat = [id(g) for g in vp._static_draw_groups(placements)]
            fresh = _fresh(vp, lambda: [id(g) for g in vp._static_draw_groups(
                placements)], "_static_groups_memo")
            assert stat == fresh, what
    finally:
        _close(win)


def test_an_object_kept_is_one_whose_whole_subtree_reads_the_same():
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        old = vp._placements_epoch()
        m = QMatrix4x4(box.children[1].xform)
        m.translate(0.0, 0.5, 0.0)
        box.children[1].xform = m              # inside the container
        vp.scene.version += 1
        kept = vp._epoch_kept_tops(old)
        assert id(box) not in kept
        assert {id(g) for g in vp.scene.groups} - kept == {id(box)}
        old = vp._placements_epoch()
        vp.scene.layers[0].visible = not vp.scene.layers[0].visible
        vp.scene.version += 1
        assert vp._epoch_kept_tops(old) is None   # the rest changed too
    finally:
        _close(win)


def _show(win):
    win.show()
    for _ in range(10):
        _app.processEvents()
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    return vp


def _pump(n=6):
    for _ in range(n):
        _app.processEvents()


def _faces_bytes(vp):
    """The faces buffer as the parts say, opaque block and runs, without
    the room between them."""
    parts = vp._vbo_parts["faces"][0]
    raw = b"".join(parts)
    end = vp._faces_count * 24
    room = (vp._face_room_at or end) - end
    return raw[:end], raw[end + room:]


def test_a_deleted_object_leaves_zeros_its_undo_fills_and_a_paste_comes_last():
    from core.group import copy_group
    from core.history import DeleteGroupCommand, InsertGroupCommand
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = _show(win)
        sc = vp.scene
        sc.show_axes = False
        vp2, gs, box, plain, glass = _scene(win)
        vp.camera.set_view("top")
        vp.camera.perspective = False
        vp.camera.fit_to(V(-8, -10, 0), V(24, 12, 3))
        _pump()
        vp.grabFramebuffer()
        sizes = list(vp._vbo_parts["faces"][2])
        opaque, runs = _faces_bytes(vp)

        def colour(img, x, y):
            dpr = img.width() / max(vp.width(), 1)
            px = vp._world_to_pixel(V(x, y, 0))
            c = img.pixelColor(int(px[0] * dpr), int(px[1] * dpr))
            return c.redF(), c.greenF(), c.blueF()

        img = vp.grabFramebuffer()
        sky = colour(img, -6.0, 10.0)
        assert colour(img, -3.5, 2.5) != sky             # S1 is drawn
        vp.history.execute(DeleteGroupCommand(plain[1]))
        vp.history.execute(DeleteGroupCommand(glass))
        _pump()
        img = vp.grabFramebuffer()
        assert vp._vbo_parts["faces"][2] == sizes        # zeros in its place
        assert np.allclose(colour(img, -3.5, 2.5), sky, atol=0.02)
        assert np.allclose(colour(img, -6.5, 0.5), sky, atol=0.02)   # glass
        assert colour(img, -3.5, 0.5) != sky             # S0 stays
        vp.history.undo()
        vp.history.undo()
        _pump()
        vp.grabFramebuffer()
        assert vp._vbo_parts["faces"][2] == sizes
        assert _faces_bytes(vp) == (opaque, runs)        # as it was
        pasted = copy_group(plain[0], V(0.0, -6.0, 0.0))
        vp.history.execute(InsertGroupCommand(pasted))
        _pump()
        img = vp.grabFramebuffer()
        assert colour(img, -3.5, -5.5) != sky            # the copy is drawn
        got = _faces_bytes(vp)
        # The same buffer, part for part, as one laid out afresh.
        vp._slot_layout = None
        vp._face_room_at = None
        vp._vbo_parts.clear()
        vp._edges_version = -1
        vp._edges_content_key = None
        vp._edge_groups_cache = None
        _pump()
        vp.grabFramebuffer()
        assert _faces_bytes(vp) == got
    finally:
        _close(win)


def test_the_browser_takes_rows_out_and_puts_them_in_as_a_rebuild_would():
    from core.group import copy_group
    from core.history import DeleteGroupCommand, InsertGroupCommand
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        panel = win.project_browser.outliner
        panel.refresh()

        def dump():
            out = []

            def walk(item, depth):
                for i in range(item.childCount()):
                    c = item.child(i)
                    out.append((depth, tuple(c.text(k) for k in range(8)),
                                c.toolTip(1)))
                    walk(c, depth + 1)
            walk(panel._root, 0)
            return out

        rebuilds = []
        real = panel._rebuild
        panel._rebuild = lambda scene: (rebuilds.append(1), real(scene))[1]
        h = vp.history
        cmds = [DeleteGroupCommand(gs[2]), DeleteGroupCommand(box),
                InsertGroupCommand(copy_group(gs[5], V(0.0, -6.0, 0.0))),
                InsertGroupCommand(copy_group(box, V(4.0, 0.0, 0.0)))]
        for cmd in cmds:
            h.execute(cmd)
            panel.refresh(rows_if_changed=True)
            got = dump()
            assert not rebuilds, type(cmd).__name__
            panel._shape = None
            panel.refresh()                          # made afresh
            rebuilds.clear()
            assert dump() == got, type(cmd).__name__
        for _ in cmds:
            h.undo()
            panel.refresh(rows_if_changed=True)
            got = dump()
            assert not rebuilds
            panel._shape = None
            panel.refresh()
            rebuilds.clear()
            assert dump() == got
        # A paste of a component counts one copy more in its siblings' rows.
        from core import outliner
        from views.outliner import COL_COPIES
        n = outliner.instance_counts(vp.scene.groups)[id(gs[1].mesh)]
        assert panel._items[id(gs[1])].text(COL_COPIES) == str(n)
        h.execute(InsertGroupCommand(copy_group(gs[1], V(0.0, 5.0, 0.0))))
        panel.refresh(rows_if_changed=True)
        assert not rebuilds
        assert panel._items[id(gs[1])].text(COL_COPIES) == str(n + 1)
        assert panel._items[id(box.children[1])].text(COL_COPIES) == str(n + 1)
    finally:
        _close(win)


def test_a_rename_between_two_deletes_makes_the_rows_read_again():
    from core.history import DeleteGroupCommand
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        panel = win.project_browser.outliner
        panel.refresh()
        vp.history.execute(DeleteGroupCommand(gs[2]))
        gs[4].name = "renombrado"           # not through a command
        vp.scene.version += 1
        vp.history.execute(DeleteGroupCommand(gs[3]))
        panel.refresh(rows_if_changed=True)
        assert panel._items[id(gs[4])].text(0) == "renombrado"
    finally:
        _close(win)


def test_the_materials_panel_reads_only_the_meshes_that_came():
    from core.group import copy_group
    from core.history import (DeleteGroupCommand, InsertGroupCommand,
                              SetFaceColorCommand)
    from views.main_window import MainWindow
    import core.mesh as cm
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        panel = win.tray.materials

        def colours():
            panel.refresh_in_model()
            return sorted(tuple(round(c, 3) for c in k)
                          for (k, _c, _n) in panel._swatch_sig[0])

        read = []
        real = cm.face_attrs

        def spy(mesh):
            read.append(id(mesh))
            return real(mesh)
        import views.tray as tray_mod  # noqa: F401
        cm.face_attrs = spy
        try:
            start = colours()
            assert (0.2, 0.4, 0.8) in start
            read.clear()
            vp.history.execute(DeleteGroupCommand(plain[1]))
            got = colours()
            assert (0.2, 0.4, 0.8) not in got           # nothing wears it
            assert not read                             # no mesh read again
            vp.history.undo()
            assert colours() == start
            assert read == [id(plain[1].mesh)]          # back: read again
            read.clear()
            pasted = copy_group(plain[2], V(0.0, 30.0, 0.0))
            vp.history.execute(InsertGroupCommand(pasted))
            assert colours() == start
            assert read == [id(pasted.mesh)]            # the new one only
            # A paint is not a groups-only change: everything is read again.
            read.clear()
            vp.history.execute(SetFaceColorCommand(
                list(plain[0].mesh.faces), (0.9, 0.1, 0.1)))
            assert (0.9, 0.1, 0.1) in colours()
            assert len(read) > 1
        finally:
            cm.face_attrs = real
    finally:
        _close(win)


def test_unchanged_swatches_are_kept_and_the_components_list_too():
    from core.history import DeleteGroupCommand
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        mats = win.tray.materials
        mats.refresh_in_model()
        buttons = [mats._in_model_grid.itemAt(i).widget()
                   for i in range(mats._in_model_grid.count())]
        comps = win.tray.components
        comps.refresh_in_model()
        lst = comps._in_model
        items = [lst.item(i) for i in range(lst.count())]
        # A copy of the 7-sided prism: the list keeps its order (the
        # rows go by copies, then by name).
        vp.history.execute(DeleteGroupCommand(gs[5]))
        mats.refresh_in_model()
        assert [mats._in_model_grid.itemAt(i).widget()
                for i in range(mats._in_model_grid.count())] == buttons
        comps.refresh_in_model()
        assert [lst.item(i) for i in range(lst.count())] == items
        n = sum(1 for g in vp.scene.groups if g.mesh is gs[1].mesh) + 1
        row = next(it for it in items
                   if (it.data(0x0100) or [None])[0] is not None
                   and it.data(0x0100)[0].mesh is gs[1].mesh)
        assert f"({n}×" in row.text()                  # the box counts too
    finally:
        _close(win)


def test_the_flow_layout_answers_a_new_width_and_a_new_item():
    from PySide6.QtWidgets import QPushButton, QWidget
    from views.tray import FlowLayout
    host = QWidget()
    lay = FlowLayout(host)
    for _ in range(6):
        b = QPushButton("x")
        b.setFixedSize(40, 30)
        lay.addWidget(b)
    h1 = lay.heightForWidth(100)
    assert lay.heightForWidth(100) == h1
    assert lay.heightForWidth(400) < h1
    b = QPushButton("y")
    b.setFixedSize(40, 30)
    lay.addWidget(b)
    assert lay.heightForWidth(400) == lay._do_layout(
        type(lay.geometry())(0, 0, 400, 0), test_only=True)
    h2 = lay.heightForWidth(100)
    # A button that grows tells its layout so (Qt invalidates it): the
    # height asked next is the new one.
    for i in range(7):
        lay.itemAt(i).widget().setFixedSize(40, 90)
    assert lay.heightForWidth(100) > h2


def test_only_groups_only_commands_carry_the_groups_mark_forward():
    from core.group import copy_group
    from core.history import (CompoundCommand, DeleteGroupCommand,
                              InsertGroupCommand, SetFaceColorCommand)
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp, gs, box, plain, glass = _scene(win)
        h = vp.history
        cv = lambda: vp.scene.content_version            # noqa: E731
        h.groups_cv["x"] = cv()
        h.execute(DeleteGroupCommand(gs[0]))
        h.execute(CompoundCommand([InsertGroupCommand(copy_group(gs[1]))]))
        h.undo()
        assert h.groups_cv["x"] == cv()
        h.execute(SetFaceColorCommand(list(plain[0].mesh.faces), (1, 0, 0)))
        assert h.groups_cv["x"] != cv()
    finally:
        _close(win)
