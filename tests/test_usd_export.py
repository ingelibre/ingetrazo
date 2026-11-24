# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""USD export (``.usda`` / ``.usdz``): the model's structure, instancing,
materials, pictures, units and the package layout, all from generated
scenes. A last test opens the files with the reference USD library when it
is installed (``usd-core``); everything else needs nothing but the stdlib."""
from __future__ import annotations

import os
import re
import struct
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QImage, QMatrix4x4, QVector3D
from PySide6.QtWidgets import QApplication

_inst = QApplication.instance()
if _inst is None:
    _app = QApplication([])
elif not isinstance(_inst, QApplication):
    pytest.skip("a non-widget QGuiApplication is already active",
                allow_module_level=True)

from core.group import Group                                      # noqa: E402
from core.materials import Material                               # noqa: E402
from core.mesh import Mesh                                        # noqa: E402
from core.scene import Scene                                      # noqa: E402
from formats import usd                                           # noqa: E402
from georef.datum import SceneDatum                               # noqa: E402

PINK = (0.9, 0.3, 0.6)
BLUE = (0.1, 0.2, 0.9)


def _quad(mesh, x, y=0.0, attrs=None):
    f = mesh.add_face([QVector3D(x, y, 0), QVector3D(x + 1, y, 0),
                       QVector3D(x + 1, y + 1, 0), QVector3D(x, y + 1, 0)])
    if attrs:
        f.attrs.update(attrs)
    return f


def _at(x, y=0.0, z=0.0):
    m = QMatrix4x4()
    m.translate(QVector3D(x, y, z))
    return m


def _paint(name, color):
    return Material(name, color=color).face_attrs()


def _png(path: Path, fmt: str = "PNG") -> Path:
    img = QImage(4, 4, QImage.Format_RGBA8888)
    img.fill(0xFF3366CC)
    assert img.save(str(path), fmt)
    return path


def _chairs(paints=(None, None)):
    """Two copies of one component «Silla», 3 m apart."""
    scene = Scene()
    proto = Mesh()
    _quad(proto, 0)
    _quad(proto, 2, attrs=_paint("Ladrillo rojo", PINK))
    for i, paint in enumerate(paints):
        g = Group(proto, name=f"Silla {i + 1}")
        g.xform = _at(3 * i)
        if paint:
            g.material = _paint(*paint)
        scene.groups.append(g)
    return scene


def _layer(scene, **kw) -> str:
    text, _images = usd.build_layer(scene, "textures", **kw)
    return text


# ---- a tiny reader of the layer we write -----------------------------------------

_PRIM = re.compile(r'^( *)(def|class|over)\b(?: (\w+))? "([^"]+)"')


def _prims(text: str) -> dict:
    """Prim path → type name, from the indentation (four spaces a level)."""
    out: dict = {}
    stack: list[str] = []
    for line in text.splitlines():
        m = _PRIM.match(line)
        if not m:
            continue
        depth = len(m.group(1)) // 4
        stack[depth:] = [m.group(4)]
        out["/" + "/".join(stack)] = m.group(3) or ""
    return out


def _targets(text: str) -> list[str]:
    """Every path the layer points at: bindings, connections, references."""
    return re.findall(r"<(/[^>.]*)(?:\.[^>]*)?>", text)


def _block(text: str, head: str) -> str:
    """The lines of the prim whose header contains ``head``."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if head in line and _PRIM.match(line):
            indent = len(line) - len(line.lstrip())
            j = i + 1
            while not (lines[j].strip() == "}"
                       and len(lines[j]) - len(lines[j].lstrip()) == indent):
                j += 1
            return "\n".join(lines[i:j + 1])
    raise AssertionError(f"no prim {head!r}")


# ---- the layer -------------------------------------------------------------------

def test_layer_states_z_up_metres_and_default_prim():
    text = _layer(_chairs())
    assert text.startswith("#usda 1.0\n")
    assert 'upAxis = "Z"' in text
    assert "metersPerUnit = 1" in text
    assert 'defaultPrim = "Model"' in text
    assert _prims(text)["/Model"] == "Xform"


def test_braces_and_parentheses_balance():
    text = _layer(_chairs())
    assert text.count("{") == text.count("}")
    assert text.count("(") == text.count(")")
    assert text.count("[") == text.count("]")


def test_every_target_exists():
    """No binding, connection or reference points at a prim that is not in
    the file — a reader would drop the material or the copy."""
    scene = _chairs()
    _quad(scene.loose_mesh, 10, attrs=_paint("Ladrillo rojo", PINK))
    text = _layer(scene)
    prims = _prims(text)
    for target in _targets(text):
        assert target in prims, target


def test_prototype_never_points_outside_itself():
    """A referenced prototype may only point inside itself: a binding to
    /Model/Materials from inside it is an error in a USD reader."""
    text = _layer(_chairs())
    proto = _block(text, 'class "Prototypes"')
    for target in _targets(proto):
        assert target.startswith("/Prototypes/"), target


def test_mesh_is_triangles_with_corner_normals_and_no_subdivision():
    scene = Scene()
    _quad(scene.loose_mesh, 0)
    mesh = _block(_layer(scene), 'def Mesh "Mesh"')
    counts = re.search(r"faceVertexCounts = \[([^\]]*)\]", mesh).group(1)
    indices = re.search(r"faceVertexIndices = \[([^\]]*)\]", mesh).group(1)
    normals = re.search(r"normals = \[(.*?)\] \(", mesh, re.S).group(1)
    assert counts.split(", ") == ["3", "3"]
    assert len(indices.split(", ")) == 6
    assert normals.count("(") == 6                      # one per corner
    assert 'interpolation = "faceVarying"' in mesh
    assert 'subdivisionScheme = "none"' in mesh      # not smoothed into a blob
    assert "extent = [(0, 0, 0), (1, 1, 0)]" in mesh


def test_component_copies_share_one_prototype():
    text = _layer(_chairs())
    refs = re.findall(r"references = <([^>]+)>", text)
    assert len(refs) == 2 and len(set(refs)) == 1
    assert text.count("instanceable = true") == 2
    meshes = [p for p, t in _prims(text).items() if t == "Mesh"]
    assert len(meshes) == 1 and meshes[0].startswith("/Prototypes/")


def test_copies_keep_their_place():
    text = _layer(_chairs())
    second = _block(text, '"Silla_2"')
    assert "(3.0, 0, 0, 1.0)" in second                # translation row
    assert 'xformOpOrder = ["xformOp:transform"]' in second
    assert "xformOp" not in _block(text, '"Silla_1"')  # identity: none


def test_copies_in_different_paint_are_two_meshes():
    text = _layer(_chairs(paints=(("Rosa", PINK), ("Azul", BLUE))))
    assert "Prototypes" not in text
    assert "instanceable" not in text
    meshes = [p for p, t in _prims(text).items() if t == "Mesh"]
    assert len(meshes) == 2
    assert "Rosa" in _block(text, '"Silla_1"')
    assert "Azul" in _block(text, '"Silla_2"')


def test_materials_keep_their_names_and_colours():
    text = _layer(_chairs())
    mat = _block(text, 'def Material "Ladrillo_rojo"')
    assert 'ingetrazo_name = "Ladrillo rojo"' in mat
    assert "diffuseColor = (0.9, 0.3, 0.6)" in mat
    assert 'info:id = "UsdPreviewSurface"' in mat
    # Two materials on one mesh: one subset each, bound to its material.
    subsets = re.findall(r'def GeomSubset "(\w+)"', text)
    assert len(subsets) == 2 and "Ladrillo_rojo" in subsets


def test_nested_groups_nest_in_the_file():
    scene = Scene()
    proto = Mesh()
    _quad(proto, 0)
    inner = Group(proto, name="Puerta")
    top = Group(Mesh(), name="Habitación")
    top.adopt([inner])
    scene.groups.append(top)
    prims = _prims(_layer(scene))
    assert "/Model/Habitacion/Puerta/Mesh" in prims


def test_names_become_unique_ascii_prim_names():
    used: set = set()
    assert usd._ident("Muro sur", used) == "Muro_sur"
    assert usd._ident("Muro sur", used) == "Muro_sur_2"
    assert usd._ident("Cocína", used) == "Cocina"
    assert usd._ident("3 ventanas", used) == "_3_ventanas"
    assert usd._ident("", used) == "Prim"
    assert usd._ident("木", used) == "Prim_2"


def test_geolocation_rides_in_the_layer_data():
    scene = _chairs()
    scene.georef = SceneDatum(-15.6167, -71.9333, 3416.0)
    text = _layer(scene)
    assert "dictionary ingetrazo_geolocation" in text
    assert "double lat = -15.6167" in text
    assert "double lon = -71.9333" in text
    assert "double alt = 3416.0" in text
    assert "ingetrazo_geolocation" not in _layer(_chairs())


def test_glass_keeps_its_opacity():
    scene = Scene()
    attrs = _paint("Vidrio", (0.7, 0.8, 0.9))
    attrs["opacity"] = 0.3
    _quad(scene.loose_mesh, 0, attrs=attrs)
    assert "float inputs:opacity = 0.3" in _layer(scene)


def test_two_sided_paint_goes_out_single_sided():
    scene = Scene()
    f = _quad(scene.loose_mesh, 0, attrs=_paint("Rosa", PINK))
    f.attrs["back"] = _paint("Azul", BLUE)
    text = _layer(scene)
    one = _block(text, '"Mesh_one_sided"')
    assert "doubleSided = 0" in one
    assert '"Mesh"' not in text                       # nothing double-sided


def test_only_the_selection():
    scene = _chairs(paints=(("Rosa", PINK), ("Azul", BLUE)))
    text = _layer(scene, only={scene.groups[1]})
    assert '"Silla_2"' in text and '"Silla_1"' not in text


# ---- files -----------------------------------------------------------------------

def _textured_scene(tmp_path, fmt="PNG", suffix=".png"):
    img = _png(tmp_path / f"ladrillo{suffix}", fmt)
    scene = Scene()
    f = _quad(scene.loose_mesh, 0)
    f.attrs["texture"] = {"path": str(img), "sw": 1.0, "sh": 1.0}
    return scene


def test_usda_copies_its_pictures_beside_it(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    path = out / "casa.usda"
    usd.save_usda(_textured_scene(tmp_path), path)
    text = path.read_text(encoding="utf-8")
    assert "asset inputs:file = @./casa_textures/ladrillo.png@" in text
    assert (out / "casa_textures" / "ladrillo.png").read_bytes()[:4] == b"\x89PNG"
    assert "texCoord2f[] primvars:st" in text
    assert 'string inputs:varname = "st"' in text


def test_other_pictures_become_png(tmp_path):
    path = tmp_path / "casa.usda"
    usd.save_usda(_textured_scene(tmp_path, "BMP", ".bmp"), path)
    assert "@./casa_textures/ladrillo.png@" in path.read_text(encoding="utf-8")
    png = tmp_path / "casa_textures" / "ladrillo.png"
    assert png.read_bytes()[:4] == b"\x89PNG"


def test_unreadable_picture_falls_back_to_white(tmp_path):
    scene = Scene()
    f = _quad(scene.loose_mesh, 0)
    f.attrs["texture"] = {"path": str(tmp_path / "missing.png")}
    path = tmp_path / "casa.usda"
    usd.save_usda(scene, path)
    text = path.read_text(encoding="utf-8")
    assert "diffuseColor = (1, 1, 1)" in text and "UsdUVTexture" not in text
    assert not (tmp_path / "casa_textures").exists()


def _local_data_offsets(path: Path) -> dict:
    """Name → offset of the file's data, read from the local headers."""
    raw = path.read_bytes()
    out = {}
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            off = info.header_offset
            assert raw[off:off + 4] == b"PK\x03\x04"
            name_len, extra_len = struct.unpack_from("<HH", raw, off + 26)
            out[info.filename] = off + 30 + name_len + extra_len
    return out


def test_usdz_is_an_aligned_uncompressed_package(tmp_path):
    path = tmp_path / "Casa nueva.usdz"
    usd.save_usdz(_textured_scene(tmp_path), path)
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        assert infos[0].filename == "Casa_nueva.usda"   # the layer first
        assert all(i.compress_type == zipfile.ZIP_STORED for i in infos)
        names = [i.filename for i in infos]
        assert "textures/ladrillo.png" in names
        text = zf.read(names[0]).decode("utf-8")
        assert zf.testzip() is None
    for name, offset in _local_data_offsets(path).items():
        assert offset % 64 == 0, name
    # The layer points at the picture inside the package.
    assert "@textures/ladrillo.png@" in text


def test_usdz_without_pictures_is_just_the_layer(tmp_path):
    path = tmp_path / "sillas.usdz"
    usd.save_usdz(_chairs(), path)
    with zipfile.ZipFile(path) as zf:
        assert [i.filename for i in zf.infolist()] == ["sillas.usda"]


def test_bridge_exports_usd_by_suffix():
    from views.bridge_tools import EXPORT_SUFFIXES
    assert ".usdz" in EXPORT_SUFFIXES and ".usda" in EXPORT_SUFFIXES


# ---- the reference reader, when it is installed --------------------------------

def test_reference_reader_opens_both_files(tmp_path):
    pxr = pytest.importorskip("pxr")
    from pxr import Usd, UsdGeom, UsdShade               # noqa: F401
    scene = _chairs()
    img = _png(tmp_path / "ladrillo.png")
    f = _quad(scene.loose_mesh, 10)
    f.attrs["texture"] = {"path": str(img), "sw": 1.0, "sh": 1.0}
    for name, save in (("m.usda", usd.save_usda), ("m.usdz", usd.save_usdz)):
        path = tmp_path / name
        save(scene, path)
        stage = Usd.Stage.Open(str(path))
        assert stage.GetCompositionErrors() == []
        assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
        assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0
        copies = [stage.GetPrimAtPath(f"/Model/Silla_{i}/Geometry")
                  for i in (1, 2)]
        assert all(p.IsInstance() for p in copies)
        assert copies[0].GetPrototype() == copies[1].GetPrototype()
        meshes = [p for p in Usd.PrimRange(
            stage.GetPseudoRoot(), Usd.TraverseInstanceProxies())
            if p.IsA(UsdGeom.Mesh)]
        assert len(meshes) == 3                  # two chairs + loose
        for mesh in meshes:
            for sub in UsdGeom.Subset.GetAllGeomSubsets(UsdGeom.Imageable(mesh)):
                bound, _ = UsdShade.MaterialBindingAPI(
                    sub.GetPrim()).ComputeBoundMaterial()
                assert bound, sub.GetPath()
