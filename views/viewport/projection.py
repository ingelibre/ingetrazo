# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pixel and world conversions, rays, work planes and depth reads."""
from __future__ import annotations

import math
from typing import Optional
from PySide6.QtGui import QVector3D, QVector4D


class ProjectionMixin:
    """Pixel and world conversions, rays, work planes and depth reads."""

    # ---- Pixel ↔ world ------------------------------------------------------
    def _pixel_to_ray(
        self, x: float, y: float
    ) -> tuple[Optional[QVector3D], Optional[QVector3D]]:
        """Camera ray (origin, unit direction) through the given pixel."""
        w = max(self.width(), 1)
        h = max(self.height(), 1)
        ndc_x = 2.0 * x / w - 1.0
        ndc_y = 1.0 - 2.0 * y / h
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        inv, ok = mvp.inverted()
        if not ok:
            return None, None
        p_near = inv.map(QVector3D(ndc_x, ndc_y, -1.0))

        def finite(v):
            return all(map(math.isfinite, (v.x(), v.y(), v.z())))
        # The far plane gives the most exact direction, far from the near
        # point. But a camera a few centimetres from a part (#583) has its
        # near plane 0.4 mm out and the far one kilometres away: past
        # float32 the depth term rounds to exactly -1, the far plane goes
        # to infinity, and the ray came out NaN — and with it every snap
        # built on the cursor. Then a point just short of it serves.
        direction = None
        for depth in (1.0, 0.999, 0.9, 0.0):
            d = inv.map(QVector3D(ndc_x, ndc_y, depth)) - p_near
            if finite(d) and d.length() >= 1e-9:
                direction = d
                break
        if direction is None or not finite(p_near):
            return None, None
        return p_near, direction.normalized()

    def _coplanar_eps(self, origin: QVector3D, direction: QVector3D,
                      best_t: float) -> float:
        """How much deeper than the nearest hit a face may sit and still
        count as "the same depth" (coplanar faces, a hole's rim on its
        slab): a ten-thousandth of the distance from the EYE, never less
        than 0.1 mm. It used to be a ten-thousandth of the ray parameter —
        fine in perspective, where the ray starts at the eye, but the
        parallel camera's ray starts a far plane behind it, 10 km back, so
        the tolerance came out a full metre and a smaller face 30 cm
        BEHIND the one under the cursor won the coplanar tiebreak
        (@pacaeiro, issue #37: «face detection is identifying the face
        that is behind the one in front… in CAMERA orthogonal mode»)."""
        cam = getattr(self, "camera", None)
        if cam is None:                     # a bare stand-in (tests)
            return max(1e-4, best_t * 1e-4)
        t_eye = QVector3D.dotProduct(cam.eye() - origin, direction)
        return max(1e-4, abs(best_t - t_eye) * 1e-4)

    def _world_from_pixel(self, x: int, y: int) -> Optional[QVector3D]:
        """Pixel → world hit on the *current* work plane.

        Plane choice priority:
        1. ``tool.work_plane``, captured at first click when the user clicked
           on a face — keeps the rest of the chain coplanar with that face.
        2. If a tool has a ``start_point``, the plane goes through it; its
           orientation is horizontal for most camera tilts and vertical only
           near the horizon (so dragging up/down can move in Z).
        3. If no ``start_point`` yet and the cursor is over an existing
           face, that face's plane (this is what lets the user draw a new
           polygon *inside* an existing one — e.g. on top of a box).
        4. Ground (Z=0).
        """
        origin, direction = self._pixel_to_ray(x, y)
        if origin is None or direction is None:
            return None
        plane_point, plane_normal = self._current_work_plane(cursor=(x, y))
        # The snap engine needs the plane too — "perpendicular to this edge"
        # only means something within a plane. Stashed instead of asked for
        # again: this runs on every mouse move, and the answer can cost a pick.
        self._last_work_plane = (plane_point, plane_normal)
        tool = self.active_tool
        allow_planar_grazing = False
        if (tool is not None
                and getattr(tool, "start_point", None) is None
                and getattr(tool, "work_plane", None) is None
                and getattr(tool, "plane_lock", None) is None
                and getattr(tool, "plane_ref", None) is None):
            from tools.base import PlaneLock
            if isinstance(tool, PlaneLock):
                from core import axes
                normal = QVector3D(plane_normal).normalized()
                through_origin = (
                    (QVector3D(plane_point) - axes.origin()).length() < 1e-5)
                principal = any(
                    abs(QVector3D.dotProduct(normal, axes.axis(name))) > 0.999
                    for name in ("x", "y", "z")
                )
                allow_planar_grazing = through_origin and principal
        hit = self._ray_plane(
            origin, direction, plane_point, plane_normal,
            allow_grazing=allow_planar_grazing)
        if hit is not None:
            return hit
        # The ray only grazes the work plane here, so the intersection is
        # junk: it runs off toward the horizon and a single pixel is worth
        # hundreds of metres (measured with the ground plane captured and the
        # camera 16 deg below the horizon: 85 m at mid screen, 405 m twenty
        # pixels higher, and Marco got 1757.25 m on a 100 m plaza while the
        # status bar said "On face"). If a real face IS under the cursor,
        # believe the face — that is what the cursor is pointing at, and what
        # the inference is already promising.
        face, group = self.pick_face_any(x, y)
        if face is not None:
            from core.snap import face_plane_world
            fpoint, fnormal = face_plane_world(face, getattr(group, "xform", None))
            if fnormal is not None:
                return self._ray_plane(origin, direction, fpoint, fnormal)
        return None

    #: A ray meeting the work plane below this angle gives a point nobody
    #: asked for. Measured: at 25 deg of camera pitch — an ordinary
    #: architectural view — nothing on screen comes anywhere near it, so this
    #: only fires where the plane really is unreadable.
    GRAZING_PLANE_DEG = 6.0

    def _work_plane_normal(self) -> Optional[QVector3D]:
        """The normal of the plane the last pixel→world used, or ``None``."""
        plane = getattr(self, "_last_work_plane", None)
        return plane[1] if plane is not None else None

    @staticmethod
    def _same_plane(a, b, tol: float = 1e-6) -> bool:
        """Whether the ``(point, normal)`` planes ``a`` and ``b`` are the
        same plane: parallel normals AND the same offset — two opposite
        walls are parallel and are not the same plane."""
        na = QVector3D(a[1]).normalized()
        nb = QVector3D(b[1]).normalized()
        if abs(QVector3D.dotProduct(na, nb)) < 1e-3:
            return False
        return abs(QVector3D.dotProduct(QVector3D(b[0]) - QVector3D(a[0]),
                                        na)) < tol

    def _planar_face_plane(self, tool, cursor, captured=None, face_plane=None):
        """The plane of the face under the cursor when a PLANAR shape is
        being drawn over one that is not its captured plane, else ``None``.

        A rectangle, circle, polygon or arc lives in ONE plane, and its
        first click captures the plane of the face it started on — the
        viewport sets ``tool.work_plane`` and the tool lays its geometry
        out there (``PlaneLock.drawing_plane``). A capture, though, also
        FROZE the shape: moving the cursor onto another face left the point
        and the preview on the captured plane while the badge went on
        reading «On face» — @pacaeiro, #545: «se eu coloco o rato
        directamente na face diz (on face), mas o plano permanece
        imutável». A rectangle started on the top vertex of a cube and
        drawn over its front face was the plain case: the cursor's point
        stayed up on the horizontal plane through that vertex.

        An EDGE off the plane already re-planned the shape, through the
        tool's ``snapped_plane``, because its point comes off the plane; a
        face did not, because the axis inference answered with a camera
        plane while the status bar named the face. The face the cursor is
        over is the same bargain and the plainer one: it is what the cursor
        points at and what the badge names, so the shape lands on it.

        A snap that names a POINT of the model (``core.snap.
        POINT_SNAP_KINDS``) is not this bargain and is not decided here:
        the user aimed at that point, not at the face it happens to lie
        on, and the tool re-plans onto it through ``PlaneLock.
        snapped_plane`` — which is where the face's claim is settled too
        (``Tool.snap_kind``). Here the viewport only reads which face the
        cursor is over.

        ``None`` keeps the caller's plane: no cursor, no face under it, the
        face the shape started on (``captured``), a tool that is not a
        planar shape (a LINE keeps its chain coplanar with the face it was
        started on), the arrows already locking a direction (anywhere else
        in here a locked direction leaves the plane where it was), or the
        user's own plane lock — ``plane_lock`` / the magenta ``plane_ref`` —
        which never yields."""
        if cursor is None or tool is None or self.axis_lock is not None:
            return None
        if (getattr(tool, "plane_lock", None) is not None
                or getattr(tool, "plane_ref", None) is not None):
            return None
        from tools.base import PlaneLock
        if not isinstance(tool, PlaneLock):
            return None
        if face_plane is None:
            face_plane = self._hover_face_plane(cursor)
        if face_plane is None:
            return None
        if captured is not None and self._same_plane(captured, face_plane):
            return None        # the face it started on: nothing to re-plan
        return face_plane

    def _ray_plane(self, origin: QVector3D, direction: QVector3D,
                   plane_point: QVector3D, plane_normal: QVector3D,
                   *, allow_grazing: bool = False,
                   ) -> Optional[QVector3D]:
        """Ray/plane hit, or ``None`` when it is behind the camera or the ray
        merely grazes the plane."""
        length = plane_normal.length()
        if length < 1e-9:
            return None
        normal = plane_normal / length
        denom = QVector3D.dotProduct(normal, direction)
        if abs(denom) < 1e-12:
            return None
        if (not allow_grazing
                and abs(denom) < math.sin(math.radians(
                    self.GRAZING_PLANE_DEG))):
            return None
        t = QVector3D.dotProduct(normal, plane_point - origin) / denom
        if t < 0:
            return None
        return origin + direction * t

    #: XY stays the ground in shallow views and where its cursor-ray hit is
    #: reasonably close compared with the two vertical global planes.
    GROUND_PREFERENCE_ANGLE_DEG = 5.0
    GROUND_DEPTH_PREFERENCE_RATIO = 1.25
    PERSPECTIVE_GROUND_DEPTH_PREFERENCE_RATIO = 10.0
    PLANE_ALIGNMENT_TIE_MARGIN = 0.05

    def _camera_planar_work_plane(
        self, cursor: Optional[tuple[float, float]] = None,
    ) -> Optional[tuple[QVector3D, QVector3D]]:
        """Choose XY as floor/ceiling when preferred, otherwise XZ or YZ.

        The vertical planes compete by their alignment with the local cursor
        ray. XY remains the ground (or ceiling when viewed from below), with
        a depth preference that avoids mapping a nearby cursor to an
        implausibly distant point on the floor.
        """
        from core import axes
        origin = axes.origin()
        view = self.camera.target - self.camera.eye()
        if view.lengthSquared() < 1e-18:
            return None
        view.normalize()
        ray_origin = self.camera.eye()
        ray_direction = view
        cursor_origin: Optional[QVector3D] = None
        cursor_direction: Optional[QVector3D] = None
        if cursor is not None:
            cursor_origin, cursor_direction = self._pixel_to_ray(*cursor)
            if cursor_origin is not None and cursor_direction is not None:
                ray_origin = cursor_origin
                ray_direction = cursor_direction.normalized()

        normals = {name: axes.axis(name) for name in ("x", "y", "z")}
        hits: dict[str, tuple[QVector3D, float]] = {}
        if ray_origin is not None:
            for name, normal in normals.items():
                hit = self._ray_plane(
                    ray_origin, ray_direction, origin, normal,
                    allow_grazing=True)
                if hit is None:
                    continue
                depth = (
                    (hit - self.camera.eye()).length()
                    if self.camera.perspective
                    else QVector3D.dotProduct(hit - self.camera.eye(), view)
                )
                if depth >= 0:
                    hits[name] = hit, depth

        horizontal_angle = math.degrees(math.asin(min(
            1.0, abs(QVector3D.dotProduct(view, normals["z"])))))
        if "z" in hits:
            vertical_depths = [
                hits[name][1] for name in ("x", "y") if name in hits]
            depth_ratio = (
                self.GROUND_DEPTH_PREFERENCE_RATIO
                if horizontal_angle <= self.GROUND_PREFERENCE_ANGLE_DEG
                else self.PERSPECTIVE_GROUND_DEPTH_PREFERENCE_RATIO
            )
            if (not vertical_depths
                    or hits["z"][1] <= min(vertical_depths) * depth_ratio):
                return origin, normals["z"]

        alignment = {
            name: abs(QVector3D.dotProduct(ray_direction, normals[name]))
            for name in ("x", "y")
        }
        candidates = {"x", "y"}
        if cursor_origin is not None and cursor_direction is not None:
            candidates = {
                name for name in candidates
                if self._ray_plane(
                    cursor_origin, cursor_direction, origin, normals[name],
                    allow_grazing=True) is not None
            }
        if not candidates:
            candidates = {"x", "y"}
        normal_name = max(candidates, key=alignment.__getitem__)
        if (candidates == {"x", "y"}
                and abs(alignment["x"] - alignment["y"])
                <= self.PLANE_ALIGNMENT_TIE_MARGIN):
            normal_name = "y"
        return origin, normals[normal_name]

    # When the camera is at least this tilted off the horizon, the work plane
    # stays horizontal (XY) — that covers top, iso, and most architectural
    # angles. Only at near-horizon views does it switch to a vertical plane,
    # which is the only orientation where cursor-to-ground is ambiguous.
    HORIZON_PITCH_THRESHOLD_DEG = 15.0

    def _current_work_plane(
        self, cursor: Optional[tuple[float, float]] = None
    ) -> tuple[QVector3D, QVector3D]:
        """Return ``(point, normal)`` of the current drawing plane.

        Priority: tool-captured plane > camera-aware plane through the active
        ``start_point`` > face under cursor (face-plane inference) > ground —
        except that a PLANAR shape re-plans onto the face the cursor is over,
        capture or not (#545, see :meth:`_planar_face_plane`). A shape lives
        in ONE plane, and the face the cursor is over is the one the user
        means.
        """
        tool = self.active_tool
        if tool is not None:
            # A tool mid-operation may know better than any plane below —
            # Push/Pull reads the cursor along its normal and must keep
            # hearing hovers and clicks above the horizon (see
            # ``Tool.drag_plane``).
            own_plane = getattr(tool, "drag_plane", None)
            own = own_plane(self) if own_plane is not None else None
            if own is not None:
                return own
        captured = getattr(tool, "work_plane", None) if tool is not None else None
        if captured is not None:
            # (#545) A planar shape re-plans onto the face the cursor is
            # over, and takes its capture with it: the preview (drawn on the
            # tool's own plane, ``PlaneLock.drawing_plane``) and the point
            # would otherwise sit on two different planes — and that split
            # IS the bug. ``_planar_face_plane`` holds the whole argument.
            face_plane = self._planar_face_plane(tool, cursor, captured)
            if face_plane is not None:
                tool.work_plane = face_plane
                return face_plane
            # The escape hatch: orbiting down to the horizon means "I
            # want to draw UPWARD now". A first click on a horizontal face
            # (the ground, a slab) captures its plane and would pin the whole
            # chain flat forever; at near-horizon views, where the horizontal
            # plane is unreadable anyway, a HORIZONTAL captured plane yields
            # to the vertical plane through the start point so the line can
            # rise in Z. Vertical captured planes (walls) already allow it.
            start = (getattr(tool, "start_point", None)
                     if tool is not None else None)
            from tools.base import PlaneLock
            if (start is not None and abs(captured[1].normalized().z()) > 0.94
                    and getattr(tool, "plane_lock", None) is None
                    and not isinstance(tool, PlaneLock)):
                # (an arrow-key plane lock is exactly what the user asked
                # for: it never yields; and a PLANAR shape — rectangle,
                # circle, arc — lives in its captured plane by definition:
                # handing it points on another plane squashed it to a line)
                vertical = self._near_horizon_vertical(start)
                if vertical is not None:
                    return vertical
            return captured

        start = getattr(tool, "start_point", None) if tool is not None else None
        if start is None:
            from core import axes
            from tools.base import PlaneLock
            if isinstance(tool, PlaneLock):
                locked = tool.locked_work_plane(axes.origin())
                if locked is not None:
                    return locked
            # First-click hover: if the cursor is over an existing face —
            # loose OR a group's (drawing/measuring on top of an imported
            # reference model) — use that face's plane so a new polygon
            # drawn "inside" it lands on the face instead of the ground.
            if cursor is not None and tool is not None:
                face, grp = self.pick_face_placement(cursor[0], cursor[1])
                if face is not None:
                    from core.snap import face_plane_world
                    return face_plane_world(face, getattr(grp, "xform", None))
                # No geometry under the cursor, but maybe a reference image:
                # its plane becomes the drawing plane, which is the whole
                # point of importing a scan — you trace ON it, at its own
                # tilt, not on the ground underneath.
                image = self.image_plane_at(cursor[0], cursor[1])
                if image is not None:
                    return image.plane()
            if isinstance(tool, PlaneLock) and cursor is not None:
                plane = self._camera_planar_work_plane(cursor)
                if plane is not None:
                    return plane
            # In an axis-aligned (standard) view, an unsnapped first point
            # belongs on the plane FACING the camera through the model
            # centre — so measuring/drawing in a front view stays in the
            # frontal plane instead of dropping to the ground. Oblique
            # orbit views keep the ground fallback (freehand unchanged).
            from core.snap import first_point_work_plane
            forward = self.camera.target - self.camera.eye()
            lo, hi = self.scene.bounds()
            center = ((lo + hi) * 0.5 if lo is not None
                      else QVector3D(0.0, 0.0, 0.0))
            plane = first_point_work_plane(forward, center)
            if plane is not None:
                return plane
            return QVector3D(0.0, 0.0, 0.0), QVector3D(0.0, 0.0, 1.0)

        base = self._start_point_plane(tool, start)
        if cursor is not None and self.axis_lock is None:
            # On Face for the SECOND point (Move's target, the
            # tape's far end, a line's end): the cursor over another face
            # lands ON that face. The axis inference still wins — a line
            # drawn straight up over a slab keeps rising instead of dropping
            # onto it — and the geometry being moved never offers its own
            # (already vacated) faces.
            fp = self._hover_face_plane(cursor)
            if fp is not None:
                from tools.base import PlaneLock
                if isinstance(tool, PlaneLock):
                    # A PLANAR shape does not get the axis escape below
                    # (#545, @pacaeiro: «se eu coloco o rato directamente
                    # na face diz (on face), mas o plano permanece
                    # imutável»). An EDGE already re-planned the shape,
                    # through ``snapped_plane``, because its point comes
                    # off the plane; a face did not, because the axis
                    # inference handed back the camera plane through the
                    # first corner while the status bar went on reading
                    # «On face» — and the shape's own axes had already
                    # taken the wall's, so the preview and the point sat
                    # on two different planes. A rectangle started on the
                    # top vertex of a cube was the plain case: over the
                    # front face the point came back at (2.00, -1.20,
                    # 2.00), the horizontal plane through that vertex.
                    # The point the cursor is over is the one the user
                    # means: a shape lives in ONE plane, so the face wins
                    # outright. The arrows and the Down reference never
                    # reach this branch — a lock is captured as the
                    # tool's ``work_plane`` by the first click and
                    # returned above. A line drawn straight up over a
                    # slab is not a PlaneLock and keeps rising. A snap
                    # that names a POINT of the model is not this case
                    # either: ``PlaneLock.snapped_plane`` re-plans the
                    # shape onto the point (``Tool.snap_kind``).
                    return fp
                cand = self._ray_hit_plane(cursor, base)
                angle = (getattr(tool, "magnetic_axis_deg", None)
                         or self.inference_angle_deg)
                from core.snap import _detect_axis_alignment
                if cand is None or _detect_axis_alignment(
                        start, cand, angle) is None:
                    return fp
        return base

    def _still_face_under(self, px: float, py: float) -> bool:
        """Whether a face the drag is NOT bending is under the cursor —
        the «On face» cue never names the face being moved."""
        face, grp = self.pick_face_any(px, py)
        if face is None:
            return False
        moving = getattr(self.active_tool, "moving_face_ids", None)
        return not (grp is None and callable(moving) and id(face) in moving())

    def _hover_face_plane(self, cursor):
        """World plane of the face under the cursor, or None.

        Selected geometry remains a valid plane target for planar drawing
        tools; other tools must not land on geometry they are moving.
        """
        face, grp = self.pick_face_placement(cursor[0], cursor[1])
        if face is None:
            return None
        sel = self.scene.selection
        owner = self._owner_of(grp) if grp is not None else None
        from tools.base import PlaneLock
        if (not isinstance(self.active_tool, PlaneLock)
                and ((owner is not None and owner in sel)
                     or (grp is None and face in sel))):
            return None
        if grp is None:
            # A face the drag is bending (one corner on a grabbed vertex)
            # is not somewhere to land: the point would follow the face,
            # the face the point, and the geometry shook under a still
            # mouse.
            moving = getattr(self.active_tool, "moving_face_ids", None)
            if callable(moving) and id(face) in moving():
                return None
        from core.snap import face_plane_world
        return face_plane_world(face, getattr(grp, "xform", None))

    def _ray_hit_plane(self, cursor, plane):
        origin, direction = self._pixel_to_ray(cursor[0], cursor[1])
        if origin is None or direction is None:
            return None
        point, normal = plane
        denom = QVector3D.dotProduct(normal, direction)
        if abs(denom) < 1e-6:
            return None
        t = QVector3D.dotProduct(normal, point - origin) / denom
        return None if t < 0 else origin + direction * t

    def _start_point_plane(self, tool, start):
        """The camera-aware plane through the active start point."""
        forward = (self.camera.target - self.camera.eye())
        if forward.length() < 1e-9:
            return start, QVector3D(0.0, 0.0, 1.0)
        forward = forward.normalized()
        # Tools that drag geometry up and down (Move) use a camera-facing
        # vertical plane through the grab point, so pulling the mouse up raises
        # the geometry rigidly instead of sliding it across the ground (which
        # shears connected faces and looks disordered). The plane contains the
        # world Z axis; its normal is the camera's horizontal heading. Only when
        # looking nearly straight down — where height is unreadable anyway — does
        # it fall back to the horizontal plane.
        if getattr(tool, "prefers_vertical_drag", False):
            horiz = QVector3D(forward.x(), forward.y(), 0.0)
            if horiz.length() >= math.sin(math.radians(self.HORIZON_PITCH_THRESHOLD_DEG)):
                return start, horiz.normalized()
            return start, QVector3D(0.0, 0.0, 1.0)
        # |forward.z| ≈ sin(pitch). Anything tilted more than the threshold
        # keeps the horizontal plane.
        vertical = self._near_horizon_vertical(start)
        if vertical is not None:
            return vertical
        return start, QVector3D(0.0, 0.0, 1.0)

    def _near_horizon_vertical(
        self, start: QVector3D
    ) -> Optional[tuple[QVector3D, QVector3D]]:
        """The vertical work plane through ``start`` when the camera sits near
        the horizon — the only orientation where cursor→ground is ambiguous
        and dragging up must move in Z. ``None`` at steeper tilts."""
        forward = (self.camera.target - self.camera.eye())
        if forward.length() < 1e-9:
            return None
        forward = forward.normalized()
        if abs(forward.z()) >= math.sin(
                math.radians(self.HORIZON_PITCH_THRESHOLD_DEG)):
            return None
        # Pick the vertical plane whose normal is more end-on to the camera
        # so cursor motion maps cleanly to it.
        if abs(forward.x()) >= abs(forward.y()):
            return start, QVector3D(1.0, 0.0, 0.0)
        return start, QVector3D(0.0, 1.0, 0.0)

    def _project_to_lock_line(
        self,
        start: QVector3D,
        lock_dir: QVector3D,
        pixel_x: float,
        pixel_y: float,
    ) -> QVector3D:
        """Closest point on the lock line (``start``, ``lock_dir``) to the
        camera ray that passes through ``(pixel_x, pixel_y)``.

        This is what makes Z-axis locks actually let you draw vertical
        lines — moving the mouse up/down on screen slides the projected
        point along the Z line.

        The cursor is first dropped square onto the line as the screen
        shows it, so only motion ALONG the line changes the length. In
        perspective the closest point to the cursor's own ray also moved
        with the cursor's sideways position (#769).
        """
        step = max(float(getattr(self.camera, "distance", 1.0)) * 0.25, 1e-3)
        pa = self._world_to_pixel(start)
        pb = self._world_to_pixel(start + lock_dir.normalized() * step)
        if pa is not None and pb is not None:
            dx, dy = pb[0] - pa[0], pb[1] - pa[1]
            dd = dx * dx + dy * dy
            if dd > 1.0:
                s = ((pixel_x - pa[0]) * dx + (pixel_y - pa[1]) * dy) / dd
                pixel_x, pixel_y = pa[0] + dx * s, pa[1] + dy * s
        ray_origin, ray_dir = self._pixel_to_ray(pixel_x, pixel_y)
        if ray_origin is None or ray_dir is None:
            return start
        d1 = lock_dir.normalized()
        d2 = ray_dir
        r = start - ray_origin
        b = QVector3D.dotProduct(d1, d2)
        d = QVector3D.dotProduct(d1, r)
        e = QVector3D.dotProduct(d2, r)
        denom = 1.0 - b * b
        if abs(denom) < 1e-6:
            # Lock line is parallel to the camera ray — project the ray
            # origin onto the lock line as a stable fallback.
            t = -d
        else:
            t = (b * e - d) / denom
        return start + d1 * t

    #: Eye depth (m) a segment is cut at when it runs behind the camera.
    _CLIP_W = 1e-3

    def _clip_w(self) -> float:
        """Where a segment is cut in front of the eye: 1 mm, or the near
        plane when the camera has come closer than that would allow — at a
        few millimetres from a small part, 1 mm cut away the very line
        being drawn (#653, #692)."""
        cam = self.camera
        if not getattr(cam, "perspective", True):
            return self._CLIP_W
        near = getattr(cam, "near_plane", None)
        return min(self._CLIP_W, near()) if callable(near) else self._CLIP_W

    def _segment_to_pixels(self, p0: QVector3D, p1: QVector3D):
        """A world segment → its two screen pixels, cut where it passes
        behind the eye instead of dropped whole. A guide is kilometres
        long: in perspective one end is nearly always behind the camera,
        and the preview never showed (#89)."""
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        c0 = mvp.map(QVector4D(p0.x(), p0.y(), p0.z(), 1.0))
        c1 = mvp.map(QVector4D(p1.x(), p1.y(), p1.z(), 1.0))
        w0, w1, eps = c0.w(), c1.w(), self._clip_w()
        if w0 < eps and w1 < eps:
            return None
        if w0 < eps:
            c0 = c0 + (c1 - c0) * ((eps - w0) / (w1 - w0))
            c0.setW(eps)
        elif w1 < eps:
            c1 = c1 + (c0 - c1) * ((eps - w1) / (w0 - w1))
            c1.setW(eps)
        (x0, y0), (x1, y1) = [
            ((c.x() / c.w() * 0.5 + 0.5) * self.width(),
             (1.0 - (c.y() / c.w() * 0.5 + 0.5)) * self.height())
            for c in (c0, c1)]
        # Cut to the window (a margin past it): a point a hair in front of
        # the eye lands millions of pixels out, past what the painter's
        # fixed-point rasteriser draws right.
        m = 64.0
        lo_x, hi_x = -m, self.width() + m
        lo_y, hi_y = -m, self.height() + m
        dx, dy = x1 - x0, y1 - y0
        t0, t1 = 0.0, 1.0
        for p, q in ((-dx, x0 - lo_x), (dx, hi_x - x0),
                     (-dy, y0 - lo_y), (dy, hi_y - y0)):
            if p == 0.0:
                if q < 0.0:
                    return None
                continue
            r = q / p
            if p < 0.0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
        if t0 > t1:
            return None
        return [(x0 + dx * t0, y0 + dy * t0), (x0 + dx * t1, y0 + dy * t1)]

    def world_to_pixel(self, world: QVector3D) -> Optional[tuple[float, float]]:
        """Public API (extensions): world point (metres) → widget pixel
        ``(x, y)`` in logical pixels, or ``None`` when the point is behind
        the camera. The same projection the host's own overlays use."""
        return self._world_to_pixel(world)

    def world_to_pixels(self, pts):
        """Public API (extensions): an ``(N, 3)`` float array of world points
        (metres) → ``(px, py, in_front)`` NumPy arrays, vectorised — for
        overlays with thousands of points, where a Python loop over
        :meth:`world_to_pixel` would cost frames. Points with
        ``in_front == False`` are behind the camera; skip them."""
        import numpy as np
        return self._project_px(np.asarray(pts, dtype=float).reshape(-1, 3))

    def _world_to_pixel(self, world: QVector3D) -> Optional[tuple[float, float]]:
        """World point → screen pixel (or None if behind the camera)."""
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        clip = mvp.map(QVector4D(world.x(), world.y(), world.z(), 1.0))
        if clip.w() <= 0:
            return None
        ndc_x = clip.x() / clip.w()
        ndc_y = clip.y() / clip.w()
        px = (ndc_x * 0.5 + 0.5) * self.width()
        py = (1.0 - (ndc_y * 0.5 + 0.5)) * self.height()
        return (px, py)

    def _np_mvp(self):
        """Current MVP as a (4, 4) float64 NumPy matrix (row-major indexing).
        ``QMatrix4x4.data()`` is column-major, hence the Fortran reshape."""
        import numpy as np
        m = self.camera.projection_matrix() * self.camera.view_matrix()
        return np.array(m.data(), dtype=np.float64).reshape(4, 4, order="F")

    def _project_px(self, pts):
        """Batch world points (N, 3) → ``(px, py, in_front)`` arrays — the
        exact math of :meth:`_world_to_pixel`, vectorised."""
        import numpy as np
        M = self._np_mvp()
        clip = pts @ M[:, :3].T + M[:, 3]
        w = clip[:, 3]
        ok = w > 0
        safe = np.where(ok, w, 1.0)
        px = (clip[:, 0] / safe * 0.5 + 0.5) * self.width()
        py = (1.0 - (clip[:, 1] / safe * 0.5 + 0.5)) * self.height()
        return px, py, ok

    def _depth_of(self, point) -> Optional[float]:
        """How far ``point`` lies in front of the eye, along the view
        direction: what one pixel of pan is worth there (#184)."""
        if point is None:
            return None
        cam = self.camera
        return QVector3D.dotProduct(point - cam.eye(), cam.forward())

    def _depth_world_at(self, x: float, y: float):
        """What the last frame shows under widget pixel ``(x, y)``, read from
        its depth: ``("hit", point)``, ``("background", None)`` or ``None``
        when there is no frame to read (the camera moved since, an export,
        no GL). The zoom and the orbit pivot ask this first: finding the
        point with a ray needs the pick index, and on a model of 21 406
        placements building it baked every one — minutes and 8 GB on the
        first wheel notch (issue #158). A read-back is ~8 ms, and it is
        what is on screen, hidden objects and cuts included."""
        painted = getattr(self, "_painted_view", None)
        fbo = getattr(self, "_scene_fbo", None)
        if painted is None or fbo is None or self.context() is None:
            return None
        mvp = self.camera.projection_matrix() * self.camera.view_matrix()
        if tuple(mvp.data()) != painted[0]:
            return None
        w, h = painted[1], painted[2]
        snap = getattr(self, "_depth_snap", None)
        if snap is None or tuple(snap[1].data()) != painted[0]:
            self.makeCurrent()
            try:
                self._capture_depth(w, h)
            finally:
                self.doneCurrent()
            snap = getattr(self, "_depth_snap", None)
            if snap is None:
                return None
        buf, _mvp, inv = snap[0], snap[1], snap[2]
        if float(buf.min()) >= float(buf.max()):
            return None                  # a blank read-back: this GL gives no depth
        dpr = w / max(1, self.width())
        ix = int(x * dpr)
        iy = int(h - 1 - y * dpr)
        if not (0 <= ix < w and 0 <= iy < h):
            return None
        d = float(buf[iy, ix])
        if d >= 1.0:
            return ("background", None)
        nx = (ix + 0.5) / w * 2.0 - 1.0
        ny = (iy + 0.5) / h * 2.0 - 1.0
        q = inv.map(QVector4D(nx, ny, d * 2.0 - 1.0, 1.0))
        if abs(q.w()) < 1e-12:
            return None
        point = QVector3D(q.x() / q.w(), q.y() / q.w(), q.z() / q.w())
        # Zoomed right in, the near plane is a fraction of a millimetre while
        # the far one is kilometres away: the depth buffer has no precision
        # left, and the read-back unprojects to a point far behind the model
        # — or to infinity. The orbit then turned about that point and threw
        # the camera off until its target was NaN and the model would not
        # save (#485, #383). Such a point is no answer: the caller falls
        # back to the ray.
        if not all(math.isfinite(c) for c in (point.x(), point.y(), point.z())):
            return None
        if (point - self.camera.eye()).length() > 1.01 * self.camera.far_plane():
            return None
        return ("hit", point)

    def _world_under_cursor(self, x: float, y: float) -> Optional[QVector3D]:
        """The world point the cursor points at: nearest geometry hit, else the
        ground plane (Z=0), else the focal plane through the target."""
        origin, direction = self._pixel_to_ray(x, y)
        if origin is None or direction is None:
            return None
        best_t = None
        seen = self._depth_world_at(x, y) if hasattr(self, "_depth_world_at") \
            else None
        if seen is not None and seen[0] == "hit":
            return seen[1]
        # No frame to read (wheel notches faster than paints): on a huge
        # model the ray against the index cost 2 s a notch (live profile,
        # #158) — the ground and focal planes below answer at once.
        huge = (seen is None and hasattr(self, "_pick_lazy_table")
                and self._pick_lazy_table() is not None)
        idx = (self._pick_index(near=("px", x, y))
               if seen is None and not huge else None)
        if idx is not None and idx.entities:
            import numpy as np
            t = self._ray_hits(idx, origin, direction, idx.ent_vis,
                               reduce_global=True)
            if t is not None and np.isfinite(t):
                best_t = float(t)
        if best_t is not None:
            return origin + direction * best_t
        if abs(direction.z()) > 1e-6:
            t = -origin.z() / direction.z()
            if t > 0:
                return origin + direction * t
        view = (self.camera.target - self.camera.eye())
        if view.length() > 1e-9:
            view = view.normalized()
            denom = QVector3D.dotProduct(direction, view)
            if abs(denom) > 1e-6:
                t = QVector3D.dotProduct(self.camera.target - origin, view) / denom
                if t > 0:
                    return origin + direction * t
        return None

    def _model_diag(self) -> float:
        """The model's size, for the zoom step. On a huge model it comes
        from the placement boxes the pick index already holds: the exact
        box read every vertex, ~2 s on the first wheel notch (#158)."""
        cached = getattr(self.scene, "_bounds_cache", None)
        if cached is None or cached[0] != self.scene.version:
            table = (self._pick_lazy_table()
                     if hasattr(self, "_pick_lazy_table") else None)
            if table is not None:
                import numpy as np
                lo, hi = table[1], table[2]
                ok = np.isfinite(lo).all(axis=1) & np.isfinite(hi).all(axis=1)
                if ok.any():
                    return float(np.linalg.norm(hi[ok].max(axis=0)
                                                - lo[ok].min(axis=0)))
        lo, hi = self.scene.bounds()
        return (hi - lo).length() if lo is not None else 0.0
