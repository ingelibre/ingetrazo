# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rotated Rectangle tool: a rectangle at any angle IN ANY PLANE.

Three clicks, the classic way:
1. first corner — which also captures the plane,
2. second corner — sets the base edge's **direction and length** (the
   rotation), with a protractor drawn at the first corner: near its rim the
   direction snaps to 15° ticks, Shift holds the direction so only the
   length follows the cursor; the VCB takes ``length`` or
   ``length;angle`` (angle from the plane's first axis),
3. the width and its angle around the base edge, with a second protractor
   square to that edge at the second corner (15° ticks near its rim; Shift
   holds the angle); the VCB takes ``width`` or ``width;angle``.

The two protractors are @pacaeiro's issue #70 — «a "Protractor" inside it,
to help drawing the rectangle» — which is the classic tool: IngeTrazo
had the geometry of step 3 but drew neither instrument.

The plane is the whole point of the tool and it used to be missing:
``work_plane`` was declared, reset and read, but never assigned, so ``_perp``
always fell back to world +Z. Drawing on a wall sent the width off the wall
horizontally, and a vertical base edge made ``cross(Z, Z)`` zero — the tool
then did nothing at all, without a word. Now the plane comes from the arrow
keys' lock, else from the face under the first click, exactly as the plain
Rectangle and the arcs do (Marco, 2026-09-10: «sospecho que no es igual»).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.i18n import tr
from core.history import AddFaceCommand
from core.axes import plane_axes  # drawing axes (#44)
from tools.base import AxisMagnet, face_the_plane, PlaneLock, Tool, ToolContext
from core.units import fmt_len, fmt_pair
from tools.protractor import DISC_PX, TICK_DEG


class RotatedRectangleTool(AxisMagnet, PlaneLock, Tool):
    #: Debajo de esto el ancho no hace rectángulo: las esquinas se funden.
    _MIN_WIDTH = 1e-6

    name = "Rotated Rect"
    # K belongs to Back Edges, as in the other modeller (issue #234);
    # there the rotated rectangle has no default key either.
    shortcut = None
    description = (
        "Draw a rectangle at any angle and in any plane: a base edge, "
        "then the width.")

    @property
    def vcb_label(self) -> str:  # type: ignore[override]
        return "Length; angle" if self.base_point is None else "Width; angle"

    def magnet_on(self) -> bool:
        # The base edge is a direction from the first corner; the height
        # is measured square off that edge, not from the corner.
        return self.base_point is None

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None   # first corner (drives plane)
        self.base_point: QVector3D | None = None     # second corner
        self.hover_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        #: Giro del ANCHO alrededor de la arista base, en grados. 0 = en el
        #: plano de trabajo (el rectángulo tumbado), 90 = perpendicular a él
        #: (de pie). Es el tercer paso clásico: su transportador gira
        #: sobre la arista base y el cuadro pide «Anchura, Ángulo».
        self.angle: float = 0.0
        #: Dirección impuesta por el bloqueo de eje, cacheada en el hover.
        self._locked: QVector3D | None = None
        #: Protractor state (#70): world radius of the fixed-screen-size
        #: disc, whether the cursor is near its rim (15° ticks), and the
        #: width angle Shift holds.
        self._disc_r = 1.0
        self._near_disc = False
        self._held_angle: float | None = None
        #: The base edge's direction Shift holds on the first protractor
        #: (#70, @pacaeiro: «the protactor could react to Shift… That way
        #: we fix the orientation and can give the distance»).
        self._held_dir: QVector3D | None = None

    # ---- Lifecycle ----------------------------------------------------------
    def on_activate(self, viewport) -> None:
        self._reset()

    def on_deactivate(self, viewport) -> None:
        self._reset()
        self.hover_point = None

    # ---- Spatial input ------------------------------------------------------
    def on_click(self, ctx: ToolContext) -> None:
        if self.start_point is None:
            # BEFORE start_point is set: the plane comes from the arrow-key
            # lock if there is one, else from the face under this very click.
            self.work_plane = self._capture_plane(ctx)
            self.start_point = ctx.world
            return
        if self.base_point is None:
            if (ctx.world - self.start_point).length() < 1e-6:
                return
            # With Shift holding the direction the corner is where the
            # preview shows it — on the held line, not under the cursor.
            self.base_point = (self.hover_point
                               if self._held_dir is not None
                               and self.hover_point is not None
                               else ctx.world)
            self._held_dir = None
            if self._perp().lengthSquared() < 1e-12:
                # The base edge is perpendicular to the drawing plane, so
                # there is no width direction left. Say it — going quiet
                # here is what reads as "the tool is broken".
                self.base_point = None
                ctx.viewport.flash_status(tr(
                    "That edge is perpendicular to the drawing plane — lock "
                    "another one with the arrow keys, or start on the face "
                    "you want to draw on"), 5000)
                ctx.viewport.update()
            return
        locked = self.locked_dir(ctx.viewport)
        width, self.angle = self._width_and_angle(self._width_cursor(ctx),
                                                  locked)
        if locked is not None and width < self._MIN_WIDTH \
                and self.hover_point is not None:
            # Con un eje bloqueado, el motor de snap todavía puede entregar en
            # el CLIC un punto fuera de ese eje (pegado a una arista del
            # suelo), y entonces el ancho proyectado se va a cero: la vista
            # previa prometía 90° y salía un rectángulo tumbado de 0,60 m
            # (Marco, 2026-09-10). Lo que el usuario aceptó al hacer clic es
            # lo que estaba viendo, así que vale el punto del hover.
            width, self.angle = self._width_and_angle(self.hover_point, locked)
        if width < self._MIN_WIDTH:
            # Sin ancho no hay rectángulo: las dos esquinas nuevas caen sobre
            # las viejas y el plan muere con «degenerate edge», revertido y
            # sin explicación. Decirlo y seguir esperando el clic bueno.
            ctx.viewport.flash_status(tr(
                "The width is zero — move away from the base edge, or type "
                "the width (and the angle after a comma)"), 4000)
            return
        corners = self._corners(width)
        if corners:
            self._commit(ctx.viewport, corners)

    def on_hover(self, ctx: ToolContext) -> None:
        self.hover_point = (self._width_cursor(ctx)
                            if self.base_point is not None else ctx.world)
        # Cacheado para la vista previa y el rótulo, que no reciben viewport.
        self._locked = self.locked_dir(ctx.viewport)
        if self.start_point is not None and self.base_point is None:
            self._disc_metrics(ctx, self.start_point, self._normal())
            if self._near_disc:
                # Near the first protractor the edge turns in 15° steps.
                d = self._in_plane(ctx.world - self.start_point)
                if d.length() > 1e-9:
                    deg = round(self._edge_angle(d) / TICK_DEG) * TICK_DEG
                    self.hover_point = (self.start_point
                                        + self._dir_at(deg) * d.length())
            if not (ctx.modifiers & Qt.ShiftModifier):
                self._held_dir = None
            else:
                d = self._in_plane(self.hover_point - self.start_point)
                if self._held_dir is None and d.length() > 1e-9:
                    self._held_dir = d.normalized()      # Shift takes it
                if self._held_dir is not None:
                    # Only the length follows the cursor now — along the
                    # held line, either way along it.
                    along = QVector3D.dotProduct(
                        ctx.world - self.start_point, self._held_dir)
                    self.hover_point = (self.start_point
                                        + self._held_dir * along)
        if self.base_point is not None:
            edge = (self.base_point - self.start_point).normalized()
            self._disc_metrics(ctx, self.base_point, edge)
            shift = bool(ctx.modifiers & Qt.ShiftModifier)
            if not shift:
                self._held_angle = None
            elif self._held_angle is None:
                self._held_angle = self.angle     # Shift holds the angle
            if self._held_angle is not None:
                self._locked = self._width_dir(self._held_angle)
            # El ángulo que se está ENSEÑANDO queda guardado. Antes solo lo
            # guardaba el tercer clic, así que escribir el ancho en el cuadro
            # —que no pasa por on_click— construía el rectángulo con el
            # ángulo viejo, es decir 0: la vista previa mostraba 90° y salía
            # tumbado (Marco, 2026-09-10, visto en la traza en vivo).
            _w, angulo = self._width_and_angle(self.hover_point, self._locked)
            if _w > self._MIN_WIDTH:
                self.angle = angulo
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        """``3`` = 3 m wide keeping the current angle; ``3;90`` = 3 m wide
        standing perpendicular to the base plane — the classic «Anchura,
        Ángulo», which is the only way to raise a rectangle whose base edge
        lies flat."""
        if self.start_point is None:
            return False
        if self.base_point is None:
            return self._on_edge_value(viewport, value)
        if self.hover_point is None:
            return False
        if isinstance(value, tuple):
            if len(value) != 2:
                return False
            width, angle = value
            if width <= 0.0:
                return False
            self.angle = _degrees(angle)
            corners = self._corners(float(width))
        else:
            if value == 0.0:
                return False
            # El LADO ya viaja dentro del ángulo que guarda el hover: 180° es
            # el lado opuesto a `_perp`, -90° es hacia abajo. Sacar además un
            # signo de la componente sobre `_perp` era negar dos veces, y el
            # rectángulo salía al lado contrario del cursor («le digo que
            # para ese lado 9 m y lo hace para el otro», Marco 2026-09-10).
            corners = self._corners(float(value))
        if corners:
            self._commit(viewport, corners)
        return True

    def on_cancel(self, viewport) -> None:
        self._reset()
        viewport.update()

    def on_key(self, viewport, key: int, modifiers) -> bool:
        return self.plane_lock_key(viewport, key)

    # ---- Preview ------------------------------------------------------------
    def rubber_band_lines(self):
        if self.start_point is None or self.hover_point is None:
            return []
        if self.base_point is None:
            # Drawing the base edge, over the first protractor (#70).
            u, v = plane_axes(self._normal())
            return ([(self.start_point, self.hover_point)]
                    + self._disc(self.start_point, u, v))
        width, angle = self._width_and_angle(self.hover_point, self._locked)
        c = self._corners(width, angle)
        # The second protractor: square to the base edge at its end, zero
        # along the plane (the rectangle lying flat), 90° standing up.
        disc = self._disc(self.base_point, self._perp(), self._normal())
        if not c:
            return [(self.start_point, self.base_point)] + disc
        return [(c[i], c[(i + 1) % 4]) for i in range(4)] + disc

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        if self.base_point is None:
            d = self.hover_point - self.start_point
            mid = (self.start_point + self.hover_point) * 0.5
            texto = fmt_len(d.length())
            flat = self._in_plane(d)
            if flat.length() > 1e-9:
                texto += f"   {self._edge_angle(flat):.0f}°"
            return (texto, mid)
        w, angle = self._width_and_angle(self.hover_point, self._locked)
        length = (self.base_point - self.start_point).length()
        c = self._corners(w, angle)
        mid = (self.start_point + c[2]) * 0.5 if c else self.base_point
        texto = fmt_pair(length, abs(w))
        if abs(angle) > 0.05:
            texto += f"   {angle:.0f}°"
        return (texto, mid)

    # ---- Internals ----------------------------------------------------------
    def _capture_plane(self, ctx: ToolContext):
        """``(point, normal)`` the rectangle will live in, or ``None`` to keep
        the legacy ground plane. An arrow-key lock is an explicit request and
        wins; otherwise the face under the click decides, which is what
        users expect without being asked."""
        locked = self.locked_work_plane(ctx.world)
        if locked is not None:
            return locked
        pick = (getattr(ctx.viewport, "pick_face_placement", None)
                or getattr(ctx.viewport, "pick_face_any", None))
        if pick is None:
            return None
        face, group = pick(ctx.screen.x(), ctx.screen.y())
        if face is None:
            return None
        from core.snap import face_plane_world
        _point, normal = face_plane_world(face, getattr(group, "xform", None))
        if normal is None or normal.lengthSquared() < 0.5:
            return None
        return QVector3D(ctx.world), QVector3D(normal)

    def _normal(self) -> QVector3D:
        return (self.work_plane[1].normalized() if self.work_plane is not None
                else QVector3D(0.0, 0.0, 1.0))

    def _perp(self) -> QVector3D:
        """In-plane unit vector perpendicular to the base edge (angle 0)."""
        e = (self.base_point - self.start_point)
        if e.length() < 1e-9:
            return QVector3D(0.0, 0.0, 0.0)
        return QVector3D.crossProduct(self._normal(),
                                      e.normalized()).normalized()

    def _width_dir(self, angle: float | None = None) -> QVector3D:
        """The width's direction for ``angle`` degrees around the base edge.

        Both ``_perp`` and the plane normal are perpendicular to the edge, so
        spinning between them sweeps every direction the width can take — and
        90° lands on the normal, which is the perpendicular rectangle
        the classic tool draws with its protractor.
        """
        import math
        perp = self._perp()
        if perp.length() < 1e-6:
            return QVector3D(0.0, 0.0, 0.0)
        a = math.radians(self.angle if angle is None else angle)
        return (perp * math.cos(a) + self._normal() * math.sin(a)).normalized()

    #: Degrees within which the angle sticks to flat / perpendicular. Only
    #: those two: they are the ones a drawing actually needs, and snapping
    #: every 15° would fight fine control on the rest.
    _ANGLE_SNAP = 3.0

    def _width_and_angle(self, cursor: QVector3D,
                         forced: QVector3D | None = None) -> tuple[float, float]:
        """``(width, angle)`` the cursor asks for, measured around the base
        edge. The component along the edge is dropped — only how far from it
        the cursor sits, and in which direction around it."""
        import math
        perp = self._perp()
        if perp.length() < 1e-6:
            return 0.0, 0.0
        edge = (self.base_point - self.start_point).normalized()
        d = cursor - self.base_point
        d = d - edge * QVector3D.dotProduct(d, edge)     # off-edge part only
        if forced is not None:
            # Proyectada sobre la dirección bloqueada: el signo sobrevive
            # (la parte negativa sale como el ángulo opuesto) y el snap deja
            # de poder sacar el ancho de su eje.
            d = forced * QVector3D.dotProduct(d, forced)
        width = d.length()
        if width < 1e-9:
            return 0.0, self.angle
        angle = math.degrees(math.atan2(
            QVector3D.dotProduct(d, self._normal()),
            QVector3D.dotProduct(d, perp)))
        if self._near_disc and forced is None:
            angle = round(angle / TICK_DEG) * TICK_DEG   # the 15° ticks
        for target in (-180.0, -90.0, 0.0, 90.0, 180.0):
            if abs(angle - target) <= self._ANGLE_SNAP:
                angle = target
                break
        return width, angle

    #: The drawing axes (core.axes): the open group's own inside it (#44).
    from core.axes import AXES as _AXES

    def locked_dir(self, viewport) -> QVector3D | None:
        """La dirección que el bloqueo de eje del viewport impone al ancho, o
        ``None`` si no hay bloqueo (o si el eje ES la arista base).

        Hace falta porque el motor de snap manda sobre el bloqueo: con el eje
        Z bloqueado y el cursor cerca de una arista del suelo, el clic se
        pegaba a esa arista y el ángulo caía a 0 — la vista previa decía 90°
        y salía un rectángulo tumbado de 0,60 m (Marco, 2026-09-10). Si el
        usuario bloqueó un eje, el ancho va por ahí y no se discute.
        """
        lock = getattr(viewport, "axis_lock", None)
        if not lock or lock not in self._AXES or self.base_point is None:
            return None
        edge = self.base_point - self.start_point
        if edge.length() < 1e-9:
            return None
        edge = edge.normalized()
        axis = QVector3D(self._AXES[lock])
        d = axis - edge * QVector3D.dotProduct(axis, edge)
        return d.normalized() if d.length() > 1e-6 else None

    def _corners(self, width: float, angle: float | None = None) -> list[QVector3D]:
        direction = self._width_dir(angle)
        if direction.length() < 1e-6:
            return []
        off = direction * width
        return [self.start_point, self.base_point,
                self.base_point + off, self.start_point + off]

    def _commit(self, viewport, corners: list[QVector3D]) -> None:
        # Same inversion as the plain Rectangle, reached by going round the
        # base edge the other way: anticlockwise landed the face backwards.
        # Stood upright on its base edge (angle 90) the loop is square to
        # the plane and face_the_plane leaves it alone.
        plano = self.work_plane[1] if self.work_plane else None
        if plano is None:
            # getattr, not a bare call: the tool must not hard-depend on a
            # private of the viewport, and the test doubles do not have it.
            leer = getattr(viewport, "_work_plane_normal", None)
            plano = leer() if callable(leer) else None
        corners = face_the_plane(corners, plano)
        segments = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        cmd = build_add_edges(
            viewport.scene, segments, detect_faces=False,
            extra=[AddFaceCommand(list(corners))])
        viewport.history.execute(cmd)
        self._reset()
        viewport.update()

    # ---- Protractors (#70) --------------------------------------------------
    #: Snaps that name a real point of the model: the width goes there.
    #: Everything else (the drawing plane, a face, an axis direction) only
    #: says where the cursor is, and is read on the protractor's plane.
    _POINT_SNAPS = frozenset({"endpoint", "midpoint", "intersection",
                              "on_edge", "close", "origin", "center",
                              "centre", "on_line"})

    def _width_cursor(self, ctx: ToolContext) -> QVector3D:
        """Where the cursor is for the width: on the second protractor's
        plane (square to the base edge, through its end), the usual reading
        of it. The snap engine answers on the drawing plane, so the width
        could only lie in it — 0° or 180° — unless the view happened to
        look along the edge (Marco, 2026-09-23: «me fuerza a 180° a no ser
        que cambie un poco la vista»)."""
        snap = getattr(ctx, "snap", None)
        if snap is not None and getattr(snap, "kind", "none") in self._POINT_SNAPS:
            return ctx.world
        ray = getattr(ctx.viewport, "_pixel_to_ray", None)
        if ray is None:
            return ctx.world
        origin, direction = ray(ctx.screen.x(), ctx.screen.y())
        if origin is None or direction is None:
            return ctx.world
        n = (self.base_point - self.start_point).normalized()
        denom = QVector3D.dotProduct(direction, n)
        if abs(denom) < 0.02:
            # The protractor seen edge-on: its plane gives no point, the
            # drawing plane's answer is the best there is.
            return ctx.world
        t = QVector3D.dotProduct(self.base_point - origin, n) / denom
        if t <= 0.0:
            return ctx.world
        return origin + direction * t

    def _in_plane(self, d: QVector3D) -> QVector3D:
        n = self._normal()
        return d - n * QVector3D.dotProduct(d, n)

    def _edge_angle(self, d: QVector3D) -> float:
        """Direction of the base edge in the plane, degrees from its first
        axis (0..360) — what the first protractor reads."""
        import math
        u, v = plane_axes(self._normal())
        deg = math.degrees(math.atan2(QVector3D.dotProduct(d, v),
                                      QVector3D.dotProduct(d, u)))
        return deg % 360.0

    def _dir_at(self, deg: float) -> QVector3D:
        import math
        u, v = plane_axes(self._normal())
        a = math.radians(deg)
        return (u * math.cos(a) + v * math.sin(a)).normalized()

    def _on_edge_value(self, viewport, value) -> bool:
        """The base edge typed: ``length`` along the cursor's direction, or
        ``length;angle`` with the angle read on the first protractor."""
        if isinstance(value, tuple):
            if len(value) != 2:
                return False
            length, angle = float(value[0]), _degrees(value[1])
            direction = self._dir_at(angle)
        else:
            length = float(value)
            d = (self.hover_point - self.start_point
                 if self.hover_point is not None else QVector3D())
            direction = (d.normalized() if d.length() > 1e-9
                         else self._dir_at(0.0))
        if length == 0.0:
            return False
        if length < 0.0:
            length, direction = -length, -direction
        self.base_point = self.start_point + direction * length
        if self._perp().lengthSquared() < 1e-12:
            self.base_point = None
            return False
        viewport.update()
        return True

    def _disc_metrics(self, ctx: ToolContext, centre: QVector3D,
                      axis: QVector3D) -> None:
        """Fixed screen size for the disc, and whether the cursor is near
        enough to snap to its ticks — the Protractor tool's rule."""
        import math
        w2p = getattr(ctx.viewport, "_world_to_pixel", None)
        self._near_disc = False
        if w2p is None:
            return
        u, _v = plane_axes(axis)
        p0, p1 = w2p(centre), w2p(centre + u)
        if p0 is None or p1 is None:
            return
        px = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if px > 1e-6:
            self._disc_r = DISC_PX / px
        self._near_disc = (math.hypot(ctx.screen.x() - p0[0],
                                      ctx.screen.y() - p0[1])
                           <= DISC_PX * 1.25)

    def _disc(self, centre: QVector3D, u: QVector3D, v: QVector3D) -> list:
        """A protractor disc in the plane (u, v): rim and ticks every 15°,
        long ones every 90°, zero on ``u``."""
        import math
        if u.length() < 1e-9 or v.length() < 1e-9:
            return []
        r = self._disc_r

        def rim(t: float, k: float = 1.0) -> QVector3D:
            return centre + (u * math.cos(t) + v * math.sin(t)) * (r * k)

        n = 48
        pts = [rim(2 * math.pi * k / n) for k in range(n)]
        segs = [(pts[k], pts[(k + 1) % n]) for k in range(n)]
        for k in range(int(360 / TICK_DEG)):
            t = math.radians(k * TICK_DEG)
            inner = 0.75 if k * TICK_DEG % 90 == 0 else 0.86
            segs.append((rim(t, inner), rim(t)))
        return segs

    def _reset(self) -> None:
        self.start_point = None
        self.base_point = None
        self.work_plane = None
        self.clear_plane_lock()
        self.angle = 0.0
        self._locked = None
        self._near_disc = False
        self._held_angle = None
        self._held_dir = None


def _degrees(value) -> float:
    """An angle typed in the VCB. The parser reads every bare field as a
    LENGTH in the document's unit, so in a millimetre model «90» arrived as
    0.09 — undo that scale; an angle has no unit."""
    from core.units import bare_number_scale
    scale = bare_number_scale()
    return float(value) / scale if scale else float(value)
