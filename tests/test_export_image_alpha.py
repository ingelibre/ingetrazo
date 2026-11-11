# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""What an exported picture says about its alpha, read back from the PNG.

The scene's blending used to treat the alpha like a colour: a pane of 30 %
over an opaque background left 201 in the file and two panes 164, in every
picture, so a viewer showed a hole behind the glass. With the Transparent
background box of Export image the file is opaque only where the model is.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage, QVector3D
from PySide6.QtWidgets import QApplication, QDialog

_app = QApplication.instance() or QApplication([])
V = QVector3D
WIDTH = 900
GLASS = {"color": (0.2, 0.55, 0.85), "opacity": 0.3}


def _box(mesh, x0, x1, y0, y1, z0, z1, **attrs):
    c = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([c[i] for i in q]).attrs.update(attrs)


def _pane(mesh, x0, x1, y, **attrs):
    mesh.add_face([V(x0, y, 0), V(x1, y, 0), V(x1, y, 3),
                   V(x0, y, 3)]).attrs.update(attrs)


#: Where to look, as points on the front pane's plane.
ZONES = {"background": V(-7.5, -2, 4.5), "glass": V(-3, -2, 2.8),
         "double": V(-5, -2, 2.8), "glass_on_solid": V(-1, -2, 1.5),
         "solid": V(1.5, -2, 1.5), "tex_on_solid": V(4, -2, 1.5)}


@pytest.fixture
def view(tmp_path):
    from views.main_window import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    vp = win.viewport
    if getattr(vp, "_gl", None) is None or not vp.isValid():
        win._saved_version = vp.scene.version
        win.close()
        pytest.skip("no OpenGL context on this platform")
    mesh = vp.scene.mesh
    tex = tmp_path / "blue.png"
    img = QImage(8, 8, QImage.Format_RGB32)
    img.fill(QColor(40, 90, 200))
    img.save(str(tex))
    _box(mesh, -2, 6, 0, 4, 0, 3, color=(0.75, 0.35, 0.25))
    _pane(mesh, -6, 0, -2, **GLASS)
    _pane(mesh, -6, -4, -1.5, **GLASS)
    _pane(mesh, 3, 5, -2, opacity=0.3,
          texture={"path": str(tex), "sw": 1, "sh": 1})
    vp.scene.version += 1
    cam = vp.camera
    cam.perspective = False
    cam.target = V(0, 0, 1.5)
    cam.distance, cam.yaw, cam.pitch = 22.0, -1.5707963, 0.12
    yield win, vp, tmp_path
    vp.style_override = None
    vp.scene.shadows.enabled = False
    win._saved_version = vp.scene.version
    win.close()


def _saved(vp, folder, style, **kw):
    """The picture as a viewer gets it: written to disk and read back."""
    from core.style import style_by_name
    vp.style_override = style_by_name(style)
    path = folder / "out.png"
    assert vp.render_image(WIDTH, sharp_shadows=True, **kw).save(str(path))
    return QImage(str(path)).convertToFormat(QImage.Format_ARGB32)


def _rgba(img):
    """``img`` (Format_ARGB32) as rows of R, G, B, A."""
    buf = np.frombuffer(img.constBits(), np.uint8).reshape(
        img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return buf.reshape(img.height(), img.width(), 4)[..., [2, 1, 0, 3]].astype(float)


def _at(vp, img, zone):
    x, y = vp._world_to_pixel(ZONES[zone])
    scale = WIDTH / vp.width()
    return img.pixelColor(int(x * scale), int(y * scale))


@pytest.mark.parametrize("style", ["Default", "Shaded", "Monochrome",
                                   "Hidden line", "X-ray"])
@pytest.mark.parametrize("sun", [False, True])
def test_a_normal_picture_is_opaque_behind_the_glass(view, style, sun):
    _win, vp, folder = view
    vp.scene.shadows.enabled = sun
    img = _saved(vp, folder, style)
    for zone in ZONES:
        assert _at(vp, img, zone).alpha() == 255, zone


def test_the_occlusion_pass_leaves_the_same_blending(view, monkeypatch):
    """It multiplies with a blending of its own and puts the scene's back
    before the glass draws."""
    _win, vp, folder = view
    monkeypatch.setenv("INGETRAZO_AO", "1")
    img = _saved(vp, folder, "Default")
    for zone in ZONES:
        assert _at(vp, img, zone).alpha() == 255, zone


@pytest.mark.parametrize("style", ["Default", "Monochrome", "Hidden line",
                                   "X-ray", "Wireframe"])
def test_the_transparent_background_is_alpha_zero(view, style):
    _win, vp, folder = view
    img = _saved(vp, folder, style, transparent=True)
    assert _at(vp, img, "background").alpha() == 0


def test_the_box_only_lasts_that_picture(view):
    _win, vp, folder = view
    _saved(vp, folder, "Default", transparent=True)
    # The view on screen first: no export call sets the flag for it.
    live = vp.grabFramebuffer()
    x, y = vp._world_to_pixel(ZONES["background"])
    assert live.pixelColor(int(x), int(y)).lightness() > 150
    assert _at(vp, _saved(vp, folder, "Default"), "background").alpha() == 255


def test_glass_on_nothing_keeps_its_own_opacity_and_colour(view):
    """A pane of 30 % is alpha 0.3 in the file, two are 1 - 0.7², and the
    colour is the glass's, not darkened by the empty background."""
    _win, vp, folder = view
    img = _saved(vp, folder, "Shaded", transparent=True)
    assert _at(vp, img, "glass").alpha() == pytest.approx(0.3 * 255, abs=2)
    assert _at(vp, img, "double").alpha() == pytest.approx(0.51 * 255, abs=2)
    glass = _at(vp, img, "glass")
    assert glass.blue() > glass.green() > glass.red() > 25
    assert glass.blue() > 140, "the colour must not come out premultiplied"
    assert _at(vp, img, "glass_on_solid").alpha() == 255
    assert _at(vp, img, "solid").alpha() == 255


def test_the_model_is_the_same_as_in_a_normal_picture(view):
    _win, vp, folder = view
    plain = _saved(vp, folder, "Shaded")
    clear = _saved(vp, folder, "Shaded", transparent=True)
    for zone in ("solid", "glass_on_solid", "tex_on_solid"):
        assert _at(vp, plain, zone).getRgb() == _at(vp, clear, zone).getRgb()


@pytest.mark.parametrize("style", ["Hidden line", "Monochrome", "Architectural"])
def test_the_edges_leave_no_halo(view, style):
    """Laid over the style's own background, the transparent picture is the
    normal one, pixel by pixel: an edge's antialiased pixels, against nothing,
    are the edge's colour at a low alpha and carry no fringe of a background
    that is not there."""
    _win, vp, folder = view
    plain = _rgba(_saved(vp, folder, style))
    clear = _rgba(_saved(vp, folder, style, transparent=True))
    bg = np.array(vp._effective_style().background[:3]) * 255.0
    a = clear[..., 3:] / 255.0
    over = clear[..., :3] * a + bg * (1.0 - a)
    edge = (clear[..., 3] > 0) & (clear[..., 3] < 255)
    assert edge.sum() > 100, "the model's outline must have soft pixels"
    assert np.abs(over - plain[..., :3]).max() <= 4


def test_a_shadow_on_the_ground_is_translucent_black(view):
    """No ground under it: the shadow stays, as black at the style's
    darkness, the way a compositor expects it."""
    _win, vp, folder = view
    vp.scene.shadows.enabled = True
    img = _saved(vp, folder, "Shaded", transparent=True)
    w, h = img.width(), img.height()
    seen = [img.pixelColor(x, y) for y in range(0, h, 2)
            for x in range(0, w, 2)]
    shadow = [c for c in seen if 0 < c.alpha() < 255
              and c.red() == c.green() == c.blue() == 0]
    assert shadow, "the shadow on the ground must reach the picture"
    # ...and a shadow is not what the background turned into:
    assert sum(1 for c in seen if c.alpha() == 0) > len(seen) // 2


@pytest.fixture
def export(view, monkeypatch):
    """Export image as the menu runs it, its file dialog answered: ``run``
    ticks the box as told and returns the file read back. ``seen`` holds the
    dialog as the user found it."""
    from views import export_image_dialog as eid
    from views.filedialogs import file_dialogs
    win, vp, folder = view
    seen = {}

    def run(name, tick=None, width=900):
        target = folder / name

        def answer(self):
            seen["enabled"] = self.transparent_box.isEnabled()
            seen["checked"] = self.transparent_box.isChecked()
            seen["tip"] = self.transparent_box.toolTip()
            self.width_box.setValue(width)
            if tick is not None:
                self.transparent_box.setChecked(tick)
            return QDialog.Accepted

        monkeypatch.setattr(eid.ExportImageDialog, "exec", answer)
        monkeypatch.setattr(file_dialogs, "getSaveFileName",
                            lambda *a, **k: (str(target), ""))
        win._on_export_image()
        return QImage(str(target)).convertToFormat(QImage.Format_ARGB32)

    return vp, run, seen


def test_the_box_is_offered_for_a_png_and_starts_off(export):
    vp, run, seen = export
    img = run("a.png")
    assert seen == {"enabled": True, "checked": False, "tip": ""}
    assert _at(vp, img, "background").alpha() == 255


def test_ticking_it_makes_the_png_transparent(export):
    vp, run, _seen = export
    img = run("a.png", tick=True)
    assert img.width() == WIDTH
    assert _at(vp, img, "background").alpha() == 0
    assert _at(vp, img, "solid").alpha() == 255


def test_the_next_export_does_not_remember_it(export):
    """The dialog keeps none of its options: the width is 3840 each time."""
    _vp, run, seen = export
    run("a.png", tick=True)
    run("b.png")
    assert seen["checked"] is False


@pytest.mark.parametrize("name", ["a.jpg", "a.jpeg", "a.JPG"])
def test_a_jpeg_does_not_offer_it(export, name):
    vp, run, seen = export
    img = run(name)
    assert seen["enabled"] is False and seen["checked"] is False
    assert seen["tip"]
    assert _at(vp, img, "background").lightness() > 150


def test_a_disabled_box_never_counts():
    from views.export_image_dialog import ExportImageDialog
    dlg = ExportImageDialog(None, ".jpg")
    dlg.transparent_box.setChecked(True)     # by no hand: it is disabled
    assert dlg.transparent() is False
    dlg.deleteLater()


def test_the_new_texts_are_translated():
    """test_translation_files asks that every language has the message;
    here, that the message is what the dialog asks for."""
    from core import i18n
    data = json.loads((i18n._I18N_DIR / "es.json").read_text(encoding="utf-8"))
    assert data["Transparent background"] == "Fondo transparente"
    assert "PNG" in data["Only PNG images keep transparency."]


# ---- Glass in Monochrome: it used to vanish (a colour) or wall off what is
# behind it in white (a texture); it now shows, translucent and grey.


def _grey(c):
    return c.red() == c.green() == c.blue()


def test_monochrome_glass_is_translucent_and_neutral(view):
    _win, vp, folder = view
    img = _saved(vp, folder, "Monochrome")
    solid = _at(vp, img, "solid")
    glass = _at(vp, img, "glass")
    double = _at(vp, img, "double")
    assert solid.getRgb()[:3] == (255, 255, 255)
    assert _at(vp, img, "background").getRgb()[:3] == (255, 255, 255)
    assert _grey(glass) and glass.red() == pytest.approx(217, abs=2)
    assert _grey(double) and double.red() < glass.red()
    for zone in ("glass_on_solid", "tex_on_solid"):
        over = _at(vp, img, zone)
        assert _grey(over) and over.red() == pytest.approx(217, abs=2), zone


def test_a_textured_pane_lets_the_model_through_in_monochrome(view):
    """Its edges behind it read through: the solid's lower edge, a dark line
    across the pane, is what a white wall hid."""
    _win, vp, folder = view
    img = _saved(vp, folder, "Monochrome")
    x, y0 = vp._world_to_pixel(V(4, 0, 0))
    scale = WIDTH / vp.width()
    tones = [img.pixelColor(int(x * scale), int(y0 * scale) + d).red()
             for d in range(-3, 4)]
    assert min(tones) < 190, tones


def test_monochrome_glass_on_a_transparent_background(view):
    _win, vp, folder = view
    img = _saved(vp, folder, "Monochrome", transparent=True)
    glass = _at(vp, img, "glass")
    assert glass.alpha() == pytest.approx(76, abs=2)
    assert _grey(glass) and glass.red() == pytest.approx(127, abs=2)


def test_the_glass_of_another_mode_keeps_its_colour(view):
    _win, vp, folder = view
    glass = _at(vp, _saved(vp, folder, "Shaded"), "glass")
    assert glass.blue() > glass.red() + 15


def test_hidden_line_leaves_the_glass_as_it_was(view):
    """Not asked for: the plan style still ignores the colour runs."""
    _win, vp, folder = view
    assert _at(vp, _saved(vp, folder, "Hidden line"),
               "glass").getRgb()[:3] == (255, 255, 255)


def test_one_constant_gives_the_real_colour_back(view, monkeypatch):
    """The open decision (grey or the real colour) is this one value."""
    import views.viewport as viewport
    monkeypatch.setattr(viewport, "MONOCHROME_GLASS_RGB", None)
    _win, vp, folder = view
    img = _saved(vp, folder, "Monochrome")
    glass = _at(vp, img, "glass")
    assert glass.blue() > glass.red() + 15
    tex = _at(vp, img, "tex_on_solid")
    assert tex.blue() > tex.red() + 15


def test_a_pane_seen_from_behind_is_the_same_grey(view):
    """Glass reads the same from both sides, not in the back tint."""
    _win, vp, folder = view
    vp.camera.yaw = 1.5707963
    img = _saved(vp, folder, "Monochrome")
    x, y = vp._world_to_pixel(ZONES["glass"])
    scale = WIDTH / vp.width()
    c = img.pixelColor(int(x * scale), int(y * scale))
    assert _grey(c) and c.red() == pytest.approx(217, abs=2)
