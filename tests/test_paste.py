"""Paste tool: stamp copied geometry at the cursor, as one undoable step."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QVector3D

from core.history import History
from core.scene import Scene
from tools.base import ToolContext
from tools.paste import PasteTool


def V(x: float, y: float, z: float = 0.0) -> QVector3D:
    return QVector3D(float(x), float(y), float(z))


class _VP:
    def __init__(self, scene, history, clipboard):
        self.scene, self.history, self.clipboard = scene, history, clipboard

    def update(self):
        pass


def test_paste_stamps_clipboard_at_cursor():
    scene = Scene()
    hist = History(scene)
    scene.mesh.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    vp = _VP(scene, hist, clip)

    tool = PasteTool()
    tool.on_activate(vp)
    ctx = ToolContext(viewport=vp, world=V(5, 5, 0),
                      screen=QPointF(0, 0), modifiers=Qt.NoModifier, snap=None)
    tool.on_click(ctx)

    assert len(scene.mesh.faces) == 2
    pasted = [f for f in scene.mesh.faces
              if {(round(v.x()), round(v.y())) for v in f.vertices}
              == {(5, 5), (7, 5), (7, 7), (5, 7)}]
    assert len(pasted) == 1                 # the ref corner landed at the cursor

    assert hist.undo() is True
    assert len(scene.mesh.faces) == 1


def test_paste_preview_follows_cursor():
    scene = Scene()
    clip = {"faces": [([V(0, 0), V(2, 0), V(2, 2), V(0, 2)], [])],
            "edges": [], "ref": V(0, 0, 0)}
    vp = _VP(scene, History(scene), clip)
    tool = PasteTool()
    tool.on_activate(vp)
    ctx = ToolContext(viewport=vp, world=V(3, 0, 0),
                      screen=QPointF(0, 0), modifiers=Qt.NoModifier, snap=None)
    tool.on_hover(ctx)
    segs = tool.rubber_band_lines()
    assert len(segs) == 4                    # the square's 4 edges, offset by +3 x
    xs = {round(p.x()) for seg in segs for p in seg}
    assert xs == {3, 5}
