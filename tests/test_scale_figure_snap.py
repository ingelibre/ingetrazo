"""The scale figure offers ONE snap, its feet (Rafael, revision 4: «me está
cogiendo el paisano»): its base corners, midpoints, head and the two lines
through it stole the inference from the drawing around the origin."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


def test_the_scale_figure_snaps_only_at_its_feet():
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    assert any(getattr(g, "billboard", False) for g in vp.scene.groups)
    snaps = vp._billboard_snap_edges()
    assert len(snaps) == 1
    feet = snaps[0]
    assert feet.a == feet.b                       # a point, not a line
    assert abs(feet.a.z()) < 1e-6                 # on the ground
    assert abs(feet.a.x() + 0.65) < 0.05 and abs(feet.a.y() + 0.60) < 0.05
    win._saved_version = vp.scene.version
    win.close()


def test_the_feet_follow_the_figures_added_and_taken_away():
    """The face-me placements are kept between pointer moves (21 406
    placements walked for two on the plant of #158): a figure added,
    taken away or made a plain group changes the feet offered."""
    from PySide6.QtGui import QMatrix4x4

    from core.group import Group
    from views.main_window import MainWindow
    win = MainWindow()
    vp = win.viewport
    sc = vp.scene
    fig = next(g for g in sc.groups if getattr(g, "billboard", False))
    assert len(vp._billboard_snap_edges()) == 1
    copy = Group(fig.mesh, name="otro paisano")
    copy.billboard = fig.billboard
    xf = QMatrix4x4()
    xf.translate(5.0, 2.0, 0.0)
    copy.xform = xf
    sc.groups.append(copy)
    sc.version += 1
    feet = sorted(round(s.a.x(), 3) for s in vp._billboard_snap_edges())
    assert len(feet) == 2 and feet[1] - feet[0] > 4.0
    sc.groups.remove(copy)
    sc.version += 1
    assert len(vp._billboard_snap_edges()) == 1
    was = fig.billboard
    fig.billboard = False
    sc.version += 1
    assert vp._billboard_snap_edges() == []
    fig.billboard = was
    sc.version += 1
    assert len(vp._billboard_snap_edges()) == 1
    win._saved_version = sc.version
    win.close()
