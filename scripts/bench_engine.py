# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Where the engine spends its time on a real document: the model-side
operations, timed, each with the functions that cost the most (cProfile).

The viewport side (orbit, hover with inferences, move, undo) is
``bench_interaction.py``; this one needs no window. Run it once per engine
to compare (the engine is fixed per process):

    INGETRAZO_RUST=0 venv/bin/python scripts/bench_engine.py ~/Descargas/plaza.igz \\
        --out py.json
    INGETRAZO_RUST=1 venv/bin/python scripts/bench_engine.py ~/Descargas/plaza.igz \\
        --out rs.json

``--only open,save`` picks operations; ``--top 15`` the rows of each
profile; ``--no-profile`` times without cProfile (its overhead is ~2×
on Python-heavy code, so the times to quote are the unprofiled ones)."""
from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Never the user's own settings (see bench_session.py).
_tmp = tempfile.mkdtemp(prefix="ingetrazo-bench-engine-")
os.environ["XDG_DATA_HOME"] = _tmp

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.IniFormat)
for _scope in (QSettings.UserScope, QSettings.SystemScope):
    QSettings.setPath(QSettings.IniFormat, _scope, _tmp)
_app = QApplication.instance() or QApplication([])

from core._native import engine  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402


def _biggest_group(scene):
    from core.group import Group, iter_placements
    best, n = None, -1
    for g in scene.groups:
        if not isinstance(g, Group):
            continue
        k = sum(len(m.mesh.faces) for m, _ in iter_placements(g))
        if k > n:
            best, n = g, k
    return best


def op_open(ctx):
    scene = Scene()
    igz.load_into(scene, ctx["doc"])
    ctx["scene"] = scene


def op_save(ctx):
    igz.save_scene(ctx["scene"], Path(_tmp) / "out.igz")


def op_stl(ctx):
    from formats.stl import save_stl
    save_stl(ctx["scene"], Path(_tmp) / "out.stl")


def op_obj(ctx):
    from formats.obj import save_obj
    save_obj(ctx["scene"], Path(_tmp) / "out.obj")


def op_collect(ctx):
    from core.hlr import collect_geometry
    collect_geometry(ctx["scene"])


def _hlr(ctx, view):
    from core.camera import OrbitCamera
    from core.hlr import hlr_drawing
    scene = ctx["scene"]
    cam = OrbitCamera()
    cam.set_view(view)
    lo, hi = scene.bounds()
    if lo is not None:
        cam.fit_to(lo, hi)
    hlr_drawing(scene, cam)


def op_hlr_top(ctx):
    _hlr(ctx, "top")


def op_hlr_iso(ctx):
    _hlr(ctx, "iso")


def op_intersect_find(ctx):
    """Intersect Faces ▸ With Selection, everything selected (#541): the
    crossings."""
    from core.intersect import WITH_SELECTION, segments_for
    scene = ctx["scene"]
    scene.selection.clear()
    scene.selection.update(scene.mesh.faces)
    scene.selection.update(scene.groups)
    ctx["segs"] = segments_for(scene, WITH_SELECTION)


def op_intersect_apply(ctx):
    """…and adding them as edges (one undo step), as the menu does."""
    from core.edits import build_add_edges
    from core.history import History
    scene = ctx["scene"]
    from views.main_window import _WELD_LENGTH
    segs = [(a, b) for a, b in ctx.get("segs", [])
            if (b - a).length() >= _WELD_LENGTH][:ctx["apply_cap"]]
    ctx["applied"] = len(segs)
    if segs:
        History(scene).execute(build_add_edges(scene, segs,
                                               detect_faces=True))


def op_orient(ctx):
    """Orient Faces over the biggest group's meshes."""
    from core.group import iter_placements
    from core.orient import orient_outward
    for m, _ in iter_placements(_biggest_group(ctx["scene"])):
        orient_outward(m.mesh)


def op_triangulate(ctx):
    """Every face triangulated again (what a full GPU rebuild asks)."""
    from core.group import iter_placements
    scene = ctx["scene"]
    for f in scene.mesh.faces:
        f.triangulate()
    for g in scene.groups:
        for m, _ in iter_placements(g):
            for f in m.mesh.faces:
                f.triangulate()


class _StubVP:
    """What PushPullTool._commit needs of a viewport (tests/test_fuzz_engine)."""

    def __init__(self, scene, history):
        self.scene, self.history = scene, history

    def update(self):
        pass

    def set_hover(self, entity):
        pass

    def set_suppressed_faces(self, faces):
        pass

    def flash_status(self, text, msec=2500):
        pass


def push_faces(scene, n=12, seed=3, after=None):
    """Push/pull ``n`` faces of the biggest group (seeded): the faces
    facing up/sideways of its largest meshes, ±0.3 m alternately, each one
    commit as the tool does it. Returns a signature of the result."""
    import random

    from core.group import iter_placements
    from core.history import History
    from tools.pushpull import PushPullTool
    rng = random.Random(seed)
    hist = History(scene)
    g = _biggest_group(scene)
    groups = sorted({id(m): m for m, _ in iter_placements(g)}.values(),
                    key=lambda m: -len(m.mesh.faces))[:4]
    done = 0
    for k in range(n):
        grp = groups[k % len(groups)]
        faces = [f for f in grp.mesh.faces
                 if not f.interior and f.area() > 0.05]
        if not faces:
            continue
        face = rng.choice(faces)
        tool = PushPullTool()
        tool.base_face = face
        tool.dragging = True
        tool._group = grp
        target = tool._target_scene(scene)
        tool._anchor = face.centroid()
        tool._normal = face.normal()
        tool._attached, tool._prism_cap = tool._classify_base(target)
        tool._cap_positions = tool._cap_loop_positions(face)
        tool._keep_base = False
        tool._compute_inward_limit(target)
        tool.extrusion = 0.3 if k % 2 == 0 else -0.1
        tool._clamp_extrusion()
        if abs(tool.extrusion) < 1e-6:
            tool._reset()
            continue
        tool._commit(_StubVP(scene, hist))
        done += 1
        if after is not None:
            after(k, grp, face)
    return done, [mesh_signature(grp.mesh) for grp in groups]


def _loop_key(points) -> tuple:
    """A loop's points rounded, started at its smallest point: the same
    face reads the same whichever vertex its loop happens to start on
    (that start is not stable between runs of the same edit)."""
    pts = [tuple(round(c, 6) for c in p.toTuple()) for p in points]
    if not pts:
        return ()
    k = pts.index(min(pts))
    return tuple(pts[k:] + pts[:k])


def mesh_signature(m) -> tuple:
    """Faces (outer loop, holes, interior mark) and counts of a mesh, in an
    order that does not depend on how the run built them."""
    faces = sorted((_loop_key(f.vertices),
                    tuple(sorted(_loop_key(h) for h in f.holes)),
                    bool(f.interior)) for f in m.faces)
    return (len(m.faces), len(m.edges), faces)


def op_pushpull(ctx):
    ctx["pushes"], ctx["push_sig"] = push_faces(ctx["scene"])


OPS = [("open", op_open), ("save", op_save), ("stl", op_stl),
       ("obj", op_obj), ("collect", op_collect), ("hlr_top", op_hlr_top),
       ("hlr_iso", op_hlr_iso), ("triangulate", op_triangulate),
       ("orient", op_orient), ("intersect_find", op_intersect_find),
       ("pushpull", op_pushpull),
       ("intersect_apply", op_intersect_apply)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("document")
    ap.add_argument("--only", default="")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--no-profile", action="store_true")
    ap.add_argument("--apply-cap", type=int, default=2000,
                    help="crossings added by intersect_apply (all: >15 min)")
    ap.add_argument("--out")
    args = ap.parse_args()
    only = set(filter(None, args.only.split(",")))
    ctx = {"doc": Path(args.document).expanduser(),
           "apply_cap": args.apply_cap}
    res = {"engine": engine(), "document": str(ctx["doc"]),
           "commit": os.popen("git rev-parse --short HEAD").read().strip(),
           "ops": {}}
    print(f"engine: {res['engine']}  commit {res['commit']}")
    for name, fn in OPS:
        if only and name not in only and name != "open":
            continue
        prof = None if args.no_profile else cProfile.Profile()
        t = time.perf_counter()
        if prof:
            prof.enable()
        try:
            fn(ctx)
            err = None
        except Exception as exc:  # noqa: BLE001 — report, go on
            err = f"{type(exc).__name__}: {exc}"
        if prof:
            prof.disable()
        dt = time.perf_counter() - t
        row = {"s": round(dt, 3)}
        if err:
            row["error"] = err
        if name == "intersect_find":
            row["crossings"] = len(ctx.get("segs", []))
        if name == "pushpull":
            row["pushes"] = ctx.get("pushes", 0)
        if name == "intersect_apply":
            row["applied"] = ctx.get("applied", 0)
        if prof:
            buf = io.StringIO()
            st = pstats.Stats(prof, stream=buf)
            st.sort_stats("tottime")
            rows = []
            for (file, line, func), (_cc, nc, tt, ct, _c) in sorted(
                    st.stats.items(), key=lambda kv: -kv[1][2])[:args.top]:
                rows.append({"func": f"{Path(file).name}:{line}:{func}",
                             "calls": nc, "self_s": round(tt, 3),
                             "cum_s": round(ct, 3)})
            row["top"] = rows
        res["ops"][name] = row
        extra = "".join(f"  {k}={row[k]}" for k in ("crossings", "applied",
                                                    "pushes",
                                                    "error") if k in row)
        print(f"{name:>16}: {dt:9.2f} s{extra}")
        for r in row.get("top", [])[:5]:
            print(f"{'':>18}{r['self_s']:8.2f} s self  {r['func']}")
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1, ensure_ascii=False))
        print("saved", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
