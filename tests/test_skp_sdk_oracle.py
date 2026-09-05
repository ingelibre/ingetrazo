# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The SketchUp SDK as the oracle for texture placement.

Export the calibration faces, convert the ``.skp`` with skp2dae.exe (Trimble's
own ``SketchUpAPI.dll``, run under Wine — the converter the import already
falls back to) and compare the TEXCOORDs it writes with what the viewport
draws. openskp reading its own output is not proof: that is how three UV
defects survived every round-trip test until 2026-09-04. Skipped where the
converter is not installed (CI); on a dev machine this is the real "how will
SketchUp show it".
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PySide6.QtGui import QVector3D

from core.scene import Scene
from formats import skp_out as skp_out_format
from tests.test_skp_export import (_M_TO_IN, _assert_uvs_match_the_viewport,
                                   _calibration_faces, _make_png)

_NS = "{http://www.collada.org/2005/11/COLLADASchema}"


def _converter() -> list[str] | None:
    """Same search as ``MainWindow._find_skp_converter``: ``SKP2DAE_EXE``,
    ``~/.local/share/skp2dae/skp2dae.exe``, ``skp2dae`` on PATH."""
    candidates = []
    if os.environ.get("SKP2DAE_EXE"):
        candidates.append(Path(os.environ["SKP2DAE_EXE"]))
    candidates.append(Path.home() / ".local" / "share" / "skp2dae" / "skp2dae.exe")
    which = shutil.which("skp2dae")
    if which:
        candidates.append(Path(which))
    for cand in candidates:
        if not cand.exists():
            continue
        if cand.suffix.lower() == ".exe" and sys.platform != "win32":
            wine = shutil.which("wine")
            if wine:
                return [wine, str(cand)]
            continue
        return [str(cand)]
    return None


def _sdk_uvs(dae: Path):
    """``(point_metres, (s, t))`` for every triangle corner the SDK wrote
    with texture coordinates."""
    root = ET.parse(dae).getroot()
    byid = {el.get("id"): el for el in root.iter() if el.get("id")}

    def floats(src):
        return [float(t) for t in src.find(f"{_NS}float_array").text.split()]

    out = []
    for geom in root.iter(f"{_NS}geometry"):
        mesh = geom.find(f"{_NS}mesh")
        pos = None
        for inp in mesh.find(f"{_NS}vertices").findall(f"{_NS}input"):
            if inp.get("semantic") == "POSITION":
                d = floats(byid[inp.get("source")[1:]])
                pos = [(d[i], d[i + 1], d[i + 2]) for i in range(0, len(d), 3)]
        for prim in mesh.findall(f"{_NS}triangles"):
            offs, uvs = {}, None
            for inp in prim.findall(f"{_NS}input"):
                offs[inp.get("semantic")] = int(inp.get("offset", 0))
                if inp.get("semantic") == "TEXCOORD":
                    d = floats(byid[inp.get("source")[1:]])
                    uvs = [(d[i], d[i + 1]) for i in range(0, len(d), 2)]
            if uvs is None:
                continue
            stride = max(offs.values()) + 1
            idx = [int(t) for t in prim.find(f"{_NS}p").text.split()]
            for k in range(0, len(idx), stride):
                x, y, z = pos[idx[k + offs["VERTEX"]]]
                out.append((QVector3D(x / _M_TO_IN, y / _M_TO_IN, z / _M_TO_IN),
                            uvs[idx[k + offs["TEXCOORD"]]]))
    return out


@pytest.mark.skipif(_converter() is None, reason="skp2dae.exe (+ Wine) not installed")
@pytest.mark.parametrize("planar", [False, True], ids=["pinned", "planar"])
def test_sketchup_shows_the_textures_where_the_viewport_drew_them(tmp_path, planar):
    png = _make_png(tmp_path / "tile.png")
    scene = Scene()
    faces = _calibration_faces(scene, png, planar)
    skp = tmp_path / "calibration.skp"
    dae = tmp_path / "calibration.dae"
    skp_out_format.save_skp(scene, skp)
    run = subprocess.run(_converter() + [str(skp), str(dae)],
                         env={**os.environ, "WINEDEBUG": "-all"},
                         capture_output=True, text=True, timeout=180)
    assert dae.exists(), run.stdout + run.stderr
    samples = _sdk_uvs(dae)
    assert len(samples) == 11 * 6            # two triangles per square
    _assert_uvs_match_the_viewport(faces, samples, tol=1e-3)
