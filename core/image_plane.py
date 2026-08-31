# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Imported reference images (SketchUp's ``File ▸ Import ▸ image``).

An image plane is a textured rectangle you trace over: a scanned floor plan, a
survey sketch, a facade photo. It is **reference, never geometry** — invariant
#4 of the project: display-only entities never enter the topology engine, so an
image is not a face, is never welded, healed, pushed or exported as a mesh. It
lives in ``Scene.image_planes`` beside guides and survey points.

Geometry is stored as a corner plus two edge vectors, so the same three fields
carry position, size *and* orientation on any plane:

    origin ───u───▶ (origin+u)
      │
      v
      ▼
    (origin+v)      (origin+u+v)

``u`` runs along the image's width and ``v`` along its height; the length of
each **is** the real-world size in metres, so scaling is just re-deriving the
two vectors. ``aspect`` (pixel height / pixel width) lets the placement tool
keep the picture undistorted while the user drags.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

# Imported images land here rather than on the default layer, for the same
# reason surveys do (``layers.SURVEY_LAYER``): you import a plan *to draw on
# top of it*, and you need to switch it off to look at what you drew — which
# would take the drawing with it if they shared a layer. A stored name, not a
# translated one: layer names are document data.
IMAGE_LAYER = "Images"


class ImagePlane:
    """A rectangular reference image placed in the model."""

    __slots__ = ("path", "origin", "u", "v", "aspect", "name",
                 "opacity", "layer", "locked")

    def __init__(self, path: str, origin: QVector3D, u: QVector3D,
                 v: QVector3D, aspect: float = 1.0, name: str = "",
                 opacity: float = 1.0, layer: str | None = IMAGE_LAYER,
                 locked: bool = False) -> None:
        self.path = str(path)
        self.origin = QVector3D(origin)
        self.u = QVector3D(u)
        self.v = QVector3D(v)
        self.aspect = float(aspect) if aspect > 0 else 1.0
        self.name = name or ""
        self.opacity = float(opacity)
        self.layer = layer
        self.locked = bool(locked)

    # ---- Geometry -----------------------------------------------------------
    def corners(self) -> list[QVector3D]:
        """The four corners, counter-clockwise seen from the front face:
        origin, +u, +u+v, +v. Render, pick and snap all read this."""
        o, u, v = self.origin, self.u, self.v
        return [QVector3D(o), o + u, o + u + v, o + v]

    def center(self) -> QVector3D:
        return self.origin + (self.u + self.v) * 0.5

    def width(self) -> float:
        """Real-world width in metres (the length of ``u``)."""
        return self.u.length()

    def height(self) -> float:
        """Real-world height in metres (the length of ``v``)."""
        return self.v.length()

    def normal(self) -> QVector3D:
        n = QVector3D.crossProduct(self.u, self.v)
        return n.normalized() if n.length() > 1e-12 else QVector3D(0.0, 0.0, 1.0)

    def plane(self) -> tuple[QVector3D, QVector3D]:
        """``(point, normal)`` — what the viewport feeds the work-plane
        inference so drawing tools land *on* the image instead of the ground."""
        return self.center(), self.normal()

    def border_edges(self):
        """The four border segments as ``(a, b)`` pairs. The snap engine takes
        these as pseudo-edges so tracing locks onto the image's corners and
        sides, which is how you align it against real geometry."""
        c = self.corners()
        return [(c[i], c[(i + 1) % 4]) for i in range(4)]

    def contains_uv(self, u_frac: float, v_frac: float) -> bool:
        return -1e-9 <= u_frac <= 1.0 + 1e-9 and -1e-9 <= v_frac <= 1.0 + 1e-9

    def project(self, point: QVector3D) -> tuple[float, float]:
        """``point`` expressed as ``(u, v)`` fractions of the rectangle.
        ``(0,0)`` is ``origin`` and ``(1,1)`` the opposite corner."""
        d = point - self.origin
        lu = self.u.lengthSquared()
        lv = self.v.lengthSquared()
        return (QVector3D.dotProduct(d, self.u) / lu if lu > 1e-18 else 0.0,
                QVector3D.dotProduct(d, self.v) / lv if lv > 1e-18 else 0.0)

    # ---- Scaling ------------------------------------------------------------
    def scaled(self, width: float, keep_aspect: bool = True) -> tuple[QVector3D, QVector3D]:
        """The ``(u, v)`` a rescale to ``width`` metres would produce, anchored
        at ``origin`` and keeping the picture's proportions by default.
        Returns the vectors instead of mutating so the caller can wrap it in a
        Command (every mutation is undoable)."""
        w = self.width()
        if w <= 1e-12 or width <= 0.0:
            return QVector3D(self.u), QVector3D(self.v)
        u = self.u * (width / w)
        if not keep_aspect:
            return u, QVector3D(self.v)
        h = self.height()
        if h <= 1e-12:
            return u, QVector3D(self.v)
        return u, self.v * ((width * self.aspect) / h)

    # ---- Serialisation ------------------------------------------------------
    def to_dict(self) -> dict:
        # The file goes under a ``"texture"`` sub-dict on purpose: ``igz``'s
        # packer walks the payload for exactly that key, so the picture is
        # embedded in (and restored from) the document for free — a saved
        # model carries its own scans instead of pointing at paths that break
        # the moment the file is opened on another machine.
        entry = {
            "texture": {"path": self.path},
            "origin": [self.origin.x(), self.origin.y(), self.origin.z()],
            "u": [self.u.x(), self.u.y(), self.u.z()],
            "v": [self.v.x(), self.v.y(), self.v.z()],
            "aspect": self.aspect,
        }
        if self.name:
            entry["name"] = self.name
        if self.opacity != 1.0:
            entry["opacity"] = self.opacity
        if self.layer and self.layer != IMAGE_LAYER:
            entry["layer"] = self.layer
        elif self.layer is None:
            entry["layer"] = None
        if self.locked:
            entry["locked"] = True
        return entry

    @classmethod
    def from_dict(cls, raw: dict) -> "ImagePlane":
        tex = raw.get("texture")
        path = (tex.get("path", "") if isinstance(tex, dict)
                else raw.get("path", ""))
        return cls(
            path,
            QVector3D(*raw["origin"]),
            QVector3D(*raw["u"]),
            QVector3D(*raw["v"]),
            aspect=float(raw.get("aspect", 1.0)),
            name=raw.get("name", ""),
            opacity=float(raw.get("opacity", 1.0)),
            layer=raw.get("layer", IMAGE_LAYER),
            locked=bool(raw.get("locked", False)),
        )


def image_aspect(path) -> tuple[float, int, int]:
    """``(aspect, pixel_width, pixel_height)`` of an image file, where aspect is
    height/width. Reads the header only — no full decode — and lifts
    ``QImageReader``'s 256 MB allocation cap, which otherwise rejects large
    scans with a misleading "out of memory" (the same trap ``georef/photomesh``
    documents). Returns ``(1.0, 0, 0)`` when the file is unreadable."""
    from PySide6.QtGui import QImageReader

    previous = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(0)          # 0 = no limit
    try:
        reader = QImageReader(str(path))
        size = reader.size()
    finally:
        QImageReader.setAllocationLimit(previous)
    w, h = size.width(), size.height()
    if w <= 0 or h <= 0:
        return 1.0, 0, 0
    return h / w, w, h
