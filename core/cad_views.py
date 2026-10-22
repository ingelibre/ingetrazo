# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""2D CAD views of the model — floor plans, elevations, sections.

A view here is what Revit calls a view with a view range: a parallel
camera, an optional cut plane, and how far beyond the cut the drawing
looks (the view depth). None of it is placed in the document — a plan
at 1.20 m is drawn without adding a section plane to the model — and the
line work is the exact hidden-line pass (``core.hlr``) with every line
knowing its object, so ``core.cad_layers`` can put it on ``A-WALL-CUT``,
``S-COLS-PROJ``, ``M-DUCT-HIDN``…

Plans and elevations come out in WORLD coordinates (a plan's x, y are the
model's X, Y; an elevation's x runs along the façade, y is Z), so views of
one model overlay in CAD. Headless (Qt only for vectors).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QVector3D

from core.camera import OrbitCamera
from core.hlr import collect_geometry, hlr_drawing
from core.section import SectionPlane

#: View types.
PLAN = "plan"
ELEVATION = "elevation"
SECTION = "section"

#: Elevations by the façade they show: the camera stands on that side
#: and looks across the model.
ELEVATION_LOOK = {
    "N": QVector3D(0.0, -1.0, 0.0),
    "S": QVector3D(0.0, 1.0, 0.0),
    "E": QVector3D(-1.0, 0.0, 0.0),
    "W": QVector3D(1.0, 0.0, 0.0),
}

#: How far the parallel eye stands off: well outside any model, so every
#: depth is positive (the hidden-line pass only compares them).
_EYE_DISTANCE = 1.0e4


@dataclass
class ViewSpec:
    """What to draw.

    - ``PLAN``: cut at ``level + cut_height``, looking down; the view
      depth reaches ``view_depth`` below the cut (default: 1.50 m, so a
      1.20 m cut sees the floor it stands on and 0.30 m under it).
    - ``ELEVATION``: the façade ``direction`` (N/S/E/W), no cut;
      ``view_depth`` > 0 limits how far into the model it looks, measured
      from the nearest point of the model.
    - ``SECTION``: the document's section plane ``section_uid``, looking at
      what it keeps; the view depth is measured from the plane.
    """
    kind: str = PLAN
    level: float = 0.0
    cut_height: float = 1.2
    view_depth: float = 1.5
    direction: str = "S"
    section_uid: int | None = None
    hidden: bool = False


def _camera_looking(look: QVector3D) -> OrbitCamera:
    cam = OrbitCamera()
    cam.perspective = False
    if abs(look.z()) > 0.9999:
        # straight down / up: the exact standard view (look_from keeps
        # a degree off the pole, which would tilt the drawing)
        cam.set_view("top" if look.z() < 0 else "bottom")
    else:
        cam.look_from(-look * _EYE_DISTANCE, look)
    cam.target = QVector3D(0.0, 0.0, 0.0)
    cam.distance = _EYE_DISTANCE
    return cam


def _model_bounds(tris):
    xs = [p[0] for t in tris for p in t]
    ys = [p[1] for t in tris for p in t]
    zs = [p[2] for t in tris for p in t]
    if not xs:
        return None
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def view_setup(scene, spec: ViewSpec, tris=None):
    """``(camera, section, far_plane)`` for ``spec``. Raises ValueError
    for a section view whose plane is not in the document."""
    if spec.kind == PLAN:
        cam = _camera_looking(QVector3D(0.0, 0.0, -1.0))
        z = spec.level + spec.cut_height
        section = SectionPlane(QVector3D(0, 0, z), QVector3D(0, 0, 1))
        far = None
        if spec.view_depth and spec.view_depth > 0:
            far = SectionPlane(QVector3D(0, 0, z - spec.view_depth),
                               QVector3D(0, 0, -1))
        return cam, section, far
    if spec.kind == ELEVATION:
        look = ELEVATION_LOOK.get(spec.direction.upper())
        if look is None:
            raise ValueError(f"unknown elevation {spec.direction!r}")
        cam = _camera_looking(look)
        far = None
        if spec.view_depth and spec.view_depth > 0 and tris:
            # from the façade (the model's nearest point along the look)
            lo, hi = _model_bounds(tris)
            corners = [QVector3D(x, y, z) for x in (lo[0], hi[0])
                       for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            near = min(QVector3D.dotProduct(c, look) for c in corners)
            far = SectionPlane(look * (near + spec.view_depth), look)
        return cam, None, far
    if spec.kind == SECTION:
        plane = next((p for p in getattr(scene, "section_planes", ())
                      if p.uid == spec.section_uid), None)
        if plane is None:
            raise ValueError(f"no section plane with uid {spec.section_uid}")
        # The plane hides its normal's side: stand there, look at the rest.
        look = -plane.normal
        cam = _camera_looking(look)
        section = SectionPlane(plane.point, plane.normal)
        far = None
        if spec.view_depth and spec.view_depth > 0:
            far = SectionPlane(plane.point + look * spec.view_depth, look)
        return cam, section, far
    raise ValueError(f"unknown view kind {spec.kind!r}")


def build_view(scene, spec: ViewSpec):
    """The view's line drawing and its owner table: ``(HlrDrawing,
    [core.hlr.Owner])``. The drawing has fills (the cut rings) and
    per-segment owners."""
    tris, hard, soft, (tri_o, hard_o, soft_o, table) = collect_geometry(
        scene, owners=True)
    cam, section, far = view_setup(scene, spec, tris)
    drawing = hlr_drawing(scene, cam, geometry=(tris, hard, soft),
                          section=section, far_plane=far,
                          hidden=spec.hidden,
                          owners=(tri_o, hard_o, soft_o))
    return drawing, table


def export_dxf(scene, spec: ViewSpec, path, disciplines=None,
               scale_n: float = 100.0, hatch: bool = True) -> dict:
    """Draw ``spec`` and write it to ``path`` as a layered DXF. Returns
    ``{"lines": n, "layers": [names]}``."""
    from core.cad_layers import split_drawing
    from formats.dxf_cad import save_cad_dxf

    drawing, table = build_view(scene, spec)
    layers = split_drawing(drawing, table, disciplines)
    n = save_cad_dxf(path, layers, scale_n=scale_n, hatch=hatch)
    return {"lines": n, "layers": list(layers)}
