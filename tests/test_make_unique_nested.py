"""Make Unique on a component that holds subgroups keeps them as subgroups
(issue #90, @fafecm: «if I try to make it unique, it explodes all the
subgroups within it») — with a private copy of the whole tree, so editing
the unique one never reaches its former siblings."""
from __future__ import annotations

from PySide6.QtGui import QMatrix4x4, QVector3D as V

from core.group import Group, copy_group, world_mesh
from core.history import History, MakeUniqueCommand
from core.mesh import Mesh
from core.scene import Scene


def _quad(z=0.0):
    m = Mesh()
    m.add_face([V(0, 0, z), V(1, 0, z), V(1, 1, z), V(0, 1, z)])
    return m


def _placed(mesh, dx=0.0, dz=0.0):
    g = Group(mesh)
    xf = QMatrix4x4()
    xf.translate(dx, 0.0, dz)
    g.xform = xf
    return g


def _points(group):
    return sorted((round(v.position.x(), 6), round(v.position.y(), 6),
                   round(v.position.z(), 6))
                  for v in world_mesh(group).vertices)


def test_make_unique_keeps_the_subgroups_and_shares_nothing():
    scene = Scene()
    hist = History(scene)
    parent = _placed(_quad(), dx=5.0)
    parent.adopt([_placed(_quad(), dz=1.0), _placed(_quad(), dz=2.0)])
    sibling = copy_group(parent, V(10, 0, 0))
    scene.groups.extend([parent, sibling])
    before = _points(parent)
    kids_uid = [c.uid for c in parent.children]

    hist.execute(MakeUniqueCommand(parent))
    assert len(parent.children) == 2                    # not exploded
    assert [c.uid for c in parent.children] == kids_uid
    assert parent.xform is not None                     # still placed
    assert _points(parent) == before                    # same geometry
    assert parent.mesh is not sibling.mesh
    for mine, theirs in zip(parent.children, sibling.children):
        assert mine.mesh is not theirs.mesh
    # editing the unique one's subgroup leaves the sibling alone
    theirs = _points(sibling)
    parent.children[0].mesh.vertices[0].position = V(0, 0, 9)
    assert _points(sibling) == theirs

    hist.undo()
    assert parent.mesh is sibling.mesh
    assert all(a.mesh is b.mesh
               for a, b in zip(parent.children, sibling.children))


def test_a_component_without_subgroups_becomes_a_component_of_its_own():
    """Still a component, placed where it was, with a definition of its
    own: the other copy is not touched (#620)."""
    scene = Scene()
    hist = History(scene)
    a = _placed(_quad(), dx=3.0)
    other = copy_group(a, V(5, 0, 0))
    scene.groups.extend([a, other])
    before = _points(a)
    hist.execute(MakeUniqueCommand(a))
    assert a.is_component() and a.xform is not None and not a.children
    assert a.mesh is not other.mesh
    assert _points(a) == before                     # nothing moved
