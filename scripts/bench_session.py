"""Benchmark A/B: mismas operaciones sobre la Plaza Yanque, medidas con reloj.
Uso: cd <checkout> && <venv python> bench.py <igz> <etiqueta> <salida.json>
Abre una ventana GL real (xcb) unos segundos."""
import os, sys, json, time, statistics as st, random
os.environ["QT_QPA_PLATFORM"] = "xcb"
sys.path.insert(0, os.getcwd())
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, Qt
app = QApplication([])
from views.main_window import MainWindow
igz, label, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
res = {"label": label, "commit": os.popen("git rev-parse --short HEAD").read().strip()}

def timed(fn, n=1):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); ts.append((time.perf_counter() - t0) * 1000.0)
    return {"median_ms": round(st.median(ts), 2), "mean_ms": round(st.mean(ts), 2), "max_ms": round(max(ts), 2), "n": n}

win = MainWindow(); vp = win.viewport
win.resize(1280, 800); win.show()
for _ in range(20):
    app.processEvents(); time.sleep(0.05)
    if vp._gl is not None:
        break
assert vp._gl is not None, "sin contexto GL"

def paint_now():
    vp.makeCurrent()
    try:
        vp.paintGL()
    finally:
        vp.doneCurrent()
t0 = time.perf_counter(); win.open_path(igz); app.processEvents()
res["open_s"] = round(time.perf_counter() - t0, 2)
sc = vp.scene
sc.selection.clear()
vp.camera.set_view("iso") if hasattr(vp.camera, "set_view") else None
lo, hi = sc.bounds(); vp.camera.fit_to(lo, hi)
# primer cuadro (frío: trozos)
t0 = time.perf_counter(); paint_now()
res["first_paint_s"] = round(time.perf_counter() - t0, 2)
paint_now()

def paint():
    paint_now()

def resync():
    vp._edges_version = -1; paint_now()

def orbit_frame():
    vp.camera.orbit(6.0, 2.0, vp.height()); paint_now()

def hover_at(px, py):
    vp._process_hover(QPointF(px, py), Qt.NoModifier)

W, H = vp.width(), vp.height()
random.seed(7)
pts = [(random.uniform(W * 0.2, W * 0.8), random.uniform(H * 0.25, H * 0.75)) for _ in range(60)]

def hovers():
    for px, py in pts:
        hover_at(px, py)

def pick_index_cold():
    vp._pick_index_cache = None; vp._pick_block = None; vp._pick_index()

def chunks_cold():
    vp._group_chunks.clear(); vp._inst_chunks.clear(); vp._edges_version = -1; paint_now()

# --- raíz --------------------------------------------------------------------
res["root"] = {}
res["root"]["paint"] = timed(paint, 30)
res["root"]["orbit_frame"] = timed(orbit_frame, 40)
res["root"]["resync_vbos"] = timed(resync, 5)
res["root"]["chunks_rebuild+paint"] = timed(chunks_cold, 2)
res["root"]["pick_index_cold"] = timed(pick_index_cold, 3)
win._activate_tool("select"); res["root"]["hover_select_x60"] = timed(hovers, 3)
win._activate_tool("line");   res["root"]["hover_line_x60"] = timed(hovers, 3)
win._activate_tool("select")
# --- dentro de un contenedor (la plaza: el grupo con más hijos) -------------
cont = max((g for g in sc.groups if g.children), key=lambda g: len(g.children), default=None)
res["container"] = {"name": getattr(cont, "name", None), "children": len(cont.children) if cont else 0}
if cont is not None:
    vp.begin_group_edit(cont); app.processEvents(); paint_now()
    res["container"]["paint"] = timed(paint, 30)
    res["container"]["orbit_frame"] = timed(orbit_frame, 40)
    res["container"]["resync_vbos"] = timed(resync, 5)
    res["container"]["pick_index_cold"] = timed(pick_index_cold, 3)
    win._activate_tool("select"); res["container"]["hover_select_x60"] = timed(hovers, 3)
    win._activate_tool("line");   res["container"]["hover_line_x60"] = timed(hovers, 3)
    win._activate_tool("select")
    # mover un hijo (traslación → atajo de los trozos)
    from core.history import MoveGroupCommand
    from PySide6.QtGui import QVector3D
    child = cont.children[0]
    def move_child():
        vp.history.execute(MoveGroupCommand(child, QVector3D(0.05, 0, 0))); paint_now()
    res["container"]["move_child+paint"] = timed(move_child, 10)
    vp.end_group_edit(); paint_now()
res["scene"] = {"groups": len(sc.groups), "faces_drawn": vp._faces_count // 3, "edges": vp._edges_count // 2,
                "dback": getattr(vp, "_dback_count", None)}
json.dump(res, open(out, "w"), indent=1)
print(json.dumps(res, indent=1))
win._saved_version = sc.version; win.close(); app.quit()
