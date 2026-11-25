# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Compare Select All and native GL frames on identical synthetic solids.

Run this same script with --source pointing at upstream, the old PR and the
updated PR. Defaults: 1,035 independent groups and 49,680 faces. Settings and
extensions are isolated. A real OpenGL context is required; no timing gate is
applied because drivers and machines differ.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--label", default="candidate")
    parser.add_argument("--groups", type=int, default=1035)
    parser.add_argument("--boxes-per-group", type=int, default=8)
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.groups, args.boxes_per_group, args.frames) < 1:
        parser.error("groups, boxes-per-group and frames must be positive")
    sys.path.insert(0, str(args.source.resolve()))
    os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "xcb")
    os.environ["INGETRAZO_RUST"] = "0"
    with tempfile.TemporaryDirectory(prefix="ingetrazo-locked-bench-",
                                     ignore_cleanup_errors=True) as data:
        os.environ["XDG_DATA_HOME"] = data
        os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = data
        os.environ["INGETRAZO_CATEGORIES_DB"] = str(Path(data) / "categories.sqlite")
        from PySide6.QtCore import QSettings, Qt, qVersion
        from PySide6.QtGui import QVector3D as V
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        QSettings.setDefaultFormat(QSettings.IniFormat)
        for scope in (QSettings.UserScope, QSettings.SystemScope):
            QSettings.setPath(QSettings.IniFormat, scope, data)
        from core.group import Group
        from views.main_window import MainWindow
        win = MainWindow(defer_extensions=True)
        win._autosave_timer.stop()
        win.setAttribute(Qt.WA_DontShowOnScreen)
        win.resize(1280, 800)
        win.show()
        app.processEvents()
        vp, scene = win.viewport, win.viewport.scene
        assert vp.isValid(), "A native OpenGL context is required"
        scene.clear()
        scene.show_axes = False
        side = math.ceil(math.sqrt(args.groups))
        for i in range(args.groups):
            group = Group(name=f"Solid {i}")
            x0, y0 = (i % side) * 4, (i // side) * 4
            for box in range(args.boxes_per_group):
                x, y, z = x0 + (box % 2) * 1.2, y0 + ((box // 2) % 2) * 1.2, (box // 4) * 1.2
                points = [V(x + dx, y + dy, z + dz)
                          for dz in (0, 1) for dy in (0, 1) for dx in (0, 1)]
                for face in ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
                             (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)):
                    group.mesh.add_face([points[j] for j in face])
            scene.groups.append(group)
        scene.version += 1
        vp.camera.set_view("iso")
        vp.camera.fit_to(*scene.bounds())

        def frame(orbit=False):
            if orbit:
                vp.camera.orbit(0.5, 0.1, vp.height())
            vp.makeCurrent()
            try:
                vp.paintGL()
                vp._gl.glFinish()
            finally:
                vp.doneCurrent()

        def measure(fn, repeats):
            values = []
            for _ in range(repeats):
                start = time.perf_counter()
                fn()
                values.append((time.perf_counter() - start) * 1000)
            return {"median_ms": round(statistics.median(values), 3),
                    "max_ms": round(max(values), 3), "samples": repeats}

        result = {"label": args.label, "source": str(args.source.resolve()),
                  "commit": subprocess.check_output(
                      ["git", "-c", f"safe.directory={args.source.resolve().as_posix()}",
                       "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip(),
                  "platform": platform.platform(), "python": platform.python_version(),
                  "qt": qVersion(), "engine": "Python", "groups": args.groups,
                  "faces": sum(len(g.mesh.faces) for g in scene.groups),
                  "device_pixel_ratio": vp.devicePixelRatioF(), "scenarios": {}}
        def scenario(name, select):
            scene.clear_selection()
            select()
            cold = measure(frame, 1)
            frame()
            result["scenarios"][name] = {"first_frame": cold,
                "paint": measure(frame, args.frames),
                "orbit": measure(lambda: frame(True), args.frames)}

        scenario("none", lambda: None)
        result["select_all"] = measure(win._on_select_all, 3)
        scenario("all_ordinary", win._on_select_all)
        if hasattr(scene, "locked_selection"):
            group = scene.groups[0]
            group.locked = True
            scene.version += 1
            scenario("one_locked", lambda: scene.select([group]))
            scenario("all_with_one_locked", win._on_select_all)
        text = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text, flush=True)
        # Match the test runner: do not let a benchmark's hidden Qt windows
        # outlive the interpreter's teardown ordering.
        os._exit(0)


if __name__ == "__main__":
    main()
