# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""An ordinary selection adds no locked-inspection work to orbit frames."""
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.scene import Scene
from tests.test_locked_group_not_pickable import _vp, _boxed_group


class UnwalkableSelection(set):
    def __iter__(self):
        pytest.fail("The inspection renderer walked the editable selection")

    def __or__(self, other):
        pytest.fail("The inspection renderer copied the editable selection")


def test_ordinary_select_all_does_no_inspection_work(monkeypatch):
    vp = _vp()
    vp.scene.selection = UnwalkableSelection(range(100_000))
    def unexpected(*args, **kwargs):
        pytest.fail("Ordinary selection triggered inspection geometry or drawing")
    for name in ("_expand_placements", "_group_obb", "_ensure_proto_draw"):
        monkeypatch.setattr(vp, name, unexpected)
    for _ in range(100):
        vp._draw_locked_group_edges()
        vp._draw_locked_selection()


@pytest.mark.parametrize("mode", ["replace", "add", "toggle", "remove"])
def test_bulk_selection_checks_locks_only_on_groups(monkeypatch, mode):
    scene = Scene()
    for i in range(1000):
        scene.mesh.add_edge(V(i, 0, 0), V(i, 1, 0))
    normal, locked = Group(), Group()
    locked.locked = True
    scene.groups.extend([normal, locked])
    original = scene.entity_locked
    checked = []
    def check(entity):
        assert isinstance(entity, Group), "Bulk selection checked a loose entity's lock"
        checked.append(entity)
        return original(entity)
    monkeypatch.setattr(scene, "entity_locked", check)
    scene.select([*scene.edges, normal, locked], mode=mode)
    assert set(checked) == {normal, locked}
    assert len(checked) == 2
    assert locked not in scene.selection


def test_cached_inspection_does_not_walk_groups_while_orbiting(monkeypatch):
    vp = _vp()
    group = _boxed_group(vp)
    group.locked = True
    vp.scene.select([group])
    first = vp._locked_selection_geometry()
    assert first[0] and first[1]
    def unexpected(*args, **kwargs):
        pytest.fail("An orbit frame rebuilt the inspection geometry")
    monkeypatch.setattr(vp, "_expand_placements", unexpected)
    monkeypatch.setattr(vp, "_group_obb", unexpected)
    vp.scene.selection = UnwalkableSelection(range(100_000))
    for _ in range(100):
        vp.camera.orbit(2, 1, vp.height())
        assert vp._locked_selection_geometry() is first


@pytest.mark.parametrize("change", ["clear", "hide", "delete", "unlock", "move"])
def test_inspection_cache_follows_scene_changes(change):
    vp = _vp()
    group = _boxed_group(vp)
    group.locked = True
    vp.scene.select([group])
    first = vp._locked_selection_geometry()
    if change == "clear":
        vp.scene.clear_selection()
    elif change == "hide":
        group.hidden = True
    elif change == "delete":
        vp.scene.groups.remove(group)
    elif change == "unlock":
        group.locked = False
    else:
        group.xform = QMatrix4x4()
        group.xform.translate(20, 0, 0)
    vp.scene.version += 1
    second = vp._locked_selection_geometry()
    if change == "move":
        assert second[1] != first[1]
    else:
        assert not second[0] and not second[1]


def test_opening_another_scene_drops_inspection_geometry():
    vp = _vp()
    group = _boxed_group(vp)
    group.locked = True
    vp.scene.select([group])
    assert vp._locked_selection_geometry()[0]
    vp.scene = Scene()
    assert vp._locked_selection_geometry() == ((), b"", ())
    assert vp._locked_geometry_cache is None


def test_face_me_outline_follows_camera_and_scene_changes(monkeypatch):
    vp = _vp()
    group = _boxed_group(vp)
    group.billboard = group.locked = True
    vp.scene.select([group])
    quads = []
    def quad(g):
        quads.append(g)
        return [V(), V(1, 0, 0), V(1, 0, 1), V(0, 0, 1)], None
    class Buffer:
        def bind(self): pass
        def release(self): pass
        def allocate(self, raw, size): pass
    monkeypatch.setattr(vp, "_billboard_quad", quad)
    monkeypatch.setattr(vp, "_set_color", lambda *args: None)
    vp._locked_sel_vbo = vp._locked_sel_vao = Buffer()
    vp._gl = SimpleNamespace(glDrawArrays=lambda *args: None)
    vp._draw_locked_selection()
    geometry = vp._locked_geometry_cache
    vp._draw_locked_selection()
    assert len(quads) == 1
    vp.camera.orbit(20, 0, vp.height())
    vp._draw_locked_selection()
    assert len(quads) == 2
    assert vp._locked_geometry_cache is geometry
    vp.scene.version += 1
    vp._draw_locked_selection()
    assert len(quads) == 3
