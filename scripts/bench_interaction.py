# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Interaction benchmark: what a hand on the mouse feels, timed per event.

``bench_session.py`` (the release check) times the viewport's internals —
``paintGL``, ``camera.orbit``, ``_process_hover`` — on one private document.
This one drives the app the way a user does and times what the user waits
for: a REAL Qt event (mouse press/move/release, wheel, key) goes through
the viewport's own handlers, then the frame it asked for is painted and the
GPU is waited on (``glFinish`` — a paint that only queued GL commands is not
on screen yet), then whatever the event left pending in the queue (deferred
snap refinement, timers) runs. Each event's three slices are recorded:

    handler  the event handler itself (Python: camera, pick, snap, tool)
    paint    paintGL — the draw's CPU side (it runs in the event loop:
             QOpenGLWidget's update()/repaint() only schedule it)
    other    the rest of the loop right after (timers, posted work — and
             a pointer move the viewport parked to coalesce, waited for
             until it ran: the screen catching up with the pointer)
    gpu      glFinish after it all — what the GPU still had to do

and the gesture is summarised per event: median, p95, max, and the share of
events over one 60 Hz frame (16.7 ms) and over two (33 ms) — the share is
what "it stutters" means, the median alone hides it.

Gestures (the basic operations, each on points that land ON the model):

    orbit         middle-drag, 60 moves
    pan           Shift+middle-drag, 40 moves
    zoom          15 wheel notches in, 15 out, at a point on the model
    hover_select  60 pointer moves over the model, Select tool
    hover_line    the same with Line (the inference engine: snapping to
                  vertices, edges, midpoints — "picking a vertex")
    click_select  20 clicks on objects, Select tool
    move          Move a building: click, 30 moves (live deform), click
    undo          Ctrl+Z of that move

Usage (a real window opens; the machine should be otherwise idle):

    python scripts/bench_models.py S M L          # synthetic city models
    python scripts/bench_interaction.py out.json benchmarks/models/city-S.igz \\
        benchmarks/models/city-M.igz examples/pileta-fuente-yanque.igz
    python scripts/bench_interaction.py --compare before.json after.json

``--vsync`` keeps the wait for the monitor refresh (off by default: it
puts a floor of one refresh under every frame and hides the real cost).
``--repeat N`` runs every gesture N times and keeps each event's best
run (default 2: the first run of a gesture warms caches the user also
warms within a second of starting to work).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FRAME_60 = 1000.0 / 60.0
GESTURES = ("orbit", "pan", "zoom", "hover_select", "hover_line",
            "click_select", "move", "undo")


# ---- statistics -------------------------------------------------------------

def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summarise(events):
    """``events`` = [(handler, paint, other, gpu, paints, hover)] → the
    gesture's row (times in ms)."""
    tot = [e[0] + e[1] + e[2] + e[3] for e in events]
    r = lambda v: round(v, 2)  # noqa: E731
    return {
        "n": len(tot),
        "median_ms": r(st.median(tot)),
        "p95_ms": r(_pct(tot, 0.95)),
        "max_ms": r(max(tot)),
        "over_16ms_pct": r(100.0 * sum(t > FRAME_60 for t in tot) / len(tot)),
        "over_33ms_pct": r(100.0 * sum(t > 2 * FRAME_60 for t in tot)
                           / len(tot)),
        "median_handler_ms": r(st.median(e[0] for e in events)),
        "median_paint_ms": r(st.median(e[1] for e in events)),
        "median_other_ms": r(st.median(e[2] for e in events)),
        "median_gpu_ms": r(st.median(e[3] for e in events)),
        "paints_per_event": r(sum(e[4] for e in events) / len(events)),
        "median_hover_compute_ms": r(st.median(e[5] for e in events)),
        "p95_hover_compute_ms": r(_pct([e[5] for e in events], 0.95)),
    }


# ---- the driver -------------------------------------------------------------

def _surface_format(vsync: bool) -> None:
    """The context ``main._configure_surface_format`` asks for (GL 3.3 core,
    24-bit depth, 8-bit stencil) — measured on anything else, the numbers
    describe some other app. Plus the swap interval: with vsync every frame
    waits for the monitor's refresh (13.3 ms at 75 Hz), a floor that hides
    the real cost of the frame under it, so it is off unless asked for."""
    from PySide6.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSwapInterval(1 if vsync else 0)
    QSurfaceFormat.setDefaultFormat(fmt)


class Driver:
    def __init__(self, width=1600, height=900, vsync=False):
        from PySide6.QtWidgets import QApplication
        _surface_format(vsync)
        self.app = QApplication.instance() or QApplication([])
        self.app.setApplicationName("IngeTrazo-bench")   # own settings
        self.app.setOrganizationName("IngeTrazo-bench")
        # No autosave: a run killed mid-gesture would leave a slot behind,
        # and the next open of that document would stop on the «recover the
        # auto-saved copy?» dialog instead of measuring.
        from PySide6.QtCore import QSettings
        st_ = QSettings()
        st_.setValue("general/autosave", "0")
        st_.setValue("general/backup", "0")
        from views.main_window import MainWindow
        self.win = MainWindow()
        self.vp = self.win.viewport
        self.win.resize(width, height)
        self.win.show()
        for _ in range(100):
            self.app.processEvents()
            if self.vp._gl is not None:
                break
            time.sleep(0.02)
        if self.vp._gl is None:
            raise SystemExit("no GL context")
        self.renderer = self._renderer()
        # Every paintGL timed where it happens: inside repaint() (the frame
        # this event asked for) or later in the queue (one an update() or a
        # timer scheduled) — the slices alone cannot tell those apart.
        self.paints = []
        paint_gl = self.vp.paintGL

        def timed_paint():
            t0 = time.perf_counter()
            paint_gl()
            self.paints.append((time.perf_counter() - t0) * 1e3)
        self.vp.paintGL = timed_paint

    def _renderer(self):
        from PySide6.QtGui import QOpenGLContext
        self.vp.makeCurrent()
        try:
            f = QOpenGLContext.currentContext().functions()
            return {"vendor": f.glGetString(0x1F00),
                    "renderer": f.glGetString(0x1F01),
                    "version": f.glGetString(0x1F02)}
        except Exception:  # noqa: BLE001 — informative only
            return {}
        finally:
            self.vp.doneCurrent()

    # -- one event, three slices
    def _finish(self):
        self.vp.makeCurrent()
        try:
            self.vp.context().functions().glFinish()
        finally:
            self.vp.doneCurrent()

    def step(self, send):
        """One event, timed to the frame it caused being on screen:
        ``(handler, paint, other, gpu, paints, hover)`` in ms. The paint runs in
        the event loop (QOpenGLWidget's repaint() only schedules it), so
        the loop is run and every paintGL in it timed apart from the rest
        of what the event left queued; glFinish then waits for the GPU."""
        self.paints.clear()
        hover_t = getattr(self.vp, "_hover_last_t", None)
        t0 = time.perf_counter()
        send()
        t1 = time.perf_counter()
        self.app.processEvents()
        # A pointer move that came too soon after the last one is parked
        # (``_pending_hover``) and run by a timer — the viewport's own
        # coalescing. What the hand waits for is the screen catching up
        # with the pointer, so the parked move is waited for and counted.
        limit = t1 + 0.5
        while (getattr(self.vp, "_pending_hover", None) is not None
               and time.perf_counter() < limit):
            time.sleep(0.0002)
            self.app.processEvents()
        t2 = time.perf_counter()
        self._finish()
        t3 = time.perf_counter()
        paint = sum(self.paints)
        # The hover pass's own cost, as the viewport measures it (pick +
        # snap): "other" minus this is the coalescing wait, not compute.
        hover = (getattr(self.vp, "_hover_cost", 0.0) * 1e3
                 if getattr(self.vp, "_hover_last_t", None) != hover_t
                 else 0.0)
        return ((t1 - t0) * 1e3, paint, (t2 - t1) * 1e3 - paint,
                (t3 - t2) * 1e3, len(self.paints), hover)

    def settle(self, ms=150):
        end = time.perf_counter() + ms / 1e3
        while time.perf_counter() < end:
            self.app.processEvents()
            time.sleep(0.005)

    # -- synthetic input
    def _send(self, ev):
        from PySide6.QtWidgets import QApplication
        QApplication.sendEvent(self.vp, ev)

    def mouse(self, kind, x, y, button=None, buttons=None, mods=None):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        t = {"press": QEvent.MouseButtonPress,
             "release": QEvent.MouseButtonRelease,
             "move": QEvent.MouseMove}[kind]
        pos = QPointF(x, y)
        glob = QPointF(self.vp.mapToGlobal(pos.toPoint()))
        self._send(QMouseEvent(t, pos, glob,
                               button if button is not None else Qt.NoButton,
                               buttons if buttons is not None else Qt.NoButton,
                               mods if mods is not None else Qt.NoModifier))

    def wheel(self, x, y, notches):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        pos = QPointF(x, y)
        glob = QPointF(self.vp.mapToGlobal(pos.toPoint()))
        self._send(QWheelEvent(pos, glob, QPoint(0, 0),
                               QPoint(0, 120 * notches), Qt.NoButton,
                               Qt.NoModifier, Qt.NoScrollPhase, False))

    def key(self, key, mods=None):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        m = mods if mods is not None else Qt.NoModifier
        self._send(QKeyEvent(QEvent.KeyPress, key, m))
        self._send(QKeyEvent(QEvent.KeyRelease, key, m))

    # -- document and camera
    def open(self, path):
        t0 = time.perf_counter()
        ok = self.win.open_path(Path(path))
        self.app.processEvents()
        open_s = time.perf_counter() - t0
        if ok is False:
            raise SystemExit(f"could not open {path}")
        self.home()
        first = sum(self.step(self.vp.update)[:4]) / 1e3
        self.settle(500)
        return open_s, first

    def home(self):
        sc = self.vp.scene
        sc.selection.clear()
        if hasattr(self.vp.camera, "set_view"):
            self.vp.camera.set_view("iso")
        lo, hi = sc.bounds()
        self.vp.camera.fit_to(lo, hi)
        self.vp.update()
        self.settle()

    def model_points(self, n, seed=7):
        """``n`` pixels that land on the model: centroids of random faces,
        projected, kept when on screen and in front."""
        import numpy as np
        rng = random.Random(seed)
        groups = [g for g in self.vp.scene.groups if g.mesh.faces]
        cand = []
        for _ in range(n * 8):
            g = rng.choice(groups)
            f = rng.choice(g.mesh.faces)
            c = f.centroid()
            if g.xform is not None:
                c = g.xform.map(c)
            cand.append((c.x(), c.y(), c.z()))
        px, py, ok = self.vp._project_px(np.asarray(cand, dtype=float))
        W, H = self.vp.width(), self.vp.height()
        pts = [(float(x), float(y)) for x, y, k in zip(px, py, ok)
               if k and 20 < x < W - 20 and 20 < y < H - 20]
        if len(pts) < n:
            pts += [(W * rng.uniform(0.3, 0.7), H * rng.uniform(0.3, 0.7))
                    for _ in range(n - len(pts))]
        return pts[:n]


# ---- gestures ---------------------------------------------------------------

def g_orbit(d, pts):
    from PySide6.QtCore import Qt
    cx, cy = pts[0]
    ev = [d.step(lambda: d.mouse("press", cx, cy, Qt.MiddleButton,
                                 Qt.MiddleButton))]
    x, y = cx, cy
    for i in range(60):
        x, y = x + (6 if i < 30 else -6), y + 2 * (1 if i % 20 < 10 else -1)
        ev.append(d.step(lambda x=x, y=y: d.mouse(
            "move", x, y, Qt.NoButton, Qt.MiddleButton)))
    ev.append(d.step(lambda: d.mouse("release", x, y, Qt.MiddleButton,
                                     Qt.NoButton)))
    return ev


def g_pan(d, pts):
    from PySide6.QtCore import Qt
    cx, cy = pts[0]
    sh = Qt.ShiftModifier
    ev = [d.step(lambda: d.mouse("press", cx, cy, Qt.MiddleButton,
                                 Qt.MiddleButton, sh))]
    x, y = cx, cy
    for i in range(40):
        x, y = x + (5 if i < 20 else -5), y + (3 if i < 20 else -3)
        ev.append(d.step(lambda x=x, y=y: d.mouse(
            "move", x, y, Qt.NoButton, Qt.MiddleButton, sh)))
    ev.append(d.step(lambda: d.mouse("release", x, y, Qt.MiddleButton,
                                     Qt.NoButton, sh)))
    return ev


def g_zoom(d, pts):
    x, y = pts[1]
    return ([d.step(lambda: d.wheel(x, y, 1)) for _ in range(15)]
            + [d.step(lambda: d.wheel(x, y, -1)) for _ in range(15)])


def _hover(d, pts, tool):
    d.win._activate_tool(tool)
    d.settle(50)
    return [d.step(lambda p=p: d.mouse("move", p[0], p[1])) for p in pts[:60]]


def g_hover_select(d, pts):
    return _hover(d, pts, "select")


def g_hover_line(d, pts):
    ev = _hover(d, pts, "line")
    d.win._activate_tool("select")
    return ev


def g_click_select(d, pts):
    from PySide6.QtCore import Qt
    d.win._activate_tool("select")
    ev = []
    for x, y in pts[:20]:
        ev.append(d.step(lambda x=x, y=y: d.mouse(
            "press", x, y, Qt.LeftButton, Qt.LeftButton)))
        ev.append(d.step(lambda x=x, y=y: d.mouse(
            "release", x, y, Qt.LeftButton, Qt.NoButton)))
    d.vp.scene.selection.clear()
    return ev


def g_move(d, pts):
    """Select an object with a click, then Move it: click, 30 moves (the
    geometry follows live), click. Raises if no undo step landed — a Move
    that grabbed nothing would time an idle pointer and call it a move."""
    from PySide6.QtCore import Qt
    x, y = pts[2]
    click = lambda x, y: (d.mouse("press", x, y, Qt.LeftButton,  # noqa: E731
                                  Qt.LeftButton),
                          d.mouse("release", x, y, Qt.LeftButton,
                                  Qt.NoButton))
    d.vp.scene.selection.clear()
    d.win._activate_tool("select")
    click(x, y)
    d.win._activate_tool("move")
    d.settle(50)
    steps = len(d.vp.history.undo_stack)
    ev = [d.step(lambda: d.mouse("move", x, y))]
    ev.append(d.step(lambda: click(x, y)))
    for i in range(30):
        ev.append(d.step(lambda i=i: d.mouse("move", x + 3 * (i + 1),
                                             y - (i + 1))))
    ev.append(d.step(lambda: click(x + 90, y - 30)))
    if len(d.vp.history.undo_stack) <= steps:
        raise RuntimeError("move: nothing was moved (no undo step)")
    return ev


def g_undo(d, pts):
    from PySide6.QtCore import Qt
    ev = [d.step(lambda: d.key(Qt.Key_Z, Qt.ControlModifier))]
    d.win._activate_tool("select")
    return ev


def run_model(d, path, repeat):
    open_s, first_s = d.open(path)
    sc = d.vp.scene
    faces = sum(len(g.mesh.faces) for g in sc.groups)
    pts = d.model_points(60)
    out = {"document": Path(path).name, "faces_drawn": faces,
           "objects": len(sc.groups), "open_s": round(open_s, 2),
           "first_frame_ms": round(first_s * 1e3, 1), "gestures": {}}
    print(f"\n{Path(path).name}: {faces:,} faces, {len(sc.groups)} objects, "
          f"open {open_s:.2f} s, first frame {first_s * 1e3:.0f} ms",
          flush=True)
    undo_runs = []
    for name in GESTURES:
        runs = []
        for _ in range(repeat):
            if name == "undo":                  # timed right after each move
                runs = undo_runs
                break
            d.home()
            runs.append(globals()[f"g_{name}"](d, pts))
            if name == "move":                  # and it puts the building back
                undo_runs.append(g_undo(d, pts))
        # Each event's best run: noise only ever adds time.
        best = [min(evs, key=lambda e: e[0] + e[1] + e[2] + e[3])
                for evs in zip(*runs)]
        row = out["gestures"][name] = summarise(best)
        print(f"  {name:13} median {row['median_ms']:7.1f}  "
              f"p95 {row['p95_ms']:7.1f}  max {row['max_ms']:7.1f} ms  "
              f">16ms {row['over_16ms_pct']:5.1f}%   "
              f"[handler {row['median_handler_ms']:.1f} / paint "
              f"{row['median_paint_ms']:.1f} / other "
              f"{row['median_other_ms']:.1f} / gpu "
              f"{row['median_gpu_ms']:.1f}]  paints/event "
              f"{row['paints_per_event']:.1f}  hover compute "
              f"{row['median_hover_compute_ms']:.1f}/"
              f"{row['p95_hover_compute_ms']:.1f}", flush=True)
    return out


# ---- compare ----------------------------------------------------------------

def compare(a_path, b_path):
    a = json.loads(Path(a_path).read_text(encoding="utf-8"))
    b = json.loads(Path(b_path).read_text(encoding="utf-8"))
    print(f"{a.get('label')} ({a.get('commit')})  ->  "
          f"{b.get('label')} ({b.get('commit')})")
    bm = {m["document"]: m for m in b["models"]}
    for ma in a["models"]:
        mb = bm.get(ma["document"])
        if mb is None:
            continue
        print(f"\n{ma['document']}  open {ma['open_s']} -> {mb['open_s']} s")
        for g, ra in ma["gestures"].items():
            rb = mb["gestures"].get(g)
            if not rb:
                continue
            for k in ("median_ms", "p95_ms"):
                va, vb = ra[k], rb[k]
                ch = (vb - va) / va * 100 if va else 0.0
                flag = ("  <- SLOWER" if ch > 25 else
                        "  faster" if ch < -25 else "")
                print(f"  {g:13} {k:10} {va:8.1f} -> {vb:8.1f}  "
                      f"({ch:+.0f}%){flag}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out", nargs="?")
    ap.add_argument("models", nargs="*")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--label", default="")
    ap.add_argument("--vsync", action="store_true",
                    help="wait for the monitor refresh, as the app does")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    args = ap.parse_args(argv)
    if args.compare:
        compare(*args.compare)
        return 0
    if not args.out or not args.models:
        ap.error("give an output .json and at least one model")
    d = Driver(vsync=args.vsync)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                            cwd=ROOT, capture_output=True,
                            text=True).stdout.strip()
    res = {"label": args.label or commit, "commit": commit,
           "date": time.strftime("%Y-%m-%d %H:%M"),
           "machine": {"os": platform.platform(),
                       "cpu": platform.processor(),
                       "python": platform.python_version(),
                       **d.renderer},
           "repeat": args.repeat, "vsync": args.vsync,
           "models": [run_model(d, m, args.repeat) for m in args.models]}
    Path(args.out).write_text(json.dumps(res, indent=1, ensure_ascii=False),
                              encoding="utf-8")
    print(f"\n-> {args.out}")
    d.win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
