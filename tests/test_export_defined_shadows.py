# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Export image ▸ Defined shadows (PNG only): the sun's shadows drawn from
the model's projected polygons instead of the shadow map, so their edges
follow the geometry and not the map's pixels (José Castro Basso)."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtGui import QImage, QVector3D
from PySide6.QtWidgets import QApplication, QDialog

_app = QApplication.instance() or QApplication([])
V = QVector3D
WIDTH = 640


# ---- The dialog -------------------------------------------------------------

def test_the_box_is_offered_for_a_png_and_starts_off():
    from views.export_image_dialog import ExportImageDialog
    dlg = ExportImageDialog(None, ".png")
    try:
        box = dlg.defined_shadows_box
        assert box.isEnabled() and not box.isChecked()
        assert dlg.defined_shadows() is False
        box.setChecked(True)
        assert dlg.defined_shadows() is True
    finally:
        dlg.deleteLater()


@pytest.mark.parametrize("suffix", [".jpg", ".jpeg", ".JPG"])
def test_a_jpeg_does_not_offer_it(suffix):
    from views.export_image_dialog import ExportImageDialog
    dlg = ExportImageDialog(None, suffix)
    try:
        box = dlg.defined_shadows_box
        assert not box.isEnabled()
        assert "PNG" in box.toolTip()
        box.setChecked(True)               # by no hand: it is disabled
        assert dlg.defined_shadows() is False
    finally:
        dlg.deleteLater()


def test_the_new_texts_are_translated():
    from core import i18n
    for path in sorted(i18n._I18N_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "Transparent background" not in data:
            continue
        assert data.get("Defined shadows"), path.stem
        assert "PNG" in data.get(
            "Defined shadows are available for PNG images.", ""), path.stem
    es = json.loads((i18n._I18N_DIR / "es.json").read_text(encoding="utf-8"))
    assert es["Defined shadows"] == "Sombras definidas"


# ---- The picture ------------------------------------------------------------

def _box(mesh, x0, x1, y0, y1, z0, z1):
    c = [V(x0, y0, z0), V(x1, y0, z0), V(x1, y1, z0), V(x0, y1, z0),
         V(x0, y0, z1), V(x1, y0, z1), V(x1, y1, z1), V(x0, y1, z1)]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
              (2, 3, 7, 6), (3, 0, 4, 7)):
        mesh.add_face([c[i] for i in q])


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
    _box(vp.scene.mesh, -1, 1, -1, 1, 0, 3)
    vp.scene.version += 1
    vp.scene.shadows.enabled = True
    cam = vp.camera
    cam.perspective = False
    cam.target = V(0, 0, 1.0)
    cam.distance, cam.yaw, cam.pitch = 18.0, -1.2, 0.6
    yield win, vp, tmp_path
    vp.scene.shadows.enabled = False
    win._saved_version = vp.scene.version
    win.close()


def _rgb(img):
    img = img.convertToFormat(QImage.Format_ARGB32)
    buf = np.frombuffer(img.constBits(), np.uint8).reshape(
        img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return buf.reshape(img.height(), img.width(), 4)[..., :3].astype(float)


def test_the_box_changes_how_the_shadows_are_drawn(view, monkeypatch):
    from views import viewport as vp_mod
    _win, vp, _folder = view
    calls = []
    real = vp_mod._build_hard_shadow_image

    def spy(*a, **k):
        calls.append(a[2:4])
        return real(*a, **k)

    monkeypatch.setattr(vp_mod, "_build_hard_shadow_image", spy)
    plain = vp.render_image(WIDTH, sharp_shadows=True)
    assert not calls                           # the box off: the map
    defined = vp.render_image(WIDTH, sharp_shadows=True,
                              defined_shadows=True)
    assert calls and calls[-1] == (defined.width(), defined.height())
    assert plain.size() == defined.size()
    diff = np.abs(_rgb(plain) - _rgb(defined)).max(axis=2)
    assert (diff > 8).sum() > 50, "the defined shadows must show"
    # Only for that picture: the next one is drawn as before.
    again = vp.render_image(WIDTH, sharp_shadows=True)
    assert np.abs(_rgb(again) - _rgb(plain)).max() <= 2
    assert getattr(vp, "_export_defined_shadows", False) is False


def test_the_defined_shadows_darken_the_ground_by_the_box(view):
    """With the shadow map off for that picture, the darkness comes from
    the polygons: there is shadow, and the background stays clear."""
    _win, vp, _folder = view
    img = _rgb(vp.render_image(WIDTH, sharp_shadows=True,
                               defined_shadows=True))
    light = img.mean(axis=2)
    assert (light < light.max() - 60).sum() > 100


def test_export_image_hands_the_box_to_the_render(view, monkeypatch):
    from views import export_image_dialog as eid
    from views.filedialogs import file_dialogs
    win, vp, folder = view
    seen = {}
    real = vp.render_image

    def render_image(*a, **k):
        seen.update(k)
        return real(*a, **k)

    def answer(self):
        self.width_box.setValue(WIDTH)
        self.defined_shadows_box.setChecked(True)
        return QDialog.Accepted

    monkeypatch.setattr(vp, "render_image", render_image)
    monkeypatch.setattr(win, "_active_view", lambda: vp)
    monkeypatch.setattr(eid.ExportImageDialog, "exec", answer)
    monkeypatch.setattr(file_dialogs, "getSaveFileName",
                        lambda *a, **k: (str(folder / "a.png"), ""))
    win._on_export_image()
    assert seen.get("defined_shadows") is True
    assert (folder / "a.png").exists()
