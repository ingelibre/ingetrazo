# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Rotated Rectangle tool: a rectangle at any angle IN ANY PLANE.

Three clicks, SketchUp-style:
1. first corner — which also captures the plane,
2. second corner — sets the base edge's **direction and length** (the rotation),
3. move to set the perpendicular width, click to commit.

The width can also be typed in the VCB after the base edge is set.

The plane is the whole point of the tool and it used to be missing:
``work_plane`` was declared, reset and read, but never assigned, so ``_perp``
always fell back to world +Z. Drawing on a wall sent the width off the wall
horizontally, and a vertical base edge made ``cross(Z, Z)`` zero — the tool
then did nothing at all, without a word. Now the plane comes from the arrow
keys' lock, else from the face under the first click, exactly as the plain
Rectangle and the arcs do (Marco, 2026-09-10: «sospecho que no es igual»).
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D

from core.edits import build_add_edges
from core.i18n import tr
from core.history import AddFaceCommand
from core.triangulate import plane_axes
from tools.base import PlaneLock, Tool, ToolContext


class RotatedRectangleTool(PlaneLock, Tool):
    #: Debajo de esto el ancho no hace rectángulo: las esquinas se funden.
    _MIN_WIDTH = 1e-6

    name = "Rotated Rect"
    shortcut = "K"
    vcb_label = "Width; angle"

    def __init__(self) -> None:
        self.start_point: QVector3D | None = None   # first corner (drives plane)
        self.base_point: QVector3D | None = None     # second corner
        self.hover_point: QVector3D | None = None
        self.work_plane: tuple[QVector3D, QVector3D] | None = None
        #: Giro del ANCHO alrededor de la arista base, en grados. 0 = en el
        #: plano de trabajo (el rectángulo tumbado), 90 = perpendicular a él
        #: (de pie). Es el tercer paso de SketchUp: su transportador gira
        #: sobre la arista base y el cuadro pide «Anchura, Ángulo».
        self.angle: float = 0.0
        #: Dirección impuesta por el bloqueo de eje, cacheada en el hover.
        self._locked: QVector3D | None = None

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
            self.base_point = ctx.world
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
        width, self.angle = self._width_and_angle(ctx.world, locked)
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
        self.hover_point = ctx.world
        # Cacheado para la vista previa y el rótulo, que no reciben viewport.
        self._locked = self.locked_dir(ctx.viewport)
        if self.base_point is not None:
            # El ángulo que se está ENSEÑANDO queda guardado. Antes solo lo
            # guardaba el tercer clic, así que escribir el ancho en el cuadro
            # —que no pasa por on_click— construía el rectángulo con el
            # ángulo viejo, es decir 0: la vista previa mostraba 90° y salía
            # tumbado (Marco, 2026-09-10, visto en la traza en vivo).
            _w, angulo = self._width_and_angle(ctx.world, self._locked)
            if _w > self._MIN_WIDTH:
                self.angle = angulo
        ctx.viewport.update()

    def on_value(self, viewport, value) -> bool:
        """``3`` = 3 m wide keeping the current angle; ``3;90`` = 3 m wide
        standing perpendicular to the base plane — SketchUp's «Anchura,
        Ángulo», which is the only way to raise a rectangle whose base edge
        lies flat."""
        if self.base_point is None or self.hover_point is None:
            return False
        if isinstance(value, tuple):
            if len(value) != 2:
                return False
            width, angle = value
            if width <= 0.0:
                return False
            self.angle = float(angle)
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
            return [(self.start_point, self.hover_point)]   # drawing the base
        width, angle = self._width_and_angle(self.hover_point, self._locked)
        c = self._corners(width, angle)
        if not c:
            return [(self.start_point, self.base_point)]
        return [(c[i], c[(i + 1) % 4]) for i in range(4)]

    def value_label(self):
        if self.start_point is None or self.hover_point is None:
            return None
        if self.base_point is None:
            length = (self.hover_point - self.start_point).length()
            mid = (self.start_point + self.hover_point) * 0.5
            return (f"{length:.2f} m", mid)
        w, angle = self._width_and_angle(self.hover_point, self._locked)
        length = (self.base_point - self.start_point).length()
        c = self._corners(w, angle)
        mid = (self.start_point + c[2]) * 0.5 if c else self.base_point
        texto = f"{length:.2f} × {abs(w):.2f} m"
        if abs(angle) > 0.05:
            texto += f"   {angle:.0f}°"
        return (texto, mid)

    # ---- Internals ----------------------------------------------------------
    def _capture_plane(self, ctx: ToolContext):
        """``(point, normal)`` the rectangle will live in, or ``None`` to keep
        the legacy ground plane. An arrow-key lock is an explicit request and
        wins; otherwise the face under the click decides, which is what
        SketchUp does without being asked."""
        locked = self.locked_work_plane(ctx.world)
        if locked is not None:
            return locked
        pick = getattr(ctx.viewport, "pick_face_any", None)
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
        SketchUp draws with its protractor.
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
        for target in (-180.0, -90.0, 0.0, 90.0, 180.0):
            if abs(angle - target) <= self._ANGLE_SNAP:
                angle = target
                break
        return width, angle

    _AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}

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
        axis = QVector3D(*self._AXES[lock])
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
        segments = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
        cmd = build_add_edges(
            viewport.scene, segments, detect_faces=False,
            extra=[AddFaceCommand(list(corners))])
        viewport.history.execute(cmd)
        self._reset()
        viewport.update()

    def _reset(self) -> None:
        self.start_point = None
        self.base_point = None
        self.work_plane = None
        self.plane_lock = None
        self.angle = 0.0
        self._locked = None
