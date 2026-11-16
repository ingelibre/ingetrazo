# SPDX-License-Identifier: GPL-3.0-or-later
"""Import one DXF with the IngeTrazo tree on sys.path[0]; print one JSON line:
time, groups, faces, open edges, total area, faces per part."""
import json, os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tree, path = sys.argv[1], sys.argv[2]
sys.path.insert(0, tree)
os.chdir(tree)
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from core.group import world_mesh
from core.scene import Scene
from formats.dxf_in import load_dxf

scene = Scene()
t = time.perf_counter()
load_dxf(scene, path, scale=0.001)
dt = time.perf_counter() - t
faces = open_edges = 0
area = 0.0
parts = {}
for g in scene.groups:
    m = world_mesh(g)
    n = len(m.faces)
    faces += n
    open_edges += sum(1 for e in m.edges if len(e.faces) != 2)
    for f in m.faces:
        try:
            area += f.area()
        except Exception:
            pass
    parts[g.name] = parts.get(g.name, 0) + n
print(json.dumps({"t": round(dt, 2), "groups": len(scene.groups), "faces": faces,
                  "open": open_edges, "area": round(area, 6), "parts": parts}))
