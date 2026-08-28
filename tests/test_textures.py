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
