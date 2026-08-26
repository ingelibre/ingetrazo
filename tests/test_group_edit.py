# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Groups v2: edit-inside-group context (double-click into a group)."""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.history import AddFaceCommand, History, MakeGroupCommand
from core.scene import Scene


def V(x, y, z=0.0):
    return QVector3D(x, y, z)


def _rect(scene, hist, x0, y0, x1, y1):
    pts = [V(x0, y0), V(x1, y0), V(x1, y1), V(x0, y1)]
    hist.execute(build_add_edges(
        scene, [(pts[i], pts[(i + 1) % 4]) for i in range(4)],
        detect_faces=False, extra=[AddFaceCommand(list(pts))]))


def _grouped_scene():
    scene = Scene()
    hist = History(scene)
    _rect(scene, hist, 0, 0, 4, 4)
    hist.execute(MakeGroupCommand(list(scene.mesh.faces),
                                  list(scene.mesh.edges)))
    return scene, hist, scene.groups[0]


def test_enter_edit_swaps_mesh_and_exit_restores():
    scene, hist, group = _grouped_scene()
    loose = scene.mesh
    scene.begin_group_edit(group)
    assert scene.mesh is group.mesh
    assert scene.edit_group is group
    assert scene.loose_mesh is loose
    scene.end_group_edit()
    assert scene.mesh is loose
    assert scene.edit_group is None


def test_drawing_inside_lands_in_the_group():
    scene, hist, group = _grouped_scene()
    scene.begin_group_edit(group)
    _rect(scene, hist, 1, 1, 2, 2)                 # drawn INSIDE the context
    scene.end_group_edit()
    assert len(scene.mesh.faces) == 0              # loose mesh untouched
    assert len(group.mesh.faces) == 2              # group gained the rect


def test_undo_after_exiting_restores_the_group_not_the_loose_mesh():
    # The critical cross-context case: a command executed INSIDE the group,
    # undone AFTER leaving. Its snapshot must land on the group's mesh.
    scene, hist, group = _grouped_scene()
    _rect(scene, hist, 10, 10, 12, 12)             # loose slab (outside)
    scene.begin_group_edit(group)
    _rect(scene, hist, 1, 1, 2, 2)                 # inside the group
    scene.end_group_edit()
    loose_faces = len(scene.mesh.faces)
    assert len(group.mesh.faces) == 2
    assert hist.undo()                             # undoes the INSIDE rect
    assert len(group.mesh.faces) == 1              # group restored
    assert len(scene.mesh.faces) == loose_faces    # loose mesh untouched
    assert hist.redo()
    assert len(group.mesh.faces) == 2


def test_render_views_do_not_duplicate_while_editing():
    scene, hist, group = _grouped_scene()
    _rect(scene, hist, 10, 10, 12, 12)             # loose slab
    total = len(list(scene.render_faces()))
    scene.begin_group_edit(group)
    assert len(list(scene.render_faces())) == total   # same faces, no dupes
    scene.end_group_edit()


def test_clear_scene_exits_the_context():
    scene, hist, group = _grouped_scene()
    scene.begin_group_edit(group)
    scene.clear()
    assert scene.edit_group is None
    assert len(scene.mesh.faces) == 0


def test_bundled_components_import_and_insert_undoably():
    # The starter components (the Sketchfab CC-BY set, see SOURCES.md) are
    # .glb files listed in components.json: every entry must exist, load
    # through the GLB importer, sit on the ground, and insert with exact
    # undo. The smallest one loads for real; the rest just exist (loading
    # 10 models is a slow-suite job).
    import json
    from pathlib import Path

    from core.group import Group
    from core.history import InsertGroupCommand
    from formats.glb import load_glb

    comp_dir = Path(__file__).resolve().parent.parent / "resources" / "components"
    manifest = json.loads((comp_dir / "components.json").read_text())
    assert len(manifest) >= 1
    for entry in manifest:
        assert (comp_dir / f"{entry['key']}.glb").exists(), entry["key"]
        assert (comp_dir / "thumbs" / f"{entry['key']}.png").exists(), \
            entry["key"]

    scene = Scene()
    hist = History(scene)
    temp = Scene()
    load_glb(temp, comp_dir / "cama.glb")
    mesh = temp.groups[0].mesh
    assert mesh.faces
    assert sum(1 for f in mesh.faces if f.attrs.get("texture")) > 1000
    zs = [v.position.z() for v in mesh.vertices]
    assert abs(min(zs)) < 1e-4                      # grounded
    hist.execute(InsertGroupCommand(Group(mesh, name="cama")))
    assert len(scene.groups) == 1
    assert hist.undo() and len(scene.groups) == 0
    assert hist.redo() and len(scene.groups) == 1


def test_billboard_group_round_trips_and_faces_camera(tmp_path):
    # Face-me billboards: flag + textured quad persist in .igz; the quad the
    # viewport computes always faces the camera around the vertical axis.
    from core.group import make_billboard_group
    from formats import igz

    scene = Scene()
    g = make_billboard_group("person_billboard.png", 1.75, "Persona", 0.28)
    scene.groups.append(g)
    assert g.billboard
    # excluded from the static render views (drawn per-frame instead)
    assert list(scene.render_faces()) == []
    p = tmp_path / "bb.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    g2 = scene2.groups[0]
    assert g2.billboard
    tex = g2.mesh.faces[0].attrs["texture"]
    assert tex["path"].endswith("person_billboard.png")

    # quad math: a stub viewport with a camera at two azimuths
    class _Cam:
        def __init__(self, eye):
            self._eye = eye

        def eye(self):
            return self._eye

    class _VpB:
        def __init__(self, scene, eye):
            self.scene = scene
            self.camera = _Cam(eye)

    from views.viewport import Viewport
    for eye, expect_normal in ((QVector3D(10, 0, 1), QVector3D(1, 0, 0)),
                               (QVector3D(0, -8, 1), QVector3D(0, -1, 0))):
        vp = _VpB(scene2, eye)
        corners, _path = Viewport._billboard_quad(vp, g2)
        n = QVector3D.crossProduct(corners[1] - corners[0],
                                   corners[3] - corners[0]).normalized()
        assert QVector3D.dotProduct(n, expect_normal) > 0.99 or \
            QVector3D.dotProduct(-n, expect_normal) > 0.99
        assert abs((corners[3] - corners[0]).z() - 1.75) < 1e-6


# ---- rest-of-model context while editing (SketchUp Model Info ▸ Components)

class _SpanStub:
    """Just enough Viewport to exercise the span splitting: everything is
    inside the frustum, so only the merge rule is under test."""

    from views.viewport import Viewport
    _visible_spans = Viewport._visible_spans
    _tex_run_spans = Viewport._tex_run_spans

    def _aabb_visible(self, planes, lo, hi):
        return True


def test_visible_spans_merge_adjacent_by_default():
    vp = _SpanStub()
    spans = [(None, 0, 10), ((0, 1), 10, 5), ((0, 1), 15, 7)]
    out, culled = vp._visible_spans(spans, planes=None)
    assert out == [(0, 22)] and culled == 0


def test_visible_spans_never_merge_across_the_split():
    """The context ends and the edited group begins at ``split``; merging
    across it would leave the fade pass unable to tell them apart."""
    vp = _SpanStub()
    spans = [(None, 0, 10), ((0, 1), 10, 5), ((0, 1), 15, 7)]
    out, _ = vp._visible_spans(spans, planes=None, split=15)
    assert out == [(0, 15), (15, 7)]
    # a split that falls on no boundary changes nothing
    out2, _ = vp._visible_spans(spans, planes=None, split=99)
    assert out2 == [(0, 22)]


def test_tex_run_spans_split_subject_from_context():
    vp = _SpanStub()
    parts = [(None, 0, 6, False), ((0, 1), 6, 4, False), ((0, 1), 10, 8, True)]
    ctx, subj = vp._tex_run_spans(parts, planes=None, fading=True)
    assert ctx == [(0, 10)]
    assert subj == [(10, 8)]
    # not fading: one list, everything in it
    ctx2, subj2 = vp._tex_run_spans(parts, planes=None, fading=False)
    assert ctx2 == [(0, 18)] and subj2 == []


def test_edit_rest_mode_defaults_to_fade_and_validates():
    from views.viewport import EDIT_REST_MODES, _load_edit_rest_mode
    assert "fade" in EDIT_REST_MODES and "hide" in EDIT_REST_MODES
    assert _load_edit_rest_mode() in EDIT_REST_MODES


# ---- incremental VBO upload -------------------------------------------------

class _FakeVBO:
    """Records the allocate/write traffic so a test can assert what actually
    reached the GPU."""

    def __init__(self):
        self.calls: list = []
        self.data = bytearray()

    def bind(self):
        pass

    def release(self):
        pass

    def allocate(self, arg, count=None):
        self.calls.append(("allocate", arg if count is None else count))
        size = arg if count is None else count
        self.data = bytearray(size)

    def write(self, offset, data, count):
        self.calls.append(("write", offset, count))
        self.data[offset:offset + count] = data[:count]


class _UploadStub:
    from views.viewport import Viewport
    _upload_vbo = Viewport._upload_vbo

    def __init__(self):
        self._vbo_parts = {}


def test_upload_vbo_first_call_allocates_and_writes_everything():
    vp, vbo = _UploadStub(), _FakeVBO()
    total = vp._upload_vbo(vbo, "e", [b"aaaa", b"bbbb"])
    assert total == 8
    assert vbo.calls[0][0] == "allocate"
    assert ("write", 0, 8) in vbo.calls
    assert bytes(vbo.data[:8]) == b"aaaabbbb"


def test_upload_vbo_resends_only_the_changed_tail():
    """The whole point: an unchanged prefix is already on the GPU."""
    vp, vbo = _UploadStub(), _FakeVBO()
    head = b"a" * 100                       # a group chunk: cached object
    vp._upload_vbo(vbo, "e", [head, b"bbbb"])
    vbo.calls.clear()
    vp._upload_vbo(vbo, "e", [head, b"cccc"])
    assert vbo.calls == [("write", 100, 4)]       # no allocate, no re-send
    assert bytes(vbo.data[:104]) == head + b"cccc"


def test_upload_vbo_prefix_matches_by_value_not_only_identity():
    """The loose block is rebuilt fresh every sync, so identity never holds
    for it; equal bytes must still count as already uploaded."""
    vp, vbo = _UploadStub(), _FakeVBO()
    vp._upload_vbo(vbo, "e", [b"a" * 50, b"bbbb"])
    vbo.calls.clear()
    vp._upload_vbo(vbo, "e", [b"a" * 50, b"dddd"])   # equal, not identical
    assert vbo.calls == [("write", 50, 4)]


def test_upload_vbo_growing_past_capacity_reallocates_and_rewrites():
    vp, vbo = _UploadStub(), _FakeVBO()
    head = b"a" * 16
    vp._upload_vbo(vbo, "e", [head])
    cap = vbo.calls[0][1]
    vbo.calls.clear()
    big = b"c" * (cap * 4)
    vp._upload_vbo(vbo, "e", [head, big])
    assert vbo.calls[0][0] == "allocate"             # outgrew the slack
    assert vbo.calls[1] == ("write", 0, 16 + len(big))
    assert bytes(vbo.data[:16 + len(big)]) == head + big


def test_upload_vbo_shrinking_keeps_the_prefix_and_the_count():
    vp, vbo = _UploadStub(), _FakeVBO()
    head = b"a" * 40
    vp._upload_vbo(vbo, "e", [head, b"b" * 40])
    vbo.calls.clear()
    total = vp._upload_vbo(vbo, "e", [head, b"b" * 8])
    assert total == 48
    assert vbo.calls == [("write", 40, 8)]           # capacity still fits
