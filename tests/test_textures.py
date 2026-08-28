# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SketchUp-compatible textures: planar UV projection, the SetFaceTexture
command, OBJ export with vt + map_Kd, and .igz round-trip."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage, QColor, QVector3D

from core.history import History, SetFaceColorCommand, SetFaceTextureCommand
from core.scene import Scene
from core.texture import Texture, planar_uv
from formats import igz
from formats import obj as obj_format
import tests.test_fuzz_engine as F


def V(x, y, z=0.0):
    return QVector3D(float(x), float(y), float(z))


def _cube(scene, hist, height=3.0):
    F._draw_rect(scene, hist, [V(0, 0), V(4, 0), V(4, 4), V(0, 4)], [])
    f = scene.mesh.faces[0]
    F._push(scene, hist, f, height if f.normal().z() > 0 else -height)


def _checker(path, n=16):
    img = QImage(n, n, QImage.Format_RGB888)
    for y in range(n):
        for x in range(n):
            img.setPixelColor(x, y, QColor(200, 120, 60) if (x + y) % 2
                              else QColor(245, 235, 220))
    img.save(str(path))


# ---- Planar UV projection ------------------------------------------------------

def test_planar_uv_scales_by_tile_size():
    # Top face (normal +Z): UVs are the X/Y world coords divided by the tile.
    pts = [V(0, 0, 3), V(4, 0, 3), V(4, 4, 3), V(0, 4, 3)]
    uv1 = planar_uv(V(0, 0, 1), pts, 1.0, 1.0)
    uv2 = planar_uv(V(0, 0, 1), pts, 2.0, 2.0)
    # A 2 m tile halves the UV span (4 m → 2 repeats instead of 4).
    span1 = max(u for u, _ in uv1) - min(u for u, _ in uv1)
    span2 = max(u for u, _ in uv2) - min(u for u, _ in uv2)
    assert abs(span1 - 4.0) < 1e-6
    assert abs(span2 - 2.0) < 1e-6


def test_coplanar_faces_share_projection():
    # Two faces on the same plane project continuously (same basis → seamless).
    a = planar_uv(V(0, 0, 1), [V(0, 0, 0)], 1.0, 1.0)[0]
    b = planar_uv(V(0, 0, 1), [V(4, 0, 0)], 1.0, 1.0)[0]
    assert a == (0.0, 0.0)
    assert b == (4.0, 0.0)


def test_texture_dataclass_round_trip():
    t = Texture("/x/brick.png", 0.5, 0.25)
    assert Texture.from_dict(t.as_dict()) == t


# ---- Command -------------------------------------------------------------------

def test_set_face_texture_command_do_undo():
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    face = scene.mesh.faces[0]
    tex = {"path": "/x/brick.png", "sw": 1.0, "sh": 1.0}
    hist.execute(SetFaceTextureCommand([face], tex))
    assert face.attrs["texture"] == tex
    hist.undo()
    assert "texture" not in face.attrs
    hist.redo()
    assert face.attrs["texture"] == tex


# ---- OBJ export ----------------------------------------------------------------

def test_obj_export_writes_texture_material_and_uvs(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    tex_src = tmp_path / "checker.png"
    _checker(tex_src)
    top = next(f for f in scene.mesh.faces
               if all(abs(v.z() - 3) < 1e-9 for v in f.vertices))
    hist.execute(SetFaceTextureCommand(
        [top], {"path": str(tex_src), "sw": 1.0, "sh": 1.0}))

    out = tmp_path / "out.obj"
    obj_format.save_obj(scene, out)

    obj_text = out.read_text()
    mtl_text = (out.with_suffix(".mtl")).read_text()
    assert "vt " in obj_text                       # texture coords written
    assert "map_Kd checker.png" in mtl_text        # texture material
    assert (tmp_path / "checker.png").exists()     # image copied next to .obj
    # The textured face references v/vt; the plain faces reference v only.
    assert any("/" in tok for line in obj_text.splitlines()
               if line.startswith("f ") for tok in line.split()[1:])


# ---- .igz round-trip -----------------------------------------------------------

def test_texture_survives_igz_round_trip(tmp_path):
    # An image that cannot be read (here: a path that never existed) is not
    # packed — the entry keeps its original "path" so the document is no worse
    # off than before containers existed.
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    face = scene.mesh.faces[0]
    tex = {"path": "/x/brick.png", "sw": 0.5, "sh": 0.25}
    hist.execute(SetFaceTextureCommand([face], tex))
    path = tmp_path / "tex.igz"
    stats = igz.save_scene(scene, path)
    assert stats == {"embedded": 0, "missing": 1}

    loaded = Scene()
    igz.load_into(loaded, path)
    painted = [f for f in loaded.mesh.faces if f.attrs.get("texture")]
    assert len(painted) == 1
    assert painted[0].attrs["texture"] == tex


# ---- .igz container: images ride INSIDE the document ---------------------------

def _textured_cube(scene, hist, img_path, extra=None):
    _cube(scene, hist)
    _checker(img_path)
    top = next(f for f in scene.mesh.faces
               if all(abs(v.z() - 3) < 1e-9 for v in f.vertices))
    tex = {"path": str(img_path), "sw": 1.0, "sh": 1.0}
    hist.execute(SetFaceTextureCommand([top], tex))
    if extra:
        top.attrs.update(extra)
    return top


def test_igz_packs_texture_images_into_the_document(tmp_path, monkeypatch):
    import zipfile

    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache"))
    scene = Scene()
    hist = History(scene)
    src = tmp_path / "checker.png"
    _textured_cube(scene, hist, src)

    doc = tmp_path / "casa.igz"
    assert igz.save_scene(scene, doc) == {"embedded": 1, "missing": 0}

    import json
    with zipfile.ZipFile(doc) as zf:
        names = zf.namelist()
        assert "document.json" in names
        member = next(n for n in names if n.startswith("textures/"))
        assert zf.read(member) == src.read_bytes()      # the real image bytes
        raw = zf.read("document.json").decode()
    data = json.loads(raw)
    assert data["igz_format"] == 2
    # The entry points INSIDE the archive, and no machine-local path leaks out.
    tex = next(f["texture"] for f in data["scene"]["faces"] if "texture" in f)
    assert tex == {"embed": member, "sw": 1.0, "sh": 1.0}
    assert str(tmp_path) not in raw

    # Saving must not disturb the live scene: it still points at the original.
    live = next(f.attrs["texture"] for f in scene.mesh.faces
                if f.attrs.get("texture"))
    assert live["path"] == str(src)


def test_igz_document_opens_on_another_machine(tmp_path, monkeypatch):
    # The whole point: the .igz travels alone — original image gone, texture
    # cache empty (a different computer) — and the texture is still there.
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache-a"))
    scene = Scene()
    hist = History(scene)
    src = tmp_path / "checker.png"
    _textured_cube(scene, hist, src)
    doc = tmp_path / "casa.igz"
    igz.save_scene(scene, doc)
    original = src.read_bytes()
    src.unlink()

    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache-b"))
    loaded = Scene()
    igz.load_into(loaded, doc)
    tex = next(f.attrs["texture"] for f in loaded.mesh.faces
               if f.attrs.get("texture"))
    img = Path(tex["path"])
    assert img.parent == tmp_path / "cache-b" / "embedded"
    assert img.read_bytes() == original
    assert tex["sw"] == 1.0 and "embed" not in tex

    # Re-saving the reopened document keeps carrying the image.
    again = tmp_path / "otra.igz"
    assert igz.save_scene(loaded, again) == {"embedded": 1, "missing": 0}


def test_igz_stays_plain_json_without_textures(tmp_path):
    # The common case must remain diffable, hand-editable and readable by
    # older builds — no container, no format bump.
    import json

    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    doc = tmp_path / "plain.igz"
    assert igz.save_scene(scene, doc) == {"embedded": 0, "missing": 0}
    data = json.loads(doc.read_text())
    assert data["igz_format"] == 1


def test_igz_container_is_byte_identical_across_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache"))
    scene = Scene()
    hist = History(scene)
    _textured_cube(scene, hist, tmp_path / "checker.png")
    a = tmp_path / "a.igz"
    b = tmp_path / "b.igz"
    igz.save_scene(scene, a)
    igz.save_scene(scene, b)
    assert a.read_bytes() == b.read_bytes()


def test_igz_packs_back_side_textures_without_touching_the_scene(tmp_path,
                                                                 monkeypatch):
    # attrs["back"] carries its own material (SketchUp paints both sides) —
    # its image must travel too, and packing must not mutate the live face.
    monkeypatch.setenv("INGETRAZO_TEXTURE_CACHE", str(tmp_path / "cache"))
    scene = Scene()
    hist = History(scene)
    back_img = tmp_path / "back.png"
    _checker(back_img, n=8)
    top = _textured_cube(scene, hist, tmp_path / "checker.png")
    top.attrs["back"] = {"texture": {"path": str(back_img),
                                     "sw": 2.0, "sh": 2.0}}

    doc = tmp_path / "dos-caras.igz"
    assert igz.save_scene(scene, doc) == {"embedded": 2, "missing": 0}
    assert top.attrs["back"]["texture"]["path"] == str(back_img)   # untouched

    loaded = Scene()
    igz.load_into(loaded, doc)
    back = next(f.attrs["back"] for f in loaded.mesh.faces
                if f.attrs.get("back"))
    assert Path(back["texture"]["path"]).read_bytes() == back_img.read_bytes()
    assert back["texture"]["sw"] == 2.0


def test_textured_obj_round_trips_the_texture(tmp_path):
    scene = Scene()
    hist = History(scene)
    _cube(scene, hist)
    tex_src = tmp_path / "checker.png"
    _checker(tex_src)
    top = next(f for f in scene.mesh.faces
               if all(abs(v.z() - 3) < 1e-9 for v in f.vertices))
    hist.execute(SetFaceTextureCommand(
        [top], {"path": str(tex_src), "sw": 1.0, "sh": 1.0}))
    out = tmp_path / "out.obj"
    obj_format.save_obj(scene, out)

    loaded = Scene()
    obj_format.load_obj(loaded, out)
    textured = [f for f in loaded.mesh.faces if f.attrs.get("texture")]
    assert len(textured) == 1
    assert Path(textured[0].attrs["texture"]["path"]).name == "checker.png"


def test_planar_uv_rotation_and_scale():
    # Bigger tile size = fewer repeats; rotation turns the UV frame in-plane
    # (SketchUp's edit-material W/H/Rot).
    from PySide6.QtGui import QVector3D

    from core.texture import planar_uv

    n = QVector3D(0, 0, 1)
    pts = [QVector3D(1, 0, 0), QVector3D(0, 1, 0)]
    # Doubling the tile halves the UV.
    (u1, _), _ = planar_uv(n, pts, 1.0, 1.0)
    (u2, _), _ = planar_uv(n, pts, 2.0, 2.0)
    assert abs(u2 - u1 / 2.0) < 1e-9
    # 90° rotation maps the +X point onto the (former) V axis.
    (u90, v90), (u90b, v90b) = planar_uv(n, pts, 1.0, 1.0, rot=90.0)
    (u0, v0), (u0b, v0b) = planar_uv(n, pts, 1.0, 1.0)
    assert abs(abs(v90) - abs(u0)) < 1e-9         # swapped axes
    assert abs(abs(u90b) - abs(v0b)) < 1e-6      # (0,1) lands on former U
    # rotation preserves scale (rigid in-plane turn)
    import math
    assert abs(math.hypot(u90, v90) - math.hypot(u0, v0)) < 1e-9


def test_texture_rotation_round_trips_igz(tmp_path):
    from PySide6.QtGui import QVector3D

    from core.scene import Scene
    from formats import igz

    scene = Scene()
    f = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(2, 0, 0),
                             QVector3D(2, 2, 0), QVector3D(0, 2, 0)])
    f.attrs["texture"] = {"path": "x.png", "sw": 1.5, "sh": 0.75, "rot": 45.0}
    p = tmp_path / "rot.igz"
    igz.save_scene(scene, p)
    scene2 = Scene()
    igz.load_into(scene2, p)
    tex = scene2.mesh.faces[0].attrs["texture"]
    assert tex["rot"] == 45.0 and tex["sw"] == 1.5


# ---- A dead map_Kd costs its own texture, not the model ----------------------

def _model_with_map(tmp_path, map_line, image=None):
    """A one-triangle OBJ whose material carries ``map_line`` and a red Kd."""
    if image is not None:
        QImage(2, 2, QImage.Format_RGB32).save(str(tmp_path / image))
    (tmp_path / "m.mtl").write_text(
        "newmtl skin\nKd 0.8 0.1 0.1\n%s\n" % map_line)
    obj = tmp_path / "m.obj"
    obj.write_text(
        "mtllib m.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl skin\nf 1 2 3\n")
    return obj


def test_a_windows_path_with_spaces_finds_the_image_that_travelled_along(tmp_path):
    # Third-party OBJs point at the machine they were made on. Taking the
    # line's last token broke on the spaces every Windows path has, and
    # Path.with_name then raised on the fragment and took the whole import
    # down: four models of the Sweet Home 3D CC0 library would not load.
    obj = _model_with_map(
        tmp_path,
        "map_Kd C:/Documents and Settings/Jeremy.KIDSXP/Desktop/wood.jpg",
        image="wood.jpg")
    scene = Scene()
    obj_format.load_obj(scene, obj)
    assert scene.faces
    tex = scene.faces[0].attrs.get("texture")
    assert tex and Path(tex["path"]).name == "wood.jpg"


def test_a_map_that_leads_nowhere_falls_back_to_the_colour(tmp_path):
    obj = _model_with_map(
        tmp_path, "map_Kd C:/Documents and Settings/jeremy/gone.jpg")
    scene = Scene()
    obj_format.load_obj(scene, obj)              # must not raise
    assert scene.faces
    attrs = scene.faces[0].attrs
    assert "texture" not in attrs, "kept a path that leads nowhere"
    assert attrs.get("color") == [0.8, 0.1, 0.1]


def test_map_options_are_not_mistaken_for_the_filename(tmp_path):
    # map_Kd takes options before the file: -s scales, -o offsets.
    obj = _model_with_map(tmp_path, "map_Kd -s 1 1 1 -o 0 0 0 wood.jpg",
                          image="wood.jpg")
    scene = Scene()
    obj_format.load_obj(scene, obj)
    tex = scene.faces[0].attrs.get("texture")
    assert tex and Path(tex["path"]).name == "wood.jpg"


def test_an_mtl_in_a_foreign_encoding_still_loads(tmp_path):
    (tmp_path / "m.mtl").write_bytes(
        b"# color caf\xe9\nnewmtl skin\nKd 0.8 0.1 0.1\n")
    obj = tmp_path / "m.obj"
    obj.write_text(
        "mtllib m.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nusemtl skin\nf 1 2 3\n")
    scene = Scene()
    obj_format.load_obj(scene, obj)              # must not raise
    assert scene.faces[0].attrs.get("color") == [0.8, 0.1, 0.1]


# ---- The unit an OBJ never records ------------------------------------------

def _obj_of_size(tmp_path, span):
    tmp_path.mkdir(parents=True, exist_ok=True)
    obj = tmp_path / "s.obj"
    obj.write_text("v 0 0 0\nv %g 0 0\nv 0 %g 0\nf 1 2 3\n" % (span, span))
    return obj


def test_suggest_unit_only_speaks_when_metres_are_impossible(tmp_path):
    # OBJ records no unit, so the size is the only clue — and it is only
    # conclusive at the top: 234 units across is not a 234 m sofa, but 115
    # reads the same for a chair in centimetres and a tower in metres.
    from formats.obj import suggest_unit
    assert suggest_unit(_obj_of_size(tmp_path / "a", 234)) == "cm"
    assert suggest_unit(_obj_of_size(tmp_path / "b", 45000)) == "mm"
    assert suggest_unit(_obj_of_size(tmp_path / "c", 115)) == "m"
    assert suggest_unit(_obj_of_size(tmp_path / "d", 3.2)) == "m"


def test_the_import_scale_lands_the_model_in_metres(tmp_path):
    # A Sweet Home 3D chair is 51 x 80 x 53 centimetres.
    obj = tmp_path / "chair.obj"
    obj.write_text("v 0 0 0\nv 51 0 0\nv 0 80 0\nf 1 2 3\n")
    scene = Scene()
    obj_format.load_obj(scene, obj, scale=0.01)
    xs = [v.x() for f in scene.faces for v in f.vertices]
    ys = [v.y() for f in scene.faces for v in f.vertices]
    assert abs(max(xs) - 0.51) < 1e-6 and abs(max(ys) - 0.80) < 1e-6


def test_the_default_scale_leaves_a_model_untouched(tmp_path):
    # Our own exports are metres: a round trip must not be rescaled.
    obj = tmp_path / "m.obj"
    obj.write_text("v 0 0 0\nv 2 0 0\nv 0 3 0\nf 1 2 3\n")
    scene = Scene()
    obj_format.load_obj(scene, obj)
    xs = [v.x() for f in scene.faces for v in f.vertices]
    assert abs(max(xs) - 2.0) < 1e-9


# ---- The file's own texture coordinates ------------------------------------

def test_an_obj_brings_its_own_texture_coordinates(tmp_path):
    # Without them a curved surface can only be guessed at, and the guess
    # projects the image flatly onto each little facet in turn: a car wheel
    # and a person's clothes came out as confetti. The file says where the
    # image goes; the import has to keep it.
    from core.texture import affine_uv
    QImage(2, 2, QImage.Format_RGB32).save(str(tmp_path / "skin.jpg"))
    (tmp_path / "m.mtl").write_text("newmtl skin\nKd 1 1 1\nmap_Kd skin.jpg\n")
    obj = tmp_path / "m.obj"
    obj.write_text("mtllib m.mtl\n"
                   "v 0 0 0\nv 2 0 0\nv 0 3 0\n"
                   "vt 0.25 0.5\nvt 0.75 0.5\nvt 0.25 0.9\n"
                   "usemtl skin\nf 1/1 2/2 3/3\n")
    scene = Scene()
    obj_format.load_obj(scene, obj)
    tex = scene.faces[0].attrs["texture"]
    assert "uvw" in tex, "the file's vt were thrown away"
    got = affine_uv(tex["uvw"], scene.faces[0].vertices)
    want = {(0.25, 0.5), (0.75, 0.5), (0.25, 0.9)}
    for u, v in got:
        assert min(abs(u - a) + abs(v - b) for a, b in want) < 1e-6


def test_a_face_without_texture_coordinates_still_gets_its_texture(tmp_path):
    # The planar projection stays for what it is meant for: a wall, a floor,
    # a panel — anything the file gives no vt for.
    obj = _model_with_map(tmp_path, "map_Kd wood.jpg", image="wood.jpg")
    scene = Scene()
    obj_format.load_obj(scene, obj)
    tex = scene.faces[0].attrs["texture"]
    assert Path(tex["path"]).name == "wood.jpg"
    assert "uvw" not in tex


# ---- A texture that came with the model travels with it ---------------------

def _textured_group(offset=0.0):
    """A one-face group whose texture carries its own world→UV map."""
    from core.group import Group
    from core.mesh import Mesh
    mesh = Mesh()
    face = mesh.add_face([V(offset, 0, 0), V(offset + 1, 0, 0),
                          V(offset + 1, 1, 0), V(offset, 1, 0)])
    face.attrs["texture"] = {"path": "skin.jpg", "sw": 1.0, "sh": 1.0,
                             "uvw": [1.0, 0.0, 0.0, -offset,
                                     0.0, 1.0, 0.0, 0.0]}
    return Group(mesh), face


def _uvs(face):
    from core.texture import affine_uv
    return [(round(u, 6), round(v, 6))
            for u, v in affine_uv(face.attrs["texture"]["uvw"], face.vertices)]


def test_moving_a_group_takes_its_texture_with_it():
    # The map says WHERE IN THE WORLD the image sits, so moving the geometry
    # without it leaves the image behind — and every little facet of a person
    # or a car wheel then samples a different scrap of the photo.
    from core.history import MoveGroupCommand
    scene = Scene()
    group, face = _textured_group()
    scene.groups.append(group)
    before = _uvs(face)
    MoveGroupCommand(group, V(2, 3, 0)).do(scene)
    assert _uvs(face) == before


def test_rotating_and_scaling_a_group_keep_its_texture():
    from core.history import RotateGroupCommand, ScaleGroupCommand
    scene = Scene()
    group, face = _textured_group()
    scene.groups.append(group)
    before = _uvs(face)
    RotateGroupCommand(group, V(0, 0, 0), V(0, 0, 1), 37.0).do(scene)
    assert _uvs(face) == before
    ScaleGroupCommand(group, V(0, 0, 0), 2.5).do(scene)
    assert _uvs(face) == before


def test_undoing_the_move_puts_the_texture_back():
    from core.history import RotateGroupCommand
    scene = Scene()
    group, face = _textured_group()
    scene.groups.append(group)
    before = _uvs(face)
    cmd = RotateGroupCommand(group, V(0, 0, 0), V(0, 0, 1), 37.0)
    cmd.do(scene)
    cmd.undo(scene)
    assert _uvs(face) == before


def test_the_placement_matrix_is_the_move_the_tool_actually_makes():
    # The tool re-poses the mesh vertex by vertex and hands the SAME move to
    # the texture map. If the two ever disagree the image slides off, so pin
    # them to each other.
    from tools.place_group import PlaceGroupTool
    group, _face = _textured_group()
    tool = PlaceGroupTool(group)
    shift = V(2, 3, 1)
    m = tool._pose_matrix(shift)
    for p in (V(0, 0, 0), V(1, 0, 0), V(0.5, 0.25, 2)):
        assert (m.map(p) - (tool._rotate(p) + shift)).length() < 1e-6


# ---- The file's own smoothing groups ----------------------------------------

def _obj_with_smoothing(tmp_path, smooth: str):
    """Two triangles meeting at 45°, inside ``smooth`` — a curved surface as
    far as the file is concerned."""
    obj = tmp_path / "s.obj"
    obj.write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "v 0 2 1\nv 1 2 1\n"
        "%s\nf 1 2 3 4\nf 4 3 6 5\n" % smooth)
    return obj


def test_a_file_that_says_the_surface_is_smooth_is_believed(tmp_path):
    # Guessing from the angle left a car bonnet and a figure's face covered
    # in the lines of their own triangulation. The modeller already said
    # those faces are one surface.
    scene = Scene()
    obj_format.load_obj(scene, _obj_with_smoothing(tmp_path, "s 1"))
    shared = [e for e in scene.mesh.edges if len(e.faces) == 2]
    assert shared and all(e.soft for e in shared)


def test_a_file_that_says_nothing_keeps_its_line(tmp_path):
    # "s off" is a statement too: this is a corner, draw it.
    scene = Scene()
    obj_format.load_obj(scene, _obj_with_smoothing(tmp_path, "s off"))
    shared = [e for e in scene.mesh.edges if len(e.faces) == 2]
    assert shared and not any(e.soft for e in shared)


def test_the_smoothing_group_never_reaches_the_model(tmp_path):
    # It is scaffolding for the import, not something to edit or save.
    from formats.fuse import SMOOTH_KEY
    scene = Scene()
    obj_format.load_obj(scene, _obj_with_smoothing(tmp_path, "s 1"))
    assert not any(SMOOTH_KEY in (f.attrs or {}) for f in scene.mesh.faces)
