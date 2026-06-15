"""Image textures, mapped the SketchUp way for interchange compatibility.

A SketchUp material is a colour plus an optional texture image with a
**real-world tile size** (the model-unit width/height one repeat of the image
covers). The default mapping is a **planar projection**: a face's UVs come from
its world position projected onto the face plane, divided by the tile size. The
projection basis depends only on the face normal, so coplanar faces share it and
the texture tiles **seamlessly** across a flat surface — exactly SketchUp's
behaviour, and what makes an exported ``.obj``/``.mtl`` line up the same way in
SketchUp or Blender.

A textured face carries ``attrs["texture"] = {"path", "sw", "sh"}``. Colour and
texture are independent (a face can have either or both).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QVector3D

from core.triangulate import plane_axes


@dataclass
class Texture:
    path: str          # image file
    sw: float = 1.0    # real-world width of one tile (metres)
    sh: float = 1.0    # real-world height of one tile (metres)

    def as_dict(self) -> dict:
        return {"path": self.path, "sw": self.sw, "sh": self.sh}

    @staticmethod
    def from_dict(d: dict) -> "Texture":
        return Texture(d["path"], float(d.get("sw", 1.0)), float(d.get("sh", 1.0)))


def planar_uv(normal: QVector3D, positions, sw: float, sh: float):
    """SketchUp-style planar-projected ``(u, v)`` for each world ``positions``
    point: project onto the plane basis derived from ``normal`` (so coplanar
    faces tile seamlessly), scaled by the tile size. ``sw``/``sh`` ≤ 0 fall back
    to 1 to avoid a divide-by-zero."""
    u_axis, v_axis = plane_axes(normal.normalized())
    sw = sw if abs(sw) > 1e-9 else 1.0
    sh = sh if abs(sh) > 1e-9 else 1.0
    return [(QVector3D.dotProduct(p, u_axis) / sw,
             QVector3D.dotProduct(p, v_axis) / sh) for p in positions]


def face_uvs(face, tex: dict):
    """Planar UVs for ``face``'s outer-loop vertices from a texture attrs dict."""
    return planar_uv(face.normal(), list(face.vertices),
                     float(tex.get("sw", 1.0)), float(tex.get("sh", 1.0)))
