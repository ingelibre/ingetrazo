# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The pencil draws where its tip is, at any screen scale.

On Linux the app runs under XWayland (xcb) by default, where Qt sees a
125 % laptop screen at a scale of 2. X11 takes a pixmap cursor's hotspot
in the image's own pixels, while Windows and Wayland take it in logical
pixels and scale it themselves. The hotspot was always handed over in
logical pixels, so under xcb a line started halfway to the pencil's tip
(Marco, 11-11: «en Windows el lápiz está donde está la punta, en Linux
está desfasado»). Here the cursor is drawn at a scale of 2 and the point
each platform clicks at, in the image's pixels, must be the tip."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = r"""
import json, sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv[:1])
from views import icons
real = icons.cursor_hotspot
out = {}
for platform in ("xcb", "wayland", "windows"):
    icons._cursor_cache.clear()
    icons.cursor_hotspot = (lambda h, s, d, platform=platform:
                            real(h, s, d, platform=platform))
    cur = icons.tool_cursor("line")
    img = cur.pixmap().toImage()
    dpr = cur.pixmap().devicePixelRatio()
    hot = cur.hotSpot()
    # Where the platform clicks, in the image's own pixels.
    k = 1.0 if platform == "xcb" else dpr
    at = (hot.x() * k, hot.y() * k)
    # The tip: the pencil points down and to the left, so its tip is the
    # drawn pixel farthest that way.
    best = None
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 128:
                v = y - x
                if best is None or v > best[0]:
                    best = (v, x, y)
    out[platform] = {"dpr": dpr, "at": at, "tip": best[1:]}
print(json.dumps(out))
"""


def test_the_pencil_draws_at_its_tip_on_every_platform_at_scale_two():
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen",
           "QT_SCALE_FACTOR": "2"}
    done = subprocess.run([sys.executable, "-c", CHILD], capture_output=True,
                          text=True, timeout=120, cwd=str(ROOT), env=env)
    assert done.returncode == 0, done.stderr[-2000:]
    res = json.loads(done.stdout.strip().splitlines()[-1])
    for platform, r in res.items():
        assert r["dpr"] == 2.0, r
        (ax, ay), (tx, ty) = r["at"], r["tip"]
        # Within the round end of the stroke and its halo: 3 logical
        # pixels. The point used to sit 30 image pixels from the tip.
        assert abs(ax - tx) <= 6 and abs(ay - ty) <= 6, (platform, r)
