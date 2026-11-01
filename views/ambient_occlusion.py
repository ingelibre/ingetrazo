# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Ambient occlusion of the 3D view (#954).

The soft darkening where surfaces meet: a wall and its slab, a beam and
its column, the foot of a cabinet. It is worked out on the picture the
face passes just drew, from its depth alone, so it never touches the model:

1. the scene's depth (multisampled) is resolved into a depth texture;
2. ``ao.frag`` measures, at half size, how much of each point's hemisphere
   the nearby surfaces take;
3. ``ao_blur.frag`` smooths that noise without crossing silhouettes;
4. ``ao_apply.frag`` multiplies it onto the scene, before the edges,
   dimensions, text and guides are drawn — those stay as they were.

Switched on per style in the Styles panel (off in every
preset). The environment can force it, for tests and benchmarks:
``INGETRAZO_AO=1`` (or 0 to force it off), with
``INGETRAZO_AO_RADIUS`` (model units, default 0.5), ``INGETRAZO_AO_INTENSITY``
(0–2, default 1.0) and ``INGETRAZO_AO_SAMPLES`` (default 16);
``INGETRAZO_AO_DEBUG=1`` shows the bare map instead of the picture.
"""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtGui import QMatrix4x4, QVector2D
from PySide6.QtOpenGL import (QOpenGLFramebufferObject, QOpenGLShader,
                              QOpenGLShaderProgram, QOpenGLTexture,
                              QOpenGLVertexArrayObject)

GL_TEXTURE_2D = 0x0DE1
GL_TEXTURE0 = 0x84C0
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_LINEAR = 0x2601
GL_NEAREST = 0x2600
GL_FRAMEBUFFER = 0x8D40
GL_READ_FRAMEBUFFER = 0x8CA8
GL_DRAW_FRAMEBUFFER = 0x8CA9
GL_DEPTH_STENCIL_ATTACHMENT = 0x821A
GL_FRAMEBUFFER_COMPLETE = 0x8CD5
GL_DEPTH_BUFFER_BIT = 0x00000100
GL_COLOR_BUFFER_BIT = 0x00004000
GL_DEPTH_TEST = 0x0B71
GL_BLEND = 0x0BE2
GL_ZERO = 0
GL_SRC_COLOR = 0x0300
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_TRIANGLES = 0x0004
GL_NO_ERROR = 0
GL_STENCIL_TEST = 0x0B90
GL_NOTEQUAL = 0x0205
GL_ALWAYS = 0x0207
GL_KEEP = 0x1E00
#: The stencil bit the foliage cutouts leave (viewport.AO_FOLIAGE_BIT).
FOLIAGE_BIT = 0x80

#: Refused depth resolves in a row before the pass gives up for the session.
REFUSALS_TO_GIVE_UP = 3

#: Texture units the passes use — clear of the face passes' 0 (images) and
#: 1 (the sun's shadow map).
_UNIT_DEPTH = 4
_UNIT_AO = 5
_UNIT_COLOR = 6


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def settings_from_env() -> Optional[dict]:
    """The settings forced from the environment, or None when it is off."""
    if os.environ.get("INGETRAZO_AO", "0") in ("", "0"):
        return None
    return {"radius": max(_env_float("INGETRAZO_AO_RADIUS", 0.5), 1e-4),
            "intensity": _env_float("INGETRAZO_AO_INTENSITY", 1.0),
            "samples": int(max(4, min(64, _env_float("INGETRAZO_AO_SAMPLES",
                                                      16))))}


def settings_for(style) -> Optional[dict]:
    """What this frame draws with: the style's switch and values (Styles
    panel), unless ``INGETRAZO_AO`` is set — 1 forces it on with the
    environment's values, 0 forces it off (tests, benchmarks)."""
    forced = os.environ.get("INGETRAZO_AO")
    if forced is not None and forced != "":
        return settings_from_env()
    if style is None or not getattr(style, "ambient_occlusion", False):
        return None
    return {"radius": max(float(style.ao_distance), 1e-4),
            "intensity": float(style.ao_intensity),
            "samples": int(max(4, min(64, _env_float("INGETRAZO_AO_SAMPLES",
                                                      16))))}


class AmbientOcclusion:
    """The GPU resources of the passes, made on first use in the view's
    GL context and remade when the view changes size."""

    def __init__(self, widget, shader_dir) -> None:
        self._w = widget
        self._dir = shader_dir
        #: Targets per size: the view's own and an export's live side by
        #: side, so an image export does not remake the view's on its way.
        self._targets: dict = {}
        self._size = None
        self._depth_fbo = None
        self._depth_tex = None
        self._ao_fbo = None
        self._blur_fbo = None
        self._vao = None
        self._progs = None
        #: A driver that refused something: the pass stays off this session.
        self.broken: Optional[str] = None
        #: Depth resolves refused in a row (see REFUSALS_TO_GIVE_UP).
        self._refusals = 0

    # -- resources ------------------------------------------------------------
    def _program(self, frag: str) -> QOpenGLShaderProgram:
        prog = QOpenGLShaderProgram(self._w)
        ok_v = prog.addShaderFromSourceFile(QOpenGLShader.Vertex,
                                            str(self._dir / "ao.vert"))
        ok_f = prog.addShaderFromSourceFile(QOpenGLShader.Fragment,
                                            str(self._dir / frag))
        if not (ok_v and ok_f and prog.link()):
            raise RuntimeError(f"{frag}: " + prog.log())
        return prog

    def _ensure(self, gl, w: int, h: int) -> None:
        if self._progs is None:
            self._progs = {name: self._program(name) for name in
                           ("ao.frag", "ao_blur.frag", "ao_apply.frag")}
            self._vao = QOpenGLVertexArrayObject(self._w)
            self._vao.create()
        if self._size == (w, h):
            return
        if (w, h) in self._targets:
            self._size = (w, h)
            (self._depth_tex, self._depth_fbo, self._ao_fbo,
             self._blur_fbo) = self._targets[(w, h)]
            return
        if len(self._targets) >= 2:          # an old view size: let it go
            for key in [k for k in self._targets if k != self._size]:
                self._targets.pop(key)[0].destroy()
        self._size = (w, h)
        tex = QOpenGLTexture(QOpenGLTexture.Target2D)
        tex.setFormat(QOpenGLTexture.D24S8)
        tex.setSize(w, h)
        tex.setMinMagFilters(QOpenGLTexture.Nearest, QOpenGLTexture.Nearest)
        tex.setWrapMode(QOpenGLTexture.ClampToEdge)
        tex.allocateStorage(QOpenGLTexture.DepthStencil,
                            QOpenGLTexture.UInt32_D24S8)
        self._depth_tex = tex
        self._depth_fbo = QOpenGLFramebufferObject(w, h)
        self._depth_fbo.bind()
        gl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT,
                                  GL_TEXTURE_2D, tex.textureId(), 0)
        if gl.glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("depth target incomplete")
        hw, hh = max(w // 2, 1), max(h // 2, 1)
        self._ao_fbo = QOpenGLFramebufferObject(hw, hh)
        self._blur_fbo = QOpenGLFramebufferObject(hw, hh)
        for fbo in (self._ao_fbo, self._blur_fbo):
            gl.glBindTexture(GL_TEXTURE_2D, fbo.texture())
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        gl.glBindTexture(GL_TEXTURE_2D, 0)
        self._targets[(w, h)] = (tex, self._depth_fbo, self._ao_fbo,
                                 self._blur_fbo)

    def release(self) -> None:
        """Free the GL resources; the caller has the context current."""
        for tex, *_ in self._targets.values():
            tex.destroy()
        self._targets.clear()
        self._size = None
        self._depth_tex = self._depth_fbo = None
        self._ao_fbo = self._blur_fbo = None

    # -- the pass -------------------------------------------------------------
    def apply(self, gl, extra, scene_fbo, w: int, h: int,
              proj: QMatrix4x4, settings: dict) -> bool:
        """Darken the opaque faces already in ``scene_fbo``. Leaves the scene
        FBO bound with the view's viewport, depth test and blend as the face
        passes had them; the caller rebinds its own program. False (and
        ``broken`` set) when the driver refused it."""
        if self.broken:
            return False
        try:
            self._ensure(gl, w, h)
        except RuntimeError as exc:
            self.broken = str(exc)
            gl.glBindFramebuffer(GL_FRAMEBUFFER, scene_fbo.handle())
            return False
        inv, ok = proj.inverted()
        if not ok:
            gl.glBindFramebuffer(GL_FRAMEBUFFER, scene_fbo.handle())
            return False

        # 1. Resolve the depth. An error some earlier call left pending (a
        # texture upload while a big file opens) is not ours to answer for:
        # read it out first, or it switched the pass off for the session.
        for _ in range(16):
            if gl.glGetError() == GL_NO_ERROR:
                break
        gl.glBindFramebuffer(GL_READ_FRAMEBUFFER, scene_fbo.handle())
        gl.glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self._depth_fbo.handle())
        # The colour rides along into the target's own colour texture: the
        # last pass reads how light each face is, for the light it bounces.
        extra.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h,
                                GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT,
                                GL_NEAREST)
        if gl.glGetError() != GL_NO_ERROR:
            # One refused frame (the view resizing under a file being
            # opened) only skips that frame; a driver that keeps refusing
            # switches the pass off.
            self._refusals += 1
            if self._refusals >= REFUSALS_TO_GIVE_UP:
                self.broken = "depth resolve refused"
            gl.glBindFramebuffer(GL_FRAMEBUFFER, scene_fbo.handle())
            return False
        self._refusals = 0

        gl.glDisable(GL_DEPTH_TEST)
        gl.glDepthMask(False)
        gl.glDisable(GL_BLEND)
        gl.glActiveTexture(GL_TEXTURE0 + _UNIT_DEPTH)
        gl.glBindTexture(GL_TEXTURE_2D, self._depth_tex.textureId())
        hw, hh = self._ao_fbo.width(), self._ao_fbo.height()
        r = float(settings["radius"])
        self._vao.bind()

        # 2. Occlusion, half size.
        self._ao_fbo.bind()
        gl.glViewport(0, 0, hw, hh)
        p = self._progs["ao.frag"]
        p.bind()
        p.setUniformValue1i(p.uniformLocation("u_depth"), _UNIT_DEPTH)
        p.setUniformValue(p.uniformLocation("u_proj"), proj)
        p.setUniformValue(p.uniformLocation("u_inv_proj"), inv)
        p.setUniformValue(p.uniformLocation("u_texel"),
                          QVector2D(1.0 / w, 1.0 / h))
        p.setUniformValue1f(p.uniformLocation("u_radius"), r)
        p.setUniformValue1f(p.uniformLocation("u_bias"), r * 0.025)
        p.setUniformValue1i(p.uniformLocation("u_samples"),
                            int(settings["samples"]))
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)

        # 3. Blur, half size.
        self._blur_fbo.bind()
        p = self._progs["ao_blur.frag"]
        p.bind()
        gl.glActiveTexture(GL_TEXTURE0 + _UNIT_AO)
        gl.glBindTexture(GL_TEXTURE_2D, self._ao_fbo.texture())
        p.setUniformValue1i(p.uniformLocation("u_ao"), _UNIT_AO)
        p.setUniformValue1i(p.uniformLocation("u_depth"), _UNIT_DEPTH)
        p.setUniformValue(p.uniformLocation("u_texel"),
                          QVector2D(1.0 / hw, 1.0 / hh))
        p.setUniformValue(p.uniformLocation("u_inv_proj"), inv)
        p.setUniformValue1f(p.uniformLocation("u_radius"), r)
        p.setUniformValue1f(p.uniformLocation("u_spread"), 1.0)
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)
        # ...and once more, twice as wide, back into the occlusion target:
        # the first pass cancels the rotation tile, this one spreads the
        # gradient so a corner fades out softly instead of in a band.
        self._ao_fbo.bind()
        gl.glBindTexture(GL_TEXTURE_2D, self._blur_fbo.texture())
        p.setUniformValue1f(p.uniformLocation("u_spread"), 2.0)
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)

        # 4. Multiply onto the scene, full size.
        gl.glBindFramebuffer(GL_FRAMEBUFFER, scene_fbo.handle())
        gl.glViewport(0, 0, w, h)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_ZERO, GL_SRC_COLOR)
        if os.environ.get("INGETRAZO_AO_DEBUG") == "1":   # the bare map
            gl.glDisable(GL_BLEND)
        # The leaves keep their colour: a crown of crossed cards is all
        # "corners" to the depth, and came out nearly black.
        gl.glEnable(GL_STENCIL_TEST)
        gl.glStencilMask(0)
        gl.glStencilFunc(GL_NOTEQUAL, FOLIAGE_BIT, FOLIAGE_BIT)
        gl.glStencilOp(GL_KEEP, GL_KEEP, GL_KEEP)
        p = self._progs["ao_apply.frag"]
        p.bind()
        gl.glBindTexture(GL_TEXTURE_2D, self._ao_fbo.texture())
        p.setUniformValue1i(p.uniformLocation("u_ao"), _UNIT_AO)
        p.setUniformValue1i(p.uniformLocation("u_depth"), _UNIT_DEPTH)
        p.setUniformValue(p.uniformLocation("u_inv_proj"), inv)
        p.setUniformValue(p.uniformLocation("u_ao_size"), QVector2D(hw, hh))
        p.setUniformValue1f(p.uniformLocation("u_radius"), r)
        p.setUniformValue1f(p.uniformLocation("u_intensity"),
                            float(settings["intensity"]))
        gl.glActiveTexture(GL_TEXTURE0 + _UNIT_COLOR)
        gl.glBindTexture(GL_TEXTURE_2D, self._depth_fbo.texture())
        p.setUniformValue1i(p.uniformLocation("u_color"), _UNIT_COLOR)
        gl.glDrawArrays(GL_TRIANGLES, 0, 3)
        gl.glBindTexture(GL_TEXTURE_2D, 0)
        gl.glActiveTexture(GL_TEXTURE0 + _UNIT_AO)
        self._vao.release()

        # Back to the face passes' state.
        gl.glDisable(GL_STENCIL_TEST)
        gl.glStencilMask(0xFF)
        gl.glStencilFunc(GL_ALWAYS, 0, 0xFF)
        gl.glBindTexture(GL_TEXTURE_2D, 0)
        gl.glActiveTexture(GL_TEXTURE0 + _UNIT_DEPTH)
        gl.glBindTexture(GL_TEXTURE_2D, 0)
        gl.glActiveTexture(GL_TEXTURE0)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(GL_DEPTH_TEST)
        gl.glDepthMask(True)
        return True
