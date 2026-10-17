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

**Large documents are format 3** (see ``_LARGE_DOCUMENT``): always a ZIP, and
each big mesh is a ``{"geom": {...}}`` block instead of ``edges``/``faces``
lists — its distinct points once as float32, edges and face rings as int32
indices, edge flags and a shared table of face attributes, in one raw
member under ``geom/`` (layout in the JSON, no pickles). Builds that read
only up to format 2 refuse it with a message instead of opening it empty.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from core.version import __version__

from PySide6.QtGui import QVector3D

from core.dimension import Dimension
from core.group import Group
from core.mesh import Mesh
from georef.datum import SceneDatum
from georef.geopath import GeoPath


PLAIN_FORMAT = 1        # bare JSON document (no images to carry)
CONTAINER_FORMAT = 2    # ZIP container: document.json + textures/
GEOMETRY_FORMAT = 3     # + big meshes as binary blocks under geom/
CURRENT_FORMAT = GEOMETRY_FORMAT   # the newest this build reads
_ZIP_MAGIC = b"PK\x03\x04"
_DOC_ENTRY = "document.json"
_TEX_PREFIX = "textures/"
# Fixed timestamp for every archive member: two saves of the same scene must
# produce byte-identical files (diffable documents, and no pointless churn in
# whatever the user syncs them with).
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# A document with more faces + edges than this is written COMPACT (no
# indentation) and deflated at level 1. Indented, the 14 M-face model of
# #158 was 3.3 GB of text — every coordinate on a line of its own — and
# saving it peaked at 16 GB of memory; compact it is 1.4 GB, and level 1
# deflates it in 4 s instead of 20 (the file grows ~35 %). Nobody reads a
# document that size by hand, while a small one stays indented and
# diffable, at the default level where deflating costs nothing anyway.
_LARGE_DOCUMENT = 20_000

# Format 3 — a LARGE document (above) stores each mesh of at least this many
# corners as a binary block instead of JSON lists: every distinct point once
# as float32 (exactly what the QVector3D of the live mesh holds, so nothing
# is lost), and edges and faces as int32 indices into it. On the #158 model
# the JSON spelled out 19 M points to describe 2 M distinct ones, and
# parsing that text was half of the minute it took to open. Structure —
# groups, layers, materials, the face attributes — stays JSON. Small meshes
# stay JSON too: the reader rebuilds a small mesh entity by entity, a big
# one in one bulk pass (see :func:`_bulk_sized`), and the two number their
# vertices differently — a mesh goes binary only where the JSON reader
# would take the bulk pass, so either way it reopens the same.
_GEOM_PREFIX = "geom/"
_BULK_MIN = 1024
#: The dtypes a geometry block may declare — anything else is refused, so a
#: crafted document cannot make the reader build arbitrary objects.
_GEOM_DTYPES = frozenset(("<f4", "<i4", "<i8", "|u1"))


# Keys the texture walk never needs to enter: pure coordinate blocks, and
# the edge list (fixed ``_edge_json`` schema — no attrs, no textures).
# Descending into every vertex triple and edge dict made the walk itself
# cost seconds on a 300k-face document.
_TEXTURE_WALK_SKIP = frozenset(("vertices", "holes", "a", "b", "edges",
                                "arrays"))


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
    from core.texture import is_image_file, texture_file_name

    blobs: dict = {}
    resolved: dict = {}          # source path → member name ("" = unreadable)
    missing = 0
    def _member_for(src):
        nonlocal missing
        member = resolved.get(src)
        if member is None:
            if not is_image_file(src):
                resolved[src] = ""
                missing += 1
                return ""
            try:
                data = Path(src).read_bytes()
            except OSError:
                resolved[src] = ""
                missing += 1
                return ""
            digest = hashlib.sha1(data).hexdigest()[:16]
            # ``src`` is usually a cached file already named ``<hash>-<name>``:
            # texture_file_name drops that prefix, so the member is always
            # ``<hash>-<name>`` and never grows with the number of saves.
            member = f"{_TEX_PREFIX}{digest}-{texture_file_name(Path(src).name)}"
            resolved[src] = member
            blobs[member] = data
        return member

    for tex in _texture_entries(payload):
        src = tex.get("path")
        if src:
            member = _member_for(src)
            if member:
                tex.pop("path", None)
                tex["embed"] = member
        # A colourized entry also carries its UNTINTED source: without it a
        # document opened on another machine could only re-tint the tinted
        # image, and "remove colour" would have nothing to go back to. The
        # blobs map is content-addressed, so a base shared with another
        # material (or with an untinted face) costs nothing extra.
        base = tex.get("base")
        if base:
            member = _member_for(base)
            if member:
                tex.pop("base", None)
                tex["base_embed"] = member
    return blobs, missing


def _unpack_textures(payload, archive) -> None:
    """Inverse of :func:`_pack_textures`: extract each embedded image into the
    app's texture cache and point the entry back at that real file, so
    everything downstream (renderer, exporters) keeps working with paths. A
    member the archive lost leaves the entry without a texture path — the face
    renders untextured rather than the load failing."""
    from core.texture import cache_image

    unpacked: dict = {}

    def _restore(member):
        """The cached file for an archive member, or None. cache_image drops
        the member's hash prefix(es) and re-derives one from the bytes, so the
        same image lands on the same cached file whether it arrived in a
        document (even one whose member name was bloated by 0.3.10's
        stacking) or straight from a .skp."""
        out = unpacked.get(member)
        if out is None:
            try:
                data = archive.read(member)
            except KeyError:
                return None
            name = member.rsplit("/", 1)[-1]
            try:
                out = str(cache_image(data, name, "embedded"))
            except OSError:
                out = ""        # unwritable cache: the face loses its image
            unpacked[member] = out
        return out or None

    for tex in _texture_entries(payload):
        base_member = tex.pop("base_embed", None)
        if base_member and not tex.get("base"):
            restored = _restore(base_member)
            if restored:
                tex["base"] = restored
        member = tex.pop("embed", None)
        if not member or tex.get("path"):
            continue
        out = _restore(member)
        if out:
            tex["path"] = out


def _face_json(f) -> dict:
    entry = {"vertices": [list(v.position.toTuple()) for v in f.loop]}
    # Holes are written only when present, so simple documents stay terse and
    # older readers ignore the extra key gracefully.
    if getattr(f, "hole_loops", None):
        entry["holes"] = [
            [list(v.position.toTuple()) for v in loop] for loop in f.hole_loops
        ]
    entry.update(_face_attrs_json(f))
    return entry


def _face_attrs_json(f) -> dict:
    """Everything a face stores besides its loops — the part a format-3
    geometry block keeps as JSON, in a table shared by equal faces."""
    entry: dict = {}
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
    if getattr(f, "attrs", {}).get("hidden"):
        entry["hidden"] = True          # Hide on a face
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
    elif back is True:
        # A two-sided face: the back mirrors the front (what the mesh
        # formats describe, and what a .skp face painted the same on
        # both sides becomes). Absent = the style's default back.
        entry["back"] = True
    return entry


def _edge_json(e) -> dict:
    entry = {"a": list(e.v0.position.toTuple()),
             "b": list(e.v1.position.toTuple())}
    if getattr(e, "soft", False):
        entry["soft"] = True
    if getattr(e, "hidden", False):
        entry["hidden"] = True
    if getattr(e, "curve", None) is not None:
        entry["curve"] = e.curve
    if getattr(e, "layer", None) is not None:
        entry["layer"] = e.layer
    return entry


def _mesh_json(mesh, geom_sink=None) -> dict:
    """The mesh block. With a ``geom_sink`` (a large document) a big mesh
    goes to a binary block in the sink and the JSON keeps only its
    reference and face-attribute table (format 3)."""
    if geom_sink is not None and _bulk_sized(len(mesh.edges),
                                             len(mesh.faces)):
        return {"geom": _pack_geometry(mesh, geom_sink)}
    return {
        "edges": [_edge_json(e) for e in mesh.edges],
        "faces": [_face_json(f) for f in mesh.faces],
    }


def _bulk_sized(n_edges: int, n_faces: int) -> bool:
    """Whether a mesh this size is rebuilt in one bulk pass (a rough corner
    count) — the same test for the JSON reader and the format-3 writer."""
    return n_edges + n_faces * 4 >= _BULK_MIN


def _pack_geometry(mesh, sink: dict) -> dict:
    """Write ``mesh`` as a format-3 geometry block into ``sink`` (member
    name → bytes) and return its JSON side.

    The points are numbered in the order a JSON document lists them —
    every edge's two ends, then every face's outer ring and holes — so
    the reader's weld meets them in the same order and rebuilds the same
    vertices. Holes nested in a bigger hole are dropped here, where the
    JSON reader drops them (:func:`core.topology._maximal_holes`)."""
    import numpy as np
    from core.topology import _maximal_holes

    edges = mesh.edges
    corners: list = []
    for e in edges:
        corners.append(e.v0)
        corners.append(e.v1)
    ring_sizes: list = []
    ring_counts: list = []
    face_attr: list = []
    table: list = []
    table_index: dict = {}
    for f in mesh.faces:
        loop = f.loop
        holes = f.hole_loops or ()
        if len(holes) > 1:
            pos = [[QVector3D(v.position) for v in h] for h in holes]
            kept = {id(k) for k in _maximal_holes(pos)}
            holes = [h for h, p in zip(holes, pos) if id(p) in kept]
        ring_counts.append(1 + len(holes))
        ring_sizes.append(len(loop))
        corners.extend(loop)
        for h in holes:
            ring_sizes.append(len(h))
            corners.extend(h)
        attrs = _face_attrs_json(f) if f.attrs else None
        if attrs:
            key = json.dumps(attrs, sort_keys=True, separators=(",", ":"))
            k = table_index.get(key)
            if k is None:
                k = table_index[key] = len(table)
                table.append(attrs)
            face_attr.append(k)
        else:
            face_attr.append(-1)

    # Number the vertex objects by first appearance.
    ids = np.fromiter((id(v) for v in corners), dtype=np.uint64,
                      count=len(corners))
    _u, first, inverse = np.unique(ids, return_index=True,
                                   return_inverse=True)
    order = np.argsort(first, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    index = rank[inverse.reshape(-1)].astype(np.int32)
    pos = np.array([corners[i].position.toTuple()
                    for i in first[order].tolist()],
                   dtype=np.float32).reshape(-1, 3)
    if not np.isfinite(pos).all():
        raise NonFiniteDocumentError("geometry")

    ne = len(edges)
    arrays = {
        "pos": pos,
        "edges": index[:2 * ne].reshape(-1, 2),
        "rings": index[2 * ne:],
        "ring_sizes": np.asarray(ring_sizes, dtype=np.int32),
        "ring_counts": np.asarray(ring_counts, dtype=np.int32),
        "face_attr": np.asarray(face_attr, dtype=np.int32),
    }
    flags = np.zeros(ne, dtype=np.uint8)
    curves = layers = None
    layer_table: list = []
    layer_index: dict = {}
    for i, e in enumerate(edges):
        if e.soft:
            flags[i] |= 1
        if e.hidden:
            flags[i] |= 2
        if e.curve is not None:
            if curves is None:
                curves = np.full(ne, -1, dtype=np.int64)
            curves[i] = e.curve
        if e.layer is not None:
            if layers is None:
                layers = np.full(ne, -1, dtype=np.int32)
            k = layer_index.get(e.layer)
            if k is None:
                k = layer_index[e.layer] = len(layer_table)
                layer_table.append(e.layer)
            layers[i] = k
    arrays["edge_flags"] = flags
    if curves is not None:
        arrays["edge_curve"] = curves
    if layers is not None:
        arrays["edge_layer"] = layers

    # One raw blob, each array at an 8-byte-aligned offset: no pickles, no
    # per-save timestamps (an .npz carries them), so two saves of the same
    # model stay byte-identical.
    layout: dict = {}
    chunks: list = []
    offset = 0
    for name, arr in arrays.items():
        arr = np.ascontiguousarray(arr)
        data = arr.tobytes()
        layout[name] = [arr.dtype.str, list(arr.shape), offset]
        pad = (-len(data)) % 8
        chunks.append(data + b"\0" * pad)
        offset += len(data) + pad
    member = f"{_GEOM_PREFIX}{len(sink)}.bin"
    sink[member] = b"".join(chunks)
    meta = {"member": member, "arrays": layout}
    if table:
        meta["face_attrs"] = table
    if layer_table:
        meta["edge_layers"] = layer_table
    return meta


def save_scene(scene, path: Path) -> dict:
    """Write ``scene`` to ``path``. Returns ``{"embedded", "missing"}``: how
    many texture images were packed into the document, and how many could not
    be read (those keep pointing at their original path)."""
    # Accept a Scene or a bare Mesh (the M1 read-compat path feeds a Mesh).
    mesh = scene.mesh if hasattr(scene, "mesh") else scene
    # Decided BEFORE anything is serialized: a large document writes its
    # big meshes as binary blocks (format 3) and never builds their JSON.
    large = _live_element_count(scene) > _LARGE_DOCUMENT
    geom: dict | None = {} if large else None
    payload = _mesh_json(mesh, geom)
    groups = getattr(scene, "groups", None)
    kept = getattr(scene, "kept_components", None)
    if groups or kept:
        # Component prototypes: each shared instance mesh is written ONCE —
        # including the ones only NESTED placements reference, which is what
        # keeps a component's internal repetition (the hedge: 9600 faces
        # placed 48 times) from being written out 48 times over.
        proto_index: dict = {}
        protos: list = []

        def _entry(g):
            xf = getattr(g, "xform", None)
            if xf is not None:
                idx = proto_index.get(id(g.mesh))
                if idx is None:
                    idx = proto_index[id(g.mesh)] = len(protos)
                    protos.append(None)          # reserve: recursion is depth
                    protos[idx] = _mesh_json(g.mesh, geom)
                entry = {"proto": idx,
                         "xform": [float(x) for x in xf.data()]}
                # Group or component (issue #90): a group of groups and a
                # copied group carry a matrix too. Written for EVERY
                # instance — a file without the key is an older one, which
                # the reader tells apart its own way. Older readers ignore it.
                entry["component"] = bool(getattr(g, "component", True))
            else:
                entry = _mesh_json(g.mesh, geom)
            # The name — never written until 2026-09-11, so every reopened
            # document renumbered its groups and a "Pérgola" came back as
            # "Group 7". Older readers ignore the key.
            if getattr(g, "name", None):
                entry["name"] = g.name
            axes = getattr(g, "axes", None)
            if axes is not None:
                # A classic group's own axes (issue #44), column-major like
                # "xform"; older readers ignore the key.
                entry["axes"] = [float(x) for x in axes.data()]
            if getattr(g, "layer", None) is not None:
                entry["layer"] = g.layer
            if getattr(g, "ifc", None):
                entry["ifc"] = dict(g.ifc)
            if getattr(g, "billboard", False):
                # True = legacy textured-quad face-me; "mesh" = imported
                # silhouette whose real geometry turns toward the camera.
                entry["billboard"] = g.billboard
            if getattr(g, "material", None):
                # The container's own paint (issue #47); older readers
                # ignore the key and show the faces in the default.
                entry["material"] = dict(g.material)
            if getattr(g, "text3d", None):
                # A 3D text keeps what it was made from, so it reopens
                # editable. Older readers ignore the key.
                entry["text3d"] = dict(g.text3d)
            if getattr(g, "ext", None):
                # Extensions' parameters for this container (JSON-safe by
                # contract); older readers ignore the key.
                entry["ext"] = json.loads(json.dumps(g.ext, default=str))
            if getattr(g, "uid", None):
                # The identity a scene's hidden-object list names.
                entry["uid"] = g.uid
            if getattr(g, "hidden", False):
                entry["hidden"] = True
            if getattr(g, "locked", False):
                entry["locked"] = True          # older readers ignore it
            if getattr(g, "exploded", None):
                # An exploded view and each part's share of it, so the
                # document reopens able to reassemble (core/explode.py).
                # Older readers ignore both and see the parts where they
                # stand.
                entry["exploded"] = dict(g.exploded)
            if getattr(g, "explode_offset", None):
                entry["explode_offset"] = list(g.explode_offset)
            kids = getattr(g, "children", None)
            if kids:
                entry["children"] = [_entry(c) for c in kids]
            return entry

        payload["groups"] = [_entry(g) for g in groups or ()]
        if kept:
            # Definitions kept with no copy placed: written like instances
            # through the SAME prototype table, so one still in use is not
            # written twice. Older readers ignore the key (and lose them).
            payload["kept_components"] = [_entry(t) for t in kept]
        if protos:
            payload["protos"] = protos
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
             "offset": [d.offset.x(), d.offset.y(), d.offset.z()],
             **({"axis": d.axis} if getattr(d, "axis", None) else {}),
             **({"layer": d.layer} if getattr(d, "layer", None) else {}),
             **({"text": d.text} if getattr(d, "text", None) else {})}
            for d in dims
        ]
    mats = getattr(scene, "materials", None)
    if mats:
        payload["materials"] = [m.to_dict() for m in mats.values()]
    style = getattr(scene, "dimension_style", None)
    if style:
        payload["dimension_style"] = dict(style)
    cam = getattr(scene, "camera_home", None)
    if isinstance(cam, dict) and _non_finite_where(cam) == "scene":
        payload["camera"] = dict(cam)      # what the author was looking at
    # A camera holding a NaN is left out instead of refusing the save: it is
    # only the view, and the file opens framed on the model (#485). The
    # geometry keeps its own guard below.
    units = getattr(scene, "units", None)
    if isinstance(units, dict) and units != {"length": "m", "precision": 2}:
        payload["units"] = dict(units)     # only when not the metre default
    pdata = getattr(scene, "plugin_data", None)
    if pdata:
        # Extensions' data: JSON-safe by contract; a value that is not is
        # dropped with its key rather than breaking the save.
        import json as _json
        keep = {}
        for key, value in pdata.items():
            try:
                keep[str(key)] = _json.loads(_json.dumps(value))
            except (TypeError, ValueError):
                continue
        if keep:
            payload["plugin_data"] = keep
    scales = getattr(scene, "custom_scales", None)
    if scales:
        payload["custom_scales"] = [float(n) for n in scales]
    back = getattr(scene, "back_face_color", None)
    if back:
        payload["back_face_color"] = list(back)
    splanes = getattr(scene, "section_planes", None)
    if splanes:
        payload["section_planes"] = [sp.to_dict() for sp in splanes]
        vis = {}
        if not getattr(scene, "show_section_planes", True):
            vis["planes_hidden"] = True
        if not getattr(scene, "show_section_cuts", True):
            vis["cuts_hidden"] = True
        if vis:
            payload["section_view"] = vis
    shown = {}
    if getattr(scene, "show_hidden_objects", False):
        shown["objects"] = True
    if getattr(scene, "show_hidden_geometry", False):
        shown["geometry"] = True
    if shown:
        payload["hidden_view"] = shown       # View ▸ Hidden Objects / Geometry
    if not getattr(scene, "show_axes", True):
        payload["axes_hidden"] = True        # Camera ▸ Axes (shown is implicit)
    dstyle = getattr(scene, "display_style", None)
    if dstyle is not None:
        from core.style import Style
        d = dstyle.to_dict()
        if d != Style().to_dict():   # default stays implicit (terse files)
            payload["display_style"] = d
    shadows = getattr(scene, "shadows", None)
    if shadows is not None:
        from core.sun import ShadowSettings
        d = shadows.to_dict()
        if d != ShadowSettings().to_dict():
            payload["shadows"] = d
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
    # Reference images. Written BEFORE the packing step below on purpose:
    # each entry hangs its file under a "texture" key, so the same walk that
    # embeds face textures embeds the scans too.
    images = getattr(scene, "image_planes", None)
    if images:
        payload["image_planes"] = [im.to_dict() for im in images]
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
        "igz_format": (GEOMETRY_FORMAT if geom else
                       CONTAINER_FORMAT if blobs else PLAIN_FORMAT),
        "app_version": __version__,
        "scene": payload,
    }
    try:
        if large:
            doc = json.dumps(data, separators=(",", ":"), allow_nan=False)
        else:
            doc = json.dumps(data, indent=2, allow_nan=False)
    except ValueError:
        # A NaN or an infinity in a coordinate (#185). Python would write
        # it as the bare word NaN — not JSON, and a broken shape for good.
        # Refuse, and leave the file on disk as it was.
        raise NonFiniteDocumentError(_non_finite_where(payload)) from None
    if blobs or geom:
        _write_container(path, doc, blobs, fast=large, deflated=geom)
    else:
        _write_atomic(path, doc.encode("utf-8"))
    return {"embedded": len(blobs), "missing": missing}


def _live_element_count(scene) -> int:
    """Faces + edges the document will hold: the loose mesh, and every
    distinct mesh of the groups (a component prototype is written once,
    however many times it is placed). Only list lengths."""
    mesh = scene.mesh if hasattr(scene, "mesh") else scene
    total = len(mesh.faces) + len(mesh.edges)
    seen: set = set()
    stack = (list(getattr(scene, "groups", None) or ())
             + list(getattr(scene, "kept_components", None) or ()))
    while stack:
        g = stack.pop()
        m = getattr(g, "mesh", None)
        if m is not None and id(m) not in seen:
            seen.add(id(m))
            total += len(m.faces) + len(m.edges)
        stack.extend(getattr(g, "children", None) or ())
    return total


class NonFiniteDocumentError(ValueError):
    """The document holds a coordinate that is not a number; it is not
    written, so the file on disk keeps its last good version."""

    def __init__(self, where: str) -> None:
        from core.i18n import tr
        self.where = where
        super().__init__(tr(
            "The model has a point with invalid coordinates (not a number), "
            "so it was not saved and the file on disk keeps its last good "
            "version. Undo the last step and save again. Where: {where}",
            where=where))


def _non_finite_where(node, path: str = "scene") -> str:
    """The first place in the payload holding a NaN or an infinity."""
    import math as _math
    stack = [(node, path)]
    while stack:
        cur, here = stack.pop()
        if isinstance(cur, float) and not _math.isfinite(cur):
            return here
        if isinstance(cur, dict):
            stack.extend((v, f"{here} › {k}") for k, v in
                         reversed(list(cur.items())))
        elif isinstance(cur, (list, tuple)):
            stack.extend((v, f"{here}[{i}]") for i, v in
                         reversed(list(enumerate(cur))))
    return path


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


def _write_container(path: Path, doc: str, blobs: dict,
                     fast: bool = False, deflated: dict | None = None) -> None:
    """The ZIP shape: ``document.json`` deflated, images stored as-is (PNG/JPG
    are already compressed — deflating them again costs time for nothing).
    ``fast`` deflates at level 1 (see ``_LARGE_DOCUMENT``). ``deflated``
    holds members compressed like the document — the geometry blocks."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(_DOC_ENTRY, date_time=_ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, doc, compresslevel=1 if fast else None)
        for member in sorted(deflated or ()):
            info = zipfile.ZipInfo(member, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, deflated[member],
                        compresslevel=1 if fast else None)
        for member in sorted(blobs):
            info = zipfile.ZipInfo(member, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_STORED
            zf.writestr(info, blobs[member])
    _write_atomic(path, buf.getvalue())


def _parse_json(text, pump=None):
    """``json.loads`` — in a worker thread while ``pump`` keeps the window
    answering, when given. A 3.3 GB document took 24 s in one call, and the
    desktop flagged IngeTrazo as «not responding» after five (Marco, 01-10,
    the model of #158); the parser lets the main thread in every ~0.4 s."""
    if pump is None:
        return json.loads(text, parse_constant=_note_constant)
    import threading
    box: dict = {}

    def work():
        try:
            box["data"] = json.loads(text, parse_constant=_note_constant)
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            box["error"] = exc
    th = threading.Thread(target=work, daemon=True)
    th.start()
    while th.is_alive():
        th.join(0.1)
        pump()
    if "error" in box:
        raise box["error"]
    return box["data"]


def _read_document(path: Path, pump=None):
    """``(data, archive)`` for a document of either shape — the archive is
    ``None`` for a plain-JSON one, and stays open while the caller extracts
    embedded images."""
    raw = path.read_bytes()
    if not raw.startswith(_ZIP_MAGIC):
        return _parse_json(raw.decode("utf-8"), pump), None
    import zipfile
    archive = zipfile.ZipFile(path)
    try:
        data = _parse_json(archive.read(_DOC_ENTRY).decode("utf-8"), pump)
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


def load_into(scene, path: Path, progress=None) -> None:
    """Replace ``scene`` contents with what's stored at ``path``.

    ``progress(fraction, text)``, when given, is called at the loader's
    milestones so the window can show a bar: a big document took seconds
    with nothing on screen and read as frozen (issue #59, @pacaeiro)."""
    import gc

    # Mass object construction ahead — see formats.skp.apply_payload: the
    # generational GC re-scanning the growing heap can dominate big loads.
    _gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        _load_into_inner(scene, path, progress)
    finally:
        if _gc_was_enabled:
            gc.enable()


#: Entities left out of the document being opened because a coordinate
#: is not a number (NaN / inf) — counted per load, reported on the scene.
_dropped_nonfinite = [0]
#: Whether the document text holds any NaN / Infinity at all. The JSON
#: parser reports them as it reads (``parse_constant``), so a clean
#: document — nearly every one — skips the per-coordinate check entirely.
_saw_nonfinite = [False]


def _note_constant(token: str) -> float:
    _saw_nonfinite[0] = True
    return float(token)


def _finite_points(*points) -> bool:
    try:
        return all(math.isfinite(float(c)) for p in points for c in p)
    except (TypeError, ValueError):
        return False


def _without_nonfinite(payload: dict) -> dict:
    """The mesh block minus the edges and faces with a NaN or infinite
    coordinate. One such corner made the WHOLE document unopenable
    («cannot convert float NaN to integer», #185): the rest of the model
    opens, the damaged pieces are left out and counted."""
    if not _saw_nonfinite[0]:
        return payload
    edges = [r for r in payload.get("edges", [])
             if _finite_points(r.get("a", ()), r.get("b", ()))]
    faces = [r for r in payload.get("faces", [])
             if _finite_points(*r.get("vertices", ()),
                               *(p for h in r.get("holes", []) for p in h))]
    dropped = (len(payload.get("edges", [])) - len(edges)
               + len(payload.get("faces", [])) - len(faces))
    if not dropped:
        return payload
    _dropped_nonfinite[0] += dropped
    return dict(payload, edges=edges, faces=faces)


def _normalize_text_curve_ids(payload: dict, geom: dict) -> None:
    """Map stored text curve identities to the engine's integer identities.

    JSON documents can carry named curves. Their segments must stay grouped,
    but the engine's counter and binary geometry writer require integer ids.
    Reserve the document's existing integers first, including binary meshes
    loaded later, so a name cannot collide with an existing numeric curve.
    """
    import core.mesh as _mesh_mod

    def group_meshes(groups, depth=0):
        for raw in groups:
            if not isinstance(raw, dict):
                continue
            # A placement uses its prototype, not any local geometry block.
            if raw.get("xform") is None or "proto" not in raw:
                yield raw
            if depth < 32:             # the same limit as _group_from
                yield from group_meshes(raw.get("children", []) or [],
                                        depth + 1)

    def meshes():
        yield payload
        yield from payload.get("protos", [])
        yield from group_meshes(payload.get("groups", []) or [])
        yield from group_meshes(payload.get("kept_components", []) or [])

    text_edges = []
    binary_meshes = []
    top = _mesh_mod._CURVE_COUNTER - 1
    for block in meshes():
        if "geom" in block:
            binary_meshes.append(block["geom"])
            continue
        for raw in block.get("edges", []):
            cid = raw.get("curve")
            if isinstance(cid, str):
                text_edges.append(raw)
            elif isinstance(cid, int):
                top = max(top, cid)
    if not text_edges:
        return                         # no extra scan of ordinary binary meshes

    for meta in binary_meshes:
        curves = _document_geometry_arrays(meta, geom).get("edge_curve")
        if curves is not None and curves.size:
            top = max(top, int(curves.max()))
    _mesh_mod._CURVE_COUNTER = top + 1
    ids: dict[str, int] = {}
    for raw in text_edges:
        name = raw["curve"]
        if name not in ids:
            ids[name] = Mesh.next_curve_id()
        raw["curve"] = ids[name]


def _load_into_inner(scene, path: Path, progress=None) -> None:
    def tick(frac, text):
        if progress is not None:
            progress(frac, text)

    _dropped_nonfinite[0] = 0
    _saw_nonfinite[0] = False

    tick(0.05, "Reading the document…")
    data, archive = _read_document(
        path, pump=(lambda: tick(0.1, "Reading the document…"))
        if progress is not None else None)
    survey = None
    geom: dict = {}
    try:
        if archive is not None:
            # Format 3's binary geometry blocks, read while the archive is
            # open (it closes below).
            geom = {n: archive.read(n) for n in archive.namelist()
                    if n.startswith(_GEOM_PREFIX)}
            tick(0.2, "Unpacking textures…")
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
    _normalize_text_curve_ids(payload, geom)

    scene.mesh.clear()
    scene.selection.clear()
    scene.groups.clear()
    scene.geo_paths.clear()
    scene.geo_points.clear()
    scene.text_labels.clear()
    scene.georef = None
    scene.photo_mesh = survey
    scene.tile_layer = None
    # The writer leaves a block out when it holds the default (no planes,
    # nothing hidden, no own scales…), so what the file does not bring is
    # reset here — or it leaked from the document open before (#602).
    from core.layers import DEFAULT_LAYER, Layer
    scene.layers = [Layer(DEFAULT_LAYER)]
    scene.section_planes = []
    scene.show_section_planes = True
    scene.show_section_cuts = True
    scene.show_hidden_objects = False
    scene.show_hidden_geometry = False
    scene.show_axes = True
    scene.custom_scales = []
    scene.back_face_color = None
    from core.scene import Scene
    scene.dimension_style = \
        Scene.__dataclass_fields__["dimension_style"].default_factory()

    tick(0.35, "Building geometry…")
    _load_mesh(scene.mesh, payload, geom)
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
    scene.compositions = []
    for r in payload.get("compositions", []):
        # A sheet this version cannot rebuild must not take the model down
        # with it: keep the others, log the one that failed.
        try:
            scene.compositions.append(Composicion.from_dict(r))
        except Exception as exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "sheet %r skipped: %s", r.get("name", "?"), exc)
    proto_meshes: list = []
    import time as _time
    raw_protos = payload.get("protos", [])
    last = _time.monotonic()
    for k, raw in enumerate(raw_protos):
        m = Mesh()
        _load_mesh(m, raw, geom)
        proto_meshes.append(m)
        if _time.monotonic() - last > 0.25:
            # Thousands of components took 25 s here without a word to the
            # window, which the desktop reads as a hang (#158).
            tick(0.35 + 0.25 * k / max(1, len(raw_protos)),
                 "Building geometry…")
            last = _time.monotonic()
    names: list = []

    def _group_from(raw, depth=0):
        name = raw.get("name") or None
        if name:
            names.append(name)
        if raw.get("xform") is not None and "proto" in raw:
            from PySide6.QtGui import QMatrix4x4
            group = Group(proto_meshes[int(raw["proto"])], name=name)
            vals = [float(x) for x in raw["xform"]]
            # data() is column-major; the constructor takes row-major.
            rm = [vals[col * 4 + row] for row in range(4) for col in range(4)]
            group.xform = QMatrix4x4(*rm)
        else:
            group = Group(name=name)
            _load_mesh(group.mesh, raw, geom)
        if isinstance(raw.get("axes"), list) and len(raw["axes"]) == 16:
            from PySide6.QtGui import QMatrix4x4
            vals = [float(x) for x in raw["axes"]]
            group.axes = QMatrix4x4(*[vals[col * 4 + row] for row in range(4)
                                      for col in range(4)])
        if raw.get("layer"):
            group.layer = raw["layer"]
        if raw.get("ifc"):
            group.ifc = dict(raw["ifc"])
        if raw.get("billboard"):
            group.billboard = raw["billboard"]   # True | "mesh"
        if isinstance(raw.get("text3d"), dict):
            group.text3d = dict(raw["text3d"])
        if isinstance(raw.get("ext"), dict):
            group.ext = raw["ext"]
        if raw.get("uid"):
            group.uid = str(raw["uid"])   # older documents keep the fresh one
        if raw.get("hidden"):
            group.hidden = True
        if raw.get("locked"):
            group.locked = True
        if isinstance(raw.get("material"), dict):
            group.material = dict(raw["material"])
        if isinstance(raw.get("exploded"), dict):
            group.exploded = dict(raw["exploded"])
        off = raw.get("explode_offset")
        if isinstance(off, list) and len(off) == 3:
            group.explode_offset = tuple(float(v) for v in off)
        if depth < 32:              # a corrupt document must not spin
            group.adopt(_group_from(c, depth + 1)
                        for c in raw.get("children", []) or [])
        if "component" in raw:
            group.component = bool(raw["component"])
        elif any(isinstance(c, dict) and "xform" not in c
                 for c in raw.get("children", []) or []):
            # Saved before the key existed (issue #90): a container holding
            # a CLASSIC group can only be Make Group's — a .skp import
            # places every child with a matrix. A group, then.
            group.component = False
        return group

    raw_groups = payload.get("groups", []) or []
    for i, raw in enumerate(raw_groups):
        if i % 50 == 0:
            tick(0.6 + 0.35 * i / max(1, len(raw_groups)), "Placing groups…")
        scene.groups.append(_group_from(raw))
    scene.kept_components = [
        t for t in (_group_from(raw) for raw in
                    payload.get("kept_components", []) or []
                    if isinstance(raw, dict))
        if t.is_component()]
    tick(0.96, "Finishing…")
    if names:
        from core.group import reserve_group_names
        reserve_group_names(names)   # new groups never reuse a stored "Group N"

    for raw in payload.get("dimensions", []):
        dim = Dimension(
            QVector3D(*raw["a"]), QVector3D(*raw["b"]),
            QVector3D(*raw["offset"]), layer=raw.get("layer") or None,
            text=raw.get("text") or None, axis=raw.get("axis") or None)
        dim.bind(scene)         # the vertex at that spot is the one snapped to
        scene.dimensions.append(dim)

    # A document from before the ends could be chosen drew oblique ticks:
    # it keeps them. Only a NEW document is born with arrows.
    style = payload.get("dimension_style")
    scene.dimension_style.update(
        {"ends": "tick", **(style if isinstance(style, dict) else {})})
    cam = payload.get("camera")
    scene.camera_home = dict(cam) if isinstance(cam, dict) else None
    from core.units import model_units_of
    scene.units = model_units_of(payload)   # validated; absent = metres
    pdata = payload.get("plugin_data")
    scene.plugin_data = dict(pdata) if isinstance(pdata, dict) else {}
    scales = payload.get("custom_scales")
    if isinstance(scales, list):
        scene.custom_scales = [float(n) for n in scales
                               if isinstance(n, (int, float)) and n > 0]

    back = payload.get("back_face_color")
    if isinstance(back, list) and len(back) == 3:
        scene.back_face_color = tuple(float(c) for c in back)

    # Defaults stay implicit in the file (terse), so a document WITHOUT the
    # block must reset the field — otherwise the previous document's look or
    # sun leaks into the one being opened.
    from core.style import Style
    dstyle = payload.get("display_style")
    scene.display_style = (Style.from_dict(dstyle)
                           if isinstance(dstyle, dict) else Style())

    from core.sun import ShadowSettings
    shadows = payload.get("shadows")
    scene.shadows = (ShadowSettings.from_dict(shadows)
                     if isinstance(shadows, dict) else ShadowSettings())

    raw_planes = payload.get("section_planes")
    if isinstance(raw_planes, list):
        from core.section import SectionPlane
        scene.section_planes = [SectionPlane.from_dict(r)
                                for r in raw_planes]
        # One active cut max: keep the FIRST marked active.
        seen_active = False
        for sp in scene.section_planes:
            if sp.active and seen_active:
                sp.active = False
            seen_active = seen_active or sp.active
    vis = payload.get("section_view")
    if isinstance(vis, dict):
        scene.show_section_planes = not vis.get("planes_hidden", False)
        scene.show_section_cuts = not vis.get("cuts_hidden", False)
    shown = payload.get("hidden_view")
    if isinstance(shown, dict):
        scene.show_hidden_objects = bool(shown.get("objects", False))
        scene.show_hidden_geometry = bool(shown.get("geometry", False))
    scene.show_axes = not bool(payload.get("axes_hidden", False))

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
        # A guide at (nan, nan, nan) stalled every tool (#185): left out.
        if not _finite_points(raw.get("point", ()),
                              raw.get("direction") or (),
                              raw.get("origin") or ()):
            _dropped_nonfinite[0] += 1
            continue
        scene.guides.append(Guide.from_dict(raw))
    # What had to be left out, for the window to say so.
    scene.load_repairs = _dropped_nonfinite[0]

    from core.image_plane import ImagePlane
    scene.image_planes.clear()
    for raw in payload.get("image_planes", []):
        scene.image_planes.append(ImagePlane.from_dict(raw))

    if progress is not None:
        _release_in_steps(data, lambda: tick(0.98, "Finishing…"))
    data = payload = None
    scene.version += 1


def _bulky(node) -> bool:
    """A container worth taking apart before dropping: a long list, or a
    dict holding one (a group, a prototype, the scene). Coordinates and
    small face records just go with their parent."""
    if isinstance(node, list):
        return len(node) > 64
    if isinstance(node, dict):
        return any(isinstance(v, (list, dict)) and len(v) > 64
                   for v in node.values())
    return False


def _release_in_steps(data, pump) -> None:
    """Drop the parsed document a slice at a time, ``pump()`` between
    slices. Released in one go when the loader returned, the JSON tree of
    a 3.3 GB document — tens of millions of objects — kept the window from
    answering for 8 s, long enough for the desktop to call IngeTrazo «not
    responding» (#158)."""
    import time
    last = time.monotonic()
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in list(node):
                child = node.pop(key)
                if _bulky(child):
                    stack.append(child)
        elif isinstance(node, list):
            while node:
                child = node.pop()
                if _bulky(child):
                    stack.append(child)
                if time.monotonic() - last > 0.25:
                    pump()
                    last = time.monotonic()
        if time.monotonic() - last > 0.25:
            pump()
            last = time.monotonic()


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
    if raw.get("hidden"):
        attrs["hidden"] = True
    if raw.get("mat"):
        attrs["mat"] = raw["mat"]
    back = raw.get("back")
    if isinstance(back, dict):
        attrs["back"] = dict(back)
    elif back is True:
        attrs["back"] = True
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
        if raw.get("hidden"):
            edge.hidden = True
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


def _load_mesh(mesh, payload, geom=None) -> None:
    """Rebuild a mesh from its JSON block in ONE bulk pass: every edge
    endpoint and face corner welds through :meth:`Mesh.bulk_weld` at once,
    then the edges and faces are created vectorized — the per-entity
    ``add_edge``/``add_face`` walk dominated opening big documents. Small
    groups take the plain walk (the bulk pass's fixed cost loses there).
    A format-3 block (``"geom"``) is read from ``geom``, the document's
    binary members."""
    import numpy as np
    import core.mesh as _mesh_mod
    from core.topology import _maximal_holes

    if "geom" in payload:
        _load_geometry(mesh, payload["geom"], geom or {})
        return

    payload = _without_nonfinite(payload)
    raw_edges = payload.get("edges", [])
    raw_faces = payload.get("faces", [])
    if not _bulk_sized(len(raw_edges), len(raw_faces)):
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
            flags.append((bool(raw.get("soft")), cid, raw.get("layer"),
                          bool(raw.get("hidden"))))
        emap = mesh.add_edges_welded(
            vobjs, inverse[0:n_edge_pts:2], inverse[1:n_edge_pts:2], flags)
        # Keep new curves unique after loading stored ids.
        if max_curve is not None and max_curve >= _mesh_mod._CURVE_COUNTER:
            _mesh_mod._CURVE_COUNTER = max_curve + 1
    if ring_counts:
        mesh.add_faces_welded(vobjs, inverse[n_edge_pts:], ring_sizes,
                              ring_counts, attrs_list, edge_map=emap)


def _geometry_arrays(meta, blob: bytes) -> dict:
    """The arrays of a format-3 block, checked: known dtypes, inside the
    blob, and every index pointing at something that exists. A damaged or
    crafted document fails with a ValueError instead of building garbage."""
    import numpy as np

    def bad(why):
        return ValueError(f"damaged geometry block ({why})")

    layout = meta.get("arrays") if isinstance(meta, dict) else None
    if not isinstance(layout, dict):
        raise bad("no layout")
    out = {}
    for name, spec in layout.items():
        try:
            dtype, shape, offset = spec
            shape = tuple(int(n) for n in shape)
            offset = int(offset)
        except (TypeError, ValueError):
            raise bad(name) from None
        if dtype not in _GEOM_DTYPES or offset < 0 or any(n < 0 for n in shape):
            raise bad(name)
        count = 1
        for n in shape:
            count *= n
        size = count * np.dtype(dtype).itemsize
        if offset + size > len(blob):
            raise bad(name)
        out[name] = np.frombuffer(blob, dtype=dtype, count=count,
                                  offset=offset).reshape(shape)
    for name in ("pos", "edges", "rings", "ring_sizes", "ring_counts",
                 "face_attr", "edge_flags"):
        if name not in out:
            raise bad(f"missing {name}")
    pos = out["pos"]
    nv = len(pos)
    ne = len(out["edges"])
    if pos.ndim != 2 or pos.shape[1] != 3:
        raise bad("pos")
    if out["edges"].ndim != 2 or out["edges"].shape[1] != 2:
        raise bad("edges")
    for name in ("edges", "rings"):
        a = out[name]
        if a.size and (a.min() < 0 or a.max() >= nv):
            raise bad(name)
    sizes, counts = out["ring_sizes"], out["ring_counts"]
    if (sizes.size and sizes.min() < 1) or (counts.size and counts.min() < 1):
        raise bad("rings")
    if int(sizes.sum()) != len(out["rings"]) or int(counts.sum()) != len(sizes):
        raise bad("rings")
    n_attrs = len(meta.get("face_attrs") or ())
    fa = out["face_attr"]
    if len(fa) != len(counts) or (fa.size and (fa.min() < -1
                                               or fa.max() >= n_attrs)):
        raise bad("face_attr")
    n_layers = len(meta.get("edge_layers") or ())
    for name in ("edge_flags", "edge_curve", "edge_layer"):
        if name in out and len(out[name]) != ne:
            raise bad(name)
    el = out.get("edge_layer")
    if el is not None and el.size and (el.min() < -1 or el.max() >= n_layers):
        raise bad("edge_layer")
    return out


def _document_geometry_arrays(meta, geom: dict) -> dict:
    """Read and validate a mesh's referenced format-3 geometry block."""
    member = meta.get("member") if isinstance(meta, dict) else None
    blob = geom.get(member)
    if blob is None:
        raise ValueError(f"the document lost its geometry block {member!r}")
    return _geometry_arrays(meta, blob)


def _load_geometry(mesh, meta, geom: dict) -> None:
    """Rebuild a mesh from its format-3 block — the same weld and the same
    bulk edge/face creation as the JSON path, fed from arrays."""
    import numpy as np
    import core.mesh as _mesh_mod

    a = _document_geometry_arrays(meta, geom)
    pos = a["pos"]
    edges, rings = a["edges"], a["rings"]
    sizes, counts = a["ring_sizes"], a["ring_counts"]
    face_attr = a["face_attr"]
    flags, curves, layers = (a["edge_flags"], a.get("edge_curve"),
                             a.get("edge_layer"))

    bad = ~np.isfinite(pos).all(axis=1)
    if bad.any():
        # Never written by this build (it refuses to save such a point),
        # but a damaged document opens like a JSON one: the pieces touching
        # the bad points are left out and counted (#185).
        keep_e = ~(bad[edges[:, 0]] | bad[edges[:, 1]])
        ring_bad = np.add.reduceat(bad[rings].astype(np.int64),
                                   np.cumsum(sizes) - sizes) > 0 \
            if len(sizes) else np.zeros(0, dtype=bool)
        face_bad = np.add.reduceat(ring_bad.astype(np.int64),
                                   np.cumsum(counts) - counts) > 0 \
            if len(counts) else np.zeros(0, dtype=bool)
        _dropped_nonfinite[0] += int((~keep_e).sum() + face_bad.sum())
        edges, flags = edges[keep_e], flags[keep_e]
        curves = curves[keep_e] if curves is not None else None
        layers = layers[keep_e] if layers is not None else None
        ring_face = np.repeat(np.arange(len(counts)), counts)
        keep_r = ~face_bad[ring_face]
        rings = rings[np.repeat(keep_r, sizes)]
        sizes, counts = sizes[keep_r], counts[~face_bad]
        face_attr = face_attr[~face_bad]
    if not len(pos) or not (len(edges) or len(counts)):
        return

    vobjs, inverse = mesh.bulk_weld(pos.astype(np.float64))
    emap = None
    if len(edges):
        eflags = None
        if flags.any() or curves is not None or layers is not None:
            names = meta.get("edge_layers") or []
            soft = (flags & 1).astype(bool).tolist()
            hidden = (flags & 2).astype(bool).tolist()
            cl = (curves.tolist() if curves is not None
                  else [-1] * len(edges))
            ll = (layers.tolist() if layers is not None
                  else [-1] * len(edges))
            eflags = [(s, c if c >= 0 else None, names[l] if l >= 0 else None,
                       h) for s, c, l, h in zip(soft, cl, ll, hidden)]
            if curves is not None and curves.size:
                top = int(curves.max())
                if top >= _mesh_mod._CURVE_COUNTER:
                    _mesh_mod._CURVE_COUNTER = top + 1
        emap = mesh.add_edges_welded(vobjs, inverse[edges[:, 0]],
                                     inverse[edges[:, 1]], eflags)
    if len(counts):
        table = meta.get("face_attrs") or []
        attrs = [_face_attrs_from_json(table[k]) if k >= 0 else None
                 for k in face_attr.tolist()]
        mesh.add_faces_welded(vobjs, inverse[rings], sizes, counts, attrs,
                              edge_map=emap)
