# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Exports speak material NAMES: Concreto_visto, not mat0.

A face whose attrs carry a registry identity (attrs["mat"], core.materials)
must export under that name in all three interchange formats — sanitized to
the least common denominator (OBJ's .mtl chokes on whitespace) and unique.
Anonymous paints keep the classic matN, so old documents export unchanged."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.scene import Scene                                      # noqa: E402
from formats import dae as dae_format                             # noqa: E402
from formats import gltf as gltf_format                           # noqa: E402
from formats import obj as obj_format                             # noqa: E402
from formats.meshexport import export_names                       # noqa: E402


def _scene_two_materials():
    """A named 'Concreto visto' quad + an anonymous red quad."""
    scene = Scene()
    f1 = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                              QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    f1.attrs["color"] = (0.62, 0.60, 0.58)
    f1.attrs["mat"] = "Concreto visto"
    f2 = scene.mesh.add_face([QVector3D(3, 0, 0), QVector3D(5, 0, 0),
                              QVector3D(5, 2, 0), QVector3D(3, 2, 0)])
    f2.attrs["color"] = (0.8, 0.1, 0.1)
    return scene


# ---- export_names ---------------------------------------------------------

def test_names_sanitized_unique_and_fallback():
    mats = {
        ("color", (0.1,)): {"mat": "Concreto visto"},
        ("color", (0.2,)): {"mat": "Concreto visto"},   # same identity, other recipe
        ("color", (0.3,)): {},                          # anonymous
        ("color", (0.4,)): {"mat": "1º acabado / fino"},
    }
    names = list(export_names(mats).values())
    assert names[0] == "Concreto_visto"
    assert names[1] == "Concreto_visto_2"               # never silently merged
    assert names[2] == "mat2"                           # classic fallback
    assert names[3] == "m_1º_acabado___fino"            # digit-safe; UTF-8 kept


# ---- The three exporters --------------------------------------------------

def test_obj_mtl_uses_real_names(tmp_path):
    path = tmp_path / "m.obj"
    obj_format.save_obj(_scene_two_materials(), path)
    mtl = (tmp_path / "m.mtl").read_text()
    obj = path.read_text()
    assert "newmtl Concreto_visto" in mtl
    assert "usemtl Concreto_visto" in obj
    assert "mat1" in mtl                                # anonymous keeps matN
    assert "mat0" not in mtl                            # the named one is gone


def test_dae_material_names(tmp_path):
    path = tmp_path / "m.dae"
    dae_format.save_dae(_scene_two_materials(), path)
    xml = path.read_text()
    assert 'name="Concreto_visto"' in xml
    assert 'id="mat0"' in xml                           # ids stay NCName-safe


def test_gltf_material_names(tmp_path):
    path = tmp_path / "m.glb"
    gltf_format.save_glb(_scene_two_materials(), path)
    raw = path.read_bytes()
    # GLB: header (12 bytes) + JSON chunk [len, b"JSON", payload].
    import struct
    json_len = struct.unpack_from("<I", raw, 12)[0]
    doc = json.loads(raw[20:20 + json_len])
    names = [m["name"] for m in doc["materials"]]
    assert "Concreto_visto" in names
    assert any(n.startswith("mat") for n in names)      # anonymous fallback
