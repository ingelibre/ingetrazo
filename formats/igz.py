# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Native IngeTrazo document format (``.igz``).

Plain JSON, schema-versioned. Trivial to inspect, edit by hand, and diff
in source control. Will grow as new entity types (faces, groups,
components, materials) land — old documents must keep loading.

Layout::

    {
      "igz_format": 1,
      "app_version": __version__,
      "scene": {
        "edges": [
          {"a": [x, y, z], "b": [x, y, z]},
          ...
        ],
        "faces": [
          {"vertices": [[x, y, z], ...]}
        ]
      }
    }

**Textured documents are ZIP containers** (format 2). A texture is an image
*file*, so a plain-JSON document could only point at one — an absolute path
that broke the moment the ``.igz`` travelled to another machine. When the scene
uses textures the document becomes a ZIP holding the very same JSON as
``document.json`` plus the images under ``textures/``, and each texture entry
carries ``"embed": "textures/<hash>-<name>"`` instead of ``"path"``. The
document is then **self-contained and portable**. Opening one unpacks the
images into the app's texture cache (content-addressed, so documents sharing an
image share the file and the GPU upload) and points the entries back at real
paths — the rest of the app keeps seeing ``attrs["texture"]["path"]`` and knows
nothing about containers.

Untextured documents stay **plain JSON at format 1**: the common case remains
diffable, hand-editable, and readable by older builds. ``load_into`` sniffs the
ZIP magic, so both shapes open transparently.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.version import __version__

from PySide6.QtGui import QVector3D

from core.dimension import Dimension
from core.group import Group
from core.mesh import Mesh
from georef.datum import SceneDatum
from georef.geopath import GeoPath


PLAIN_FORMAT = 1        # bare JSON document (no images to carry)
CURRENT_FORMAT = 2      # ZIP container: document.json + textures/
_ZIP_MAGIC = b"PK\x03\x04"
_DOC_ENTRY = "document.json"
_TEX_PREFIX = "textures/"
# Fixed timestamp for every archive member: two saves of the same scene must
# produce byte-identical files (diffable documents, and no pointless churn in
# whatever the user syncs them with).
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


# Keys the texture walk never needs to enter: pure coordinate blocks, and
# the edge list (fixed ``_edge_json`` schema — no attrs, no textures).
# Descending into every vertex triple and edge dict made the walk itself
# cost seconds on a 300k-face document.
_TEXTURE_WALK_SKIP = frozenset(("vertices", "holes", "a", "b", "edges"))


def _texture_entries(node):
    """Yield every ``"texture"`` dict inside a serialized payload — face
    materials, back-side materials (``attrs["back"]``), and whatever nests one
    later. Walking the JSON keeps this honest as the schema grows: a new place
    to hang a texture is embedded without touching this module. Coordinate
    blocks (:data:`_TEXTURE_WALK_SKIP`) and leaf value lists are skipped —
    they are the bulk of the document and can never carry a texture."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "texture" and isinstance(value, dict):
                yield value
            elif key not in _TEXTURE_WALK_SKIP:
                yield from _texture_entries(value)
    elif isinstance(node, list):
        if node and not isinstance(node[0], (dict, list)):
            return                       # a leaf value list (colour, offsets)
        for value in node:
            yield from _texture_entries(value)


def _pack_textures(payload) -> tuple[dict, int]:
    """Rewrite the payload's texture entries in place for storage inside the
    container: ``"path"`` (a machine-local absolute path) → ``"embed"`` (an
    archive member name). Returns ``({member name: image bytes}, missing)``,
    where *missing* counts images whose file could not be read — those keep
    their ``"path"``, so a document whose cache was wiped saves no worse than
    before instead of losing the reference outright."""
    import hashlib

    blobs: dict = {}
    resolved: dict = {}          # source path → member name ("" = unreadable)
    missing = 0
    for tex in _texture_entries(payload):
        src = tex.get("path")
        if not src:
            continue
        member = resolved.get(src)
        if member is None:
            try:
                data = Path(src).read_bytes()
            except OSError:
                resolved[src] = ""
                missing += 1
                continue
            digest = hashlib.sha1(data).hexdigest()[:16]
            safe = "".join(c for c in Path(src).name
                           if c.isalnum() or c in " ._-").strip(" .")
            member = f"{_TEX_PREFIX}{digest}-{safe or 'texture.png'}"
            resolved[src] = member
            blobs[member] = data
        if member:
            tex.pop("path", None)
            tex["embed"] = member
    return blobs, missing


def _unpack_textures(payload, archive) -> None:
    """Inverse of :func:`_pack_textures`: extract each embedded image into the
    app's texture cache and point the entry back at that real file, so
    everything downstream (renderer, exporters) keeps working with paths. A
    member the archive lost leaves the entry without a texture path — the face
    renders untextured rather than the load failing."""
    from core.texture import cache_image

    unpacked: dict = {}
    for tex in _texture_entries(payload):
        member = tex.pop("embed", None)
        if not member or tex.get("path"):
            continue
        out = unpacked.get(member)
        if out is None:
            try:
                data = archive.read(member)
            except KeyError:
                continue
            # Drop the member's hash prefix — cache_image re-derives it from
            # the bytes, and the same image must land on the same cached file
            # whether it arrived in a document or straight from a .skp.
            name = member.rsplit("/", 1)[-1].split("-", 1)[-1]
            out = str(cache_image(data, name, "embedded"))
            unpacked[member] = out
        tex["path"] = out


def _face_json(f) -> dict:
    entry = {"vertices": [list(v.position.toTuple()) for v in f.loop]}
    # Holes are written only when present, so simple documents stay terse and
    # older readers ignore the extra key gracefully.
    if getattr(f, "hole_loops", None):
        entry["holes"] = [
            [list(v.position.toTuple()) for v in loop] for loop in f.hole_loops
        ]
    # Material colour (the Paint tool), written only when set.
    color = getattr(f, "attrs", {}).get("color")
    if color is not None:
        entry["color"] = list(color)
    texture = getattr(f, "attrs", {}).get("texture")
    if texture is not None:
        entry["texture"] = dict(texture)
    layer = getattr(f, "attrs", {}).get("layer")
    if layer is not None:
        entry["layer"] = layer
    ifc = getattr(f, "attrs", {}).get("ifc")
    if ifc is not None:
        entry["ifc"] = dict(ifc)
    opacity = getattr(f, "attrs", {}).get("opacity")
    if opacity is not None:
        entry["opacity"] = float(opacity)
    # Material identity (core.materials): the registry name this face was
    # painted with. Written only when present; older readers ignore it.
    mat = getattr(f, "attrs", {}).get("mat")
    if mat:
        entry["mat"] = mat
    back = getattr(f, "attrs", {}).get("back")
    if isinstance(back, dict):
        # Deep-copy the nested texture: _pack_textures rewrites the entries it
        # finds, and it must never reach into the live scene's attrs.
        entry["back"] = {k: dict(v) if isinstance(v, dict) else v
                         for k, v in back.items()}
    return entry


def _edge_json(e) -> dict:
    entry = {"a": list(e.v0.position.toTuple()),
             "b": list(e.v1.position.toTuple())}
    if getattr(e, "soft", False):
        entry["soft"] = True
    if getattr(e, "curve", None) is not None:
        entry["curve"] = e.curve
    if getattr(e, "layer", None) is not None:
        entry["layer"] = e.layer
    return entry


def _mesh_json(mesh) -> dict:
    return {
        "edges": [_edge_json(e) for e in mesh.edges],
        "faces": [_face_json(f) for f in mesh.faces],
    }


def save_scene(scene, path: Path) -> dict:
    """Write ``scene`` to ``path``. Returns ``{"embedded", "missing"}``: how
    many texture images were packed into the document, and how many could not
    be read (those keep pointing at their original path)."""
    # Accept a Scene or a bare Mesh (the M1 read-compat path feeds a Mesh).
    mesh = scene.mesh if hasattr(scene, "mesh") else scene
    payload = _mesh_json(mesh)
    groups = getattr(scene, "groups", None)
    if groups:
        payload["groups"] = []
        # Component prototypes: each shared instance mesh is written ONCE.
        proto_index: dict = {}
        protos: list = []
        for g in groups:
            if getattr(g, "xform", None) is not None \
                    and id(g.mesh) not in proto_index:
                proto_index[id(g.mesh)] = len(protos)
                protos.append(_mesh_json(g.mesh))
        if protos:
            payload["protos"] = protos
        for g in groups:
            if getattr(g, "xform", None) is not None:
                entry = {"proto": proto_index[id(g.mesh)],
                         "xform": [float(x) for x in g.xform.data()]}
            else:
                entry = _mesh_json(g.mesh)
            if getattr(g, "layer", None) is not None:
                entry["layer"] = g.layer
            if getattr(g, "ifc", None):
                entry["ifc"] = dict(g.ifc)
            if getattr(g, "billboard", False):
                # True = legacy textured-quad face-me; "mesh" = imported
                # silhouette whose real geometry turns toward the camera.
                entry["billboard"] = g.billboard
            payload["groups"].append(entry)
    layers = getattr(scene, "layers", None)
    if layers is not None and (len(layers) > 1 or any(
            not ly.visible or ly.locked for ly in layers)):
        payload["layers"] = [ly.to_dict() for ly in layers]
    views = getattr(scene, "saved_views", None)
    if views:
        payload["saved_views"] = [v.to_dict() for v in views]
    comps = getattr(scene, "compositions", None)
    if comps:
        payload["compositions"] = [c.to_dict() for c in comps]
    dims = getattr(scene, "dimensions", None)
    if dims:
        payload["dimensions"] = [
            {"a": [d.a.x(), d.a.y(), d.a.z()],
             "b": [d.b.x(), d.b.y(), d.b.z()],
             "offset": [d.offset.x(), d.offset.y(), d.offset.z()]}
            for d in dims
        ]
    mats = getattr(scene, "materials", None)
    if mats:
        payload["materials"] = [m.to_dict() for m in mats.values()]
    style = getattr(scene, "dimension_style", None)
    if style:
        payload["dimension_style"] = dict(style)
    back = getattr(scene, "back_face_color", None)
    if back:
        payload["back_face_color"] = list(back)
    # Georeferencing datum (Track G) — optional block, written only when set so
    # ungeoreferenced documents stay terse and older readers ignore it.
    datum = getattr(scene, "georef", None)
    if datum is not None:
        payload["georef"] = {"datum": datum.to_dict()}
    # Base-map capture (Track G, G1). Only the capture rectangle and the
    # source, never the tiles — see TileLayer.to_dict.
    tile_layer = getattr(scene, "tile_layer", None)
    if tile_layer is not None:
        payload["tile_layer"] = tile_layer.to_dict()
    paths = getattr(scene, "geo_paths", None)
    if paths:
        payload["geo_paths"] = [p.to_dict() for p in paths]
    points = getattr(scene, "geo_points", None)
    if points:
        payload["geo_points"] = [p.to_dict() for p in points]
    labels = getattr(scene, "text_labels", None)
    if labels:
        payload["text_labels"] = [t.to_dict() for t in labels]
    guides = getattr(scene, "guides", None)
    if guides:
        payload["guides"] = [g.to_dict() for g in guides]
    # Images ride INSIDE the document (see the module docstring). Only a scene
    # that actually has textures pays for the container; everything else stays
    # plain JSON at format 1, readable by older builds.
    blobs, missing = _pack_textures(payload)
    # The photogrammetric survey (Track G, G6) rides inside the document too,
    # for the same reason the textures do: a reference mesh that lives in a
    # folder next to the .igz is one move away from being lost.
    survey = getattr(scene, "photo_mesh", None)
    if survey is not None and getattr(survey, "triangle_count", 0):
        from georef.photomesh import pack_mesh
        meta, survey_blobs = pack_mesh(survey)
        payload["photo_mesh"] = meta
        blobs.update(survey_blobs)
    data = {
        "igz_format": CURRENT_FORMAT if blobs else PLAIN_FORMAT,
        "app_version": __version__,
        "scene": payload,
    }
    doc = json.dumps(data, indent=2)
    if blobs:
        _write_container(path, doc, blobs)
    else:
        _write_atomic(path, doc.encode("utf-8"))
    return {"embedded": len(blobs), "missing": missing}


def _write_atomic(path: Path, data: bytes) -> None:
    """Write via a sibling temp file + rename: a failure mid-write must not
    leave the user's existing document truncated."""
    tmp = path.with_name(path.name + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _write_container(path: Path, doc: str, blobs: dict) -> None:
    """The ZIP shape: ``document.json`` deflated, images stored as-is (PNG/JPG
    are already compressed — deflating them again costs time for nothing)."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(_DOC_ENTRY, date_time=_ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, doc)
        for member in sorted(blobs):
            info = zipfile.ZipInfo(member, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, blobs[member])
    _write_atomic(path, buf.getvalue())


def _read_document(path: Path):
    """``(data, archive)`` for a document of either shape — the archive is
    ``None`` for a plain-JSON one, and stays open while the caller extracts
    embedded images."""
    raw = path.read_bytes()
    if not raw.startswith(_ZIP_MAGIC):
        return json.loads(raw.decode("utf-8")), None
    import zipfile
    archive = zipfile.ZipFile(path)
    try:
        data = json.loads(archive.read(_DOC_ENTRY).decode("utf-8"))
    except KeyError:
        archive.close()
        raise ValueError(
            f"{path.name} is not an IngeTrazo document (no {_DOC_ENTRY}).")
    return data, archive


def _unpack_photo_mesh(payload: dict, archive):
    """Rebuild the stored survey, or ``None`` when the document has none."""
    meta = payload.get("photo_mesh")
    if not meta:
        return None
    from georef.photomesh import unpack_mesh

    def read_blob(member: str) -> bytes:
        try:
            return archive.read(member)
        except KeyError:
            return b""

    return unpack_mesh(meta, read_blob)


def load_into(scene, path: Path) -> None:
    """Replace ``scene`` contents with what's stored at ``path``."""
    import gc

    # Mass object construction ahead — see formats.skp.apply_payload: the
    # generational GC re-scanning the growing heap can dominate big loads.
    _gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        _load_into_inner(scene, path)
    finally:
        if _gc_was_enabled:
            gc.enable()


def _load_into_inner(scene, path: Path) -> None:
    data, archive = _read_document(path)
    survey = None
    try:
        if archive is not None:
            _unpack_textures(data.get("scene", {}), archive)
            # Rebuilt here, while the archive is still open — it closes below
            # and the survey's blobs live inside it.
            survey = _unpack_photo_mesh(data.get("scene", {}), archive)
    finally:
        if archive is not None:
            archive.close()
    fmt = data.get("igz_format", 1)
    if fmt > CURRENT_FORMAT:
        raise ValueError(
            f"Document format v{fmt} is newer than this build (v{CURRENT_FORMAT})."
        )

    payload = data.get("scene", {})

    scene.mesh.clear()
    scene.selection.clear()
    scene.groups.clear()
    scene.geo_paths.clear()
    scene.geo_points.clear()
    scene.text_labels.clear()
    scene.georef = None
    scene.photo_mesh = survey
    scene.tile_layer = None

    _load_mesh(scene.mesh, payload)
    raw_layers = payload.get("layers")
    if raw_layers:
        from core.layers import DEFAULT_LAYER, Layer
        scene.layers = [Layer.from_dict(r) for r in raw_layers]
        if not any(ly.name == DEFAULT_LAYER for ly in scene.layers):
            scene.layers.insert(0, Layer(DEFAULT_LAYER))
    raw_tiles = payload.get("tile_layer")
    if raw_tiles:
        from georef.tiles import TileLayer
        try:
            scene.tile_layer = TileLayer.from_dict(raw_tiles)
        except Exception:  # noqa: BLE001 — a bad block costs the map, not the file
            scene.tile_layer = None
    from core.materials import Material
    scene.materials = {}
    for raw in payload.get("materials", []):
        mat = Material.from_dict(raw)
        if mat.name:
            scene.materials[mat.name] = mat
    from core.saved_views import SavedView
    scene.saved_views = [SavedView.from_dict(r)
                         for r in payload.get("saved_views", [])]
    from core.composition import Composicion
    scene.compositions = [Composicion.from_dict(r)
                          for r in payload.get("compositions", [])]
    proto_meshes: list = []
    for raw in payload.get("protos", []):
        m = Mesh()
        _load_mesh(m, raw)
        proto_meshes.append(m)
    for raw in payload.get("groups", []):
        if raw.get("xform") is not None and "proto" in raw:
            from PySide6.QtGui import QMatrix4x4
            group = Group(proto_meshes[int(raw["proto"])])
            vals = [float(x) for x in raw["xform"]]
            # data() is column-major; the constructor takes row-major.
            rm = [vals[col * 4 + row] for row in range(4) for col in range(4)]
            group.xform = QMatrix4x4(*rm)
        else:
            group = Group()
            _load_mesh(group.mesh, raw)
        if raw.get("layer"):
            group.layer = raw["layer"]
        if raw.get("ifc"):
            group.ifc = dict(raw["ifc"])
        if raw.get("billboard"):
            group.billboard = raw["billboard"]   # True | "mesh"
        scene.groups.append(group)

    for raw in payload.get("dimensions", []):
        scene.dimensions.append(Dimension(
            QVector3D(*raw["a"]), QVector3D(*raw["b"]),
            QVector3D(*raw["offset"])))

    style = payload.get("dimension_style")
    if isinstance(style, dict):
        scene.dimension_style.update(style)

    back = payload.get("back_face_color")
    if isinstance(back, list) and len(back) == 3:
        scene.back_face_color = tuple(float(c) for c in back)

    georef = payload.get("georef")
    if isinstance(georef, dict) and isinstance(georef.get("datum"), dict):
        scene.georef = SceneDatum.from_dict(georef["datum"])

    for raw in payload.get("geo_paths", []):
        scene.geo_paths.append(GeoPath.from_dict(raw))

    from georef.points import GeoPoint
    for raw in payload.get("geo_points", []):
        scene.geo_points.append(GeoPoint.from_dict(raw))

    from core.textlabel import TextLabel
    for raw in payload.get("text_labels", []):
        scene.text_labels.append(TextLabel.from_dict(raw))

    from core.guide import Guide
    scene.guides.clear()
    for raw in payload.get("guides", []):
        scene.guides.append(Guide.from_dict(raw))

    scene.version += 1


def _face_attrs_from_json(raw) -> dict | None:
    attrs: dict = {}
    color = raw.get("color")
    if color is not None:
        attrs["color"] = list(color)
    texture = raw.get("texture")
    if texture is not None:
        attrs["texture"] = dict(texture)
    if raw.get("layer"):
        attrs["layer"] = raw["layer"]
    if raw.get("ifc"):
        attrs["ifc"] = dict(raw["ifc"])
    if raw.get("opacity") is not None:
        attrs["opacity"] = float(raw["opacity"])
    if raw.get("mat"):
        attrs["mat"] = raw["mat"]
    if isinstance(raw.get("back"), dict):
        attrs["back"] = dict(raw["back"])
    return attrs or None


def _load_mesh_small(mesh, payload) -> None:
    """The plain per-entity walk — faster than the bulk pass's fixed NumPy
    cost for the many small groups a document can carry."""
    import core.mesh as _mesh_mod
    for raw in payload.get("edges", []):
        try:
            edge = mesh.add_edge(QVector3D(*raw["a"]), QVector3D(*raw["b"]))
        except ValueError:
            continue  # degenerate edge in the document — skip
        if raw.get("soft"):
            edge.soft = True
        if raw.get("layer"):
            edge.layer = raw["layer"]
        cid = raw.get("curve")
        if cid is not None:
            edge.curve = cid
            # Keep new curves unique after loading stored ids.
            if cid >= _mesh_mod._CURVE_COUNTER:
                _mesh_mod._CURVE_COUNTER = cid + 1
    for raw in payload.get("faces", []):
        verts = [QVector3D(*v) for v in raw["vertices"]]
        holes = [[QVector3D(*v) for v in loop] for loop in raw.get("holes", [])]
        face = mesh.add_face(verts, holes)
        attrs = _face_attrs_from_json(raw)
        if attrs:
            face.attrs.update(attrs)


def _load_mesh(mesh, payload) -> None:
    """Rebuild a mesh from its JSON block in ONE bulk pass: every edge
    endpoint and face corner welds through :meth:`Mesh.bulk_weld` at once,
    then the edges and faces are created vectorized — the per-entity
    ``add_edge``/``add_face`` walk dominated opening big documents. Small
    groups take the plain walk (the bulk pass's fixed cost loses there)."""
    import numpy as np
    import core.mesh as _mesh_mod
    from core.topology import _maximal_holes

    raw_edges = payload.get("edges", [])
    raw_faces = payload.get("faces", [])
    if len(raw_edges) + len(raw_faces) * 4 < 1024:   # ~corner estimate
        _load_mesh_small(mesh, payload)
        return
    flat: list = []
    for raw in raw_edges:
        flat.append(raw["a"])
        flat.append(raw["b"])
    n_edge_pts = len(flat)
    ring_sizes: list = []
    ring_counts: list = []
    attrs_list: list = []
    for raw in raw_faces:
        verts = raw["vertices"]
        holes = raw.get("holes", [])
        if len(holes) > 1:
            qholes = _maximal_holes(
                [[QVector3D(*v) for v in loop] for loop in holes])
            holes = [[(p.x(), p.y(), p.z()) for p in loop] for loop in qholes]
        ring_counts.append(1 + len(holes))
        ring_sizes.append(len(verts))
        flat.extend(verts)
        for loop in holes:
            ring_sizes.append(len(loop))
            flat.extend(loop)
        attrs_list.append(_face_attrs_from_json(raw))
    if not flat:
        return
    vobjs, inverse = mesh.bulk_weld(np.array(flat, dtype=np.float64))
    emap = None
    if raw_edges:
        flags = []
        max_curve = None
        for raw in raw_edges:
            cid = raw.get("curve")
            if cid is not None and (max_curve is None or cid > max_curve):
                max_curve = cid
            flags.append((bool(raw.get("soft")), cid, raw.get("layer")))
        emap = mesh.add_edges_welded(
            vobjs, inverse[0:n_edge_pts:2], inverse[1:n_edge_pts:2], flags)
        # Keep new curves unique after loading stored ids.
        if max_curve is not None and max_curve >= _mesh_mod._CURVE_COUNTER:
            _mesh_mod._CURVE_COUNTER = max_curve + 1
    if ring_counts:
        mesh.add_faces_welded(vobjs, inverse[n_edge_pts:], ring_sizes,
                              ring_counts, attrs_list, edge_map=emap)
