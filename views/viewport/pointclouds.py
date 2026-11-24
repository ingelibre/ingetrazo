# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Point clouds in the viewport: one GPU buffer per cloud, drawn as points.

The cloud is reference content (``georef.pointcloud``), drawn with the other
reference layers before the model, depth-tested both ways: a wall you model
hides the scan behind it and the scan hides what is behind it. The section
cut applies, so slicing a scanned building at 1 m shows its floor plan.
"""
from __future__ import annotations

from PySide6.QtGui import QVector3D
from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader,
                              QOpenGLShaderProgram, QOpenGLVertexArrayObject)

from views.viewport._support import GL_CLIP_DISTANCE0, GL_FLOAT, SHADER_DIR

GL_POINTS = 0x0000
GL_UNSIGNED_BYTE = 0x1401
GL_PROGRAM_POINT_SIZE = 0x8642

#: Pixels around the cursor in which a cloud point is snapped to.
SNAP_RADIUS_PX = 8.0


class PointCloudMixin:
    """Point clouds: upload, draw and the point under the cursor."""

    _cloud_program = None
    _cloud_gpu = None

    def _visible_point_clouds(self) -> list:
        scene = self.scene
        return [c for c in getattr(scene, "point_clouds", None) or ()
                if getattr(c, "visible", False) and c.point_count
                and scene.entity_visible(c)]

    def _point_clouds_showing(self) -> bool:
        return bool(self._visible_point_clouds())

    # ---- GPU ----------------------------------------------------------------
    def _ensure_cloud_program(self):
        if self._cloud_program is None:
            prog = QOpenGLShaderProgram(self)
            ok_v = prog.addShaderFromSourceFile(
                QOpenGLShader.Vertex, str(SHADER_DIR / "points.vert"))
            ok_f = prog.addShaderFromSourceFile(
                QOpenGLShader.Fragment, str(SHADER_DIR / "points.frag"))
            if not (ok_v and ok_f and prog.link()):
                raise RuntimeError(
                    "point shader compile/link failed:\n" + prog.log())
            self._cloud_program = prog
            self._cloud_locs = {
                "mvp": prog.uniformLocation("u_mvp"),
                "size": prog.uniformLocation("u_point_size"),
                "round": prog.uniformLocation("u_round"),
                "count": prog.uniformLocation("u_clip_count"),
                "planes": [prog.uniformLocation(f"u_clip_planes[{i}]")
                           for i in range(7)],
            }
        return self._cloud_program

    def _cloud_entry(self, cloud):
        """``(vao, vbo, count)`` for ``cloud``, uploading when its points or
        colours changed since the last frame. Needs a current context."""
        import numpy as np

        if self._cloud_gpu is None:
            self._cloud_gpu = {}
        key = (cloud.revision, cloud.effective_mode(), cloud.point_count)
        entry = self._cloud_gpu.get(id(cloud))
        if entry is not None and entry["cloud"] is cloud \
                and entry["key"] == key:
            return entry
        if entry is None or entry["cloud"] is not cloud:
            if entry is not None:
                self._destroy_cloud_entry(entry)
            vao = QOpenGLVertexArrayObject(self)
            vao.create()
            vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            vbo.setUsagePattern(QOpenGLBuffer.StaticDraw)
            vbo.create()
            entry = {"vao": vao, "vbo": vbo, "cloud": cloud}
            self._cloud_gpu[id(cloud)] = entry
        # 16 bytes a point: position (3 floats) + RGBA (4 normalised bytes).
        n = cloud.point_count
        packed = np.empty(n, dtype=[("p", "<f4", 3), ("c", "u1", 4)])
        packed["p"] = cloud.positions
        packed["c"][:, :3] = cloud.display_colors()
        packed["c"][:, 3] = 255
        raw = packed.tobytes()
        vao, vbo = entry["vao"], entry["vbo"]
        vao.bind()
        vbo.bind()
        vbo.allocate(raw, len(raw))
        prog = self._ensure_cloud_program()
        prog.bind()
        prog.enableAttributeArray(0)
        prog.setAttributeBuffer(0, GL_FLOAT, 0, 3, 16)
        prog.enableAttributeArray(2)
        prog.setAttributeBuffer(2, GL_UNSIGNED_BYTE, 12, 4, 16)
        vbo.release()
        vao.release()
        entry["key"] = key
        entry["count"] = n
        return entry

    @staticmethod
    def _destroy_cloud_entry(entry) -> None:
        try:
            entry["vbo"].destroy()
            entry["vao"].destroy()
        except RuntimeError:
            pass                        # its context is already gone

    def _sweep_cloud_gpu(self, keep) -> None:
        """Free the buffers of clouds no longer drawn (removed, undone, or
        the previous document's)."""
        if not self._cloud_gpu:
            return
        alive = {id(c): c for c in keep}
        for key in list(self._cloud_gpu):
            entry = self._cloud_gpu[key]
            if alive.get(key) is not entry["cloud"]:
                self._destroy_cloud_entry(entry)
                del self._cloud_gpu[key]

    # ---- Frame --------------------------------------------------------------
    def _render_point_clouds(self, mvp) -> None:
        clouds = self._visible_point_clouds()
        self._sweep_cloud_gpu(getattr(self.scene, "point_clouds", ()) or ())
        if not clouds:
            return
        prog = self._ensure_cloud_program()
        locs = self._cloud_locs
        gl = self._gl
        vecs = getattr(self, "_clip_vecs", None) or []
        try:
            dpr = float(self.devicePixelRatioF())
        except (AttributeError, RuntimeError):
            dpr = 1.0
        gl.glEnable(GL_PROGRAM_POINT_SIZE)
        for i in range(len(vecs)):
            gl.glEnable(GL_CLIP_DISTANCE0 + i)
        try:
            for cloud in clouds:
                entry = self._cloud_entry(cloud)
                prog.bind()
                prog.setUniformValue(locs["mvp"], mvp)
                for i, v in enumerate(vecs):
                    prog.setUniformValue(locs["planes"][i], v)
                prog.setUniformValue(locs["count"], len(vecs))
                size = max(1.0, float(cloud.point_size)) * dpr
                prog.setUniformValue1f(locs["size"], size)
                prog.setUniformValue(locs["round"], 1 if size >= 3.0 else 0)
                entry["vao"].bind()
                gl.glDrawArrays(GL_POINTS, 0, entry["count"])
                entry["vao"].release()
        finally:
            for i in range(len(vecs)):
                gl.glDisable(GL_CLIP_DISTANCE0 + i)
            gl.glDisable(GL_PROGRAM_POINT_SIZE)
            # The rest of the frame draws with the main program.
            self._program.bind()

    # ---- Snap ---------------------------------------------------------------
    def _point_cloud_snap(self, px: float, py: float):
        """The cloud point under the cursor as a ``QVector3D``, or ``None``.

        Points a section cut hides are left out, the way the cut leaves
        hidden edges out of the snap."""
        clouds = self._visible_point_clouds()
        if not clouds:
            return None
        import numpy as np
        from core.section import cut_planes
        from georef.pointcloud import nearest_screen_point

        planes = cut_planes(self.scene)
        normals = np.array([(p.normal.x(), p.normal.y(), p.normal.z())
                            for p in planes], dtype=np.float64)
        origins = np.array([(p.point.x(), p.point.y(), p.point.z())
                            for p in planes], dtype=np.float64)

        def kept_by_cut(pts):
            side = ((pts[:, None, :] - origins[None]) * normals[None]
                    ).sum(axis=2)
            return (side <= 1e-6).all(axis=1)

        keep = kept_by_cut if planes else None

        mvp = self._np_mvp()
        w, h = float(self.width()), float(self.height())
        best = None
        for cloud in clouds:
            i = nearest_screen_point(cloud.positions, mvp, w, h, px, py,
                                     SNAP_RADIUS_PX, keep=keep)
            if i is None:
                continue
            p = cloud.positions[i]
            point = QVector3D(float(p[0]), float(p[1]), float(p[2]))
            pix = self._world_to_pixel(point)
            if pix is None:
                continue
            d = (pix[0] - px) ** 2 + (pix[1] - py) ** 2
            if best is None or d < best[0]:
                best = (d, point)
        return None if best is None else best[1]
