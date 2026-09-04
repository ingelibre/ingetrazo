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
