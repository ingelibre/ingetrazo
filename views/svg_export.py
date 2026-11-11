# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Builds the SVG of a view for the export and for the dialog's preview.

One builder per export: it keeps what it has worked out — the lines, the
faces for each set of face options, the picture of the view — so turning
the dialog's choices or the paper size redraws the preview at once, and
the export that follows reuses what the preview already computed."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager

from formats.svg_out import svg_text

#: The picture of the view, in pixels across: the preview's and the file's.
PREVIEW_IMAGE_PX = 900
EXPORT_IMAGE_PX = 3200

#: How finely a textured face is drawn in the preview, pixels per paper mm.
PREVIEW_BAKE_PX_PER_MM = 3.0

#: The colour hair round each face in the preview, in paper mm: drawn
#: small, neighbouring faces show light seams under the standard one.
PREVIEW_SEAM_MM = 0.6


@contextmanager
def selection_only(scene):
    """While inside, only what is selected is visible to the exports that
    ask ``scene.entity_visible`` — the hidden-line pass and the faces:
    the selected objects, loose faces and edges (an edge also when a face
    of its is), as if the rest were hidden. Nothing in the model changes;
    the old answer is back on the way out."""
    chosen = {id(e) for e in scene.selection}

    def picked(entity):
        if id(entity) in chosen:
            return True
        return any(id(f) in chosen for f in getattr(entity, "faces", ()))

    shown = scene.entity_visible
    scene.entity_visible = lambda e: picked(e) and shown(e)
    try:
        yield
    finally:
        del scene.entity_visible


@contextmanager
def pictured_alone(scene):
    """While inside, the selection is all the view draws: every other
    object hidden (the selected ones and the groups holding them stay, and
    whatever they hold), and the loose faces and edges that are not
    selected — so the picture of the view is of the selection alone, as
    :func:`selection_only` makes the lines and the faces. Each flag is
    back as it was on the way out; nothing goes into the undo history."""
    from core.history import _dirty_group_chunks, _is_hidden, _set_hidden
    chosen = {id(e) for e in scene.selection}
    holding: set = set()

    def holds(g) -> bool:
        inner = [holds(c) for c in getattr(g, "children", None) or ()]
        if id(g) in chosen or any(inner):
            holding.add(id(g))
            return True
        return False

    for g in scene.groups:
        holds(g)
    out: list = []

    def hide(groups):
        for g in groups:
            if id(g) in chosen:
                continue                     # all of it stays
            if id(g) in holding:
                hide(getattr(g, "children", None) or ())
            elif not _is_hidden(g):
                out.append(g)

    hide(scene.groups)
    kept_faces = {id(f) for f in scene.faces if id(f) in chosen}
    for f in scene.faces:
        if id(f) not in chosen and not _is_hidden(f):
            out.append(f)
    for e in scene.edges:
        if (id(e) not in chosen and not _is_hidden(e)
                and not any(id(f) in kept_faces
                            for f in getattr(e, "faces", ()))):
            out.append(e)
    for e in out:
        _set_hidden(e, True)
    _dirty_group_chunks(scene)
    scene.version += 1
    try:
        yield
    finally:
        for e in out:
            _set_hidden(e, False)
        _dirty_group_chunks(scene)
        scene.version += 1


@contextmanager
def widened(camera, aspect: float):
    """While inside, ``camera`` sees as it would in a window ``aspect``
    wide over high — what lay past the screen's edges comes in, nothing it
    showed goes out: a wider window keeps the height and grows sideways, a
    taller one keeps the width and grows up and down (a parallel camera
    by drawing back, a perspective one by opening its field). The camera
    is as it was on the way out."""
    import math
    keep = (camera.aspect, camera.distance, camera.fov_deg)
    old = float(camera.aspect) or 1.0
    try:
        if aspect < old:
            grow = old / aspect
            if camera.perspective:
                half = math.radians(camera.fov_deg) / 2.0
                camera.fov_deg = math.degrees(
                    2.0 * math.atan(math.tan(half) * grow))
            else:
                camera.distance = camera.distance * grow
        camera.aspect = aspect
        yield
    finally:
        camera.aspect, camera.distance, camera.fov_deg = keep


@contextmanager
def fitted(camera, bounds):
    """While inside, ``camera`` frames the box ``bounds`` — ``(lo, hi)``,
    the whole model or the selection — as Zoom Extents does, looking the
    way it looks now; the camera is as it was on the way out. ``(None,
    None)`` leaves it alone."""
    from PySide6.QtGui import QVector3D
    keep = (QVector3D(camera.target), camera.distance, camera.fov_deg)
    try:
        lo, hi = bounds
        if lo is not None and hi is not None:
            camera.fit_box(lo, hi, 1.02)
        yield
    finally:
        camera.target, camera.distance, camera.fov_deg = keep


#: The framing that leaves the view as it is: no pan, no zoom.
NO_FRAME = (0.0, 0.0, 1.0)


@contextmanager
def framed(camera, frame):
    """While inside, ``camera`` is moved and zoomed by ``frame`` —
    ``(pan_x, pan_y, zoom)``: the pan in widths and heights of what the
    window shows (right and up), the zoom a factor (2: twice as close) —
    the export's own framing, set in the dialog's preview. It moves the
    point it looks at across the view and draws in (a parallel camera) or
    narrows its field (a perspective one); the camera is as it was on the
    way out."""
    import math

    from PySide6.QtGui import QVector3D

    from core.hlr import camera_basis
    from core.vista_caras import view_rect
    pan_x, pan_y, zoom = frame
    keep = (QVector3D(camera.target), camera.distance, camera.fov_deg)
    try:
        x0, y0, x1, y1 = view_rect(camera)
        _eye, right, up, _fwd = camera_basis(camera)
        shift = right * (pan_x * (x1 - x0)) + up * (pan_y * (y1 - y0))
        camera.target = camera.target + QVector3D(*map(float, shift))
        zoom = max(float(zoom), 1e-3)
        if abs(zoom - 1.0) > 1e-9:
            if camera.perspective:
                half = math.radians(camera.fov_deg) / 2.0
                camera.fov_deg = math.degrees(
                    2.0 * math.atan(math.tan(half) / zoom))
            else:
                camera.distance = camera.distance / zoom
        yield
    finally:
        camera.target, camera.distance, camera.fov_deg = keep


class SvgBuilder:
    """``lines()`` → the line groups; ``faces(**options)`` → the faces
    (:func:`core.vista_caras.view_faces`); ``image(width_px, axes[,
    aspect])`` → ``(QImage, window rect)`` or ``None``. ``scale_n`` and
    ``pens`` as :func:`formats.svg_out.svg_text` takes them. ``window()``
    → what the screen (or the composer's frame) shows, in the drawing's
    plane, and ``screen_mm`` its size on paper: the «screen size» sheet.

    ``isolate()`` → a context in which only the selection is visible (the
    «Selection» part); ``widen(aspect)`` → a context in which the view is
    as it would be in a window of that width over height — what lies past
    the screen's edges comes into it, as when the window is resized. With
    them, everything is worked out inside; without, «Selection» is the
    whole model and a sheet of another shape widens the window in the
    drawing's plane alone. ``frame(framing)`` → a context with the view
    moved and zoomed by the dialog's framing (:func:`framed`); without
    it, what the screen shows cannot be reframed. ``fit(selection)`` → a
    context with the camera framing all of the model (or the selection,
    :func:`fitted`): the «Whole model» and «Selection» parts; without it,
    they are what the camera sees now."""

    def __init__(self, lines, faces, image=None, scale_n: float = 100.0,
                 pens: dict | None = None, window=None,
                 screen_mm=None, isolate=None, widen=None,
                 frame=None, fit=None, isolate_picture=None) -> None:
        self._lines_fn = lines
        self._faces_fn = faces
        self._image_fn = image
        self.scale_n = scale_n
        self.pens = pens
        self._window_fn = window
        self._isolate = isolate
        self._widen = widen
        self._frame = frame
        self._fit = fit
        self._isolate_picture = isolate_picture
        self.screen_mm = screen_mm
        self._cache: dict = {}

    # ---- what is worked out, once per (what, selection, shape, frame) -----
    def _once(self, key, work, selection=False, aspect=None, frame=None,
              whole=False):
        whole = whole and self._fit is not None
        key = key + (whole,)
        if key not in self._cache:
            with ExitStack() as stack:
                if selection:
                    stack.enter_context(self._isolate())
                if whole:
                    stack.enter_context(self._fit(selection))
                if aspect is not None:
                    stack.enter_context(self._widen(aspect))
                if frame is not None:
                    stack.enter_context(self._frame(frame))
                self._cache[key] = work()
        return self._cache[key]

    def window(self, aspect=None, frame=None):
        if self._window_fn is None:
            return None
        return self._once(("window", aspect, frame), self._window_fn,
                          aspect=aspect, frame=frame)

    def lines(self, selection: bool = False, aspect=None, frame=None,
              whole=False):
        if (selection or aspect is not None or frame is not None
                or (whole and self._fit is not None)):
            work = (lambda: self._lines_fn(fast=not selection))
        else:
            work = self._lines_fn
        return self._once(("lines", selection, aspect, frame), work,
                          selection, aspect, frame, whole)

    def faces(self, options: dict, selection: bool = False, aspect=None,
              frame=None, whole=False):
        key = ("faces", tuple(sorted(options.items())), selection, aspect,
               frame)
        return self._once(key, lambda: self._faces_fn(**options), selection,
                          aspect, frame, whole)

    def image(self, preview: bool, axes: bool = True, aspect=None,
              frame=None, whole=False, selection=False):
        """The picture of the view; ``axes`` off draws it without the
        axes; ``aspect``, in a window of that shape; ``frame``, moved and
        zoomed."""
        if self._image_fn is None:
            return None
        width = PREVIEW_IMAGE_PX if preview else EXPORT_IMAGE_PX
        if aspect is None:
            work = (lambda: self._image_fn(width, axes))
        else:
            work = (lambda: self._image_fn(width, axes, aspect))
        if selection and self._isolate_picture is not None:
            # The selection alone: the rest hidden for the picture.
            alone = work

            def work():
                with self._isolate_picture():
                    return alone()
        return self._once(("image", preview, axes, aspect, frame, selection),
                          work, selection, aspect=aspect, frame=frame,
                          whole=whole)

    def can_frame(self) -> bool:
        """Whether what the screen shows can be moved and zoomed here."""
        return self._frame is not None

    def _framing(self, sheet):
        """The dialog's framing of what the screen shows, or ``None`` when
        there is none to apply (the view as it is, another part, or no way
        to reframe here)."""
        if (self._frame is None or not isinstance(sheet, dict)
                or sheet.get("area") != "view"):
            return None
        frame = tuple(float(v) for v in (sheet.get("frame") or NO_FRAME))
        if all(abs(a - b) < 1e-9 for a, b in zip(frame, NO_FRAME)):
            return None
        return tuple(round(v, 6) for v in frame)

    # ---- the sheet ----------------------------------------------------------
    def _aspect(self, sheet) -> float | None:
        """The window's new shape when what the screen shows goes on a
        sheet of another shape — ``None`` when it keeps the screen's, or
        there is no way to widen the view here."""
        if (self._widen is None or not isinstance(sheet, dict)
                or sheet.get("area") != "view"):
            return None
        size = sheet.get("size")
        if not isinstance(size, tuple) or not self.screen_mm:
            return None
        want = float(size[0]) / max(float(size[1]), 1e-9)
        have = float(self.screen_mm[0]) / max(float(self.screen_mm[1]), 1e-9)
        if abs(want / have - 1.0) < 1e-3:
            return None
        return round(want, 4)

    def _sheet(self, sheet: dict, aspect=None, frame=None):
        """``(paper, window, margin)`` for :func:`svg_text` from the
        dialog's sheet: ``area`` — ``"view"`` (what the screen or the frame
        shows), ``"model"`` or ``"selection"`` — and ``size`` —
        ``"screen"`` (the screen's own size), ``None`` (at the drawing's
        scale) or ``(width_mm, height_mm)``.

        What the screen shows, on a sheet of another shape, is the view in
        a window of the sheet's shape (``aspect``); where the view cannot
        be widened, the window widens in the drawing's plane round its
        middle — either way the drawing fills the sheet edge to edge. The
        whole model and the selection keep the 10 mm margin."""
        size = sheet.get("size")
        window = (self.window(aspect, frame) if sheet.get("area") == "view"
                  else None)
        if size == "screen":
            size = self.screen_mm
        if window is None:
            return size, None, None
        if size is not None:
            x0, y0, x1, y1 = window
            w, h = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
            want = float(size[0]) / max(float(size[1]), 1e-9)
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            if want > w / h:
                w = h * want
            else:
                h = w / want
            window = (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
        return size, window, 0.0

    def build(self, options, paper=None, preview: bool = False):
        """``(svg text, line segments)`` for the dialog's ``options``
        (``None``: the lines alone; ``{"image": True}``: the picture of the
        view under them — ``"axes": False`` without the axes —; else the
        face options) on ``paper`` — the dialog's sheet (see
        :meth:`_sheet`), or as before ``(width_mm, height_mm)``, ``None``
        for the drawing at its scale, or ``"screen"``."""
        if paper == "screen":
            paper = {"area": "view", "size": "screen"}
        selection = (isinstance(paper, dict) and self._isolate is not None
                     and paper.get("area") == "selection")
        aspect = self._aspect(paper)
        frame = self._framing(paper)
        # The whole model or the selection: all of it, framed afresh — not
        # what the screen happens to show of it.
        whole = (isinstance(paper, dict)
                 and paper.get("area") in ("model", "selection"))
        faces = image = None
        if options and options.get("image"):
            image = self.image(preview, options.get("axes", True), aspect,
                               frame, whole, selection)
        elif options:
            faces = self.faces(options, selection, aspect, frame, whole)
        line_colours = not options or options.get("materials", True)
        window = margin = None
        if isinstance(paper, dict):
            paper, window, margin = self._sheet(paper, aspect, frame)
        return svg_text(self.lines(selection, aspect, frame, whole),
                        self.scale_n,
                        self.pens, faces, line_colours, image, paper,
                        bake_px_per_mm=(PREVIEW_BAKE_PX_PER_MM if preview
                                        else None),
                        window=window, margin=margin,
                        seam_mm=PREVIEW_SEAM_MM if preview else None)
