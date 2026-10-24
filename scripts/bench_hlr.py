# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Time the sheet's hidden-line pass (core.hlr.hlr_drawing) on a real
document, view by view, and optionally save or compare its output.

    venv/bin/python scripts/bench_hlr.py ~/Descargas/plaza.igz \
        [--views top,iso] [--save ref.npz] [--compare ref.npz]

``--save`` keeps every view's segments/world/kinds so a faster kernel can
be checked against this one: ``--compare`` reports the largest coordinate
difference and any change in the number or the kind of segments."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from core.camera import OrbitCamera  # noqa: E402
from core.hlr import collect_geometry, hlr_drawing  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402


def camera_for(scene, view: str) -> OrbitCamera:
    cam = OrbitCamera()
    cam.set_view(view)
    lo, hi = scene.bounds()
    if lo is not None:
        cam.fit_to(lo, hi)
    return cam


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("document")
    ap.add_argument("--views", default="top,iso")
    ap.add_argument("--save")
    ap.add_argument("--compare")
    args = ap.parse_args()

    scene = Scene()
    igz.load_into(scene, Path(args.document).expanduser())
    t = time.perf_counter()
    tris, hard, soft = collect_geometry(scene)
    print(f"collect_geometry: {time.perf_counter() - t:.2f} s — "
          f"{len(tris)} triangles, {len(hard)} hard, {len(soft)} soft edges")

    out = {}
    for view in args.views.split(","):
        cam = camera_for(scene, view)
        t = time.perf_counter()
        d = hlr_drawing(scene, cam)
        dt = time.perf_counter() - t
        kinds = np.bincount(d.kinds, minlength=5) if len(d.kinds) else []
        print(f"{view:>6}: {dt:8.2f} s — {len(d.segs)} segments, "
              f"kinds {list(kinds)}")
        out[f"{view}_segs"] = d.segs
        out[f"{view}_world"] = d.world
        out[f"{view}_kinds"] = d.kinds

    if args.save:
        np.savez_compressed(args.save, **out)
        print("saved", args.save)
    if args.compare:
        ref = np.load(args.compare)
        for view in args.views.split(","):
            a, b = ref[f"{view}_segs"], out[f"{view}_segs"]
            ka, kb = ref[f"{view}_kinds"], out[f"{view}_kinds"]
            if a.shape != b.shape:
                print(f"{view}: DIFFERENT count {len(a)} -> {len(b)}")
                continue
            print(f"{view}: max |Δ| = {np.abs(a - b).max() if len(a) else 0:.3g}, "
                  f"kinds equal = {bool((ka == kb).all())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
