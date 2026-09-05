# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP export: geometry, materials, layers, and groups round-trip through
openskp — export to .skp then re-parse and verify the content."""
from __future__ import annotations

from pathlib import Path

import pytest

from PySide6.QtGui import QImage, QMatrix4x4, QVector3D

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
    """A classic group exports as a SketchUp GROUP: its face lives in a
    definition placed by one instance, not flattened into root geometry."""
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
    model = _parse_skp(path)
    assert len(model.root.faces) == 0
    assert any(d.name == "TestGroup" and len(d.faces) == 1
               for d in model.definitions.values())
    assert len(model.root.instances) == 1


def test_skp_export_instances_share_one_definition(tmp_path):
    """Three component instances sharing a prototype mesh export as ONE
    definition + three placements — the geometry is stored once, not
    duplicated per instance."""
    from PySide6.QtGui import QMatrix4x4
    from core.mesh import Mesh
    scene = Scene()
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    for i, dx in enumerate((0.0, 5.0, 10.0)):
        g = Group(proto)
        g.name = f"Col {i + 1}"
        m = QMatrix4x4()
        m.translate(dx, 0.0, 0.0)
        g.xform = m
        scene.groups.append(g)
    scene.version += 1
    path = tmp_path / "columns.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    assert len(model.root.instances) == 3
    assert sum(len(d.faces) for d in model.definitions.values()) == 1


def test_skp_export_roundtrip_instances(tmp_path):
    """Export → re-import through IngeTrazo's OWN .skp importer: the three
    instances come back as groups at their original world positions —
    the strongest check that the placement matrix convention matches
    ``skp_openskp._matrix`` (and therefore real SketchUp)."""
    from PySide6.QtGui import QMatrix4x4
    from core.group import world_mesh
    from core.mesh import Mesh
    from formats import skp as skp_format
    scene = Scene()
    proto = Mesh()
    proto.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    for i, dx in enumerate((0.0, 5.0, 10.0)):
        g = Group(proto)
        g.name = f"Col {i + 1}"
        m = QMatrix4x4()
        m.translate(dx, 0.0, 0.0)
        g.xform = m
        scene.groups.append(g)
    scene.version += 1
    path = tmp_path / "roundtrip.skp"
    skp_out_format.save_skp(scene, path)

    scene2 = Scene()
    skp_format.load_skp(scene2, path)
    assert len(scene2.groups) == 3
    xs = sorted(min(v.x() for f in world_mesh(g).faces for v in f.vertices)
                for g in scene2.groups)
    for got, want in zip(xs, (0.0, 5.0, 10.0)):
        assert abs(got - want) < 1e-3


def test_skp_export_face_hole_survives(tmp_path):
    """A face with a hole (window/door opening) exports as outer + inner
    loops, not as a filled polygon."""
    scene = Scene()
    outer = [V(0, 0), V(10, 0), V(10, 10), V(0, 10)]
    hole = [V(4, 4), V(6, 4), V(6, 6), V(4, 6)]
    scene.mesh.add_face(outer, [hole])
    scene.version += 1
    path = tmp_path / "hole.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    face = next(iter(model.root.faces.values()))
    assert len(face.loops) == 2


def test_skp_export_unpainted_face_has_no_material(tmp_path):
    """A face that was never painted must export with SketchUp's default
    material (i.e. no material record at all), not an explicit cream paint —
    otherwise a round-trip stamps attrs["color"] on faces the model left
    unspecified and pollutes the per-material takeoff."""
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    path = tmp_path / "unpainted.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    assert len(model.materials) == 0


def test_skp_export_mixed_painted_and_unpainted(tmp_path):
    """Only the painted face creates a material; the unpainted one keeps
    SketchUp's default."""
    scene = Scene()
    hist = History(scene)
    F._draw_rect(scene, hist, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    F._draw_rect(scene, hist, [V(6, 0), V(10, 0), V(10, 4), V(6, 4)], [])
    hist.execute(SetFaceColorCommand([scene.mesh.faces[0]], [1.0, 0.0, 0.0]))
    path = tmp_path / "mixed.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    assert len(model.materials) == 1


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


def test_skp_export_same_color_different_names_stay_separate(tmp_path):
    """Two materials with distinct registry names but the same RGB recipe
    must export as TWO materials — merging them corrupts the per-material
    takeoff after a round-trip."""
    scene = Scene()
    hist = History(scene)
    F._draw_rect(scene, hist, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    F._draw_rect(scene, hist, [V(6, 0), V(10, 0), V(10, 4), V(6, 4)], [])
    for face, name in zip(scene.mesh.faces, ("Concreto", "Mortero")):
        face.attrs["color"] = [0.6, 0.6, 0.6]
        face.attrs["mat"] = name
    path = tmp_path / "twins.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    names = {m.name for m in model.materials}
    assert any("Concreto" in n for n in names)
    assert any("Mortero" in n for n in names)


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


def test_skp_export_annotations_roundtrip(tmp_path):
    """Dimensions and leader texts drawn in IngeTrazo survive the .skp
    export: re-reading the file yields their world geometry (metres →
    inches), with the text label floating at anchor + offset."""
    from core.dimension import Dimension
    from core.textlabel import TextLabel

    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    scene.dimensions.append(
        Dimension(V(0, 0, 0), V(4, 0, 0), V(0, -0.5, 0)))
    scene.text_labels.append(
        TextLabel(V(2, 0, 1.5), V(0.4, -0.3, 0.6), "MURO PRINCIPAL"))
    path = tmp_path / "anotado.skp"
    skp_out_format.save_skp(scene, path)

    model = _parse_skp(path)
    dims = getattr(model, "dimensions", [])
    assert len(dims) == 1
    assert abs(dims[0].a[0] - 0.0) < 1e-6
    assert abs(dims[0].b[0] - 4.0 * _M_TO_IN) < 1e-6
    assert abs(abs(dims[0].offset) - 0.5 * _M_TO_IN) < 1e-6
    texts = getattr(model.root, "texts", [])
    assert len(texts) == 1
    assert texts[0].text == "MURO PRINCIPAL"
    assert abs(texts[0].point[0] - 2.0 * _M_TO_IN) < 1e-6
    assert abs(texts[0].point[2] - 1.5 * _M_TO_IN) < 1e-6
    lp = texts[0].label_point
    assert abs(lp[0] - 2.4 * _M_TO_IN) < 1e-6
    assert abs(lp[1] + 0.3 * _M_TO_IN) < 1e-6
    assert abs(lp[2] - 2.1 * _M_TO_IN) < 1e-6


def test_export_survives_an_older_openskp_writer():
    """The applied size and the opacity gate are OUR additions to the writer;
    upstream's has neither. Passing them blind raised ``TypeError:
    add_material() got an unexpected keyword argument 'opacity'`` — CI red,
    and every .skp save broken in a build made against the pinned library.
    The file must still be written, just without what the writer can't do."""
    from formats.skp_out import _collect_materials

    calls = []

    class _OldBuilder:
        def add_material(self, name, rgba):          # no opacity
            calls.append(("color", name))
            return len(calls)

        def add_texture_material(self, name, path):  # no width/height/opacity
            calls.append(("texture", name))
            return len(calls)

    faces_by_key = {
        ("c", (1.0, 0.0, 0.0), None): {"color": (1.0, 0.0, 0.0),
                                       "opacity": 0.5},
        ("t", "/tex/x.png", None): {"map": True, "src": "/tex/x.png",
                                    "color": (1.0, 1.0, 1.0),
                                    "sw_in": 39.37, "sh_in": 39.37,
                                    "opacity": 0.6},
    }
    handles = _collect_materials(faces_by_key, _OldBuilder())
    assert len(handles) == 2
    assert sorted(k for k, _n in calls) == ["color", "texture"]


def test_export_uses_the_new_writer_arguments_when_they_exist():
    from formats.skp_out import _collect_materials

    seen = {}

    class _NewBuilder:
        def add_material(self, name, rgba, opacity=None):
            seen["color_opacity"] = opacity
            return 1

        def add_texture_material(self, name, path, width=None, height=None,
                                 opacity=None):
            seen["tex"] = (width, height, opacity)
            return 2

    faces_by_key = {
        ("c", (1.0, 0.0, 0.0), None): {"color": (1.0, 0.0, 0.0),
                                       "opacity": 0.5},
        ("t", "/tex/x.png", None): {"map": True, "src": "/tex/x.png",
                                    "color": (1.0, 1.0, 1.0),
                                    "sw_in": 39.37, "sh_in": 78.74,
                                    "opacity": 0.6},
    }
    _collect_materials(faces_by_key, _NewBuilder())
    assert seen["color_opacity"] == 0.5
    assert seen["tex"] == (39.37, 78.74, 0.6)


def test_a_texture_at_a_very_long_path_exports_a_file_that_still_opens(tmp_path):
    """0.3.10's Flatpak: a texture cached under a stacked-hash name spilled
    into the temp fallback, the path passed openskp's 255-character string
    limit AFTER the image was in the buffer, the colour fallback landed on
    top, and SketchUp (and openskp itself) refused the file."""
    deep = tmp_path / ("x" * 120)
    deep.mkdir()
    png = _make_png(deep / ("b307e18de460e81b-" * 12 + "water_calm.png"))
    assert len(str(png)) > 255
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    face = scene.mesh.faces[0]
    face.attrs["texture"] = {"path": str(png), "sw": 2.0, "sh": 2.0}
    face.attrs["opacity"] = 0.75
    path = tmp_path / "long.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)                    # 0.3.10 could not parse its own file
    textured = [m for m in model.materials if m.texture is not None]
    assert len(textured) == 1
    raw = path.read_bytes()
    assert "water_calm.png".encode("utf-16-le") in raw
    assert str(tmp_path).encode("utf-16-le") not in raw     # no machine path leaks


def test_a_texture_that_cannot_be_embedded_becomes_a_colour_before_the_writer_runs(tmp_path):
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    bmp = tmp_path / "odd.bmp"
    bmp.write_bytes(b"BM" + bytes(64))
    scene.mesh.faces[0].attrs["texture"] = {"path": str(bmp), "sw": 1.0, "sh": 1.0}
    loop2 = [V(10, 0), V(14, 0), V(14, 4), V(10, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop2], [])
    scene.mesh.faces[-1].attrs["texture"] = {"path": str(tmp_path / "missing.png"),
                                             "sw": 1.0, "sh": 1.0}
    path = tmp_path / "fallback.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    assert model.materials and all(m.texture is None for m in model.materials)


def test_a_bmp_texture_from_an_imported_model_is_re_encoded_not_dropped(tmp_path):
    """openskp embeds PNG and JPEG only; a bridge imported from SketchUp
    carries its logos as BMP. They must reach the .skp as textures."""
    bmp = tmp_path / "coca-cola_logo5.bmp"
    img = QImage(6, 6, QImage.Format_RGB32)
    img.fill(0xFFCC0000)
    assert img.save(str(bmp), "BMP")
    scene = Scene()
    hist = History(scene)
    loop = [V(0, 0), V(4, 0), V(4, 4), V(0, 4)]
    F._draw_rect(scene, hist, [QVector3D(p) for p in loop], [])
    scene.mesh.faces[0].attrs["texture"] = {"path": str(bmp), "sw": 1.0, "sh": 1.0}
    path = tmp_path / "bmp.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    textured = [m for m in model.materials if m.texture is not None]
    assert len(textured) == 1
    assert "coca-cola_logo5.png".encode("utf-16-le") in path.read_bytes()


# ---- Texture placement: what SketchUp reads back is what the viewport drew --

_TILE_M = 0.254            # a 10-inch tile: a scale slip shows up as ×10


def _calibration_faces(scene, png, planar: bool, sdk_extras: bool = False):
    """Eleven textured squares covering the orientations that told the UV
    recipes apart: horizontal with the first edge along +X, +Y, −X and at
    30°; walls facing +Y, −Y, +X, −X (the +Y one drawn from a vertical AND
    from a horizontal first edge); a 45° slope. ``planar`` marks them the
    way push/pull does (default projection, no per-face record).

    ``sdk_extras`` adds the cases openskp's reader gets wrong today, so
    only the SDK oracle asks for them: a square tilted by 1e-4 (inside
    SketchUp's 1e-3 vertical tolerance, outside the reader's 1e-9), one
    far from the origin (float32 vertex noise once turned its normal and
    its texture with it), and three floors looking DOWN, whose basis
    SketchUp turns 180° rather than mirroring."""
    import math
    c30, s30 = math.cos(math.radians(30)), math.sin(math.radians(30))
    c45 = math.sqrt(0.5)

    def sq(o, ex, ey, start=0):
        pts = [o, o + ex, o + ex + ey, o + ey]
        return pts[start:] + pts[:start]
    loops = [
        sq(V(0, 0, 0), V(1, 0, 0), V(0, 1, 0)),
        sq(V(0, 3, 0), V(1, 0, 0), V(0, 1, 0), start=1),
        sq(V(0, 6, 0), V(1, 0, 0), V(0, 1, 0), start=2),
        sq(V(3, 0, 0), V(c30, s30, 0), V(-s30, c30, 0)),
        sq(V(6, 0, 0), V(0, 0, 1), V(1, 0, 0)),          # normal +Y
        sq(V(6, 3, 0), V(1, 0, 0), V(0, 0, 1)),          # normal −Y
        sq(V(9, 0, 0), V(0, 1, 0), V(0, 0, 1)),          # normal +X
        sq(V(9, 3, 0), V(0, 0, 1), V(0, 1, 0)),          # normal −X
        sq(V(12, 0, 0), V(1, 0, 0), V(0, c45, c45)),     # 45° slope
        sq(V(6, 6, 0), V(0, 0, 1), V(1, 0, 0), start=0),
        sq(V(6, 9, 0), V(0, 0, 1), V(1, 0, 0), start=1),
    ]
    if sdk_extras:
        loops.append(sq(V(15, 0, 0), V(1, 0, -1e-4), V(0, 1, 0), start=1))    # tilt 1e-4
        loops.append(sq(V(1500, -240, 1.215), V(1, 0, 0), V(0, 1, 0), start=2))  # far away
        for k in range(3):                                                    # looking down
            loops.append(sq(V(3 * k, 12, 0), V(0, 1, 0), V(1, 0, 0), start=k))
    faces = []
    for pts in loops:
        f = scene.mesh.add_face(pts)
        tex = {"path": str(png), "sw": _TILE_M, "sh": _TILE_M}
        if planar:
            tex["planar"] = True
        f.attrs["texture"] = tex
        faces.append(f)
    scene.version += 1
    return faces


def _reader_uvs(model, defn):
    """Every ``(point_metres, (u, v))`` of the textured faces in ``defn`` as
    openskp's parser — calibrated against real SketchUp files — reads them:
    through the per-face matrix when there is one, the default projection
    otherwise, both divided by the material's applied size."""
    from openskp._face_groups import (compute_face_uv, face_uv_basis,
                                      reconstruct_loop_vertices)
    edges = {eid: (e.v1_id, e.v2_id) for eid, e in defn.edges.items()}
    out = []
    for face in defn.faces.values():
        mat = model.materials_by_id.get(face.material_id)
        if mat is None or mat.texture is None:
            continue
        xr, yr = face_uv_basis(face.normal)
        for vid in reconstruct_loop_vertices(face.loops[0], edges):
            v = defn.vertices[vid]
            uv = compute_face_uv((v.x, v.y, v.z), xr, yr, face.uv_transform,
                                 mat.texture.width, mat.texture.height)
            out.append((V(v.x / _M_TO_IN, v.y / _M_TO_IN, v.z / _M_TO_IN),
                        uv))
    return out


def _face_at(faces, p):
    """The calibration face ``p`` (metres) lies on."""
    for f in faces:
        pts = list(f.vertices)
        n = f.normal().normalized()
        c = sum(pts, QVector3D()) / len(pts)
        if abs(QVector3D.dotProduct(n, p - c)) < 1e-3 and (p - c).length() < 1.2:
            return f
    return None


def _assert_uvs_match_the_viewport(faces, samples, tol=1e-4):
    from core.texture import face_uv_axes
    seen = set()
    for p, (u, v) in samples:
        f = _face_at(faces, p)
        assert f is not None, p
        seen.add(id(f))
        gu, cu, gv, cv = face_uv_axes(f.attrs["texture"], f.normal())
        assert abs(QVector3D.dotProduct(gu, p) + cu - u) < tol, (p, u, v)
        assert abs(QVector3D.dotProduct(gv, p) + cv - v) < tol, (p, u, v)
    assert len(seen) == len(faces)


@pytest.mark.parametrize("planar", [False, True], ids=["pinned", "planar"])
def test_textures_read_back_where_the_viewport_drew_them(tmp_path, planar):
    """The UV openskp's calibrated reader computes for every vertex of the
    exported file equals the UV the viewport draws (``face_uv_axes``) — on
    all eleven orientations, pinned faces and default-projected alike.

    Three defects hid here until the SDK's own converter was used as an
    oracle (2026-09-04): the writer solved pins in a first-edge basis (each
    face turned by its first edge's angle — a palm trunk shattered), the
    writer did not scale pins by the applied size (a 2 m water tile 78×
    too big: a flat blue slab), and the renderer's planar projection used a
    basis 180° off SketchUp's on walls facing +Y and −X. The first two are
    compensated per ``_writer_uv_quirks``; the third is one shared recipe
    now (``core.texture.projection_basis``)."""
    png = _make_png(tmp_path / "tile.png")
    scene = Scene()
    faces = _calibration_faces(scene, png, planar)
    path = tmp_path / "calibration.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    samples = _reader_uvs(model, model.root)
    assert len(samples) == 11 * 4
    _assert_uvs_match_the_viewport(faces, samples)


def test_the_writer_probe_names_only_known_quirks(tmp_path):
    """Whatever the installed openskp does, the probe answers with a subset
    of the two defects it knows how to compensate, and answers once."""
    import openskp
    skp_out_format._QUIRK_CACHE.clear()
    quirks = skp_out_format._writer_uv_quirks(openskp, tmp_path)
    assert quirks <= {"first-edge basis", "unscaled pins"}
    assert skp_out_format._writer_uv_quirks(openskp, tmp_path) is quirks


# ---- Both sides painted -------------------------------------------------------

def _root_faces_with_materials(model):
    return [(f, model.materials_by_id.get(f.material_id),
             model.materials_by_id.get(f.back_material_id))
            for f in model.root.faces.values()]


def test_a_face_painted_in_ingetrazo_is_painted_on_both_sides_in_sketchup(tmp_path):
    """IngeTrazo draws a face's paint on both sides; SketchUp paints only
    the side the file names. Naming only the front showed SketchUp's
    lavender default on every face seen from behind (benches, a roof's
    underside, palm fronds facing away) — so the back gets the same
    material, and the same pins when the texture is positioned."""
    png = _make_png(tmp_path / "tile.png")
    scene = Scene()
    colour = scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    colour.attrs["color"] = (1.0, 0.0, 0.0)
    textured = scene.mesh.add_face([V(3, 0), V(4, 0), V(4, 1), V(3, 1)])
    textured.attrs["texture"] = {"path": str(png), "sw": _TILE_M, "sh": _TILE_M}
    scene.version += 1
    path = tmp_path / "both.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    rows = _root_faces_with_materials(model)
    assert len(rows) == 2
    for face, front, back in rows:
        assert front is not None and back is front
        if front.texture is not None:
            assert face.uv_transform is not None
            assert face.uv_transform_back == pytest.approx(face.uv_transform)


def test_a_two_sided_face_keeps_its_own_back_paint(tmp_path):
    """``attrs["back"]`` — a face SketchUp painted differently on each side
    — comes back as its own back material, not the front's."""
    scene = Scene()
    f = scene.mesh.add_face([V(0, 0), V(1, 0), V(1, 1), V(0, 1)])
    f.attrs["color"] = (1.0, 0.0, 0.0)
    f.attrs["back"] = {"color": (0.0, 0.0, 1.0)}
    scene.version += 1
    path = tmp_path / "two-sided.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    [(face, front, back)] = _root_faces_with_materials(model)
    assert tuple(front.color)[:3] == (255, 0, 0)
    assert tuple(back.color)[:3] == (0, 0, 255)
    assert back is not front


# ---- Face-me figures ----------------------------------------------------------

def test_face_me_figures_become_face_me_components(tmp_path):
    """A textured cut-out (Sumari) and a vector figure (a 2D person) leave
    as component definitions in SketchUp's face-me convention — feet at the
    local origin, front along −Y, the axis SketchUp turns toward the camera
    — placed at their anchors. They used to be skipped altogether: every
    person on the pool deck vanished in SketchUp."""
    from core.group import Group, make_billboard_group
    from core.mesh import Mesh
    png = _make_png(tmp_path / "figure.png")
    scene = Scene()
    scene.groups.append(make_billboard_group(str(png), 1.65, "Sumari",
                                             aspect=0.4, position=V(3, 4, 0)))
    m = Mesh()
    f = m.add_face([V(10, 0, 0), V(10, 0.5, 0), V(10, 0.5, 1.8), V(10, 0, 1.8)])
    f.attrs["color"] = (0.2, 0.4, 0.8)               # a vector figure facing +X
    susan = Group(m, name="Susan")
    susan.billboard = "mesh"
    scene.groups.append(susan)
    scene.version += 1
    path = tmp_path / "figures.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    by_name = {d.name: d for d in model.definitions.values()}
    assert {"Sumari", "Susan"} <= set(by_name)

    def corners(defn):
        return [(round(v.x / _M_TO_IN, 3), round(v.y / _M_TO_IN, 3),
                 round(v.z / _M_TO_IN, 3)) for v in defn.vertices.values()]

    sumari = by_name["Sumari"]
    assert len(sumari.faces) == 1
    xs, ys, zs = zip(*corners(sumari))
    assert min(xs) == -0.33 and max(xs) == 0.33          # 1.65 × 0.4 wide, centred
    assert set(ys) == {0.0} and min(zs) == 0.0 and max(zs) == 1.65
    face = next(iter(sumari.faces.values()))
    assert model.materials_by_id[face.material_id].texture is not None
    assert face.uv_transform is not None                  # the picture once, pinned
    assert all(e.hidden for e in sumari.edges.values())   # no black frame

    susan_def = by_name["Susan"]
    xs, ys, zs = zip(*corners(susan_def))
    assert min(xs) == -0.25 and max(xs) == 0.25          # turned from +X onto −Y
    assert set(ys) == {0.0} and max(zs) == 1.8
    normal = next(iter(susan_def.faces.values())).normal
    assert normal[1] == pytest.approx(-1.0)

    placed = {}
    for inst in model.root.instances:
        d = model.definitions[inst.ref_idx]
        placed[d.name] = tuple(round(c / _M_TO_IN, 3) for c in inst.matrix[9:12])
    assert placed["Sumari"] == (3.0, 4.0, 0.0)            # its feet
    assert placed["Susan"] == (10.0, 0.25, 0.0)

    import openskp
    b = openskp.create()
    if "always_faces_camera" in skp_out_format._supported(
            b.add_component_definition, "always_faces_camera"):
        assert sumari.always_faces_camera and susan_def.always_faces_camera


# ---- Repeated geometry shares a definition ------------------------------------

def _strip(mesh, n, origin, colour):
    """``n`` unit quads in a row sharing edges — one connected piece."""
    ox, oy, oz = origin
    faces = []
    for i in range(n):
        f = mesh.add_face([V(ox + i, oy, oz), V(ox + i + 1, oy, oz),
                           V(ox + i + 1, oy + 1, oz), V(ox + i, oy + 1, oz)])
        f.attrs["color"] = colour
        faces.append(f)
    return faces


def test_translated_copies_inside_one_mesh_share_a_definition(tmp_path):
    """Three translated copies of a 20-face strip fused in one group, plus a
    different 21-face strip: the copy is written ONCE as a definition placed
    three times (at each copy's corner) and the odd strip stays as faces.
    An older IngeTrazo saved models with their components exploded — the
    pool's 24 hedges became one 230 400-face group — and the file was 70 MB
    for what SketchUp keeps in a fraction."""
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    red = (1.0, 0.0, 0.0)
    for y in (0, 5, 10):
        _strip(m, 20, (0, y, 0), red)
    _strip(m, 21, (0, 20, 0), red)
    scene = Scene()
    scene.groups.append(Group(m, name="tiras"))
    scene.version += 1
    path = tmp_path / "repeats.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    by_faces = {len(d.faces): d for d in model.definitions.values()}
    assert 20 in by_faces and 21 in by_faces
    strip, group = by_faces[20], by_faces[21]
    placed = sorted(tuple(round(c / _M_TO_IN, 3) for c in i.matrix[9:12])
                    for i in group.instances if i.ref_idx == strip.id)
    # a piece's origin: its XY centroid at its lowest z
    assert placed == [(10.0, 0.5, 0.0), (10.0, 5.5, 0.0), (10.0, 10.5, 0.0)]
    total = sum(len(d.faces) for d in model.definitions.values()) + len(model.root.faces)
    assert total == 41                                   # 20 once + 21, not 81


def test_a_copy_painted_differently_is_not_shared(tmp_path):
    """Sharing needs the same paint face for face: two red strips share,
    the blue one is written as it is."""
    from core.group import Group
    from core.mesh import Mesh
    m = Mesh()
    _strip(m, 20, (0, 0, 0), (1.0, 0.0, 0.0))
    _strip(m, 20, (0, 5, 0), (1.0, 0.0, 0.0))
    _strip(m, 20, (0, 10, 0), (0.0, 0.0, 1.0))
    scene = Scene()
    scene.groups.append(Group(m, name="tiras"))
    scene.version += 1
    path = tmp_path / "repeats-paint.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    sizes = sorted(len(d.faces) for d in model.definitions.values())
    assert sizes == [20, 20]            # the red proto, and the group with the blue strip
    group = next(d for d in model.definitions.values() if d.instances)
    assert len(group.instances) == 2
    blue = model.materials_by_id[next(iter(group.faces.values())).material_id]
    assert tuple(blue.color)[:3] == (0, 0, 255)


def test_a_copy_turned_about_the_vertical_shares_too(tmp_path):
    """The pool's hedges are 7200 leaves, each the same few leaves turned at
    random about Z — no two translated alike. A copy turned about the
    vertical matches the prototype after the turn, point for point, and is
    placed with that rotation; a mirrored one is not."""
    from core.group import Group
    from core.mesh import Mesh
    import math
    m = Mesh()
    red = (1.0, 0.0, 0.0)
    _strip(m, 20, (0, 0, 0), red)                       # along +X
    c, s_ = math.cos(math.radians(37)), math.sin(math.radians(37))
    for i in range(20):                                  # the same strip, turned 37° and moved
        pts = [(i, 0), (i + 1, 0), (i + 1, 1), (i, 1)]
        f = m.add_face([V(30 + c * x - s_ * y, 40 + s_ * x + c * y, 2) for x, y in pts])
        f.attrs["color"] = red
    # An L: the strip plus an arm at one end — asymmetric, so its mirror is
    # NOT a turn of it. Three of them: two turned copies and a mirrored one.
    def ell(place):
        for i in range(18):
            f = m.add_face([V(*place(i, 0)), V(*place(i + 1, 0)), V(*place(i + 1, 1)), V(*place(i, 1))])
            f.attrs["color"] = red
        for j in range(1, 4):
            f = m.add_face([V(*place(0, j)), V(*place(1, j)), V(*place(1, j + 1)), V(*place(0, j + 1))])
            f.attrs["color"] = red
    ell(lambda x, y: (x, 100 + y, 0))
    ell(lambda x, y: (60 + c * x - s_ * y, 100 + s_ * x + c * y, 0))
    ell(lambda x, y: (-x, 140 + y, 0))                   # mirrored in X
    scene = Scene()
    scene.groups.append(Group(m, name="tiras"))
    scene.version += 1
    path = tmp_path / "turned.skp"
    skp_out_format.save_skp(scene, path)
    model = _parse_skp(path)
    total = sum(len(d.faces) for d in model.definitions.values()) + len(model.root.faces)
    assert total == 20 + 21 + 21                         # strip once, L once, mirrored L as faces
    group = next(d for d in model.definitions.values() if d.instances)
    assert len(group.instances) == 4                     # 2 strips + 2 Ls
    # Each placement, read the way the importer reads it, lands the shared
    # definition's corners exactly on the copy's original corners.
    from formats.skp_openskp import _matrix
    originals = {(round(v.position.x(), 3), round(v.position.y(), 3),
                  round(v.position.z(), 3)) for v in m.vertices}
    for inst in group.instances:
        defn = model.definitions[inst.ref_idx]
        mat = _matrix(inst.matrix)                       # translation in metres
        for v in defn.vertices.values():
            w = mat.map(QVector3D(v.x / _M_TO_IN, v.y / _M_TO_IN, v.z / _M_TO_IN))
            assert (round(w.x(), 3), round(w.y(), 3), round(w.z(), 3)) in originals



# ---- The file SketchUp can save --------------------------------------------------

def test_the_pid_counter_covers_every_entity_written(tmp_path):
    """SketchUp could open our files but not SAVE them: the pinned writer
    numbers every section's persistent IDs from 1 and grows the header's
    counter by materials and layers only, so SketchUp renumbers duplicates
    on load and then fails to serialize (Marco's pool in SketchUp Web,
    2026-09-04: "Guardado fallido"). Whatever writer is installed, the
    u32 counter at the writer's own offset must cover every record."""
    import struct
    from openskp.create import _PID_COUNTER_POS
    from core.group import Group
    from core.mesh import Mesh
    scene = Scene()
    for k in range(3):
        m = Mesh()
        _strip(m, 25, (0, 5 * k, 0), (0.2 * k, 0.5, 0.5))
        g = Group(m, name=f"pieza {k}")
        g.xform = QMatrix4x4()
        g.xform.translate(QVector3D(0, 0, 2 * k))
        scene.groups.append(g)
    scene.groups.append(Group(_quad_mesh(), name="suelto"))
    scene.version += 1
    path = tmp_path / "pids.skp"
    skp_out_format.save_skp(scene, path)
    counter = struct.unpack_from("<I", path.read_bytes(), _PID_COUNTER_POS)[0]
    model = _parse_skp(path)
    records = sum(len(d.faces) + len(d.edges) + len(d.vertices)
                  for d in model.definitions.values())
    records += len(model.root.faces) + len(model.root.edges) + len(model.root.vertices)
    records += sum(len(d.instances) for d in model.definitions.values()) + len(model.root.instances)
    assert counter >= records


def _quad_mesh():
    from core.mesh import Mesh
    m = Mesh()
    m.add_face([V(50, 50), V(51, 50), V(51, 51), V(50, 51)])
    return m



def test_only_layers_in_use_are_written(tmp_path):
    """SketchUp's Purge on the pool threw away 8 of our 10 layers — all
    empty — and IngeTrazo's default "Layer 0" is SketchUp's own "Layer0":
    an exported file carries the layers something sits on, nothing else."""
    scene = Scene()
    hist = History(scene)
    F._draw_rect(scene, hist, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    face = scene.mesh.faces[0]
    scene.layers.append(Layer("Estructura"))
    scene.layers.append(Layer("Vacía"))
    scene.layers.append(Layer("Layer 0"))
    assign_layer(face, "Estructura")
    path = tmp_path / "layers.skp"
    skp_out_format.save_skp(scene, path)
    names = [ly.name for ly in _parse_skp(path).layers]
    assert "Estructura" in names
    assert "Vacía" not in names and "Layer 0" not in names
