# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""File ▸ Export ▸ 360° Image: the view all around the camera's eye as one
equirectangular panorama (``core.panorama``), for panorama viewers, phones
and headsets.

The eye renders six square views at 90° — front, right, back, left, up
and down — with the style, the sun and the shadows of the view; the camera
is given back exactly as it was, locked or not. Annotations, guides and
watermarks stay out: drawn for a flat screen, they would be repeated and
bent around the sphere."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from core import panorama
from core.i18n import tr

JPEG = ".jpg"
PNG = ".png"
JPEG_QUALITY = 92

#: The camera fields a face sets; everything else of the pose comes from
#: the eye and the face's direction.
_FACE_LENS = {"perspective": True, "two_point": False, "shift_x": 0.0,
              "shift_y": 0.0, "pan_shift_x": 0.0, "pan_shift_y": 0.0,
              "roll_deg": 0.0, "eye_offset": 0.0, "zero_parallax": 0.0,
              "aspect": 1.0, "frame_aspect": None}


class PanoramaError(Exception):
    """The panorama could not be rendered or written; the message says why."""


def point_camera(camera, eye, direction, fov_deg: float) -> None:
    """Put ``camera`` at ``eye`` looking exactly along ``direction`` (a unit
    3-vector) with a square ``fov_deg`` view, straight up and down
    included — which ``look_from`` keeps 1° off — and no lens shift, roll
    or stereo offset."""
    from PySide6.QtGui import QVector3D
    for k, v in _FACE_LENS.items():
        setattr(camera, k, v)
    camera.fov_deg = float(fov_deg)
    camera.up = QVector3D(0.0, 0.0, 1.0)
    dx, dy, dz = (float(c) for c in direction)
    pitch = math.asin(max(-1.0, min(1.0, -dz)))
    if math.hypot(dx, dy) > 1e-9:
        camera.yaw = math.atan2(-dy, -dx)
    camera.pitch = pitch
    camera.target = QVector3D(eye) + QVector3D(dx, dy, dz) * camera.distance


def view_rotation(camera) -> np.ndarray:
    """The world-to-camera rotation of ``camera`` (rows right, up, back),
    read from the view matrix the picture is drawn with."""
    m = camera.view_matrix()
    rows = [m.row(i) for i in range(3)]
    return np.array([[r.x(), r.y(), r.z()] for r in rows], dtype=np.float64)


def image_array(image) -> np.ndarray:
    """A ``QImage`` as an ``(h, w, 4)`` RGBA uint8 array (a copy)."""
    from PySide6.QtGui import QImage
    img = image.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8,
                        count=img.bytesPerLine() * h)
    return buf.reshape(h, img.bytesPerLine())[:, :w * 4].reshape(
        h, w, 4).copy()


def array_image(arr: np.ndarray):
    """An ``(h, w, 3|4)`` uint8 array as a ``QImage`` (owning its pixels)."""
    from PySide6.QtGui import QImage
    arr = np.ascontiguousarray(arr)
    h, w, ch = arr.shape
    fmt = QImage.Format_RGBA8888 if ch == 4 else QImage.Format_RGB888
    return QImage(arr.data, w, h, w * ch, fmt).copy()


def render_faces(viewport, width: int):
    """The six faces for a panorama ``width`` wide, rendered from the eye
    of ``viewport``'s camera: ``(basis, side, [(rotation, rgba), ...])``.
    The camera, and whatever the viewport was told for these pictures,
    are put back whatever happens."""
    camera = viewport.camera
    side = panorama.face_size(panorama.panorama_size(width)[0])
    full, fov = panorama.face_render(side)
    eye = camera.eye()
    fwd = camera.forward()
    basis = panorama.heading_basis((fwd.x(), fwd.y()))
    if math.hypot(fwd.x(), fwd.y()) < 1e-6:
        # Straight down or up: the front is where the view's top points.
        up = camera.up_vector()
        basis = panorama.heading_basis((up.x(), up.y()) if fwd.z() < 0
                                       else (-up.x(), -up.y()))
    saved = dict(camera.__dict__)
    own = viewport.__dict__
    had_watermarks = "_draw_style_watermarks" in own
    faces = []
    try:
        camera.locked = False
        viewport._export_panorama = True
        if not had_watermarks:
            # Drawn on the screen's corners, they would come six times.
            viewport._draw_style_watermarks = lambda *a, **k: None
        for direction in panorama.face_directions(basis):
            point_camera(camera, eye, direction, fov)
            image = viewport.render_image(full, full, overlays=False,
                                          sharp_shadows=True)
            if image is None or image.isNull():
                raise PanoramaError(tr("Could not render the view."))
            faces.append((view_rotation(camera), image_array(image)))
    finally:
        camera.__dict__.clear()
        camera.__dict__.update(saved)
        own.pop("_export_panorama", None)
        if not had_watermarks:
            own.pop("_draw_style_watermarks", None)
        viewport.update()
    return basis, side, faces


def encode(pixels: np.ndarray, suffix: str) -> bytes:
    """The panorama as the bytes of a JPEG or PNG file carrying the mark
    panorama viewers read (``core.panorama.xmp_packet``)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    h, w = pixels.shape[:2]
    jpeg = suffix.lower() != PNG
    image = array_image(pixels[:, :, :3] if jpeg else pixels)
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    ok = image.save(buf, "JPG" if jpeg else "PNG",
                    JPEG_QUALITY if jpeg else -1)
    buf.close()
    if not ok:
        raise PanoramaError(tr("Could not render or save the image."))
    raw = bytes(data.data())
    xmp = panorama.xmp_packet(w, h)
    return (panorama.jpeg_with_xmp(raw, xmp) if jpeg
            else panorama.png_with_xmp(raw, xmp))


def export_panorama(viewport, path, width: int) -> tuple[int, int]:
    """Write the 360° panorama of ``viewport``'s eye to ``path`` (JPEG,
    or PNG by its suffix), ``width`` wide; returns its ``(width, height)``."""
    path = Path(path)
    width, height = panorama.panorama_size(width)
    basis, side, faces = render_faces(viewport, width)
    # Opaque faces: the sky fills every pixel, alpha is not wanted.
    pixels = panorama.equirectangular(faces, width, basis, side)
    pixels[:, :, 3] = 255
    path.write_bytes(encode(pixels, path.suffix))
    return width, height


class PanoramaOptionsDialog:
    """The quality of the panorama: 2K to 8K wide."""

    def __init__(self, parent) -> None:
        from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                                       QLabel, QVBoxLayout)
        self.dialog = dlg = QDialog(parent)
        dlg.setWindowTitle(tr("Export 360° Image"))
        self.quality_box = QComboBox(dlg)
        for w, name in panorama.QUALITIES:
            self.quality_box.addItem(
                tr("{name} — {w} × {h} px", name=name, w=w, h=w // 2), w)
        self.quality_box.setCurrentIndex(
            [w for w, _ in panorama.QUALITIES].index(panorama.DEFAULT_WIDTH))
        note = QLabel(tr(
            "Everything around the camera, as seen from where it stands. "
            "Open the picture in a 360° viewer to look around."))
        note.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel, parent=dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(tr("Quality:")))
        lay.addWidget(self.quality_box)
        lay.addWidget(note)
        lay.addWidget(buttons)

    def width(self) -> int:
        return int(self.quality_box.currentData())

    def exec(self) -> bool:
        return bool(self.dialog.exec())


def export_panorama_from_menu(window) -> None:
    """File ▸ Export ▸ 360° Image: pick the file, the quality, and write it."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from views.filedialogs import file_dialogs
    current = getattr(window, "_current_path", None)
    base = current.stem if current is not None else "untitled"
    path_str, _ = file_dialogs.getSaveFileName(
        window, tr("Export 360° Image"), f"{base}-360.jpg",
        tr("JPEG image (*.jpg);;PNG image (*.png)"))
    if not path_str:
        return
    path = Path(path_str)
    if path.suffix.lower() not in (JPEG, ".jpeg", PNG):
        path = path.with_suffix(JPEG)
    options = PanoramaOptionsDialog(window)
    accepted = options.exec()
    width = options.width()
    options.dialog.deleteLater()
    if not accepted:
        return
    viewport = window._active_view()
    window.statusBar().showMessage(tr("Exporting {name}…", name=path.name))
    window.statusBar().repaint()
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        w, h = export_panorama(viewport, path, width)
    except (PanoramaError, OSError, ValueError) as exc:
        QApplication.restoreOverrideCursor()
        window.statusBar().clearMessage()
        QMessageBox.critical(window, tr("Export 360° Image failed"), str(exc))
        return
    QApplication.restoreOverrideCursor()
    window.statusBar().showMessage(
        tr("Exported image {w}×{h} → {name}", w=w, h=h, name=path.name), 4000)
