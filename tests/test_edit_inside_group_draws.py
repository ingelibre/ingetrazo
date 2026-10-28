"""What you draw inside an open group or component is drawn at once
(Rafael, revision 4: «no se ven las líneas... estar está, pero no se ven»).

The group half of the edge buffer is cached on the placements epoch, which
leaves the open mesh's serial out on purpose; the open group's own edges
were cached with it and never refreshed until you left the group."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D as V
from PySide6.QtWidgets import QApplication

from core.group import Group
from core.mesh import Mesh

_app = QApplication.instance() or QApplication([])


def _box_group():
    m = Mesh()
    c = [V(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
    for q in ([0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4],
              [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]):
        m.add_face([c[i] for i in q])
    return Group(m, name="casa")


def _uploaded_edges(vp):
    """Run the edge sync, returning the number of edges it sent."""
    sent = {}

    def fake_upload(_vbo, slot, parts, empty=24):
        data = b"".join(parts)
        sent[slot] = len(data)
        return len(data)
    vp._upload_vbo = fake_upload
    # No GL here: the buffers the sync hands to the fake upload are names.
    import re
    import views.viewport as vpmod
    src = open(vpmod.__file__, encoding="utf-8").read()
    for name in set(re.findall(r"self\.(_\w+_vbo)\b", src)):
        if not hasattr(vp, name):
            setattr(vp, name, None)
    vp._tick = getattr(vp, "_tick", 0) + 1
    vp._sync_edges()
    return sent["edges"] // 24


@pytest.mark.parametrize("component", [False, True])
def test_an_edge_drawn_inside_an_open_group_is_drawn_at_once(component):
    from PySide6.QtGui import QMatrix4x4
    from views.main_window import MainWindow
    win = MainWindow()
    vp, sc = win.viewport, win.viewport.scene
    g = _box_group()
    if component:
        g.xform = QMatrix4x4()           # an instance: edited on a world copy
    sc.groups.append(g)
    sc.version += 1
    vp.begin_group_edit(g)
    box = vp._edit_group_box_corners()
    assert box is not None and len(box) == 8, (
        "an open group or component must show its dotted edit box")
    frame, lo, hi = vp._group_obb(g)
    for i, axis in enumerate(frame):
        coords = [V.dotProduct(p, axis) for p in box]
        assert min(coords) < lo[i] and max(coords) > hi[i], (
            "the dotted edit box must sit outside a cube's solid edges")
    before = _uploaded_edges(vp)
    sc.mesh.add_edge(V(0.2, 0, 0.2), V(0.8, 0, 0.8))    # drawn inside
    sc.version += 1
    assert _uploaded_edges(vp) == before + 1
    win._saved_version = sc.version
    win.close()


@pytest.mark.parametrize("component", [False, True])
def test_empty_click_leaves_only_beyond_the_dotted_box(monkeypatch, component):
    """The edit context is the visible box, not only the occupied faces.

    A cube now has a deliberate empty gutter inside its dotted frame, and an
    irregular group can leave much more empty space there. Clicking either
    must stay inside; only a click beyond the projected frame steps out.
    """
    from PySide6.QtGui import QMatrix4x4
    from tools.base import ToolContext
    from tools.select import SelectTool
    from views.main_window import MainWindow

    win = MainWindow()
    vp, scene = win.viewport, win.viewport.scene
    group = _box_group()
    if component:
        group.xform = QMatrix4x4()
    scene.groups.append(group)
    scene.version += 1
    vp.begin_group_edit(group)

    # Exercise the empty-click branch independently of face picking: the
    # centre stands for a hole/empty patch inside an irregular group's box.
    monkeypatch.setattr(SelectTool, "_pick",
                        lambda _self, _vp, _x, _y: None)
    tool = SelectTool()
    pixels = [vp._world_to_pixel(c) for c in vp._edit_group_box_corners()]
    pixels = [p for p in pixels if p is not None]
    centre = (sum(p[0] for p in pixels) / len(pixels),
              sum(p[1] for p in pixels) / len(pixels))

    # Find a pixel in the NEW gutter: inside the dotted frame but outside
    # the old, tight frame that coincided with the cube's solid edges.
    from core.group import oriented_box_corners
    from views.viewport import _point_in_screen_hull
    tight_px = [vp._world_to_pixel(c)
                for c in oriented_box_corners(*vp._group_obb(group))]
    tight_px = [p for p in tight_px if p is not None]
    gap = None
    for fraction in (0.05, 0.10, 0.20, 0.30):
        for p in pixels:
            q = (p[0] * (1.0 - fraction) + centre[0] * fraction,
                 p[1] * (1.0 - fraction) + centre[1] * fraction)
            if (vp.edit_group_box_contains_pixel(*q)
                    and not _point_in_screen_hull(*q, tight_px)):
                gap = QPointF(*q)
                break
        if gap is not None:
            break
    assert gap is not None, "the dotted box needs a clickable empty gutter"
    tool.on_click(ToolContext(vp, V(0, 0, 0), gap,
                              Qt.NoModifier, None))
    assert scene.edit_group is group

    outside = QPointF(min(p[0] for p in pixels) - 20.0,
                      min(p[1] for p in pixels) - 20.0)
    assert not vp.edit_group_box_contains_pixel(outside.x(), outside.y())
    tool.on_click(ToolContext(vp, V(0, 0, 0), outside,
                              Qt.NoModifier, None))
    assert scene.edit_group is None
    win._saved_version = scene.version
    win.close()


def test_the_edit_box_is_world_edges_on_its_twelve_edges():
    """The dashed box of the open group is geometry for the depth-tested GL
    pass (so its back edges hide behind the faces), not an overlay — twelve
    whole edges; the dash pattern is the shader's (u_stipple 4), so zooming
    into a large group costs nothing extra per frame."""
    from core.group import oriented_box_corners
    from views.viewport import _box_edge_vertices
    corners = oriented_box_corners((V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)),
                                   (0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
    pts = list(_box_edge_vertices(corners))
    assert len(pts) == 12 * 6          # twelve edges, two endpoints each
    for i in range(0, len(pts), 3):
        x, y, z = pts[i:i + 3]
        on_faces = sum(1 for c in (x, y, z) if abs(c) < 1e-6 or abs(c - 1) < 1e-6)
        assert on_faces >= 2          # every endpoint lies on a box edge
