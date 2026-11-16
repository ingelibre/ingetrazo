# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The picture of the model saved inside the ``.igz`` (``thumbnail.png``).

The file manager shows it in place of the document icon, and lists of
documents can read it without opening the model (``formats.igz.read_thumbnail``).

- **What it shows**: the model's FIRST scene, as the scene shows it — its
  camera, style, layers, section, shadows and hidden objects — so the
  picture stays the same whatever view the model was saved from. A model
  without scenes shows the view as it stands.
- **How**: one render of the live viewport into an offscreen framebuffer
  (``Viewport.render_image``), square, without dimensions, texts, guides or
  the drawing axes:
  the middle of the view, as tall as it is. The view on screen is put back
  exactly as it was and does not flicker.
- **Never in the way**: anything that goes wrong gives no picture, and the
  document is saved without one (``save_scene`` takes ``None``).

Preferences ▸ General ▸ «Save a picture of the model in the document»
turns it off (``save_thumbnail``): a model without textures then stays a
plain-text (JSON) document.
"""
from __future__ import annotations

import logging
import time

#: Side of the picture, in pixels. The file manager asks for up to 256 at
#: «Extra large icons»; 512 stays sharp on a scaled-up screen.
SIZE = 512
#: The setting that turns the picture off.
SETTING = "save_thumbnail"

_log = logging.getLogger("ingetrazo.thumbnail")
#: Seconds the last picture took (the test and the measurements read it).
last_seconds = [0.0]


def enabled(settings=None) -> bool:
    from core import general_settings as _gs
    return str(_gs.value(SETTING, "1", settings)) != "0"


def first_scene(scene):
    """The scene the picture shows, or ``None`` (a model without scenes)."""
    views = getattr(scene, "saved_views", None) or ()
    return views[0] if views else None


def _opaque(image):
    """``image`` as plain opaque RGB. The framebuffer comes back labelled
    premultiplied while glass leaves alpha below 1 under bright texels; the
    render already composed its background, so it is read as opaque."""
    from PySide6.QtGui import QImage
    if image.hasAlphaChannel():
        image = image.copy()
        straight = {
            QImage.Format_ARGB32_Premultiplied: QImage.Format_ARGB32,
            QImage.Format_RGBA8888_Premultiplied: QImage.Format_RGBA8888,
        }.get(image.format())
        if straight is not None:
            image.reinterpretAsFormat(straight)
    return image.convertToFormat(QImage.Format_RGB32)


def png_bytes(image) -> bytes | None:
    """``image`` encoded as PNG, or ``None``."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buf = QBuffer(data)
    if not buf.open(QIODevice.WriteOnly):
        return None
    ok = image.save(buf, "PNG")
    buf.close()
    return bytes(data.data()) if ok and data.size() else None


def _render(vp, size: int):
    """The live viewport's render at ``size`` × ``size``, the camera made
    square for it and given back its aspect after. Without the drawing
    axes, as an exported view without them: the picture is the model."""
    cam = vp.camera
    scene = vp.scene
    keep_aspect = cam.aspect
    keep_axes = getattr(scene, "show_axes", None)
    try:
        cam.aspect = 1.0
        if keep_axes is not None:
            scene.show_axes = False
        return vp.render_image(size, size, overlays=False)
    finally:
        cam.aspect = keep_aspect
        if keep_axes is not None:
            scene.show_axes = keep_axes


#: What a scene shows besides its camera (``SavedView.to_dict`` keys).
_STATE_KEYS = ("hidden_layers", "style", "section", "georef", "shadows",
               "hidden_objects", "hidden_shown")


def _state(view) -> dict:
    d = view.to_dict()
    return {k: d.get(k) for k in _STATE_KEYS}


def _render_scene(vp, view, size: int):
    """``view`` (a saved scene) rendered whole, and the model and the
    camera put back exactly as they were."""
    from core.saved_views import SavedView
    scene = vp.scene
    cam = vp.camera
    before = SavedView.capture("", scene, cam)
    keep_style = getattr(scene, "display_style", None)
    keep_up = cam.up
    shown = False
    try:
        scene._bounds_cache = None
        view.apply(scene, cam)
        # Other layers, objects or style than the view's: the caches keyed
        # on the version must see it — a view-only bump, so the document
        # does not come back «modified» from a save. The same scene as the
        # view (the usual case right after recalling it) costs nothing.
        shown = _state(SavedView.capture("", scene, cam)) != _state(before)
        if shown:
            scene.bump_view()
        return _render(vp, size)
    finally:
        before.apply(scene, cam)
        # The same style OBJECT the view had, not an equal copy of it.
        if hasattr(scene, "display_style"):
            scene.display_style = keep_style
        cam.up = keep_up
        scene._bounds_cache = None
        if shown:
            scene.bump_view()
        vp.update()


def render(vp, size: int = SIZE):
    """The picture of the model the viewport ``vp`` holds, as a ``QImage``
    (``size`` × ``size``), or ``None``. The first scene when there is
    one — the view as it stands if that scene cannot be drawn — else the
    view."""
    start = time.perf_counter()
    image = None
    try:
        view = first_scene(vp.scene)
        if view is not None:
            try:
                image = _render_scene(vp, view, size)
            except Exception:  # noqa: BLE001 — the view's picture instead
                _log.warning("The first scene could not be drawn for the "
                             "document picture.", exc_info=True)
                image = None
        if image is None or image.isNull():
            image = _render(vp, size)
        if image is None or image.isNull():
            return None
        return _opaque(image)
    finally:
        last_seconds[0] = time.perf_counter() - start
        _log.debug("Document picture: %.0f ms", last_seconds[0] * 1000)


def for_save(vp, size: int = SIZE, settings=None) -> bytes | None:
    """The PNG to store in the document being saved, or ``None`` — when
    Preferences turn it off, or when anything at all goes wrong (the
    document is saved without a picture)."""
    try:
        if not enabled(settings):
            return None
        image = render(vp, size)
        return png_bytes(image) if image is not None else None
    except Exception:  # noqa: BLE001 — a missing picture only
        _log.warning("No picture for the document.", exc_info=True)
        return None
