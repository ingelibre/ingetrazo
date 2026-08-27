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

The current colour is class-level (shared across activations) and is set from
the toolbar swatch (a ``QColorDialog``); the tool only applies it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from core.i18n import tr
from core.mesh import Face
from core.history import (
    CompoundCommand,
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
        face, _group = vp.pick_face_any(ctx.screen.x(), ctx.screen.y())
        if face is None:
            return

        if (ctx.modifiers & Qt.AltModifier) or PaintTool.sample_armed:
            # Eyedropper: adopt the face's material (texture if it has one, else
            # colour) as the current paint material — identity included, so
            # sampling "Concreto visto" paints "Concreto visto".
            tex = face.attrs.get("texture")
            if tex is not None:
                PaintTool.current_texture = dict(tex)
                PaintTool.current_texture_plane = (
                    _face_plane(face) if tex.get("uvw") else None)
            else:
                PaintTool.current_texture = None
                PaintTool.current_texture_plane = None
                sampled = face.attrs.get("color")
                PaintTool.current_color = (tuple(sampled) if sampled is not None
                                           else DEFAULT_FACE_COLOR)
            PaintTool.current_opacity = face.attrs.get("opacity")
            name = face.attrs.get("mat")
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
