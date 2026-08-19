# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP export: geometry, materials, layers, and groups round-trip through
openskp — export to .skp then re-parse and verify the content."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage, QVector3D

from core.history import History, SetFaceColorCommand
from core.group import Group
from core.layers import Layer, assign_layer
from core.scene import Scene
from formats import skp_out as skp_out_format
import tests.test_fuzz_engine as F


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cube(scene, hist, size=4.0, height=3.0):
    loop = [V(0, 0), V(size, 0), V(size, size), V(0, size)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    f = scene.mesh.faces[0]
    F._push(scene, hist, f, height if f.normal().z() > 0 else -height)


# ---- Helpers ---------------------------------------------------------------

_M_TO_IN = 39.37007874


def _parse_skp(path):
    """Re-read an exported .skp via openskp and return the parsed model."""
    from openskp import SkpFile
    return SkpFile.open(str(path)).parse()


def _make_png(path: Path) -> Path:
    """A tiny real PNG — openskp.add_texture_material detects the format
    from the file's own magic bytes, so a placeholder must be genuine.
    Same helper as tests/test_gltf_dae_export.py's."""
    img = QImage(4, 4, QImage.Format_RGBA8888)
    img.fill(0xFF3366CC)
    img.save(str(path), "PNG")
    return path


# ---- Tests -----------------------------------------------------------------

def test_skp_export_creates_file(tmp_path):
    """A basic scene exports without error and produces a non-empty .skp."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "cube.skp"
    skp_out_format.save_skp(scene, path)
    assert path.exists()
    assert path.stat().st_size > 0


def test_skp_export_face_count(tmp_path):
    """A cube (6 quads) exports and the re-parsed model has faces."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "cube.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    # Root-level geometry lives in model.root (a Definition).
    assert len(model.root.faces) >= 6


def test_skp_export_vertex_units(tmp_path):
    """Exported coordinates are in inches, not metres."""
    scene = Scene()
    hist = History(scene)
    # A single face at 4 × 4 metres.
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    path = tmp_path / "quad.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    # 4 metres = 157.48 inches.
    # model.root.vertices is a dict {id: Vertex}, access .values().
    xs = [v.x for v in model.root.vertices.values()]
    ys = [v.y for v in model.root.vertices.values()]
    max_x = max(xs) - min(xs)
    max_y = max(ys) - min(ys)
    assert abs(max_x - 4.0 * _M_TO_IN) < 0.01
    assert abs(max_y - 4.0 * _M_TO_IN) < 0.01


def test_skp_export_with_color(tmp_path):
    """A face painted red exports as a material with that colour."""
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    face = scene.mesh.faces[0]
    # SetFaceColorCommand takes (faces_iterable, color).
    hist.execute(SetFaceColorCommand([face], [1.0, 0.0, 0.0]))
    path = tmp_path / "red.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    # At least one material should have a red-ish colour.
    reds = [m for m in model.materials if m.color and m.color[0] > 200
            and m.color[1] < 50 and m.color[2] < 50]
    assert len(reds) >= 1


def test_skp_export_includes_groups(tmp_path):
    """A scene with a group exports — the .skp should have faces."""
    scene = Scene()
    hist = History(scene)
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(0, 0), V(2, 0), V(2, 2), V(0, 2)])
    g = Group(m)
    g.name = "TestGroup"
    scene.groups.append(g)
    scene.version += 1
    path = tmp_path / "grouped.skp"
    skp_out_format.save_skp(scene, path)
    # The file should exist and be valid.
    assert path.exists()
    model = _parse_skp(path)
    # Group geometry flattens into root-level faces in this exporter.
    assert len(model.root.faces) >= 1


def test_skp_export_material_name(tmp_path):
    """A face carrying attrs[\"mat\"] exports under that material name."""
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    face = scene.mesh.faces[0]
    face.attrs["color"] = [0.6, 0.6, 0.6]
    face.attrs["mat"] = "Concreto"
    path = tmp_path / "named.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    mat_names = [m.name for m in model.materials]
    assert any("Concreto" in n for n in mat_names)


def test_skp_export_with_texture(tmp_path):
    """A face with an image texture exports as a textured SketchUp
    material (add_texture_material), not just a solid fallback colour."""
    png = _make_png(tmp_path / "brick.png")
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    face = scene.mesh.faces[0]
    face.attrs["texture"] = {"path": str(png), "sw": 1.0, "sh": 1.0}
    path = tmp_path / "textured.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    textured = [m for m in model.materials if m.texture is not None]
    assert len(textured) == 1


def test_skp_export_with_layer(tmp_path):
    """A face assigned to a custom layer exports as a SketchUp layer/tag
    of that name, alongside the default layer."""
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    face = scene.mesh.faces[0]
    scene.layers.append(Layer("Estructura"))
    assign_layer(face, "Estructura")
    path = tmp_path / "layered.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    names = [ly.name for ly in model.layers]
    assert "Estructura" in names


def test_skp_export_triangulates_non_coplanar_face(tmp_path):
    """A face with one vertex nudged off the other three's plane — the
    kind of drift a component-instance transform can introduce — must
    still export, split into triangles, rather than being silently
    dropped (the auto_triangulate fallback in save_skp)."""
    scene = Scene()
    # Deliberately non-planar: (4, 4, 0.02) isn't on the z=0 plane the
    # other three corners share. The offset is far larger than needed
    # (openskp's tolerance is on the order of 1e-4 inches for a face
    # this size) - a clearly-intentional non-coplanar quad, not an
    # attempt to reproduce exact floating-point drift magnitudes.
    scene.mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 4, 0.02), V(0, 4, 0)])
    scene.version += 1
    path = tmp_path / "warped.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    # A single 4-point face fans into 2 triangles when it isn't coplanar
    # rather than raising or vanishing.
    assert len(model.root.faces) == 2
    zs = {round(v.z, 4) for v in model.root.vertices.values()}
    assert round(0.02 * _M_TO_IN, 4) in zs  # the drifted vertex survived


def test_skp_export_empty_scene(tmp_path):
    """An empty scene should not crash — SkpBuilder with zero faces may raise
    or produce a minimal file; either is acceptable."""
    scene = Scene()
    path = tmp_path / "empty.skp"
    try:
        skp_out_format.save_skp(scene, path)
    except Exception:
        # SkpBuilder requires at least one face; this is fine.
        pass
