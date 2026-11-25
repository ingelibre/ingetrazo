# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The picture of the model inside the ``.igz`` (``thumbnail.png``): what
the file manager shows instead of the document icon.

- Saved as a stored (not deflated) member of the container, read back
  without opening the model; documents without it open as before.
- The first scene when the model has scenes, else the view; the view on
  screen comes back exactly as it was and the document stays clean.
- Anything that goes wrong saves the document without a picture."""
from __future__ import annotations

import json
import math
import zipfile

import pytest
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication

from core.camera import OrbitCamera
from core.layers import Layer
from core.saved_views import SavedView
from core.scene import Scene
from formats import igz
from views import document_thumbnail

_app = QApplication.instance() or QApplication([])

V = QVector3D


def _png(w=32, h=32, color="#3a7") -> bytes:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    data = document_thumbnail.png_bytes(img)
    assert data and data.startswith(b"\x89PNG")
    return data


def _box_scene() -> Scene:
    scene = Scene()
    p = [V(0, 0, 0), V(4, 0, 0), V(4, 4, 0), V(0, 4, 0),
         V(0, 0, 3), V(4, 0, 3), V(4, 4, 3), V(0, 4, 3)]
    for idx in ((3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                (2, 3, 7, 6), (3, 0, 4, 7)):
        scene.mesh.add_face([p[i] for i in idx])
    scene.version += 1
    return scene


# ---- The format ------------------------------------------------------------

def test_the_picture_is_stored_in_the_container(tmp_path):
    path = tmp_path / "box.igz"
    picture = _png()
    stats = igz.save_scene(_box_scene(), path, thumbnail=picture)
    assert stats["embedded"] == 0          # a picture is not a texture
    with zipfile.ZipFile(path) as z:
        info = z.getinfo(igz.THUMBNAIL_ENTRY)
        # Stored as it is: a reader needs no inflater to get it out.
        assert info.compress_type == zipfile.ZIP_STORED
        assert z.read(info) == picture
        data = json.loads(z.read("document.json"))
    # A plain model that gets a picture becomes a container at format 2,
    # which every build since 0.2.4 opens — no newer format for it.
    assert data["igz_format"] == igz.CONTAINER_FORMAT
    assert igz.read_thumbnail(path) == picture


def test_the_document_holds_one_picture_the_last_saved(tmp_path):
    """One picture per document: every save replaces it with the new one,
    and a save without one leaves none behind."""
    path = tmp_path / "box.igz"
    scene = _box_scene()
    igz.save_scene(scene, path, thumbnail=_png(color="#a00"))
    last = _png(color="#00a")
    igz.save_scene(scene, path, thumbnail=last)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    assert names.count(igz.THUMBNAIL_ENTRY) == 1
    assert [n for n in names if n.endswith(".png")] == [igz.THUMBNAIL_ENTRY]
    assert igz.read_thumbnail(path) == last
    igz.save_scene(scene, path)
    assert igz.read_thumbnail(path) is None


def test_a_document_with_a_picture_opens_as_before(tmp_path):
    path = tmp_path / "box.igz"
    igz.save_scene(_box_scene(), path, thumbnail=_png())
    scene = Scene()
    igz.load_into(scene, path)
    assert len(scene.mesh.faces) == 6


def test_without_a_picture_a_plain_model_stays_plain_json(tmp_path):
    path = tmp_path / "box.igz"
    igz.save_scene(_box_scene(), path)
    raw = path.read_bytes()
    assert raw.lstrip().startswith(b"{")
    assert json.loads(raw)["igz_format"] == igz.PLAIN_FORMAT
    assert igz.read_thumbnail(path) is None


def test_bytes_that_are_not_a_png_are_left_out(tmp_path):
    path = tmp_path / "box.igz"
    igz.save_scene(_box_scene(), path, thumbnail=b"GIF89a not a png")
    assert path.read_bytes().lstrip().startswith(b"{")
    assert igz.read_thumbnail(path) is None


def test_the_picture_rides_beside_the_textures(tmp_path):
    """A textured model keeps its count of packed textures, and its
    picture next to them."""
    tex = tmp_path / "brick.png"
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor("#a33"))
    assert img.save(str(tex))
    scene = _box_scene()
    scene.mesh.faces[0].attrs["texture"] = {"path": str(tex),
                                            "size": [1.0, 1.0]}
    path = tmp_path / "textured.igz"
    stats = igz.save_scene(scene, path, thumbnail=_png())
    assert stats["embedded"] == 1
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
    assert igz.THUMBNAIL_ENTRY in names
    assert any(n.startswith("textures/") for n in names)


def test_old_documents_without_a_picture_open(tmp_path):
    """A format-1 JSON document and a format-2 container written before
    the picture existed: both open, neither has a picture."""
    plain = tmp_path / "old-plain.igz"
    plain.write_text(json.dumps({
        "igz_format": 1, "app_version": "0.5.0",
        "scene": {"edges": [{"a": [0, 0, 0], "b": [1, 0, 0]}],
                  "faces": []}}), encoding="utf-8")
    container = tmp_path / "old-container.igz"
    with zipfile.ZipFile(container, "w") as z:
        z.writestr("document.json", json.dumps({
            "igz_format": 2, "app_version": "0.4.0",
            "scene": {"edges": [{"a": [0, 0, 0], "b": [0, 2, 0]}],
                      "faces": []}}))
    for path in (plain, container):
        scene = Scene()
        igz.load_into(scene, path)
        assert len(scene.mesh.edges) == 1
        assert igz.read_thumbnail(path) is None


def test_reading_the_picture_never_fails(tmp_path):
    assert igz.read_thumbnail(tmp_path / "missing.igz") is None
    junk = tmp_path / "junk.igz"
    junk.write_bytes(b"PK\x03\x04 broken archive")
    assert igz.read_thumbnail(junk) is None
    not_png = tmp_path / "not-png.igz"
    with zipfile.ZipFile(not_png, "w") as z:
        z.writestr("document.json", "{}")
        z.writestr(igz.THUMBNAIL_ENTRY, b"not a picture")
    assert igz.read_thumbnail(not_png) is None


# ---- What the picture shows ------------------------------------------------

class _Viewport:
    """The parts of the GL viewport the picture uses: it records the
    camera and the layers as they are when it renders."""

    def __init__(self, scene=None, fail=False):
        self.scene = scene or _box_scene()
        self.camera = OrbitCamera()
        self.camera.aspect = 16 / 9
        self.fail = fail
        self.seen = []
        self.updated = 0

    def render_image(self, w, h, overlays=True, **_kw):
        if self.fail:
            raise RuntimeError("no GL")
        self.seen.append({
            "size": (w, h), "overlays": overlays,
            "yaw": self.camera.yaw, "aspect": self.camera.aspect,
            "perspective": self.camera.perspective,
            "axes": getattr(self.scene, "show_axes", True),
            "visible": {ly.name: ly.visible for ly in self.scene.layers},
        })
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor("#468"))
        return img

    def update(self):
        self.updated += 1


def _two_scenes(vp):
    scene = vp.scene
    scene.layers.append(Layer("Roof"))
    first = SavedView("Front", yaw=1.25, pitch=0.2, perspective=False,
                      hidden_layers=["Roof"])
    second = SavedView("Back", yaw=-2.0, pitch=0.4)
    scene.saved_views = [first, second]
    return first, second


def test_a_model_without_scenes_shows_the_view_square():
    vp = _Viewport()
    vp.camera.yaw = 0.5
    data = document_thumbnail.for_save(vp)
    shot = vp.seen[-1]
    assert shot["size"] == (document_thumbnail.SIZE,) * 2
    assert shot["overlays"] is False         # no dimensions, texts, guides
    assert shot["axes"] is False             # nor the drawing axes …
    assert vp.scene.show_axes is True        # … which the view keeps
    assert shot["aspect"] == pytest.approx(1.0)
    assert shot["yaw"] == pytest.approx(0.5)
    assert vp.camera.aspect == pytest.approx(16 / 9)      # given back
    img = QImage.fromData(data)
    assert (img.width(), img.height()) == (document_thumbnail.SIZE,) * 2
    assert not img.hasAlphaChannel()          # opaque: no see-through holes


def test_a_model_with_scenes_shows_the_first_one():
    vp = _Viewport()
    first, _second = _two_scenes(vp)
    cam = vp.camera
    cam.yaw, cam.pitch, cam.perspective = 0.1, 0.3, True
    cam.target = V(1, 2, 3)
    before = (cam.yaw, cam.pitch, cam.distance, cam.fov_deg,
              cam.perspective, cam.aspect)
    content = vp.scene.content_version
    assert document_thumbnail.for_save(vp) is not None
    shot = vp.seen[-1]
    assert shot["yaw"] == pytest.approx(first.yaw)
    assert shot["perspective"] is False
    assert shot["visible"]["Roof"] is False   # the scene's layers
    assert shot["aspect"] == pytest.approx(1.0)
    # The view on screen is exactly as it was …
    assert (cam.yaw, cam.pitch, cam.distance, cam.fov_deg,
            cam.perspective, cam.aspect) == pytest.approx(before)
    assert (cam.target.x(), cam.target.y(), cam.target.z()) == (1, 2, 3)
    assert next(ly for ly in vp.scene.layers if ly.name == "Roof").visible
    assert vp.updated
    # … and showing a scene for the picture is not an edit.
    assert vp.scene.content_version == content


def test_a_scene_that_cannot_be_drawn_gives_the_view(monkeypatch):
    vp = _Viewport()
    first, _ = _two_scenes(vp)
    vp.camera.yaw = 0.7

    def broken(*_a, **_k):
        raise ValueError("broken scene")

    monkeypatch.setattr(first, "apply", broken)
    assert document_thumbnail.for_save(vp) is not None
    assert vp.seen[-1]["yaw"] == pytest.approx(0.7)
    assert math.isclose(vp.camera.yaw, 0.7)


def test_no_picture_when_rendering_fails_or_it_is_off(monkeypatch):
    assert document_thumbnail.for_save(_Viewport(fail=True)) is None
    from core import general_settings
    monkeypatch.setattr(general_settings, "value",
                        lambda name, default=None, settings=None:
                        "0" if name == document_thumbnail.SETTING
                        else default)
    vp = _Viewport()
    assert document_thumbnail.for_save(vp) is None
    assert not vp.seen                        # nothing was even rendered


# ---- Saving from the window ------------------------------------------------

@pytest.fixture
def window():
    from views.main_window import MainWindow
    win = MainWindow()
    scene = win.viewport.scene
    for f in _box_scene().mesh.faces:
        scene.mesh.add_face(list(f.vertices))
    scene.version += 1
    yield win
    win._saved_version = win.viewport.scene.version
    win._confirm_discard = lambda *a, **k: True
    win.close()


def test_saving_stores_the_picture_and_leaves_the_document_clean(
        window, tmp_path, monkeypatch):
    img = QImage(64, 64, QImage.Format_RGB32)
    img.fill(QColor("#2a6"))
    monkeypatch.setattr(document_thumbnail, "render", lambda vp, size=0: img)
    path = tmp_path / "saved.igz"
    window._do_save(path)
    picture = igz.read_thumbnail(path)
    assert picture is not None
    assert QImage.fromData(picture).size() == img.size()
    assert not window._is_dirty()


def test_saving_goes_on_when_the_picture_fails(window, tmp_path, monkeypatch):
    def broken(*_a, **_k):
        raise RuntimeError("the GL context is gone")

    monkeypatch.setattr(document_thumbnail, "render", broken)
    path = tmp_path / "saved.igz"
    window._do_save(path)
    assert path.is_file()
    assert igz.read_thumbnail(path) is None
    scene = Scene()
    igz.load_into(scene, path)
    assert len(scene.mesh.faces) == 6
    assert not window._is_dirty()


def test_the_real_render_gives_a_picture_of_the_model(window, tmp_path):
    """With a GL context (skipped on the offscreen platform): the picture
    is the size asked, and shows a model, not one flat colour."""
    window.show()
    for _ in range(3):
        _app.processEvents()
    vp = window.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        pytest.skip("no OpenGL context on this platform")
    vp.camera.set_view("iso")
    vp.camera.fit_to(V(0, 0, 0), V(4, 4, 3))
    _app.processEvents()
    path = tmp_path / "rendered.igz"
    window._do_save(path)
    img = QImage.fromData(igz.read_thumbnail(path))
    assert (img.width(), img.height()) == (document_thumbnail.SIZE,) * 2
    colours = {img.pixel(x, y) for x in range(0, img.width(), 16)
               for y in range(0, img.height(), 16)}
    assert len(colours) > 4
