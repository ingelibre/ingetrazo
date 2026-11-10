"""Export the view as SVG: the hidden-line drawing the DXF export writes,
as a vector drawing to finish in an illustration program — one SVG layer
per model layer (and per line class), each in its colour, line type and
pen, at paper size, its touching segments chained into one path."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest
from PySide6.QtGui import QVector3D

SVG = "{http://www.w3.org/2000/svg}"
INK = "{http://www.inkscape.org/namespaces/inkscape}"


def _layers(path):
    """``{label: <g>}`` of the SVG's top-level layers."""
    root = ET.parse(path).getroot()
    assert root.tag == SVG + "svg"
    out = {}
    for g in root.findall(SVG + "g"):
        assert g.get(INK + "groupmode") == "layer"
        out[g.get(INK + "label")] = g
    return root, out


def _points(path_el):
    d = path_el.get("d").replace("M", "").replace("Z", "").split("L")
    return [tuple(float(v) for v in p.split(",")) for p in d]


# ---- Chaining ---------------------------------------------------------------

def test_a_square_comes_apart_into_its_four_sides():
    """A corner ends a line: each side of a rectangle is a line of its own
    in the illustration program, not one stroke round the corners."""
    from formats.svg_out import chain_segments
    segs = [(1, 0, 1, 1), (0, 0, 1, 0), (0, 1, 0, 0), (0, 1, 1, 1)]
    chains = chain_segments(segs)
    assert len(chains) == 4
    assert all(len(p) == 2 and not c for p, c in chains)


def test_a_junction_ends_every_line_that_meets_there():
    """A T: the bar's two halves and the stem are three lines — chaining
    across the junction welded lines going different ways into one."""
    from formats.svg_out import chain_segments
    segs = [(0, 0, 1, 0), (1, 0, 2, 0), (1, 0, 1, -1), (9, 9, 9, 9)]
    chains = chain_segments(segs)
    assert sorted(len(p) for p, _c in chains) == [2, 2, 2]


def test_the_pieces_of_one_edge_and_an_arc_stay_one_line():
    import math as m
    from formats.svg_out import chain_segments
    # One edge the hidden-line pass split in three, drawn out of order.
    edge = [(2, 0, 3, 0), (0, 0, 1, 0), (1, 0, 2, 0)]
    chains = chain_segments(edge)
    assert len(chains) == 1 and len(chains[0][0]) == 4
    # A circle of 24 facets: one closed line.
    pts = [(m.cos(k * m.pi / 12), m.sin(k * m.pi / 12)) for k in range(24)]
    ring = [(*pts[k], *pts[(k + 1) % 24]) for k in range(24)]
    chains = chain_segments(ring)
    assert len(chains) == 1
    assert chains[0][1] and len(chains[0][0]) == 24


# ---- The writer -------------------------------------------------------------

def test_each_group_is_a_layer_with_its_colour_line_type_and_pen(tmp_path):
    from formats.svg_out import save_svg_layers
    square = [(0, 0, 2, 0), (2, 0, 2, 1), (2, 1, 0, 1), (0, 1, 0, 0)]
    groups = [
        ("PLANTA-CORTE", np.array([(0, 0, 2, 1)], float)),
        ("Muros ñ", np.array(square, float), "DASHDOT", (1.0, 0.0, 0.0), 0.7),
        ("Muros ñ-PERFIL", np.array([(0, 0, 0, 1)], float), "DASHDOT",
         (1.0, 0.0, 0.0), None),
        ("Vacía", np.zeros((0, 4))),
        ("PLANTA", np.array([(0, 0, 1, 1)], float)),
    ]
    path = tmp_path / "v.svg"
    n = save_svg_layers(path, groups, scale_n=50.0,
                        pens={"cut": 0.6, "profile": 0.4, "edge": 0.2})
    assert n == 7
    root, layers = _layers(path)
    assert list(layers) == ["PLANTA-CORTE", "Muros ñ", "Muros ñ-PERFIL",
                            "PLANTA"]                    # the empty one: out
    # 2 m × 1 m at 1:50 = 40 × 20 mm, plus a 10 mm margin all round.
    assert root.get("width") == "60.000mm"
    assert root.get("height") == "40.000mm"
    assert root.get("viewBox") == "0 0 60.000 40.000"
    muros = layers["Muros ñ"]
    assert muros.get("stroke") == "#ff0000"
    assert muros.get("stroke-width") == "0.7"            # the layer's own pen
    assert muros.get("stroke-dasharray")
    assert layers["Muros ñ-PERFIL"].get("stroke-width") == "0.4"
    assert layers["PLANTA-CORTE"].get("stroke-width") == "0.6"
    assert layers["PLANTA"].get("stroke-width") == "0.2"
    assert layers["PLANTA"].get("stroke") == "#000000"
    assert layers["PLANTA"].get("stroke-dasharray") is None
    paths = muros.findall(SVG + "path")
    assert len(paths) == 4                       # one per side
    # The model's y up is the page's y down: (0, 1) m sits at the top.
    corners = {p for el in paths for p in _points(el)}
    assert corners == {(10.0, 30.0), (50.0, 30.0), (50.0, 10.0),
                       (10.0, 10.0)}
    ids = [g.get("id") for g in root.findall(SVG + "g")]
    assert len(set(ids)) == len(ids) and all(i[0].isalpha() or i[0] == "_"
                                             for i in ids)


def test_an_empty_view_still_writes_a_valid_svg(tmp_path):
    from formats.svg_out import save_svg_layers
    path = tmp_path / "vacia.svg"
    assert save_svg_layers(path, [("VISTA", np.zeros((0, 4)))]) == 0
    _root, layers = _layers(path)
    assert layers == {}


def test_the_dxf_still_reads_groups_that_carry_a_pen(tmp_path):
    """The layer groups now carry a fifth element, the pen; the DXF writer
    keeps reading them as before."""
    from formats.dxf_out import save_dxf_layers
    path = tmp_path / "v.dxf"
    n = save_dxf_layers(path, [("A", [(0, 0, 1, 0)], "DASHED",
                                (1.0, 0.0, 0.0), 0.5)])
    assert n == 1
    assert "0\nLAYER\n2\nA\n70\n0\n62\n1\n6\nDASHED\n" in path.read_text(
        encoding="ascii")


# ---- From the program ------------------------------------------------------

def _two_layer_scene(scene):
    from core.group import Group
    from core.layers import DEFAULT_LAYER, Layer
    from core.mesh import Mesh

    def box(mesh, x0):
        V = QVector3D
        mesh.add_face([V(x0, 0, 0), V(x0 + 1, 0, 0), V(x0 + 1, 1, 0),
                       V(x0, 1, 0)])

    scene.layers[:] = [Layer(DEFAULT_LAYER),
                       Layer("Muros", linetype="dashed", lineweight=0.5),
                       Layer("Mobiliario", color=(0.0, 0.0, 1.0))]
    a, b = Group(Mesh(), name="a"), Group(Mesh(), name="b")
    box(a.mesh, 0.0)
    box(b.mesh, 3.0)
    a.layer, b.layer = "Muros", "Mobiliario"
    scene.groups[:] = [a, b]
    scene.version += 1


def test_the_export_menu_writes_the_view_as_svg(tmp_path, monkeypatch):
    from PySide6.QtGui import QAction
    from views import main_window as mw
    from views.main_window import MainWindow

    from views import export_svg_dialog
    monkeypatch.setattr(
        export_svg_dialog, "ask_svg_options",
        lambda parent, *a, **k: (True, {"textures": True,
                                        "as_view": True}, None))
    win = MainWindow()
    try:
        labels = [a.text() for a in win.findChildren(QAction)]
        assert any("SVG" in t for t in labels)
        vp = win.viewport
        vp.resize(800, 600)
        vp.camera.set_aspect(800, 600)
        _two_layer_scene(vp.scene)
        vp.notify_scene_changed()
        lo, hi = vp.scene.bounds()
        vp.camera.fit_to(lo, hi, 1.2)
        for mode in ("parallel", "perspective"):
            vp.camera.perspective = mode == "perspective"
            vp.camera.two_point = False
            asked = tmp_path / mode                  # no extension typed
            monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                                lambda *a, p=asked, **k: (str(p), ""))
            win._on_export_view_svg()
            root, layers = _layers(tmp_path / f"{mode}.svg")
            assert root.findall(f".//{SVG}path"), mode
            # The faces go under the lines, on their own layers.
            names = list(layers)
            faces = [i for i, n in enumerate(names) if n.endswith("-CARAS")]
            lines = [i for i, n in enumerate(names) if "-CARAS" not in n]
            assert faces and lines and max(faces) < min(lines), names
        _root, layers = _layers(tmp_path / "parallel.svg")
        names = " ".join(layers)
        assert "Muros" in names and "Mobiliario" in names
        blue = [g for name, g in layers.items()
                if name.startswith("Mobil") and "-CARAS" not in name]
        assert blue
        assert all(g.get("stroke") == "#0000ff" for g in blue)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_composer_frame_goes_out_at_its_scale_and_pens(tmp_path,
                                                           monkeypatch):
    from core.composition import MarcoVista
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        _two_layer_scene(win.viewport.scene)
        win.viewport.notify_scene_changed()
        sizes = {}
        for scale in (50.0, 100.0):
            frame = MarcoVista(view_key="std:top", scale_n=scale,
                               w_mm=100.0, h_mm=100.0, pen_profile_mm=0.3)
            path = tmp_path / f"planta-{scale:g}.svg"
            assert comp.export_frame_svg(frame, str(path)) > 0
            root, layers = _layers(path)
            sizes[scale] = float(root.get("width").rstrip("mm"))
            names = list(layers)
            assert any(n.startswith("Muros") for n in names), names
            assert any(n.startswith("Mobiliario") for n in names), names
            assert any(n.endswith("-PERFIL") for n in names), names
            for name, g in layers.items():
                if name.endswith("-PERFIL"):
                    assert g.get("stroke-width") == "0.3", name
        # 4 m of drawing: 80 mm at 1:50, 40 mm at 1:100, plus the margins.
        assert sizes[50.0] - 20 == pytest.approx(2 * (sizes[100.0] - 20),
                                                 rel=1e-3)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- The faces --------------------------------------------------------------

def _box(mesh, x0=0.0, y0=0.0, z0=0.0, s=1.0):
    """A closed cube, every face wound outwards."""
    V = QVector3D
    x1, y1, z1 = x0 + s, y0 + s, z0 + s
    for loop in (
            [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
            [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
            [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]):
        mesh.add_face([V(*p) for p in loop])


def _camera(scene, view="iso"):
    from core.camera import OrbitCamera
    cam = OrbitCamera()
    cam.set_aspect(800, 600)
    cam.perspective = False
    cam.set_view(view)
    lo, hi = scene.bounds()
    cam.fit_to(lo, hi, 1.2)
    return cam


def _ring_area(f):
    from core.vista_caras import _area
    return sum(abs(_area(r)) for r in f.rings)


def test_the_matte_light_is_the_viewport_s():
    from core.vista_caras import MATTE_LIGHT
    from views.viewport import Viewport
    light = Viewport._LIGHT
    assert np.allclose(MATTE_LIGHT, [light.x(), light.y(), light.z()])


def test_an_unpainted_box_is_ingetrazo_white_lit_as_in_the_view():
    from core.scene import Scene
    from core.style import DEFAULT_FACE_COLOR
    from core.vista_caras import shade_factor, shaded, view_faces
    scene = Scene()
    _box(scene.loose_mesh)
    faces = view_faces(scene, _camera(scene))
    assert len(faces) == 3                       # top and two sides
    assert not any(f.back for f in faces)
    tones = sorted({f.rgb for f in faces})
    assert len(tones) == 3                       # three lights, three tones
    top = shaded(DEFAULT_FACE_COLOR, shade_factor((0, 0, 1)))
    assert max(tones) == top                     # the top is the lightest
    flat = view_faces(scene, _camera(scene), as_view=False)
    assert {f.rgb for f in flat} == {tuple(DEFAULT_FACE_COLOR)}


def test_a_painted_object_wears_its_colour_and_a_face_its_own():
    from core.group import Group
    from core.mesh import Mesh
    from core.scene import Scene
    from core.vista_caras import view_faces
    scene = Scene()
    g = Group(Mesh(), name="caja")
    _box(g.mesh)
    g.material = {"color": (0.0, 0.0, 1.0)}
    top = next(f for f in g.mesh.faces if f.normal().z() > 0.5)
    top.attrs["color"] = (1.0, 0.0, 0.0)
    scene.groups.append(g)
    faces = view_faces(scene, _camera(scene), as_view=False)
    assert sorted(f.rgb for f in faces) == [(0.0, 0.0, 1.0), (0.0, 0.0, 1.0),
                                            (1.0, 0.0, 0.0)]
    assert {f.layer for f in faces} == {"Layer 0"}


def test_a_nearer_face_hides_what_is_behind_it():
    """Seen from the top, a square floating over a bigger one: the lower
    keeps only the ring round the upper — no face lies under another."""
    from core.scene import Scene
    from core.vista_caras import view_faces
    V = QVector3D
    scene = Scene()
    scene.loose_mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 4, 0),
                               V(0, 4, 0)])
    scene.loose_mesh.add_face([V(1, 1, 1), V(3, 1, 1), V(3, 3, 1),
                               V(1, 3, 1)])
    from core.vista_caras import _area
    faces = view_faces(scene, _camera(scene, "top"))
    assert len(faces) == 2
    upper, lower = sorted(faces, key=lambda f: len(f.rings))
    assert _ring_area(upper) == pytest.approx(4.0, rel=1e-4)
    # The lower one: its outline with a hole where the upper one is.
    assert sorted(abs(_area(r)) for r in lower.rings) == pytest.approx(
        [4.0, 16.0], rel=1e-4)


def test_glass_hides_nothing_and_a_face_seen_from_behind_is_back_colour():
    from core.scene import Scene
    from core.style import effective_back_color
    from core.vista_caras import view_faces
    V = QVector3D
    scene = Scene()
    scene.loose_mesh.add_face([V(0, 0, 0), V(4, 0, 0), V(4, 4, 0),
                               V(0, 4, 0)])
    glass = scene.loose_mesh.add_face([V(1, 1, 1), V(3, 1, 1), V(3, 3, 1),
                                       V(1, 3, 1)])
    glass.attrs.update({"color": (0.5, 0.8, 1.0), "opacity": 0.3})
    faces = view_faces(scene, _camera(scene, "top"), as_view=False)
    assert sum(_ring_area(f) for f in faces) == pytest.approx(20.0,
                                                               rel=1e-4)
    see = [f for f in faces if f.opacity < 1]
    assert len(see) == 1 and faces[-1] is see[0]     # drawn last, on top
    # From below, the floor shows its back.
    back = [f for f in view_faces(scene, _camera(scene, "bottom"),
                                  as_view=False) if f.opacity >= 1]
    assert back and all(f.back for f in back)
    assert back[0].rgb == tuple(effective_back_color(scene.display_style,
                                                     scene))


def _png(path, w=8, h=4):
    from PySide6.QtGui import QColor, QImage
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(200, 40, 40))
    assert img.save(str(path))
    return str(path)


def _quadrants(path):
    """An 8 x 8 texture of four plain quadrants, to read orientation."""
    from PySide6.QtGui import QColor, QImage
    img = QImage(8, 8, QImage.Format_RGB32)
    cols = {(0, 0): (220, 30, 30), (1, 0): (30, 200, 30),
            (0, 1): (30, 30, 220), (1, 1): (230, 220, 30)}
    for x in range(8):
        for y in range(8):
            img.setPixelColor(x, y, QColor(*cols[(x // 4, y // 4)]))
    assert img.save(str(path))
    return str(path), img


def test_a_textured_face_is_one_shape_filled_as_the_view_lays_it(tmp_path):
    """A 2 x 1 m wall with a 0.5 x 0.5 m tile, seen from the front at 1:100:
    one path filled with a pattern that needs no transform — the texture is
    laid onto the face here, as the viewport does (its world → UV map and
    its image turned bottom-up), so any program shows it the same."""
    import base64
    from PySide6.QtGui import QImage
    from core.scene import Scene
    from core.texture import face_uv_axes
    from core.vista_caras import view_faces
    from formats.svg_out import save_svg_layers
    XL = "{http://www.w3.org/1999/xlink}href"
    V = QVector3D
    scene = Scene()
    wall = scene.loose_mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 0, 1),
                                      V(0, 0, 1)])
    path, src = _quadrants(tmp_path / "cuadrantes.png")
    tex = {"path": path, "sw": 0.5, "sh": 0.5}
    wall.attrs["texture"] = tex
    faces = view_faces(scene, _camera(scene, "front"), as_view=False)
    assert len(faces) == 1 and faces[0].texture is not None
    out = tmp_path / "muro.svg"
    save_svg_layers(out, [], scale_n=100.0, faces=faces)
    root, layers = _layers(out)
    paths = layers["Layer 0-CARAS"].findall(SVG + "path")
    assert len(paths) == 1
    fill = paths[0].get("fill")
    assert fill.startswith("url(#")
    pat = root.find(f".//{SVG}pattern[@id='{fill[5:-1]}']")
    assert pat.get("patternTransform") is None
    # The fill covers the wall's box: 2 x 1 m at 1:100.
    # The tile is the page from its origin; the image covers the wall's
    # box (2 x 1 m at 1:100) where the wall is.
    assert pat.get("x") == "0" and pat.get("y") == "0"
    assert float(pat.get("width")) == pytest.approx(
        float(root.get("width").rstrip("mm")))
    pic = pat.find(SVG + "image")
    assert float(pic.get("width")) == pytest.approx(20.0, abs=0.01)
    assert float(pic.get("height")) == pytest.approx(10.0, abs=0.01)
    assert float(pic.get("x")) == pytest.approx(10.0, abs=0.01)  # margin
    uri = pic.get(XL)
    baked = QImage.fromData(base64.b64decode(uri.split(",", 1)[1]))
    gu, cu, gv, cv = face_uv_axes(tex, wall.normal())
    for wx, wz in ((0.1, 0.1), (0.4, 0.9), (0.6, 0.3), (1.3, 0.6),
                   (1.85, 0.15)):
        p = V(wx, 0, wz)
        u = QVector3D.dotProduct(gu, p) + cu
        v = QVector3D.dotProduct(gv, p) + cv
        # The viewport uploads the image bottom-up: v = 0 is its last row.
        tx = int((u % 1.0) * 8)
        ty = int((1.0 - v % 1.0) * 8) % 8
        want = src.pixelColor(tx, ty)
        # Front view: page x follows world x, page y runs down world z.
        got = baked.pixelColor(int(wx / 2 * baked.width()),
                               int((1 - wz) * baked.height()))
        assert abs(got.red() - want.red()) < 40, (wx, wz)
        assert abs(got.green() - want.green()) < 40, (wx, wz)
        assert abs(got.blue() - want.blue()) < 40, (wx, wz)
    # Without textures: its mean colour, no pattern.
    wall.attrs["texture"] = {"path": _png(tmp_path / "rojo.png"),
                             "sw": 1.0, "sh": 1.0}
    flat = view_faces(scene, _camera(scene, "front"), textures=False)
    assert flat[0].texture is None
    assert flat[0].rgb[0] > flat[0].rgb[1]       # reddish, as the image


def test_a_shaded_texture_is_darkened_in_the_file(tmp_path):
    import base64
    from PySide6.QtGui import QImage
    from formats.svg_out import _image_uri
    png = _png(tmp_path / "t.png")
    imgs = [QImage.fromData(base64.b64decode(u.split(",", 1)[1]))
            for u in (_image_uri(png, 1.0), _image_uri(png, 0.5))]
    r_full = imgs[0].pixelColor(1, 1).red()
    r_dark = imgs[1].pixelColor(1, 1).red()
    assert r_dark == pytest.approx(r_full * 0.5, abs=4)


def _settings(tmp_path, advanced=True):
    """Settings of its own for a test; the dialog in its advanced mode
    unless asked (the tests of the full dialog), or in its basic one."""
    from PySide6.QtCore import QSettings
    from views.export_svg_dialog import _KEY
    name = "ajustes.ini" if advanced else "ajustes-basico.ini"
    st = QSettings(str(tmp_path / name), QSettings.IniFormat)
    if st.value(_KEY + "advanced") is None:
        st.setValue(_KEY + "advanced", advanced)
    return st


def test_the_dialog_offers_the_ways_for_the_faces_and_the_light(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    dlg = ExportSvgDialog(None, screen_mm=(217.0, 174.0),
                          settings=_settings(tmp_path))
    # The first time: the view as on screen — what you see, like the screen.
    assert dlg.options() == {"image": True}
    assert dlg.paper() == {"area": "view", "size": "screen"}
    assert (dlg.w_box.value(), dlg.h_box.value()) == (217.0, 174.0)
    assert not dlg.w_box.isEnabled()                 # shown, not typed
    dlg.face_buttons["full"].setChecked(True)
    assert dlg.options() == {"materials": True, "textures": True,
                             "as_view": True, "shadows": False}
    assert dlg.note.text() == dlg.face_buttons["full"].toolTip()
    dlg.face_buttons["colours"].setChecked(True)
    assert dlg.options() == {"materials": True, "textures": False,
                             "as_view": True, "shadows": False}
    dlg.face_buttons["default"].setChecked(True)
    dlg.as_view_box.setChecked(False)
    assert dlg.options() == {"materials": False, "textures": False,
                             "as_view": False, "shadows": False}
    dlg.face_buttons["view"].setChecked(True)
    assert dlg.options() == {"image": True}
    assert not dlg.as_view_box.isEnabled()
    dlg.face_buttons["none"].setChecked(True)
    assert dlg.options() is None
    dlg.deleteLater()

def test_the_dialog_remembers_the_last_choice(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    st = _settings(tmp_path)
    dlg = ExportSvgDialog(None, settings=st)
    dlg.face_buttons["default"].setChecked(True)
    dlg.as_view_box.setChecked(False)
    dlg.accept()
    again = ExportSvgDialog(None, settings=st)
    assert again.face_buttons["default"].isChecked()
    assert not again.as_view_box.isChecked()
    for d in (dlg, again):
        d.deleteLater()


def test_each_choice_has_its_own_little_cube():
    from views.export_svg_dialog import FACE_CHOICES, cube_preview
    images = [cube_preview(key).toImage() for key, _o in FACE_CHOICES]
    assert all(not im.isNull() for im in images)
    # Four different pictures: textured, coloured, white, lines.
    keys = {bytes(im.constBits()) for im in images}
    assert len(keys) == len(FACE_CHOICES) == 5


def test_default_colour_only_drops_every_material_and_texture(tmp_path):
    """Painted, textured, see-through: with «Default colour only» every
    face comes out in IngeTrazo's default colour, lit as the view or flat,
    opaque, with no image — a clean model to colour elsewhere."""
    from core.group import Group
    from core.mesh import Mesh
    from core.scene import Scene
    from core.style import DEFAULT_FACE_COLOR
    from core.vista_caras import shade_factor, shaded, view_faces
    from formats.svg_out import save_svg_layers
    scene = Scene()
    g = Group(Mesh(), name="caja")
    _box(g.mesh)
    g.material = {"color": (0.0, 0.0, 1.0), "opacity": 0.4}
    top = next(f for f in g.mesh.faces if f.normal().z() > 0.5)
    top.attrs["texture"] = {"path": _png(tmp_path / "t.png"), "sw": 1.0,
                            "sh": 1.0}
    scene.groups.append(g)
    flat = view_faces(scene, _camera(scene), as_view=False,
                      materials=False, textures=False)
    assert len(flat) == 3
    assert {f.rgb for f in flat} == {tuple(DEFAULT_FACE_COLOR)}
    assert all(f.texture is None and f.opacity == 1.0 for f in flat)
    lit = view_faces(scene, _camera(scene), materials=False,
                     textures=False)
    tones = {f.rgb for f in lit}
    assert len(tones) == 3
    assert shaded(DEFAULT_FACE_COLOR, shade_factor((0, 0, 1))) in tones
    out = tmp_path / "limpio.svg"
    save_svg_layers(out, [], faces=lit)
    assert "data:image" not in out.read_text(encoding="utf-8")


def test_the_composer_frame_takes_its_faces_too(tmp_path, monkeypatch):
    from core.composition import MarcoVista
    from views.composer import ComposerWindow
    from views.main_window import MainWindow
    monkeypatch.setattr(ComposerWindow, "render_frame", lambda self, f: None)
    win = MainWindow()
    comp = ComposerWindow(win)
    try:
        _two_layer_scene(win.viewport.scene)
        win.viewport.notify_scene_changed()
        frame = MarcoVista(view_key="std:top", scale_n=50.0, w_mm=100.0,
                           h_mm=100.0)
        path = tmp_path / "planta.svg"
        comp.export_frame_svg(frame, str(path),
                              faces={"textures": True, "as_view": True})
        _root, layers = _layers(path)
        assert "Muros-CARAS" in layers and "Mobiliario-CARAS" in layers
        assert len(layers["Mobiliario-CARAS"].findall(SVG + "path")) == 1
        comp.export_frame_svg(frame, str(path))           # lines alone
        _root, layers = _layers(path)
        assert not any("-CARAS" in n for n in layers)
    finally:
        comp.close()
        win._saved_version = win.viewport.scene.version
        win.close()


def _slab(mesh, x0, y0, z0, sx, sy, sz):
    """A closed box sx x sy x sz, faces wound outwards."""
    V = QVector3D
    x1, y1, z1 = x0 + sx, y0 + sy, z0 + sz
    for loop in (
            [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
            [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
            [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],
            [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]):
        mesh.add_face([V(*p) for p in loop])


@pytest.mark.parametrize("perspective", [False, True])
def test_a_thin_slab_shows_its_top_not_its_underside(perspective):
    """Sorted by mean depth, the underside of a thin, wide slab came out
    nearer than its top and hid it (the test house's roof slope)."""
    from core.scene import Scene
    from core.vista_caras import view_faces
    scene = Scene()
    _slab(scene.loose_mesh, 0, 0, 3, 8.0, 4.0, 0.05)
    cam = _camera(scene)
    cam.perspective = perspective
    faces = view_faces(scene, cam, as_view=False)
    assert not any(f.back for f in faces)
    top = max(faces, key=_ring_area)
    total = sum(_ring_area(f) for f in faces)
    assert _ring_area(top) > 0.8 * total


def test_a_box_at_the_far_end_of_a_big_floor_stays_in_view():
    """A floor reaching toward the eye has its mean depth nearer than a box
    standing at its far end; the box must still show, the floor round it."""
    from core.scene import Scene
    from core.vista_caras import view_faces
    V = QVector3D
    scene = Scene()
    scene.loose_mesh.add_face([V(-20, -20, 0), V(2, -20, 0), V(2, 2, 0),
                               V(-20, 2, 0)])
    _slab(scene.loose_mesh, 0, 0, 0, 1, 1, 1)
    faces = view_faces(scene, _camera(scene), as_view=False)
    assert len(faces) == 4                       # floor + three box faces
    floor = max(faces, key=_ring_area)
    box = sum(_ring_area(f) for f in faces if f is not floor)
    assert box == pytest.approx(0.5 + 2 * 0.6124, rel=0.01)   # top, sides


def test_two_faces_that_cross_each_show_the_part_in_front():
    """An X seen from the front: each upright face is in front of the other
    on one side of the crossing — no order by depth can draw that."""
    from core.scene import Scene
    from core.vista_caras import view_faces
    V = QVector3D
    scene = Scene()
    scene.loose_mesh.add_face([V(-1, -1, 0), V(1, 1, 0), V(1, 1, 1),
                               V(-1, -1, 1)])
    scene.loose_mesh.add_face([V(-1, 1, 0), V(1, -1, 0), V(1, -1, 1),
                               V(-1, 1, 1)])
    faces = view_faces(scene, _camera(scene, "front"), as_view=False)
    assert len(faces) == 2
    areas = sorted(_ring_area(f) for f in faces)
    assert areas == pytest.approx([1.0, 1.0], rel=1e-3)   # half of 2 x 1 each


def test_in_perspective_the_texture_lands_where_the_camera_puts_it():
    """Seen in perspective a textured wall's map to the drawing is
    projective: any point of the wall, taken through its texture
    coordinates, must land where the camera projects it — an affine guess
    from three points broke the brick courses at every piece of wall."""
    from PySide6.QtCore import QPointF
    from core.scene import Scene
    from core.texture import face_uv_axes
    from core.vista_caras import _Perspective, view_faces
    from formats.svg_out import _uv_to_page
    V = QVector3D
    scene = Scene()
    wall = scene.loose_mesh.add_face([V(0, 0, 0), V(6, 0, 0), V(6, 0, 3),
                                      V(0, 0, 3)])
    tex = {"path": _png(_tmp_png_dir() / "t.png"), "sw": 0.5, "sh": 0.25}
    wall.attrs["texture"] = tex
    cam = _camera(scene)
    cam.perspective = True
    cam.distance *= 0.6                        # strong perspective
    faces = view_faces(scene, cam, as_view=False)
    assert len(faces) == 1
    pins = faces[0].texture["uv"]
    assert len(pins) == 4
    t = _uv_to_page(pins, lambda x: x, lambda y: y)
    proj = _Perspective(cam)
    gu, cu, gv, cv = face_uv_axes(tex, wall.normal())
    for wx, wz in ((0.2, 0.2), (5.8, 0.3), (5.5, 2.9), (0.3, 2.7),
                   (3.1, 1.4)):
        p = V(wx, 0, wz)
        u = QVector3D.dotProduct(gu, p) + cu
        v = QVector3D.dotProduct(gv, p) + cv
        got = t.map(QPointF(u, -v))
        want = proj.point(np.array([wx, 0.0, wz]))
        assert got.x() == pytest.approx(want[0], abs=1e-6), (wx, wz)
        assert got.y() == pytest.approx(want[1], abs=1e-6), (wx, wz)


def _tmp_png_dir():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


def test_default_colour_only_also_inks_every_line_black(tmp_path,
                                                         monkeypatch):
    from views import export_svg_dialog, main_window as mw
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(800, 600)
        vp.camera.set_aspect(800, 600)
        _two_layer_scene(vp.scene)
        vp.notify_scene_changed()
        lo, hi = vp.scene.bounds()
        vp.camera.fit_to(lo, hi, 1.2)
        vp.camera.perspective = False
        strokes = {}
        for name, opts in (("color", {"materials": True, "textures": True,
                                      "as_view": True}),
                           ("defecto", {"materials": False,
                                        "textures": False,
                                        "as_view": True})):
            monkeypatch.setattr(export_svg_dialog, "ask_svg_options",
                                lambda parent, *a, o=opts, **k: (
                                    True, o, None))
            monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                                lambda *a, n=name, **k: (
                                    str(tmp_path / n), ""))
            win._on_export_view_svg()
            _root, layers = _layers(tmp_path / f"{name}.svg")
            strokes[name] = {g.get("stroke") for n, g in layers.items()
                             if "-CARAS" not in n}
        assert "#0000ff" in strokes["color"]           # Mobiliario, blue
        assert strokes["defecto"] == {"#000000"}
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


# ---- Sun shadows, picture of the view, paper, preview ----------------------

def _sunny(scene):
    scene.shadows.enabled = True
    scene.shadows.month, scene.shadows.day = 6, 21
    scene.shadows.hour, scene.shadows.minute = 10, 0
    from core.sun import scene_sun_direction
    return np.array(scene_sun_direction(scene))


def test_the_ground_shadow_falls_away_from_the_sun():
    from core.scene import Scene
    from core.vista_caras import GROUND_LAYER, _Parallel, view_faces
    scene = Scene()
    _slab(scene.loose_mesh, 0, 0, 0, 1, 1, 3)        # a 3 m post
    d = _sunny(scene)
    cam = _camera(scene, "top")
    faces = view_faces(scene, cam, shadows=True)
    ground = [f for f in faces if f.extra.get("ground_shadow")]
    assert len(ground) == 1 and ground[0].layer == GROUND_LAYER
    # Its far end is where the post's top throws it.
    tip = np.array([0.5, 0.5, 3.0]) - d * (3.0 / d[2])
    want = _Parallel(cam).point(tip)
    pts = np.concatenate(ground[0].rings)
    far = pts[np.argmax(pts @ (want / np.linalg.norm(want)))]
    assert np.linalg.norm(far - want) < 0.75
    # Without shadows asked, or with the document's off: none.
    assert not any(f.extra.get("ground_shadow")
                   for f in view_faces(scene, cam))
    scene.shadows.enabled = False
    assert not any(f.extra.get("ground_shadow") or f.shadow
                   for f in view_faces(scene, cam, shadows=True))


def test_a_post_shades_part_of_a_slab_and_a_wall_turned_away_is_dark():
    """A slab with a post standing beside it on the sun's side: part of
    the slab's top is in the post's shadow, not all of it; the post's side
    turned from the sun is in shadow whole."""
    from core.scene import Scene
    from core.vista_caras import view_faces
    scene = Scene()
    d = _sunny(scene)
    _slab(scene.loose_mesh, -3, -3, 0, 6, 6, 0.2)    # the slab
    # The post on the sun's side, so its shadow crosses the slab.
    ox, oy = -0.5 + 2.0 * d[0] / np.hypot(d[0], d[1]), \
        -0.5 + 2.0 * d[1] / np.hypot(d[0], d[1])
    _slab(scene.loose_mesh, ox, oy, 0.2, 1, 1, 3)
    faces = view_faces(scene, _camera(scene, "iso"), shadows=True)
    top = max((f for f in faces if not f.extra.get("ground_shadow")),
              key=_ring_area)                       # the slab's top
    assert top.shadow
    dark = sum(abs(_area_of(r)) for r in top.shadow)
    assert 0.02 * _ring_area(top) < dark < 0.6 * _ring_area(top)
    assert 0.0 < top.shadow_alpha < 1.0
    turned = [f for f in faces if f.extra.get("seen_normal") is not None
              and float(np.asarray(f.extra["seen_normal"]) @ d) < 0]
    assert turned and all(f.shadow for f in turned)


def _area_of(r):
    from core.vista_caras import _area
    return _area(r)


def test_the_shadows_go_out_on_layers_of_their_own(tmp_path):
    from core.scene import Scene
    from core.vista_caras import view_faces
    from formats.svg_out import save_svg_layers
    scene = Scene()
    _slab(scene.loose_mesh, 0, 0, 0, 1, 1, 3)
    _sunny(scene)
    faces = view_faces(scene, _camera(scene), shadows=True)
    out = tmp_path / "sombras.svg"
    save_svg_layers(out, [], faces=faces)
    _root, layers = _layers(out)
    assert "SOMBRAS-SUELO" in layers and "Layer 0-SOMBRAS" in layers
    names = list(layers)
    assert names.index("Layer 0-CARAS") < names.index("Layer 0-SOMBRAS")
    veil = layers["Layer 0-SOMBRAS"].find(SVG + "path")
    assert veil.get("fill") == "#000000"
    assert float(veil.get("fill-opacity")) == pytest.approx(
        1.0 - scene.shadows.darkness, abs=0.01)


def test_a_sheet_of_paper_takes_the_drawing_fitted_and_centred():
    from formats.svg_out import svg_text
    import xml.etree.ElementTree as ET2
    groups = [("PLANTA", np.array([(0, 0, 8, 0), (8, 0, 8, 2)], float))]
    text, _n = svg_text(groups, paper=(297.0, 210.0))
    root = ET2.fromstring(text)
    assert root.get("width") == "297.000mm"
    assert root.get("height") == "210.000mm"
    # 8 m across 277 mm of sheet: 1:28.9 — said as 1:29.
    assert root.find(SVG + "desc").text == "1:29"
    xs = [p[0] for el in root.iter(SVG + "path") for p in _points(el)]
    assert min(xs) == pytest.approx(10.0, abs=0.01)
    assert max(xs) == pytest.approx(287.0, abs=0.01)


def test_the_picture_of_the_view_lies_under_the_lines_on_its_window():
    from PySide6.QtGui import QColor, QImage
    from formats.svg_out import svg_text
    import xml.etree.ElementTree as ET2
    img = QImage(40, 20, QImage.Format_RGB32)
    img.fill(QColor(10, 120, 200))
    groups = [("VISTA", np.array([(1, 1, 3, 1)], float))]
    text, _n = svg_text(groups, scale_n=100.0,
                        image=(img, (0.0, 0.0, 4.0, 2.0)))
    root = ET2.fromstring(text)
    layers = [g.get(INK + "label") for g in root.findall(SVG + "g")]
    assert layers[0] == "VISTA-IMAGEN" and "VISTA" in layers
    pic = root.find(f"{SVG}g/{SVG}image")
    assert float(pic.get("width")) == pytest.approx(40.0)    # 4 m at 1:100
    assert float(pic.get("height")) == pytest.approx(20.0)
    assert root.get("width") == "60.000mm"           # the window + margin


@pytest.mark.parametrize("perspective", [False, True])
def test_the_window_rect_holds_what_the_screen_shows(perspective):
    from core.scene import Scene
    from core.vista_caras import _Parallel, _Perspective, view_rect
    scene = Scene()
    _slab(scene.loose_mesh, 0, 0, 0, 2, 2, 2)
    cam = _camera(scene)
    cam.perspective = perspective
    x0, y0, x1, y1 = view_rect(cam)
    assert x1 > x0 and y1 > y0
    assert (x1 - x0) / (y1 - y0) == pytest.approx(cam.aspect, rel=1e-6)
    # The orbit target sits in the middle of the window.
    t = cam.target
    proj = _Perspective(cam) if perspective else _Parallel(cam)
    mid = proj.point(np.array([t.x(), t.y(), t.z()]))
    assert mid[0] == pytest.approx((x0 + x1) / 2, abs=1e-6)


def test_the_builder_works_each_thing_out_once():
    from views.svg_export import SvgBuilder
    counts = {"lines": 0, "faces": 0}

    def lines():
        counts["lines"] += 1
        return [("VISTA", np.array([(0, 0, 1, 0)], float))]

    def faces(**o):
        counts["faces"] += 1
        return []

    b = SvgBuilder(lines, faces)
    opts = {"materials": True, "textures": True, "as_view": True,
            "shadows": False}
    b.build(opts, None, preview=True)
    b.build(opts, (297.0, 210.0), preview=True)
    b.build(dict(opts), (420.0, 297.0))
    assert counts == {"lines": 1, "faces": 1}
    b.build({**opts, "as_view": False}, None)
    assert counts["faces"] == 2


def test_the_screen_size_sheet_is_the_window_edge_to_edge():
    """«Screen size»: the page is what the window shows, at its size, with
    no margin — and what lies past it is cut off at the page."""
    import xml.etree.ElementTree as ET2
    from views.svg_export import SvgBuilder
    lines = [("VISTA", np.array([(-5, 0, 5, 0), (0, -1, 0, 1)], float))]
    b = SvgBuilder(lambda: lines, lambda **o: [],
                   window=lambda: (-2.0, -1.0, 2.0, 1.0),
                   screen_mm=(200.0, 100.0))
    text, _n = b.build(None, "screen")
    root = ET2.fromstring(text)
    assert root.get("width") == "200.000mm"
    assert root.get("height") == "100.000mm"
    assert root.find(f"{SVG}defs/{SVG}clipPath") is not None
    layer = next(g for g in root.findall(SVG + "g")
                 if g.get(INK + "label") == "VISTA")
    assert layer.get("clip-path") == "url(#pagina)"
    # 4 m across 200 mm: the vertical stroke at x = 0 sits in the middle.
    xs = {round(p[0], 3) for el in layer.iter(SVG + "path")
          for p in _points(el)}
    assert 100.0 in xs
    # The drawing at its scale and the sheets keep working.
    assert ET2.fromstring(b.build(None, None)[0]).get("width") != "200.000mm"


def test_the_cubes_are_whole_inside_their_picture():
    from views.export_svg_dialog import FACE_CHOICES, cube_preview
    for key, _o in FACE_CHOICES:
        img = cube_preview(key, 56).toImage()
        # Nothing drawn on the picture's top and bottom rows.
        for y in (0, 55):
            assert all(img.pixelColor(x, y).alpha() == 0
                       for x in range(56)), (key, y)


def test_the_picture_of_the_view_can_leave_the_axes_out(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    from views.svg_export import SvgBuilder
    st = _settings(tmp_path)
    dlg = ExportSvgDialog(None, axes_available=True, settings=st)
    dlg.face_buttons["view"].setChecked(True)
    assert dlg.axes_box.isEnabled() and dlg.axes_box.isChecked()
    assert dlg.options() == {"image": True, "axes": False}
    dlg.axes_box.setChecked(False)
    assert dlg.options() == {"image": True}
    dlg.face_buttons["full"].setChecked(True)
    assert not dlg.axes_box.isEnabled()                  # faces: no axes
    # A view without axes: nothing to hide.
    plain = ExportSvgDialog(None, axes_available=False, settings=st)
    plain.face_buttons["view"].setChecked(True)
    assert not plain.axes_box.isEnabled()
    assert plain.options() == {"image": True}
    # The builder asks for the picture with or without them, each once.
    asked = []

    def image(width, axes=True):
        asked.append((width, axes))
        return None

    b = SvgBuilder(lambda: [], lambda **o: [], image)
    b.build({"image": True, "axes": False}, None, preview=True)
    b.build({"image": True, "axes": False}, None, preview=True)
    b.build({"image": True}, None, preview=True)
    assert [a for _w, a in asked] == [False, True]
    for d in (dlg, plain):
        d.deleteLater()


def test_the_view_picture_without_axes_leaves_the_view_as_it_was(
        monkeypatch):
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        seen = []
        monkeypatch.setattr(vp, "render_image", lambda *a, **k: seen.append(
            vp.scene.show_axes))
        vp.scene.show_axes = True
        builder = win.view_svg_builder()
        builder.image(True, axes=False)
        builder.image(True, axes=True)
        assert seen == [False, True]
        assert vp.scene.show_axes is True
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_preview_can_be_turned_off(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    calls = []

    def build(options, paper, preview=False):
        calls.append(preview)
        from formats.svg_out import svg_text
        return svg_text([("VISTA", np.array([(0, 0, 1, 0)], float))])

    st = _settings(tmp_path)
    dlg = ExportSvgDialog(None, build, settings=st)
    dlg.preview_box.setChecked(False)
    calls.clear()
    dlg.face_buttons["full"].setChecked(True)
    dlg._refresh_preview()
    assert calls == []
    assert dlg.preview.text()                          # «Preview off»
    dlg.accept()
    again = ExportSvgDialog(None, build, settings=st)
    assert not again.preview_box.isChecked()           # remembered
    again.preview_box.setChecked(True)
    again._refresh_preview()
    assert calls == [True]
    for d in (dlg, again):
        d.deleteLater()


def test_the_sheet_takes_the_part_and_the_size_apart():
    """What you see on an A3 widens the window to the sheet's shape round
    its middle, edge to edge; the whole model on A3 fits with a margin;
    at the drawing's scale the sheet is as big as it needs."""
    import xml.etree.ElementTree as ET2
    from views.svg_export import SvgBuilder
    lines = [("VISTA", np.array([(-5, 0, 5, 0), (0, -1, 0, 1)], float))]
    b = SvgBuilder(lambda: lines, lambda **o: [],
                   window=lambda: (-2.0, -1.0, 2.0, 1.0),
                   screen_mm=(200.0, 100.0))

    def page(sheet):
        root = ET2.fromstring(b.build(None, sheet)[0])
        return (float(root.get("width").rstrip("mm")),
                float(root.get("height").rstrip("mm")),
                root.find(SVG + "desc").text,
                root.find(f"{SVG}defs/{SVG}clipPath") is not None)

    # What you see, like the screen: 4 m across 200 mm, cut at the page.
    assert page({"area": "view", "size": "screen"}) == (200.0, 100.0,
                                                         "1:20", True)
    # What you see on A3 landscape: the 4 x 2 m window (2:1) grows to
    # 420:297 round its middle — taller, its 4 m across 420 mm.
    w, h, scale, clipped = page({"area": "view", "size": (420.0, 297.0)})
    assert (w, h, clipped) == (420.0, 297.0, True)
    assert scale == "1:9.5"
    # The whole model on A3: 10 m across 400 mm, no cutting.
    w, h, scale, clipped = page({"area": "model", "size": (420.0, 297.0)})
    assert (w, h, scale, clipped) == (420.0, 297.0, "1:25", False)
    # The whole model at the drawing's scale: 10 m at 1:100 + margins.
    assert page({"area": "model", "size": None})[:2] == (120.0, 40.0)
    # What you see at the drawing's scale: the window at 1:100, no margin.
    assert page({"area": "view", "size": None})[:2] == (40.0, 20.0)



def test_the_size_list_opens_upwards(tmp_path):
    from PySide6.QtWidgets import QApplication
    from views.export_svg_dialog import ExportSvgDialog
    dlg = ExportSvgDialog(None, settings=_settings(tmp_path))
    dlg.move(200, 500)
    dlg.show()
    QApplication.processEvents()
    combo = dlg.size_combo
    combo.showPopup()
    QApplication.processEvents()
    popup = combo.view().window()
    combo_top = combo.mapToGlobal(combo.rect().topLeft()).y()
    assert popup.geometry().bottom() <= combo_top
    combo.hidePopup()
    dlg.close()
    dlg.deleteLater()


def test_the_selection_part_exports_only_what_is_selected(tmp_path):
    """«Selection»: only the selected objects, as if the rest were hidden —
    and the model is left as it was."""
    from core.group import Group
    from core.mesh import Mesh
    from core.scene import Scene
    from core.vista_caras import view_faces
    from views.export_svg_dialog import ExportSvgDialog
    from views.svg_export import SvgBuilder, selection_only
    scene = Scene()
    a, b = Group(Mesh(), name="a"), Group(Mesh(), name="b")
    _slab(a.mesh, 0, 0, 0, 1, 1, 1)
    _slab(b.mesh, 3, 0, 0, 1, 1, 1)
    scene.groups[:] = [a, b]
    scene.selection.add(b)
    cam = _camera(scene)
    everything = view_faces(scene, cam, as_view=False)
    with selection_only(scene):
        only_b = view_faces(scene, cam, as_view=False)
    assert len(everything) == 6 and len(only_b) == 3
    assert scene.entity_visible(a)                  # back as it was
    # Through the builder: the faces with the selection alone, cached apart.
    built = []

    def faces(**o):
        built.append(scene.entity_visible(a))
        return []

    builder = SvgBuilder(lambda fast=True: [], faces,
                         isolate=lambda: selection_only(scene))
    opts = {"materials": True, "textures": True, "as_view": True,
            "shadows": False}
    builder.build(opts, {"area": "selection", "size": None})
    builder.build(opts, {"area": "model", "size": None})
    assert built == [False, True]
    # The dialog offers it only with something selected — for every
    # choice, the picture of the view too.
    dlg = ExportSvgDialog(None, selection_available=True,
                          settings=_settings(tmp_path))
    dlg.face_buttons["full"].setChecked(True)
    dlg.area_combo.setCurrentIndex(dlg.area_combo.findData("selection"))
    assert dlg.paper()["area"] == "selection"
    dlg.face_buttons["view"].setChecked(True)
    assert dlg.paper()["area"] == "selection"
    none = ExportSvgDialog(None, selection_available=False,
                           settings=_settings(tmp_path))
    item = none.area_combo.model().item(none.area_combo.findData("selection"))
    assert not item.isEnabled()
    for d in (dlg, none):
        d.deleteLater()


@pytest.mark.parametrize("perspective", [False, True])
def test_a_sheet_of_another_shape_shows_what_lay_past_the_screen(
        perspective):
    """«What you see» on a sheet of another shape: the view as in a window
    of that shape — wider shows more at the sides with the same height,
    taller shows more above and below with the same width — and the
    camera is left as it was."""
    from core.scene import Scene
    from core.vista_caras import view_rect
    from views.svg_export import widened
    scene = Scene()
    _slab(scene.loose_mesh, 0, 0, 0, 2, 2, 2)
    cam = _camera(scene)
    cam.perspective = perspective
    before = (cam.aspect, cam.distance, cam.fov_deg)
    x0, y0, x1, y1 = view_rect(cam)
    w, h = x1 - x0, y1 - y0
    with widened(cam, cam.aspect * 2.0):
        a0, b0, a1, b1 = view_rect(cam)
    assert (b1 - b0) == pytest.approx(h, rel=1e-6)
    assert (a1 - a0) == pytest.approx(2.0 * w, rel=1e-6)
    with widened(cam, cam.aspect / 2.0):
        a0, b0, a1, b1 = view_rect(cam)
    assert (a1 - a0) == pytest.approx(w, rel=1e-6)
    assert (b1 - b0) == pytest.approx(2.0 * h, rel=1e-6)
    assert (cam.aspect, cam.distance, cam.fov_deg) == before


def test_the_builder_works_a_new_shape_out_in_the_widened_view():
    from views.svg_export import SvgBuilder
    inside = []

    class Widen:
        def __init__(self, aspect):
            self.aspect = aspect

        def __enter__(self):
            inside.append(self.aspect)

        def __exit__(self, *_a):
            inside.append(None)

    shapes = []

    def image(width, axes=True, aspect=None):
        shapes.append(aspect)
        return None, (0.0, 0.0, 2.0 * (aspect or 1.0), 2.0)

    b = SvgBuilder(lambda fast=True: [], lambda **o: [], image,
                   window=lambda: (0.0, 0.0, 2.0, 2.0),
                   screen_mm=(100.0, 100.0), widen=Widen)
    b.build({"image": True}, {"area": "view", "size": (300.0, 100.0)},
            preview=True)
    assert shapes == [3.0] and 3.0 in inside
    # The screen's own shape, or the whole model: nothing to widen.
    inside.clear()
    b.build({"image": True}, {"area": "view", "size": (200.0, 200.0)},
            preview=True)
    b.build(None, {"area": "model", "size": (300.0, 100.0)})
    assert inside == []


# ---- The sheet: on screen, custom (paper sheet, proportion, mm), at scale --

def _sheet_state(dlg):
    return {"sheet": dlg.sheet_combo.isEnabled(),
            "ratio": dlg.ratio_combo.isEnabled(),
            "mm": dlg.w_box.isEnabled() and dlg.h_box.isEnabled(),
            "turn": dlg.turn_buttons["landscape"].isEnabled()}


def test_only_custom_switches_on_the_controls_that_depend_on_it(tmp_path):
    """The acceptance: a main choice — on screen, custom, at scale —; with
    «Custom» the paper sheet, the proportion (when no sheet sets one) and
    the millimetres come on; with anything else they all go off."""
    from views.export_svg_dialog import ExportSvgDialog
    # The view has no scale of its own to keep: no «at scale».
    view = ExportSvgDialog(None, screen_mm=(300.0, 200.0),
                           settings=_settings(tmp_path))
    assert [view.size_combo.itemData(i)
            for i in range(view.size_combo.count())] == ["screen", "custom"]
    view.deleteLater()
    # A composer frame has one.
    dlg = ExportSvgDialog(None, base_label="Frame scale (1:50)",
                          screen_mm=(300.0, 200.0),
                          settings=_settings(tmp_path))
    modes = [dlg.size_combo.itemData(i)
             for i in range(dlg.size_combo.count())]
    assert modes == ["screen", "custom", "scale"]
    off = {"sheet": False, "ratio": False, "mm": False, "turn": False}
    assert dlg.paper()["size"] == "screen"
    assert _sheet_state(dlg) == off
    assert (dlg.w_box.value(), dlg.h_box.value()) == (300.0, 200.0)
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("custom"))
    assert _sheet_state(dlg) == {"sheet": True, "ratio": True, "mm": True,
                                 "turn": True}
    # A paper sheet sets its own proportion: the proportion goes off.
    dlg.sheet_combo.setCurrentIndex(dlg.sheet_combo.findData("A3"))
    assert _sheet_state(dlg) == {"sheet": True, "ratio": False,
                                 "mm": True, "turn": True}
    assert dlg.paper()["size"] == (420.0, 297.0)
    # Out of «Custom»: everything that hangs on it off again.
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("scale"))
    assert _sheet_state(dlg) == off
    assert dlg.paper()["size"] is None
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("screen"))
    assert _sheet_state(dlg) == off
    dlg.deleteLater()


def test_custom_begins_at_the_screen_and_a_sheet_turns(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    dlg = ExportSvgDialog(None, screen_mm=(300.0, 200.0),
                          settings=_settings(tmp_path))
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("custom"))
    assert dlg.paper()["size"] == (300.0, 200.0)
    assert dlg.sheet_combo.currentData() == "none"
    assert dlg.ratio_combo.currentData() == "screen"
    dlg.sheet_combo.setCurrentIndex(dlg.sheet_combo.findData("A4"))
    assert dlg.paper()["size"] == (297.0, 210.0)
    dlg.turn_buttons["portrait"].click()
    assert dlg.paper()["size"] == (210.0, 297.0)
    # Its measures changed: your own measures again, free.
    dlg.w_box.setValue(250.0)
    assert dlg.sheet_combo.currentData() == "none"
    assert dlg.ratio_combo.currentData() == "free"
    assert dlg.ratio_combo.isEnabled()
    assert dlg.paper()["size"] == (250.0, 297.0)
    dlg.deleteLater()


def test_a_proportion_keeps_the_shape_and_square_has_no_turn(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    dlg = ExportSvgDialog(None, screen_mm=(300.0, 200.0),
                          settings=_settings(tmp_path))
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("custom"))
    dlg.ratio_combo.setCurrentIndex(dlg.ratio_combo.findData("16:9"))
    dlg.turn_buttons["landscape"].click()
    dlg.w_box.setValue(320.0)
    assert dlg.paper()["size"] == (320.0, 180.0)
    dlg.turn_buttons["portrait"].click()
    assert dlg.paper()["size"] == (320.0, 569.0)
    dlg.h_box.setValue(640.0)
    assert dlg.paper()["size"] == (360.0, 640.0)
    # Square: the height takes the width; there is no turn to make.
    dlg.ratio_combo.setCurrentIndex(dlg.ratio_combo.findData("1:1"))
    assert dlg.paper()["size"] == (360.0, 360.0)
    assert not dlg.turn_buttons["landscape"].isEnabled()
    dlg.w_box.setValue(250.0)
    assert dlg.paper()["size"] == (250.0, 250.0)
    # Out of the square: a turn is there again.
    dlg.ratio_combo.setCurrentIndex(dlg.ratio_combo.findData("4:3"))
    assert dlg.turn_buttons["landscape"].isEnabled()
    dlg.turn_buttons["landscape"].click()
    assert dlg.paper()["size"] == (250.0, 188.0)
    # Free: each side its own; the turn swaps them and follows them.
    dlg.ratio_combo.setCurrentIndex(dlg.ratio_combo.findData("free"))
    dlg.h_box.setValue(100.0)
    assert dlg.paper()["size"] == (250.0, 100.0)
    dlg.turn_buttons["portrait"].click()
    assert dlg.paper()["size"] == (100.0, 250.0)
    dlg.w_box.setValue(400.0)
    assert dlg.turn_buttons["landscape"].isChecked()
    dlg.deleteLater()


def test_the_dialog_previews_the_sheet_and_remembers_it(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    from formats.svg_out import svg_text
    calls = []

    def build(options, sheet, preview=False):
        calls.append((options, sheet, preview))
        groups = [("VISTA", np.array([(0, 0, 4, 0), (4, 0, 4, 2)], float))]
        size = sheet["size"]
        return svg_text(groups, paper=size if isinstance(size, tuple)
                        else None)

    st = _settings(tmp_path)
    dlg = ExportSvgDialog(None, build, "1:100", screen_mm=(217.0, 174.0),
                          settings=st, selection_available=True)
    assert dlg.area_combo.findData("model") < 0     # no «whole model»
    dlg.face_buttons["full"].setChecked(True)
    dlg.area_combo.setCurrentIndex(dlg.area_combo.findData("selection"))
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("scale"))
    dlg._refresh_preview()
    assert calls and calls[-1][2] is True
    assert not dlg.preview.pixmap().isNull()
    assert "1:100" in dlg.preview_note.text()
    assert dlg.w_box.value() == 60.0                 # 4 m at 1:100 + 2 x 10
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("custom"))
    dlg.ratio_combo.setCurrentIndex(dlg.ratio_combo.findData("free"))
    dlg.w_box.setValue(500.0)
    dlg.h_box.setValue(250.0)
    dlg.accept()
    again = ExportSvgDialog(None, settings=st, selection_available=True)
    assert again.paper() == {"area": "selection", "size": (500.0, 250.0)}
    assert again.ratio_combo.currentData() == "free"
    sunny = ExportSvgDialog(None, shadows_available=True, settings=st)
    sunny.face_buttons["full"].setChecked(True)
    assert sunny.shadows_box.isEnabled()
    assert sunny.options()["shadows"] is True
    for d in (dlg, again, sunny):
        d.deleteLater()



# ---- Framing: drag and wheel on the preview ---------------------------------

@pytest.mark.parametrize("perspective", [False, True])
def test_the_framing_moves_and_zooms_the_view_and_leaves_it_as_it_was(
        perspective):
    from core.scene import Scene
    from core.vista_caras import _Parallel, _Perspective, view_rect
    from views.svg_export import framed
    scene = Scene()
    _slab(scene.loose_mesh, 0, 0, 0, 2, 2, 2)
    cam = _camera(scene)
    cam.perspective = perspective
    before = (cam.target.x(), cam.target.y(), cam.target.z(),
              cam.distance, cam.fov_deg)
    x0, y0, x1, y1 = view_rect(cam)
    w = x1 - x0
    t = np.array([cam.target.x(), cam.target.y(), cam.target.z()])

    def seen(c):
        proj = _Perspective(c) if perspective else _Parallel(c)
        return proj.point(t)

    # Half a window to the right: the old middle now sits half a window
    # to the left of the new one.
    with framed(cam, (0.5, 0.0, 1.0)):
        assert seen(cam)[0] == pytest.approx(-0.5 * w, rel=1e-6)
    # Twice as close: half as much across.
    with framed(cam, (0.0, 0.0, 2.0)):
        a0, _b0, a1, _b1 = view_rect(cam)
        assert (a1 - a0) == pytest.approx(w / 2.0, rel=1e-6)
    assert (cam.target.x(), cam.target.y(), cam.target.z(),
            cam.distance, cam.fov_deg) == before


def test_the_builder_frames_only_what_the_screen_shows():
    from views.svg_export import NO_FRAME, SvgBuilder
    asked = []

    class Frame:
        def __init__(self, frame):
            self.frame = frame

        def __enter__(self):
            asked.append(self.frame)

        def __exit__(self, *_a):
            pass

    b = SvgBuilder(lambda fast=True: [], lambda **o: [],
                   window=lambda: (0.0, 0.0, 2.0, 1.0),
                   screen_mm=(200.0, 100.0), frame=Frame)
    assert b.can_frame()
    b.build(None, {"area": "view", "size": "screen",
                   "frame": (0.25, 0.0, 2.0)})
    assert (0.25, 0.0, 2.0) in asked
    asked.clear()
    b.build(None, {"area": "view", "size": "screen", "frame": NO_FRAME})
    b.build(None, {"area": "model", "size": None,
                   "frame": (0.25, 0.0, 2.0)})
    assert asked == []
    assert not SvgBuilder(lambda: [], lambda **o: []).can_frame()


def test_dragging_and_turning_the_wheel_on_the_preview_frame_it(tmp_path):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from views.export_svg_dialog import ExportSvgDialog
    from views.svg_export import NO_FRAME
    from formats.svg_out import svg_text

    def build(options, sheet, preview=False):
        return svg_text([("VISTA", np.array([(0, 0, 4, 0), (4, 0, 4, 2)],
                                            float))])

    dlg = ExportSvgDialog(None, build, screen_mm=(200.0, 100.0),
                          can_frame=True, selection_available=True,
                          settings=_settings(tmp_path))
    dlg.show()
    dlg._refresh_preview()
    QApplication.processEvents()
    page = dlg.preview._page
    assert page.width() > 0
    assert dlg.paper().get("frame") is None          # the view as it is
    assert not dlg.frame_reset.isEnabled()
    # Drag a quarter of the sheet to the right: the framing goes left.
    start = page.center().toPoint()
    end = start + QPoint(round(page.width() / 4), 0)
    QTest.mousePress(dlg.preview, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(dlg.preview, end)
    QTest.mouseRelease(dlg.preview, Qt.LeftButton, Qt.NoModifier, end)
    px, py, zoom = dlg.paper()["frame"]
    assert px == pytest.approx(-0.25, abs=0.02)
    assert py == pytest.approx(0.0, abs=1e-6) and zoom == 1.0
    assert dlg.frame_reset.isEnabled()
    # The wheel, one notch in: 15 % closer.
    pos = QPointF(page.center())
    wheel = QWheelEvent(pos, dlg.preview.mapToGlobal(pos), QPoint(0, 0),
                        QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    QApplication.sendEvent(dlg.preview, wheel)
    assert dlg.paper()["frame"][2] == pytest.approx(1.15)
    dlg.frame_reset.click()
    assert dlg.paper().get("frame") is None
    assert dlg._frame == NO_FRAME
    # Another part, or no way to reframe: no framing at all.
    dlg.face_buttons["full"].setChecked(True)
    dlg.area_combo.setCurrentIndex(dlg.area_combo.findData("selection"))
    assert dlg.area_combo.currentData() == "selection"
    assert not dlg.preview._framing
    plain = ExportSvgDialog(None, build, settings=_settings(tmp_path))
    plain.show()
    assert not plain.preview._framing
    assert not plain.frame_reset.isVisible()
    for d in (dlg, plain):
        d.close()
        d.deleteLater()


# ---- Composition guides over the preview ------------------------------------

@pytest.mark.parametrize("key,fracs", [("thirds", (1 / 3, 2 / 3)),
                                       ("golden", (0.382, 0.618)),
                                       ("grid", (0.25, 0.5, 0.75))])
def test_each_guide_falls_where_it_should(key, fracs):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from views.export_svg_dialog import draw_guides
    img = QImage(301, 201, QImage.Format_ARGB32)
    img.fill(Qt.black)
    page = QRectF(0, 0, 300, 200)
    p = QPainter(img)
    draw_guides(p, page, key)
    p.end()
    # A row that no horizontal guide crosses: only the upright ones light.
    lit = [x for x in range(1, 300) if img.pixelColor(x, 90).red() > 150]
    for f in fracs:
        assert any(abs(x - f * 300) <= 1.5 for x in lit), (key, f, lit)
    # Nothing far from them.
    assert all(any(abs(x - f * 300) <= 3 for f in fracs) for x in lit)


def test_the_guides_are_chosen_remembered_and_never_exported(tmp_path):
    from views.export_svg_dialog import GUIDES, ExportSvgDialog
    from formats.svg_out import svg_text
    texts = []

    def build(options, sheet, preview=False):
        text = svg_text([("VISTA", np.array([(0, 0, 4, 0)], float))])
        texts.append(text)
        return text

    st = _settings(tmp_path)
    dlg = ExportSvgDialog(None, build, settings=st)
    keys = [dlg.guides_combo.itemData(i)
            for i in range(dlg.guides_combo.count())]
    assert keys == list(GUIDES) and dlg.preview._guides == "thirds"
    dlg.guides_combo.setCurrentIndex(dlg.guides_combo.findData("golden"))
    assert dlg.preview._guides == "golden"
    dlg._refresh_preview()
    assert texts and "golden" not in texts[-1]
    # The sheet the export writes is the same with or without guides.
    without = svg_text([("VISTA", np.array([(0, 0, 4, 0)], float))])[0]
    assert texts[-1][0] == without
    dlg.accept()
    again = ExportSvgDialog(None, build, settings=st)
    assert again.guides_combo.currentData() == "golden"
    assert again.preview._guides == "golden"
    for d in (dlg, again):
        d.deleteLater()


# ---- The basic dialog --------------------------------------------------------

def test_the_basic_dialog_is_the_one_to_begin_with(tmp_path):
    """Compact, one column, no preview: what to export — the picture of the
    view (chosen), materials with or without textures or the default
    colour — and the size like the screen, its millimetres shown but not
    editable."""
    from PySide6.QtCore import QSettings
    from views.export_svg_dialog import ExportSvgDialog
    fresh = QSettings(str(tmp_path / "nuevo.ini"), QSettings.IniFormat)
    dlg = ExportSvgDialog(None, lambda *a, **k: ("", 0),
                          screen_mm=(278.0, 162.0), settings=fresh)
    dlg.show()
    assert not dlg.is_advanced() and not dlg.advanced_box.isChecked()
    assert dlg.basic_page.isVisible() and not dlg.advanced_page.isVisible()
    assert list(dlg.basic_buttons) == ["view", "full", "colours", "default"]
    assert dlg.basic_buttons["view"].isChecked()
    assert dlg.basic_size.currentData() == "screen"
    assert (dlg.basic_w.value(), dlg.basic_h.value()) == (278.0, 162.0)
    assert not dlg.basic_w.isEnabled() and not dlg.basic_h.isEnabled()
    assert dlg.options()["image"] is True
    assert dlg.paper() == {"area": "view", "size": "screen"}
    dlg.basic_buttons["colours"].setChecked(True)
    assert dlg.options()["textures"] is False
    dlg.basic_buttons["default"].setChecked(True)
    assert dlg.options()["materials"] is False
    dlg.close()
    dlg.deleteLater()


def test_custom_mm_starts_from_the_screen_and_the_lock_keeps_its_shape(
        tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    dlg = ExportSvgDialog(None, screen_mm=(278.0, 162.0),
                          settings=_settings(tmp_path, advanced=False))
    dlg.basic_size.setCurrentIndex(dlg.basic_size.findData("custom"))
    assert dlg.basic_w.isEnabled() and dlg.basic_h.isEnabled()
    assert (dlg.basic_w.value(), dlg.basic_h.value()) == (278.0, 162.0)
    assert dlg.basic_lock.isChecked()
    dlg.basic_w.setValue(556.0)
    assert dlg.paper()["size"] == (556.0, 324.0)      # the same shape
    dlg.basic_lock.setChecked(False)
    dlg.basic_h.setValue(100.0)
    assert dlg.paper()["size"] == (556.0, 100.0)      # free to distort
    dlg.basic_lock.setChecked(True)                   # this shape now
    dlg.basic_w.setValue(278.0)
    assert dlg.paper()["size"] == (278.0, 50.0)
    dlg.basic_size.setCurrentIndex(dlg.basic_size.findData("screen"))
    assert dlg.paper()["size"] == "screen"
    assert (dlg.basic_w.value(), dlg.basic_h.value()) == (278.0, 162.0)
    assert not dlg.basic_w.isEnabled()
    dlg.deleteLater()


def test_advanced_options_open_the_full_dialog_and_carry_the_choice(
        tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    st = _settings(tmp_path, advanced=False)
    dlg = ExportSvgDialog(None, lambda *a, **k: ("", 0),
                          screen_mm=(278.0, 162.0), settings=st)
    dlg.show()
    dlg.basic_buttons["view"].setChecked(True)
    dlg.basic_size.setCurrentIndex(dlg.basic_size.findData("custom"))
    dlg.basic_lock.setChecked(False)
    dlg.basic_w.setValue(300.0)
    dlg.basic_h.setValue(200.0)
    dlg.advanced_box.setChecked(True)
    assert dlg.is_advanced()
    assert dlg.advanced_page.isVisible() and not dlg.basic_page.isVisible()
    assert dlg.face_buttons["view"].isChecked()
    assert dlg.paper()["size"] == (300.0, 200.0)
    assert dlg.paper()["area"] == "view"
    # Back: the basic dialog takes what the advanced one says.
    dlg.face_buttons["colours"].setChecked(True)
    dlg.size_combo.setCurrentIndex(dlg.size_combo.findData("screen"))
    dlg.advanced_box.setChecked(False)
    assert not dlg.is_advanced() and dlg.basic_page.isVisible()
    assert dlg.basic_buttons["colours"].isChecked()
    assert dlg.paper() == {"area": "view", "size": "screen"}
    dlg.advanced_box.setChecked(True)                 # lines only: no such
    dlg.face_buttons["none"].setChecked(True)         # basic choice
    dlg.advanced_box.setChecked(False)
    assert dlg.basic_buttons["full"].isChecked()
    # The mode is remembered.
    dlg.advanced_box.setChecked(True)
    dlg.accept()
    again = ExportSvgDialog(None, settings=st)
    assert again.is_advanced()
    dlg.close()
    for d in (dlg, again):
        d.deleteLater()


def test_the_basic_dialog_works_nothing_out_before_export(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    calls = []
    dlg = ExportSvgDialog(None, lambda *a, **k: calls.append(1) or ("", 0),
                          settings=_settings(tmp_path, advanced=False))
    dlg.show()
    dlg.basic_buttons["view"].setChecked(True)
    dlg.basic_size.setCurrentIndex(dlg.basic_size.findData("custom"))
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    assert not dlg._timer.isActive() and calls == []
    dlg.close()
    dlg.deleteLater()



def test_both_dialogs_begin_with_the_picture_of_the_view(tmp_path):
    from PySide6.QtCore import QSettings
    from views.export_svg_dialog import ExportSvgDialog
    for advanced in (False, True):
        fresh = QSettings(str(tmp_path / f"nuevo-{advanced}.ini"),
                          QSettings.IniFormat)
        dlg = ExportSvgDialog(None, screen_mm=(278.0, 162.0), settings=fresh,
                              advanced=advanced)
        assert dlg.is_advanced() is advanced
        assert dlg.basic_buttons["view"].isChecked()
        assert dlg.face_buttons["view"].isChecked()
        assert dlg.options()["image"] is True
        dlg.deleteLater()


def test_switching_mode_keeps_the_dialog_centred_and_on_screen(tmp_path):
    """Basic to advanced and back: the dialog grows and shrinks about the
    middle of its window and stays wholly on the screen."""
    from PySide6.QtWidgets import QApplication, QWidget
    from views.export_svg_dialog import ExportSvgDialog
    host = QWidget()
    host.resize(1200, 800)
    host.show()
    dlg = ExportSvgDialog(host, lambda *a, **k: ("", 0),
                          screen_mm=(278.0, 162.0),
                          settings=_settings(tmp_path, advanced=False))
    dlg.show()
    QApplication.processEvents()
    avail = dlg.screen().availableGeometry()
    centre = host.frameGeometry().center()
    for on in (True, False):
        dlg.advanced_box.setChecked(on)
        QApplication.processEvents()
        g = dlg.frameGeometry()
        if g.width() <= avail.width() and g.height() <= avail.height():
            assert avail.contains(g)
        wanted = g.translated(centre - g.center())
        if avail.contains(wanted):                     # room to centre it
            assert (g.center() - centre).manhattanLength() <= 2
    dlg.close()
    host.close()
    for w in (dlg, host):
        w.deleteLater()


# ---- Scenes ------------------------------------------------------------------

def test_the_scene_row_is_there_only_with_scenes(tmp_path):
    from views.export_svg_dialog import ExportSvgDialog
    plain = ExportSvgDialog(None, lambda *a, **k: ("", 0),
                            settings=_settings(tmp_path))
    plain.show()
    assert not plain.scene_combo.isVisibleTo(plain)
    plain.advanced_box.setChecked(False)
    assert not plain.basic_scene.isVisibleTo(plain)
    assert plain.scene_index() is None
    calls, builds = [], []

    def on_scene(index):
        calls.append(index)
        build = (lambda *a, **k: builds.append(index) or ("", 0))
        return build

    dlg = ExportSvgDialog(None, lambda *a, **k: ("", 0),
                          settings=_settings(tmp_path),
                          scenes=["Plan", "Facade"], on_scene=on_scene)
    dlg.show()
    assert dlg.scene_combo.isVisibleTo(dlg)
    assert [dlg.scene_combo.itemText(i)
            for i in range(dlg.scene_combo.count())][1:] == ["Plan", "Facade"]
    assert dlg.scene_index() is None and calls == []
    dlg._frame = (0.2, 0.1, 2.0)
    dlg.scene_combo.setCurrentIndex(2)
    assert calls == [1] and dlg.scene_index() == 1
    assert dlg._frame == (0, 0, 1)                 # framed afresh
    dlg._timer.stop()
    dlg._refresh_preview()
    assert builds == [1]                           # the scene's builder
    # The quick dialog has the same choice: it keeps the scene, and a
    # scene chosen there is the advanced dialog's too.
    dlg.advanced_box.setChecked(False)
    assert dlg.basic_scene.isVisibleTo(dlg)
    assert calls == [1] and dlg.basic_scene.currentIndex() == 2
    dlg.basic_scene.setCurrentIndex(1)
    assert calls == [1, 0] and dlg.scene_index() == 0
    dlg.basic_scene.setCurrentIndex(0)
    assert calls == [1, 0, None] and dlg.scene_index() is None
    for d in (plain, dlg):
        d.close()
        d.deleteLater()


def test_a_scene_is_exported_and_the_view_comes_back(tmp_path, monkeypatch):
    from core.saved_views import SavedView
    from views import export_svg_dialog
    from views import main_window as mw
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(800, 600)
        vp.camera.set_aspect(800, 600)
        _two_layer_scene(vp.scene)
        vp.notify_scene_changed()
        lo, hi = vp.scene.bounds()
        vp.camera.fit_to(lo, hi, 1.2)
        vp.camera.perspective = False
        # A scene without the furniture, looking from elsewhere.
        mob = next(ly for ly in vp.scene.layers if ly.name == "Mobiliario")
        mob.visible = False
        yaw = vp.camera.yaw
        vp.camera.yaw = yaw + 1.0
        vp.scene.saved_views.append(
            SavedView.capture("Sin muebles", vp.scene, vp.camera))
        mob.visible = True
        vp.camera.yaw = yaw
        win._saved_version = vp.scene.version          # nothing to save

        def ask(parent, *a, scenes=None, on_scene=None, **k):
            assert scenes == ["Sin muebles"]
            on_scene(0)
            assert not mob.visible                     # shown meanwhile
            return True, {"textures": True, "as_view": True}, None

        monkeypatch.setattr(export_svg_dialog, "ask_svg_options", ask)
        monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                            lambda *a, **k: (str(tmp_path / "escena"), ""))
        win._on_export_view_svg()
        _root, layers = _layers(tmp_path / "escena.svg")
        names = " ".join(layers)
        assert "Muros" in names and "Mobiliario" not in names
        # The view as it was, and the document still unchanged.
        assert mob.visible and vp.camera.yaw == yaw
        assert vp.scene.version == win._saved_version
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_whole_model_is_all_of_it_not_what_the_screen_shows():
    """Zoomed in on a corner, «Whole model» still exports every part of
    the model — framed afresh, as Zoom Extents frames it — and leaves the
    camera as it was."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(800, 600)
        vp.camera.set_aspect(800, 600)
        _two_layer_scene(vp.scene)
        vp.notify_scene_changed()
        lo, hi = vp.scene.bounds()
        whole = {"area": "model", "size": None}
        for perspective in (False, True):
            vp.camera.perspective = perspective
            vp.camera.two_point = False
            vp.camera.fit_box(lo, hi)
            _t, everything = win.view_svg_builder().build(None, whole)
            # Close in on one corner: the screen shows a part of it.
            vp.camera.target = lo
            vp.camera.distance = vp.camera.distance / 4.0
            keep = (vp.camera.target, vp.camera.distance)
            builder = win.view_svg_builder()
            _t, on_screen = builder.build(None, {"area": "view",
                                                 "size": "screen"})
            text, n = builder.build({"textures": True, "as_view": True},
                                    whole)
            if perspective:              # only what the window shows
                assert on_screen < everything
            assert n == everything, perspective
            assert "Mobiliario-CARAS" in text and "Muros-CARAS" in text
            assert (vp.camera.target, vp.camera.distance) == keep
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_the_picture_of_the_selection_shows_the_selection_alone():
    """«Picture of the view» with «Selection»: the rest of the model is
    hidden for the picture, framed on the selection, and every flag — and
    the document's «nothing to save» — is back afterwards."""
    from views.main_window import MainWindow
    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(400, 300)
        vp.camera.set_aspect(400, 300)
        _two_layer_scene(vp.scene)
        vp.notify_scene_changed()
        lo, hi = vp.scene.bounds()
        vp.camera.fit_box(lo, hi)
        a, b = vp.scene.groups
        vp.scene.selection.clear()
        vp.scene.selection.add(b)
        win._saved_version = vp.scene.version
        seen = []
        real = vp.render_image

        def render(*args, **kw):
            seen.append((a.hidden, b.hidden))
            return real(*args, **kw)

        vp.render_image = render
        text, _n = win.view_svg_builder().build(
            {"image": True}, {"area": "selection", "size": None})
        assert seen == [(True, False)]               # the other one hidden
        assert not a.hidden and not b.hidden
        assert vp.scene.version == win._saved_version
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
