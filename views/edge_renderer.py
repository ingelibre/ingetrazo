# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Pixel-sized edge effects using quads instead of driver-dependent wide lines."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector2D, QVector3D, QVector4D
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram
from PySide6.QtOpenGL import QOpenGLVertexArrayObject

from core.edge_style import EDGE_FLOATS, AXIS_COLORS, edge_vertices, marker_candidates
from core.group import effective_material
from core.layers import DEFAULT_LAYER
from core.materials import material_sig
from core.paths import app_root
from core.style import PROFILE_CAPS, ENDPOINT_TYPES, xray_enabled

GL_FLOAT, GL_LINES = 0x1406, 0x0001
GL_LEQUAL, GL_GREATER = 0x0203, 0x0204
GL_DEPTH_BUFFER_BIT, GL_CULL_FACE = 0x0100, 0x0B44


class EdgeRenderer:
    """Keep one geometry buffer per prototype and instance matrices per batch."""

    def __init__(self, viewport):
        self.viewport = viewport
        self.program = QOpenGLShaderProgram(viewport)
        directory = app_root() / "resources" / "shaders"
        for stage, filename in ((QOpenGLShader.Vertex, "edges.vert"),
                                (QOpenGLShader.Geometry, "edges.geom"),
                                (QOpenGLShader.Fragment, "edges.frag")):
            if not self.program.addShaderFromSourceFile(stage, str(directory / filename)):
                raise RuntimeError(self.program.log())
        if not self.program.link():
            raise RuntimeError(self.program.log())
        self.locations = {}
        self.geometry = {}
        self.batches = []
        self.batch_key = None
        self.marker_batches = []
        self.marker_key = None

    def loc(self, name):
        if name not in self.locations:
            self.locations[name] = self.program.uniformLocation(name)
        return self.locations[name]

    def integer(self, name, value):
        self.program.setUniformValue(self.loc(name), int(value))

    def number(self, name, value):
        self.program.setUniformValue1f(self.loc(name), float(value))

    def vector(self, name, value):
        self.program.setUniformValue(self.loc(name), QVector3D(*map(float, value)))

    @staticmethod
    def _buffer(raw, usage):
        buffer = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        buffer.setUsagePattern(usage)
        buffer.create()
        buffer.bind()
        buffer.allocate(raw or b"\0" * 4, max(4, len(raw)))
        buffer.release()
        return buffer

    def _make_batch(self, geometry, matrices, fade):
        vao = QOpenGLVertexArrayObject(self.viewport)
        vao.create()
        vao.bind()
        geometry["vbo"].bind()
        for location, offset, size in ((0, 0, 3), (1, 3, 3), (2, 6, 3),
                                       (3, 9, 3), (4, 12, 3), (5, 15, 4), (6, 19, 4)):
            self.program.enableAttributeArray(location)
            self.program.setAttributeBuffer(location, GL_FLOAT, offset * 4,
                                              size, EDGE_FLOATS * 4)
        geometry["vbo"].release()
        matrix_buffer = self._buffer(np.asarray(matrices, dtype=np.float32).tobytes(),
                                      QOpenGLBuffer.DynamicDraw)
        matrix_buffer.bind()
        extra = self.viewport.context().extraFunctions()
        for index in range(4):
            location = 7 + index
            self.program.enableAttributeArray(location)
            self.program.setAttributeBuffer(location, GL_FLOAT, index * 16, 4, 64)
            extra.glVertexAttribDivisor(location, 1)
        matrix_buffer.release()
        vao.release()
        # Eight local bounds corners per instance suffice for a stable scene
        # depth interval. Marker eligibility is evaluated only on view changes.
        corners = geometry["corners"]
        transforms = np.asarray(matrices).reshape((-1, 4, 4)).transpose(0, 2, 1)
        world = np.einsum("nij,kj->nki", transforms, corners)[..., :3].reshape((-1, 3))
        return {"vao": vao, "matrices": matrix_buffer, "instances": len(matrices),
                "corners": world, "transforms": transforms, "source": geometry,
                "count": geometry["count"], "fade": fade}

    def _clear_batches(self):
        for batch in self.batches:
            batch["vao"].destroy()
            batch["vao"].deleteLater()
            batch["matrices"].destroy()
        self.batches = []
        self._clear_markers()

    def _clear_markers(self):
        for batch in self.marker_batches:
            batch["vao"].destroy()
            batch["vao"].deleteLater()
            batch["matrices"].destroy()
            batch["source"]["vbo"].destroy()
        self.marker_batches = []
        self.marker_key = None

    def clear(self):
        """Release a document's buffers with the owning GL context current."""
        self._clear_batches()
        for geometry in self.geometry.values():
            geometry["vbo"].destroy()
        self.geometry.clear()
        self.batch_key = None

    def forget_context(self):
        """Drop Qt wrappers after their GL context has already gone away."""
        for batch in self.batches + self.marker_batches:
            batch["vao"].deleteLater()
        self.program.deleteLater()
        self.batches = []
        self.marker_batches = []
        self.marker_key = None
        self.geometry.clear()
        self.batch_key = None

    def _sync(self):
        vp, scene = self.viewport, self.viewport.scene
        layers = tuple((layer.name, layer.visible, layer.linetype) for layer in scene.layers)
        epoch = vp._placements_epoch()
        key = (id(scene), scene.version, epoch, layers,
               id(scene.edit_group), vp._edit_rest_mode, vp.edit_rest_fade,
               tuple(sorted(getattr(vp, "_preview_groups", None) or ())))
        if key == self.batch_key:
            return
        self._clear_batches()
        self.batch_key = key
        grouped = {}
        identity = list(QMatrix4x4().data())

        def add(mesh, paint, layer, group, fade):
            signature = (id(mesh), material_sig(paint), layer, fade)
            bucket = grouped.setdefault(signature, [mesh, paint, layer, fade, []])
            matrix = getattr(group, "xform", None)
            bucket[4].append(list(matrix.data()) if matrix is not None else identity)

        mode = vp._edit_rest_mode if scene.edit_group is not None else None
        if mode != "hide":
            add(scene.loose_mesh, None, None, None, vp.edit_rest_fade if mode == "fade" else 0.0)
        preview = getattr(vp, "_preview_groups", None) or ()
        for group in vp._placements():
            if (id(group) in preview or getattr(group, "billboard", False)
                    or not scene.entity_visible(group)):
                continue
            outside = vp._draws_in_edit_context(group)
            if outside and mode == "hide":
                continue
            layer = group.layer
            if not layer or layer == DEFAULT_LAYER:
                owner = getattr(group, "owner", None)
                layer = getattr(owner, "layer", None) or layer
            add(group.mesh, effective_material(group), layer, group,
                vp.edit_rest_fade if outside and mode == "fade" else 0.0)
        live = set()
        for mesh, paint, layer, fade, matrices in grouped.values():
            cache_key = (id(mesh), getattr(mesh, "_mut_serial", 0),
                         getattr(scene, "content_version", scene.version),
                         material_sig(paint), layer, layers)
            geometry = self.geometry.get(cache_key)
            if geometry is None:
                data = edge_vertices(mesh, scene, paint, layer, vp._texture_avg_color)
                geometry = {"vbo": self._buffer(data.tobytes(), QOpenGLBuffer.StaticDraw),
                            "count": len(data), "mesh": mesh,
                            "paint": paint, "layer": layer, "marker_data": None}
                lo = data[:, :3].min(axis=0) if len(data) else np.zeros(3)
                hi = data[:, :3].max(axis=0) if len(data) else lo
                geometry["corners"] = np.array([
                    (x, y, z, 1) for x in (lo[0], hi[0])
                    for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
                self.geometry[cache_key] = geometry
            live.add(cache_key)
            if geometry["count"]:
                self.batches.append(self._make_batch(geometry, matrices, fade))
        for old in list(self.geometry.keys() - live):
            self.geometry.pop(old)["vbo"].destroy()

    def _sync_markers(self, mvp, width, height, style, mode):
        """One screen-aligned marker per world vertex, across all placements.

        Cache this stream until the camera, geometry or edge visibility changes.
        The original instanced edge buffers remain untouched.
        """
        from core import axes
        vp = self.viewport
        basis = np.asarray([axes.as_tuple(axis) for axis in ("x", "y", "z")])
        key = (tuple(mvp.data()), width, height, style.edges, style.profiles,
               mode, style.edge_color_mode, tuple(style.edge_color), tuple(basis.flat))
        if key == self.marker_key:
            return
        self._clear_markers()
        self.marker_key = key
        eye = np.asarray(vp.camera.eye().toTuple())
        forward = np.asarray(vp.camera.forward().toTuple())
        streams, fades = [], []
        # Prefer an actively edited edge to a faded neighbour at the same point.
        for batch in sorted(self.batches, key=lambda b: b["fade"]):
            source = batch["source"]
            if source["marker_data"] is None:
                source["marker_data"] = edge_vertices(
                    source["mesh"], vp.scene, source["paint"], source["layer"], vp._texture_avg_color)
            for transform in batch["transforms"]:
                data = marker_candidates(source["marker_data"], transform, style, mode,
                                         eye, forward, vp.camera.perspective)
                if not len(data):
                    continue
                # A segment projected to a point has no visible stroke to mark.
                matrix = np.asarray(mvp.data()).reshape(4, 4).T
                clip = np.c_[data[:, :3], np.ones(len(data))] @ matrix.T
                ndc = clip[:, :2] / np.maximum(clip[:, 3:4], 1e-7)
                visible = np.linalg.norm(np.diff(ndc.reshape((-1, 2, 2)), axis=1)[:, 0], axis=1) > 1e-7
                data = data.reshape((-1, 2, EDGE_FLOATS))[visible].reshape((-1, EDGE_FLOATS))
                if style.edge_color_mode == "axis" and len(data):
                    direction = np.diff(data[:, :3].reshape((-1, 2, 3)), axis=1)[:, 0]
                    direction /= np.maximum(np.linalg.norm(direction, axis=1)[:, None], 1e-12)
                    dots = np.abs(direction @ basis.T)
                    color = np.broadcast_to(style.edge_color, (len(direction), 3)).copy()
                    aligned = dots.max(axis=1) >= 0.999999
                    color[aligned] = np.asarray(AXIS_COLORS)[dots[aligned].argmax(axis=1)]
                    data[:, 3:6] = np.repeat(color, 2, axis=0)
                streams.append(data)
                fades.append(np.full(len(data), batch["fade"]))
        if not streams:
            return
        data = np.concatenate(streams)
        fade = np.concatenate(fades)
        _points, first, inverse_ids = np.unique(data[:, :3], axis=0, return_index=True, return_inverse=True)
        if not len(first):
            return
        # Bound every incident face's slope. The single marker must cover the
        # junction's faces as reliably as the former overlapping edge quads.
        inverse, _ok = mvp.inverted()
        plane_matrix = np.asarray(inverse.data()).reshape(4, 4).T
        slopes = np.zeros((len(data), 2))
        for column in (6, 9):
            normals = data[:, column:column + 3]
            planes = np.c_[normals, -np.sum(normals * data[:, :3], axis=1)] @ plane_matrix
            valid = np.abs(planes[:, 2]) > 1e-8
            slopes[valid] = np.maximum(slopes[valid], np.abs(
                planes[valid, :2] / planes[valid, 2:3]) * (2.0 / np.array([width, height])))
        bounds = np.zeros((len(first), 2))
        np.maximum.at(bounds, inverse_ids, slopes)
        markers = data[first].copy()
        markers[:, 15:17] = bounds
        identity = list(QMatrix4x4().data())
        for opacity in np.unique(fade[first]):
            # A line invocation whose two inputs coincide emits one marker quad.
            packed = np.repeat(markers[fade[first] == opacity], 2, axis=0)
            geometry = {"vbo": self._buffer(packed.tobytes(), QOpenGLBuffer.StaticDraw),
                        "count": len(packed), "corners": np.zeros((1, 4))}
            self.marker_batches.append(self._make_batch(geometry, [identity], float(opacity)))

    def draw(self, mvp, width, height, style, mode, fade_color=None):
        """Draw visible edges and optional hidden edges, restoring the main program."""
        vp = self.viewport
        gl = vp._gl
        # The original X-ray face pass leaves depth empty; lay it down just
        # for comparing visible and hidden strokes, as the regular edge pass.
        xray = xray_enabled(style) and mode != "wireframe"
        if xray:
            vp._xray_face_depth()
        self.program.bind()
        try:
            self._sync()
            self.program.setUniformValue(self.loc("u_mvp"), mvp)
            inverse, _ok = mvp.inverted()
            self.program.setUniformValue(self.loc("u_plane_to_clip"), inverse.transposed())
            self.program.setUniformValue(self.loc("u_viewport"),
                                           QVector2D(float(width), float(height)))
            self.vector("u_eye", vp.camera.eye().toTuple())
            self.vector("u_forward", vp.camera.forward().toTuple())
            self.integer("u_perspective", vp.camera.perspective)
            self.integer("u_edges", style.edges or mode == "wireframe")
            self.integer("u_profiles", style.profiles)
            scale = (max(1, vp._export_edge_px) if vp._export_size is not None
                     else max(1.0, vp.devicePixelRatioF()))
            profile_width = style.profile_width
            if vp._export_size is not None:
                profile_width = max(profile_width, getattr(vp, "_export_profile_px", 1) / scale)
            self.number("u_profile_width", profile_width)
            self.integer("u_profile_cap", PROFILE_CAPS.index(style.profile_cap))
            self.number("u_depth_width", style.depth_cue_width if style.depth_cue else 1)
            near, far = 0.0, 1.0
            if style.depth_cue:
                forward = np.asarray(vp.camera.forward().toTuple())
                eye = np.asarray(vp.camera.eye().toTuple())
                depths = [(batch["corners"] - eye) @ forward for batch in self.batches]
                near = max(0.0, min((d.min() for d in depths), default=0.0))
                far = max(near + 1e-4, max((d.max() for d in depths), default=near))
            self.number("u_depth_near", near)
            self.number("u_depth_range", far - near)
            self.number("u_extension", style.extension_length if style.extensions else 0)
            self.number("u_endpoint", style.endpoint_length if style.endpoints else 0)
            self.integer("u_endpoint_type", ENDPOINT_TYPES.index(style.endpoint_type))
            self.number("u_endpoint_size", style.endpoint_size)
            self.integer("u_dashes", style.dashes)
            self.integer("u_color_mode", {"same": 0, "material": 1, "axis": 2}[style.edge_color_mode])
            self.vector("u_color", style.edge_color)
            self.vector("u_background", style.background)
            from core import axes
            axes.sync(vp.scene.drawing_frame)
            for index, axis in enumerate(("x", "y", "z")):
                self.vector(f"u_axis{index}", axes.as_tuple(axis))
            markers = style.endpoints and style.endpoint_type != "default"
            if markers:
                self._sync_markers(mvp, width, height, style, mode)
            self.vector("u_fade_color", style.background if fade_color is None else fade_color)
            plane = getattr(vp, "_clip_vec", None)
            self.integer("u_clip_enable", plane is not None)
            self.program.setUniformValue(self.loc("u_clip_plane"),
                                           plane if plane is not None else QVector4D())
            self.number("u_scale", scale)
            gl.glDisable(GL_CULL_FACE)
            # Coverage antialiasing must preserve an opaque framebuffer's
            # alpha. Squaring coverage in the alpha channel makes exported
            # pixels look translucent and corrupts premultiplied QImages.
            gl.glBlendFuncSeparate(0x0302, 0x0303, 1, 0x0303)
            # Expanded strokes share depth with the faces beneath them. They
            # test against model depth but must not occlude neighboring strokes.
            gl.glDepthMask(False)
            extra = vp.context().extraFunctions()
            passes = [(False, 0.0)]
            if xray or (style.back_edges and mode != "wireframe"):
                passes.insert(0, (True, 0.6 if xray else 0.0))
            streams = [(False, self.batches)]
            if markers:
                streams.append((True, self.marker_batches))
            for marker_pass, batches in streams:
                self.integer("u_marker_pass", marker_pass)
                for hidden, hidden_fade in passes:
                    self.integer("u_hidden", hidden)
                    self.number("u_hidden_fade", hidden_fade)
                    gl.glDepthFunc(GL_GREATER if hidden else GL_LEQUAL)
                    for batch in batches:
                        self.number("u_fade", batch["fade"])
                        batch["vao"].bind()
                        extra.glDrawArraysInstanced(GL_LINES, 0, batch["count"], batch["instances"])
                        batch["vao"].release()
        finally:
            gl.glBlendFunc(0x0302, 0x0303)
            gl.glDepthFunc(GL_LEQUAL)
            gl.glDepthMask(True)
            if xray:
                gl.glClear(GL_DEPTH_BUFFER_BIT)
            vp._program.bind()
