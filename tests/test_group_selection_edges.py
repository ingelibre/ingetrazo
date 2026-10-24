# SPDX-License-Identifier: GPL-3.0-or-later
"""Selected groups highlight their visible geometry, by placement identity."""
import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group
from core.mesh import Mesh
from views.group_selection import _clear_group_selection, _group_selection_plan
from views.viewport import Viewport


def quad():
    mesh = Mesh()
    mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    return mesh


def placed(mesh, x=0):
    group = Group(mesh)
    group.xform = QMatrix4x4()
    group.xform.translate(x, 0, 0)
    return group


def tree():
    shared = quad()
    first, second = placed(shared), placed(shared, 3)
    parent = placed(Mesh(), 10)
    parent.adopt([first, second])
    other = placed(shared, 100)
    vp = Viewport()
    vp.scene.groups = [parent, other]
    vp.scene.selection = {parent}
    vp.scene.version += 1
    return vp, parent, first, second, other


def test_selecting_parent_highlights_all_child_edges_and_no_other_copy():
    vp, parent, _, _, other = tree()
    plan = _group_selection_plan(vp)
    assert len(plan['groups']) == 3
    assert all(g is parent or vp._owner_of(g) is parent for g in plan['groups'])
    assert other not in plan['groups']
    run, = plan['runs'].values()
    assert len(run['raw']) // 12 == 8  # Four source edges, shared by two placements.
    matrices = np.frombuffer(run['matrices'], np.float32).reshape(-1, 16)
    assert sorted(matrices[:, 12]) == [10, 13]


def test_selecting_one_child_inside_parent_only_highlights_that_child():
    vp, parent, first, _, _ = tree()
    vp.scene.begin_group_edit(parent)
    vp.scene.selection = {first}
    plan = _group_selection_plan(vp)
    assert len(plan['groups']) == 1 and vp._owner_of(plan['groups'][0]) is first


def test_plan_is_cached_and_invalidates_when_selection_changes():
    vp, _, _, _, other = tree()
    first = _group_selection_plan(vp)
    assert _group_selection_plan(vp) is first
    vp.scene.selection = {other}
    second = _group_selection_plan(vp)
    assert second is not first and second['groups'] == [other]


def test_hidden_objects_and_billboards_do_not_leave_static_edge_cues():
    vp, parent, first, second, _ = tree()
    first.hidden, second.billboard = True, 'mesh'
    vp.scene.version += 1
    plan = _group_selection_plan(vp)
    assert plan['groups'] == [parent] and not plan['runs']


def test_previewed_group_does_not_leave_highlight_at_its_original_position():
    vp, parent, _, _, _ = tree()
    vp._preview_groups = {id(g) for g in vp._expand_placements(parent)}
    assert not _group_selection_plan(vp)['runs']


def test_hide_rest_mode_excludes_selection_outside_the_open_group():
    vp, parent, _, _, other = tree()
    vp.scene.begin_group_edit(parent)
    vp._edit_rest_mode = 'hide'
    vp.scene.selection = {other}
    assert not _group_selection_plan(vp)['runs']


def test_many_small_runs_batch_world_edges_without_flattening_objects():
    vp = Viewport()
    children = [placed(quad(), i * 3) for i in range(80)]
    parent = placed(Mesh(), 20)
    parent.adopt(children)
    vp.scene.groups = [parent]
    vp.scene.selection = {parent}
    plan = _group_selection_plan(vp)
    run, = plan['runs'].values()
    world = np.frombuffer(run['raw'], np.float32).reshape(-1, 3)
    assert len(world) == 80 * 8
    assert world[:, 0].min() == 20 and world[:, 0].max() == 20 + 79 * 3 + 1
    assert parent.children == children and all(len(c.mesh.faces) == 1 for c in children)


def test_cache_reset_releases_model_references():
    vp, _, _, _, _ = tree()
    _group_selection_plan(vp)
    _clear_group_selection(vp, destroy=False)
    assert vp._group_selection_plan is None
    assert not vp._group_selection_gl and vp._group_selection_sil_table is None


def test_deselection_removes_the_geometry_highlight():
    vp, _, _, _, _ = tree()
    _group_selection_plan(vp)
    vp.scene.selection.clear()
    plan = _group_selection_plan(vp)
    assert not plan['runs'] and not plan['groups']
