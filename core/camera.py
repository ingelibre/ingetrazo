"""Orbital camera for the 3D viewport.

Z-up convention (SketchUp, Blender, FreeCAD): X red (east), Y green (north),
Z blue (up). The camera orbits around a ``target`` point in spherical
coordinates (``yaw``, ``pitch``, ``distance``). Both perspective and parallel
("orthographic") projections are supported.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QMatrix4x4, QVector3D


class OrbitCamera:
    """Camera that orbits around a target point."""

    def __init__(self) -> None:
        self.target = QVector3D(0.0, 0.0, 0.0)
        self.distance = 20.0
        self.yaw = math.radians(-45.0)
        self.pitch = math.radians(30.0)
        self.up = QVector3D(0.0, 0.0, 1.0)
        self.fov_deg = 45.0
        self.aspect = 1.0
        self.znear = 0.1
        self.zfar = 10000.0
        self.perspective = True

    # ---- Derived state ------------------------------------------------------
    def eye(self) -> QVector3D:
        cp = math.cos(self.pitch)
        sp = math.sin(self.pitch)
        cy = math.cos(self.yaw)
        sy = math.sin(self.yaw)
        return self.target + QVector3D(
            self.distance * cp * cy,
            self.distance * cp * sy,
            self.distance * sp,
        )

    def view_matrix(self) -> QMatrix4x4:
        m = QMatrix4x4()
        m.lookAt(self.eye(), self.target, self.up)
        return m

    def projection_matrix(self) -> QMatrix4x4:
        m = QMatrix4x4()
        if self.perspective:
            m.perspective(self.fov_deg, self.aspect, self.znear, self.zfar)
        else:
            # Parallel projection — size derived from camera distance so the
            # framing matches what the user sees in perspective.
            half_h = self.distance * math.tan(math.radians(self.fov_deg) / 2.0)
            half_w = half_h * self.aspect
            m.ortho(-half_w, half_w, -half_h, half_h, -self.zfar, self.zfar)
        return m

    # ---- Navigation ---------------------------------------------------------
    def orbit(self, dx_pixels: float, dy_pixels: float, viewport_h: int) -> None:
        scale = math.pi / max(viewport_h, 1)
        self.yaw -= dx_pixels * scale
        # Clamp to just shy of poles to avoid the up-vector singularity.
        self.pitch = max(
            min(self.pitch - dy_pixels * scale, math.radians(89.0)),
            math.radians(-89.0),
        )

    def pan(self, dx_pixels: float, dy_pixels: float, viewport_h: int) -> None:
        cp = math.cos(self.pitch)
        sp = math.sin(self.pitch)
        cy = math.cos(self.yaw)
        sy = math.sin(self.yaw)
        forward = QVector3D(cp * cy, cp * sy, sp)
        right = QVector3D.crossProduct(forward, self.up).normalized()
        screen_up = QVector3D.crossProduct(right, forward).normalized()
        world_per_pixel = (
            2.0
            * self.distance
            * math.tan(math.radians(self.fov_deg) / 2.0)
            / max(viewport_h, 1)
        )
        self.target = self.target - right * (dx_pixels * world_per_pixel)
        self.target = self.target + screen_up * (dy_pixels * world_per_pixel)

    def zoom(self, steps: float) -> None:
        factor = 0.9 ** steps
        self.distance = max(0.5, min(self.distance * factor, 10000.0))

    def set_aspect(self, w: int, h: int) -> None:
        self.aspect = max(w, 1) / max(h, 1)

    def toggle_projection(self) -> None:
        self.perspective = not self.perspective

    # ---- Navigation presets ------------------------------------------------
    def fit_to(self, min_pt: QVector3D, max_pt: QVector3D, margin: float = 1.3) -> None:
        """Center the camera on the AABB and back up enough to frame it."""
        center = QVector3D(
            (min_pt.x() + max_pt.x()) * 0.5,
            (min_pt.y() + max_pt.y()) * 0.5,
            (min_pt.z() + max_pt.z()) * 0.5,
        )
        diag = (max_pt - min_pt).length()
        if diag < 1.0:
            diag = 1.0
        self.target = center
        fov_rad = math.radians(self.fov_deg)
        self.distance = max(diag * margin / (2.0 * math.tan(fov_rad / 2.0)), 1.0)

    # Yaw / pitch presets for standard architectural views (Z-up convention).
    _STANDARD_VIEWS = {
        "top":    (math.radians(-90.0), math.radians(89.0)),
        "bottom": (math.radians(-90.0), math.radians(-89.0)),
        "front":  (math.radians(-90.0), 0.0),
        "back":   (math.radians(90.0), 0.0),
        "right":  (0.0, 0.0),
        "left":   (math.radians(180.0), 0.0),
        "iso":    (math.radians(-45.0), math.radians(30.0)),
    }

    def set_view(self, name: str) -> None:
        preset = self._STANDARD_VIEWS.get(name)
        if preset is None:
            return
        self.yaw, self.pitch = preset
