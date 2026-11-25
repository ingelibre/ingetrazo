# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Back-to-front ordering for the viewport's translucent material triangles."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(eq=False)
class TransparencyRun:
    start: int
    opacity: float
    centers: np.ndarray
    path: str | None = None
    shade: float = 1.0
    side: str = "both"

    @property
    def count(self) -> int:
        return len(self.centers) * 3


def transparency_run(parts, start, stride, opacity, path=None, shade=1.0, side="both"):
    """Keep only triangle centers; vertices remain in the existing GPU buffers."""
    centers = [np.frombuffer(raw, dtype=np.float32).reshape((-1, 3, stride))[:, :, :3].mean(axis=1)
               for raw in parts if raw]
    points = np.concatenate(centers) if centers else np.empty((0, 3), dtype=np.float32)
    return TransparencyRun(start, opacity, points, path, shade, side)


def transparency_draws(runs, eye, forward, sorted_triangles=False):
    """Return (run, first vertex, count), merging contiguous sorted triangles.

    Faster preserves material batches. Nicer orders triangle centers across
    colors, textures and front/back overrides, not just within each material.
    """
    runs = [run for run in runs if run.count]
    if not sorted_triangles or not runs:
        return [(run, run.start, run.count) for run in runs]
    centers = np.concatenate([run.centers for run in runs])
    owners = np.repeat(np.arange(len(runs)), [len(run.centers) for run in runs])
    starts = np.concatenate([run.start + np.arange(len(run.centers)) * 3 for run in runs])
    depths = (centers - np.asarray(eye)) @ np.asarray(forward)
    order = np.argsort(-depths, kind="stable")
    draws = []
    for index in order:
        run, start = runs[int(owners[index])], int(starts[index])
        if draws and draws[-1][0] is run and draws[-1][1] + draws[-1][2] == start:
            previous = draws[-1]
            draws[-1] = (run, previous[1], previous[2] + 3)
        else:
            draws.append((run, start, 3))
    return draws
