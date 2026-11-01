from __future__ import annotations

from PySide6.QtGui import QMatrix4x4

from core.group import Group
from core.group_scale import group_scale, scale_command
from core.history import History
from core.scene import Scene
from tests.test_group_axes import _slab


def _width(g) -> float:
    xs = [v.position.x() for v in g.mesh.vertices]
    return max(xs) - min(xs)


def test_a_classic_group_takes_a_typed_scale_and_undoes_it():
    g = _slab()
    scene = Scene()
    scene.groups.append(g)
    hist = History(scene)
    before = _width(g)
    hist.execute(scale_command(g, (2.0, 1.0, 1.0)))
    assert abs(_width(g) - 2 * before) < 1e-5
    assert abs(group_scale(g)[0] - 2.0) < 1e-5
    hist.undo()
    assert abs(_width(g) - before) < 1e-5
    assert abs(group_scale(g)[0] - 1.0) < 1e-5


def test_a_component_scales_along_its_own_axes_and_resets():
    g = Group()
    g.xform = QMatrix4x4()
    scene = Scene()
    hist = History(scene)
    hist.execute(scale_command(g, (2.0, 3.0, 4.0)))
    assert all(abs(a - b) < 1e-5 for a, b in zip(group_scale(g), (2, 3, 4)))
    hist.execute(scale_command(g, (1.0, 1.0, 1.0)))
    assert all(abs(a - 1.0) < 1e-5 for a in group_scale(g))


def test_unusable_or_unchanged_values_make_no_command():
    g = Group()
    g.xform = QMatrix4x4()
    assert scale_command(g, (0.0, 1.0, 1.0)) is None
    assert scale_command(g, (-1.0, 1.0, 1.0)) is None
    assert scale_command(g, (1.0, 1.0, 1.0)) is None


def test_a_rotated_group_made_component_scales_along_its_turned_axes():
    from PySide6.QtGui import QVector3D
    from core.history import GroupToComponentCommand, RotateGroupCommand
    g = _slab()
    scene = Scene()
    scene.groups.append(g)
    hist = History(scene)
    hist.execute(RotateGroupCommand(g, QVector3D(0, 0, 0),
                                    QVector3D(0, 0, 1), 30.0))
    hist.execute(GroupToComponentCommand(g))

    def span(direction):
        pts = [g.xform.map(v.position) for v in g.mesh.vertices]
        d = [QVector3D.dotProduct(p, direction) for p in pts]
        return max(d) - min(d)

    import math
    red = QVector3D(math.cos(math.radians(30)), math.sin(math.radians(30)), 0)
    green = QVector3D(-red.y(), red.x(), 0)
    r0, g0 = span(red), span(green)
    hist.execute(scale_command(g, (2.0, 1.0, 1.0)))
    assert abs(span(red) - 2 * r0) < 1e-4
    assert abs(span(green) - g0) < 1e-4
    assert all(abs(a - b) < 1e-4 for a, b in zip(group_scale(g), (2, 1, 1)))


def test_repeated_set_and_undo_does_not_drift():
    import math
    from PySide6.QtGui import QVector3D
    from core.history import GroupToComponentCommand, RotateGroupCommand
    g = _slab()
    scene = Scene()
    scene.groups.append(g)
    hist = History(scene)
    hist.execute(RotateGroupCommand(g, QVector3D(0, 0, 0),
                                    QVector3D(0, 0, 1), 37.0))
    hist.execute(GroupToComponentCommand(g))
    for _ in range(5):
        for target in ((1.0, 2.0, 1.0), (2.0, 2.0, 3.0)):
            hist.execute(scale_command(g, target))
            assert all(abs(a - b) < 1e-5 for a, b in zip(group_scale(g), target))
            hist.undo()
            assert all(f"{a:.6g}" == "1" for a in group_scale(g)), group_scale(g)
