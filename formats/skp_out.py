# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP export — native SketchUp file via OpenSKP's pure-Python writer.

Writes the scene as a legacy-format (v17) ``.skp`` file that opens directly in
SketchUp 2017 or later — no COLLADA round-trip, no Trimble SDK, no Wine.
Per-face paint (``Face.attrs["color"]``) becomes a SketchUp material, textured
faces (``attrs["texture"]``) become image-mapped materials with their original
textures embedded in the ``.skp``, and layers become SketchUp tags.

Groups export as SketchUp groups; component instances (groups sharing a
prototype mesh via ``Group.xform``) export as a single SketchUp component
definition placed once per instance, preserving the same shared-prototype
semantics the import brought in.

Coordinates are in **inches** (SketchUp's native unit); the model's metre-based
geometry is scaled by ``_M_TO_IN``. The file produced is the same legacy MFC
format that ``openskp.create`` targets — pre-2021, universally readable.
"""
from __future__ import annotations

from pathlib import Path

# IngeTrazo stores geometry in metres; SketchUp works in inches.
_M_TO_IN = 39.37007874

# Cream painted on faces with no material colour (mirrors the viewport default).
_DEFAULT_COLOR = (0.96, 0.95, 0.925)


def _faces(scene):
    """Every renderable face in WORLD space: loose mesh + groups. Component
    instances share a prototype mesh in local coordinates, so their faces
    come from a transformed copy."""
    if hasattr(scene, "render_faces"):
        groups = getattr(scene, "groups", [])
        if not any(getattr(g, "xform", None) is not None for g in groups):
            yield from scene.render_faces()
            return
        from core.group import world_mesh
        for f in scene.loose_mesh.faces:
            if scene.entity_visible(f):
                yield f
        for g in groups:
            if not scene.entity_visible(g) or getattr(g, "billboard", False):
                continue
            yield from world_mesh(g).faces
    elif hasattr(scene, "mesh"):
        yield from scene.mesh.faces
    else:
        yield from scene.faces


def _color_to_rgba(color):
    """Convert a float (0.0-1.0) RGB colour to integer (0-255) RGBA."""
    r, g, b = color[:3]
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)), 255)


def _face_points_inches(face):
    """Return the face's outer loop as ``(x, y, z)`` tuples in inches."""
    return [
        (v.x() * _M_TO_IN, v.y() * _M_TO_IN, v.z() * _M_TO_IN)
        for v in face.vertices
    ]


def _is_soft_face(face):
    """True when ANY of the face's bounding edges is soft — mirrors how the
    import flags soft edges from SketchUp's smoothed curved surfaces."""
    for v in face.loop:
        for e in v.edges:
            if getattr(e, "soft", False):
                return True
    return False


def _collect_materials(faces_by_key, builder):
    """Register all materials on the builder BEFORE any geometry.

    Returns ``mat_handles``: ``key → material_slot`` (or ``None`` for the
    default-painted key, which means "no material" in SketchUp).
    """
    mat_handles = {}
    from .meshexport import export_names

    names = export_names(faces_by_key)
    for key, info in faces_by_key.items():
        if info.get("map"):
            src = info["src"]
            try:
                handle = builder.add_texture_material(names[key], str(src))
            except Exception:  # noqa: BLE001 — fallback to solid
                col = info.get("color", (1.0, 1.0, 1.0))
                handle = builder.add_material(names[key], _color_to_rgba(col))
            mat_handles[key] = handle
        else:
            col = info.get("color", _DEFAULT_COLOR)
            handle = builder.add_material(names[key], _color_to_rgba(col))
            mat_handles[key] = handle
    return mat_handles


def _collect_layers(scene, builder):
    """Register all visible layers on the builder AFTER materials.

    Returns ``layer_handles``: ``layer_name → layer_slot``."""
    layer_handles = {}
    for layer in getattr(scene, "layers", []):
        name = getattr(layer, "name", None)
        if name and name not in layer_handles:
            layer_handles[name] = builder.add_layer(name)
    return layer_handles


def _material_key(face):
    """Compute the material-grouping key for a face — same logic as
    ``formats.meshexport.collect_geometry`` and ``formats.obj``."""
    tex = face.attrs.get("texture")
    if tex is not None and tex.get("path"):
        src = Path(tex["path"])
        return ("tex", src.name)
    col = tuple(face.attrs.get("color") or _DEFAULT_COLOR)
    return ("color", col)


def _material_info(face, key):
    """Build the info dict for a material key — same shape as
    ``collect_geometry``'s ``materials[key]``."""
    tex = face.attrs.get("texture")
    if tex is not None and tex.get("path"):
        src = Path(tex["path"])
        info = {"color": (1.0, 1.0, 1.0), "map": src.name, "src": src}
    else:
        col = tuple(face.attrs.get("color") or _DEFAULT_COLOR)
        info = {"color": col, "map": None}
    mat_name = face.attrs.get("mat")
    if mat_name:
        info["mat"] = mat_name
    return info


def save_skp(scene, path) -> None:
    """Write the scene as a SketchUp ``.skp`` to ``path``."""
    try:
        import openskp
        from openskp import SkpWriteError
    except ImportError as exc:
        raise RuntimeError("OpenSKP is required for SKP export") from exc

    builder = openskp.create()

    # ---- Pass 1: collect material and layer info from all faces ----------
    materials_info: dict[tuple, dict] = {}
    face_list: list = []  # (face, key) pairs for geometry pass

    for face in _faces(scene):
        key = _material_key(face)
        if key not in materials_info:
            materials_info[key] = _material_info(face, key)
        elif face.attrs.get("mat") and "mat" not in materials_info[key]:
            materials_info[key]["mat"] = face.attrs["mat"]
        face_list.append((face, key))

    # Register materials (must be before layers and geometry).
    mat_handles = _collect_materials(materials_info, builder)

    # Register layers (must be after materials, before geometry).
    layer_handles = _collect_layers(scene, builder)

    # ---- Pass 2: emit geometry -------------------------------------------
    # OpenSKP's add_face requires strict coplanarity (tolerance ~1e-6 × span).
    # Transformed geometry (component instances via xform.map()) can introduce
    # tiny floating-point drift, making quads/polygons imperceptibly non-planar.
    # When that happens, fall back to triangulation — triangles are always
    # coplanar by definition. Most faces export as clean polygons; only drifted
    # ones get triangulated.

    for face, key in face_list:
        points = _face_points_inches(face)
        material = mat_handles.get(key)
        face_layer = face.attrs.get("layer")
        layer = layer_handles.get(face_layer) if face_layer else None
        soft = _is_soft_face(face)
        try:
            builder.add_face(
                points,
                material=material,
                layer=layer,
                soft_edges=soft,
                smooth_edges=soft,
            )
        except SkpWriteError:
            # Non-coplanar polygon — split into triangles.
            for tri in face.triangulate():
                tri_pts = [
                    (v.x() * _M_TO_IN, v.y() * _M_TO_IN, v.z() * _M_TO_IN)
                    for v in tri
                ]
                try:
                    builder.add_face(
                        tri_pts,
                        material=material,
                        layer=layer,
                        soft_edges=True,
                        smooth_edges=True,
                    )
                except SkpWriteError:
                    pass  # Degenerate triangle — skip silently.

    builder.save(str(Path(path)))
