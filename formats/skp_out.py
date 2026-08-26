# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""SKP export — native SketchUp file via OpenSKP's pure-Python writer.

Writes the scene as a legacy-format (v17) ``.skp`` file that opens directly in
SketchUp 2017 or later — no COLLADA round-trip, no Trimble SDK, no Wine.
Per-face paint (``Face.attrs["color"]``) becomes a SketchUp material, textured
faces (``attrs["texture"]``) become image-mapped materials with their original
textures embedded in the ``.skp``, layers become SketchUp tags, and face holes
survive as inner loops.

Structure survives too: a classic group (mesh in world coordinates, no
``xform``) becomes a SketchUp group via ``add_group``, and component instances
— sibling groups sharing one prototype mesh — become ONE component definition
placed by N instances (``add_component_definition`` + ``add_instance``), so
the shared geometry is stored once and stays editable as a component on the
SketchUp side. Loose mesh faces stay root-level. Two deliberate exclusions,
mirroring ``meshexport.world_faces``: hidden entities and face-me billboards
(SketchUp-specific import artifacts) are not exported. IngeTrazo's group list
is flat, so there is no nesting to preserve.

Coordinates are in **inches** (SketchUp's native unit); the model's metre-based
geometry is scaled by ``_M_TO_IN``, and instance placements carry their
rotation/scale 3×3 unchanged with the translation converted the same way.
The file produced is the same legacy MFC format that ``openskp.create``
targets — pre-2021, universally readable.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QVector3D

from core.texture import face_uv_axes, uv_reference_points

# IngeTrazo stores geometry in metres; SketchUp works in inches.
_M_TO_IN = 39.37007874

def _color_to_rgba(color):
    """Convert a float (0.0-1.0) RGB colour to integer (0-255) RGBA."""
    r, g, b = color[:3]
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)), 255)


def _pts_inches(points):
    """``QVector3D`` positions (metres) as ``(x, y, z)`` tuples in inches."""
    return [(v.x() * _M_TO_IN, v.y() * _M_TO_IN, v.z() * _M_TO_IN)
            for v in points]


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

    Returns ``mat_handles``: ``key → material_slot``. Unpainted faces never
    reach here — their ``None`` key stays out of ``faces_by_key``, so they
    export with no material at all (SketchUp's default material).
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
            handle = builder.add_material(names[key], _color_to_rgba(info["color"]))
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
    ``formats.meshexport.collect_geometry`` and ``formats.obj``, except an
    unpainted face keys to ``None``: SketchUp has a first-class default
    material (OBJ/glTF don't, which is why meshexport bakes cream there),
    so "never painted" round-trips as "no material" instead of coming back
    as an explicit cream paint that pollutes the per-material takeoff.

    Unlike meshexport, the registry identity (``attrs["mat"]``) is PART of
    the key: two named materials sharing one recipe (e.g. "Yellow" and
    "[0056_Yellow]", both the same RGB) stay separate materials in the
    ``.skp`` instead of silently merging — merged names corrupt the
    per-material takeoff after a round-trip. Measured on a real model
    (toril 2017): 9 distinct names shared a recipe with another."""
    mat = face.attrs.get("mat")
    ident = (mat,) if mat else ()
    tex = face.attrs.get("texture")
    if tex is not None and tex.get("path"):
        src = Path(tex["path"])
        return ("tex", src.name) + ident
    col = face.attrs.get("color")
    if not col:
        return None
    return ("color", tuple(col)) + ident


def _material_info(face, key):
    """Build the info dict for a material key — same shape as
    ``collect_geometry``'s ``materials[key]``."""
    tex = face.attrs.get("texture")
    if tex is not None and tex.get("path"):
        src = Path(tex["path"])
        info = {"color": (1.0, 1.0, 1.0), "map": src.name, "src": src}
    else:
        info = {"color": tuple(face.attrs["color"]), "map": None}
    mat_name = face.attrs.get("mat")
    if mat_name:
        info["mat"] = mat_name
    return info


def _split_containers(scene):
    """The scene's exportable geometry, structured: ``(loose_faces,
    classic_groups, families)``.

    ``families`` maps a shared prototype mesh's ``id()`` to the list of
    component instances (groups with an ``xform``) placing it; classic
    groups (no ``xform``) keep their mesh in world coordinates. Mirrors
    ``meshexport.world_faces``'s rules: hidden entities and face-me
    billboards are skipped, and loose faces come from ``scene.loose_mesh``
    so a group being edited is not double-counted (its mesh is already in
    ``scene.groups``)."""
    visible = getattr(scene, "entity_visible", None) or (lambda e: True)
    mesh = getattr(scene, "loose_mesh", None) or getattr(scene, "mesh", None)
    faces = mesh.faces if mesh is not None else getattr(scene, "faces", [])
    loose_faces = [f for f in faces if visible(f)]

    classic, families = [], {}
    for g in getattr(scene, "groups", []):
        if not visible(g) or getattr(g, "billboard", False) or not g.mesh.faces:
            continue
        if getattr(g, "xform", None) is None:
            classic.append(g)
        else:
            families.setdefault(id(g.mesh), []).append(g)
    return loose_faces, classic, families


def _iter_export_faces(loose_faces, classic, families):
    """Every face the geometry pass will emit, prototype meshes ONCE — the
    material pass must cover exactly this set, no more (a prototype's attrs
    are shared by its instances, so visiting it per-instance is redundant)."""
    yield from loose_faces
    for g in classic:
        yield from g.mesh.faces
    for members in families.values():
        yield from members[0].mesh.faces


def _face_uv_pairs(face, points=None):
    """Where the face's texture sits, as the three ``(point, (u, v))`` pairs
    OpenSKP fits its UV matrix through — or ``None`` for an untextured or
    degenerate face, which then takes SketchUp's default projection.

    Without this the exporter wrote textured faces with no mapping at all,
    and a model saved from IngeTrazo opened in SketchUp Web with every
    texture gone, each surface flat in its average colour (Marco's pool: the
    water lavender, the deck terracotta, the palm a black silhouette). The
    recipe is shared with the renderer through ``core.texture.face_uv_axes``,
    so what the .skp carries is what the viewport showed.

    The points are handed over in INCHES, like the rest of the geometry, but
    the coordinates are read in metres — a pair only says "this point lands
    on that texture coordinate", and the two spaces must not be mixed."""
    tex = face.attrs.get("texture")
    if not tex or not tex.get("path"):
        return None
    ref = uv_reference_points(points if points is not None else face.vertices,
                              face.normal())
    if ref is None:
        return None
    gu, cu, gv, cv = face_uv_axes(tex, face.normal())
    return [
        (pt, (QVector3D.dotProduct(gu, p) + cu,
              QVector3D.dotProduct(gv, p) + cv))
        for p, pt in zip(ref, _pts_inches(ref))
    ]


def _emit_face(sink, face, mat_handles, layer_handles, SkpWriteError):
    """Write one face (outer loop + holes) to ``sink`` — the root builder or
    an open group/component definition; all three expose the same
    ``add_face``.

    OpenSKP's ``add_face`` requires strict coplanarity (tolerance ~1e-6 ×
    span) and transformed geometry can carry tiny floating-point drift, so a
    rejected polygon falls back to triangulation — ``face.triangulate()`` is
    hole-aware, and triangles are coplanar by definition. Most faces export
    as clean polygons; only drifted ones get triangulated."""
    material = mat_handles.get(_material_key(face))
    face_layer = face.attrs.get("layer")
    layer = layer_handles.get(face_layer) if face_layer else None
    soft = _is_soft_face(face)
    uv = _face_uv_pairs(face)
    try:
        sink.add_face(
            _pts_inches(face.vertices),
            material=material,
            layer=layer,
            soft_edges=soft,
            smooth_edges=soft,
            front_uv=uv,
            holes=[_pts_inches(h) for h in face.holes],
        )
    except SkpWriteError:
        for tri in face.triangulate():
            try:
                sink.add_face(
                    _pts_inches(tri),
                    material=material,
                    layer=layer,
                    soft_edges=True,
                    smooth_edges=True,
                    front_uv=_face_uv_pairs(face, tri),
                )
            except SkpWriteError:
                pass  # Degenerate triangle — skip silently.


def _instance_placement(xform):
    """Split a ``QMatrix4x4`` (local metres → world metres) into OpenSKP's
    ``(translation, matrix3x3)``: the rotation/scale 3×3 is unitless so it
    passes through row-major unchanged; only the translation converts to
    inches. Inverse of ``skp_openskp._matrix``."""
    r0, r1, r2 = xform.row(0), xform.row(1), xform.row(2)
    matrix3x3 = (r0.x(), r0.y(), r0.z(),
                 r1.x(), r1.y(), r1.z(),
                 r2.x(), r2.y(), r2.z())
    translation = (r0.w() * _M_TO_IN, r1.w() * _M_TO_IN, r2.w() * _M_TO_IN)
    return translation, matrix3x3


def save_skp(scene, path) -> None:
    """Write the scene as a SketchUp ``.skp`` to ``path``."""
    try:
        import openskp
        from openskp import SkpWriteError
    except ImportError as exc:
        raise RuntimeError("OpenSKP is required for SKP export") from exc

    builder = openskp.create()
    loose_faces, classic, families = _split_containers(scene)

    # ---- Pass 1: collect material and layer info from all faces ----------
    materials_info: dict[tuple, dict] = {}
    for face in _iter_export_faces(loose_faces, classic, families):
        key = _material_key(face)
        if key is None:  # unpainted — SketchUp's default material
            continue
        if key not in materials_info:
            materials_info[key] = _material_info(face, key)
        elif face.attrs.get("mat") and "mat" not in materials_info[key]:
            materials_info[key]["mat"] = face.attrs["mat"]

    # Register materials (must be before layers and geometry).
    mat_handles = _collect_materials(materials_info, builder)

    # Register layers (must be after materials, before geometry).
    layer_handles = _collect_layers(scene, builder)

    # ---- Pass 2: emit geometry -------------------------------------------
    # Groups and component definitions must ALL be written before any
    # root-level face or instance — OpenSKP splices definitions in after
    # materials and layers, so their slot numbering locks once root
    # geometry starts.
    for g in classic:
        with builder.add_group(
                g.name, layer=layer_handles.get(getattr(g, "layer", None))) as grp:
            for face in g.mesh.faces:
                _emit_face(grp, face, mat_handles, layer_handles, SkpWriteError)

    placed = []  # (definition, members) — instances go in after root faces
    for members in families.values():
        with builder.add_component_definition(members[0].name) as defn:
            for face in members[0].mesh.faces:
                _emit_face(defn, face, mat_handles, layer_handles, SkpWriteError)
        placed.append((defn, members))

    for face in loose_faces:
        _emit_face(builder, face, mat_handles, layer_handles, SkpWriteError)

    for defn, members in placed:
        for g in members:
            translation, matrix3x3 = _instance_placement(g.xform)
            builder.add_instance(
                defn,
                name=g.name,
                translation=translation,
                matrix3x3=matrix3x3,
                layer=layer_handles.get(getattr(g, "layer", None)),
            )

    _emit_annotations(scene, builder)

    builder.save(str(Path(path)))


def _emit_annotations(scene, builder) -> None:
    """Write dimensions and leader texts, when this openskp has the writer
    (add_dimension/add_text — our annotations branch; harmless no-op before
    it lands upstream).

    The .skp free dimension stores a SCALAR offset; SketchUp derives the
    plane itself, so the scalar is our offset vector projected on the same
    in-plane perpendicular the importer uses (cross(Z, segment) with the
    import's fallbacks) — export∘import is the identity on our own files.
    """
    from PySide6.QtGui import QVector3D
    add_dim = getattr(builder, "add_dimension", None)
    add_text = getattr(builder, "add_text", None)
    if add_dim is not None:
        for dim in getattr(scene, "dimensions", []) or []:
            seg = dim.b - dim.a
            if seg.length() < 1e-9:
                continue
            perp = QVector3D.crossProduct(QVector3D(0.0, 0.0, 1.0), seg)
            if perp.length() < 1e-9:               # vertical dimension
                perp = QVector3D.crossProduct(QVector3D(1.0, 0.0, 0.0), seg)
            perp.normalize()
            (pa, pb) = _pts_inches([dim.a, dim.b])
            add_dim(pa, pb,
                    offset=QVector3D.dotProduct(dim.offset, perp) * _M_TO_IN)
    if add_text is not None:
        for lab in getattr(scene, "text_labels", []) or []:
            text = (lab.text or "").strip()
            if not text:
                continue
            (anchor,) = _pts_inches([lab.anchor])
            leader = (lab.offset.x() * _M_TO_IN, lab.offset.y() * _M_TO_IN,
                      lab.offset.z() * _M_TO_IN)
            add_text(text, anchor, leader=leader)
