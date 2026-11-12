#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Measure box-selection scratch memory on a synthetic import-sized mesh.

    python scripts/bench_box_selection.py --triangles 1000000
    python scripts/bench_box_selection.py --triangles 1000000 --instance

Use --source /path/to/another/checkout to compare the same benchmark against
upstream. Input arrays are allocated before tracing. Bounds are measured
first; subsequent queries use that cached bound. Output is JSON per query.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import tracemalloc
from types import SimpleNamespace

import numpy as np
from PySide6.QtGui import QMatrix4x4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--triangles', type=int, default=1_000_000)
    parser.add_argument('--instance', action='store_true')
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.triangles < 1:
        parser.error('--triangles must be positive')
    sys.path.insert(0, str(args.source.resolve()))
    from tools.select import _box_group_fast, _local_bounds
    if args.instance:
        # Exclude module loading from the geometry scratch measurement.
        import views.viewport  # noqa: F401

    n, width = args.triangles, min(1000, args.triangles)
    height = (n + width - 1) // width
    v0 = np.zeros((n, 3))
    v0[:, 0], v0[:, 1] = np.arange(n) % width, np.arange(n) // width
    e1, e2 = np.tile([1., 0., 0.], (n, 1)), np.tile([0., 1., 0.], (n, 1))
    edges = np.empty((n * 2, 3), dtype=np.float32)
    edges[0::2], edges[1::2] = v0, v0 + e2
    chunk = dict(v0=v0, e1=e1, e2=e2, edges=edges.tobytes(), uid=1)
    del edges

    class Viewport:
        def _group_chunk(self, _group):
            return chunk

        def _project_px(self, points):
            return points[:, 0], points[:, 1], np.ones(len(points), dtype=bool)

    xf, dx, dy = None, 0, 0
    if args.instance:
        xf, dx, dy = QMatrix4x4(), 7, -3
        xf.translate(dx, dy, 0)
    vp = Viewport()
    group = SimpleNamespace(xform=xf, mesh=object(), billboard=False)

    def measure(name, fn):
        tracemalloc.start()
        try:
            start = time.perf_counter()
            result = fn()
            seconds = time.perf_counter() - start
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        print(json.dumps(dict(operation=name, triangles=n, instance=args.instance,
                              result=result, seconds=seconds,
                              peak_scratch_mib=peak / 1024**2)), flush=True)

    hit = (-1 + dx, -1 + dy, min(10, width * 0.5) + dx, min(10, height * 0.5) + dy)
    x, y = width // 2 + dx, height // 2 + dy
    miss = (x + 0.8, y + 0.8, x + 0.9, y + 0.9)
    measure('bounds', lambda: _local_bounds(chunk) is not None)
    measure('crossing_hit', lambda: _box_group_fast(vp, group, hit, True))
    measure('crossing_miss', lambda: _box_group_fast(vp, group, miss, True))
    measure('window_partial', lambda: _box_group_fast(vp, group, hit, False))


if __name__ == '__main__':
    main()
