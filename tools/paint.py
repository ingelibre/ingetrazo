# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Paint (bucket) tool: assign a material colour to a face.

Behavior (SketchUp's Paint Bucket, ``B``):
- Left click on a face: paint it with the tool's current colour. The colour
  lives in the face's ``attrs["color"]`` (the generic per-region attrs from
  A.3), so it survives push/pull and the plane rebuild.
- If the clicked face is part of the current face selection, the whole
  selection is painted in one undoable step (paint many at once).
- **Alt**+click samples the face's material into the current one (SketchUp's
  eyedropper): image, applied size, rotation, translucency and the material
  identity all travel, so the next click reproduces that material on another
  face. A face carrying an explicit world→UV map (an imported texture, or one
  positioned by hand) hands that map on only to faces on the SAME plane, where
  it keeps the pattern lined up; a face on another plane gets the material with
  its OWN planar projection at the same applied size. Copying the map across
  planes is what SketchUp calls a *projected* texture, and doing it by default
  degenerates: on a wall perpendicular to the sampled floor the ``v`` axis
  lands along the wall's normal and the image smears into stripes.
- Works on loose geometry and group faces alike (``pick_face_any``).
- **Paints the side you click.** A face has a front and a back, and
  SketchUp paints exactly the side under the cursor: the front of a wall
  takes the brick, its back keeps the style's default blue-grey. IngeTrazo
  used to show every paint on both sides («si a una cara le aplico un
  color o textura también se aplica a su revés, lo cual no debería» —
  Marco, 2026-09-11). The back's own material lives in ``attrs["back"]``
  (``SetFaceBackCommand``); a translucent front — glass, water, a raschel
  mesh, a leaf cutout — reads on both sides anyway, as in SketchUp, and
  that rule lives in ``core.materials.back_is_default``.

The current colour is class-level (shared across activations) and is set from
the toolbar swatch (a ``QColorDialog``); the tool only applies it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from core.i18n import tr
from core.mesh import Face
from core.history import (
    CompoundCommand,
    SetFaceBackCommand,
    SetFaceColorCommand,
    SetFaceMaterialTagCommand,
    SetFaceOpacityCommand,
    SetFaceTextureCommand,
)
from tools.base import Tool, ToolContext

# The default cream the viewport paints unpainted faces with — sampling an
# unpainted face yields this, and it is what "no colour" reads as.
DEFAULT_FACE_COLOR = (0.96, 0.95, 0.925)


def _face_plane(face) -> tuple:
    """``(unit normal, offset)`` of the face's plane."""
    from PySide6.QtGui import QVector3D
    n = face.normal()
    p = face.vertices[0] if face.vertices else QVector3D()
    return (n, QVector3D.dotProduct(n, p))


def _same_plane(face, plane, tol: float = 1e-4) -> bool:
    from PySide6.QtGui import QVector3D
    n, d = plane
    fn = face.normal()
    if abs(abs(QVector3D.dotProduct(fn, n)) - 1.0) > 1e-3:
        return False
    p = face.vertices[0] if face.vertices else QVector3D()
    return abs(QVector3D.dotProduct(n, p) - d) <= tol


def _texture_commands(faces, tex, plane) -> list:
    """Apply ``tex`` the way SketchUp's eyedropper does.

    An explicit ``uvw`` is where the image sits IN THE WORLD; it only means
    the same thing on the plane it was fitted for. Faces on that plane keep
    it, so a pattern continues across a seam; every other face takes the
    material without it and projects the image on its own plane at the same
    applied size."""
    if not tex.get("uvw") or plane is None:
        return [SetFaceTextureCommand(faces, tex)]
    same = [f for f in faces if _same_plane(f, plane)]
    other = [f for f in faces if not _same_plane(f, plane)]
    cmds = []
    if same:
        cmds.append(SetFaceTextureCommand(same, tex))
    if other:
        flat = {k: v for k, v in tex.items() if k != "uvw"}
        cmds.append(SetFaceTextureCommand(other, flat))
    return cmds


def clicked_back_side(viewport, face, group, x: float, y: float) -> bool:
    """Whether the cursor at ``(x, y)`` sees the BACK of ``face``: the
    pick ray runs along the face's world normal instead of against it.
    ``group`` is what ``pick_face_any`` returned beside the face (its
    transform places the normal). A viewport without a ray (the stubs in
    tests) reads as the front."""
    from PySide6.QtGui import QVector3D
    ray = getattr(viewport, "_pixel_to_ray", None)
    if ray is None:
        return False
    origin, direction = ray(x, y)
    if origin is None or direction is None:
        return False
    from core.snap import face_plane_world
    _p, normal = face_plane_world(face, getattr(group, "xform", None))
    return QVector3D.dotProduct(normal, direction) > 0.0


class PaintTool(Tool):
    name = "Paint"
    shortcut = "B"
    uses_snap = False  # picks a face to paint; no snap markers

    # Shared current paint colour (RGB, 0..1), set from the toolbar swatch.
    current_color: tuple[float, float, float] = (0.80, 0.45, 0.30)
    # Shared current texture ({"path","sw","sh"}) or None. When set, the click
    # applies a texture instead of a colour — chosen from the toolbar.
    current_texture: dict | None = None
    # Shared current material IDENTITY (core.materials.Material) or None.
    # Set by the tray when the active swatch has a name; painting then
    # stamps attrs["mat"] alongside the colour/texture (and registers the
    # material in the scene on first use). None = anonymous paint, which
    # CLEARS any previous identity — a red face is no longer "Concreto
    # visto", so the per-material takeoff never lies.
    current_material = None
    # Shared translucency (glass): None = opaque paint, which also CLEARS
    # any previous opacity on the painted faces.
    current_opacity: float | None = None
    # Armed by the toolbar's eyedropper button: the NEXT click samples
    # instead of painting, then disarms. SketchUp puts the same pipette
    # beside the material — Alt works for people who know it, the button is
    # how you find it.
    sample_armed: bool = False
    # Plane the current texture's explicit ``uvw`` belongs to, as
    # ``(normal, offset)`` — set when the eyedropper samples a face that
    # carries one. Only faces on that plane inherit the map; see the module
    # docstring. ``None`` = the texture has no map of its own to hand on.
    current_texture_plane: tuple | None = None

    def on_activate(self, viewport) -> None:
        pass

    def on_deactivate(self, viewport) -> None:
        viewport.set_hover(None)

    def on_hover(self, ctx: ToolContext) -> None:
        face, _group = ctx.viewport.pick_face_any(ctx.screen.x(), ctx.screen.y())
        ctx.viewport.set_hover(face)

    def on_click(self, ctx: ToolContext) -> None:
        vp = ctx.viewport
        face, group = vp.pick_face_any(ctx.screen.x(), ctx.screen.y())
        if face is None:
            return
        back_side = clicked_back_side(vp, face, group,
                                      ctx.screen.x(), ctx.screen.y())

        if (ctx.modifiers & Qt.AltModifier) or PaintTool.sample_armed:
            # Eyedropper: adopt the face's material (texture if it has one, else
            # colour) as the current paint material — identity included, so
            # sampling "Concreto visto" paints "Concreto visto". The side
            # under the cursor is what gets sampled: a back painted on its
            # own gives its own material, a two-sided face its front, a
            # default back the default paint.
            src = face.attrs
            if back_side:
                back = face.attrs.get("back")
                if isinstance(back, dict):
                    src = back
                elif back is not True:
                    src = {}
            tex = src.get("texture")
            if tex is not None:
                PaintTool.current_texture = dict(tex)
                PaintTool.current_texture_plane = (
                    _face_plane(face) if tex.get("uvw") else None)
            else:
                PaintTool.current_texture = None
                PaintTool.current_texture_plane = None
                sampled = src.get("color")
                PaintTool.current_color = (tuple(sampled) if sampled is not None
                                           else DEFAULT_FACE_COLOR)
            PaintTool.current_opacity = src.get("opacity")
            name = src.get("mat")
            PaintTool.current_material = (
                vp.scene.materials.get(name) if name else None)
            if PaintTool.sample_armed:
                PaintTool.sample_armed = False
                win = vp.window()
                if hasattr(win, "release_eyedropper"):
                    win.release_eyedropper()
            vp.update()
            # Optional, like the other viewport niceties this package uses:
            # the tool has to work against a bare viewport too.
            flash = getattr(vp, "flash_status", None)
            if callable(flash):
                flash(tr("Material sampled — click a face to paint it"))
            return

        # Paint the clicked face — or, if it is part of the current face
        # selection, the whole selection. A face on a curved surface (cylinder
        # side) paints the whole surface, SketchUp-style.
        sel_faces = [e for e in vp.scene.selection if isinstance(e, Face)]
        faces = (sel_faces if face in sel_faces
                 else vp.scene.mesh.surface_of(face))
        mat = PaintTool.current_material
        if back_side:
            # The back gets its own material and nothing else changes:
            # the front keeps what it had. The material still registers
            # itself in the scene (an empty tag stamp does only that).
            vp.history.execute(CompoundCommand([
                SetFaceMaterialTagCommand(
                    [], mat.name if mat is not None else None, mat),
                SetFaceBackCommand(faces, [self._back_material_for(f)
                                           for f in faces]),
            ]))
            vp.update()
            return
        tag = SetFaceMaterialTagCommand(
            faces, mat.name if mat is not None else None, mat)
        opacity = SetFaceOpacityCommand(faces, PaintTool.current_opacity)
        if PaintTool.current_texture is not None:
            vp.history.execute(CompoundCommand(
                _texture_commands(faces, PaintTool.current_texture,
                                  PaintTool.current_texture_plane)
                + [opacity, tag]))
        else:
            # Painting a solid colour clears any texture on those faces, in one
            # undoable step.
            vp.history.execute(CompoundCommand([
                SetFaceColorCommand(faces, PaintTool.current_color),
                SetFaceTextureCommand(faces, None),
                opacity,
                tag,
            ]))
        vp.update()

    @classmethod
    def _back_material_for(cls, face) -> dict:
        """The current paint as a back-side material dict for ``face`` —
        the same keys the front uses, with the eyedropper's plane rule for
        a positioned texture (see ``_texture_commands``)."""
        back: dict = {}
        if cls.current_texture is not None:
            tex = dict(cls.current_texture)
            if tex.get("uvw") and (cls.current_texture_plane is None
                                   or not _same_plane(
                                       face, cls.current_texture_plane)):
                tex.pop("uvw", None)
            back["texture"] = tex
        else:
            back["color"] = list(cls.current_color)
        if cls.current_opacity is not None:
            back["opacity"] = float(cls.current_opacity)
        if cls.current_material is not None:
            back["mat"] = cls.current_material.name
        return back
