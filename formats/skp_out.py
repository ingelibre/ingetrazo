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


def _supported(fn, *names) -> set:
    """Which of ``names`` the installed OpenSKP's ``fn`` actually accepts.

    The applied size and the opacity gate are OUR additions to the writer
    (upstream PR #252; the size kwargs are ``applied_width``/``applied_height``
    there, matching upstream's own ``applied_height``, while the pre-PR fork
    spelled them ``width``/``height`` — the caller probes for both
    generations). Passing them blind raised ``TypeError: add_material() got
    an unexpected keyword argument 'opacity'`` against the pinned upstream —
    CI red and, worse, every .skp save broken in a build made from it. The
    rest of this module already guards its OpenSKP joins the same way; these
    two slipped through.  Older library: the file is written without them (a
    texture claims one inch per tile, glass exports opaque) instead of not
    written at all."""
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):          # C accelerator / builtin
        return set(names)
    if any(pm.kind is inspect.Parameter.VAR_KEYWORD for pm in params.values()):
        return set(names)
    return {n for n in names if n in params}


def _stage_texture(src: Path, stage_dir: Path | None, taken: set) -> Path | None:
    """The image as the writer must see it: readable, PNG or JPEG, and at a
    SHORT path. openskp stores ``image_path`` verbatim in the .skp and its
    string writer refuses 255+ characters — AFTER the image bytes and the
    applied size are already in its buffer. So a long path never "fell
    back to a colour": the material was left half-written, the colour
    record landed on top, and SketchUp refused the whole file (0.3.10's
    Flatpak: a texture cached under a stacked-hash name of 250 characters
    spilled into the temp fallback and the path passed 255). Staging into
    ``stage_dir`` under the image's plain name keeps the stored string short
    and keeps the user's home path out of the document; without a stage
    dir (direct callers) the source path is used when it is short enough.
    Returns None when the file cannot be embedded, and the caller writes a
    solid colour WITHOUT having touched the writer."""
    src = Path(src)
    if stage_dir is None:                   # direct callers: no staging
        return src if len(str(src)) < 200 else None
    try:
        data = src.read_bytes()
    except OSError:
        return None
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data[:3] == b"\xff\xd8\xff"):
        return None
    from core.texture import texture_file_name
    base = texture_file_name(src.name)
    name = base
    n = 1
    while name in taken:
        n += 1
        stem, dot, ext = base.rpartition(".")
        name = f"{stem}-{n}.{ext}" if dot else f"{base}-{n}"
    taken.add(name)
    out = stage_dir / name
    out.write_bytes(data)
    return out


def _collect_materials(faces_by_key, builder, stage_dir: Path | None = None):
    """Register all materials on the builder BEFORE any geometry.

    Returns ``mat_handles``: ``key → material_slot``. Unpainted faces never
    reach here — their ``None`` key stays out of ``faces_by_key``, so they
    export with no material at all (SketchUp's default material).
    """
    mat_handles = {}
    from .meshexport import export_names

    names = export_names(faces_by_key)
    tex_ok = _supported(builder.add_texture_material,
                        "applied_width", "applied_height",
                        "width", "height", "opacity")
    col_ok = _supported(builder.add_material, "opacity")
    staged_names: set[str] = set()
    for key, info in faces_by_key.items():
        if info.get("map"):
            staged = _stage_texture(info["src"], stage_dir, staged_names)
            if staged is None:
                # Unreadable, or not PNG/JPEG: a solid colour, decided HERE
                # — never by catching the writer's exception, see
                # _stage_texture.
                col = info.get("color", (1.0, 1.0, 1.0))
                mat_handles[key] = builder.add_material(
                    names[key], _color_to_rgba(col))
                continue
            # The applied size, in inches: how much model space one tile
            # covers. For a texture applied without positioning this IS
            # the mapping — SketchUp writes no per-face record for those
            # — so leaving it out made every texture claim to span one
            # inch however large it was. Marco's lawn (3.26 x 8.82 m)
            # repeated 128 times and lost its aspect; only the surfaces
            # whose tile was already inch-sized came out right.
            w_kw, h_kw = (("applied_width", "applied_height")
                          if "applied_width" in tex_ok
                          else ("width", "height"))
            extra = {k: v for k, v in
                     ((w_kw, info.get("sw_in")),
                      (h_kw, info.get("sh_in")),
                      ("opacity", info.get("opacity")))
                     if k in tex_ok}
            mat_handles[key] = builder.add_texture_material(
                names[key], str(staged), **extra)
        else:
            extra = ({"opacity": info.get("opacity")} if "opacity" in col_ok
                     else {})
            handle = builder.add_material(names[key],
                                          _color_to_rgba(info["color"]),
                                          **extra)
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


def _opacity_key(face) -> tuple:
    """Translucency is part of a material's identity: the same image painted
    at two opacities is two SketchUp materials, and merging them would make
    one of them wrong."""
    op = face.attrs.get("opacity")
    return () if op is None or float(op) >= 0.999 else (round(float(op), 3),)


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
        return ("tex", src.name) + ident + _opacity_key(face)
    col = face.attrs.get("color")
    if not col:
        return None
    return ("color", tuple(col)) + ident + _opacity_key(face)


def _material_info(face, key):
    """Build the info dict for a material key — same shape as
    ``collect_geometry``'s ``materials[key]``."""
    tex = face.attrs.get("texture")
    if tex is not None and tex.get("path"):
        src = Path(tex["path"])
        info = {"color": (1.0, 1.0, 1.0), "map": src.name, "src": src}
        sw, sh = tex.get("sw"), tex.get("sh")
        if sw:
            info["sw_in"] = float(sw) * _M_TO_IN
        if sh:
            info["sh_in"] = float(sh) * _M_TO_IN
    else:
        info = {"color": tuple(face.attrs["color"]), "map": None}
    op = face.attrs.get("opacity")
    if op is not None and float(op) < 0.999:
        # Translucency lives on the MATERIAL in SketchUp, so it has to reach
        # the material record: a pool's water (0.6) exported as an opaque
        # slab without it.
        info["opacity"] = float(op)
    mat_name = face.attrs.get("mat")
    if mat_name:
        info["mat"] = mat_name
    return info


def _split_containers(scene):
    """The scene's exportable geometry, structured: ``(loose_faces,
    classic_groups, definitions, root_placements)``.

    ``defs`` is the component definitions to write, CHILDREN BEFORE PARENTS
    (a .skp definition may only reference ones already closed): each
    ``{"name", "mesh", "children"}`` where ``children`` is
    ``(definition index, placing group)`` pairs. ``roots`` places the
    top-level ones. Classic groups (no ``xform``) keep their mesh in world
    coordinates and may place definitions too.

    Definitions are keyed by prototype mesh AND nested structure, so the
    hedge's 9600 faces are written ONCE and placed 48 times instead of
    landing in the file 48 times over — which is the difference between the
    14 MB SketchUp writes for that model and the 80 MB we used to.

    Mirrors ``meshexport.world_faces``'s rules: hidden entities and face-me
    billboards are skipped, and loose faces come from ``scene.loose_mesh``
    so a group being edited is not double-counted (its mesh is already in
    ``scene.groups``)."""
    visible = getattr(scene, "entity_visible", None) or (lambda e: True)
    mesh = getattr(scene, "loose_mesh", None) or getattr(scene, "mesh", None)
    faces = mesh.faces if mesh is not None else getattr(scene, "faces", [])
    loose_faces = [f for f in faces if visible(f)]

    defs: list = []
    index_of: dict = {}

    def _kids(g):
        return [c for c in (getattr(g, "children", None) or ())
                if visible(c) and not getattr(c, "billboard", False)
                and (c.mesh.faces or getattr(c, "children", None))]

    def _key(g):
        return (id(g.mesh),
                tuple((_key(c),
                       tuple(c.xform.data()) if c.xform is not None else None,
                       getattr(c, "layer", None)) for c in _kids(g)))

    def _register(g):
        """Definition index of ``g``'s content, registering its nested
        definitions FIRST — post-order, which is exactly the order the
        format needs them written in."""
        key = _key(g)
        idx = index_of.get(key)
        if idx is not None:
            return idx
        children = [(_register(c), c) for c in _kids(g)]
        idx = index_of[key] = len(defs)
        defs.append({"name": g.name, "mesh": g.mesh, "children": children})
        return idx

    classic, roots = [], []
    for g in getattr(scene, "groups", []):
        if not visible(g) or getattr(g, "billboard", False):
            continue
        kids = _kids(g)
        if not g.mesh.faces and not kids:
            continue
        if getattr(g, "xform", None) is None:
            classic.append((g, [(_register(c), c) for c in kids]))
        else:
            roots.append((_register(g), g))
    return loose_faces, classic, defs, roots


def _iter_export_faces(loose_faces, classic, defs):
    """Every face the geometry pass will emit, prototype meshes ONCE — the
    material pass must cover exactly this set, no more (a prototype's attrs
    are shared by its instances, so visiting it per-instance is redundant)."""
    yield from loose_faces
    for g, _ in classic:
        yield from g.mesh.faces
    for d in defs:
        yield from d["mesh"].faces


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
    if tex.get("planar"):
        # SketchUp's default projection: the material's applied size is the
        # whole mapping and the file carries no per-face record — its own
        # files do exactly this for a texture applied without positioning
        # (all three faces of the calibration model, and two thirds of the
        # textured faces in Marco's pool). Pinning one here would fight the
        # format AND rotate the result, since the writer expresses a UV
        # matrix in the face's first-edge basis while the reader uses one
        # derived from the normal.
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
    the face's SPAN) and our vertices are float32, so a small face far from
    the origin inherits the rounding of a big number and is refused: 15516 of
    the 75486 faces of Marco's pool, each then written as a fan of triangles
    (+18k face records, and the edges that come with them). Snapping each
    face onto its own best-fit plane fixes the test and costs more: it moves
    corners PER FACE, so neighbours stop sharing vertices and every shared
    edge gets written twice (measured: 169878 edges -> 222473, file 28.7 ->
    30.8 MB). The tolerance wants to scale with coordinate magnitude rather
    than face span — an OpenSKP matter. Until then a rejected polygon falls
    back to triangulation: ``face.triangulate()`` is hole-aware, triangles
    are coplanar by definition, and the original corners are kept, so the
    welding survives."""
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

    import tempfile
    with tempfile.TemporaryDirectory(prefix="ingetrazo-skp-") as stage:
        _write_skp(scene, path, openskp, SkpWriteError, Path(stage))


def _write_skp(scene, path, openskp, SkpWriteError, stage_dir: Path) -> None:
    builder = openskp.create()
    loose_faces, classic, defs, roots = _split_containers(scene)

    # ---- Pass 1: collect material and layer info from all faces ----------
    materials_info: dict[tuple, dict] = {}
    for face in _iter_export_faces(loose_faces, classic, defs):
        key = _material_key(face)
        if key is None:  # unpainted — SketchUp's default material
            continue
        if key not in materials_info:
            materials_info[key] = _material_info(face, key)
        elif face.attrs.get("mat") and "mat" not in materials_info[key]:
            materials_info[key]["mat"] = face.attrs["mat"]

    # Register materials (must be before layers and geometry).
    mat_handles = _collect_materials(materials_info, builder, stage_dir)

    # Register layers (must be after materials, before geometry).
    layer_handles = _collect_layers(scene, builder)

    # ---- Pass 2: emit geometry -------------------------------------------
    # Groups and component definitions must ALL be written before any
    # root-level face or instance — OpenSKP splices definitions in after
    # materials and layers, so their slot numbering locks once root
    # geometry starts.
    def _place_children(container, children):
        """Write a container's nested placements — the component's own
        internal sharing, kept instead of flattened."""
        for ci, c in children:
            translation, matrix3x3 = _instance_placement(c.xform)
            container.add_instance(
                handles[ci],
                name=c.name,
                translation=translation,
                matrix3x3=matrix3x3,
                layer=layer_handles.get(getattr(c, "layer", None)),
            )

    # Definitions come first and in registration order — post-order, so a
    # definition is always closed before the one that places it is opened,
    # which is the only order this format accepts.
    handles: list = []
    for d in defs:
        with builder.add_component_definition(d["name"]) as defn:
            for face in d["mesh"].faces:
                _emit_face(defn, face, mat_handles, layer_handles, SkpWriteError)
            _place_children(defn, d["children"])
        handles.append(defn)

    for g, kids in classic:
        with builder.add_group(
                g.name, layer=layer_handles.get(getattr(g, "layer", None))) as grp:
            for face in g.mesh.faces:
                _emit_face(grp, face, mat_handles, layer_handles, SkpWriteError)
            _place_children(grp, kids)

    for face in loose_faces:
        _emit_face(builder, face, mat_handles, layer_handles, SkpWriteError)

    for di, g in roots:
        translation, matrix3x3 = _instance_placement(g.xform)
        builder.add_instance(
            handles[di],
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
