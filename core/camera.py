# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Orbital camera for the 3D viewport.

Z-up convention (Blender, FreeCAD): X red (east), Y green (north),
Z blue (up). The camera orbits around a ``target`` point in spherical
coordinates (``yaw``, ``pitch``, ``distance``). Both perspective and parallel
("orthographic") projections are supported.
"""
from __future__ import annotations

import math

from PySide6.QtGui import QMatrix4x4, QVector3D


#: How close the camera may get to what it is looking at. A component is
#: centimetres, not metres: half a metre away is as close as you can stand
#: to a wall, and it left the face of a figure or the rim of a wheel
#: impossible to look at. Two centimetres is close enough for any of it.
MIN_DISTANCE = 0.02

#: Ceiling: past this the model is a dot and the depth buffer is noise.
MAX_DISTANCE = 10000.0


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
        #: Two-Point Perspective: vertical lines stay vertical
        #: (José Castro Basso, FADU–UDELAR, for teaching architectural
        #: drawing). Only in perspective; see ``_level_forward``.
        self.two_point = False

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

    def forward(self) -> QVector3D:
        """Unit view direction, eye → target."""
        d = self.target - self.eye()
        return d.normalized() if d.lengthSquared() > 1e-18 else QVector3D(0, 1, 0)

    def up_vector(self) -> QVector3D:
        """The up vector every projection must use: ``up`` itself, unless
        the sight line runs along it — the exact Top and Bottom views —
        where ``lookAt`` has no right and a cross product gives nothing.
        There it is the limit of the view a hair short of vertical: north
        up the screen in Top (y+ at the default yaw), the same axis the
        other way in Bottom, so the exact view looks like the 89° one it
        replaces, only straight. A rolled ``up`` (the composer turning a
        plan) is never along the sight line and comes back as it is."""
        f = self.forward()
        if abs(QVector3D.dotProduct(f, self.up)) < 0.9999:
            return self.up
        sign = -1.0 if self.pitch > 0 else 1.0
        return QVector3D(sign * math.cos(self.yaw), sign * math.sin(self.yaw),
                         0.0)

    # ---- First person (Position Camera / Look Around / Walk) ---------------
    # The orbit model stays: a walkthrough only ever asks "the eye is HERE,
    # looking THERE", and that is a target at ``distance`` along the look
    # direction. Nothing else in the viewport has to learn a second camera.

    def look_from(self, eye: QVector3D, direction: QVector3D) -> None:
        """Put the eye at ``eye`` looking along ``direction`` (any length).
        A near-vertical look keeps just off the pole, like ``orbit``."""
        d = QVector3D(direction)
        if d.lengthSquared() < 1e-18:
            d = self.forward()
        d = d.normalized()
        # eye = target + distance·(cp·cy, cp·sy, sp): the eye sits BEHIND
        # the target along -forward, so the spherical angles come from -d.
        pitch = math.asin(max(-1.0, min(1.0, -d.z())))
        pitch = max(min(pitch, math.radians(89.0)), math.radians(-89.0))
        if abs(math.cos(pitch)) > 1e-9:
            yaw = math.atan2(-d.y(), -d.x())
        else:
            yaw = self.yaw
        self.yaw, self.pitch = yaw, pitch
        self.target = eye + d * self.distance

    def turn(self, d_yaw_deg: float, d_pitch_deg: float) -> None:
        """Turn the head: the eye stays put, the look direction swings by
        ``d_yaw_deg`` to the right (clockwise seen from above) and
        ``d_pitch_deg`` upward."""
        eye = self.eye()
        d = self.forward()
        yaw = math.atan2(d.y(), d.x()) - math.radians(d_yaw_deg)
        pitch = math.asin(max(-1.0, min(1.0, d.z()))) + math.radians(d_pitch_deg)
        pitch = max(min(pitch, math.radians(89.0)), math.radians(-89.0))
        cp = math.cos(pitch)
        self.look_from(eye, QVector3D(cp * math.cos(yaw), cp * math.sin(yaw),
                                      math.sin(pitch)))

    def move_eye(self, delta: QVector3D) -> None:
        """Walk: eye and target move together, the look stays the same."""
        self.target = self.target + delta

    #: Two-point perspective gives way to the ordinary one past this pitch
    #: (about 78°): looking nearly straight down, the frustum shift that
    #: keeps the target centred grows without bound.
    _TWO_POINT_MIN_COS = 0.2

    def _level_forward(self) -> QVector3D | None:
        """The level sight line of a two-point perspective — the view
        direction with its slope taken out — or ``None`` when the view is
        an ordinary one (the mode off, parallel, or looking too steeply)."""
        if not (self.two_point and self.perspective):
            return None
        f = self.forward()
        h = QVector3D(f.x(), f.y(), 0.0)
        if h.length() < self._TWO_POINT_MIN_COS:
            return None
        return h / h.length()

    def view_matrix(self) -> QMatrix4x4:
        m = QMatrix4x4()
        level = self._level_forward()
        if level is not None:
            # The picture plane stands upright, so verticals stay vertical;
            # the projection's shift (below) puts the target back on centre.
            eye = self.eye()
            m.lookAt(eye, eye + level, QVector3D(0.0, 0.0, 1.0))
            return m
        m.lookAt(self.eye(), self.target, self.up_vector())
        return m

    def projection_matrix(self) -> QMatrix4x4:
        m = QMatrix4x4()
        if self.perspective:
            # The near plane follows the camera in: at any normal working
            # distance it is the usual 0.1 m, and only when you come right up
            # to something does it step back out of the way — otherwise the
            # near plane itself is what stops you.
            near = min(self.znear, max(self.distance * 0.02, 1e-4))
            level = self._level_forward()
            if level is not None:
                # A view camera's rise: the frustum slides up or down by the
                # target's height over the level sight line, so what you
                # orbit around stays in the middle of the screen.
                half_h = near * math.tan(math.radians(self.fov_deg) / 2.0)
                half_w = half_h * self.aspect
                rel = self.target - self.eye()
                depth = QVector3D.dotProduct(rel, level)
                shift = rel.z() * near / depth
                m.frustum(-half_w, half_w, -half_h + shift, half_h + shift,
                          near, self.zfar)
                return m
            m.perspective(self.fov_deg, self.aspect, near, self.zfar)
        else:
            # Parallel projection — size derived from camera distance so the
            # framing matches what the user sees in perspective.
            half_h = self.distance * math.tan(math.radians(self.fov_deg) / 2.0)
            half_w = half_h * self.aspect
            m.ortho(-half_w, half_w, -half_h, half_h, -self.zfar, self.zfar)
        return m

    # ---- Navigation ---------------------------------------------------------
    def orbit(self, dx_pixels: float, dy_pixels: float, viewport_h: int) -> None:
        """Turn the model under the cursor, Blender style.

        Both axes GRAB THE MODEL: drag right and the model swings right,
        drag down and it tips down — you come up over it and see its top.
        Same gesture as :meth:`pan`, and that is the check that matters,
        because until 2026-09-09 the vertical axis disagreed with it:
        ``pitch`` went the other way, so dragging down moved the CAMERA
        down and the model appeared to slide up while the horizontal axis
        kept grabbing. Two users reported it the same day (GitHub #7 and
        an e-mail), neither able to say which of the two axes was wrong —
        which is exactly what a single inverted axis feels like from the
        outside.

        Callers that let the user ask for the old feel negate ``dy_pixels``
        (Preferences ▸ Invert vertical orbit); the convention itself lives
        here.
        """
        scale = math.pi / max(viewport_h, 1)
        self.yaw -= dx_pixels * scale
        # Clamp to just shy of poles to avoid the up-vector singularity.
        self.pitch = max(
            min(self.pitch + dy_pixels * scale, math.radians(89.0)),
            math.radians(-89.0),
        )

    def orbit_about(self, pivot: QVector3D, dx_pixels: float,
                    dy_pixels: float, viewport_h: int) -> None:
        """:meth:`orbit` around ``pivot`` instead of the target (#164).

        Same drag convention and the same yaw/pitch change, but the whole
        camera (eye AND target) turns rigidly about ``pivot``: the model
        point the gesture started on stays where it was on screen, instead
        of the view swinging around the target -- which, on a model far
        from the origin, was a point nowhere near what you were looking at.
        The yaw turn is about the world vertical through the pivot, the
        pitch turn about the view's horizontal axis, so the horizon stays
        level (no roll) and the distance to the target never changes.
        """
        from PySide6.QtGui import QQuaternion

        old_yaw, old_pitch = self.yaw, self.pitch
        self.orbit(dx_pixels, dy_pixels, viewport_h)     # the angles, clamped
        d_yaw = self.yaw - old_yaw
        d_pitch = self.pitch - old_pitch
        if abs(d_yaw) < 1e-12 and abs(d_pitch) < 1e-12:
            return
        z = QVector3D(0.0, 0.0, 1.0)
        rot_yaw = QQuaternion.fromAxisAndAngle(z, math.degrees(d_yaw))
        # the eye's direction from the target after the yaw turn; raising
        # its elevation is a turn about (offset x Z), right-handed
        cp = math.cos(old_pitch)
        offset = QVector3D(cp * math.cos(self.yaw), cp * math.sin(self.yaw),
                           math.sin(old_pitch))
        axis = QVector3D.crossProduct(offset, z)
        if axis.length() < 1e-9:
            rot = rot_yaw
        else:
            rot = QQuaternion.fromAxisAndAngle(
                axis.normalized(), math.degrees(d_pitch)) * rot_yaw
        self.target = pivot + rot.rotatedVector(self.target - pivot)

    def pan(self, dx_pixels: float, dy_pixels: float, viewport_h: int,
            depth: float | None = None) -> None:
        """Slide the view by a drag of ``(dx, dy)`` pixels.

        ``depth`` is how far in front of the eye the point grabbed under
        the cursor lies: in perspective, a pixel spans more the deeper it
        is, so moving by that depth keeps the grabbed point under the
        cursor, as users expect. Without it the pan used the distance to
        the orbit target, which zooming in shrinks to 2 cm: at full zoom a
        wall metres away barely moved (Alejandro Limón, #184). Parallel
        views scale the same at every depth and ignore it."""
        cp = math.cos(self.pitch)
        sp = math.sin(self.pitch)
        cy = math.cos(self.yaw)
        sy = math.sin(self.yaw)
        # View direction (eye → target): the eye sits at
        # target + distance·(cp·cy, cp·sy, sp), so forward is its negation.
        # Using +that vector flipped screen-right, inverting horizontal pan.
        forward = QVector3D(-cp * cy, -cp * sy, -sp)
        right = QVector3D.crossProduct(forward, self.up_vector()).normalized()
        screen_up = QVector3D.crossProduct(right, forward).normalized()
        span = self.distance
        if (self.perspective and depth is not None and math.isfinite(depth)
                and depth > 1e-6):
            span = depth
        world_per_pixel = (
            2.0
            * span
            * math.tan(math.radians(self.fov_deg) / 2.0)
            / max(viewport_h, 1)
        )
        self.target = self.target - right * (dx_pixels * world_per_pixel)
        self.target = self.target + screen_up * (dy_pixels * world_per_pixel)

    def zoom(self, steps: float) -> None:
        factor = 0.9 ** steps
        self.distance = max(MIN_DISTANCE,
                            min(self.distance * factor, MAX_DISTANCE))

    def zoom_to(self, steps: float, focus: QVector3D,
                min_step: float = 0.0) -> None:
        """Zoom keeping the world point ``focus`` (under the cursor) fixed on
        screen, as usual. The whole frame scales toward ``focus``, so both
        the distance and the target move by the same factor.

        Two escapes from the "stuck" close-up (the orbit distance pinned at
        MIN_DISTANCE, 2 cm): zooming IN keeps sliding the target toward the
        focus even when the distance cannot shrink any more, and zooming OUT
        retreats the eye by at least ``min_step`` (the viewport passes ~1 %
        of the model's size) — at 2 cm a plain 10 % step was 2 mm per
        notch, dozens of notches to see anything, so users reached for Zoom
        Extents instead."""
        factor = 0.9 ** steps
        new_distance = max(MIN_DISTANCE,
                           min(self.distance * factor, MAX_DISTANCE))
        eye_before = self.eye()
        self.target = focus + (self.target - focus) * factor
        self.distance = new_distance
        if steps < 0 and min_step > 0.0:
            moved = (self.eye() - eye_before).length()
            if moved < min_step:
                back = self.eye() - self.target
                if back.length() > 1e-9:
                    self.target += back.normalized() * (min_step - moved)

    def set_aspect(self, w: int, h: int) -> None:
        self.aspect = max(w, 1) / max(h, 1)

    def toggle_projection(self) -> None:
        self.perspective = not self.perspective
        self.two_point = False

    def toggle_two_point(self) -> None:
        """Camera ▸ Two-Point Perspective; turning it on also
        turns a parallel view back into a perspective."""
        self.two_point = not self.two_point
        if self.two_point:
            self.perspective = True

    #: The three projections the View toolbar's quick buttons offer.
    PROJECTIONS = ("parallel", "perspective", "two_point")

    def projection_mode(self) -> str:
        """``"parallel"``, ``"perspective"`` or ``"two_point"`` — what the
        camera is showing, as the quick buttons name it. ``two_point`` set
        on a parallel camera is no two-point view, so it reads parallel."""
        if not self.perspective:
            return "parallel"
        return "two_point" if self.two_point else "perspective"

    def set_projection(self, mode: str) -> None:
        """Put the camera in one of :attr:`PROJECTIONS` (an unknown name
        is ignored). The pose — target, angles, distance — is untouched."""
        if mode not in self.PROJECTIONS:
            return
        self.perspective = mode != "parallel"
        self.two_point = mode == "two_point"

    # ---- Navigation presets ------------------------------------------------
    def fit_to(self, min_pt: QVector3D, max_pt: QVector3D, margin: float = 1.3) -> None:
        """Center the camera on the AABB and back up enough to frame it."""
        center = QVector3D(
            (min_pt.x() + max_pt.x()) * 0.5,
            (min_pt.y() + max_pt.y()) * 0.5,
            (min_pt.z() + max_pt.z()) * 0.5,
        )
        diag = (max_pt - min_pt).length()
        if diag < MIN_DISTANCE:
            diag = MIN_DISTANCE      # an empty scene still needs a distance
        self.target = center
        fov_rad = math.radians(self.fov_deg)
        self.distance = max(diag * margin / (2.0 * math.tan(fov_rad / 2.0)),
                            MIN_DISTANCE)

    def fit_box(self, min_pt: QVector3D, max_pt: QVector3D,
                margin: float = 1.1) -> None:
        """Zoom Extents: frame the box as the camera looks at it NOW.

        ``fit_to`` frames the box's bounding SPHERE, which does not depend
        on the view — so after an orbit or a standard view it gave back the
        very same target and distance, and a second Zoom Extents did
        nothing even with the model a fraction of the screen (Marco: «a
        veces no hace efecto, en determinadas posiciones»). Here the eight
        corners are measured along the camera's right and up, so the model
        fills the window in this orientation and for this window shape;
        in perspective the camera also backs off by how far the box comes
        toward it, so the near side is not cut by the frame."""
        f = self.forward()
        r = QVector3D.crossProduct(f, self.up_vector())
        if r.lengthSquared() < 1e-18:
            self.fit_to(min_pt, max_pt)
            return
        r = r.normalized()
        u = QVector3D.crossProduct(r, f)
        xs = (min_pt.x(), max_pt.x())
        ys = (min_pt.y(), max_pt.y())
        zs = (min_pt.z(), max_pt.z())
        corners = [QVector3D(x, y, z) for x in xs for y in ys for z in zs]
        center = (min_pt + max_pt) * 0.5
        pr = [QVector3D.dotProduct(c - center, r) for c in corners]
        pu = [QVector3D.dotProduct(c - center, u) for c in corners]
        target = center + r * ((max(pr) + min(pr)) * 0.5) \
            + u * ((max(pu) + min(pu)) * 0.5)
        half_w = (max(pr) - min(pr)) * 0.5
        half_h = (max(pu) - min(pu)) * 0.5
        t = math.tan(math.radians(self.fov_deg) / 2.0)
        aspect = self.aspect if self.aspect > 1e-6 else 1.0
        half = max(half_h, half_w / aspect, MIN_DISTANCE) * margin
        distance = half / t
        if self.perspective:
            toward = max(-QVector3D.dotProduct(c - target, f)
                         for c in corners)
            distance += max(toward, 0.0)
        self.target = target
        self.distance = min(max(distance, MIN_DISTANCE), MAX_DISTANCE)
        if self.perspective:
            self._settle_perspective_fit(corners, margin)

    def _settle_perspective_fit(self, corners, margin: float) -> None:
        """The perspective estimate above backs off for the NEAREST corner
        as if every corner were that close, and centres the box in space,
        not on screen — a deep box came out at 60 % of the window and low.
        Measure the real projection: slide the target so the box is centred
        on screen, then walk the distance in until its wider half-span sits
        at ``1 / margin`` of the window — never past a corner reaching the
        camera."""
        from PySide6.QtGui import QVector4D
        goal = 1.0 / margin
        t = math.tan(math.radians(self.fov_deg) / 2.0)
        for _ in range(8):
            mvp = self.projection_matrix() * self.view_matrix()
            xs, ys = [], []
            for c in corners:
                p = mvp.map(QVector4D(c.x(), c.y(), c.z(), 1.0))
                if p.w() <= 1e-9:
                    return
                xs.append(p.x() / p.w())
                ys.append(p.y() / p.w())
            cx = (max(xs) + min(xs)) * 0.5
            cy = (max(ys) + min(ys)) * 0.5
            reach = max((max(xs) - min(xs)) * 0.5, (max(ys) - min(ys)) * 0.5)
            if reach <= 0.0:
                return
            if abs(reach - goal) < 0.005 and abs(cx) < 0.005 and abs(cy) < 0.005:
                return
            f = self.forward()
            r = QVector3D.crossProduct(f, self.up_vector()).normalized()
            u = QVector3D.crossProduct(r, f)
            half_h = self.distance * t
            self.target = self.target + r * (cx * half_h * self.aspect) \
                + u * (cy * half_h)
            nearest = max(-QVector3D.dotProduct(c - self.target, f)
                          for c in corners)
            gap = self.distance - nearest       # eye to the nearest corner
            self.distance = min(max(nearest + gap * reach / goal,
                                    MIN_DISTANCE), MAX_DISTANCE)

    # Yaw / pitch presets for standard architectural views (Z-up convention).
    # Top and Bottom are EXACTLY vertical: at 89° the parallel projection
    # showed every vertical edge as a short line and a plan came out a
    # hair oblique (@pacaeiro, issue #45: «Top and Bottom views are not
    # straight (camera not perpendicular to view)»). ``up_vector`` keeps
    # lookAt and the camera bases from degenerating there.
    _STANDARD_VIEWS = {
        "top":    (math.radians(-90.0), math.radians(90.0)),
        "bottom": (math.radians(-90.0), math.radians(-90.0)),
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
